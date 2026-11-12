"""(0.105.40b fix) The dig guard's review findings (lua/ai-util.lua dig_forbidden,
deep_map, deep_tile, deep_hazard; lua/ai-builder.lua quickfort_apply,
dig_guard_note, dig_guard_sweep; the water works' and cistern's plugs):

  1. fail closed near the deep: a guard read error at or below the deep floor
     (the lowest cavern's top) or beside a deep level refuses the tile; above
     it, or with no floor known, let by as before; quickfort_apply drops only
     the deep levels when the whole guard throws;
  2. performance: nil at once above the floor where z-1..z+1 hold nothing
     deep (no block read); the daily deep_hazard walk only over the blocks
     that can hold any of it;
  3. the features fallback keyed by (region, index); deep_hazard uses it too;
  4. map special stone of a block whose local feature is known not to be a
     tube is not 'the adamantine spire';
  5. a plug the guard refuses holds the water works / the cistern with the
     guard's reason (not 'dig-now did not dig it'), counted once per tile;
  6. refusals counted once per tile; the guard's why in the wells', way-in's
     and landmarks' failure texts;
  7. everything the guard keeps dropped when the map or world unloads;
  8. 'F' digs; an unknown key refused at a deep level;
  9. once per map, the AI's own dig designations on refused tiles in its
     open projects' areas taken back (never elsewhere).

    python tests/test_r41_dig_guard_fix.py
"""

from __future__ import annotations

import ast
import re
import sys
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


