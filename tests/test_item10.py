"""(item10) Training benches, cavern logging, the grove and leather armour:
lua/ai-benches.lua, lua/ai-forestry.lua and lua/ai-leather-gear.lua in a fake
fort, the bridge's wiring, and the brain (brain/planner_benches.py,
planner_forestry.py, planner_leather.py).

    python tests/test_item10.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
import planner_benches as PB  # noqa: E402
import planner_forestry as PF  # noqa: E402
import planner_leather as PL  # noqa: E402
import planner_core  # noqa: E402
import digest  # noqa: E402
import overseer  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
CFG = dict(PLANNER_CONFIG)

FAKE = r"""
local src = ...
local W = {site = {}, tiles = {}, units = {}, plants = {}, shops = {}, dangers = {}, squads = {}, items = {},
           una = {}, walk_z = {}}
local env = setmetatable({}, {__index = _G})
local function both(t)
    local out = {}
    for k, v in pairs(t) do out[k] = v; out[v] = k end
    return out
end
local ident = setmetatable({}, {__index = function(_, k) return k end})
local function key(x, y, z) return x .. ',' .. y .. ',' .. z end
W.key = key
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {
    global = {cur_year = 5, cur_year_tick = 1000,
              plotinfo = {site_id = 7, group_id = 1, equipment = {items_unassigned = W.una}},
              world = {buildings = {other = {WORKSHOP_ANY = W.shops}}, plants = {all = W.plants},
                       units = {active = {}}, items = {other = W.items}}},
    workshop_type = both({Carpenters = 0, Masons = 1, Kitchen = 2, Craftsdwarfs = 3, Jewelers = 4}),
    job_skill = both({CARPENTRY = 1, MASONRY = 2, STONECRAFT = 3, CUTGEM = 4, CLOTHESMAKING = 5,
                      LEATHERWORK = 6, BOWYER = 7, MECHANICS = 8}),
    unit_labor = both({CARPENTER = 1, MASON = 2, STONE_CRAFT = 3, CUT_GEM = 4, CLOTHESMAKER = 5,
                       LEATHER = 6, BOWYER = 7, MECHANIC = 8}),
    tiletype = {attrs = setmetatable({}, {__index = function(_, t) return W.tiles[t] end})},
    tiletype_shape = ident, tiletype_material = ident,
    tile_dig_designation = {No = 'No', Default = 'Default'},
    tile_traffic = {Normal = 'Normal', Restricted = 'Restricted'},
    tile_building_occ = {None = 'None'},
    uniform_category = both({body = 0, head = 1, pants = 2, gloves = 3, shoes = 4}),
    entity_material_category = both({Leather = 1, Armor = 2}),
    item_type = both({ARMOR = 10, HELM = 11, PANTS = 12, GLOVES = 13, SHOES = 14}),
    historical_entity = {find = function(id) return id == 1 and {squads = {1}} or nil end},
    squad = {find = function(id) return W.squads[id] end},
}
env.dfhack = {
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
    units = {getCitizens = function() return W.units end,
             getNominalSkill = function(u, sk) return u.skills[sk] or 0 end,
             getPosition = function(u) return u.pos.x, u.pos.y, u.pos.z end},
    maps = {
        getTileType = function(x, y, z) if W.tiles[key(x, y, z)] then return key(x, y, z) end end,
        getTileFlags = function(x, y, z)
            local t = W.tiles[key(x, y, z)]
            if not t then return nil end
            return t, t
        end,
        getTileBlock = function() return {flags = {}} end,
        getPlantAtTile = function(x, y, z) return W.plant_at[key(x, y, z)] end,
        canWalkBetween = function(a, b) return W.walk_z[b.z] == true and W.walk_z[a.z] == true
            and (W.tiles[key(b.x, b.y, b.z)] or {}).wall ~= true end,
    },
    designations = {
        markPlant = function(p) W.tiles[key(p.pos.x, p.pos.y, p.pos.z)].dig = 'Default'; return true end,
        unmarkPlant = function(p) W.tiles[key(p.pos.x, p.pos.y, p.pos.z)].dig = 'No'; return true end,
    },
    items = {getSubtypeDef = function(t, s) return {id = W.subdefs[t .. ':' .. s]} end,
             getHolderUnit = function() return nil end},
    matinfo = {decode = function(it) return {material = {flags = {LEATHER = it.leather == true}}} end},
}
W.plant_at = {}
W.subdefs = {['10:0'] = 'ITEM_ARMOR_LEATHER', ['10:1'] = 'ITEM_ARMOR_MAIL_SHIRT', ['11:0'] = 'ITEM_HELM_CAP',
             ['12:0'] = 'ITEM_PANTS_LEGGINGS', ['13:0'] = 'ITEM_GLOVES_GLOVES', ['14:0'] = 'ITEM_SHOES_BOOTS'}

