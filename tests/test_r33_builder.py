"""(0.105.33, group builder) The L4 audit's builder fixes, on test_builder's
fake fort (its harness read by ast, as test_halls does) and test_construct_report's
fake constructions list: the join corridor never beside a cavern or open air,
a new stairwell's bottom level checked all round, the tile cache never left
live, the keep's stall on a non-wall building and its blocks, the player's
bridge left alone, the hall off the deep depot's mouth, the new corridor
reported apart, the constructions walk resumed. Needs lupa.

    python tests/test_r33_builder.py
"""

from __future__ import annotations

import ast
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


def _string_assign(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name)


HARNESS = _string_assign(ROOT / "tests" / "test_builder.py", "HARNESS")
FAKE_CONS = _string_assign(ROOT / "tests" / "test_construct_report.py", "FAKE")

LUA = LuaRuntime(unpack_returned_tuples=True)
LUA.globals().LUA_DIR = str(ROOT / "lua")
B, W = LUA.execute(HARNESS, (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8"),
                   (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8"))
T = LUA.table_from
LUA.execute("df = df or {}; df.global = df.global or {}; df.global.world = df.global.world or {}")
LUA.execute("df.global.world.buildings = {other = {TRADE_DEPOT = {}}}")
LUA.globals().W_PEEK = W.peek

# ai-joins over the same builder (its reqscript answers the builder, ai-util a stub)
J = LUA.execute(r"""
local src, B = ...
local U = {abs_tick = function() return 1000 end, site_get = function(k, d) return d end, site_put = function() end}
local env = setmetatable({reqscript = function(n) if n == 'ai-util' then return U end return B end,
                          dfhack = {buildings = {findCivzonesAt = function() return {} end,
                                                 findAtTile = function() return nil end}}},
                         {__index = _G})
assert(load(src, 'ai-joins', 't', env))()
return env
""", (ROOT / "lua" / "ai-joins.lua").read_text(encoding="utf-8"), B)

SAVED = {k: B[k] for k in ("tile_taken", "pasture_anchors", "dump_zones", "dump_keep_away", "keep_wall_waits",
                           "choose_site", "surface_farm_spots", "hall_planned_at", "hall_free_items",
                           "fell_tree", "walk_group")}


def _reset():
    W.reset()
    for k, v in SAVED.items():
        B[k] = v
    B.CACHE = None
    B.ROOF_STAIR = True
    B.CAVERN_NO_SPOT = None
    B.surface_farm_spots = LUA.eval("function() return {} end")
    B.hall_planned_at = LUA.eval("function() return false end")
    B.hall_free_items = LUA.eval("function() return 0 end")
    LUA.execute("df.global.world.buildings = {other = {TRADE_DEPOT = {}}}; df.building_type = nil")
    LUA.execute("dfhack.buildings = nil")


test = make_test(before=_reset)


def params(**kw):
    t = LUA.table()
    for k, v in kw.items():
        t[k] = T(v) if isinstance(v, (list, dict)) else v
    return t


def field(x1, y1, x2, y2, z=80):
    for x in range(x1, x2 + 1):
        for y in range(y1, y2 + 1):
            if (x, y) != (60, 60):
                W.set(x, y, z, T({"shape": "FLOOR", "material": "SOIL", "outside": True}))
            W.set(x, y, z + 1, T({"shape": "EMPTY", "outside": True}))


# --- L4 High: joins 371/387-388 -------------------------------------------------------

@test("joins: a cavern, open sky or open air beside a tile reads as danger; plain rock does not")
def _():
    W.set(30, 30, 70, T({"shape": "FLOOR", "feature": True}))
    W.set(31, 30, 70, T({"shape": "FLOOR", "outside": True}))
    W.set(32, 30, 70, T({"shape": "EMPTY"}))
    R = J.game_reader(70)
    assert R(30, 30).danger and R(31, 30).danger and R(32, 30).danger
    assert not R(33, 30).danger and R(33, 30).rock
    assert not R(45, 60).danger and R(45, 60).open        # the fort's own floor


@test("joins: no join corridor dug beside a cavern (the audit's case: refused, or routed clear of it)")
def _():
    z = 70
    for x in range(61, 67):                                # wall off the fort level into two areas
        for y in range(55, 66):
            W.set(x, y, z, T({"shape": "WALL", "material": "STONE"}))
    cavern = [(63, y) for y in range(57, 66)]
    for x, y in cavern:
        W.set(x, y, z, T({"shape": "FLOOR", "feature": True}))
    r, why, _stats = J.plan_join(J.game_reader(z), T([T({"x": 50, "y": 60}), T({"x": 70, "y": 60})]))
    if r:
        tiles = [(t.x, t.y) for t in r.tiles.values()]
        assert not any(max(abs(x - cx), abs(y - cy)) <= 1 for x, y in tiles for cx, cy in cavern), tiles
    else:
        assert why, why


# --- L4 High: sites 828-918 with check_extension 93-111 --------------------------------

@test("stairwell: check_extension reads the bottom level's 8 neighbours when asked (all_last)")
def _():
    W.set(71, 60, 62, T({"shape": "FLOOR", "feature": True}))     # a cavern beside the bottom
    ok_old = B.check_extension(70, 60, 66, 62)
    ok, why = B.check_extension(70, 60, 66, 62, True)
    assert ok_old is True or ok_old == (True,), ok_old            # the hub check's case: not read
    assert not ok and "cavern" in why, why


@test("stairwell: the bottom 'u' is never dug beside a cavern or water on its level")
def _():
    base = B.dig_stairwell(params(dir="east", elev_lo=62, elev_hi=66, min_dist=10, max_dist=40), True)
    assert base.ok and (base.x, base.y) == (70, 60), dict(base)
    W.set(71, 60, 62, T({"shape": "FLOOR", "feature": True}))
    W.set(70, 61, 62, T({"shape": "EMPTY", "liquid": True}))
    r = B.dig_stairwell(params(dir="east", elev_lo=62, elev_hi=66, min_dist=10, max_dist=40), True)
    if r.ok:
        assert max(abs(r.x - 71), abs(r.y - 60)) > 1 and max(abs(r.x - 70), abs(r.y - 61)) > 1, dict(r)
    assert B.CACHE is None


# --- L4 High: sites 828 / rooms 18 / surface 2368-2472: the tile cache --------------------

@test("cache: dig_stairwell leaves no live tile cache on any way out (a refusal, an error)")
def _():
    r = B.dig_stairwell(params(dir="up", elev_lo=62), False)
    assert not r.ok and B.CACHE is None, dict(r)
    real = B.find_stairs
    B.find_stairs = LUA.eval("function() return {} end")
    r = B.dig_stairwell(params(dir="north", elev_lo=0), False)
    assert not r.ok and "no main stair" in r.error and B.CACHE is None, dict(r)
    B.find_stairs = LUA.eval("function() error('boom') end")
    r = B.dig_stairwell(params(dir="north", elev_lo=0), False)
    assert not r.ok and "search failed" in r.error and B.CACHE is None, dict(r)
    B.find_stairs = real
    # a stale read is gone: a tile read, then changed, reads as it is now
    assert B.info(46, 25, 20).shape == "WALL"
    W.set(46, 25, 20, T({"shape": "FLOOR", "liquid": True}))
    assert B.info(46, 25, 20).shape == "FLOOR"


@test("cache: gate_dog_pen clears the cache, placed or failed")
def _():
    r = B.gate_dog_pen(params(x=60, y=60, z=70), True)
    assert r.ok and B.CACHE is None, dict(r)
    B.tile_taken = LUA.eval("function() error('boom') end")
    r = B.gate_dog_pen(params(x=60, y=60, z=70), True)
    assert not r.ok and "pen search failed" in r.error and B.CACHE is None, dict(r)


@test("cache: place_dump_zone (inside) clears the cache when its search throws, and when it ends")
def _():
    B.dump_zones = LUA.eval("function() return {} end")
    B.pasture_anchors = LUA.eval("function() return {{x = 60, y = 60, z = 80}} end")
    B.dump_keep_away = LUA.eval("function() error('boom') end")
    r = B.place_dump_zone(True, True)
    assert not r.ok and "dump search failed" in r.error and B.CACHE is None, dict(r)
    B.dump_keep_away = LUA.eval("function() return {} end")
    r = B.place_dump_zone(True, True)
    assert B.CACHE is None, dict(r)


# --- L4 Med: surface 582-590/895-906/1026-1033 (keep stall), planner_construct 458-462 ----

def _keep(stage="walls"):
    field(50, 50, 70, 70)
    W.persist["ai-overseer/keep"] = T({"x": 60, "y": 60, "z": 80, "r": 4, "stage": stage,
                                       "door": T({"x": 64, "y": 60})})


@test("keep: a non-wall building on a ring tile is a gap, not a wall waiting; the walls stage moves on")
def _():
    _keep()
    ring = [(x, y) for x in range(56, 65) for y in range(56, 65) if max(abs(x - 60), abs(y - 60)) == 4
            and (x, y) != (64, 60)]
    for x, y in ring:
        W.set(x, y, 80, T({"shape": "WALL", "material": "CONSTRUCTION"}))
    W.set(56, 56, 80, T({"shape": "FLOOR", "building": True}))       # a statue the player put there
    B.keep_wall_waits = LUA.eval("function(x, y, z) return not (x == 56 and y == 56) end")
    st = B.keep_status()
    assert st.walls_planned == 0 and st.walls_left == 1, dict(st)
    r = B.place_keep(True)
    assert not (r.waiting and "walls are going up" in (r.error or "")), dict(r)
    B.keep_wall_waits = SAVED["keep_wall_waits"]


@test("keep: keep_wall_waits: a Construction waits, any other building doesn't, unreadable = waits")
def _():
    LUA.execute("""
      df.building_type = {Construction = 5, Statue = 9}
      BLD = {['1,1,1'] = {getType = function() return 5 end}, ['2,2,2'] = {getType = function() return 9 end}}
      dfhack.buildings = {findAtTile = function(p) return BLD[p.x .. ',' .. p.y .. ',' .. p.z] end}
    """)
    assert B.keep_wall_waits(1, 1, 1) is True
    assert B.keep_wall_waits(2, 2, 2) is False
    LUA.execute("dfhack.buildings = nil")
    assert B.keep_wall_waits(1, 1, 1) is True


@test("keep: keep_status writes blocks_needed (walls + roof + stair), 0 once done")
def _():
    _keep("walls")
    st = B.keep_status()
    assert st.walls_left == 31 and st.blocks_needed == 31 + 49 + 2, dict(st)
    B.ROOF_STAIR = False
    assert B.keep_status().blocks_needed == 31 + 49
    _keep("done")
    assert B.keep_status().blocks_needed == 0


@test("keep: the brain's blocks rule counts the keep from keep_status's blocks_needed")
def _():
    sys.path.insert(0, str(ROOT / "brain"))
    import planner_construct as pc  # noqa: E402
    import inspect
    src = inspect.getsource(pc._construction_blocks_rule)
    assert 'k.get("blocks_needed")' in src
    _keep("walls")
    assert isinstance(B.keep_status().blocks_needed, int)


# --- L4 Med: surface 499-512 (remove_crossing) -----------------------------------------

def _bridges():
    LUA.execute("""
      df.building_type = {Bridge = 1}
      local function bridge(id, x1, y1, x2, y2, z)
        return {id = id, x1 = x1, y1 = y1, x2 = x2, y2 = y2, z = z, getType = function() return 1 end,
                getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end}
      end
      MAKE_BRIDGE = bridge
      BLD = {}
      DECON = {}
      dfhack.buildings = {findAtTile = function(p) return BLD[p.x .. ',' .. p.y .. ',' .. p.z] end,
                          deconstruct = function(b) table.insert(DECON, b.id) end}
    """)


@test("crossings: only the AI's own bridge (by id) is taken down; the player's over the same spot stays")
def _():
    _bridges()
    W.persist["ai-overseer/crossings"] = T({"list": T([T({"x": 50, "y": 50, "z": 90, "w": 3, "h": 1, "id": 7})])})
    LUA.execute("BLD['50,50,90'] = MAKE_BRIDGE(8, 50, 50, 52, 50, 90)")      # the player's
    r = B.remove_crossing(1, False)
    assert r.ok and not r.removed and len(LUA.eval("DECON")) == 0, dict(r)
    W.persist["ai-overseer/crossings"] = T({"list": T([T({"x": 50, "y": 50, "z": 90, "w": 3, "h": 1, "id": 8})])})
    r = B.remove_crossing(1, False)
    assert r.ok and r.removed and list(LUA.eval("DECON").values()) == [8], dict(r)


@test("crossings: a record from before ids: only the bridge on its exact rectangle is the AI's")
def _():
    _bridges()
    W.persist["ai-overseer/crossings"] = T({"list": T([T({"x": 50, "y": 50, "z": 90, "w": 3, "h": 1})])})
    LUA.execute("BLD['50,50,90'] = MAKE_BRIDGE(8, 49, 50, 53, 50, 90)")      # wider: the player's
    r = B.remove_crossing(1, False)
    assert r.ok and not r.removed and len(LUA.eval("DECON")) == 0, dict(r)
    W.persist["ai-overseer/crossings"] = T({"list": T([T({"x": 50, "y": 50, "z": 90, "w": 3, "h": 1})])})
    LUA.execute("BLD['50,50,90'] = MAKE_BRIDGE(9, 50, 50, 52, 50, 90)")
    r = B.remove_crossing(1, False)
    assert r.ok and r.removed and list(LUA.eval("DECON").values()) == [9], dict(r)


# --- L4 Med: halls 256-289 (the deep depot's mouth) -------------------------------------

@test("hall: never on the underground depot road's mouth (the wagons' turn-in ground)")
def _():
    field(66, 57, 74, 63)
    s = B.find_hall_site("field_hall")
    assert s and (s.x1, s.y1, s.x2, s.y2) == (66, 57, 74, 63), s
    B.deep_depot_mouth = LUA.eval("function() return {{x = 75, y = 60, z = 80}} end")
    s, why = B.find_hall_site("field_hall")
    assert s is None, (s and (s.x1, s.y1, s.x2, s.y2), why)
    B.deep_depot_mouth = LUA.eval("function() return {{x = 90, y = 90, z = 80}} end")
    assert B.find_hall_site("field_hall")
    B.deep_depot_mouth = LUA.eval("function() error('no deep depot data') end")
    assert B.find_hall_site("field_hall")


# --- Spacing (Lua side): the new corridor reported apart --------------------------------

@test("spacing: a site beside the stairs carries new_corridor (the dug corridor alone, walked tiles not counted)")
def _():
    B.TRY_BESIDE = True
    got = []
    real = SAVED["choose_site"]
    B.choose_site = lambda *a: (lambda r: got.append(r) or r)(real(*a))
    t = params(kind="bedrooms", rooms=8, room_size=3)
    r = B.start_project(t, T({"year": 148, "tick": 100}))
    B.TRY_BESIDE = False
    assert r.ok, r.error
    site = got[-1]
    assert isinstance(site.new_corridor, int) and 0 <= site.new_corridor <= site.corridor, \
        (site.new_corridor, site.corridor)
    assert site.corridor == r.corridor


# --- L4 Lows: ai-constructions 308-313, 325/336 ------------------------------------------

CW = LUA.execute(FAKE_CONS, (ROOT / "lua" / "ai-constructions.lua").read_text(encoding="utf-8"))


@test("constructions: a walk cut short resumes where it stopped next time, round to the start")
def _():
    CW.reset()
    CW.env.SURVEY_RESUME = None
    for i in range(600):
        CW.con(i % 100, i // 100, 60, 1, 1, True)
    CW.env.SURVEY_SECONDS = -1                     # cut at the first check (every 256th record)
    a = CW.env.survey(True)
    assert a.partial and a.total == 255 and a.resumed_at is None, (a.partial, a.total)
    b = CW.env.survey(True)
    assert b.partial and b.resumed_at == 255 and b.total == 255, (b.resumed_at, b.total)
    c = CW.env.survey(True)
    assert c.partial and c.resumed_at == 510 and c.total == 255, (c.resumed_at, c.total)   # 90, then 165 from 1
    assert CW.env.SURVEY_RESUME.at == 165, CW.env.SURVEY_RESUME.at
    CW.env.SURVEY_SECONDS = 100
    d = CW.env.survey(True)
    assert not d.partial and d.total == 600 and CW.env.SURVEY_RESUME is None, (d.partial, d.total)
    e = CW.env.survey(True)
    assert e.total == 600 and e.resumed_at is None
    CW.env.SURVEY_SECONDS = 0.25


@test("constructions: a missing designation.subterranean doesn't throw the survey (read as surface)")
def _():
    CW.reset()
    CW.env.SURVEY_RESUME = None
    CW.con(10, 10, 80, 1, 1, False)
    CW.con(11, 10, 80, 2, 1, False)
    LUA.execute("""
      local W = ...
      W.old_flags = W.env.dfhack.maps.getTileFlags
      W.env.dfhack.maps.getTileFlags = function()
        return setmetatable({outside = false}, {__index = function(_, k) error('no field ' .. k) end})
      end
    """, CW)
    s = CW.env.survey(True)
    LUA.execute("local W = ...; W.env.dfhack.maps.getTileFlags = W.old_flags", CW)
    assert s.total == 2 and s.surface.total == 2, (s.total, dict(s.surface))


if __name__ == "__main__":
    finish()
