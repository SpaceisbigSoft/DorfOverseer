"""(0.105.38) The whole-map water survey (lua/ai-water.lua) and far sources
for the water works (lua/ai-waterworks.lua; the brain's planner_water.py and
digest.py): a river beyond the old 72-tile box found with its reach, the
slices within their time on a 288x288x194 map, a survey resumed across
cycles and reloads and dropped on unload, magma by kind (a pipe, a cavern's
pool, the sea), far rivers for a moat or a water wheel (the long channel
staged and checked end to end), far still water for the muddied farm level,
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
                                               [2] = {material = 2, shape = 2}, [3] = {material = 3, shape = 2}}},
          tiletype_material = {[0] = 'AIR', [1] = 'STONE', [2] = 'RIVER', [3] = 'BROOK'},
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
            env.SET(120, y, z, F(water_table=True))
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


@test("moat: a far river chosen when none is near: a 96-tile channel, staged, the dry run walked again before each segment")
def _():
    env, W = far_moat_world()
    r = TW.step(env, "moat")
    assert r.ok and r.stage == "planned", dict(r)
    wk = W.saved["ai-overseer/waterworks"].works.moat
    p = wk.plan
    assert p.far and p.far.kind == "channel" and p.far.d > 90 and p.plug.x == 149
    n = len(list(p.dig.values()))
    assert len(list(p.stages.values())) == (n + 39) // 40 >= 3
    r = TW.step(env, "moat")
    assert r.stage == "digging" and r.segment == 1
    assert len(list(W.designated.values())) == 40                     # the first segment only
    r = TW.step(env, "moat")
    assert r.waiting and "segment 1 of 3" in r.error, r.error
    seg1 = [p.dig[i] for i in range(1, 41)]
    W.dig_all(L(*seg1))
    r = TW.step(env, "moat")
    assert r.waiting and "segment 2 of 3 designated" in r.error, r.error
    assert len(list(W.designated.values())) == 80
    W.dig_all(L(*[p.dig[i] for i in range(41, 81)]))
    W.set(120, 55, 99, T(shape="FLOOR"))                              # a room dug beside the channel meanwhile
    r = TW.step(env, "moat")
    assert r.stage == "held" and "dry run before segment 3" in r.error and "x120 y55" in r.error, r.error
    assert len(list(W.designated.values())) == 80


@test("moat: a far river behind an aquifer or a cavern under the channel is refused, saying where")
def _():
    for what, word in (("aquifer", "an aquifer under the channel at x100 y54"), ("feature", "a cavern under the channel")):
        env, W = far_moat_world()
        W.set(100, 54, 99, T(**{what: True}))
        r = TW.step(env, "moat")
        assert r.rejected and word in r.error, r.error
        assert not list(W.designated.values())


@test("moat: the near river still chosen when a far one is found too (the same plan as without the whole-map survey)")
def _():
    env, W = TW.moat_world()
    _, before = plan_of(env, "moat")
    env, W = TW.moat_world()
    W.survey.waters = L(T(kind="river", flow="flowing", tiles=30, d=100, nearest=T(x=150, y=54, z=99), z2=99))
    W.survey.map = T(w=192)
    _, after = plan_of(env, "moat")
    assert cells(before.dig) == cells(after.dig) and after.far is None and after.stages is None


@test("moat: a far river past the reach cap (the brain's water_far_reach) or the job cap is refused")
def _():
    env, W = far_moat_world()
    r = TW.step(env, "moat", far_reach=50)
    assert r.rejected and "(50 at most)" in r.error, r.error
    env, W = far_moat_world()
    r = TW.step(env, "moat", job_max=60)
    assert r.rejected and "(60 at most)" in r.error, r.error


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
    x150 with its top at z 80, and the magma sea's top at z 40."""
    env = TW.LUA.execute(TW.FAKE, TW.SRC)
    W = env.W
    for x in range(50, 71):
        for y in range(50, 71):
            W.set(x, y, 90, T(shape="FLOOR"))
    W.citizens = L(T(x=60, y=60, z=90), T(x=61, y=60, z=92))
    W.set(150, 60, 80, T(shape="FLOOR", liquid=True, magma=True, depth=7, material="STONE", feature=True))
    W.set(60, 120, 40, T(shape="FLOOR", liquid=True, magma=True, depth=7, material="STONE", feature=True))
    pipe = T(kind="magma", magma="pipe", tiles=40, d=110, reach=100, top=T(x=150, y=60, z=80),
             nearest=T(x=150, y=60, z=80))
    if pipe_cavern:
        pipe.opens_cavern, pipe.reach, pipe.reach_through = pipe_cavern, None, 100
    sea = T(kind="magma", magma="sea", tiles=900, d=60, reach=110, top=T(x=60, y=120, z=40),
            nearest=T(x=60, y=120, z=40))
    W.survey = T(bodies=L(), map=T(w=192), waters=L(sea, pipe))
    return env, W


@test("magma (the player, 10:48): the workshop takes the far pipe over the nearer sea, its stair joined to the fort by a tunnel")
def _():
    env, W = magma_far_world()
    r, p = plan_of(env, "magma", shop="MagmaForge")
    assert p is not None, dict(r)
    assert p.source.magma == "pipe" and p.gate.z == 80 and p.room.z == 81, dict(p.source)
    assert p.access and p.access > 50 and p.stages                     # the tunnel to the fort, dug in segments
    tun = [c for c in p.dig.values() if c.z == 90 and c.text == "d"]
    assert tun and min(c.x for c in tun) <= 72
    # a pipe whose way opens a cavern: only with the cavern switch's leave; else the sea
    env, W = magma_far_world(pipe_cavern="Cavern1")
    r, p = plan_of(env, "magma", shop="MagmaForge")
    assert p is not None and p.source.magma == "sea", dict(r)
    env, W = magma_far_world(pipe_cavern="Cavern1")
    W.survey.waters = L(W.survey.waters[2])
    r = TW.step(env, "magma", shop="MagmaForge")
    assert r.rejected and "opens Cavern1" in r.error and "cavern switch" in r.error, r.error
    r, p = plan_of(env, "magma", shop="MagmaForge", open_caverns=True)
    assert p is not None and p.source.opens_cavern == "Cavern1"
    # the near box's magma (as before) first
    env, W = TW.magma_world()
    _, before = plan_of(env, "magma", shop="MagmaForge")
    env, W = TW.magma_world()
    W.survey.waters = magma_far_world()[1].survey.waters
    _, after = plan_of(env, "magma", shop="MagmaForge")
    assert cells(before.dig) == cells(after.dig) and after.source is None


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


if __name__ == "__main__":
    finish()
