"""Tests for lua/ai-builder.lua (site finding, safety checks, projects) on a
fake fort map, in a real Lua engine (pip install lupa).

    python tests/test_builder.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = []

try:
    from lupa import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

# The fake world, in Lua so the module's calls stay inside one engine.
HARNESS = r"""
local layouts_src, builder_src = ...
local function load_module(src, name, extra)
  local env = setmetatable(extra or {}, {__index=_G})
  assert(load(src, name, 't', env))()
  return env
end

local W = {}         -- W.tiles["x,y,z"] = tile table; default natural stone wall
W.size = {120, 120, 100}
W.persist = {}
W.calls = {}
function W.key(x,y,z) return x..','..y..','..z end
function W.get(x,y,z)
  if x < 0 or y < 0 or z < 0 or x >= W.size[1] or y >= W.size[2] or z >= W.size[3] then return nil end
  local t = W.tiles[W.key(x,y,z)]
  if not t then
    t = {shape='WALL', material=W.soil_levels[z] and 'SOIL' or 'STONE', aquifer=false, liquid=false, feature=false,
         outside=false, designated=false, building=false}
    W.tiles[W.key(x,y,z)] = t
  end
  return t
end
function W.set(x,y,z,fields) local t = W.get(x,y,z); for k,v in pairs(fields) do t[k]=v end end

function W.reset()
  W.tiles = {}
  W.persist = {}
  W.calls = {}
  W.placed = {}
  W.jobs = {}
  W.citizens = {}
  W.soil_levels = {}   -- z -> true: natural wall there is soil, not stone
  -- main staircase at (60,60), z 60..80; fort levels 66..80 dug out widely
  for z = 60, 80 do
    W.set(60,60,z,{shape = (z == 60) and 'STAIR_UP' or ((z == 80) and 'STAIR_DOWN' or 'STAIR_UPDOWN')})
  end
  for z = 66, 80 do
    for x = 40, 80 do for y = 55, 65 do
      if not (x == 60 and y == 60) then W.set(x,y,z,{shape='FLOOR'}) end
    end end
  end
  for i = 1, 30 do table.insert(W.citizens, {x=50+i%10, y=60, z=70 + i%3}) end
end

local function parse(text)
  -- quickfort's [symbol][priority][expansion]: h1, d(3x3), d4(2x2)
  local key, w, h = text:match('^([%a~]+)%d*%((%d+)x(%d+)%)$')
  if key then return key, tonumber(w), tonumber(h) end
  local k2 = text:match('^([%a~]+)%d+$')
  if k2 then return k2, 1, 1 end
  return text, 1, 1
end

local quickfort = {}
function quickfort.apply_blueprint(p)
  table.insert(W.calls, {mode=p.mode, command=p.command, dry_run=p.dry_run})
  local stats = {dig_designated={value=0}, dig_invalid_tiles={value=0}, out_of_bounds={value=0},
                 invalid_keys={value=0}, build_designated={value=0}, place_designated={value=0},
                 zone_designated={value=0}}
  for z, grid in pairs(p.data) do for y, row in pairs(grid) do for x, text in pairs(row) do
    local key, w, h = parse(text)
    if p.mode ~= 'dig' then
      stats[p.mode..'_designated'].value = stats[p.mode..'_designated'].value + 1
      if not p.dry_run then table.insert(W.placed, {mode=p.mode, x=x+p.pos.x, y=y+p.pos.y, z=z, text=text}) end
    elseif key == 's' or key == 'e' then
      local t = W.get(x + p.pos.x, y + p.pos.y, z + p.pos.z)
      stats.dig_designated.value = stats.dig_designated.value + 1
      if not p.dry_run then t.smoothing = true end
    else
      for dx = 0, w-1 do for dy = 0, h-1 do
        local tx, ty, tz = x + p.pos.x + dx, y + p.pos.y + dy, z + p.pos.z
        local t = W.get(tx, ty, tz)
        if not t then stats.out_of_bounds.value = stats.out_of_bounds.value + 1
        elseif t.shape == 'WALL' or (t.shape == 'STAIR_UP' and key == 'i') or ((key == 'h' or key == 'j') and t.shape == 'FLOOR')
            or (key == 'h' and t.shape == 'RAMP') then
          stats.dig_designated.value = stats.dig_designated.value + 1
          if not p.dry_run then
            t.designated = (p.command ~= 'undo')
            t.dig_text = text
          end
          if tx == 60 and ty == 60 and key == 'd' then error('dug the stair tile!') end
        else
          stats.dig_invalid_tiles.value = stats.dig_invalid_tiles.value + 1
        end
      end end
    end
  end end end
  return stats
end

_G.reqscript = function(name)
  if name == 'ai-layouts' then return LAYOUTS end
  if name == 'quickfort' then return quickfort end
  error('unexpected reqscript '..name)
end
_G.dfhack = {persistent = {
  getSiteData = function(k, default) return W.persist[k] or default end,
  saveSiteData = function(k, v) W.persist[k] = v end}}
LAYOUTS = load_module(layouts_src, 'ai-layouts')
local B = load_module(builder_src, 'ai-builder')
B.tile_info = function(x,y,z) local t = W.get(x,y,z); if not t then return nil end
  local c = {}; for k,v in pairs(t) do c[k]=v end; return c end
B.map_size = function() return W.size[1], W.size[2], W.size[3] end
B.stair_shape = function(x,y,z) local t = W.get(x,y,z)
  return t and (t.shape:find('^STAIR') and t.shape) or nil end
B.citizen_positions = function() return W.citizens end
B.job_tiles = function() return W.jobs end
-- one connected walking area: every open tile on the fort levels
B.walk_group = function(x,y,z) local t = W.get(x,y,z)
  if t and t.shape ~= 'WALL' and z >= 60 and z <= 80 then return 1 end
  return 0 end
B.floor_material = function(x,y,z) local t = W.get(x,y,z)
  return t ~= nil and t.shape == 'FLOOR' and t.material or nil end
B.mud_at = function(x,y,z) local t = W.get(x,y,z); return t ~= nil and t.mud == true end
B.tile_taken = function(x,y,z) local t = W.get(x,y,z); return t ~= nil and t.taken == true end
B.grass_at = function(x,y,z) local t = W.get(x,y,z)
  return t ~= nil and (t.shape == 'FLOOR' or t.shape == 'SHRUB')
    and (t.material == 'GRASS_LIGHT' or t.material == 'GRASS_DARK' or t.material == 'GRASS_DRY') end
