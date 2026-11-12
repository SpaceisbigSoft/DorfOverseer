"""(fix41) The review's findings on the food store and the alloys, one test
each (or more):

  1  the food storage level: not while the AI has a roofed food pile or a
     storage level is open; one a kitchen or still ever (memory)
  2  food lying under the sky is not counted loose
  3  a new food pile never in an open project's box nor on minecart track
  4  tin and bismuth are gear metal (not spare) while the fort alloys bronze
  5  a kitchen or still with a feeder_pile proposal this cycle is left to it
  6  the feeder pile and the furnish step clear the cached food_store
  7  the AI's piles known by building id too; the gone ones forgotten
  8  the containers' crisis words kept when the food raises the want
  9  the bronze-waits-for-fuel note once a day; value alloys only with
     the Rules' import_smelting on
  10 the alloy reaction cache is one world's
  11 the food item walk is bounded in time and says partial

    python tests/test_r41_food_fixes.py
"""

from __future__ import annotations

import ast
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, record, TICKS_PER_DAY  # noqa: E402
from planner_core import Proposal  # noqa: E402
import planner_food as PF  # noqa: E402
import planner_industry  # noqa: E402
import planner_alloys  # noqa: E402
import planner_building  # noqa: E402
import planner_wells  # noqa: E402
import digest  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = PLANNER_CONFIG
LUA_DIR = ROOT / "lua"

# the fake fort of tests/test_r41_food.py (read from its source, not imported:
# importing it would run its tests)
_SRC = (ROOT / "tests" / "test_r41_food.py").read_text(encoding="utf-8")
FAKE = next(ast.literal_eval(n.value) for n in ast.parse(_SRC).body
            if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "FAKE")


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-food-store.lua"))
    return lua, env, w


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


def py(v):
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    try:
        keys = list(v.keys())
    except AttributeError:
        return v
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in sorted(keys)]
    return {k: py(v[k]) for k in keys}


BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
KITCHEN = {"id": 7, "kind": "Kitchen", "x": 21, "y": 21, "z": 100, "elevation": 0,
           "x1": 20, "y1": 20, "x2": 22, "y2": 22}
STILL = {"id": 8, "kind": "Still", "x": 25, "y": 21, "z": 100, "elevation": 0,
         "x1": 24, "y1": 20, "x2": 26, "y2": 22}


def pile(id_, x1, y1, w=5, h=5, used=0, barrels=25, ai=True, outside=0, z=100):
    return {"id": id_, "x1": x1, "y1": y1, "x2": x1 + w - 1, "y2": y1 + h - 1, "z": z, "elevation": z - 100,
            "tiles": w * h, "used": used, "outside": outside, "barrels": barrels, "bins": 0, "ai": ai}


def section(piles=(), shops=(KITCHEN, STILL), **items):
    it = {"loose": 0, "exposed": 0, "in_containers": 0, "rotten": 0, "total": 0}
    it.update(items)
    return {"piles": [dict(p) for p in piles], "shops": [dict(s) for s in shops], "items": it, "reach": 20}


def fort(fs=None, citizens=None) -> dict:
    s = copy.deepcopy(BASE)
    if fs is not None:
        s["food_store"] = fs
    if citizens is not None:
        s["dwarves"]["total"] = citizens
    return digest.normalize(s)


def mine(s, memory=None, props=None):
    props, notes = list(props or []), []
    PF._food_store_rule(s, CFG, props, notes, memory)
    return props, notes


NO_ROOM = [dict(KITCHEN, room=False), dict(STILL, room=False)]


# --- 1 -----------------------------------------------------------------------------------

@test("1: no storage level while a storage level is open; (re-review) a roofed AI pile out of the shops' reach "
      "doesn't stop it, one within reach does")
