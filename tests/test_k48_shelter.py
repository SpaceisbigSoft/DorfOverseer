"""(0.105.48, K48 group 3) The shelter: never shrunk for dangers that can't
come, always able to hold the civilians, widened back once the danger is
gone; the evil-weather keep-in on a shelter drawn now and with drink; the
shelter plan walked in slices so the pulse stays fast.

  * lua/ai-shelter-plan.lua dangers(): a hidden unit, one on an unrevealed
    tile, one sealed in a cavern (no citizen's walk group) left out; the
    surface and a building destroyer with a door-only entrance kept; the
    calm count; the walk in slices (pulse budget), `walking` and `stale`;
    the designation read as one number (`whole`);
  * brain/planner_shelter.py: the War-hold's shelter (one level, 90 tiles,
    28 drinks, 0 food for 34) never picked, a bigger one looked for, an
    unlivable pick in use dropped, widened back with the alarm up;
  * lua/ai-society.lua shelter_for_keep_in and ai-society-burrows
    weather_keep_in: drawn again at a spell's start, refused (and let out)
    with no drink.

    python tests/test_k48_shelter.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG  # noqa: E402
import planner_shelter as PS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
CFG = dict(PLANNER_CONFIG)


def _fake_src(file: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return node.value.value
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


# --- 1. the Lua: which dangers count, the walk in slices -----------------------------------

# extras over test_h5's fake fort: DF's tile flags and walk groups (by z,
# set by a test), isHidden, the real slices module
EXTRA = r"""
local env, W = ...
W.flags, W.groups = {}, {}
env.dfhack.units.isHidden = function(u) return u.hidden == true end
env.dfhack.maps = {
    getTileFlags = function(x, y, z) return W.flags[z] or {hidden = false, outside = false} end,
    getWalkableGroup = function(p) return W.groups[p.z] or 1 end,
}
local slices_src = W.slices_src
local senv = setmetatable({}, {__index = _G})
assert(load(slices_src, 'ai-slices', 't', senv))()
local old = env.reqscript
env.reqscript = function(n)
    if n == 'ai-slices' then return senv end
    return old(n)
