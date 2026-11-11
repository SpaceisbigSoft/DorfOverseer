"""Tests for the emergency way in (0.105.32, group wayin): lua/ai-builder-projects.lua
dig_way_in on a fake map, in a real Lua engine (pip install lupa), and the
gate scan (lua/ai-gates.lua find_entrances) seeing the dug column as a new
surface entrance.

    python tests/test_r32_wayin.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from lua_modules_util import module_src  # noqa: E402
from harness import make_test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

# The fake world. Surface ground at z 30 (outside, walk group 2), open air
# above it, rock below. The fort: one level at z 24 (x 20-40, y 20-30, walk
# group 1) and its founding stair at (30, 25) up to a hatch at z 30.
HARNESS = r"""
local layouts_src, builder_src, gates_src = ...
local function load_module(src, name, extra)
  local env = setmetatable(extra or {}, {__index=_G})
  assert(load(src, name, 't', env))()
  return env
end

local W = {}
W.size = {64, 64, 40}
W.SURF = 30
local function n_of(x, y, z) return (z * 64 + y) * 64 + x end
function W.default(x, y, z)
  if z < W.SURF then return {shape='WALL', material='STONE'} end
  if z == W.SURF then return {shape='FLOOR', material='SOIL', outside=true} end
  return {shape='EMPTY', material='AIR', outside=true}
end
function W.get(x, y, z)
  if x < 0 or y < 0 or z < 0 or x >= W.size[1] or y >= W.size[2] or z >= W.size[3] then return nil end
  local n = n_of(x, y, z)
  local t = W.idx[n]
  if not t then
    t = W.default(x, y, z)
    for _, k in ipairs({'aquifer', 'liquid', 'feature', 'outside', 'designated', 'building', 'warm', 'hidden'}) do
      if t[k] == nil then t[k] = false end
    end
    t.x, t.y, t.z = x, y, z
    W.idx[n] = t
  end
  return t
end
function W.set(x, y, z, f) local t = W.get(x, y, z); for k, v in pairs(f) do t[k] = v end end
function W.group(x, y, z)
  local t = W.get(x, y, z)
  if not t then return 0 end
  if t.group then return t.group end
  if t.shape == 'WALL' or t.shape == 'EMPTY' then return 0 end
  if t.feature then return 3 end
  return t.outside and 2 or 1
end
function W.box(x1, y1, x2, y2, z, f)
  for x = x1, x2 do for y = y1, y2 do W.set(x, y, z, f) end end
end
function W.fort(z, x1, y1, x2, y2)
  W.box(x1, y1, x2, y2, z, {shape='FLOOR'})
end
-- the gate scan's map of the inside: every open tile not outside, under the surface
function W.scan_inside()
  local inside = {}
  for n, t in pairs(W.idx) do
    if t.z < W.SURF and t.shape ~= 'WALL' and t.shape ~= 'EMPTY' and not t.outside and not t.feature then
      inside[(t.z * 4096 + t.y) * 4096 + t.x] = true
    end
  end
  W.GATES.inside = inside
end
function W.reset()
  W.idx, W.persist, W.calls, W.jobs, W.citizens = {}, {}, {}, {}, {}
  W.SURF = 30
  W.fort(24, 20, 20, 40, 30)
  for z = 24, 29 do W.set(30, 25, z, {shape = (z == 24) and 'STAIR_UP' or 'STAIR_UPDOWN'}) end
  W.set(30, 25, 30, {shape='STAIR_DOWN', building=true})        -- the hatch over it
  W.persist['ai-overseer/founded'] = {x=30, y=25, z=30}
  W.GATES = {scanned=true, inside={}, entrances={{id=1, kind='surface', x=30, y=25, z=29,
             equipment={{id=7, kind='hatch', x1=30, y1=25, x2=30, y2=25, z=30}}}}}
  W.scan_inside()
  W.use_gates = true
end

local function parse(text)
  local k2 = text:match('^([%a~]+)%d+$')
  if k2 then return k2 end
  return text