B.building_at = function(x,y,z) local t = W.get(x,y,z); return t ~= nil and t.taken == true end
B.zone_types = function(x,y,z) local t = W.get(x,y,z); return (t and t.zones) or {} end
W.soil_levels = {}
W.reset()
return B, W
"""


def boot():
    lua = LuaRuntime(unpack_returned_tuples=True)
    layouts = (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8")
    builder = (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8")
    B, W = lua.execute(HARNESS, layouts, builder)
    return lua, B, W


LUA, B, W = boot()


def params(**kw):
    t = LUA.table()
    for k, v in kw.items():
        t[k] = LUA.table_from(v) if isinstance(v, list) else v
    return t


def start(**kw):
    return B.start_project(params(**kw), LUA.table_from({"year": 148, "tick": 100}))


REAL_FURNISH_PROGRESS = None


def test(name, beside=False):
    def wrap(fn):
        global REAL_FURNISH_PROGRESS
        if REAL_FURNISH_PROGRESS is None:
            REAL_FURNISH_PROGRESS = B.furnish_progress
        B.furnish_progress = REAL_FURNISH_PROGRESS
        W.reset()
        B.CAVERN_NO_SPOT = None          # (0.105.4 review) the cavern search's kept "no spot"
        B.TRY_BESIDE = beside
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


def designated_count():
    return sum(1 for t in W.tiles.values() if t.designated)


def _stair(x, y, lo, hi):
    for z in range(lo, hi + 1):
        W.set(x, y, z, LUA.table_from({"shape": "STAIR_UP" if z == lo else "STAIR_DOWN" if z == hi else "STAIR_UPDOWN"}))


@test("stairwell (0.104.82): a new stair column east of the main stair, from a fort floor down through solid rock")
def _():
    r = B.dig_stairwell(params(dir="east", elev_lo=62, elev_hi=66, min_dist=10, max_dist=40), True)
    assert r.ok and r.dry_run and designated_count() == 0, dict(r)
    r = B.dig_stairwell(params(dir="east", elev_lo=62, elev_hi=66, min_dist=10, max_dist=40), False)
    off = r.elev_top - 66
    assert r.ok and (r.x, r.y) == (70, 60) and r.levels == 5 and r.elev_bottom - off == 62, dict(r)
    assert [W.get(70, 60, z).dig_text for z in (66, 65, 64, 63, 62)] == ["j", "i", "i", "i", "u"]


@test("stairwell (0.104.82): never beside another stair, never where no fort floor reaches; refused with why")
def _():
    _stair(74, 60, 66, 80)
    r = B.dig_stairwell(params(dir="east", elev_lo=62, elev_hi=66, min_dist=10, max_dist=40), False)
    assert not r.ok and "too near another stair" in r.error, dict(r)   # the floors end at x80
    r = B.dig_stairwell(params(dir="north", elev_lo=62, elev_hi=66, min_dist=10, max_dist=40), False)
    assert not r.ok and r.rejected and "north" in r.error, dict(r)
    assert designated_count() == 0


@test("stairwells counted (0.104.82): columns of 3+ levels, a stair beside another counted once")
def _():
    assert B.stairwell_count() == 1
    _stair(68, 60, 66, 80)                                             # (where the dwarves are)
    assert B.stairwell_count() == 2
    _stair(61, 61, 66, 80)                                             # beside the main stair
    assert B.stairwell_count() == 2


@test("gate dog pen (0.104.83): a free 3x3 of inside floor near the gate, as a named pen; refused with no room")
def _():
    r = B.gate_dog_pen(params(x=60, y=60, z=80, name="AI gate dogs"), False)
    assert r.ok and abs(r.x + 1 - 60) <= 8 and abs(r.y + 1 - 60) <= 8, dict(r)
    z = [c for c in W.placed.values() if c.mode == "zone"]
    assert z and 'n{name="AI gate dogs"}(3x3)' == z[-1].text, [dict(c) for c in z]
    for zz in (78, 79, 80):
        for x in range(40, 81):
            for y in range(55, 66):
                W.set(x, y, zz, LUA.table_from({"taken": True}))
    assert not B.gate_dog_pen(params(x=60, y=60, z=80), True).ok


@test("finds the main staircase where the dwarves live")
def _():
    s = B.find_main_stair()
    assert (s.x, s.y, s.z_bottom, s.z_top) == (60, 60, 60, 80), (s.x, s.y, s.z_bottom, s.z_top)
    assert s.bottom_shape == "STAIR_UP"


@test("new bedroom level: a solid level the stairs already pass through, nearest the dwarves")
def _():
    r = start(kind="bedrooms", rooms=8, room_size=3)
    assert r.ok, r.error
    assert r.z == 65 and not r.extends_stairs, (r.z, r.extends_stairs)
    assert designated_count() == r.tiles and r.tiles > 50


@test("when no level on the stairs is free, it extends the stairs downward safely")
def _():
    for z in range(60, 66):
        W.set(70, 60, z, LUA.table_from({"shape": "FLOOR"}))      # something dug on every level
    r = start(kind="bedrooms", rooms=8, room_size=3)
    assert r.ok, r.error
    assert r.z == 59 and r.extends_stairs
    assert W.get(60, 60, 60).designated and W.get(60, 60, 59).designated   # 'i' on old bottom, 'u' below


@test("never digs into an aquifer (even a hidden one): skips that level")
def _():
    for z in range(60, 66):
        W.set(70, 60, z, LUA.table_from({"shape": "FLOOR"}))
    W.set(64, 57, 59, LUA.table_from({"aquifer": True}))           # inside the z59 footprint
    r = start(kind="bedrooms", rooms=8, room_size=3)
    assert r.ok, r.error
    assert r.z == 57, r.z          # z58 lies right under the aquifer (damp), so z57


@test("aquifer next to the stair shaft blocks every level below it")
def _():
    for z in range(60, 66):
        W.set(70, 60, z, LUA.table_from({"shape": "FLOOR"}))
    W.set(61, 61, 57, LUA.table_from({"aquifer": True}))           # beside the shaft at z57
    r = start(kind="bedrooms", rooms=8, room_size=3)
    assert r.ok and r.z in (59, 58), (r.ok, r.z, r.error)
    W.reset()
    for z in range(60, 66):
        W.set(70, 60, z, LUA.table_from({"shape": "FLOOR"}))
    W.set(61, 61, 59, LUA.table_from({"aquifer": True}))           # beside the shaft right below
    r = start(kind="bedrooms", rooms=8, room_size=3)
    assert not r.ok and "aquifer" in r.error, (r.ok, r.error)
    assert designated_count() == 0


@test("water, caverns and the surface in the border are refused too")
def _():
    for hazard in ({"liquid": True}, {"feature": True}, {"outside": True}, {"shape": "FLOOR"}):
        W.reset()
        L = LUA.eval("function(m) return m.make('bedrooms', {rooms=8, room_size=3}) end")(B.__index if False else LUA.globals().LAYOUTS)
        b = L.bounds
        W.set(60 + b.x2 + 1, 60, 65, LUA.table_from(hazard))        # just outside the dug area
        ok = B.check_level(L, 60, 60, 65, LUA.table())
        assert not (ok[0] if isinstance(ok, tuple) else ok), hazard


@test("at most 2 unfinished projects, and they never overlap")
def _():
    a = start(kind="bedrooms", rooms=4, room_size=3)
    b = start(kind="dining", tables=8)
    c = start(kind="storage", piles=["food"])
    assert a.ok and b.ok and a.z != b.z, (a.error, b.error, a.z, b.z)
    assert not c.ok and c.rejected


@test("progress: furnishing only after digging, and only with buildingplan on")
def _():
    r = start(kind="bedrooms", rooms=4, room_size=3)
    rep = B.projects_report()
    p = rep.open[1]
    assert p.phase == "dig" and p.dig.dug == 0 and p.dig.total == r.tiles
    f = B.furnish_project(r.project_id, True)
    assert not f.ok and "not finished" in f.error
    for t in W.tiles.values():                      # dwarves dig everything
        if t.designated:
            t.shape, t.designated = "FLOOR", False
    assert B.projects_report().open[1].dig.dug == r.tiles
    f = B.furnish_project(r.project_id, False)
    assert not f.ok and "buildingplan" in f.error
    # (furnishing itself needs the real game's buildings list; checked in the game)


@test("0.104.110: a stalled level 90%+ dug may be furnished without its last tiles; under 90% never")
def _():
    r = start(kind="bedrooms", rooms=4, room_size=3)
    tiles = [t for t in W.tiles.values() if t.designated]
    left = max(1, len(tiles) // 20)                  # 5% left undug
    for t in tiles[left:]:
        t.shape, t.designated = "FLOOR", False
    f = B.furnish_project(r.project_id, False)
    assert not f.ok and "not finished" in f.error
    f = B.furnish_project(r.project_id, False, True)
    assert not f.ok and "buildingplan" in f.error, f.error          # past the dig check
    for t in tiles[:len(tiles) // 5]:
        t.shape, t.designated = "WALL", True         # 20% left: too much
    f = B.furnish_project(r.project_id, False, True)
    assert not f.ok and "not finished" in f.error


@test("cancel removes only the AI's designations, and only while digging")
def _():
    r = start(kind="bedrooms", rooms=4, room_size=3)
    assert designated_count() > 0
    c = B.cancel_project(r.project_id)
    assert c.ok and designated_count() == 0
    assert not B.cancel_project(r.project_id).ok
    assert not B.cancel_project(999).ok


@test("dry run disagreeing with the plan means nothing is designated")
def _():
    real = LUA.globals().reqscript("quickfort").apply_blueprint
    LUA.globals().reqscript("quickfort").apply_blueprint = LUA.eval(
        "function(real) return function(p) local s = real(p); if p.dry_run then s.dig_invalid_tiles.value = 1 end; return s end end")(real)
    try:
        r = start(kind="bedrooms", rooms=4, room_size=3)
    finally:
        LUA.globals().reqscript("quickfort").apply_blueprint = real
    assert not r.ok and "dry run" in r.error and designated_count() == 0


@test("dry run: says where it would dig, changes nothing, records nothing")
def _():
    r = B.start_project(params(kind="bedrooms", rooms=8, room_size=3), LUA.table(), True)
    assert r.ok and r.dry_run and r.z == 65 and r.tiles > 50
    assert designated_count() == 0 and len(B.projects_report().open) == 0


@test("marker-only designations are reported (dwarves would never dig them)")
def _():
    r = start(kind="bedrooms", rooms=4, room_size=3)
    for t in W.tiles.values():
        if t.designated:
            t.designated, t.marked = False, True
    d = B.projects_report().open[1].dig
    assert d.marked == r.tiles and d.stuck == 0, (d.marked, d.stuck)


@test("main staircase: equal counts go to the longer walkable run")
def _():
    for z in (70, 71):                         # a short 2-level stair at x=45, sampled levels 70-72
        W.set(45, 58, z, LUA.table_from({"shape": "STAIR_UPDOWN" if z == 70 else "STAIR_DOWN"}))
    W.set(45, 58, 72, LUA.table_from({"shape": "STAIR_UPDOWN"}))
    s = B.find_main_stair()
    assert (s.x, s.y) == (60, 60), (s.x, s.y)


@test("a stair run stops where dwarves can't walk on (an up-stair over an up-stair)")
def _():
    W.set(60, 60, 81, LUA.table_from({"shape": "STAIR_UP"}))   # top was STAIR_DOWN at 80: fine
    W.set(60, 60, 80, LUA.table_from({"shape": "STAIR_UP"}))   # now 80 can't go down to 79
    zt, zb = B.stair_run(60, 60, 70)
    assert (zt, zb) == (79, 60), (zt, zb)


@test("if designating fails part-way, everything this call designated is taken back")
def _():
    for z in range(60, 66):
        W.set(70, 60, z, LUA.table_from({"shape": "FLOOR"}))
    qf = LUA.globals().reqscript("quickfort")
    real = qf.apply_blueprint
    qf.apply_blueprint = LUA.eval("""function(real) return function(p)
        local s = real(p)
        for z, g in pairs(p.data) do for y, r in pairs(g) do for x, t in pairs(r) do
          if t == 'u' and not p.dry_run and p.command ~= 'undo' then s.dig_designated.value = 0 end
        end end end
        return s end end""")(real)
    try:
        r = start(kind="bedrooms", rooms=8, room_size=3)     # needs the stairs extended
    finally:
        qf.apply_blueprint = real
    assert not r.ok and "undone" in r.error, (r.ok, r.z, r.error)
    assert designated_count() == 0 and len(B.projects_report().open) == 0


@test("progress and cancel use the cells saved with the project, not a regenerated layout")
def _():
    r = start(kind="bedrooms", rooms=4, room_size=3)
    lay = LUA.globals().LAYOUTS
    real_make = lay.make
    lay.make = LUA.eval("function() return nil, 'layouts changed' end")
    try:
        assert B.projects_report().open[1].dig.total == r.tiles
        assert B.cancel_project(r.project_id).ok and designated_count() == 0
    finally:
        lay.make = real_make


@test("bad requests are refused before touching the map")
def _():
    assert start(kind="lake").rejected          # (0.105.0) a moat is a water_work now, not a level
    assert start(kind="storage", piles=["refuse"]).rejected
    assert designated_count() == 0


# --- sites beside the stairs, and other staircases ----------------------------------

AREA_CHECK = r"""
function(W, z)
  -- every designated tile on level z, and every open (dug) tile next to one
  local D, open = {}, {}
  for k, t in pairs(W.tiles) do
    local x, y, tz = k:match('^(%-?%d+),(%-?%d+),(%-?%d+)$')
    x, y, tz = tonumber(x), tonumber(y), tonumber(tz)
    if tz == z and t.designated then D[#D+1] = {x, y} end
  end
  local isD = {}
  for _, d in ipairs(D) do isD[d[1]..','..d[2]] = true end
  for _, d in ipairs(D) do
    for dx = -1, 1 do for dy = -1, 1 do
      local nx, ny = d[1]+dx, d[2]+dy
      local t = W.get(nx, ny, z)
      if not isD[nx..','..ny] and t.shape ~= 'WALL' then open[nx..','..ny] = {nx, ny} end
      if t.aquifer or t.liquid or t.feature then error('hazard next to a dug tile') end
    end end
  end
  -- all those open tiles must sit around ONE designated tile (where the corridor joins)
  for _, f in ipairs(D) do
    local all = true
    for _, o in pairs(open) do
      if math.max(math.abs(o[1]-f[1]), math.abs(o[2]-f[2])) > 1 then all = false end
    end
    if all then return #D, f[1], f[2] end
  end
  return #D, nil, nil
end"""


@test("busy fort: new level goes beside the stairs on the busiest level, joined by a corridor", beside=True)
def _():
    r = start(kind="bedrooms", rooms=8, room_size=3)
    assert r.ok, r.error
    assert r.z == 72 and r.corridor >= 1 and not r.extends_stairs, (r.z, r.corridor)
    n, fx, fy = LUA.eval(AREA_CHECK)(W, 72)
    assert n == r.tiles and fx is not None, "the new level touches existing rooms in more than one place"


@test("beside: the new level is walkable from the stairs", beside=True)
def _():
    r = start(kind="dining", tables=12)
    assert r.ok, r.error
    reach = LUA.eval(r"""function(W, z)
      local seen, todo, n = {}, {{60, 60}}, 0
      while #todo > 0 do
        local p = table.remove(todo)
        local k = p[1]..','..p[2]
        local t = W.get(p[1], p[2], z)
        if not seen[k] and t and (t.shape ~= 'WALL' or t.designated) then
          seen[k] = true
          if t.designated then n = n + 1 end
          for _, d in ipairs({{1,0},{-1,0},{0,1},{0,-1}}) do todo[#todo+1] = {p[1]+d[1], p[2]+d[2]} end
        end
      end
      return n end""")(W, r.z)
    assert reach == r.tiles, (reach, r.tiles)


@test("beside: water near the fort pushes the level elsewhere, never next to it", beside=True)
def _():
    LUA.execute("""local W = ...
      for x = 30, 90 do for y = 30, 54 do W.set(x, y, 72, {liquid = true}) end end""", W)
    r = start(kind="bedrooms", rooms=8, room_size=3)
    assert r.ok, r.error
    LUA.eval(AREA_CHECK)(W, r.z)            # raises if a hazard is next to a dug tile


@test("another staircase is used when the main one has no safe spot", beside=True)
def _():
    LUA.execute("""local W = ...
      -- a second, less used staircase far away, with a small dug room on its levels
      for z = 70, 74 do W.set(15, 100, z, {shape = (z == 70) and 'STAIR_UP' or ((z == 74) and 'STAIR_DOWN' or 'STAIR_UPDOWN')}) end
      for i = 1, 3 do table.insert(W.citizens, {x = 15, y = 100, z = 70 + i}) end
      -- everything near the main staircase is aquifer
      for x = 20, 100 do for y = 20, 100 do for z = 44, 85 do
        if not (x < 40 and y > 90) then
          local t = W.get(x, y, z); if t.shape == 'WALL' then t.aquifer = true end
        end
      end end end""", W)
    stairs = B.find_stairs(5)
    assert stairs[1].x == 60 and stairs[2].x == 15, [(s.x, s.y) for s in stairs.values()]
    r = start(kind="bedrooms", rooms=4, room_size=2)
    assert r.ok, r.error
    assert abs(r.anchor.x - 15) < 30 and abs(r.anchor.y - 100) < 30, (r.anchor.x, r.anchor.y)


@test("the search stops at its time limit, designates nothing, and says so", beside=True)
def _():
    B.SEARCH_SECONDS = 0
    try:
        r = start(kind="bedrooms", rooms=8, room_size=3)
    finally:
        B.SEARCH_SECONDS = 4
    assert not r.ok and "time limit" in r.error, r.error
    assert designated_count() == 0


# --- culture: styles, entry doors, decoration, temples, memorials -----------------------

def styled(**kw):
    style = kw.pop("style", {})
    t = params(**kw)
    t["style"] = LUA.table_from(style)
    return B.start_project(t, LUA.table_from({"year": 148, "tick": 100}))


def finish_digging():
    for t in W.tiles.values():
        if t.designated:
            t.shape, t.designated = "FLOOR", False


@test("fortified fort: a door where the new level's corridor leaves the fort", beside=True)
def _():
    r = styled(kind="bedrooms", rooms=4, room_size=3, style={"entry_door": True})
    assert r.ok and r.corridor > 0, r.error
    plain = B.start_project(params(kind="bedrooms", rooms=4, room_size=3), LUA.table(), True)
    W.reset(); B.TRY_BESIDE = True
    dry = B.start_project(LUA.eval("function(t) t.style = {entry_door = true}; return t end")(
        params(kind="bedrooms", rooms=4, room_size=3)), LUA.table(), True)
    assert dry.furniture.Door == plain.furniture.Door + 1, (dry.furniture.Door, plain.furniture.Door)


@test("decoration never touches the player's existing rooms", beside=True)
def _():
    r = styled(kind="dining", tables=12, style={"smooth": 3, "hall": "pillared"})
    assert r.ok, r.error
    finish_digging()
    B.furnish_project(r.project_id, True)
    # the fake fort's existing rooms (x 40-80, y 55-65) must get no smoothing jobs
    W2 = LUA.eval("""function(W, z)
      local bad = 0
      for x = 40, 80 do for y = 55, 65 do
        local t = W.get(x, y, z)
        if t.smoothing then bad = bad + 1 end
      end end
      return bad end""")(W, r.z)
    assert W2 == 0, f"{W2} smoothing jobs on the existing fort"


@test("phases: dig -> furnish (+ smoothing) -> decorate (slot freed) -> engrave -> done", beside=True)
def _():
    B.furnish_progress = LUA.eval("function() return {placed = 3, done = 3, waiting = {}} end")
    r = styled(kind="dining", tables=8, style={"smooth": 3})
    assert r.ok, r.error
    finish_digging()
    assert B.projects_report().open[1].next == "furnish"
    f = B.furnish_project(r.project_id, True)
    assert f.ok and f.placed.smooth > 0, dict(f.placed)
    rep = B.projects_report()
    assert rep.open[1].next == "finish"
    assert B.finish_project(r.project_id).phase == "decorate"
    rep = B.projects_report()
    assert len(rep.open) == 0 and not rep.decorating[1].next          # still smoothing
    assert not B.engrave_project(r.project_id).ok
    for t in W.tiles.values():                                          # dwarves smooth everything
        if t.smoothing:
            t.smoothing, t.smoothed = False, True
    assert B.projects_report().decorating[1].next == "engrave"
    e = B.engrave_project(r.project_id)
    assert e.ok and e.engraved > 0
    assert B.projects_report().finished == 1


@test("plain style: nothing to engrave, so finishing goes straight to done", beside=True)
def _():
    B.furnish_progress = LUA.eval("function() return {placed = 0, done = 0, waiting = {}} end")
    r = styled(kind="storage", piles=["food"], style={"smooth": 0})
    finish_digging()
    B.furnish_project(r.project_id, True)
    assert B.finish_project(r.project_id).phase == "done"


@test("finish (0.104.12): decor_only finishes a level whose only waiting buildings are statues; never other furniture", beside=True)
def _():
    B.furnish_progress = LUA.eval("function() return {placed = 6, done = 4, waiting = {Statue = 2}} end")
    r = styled(kind="storage", piles=["food"], style={"smooth": 0})
    finish_digging()
    B.furnish_project(r.project_id, True)
    assert not B.finish_project(r.project_id).ok                              # statues wait: not without decor_only
    assert B.finish_project(r.project_id, True).phase == "done"
    B.furnish_progress = LUA.eval("function() return {placed = 6, done = 4, waiting = {Statue = 1, Bed = 1}} end")
    r2 = styled(kind="storage", piles=["food"], style={"smooth": 0})
    finish_digging()
    B.furnish_project(r2.project_id, True)
    assert not B.finish_project(r2.project_id, True).ok                       # a bed waits too


@test("finish (0.104.141): stalled finishes a level with everything placed and nothing missing; never one still waiting", beside=True)
def _():
    B.furnish_progress = LUA.eval("function() return {placed = 31, done = 30, waiting = {}} end")
    r = styled(kind="storage", piles=["food"], style={"smooth": 0})
    finish_digging()
    B.furnish_project(r.project_id, True)
    assert not B.finish_project(r.project_id).ok                              # a building unfinished
    assert B.finish_project(r.project_id, False, True).phase == "done"
    B.furnish_progress = LUA.eval("function() return {placed = 31, done = 29, waiting = {Bed = 1}} end")
    r2 = styled(kind="storage", piles=["food"], style={"smooth": 0})
    finish_digging()
    B.furnish_project(r2.project_id, True)
    assert not B.finish_project(r2.project_id, False, True).ok                # a bed still missing


@test("slots (0.104.142): a level furnishing 14+ days lends its slot, three at most; the report's max_open says so", beside=True)
def _():
    now = B.now_tick()
    def proj(phase, days_ago):
        t_ = now - days_ago * 1200
        return LUA.table_from({"phase": phase, "furnish_started": LUA.table_from({"year": t_ // 403200, "tick": t_ % 403200})})
    base = B.MAX_OPEN_PROJECTS
    assert B.slot_cap(LUA.table_from({})) == base
    assert B.slot_cap(LUA.table_from([proj("furnish", 20), proj("furnish", 3), proj("dig", 40)])) == base + 1
    assert B.slot_cap(LUA.table_from([proj("furnish", 20), proj("furnish", 30), proj("furnish", 50)])) == base + 3
    assert B.slot_cap(LUA.table_from([proj("furnish", d) for d in (20, 30, 50, 60)])) == base + 3


@test("bounds_of: the box of the dig cells (or build cells) in map coordinates; nil without cells")
def _():
    p = LUA.eval("""function() return {z = 70, anchor = {x = 50, y = 40},
        cells = {dig = {{x = -2, y = 3, text = 'd'}, {x = 4, y = -1, text = 'd'}, {x = 0, y = 0, text = 'd'}},
                 build = {{x = 9, y = 9, text = 'b'}}}} end""")()
    b = B.bounds_of(p)
    assert (b.x1, b.y1, b.x2, b.y2, b.z) == (48, 39, 54, 43, 70), (b.x1, b.y1, b.x2, b.y2, b.z)
    p = LUA.eval("""function() return {z = 5, stair = {x = 10, y = 10},
        cells = {dig = {}, build = {{x = 1, y = 2, text = 'b'}}}} end""")()   # older record: stair anchor
    b = B.bounds_of(p)
    assert (b.x1, b.y1, b.x2, b.y2, b.z) == (11, 12, 11, 12, 5)
    assert B.bounds_of(LUA.eval("function() return {z = 5, anchor = {x = 1, y = 1}, cells = {dig = {}}} end")()) is None
    assert B.bounds_of(LUA.eval("function() return {z = 5, anchor = {x = 1, y = 1}} end")()) is None


@test("registry: every AI project on record, any phase, with where it is and what it's called", beside=True)
def _():
    B.furnish_progress = LUA.eval("function() return {placed = 0, done = 0, waiting = {}} end")
    a = styled(kind="storage", piles=["food"], style={"smooth": 0}, name="Larder")
    assert a.ok, a.error
    finish_digging()
    B.furnish_project(a.project_id, True)
    assert B.finish_project(a.project_id).phase == "done"
    c = start(kind="bedrooms", rooms=4, room_size=3)
    assert c.ok, c.error
    assert B.cancel_project(c.project_id).ok
    d = start(kind="bedrooms", rooms=4, room_size=3)
    assert d.ok, d.error
    reg = list(B.registry_report().values())
    assert [(e.id, e.phase) for e in reg] == [(a.project_id, "done"), (c.project_id, "cancelled"),
                                              (d.project_id, "dig")], [(e.id, e.phase) for e in reg]
    e = reg[0]
    assert e.kind == "storage" and e.name == "Larder" and e.style.smooth == 0 and e.z == a.z
    assert e.elevation == a.elevation and e.started.year == 148
    b = e.bounds
    assert b.z == a.z and b.x1 <= a.anchor.x <= b.x2 and b.y1 <= a.anchor.y <= b.y2 and b.x1 < b.x2
    assert reg[2].name is None and reg[2].bounds is not None


@test("registry: capped at the newest 400")
def _():
    W.persist["ai-overseer/projects"] = LUA.eval("""function()
        local l = {}
        for i = 1, 450 do l[i] = {id = i, kind = 'storage', phase = 'done', z = 70, anchor = {x = 0, y = 0},
                                  cells = {dig = {{x = 1, y = 1, text = 'd'}}}} end
        return {next_id = 451, list = l} end""")()
    reg = B.registry_report()
    assert len(reg) == 400 and reg[1].id == 51 and reg[400].id == 450


@test("temple and memorial levels can be started", beside=True)
def _():
    t = styled(kind="temple", size="grand", style={"statues": 2})
    m = styled(kind="memorial", name="Shulmik the Jackalowls")
    assert t.ok and m.ok, (t.error, m.error)
    assert t.summary.temple == "grand" and m.summary.memorial == "Shulmik the Jackalowls"



@test("review 4c: decoration can't wait forever (marker mode, or 60 days)", beside=True)
def _():
    B.furnish_progress = LUA.eval("function() return {placed = 0, done = 0, waiting = {}} end")
    r = styled(kind="dining", tables=8, style={"smooth": 3})
    finish_digging()
    B.furnish_project(r.project_id, True)
    B.now_tick = LUA.eval("function() return 1000 end")
    B.finish_project(r.project_id)
    assert not B.projects_report().decorating[1].next
    for t in W.tiles.values():                    # marker mode: designated but never dug
        if t.smoothing:
            t.marked = True
    d = B.projects_report().decorating[1]
    assert d.next == "engrave" and d.decor.smooth_marked > 0
    for t in W.tiles.values():
        t.marked = False
    assert not B.projects_report().decorating[1].next
    B.now_tick = LUA.eval("function() return 1000 + 60 * 1200 end")
    assert B.projects_report().decorating[1].next == "engrave"
    assert B.engrave_project(r.project_id).ok


@test("review 4c: smoothing skips rock the player dug or designated after the level was started", beside=True)
def _():
    B.furnish_progress = LUA.eval("function() return {placed = 0, done = 0, waiting = {}} end")
    r = styled(kind="dining", tables=8, style={"smooth": 2})
    finish_digging()
    # the player digs out every rock tile around the new level before it is furnished
    LUA.execute("""local W, z = ...
      for k, t in pairs(W.tiles) do
        local x, y, tz = k:match('^(%-?%d+),(%-?%d+),(%-?%d+)$')
        if tonumber(tz) == z and t.shape == 'WALL' then t.shape = 'FLOOR'; t.player = true end
      end""", W, r.z)
    B.furnish_project(r.project_id, True)
    bad = LUA.eval("""function(W) local n = 0
      for _, t in pairs(W.tiles) do if t.player and t.smoothing then n = n + 1 end end
      return n end""")(W)
    assert bad == 0, f"{bad} of the player's new tiles got smoothing jobs"



# --- found in the game: damp and warm stone ------------------------------------------

@test("game: water or aquifer directly above a tile to dig rejects that level (DF calls it damp)")
def _():
    L = LUA.globals().LAYOUTS.make("bedrooms", LUA.table_from({"rooms": 8, "room_size": 3}))
    assert B.check_level(L, 60, 60, 65, LUA.table())[0]
    for hazard in ({"aquifer": True}, {"liquid": True}):
        W.reset()
        W.set(64, 57, 66, LUA.table_from(hazard))            # above a room tile on z65
        res = B.check_level(L, 60, 60, 65, LUA.table())
        assert not res[0] and "directly above" in res[1], res


@test("game: warm stone (magma nearby) is never dug")
def _():
    L = LUA.globals().LAYOUTS.make("bedrooms", LUA.table_from({"rooms": 8, "room_size": 3}))
    W.set(64, 57, 65, LUA.table_from({"warm": True}))
    res = B.check_level(L, 60, 60, 65, LUA.table())
    assert not res[0] and "warm" in res[1], res


@test("game: a few cancelled tiles -> furnish what's dug; too many -> give up on the spot")
def _():
    r = start(kind="bedrooms", rooms=8, room_size=3)
    assert r.ok, r.error
    dug_some = LUA.eval("""function(W, n_cancel)
      local n = 0
      for _, t in pairs(W.tiles) do
        if t.designated then
          t.designated = false
          if n < n_cancel then n = n + 1 else t.shape = 'FLOOR' end
        end
      end end""")
    dug_some(W, r.tiles // 10)                                  # 10% cancelled
    p = B.projects_report().open[1]
    assert p.next == "furnish" and p.dig.stuck == r.tiles // 10, (p.next, p.dig.stuck)
    assert B.furnish_project(r.project_id, True).ok
    W.reset()
    r = start(kind="bedrooms", rooms=8, room_size=3)
    dug_some(W, r.tiles // 3)                                   # a third cancelled
    assert B.projects_report().open[1].next == "cancel"
    assert not B.furnish_project(r.project_id, True).ok


@test("game: tiles being dug right now (designation taken off by DF) are not 'cancelled'")
def _():
    W.reset()
    r = start(kind="bedrooms", rooms=8, room_size=3)
    assert r.ok, r.error
    in_job = LUA.eval("""function(W)
      local n = 0
      for k, t in pairs(W.tiles) do
        if t.designated then
          t.designated = false
          n = n + 1
          if n % 2 == 0 then t.shape = 'FLOOR' else W.jobs[k] = true end
        end
      end
      return n end""")
    n = in_job(W)
    p = B.projects_report().open[1]
    assert p.dig.stuck == 0 and p.dig.digging == (n + 1) // 2, (p.dig.stuck, p.dig.digging, n)
    assert p.next is False, p.next                    # not furnish, not cancel: still digging
    assert not B.furnish_project(r.project_id, True).ok


@test("tombs, tavern and library levels start like any other (dug, then furnished with zones)")
def _():
    for kind, kw in (("tombs", {"coffins": 6}), ("tavern", {"tables": 6}), ("library", {"bookcases": 6})):
        W.reset()
        r = start(kind=kind, **kw)
        assert r.ok, (kind, r.error)
        LUA.eval("""function(W) for _, t in pairs(W.tiles) do
            if t.designated then t.designated = false; t.shape = 'FLOOR' end end end""")(W)
        assert B.projects_report().open[1].next == "furnish", kind
        f = B.furnish_project(r.project_id, True)
        assert f.ok, (kind, f.error)
        zones = [c for c in W.placed.values() if c.mode == "zone"]
        assert zones, kind
        if kind == "tombs":
            assert len(zones) == 6 and all(z.text == "T{citizens=true}" for z in zones), [z.text for z in zones]


# --- farm plots ------------------------------------------------------------------

def farm(tiles, dig=False, dry=False):
    return B.farm_plots(params(tiles=tiles, dig=dig), LUA.table_from({"year": 148, "tick": 100}), dry)


def plots_placed():
    return [c for c in W.placed.values() if c.mode == "build" and str(c.text).startswith("p(")]


def soil_floor(x1, y1, x2, y2, z, **extra):
    for x in range(x1, x2 + 1):
        for y in range(y1, y2 + 1):
            W.set(x, y, z, LUA.table_from({"shape": "FLOOR", "material": "SOIL", **extra}))


def plot_tiles(cells):
    import re
    n = 0
    for c in cells:
        w, h = map(int, re.match(r"p\((\d+)x(\d+)\)", c.text).groups())
        n += w * h
    return n


@test("farms: plots go on soil floor the fort already has, near the dwarves, no digging")
def _():
    soil_floor(42, 56, 47, 59, 71)                     # a 6x4 soil-floored room on a busy level
    r = farm(20)
    assert r.ok and r.tiles >= 20 and not r.level, (r.ok, r.tiles, r.error)
    cells = plots_placed()
    assert cells and all(c.z == 71 and 42 <= c.x <= 47 and 56 <= c.y <= 59 for c in cells), \
        [(c.x, c.y, c.z, c.text) for c in cells]
    assert plot_tiles(cells) == r.tiles and designated_count() == 0


@test("farms: muddy stone counts as soil; a 1-wide soil corridor doesn't (no plot under 2x2)")
def _():
    for x in range(42, 52):
        W.set(x, 56, 71, LUA.table_from({"material": "SOIL"}))           # 1-wide strip
    r = farm(9)
    assert not r.ok and "no free soil" in r.error and not plots_placed(), (r.ok, r.error)
    for x in range(44, 47):
        for y in range(58, 61):
            W.set(x, y, 71, LUA.table_from({"mud": True}))               # muddied stone 3x3
    r = farm(9)
    assert r.ok and r.tiles == 9, (r.ok, r.tiles, r.error)


@test("farms (0.99.7): outdoors, the surface is searched even with no dwarf on it (region2: \"no free soil\")")
def _():
    W.reset()                                            # the dwarves are on z 70-72 only
    for x in range(30, 91):                              # the surface at z 80, open sky above it
        for y in range(40, 55):
            for z in range(81, 100):
                W.set(x, y, z, LUA.table_from({"shape": "EMPTY", "outside": True}))
            W.set(x, y, 80, LUA.table_from({"shape": "FLOOR", "material": "SOIL", "outside": True}))
    r = B.farm_plots(params(tiles=20, dig=False, outside=True), LUA.table_from({"year": 148, "tick": 100}), True)
    assert r.ok and r.tiles >= 20, (r.ok, r.error, r.tiles)
    r2 = B.farm_plots(params(tiles=20, dig=False), LUA.table_from({"year": 148, "tick": 100}), True)
    assert not r2.ok or r2.tiles == 0, "indoors only: the surface isn't used"


@test("farms (13c): dead grass under the sky takes farm plots (the pastures' list no longer overwrites the farms')")
def _():
    W.reset()
    for x in range(30, 91):
        for y in range(40, 55):
            for z in range(81, 100):
                W.set(x, y, z, LUA.table_from({"shape": "EMPTY", "outside": True}))
            W.set(x, y, 80, LUA.table_from({"shape": "FLOOR", "material": "GRASS_DEAD", "outside": True}))
    r = B.farm_plots(params(tiles=20, dig=False, outside=True), LUA.table_from({"year": 148, "tick": 100}), True)
    assert r.ok and r.tiles >= 20, (r.ok, r.error, r.tiles)
    assert not B.PASTURE_GRASS["GRASS_DEAD"], "pastures want living grass"


@test("farms: never on a zone or building, outside, in a cavern, on water, or out of the dwarves' reach")
def _():
    for i, bad in enumerate(({"taken": True}, {"outside": True}, {"feature": True}, {"liquid": True})):
        W.reset()
        soil_floor(42, 56, 45, 59, 71, **bad)
        r = farm(9)
        assert not r.ok and not plots_placed(), (bad, r.tiles)
    W.reset()
    soil_floor(42, 56, 45, 59, 85)                      # soil floor, but not walkable from the fort
    LUA.globals().table.insert(W.citizens, LUA.table_from({"x": 43, "y": 57, "z": 85}))
    r = farm(9)
    assert not r.ok and not plots_placed(), r.tiles


@test("farms: no soil floor -> a farm level dug in a soil layer, plots only on soil")
def _():
    W.soil_levels[63] = True
    r = farm(30, dig=True)
    assert r.ok and r.tiles == 0 and r.level and r.level.ok, (r.ok, r.error, r.level and r.level.error)
    assert r.level.kind == "farms" and r.level.z == 63, (r.level.kind, r.level.z)
    rep = B.projects_report().open[1]
    assert rep.kind == "farms" and rep.summary.farm_tiles >= 30, rep.summary.farm_tiles
    LUA.eval("""function(W) for _, t in pairs(W.tiles) do
        if t.designated then t.designated = false; t.shape = 'FLOOR' end end end""")(W)
    assert B.furnish_project(r.level.project_id, True).ok
    assert len(plots_placed()) == rep.summary.farm_plots


@test("farms: stone where a plot would go rejects the farm level there")
def _():
    W.soil_levels[63] = True
    L = LUA.globals().LAYOUTS.make("farms", LUA.table_from({"plots": 2}))
    assert B.check_level(L, 60, 60, 63, LUA.table())[0]
    W.set(63, 58, 63, LUA.table_from({"material": "STONE"}))               # under a plot
    res = B.check_level(L, 60, 60, 63, LUA.table())
    assert not res[0] and "not soil" in res[1], res
    W.reset()
    W.soil_levels[63] = True
    W.set(61, 60, 63, LUA.table_from({"material": "STONE"}))               # hub: fine
    assert B.check_level(L, 60, 60, 63, LUA.table())[0]


@test("farms: no soil anywhere -> refused with the reason; without dig, no level is tried")
def _():
    r = farm(30, dig=True)
    assert not r.ok and "no free soil" in r.error and "no soil on any level the staircases reach" in r.error, \
        r.error
    assert designated_count() == 0 and len(B.projects_report().open) == 0
    W.soil_levels[63] = True
    r = farm(30, dig=False)
    assert not r.ok and not r.level and designated_count() == 0, r.error


@test("farms: some soil floor, the rest as a level; a dry run changes nothing")
def _():
    W.soil_levels[63] = True
    soil_floor(42, 56, 44, 58, 71)                      # 9 tiles
    r = farm(40, dig=True, dry=True)
    assert r.ok and r.tiles == 9 and r.level.ok and r.level.dry_run, (r.tiles, r.error)
    assert not plots_placed() and designated_count() == 0 and len(B.projects_report().open) == 0
    r = farm(40, dig=True)
    assert r.ok and r.tiles == 9 and r.level.ok and len(plots_placed()) == 1


@test("farms: soil exists but every spot is unsafe -> says where the soil is and why it can't be used")
def _():
    W.soil_levels[63] = True
    for x in range(30, 95):
        for y in range(30, 95):
            W.set(x, y, 64, LUA.table_from({"aquifer": True}))       # an aquifer right above the soil
    r = farm(30, dig=True)
    assert not r.ok and "there is soil at elevation 63" in r.error and "aquifer" in r.error, r.error
    assert designated_count() == 0


# --- Spacing trait ----------------------------------------------------------------

@test("spacing: corridor length range follows the trait (tight 0-8, middle 0-25, spread 10-25)")
def _():
    L = LUA.globals().LAYOUTS.make("bedrooms", LUA.table_from({"rooms": 4}))
    for sp, want in ((-100, (0, 8)), (-50, (0, 16)), (0, (0, 25)), (50, (5, 25)), (100, (10, 25)), (200, (10, 25)),
                     (-200, (0, 8))):
        L.style.spacing = sp
        got = B.corridor_range(L)
        assert tuple(got) == want, (sp, got)


@test("spacing: a spread-out fort puts the new level further from the fort; middle is unchanged", beside=True)
def _():
    base = styled(kind="bedrooms", rooms=8, room_size=3)
    W.reset()
    spread = styled(kind="bedrooms", rooms=8, room_size=3, style={"spacing": 100})
    W.reset()
    tight = styled(kind="bedrooms", rooms=8, room_size=3, style={"spacing": -100})
    assert base.ok and spread.ok and tight.ok, (base.error, spread.error, tight.error)
    assert spread.corridor >= base.corridor + 5, (base.corridor, spread.corridor)
    assert tight.corridor <= base.corridor, (base.corridor, tight.corridor)
    n, fx, fy = LUA.eval(AREA_CHECK)(W, tight.z)
    assert fx is not None, "a tight level still joins the fort in one place"


# --- wells ------------------------------------------------------------------------

def well(dry=False):
    return B.place_well(LUA.table(), LUA.table_from({"year": 148, "tick": 100}), dry)


def water_column(x, y, top, open_levels=1, depth=7, **extra):
    """A floor at `top` with open space under it, then water."""
    for k in range(1, open_levels + 1):
        W.set(x, y, top - k, LUA.table_from({"shape": "EMPTY"}))
    W.set(x, y, top - open_levels - 1, LUA.table_from({"shape": "EMPTY", "liquid": True, "depth": depth,
                                                       **extra}))


@test("wells: a free floor over an open drop to water -> channelled now, the well placed when dug")
def _():
    water_column(70, 58, 71, open_levels=2)
    r = well()
    assert r.ok and (r.x, r.y, r.elevation, r.drop) == (70, 58, 71, 3), (r.ok, r.error, r.x, r.y, r.drop)
    assert W.get(70, 58, 71).designated and designated_count() == 1
    p = B.projects_report().open[1]
    assert p.kind == "well" and p.phase == "dig" and p.dig.total == 1 and p.dig.dug == 0, (p.kind, p.dig.dug)
    LUA.eval("function(W) local t = W.get(70, 58, 71); t.designated = false; t.shape = 'EMPTY' end")(W)
    assert B.projects_report().open[1].next == "furnish"
    f = B.furnish_project(r.project_id, True)
    assert f.ok, f.error
    built = [c for c in W.placed.values() if c.mode == "build"]
    assert [(c.x, c.y, c.z, c.text) for c in built] == [(70, 58, 71, "l")], [(c.x, c.y, c.text) for c in built]


@test("wells: a dry run says where, changes nothing; a second well waits while two projects are open")
def _():
    water_column(70, 58, 71)
    r = well(dry=True)
    assert r.ok and r.dry_run and r.x == 70 and designated_count() == 0
    assert len(B.projects_report().open) == 0
    start(kind="bedrooms", rooms=4, room_size=3)
    start(kind="dining", tables=8)
    r = well()
    assert not r.ok and r.rejected and "unfinished" in r.error, r.error


@test("wells: never into a cavern, over magma, stagnant or salt water, or a full tile right under the floor")
def _():
    for extra, word in (({"feature": True}, "cavern"), ({"magma": True}, "magma"),
                        ({"stagnant": True}, "stagnant"), ({"salt": True}, "salt")):
        W.reset()
        water_column(70, 58, 71, **extra)
        r = well()
        assert not r.ok and word in r.error and designated_count() == 0, (extra, r.error)
    W.reset()
    W.set(70, 58, 70, LUA.table_from({"shape": "FLOOR", "liquid": True, "depth": 7}))   # a full cistern
    r = well()
    assert not r.ok and "pressure" in r.error, r.error
    W.reset()
    W.set(70, 58, 70, LUA.table_from({"shape": "FLOOR", "liquid": True, "depth": 4}))   # half full: fine
    r = well()
    assert r.ok and r.drop == 1, (r.ok, r.error)


@test("wells: shallow water counts only over a full tile; too shallow is refused")
def _():
    water_column(70, 58, 71, depth=1)
    W.set(70, 58, 68, LUA.table_from({"shape": "EMPTY", "liquid": True, "depth": 7}))
    r = well()
    assert r.ok and r.drop == 3, (r.ok, r.error)
    W.reset()
    water_column(70, 58, 71, depth=2)
    r = well()
    assert not r.ok and "too shallow" in r.error, r.error


def release_hold(pid):
    """(0.105.4 review) a cavern well from before the hold (its last level dug with the rest)."""
    LUA.execute("""local B, pid = ...
      local d = B.load_projects()
      for _, p in ipairs(d.list) do if p.id == pid then p.held = nil end end
      B.save_projects(d)""", B, pid)


def cavern_column(x=70, y=58, top=70, lake_depth=5, **lake):
    """A floor at `top` with solid rock under it (the fort's dug levels walled
    back round the column, wide enough for the stairs beside the shaft),
    then a cavern's air, then its lake."""
    for z in range(66, top):
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                W.set(x + dx, y + dy, z, LUA.table_from({"shape": "WALL", "material": "STONE"}))
    W.set(x, y, 62, LUA.table_from({"shape": "EMPTY", "feature": True}))
    W.set(x, y, 61, LUA.table_from({"shape": "EMPTY", "feature": True, "liquid": True, "depth": lake_depth, **lake}))


def dig_shaft_stairs(x=71, y=58, top=70, bottom=63):
    LUA.eval("""function(W, x, y, top, bottom)
        for z = bottom, top do
            local t = W.get(x, y, z); t.designated = false
            t.shape = (z == top) and 'STAIR_DOWN' or ((z == bottom) and 'STAIR_UP' or 'STAIR_UPDOWN')
        end
    end""")(W, x, y, top, bottom)


def open_shaft(x=70, y=58, top=70, bottom=63):
    LUA.eval("""function(W, x, y, top, bottom)
        local t = W.get(x, y, top); t.designated = false; t.shape = 'EMPTY'
        for z = bottom, top - 1 do local s = W.get(x, y, z); s.designated = false; s.shape = 'EMPTY' end
    end""")(W, x, y, top, bottom)


@test("cavern well: a shaft channelled through solid rock to the cavern lake, the well when it's all open")
def _():
    cavern_column()
    assert not well().ok                                         # an ordinary well: no
    r = B.place_well(LUA.table_from({"cavern": True}), LUA.table_from({"year": 148, "tick": 100}), False)
    assert r.ok and r.cavern and r.shaft == 7 and r.drop == 9 and (r.x, r.y) == (70, 58), (r.ok, r.error)
    # (0.104.13) the floor and 7 levels of rock, and the 8 stairs beside them;
    # (0.105.4 review) the last level and its stair step held undug (2 of them)
    assert r.stairs == 8 and r.held == 2 and designated_count() == 14, (r.stairs, designated_count())
    p = B.projects_report().open[1]
    assert p.dig.total == 16 and p.dig.dug == 0 and p.dig.shaft_open is False and p.dig.held == 2, (p.dig.total, p.dig.dug)
    release_hold(r.project_id)
    open_shaft()
    assert B.projects_report().open[1].next is False             # the stairs aren't dug yet
    dig_shaft_stairs()
    assert B.projects_report().open[1].next == "furnish"


@test("cavern well (0.104.13): stairs beside the shaft, down to up, every level reachable for its channel")
def _():
    cavern_column()
    r = B.place_well(LUA.table_from({"cavern": True}), LUA.table_from({"year": 148, "tick": 100}), False)
    assert r.ok, r.error
    keys = {z: W.get(71, 58, z).dig_text for z in range(63, 71)}
    # (0.105.4 review) the bottom step (beside the shaft's last level) held undug
    assert keys[70] == "j" and keys[63] is None and all(keys[z] == "i" for z in range(64, 70)), keys
    assert W.get(70, 58, 63).dig_text is None and all(W.get(70, 58, z).dig_text == "h" for z in range(64, 71))
    assert not W.get(71, 58, 62).designated                      # nothing dug into the cavern's air


@test("cavern well (0.104.13): no room for the stairs (open space beside them) -> not here")
def _():
    cavern_column()
    for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2)):           # beside each possible stair column
        W.set(70 + dx, 58 + dy, 65, LUA.table_from({"shape": "EMPTY"}))
    res = B.find_cavern_well_spot(LUA.table_from([]))
    assert res[0] is None and "stairs" in res[1], res[1]


