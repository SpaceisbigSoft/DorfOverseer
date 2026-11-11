"""(0.105.36, gates) The focused audit's fixes in lua/ai-gates.lua and
brain/planner_gates.py (D2, X1):

- an AI bridge still being opened is saved with `opening` and comes back the
  AI's after a reload; re-arming keeps it too (it was read as the player's);
- open_entrance's seal and great-danger refusals are waiting (no back-off),
  and a waiting refusal of the stranded is looked at again after the rule's
  cooldown;
- close_threatened_gates shuts a real (sealed: the scan's) entrance;
- one citizen near an enemy no longer holds every entrance: the AI's gate is
  judged per entrance at 12 tiles;
- a cancelled way in is not "dug already" (and the strategist can't cancel it);
- free_gate_jobs: pieces planned before v35 at an entrance the AI fortified,
  and records by building id, forgotten once built or gone;
- the second way not behind routine work once citizens were stranded;
- shared_lever_row (dead) gone.

    python tests/test_r36_gates.py
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
import planner_gates  # noqa: E402
from planner import Memory, plan, record  # noqa: E402
from planner_core import Proposal, TICKS_PER_DAY, note_refusal, refusal_key  # noqa: E402
import test_r33_fix_gates as F  # noqa: E402

fort, cycle, later, acts = (_bns[k] for k in ("fort", "cycle", "later", "acts"))
LUA = _ns["LUA"]
t = LUA.table_from


def bridge_rig(raised=True, occupied=False):
    """Entrance 1's gate: the AI's drawbridge 9 on its lever 137; a pull flips it at once."""
    E, G = _ns["rig"]()
    G.blds[9] = t({"id": 9, "x1": 108, "y1": 149, "x2": 108, "y2": 149, "z": 171, "jobs": t({}),
                   "gate_flags": t({"raised": raised, "raising": False, "lowering": False})})
    br = t({"id": 9, "kind": "bridge", "lever_id": 137, "x1": 108, "y1": 149, "x2": 108, "y2": 149, "z": 171})
    E.GATES.entrances[1].equipment = t([br])
    E.bridge_occupied = LUA.eval("function() return %s end" % ("true" if occupied else "false"))
    LUA.execute("CR_OK = CR_OK or 0")
    E.dfhack.run_command_silent = LUA.eval("""function(G) return function(_, _, _, id)
        table.insert(G.pulled, tonumber(id))
        local f = G.blds[9].gate_flags; f.raised = not f.raised
        return '', CR_OK end end""")(G)
    return E, G


def reload(E, G):
    G.saved[E.GATES_SAVE_KEY] = E.gates_snapshot()
    ent = E.GATES.entrances
    E.GATES_SAVE = t({})
    E.GATES = t({"scanned": True, "inside": E.GATES.inside, "entrances": ent, "closed": t({})})
    E.gates_restore()


# --- lua ---------------------------------------------------------------------------------

@test("D2: a bridge still opening when saved comes back the AI's (closed + opening), lowered once clear")
def _():
    for armed in (False, True):
        E, G = bridge_rig(occupied=True)
        E.GATES.closed = t({1: True})
        E.GATES_ORIG.open_all()
        if armed:
            E.GATES_ORIG.arm()
        snap = E.gates_snapshot()
        assert [(g.id, g.opening) for g in snap.gates.values()] == [(9, True)], list(snap.gates.values())
        reload(E, G)
        assert E.GATES.closed[1] and E.GATES.opening[1] and len(G.pulled) == 0, armed
        assert bool(E.GATES.armed) == armed
        E.bridge_occupied = LUA.eval("function() return false end")
        if armed:
            E.GATES_ORIG.check()
        else:
            E.GATES_ORIG.open_all()
        assert list(G.pulled.values()) == [137] and not G.blds[9].gate_flags.raised, armed


@test("D2: re-arming keeps an entrance still being opened; the watcher's look lowers it")
def _():
    E, G = bridge_rig(occupied=True)
    E.GATES.closed = t({1: True})
    E.GATES_ORIG.open_all()
    E.GATES_ORIG.arm()
    assert E.GATES.closed[1] and E.GATES.opening[1]
    E.bridge_occupied = LUA.eval("function() return false end")
    E.GATES_ORIG.check()
    assert list(G.pulled.values()) == [137] and not G.blds[9].gate_flags.raised
    E.GATES_ORIG.check()
    assert not E.GATES.closed[1] and list(G.pulled.values()) == [137]


@test("D2: open_entrance's seal and great-danger refusals are waiting (no back-off)")
def _():
    E, G = _ns["rig"]()
    E.GATES.closed[1] = True
    G.units[1] = t({"id": 99, "danger": True, "great": True, "flags1": t({"caged": False, "chained": False}),
                    "pos": t({"x": 10, "y": 10, "z": 171})})
    E.dfhack.units.isGreatDanger = LUA.eval("function(u) return u.great == true end")
    r = E.open_entrance(1, False)
    assert not r.ok and r.waiting and "great danger" in r.error, dict(r)
    E.seal_holds = LUA.eval("function() return {ids = {[7] = true}, levers = {}} end")
    r = E.open_entrance(1, False)
    assert not r.ok and r.waiting and "seal" in r.error, dict(r)


@test("X1: close_threatened_gates shuts a sealed (scanned) entrance, and one still being opened")
def _():
    E, G = _ns["rig"]()
    assert E.GATES.entrances[1].sealed is True
    G.units[1] = t({"id": 99, "danger": True, "flags1": t({"caged": False, "chained": False}),
                    "pos": t({"x": 112, "y": 149, "z": 171})})
    r = E.close_threatened_gates(False)
    assert r.ok and G.blds[7].door_flags.closed and E.GATES.closed[1], dict(r)
    E2, G2 = bridge_rig(raised=False)
    E2.GATES.closed, E2.GATES.opening = t({1: True}), t({1: True})
    G2.units[1] = t({"id": 99, "danger": True, "flags1": t({"caged": False, "chained": False}),
                     "pos": t({"x": 112, "y": 149, "z": 171})})
    r = E2.close_threatened_gates(False)
    assert r.ok and G2.blds[9].gate_flags.raised and not E2.GATES.opening[1], dict(r)


@test("D2: free_gate_jobs: a piece with no record at an entrance the AI fortified is the AI's (ai_plan); "
      "a record of another building there still isn't; records of built pieces forgotten")
def _():
    E, G = _ns["rig"]()
    job = t({"flags": t({"suspend": True})})
    G.blds[50] = t({"id": 50, "x1": 30, "y1": 31, "x2": 30, "y2": 31, "z": 170, "jobs": t([job]),
                    "getBuildStage": LUA.eval("function() return 0 end"),
                    "getMaxBuildStage": LUA.eval("function() return 1 end")})
    E.GATES.entrances[1].pending_ids = t([50])
    E.df["global"].building_next_id = 60        # (0.105.36 fix) the records began after building 50
    assert not E.free_gate_jobs(1, False).ok and job.flags.suspend                  # unknown: the player's
    r = E.free_gate_jobs(1, False, True)
    assert r.ok and r.unsuspended == 1 and not job.flags.suspend, dict(r)
    # a record with another building's id on that tile: not the AI's even with ai_plan
    job.flags.suspend = True
    G.saved[E.GATE_PLANNED_KEY] = t({"tiles": t(["30,31,170@77"])})
    G.blds[77] = t({"id": 77, "getBuildStage": LUA.eval("function() return 0 end"),
                    "getMaxBuildStage": LUA.eval("function() return 1 end")})
    r = E.free_gate_jobs(1, False, True)
    assert not r.ok and job.flags.suspend, dict(r)
    # its own id: the AI's
    G.saved[E.GATE_PLANNED_KEY] = t({"tiles": t(["30,31,170@50"])})
    assert E.free_gate_jobs(1, False).ok and not job.flags.suspend
    # built (or gone): the record forgotten
    G.blds[77].getBuildStage = LUA.eval("function() return 1 end")
    kept = E.prune_gate_planned(t(["30,31,170@50", "1,2,3@77", "4,5,6@999"]))
    assert list(kept.values()) == ["30,31,170@50"], list(kept.values())
    acts_src = (ROOT / "lua" / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    assert "free_gate_jobs(id, a.dry_run == true, a.ai_plan == true)" in acts_src


# --- brain ------------------------------------------------------------------------------

def two_gates(gd_a, gd_b):
    s = F.stranded_state({"invader": True, "can_reach_dwarves": True, "pos": {"x": 10, "y": 150, "z": 173}})
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    ent = s["entrances"]
    e2 = dict(ent["entrances"][0])
    e3 = dict(e2, id=3, x=60)
    ent["entrances"] = [e2, e3]
    r2, r3 = (dict(r) for r in ent["stranded"])
    r2.update(gate_danger=gd_a, danger_near=gd_a)
    r3.update(id=99, x=62, gate_danger=gd_b, danger_near=gd_b,
              entrance={"id": 3, "kind": "surface", "x": 60, "y": 20, "z": 173})
    ent["stranded"] = [r2, r3]
    return s


@test("X1: an enemy 20 tiles from gate A doesn't hold gate B; each gate judged at 12 tiles")
def _():
    props, notes = plan(two_gates(20, 100), Memory())
    got = [p.action for p in props if p.rule == "stranded"]
    assert got == [{"type": "open_entrance", "id": 2}, {"type": "open_entrance", "id": 3}], (got, notes)
    for gd, want in ((5, False), (12, False), (13, True), (30, True)):
        props, notes = plan(two_gates(gd, 100), Memory())
        ids = [p.action.get("id") for p in props if p.rule == "stranded"]
        assert (2 in ids) == want and 3 in ids, (gd, ids)
    # no siege, an enemy 20 tiles from them: their gate alone (open_gates would disarm the watcher)
    s = F.stranded_state({"pos": {"x": 10, "y": 150, "z": 173}})
    for r in s["entrances"]["stranded"]:
        r.update(gate_danger=20, danger_near=20)
    got = [p.action for p in plan(s, Memory())[0] if p.rule == "stranded"]
    assert got == [{"type": "open_entrance", "id": 2}], got


@test("X1: a waiting refusal of open_entrance looked at again after the stranded cooldown, not 2 days")
def _():
    s = two_gates(100, 100)
    m = Memory()
    p = Proposal("stranded", {"type": "open_entrance", "id": 2}, "", 0)
    now = planner_core.abs_tick(s)
    note_refusal(m, p, {"ok": False, "waiting": True, "error": "a great danger is in sight"}, now - 100)
    planner_gates._stranded_relook(m, p, s, planner_core.PLANNER_CONFIG)
    assert refusal_key(p) in m.refusals                          # within the cooldown: kept
    note_refusal(m, p, {"ok": False, "waiting": True, "error": "a great danger is in sight"}, now - 400)
    planner_gates._stranded_relook(m, p, s, planner_core.PLANNER_CONFIG)
    assert refusal_key(p) not in m.refusals
    m.refusals[refusal_key(p)] = {"n": 2, "until": now + 9 * TICKS_PER_DAY, "at": now - 400}
    planner_gates._stranded_relook(m, p, s, planner_core.PLANNER_CONFIG)
    assert refusal_key(p) in m.refusals                          # a real back-off: kept


@test("X1: a cancelled way in is a refusal there (dug again after the back-off), not 'already dug'")
def _():
    s = fort(split=False, stranded=3, cause="no_path", out_ticks=2400, group=900)
    for r in s["entrances"]["stranded"]:
        r.pop("entrance", None)
    m = Memory()
    w = acts(cycle(s, m)[0], "way_in")[0]
    record([(w, {"ok": True, "project_id": 55})], s, m)
    s2 = later(s, 2 * TICKS_PER_DAY)
    s2["registry"] = [{"id": 55, "kind": "way_in", "phase": "cancelled"}]
    props, notes = cycle(s2, m)
    assert not acts(props, "way_in") and not [n for n in notes if "already dug" in n], notes
    rec = next(iter(m.way_in.values()))
    assert rec["ok"] is False and "cancelled" in rec["why"] and rec["refusals"] == 1, m.way_in
    props, notes = cycle(later(s2, TICKS_PER_DAY + 10), m)
    assert acts(props, "way_in", "dig_way_in"), notes
    # done (not cancelled): still "dug already" as before
    m = Memory()
    w = acts(cycle(s, m)[0], "way_in")[0]
    record([(w, {"ok": True, "project_id": 56})], s, m)
    s3 = later(s, 2 * TICKS_PER_DAY)
    s3["registry"] = [{"id": 56, "kind": "way_in", "phase": "done"}]
    props, notes = cycle(s3, m)
    assert not acts(props, "way_in") and [n for n in notes if "already dug" in n], notes
    src = (ROOT / "brain" / "review.py").read_text(encoding="utf-8")
    assert 'p.get("kind") not in ("way_in", "dig_way_in")' in src


@test("X1: the second way at priority 5 once citizens were stranded (9 otherwise)")
def _():
    s = json.loads(json.dumps(F.FIX))
    surf = [e for e in s["entrances"]["entrances"] if e.get("kind") == "surface"][:1]
    s["entrances"]["entrances"] = surf or [{"id": 1, "kind": "surface", "x": 10, "y": 10, "z": 100}]
    s["entrances"]["armed"] = False
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s.setdefault("dwarves", {})["total"] = 40
    for ever, want in ((None, 9), (1, 5)):
        m = Memory()
        if ever:
            m.second_way = {"stranded_ever": ever}
        props: list = []
        planner_gates._second_way_rule(s, m, planner_core.PLANNER_CONFIG, {}, props, [], {})
        got = [p.priority for p in props if p.rule == "second_way"]
        assert got == [want], (ever, got)


@test("D2: free_gate_jobs carries ai_plan where the AI fortified the entrance (memory.gates_fortified)")
def _():
    s = fort(split=False, stranded=0)
    e = s["entrances"]["entrances"][0]
    e.update(sealed=False, closing=True, waiting={"hatch": 1}, closing_days=8, equipment=[])
    s["entrances"]["parts"] = {"hatch_covers": 2, "doors": 0}
    m = Memory()
    fj = acts(cycle(copy.deepcopy(s), m)[0], "gate_jobs", "free_gate_jobs")
    assert fj and "ai_plan" not in fj[0].action, fj
    m = Memory()
    m.gates_fortified = {f"{e['x']},{e['y']},{e['z']}": "plain"}
    fj = acts(cycle(copy.deepcopy(s), m)[0], "gate_jobs", "free_gate_jobs")
    assert fj and fj[0].action.get("ai_plan") is True, fj


@test("D2: shared_lever_row (dead since v35) gone")
def _():
    assert not hasattr(planner_gates, "shared_lever_row")
    assert "shared_lever_row" not in planner_gates.__all__


finish()
