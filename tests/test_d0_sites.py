"""(D0, G6) The Design track's landmarks: candidate sites, the map checks and
the building (lua/ai-builder-landmarks.lua), and the bridge actions
(lua/ai-bridge-design.lua), on test_builder's fake fort (its harness read by
ast, as test_halls does) and test_hygiene_bridge's stub DFHack. Needs lupa.

ai-blueprints (G5's) is the real lua/ai-blueprints.lua when it is there, else
a small stand-in below that keeps its contract (d0-spec 1.5) for the drawings
these tests use.

    python tests/test_d0_sites.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

LUA_DIR = ROOT / "lua"
_tree = ast.parse((ROOT / "tests" / "test_builder.py").read_text(encoding="utf-8"))
HARNESS = next(n.value.value for n in _tree.body
               if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "HARNESS")

# A stand-in for ai-blueprints (pure), to the contract: check_format, cost,
# to_layouts (q quarter turns clockwise, the join at 0, 0), BP_LIMITS, ITEMS.
FAKE_BLUEPRINTS = r"""
local M = {}
M.BP_LIMITS = {w = 31, h = 31, levels = 5, dug = 700, built = 400, items = 40, statues = 16, doors = 8,
               stairs = 4, legend = 12, cost_max = 2500}
M.ITEMS = {Statue = 's', Table = 't', Chair = 'c', Bed = 'b', Coffin = 'n', Cabinet = 'f', Chest = 'h',
           Bookcase = 'B', ArmorStand = 'a', WeaponRack = 'r'}
local ROCK = {['.'] = 'd', [','] = 'd', ['@'] = 'd', ['<'] = 'u', ['>'] = 'j', X = 'i', ['^'] = 'r', ['+'] = 'd'}
local SURF = {W = 'Cw', F = 'Cf', R = 'Cr', U = 'Cu', D = 'Cd', I = 'Cx', O = 'CF'}
local function turn(x, y, q) for _ = 1, q % 4 do x, y = -y, x end return x, y end
local function each(bp, fn)
  for k, lv in ipairs(bp.levels) do
    for r, row in ipairs(lv.grid) do
      for c = 1, #row do fn(k, c - 1, r - 1, row:sub(c, c)) end
    end
  end
end
local function join(bp)
  for c = 1, #bp.levels[1].grid[1] do if bp.levels[1].grid[1]:sub(c, c) == '@' then return c - 1, 0 end end
end
function M.check_format(bp)
  local out = {}
  if type(bp) ~= 'table' or type(bp.levels) ~= 'table' or #bp.levels == 0 then
    return false, {{code = 'FORMAT', words = 'no levels'}}
  end
  local surface = bp.ground == 'surface'
  local ats = 0
  each(bp, function(k, x, y, s)
    if s == '@' then ats = ats + 1 end
    local good = s == '_' or s == '#' and not surface or (surface and (SURF[s] or s == '.' or s == '@' or s == '+'))
      or (not surface and (ROCK[s] or (s:match('%l') and type(bp.legend) == 'table' and bp.legend[s])))
    if not good and #out < 8 then
      table.insert(out, {code = 'SYMBOL', level = k, x = x, y = y, words = ('L%d x%d y%d: %q'):format(k, x, y, s)})
    end
  end)
  if ats ~= 1 or not join(bp) then table.insert(out, 1, {code = 'JOIN', level = 1, words = 'one @ in row 0'}) end
  return #out == 0, out
end
function M.cost(bp)
  local c = {dug = 0, built = 0, items = 0, statues = 0, doors = 0, stairs = 0}
  local surface = bp.ground == 'surface'
  each(bp, function(k, x, y, s)
    if surface then
      if SURF[s] then c.built = c.built + 1 end
      if s == 'U' or s == 'D' or s == 'I' then c.stairs = c.stairs + 1 end
    elseif ROCK[s] or s:match('%l') then
      c.dug = c.dug + 1
      if s == '<' or s == '>' or s == 'X' then c.stairs = c.stairs + 1 end
    end
    if s == '+' then c.doors = c.doors + 1 end
    if s:match('%l') then
      c.items = c.items + 1
      if bp.legend[s] == 'Statue' then c.statues = c.statues + 1 end
    end
  end)
  c.jobs = c.dug + 4 * c.built + 10 * c.items
  return c
