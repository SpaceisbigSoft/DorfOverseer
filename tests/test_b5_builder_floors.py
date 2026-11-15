"""(layout B, group B5) lua/ai-builder-floors.lua: floor_site, the site of a new
level on a floor (a z-level with its 3-wide main hall out from the stair), and
the `env` through which the pure placement module sees the map.

On test_builder's fake fort, in a real Lua engine. The three pure modules
(ai-floorunits, ai-floorplan, ai-floorplace) and the sibling parts
(load_floors, floor_pile_units) are other groups' work: stand-ins that keep
the contract's shapes answer for them here (FM, below). One honest minimal
`place` puts each unit on the south side of an east run from u = 4 and asks
env.open / env.blocked / env.probe as the contract says; `survey` counts the
free columns each way through env; `compose` turns a placement into plain
dig cells.

    python tests/test_b5_builder_floors.py
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain" / "tools"))
from harness import finish, have_lua, make_test, skip  # noqa: E402

try:                                    # a drawing for a failure's message, when the helper is there
    from draw_level import render as _render
except Exception:                       # noqa: BLE001
    _render = None

LUA = B = W = TB = FM = None
if have_lua():
    import test_builder as TB  # noqa: E402  (its fake fort; its tests run only when it is run itself)
    LUA, B, W = TB.LUA, TB.B, TB.W

STANDINS = r"""
local B = ...
FM = {calls = {}, mods = {}}
local function add(set, x, y) set[x] = set[x] or {}; set[x][y] = true end

---------------------------------------------------------------- ai-floorunits
local U = {}
function U.unit_params(p)
  local out = {}
  for k, v in pairs(p) do out[k] = v end
  local st = {}
  for k, v in pairs(type(p.style) == 'table' and p.style or {}) do st[k] = v end
  st.orient, st.arms = 0, 'corridor'
  out.style = st
  if p.kind == 'workshops' or (p.kind == nil and p.shops) then out.spare, out.spare_for = 0, nil end
  return out
end
local function box(w, d, mode, tag, place)
  local mid = w // 2
  return {w = w, d = d, mode = mode, open = {mid, mid},
          dig = {{x = mid, y = 0, text = 'd'}, {x = 0, y = 1, text = ('d(%dx%d)'):format(w, d)}},
          build = {}, place = place or {}, zone = {}, rooms_at = {}, halls = {}, tag = tag}
end
function U.cut(L, params)
  FM.cut_n = (FM.cut_n or 0) + 1
  FM.cut_params = FM.cut_params or {}
  table.insert(FM.cut_params, params or false)
  if FM.cut_fn then return FM.cut_fn(L) end
  local units = {}
  if L.kind == 'workshops' then
    for _, r in ipairs(L.rooms_at) do
      table.insert(units, box(5, 5, 'room', r.text, r.text == 'pile' and {{x = 0, y = 1, text = 's(5x5)'}} or nil))
    end
  elseif L.kind == 'storage' then
    units[1] = box(5, 5, 'room', nil, {{x = 0, y = 1, text = 's(5x5)'}})
  elseif L.kind == 'bedrooms' then
    units = {box(3, 3, 'room'), box(3, 3, 'room')}
  else
    units[1] = box(7, 5, 'hall')
  end
  return units, {kind = L.kind, mode = units[1].mode, summary = L.summary, furniture = L.furniture,
                 style = L.style, engrave_all = L.engrave_all}
end
function U.xf_cell(T, c)
  return {x = T.a * c.x + T.b * c.y + T.tx, y = T.c * c.x + T.d * c.y + T.ty, text = c.text}
