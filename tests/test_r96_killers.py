"""(0.105.96) B's hospital deaths: the guard kept through wildlife.

Live 23 Nov, B: at 20:05 three patients were strangled inside the second
hospital (zone 1342, z160: x117 y136, x117 y134, x123 y136) by Fath Shemnish
(not yet a known killer: celled at 20:06:30, after these two killings) and
Kadol Kûbukdast (one killing: watched). Both hospital guards had been taken off
at 20:01:14 for "enemies can reach the dwarves": an agitated giant raven, the
free squads' work anyway. The killer cells' trips out killed nobody. Now only
invaders, a great danger, or enemies with no other able squad take a guard.

    python tests/test_r96_killers.py
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

from planner import Memory, plan, PLANNER_CONFIG  # noqa: E402
from planner_core import abs_tick  # noqa: E402
import planner_tantrums as PT  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
RAVEN = {"id": 9, "name": "Agitated Giant Raven", "animal": True, "invader": False, "great_danger": False,
         "can_reach_dwarves": True}


def guard_fort(threats, squads):
    s = copy.deepcopy(BASE)
    s["tantrums"] = {"loose": 1, "berserk": 0, "possessed": 0, "dwarves": [], "chronic": 0,
                     "hospitals": [{"zone_id": 333, "x": 116, "y": 139, "z": 163},
                                   {"zone_id": 1342, "x": 120, "y": 136, "z": 160}],
                     "squads": [{"id": 20, "members": 8, "calm": True, "ai_orders": 1, "player_orders": 0}],
                     "guards": [{"squad_id": 20, "zone_id": 333, "since": abs_tick(s)}]}
    s.setdefault("others_on_map", {})
    s["others_on_map"]["threats"] = threats
    s["others_on_map"]["threats_that_can_reach_dwarves"] = sum(1 for t in threats if t.get("can_reach_dwarves"))
    s["military"]["squads"] = squads
    return s


def sq(i, members=6):
    return {"id": i, "name": f"Squad {i}", "members": members, "size": 10, "orders": 0, "ai_orders": 0,
            "power": {"power": 5000, "armed": members}}


def releases(s):
    return [p for p in plan(s, Memory())[0] if p.rule == "hospital_guard" and p.action.get("release")]


@test("B's raven with another able squad free: the hospital guard stays")
def _():
    s = guard_fort([RAVEN], [sq(20, 8), sq(30)])
    assert not releases(s), releases(s)


@test("the raven and no other able squad: the guard goes to it; an invader or a great danger: the guard goes")
def _():
    assert releases(guard_fort([RAVEN], [sq(20, 8)]))
    assert releases(guard_fort([dict(RAVEN, animal=False, invader=True)], [sq(20, 8), sq(30)]))
    assert releases(guard_fort([dict(RAVEN, great_danger=True)], [sq(20, 8), sq(30)]))


@test("_guard_wanted_elsewhere: nothing about: False; enemies that can't reach: False")
def _():
    s = guard_fort([], [sq(20, 8)])
    assert PT._guard_wanted_elsewhere(s, PLANNER_CONFIG, {20}) is False
    s = guard_fort([dict(RAVEN, can_reach_dwarves=False)], [sq(20, 8)])
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    assert PT._guard_wanted_elsewhere(s, PLANNER_CONFIG, {20}) is False



@test("(verifier) no guard yet, one able squad and the raven: no guard posted (it would be released next cycle); "
      "with a second able squad: the guard is posted")
def _():
    def unguarded(squads):
        s = guard_fort([RAVEN], squads)
        s["tantrums"]["guards"] = []
        s["tantrums"]["squads"] = [{"id": q["id"], "members": q["members"], "calm": True, "ai_orders": 0,
                                    "player_orders": 0} for q in squads]
        return [p for p in plan(s, Memory())[0] if p.rule == "hospital_guard" and not p.action.get("release")]
    assert not unguarded([sq(20, 8)]), unguarded([sq(20, 8)])
    got = unguarded([sq(20, 8), sq(30)])
    assert got and got[0].action["squad_id"] == 20, got

finish()
