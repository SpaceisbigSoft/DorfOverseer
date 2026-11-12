"""(0.105.38) The whole-map water survey (lua/ai-water.lua) and far sources
for the water works (lua/ai-waterworks.lua; the brain's planner_water.py and
digest.py): a river beyond the old 72-tile box found with its reach, the
slices within their time on a 288x288x194 map, a survey resumed across
cycles and reloads and dropped on unload, magma by kind (a pipe, a cavern's
pool, the sea), far rivers for a water wheel (never a moat: the near river
only), far still water for the muddied farm level (the long tunnel staged
and checked end to end, retired half-dug safely), a far pump stack,
the pipe before the sea for a magma workshop, near sources still first, and
the digest's WATER line. pip install lupa.

    python tests/test_r38_water.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from lua_modules_util import module_src  # noqa: E402
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import test_waterworks as TW  # noqa: E402  (the waterworks' fake map)
import test_x_e3 as TE  # noqa: E402       (the pump stack and its power)

SRC = module_src("ai-water.lua")

# A big fake map: blocks share one dry designation table (rock under the
# surface at SURF, open sky above), so a 288x288x194 map costs little; the
# tests set tiles (SET) or whole blocks (FILL) of their own.
FAKE = r"""
local src, W, H, Z, SURF = ...
local env = setmetatable({}, {__index = _G})
local function mk(tt, shared)
  local des, t = {}, {}
  for x = 0, 15 do des[x] = {}; t[x] = {}
    for y = 0, 15 do des[x][y] = shared or {flow_size = 0}; t[x][y] = tt end end
  return {designation = des, tiletype = t, global_feature = -1}
end
local DRY = {flow_size = 0}
local AIR, ROCK = mk(0, DRY), mk(1, DRY)
local own = {}
local function bkey(bx, by, bz) return (bz * 1000 + by) * 1000 + bx end
local function blk(bx, by, bz)
  local k = bkey(bx, by, bz)
  if not own[k] then own[k] = mk(bz > SURF and 0 or 1) end
  return own[k]
