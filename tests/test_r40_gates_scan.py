"""(0.105.40, 13e) The gate scan made cheaper (lua/ai-gates.lua tile(),
gate_buildings; lua/ai-gates-scan.lua explore, seals, reaches_edge,
find_entrances, scan; lua/ai-gates-wings.lua fort_starts, porch_of) gives
the same answers as before: the round's base (merge39, one ai-gates.lua) and
the new one are run side by side.

1. On a fake DFHack (tile types, flags, buildings, citizens) through the
   game's own tile(): every tile() and under_tree() answer, gate_buildings,
   and whole scans of hand-made and random forts compared field by field;
   the DFHack reads each needs are counted.
2. On the fake maps of the existing gate tests: each test file is run with
   ai-gates loaded twice (merge39 beside the new one); every find_entrances
   and scan a test makes runs in both and the answers are compared.

Needs lupa and the merge39 commit (git); skipped without them.

    python tests/test_r40_gates_scan.py
"""

from __future__ import annotations

import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from lua_modules_util import module_src, with_util  # noqa: E402
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

BASE = "merge39"


def base_src() -> str | None:
    try:
        return subprocess.run(["git", "show", f"{BASE}:lua/ai-gates.lua"], cwd=ROOT, check=True,
                              capture_output=True, text=True, encoding="utf-8").stdout
    except (OSError, subprocess.CalledProcessError):
        return None


OLD = base_src()
if OLD is None:
    print(f"SKIPPED: no {BASE} commit to compare with (git history needed)")
    sys.exit(0)
OLD_SRC = with_util(OLD, "ai-gates.lua")
NEW_SRC = module_src("ai-gates.lua")

# A deep comparison: the first difference as a path, or nil.
DEEP_EQ = r"""
local function deep_eq(a, b, path, seen)
  if a == b then return nil end
  if type(a) ~= type(b) then return path .. ': ' .. type(a) .. ' vs ' .. type(b) .. ' (' .. tostring(a) .. ' / ' .. tostring(b) .. ')' end
  if type(a) ~= 'table' then
    if type(a) == 'number' and a == b then return nil end
    return path .. ': ' .. tostring(a) .. ' vs ' .. tostring(b)
  end
  seen = seen or {}
  if seen[a] == b then return nil end
  seen[a] = b
  for k, v in pairs(a) do
    local d = deep_eq(v, b[k], path .. '.' .. tostring(k), seen)
    if d then return d end
  end
  for k, v in pairs(b) do
    if a[k] == nil then return path .. '.' .. tostring(k) .. ': nil vs ' .. tostring(v) end
  end
  return nil
end
"""

