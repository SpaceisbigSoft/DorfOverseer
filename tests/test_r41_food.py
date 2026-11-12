"""(0.105.40b, M6) The food store: lua/ai-food-store.lua in a fake fort (the
report's piles, barrels, fullness, the AI's own piles, the kitchens and
stills, the food out of piles and barrels and the rotten; food_pile placing
a roofed pile near a kitchen and setting its barrels; food_barrels on the
AI's piles only), the bridge's wiring, and the brain (brain/planner_food.py:
a missing pile placed, its barrels set, a full one enlarged, no room a
storage level, spoilage said and the cats kept, barrels ordered through the
container rule, the player's piles untouched, and plan() and note_cycle()
without a food_store section the same as main's).

    python tests/test_r41_food.py
"""

from __future__ import annotations

import atexit
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish, code_has  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan, note_cycle, TICKS_PER_DAY  # noqa: E402
import planner_food as PF  # noqa: E402
import planner_industry  # noqa: E402
import digest  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
CFG = PLANNER_CONFIG

# A fort level at z 100: floor over x 0..59, y 0..59 (walls round it), roofed
# unless W.outside["x,y,z"]. Stockpiles: W.pile{...}; workshops: W.shop{...};
# items: W.item{...}. The builder (tile_info, qf_try, tile_taken,
# load_projects) is a stub over the same map; quickfort's 'place' makes a
# stockpile (max barrels 0, as a stub of the game's default).
FAKE = r"""
local src = ...
local W = {piles = {}, shops = {}, site = {}, outside = {}, used = {}, taken = {}, projects = {list = {}},
           qf = {}, items = {}, next_id = 500}
local env = setmetatable({}, {__index = _G})
local function key(x, y, z) return x .. ',' .. y .. ',' .. z end
function W.pile(t)
    t.id = t.id or W.next_id; W.next_id = W.next_id + 1
    t.z = t.z or 100
    t.settings = t.settings or {flags = {food = t.food ~= false}}
    t.storage = t.storage or {max_barrels = t.barrels or 0, max_bins = 0}
    table.insert(W.piles, t)
    return t
end
function W.shop(t)
    t.id = t.id or W.next_id; W.next_id = W.next_id + 1
    t.z = t.z or 100
    t.x2, t.y2 = t.x1 + 2, t.y1 + 2
    t.centerx, t.centery = t.x1 + 1, t.y1 + 1
    t.getBuildStage = function() return 1 end
    t.getMaxBuildStage = function() return 1 end
    table.insert(W.shops, t)
    return t
end
W.lists = {}
function W.item(t)
    t.flags = t.flags or {}
    t.pos = t.pos or {x = 1, y = 1, z = 100}
    t.getType = function(self) return self.kind end
    W.lists[t.kind] = W.lists[t.kind] or {}
    table.insert(W.lists[t.kind], t)
    return t
end
local function in_pile(x, y, z)
    for _, p in ipairs(W.piles) do
        if p.z == z and x >= p.x1 and x <= p.x2 and y >= p.y1 and y <= p.y2 then return p end
    end
end
local function in_shop(x, y, z)
    for _, b in ipairs(W.shops) do
        if b.z == z and x >= b.x1 and x <= b.x2 and y >= b.y1 and y <= b.y2 then return b end
    end
end
local function find(id)
    for _, p in ipairs(W.piles) do if p.id == id then return p end end
    for _, b in ipairs(W.shops) do if b.id == id then return b end end
end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {
    global = {world = {buildings = {other = {STOCKPILE = W.piles, WORKSHOP_ANY = W.shops}},
                       items = {other = W.lists}, map = {region_z = 100}}},
    building = {find = find},
    workshop_type = setmetatable({}, {__index = function(_, k) return k end}),
    item_type = setmetatable({}, {__index = function(_, k) return k end}),
}
env.dfhack = {
    maps = {getTileFlags = function(x, y, z)
        local p = in_pile(x, y, z)
        return {pile = p ~= nil, outside = W.outside[key(x, y, z)] == true}, {item = W.used[key(x, y, z)] == true}
    end},
    items = {getPosition = function(it) return it.pos.x, it.pos.y, it.pos.z end,
             getContainer = function(it) return it.container end},
    buildings = {findAtTile = function(p) return in_pile(p.x, p.y, p.z) end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
assert(load(src, 'ai-food-store', 't', env))()
local B = {}
function B.tile_info(x, y, z)
    if z ~= 100 or x < 0 or y < 0 or x > 59 or y > 59 then return {shape = 'WALL'} end
    return {shape = in_shop(x, y, z) and 'FLOOR' or 'FLOOR', building = in_shop(x, y, z) ~= nil,
            outside = W.outside[key(x, y, z)] == true}
end
function B.tile_taken(x, y, z) return W.taken[key(x, y, z)] == true end
function B.load_projects() return W.projects end
function B.qf_try(mode, cells, z, ax, ay, dry_run)
    table.insert(W.qf, {mode = mode, text = cells[1].text, z = z, x = ax, y = ay, dry = dry_run == true})
    if W.qf_refuse then return false, 'dry' end
    if dry_run then return true end
    local w, h = cells[1].text:match('f%((%d+)x(%d+)%)')
    W.pile{x1 = ax, y1 = ay, x2 = ax + tonumber(w) - 1, y2 = ay + tonumber(h) - 1, z = z}
    return true
end
env.builder = function() return B end
return env, W
"""


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


