"""(r9, builder f1) The A3 audit's builder findings, finished: the join and
widening corridors keep off space to come (a designated tile, a room still
being dug) and off water above. On test_builder's fake fort, as test_r33_builder.

    python tests/test_r9_f1_builder.py
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


def split_level(z=70):
    for x in range(61, 67):                                # wall off the fort level into two areas
        for y in range(55, 66):
            W.set(x, y, z, T({"shape": "WALL", "material": "STONE"}))


def tiles_of(r):
    return [(t.x, t.y) for t in r.tiles.values()]


# --- A3 8: joins beside undug designations and under water ---------------------------

@test("joins (r9): the corridor found on a split level (the case the next tests block)")
def _():
    split_level()
    r, why, _ = J.plan_join(J.game_reader(70), T([T({"x": 50, "y": 60}), T({"x": 70, "y": 60})]))
    assert r, why


def near(tiles, x, y):
    return any(max(abs(tx - x), abs(ty - y)) <= 1 for tx, ty in tiles)


@test("joins (r9): a tile designated and not dug beside the way is other space: routed clear or refused")
def _():
    split_level()
    W.set(63, 57, 70, T({"designated": True}))
    R = J.game_reader(70)
    assert R(63, 57).other and not R(63, 57).open and not R(40, 70).other
    r, why, _ = J.plan_join(R, T([T({"x": 50, "y": 60}), T({"x": 70, "y": 60})]))
    assert why is None or "other space" in why or "none" in why, why
    if r:
        assert not near(tiles_of(r), 63, 57), sorted(tiles_of(r))


@test("joins (r9): the inside of a room still being dug is other space (its wall ring is not)")
def _():
    split_level()
    W.persist["ai-overseer/projects"] = LUA.eval("""function()
        return {next_id = 2, list = {{id = 1, kind = 'bedrooms', phase = 'dig', z = 70, anchor = {x = 63, y = 58},
                area = {x1 = 62, y1 = 56, x2 = 65, y2 = 60, z = 70}}}} end""")()
    R = J.game_reader(70)
    assert R(63, 57).other and R(64, 59).other
    assert not R(62, 56).other and not R(65, 60).other        # the ring
    r, why, _ = J.plan_join(R, T([T({"x": 50, "y": 60}), T({"x": 70, "y": 60})]))
    if r:
        assert not any(63 <= x <= 64 and 56 <= y <= 60 for x, y in tiles_of(r)), sorted(tiles_of(r))
    # finished, the room no longer counts
    W.persist["ai-overseer/projects"].list[1].phase = "done"
    assert not J.game_reader(70)(63, 57).other


@test("joins (r9): no corridor tile dug under water or aquifer on the level above")
def _():
    split_level()
    wet = [(x, y) for x in range(61, 67) for y in (55, 56, 57)]
    for x, y in wet:
        W.set(x, y, 71, T({"shape": "WALL", "aquifer": True}))
    R = J.game_reader(70)
    assert R(63, 56).wet_above and not R(63, 60).wet_above
    r, why, _ = J.plan_join(R, T([T({"x": 50, "y": 60}), T({"x": 70, "y": 60})]))
    if r:
        assert not set(tiles_of(r)) & set(wet), sorted(tiles_of(r))
    else:
        assert why, why


@test("widening (r9): a second row never beside a designated tile nor under water")
def _():
    z = 70
    # one corridor 1 wide, 8 long, between two halls: x 61..68 at y 60
    for x in range(61, 69):
        for y in range(55, 66):
            W.set(x, y, z, T({"shape": "WALL", "material": "STONE"}))
    for x in range(61, 69):
        W.set(x, 60, z, T({"shape": "FLOOR"}))
    run = T({"axis": "ew", "tiles": T([T({"x": x, "y": 60}) for x in range(61, 69)])})
    w = J.widen_run(J.game_reader(z), run)
    assert w and not isinstance(w, tuple), w               # the plain case widens
    W.set(64, 62, z, T({"designated": True}))              # beside the row y 61
    for x in range(61, 69):
        W.set(x, 59, z + 1, T({"shape": "WALL", "liquid": True}))   # water over the row y 59
    w, why = J.widen_run(J.game_reader(z), run)
    assert w is None and why, (w and sorted(tiles_of(w)), why)


# --- A3 9: the garden court's meeting area is outside the gates ---------------------

def _gates_env():
    from lua_modules_util import module_src
    G = LuaRuntime(unpack_returned_tuples=True)
    M = G.execute("local src = ...; local env = setmetatable({}, {__index = _G}); "
                  "assert(load(src, 'ai-gates', 't', env))(); return env", module_src("ai-gates.lua"))
    # two meeting areas: the garden court's under the sky (x10), a hall inside (x30)
    G.execute("""local M = ...
      local zones = {{centerx = 10, centery = 5, z = 150}, {centerx = 30, centery = 5, z = 140}}
      M.df = {global = {world = {buildings = {other = {ZONE_MEETING_HALL = zones}}}}}
      M.dfhack = {maps = {getTileFlags = function(x, y, z) return {outside = z == 150} end,
                          getWalkableGroup = function(p) return p.z == 150 and 7 or 3 end},
                  units = {getCitizens = function() return {} end}}
      M.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
      M.GATES = {entrances = {}}""", M)
    return G, M


@test("gates (r9): a meeting area under the sky (the garden court's) is never the fort's inside")
def _():
    G, M = _gates_env()
    starts = [(p.x, p.y, p.z) for p in M.fort_anchor_starts().values()]
    assert starts == [(30, 5, 140)], starts
    fi = M.fort_interior()
    assert fi and fi.what == "meeting hall" and fi.x == 30 and fi.group == 3, fi and dict(fi)


# --- A3 16: a stuck surface landmark pins a building slot ---------------------------

@test("landmarks (r9): a surface landmark with nothing built for LANDMARK_SLOT_DAYS holds its slot no longer")
def _():
    real = B.now_tick
    LUA.execute("W_NOW = 2000000")
    B.now_tick = LUA.eval("function() return W_NOW end")
    try:
        W.persist["ai-overseer/landmarks"] = LUA.eval("""function() return {next = 2, list = {{landmark_id = 1,
            ground = 'surface', status = 'building', stage = 'walls', level = 1, name = 'Tower',
            surface = {{z = 80, walls = {{x = 50, y = 50, text = 'Cw'}, {x = 51, y = 50, text = 'Cw'}},
                        floor = {}, furnish = {}, place = {}, zone = {}}}}}} end""")()
        W.set(50, 50, 80, T({"shape": "FLOOR", "building": True}))      # both walls planned, no blocks
        W.set(51, 50, 80, T({"shape": "FLOOR", "building": True}))
        assert B.landmarks_open_surface() == 1                          # (an older record: counted)
        r = B.landmark_step(1, False)
        assert r.waiting and r.left == 2, dict(r)
        rec = W.persist["ai-overseer/landmarks"].list[1]
        assert rec.progress_tick == 2000000
        LUA.execute("W_NOW = W_NOW + 59 * 1200")
        B.landmark_step(1, False)                                       # nothing changed: the clock runs on
        assert rec.progress_tick == 2000000 and B.landmarks_open_surface() == 1
        LUA.execute("W_NOW = W_NOW + 1200")
        assert B.landmarks_open_surface() == 0                          # 60 days: the slot is free
        W.set(50, 50, 80, T({"shape": "WALL", "building": False}))      # a wall built: counted again
        B.landmark_step(1, False)
        assert rec.progress_tick == LUA.eval("W_NOW") and B.landmarks_open_surface() == 1
    finally:
        B.now_tick = real


# --- A3 17: furnish progress walks the buildings once a report ----------------------

@test("furnish_progress (r9): inside a report the buildings are walked once for all the levels furnishing")
def _():
    real_planned, real_util = B.is_planned, B.util_module
    try:
        B.df = LUA.eval("""(function()
          local bt = {Bed = 3, [3] = 'Bed', Stockpile = 90, Civzone = 91}
          WALKS = 0
          local list = {}
          for i = 1, 12 do
            local z = 68 + i % 4
            list[i] = {x1 = 5, x2 = 5, y1 = 5, y2 = 5, z = z, flags = {exists = i % 2 == 0},
                       getType = function() return 3 end, getSubtype = function() return -1 end}
          end
          local all = setmetatable({}, {__index = function(_, i) if i == 1 then WALKS = WALKS + 1 end return list[i] end})
          return {building_type = bt, workshop_type = {}, furnace_type = {},
                  global = {world = {buildings = {all = all}}}}
        end)()""")
        B.is_planned = LUA.eval("function(b) return true end")
        p70 = LUA.eval("{area = {x1 = 0, x2 = 10, y1 = 0, y2 = 10, z = 70}}")
        p71 = LUA.eval("{area = {x1 = 0, x2 = 10, y1 = 0, y2 = 10, z = 71}}")
        plain = [(f.placed, f.done) for f in (B.furnish_progress(p70), B.furnish_progress(p71))]
        assert LUA.eval("WALKS") == 2                                  # outside a report: a walk each
        LUA.execute("WALKS = 0")
        B.util_module = LUA.eval("(function() local U = {REPORT_CTX = {}} return function() return U end end)()")
        inside = [(f.placed, f.done) for f in (B.furnish_progress(p70), B.furnish_progress(p71),
                                                B.furnish_progress(p70))]
        assert LUA.eval("WALKS") == 1, LUA.eval("WALKS")
        assert inside == plain + plain[:1] and plain == [(3, 3), (3, 0)], (plain, inside)
    finally:
        B.df = None
        B.is_planned, B.util_module = real_planned, real_util


if __name__ == "__main__":
    finish()