# A fake DFHack: tile types, flags (each read counted), buildings, citizens.
# FAKE(map, buildings, citizens) -> df, dfhack, counter. map[z][y] = string;
# characters as below.
FAKE = DEEP_EQ + r"""
local function enum(names)
  local e = {}
  for i, n in ipairs(names) do e[i - 1] = n; e[n] = i - 1 end
  return e
end
local SHAPES = {'NONE', 'EMPTY', 'FLOOR', 'WALL', 'STAIR_UP', 'STAIR_DOWN', 'STAIR_UPDOWN', 'RAMP', 'RAMP_TOP',
                'BRANCH', 'TRUNK_BRANCH', 'TWIG', 'SHRUB', 'BOULDER', 'FORTIFICATION'}
local WALK = {FLOOR = true, STAIR_UP = true, STAIR_DOWN = true, STAIR_UPDOWN = true, RAMP = true, BRANCH = true,
              TRUNK_BRANCH = true, TWIG = true, SHRUB = true, BOULDER = true}
local MATS = {'NONE', 'STONE', 'SOIL', 'TREE', 'ROOT', 'PLANT', 'POOL', 'RIVER', 'CONSTRUCTION', 'MUSHROOM', 'FEATURE'}
-- char -> shape, material, flags
local CH = {
  ['#'] = {'WALL', 'STONE', {subterranean = true}},
  ['.'] = {'FLOOR', 'STONE', {subterranean = true}},
  ['o'] = {'FLOOR', 'SOIL', {outside = true}},
  ['n'] = {'FLOOR', 'SOIL', {}},                                  -- not outside, not underground: a tree's shade?
  ['T'] = {'WALL', 'TREE', {outside = true}},                     -- a trunk
  ['B'] = {'BRANCH', 'TREE', {outside = true}},
  ['e'] = {'EMPTY', 'NONE', {outside = true}},
  ['E'] = {'EMPTY', 'NONE', {subterranean = true}},
  ['s'] = {'STAIR_UPDOWN', 'STONE', {subterranean = true}},
  ['u'] = {'STAIR_UP', 'STONE', {subterranean = true}},
  ['d'] = {'STAIR_DOWN', 'STONE', {subterranean = true}},
  ['t'] = {'STAIR_UPDOWN', 'STONE', {outside = true}},
  ['r'] = {'RAMP', 'STONE', {subterranean = true}},
  ['R'] = {'RAMP', 'SOIL', {outside = true}},
  ['^'] = {'RAMP_TOP', 'NONE', {outside = true}},
  ['c'] = {'FLOOR', 'STONE', {subterranean = true, feature_global = true}},
  ['C'] = {'RAMP', 'STONE', {subterranean = true, feature_global = true}},
  ['p'] = {'FLOOR', 'STONE', {subterranean = true, feature_local = true}},
  ['?'] = {'FLOOR', 'STONE', {subterranean = true, hidden = true}},
  ['w'] = {'FLOOR', 'POOL', {subterranean = true, flow_size = 7, water_stagnant = true}},
  ['v'] = {'FLOOR', 'RIVER', {outside = true, flow_size = 2, water_salt = true}},
  ['m'] = {'FLOOR', 'STONE', {subterranean = true, flow_size = 3, liquid_type = true}},
  ['a'] = {'FLOOR', 'SOIL', {subterranean = true, water_table = true}},
  ['b'] = {'FLOOR', 'STONE', {subterranean = true}, true},          -- something built on it
  ['k'] = {'FORTIFICATION', 'CONSTRUCTION', {subterranean = true}},
}
function FAKE(map, buildings, citizens)
  local C = {n = 0}
  local df = {}
  df.tiletype_shape = enum(SHAPES)
  df.tiletype_shape.attrs = {}
  for i, n in ipairs(SHAPES) do df.tiletype_shape.attrs[i - 1] = {walkable = WALK[n] or false} end
  df.tiletype_material = enum(MATS)
  local tts, tt_of = {}, {}
  for ch, d in pairs(CH) do
    local id = d[1] .. ':' .. d[2]
    if not tt_of[id] then
      tts[#tts + 1] = {shape = df.tiletype_shape[d[1]], material = df.tiletype_material[d[2]], special = 0}
      tt_of[id] = #tts
    end
  end
  df.tiletype = {attrs = setmetatable({}, {__index = function(_, tt) C.n = C.n + 1; return tts[tt] end})}
  df.tile_building_occ = {None = 0, Planned = 1}
  df.building_type = enum({'Door', 'Hatch', 'Bridge', 'Construction', 'Bed', 'Table', 'Trap', 'Workshop'})
  df.construction_type = enum({'Wall', 'Fortification', 'Floor'})
  df.trap_type = enum({'Lever', 'CageTrap'})
  df.general_ref_type = enum({'BUILDING_HOLDER', 'BUILDING_TRIGGER', 'BUILDING_TRIGGERTARGET'})
  local all = {}
  local function bmethods(b)
    function b:getType() C.n = C.n + 1; return df.building_type[self.btype] end
    function b:getBuildStage() C.n = C.n + 1; return self.stage or 1 end
    function b:getMaxBuildStage() C.n = C.n + 1; return 1 end
    b.door_flags = b.door_flags or {forbidden = false, closed = false}
    b.contained_items = b.contained_items or {}
    b.linked_mechanisms, b.jobs = {}, {}
    b.name = b.name or ''
    return b
  end
  for _, b in ipairs(buildings or {}) do all[#all + 1] = bmethods(b) end
  local by_id = {}
  for _, b in ipairs(all) do by_id[b.id] = b end
  df.global = {cur_year = 100, cur_year_tick = 5000,
               world = {buildings = {all = all, other = setmetatable({TRAP = {}}, {__index = function() return {} end})},
                        items = {other = setmetatable({}, {__index = function() return {} end})},
                        units = {active = {}}}}
  df.building = {find = function(id) return by_id[id] end}
  local function cell(x, y, z)
    local lvl = map[z]; if not lvl then return nil end
    local row = lvl[y]; if not row or x < 0 then return nil end
    local ch = row:sub(x + 1, x + 1)
    if ch == '' then return nil end
    return CH[ch], ch
  end
  local dfhack = {maps = {}, units = {}, buildings = {}, persistent = {}, onStateChange = {}}
  function dfhack.maps.getTileType(x, y, z)
    C.n = C.n + 1
    local d = cell(x, y, z)
    return d and tt_of[d[1] .. ':' .. d[2]] or nil
  end
  function dfhack.maps.getTileFlags(x, y, z)
    C.n = C.n + 1
    local d = cell(x, y, z)
    if not d then return nil end
    local f = d[3]
    local des = setmetatable({}, {__index = function(_, k)
      C.n = C.n + 1
      local v = f[k]
      if v == nil then
        if k == 'flow_size' then return 0 end
        if k == 'liquid_type' then return false end
        return false
      end
      return v
    end})
    local occ = setmetatable({}, {__index = function(_, k) C.n = C.n + 1; if k == 'building' then return d[4] and 1 or 0 end end})
    return des, occ
  end
  local w, h, zs = 0, 0, 0
  for z, lvl in pairs(map) do zs = math.max(zs, z + 1); for y, row in pairs(lvl) do h = math.max(h, y + 1); w = math.max(w, #row) end end
  function dfhack.maps.getTileSize() return w, h, zs end
  function dfhack.units.getCitizens() return citizens or {} end
  function dfhack.units.getPosition(u) return u.pos.x, u.pos.y, u.pos.z end
  function dfhack.buildings.findAtTile() return nil end
  local site = {}
  function dfhack.persistent.getSiteData(k, d) return site[k] or d end
  function dfhack.persistent.saveSiteData(k, v) site[k] = v end
  return df, dfhack, C
end

-- a module loaded into its own env over the fake game
function LOAD(src, df, dfhack)
  local env = setmetatable({df = df, dfhack = dfhack, xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end,
                            SC_MAP_UNLOADED = 'unloaded'}, {__index = _G})
  assert(load(src, 'ai-gates', 't', env))()
  return env
end
"""

