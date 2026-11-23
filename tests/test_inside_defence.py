"""(0.105.83) A few ordinary enemies already inside the fort, fliers and wild
animals too, get one armed squad whatever the Rules tab says (B, 23 Nov 14:48:
three agitated giant ravens inside killed a planter, a stonecrafter and a
child in a minute; "send squads against nothing", a flier never a lone
intruder: 37 soldiers stood by): planner_leisure.inside_few and its place in
planner_military.

    python tests/test_inside_defence.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
import planner_leisure as PL  # noqa: E402

CFG = dict(PLANNER_CONFIG)
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def raven(i, **kw):
    t = {"id": i, "name": "Agitated Giant Raven", "can_reach_dwarves": True, "great_danger": False, "flier": True,
         "invader": False, "layer": "surface", "size": 20000, "pos": {"x": 127, "y": 130, "z": 165},
         "distance_to_nearest_dwarf": 2, "levels_from_nearest_dwarf": 0, "kinds": ["Animal"]}
    t.update(kw)
    return t


def sq(i, members=10):
    return {"id": i, "name": f"Squad {i}", "members": members, "size": 10, "orders": 0, "ai_orders": 0,
            "power": {"power": 60, "armed": members}, "routine": "Constant training"}


def fort(threats, inside, policy="never"):
    s = copy.deepcopy(BASE)
    s["others_on_map"]["threats"] = threats
    s["others_on_map"]["threats_that_can_reach_dwarves"] = len(threats)
    s["military"]["squads"] = [sq(182), sq(212)]
    s["entrances"]["intruders_inside"] = inside
    s.setdefault("settings", {})["attack_policy"] = policy
    return s


def attacks(s):
    return [p for p in plan(s, Memory())[0] if p.action.get("type") == "squad_orders" and p.action.get("kill")]


@test("B's three ravens inside, the Rules tab 'never': one squad is sent at them")
def _():
    rs = [raven(1), raven(2), raven(3)]
    s = fort(rs, [1, 2, 3])
    assert PL.inside_few(s, CFG, [1, 2, 3], {t["id"]: t for t in rs}) == [1, 2, 3]
    a = attacks(s)
    assert len(a) == 1 and set(a[0].action["kill"]) == {1, 2, 3}, [(p.rule, p.action) for p in a]


@test("not when one is still outside, one is a great danger or fire breather, or there are too many")
def _():
    rs = [raven(1), raven(2), raven(3)]
    m = {t["id"]: t for t in rs}
    assert PL.inside_few(fort(rs, [1, 2]), CFG, [1, 2, 3], m) == []
    for bad in ({"great_danger": True}, {"fire_breather": True}, {"destroyer": True}):
        r2 = [raven(1), raven(2, **bad)]
        assert PL.inside_few(fort(r2, [1, 2]), CFG, [1, 2], {t["id"]: t for t in r2}) == [], bad
    many = [raven(i) for i in range(1, 9)]
    assert PL.inside_few(fort(many, list(range(1, 9))), CFG, list(range(1, 9)), {t["id"]: t for t in many}) == []
    assert not attacks(fort(rs, [1, 2]))               # one outside: the Rules tab's 'never' holds


if __name__ == "__main__":
    finish()
