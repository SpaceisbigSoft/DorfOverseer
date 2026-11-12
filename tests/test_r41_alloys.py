"""(0.105.40 M7) Alloys at the smelter: a fort without iron makes bronze (or
bismuth bronze) from copper and tin for its gear, within fuel and caps; tin
ore smelted and mined for it; precious metals alloyed only where the alloy is
worth more; nothing at all on a fort without these bars. The bridge's alloy
recipes and their fallback reaction lookup in a real Lua 5.3 engine.

    python tests/test_r41_alloys.py
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish  # noqa: E402

import planner_alloys as pa  # noqa: E402
import planner_core  # noqa: E402
from planner import Memory, plan, PLANNER_CONFIG as CFG  # noqa: E402
import test_planner as TPL  # noqa: E402

test = make_test()


def no_iron_fort(bars: dict, fuel: int = 40, magma: bool = False) -> dict:
    s = TPL.geared(bars=dict(bars))
    g = s["military"]["gear"]
    g["all_bars"] = dict(bars)
    g.pop("pig_iron", None)
    s["buildings"]["furnaces"] = {"MagmaSmelter": 1} if magma else {"Smelter": 1, "WoodFurnace": 1}
    s["supplies"]["fuel"] = fuel
    s["industry"] = {"ores": {"COPPER": {"ore": "MALACHITE", "tiles": 40}}, "ore_stock_by": {}, "flux_stock": 0}
    s["orders"] = [o for o in s["orders"] if not str(o.get("recipe", "")).startswith("alloy_")]
    return s


def alloys(s):
    return [p for p in plan(s, Memory())[0] if p.rule == "alloy"]


@test("copper and tin, no iron: a bronze order for the gear")
def _():
    a = alloys(no_iron_fort({"COPPER": 30, "TIN": 4}))
    assert a and a[0].action == {"type": "work_order", "recipe": "alloy_bronze", "amount": 4}, a
    assert a[0].is_order and "no iron here" in a[0].reason, a


@test("with bismuth too: bismuth bronze (four bars from a tin)")
def _():
    a = alloys(no_iron_fort({"COPPER": 30, "TIN": 4, "BISMUTH": 2}))
    assert a and a[0].action == {"type": "work_order", "recipe": "alloy_bismuth_bronze", "amount": 2}, a


@test("no tin: nothing (bismuth and copper alone make no bronze)")
def _():
    assert not alloys(no_iron_fort({"COPPER": 30}))
    assert not alloys(no_iron_fort({"COPPER": 30, "BISMUTH": 5}))


@test("an iron fort (bars, iron ore dug, or a vein uncovered): no bronze for gear")
def _():
    assert not alloys(no_iron_fort({"COPPER": 30, "TIN": 4, "IRON": 20}))
    s = no_iron_fort({"COPPER": 30, "TIN": 4})
    s["industry"]["ore_stock_by"] = {"HEMATITE": {"metals": ["IRON"], "n": 3}}
    assert not alloys(s)
    s = no_iron_fort({"COPPER": 30, "TIN": 4})
    s["industry"]["ores"]["IRON"] = {"ore": "MAGNETITE", "tiles": 10}
    assert not alloys(s)


@test("fuel short: the bronze waits and says so; a magma smelter needs none")
def _():
    s = no_iron_fort({"COPPER": 30, "TIN": 4}, fuel=1)
    p, notes = plan(s, Memory())
    assert not [x for x in p if x.rule == "alloy"], p
    assert any("waits for fuel" in n for n in notes), notes
    a = alloys(no_iron_fort({"COPPER": 30, "TIN": 4}, fuel=0, magma=True))
    assert a and a[0].action["recipe"] == "alloy_bronze", a


@test("caps: enough bronze already, or an alloy order queued -> nothing; the batch is capped")
def _():
    assert not alloys(no_iron_fort({"COPPER": 30, "TIN": 4, "BRONZE": CFG["alloy_bronze_want"]}))
    s = no_iron_fort({"COPPER": 30, "TIN": 4})
    s["orders"].append({"id": 999, "recipe": "alloy_bronze", "by_ai": True, "amount_left": 2, "amount_total": 2})
    assert not alloys(s)
    a = alloys(no_iron_fort({"COPPER": 60, "TIN": 40}))
    assert a[0].action["amount"] == CFG["alloy_batch"], a
    # copper kept back for a job being made now
    assert not alloys(no_iron_fort({"COPPER": CFG["alloy_copper_keep"], "TIN": 4}))


@test("the Rules switch make_gear off: no bronze for gear")
def _():
    s = no_iron_fort({"COPPER": 30, "TIN": 4})
    s["settings"]["make_gear"] = False
    assert not alloys(s)


@test("copper and tin ore but no tin bars: the tin ore smelted (smelting stops at the gear-metal line)")
def _():
    s = no_iron_fort({"COPPER": 60})
    s["industry"]["ore_stock_by"] = {"CASSITERITE": {"metals": ["TIN"], "n": 7}}
    a = alloys(s)
    assert a and a[0].action == {"type": "work_order", "recipe": "smelt_ore", "amount": 7,
                                 "material": "INORGANIC:CASSITERITE"}, a


@test("no iron, copper in hand, a tin vein: the tin vein is the one mined")
def _():
    s = no_iron_fort({"COPPER": 20})
    ores = {"COPPER": {"ore": "MALACHITE", "tiles": 40}, "TIN": {"ore": "CASSITERITE", "tiles": 9}}
    assert pa.tin_ore_first(s, CFG, ores) == "TIN"
    s2 = no_iron_fort({"COPPER": 20, "TIN": 2})
    assert pa.tin_ore_first(s2, CFG, ores) is None
    s3 = no_iron_fort({"COPPER": 2})
    assert pa.tin_ore_first(s3, CFG, ores) is None
    s4 = no_iron_fort({"COPPER": 20})
    assert pa.tin_ore_first(s4, CFG, dict(ores, IRON={"ore": "HEMATITE", "tiles": 9})) is None
    s["industry"]["ores"] = ores
    s["labor"] = dict(s.get("labor") or {}, dig=0, miners=3)
    s["industry"]["ore_stock"] = 0
    p = [x for x in plan(s, Memory())[0] if x.rule == "ore"]
    assert p and p[0].action["metal"] == "TIN", p


@test("value: spare silver and copper -> sterling silver at low priority; not when fuel is short")
def _():
    s = no_iron_fort({"COPPER": 40, "SILVER": 40, "IRON": 50})
    a = alloys(s)
    assert a and a[0].action["recipe"] == "alloy_sterling_silver" and a[0].priority == 7, a
    s["supplies"]["fuel"] = CFG["alloy_value_fuel_min"] - 1
    assert not alloys(s)


@test("value: the game's own values decide (an alloy worth less than its parts is never made)")
def _():
    s = no_iron_fort({"COPPER": 40, "SILVER": 40, "GOLD": 40, "IRON": 50})
    vals = dict(pa.VANILLA_VALUES)
    vals.update({"ROSE_GOLD": 1, "STERLING_SILVER": 1, "ELECTRUM": 1, "BLACK_BRONZE": 1, "BILLON": 1, "BRASS": 1})
    s["military"]["gear"]["bar_values"] = vals
    assert not alloys(s)
    vals["ROSE_GOLD"] = 40
    a = alloys(s)
    assert a and a[0].action["recipe"] == "alloy_rose_gold", a


@test("value alloys leave the copper the bronze still wants")
def _():
    s = no_iron_fort({"COPPER": 25, "SILVER": 40, "TIN": 0})
    assert not [p for p in alloys(s) if p.action["recipe"] == "alloy_sterling_silver"]


@test("gear metals best first: steel > iron > bronze > bismuth bronze > copper (brain and bridge)")
def _():
    assert planner_core.GEAR_METALS == ("STEEL", "IRON", "BRONZE", "BISMUTH_BRONZE", "COPPER")
    src = (ROOT / "lua" / "ai-military-gear.lua").read_text(encoding="utf-8")
    assert "GEAR_METALS = {'STEEL', 'IRON', 'BRONZE', 'BISMUTH_BRONZE', 'COPPER'}" in src
    s = TPL.geared(armed=12, bars={"BRONZE": 30, "COPPER": 100})
    arms = [p for p in plan(s, Memory())[0] if p.rule == "arms"]
    assert arms and arms[0].action["material"] == "INORGANIC:BRONZE", arms


@test("identity: forts without tin, zinc, gold or silver bars propose and note nothing new")
def _():
    for s in (TPL.fort(), TPL.geared(), no_iron_fort({"COPPER": 30})):
        p, notes = plan(copy.deepcopy(s), Memory())
        assert not [x for x in p if x.rule == "alloy"], p
        assert not [n for n in notes if "bronze" in n], notes
    for name in ("region2-0.83-y62-spring.json", "enxah-0.104.52-y73-winter.json"):
        import json
        from digest import normalize
        raw = json.loads((ROOT / "tests" / "fixtures" / "real" / name).read_text(encoding="utf-8"))
        p, _ = plan(normalize(raw), Memory())
        assert not [x for x in p if x.rule == "alloy"], (name, p)


@test("every alloy recipe is a bridge recipe at the smelter")
def _():
    src = (ROOT / "lua" / "ai-bridge-orders.lua").read_text(encoding="utf-8")
    for metal, (recipe, parts, out) in pa.ALLOYS.items():
        code = metal + "_MAKING"
        assert re.search(rf"\n    {recipe} = {{job = 'CustomReaction', reaction = '{code}', alloy = '{metal}'}}", src), recipe
        assert planner_core.RECIPE_SHOPS[recipe] == "Smelter"


def _lua_fn(src: str, name: str) -> str:
    m = re.search(r"\nfunction " + name + r"\(.*?\nend\n", src, re.S)
    assert m, name
    return m.group(0)


@test("bridge (lua): the alloy reaction is the raws' code, else the bars-only smelter reaction making that metal")
def _():
    try:
        from lupa.lua53 import LuaRuntime
    except ImportError:
        return
    src = (ROOT / "lua" / "ai-bridge-orders.lua").read_text(encoding="utf-8")
    L = LuaRuntime()
    L.execute("""
        MATS = {[1] = 'BRONZE', [2] = 'TIN', [3] = 'BRASS'}
        df = {item_type = {BAR = 1, BOULDER = 2},
              global = {world = {raws = {reactions = {reactions = {}}}}}}
        dfhack = {matinfo = {decode = function(t, i) return {inorganic = {id = MATS[i]}} end}}
        function ipairs0(t) return ipairs(t) end
        function rx(code, reagent_types, product_type, mat)
            return {code = code, reagents = reagent_types,
                    products = {{item_type = product_type, mat_type = 0, mat_index = mat}}}
        end
    """ + _lua_fn(src, "reaction_exists") + "\nALLOY_CACHE = {}\n" + _lua_fn(src, "alloy_reaction"))
    L.execute("""
        local R = df.global.world.raws.reactions.reactions
        R[1] = rx('BRONZE_MAKING', {{item_type = 1}, {item_type = 1}}, 1, 1)
        A1 = alloy_reaction({reaction = 'BRONZE_MAKING', alloy = 'BRONZE'})
        R[1] = rx('MOD_BRONZE_ORE', {{item_type = 2}}, 1, 1)
        R[2] = rx('MOD_BRONZE', {{item_type = 1}, {item_type = 1}}, 1, 1)
        ALLOY_CACHE = {}
        A2 = alloy_reaction({reaction = 'BRONZE_MAKING', alloy = 'BRONZE'})
        A3 = alloy_reaction({reaction = 'BRASS_MAKING', alloy = 'BRASS'}) or 'none'
    """)
    assert L.eval("A1") == "BRONZE_MAKING"
    assert L.eval("A2") == "MOD_BRONZE"            # the ore reaction passed over
    assert L.eval("A3") == "none"


@test("lua files compile")
def _():
    try:
        from lupa.lua53 import LuaRuntime
    except ImportError:
        return
    L = LuaRuntime()
    load = L.eval("function(src, name) local f, e = load(src, name, 't', {}); return e end")
    for name in ("ai-bridge-orders.lua", "ai-military-gear.lua"):
        err = load((ROOT / "lua" / name).read_text(encoding="utf-8"), name)
        assert err is None, err


finish()
