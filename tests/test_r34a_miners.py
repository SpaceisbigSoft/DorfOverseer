"""(r34a) Fort E, the Deep mine (26 Nov, 0.105.129): 26-27 miners and
nothing to dig, 32-36% of the fort idle.

- `prospect` refused "no vein within 30 tiles" every time: the bridge's drift
  search (lua/ai-industry.lua find_drift) spent its 8,000 tiles on the first
  few of 400 vein tiles nearest the citizens' middle, wherever they lay, only
  on the levels a citizen stood on, and kept the empty answer a week. Now a
  vein tile needs seen ground within reach, a vein gives at most 4 tiles, the
  AI's levels count, a search reaches its full 30 tiles, a hidden tile skips
  the zone lookup, and the refusal says what it found and what turned it back;
- the quarry marked 1-5 tiles (only the face of a wall is uncovered; every
  tile past the first had to be) and asked 12 tiles for 11 boulders when DF
  leaves a boulder for about one tile in four: the rock behind the face is
  quarried now, the chamber's reach grows, and the brain asks 4 tiles a
  boulder (at most 60, twice the Mining slider's size);
- with no vein to be had the idle miners get exploratory tunnels (rule
  `explore`, the bridge's explore_dig): straight tunnels from the dwarves'
  ground into unseen rock, away from the levels, one miner each, going on
  from the last ends.

The Lua tests need lupa (need_lua: skipped without it).

    python tests/test_r34a_miners.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
import hold_classes as hc  # noqa: E402
import planner_prospect as PP  # noqa: E402
from design_rules import PRESET_SLIDERS  # noqa: E402
from overseer_words import short as describe_action  # noqa: E402
from planner import Memory, PLANNER_CONFIG, Proposal  # noqa: E402
from planner_core import TICKS_PER_DAY, abs_tick  # noqa: E402
from planner_industry_stone import quarry_size  # noqa: E402

CFG = PLANNER_CONFIG


# --- the brain -----------------------------------------------------------------------

def fort(preset="Deep mine", miners=27, dig=0, gems=4, ore_stock=400, threats=0, pop=58, usable=9):
    return {"settings": {"traits": dict(PRESET_SLIDERS[preset]), "preset": preset},
            "dwarves": {"total": pop}, "date": {"year": 258, "tick": 100000},
            "labor": {"miners": miners, "dig": dig},
            "industry": {"ore_stock": ore_stock, "ore_stock_by": {}, "ores": {}},
            "stocks": {"rough_gems": gems}, "military": {"gear": {"bars": {}}},
            "others_on_map": {"threats_that_can_reach_dwarves": threats},
            "buildings": {}, "supplies": {}, "projects": {"open": []}, "orders": [],
            "stone_use": {"usable": usable}}


def refused_gems(s, m):
    """Exploratory mining's gem vein refused (its back-off running)."""
    p = Proposal("prospect", {"type": "mine_ore", "metal": "GEM", "count": 80, "prospect": True}, "x", 6)
    from planner_core_refusals import refusal_key
    m.refusals[refusal_key(p)] = {"n": 1, "until": abs_tick(s) + 3 * TICKS_PER_DAY, "at": abs_tick(s)}


def explore(s, m, proposals=None):
    props, notes = list(proposals or []), []
    PP._prospect_rule(s, m, CFG, props, notes)
    PP._explore_rule(s, m, CFG, props, notes)
    return props, notes


@test("E: 27 miners, 0 tiles, the gem vein refused: exploratory tunnels, sized by Mining, the reason honest")
def _():
    s, m = fort(), Memory()
    refused_gems(s, m)
    props, _ = explore(s, m)
    assert [p.rule for p in props] == ["explore"], props
    p = props[0]
    assert p.action == {"type": "explore_dig", "count": 67, "tunnels": 5}, p.action      # 24 x 2.83; 27 // 5
    assert "27 miners with only 0 tiles to dig" in p.reason and "found none in reach" in p.reason, p.reason
    assert "about one tile in four leaves a boulder" in p.reason, p.reason
    assert describe_action(p.action).startswith("dig 5 exploratory tunnel(s), 67 tiles"), describe_action(p.action)


