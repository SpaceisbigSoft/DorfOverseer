"""(0.105.30, construction G3) What the fort has built, counted
(lua/ai-constructions.lua), and the bridge's wiring for the construction
round: the `constructions` section, the census, the halls in the buildings
report, and the place_hall / build_wings / floor_rooms actions. On a stub
DFHack in a real Lua 5.3 engine (pip install lupa).

    python tests/test_construct_report.py
"""

from __future__ import annotations

import re
import sys

from harness import ROOT, finish, test

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package with Lua 5.3 (pip install lupa)")
    sys.exit(0)

LUA_DIR = ROOT / "lua"
SRC = (LUA_DIR / "ai-constructions.lua").read_text(encoding="utf-8")
HUB = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
VERSION = re.search(r"^BRIDGE_VERSION = '([^']+)'", HUB, re.M).group(1)

# A small fake world. Tiles: W.tiles["x,y,z"] = {shape, sub (subterranean), out (outside)}.
# Shapes are tiletype numbers: 1 wall, 2 floor, 3 ramp, 4 stair_updown, 5 fortification, 6 pebbles, 7 empty.
FAKE = r"""
local src = ...
local W = {tiles = {}, cons = {}, buildings = {}, persist = {}, scripts = {}, reads = 0, tick = 1000}
local SHAPE_NAMES = {[1] = 'WALL', [2] = 'FLOOR', [3] = 'RAMP', [4] = 'STAIR_UPDOWN', [5] = 'FORTIFICATION',
                     [6] = 'PEBBLES', [7] = 'EMPTY'}
local attrs = {}
for i = 1, 7 do attrs[i] = {shape = i} end
local cons_holder = {}
W.event = setmetatable({}, {__index = function(_, k)
    if k == 'constructions' then W.reads = W.reads + 1; return W.cons end
end})
local df = {
  global = {cur_year = 250, cur_year_tick = 1000, plotinfo = {site_id = 3},
            world = {event = W.event, buildings = {all = W.buildings}}},
  tiletype = {attrs = attrs}, tiletype_shape = SHAPE_NAMES,
  item_type = {[0] = 'BAR', [1] = 'BLOCKS', [2] = 'BOULDER', [3] = 'WOOD', [4] = 'GLOB'},
  building_type = {Construction = 99}, construction_type = {[0] = 'Wall', [1] = 'Floor', [2] = 'UpStair'},
}
setmetatable(df.global, {__index = function(_, k) if k == 'cur_year_tick' then return W.tick end end})
df.global.cur_year_tick = nil
local function k(x, y, z) return x .. ',' .. y .. ',' .. z end
local dfhack = {
  maps = {getTileType = function(x, y, z) local t = W.tiles[k(x, y, z)]; return t and t.shape or 7 end,
          getTileFlags = function(x, y, z) local t = W.tiles[k(x, y, z)] or {}
            return {subterranean = t.sub == true, outside = t.out == true} end},
  persistent = {getSiteData = function(key, d) local v = W.persist[key]; if v == nil then return d end; return v end},
}
local env = setmetatable({df = df, dfhack = dfhack,
  reqscript = function(n) if W.scripts[n] then return W.scripts[n] end error('no ' .. n) end}, {__index = _G})
assert(load(src, 'ai-constructions', 't', env))()
W.env, W.df = env, df
function W.tile(x, y, z, shape, sub, out) W.tiles[k(x, y, z)] = {shape = shape, sub = sub, out = out} end
function W.con(x, y, z, shape, item, sub, top)
  W.tile(x, y, z, shape, sub, false)
  table.insert(W.cons, {pos = {x = x, y = y, z = z}, item_type = item, flags = {top_of_wall = top == true}})
end
function W.planned(t) table.insert(W.buildings, {type = t, getType = function() return 99 end}) end
function W.other_building() table.insert(W.buildings, {type = 0, getType = function() return 5 end}) end
function W.reset()
  for key in pairs(W.tiles) do W.tiles[key] = nil end
  for i = #W.cons, 1, -1 do W.cons[i] = nil end
  for i = #W.buildings, 1, -1 do W.buildings[i] = nil end
  for key in pairs(W.persist) do W.persist[key] = nil end
  for key in pairs(W.scripts) do W.scripts[key] = nil end
  W.reads, W.tick = 0, 1000
  env.SURVEY_CACHE = nil
  env.SURVEY_SECONDS = 0.25
  df.global.world.event = W.event
  df.global.world.constructions = nil
end
return W
"""