# 1a. Every tile() / under_tree() / tile_is_ramp answer over a map, and the reads.
TILES = FAKE + r"""
local old_src, new_src, map = ...
local df, dfhack, C = FAKE(map, {}, {})
local O, N = LOAD(old_src, df, dfhack), LOAD(new_src, df, dfhack)
local W, H, Z = dfhack.maps.getTileSize()
local n, ramps = 0, 0
local old_reads, new_reads = 0, 0
for pass = 1, 2 do          -- twice: the second with the new one's tile types already known
  for z = -1, Z do for y = -1, H do for x = -1, W do
    local c0 = C.n; local a = O.tile(x, y, z); old_reads = old_reads + C.n - c0
    c0 = C.n; local b = N.tile(x, y, z); new_reads = new_reads + C.n - c0
    local d = deep_eq(a, b, ('tile(%d,%d,%d)'):format(x, y, z))
    if d then return d end
    local ua, ub = O.under_tree(x, y, z), N.under_tree(x, y, z)
    if ua ~= ub then return ('under_tree(%d,%d,%d): %s vs %s'):format(x, y, z, tostring(ua), tostring(ub)) end
    local want = (a and a.shape == 'RAMP') or false
    if N.tile_is_ramp(x, y, z) ~= want then return ('tile_is_ramp(%d,%d,%d)'):format(x, y, z) end
    if want then ramps = ramps + 1 end
    n = n + 1
  end end end
end
return 'ok', n, ramps, old_reads, new_reads
"""

