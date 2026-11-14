"""(0.105.46, I6) Speed and disk.

  * lua/ai-slices.lua: a walk spread over several reports sees every item
    once a pass, sends the last whole result meanwhile, starts afresh on an
    invalidation or another key, keeps a result for its ttl;
  * lua/ai-industry.lua survey: the vein walk sliced over reports (the
    section not kept by the bridge while a pass is under way), the same ores
    as the whole walk, each ore event's tiles listed once per map, the
    boulders walked once;
  * lua/ai-util.lua deep_hazard: only the blocks the deep map listed, sliced,
    the underworld not read again once seen;
  * lua/ai-cavern-scan.lua: the caverns' seen samples kept, the hidden ones
    read in slices (and round the citizens every report), the same seen and
    open as the old walk (get_deep on test_r40_sections' fake world);
  * brain/backup.py retention by age; brain/old_saves.py's one Needs you line.

    python tests/test_i6_speed.py
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))
from lua_modules_util import module_src, UTIL_SRC  # noqa: E402

import backup  # noqa: E402
import old_saves  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:  # pragma: no cover
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
SLICES_SRC = (LUA_DIR / "ai-slices.lua").read_text(encoding="utf-8")
SCAN_SRC = (LUA_DIR / "ai-cavern-scan.lua").read_text(encoding="utf-8")


def lua_const(test_file: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / test_file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return eval(compile(ast.Expression(node.value), test_file, "eval"), {"__builtins__": {}})
    raise KeyError(name)


def lua_test(name):
    def deco(fn):
        def run():
            if LuaRuntime is None:
                print("  (no lupa: skipped)")
                return
            fn()
        return test(name)(run)
    return deco


def slices_env(lua):
    return lua.execute("local src = ...; local env = setmetatable({}, {__index = _G}); "
                       "assert(load(src, 'ai-slices', 't', env))(); return env", SLICES_SRC)


# --- the slicer ------------------------------------------------------------------------------------

SPEC = r"""
local S, n, max_items, whole_first = ...
local seen = {}
local spec = {key = 'k', now = 0, ttl = nil, whole_first = whole_first, max_items = max_items, max_ms = 1e9,
              items = function() local l = {}; for i = 1, n do l[i] = i end; return l end,
              init = function() return {sum = 0, count = 0} end,
              visit = function(acc, i) seen[i] = (seen[i] or 0) + 1; acc.sum = acc.sum + i; acc.count = acc.count + 1 end,
              finish = function(acc) return {sum = acc.sum, count = acc.count} end}