def lake_beside(x1=93, x2=100, y1=56, y2=64, depth=5):
    """(0.105.3) Hammerstirred: a cavern lake east of the fort, under no fort
    floor (the fort's levels end at x80): air at z62 over water at z61."""
    LUA.execute("""local W, x1, x2, y1, y2, depth = ...
      for x = x1, x2 do for y = y1, y2 do
        W.set(x, y, 62, {shape = 'EMPTY', feature = true})
        W.set(x, y, 61, {shape = 'EMPTY', feature = true, liquid = true, depth = depth})
      end end""", W, x1, x2, y1, y2, depth)


def gallery_well(dry=False, **kw):
    a = LUA.eval("""function(g, urgent) return {cavern = true, gallery = g, urgent = urgent,
        toward = {{x = 96, y = 60, z = 61}}} end""")(kw.get("gallery", 40), kw.get("urgent", False))
    return B.place_well(a, LUA.table_from({"year": 148, "tick": 100}), dry)


@test("cavern well (0.105.3): the lake beside the fort, under no floor: a gallery through rock out to it, then the shaft")
def _():
    lake_beside()
    old = B.find_cavern_well_spot(LUA.table_from([]))
    assert old[0] is None, "no fort floor is over the lake"
    r = gallery_well(dry=True)
    assert r.ok and r.cavern and r.gallery and r.gallery > 0, (r.ok, r.error)
    assert r.elevation == 70 and 92 <= r.x <= 100 and r.shaft == 7, (r.x, r.elevation, r.shaft)
    assert designated_count() == 0                                     # a dry run digs nothing
    r = gallery_well()
    assert r.ok and r.project_id, r.error
    p = B.projects_report().open[1]
    # the gallery (dug to floor), the shaft's 8 tiles and the 8 stairs beside it
    assert p.dig.total == r.gallery + 16, (p.dig.total, r.gallery)
    # every gallery tile is plain digging on the fort's level, all through rock
    dug = [(k, t) for k, t in W.tiles.items() if t.designated and t.dig_text == "d"]
    assert len(dug) == r.gallery and all(k.endswith(",70") for k, _ in dug), dug[:3]
    # the gallery starts beside a fort floor and nothing is dug into the cavern
    assert not any(t.designated for k, t in W.tiles.items() if k.endswith(",62") or k.endswith(",61"))


@test("cavern well (0.105.3): no gallery when it would be too long, cross an aquifer or water, or is switched off")
def _():
    lake_beside()
    r = gallery_well(dry=True, gallery=5)
    assert not r.ok and "gallery reaches 5" in r.error and "tiles from the dwarves" in r.error, r.error
    r = gallery_well(dry=True, gallery=0)
    assert not r.ok and "gallery" not in r.error, r.error              # off: the old refusal only
    # an aquifer band across the way (x84-86, every y): the gallery can't pass it
    LUA.execute("""local W = ...
      for z = 66, 80 do for x = 84, 86 do for y = 30, 90 do W.set(x, y, z, {aquifer = true}) end end end""", W)
    r = gallery_well(dry=True)
    assert not r.ok and "no way of at most 40 tiles" in r.error, r.error
    W.reset()
    B.CAVERN_NO_SPOT = None
    lake_beside()
    # water in the rock above the way (a cap with water): not dug under it
    LUA.execute("""local W = ...
      for z = 67, 81 do for x = 84, 86 do for y = 30, 90 do
        W.set(x, y, z, {shape = 'EMPTY', liquid = true, depth = 7}) end end end""", W)
    r = gallery_well(dry=True)
    assert not r.ok and "no way" in r.error, r.error
    W.reset()
    B.CAVERN_NO_SPOT = None
    lake_beside(depth=7)
    LUA.execute("""local W = ...
      for x = 93, 100 do for y = 56, 64 do W.set(x, y, 62, {shape = 'EMPTY', feature = true, liquid = true, depth = 7}) end end""", W)
    r = gallery_well(dry=True)
    assert not r.ok and "pressure" in r.error, r.error                 # the lake fills up to the rock


@test("wells on the shore (0.105.3): a pond past 40 tiles from the gate, within the brain's reach, by the survey")
def _():
    saved = LUA.execute("""local B = ...
      return {pa = B.pasture_anchors, wg = B.walk_group, req = reqscript}""", B)
    LUA.execute("""local B, W = ...
      -- the gate at (60, 40, 80); the pond 50 tiles east, on the surface
      B.pasture_anchors = function() return {{x = 60, y = 40, z = 80}} end
      for x = 100, 118 do for y = 30, 50 do
        W.set(x, y, 80, {shape = 'FLOOR', material = 'SOIL', outside = true})
      end end
      for x = 110, 113 do for y = 38, 41 do
        W.set(x, y, 80, {shape = 'EMPTY', outside = true})
        W.set(x, y, 79, {shape = 'FLOOR', material = 'POOL', liquid = true, depth = 7, outside = true})
      end end
      local wg = B.walk_group
      B.walk_group = function(x, y, z) if z == 80 and x >= 100 then return 1 end return wg(x, y, z) end
      local real_req = reqscript
      reqscript = function(name)
        if name == 'ai-water' then
          return {last = function() return {bodies = {{kind = 'surface', nearest = {x = 110, y = 39, z = 79, d = 50}}}} end}
        end
        return real_req(name)
      end
    """, B, W)
    try:
        r = B.place_well(LUA.table(), LUA.table_from({"year": 148, "tick": 100}), True)
        assert not r.ok and "within 40 tiles" in r.error and "50 tiles off" in r.error, r.error
        r = B.place_well(LUA.table_from({"shore_reach": 60}), LUA.table_from({"year": 148, "tick": 100}), True)
        assert r.ok and r.shore and r.from_gate and r.from_gate <= 60 and r.x >= 109, (r.ok, r.error)
        r = B.place_well(LUA.table_from({"shore_reach": 45}), LUA.table_from({"year": 148, "tick": 100}), True)
        assert not r.ok and "within 45 tiles" in r.error, r.error
    finally:
        LUA.execute("""local B, saved = ...
          B.pasture_anchors, B.walk_group, reqscript = saved.pa, saved.wg, saved.req""", B, saved)


@test("wells on the shore (0.105.4 review): at most the 3 nearest far ponds are looked round")
def _():
    saved = LUA.execute("""local B = ...
      return {pa = B.pasture_anchors, ti = B.tile_info, req = reqscript}""", B)
    LUA.execute("""local B, W = ...
      B.pasture_anchors = function() return {{x = 20, y = 20, z = 80}} end
      SEEN = {}
      local ti = B.tile_info
      B.tile_info = function(x, y, z) if z == 80 then SEEN[x .. ',' .. y] = true end return ti(x, y, z) end
      local real_req = reqscript
      reqscript = function(name)
        if name == 'ai-water' then
          local b = {}
          -- five far ponds 45-85 tiles east of the gate (the nearest last in the list)
          for i, d in ipairs({85, 75, 65, 55, 45}) do
            table.insert(b, {kind = 'surface', nearest = {x = 20 + d, y = 20, z = 79, d = d}})
          end
          return {last = function() return {bodies = b} end}
        end
        return real_req(name)
      end""", B, W)
    try:
        r = B.place_well(LUA.table_from({"shore_reach": 100}), LUA.table_from({"year": 148, "tick": 100}), True)
        assert not r.ok
        seen = LUA.eval("SEEN")
        looked = [d for d in (45, 55, 65, 75, 85) if seen[f"{20 + d},20"]]
        assert looked == [45, 55, 65], looked
    finally:
        LUA.execute("""local B, saved = ...
          B.pasture_anchors, B.tile_info, reqscript = saved.pa, saved.ti, saved.req""", B, saved)


@test("cistern plan (0.105.4 review): the distance spread over the wider box stops at the plan's deadline")
def _():
    LUA.execute("""local W = ...
      W.citizens = {}
      for i = 1, 20 do table.insert(W.citizens, {x = 50 + i % 10, y = 60, z = 80}) end
      for x = 112, 117 do for y = 55, 65 do W.set(x, y, 79, {shape = 'EMPTY', liquid = true, depth = 7}) end end
    """, W)
    B.CISTERN_SECONDS = -1
    try:
        r = B.plan_cistern(None, None, LUA.table_from({"tunnel": 70}))
    finally:
        B.CISTERN_SECONDS = 3
    assert r[0] is None and "ran out of time" in r[1], r


@test("cavern well (0.104.13): urgent: dug first (priority 1) and in an urgent slot beyond the two")
def _():
    cavern_column()
    start(kind="bedrooms", rooms=4, room_size=3)
    start(kind="dining", tables=8)
    r = B.place_well(LUA.table_from({"cavern": True}), LUA.table_from({"year": 148, "tick": 100}), False)
    assert not r.ok and r.rejected, r.error
    r = B.place_well(LUA.table_from({"cavern": True, "urgent": True}), LUA.table_from({"year": 148, "tick": 100}), False)
    assert r.ok and r.urgent, r.error
    assert W.get(70, 58, 66).dig_text == "h1" and W.get(71, 58, 66).dig_text == "i1"


@test("dig first (0.104.128): an urgent level's tiles designated at priority 2; an open level raised to it once")
def _():
    r = start(kind="hospital", beds=8, urgent=True)
    assert r.ok, r.error
    texts = [tt.dig_text for tt in W.tiles.values() if tt.designated and tt.dig_text]
    assert texts and all(x in ("d2",) or not x.startswith("d") for x in texts), set(texts)
    assert designated_count() >= r.tiles
    W.reset()
    r = start(kind="bedrooms", rooms=4, room_size=3)
    assert r.ok, r.error
    assert not [tt for tt in W.tiles.values() if tt.designated and tt.dig_text == "d2"]
    pid = r.project_id or r.id
    got = B.prioritize_project(pid, 2, False)
    assert got.ok and got.tiles > 0 and got.priority == 2, (got.ok, got.error)
    assert [tt for tt in W.tiles.values() if tt.designated and tt.dig_text == "d2"]
    again = B.prioritize_project(pid, 2, False)
    assert again.ok and again.already and again.tiles == 0, "done before: ok, nothing redone"


@test("cavern well (0.104.13): a shaft tile that lost its designation is designated again; no well over a closed shaft")
def _():
    cavern_column()
    r = B.place_well(LUA.table_from({"cavern": True, "urgent": True}), LUA.table_from({"year": 148, "tick": 100}), False)
    assert r.ok, r.error
    # the channel above dug, the rock below turned to a ramp and its designation dropped
    LUA.eval("""function(W)
        local t = W.get(70, 58, 70); t.designated = false; t.shape = 'EMPTY'
        local s = W.get(70, 58, 69); s.designated = false; s.shape = 'RAMP'
    end""")(W)
    d = B.projects_report().open[1].dig
    assert d.stuck == 0 and d.redesignated == 1 and W.get(70, 58, 69).designated, (d.stuck, d.redesignated)
    assert W.get(70, 58, 69).dig_text == "h1"
    # every stair dug, the shaft not: the well is never placed over it
    dig_shaft_stairs()
    f = B.furnish_project(r.project_id, True)
    assert not f.ok and "digging" in f.error, f.error


GAME_FAKE = """
  SB, LINKS, PULLS, REMOVED, DECON = {}, {}, {}, {}, {}
  xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
  df = df or {}
  df.building_type = {Hatch = 7, Trap = 8, [7] = 'Hatch', [8] = 'Trap'}
  df.trap_type = {Lever = 3}
  df.job_type = {PullLever = 1, LinkBuildingToTrigger = 2}
  df.building = {find = function(id) for _, b in pairs(SB) do if b.id == id then return b end end end}
  MECHS = {}
  df.global = {world = {items = {other = {TRAPPARTS = MECHS}}}}
  dfhack.buildings = {findAtTile = function(p) return SB[p.x .. ',' .. p.y .. ',' .. p.z] end,
                      deconstruct = function(b) table.insert(DECON, b.id) end}
  dfhack.job = {removeJob = function(j) table.insert(REMOVED, j) end}
  TIMERS = {}
  dfhack.timeout = function(n, unit, f) table.insert(TIMERS, f); return #TIMERS end
  UNITS = {}
  df.global.world.units = {active = UNITS}
  DFU_SAVE = dfhack.units
  dfhack.units = setmetatable({}, {__index = DFU_SAVE})
  for k, v in pairs({isActive = function() return true end, isDead = function() return false end,
                     isCitizen = function(u) return u.citizen == true end, isDanger = function(u) return u.danger == true end,
                     isAnimal = function(u) return u.animal == true end, isFortControlled = function() return false end,
                     isTame = function() return false end}) do dfhack.units[k] = v end
  CR_OK = 0
  dfhack.run_command_silent = function(cmd, a, b, id, inst)
    table.insert(PULLS, {id = tonumber(id), instant = inst})
    for _, x in pairs(SB) do if x.t == 7 and LINKS[x.id] then x.door_flags.closed = not x.door_flags.closed end end
    return 'ok', 0
  end
  REAL_REQ = REAL_REQ or reqscript
  LINK_RESULT = {ok = true}
  reqscript = function(name)
    if name == 'ai-gates' then
      return {link_lever = function(l, g) if LINK_RESULT.ok then LINKS[g] = {l} end; return LINK_RESULT end,
              lever_links = function() return LINKS end}
    end
    return REAL_REQ(name)
  end
  function MKS(x, y, z, t, built, trap_type)
    local b = {id = t * 100000 + x * 100 + y, t = t, built = built, jobs = {}, trap_type = trap_type,
               door_flags = {forbidden = false, closed = true},
               getType = function(self) return self.t end,
               getBuildStage = function(self) return self.built and 1 or 0 end,
               getMaxBuildStage = function() return 1 end}
    SB[x .. ',' .. y .. ',' .. z] = b
    return b
  end
  function MECH(n) for i = #MECHS, 1, -1 do MECHS[i] = nil end
    for i = 1, n do MECHS[i] = {flags = {}} end end
"""
GAME_CLEAN = ("df.building = nil; dfhack.buildings = nil; df.building_type = nil; df.job_type = nil; df.trap_type = nil; "
              "df.global = nil; dfhack.job = nil; dfhack.timeout = nil; SB = nil; MKS = nil; reqscript = REAL_REQ; "
              "if DFU_SAVE ~= nil then dfhack.units = DFU_SAVE; DFU_SAVE = nil end")


def dug_cavern_well():
    cavern_column()
    r = B.place_well(LUA.table_from({"cavern": True}), LUA.table_from({"year": 148, "tick": 100}), False)
    assert r.ok, r.error
    release_hold(r.project_id)
    open_shaft()
    dig_shaft_stairs()
    assert B.furnish_project(r.project_id, True).ok
    return r


@test("cavern well (0.104.151-152): the stair lid only where the shaft gate can't be built: planned, then locked")
def _():
    r = dug_cavern_well()
    LUA.execute(GAME_FAKE)
    try:
        lids = B.well_lids(False)
        assert len(lids) == 1 and lids[1].state == "none" and lids[1].gate == "none", dict(lids[1])
        assert (lids[1].x, lids[1].y, lids[1].z) == (71, 58, 70)
        assert not B.seal_well_stairs(False).ok                      # the gate seals the cavern: no lid
        LUA.eval("""function(B, id)
            local d = B.load_projects()
            for _, p in ipairs(d.list) do if p.id == id then p.shaft_gate = {lever = {x = 0, y = 0, z = 0}, impossible = true} end end
            B.save_projects(d)
        end""")(B, r.project_id)
        assert B.well_lids(False)[1].gate == "none_possible"
        before = len(W.placed)
        s = B.seal_well_stairs(False)
        assert s.ok and s.planned == 1, dict(s)
        put = [W.placed[i] for i in range(before + 1, len(W.placed) + 1)]
        assert any(h.text == "H" and (h.x, h.y, h.z) == (71, 58, 70) for h in put), [dict(h) for h in put]
        lid = LUA.eval("MKS")(71, 58, 70, 7, False)
        assert B.well_lids(False)[1].state == "planned" and not B.seal_well_stairs(False).ok
        lid.built = True
        s = B.seal_well_stairs(False)
        assert s.ok and s.locked == 1 and lid.door_flags.forbidden is True, dict(s)
        assert B.well_lids(False)[1].state == "locked" and not B.seal_well_stairs(False).ok
        LUA.eval("MKS")(71, 58, 70, 99, True)                         # something else on the step
        assert B.well_lids(False)[1].state == "blocked"
    finally:
        LUA.execute(GAME_CLEAN)


@test("cavern well (0.104.152): the shaft gate: lever, then (2 mechanisms free) a hatch at the shaft's bottom, linked, opened; shut at once on danger")
def _():
    r = dug_cavern_well()
    LUA.execute(GAME_FAKE)
    try:
        mk, mech = LUA.eval("MKS"), LUA.eval("MECH")
        assert B.well_lids(False)[1].gate == "none"
        before = len(W.placed)
        s = B.well_shaft_step(False, False)
        assert s.ok and s.wells[1].stage == "lever_placed", dict(s.wells[1])
        put = [W.placed[i] for i in range(before + 1, len(W.placed) + 1)]
        assert [h.text for h in put] == ["Tl"], [dict(h) for h in put]          # the lever only, no hatch yet
        lx, ly, lz = put[0].x, put[0].y, put[0].z
        assert lz == 70 and max(abs(lx - 70), abs(ly - 58)) >= 2, (lx, ly)      # outside the well's 3x3
        assert B.well_lids(False)[1].gate == "no_lever"
        lv = mk(lx, ly, 70, 8, False, 3)
        assert B.well_lids(False)[1].gate == "building"
        assert not B.well_shaft_step(False, False).ok
        lv.built = True
        assert B.well_lids(False)[1].gate == "no_hatch"
        mech(1)
        s = B.well_shaft_step(False, False)
        assert not s.ok and s.wells[1].stage == "waiting_mechanisms", dict(s.wells[1])   # the well stays open meanwhile
        mech(2)
        before = len(W.placed)
        s = B.well_shaft_step(False, False)
        assert s.ok and s.wells[1].stage == "hatch_placed", dict(s.wells[1])
        put = [W.placed[i] for i in range(before + 1, len(W.placed) + 1)]
        assert [(h.text, h.x, h.y, h.z) for h in put] == [("H", 70, 58, 63)], [dict(h) for h in put]  # the shaft's bottom
        h = mk(70, 58, 63, 7, False)
        assert B.well_lids(False)[1].gate == "building"
        h.built = True
        assert B.well_lids(False)[1].gate == "unlinked"
        # a lid locked by an older version is unlocked while the gate is built (the way down)
        lid = mk(71, 58, 70, 7, True)
        lid.door_flags.forbidden = True
        s = B.well_shaft_step(False, False)
        assert s.ok and s.wells[1].stage == "linking" and lid.door_flags.forbidden is False, dict(s.wells[1])
        assert not B.seal_well_stairs(False).ok                                  # and not locked again
        assert B.well_lids(False)[1].gate == "closed"                             # linked; a hatch starts shut
        s = B.well_shaft_step(False, False)
        pulls = LUA.eval("PULLS")
        # (0.104.164) opened at once (a dwarf's pull never came on Teacheroar)
        assert s.ok and s.wells[1].stage == "opened" and pulls[1].instant == "--instant" and h.door_flags.closed is False
        assert B.well_lids(False)[1].gate == "open" and not B.well_shaft_step(False, False).ok
        s = B.well_shaft_step(True, False)
        assert s.ok and s.wells[1].stage == "closed" and pulls[2].instant == "--instant" and h.door_flags.closed is True
        assert B.well_shaft_step(False, False).wells[1].stage == "opened"
        # a danger while a dwarf is on the way to pull it open: the pull called off
        lv.jobs[1] = LUA.table_from({"job_type": 1})
        assert B.well_lids(False)[1].gate == "pulling"
        s = B.well_shaft_step(True, False)
        assert s.ok and s.wells[1].stage == "closed" and len(LUA.eval("REMOVED")) == 1, dict(s.wells[1])
        # (0.104.164) a pull to open that no dwarf makes: called off, the gate opened at once
        lv.jobs[1] = LUA.table_from({"job_type": 1})
        s = B.well_shaft_step(False, False)
        assert s.ok and s.wells[1].stage == "opened" and len(LUA.eval("REMOVED")) == 2 and h.door_flags.closed is False, dict(s.wells[1])
        assert B.well_shaft_step(True, False).wells[1].stage == "closed"
        # (0.104.153) the watcher: started once the gate is linked; it shuts an open gate at once
        lv.jobs[1] = None
        assert B.well_shaft_step(False, False).wells[1].stage == "opened" and h.door_flags.closed is False
        assert B.SHAFT_WATCH.on and B.well_lids(False)[1].watching is True
        tick = lambda: LUA.eval("function() local f = TIMERS[#TIMERS]; TIMERS[#TIMERS] = nil; f() end")()
        units = LUA.eval("UNITS")
        units[1] = LUA.table_from({"id": 9, "animal": True, "pos": LUA.table_from({"x": 100, "y": 58, "z": 50}),
                                   "flags1": LUA.table_from({}), "flags4": LUA.table_from({"agitated_wilderness_creature": True})})
        tick()                                                    # 30 tiles off, not flying: left alone
        assert h.door_flags.closed is False
        units[1].pos.x = 85                                       # 15 tiles: shut at once, no dwarf
        n = len(LUA.eval("PULLS"))
        tick()
        assert h.door_flags.closed is True and LUA.eval("PULLS")[n + 1].instant == "--instant"
        assert B.well_lids(False)[1].watch_last.unit == 9
        assert B.well_lids(False)[1].watch_near.id == 9                # (0.104.165) the watcher's test, said
        tick()                                                    # shut: nothing more (only the brain opens it)
        assert len(LUA.eval("PULLS")) == n + 1
    finally:
        LUA.eval("function(B) B.SHAFT_WATCH.on = false; B.SHAFT_WATCH.timer = nil end")(B)
        LUA.execute(GAME_CLEAN)


@test("cavern well (0.105.4 review): the breach held until the lever stands and a hatch cover and 2 mechanisms are in store")
def _():
    cavern_column()
    r = B.place_well(LUA.table_from({"cavern": True}), LUA.table_from({"year": 148, "tick": 100}), False)
    assert r.ok and r.held == 2, r.error
    assert not W.get(70, 58, 63).designated and not W.get(71, 58, 63).designated   # the cavern's roof untouched
    # every other level dug: still not "furnish" (the shaft isn't open)
    LUA.eval("""function(W)
        local t = W.get(70, 58, 70); t.designated = false; t.shape = 'EMPTY'
        for z = 64, 69 do local s = W.get(70, 58, z); s.designated = false; s.shape = 'EMPTY' end
        for z = 64, 70 do local s = W.get(71, 58, z); s.designated = false; s.shape = (z == 70) and 'STAIR_DOWN' or 'STAIR_UPDOWN' end
    end""")(W)
    p = B.projects_report().open[1]
    assert p.next is False and p.dig.held == 2 and p.dig.stuck == 0, (p.next, p.dig.held, p.dig.stuck)
    LUA.execute(GAME_FAKE)
    try:
        LUA.execute("COVERS = {}; df.global.world.items.other.HATCH_COVER = COVERS")
        mk, mech = LUA.eval("MKS"), LUA.eval("MECH")
        # the gate runs while the well is still being dug: the lever first
        s = B.well_shaft_step(False, False)
        assert s.ok and s.wells[1].stage == "lever_placed", dict(s.wells[1])
        lid = B.well_lids(False)[1]
        assert lid.held and lid.hatch_covers == 0
        lv = mk(W.placed[len(W.placed)].x, W.placed[len(W.placed)].y, 70, 8, False, 3)
        lv.built = True
        mech(2)
        s = B.well_shaft_step(False, False)
        assert not s.ok and s.wells[1].stage == "waiting_parts" and s.wells[1].hatch_covers == 0, dict(s.wells[1])
        assert not W.get(70, 58, 63).designated                         # no cover: still held
        LUA.execute("COVERS[1] = {flags = {}}")
        mech(1)
        s = B.well_shaft_step(False, False)
        assert not s.ok and s.wells[1].stage == "waiting_parts"         # a cover but 1 mechanism
        mech(2)
        s = B.well_shaft_step(True, True)
        assert s.ok and s.wells[1].stage == "break_through" and not W.get(70, 58, 63).designated   # dry run
        s = B.well_shaft_step(False, False)
        assert s.ok and s.wells[1].stage == "break_started", dict(s.wells[1])
        assert W.get(70, 58, 63).designated and W.get(71, 58, 63).dig_text == "u"   # now the last level and step
        assert B.projects_report().open[1].dig.held is None
        s = B.well_shaft_step(False, False)
        assert not s.ok and s.wells[1].stage == "breaking_through"      # no hatch till it's open
        LUA.eval("function(W) local t = W.get(70, 58, 63); t.designated = false; t.shape = 'EMPTY' end")(W)
        before = len(W.placed)
        s = B.well_shaft_step(False, False)
        assert s.ok and s.wells[1].stage == "hatch_placed", dict(s.wells[1])   # the hatch straight after the breach
        put = [W.placed[i] for i in range(before + 1, len(W.placed) + 1)]
        assert [(h.text, h.x, h.y, h.z) for h in put] == [("H", 70, 58, 63)], [dict(h) for h in put]
    finally:
        LUA.execute(GAME_CLEAN)