def _():
    far_ai = pile(1, 2, 50, z=110)                          # the AI's, roofed, far from both
    props, _ = mine(fort(section([far_ai], shops=NO_ROOM), citizens=40))
    assert [x for x in props if x.rule == "food_store_level"], props
    near_ai = pile(1, 20, 24)                               # the AI's, roofed, by both
    props, _ = mine(fort(section([near_ai], shops=NO_ROOM), citizens=40))
    assert not [x for x in props if x.rule == "food_store_level"], props
    far_theirs = pile(1, 2, 50, z=110, ai=False)            # the player's far one doesn't stop it
    props, _ = mine(fort(section([far_theirs], shops=NO_ROOM), citizens=40))
    assert [x for x in props if x.rule == "food_store_level"], props
    far_sky = pile(1, 2, 50, z=110, outside=25)             # the AI's under the sky doesn't either
    props, _ = mine(fort(section([far_sky], shops=NO_ROOM), citizens=40))
    assert [x for x in props if x.rule == "food_store_level"], props
    s = fort(section(shops=NO_ROOM), citizens=40)
    s["projects"]["open"] = [{"kind": "storage", "id": 3}]
    assert not mine(s)[0]


@test("1: one storage level a kitchen or still ever: booked by record() unless refused")
def _():
    m = Memory()
    s = fort(section(shops=NO_ROOM), citizens=40)
    props, _ = mine(s, m)
    lvl = [x for x in props if x.rule == "food_store_level"]
    assert lvl and lvl[0].action["for_shops"] == [7, 8]
    record([(lvl[0], {"ok": False, "error": "no site"})], s, m)
    assert PF.food_levels(m) == set()                       # refused: asked again later
    assert [x for x in mine(s, m)[0] if x.rule == "food_store_level"]
    record([(lvl[0], {"ok": True})], s, m)
    assert PF.food_levels(m) == {7, 8}
    props, notes = mine(s, m)
    assert not [x for x in props if x.rule == "food_store_level"]
    # (re-review) said instead: the level dug already, none other
    assert any("dug a storage level for it already" in n for n in notes), notes
    # a new still with no room gets its own one
    s2 = fort(section(shops=NO_ROOM + [dict(STILL, id=9, x1=40, x2=42, room=False)]), citizens=40)
    lvl = [x for x in mine(s2, m)[0] if x.rule == "food_store_level"]
    assert lvl and lvl[0].action["for_shops"] == [9], lvl
    # the rotten-food watch keeps the levels
    s3 = fort(section(shops=NO_ROOM, rotten=1), citizens=40)
    PF.note_food(s3, m, CFG)
    assert PF.food_levels(m) == {7, 8}


# --- 2 -----------------------------------------------------------------------------------

@test("2: food lying outside a pile under the sky is not counted loose; under a roof it is")
def _():
    lua, env, w = world()
    w.outside["5,5,100"] = True
    w.item(T(lua, {"kind": "PLANT", "flags": {"on_ground": True}, "pos": {"x": 5, "y": 5, "z": 100}}))
    w.item(T(lua, {"kind": "MEAT", "flags": {"on_ground": True}, "pos": {"x": 6, "y": 5, "z": 100}}))
    it = py(env.item_counts())
    assert it["loose"] == 1 and it["total"] == 2 and not it.get("partial"), it


# --- 3 -----------------------------------------------------------------------------------

@test("3: a new food pile is never laid in an open project's box nor on minecart track")
def _():
    lua, env, w = world()
    k = w.shop(T(lua, {"type": "Kitchen", "x1": 20, "y1": 20}))
    free = py(env.inside_rect(T(lua, {"x1": 20, "y1": 20, "x2": 22, "y2": 22, "z": 100}), 3, 3, 20))
    # an open project over that spot, and track over the next
    w.projects = T(lua, {"list": [{"phase": "dig", "z": 100, "area": {"x1": free["x"], "y1": free["y"],
                                                                     "x2": free["x"] + 2, "y2": free["y"] + 2, "z": 100}},
                                  {"phase": "done", "z": 100, "area": {"x1": 0, "y1": 0, "x2": 59, "y2": 59, "z": 100}}]})
    r = py(env.inside_rect(T(lua, {"x1": 20, "y1": 20, "x2": 22, "y2": 22, "z": 100}), 3, 3, 20))
    assert r and not (abs(r["x"] - free["x"]) < 3 and abs(r["y"] - free["y"]) < 3), (free, r)
    lua.execute("""local env, W, tx, ty = ...
        local B = env.builder()
        local old = B.tile_info
        B.tile_info = function(x, y, z)
            local t = old(x, y, z)
            if x >= tx and x <= tx + 2 and y >= ty and y <= ty + 2 then t.track = true end
            return t
        end""", env, w, r["x"], r["y"])
    r2 = py(env.inside_rect(T(lua, {"x1": 20, "y1": 20, "x2": 22, "y2": 22, "z": 100}), 3, 3, 20))
    assert r2 and not (abs(r2["x"] - r["x"]) < 3 and abs(r2["y"] - r["y"]) < 3), (r, r2)
    assert k.id                                              # (the kitchen stands)


