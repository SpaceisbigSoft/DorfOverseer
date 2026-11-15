"""(0.105.48 merge) Two fixes made at the round-2 merge: select()'s free-squad
pick never sends out a squad the matchup kept home in the same cycle; a kill
zone's drawbridge is linked only to a lever its puller reaches away from the
zone (20+ tiles or 4+ levels), as for the gates.

    python tests/test_k48_merge_fixes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, free_squad_for  # noqa: E402
from planner_core import Proposal  # noqa: E402
import planner_killzone  # noqa: E402

CFG = dict(PLANNER_CONFIG)


def _state(tick=5000):
    sq = lambda i: {"id": i, "name": f"S{i}", "members": 5, "armed": 5, "power": 30, "orders": 0, "ai_orders": 0}
    return {"date": {"year": 250, "tick": tick}, "military": {"squads": [sq(1), sq(2), sq(3)]}}


@test("free_squad_for: a taken squad's second kill order goes to a free squad; not in a cycle the matchup sized a fight")
def _():
    st = _state()
    p = Proposal("thieves", {"type": "squad_orders", "squad_id": 1, "kill": [77]}, "a thief", 3)
    claimed = {1: p}
    mem = Memory()
    alt = free_squad_for(p, claimed, st, CFG, {1}, mem)
    assert alt is not None and alt["id"] in (2, 3), alt
    from planner_core import abs_tick
    mem.matchup_judged = abs_tick(st)
    assert free_squad_for(p, claimed, st, CFG, {1}, mem) is None
    mem.matchup_judged = abs_tick(st) - 100           # an older cycle's: no hold
    assert free_squad_for(p, claimed, st, CFG, {1}, mem) is not None


@test("killzone link: a lever next to the zone's bridge is not linked; one 20+ tiles off is")
def _():
    br = {"built": True, "id": 50, "linked": False, "x": 10, "y": 10, "z": 100}
    kz = {"zones": [{"drawbridge": br}]}
    def run(levers):
        s = {"entrances": {"free_levers": levers}}
        out = []
        orig = planner_killzone._rows
        planner_killzone._rows = lambda k: k["zones"]
        try:
            planner_killzone._link_rule(s, kz, out)
        finally:
            planner_killzone._rows = orig
        return out
    near = {"id": 1, "x": 12, "y": 11, "z": 100}
    far = {"id": 2, "x": 40, "y": 10, "z": 100}
    assert run([near]) == []
    got = run([near, far])
    assert got and got[0].action["lever_id"] == 2, [p.action for p in got]


finish()