@test("cavern well (0.105.4 review): a cavern no dwarf has seen is opened only when the Rules tab allows it")
def _():
    cavern_column()
    W.set(70, 58, 62, LUA.table_from({"hidden": True}))
    r = B.place_well(LUA.table_from({"cavern": True}), LUA.table_from({"year": 148, "tick": 100}), True)
    assert not r.ok and r.unfound and "Rules tab" in r.error, r.error
    r = B.place_well(LUA.table_from({"cavern": True, "open_caverns": True}), LUA.table_from({"year": 148, "tick": 100}), True)
    assert r.ok and r.held == 2, r.error


@test("cavern well (0.105.4 review): a \"no spot\" is kept (no second search) until the survey changes or 28 days pass")
def _():
    calls = LUA.execute("""local B = ...
      CALLS = {n = 0}
      CAVERN_REAL = B.find_cavern_well_spot
      B.find_cavern_well_spot = function(...) CALLS.n = CALLS.n + 1; return CAVERN_REAL(...) end
      return CALLS""", B)
    try:
        day = lambda d: LUA.table_from({"year": 148, "tick": 100 + d * 1200})
        a = B.place_well(LUA.table_from({"cavern": True, "gallery": 0}), day(0), False)
        assert not a.ok and calls.n == 1
        b = B.place_well(LUA.table_from({"cavern": True, "gallery": 0}), day(5), False)
        assert not b.ok and b.cached and b.error == a.error and calls.n == 1
        B.place_well(LUA.table_from({"cavern": True, "gallery": 40}), day(5), False)   # other reach: searched
        assert calls.n == 2
        B.place_well(LUA.table_from({"cavern": True, "gallery": 40}), day(40), False)  # 28 days on: searched
        assert calls.n == 3
    finally:
        LUA.execute("local B = ...; B.find_cavern_well_spot = CAVERN_REAL", B)


@test("cavern well (0.104.152): a link that keeps failing (not for mechanisms) -> the hatch down, the stair lid instead")
def _():
    r = dug_cavern_well()
    LUA.execute(GAME_FAKE)
    try:
        mk = LUA.eval("MKS")
        assert B.well_shaft_step(False, False).ok
        lever = [x for x in W.placed.values() if x.text == "Tl"][-1]
        mk(lever.x, lever.y, 70, 8, True, 3)
        LUA.eval("MECH")(2)
        assert B.well_shaft_step(False, False).ok
        mk(70, 58, 63, 7, True)
        LUA.execute("LINK_RESULT = {ok = false, error = 'this DF version has no lever-link job'}")
        for i in range(2):
            s = B.well_shaft_step(False, False)
            assert not s.ok and B.well_lids(False)[1].gate == "unlinked", dict(s.wells[1])
        s = B.well_shaft_step(False, False)
        assert "taken down" in s.wells[1].error and len(LUA.eval("DECON")) == 1, dict(s.wells[1])
        assert B.well_lids(False)[1].gate == "none_possible"
        # (review 2) the hatch still stands (until a dwarf takes it away): the lid waits
        lid = mk(71, 58, 70, 7, True)
        assert B.well_lids(False)[1].gate_hatch_standing is True
        sl = B.seal_well_stairs(False)
        assert not sl.ok and lid.door_flags.forbidden is False, dict(sl)
        LUA.execute("SB['70,58,63'] = nil")                                    # taken away
        sl = B.seal_well_stairs(False)
        assert sl.ok and sl.locked == 1 and lid.door_flags.forbidden is True, dict(sl)
        LUA.execute("LINK_RESULT = {ok = false, error = 'a link needs 2 free mechanisms (0 free)'}")
    finally:
        LUA.execute(GAME_CLEAN)


@test("cavern well (0.104.156): a link job DF cancels is counted lost; 3 times with the same mechanisms -> no new job until others")
def _():
    r = dug_cavern_well()
    LUA.execute(GAME_FAKE)
    try:
        mk = LUA.eval("MKS")
        assert B.well_shaft_step(False, False).ok
        lever = [x for x in W.placed.values() if x.text == "Tl"][-1]
        mk(lever.x, lever.y, 70, 8, True, 3)
        LUA.eval("MECH")(2)
        assert B.well_shaft_step(False, False).ok
        mk(70, 58, 63, 7, True)
        # the job is made (ok) but DF cancels it: no link, no job left on the lever
        LUA.execute("""FREE_IDS = {11, 12}
            local G0 = reqscript
            reqscript = function(name)
              if name == 'ai-gates' then
                return {link_lever = function() LINK_CALLS = (LINK_CALLS or 0) + 1; return {ok = true} end,
                        lever_links = function() return LINKS end,
                        free_mechanisms = function(n, near)
                          NEAR = near
                          local out = {}; for _, id in ipairs(FREE_IDS) do table.insert(out, {id = id}) end
                          return out, 0 end}
              end
              return G0(name)
            end""")
        for i in range(4):                                  # 1 asked, then lost 1, 2, 3 (the 4th call)
            s = B.well_shaft_step(False, False)
            if i < 3:
                assert s.ok and s.wells[1].stage == "linking", (i, dict(s.wells[1]))
        assert LUA.eval("LINK_CALLS") == 3
        assert not s.ok and "lost 3 times" in s.wells[1].error and "11,12" in s.wells[1].error, dict(s.wells[1])
        near = LUA.eval("NEAR")
        assert (near.x, near.y, near.z) == (lever.x, lever.y, 70), dict(near)       # picked near the lever
        lids = B.well_lids(False)
        assert lids[1].gate_link_lost == 3, dict(lids[1])
        assert not B.well_shaft_step(False, False).ok and LUA.eval("LINK_CALLS") == 3   # same ones: waits
        LUA.execute("FREE_IDS = {11, 14}")                  # another mechanism free: a fresh try
        s = B.well_shaft_step(False, False)
        assert s.ok and s.wells[1].stage == "linking" and LUA.eval("LINK_CALLS") == 4, dict(s.wells[1])
        LUA.execute("local lv; for _, b in pairs(SB) do if b.t == 8 then lv = b.id end end; "
                    "for _, b in pairs(SB) do if b.t == 7 and b.id == 7 * 100000 + 70 * 100 + 58 then LINKS[b.id] = {lv} end end")
        s = B.well_shaft_step(False, False)                 # linked at last: the count is cleared
        assert s.wells[1].was in ("closed", "open") and B.well_lids(False)[1].gate_link_lost is None, dict(s.wells[1])
    finally:
        LUA.execute("FREE_IDS = nil; LINK_CALLS = nil; NEAR = nil")
        LUA.execute(GAME_CLEAN)


@test("cavern well (0.104.152): the game refusing the bottom hatch 3 times -> the stair lid instead (not after one)")
def _():
    r = dug_cavern_well()
    LUA.execute(GAME_FAKE)
    try:
        mk = LUA.eval("MKS")
        assert B.well_shaft_step(False, False).ok
        lever = [x for x in W.placed.values() if x.text == "Tl"][-1]
        mk(lever.x, lever.y, 70, 8, True, 3)
        LUA.eval("MECH")(2)
        LUA.execute("""local q = REAL_REQ('quickfort'); Q_REAL = q.apply_blueprint
            q.apply_blueprint = function(p) local s = Q_REAL(p); if p.mode == 'build' then s.build_designated.value = 0 end; return s end""")
        for i in range(2):
            s = B.well_shaft_step(False, False)
            assert not s.ok and B.well_lids(False)[1].gate == "no_hatch", dict(s.wells[1])
        s = B.well_shaft_step(False, False)
        assert "stair lid instead" in s.wells[1].error and B.well_lids(False)[1].gate == "none_possible", dict(s.wells[1])
    finally:
        LUA.execute("local q = REAL_REQ('quickfort'); if Q_REAL then q.apply_blueprint = Q_REAL; Q_REAL = nil end")
        LUA.execute(GAME_CLEAN)


@test("cavern well (0.104.152): never dropped from the project list, however many levels close after it")
def _():
    r = dug_cavern_well()
    LUA.eval("""function(B, id)
        local d = B.load_projects()
        for _, p in ipairs(d.list) do if p.id == id then p.phase = 'done' end end
        for i = 1, 40 do table.insert(d.list, {id = 1000 + i, kind = 'bedrooms', phase = 'done', z = 70}) end
        B.save_projects(d)
    end""")(B, r.project_id)
    ids = [p.id for p in LUA.eval("function(B) return B.load_projects().list end")(B).values()]
    assert r.project_id in ids, ids


@test("cavern well: never through an aquifer, past open space, into salt or magma, or under a full lake")
def _():
    for change, word in (({"aquifer": True}, "solid rock"), ):
        cavern_column()
        W.set(70, 58, 65, LUA.table_from(change))
        r = B.find_cavern_well_spot(LUA.table_from([]))
        assert r[0] is None and word in r[1], r[1]
        W.reset()
    cavern_column()
    W.set(71, 58, 64, LUA.table_from({"shape": "EMPTY"}))       # open space beside the shaft
    assert B.find_cavern_well_spot(LUA.table_from([]))[0] is None
    for lake, word in (({"salt": True}, "salt"), ({"magma": True}, "magma")):
        W.reset()
        cavern_column(**lake)
        res = B.find_cavern_well_spot(LUA.table_from([]))
        assert res[0] is None and word in res[1], res[1]
    W.reset()
    cavern_column(lake_depth=7)
    W.set(70, 58, 62, LUA.table_from({"shape": "EMPTY", "feature": True, "liquid": True, "depth": 7}))
    res = B.find_cavern_well_spot(LUA.table_from([]))
    assert res[0] is None and "pressure" in res[1], res[1]


@test("rooms (0.104.20): a bedroom's wall dug open: a wall built back in the gap; the door, a corridor and other rooms left alone")
def _():
    # a 3x3 bedroom at x 70-72, y 57-59, z 70 (the fort's floors are open all round: the walls rebuilt
    # are the ring round the zone); its door at (71, 56); a bed inside
    LUA.execute("""local B, W = ...
      for x = 69, 73 do for y = 56, 60 do W.set(x, y, 70, {shape = 'WALL'}) end end
      for x = 70, 72 do for y = 57, 59 do W.set(x, y, 70, {shape = 'FLOOR'}) end end
      W.set(71, 56, 70, {shape = 'FLOOR', building = true})          -- the door
      W.set(73, 58, 70, {shape = 'FLOOR'})                           -- the quarry's gap
      W.set(69, 57, 70, {shape = 'FLOOR', zones = {'Office'}})       -- another room's floor: never walled
      B.room_zones = function() return {{id = 1, x1 = 70, y1 = 57, x2 = 72, y2 = 59, z = 70}} end
      B.building_kind_at = function(x, y, z)
        if x == 71 and y == 56 then return 'Door' end
        if x == 72 and y == 59 then return 'Bed' end
      end
    """, B, W)
    gaps, rooms, total = B.room_gaps(40)
    assert rooms == 1 and total == 1 and (gaps[1].x, gaps[1].y) == (73, 58), (rooms, total)
    cleared = LUA.eval("{}")
    LUA.execute("""local B, cleared = ...
      B.clear_smooth = function(x, y, z) table.insert(cleared, x .. ',' .. y) end
      B.planned_walls = function() return {} end""", B, cleared)
    r = B.repair_rooms(False)
    assert list(cleared.values()) == ["73,58"], list(cleared.values())   # (0.104.25) its smoothing mark cleared first
    assert r.ok and r.walls == 1, (r.ok, r.error)
    built = [(c.x, c.y, c.text) for c in W.placed.values() if c.mode == "build"]
    assert built == [(73, 58, "Cw")], built
    # no door and no bed in it (not a bedroom): nothing
    LUA.execute("""local B = ...
      B.building_kind_at = function(x, y, z) return nil end""", B)
    assert B.room_gaps(40)[1] is not None and B.room_gaps(40)[2] == 0


@test("rooms (0.104.26): a bedroom whose door went with its walls: a door on the side to the corridor, walls on the rest")
def _():
    # a 2x2 bedroom at x 70-71, y 57-58, z 70, its ring all open floor (the fort's floors); a bed inside;
    # the corridor north of it (y 55) is open, everything else round the ring is walled except the ring itself
    LUA.execute("""local B, W = ...
      for x = 67, 74 do for y = 54, 61 do W.set(x, y, 70, {shape = 'WALL'}) end end
      for x = 69, 72 do for y = 56, 59 do W.set(x, y, 70, {shape = 'FLOOR'}) end end   -- room and its ring dug out
      for x = 67, 74 do W.set(x, 55, 70, {shape = 'FLOOR'}) end                         -- the corridor
      B.room_zones = function() return {{id = 1, x1 = 70, y1 = 57, x2 = 71, y2 = 58, z = 70}} end
      B.building_kind_at = function(x, y, z) if x == 71 and y == 58 then return 'Bed' end end
      B.planned_walls = function() return {} end
      B.clear_smooth = function() end
    """, B, W)
    gaps, rooms, total = B.room_gaps(40)
    assert rooms == 1 and total == 12, (rooms, total)
    doors = [(g.x, g.y) for g in gaps.values() if g.door]
    assert len(doors) == 1 and doors[0][1] == 56, doors                # on the north side, to the corridor
    r = B.repair_rooms(False)
    assert r.ok and r.walls == 12, (r.ok, r.error)
    built = sorted((c.x, c.y, c.text) for c in W.placed.values() if c.mode == "build")
    assert sum(1 for b in built if b[2] == "d") == 1 and sum(1 for b in built if b[2] == "Cw") == 11, built
    # no way out found (the corridor walled): the room is left alone, never walled shut
    LUA.execute("""local B, W = ...
      for x = 67, 74 do W.set(x, 55, 70, {shape = 'WALL'}) end""", B, W)
    assert B.room_gaps(40)[1] is not None and B.room_gaps(40)[2] == 0


@test("rooms (0.104.25): a planned wall on a floor marked for smoothing: counted as held; the repair clears the mark")
def _():
    LUA.execute("""local B, W = ...
      W.marks = {['70,58,70'] = true, ['71,58,70'] = false}
      B.planned_walls = function() return {{x = 70, y = 58, z = 70, b = {jobs = {}}}, {x = 71, y = 58, z = 70, b = {jobs = {}}}} end
      B.smooth_marked = function(x, y, z) return W.marks[x .. ',' .. y .. ',' .. z] == true end
      B.clear_smooth = function(x, y, z) W.marks[x .. ',' .. y .. ',' .. z] = false end
      B.room_zones = function() return {} end
    """, B, W)
    assert B.room_gaps_report().stalled == 1
    r = B.repair_rooms(False)
    assert r.ok and r.freed == 1 and r.walls == 0, (r.ok, r.error)
    assert B.room_gaps_report().stalled == 0


@test("cistern plan: under a fort floor, a tunnel through rock to still water, floodgate then plug; never a river")
def _():
    LUA.execute("""local W = ...
      W.citizens = {}
      for i = 1, 20 do table.insert(W.citizens, {x = 50 + i % 10, y = 60, z = 80}) end
      for x = 30, 90 do for y = 45, 75 do
        if not (x == 60 and y == 60) then W.set(x, y, 79, {shape = 'WALL', material = 'STONE'}) end
      end end
      for x = 74, 78 do for y = 55, 65 do
        W.set(x, y, 79, {shape = 'EMPTY', liquid = true, depth = 7})
      end end
    """, W)
    p = B.plan_cistern()
    plan = p[0] if not hasattr(p, "cistern") else p
    assert plan is not None and plan.cistern is not None, p
    c = plan.cistern
    assert c.z == 79 and c.x2 - c.x1 == 4 and plan.well.z == 80, (c.z, plan.well.z)
    assert plan.tunnel >= 2 and plan.source == "underground pool", (plan.tunnel, plan.source)
    fg, plug, w = plan.floodgate, plan.plug, plan.water
    assert abs(plug.x - w.x) + abs(plug.y - w.y) == 1                     # the plug touches the water
    assert not (c.x1 <= fg.x <= c.x2 and c.y1 <= fg.y <= c.y2)           # the floodgate is outside the room
    assert min(abs(fg.x - c.x1), abs(fg.x - c.x2)) <= 1 or min(abs(fg.y - c.y1), abs(fg.y - c.y2)) <= 1
    assert designated_count() == 0                                        # a plan only
    LUA.execute("""local W = ...
      for x = 74, 78 do for y = 55, 65 do W.set(x, y, 79, {material = 'RIVER'}) end end
    """, W)
    r = B.plan_cistern()
    assert r[0] is None, r                                                 # rivers can be under pressure


@test("cistern plan (0.105.3): still water past the 30-tile tunnel: refused with how far; the brain's longer reach finds it")
def _():
    LUA.execute("""local W = ...
      W.citizens = {}
      for i = 1, 20 do table.insert(W.citizens, {x = 50 + i % 10, y = 60, z = 80}) end
      for x = 30, 90 do for y = 45, 75 do
        if not (x == 60 and y == 60) then W.set(x, y, 79, {shape = 'WALL', material = 'STONE'}) end
      end end
      -- Hammerstirred's pool: underground, stagnant, well off the fort's east end (x80)
      for x = 112, 117 do for y = 55, 65 do
        W.set(x, y, 79, {shape = 'EMPTY', liquid = true, depth = 7, stagnant = true})
      end end
    """, W)
    r = B.plan_cistern()
    assert r[0] is None and "no still, fresh water" in r[1], r
    # in sight (a wider look), but the tunnel too short: says how far it was
    B.CISTERN_RADIUS = 60
    try:
        r = B.plan_cistern(None, None, LUA.table_from({"tunnel": 20}))
    finally:
        B.CISTERN_RADIUS = 30
    assert r[0] is None and "tiles from a fort floor; a tunnel reaches 20" in r[1], r
    # the brain's longer reach: the area grows with it, and the tunnel goes there
    r = B.plan_cistern(None, None, LUA.table_from({"tunnel": 50}))
    plan = r[0] if not hasattr(r, "cistern") else r
    assert plan is not None and plan.cistern is not None, r
    assert plan.tunnel >= 25 and plan.stagnant and plan.source == "underground pool", (plan.tunnel, plan.source)
    assert plan.plug.x == 111 and plan.water.x == 112, (plan.plug.x, plan.water.x)   # the plug touches the pool
    assert designated_count() == 0


def _body():
    LUA.execute("""local W = ...
      W.citizens = {}
      for i = 1, 20 do table.insert(W.citizens, {x = 50 + i % 10, y = 60, z = 80}) end
      for x = 30, 90 do for y = 45, 75 do
        if not (x == 60 and y == 60) then W.set(x, y, 79, {shape = 'WALL', material = 'STONE'}) end
      end end
      for x = 74, 78 do for y = 55, 65 do W.set(x, y, 79, {shape = 'EMPTY', liquid = true, depth = 7}) end end
      -- the game's side: buildings by tile, lever links, lever pulls
      BLD, LINKS, PULLS = {}, {}, {}
      xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
      df = df or {}
      df.building_type = {[1] = 'Floodgate', [2] = 'Trap', [3] = 'Well'}
      dfhack.buildings = {findAtTile = function(p) return BLD[p.x .. ',' .. p.y .. ',' .. p.z] end}
      CR_OK = 0
      dfhack.run_command_silent = function(cmd, a, b, id)
        if cmd == 'dig-now' then                       -- (0.104.145) the plug dug at once
          local x, y, z = a:match('(%d+),(%d+),(%d+)')
          W.set(tonumber(x), tonumber(y), tonumber(z), {shape = 'FLOOR'})
          return 'ok', 0
        end
        table.insert(PULLS, id)
        for _, b in pairs(BLD) do if b.gate_flags then b.gate_flags.closed = not b.gate_flags.closed end end
        return 'ok', 0
      end
      local real_req = reqscript
      reqscript = function(name)
        if name == 'ai-gates' then
          return {link_lever = function(l, g) return {ok = true} end,
                  lever_links = function() return LINKS end}
        end
        return real_req(name)
      end
      function MKB(x, y, z, t, extra)
        local b = {id = #PULLS + x * 1000 + y, t = t, built = false,
                   getType = function(self) return self.t end,
                   getBuildStage = function(self) return self.built and 1 or 0 end,
                   getMaxBuildStage = function() return 1 end}
        for k, v in pairs(extra or {}) do b[k] = v end
        BLD[x .. ',' .. y .. ',' .. z] = b
        return b
      end
    """, W)
    step = lambda: B.cistern_step(False)
    r = step()
    assert r.ok and r.stage == "digging", dict(r)
    plan = B.cistern_data().plan
    c, z, wx, wy = plan.cistern, plan.cistern.z, plan.well.x, plan.well.y
    assert step().waiting                                                  # still rock
    for x in range(c.x1, c.x2 + 1):                                         # the game digs
        for y in range(c.y1, c.y2 + 1):
            W.set(x, y, z, LUA.table_from({"shape": "FLOOR"}))
    tp = plan.tunnel_path
    for i in range(1, len(tp)):
        W.set(tp[i].x, tp[i].y, z, LUA.table_from({"shape": "FLOOR"}))
    W.set(wx, wy, z + 1, LUA.table_from({"shape": "STAIR_DOWN"}))
    r = step()
    assert r.ok and r.stage == "building", dict(r)
    fg, lv = plan.floodgate, plan.lever
    gate = LUA.globals().MKB(fg.x, fg.y, z, 1, LUA.table_from({"gate_flags": LUA.table_from({"closed": True})}))
    lever = LUA.globals().MKB(lv.x, lv.y, z + 1, 2)
    assert step().waiting                                                  # not built yet
    gate.built = True
    lever.built = True
    assert step().stage == "linking"
    r = step()
    assert r.waiting and "asked for again (1)" in r.error, r.error         # (0.104.110) no link job: asked again
    # (0.104.138) the lever itself gone (toppled) and a new one built on its spot: adopted, linked, counted afresh
    old_id = lever.id
    LUA.execute("""local old = ...
      df.building = {find = function(id) if id == old then return nil end return {} end}""", old_id)
    lever = LUA.globals().MKB(lv.x, lv.y, z + 1, 2, LUA.table_from({"id": old_id + 7}))
    lever.built = True
    r = step()
    assert r.waiting and "replaced" in r.error and B.cistern_data().lever_id == old_id + 7, (r.error,)
    assert B.cistern_data().relinks == 0
    LUA.execute("df.building = nil")
    LUA.globals().LINKS[gate.id] = LUA.table_from([lever.id])
    r = step()
    assert r.ok and r.stage == "opening" and gate.gate_flags.closed, dict(r)       # (0.104.145) still shut
    # (0.104.0) a hauler in the cistern: the plug waits; its stones forbidden once empty
    INSIDE = {"n": 1}
    FORBID = []
    real_units, real_forbid = B.units_on_tiles, B.forbid_items_on
    B.units_on_tiles = lambda tiles, zz: INSIDE["n"]
    B.forbid_items_on = lambda tiles, zz: FORBID.append(len(tiles)) or 0
    r = step()
    assert r.waiting and "1 creature(s) in the cistern" in r.error, dict(r)
    INSIDE["n"] = 0
    r = step()
    # (0.104.145) the plug dug at once with nobody inside, then the gate opened
    assert r.ok and r.stage == "filling" and r.opened and not gate.gate_flags.closed, dict(r)
    assert W.get(plan.plug.x, plan.plug.y, z).shape == "FLOOR"
    assert FORBID == [(c.x2 - c.x1 + 1) * (c.y2 - c.y1 + 1) + len(tp) - 1], FORBID
    B.units_on_tiles, B.forbid_items_on = real_units, real_forbid
    W.set(wx, wy, z, LUA.table_from({"liquid": True, "depth": 4}))
    r = step()
    assert r.waiting and "4/7" in r.error and "plug floor" in r.error and "source" in r.error, r.error   # (0.104.94)
    assert B.cistern_status().path.plug == "floor"
    # (0.104.94) a tree grown in the tunnel is felled
    t1 = plan.tunnel_path[1]
    FELLED = []
    real_fell = B.fell_tree
    B.fell_tree = lambda x, y, zz: FELLED.append((x, y)) or True
    W.set(t1.x, t1.y, z, LUA.table_from({"shape": "WALL", "material": "TREE", "designated": False}))
    r = step()
    assert r.waiting and "blocked" in r.error and FELLED == [(t1.x, t1.y)], (r.error, FELLED)
    W.set(t1.x, t1.y, z, LUA.table_from({"shape": "FLOOR", "material": "SOIL"}))
    B.fell_tree = real_fell
    W.set(wx, wy, z, LUA.table_from({"depth": 7}))
    W.set(wx, wy, z + 1, LUA.table_from({"shape": "FLOOR"}))             # (the fake quickfort channels floors)
    r = step()
    assert r.ok and r.stage == "hole" and gate.gate_flags.closed, dict(r)   # shut at 6/7+
    W.set(wx, wy, z + 1, LUA.table_from({"shape": "EMPTY"}))
    assert step().stage == "well"
    well = LUA.globals().MKB(wx, wy, z + 1, 3)
    well.built = True
    assert step().stage == "done"
    W.set(wx, wy, z, LUA.table_from({"depth": 2}))
    r = step()
    assert r.ok and r.refill and not gate.gate_flags.closed, dict(r)      # low: opened to refill
    assert B.cistern_status().gate == "open"