return spec, seen
"""


@lua_test("slicer: a walk of 23 items 5 a call sees every item exactly once over 5 calls; the result only when whole")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    S = slices_env(lua)
    spec, seen = lua.execute(SPEC, S, 23, 5, False)
    out = []
    for _ in range(5):
        r, st, done, total = S.run("w", spec)
        out.append((st, done, total, r))
    assert [o[0] for o in out] == ["partial"] * 4 + ["done"], out
    assert [o[1] for o in out] == [5, 10, 15, 20, 23] and all(o[2] == 23 for o in out), out
    assert all(o[3] is None for o in out[:4])                     # no whole pass yet: nothing to send
    assert out[4][3].sum == sum(range(1, 24)) and out[4][3].count == 23
    assert sorted(seen.keys()) == list(range(1, 24)) and set(seen.values()) == {1}, dict(seen)
    # ttl nil: kept until invalidated
    r, st, _, _ = S.run("w", spec)
    assert st == "cached" and r.sum == 276
    # invalidated: the next pass starts; the last whole result is sent meanwhile
    S.invalidate("w")
    r, st, done, _ = S.run("w", spec)
    assert st == "partial" and r.sum == 276 and done == 5
    S.invalidate("w")                                              # mid-pass: the pass starts over
    r, st, done, _ = S.run("w", spec)
    assert st == "partial" and done == 5, done
    for _ in range(4):
        r, st, _, _ = S.run("w", spec)
    assert st == "done" and r.count == 23
    assert S.status("w").passes == 2


@lua_test("slicer: whole_first walks the first pass at once; another key starts afresh; ttl 0 a new pass each time; "
          "a ttl keeps the result that long; a throw in one item is counted and the walk goes on")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    S = slices_env(lua)
    spec, seen = lua.execute(SPEC, S, 23, 5, True)
    r, st, done, total = S.run("w", spec)
    assert st == "done" and r.count == 23 and done == total == 23
    # the next pass is sliced
    spec.ttl = 0
    r, st, done, _ = S.run("w", spec)
    assert st == "partial" and done == 5 and r.count == 23
    # another key: afresh (whole again: no result for it yet)
    spec.key = "other"
    r, st, _, _ = S.run("w", spec)
    assert st == "done" and r.count == 23 and S.status("w").key == "other" and S.status("w").passes == 1
    # a ttl of 100 ticks
    spec.ttl = 100
    spec.now = 50
    assert S.run("w", spec)[1] == "cached"
    spec.now = 120
    assert S.run("w", spec)[1] == "partial"
    # a throw
    S.reset()
    spec2, _ = lua.execute(SPEC, S, 6, 100, False)
    spec2.visit = lua.eval("function(acc, i) if i == 3 then error('boom') end acc.count = acc.count + 1 end")
    r, st, _, _ = S.run("e", spec2)
    assert st == "done" and r.count == 5


# --- industry ---------------------------------------------------------------------------------------

IND_FAKE = r"""
local src, SL = ...
local W = {assign = 0, tiletype = 0, getblock = 0, dug = {}, hidden = {}}
local MINERAL = {}
local blocks = {}
-- blocks bx 0..2, by 0..2 at z 10..12; hematite (1, iron) in a 4x4 patch of every block on z 11,
-- malachite (2, copper) in a 3x3 patch of the blocks with bx == 1
local function patch(x0, y0, n)
    local m = {}
    for x = x0, x0 + n - 1 do for y = y0, y0 + n - 1 do m[x * 16 + y] = true end end
    return m
end
for z = 10, 12 do
    for bx = 0, 2 do
        for by = 0, 2 do
            local b = {map_pos = {x = bx * 16, y = by * 16, z = z}, block_events = {}, designation = {}}
            if z == 11 then
                table.insert(b.block_events, {_cls = MINERAL, inorganic_mat = 1, tile_bitmask = patch(2, 2, 4)})
                if bx == 1 then table.insert(b.block_events, {_cls = MINERAL, inorganic_mat = 2, tile_bitmask = patch(9, 9, 3)}) end
            end
            for x = 0, 15 do
                b.designation[x] = setmetatable({}, {__index = function(_, y)
                    return {hidden = W.hidden[(bx * 16 + x) .. ',' .. (by * 16 + y) .. ',' .. z] == true} end})
            end
            blocks[bx .. ',' .. by .. ',' .. z] = b
        end
    end
end
local INORG = {[1] = {id = 'HEMATITE', metal_ore = {mat_index = {100}}},
               [2] = {id = 'MALACHITE', metal_ore = {mat_index = {101}}},
               [100] = {id = 'IRON', metal_ore = {mat_index = {}}},
               [101] = {id = 'COPPER', metal_ore = {mat_index = {}}}}
local env = setmetatable({}, {__index = _G})
env.df = {
    global = {cur_year = 200, cur_year_tick = 5000,
              world = {map = {map_blocks = {}, region_x = 1, region_y = 2, region_z = 3, x_count = 48, y_count = 48, z_count = 20},
                       raws = {inorganics = {all = INORG}}, items = {other = {BOULDER = {}}}}},
    tiletype = {attrs = {[1] = {shape = 1}, [2] = {shape = 2}}},
    tiletype_shape = {[1] = 'WALL', [2] = 'FLOOR'},
    block_square_event_mineralst = {is_instance = function(_, ev) return ev._cls == MINERAL end},
}
env.dfhack = {maps = {
    getBlock = function(bx, by, z) W.getblock = W.getblock + 1; return blocks[bx .. ',' .. by .. ',' .. z] end,
    getTileAssignment = function(m, x, y) W.assign = W.assign + 1; return m[x * 16 + y] == true end,
    getTileType = function(x, y, z) W.tiletype = W.tiletype + 1; return W.dug[x .. ',' .. y .. ',' .. z] and 2 or 1 end,
}}
local B = {citizen_positions = function() return {{x = 24, y = 24, z = 12}} end}
env.reqscript = function(name)
    if name == 'ai-builder' then return B end
    if name == 'ai-slices' and W.use_slices then return SL end
    error('no ' .. name)