LUA = LuaRuntime(unpack_returned_tuples=True)
W = LUA.execute(FAKE, SRC)
BAR, BLOCKS, BOULDER, LOG, GLOB = 0, 1, 2, 3, 4
WALL, FLOOR, RAMP, STAIRS, FORT, PEBBLES = 1, 2, 3, 4, 5, 6


def t(d):
    if isinstance(d, dict):
        return LUA.table_from({k: t(v) for k, v in d.items()})
    if isinstance(d, list):
        return LUA.table_from([t(v) for v in d])
    return d


def small_fort():
    """Surface z=80: a 3x1 roofed shed (walls at y=10, floors over 2 tiles at z=81); underground z=60."""
    W.reset()
    W.con(10, 10, 80, WALL, BLOCKS, False)
    W.con(10, 10, 81, FLOOR, BLOCKS, False, True)      # the wall's top: skipped
    W.con(11, 10, 80, WALL, BOULDER, False)
    W.con(12, 11, 81, FLOOR, BLOCKS, False)            # a roof over a walkable, inside tile
    W.tile(12, 11, 80, FLOOR, False, False)
    W.con(13, 11, 81, FLOOR, LOG, False)               # over open sky: no roof
    W.tile(13, 11, 80, FLOOR, False, True)
    W.con(14, 11, 81, FLOOR, BAR, False)               # over a wall: not walkable
    W.tile(14, 11, 80, WALL, False, False)
    W.con(20, 20, 60, WALL, BOULDER, True)
    W.con(21, 20, 60, RAMP, GLOB, True)
    W.con(22, 20, 60, STAIRS, BLOCKS, True)
    W.con(23, 20, 60, FORT, BLOCKS, True)
    W.con(24, 20, 60, PEBBLES, BLOCKS, True)           # an odd shape: other
    W.planned(0)
    W.planned(0)
    W.planned(1)
    W.other_building()


@test("survey: built tiles by shape, material and side; wall tops skipped; roofed surface; waiting ones")
def _():
    small_fort()
    s = W.env.survey()
    assert s.total == 10 and s.wall_tops == 1, (s.total, s.wall_tops)
    b = s.by_shape
    assert (b.wall, b.floor, b.ramp, b.stair_updown, b.fortification, b.other) == (3, 3, 1, 1, 1, 1), dict(b)
    i = s.by_item
    assert (i.blocks, i.boulder, i.log, i.bar, i.other) == (5, 2, 1, 1, 1), dict(i)
    assert s.surface.total == 5 and s.surface.wall == 2 and s.surface.floor == 3, dict(s.surface)
    assert s.underground.total == 5 and s.underground.wall == 1 and s.underground.floor == 0, dict(s.underground)
    assert s.roofed_surface_tiles == 1, s.roofed_surface_tiles
    assert s.planned.n == 3 and s.planned.by_type.Wall == 2 and s.planned.by_type.Floor == 1, dict(s.planned.by_type)
    assert s.block_pct == 50 and s.where == "world.event.constructions" and not s.missing and not s.partial
    assert s.line == "Built: 3 walls, 3 floors (50% blocks), 5 above ground; 3 waiting.", s.line
    assert s.ms >= 0 and s.ai.keep == 0 and s.ai_errors is not None   # no builder or gates here: listed, not raised


@test("survey: an empty fort, the old field, and no field at all")
def _():
    W.reset()
    s = W.env.survey()
    assert s.total == 0 and s.block_pct is None and s.planned.n == 0, dict(s)
    assert s.line == "Built: 0 walls, 0 floors (- blocks), 0 above ground; 0 waiting.", s.line
    W.reset()
    W.con(1, 1, 80, WALL, BLOCKS, False)
    W.df["global"].world.constructions = W.cons
    W.df["global"].world.event = None
    s = W.env.survey(True)
    assert s.total == 1 and s.where == "world.constructions", (s.total, s.where)
    W.df["global"].world.constructions = None
    s = W.env.survey(True)
    assert s.missing and s.total == 0, dict(s)