@test("cistern build: dig, floodgate and lever, link, open, plug, fill, shut, hole, well; then kept topped up")
def _():
    B.CISTERN_HOLD = False                  # (0.104.144) the design under the hold
    try:
        _body()
    finally:
        B.CISTERN_HOLD = False


def _body():
    LUA.execute("""local W = ...
      W.citizens = {}
      for i = 1, 20 do table.insert(W.citizens, {x = 50 + i % 10, y = 60, z = 80}) end
      for x = 30, 90 do for y = 45, 75 do
        if not (x == 60 and y == 60) then W.set(x, y, 79, {shape = 'WALL', material = 'STONE'}) end
      end end
      for x = 74, 78 do for y = 55, 65 do W.set(x, y, 79, {shape = 'EMPTY', liquid = true, depth = 7}) end end
    """, W)
    plan = B.plan_cistern()
    plan = plan[0] if not hasattr(plan, "cistern") else plan
    z = plan.cistern.z
    for c in list(plan.tunnel_path.values()) + [plan.plug]:
        W.set(c.x, c.y, z, LUA.table_from({"shape": "FLOOR", "designated": False}))
    LUA.execute("BLD, LINKS, PULLS = {}, {}, {}")
    gate = LUA.globals().MKB(plan.floodgate.x, plan.floodgate.y, z, 1, LUA.table_from({"gate_flags": LUA.table_from({"closed": False})}))
    gate.built = True
    W.persist["ai-overseer/cistern"] = LUA.table_from({"stage": "filling", "plan": plan, "lever_id": 5, "gate_id": gate.id})
    for x in range(74, 79):
        for y in range(55, 66):
            W.set(x, y, z, LUA.table_from({"liquid": False, "depth": 0, "shape": "RAMP"}))
    LUA.execute("df = df or {}; df.global = {cur_year = 10, cur_year_tick = 0}")
    t1 = plan.tunnel_path[1]                                               # (0.104.96) a wall in the tunnel as well:
    W.set(t1.x, t1.y, z, LUA.table_from({"shape": "WALL", "material": "SOIL", "designated": False}))   # the dry count still runs
    try:
        step = lambda: B.cistern_step(False)
        r = step()
        assert r.waiting and "dry for 0 day" in r.error, r.error
        LUA.execute("df.global.cur_year_tick = 27 * 1200")
        assert step().waiting                                              # 27 days: still waiting
        W.set(plan.water.x, plan.water.y, z, LUA.table_from({"liquid": True, "depth": 5}))
        assert step().waiting and B.cistern_data().dry_since is None      # water back: the count starts again
        W.set(plan.water.x, plan.water.y, z, LUA.table_from({"liquid": False, "depth": 0}))
        step()
        LUA.execute("df.global.cur_year_tick = 56 * 1200")
        r = step()
        assert r.ok and r.retired and "dried up" in r.error, dict(r)
        assert B.cistern_data() is None and len(W.persist["ai-overseer/cistern/retired"]) == 1
        assert len(LUA.globals().PULLS) == 1 and gate.gate_flags.closed     # its floodgate shut
    finally:
        LUA.execute("df.global = nil")


@test("cistern (0.104.94): a source dry for a month retires the cistern, its floodgate shut; water back resets the count")
def _():
    B.CISTERN_HOLD = False                  # (0.104.144) the design under the hold
    try:
        _body()
    finally:
        B.CISTERN_HOLD = False


def _body():
    LUA.execute("""local W = ...
      W.citizens = {}
      for i = 1, 20 do table.insert(W.citizens, {x = 50 + i % 10, y = 60, z = 80}) end
      for x = 30, 90 do for y = 45, 75 do
        if not (x == 60 and y == 60) then W.set(x, y, 79, {shape = 'WALL', material = 'STONE'}) end
      end end
      for x = 74, 78 do for y = 55, 65 do W.set(x, y, 79, {shape = 'EMPTY', liquid = true, depth = 7}) end end
    """, W)
    plan = B.plan_cistern()
    plan = plan[0] if not hasattr(plan, "cistern") else plan
    z = plan.cistern.z
    for c in list(plan.tunnel_path.values()) + [plan.plug]:
        W.set(c.x, c.y, z, LUA.table_from({"shape": "FLOOR", "designated": False, "liquid": True, "depth": 7}))
    W.set(plan.well.x, plan.well.y, z, LUA.table_from({"shape": "FLOOR", "liquid": True, "depth": 5}))
    LUA.execute("BLD, LINKS, PULLS = {}, {}, {}")
    gate = LUA.globals().MKB(plan.floodgate.x, plan.floodgate.y, z, 1, LUA.table_from({"gate_flags": LUA.table_from({"closed": True})}))
    gate.built = True
    W.persist["ai-overseer/cistern"] = LUA.table_from({"stage": "filling", "plan": plan, "lever_id": 5, "gate_id": gate.id})
    LUA.execute("df = df or {}; df.global = {cur_year = 10, cur_year_tick = 0}")
    real_pending = B.lever_pull_pending
    B.lever_pull_pending = lambda i: False
    try:
        step = lambda: B.cistern_step(False)
        W.set(51, 60, 80, LUA.table_from({"liquid": True, "depth": 6}))       # a dwarf in deep water
        r = step()
        assert r.waiting and "in deep water now" in r.error, r.error
        W.set(51, 60, 80, LUA.table_from({"liquid": False, "depth": 0}))
        LUA.execute("df.global.cur_year_tick = 2 * 1200")
        r = step()
        assert r.waiting and "2 day(s) dry so far" in r.error and len(LUA.globals().PULLS) == 0, r.error
        LUA.execute("df.global.cur_year_tick = 3 * 1200")
        r = step()
        assert r.ok and r.reopened and len(LUA.globals().PULLS) == 1 and not gate.gate_flags.closed, dict(r)
        assert B.cistern_data().reopens == 1
        # three floods in a row: it stays shut
        gate.gate_flags.closed = True
        W.persist["ai-overseer/cistern"].reopens = 3
        r = step()
        assert r.waiting and "stays shut" in r.error, r.error
    finally:
        B.lever_pull_pending = real_pending
        LUA.execute("df.global = nil")


@test("cistern (0.104.100): a floodgate shut for a flood reopens after 3 days with nobody in deep water; not while wet")
def _():
    B.CISTERN_HOLD = False                  # (0.104.144) the design under the hold
    try:
        _body()
    finally:
        B.CISTERN_HOLD = False


@test("cistern hold (0.104.144): no new cistern and the floodgate never opened while the design is on hold")
def _():
    B.CISTERN_HOLD = True
    try:
        W.persist["ai-overseer/cistern"] = None
        r = B.cistern_step(False)
        assert not r.ok and r.held, dict(r)
    finally:
        B.CISTERN_HOLD = False


@test("cistern plan (0.104.94): a small surface pool is no source; a big one counts as further off than water underground")
def _():
    LUA.execute("""local W = ...
      W.citizens = {}
      for i = 1, 20 do table.insert(W.citizens, {x = 50 + i % 10, y = 60, z = 80}) end
      for x = 30, 90 do for y = 45, 75 do
        if not (x == 60 and y == 60) then W.set(x, y, 79, {shape = 'WALL', material = 'STONE'}) end
      end end
      for x = 74, 78 do for y = 55, 65 do W.set(x, y, 79, {shape = 'EMPTY', liquid = true, depth = 7, outside = true}) end end
    """, W)
    r = B.plan_cistern()
    assert r[0] is None and "surface water" in r[1], r                 # 55 tiles: too small outside


@test("cistern v2 (0.104.145): a source higher up comes in down a shaft to a tile diagonal to the room; sealed; never past a leak")
def _():
    LUA.execute("""local W = ...
      W.reset()
      W.citizens = {}
      for i = 1, 20 do table.insert(W.citizens, {x = 50 + i % 10, y = 60, z = 80}) end
      for x = 30, 90 do for y = 45, 75 do
        if not (x == 60 and y == 60) then W.set(x, y, 79, {shape = 'WALL', material = 'STONE'}) end
      end end
      -- a pond two levels deep north of the fort, its top a level over the fort's floor
      for x = 52, 64 do for y = 36, 44 do
        W.set(x, y, 81, {shape = 'EMPTY', liquid = true, depth = 7})
        W.set(x, y, 82, {shape = 'EMPTY', liquid = true, depth = 7})
      end end
    """, W)
    B.cistern_prefs(LUA.table_from({}))
    r = B.plan_cistern()
    plan, why = (r, None) if hasattr(r, "cistern") else (r[0], r[1])
    assert plan is not None, why
    assert plan.v == 2 and plan.shaft is not None and plan.intake_z == 81 and plan.cistern.z == 79, (plan.intake_z, plan.cistern.z)
    c, s, k = plan.cistern, plan.shaft, plan.corner
    assert abs(s.x - k.x) == 1 and abs(s.y - k.y) == 1                    # the shaft's foot is diagonal to the room
    assert c.x1 <= k.x <= c.x2 and c.y1 <= k.y <= c.y2                    # ... at its corner
    assert not (c.x1 <= s.x <= c.x2 and c.y1 <= s.y <= c.y2)
    assert plan.source == "underground pool" and plan.considered["underground pool"] == plan.score
    r = B.cistern_sealed(plan)
    assert r is True, r
    # a tile dug beside the shaft halfway up: not sealed, and it says where
    W.set(s.x + 1 if s.x + 1 != k.x else s.x - 1, s.y, 80, LUA.table_from({"shape": "FLOOR"}))
    ok, where, gaps = B.cistern_sealed(plan)
    assert not ok and "shaft is open" in where, where
    assert len(gaps) == 1 and gaps[1].fix == "wall", [dict(g) for g in gaps.values()]   # (0.104.168) every gap listed


def _shaft_plan():
    """(0.104.168) The v2 shaft plan of the test above (a pond north of the fort)."""
    LUA.execute("""local W = ...
      W.reset()
      W.citizens = {}
      for i = 1, 20 do table.insert(W.citizens, {x = 50 + i % 10, y = 60, z = 80}) end
      for x = 30, 90 do for y = 45, 75 do
        if not (x == 60 and y == 60) then W.set(x, y, 79, {shape = 'WALL', material = 'STONE'}) end
      end end
      for x = 52, 64 do for y = 36, 44 do
        W.set(x, y, 81, {shape = 'EMPTY', liquid = true, depth = 7})
        W.set(x, y, 82, {shape = 'EMPTY', liquid = true, depth = 7})
      end end
    """, W)
    B.cistern_prefs(LUA.table_from({}))
    r = B.plan_cistern()
    plan = r if hasattr(r, "cistern") else r[0]
    assert plan is not None and plan.shaft is not None
    s, k = plan.shaft, plan.corner
    # an open spot beside the shaft halfway up, away from the corner and the tunnel
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        gx, gy = s.x + dx, s.y + dy
        if (gx, gy) != (k.x, k.y) and W.get(gx, gy, 80).shape == "WALL" and W.get(gx + dx, gy + dy, 80).shape == "WALL":
            return plan, gx, gy, dx, dy
    raise AssertionError("no spot beside the shaft")


@test("cistern gaps (0.104.168): the AI walls up an open spot beside the shaft itself; then it is being built, not the player's")
def _():
    plan, gx, gy, dx, dy = _shaft_plan()
    W.set(gx, gy, 80, LUA.table_from({"shape": "FLOOR"}))
    d = LUA.table_from({"stage": "linking", "plan": plan})
    saved = []
    ok, where, gaps = B.cistern_sealed(plan)
    r = B.cistern_close_gaps(d, plan, gaps, True, lambda x: saved.append(1))
    assert r.ok and r.dry_run and r.walls == 1 and not W.placed[1] and not saved, dict(r)
    r = B.cistern_close_gaps(d, plan, gaps, False, lambda x: saved.append(1))
    walls = [c for c in W.placed.values() if c.mode == "build"]
    assert r.ok and r.sealing and r.walls == 1 and not r.needs_player, dict(r)
    assert [(c.x, c.y, c.z, c.text) for c in walls] == [(gx, gy, 80, "Cw")], [dict(c) for c in walls]
    assert d.sealing[f"{gx},{gy},80"] == "Cw" and saved and not d.unsealed_why
    # the construction placed: the next step waits on it (nothing placed twice)
    W.set(gx, gy, 80, LUA.table_from({"building": True}))
    r = B.cistern_close_gaps(d, plan, gaps, False, lambda x: None)
    assert r.waiting and not r.needs_player and "being built" in r.error, dict(r)
    assert len([c for c in W.placed.values() if c.mode == "build"]) == 1
    # built: closed
    W.set(gx, gy, 80, LUA.table_from({"shape": "WALL", "building": False}))
    assert B.cistern_sealed(plan) is True


@test("cistern gaps (0.104.168): never a wall that cuts a way, on a stair, in water or on someone; those stay the player's")
def _():
    plan, gx, gy, dx, dy = _shaft_plan()
    # a corridor one tile wide runs past the shaft (across it): walling it would cut it
    px, py = dy, dx                                  # across the line out from the shaft
    for i in range(-4, 5):
        W.set(gx + px * i, gy + py * i, 80, LUA.table_from({"shape": "FLOOR"}))
    ok, where, gaps = B.cistern_sealed(plan)
    assert not ok
    d = LUA.table_from({"stage": "linking", "plan": plan})
    r = B.cistern_close_gaps(d, plan, gaps, False, lambda x: None)
    assert not r.ok and r.needs_player and "cut a way" in r.unsealed_why, dict(r)
    assert d.unsealed_why and "cut a way" in d.unsealed_why
    # a stair beside the shaft: the player's
    plan, gx, gy, dx, dy = _shaft_plan()
    W.set(gx, gy, 80, LUA.table_from({"shape": "STAIR_UPDOWN"}))
    ok, where, gaps = B.cistern_sealed(plan)
    r = B.cistern_close_gaps(LUA.table_from({"stage": "linking"}), plan, gaps, False, lambda x: None)
    assert r.needs_player and "stair" in r.unsealed_why, dict(r)
    # water there: the player's
    W.set(gx, gy, 80, LUA.table_from({"shape": "FLOOR", "liquid": True, "depth": 3}))
    ok, where, gaps = B.cistern_sealed(plan)
    r = B.cistern_close_gaps(LUA.table_from({"stage": "linking"}), plan, gaps, False, lambda x: None)
    assert r.needs_player and "water" in r.unsealed_why, dict(r)
    # a dug hollow beyond the gap with a dwarf in it: wait (the wall would shut them in)
    W.set(gx, gy, 80, LUA.table_from({"shape": "FLOOR", "liquid": False, "depth": 0}))
    W.set(gx + dx, gy + dy, 80, LUA.table_from({"shape": "FLOOR"}))
    real = B.units_on_tiles
    B.units_on_tiles = lambda tiles, z: sum(1 for t in tiles.values() if (t.x, t.y) == (gx + dx, gy + dy))
    try:
        ok, where, gaps = B.cistern_sealed(plan)
        r = B.cistern_close_gaps(LUA.table_from({"stage": "linking"}), plan, gaps, False, lambda x: None)
        assert r.waiting and not r.needs_player and "hollow" in r.error, dict(r)
        assert not [c for c in W.placed.values() if c.mode == "build"]
    finally:
        B.units_on_tiles = real
    # nobody in it: walled
    ok, where, gaps = B.cistern_sealed(plan)
    r = B.cistern_close_gaps(LUA.table_from({"stage": "linking"}), plan, gaps, False, lambda x: None)
    assert r.ok and r.walls == 1, dict(r)


def _gaps(plan):
    ok, where, gaps = B.cistern_sealed(plan)
    assert not ok
    return gaps


def _unit_at(*spots):
    want = set(spots)
    return lambda tiles, z: sum(1 for t in tiles.values() if (t.x, t.y, z) in want)


@test("cistern gaps (0.104.168, review): open air is no way off a hollow, nor a way round the wall; unsure past the tiles looked at: the player's")
def _():
    plan, gx, gy, dx, dy = _shaft_plan()
    real = B.units_on_tiles
    try:
        # (b) a hollow beyond the gap with a channel (open air) in it and a dwarf: wait, not build
        W.set(gx, gy, 80, LUA.table_from({"shape": "FLOOR"}))
        W.set(gx + dx, gy + dy, 80, LUA.table_from({"shape": "FLOOR"}))
        W.set(gx + 2 * dx, gy + 2 * dy, 80, LUA.table_from({"shape": "EMPTY"}))
        B.units_on_tiles = _unit_at((gx + dx, gy + dy, 80))
        r = B.cistern_close_gaps(LUA.table_from({"stage": "linking"}), plan, _gaps(plan), False, lambda x: None)
        assert r.waiting and "hollow" in r.error and not [c for c in W.placed.values() if c.mode == "build"], dict(r)
        B.units_on_tiles = real
        # (c) two sides of a corridor joined only through open air: walling the gap cuts the way
        plan, gx, gy, dx, dy = _shaft_plan()
        px, py = dy, dx
        for i in (-1, 0, 1):
            W.set(gx + px * i, gy + py * i, 80, LUA.table_from({"shape": "FLOOR"}))
            W.set(gx + dx + px * i, gy + dy + py * i, 80, LUA.table_from({"shape": "EMPTY"}))
        for i in (-2, 2):                                  # the corridor goes on both ways
            W.set(gx + px * i, gy + py * i, 80, LUA.table_from({"shape": "FLOOR"}))
        r = B.cistern_close_gaps(LUA.table_from({"stage": "linking"}), plan, _gaps(plan), False, lambda x: None)
        assert r.needs_player and "cut a way" in r.unsealed_why, dict(r)
        # (a) more ground beyond than is looked at, no stair found: never assumed safe
        plan, gx, gy, dx, dy = _shaft_plan()
        W.set(gx, gy, 80, LUA.table_from({"shape": "FLOOR"}))
        for i in range(1, 7):
            W.set(gx + dx * i, gy + dy * i, 80, LUA.table_from({"shape": "FLOOR"}))
        B.CISTERN_GAP_POCKET_MAX = 3
        r = B.cistern_close_gaps(LUA.table_from({"stage": "linking"}), plan, _gaps(plan), False, lambda x: None)
        assert r.needs_player and "too much ground" in r.unsealed_why, dict(r)
        # ...a stair within the tiles looked at: a way off the level, no hollow: walled
        W.set(gx + dx * 2, gy + dy * 2, 80, LUA.table_from({"shape": "STAIR_UPDOWN"}))
        r = B.cistern_close_gaps(LUA.table_from({"stage": "linking"}), plan, _gaps(plan), False, lambda x: None)
        assert r.ok and r.walls == 1, dict(r)
    finally:
        B.units_on_tiles = real
        B.CISTERN_GAP_POCKET_MAX = 400


@test("cistern gaps (0.104.168, review): a dwarf gone into the hollow while the wall waits for a builder: the wall is taken back")
def _():
    plan, gx, gy, dx, dy = _shaft_plan()
    W.set(gx, gy, 80, LUA.table_from({"shape": "FLOOR"}))
    W.set(gx + dx, gy + dy, 80, LUA.table_from({"shape": "FLOOR"}))
    d = LUA.table_from({"stage": "linking", "plan": plan})
    r = B.cistern_close_gaps(d, plan, _gaps(plan), False, lambda x: None)
    assert r.ok and r.walls == 1, dict(r)
    W.set(gx, gy, 80, LUA.table_from({"building": True}))             # placed, not built yet
    real, real_cancel = B.units_on_tiles, B.cancel_construction
    cancelled = []
    try:
        B.cancel_construction = lambda x, y, z: cancelled.append((x, y, z)) or True
        r = B.cistern_close_gaps(d, plan, _gaps(plan), False, lambda x: None)
        assert r.waiting and "being built" in r.error and not cancelled, dict(r)      # nobody inside: it goes on
        B.units_on_tiles = _unit_at((gx + dx, gy + dy, 80))
        r = B.cistern_close_gaps(d, plan, _gaps(plan), False, lambda x: None)
        assert r.waiting and "taken back" in r.error and cancelled == [(gx, gy, 80)], dict(r)
        assert d.sealing[f"{gx},{gy},80"] is None
        B.units_on_tiles = _unit_at((gx, gy, 80))                         # only passing over the tile: kept
        cancelled.clear()
        r = B.cistern_close_gaps(d, plan, _gaps(plan), False, lambda x: None)
        assert not cancelled, dict(r)
    finally:
        B.units_on_tiles, B.cancel_construction = real, real_cancel


@test("cistern v2 (0.104.145): the AI weighs the sources: a cavern lake over a pond that freezes; a pond over caverns with a danger")
def _():
    LUA.execute("""local W = ...
      W.reset()
      W.citizens = {}
      for i = 1, 20 do table.insert(W.citizens, {x = 50 + i % 10, y = 60, z = 80}) end
      for x = 30, 90 do for y = 45, 75 do
        if not (x == 60 and y == 60) then W.set(x, y, 79, {shape = 'WALL', material = 'STONE'}) end
      end end
      -- a surface pond to the east, a cavern lake to the west, as far each
      for x = 82, 92 do for y = 54, 66 do W.set(x, y, 79, {shape = 'EMPTY', liquid = true, depth = 7, outside = true}) end end
      for x = 28, 38 do for y = 54, 66 do W.set(x, y, 79, {shape = 'EMPTY', liquid = true, depth = 7, feature = true}) end end
    """, W)
    B.cistern_prefs(LUA.table_from({"freezes": True}))
    r = B.plan_cistern()
    plan, why = (r, None) if hasattr(r, "cistern") else (r[0], r[1])
    assert plan is not None and plan.source == "cavern lake", (why, plan and plan.source)
    assert plan.considered["surface pool"] is not None
    B.cistern_prefs(LUA.table_from({"freezes": True, "cavern_danger": True}))
    r = B.plan_cistern()
    plan, why = (r, None) if hasattr(r, "cistern") else (r[0], r[1])
    assert plan is not None and plan.source == "surface pool", (why, plan and plan.source)
    B.cistern_prefs(LUA.table_from({}))


@test("cistern v2 (0.104.145): a cistern of the first design is retired (its gate shut first), the next planned afresh")
def _():
    LUA.execute("""local W = ...
      W.persist['ai-overseer/cistern'] = {stage = 'filling', plan = {cistern = {x1 = 1, y1 = 1, x2 = 5, y2 = 5, z = 79},
          well = {x = 3, y = 3, z = 80}, floodgate = {x = 6, y = 3}, plug = {x = 8, y = 3}, water = {x = 9, y = 3},
          tunnel_path = {{x = 6, y = 3}, {x = 7, y = 3}, {x = 8, y = 3}}, source = 'underground pool'}}
      W.persist['ai-overseer/cistern/retired'] = nil
    """, W)
    r = B.cistern_step(False)
    assert r.ok and r.retired, dict(r)
    assert B.cistern_data() is None
    assert len(W.persist["ai-overseer/cistern/retired"]) >= 1


@test("sand_zone (0.104.95): the nearest floor beside sand the dwarves reach; one zone only; none without sand")
def _():
    LUA.execute("""local W = ...
      W.citizens = {}
      for i = 1, 5 do table.insert(W.citizens, {x = 60 + i, y = 60, z = 80}) end
    """, W)
    real_sand, real_surf = B.sand_tile, B.surface_levels
    B.surface_levels = lambda area: LUA.table_from([])
    B.sand_tile = lambda x, y, z: False
    r = B.sand_zone(True)
    assert not r.ok and "no sand" in r.error, dict(r)
    B.sand_tile = lambda x, y, z: (x, y, z) == (70, 54, 80)          # a sand wall beside the fort's floor
    W.set(70, 54, 80, LUA.table_from({"shape": "WALL"}))
    r = B.sand_zone(True)
    assert r.ok and r.dry_run and abs(r.x - 70) <= 1 and abs(r.y - 54) <= 1, dict(r)
    r = B.sand_zone(False)
    assert r.ok and len(W.persist["ai-overseer/sand_zones"]) == 1, dict(r)
    r = B.sand_zone(False)
    assert not r.ok and "already" in r.error
    B.sand_tile, B.surface_levels = real_sand, real_surf


@test("water_zone (0.104.2): a 3x3 water source on liquid water with a bank the dwarves reach; ice and magma skipped")
def _():
    W.set(70, 58, 70, LUA.table_from({"shape": "EMPTY", "liquid": False}))                   # ice / gone
    W.set(72, 58, 70, LUA.table_from({"shape": "EMPTY", "liquid": True, "depth": 4, "magma": True}))
    W.set(74, 58, 70, LUA.table_from({"shape": "EMPTY", "liquid": True, "depth": 4}))        # banks: the fort floor
    pts = LUA.table_from([LUA.table_from({"x": x, "y": 58, "z": 70}) for x in (70, 72, 74)])
    r = B.water_zone(pts, True)
    assert r.ok and r.x == 74 and r.dry_run and not W.placed[1], dict(r)
    r = B.water_zone(pts, False)
    zs = [c for c in W.placed.values() if c.mode == "zone"]
    assert r.ok and len(zs) == 1 and zs[0].text == "w(3x3)" and (zs[0].x, zs[0].y) == (73, 57), (dict(r), [dict(z) for z in zs])
    assert B.water_zones()[1].x == 74
    # water nobody can reach: refused, saying why
    W.set(10, 10, 90, LUA.table_from({"shape": "EMPTY", "liquid": True, "depth": 5}))
    r = B.water_zone(LUA.table_from([LUA.table_from({"x": 10, "y": 10, "z": 90})]), True)
    assert not r.ok and "no bank" in r.error, dict(r)
    # a pond sunk below the ground: the bank is on the level above
    W.set(82, 60, 79, LUA.table_from({"shape": "EMPTY", "liquid": True, "depth": 3}))
    W.set(81, 60, 80, LUA.table_from({"shape": "FLOOR"}))
    r = B.water_zone(LUA.table_from([LUA.table_from({"x": 10, "y": 10, "z": 90}),
                                     LUA.table_from({"x": 82, "y": 60, "z": 79})]), True)
    assert r.ok and r.bank.above and r.x == 82, dict(r)
    # (0.105.5) Hammerstirred: the water around a point is tried too (the ice
    # at x70 has live water at x74 beside it, with a bank)
    r = B.water_zone(LUA.table_from([LUA.table_from({"x": 10, "y": 10, "z": 90}),
                                     LUA.table_from({"x": 70, "y": 58, "z": 70})]), True)
    assert r.ok and r.x == 74, dict(r)
    W.set(74, 58, 70, LUA.table_from({"liquid": False}))
    r = B.water_zone(LUA.table_from([LUA.table_from({"x": 10, "y": 10, "z": 90}),
                                     LUA.table_from({"x": 70, "y": 58, "z": 70})]), True)
    assert not r.ok and "no bank" in r.error and "frozen" in r.error, dict(r)     # every spot's reason