end
W.slices = senv
"""


def fake(slices=True):
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(_fake_src("test_h5_shelter_plan.py", "FAKE"), module_src("ai-shelter-plan.lua"))
    lua.execute("""local env, W = ...
        W.block(100, {'', ' o............>'})
        local hall, deep = {'', ' .............X'}, {'', ' .............<'}
        for i = 1, 6 do table.insert(hall, ' ..............'); table.insert(deep, ' ..............') end
        W.block(99, hall)
        W.block(98, deep)""", env, w)
    if slices:
        w.slices_src = (LUA_DIR / "ai-slices.lua").read_text(encoding="utf-8")
        lua.execute(EXTRA, env, w)
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


def beast(lua, w, x, y, z, **kw):
    return add_unit(lua, w, id=900, name="Beast", danger=True, great=True, pos={"x": x, "y": y, "z": z},
                    flags1={"caged": False, "chained": False}, **kw)


def lua_test(name):
    def wrap(fn):
        def run():
            if LuaRuntime is None:
                skip("needs the lupa package (pip install lupa)")
            fn()
        return test(name)(run)
    return wrap


@lua_test("dangers: one DF hides (an unseen ambusher, a beast in a cavern not opened) doesn't shrink the shelter")
def _():
    lua, env, w = fake()
    civ(lua, w, 3, 3, 99)
    beast(lua, w, 5, 5, 60, hidden=True)
    r = py(env.report())
    assert r["danger"] is False and "candidates" not in r, r
    assert r["left_out"][0]["why"] == "hidden", r


@lua_test("dangers: one on an unrevealed tile (the War-hold's forgotten beasts) is left out")
def _():
    lua, env, w = fake()
    civ(lua, w, 3, 3, 99)
    beast(lua, w, 5, 5, 60)
    lua.execute("local W = ...; W.flags[60] = {hidden = true}", w)
    r = py(env.report())
    assert r["danger"] is False and r["left_out"][0]["why"] == "hidden", r


@lua_test("dangers: sealed in a cavern or the underworld (no citizen's walk group): left out; a destroyer with a door-only way in kept")
def _():
    lua, env, w = fake()
    civ(lua, w, 3, 3, 99)
    beast(lua, w, 5, 5, 3)
    lua.execute("local W = ...; W.flags[3] = {feature_global = true}; W.groups[3] = 7", w)
    r = py(env.report())
    assert r["danger"] is False and r["left_out"][0]["why"] == "sealed", r
    # the same group as the citizens: it can come
    lua.execute("local W = ...; W.groups[3] = 1", w)
    assert py(env.report())["danger"] is True
    # a building destroyer, sealed, but an entrance held by a door alone: it can come
    lua.execute("""local env, W = ...
        W.groups[3] = 7
        env.df.creature_raw = {find = function() return {caste = {[0] = {misc = {buildingdestroyer = 2}}}} end}
        W.units[#W.units].caste = 0
        env.reqscript('ai-gates').GATES.entrances[1].equipment = {{kind = 'door'}}""", env, w)
    assert py(env.report())["danger"] is True


@lua_test("dangers: on the surface or in the fort's rock with another walk group (the gates shut): still counted")
def _():
    lua, env, w = fake()
    civ(lua, w, 3, 3, 99)
    beast(lua, w, 0, 1, 100)
    lua.execute("local W = ...; W.flags[100] = {outside = true}; W.groups[100] = 5", w)
    r = py(env.report())
    assert r["danger"] is True and r["candidates"], r
    lua.execute("local W = ...; W.flags[100] = {outside = false}", w)
    assert py(env.report())["danger"] is True


@lua_test("calm: the ticks since no danger that can come was on the map")
def _():
    lua, env, w = fake()
    civ(lua, w, 3, 3, 99)
    r = py(env.report())
    assert r["danger"] is False and r["calm_ticks"] == 0, r
    lua.execute("local env = ...; env.df.global.cur_year_tick = env.df.global.cur_year_tick + 700", env)
    assert py(env.report())["calm_ticks"] == 700
    t = beast(lua, w, 0, 1, 100)
    assert py(env.report())["danger"] is True
    lua.execute("local t = ...; t.hidden = true", t)
    assert py(env.report())["calm_ticks"] == 0


@lua_test("slices: a pulse walks a slice (nothing yet: walking), the plan whole after a few; the same as a full report's")
def _():
    lua, env, w = fake()
    civ(lua, w, 3, 3, 99)
    civ(lua, w, 4, 4, 99)
    beast(lua, w, 0, 1, 100)
    full = py(env.report(None, "daily"))
    assert full["danger"] and len(full["candidates"]) == 2, full
    lua2, env2, w2 = fake()
    civ(lua2, w2, 3, 3, 99)
    civ(lua2, w2, 4, 4, 99)
    beast(lua2, w2, 0, 1, 100)
    lua2.execute("local env = ...; env.SHELTER_SLICE_MS_FIRST = 0; env.SHELTER_SLICE_MS_PULSE = 0", env2)
    # (r5 p1) a clock that moves 1 ms each time it is read: the slices go by
    # their budgets (0 ms: a block a slice; the walk's 1 ms: an item a slice),
    # not by how fast this PC is (under load, or with Windows' coarse
    # os.clock, the walk took more or fewer pulses)
    lua2.execute("local t = 0; os.clock = function() t = t + 0.001; return t end")
    seen = []
    r = None
    for _ in range(12):
        r = py(env2.report(None, "pulse"))
        seen.append(bool(r.get("walking")))
        if not r.get("walking"):
            break
    assert seen[0] is True and seen[-1] is False and len(seen) >= 3, seen      # three blocks, a block a slice
    key = lambda c: (c["z"], c["d_threat"], c["civ_p90"], c["tiles"])
    assert sorted(map(key, r["candidates"])) == sorted(map(key, full["candidates"])), (r["candidates"], full["candidates"])
    # another pick: the last plan sent as stale (no walk to the shelter) until walked again
    w2.site["ai-overseer/shelter-pick"] = T(lua2, {"levels": [98], "tick": 300 * 403200 + 900})
    r = py(env2.report(None, "pulse"))
    assert r.get("stale") is True and r["candidates"], r
    for _ in range(12):
        r = py(env2.report(None, "pulse"))
        if not r.get("stale"):
            break
    assert not r.get("stale") and r.get("current_walk"), r


@lua_test("slices: the full report's budget walks it whole at once; the bridge gives the section its tier")
def _():
    lua, env, w = fake()
    civ(lua, w, 3, 3, 99)
    beast(lua, w, 0, 1, 100)
    r = py(env.report(None, "daily"))
    assert not r.get("walking") and r["candidates"], r
    hub = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "local ctx = {tier = tier}" in hub and "report(txt, ctx and ctx.tier)" in hub
    assert "'shelter_grid', 'shelter_walk'" in hub


@lua_test("grid: DF's designation read as one number (whole): hidden, outside, a cavern, magma and deep water as the fields say")
def _():
    lua, env, w = fake(slices=False)
    grid, counts = lua.execute(r"""local env = ...
        local blocks = env.df.global.world.map.map_blocks
        for i = #blocks, 1, -1 do blocks[i] = nil end
        local des, tt = {}, {}
        for x = 0, 15 do des[x], tt[x] = {}, {}
            for y = 0, 15 do des[x][y] = {whole = 0}; tt[x][y] = 2 end
        end
        des[1][0].whole = 512                    -- hidden
        des[2][0].whole = 65536                  -- outside
        des[3][0].whole = 1 << 29                -- feature_global (the underworld)
        des[4][0].whole = 1 << 28                -- feature_local (a cavern)
        des[5][0].whole = 1 + (1 << 21)          -- magma
        des[6][0].whole = 5                      -- deep water
        des[7][0].whole = 2                      -- shallow water: a way
        des[8][0].whole = 1 << 15                -- subterranean: inside as ever
        table.insert(blocks, {map_pos = {x = 0, y = 0, z = 50}, designation = des, tiletype = tt})
        return env.build_grid(50, 50, {{x = 2, y = 0, z = 50}})""", env)
    K = lambda x, y, z: x + y * 1024 + z * 1048576
    assert grid[K(0, 0, 50)] == 1 + 16 and grid[K(7, 0, 50)] == 17 and grid[K(8, 0, 50)] == 17
    assert grid[K(1, 0, 50)] is None and grid[K(5, 0, 50)] is None and grid[K(6, 0, 50)] is None
    assert grid[K(2, 0, 50)] == 1 and grid[K(3, 0, 50)] == 1 and grid[K(4, 0, 50)] == 1     # near the point: outside ones
    assert counts[50] == 256 - 6, counts[50]                                       # six no inside way


# --- 2. the brain: a shelter that holds the civilians, widened back ------------------------

def cand(z, d, p90=5, drink=0, wells=0, tiles=200, food=200, reached=10):
    return {"z": z, "d_threat": d, "civ_p90": p90, "civ_med": p90 // 2, "civ_reached": reached, "civ_late": 0,
            "drink": drink, "wells": wells, "tiles": tiles, "food": food,
            "chokes": [], "way_in": {"id": 1, "kind": "surface", "x": 10, "y": 20, "z": 170}}


def splan(cands, current=None, civilians=34, **kw):
    p = {"danger": True, "candidates": cands,
         "dangers": [{"id": 900, "name": "Demon", "great": True, "x": 9, "y": 20, "z": 170, "way_in": 1}],
         "civilians": civilians, "barracks": []}
    if current is not None:
        p["current"] = {"levels": current}
    p.update(kw)
    return p


def state(sp, alert=False, total=34):
    return {"date": {"year": 300, "tick": 1000}, "shelter_plan": sp, "civ_alert": alert,
            "civ_alert_shelter": "ai", "dwarves": {"total": total}, "military": {"squads": []}}


def run(s, cfg=None):
    props, notes = [], []
    PS._shelter_pick_rule(s, cfg or CFG, props, notes, Memory())
    return props, notes


WAR_HOLD = [cand(151, 40, p90=60, drink=28, tiles=90, food=0), cand(140, 30, p90=60, drink=500, tiles=900, food=900)]


@test("War-hold: one level of 90 tiles, 28 drinks, 0 food for 34: never picked; the whole fort kept")
def _():
    c = PS.choose_shelter(splan(WAR_HOLD[:1]), CFG, citizens=34)
    assert c and c["livable"] is False and any("0 food" in x for x in c["short"]), c
    p, n = run(state(splan(WAR_HOLD[:1])))
    assert p == [] and any("can hold the civilians" in x for x in n), (p, n)


@test("War-hold: that pick in use is dropped: the whole fort again (no level away from it holds them)")
def _():
    p, n = run(state(splan(WAR_HOLD[:1], current=[151])))
    assert [x.action for x in p] == [{"type": "shelter_pick", "clear": True}], [x.action for x in p]
    assert "can hold the civilians" in p[0].reason


@test("bigger: no three levels within two hold them: looked for wider (four levels away), the levels together")
def _():
    cands = [cand(150, 90, wells=1, tiles=40, food=0), cand(154, 80, tiles=60, food=100), cand(170, 3, p90=10)]
    c = PS.choose_shelter(splan(cands, civilians=30), CFG, citizens=30)
    assert c["livable"] and c["levels"] == [150, 154], c
    p, n = run(state(splan(cands, civilians=30), total=30))
    assert [x.action.get("levels") for x in p] == [[150, 154]], [x.action for x in p]


@test("pick in use that can't hold them is replaced even when it is safe (no hysteresis for it)")
def _():
    cands = [cand(160, 45, wells=1, tiles=20, food=0), cand(150, 50, wells=1, tiles=400, food=400)]
    walk = {"d_threat": 45, "civ_p90": 5}
    p, n = run(state(splan(cands, current=[160], current_walk=walk)))
    assert [x.action.get("levels") for x in p] == [[150]] and "holds only" in p[0].reason, [(x.action, x.reason) for x in p]
    # a livable pick in use stays (the hysteresis as before)
    cands[0].update(tiles=400, food=400)
    p, n = run(state(splan(cands, current=[160], current_walk=walk)))
    assert p == [], [x.action for x in p]


@test("widened back: no danger that can come for shelter_widen_ticks: the whole fort again, alarm up or not")
def _():
    s = state({"danger": False, "current": {"levels": [151]}, "calm_ticks": 100}, alert=True)
    assert run(s)[0] == []
    s["shelter_plan"]["calm_ticks"] = CFG["shelter_widen_ticks"]
    p, _ = run(s)
    assert [x.action for x in p] == [{"type": "shelter_pick", "clear": True}], p
    s["civ_alert"] = False
    s["shelter_plan"]["calm_ticks"] = 0
    assert [x.action for x in run(s)[0]] == [{"type": "shelter_pick", "clear": True}]


@test("slices: a plan still being walked, or one made for other ways in: nothing moved on it")
def _():
    for extra in ({"walking": True}, {"stale": True}):
        p, n = run(state(splan([cand(150, 90, wells=1)], **extra)))
        assert p == [] and any("still being walked" in x for x in n), (extra, p, n)


@test("slices: a plan still being walked is no plan for the squads' post (they do as without one)")
def _():
    s = state(splan([cand(150, 90, wells=1)], walking=True))
    assert PS.plan_ready(s) == {} and PS.plan_ready(state(splan([cand(150, 90, wells=1)]))), s


# --- 3. the weather keep-in: the shelter now, with drink --------------------------------------

if LuaRuntime:
    SOC = _fake_src("test_society.py", "FAKE")

    def soc():
        lua = LuaRuntime(unpack_returned_tuples=True)
        env, units, assigned, ntiles, g = lua.execute(SOC, module_src("ai-society.lua"))
        lua.execute("""local env = ...
            local b = {id = 9, name = 'AI shelter'}
            env.df.global.plotinfo.burrows.list[#env.df.global.plotinfo.burrows.list] = b
            env.dfhack.burrows.listBlocks = function() return {1, 2} end
            env.KEEP_IN_CHECKS = {}
            env.shelter_for_keep_in = function(force)
                table.insert(env.KEEP_IN_CHECKS, force)
                return env.KEEP_IN_SHELTER or {tiles = 30, redrawn = force}
            end""", env)
        return lua, env, units, assigned


@lua_test("weather keep-in: the shelter drawn again at a spell's first keep-in (not each resend); again after a let-out")
def _():
    lua, env, units, assigned = soc()
    assert env.weather_keep_in(True, False).ok
    assert env.weather_keep_in(True, False).ok
    env.weather_keep_in(False, False)
    assert env.weather_keep_in(True, False).ok
    assert py(env.KEEP_IN_CHECKS) == [True, False, True], py(env.KEEP_IN_CHECKS)


@lua_test("weather keep-in: no drink nor well in the shelter: refused and those kept in let out (the brain falls back)")
def _():
    lua, env, units, assigned = soc()
    r = env.weather_keep_in(True, False)
    n = r.members
    assert r.ok and n >= 5
    lua.execute("local env = ...; env.KEEP_IN_SHELTER = {tiles = 30, no_water = true}", env)
    r = env.weather_keep_in(True, False)
    assert not r.ok and r.rejected and "no drink" in r.error and r.released == n, dict(r)
    assert not any(assigned[i] for i in range(1, 8)), dict(assigned)
    assert env.weather_keep_in_status().members == 0
    lua.execute("local env = ...; env.KEEP_IN_SHELTER = {tiles = 0}", env)
    r = env.weather_keep_in(True, False)
    assert not r.ok and "covers no tiles" in r.error


@lua_test("shelter_for_keep_in: forced or unknown: drawn again and its drink read; drawn within the day: as recorded")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, got, w = lua.execute(_fake_src("test_fix26_combat.py", "FAKE"), module_src("ai-society.lua"))
    lua.execute("""local env = ...
        env.df.global.cur_year, env.df.global.cur_year_tick = 300, 1000
        env.dfhack.burrows.listBlocks = function() return {1} end""", env)
    r = env.shelter_for_keep_in(False)          # never drawn: drawn now
    assert r.redrawn and r.tiles > 0 and r.no_water, dict(r)
    lua.execute("""local w = ...
        w.drinks[1] = {flags = {}, pos = {x = 120, y = 150, z = 166}}
        w.wells[1] = {centerx = 125, centery = 150, z = 166,
                      getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end}""", w)
    r = env.shelter_for_keep_in(False)          # drawn just now: as recorded (no water then)
    assert r.redrawn is False and r.no_water, dict(r)
    r = env.shelter_for_keep_in(True)           # a spell's start: drawn again, the drink back
    assert r.redrawn and not r.no_water, dict(r)
    lua.execute("local env = ...; env.df.global.cur_year_tick = env.df.global.cur_year_tick + 1300", env)
    r = env.shelter_for_keep_in(False)          # over a day old: drawn again
    assert r.redrawn and not r.no_water, dict(r)


if __name__ == "__main__":
    finish()
