"""(r36) The near-gates reason says where a stalker is (inside the fort or
outside) and what it is (B 26 Nov 18:22: a hidden ambusher in the tavern was
said to stalk the dwarves "outside")."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import test, finish  # noqa: E402
from planner_near_gates import stalker_kind, stalker_why  # noqa: E402


def row(i, **kw):
    r = {"id": i, "name": f"U{i}", "can_reach_dwarves": True, "layer": "upper_levels"}
    r.update(kw)
    return r


@test("one hidden ambusher inside: 'it is inside the fort (a hidden ambusher)'")
def _():
    s = {"entrances": {"intruders_inside": [10]}}
    w = stalker_why(s, [row(10, hidden=True, ambush=True)])
    assert w == "it is inside the fort (a hidden ambusher)", w
    assert "outside" not in w


@test("outside only keeps 'stalks the dwarves outside', with the kind")
def _():
    w = stalker_why({}, [row(1, were_curse=True)])
    assert w == "it stalks the dwarves outside (a were)", w


@test("mixed: both, counted; a row's own inside counts")
def _():
    rows = [row(1, hidden=True), row(2, kinds=["NightCreature"], inside=True), row(3, arrival=True), row(4, transformed=True)]
    w = stalker_why({"entrances": {"intruders_inside": [1]}}, rows)
    assert w == "2 are inside the fort (hidden, a night creature); 2 stalk the dwarves outside (a hostile arrival, a were)", w


@test("stalker_kind: a were before a night creature before an ambusher")
def _():
    assert stalker_kind(row(1, transformed=True, hidden=True)) == "a were"
    assert stalker_kind(row(1, kinds=["NightCreature"], ambush=True)) == "a night creature"
    assert stalker_kind(row(1)) == "a stalker"



finish()