end
assert(load(src, 'ai-industry', 't', env))()
env.W = W
return env
"""


def industry(lua, slices=True):
    SL = slices_env(lua)
    env = lua.execute(IND_FAKE, module_src("ai-industry.lua"), SL)
    env.W.use_slices = slices
    return env, SL


def ores(v):
    return {k: (v[k].tiles, v[k].ore) for k in v.keys()}


@lua_test("industry: the sliced vein walk gives the whole walk's ores; while a pass is under way the last whole "
          "result is sent with true (not kept); each ore event's tiles listed once per map")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    whole, _ = industry(lua, slices=False)
    w = whole.survey()
    assert ores(w.ores) == {"IRON": (9 * 16, "HEMATITE"), "COPPER": (3 * 9, "MALACHITE")}, ores(w.ores)
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, SL = industry(lua)
    env.SLICE_MS = 1e9
    env.SLICE_ITEMS = 7
    first = env.survey()
    assert not isinstance(first, tuple), first                    # the first pass whole: kept by the bridge
    assert ores(first.ores) == ores(w.ores) and first.sliced is None
    assign_first = env.W.assign
    assert assign_first > 0
    # the dwarves uncover nothing new, dig two hematite tiles; hide one malachite tile
    env.W.dug["2,2,11"] = True
    env.W.dug["3,2,11"] = True
    env.W.hidden["25,25,11"] = True
    n_blocks = len(list(env.area_blocks(lua.table_from({"x1": -16, "y1": -16, "x2": 64, "y2": 64, "z1": 0, "z2": 14})).values()))
    calls, last = 0, None
    while True:
        calls += 1
        r = env.survey()
        if isinstance(r, tuple):
            v, nocache = r
            assert nocache is True and ores(v.ores) == ores(w.ores) and v.sliced.done < v.sliced.total, ores(v.ores)
        else:
            last = r
            break
        assert calls < 100
    assert calls == -(-n_blocks // 7), (calls, n_blocks)
    assert ores(last.ores) == {"IRON": (9 * 16 - 2, "HEMATITE"), "COPPER": (3 * 9 - 1, "MALACHITE")}, ores(last.ores)
    assert env.W.assign == assign_first, "the event tiles were asked for again"
    # the work, counted (fake DF calls): the old walk asked 256 masks per event each rebuild
    old_assign = 256 * (9 + 3)
    print(f"  (work: mask asks per rebuild {old_assign} before, 0 after the first; "
          f"{n_blocks} area blocks in {calls} slices of 7)")


@lua_test("industry: the boulders walked once for ore and flux (once a report)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, _ = industry(lua)
    walks = lua.execute(r"""
        local env = ...
        local n = {0}
        local function boulder(idx) return {flags = {}, getMaterial = function() return 0 end,
                                            getMaterialIndex = function() n[1] = n[1] + 1; return idx end} end
        env.df.global.world.items.other.BOULDER = {boulder(1), boulder(1), boulder(2), boulder(5)}
        env.df.global.world.raws.inorganics.all[5] = {id = 'LIMESTONE', metal_ore = {mat_index = {}},
                                                       material = {reaction_class = {'FLUX'}}}
        return n
    """, env)
    s = env.survey()
    assert s.ore_stock == 3 and s.flux_stock == 1 and s.ore_stock_by.HEMATITE.n == 2, (s.ore_stock, s.flux_stock)
    assert walks[1] == 4, walks[1]                                # one read per boulder (was two walks)


# --- the bridge keeps no copy of a section under way ---------------------------------------------

def _harness_src() -> str:
    tree = ast.parse((ROOT / "tests" / "test_bridge_memory.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "HARNESS" for t in node.targets):
            return node.value.value
    raise AssertionError("no HARNESS")


@lua_test("bridge: the industry section returns the survey's true (a pass under way): no copy kept, built again "
          "next report; a whole one kept for its days")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    H = lua.execute(_harness_src(), (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8"), str(LUA_DIR))
    M = H.module()
    M.get_dwarves = lua.eval("function(inc) return {total = 7}, nil end")
    state = lua.eval("{n = 0, partial = 2}")
    H.scripts = lua.table_from({"ai-industry": lua.eval("""function(state) return {survey = function()
        state.n = state.n + 1
        if state.n <= state.partial then return {ores = {}, n = state.n}, true end
        return {ores = {}, n = state.n} end} end""")(state)})
    real = M.SECTIONS.industry
    M.SECTIONS = lua.table_from({"industry": real})
    M.SECTION_CACHE = lua.table()
    assert M.build_state(False).industry.n == 1 and M.SECTION_CACHE.industry is None
    assert M.build_state(False).industry.n == 2 and M.SECTION_CACHE.industry is None
    assert M.build_state(False).industry.n == 3 and M.SECTION_CACHE.industry.value.n == 3
    assert M.build_state(False).industry.n == 3 and state.n == 3            # the copy, 7 days
    # a throw: an error section, as safe() gives
    H.scripts["ai-industry"] = lua.eval("{survey = function() error('boom') end}")
    M.SECTION_CACHE = lua.table()
    assert "boom" in str(M.build_state(False).industry.error)


# --- deep_hazard -------------------------------------------------------------------------------------

DEEP = lua_const("test_r41_dig_guard.py", "DEEP")


def deep_world(with_slices=True):
    lua = LuaRuntime(unpack_returned_tuples=True)
    D = lua.execute(DEEP)
    SL = slices_env(lua)
    U = lua.execute("local src, D, SL, on = ...; local env = setmetatable({df = D.df, dfhack = D.dfhack}, "
                    "{__index = _G}); env.reqscript = function(n) if n == 'ai-slices' and on then return SL end "
                    "error('no ' .. n) end; assert(load(src, 'ai-util', 't', env))(); return env",
                    UTIL_SRC, D, SL, with_slices)
    D.reset()
    U.dig_guard_unload()
    U.dig_guard_reset()
    return lua, D, U, SL


def T(lua, d):
    return lua.table_from(d)


@lua_test("deep_hazard: only the deep map's listed blocks; sliced over reports a day apart (the last whole pass sent "
          "meanwhile), every listed block read once a pass; the same count as the whole walk")
def _():
    lua, D, U, SL = deep_world()
    D.global_types[2] = D.FT.subterranean_from_layer
    for z in (10, 11, 12):
        D.feat(3, 3, z, T(lua, {"gf": 2}))                    # the lowest cavern: the floor at 12
    spots = [(20 + 16 * i, 20, 5 + i) for i in range(6)]       # adamantine in 6 blocks below the floor
    for x, y, z in spots:
        D.set(x, y, z, T(lua, {"vein": D.ADAM, "mat": "MINERAL", "hidden": True}))
    D.set(spots[0][0], spots[0][1], spots[0][2], T(lua, {"hidden": False}))
    h = U.deep_hazard(None, False)
    assert h.tiles == 1 and U.DEEP_HAZARD_CACHE.walked == 6, (h.tiles, U.DEEP_HAZARD_CACHE.walked)
    assert len(list(U.deep_map().hz.values())) == 6
    for x, y, z in spots:                                      # all six seen now
        D.set(x, y, z, T(lua, {"hidden": False}))
    U.HAZARD_SLICE_MS = 1e9
    U.HAZARD_SLICE_ITEMS = 2
    D.df["global"].cur_year_tick = 1000 + 1200                 # a day later
    D.calls = 0
    seen = []
    for _ in range(3):
        seen.append(U.deep_hazard(None, False).tiles)
    assert seen == [1, 1, 6], seen                             # 2 + 2 + 2 blocks
    assert U.DEEP_HAZARD_CACHE.walked == 6
    assert U.deep_hazard(None, False).tiles == 6               # the same day: kept
    # the whole walk (no slicer) says the same
    lua2, D2, U2, _ = deep_world(with_slices=False)
    D2.global_types[2] = D2.FT.subterranean_from_layer
    for z in (10, 11, 12):
        D2.feat(3, 3, z, T(lua2, {"gf": 2}))
    for x, y, z in spots:
        D2.set(x, y, z, T(lua2, {"vein": D2.ADAM, "mat": "MINERAL"}))
    assert U2.deep_hazard(None, False).tiles == 6


@lua_test("deep_hazard: the underworld once seen isn't read again on this map; still said seen")
def _():
    lua, D, U, SL = deep_world()
    D.global_types[2] = D.FT.subterranean_from_layer
    D.feat(3, 3, 12, T(lua, {"gf": 2}))
    D.global_types[9] = D.FT.underworld_from_layer
    for bx in range(4):
        D.feat(bx, 0, 2, T(lua, {"gf": 9}))
    h = U.deep_hazard(None, False)
    assert h.underworld_seen is True and U.DEEP_HAZARD_CACHE.walked >= 1
    D.df["global"].cur_year_tick = 1000 + 2400
    h = U.deep_hazard(None, False)
    assert h.underworld_seen is True and U.DEEP_HAZARD_CACHE.walked == 0, U.DEEP_HAZARD_CACHE.walked


# --- the caverns' scan -------------------------------------------------------------------------------

SCAN_FAKE = r"""
local src, SL = ...
local W = {hidden = {}, group = {}, getblock = 0}
local env = setmetatable({}, {__index = _G})
local function key(x, y, z) return x .. ',' .. y .. ',' .. z end
env.dfhack = {maps = {
    getTileBlock = function(x, y, z)
        W.getblock = W.getblock + 1
        local bx, by = x // 16 * 16, y // 16 * 16
        local des = {}
        for lx = 0, 15 do
            des[lx] = setmetatable({}, {__index = function(_, ly)
                local k = key(bx + lx, by + ly, z)
                return {hidden = W.hidden[k] ~= false} end})
        end
        return {designation = des, map_pos = {x = bx, y = by, z = z}}
    end,
    getWalkableGroup = function(p) return W.group[key(p.x, p.y, p.z)] or 0 end,
}}
env.reqscript = function(n) if n == 'ai-slices' and SL then return SL end error('no ' .. n) end
assert(load(src, 'ai-cavern-scan', 't', env))()
env.W = W
return env
"""


def scan_world(lua, with_slices=True):
    SL = slices_env(lua) if with_slices else None
    return lua.execute(SCAN_FAKE, SCAN_SRC, SL)


@lua_test("cavern scan: seen samples kept; a sample far from the citizens is found within one sliced pass, one "
          "under them the next report; open once a seen sample's walk group is the citizens'")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    C = scan_world(lua)
    C.SCAN_MS = 1e9
    C.SCAN_ITEMS = 5
    blocks = [[bx * 16, by * 16, z] for z in (40, 41) for bx in range(5) for by in range(4)]   # 40 blocks
    rows = lua.table_from([lua.table_from({"name": "Cavern 1", "blocks": lua.table_from(
        [lua.table_from(b) for b in blocks])})])
    groups = lua.table_from({1: True})
    cit = lua.table_from([lua.table_from({"x": 8, "y": 8, "z": 60})])
    C.W.hidden["21,21,40"] = False                             # one seen sample (block 1,1)
    out, _ = C.scan(rows, groups, cit, "map", 0)
    assert out["Cavern 1"].seen == 1 and out["Cavern 1"].open is False
    assert C.W.getblock == 8 + 40                              # the 8 round the citizens, then the first pass whole
    # a far one (block 4,3 at z 41) uncovered: found within ceil(39/5) + 1 reports, not the next one
    C.W.hidden["74,53,41"] = False
    n = 0
    while True:
        n += 1
        out, _ = C.scan(rows, groups, cit, "map", n)
        if out["Cavern 1"].seen == 2:
            break
        assert n < 20
    assert 1 < n <= -(-40 // 5) + 1, n
    # one under the citizens (block 0,0): the next report
    C.W.hidden["5,5,41"] = False
    out, _ = C.scan(rows, groups, cit, "map", 100)
    assert out["Cavern 1"].seen == 3, out["Cavern 1"].seen
    # the fort's ground meets a seen sample: open, at it
    C.W.group["74,53,41"] = 1
    out, _ = C.scan(rows, groups, cit, "map", 101)
    o = out["Cavern 1"]
    assert o.open is True and (o.open_at.x, o.open_at.y, o.open_at.z) == (74, 53, 41)
    # a block whose 16 samples are all seen is never read again
    for sx in range(4):
        for sy in range(4):
            C.W.hidden[f"{sx * 5},{sy * 5},40"] = False
    C.scan(rows, groups, cit, "map", 102)
    assert C.CAVERN_SCAN.caverns["Cavern 1"].mask[1] == 0xFFFF


@lua_test("cavern scan: a sliced pass reads every hidden block once across its reports (completeness)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    C = scan_world(lua)
    C.SCAN_MS = 1e9
    C.SCAN_ITEMS = 7
    C.NEAR_MAX = 0
    blocks = [[bx * 16, by * 16, 40] for bx in range(6) for by in range(5)]   # 30 blocks
    rows = lua.table_from([lua.table_from({"name": "C", "blocks": lua.table_from([lua.table_from(b) for b in blocks])})])
    g, cit = lua.table_from({}), lua.table_from([])
    C.scan(rows, g, cit, "m", 0)                              # whole
    read = lua.execute(r"""
        local C = ...
        local real = C.scan_block
        local n = {}
        C.scan_block = function(c, i) n[i] = (n[i] or 0) + 1; return real(c, i) end
        return n
    """, C)
    # scan_block is called through the module's global: count a whole pass of 30 in slices of 7
    for r in range(1, 6):
        C.scan(rows, g, cit, "m", r)
    counts = dict(read)
    assert sorted(counts) == list(range(1, 31)) and set(counts.values()) == {1}, counts


SECTIONS_FAKE = lua_const("test_r40_sections.py", "FAKE")

HUB = r"""
local base, report_src, util, scan, slices = ...
local env = setmetatable({BRIDGE_VERSION = 'test', txt = tostring,
                          abs_tick = function() return 120 * 403200 + 5000 end,
                          qerror = error}, {__index = base})