end
function M.to_layouts(bp, q)
  local jx, jy = join(bp)
  local surface = bp.ground == 'surface'
  local levels, dz = {}, {}
  for k, lv in ipairs(bp.levels) do
    local L = {kind = 'landmark', dig = {}, build = {}, place = {}, zone = {}, construct = {}, tiles = {},
               furniture = {}, summary = {}, halls = {}, smooth = {}, engrave = {}}
    local x1, y1, x2, y2 = math.huge, math.huge, -math.huge, -math.huge
    for r, row in ipairs(lv.grid) do
      for c = 1, #row do
        local s = row:sub(c, c)
        local x, y = turn(c - 1 - jx, r - 1 - jy, q)
        if not surface and (ROCK[s] or s:match('%l')) then
          table.insert(L.dig, {x = x, y = y, text = ROCK[s] or 'd'})
          L.tiles[x] = L.tiles[x] or {}; L.tiles[x][y] = true
          x1, x2, y1, y2 = math.min(x1, x), math.max(x2, x), math.min(y1, y), math.max(y2, y)
        end
        if surface and SURF[s] then table.insert(L.construct, {x = x, y = y, text = SURF[s]}) end
        if s == '+' then table.insert(L.build, {x = x, y = y, text = 'd'}); L.furniture.Door = (L.furniture.Door or 0) + 1 end
        if s:match('%l') then
          local item = bp.legend[s]
          table.insert(L.build, {x = x, y = y, text = M.ITEMS[item]}); L.furniture[item] = (L.furniture[item] or 0) + 1
        end
        if type(bp.zone) == 'table' and bp.zone.level == k and (s == '.' or s == ',') then
          table.insert(L.zone, {x = x, y = y, text = 'm(1x1)'})
        end
      end
    end
    L.bounds = {x1 = x1, y1 = y1, x2 = x2, y2 = y2}
    levels[k] = L
    dz[k] = surface and (k - 1) or -(k - 1)
  end
  return {levels = levels, dz = dz}
end
return M
"""

REAL_BLUEPRINTS = (LUA_DIR / "ai-blueprints.lua").exists()


def boot():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(LUA_DIR)
    layouts = (LUA_DIR / "ai-layouts.lua").read_text(encoding="utf-8")
    builder = (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8")
    B, W = lua.execute(HARNESS, layouts, builder)
    if REAL_BLUEPRINTS:
        src = (LUA_DIR / "ai-blueprints.lua").read_text(encoding="utf-8")
        BPM = lua.eval("""function(src)
            local env = setmetatable({}, {__index = _G})
            assert(load(src, 'ai-blueprints', 't', env))()
            return env end""")(src)
    else:
        BPM = lua.execute(FAKE_BLUEPRINTS)
    lua.globals().BPM = BPM
    lua.execute("""
      local old = _G.reqscript
      _G.reqscript = function(name) if name == 'ai-blueprints' then return BPM end return old(name) end
      df = df or {}
      df.global = df.global or {}
      df.global.world = df.global.world or {}
      df.global.world.buildings = {other = {TRADE_DEPOT = {}}, all = {}}
    """)
    return lua, B, W


LUA, B, W = boot()
T = LUA.table_from
REAL = {k: B[k] for k in ("landmark_stock", "landmark_times", "furnish_progress", "stone_at", "hall_planned_at",
                          "SEARCH_SECONDS")}


def lt(d):
    """A Python value as a Lua one, nested."""
    if isinstance(d, dict):
        return LUA.table_from({k: lt(v) for k, v in d.items()})
    if isinstance(d, list):
        return LUA.table_from([lt(v) for v in d])
    return d


def lua_list(v) -> list:
    return [] if v is None else [v[i] for i in range(1, len(v) + 1)]


def _reset():
    W.reset()
    for k, v in REAL.items():
        B[k] = v
    B.landmark_stock = LUA.eval("function() return 1000 end")
    B.landmark_times = LUA.eval("function() return nil end")
    B.stone_at = LUA.eval("function() return 'GRANITE' end")
    B.furnish_progress = LUA.eval("function(p) return {placed = 0, done = 0, waiting = {}} end")
    B.hall_planned_at = LUA.eval("function(x, y, z) local t = W_PEEK(x, y, z); return t ~= nil and t.planned == true end")
    B.TRY_BESIDE = True
    LUA.execute("FAILZ = nil")


LUA.globals().W_PEEK = W.peek
LUA.execute("""
  local qf = reqscript('quickfort')
  local real = qf.apply_blueprint
  qf.apply_blueprint = function(p)
    if FAILZ and not p.dry_run and p.mode == 'dig' and p.command ~= 'undo' and p.data[FAILZ] then
      error('injected failure')
    end
    return real(p)
  end
""")
test = make_test(before=_reset)

NOW = {"year": 150, "tick": 100}


def descent(levels=2, w=7, h=7):
    """A rock drawing: w x h, the join mid row 0, a stair down through every level."""
    mid = (w - 1) // 2
    out = []
    for k in range(levels):
        rows = []
        for y in range(h):
            row = ["."] * w
            if k == 0 and y == 0:
                row[mid] = "@"
            if y == h // 2:
                row[mid] = ">" if k == 0 else ("<" if k == levels - 1 else "X")
            rows.append("".join(row))
        out.append({"grid": rows})
    return {"v": 1, "name": "The Spiral", "purpose": "descent", "ground": "rock", "levels": out, "legend": {}}


def tower():
    return {"v": 1, "name": "The Tower", "purpose": "tower", "ground": "surface",
            "levels": [{"grid": ["WW@WW", "W...W", "W.U.W", "W...W", "WWWWW"]},
                       # level 2 by ai-blueprints' SUPPORT rule: '.' on a wall's top, 'F' over open floor
                       {"grid": ["..F..", ".FFF.", ".FDF.", ".FFF.", "....."]}],
            "legend": {}, "zone": {"kind": "meeting", "level": 1}}


def meta(**kw):
    m = {"name": "The Spiral", "purpose": "descent", "by": "library", "cap": 2500}
    m.update(kw)
    return lt(m)


def offered(sid):
    """offered_site's record, or None (it returns nil and why)."""
    r = B.offered_site(sid)
    return r[0] if isinstance(r, tuple) else r