@test("survey: kept a game day (one walk for the census and the report), walked again after or when asked")
def _():
    small_fort()
    same = LUA.eval("function(a, b) return rawequal(a, b) end")
    a = W.env.survey()
    W.tick = 1000 + 1199
    assert same(W.env.survey(), a) and W.reads == 1, W.reads
    assert not same(W.env.survey(True), a) and W.reads == 2
    W.tick = 1000 + 1199 + 1200
    W.env.survey()
    assert W.reads == 3, W.reads


@test("survey: the time cap stops the walk and says so")
def _():
    W.reset()
    for x in range(600):
        W.con(x, 5, 80, WALL, BLOCKS, False)
    W.env.SURVEY_SECONDS = -1
    s = W.env.survey(True)
    assert s.partial and s.total == 255, (s.partial, s.total)


@test("ai: the keep, a hall, the cistern, gate walls and wings, a cavern wall, room walls, soil floors")
def _():
    W.reset()
    W.persist["ai-overseer/keep"] = t({"stage": "roof", "x": 50, "y": 50, "z": 80, "r": 3})
    W.persist["ai-overseer/halls"] = t({"list": [{"kind": "field_hall", "x1": 70, "y1": 70, "x2": 78, "y2": 76,
                                                  "z": 80, "stage": "roof", "tiles": ["90,90,80"]}]})
    W.persist["ai-overseer/cistern"] = t({"sealing": {"30,30,40": "Cw"}})
    W.scripts["ai-gates"] = t({"GATES": {"entrances": [
        {"id": 1, "kind": "surface", "x": 100, "y": 100, "z": 80, "width": 1, "wings": ["110,95,80"]},
        {"id": 2, "kind": "cavern", "x": 5, "y": 5, "z": 20, "width": 2}]}})
    W.scripts["ai-builder"] = LUA.eval("""{registry_report = function() return {
        {id = 7, kind = 'dining', bounds = {x1 = 40, y1 = 40, x2 = 44, y2 = 43, z = 50}}} end}""")
    W.con(53, 50, 80, WALL, BLOCKS, False)          # keep ring
    W.con(50, 50, 81, FLOOR, BLOCKS, False)         # keep roof
    W.con(70, 73, 80, WALL, BLOCKS, False)          # hall wall
    W.con(74, 73, 81, FLOOR, BLOCKS, False)         # hall roof
    W.con(90, 90, 80, WALL, BLOCKS, False)          # a hall's recorded tile outside its box
    W.con(30, 30, 40, WALL, BOULDER, True)          # cistern seal
    W.con(103, 100, 80, WALL, BLOCKS, False)        # gate wall
    W.con(104, 100, 80, FLOOR, BLOCKS, False)       # a floor by the gate: not a gate piece
    W.con(110, 95, 80, WALL, BLOCKS, False)         # a recorded wing (outside the gate box)
    W.con(6, 5, 20, WALL, BOULDER, True)            # a cavern opening walled
    W.con(6, 6, 20, FLOOR, BOULDER, True)           # ...a floor there: not counted
    W.con(39, 41, 50, WALL, BOULDER, True)          # a room's wall, on its edge
    W.con(42, 42, 50, FLOOR, BLOCKS, True)          # a soil floor in the room
    W.con(200, 200, 50, WALL, BOULDER, True)        # the player's own
    a = W.env.survey(True).ai
    got = {k: a[k] for k in ("keep", "halls", "cistern", "gate_pieces", "wings", "cavern_walls", "room_walls",
                             "soil_floors")}
    assert got == {"keep": 2, "halls": 3, "cistern": 1, "gate_pieces": 1, "wings": 1, "cavern_walls": 1,
                   "room_walls": 1, "soil_floors": 1}, got