@test("plant_thread (0.104.11): a plant with a THREAD material gives thread; others don't")
def _():
    mk = lambda ids: LUA.table_from({"material": LUA.table_from([LUA.table_from({"id": i}) for i in ids])})
    assert B.plant_thread(mk(["STRUCTURAL", "THREAD", "SEED"])) is True
    assert B.plant_thread(mk(["STRUCTURAL", "DRINK"])) is False


@test("units_on_tiles (0.104.0): living creatures on the given tiles of one level only")
def _():
    LUA.execute("""
      df = df or {}
      df.global = df.global or {}
      df.global.world = df.global.world or {}
      df.global.world.units = {active = {
        {pos = {x = 1, y = 1, z = 5}, dead = false}, {pos = {x = 1, y = 1, z = 6}, dead = false},
        {pos = {x = 2, y = 1, z = 5}, dead = true}, {pos = {x = 9, y = 9, z = 5}, dead = false}}}
      dfhack.units = dfhack.units or {}
      dfhack.units.isDead = function(u) return u.dead end
    """)
    tiles = LUA.table_from([LUA.table_from({"x": 1, "y": 1}), LUA.table_from({"x": 2, "y": 1})])
    assert B.units_on_tiles(tiles, 5) == 1


@test("wells: in a dining hall first; never in a bedroom, on a building or a built floor")
def _():
    water_column(60, 58, 71)                                   # near the middle of the fort
    water_column(75, 62, 71)
    W.set(75, 62, 71, LUA.table_from({"zones": LUA.table_from(["DiningHall"])}))
    r = well(dry=True)
    assert r.ok and (r.x, r.y) == (75, 62) and r.in_hall, (r.x, r.y)
    W.set(75, 62, 71, LUA.table_from({"zones": LUA.table_from(["Bedroom"])}))
    W.set(60, 58, 71, LUA.table_from({"taken": True}))
    r = well(dry=True)
    assert not r.ok, (r.x, r.y)
    W.set(60, 58, 71, LUA.table_from({"taken": False, "material": "CONSTRUCTION"}))
    r = well(dry=True)
    assert not r.ok, (r.x, r.y)


def pond(x1=70, y1=48, x2=73, y2=51, z=79, **extra):
    """A pond on the surface (z 80): water on the level below, ground round it."""
    for x in range(64, 80):
        for y in range(42, 55):
            W.set(x, y, 80, LUA.table_from({"shape": "FLOOR", "material": "SOIL", "outside": True}))
    for x in range(x1, x2 + 1):
        for y in range(y1, y2 + 1):
            W.set(x, y, 80, LUA.table_from({"shape": "EMPTY", "outside": True}))
            W.set(x, y, z, LUA.table_from({"shape": "FLOOR", "material": "POOL", "liquid": True, "depth": 7,
                                           "outside": True, **extra}))


@test("wells: no water under the fort: a well on a pond's bank, away from the fort below")
def _():
    pond()
    r = well(dry=True)
    assert r.ok and r.shore and r.elevation == 80 and r.drop == 1, (r.ok, r.error)
    assert 46 <= r.y <= 53 and 68 <= r.x <= 75, (r.x, r.y)
    assert r.y <= 52, "not the south bank: the fort is dug out one level down there"
    r = well()
    assert r.ok and r.project_id, r.error


@test("wells on the shore: never salt water; stagnant only if nothing better; never beside open ground below")
def _():
    pond(salt=True)
    assert not well(dry=True).ok
    W.reset()
    pond(stagnant=True)
    r = well(dry=True)
    assert r.ok and r.stagnant, r.error
    W.reset()
    pond()
    for x in range(64, 80):
        for y in range(42, 48):
            W.set(x, y, 79, LUA.table_from({"shape": "FLOOR"}))     # a cave or tunnel north of it, one level down
    r = well(dry=True)
    assert not r.ok or r.y >= 50, (r.x, r.y)


@test("wells: if the game won't put a well over the dug hole, the project ends and says so")
def _():
    water_column(70, 58, 71)
    r = well()
    LUA.eval("function(W) local t = W.get(70, 58, 71); t.designated = false; t.shape = 'EMPTY' end")(W)
    real = LUA.globals().reqscript("quickfort").apply_blueprint
    LUA.globals().reqscript("quickfort").apply_blueprint = LUA.eval(
        "function(real) return function(p) local s = real(p); if p.mode == 'build' then s.build_designated.value = 0 end; return s end end")(real)
    try:
        f = B.furnish_project(r.project_id, True)
    finally:
        LUA.globals().reqscript("quickfort").apply_blueprint = real
    assert not f.ok and "would not place the well" in f.error, f.error
    assert len(B.projects_report().open) == 0


# --- pastures ------------------------------------------------------------------------

def pasture(tiles, dry=False):
    return B.make_pasture(params(tiles=tiles), dry)


def grass(x1, y1, x2, y2, z, material="GRASS_LIGHT", **extra):
    for x in range(x1, x2 + 1):
        for y in range(y1, y2 + 1):
            W.set(x, y, z, LUA.table_from({"shape": "FLOOR", "material": material, "outside": True, **extra}))


def zones_made():
    return [c for c in W.placed.values() if c.mode == "zone"]


@test("pastures: a zone on living grass near the top of the stairs, sized for the herd")
def _():
    grass(66, 50, 80, 64, 80)                          # beside the stairs' top (60,60,80)
    r = pasture(40)
    assert r.ok and r.tiles >= 40, (r.ok, r.error, r.tiles)
    z = zones_made()
    assert z and all(str(c.text).startswith('n{name="AI pasture"}(') for c in z), [c.text for c in z]
    assert len(z) == 1, [c.text for c in z]           # one zone: a herd grazes in one pasture
    for c in z:
        assert 63 <= c.x <= 80 and 50 <= c.y <= 64 and c.z == 80
        assert max(abs(c.x - 60), abs(c.y - 60)) > 3, "keeps the way in clear"
    assert r.tiles < 40 + 15, r.tiles                  # not much bigger than asked


@test("pastures: one zone with enough grass for the hungriest animal, not patches that add up (0.38's 60 zones)")
def _():
    # grass in 4x4 patches split by rock: no single zone can hold 40 grass
    for x0 in (66, 72, 78):
        grass(x0, 50, x0 + 3, 53, 80)
    r = pasture(40)
    assert not r.ok and not zones_made(), (r.ok, [c.text for c in zones_made()])
    W.reset()
    grass(66, 50, 80, 64, 80)
    grass(70, 54, 72, 56, 80, material="SOIL")          # bare ground inside is fine: animals walk it
    r = pasture(100)
    assert r.ok and len(zones_made()) == 1 and r.zones[1].w >= 10, (r.error, [c.text for c in zones_made()])


@test("pastures: no room for the whole herd in one: zones that each feed an animal")
def _():
    grass(66, 50, 72, 56, 80)                          # 49 grass
    grass(66, 66, 72, 72, 80)                          # 49 more, apart
    r = pasture(90)
    assert r.ok and len(zones_made()) == 2, (r.error, [c.text for c in zones_made()])


@test("outside things: a refuse pile and a depot on open ground near the way in, never right at it")
def _():
    for x in range(45, 80):
        for y in range(45, 80):
            if (x, y) != (60, 60):
                W.set(x, y, 80, LUA.table_from({"shape": "FLOOR", "material": "SOIL", "outside": True}))
    r = B.place_surface("refuse", True)
    assert r.ok and r.dry_run, r.error
    assert not (r.x - 6 < 60 < r.x + 5 + 6 and r.y - 6 < 60 < r.y + 5 + 6), (r.x, r.y)
    d = B.place_surface("depot", False)
    assert d.ok and any(c.text == "D" and c.mode == "build" for c in W.placed.values()), d.error
    W.reset()
    assert not B.place_surface("refuse", True).ok                     # nowhere open outside


@test("pastures: never on dead grass, water, buildings or zones, or grass the dwarves can't walk to")
def _():
    grass(66, 50, 75, 59, 80, material="GRASS_DEAD")
    assert not pasture(20).ok
    for bad in ({"liquid": True}, {"taken": True}, {"feature": True}):
        W.reset()
        grass(66, 50, 75, 59, 80, **bad)
        r = pasture(20)
        assert not r.ok and not zones_made(), bad
    W.reset()
    grass(66, 50, 75, 59, 85)                          # off in the hills: not walkable from the fort
    r = pasture(20)
    assert not r.ok and "no living grass" in r.error, r.error


@test("pastures: the nearest grass first; a dry run changes nothing")
def _():
    grass(90, 50, 100, 60, 80)                         # far
    grass(66, 55, 72, 64, 80)                          # near
    r = pasture(20, dry=True)
    assert r.ok and r.dry_run and not zones_made(), r.error
    assert all(zn.x < 80 for zn in r.zones.values()), [(zn.x, zn.y) for zn in r.zones.values()]


# --- the master plan (placement hints) ---------------------------------------------

def plan(**kw):
    return LUA.table_from({k: LUA.table_from(v) if isinstance(v, (list, dict)) else v for k, v in kw.items()})


def planned(pl=None, dry=True, **kw):
    p = params(**(kw or {"kind": "bedrooms", "rooms": 8, "room_size": 3}))
    if pl is not None:
        p["plan"] = pl
    return B.start_project(p, LUA.table_from({"year": 148, "tick": 100}), dry)


def site_of(r):
    return (r.z, r.anchor.x, r.anchor.y, r.extends_stairs)


@test("plan: a level in the band is chosen first, though a nearer level outside it is free")
def _():
    base = planned()
    assert base.ok and base.z == 65 and base.in_district is None, (base.z, base.in_district)
    assert (base.stair.x, base.stair.y) == (60, 60)
    W.reset()
    r = planned(plan(elev_lo=61, elev_hi=62, elev_target=61))
    assert r.ok and r.z == 61 and r.in_district is True, (r.ok, r.z, r.in_district, r.error)
    W.reset()
    r = planned(plan(elev_lo=61, elev_hi=63))                    # no target: the middle (62) first
    assert r.ok and r.z == 62 and r.in_district is True, (r.z, r.in_district)


@test("plan: a band just below the spine's bottom is tried first, extending the spine a little")
def _():
    r = planned(plan(elev_lo=55, elev_hi=57, spine={"x": 60, "y": 60}))
    # 56 (the target) is more than PLAN_EXTEND below the bottom: the band's nearest allowed level
    assert r.ok and r.z == 57 and r.extends_stairs and r.in_district is True, (r.z, r.extends_stairs, r.error)


@test("plan: without the spine, or deeper than a few levels, the band pass never extends stairs")
def _():
    base = planned()
    W.reset()
    r = planned(plan(elev_lo=55, elev_hi=57))                         # no spine named
    assert r.ok and site_of(r) == site_of(base) and r.in_district is False, (site_of(r), site_of(base))
    W.reset()
    r = planned(plan(elev_lo=40, elev_hi=42, spine={"x": 60, "y": 60}))   # far below the bottom
    assert r.ok and site_of(r) == site_of(base) and r.in_district is False, (site_of(r), site_of(base))


@test("plan: no room in the band -> the ordinary search finds the same site as without a plan")
def _():
    base = planned()
    for band in ((74, 76), (90, 95), (-50, -40)):
        W.reset()
        r = planned(plan(elev_lo=band[0], elev_hi=band[1]))
        assert r.ok and site_of(r) == site_of(base) and r.in_district is False, (band, site_of(r), r.in_district)
    W.reset()
    B.TRY_BESIDE = True
    base = planned()
    W.reset()
    r = planned(plan(elev_lo=90, elev_hi=95))
    assert r.ok and site_of(r) == site_of(base) and r.in_district is False, (site_of(r), site_of(base))


@test("plan: the preferred direction is tried first (north = y-1)", beside=True)
def _():
    base = planned(plan(elev_lo=72, elev_hi=72))
    assert base.ok and base.z == 72 and base.anchor.y > 60, (base.z, base.anchor.y)   # south by default
    W.reset()
    r = planned(plan(elev_lo=72, elev_hi=72, dirs=["north"]))
    assert r.ok and r.z == 72 and r.anchor.y < 60 and r.in_district, (r.z, r.anchor.y)
    order = [(d.x, d.y) for d in B.plan_dirs(plan(elev_lo=0, elev_hi=0, dirs=["west", "north"])).values()]
    assert order == [(-1, 0), (0, -1), (0, 1), (1, 0)], order


def second_stair(x, y, z1, z2, citizens=0):
    for z in range(z1, z2 + 1):
        shape = "STAIR_UP" if z == z1 else ("STAIR_DOWN" if z == z2 else "STAIR_UPDOWN")
        W.set(x, y, z, LUA.table_from({"shape": shape}))
    for i in range(citizens):
        LUA.globals().table.insert(W.citizens, LUA.table_from({"x": x, "y": y, "z": z1 + 1 + i % 3}))


@test("plan: the spine staircase goes first; the others stay as the fallback")
def _():
    second_stair(15, 100, 70, 74, citizens=3)
    stairs = B.find_stairs(5)
    assert stairs[1].x == 60 and stairs[2].x == 15
    out = B.spine_first(stairs, plan(elev_lo=0, elev_hi=0, spine={"x": 15, "y": 100}), None)
    assert [(s.x, s.y) for s in out.values()] == [(15, 100), (60, 60)]
    r = planned(plan(elev_lo=70, elev_hi=74, spine={"x": 15, "y": 100}))
    assert r.ok and (r.stair.x, r.stair.y) == (15, 100) and r.in_district, (r.stair.x, r.stair.y, r.error)
    out = B.spine_first(stairs, plan(elev_lo=70, elev_hi=74, spine={"x": 99, "y": 99}), None)
    assert [(s.x, s.y) for s in out.values()] == [(60, 60), (15, 100)]      # no stairs there: unchanged


@test("plan: a spine staircase find_stairs didn't list is found and used (if the dwarves can walk to it)")
def _():
    second_stair(30, 95, 70, 74)                          # outside the area around the dwarves
    assert all(s.x != 30 for s in B.find_stairs(5).values())
    r = planned(plan(elev_lo=71, elev_hi=73, spine={"x": 30, "y": 95}))
    assert r.ok and (r.stair.x, r.stair.y) == (30, 95) and 71 <= r.z <= 73 and r.in_district, \
        (r.stair.x, r.stair.y, r.z, r.error)
    W.reset()
    second_stair(30, 95, 84, 88)                          # not walkable from the fort (fake: z 60-80 only)
    r = planned(plan(elev_lo=84, elev_hi=88, spine={"x": 30, "y": 95}))
    assert r.ok and (r.stair.x, r.stair.y) == (60, 60) and r.in_district is False, (r.stair.x, r.error)


@test("plan: saved with the project; the registry shows the district and whether it was met")
def _():
    r = planned(plan(elev_lo=61, elev_hi=62, district="Deep Halls"), dry=False)
    assert r.ok and r.project_id and r.in_district is True and (r.stair.x, r.stair.y) == (60, 60), r.error
    s = planned(dry=False, kind="dining", tables=8)
    assert s.ok and s.in_district is None
    reg = list(B.registry_report().values())
    assert reg[0].district == "Deep Halls" and reg[0].in_district is True, (reg[0].district, reg[0].in_district)
    assert reg[1].district is None and reg[1].in_district is None
    saved = W.persist["ai-overseer/projects"].list[1]
    assert saved.plan.elev_lo == 61 and saved.in_district is True


@test("plan: the band pass never uses up the whole time limit", beside=True)
def _():
    B.SEARCH_SECONDS = 0
    try:
        r = planned(plan(elev_lo=61, elev_hi=62))
    finally:
        B.SEARCH_SECONDS = 4
    assert not r.ok and "time limit" in r.error, r.error
    assert designated_count() == 0


# --- 4b: corridor grammar (avenue width, dog-legs, doors) ----------------------------

CORRIDOR_TILES = r"""function(W, LAYOUTS, i)
  -- the saved project's new corridor tiles in map coordinates (not the level itself)
  local p = W.persist['ai-overseer/projects'].list[i or 1]
  local L = LAYOUTS.make(p.kind, p.params)
  local all = LAYOUTS.tiles_from_dig(p.cells.dig)
  local out = {}
  for x, col in pairs(all) do for y in pairs(col) do
    if not (L.tiles[x] and L.tiles[x][y]) and not (x == 0 and y == 0) then
      out[#out + 1] = {p.anchor.x + x, p.anchor.y + y}
    end
  end end
  return out
end"""


def corridor_tiles(i=1):
    return {(int(t[1]), int(t[2])) for t in
            LUA.eval(CORRIDOR_TILES)(W, LUA.globals().LAYOUTS, i).values()}


def grammar(dry=False, style=None, **kw):
    p = params(kind="bedrooms", rooms=4, room_size=3)
    p["plan"] = plan(elev_lo=72, elev_hi=72, **kw)
    if style is not None:
        p["style"] = LUA.table_from(style)
    return B.start_project(p, LUA.table_from({"year": 148, "tick": 100}), dry)


@test("avenue: width 1 (and straight, doored) is exactly today's corridor", beside=True)
def _():
    base = grammar()
    assert base.ok and base.z == 72, base.error
    tiles0 = corridor_tiles()
    W.reset(); B.TRY_BESIDE = True
    r = grammar(avenue=1, corridors="straight", doors="doored")
    assert r.ok and site_of(r) == site_of(base) and r.tiles == base.tiles, (site_of(r), site_of(base))
    assert corridor_tiles() == tiles0 and r.corridor == base.corridor
    assert B.plan_grammar(plan(elev_lo=0, elev_hi=0, avenue=1, doors="doored")) is None


@test("avenue: width 3 digs a 3-wide corridor with 1-wide doorways at its ends; width 2 one extra row", beside=True)
def _():
    base = grammar()
    one = corridor_tiles()
    W.reset(); B.TRY_BESIDE = True
    r = grammar(avenue=3)
    assert r.ok and r.z == 72, r.error
    three = corridor_tiles()
    n = len(one)
    inner = n - 2                                     # the first and last tiles stay 1 wide (doorways)
    assert n >= 3 and len(three) == n + 2 * inner and r.tiles == base.tiles + 2 * inner, (len(three), n, r.tiles)
    ys = sorted({y for _, y in one})
    want = {(60, ys[0]), (60, ys[-1])} | {(x, y) for x in (59, 60, 61) for y in ys[1:-1]}
    assert want == three, sorted(three)               # straight south from 60,60
    assert all(W.get(x, y, 72).designated for x, y in three)
    LUA.eval(AREA_CHECK)(W, 72)
    W.reset(); B.TRY_BESIDE = True
    r = grammar(avenue=2)
    two = corridor_tiles()
    assert r.ok and len(two) == n + inner and {x for x, _ in two} == {59, 60}, sorted(two)   # +perp of south = west
    # a 3-wide avenue that would graze water is refused there and goes elsewhere
    W.reset(); B.TRY_BESIDE = True
    base = grammar()
    one = corridor_tiles()
    W.reset(); B.TRY_BESIDE = True
    for y in range(64, 80):
        W.set(58, y, 72, LUA.table_from({"aquifer": True}))     # the wide corridor's border
    r = grammar(avenue=3)
    assert r.ok, r.error
    assert not (r.z == 72 and r.anchor.y > 60), (r.z, sorted(corridor_tiles()))   # not south any more
    assert not any(abs(x - 58) <= 1 and 63 <= y <= 80 for x, y in corridor_tiles())
    LUA.eval(AREA_CHECK)(W, r.z)


@test("dog-leg: half way the corridor steps 2 tiles sideways; a jog into an aquifer is refused", beside=True)
def _():
    sp = {"spacing": 100}                                  # corridors of 10+ tiles
    straight = grammar(style=sp)
    assert straight.ok and straight.z == 72 and straight.anchor.x == 60, (straight.error, straight.anchor.x)
    st = corridor_tiles()
    assert {x for x, _ in st} == {60}
    W.reset(); B.TRY_BESIDE = True
    r = grammar(style=sp, corridors="dog-leg")
    assert r.ok and r.z == 72, r.error
    dl = corridor_tiles()
    assert len(dl) == len(st) + 2 and {x for x, _ in dl} == {58, 59, 60}, sorted(dl)   # +perp of south = west
    jog = sorted(t for t in dl if t[0] in (58, 59))
    ys = sorted(y for x, y in dl if x == 60)
    assert jog[0][1] == ys[-1] and (59, ys[-1]) in dl and (58, ys[-1]) in dl     # the 2 sideways tiles
    assert len(ys) == (len(st)) // 2 and r.anchor.x == 58 and r.anchor.y == straight.anchor.y
    assert r.corridor == straight.corridor + 2
    LUA.eval(AREA_CHECK)(W, 72)
    # aquifer beside the westward jog: the eastward one is chosen instead
    W.reset(); B.TRY_BESIDE = True
    for y in range(69, 72):
        W.set(57, y, 72, LUA.table_from({"aquifer": True}))
    r = grammar(style=sp, corridors="dog-leg")
    assert r.ok and r.z == 72 and r.anchor.x == 62, (r.error, r.z, r.anchor.x)
    assert {x for x, _ in corridor_tiles()} == {60, 61, 62}
    LUA.eval(AREA_CHECK)(W, 72)
    # open space where the eastward jog would go too: neither, the level goes elsewhere
    W.reset(); B.TRY_BESIDE = True
    for y in range(69, 72):
        W.set(57, y, 72, LUA.table_from({"aquifer": True}))
        W.set(63, y, 72, LUA.table_from({"shape": "FLOOR"}))
    r = grammar(style=sp, corridors="dog-leg")
    assert r.ok and not (r.z == 72 and r.anchor.x in (58, 62) and r.anchor.y > 60), (r.z, r.anchor.x)
    LUA.eval(AREA_CHECK)(W, r.z)
    # corridors under 4 new tiles stay straight
    B.MAX_CORRIDOR = 3
    try:
        W.reset(); B.TRY_BESIDE = True
        short = grammar()
        tiles = corridor_tiles()
        W.reset(); B.TRY_BESIDE = True
        r = grammar(corridors="dog-leg")
    finally:
        B.MAX_CORRIDOR = 25
    assert short.ok and r.ok and site_of(r) == site_of(short) and corridor_tiles() == tiles, \
        (site_of(r), site_of(short))
    assert len({x for x, _ in tiles}) <= 1


@test("doors: fortified puts a door at both ends of the corridor; open puts none", beside=True)
def _():
    plain = grammar(dry=True)
    W.reset(); B.TRY_BESIDE = True
    styled_door = grammar(dry=True, style={"entry_door": True})
    assert styled_door.furniture.Door == plain.furniture.Door + 1
    W.reset(); B.TRY_BESIDE = True
    r = grammar(doors="fortified")
    assert r.ok and r.corridor >= 2, (r.error, r.corridor)
    saved = W.persist["ai-overseer/projects"].list[1]
    assert saved.furniture.Door == plain.furniture.Door + 2
    layout_doors = plain.furniture.Door
    corr = corridor_tiles()
    doors = {(saved.anchor.x + c.x, saved.anchor.y + c.y) for c in saved.cells.build.values() if c.text == "d"}
    on_corridor = sorted(doors & corr)
    assert len(doors) == layout_doors + 2 and len(on_corridor) == 2, on_corridor
    ys = sorted(y for _, y in corr)
    assert {y for _, y in on_corridor} == {ys[0], ys[-1]}, (on_corridor, ys)        # both ends
    LUA.globals().LAYOUTS.to_data(saved.cells.build, 0)                           # no two on one tile
    W.reset(); B.TRY_BESIDE = True
    r = grammar(dry=True, doors="open", style={"entry_door": True})
    assert r.ok and r.furniture.Door == plain.furniture.Door, (r.furniture.Door, plain.furniture.Door)
    # a 3-wide avenue keeps 1-wide doorways at its ends, so a fortified fort still gets both doors
    W.reset(); B.TRY_BESIDE = True
    r = grammar(dry=True, doors="fortified", avenue=3)
    assert r.ok and r.furniture.Door == plain.furniture.Door + 2, r.furniture.Door


@test("avenue: a wide corridor may brush a hall (the same open space) but never a room past its door")
def _():
    LAY = LUA.globals().LAYOUTS
    saved_below = B.MAX_LEVELS_BELOW
    for kind, kp, o, av in (("dining", {"tables": 20}, 0, 3), ("bedrooms", {"rooms": 8, "room_size": 3}, 2, 2),
                            ("bedrooms", {"rooms": 8, "room_size": 3}, 0, 3)):
        W.reset(); B.TRY_BESIDE = True; B.MAX_LEVELS_BELOW = 0
        pp = dict(kp); pp["style"] = LUA.table_from({"spacing": 60, "orient": o})
        res = LAY.make(kind, LUA.table_from(pp)); L = res[0] if isinstance(res, tuple) else res
        st = LUA.table_from([LUA.table_from({"x": 60, "y": 60, "z_top": 72, "z_bottom": 72, "citizen_z": 72,
                                              "len": 0, "count": 1})])
        r = B.choose_site(L, st, LUA.table(), plan(elev_lo=72, elev_hi=72, avenue=av))
        site = r[0] if isinstance(r, tuple) else r
        assert site and site.in_district, (kind, o, av, r[1] if isinstance(r, tuple) else None)
        # no corridor tile (but the doorway at the end) is next to a room tile outside the halls
        halls = [(h.x, h.y, h.w, h.h) for h in L.halls.values()]
        def in_hall(x, y):
            return any(hx <= x < hx + hw and hy <= y < hy + hh for hx, hy, hw, hh in halls)
        rooms = {(x, y) for x, col in L.tiles.items() for y in col.keys()
                 if not in_hall(x, y) and not (abs(x) <= 1 and abs(y) <= 1)}
        for x, col in site.extra.items():
            for y in col.keys():
                if x == 0 or y == 0:
                    continue                                   # the corridor's own line, ending at the entry
                touching = {(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)} & rooms
                assert not touching, (kind, o, av, (x, y), sorted(touching))
    B.MAX_LEVELS_BELOW = saved_below