@test("7 (re-review): the reserved boxes are every box an open project keeps (p.areas too, as project_areas gives)")
def _():
    lua, env, w = world()
    B = lua.eval("""{load_projects = function() return {list = {
        {phase = 'dig', area = {x1 = 0, y1 = 0, x2 = 1, y2 = 1, z = 100},
         areas = {{x1 = 5, y1 = 5, x2 = 6, y2 = 6, z = 99}}},
        {phase = 'done', areas = {{x1 = 9, y1 = 9, x2 = 9, y2 = 9, z = 98}}}}} end}""")
    got = py(env.reserved_areas(B))
    assert sorted(a["z"] for a in got) == [99, 100], got            # the fallback: area and areas
    lua.execute("""local B = ...
        B.project_areas = function(p) local o = {}
            if p.area then table.insert(o, p.area) end
            for _, a in ipairs(p.areas or {}) do table.insert(o, a) end
            table.insert(o, {x1 = 50, y1 = 50, x2 = 50, y2 = 50, z = 120}); return o end""", B)
    got = py(env.reserved_areas(B))
    assert sorted(a["z"] for a in got) == [99, 100, 120], got        # the builder's own list


# --- 4 -----------------------------------------------------------------------------------

def metal_fort(bars, iron=False, make_gear=True):
    s = fort()
    s["military"]["gear"] = {"forges": 2, "all_bars": dict(bars)}
    s["supplies"]["fuel"] = 200
    s["settings"]["make_gear"] = make_gear
    s.setdefault("industry", {})
    if iron:
        s["industry"]["ores"] = {"IRON": 3}
    return s


@test("4: tin and bismuth are gear metal while there is no iron route (make_gear on) and (re-review) copper "
      "bars or copper ore; spare otherwise")
def _():
    bars = {"TIN": 60, "BISMUTH": 50, "SILVER": 20, "COPPER": 5}
    s = metal_fort(bars)
    assert {"TIN", "BISMUTH"} <= planner_alloys.gear_metals(s, CFG)
    assert planner_building.spare_metal(s, CFG, 2) == "SILVER"
    assert planner_wells.chain_metal(s) == "SILVER"
    assert planner_wells.chain_metal(s, CFG) == "SILVER"
    s = metal_fort(bars, iron=True)
    assert "TIN" not in planner_alloys.gear_metals(s, CFG)
    assert planner_building.spare_metal(s, CFG, 2) == "TIN"
    assert planner_wells.chain_metal(s) == "TIN"
    s = metal_fort(bars, make_gear=False)
    assert planner_building.spare_metal(s, CFG, 2) == "TIN"
    # only tin (and a little copper): the chain still takes it (the commonest gear metal), furniture doesn't
    s = metal_fort({"TIN": 60, "COPPER": 1})
    assert planner_building.spare_metal(s, CFG, 2) is None
    assert planner_wells.chain_metal(s) == "TIN"
    # (re-review) no copper bars and no copper ore: no bronze to keep tin for
    s = metal_fort({"TIN": 60, "BISMUTH": 50, "SILVER": 20})
    assert not ({"TIN", "BISMUTH"} & planner_alloys.gear_metals(s, CFG))
    assert planner_building.spare_metal(s, CFG, 2) == "TIN"
    # copper ore dug (no bars yet): kept again
    s["industry"]["ore_stock_by"] = {"malachite": {"n": 4, "metals": ["COPPER"]}}
    assert {"TIN", "BISMUTH"} <= planner_alloys.gear_metals(s, CFG)