end
local quickfort = {}
function quickfort.apply_blueprint(p)
  table.insert(W.calls, {mode=p.mode, command=p.command, dry_run=p.dry_run})
  local stats = {dig_designated={value=0}, dig_invalid_tiles={value=0}, out_of_bounds={value=0}, invalid_keys={value=0}}
  for z, grid in pairs(p.data) do for y, row in pairs(grid) do for x, text in pairs(row) do
    local key = parse(text)
    local t = W.get(x + p.pos.x, y + p.pos.y, z + p.pos.z)
    if not t then stats.out_of_bounds.value = stats.out_of_bounds.value + 1
    elseif t.shape == 'WALL' or (key == 'j' and t.shape == 'FLOOR') then
      stats.dig_designated.value = stats.dig_designated.value + 1
      if not p.dry_run then
        t.designated = (p.command ~= 'undo')
        t.dig_text = (p.command ~= 'undo') and text or nil
      end
    else
      stats.dig_invalid_tiles.value = stats.dig_invalid_tiles.value + 1
    end
  end end end
  return stats
end
-- the miners at work: every designated tile dug as its key says
local DUG = {j='STAIR_DOWN', i='STAIR_UPDOWN', u='STAIR_UP', d='FLOOR'}
function W.dig_all()
  for _, t in pairs(W.idx) do
    if t.designated and t.dig_text then
      t.shape = DUG[parse(t.dig_text)]
      t.designated = false
    end
  end
end

local GATES_MOD = {fort_interior = function() return {what='founding stair', x=30, y=25, z=29, group=1} end}
_G.reqscript = function(name)
  if name == 'ai-layouts' then return LAYOUTS end
  if name == 'quickfort' then return quickfort end
  error('unexpected reqscript '..name)
end
_G.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
_G.dfhack = {persistent = {
  getSiteData = function(k, default) local v = W.persist[k]; if v == nil then return default end return v end,
  saveSiteData = function(k, v) W.persist[k] = v end},
  findScript = function(name) return LUA_DIR .. '/' .. name .. '.lua' end}
LAYOUTS = load_module(layouts_src, 'ai-layouts')
local B = load_module(builder_src, 'ai-builder')
B.tile_info = W.get
B.map_size = function() return W.size[1], W.size[2], W.size[3] end
B.stair_shape = function(x,y,z) local t = W.get(x,y,z)
  return t and (t.shape:find('^STAIR') and t.shape) or nil end
B.citizen_positions = function() return W.citizens end
B.job_tiles = function() return W.jobs end
B.walk_group = W.group
B.building_at = function(x,y,z) local t = W.get(x,y,z); return t ~= nil and t.building == true end
B.zone_types = function() return {} end
B.way_in_gates = function()
  if not W.use_gates then return nil end
  GATES_MOD.GATES = W.GATES
  return GATES_MOD
end

-- the real gate scan, over the same map
local G = load_module(gates_src, 'ai-gates')
function G.tile(x, y, z)
  local t = W.get(x, y, z)
  if not t then return nil end
  return {walk = t.shape ~= 'WALL' and t.shape ~= 'EMPTY', shape = t.shape, outside = t.outside,
          feature = t.feature, special = false, hidden = false, liquid = t.liquid, depth = t.liquid and 7 or 0,
          material = t.material, occupied = false}