@test("orientation: a turned level is found, dug and checked like any other", beside=True)
def _():
    for o in range(4):
        W.reset(); B.TRY_BESIDE = True
        r = styled(kind="bedrooms", rooms=6, room_size=3, style={"orient": o})
        assert r.ok, (o, r.error)
        LUA.eval(AREA_CHECK)(W, r.z)
        n = sum(1 for t in W.tiles.values() if t.designated)
        assert n == r.tiles, (o, n, r.tiles)

@test("survey: staircases, the busiest level and soil levels, as elevations; changes nothing")
def _():
    W.soil_levels[63] = True
    W.soil_levels[50] = True
    s = B.survey()
    assert s.ok and s.elevation_offset == 0 and s.citizen_elevation == 72, (s.citizen_elevation,)
    st = s.stairs[1]
    assert (st.x, st.y, st.z_top, st.z_bottom, st.elev_top, st.elev_bottom) == (60, 60, 80, 60, 80, 60)
    assert st.count >= 1 and list(s.soil.values()) == [50, 63], list(s.soil.values())
    assert designated_count() == 0 and len(W.calls) == 0
    W.reset()
    s = B.survey()
    assert s.ok and s.soil is None and s.soil_error is None          # no soil: the key is left out
    W.citizens = LUA.table()
    s = B.survey()
    assert s.ok and s.stairs is None and s.stairs_error == "no citizens" and s.citizen_error == "no citizens"


def fresh_embark(aquifer_z=None):
    """A new embark: grass at z80 open to the sky, soil z79-78, rock from z77; no stairs."""
    W.reset()
    LUA.execute("""local W = ...
      W.tiles = {}
      W.soil_levels = {[79] = true, [78] = true}
      for x = 30, 70 do for y = 30, 70 do W.set(x, y, 80, {shape = 'FLOOR', outside = true, material = 'GRASS_LIGHT'}) end end
      W.citizens = {}
      for i = 1, 7 do table.insert(W.citizens, {x = 48 + i, y = 50, z = 80}) end""", W)
    if aquifer_z is not None:
        LUA.execute("""local W, z = ...
          for x = 20, 80 do for y = 20, 80 do W.set(x, y, z, {aquifer = true}) end end""", W, aquifer_z)


@test("founding: a fresh embark gets its first stair shaft near the dwarves, down through the soil to rock")
def _():
    fresh_embark()
    assert B.find_stairs(1)[0] is None                               # (nil, why)
    r = B.found_fort(True)
    assert r.ok and r.dry_run and r.levels == 3 and r.rock and r.z == 80, dict(r)
    assert abs(r.x - 52) <= 8 and abs(r.y - 50) <= 8, (r.x, r.y)
    assert designated_count() == 0                                   # a dry run designates nothing
    r = B.found_fort(False)
    assert r.ok and not r.dry_run, dict(r)
    shaft = [(z, W.get(r.x, r.y, z).designated) for z in (80, 79, 78, 77)]
    assert all(d for _, d in shaft), shaft                           # j, i, i, u down to the first rock level
    assert not W.get(r.x, r.y, 76).designated
    again = B.found_fort(False)                                      # not dug yet: no second shaft
    assert again.rejected and again.waiting and "waiting for the miners" in again.error, dict(again)


@test("founding (review): never beside water a level down (digging opens the shaft's sides)")
def _():
    fresh_embark()
    LUA.execute("""local W = ...
      for x = 20, 80 do for y = 20, 80 do
        if (x + y) % 2 == 0 then W.set(x, y, 79, {liquid = true}) end
      end end""", W)
    r = B.found_fort(True)
    assert not r.ok and "water or magma" in r.error, dict(r)


@test("founding (review): a dug shaft is found even with the dwarves moved away: no second one")
def _():
    fresh_embark()
    r = B.found_fort(False)
    LUA.execute("""local W, x, y = ...
      W.set(x, y, 80, {shape = 'STAIR_DOWN', designated = false})
      for z = 79, 78 do W.set(x, y, z, {shape = 'STAIR_UPDOWN', designated = false}) end
      W.set(x, y, 77, {shape = 'STAIR_UP', designated = false})
      W.citizens = {}
      for i = 1, 7 do table.insert(W.citizens, {x = 40 + i, y = 70, z = 80}) end""", W, r.x, r.y)
    again = B.found_fort(False)
    assert again.rejected and "already has a staircase" in again.error, dict(again)


@test("founding: never into an aquifer; the reason says what was found; refused once stairs exist")
def _():
    fresh_embark(aquifer_z=78)
    r = B.found_fort(False)
    assert not r.ok and "aquifer below" in r.error and designated_count() == 0, dict(r)
    W.reset()                                                        # the usual fort: it has stairs
    r = B.found_fort(False)
    assert r.rejected and "already has a staircase" in r.error, dict(r)



@test("outside things: trees in the way are marked for felling and the spot kept; placed once they're down")
def _():
    trees = set()
    for x in range(45, 80):
        for y in range(45, 80):
            if (x, y) == (60, 60):
                continue
            if x % 4 == 0 and y % 4 == 0:              # a tree every 4 tiles: no clear 5x5 anywhere
                W.set(x, y, 80, LUA.table_from({"shape": "WALL", "material": "TREE", "outside": True}))
                trees.add((x, y))
            else:
                W.set(x, y, 80, LUA.table_from({"shape": "BOULDER" if (x + y) % 7 == 0 else "FLOOR",
                                                "material": "SOIL", "outside": True}))
    felled = []
    B.fell_tree = lambda x, y, z: felled.append((x, y)) or True
    assert B.find_surface_rect(5, 5, 4, LUA.table_from([]), LUA.table_from({"FLOOR": True, "BOULDER": True}))[0] is None
    d = B.place_surface("depot", False)
    assert d.ok and d.clearing and d.trees >= 1 and not any(c.mode == "build" for c in W.placed.values()), dict(d)
    assert len(felled) == d.trees and all(f in trees for f in felled), felled
    st = B.clearing_status()
    assert st.depot == d.trees, dict(st)
    w = B.place_surface("depot", False)                          # trees still standing: wait, re-mark
    assert not w.ok and w.waiting and "still felling" in w.error, dict(w)
    for (x, y) in set(felled):
        W.set(x, y, 80, LUA.table_from({"shape": "FLOOR", "material": "SOIL"}))
    assert B.clearing_status().depot == 0
    r = B.place_surface("depot", False)
    assert r.ok and not r.clearing and (r.x, r.y) == (d.x, d.y), dict(r)
    assert any(c.text == "D" and c.mode == "build" for c in W.placed.values())
    assert B.clearing_status().depot is None                     # the spot is forgotten


@test("pastures: trees, boulders and slopes may lie inside a pasture (a zone may cover any seen tile)")
def _():
    grass(66, 50, 80, 64, 80)
    for x in range(66, 81, 3):
        for y in range(50, 65, 3):
            W.set(x, y, 80, LUA.table_from({"shape": "WALL", "material": "TREE"}))
    W.set(70, 55, 80, LUA.table_from({"shape": "BOULDER"}))
    W.set(71, 55, 80, LUA.table_from({"shape": "RAMP"}))
    r = pasture(80)
    assert r.ok and len(zones_made()) == 1, (r.error, [c.text for c in zones_made()])
    W.reset()
    grass(66, 50, 80, 64, 80, hidden=True)                        # never on tiles not yet seen
    assert not pasture(20).ok


@test("polish: the dining hall before bedrooms; smoothed, then engraved two weeks on; one level at a time")
def _():
    pick = B.polish_pick
    mk = lambda pid, kind, phase="done", pol=None: LUA.table_from(
        {"id": pid, "kind": kind, "phase": phase, **({"polish": LUA.table_from(pol)} if pol else {})})
    lst = LUA.table_from([mk(1, "bedrooms"), mk(2, "dining"), mk(3, "workshops"), mk(4, "tavern", "furnish")])
    p, what = pick(lst, 10000)
    assert p.id == 2 and what == "smooth", (p.id, what)
    lst = LUA.table_from([mk(1, "bedrooms"), mk(2, "dining", pol={"step": "smooth", "at": 10000})])
    p, why = pick(lst, 10000 + 5 * 1200)
    assert p is None and "being smoothed" in why, (p, why)
    p, what = pick(lst, 10000 + 15 * 1200)
    assert p.id == 2 and what == "engrave", (p.id, what)
    lst = LUA.table_from([mk(1, "bedrooms", pol={"step": "engraved", "at": 1}), mk(3, "workshops")])
    p, why = pick(lst, 99999)
    assert p is None and why is None


@test("polish: smoothing designated over the level's dug tiles, recorded, then engraving")
def _():
    r = start(kind="dining", tables=8)
    assert r.ok, r.error
    data = B.load_projects()
    data.list[1].phase = "done"
    B.save_projects(data)
    B.now_tick = LUA.eval("function() return 5000 end")
    d = B.polish_next(True)
    assert d.ok and d.dry_run and d.step == "smooth" and d.tiles > 10, dict(d)
    x = B.polish_next(False)
    assert x.ok and x.step == "smooth", dict(x)
    assert B.load_projects().list[1].polish.step == "smooth"
    w = B.polish_next(False)
    assert not w.ok and w.waiting, dict(w)
    B.now_tick = LUA.eval("function() return 5000 + 15 * 1200 end")
    e = B.polish_next(False)
    assert e.ok and e.step == "engrave", dict(e)
    assert B.load_projects().list[1].polish.step == "engraved"

@test("feeder stockpile: the nearest free 3x3 two tiles or more from the workshop, on free floor only")
def _():
    r = B.feeder_rect(50, 59, 52, 61, 70, 3, 3, False, 6)
    assert r, "no spot"
    gx = max(50 - (r.x + 2), r.x - 52, 0)
    gy = max(59 - (r.y + 2), r.y - 61, 0)
    assert max(gx, gy) == 2, (r.x, r.y)                                   # a tile of space left
    for y in range(r.y, r.y + 3):
        for x in range(r.x, r.x + 3):
            W.set(x, y, 70, LUA.table_from({"building": True}))
    r2 = B.feeder_rect(50, 59, 52, 61, 70, 3, 3, False, 6)
    assert r2 and (r2.x, r2.y) != (r.x, r.y), "took a tile with a building"
    assert not B.feeder_rect(60, 70, 62, 72, 90, 3, 3, False, 6)           # all wall around: nothing


@test("the keep: a ring of walls with a door round the way in, trees felled first, then a roof, then done")
def _():
    for x in range(40, 81):
        for y in range(40, 81):
            if (x, y) != (60, 60):
                W.set(x, y, 80, LUA.table_from({"shape": "FLOOR", "material": "SOIL", "outside": True}))
            W.set(x, y, 81, LUA.table_from({"shape": "EMPTY", "outside": True}))
    W.set(64, 58, 80, LUA.table_from({"shape": "WALL", "material": "TREE", "outside": True}))   # in the r=4 ring
    felled = []
    B.fell_tree = lambda x, y, z: felled.append((x, y)) or True
    d = B.place_keep(True)
    assert d.ok and d.clearing and d.dry_run and not felled, dict(d)
    c = B.place_keep(False)
    assert c.ok and c.stage == "clearing" and c.r == 4 and felled == [(64, 58)], dict(c)
    w = B.place_keep(False)
    assert not w.ok and w.waiting and "felling" in w.error, dict(w)
    W.set(64, 58, 80, LUA.table_from({"shape": "FLOOR", "material": "SOIL"}))
    r = B.place_keep(False)
    assert r.ok and r.stage == "walls", dict(r)
    built = [c for c in W.placed.values() if c.mode == "build"]
    walls = [c for c in built if c.text == "Cw"]
    doors = [c for c in built if c.text == "d"]
    assert len(walls) == 31 and len(doors) == 1 and all(max(abs(c.x - 60), abs(c.y - 60)) == 4 for c in built), \
        (len(walls), len(doors))
    for c in walls:                                       # planned: the game shows a building there
        W.set(c.x, c.y, 80, LUA.table_from({"building": True}))
    st = B.keep_status()
    assert st.stage == "walls" and st.walls_planned == 31, dict(st)
    assert B.place_keep(False).waiting
    for c in walls:                                       # built
        W.set(c.x, c.y, 80, LUA.table_from({"shape": "WALL", "material": "CONSTRUCTION", "building": False}))
    W.placed = LUA.table_from([])
    f = B.place_keep(False)
    assert f.ok and f.stage == "roof" and f.roof == 49, dict(f)
    assert all(c.text == "Cf" and c.z == 81 and max(abs(c.x - 60), abs(c.y - 60)) <= 3 for c in W.placed.values())
    for c in list(W.placed.values()):
        W.set(c.x, c.y, 81, LUA.table_from({"shape": "FLOOR", "material": "CONSTRUCTION"}))
    e = B.place_keep(False)
    assert e.ok and e.stage == "done", dict(e)
    assert B.place_keep(False).done and B.keep_status().stage == "done"


@test("the keep: never round a spot with water or a zone in the ring, nor with nothing outside")
def _():
    assert not B.place_keep(True).ok                       # underground only: no open ring
    for x in range(40, 81):
        for y in range(40, 81):
            if (x, y) != (60, 60):
                W.set(x, y, 80, LUA.table_from({"shape": "FLOOR", "material": "SOIL", "outside": True}))
    for r in (4, 5, 6):
        W.set(60 + r, 60, 80, LUA.table_from({"liquid": True}))
    r = B.place_keep(True)
    assert not r.ok, dict(r)


@test("the keep (0.104.0): never while the trade depot is underground (the wagons come in through the way in)")
def _():
    for x in range(40, 81):
        for y in range(40, 81):
            if (x, y) != (60, 60):
                W.set(x, y, 80, LUA.table_from({"shape": "FLOOR", "material": "SOIL", "outside": True}))
            W.set(x, y, 81, LUA.table_from({"shape": "EMPTY", "outside": True}))
    W.set(30, 30, 70, LUA.table_from({"shape": "FLOOR"}))                 # under the ground
    LUA.execute("""
      df = df or {}
      df.global = df.global or {}
      df.global.world = df.global.world or {}
      df.global.world.buildings = {other = {TRADE_DEPOT = {{x1 = 29, x2 = 31, y1 = 29, y2 = 31, z = 70}}}}
    """)
    real = B.find_keep_court
    B.find_keep_court = LUA.eval("function() return nil, 'no court' end")
    try:
        r = B.place_keep(True)
        assert not r.ok and "underground" in r.error, dict(r)
    finally:
        B.find_keep_court = real
    # (0.105.23) a court away from the way in leaves the wagons' road alone: it may go up
    r = B.place_keep(True)
    assert r.ok and r.court and max(abs(r.x - 60), abs(r.y - 60)) > r.r + 3, dict(r)
    W.set(30, 30, 70, LUA.table_from({"outside": True}))                  # a depot outside: the keep may go up
    r = B.place_keep(True)
    assert r.ok and not r.court, dict(r)
    LUA.execute("df.global.world.buildings = {other = {TRADE_DEPOT = {}}}")


def _slope():
    """(0.105.23) F's site: the way in (the stair at 60,60, z80) inside the
    mountain (the fort's floors round it are under a roof: no ring), open
    flat ground under the sky two levels down, east of x85."""
    for x in range(85, 116):
        for y in range(40, 81):
            W.set(x, y, 78, LUA.table_from({"shape": "FLOOR", "material": "SOIL", "outside": True}))
            W.set(x, y, 79, LUA.table_from({"shape": "EMPTY", "outside": True}))


@test("the keep (0.105.23): no ring round the way in (a slope) -> a court on the open flat ground below, walls and a door")
def _():
    _slope()
    site, why = B.find_keep_ring(B.pasture_anchors())
    assert site is None and "no ring of open ground" in why, why
    d = B.place_keep(True)
    assert d.ok and d.dry_run and d.court and d.stage == "walls", dict(d)
    # the nearest the way in, the hillside's rock (x84, y39) two of its walls
    assert (d.x, d.y, d.elevation, d.r) == (88, 43, 78, 4), dict(d)
    r = B.place_keep(False)
    assert r.ok and r.court and r.stage == "walls", dict(r)
    built = [c for c in W.placed.values() if c.mode == "build"]
    assert len([c for c in built if c.text == "d"]) == 1 and len(built) == 15, len(built)
    assert all(c.z == 78 and max(abs(c.x - 88), abs(c.y - 43)) == 4 and c.x > 84 and c.y > 39 for c in built)
    st = B.keep_status()
    assert st.court and st.stage == "walls", dict(st)


@test("the keep (0.105.23): the court goes by the surface farm plots, never over them")
def _():
    _slope()
    for x in range(103, 108):
        for y in range(68, 73):
            W.set(x, y, 78, LUA.table_from({"building": True}))          # the plot
    real = B.surface_farm_spots
    B.surface_farm_spots = LUA.eval("function() return {{x = 105, y = 70, z = 78}} end")
    try:
        d = B.place_keep(True)
    finally:
        B.surface_farm_spots = real
    assert d.ok and d.court, dict(d)
    assert max(abs(d.x - 105), abs(d.y - 70)) <= 10, dict(d)              # by the fields, not by the slope (x89)
    assert not (abs(d.x - 105) <= d.r + 2 and abs(d.y - 70) <= d.r + 2), dict(d)   # its square clear of the plot


@test("the keep (0.105.23): no court on ground the dwarves can't walk to, nor with sky closed above; says why")
def _():
    _slope()
    real = B.walk_group
    B.walk_group = LUA.eval("function(x, y, z) if z == 78 then return 2 end return 1 end")
    try:
        r = B.place_keep(True)
    finally:
        B.walk_group = real
    assert not r.ok and "no ring of open ground" in r.error and "open, flat ground" in r.error, dict(r)
    for x in range(85, 116):
        for y in range(40, 81):
            W.set(x, y, 79, LUA.table_from({"shape": "FLOOR"}))           # an overhang: not open sky
    r = B.place_keep(True)
    assert not r.ok, dict(r)


@test("levels (0.105.23): max_elev keeps every new level under it (the Deep mine); none found says so")
def _():
    r = B.start_project(params(kind="bedrooms", rooms=8, room_size=3), LUA.table(), True)
    assert r.ok and r.z == 65, dict(r)
    r = B.start_project(params(kind="bedrooms", rooms=8, room_size=3, max_elev=62), LUA.table(), True)
    assert r.ok and r.z <= 62, dict(r)
    r = B.start_project(params(kind="bedrooms", rooms=8, room_size=3, max_elev=0), LUA.table(), True)
    assert not r.ok and "under the surface only" in r.error, dict(r)


@test("extra workshops: all but one soap maker's taken down, the idle ones, at work kept first")
def _():
    LUA.execute("""
      local function shop(id, jobs, code)
        local b = {id = id, type = 99, jobs = jobs or {}, code = code or 'SOAP_MAKER',
                   getType = function() return 1 end}
        b.custom_type = b
        return b
      end
      DOWN = {}
      SHOPS = {shop(5), shop(3), shop(9, {{}}), shop(7), shop(8, nil, 'OTHER')}
      df = {building_type = {Workshop = 1}, workshop_type = {[99] = 'Custom'},
            building_def = {find = function(b) return {code = b.code} end},
            global = {world = {buildings = {other = {WORKSHOP_ANY = SHOPS}}}}}
      dfhack.buildings = {deconstruct = function(b) table.insert(DOWN, b.id) end}
    """)
    r = B.remove_workshops("SoapMaker", 1, 20, False)
    assert r.ok and r.had == 4 and r.removed == 3, dict(r)
    down = sorted(LUA.globals().DOWN.values())
    assert down == [3, 5, 7], down                                       # 9 is at work: kept
    assert not B.remove_workshops("SoapMaker", 4, 20, True).ok



@test("furniture into a zone (0.88): a traction bench on a free floor beside a wall, never by a door")
def _():
    # a 5x3 room at z 70: walls round it, a bed at (12,20), a door in the west wall at (9,21)
    for x in range(9, 16):
        for y in range(19, 24):
            W.set(x, y, 70, LUA.table_from({"shape": "WALL"}))
    for x in range(10, 15):
        for y in range(20, 23):
            W.set(x, y, 70, LUA.table_from({"shape": "FLOOR"}))
    W.set(12, 20, 70, LUA.table_from({"shape": "FLOOR", "building": True}))
    W.set(9, 21, 70, LUA.table_from({"shape": "FLOOR", "building": True}))
    LUA.execute("""local B = ...
        B.zone_area = function(id) if id ~= 355 then return nil end
            return {x1 = 10, y1 = 20, x2 = 14, y2 = 22, z = 70, has = function() return true end} end
        B.door_at = function(x, y, z) return x == 9 and y == 21 end""", B)
    spots = B.zone_spots(B.zone_area(355))
    xy = [(sp.x, sp.y) for sp in spots.values()]
    assert (12, 20) not in xy and (10, 21) not in xy and (12, 21) not in xy, xy    # the bed, by the door, the middle
    assert xy[0] == (11, 20), xy                                                  # one wall beside it, first
    d = B.place_in_zone(355, "traction_bench", True)
    assert d.ok and d.dry_run and (d.x, d.y) == (11, 20) and len(W.placed) == 0, dict(d)
    r = B.place_in_zone(355, "traction_bench", False)
    assert r.ok and W.placed[1].text == "R" and (W.placed[1].x, W.placed[1].y) == (11, 20), dict(r)
    assert not B.place_in_zone(999, "traction_bench", False).ok
    assert not B.place_in_zone(355, "throne", False).ok


@test("furniture into a zone (0.104.68): every tile by the walls taken -> the open floor in the middle")
def _():
    # a 5x5 room at z 71; every floor tile touching a wall has something on it
    for x in range(19, 26):
        for y in range(19, 26):
            W.set(x, y, 71, LUA.table_from({"shape": "WALL"}))
    for x in range(20, 25):
        for y in range(20, 25):
            edge = x in (20, 24) or y in (20, 24)
            W.set(x, y, 71, LUA.table_from({"shape": "FLOOR", "items": edge or None}))
    LUA.execute("""local B = ...
        B.zone_area = function(id) if id ~= 356 then return nil end
            return {x1 = 20, y1 = 20, x2 = 24, y2 = 24, z = 71, has = function() return true end} end
        B.door_at = function() return false end""", B)
    xy = [(sp.x, sp.y) for sp in B.zone_spots(B.zone_area(356)).values()]
    assert xy and all(21 <= x <= 23 and 21 <= y <= 23 for x, y in xy), xy
    assert B.place_in_zone(356, "chest", True).ok


@test("pair chairs (0.104.77): a chair beside each lone chair, beside a table where it can, never by a door")
def _():
    # a 7x3 tavern at z 72: tables at (21,30) (24,30), chairs on their inner side at (21,31) (24,31)
    for x in range(19, 28):
        for y in range(29, 34):
            W.set(x, y, 72, LUA.table_from({"shape": "WALL"}))
    for x in range(20, 27):
        for y in range(30, 33):
            W.set(x, y, 72, LUA.table_from({"shape": "FLOOR"}))
    for xy in ((21, 30), (24, 30), (21, 31), (24, 31)):
        W.set(xy[0], xy[1], 72, LUA.table_from({"shape": "FLOOR", "building": True}))
    LUA.execute("""local B = ...
        B.zone_area = function(id) if id ~= 357 then return nil end
            return {x1 = 20, y1 = 30, x2 = 26, y2 = 32, z = 72, has = function() return true end} end
        B.door_at = function() return false end
        B.building_kind_at = function(x, y, z)
            if z ~= 72 then return nil end
            if (x == 21 or x == 24) and y == 30 then return 'Table' end
            if (x == 21 or x == 24) and y == 31 then return 'Chair' end
            return nil end""", B)
    r = B.pair_chairs(357, False, 5)
    assert r.ok and r.lone == 2 and r.placed == 2, dict(r)
    spots = sorted((r.spots[i][1], r.spots[i][2]) for i in range(1, r.placed + 1))
    # each new chair beside its lone chair and beside a table: (20,31)/(22,31) and (23,31)/(25,31)
    assert all(abs(x - cx) == 1 and y == 31 for (x, y), cx in zip(spots, (21, 24))), spots
    assert not B.pair_chairs(999, False, 5).ok


@test("a temple asked for by a petition (0.89): the location quickfort made is dedicated to the deity")
def _():
    LUA.execute("""
        local B = ...
        local function enum(names) local e = {} for i, n in pairs(names) do e[i] = n; e[n] = i end return e end
        _G.df = _G.df or {}
        df.abstract_building_type = enum({[0] = 'INN_TAVERN', [1] = 'TEMPLE'})
        df.religious_practice_type = enum({[-1] = 'NONE', [0] = 'WORSHIP_HFID', [1] = 'RELIGION_ENID'})
        local tav = {id = 3, getType = function() return 0 end}
        LOC = {id = 4, deity_type = -1, deity_data = {}, getType = function() return 1 end}
        dfhack.world = {getCurrentSite = function() return {buildings = {tav, LOC}} end}
        dfhack.buildings = {findCivzonesAt = function(pos)
            if pos.x == 12 and pos.y == 17 and pos.z == 70 then return {{location_id = 4}} end
            return {} end}
    """, B)
    p = LUA.eval("{kind = 'temple', z = 70, anchor = {x = 10, y = 20}, cells = {zone = {{x = 2, y = -3, text = 'm'}}}}")
    assert B.dedicate_temple(p, LUA.eval("{deity_hf = 55}")) == 4
    loc = LUA.globals().LOC
    assert loc.deity_type == 0 and loc.deity_data.Deity == 55
    assert B.dedicate_temple(p, LUA.eval("{deity_hf = 56}")) is False      # already dedicated: left alone


