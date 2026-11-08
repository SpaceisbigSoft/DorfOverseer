"""Tests for lua/ai-industry.lua (ore near the fort, mining a vein safely),
in a real Lua engine with a small fake map (pip install lupa).

    python tests/test_industry.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from lua_modules_util import module_src  # (13c lua-modules) the modules' sources, with lua/ai-util.lua
from harness import test, finish  # noqa: E402

try:
    from lupa import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

SRC = module_src("ai-industry.lua")

# One 16x16 block at z 10, x/y 0-15. Rock everywhere ('#'), a dug room ('.'),
# hematite ('h', iron) and malachite ('m', copper) veins; 'w' water; '?' hidden hematite.
FAKE = r"""
local src, rows = ...
local SHAPE = {WALL = 1, FLOOR = 2}
local tiles = {}
local function key(x, y, z) return x .. ',' .. y .. ',' .. z end
for y = 0, 15 do
    local row = rows[y + 1]
    for x = 0, 15 do
        local ch = row:sub(x + 1, x + 1)
        tiles[key(x, y, 10)] = {ch = ch,
            d = {hidden = ch == '?', dig = 0, flow_size = ch == 'w' and 7 or 0, water_table = false,
                 feature_global = false, feature_local = false, outside = false}}
    end
end
local function at(x, y, z)
    local t = tiles[key(x, y, z)]
    if t then return t end
    return {ch = '#', d = {hidden = true, dig = 0, flow_size = 0, water_table = false,
                           feature_global = false, feature_local = false, outside = false}}
end
local INORG = {[1] = {id = 'HEMATITE', metal_ore = {mat_index = {[0] = 100}}},
               [2] = {id = 'MALACHITE', metal_ore = {mat_index = {[0] = 101}}},
               [100] = {id = 'IRON', metal_ore = {mat_index = {}}},
               [101] = {id = 'COPPER', metal_ore = {mat_index = {}}}}
local function mask(chars)
    local m = {}
    for y = 0, 15 do for x = 0, 15 do
        local ch = at(x, y, 10).ch
        if chars:find(ch, 1, true) then m[x .. ',' .. y] = true end
    end end
    return m
end
local MINERAL = {}
local block = {map_pos = {x = 0, y = 0, z = 10}, flags = {designated = false},
               block_events = {setmetatable({inorganic_mat = 1, tile_bitmask = mask('h?')}, {__index = {_cls = MINERAL}}),
                               setmetatable({inorganic_mat = 2, tile_bitmask = mask('m')}, {__index = {_cls = MINERAL}})},
               designation = {}}
for x = 0, 15 do
    block.designation[x] = {}
    for y = 0, 15 do block.designation[x][y] = at(x, y, 10).d end
