"""(0.105.41, item 4) Provisions from the land: lua/ai-provisions.lua in a
fake fort (the report's game, hunters, butchery, hides, meals, fruit trees
and zones, cavern plots; hunters added and called in; DF's butchering and
tanning standing orders; a fruit zone; cavern soil farms), the bridge's
wiring, the Rules switches, and the brain (brain/planner_provisions.py).

    python tests/test_provisions.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish, code_has  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan, TICKS_PER_DAY  # noqa: E402
import planner_provisions as PP  # noqa: E402
import planner_labor  # noqa: E402
import planner_core  # noqa: E402
import digest  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
CFG = PLANNER_CONFIG

# A fake map: tiles outside unless W.inside["x,y,z"]; cavern tiles in
# W.cave["x,y,z"] = 'SOIL' (or another material); walk group 1 everywhere
# but W.group["x,y,z"]. Units, items, plants, zones and plots by hand.
FAKE = r"""
local src = ...
local W = {units = {}, cits = {}, items = {}, plants = {}, raws = {}, buildings = {}, site = {}, inside = {},
           cave = {}, group = {}, taken = {}, qf = {}, assigned = {}, standing = {}, labor_calls = {},
           creatures = {}, detail = nil, mode = 'OnlySelectedDoesThis', removed_workers = 0}
