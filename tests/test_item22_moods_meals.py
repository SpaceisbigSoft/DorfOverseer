"""(0.105.123 item22) Moods that wait on silk, and good meals in a full store.

  * W1, 25 Nov 19:21-22:24, six forts: 7 moods failed, 5 for silk. The deals
    asked for silk cloth first and bought food: the caravans carried none
    (the deal now says what was on sale of its first wants). The webs
    (3,300-13,200 a fort) all lie in the sealed caverns, out of every
    Loom's reach. Silk thread is now asked for too (woven at the Loom), and a
    reserve counts only whole cloths (E: 5 yarn and 3 silk part-used).
  * B, E and F cooked 0 good meals with 2,100-4,100 in store: the lavish
    meals were cooked by anyone (the kitchens open to all, their second cook
    skill 1-3); the newest 80 meals by 30+ dwarves of skill 0-2, quality
    0-1. The best cook alone now sets the bar while the store is full.
  * A and D: cook_staff and meal_cheap on and off ~45 times in 3 h as the good
    meals crossed 2 a dwarf: hysteresis (GOOD_MEAL_LIFT).

    python tests/test_item22_moods_meals.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import planner_farms  # noqa: E402
import planner_moods  # noqa: E402
import planner_society  # noqa: E402
from planner import PLANNER_CONFIG as CFG, Memory, plan  # noqa: E402
from planner_trade import trade_wants  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["orders"] = []
    s["buildings"].setdefault("workshops", {}).update({"Kitchen": 1, "Loom": 1, "Farmers": 1})
    s.setdefault("supplies", {})
    return s


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


def cook_fort(free, kitchen_min=0, best=11, able=(11, 1, 1), staffed=(), meals_pd=21, good=0, want=37):
    """B at 22:27: 99 dwarves, 2,100 meals, 0 good, the best free cook 11 and the next 1."""
    s = fort()
    pop = s["dwarves"]["total"]
    s["needs"] = {"needs": {"EatGoodMeal": {"distracted": want, "badly": 1}}}
    s["stocks"]["prepared_meals"] = int(pop * meals_pd)
    s["supplies"].update(meal_servings=int(pop * meals_pd), good_meals=good,
                         cooks={"best": best, "skilled": 1, "kitchen_min": kitchen_min, "able_skills": list(able),
                                "free": free, "staffed": list(staffed)})
    return s


B_FREE = [{"id": 17013, "skill": 11, "cook": True, "hauls": False, "away_days": 2},
          {"id": 17014, "skill": 1, "cook": True, "hauls": True, "away_days": 2}]


@test("good_meals_short: starts under good_meals_pd a dwarf with needs_build_at wanting; held until GOOD_MEAL_LIFT times it")
def _():
    s = cook_fort(B_FREE)
    pop = s["dwarves"]["total"]
    line = CFG["good_meals_pd"] * pop
    s["supplies"]["good_meals"] = line - 1
    assert planner_farms.good_meals_short(s, CFG, pop)
    s["supplies"]["good_meals"] = line + 1
    assert not planner_farms.good_meals_short(s, CFG, pop)
    assert planner_farms.good_meals_short(s, CFG, pop, held=True)              # held: kept over the line
    s["supplies"]["good_meals"] = int(line * planner_farms.GOOD_MEAL_LIFT) + 1
    assert not planner_farms.good_meals_short(s, CFG, pop, held=True)
    s["supplies"]["good_meals"] = 0
    s["needs"]["needs"]["EatGoodMeal"]["distracted"] = 0
    assert not planner_farms.good_meals_short(s, CFG, pop, held=True)          # nobody wants one
    s["needs"]["needs"]["EatGoodMeal"]["distracted"] = 1
    assert planner_farms.good_meals_short(s, CFG, pop, held=True)
    assert not planner_farms.good_meals_short(s, CFG, pop)                     # under needs_build_at: not started
    del s["supplies"]["good_meals"]
    assert not planner_farms.good_meals_short(s, CFG, pop, held=True)          # an older report


@test("cook_staff (A, D): kept cooks stay between the line and GOOD_MEAL_LIFT times it; sent back past it")
def _():
    free = [{"id": 7, "skill": 16, "cook": True, "hauls": False, "away_days": 0},
            {"id": 9, "skill": 11, "cook": True, "hauls": False, "away_days": 0}]
    s = cook_fort(free, kitchen_min=11, best=16, able=(16, 11), staffed=(7, 9))
    pop = s["dwarves"]["total"]
    s["supplies"]["good_meals"] = int(CFG["good_meals_pd"] * pop * 1.2)       # D: 108 for 55, just over 2
    assert not by_rule(plan(s, Memory())[0], "cook_staff")                     # no "haul again"
    s["supplies"]["good_meals"] = int(CFG["good_meals_pd"] * pop * planner_farms.GOOD_MEAL_LIFT) + 1
    c = by_rule(plan(s, Memory())[0], "cook_staff")
    assert c and c[0].action.get("back") is True, [p.action for p in c]
    # not kept yet and just over the line: not started
    s = cook_fort([dict(x, hauls=True) for x in free], kitchen_min=11, best=16, able=(16, 11))
    s["supplies"]["good_meals"] = int(CFG["good_meals_pd"] * pop * 1.2)
    assert not by_rule(plan(s, Memory())[0], "cook_staff")


@test("good_cooks (B): one skill-11 cook, the next 1, 21 meals a dwarf, 0 good: the bar goes by the best (9+)")
def _():
    s = cook_fort(B_FREE)
    g = by_rule(plan(s, Memory())[0], "good_cooks")
    assert g and g[0].action == {"type": "kitchen_skill", "min_level": 9}, [p.action for p in g]
    # held at 9 while the store is over good_cook_release_pd (no drop back to "any cook")
    s["supplies"]["cooks"]["kitchen_min"] = 9
    s["stocks"]["prepared_meals"] = s["dwarves"]["total"] * 7
    assert not by_rule(plan(s, Memory())[0], "good_cooks")
    # the store under good_cook_release_pd: any cook again (hunger first)
    s["stocks"]["prepared_meals"] = s["dwarves"]["total"] * 3
    g = by_rule(plan(s, Memory())[0], "good_cooks")
    assert g and g[0].action == {"type": "kitchen_skill", "min_level": 0}, [p.action for p in g]
    # not raised while the store is under good_cook_store_pd
    s = cook_fort(B_FREE, meals_pd=7)
    g = by_rule(plan(s, Memory())[0], "good_cooks")
    assert not g or g[0].action["min_level"] == 0, [p.action for p in g]


@test("good_cooks: the best cook without the labour or long at other work: 0.105.8's two-cook bar as before")
def _():
    free = [dict(B_FREE[0], away_days=9), B_FREE[1]]
    s = cook_fort(free, kitchen_min=9)
    g = by_rule(plan(s, Memory())[0], "good_cooks")
    assert g and g[0].action == {"type": "kitchen_skill", "min_level": 0}, [p.action for p in g]
    assert not planner_society.solo_cook_bar(cook_fort([dict(B_FREE[0], cook=False)]), {"kitchen_min": 0, "best": 11,
                                             "free": [dict(B_FREE[0], cook=False)]}, CFG, 3, 99, 21)


@test("lavish_due: past meals_hard_max_pd while only skilled cooks cook (F: 55 a dwarf... 61, 0 good)")
def _():
    s = cook_fort(B_FREE, meals_pd=CFG["meals_hard_max_pd"] + 5, kitchen_min=0)
    assert not planner_society.lavish_due(s, CFG)                              # anyone cooks: the ceiling holds
    s["supplies"]["cooks"]["kitchen_min"] = 9
    assert planner_society.lavish_due(s, CFG)
    s["supplies"]["good_meals"] = CFG["good_meals_pd"] * s["dwarves"]["total"]
    assert not planner_society.lavish_due(s, CFG)


@test("mood reserves count whole cloths only (the bridge's cloth_part off cloth_kinds)")
def _():
    s = fort()
    s["supplies"]["cloth_kinds"] = {"plant": 12, "silk": 3, "yarn": 5}
    assert planner_moods.mood_reserve_counts(s)["silk_cloth"] == 3                 # an older bridge
    s["supplies"]["cloth_part"] = {"plant": 0, "silk": 3, "yarn": 4}
    c = planner_moods.mood_reserve_counts(s)
    assert (c["plant_cloth"], c["silk_cloth"], c["yarn_cloth"]) == (12, 0, 1), c
    rep = (ROOT / "lua" / "ai-bridge-report-supplies.lua").read_text(encoding="utf-8")
    assert "out.cloth_part = {plant = 0, silk = 0, yarn = 0}" in rep and "CLOTH_WHOLE = 10000" in rep


SILK = {"index": 0, "item": "CLOTH", "quantity": 1, "flags": ["silk"], "min_dim": 10000,
        "avail": {"free": 0, "reach": 0, "forbidden": 0, "forbidden_reach": 0, "dump": 0, "job": 0, "other": 0}}


def silk_fort():
    s = fort()
    s["moods"] = {"list": [{"unit_id": 17621, "name": "Fath", "mood": "Possessed", "craft": True,
                            "skill": "MECHANICS", "workshop": "Mechanics", "items_have": 9, "items_needed": 8,
                            "missing": [dict(SILK)]}]}
    return s


@test("D's Fath (silk cloth the last of 9): the deal asks silk cloth, then silk thread, before food")
def _():
    s = silk_fort()
    for k in ("prepared_meals", "meat", "fish", "cheese", "eggs", "plants"):
        s["stocks"][k] = 0
    w = trade_wants(s, CFG, int(s["dwarves"]["total"]))
    keys = [x["key"] for x in w]
    assert keys[:2] == ["CLOTH:SILK", "THREAD:SILK"], keys
    assert "FOOD" in keys and keys.index("FOOD") > 1
    # no Loom: no thread asked (nothing to weave it at)
    s["buildings"]["workshops"].pop("Loom")
    assert [x["key"] for x in planner_moods.mood_trade_wants(s)] == ["CLOTH:SILK"]


@test("the deal says what was on sale of its first wants (lua/ai-trade.lua on_sale)")
def _():
    src = (ROOT / "lua" / "ai-trade.lua").read_text(encoding="utf-8")
    assert "ON_SALE_KEYS = 4" in src and "on_sale[w.key] = n" in src
    assert src.count("on_sale = on_sale") == 2


finish()
