"""(0.105.113 item10) Meals' worth and the metal industry's trade.

- meal_drink: drink kept from the cooks while the meals are at their target
  (a barrel cooked: 25-30 servings worth the drink's 2-3 each), lifted when
  they fall under half of it; the 0.105.78 cap still holds.
- metal_trade_wants: steel/iron bars, pig iron, flux and iron ore bought when
  the smelter and forge need them, scaled by Greed.

    python tests/test_item10_meals_trade.py
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

from planner import PLANNER_CONFIG, Memory, plan, record  # noqa: E402
import planner_farms  # noqa: E402
import planner_guards  # noqa: E402
from planner_trade import metal_trade_wants, metal_buy_scale, trade_wants  # noqa: E402
import overseer_words  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG


def fort(wanting: bool = True) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["buildings"].setdefault("workshops", {})["Kitchen"] = 1
    if wanting:      # E, 25 Nov: 73 distracted for want of a good meal, 11 of 5,824 servings worth over 20
        s.setdefault("needs", {}).setdefault("needs", {})["EatGoodMeal"] = {"distracted": 20, "badly": 5}
        s.setdefault("supplies", {})["good_meals"] = 10
    return s


def drink_rule(s, m):
    props: list = []
    planner_farms._meal_drink_rule(s, m, CFG, props)
    return props


@test("meal_drink: meals at their target and drink in store: the cooks leave drink alone")
def _():
    s = fort()
    pop = int(s["dwarves"]["total"])
    s["stocks"].update(prepared_meals=pop * CFG["meals_per_dwarf"], drink=500)
    p = drink_rule(s, Memory())
    assert p and p[0].rule == "meal_drink" and p[0].action == {"type": "kitchen_drinks", "ban": True}, p
    # nobody wanting a good meal, good meals enough, or an older report: nothing asked
    q = copy.deepcopy(s); q["needs"]["needs"]["EatGoodMeal"]["distracted"] = 1
    assert not drink_rule(q, Memory())
    q = copy.deepcopy(s); q["supplies"]["good_meals"] = 2 * int(q["dwarves"]["total"])
    assert not drink_rule(q, Memory())
    q = copy.deepcopy(s); q["supplies"].pop("good_meals")
    assert not drink_rule(q, Memory())
    assert p[0].priority >= 8, p                    # never ahead of the fort's urgent work
    # in the whole plan too
    assert any(x.rule == "meal_drink" for x in plan(copy.deepcopy(s), Memory())[0])


@test("meal_drink: meals short: no ban; banned and under half the target: lifted; no kitchen or memory: nothing")
def _():
    s = fort()
    pop = int(s["dwarves"]["total"])
    target = pop * CFG["meals_per_dwarf"]
    s["stocks"].update(prepared_meals=target - 1, drink=500)
    assert not drink_rule(s, Memory())
    m = Memory()
    m.drink_cook_ban = True
    assert not drink_rule(s, m)                      # between half and the target: kept as it is
    s["stocks"]["prepared_meals"] = int(target * planner_farms.MEAL_DRINK_LIFT) - 1
    p = drink_rule(s, m)
    assert p and p[0].action == {"type": "kitchen_drinks", "ban": False}, p
    s["stocks"]["prepared_meals"] = target * 2
    s["stocks"]["drink"] = 0
    assert not drink_rule(s, Memory())               # no drink to keep
    s["stocks"]["drink"] = 50
    assert not drink_rule(s, None)
    s["buildings"]["workshops"].pop("Kitchen")
    assert not drink_rule(s, Memory())


@test("meal_drink: the ban recorded in memory when the bridge did it; a week between asks; words for the log")
def _():
    s = fort()
    m = Memory()
    s["stocks"].update(prepared_meals=10 ** 5, drink=500)
    p = [x for x in plan(copy.deepcopy(s), m)[0] if x.rule == "meal_drink"]
    assert p, "no meal_drink"
    record([(p[0], {"ok": True})], s, m)
    assert m.drink_cook_ban is True
    from planner_core_base import COOLDOWN_KEYS
    assert COOLDOWN_KEYS["meal_drink"] == "fat_ban_cooldown_ticks" and CFG["fat_ban_cooldown_ticks"] == 7 * 1200
    assert overseer_words.short({"type": "kitchen_drinks", "ban": True}) == "keep drink from the cooks"
    assert overseer_words.short({"type": "kitchen_drinks", "ban": False}) == "let the cooks use drink again"


@test("food: the 3x cap (0.105.78) still holds a lavish order")
def _():
    s = fort()
    from planner import Proposal
    pop = int(s["dwarves"]["total"])
    s["stocks"]["prepared_meals"] = pop * CFG["meals_per_dwarf"] * 3
    p = Proposal("food", {"type": "work_order", "recipe": "prepare_lavish_meal", "amount": 5}, "x", 2, True)
    notes: list = []
    assert planner_guards.meal_glut_filter(s, CFG, [p], notes) == [] and notes


def metal_fort(**gear) -> dict:
    s = fort()
    s["buildings"].setdefault("furnaces", {})["Smelter"] = 1
    g = s.setdefault("military", {}).setdefault("gear", {})
    g.update({"forges": 1, "bars": {"IRON": 60, "STEEL": 9}, "pig_iron": 0})
    g.update(gear)
    s["industry"] = {"flux_stock": 3, "ore_stock_by": {"HEMATITE": {"n": 20, "metals": ["IRON"]}},
                     "ores": {"IRON": {"ore": "HEMATITE", "tiles": 500}}}
    return s


@test("metal wants: F's case (60 iron, 9 steel, 3 flux): steel, pig iron and flux; no iron, no ore")
def _():
    w = dict(metal_trade_wants(metal_fort(), CFG, {}))
    assert w.get("BAR:STEEL") == 30 and w.get("BAR:PIG_IRON") == 10, w
    assert w.get("BOULDER:FLUX") == 17 and "BAR:IRON" not in w and "BOULDER:ORE_IRON" not in w, w
    keys = [x["key"] for x in trade_wants(metal_fort(), CFG, 20, {})]
    assert keys.index("BAR:STEEL") < keys.index("BOULDER:FLUX"), keys


@test("metal wants: no iron ore here and few bars: ore bought; flux enough: none; steel enough: no flux or pig iron")
def _():
    s = metal_fort(bars={"IRON": 4, "STEEL": 0})
    s["industry"] = {"flux_stock": 30, "ore_stock_by": {}, "ores": {}}
    w = dict(metal_trade_wants(s, CFG, {}))
    assert w.get("BOULDER:ORE_IRON") == 15 and w.get("BAR:IRON") == CFG["trade_bars_iron"] - 4, w
    assert "BOULDER:FLUX" not in w, w
    s = metal_fort(bars={"IRON": 60, "STEEL": CFG["steel_want"]})
    w = dict(metal_trade_wants(s, CFG, {}))
    assert not w, w


@test("metal wants: Greed scales them (generous more, grasping less); no forge or smelter, or Make gear off: none")
def _():
    assert metal_buy_scale({"greed": -100}) == 1.5 and metal_buy_scale({"greed": 100}) == 0.5
    assert metal_buy_scale({}) == 1.0 and metal_buy_scale(None) == 1.0
    gen = dict(metal_trade_wants(metal_fort(), CFG, {"greed": -100}))
    grasp = dict(metal_trade_wants(metal_fort(), CFG, {"greed": 100}))
    assert gen["BAR:STEEL"] == 45 and grasp["BAR:STEEL"] == 15 and grasp["BOULDER:FLUX"] == 8, (gen, grasp)
    s = metal_fort(forges=0)
    s["buildings"]["furnaces"] = {}
    assert metal_trade_wants(s, CFG, {}) == []


@test("trade_deal's wants carry the Greed-scaled metal (the fort's traits)")
def _():
    s = metal_fort()
    s["settings"]["traits"] = {"greed": 100}
    s["trade"] = {"depot": True, "caravans": [{"civ": "the Mountainhomes", "state": "AtDepot"}], "goods": 0,
                  "at_depot": 30, "screen": {"open": True, "ready": True, "by_ai": True}}
    s["stocks"].update(drink=10 ** 6, prepared_meals=10 ** 6)
    d = [p for p in plan(s, Memory())[0] if p.rule == "trade_deal"]
    assert d, "no trade_deal"
    w = {x["key"]: x["count"] for x in d[0].action["wants"]}
    assert w.get("BAR:STEEL") == 15 and w.get("BOULDER:FLUX") == 8, w


finish()