end
function U.compose(units0, info, placement, opts)
  -- puts[i].unit counts opts.extra_units first, then units (ai-floorunits' own numbering)
  local units = {}
  for _, u in ipairs(opts.extra_units or {}) do table.insert(units, u) end
  for _, u in ipairs(units0) do table.insert(units, u) end
  FM.compose_opts, FM.compose_units = opts, units
  if FM.compose_fn then return FM.compose_fn(units, info, placement, opts) end
  local L2 = {kind = info.kind, dig = {}, build = {}, place = {}, zone = {}, rooms_at = {}, smooth = {},
              engrave = {}, tiles = {}, halls = {}, furniture = {}, summary = {floor = placement.floor_id},
              style = info.style, orient = 0}
  local b
  local function dig(x, y, w, h, text)
    table.insert(L2.dig, {x = x, y = y, text = text})
    for dx = 0, w - 1 do for dy = 0, h - 1 do
      add(L2.tiles, x + dx, y + dy)
      b = b or {x1 = x, y1 = y, x2 = x, y2 = y}
      b.x1, b.y1 = math.min(b.x1, x + dx), math.min(b.y1, y + dy)
      b.x2, b.y2 = math.max(b.x2, x + dx), math.max(b.y2, y + dy)
    end end
  end
  for _, t in ipairs(placement.hall) do dig(t.x, t.y, 1, 1, 'd' .. opts.hall_pri) end
  for _, p in ipairs(placement.puts) do
    local u = units[p.unit]
    for _, c in ipairs(u.dig) do
      local w, h = c.text:match('%((%d+)x(%d+)%)')
      dig(c.x + p.T.tx, c.y + p.T.ty, tonumber(w) or 1, tonumber(h) or 1, c.text)
    end
    for _, c in ipairs(u.place) do table.insert(L2.place, U.xf_cell(p.T, c)) end
  end
  if FM.compose_extra then dig(FM.compose_extra.x, FM.compose_extra.y, 1, 1, 'd') end
  L2.bounds = b
  return L2
end

----------------------------------------------------------------- ai-floorplan
local P = {}
function P.find_floor(store, z, sx, sy)
  for _, f in ipairs(store.floors) do
    if f.z == z and f.stair.x == sx and f.stair.y == sy then return f end
  end
end
function P.new_floor(store, z, sx, sy, tick)
  return {id = store.next, z = z, stair = {x = sx, y = sy}, made = tick, runs = {}, slots = {}, full = {}}
end
function P.grammar(h)
  FM.hint = h
  return {gap = h.gap or 1, lead = h.lead or 2, ahead = 1, run_max = h.run_max or 30, run_min = h.run_min or 10,
          neck = h.neck == true, dirs = h.dirs, tries = 24, full_retry_days = h.full_retry_days or 28,
          pile_w = h.pile_w or 5, piles_new = h.piles_new or 1}
end
function P.claims(floor) return floor.claims or {} end

---------------------------------------------------------------- ai-floorplace
local PL = {}
local DIRS = {north = {0, -1}, east = {1, 0}, south = {0, 1}, west = {-1, 0}}
function FM.honest_survey(floor, G, env)
  local free = {}
  for name, d in pairs(DIRS) do
    local dx, dy = d[1], d[2]
    local px, py = -dy, dx
    local n = 0
    for u = 2, 61 do
      local x, y = u * dx, u * dy
      local ok = not env.blocked(x - math.abs(px), y - math.abs(py), x + math.abs(px), y + math.abs(py))
      for v = -1, 1 do
        local tx, ty = x + v * px, y + v * py
        if tx < env.bounds.x1 or tx > env.bounds.x2 or ty < env.bounds.y1 or ty > env.bounds.y2 then ok = false end
        if ok and env.open(tx, ty) == 'bad' then ok = false end
      end
      if not ok then break end
      n = n + 1
    end
    free[name] = n
  end
  return free
end
function PL.survey(floor, G, env)
  table.insert(FM.calls, {fn = 'survey', z = floor.z, sx = floor.stair.x, id = floor.id})
  FM.env = env
  if FM.survey_fn then return FM.survey_fn(floor, G, env) end
  return FM.honest_survey(floor, G, env)
end
function FM.honest_place(floor, req, G, env)
  local hall, known = {}, {}
  local function need(x, y)
    local s = env.open(x, y)
    if s == 'bad' then return false end
    add(known, x, y)
    if s == 'rock' then table.insert(hall, {x = x, y = y}) end
    return true
  end
  for x = -1, 1 do for y = -1, 1 do
    if not (x == 0 and y == 0) and not need(x, y) then return nil, "refused: the stair's hub" end
  end end
  local u = math.max(FM.u or 4, FM.ignore_min and 0 or (req.min_u or 0))
  local puts, rooms, last = {}, {}, u
  for i, unit in ipairs(req.units) do
    local rect = {x1 = u, y1 = 2, x2 = u + unit.w - 1, y2 = 2 + unit.d}
    if env.blocked(rect.x1, rect.y1, rect.x2, rect.y2) then return nil, 'no room' end
    local tiles = {}
    for bx = unit.open[1], unit.open[2] do table.insert(tiles, {x = u + bx, y = 2}) end
    for bx = 0, unit.w - 1 do for by = 1, unit.d do table.insert(tiles, {x = u + bx, y = 2 + by}) end end
    rooms[i] = tiles
    puts[i] = {unit = i, run = 1, side = 1, u = u, w = unit.w, d = unit.d, axial = false, role = unit.role,
               flag = unit.flag, T = {a = 1, b = 0, c = 0, d = 1, tx = u, ty = 2}, rect = rect}
    last = u + unit.w - 1
    u = u + unit.w + (G.gap or 1)
  end
  local E = last + (G.ahead or 1)
  if env.blocked(2, -1, E, 1) then return nil, 'no hall: north 0, east 0, south 0, west 0' end
  for c = 2, E do for v = -1, 1 do
    if not (G.neck and c == 2 and v ~= 0) and not need(c, v) then return nil, 'refused: a hall tile is taken' end
  end end
  if #hall > 0 then
    local ok, why = env.probe(hall, known, 'hall')
    if not ok then return nil, 'refused: ' .. tostring(why) end
  end
  local n = #hall
  for i in ipairs(puts) do
    local ok, why = env.probe(rooms[i], known, 'room')
    if not ok then return nil, 'refused: ' .. tostring(why) end
    n = n + #rooms[i]
  end
  return {floor_id = floor.id, new_floor = #floor.runs == 0, req = {kind = req.kind, tag = req.tag, group = req.group},
          puts = puts, hall = hall, hall_rects = {{x = 2, y = -1, w = E - 1, h = 3}},
          runs = {{id = 1, new = true, parent = 0, ox = 0, oy = 0, dx = 1, dy = 0, len_before = 0, len = E - 1,
                   walked = 0, tag = req.tag, node = 3, neck = G.neck}},
          neck = G.neck and {x = 2, y = 0} or nil, statues = {}, tiles = n, hall_new = #hall}
end
function PL.place(floor, req, G, env)
  table.insert(FM.calls, {fn = 'place', z = floor.z, sx = floor.stair.x, id = floor.id, req = req, G = G})
  if FM.place_fn then return FM.place_fn(floor, req, G, env) end
  return FM.honest_place(floor, req, G, env)
end

FM.mods = {['ai-floorunits'] = U, ['ai-floorplan'] = P, ['ai-floorplace'] = PL}
local real = reqscript
reqscript = function(name)
  if not FM.off and FM.mods[name] then return FM.mods[name] end
  return real(name)
end
FM.real = {now_tick = B.now_tick, walk_group = B.walk_group, seconds = B.FLOOR_SECONDS,
           scan = B.FLOOR_LEVELS_SCAN, try = B.FLOORS_TRY}
function FM.reset()
  FM.calls, FM.off = {}, false
  FM.cut_fn, FM.compose_fn, FM.survey_fn, FM.place_fn = nil, nil, nil, nil
  FM.compose_extra, FM.u, FM.ignore_min, FM.env, FM.hint, FM.cut_n, FM.cut_params = nil, nil, nil, nil, nil, 0, nil
  FM.store, FM.writable = {v = 1, next = 1, floors = {}}, true
  B.load_floors = function() return FM.store, FM.writable end
  B.floor_pile_units = nil
  B.now_tick, B.walk_group = FM.real.now_tick, FM.real.walk_group
  B.FLOOR_SECONDS, B.FLOOR_LEVELS_SCAN, B.FLOORS_TRY = FM.real.seconds, FM.real.scan, FM.real.try
end
return FM
"""

if TB is not None:
    FM = LUA.execute(STANDINS, B)

SIZE0 = (120, 120, 100)
SAME = LUA.eval("function(a, b) return rawequal(a, b) end") if LUA is not None else None


def _reset():
    if TB is None:
        skip("needs the lupa package (pip install lupa)")
    W.size = LUA.table_from(list(SIZE0))
    TB._reset(False)
    FM.reset()


test = make_test(before=_reset)


def tbl(v):
    if isinstance(v, dict):
        return LUA.table_from({k: tbl(x) for k, x in v.items()})
    if isinstance(v, (list, tuple)):
        return LUA.table_from([tbl(x) for x in v])
    return v


def lst(t):
    return [] if t is None else [t[i] for i in range(1, len(t) + 1)]


def fn(src):
    return LUA.eval(src)


def stair(x=60, y=60, top=80, bottom=60, cz=70):
    return {"x": x, "y": y, "z_top": top, "z_bottom": bottom, "count": 3, "len": top - bottom,
            "k": x * 100000 + y, "citizen_z": cz}


def fs(params, stairs=None, reserved=None, data=None, ceil=None):
    """floor_site -> (site, L2, None, None) or (None, None, why, marks)."""
    stairs = tbl(stairs if stairs is not None else [stair()])
    out = B.floor_site(tbl(params), stairs, tbl(reserved or []), data if data is not None else B.load_projects(), ceil)
    if not isinstance(out, tuple):
        out = (out,)
    out = tuple(out) + (None,) * (3 - len(out))
    if out[0] is not None:
        return out[0], out[1], None, None
    return None, None, out[1], out[2]


def calls(kind):
    return [c for c in lst(FM.calls) if c.fn == kind]


def env_at(z, floor=None, data=None, reserved=None, claims=None, st=None):
    floor = floor or {"id": 1, "z": z, "stair": {"x": 60, "y": 60}, "runs": [], "slots": []}
    return B.floor_env(tbl(floor), tbl(st or stair()), z, tbl(data or {"next_id": 1, "list": []}),
                       tbl(reserved or []), claims, None)


def tiles(*pts):
    return tbl([{"x": x, "y": y} for x, y in pts])


def col_set(pts):
    """{[x] = {[y] = true}} as the claims are."""
    t = LUA.table()
    for x, y in pts:
        if t[x] is None:
            t[x] = LUA.table()
        t[x][y] = True
    return t


def picture(L2):
    if _render is None or L2 is None:
        return ""
    try:
        return "\n" + _render([(x, y) for x, col in L2.tiles.items() for y in col.keys()])
    except Exception:  # noqa: BLE001
        return ""


def persisted():
    return json.dumps({k: str(dict(v)) if hasattr(v, "items") else str(v) for k, v in W.persist.items()}, sort_keys=True)


BED = {"kind": "bedrooms", "rooms": 2, "room_size": 3}


# ---------------------------------------------------------------- 1. the part loads

@test("the builder boots with the floors part: in PARTS, its version mark, no reqscript while loading")
def _():
    assert "floors" in lst(B.PARTS), lst(B.PARTS)
    assert B.PART_VERSIONS["ai-builder-floors"] == B.PART_VERSIONS["ai-builder"] == "0.105.54"
    assert LUA.eval("type")(B.floor_site) == "function" and LUA.eval("type")(B.floor_env) == "function"
    assert B.FLOOR_SECONDS == 1.5 and B.FLOORS_TRY == 3 and B.FLOOR_LEVELS_SCAN == 8 and B.FLOOR_STAIRS == 3
    kinds = dict(B.FLOOR_KINDS)
    assert len(kinds) == 15 and "farms" not in kinds and kinds["workshops"] is True
    tags = dict(B.FLOOR_TAGS)
    assert tags == {"bedrooms": "homes", "suites": "homes", "dining": "homes", "tavern": "homes", "hospital": "homes",
                    "temple": "halls", "library": "halls", "memorial": "halls", "garden": "halls", "tombs": "halls",
                    "jail": "defence", "barracks": "defence", "archery": "defence",
                    "storage": "storage", "workshops": "industry"}, tags
    assert set(tags) == set(kinds)
    src = (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8")
    assert "'floors'}      -- (layout B) hallway-first floors: the site on a floor" in src
    assert "'court',       -- (0.105.47)" in src


@test("without the three modules, or without load_floors, floor_site answers nil, 'the floor modules are not loaded'")
def _():
    FM.off = True                       # the fake fort's reqscript raises for the three names
    site, _, why, marks = fs(BED)
    assert site is None and why == "the floor modules are not loaded" and marks is None, why
    FM.off = False
    B.load_floors = None
    site, _, why, _ = fs(BED)
    assert site is None and why == "the floor modules are not loaded", why
    assert B.CACHE is None
    # a record from a newer version is only read: the level goes the classic way
    FM.reset()
    FM.writable = False
    site, _, why, _ = fs(BED)
    assert site is None and "newer" in why, why
    # floor = false: classic on purpose
    FM.reset()
    site, _, why, _ = fs(dict(BED, floor=False))
    assert site is None and calls("survey") == [], why


# ---------------------------------------------------------------- 2. env.probe

@test("env.probe: rock passes; aquifer, water on or above, open sky, a feature, the map's edge refuse with check_site's reason")
def _():
    z = 64
    env = env_at(z)
    room = tiles(*[(x, y) for x in range(5, 8) for y in range(5, 8)])
    assert env.probe(room, None, "room") is True
    assert env.probe(room, None, "hall") is True
    assert env.probe(tiles(), None, "room") is True
    cases = [({"aquifer": True}, 0, "aquifer at x66 y66"),
             ({"liquid": True}, 0, "water or magma at x66 y66"),
             ({"liquid": True}, 1, "water or magma directly above x66 y66"),
             ({"aquifer": True}, 1, "aquifer directly above x66 y66"),
             ({"outside": True}, 0, "open to the sky at x66 y66"),
             ({"feature": True}, 0, "cavern, magma sea or special vein at x66 y66"),
             ({"warm": True}, 0, "warm stone"),
             ({"designated": True}, 0, "already designated")]
    for fields, dz, want in cases:
        TB._reset(False)
        W.set(66, 66, z + dz, tbl(fields))
        ok, why = env_at(z).probe(room, None, "room")
        assert ok is False and want in why, (fields, dz, why)
    # the same on a border tile (beside the room, not in it)
    TB._reset(False)
    W.set(68, 66, z, tbl({"liquid": True}))
    ok, why = env_at(z).probe(room, None, "hall")
    assert ok is False and "water or magma at x68 y66" in why, why
    # beside the map's edge (stair-relative x = -59 is map x = 1: its border would be column 0)
    TB._reset(False)
    env = env_at(z)
    ok, why = env.probe(tiles((-59, 0)), None, "hall")
    assert ok is False and why == "too close to the map edge", why
    assert env.probe(tiles((-58, 0)), None, "hall") is True
    assert env.probe(tiles((57, 0)), None, "hall") is True          # map x = 117 = w - 3
    assert env.probe(tiles((58, 0)), None, "hall")[0] is False
    b = env.bounds
    assert (b.x1, b.y1, b.x2, b.y2) == (-58, -58, 57, 57), (b.x1, b.y1, b.x2, b.y2)
    # tiles as a set, as the claims are
    assert env.probe(col_set([(5, 5), (5, 6)]), None, "room") is True
    # the stair is never read, in the tiles' border or not
    assert env.probe(tiles((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)), None, "hall") is True


@test("env.probe: a room may not border the fort's open floor, a hall may; the floor's own known tiles are exempt for both")
def _():
    z = 70                                # the fort's floor: x 40..80, y 55..65 open
    env = env_at(z)
    beside = tiles((21, 0), (22, 0))      # map x 81, 82: the border x 80 is open floor
    ok, why = env.probe(beside, None, "room")
    assert ok is False and "not solid rock" in why and "x80" in why, why
    assert env.probe(beside, None, "hall") is True
    known = col_set([(20, -1), (20, 0), (20, 1)])
    assert env.probe(beside, known, "room") is True
    assert env.probe(beside, tiles((20, -1), (20, 0), (20, 1)), "room") is True      # known as a list
    ok, why = env.probe(beside, col_set([(20, 0)]), "room")                          # only one of the three
    assert ok is False, why
    # a hall may brush the open floor, not water, a room of a level, or a building
    W.set(80, 61, z, tbl({"liquid": True}))
    ok, why = env_at(z).probe(beside, None, "hall")
    assert ok is False and "x80 y61" in why, why
    W.set(80, 61, z, tbl({"liquid": False, "taken": True}))
    ok, why = env_at(z).probe(beside, None, "hall")
    assert ok is False and "x80 y61" in why, why
    # a tile that is itself open can never be dug, whatever the role
    ok, why = env_at(z).probe(tiles((20, 0)), None, "hall")
    assert ok is False and "not solid rock" in why, why
    # an open tile meeting the dig only at a corner (no wall or door closes it): refused for a hall too
    TB._reset(False)
    W.set(70, 70, 64, tbl({"shape": "FLOOR"}))
    ok, why = env_at(64).probe(tiles((11, 11)), None, "hall")
    assert ok is False and "only at a corner" in why, why


@test("env.probe: another open project's area refuses, a project of this floor does not")
def _():
    z = 64
    room = tiles(*[(x, y) for x in range(5, 8) for y in range(5, 8)])
    area = {"x1": 60, "y1": 60, "x2": 75, "y2": 75, "z": z}
    other = {"id": 7, "kind": "dining", "phase": "dig", "z": z, "area": area, "stair": {"x": 60, "y": 60}}
    ok, why = env_at(z, data={"next_id": 8, "list": [other]}, reserved=[area]).probe(room, None, "room")
    assert ok is False and why == "overlaps another AI project", why
    # the same box on another level reserves nothing here
    ok = env_at(z, data={"next_id": 8, "list": [other]}, reserved=[dict(area, z=z + 1)]).probe(room, None, "room")
    assert ok is True
    mine = dict(other, floor={"id": 1, "slots": 2, "hall": 30})
    assert env_at(z, data={"next_id": 8, "list": [mine]}, reserved=[area]).probe(room, None, "room") is True
    # the very table start_project hands on (the project's own area), not only an equal one
    data = tbl({"next_id": 8, "list": [mine]})
    res = LUA.eval("function(d) return {d.list[1].area} end")(data)
    env = B.floor_env(tbl({"id": 1, "z": z, "slots": []}), tbl(stair()), z, data, res, None, None)
    assert env.probe(room, None, "room") is True
    # another floor's project (another id, or the same id on another stair) still reserves
    for p in (dict(mine, floor={"id": 2}), dict(mine, stair={"x": 30, "y": 60})):
        ok, why = env_at(z, data={"next_id": 8, "list": [p]}, reserved=[area]).probe(room, None, "room")
        assert ok is False and why == "overlaps another AI project", why
    # a reserve that is no listed project's (a level given up as out of reach) holds too
    ok, why = env_at(z, reserved=[area]).probe(room, None, "room")
    assert ok is False, why


# ---------------------------------------------------------------- 3. env.open

@test("env.open: rock; the fort's open floor; a room of an AI level, a building or zone, water, outside, another walk group -> bad")
def _():
    assert env_at(64).open(5, 5) == "rock"
    z = 70
    env = env_at(z)
    assert env.open(5, 0) == "open" and env.open(-20, -5) == "open"
    assert env.open(30, 0) == "rock"                       # past the fort's floor
    assert env.open(500, 0) == "bad"                       # off the map
    level = {"id": 3, "kind": "bedrooms", "phase": "done", "z": z, "anchor": {"x": 60, "y": 60},
             "area": {"x1": 64, "y1": 61, "x2": 68, "y2": 65, "z": z},
             "cells": {"zone": [{"x": 5, "y": 2, "text": "b(3x3)"}], "dig": [], "build": [], "place": []}}
    env = env_at(z, data={"next_id": 4, "list": [level]})
    assert env.open(5, 2) == "bad" and env.open(7, 4) == "bad", "a bedroom's tiles"
    assert env.open(8, 2) == "open" and env.open(5, 1) == "open"
    assert env_at(z + 1, data={"next_id": 4, "list": [level]}).open(5, 2) == "open"       # another level's room
    for fields in ({"taken": True}, {"liquid": True}, {"outside": True}, {"aquifer": True}, {"feature": True}):
        TB._reset(False)
        W.set(65, 60, z, tbl(fields))
        assert env_at(z).open(5, 0) == "bad", fields
    TB._reset(False)
    W.set(65, 60, z, tbl({"zones": LUA.table_from(["Bedroom"])}))
    B.tile_taken = fn("function(x, y, z) return B.building_at(x, y, z) or #B.zone_types(x, y, z) > 0 end".replace("B.", "ZB."))
    LUA.globals().ZB = B
    try:
        assert env_at(z).open(5, 0) == "bad", "a zone"
        assert env_at(z).open(6, 0) == "open"
    finally:
        B.tile_taken = fn("function(x, y, z) local t = ZW.peek(x, y, z); return t ~= nil and t.taken == true end")
        LUA.globals().ZW = W
    # designated rock is neither rock (to dig) nor open
    TB._reset(False)
    W.set(65, 65, 64, tbl({"designated": True}))
    assert env_at(64).open(5, 5) == "bad"
    # an open tile the stair's dwarves cannot walk to (another walk group); a dug pocket on a rock level
    LUA.globals().ZREAL = B.walk_group
    B.walk_group = fn("function(x, y, z) if x == 65 and y == 60 then return 2 end return ZREAL(x, y, z) end")
    assert env_at(z).open(5, 0) == "bad" and env_at(z).open(6, 0) == "open"
    B.walk_group = fn("function(x, y, z) return 0 end")           # the stair itself not walkable: nothing is open
    assert env_at(z).open(6, 0) == "bad" and env_at(64).open(8, 8) == "rock"


# ---------------------------------------------------------------- 4. env.blocked

@test("env.blocked: other projects' tiles on this z in any phase (area less its border, areas whole); not this floor's; old_areas unless the floor's own")
def _():
    z = 64

    def proj(pid, phase, **kw):
        p = {"id": pid, "kind": "dining", "phase": phase, "z": z, "stair": {"x": 60, "y": 60},
             "area": {"x1": 70, "y1": 50, "x2": 80, "y2": 58, "z": z}}
        p.update(kw)
        return p

    for phase in ("dig", "furnish", "decorate", "done", "cancelled"):
        env = env_at(z, data={"next_id": 9, "list": [proj(4, phase)]})
        # the area's tiles are x 71..79, y 51..57 (map), 11..19, -9..-3 (stair-relative)
        assert env.blocked(11, -9, 19, -3) is True, phase
        assert env.blocked(19, -3, 25, 5) is True and env.blocked(0, -20, 11, -9) is True, phase
        assert env.blocked(20, -9, 25, -3) is False, "its border is rock, not its tiles"
        assert env.blocked(11, -2, 19, 3) is False and env.blocked(2, -1, 10, 1) is False, phase
        assert env.blocked(tbl({"x1": 11, "y1": -9, "x2": 19, "y2": -3})) is True, "a box as one table"
        assert env.blocked(19, -3, 11, -9) is True, "corners either way round"
    # `areas` (a second box: a new hall's, an extension's) are kept whole
    env = env_at(z, data={"next_id": 9, "list": [proj(4, "done", areas=[{"x1": 40, "y1": 40, "x2": 45, "y2": 42, "z": z}])]})
    assert env.blocked(-20, -20, -20, -20) is True and env.blocked(-15, -18, -15, -18) is True
    assert env.blocked(-14, -18, -14, -18) is False
    # a way in's column: a box on this level counts though the project's own z is another
    env = env_at(z, data={"next_id": 9, "list": [proj(4, "done", z=70, area={"x1": 1, "y1": 1, "x2": 9, "y2": 9, "z": 70},
                                                      areas=[{"x1": 40, "y1": 40, "x2": 45, "y2": 42, "z": z}])]})
    assert env.blocked(-20, -20, -20, -20) is True and env.blocked(-58, -58, -52, -52) is False
    # nothing on another z
    env = env_at(z + 1, data={"next_id": 9, "list": [proj(4, "done")]})
    assert env.blocked(-58, -58, 57, 57) is False
    # a project of this floor does not block it; another floor's, or the id on another stair, does
    mine = proj(4, "done", floor={"id": 1, "slots": 1, "hall": 9}, areas=[{"x1": 61, "y1": 58, "x2": 72, "y2": 62, "z": z}])
    assert env_at(z, data={"next_id": 9, "list": [mine]}).blocked(-58, -58, 57, 57) is False
    assert env_at(z, data={"next_id": 9, "list": [dict(mine, floor={"id": 2})]}).blocked(11, -9, 19, -3) is True
    assert env_at(z, data={"next_id": 9, "list": [dict(mine, stair={"x": 30, "y": 60})]}).blocked(11, -9, 19, -3) is True
    # a 1-tile project (a well's box has no border to take off)
    env = env_at(z, data={"next_id": 9, "list": [proj(5, "done", area={"x1": 90, "y1": 90, "x2": 90, "y2": 90, "z": z})]})
    assert env.blocked(30, 30, 30, 30) is True and env.blocked(31, 30, 31, 30) is False
    # a broken record blocks nothing and breaks nothing
    env = env_at(z, data={"next_id": 9, "list": [proj(6, "done", area="x"), proj(7, "done", area={"x1": 5})]})
    assert env.blocked(-58, -58, 57, 57) is False


@test("env.blocked: a dropped level's outline blocks, unless it is the floor's own (its edges on the floor's claims)")
def _():
    z = 64
    old = {"x1": 70, "y1": 50, "x2": 80, "y2": 58, "z": z}
    data = {"next_id": 1, "list": [], "old_areas": [old, dict(old, z=z + 3)]}
    env = env_at(z, data=data)
    assert env.blocked(10, -10, 20, -2) is True, "the outline whole, border and all"
    assert env.blocked(21, -10, 30, -2) is False and env.blocked(10, -1, 20, 5) is False
    assert env_at(z + 1, data=data).blocked(-58, -58, 57, 57) is False
    assert env_at(z + 3, data=data).blocked(10, -10, 20, -2) is True
    # the floor's own dropped project: two rooms 11..13 and 17..19 south of the hall, a rock gap between them,
    # the box round them plus one tile (10..20, 1..6); and its hall's box
    rooms = [(x, y) for x in (11, 12, 13, 17, 18, 19) for y in (3, 4, 5)] + [(12, 2), (18, 2)]
    hall = [(x, y) for x in range(2, 21) for y in (-1, 0, 1)]
    claims = col_set(rooms + hall + [(x, y) for x in (-1, 0, 1) for y in (-1, 0, 1)])
    own = {"x1": 70, "y1": 61, "x2": 80, "y2": 66, "z": z}
    own_hall = {"x1": 61, "y1": 58, "x2": 81, "y2": 62, "z": z}
    data = {"next_id": 1, "list": [], "old_areas": [own, own_hall]}
    assert env_at(z, data=data, claims=claims).blocked(-58, -58, 57, 57) is False
    assert env_at(z, data=data).blocked(11, 3, 13, 5) is True, "without the claims it is another's"
    # an outline that only overlaps the claims is another's
    data = {"next_id": 1, "list": [], "old_areas": [{"x1": 70, "y1": 61, "x2": 84, "y2": 70, "z": z}]}
    assert env_at(z, data=data, claims=claims).blocked(11, 3, 13, 5) is True
    # one that touches no claim at all, inside the floor's reach, is another's
    data = {"next_id": 1, "list": [], "old_areas": [{"x1": 73, "y1": 66, "x2": 77, "y2": 70, "z": z}]}
    assert env_at(z, data=data, claims=claims).blocked(14, 7, 16, 9) is True


# ---------------------------------------------------------------- 5. the six forts

FORTS = sorted((ROOT / "tests" / "fixtures" / "live").glob("*-levels.json"))
DIRS = {"east": (1, 0), "west": (-1, 0), "south": (0, 1), "north": (0, -1)}


def free_runs(sx, sy, boxes, size, cap=60):
    out = {}
    for name, (dx, dy) in DIRS.items():
        px, py = -dy, dx
        n = 0
        for u in range(2, 2 + cap):
            ts = [(sx + u * dx + v * px, sy + u * dy + v * py) for v in (-1, 0, 1)]
            if any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in boxes for x, y in ts):
                break
            if any(not (2 <= x <= size[0] - 3 and 2 <= y <= size[1] - 3) for x, y in ts):
                break
            n += 1
        out[name] = n
    return out


def fort_data(d, old_half, cancelled=True):
    """The fort's levels as saved projects; with old_half every second one only as a dropped outline."""
    plist, old = [], []
    for i, lv in enumerate(d["levels"]):
        if not cancelled and lv.get("state") == "cancelled":
            continue
        b = lv["bounds"]
        area = {"x1": b["x1"] - 1, "y1": b["y1"] - 1, "x2": b["x2"] + 1, "y2": b["y2"] + 1, "z": lv["z"]}
        if old_half and i % 2 == 1:
            old.append(area)
        else:
            plist.append({"id": lv["id"], "kind": lv["kind"], "phase": {"done": "done", "cancelled": "cancelled"}.get(lv.get("state"), "dig"),
                          "z": lv["z"], "area": area, "stair": {"x": d["stair"]["x"], "y": d["stair"]["y"]},
                          "anchor": {"x": b["x1"], "y": b["y1"]}})
    return {"next_id": 999, "list": plist, "old_areas": old}


def fort_boxes(d, z, old_half):
    out = []
    for i, lv in enumerate(d["levels"]):
        if lv["z"] == z:
            b = lv["bounds"]
            g = 1 if (old_half and i % 2 == 1) else 0       # a dropped outline keeps its border
            out.append((b["x1"] - g, b["y1"] - g, b["x2"] + g, b["y2"] + g))
    return out


@test("the six forts: env.blocked agrees with every standing level's box, as projects and as dropped outlines; the free runs are the survey's")
def _():
    assert len(FORTS) == 6, FORTS
    rng = random.Random(5)
    for path in FORTS:
        d = json.loads(path.read_text(encoding="utf-8"))
        size = d["map"]["size"]
        W.size = LUA.table_from(size)
        W.reset()
        sx, sy = d["stair"]["x"], d["stair"]["y"]
        st = stair(sx, sy, top=d["stair"]["z_top"], bottom=min(lv["z"] for lv in d["levels"]), cz=165)
        for old_half in (False, True):
            data = tbl(fort_data(d, old_half))
            for zs, run in d["hall_runs"].items():
                z = int(zs)
                floor = tbl({"id": 1, "z": z, "stair": {"x": sx, "y": sy}, "runs": [], "slots": []})
                env = B.floor_env(floor, tbl(st), z, data, tbl([]), None, None)
                boxes = fort_boxes(d, z, old_half)
                assert boxes, (path.name, z)
                for b in boxes:
                    assert env.blocked(b[0] - sx, b[1] - sy, b[2] - sx, b[3] - sy) is True, (path.name, z, b)
                for _ in range(60):
                    x1, y1 = sx + rng.randint(-70, 70), sy + rng.randint(-70, 70)
                    x2, y2 = x1 + rng.randint(0, 6), y1 + rng.randint(0, 6)
                    want = any(x1 <= b[2] and b[0] <= x2 and y1 <= b[3] and b[1] <= y2 for b in boxes)
                    assert env.blocked(x1 - sx, y1 - sy, x2 - sx, y2 - sy) is want, (path.name, z, (x1, y1, x2, y2))
                free = dict(FM.honest_survey(floor, None, env))
                assert free == free_runs(sx, sy, boxes, size), (path.name, z, old_half, free)
                if not old_half:        # the survey of the live forts (59 tiles out, cancelled levels not counted)
                    env = B.floor_env(floor, tbl(st), z, tbl(fort_data(d, False, cancelled=False)), tbl([]), None, None)
                    free = dict(FM.honest_survey(floor, None, env))
                    live = {k: v["free"] for k, v in run["dirs"].items()}
                    assert {k: min(v, 59) for k, v in free.items()} == live, (path.name, z, free, live)


@test("the six forts: a level whose hub lies in a standing level with no direction free is marked '*' and the next level is tried")
def _():
    found = 0
    for path in FORTS:
        d = json.loads(path.read_text(encoding="utf-8"))
        shut = [int(z) for z, run in d["hall_runs"].items()
                if run["hub_in_boxes"] and all(v["free"] == 0 for v in run["dirs"].values())]
        if not shut:
            continue
        found += 1
        size = d["map"]["size"]
        W.size = LUA.table_from(size)
        W.reset()
        FM.reset()
        sx, sy = d["stair"]["x"], d["stair"]["y"]
        used = {lv["z"] for lv in d["levels"]}
        clear = next(z for z in range(d["stair"]["z_top"] - 1, 100, -1) if z not in used)
        st = stair(sx, sy, top=d["stair"]["z_top"], bottom=min(min(used), clear), cz=165)
        B.walk_group = fn("function(x, y, z) return 1 end")
        # the scripted place: no hall where no direction has run_min free columns, else the honest one
        FM.place_fn = fn("""function(floor, req, G, env)
          local f = FM.honest_survey(floor, G, env)
          if math.max(f.north, f.east, f.south, f.west) < G.run_min then
            return nil, ('no hall: north %d, east %d, south %d, west %d'):format(f.north, f.east, f.south, f.west)
          end
          return FM.honest_place(floor, req, G, env)
        end""")
        z0 = shut[0]
        site, L2, why, marks = fs(dict(BED, floor={"elevs": [z0, clear]}), stairs=[st], data=tbl(fort_data(d, True)))
        assert site is not None, (path.name, why)
        assert site.z == clear and [c.z for c in calls("survey")] == [z0, clear], (path.name, site.z)
        ms = lst(site._commit.marks)
        assert len(ms) == 1 and ms[0].z == z0 and ms[0].tag == "*" and (ms[0].sx, ms[0].sy) == (sx, sy), path.name
        assert {k: ms[0].free[k] for k in DIRS} == {k: 0 for k in DIRS}, dict(ms[0].free)
        # and with no other level offered: nil, the reason and the mark
        FM.calls = LUA.table()
        site, _, why, marks = fs(dict(BED, floor={"elevs": [z0]}), stairs=[st], data=tbl(fort_data(d, False)))
        assert site is None and why == f"z{z0}: no hall: north 0, east 0, south 0, west 0", why
        assert [(m.z, m.tag) for m in lst(marks)] == [(z0, "*")]
    assert found >= 3, found


# ---------------------------------------------------------------- 6. which stair

@test("which stair: the hint's spine first when it is a usable stair, else stairs[1]; a second stair when the first has no room")
def _():
    TB._stair(30, 60, 60, 80)
    s1, s2 = stair(), stair(30, 60)
    site, L2, why, _ = fs(dict(BED, floor={"elevs": [64]}), stairs=[s1, s2])
    assert site is not None and site.stair.x == 60 and calls("survey")[0].sx == 60, why
    FM.reset()
    site, L2, why, _ = fs(dict(BED, floor={"elevs": [64], "spine": {"x": 30, "y": 60}}), stairs=[s1, s2])
    assert site is not None and (site.stair.x, site.stair.y) == (30, 60), why
    assert (site.anchor.x, site.anchor.y) == (30, 60) and (site.floor_result.stair.x, site.floor_result.stair.y) == (30, 60)
    assert calls("survey")[0].sx == 30 and len(calls("survey")) == 1
    assert site._commit.floor.stair.x == 30
    # a spine that is no stair: the stairs in their own order
    FM.reset()
    site, _, why, _ = fs(dict(BED, floor={"elevs": [64], "spine": {"x": 99, "y": 99}}), stairs=[s1, s2])
    assert site is not None and site.stair.x == 60, why
    # a spine that is a stair the list did not have (a district's own stairwell): found and tried first
    FM.reset()
    site, _, why, _ = fs(dict(BED, floor={"elevs": [64], "spine": {"x": 30, "y": 60}}), stairs=[s1])
    assert site is not None and site.stair.x == 30 and site.stair.z_bottom == 60, why
    # the first stair has no room: the second takes the level, and the site is the second's
    FM.reset()
    FM.place_fn = fn("""function(floor, req, G, env)
      if floor.stair.x == 60 then return nil, 'no room' end
      return FM.honest_place(floor, req, G, env)
    end""")
    site, L2, why, _ = fs(dict(BED, floor={"elevs": [64]}), stairs=[s1, s2])
    assert site is not None and [c.sx for c in calls("place")] == [60, 30], why
    assert (site.stair.x, site.anchor.x, site.floor_result.stair.x) == (30, 30, 30)
    assert site.area.x1 == 30 + 4 - 1 and [(m.sx, m.tag) for m in lst(site._commit.marks)] == [(60, "homes")]
    # FLOOR_STAIRS at most
    FM.reset()
    for x in (20, 25):
        TB._stair(x, 60, 60, 80)
    FM.place_fn = fn("function() return nil, 'no hall: nowhere' end")
    site, _, why, marks = fs(dict(BED, floor={"elevs": [64]}), stairs=[s1, s2, stair(20, 60), stair(25, 60)])
    assert site is None and [c.sx for c in calls("survey")] == [60, 30, 20], why
    assert why.count("no hall") == 3 and len(lst(marks)) == 3


# ---------------------------------------------------------------- 7. which levels

NO_HALL = "function() return nil, 'no hall: north 0, east 0, south 0, west 0' end"


@test("which levels: the hint's elevations in order; else the plan's band, target first; else nearest the dwarves; never above the ceiling")
def _():
    FM.place_fn = fn(NO_HALL)
    fs(dict(BED, floor={"elevs": [64, 62, 63]}))
    assert [c.z for c in calls("survey")] == [64, 62, 63]
    # the hint wins over the plan
    FM.reset(); FM.place_fn = fn(NO_HALL)
    plan = {"elev_lo": 61, "elev_hi": 64, "elev_target": 63}
    fs(dict(BED, floor={"elevs": [65]}, plan=plan))
    assert [c.z for c in calls("survey")] == [65]
    # no hint: the plan's band, nearest its target (the higher of two as near first)
    FM.reset(); FM.place_fn = fn(NO_HALL)
    site, _, why, marks = fs(dict(BED, plan=plan))
    assert [c.z for c in calls("survey")] == [63, 64, 62, 61], why
    # a hint without elevations: the band too
    FM.reset(); FM.place_fn = fn(NO_HALL)
    fs(dict(BED, plan=plan, floor={"tag": "halls"}))
    assert [c.z for c in calls("survey")] == [63, 64, 62, 61]
    # neither: the stair's levels nearest the dwarves (z 70), FLOOR_LEVELS_SCAN of them
    FM.reset(); FM.place_fn = fn(NO_HALL)
    site, _, why, marks = fs(BED)
    zs = [c.z for c in calls("survey")]
    assert len(zs) == 8 == B.FLOOR_LEVELS_SCAN and zs[0] == 70 and len(set(zs)) == 8 and max(abs(z - 70) for z in zs) == 4, zs
    assert [abs(z - 70) for z in zs] == sorted(abs(z - 70) for z in zs)
    assert len(lst(marks)) == 8 and len(why) <= 300
    # never above the ceiling
    FM.reset(); FM.place_fn = fn(NO_HALL)
    fs(dict(BED, floor={"elevs": [65, 64, 63, 62]}), ceil=63)
    assert [c.z for c in calls("survey")] == [63, 62]
    FM.reset(); FM.place_fn = fn(NO_HALL)
    fs(BED, ceil=68)
    assert max(c.z for c in calls("survey")) == 68 and calls("survey")[0].z == 68
    # a level the stair does not reach (above its top) is not a floor of it
    FM.reset(); FM.place_fn = fn(NO_HALL)
    site, _, why, marks = fs(dict(BED, floor={"elevs": [85, 90]}))
    assert site is None and calls("survey") == [] and why == "no level of the stairs to try" and lst(marks) == []


@test("which levels: under the stair's bottom only after the reached ones, within reach, check_extension passing; extend = true")
def _():
    FM.place_fn = fn("""function(floor, req, G, env)
      if floor.z >= 60 then return nil, 'no room' end
      return FM.honest_place(floor, req, G, env)
    end""")
    site, L2, why, _ = fs(dict(BED, floor={"elevs": [59, 61]}))
    assert site is not None and [c.z for c in calls("survey")] == [61, 59], why
    assert site.z == 59 and site.extend is True and site.floor_result.elevation == 59
    assert L2.tiles[1][0] is True and L2.tiles[0] is None or L2.tiles[0][0] is None, "the hub is dug, never the stair tile"
    # a reached level: extend is false
    FM.reset()
    site, _, why, _ = fs(dict(BED, floor={"elevs": [61]}))
    assert site is not None and site.extend is False and site.z == 61
    # the stair cannot go down (an aquifer in its way): the level is not tried
    FM.reset()
    W.set(60, 60, 59, tbl({"aquifer": True}))
    site, _, why, marks = fs(dict(BED, floor={"elevs": [59]}))
    assert site is None and calls("survey") == [] and "stairs down to z59: aquifer" in why and lst(marks) == [], why
    # within the plan's reach only: PLAN_EXTEND (3) levels, or the band's own `extend`
    TB._reset(False); FM.reset(); FM.place_fn = fn(NO_HALL)
    fs(dict(BED, floor={"elevs": [55, 56, 57, 58, 59, 60]}))
    assert [c.z for c in calls("survey")] == [60, 57, 58, 59]
    FM.reset(); FM.place_fn = fn(NO_HALL)
    fs(dict(BED, floor={"elevs": [54, 55, 60]}, plan={"elev_lo": 50, "elev_hi": 60, "extend": 5}))
    assert [c.z for c in calls("survey")] == [60, 55]
    # no hint, a band under the stair: the stair goes down to it
    FM.reset()
    site, _, why, _ = fs(dict(BED, plan={"elev_lo": 58, "elev_hi": 59, "elev_target": 58}))
    assert site is not None and site.z == 58 and site.extend is True and site.in_district is True, why


@test("which levels: at most FLOORS_TRY floors really tried (a floor with no hall costs only its survey), FLOOR_LEVELS_SCAN looked at")
def _():
    FM.place_fn = fn("function() return nil, 'no room' end")
    site, _, why, marks = fs(dict(BED, floor={"elevs": [65, 64, 63, 62, 61, 60]}))
    assert site is None and [c.z for c in calls("place")] == [65, 64, 63], why
    assert why == "z65: no room; z64: no room; z63: no room"
    assert [(m.z, m.tag) for m in lst(marks)] == [(65, "homes"), (64, "homes"), (63, "homes")]
    # 'refused' counts as a try and leaves no mark
    FM.reset(); FM.place_fn = fn("function() return nil, 'refused: aquifer at x1 y2 z3' end")
    site, _, why, marks = fs(dict(BED, floor={"elevs": [65, 64, 63, 62]}))
    assert len(calls("place")) == 3 and lst(marks) == [] and why.startswith("z65: refused: aquifer at x1 y2 z3; z64"), why
    # no hall: not a try
    FM.reset(); FM.place_fn = fn("""function(floor) if floor.z > 62 then return nil, 'no hall: none' end
      return nil, 'no room' end""")
    site, _, why, marks = fs(dict(BED, floor={"elevs": [65, 64, 63, 62, 61, 60]}))
    assert [c.z for c in calls("place")] == [65, 64, 63, 62, 61, 60], why
    assert [m.tag for m in lst(marks)] == ["*", "*", "*", "homes", "homes", "homes"]
    # the limits are the part's own numbers
    FM.reset(); FM.place_fn = fn(NO_HALL); B.FLOOR_LEVELS_SCAN = 2
    fs(dict(BED, floor={"elevs": [65, 64, 63]}))
    assert len(calls("survey")) == 2
    FM.reset(); FM.place_fn = fn("function() return nil, 'no room' end"); B.FLOORS_TRY = 1
    fs(dict(BED, floor={"elevs": [65, 64, 63]}))
    assert len(calls("place")) == 1
    # the reasons, 300 characters at most
    FM.reset(); FM.place_fn = fn("function() return nil, 'refused: ' .. ('x'):rep(400) end")
    site, _, why, _ = fs(dict(BED, floor={"elevs": [65, 64]}))
    assert site is None and len(why) == 300, len(why)


# ---------------------------------------------------------------- 8. full floors, marks

@test("a floor marked full for the tag (or '*') less than full_retry_days ago is skipped; no room / no hall come back in marks with the survey's free")
def _():
    day = 1200

    def store(full):
        FM.store = tbl({"v": 1, "next": 2, "floors": [
            {"id": 1, "z": 64, "stair": {"x": 60, "y": 60}, "made": 5, "runs": [], "slots": [], "full": full}]})

    B.now_tick = fn("function() return 100 * 1200 end")
    for full in ({"homes": 80 * day}, {"*": 99 * day}, {"homes": 100 * day}):
        FM.reset(); B.now_tick = fn("function() return 100 * 1200 end")
        store(full)
        site, _, why, marks = fs(dict(BED, floor={"elevs": [64, 63]}))
        assert site is not None and site.z == 63 and [c.z for c in calls("survey")] == [63], (full, why)
        assert lst(site._commit.marks) == [], "a skipped floor is not marked again"
    FM.reset(); B.now_tick = fn("function() return 100 * 1200 end")
    store({"homes": 80 * day})
    site, _, why, marks = fs(dict(BED, floor={"elevs": [64]}))
    assert site is None and why == "floor 1: full for homes" and lst(marks) == [], why
    FM.reset(); B.now_tick = fn("function() return 100 * 1200 end")
    store({"*": 80 * day})
    site, _, why, marks = fs(dict(BED, floor={"elevs": [64]}))
    assert site is None and why == "floor 1: no hall can start here", why
    # long enough ago, or full for another tag: tried again (on the record's own floor)
    for full in ({"homes": 72 * day}, {"*": 71 * day}, {"industry": 99 * day}, {}):
        FM.reset(); B.now_tick = fn("function() return 100 * 1200 end")
        store(full)
        site, _, why, _ = fs(dict(BED, floor={"elevs": [64, 63]}))
        assert site is not None and site.z == 64 and site.floor.id == 1 and site.floor_result.new_floor is False, (full, why)
        assert site._commit.floor.id == 1 and site._commit.store.next == 2
    # the hint's own retry time
    FM.reset(); B.now_tick = fn("function() return 100 * 1200 end")
    store({"homes": 80 * day})
    site, _, why, _ = fs(dict(BED, floor={"elevs": [64], "full_retry_days": 10}))
    assert site is not None and site.z == 64, why
    # the marks: z, the stair, the tag ('*' for no hall), the survey's free run each way and its tick
    FM.reset(); B.now_tick = fn("function() return 4242 end")
    FM.place_fn = fn("""function(floor) if floor.z == 70 then return nil, 'no hall: none' end
      return nil, 'no room' end""")
    site, _, why, marks = fs(dict(BED, floor={"elevs": [70, 64], "tag": "halls"}))
    ms = lst(marks)
    assert site is None and [(m.z, m.sx, m.sy, m.tag) for m in ms] == [(70, 60, 60, "*"), (64, 60, 60, "halls")], why
    assert dict(ms[1].free) == {"north": 57, "east": 56, "south": 56, "west": 57, "tick": 4242}, dict(ms[1].free)
    assert ms[0].free.east == 56 and ms[0].free.tick == 4242, dict(ms[0].free)     # open floor counts as free
    assert why == "z70: no hall: none; z64: no room"


# ---------------------------------------------------------------- 9. workshops

PILES = """function(params, hint, has_flag)
  ZP = {hint = hint, shops = params.shops, had = has_flag('stone')}
  if has_flag('stone') then return {} end
  return {{flag = 'stone', shop = 'Masons', room_size = hint.pile_w, output = false}}
end"""


@test("workshops: floor_pile_units' pile room goes first (role pile, its flag), together; without it no pile; the ore_piles custom's room keeps role pile")
def _():
    B.floor_pile_units = fn(PILES)
    site, L2, why, _ = fs({"kind": "workshops", "shops": ["Masons"], "floor": {"elevs": [64], "pile_w": 5}})
    assert site is not None, why
    req = calls("place")[0].req
    units = lst(req.units)
    assert [(u.role, u.flag, u.w, u.d) for u in units] == [("pile", "stone", 5, 5), ("shop", None, 5, 5)]
    assert (units[0].open[1], units[0].open[2]) == (2, 2)
    assert req.together is True and req.kind == "workshops" and req.tag == "industry" and req.group == "crafts"
    assert req.zone == "any" and req.axial is False and req.min_u is None
    zp = LUA.globals().ZP
    assert zp.hint.pile_w == 5 and zp.hint.piles_new == 1 and zp.hint.tag == "industry" and zp.had is False
    assert [(p.x, p.y, p.flag, p.shop) for p in lst(site.floor.piles)] == [(4, 3, "stone", "Masons")]
    assert lst(site.floor_result.piles) == ["stone"] and site.floor_result.units == 2 and site.floor.slots == 2
    assert [(c.x, c.y, c.text) for c in lst(L2.place)] == [(4, 3, "s(5x5)")], "the pile's cell came through compose"
    assert len(lst(FM.compose_units)) == 2 and FM.compose_units[1].place[1].text == "s(5x5)"
    assert FM.compose_units[2].tag == "shop:Masons"
    assert len(lst(FM.compose_opts.extra_units)) == 1 and FM.compose_opts.extra_units[1].place[1].text == "s(5x5)"
    cp = lst(FM.cut_params)       # cut(L, params): the level's own params (kind, style) and each pile room's
    assert [p.kind for p in cp] == ["workshops", "storage"] and cp[0].spare == 0 and cp[1].piles[1] == "stone"
    # the floor already has a live stone pile on the tag's hall: has_flag says so, no second one
    for slot, want in (({"role": "pile", "flag": "stone", "tag": "industry"}, True),
                       ({"role": "pile", "flag": "stone", "tag": "industry", "dead": True}, False),
                       ({"role": "pile", "flag": "wood", "tag": "industry"}, False),
                       ({"role": "pile", "flag": "stone", "tag": "homes"}, False),
                       ({"role": "shop", "flag": "stone", "tag": "industry"}, False)):
        FM.reset(); B.floor_pile_units = fn(PILES)
        FM.store = tbl({"v": 1, "next": 2, "floors": [
            {"id": 1, "z": 64, "stair": {"x": 60, "y": 60}, "runs": [], "full": {},
             "slots": [dict(slot, run=1, side=-1, u=4, w=5, d=5, pid=3, kind="workshops")]}]})
        site, _, why, _ = fs({"kind": "workshops", "shops": ["Masons"], "floor": {"elevs": [64]}})
        assert site is not None and LUA.globals().ZP.had is want, (slot, why)
        assert len(lst(calls("place")[0].req.units)) == (1 if want else 2)
        assert (site.floor.piles is None) is want
    # no floor_pile_units (the sibling part absent): no pile, no error
    FM.reset()
    site, L2, why, _ = fs({"kind": "workshops", "shops": ["Masons", "Carpenters"], "floor": {"elevs": [64]}})
    assert site is not None, why
    req = calls("place")[0].req
    assert [(u.role, u.flag) for u in lst(req.units)] == [("shop", None), ("shop", None)] and req.together is True
    assert site.floor.piles is None and site.floor_result.piles is None and site.floor_result.units == 2
    # the ore_piles custom: the level's own pile room (after its shops) is a pile of stone, and no second is asked for
    FM.reset(); B.floor_pile_units = fn(PILES)
    site, _, why, _ = fs({"kind": "workshops", "shops": ["Masons"], "style": {"customs": ["ore_piles"]},
                          "floor": {"elevs": [64]}})
    assert site is not None, why
    req = calls("place")[0].req
    assert [(u.role, u.flag) for u in lst(req.units)] == [("shop", None), ("pile", "stone")], "the custom's room"
    assert LUA.globals().ZP.had is True and site.floor.piles is None
    # a pile room the storage layout cannot make is left out, the shop still placed
    FM.reset()
    B.floor_pile_units = fn("function() return {{flag = 'no such pile', shop = 'Masons', room_size = 5}, 7, {shop = 'x'}} end")
    site, _, why, _ = fs({"kind": "workshops", "shops": ["Masons"], "floor": {"elevs": [64]}})
    assert site is not None and len(lst(calls("place")[0].req.units)) == 1, why


@test("the request: roles, tag, zone and group by kind; a grand level of one hall is axial; the hint goes through the grammar")
def _():
    site, _, why, _ = fs(dict(BED, floor={"elevs": [64]}))
    req = calls("place")[0].req
    assert [(u.role, u.w, u.d) for u in lst(req.units)] == [("room", 3, 3), ("room", 3, 3)]
    assert (req.kind, req.tag, req.zone, req.group, req.together, req.axial) == ("bedrooms", "homes", "any", None, False, False)
    for kind, tag in (("dining", "homes"), ("temple", "halls"), ("barracks", "defence"), ("storage", "storage")):
        FM.reset()
        p = {"kind": kind, "floor": {"elevs": [64]}}
        if kind == "storage":
            p["piles"] = ["stone"]
        site, _, why, _ = fs(p)
        assert site is not None, (kind, why)
        req = calls("place")[0].req
        assert req.tag == tag and req.zone == "any", kind
        assert [u.role for u in lst(req.units)] == (["room"] if kind == "storage" else ["hall"]), kind
    # the brain's hint: its tag, zone, group and grammar keys as sent, through ai-floorplan.grammar
    FM.reset()
    site, _, why, _ = fs({"kind": "dining", "style": {"grand": True, "statues": 3}, "urgent": True,
                          "floor": {"elevs": [64], "tag": "halls", "zone": "mid", "group": "feast", "gap": 2,
                                    "lead": 4, "run_max": 44, "dirs": ["south"]}})
    assert site is not None, why
    c = calls("place")[0]
    assert (c.req.tag, c.req.zone, c.req.group, c.req.axial) == ("halls", "mid", "feast", True)
    assert (c.G.gap, c.G.lead, c.G.run_max) == (2, 4, 44) and FM.hint.dirs[1] == "south"
    assert (site.floor_result.gap, site.floor_result.lead, site.floor_result.run_max) == (2, 4, 44)
    assert FM.compose_opts.hall_pri == 1 and FM.compose_opts.statues == 3
    # not grand, or more than one unit: not axial; an ordinary level's hall is dug at priority 3
    FM.reset()
    fs({"kind": "dining", "floor": {"elevs": [64]}})
    assert calls("place")[0].req.axial is False and FM.compose_opts.hall_pri == 3 and FM.compose_opts.statues == 0
    FM.reset()
    fs(dict(BED, style={"grand": True}, floor={"elevs": [64]}))
    assert calls("place")[0].req.axial is False
    # the level is made as ai-floorunits.unit_params says (never turned, never a cross or a ring)
    FM.reset()
    FM.cut_fn = fn("function(L) ZL = L; return nil, 'not cuttable' end")
    site, _, why, marks = fs(dict(BED, style={"orient": 2, "arms": "ring"}, floor={"elevs": [64]}))
    assert site is None and why == "not cuttable" and marks is None and calls("survey") == []
    assert LUA.globals().ZL.style.orient == 0 and LUA.globals().ZL.style.arms == "corridor"
    # cut gets the params too: entry_door, which ai-layouts' style drops, read from params.style
    FM.reset()
    fs({"kind": "dining", "style": {"entry_door": True}, "floor": {"elevs": [64]}})
    cp = lst(FM.cut_params)
    assert cp[0].kind == "dining" and cp[0].style.entry_door is True and cp[0].style.orient == 0
    # a kind the layouts do not know
    site, _, why, _ = fs({"kind": "ballroom"})
    assert site is None and "unknown level kind" in why, why


# ---------------------------------------------------------------- 10. the site

@test("the site: anchor the stair, extra empty, corridor 0, area / areas / links / floor / floor_result / _commit as the contract says")
def _():
    before = designated = TB.designated_count()
    site, L2, why, marks = fs(dict(BED, floor={"elevs": [64]}))
    assert site is not None and marks is None, why
    assert site.z == 64 and site.extend is False and (site.anchor.x, site.anchor.y) == (60, 60)
    assert len(dict(site.extra)) == 0 and site.corridor == 0 and site.new_corridor == 0
    assert site.stair.z_top == 80 and site.stair.z_bottom == 60 and site.stair.x == 60
    assert site.in_district is None and site.join is None and site.doors is None
    # two 3x3 rooms south of an east hall at u = 4 and u = 8: wall row y = 2, rooms y = 3..5
    a = site.area
    assert (a.x1, a.y1, a.x2, a.y2, a.z) == (60 + 4 - 1, 60 + 2 - 1, 60 + 10 + 1, 60 + 5 + 1, 64), (a.x1, a.y1, a.x2, a.y2)
    hall = sorted([(x, y) for x in (-1, 0, 1) for y in (-1, 0, 1) if (x, y) != (0, 0)]
                  + [(x, y) for x in range(2, 12) for y in (-1, 0, 1)])
    assert [(t.x, t.y) for t in lst(site.links)] == hall, "the new hall tiles, sorted, the hub's with them"
    areas = lst(site.areas)
    assert len(areas) == 1
    h = areas[0]
    assert (h.x1, h.y1, h.x2, h.y2, h.z) == (60 - 2, 60 - 2, 60 + 12, 60 + 2, 64)
    assert dict(site.floor) == {"id": 1, "slots": 2, "hall": 38} and site.floor.piles is None
    r = site.floor_result
    assert (r.id, r.elevation, r.stair.x, r.stair.y, r.arm, r.side, r.u) == (1, 64, 60, 60, "east", "south", 4)
    assert (r.hall_new, r.new_floor, r.units, r.gap, r.lead, r.run_max, r.piles) == (38, True, 2, 1, 2, 30, None)
    c = site._commit
    assert SAME(c.store, FM.store) and c.floor.id == 1 and c.floor.z == 64 and c.placement.floor_id == 1
    assert dict(c.free) == {"north": 57, "east": 56, "south": 56, "west": 57, "tick": 0} and lst(c.marks) == []
    assert len(lst(FM.store.floors)) == 0 and FM.store.next == 1, "nothing is written into the record here"
    # the layout: stair-relative, the hall first, every tile really diggable (the fake Quickfort agrees)
    assert L2.dig[1].text == "d3" and L2.summary.floor == 1 and L2.kind == "bedrooms"
    n = B.count(L2.tiles)
    assert n == 38 + 2 * 10, n
    dry = B.quickfort_apply("dig", L2.dig, site.z, site.anchor.x, site.anchor.y, "run", True)
    assert dry.dig_designated.value == n and dry.dig_invalid_tiles.value == 0, picture(L2)
    assert TB.designated_count() == designated == before
    # the env it was seen through
    env = FM.env
    assert env.seed == 31 and env.late() is False and env.bounds.x1 == -58
    # with a plan's band: in the district or not
    FM.reset()
    site, _, why, _ = fs(dict(BED, floor={"elevs": [64]}, plan={"elev_lo": 62, "elev_hi": 65}))
    assert site.in_district is True
    FM.reset()
    site, _, why, _ = fs(dict(BED, floor={"elevs": [64]}, plan={"elev_lo": 70, "elev_hi": 72}))
    assert site.in_district is False
    # on a level the fort already uses: the open hub and hall are kept (not dug), rooms never go onto open floor
    FM.reset()
    site, _, why, marks = fs(dict(BED, floor={"elevs": [70]}))
    assert site is None and why.startswith("z70: refused: not solid rock") and lst(marks) == [], why
    # a second project on the same floor: the record's floor, its id, the seed from its slots
    FM.reset()
    FM.store = tbl({"v": 1, "next": 5, "floors": [
        {"id": 3, "z": 64, "stair": {"x": 60, "y": 60}, "runs": [], "full": {},
         "slots": [{"run": 1, "side": -1, "u": 4, "w": 3, "d": 3, "pid": 9, "kind": "bedrooms", "tag": "homes"}]}]})
    site, _, why, _ = fs(dict(BED, floor={"elevs": [64]}))
    assert site.floor.id == 3 and site.floor_result.new_floor is False and FM.env.seed == 3 * 31 + 1


@test("the site: the arm is the hub run the first room hangs on through its turns; the side's compass word; an axial room closes its run")
def _():
    FM.store = tbl({"v": 1, "next": 4, "floors": [
        {"id": 2, "z": 64, "stair": {"x": 60, "y": 60}, "full": {}, "slots": [],
         "runs": [{"id": 1, "parent": 0, "ox": 0, "oy": 0, "dx": -1, "dy": 0, "len": 12, "tag": "homes", "node": 3},
                  {"id": 2, "parent": 1, "ox": -13, "oy": 0, "dx": 0, "dy": -1, "len": 6, "tag": "homes", "node": 3}]}]})
    # a room on a new run 3 that turns east off run 2 (which turned north off the west arm): side +1 of east is south
    place = """function(floor, req, G, env)
      local p = FM.honest_place({id = floor.id, runs = {}, slots = {}, stair = floor.stair, z = floor.z}, req, G, env)
      p.runs = {{id = 3, new = true, parent = 2, ox = 0, oy = 0, dx = 1, dy = 0, len_before = 0, len = 10, node = 3}}
      for _, put in ipairs(p.puts) do put.run = 3; put.side = %d; put.axial = %s end
      return p
    end"""
    FM.place_fn = fn(place % (1, "false"))
    site, _, why, _ = fs(dict(BED, floor={"elevs": [64]}))
    assert site is not None and (site.floor_result.arm, site.floor_result.side) == ("west", "south"), why
    FM.place_fn = fn(place % (-1, "false"))
    site, _, why, _ = fs(dict(BED, floor={"elevs": [64]}))
    assert (site.floor_result.arm, site.floor_result.side) == ("west", "north")
    FM.place_fn = fn(place % (1, "true"))
    site, _, why, _ = fs(dict(BED, floor={"elevs": [64]}))
    assert (site.floor_result.arm, site.floor_result.side) == ("west", "east")


@test("the site: a hospital keeps its gap from the stairs (min_u, zone far, stair_gap on the layout); a neck gives join and doors")
def _():
    site, L2, why, _ = fs({"kind": "hospital", "floor": {"elevs": [64], "zone": "near"}})
    assert site is not None, why
    req = calls("place")[0].req
    assert req.min_u == B.HOSPITAL_STAIR_GAP + 1 == 7 and req.zone == "far" and req.tag == "homes"
    assert L2.stair_gap == 6 and L2.main_stair.x == 60 and site.floor_result.u == 7
    # the builder's own hint for a hospital
    FM.reset()
    fs({"kind": "hospital"})
    assert FM.hint.zone == "far" and FM.hint.tag == "homes"
    # a placement nearer than the gap is refused by the last check, and the next level tried
    FM.reset()
    FM.ignore_min = True
    FM.place_fn = fn("""function(floor, req, G, env)
      FM.u = floor.z == 64 and 4 or 9
      return FM.honest_place(floor, req, G, env)
    end""")
    site, L2, why, _ = fs({"kind": "hospital", "floor": {"elevs": [64, 63]}})
    assert site is not None and site.z == 63 and len(calls("place")) == 2, why
    FM.reset(); FM.ignore_min = True
    site, _, why, marks = fs({"kind": "hospital", "floor": {"elevs": [64]}})
    assert site is None and "a hospital keeps 6 tiles from the stairs" in why and lst(marks) == [], why
    # the main stair's gap too (the most used, stairs[1]), when the floor hangs on another
    FM.reset()
    TB._stair(48, 60, 60, 80)                 # the floor's stair, 12 west of the main one: the hall runs at it
    site, _, why, _ = fs({"kind": "hospital", "floor": {"elevs": [64], "spine": {"x": 48, "y": 60}}},
                         stairs=[stair(), stair(48, 60)])
    assert site is not None and site.stair.x == 60 and [c.sx for c in calls("place")] == [48, 60], why
    B.FLOOR_STAIRS = 1
    try:
        FM.calls = LUA.table()
        site, _, why, _ = fs({"kind": "hospital", "floor": {"elevs": [64], "spine": {"x": 48, "y": 60}}},
                             stairs=[stair(), stair(48, 60)])
    finally:
        B.FLOOR_STAIRS = 3
    assert site is None and "from x60 y60" in why, why
    # a neck: the hall's first column 1 wide with a door, for entry_door
    FM.reset()
    site, L2, why, _ = fs(dict(BED, floor={"elevs": [64], "neck": True}))
    assert site is not None and (site.join.x, site.join.y) == (2, 0) and site.doors == "fortified", why
    assert L2.tiles[2][0] is True and L2.tiles[2][1] is None and L2.tiles[2][-1] is None
    build, furniture = B.entry_door(L2, site, None)
    assert [(c.x, c.y, c.text) for c in lst(build)] == [(2, 0, "d")] and furniture.Door == 1
    FM.reset()
    site, L2, why, _ = fs(dict(BED, floor={"elevs": [64]}))
    build, furniture = B.entry_door(L2, site, tbl({"entry_door": True}))
    assert lst(build) == [] and site.join is None, "no neck, no door on the hall"


# ---------------------------------------------------------------- 11. the last whole check

@test("the composed level refused by the last whole check (a tile beside water): the next level is tried, nothing half-returned")
def _():
    W.set(80, 71, 64, tbl({"liquid": True}))          # water on z 64 only, beside the tile compose adds
    FM.compose_extra = tbl({"x": 20, "y": 10})
    site, L2, why, _ = fs(dict(BED, floor={"elevs": [64, 63]}))
    assert site is not None and site.z == 63 and L2.tiles[20][10] is True, why
    assert [c.z for c in calls("place")] == [64, 63]
    FM.reset()
    FM.compose_extra = tbl({"x": 20, "y": 10})
    out = B.floor_site(tbl(dict(BED, floor={"elevs": [64]})), tbl([stair()]), tbl([]), B.load_projects(), None)
    assert out[0] is None and out[1] == "z64: refused: water or magma at x80 y71 z64" and lst(out[2]) == [], out[1]
    assert B.CACHE is None
    # the open floor may border the new hall, never a new room: a room's tile beside a dug pocket
    TB._reset(False); FM.reset()
    W.set(64, 66, 64, tbl({"shape": "FLOOR"}))        # beside the first room's west wall, walkable
    FM.place_fn = fn("""function(floor, req, G, env)          -- a place that does not probe
      local real = env.probe
      env.probe = function() return true end
      local p, why = FM.honest_place(floor, req, G, env)
      env.probe = real
      return p, why
    end""")
    site, _, why, _ = fs(dict(BED, floor={"elevs": [64]}))
    assert site is None and "refused: not solid rock (already dug or open) at x64 y66" in why, why
    # the same pocket beside the hall only is the same open space
    TB._reset(False); FM.reset()
    W.set(66, 58, 64, tbl({"shape": "FLOOR"}))        # north of the hall's north row
    site, _, why, _ = fs(dict(BED, floor={"elevs": [64]}))
    assert site is not None, why
    # the stair tile in the dig: refused
    FM.reset()
    FM.compose_extra = tbl({"x": 0, "y": 0})
    site, _, why, _ = fs(dict(BED, floor={"elevs": [64]}))
    assert site is None and "the stair tile is in the dig" in why, why
    # another open project's area under the composed level: refused
    FM.reset()
    area = {"x1": 62, "y1": 62, "x2": 66, "y2": 66, "z": 64}
    FM.place_fn = fn("""function(floor, req, G, env)
      env.probe = function() return true end
      env.blocked = function() return false end
      return FM.honest_place(floor, req, G, env)
    end""")
    site, _, why, _ = fs(dict(BED, floor={"elevs": [64]}), reserved=[area])
    assert site is None and "overlaps another AI project" in why, why


@test("an adopted corridor: hall columns that are the fort's open floor are kept, and rooms may open onto them")
def _():
    # an old 3-wide corridor east of the stair on a rock level: x 62..75, y 59..61, and the hub open
    for x in range(59, 76):
        for y in (59, 60, 61):
            if (x, y) != (60, 60):
                W.set(x, y, 64, tbl({"shape": "FLOOR"}))
    site, L2, why, _ = fs(dict(BED, floor={"elevs": [64]}))
    assert site is not None, why
    assert site.links is not None and lst(site.links) == [] and site.areas is None, "no hall tile is new"
    assert site.floor.hall == 0 and site.floor_result.hall_new == 0 and B.count(L2.tiles) == 20
    assert L2.tiles[5][2] is True and L2.tiles[5][1] is None
    dry = B.quickfort_apply("dig", L2.dig, 64, 60, 60, "run", True)
    assert dry.dig_designated.value == 20
    # a room of an AI level on that corridor makes its tiles bad: the hall cannot run through it
    FM.reset()
    level = {"id": 3, "kind": "storage", "phase": "done", "z": 64, "anchor": {"x": 60, "y": 60},
             "floor": {"id": 1}, "stair": {"x": 60, "y": 60},
             "cells": {"place": [{"x": 6, "y": -1, "text": "s(3x3)"}], "zone": [], "dig": [], "build": []}}
    site, _, why, _ = fs(dict(BED, floor={"elevs": [64]}), data=tbl({"next_id": 4, "list": [level]}))
    assert site is None and "a hall tile is taken" in why, why


# ---------------------------------------------------------------- 12. reads only

@test("floor_site never designates or saves, also when it fails half-way; CACHE is cleared; a stand-in's error becomes nil, why")
def _():
    W.persist["ai-overseer/projects"] = tbl({"next_id": 3, "list": [
        {"id": 2, "kind": "dining", "phase": "done", "z": 62, "area": {"x1": 50, "y1": 50, "x2": 58, "y2": 58, "z": 62}}]})

    def state():
        return (persisted(), TB.designated_count(), len(lst(W.calls)), len(W.placed),
                json.dumps(sorted((k, str(dict(t))) for k, t in W.tiles.items() if t.designated)))

    before = state()
    keys = sorted(W.persist.keys())
    store = FM.store
    site, L2, why, _ = fs(dict(BED, floor={"elevs": [64]}))
    assert site is not None and state() == before and sorted(W.persist.keys()) == keys, why
    assert B.CACHE is None and SAME(FM.store, store) and len(lst(store.floors)) == 0 and store.next == 1
    assert len(lst(B.load_projects().list)) == 1
    # failing half-way: a refusal after compose, a level with no room, a full search
    for setup in ("FM.compose_extra = {x = 0, y = 0}", "FM.place_fn = function() return nil, 'no room' end",
                  "FM.survey_fn = function() return {north = 0, east = 0, south = 0, west = 0} end "
                  "FM.place_fn = function() return nil, 'no hall: none' end"):
        FM.reset()
        LUA.execute(setup)
        site, _, why, marks = fs({"kind": "workshops", "shops": ["Masons"]})
        assert site is None and why and state() == before and B.CACHE is None, (setup, why)
    # an error thrown inside a stand-in: nil and the reason (the next floor is tried), never half a site
    for setup, word in (("FM.place_fn = function() error('boom in place') end", "boom in place"),
                        ("FM.survey_fn = function() error('boom in survey') end", "boom in survey"),
                        ("FM.compose_fn = function() error('boom in compose') end", "boom in compose"),
                        ("FM.compose_fn = function() return nil end", "could not be composed"),
                        ("FM.compose_fn = function() return {tiles = {}} end", "could not be composed"),
                        ("FM.place_fn = function() return {puts = {}} end", "holds no room")):
        FM.reset()
        LUA.execute(setup)
        out = B.floor_site(tbl(dict(BED, floor={"elevs": [64, 63]})), tbl([stair()]), tbl([]), B.load_projects(), None)
        assert out[0] is None and word in out[1] and out[1].startswith("z64: ") and "; z63: " in out[1], (setup, out[1])
        assert state() == before and B.CACHE is None, setup
    # an error outside any one floor (the level cannot be cut) is thrown on: start_project's pcall words it
    FM.reset()
    FM.cut_fn = fn("function() error('boom in cut') end")
    try:
        B.floor_site(tbl(dict(BED, floor={"elevs": [64]})), tbl([stair()]), tbl([]), B.load_projects(), None)
        raised = None
    except Exception as e:  # noqa: BLE001
        raised = str(e)
    assert raised and "boom in cut" in raised and B.CACHE is None and state() == before, raised
    # as start_project calls it: pcall(floor_site, ...) -> ok, nil, why, marks / ok, site, L2 / false, error
    FM.reset()
    FM.place_fn = fn("function() return nil, 'no room' end")
    r = LUA.eval("function(B, p, s, d) return {pcall(B.floor_site, p, s, {}, d, nil)} end")(
        B, tbl(dict(BED, floor={"elevs": [64]})), tbl([stair()]), B.load_projects())
    assert r[1] is True and r[2] is None and r[3] == "z64: no room" and r[4][1].tag == "homes"
    # no stairs at all
    site, _, why, _ = fs(BED, stairs=[])
    assert site is None and why == "no staircase"


@test("a second floor_site reads the map afresh (the cache is the call's own)")
def _():
    site, _, why, _ = fs(dict(BED, floor={"elevs": [64]}))
    assert site is not None, why
    W.set(66, 60, 65, tbl({"aquifer": True}))
    site, _, why, _ = fs(dict(BED, floor={"elevs": [64]}))
    assert site is None and "aquifer directly above x66 y60 z64" in why, why


# ---------------------------------------------------------------- 13. time

@test("time: a place that never finds room and a 0.2 s deadline: back within about that time, 'out of time' in why")
def _():
    B.FLOOR_SECONDS = 0.2
    FM.place_fn = fn("""function(floor, req, G, env)
      FM.spins = 0
      while not env.late() do FM.spins = FM.spins + 1 end
      return nil, 'out of time'
    end""")
    # (the deadline is os.clock(), the process's CPU time, as the part counts it; wall time only
    # bounds it loosely: the test machine is shared)
    clock = LUA.eval("os.clock")
    t0, w0 = clock(), time.perf_counter()
    site, _, why, marks = fs(dict(BED, floor={"elevs": [65, 64, 63]}))
    took, wall = clock() - t0, time.perf_counter() - w0
    assert site is None and "out of time" in why and len(calls("place")) == 1, why
    assert 0.15 <= took < 0.6 and wall < 10 and FM.spins > 0, (took, wall)
    assert lst(marks) == [] and B.CACHE is None
    assert FM.env.late() is True
    # out of the module's own tries (not the clock): the next floor is still tried
    FM.reset()
    FM.place_fn = fn("function() return nil, 'out of time: 24 tries' end")
    site, _, why, _ = fs(dict(BED, floor={"elevs": [65, 64]}))
    assert len(calls("place")) == 2 and why == "z65: out of time: 24 tries; z64: out of time: 24 tries", why
    # a deadline already past: nothing is looked at
    FM.reset()
    B.FLOOR_SECONDS = -1
    site, _, why, marks = fs(dict(BED, floor={"elevs": [65, 64]}))
    assert site is None and why == "out of time" and calls("survey") == [] and lst(marks) == [], why


if __name__ == "__main__":
    finish()