# --- 1. the report ---------------------------------------------------------------------

@test("report: food piles with box, tiles, used, barrels, open sky, distance to the kitchen; the AI's own by its "
      "registry and its levels' place cells; the player's not")
def _():
    lua, env, w = world()
    k = w.shop(T(lua, {"type": "Kitchen", "x1": 20, "y1": 20}))
    mine = w.pile(T(lua, {"x1": 25, "y1": 20, "x2": 27, "y2": 22, "barrels": 3}))
    lvl = w.pile(T(lua, {"x1": 40, "y1": 40, "x2": 44, "y2": 44}))
    theirs = w.pile(T(lua, {"x1": 10, "y1": 10, "x2": 11, "y2": 11}))
    w.pile(T(lua, {"x1": 50, "y1": 50, "x2": 51, "y2": 51, "food": False}))      # takes no food: not listed
    env.remember(25, 20, 100)
    w.projects = T(lua, {"list": [{"z": 100, "anchor": {"x": 30, "y": 30}, "cells": {"place": [{"x": 10, "y": 10, "text": "f(5x5)"}]}}]})
    w.used["25,20,100"] = True
    w.used["26,20,100"] = True
    w.outside["10,10,100"] = True
    r = py(env.report())
    rows = {p["id"]: p for p in r["piles"]}
    assert set(rows) == {mine.id, lvl.id, theirs.id}, rows
    m = rows[mine.id]
    assert (m["tiles"], m["used"], m["barrels"], m["ai"], m["dist"], m["shop"]) == (9, 2, 3, True, 3, "Kitchen"), m
    assert rows[lvl.id]["ai"] is True and rows[lvl.id]["tiles"] == 25
    assert rows[theirs.id]["ai"] is False and rows[theirs.id]["outside"] == 1
    assert r["piles"][0]["id"] == mine.id                 # nearest the kitchen first
    s = r["shops"][0]
    assert s["kind"] == "Kitchen" and s["pile"] == mine.id and s["dist"] == 3 and "room" not in s


@test("report: a kitchen with no food pile near says whether a roofed pile would fit (room)")
def _():
    lua, env, w = world()
    w.shop(T(lua, {"type": "Still", "x1": 20, "y1": 20}))
    r = py(env.report())
    assert r["shops"][0]["room"] is True and r["shops"][0].get("dist") is None
    for x in range(0, 60):
        for y in range(0, 60):
            w.outside[f"{x},{y},100"] = True                # all under the sky
    assert py(env.report())["shops"][0]["room"] is False


@test("report: food items lying outside a pile, in a pile out of a container, in barrels and pots, rotten")
def _():
    lua, env, w = world()
    w.pile(T(lua, {"x1": 30, "y1": 30, "x2": 32, "y2": 32}))
    barrel = T(lua, {"kind": "BARREL", "getType": None})
    lua.execute("local b = ...; b.getType = function(self) return self.kind end", barrel)
    w.item(T(lua, {"kind": "PLANT", "flags": {"on_ground": True}, "pos": {"x": 5, "y": 5, "z": 100}}))           # loose
    w.item(T(lua, {"kind": "FOOD", "flags": {"on_ground": True, "rotten": True}, "pos": {"x": 6, "y": 5, "z": 100}}))
    w.item(T(lua, {"kind": "MEAT", "flags": {"on_ground": True}, "pos": {"x": 31, "y": 31, "z": 100}}))          # exposed
    w.item(T(lua, {"kind": "DRINK", "flags": {"in_inventory": True}, "container": barrel}))                       # in a barrel
    w.item(T(lua, {"kind": "PLANT", "flags": {"on_ground": True, "forbid": True}, "pos": {"x": 7, "y": 5, "z": 100}}))
    w.item(T(lua, {"kind": "FISH", "flags": {"removed": True}}))
    it = py(env.report())["items"]
    assert it == {"loose": 2, "exposed": 1, "in_containers": 1, "rotten": 1, "total": 5}, it


