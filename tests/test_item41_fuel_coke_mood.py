"""(0.105.119 item41) Fuel and coke, the mood's 3x3 shop, glass with no sand.

1. coke: D, 25 Nov, a bar mood's coke order cancelled by DF "Needs refined
   coal" (twice, then five more times by the stuck sweep): the vanilla raws'
   BITUMINOUS_COAL_TO_COKE / LIGNITE_TO_COKE carry [FUEL], so at fuel 0 coke
   can't be made. The mood's fuel step makes charcoal; the fuel rule cokes
   once there is a fuel (one a job), and order_check holds a coke order with
   no fuel (it was in NO_FUEL).
2. siege (the Lua part in tests/test_r2_h7.py): a mood's shop is 3x3.
3. glass: region4-1430 has no sand in any of the six forts: a mood's raw
   glass is said once ("no sand on the map ...") and asked of caravans
   (ROUGH:GLASS), no furnace / zone / bag steps.

    python tests/test_item41_fuel_coke_mood.py
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

import planner  # noqa: E402
from planner import Memory, PLANNER_CONFIG as CFG, abs_tick, TICKS_PER_DAY  # noqa: E402
import planner_moods  # noqa: E402
import order_check  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LUA = ROOT / "lua"


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["orders"] = []
    return s


def geared() -> dict:
    s = fort()
    s["military"]["gear"] = {"soldiers": 20, "armed": 20, "armored": 20, "helmed": 20, "squads": 4,
                             "squads_with_uniform": 4, "spare": {"weapons": 0, "body": 0, "helms": 0},
                             "bars": {"IRON": 100, "STEEL": 5}, "forges": 2}
    return s


def fuel_props(s):
    return [p for p in planner.plan(s, Memory())[0] if p.rule == "fuel"]


@test("coke: order_check counts the fuel a coke job burns (DF's [FUEL]); charcoal and sand burn none")
def _():
    assert order_check.order_needs("coke_bituminous")["fuel"] is True
    assert order_check.order_needs("coke_lignite")["fuel"] is True
    assert order_check.order_needs("make_charcoal")["fuel"] is False
    s = fort()
    s["buildings"]["furnaces"] = {"Smelter": 1}
    s["supplies"]["fuel"] = 0
    r = order_check.order_feasible("coke_bituminous", s)
    assert r["ok"] is False and r["missing"] == "fuel", r


@test("fuel: coke made with one fuel in stock (the batch no bigger than the fuel); at 0 charcoal, never coke")
def _():
    s = geared()
    s["buildings"]["furnaces"].update(Smelter=1, WoodFurnace=1)
    s["industry"] = {"ores": {"IRON": {"tiles": 30, "ore": "MAGNETITE"}}}
    s["stone_use"] = {"usable": 50, "economic": {"COAL_BITUMINOUS": {"n": 39}}}
    s["supplies"]["fuel"] = 1
    f = fuel_props(s)
    assert f and f[0].action == {"type": "work_order", "recipe": "coke_bituminous", "amount": 1}, f
    s["supplies"]["fuel"] = 0
    f = fuel_props(s)
    assert f and all(p.action.get("recipe") == "make_charcoal" for p in f), [p.action for p in f]


@test("mood coke: a bar mood at fuel 0 with coal and logs burns charcoal (D, 25 Nov: 'Needs refined coal')")
def _():
    s = fort()
    s["buildings"]["furnaces"] = {"Smelter": 1, "WoodFurnace": 1}
    s.setdefault("supplies", {})["fuel"] = 0
    s["industry"] = {"ore_stock_by": {"LIMONITE": {"n": 5, "metals": ["IRON"]}}}
    s["stocks"]["wood"] = 19
    s["stone_use"] = {"economic": {"COAL_BITUMINOUS": {"n": 36}}}
    x = {"index": 0, "item": "BAR", "quantity": 1, "flags": ["metal"],
         "avail": {"free": 0, "reach": 0, "forbidden": 0, "forbidden_reach": 0, "dump": 0, "job": 0, "other": 0,
                   "held": 0, "trader": 0, "hospital": 0}}
    m = Memory()
    acts, why = planner_moods._mood_make(s, x, "bar", m, CFG, mood={"name": "Nil", "unit_id": 5})
    recipes = [a.get("recipe") for a, _ in acts]
    assert why is None and recipes == ["make_charcoal"], (acts, why)
    assert "make coke" not in (LUA.parent / "brain" / "planner_moods.py").read_text(encoding="utf-8")


def glass_fort(sand_layers):
    s = fort()
    s["supplies"].update({"sand_layers": sand_layers, "sand_bags": 0, "sand_zones": 0, "empty_bags": 4,
                          "fuel": 5})
    s["buildings"]["furnaces"] = {"GlassFurnace": 1}
    s["trade"] = dict(s.get("trade") or {}, depot=True)
    x = {"index": 0, "item": "ROUGH", "material": "green glass", "quantity": 3, "flags": ["glass"],
         "avail": {"free": 0, "reach": 0, "forbidden": 0, "forbidden_reach": 0, "dump": 0, "job": 0, "other": 0,
                   "held": 0, "trader": 0, "hospital": 0}}
    s["moods"] = {"list": [{"unit_id": 9, "name": "Urist", "mood": "Fey", "craft": True, "skill": "GLASSMAKER",
                            "workshop": "GlassFurnace", "items_have": 0, "items_needed": 1, "missing": [x]}]}
    return s, x


@test("mood glass: no sand on the map -> said once a mood, raw glass asked of caravans, no zone/bag steps")
def _():
    s, x = glass_fort([])
    assert planner_moods.no_sand(s)
    acts, why = planner_moods._mood_make(s, x, "glass_rough", Memory(), CFG, mood={"name": "Urist", "unit_id": 9})
    assert not acts and "no sand on this map" in why and "caravans" in why, (acts, why)
    wants = planner_moods.mood_trade_wants(s)
    assert {"key": "ROUGH:GLASS", "count": 3} in wants, wants
    mem = Memory()
    mem.moods_seen = {"9": abs_tick(s) - 2 * TICKS_PER_DAY}
    n1, n2 = [], []
    planner_moods._mood_rules(s, mem, CFG, [], n1)
    planner_moods._mood_rules(s, mem, CFG, [], n2)
    said = "no sand on the map: raw glass can't be made; asked of caravans"
    assert sum(said in n for n in n1) == 1 and not any(said in n for n in n2), (n1, n2)
    # sand in the geology (or an older bridge, no sand_layers): not said, the old route
    s2, x2 = glass_fort(["sand"])
    assert not planner_moods.no_sand(s2)
    acts, why = planner_moods._mood_make(s2, x2, "glass_rough", Memory(), CFG, mood={"name": "Urist", "unit_id": 9})
    assert acts and acts[0][0].get("type") == "sand_zone", (acts, why)
    s3, _ = glass_fort([])
    del s3["supplies"]["sand_layers"]
    assert not planner_moods.no_sand(s3)


@test("trade Lua: raw glass is ROUGH:GLASS (apart from gems), matched by the want's key")
def _():
    src = (LUA / "ai-trade.lua").read_text(encoding="utf-8")
    i = src.index("function category(item)")
    body = src[i:src.index("\nend", i)]
    assert "'ROUGH:GLASS'" in body and body.index("'ROUGH:GLASS'") < body.index("SIMPLE[tname]"), body
    assert len(src.replace("\r", "").encode("utf-8")) <= 60000


finish()
