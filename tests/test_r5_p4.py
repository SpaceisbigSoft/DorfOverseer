"""(r5 p4) The slow report sections made cheaper, proved by counting the work
(tiles walked, game reads), never by the clock:

  * lua/ai-shelter-plan.lua: one level's walk is no longer one slice item
    (A, run 2: 1,038 ms each report, the walk 2 of 6 levels a report and
    never whole): a slice walks at most SHELTER_WALK_CHUNK tiles of it, and
    the plan is the same as the whole walk's; a short calm (a beast on and
    off unrevealed tiles) keeps the range, the walk under way and the last
    plan; a calm of SHELTER_CALM_KEEP_TICKS drops them as before;
  * lua/ai-bridge-report.lua get_deep: the search for where the fort meets
    a cavern reads each tile once (it read a tile again for each of its 26
    neighbours);
  * lua/ai-syndromes.lua miasma_report: one flag read a miasma tile (two
    before), and the danger spots, walk groups and butcher's shop read only
    when something rots near it.

    python tests/test_r5_p4.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402
from lua_modules_util import module_src, bridge_part_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"


def const(file: str, name: str) -> str:
    """A string constant of another test file (its fake world), unrun."""
    tree = ast.parse((ROOT / "tests" / file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return eval(compile(ast.Expression(node.value), file, "eval"), {"__builtins__": {}})
    raise KeyError(name)


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


def py(v):
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    try:
        keys = list(v.keys())
    except AttributeError:
        return v
    if not keys:
        return {}
    if all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in sorted(keys)]
    return {k: py(v[k]) for k in keys}


def lua_test(name):
    def wrap(fn):
        def run():
            if LuaRuntime is None:
                skip("needs the lupa package (pip install lupa)")
            fn()
        return test(name)(run)
    return wrap


# --- 1. the shelter plan ---------------------------------------------------------------------

# test_h5's fake fort and test_k48's extras (tile flags, walk groups, isHidden,
# the real slices module); a bigger fort: 4 levels of 14 x 14 under the gate
COUNT = r"""
local env, W = ...
W.calls = 0
local nb = env.neighbours
env.neighbours = function(...) W.calls = W.calls + 1; return nb(...) end
W.range = {97, 101}
env.reqscript('ai-society').shelter_level_range = function() return W.range[1], W.range[2] end
"""


def shelter_fort():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(const("test_h5_shelter_plan.py", "FAKE"), module_src("ai-shelter-plan.lua"))
    lua.execute("""local env, W = ...
        W.block(100, {'', ' o............>'})
        local function level(top)
            local rows = {'', top}
            for i = 1, 13 do table.insert(rows, ' ..............') end
            return rows
        end
        W.block(99, level(' .............X'))
        W.block(98, level(' .............X'))
        W.block(97, level(' .............<'))""", env, w)
    w.slices_src = (LUA_DIR / "ai-slices.lua").read_text(encoding="utf-8")
    lua.execute(const("test_k48_shelter.py", "EXTRA"), env, w)
    lua.execute(COUNT, env, w)
    return lua, env, w


def add_unit(lua, w, **kw):
    u = T(lua, kw)
    w.units[len(w.units) + 1] = u
    if kw.get("citizen"):
        w.cits[len(w.cits) + 1] = u
    return u


def civ(lua, w, x, y, z):
    return add_unit(lua, w, citizen=True, pos={"x": x, "y": y, "z": z}, military={"squad_id": -1},
                    flags1={"caged": False, "chained": False})


def beast(lua, w, x, y, z):
    return add_unit(lua, w, id=900, name="Beast", danger=True, great=True, pos={"x": x, "y": y, "z": z},
                    flags1={"caged": False, "chained": False})


def people(lua, w):
    civ(lua, w, 3, 3, 99)
    civ(lua, w, 9, 9, 98)
    civ(lua, w, 5, 12, 97)
    return beast(lua, w, 0, 1, 100)


def sliced(env):
    """A pulse's budget of nothing: one slice item a report."""
    env.SHELTER_SLICE_MS_FIRST = 0
    env.SHELTER_SLICE_MS_PULSE = 0
    env.SHELTER_WALK_MAX_ITEMS = 1
    env.SHELTER_WALK_CHUNK = 20


def cand_key(c):
    return (c["z"], c.get("d_threat"), c.get("civ_med"), c.get("civ_p90"), c.get("civ_max"), c.get("civ_late"),
            c.get("reached"), c.get("tiles"), c.get("path"), len(c.get("chokes") or []))