@test("4 (re-review): well_parts_plan passes the plan's cfg on to chain_metal")
def _():
    got = []
    real = planner_wells.chain_metal
    planner_wells.chain_metal = lambda s, cfg=None: got.append(cfg) or real(s, cfg)
    try:
        s = metal_fort({"SILVER": 20})
        mycfg = dict(CFG)
        planner_wells.well_parts_plan(s, mycfg)
    finally:
        planner_wells.chain_metal = real
    assert got and got[0] is mycfg, got


@test("4: the stuck rope's chain fallback keeps the tin for bronze too")
def _():
    s = metal_fort({"TIN": 60, "SILVER": 20, "COPPER": 1})
    s["buildings"].setdefault("workshops", {})["MetalsmithsForge"] = 1
    p = Proposal("x", {"type": "work_order", "recipe": "cloth_rope", "amount": 2}, "", 5, True)
    a = planner_building.stuck_fallback(p, s, Memory(), CFG, 0)
    assert a and a["recipe"] == "metal_chain" and a["material"] == "INORGANIC:SILVER", a
    s = metal_fort({"TIN": 60, "COPPER": 1})
    s["buildings"].setdefault("workshops", {})["MetalsmithsForge"] = 1
    a = planner_building.stuck_fallback(p, s, Memory(), CFG, 0)
    assert a is None or a["material"] != "INORGANIC:TIN", a
    s = metal_fort({"TIN": 60}, iron=True)
    s["buildings"].setdefault("workshops", {})["MetalsmithsForge"] = 1
    a = planner_building.stuck_fallback(p, s, Memory(), CFG, 0)
    assert a and a["material"] == "INORGANIC:TIN", a


# --- 5 -----------------------------------------------------------------------------------

@test("5: a kitchen with a feeder_pile proposal this cycle is left to it (the still still gets its pile)")
def _():
    feeder = Proposal("feeder", {"type": "feeder_pile", "building_id": 7}, "", 6)
    props, _ = mine(fort(section(), citizens=40), props=[feeder])
    fp = [x for x in props if x.rule == "food_store"]
    assert len(fp) == 1 and fp[0].action["building_id"] == 8, props
    both = [feeder, Proposal("feeder", {"type": "feeder_pile", "building_id": 8}, "", 6)]
    props, _ = mine(fort(section(), citizens=40), props=both)
    assert not [x for x in props if x.rule.startswith("food_store")], props
    # the full piles' "more" for a kitchen being fed waits too
    full = [dict(pile(1, 30, 20, used=25), shop_id=7)]
    props, _ = mine(fort(section(full, shops=(KITCHEN,), loose=30), citizens=40), props=[feeder])
    assert not [x for x in props if x.rule == "food_store"], props


# --- 6 -----------------------------------------------------------------------------------

@test("6: the feeder pile and the furnish step clear the cached food_store section")
def _():
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    lua = LuaRuntime()
    start = src.index("CACHE_INVALIDATES = {")
    end = src.index("SECTION_CACHE = SECTION_CACHE or {}")
    lua.execute("function reqscript() return {} end\n" + src[start:end])
    ci = lua.eval("CACHE_INVALIDATES")
    assert "food_store" in list(ci.feeder_pile.values()) and "logistics" in list(ci.feeder_pile.values())
    fp = list(ci.furnish_project.values())
    assert {"food_store", "registry", "locations", "noble_rooms"} <= set(fp), fp


# --- 7 -----------------------------------------------------------------------------------

@test("7: the AI's pile remembered by its building id too; a pile gone is forgotten, and a player's pile later at "
      "the same corner is the player's")