# --- 2. the actions ----------------------------------------------------------------------

@test("food_pile: a missing pile is placed on roofed floor near the kitchen, sized as asked, its max barrels set, "
      "remembered as the AI's own")
def _():
    lua, env, w = world()
    k = w.shop(T(lua, {"type": "Kitchen", "x1": 20, "y1": 20}))
    for x in range(0, 60):                      # the rows just round the kitchen are open to the sky
        for y in (18, 19):
            w.outside[f"{x},{y},100"] = True
    r = py(env.food_pile(T(lua, {"building_id": k.id, "tiles": 16, "barrels": 16}), False))
    assert r["ok"] and r["w"] == 4 and r["h"] == 4 and r["barrels"] == 16, r
    new = [p for p in py(w.piles)]
    assert len(new) == 1
    p = w.piles[1]
    assert p.storage.max_barrels == 16
    assert all(not w.outside[f"{x},{y},100"] for x in range(p.x1, p.x2 + 1) for y in range(p.y1, p.y2 + 1))
    assert max(k.x1 - p.x2, p.x1 - k.x2, k.y1 - p.y2, p.y1 - k.y2) >= 2      # never touching the kitchen
    assert f"{p.x1},{p.y1},100" in py(env.registry())["piles"]
    assert py(env.report())["piles"][0]["ai"] is True


@test("food_pile: refused while a food pile is near (anyone's), unless more; a dry run places nothing")
def _():
    lua, env, w = world()
    k = w.shop(T(lua, {"type": "Kitchen", "x1": 20, "y1": 20}))
    w.pile(T(lua, {"x1": 30, "y1": 20, "x2": 31, "y2": 21}))
    r = py(env.food_pile(T(lua, {"building_id": k.id, "tiles": 9}), False))
    assert r["rejected"] and "already" in r["error"], r
    r = py(env.food_pile(T(lua, {"building_id": k.id, "tiles": 9, "more": True}), True))
    assert r["ok"] and r["dry_run"] and len(py(w.piles)) == 1 and not py(env.registry())["piles"], r
    r = py(env.food_pile(T(lua, {"building_id": k.id, "tiles": 9, "more": True}), False))
    assert r["ok"] and len(py(w.piles)) == 2
    assert py(env.food_pile(T(lua, {"building_id": 99999}), False))["rejected"]


@test("food_pile: no roofed floor in reach: not placed, says so")
def _():
    lua, env, w = world()
    k = w.shop(T(lua, {"type": "Kitchen", "x1": 20, "y1": 20}))
    for x in range(0, 60):
        for y in range(0, 60):
            w.outside[f"{x},{y},100"] = True
    r = py(env.food_pile(T(lua, {"building_id": k.id, "tiles": 9}), False))
    assert not r["ok"] and r["room"] is False and not py(w.qf), r


@test("food_barrels: the AI's pile takes the barrels; the player's pile is refused and left exactly as it was")
def _():
    lua, env, w = world()
    mine = w.pile(T(lua, {"x1": 30, "y1": 30, "x2": 32, "y2": 32}))
    theirs = w.pile(T(lua, {"x1": 40, "y1": 40, "x2": 42, "y2": 42, "barrels": 2}))
    env.remember(30, 30, 100)
    r = py(env.food_barrels(T(lua, {"pile_id": mine.id, "barrels": 9}), True))
    assert r["ok"] and mine.storage.max_barrels == 0          # a dry run changes nothing
    r = py(env.food_barrels(T(lua, {"pile_id": mine.id, "barrels": 50}), False))
    assert r["ok"] and r["barrels"] == 9 and mine.storage.max_barrels == 9, r      # at most a barrel a tile
    r = py(env.food_barrels(T(lua, {"pile_id": theirs.id, "barrels": 9}), False))
    assert r["rejected"] and "player" in r["error"] and theirs.storage.max_barrels == 2, r


# --- 3. the bridge -------------------------------------------------------------------------

BRIDGE = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
ACTS = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")