# 1b. Whole scans, old and new, each over its own copy of the same fake game.
SCAN = FAKE + r"""
local old_src, new_src, map, buildings, citizens, rounds = ...
local function copy(t, seen)
  if type(t) ~= 'table' then return t end
  seen = seen or {}
  if seen[t] then return seen[t] end
  local o = {}; seen[t] = o
  for k, v in pairs(t) do o[copy(k, seen)] = copy(v, seen) end
  return o
end
local out = {}
local function run(src)
  local df, dfhack, C = FAKE(map, copy(buildings), copy(citizens))
  local M = LOAD(src, df, dfhack)
  local results, reads = {}, 0
  for i = 1, rounds do
    local c0 = C.n
    local ok, r = pcall(M.scan, 5000 + i)
    reads = reads + C.n - c0
    if not ok then return nil, 'scan error: ' .. tostring(r) end
    results[i] = {summary = r, gates = copy(M.GATES), gb = M.gate_buildings()}
    -- the scan's pieces as other actions call them (outside a scan)
    local okf, fs = pcall(M.fort_starts, nil)
    results[i].fort_starts_nil = okf and fs or ('error ' .. tostring(fs))
  end
  local okx, st = pcall(function()
    local s = {}
    for _, u in ipairs(citizens) do s[#s + 1] = {x = u.pos.x, y = u.pos.y, z = u.pos.z} end
    return M.fort_starts(s)
  end)
  results.fort_starts = okx and st or ('error ' .. tostring(st))
  for _, e in ipairs(M.GATES.entrances or {}) do
    local okp, p = pcall(M.porch_of, e, results.fort_starts)
    results['porch' .. e.id] = okp and p or ('error ' .. tostring(p))
    local okc, plan, why = pcall(M.plan_cut, e, results.fort_starts, true)
    results['cut' .. e.id] = {okc, plan or false, why or false}
  end
  return results, reads
end
local a, ra = run(old_src)
if not a then return 'old: ' .. ra end
local b, rb = run(new_src)
if not b then return 'new: ' .. rb end
local d = deep_eq(a, b, 'scan')
if d then return d end
local n = 0
for _, e in ipairs(b[rounds].gates.entrances or {}) do n = n + 1 end
local kinds = {}
for _, e in ipairs(b[rounds].gates.entrances or {}) do
  kinds[#kinds + 1] = e.kind .. (e.sealed and ':sealed' or '') .. (e.closing and ':closing' or '') .. (e.cut and ':cut' or '')
      .. (e.cut_why and ':why' or '') .. (e.cut_hatches and ':cuthatches' or '') .. ((#e.door_spots > 0) and ':doors' or '')
      .. (e.gatehouse and (':gh-' .. e.gatehouse) or '')
end
return 'ok', n, b[rounds].gates.inside_tiles or 0, ra, rb, table.concat(kinds, ' ')
"""


def lua_map(lua, levels):
    """levels: list (z = 0 up) of lists of row strings -> map[z][y] = row."""
    return lua.eval("""function(levels)
      local m = {}
      for z = 1, #levels do local l = {}; for y = 1, #levels[z] do l[y - 1] = levels[z][y] end; m[z - 1] = l end
      return m end""")(lua.table_from([lua.table_from(lv) for lv in levels]))


def to_lua(lua, v):
    if isinstance(v, dict):
        return lua.table_from({k: to_lua(lua, x) for k, x in v.items()})
    if isinstance(v, list):
        return lua.table_from([to_lua(lua, x) for x in v])
    return v


