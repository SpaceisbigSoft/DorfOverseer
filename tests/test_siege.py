"""(item5) Siege works and the field guard: lua/ai-siege.lua in a fake fort
(the posts survey: fortifications and the floor behind them, thin walls to
smooth or carve, a 2-thick wall's inner tile to dig, a ballista's spot and
facing; fortify_post, archer_post and place_engine with their dry runs; the
field watch: hostiles near a caravan, hostile wild animals near the dwarves
outside, the caverns never read), ai-military's archer post order and wild
kill targets, the bridge's wiring, the settings, and the brain
(brain/planner_siege.py: the siege workshop, ballistae, parts, arrows and
operators behind the sliders; fortifications and the crossbows posted in a
siege, never while hiding or with a fire breather; the caravan guarded and
the wildlife hunted within the danger rules; their squads kept on them; and
plan() without the sections the same as main's).

    python tests/test_siege.py
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
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, Proposal, plan  # noqa: E402
import planner_siege as PS  # noqa: E402
import digest  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
CFG = PLANNER_CONFIG

# A fort at z 100: roofed inside floor over x 10..30, y 10..30 (W.inside),
# a natural wall row at y 9 (x 0..40) with the opening at x 20, walkable
# open ground outside at y 0..8. W.set(x, y, {...}) overrides a tile;
# W.thick() makes y 8 a second wall row (the outside at y 0..7).
FAKE = r"""
local src = ...
local W = {over = {}, inside = {}, qf = {}, burrows = {}, defend = {}, buildings = {}, units = {}, citizens = {},
           site = {}, wild = {}, fire = {}, groups = {}, merchants = {}, next_burrow = 1}
local env = setmetatable({}, {__index = _G})
local function k3(x, y, z) return x .. ',' .. y .. ',' .. z end
local function gkey(x, y, z) return (z * 4096 + y) * 4096 + x end
W.gkey = gkey
for x = 10, 30 do for y = 10, 30 do W.inside[gkey(x, y, 100)] = true end end
W.inside[gkey(20, 9, 100)] = true            -- the opening
W.outside_rows = 8
function W.thick() W.outside_rows = 7 end
function W.set(x, y, t) W.over[k3(x, y, 100)] = t end
local function base(x, y, z)
    if z ~= 100 or x < 0 or y < 0 or x > 40 or y > 40 then return nil end
    local o = W.over[k3(x, y, z)]
    if o then return o end
    if y <= W.outside_rows then
        return {shape = 'FLOOR', material = 'SOIL', walk = true, outside = true}
    end
    if x == 20 and y <= 9 then return {shape = 'FLOOR', material = 'STONE', walk = true} end
    if y == 9 or y == 8 then
        return {shape = 'WALL', material = 'STONE', walk = false, smooth = W.smooth == true}
    end
    if x >= 10 and x <= 30 and y >= 9 and y <= 30 then
        return {shape = 'FLOOR', material = 'STONE', walk = true}
    end
    return {shape = 'WALL', material = 'STONE', walk = false}