@test("bridge: food_pile and food_barrels in ACTIONS and DRY_OK, the food_store section (cached a day, cleared by "
      "the actions), ai-food-store in BRIDGE_MODULES; the kitchen's feeder pile remembered as the AI's")
def _():
    dry = BRIDGE[BRIDGE.index("DRY_OK = {}"):BRIDGE.index("}) do DRY_OK[name] = true end")]
    for a in ("food_pile", "food_barrels"):
        assert code_has(BRIDGE, f"{a} = act_{a},"), a
        assert f"'{a}'" in dry, a
        assert f"function act_{a}(a)" in ACTS
        assert f"CACHE_INVALIDATES.{a} = {{'food_store'" in BRIDGE
    assert code_has(BRIDGE, "food_store = function() return safe(function() return reqscript('ai-food-store').report() end) end,")
    assert "SECTION_CACHE_DAYS.food_store = 1" in BRIDGE
    mods = BRIDGE[BRIDGE.index("BRIDGE_MODULES = {"):BRIDGE.index("}", BRIDGE.index("BRIDGE_MODULES = {"))]
    assert "'ai-food-store'" in mods
    rooms = (LUA_DIR / "ai-builder-rooms.lua").read_text(encoding="utf-8")
    assert "reqscript('ai-food-store').remember(r.x, r.y, r.z)" in rooms
    src = (LUA_DIR / "ai-food-store.lua").read_text(encoding="utf-8")
    lua = LuaRuntime(unpack_returned_tuples=True)
    assert lua.eval("function(s) local f, e = load(s, 'c', 't', {}); return e end")(src) is None
    assert "--@ module = true" in src


@test("bridge: the handlers check their numbers and pass dry_run on")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    f = lua.eval("""function(src)
        local seen = {}
        local env = setmetatable({BRIDGE_VERSION = 'x', OUT_DIR = '/tmp'}, {__index = _G})
        env.require = function(n) return {} end
        env.reject = function(m) return {ok = false, rejected = true, error = m} end
        env.whole_number = function(v) return math.tointeger(tonumber(v)) end
        env.int_in = function(v, lo, hi) local n = math.tointeger(tonumber(v)); if n == nil or n < lo or n > hi then return nil end return n end
        env.reqscript = function(n)
            assert(n == 'ai-food-store')
            return {food_pile = function(o, dry) seen[#seen + 1] = {'pile', o, dry}; return {ok = true} end,
                    food_barrels = function(o, dry) seen[#seen + 1] = {'barrels', o, dry}; return {ok = true} end}
        end
        assert(load(src, 'actions', 't', env))()
        return env, seen
    end""")
    env, seen = f(ACTS)
    assert env.act_food_pile(T(lua, {})).rejected
    assert env.act_food_pile(T(lua, {"building_id": 3, "tiles": 999})).rejected
    assert env.act_food_barrels(T(lua, {"pile_id": 3})).rejected
    assert env.act_food_pile(T(lua, {"building_id": 3, "tiles": 16, "barrels": 16, "more": True, "dry_run": True})).ok
    last = seen[len(seen)]
    assert last[1] == "pile" and last[2].tiles == 16 and last[2].more is True and last[3] is True
    assert env.act_food_barrels(T(lua, {"pile_id": 3, "barrels": 9})).ok
    assert seen[len(seen)][2].barrels == 9 and seen[len(seen)][3] is False


# --- 4. the brain ------------------------------------------------------------------------------

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


def mine(s, memory=None):
    props, notes = [], []
    PF._food_store_rule(s, CFG, props, notes, memory)
    return props, notes


@test("brain: a kitchen with no food pile near: one placed beside it, sized by the citizens, a barrel a tile")
def _():
    props, _ = mine(fort(section(), citizens=40))
    p = [x for x in props if x.rule == "food_store"]
    assert len(p) == 1, props
    a = p[0].action
    assert a == {"type": "food_pile", "building_id": 7, "tiles": 20, "barrels": 20, "reach": 20}, a
    props, _ = mine(fort(section(), citizens=500))
    assert props[0].action["tiles"] == CFG["food_store_tiles_max"]
    props, _ = mine(fort(section(), citizens=4))
    assert not props                                     # a handful of dwarves: not yet
    props, _ = mine(fort(section(shops=()), citizens=40))
    assert not props                                     # no kitchen nor still yet