# A hand-made fort: three levels under a surface with trees, a courtyard, a
# wide open hillside mouth (the cut's porch), stairs, ramps in and out, a
# cavern, water, magma, a hidden patch, a local feature, a door that seals
# a tunnel, a hatch on the stair's top, a planned wall.
HAND = [
    [  # z0: the cavern level
        "########################################",
        "#cccccccc#######################.......#",
        "#cccccccc.......................s......#",
        "#ccCccccc#######################.......#",
        "#cccccccc#############?????#############",
        "#cccccccc########ppp###################",
        "########################################",
    ],
    [  # z1
        "########################################",
        "#######w.........m......################",
        "#######w..................r.....s......#",
        "#######..........a......#######........#",
        "#######.........#########.......########",
        "#######.......b..................bb....#",
        "########################################",
    ],
    [  # z2: the fort's top level, a hillside to the west
        "oooooooo################################",
        "oooooooo......................#........#",
        "oooooooo..........#..........E.s.......#",
        "oooooooo......................#........#",
        "ooooRooo#######################........#",
        "oooooooo########################.......#",
        "oooooooo################################",
    ],
    [  # z3: the surface
        "eeeeeeeeooooooooooooooooooooooooooooooo",
        "eeeeeeeeooooooooo###########oooooooooooo",
        "eeeeeeeeoooonnnoo#ooooooooo#ooot^oooooooo",
        "eeeeeeeeoooonnnoo#ooooooooo#oooooooooooo",
        "eeee^eeeooooooooo###########oooooovvvooo",
        "eeeeeeeeooooooooooooooooooooooooooooooooo",
        "eeeeeeeeooooooooooooooooooooooooooooooooo",
    ],
    [  # z4: a tree's crown over the shade
        "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        "eeeeeeeeeeeeBBBeeeeeeeeeeeeeeeeeeeeeeeee",
        "eeeeeeeeeeeeBTBeeeeeeeeeeeeeeeeeeeeeeeee",
        "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
    ],
]
HAND_BUILDINGS = [
    {"id": 1, "btype": "Door", "x1": 34, "y1": 5, "x2": 34, "y2": 5, "z": 1},
    {"id": 2, "btype": "Door", "x1": 33, "y1": 5, "x2": 33, "y2": 5, "z": 1, "door_flags": {"forbidden": True, "closed": True}},
    {"id": 3, "btype": "Hatch", "x1": 31, "y1": 2, "x2": 31, "y2": 2, "z": 3},
    {"id": 4, "btype": "Construction", "type": 1, "stage": 0, "x1": 30, "y1": 1, "x2": 30, "y2": 1, "z": 2},
    {"id": 5, "btype": "Bed", "x1": 10, "y1": 2, "x2": 10, "y2": 2, "z": 1},
    {"id": 6, "btype": "Door", "stage": 0, "x1": 14, "y1": 5, "x2": 14, "y2": 5, "z": 1},
    {"id": 7, "btype": "Bridge", "x1": 4, "y1": 3, "x2": 6, "y2": 3, "z": 2},
]


def citizens_on(levels, n, seed, chars="."):
    rnd = random.Random(seed)
    spots = [(x, y, z) for z, lv in enumerate(levels) for y, row in enumerate(lv) for x, ch in enumerate(row)
             if ch in chars]
    rnd.shuffle(spots)
    return [{"id": i + 1, "pos": {"x": x, "y": y, "z": z}} for i, (x, y, z) in enumerate(spots[:n])]