local env = setmetatable({}, {__index = _G})
local function key(x, y, z) return x .. ',' .. y .. ',' .. z end
-- a DF vector: 0-based, insert/erase; items() for the stubs
local function vec(t)
    local d = {}
    for i, v in ipairs(t or {}) do d[i] = v end
    local o = {}
    local methods = {
        insert = function(self, at, v) table.insert(d, at + 1, v) end,
        erase = function(self, i) table.remove(d, i + 1) end,
        items = function(self) return d end}
    return setmetatable(o, {__index = function(_, k)
        if type(k) == 'number' then return d[k + 1] end
        return methods[k]
    end, __len = function() return #d end})
end
W.vec = vec
local LABORS = {HUNT = 1, BUTCHER = 2, TANNER = 3, HERBALIST = 4}
function W.unit(t)
    t.pos = t.pos or {x = 10, y = 10, z = 100}
    t.flags1 = t.flags1 or {}
    t.military = {squad_id = t.squad or -1}
    t.status = {labors = t.labors or {}}
    t.job = {current_job = t.current_job}
    table.insert(W.units, t)
    if t.citizen then table.insert(W.cits, t) end
    return t
end
function W.item(t)
    t.flags = t.flags or {}
    t.getStackSize = function(self) return self.n or 1 end
    W.items[t.kind] = W.items[t.kind] or {}
    table.insert(W.items[t.kind], t)
    return t
end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {
    global = {world = {units = {active = W.units}, items = {other = setmetatable({}, {__index = function(_, k)
                            W.items[k] = W.items[k] or {}; return W.items[k] end})},
                       plants = {all = W.plants}, raws = {plants = {all = W.raws}},
                       buildings = {all = W.buildings}},
              cur_year = 5, cur_year_tick = 1000},
    unit_labor = setmetatable(LABORS, {__index = function() return nil end}),
    unit = {find = function(id) for _, u in ipairs(W.units) do if u.id == id then return u end end end},
    creature_raw = {find = function(r) return W.creatures[r] end},
    building_type = {Civzone = 'Civzone', [1] = 'FarmPlot', FarmPlot = 1},
    civzone_type = setmetatable({}, {__index = function(_, k) return k end}),
    job_type = setmetatable({}, {__index = function(_, k) return k end}),
}
env.df.building_type = setmetatable({Civzone = 'Civzone'}, {__index = function(_, k) return k end})
env.dfhack = {
    units = {
        isDead = function(u) return u.dead == true end, isActive = function(u) return true end,
        isAnimal = function(u) return u.animal == true end, isFortControlled = function(u) return u.tame == true end,
        isTame = function(u) return u.tame == true end, isDanger = function(u) return u.danger == true end,
        isGreatDanger = function(u) return false end, isInvader = function(u) return false end,
        isChild = function(u) return false end, isBaby = function(u) return false end,
        getCitizens = function() return W.cits end,
        getPosition = function(u) return u.pos.x, u.pos.y, u.pos.z end,
        getReadableName = function(u) return u.name or ('dwarf ' .. u.id) end,
        setAutomaticProfessions = function(u)
            local on = false
            if W.detail then for _, id in ipairs(W.detail.assigned_units:items()) do if id == u.id then on = true end end end
            u.status.labors[LABORS.HUNT] = on or u.player_hunter == true
        end,
    },
    maps = {getTileFlags = function(x, y, z)
        if type(x) == 'table' then x, y, z = x.x, x.y, x.z end
        return {outside = not W.inside[key(x, y, z)] and not W.cave[key(x, y, z)]}
    end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
    matinfo = {decode = function(it) return {material = it.mat} end},
    buildings = {findAtTile = function(p)
        for _, b in ipairs(W.buildings) do
            if b.kind == 'FarmPlot' and b.z == p.z and p.x >= b.x1 and p.x <= b.x2 and p.y >= b.y1 and p.y <= b.y2 then
                return b
            end
        end
    end},
    job = {removeWorker = function(j, c) W.removed_workers = W.removed_workers + 1 end},
}
for k, v in pairs(W.standing) do end
setmetatable(env.df.global, {__index = function(_, k)
    local name = k:match('^standing_orders_(.+)$')
    if name then return W.standing[name] end
end, __newindex = function(t, k, v)
    local name = k:match('^standing_orders_(.+)$')
    if name then W.standing[name] = v else rawset(t, k, v) end
end})
assert(load(src, 'ai-provisions', 't', env))()
-- the builder and labour stubs
local B = {}
function B.found_center() return W.centre or {x = 50, y = 50, z = 100, what = 'the wagon'} end
function B.tile_info(x, y, z)
    local m = W.cave[key(x, y, z)]
    if m then return {shape = 'FLOOR', material = m, feature_global = true, outside = false} end
    return {shape = 'FLOOR', material = 'SOIL', outside = true}
end
function B.walk_group(x, y, z) return W.group[key(x, y, z)] or 1 end
function B.tile_taken(x, y, z) return W.taken[key(x, y, z)] == true end
function B.qf_try(mode, cells, z, ax, ay, dry_run)
    table.insert(W.qf, {mode = mode, text = cells[1].text, z = z, x = ax, y = ay, dry = dry_run == true})
    if W.qf_refuse then return false, 'dry' end
    if dry_run then return true end
    local w, h = cells[1].text:match('%((%d+)x(%d+)%)')
    w, h = tonumber(w), tonumber(h)
    if mode == 'zone' then
        table.insert(W.buildings, {kind = 'Civzone', type = 'PlantGathering', x1 = ax, y1 = ay, x2 = ax + w - 1,
                                   y2 = ay + h - 1, z = z, getType = function(self) return 'Civzone' end})
    else
        table.insert(W.buildings, {kind = 'FarmPlot', x1 = ax, y1 = ay, x2 = ax + w - 1, y2 = ay + h - 1, z = z,
                                   getType = function(self) return 'FarmPlot' end})
    end
    return true
end
function B.hostile_wild(u) return u.hostile_wild == true end
local L = {}
function L.detail_for(job)
    return W.detail, W.detail and W.mode or nil
end
function L.assign(job, n, dry, txt)
    table.insert(W.labor_calls, {job = job, n = n, dry = dry == true})
    if dry then return {ok = true, dry_run = true} end
    local added = 0
    for _, u in ipairs(W.cits) do
        if added < n and not u.status.labors[LABORS.HUNT] and u.military.squad_id < 0 then
            if W.detail then W.detail.assigned_units:insert(#W.detail.assigned_units, u.id) end
            u.status.labors[LABORS.HUNT] = true
            added = added + 1
        end
    end
    return {ok = true, assigned = added}
end
env.builder = function() return B end
env.labor = function() return L end
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-provisions.lua"))
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


def citizens(lua, w, n, start=1):
    out = []
    for i in range(start, start + n):
        out.append(w.unit(T(lua, {"id": i, "citizen": True, "labors": {}})))
    return out


# --- 1. the report --------------------------------------------------------------------

@test("report hunting: wild animals on the surface (game; dangerous ones apart), not tame, caged or in a "
      "cavern; hunters outside the squads, the AI's own")
def _():
    lua, env, w = world()
    w.unit(T(lua, {"id": 50, "animal": True}))                                   # game
    w.unit(T(lua, {"id": 51, "animal": True}))
    w.unit(T(lua, {"id": 52, "animal": True, "danger": True}))                   # a danger
    w.unit(T(lua, {"id": 53, "animal": True, "tame": True}))                     # the fort's
    w.unit(T(lua, {"id": 54, "animal": True, "flags1": {"caged": True}}))
    w.unit(T(lua, {"id": 55, "animal": True, "pos": {"x": 5, "y": 5, "z": 80}}))
    w.cave["5,5,80"] = "SOIL"                                                    # in a cavern
    w.unit(T(lua, {"id": 1, "citizen": True, "labors": {1: True}}))
    w.unit(T(lua, {"id": 2, "citizen": True, "labors": {1: True}, "squad": 3}))  # a soldier
    w.unit(T(lua, {"id": 3, "citizen": True, "labors": {1: True}}))
    w.site["ai-overseer/hunters"] = T(lua, {"ids": [3]})
    h = py(env.report())["hunting"]
    assert (h["game"], h["danger"], h["hunters"], h["ai_hunters"]) == (2, 1, 2, 1), h


@test("report butchery: unbutchered bodies of beasts (forbidden apart; a sapient's never), raw hides that tan, "
      "the standing orders as 0/1, butchers and tanners")
def _():
    lua, env, w = world()
    w.creatures[1] = T(lua, {"caste": [{"flags": {}}]})
    w.creatures[2] = T(lua, {"caste": [{"flags": {"CAN_SPEAK": True}}]})
    w.item(T(lua, {"kind": "CORPSE", "race": 1, "corpse_flags": {"unbutchered": True}}))
    w.item(T(lua, {"kind": "CORPSE", "race": 1, "corpse_flags": {"unbutchered": True}, "flags": {"forbid": True}}))
    w.item(T(lua, {"kind": "CORPSE", "race": 2, "corpse_flags": {"unbutchered": True}}))      # a goblin
    w.item(T(lua, {"kind": "CORPSE", "race": 1, "corpse_flags": {"unbutchered": False}}))     # done
    w.item(T(lua, {"kind": "CORPSE", "race": 1, "corpse_flags": {"unbutchered": True}, "flags": {"rotten": True}}))
    tan = {"reaction_product": {"id": ["TAN_MAT"]}}
    w.item(T(lua, {"kind": "CORPSEPIECE", "mat": tan}))
    w.item(T(lua, {"kind": "CORPSEPIECE", "mat": tan, "flags": {"rotten": True}}))
    w.item(T(lua, {"kind": "CORPSEPIECE", "mat": {"reaction_product": {"id": []}}}))          # a bone
    w.standing["auto_butcher"] = 0
    w.standing["auto_tan"] = 1
    w.unit(T(lua, {"id": 1, "citizen": True, "labors": {2: True}}))
    b = py(env.report())["butchery"]
    assert (b["corpses"], b["corpses_forbidden"], b["hides"], b["butchers"], b["tanners"]) == (1, 1, 1, 1, 0), b
    assert b["standing"]["auto_butcher"] == 0 and b["standing"]["auto_tan"] == 1, b


@test("report meals: servings by kind (biscuits, stew, roast), rotten left out")
def _():
    lua, env, w = world()
    w.item(T(lua, {"kind": "FOOD", "n": 10, "subtype": {"id": "ITEM_FOOD_BISCUITS"}}))
    w.item(T(lua, {"kind": "FOOD", "n": 5, "subtype": {"id": "ITEM_FOOD_ROAST"}}))
    w.item(T(lua, {"kind": "FOOD", "n": 7, "subtype": {"id": "ITEM_FOOD_STEW"}, "flags": {"rotten": True}}))
    m = py(env.report())["meals"]
    assert m == {"by_kind": {"biscuits": 10, "stew": 0, "roast": 5}, "servings": 15}, m


def fruit_raws(lua, w):
    w.raws[0] = T(lua, {"flags": {"TREE": True}, "growths": [{"mat_index": 0}],
                        "material": {0: {"flags": {"EDIBLE_RAW": True}}}})
    w.raws[1] = T(lua, {"flags": {"TREE": True}, "growths": [], "material": []})        # no fruit


def tree(lua, w, x, y, z=100, mat=0):
    w.plants[len(w.plants) + 1] = T(lua, {"pos": {"x": x, "y": y, "z": z}, "material": mat})


@test("report fruit: fruit trees near the fort (a growth to eat or brew; none far, none fruitless), the fruit "
      "zones and the AI's own")
def _():
    lua, env, w = world()
    fruit_raws(lua, w)
    for x in range(40, 46):
        tree(lua, w, x, 50)
    tree(lua, w, 47, 50, mat=1)
    tree(lua, w, 200, 50)
    f = py(env.report())["fruit"]
    assert f["trees"] == 6 and f["zones"] == 0 and f["ai_zones"] == 0, f


# --- 2. the actions ---------------------------------------------------------------------

@test("hunters: more through ai-labor, the new ones remembered as the AI's; a dry run remembers nothing")
def _():
    lua, env, w = world()
    citizens(lua, w, 3)
    w.detail = T(lua, {"name": "Hunters"})
    w.detail.assigned_units = w.vec()
    r = py(env.hunters(T(lua, {"count": 2}), True))
    assert r["ok"] and not py(w.site).get("ai-overseer/hunters"), r
    r = py(env.hunters(T(lua, {"count": 2}), False))
    assert r["ok"] and r["ai_hunters"] == 2 and r["added_ids"] == [1, 2], r
    assert py(w.labor_calls)[-1] == {"job": "HUNT", "n": 2, "dry": False}
    assert not py(env.hunters(T(lua, {"count": 9}), False))["ok"]


@test("hunters stop: only the AI's hunters off the detail and the hunt dropped; the player's hunter kept; "
      "a detail set to everybody is left alone")
def _():
    lua, env, w = world()
    us = citizens(lua, w, 3)
    w.detail = T(lua, {"name": "Hunters"})
    w.detail.assigned_units = w.vec(T(lua, [1, 2, 3]))
    for u in us:
        u.status.labors[1] = True
    us[1].job.current_job = T(lua, {"job_type": "Hunt"})
    w.site["ai-overseer/hunters"] = T(lua, {"ids": [1, 2]})
    r = py(env.hunters(T(lua, {"stop": True}), True))
    assert r["ok"] and r["dry_run"] and len(py(lua.eval("function(v) return v:items() end")(w.detail.assigned_units))) == 3, r
    r = py(env.hunters(T(lua, {"stop": True}), False))
    assert r["ok"] and r["stopped"] == 2, r
    assert py(lua.eval("function(v) return v:items() end")(w.detail.assigned_units)) == [3]
    assert not us[0].status.labors[1] and not us[1].status.labors[1] and us[2].status.labors[1]
    assert w.removed_workers == 1
    assert py(w.site["ai-overseer/hunters"])["ids"] in ([], {})
    w.site["ai-overseer/hunters"] = T(lua, {"ids": [3]})
    w.mode = "EverybodyDoesThis"
    r = py(env.hunters(T(lua, {"stop": True}), False))
    assert r["rejected"] and us[2].status.labors[1], r


@test("food_standing: butchering and tanning orders turned on and remembered; any other order refused; one "
      "the AI set and the player turned off is left off")
def _():
    lua, env, w = world()
    w.standing["auto_butcher"] = 0
    w.standing["auto_tan"] = 0
    r = py(env.food_standing(T(lua, {"orders": {"auto_butcher": 1}}), True))
    assert r["ok"] and r["dry_run"] and w.standing["auto_butcher"] == 0, r
    r = py(env.food_standing(T(lua, {"orders": {"auto_butcher": 1, "auto_tan": 1}}), False))
    assert r["ok"] and w.standing["auto_butcher"] == 1 and w.standing["auto_tan"] == 1, r
    assert py(w.site["ai-overseer/food-standing"]) == {"auto_butcher": 1, "auto_tan": 1}
    w.standing["auto_butcher"] = 0                                    # the player
    r = py(env.food_standing(T(lua, {"orders": {"auto_butcher": 1}}), False))
    assert r["rejected"] and "yours" in r["error"] and w.standing["auto_butcher"] == 0, r
    assert py(env.food_standing(T(lua, {"orders": {"forbid_other_nohunt": 0}}), False))["rejected"]
    assert py(env.food_standing(T(lua, {"orders": {"auto_tan": 1}}), False))["rejected"]       # already so


@test("best_stand: the densest stand of trees, boxed with a tile round it, clamped to the side")
def _():
    lua, env, w = world()
    trees = T(lua, [{"x": 10, "y": 10, "z": 1}, {"x": 12, "y": 11, "z": 1}, {"x": 11, "y": 13, "z": 1},
                    {"x": 60, "y": 60, "z": 1}, {"x": 11, "y": 12, "z": 2}])
    box, n = env.best_stand(trees, 8, 21, 3)
    box = py(box)
    assert n == 3 and box == {"x1": 9, "y1": 9, "x2": 13, "y2": 14, "z": 1}, (n, box)
    many = T(lua, [{"x": x, "y": 10, "z": 1} for x in range(0, 60, 2)])
    box, n = env.best_stand(many, 30, 21, 3)
    box = py(box)
    assert box["x2"] - box["x1"] + 1 == 21, box


@test("fruit_zone: a 'g' zone over the stand by quickfort (dry run first), remembered; trees already zoned "
      "don't count; no stand: refused")
def _():
    lua, env, w = world()
    fruit_raws(lua, w)
    for x, y in ((40, 50), (42, 51), (41, 53), (44, 52)):
        tree(lua, w, x, y)
    r = py(env.fruit_zone(T(lua, {}), True))
    assert r["ok"] and r["dry_run"] and not py(w.site).get("ai-overseer/fruit-zones"), r
    r = py(env.fruit_zone(T(lua, {}), False))
    assert r["ok"] and r["trees"] == 4 and py(w.qf)[-1]["mode"] == "zone" and py(w.qf)[-1]["text"].startswith("g("), r
    f = py(env.report())["fruit"]
    assert f["zones"] == 1 and f["ai_zones"] == 1, f
    r = py(env.fruit_zone(T(lua, {}), False))
    assert r["rejected"], r                                  # every tree in a zone now
    lua2, env2, w2 = world()
    assert py(env2.fruit_zone(T(lua2, {}), False))["rejected"]


def cave_floor(w, x1, y1, x2, y2, z=80, mat="SOIL"):
    for x in range(x1, x2 + 1):
        for y in range(y1, y2 + 1):
            w.cave[f"{x},{y},{z}"] = mat


@test("cavern_farm: plots on the cavern's soil nearest where the fort meets it, by quickfort 'p', remembered "
      "and reported; stone floor and other walk groups never")
def _():
    lua, env, w = world()
    cave_floor(w, 20, 20, 23, 25)                 # soil 4x6 by the way in
    cave_floor(w, 24, 20, 30, 25, mat="STONE")    # stone beside it
    for y in range(20, 26):
        w.group[f"22,{y},80"] = 2                  # cut off: another walk group
    r = py(env.cavern_farm(T(lua, {"at": {"x": 20, "y": 20, "z": 80}, "tiles": 12}), True))
    assert r["ok"] and r["dry_run"] and not py(w.site).get("ai-overseer/cavern-farms"), r
    r = py(env.cavern_farm(T(lua, {"at": {"x": 20, "y": 20, "z": 80}, "tiles": 12}), False))
    assert r["ok"] and r["tiles"] >= 4, r
    for p in r["placed"]:
        for x in range(p["x"], p["x"] + p["w"]):
            for y in range(p["y"], p["y"] + p["h"]):
                assert w.cave[f"{x},{y},80"] == "SOIL" and x != 22, (x, y)
    assert all(q["text"].startswith("p(") for q in py(w.qf))
    c = py(env.report())["cavern"]
    assert c["plots"] == len(r["placed"]) and c["tiles"] == r["tiles"], c


@test("cavern_farm: refused off a cavern, with a danger near, without soil, or with bad numbers")
def _():
    lua, env, w = world()
    cave_floor(w, 20, 20, 25, 25)
    assert py(env.cavern_farm(T(lua, {"at": {"x": 5, "y": 5, "z": 100}, "tiles": 12}), False))["rejected"]
    assert py(env.cavern_farm(T(lua, {"at": {"x": 20, "y": 20, "z": 80}, "tiles": 999}), False))["rejected"]
    assert py(env.cavern_farm(T(lua, {"tiles": 12}), False))["rejected"]
    w.unit(T(lua, {"id": 70, "hostile_wild": True, "pos": {"x": 30, "y": 30, "z": 80}}))
    r = py(env.cavern_farm(T(lua, {"at": {"x": 20, "y": 20, "z": 80}, "tiles": 12}), False))
    assert r["rejected"] and "danger" in r["error"] and not py(w.qf), r
    lua, env, w = world()
    cave_floor(w, 20, 20, 25, 25, mat="STONE")
    r = py(env.cavern_farm(T(lua, {"at": {"x": 20, "y": 20, "z": 80}, "tiles": 12}), False))
    assert r["rejected"] and "soil" in r["error"], r


@test("cavern_spots: rectangles nearest the way in first, never overlapping, at least 2x2")
def _():
    lua, env, w = world()
    good = lua.eval("function(x, y, z) return x >= 0 and x < 10 and y >= 0 and y < 10 and z == 0 end")
    spots, total = env.cavern_spots(good, T(lua, {"x": 0, "y": 0, "z": 0}), 30, 12, 0, 6, 2)
    spots = py(spots)
    assert total >= 30 and spots[0]["x"] == 0 and spots[0]["y"] == 0, spots
    seen = set()
    for s in spots:
        assert s["w"] >= 2 and s["h"] >= 2
        for x in range(s["x"], s["x"] + s["w"]):
            for y in range(s["y"], s["y"] + s["h"]):
                assert (x, y) not in seen
                seen.add((x, y))


# --- 3. the bridge -------------------------------------------------------------------------

BRIDGE = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
ACTS = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
NAMES = ("hunters", "food_standing", "fruit_zone", "cavern_farm")


@test("bridge: the four actions in ACTIONS and DRY_OK, the provisions section, ai-provisions in BRIDGE_MODULES")
def _():
    dry = BRIDGE[BRIDGE.index("DRY_OK = {}"):BRIDGE.index("}) do DRY_OK[name] = true end")]
    for a in NAMES:
        assert code_has(BRIDGE, f"{a} = act_{a},"), a
        assert f"'{a}'" in dry, a
        assert f"function act_{a}(a)" in ACTS, a
    assert code_has(BRIDGE, "provisions = function() return safe(function() return reqscript('ai-provisions').report() end) end,")
    mods = BRIDGE[BRIDGE.index("BRIDGE_MODULES = {"):BRIDGE.index("}", BRIDGE.index("BRIDGE_MODULES = {"))]
    assert "'ai-provisions'" in mods
    src = (LUA_DIR / "ai-provisions.lua").read_text(encoding="utf-8")
    assert "--@ module = true" in src
    lua = LuaRuntime(unpack_returned_tuples=True)
    assert lua.eval("function(s) local f, e = load(s, 'c', 't', {}); return e end")(src) is None


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
            if n ~= 'ai-provisions' then return {} end
            local M = {}
            for _, k in ipairs({'hunters', 'food_standing', 'fruit_zone', 'cavern_farm'}) do
                M[k] = function(o, dry) seen[#seen + 1] = {k, o, dry}; return {ok = true} end
            end
            return M
        end
        assert(load(src, 'actions', 't', env))()
        return env, seen
    end""")
    env, seen = f(ACTS)
    assert env.act_hunters(T(lua, {})).rejected
    assert env.act_hunters(T(lua, {"count": 9})).rejected
    assert env.act_hunters(T(lua, {"count": 2, "dry_run": True})).ok
    assert seen[len(seen)][2].count == 2 and seen[len(seen)][3] is True
    assert env.act_hunters(T(lua, {"stop": True})).ok and seen[len(seen)][2].stop is True
    assert env.act_food_standing(T(lua, {})).rejected
    assert env.act_food_standing(T(lua, {"orders": {"auto_tan": 1}})).ok
    assert env.act_fruit_zone(T(lua, {"min_trees": 0})).rejected
    assert env.act_fruit_zone(T(lua, {"min_trees": 3})).ok
    assert env.act_cavern_farm(T(lua, {"tiles": 10})).rejected
    assert env.act_cavern_farm(T(lua, {"at": {"x": 1, "y": 2, "z": 3}, "tiles": 2})).rejected
    assert env.act_cavern_farm(T(lua, {"at": {"x": 1, "y": 2, "z": 3}, "tiles": 20, "dry_run": True})).ok
    last = seen[len(seen)]
    assert last[1] == "cavern_farm" and last[2].at.z == 3 and last[2].tiles == 20 and last[3] is True


@test("settings: the hunting and cavern_farms switches (on by default) in the settings, for the AI, the Army "
      "tab, and player_rules; overseer labels")
def _():
    st = (LUA_DIR / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    assert "hunting = true, cavern_farms = true," in st
    assert "'hunting', 'cavern_farms'," in st
    assert "hunting = s.hunting, cavern_farms = s.cavern_farms," in st
    gui = (LUA_DIR / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
    assert "{'hunting', 'Hunters (when safe):'}" in gui and "{'cavern_farms', 'Cavern-soil farms:'}" in gui
    assert "frame = {t = t + 17, l = 2 + (i - 1) * 28, w = 26}," in gui
    r = planner_core.player_rules({"settings": {}})
    assert r["hunting"] is True and r["cavern_farms"] is True
    r = planner_core.player_rules({"settings": {"hunting": False, "cavern_farms": False}})
    assert r["hunting"] is False and r["cavern_farms"] is False
    import overseer
    for a in NAMES:
        assert a in overseer.SHORT_WORDS, a


# --- 4. the brain ------------------------------------------------------------------------------

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def section(**parts) -> dict:
    out = {"hunting": {"game": 0, "danger": 0, "hunters": 0, "ai_hunters": 0, "mode": "OnlySelectedDoesThis"},
           "butchery": {"standing": {"auto_butcher": 1, "auto_tan": 1, "auto_fishery": 1}, "corpses": 0,
                        "corpses_forbidden": 0, "hides": 0, "butchers": 1, "tanners": 1, "ai_set": {}},
           "meals": {"by_kind": {"biscuits": 0, "stew": 0, "roast": 0}, "servings": 0},
           "fruit": {"zones": 0, "ai_zones": 0, "trees": 0},
           "cavern": {"plots": 0, "tiles": 0}}
    for k, v in parts.items():
        out[k] = {**out[k], **v}
    return out


def fort(pv=None, citizens=30, gear=None, shops=None) -> dict:
    s = copy.deepcopy(BASE)
    if pv is not None:
        s["provisions"] = pv
    s["dwarves"]["total"] = citizens
    s["military"]["gear"] = gear if gear is not None else {"spare_crossbows": 2, "bolts": 100, "ranged_armed": 0}
    if shops is not None:
        s["buildings"]["workshops"] = shops
    s = digest.normalize(s)
    s["others_on_map"]["threats"] = []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    return s


def run(s, memory=None):
    props, notes = [], []
    PP._provisions_rules(s, CFG, int(s["dwarves"]["total"]), props, notes, memory or Memory())
    return props, notes


def by(props, rule):
    return [p for p in props if p.rule == rule]


@test("hunting: game on the surface, crossbows and bolts to spare, no danger: a hunter or two")
def _():
    props, _ = run(fort(section(hunting={"game": 4})))
    p = by(props, "hunting")
    assert p and p[0].action == {"type": "hunters", "count": 2}, props
    props, _ = run(fort(section(hunting={"game": 4, "hunters": 1})))
    assert by(props, "hunting")[0].action["count"] == 1
    props, _ = run(fort(section(hunting={"game": 0})))
    assert not by(props, "hunting")
    props, _ = run(fort(section(hunting={"game": 4}), citizens=4))
    assert not by(props, "hunting")
    props, _ = run(fort(section(hunting={"game": 4, "mode": "NobodyDoesThis"})))
    assert not by(props, "hunting")


@test("hunting: the crossbow squads' crossbows and bolts come first")
def _():
    s = fort(section(hunting={"game": 4}), gear={"spare_crossbows": 1, "bolts": 60, "ranged_armed": 0})
    s["military"]["squads"] = [{"id": 1, "members": 1, "ai_uniform": "crossbow"}]
    props, _ = run(s)
    assert not by(props, "hunting"), props          # the one crossbow and 50 of the bolts are the squad's
    s = fort(section(hunting={"game": 4}), gear={"spare_crossbows": 3, "bolts": 100, "ranged_armed": 1})
    s["military"]["squads"] = [{"id": 1, "members": 1, "ai_uniform": "crossbow"}]
    props, _ = run(s)
    assert by(props, "hunting")[0].action["count"] == 2
    n, _ = PP.hunters_wanted(fort(section(), gear={"spare_crossbows": 5, "bolts": 30}), CFG)
    assert n == 1


@test("hunting: danger about (a reachable threat, the alarm, a dangerous beast up top, a recent threat): no "
      "new hunters and the AI's own called in; the Rules switch off calls them in too")
def _():
    s = fort(section(hunting={"game": 4, "ai_hunters": 2}))
    s["others_on_map"]["threats"] = [{"id": 9, "can_reach_dwarves": True}]
    props, _ = run(s)
    assert not by(props, "hunting") and by(props, "hunting_stop")[0].action == {"type": "hunters", "stop": True}
    m = Memory()
    m.ai_alert_raised = True
    props, _ = run(fort(section(hunting={"game": 4, "ai_hunters": 1})), m)
    assert by(props, "hunting_stop") and not by(props, "hunting")
    props, _ = run(fort(section(hunting={"game": 4, "danger": 1, "ai_hunters": 1})))
    assert by(props, "hunting_stop")
    s = fort(section(hunting={"game": 4}))
    m = Memory()
    m.last_threat_tick = planner_core.abs_tick(s) - TICKS_PER_DAY
    props, _ = run(s, m)
    assert not by(props, "hunting") and not by(props, "hunting_stop")      # none of the AI's out
    s = fort(section(hunting={"game": 4, "ai_hunters": 1}))
    s["settings"]["hunting"] = False
    props, _ = run(s)
    assert by(props, "hunting_stop") and not by(props, "hunting")
    assert PP.hunting_danger(fort(section()), Memory(), CFG) == ""


@test("butchery: bodies, hides or raw fish waiting with DF's standing order off: turned on; never one the AI "
      "set that the player turned off again")
def _():
    sec = section(butchery={"standing": {"auto_butcher": 0, "auto_tan": 0, "auto_fishery": 1}, "corpses": 2, "hides": 0})
    props, _ = run(fort(sec, shops={"Butchers": 1, "Tanners": 1}))
    p = by(props, "food_standing")
    assert p and p[0].action == {"type": "food_standing", "orders": {"auto_butcher": 1}}, props
    sec = section(butchery={"standing": {"auto_butcher": 0}, "corpses": 2, "ai_set": {"auto_butcher": 1}})
    props, _ = run(fort(sec, shops={"Butchers": 1}))
    assert not by(props, "food_standing")


@test("butchery: a butcher's shop for bodies waiting, a butcher when nobody butchers; a tanner's, a tanner and "
      "a tan order for hides; no second tan order while one is queued")
def _():
    props, _ = run(fort(section(butchery={"corpses": 3}), shops={}))
    assert by(props, "butchery_shop")[0].action["shops"] == ["Butchers"]
    props, _ = run(fort(section(butchery={"corpses": 1, "butchers": 0}), shops={"Butchers": 1}))
    assert by(props, "butchery_labor")[0].action == {"type": "assign_labor", "job": "BUTCHER", "count": 1}
    props, _ = run(fort(section(butchery={"hides": 4}), shops={}))
    assert by(props, "butchery_shop")[0].action["shops"] == ["Tanners"]
    props, _ = run(fort(section(butchery={"hides": 4, "tanners": 0}), shops={"Tanners": 1}))
    assert by(props, "butchery_labor")[0].action["job"] == "TANNER"
    props, _ = run(fort(section(butchery={"hides": 4}), shops={"Tanners": 1}))
    p = by(props, "tanning")
    assert p and p[0].action == {"type": "work_order", "recipe": "tan_hide", "amount": 4} and p[0].is_order
    s = fort(section(butchery={"hides": 4}), shops={"Tanners": 1})
    s["orders"] = [{"id": 1, "recipe": "tan_hide", "amount_left": 3, "active": True, "by_ai": True}]
    props, _ = run(s)
    assert not by(props, "tanning")


@test("fruit: fruit trees near and no fruit zone: one zoned while the surface is safe; a picker while the AI's "
      "zone stands and nobody gathers")
def _():
    props, _ = run(fort(section(fruit={"trees": 8})))
    assert by(props, "fruit_zone")[0].action == {"type": "fruit_zone", "min_trees": CFG["fruit_stand_min"]}
    props, _ = run(fort(section(fruit={"trees": 2})))
    assert not by(props, "fruit_zone")
    s = fort(section(fruit={"trees": 8}))
    s["others_on_map"]["threats"] = [{"id": 9, "can_reach_dwarves": True}]
    props, _ = run(s)
    assert not by(props, "fruit_zone")
    s = fort(section(fruit={"trees": 8, "zones": 1, "ai_zones": 1}))
    s["labor"] = {"jobs": {"gathering": {"doing": 0, "candidates": 5, "mode": "OnlySelectedDoesThis"}}}
    props, _ = run(s)
    assert not by(props, "fruit_zone")
    assert by(props, "fruit_pickers")[0].action == {"type": "assign_labor", "job": "gathering", "count": 1}


@test("meal variety: one kind most of a stocked store: a few jobs of the scarcest kind (no lavish at welfare "
      "-50); not while meals are short or an order cooks")
def _():
    assert PP.meal_variety_pick({"biscuits": 90, "stew": 10, "roast": 0}, 0, CFG) == ("roast", "prepare_lavish_meal")
    assert PP.meal_variety_pick({"biscuits": 90, "stew": 10, "roast": 0}, -60, CFG) == ("stew", "prepare_fine_meal")
    assert PP.meal_variety_pick({"biscuits": 50, "stew": 30, "roast": 20}, 0, CFG) is None
    assert PP.meal_variety_pick({}, 0, CFG) is None
    sec = section(meals={"by_kind": {"biscuits": 300, "stew": 0, "roast": 0}})
    props, _ = run(fort(sec, shops={"Kitchen": 1}))
    p = by(props, "meal_variety")
    assert p and p[0].action["recipe"] == "prepare_easy_meal" or p[0].action["recipe"] in (
        "prepare_fine_meal", "prepare_lavish_meal"), props
    assert p[0].action["amount"] == CFG["meal_variety_jobs"] and p[0].is_order
    sec = section(meals={"by_kind": {"biscuits": 20, "stew": 0, "roast": 0}})
    props, _ = run(fort(sec, shops={"Kitchen": 1}))
    assert not by(props, "meal_variety")                  # under 2 a dwarf: the food rule's
    s = fort(section(meals={"by_kind": {"biscuits": 300}}), shops={"Kitchen": 1})
    s["orders"] = [{"id": 1, "recipe": "prepare_easy_meal", "amount_left": 3, "active": True, "by_ai": True}]
    props, _ = run(s)
    assert not by(props, "meal_variety")
    props, _ = run(fort(section(meals={"by_kind": {"biscuits": 300}}), shops={}))
    assert not by(props, "meal_variety")


def cavern_fort(pv=None, **deep) -> dict:
    s = fort(pv if pv is not None else section())
    s["deep"] = {"caverns": [{"name": "Cavern1", "discovered": True, "open": True, "z_top": 80, "z_bottom": 70,
                              "junctions": [{"x": 20, "y": 20, "z": 81, "cave": {"x": 20, "y": 21, "z": 80}}]}],
                 "dangers": [], "cursed": []}
    s["deep"].update(deep)
    s["farms"]["crops"] = {"MUSHROOM_HELMET_PLUMP": {"seeds": 40, "underground": True, "seasons": [0, 1, 2, 3]}}
    s["farms"]["plot_list"] = [{"tiles": 20, "underground": False}]
    return s


@test("cavern farms: underground seeds and nowhere to sow them (the farms found no soil): plots on the open "
      "cavern's soil by where the fort meets it")
def _():
    m = Memory()
    m.farm_failure = "no soil or muddy floor"
    props, _ = run(cavern_fort(), m)
    p = by(props, "cavern_farm")
    assert p and p[0].action == {"type": "cavern_farm", "at": {"x": 20, "y": 21, "z": 80},
                                 "tiles": CFG["cavern_farm_tiles"]}, props
    props, _ = run(cavern_fort())
    assert not by(props, "cavern_farm")                   # the farms are fine: no need
    s = cavern_fort()
    s["stocks"]["drink"] = 0
    props, _ = run(s)
    assert by(props, "cavern_farm")                       # no underground plot and drink short


@test("cavern farms: not with a great beast in the caverns, a hostile creature in that cavern, a cavern not "
      "open, enough plots there already, few seeds, or the switch off")
def _():
    m = Memory()
    m.farm_failure = "no soil"
    s = cavern_fort(dangers=[{"name": "Xu", "kind": "forgotten beast", "layer": "Cavern1"}])
    assert not by(run(s, m)[0], "cavern_farm")
    s = cavern_fort()
    s["others_on_map"]["wild_hostile"] = [{"id": 3, "layer": "Cavern1"}]
    assert not by(run(s, m)[0], "cavern_farm")
    s = cavern_fort()
    s["deep"]["caverns"][0]["open"] = False
    assert not by(run(s, m)[0], "cavern_farm")
    s = cavern_fort(section(cavern={"tiles": CFG["cavern_farm_max_tiles"]}))
    assert not by(run(s, m)[0], "cavern_farm")
    s = cavern_fort()
    s["farms"]["crops"]["MUSHROOM_HELMET_PLUMP"]["seeds"] = 3
    assert not by(run(s, m)[0], "cavern_farm")
    s = cavern_fort()
    s["settings"]["cavern_farms"] = False
    assert not by(run(s, m)[0], "cavern_farm")
    s = cavern_fort()
    s["deep"] = {"error": "x"}
    assert not by(run(s, m)[0], "cavern_farm")


@test("no provisions section (an older bridge, a failed one): nothing proposed or said; plan() runs with it")
def _():
    props, notes = run(fort(None))
    assert not props and not notes
    s = fort({"error": "boom"})
    s["_errors"]["provisions"] = "boom"
    props, notes = run(s)
    assert not props and not notes
    s = fort(section(hunting={"game": 4}))
    out = plan(s, Memory())
    assert isinstance(out, (list, tuple, dict)) or out is not None


@test("labour: hunters go by their own rule (HUNT out of the waiting-work and skilled-off rules)")
def _():
    assert "HUNT" in planner_labor.OWN_LABOR_RULES
    props = []
    lb = {"waiting": [], "skilled_off": [{"labor": "HUNT", "skilled": 3, "detail": "Hunters"}]}
    planner_labor._labor_waiting_rule(lb, 30, CFG, props)
    assert not props


if LuaRuntime is None:
    finish("these tests need the lupa package (pip install lupa)")
finish()
