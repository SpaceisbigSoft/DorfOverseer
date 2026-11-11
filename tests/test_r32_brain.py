"""(0.105.32, brain) An open gate the game holds shut (E, 8 Nov: the founding
stair's hatch read open after the watcher's instant lever pulls, DF's walk
map split at it, 64 dead of thirst outside): planner_gates._gate_stuck_rule
proposes unstick_gate at once, a step at a time; _way_in_rule digs a way in
for citizens cut off with no gate to blame. Fake reports, no Lua.

    python tests/test_r32_brain.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

import planner  # noqa: E402
from planner import Memory, plan, select, record, note_cycle, Proposal, PLANNER_CONFIG  # noqa: E402
import planner_core  # noqa: E402
import digest  # noqa: E402
import overseer  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
HOUR = 50

PIECE = {"id": 7, "kind": "hatch", "x": 108, "y": 149, "z": 171, "outside_group": 5151, "inside_group": 1702,
         "flags": {"closed": False, "forbidden": False, "operated_by_mechanisms": True},
         "tiles": {"above": "Grass", "at": "StoneStairD", "below": "StoneStairUD"},
         "link": {"lever": 137, "linked_mechanisms": 1, "status": "linking"}}


def fort(split=True, stranded=12, cause="gate_stuck", out_ticks=100, **row) -> dict:
    s = copy.deepcopy(BASE)
    s["map"]["elevation_offset"] = -100
    ent = s["entrances"]
    e = {"id": 1, "kind": "surface", "x": 108, "y": 149, "z": 170, "width": 1, "sealed": True,
         "equipment": [{"id": 7, "kind": "hatch"}], "door_spots": 0, "closed": False}
    if split:
        e["split"] = [copy.deepcopy(PIECE)]
    ent["entrances"] = [e]
    ent["scanned_tick"] = planner_core.abs_tick(s) - 10
    rows = []
    for i in range(stranded):
        r = {"id": 100 + i, "name": f"Dwarf{i}", "x": 100 + i, "y": 150, "z": 171, "cause": cause,
             "out_ticks": out_ticks, "out_days": out_ticks // 1200, "group": 5151,
             "entrance": {"id": 1, "kind": "surface", "x": 108, "y": 149, "z": 170}}
        if cause == "gate_stuck":
            r["stuck_gate"] = 7
        r.update(row)
        rows.append(r)
    ent["stranded"] = rows
    return s


def later(s: dict, ticks: int, rescan: bool = False) -> dict:
    s = copy.deepcopy(s)
    s["date"]["tick"] += ticks
    if rescan:
        s["entrances"]["scanned_tick"] = planner_core.abs_tick(s) - 1
    return s


def acts(props, rule=None, typ=None):
    return [p for p in props if (rule is None or p.rule == rule) and (typ is None or p.action.get("type") == typ)]


def needs_you(notes):
    return [n for n in notes if n.startswith("[you]")]


def cycle(s, m):
    note_cycle(s, m)
    return plan(s, m)


def answer(s, m, p, **r):
    record([(p, dict({"ok": True, "step": p.action.get("step")}, **r))], s, m)


# --- E's case: the split hatch and 12 gate_stuck rows ---------------------------

@test("E's hatch: step 1 at once, step 2 after 6 game hours while still split, step 3 after that, nothing once joined")
def _():
    m = Memory()
    s = fort()
    props, notes = cycle(s, m)
    u = acts(props, "gate_stuck", "unstick_gate")
    assert len(u) == 1 and u[0].action == {"type": "unstick_gate", "id": 7, "step": 1}, props
    assert u[0].priority < 0, u[0].priority
    assert not needs_you([n for n in notes if "no way back in" in n]), notes      # the gate's line, not "dig"
    assert not acts(props, "way_in"), props
    answer(s, m, u[0], split_after=True, done="forbid cleared; reindexed")
    assert m.gate_unstick["7"]["step"] == 1 and m.rescan_entrances
    # 3 hours on: waiting
    assert not acts(cycle(later(s, 3 * HOUR), m)[0], "gate_stuck")
    # 6 hours on, still split: step 2
    s2 = later(s, 6 * HOUR, rescan=True)
    u = acts(cycle(s2, m)[0], "gate_stuck")
    assert len(u) == 1 and u[0].action["step"] == 2, u
    answer(s2, m, u[0], split_after=True, done="lever 137 pulled twice")
    assert not acts(cycle(later(s2, 5 * HOUR), m)[0], "gate_stuck")
    s3 = later(s2, 6 * HOUR)
    u = acts(cycle(s3, m)[0], "gate_stuck")
    assert len(u) == 1 and u[0].action["step"] == 3, u
    answer(s3, m, u[0], split_after=False, done="hatch 7 deconstructed")
    # joined: no split, nobody stranded: nothing, and the steps forgotten
    s4 = later(fort(split=False, stranded=0), 0)
    s4["date"]["tick"] = s3["date"]["tick"] + 6 * HOUR
    props, notes = cycle(s4, m)
    assert not acts(props, "gate_stuck"), props
    assert "7" not in m.gate_unstick or set(m.gate_unstick["7"]) <= {"prevent"}, m.gate_unstick


@test("E's hatch: step 1 answered joined, nobody out any more: no step 2")
def _():
    m = Memory()
    s = fort()
    u = acts(cycle(s, m)[0], "gate_stuck")
    answer(s, m, u[0], split_after=False)
    s2 = fort(split=False, stranded=0)
    s2["date"]["tick"] = s["date"]["tick"] + 7 * HOUR
    assert not acts(cycle(s2, m)[0], "gate_stuck")
    # joined, but the rows come from a scan older than the step: still no step 2
    m = Memory()
    answer(s, m, u[0], split_after=False)
    s3 = later(s, 7 * HOUR)
    assert not acts(cycle(s3, m)[0], "gate_stuck")


@test("E's hatch: joined answer, then a scan since still finds it split: step 2")
def _():
    m = Memory()
    s = fort()
    u = acts(cycle(s, m)[0], "gate_stuck")
    answer(s, m, u[0], split_after=False)
    s3 = later(s, 7 * HOUR, rescan=True)
    u = acts(cycle(s3, m)[0], "gate_stuck")
    assert u and u[0].action["step"] == 2, u


@test("a fallback: no_path rows in the split piece's outside group are the gate's (an older bridge)")
def _():
    m = Memory()
    s = fort(cause="no_path")
    props, notes = cycle(s, m)
    assert acts(props, "gate_stuck", "unstick_gate") and not acts(props, "way_in"), props
    assert not [n for n in notes if "no way back in" in n], notes


@test("all three steps tried (step 3 refused: the player's own hatch): no more steps; the way in is dug")
def _():
    m = Memory()
    s = fort()
    m.gate_unstick["7"] = {"step": 3, "tick": planner_core.abs_tick(s) - 7 * HOUR, "ok": False,
                           "split_after": None, "done": "not the AI's hatch"}
    props = cycle(s, m)[0]
    assert not acts(props, "gate_stuck"), props
    w = acts(props, "way_in")
    assert w and w[0].action["type"] == "dig_way_in", props
    props = cycle(later(s, 30 * HOUR), m)[0]
    assert not acts(props, "gate_stuck"), props          # never back to step 1


# --- prevention, the enemy hold ---------------------------------------------------

@test("prevention: a split with nobody stranded yet: step 1, at most once a game day")
def _():
    m = Memory()
    s = fort(stranded=0)
    props, notes = cycle(s, m)
    u = acts(props, "gate_stuck")
    assert len(u) == 1 and u[0].action["step"] == 1 and "nobody is shut out yet" in u[0].reason, u
    assert not needs_you(notes) or not [n for n in needs_you(notes) if "building 7" in n], notes
    answer(s, m, u[0], split_after=True)
    assert not acts(cycle(later(s, 12 * HOUR, rescan=True), m)[0], "gate_stuck")
    u = acts(cycle(later(s, 25 * HOUR, rescan=True), m)[0], "gate_stuck")
    assert u and u[0].action["step"] == 1, u          # prevention never goes past step 1
    # a threat that can reach the dwarves, or the watcher armed: not now
    s2 = fort(stranded=0)
    s2["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    assert not acts(cycle(s2, Memory())[0], "gate_stuck")
    s3 = fort(stranded=0)
    s3["entrances"]["armed"] = True
    assert not acts(cycle(s3, Memory())[0], "gate_stuck")


@test("an enemy near them or the gate: no unstick, said why")
def _():
    for k in ("danger_near", "gate_danger"):
        m = Memory()
        props, notes = cycle(fort(**{k: 10}), m)
        assert not acts(props, "gate_stuck"), props
        assert any("enemy is 10 tiles away" in n and "building 7" in n for n in notes), notes
    props, _ = cycle(fort(danger_near=200, gate_danger=150), Memory())
    assert acts(props, "gate_stuck")


# --- the Needs you line -------------------------------------------------------------

@test("Needs you: one line naming the gate, where, the walk groups, the flags, what was tried; the same shape each cycle")
def _():
    m = Memory()
    s = fort()
    props, notes = cycle(s, m)
    ny = [n for n in needs_you(notes) if "building 7" in n]
    assert len(ny) == 1, notes
    t = ny[0]
    for want in ("12 citizen(s)", "hatch (building 7) at x108 y149 elevation 71", "outside 5151", "inside 1702",
                 "closed=false", "forbidden=false", "operated_by_mechanisms=true", "tried: nothing yet",
                 "DF's walk map holding an open hatch shut"):
        assert want in t, (want, t)
    answer(s, m, acts(props, "gate_stuck")[0], split_after=True, done="forbid cleared")
    _, notes2 = cycle(later(s, HOUR), m)
    t2 = [n for n in needs_you(notes2) if "building 7" in n][0]
    assert "tried: step 1" in t2 and "forbid cleared" in t2, t2
    s3 = later(s, 2 * HOUR)
    s3["entrances"]["stranded"] = s3["entrances"]["stranded"][:9]
    _, notes3 = cycle(s3, m)
    t3 = [n for n in needs_you(notes3) if "building 7" in n][0]
    assert overseer._shape(t3) == overseer._shape(t2), (t2, t3)     # printed once (show_changed)


# --- dig_way_in -----------------------------------------------------------------------

def cut_off(n=3, days=2, **row):
    s = fort(split=False, stranded=n, cause="no_path", out_ticks=days * 1200, group=900, **row)
    for r in s["entrances"]["stranded"]:
        r.pop("entrance", None)
    s["entrances"]["stranded"][0].update(x=50, y=60, z=171)
    return s


@test("dig_way_in: cut off 2 days with no split: a stair at their median spot; not before; the Needs you kept")
def _():
    assert not acts(cycle(cut_off(days=1), Memory())[0], "way_in")
    m = Memory()
    s = cut_off()
    props, notes = cycle(s, m)
    w = acts(props, "way_in", "dig_way_in")
    assert len(w) == 1 and w[0].action == {"type": "dig_way_in", "x": 101, "y": 150, "z": 171}, w
    assert w[0].priority < 0
    ny = [n for n in needs_you(notes) if "no way back in" in n]
    assert ny and "digs them a way in" in ny[0] and "x101 y150 elevation 71" in ny[0], ny
    assert not acts(props, "gate_stuck")
    # in a cavern, or an enemy near: not dug
    assert not acts(cycle(cut_off(in_cavern=True), Memory())[0], "way_in")
    props, notes = cycle(cut_off(danger_near=5), Memory())
    assert not acts(props, "way_in") and any("enemy is 5 tiles away" in n for n in notes), notes


@test("dig_way_in: once; none while it is dug; done and they're still out: never again there, only the Needs you")
def _():
    m = Memory()
    s = cut_off()
    w = acts(cycle(s, m)[0], "way_in")[0]
    record([(w, {"ok": True, "project_id": 55, "from": {}, "to": {}, "tiles": 12})], s, m)
    assert m.way_in["101,150,171"]["project_id"] == 55
    assert not acts(cycle(later(s, 600), m)[0], "way_in")     # (not in the report yet)
    s2 = later(s, 1200)
    s2["projects"]["open"] = [{"id": 55, "kind": "way_in", "phase": "dig"}]
    props, notes = cycle(s2, m)
    assert not acts(props, "way_in"), props
    assert any("project #55" in n for n in needs_you(notes)), notes
    # (merge32 review) the project done, still out: no more digging there, ever
    for d in (3, 8, 20, 40):
        props, notes = cycle(later(s, d * 1200), m)
        assert not acts(props, "way_in"), (d, props)
        assert any("digs no more there" in n for n in notes), notes
        assert [n for n in needs_you(notes) if "dig or build them a way in" in n], notes
    # everyone home: forgotten (a new stranding there may be dug for)
    home = later(fort(split=False, stranded=0), 0)
    home["date"]["tick"] = later(s, 41 * 1200)["date"]["tick"]
    cycle(home, m)
    assert m.way_in == {}, m.way_in
    # a refusal: again a day on, not a week
    m2 = Memory()
    w = acts(cycle(s, m2)[0], "way_in")[0]
    record([(w, {"ok": False, "error": "no tile of the fort near"})], s, m2)
    assert not acts(cycle(later(s, 600), m2)[0], "way_in")
    assert acts(cycle(later(s, 1300), m2)[0], "way_in")


@test("dig_way_in: fewer than way_in_min_stranded: nothing")
def _():
    cfg = dict(PLANNER_CONFIG, way_in_min_stranded=4)
    s = cut_off(n=3)
    m = Memory()
    note_cycle(s, m)
    assert not acts(plan(s, m, cfg)[0], "way_in")


# --- protection ------------------------------------------------------------------------

@test("protected: STEER_PROTECTED, no action limit, no cooldown; the strategist can't hold them")
def _():
    for r in ("gate_stuck", "way_in"):
        assert r in planner_core.STEER_PROTECTED and r in planner_core.LIMIT_EXEMPT and r in planner_core.NO_COOLDOWN
    for k in ("gate_stuck_step_hours", "way_in_after_days", "way_in_min_stranded"):
        assert k in PLANNER_CONFIG
    assert PLANNER_CONFIG["gate_stuck_step_hours"] == 6 and PLANNER_CONFIG["way_in_after_days"] == 2
    s = fort()
    m = Memory()
    now = planner_core.abs_tick(s)
    m.steer = {"gate_stuck": {"mode": "hold", "until": now + 10000, "why": "test"},
               "way_in": {"mode": "hold", "until": now + 10000, "why": "test"}}
    m.last_fired = {"gate_stuck": now - 10, "way_in": now - 10}
    busy = [Proposal(f"busy{i}", {"type": "work_order", "recipe": f"r{i}"}, "x", -5) for i in range(6)]
    ours = [Proposal("gate_stuck", {"type": "unstick_gate", "id": 7, "step": 1}, "x", -1),
            Proposal("gate_stuck", {"type": "unstick_gate", "id": 8, "step": 1}, "x", -1),
            Proposal("way_in", {"type": "dig_way_in", "x": 1, "y": 2, "z": 3}, "x", -1)]
    allowed, held = select(busy + ours, s, m)
    for p in ours:
        assert p in allowed, held
    # refused: no back-off booked (each paces itself)
    record([(ours[2], {"ok": False, "error": "no"})], s, m)
    assert not [k for k in m.refusals if k.startswith("way_in:")], m.refusals


@test("the gate watcher isn't armed in the cycle a gate is unstuck")
def _():
    s = fort()
    s["entrances"]["armed"] = False
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    props, _ = cycle(s, Memory())
    assert acts(props, "gate_stuck") and not acts(props, typ="arm_gates"), [(p.rule, p.action) for p in props]
    # nothing to unstick: armed as before
    s2 = fort(split=False, stranded=0)
    s2["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    props, _ = cycle(s2, Memory())
    assert acts(props, typ="arm_gates"), [(p.rule, p.action) for p in props]


# --- words -------------------------------------------------------------------------------

@test("words: the panel's words for the two actions; the digest's GATE_SPLIT line")
def _():
    assert "step 2 of 3" in overseer.short({"type": "unstick_gate", "id": 7, "step": 2})
    assert overseer.short({"type": "dig_way_in", "x": 1, "y": 1, "z": 1}) != "dig_way_in"
    d = digest.digest(fort())
    line = [ln for ln in d.splitlines() if ln.startswith("GATE_SPLIT")]
    assert line and "hatch #7 x108 y149 elevation 71" in line[0] and "12 shut out" in line[0], line
    assert "5151" in line[0] and "1702" in line[0]
    assert not [ln for ln in digest.digest(fort(split=False)).splitlines() if ln.startswith("GATE_SPLIT")]
    assert "GATE_SPLIT" not in digest.digest(copy.deepcopy(BASE))


@test("(merge32 review) a siege (threats that can reach the dwarves, or the watcher armed): steps 2 and 3 and the way in held, said why; step 1 still goes")
def _():
    for kind in ("reach", "armed"):
        def siege(st):
            if kind == "reach":
                st["others_on_map"]["threats_that_can_reach_dwarves"] = 8
            else:
                st["entrances"]["armed"] = True
            return st
        s = siege(fort(danger_near=40, gate_danger=35))
        props = cycle(s, Memory())[0]
        u = acts(props, "gate_stuck")
        assert len(u) == 1 and u[0].action["step"] == 1, (kind, u)
        for st in (2, 3):
            m = Memory()
            m.gate_unstick = {"7": {"step": st - 1, "tick": planner_core.abs_tick(s) - 7 * HOUR, "ok": True,
                                    "split_after": True}}
            props, notes = cycle(s, m)
            assert not acts(props, "gate_stuck"), (kind, st, props)
            assert any(f"step {st}" in n and "waits until that is over" in n for n in notes), notes
        # a way in during the siege: not dug
        s = siege(cut_off(days=3, danger_near=40))
        props, notes = cycle(s, Memory())
        assert not acts(props, "way_in"), (kind, props)
        assert any("no way in is dug until that is over" in n for n in notes), notes
    # the siege over: step 2 goes
    s = fort(danger_near=40)
    m = Memory()
    m.gate_unstick = {"7": {"step": 1, "tick": planner_core.abs_tick(s) - 7 * HOUR, "ok": True, "split_after": True}}
    assert acts(cycle(s, m)[0], "gate_stuck")[0].action["step"] == 2


@test("(merge32 review) step 2 with no lever: answered done ('no lever: skipped'), step 3 next; an older bridge's refusal too")
def _():
    for answer_kw in ({"ok": True, "done": "no lever: skipped", "split_after": True},
                      {"ok": False, "rejected": True, "error": "no lever of its own works this gate: nothing to pull"}):
        m = Memory()
        s = fort()
        answer(s, m, acts(cycle(s, m)[0], "gate_stuck")[0], split_after=True)
        s = later(s, 6 * HOUR, rescan=True)
        u = acts(cycle(s, m)[0], "gate_stuck")
        assert u[0].action["step"] == 2, u
        answer(s, m, u[0], **answer_kw)
        s = later(s, 6 * HOUR, rescan=True)
        u = acts(cycle(s, m)[0], "gate_stuck")
        assert len(u) == 1 and u[0].action["step"] == 3, (answer_kw, u)


@test("(merge32 review) a cavern's gate: step 1 only (the bridge won't pull or take it down); the Needs you stays")
def _():
    m = Memory()
    s = fort()
    s["entrances"]["entrances"][0]["kind"] = "cavern"
    answer(s, m, acts(cycle(s, m)[0], "gate_stuck")[0], split_after=True)
    for k in (1, 2, 4):
        props, notes = cycle(later(s, 6 * k * HOUR + 10, rescan=True), m)
        assert not acts(props, "gate_stuck"), props
        assert [n for n in needs_you(notes) if "building 7" in n], notes
    # a surface entrance the bridge answered "a cavern's way": no step 2 again
    m = Memory()
    s = fort()
    m.gate_unstick = {"7": {"step": 2, "tick": planner_core.abs_tick(s) - 7 * HOUR, "ok": False, "cavern": True,
                            "done": "this gate is on a cavern's way"}}
    assert not acts(cycle(s, m)[0], "gate_stuck")
    m = Memory()
    record([(Proposal("gate_stuck", {"type": "unstick_gate", "id": 7, "step": 2}, "x", -1),
             {"ok": False, "rejected": True, "cavern": True, "error": "a cavern's way"})], s, m)
    assert m.gate_unstick["7"]["cavern"] is True


@test("(merge32 review) a refused way in backs off per area: 1, then 2 days; after 3 refusals only the Needs you")
def _():
    m = Memory()
    s = cut_off(days=3)
    t0 = 0
    tries = []
    for h in range(0, 12 * 24, 6):
        sx = later(s, h * HOUR)
        props, notes = cycle(sx, m)
        for w in acts(props, "way_in"):
            tries.append(h // 24)
            record([(w, {"ok": False, "rejected": True, "error": "no safe way in found"})], sx, m)
    assert tries == [0, 1, 3], tries
    assert len(m.way_in) == 1 and list(m.way_in.values())[0]["refusals"] == 3, m.way_in
    props, notes = cycle(later(s, 30 * 1200), m)
    assert not acts(props, "way_in")
    assert any("refused 3 time(s)" in n for n in notes), notes
    assert [n for n in needs_you(notes) if "dig or build them a way in" in n], notes
    # another area, far off: its own count
    s2 = cut_off(days=3)
    for r in s2["entrances"]["stranded"]:
        r["x"] += 60
    assert acts(cycle(later(s2, 30 * 1200), m)[0], "way_in")


@test("(merge32 review) one dwarf alone: a way in only after way_in_single_days (3) out")
def _():
    assert PLANNER_CONFIG["way_in_single_days"] == 3
    assert not acts(cycle(cut_off(n=1, days=2), Memory())[0], "way_in")
    assert acts(cycle(cut_off(n=1, days=3), Memory())[0], "way_in")
    assert acts(cycle(cut_off(n=2, days=2), Memory())[0], "way_in")


@test("(merge32 review) the panel's words: one branch for unstick_gate")
def _():
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    assert src.count('if t == "unstick_gate"') == 1
    assert overseer.short({"type": "unstick_gate", "id": 7, "step": 3}) == "free a gate the game holds shut (step 3 of 3)"


if __name__ == "__main__":
    finish()