@test("explore: never when exploratory mining or a quarry gives work this cycle, nor with digging waiting")
def _():
    s, m = fort(), Memory()
    props, _ = explore(s, m)                                     # the gem vein not refused: prospect's
    assert [p.rule for p in props] == ["prospect"], props
    s2, m2 = fort(), Memory()
    refused_gems(s2, m2)
    q = Proposal("quarry", {"type": "quarry", "count": 44}, "q", 4)
    props, _ = explore(s2, m2, [q])
    assert [p.rule for p in props] == ["quarry"], props
    s3, m3 = fort(dig=500), Memory()                             # 500 tiles waiting: the miners have work
    refused_gems(s3, m3)
    assert explore(s3, m3)[0] == []
    s4, m4 = fort(miners=3), Memory()                            # 3 miners (region2's old saves): no tunnels
    refused_gems(s4, m4)
    assert explore(s4, m4)[0] == []


@test("explore: paced by Mining (a day at least), none under threat, at Mining -50 or lower, or for a young fort")
def _():
    s, m = fort(), Memory()
    refused_gems(s, m)
    m.last_fired["explore"] = abs_tick(s) - TICKS_PER_DAY // 2
    assert explore(s, m)[0] == []
    m.last_fired["explore"] = abs_tick(s) - TICKS_PER_DAY
    assert [p.rule for p in explore(s, m)[0]] == ["explore"]
    for kw in ({"threats": 2}, {"preset": "Garden fort"}, {"pop": 8}):
        s, m = fort(**kw), Memory()
        refused_gems(s, m)
        assert explore(s, m)[0] == [], kw
    s, m = fort(gems=500), Memory()                               # gems and ore enough: tunnels all the same
    props, _ = explore(s, m)
    assert [p.rule for p in props] == ["explore"] and "enough in store" in props[0].reason, props


@test("explore: the Hermit hold (Mining 0) digs smaller tunnels, a slower pace; the wiring")
def _():
    s, m = fort(preset="Hermit hold", miners=12), Memory()
    refused_gems(s, m)
    props, _ = explore(s, m)
    assert props and props[0].action == {"type": "explore_dig", "count": 24, "tunnels": 2}, props
    assert hc.rule_class("explore") == hc.EXPANSION if hasattr(hc, "rule_class") else True
    assert "explore_dig" in hc._EXPANSION_ACTIONS
    import planner
    src = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")
    assert "_guard(_explore_rule, s, memory, cfg, proposals, notes)" in src
    assert planner.RULE_LABELS.get("explore") if hasattr(planner, "RULE_LABELS") else True
    cat = (ROOT / "lua" / "ai-bridge-catalog.lua").read_text(encoding="utf-8")
    assert "explore_dig = act_explore_dig," in cat and "'explore_dig'," in cat
    act = (ROOT / "lua" / "ai-bridge-actions-works.lua").read_text(encoding="utf-8")
    assert "reqscript('ai-industry').explore(n, t, a.dry_run == true)" in act


@test("quarry_size: 4 tiles a boulder wanted, at most twice the Mining slider's size and 60 (E: 44, was 12)")
def _():
    s = fort(usable=9)                                            # 2 x 10 - 9 = 11 boulders
    assert quarry_size(s, CFG) == 44, quarry_size(s, CFG)
    assert quarry_size(fort(usable=0), CFG) == 60                 # 20 boulders: 80 tiles, capped
    assert quarry_size(fort(preset="Garden fort", usable=0), CFG) == 26     # the slider's 13 (Mining -60): 26
    assert quarry_size(fort(usable=30), CFG) == 32                # at least quarry_min_tiles (8) boulders
    act = (ROOT / "lua" / "ai-bridge-actions-civic.lua").read_text(encoding="utf-8")
    assert "int_in(a.count or 30, 1, 60)" in act


