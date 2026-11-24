"""(0.105.94) Two of B's daily miseries the AI failed at (the Monastery, 23 Nov,
53% unhappy, 25 miserable, tantrums killing).

1. Cups: 16 citizens upset at drinking without a cup; the comfort rule's stone
   mugs were held every cycle ("11 stone the masons may use, 15 of them
   claimed by the AI's open orders") while 325 logs lay in store, because
   stone_short saw 11 usable against stone_low 10. Now wooden cups whenever
   the mugs would be held for stone and there's wood (comfort and tavern).
2. Chronic tantrums: Mebzuth's BeExtravagant drew give_trinkets 28 times an
   hour, refused "nobody wants something to own": give_trinkets reaches only
   dwarves wanting AcquireObject. BeExtravagant alone no longer maps to it.

    python tests/test_r94_tantrum.py
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

from planner import PLANNER_CONFIG  # noqa: E402
import planner_society as PS  # noqa: E402
import planner_tantrums as PT  # noqa: E402
from cup_material import cup_recipe  # noqa: E402

CFG = dict(PLANNER_CONFIG)
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def cup_fort(usable=11, claimed=15, wood=325, cupless=16, citizens=75) -> dict:
    s = copy.deepcopy(BASE)
    s["dwarves"]["total"] = citizens
    s["needs"] = {"clothing": {"citizens": citizens, "without": {"shoes": 0}, "free_shoes": 50, "free_cups": 0,
                               "free_cups_detail": {"n": 0, "why": {}, "why_locations": {}, "place": {}}},
                  "stress_causes": {"days": 28, "causes": [{"thought": "DrinkWithoutCup", "citizens": cupless}]}}
    s["stone_use"] = {"usable": usable}
    s.setdefault("stocks", {})["wood"] = wood
    s["orders"] = ([{"id": 1, "recipe": "stone_blocks", "amount_left": claimed, "by_ai": True}] if claimed else [])
    return s


def cups(props):
    return [p for p in props if p.action.get("recipe") in ("stone_mugs", "wooden_cups")]


@test("1. B: 11 usable stone, all claimed by open orders, 325 logs: wooden cups (was: stone mugs, held each cycle)")
def _():
    s = cup_fort()
    assert cup_recipe(s, CFG, 10) == "wooden_cups"
    props = []
    PS._comfort_rules(s, CFG, props, [])
    c = cups(props)
    assert c and c[0].action["recipe"] == "wooden_cups" and "no stone to spare" in c[0].reason, \
        [(p.action, p.reason) for p in props]


@test("1. stone to spare (40 usable, none claimed): stone mugs as before; no wood: stone mugs (held, as before)")
def _():
    assert cup_recipe(cup_fort(usable=40, claimed=0), CFG, 10) == "stone_mugs"
    assert cup_recipe(cup_fort(wood=5), CFG, 10) == "stone_mugs"
    assert cup_recipe(cup_fort(usable=3, claimed=0), CFG, 10) == "wooden_cups"      # stone short: as before


def chronic_row(unmet):
    return {"id": 17182, "name": "Mebzuth", "unmet": unmet, "bedroom": True}


@test("2. BeExtravagant alone: no give_trinkets (it reaches only AcquireObject); with AcquireObject too: given")
def _():
    s = copy.deepcopy(BASE)
    s["needs"] = {"trinkets": 200}
    acts = PT.chronic_need_actions(s, CFG, chronic_row(["BeExtravagant"]))
    assert not [a for a in acts if a[1].get("type") == "give_trinkets"], acts
    acts = PT.chronic_need_actions(s, CFG, chronic_row(["BeExtravagant", "AcquireObject"]))
    assert [a for a in acts if a[1].get("type") == "give_trinkets"], acts
    acts = PT.chronic_need_actions(s, CFG, chronic_row(["AcquireObject"]))
    assert [a for a in acts if a[1].get("type") == "give_trinkets"], acts


finish()