@test("brain: a pile near but open to the sky doesn't count: a roofed one beside it (more); far piles don't count")
def _():
    props, _ = mine(fort(section([pile(1, 30, 20, outside=20)]), citizens=40))
    a = [x for x in props if x.rule == "food_store"][0].action
    assert a["more"] is True and a["building_id"] == 7
    props, _ = mine(fort(section([pile(1, 50, 50, z=104)]), citizens=40))      # 28 across, 4 levels down
    assert [x for x in props if x.rule == "food_store"][0].action.get("more") is None
    props, _ = mine(fort(section([pile(1, 30, 20)]), citizens=40))
    assert not [x for x in props if x.rule.startswith("food_store")], props


@test("brain: no room near the kitchen and still: a storage level of food piles (not beside another storage level)")
def _():
    sh = [dict(KITCHEN, room=False), dict(STILL, room=False)]
    props, _ = mine(fort(section(shops=sh), citizens=40))
    p = [x for x in props if x.rule == "food_store_level"]
    assert p and p[0].action == {"type": "start_project", "kind": "storage", "piles": ["food"], "room_size": 7}
    s = fort(section(shops=sh), citizens=40)
    s["projects"]["open"] = [{"kind": "storage", "id": 3}]
    props, _ = mine(s)
    assert not props


@test("brain: the AI's own food pile near the kitchen with too few barrels is set to a barrel a tile; the player's "
      "pile is never touched")
def _():
    props, _ = mine(fort(section([pile(1, 30, 20, barrels=0)]), citizens=40))
    p = [x for x in props if x.rule == "food_barrels"]
    assert p and p[0].action == {"type": "food_barrels", "pile_id": 1, "barrels": 25}, props
    props, _ = mine(fort(section([pile(1, 30, 20, barrels=0, ai=False)]), citizens=40))
    assert not props, props                                # the player's: no barrels, no new pile (it is near)
    props, _ = mine(fort(section([pile(1, 30, 20, barrels=25)]), citizens=40))
    assert not props


@test("brain: the near piles full and food lying about: another beside them; not past the cap; not with little loose")
def _():
    full = [pile(1, 30, 20, used=25)]
    props, _ = mine(fort(section(full, loose=30), citizens=40))
    a = [x for x in props if x.rule == "food_store"][0].action
    assert a["more"] is True and a["tiles"] == 20, a
    props, _ = mine(fort(section(full, loose=3), citizens=40))
    assert not props
    big = [pile(i, 30, 20 + 6 * i, w=5, h=5, used=25) for i in range(3)]       # 75 tiles: past 3 x 20
    props, _ = mine(fort(section(big, loose=30), citizens=40))
    assert not props
    props, _ = mine(fort(section([pile(1, 30, 20, used=25, ai=False)], loose=30), citizens=40))
    a = [x for x in props if x.rule == "food_store"][0].action       # the player's full: the AI's own beside it
    assert a["more"] is True


@test("brain: spoilage risen: said once (note_cycle), the cats kept from the butcher for the window")
def _():
    m = Memory()
    s = fort(section([pile(1, 30, 20)], rotten=2, loose=12, exposed=7), citizens=40)
    assert note_cycle(copy.deepcopy(s), m) == [] or not any("rotted" in n for n in note_cycle(copy.deepcopy(s), m))
    s2 = copy.deepcopy(s)
    s2["food_store"]["items"]["rotten"] = 15
    s2["date"]["tick"] += TICKS_PER_DAY
    notes = note_cycle(copy.deepcopy(s2), m)
    said = [n for n in notes if "rotted" in n]
    assert said and said[0].startswith("13 more food items rotted"), notes
    assert not [n for n in note_cycle(copy.deepcopy(s2), m) if "rotted" in n]      # once
    s2["needs"] = {"vermin_hunters": {"n": 6, "loose": 5, "kept": 0}}
    props, _ = mine(s2, m)
    p = [x for x in props if x.action.get("type") == "keep_mousers"]
    assert p and p[0].rule == "vermin" and p[0].action["count"] == 4, props
    s3 = copy.deepcopy(s2)
    s3["date"]["tick"] += 40 * TICKS_PER_DAY
    props, _ = mine(s3, m)
    assert not [x for x in props if x.action.get("type") == "keep_mousers"]