def lua_const(test_file: str, name: str) -> str:
    """A string constant of another test file, read without running it."""
    tree = ast.parse((ROOT / "tests" / test_file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return eval(compile(ast.Expression(node.value), test_file, "eval"), {"__builtins__": {}})
    raise KeyError(name)


DEEP = lua_const("test_r41_dig_guard.py", "DEEP")
ERR = "the dig guard could not read the tile"

if LuaRuntime is not None:
    LUA = LuaRuntime(unpack_returned_tuples=True)
    D = LUA.execute(DEEP)
    U = LUA.execute("local src, D = ...; local env = setmetatable({df = D.df, dfhack = D.dfhack}, {__index = _G}); "
                    "assert(load(src, 'ai-util', 't', env))(); return env", UTIL_SRC, D)
    REAL_FLAGS = D.maps.getTileFlags
else:  # pragma: no cover
    LUA = D = U = None


def T(d):
    return LUA.table_from({k: (LUA.table_from(v) if isinstance(v, dict) else v) for k, v in d.items()})


def reset():
    D.reset()
    D.maps.getTileFlags = REAL_FLAGS
    U.dig_guard_unload()
    U.dig_guard_reset()


def guard(x, y, z):
    U.dig_guard_reset()
    return U.dig_forbidden(x, y, z)


def adamantine(x, y, z, **kw):
    D.set(x, y, z, T(dict({"vein": D.ADAM, "mat": "MINERAL"}, **kw)))


def cavern(z_lo, z_hi, gf=2):
    """A cavern layer (a global subterranean feature) on levels z_lo..z_hi."""
    D.global_types[gf] = D.FT.subterranean_from_layer
    for z in range(z_lo, z_hi + 1):
        D.feat(3, 3, z, T({"gf": gf}))


def broken_at(*tiles):
    """getTileFlags throws for these tiles (a read the guard can't make)."""
    bad = {f"{x},{y},{z}" for x, y, z in tiles}
    D.maps.getTileFlags = lambda x, y, z: (_ for _ in ()).throw(RuntimeError("boom")) \
        if f"{x},{y},{z}" in bad else REAL_FLAGS(x, y, z)


def util_test(name):
    def deco(fn):
        def run():
            if LuaRuntime is None:
                return
            reset()
            try:
                fn()
            finally:
                reset()
        return test(name)(run)
    return deco


# --- 1. fail closed near the deep ------------------------------------------------------------

@util_test("1 fail-closed: a read error at or below the deep floor, or beside a deep level, refuses; above it "
           "and with no floor known it is let by (as before); counted once per tile")
def _():
    cavern(10, 12)                              # the lowest cavern: floor at z 12
    D.feat(2, 2, 40, T({"lf": 4}))              # a spire block at z 40: a deep level above the floor
    D.local_types[4] = D.FT.deep_special_tube
    broken_at((5, 5, 12), (5, 5, 8), (5, 5, 41), (5, 5, 30))
    U.dig_guard_reset()
    dm = U.deep_map()
    assert dm.ok and dm.floor == 12 and dm.levels[40] and not dm.levels[30], (dm.floor,)
    assert guard(5, 5, 12) == ERR
    assert guard(5, 5, 8) == ERR
    assert guard(5, 5, 41) == ERR               # beside the spire's level
    assert guard(5, 5, 30) is None              # above the floor, nothing deep near: as before
    assert U.DIG_GUARD.unreadable == 3, U.DIG_GUARD.unreadable
    guard(5, 5, 12)
    assert U.DIG_GUARD.unreadable == 3          # the same tile once
    why, at = U.dig_check_tiles(LUA.table_from({1: T({"x": 5, "y": 5})}), 12, "test")
    assert why == ERR and U.DIG_GUARD.refused == 1
    # no deep floor known (a test's map): an error is let by, as before
    reset()
    broken_at((5, 5, 12))
    assert guard(5, 5, 12) is None


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
    Uw.dig_guard_unload()
    Uw.dig_guard_reset()
    return lua, B, W, Dw, Uw


def path_test(name):
    def deco(fn):
        def run():
            if LuaRuntime is None:
                return
            fn()
        return test(name)(run)
    return deco


@path_test("1 fail-closed: quickfort_apply with the whole guard throwing drops only the levels at or below the "
           "deep floor, and says why")
def _():
    lua, B, W, Dw, Uw = wayin_world()
    Dw.global_types[2] = Dw.FT.subterranean_from_layer
    Dw.feat(3, 3, 27, lua.table_from({"gf": 2}))          # the lowest cavern's top at z 27
    Uw.dig_guard_reset()

    def boom(*a):
        raise RuntimeError("guard broke")
    Uw.dig_guard_data = boom
    cell = lua.eval("function(t) return {{x = 0, y = 0, text = t}} end")
    st = B.quickfort_apply("dig", cell("d"), 27, 45, 25)
    assert st.dig_designated.value == 0 and st.dig_guard_refused.value == 1 and st.dig_guard_why == ERR, dict(st)
    assert not W.get(45, 25, 27).designated and Uw.DIG_GUARD.by.quickfort == 1
    st = B.quickfort_apply("dig", cell("d"), 28, 45, 25)    # above the floor: let by as before
    assert st.dig_designated.value == 1 and st.dig_guard_refused is None, dict(st)
    # no floor known: everything let by, as before
    lua, B, W, Dw, Uw = wayin_world()
    Uw.dig_guard_data = boom
    cell = lua.eval("function(t) return {{x = 0, y = 0, text = t}} end")
    st = B.quickfort_apply("dig", cell("d"), 27, 45, 25)
    assert st.dig_designated.value == 1, dict(st)


# --- 2. performance ----------------------------------------------------------------------------

@util_test("2 performance: above the deep floor with nothing deep on z-1..z+1 the guard reads no block; at a "
           "deep level it reads them; the daily walk skips blocks that hold nothing deep")
def _():
    cavern(10, 12)
    adamantine(30, 30, 50)
    D.set(60, 60, 30, T({"vein": 1, "mat": "MINERAL"}))   # a granite block at z 30: never walked
    U.dig_guard_reset()
    U.dig_forbidden(0, 0, 0)                              # builds the deep map once
    D.calls = 0
    for x in range(100):
        assert U.dig_forbidden(x, 20, 30) is None
    assert D.calls == 0, D.calls
    assert U.dig_forbidden(31, 30, 50) == "next to raw adamantine" and D.calls > 0
    assert U.dig_forbidden(30, 30, 49) == "under raw adamantine"
    h = U.deep_hazard(None, False)
    assert h.tiles == 1 and h.deep_floor == 12, dict(h)
    # walked: the cavern's three levels (at/below the floor) and the adamantine's; not z 30
    assert U.DEEP_HAZARD_CACHE.walked == 4, U.DEEP_HAZARD_CACHE.walked
    # with no floor known the walk is the whole map, as before
    reset()
    adamantine(30, 30, 50)
    D.set(60, 60, 30, T({"vein": 1, "mat": "MINERAL"}))
    U.deep_hazard(None, False)
    assert U.DEEP_HAZARD_CACHE.walked == 2


# --- 3. the features fallback by (region, index) ------------------------------------------------

FEATS = """local D, entries = ...
  local F = D.df.global.world.features
  F.map_features, F.feature_local_idx, F.feature_global_idx, F.feature_x, F.feature_y = {}, {}, {}, {}, {}
  for _, e in ipairs(entries) do
    local t = e[4]
    table.insert(F.map_features, {_t = t, getType = function() return t end})
    table.insert(F.feature_local_idx, e[3]); table.insert(F.feature_global_idx, -1)
    table.insert(F.feature_x, e[1]); table.insert(F.feature_y, e[2])
  end
"""


def features(*entries):
    LUA.execute(FEATS, D, LUA.table_from({i + 1: LUA.table_from({j + 1: v for j, v in enumerate(e)})
                                          for i, e in enumerate(entries)}))


@util_test("3 fallback: a local feature index is read in its own region (index 4 is a tube elsewhere, a cave "
           "here: no spire); deep_hazard reads the spire the same way")
def _():
    D.init_lookup = False                                 # no getLocalInitFeature: the map's list
    D.feat(2, 2, 25, T({"lf": 4}))                        # the fake's blocks are in region (3, 4)
    D.set(40, 40, 25, T({"feature_local": True, "mat": "FEATURE"}))
    features((3, 4, 4, D.FT.cave), (5, 5, 4, D.FT.deep_special_tube))
    assert guard(40, 40, 25) is None, guard(40, 40, 25)
    U.DEEP_HAZARD_CACHE = None
    assert U.deep_hazard(None, False).spire_seen is False
    features((3, 4, 4, D.FT.deep_special_tube), (5, 5, 4, D.FT.cave))
    assert guard(40, 40, 25) == "the adamantine spire"
    U.dig_guard_reset()
    U.DEEP_HAZARD_CACHE = None
    assert U.deep_hazard(None, False).spire_seen is True
    # no region in the list (an older DFHack): by index alone, a tube anywhere counts (as before)
    D.sync_features()
    D.local_types[4] = D.FT.deep_special_tube
    D.sync_features()
    assert guard(40, 40, 25) == "the adamantine spire"


# --- 4. the spire's label ----------------------------------------------------------------------

@util_test("4 deep_tile: special stone of a block whose local feature is known not to be a tube is not "
           "'the adamantine spire'; unknown still is")
def _():
    D.feat(2, 2, 25, T({"lf": 4}))
    D.local_types[4] = D.FT.cave
    D.set(40, 40, 25, T({"feature_local": True, "mat": "FEATURE"}))
    assert guard(40, 40, 25) is None
    D.local_types[4] = None                     # the feature unknown (not listed): still refused
    assert guard(40, 40, 25) == "the adamantine spire"


# --- 5. the plugs held with the guard's reason --------------------------------------------------

WW_FAKE = lua_const("test_waterworks.py", "FAKE")


def moat_world(guard_why):
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(WW_FAKE, (LUA_DIR / "ai-waterworks.lua").read_text(encoding="utf-8"))
    W = env.W
    tl = lua.table_from
    for x in range(40, 61):
        for y in range(30, 51):
            W.set(x, y, 100, tl({"outside": False}))
    W.entrances = tl([tl({"x": 50, "y": 50, "z": 100, "id": 1})])
    W.citizens = tl([tl({"x": 50, "y": 40, "z": 100}), tl({"x": 52, "y": 40, "z": 100})])
    for y in range(52, 58):
        W.set(40, y, 99, tl({"shape": "FLOOR", "material": "RIVER", "liquid": True, "depth": 7, "outside": True}))
        W.set(40, y, 100, tl({"shape": "EMPTY", "outside": True}))
    W.survey = tl({"bodies": tl([tl({"kind": "river", "tiles": 6, "nearest": tl({"x": 40, "y": 54, "z": 99})})])})
    Uu = lua.execute("local src = ...; local env = setmetatable({}, {__index = _G}); "
                     "assert(load(src, 'ai-util', 't', env))(); return env", UTIL_SRC)
    builder = lua.table_from({"dig_forbidden": guard_why})
    env.reqscript = lambda name, *a: builder if name == "ai-builder" else (Uu if name == "ai-util" else None)
    return lua, env, W, Uu


@path_test("5 the water works' plug refused by the guard: held with the guard's reason (no 'dig-now did not "
           "dig it'), the plug not dug, counted once")
def _():
    state = {"on": False}
    lua, env, W, Uu = moat_world(lambda x, y, z: "next to raw adamantine" if state["on"] else None)
    step = lambda: env.step("moat", lua.table_from({}))
    assert step().stage == "planned"
    assert step().stage == "digging"
    wk = W.saved["ai-overseer/waterworks"].works.moat
    W.dig_all(wk.plan.dig)
    step()
    W.dig_all(wk.plan.dig2)
    assert step().stage == "building"
    W.build_all()
    step()
    assert step().stage == "filling"
    state["on"] = True
    p = wk.plan.plug
    dry = env.step("moat", lua.table_from({"dry_run": True}))
    assert dry.stage == "held" and Uu.DIG_GUARD.refused == 0, dict(dry)         # a dry run: not counted
    r = step()
    assert r.stage == "held" and "next to raw adamantine" in r.error and "guards the underworld" in r.error, dict(r)
    assert "dig-now" not in r.error
    assert W.get(p.x, p.y, p.z).shape != "EMPTY"                                 # not dug
    r2 = step()
    assert r2.stage == "held" and r2.error == r.error
    assert Uu.DIG_GUARD.refused == 1 and Uu.DIG_GUARD.by.waterworks_plug == 1


@test("5 the cistern's plug refused by the guard: held (held = true) with the guard's reason, before any "
      "dig-now; the refusal counted once per tile")
def _():
    src = (LUA_DIR / "ai-builder-cistern.lua").read_text(encoding="utf-8")
    i = src.index("dig_check_tiles({{x = p.plug.x, y = p.plug.y}}, zi")
    seg = src[i:i + 900]
    assert "held = true" in seg and "guards the underworld" in seg and "d.guard_held" in seg, seg
    assert src.index("'dig-now'", i) > i + seg.index("held = true")
    if LuaRuntime is None:
        return
    reset()
    adamantine(30, 30, 20)
    U.dig_guard_reset()
    tiles = LUA.table_from({1: T({"x": 31, "y": 30})})
    for _ in range(5):                                   # the step asked every cycle
        assert U.dig_check_tiles(tiles, 20, "cistern_plug")[0] == "next to raw adamantine"
    assert U.DIG_GUARD.refused == 1 and U.DIG_GUARD.by.cistern_plug == 1 and U.DIG_GUARD.asked == 5
    reset()


# --- 6. counted per tile; the guard's why in the failure texts --------------------------------

@util_test("6 refusals counted once per tile (a second path for the same tile counts for that path, not again "
           "in the total)")
def _():
    U.dig_refused("quickfort", 1, 2, 3, "next to raw adamantine")
    U.dig_refused("quickfort", 1, 2, 3, "next to raw adamantine")
    U.dig_refused("join", 1, 2, 3, "next to raw adamantine")
    U.dig_refused("join", 4, 2, 3, "next to raw adamantine")
    g = U.DIG_GUARD
    assert g.refused == 2 and g.by.quickfort == 1 and g.by.join == 2 and g.asked == 4, (g.refused, dict(g.by))
    assert len(g.last) == 2


@path_test("6 the guard's why in the failure texts: dig_guard_note on quickfort's stats; the wells, the way in "
           "and the landmarks add it")
def _():
    lua, B, W, Dw, Uw = wayin_world()
    Dw.set(42, 25, 27, lua.table_from({"vein": Dw.ADAM, "mat": "MINERAL"}))
    Uw.dig_guard_reset()
    cell = lua.eval("function(t) return {{x = 0, y = 0, text = t}} end")
    st = B.quickfort_apply("dig", cell("h"), 27, 43, 25, "run", True)
    note = B.dig_guard_note(st)
    assert "the dig guard refused 1: next to raw adamantine" in note and "guards the underworld" in note, note
    assert B.dig_guard_note(B.quickfort_apply("dig", cell("d"), 27, 50, 25, "run", True)) == ""
    assert B.dig_guard_note("boom") == "" and B.dig_guard_note(None) == ""
    # (0.105.41 review) the cave-in check's refused channels in their own words
    mk = lua.eval("function(r, why, c, cwhy) return {dig_guard_refused = {value = r}, dig_guard_why = why, "
                  "dig_guard_cave_ins = c and {value = c} or nil, dig_guard_cave_why = cwhy} end")
    cave = B.dig_guard_note(mk(2, "a floor beside it would hang over nothing (a cave-in)", 2,
                               "a floor beside it would hang over nothing (a cave-in)"))
    assert "underworld" not in cave and "2 channel(s) left out" in cave and "a cave-in would follow" in cave, cave
    both = B.dig_guard_note(mk(3, "next to raw adamantine", 1, "a floor beside it would hang over nothing (a cave-in)"))
    assert "the dig guard refused 2: next to raw adamantine" in both and "1 channel(s) left out" in both, both
    wells = (LUA_DIR / "ai-builder-wells.lua").read_text(encoding="utf-8")
    assert re.search(r"channel the well spot at x%d y%d z%d'\):format\(\s*spot\.x, spot\.y, ez\(spot\.z\)\) \.\. "
                     r"dig_guard_note\(dry\)", wells)
    assert re.search(r"channel the shaft at elevation %d'\):format\(ez\(zk\)\)\s*\.\. dig_guard_note\(d\)", wells)
    proj = (LUA_DIR / "ai-builder-projects.lua").read_text(encoding="utf-8")
    assert re.search(r"the game would not dig x%d y%d z%d \(%s\)'\):format\([^\n]*\n\s*\.\. \(okd and "
                     r"dig_guard_note\(st\)", proj)
    lm = (LUA_DIR / "ai-builder-landmarks.lua").read_text(encoding="utf-8")
    assert re.search(r"the game would dig %d of its %d tiles'\):format\([^\n]*\n[^\n]*\n\s*\.\. \(okq and "
                     r"dig_guard_note\(dry\)", lm)


# --- 7. unload ---------------------------------------------------------------------------------

@path_test("7 the map or world unloading drops the raws' memo, the tick memo, the deep map, the day's "
           "deep_hazard and the refusals")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    Dd = lua.execute(DEEP)
    Uu = lua.execute("local src, D = ...; SC_MAP_UNLOADED, SC_WORLD_UNLOADED = 5, 6; "
                     "D.dfhack.onStateChange = {}; local env = setmetatable({df = D.df, dfhack = D.dfhack}, "
                     "{__index = _G}); assert(load(src, 'ai-util', 't', env))(); return env", UTIL_SRC, Dd)
    set_deep = lua.eval("function(D, v) D.df.global.world.raws.inorganics.all[7].flags.DEEP_SPECIAL = v end")
    handler = Dd.dfhack.onStateChange["ai-util-dig-guard"]
    assert handler is not None
    for sc in (5, 6):
        Dd.set(30, 30, 20, lua.table_from({"vein": Dd.ADAM, "mat": "MINERAL"}))
        Dd.global_types[2] = Dd.FT.subterranean_from_layer
        Dd.feat(3, 3, 10, lua.table_from({"gf": 2}))
        assert Uu.dig_forbidden(31, 30, 20) == "next to raw adamantine"
        Uu.dig_refused("quickfort", 31, 30, 20, "next to raw adamantine")
        Uu.deep_hazard(None, False)
        assert Uu.DEEP_MAP is not None and Uu.DEEP_HAZARD_CACHE is not None and Uu.DIG_GUARD.refused == 1
        set_deep(Dd, False)                                                            # another world's raws
        assert Uu.is_deep_inorganic(Dd.ADAM) is True                                  # memo: still the old
        handler(sc)
        assert Uu.DEEP_MAP is None and Uu.DEEP_HAZARD_CACHE is None and Uu.DIG_GUARD.refused == 0
        assert Uu.is_deep_inorganic(Dd.ADAM) is False
        set_deep(Dd, True)
        handler(sc)
        Dd.reset()
    handler(1)                                                                        # another event: nothing


# --- 8. the keys ---------------------------------------------------------------------------------

@util_test("8 'F' (a fortification) digs: refused beside adamantine; a key the guard doesn't know is refused at "
           "a deep level, kept elsewhere; a known safe key kept")
def _():
    cavern(10, 12)
    adamantine(30, 30, 20)
    U.dig_guard_reset()
    assert U.DIG_KEYS.F is True
    data = LUA.eval("""function() return {[20] = {[0] = {[0] = 'F', [1] = 'Q', [2] = 'x'}}} end""")()
    out, n, why = U.dig_guard_data(data, 31, 30, 0, "quickfort")
    assert n == 2 and why == "next to raw adamantine", (n, why)
    row = out[20][0]
    assert row[0] is None and row[1] is None and row[2] == "x", dict(row)
    assert U.DIG_GUARD.refused == 2
    # an unknown key far from anything deep: kept
    far = LUA.eval("function() return {[40] = {[0] = {[0] = 'Q'}}} end")()
    out, n, _ = U.dig_guard_data(far, 31, 30, 0, None)
    assert n == 0 and out[40][0][0] == "Q"
    # at the deep floor itself
    low = LUA.eval("function() return {[11] = {[0] = {[0] = 'Q(2x1)'}}} end")()
    out, n, why = U.dig_guard_data(low, 0, 0, 0, None)
    assert n == 2 and why == "an unknown dig key (Q) at a deep level" and LUA.eval("next")(out[11]) is None, (n, why)


# --- 9. the sweep on load -------------------------------------------------------------------------

@path_test("9 once per map: the AI's own dig designations on refused tiles in its open projects' areas taken "
           "back and logged; the player's elsewhere and a done project's left; not again")
def _():
    lua, B, W, Dw, Uw = wayin_world()
    B.df, B.dfhack = Dw.df, Dw.dfhack
    B.print = lambda *a: None
    tl = lua.table_from
    Dw.global_types[2] = Dw.FT.subterranean_from_layer
    Dw.feat(3, 3, 5, tl({"gf": 2}))                          # floor at z 5
    Dw.set(42, 25, 27, tl({"vein": Dw.ADAM, "mat": "MINERAL"}))
    for x, y, z in [(41, 25, 27), (44, 25, 27), (43, 25, 27), (41, 26, 27), (60, 60, 27), (41, 24, 27)]:
        Dw.set(x, y, z, tl({"dig": 1}))
    projects = tl({"list": tl([
        tl({"id": 3, "phase": "dig", "area": tl({"x1": 40, "y1": 25, "x2": 44, "y2": 26, "z": 27})}),
        tl({"id": 2, "phase": "done", "area": tl({"x1": 40, "y1": 24, "x2": 44, "y2": 24, "z": 27})})])})
    B.load_projects = lambda: projects
    B.sweep_acting = lambda: True                            # (fix41-ff) the AI acting
    Uw.dig_guard_reset()
    r = B.dig_guard_sweep(True)                              # a dry run: counted, nothing changed
    assert r.removed == 3 and Dw.tile(41, 25, 27).dig == 1, dict(r)
    r = B.dig_guard_sweep()
    assert r.removed == 3, dict(r)
    assert Dw.tile(41, 25, 27).dig == 0 and Dw.tile(43, 25, 27).dig == 0 and Dw.tile(41, 26, 27).dig == 0
    assert Dw.tile(44, 25, 27).dig == 1                      # two away: kept
    assert Dw.tile(60, 60, 27).dig == 1                      # outside every area (the player's): kept
    assert Dw.tile(41, 24, 27).dig == 1                      # a done project's area: kept
    assert Uw.DIG_GUARD.by.sweep == 3 and Uw.DIG_GUARD.swept.removed == 3
    h = Uw.deep_hazard(None, False)
    assert h.swept.removed == 3, dict(h)
    Dw.set(41, 25, 27, tl({"dig": 1}))
    assert B.dig_guard_sweep() is None and Dw.tile(41, 25, 27).dig == 1   # once per map
    # the report's deep section runs it
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    fn = src[src.index("function deep_hazard_section()"):src.index("\nend\n", src.index("function deep_hazard_section()"))]
    assert "dig_guard_sweep()" in fn


# --- (fix41-ff) the re-review -------------------------------------------------------------------

@test("ff 1: every unload hook this round checks `dfhack.onStateChange` itself (a userdata in the game), "
      "with its own key; the dig guard's hook registers on a userdata-like event")
def _():
    import glob
    for f in glob.glob(str(LUA_DIR / "*.lua")):
        assert "type(dfhack.onStateChange)" not in Path(f).read_text(encoding="utf-8"), f
    keys = []
    for name in ("ai-util.lua", "ai-hauling.lua", "ai-bridge-orders.lua"):
        src = (LUA_DIR / name).read_text(encoding="utf-8")
        assert "if dfhack and dfhack.onStateChange then" in src, name
        keys += re.findall(r"dfhack\.onStateChange\['([^']+)'\]", src)
    assert len(keys) == len(set(keys)) and "ai-util-dig-guard" in keys, keys
    if LuaRuntime is None:
        return
    lua = LuaRuntime(unpack_returned_tuples=True)

    class Event:                    # a Python object: a userdata in Lua, as DFHack's event is
        pass
    ev = Event()
    assert lua.eval("type")(ev) == "userdata"
    lua.execute("local src, ev = ...; local env = setmetatable({dfhack = {onStateChange = ev}, "
                "SC_MAP_UNLOADED = 1, SC_WORLD_UNLOADED = 2}, {__index = _G}); assert(load(src, 'ai-util', 't', env))()",
                UTIL_SRC, ev)
    assert callable(getattr(ev, "ai-util-dig-guard", None)), vars(ev)


@test("ff 5, 8: 'n' is no longer a key the guard calls safe; the unreadable tiles remembered up to "
      "DIG_GUARD_TILES_MAX")
def _():
    if LuaRuntime is None:
        return
    assert U.DIG_KEYS_SAFE.n is None and U.dig_cell_unknown("n")
    assert U.DIG_KEYS_SAFE.x is True and not U.dig_cell_unknown("x")
    reset()
    cavern(10, 12)
    old = U.DIG_GUARD_TILES_MAX
    U.DIG_GUARD_TILES_MAX = 3
    try:
        tiles = [(x, 5, 8) for x in range(5, 11)]
        broken_at(*tiles)
        for x, y, z in tiles:
            assert guard(x, y, z) == ERR
        g = U.DIG_GUARD
        n = sum(1 for _ in g.unreadable_tiles.items())
        assert n == 3 and g.nunreadable == 3 and g.unreadable == 6, (n, g.unreadable)
    finally:
        U.DIG_GUARD_TILES_MAX = old
        reset()


def _moat_to_filling(lua, env, W):
    step = lambda: env.step("moat", lua.table_from({}))
    assert step().stage == "planned"
    assert step().stage == "digging"
    wk = W.saved["ai-overseer/waterworks"].works.moat
    W.dig_all(wk.plan.dig)
    step()
    W.dig_all(wk.plan.dig2)
    assert step().stage == "building"
    W.build_all()
    step()
    assert step().stage == "filling"
    return step, wk


@path_test("ff 3: the water works' plug: a guard read error waits (no lasting hold) and is read again; a "
           "refused plug's hold is looked at again each step; the message reads right")
def _():
    state = {"why": None}
    lua, env, W, Uu = moat_world(lambda x, y, z: state["why"])
    step, wk = _moat_to_filling(lua, env, W)
    state["why"] = ERR
    r = step()
    assert r.waiting and r.stage == "filling" and "waits: the dig guard could not read the tile" in r.error, dict(r)
    assert wk.stage == "filling"
    state["why"] = "next to raw adamantine"
    r = step()
    assert r.stage == "held" and r.error.endswith("is left alone (next to raw adamantine): it guards the underworld"), r.error
    assert wk.plug_guard
    assert step().stage == "held"                                     # still refused: still held
    state["why"] = None
    r = step()
    assert r.stage == "filling" and wk.stage == "filling" and not wk.plug_guard, dict(r)
    cis = (LUA_DIR / "ai-builder-cistern.lua").read_text(encoding="utf-8")
    assert "is left alone (%s): it guards the underworld" in cis and "waits: %s (read again next time)" in cis


@path_test("ff 6: the sweep: only while the AI acts; counted swept only once its walk has ended; the cap stops "
           "the whole walk")
def _():
    lua, B, W, Dw, Uw = wayin_world()
    B.df, B.dfhack = Dw.df, Dw.dfhack
    B.print = lambda *a: None
    tl = lua.table_from
    Dw.global_types[2] = Dw.FT.subterranean_from_layer
    Dw.feat(3, 3, 5, tl({"gf": 2}))
    Dw.set(42, 25, 27, tl({"vein": Dw.ADAM, "mat": "MINERAL"}))
    Dw.set(41, 25, 27, tl({"dig": 1}))
    projects = tl({"list": tl([tl({"id": 3, "phase": "dig", "area": tl({"x1": 40, "y1": 25, "x2": 44, "y2": 26, "z": 27})})])})
    B.load_projects = lambda: projects
    acting = {"on": False}
    B.sweep_acting = lambda: acting["on"]
    Uw.dig_guard_reset()
    assert B.dig_guard_sweep() is None and Dw.tile(41, 25, 27).dig == 1      # not acting: nothing, tried later
    assert Uw.DIG_GUARD.swept_key is None
    # a walk that throws: not counted as swept
    B.load_projects = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    acting["on"] = True
    try:
        B.dig_guard_sweep()
    except Exception:  # noqa: BLE001
        pass
    assert Uw.DIG_GUARD.swept_key is None
    B.load_projects = lambda: projects
    old = B.SWEEP_TILES_MAX
    B.SWEEP_TILES_MAX = 3
    try:
        r = B.dig_guard_sweep(True)
        assert r.looked == 3 and r.capped, (r.looked, r.capped)          # all areas, not one row
    finally:
        B.SWEEP_TILES_MAX = old
    r = B.dig_guard_sweep()
    assert r.removed == 1 and Dw.tile(41, 25, 27).dig == 0 and Uw.DIG_GUARD.swept_key is not None
    # the real check: halted, Advisor, or the overseer not acting -> false
    src = (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8")
    fn = src[src.index("function sweep_acting()"):src.index("function dig_guard_sweep(")]
    assert "is_halted()" in fn and "'advisor'" in fn and "STATUS.acting == 'acting'" in fn
    assert "the player's own designation" in src


if LuaRuntime is None:
    finish("these tests need the lupa package (pip install lupa)")
finish()