end
function env.SET(x, y, z, fields, tt)
  local b = blk(x // 16, y // 16, z)
  local d = b.designation[x % 16][y % 16]
  for k, v in pairs(fields) do d[k] = v end
  if tt then b.tiletype[x % 16][y % 16] = tt end
end
-- a whole block of one liquid (one designation table for its 256 tiles)
function env.FILL(bx, by, bz, fields, gid)
  local d = {flow_size = 0}
  for k, v in pairs(fields) do d[k] = v end
  local b = mk(1, d)
  b.global_feature = gid or -1
  own[bkey(bx, by, bz)] = b
end
env.df = {tiletype = {OpenSpace = 0, attrs = {[0] = {material = 0, shape = 0}, [1] = {material = 1, shape = 1},
                                               [2] = {material = 2, shape = 2}, [3] = {material = 3, shape = 2},
                                               [4] = {material = 4, shape = 1}}},
          tiletype_material = {[0] = 'AIR', [1] = 'STONE', [2] = 'RIVER', [3] = 'BROOK', [4] = 'FROZEN_LIQUID'},
          tiletype_shape = {[0] = 'EMPTY', [1] = 'WALL', [2] = 'FLOOR'}}
env.SAVED = {}
env.CITIZENS = {{p = {40, 40, SURF - 2}}}
env.SC_MAP_UNLOADED = 'unloaded'
env.dfhack = {
  units = {getCitizens = function() return env.CITIZENS end,
           getPosition = function(u) return u.p[1], u.p[2], u.p[3] end},
  maps = {getTileSize = function() return W, H, Z end,
          getBlock = function(bx, by, bz)
            if bx < 0 or by < 0 or bz < 0 or bx * 16 >= W or by * 16 >= H or bz >= Z then return nil end
            return own[bkey(bx, by, bz)] or (bz > SURF and AIR or ROCK) end},
  persistent = {saveSiteData = function(k, v) env.SAVED[k] = v end,
                getSiteData = function(k, d) return env.SAVED[k] or d end},
  onStateChange = {},
}
env.RELOAD = function() assert(load(src, 'ai-water', 't', env))() end
env.RELOAD()
env.layer_names = function() return {[1] = {name = 'Cavern1', found = false}, [2] = {name = 'MagmaSea', found = false}} end
-- one slice, its CPU time measured inside Lua
env.TIMED = function(tick, seconds)
  local t = os.clock()
  local r = env.scan_step(tick, seconds)
  return r, os.clock() - t
end
return env
"""

LUA = LuaRuntime(unpack_returned_tuples=True)


def world(W=288, H=288, Z=194, SURF=150):
    return LUA.execute(FAKE, SRC, W, H, Z, SURF)


def F(**kw):
    return LUA.table_from(kw)


def river_far(env, x0=200):
    """A river 4 tiles wide down the whole map at x 200-203, one level under the ground (z 149)."""
    for y in range(0, 288):
        for x in range(x0, x0 + 4):
            env.SET(x, y, 149, F(flow_size=7, outside=True), 2)


def waters(r):
    return list(r.waters.values())


def run_slices(env, seconds=0.15, tick=5, before=None):
    times, calls = [], 0
    while True:
        if before:
            before(calls)
        r, t = env.TIMED(tick, seconds)
        times.append(t)
        calls += 1
        if r.done:
            return r, times
        assert r.ok and r.left >= 1, dict(r)


@test("survey: a river 160 tiles from the fort (beyond the old 72-tile box) found, flowing, with its reach")
def _():
    env = world()
    river_far(env)
    r = env.survey()
    assert r.ok and r.map.w == 288 and r.map_box.x2 == 287 and r.map_box.y2 == 287
    assert not [b for b in r.bodies.values() if b.kind == "river"]        # the near box (as before): none
    rivers = [b for b in waters(r) if b.flow == "flowing"]
    assert len(rivers) == 1, [b.kind for b in waters(r)]
    b = rivers[0]
    assert b.kind == "river" and b.tiles == 288 * 4 and b.nearest.x == 200 and b.nearest.z == 149
    assert b.d == 162 and b.reach == 161, (b.d, b.reach)                   # a stair down a level, 160 across
    assert r.nearest_flowing.kind == "river" and r.nearest_flowing.reach == 161
    assert r.waters_found == 1


@test("survey: an aquifer across the way: no reach, said why, the length all the same")
def _():
    env = world()
    river_far(env)
    for z in (148, 149):
        for y in range(0, 288):
            env.SET(130, y, z, F(water_table=True))     # (past the near box's blocks: x 0-127)
    r = env.survey()
    b = [b for b in waters(r) if b.flow == "flowing"][0]
    assert b.reach is None and b.aquifer and b.reach_through == 161, (b.reach, b.aquifer, b.reach_through)
    aq = [b for b in waters(r) if b.kind == "aquifer"]
    assert aq and aq[0].reach is None
    assert r.aquifer is None                                             # past the near box: only in the list


@test("survey: every slice of a 288x288x194 map within the budget (SLICE_SECONDS), the result the same as at once")
def _():
    env = world()
    river_far(env)
    whole = env.survey()
    r, times = run_slices(env, env.SLICE_SECONDS)
    assert max(times) <= env.SLICE_SECONDS, (max(times), len(times))
    assert len(times) >= 2
    a = sorted((b.kind, b.tiles, b.d, b.reach) for b in waters(whole))
    b = sorted((b.kind, b.tiles, b.d, b.reach) for b in waters(r))
    assert a == b, (a, b)
    # no time at all: one block a call, and it still finishes (a small map)
    env = world(W=64, H=64, Z=40, SURF=30)
    for y in range(64):
        env.SET(60, y, 29, F(flow_size=7, outside=True), 2)
    r, times = run_slices(env, 0)
    assert len(times) > 4 * 4 * 20 and [b for b in waters(r) if b.flow == "flowing"]


@test("survey: resumed across cycles and a reload of the module; dropped when the map is unloaded")
def _():
    env = world()
    river_far(env)
    r, _ = env.TIMED(5, 0.02)
    assert not r.done and env.scanning()
    env.RELOAD()                                     # DFHack reloads a changed script: the half-done survey stays
    assert env.scanning()
    left0 = r.left
    r, _ = env.TIMED(5, 0.02)
    assert not r.done and r.left <= left0
    env.dfhack.onStateChange["ai-water"](env.SC_MAP_UNLOADED)
    assert not env.scanning()
    r, times = run_slices(env, 0.15)
    assert [b for b in waters(r) if b.flow == "flowing"][0].reach == 161


@test("survey (the player, 10:48): magma by kind: a pipe beyond 72 tiles with its top, a cavern's pool opening it, the sea's top")
def _():
    env = world()
    for z in range(60, 141):                                   # a magma pipe's column at x250 y100, top at z 140
        env.SET(250, 100, z, F(flow_size=7, liquid_type=True, feature_local=True))
    for bx in (5, 6):                                          # a magma pool in Cavern1 (z 90)
        env.FILL(bx, 12, 90, F(flow_size=7, liquid_type=True, feature_global=True), 1)
    env.FILL(5, 11, 91, F(flow_size=0, feature_global=True), 1)       # the cavern's air over it
    for z in (20, 21, 22):                                     # the magma sea, its top at z 22
        for bx in range(0, 18, 4):
            env.FILL(bx, 2, z, F(flow_size=7, liquid_type=True, feature_global=True), 2)
    r = env.survey()
    mags = {b.magma: b for b in waters(r) if b.kind == "magma"}
    assert set(mags) == {"pipe", "cavern", "sea"}, set(mags)
    pipe = mags["pipe"]
    assert pipe.top.z == 140 and pipe.top.x == 250 and pipe.z1 == 60 and pipe.tiles == 81
    assert pipe.d > 72 and pipe.reach == (148 - 140) + 210 + 60, pipe.reach     # down 8, across 210 and 60
    assert pipe.opens_cavern is None
    cav = mags["cavern"]
    assert cav.cavern == "Cavern1" and cav.opens_cavern == "Cavern1" and cav.reach is None and cav.reach_through
    sea = mags["sea"]
    assert sea.top.z == 22 and r.magma_sea_top == 22 and sea.z1 == 20
    assert r.map_box.z1 == 20                                  # nothing scanned under the sea's top - 2
    assert r.magma is None                                     # the near box's magma (outside the deep layers): none


@test("survey: the report is capped, flowing water and each kind of magma always in it, nearest first")
def _():
    env = world()
    river_far(env)
    for i in range(30):                                        # 30 ponds, far apart
        x, y = 8 + (i % 6) * 40, 120 + (i // 6) * 32
        env.SET(x, y, 150, F(flow_size=3, outside=True, water_stagnant=True))
    for z in range(60, 141):
        env.SET(250, 250, z, F(flow_size=7, liquid_type=True, feature_local=True))
    r = env.survey()
    ws = waters(r)
    assert len(ws) == env.WATERS_MAX and r.waters_found == 32
    assert any(b.flow == "flowing" for b in ws) and any(b.kind == "magma" for b in ws)
    ds = [b.d for b in ws]
    assert ds == sorted(ds)
    assert {b.kind for b in ws} >= {"river", "pool", "magma"}


@test("survey (review 2): the near box counted by its blocks, as before 0.105.38 (a tile past the 72-tile box in its block counts)")
def _():
    env = world()
    env.SET(120, 40, 149, F(flow_size=7, outside=True), 2)        # x 120: past x2 = 112, in block 7 (x 112-127)
    env.SET(130, 40, 149, F(flow_size=7, outside=True), 2)        # block 8: not the near box's
    env.SET(121, 40, 140, F(water_table=True))
    r = env.survey()
    river = [b for b in r.bodies.values() if b.kind == "river"]
    assert len(river) == 1 and river[0].tiles == 1 and river[0].nearest.x == 120, [dict(b) for b in r.bodies.values()]
    assert r.aquifer.tiles == 1 and r.box.x2 == 112


@test("survey (review 4): the near box's result saved before the whole map is done, the old whole-map list kept meanwhile")
def _():
    env = world()
    env.SET(50, 40, 149, F(flow_size=7, outside=True), 2)         # a near river
    river_far(env)
    first, _ = run_slices(env, 0.15)
    assert first.done and not first.waters_pending
    n_before = len(waters(first))
    calls, near_seen = 0, None
    while True:
        r, _ = env.TIMED(9, 0.01)
        calls += 1
        saved = env.SAVED["ai-overseer/water"]
        if r.near_done and near_seen is None:
            near_seen = calls
            # (review 2nd 1) the survey's tick stays the last whole one's; near_tick is this one's
            assert saved.tick == 5 and saved.near_tick == 9 and saved.waters_pending is True
            assert [b for b in saved.bodies.values() if b.kind == "river"]          # the near result
            assert len(waters(saved)) == n_before                                   # the old list kept
        if r.done:
            break
    assert near_seen is not None and near_seen < calls, (near_seen, calls)
    saved = env.SAVED["ai-overseer/water"]
    assert saved.tick == 9 and not saved.waters_pending and saved.done


@test("survey (review 2nd 1): a whole-map pass cut off after the near save (unloaded) is begun again at once, not a season on")
def _():
    from planner_wells import _water_rules
    from planner import PLANNER_CONFIG
    env = world()
    river_far(env)
    while True:                                   # the first survey ever: cut off after its near save
        r, _ = env.TIMED(9, 0.01)
        if r.near_done:
            break
    env.dfhack.onStateChange["ai-water"](env.SC_MAP_UNLOADED)
    saved = env.SAVED["ai-overseer/water"]
    assert saved.waters_pending and saved.tick is None and saved.near_tick == 9
    w = {k: v for k, v in saved.items() if k in ("tick", "near_tick", "waters_pending", "ok")}
    props, notes = [], []
    _water_rules({"water": dict(w, bodies=[]), "date": {"year": 0, "tick": 20}}, PLANNER_CONFIG, props, notes)
    assert props and props[0].action["type"] == "survey_water", props
    # with a whole survey before (tick 5, a day ago): still due while the list is pending
    w = {"ok": True, "tick": 5, "near_tick": 9, "waters_pending": True, "bodies": []}
    props, notes = [], []
    _water_rules({"water": w, "date": {"year": 0, "tick": 1205}}, PLANNER_CONFIG, props, notes)
    assert props and "cut off" in props[0].reason, [p.reason for p in props]
    w.pop("waters_pending")
    props, notes = [], []
    _water_rules({"water": w, "date": {"year": 0, "tick": 1205}}, PLANNER_CONFIG, props, notes)
    assert not props
    r, _ = run_slices(env, 0.15, tick=30)        # resumed: the whole survey done
    assert r.done and not env.SAVED["ai-overseer/water"].waters_pending and env.SAVED["ai-overseer/water"].tick == 30


@test("survey (review 3): magma read by the feature's type (getGlobalInitFeature); unknown: a cavern's pool, the scan not cut")
def _():
    def magma_world(kinds):
        env = world(W=96, H=96, Z=200, SURF=150)
        env.layer_names = LUA.eval("function() return {} end")      # the layer names fail
        env.df.feature_type = F(magma_core_from_layer="MC", subterranean_from_layer="SUB",
                                underworld_from_layer="UW")
        env.dfhack.maps.getGlobalInitFeature = LUA.eval("""function(kinds) return function(gid)
            local k = kinds[gid]
            if not k then return nil end
            return {getType = function() return k end} end end""")(kinds)
        env.FILL(1, 1, 10, F(flow_size=7, liquid_type=True, feature_global=True), 2)
        env.FILL(1, 1, 30, F(flow_size=7, liquid_type=True, feature_global=True), 1)
        return env
    r = magma_world(LUA.table_from({1: "SUB", 2: "MC"})).survey()
    mags = sorted(b.magma for b in waters(r) if b.kind == "magma")
    assert mags == ["cavern", "sea"] and r.magma_sea_top == 10 and r.map_box.z1 == 8, (mags, r.magma_sea_top)
    r = magma_world(LUA.table_from({})).survey()                    # neither type nor name known
    mags = sorted(b.magma for b in waters(r) if b.kind == "magma")
    assert mags == ["cavern", "cavern"] and r.magma_sea_top is None and r.map_box.z1 == 0, mags


@test("survey (review 6): the reach estimate refuses a dug tile with an aquifer or other water beside it (not only on the way)")
def _():
    env = world()
    river_far(env)
    for x in range(130, 135):
        env.SET(x, 41, 149, F(water_table=True))                  # beside the tunnel at y 40, not on it
    b = [b for b in waters(env.survey()) if b.flow == "flowing"][0]
    assert b.reach is None and b.aquifer and b.reach_through == 161, (b.reach, b.aquifer)
    env = world()
    river_far(env)
    env.SET(130, 39, 149, F(flow_size=3))                         # an underground pool's tile beside it
    b = [b for b in waters(env.survey()) if b.flow == "flowing"][0]
    assert b.reach is None and "beside the way" in b.blocked, (b.reach, b.blocked)


@test("survey (review 13): a river frozen over (FROZEN_LIQUID under the sky) since a survey saw it: still a river for a wheel")
def _():
    env = world()
    river_far(env)
    r = env.scan_step(1, 1e9)
    assert r.done and r.river_seen and not r.frozen_river
    for y in range(0, 288):                                       # winter: the river is ice
        for x in range(200, 204):
            env.SET(x, y, 149, F(flow_size=0, outside=True), 4)
    r = env.scan_step(2, 1e9)
    assert r.done and r.frozen_river and r.river_seen and not [b for b in waters(r) if b.flow == "flowing"]
    assert [b for b in waters(r) if b.kind == "ice"]
    from planner_water import river_found
    assert river_found({"water": dict(r.items())})
    env = world()                                                 # ice never seen as a river: no river
    for y in range(0, 288):
        env.SET(200, y, 149, F(flow_size=0, outside=True), 4)
    r = env.survey()
    assert not r.frozen_river and not r.river_seen


# ---------------------------------------------------------------------------
# The works
# ---------------------------------------------------------------------------

T, L = TW.T, TW.L


def far_moat_world(river_x=150):
    """The moat's fort and gate (test_waterworks), no river near; a river at
    x 150 one level under the ground, found only by the whole-map survey."""
    env, W = TW.moat_world()
    for y in range(52, 58):
        W.tiles[f"40,{y},99"] = None
        W.tiles[f"40,{y},100"] = None
    for y in range(40, 70):
        W.set(river_x, y, 99, T(shape="FLOOR", material="RIVER", liquid=True, depth=7, outside=True))
        W.set(river_x, y, 100, T(shape="EMPTY", outside=True))
    W.survey = T(bodies=L(), map=T(w=192, h=192, z=200),
                 waters=L(T(kind="river", flow="flowing", tiles=30, d=100, reach=None,
                            nearest=T(x=river_x, y=54, z=99), z2=99)))
    return env, W


def plan_of(env, kind, **kw):
    r = TW.step(env, kind, dry_run=True, **kw)
    return r, (r.plan if r.ok else None)


def cells(lst):
    return sorted((c.x, c.y, c.z, c.text) for c in lst.values())


# the waterworks' walk groups (review 1, 10): an inside floor is the
# citizens' group 1, unless the test puts a tile in another (W.group)
GROUPS = TW.LUA.eval("""function(env)
  local W = env.W
  W.group = {}
  env.walk_group = function(x, y, z)
    local g = W.group[W.key(x, y, z)]
    if g then return g end
    local t = W.get(x, y, z)
    if (t.shape == 'FLOOR' or t.shape == 'STAIR_UPDOWN' or t.shape == 'STAIR_DOWN' or t.shape == 'STAIR_UP')
        and not t.outside and not t.liquid then return 1 end
    return 0
  end
  env.citizen_groups = function() return {[1] = true} end
  W.undesignated = {}
  env.undesignate = function(cs) for _, c in ipairs(cs) do table.insert(W.undesignated, c) end return #cs end
  env.LOGS = {}
  env.log_line = function(m) table.insert(env.LOGS, m) end
end""")


@test("moat (review 8): a far river never feeds a moat (the near river only, as before); nor does the brain ask for one")
def _():
    env, W = far_moat_world()
    r = TW.step(env, "moat")
    assert r.rejected and r.error == "no river or brook near the fort", dict(r)
    assert not list(W.designated.values())
    from planner_water import moat_wanted, near_river_found, river_found
    from planner import PLANNER_CONFIG
    s = TW.state(water={"bodies": [], "waters": [{"kind": "river", "flow": "flowing", "tiles": 40, "d": 150}]})
    assert river_found(s, PLANNER_CONFIG) and not near_river_found(s) and moat_wanted(s, PLANNER_CONFIG) is None
    props, _ = TW.run(s)
    assert not [p for p in props if p.action.get("kind") == "moat"], [p.action for p in props]
    assert moat_wanted(TW.state(), PLANNER_CONFIG)                     # the near river, as before


@test("moat: the near river still chosen when a far one is found too (the same plan as without the whole-map survey)")
def _():
    env, W = TW.moat_world()
    _, before = plan_of(env, "moat")
    env, W = TW.moat_world()
    W.survey.waters = L(T(kind="river", flow="flowing", tiles=30, d=100, nearest=T(x=150, y=54, z=99), z2=99))
    W.survey.map = T(w=192)
    _, after = plan_of(env, "moat")
    assert cells(before.dig) == cells(after.dig) and after.far is None and after.stages is None


def irr_far_world():
    env, W = TW.irrigation_world()
    W.tiles["70,60,94"] = None
    W.set(150, 60, 94, T(shape="FLOOR", liquid=True, depth=7))
    W.survey = T(bodies=L(), map=T(w=192), waters=L(T(kind="pool", flow="stagnant", underground=True, tiles=40,
                                                       d=92, salt_share=0, nearest=T(x=150, y=60, z=94))))
    GROUPS(env)
    return env, W


@test("irrigation far: the long tunnel staged, the dry run walked again before each segment, the next segment's rock rechecked")
def _():
    env, W = irr_far_world()
    r = TW.step(env, "irrigation")
    assert r.ok and r.stage == "planned", dict(r)
    p = W.saved["ai-overseer/waterworks"].works.irrigation.plan
    n = len(list(p.dig.values()))
    assert p.far and len(list(p.stages.values())) == (n + 39) // 40 >= 3
    r = TW.step(env, "irrigation")
    assert r.stage == "digging" and r.segment == 1 and len(list(W.designated.values())) == 40
    r = TW.step(env, "irrigation")
    assert r.waiting and "segment 1 of 3" in r.error, r.error
    W.dig_all(L(*[p.dig[i] for i in range(1, 41)]))
    # (review 11) an aquifer seeps beside the next segment's tunnel since: held, not designated
    nxt = p.dig[60]
    W.set(nxt.x, nxt.y + 1, nxt.z, T(aquifer=True))
    r = TW.step(env, "irrigation")
    assert r.stage == "held" and "before segment 2 of 3" in r.error and "aquifer beside" in r.error, r.error
    assert len(list(W.designated.values())) == 40
    # the same with the next segment's own tile turned to a cavern's, and a room dug beside it (the dry run)
    for fields, word in ((dict(feature=True), "a cavern at"), (dict(shape="FLOOR"), "dry run before segment 2")):
        env, W = irr_far_world()
        TW.step(env, "irrigation")
        TW.step(env, "irrigation")
        p = W.saved["ai-overseer/waterworks"].works.irrigation.plan
        W.dig_all(L(*[p.dig[i] for i in range(1, 41)]))
        c = p.dig[55]
        W.set(c.x, c.y + (1 if "shape" in fields else 0), c.z, T(**fields))
        r = TW.step(env, "irrigation")
        assert r.stage == "held" and word in r.error, (word, r.error)
    # all well: the next segment designated
    env, W = irr_far_world()
    TW.step(env, "irrigation")
    TW.step(env, "irrigation")
    p = W.saved["ai-overseer/waterworks"].works.irrigation.plan
    W.dig_all(L(*[p.dig[i] for i in range(1, 41)]))
    r = TW.step(env, "irrigation")
    assert r.waiting and "segment 2 of 3 designated" in r.error and len(list(W.designated.values())) == 80, r.error


@test("irrigation far (review 11): retired half-dug: the designations not dug called off, the tunnel recorded and logged")
def _():
    env, W = irr_far_world()
    TW.step(env, "irrigation")
    TW.step(env, "irrigation")
    p = W.saved["ai-overseer/waterworks"].works.irrigation.plan
    W.dig_all(L(*[p.dig[i] for i in range(1, 31)]))                   # 30 of segment 1's 40 dug
    r = TW.step(env, "irrigation", retire=True, why="held too long")
    wk = W.saved["ai-overseer/waterworks"].works.irrigation
    assert wk.stage == "retired" and wk.half_dug.dug == 30 and wk.half_dug.called_off == 10, dict(wk.half_dug)
    assert sorted((c.x, c.y, c.z) for c in W.undesignated.values()) == sorted(
        (p.dig[i].x, p.dig[i].y, p.dig[i].z) for i in range(31, 41))
    last = p.dig[30]
    assert (wk.half_dug.last.x, wk.half_dug.last.y) == (last.x, last.y)
    assert env.LOGS[1].startswith("irrigation retired half-dug: 30 of"), env.LOGS[1]


@test("far caps: water_far_reach (50: too near; 0: far sources off) and water_job_max (60: too small; 0: no far work)")
def _():
    for kw, word in ((dict(far_reach=50), None), (dict(far_reach=0), None), (dict(job_max=60), "(60 at most)"),
                     (dict(job_max=0), None)):
        env, W = irr_far_world()
        r = TW.step(env, "irrigation", **kw)
        assert r.rejected, (kw, dict(r))
        if word:
            assert word in r.error, r.error
    env, W = irr_far_world()
    assert TW.step(env, "irrigation", far_reach=-1).ok          # below 0: the map's width (the default)
    from planner_water import far_args, far_on
    from planner import PLANNER_CONFIG
    assert far_args(PLANNER_CONFIG) == {} and far_on(PLANNER_CONFIG)
    assert far_args(dict(PLANNER_CONFIG, water_far_reach=0)) == {"far_reach": 0}
    assert far_args(dict(PLANNER_CONFIG, water_job_max=0)) == {"job_max": 0}
    assert not far_on(dict(PLANNER_CONFIG, water_far_reach=0)) and not far_on(dict(PLANNER_CONFIG, water_job_max=0))
    # the bridge's defaults are the brain's
    src = (ROOT / "lua" / "ai-waterworks.lua").read_text(encoding="utf-8")
    assert "FAR_REACH = nil" in src and f"FAR_JOB_MAX = {PLANNER_CONFIG['water_job_max']}" in src
    assert f"DIG_SEGMENT = {PLANNER_CONFIG['water_dig_segment']}" in src and PLANNER_CONFIG["water_far_reach"] == -1


def far_power_world():
    env, W = TE.stack_world(river=False)
    for x in range(150, 153):
        for y in range(45, 76):
            W.set(x, y, 99, TE.T(shape="FLOOR", material="RIVER", liquid=True, depth=7, outside=True))
            W.set(x, y, 100, TE.T(shape="EMPTY", outside=True))
    W.survey = TE.T(bodies=TE.L(TE.T(kind="pool", tiles=1, nearest=TE.T(x=60, y=60, z=86))),
                    map=TE.T(w=192), waters=TE.L(TE.T(kind="river", flow="flowing", tiles=93, d=90,
                                                      nearest=TE.T(x=150, y=60, z=99))))
    return env, W


@test("power: a far river's water wheel when none is near (a long axle run, more wheels for it), not a windmill")
def _():
    env, W = far_power_world()
    r = TE.step(env, "power", dry_run=True)
    assert r.ok and r.plan.source == "wheel" and r.plan.far and r.plan.far.kind == "axles", dict(r)
    p = r.plan
    builds = TE.tolist(p.builds)
    wheel = [b for b in builds if b.kind == "WaterWheel"][0]
    assert 149 <= wheel.cx <= 153 and p.far.d > 60
    assert p.have >= p.need and p.wheels >= 2, (p.need, p.have, p.wheels)
    # the near river still wins when there is one
    env, W = TE.stack_world()
    near = TE.step(env, "power", dry_run=True).plan
    env, W = TE.stack_world()
    W.survey.waters = TE.L(TE.T(kind="river", flow="flowing", tiles=93, d=90, nearest=TE.T(x=150, y=60, z=99)))
    again = TE.step(env, "power", dry_run=True).plan
    assert again.far is None and [b.kind for b in TE.tolist(near.builds)] == [b.kind for b in TE.tolist(again.builds)]
    assert [(b.x, b.y, b.z) for b in TE.tolist(near.builds)] == [(b.x, b.y, b.z) for b in TE.tolist(again.builds)]


@test("power (review 5): the far wheel's search within its time (else a clean 'try later', no windmill) and its centres capped")
def _():
    env, W = far_power_world()
    env.WHEEL_FAR_SECONDS = -1                        # out of time at once
    r = TE.step(env, "power")
    assert r.rejected and r.later and "ran out of time" in r.error and "tried again later" in r.error, dict(r)
    ref = W.saved["ai-overseer/waterworks"].refused.power
    assert ref.later is True
    env, W = far_power_world()
    env.WHEEL_FAR_CENTRES = 0                         # no centre tried: a plain refusal
    r = TE.step(env, "power", dry_run=True)
    assert r.rejected and not r.later, dict(r)
    # the brain: a search cut short is tried again in days, not weeks
    s = TW.state(waterworks={"works": {}, "refused": {"moat": {"tick": 10 * 403200 - 4 * 1200, "why": "x", "later": True}}})
    props, _ = TW.run(s)
    assert [p for p in props if p.action.get("kind") == "moat"]
    s["waterworks"]["refused"]["moat"].pop("later")
    props, _ = TW.run(s)
    assert not [p for p in props if p.action.get("kind") == "moat"]


@test("irrigation: still water 90 tiles off reached by a long tunnel from a room under the fort, staged")
def _():
    env, W = TW.irrigation_world()
    W.tiles["70,60,94"] = None
    W.set(150, 60, 94, T(shape="FLOOR", liquid=True, depth=7))
    W.survey = T(bodies=L(), map=T(w=192), waters=L(T(kind="pool", flow="stagnant", underground=True, tiles=40,
                                                       d=92, salt_share=0, nearest=T(x=150, y=60, z=94))))
    r, p = plan_of(env, "irrigation")
    assert p is not None, dict(r)
    assert p.far and p.far.kind == "tunnel" and p.far.d > 40 and p.stages
    assert p.room.x1 <= 89 and p.plug.x == 149, (p.room.x1, p.plug.x, p.plug.y)
    # near water still first (the same plan as before)
    env, W = TW.irrigation_world()
    _, before = plan_of(env, "irrigation")
    env, W = TW.irrigation_world()
    W.survey = T(bodies=L(), map=T(w=192), waters=L(T(kind="pool", flow="stagnant", underground=True, tiles=40,
                                                       d=92, salt_share=0, nearest=T(x=150, y=60, z=94))))
    _, after = plan_of(env, "irrigation")
    assert cells(before.dig) == cells(after.dig) and after.far is None


def magma_far_world(pipe_cavern=None):
    """The fort at z 90 (a floor round its middle); no near magma; a pipe at
    x150 with its top at z 80, and the magma sea's top at z 40. pipe_cavern:
    a cavern's wall across the pipe's tunnel to the fort (x 100, z 90)."""
    env = TW.LUA.execute(TW.FAKE, TW.SRC)
    W = env.W
    GROUPS(env)
    for x in range(50, 71):
        for y in range(50, 71):
            W.set(x, y, 90, T(shape="FLOOR"))
    W.citizens = L(T(x=60, y=60, z=90), T(x=61, y=60, z=92))
    W.set(150, 60, 80, T(shape="FLOOR", liquid=True, magma=True, depth=7, material="STONE", feature=True))
    W.set(60, 120, 40, T(shape="FLOOR", liquid=True, magma=True, depth=7, material="STONE", feature=True))
    if pipe_cavern:
        for y in range(0, 192):
            W.set(100, y, 90, T(feature=True))
    pipe = T(kind="magma", magma="pipe", tiles=40, d=110, reach=100, top=T(x=150, y=60, z=80),
             nearest=T(x=150, y=60, z=80))
    sea = T(kind="magma", magma="sea", tiles=900, d=60, reach=110, top=T(x=60, y=120, z=40),
            nearest=T(x=60, y=120, z=40))
    W.survey = T(bodies=L(), map=T(w=192), waters=L(sea, pipe), middle=T(x=60, y=60, z_low=90))
    return env, W


@test("magma (the player, 10:48): the workshop takes the far pipe over the nearer sea, its stair joined to the fort by a tunnel")
def _():
    env, W = magma_far_world()
    r, p = plan_of(env, "magma", shop="MagmaForge")
    assert p is not None, dict(r)
    assert p.source.magma == "pipe" and p.gate.z == 80 and p.room.z == 81, dict(p.source)
    assert p.access and p.access > 50 and p.stages                     # the tunnel to the fort, dug in segments
    assert p.source.opens_cavern is None
    tun = [c for c in p.dig.values() if c.z == 90 and c.text == "d"]
    assert tun and min(c.x for c in tun) <= 72
    # (review 9) a cavern on the planned dig (not the survey's estimate): only with the cavern switch's leave; else the sea
    env, W = magma_far_world(pipe_cavern=True)
    r, p = plan_of(env, "magma", shop="MagmaForge")
    assert p is not None and p.source.magma == "sea", dict(r)
    env, W = magma_far_world(pipe_cavern=True)
    W.survey.waters = L(W.survey.waters[2])
    r = TW.step(env, "magma", shop="MagmaForge")
    assert r.rejected and "open a cavern at x100" in r.error and "cavern switch" in r.error, r.error
    r, p = plan_of(env, "magma", shop="MagmaForge", open_caverns=True)
    assert p is not None and p.source.opens_cavern == "a cavern", dict(r)
    assert [c for c in p.dig.values() if c.x == 100 and c.z == 90]        # the cavern's wall dug through
    # the survey's estimate alone (it said the pipe's way opens Cavern1) no longer refuses it: the dig is walked
    env, W = magma_far_world()
    pipe = W.survey.waters[2]
    pipe.opens_cavern, pipe.reach, pipe.reach_through = "Cavern1", None, 100
    r, p = plan_of(env, "magma", shop="MagmaForge")
    assert p is not None and p.source.magma == "pipe" and p.source.opens_cavern is None, dict(r)
    # a body the survey found blocked is left out; magma deeper than a stair reaches too
    env, W = magma_far_world()
    W.survey.waters[2].blocked = "other water on the way"
    r, p = plan_of(env, "magma", shop="MagmaForge")
    assert p is not None and p.source.magma == "sea"
    env, W = magma_far_world()
    W.survey.waters = L(T(kind="magma", magma="sea", tiles=900, d=60, reach=110, top=T(x=60, y=120, z=20),
                          nearest=T(x=60, y=120, z=20)))
    r = TW.step(env, "magma", shop="MagmaForge")
    assert r.rejected and "too deep for a stair" in r.error, r.error
    # the near box's magma (as before) first
    env, W = TW.magma_world()
    _, before = plan_of(env, "magma", shop="MagmaForge")
    env, W = TW.magma_world()
    W.survey.waters = magma_far_world()[1].survey.waters
    _, after = plan_of(env, "magma", shop="MagmaForge")
    assert cells(before.dig) == cells(after.dig) and after.source is None


@test("magma (review 1): the tunnel to the fort stops only at a seen fort floor the dwarves walk on; water beside it refuses it")
def _():
    # an open floor on the way that is no fort's (not the citizens' walk group): refused, not met
    env, W = magma_far_world()
    W.survey.waters = L(W.survey.waters[2])
    for y in range(0, 192):
        W.set(110, y, 90, T(shape="FLOOR"))
        W.group[W.key(110, y, 90)] = 7
    r = TW.step(env, "magma", shop="MagmaForge")
    assert r.rejected and "other than solid rock at x110" in r.error, r.error
    # a hidden floor in the citizens' group: the same
    env, W = magma_far_world()
    W.survey.waters = L(W.survey.waters[2])
    for y in range(0, 192):
        W.set(110, y, 90, T(shape="FLOOR", hidden=True))
    r = TW.step(env, "magma", shop="MagmaForge")
    assert r.rejected and "x110" in r.error, r.error
    # a cavern's open floor on the way: refused (the cavern switch), not taken for the fort
    env, W = magma_far_world()
    W.survey.waters = L(W.survey.waters[2])
    for y in range(0, 192):
        W.set(110, y, 90, T(shape="FLOOR", feature=True))
    r = TW.step(env, "magma", shop="MagmaForge")
    assert r.rejected and "open a cavern at x110" in r.error, r.error
    # (review 6) an aquifer beside the tunnel (not on it)
    env, W = magma_far_world()
    W.survey.waters = L(W.survey.waters[2])
    for x in range(71, 150):
        for y in (57, 59, 61):
            W.set(x, y, 90, T(aquifer=True))
    r = TW.step(env, "magma", shop="MagmaForge")
    assert r.rejected and "an aquifer beside the dug tile" in r.error, r.error


@test("brain (review 8/9): magma too deep for a stair left out; Never/Always/AI decides on a cavern's way; a refusal waits a season")
def _():
    from planner_water import magma_choice
    from planner import PLANNER_CONFIG
    pipe = {"kind": "magma", "magma": "pipe", "d": 150, "reach": 160, "top": {"z": 80}}
    deep_sea = {"kind": "magma", "magma": "sea", "d": 80, "reach": 90, "top": {"z": 20}}
    sea = {"kind": "magma", "magma": "sea", "d": 80, "reach": 90, "top": {"z": 40}}
    cav_pipe = {"kind": "magma", "magma": "pipe", "d": 100, "opens_cavern": "Cavern1", "reach_through": 90, "top": {"z": 70}}

    def s(ws, mode="never", magma=None):
        return {"water": {"waters": ws, "magma": magma or {}, "middle": {"z_low": 90}},
                "settings": {"open_caverns": mode}}
    assert magma_choice(s([deep_sea]), PLANNER_CONFIG) == ("", False)          # 90 - 21 = 69 levels > 60
    assert magma_choice(s([deep_sea, pipe]), PLANNER_CONFIG) == ("pipe", False)
    assert magma_choice(s([sea], magma={"top_nearest": {"x": 1, "z": 10}}), PLANNER_CONFIG) == ("sea", False)
    assert magma_choice(s([dict(pipe, blocked="magma on the way")]), PLANNER_CONFIG) == ("", False)
    # AI decides: a cavern's way only when no other magma can be reached
    assert magma_choice(s([cav_pipe, sea], "ai"), PLANNER_CONFIG) == ("sea", False)
    assert magma_choice(s([cav_pipe], "ai"), PLANNER_CONFIG) == ("", False)          # (2nd 2) no soldiers ready
    armed = s([cav_pipe], "ai")
    armed["military"] = {"squads": [{"members": 9, "power": {"armed": 8}}]}
    assert magma_choice(armed, PLANNER_CONFIG) == ("pipe", True)
    armed["settings"]["traits"] = {"caution": 100}                                    # Caution wants more
    armed["military"]["squads"][0]["power"]["armed"] = PLANNER_CONFIG["unfound_cavern_soldiers"]
    assert magma_choice(armed, PLANNER_CONFIG) == ("", False)
    found = s([dict(cav_pipe, magma="cavern", cavern="Cavern1", cavern_found=True)], "ai")   # found: soldiers all the same
    assert magma_choice(found, PLANNER_CONFIG) == ("", False)
    found["military"] = {"squads": [{"members": 9, "power": {"armed": 9}}]}
    assert magma_choice(found, PLANNER_CONFIG) == ("cavern", True)
    assert magma_choice(s([cav_pipe], "never"), PLANNER_CONFIG) == ("", False)
    assert magma_choice(s([cav_pipe, sea], "always"), PLANNER_CONFIG) == ("pipe", True)
    assert magma_choice(s([pipe], "never"), dict(PLANNER_CONFIG, water_far_reach=0)) == ("", False)
    # a refused magma workshop waits a season (not the 4 weeks of the other works)
    st = TW.state(settings={"traits": {}}, buildings={"workshops": {"MetalsmithsForge": 1}, "furnaces": {}, "other": {}},
                  water={"bodies": [], "waters": [pipe], "middle": {"z_low": 90}}, map={"layers": []},
                  waterworks={"works": {}, "refused": {"magma:MagmaForge": {"tick": 10 * 403200 - 40 * 1200, "why": "x"}}})
    props, _ = TW.run(st)
    assert not [p for p in props if p.action.get("kind") == "magma"], [p.action for p in props]
    st["waterworks"]["refused"]["magma:MagmaForge"]["tick"] = 10 * 403200 - 90 * 1200
    props, _ = TW.run(st)
    assert [p for p in props if p.action.get("kind") == "magma"], [p.action for p in props]


@test("pump: the near pool first; another underground pool under the fort tried when it won't do")
def _():
    env, W = TW.pump_world()
    _, before = plan_of(env, "pump")
    env, W = TW.pump_world()
    W.survey.waters = L(T(kind="pool", flow="stagnant", underground=True, tiles=5, d=40, salt_share=0,
                          nearest=T(x=10, y=10, z=80)))
    _, after = plan_of(env, "pump")
    assert before is not None and cells(before.dig) == cells(after.dig) and after.far is None


# ---------------------------------------------------------------------------
# The brain
# ---------------------------------------------------------------------------

@test("brain: a far river counts as found; the far settings ride on the actions only off their defaults")
def _():
    from planner_water import river_found, far_args
    from planner import PLANNER_CONFIG
    s = {"water": {"bodies": [], "waters": [{"kind": "river", "flow": "flowing", "tiles": 40, "d": 150}]}}
    assert river_found(s) and not river_found({"water": {"bodies": [], "waters": []}})
    assert far_args(PLANNER_CONFIG) == {}
    cfg = dict(PLANNER_CONFIG, water_far_reach=120, water_dig_segment=25)
    assert far_args(cfg) == {"far_reach": 120, "segment": 25}
    for k in ("well_shore_reach", "cistern_tunnel_max", "water_far_reach", "water_job_max", "water_dig_segment"):
        assert k in PLANNER_CONFIG, k


@test("brain: the magma workshop's magma: the near box's first, then a pipe before the sea; a cavern only by the switch")
def _():
    from planner_water import magma_choice
    from planner import PLANNER_CONFIG
    pipe = {"kind": "magma", "magma": "pipe", "d": 150, "reach": 160, "top": {"z": 80}}
    sea = {"kind": "magma", "magma": "sea", "d": 80, "reach": 90, "top": {"z": 20}}
    cav = {"kind": "magma", "magma": "cavern", "d": 30, "opens_cavern": "Cavern1", "reach_through": 30}

    def s(ws, mode="never", magma=None):
        return {"water": {"waters": ws, "magma": magma or {}}, "settings": {"open_caverns": mode}}
    assert magma_choice(s([sea, pipe]), PLANNER_CONFIG) == ("pipe", False)
    assert magma_choice(s([sea]), PLANNER_CONFIG) == ("sea", False)
    assert magma_choice(s([cav]), PLANNER_CONFIG) == ("", False)
    assert magma_choice(s([cav], "always"), PLANNER_CONFIG) == ("cavern", True)
    assert magma_choice(s([sea], magma={"top_nearest": {"x": 1}}), PLANNER_CONFIG) == ("near", False)


@test("digest: the WATER line names the nearest flowing water and the magma's kinds; a default for an older survey")
def _():
    import digest
    s = {"water": {"waters": [
        {"kind": "pond", "flow": "stagnant", "d": 20, "tiles": 30},
        {"kind": "river", "flow": "flowing", "d": 162, "reach": 161, "tiles": 1152},
        {"kind": "brook", "flow": "flowing", "d": 300, "tiles": 50, "aquifer": True},
        {"kind": "magma", "magma": "pipe", "d": 200, "top": {"z": 140}},
        {"kind": "magma", "magma": "cavern", "d": 90, "opens_cavern": "Cavern1"}], "waters_found": 7},
         "map": {"elevation_offset": -100}}
    line = digest.water_line(s)
    assert line.startswith("WATER nearest flowing: river 162 tiles off, reach 161"), line
    assert "5 bodies listed of 7" in line and "pipe top 40" in line and "cavern (opens Cavern1)" in line, line
    s = {"water": {"waters": [{"kind": "lake", "flow": "stagnant", "d": 9}]}}
    assert "none on the map" in digest.water_line(s)
    old = digest.normalize({"water": {"bodies": [], "tick": 5}})
    assert old["water"]["waters"] == [] and old["water"]["waters_found"] == 0 and digest.water_line(old) == ""
    bad = digest.normalize({"water": {"error": "boom"}})
    assert bad["water"] == {"error": "boom"} and bad["_errors"]["water"] == "boom"
    assert "WATER nearest flowing" in digest.digest(digest.normalize(dict(s)))


@test("cistern: the tunnel's reach grows to a far still pool only when none is near enough (the map's width at most)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    src = (ROOT / "lua" / "ai-builder-cistern.lua").read_text(encoding="utf-8")
    env = lua.eval("""function(src)
      local env = setmetatable({}, {__index = _G})
      env.SURVEY = nil
      env.reqscript = function(n) return {last = function() return env.SURVEY end} end
      env.site_get = function() return {} end
      env.site_put = function() end
      assert(load(src, 'ai-builder-cistern', 't', env))()
      return env end""")(src)
    far = lua.table_from({"kind": "pool", "flow": "stagnant", "underground": True, "salt_share": 0, "d": 130,
                          "reach": 140, "nearest": lua.table_from({"x": 1, "y": 2, "z": 3, "d": 130})})
    env.SURVEY = lua.table_from({"bodies": lua.table_from([]), "map": lua.table_from({"w": 288}),
                                 "waters": lua.table_from([far])})
    assert env.cistern_far_len(70) == 140 + env.CISTERN_HALF + 4
    env.CISTERN_FAR_REACH = 100                       # the brain's water_far_reach
    assert env.cistern_far_len(70) is None
    env.CISTERN_FAR_REACH = None
    near = lua.table_from({"kind": "pool", "tiles": 9, "nearest": lua.table_from({"x": 1, "y": 2, "z": 3, "d": 40})})
    env.SURVEY.bodies = lua.table_from([near])         # still water near enough: the asked reach stands
    assert env.cistern_far_len(70) is None
    env.SURVEY = lua.table_from({"bodies": lua.table_from([])})     # an older survey: nothing changes
    assert env.cistern_far_len(70) is None


@test("cistern (review 7): the tunnel's next stretch takes solid rock or a dry dug tile only, never water, a cavern or an aquifer")
def _():
    import re
    lua = LuaRuntime(unpack_returned_tuples=True)
    src = (ROOT / "lua" / "ai-builder-cistern.lua").read_text(encoding="utf-8")
    wells = (ROOT / "lua" / "ai-builder-wells.lua").read_text(encoding="utf-8")
    solid = re.search(r"^function solid_rock\(t\).*?^end", wells, re.S | re.M).group(0)
    env = lua.eval("""function(src, solid)
      local env = setmetatable({}, {__index = _G})
      env.reqscript = function(n) return {last = function() return nil end} end
      env.site_get = function() return {} end
      env.site_put = function() end
      env.is_tree = function(t) return false end
      assert(load(src, 'ai-builder-cistern', 't', env))()
      assert(load(solid, 'solid_rock', 't', env))()
      return env end""")(src, solid)
    t = lambda **kw: lua.table_from(dict({"material": "STONE"}, **kw))
    ok = env.tunnel_stretch_ok
    assert ok(t(shape="WALL")) and ok(t(shape="FLOOR"))
    for bad in (t(shape="FLOOR", liquid=True), t(shape="EMPTY", liquid=True, depth=7), t(shape="FLOOR", feature=True),
                t(shape="FLOOR", aquifer=True), t(shape="WALL", aquifer=True), t(shape="WALL", feature=True),
                t(shape="WALL", liquid=True), t(shape="EMPTY"), t(shape="FLOOR", outside=True), None):
        assert not ok(bad), dict(bad) if bad else bad
    assert "tunnel_stretch_ok(t)" in src and "t.shape ~= 'WALL' or solid_rock(t)" not in src


@test("pump far (review 10): another pool's stack only with its reservoir where the dwarves walk; staged and capped")
def _():
    def far_pump_world():
        env, W = TW.pump_world()
        GROUPS(env)
        W.tiles["60,60,86"] = None
        W.set(150, 60, 86, T(shape="FLOOR", liquid=True, depth=7))
        for x in range(140, 165):                                  # an outpost's floor over it
            for y in range(45, 76):
                W.set(x, y, 90, T(shape="FLOOR"))
        W.survey = T(bodies=L(), map=T(w=192), waters=L(T(kind="pool", flow="stagnant", underground=True, tiles=1,
                                                           d=90, salt_share=0, nearest=T(x=150, y=60, z=86))))
        return env, W
    env, W = far_pump_world()
    r, p = plan_of(env, "pump")
    assert p is not None and p.far and p.far.kind == "pool", dict(r)
    assert 140 <= p.reservoir.x <= 164
    env, W = far_pump_world()
    for k in list(W.tiles.keys()):
        x, y, z = map(int, k.split(","))
        if z == 90 and x >= 140:
            W.group[k] = 5                                         # walled off from the fort
    r = TW.step(env, "pump", dry_run=True)
    assert r.rejected and "not where the dwarves can walk" in r.error, r.error
    env, W = far_pump_world()
    r = TW.step(env, "pump", dry_run=True, job_max=10)
    assert r.rejected and "(10 at most)" in r.error, r.error
    env, W = far_pump_world()
    r = TW.step(env, "pump", dry_run=True, job_max=0)
    assert r.rejected, dict(r)


@test("survey (review 2nd 3a): the way to the magma sea through the sea's own layer is no block; a pipe's still is")
def _():
    env = world()
    for z in (20, 21, 22):                                     # the sea under the fort's middle (block 2, 2)
        env.FILL(2, 2, z, F(flow_size=7, liquid_type=True, feature_global=True), 2)
    for z in (23, 24, 25):                                     # its layer's dry rock over it
        env.FILL(2, 2, z, F(flow_size=0, feature_global=True), 2)
    r = env.survey()
    sea = [b for b in waters(r) if b.kind == "magma" and b.magma == "sea"][0]
    assert sea.reach and not sea.blocked, (sea.reach, sea.blocked)


@test("survey (review 2nd 12): ice where no river ran before (a glacier, a frozen lake) is no frozen river")
def _():
    env = world()
    river_far(env)
    assert env.scan_step(1, 1e9).river_seen
    for y in range(0, 288):                                       # the river dries up; ice far from it
        for x in range(200, 204):
            env.SET(x, y, 149, F(flow_size=0, outside=False), 1)
        env.SET(20, y, 149, F(flow_size=0, outside=True), 4)
    r = env.scan_step(2, 1e9)
    assert not r.frozen_river and not r.river_seen and [b for b in waters(r) if b.kind == "ice"]


def sea_world():
    env, W = magma_far_world()
    W.survey.waters = L(W.survey.waters[1])                       # the sea alone
    return env, W


@test("magma (review 2nd 3b): a sea plan dug through all its segments; the sea's own layer under the room no cavern")
def _():
    env, W = sea_world()
    r = TW.step(env, "magma", shop="MagmaForge")
    assert r.ok and r.stage == "planned", dict(r)
    wk = W.saved["ai-overseer/waterworks"].works["magma:MagmaForge"]
    p = wk.plan
    assert p.deep_z == 41 and p.source.magma == "sea" and p.stages
    nst = len(list(p.stages.values()))
    assert nst >= 2
    # the sea's layer flag on the last segment's tiles at the magma's level (as the game sets it)
    last = p.stages[nst]
    for i in range(last[1], last[2] + 1):
        c = p.dig[i]
        if c.z <= 41:
            W.set(c.x, c.y, c.z, T(feature=True, feature_global=True))
    TW.step(env, "magma", shop="MagmaForge")
    for k in range(1, nst + 1):
        st = p.stages[k]
        W.dig_all(L(*[p.dig[i] for i in range(st[1], st[2] + 1)]))
        r = TW.step(env, "magma", shop="MagmaForge")
        assert not (r.stage == "held"), r.error
    assert r.stage == "building", dict(r)
    # the same flag on a pipe's plan: a cavern, held
    env, W = magma_far_world()
    TW.step(env, "magma", shop="MagmaForge")
    p = W.saved["ai-overseer/waterworks"].works["magma:MagmaForge"].plan
    assert p.deep_z is None
    c = p.dig[p.stages[2][1]]
    W.set(c.x, c.y, c.z, T(feature=True, feature_global=True))
    TW.step(env, "magma", shop="MagmaForge")
    W.dig_all(L(*[p.dig[i] for i in range(1, p.stages[1][2] + 1)]))
    r = TW.step(env, "magma", shop="MagmaForge")
    assert r.stage == "held" and "a cavern at" in r.error, r.error


@test("far checks (review 2nd 4, 9): the work's own source beside a dug tile allowed, other liquid not; a pipe is no cavern")
def _():
    env, W = irr_far_world()
    W.set(11, 11, 50, T(shape="FLOOR", liquid=True, depth=7))
    p = TW.LUA.table_from({"dig": L(T(x=10, y=10, z=50, text="d")), "src": T(x=12, y=12, z=50)})
    assert env.far_route_check(p, False) is None and env.next_segment_bad(p, p.dig) is None
    W.set(11, 11, 50, T(magma=True))                               # magma beside a water work: other liquid
    assert "magma beside" in env.far_route_check(p, False)
    assert "magma beside" in env.next_segment_bad(p, p.dig)
    W.set(11, 11, 50, T(magma=False))
    p.src = None                                                   # no source known: any liquid refuses
    assert "water beside" in env.far_route_check(p, False)
    # a local feature (a pipe's) on the dig: no cavern (the switch does not let it through either)
    W.tiles["11,11,50"] = None
    W.set(10, 10, 50, T(feature=True, feature_local=True, feature_global=False))
    why = env.far_route_check(p, True)
    assert why and "magma pipe or a pool" in why and "cavern" not in why, why
    assert "magma pipe or a pool" in env.next_segment_bad(p, p.dig)
    W.set(10, 10, 50, T(feature=True, feature_local=False, feature_global=True))
    assert env.far_route_check(p, True) is None and "open a cavern" in env.far_route_check(p, False)[0]


@test("retire (review 2nd 5): dig jobs on the undug plan tiles removed, the floodgate floor's dig called off; all dug: no half-dug")
def _():
    env, W = irr_far_world()
    TW.step(env, "irrigation")
    TW.step(env, "irrigation")
    p = W.saved["ai-overseer/waterworks"].works.irrigation.plan
    W.dig_all(L(*[p.dig[i] for i in range(1, 31)]))
    W.jobs = L()
    TW.LUA.execute("local env = ...; env.cancel_dig_jobs = function(cs) for _, c in ipairs(cs) do table.insert(env.W.jobs, c) end return #cs end", env)
    TW.step(env, "irrigation", retire=True)
    wk = W.saved["ai-overseer/waterworks"].works.irrigation
    assert wk.half_dug.jobs_removed == 10 and len(list(W.jobs.values())) == 10
    # every segment dug, the floodgate floor's dig designated, then retired: that dig called off, no half-dug
    env, W = irr_far_world()
    TW.step(env, "irrigation")
    TW.step(env, "irrigation")
    wk = W.saved["ai-overseer/waterworks"].works.irrigation
    p = wk.plan
    nst = len(list(p.stages.values()))
    W.dig_all(p.dig)
    wk.seg = nst
    p.dig2 = L(T(x=p.gate.x, y=p.gate.y, z=p.gate.z - 1, text="z"))
    wk.dig2 = True
    TW.step(env, "irrigation", retire=True)
    wk = W.saved["ai-overseer/waterworks"].works.irrigation
    assert wk.stage == "retired" and wk.half_dug is None and not list(env.LOGS.values())
    assert [(c.x, c.y, c.z) for c in W.undesignated.values()] == [(p.gate.x, p.gate.y, p.gate.z - 1)]
    # the game's hook: only the dig jobs on these tiles
    env2 = TW.LUA.execute(TW.FAKE, TW.SRC)
    removed = TW.LUA.execute("""
      local env = ...
      local jobs = {{job_type = 1, pos = {x = 1, y = 1, z = 1}}, {job_type = 1, pos = {x = 2, y = 2, z = 2}},
                    {job_type = 9, pos = {x = 1, y = 1, z = 1}}}
      local head = {}
      local link = head
      for _, j in ipairs(jobs) do link.next = {item = j}; link = link.next end
      local gone = {}
      env.df = {global = {world = {jobs = {list = head}}}, job_type = {[1] = 'Dig', [9] = 'StoreItemInStockpile'}}
      env.dfhack = {job = {removeJob = function(j) table.insert(gone, j) return true end}}
      local n = env.cancel_dig_jobs({{x = 1, y = 1, z = 1}})
      return n, #gone, gone[1] == jobs[1]
    """, env2)
    assert tuple(removed) == (1, 1, True), removed


@test("brain (review 2nd 6, 7, 8): no open_caverns for the near magma; water_job_max 0 stops far tunnels and banks; floats; power's cfg")
def _():
    from planner_water import _int, far_args, power_wanted
    from planner_wells import _far_args
    from planner import PLANNER_CONFIG
    st = TW.state(settings={"traits": {}, "open_caverns": "always"},
                  buildings={"workshops": {"MetalsmithsForge": 1}, "furnaces": {}, "other": {}},
                  water={"bodies": [], "magma": {"z1": 30, "z2": 40, "tiles": 9, "top_nearest": {"x": 1, "y": 1, "z": 40}}},
                  map={"dwarves": {"z_bottom": 90}, "layers": []})
    props, _ = TW.run(st)
    acts = [p.action for p in props if p.action.get("kind") == "magma"]
    assert acts == [{"type": "water_work", "kind": "magma", "shop": "MagmaForge"}], acts
    assert _far_args(dict(PLANNER_CONFIG, water_job_max=0)) == {"job_max": 0, "far_reach": 0}
    assert _far_args(PLANNER_CONFIG) == {}
    assert _int(0.0, -1) == 0 and _int(2.5, -1) == -1 and _int(True, -1) == -1
    assert far_args(dict(PLANNER_CONFIG, water_far_reach=0.0)) == {"far_reach": 0}
    works = {"pump": {"stage": "done"}}
    s = {"water": {"bodies": [], "waters": [{"kind": "river", "flow": "flowing", "tiles": 40}]}}
    assert "river" in power_wanted(s, works, PLANNER_CONFIG)
    assert "river" not in power_wanted(s, works, dict(PLANNER_CONFIG, water_far_reach=0))
    # the bridge: job_max 0 sets the cistern's and the well's far reach to 0
    import re
    src = (ROOT / "lua" / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    fn = re.search(r"^function far_reach_of\(a\).*?^end", src, re.S | re.M).group(0)
    lua = LuaRuntime(unpack_returned_tuples=True)
    got = lua.execute("""
      local fn = ...
      local B = {}
      local env = setmetatable({whole_number = function(v) return math.tointeger(tonumber(v)) end,
                                reqscript = function() return B end}, {__index = _G})
      assert(load(fn, 'f', 't', env))()
      env.far_reach_of({job_max = 0, far_reach = 90})
      local a, b = B.CISTERN_FAR_REACH, B.SHORE_FAR_REACH
      env.far_reach_of({far_reach = 90})
      return a, b, B.CISTERN_FAR_REACH
    """, fn)
    assert tuple(got) == (0, 0, 90), got


@test("irrigation far (review 2nd 10): the far search within its time, else a clean 'try later' (sooner for the brain)")
def _():
    env, W = irr_far_world()
    env.IRR_FAR_SECONDS = -1
    r = TW.step(env, "irrigation")
    assert r.rejected and r.later and "tried again later" in r.error, dict(r)
    assert W.saved["ai-overseer/waterworks"].refused.irrigation.later is True
    env, W = TW.irrigation_world()                                  # near water: no budget asked
    env.IRR_FAR_SECONDS = -1
    assert TW.step(env, "irrigation", dry_run=True).ok


if __name__ == "__main__":
    finish()