end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {
    global = {plotinfo = {burrows = {list = W.burrows}}, world = {buildings = {all = W.buildings, other = {}},
              items = {other = {}}, units = {active = W.units}}},
    building_type = {SiegeEngine = 'SiegeEngine'},
    siegeengine_type = setmetatable({}, {__index = function(_, k) return k end}),
    building_siegeenginest = {T_facing = setmetatable({}, {__index = function(_, k) return k end})},
    unit_labor = {SIEGEOPERATE = 'SIEGEOPERATE', SIEGECRAFT = 'SIEGECRAFT'},
    squad = {find = function() return nil end},
    squad_order_defend_burrowsst = {is_instance = function() return false end},
}
env.dfhack = {
    maps = {getTileFlags = function(p) return {outside = (base(p.x, p.y, p.z) or {}).outside == true} end,
            getWalkableGroup = function(p) return W.groups[k3(p.x, p.y, p.z)] or 1 end},
    burrows = {clearTiles = function(b) b.tiles = {} end,
               setAssignedTile = function(b, p, on) b.tiles = b.tiles or {}; table.insert(b.tiles, p) end},
    buildings = {findAtTile = function(p)
        for _, b in ipairs(W.buildings) do if b.centerx == p.x and b.centery == p.y and b.z == p.z then return b end end
    end},
    units = {
        getCitizens = function() return W.citizens end,
        isDead = function(u) return u.dead == true end,
        isActive = function(u) return u.inactive ~= true end,
        isCitizen = function(u) return u.citizen == true end,
        isMerchant = function(u) return u.merchant == true end,
        isDiplomat = function(u) return false end,
        isVisitor = function(u) return false end,
        isTame = function(u) return u.tame == true end,
        isDanger = function(u) return u.danger == true end,
        isInvader = function(u) return u.invader == true end,
        isGreatDanger = function(u) return u.great == true end,
        getReadableName = function(u) return u.name or ('#' .. u.id) end,
    },
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
local G = {GATES = {scanned = true, inside = W.inside, entrances = {
    {id = 1, kind = 'surface', x = 20, y = 9, z = 100, sealed = true, inside_list = {gkey(20, 9, 100)}},
    {id = 2, kind = 'cavern', x = 5, y = 35, z = 100, sealed = true, inside_list = {}}}}}
W.G = G
local B = {}
function B.qf_try(mode, cells, z, ax, ay, dry_run)
    local texts = {}
    for _, c in ipairs(cells) do table.insert(texts, c.x .. ',' .. c.y .. '=' .. c.text) end
    table.insert(W.qf, {mode = mode, cells = table.concat(texts, ' '), n = #cells, z = z, dry = dry_run == true})
    if W.qf_refuse then return false, 'dry' end
    if not dry_run and mode == 'build' then
        local c = cells[1]
        table.insert(W.buildings, {id = 900 + #W.buildings, centerx = c.x, centery = c.y, z = z, type = 'Ballista',
            getType = function() return 'SiegeEngine' end,
            getBuildStage = function() return 0 end, getMaxBuildStage = function() return 1 end})
    end
    return true
end
function B.hostile_wild(u) return u.wild == true end
local M = {}
function M.defend(sid, bid)
    if sid == 66 then return {ok = false, rejected = true, error = 'the squad is on your orders'} end
    table.insert(W.defend, {sid = sid, bid = bid})
    return {ok = true}
end
local S = {}
function S.new_burrow(name)
    local b = {id = W.next_burrow, name = name}
    W.next_burrow = W.next_burrow + 1
    table.insert(W.burrows, b)
    return b
end
local TH = {fire_breath_of = function(race, caste) return W.fire[race] or false end}
env.reqscript = function(n)
    if n == 'ai-threats' then return TH end
    error('reqscript ' .. tostring(n))
end
assert(load(src, 'ai-siege', 't', env))()
env.gates = function() return G end
env.builder = function() return B end
env.military = function() return M end
env.society = function() return S end
env.tile = function(x, y, z)
    local t = base(x, y, z)
    if not t then return nil end
    return {shape = t.shape, material = t.material, smooth = t.smooth == true, walk = t.walk == true,
            outside = t.outside == true, hidden = false, liquid = t.liquid == true, occupied = t.occupied == true,
            designated = t.designated == true, aquifer = t.aquifer == true}
end
function W.unit(t)
    t.pos = t.pos or {x = 0, y = 0, z = 100}
    t.flags1 = t.flags1 or {}
    t.race, t.caste = t.race or 1, 0
    t.body = {size_info = {size_cur = t.size or 70000}}
    t.enemy = {caste_flags = {}}
    table.insert(W.units, t)
    if t.citizen then table.insert(W.citizens, t) end
    return t
end
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-siege.lua"))
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


def fort_tiles(lua, w, *xs):
    for x in xs:
        w.set(x, 9, T(lua, {"shape": "FORTIFICATION", "material": "STONE", "walk": False}))


# --- 1. the survey and the report --------------------------------------------------------

if LuaRuntime is not None:
    @test("survey: thin rough walls beside the gate are to smooth, smooth ones to carve; the opening never; "
          "the cavern entrance not surveyed")
    def _():
        lua, env, w = world()
        r = py(env.report())
        assert [e["id"] for e in r["entrances"]] == [1], r["entrances"]
        e = r["entrances"][0]
        # x 13..27 at y 9, less the opening at x 20: 14 thin walls
        assert (e["smooth"], e["carve"], e["dig"], e["fortifications"], e["posts"]) == (14, 0, 0, 0, 0), e
        w.smooth = True
        e = py(env.report())["entrances"][0]
        assert (e["smooth"], e["carve"]) == (0, 14), e

    @test("survey: a 2-thick wall's inner tile is to dig; fortifications give the roofed floor behind them as "
          "posts, and a ballista spot 2-6 tiles back with a free ring, facing them")
    def _():
        lua, env, w = world()
        w.thick()
        e = py(env.report())["entrances"][0]
        assert (e["smooth"], e["carve"], e["dig"]) == (0, 0, 14), e
        lua, env, w = world()
        fort_tiles(lua, w, 17, 23)
        e = py(env.report())["entrances"][0]
        assert e["fortifications"] == 2 and e["posts"] == 2, e
        sp = e["engine_spot"]
        assert sp["y"] >= 12 and sp["facing"] == "Up", sp
        assert abs(sp["x"] - 20) >= 2                     # the 5x5 never takes in the opening
        w.set(sp["x"], sp["y"], T(lua, {"shape": "FLOOR", "material": "STONE", "walk": True, "occupied": True}))
        sp2 = py(env.report())["entrances"][0]["engine_spot"]
        assert sp2 != sp

    @test("(fix3) survey: a soil wall is never to smooth or carve; an aquifer's wall is never to carve or dig")
    def _():
        lua, env, w = world()
        for x in (13, 14):
            w.set(x, 9, T(lua, {"shape": "WALL", "material": "SOIL", "walk": False}))
        w.set(15, 9, T(lua, {"shape": "WALL", "material": "STONE", "walk": False, "aquifer": True}))
        e = py(env.report())["entrances"][0]
        assert e["smooth"] == 11, e
        lua, env, w = world()
        w.thick()
        w.set(13, 9, T(lua, {"shape": "WALL", "material": "STONE", "walk": False, "aquifer": True}))   # inner
        w.set(14, 8, T(lua, {"shape": "WALL", "material": "STONE", "walk": False, "aquifer": True}))   # outer
        e = py(env.report())["entrances"][0]
        assert e["dig"] == 12, e

    @test("report: siege engines, the AI's by name or record, built and planned; ammo and labour counts; "
          "no gates scan: no entrances")
    def _():
        lua, env, w = world()
        lua.execute("""local W = ...
            local function b(id, x, name, built)
                table.insert(W.buildings, {id = id, centerx = x, centery = 14, z = 100, type = 'Ballista', name = name,
                    getType = function() return 'SiegeEngine' end,
                    getBuildStage = function() return built and 1 or 0 end, getMaxBuildStage = function() return 1 end})
            end
            b(1, 15, 'AI ballista', true); b(2, 25, 'theirs', true); b(3, 17, nil, false)
            W.site['ai-overseer/siege-engines'] = {3}""", w)
        r = py(env.report())
        assert (r["ai_engines"], r["built"], r["planned"], r["all_built"]) == (2, 1, 1, 2), r
        assert r["entrances"][0]["engines_near"] == 3
        assert r["operators"] == 0 and r["ammo"]["siege_ammo"] == 0
        w.G.GATES.scanned = False
        assert not py(env.report())["entrances"]

    # --- 2. the actions -------------------------------------------------------------------

    @test("fortify_post: carves the smooth thin walls (at most max), else smooths the rough, else digs the inner "
          "tile; a dry run goes to quickfort's dry run only")
    def _():
        lua, env, w = world()
        r = py(env.fortify_post(1, 3, True))
        assert r["ok"] and r["step"] == "smooth" and r["tiles"] == 3 and r["dry_run"], r
        assert w.qf[1].dry is True and w.qf[1].mode == "dig" and "=s" in w.qf[1].cells
        w.smooth = True
        r = py(env.fortify_post(1, 20, False))
        assert r["ok"] and r["step"] == "carve" and r["tiles"] == 8, r      # FORTIFY_MAX
        assert w.qf[2].cells.count("=F") == 8 and w.qf[2].dry is False
        lua, env, w = world()
        w.thick()
        r = py(env.fortify_post(1, 2, False))
        assert r["step"] == "dig" and "=d" in w.qf[1].cells and ",9=" in w.qf[1].cells, (r, w.qf[1].cells)
        assert py(env.fortify_post(2, 2, False))["rejected"]          # a cavern entrance
        assert py(env.fortify_post(99, 2, False))["rejected"]

    @test("fortify_post: nothing thin enough: refused and said why; quickfort refusing: not ok")
    def _():
        lua, env, w = world()
        for x in range(0, 41):
            w.set(x, 8, T(lua, {"shape": "WALL", "material": "CONSTRUCTION", "walk": False}))
        r = py(env.fortify_post(1, 2, False))
        assert r["rejected"] and "thin enough" in r["error"], r
        lua, env, w = world()
        w.qf_refuse = True
        r = py(env.fortify_post(1, 2, False))
        assert not r["ok"] and not r.get("rejected"), r

    @test("archer_post: the post burrow made over the floor behind the fortifications, each squad told to "
          "defend it; one on the player's orders refused; a dry run makes nothing")
    def _():
        lua, env, w = world()
        assert py(env.archer_post(1, T(lua, [5]), False))["rejected"]          # no fortifications yet
        fort_tiles(lua, w, 17)
        r = py(env.archer_post(1, T(lua, [5, 66]), True))
        assert r["ok"] and r["dry_run"] and r["tiles"] >= 1 and len(w.burrows) == 0, r
        r = py(env.archer_post(1, T(lua, [5, 66]), False))
        assert r["ok"] and r["squads"] == [5] and len(r["refused"]) == 1, r
        assert w.burrows[1].name == "AI archer post" and len(w.defend) == 1 and w.defend[1].bid == w.burrows[1].id
        tiles = py(w.burrows[1].tiles)
        assert {"x": 17, "y": 10, "z": 100} in tiles and all(t["y"] >= 10 for t in tiles), tiles
        r = py(env.archer_post(1, T(lua, [7]), False))
        assert r["ok"] and len(w.burrows) == 1                       # the same burrow again

    @test("place_engine: a ballista at the spot, named and recorded as the AI's, facing out; refused with "
          "one there, or with nothing to shoot through")
    def _():
        lua, env, w = world()
        w.smooth = True                                     # walls only ready to carve: nothing to shoot through yet
        r = py(env.place_engine(1, "ballista", False))
        assert r["rejected"] and "fortification" in r["error"], r
        fort_tiles(lua, w, 17, 23)
        r = py(env.place_engine(1, "ballista", True))
        assert r["ok"] and r["dry_run"] and len(w.buildings) == 0, r
        r = py(env.place_engine(1, "ballista", False))
        assert r["ok"] and r["building_id"] == 900 and w.qf[2].cells.endswith("=ib"), (r, w.qf[2].cells)
        assert w.buildings[1].name == "AI ballista" and w.buildings[1].facing == r["facing"]
        assert py(w.site["ai-overseer/siege-engines"]) == [900]
        r = py(env.place_engine(1, "ballista", False))
        assert r["rejected"] and "already" in r["error"], r
        assert py(env.place_engine(1, "trebuchet", False))["rejected"]

    @test("place_shop: a siege workshop on a free 7x7 of roofed floor near the gate, off the opening; a dry "
          "run places nothing; one standing: refused")
    def _():
        lua, env, w = world()
        r = py(env.place_shop(1, True))
        assert r["ok"] and r["dry_run"] and w.qf[1].dry is True and w.qf[1].cells.endswith("=ws"), r
        at = r["at"]
        assert at["y"] - 3 >= 10 and 10 <= at["x"] - 3 and at["x"] + 3 <= 30, at
        r = py(env.place_shop(1, False))
        assert r["ok"] and w.qf[2].dry is False
        lua.execute("""local W, env = ...
            env.df.global.world.buildings.other.WORKSHOP_ANY = {{type = 'Siege'}}
            env.df.workshop_type = setmetatable({}, {__index = function(_, k) return k end})""", w, env)
        r = py(env.place_shop(1, False))
        assert r["rejected"] and "already" in r["error"], r
        assert py(env.report())["shops"] == 1


    # --- 3. the field watch --------------------------------------------------------------

    @test("field_watch: a danger or a hostile wild animal near a merchant is listed for the caravan; a wild one "
          "outside near the dwarves for the hunt; the caravan's own, the tame, the caged and the caverns' not")
    def _():
        lua, env, w = world()
        w.unit(T(lua, {"id": 1, "citizen": True, "pos": {"x": 20, "y": 3, "z": 100}}))          # a woodcutter outside
        w.unit(T(lua, {"id": 2, "citizen": True, "pos": {"x": 20, "y": 20, "z": 100}}))         # inside
        w.unit(T(lua, {"id": 10, "merchant": True, "pos": {"x": 5, "y": 2, "z": 100}}))
        w.unit(T(lua, {"id": 11, "merchant": True, "wild": True, "pos": {"x": 6, "y": 2, "z": 100}}))   # its pack animal
        w.unit(T(lua, {"id": 20, "danger": True, "invader": True, "name": "goblin", "pos": {"x": 9, "y": 2, "z": 100}}))
        w.unit(T(lua, {"id": 21, "wild": True, "name": "grizzly bear", "race": 7, "pos": {"x": 25, "y": 4, "z": 100}}))
        w.unit(T(lua, {"id": 22, "wild": True, "tame": True, "pos": {"x": 26, "y": 4, "z": 100}}))
        w.unit(T(lua, {"id": 23, "wild": True, "flags1": {"caged": True}, "pos": {"x": 27, "y": 4, "z": 100}}))
        w.unit(T(lua, {"id": 24, "wild": True, "pos": {"x": 25, "y": 25, "z": 100}}))   # not under the sky
        w.fire[7] = "breath"
        r = py(env.field_watch(None))
        assert r["merchants"] == 2 and r["citizens_outside"] == 1, r
        cv = {x["id"]: x for x in r["caravan"]}
        assert set(cv) == {20, 21}, cv                      # the bear is 20 tiles from the merchants
        assert cv[20]["distance"] == 3 and cv[20]["invader"] is True and cv[20].get("wild") is None
        wild = {x["id"]: x for x in r["wild"]}
        assert set(wild) == {21} and r["wild_total"] == 1, wild
        assert wild[21]["distance_outside"] == 6 and wild[21]["fire_breather"] is True and wild[21]["reach"] is True

    @test("field_watch: no merchants and nothing outside: nothing listed")
    def _():
        lua, env, w = world()
        w.unit(T(lua, {"id": 2, "citizen": True, "pos": {"x": 20, "y": 20, "z": 100}}))
        w.unit(T(lua, {"id": 24, "wild": True, "danger": True, "pos": {"x": 25, "y": 25, "z": 100}}))
        r = py(env.field_watch(None))
        assert not r["caravan"] and not r["wild"] and r["merchants"] == 0, r

    @test("(fix3) field_watch: a creature neither outside nor near a caravan pays none of the unit checks")
    def _():
        lua, env, w = world()
        for i in range(30):
            w.unit(T(lua, {"id": 100 + i, "wild": True, "pos": {"x": 25, "y": 25, "z": 100}}))   # under a roof
        calls = lua.execute("""local env = ...
            local n = {0}
            for _, name in ipairs({'isCitizen', 'isDiplomat', 'isVisitor', 'isTame'}) do
                local f = env.dfhack.units[name]
                env.dfhack.units[name] = function(u) n[1] = n[1] + 1; return f(u) end
            end
            return n""", env)
        py(env.field_watch(None))
        assert calls[1] == 0, calls[1]


# --- 4. ai-military: the post is the AI's order, a hostile wild animal a target ------------

MIL = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local burrows = {{id = 3, name = 'AI gate guard'}, {id = 4, name = 'AI archer post'}, {id = 5, name = 'yours'}}
local DEF = {}
env.df = {global = {plotinfo = {burrows = {list = burrows}}}, squad_order_defend_burrowsst = DEF,
          mood_type = {Berserk = 99}}
function DEF:is_instance(o) return o.defend == true end
env.dfhack = {units = {isMerchant = function(u) return u.merchant == true end, isDiplomat = function() return false end,
                       isTame = function(u) return u.tame == true end, isCitizen = function() return false end,
                       isDanger = function(u) return u.danger == true end, isInvader = function() return false end}}
env.reqscript = function(n)
    if n == 'ai-builder' then return {hostile_wild = function(u) return u.wild == true end} end
    error('reqscript ' .. n)
end
assert(load(src, 'ai-military', 't', env))()
return env
"""

if LuaRuntime is not None:
    @test("ai-military: a defend order on the archer post is the AI's (guarding), the gate guard's still is, "
          "another burrow's isn't; a hostile wild animal may be a kill target, a tame or calm one not")
    def _():
        lua = LuaRuntime(unpack_returned_tuples=True)
        env = lua.execute(MIL, module_src("ai-military.lua"))
        defend = lua.eval("""function(env, b)
            local o = {defend = true, burrows = setmetatable({[0] = b}, {__len = function() return 1 end})}
            local sq = {orders = {o}, positions = {}}
            env.fort_squad = function() return sq end
            return env.defend(1, 9)
        end""")
        assert "already holds" in py(defend(env, 4))["error"]          # the archer post: the AI's own
        assert "already holds" in py(defend(env, 3))["error"]          # the gate guard: still
        assert "your orders" in py(defend(env, 5))["error"]            # another burrow: the player's
        kt = env.kill_target_ok
        assert kt(T(lua, {"wild": True})) is True
        assert kt(T(lua, {"wild": True, "tame": True})) is False
        assert kt(T(lua, {})) is False
        assert kt(T(lua, {"danger": True})) is True


# --- 5. the wiring -------------------------------------------------------------------------

@test("wiring: the bridge's actions, dry runs, sections, pulse, cache; the module listed; the labels; the "
      "Rules switches; the siege workshop and the recipes")
def _():
    hub = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    for a in ("fortify_post", "archer_post", "place_siege_engine", "place_siege_shop"):
        assert f"    {a} = function(a)" in hub and f"'{a}'" in hub and f"CACHE_INVALIDATES.{a} = {{'siege'}}" in hub
    assert "    siege = function() return safe(" in hub and "    field_watch = function() return safe(" in hub
    assert "'field_watch',   -- (item5)" in hub and "SECTION_CACHE_DAYS.siege = 1" in hub
    assert "'ai-siege'," in hub
    import overseer
    for a in ("fortify_post", "archer_post", "place_siege_engine", "place_siege_shop"):
        assert a in overseer.SHORT_WORDS
    st = (LUA_DIR / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    for k in ("siege_engines", "archer_posts", "caravan_guard", "wildlife_hunts"):
        assert f"{k} = s.{k}" in st and f"'{k}'" in st
    assert "siege_engines = true, archer_posts = true, caravan_guard = true, wildlife_hunts = true" in st
    assert "Siege = 'ws'" not in (LUA_DIR / "ai-layouts.lua").read_text(encoding="utf-8")   # a 5x5: placed apart
    orders = (LUA_DIR / "ai-bridge-orders.lua").read_text(encoding="utf-8")
    for r in ("ballista_parts", "ballista_arrowheads", "ballista_arrows", "catapult_parts"):
        assert f"    {r} = {{job = " in orders
    from planner_core import EMERGENCY, recipe_shop
    assert {"archer_post", "caravan_guard"} <= EMERGENCY
    assert recipe_shop("ballista_arrows") == "Siege" and recipe_shop("ballista_arrowheads") == "MetalsmithsForge"
    for k in PS.SIEGE_CONFIG:
        assert k in CFG
    s = digest.normalize(json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8")))
    assert s["siege"] == {} and s["field_watch"] == {}


# --- 6. the brain --------------------------------------------------------------------------

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def entrance(**kw):
    e = {"id": 1, "x": 20, "y": 9, "z": 100, "kind": "surface", "sealed": True, "fortifications": 0, "posts": 0,
         "carve": 0, "smooth": 6, "dig": 0, "engines_near": 0,
         "engine_spot": {"x": 17, "y": 13, "z": 100, "facing": "Up"}}
    e.update(kw)
    return e


def siege(*ents, **kw):
    out = {"scanned": True, "entrances": list(ents) or [entrance()], "engines": [], "ai_engines": 0, "built": 0,
           "planned": 0, "ammo": {"siege_ammo": 0, "ballista_parts": 0, "catapult_parts": 0, "arrowheads": 0},
           "operators": 0, "engineers": 0}
    out.update(kw)
    return out


def squad(id_, ranged=False, armed=5, **kw):
    q = {"id": id_, "name": f"squad {id_}", "members": 5, "power": {"armed": armed, "power": 10},
         "ai_orders": 0, "orders": 0}
    if ranged:
        q["ai_uniform"] = "AI crossbow"
    q.update(kw)
    return q


def fort(sg=None, fw=None, traits=None, citizens=40, squads=None, threats=None, settings=None, **extra) -> dict:
    s = copy.deepcopy(BASE)
    if sg is not None:
        s["siege"] = sg
    if fw is not None:
        s["field_watch"] = fw
    s["settings"]["traits"] = dict(traits or {})
    s["settings"].update(settings or {})
    s["dwarves"]["total"] = citizens
    if squads is not None:
        s["military"]["squads"] = squads
    if threats is not None:
        s["others_on_map"]["threats"] = threats
    s.update(extra)
    return digest.normalize(s)


def run(s, memory=None, proposals=None):
    props, notes = list(proposals or []), []
    PS._siege_rules(s, memory or Memory(), CFG, props, notes)
    return props, notes


def rules(props):
    return [p.rule for p in props]


@test("engines: nothing below the sliders or in a small fort; at Fortification 60: the siege workshop and a "
      "ballista at the gate; Engineering counts too; the Rules switch off: nothing")
def _():
    assert not [p for p in run(fort(siege()))[0] if p.rule.startswith("siege")]
    assert not [p for p in run(fort(siege(), traits={"fortification": 60}, citizens=10))[0]
                if p.rule.startswith("siege")]
    props, _ = run(fort(siege(), traits={"fortification": 60}))
    by = {p.rule: p for p in props}
    assert by["siege_shop"].action == {"type": "place_siege_shop", "entrance_id": 1}
    assert by["siege_engine"].action == {"type": "place_siege_engine", "entrance_id": 1, "kind": "ballista"}
    props, _ = run(fort(siege(), traits={"engineering": 80}))
    assert "siege_engine" in rules(props)
    props, _ = run(fort(siege(), traits={"fortification": 60}, settings={"siege_engines": False}))
    assert not [p for p in props if p.rule.startswith("siege")]


@test("engines: enough engines, or one already at the gate: no more; no spot anywhere: said; an enemy in "
      "reach: nothing is built")
def _():
    t = {"fortification": 60}
    props, _ = run(fort(siege(ai_engines=2), traits=t))
    assert "siege_engine" not in rules(props)
    props, _ = run(fort(siege(entrance(engines_near=1)), traits=t))
    assert "siege_engine" not in rules(props)
    props, notes = run(fort(siege(entrance(engine_spot=None)), traits=t))
    assert "siege_engine" not in rules(props) and any("no gated entrance" in n for n in notes), notes
    reach = [{"id": 5, "name": "goblin", "invader": True, "can_reach_dwarves": True}]
    props, _ = run(fort(siege(), traits=t, threats=reach, **{"others_on_map": {"threats": reach,
                                                                               "threats_that_can_reach_dwarves": 1}}))
    assert not [p for p in props if p.rule.startswith("siege")]


@test("engines: parts for the placed ones, arrows and arrowheads for the built ones (a metal with bars, a "
      "forge), the siege operating labour; none without the workshop")
def _():
    t = {"fortification": 100}
    sg = siege(ai_engines=2, planned=1, built=1)
    s = fort(sg, traits=t)
    s["buildings"]["workshops"]["Siege"] = 1
    s["buildings"]["workshops"]["MetalsmithsForge"] = 1
    s["military"].setdefault("gear", {})["bars"] = {"IRON": 40}
    props, _ = run(s)
    by = {}
    for p in props:
        by.setdefault(p.rule, []).append(p.action)
    assert by["siege_parts"] == [{"type": "work_order", "recipe": "ballista_parts", "amount": 1}], by
    heads = [a for a in by["siege_ammo"] if a["recipe"] == "ballista_arrowheads"]
    assert heads and heads[0]["amount"] == 10 and heads[0]["material"] == "INORGANIC:IRON", by["siege_ammo"]
    assert by["siege_operator"] == [{"type": "assign_labor", "job": "SIEGEOPERATE", "count": 1}]
    sg["ammo"]["arrowheads"] = 4
    s = fort(sg, traits=t)
    s["buildings"]["workshops"]["Siege"] = 1
    props, _ = run(s)
    arrows = [p.action for p in props if p.rule == "siege_ammo" and p.action["recipe"] == "ballista_arrows"]
    assert arrows == [{"type": "work_order", "recipe": "ballista_arrows", "amount": 4}], arrows
    props, _ = run(fort(siege(ai_engines=2, planned=1, built=1), traits=t))
    assert not {"siege_parts", "siege_ammo"} & set(rules(props))


@test("posts: fortifications carved (smoothed first) for a fort with crossbows or Fortification 50, one "
      "entrance a cycle; enough there: none; the Rules switch off: none")
def _():
    props, _ = run(fort(siege(), squads=[squad(1, ranged=True)]))
    p = [x for x in props if x.rule == "fortify_post"]
    assert p and p[0].action == {"type": "fortify_post", "entrance_id": 1, "max": 4} and "smoothed" in p[0].reason
    props, _ = run(fort(siege(entrance(smooth=0, carve=3)), traits={"fortification": 50}, squads=[]))
    assert [x for x in props if x.rule == "fortify_post"][0].reason.count("carved") == 1
    assert "fortify_post" not in rules(run(fort(siege(), squads=[]))[0])
    assert "fortify_post" not in rules(run(fort(siege(entrance(fortifications=3)), squads=[squad(1, ranged=True)]))[0])
    assert "fortify_post" not in rules(run(fort(siege(), squads=[squad(1, ranged=True)],
                                                settings={"archer_posts": False}))[0])


@test("fortifications for the ballistae: with siege engines wanted they are carved even without crossbows or "
      "archer posts; neither wanted: none")
def _():
    props, _ = run(fort(siege(), traits={"engineering": 60}, squads=[], settings={"archer_posts": False}))
    p = [x for x in props if x.rule == "fortify_post"]
    assert p and "the ballistae" in p[0].reason, props
    props, _ = run(fort(siege(), traits={"engineering": 60}, squads=[],
                        settings={"archer_posts": False, "siege_engines": False}))
    assert "fortify_post" not in rules(props)


INV = [{"id": 50, "name": "goblin", "invader": True, "can_reach_dwarves": False, "layer": "surface"}]


@test("(fix3) a besieger on the map, none in reach yet: no fortifications carved, no siege works built")
def _():
    t = {"fortification": 60}
    props, _ = run(fort(siege(), traits=t, squads=[squad(1, ranged=True)], threats=INV))
    assert not {"fortify_post", "siege_shop", "siege_engine"} & set(rules(props)), rules(props)
    props, _ = run(fort(siege(), traits=t, squads=[squad(1, ranged=True)]))
    assert {"fortify_post", "siege_shop", "siege_engine"} <= set(rules(props)), rules(props)


@test("posts: in a siege the free crossbow squads go behind the fortifications, out of the gate guard; "
      "not while hiding, not with a fire breather among the besiegers, not at 'never'")
def _():
    sq = [squad(1, ranged=True), squad(2)]
    sg = siege(entrance(fortifications=3, posts=3))
    guard = Proposal("gate_guard", {"type": "guard_gate", "x": 20, "y": 9, "z": 100, "squads": [1, 2]}, "hold", 0)
    props, _ = run(fort(sg, squads=sq, threats=INV), proposals=[guard])
    post = [p for p in props if p.rule == "archer_post"]
    assert post and post[0].action == {"type": "archer_post", "entrance_id": 1, "squads": [1]}, props
    assert guard.action["squads"] == [2]
    fire = [dict(INV[0], fire_breather=True)]
    props, notes = run(fort(sg, squads=sq, threats=fire))
    assert "archer_post" not in rules(props) and any("fire breather" in n for n in notes), notes
    props, _ = run(fort(sg, squads=sq, threats=INV, settings={"attack_policy": "never"}))
    assert "archer_post" not in rules(props)
    import planner_army
    real = planner_army.hiding
    planner_army.hiding = lambda s, m, c: (True, [])
    try:
        props, notes = run(fort(sg, squads=sq, threats=INV))
    finally:
        planner_army.hiding = real
    assert "archer_post" not in rules(props) and any("hides" in n for n in notes), notes
    props, _ = run(fort(sg, squads=[squad(1, ranged=True, ai_orders=1)], threats=INV))
    assert "archer_post" not in rules(props)                 # already posted (or out)


def field(caravan=(), wild=(), merchants=3):
    return {"merchants": merchants, "caravan": [dict(x) for x in caravan], "wild": [dict(x) for x in wild],
            "wild_total": len(wild), "citizens_outside": 2}


GOB = {"id": 60, "name": "goblin", "distance": 6, "invader": True, "outside": True}
BEAR = {"id": 70, "name": "grizzly bear", "wild": True, "distance_outside": 8, "distance": 8, "outside": True,
        "reach": True, "size": 250000}


@test("caravan: a hostile by the merchants: a free squad (melee first) sent at it; a fire breather or a great "
      "danger not; one already on it: no other; no merchants: nothing; switch off: nothing")
def _():
    props, _ = run(fort(fw=field([GOB]), squads=[squad(1, ranged=True), squad(2)]))
    p = [x for x in props if x.rule == "caravan_guard"]
    assert p and p[0].action == {"type": "squad_orders", "squad_id": 2, "kill": [60]}, props
    props, notes = run(fort(fw=field([dict(GOB, fire_breather=True)]), squads=[squad(2)]))
    assert "caravan_guard" not in rules(props) and notes
    props, _ = run(fort(fw=field([dict(GOB, great=True)]), squads=[squad(2)]))
    assert "caravan_guard" not in rules(props)
    props, _ = run(fort(fw=field([dict(GOB, great=True)]), squads=[squad(2)], settings={"attack_policy": "all"}))
    assert "caravan_guard" in rules(props)
    props, _ = run(fort(fw=field([GOB]), squads=[squad(2, ai_orders=1, kill_ids=[60]), squad(3)]))
    assert "caravan_guard" not in rules(props)
    assert "caravan_guard" not in rules(run(fort(fw=field([GOB], merchants=0), squads=[squad(2)]))[0])
    assert "caravan_guard" not in rules(run(fort(fw=field([dict(GOB, distance=30)]), squads=[squad(2)]))[0])
    assert "caravan_guard" not in rules(run(fort(fw=field([GOB]), squads=[squad(2)],
                                                 settings={"caravan_guard": False}))[0])
    props, notes = run(fort(fw=field([GOB]), squads=[squad(2, armed=0)]))
    assert "caravan_guard" not in rules(props) and any("no squad" in n for n in notes)


@test("wildlife: a dangerous animal near the dwarves outside: a squad hunts it; a big one only a strong squad; "
      "a fire breather never; the alarm up, 'never' or the switch off: no hunt")
def _():
    props, _ = run(fort(fw=field(wild=[BEAR]), squads=[squad(2)]))
    p = [x for x in props if x.rule == "wild_hunt"]
    assert p and p[0].action == {"type": "squad_orders", "squad_id": 2, "kill": [70]}, props
    far = dict(BEAR, distance_outside=30, distance=30)
    assert "wild_hunt" not in rules(run(fort(fw=field(wild=[far]), squads=[squad(2)]))[0])
    big = dict(BEAR, size=5000000)
    assert "wild_hunt" not in rules(run(fort(fw=field(wild=[big]), squads=[squad(2)]))[0])
    strong = squad(3, power={"armed": 5, "power": 20})
    assert "wild_hunt" in rules(run(fort(fw=field(wild=[big]), squads=[squad(2), strong]))[0])
    assert "wild_hunt" not in rules(run(fort(fw=field(wild=[dict(BEAR, fire_breather=True)]), squads=[squad(2)]))[0])
    assert "wild_hunt" not in rules(run(fort(fw=field(wild=[BEAR]), squads=[squad(2)], civ_alert=True))[0])
    assert "wild_hunt" not in rules(run(fort(fw=field(wild=[BEAR]), squads=[squad(2)],
                                             settings={"attack_policy": "never"}))[0])
    assert "wild_hunt" not in rules(run(fort(fw=field(wild=[BEAR]), squads=[squad(2)],
                                             settings={"wildlife_hunts": False}))[0])
    # (fix3) near a dwarf outside but unable to walk to them (another walk group): no hunt
    assert "wild_hunt" not in rules(run(fort(fw=field(wild=[dict(BEAR, reach=False)]), squads=[squad(2)]))[0])


@test("evil weather: no squad walks out to the caravan or the wildlife (said)")
def _():
    w = {"evil_cloud": 30, "material": "evil smoke"}
    props, notes = run(fort(fw=field([GOB], [BEAR]), squads=[squad(2), squad(3)], weather=w))
    assert not {"caravan_guard", "wild_hunt"} & set(rules(props)), props
    assert any("no squad walks out" in n for n in notes), notes


@test("a squad on the wildlife or the caravan's attacker isn't recalled for 'no more threats' while it is "
      "listed; once it is gone, it is")
def _():
    q = squad(2, ai_orders=1, kill_ids=[70])
    recall = Proposal("squad_recall", {"type": "squad_orders", "squad_id": 2, "clear": True},
                      "no more threats: call squad 2 back", 1)
    props, notes = run(fort(fw=field(wild=[BEAR]), squads=[q]), proposals=[recall])
    assert recall not in props and any("stay on" in n for n in notes), notes
    recall2 = Proposal("squad_recall", {"type": "squad_orders", "squad_id": 2, "clear": True},
                       "no more threats: call squad 2 back", 1)
    props, _ = run(fort(fw=field(wild=[]), squads=[q]), proposals=[recall2])
    assert recall2 in props


@test("plan(): the rules run inside it (a ballista proposed at Fortification 60), and the actions carry labels")
def _():
    s = fort(siege(), traits={"fortification": 60})
    props, _ = plan(s, Memory())
    assert "siege_engine" in rules(props) or "siege_shop" in rules(props), rules(props)


# --- 7. identity: without the sections, plan() is main's ------------------------------------

PROBE = r'''
import copy, json, sys
from pathlib import Path
brain = Path(sys.argv[1]); sys.path.insert(0, str(brain))
fixtures = Path(sys.argv[2])
from digest import normalize, digest
from planner import Memory, plan, record, select, note_cycle, TICKS_PER_DAY
from planner import PLANNER_CONFIG as _PC
_PC.update({"survival_floor": 0, "mandate_shields": False, "mandates_low_deference": False})  # (item5) its floor and mandate changes off: main's behaviour compared
out = {}
for path in [fixtures / "test_fort.json"] + sorted((fixtures / "real").glob("*.json")):
    base = json.loads(path.read_text(encoding="utf-8"))
    s = normalize(copy.deepcopy(base))
    m = Memory()
    cycles = []
    for _ in range(2):
        n = note_cycle(copy.deepcopy(s), m)
        props, notes = plan(copy.deepcopy(s), m)
        cycles.append({"props": [[p.rule, json.dumps(p.action, sort_keys=True, default=str), p.reason,
                                  p.priority] for p in props], "notes": notes, "cycle": n})
        allowed, _ = select(props, s, m)
        record([(p, {"ok": False, "error": "refused (test)"}) for p in allowed], s, m)
        s["date"]["tick"] = s["date"].get("tick", 0) + TICKS_PER_DAY
    out[path.name] = cycles
print(json.dumps(out, sort_keys=True))
'''

_MAIN = {}


def main_brain() -> Path | None:
    if "dir" not in _MAIN:
        tmp = tempfile.mkdtemp(prefix="siege-main-")
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


@test("no siege or field_watch section: plan() and note_cycle() are main's (every fixture, 2 cycles)")
def _():
    main = main_brain()
    assert main is not None, "no main branch to compare with"
    a, b = probe(main), probe(ROOT / "brain")
    if a != b:
        ja, jb = json.loads(a), json.loads(b)
        bad = [k for k in ja if ja[k] != jb.get(k)]
        raise AssertionError(f"differs from main at {bad[:3]}")


if LuaRuntime is None:
    print("lupa not installed: the Lua tests were skipped")

if __name__ == "__main__":
    finish()