@test("ai: a project's soil-floor record claims its tiles; the keep comes before a way in near it; a broken record is listed")
def _():
    W.reset()
    W.persist["ai-overseer/keep"] = t({"stage": "walls", "x": 100, "y": 104, "z": 80, "r": 2})
    W.scripts["ai-gates"] = t({"GATES": {"entrances": [{"id": 1, "kind": "surface", "x": 100, "y": 100, "z": 80}]}})
    W.con(9, 9, 70, FLOOR, BLOCKS, False)
    W.con(102, 102, 80, WALL, BLOCKS, False)        # in both the keep's box and the gate's
    W.scripts["ai-builder"] = LUA.eval("""{registry_report = function() error('boom') end,
        load_projects = function() return {list = {{id = 4, z = 70, soil_floors = {'9,9'}}}} end,
        soil_floor_report = function() return {projects = {{project_id = 4, kind = 'dining', tiles = 3, floored = 1}},
                                               tiles = 3, floored = 1, blocks_needed = 3} end}""")
    s = W.env.survey(True)
    assert s.ai.soil_floors == 1 and s.ai.keep == 1 and s.ai.gate_pieces == 0, dict(s.ai)
    assert "boom" in s.ai_errors.projects, dict(s.ai_errors)
    # the soil still bare, as the brain's soil floor step reads it (a list of projects)
    assert s.soil_floors_placed == 1
    assert s.soil_floors[1].project_id == 4 and s.soil_floors[1].tiles == 3 and s.soil_floors_left == 3


@test("census: carries the constructions survey; an error there stays in its own field")
def _():
    census = (LUA_DIR / "ai-census.lua").read_text(encoding="utf-8")
    env = LUA.execute(r"""
      local src, survey = ...
      local env = setmetatable({}, {__index = _G})
      env.df = {global = {world = {units = {active = {}}, items = {all = {}}, jobs = {list = {next = nil}}}}}
      env.dfhack = {units = {}}
      env.reqscript = function(n) if n == 'ai-constructions' and survey then return {survey = survey} end
                                  error('no ' .. n) end
      assert(load(src, 'ai-census', 't', env))()
      return env""", census, LUA.eval("function() return {total = 4, line = 'Built: x'} end"))
    r = env.census()
    assert r.ok and r.constructions.total == 4, dict(r.constructions)
    env2 = LUA.execute(r"""
      local src = ...
      local env = setmetatable({}, {__index = _G})
      env.df = {global = {world = {units = {active = {}}, items = {all = {}}, jobs = {list = {next = nil}}}}}
      env.dfhack = {units = {}}
      env.reqscript = function(n) error('no ' .. n) end
      assert(load(src, 'ai-census', 't', env))()
      return env""", census)
    r = env2.census()
    assert r.ok and "no ai-constructions" in r.constructions.error, dict(r.constructions)


# ---- the bridge -----------------------------------------------------------

