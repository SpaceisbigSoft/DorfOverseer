"""(0.105.40b) The dig guard: no dig the AI marks may take raw adamantine, the
adamantine spire or the underworld, nor a tile beside one (the 8 around on
its level, the one over and under it).

  1. the helper (lua/ai-util.lua dig_forbidden, deep_tile, dig_guard_data,
     deep_hazard) on a fake map: each kind of deep tile, the neighbours, the
     memo, identity on a map without adamantine;
  2. every dig path refusing: quickfort's dig blueprints (ai-builder
     quickfort_apply, qf_try, the wells' and cistern's designate, the site
     check, the way in), the joins and widenings, the ore veins and drifts,
     DFHack's dig-now; and a source audit that no path marks digging
     without the guard;
  3. the report (the deep section's deep_hazard) and the Rules switch
     mine_adamantine (reserved: still refused);
  4. the brain (brain/planner_deep.py): no mine_ore of adamantine, the note,
     the digest line, and plan() on the fixtures the same as main's.

    python tests/test_r41_dig_guard.py
"""

from __future__ import annotations

import ast
import atexit
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LUA_DIR = ROOT / "lua"
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src, UTIL_SRC  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:  # pragma: no cover
    LuaRuntime = None

from planner_core import Proposal  # noqa: E402
import planner_deep as PD  # noqa: E402
from digest import digest  # noqa: E402


