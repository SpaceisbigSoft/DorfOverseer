"""(0.105.80) A lifted alarm is raised again for a great danger near a dwarf,
inside the fort or not (E, 23 Nov 11:00: the alarm, lifted for a dragon nobody
would fight, stayed down while it came at the dwarves on the surface; 10
melted): planner_war_hold.great_near_dwarves and unfought_raise_held.

    python tests/test_great_alarm.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG  # noqa: E402
import planner_war_hold as wh  # noqa: E402

CFG = dict(PLANNER_CONFIG)


def state(**t):
    row = {"id": 7, "name": "Warmthsizzle the Hot, Dragon", "distance_to_nearest_dwarf": 12}
    row.update(t)
    return {"others_on_map": {"threats": [row]}}


def lifted(ids=(7,)):
    m = Memory()
    wh._set_rec(m, {"lifted": 100, "lifted_ids": list(ids)})
    return m


@test("a dragon (dragonfire) 12 tiles from a dwarf, outside: the lift no longer holds the alarm down")
def _():
    s = state(breath=["dragonfire"], great_danger=True)
    assert wh.great_near_dwarves(s, CFG, [s["others_on_map"]["threats"][0]]) == "Warmthsizzle the Hot"
    assert wh.unfought_raise_held(s, lifted(), CFG, [7]) == ""
    s = state(breath=["dragonfire", "dust"], great_danger=True, kinds=["Megabeast"], distance_to_nearest_dwarf=44, id=0)
    assert wh.unfought_raise_held(s, lifted((0,)), CFG, [0]) == "", "E's dragon as read at 11:52 (id 0, 44 tiles)"


@test("a fire breather that isn't flagged great still counts; so do the great kinds")
def _():
    for t in ({"fire_breather": True}, {"kinds": ["Titan"]}, {"kinds": ["ForgottenBeast"]}):
        s = state(**t)
        assert wh.unfought_raise_held(s, lifted(), CFG, [7]) == "", t


@test("an ordinary lifted beast, or a great danger far from every dwarf: still held")
def _():
    for t in ({"kinds": ["Animal"]}, {"great_danger": True, "distance_to_nearest_dwarf": 80},
              {"great_danger": True, "distance_to_nearest_dwarf": None}, {"kinds": ["Undead"]}):
        s = state(**t)
        assert "the alarm was lifted" in wh.unfought_raise_held(s, lifted(), CFG, [7]), t


@test("nothing lifted, or a new enemy among them: nothing held, as before")
def _():
    s = state(kinds=["Animal"])
    assert wh.unfought_raise_held(s, lifted(()), CFG, [7]) == ""
    assert wh.unfought_raise_held(s, lifted((7,)), CFG, [7, 8]) == ""


if __name__ == "__main__":
    finish()