# --- the bridge (lupa) ---------------------------------------------------------------

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
            d = {hidden = ch == '?' or ch == ',', dig = 0, flow_size = ch == 'w' and 7 or 0, water_table = false,
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
-- (r34a) the site's data kept, zone lookups counted, a tile dug by the test
local store = {}
env.dfhack.persistent = {getSiteData = function(k, default) local v = store[k]; if v == nil then return default end; return v end,
                         saveSiteData = function(k, v) store[k] = v end}
env.ZONE_CALLS = 0
env.dfhack.buildings = {findCivzonesAt = function() env.ZONE_CALLS = env.ZONE_CALLS + 1; return {} end}
assert(load(src, 'ai-industry', 't', env))()
local function dug(x, y)
    local t = tiles[key(x, y, 10)]
    t.ch = '.'; t.d.hidden = false; t.d.dig = 0
end
return env, function(x, y) return at(x, y, 10).d.dig end, dug
"""

# z 10, one block: a room ('.') x6-9 y6-9, its walls ('#') uncovered, the rock
# beyond hidden (','); the citizen in the room
ROOM = [",,,,,,,,,,,,,,,,"] * 5 + [",,,,,######,,,,,"] + [",,,,,#....#,,,,,"] * 4 + [",,,,,######,,,,,"] + [",,,,,,,,,,,,,,,,"] * 5

SETUP = """
local env, layer_idx = ...
env.SURVEY_MARGIN = 7
env.df.tiletype.attrs[1].material = 1
env.df.tiletype.attrs[2].material = 1
env.df.tiletype.attrs[3].material = 1
env.df.tiletype_material = {[1] = 'STONE'}
env.df.global.plotinfo = {economic_stone = {}}
for i = 0, 200 do env.df.global.plotinfo.economic_stone[i] = false end
setmetatable(env.df.global.plotinfo.economic_stone, {__len = function() return 201 end})
env.df.global.world.raws.inorganics.all[3] = {id = 'GRANITE', metal_ore = {mat_index = {}}}
local block = env.dfhack.maps.getTileBlock(0, 0, 10)
for x = 0, 15 do for y = 0, 15 do block.designation[x][y].geolayer_index = 0 end end
env.dfhack.maps.getTileBiomeRgn = function() return 1, 1 end
env.dfhack.maps.getRegionBiome = function() return {geo_index = 5} end
env.df.world_geo_biome = {find = function() return {layers = {[0] = {mat_index = layer_idx}}} end}
local real = env.reqscript          -- (the modules themselves still answer: the tunnels' half loads on call)
env.REAL_REQ = real
env.reqscript = function(name)
    if name == 'ai-util' or name == 'ai-industry' or name == 'ai-industry-explore' then return real(name) end
    return {citizen_positions = function() return {{x = 7, y = 7, z = 10}} end,
            load_projects = function() return {list = {}} end}
end
"""


def lua_game(rows, setup=True):
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    env, dig, dug = L.execute(FAKE, module_src("ai-industry.lua"), L.table_from(rows))
    if setup:
        L.execute(SETUP, env, 3)
    return L, env, dig, dug


def run_lua(rows, body, setup=True):
    """body: a Lua function(env, dig, dug) with its own asserts."""
    L, env, dig, dug = lua_game(rows, setup)
    L.eval(body)(env, dig, dug)


QUARRY_BODY = """function(env, dig, dug)
    local r = env.quarry(30, false)
    assert(r.ok and r.stone == 'GRANITE', r.error)
    -- the face is uncovered; the 29 tiles behind it were hidden rock (before: the face's 4-7 tiles)
    assert(r.tiles == 30, 'tiles ' .. tostring(r.tiles))
    local hidden_marked = 0
    for x = 0, 15 do for y = 0, 15 do
        local ring = (x >= 5 and x <= 10 and (y == 5 or y == 10)) or ((x == 5 or x == 10) and y >= 6 and y <= 9)
        if dig(x, y) == 1 and not ring then hidden_marked = hidden_marked + 1 end
    end end
    assert(hidden_marked >= 20, 'hidden rock marked ' .. hidden_marked)
    -- (the old reach, 3, keeps a small quarry small)
    local r2 = env.quarry(6, true)
    assert(r2.ok and r2.tiles == 6, 'small ' .. tostring(r2.tiles))
end"""


@test("(lua) quarry: the rock behind the uncovered face is quarried (30 tiles asked, 30 marked; was the face only)")
def _():
    need_lua()
    run_lua(ROOM, QUARRY_BODY)


QUARRY_WATER_BODY = """function(env, dig, dug)
    local r = env.quarry(60, false)
    assert(r.ok, r.error)
    for x = 0, 15 do for y = 0, 15 do
        if dig(x, y) == 1 then assert(math.abs(x - 13) > 1 or math.abs(y - 7) > 1, 'beside water ' .. x .. ',' .. y) end
    end end
end"""


@test("(lua) quarry: hidden rock beside water is never quarried")
def _():
    need_lua()
    rows = list(ROOM)
    rows[7] = ",,,,,#....#,,w,,"
    run_lua(rows, QUARRY_WATER_BODY)


EXPLORE_BODY = """function(env, dig, dug)
    local r = env.explore(16, 2, true)
    assert(r.ok and r.tunnels == 2 and r.tiles == 12 and r.dry_run, r.error or ('tiles ' .. tostring(r.tiles)))
    for x = 0, 15 do for y = 0, 15 do assert(dig(x, y) == 0, 'a dry run marks nothing') end end
    r = env.explore(16, 2, false)
    assert(r.ok and r.tunnels == 2 and r.tiles == 12 and r.continued == 0, 'tiles ' .. tostring(r.tiles))
    -- two straight tunnels, out from the room's walls, 3 tiles apart at least
    local marked = {}
    for x = 0, 15 do for y = 0, 15 do if dig(x, y) == 1 then marked[#marked + 1] = {x = x, y = y} end end end
    assert(#marked == 12, #marked)
    for _, t in ipairs(marked) do
        assert(not (t.x >= 6 and t.x <= 9 and t.y >= 6 and t.y <= 9), 'never the room')
    end
    -- dug: the next call goes on from the ends (turned aside at the survey's edge)
    for _, t in ipairs(marked) do dug(t.x, t.y) end
    r = env.explore(16, 2, false)
    assert(r.ok and r.continued == 2 and r.tunnels == 2, 'continued ' .. tostring(r.continued) .. ' ' .. tostring(r.error))
    -- nowhere 4 tiles long: refused, said why (the last tunnels dug first: (r35b) marked ones hold their slots)
    for x = 0, 15 do for y = 0, 15 do if dig(x, y) == 1 then dug(x, y) end end end
    env.reqscript('ai-industry-explore').EXPLORE_MIN_RUN = 40
    r = env.explore(80, 1, false)
    assert(not r.ok and r.rejected and r.error:find('no wall beside the dwarves'), r.error)
end"""


@test("(lua) explore: two straight tunnels into unseen rock from the room's walls, then on from their ends")
def _():
    need_lua()
    run_lua(ROOM, EXPLORE_BODY)


EXPLORE_PENDING_BODY = """function(env, dig, dug)
    local r = env.explore(16, 2, false)
    assert(r.ok and r.tunnels == 2 and r.tiles == 12, 'first ' .. tostring(r.tiles))
    -- (r35b) not dug yet: the two tunnels hold their slots, nothing new marked
    local before = 0
    for x = 0, 15 do for y = 0, 15 do if dig(x, y) == 1 then before = before + 1 end end end
    r = env.explore(16, 2, false)
    assert(r.ok and r.tiles == 0 and r.tunnels == 0 and r.pending == 2 and r.waiting:find('still being dug'),
           'pending ' .. tostring(r.pending) .. ' tiles ' .. tostring(r.tiles))
    local after = 0
    for x = 0, 15 do for y = 0, 15 do if dig(x, y) == 1 then after = after + 1 end end end
    assert(after == before, 'marked ' .. before .. ' -> ' .. after)
    -- three wanted, two pending: one new tunnel only
    r = env.explore(24, 3, false)
    assert(r.ok and r.tunnels == 1 and r.pending == 2, 'one more ' .. tostring(r.tunnels) .. ' ' .. tostring(r.error))
end"""


@test("(lua) explore: tunnels still marked for digging hold their slots (B, D, E 26 Nov: new stubs every day)")
def _():
    need_lua()
    run_lua(ROOM, EXPLORE_PENDING_BODY)


EXPLORE_LEVELS_BODY = """function(env, dig, dug)
    env.reqscript = function(name)
        if name == 'ai-util' or name == 'ai-industry' or name == 'ai-industry-explore' then return env.REAL_REQ(name) end
        return {citizen_positions = function() return {{x = 7, y = 7, z = 10}} end,
                load_projects = function() return {list = {{area = {x1 = 0, y1 = 0, x2 = 15, y2 = 3, z = 10}}}} end}
    end
    local r = env.explore(16, 2, false)
    assert(r.ok, r.error)
    for x = 0, 15 do for y = 0, 5 do assert(dig(x, y) == 0, 'within 2 tiles of a level: ' .. x .. ',' .. y) end end
end"""


@test("(lua) explore: never within 2 tiles of the AI's levels")
def _():
    need_lua()
    run_lua(ROOM, EXPLORE_LEVELS_BODY)


EXPLORE_STAIR_BODY = """function(env, dig, dug)
    env.reqscript = function(name)
        if name == 'ai-util' or name == 'ai-industry' or name == 'ai-industry-explore' then return env.REAL_REQ(name) end
        return {citizen_positions = function() return {{x = 7, y = 7, z = 10}} end,
                load_projects = function() return {list = {}} end,
                find_main_stair = function() return {x = 7, y = 4} end}
    end
    local r = env.explore(16, 2, false)
    assert(r.ok, r.error)
    for x = 3, 11 do for y = 0, 8 do assert(dig(x, y) == 0, 'beside the main stair: ' .. x .. ',' .. y) end end
end"""


@test("(lua) explore: never within 4 tiles of the main stair's column (its hub)")
def _():
    need_lua()
    run_lua(ROOM, EXPLORE_STAIR_BODY)


# the 0.105.9 drift map: a level x1-5 y1-4, the vein in its walls, a hidden vein beyond
DRIFT = ["################",
         "#.....##########",
         "#.....hh####??##",
         "#.....##########",
         "#.....##########"] + ["################"] * 11

DRIFT_BODY = """function(env, dig, dug)
    env.reqscript = function() return {
        citizen_positions = function() return {{x = 2, y = 2, z = 10}} end,
        load_projects = function() return {list = {{area = {x1 = 1, y1 = 1, x2 = 5, y2 = 4, z = 10}}}} end} end
    -- a vein far out in rock nobody has seen (blocks 4 and 5 east): counted, never searched
    env.SURVEY_MARGIN = 90
    local main = env.df.global.world.map.map_blocks[1]
    local MIN = getmetatable(main.block_events[1]).__index._cls
    local far = {map_pos = {x = 64, y = 0, z = 10}, flags = {}, designation = {},
                 block_events = {setmetatable({inorganic_mat = 1, tile_bitmask = {['3,3'] = true, ['4,3'] = true}},
                                              {__index = {_cls = MIN}})}}
    for x = 0, 15 do far.designation[x] = {}; for y = 0, 15 do far.designation[x][y] = {hidden = true, dig = 0} end end
    table.insert(env.df.global.world.map.map_blocks, far)
    local get = env.dfhack.maps.getTileBlock
    env.dfhack.maps.getTileBlock = function(x, y, z)
        if z == 10 and x >= 64 and x < 80 and y >= 0 and y < 16 then return far end
        return get(x, y, z)
    end
    -- the hidden vein (x12-13) is reached by a 6-tile drift, the far one never looked at
    local r = env.mine('IRON', 40, true)
    assert(r.ok and r.drift == 6, tostring(r.error))
    local c = env.DRIFT_LAST
    assert(c.veins == 6 and c.on_levels == 6 and c.usable == 2 and c.searched == 1, c.veins .. ' ' .. c.usable .. ' ' .. c.searched)
    -- out of reach: refused, with the counts and what turned it back
    env.DRIFT_MAX = 3
    r = env.mine('IRON', 40, false)
    assert(not r.ok and r.error:find('no vein within 3 tiles', 1, true), r.error)
    assert(r.error:find("6 tile(s) of it in the survey, 6 on the fort's levels, 2 clear of the levels", 1, true), r.error)
    assert(r.error:find('1 searched', 1, true) and r.error:find('turned back:', 1, true), r.error)
    assert(r.search and r.search.searched == 1, 'the counts in the answer')
end"""


@test("(lua) drift: a hidden vein beyond the uncovered rock reached; a vein with no seen ground near never searched; the refusal's counts")
def _():
    need_lua()
    run_lua(DRIFT, DRIFT_BODY, setup=False)


LEVELS_BODY = """function(env, dig, dug)
    env.reqscript = function() return {citizen_positions = function() return {{x = 2, y = 2, z = 10}} end} end
    local zs = env.fort_levels({{x1 = 0, y1 = 0, x2 = 3, y2 = 3, z = 12}, {z = 7}, {x1 = 1}})
    assert(zs[10] and zs[12] and zs[7] and not zs[11], 'the citizens\\' level and the AI\\'s')
end"""


@test("(lua) drift: the fort's levels are the citizens' and the AI's (a level nobody stands on still counts)")
def _():
    need_lua()
    run_lua(DRIFT, LEVELS_BODY, setup=False)


ZONES_BODY = """function(env, dig, dug)
    env.ZONE_CALLS = 0
    assert(env.room_wall(13, 13, 10) == false)
    assert(env.ZONE_CALLS == 0, 'hidden ground: no zone lookups, got ' .. env.ZONE_CALLS)
    assert(env.room_wall(7, 7, 10) == false)
    assert(env.ZONE_CALLS > 0, 'seen ground: zones looked up')
end"""


@test("(lua) room_wall: hidden tiles skip the zone lookup (the costliest read of a drift's search)")
def _():
    need_lua()
    run_lua(ROOM, ZONES_BODY, setup=False)


if __name__ == "__main__":
    finish()