def _():
    lua, env, w = world()
    k = w.shop(T(lua, {"type": "Kitchen", "x1": 20, "y1": 20}))
    r = py(env.food_pile(T(lua, {"building_id": k.id, "tiles": 9, "barrels": 9}), False))
    assert r["ok"] and r["pile_id"], r
    reg = py(env.registry())
    assert reg["ids"] == [r["pile_id"]] and len(reg["piles"]) == 1, reg
    # a feeder-style remember (no id given) finds the pile's id itself
    other = w.pile(T(lua, {"x1": 40, "y1": 40, "x2": 42, "y2": 42}))
    env.remember(40, 40, 100)
    assert other.id in py(env.registry())["ids"]
    # the AI's pile moved off its corner (resized): still the AI's by id
    sp = w.piles[1]
    sp.x1 = sp.x1 + 1
    rep = {p["id"]: p for p in py(env.report())["piles"]}
    assert rep[r["pile_id"]]["ai"] is True
    # both gone: forgotten at the next report
    lua.execute("local W = ...; for i = #W.piles, 1, -1 do table.remove(W.piles, i) end", w)
    env.report()
    reg = py(env.registry())
    assert not reg.get("ids") and not reg.get("piles"), reg
    theirs = w.pile(T(lua, {"x1": 40, "y1": 40, "x2": 42, "y2": 42, "barrels": 2}))
    assert py(env.report())["piles"][0]["ai"] is False
    res = py(env.food_barrels(T(lua, {"pile_id": theirs.id, "barrels": 9}), False))
    assert res["rejected"] and theirs.storage.max_barrels == 2, res


# --- 8 -----------------------------------------------------------------------------------

@test("8: the containers' crisis words stay when the food out of barrels raises the want past the brew jobs")
def _():
    s = fort(section(exposed=400, loose=100), citizens=40)
    s["supplies"]["empty_barrels"], s["supplies"]["empty_pots"] = 0, 0
    s["stocks"]["wood"], s["stocks"]["drink"] = 10000, 0
    saved = (planner_industry.drink_crisis, planner_industry.drink_target_per_dwarf)
    planner_industry.drink_crisis = lambda *a: True
    planner_industry.drink_target_per_dwarf = lambda *a: 2.0
    try:
        props, notes = [], []
        planner_industry._supply_rules(s, 40, CFG, props, notes, memory=Memory())
    finally:
        planner_industry.drink_crisis, planner_industry.drink_target_per_dwarf = saved
    p = [x for x in props if x.rule == "containers"]
    assert p and "(crisis:" in p[0].reason and "food lies out of barrels" in p[0].reason, props


# --- 9 -----------------------------------------------------------------------------------

def alloy_fort(bars, fuel, import_smelting=True, furnace="Smelter"):
    s = fort()
    s["buildings"]["furnaces"] = {furnace: 1}
    s["military"]["gear"] = {"forges": 1, "all_bars": dict(bars)}
    s["supplies"]["fuel"] = fuel
    s["settings"]["import_smelting"] = import_smelting
    return s


@test("9: the bronze-waits-for-fuel note is said once a game day, not every cycle")
def _():
    m = Memory()
    s = alloy_fort({"COPPER": 40, "TIN": 20}, 0)

    def notes_now():
        props, notes = [], []
        planner_alloys._alloy_rule(s, m, CFG, props, notes)
        return [n for n in notes if "waits for fuel" in n]
    assert len(notes_now()) == 1
    assert notes_now() == []
    s["date"]["tick"] += TICKS_PER_DAY - 1
    assert notes_now() == []
    s["date"]["tick"] += 1
    assert len(notes_now()) == 1
    props, notes = [], []                                    # without a memory: said (as before)
    planner_alloys._alloy_rule(s, None, CFG, props, notes)
    assert [n for n in notes if "waits for fuel" in n]


@test("9: value alloys only while the Rules' import_smelting is on")
def _():
    bars = {"GOLD": 200, "SILVER": 200, "COPPER": 200, "IRON": 100}
    props, notes = [], []
    planner_alloys._alloy_rule(alloy_fort(bars, 500), Memory(), CFG, props, notes)
    assert [p for p in props if p.rule == "alloy"], props
    props, notes = [], []
    planner_alloys._alloy_rule(alloy_fort(bars, 500, import_smelting=False), Memory(), CFG, props, notes)
    assert not props and not notes, (props, notes)


