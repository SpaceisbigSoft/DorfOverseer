"""(0.105.35, gates) The player: nothing waits for them. In planner_gates
every Needs you that handed the AI's work to the player is now the AI's own
act, or a plain note of what it does, or (only where the game won't let it)
a Needs you that says what the AI does meanwhile:

- a cavern's stuck gate: step 2 once the caverns read safe (cavern_ok);
  (v35) never step 3 there;
- citizens behind a gate the AI didn't shut: (v35) a way dug in (the player's
  gate never opened); down in the caverns behind the AI's shut gate: their
  entrance opened (open_entrance, cavern_ok);
- cut off with no way in: said when the AI digs (refused: every 8 days, never
  given up);
- the gate watcher failing: close_threatened_gates shuts what an enemy is near;
- a planned gate waiting with parts free: free_gate_jobs;
- refused builds, the second way, wide entrances with the Rules switch off:
  plain notes.

    python tests/test_r35_gates.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))

from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

_src = (ROOT / "tests" / "test_r32_gatesplit.py").read_text(encoding="utf-8")
_ns: dict = {"module_src": module_src, "sys": sys}
exec(compile(_src[_src.index("try:\n    from lupa"):_src.index("\ndef lst")], "r32rig", "exec"), _ns)
_bsrc = (ROOT / "tests" / "test_r32_brain.py").read_text(encoding="utf-8")
_bns: dict = {"__name__": "r32brain", "__file__": str(ROOT / "tests" / "test_r32_brain.py")}
exec(compile(_bsrc[:_bsrc.index("# --- E's case")], "r32brain", "exec"), _bns)

import planner_core  # noqa: E402
import overseer  # noqa: E402
from planner import Memory, plan  # noqa: E402
import test_r33_fix_gates as F  # noqa: E402

fort, cycle, later, acts, answer, HOUR = (_bns[k] for k in ("fort", "cycle", "later", "acts", "answer", "HOUR"))
LUA = _ns["LUA"]


def needs_you(notes):
    return [n for n in notes if n.startswith(("[you]", "Needs you"))]


def safe_caverns(s):
    s["deep"] = {"caverns": [], "dangers": []}
    return s


# --- brain ------------------------------------------------------------------------------

@test("a cavern's stuck gate, the caverns read safe: step 2 with cavern_ok, never step 3 (v35); no Needs you until every step is tried")
def _():
    m = Memory()
    s = safe_caverns(fort())
    s["entrances"]["entrances"][0]["kind"] = "cavern"
    p1 = acts(cycle(s, m)[0], "gate_stuck")[0]
    assert p1.action == {"type": "unstick_gate", "id": 7, "step": 1}, p1.action
    answer(s, m, p1, split_after=True)
    s2 = safe_caverns(later(s, 6 * HOUR + 10, rescan=True))
    props, notes = cycle(s2, m)
    p2 = acts(props, "gate_stuck")
    assert p2 and p2[0].action == {"type": "unstick_gate", "id": 7, "step": 2, "cavern_ok": True}, props
    assert not [n for n in needs_you(notes) if "building 7" in n], notes
    answer(s2, m, p2[0], split_after=True)
    # (v35 fix) never taken down (step 3) on a cavern's way: step 2 is the last
    # every step tried, still out, on a cavern's way: the one kept Needs you (no way in from a cavern)
    props, notes = cycle(safe_caverns(later(s, 12 * HOUR + 20, rescan=True)), m)
    assert not acts(props, "gate_stuck"), props
    ny = [n for n in needs_you(notes) if "building 7" in n]
    assert ny and "digs no way in from a cavern" in ny[0] and "yourself" not in ny[0], notes


@test("a surface stuck gate, every step tried or the player's own: a plain note that the AI digs a way in")
def _():
    m = Memory()
    s = fort()
    m.gate_unstick["7"] = {"step": 3, "tick": planner_core.abs_tick(s) - 7 * HOUR, "ok": False,
                           "split_after": None, "done": "this gate is the player's own (no \"AI gate\" lever works it)"}
    props, notes = cycle(s, m)
    assert acts(props, "way_in", "dig_way_in"), props
    line = [n for n in notes if "building 7" in n and "shut outside by" in n]
    assert line and "player's own gate" in line[0] and "digs them a way in instead" in line[0], notes
    assert not needs_you([n for n in notes if "building 7" in n]), notes


@test("a gate not shut by the AI: (v35) never opened, a way dug in; an enemy 8 tiles off: kept shut and said; never a Needs you")
def _():
    s = F.stranded_state({"invader": False, "pos": {"x": 10, "y": 150, "z": 173}})
    s["entrances"]["armed"] = False
    for r in s["entrances"]["stranded"]:
        r.update(cause="gate_shut", by_ai=False)
    props, notes = plan(s, Memory())
    assert not [p for p in props if p.rule == "stranded"], props
    assert [p.action["type"] for p in props if p.rule == "way_in"] == ["dig_way_in"], props
    assert [n for n in notes if "the gate is the player's" in n and "digs them a way in" in n], notes
    assert not [n for n in needs_you(notes) if "shut outside" in n], notes
    for r in s["entrances"]["stranded"]:
        r["gate_danger"] = 8
        r["danger_near"] = 40
    props, notes = plan(s, Memory())
    assert not [p for p in props if p.rule == "stranded"], props
    assert [n for n in notes if "enemy is 8 tiles away" in n], notes
    assert not [n for n in needs_you(notes) if "shut outside" in n], notes


@test("down in the caverns behind the AI's shut gate, the caverns safe: open_entrance with cavern_ok")
def _():
    s = safe_caverns(F.stranded_state({"invader": False, "pos": {"x": 10, "y": 150, "z": 173}}))
    for r in s["entrances"]["stranded"]:
        r.update(in_cavern=True, entrance={"id": 2, "kind": "cavern", "x": 150, "y": 20, "z": 173})
    props, notes = plan(s, Memory())
    got = [p.action for p in props if p.rule == "stranded"]
    assert got == [{"type": "open_entrance", "id": 2, "cavern_ok": True}], (got, notes)
    assert not [n for n in needs_you(notes) if "caverns" in n], notes


@test("the gate watcher failing with a threat that can reach the dwarves: close_threatened_gates, a plain note")
def _():
    s = F.stranded_state({"invader": True, "can_reach_dwarves": True, "pos": {"x": 150, "y": 30, "z": 173},
                          "distance_to_nearest_dwarf": 10})
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    s["entrances"]["stranded"] = []
    s["entrances"]["watch_error"] = {"n": 3, "error": "boom", "tick": 1}
    props, notes = plan(s, Memory())
    g = [p.action for p in props if p.rule == "gates"]
    assert {"type": "close_threatened_gates"} in g, [(p.rule, p.action) for p in props]
    line = [n for n in notes if "gate watcher failed 3 time(s)" in n]
    assert line and "shuts each gate an enemy comes within 12 tiles of itself" in line[0], notes
    assert not needs_you(line) and "by hand" not in line[0], line


def closing_fort(days):
    s = fort(split=False, stranded=0)
    e = s["entrances"]["entrances"][0]
    e.update(sealed=False, closing=True, waiting={"hatch": 1}, closing_days=days, equipment=[])
    s["entrances"]["parts"] = {"hatch_covers": 2, "doors": 0}
    return s


@test("a hatch planned a week with covers free: free_gate_jobs and one more made, a plain note; two weeks: the kept Needs you")
def _():
    m = Memory()
    props, notes = cycle(closing_fort(8), m)
    fj = acts(props, "gate_jobs", "free_gate_jobs")
    assert fj and fj[0].action == {"type": "free_gate_jobs", "entrance_id": 1}, [(p.rule, p.action) for p in props]
    line = [n for n in notes if "has waited 8 days" in n]
    assert line and "suspended building job resumed" in line[0] and not needs_you(line), notes
    assert "check its job" not in " ".join(notes)
    props, notes = cycle(closing_fort(15), Memory())
    ny = [n for n in needs_you(notes) if "has waited 15 days" in n]
    assert ny and "the AI keeps it planned" in ny[0], notes


@test("refused builds and the second way said as what the AI does; wide entrances with walling off: a plain note")
def _():
    s = fort(split=False, stranded=0)
    s["entrances"]["entrances"][0].update(sealed=False, closing=False, width=80, door_spots=0, kind="surface")
    s["settings"]["fortify_entrances"] = False
    props, notes = cycle(s, Memory())
    line = [n for n in notes if "can't be closed with doors" in n]
    assert line and "off on the Rules tab" in line[0] and not needs_you(line), notes
    assert "wall them down" not in " ".join(notes)
    # the second way dug and still one surface entrance: the AI's own stop, said plainly
    s = fort(split=False, stranded=0)
    s["dwarves"]["total"] = 40
    now = planner_core.abs_tick(s)
    m = Memory()
    m.second_way = {"ok": True, "tick": now - 61 * 1200, "rescanned": now - 60 * 1200, "project_id": 9}
    notes = cycle(s, m)[1]
    line = [n for n in notes if "second way to the surface was dug" in n]
    assert line and "digs no more second ways" in line[0] and not needs_you(line), notes
    assert "yourself" not in line[0]


@test("no Needs you in planner_gates tells the player to do what the AI does")
def _():
    src = (ROOT / "brain" / "planner_gates.py").read_text(encoding="utf-8")
    for bad in ("open it yourself", "build there yourself", "dig or build them a way in", "close the gates by hand",
                "check its job isn't suspended", "open a second way out yourself", ": open it\")",
                "take the {kind} down or dig them a way in", "look at the gates for dwarves left out"):
        assert bad not in src, bad


@test("words: the panel's short words for the two new actions")
def _():
    for k in ("close_threatened_gates", "free_gate_jobs"):
        assert overseer.SHORT_WORDS.get(k), k


# --- lua ---------------------------------------------------------------------------------

@test("lua: close_threatened_gates shuts only an entrance with an enemy within 12 tiles; dry run changes nothing")
def _():
    E, G = _ns["rig"]()
    t = LUA.table_from
    r = E.close_threatened_gates(False)
    assert not r.ok and r.waiting and "within 12 tiles" in r.error, dict(r)
    G.units[1] = t({"id": 99, "danger": True, "flags1": t({"caged": False, "chained": False}),
                    "pos": t({"x": 112, "y": 149, "z": 171})})
    r = E.close_threatened_gates(True)
    assert r.ok and r.dry_run and not G.blds[7].door_flags.closed and len(list(G.pulled.values())) == 0, dict(r)
    r = E.close_threatened_gates(False)
    assert r.ok and list(r.entrances.values()) == [1] and G.blds[7].door_flags.closed and E.GATES.closed[1], dict(r)
    r = E.close_threatened_gates(False)        # already shut: nothing more
    assert not r.ok, dict(r)


@test("lua: free_gate_jobs unsuspends the planned pieces' jobs; dry run counts only; none suspended: refused")
def _():
    E, G = _ns["rig"]()
    t = LUA.table_from
    job = t({"flags": t({"suspend": True})})
    G.blds[50] = t({"id": 50, "x1": 30, "y1": 31, "x2": 30, "y2": 31, "z": 170, "jobs": t([job])})
    E.GATES.entrances[1].pending_ids = t([50])
    E.note_gate_planned(t({"x": 30, "y": 31, "z": 170}))      # (v35) the AI planned it
    r = E.free_gate_jobs(1, True)
    assert r.ok and r.unsuspended == 1 and job.flags.suspend, dict(r)
    r = E.free_gate_jobs(1, False)
    assert r.ok and r.unsuspended == 1 and not job.flags.suspend, dict(r)
    r = E.free_gate_jobs(1, False)
    assert not r.ok and "no suspended job" in r.error, dict(r)
    assert not E.free_gate_jobs(5, False).ok


@test("lua: open_entrance on a cavern entrance only with cavern_ok")
def _():
    E, G = _ns["rig"]()
    E.GATES.entrances[1].kind = "cavern"
    G.blds[7].door_flags.closed = True
    E.GATES.closed[1] = True
    r = E.open_entrance(1, False)
    assert not r.ok and "cavern" in r.error, dict(r)
    r = E.open_entrance(1, False, True)
    assert r.ok and not G.blds[7].door_flags.closed, dict(r)


@test("lua: unstick_gate step 2 on a cavern's way refused without cavern_ok, done with it")
def _():
    E, G = _ns["rig"]()
    E.GATES.entrances[1].kind = "cavern"
    r = E.unstick_gate(7, 2, False)
    assert not r.ok and r.cavern, dict(r)
    r = E.unstick_gate(7, 2, False, True)
    assert not r.cavern and r.step == 2, dict(r)
    assert len(list(G.pulled.values())) == 2, list(G.pulled.values())


@test("lua: the two new actions are in ACTIONS and DRY_OK; everything compiles under 5.3")
def _():
    br = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    acts_ = br[br.index("ACTIONS = {"):br.index("DRY_OK = {}")]
    dry = br[br.index("DRY_OK = {}"):br.index("}) do DRY_OK[name] = true end")]
    for k in ("close_threatened_gates", "free_gate_jobs"):
        assert f"{k} = act_{k}" in acts_ and f"'{k}'" in dry, k
    L = _ns["LuaRuntime"]()
    for p in sorted((ROOT / "lua").glob("*.lua")) + sorted((ROOT / "lua" / "gui").glob("*.lua")):
        ok, err = L.eval("function(src, n) local f, e = load(src, n, 't', {}); return f ~= nil, e end")(
            p.read_text(encoding="utf-8"), p.name)
        assert ok, (p.name, err)


if __name__ == "__main__":
    finish()