-- a tile: {shape, material, outside, feature_global, hidden, dig, traffic, building}
function W.tile(x, y, z, o)
    local t = {shape = o.shape or 'FLOOR', material = o.material or 'SOIL', outside = o.outside == true,
               feature_global = o.cave == true, feature_local = false, hidden = o.hidden == true,
               dig = o.dig or 'No', traffic = o.traffic or 'Normal', flow_size = 0,
               building = o.building or 'None', wall = o.wall}
    W.tiles[key(x, y, z)] = t
    return t
end
function W.tree(x, y, z, o)
    o = o or {}
    o.shape, o.material, o.wall = 'WALL', 'TREE', true
    W.tile(x, y, z, o)
    local p = {pos = {x = x, y = y, z = z}}
    table.insert(W.plants, p)
    W.plant_at[key(x, y, z)] = p
    -- the ground round the trunk, for the woodcutter to stand on
    for dy = -1, 1 do for dx = -1, 1 do
        if not W.tiles[key(x + dx, y + dy, z)] then W.tile(x + dx, y + dy, z, {outside = o.outside, cave = o.cave}) end
    end end
    return p
end
function W.sapling(x, y, z)
    W.tile(x, y, z, {shape = 'SAPLING', outside = true})
    local p = {pos = {x = x, y = y, z = z}}
    table.insert(W.plants, p)
    W.plant_at[key(x, y, z)] = p
end
function W.shop(id, kind, x, y, z, prof)
    prof = prof or {}
    local b = {id = id, type = env.df.workshop_type[kind], centerx = x, centery = y, z = z, jobs = {},
               profile = {max_level = prof.max or 3000, min_level = prof.min or 0, permitted_workers = prof.workers or {}},
               getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end}
    table.insert(W.shops, b)
    return b
end
function W.citizen(id, skills, labors, pos)
    local u = {id = id, skills = {}, status = {labors = {}}, pos = pos or {x = 0, y = 0, z = 10}}
    for k, v in pairs(skills or {}) do u.skills[env.df.job_skill[k]] = v end
    for _, l in ipairs(labors or {}) do u.status.labors[env.df.unit_labor[l]] = true end
    table.insert(W.units, u)
    return u