_hyg = (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8")
HARNESS = re.search(r'HARNESS = r"""(.*?)"""', _hyg, re.S).group(1)
BL = LuaRuntime(unpack_returned_tuples=True)
H = BL.execute(HARNESS, HUB, str(LUA_DIR))
NEW = ("place_hall", "build_wings", "floor_rooms")


def bt(d):
    if isinstance(d, dict):
        return BL.table_from({k: bt(v) for k, v in d.items()})
    if isinstance(d, list):
        return BL.table_from([bt(v) for v in d])
    return d


def fresh():
    H.scripts = BL.table()
    H.halted = False
    return H.module()


@test("bridge: the new actions in ACTIONS, DRY_OK and CACHE_INVALIDATES; the section cached 3 days; the module listed")
def _():
    M = fresh()
    for n in NEW:
        assert BL.eval(f"function(M) return M.ACTIONS.{n} == M.act_{n} and type(M.act_{n}) == 'function' end")(M), n
        assert M.DRY_OK[n] is True, n
        assert list(M.CACHE_INVALIDATES[n].values()) == ["constructions"], n
    assert list(M.CACHE_INVALIDATES.place_keep.values()) == ["constructions"]
    assert M.SECTIONS.constructions is not None and M.SECTION_CACHE_DAYS.constructions == 3
    assert "ai-constructions" in list(M.BRIDGE_MODULES.values())
    assert "ai-constructions" in list(M.MARKED_MODULES.values())
    assert f"PART_VERSIONS = {{['ai-constructions'] = '{VERSION}'}}" in SRC


@test("bridge: the constructions section asks the module, and a failure stays in that section")
def _():
    M = fresh()
    H.scripts["ai-constructions"] = BL.eval("{survey = function() return {total = 9} end}")
    assert M.SECTIONS.constructions().total == 9
    H.scripts["ai-constructions"] = BL.eval("{survey = function() error('bad tile') end}")
    assert "bad tile" in M.SECTIONS.constructions().error


@test("bridge: place_hall checks its kind and passes the dry run; a builder without it refuses")
def _():
    M = fresh()
    r = H.act(M, bt({"type": "place_hall", "kind": "tower"}))
    assert not r.ok and r.rejected and "field_hall|market_hall" in r.error, dict(r)
    H.scripts["ai-builder"] = BL.eval("{}")
    r = H.act(M, bt({"type": "place_hall", "kind": "field_hall"}))
    assert not r.ok and r.rejected and "not loaded" in r.error, dict(r)
    H.scripts["ai-builder"] = BL.eval("{place_hall = function(kind, dry) return {ok = true, kind = kind, dry_run = dry} end}")
    r = H.act(M, bt({"type": "place_hall", "kind": "market_hall", "dry_run": True}))
    assert r.ok and r.kind == "market_hall" and r.dry_run is True, dict(r)
    H.halted = True                                    # a dry run passes the halt (DRY_OK)
    r = H.act(M, bt({"type": "place_hall", "kind": "field_hall", "dry_run": True}))
    assert r.ok and r.dry_run is True, dict(r)


@test("bridge: build_wings needs an entrance id, floor_rooms a project id; each passes it on with the dry run")
def _():
    M = fresh()
    r = H.act(M, bt({"type": "build_wings"}))
    assert not r.ok and "entrance_id" in r.error, dict(r)
    r = H.act(M, bt({"type": "floor_rooms", "project_id": "x"}))
    assert not r.ok and "project_id" in r.error, dict(r)
    H.scripts["ai-gates"] = BL.eval("{build_wings = function(id, dry) return {ok = true, id = id, dry_run = dry} end}")
    H.scripts["ai-builder"] = BL.eval("{floor_soil_rooms = function(id, dry) return {ok = true, id = id, dry_run = dry} end}")
    r = H.act(M, bt({"type": "build_wings", "entrance_id": 4}))
    assert r.ok and r.id == 4 and r.dry_run is False, dict(r)
    r = H.act(M, bt({"type": "floor_rooms", "project_id": 12, "dry_run": True}))
    assert r.ok and r.id == 12 and r.dry_run is True, dict(r)


@test("bridge: fortify_entrance takes the sealed style")
def _():
    M = fresh()
    H.scripts["ai-gates"] = BL.eval("{fortify = function(id, style) return {ok = true, id = id, style = style} end}")
    r = H.act(M, bt({"type": "fortify_entrance", "entrance_id": 2, "style": "sealed"}))
    assert r.ok and r.style == "sealed", dict(r)
    r = H.act(M, bt({"type": "fortify_entrance", "entrance_id": 2, "style": "moat"}))
    assert not r.ok and "sealed" in r.error, dict(r)


@test("bridge: the buildings report carries the halls beside the keep (nil when the builder has none)")
def _():
    M = fresh()
    H.df.building_type = BL.eval("{Stockpile = 1, Civzone = 2, Workshop = 3, Furnace = 4}")
    H.df["global"].world.buildings = BL.eval("{all = {}}")
    H.scripts["ai-builder"] = BL.eval("""{halls_status = function() return {{kind = 'field_hall', stage = 'roof',
        walls_planned = 0, roof_planned = 12}} end, keep_status = function() return nil end}""")
    b = M.get_buildings()
    assert b.halls[1].stage == "roof" and b.halls[1].roof_planned == 12, dict(b)
    H.scripts["ai-builder"] = BL.eval("{}")
    assert M.get_buildings().halls is None


@test("contract: G1 and G2 export the functions the actions call (once their files carry them)")
def _():
    halls = LUA_DIR / "ai-builder-halls.lua"
    want = []
    if halls.exists():
        want += [(halls, "place_hall"), (halls, "halls_status"), (halls, "find_hall_site")]
    gates = (LUA_DIR / "ai-gates-wings.lua").read_text(encoding="utf-8")   # (13e) the gates' wings part
    if "plan_wings" in gates:
        want.append((LUA_DIR / "ai-gates-wings.lua", "build_wings"))
    rooms = (LUA_DIR / "ai-builder-rooms.lua").read_text(encoding="utf-8")
    if "soil_floor" in rooms:
        want.append((LUA_DIR / "ai-builder-rooms.lua", "floor_soil_rooms"))
    for path, fn in want:
        assert re.search(rf"^function {fn}\(", path.read_text(encoding="utf-8"), re.M), (path.name, fn)


if __name__ == "__main__":
    finish()