def random_fort(seed, w=36, h=22, zs=5):
    """A random fort: rooms and corridors on the levels under a surface,
    stairs and ramps between them, openings to the surface and a cavern."""
    rnd = random.Random(seed)
    lv = [[["#"] * w for _ in range(h)] for _ in range(zs)]
    top = zs - 1
    for y in range(h):
        for x in range(w):
            lv[top][y][x] = "o" if rnd.random() > 0.04 else "#"
    # a courtyard on the surface now and then
    if rnd.random() < 0.6:
        cx, cy = rnd.randrange(4, w - 10), rnd.randrange(3, h - 8)
        for y in range(cy, cy + 6):
            for x in range(cx, cx + 7):
                lv[top][y][x] = "#" if y in (cy, cy + 5) or x in (cx, cx + 6) else "o"
    for z in range(top):
        for _ in range(rnd.randrange(3, 7)):
            rx, ry = rnd.randrange(1, w - 8), rnd.randrange(1, h - 6)
            rw, rh = rnd.randrange(3, 8), rnd.randrange(2, 5)
            for y in range(ry, ry + rh):
                for x in range(rx, rx + rw):
                    lv[z][y][x] = rnd.choice("." * 30 + "wbv?pam")
        # corridors along a row and a column
        y0, x0 = rnd.randrange(2, h - 2), rnd.randrange(2, w - 2)
        for x in range(1, w - 1):
            if lv[z][y0][x] == "#":
                lv[z][y0][x] = "."
        for y in range(1, h - 1):
            if lv[z][y][x0] == "#":
                lv[z][y][x0] = "."
    # a stair column through every level (its top on the surface)
    sx, sy = rnd.randrange(2, w - 2), rnd.randrange(2, h - 2)
    for z in range(top):
        lv[z][sy][sx] = "s" if 0 < z else "u"
    lv[top - 1][sy][sx] = "s"
    lv[top][sy][sx] = "t"
    # ramps: up from a level to the next (the tile above the ramp open)
    for _ in range(rnd.randrange(1, 5)):
        z = rnd.randrange(0, top)
        rx, ry = rnd.randrange(1, w - 1), rnd.randrange(1, h - 1)
        lv[z][ry][rx] = "r" if z < top - 1 else "R"
        if z + 1 < zs:
            lv[z + 1][ry][rx] = "^" if z + 1 == top else "E"
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if 0 < rx + dx < w - 1 and 0 < ry + dy < h - 1 and lv[z + 1][ry + dy][rx + dx] == "#":
                    lv[z + 1][ry + dy][rx + dx] = "." if z + 1 < top else "o"
    # a hillside: the level under the surface open to the sky on one side
    if rnd.random() < 0.7:
        edge = rnd.randrange(3, 9)
        for y in range(h):
            for x in range(edge):
                lv[top - 1][y][x] = "o"
    # a cavern on the bottom level
    if rnd.random() < 0.7:
        for y in range(1, h - 1):
            for x in range(w - 8, w - 1):
                lv[0][y][x] = "c" if rnd.random() > 0.1 else "C"
    levels = ["".join(r) for r in lv[0]], *(["".join(r) for r in lv[z]] for z in range(1, zs))
    levels = list(levels)
    # doors on some corridor tiles (sealing perhaps), a hatch on the stair's top
    bl = []
    bid = 1
    for z in range(top):
        for _ in range(rnd.randrange(0, 4)):
            x, y = rnd.randrange(1, w - 1), rnd.randrange(1, h - 1)
            if levels[z][y][x] == ".":
                bl.append({"id": bid, "btype": rnd.choice(["Door", "Door", "Hatch", "Construction"]), "type": 0,
                           "stage": rnd.choice([0, 1, 1]), "x1": x, "y1": y, "x2": x, "y2": y, "z": z})
                bid += 1
    if rnd.random() < 0.5:
        bl.append({"id": bid, "btype": "Hatch", "x1": sx, "y1": sy, "x2": sx, "y2": sy, "z": top})
    return levels, bl, citizens_on(levels, rnd.randrange(3, 12), seed)


@test("tile(): the same answer as merge39's for every tile of the fake game (and under_tree, tile_is_ramp), with fewer reads")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    r = lua.execute(TILES, OLD_SRC, NEW_SRC, lua_map(lua, HAND))
    assert r[0] == "ok", r
    _, n, ramps, old_reads, new_reads = r
    assert n > 1000 and ramps > 0, r
    assert new_reads < old_reads, (old_reads, new_reads)
    print(f"        tile(): {n} answers the same; DFHack reads {old_reads} -> {new_reads}")