@test("retarget a hall being dug (0.92): its zone and params change; not once its zone stands")
def _():
    r = B.start_project(params(kind="temple", size="grand", profession="METALSMITH"),
                        LUA.table_from({"year": 148, "tick": 100}))
    assert r.ok, dict(r)
    pid = r.project_id
    d = B.retarget_hall(pid, LUA.eval("{profession = 'FARMER'}"), True)
    assert d.ok and d.dry_run and "farmer" in d.zone
    r2 = B.retarget_hall(pid, LUA.eval("{profession = 'FARMER'}"), False)
    assert r2.ok, dict(r2)
    rep = B.projects_report()
    o = [x for x in rep.open.values() if x.id == pid][0]
    assert o.dedication.profession == "FARMER", dict(o.dedication)
    assert not B.retarget_hall(pid, LUA.eval("{}"), False).ok
    assert not B.retarget_hall(999, LUA.eval("{profession = 'FARMER'}"), False).ok


@test("storage survey (0.100): bolts are their own kind; loose ones and those waiting in a workshop count")
def _():
    LUA.execute("""
      SAVED_DF, SAVED_MAPS, SAVED_ITEMS = rawget(_G, 'df'), dfhack.maps, dfhack.items
      local shop = {getType = function() return 1 end}
      local function bolt(x, ground, held)
        return {x = x, held = held, flags = {on_ground = ground, in_building = held}}
      end
      df = {building_type = {Workshop = 1},
            global = {world = {buildings = {other = {STOCKPILE = {}}},
                               items = {other = {AMMO = {bolt(1, true), bolt(2, true), bolt(3, false, true)}}}}}}
      dfhack.maps = {getTileFlags = function() return {pile = false}, {} end}
      dfhack.items = {getPosition = function(it) return it.x, 1, 1 end,
                      getHolderBuilding = function(it) return it.held and shop or nil end}
    """)
    try:
        r = B.storage_survey()
    finally:
        LUA.execute("df, dfhack.maps, dfhack.items = SAVED_DF, SAVED_MAPS, SAVED_ITEMS")
    assert r.ammo.loose == 3 and r.ammo.in_workshops == 1 and r.weapons.loose == 0, (r.ammo.loose, r.weapons.loose)


@test("crossings (0.101): the survey finds the fort's side, the shortest crossing over water and what lies over it; a bridge placed; only the AI's taken down")
def _():
    W.reset()
    L = lupa_eval = LUA.eval
    LUA.execute(r"""
    local B, W = ...
    -- a surface at z 90: the fort's side x 0..49, a river x 50..52 (3 wide), the far side x 53..119
    for x = 0, 119 do for y = 0, 119 do
      local t = {shape = 'FLOOR', material = 'GRASS_LIGHT', liquid = false}
      if x >= 50 and x <= 52 then t = {shape = 'FLOOR', material = 'RIVER', liquid = true, depth = 7} end
      if x >= 70 and x <= 80 and y >= 40 and y <= 60 then t.shape = 'SHRUB' end
      if x >= 60 and x <= 65 and y >= 40 and y <= 50 then t = {shape = 'WALL', material = 'TREE'} end
      W.set(x, y, 90, t)
    end end
    B.cross_tile = function(x, y, z)
      local t = W.get(x, y, z); if not t then return nil end
      return t.shape, t.material, t.liquid == true and not t.magma, t.liquid == true
    end
    B.pasture_anchors = function() return {{x = 40, y = 50, z = 89}} end   -- the stair's top, under the hatch
    B.elevation_offset = function() return -50 end
    BLD = {}
    dfhack.buildings = {findAtTile = function(p) return BLD[p.x .. ',' .. p.y .. ',' .. p.z] end}
    """, B, W)
    r = B.crossings_report()
    assert not r["none"], dict(r)
    near = r["near"]
    assert near["tiles"] > 1000 and near["shrubs"] == 0, dict(near)
    c = r["crossings"][1]
    assert c["len"] == 3 and c["dir"] == "e" and c["x"] == 50, dict(c)
    far = c["far_side"]
    assert far["shrubs"] > 50 and far["trees"] > 0, dict(far)
    assert c["width"] == 3, c["width"]                         # parallel crossings side by side
    # build it: checked again, placed with quickfort as a bridge, recorded
    out = B.build_crossing(c["x"], c["y"], 90, "e", 3, 1, "cheap", 1000, False)
    assert out["ok"] and out["w"] == 3 and out["h"] == 1, dict(out)
    placed = [W.placed[i] for i in range(1, len(W.placed) + 1)]
    assert any(p["mode"] == "build" and p["text"] == "gx(3x1)" for p in placed), [dict(p) for p in placed]
    assert len(W.persist["ai-overseer/crossings"]["list"]) == 1
    bad = B.build_crossing(c["x"], c["y"], 90, "e", 2, 1, "cheap", 1000, False)   # too short: no far bank
    assert not bad["ok"] and "far side" in bad["error"], dict(bad)
    # remove: the AI's own only, and not when something else stands there now
    LUA.execute("local B = ...; BLD['50,50,90'] = {getType = function() return 99 end}", B)
    LUA.execute("df = df or {}; df.building_type = {Bridge = 1}")
    no = B.remove_crossing(1, False)
    assert not no["ok"] and "something else" in no["error"], dict(no)
    assert not B.remove_crossing(5, False)["ok"]

# --- (0.105.5) farm crops: DF's own test for a plot, and set_farm_crops ---------------
# Hammerstirred (2 Nov): plots fallow all year; the forts' seeds were mostly
# underground crops and the surface plots' menu offered only "Leave fallow".
FARM_FAKE = r"""
local B = ...
local ALL = {'SPRING', 'SUMMER', 'AUTUMN', 'WINTER'}
local function raw(idx, id, opts)
    -- like DF's flag set: a flag it knows and isn't set reads false
    local f = setmetatable({SEED = opts.seed ~= false}, {__index = function() return false end})
    for _, s in ipairs(opts.seasons or ALL) do f[s] = true end
    if opts.under then f.BIOME_SUBTERRANEAN_WATER = true end
    for _, b in ipairs(opts.biomes or {}) do f['BIOME_' .. b] = true end
    local mats = {}
    if opts.brews then table.insert(mats, {id = 'STRUCTURAL', reaction_product = {id = {'DRINK_MAT'}}}) end
    if opts.thread then table.insert(mats, {id = 'THREAD', reaction_product = {id = {}}}) end
    return {id = id, name = id:lower(), flags = f, material = mats}
end
local SURF = {'FOREST_TEMPERATE_BROADLEAF', 'GRASSLAND_TEMPERATE'}
local RAWS = {
  [1] = raw(1, 'MUSHROOM_HELMET_PLUMP', {under = true, brews = true}),
  [2] = raw(2, 'GRASS_WHEAT_CAVE', {under = true, brews = true}),
  [3] = raw(3, 'BUSH_QUARRY', {under = true}),
  [4] = raw(4, 'GRASS_TAIL_PIG', {under = true, brews = true, thread = true}),
  [5] = raw(5, 'BERRIES_PRICKLE', {brews = true, biomes = SURF}),
  [6] = raw(6, 'BERRIES_STRAW_WILD', {brews = true, biomes = SURF, seasons = {'SPRING'}}),
  [7] = raw(7, 'HEMP', {thread = true, biomes = SURF}),
  [8] = raw(8, 'BERRIES_FISHER', {biomes = SURF}),
}
local FF = {}
local function seed(idx, n) return {flags = {}, getMaterialIndex = function() return idx end,
                                    getStackSize = function() return n end} end
local function plot(id, under, x)
    return {id = id, centerx = x, centery = 5, z = 10, x1 = x, x2 = x + 2, y1 = 5, y2 = 6,
            plant_id = {[0] = -1, -1, -1, -1}, flags = {exists = true}, under = under,
            getType = function() return 7 end}
end
function FF.setup(seeds, plots, tick)
    df = {plant_raw = {find = function(i) return RAWS[i] end}, building_type = {FarmPlot = 7},
          global = {cur_year_tick = tick or 100800 + 50, world = {items = {other = {SEEDS = {}, PLANT = {}}},
                    buildings = {all = {}}}}}
    for _, s in ipairs(seeds) do table.insert(df.global.world.items.other.SEEDS, seed(s[1], s[2])) end
    for _, p in ipairs(plots) do table.insert(df.global.world.buildings.all, plot(p[1], p[2], p[3])) end
    B.plot_place = function(x, y, z)
        for _, b in ipairs(df.global.world.buildings.all) do
            if b.centerx == x then return {under = b.under, biome = (not b.under) and 'FOREST_TEMPERATE_BROADLEAF' or nil} end
        end
        return {under = true}
    end
    return df.global.world.buildings.all
end
FF.RAWS = RAWS
return FF
"""
FF = LUA.execute(FARM_FAKE, B)


def farm_setup(seeds, plots, tick=None):
    return FF.setup(LUA.table_from([LUA.table_from(x) for x in seeds]),
                    LUA.table_from([LUA.table_from(x) for x in plots]), tick)


def crops_of(b):
    return [FF.RAWS[b.plant_id[k]].id if b.plant_id[k] >= 0 else "" for k in range(4)]


@test("farm crops (0.105.5): seasons and underground read from the raws, as DF's plot menu does")
def _():
    farm_setup([], [])
    R = FF.RAWS
    assert B.crop_underground(R[1]) and not B.crop_underground(R[5])
    assert B.crop_in_season(R[6], 0) and not B.crop_in_season(R[6], 1)
    under, surf = LUA.table_from({"under": True}), LUA.table_from({"under": False, "biome": "FOREST_TEMPERATE_BROADLEAF"})
    assert B.crop_grows_on(R[1], under) and not B.crop_grows_on(R[1], surf)      # plump helmet: underground only
    assert B.crop_grows_on(R[5], surf) and not B.crop_grows_on(R[5], under)      # prickle berry: surface only
    assert not B.crop_grows_on(R[5], LUA.table_from({"under": False, "biome": "TUNDRA"}))   # not its biome
    rep = B.farms_report()
    assert rep.plots == 0


@test("farm crops (0.105.5): fort B: surface plots, underground seeds plus surface brewables, drink short -> surface brewables")
def _():
    plots = farm_setup([[1, 60], [2, 30], [3, 20], [4, 10], [5, 30], [6, 9], [7, 5]],
                       [[11, False, 0], [12, False, 10], [13, False, 20]])
    lst = B.farm_plot_list(B.seed_stock(), 1)
    assert all(p.fallow and p.options > 0 and not p.dead for p in lst.values()), [dict(p) for p in lst.values()]
    r = B.set_farm_crops(LUA.table_from({"drink": True}), False)
    assert r.ok and r.changed > 0, dict(r)
    for b in plots.values():
        cs = crops_of(b)
        assert cs[1] == "BERRIES_PRICKLE", cs                    # summer: the brewable surface crop in season
        assert cs[0] in ("BERRIES_PRICKLE", "BERRIES_STRAW_WILD"), cs   # spring: a brewable one
        assert not any(c in ("MUSHROOM_HELMET_PLUMP", "GRASS_WHEAT_CAVE", "BUSH_QUARRY", "GRASS_TAIL_PIG") for c in cs), cs
    assert W.persist["ai-overseer/farm_crops"].ai is True


@test("farm crops (0.105.6): fort A: 7 plump helmet seeds for 3 underground plots; every plot sown this season")
def _():
    # spring (tick 0 is spring in the fake? use the fake's default tick, whatever season it is)
    plots = farm_setup([[1, 7]], [[41, True, 0], [42, True, 10], [43, True, 20]])
    r = B.set_farm_crops(LUA.table_from({"drink": True}), False)
    assert r.ok, dict(r)
    season = B.current_season()
    bare = [b.id for b in plots.values() if b.plant_id[season] < 0]
    assert not bare, bare                                    # none left fallow for want of leftover seeds
    again = B.set_farm_crops(LUA.table_from({"drink": True}), False)
    assert again.changed == 0, dict(again)                   # a second call changes nothing (no daily churn)


@test("farm crops (0.105.5): underground plots get underground crops, brewable first; a dead surface plot is said")
def _():
    plots = farm_setup([[1, 60], [3, 20], [4, 10]], [[21, True, 0], [22, False, 10]])
    lst = B.farm_plot_list(B.seed_stock(), 1)
    by = {p.id: p for p in lst.values()}
    assert by[22].dead and not by[21].dead, [dict(p) for p in lst.values()]
    r = B.set_farm_crops(LUA.table_from({"drink": True}), False)
    assert r.ok and r.dead == 1, dict(r)
    under = [b for b in plots.values() if b.id == 21][0]
    surf = [b for b in plots.values() if b.id == 22][0]
    assert crops_of(under)[1] in ("MUSHROOM_HELMET_PLUMP", "GRASS_TAIL_PIG"), crops_of(under)
    assert crops_of(surf) == ["", "", "", ""]
    # nothing at all grows anywhere: refused, saying why
    farm_setup([[1, 60]], [[31, False, 0]])
    r = B.set_farm_crops(LUA.table_from({}), False)
    assert not r.ok and "underground" in r.error, dict(r)


@test("farm crops (0.105.5): the player's crop that grows there is kept; one that can't grow is replaced; dry run changes nothing")
def _():
    plots = farm_setup([[5, 8], [8, 20], [1, 30]], [[41, False, 0], [42, False, 10]])
    p41 = [b for b in plots.values() if b.id == 41][0]
    p42 = [b for b in plots.values() if b.id == 42][0]
    p41.plant_id[1] = 8          # the player's fisher berry (grows there): kept, even with drink short
    p42.plant_id[1] = 1          # a plump helmet on the surface: can't grow, replaced
    r = B.set_farm_crops(LUA.table_from({"drink": True}), True)
    assert r.ok and r.dry_run and p42.plant_id[1] == 1, dict(r)
    r = B.set_farm_crops(LUA.table_from({"drink": True}), False)
    assert r.ok and r.kept >= 1, dict(r)
    assert crops_of(p41)[1] == "BERRIES_FISHER" and crops_of(p42)[1] == "BERRIES_PRICKLE", (crops_of(p41), crops_of(p42))
    # the AI's own crop is changed again when drink turns short and it doesn't brew
    b = list(farm_setup([[5, 8], [8, 20]], [[51, False, 0]]).values())[0]
    B.set_farm_crops(LUA.table_from({"drink": False}), False)
    first = crops_of(b)[1]
    B.set_farm_crops(LUA.table_from({"drink": True}), False)
    assert crops_of(b)[1] == "BERRIES_PRICKLE", (first, crops_of(b))


@test("farm crops review (0.105.7) SHOULD 3: a crop whose seeds ran out isn't fine: the plot moves to a crop with seeds")
def _():
    plots = farm_setup([[5, 0], [8, 20]], [[61, False, 0]])
    b = list(plots.values())[0]
    b.plant_id[1] = 5                      # prickle berry set, its seeds all sown
    lst = B.farm_plot_list(B.seed_stock(), 1)
    p = list(lst.values())[0]
    assert not p.ok_now and p.no_seeds and p.options == 1, dict(p)
    r = B.set_farm_crops(LUA.table_from({"drink": True}), False)
    assert r.ok and crops_of(b)[1] == "BERRIES_FISHER", (dict(r), crops_of(b))
    # nothing else has seeds: the crop stays (better than fallow when seeds come in)
    plots = farm_setup([[5, 0]], [[62, False, 0]])
    b = list(plots.values())[0]
    b.plant_id[1] = 5
    B.set_farm_crops(LUA.table_from({}), False)
    assert crops_of(b)[1] == "BERRIES_PRICKLE"


@test("farms review (0.105.7) SHOULD 5: underground plots only where DF's subterranean flag reads true")
def _():
    soil_floor(42, 56, 47, 59, 71)                     # flag unreadable (nil): not taken for underground
    r = B.farm_plots(params(tiles=20, underground=True), LUA.table_from({"year": 148, "tick": 100}), True)
    assert r.tiles == 0, (r.ok, r.tiles)
    soil_floor(42, 56, 47, 59, 71, subterranean=True)
    r = B.farm_plots(params(tiles=20, underground=True), LUA.table_from({"year": 148, "tick": 100}), True)
    assert r.ok and r.tiles >= 20, (r.ok, r.tiles, r.error)


# --- (0.105.23, 14.1 step 4c) the Deep mine's trade depot underground ---------------

def _deep_ground():
    """Open ground under the sky at z80 round the fort (its own floors at
    x40-80 y55-65 stay inside); the way in is the stair's top (60,60,80)."""
    LUA.eval("""function(W)
      for x = 20, 100 do for y = 20, 100 do
        local t = W.get(x, y, 80)
        if t.shape == 'WALL' then W.set(x, y, 80, {shape='FLOOR', material='SOIL', outside=true}) end
        W.set(x, y, 81, {shape='EMPTY', outside=true})
      end end
    end""")(W)


def _deep_reset():
    LUA.execute("df = df or {}; df.global = {cur_year = 150, cur_year_tick = 0, "
                "world = {buildings = {other = {TRADE_DEPOT = {}}}}}")
    # the way in: the stair's top (an earlier test leaves its own anchors and offset)
    LUA.eval("""function(B)
      B.pasture_anchors = function() return {{x = 60, y = 60, z = 80}} end
      B.elevation_offset = function() return 0 end
    end""")(B)


def _deep_plan_tiles():
    d = B.deep_depot_data()
    return [(t.x, t.y, t.z, t.r) for t in d.tiles.values()]


def _deep_sealed(tiles):
    """Every tile round the plan (not in it) is solid wall below the surface."""
    mine = {(x, y, z) for x, y, z, _r in tiles}
    for x, y, z, _r in tiles:
        if z >= 80:
            continue
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    n = (x + dx, y + dy, z + dz)
                    if n in mine or n[2] >= 80:
                        continue
                    if dz != 0 and (dx or dy):
                        continue          # (diagonals above and below don't touch)
                    t = W.get(*n)
                    assert t.shape == "WALL", ("opens onto", n, t.shape)


@test("deep depot (0.105.23): the layout: a 3-wide road, a channel and a ramp a level, a 9x9 hall; small enough for the gates' ledge")
def _():
    for k in (1, 2, 3):
        plan = B.deep_depot_layout(60, 53, 80, LUA.table_from([0, -1]), k)
        tiles = [(t.x, t.y, t.z, t.r) for t in plan.tiles.values()]
        assert len(set((x, y, z) for x, y, z, _ in tiles)) == len(tiles)
        assert {z for _, _, z, _ in tiles} == set(range(80 - k, 81)), sorted({z for _, _, z, _ in tiles})
        for z in range(80 - k + 1, 81):
            hs = [(x, y) for x, y, zz, r in tiles if zz == z and r == "h"]
            ramps = [(x, y) for x, y, zz, r in tiles if zz == z - 1 and r == "ramp"]
            assert len(hs) == 3 and sorted(hs) == sorted(ramps), (z, hs, ramps)     # a ramp under each channel
        assert plan.road <= B.DEEP_ROAD_MAX and len(tiles) - plan.road == 81, (plan.road, len(tiles))
        assert len(tiles) < 120, len(tiles)
        assert (plan.depot.x, plan.depot.z) == (60, 80 - k)
        h = plan.hall
        assert (h.x2 - h.x1, h.y2 - h.y1) == (8, 8) and h.x1 <= 58 and h.x2 >= 62, dict(h)
    two = B.deep_depot_layout(60, 53, 80, LUA.table_from([0, -1]), 2)
    t2 = {(x, y, z): r for x, y, z, r in [(t.x, t.y, t.z, t.r) for t in two.tiles.values()]}
    assert t2[(60, 52, 80)] == "h" and t2[(60, 52, 79)] == "ramp" and t2[(60, 51, 79)] == "d"
    assert t2[(60, 50, 79)] == "h" and t2[(60, 50, 78)] == "ramp" and t2[(60, 49, 78)] == "d"


@test("deep depot (0.105.23): a road down from open ground by the way in, sealed from the fort; dug, then the depot; the game's wagon access read")
def _():
    _deep_reset()
    _deep_ground()
    d = B.place_deep_depot(True)
    assert d.ok and d.dry_run and d.stage == "digging" and d.levels == 1, dict(d)
    assert not any(t.designated for t in W.tiles.values())
    r = B.place_deep_depot(False)
    assert r.ok and r.stage == "digging" and r.elevation == 79 and r.levels == 1, dict(r)
    tiles = _deep_plan_tiles()
    _deep_sealed(tiles)
    for x, y, z, rr in tiles:
        t = W.get(x, y, z)
        if rr == "ramp":
            assert not t.designated
        else:
            assert t.designated and t.dig_text == rr, (x, y, z, rr, t.dig_text)
        assert not (40 <= x <= 80 and 55 <= y <= 65), "into the fort's own floors"
    st = B.deep_depot_status()
    assert st.stage == "digging" and st.tiles_left == len(tiles) and st.stalled == 0, dict(st)
    w = B.place_deep_depot(False)
    assert not w.ok and w.waiting and w.tiles_left == len(tiles), dict(w)
    # a lost designation is put back
    lost = [(x, y, z) for x, y, z, rr in tiles if rr == "d"][:2]
    for x, y, z in lost:
        W.set(x, y, z, LUA.table_from({"designated": False}))
    assert B.deep_depot_status().stalled == 2
    g = B.place_deep_depot(False)
    assert g.ok and g.redig == 2 and all(W.get(*c).designated for c in lost), dict(g)
    # dug as the game digs it
    shape = {"h": "RAMP_TOP", "ramp": "RAMP", "d": "FLOOR"}
    for x, y, z, rr in tiles:
        W.set(x, y, z, LUA.table_from({"shape": shape[rr], "designated": False}))
    assert B.deep_depot_status().tiles_left == 0
    W.placed = LUA.table_from([])
    p = B.place_deep_depot(False)
    assert p.ok and p.stage == "placed", dict(p)
    built = [c for c in W.placed.values() if c.mode == "build"]
    assert len(built) == 1 and built[0].text == "D" and (built[0].x, built[0].y, built[0].z) == (st.x, st.y, 79), \
        [(c.x, c.y, c.z, c.text) for c in built]
    assert B.deep_depot_status().depot == "none"           # (not in the game's list yet)
    LUA.eval("""function(x, y, z, stage, acc)
      df.global.world.buildings.other.TRADE_DEPOT = {{x1 = x - 2, x2 = x + 2, y1 = y - 2, y2 = y + 2, z = z,
        accessible = acc, getBuildStage = function(self) return stage end, getMaxBuildStage = function(self) return 3 end}}
    end""")(st.x, st.y, 79, 1, None)
    s2 = B.deep_depot_status()
    assert s2.depot == "building" and s2.wagon_access is None, dict(s2)
    LUA.eval("function() df.global.world.buildings.other.TRADE_DEPOT[1].getBuildStage = function() return 3 end end")()
    LUA.eval("function() df.global.world.buildings.other.TRADE_DEPOT[1].accessible = 1 end")()
    s3 = B.deep_depot_status()
    assert s3.depot == "built" and s3.wagon_access is True, dict(s3)
    LUA.eval("function() df.global.world.buildings.other.TRADE_DEPOT[1].accessible = 0 end")()
    assert B.deep_depot_status().wagon_access is False
    again = B.place_deep_depot(False)
    assert not again.ok and again.done and again.wagon_access is False, dict(again)
    # its walls are kept by the quarry and the vein drifts
    areas = [dict(a) for a in B.level_areas().values()]
    assert any(a["z"] == 79 and a["x1"] <= st.x <= a["x2"] and a["y1"] <= st.y <= a["y2"] for a in areas), areas
    _deep_reset()


@test("deep depot (0.105.23): an open cavern under one side: the road goes the other way; never through an aquifer")
def _():
    _deep_reset()
    _deep_ground()
    LUA.eval("""function(W)
      for x = 20, 100 do for y = 20, 54 do for z = 76, 79 do
        W.set(x, y, z, {shape='EMPTY', feature=true, hidden=true})
      end end end
    end""")(W)
    r = B.place_deep_depot(False)
    assert r.ok, dict(r)
    tiles = _deep_plan_tiles()
    assert all(y >= 66 for _x, y, _z, _r in tiles), sorted({y for _x, y, _z, _r in tiles})
    _deep_sealed(tiles)
    # an aquifer everywhere under the ground: no road; the surface depot instead
    W.reset()
    _deep_reset()
    _deep_ground()
    LUA.eval("""function(W)
      for x = 15, 105 do for y = 15, 105 do for z = 75, 79 do
        local t = W.get(x, y, z); if t.shape == 'WALL' then t.aquifer = true end
      end end end
    end""")(W)
    n = B.place_deep_depot(False)
    assert not n.ok and n.rejected and n.no_road and "aquifer" in n.error, dict(n)
    assert not any(t.designated for t in W.tiles.values())
    st = B.deep_depot_status()
    assert st.stage == "no_road" and "aquifer" in st.why, dict(st)
    again = B.place_deep_depot(False)
    assert not again.ok and again.no_road and "surface" in again.error, dict(again)
    # a year on, it looks again
    LUA.execute("df.global.cur_year = 151")
    assert B.deep_depot_status() is None
    _deep_reset()


@test("deep depot (0.105.23): no road onto ground the dwarves can't reach, nor while a depot stands; one of the AI's levels is kept clear")
def _():
    _deep_reset()
    assert not B.place_deep_depot(True).ok                 # no open ground: nothing to start from
    _deep_ground()
    LUA.execute("df.global.world.buildings.other.TRADE_DEPOT = {{x1 = 1, x2 = 5, y1 = 1, y2 = 5, z = 80}}")
    r = B.place_deep_depot(True)
    assert not r.ok and "already stands" in r.error, dict(r)
    _deep_reset()
    # a level the AI has planned (not dug yet) north of the fort: the road keeps off it
    LUA.eval("""function(W)
      W.persist['ai-overseer/projects'] = {next_id = 2, list = {{id = 1, phase = 'dig', kind = 'bedrooms',
        area = {x1 = 20, y1 = 20, x2 = 100, y2 = 54, z = 79}}}}
    end""")(W)
    r = B.place_deep_depot(True)
    assert r.ok and (r.levels > 1 or r.y >= 66), dict(r)
    _deep_reset()

if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