end
local env = setmetatable({}, {__index = _G})
env.df = {
    global = {world = {map = {map_blocks = {block}}, raws = {inorganics = {all = INORG}}}},
    tiletype = {attrs = {[1] = {shape = 1}, [2] = {shape = 2}, [3] = {shape = 1, special = 1}}},
    tiletype_special = {[1] = 'SMOOTH'},
    tile_building_occ = {None = 0},
    tiletype_shape = setmetatable({[1] = 'WALL', [2] = 'FLOOR', attrs = {[1] = {walkable = false}, [2] = {walkable = true}}},
                                  {__index = function() return nil end}),
    block_square_event_mineralst = {is_instance = function(_, ev) return ev._cls == MINERAL end},
    tile_dig_designation = {No = 0, Default = 1},
}
env.dfhack = {maps = {
    -- (0.104.19) 'B': a floor with a building on it (a bed, a door); 'S': a smoothed wall
    getTileType = function(x, y, z) local c = at(x, y, z).ch
        return (c == '.' or c == 'w' or c == 'B') and 2 or (c == 'S' and 3 or 1) end,
    getTileFlags = function(x, y, z) local t = at(x, y, z)
        return t.d, {building = t.ch == 'B' and 1 or 0} end,
    getTileBlock = function(x, y, z) if z == 10 and x >= 0 and x < 16 and y >= 0 and y < 16 then return block end end,
    getTileAssignment = function(m, x, y) return m[x .. ',' .. y] == true end,
    getWalkableGroup = function(p) local c = at(p.x, p.y, p.z).ch; return (c == '.' or c == 'B') and 1 or 0 end,
}}
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.reqscript = function() return {citizen_positions = function() return {{x = 2, y = 2, z = 10}} end} end
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
assert(load(src, 'ai-industry', 't', env))()
return env, function(x, y) return at(x, y, 10).d.dig end
"""

MAP = [
    "################",
    "#.....##########",
    "#.....hhh#######",
    "#.....#hh??#####",
    "#.....##########",
    "########mmm#####",
    "########mw######",
    "################",
] + ["################"] * 8


def game(rows=MAP):
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, dig = lua.execute(FAKE, SRC, lua.table_from(rows))
    return env, dig


@test("the survey counts only uncovered ore, by the metal it smelts into")
def _():
    env, _ = game()
    s = env.survey()
    assert s.ores.IRON.tiles == 5 and s.ores.IRON.ore == "HEMATITE", dict(s.ores.IRON)      # not the 2 hidden
    assert s.ores.COPPER.tiles == 4, dict(s.ores.COPPER)


@test("(0.104.140) the survey finds the same ore through the area's own blocks (getBlock) as by the whole map's")
def _():
    env, _ = game()
    calls = []
    def get_block(bx, by, z):
        calls.append((bx, by, z))
        return env.dfhack.maps.getTileBlock(bx * 16, by * 16, z)
    env.dfhack.maps.getBlock = get_block
    s = env.survey()
    assert s.ores.IRON.tiles == 5 and s.ores.COPPER.tiles == 4, (dict(s.ores.IRON), dict(s.ores.COPPER))
    assert calls, "the area's blocks were looked up"


@test("mining follows the vein from a tile beside the fort, hidden parts too; a dry run marks nothing")
def _():
    env, dig = game()
    r = env.mine("IRON", 40, True)
    assert r.ok and r.tiles == 7 and r.ore == "HEMATITE" and dig(6, 2) == 0, dict(r)
    r = env.mine("IRON", 40, False)
    assert r.ok and r.tiles == 7 and dig(6, 2) == 1 and dig(9, 3) == 1 and dig(1, 1) == 0, dict(r)


@test("never beside water; nothing reachable is refused")
def _():
    env, dig = game()
    r = env.mine("COPPER", 40, False)
    assert not r.ok and "no uncovered copper ore" in r.error, dict(r)                 # not reachable
    rows = list(MAP)
    rows[4] = "#.....##mmmmm###"
    rows[5] = "#............w##"
    rows[6] = "################"
    env, dig = game(rows)
    r = env.mine("COPPER", 40, False)
    assert r.ok and r.tiles == 4 and dig(11, 4) == 1 and dig(12, 4) == 0, (dict(r), dig(12, 4))   # beside water: never


@test("mining (0.104.0): never into the AI's levels or their walls (2 tiles round each project)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, dig = lua.execute(FAKE, SRC, lua.table_from(MAP))
    lua.execute("""local env = ...
      env.reqscript = function() return {
        citizen_positions = function() return {{x = 2, y = 2, z = 10}} end,
        load_projects = function() return {list = {{area = {x1 = 1, y1 = 1, x2 = 5, y2 = 4, z = 10}}}} end} end
    """, env)
    r = env.mine("IRON", 40, False)
    # the hematite at x 6-7 lies within 2 tiles of the room (x 1-5): the vein
    # isn't followed there; (0.105.9) a 1-wide drift opens at x6 to the vein
    # beyond the margin (x8), and the vein is followed only outside it
    assert r.ok and r.drift == 2 and dig(6, 2) == 1 and dig(7, 2) == 1 and dig(7, 3) == 0, dict(r)

@test("0.105.9: every vein in a level's walls: a drift through plain rock to a hidden vein, then the vein")
def _():
    rows = ["################",
            "#.....##########",
            "#.....hh####??##",
            "#.....##########",
            "#.....##########"] + ["################"] * 11
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, dig = lua.execute(FAKE, SRC, lua.table_from(rows))
    lua.execute("""local env = ...
      env.reqscript = function() return {
        citizen_positions = function() return {{x = 2, y = 2, z = 10}} end,
        load_projects = function() return {list = {{area = {x1 = 1, y1 = 1, x2 = 5, y2 = 4, z = 10}}}} end} end
    """, env)
    r = env.mine("IRON", 40, True)
    assert r.ok and r.drift == 6 and dig(6, 2) == 0, dict(r)                    # a dry run marks nothing
    assert (r.drift_from.x, r.drift_from.y) == (6, 2), dict(r.drift_from)
    r = env.mine("IRON", 40, False)
    assert r.ok and r.drift == 6 and r.tiles == 8, dict(r)
    assert all(dig(x, 2) == 1 for x in range(6, 14)), [dig(x, 2) for x in range(5, 15)]
    assert dig(6, 1) == 0 and dig(6, 3) == 0, "a 1-wide tunnel"
    # the drift runs beside a level only at its opening: a room 1 tile above the
    # tunnel's line keeps it off that row (around it, or no drift)
    rows2 = list(rows)
    rows2[1] = "#.....##.....###"
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, dig = lua.execute(FAKE, SRC, lua.table_from(rows2))
    lua.execute("""local env = ...
      env.reqscript = function() return {
        citizen_positions = function() return {{x = 2, y = 2, z = 10}} end,
        load_projects = function() return {list = {{area = {x1 = 1, y1 = 1, x2 = 5, y2 = 4, z = 10}},
                                                     {area = {x1 = 8, y1 = 1, x2 = 12, y2 = 1, z = 10}}}} end} end
    """, env)
    r = env.mine("IRON", 40, True)
    assert not r.ok and "no vein within" in r.error, dict(r)                   # the vein is in that level's margin


@test("0.105.9: no vein within the drift's reach: refused, nothing marked")
def _():
    rows = ["################",
            "#.....##########",
            "#.....hh####??##",
            "#.....##########",
            "#.....##########"] + ["################"] * 11
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, dig = lua.execute(FAKE, SRC, lua.table_from(rows))
    lua.execute("""local env = ...
      env.reqscript = function() return {
        citizen_positions = function() return {{x = 2, y = 2, z = 10}} end,
        load_projects = function() return {list = {{area = {x1 = 1, y1 = 1, x2 = 5, y2 = 4, z = 10}}}} end} end
      env.DRIFT_MAX = 3
    """, env)
    r = env.mine("IRON", 40, False)
    assert not r.ok and "no vein within 3 tiles" in r.error, dict(r)
    assert all(dig(x, y) == 0 for x in range(16) for y in range(16))


QUARRY_SETUP = """
local env, layer_idx, econ = ...
env.df.tiletype.attrs[1].material = 1
env.df.tiletype.attrs[2].material = 1
env.df.tiletype.attrs[3].material = 1
env.df.tiletype_material = {[1] = 'STONE'}
env.df.global.plotinfo = {economic_stone = {}}
for i = 0, 200 do env.df.global.plotinfo.economic_stone[i] = false end
env.df.global.plotinfo.economic_stone[layer_idx] = econ
setmetatable(env.df.global.plotinfo.economic_stone, {__len = function() return 201 end})
env.df.global.world.raws.inorganics.all[3] = {id = 'GRANITE', metal_ore = {mat_index = {}}}
env.df.global.world.raws.inorganics.all[4] = {id = 'GYPSUM', metal_ore = {mat_index = {}}}
local block = env.dfhack.maps.getTileBlock(0, 0, 10)
for x = 0, 15 do for y = 0, 15 do block.designation[x][y].geolayer_index = 0 end end
env.dfhack.maps.getTileBiomeRgn = function() return 1, 1 end
env.dfhack.maps.getRegionBiome = function() return {geo_index = 5} end
env.df.world_geo_biome = {find = function() return {layers = {[0] = {mat_index = layer_idx}}} end}
env.reqscript = function(name)
    return {citizen_positions = function() return {{x = 2, y = 2, z = 10}} end,
            load_projects = function() return {list = {}} end}