@test("brain: food out of barrels raises the container rule's want (barrels ordered as it always does)")
def _():
    assert PF.food_containers_want(fort(), CFG) == 0
    assert PF.food_containers_want(fort(section(exposed=5)), CFG) == 0
    s = fort(section(exposed=120, loose=30), citizens=40)
    assert PF.food_containers_want(s, CFG) == 15
    s["supplies"]["empty_barrels"], s["supplies"]["empty_pots"] = 3, 0
    s["stocks"]["wood"] = 10000
    props, notes = [], []
    planner_industry._supply_rules(s, 40, CFG, props, notes)
    p = [x for x in props if x.rule == "containers"]
    assert p and p[0].action["recipe"] == "wooden_barrel" and "food lies out of barrels" in p[0].reason, props


@test("brain: plan() carries the rules, the config is food_-prefixed, the labels, the digest line")
def _():
    m = Memory()
    props, _ = plan(fort(section(), citizens=40), m)
    assert any(p.rule == "food_store" for p in props), [p.rule for p in props]
    for r in ("food_store", "food_barrels", "food_store_level"):
        assert f"{r}_cooldown_ticks" in CFG
    import overseer
    for a in ("food_pile", "food_barrels"):
        assert a in overseer.SHORT_WORDS
    line = digest.food_line(fort(section([pile(1, 30, 20, used=5, barrels=0)], rotten=4)))
    assert line.startswith("FOOD_STORE piles 1") and "rotten 4" in line and "taking no barrels: 1" in line
    assert digest.food_line(fort()) == ""
    assert "FOOD_STORE" in digest.digest(fort(section()))


# --- 5. identity: without a food_store section, plan() is main's --------------------------

PROBE = r'''
import copy, json, sys
from pathlib import Path
brain = Path(sys.argv[1]); sys.path.insert(0, str(brain))
fixtures = Path(sys.argv[2])
from digest import normalize, digest
from planner import Memory, plan, record, select, note_cycle, TICKS_PER_DAY
out = {}
for path in [fixtures / "test_fort.json"] + sorted((fixtures / "real").glob("*.json")):
    base = json.loads(path.read_text(encoding="utf-8"))
    for slow in (False, True):
        s = copy.deepcopy(base)
        if slow:
            s["fps_low"] = 8
        s = normalize(s)
        m = Memory()
        cycles = []
        for _ in range(3):
            n = note_cycle(copy.deepcopy(s), m)
            props, notes = plan(copy.deepcopy(s), m)
            cycles.append({"props": [[p.rule, json.dumps(p.action, sort_keys=True, default=str), p.reason,
                                      p.priority] for p in props], "notes": notes, "cycle": n,
                           "digest": digest(copy.deepcopy(s))})
            allowed, _ = select(props, s, m)
            record([(p, {"ok": False, "error": "refused (test)"}) for p in allowed], s, m)
            s["date"]["tick"] = s["date"].get("tick", 0) + TICKS_PER_DAY
        out[f"{path.name}:{slow}"] = cycles
print(json.dumps(out, sort_keys=True))
'''

_MAIN = {}


def main_brain() -> Path | None:
    if "dir" not in _MAIN:
        tmp = tempfile.mkdtemp(prefix="r41-food-main-")
        arch = subprocess.run(["git", "-C", str(ROOT), "archive", "main", "brain"], capture_output=True)
        if arch.returncode != 0:
            _MAIN["dir"] = None
        else:
            subprocess.run(["tar", "-x", "-C", tmp], input=arch.stdout, check=True)
            _MAIN["dir"] = Path(tmp) / "brain"
            atexit.register(shutil.rmtree, tmp, True)
    return _MAIN["dir"]


def probe(brain: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "probe.py"
        p.write_text(PROBE, encoding="utf-8")
        r = subprocess.run([sys.executable, "-I", str(p), str(brain), str(ROOT / "tests" / "fixtures")],
                           capture_output=True, text=True, env=dict(os.environ, DFAI_LOG_DIR=tmp), cwd=tmp)
    assert r.returncode == 0, r.stderr[-1500:]
    return r.stdout.strip().splitlines()[-1]


@test("no food_store section in the report: plan(), note_cycle() and the digest are main's, byte for byte "
      "(every fixture, slow and not, 3 cycles)")
def _():
    main = main_brain()
    assert main is not None, "no main branch to compare with"
    a, b = probe(main), probe(ROOT / "brain")
    if a != b:
        ja, jb = json.loads(a), json.loads(b)
        bad = [k for k in ja if ja[k] != jb.get(k)]
        raise AssertionError(f"differs from main at {bad[:3]}")


if LuaRuntime is None:
    finish("these tests need the lupa package (pip install lupa)")
finish()