end
function G.map_size() return W.size[1], W.size[2], W.size[3] end
function G.gate_buildings() return {} end
function G.building_at() return nil end
W.reset()
return B, W, G
"""


def boot():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(ROOT / "lua")
    layouts = (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8")
    builder = (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8")
    B, W, G = lua.execute(HARNESS, layouts, builder, module_src("ai-gates.lua"))
    return lua, B, W, G


LUA, B, W, G = boot()
test = make_test(before=lambda: W.reset())


def way_in(x=46, y=25, z=30, dry=False):
    return B.dig_way_in(LUA.table_from({"x": x, "y": y, "z": z}), LUA.table_from({"year": 253, "tick": 100}), dry)


def designated():
    return sorted((t.x, t.y, t.z, t.dig_text) for t in W.idx.values() if t.designated)


def projects():
    d = W.persist["ai-overseer/projects"]
    if d is None:
        return []
    return [d.list[i] for i in range(1, len(d.list) + 1)]


def column_of(r):
    return (r.column.x, r.column.y)


def surface_entrances():
    starts = LUA.table_from({1: LUA.table_from({"x": 25, "y": 25, "z": 24})})
    es = G.find_entrances(starts, LUA.table())[0]
    return sorted((e.x, e.y) for e in (es[i] for i in range(1, len(es) + 1)) if e.kind == "surface")


@test("way in: a column beside the fort's top level, up through rock to their ground, designated at priority 1")
def _():
    r = way_in()
    assert r.ok and r.project_id == 1, dict(r)
    assert column_of(r) == (41, 25) and r.tiles == 7 and r.tunnel == 0, dict(r)
    assert (r["from"].x, r["from"].y, r["from"].z) == (40, 25, 24), dict(r["from"])
    assert (r.to.x, r.to.y, r.to.z) == (41, 25, 30), dict(r.to)
    want = [(41, 25, 24, "u1")] + [(41, 25, z, "i1") for z in range(25, 30)] + [(41, 25, 30, "j1")]
    assert designated() == sorted(want), designated()


@test("way in: the project record (kind way_in, emergency, its stairs) and the report shows it")
def _():
    r = way_in()
    ps = projects()
    assert len(ps) == 1, ps
    p = ps[0]
    assert p.kind == "way_in" and p.phase == "dig" and p.emergency is True and p.params.pri == "1", dict(p)
    assert p.z == 24 and (p.anchor.x, p.anchor.y) == (41, 25) and len(p.shaft_stairs) == 7, dict(p)
    assert p.stranded.group == 2 and p.summary.way_in is True, dict(p.stranded)
    rep = B.projects_report()
    o = [rep.open[i] for i in range(1, len(rep.open) + 1)]
    assert len(o) == 1 and o[0].kind == "way_in" and o[0].dig.total == 7 and o[0].dig.dug == 0, dict(o[0])
    W.dig_all()
    rep = B.projects_report()
    o = rep.open[1]
    assert o.dig.dug == 7 and o.next == "finish", (dict(o.dig), o.next)
    r2 = way_in()
    assert not r2.ok and r2.rejected and "already being dug (project 1)" in r2.error, dict(r2)


@test("way in: once dug, the gate scan finds it as a new surface entrance")
def _():
    before = surface_entrances()
    assert before == [(30, 25)], before
    r = way_in()
    assert r.ok
    W.dig_all()
    after = surface_entrances()
    assert after == [(30, 25), (41, 25)], after


@test("way in: down, when they stand lower than the fort (a valley floor under it)")
def _():
    W.box(42, 10, 63, 40, 18, LUA.table_from({"shape": "FLOOR", "outside": True}))
    r = way_in(x=50, y=25, z=18)
    assert r.ok and column_of(r) == (41, 25) and r.tiles == 7, dict(r)
    want = [(41, 25, 18, "u1")] + [(41, 25, z, "i1") for z in range(19, 24)] + [(41, 25, 24, "j1")]
    assert designated() == sorted(want), designated()
    assert (r.to.x, r.to.z) == (42, 18), dict(r.to)
    W.dig_all()
    assert (41, 25) in surface_entrances(), surface_entrances()


@test("way in: only to ground under the sky, not to an underground road of theirs")
def _():
    # a road of theirs (walk group 2, not outside) right beside the fort at z 27
    W.box(41, 10, 60, 40, 27, LUA.table_from({"shape": "FLOOR", "group": 2}))
    r = way_in(x=46, y=25, z=27, dry=True)
    assert r.ok and r.to.z == 30, dict(r.to)


@test("way in: dry run gives the plan and changes nothing")
def _():
    r = way_in(dry=True)
    assert r.ok and r.dry_run and column_of(r) == (41, 25) and r.project_id is None, dict(r)
    assert designated() == [] and projects() == []
    assert all(c.dry_run for c in W.calls.values()), "a real quickfort run on a dry run"


@test("way in: at least 6 tiles from the gate's pieces")
def _():
    # a narrow fort round the stair: its east wall at x 34, 4 from the hatch
    W.reset()
    W.idx = LUA.table()
    W.fort(24, 26, 20, 34, 30)
    for z in range(24, 30):
        W.set(30, 25, z, LUA.table_from({"shape": "STAIR_UP" if z == 24 else "STAIR_UPDOWN"}))
    W.set(30, 25, 30, LUA.table_from({"shape": "STAIR_DOWN", "building": True}))
    W.scan_inside()
    r = way_in(x=33, y=25)
    assert r.ok, dict(r)
    x, y = column_of(r)
    assert max(abs(x - 30), abs(y - 25)) >= 6, (x, y)
    assert all(max(abs(t.x - 30), abs(t.y - 25)) >= 3 for t in W.idx.values() if t.designated), \
        (dict(r.column), designated())


@test("way in: a short tunnel on the fort's level when the column can't stand beside it")
def _():
    W.box(14, 14, 46, 36, 30, LUA.table_from({"building": True}))     # the ground over the fort is built on
    r = way_in(x=46, y=25)
    assert r.ok and column_of(r) == (47, 25) and r.tunnel == 6 and r.tiles == 13, dict(r)
    assert (r["from"].x, r["from"].y, r["from"].z) == (40, 25, 24), dict(r["from"])
    assert [(t.x, t.dig_text) for t in sorted((t for t in W.idx.values() if t.designated and t.z == 24),
                                              key=lambda t: t.x)] == [(x, "d1") for x in range(41, 47)] + [(47, "u1")]
    p = projects()[0]
    assert len(p.gallery) == 6 and p.area.x1 == 41 and p.area.x2 == 47, dict(p.area)
    W.dig_all()
    assert surface_entrances() == [(30, 25), (47, 25)], surface_entrances()


@test("way in: never beside water")
def _():
    # water under the ground east of the fort, x 41-42, z 26-29
    for z in range(26, 30):
        W.box(41, 0, 42, 63, z, LUA.table_from({"liquid": True, "shape": "FLOOR"}))
    r = way_in(x=46, y=25)
    assert r.ok, dict(r)
    x, y = column_of(r)
    assert x < 40 or x >= 44, (x, y)
    for t in W.idx.values():
        if t.designated:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = W.get(t.x + dx, t.y + dy, t.z)
                    assert not (n and n.liquid), (t.x, t.y, t.z)


@test("way in: never beside a cavern, nor through a building, nor through another AI project")
def _():
    W.box(41, 0, 41, 63, 27, LUA.table_from({"feature": True, "shape": "FLOOR"}))    # a cavern pocket
    W.box(36, 31, 44, 35, 30, LUA.table_from({"building": True}))                   # buildings outside, south
    W.persist["ai-overseer/projects"] = LUA.table_from({"next_id": 5, "list": LUA.table_from({
        1: LUA.table_from({"id": 4, "kind": "bedrooms", "phase": "dig",
                           "area": LUA.table_from({"x1": 20, "y1": 15, "x2": 44, "y2": 19, "z": 24})})})})
    r = way_in(x=46, y=25)
    assert r.ok, dict(r)
    x, y = column_of(r)
    assert abs(x - 41) > 1, (x, y)
    for t in W.idx.values():
        if t.designated:
            assert not (t.z == 24 and 20 <= t.x <= 44 and 15 <= t.y <= 19), (t.x, t.y, t.z)
            assert not t.building, (t.x, t.y, t.z)
    assert r.project_id == 5


@test("way in: more than 30 tiles of digging is refused, with the reason")
def _():
    W.SURF = 38
    W.idx = LUA.table()
    W.fort(6, 20, 20, 40, 30)
    W.scan_inside()
    W.persist["ai-overseer/founded"] = None
    W.GATES.entrances = LUA.table()
    r = way_in(x=46, y=25, z=38)
    assert not r.ok and r.rejected and "more than 30 tiles" in r.error and r.why == r.error, dict(r)
    assert designated() == [] and projects() == []


@test("way in: plain refusals: no ground there, already inside, in a cavern, nothing safe")
def _():
    r = way_in(x=46, y=25, z=20)                          # inside the rock
    assert not r.ok and "nobody can stand" in r.error, dict(r)
    r = way_in(x=25, y=25, z=24)                          # in the fort
    assert not r.ok and "already joins the fort" in r.error, dict(r)
    W.set(46, 25, 30, LUA.table_from({"feature": True}))
    r = way_in(x=46, y=25, z=30)
    assert not r.ok and "cavern" in r.error, dict(r)
    W.reset()
    for z in range(25, 30):                               # an aquifer over the whole fort
        W.box(0, 0, 63, 63, z, LUA.table_from({"aquifer": True}))
    r = way_in()
    assert not r.ok and r.error.startswith("no safe way in found") and "aquifer" in r.error, dict(r)
    assert designated() == [] and projects() == []


@test("way in: with no gate scan, the founding stair's walk group is the fort")
def _():
    W.use_gates = False
    r = way_in(dry=True)
    assert r.ok and column_of(r) == (41, 25), dict(r)
    W.persist["ai-overseer/founded"] = None
    real = B.find_stairs
    B.find_stairs = lambda n: (None, "no citizens")
    try:
        r = way_in(dry=True)
    finally:
        B.find_stairs = real
    assert not r.ok and "no fort to dig from" in r.error, dict(r)


if __name__ == "__main__":
    finish()