@test("scan: the hand-made fort, three scans in a row, the same as merge39's (entrances, GATES, summary, porch, cut)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    cit = citizens_on(HAND, 8, 1)
    r = lua.execute(SCAN, OLD_SRC, NEW_SRC, lua_map(lua, HAND), to_lua(lua, HAND_BUILDINGS), to_lua(lua, cit), 3)
    assert r[0] == "ok", r
    _, n, inside, ra, rb, kinds = r
    assert n >= 3 and inside > 100, r
    assert rb < ra, (ra, rb)
    print(f"        hand-made fort: {n} entrances ({kinds}), {inside} tiles inside; DFHack reads {ra} -> {rb}")


@test("scan: 40 random forts, each scanned twice, the same as merge39's")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    ra_all = rb_all = 0
    kinds = set()
    for seed in range(40):
        levels, bl, cit = random_fort(seed)
        r = lua.execute(SCAN, OLD_SRC, NEW_SRC, lua_map(lua, levels), to_lua(lua, bl), to_lua(lua, cit), 2)
        assert r[0] == "ok", (seed, r)
        ra_all += r[3]
        rb_all += r[4]
        kinds.update(r[5].split())
    # the random forts reach the cases that matter
    want = {"cavern", "surface"}
    assert want <= {k.split(":")[0] for k in kinds}, kinds
    assert any(":sealed" in k for k in kinds) and any(":why" in k or ":cut" in k for k in kinds), kinds
    print(f"        random forts: DFHack reads {ra_all} -> {rb_all} ({100 * (ra_all - rb_all) // ra_all}% fewer)")


# 2. The existing gate tests' fake maps: each file run with both modules.
# Appended to the new module's text in the test's env: merge39's module is
# loaded beside it (its own env; what the test swapped or set in the new
# one's env is handed over before each call), and find_entrances / scan run
# in both, the answers compared; one line a call to E5_LOG.
DUAL = DEEP_EQ + r"""
do
  local NEW = _ENV
  local own = {}
  for k, v in pairs(NEW) do own[k] = v end
  local OLDE = setmetatable({}, {__index = function(_, k) return NEW[k] end})
  assert(load(E5_OLD_SRC, 'ai-gates-merge39', 't', OLDE))()
  local old_own = {}
  for k, v in pairs(OLDE) do old_own[k] = v end
  local function sync()
    -- what the test swapped or set, and the state the new module changed,
    -- as the new module's env holds it now; the rest stays merge39's own
    for k, v in pairs(NEW) do
      if own[k] ~= v or old_own[k] == nil then rawset(OLDE, k, v)
      else rawset(OLDE, k, old_own[k]) end
    end
  end
  local function copy(t, seen)
    if type(t) ~= 'table' then return t end
    seen = seen or {}
    if seen[t] then return seen[t] end
    local o = {}; seen[t] = o
    for k, v in pairs(t) do o[copy(k, seen)] = copy(v, seen) end
    return setmetatable(o, getmetatable(t))
  end
  local log = io.open(E5_LOG, 'a')
  local function note(s) log:write(s, '\n'); log:flush() end
  local depth = 0
  -- (explore is compared through these: alone it walks with its caller's caches,
  -- which merge39 keeps where no one else can reach)
  for _, name in ipairs({'find_entrances', 'fort_starts'}) do
    local f = NEW[name]
    NEW[name] = function(...)
      if depth > 0 then return f(...) end
      depth = depth + 1
      sync()
      local args = table.pack(...)
      local oargs = copy(args)
      local ro = table.pack(pcall(OLDE[name], table.unpack(oargs, 1, oargs.n)))
      local rn = table.pack(pcall(f, ...))
      depth = depth - 1
      local d
      if ro[1] ~= rn[1] then d = 'one failed: ' .. tostring(ro[2]) .. ' / ' .. tostring(rn[2])
      elseif ro[1] then d = deep_eq({table.unpack(ro, 2, ro.n)}, {table.unpack(rn, 2, rn.n)}, name) end
      note((d and ('MISMATCH ' .. E5_FILE .. ' ' .. d) or ('ok ' .. name)))
      if not rn[1] then error(rn[2], 0) end
      return table.unpack(rn, 2, rn.n)
    end
  end
  -- scan: merge39's first on a copy of the state it reads (GATES), then the new one
  local scan_new = NEW.scan
  NEW.scan = function(...)
    if depth > 0 then return scan_new(...) end
    sync()
    local gates_before = NEW.GATES
    rawset(OLDE, 'GATES', copy(gates_before))
    depth = depth + 1
    local ro = table.pack(pcall(OLDE.scan, ...))
    local gates_old = rawget(OLDE, 'GATES')
    depth = depth - 1
    local rn = table.pack(pcall(scan_new, ...))
    local d
    if ro[1] ~= rn[1] then d = 'scan: one failed: ' .. tostring(ro[2]) .. ' / ' .. tostring(rn[2])
    elseif ro[1] then d = deep_eq(ro[2], rn[2], 'scan') or deep_eq(gates_old, NEW.GATES, 'GATES') end
    note((d and ('MISMATCH ' .. E5_FILE .. ' ' .. d) or 'ok scan'))
    if not rn[1] then error(rn[2], 0) end
    return table.unpack(rn, 2, rn.n)
  end
  -- the wrappers are the module's own (merge39 runs its own); a test's swap still reaches both
  for _, name in ipairs({'find_entrances', 'fort_starts', 'scan'}) do own[name] = NEW[name] end
end
"""

DRIVER = r"""
import os, runpy, sys
sys.path.insert(0, os.environ["E5_TESTS"])
import lua_modules_util as U
real = U.module_src
pre = U._lua_string
def module_src(name):
    src = real(name)
    if name != "ai-gates.lua":
        return src
    read = lambda p: open(p, encoding="utf-8").read()
    return src + "\nE5_OLD_SRC = " + pre(read(os.environ["E5_OLD"])) + "; E5_LOG = " + pre(os.environ["E5_LOG"]) + \
        "; E5_FILE = " + pre(os.environ["E5_NAME"]) + "\n" + read(os.environ["E5_DUAL"])
U.module_src = module_src
import harness
harness.finish = lambda *a, **k: None
sys.argv = [os.environ["E5_PATH"]]
try:
    runpy.run_path(os.environ["E5_PATH"], run_name="__main__")
except SystemExit:
    pass
print(sum(1 for r in harness.RESULTS if r[1]), "passed,", sum(1 for r in harness.RESULTS if not r[1]), "failed")
"""

# the gate tests that map the fort (find_entrances or scan on fake maps)
FILES = ["test_gates.py", "test_r32_wayin.py", "test_fix31_depotscan.py", "test_construct_gates.py",
         "test_fix26_features.py", "test_fix26_seal.py", "test_r33_gates.py", "test_r36_gates.py",
         "test_deep_depot_wagons.py", "test_construct_fixes.py", "test_r32_gatesplit.py", "test_construct_seams.py"]


@test("the existing gate tests' maps: every find_entrances, fort_starts and scan they make answers as merge39's")
def _():
    counts, bad = {}, []
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "dual.log"
        old_file, dual_file = Path(tmp) / "old.lua", Path(tmp) / "dual.lua"
        old_file.write_text(OLD, encoding="utf-8")
        dual_file.write_text(DUAL, encoding="utf-8")
        env = dict(os.environ, E5_TESTS=str(ROOT / "tests"), E5_OLD=str(old_file), E5_LOG=str(log),
                   E5_DUAL=str(dual_file))
        for f in FILES:
            env.update(E5_PATH=str(ROOT / "tests" / f), E5_NAME=f)
            p = subprocess.run([sys.executable, "-c", DRIVER], cwd=ROOT / "tests", env=env, capture_output=True,
                               timeout=600, text=True)
            if os.environ.get("E5_DEBUG"):
                print(f, p.returncode, p.stdout[-800:], p.stderr[-1500:])
        lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    for line in lines:
        if line.startswith("MISMATCH"):
            bad.append(line[:300])
        else:
            counts[line] = counts.get(line, 0) + 1
    assert not bad, bad[:5]
    assert counts.get("ok find_entrances", 0) >= 50 and counts.get("ok scan", 0) >= 3 \
        and counts.get("ok fort_starts", 0) >= 10, counts
    print("        compared: " + ", ".join(f"{k[3:]} {v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    finish()