@lua_test("shelter: a slice walks at most SHELTER_WALK_CHUNK tiles of a level's walk (one level was one item, "
          "over the budget); the plan is the whole walk's")
def _():
    lua, env, w = shelter_fort()
    people(lua, w)
    whole = py(env.report(None, "daily"))
    assert whole["danger"] and len(whole["candidates"]) >= 3, whole
    whole_calls = w.calls
    lua2, env2, w2 = shelter_fort()
    people(lua2, w2)
    sliced(env2)
    per, r = [], None
    for _ in range(400):
        before = w2.calls
        r = py(env2.report(None, "pulse"))
        per.append(w2.calls - before)
        if not r.get("walking"):
            break
    assert not r.get("walking") and r.get("candidates"), r
    # one chunk of a walk (20 tiles), or a level's plan finished (its path to the threat)
    assert max(per) <= 20 + 40, (max(per), per)
    assert sorted(map(cand_key, r["candidates"])) == sorted(map(cand_key, whole["candidates"])), \
        (r["candidates"], whole["candidates"])
    # the same work in all, only spread (a part a report)
    assert sum(per) <= whole_calls + 5, (sum(per), whole_calls)
    print(f"  (work: {whole_calls} tile visits whole; sliced at most {max(per)} a report over {len(per)} reports)")


@lua_test("shelter: a short calm (the beast on an unrevealed tile) keeps the walk under way and the last plan; "
          "a calm of SHELTER_CALM_KEEP_TICKS drops them")
def _():
    lua, env, w = shelter_fort()
    b = people(lua, w)
    sliced(env)
    r = None
    for _ in range(6):
        r = py(env.report(None, "pulse"))
    done = r["walk"]["done"]
    assert r.get("walking") and done > 0, r
    # the beast steps onto an unrevealed tile for a report; meanwhile the
    # citizens' levels read 98-100 (one went up): the range is kept
    lua.execute("local b = ...; b.hidden = true", b)
    w.range[1] = 98
    assert py(env.report(None, "pulse"))["danger"] is False
    lua.execute("local b = ...; b.hidden = false", b)
    r = py(env.report(None, "pulse"))
    assert r.get("walk", {}).get("done", 0) > done, r          # walked on, not begun again
    assert r["levels"] == [97, 101], r
    for _ in range(400):
        r = py(env.report(None, "pulse"))
        if not r.get("walking"):
            break
    assert r.get("candidates") and not r.get("walking"), r
    # the plan whole: a calm report, then the beast back: the plan sent at
    # once, nothing walked
    lua.execute("local b = ...; b.hidden = true", b)
    py(env.report(None, "pulse"))
    lua.execute("local b = ...; b.hidden = false", b)
    calls = w.calls
    r = py(env.report(None, "pulse"))
    assert r.get("candidates") and not r.get("walking") and w.calls - calls <= 2, (r, w.calls - calls)
    # a calm that lasts (a day): dropped, as before; the plan begun again
    lua.execute("local b = ...; b.hidden = true", b)
    py(env.report(None, "pulse"))
    lua.execute("local env = ...; env.df.global.cur_year_tick = env.df.global.cur_year_tick + 1200", env)
    assert py(env.report(None, "pulse"))["calm_ticks"] == 1200
    lua.execute("local b = ...; b.hidden = false", b)
    r = py(env.report(None, "pulse"))
    assert r.get("walking") and r["levels"] == [98, 101], r


@lua_test("shelter: bfs in steps is bfs whole (distances, reach, the cap, the intruder's zone)")
def _():
    lua, env, w = shelter_fort()
    out = lua.execute(r"""local env = ...
        local grid = {}
        for z = 1, 3 do for y = 0, 9 do for x = 0, 9 do
            local f = env.WALK
            if x == 5 and y == 5 then f = f + env.UP + env.DOWN end
            grid[env.K(x, y, z)] = f + env.INSIDE
        end end end
        local seeds = {env.K(0, 0, 1)}
        local zone = {[env.K(3, 3, 1)] = true, [env.K(4, 4, 1)] = true}
        local function same(cap, zn)
            local d1, n1, c1, b1 = env.bfs(grid, seeds, cap, zn)
            local st = env.bfs_begin(grid, seeds, cap, zn)
            local steps = 0
            while not env.bfs_step(st, 7) do steps = steps + 1 end
            if n1 ~= st.n or (c1 or false) ~= (st.capped or false) then return false end
            for k, v in pairs(d1) do if st.dist[k] ~= v then return false end end
            for k in pairs(st.dist) do if d1[k] == nil then return false end end
            if zn then
                for k in pairs(b1) do if not st.bad[k] then return false end end
                for k in pairs(st.bad) do if not b1[k] then return false end end
            end
            return steps > 3
        end
        return same(nil, nil), same(nil, zone), same(50, nil), same(50, zone)""", env)
    assert list(out) == [True, True, True, True], out