def lua_const(test_file: str, name: str) -> str:
    """A string constant of another test file (its fake world), read without running it."""
    tree = ast.parse((ROOT / "tests" / test_file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return eval(compile(ast.Expression(node.value), test_file, "eval"), {"__builtins__": {}})
    raise KeyError(name)


# --- the fake deep: tiles by position, blocks made on demand ------------------------------

DEEP = r"""
local D = {}
local FT = {outdoor_river = 0, cave = 1, deep_special_tube = 5, deep_surface_portal = 6,
            subterranean_from_layer = 7, magma_core_from_layer = 8, underworld_from_layer = 9}
local MAT = {STONE = 1, FEATURE = 2, HFS = 3, MINERAL = 4}
local MAT_NAME = {[1] = 'STONE', [2] = 'FEATURE', [3] = 'HFS', [4] = 'MINERAL'}
local ADAM, GRANITE, HEMATITE = 7, 1, 2
local function key(x, y, z) return x .. ',' .. y .. ',' .. z end
local function bkey(bx, by, z) return bx .. ',' .. by .. ',' .. z end
function D.reset()
  D.tiles, D.block_feat = {}, {}
  D.local_types, D.global_types = {}, {}
  D.init_lookup = true
  D.calls = 0
end
function D.tile(x, y, z)
  local t = D.tiles[key(x, y, z)]
  if t then return t end
  return {hidden = false, feature_local = false, feature_global = false, dig = 0, flow_size = 0,
          water_table = false, outside = false, mat = 'STONE'}
end
function D.set(x, y, z, f)
  local t = D.tiles[key(x, y, z)]
  if not t then t = D.tile(x, y, z); t.x, t.y, t.z = x, y, z; D.tiles[key(x, y, z)] = t end
  for k, v in pairs(f) do t[k] = v end
  return t
end
-- the block's features: {lf = local feature index, gf = global feature index}
function D.feat(bx, by, z, f) D.block_feat[bkey(bx, by, z)] = f end
local MINERAL = {}
function D.block(bx, by, z)
  D.calls = D.calls + 1
  local f = D.block_feat[bkey(bx, by, z)] or {}
  local b = {map_pos = {x = bx * 16, y = by * 16, z = z}, region_pos = {x = 3, y = 4},
             local_feature = f.lf or -1, global_feature = f.gf or -1, flags = {designated = false},
             block_events = {}, designation = {}}
  local masks = {}
  for _, t in pairs(D.tiles) do
    if t.z == z and t.x // 16 == bx and t.y // 16 == by and t.vein then
      masks[t.vein] = masks[t.vein] or {}
      masks[t.vein][(t.x & 15) * 16 + (t.y & 15)] = true
    end
  end
  for mat, m in pairs(masks) do
    table.insert(b.block_events, {_cls = MINERAL, inorganic_mat = mat, tile_bitmask = m})
  end
  for lx = 0, 15 do
    b.designation[lx] = setmetatable({}, {__index = function(_, ly) return D.tile(bx * 16 + lx, by * 16 + ly, z) end})
  end
  return b
end
function D.blocks()
  local seen, out = {}, {}
  for _, t in pairs(D.tiles) do
    local k = bkey(t.x // 16, t.y // 16, t.z)
    if not seen[k] then seen[k] = true; table.insert(out, D.block(t.x // 16, t.y // 16, t.z)) end
  end
  for k, _ in pairs(D.block_feat) do
    if not seen[k] then
      seen[k] = true
      local bx, by, z = k:match('(-?%d+),(-?%d+),(-?%d+)')
      table.insert(out, D.block(tonumber(bx), tonumber(by), tonumber(z)))
    end
  end
  return out
end
local function feature_init(t) return {_t = t, getType = function() return t end} end
D.df = {
  global = {cur_year = 250, cur_year_tick = 1000,
            world = {raws = {inorganics = {all = {[ADAM] = {id = 'RAW_ADAMANTINE', flags = {DEEP_SPECIAL = true}},
                                                  [GRANITE] = {id = 'GRANITE', flags = {}},
                                                  [HEMATITE] = {id = 'HEMATITE', flags = {}}}}},
                     features = {map_features = {}, feature_local_idx = {}, feature_global_idx = {}},
                     map = setmetatable({}, {__index = function(_, k) if k == 'map_blocks' then return D.blocks() end end})}},
  feature_type = FT,
  block_square_event_mineralst = {is_instance = function(_, e) return type(e) == 'table' and e._cls == MINERAL end},
  feature_init_deep_special_tubest = {is_instance = function(_, f) return f._t == FT.deep_special_tube end},
  feature_init_deep_surface_portalst = {is_instance = function(_, f) return f._t == FT.deep_surface_portal end},
  feature_init_underworld_from_layerst = {is_instance = function(_, f) return f._t == FT.underworld_from_layer end},
  tiletype = {attrs = {[1] = {material = 1}, [2] = {material = 2}, [3] = {material = 3}, [4] = {material = 4}}},
  tiletype_material = MAT_NAME,
  tile_dig_designation = {No = 0, Default = 1},
}
-- the map's features (the index fallback when DFHack's init lookups are missing)
function D.sync_features()
  local F = D.df.global.world.features
  F.map_features, F.feature_local_idx, F.feature_global_idx = {}, {}, {}
  for idx, t in pairs(D.local_types) do
    table.insert(F.map_features, feature_init(t)); table.insert(F.feature_local_idx, idx); table.insert(F.feature_global_idx, -1)
  end
  for idx, t in pairs(D.global_types) do
    table.insert(F.map_features, feature_init(t)); table.insert(F.feature_local_idx, -1); table.insert(F.feature_global_idx, idx)
  end
end
D.maps = {
  getTileBlock = function(x, y, z) return D.block(x // 16, y // 16, z) end,
  getTileFlags = function(x, y, z) return D.tile(x, y, z), {building = 0} end,
  getTileType = function(x, y, z) local t = D.tile(x, y, z); return MAT[t.mat] or 1 end,
  getTileAssignment = function(m, lx, ly) return m[lx * 16 + ly] == true end,
}
D.maps.getLocalInitFeature = function(rp, idx)
  if not D.init_lookup then error('no getLocalInitFeature here') end
  local t = D.local_types[idx]
  return t and feature_init(t) or nil
end
D.maps.getGlobalInitFeature = function(idx)
  if not D.init_lookup then error('no getGlobalInitFeature here') end
  local t = D.global_types[idx]
  return t and feature_init(t) or nil
end
D.dfhack = {maps = D.maps, persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end}}
D.FT, D.ADAM, D.HEMATITE = FT, ADAM, HEMATITE
D.reset()
return D
"""

if LuaRuntime is not None:
    LUA = LuaRuntime(unpack_returned_tuples=True)
    D = LUA.execute(DEEP)
    U = LUA.execute("local src, D = ...; local env = setmetatable({df = D.df, dfhack = D.dfhack}, {__index = _G}); "
                    "assert(load(src, 'ai-util', 't', env))(); return env", UTIL_SRC, D)
else:  # pragma: no cover
    LUA = D = U = None


def T(d):
    return LUA.table_from({k: (LUA.table_from(v) if isinstance(v, dict) else v) for k, v in d.items()})


def reset():
    D.reset()
    U.dig_guard_reset()
    U.DIG_GUARD = T({"refused": 0, "by": {}, "last": {}})
    U.DEEP_HAZARD_CACHE = None



def guard(x, y, z):
    U.dig_guard_reset()
    return U.dig_forbidden(x, y, z)


def adamantine(x, y, z, **kw):
    D.set(x, y, z, T(dict({"vein": D.ADAM, "mat": "MINERAL"}, **kw)))


# --- 1. the helper ------------------------------------------------------------------------

def util_test(name):
    def deco(fn):
        def run():
            if LuaRuntime is None:
                return
            reset()
            fn()
        return test(name)(run)
    return deco


@util_test("helper: a map without adamantine, the spire or the underworld refuses nothing (a cavern, a river, granite)")
def _():
    D.set(10, 10, 50, T({"vein": 1, "mat": "MINERAL"}))           # granite vein
    D.set(12, 10, 50, T({"vein": D.HEMATITE, "mat": "MINERAL"}))  # hematite
    D.feat(0, 0, 40, T({"gf": 2}))
    D.global_types[2] = D.FT.subterranean_from_layer             # a cavern
    D.set(5, 5, 40, T({"feature_global": True}))
    D.feat(1, 1, 50, T({"lf": 1}))
    D.local_types[1] = D.FT.outdoor_river
    D.set(20, 20, 50, T({"feature_local": True}))
    for x, y, z in [(10, 10, 50), (11, 10, 50), (12, 10, 50), (5, 5, 40), (5, 5, 41), (20, 20, 50), (0, 0, 0)]:
        assert guard(x, y, z) is None, (x, y, z, guard(x, y, z))


@util_test("helper: raw adamantine (a DEEP_SPECIAL vein) refused, and the 8 around, the one over and under; not further")
def _():
    adamantine(30, 30, 20)
    assert guard(30, 30, 20) == "raw adamantine"
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx or dy:
                assert guard(30 + dx, 30 + dy, 20) == "next to raw adamantine", (dx, dy)
    assert guard(30, 30, 21) == "over raw adamantine"
    assert guard(30, 30, 19) == "under raw adamantine"
    for x, y, z in [(32, 30, 20), (31, 30, 21), (30, 31, 19), (30, 30, 22), (28, 28, 20)]:
        assert guard(x, y, z) is None, (x, y, z)
    # a hidden one too: the guard reads the tile, not what the dwarves have seen
    adamantine(60, 60, 20, hidden=True)
    assert guard(61, 60, 20) == "next to raw adamantine"


@util_test("helper: the spire (feature_local in a deep_special_tube block), by DFHack's lookup and by the map's index")
def _():
    D.feat(2, 2, 25, T({"lf": 4}))
    D.local_types[4] = D.FT.deep_special_tube
    D.set(40, 40, 25, T({"feature_local": True, "mat": "FEATURE"}))
    assert guard(40, 40, 25) == "the adamantine spire"
    assert guard(39, 41, 25) == "next to the adamantine spire"
    D.init_lookup = False                       # no getLocalInitFeature: the map_features index
    D.sync_features()
    assert guard(40, 40, 25) == "the adamantine spire"
    D.local_types[4] = D.FT.cave                # a plain cave: nothing (no FEATURE stone)
    D.set(40, 40, 25, T({"mat": "STONE"}))
    D.sync_features()
    assert guard(40, 40, 25) is None
    D.local_types[4] = D.FT.deep_surface_portal
    D.sync_features()
    assert guard(40, 40, 25) == "the adamantine spire"


@util_test("helper: the underworld (feature_global of underworld_from_layer), its HFS, and special stone of an unknown layer")
def _():
    D.feat(0, 0, 3, T({"gf": 9}))
    D.global_types[9] = D.FT.underworld_from_layer
    D.set(8, 8, 3, T({"feature_global": True}))
    assert guard(8, 8, 3) == "the underworld"
    assert guard(8, 8, 4) == "over the underworld"
    D.set(50, 50, 6, T({"mat": "HFS"}))
    assert guard(50, 51, 6) == "next to the underworld"
    D.feat(5, 5, 3, T({"gf": 11}))              # unknown layer: map special stone of it refused
    D.set(85, 85, 3, T({"feature_global": True, "mat": "FEATURE"}))
    assert guard(85, 85, 3) == "the underworld"
    D.global_types[11] = D.FT.magma_core_from_layer   # known: the magma sea, no refusal
    assert guard(85, 85, 3) is None


@util_test("helper: the memo reads a block once per tick for many tiles; dig_check_tiles names the first refused")
def _():
    adamantine(30, 30, 20)
    U.dig_guard_reset()
    D.calls = 0
    for x in range(20, 40):
        U.dig_forbidden(x, 30, 20)
    assert D.calls <= 12, D.calls             # 20 tiles x 11 reads: a dozen blocks, not 220
    why, at = U.dig_check_tiles(LUA.table_from({1: T({"x": 25, "y": 30}), 2: T({"x": 29, "y": 31})}), 20, "test")
    assert why == "next to raw adamantine" and (at.x, at.y, at.z) == (29, 31, 20), (why, dict(at))
    assert U.DIG_GUARD.refused == 1 and U.DIG_GUARD.by.test == 1


@util_test("helper: dig_guard_data takes refused tiles out of a quickfort dig blueprint; extents split; channels over it")
def _():
    adamantine(30, 30, 20)
    data = LUA.eval("""function() return {[20] = {
        [0] = {[0] = 'd(5x1)', [10] = 'd5'},
        [1] = {[0] = 'Cw'},                        -- not a dig key: kept
        [3] = {[0] = 'u'}}} end""")()
    out, n, why = U.dig_guard_data(data, 28, 30, 0, "quickfort")
    # d(5x1) at x 28-32, y 30: 29, 30, 31 refused; 28 and 32 kept as single cells
    assert n == 3 and why == "next to raw adamantine", (n, why)
    row = out[20][0]
    assert row[0] == "d" and row[4] == "d" and row[1] is None and row[2] is None and row[3] is None, dict(row)
    assert row[10] == "d5" and out[20][1][0] == "Cw" and out[20][3][0] == "u", dict(row)
    assert U.DIG_GUARD.refused == 3 and U.DIG_GUARD.by.quickfort == 3
    # nothing refused: the very same table back
    same, n2, _ = U.dig_guard_data(data, 0, 0, 0, None)
    assert n2 == 0 and LUA.eval("rawequal")(same, data)
    # a channel over a tile beside adamantine: refused (it digs that tile)
    ch = LUA.eval("function() return {[22] = {[0] = {[0] = 'h'}}} end")()
    out, n, why = U.dig_guard_data(ch, 30, 30, 0, None)
    assert n == 1 and why == "a channel down to a tile over raw adamantine" and LUA.eval("next")(out[22]) is None, (n, why)
    assert U.dig_forbidden(30, 30, 22) is None                         # the tile itself: two over
    # negative extents run left / up
    neg = LUA.eval("function() return {[20] = {[0] = {[0] = 'j(-3x-1)'}}} end")()
    out, n, _ = U.dig_guard_data(neg, 32, 30, 0, None)         # x 30-32: 30 and 31 refused
    assert n == 2 and out[20][0][0] == "j" and out[20][0][-1] is None, n


@util_test("helper: deep_hazard counts only uncovered adamantine (the highest level, the nearest), the refusals, the switch")
def _():
    adamantine(30, 30, 20)
    adamantine(31, 30, 20)
    adamantine(30, 30, 24, hidden=True)        # not seen: not counted
    D.feat(0, 0, 3, T({"gf": 9}))
    D.global_types[9] = D.FT.underworld_from_layer
    D.sync_features()
    D.set(0, 0, 3, T({"feature_global": True, "hidden": True}))
    h = U.deep_hazard(T({"x": 40, "y": 30, "z": 30}), False)
    assert h.adamantine_seen is True and h.tiles == 2 and h.nearest_z == 20 and h.top_z == 20, dict(h)
    assert (h.nearest.x, h.nearest.y) == (31, 30) and h.refused == 0, dict(h)
    assert h.underworld_seen is True and h.spire_seen is False, dict(h)      # the block's other tiles are uncovered
    assert h.mine_adamantine is None and h.note is None
    U.dig_refused("quickfort", 30, 31, 20, "next to raw adamantine")
    h = U.deep_hazard(None, True)
    assert h.refused == 1 and h.refused_by.quickfort == 1 and h.refused_last.why == "next to raw adamantine", dict(h)
    assert h.mine_adamantine is True and "not built yet" in h.note, dict(h)
    reset()
    h = U.deep_hazard(None, False)
    assert h.adamantine_seen is False and h.tiles == 0 and h.nearest_z is None, dict(h)


# --- 2. every dig path ---------------------------------------------------------------------

def wayin_world():
    """test_r32_wayin's fake world and builder, with the fake deep in ai-util's env."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(LUA_DIR)
    harness = lua_const("test_r32_wayin.py", "HARNESS")
    layouts = (LUA_DIR / "ai-layouts.lua").read_text(encoding="utf-8")
    builder = (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8")
    B, W, G = lua.execute(harness, layouts, builder, module_src("ai-gates.lua"))
    Dw = lua.execute(DEEP)
    Uw = B.util_module()
    Uw.df, Uw.dfhack = Dw.df, Dw.dfhack
    Uw.dig_guard_reset()
    return lua, B, W, Dw, Uw


def two(r):
    """The first two values of a Lua call (lupa gives a tuple for several, the value for one)."""
    r = r if isinstance(r, tuple) else (r,)
    return (r + (None, None))[:2]


def path_test(name):
    def deco(fn):
        def run():
            if LuaRuntime is None:
                return
            fn()
        return test(name)(run)
    return deco


@path_test("quickfort_apply (every level, hall, well, cistern, landmark): a dig cell by adamantine is refused, "
           "dry run or not; an undo and other modes pass; the stats say why")
def _():
    lua, B, W, Dw, Uw = wayin_world()
    Dw.set(42, 25, 27, lua.table_from({"vein": Dw.ADAM, "mat": "MINERAL"}))
    Uw.dig_guard_reset()
    cell = lua.eval("function(t) return {{x = 0, y = 0, text = t}} end")
    st = B.quickfort_apply("dig", cell("d"), 27, 43, 25, "run", True)
    assert st.dig_designated.value == 0 and st.dig_guard_refused.value == 1, dict(st)
    assert st.dig_guard_why == "next to raw adamantine" and Uw.DIG_GUARD.refused == 0   # a dry run: not counted
    st = B.quickfort_apply("dig", cell("d"), 27, 43, 25)
    assert st.dig_designated.value == 0 and Uw.DIG_GUARD.refused == 1 and not W.get(43, 25, 27).designated
    st = B.quickfort_apply("dig", cell("d"), 27, 45, 25)                 # 3 tiles away: dug
    assert st.dig_designated.value == 1 and st.dig_guard_refused is None and W.get(45, 25, 27).designated
    calls = len(W.calls)
    B.quickfort_apply("dig", cell("d"), 27, 43, 25, "undo")             # an undo is never refused
    assert W.calls[calls + 1].command == "undo"
    good, failed, _ = B.qf_try("dig", cell("j"), 28, 42, 25, False)          # over it: qf_try refuses
    assert good is False and failed == "dry", (good, failed)
    assert B.designate(lua.eval("function() return {{x = 41, y = 25, text = 'd'}} end")(), 27, "dig") is False


@path_test("the way in (dig_way_in): the column beside adamantine is never dug; another is, or none")
def _():
    lua, B, W, Dw, Uw = wayin_world()
    r0 = B.dig_way_in(lua.table_from({"x": 46, "y": 25, "z": 30}), lua.table_from({"year": 253, "tick": 100}), True)
    assert r0.ok and (r0.column.x, r0.column.y) == (41, 25), dict(r0)
    Dw.set(42, 25, 27, lua.table_from({"vein": Dw.ADAM, "mat": "MINERAL"}))
    Uw.dig_guard_reset()
    r = B.dig_way_in(lua.table_from({"x": 46, "y": 25, "z": 30}), lua.table_from({"year": 253, "tick": 100}), False)
    dug = [(t.x, t.y, t.z) for t in W.idx.values() if t.designated]
    for x, y, z in dug:
        Uw.dig_guard_reset()
        assert Uw.dig_forbidden(x, y, z) is None, (x, y, z)
    if r.ok:
        assert (r.column.x, r.column.y) != (41, 25), dict(r)
    else:
        assert not dug, dug


@path_test("the site check (check_site, every level's place): a site with a tile beside adamantine is refused, with why")
def _():
    lua, B, W, Dw, Uw = wayin_world()
    L = lua.eval("function() return {bounds = {x1 = 0, y1 = 0, x2 = 2, y2 = 0}, tiles = {[0] = {[0] = true}, "
                 "[1] = {[0] = true}, [2] = {[0] = true}}} end")()
    ok0, why0 = two(B.check_site(L, lua.table(), 10, 10, 15))
    Dw.set(13, 11, 15, lua.table_from({"vein": Dw.ADAM, "mat": "MINERAL"}))
    Uw.dig_guard_reset()
    ok, why = two(B.check_site(L, lua.table(), 10, 10, 15))
    assert ok0 and not ok and "next to raw adamantine" in why and "it guards the underworld" in why, (ok0, why0, why)


@path_test("joins and widenings (ai-joins): a corridor through adamantine's neighbours is not dug; noted; elsewhere as before")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    Dj = lua.execute(DEEP)
    M = lua.execute("local src, D = ...; local env = setmetatable({}, {__index = _G}); "
                    "assert(load(src, 'ai-joins', 't', env))(); env.dfhack, env.df = D.dfhack, D.df; return env",
                    module_src("ai-joins.lua"), Dj)
    two = ["##############################",
           "#.......########.......#######",
           "#.......########.......#######",
           "#.......########.......#######",
           "##############################"]

    def reader(z):
        def T_(x, y):
            if y < 0 or y >= len(two) or x < 0 or x >= len(two[y]):
                return None
            c = two[y][x]
            return lua.table_from({"open": c in ".r", "passage": c == ".", "rock": c == "#", "danger": False})
        return T_
    M.game_reader = reader
    projects = lua.eval("function() return {list = {{z = 10, phase = 'done', anchor = {x = 1, y = 1}},"
                        "{z = 10, phase = 'done', anchor = {x = 20, y = 2}}}} end")
    Uj = M.reqscript("ai-util")
    M.reqscript = lambda n, *a: lua.table_from({"load_projects": projects})
    r = M.join_levels(True)
    assert r.ok and r.joined and r.joined.length == 8, dict(r)
    M.JOIN_CURSOR = 0
    Dj.set(11, 2, 10, lua.table_from({"vein": Dj.ADAM, "mat": "MINERAL"}))
    Uj.dig_guard_reset()
    r = M.join_levels(False)
    assert r.ok and r.joined is None and r.widened is None, dict(r)
    assert "left alone: it guards the underworld" in (r.note or ""), dict(r)
    assert not any(t.dig == 1 for t in Dj.tiles.values()), "nothing designated"


def industry(rows, adam=(), level=False):
    lua = LuaRuntime(unpack_returned_tuples=True)
    fake = lua_const("test_industry.py", "FAKE")
    env, dig = lua.execute(fake, module_src("ai-industry.lua"), lua.table_from(rows))
    if level:          # (as test_industry's drift test) a level at x 1-5, y 1-4
        lua.execute("""local env = ...
          env.reqscript = function() return {
            citizen_positions = function() return {{x = 2, y = 2, z = 10}} end,
            load_projects = function() return {list = {{area = {x1 = 1, y1 = 1, x2 = 5, y2 = 4, z = 10}}}} end} end
        """, env)
    lua.execute("""local env, adam = ...
      local INORG = env.df.global.world.raws.inorganics.all
      INORG[7] = {id = 'RAW_ADAMANTINE', flags = {DEEP_SPECIAL = true}, metal_ore = {mat_index = {}}}
      local block = env.df.global.world.map.map_blocks[1]
      local cls = getmetatable(block.block_events[1]).__index._cls
      local m = {}
      for _, t in ipairs(adam) do m[t[1] .. ',' .. t[2]] = true end
      table.insert(block.block_events, setmetatable({inorganic_mat = 7, tile_bitmask = m}, {__index = {_cls = cls}}))
    """, env, lua.table_from({i + 1: lua.table_from({1: x, 2: y}) for i, (x, y) in enumerate(adam)}))
    return env, dig


@path_test("ore veins (mine_ore): a vein tile beside adamantine is never marked; a vein wholly beside it is refused")
def _():
    rows = lua_const("test_industry.py", "MAP")
    env, dig = industry(rows)
    r = env.mine("IRON", 40, True)
    assert r.ok and r.tiles == 7, dict(r)                                     # as test_industry, no adamantine
    env, dig = industry(rows, adam=[(10, 3)])          # beside the hidden hematite at x 9-10 of row 3
    r = env.mine("IRON", 40, False)
    assert r.ok and r.tiles < 7 and dig(9, 3) == 0 and dig(10, 3) == 0 and dig(6, 2) == 1, dict(r)
    env, dig = industry(rows, adam=[(7, 1)])           # beside row 2's vein: reached by a drift on row 3
    r = env.mine("IRON", 40, False)
    assert r.ok and all(dig(x, 2) == 0 for x in (6, 7, 8)) and dig(7, 3) == 1, dict(r)
    env, dig = industry(rows, adam=[(7, 1), (9, 4), (6, 4)])   # beside every tile of it: refused
    r = env.mine("IRON", 40, False)
    assert not r.ok and r.rejected, dict(r)
    assert not any(dig(x, y) for x in range(16) for y in range(16)), "nothing marked"


@path_test("drifts (mine_ore through rock): never through adamantine's neighbours")
def _():
    rows = ["################",
            "#.....##########",
            "#.....hh####??##",
            "#.....##########",
            "#.....##########"] + ["################"] * 11
    env, dig = industry(rows, level=True)
    r = env.mine("IRON", 40, True)
    assert r.ok and r.drift == 6, dict(r)                                     # as test_industry
    env, dig = industry(rows, adam=[(9, 1)], level=True)                     # over the drift's row
    r = env.mine("IRON", 40, False)
    assert not (r.ok and r.drift == 6), dict(r)
    assert all(dig(x, 2) == 0 for x in range(8, 11)), [dig(x, 2) for x in range(6, 14)]


@path_test("DFHack dig-now (the water works' plug): refused by adamantine, counted; elsewhere called as before")
def _():
    lua, B, W, Dw, Uw = wayin_world()
    Dw.set(42, 25, 27, lua.table_from({"vein": Dw.ADAM, "mat": "MINERAL"}))
    calls = lua.table()
    env = lua.execute("local src, B, calls = ...; local env = setmetatable({}, {__index = _G}); "
                      "assert(load(src, 'ai-waterworks', 't', env))(); "
                      "env.reqscript = function(n) if n == 'ai-builder' then return B end return B.util_module() end; "
                      "env.dfhack = {run_command_silent = function(...) table.insert(calls, {...}) end}; return env",
                      module_src("ai-waterworks.lua"), B, calls)
    ok, why = env.dig_now(41, 25, 27)
    assert ok is False and why == "next to raw adamantine" and Uw.DIG_GUARD.by.dig_now == 1, (ok, why)
    assert len(calls) == 0
    env.dig_now(45, 25, 27)
    assert Uw.DIG_GUARD.refused == 1 and len(calls) == 1 and calls[1][1] == "dig-now", len(calls)


# --- the source audit: every path that marks digging goes through the guard ----------------

def lua_files():
    return sorted(list(LUA_DIR.glob("*.lua")) + list((LUA_DIR / "gui").glob("*.lua")))


@test("audit: quickfort runs in dig mode only through ai-builder's quickfort_apply (guarded); nobody else calls "
      "apply_blueprint with dig")
def _():
    for p in lua_files():
        src = p.read_text(encoding="utf-8")
        for m in re.finditer(r"apply_blueprint\s*[({]", src):
            line = src[m.start():src.find("\n", m.start())]
            seg = src[m.start():m.start() + 300]
            if p.name == "ai-builder.lua":
                continue
            assert "mode = 'dig'" not in seg and 'mode = "dig"' not in seg, (p.name, line)
            assert re.search(r"mode = '(build|place|zone)'", seg), (p.name, line)
    b = (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8")
    fn = b[b.index("function quickfort_apply"):b.index("\nend\n", b.index("function quickfort_apply"))]
    assert "dig_guard_data" in fn and "mode == 'dig'" in fn


@test("audit: every dig flag the Lua sets (d.dig = Default) is behind the guard, or marks a plant (a shrub, a tree)")
def _():
    plants = {("ai-labor.lua", "shrubs"), ("ai-builder-surface.lua", "fell_tree")}
    for p in lua_files():
        src = p.read_text(encoding="utf-8")
        for m in re.finditer(r"\.dig\s*=\s*df\.tile_dig_designation\.(?!No\b)", src):
            head = src[:m.start()]
            fn = re.findall(r"function\s+([\w.:]+)\s*\(", head)
            name = fn[-1] if fn else "?"
            if (p.name, name) in plants:
                continue
            body = head[head.rfind("function " + name):]
            assert "dig_forbidden" in body or "dig_check_tiles" in body, (p.name, name)


@test("audit: dig-now is behind the guard (the cistern's plug, the water works' dig_now)")
def _():
    for p in lua_files():
        src = p.read_text(encoding="utf-8")
        for m in re.finditer(r"'dig-now'", src):
            if src.rfind("\n", 0, m.start()) > src.rfind("--", 0, m.start()):
                head = src[max(0, m.start() - 1500):m.start()]
                assert "dig_forbidden" in head or "dig_check_tiles" in head, (p.name, src[m.start() - 80:m.start()])


@test("audit: ore veins, drifts and quarries ask the guard (safe() and before marking); joins and widenings too")
def _():
    ind = (LUA_DIR / "ai-industry.lua").read_text(encoding="utf-8")
    safe = ind[ind.index("local function safe("):ind.index("\nend\n", ind.index("local function safe("))]
    assert "U.dig_forbidden" in safe
    assert ind.count("U.dig_check_tiles(marked") == 2
    j = (LUA_DIR / "ai-joins.lua").read_text(encoding="utf-8")
    assert j.count("U.dig_check_tiles(") == 2 and "U.dig_forbidden(p.x, p.y, z)" in j
    s = (LUA_DIR / "ai-builder-sites.lua").read_text(encoding="utf-8")
    assert "dig_forbidden(ax + x, ay + y, z)" in s


# --- 3. the report and the Rules switch ----------------------------------------------------

@test("report: the deep section carries deep_hazard (ai-bridge SECTIONS), with the Rules switch read")
def _():
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    i = src.index("    deep = function()")
    seg = src[i:src.index("end) end,", i)]
    assert "deep_hazard_section()" in seg and "get_deep()" in seg
    assert "function deep_hazard_section()" in src and "mine_adamantine" in src


@test("Rules: mine_adamantine is an on/off switch, off by default, kept by sanitize and for_ai; set_rules takes it")
def _():
    if LuaRuntime is None:
        return
    import test_preset as TP      # the bridge and the settings with a stub DFHack
    TP.reset()
    S = TP.H.settings()
    d = S.defaults()
    assert d.mine_adamantine is False and S.for_ai(d).mine_adamantine is False
    assert S.sanitize(TP.t({"mine_adamantine": True})).mine_adamantine is True
    assert S.for_ai(S.sanitize(TP.t({"mine_adamantine": True}))).mine_adamantine is True
    assert S.sanitize(TP.t({"mine_adamantine": "yes"})).mine_adamantine is False
    r = TP.act({"type": "set_rules", "rules": {"mine_adamantine": True}})
    assert r.ok and TP.saved().mine_adamantine is True, dict(r)
    TP.reset()


# --- 4. the brain ----------------------------------------------------------------------------

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def hazard(**kw):
    h = {"adamantine_seen": False, "tiles": 0, "spire_seen": False, "underworld_seen": False, "refused": 0}
    h.update(kw)
    return h


def state(h=None, **settings):
    s = copy.deepcopy(BASE)
    if h is not None:
        s.setdefault("deep", {})
        if not isinstance(s["deep"], dict):
            s["deep"] = {}
        s["deep"]["deep_hazard"] = h
    s["settings"].update(settings)
    s.setdefault("map", {})["elevation_offset"] = -100
    return s


@test("brain: a mine_ore of adamantine is never proposed (by metal or by ore); the note says why")
def _():
    s = state(hazard())
    s["industry"] = {"ores": {"ADAMANTINE": {"tiles": 9, "ore": "RAW_ADAMANTINE"}, "IRON": {"tiles": 4, "ore": "HEMATITE"},
                              "WEIRD": {"tiles": 2, "ore": "RAW_ADAMANTINE"}}}
    props = [Proposal("ore", {"type": "mine_ore", "metal": "ADAMANTINE", "count": 40}, "x", 5),
             Proposal("ore", {"type": "mine_ore", "metal": "WEIRD", "count": 40}, "x", 5),
             Proposal("ore", {"type": "mine_ore", "metal": "IRON", "count": 40}, "x", 5)]
    notes = []
    PD._deep_hazard_rule(s, props, notes)
    assert [p.action["metal"] for p in props] == ["IRON"], props
    assert len(notes) == 1 and notes[0].startswith(PD.LEFT_ALONE) and "no vein of it is mined" in notes[0], notes


@test("brain: adamantine seen or a dig refused: 'adamantine: left alone: it guards the underworld', with where")
def _():
    notes = []
    PD._deep_hazard_rule(state(hazard(adamantine_seen=True, tiles=12, nearest_z=40, refused=3,
                                      refused_last={"why": "next to raw adamantine"})), [], notes)
    assert len(notes) == 1, notes
    n = notes[0]
    assert n.startswith("adamantine: left alone: it guards the underworld") and "12 tile(s)" in n, n
    assert "elevation -60" in n and "refused 3" in n and "next to raw adamantine" in n, n
    line = PD.deep_hazard_line(state(hazard(adamantine_seen=True, tiles=12, nearest_z=40, refused=3,
                                            refused_by={"quickfort": 2, "join": 1})))
    assert line.startswith("DEEP_HAZARD adamantine seen (12 tiles, nearest at elevation -60)"), line
    assert "dig guard refused 3 (join:1 quickfort:2)" in line and line.endswith(PD.LEFT_ALONE), line
    assert "DEEP_HAZARD" in digest(state(hazard(adamantine_seen=True, tiles=1, nearest_z=40)))


@test("brain: the Rules switch mine_adamantine on: still left alone, the note says the plan isn't built yet")
def _():
    notes = []
    PD._deep_hazard_rule(state(hazard(mine_adamantine=True), mine_adamantine=True), [], notes)
    assert len(notes) == 1 and "not built yet" in notes[0] and "still left alone" in notes[0], notes
    props = [Proposal("ore", {"type": "mine_ore", "metal": "ADAMANTINE", "count": 40}, "x", 5)]
    PD._deep_hazard_rule(state(hazard(), mine_adamantine=True), props, [])
    assert props == []
    assert "not built yet" in PD.deep_hazard_line(state(hazard(mine_adamantine=True)))


@test("brain: nothing seen, nothing refused, switch off: no note, no line, proposals untouched")
def _():
    for s in (state(None), state(hazard())):
        props = [Proposal("ore", {"type": "mine_ore", "metal": "IRON", "count": 40}, "x", 5)]
        notes = []
        PD._deep_hazard_rule(s, props, notes)
        assert len(props) == 1 and notes == [] and PD.deep_hazard_line(s) == "", notes
        assert "DEEP_HAZARD" not in digest(s)
    s = state(None)
    s["deep"] = {"error": "boom"}
    notes = []
    PD._deep_hazard_rule(s, [], notes)
    assert notes == []


@test("brain: the rule is registered in plan() (after the industry rules)")
def _():
    src = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")
    assert "from planner_deep import _deep_hazard_rule" in src
    i, j = src.index("_guard(_industry_rules"), src.index("_guard(_deep_hazard_rule, s, proposals, notes)")
    assert i < j


PROBE = r'''
import copy, json, sys
from pathlib import Path
brain = Path(sys.argv[1]); sys.path.insert(0, str(brain))
fixtures = Path(sys.argv[2]); with_hazard = sys.argv[3] == "1"
from digest import normalize, digest
from planner import Memory, plan, record, select, note_cycle, TICKS_PER_DAY
from planner import PLANNER_CONFIG as _PC
_PC.update({"survival_floor": 0, "mandate_shields": False, "mandates_low_deference": False})  # (item5) its floor and mandate changes off: main's behaviour compared
out = {}
for path in [fixtures / "test_fort.json"] + sorted((fixtures / "real").glob("*.json")):
    base = json.loads(path.read_text(encoding="utf-8"))
    if with_hazard and isinstance(base.get("deep"), dict):
        base["deep"]["deep_hazard"] = {"adamantine_seen": False, "tiles": 0, "spire_seen": False,
                                       "underworld_seen": False, "refused": 0}
    s = normalize(copy.deepcopy(base))
    m = Memory()
    cycles = []
    for _ in range(2):
        n = note_cycle(copy.deepcopy(s), m)
        props, notes = plan(copy.deepcopy(s), m)
        cycles.append({"props": [[p.rule, json.dumps(p.action, sort_keys=True, default=str), p.reason,
                                  p.priority] for p in props], "notes": notes, "cycle": n,
                       "digest": digest(copy.deepcopy(s))})
        allowed, _ = select(props, s, m)
        record([(p, {"ok": False, "error": "refused (test)"}) for p in allowed], s, m)
        s["date"]["tick"] = s["date"].get("tick", 0) + TICKS_PER_DAY
    out[path.name] = cycles
print(json.dumps(out, sort_keys=True))
'''

_MAIN = {}


def main_brain():
    if "dir" not in _MAIN:
        tmp = tempfile.mkdtemp(prefix="r41-main-")
        arch = subprocess.run(["git", "-C", str(ROOT), "archive", "main", "brain"], capture_output=True)
        if arch.returncode != 0:
            _MAIN["dir"] = None
        else:
            subprocess.run(["tar", "-x", "-C", tmp], input=arch.stdout, check=True)
            _MAIN["dir"] = Path(tmp) / "brain"
            atexit.register(shutil.rmtree, tmp, True)
    return _MAIN["dir"]


def probe(brain: Path, with_hazard: bool) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "probe.py"
        p.write_text(PROBE, encoding="utf-8")
        r = subprocess.run([sys.executable, "-I", str(p), str(brain), str(ROOT / "tests" / "fixtures"),
                            "1" if with_hazard else "0"],
                           capture_output=True, text=True, env=dict(os.environ, DFAI_LOG_DIR=tmp), cwd=tmp)
    assert r.returncode == 0, r.stderr[-1500:]
    return r.stdout.strip().splitlines()[-1]


@test("identity: on every fixture (no adamantine), plan(), note_cycle() and the digest are main's, with or "
      "without an empty deep_hazard")
def _():
    main = main_brain()
    assert main is not None, "no main branch to compare with"
    a = probe(main, False)
    for with_hazard in (False, True):
        b = probe(ROOT / "brain", with_hazard)
        if a != b:
            ja, jb = json.loads(a), json.loads(b)
            bad = [k for k in ja if ja[k] != jb.get(k)]
            raise AssertionError(f"differs from main at {bad[:3]} (deep_hazard {with_hazard})")


if LuaRuntime is None:
    finish("these tests need the lupa package (pip install lupa)")
finish()
