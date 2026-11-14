"""(group 2) The cavern well's shaft: shut only for a danger that could come
up it, by the bridge's own verdict (shaft_judge: watch_near on each linked
gate, watch_rule 2), kept shut for its hold (shut_hold), opened once the
danger has been away; short of water, a far danger that can't fly or climb
doesn't keep it shut (the bridge's `dry`). E and F (14 Nov): well_shaft 49
and 32 times, shut for demons in the underworld, 186 dead of thirst.

    python tests/test_g2_well_shaft.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
import planner_wells  # noqa: E402
import planner_threats  # noqa: E402
from planner import plan, Memory  # noqa: E402


def gate(**k):
    g = {"project_id": 9, "x": 120, "y": 121, "z": 156, "elevation": 26, "state": "none",
         "gate": "closed", "watching": True, "watch_rule": 2, "shut_hold": 0}
    g.update(k)
    return g


def state(*gates, wells=2, drink=900, patients=0, parched=0, zones=None):
    return {"settings": {"traits": {}}, "dwarves": {"total": 40, "needs_medical_care": patients},
            "society": {"parched": parched}, "stocks": {"drink": drink, "mechanisms": 5},
            "buildings": {"other": {"Well": wells}, "zones": zones or {}},
            "projects": {"open": [], "max_open": 2, "well_lids": list(gates)},
            "others_on_map": {}, "date": {"year": 5, "tick": 1000, "season": "spring"}}


def run(s):
    props, notes = [], []
    planner_wells._well_lid_rule(s, props, notes)
    return [p for p in props if p.rule == "well_shaft" and p.action.get("type") == "well_shaft"], notes


FLIER = {"id": 7, "name": "Seerjackals, Forgotten Beast", "d": 32, "reach": 95, "great": True, "flier": True,
         "mobile": True}
WALKER = {"id": 8, "name": "Cave Crocodile", "d": 50, "reach": 75, "great": True, "mobile": False}


@test("group 2: a shut gate with no danger and its hold run out is opened; the hold running, it isn't")
def _():
    p, notes = run(state(gate()))
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False}], [x.action for x in p]
    assert "no danger near" in p[0].reason
    p, notes = run(state(gate(shut_hold=400)))
    assert not p, [x.action for x in p]
    assert any("stays shut a while yet (400 ticks)" in n for n in notes), notes


@test("group 2: the bridge's verdict alone decides (the report's threat list doesn't shut a judged shaft)")
def _():
    s = state(gate(gate="open"))
    s["others_on_map"]["threats"] = [{"id": 5, "name": "Lizard Devil", "layer": "Cavern1",
                                      "pos": {"x": 125, "y": 120, "z": 140}}]
    p, _ = run(s)
    assert not p, [x.action for x in p]                    # the bridge saw nothing that could come up it
    s["projects"]["well_lids"][0]["watch_near"] = FLIER
    p, _ = run(s)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": True}] and p[0].priority == 2
    assert "flies, 32 tiles from the shaft" in p[0].reason, p[0].reason


@test("group 2: shut for a danger near, water enough: kept shut and said (still a well)")
def _():
    p, notes = run(state(gate(watch_near=FLIER)))
    assert not p and any("still counted as a well" in n and "flies" in n for n in notes), notes
    assert not any(n.startswith("[you]") for n in notes)


@test("group 2: short of water, a far danger that can't fly or climb: opened, the bridge told `dry`")
def _():
    s = state(gate(watch_near=WALKER), wells=1, patients=3)
    p, notes = run(s)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "dry": True}], [x.action for x in p]
    assert p[0].priority == 2 and "3 injured need water" in p[0].reason and "can't fly or climb" in p[0].reason
    # the same walker near (within a walker's reach): kept shut, said
    s["projects"]["well_lids"][0]["watch_near"] = dict(WALKER, d=18)
    p, notes = run(s)
    assert not p and any("short of water" in n and "kept shut" in n for n in notes), notes
    # a flier, short of water: kept shut, said what the AI does meanwhile (no Needs you: the standing rule)
    s["projects"]["well_lids"][0]["watch_near"] = FLIER
    p, notes = run(s)
    assert not p and any("kept shut, since it could come up the shaft" in n for n in notes), notes
    assert not any(n.startswith("[you]") for n in notes)


@test("group 2: short of water, the hold running: opened at once (dry)")
def _():
    p, _ = run(state(gate(shut_hold=900), wells=1, drink=10))
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "dry": True}], [x.action for x in p]


@test("group 2: `dry` taken back only once the fort has water again (no flapping with the open shaft)")
def _():
    s = state(gate(gate="open", watch_dry=True), wells=1, patients=2)
    p, _ = run(s)
    assert not p, [x.action for x in p]                    # still short: dry stays, nothing to do
    s["dwarves"]["needs_medical_care"] = 0
    p, _ = run(s)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "dry": False}], [x.action for x in p]
    assert "water again" in p[0].reason
    # another well, or a water source zone: not short
    assert planner_wells.shaft_water_short(state(gate(), wells=2, patients=2), [gate()]) == ""
    assert planner_wells.shaft_water_short(state(gate(), wells=1, patients=2, zones={"WaterSource": 1}), [gate()]) == ""
    assert planner_wells.shaft_water_short(state(gate(), wells=1, parched=2), [gate()]) == "2 parched"


@test("group 2: a given-up shaft open is shut; one in the shaft itself always keeps it shut")
def _():
    p, _ = run(state(gate(gate="open", cancelled=True)))
    assert [x.action for x in p] == [{"type": "well_shaft", "close": True}] and "given-up" in p[0].reason
    near = {"id": 3, "name": "Troll", "d": 1, "in_shaft": True, "mobile": True}
    p, notes = run(state(gate(watch_near=near), wells=1, patients=4))
    assert not p and any("Troll (in the shaft)" in n for n in notes), notes


@test("group 2: the well rule counts a shaft shut for its hold as a well (no second cavern well)")
def _():
    s = state(gate(shut_hold=300), wells=1)
    assert planner_wells.shaft_judged(s["projects"]["well_lids"])
    props, notes = [], []
    m = Memory()
    m.well_failure = "no clean water inside the fort to channel a well over"
    planner_wells._well_rule(s, m, {}, __import__("planner").PLANNER_CONFIG, props, notes)
    assert not any(p.rule == "well" for p in props), [(p.rule, p.action) for p in props]


@test("group 2: the threats rule says the shaft is shut for a beast only when it is")
def _():
    src = (ROOT / "brain" / "planner_threats.py").read_text(encoding="utf-8")
    assert 'x.get("watch_rule") or 0) >= 2' in src


@test("group 2: plan() end to end: Lizard Devil 140 levels down (no verdict) doesn't keep a judged shaft shut")
def _():
    from test_planner import fort  # noqa: E402
    s = fort()
    s["others_on_map"]["threats"] = []
    s["projects"]["well_lids"] = [gate()]
    acts = [p.action for p in plan(s, Memory())[0] if p.rule == "well_shaft"]
    assert {"type": "well_shaft", "close": False} in acts, acts


if __name__ == "__main__":
    finish()