end
"""


@test("quarry: a chamber in ordinary stone beside the fort (not ore veins, not economic stone)")
def _():
    L = LuaRuntime(unpack_returned_tuples=True)
    env, dig = L.execute(FAKE, SRC, L.table_from(MAP))
    L.execute(QUARRY_SETUP, env, 3, False)
    r = env.quarry(10, False)
    assert r.ok and r.stone == "GRANITE" and r.tiles >= 1, dict(r)
    assert dig(r.x, r.y) == 1
    assert env.quarry_stone(3, False, False) and not env.quarry_stone(3, True, False) and not env.quarry_stone(3, False, True)
    L2 = LuaRuntime(unpack_returned_tuples=True)
    env2, dig2 = L2.execute(FAKE, SRC, L2.table_from(MAP))
    L2.execute(QUARRY_SETUP, env2, 4, True)                       # the layer is economic (gypsum)
    r = env2.quarry(10, False)
    assert not r.ok and "ordinary" in r.error, dict(r)

@test("quarry (0.104.19): never the wall of a room: beside a bed or door, or a smoothed wall; nor an old level's")
def _():
    rooms = list(MAP)
    rooms[1] = "#SSSSS##########"                                  # a smoothed wall along the top
    rooms[3] = "#....B##########"                                  # a bed by the east wall
    L = LuaRuntime(unpack_returned_tuples=True)
    env, dig = L.execute(FAKE, SRC, L.table_from(rooms))
    L.execute(QUARRY_SETUP, env, 3, False)
    r = env.quarry(10, False)
    assert r.ok, dict(r)
    for y in range(16):
        for x in range(16):
            if dig(x, y) == 1:
                assert rooms[y][x] != "S" and not (abs(x - 5) <= 2 and abs(y - 3) <= 2), (x, y)
    # an old level's outline, dropped from the project list, still keeps the quarry out
    L2 = LuaRuntime(unpack_returned_tuples=True)
    env2, dig2 = L2.execute(FAKE, SRC, L2.table_from(MAP))
    L2.execute(QUARRY_SETUP, env2, 3, False)
    L2.execute("""local env = ...
      env.reqscript = function() return {
        citizen_positions = function() return {{x = 2, y = 2, z = 10}} end,
        level_areas = function() return {{x1 = 0, y1 = 0, x2 = 6, y2 = 5, z = 10}} end} end
    """, env2)
    r = env2.quarry(10, False)
    assert not r.ok, dict(r)                                       # every wall beside the dwarves is the old level's


@test("quarry (0.104.122): a spot marked lately is left alone; another found; forgotten after 56 days")
def _():
    L = LuaRuntime(unpack_returned_tuples=True)
    env, dig = L.execute(FAKE, SRC, L.table_from(MAP))
    L.execute(QUARRY_SETUP, env, 3, False)
    L.execute("""local env = ...
      local store = {}
      env.dfhack.persistent = {getSiteData = function(k, d) return store[k] or d end,
                               saveSiteData = function(k, v) store[k] = v end}
      env.df.global.cur_year, env.df.global.cur_year_tick = 80, 1000
      env.STORE = store
    """, env)
    r1 = env.quarry(4, False)
    assert r1.ok and r1.tried is None, dict(r1)
    first = (r1.x, r1.y)
    for y in range(16):                                            # the marks go, undug
        for x in range(16):
            if dig(x, y) == 1:
                L.execute("local env, x, y = ...; env.dfhack.maps.getTileFlags(x, y, 10).dig = 0", env, x, y)
    r2 = env.quarry(4, False)
    assert r2.ok and (r2.x, r2.y) != first and r2.tried == 1, (dict(r2), first)
    assert abs(r2.x - first[0]) > 4 or abs(r2.y - first[1]) > 4, (dict(r2), first)
    L.execute("local env = ...; env.df.global.cur_year_tick = 1000 + 57 * 1200", env)
    for y in range(16):
        for x in range(16):
            if dig(x, y) == 1:
                L.execute("local env, x, y = ...; env.dfhack.maps.getTileFlags(x, y, 10).dig = 0", env, x, y)
    r3 = env.quarry(4, False)
    assert r3.ok and (r3.x, r3.y) == first, (dict(r3), first)  # forgotten: the nearest again


if __name__ == "__main__":
    finish()