env.require = function(n) if n == 'utils' then return {listpairs = function() return function() end end} end error(n) end
local mods = {}
env.reqscript = function(n)
    if n == 'ai-util' and util then return util end
    if mods[n] then return mods[n] end
    error('no ' .. n)
end
if scan then
    local s = setmetatable({}, {__index = base})
    s.reqscript = env.reqscript
    mods['ai-slices'] = slices
    assert(load(scan, 'ai-cavern-scan', 't', s))()
    mods['ai-cavern-scan'] = s
end
assert(load(report_src, 'ai-bridge-report', 't', env))()
return env
"""


def deep_rows(v):
    return {str(c.name): (c.seen > 0, bool(c.open), c.discovered) for c in v.caverns.values()}


@lua_test("get_deep: with the cavern scan the caverns' open is the old walk's (test_r40_sections' world); seen is "
          "every seen sample (the old walk stopped counting at the first open one); the second report reads fewer blocks")
def _():
    src = (LUA_DIR / "ai-bridge-report.lua").read_text(encoding="utf-8")
    lua = LuaRuntime(unpack_returned_tuples=True)
    base = lua.execute(SECTIONS_FAKE)()
    old_env = lua.execute(HUB, base, src, None, None, None)
    o = old_env.get_deep()
    want = deep_rows(o)
    assert want and any(v[0] > 0 for v in want.values()), want
    lua2 = LuaRuntime(unpack_returned_tuples=True)
    base2 = lua2.execute(SECTIONS_FAKE)()
    SL = slices_env(lua2)
    new_env = lua2.execute(HUB, base2, src, None, SCAN_SRC, SL)
    new_env.reqscript("ai-cavern-scan").SCAN_ITEMS = 5          # (the fake's blocks fit one 30 ms slice)
    n1 = new_env.get_deep()
    assert deep_rows(n1) == want, (deep_rows(n1), want)
    old_seen = {str(c.name): c.seen for c in o.caverns.values()}
    for c in n1.caverns.values():
        assert c.seen >= old_seen[str(c.name)], (c.name, c.seen, old_seen)
    for c in n1.caverns.values():
        if c.open:
            assert c.open_at is not None
    g1 = base2.C.getblock
    n2 = new_env.get_deep()
    assert deep_rows(n2) == want
    g2 = base2.C.getblock - g1
    assert g2 < g1, (g1, g2)
    print(f"  (work: blocks read {g1} the first report, {g2} the next)")


# --- backups -----------------------------------------------------------------------------------------

def _copies(tmp: Path, days_ago: list[float], now: float) -> list[Path]:
    out = []
    for d in days_ago:
        c = tmp / datetime.fromtimestamp(now - d * 86400).strftime("%Y-%m-%d %H%M")
        c.mkdir(parents=True, exist_ok=True)
        out.append(c)
    return out


@test("backup retention: a copy a day for 60 days keeps the newest, one a day for the last 7 days and one a week "
      "for 5 weeks; nothing older")
def _():
    now = datetime(2026, 11, 14, 12, 0).timestamp()
    with tempfile.TemporaryDirectory() as t:
        copies = _copies(Path(t), [i + 0.01 for i in range(60)], now)
        keep = backup.choose_keep(copies, now)
        ages = sorted(round((now - backup.copy_time(c)) / 86400, 1) for c in keep)
        assert keep[0] == copies[0], keep[0]                         # the newest first
        assert len([a for a in ages if a < 7]) == 7, ages
        weeks = {int(a // 7) for a in ages}
        assert weeks == {0, 1, 2, 3, 4}, ages
        assert max(ages) < 35 and len(keep) == 11, ages
        # two copies the same day: the newer of them
        c2 = _copies(Path(t), [0.2, 0.3], now)
        keep2 = backup.choose_keep(c2, now)
        assert keep2 == [c2[0]] or (len(keep2) == 2 and backup.copy_time(c2[0]) // 86400 != backup.copy_time(c2[1]) // 86400)
        # an old lone copy: the newest always stays
        c3 = _copies(Path(t) / "x", [90], now)
        assert backup.choose_keep(c3, now) == c3
        # past the size cap: the oldest kept go, never the newest
        sizes = {c: 100 for c in copies}
        keep4 = backup.choose_keep(copies, now, sizes, 350)
        assert len(keep4) == 3 and keep4[0] == copies[0], keep4
        assert backup.choose_keep(copies[:1], now, {copies[0]: 10 ** 9}, 1) == copies[:1]


@test("backup prune: the fort's copies in every folder thinned by age; another fort's and the game's saves untouched")
def _():
    orig = backup.BACKUP_DIR
    with tempfile.TemporaryDirectory() as t:
        backup.BACKUP_DIR = Path(t) / "backups"
        try:
            now = time.time()
            a = _copies(backup.BACKUP_DIR / "autosave 1", [0.5, 1.5, 2.5, 20.2, 20.6], now)
            b = _copies(backup.BACKUP_DIR / "region1", [3.5, 21.1, 50], now)
            other = _copies(backup.BACKUP_DIR / "autosave 1", [40, 41], now - 3600)   # another world's
            for c in a + b:
                backup.fort_mark_path(c).write_text(json.dumps({"world": "W", "site": "7"}))
            for c in other:
                backup.fort_mark_path(c).write_text(json.dumps({"world": "X", "site": "7"}))
            code = backup.BACKUP_DIR / "code"
            code.mkdir()
            (code / "DF-Overseer.zip").write_text("zip")
            game = Path(t) / "save" / "AI Test 1"
            game.mkdir(parents=True)
            kept = backup.prune(backup.BACKUP_DIR / "autosave 1", {"world": "W", "site_id": 7}, "autosave 1", now)
            left = backup.copies_of("W", "7", "autosave 1")
            # kept: the days 0.5, 1.5, 2.5, 3.5 days back; week 2's newest (20.2), week 3's (21.1)
            assert kept == len(left) == 6, [c.name for c in left]
            gone = {c for c in a + b if not c.exists()}
            assert gone == {a[4], b[2]}, sorted(c.name for c in gone)     # week 2's older one; 50 days back
            assert all(c.exists() for c in other) and (code / "DF-Overseer.zip").exists() and game.exists()
            assert not backup.fort_mark_path(a[4]).exists()
            # never anything that isn't a dated copy two levels inside backups/
            assert backup._remove_copy(game) is False and game.exists()
            assert backup._remove_copy(code) is False and code.exists()
        finally:
            backup.BACKUP_DIR = orig


# --- the old test saves' Needs you line --------------------------------------------------------------

@test("old test saves: one Needs you line with sizes, shown SHOW_HOURS once, again only when a new one appears; "
      "never deleted; gone ones drop out")
def _():
    with tempfile.TemporaryDirectory() as t:
        path = Path(t) / "old-saves.json"
        root = Path(t) / "save"
        s1, s2, s3 = root / "AI Test 1", root / "AI Run 2", root / "test fort"
        for s in (s1, s2, s3):
            s.mkdir(parents=True)
        now = 1_000_000.0
        assert old_saves.note([(s1, 20, 400_000_000), (s2, 30, 585_000_000)], now, path) is True
        lines = old_saves.needs_you(now, path)
        assert len(lines) == 1 and "AI Test 1 (400 MB)" in lines[0] and "985 MB" in lines[0], lines
        assert "never deletes" in lines[0]
        assert old_saves.needs_you(now + 3600, path) == lines             # still shown
        assert old_saves.needs_you(now + 7 * 3600, path) == []            # told: once
        # the next run check: the same saves, nothing new (so the check's flag is a plain line)
        assert old_saves.note([(s1, 21, 400_000_000), (s2, 31, 585_000_000)], now + 86400, path) is False
        assert old_saves.needs_you(now + 86400, path) == []
        # the player deleted one: it drops out, nothing told again
        s2.rmdir()
        assert old_saves.needs_you(now + 86400 + 60, path) == []
        # a new one: told again, with the ones still there
        old_saves.note([(s1, 22, 400_000_000), (s3, 15, 1_000_000)], now + 2 * 86400, path)
        lines = old_saves.needs_you(now + 2 * 86400, path)
        assert len(lines) == 1 and "test fort" in lines[0] and "AI Test 1" in lines[0] and "AI Run 2" not in lines[0]
        assert s1.exists() and s3.exists()                               # never deleted


@test("run check housekeeping: old test saves flagged while one is untold, then a plain line")
def _():
    import health_check as hc
    with tempfile.TemporaryDirectory() as t:
        os.environ["DFAI_LOG_DIR"] = t
        orig = old_saves.LIST
        old_saves.LIST = Path(t) / "old-saves.json"
        try:
            saves = Path(t) / "save"
            d = saves / "AI Test 9"
            d.mkdir(parents=True)
            (d / "world.sav").write_text("x" * 1000)
            old = time.time() - 40 * 86400
            os.utime(d, (old, old))
            bk = Path(t) / "backups"
            bk.mkdir()
            flags, plain = hc.housekeeping([saves], "autosave 1", bk)
            assert any("old test saves" in f for f in flags), flags
            assert old_saves.needs_you()                                 # the overseer shows it
            flags, plain = hc.housekeeping([saves], "autosave 1", bk)
            assert not any("old test saves" in f for f in flags), flags
            assert any("told on the Needs you list" in p for p in plain), plain
            assert d.exists()
        finally:
            old_saves.LIST = orig


@lua_test("the new and changed Lua compiles (5.3): ai-slices, ai-cavern-scan, ai-industry, ai-util, ai-bridge, "
          "ai-bridge-report, ai-threats, ai-syndromes")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    for name in ("ai-slices", "ai-cavern-scan", "ai-industry", "ai-util", "ai-bridge", "ai-bridge-report",
                 "ai-threats", "ai-syndromes"):
        src = (LUA_DIR / f"{name}.lua").read_text(encoding="utf-8")
        ok, err = lua.execute("local s, n = ...; local f, e = load(s, n); return f ~= nil, e", src, name)
        assert ok, (name, err)


if __name__ == "__main__":
    finish()