end
function W.reset_table(t) for k in pairs(t) do t[k] = nil end end
W.env = env
local fn = assert(load(src, 'module', 't', env))
fn()
local U = env.reqscript('ai-util')
U.danger_spots = function() return W.dangers end
return env, W
"""


def world(name: str):
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src(name))
    return lua, env, w


def py(v):
    """A Lua value as plain Python (tables to dicts/lists)."""
    if hasattr(v, "items"):
        d = {k: py(x) for k, x in v.items()}
        if d and all(isinstance(k, int) for k in d) and sorted(d) == list(range(1, len(d) + 1)):
            return [d[i] for i in range(1, len(d) + 1)]
        return d
    return v


def T(lua, obj):
    return lua.eval("function(s) return s end")(lua.table_from(obj) if not isinstance(obj, dict) else _tbl(lua, obj))


def _tbl(lua, obj):
    if isinstance(obj, dict):
        t = lua.table()
        for k, v in obj.items():
            t[k] = _tbl(lua, v)
        return t
    if isinstance(obj, list):
        t = lua.table()
        for i, v in enumerate(obj, 1):
            t[i] = _tbl(lua, v)
        return t
    return obj


# --- 1. training benches (lua) ----------------------------------------------------------------

def bench_fort(lua, env, w, areas=True):
    env.ai_areas = lua.eval("function() return {{x1 = 0, y1 = 0, x2 = 20, y2 = 20, z = 10}} end") if areas else \
        lua.eval("function() return {} end")
    w.shop(1, "Carpenters", 5, 5, 10)
    w.shop(2, "Carpenters", 10, 5, 10)
    w.shop(3, "Carpenters", 40, 40, 10)              # the player's: outside the AI's areas
    w.shop(4, "Masons", 6, 6, 10)
    for i, r in enumerate((14, 2, 1, 0)):
        w.citizen(i + 1, _tbl(lua, {"CARPENTRY": r}), _tbl(lua, ["CARPENTER"]))
    w.citizen(9, _tbl(lua, {"CARPENTRY": 15}), _tbl(lua, []))   # no labour: not counted


@test("lua benches: the AI's own workshops of a kind (in its areas), their skill range, the labour's skills")
def _():
    lua, env, w = world("ai-benches.lua")
    bench_fort(lua, env, w)
    r = py(env.report())
    c = r["kinds"]["Carpenters"]
    assert [s["id"] for s in c["shops"]] == [1, 2], c
    assert c["skills"] == [14, 2, 1, 0], c
    assert r["kinds"]["Masons"]["shops"][0]["id"] == 4 and "Kitchen" not in r["kinds"]


#: df-structures' df.unit_labor and df.job_skill tokens the benches use (DF 53; unit_labor has STONE_CRAFT
#: and CUT_GEM with underscores, job_skill STONECRAFT and CUTGEM without)
UNIT_LABORS = {"CARPENTER", "MASON", "STONE_CRAFT", "CUT_GEM", "CLOTHESMAKER", "LEATHER", "BOWYER", "MECHANIC",
               "WOOD_CRAFT", "BONE_CARVE", "ENCRUST_GEM", "METAL_CRAFT", "WEAVER", "TANNER", "SIEGECRAFT"}
JOB_SKILLS = {"CARPENTRY", "MASONRY", "STONECRAFT", "CUTGEM", "CLOTHESMAKING", "LEATHERWORK", "BOWYER", "MECHANICS"}


@test("lua benches: every kind's labour and skill a real df.unit_labor / df.job_skill token; the craftsdwarfs' "
      "and jewelers' learners counted (STONE_CRAFT, CUT_GEM)")
def _():
    lua, env, w = world("ai-benches.lua")
    kinds = py(env.BENCH_KINDS)
    for kind, k in kinds.items():
        assert k["labor"] in UNIT_LABORS, (kind, k)
        assert k["skill"] in JOB_SKILLS, (kind, k)
    env.ai_areas = lua.eval("function() return {{x1 = 0, y1 = 0, x2 = 20, y2 = 20, z = 10}} end")
    w.shop(1, "Craftsdwarfs", 5, 5, 10)
    w.shop(2, "Jewelers", 6, 6, 10)
    w.citizen(1, _tbl(lua, {"STONECRAFT": 7}), _tbl(lua, ["STONE_CRAFT"]))
    w.citizen(2, _tbl(lua, {"CUTGEM": 4}), _tbl(lua, ["CUT_GEM"]))
    r = py(env.report())
    assert r["kinds"]["Craftsdwarfs"]["skills"] == [7], r
    assert r["kinds"]["Jewelers"]["skills"] == [4], r


@test("lua cap_bench: the newest untouched one capped, the oldest kept for the masters; remembered; "
      "refused with one, twice, or when the player set the others")
def _():
    lua, env, w = world("ai-benches.lua")
    bench_fort(lua, env, w)
    r = py(env.cap_bench("Carpenters", 5, True))
    assert r["ok"] and r["dry_run"] and r["id"] == 2 and r["masters"] == 1, r
    assert w.shops[2].profile.max_level == 3000
    r = py(env.cap_bench("Carpenters", 5, False))
    assert r["ok"] and r["id"] == 2, r
    assert w.shops[2].profile.max_level == 5 and w.shops[1].profile.max_level == 3000
    assert w.shops[3].profile.max_level == 3000            # the player's never
    assert py(w.site["ai-overseer/benches"])["capped"] == {"2": 5}
    rows = py(env.report())["kinds"]["Carpenters"]["shops"]
    assert rows[1]["capped"] is True and rows[1]["max_level"] == 5 and not rows[0].get("capped"), rows
    r = py(env.cap_bench("Carpenters", 5, False))
    assert not r["ok"] and r["rejected"] and "already" in r["error"], r
    r = py(env.cap_bench("Masons", 5, False))
    assert not r["ok"] and r["rejected"] and "two" in r["error"], r
    r = py(env.cap_bench("Kitchen", 5, False))
    assert not r["ok"] and r["rejected"], r
    lua, env, w = world("ai-benches.lua")
    bench_fort(lua, env, w)
    w.shops[2].profile.min_level = 3                        # the player set the second
    r = py(env.cap_bench("Carpenters", 5, False))
    assert not r["ok"] and "yours" in r["error"], r


@test("lua release_bench: the AI's cap lifted; one the player changed since is forgotten, untouched")
def _():
    lua, env, w = world("ai-benches.lua")
    bench_fort(lua, env, w)
    assert py(env.cap_bench("Carpenters", 5, False))["ok"]
    r = py(env.release_bench("Carpenters", True))
    assert r["ok"] and r["dry_run"] and w.shops[2].profile.max_level == 5, r
    r = py(env.release_bench("Carpenters", False))
    assert r["ok"] and r["lifted"] == 1 and w.shops[2].profile.max_level == 3000, r
    assert py(w.site["ai-overseer/benches"])["capped"] == {}
    assert not py(env.release_bench("Carpenters", False))["ok"]
    assert py(env.cap_bench("Carpenters", 5, False))["ok"]
    w.shops[2].profile.max_level = 8                         # the player changed it
    r = py(env.release_bench("Carpenters", False))
    assert not r["ok"] and r["forgot"] == 1 and w.shops[2].profile.max_level == 8, r


@test("lua benches: no AI areas, no workshop of the AI's; a capped workshop gone is forgotten")
def _():
    lua, env, w = world("ai-benches.lua")
    bench_fort(lua, env, w, areas=False)
    assert py(env.report())["kinds"] in ({}, [])
    assert not py(env.cap_bench("Carpenters", 5, False))["ok"]
    lua, env, w = world("ai-benches.lua")
    bench_fort(lua, env, w)
    assert py(env.cap_bench("Carpenters", 5, False))["ok"]
    lua.eval("function(t) table.remove(t, 2) end")(w.shops)
    env.report()
    assert py(w.site["ai-overseer/benches"])["capped"] == {}


# --- 2. training benches (brain) --------------------------------------------------------------

def bench_state(shops, skills):
    return {"benches": {"kinds": {"Carpenters": {"shops": shops, "skills": skills}}}}


@test("brain bench_caps: two of the AI's, learners and a master: cap the newest; not with one, not without "
      "learners or a master, not when the player set the others")
def _():
    two = [{"id": 1, "jobs": 0}, {"id": 2, "jobs": 0}]
    p, n = [], []
    PB._bench_caps_rule(bench_state(two, [14, 2, 1]), CFG, p, n)
    assert len(p) == 1 and p[0].action == {"type": "bench_caps", "kind": "Carpenters", "level": 5}, p
    for shops, skills in ((two[:1], [14, 2, 1]), (two, [14, 2]), (two, [1, 2, 0]),
                          ([{"id": 1}, {"id": 2, "workers": 1}], [14, 2, 1])):
        p = []
        PB._bench_caps_rule(bench_state(shops, skills), CFG, p, n)
        assert p == [], (shops, skills, p)


@test("brain bench_caps: a capped bench nobody under the cap can work, or the last of its kind: released")
def _():
    capped = [{"id": 1}, {"id": 2, "max_level": 5, "capped": True}]
    p, n = [], []
    PB._bench_caps_rule(bench_state(capped, [14, 9, 6]), CFG, p, n)
    assert len(p) == 1 and p[0].action == {"type": "bench_caps", "kind": "Carpenters", "release": True}, p
    p = []
    PB._bench_caps_rule(bench_state(capped[1:], [14, 2]), CFG, p, n)
    assert len(p) == 1 and p[0].action.get("release"), p
    p = []
    PB._bench_caps_rule(bench_state(capped, [14, 2, 1]), CFG, p, n)
    assert p == [], p
    p = []
    PB._bench_caps_rule({"benches": {"error": "boom"}}, CFG, p, n)
    assert p == []


# --- 3. cavern logging and the grove (lua) ---------------------------------------------------

def forest(lua, w):
    w.walk_z[10] = True
    w.walk_z[30] = True
    w.citizen(1, None, None, _tbl(lua, {"x": 0, "y": 0, "z": 30}))
    w.tree(5, 5, 10, _tbl(lua, {"cave": True}))
    w.tree(8, 5, 10, _tbl(lua, {"cave": True}))
    w.tree(9, 9, 11, _tbl(lua, {"cave": True}))
    w.tree(5, 5, 2, _tbl(lua, {"cave": True}))          # a deeper layer nobody reaches
    w.tree(50, 50, 30, _tbl(lua, {"outside": True}))
    w.tree(60, 60, 30, _tbl(lua, {"outside": True, "hidden": True}))   # unseen: not counted
    w.tree(3, 3, 25)                                     # inside the fort (no reach: z 25)


@test("lua forestry report: trees by where they stand, reach, cavern layers by z band, dangers near a layer")
def _():
    lua, env, w = world("ai-forestry.lua")
    forest(lua, w)
    r = py(env.report())
    assert r["surface"]["trees"] == 1 and r["cavern"]["trees"] == 4 and r["inside"]["trees"] == 1, r
    assert r["cavern"]["reachable"] == 2, r                 # z 10 only (z 11 and 2 not walkable)
    layers = r["layers"]
    assert [(l["z1"], l["z2"], l["trees"]) for l in layers] == [(2, 2, 1), (10, 11, 3)], layers
    assert not any(l.get("danger") for l in layers)
    w.dangers[1] = _tbl(lua, {"x": 7, "y": 7, "z": 12})
    w.tile(7, 7, 12, _tbl(lua, {"cave": True}))
    r = py(env.report())
    assert r["cavern_dangers"] == 1 and r["layers"][1].get("danger") and not r["layers"][0].get("danger"), r


@test("lua cavern_logging: the reachable cavern trees marked, nearest first, remembered; none in a layer "
      "with a danger; stop unmarks the AI's; inside_only leaves the caverns")
def _():
    lua, env, w = world("ai-forestry.lua")
    forest(lua, w)
    r = py(env.cavern_logging(5, True, False, False))
    assert r["ok"] and r["marked"] == 2 and r["dry_run"], r
    assert w.tiles["5,5,10"].dig == "No"
    r = py(env.cavern_logging(1, False, False, False))
    assert r["ok"] and r["marked"] == 1, r
    assert py(w.site["ai-overseer/forestry"])["marked"].keys() == {"5,5,10"}
    assert w.tiles["5,5,10"].dig == "Default"
    rep = py(env.report())
    assert rep["ai_marked"] == 1 and rep["cavern"]["marked"] == 1, rep
    r = py(env.cavern_logging(5, False, False, False))
    assert r["ok"] and r["marked"] == 1 and w.tiles["8,5,10"].dig == "Default", r
    r = py(env.cavern_logging(5, False, True, False))
    assert r["ok"] and r["unmarked"] == 2, r
    assert w.tiles["5,5,10"].dig == "No" and w.tiles["8,5,10"].dig == "No"
    assert py(w.site["ai-overseer/forestry"])["marked"] in ({}, [])
    # a danger in the layer: nothing there is marked
    w.dangers[1] = _tbl(lua, {"x": 90, "y": 90, "z": 10})
    w.tile(90, 90, 10, _tbl(lua, {"cave": True}))
    r = py(env.cavern_logging(5, False, False, False))
    assert not r["ok"] and r["rejected"], r
    w.reset_table(w.dangers)
    r = py(env.cavern_logging(5, False, False, True))
    assert not r["ok"] and r["rejected"], r                 # inside_only: no inside tree in reach
    assert not py(env.cavern_logging(0, False, False, False))["ok"]


@test("lua cavern_logging: a danger near one layer: the report counts the AI's marks it makes unsafe, and "
      "stop unsafe_only lifts only those (the safe layer's marks stand; no mark-unmark churn)")
def _():
    lua, env, w = world("ai-forestry.lua")
    forest(lua, w)
    w.walk_z[20] = True
    w.tree(30, 30, 20, _tbl(lua, {"cave": True}))         # a second layer, far from the first
    lua.execute("local env = ...; env.CENSUS = nil", env)
    r = py(env.cavern_logging(5, False, False, False))
    assert r["ok"] and r["marked"] == 3, r
    rep = py(env.report())
    assert rep["ai_marked"] == 3 and rep["ai_marked_unsafe"] == 0, rep
    w.dangers[1] = _tbl(lua, {"x": 90, "y": 90, "z": 10})   # in the z 10-11 layer, far from z 20
    w.tile(90, 90, 10, _tbl(lua, {"cave": True}))
    rep = py(env.report())
    assert rep["ai_marked"] == 3 and rep["ai_marked_unsafe"] == 2, rep
    r = py(env.cavern_logging(None, True, True, False, True))
    assert r["ok"] and r["dry_run"] and r["unmarked"] == 2 and r["kept"] == 1, r
    assert w.tiles["5,5,10"].dig == "Default"
    r = py(env.cavern_logging(None, False, True, False, True))
    assert r["ok"] and r["unmarked"] == 2 and r["kept"] == 1, r
    assert w.tiles["5,5,10"].dig == "No" and w.tiles["8,5,10"].dig == "No" and w.tiles["30,30,20"].dig == "Default"
    assert py(w.site["ai-overseer/forestry"])["marked"].keys() == {"30,30,20"}
    rep = py(env.report())
    assert rep["ai_marked"] == 1 and rep["ai_marked_unsafe"] == 0, rep
    # a danger near a tree of the safe layer (within DANGER_TILES) makes that mark unsafe too
    w.dangers[2] = _tbl(lua, {"x": 33, "y": 30, "z": 20})
    assert py(env.report())["ai_marked_unsafe"] == 1


@test("lua cavern_logging: a felled tree the AI marked is forgotten and counted")
def _():
    lua, env, w = world("ai-forestry.lua")
    forest(lua, w)
    assert py(env.cavern_logging(1, False, False, False))["ok"]
    w.tiles["5,5,10"].shape = "FLOOR"                        # felled
    w.tiles["5,5,10"].material = "SOIL"
    lua.execute("local env = ...; env.CENSUS = nil", env)
    r = py(env.report())
    assert r["ai_marked"] == 0 and r["ai_felled"] == 1, r


def grove_fort(lua, env, w):
    w.walk_z[30] = True
    w.citizen(1, None, None, _tbl(lua, {"x": 0, "y": 0, "z": 30}))
    for y in range(10, 25):
        for x in range(10, 25):
            w.tile(x, y, 30, _tbl(lua, {"outside": True}))
    for x, y in ((15, 15), (16, 16), (17, 15), (14, 17), (16, 14)):
        w.sapling(x, y, 30)
    w.tree(18, 18, 30, _tbl(lua, {"outside": True, "dig": "Default"}))     # autochop's mark
    env.grove_context = lua.eval("function() return {reserved = {}, anchors = {{x = 30, y = 30, z = 30}}} end")


@test("lua keep_grove: the patch with the most saplings near the fort, its traffic restricted, its trees' "
      "marks lifted, remembered; guard unmarks again; a reserved area or no way in refuses")
def _():
    lua, env, w = world("ai-forestry.lua")
    grove_fort(lua, env, w)
    r = py(env.keep_grove(True, False))
    assert r["ok"] and r["dry_run"] and r["restricted"] == 81, r
    assert w.tiles["16,16,30"].traffic == "Normal"
    r = py(env.keep_grove(False, False))
    assert r["ok"] and r["made"] and r["unmarked"] == 1, r
    g = r["grove"]
    assert g["x2"] - g["x1"] == 8 and g["x1"] <= 16 <= g["x2"], g
    assert w.tiles["16,16,30"].traffic == "Restricted" and w.tiles["18,18,30"].dig == "No"
    rep = py(env.report())["grove"]
    assert rep["saplings"] == 5 and rep["trees"] == 1 and rep["marked"] == 0, rep
    w.tiles["18,18,30"].dig = "Default"                      # autochop again
    assert py(env.report())["grove"]["marked"] == 1          # seen at once, not after the day's census
    w.tiles["16,16,30"].traffic = "Normal"                   # restricted traffic lost
    w.tiles["17,15,30"].traffic = "High"                     # someone's choice: kept
    lua.execute("local env = ...; env.census = function() error('the guard reads the grove, no census') end", env)
    r = py(env.keep_grove(True, True))
    assert r["ok"] and r["dry_run"] and r["unmarked"] == 1 and r["restricted"] == 1, r
    assert w.tiles["18,18,30"].dig == "Default" and w.tiles["16,16,30"].traffic == "Normal"
    r = py(env.keep_grove(False, True))
    assert r["ok"] and r["unmarked"] == 1 and w.tiles["18,18,30"].dig == "No", r
    assert r["restricted"] == 1 and w.tiles["16,16,30"].traffic == "Restricted", r
    assert w.tiles["17,15,30"].traffic == "High"
    lua, env, w = world("ai-forestry.lua")
    grove_fort(lua, env, w)
    assert not py(env.keep_grove(False, True))["ok"]        # guard with no grove
    env.grove_context = lua.eval("function() return {reserved = {{x1 = 0, y1 = 0, x2 = 40, y2 = 40, z = 30}}, "
                                 "anchors = {{x = 30, y = 30, z = 30}}} end")
    r = py(env.keep_grove(False, False))
    assert not r["ok"] and "clear" in r["error"], r
    env.grove_context = lua.eval("function() return {reserved = {}, anchors = {}} end")
    assert not py(env.keep_grove(False, False))["ok"]


# --- 4. cavern logging and the grove (brain) ------------------------------------------------

def forest_state(**kw):
    s = {
        "stocks": {"wood": 3},
        "settings": {},
        "diplomacy": {},
        "date": {"year": 5},
        "threats": {"openings": {"list": [{"x": 1, "y": 1, "z": 10, "building": "Door", "built": True}]},
                    "sealed": {}},
        "forestry": {"surface": {"trees": 4, "saplings": 0}, "cavern": {"trees": 30, "reachable": 12},
                     "inside": {"trees": 0, "reachable": 0}, "ai_marked": 0, "cavern_dangers": 0,
                     "layers": [{"z1": 10, "z2": 12, "trees": 30, "reachable": 12}]},
    }
    for k, v in kw.items():
        s[k] = v
    return s


def run_cave(s, memory=None, citizens=20):
    p, n = [], []
    PF._cavern_logging_rule(s, memory, CFG, citizens, p, n)
    return p, n


@test("brain cavern_logging: wood short, the surface bare, the caverns watched: fell a batch; not with wood "
      "enough, surface trees, an opening without a door, a seal, or the switch off")
def _():
    p, n = run_cave(forest_state())
    assert len(p) == 1 and p[0].action == {"type": "cavern_logging", "limit": 10}, (p, n)
    p, _ = run_cave(forest_state(stocks={"wood": 500}))
    assert p == []
    s = forest_state()
    s["forestry"]["surface"]["trees"] = 300
    assert run_cave(s)[0] == []
    s = forest_state()
    s["threats"]["openings"]["list"].append({"x": 2, "y": 2, "z": 10, "kind": "open"})
    p, n = run_cave(s)
    assert p == [] and any("without a door" in x for x in n), n
    s = forest_state()
    s["threats"]["sealed"] = {"cavern 1": {"doors": 2}}
    assert run_cave(s)[0] == []
    s = forest_state()
    s["threats"]["openings"]["list"] = []
    assert run_cave(s)[0] == []
    assert run_cave(forest_state(settings={"cavern_logging": False}))[0] == []


@test("brain cavern_logging: the elves' quota counts cavern trees too (stops at the share, at most the room); "
      "a danger or a seal with the AI's marks standing: stop")
def _():
    m = Memory()
    m.tree_year = {"year": 5, "base": 0}
    s = forest_state(diplomacy={"trees_removed": 97, "tree_cap": 100, "elves": True})
    p, n = run_cave(s, m)
    assert p == [] and any("count toward it" in x for x in n), n
    s = forest_state(diplomacy={"trees_removed": 77, "tree_cap": 100, "elves": True})
    p, _ = run_cave(s, m)
    assert p and p[0].action["limit"] == 3, p
    s = forest_state()
    s["forestry"]["ai_marked"] = 4
    s["forestry"]["layers"][0]["danger"] = True
    p, _ = run_cave(s)                                         # an older report (no count): every mark
    assert len(p) == 1 and p[0].action == {"type": "cavern_logging", "stop": True, "unsafe_only": True} \
        and p[0].priority == 2, p
    s = forest_state()
    s["forestry"]["ai_marked"] = 4
    s["threats"]["sealed"] = {"c": {"doors": 1}}
    assert run_cave(s)[0][0].action.get("stop")
    s = forest_state()
    s["forestry"]["ai_marked"] = 4
    p, _ = run_cave(s)
    assert p and p[0].action["limit"] == 6, p                 # the batch less the marks standing


@test("brain cavern_logging: a danger lifts only the marks it makes unsafe; with none unsafe the safe "
      "layers' marks stand and the batch is topped up there (no mark-unmark churn every two days)")
def _():
    s = forest_state()
    s["forestry"]["layers"] = [{"z1": 10, "z2": 12, "trees": 30, "reachable": 12, "danger": True},
                               {"z1": 30, "z2": 31, "trees": 8, "reachable": 8}]
    s["forestry"]["cavern_dangers"] = 1
    s["forestry"]["ai_marked"] = 4
    s["forestry"]["ai_marked_unsafe"] = 0
    p, n = run_cave(s)
    assert len(p) == 1 and p[0].rule == "cavern_logging" and p[0].action == {"type": "cavern_logging", "limit": 6}, p
    assert any("safe layers" in x for x in n), n
    s["forestry"]["ai_marked_unsafe"] = 3
    p, _ = run_cave(s)
    assert len(p) == 1 and p[0].rule == "cavern_logging_stop", p
    assert p[0].action == {"type": "cavern_logging", "stop": True, "unsafe_only": True}, p
    s["threats"]["sealed"] = {"c": {"doors": 1}}                 # a seal: every mark, whatever the danger
    p, _ = run_cave(s)
    assert p[0].action == {"type": "cavern_logging", "stop": True}, p


@test("brain cavern_logging: caverns not watched but trees inside the fort: inside_only")
def _():
    s = forest_state()
    s["threats"]["openings"]["list"] = [{"kind": "open"}]
    s["forestry"]["inside"] = {"trees": 5, "reachable": 5}
    p, _ = run_cave(s)
    assert p and p[0].action == {"type": "cavern_logging", "limit": 5, "inside_only": True}, p


@test("brain grove: saplings enough and no grove: keep one; the grove's marked trees unmarked unless wood is "
      "in crisis")
def _():
    s = forest_state()
    s["forestry"]["surface"]["saplings"] = 8
    p, n = [], []
    PF._grove_rule(s, CFG, 20, p, n)
    assert len(p) == 1 and p[0].action == {"type": "keep_grove"}, p
    s["forestry"]["grove"] = {"trees": 3, "saplings": 5, "marked": 2}
    s["stocks"]["wood"] = 40
    p = []
    PF._grove_rule(s, CFG, 20, p, n)
    assert len(p) == 1 and p[0].action == {"type": "keep_grove", "guard": True}, p
    # the guard is its own rule, answered within hours (autochop re-marks each cycle), never a "loop"
    assert p[0].rule == "grove_guard" and CFG["grove_guard_cooldown_ticks"] <= 1200 // 4, p
    assert "grove_guard" in planner_core.LOOP_EXEMPT
    s["stocks"]["wood"] = 1
    p, n = [], []
    PF._grove_rule(s, CFG, 20, p, n)
    assert p == [] and any("left to the woodcutters" in x for x in n), n
    s["forestry"]["grove"]["marked"] = 0
    s["stocks"]["wood"] = 40
    p = []
    PF._grove_rule(s, CFG, 20, p, n)
    assert p == []
    assert "trees:" in PF.forestry_line(s)


# --- 5. leather armour (lua) ------------------------------------------------------------------

def leather_fort(lua, w):
    def spec(cls, sub, assigned=()):
        return {"material_class": cls, "item_subtype": sub, "assigned": list(assigned)}
    uni = {0: [spec(1, 0)], 1: [spec(1, -1)], 2: [], 3: [spec(1, 0)], 4: [spec(1, 0, [99])]}
    pos = [{"occupant": 5, "equipment": {"uniform": uni}},
           {"occupant": 6, "equipment": {"uniform": {0: [spec(2, 1)], 1: [], 2: [], 3: [], 4: []}}},
           {"occupant": -1, "equipment": {"uniform": uni}}]
    w.squads[1] = _tbl(lua, {"positions": pos})
    lua.execute("""local W = ...
      local function item(id, sub, leather, flags)
        return {id = id, leather = leather, flags = flags or {}, getSubtype = function() return sub end}
      end
      W.items.ARMOR = {item(1, 0, true), item(2, 0, false), item(3, 0, true, {forbid = true}),
                       item(4, 0, true, {owned = true})}
      W.items.HELM, W.items.PANTS, W.items.GLOVES, W.items.SHOES = {}, {}, {item(7, 0, true)}, {}
      W.una.ARMOR = {1, 2, 3, 4}
      W.una.HELM, W.una.PANTS, W.una.GLOVES, W.una.SHOES = {}, {}, {}, {}
    """, w)


@test("lua leather_gear: empty leather entries by slot and kind, the given ones, the free leather pieces on "
      "DF's list, every class asked for")
def _():
    lua, env, w = world("ai-leather-gear.lua")
    leather_fort(lua, w)
    r = py(env.report())
    assert r["wanted"]["body"] == {"ITEM_ARMOR_LEATHER": 1}, r
    assert r["wanted"]["head"] == {"any": 1} and r["wanted"]["gloves"] == {"ITEM_GLOVES_GLOVES": 1}, r
    assert r["given"] == {"shoes": 1} and r["soldiers"] == 2, r
    assert r["spare"] == {"ITEM_ARMOR_LEATHER": 2}, r       # 1 and the forbidden 3; not metal 2, not owned 4
    assert r["classes"] == {"Leather": 4, "Armor": 1}, r


# --- 6. leather armour (brain) ----------------------------------------------------------------

def leather_state(**kw):
    s = {"settings": {}, "stocks": {"leather": 20}, "orders": [],
         "buildings": {"workshops": {"Leatherworks": 1}},
         "military": {"gear": {"soldiers": 4, "bars": {"IRON": 2}}},
         "leather_gear": {"wanted": {"body": {"ITEM_ARMOR_LEATHER": 4}, "head": {"any": 4},
                                     "gloves": {"ITEM_GLOVES_GLOVES": 4}},
                          "spare": {"ITEM_ARMOR_LEATHER": 1}, "soldiers": 4}}
    s.update(kw)
    return s


def run_leather(s):
    p, n = [], []
    PL._leather_gear_rule(s, CFG, p, n)
    return p, n


@test("brain leather_gear: metal short, hides and a leatherworks: the body armour first (less the spare and "
      "queued), then the next slot; nothing with metal enough, no hides, no leatherworks, make_gear off")
def _():
    p, _ = run_leather(leather_state())
    assert len(p) == 1 and p[0].action == {"type": "work_order", "recipe": "leather_armor", "amount": 3}, p
    s = leather_state(orders=[{"recipe": "leather_armor", "amount_left": 3}])
    p, _ = run_leather(s)
    assert p and p[0].action["recipe"] == "leather_cap" and p[0].action["amount"] == 4, p
    s = leather_state(orders=[{"recipe": "leather_armor", "amount_left": 3}, {"recipe": "leather_cap",
                                                                               "amount_left": 4}])
    p, _ = run_leather(s)
    assert p and p[0].action["recipe"] == "leather_gloves", p
    assert run_leather(leather_state(military={"gear": {"soldiers": 4, "bars": {"IRON": 400}}}))[0] == []
    p, n = run_leather(leather_state(stocks={"leather": 0}))
    assert p == [] and any("tanned hides" in x for x in n), n
    p, n = run_leather(leather_state(buildings={"workshops": {}}))
    assert p == [] and any("leatherworks" in x for x in n), n
    assert run_leather(leather_state(settings={"make_gear": False}))[0] == []
    p, _ = run_leather(leather_state(stocks={"leather": 2}))
    assert p[0].action["amount"] == 2, p
    assert planner_core.recipe_shop("leather_armor") == "Leatherworks"


# --- 7. wiring --------------------------------------------------------------------------------

@test("bridge: three sections (safe), three actions on ACTIONS and DRY_OK, the modules listed, the recipes; "
      "the brain's labels, the defaults, config keys, the Rules switch")
def _():
    hub = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    orders = (LUA_DIR / "ai-bridge-orders.lua").read_text(encoding="utf-8")
    for sec, mod in (("forestry", "ai-forestry"), ("benches", "ai-benches"), ("leather_gear", "ai-leather-gear")):
        assert f"{sec} = function() return safe(function() return reqscript('{mod}').report() end) end" in hub
        assert f"'{mod}'" in hub
        assert sec in digest.SECTION_DEFAULTS
    for a in ("cavern_logging", "keep_grove", "bench_caps"):
        assert f"    {a} = function(a)" in hub and f"'{a}'" in hub
        assert a in overseer.SHORT_WORDS
    for r in ("leather_armor", "leather_cap", "leather_leggings", "leather_gloves", "leather_high_boots"):
        assert f"    {r} = {{job = " in orders, r
    for k in ("cavern_logging_surface_min", "cavern_logging_batch", "grove_min_saplings", "grove_release_wood",
              "bench_training_max_level", "bench_learners_min"):
        assert k in PLANNER_CONFIG, k
    assert planner_core.player_rules({"settings": {}})["cavern_logging"] is True
    assert planner_core.player_rules({"settings": {"cavern_logging": False}})["cavern_logging"] is False
    st = (LUA_DIR / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    assert "cavern_logging = true," in st and "cavern_logging = s.cavern_logging," in st
    gui = (LUA_DIR / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
    assert "view_id = 'cavern_logging'" in gui


@test("plan(): the fixture fort with the three sections runs the new rules and proposes from them")
def _():
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    s = copy.deepcopy(base)
    s["benches"] = bench_state([{"id": 1}, {"id": 2}], [14, 2, 1])["benches"]
    s["leather_gear"] = {"wanted": {}, "spare": {}}
    s["forestry"] = {"surface": {"trees": 100, "saplings": 12}, "cavern": {}, "inside": {}}
    out = plan(s, Memory())
    props = out[0] if isinstance(out, tuple) else out
    rules = {getattr(p, "rule", None) for p in props}
    assert "bench_caps" in rules and "grove" in rules, rules


if __name__ == "__main__":
    finish()