def designated_count():
    return sum(1 for t in W.tiles.values() if t.designated)


def rock_site(env=None):
    env = env or {"w": 7, "h": 7, "levels": 2, "ground": "rock"}
    r = B.landmark_sites(lt(env), "descent", 4)
    assert r.ok, dict(r)
    return r, B.offered_site("S1")


def map_xy(site, gx, gy, k=1, w=7):
    """A grid tile of a drawing with its join at column (w-1)//2, row 0, on the map."""
    x, y = B.turn_xy(gx - (w - 1) // 2, gy, site.q)
    return site.anchor.x + x, site.anchor.y + y, site.z - (k - 1)


def codes(reasons):
    return [r.code for r in lua_list(reasons)]


def field(x1, y1, x2, y2, z=80):
    for x in range(x1, x2 + 1):
        for y in range(y1, y2 + 1):
            if (x, y) != (60, 60):
                W.set(x, y, z, T({"shape": "FLOOR", "material": "SOIL", "outside": True}))
            W.set(x, y, z + 1, T({"shape": "EMPTY", "outside": True}))
            W.set(x, y, z + 2, T({"shape": "EMPTY", "outside": True}))


def surface_site(ax, ay, q=0, z=80):
    return lt({"id": "S1", "ground": "surface", "z": z, "anchor": {"x": ax, "y": ay}, "q": q})


# --- sites -------------------------------------------------------------------

@test("sites, rock: up to 4, one a (district, direction); ids and words out, no coordinates; the ids map back")
def _():
    r, s1 = rock_site()
    sites = lua_list(r.sites)
    assert 1 <= len(sites) <= 4, len(sites)
    assert [s.id for s in sites] == [f"S{i}" for i in range(1, len(sites) + 1)]
    seen = set()
    for s in sites:
        keys = set(dict(s))
        assert not keys & {"x", "y", "z", "anchor", "stair", "corridor", "q"}, keys
        assert s.ground == "rock" and s.w == 7 and s.h == 7 and s.levels == 2 and s.words, dict(s)
        assert "granite" in s.words and not re.search(r"\bx\d+|\by\d+|\bz\d+", s.words), s.words
        rec = B.offered_site(s.id)
        assert rec and rec.ground == "rock" and rec.anchor, s.id
        key = (rec.district, rec.dir)
        assert key not in seen, key
        seen.add(key)
    assert len(sites) >= 2, "more than one direction fits on the fake fort"
    assert offered("S9") is None
    # every envelope passes check_site on each of its levels, and none overlaps another
    for s in sites:
        rec = B.offered_site(s.id)
        for k in (1, 2):
            L = B.envelope(7, 7, rec.q, True)
            ok = B.check_site(L, LUA.table(), rec.anchor.x, rec.anchor.y, rec.z - k + 1, LUA.table(), None,
                              LUA.eval("function() return true end"))
            assert ok, (s.id, k)


@test("sites, rock: the plan's districts first (their band, their name in the words), then by the stair")
def _():
    W.persist["ai-overseer/projects"] = lt({"next_id": 2, "list": [
        {"id": 1, "kind": "bedrooms", "phase": "done", "z": 75,
         "plan": {"district": "Dark Halls", "elev_lo": 62, "elev_hi": 65, "elev_target": 64}}]})
    r = B.landmark_sites(lt({"w": 7, "h": 7, "levels": 2, "ground": "rock"}), "descent", 4)
    assert r.ok, dict(r)
    sites = lua_list(r.sites)
    first = offered(sites[0].id)
    assert first.district == "Dark Halls" and 62 <= first.z <= 65 and first.in_district, (first.district, first.z)
    assert sites[0].district == "Dark Halls" and "in the Dark Halls district" in sites[0].words, sites[0].words
    keys = [(offered(x.id).district, offered(x.id).dir) for x in sites]
    assert len(set(keys)) == len(keys), keys


@test("sites, rock: no level on the stair fits -> the stair dug on down to one (check_extension), and built so")
def _():
    LUA.execute("""
      local W = ...
      for z = 60, 80 do for x = 20, 100 do for y = 20, 100 do
        if W.peek(x, y, z).shape == 'WALL' then W.set(x, y, z, {aquifer = true}) end
      end end end""", W)
    r, site = rock_site()
    assert site.extend and site.z < 60, (site.extend, site.z)
    assert "the stair dug on down to it" in lua_list(r.sites)[0].words
    bp = lt(descent())
    c = B.blueprints().cost(bp)
    b = B.build_landmark(bp, "S1", meta(), lt(NOW), False)
    assert b.ok, dict(b)
    stair = [z for z in range(site.z, 61) if W.peek(60, 60, z).designated]
    assert stair == list(range(site.z, 61)), stair
    assert designated_count() == c.dug + len(lua_list(site.corridor)) + len(stair), designated_count()
    p = lua_list(B.load_projects().list)[0]
    assert len(lua_list(p.stairs)) == len(stair)


@test("sites: kept 7 days in the AI's site data, then gone (SITE_GONE)")
def _():
    rock_site()
    assert offered("S1") is not None
    W.persist["ai-overseer/bp-sites"].asked = -10 * 1200
    rec, why = B.offered_site("S1")
    assert rec is None and "days" in why, why
    r = B.build_landmark(lt(descent()), "S1", meta(), lt(NOW), True)
    assert not r.ok and r.rejected and codes(r.reasons) == ["SITE_GONE"], dict(r)


@test("sites, surface: open ground near the way in, row 0 toward it, open air above for its levels")
def _():
    field(30, 30, 95, 95)
    r = B.landmark_sites(lt({"w": 5, "h": 5, "levels": 2, "ground": "surface"}), "tower", 3)
    assert r.ok, dict(r)
    sites = lua_list(r.sites)
    assert 1 <= len(sites) <= 3 and all(s.ground == "surface" for s in sites), [dict(s) for s in sites]
    rec = B.offered_site("S1")
    assert rec.z == 80
    # the join's side faces the way in (60, 60): its row 0 is the nearest
    cells = [B.turn_xy(x - 2, y, rec.q) for x in range(5) for y in range(5)]
    tiles = [(rec.anchor.x + c[0], rec.anchor.y + c[1]) for c in cells]
    assert min(max(abs(x - 60), abs(y - 60)) for x, y in tiles) > 3, "kept clear of the way in"
    d_join = max(abs(rec.anchor.x - 60), abs(rec.anchor.y - 60))
    far = max(max(abs(x - 60), abs(y - 60)) for x, y in tiles)
    assert d_join < far, (d_join, far)
    # and the drawing then passes on it
    ok, reasons = B.validate_landmark(lt(tower()), rec, 2500)[:2]
    assert ok, [r.words for r in lua_list(reasons)]


@test("sites: bad envelopes give no sites, and say why")
def _():
    r = B.landmark_sites(lt({"w": 7, "h": 7, "levels": 2, "ground": "surface"}), "tower", 2)
    assert not r.ok and r.error, dict(r)       # no open ground on the fake fort's top


# --- the map checks ----------------------------------------------------------

@test("checks, rock: a good descent passes; the reasons' positions are on the drawing's own grid")
def _():
    _, site = rock_site()
    ok, reasons = B.validate_landmark(lt(descent()), site, 2500)[:2]
    assert ok, [r.words for r in lua_list(reasons)]
    x, y, z = map_xy(site, 2, 4, k=2)
    W.set(x, y, z, T({"aquifer": True}))
    ok, reasons = B.validate_landmark(lt(descent()), site, 2500)[:2]
    rs = lua_list(reasons)
    assert not ok and rs[0].code == "AQUIFER" and (rs[0].level, rs[0].x, rs[0].y) == (2, 2, 4), dict(rs[0])
    assert rs[0].words.startswith("L2 x2 y4:"), rs[0].words


@test("checks: each refusal code from a crafted map (aquifer, cavern beside, water above, a building, edge)")
def _():
    _, site = rock_site()
    bp = lt(descent())
    cases = [
        ("AQUIFER", lambda: W.set(*map_xy(site, 1, 1, k=2), T({"aquifer": True}))),
        ("CAVERN", lambda: W.set(*map_xy(site, -1, 3), T({"feature": True}))),
        ("DAMP", lambda: W.set(*(lambda p: (p[0], p[1], p[2] + 1))(map_xy(site, 1, 1)), T({"liquid": True}))),
        ("ROCK", lambda: W.set(*map_xy(site, 2, 2), T({"building": True}))),
        ("LIQUID", lambda: W.set(*map_xy(site, 5, 7, k=2), T({"liquid": True}))),
    ]
    for code, craft in cases:
        W.reset()
        r, site = rock_site()
        craft()
        ok, reasons = B.validate_landmark(bp, site, 2500)[:2]
        assert not ok and code in codes(reasons), (code, [x.words for x in lua_list(reasons)])
        assert len(lua_list(reasons)) <= 8
    # beside: the words say so
    W.reset()
    _, site = rock_site()
    W.set(*map_xy(site, -1, 3), T({"feature": True}))
    rs = lua_list(B.validate_landmark(bp, site, 2500)[1])
    assert any(r.code == "CAVERN" and "beside" in r.words and r.x == -1 for r in rs), [r.words for r in rs]
    # the map's edge
    edge = lt({"id": "S1", "ground": "rock", "z": 70, "anchor": {"x": 3, "y": 1}, "q": 0,
               "stair": {"x": 60, "y": 60, "z_top": 80, "z_bottom": 60}, "corridor": []})
    assert "EDGE" in codes(B.validate_landmark(bp, edge, 2500)[1])


@test("checks: an over-cap drawing (COST), too little stone (STOCK), no slot (SLOTS), bad times (TIMES)")
def _():
    _, site = rock_site()
    assert codes(B.validate_landmark(lt(descent()), site, 50)[1]) == ["COST"]
    W.persist["ai-overseer/projects"] = lt({"next_id": 3, "list": [
        {"id": 1, "kind": "bedrooms", "phase": "dig", "area": {"x1": 2, "y1": 2, "x2": 3, "y2": 3, "z": 5}},
        {"id": 2, "kind": "bedrooms", "phase": "dig", "area": {"x1": 6, "y1": 2, "x2": 7, "y2": 3, "z": 5}}]})
    assert codes(B.validate_landmark(lt(descent()), site, 2500)[1]) == ["SLOTS"]
    W.persist["ai-overseer/projects"] = None
    B.landmark_times = LUA.eval("function() return '3 invader(s) on the map' end")
    assert codes(B.validate_landmark(lt(descent()), site, 2500)[1]) == ["TIMES"]
    B.landmark_times = LUA.eval("function() return nil end")
    field(20, 40, 100, 80)
    st = surface_site(80, 50)
    B.landmark_stock = LUA.eval("function() return 10 end")
    assert "STOCK" in codes(B.validate_landmark(lt(tower()), st, 2500)[1])


@test("checks, surface: a wall across the only way in (PATH); a way in within 3 tiles (WAY_IN); rock (ROCK)")
def _():
    # the only way out: a 5-wide strip east from the way in to the map's edge
    for x in range(40, 81):
        for y in range(55, 66):
            W.set(x, y, 80, T({"shape": "WALL"}))
    field(50, 58, 119, 62)
    W.set(60, 60, 80, T({"shape": "STAIR_DOWN", "outside": True}))
    wall = {"v": 1, "ground": "surface", "levels": [{"grid": ["W..@..W", "W.....W", "W.....W", "W.....W", "W.....W"]}],
            "legend": {}}
    open_ = {"v": 1, "ground": "surface", "levels": [{"grid": ["F..@..F", "F.....F", "F.....F", "F.....F", "F.....F"]}],
             "legend": {}}
    ok, reasons = B.validate_landmark(lt(open_), surface_site(73, 58), 2500)[:2]
    assert ok, [r.words for r in lua_list(reasons)]
    ok, reasons = B.validate_landmark(lt(wall), surface_site(73, 58), 2500)[:2]
    assert not ok and codes(reasons) == ["PATH"] and "cut the way in" in lua_list(reasons)[0].words, \
        [r.words for r in lua_list(reasons)]
    near = B.validate_landmark(lt(open_), surface_site(65, 58), 2500)[1]
    assert "WAY_IN" in codes(near), codes(near)
    W.set(74, 60, 80, T({"shape": "WALL", "outside": False}))
    assert "ROCK" in codes(B.validate_landmark(lt(open_), surface_site(73, 58), 2500)[1])


@test("checks: a drawing out of format is refused with ai-blueprints' reasons, before the map is read")
def _():
    _, site = rock_site()
    bad = descent()
    bad["levels"][0]["grid"][0] = bad["levels"][0]["grid"][0].replace("@", ".")
    ok, reasons = B.validate_landmark(lt(bad), site, 2500)[:2]
    assert not ok and reasons[1].code in ("JOIN", "FORMAT"), [r.code for r in lua_list(reasons)]
    sb = descent()
    sb["ground"] = "surface"
    sb["levels"] = [{"grid": ["W.@.W", "W...W"]}]
    ok, reasons = B.validate_landmark(lt(sb), site, 2500)[:2]
    assert not ok and codes(reasons) == ["SITE_GONE"], codes(reasons)


# --- building ----------------------------------------------------------------

@test("start: a dry run designates nothing; a real run designates exactly cost.dug (and its corridor), one project a level")
def _():
    _, site = rock_site()
    bp = lt(descent())
    d = B.build_landmark(bp, "S1", meta(), lt(NOW), True)
    assert d.ok and d.dry_run and designated_count() == 0, dict(d)
    assert not W.persist["ai-overseer/landmarks"] and not W.persist["ai-overseer/projects"]
    c = B.blueprints().cost(bp)
    r = B.build_landmark(bp, "S1", meta(), lt(NOW), False)
    assert r.ok and r.landmark_id == 1 and r.levels == 2 and r.quarter == site.q, dict(r)
    assert designated_count() == c.dug + len(lua_list(site.corridor)), (designated_count(), c.dug)
    for gx in range(7):
        for gy in range(7):
            for k in (1, 2):
                assert W.peek(*map_xy(site, gx, gy, k)).designated, (gx, gy, k)
    ps = lua_list(B.load_projects().list)
    assert [p.kind for p in ps] == ["landmark", "landmark"] and [p.params.level for p in ps] == [1, 2]
    assert all(p.params.landmark_id == 1 and p.params.name == "The Spiral" for p in ps)
    assert lua_list(r.project_ids) == [p.id for p in ps]
    # the site is taken: offered no more
    assert offered("S1") is None
    rep = lua_list(B.landmarks_report().list)
    assert len(rep) == 1 and rep[0].status == "building" and rep[0].levels == 2, dict(rep[0])


@test("start: a failure designating level 3 undoes levels 1 and 2 (nothing left designated, nothing recorded)")
def _():
    _, site = rock_site({"w": 7, "h": 7, "levels": 3, "ground": "rock"})
    LUA.execute(f"FAILZ = {site.z - 2}")
    r = B.build_landmark(lt(descent(3)), "S1", meta(), lt(NOW), False)
    assert not r.ok and "undone" in r.error, dict(r)
    assert designated_count() == 0, designated_count()
    assert not W.persist["ai-overseer/projects"] or len(lua_list(B.load_projects().list)) == 0
    assert len(lua_list(B.landmarks_data().list)) == 0


@test("projects: a landmark's levels run dig -> furnish -> done; the landmark takes one slot; the registry names them")
def _():
    rock_site()
    r = B.build_landmark(lt(descent()), "S1", meta(), lt(NOW), False)
    assert r.ok, dict(r)
    data = B.load_projects()
    open_ = B.open_projects(data)
    assert len(lua_list(open_)) == 2 and B.slot_cap(open_) == B.MAX_OPEN_PROJECTS + 1
    reg = [x for x in lua_list(B.registry_report()) if x.kind == "landmark"]
    assert [(x.name, x.landmark_id, x.level) for x in reg] == [("The Spiral", 1, 1), ("The Spiral", 1, 2)]
    for t in W.tiles.values():
        if t.designated:
            t.shape, t.designated = "FLOOR", False
    rep = B.projects_report()
    nexts = [p.next for p in lua_list(rep.open)]
    assert nexts == ["furnish", "furnish"], nexts
    step = B.landmark_step(1, False)
    assert not step.ok and step.rejected, dict(step)
    for pid in lua_list(r.project_ids):
        f = B.furnish_project(pid, True)
        assert f.ok, dict(f)
        d = B.finish_project(pid)
        assert d.ok and d.phase in ("done", "decorate"), dict(d)
    assert lua_list(B.landmarks_report().list)[0].status == "built"
    s = B.landmark_step(1, False)
    assert s.ok and s.done, dict(s)
    assert B.landmarks_data().list[1].status == "built"


@test("projects: a god-hall's zoned level is dedicated to its god when furnished (dedicate_temple, as a temple's)")
def _():
    rock_site()
    bp = descent()
    bp["zone"] = {"kind": "temple", "level": 1}
    r = B.build_landmark(lt(bp), "S1", meta(purpose="god_hall", deity_hf=7), lt(NOW), False)
    assert r.ok, dict(r)
    p1, p2 = lua_list(B.load_projects().list)
    assert p1.params.zone == "temple" and p2.params.zone is None and len(lua_list(p2.cells.zone)) == 0
    for t in W.tiles.values():
        if t.designated:
            t.shape, t.designated = "FLOOR", False
    real = B.dedicate_temple
    B.dedicate_temple = LUA.eval("function(p, pr) DEDICATED = pr.deity_hf; return 42 end")
    try:
        f = B.furnish_project(p1.id, True)
    finally:
        B.dedicate_temple = real
    assert f.ok and f.placed.dedicated == 42 and LUA.eval("DEDICATED") == 7, dict(f.placed)


@test("landmark_step: a surface tower walks clearing -> its build steps (E2: stair, walls, level 2) -> furnish -> zone -> done")
def _():
    field(20, 40, 100, 80)
    st = surface_site(80, 50)
    LUA.globals().TOWER_SITE = st
    W.persist["ai-overseer/bp-sites"] = lt({"asked": 0, "list": []})
    W.persist["ai-overseer/bp-sites"].list[1] = st
    r = B.build_landmark(lt(tower()), "S1", meta(name="The Tower", purpose="tower"), lt(NOW), False)
    assert r.ok and len(lua_list(r.project_ids)) == 0, dict(r)
    assert B.landmarks_open_surface() == 1 and B.slot_cap(LUA.table()) == B.MAX_OPEN_PROJECTS - 1
    stages = []

    def build(z):
        for c in lua_list(W.placed):
            if c.mode == "build" and c.z == z:
                shape = {"Cw": "WALL", "Cf": "FLOOR", "Cu": "STAIR_UP", "Cd": "STAIR_DOWN"}.get(c.text)
                W.set(c.x, c.y, z, T({"shape": shape or "FLOOR", "building": False}))

    for _ in range(12):
        s = B.landmark_step(1, False)
        stages.append((s.stage, bool(s.ok)))
        if s.done:
            break
        if s.stage == "build" and s.step == 2 and s.ok:
            # planned: waits; then built
            for c in lua_list(W.placed):
                if c.mode == "build":
                    W.set(c.x, c.y, c.z, T({"building": True}))
            w = B.landmark_step(1, False)
            assert not w.ok and w.waiting, dict(w)
        build(80)
        build(81)
    assert stages[-1] == ("zone", True), stages
    assert [st for st, _ in stages] == ["build", "build", "build", "furnish", "zone"], stages
    walls = [c for c in lua_list(W.placed) if c.text == "Cw"]
    assert len(walls) == 15 and all(c.z == 80 for c in walls), len(walls)
    assert any(c.text == "Cd" and c.z == 81 for c in lua_list(W.placed))
    assert any(c.mode == "zone" for c in lua_list(W.placed))
    assert B.landmarks_data().list[1].status == "built" and B.landmarks_open_surface() == 0
    again = B.landmark_step(1, False)
    assert not again.ok and again.done


@test("landmark_step: a dry run changes nothing")
def _():
    field(20, 40, 100, 80)
    W.persist["ai-overseer/bp-sites"] = lt({"asked": 0, "list": [{"id": "S1", "ground": "surface", "z": 80,
                                                                   "anchor": {"x": 80, "y": 50}, "q": 0}]})
    assert B.build_landmark(lt(tower()), "S1", meta(), lt(NOW), False).ok
    n = len(lua_list(W.placed))
    s = B.landmark_step(1, True)
    assert s.ok and s.dry_run and s.stage == "build", dict(s)
    assert len(lua_list(W.placed)) == n and B.landmarks_data().list[1].stage == "clearing"


@test("scripts unchanged: with no landmark, slot_cap and the registry read as before")
def _():
    assert B.slot_cap(LUA.table()) == B.MAX_OPEN_PROJECTS
    r = B.start_project(lt({"kind": "bedrooms", "rooms": 4, "room_size": 3}), lt(NOW))
    assert r.ok, dict(r)
    reg = lua_list(B.registry_report())
    assert reg[0].landmark_id is None and reg[0].level is None


# --- the bridge --------------------------------------------------------------

_hyg = (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8")
BRIDGE_HARNESS = re.search(r'HARNESS = r"""(.*?)"""', _hyg, re.S).group(1)
HL = LuaRuntime(unpack_returned_tuples=True)
H = HL.execute(BRIDGE_HARNESS, (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8"), str(LUA_DIR))


def ht(d):
    if isinstance(d, dict):
        return HL.table_from({k: ht(v) for k, v in d.items()})
    if isinstance(d, list):
        return HL.table_from([ht(v) for v in d])
    return d


def bridge():
    H.scripts = HL.table()
    H.halted = False
    M = H.module()
    H.scripts["ai-builder"] = HL.eval("""{
      build_landmark = function(bp, site, meta, now, dry) CALLED = {site = site, meta = meta, dry = dry}
        return {ok = true, dry_run = dry or nil, landmark_id = 1} end,
      landmark_sites = function(env, purpose, n) CALLED = {env = env, purpose = purpose, n = n}
        return {ok = true, asked = 1, sites = {}} end,
      landmark_step = function(id, dry) CALLED = {id = id, dry = dry} return {ok = true, landmark_id = id} end,
      landmarks_report = function() return {list = {{id = 1, name = 'The Spiral'}}} end}""")
    H.df.historical_figure = HL.eval("{find = function(id) if id == 7 then return {} end end}")
    return M


GOOD = {"type": "build_blueprint", "bp": {"v": 1}, "site": "S2", "name": "The Spiral of Ral", "purpose": "descent",
        "cap": 900, "by": "library"}


@test("bridge: the part loads; its actions, DRY_OK, DISPLAY_ONLY, the cache and the landmarks section are in place")
def _():
    M = bridge()
    for a in ("blueprint_sites", "build_blueprint", "landmark_step"):
        assert M.ACTIONS[a] is not None, a
    assert M.DRY_OK.build_blueprint and M.DRY_OK.landmark_step and not M.DRY_OK.blueprint_sites
    assert M.DISPLAY_ONLY.blueprint_sites and not M.DISPLAY_ONLY.build_blueprint
    assert lua_list(M.CACHE_INVALIDATES.build_blueprint) == ["registry"]
    assert lua_list(M.CACHE_INVALIDATES.landmark_step) == ["registry"]
    assert M.SECTIONS.landmarks().list[1].name == "The Spiral"
    assert "ai-bridge-design" in lua_list(M.BRIDGE_PARTS) and M.PART_VERSIONS["ai-bridge-design"] == M.BRIDGE_VERSION


@test("bridge: build_blueprint's arguments checked as start_project's are (site, name, purpose, cap, by, deity)")
def _():
    M = bridge()
    r = H.act(M, ht(GOOD))
    assert r.ok, dict(r)
    c = HL.eval("CALLED")
    assert c.site == "S2" and c.meta.cap == 900 and c.meta.by == "library" and not c.dry, dict(c)
    for bad, word in ((dict(site="S5"), "S1-S4"), (dict(site="x"), "S1-S4"), (dict(name="Ral 2"), "letters"),
                      (dict(name="A" * 41), "letters"), (dict(purpose="castle"), "purpose"),
                      (dict(cap=300), "cap"), (dict(cap=2600), "cap"), (dict(by="player"), "by"),
                      (dict(deity_hf=8), "deity"), (dict(bp="x"), "bp")):
        a = dict(GOOD)
        a.update(bad)
        r = H.act(M, ht(a))
        assert not r.ok and r.rejected and word in r.error, (bad, dict(r))
    a = dict(GOOD, deity_hf=7)
    assert H.act(M, ht(a)).ok and HL.eval("CALLED").meta.deity_hf == 7


@test("bridge: while halted, build_blueprint and landmark_step pass only as dry runs; blueprint_sites (display only) passes")
def _():
    M = bridge()
    H.halted = True
    r = H.act(M, ht(GOOD))
    assert not r.ok and r.halted, dict(r)
    r = H.act(M, ht(dict(GOOD, dry_run=True)))
    assert r.ok and r.dry_run and HL.eval("CALLED").dry is True, dict(r)
    r = H.act(M, ht({"type": "landmark_step", "landmark_id": 1}))
    assert not r.ok and r.halted
    assert H.act(M, ht({"type": "landmark_step", "landmark_id": 1, "dry_run": True})).ok
    r = H.act(M, ht({"type": "blueprint_sites", "env": {"w": 15, "h": 15, "levels": 4, "ground": "rock"},
                     "purpose": "descent", "n": 2}))
    assert r.ok, dict(r)
    c = HL.eval("CALLED")
    assert c.env.w == 15 and c.env.ground == "rock" and c.n == 2 and c.purpose == "descent"


@test("bridge: blueprint_sites refuses a bad envelope, purpose or n")
def _():
    M = bridge()
    base = {"type": "blueprint_sites", "env": {"w": 15, "h": 15, "levels": 4, "ground": "rock"}, "purpose": "descent"}
    for env, word in (({"w": 4, "h": 15, "levels": 4, "ground": "rock"}, "env.w"),
                      ({"w": 15, "h": 32, "levels": 4, "ground": "rock"}, "env.w"),
                      ({"w": 15, "h": 15, "levels": 6, "ground": "rock"}, "levels"),
                      ({"w": 15, "h": 15, "levels": 2, "ground": "air"}, "ground")):
        r = H.act(M, ht(dict(base, env=env)))
        assert not r.ok and word in r.error, (env, dict(r))
    assert "purpose" in H.act(M, ht(dict(base, purpose="moat"))).error
    assert "n must" in H.act(M, ht(dict(base, n=5))).error


@test("bridge: version_info carries ai-blueprints' limits and items (nil without the module)")
def _():
    M = bridge()
    H.scripts["ai-layouts"] = ht({"KINDS": [], "STOCKPILES": {}, "WORKSHOPS": {}})
    for k in ("getDFHackVersion", "getDFVersion"):
        H.dfhack[k] = HL.eval("function() return 'x' end")
    H.dfhack.findScript = HL.eval("function() return nil end")
    v = M.version_info()
    assert v.blueprint_limits is None and v.blueprint_items is None
    H.scripts["ai-blueprints"] = HL.eval("{BP_LIMITS = {w = 31, cost_max = 2500}, ITEMS = {Statue = 's', Table = 't'}}")
    v = M.version_info()
    assert v.blueprint_limits.cost_max == 2500 and lua_list(v.blueprint_items) == ["Statue", "Table"]
    # and build_blueprint holds the bridge's own cost_max under the cap asked
    H.scripts["ai-blueprints"].BP_LIMITS.cost_max = 800
    H.act(M, ht(GOOD))
    assert HL.eval("CALLED").meta.cap == 800


@test("needs: deity_spheres beside deity_ids, up to 4 sphere words a god")
def _():
    M = bridge()
    H.df.need_type = HL.eval("{[3] = 'PrayOrMeditate'}")
    H.df.sphere_type = HL.eval("{[1] = 'FIRE', [2] = 'WAR', [3] = 'DEATH', [4] = 'MOUNTAINS', [5] = 'SUN'}")
    H.df.historical_figure = HL.eval("""{find = function(id)
        return {name = 'Ral', info = {spheres = {spheres = {1, 2, 3, 4, 5}}}} end}""")
    unit = HL.eval("""{status = {current_soul = {personality = {needs = {{id = 3, focus_level = 0, deity_id = 9}}}}},
                       military = {squad_id = -1, squad_position = -1}, owned_buildings = {}}""")
    H.dfhack.units.getCitizens = HL.eval("function(u) return function() return {u} end end")(unit)
    H.dfhack.units.getStressCategory = HL.eval("function() return 4 end")
    n = M.get_needs()
    names = list(n.deity_ids)
    assert len(names) == 1 and n.deity_ids[names[0]] == 9, dict(n.deity_ids)
    assert list(n.deity_spheres) == names, dict(n.deity_spheres)
    sp = n.deity_spheres[names[0]]
    assert lua_list(sp) == ["fire", "war", "death", "mountains"], lua_list(sp)
    # a god whose spheres can't be read: no entry, the rest of the needs unharmed
    H.df.historical_figure = HL.eval("{find = function(id) return {name = 'Ral'} end}")
    n = M.get_needs()
    assert dict(n.deity_spheres) == {} and n.deity_ids[names[0]] == 9


# --- Lua 5.3 -----------------------------------------------------------------

@test("the new and changed Lua compiles under 5.3")
def _():
    L = LuaRuntime(unpack_returned_tuples=True)
    assert L.eval("_VERSION") == "Lua 5.3"
    for p in sorted(LUA_DIR.glob("*.lua")) + sorted((LUA_DIR / "gui").glob("*.lua")):
        ok, err = L.eval("function(s, n) local f, e = load(s, n, 't', {}); return f ~= nil, e end")(
            p.read_text(encoding="utf-8"), p.name)
        assert ok, (p.name, err)


if __name__ == "__main__":
    finish()