# --- 10 ----------------------------------------------------------------------------------

def _lua_fn(src: str, name: str) -> str:
    m = re.search(r"\nfunction " + name + r"\(.*?\nend\n", src, re.S)
    assert m, name
    return m.group(0)


@test("10: the alloy reaction cache is one world's: keyed by the save folder, emptied when the world is unloaded")
def _():
    src = (LUA_DIR / "ai-bridge-orders.lua").read_text(encoding="utf-8")
    hook = src[src.index("if dfhack and dfhack.onStateChange then\n    dfhack.onStateChange['ai-bridge-alloys']"):]
    hook = hook[:hook.index("\nend\n") + 5]
    L = LuaRuntime()
    L.execute("""
        MATS = {[1] = 'BRONZE'}
        SC_WORLD_UNLOADED, SC_MAP_UNLOADED = 'wu', 'mu'
        df = {item_type = {BAR = 1, BOULDER = 2},
              global = {world = {cur_savegame = {save_dir = 'region1'}, raws = {reactions = {reactions = {}}}}}}
        dfhack = {onStateChange = {}, matinfo = {decode = function(t, i) return {inorganic = {id = MATS[i]}} end}}
        function rx(code, reagent_types, product_type, mat)
            return {code = code, reagents = reagent_types,
                    products = {{item_type = product_type, mat_type = 0, mat_index = mat}}}
        end
        ALLOY_CACHE = {}
    """ + _lua_fn(src, "reaction_exists") + _lua_fn(src, "alloy_world") + hook + _lua_fn(src, "alloy_reaction"))
    L.execute("""
        local R = df.global.world.raws.reactions.reactions
        R[1] = rx('BRONZE_MAKING2', {{item_type = 1}, {item_type = 1}}, 1, 1)
        A1 = alloy_reaction({reaction = 'BRONZE_MAKING2', alloy = 'BRONZE'})
        R[1] = rx('MOD_BRONZE', {{item_type = 1}, {item_type = 1}}, 1, 1)
        A2 = alloy_reaction({reaction = 'BRONZE_MAKING2', alloy = 'BRONZE'})       -- same world: cached
        df.global.world.cur_savegame.save_dir = 'region2'
        A3 = alloy_reaction({reaction = 'BRONZE_MAKING2', alloy = 'BRONZE'})       -- another world: read again
        df.global.world.cur_savegame.save_dir = 'region1'
        dfhack.onStateChange['ai-bridge-alloys']('wu')
        A4 = alloy_reaction({reaction = 'BRONZE_MAKING2', alloy = 'BRONZE'})       -- unloaded: read again
    """)
    assert (L.eval("A1"), L.eval("A2"), L.eval("A3"), L.eval("A4")) == (
        "BRONZE_MAKING2", "BRONZE_MAKING2", "MOD_BRONZE", "MOD_BRONZE")


# --- 11 ----------------------------------------------------------------------------------

@test("11: the food item walk stops at its time budget and says partial; a partial count is no low for the rot watch")
def _():
    lua, env, w = world()
    for i in range(600):
        w.item(T(lua, {"kind": "PLANT", "flags": {"on_ground": True}, "pos": {"x": 5, "y": 5, "z": 100}}))
    it = py(env.item_counts(-1))
    assert it.get("partial") is True and it["total"] < 600, it
    it = py(env.item_counts())
    assert not it.get("partial") and it["total"] == 600, it
    m = Memory()
    s = fort(section(rotten=20), citizens=40)
    PF.note_food(s, m, CFG)
    s2 = fort(section(rotten=0, partial=True), citizens=40)
    s2["date"]["tick"] = s["date"]["tick"] + 1
    assert PF.note_food(s2, m, CFG) == [] and m.food_store_seen["low"] == 20
    s3 = fort(section(rotten=25), citizens=40)
    s3["date"]["tick"] = s["date"]["tick"] + 2
    assert not [n for n in PF.note_food(s3, m, CFG) if "rotted" in n]       # 5 more: under the rise


if LuaRuntime is None:
    finish("these tests need the lupa package (pip install lupa)")
finish()