# --- 2. the deep section's junctions --------------------------------------------------------

DEEP = r"""
local env, cave_z = ...
local m = env.dfhack.maps
W_TT = 0
m.getTileType = function(x, y, z) W_TT = W_TT + 1; return 1 end
m.getWalkableGroup = function(p) return 1 end
local oldf = m.getTileFlags
m.getTileFlags = function(x, y, z)
    local f = oldf(x, y, z)
    f.feature_global = cave_z ~= nil and z <= cave_z
    return f
end
env.df.tiletype = env.df.tiletype or {}
env.df.tiletype.attrs = {[1] = {shape = 1}}
env.df.tiletype_shape = env.df.tiletype_shape or {}
env.df.tiletype_shape[1] = 'FLOOR'
"""


def deep_env(cave_z=None):
    lua = LuaRuntime(unpack_returned_tuples=True)
    base = lua.execute(const("test_r40_sections.py", "FAKE"))()
    env = lua.execute(const("test_i6_speed.py", "HUB"), base, bridge_part_src("ai-bridge-report"), None, None, None)
    lua.execute(DEEP, env, cave_z)
    return lua, env


@lua_test("deep: where the fort meets a cavern: each tile read once (a tile was read again for each of its 26 "
          "neighbours: 251,114 reads in this fort, now under 20,000)")
def _():
    lua, env = deep_env()
    o = env.get_deep()
    opened = [c for c in o.caverns.values() if c.open]
    assert len(opened) == 2 and all(c.junctions is not None and len(c.junctions) == 0 for c in opened)
    n = lua.eval("W_TT")
    assert n < 20000, n
    print(f"  (work: {n} tile reads)")


@lua_test("deep: the junctions found are the same: a walkable fort tile of the citizens' group beside a cavern one")
def _():
    lua, env = deep_env(cave_z=34)
    o = env.get_deep()
    by = {str(c.name): c for c in o.caverns.values()}
    j = py(by["Cavern1"].junctions)
    assert len(j) == 4, j
    for x in j:
        assert x["z"] >= 35 and x["cave"]["z"] <= 34 and x["cave"]["z"] == x["z"] - 1, x
        assert max(abs(x["cave"]["x"] - x["x"]), abs(x["cave"]["y"] - x["y"])) <= 1, x
    # the first found as the old search found it: the lowest level, then y, then x
    assert (j[0]["z"], j[0]["y"], j[0]["x"]) == min((x["z"], x["y"], x["x"]) for x in j), j


# --- 3. miasma ------------------------------------------------------------------------------

MIASMA = r"""
local env, W = ...
W.flag_reads, W.cit_reads = 0, 0
local f = env.dfhack.maps.getTileFlags
env.dfhack.maps.getTileFlags = function(...) W.flag_reads = W.flag_reads + 1; return f(...) end
local c = env.dfhack.units.getCitizens
env.dfhack.units.getCitizens = function(...) W.cit_reads = W.cit_reads + 1; return c(...) end
"""


def miasma_world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(const("test_syndromes.py", "FAKE"), module_src("ai-syndromes.lua"))
    lua.execute(MIASMA, env, w)
    w.boxes = T(lua, {100: {"x1": 0, "y1": 0, "x2": 31, "y2": 31}})
    return lua, env, w


@lua_test("miasma: one flag read a miasma tile (outside, cavern: two before); nothing rotting near it: no walk "
          "of the citizens for the haulers' walk groups")
def _():
    lua, env, w = miasma_world()
    for x in range(0, 30):
        for y in range(0, 10):
            w.flow(x, y, 100)
    w.flow(5, 20, 99)
    w.outside["5,20,99"] = True
    r = py(env.miasma_report())
    assert r["tiles"] == 301 and r["indoor"] == 300 and r["living"] == 300 and r["markable"] == 0, r
    assert w.flag_reads == 301, w.flag_reads
    assert w.cit_reads == 0, w.cit_reads


if __name__ == "__main__":
    finish()
