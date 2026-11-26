"""(r36) A stalker inside the fort is fought at once.

B, 26 Nov 18:22:36: a hidden hero swordsman (an artifact thief, sneaking) was
inside, in the tavern among guests; the crowd rule and the lone-thief rule
kept him off the defence's targets and he killed the tavern keeper 13 s
later. brain/planner_stalker_inside.py, planner_military._military_rules.

    python3 tests/test_r36_stalker_inside.py
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
import planner_hostile_arrivals as H  # noqa: E402
from planner_stalker_inside import stalkers_inside  # noqa: E402

CFG = dict(PLANNER_CONFIG)
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
NAME = 'Kulur Jamasmoñol "Meetingtrusted", Human Swordsman'


def fort(threats=None, inside=(), policy=None) -> dict:
    s = copy.deepcopy(BASE)
    deep = [t for t in s["others_on_map"]["threats"] if H._deep(t.get("layer"))]
    s["others_on_map"]["threats"] = deep + list(threats or [])
    s.setdefault("entrances", {})["intruders_inside"] = list(inside)
    s["military"]["squads"] = [sq(183), sq(201)]
    if policy:
        s.setdefault("settings", {})["attack_policy"] = policy
    return s


def sq(i, members=10, power=20):
    return {"id": i, "name": f"Squad {i}", "members": members, "size": 10, "orders": 0, "ai_orders": 0,
            "power": {"power": power, "melee_power": power, "armed": members}, "routine": "Constant training"}


def swordsman(i=10771, **kw):
    """B's hidden hero: a thief in the tavern among guests (the crowd rule's case)."""
    t = {"id": i, "name": NAME, "can_reach_dwarves": True, "great_danger": False, "flier": False,
         "invader": True, "layer": "upper_levels", "size": 70000, "hostile": True, "hidden": True,
         "visitor": True, "thief": "thief", "crowd": 4, "location": "INN_TAVERN",
         "pos": {"x": 113, "y": 145, "z": 171}, "distance_to_nearest_dwarf": 1, "levels_from_nearest_dwarf": 0}
    t.update(kw)
    return t


def kills(props, i):
    return [p for p in props if p.action.get("type") == "squad_orders" and i in (p.action.get("kill") or [])]


@test("B's hidden swordsman inside the tavern among guests: a squad sent at him, the reason names him")
def _():
    s = fort([swordsman()], inside=[10771])
    assert stalkers_inside(s, {t["id"]: t for t in s["others_on_map"]["threats"]}) == [10771]
    props, notes = plan(s, Memory())
    k = kills(props, 10771)
    assert k, [(p.rule, p.reason[:90]) for p in props][:25]
    assert "Swordsman" in k[0].reason and "inside the fort at x113 y145 z171" in k[0].reason, k[0].reason


@test("the Rules tab's never attack gives way to a stalker inside the walls")
def _():
    s = fort([swordsman()], inside=[10771], policy="never")
    assert kills(plan(s, Memory())[0], 10771)


@test("inside by the row's own `inside` too")
def _():
    s = fort([swordsman(inside=True)])
    assert kills(plan(s, Memory())[0], 10771)


@test("not a stalker inside: a seen guest thief among a crowd (0.105.51), one outside, a great danger, wildlife")
def _():
    threats = lambda t: {t["id"]: t}      # noqa: E731
    seen = swordsman(hidden=None)
    assert stalkers_inside(fort([seen], inside=[10771]), threats(seen)) == []
    assert stalkers_inside(fort([swordsman()]), threats(swordsman())) == []          # not inside
    g = swordsman(great_danger=True)
    assert stalkers_inside(fort([g], inside=[10771]), threats(g)) == []
    w = swordsman(animal=True, name="Giant Dingo")
    assert stalkers_inside(fort([w], inside=[10771]), threats(w)) == []
    # the seen guest thief in the tavern still gets no kill order (the crowd rule stands)
    assert not kills(plan(fort([seen], inside=[10771]), Memory())[0], 10771)


finish()
