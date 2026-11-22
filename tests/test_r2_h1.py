"""(r2h1) The river, recognised and used (A4 0.2-0.5, A1 finding 1): a DF
river is a local feature, so the survey filed it under "cavern"; the far,
sunken river of region4 (~90 tiles from the stair, ten levels down) built
nothing. Proved here on the tests' fake maps with a river as DF makes it
(the feature flag, the RIVER material, flowing): the survey's kind and flow,
the near box, the 16-body cap, the frozen-river memory; the survey's longer
slice asked by the brain; a river-fed cistern through solid rock down the
shaft way (floodgate, lever, diagonal step), its frozen river waited out,
not taken for dry; and the muddied farm level fed through that cistern.
pip install lupa.

    python tests/test_r2_h1.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

from lua_modules_util import module_src  # noqa: E402


def lua_const(test_file: str, name: str) -> str:
    """A string constant of another test file (its fake world), read without running its tests."""
    tree = ast.parse((ROOT / "tests" / test_file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return eval(compile(ast.Expression(node.value), test_file, "eval"), {"__builtins__": {}})
    raise KeyError(name)


LUA = LuaRuntime(unpack_returned_tuples=True)


def F(**kw):
    return LUA.table_from(kw)


# --- the survey (lua/ai-water.lua) on test_r38_water's big fake map ----------------------

WATER_SRC = module_src("ai-water.lua")
WATER_FAKE = lua_const("test_r38_water.py", "FAKE")


def world(W=288, H=288, Z=194, SURF=150):
    return LUA.execute(WATER_FAKE, WATER_SRC, W, H, Z, SURF)


def df_river(env, x0=200, z=149, y1=0, y2=287, width=4, brook=False):
    """A river as DF makes it: its tiles a local feature's (feature_init_outdoor_riverst),
    material RIVER (BROOK: 3), flowing, under the sky."""
    for y in range(y1, y2 + 1):
        for x in range(x0, x0 + width):
            env.SET(x, y, z, F(flow_size=7, outside=True, feature_local=True), 3 if brook else 2)


def waters(r):
    return list(r.waters.values())


@test("survey: a DF river (a local feature, RIVER, flowing) is kind river with its flow, not cavern; nearest_flowing set")
def _():
    env = world()
    df_river(env)
    r = env.survey()
    kinds = [(b.kind, b.flow) for b in waters(r)]
    assert ("river", "flowing") in kinds and not [k for k in kinds if k[0] == "cavern"], kinds
    b = [b for b in waters(r) if b.kind == "river"][0]
    assert b.tiles == 288 * 4 and b.nearest.x == 200 and b.reach == 161, (b.tiles, b.nearest.x, b.reach)
    assert r.nearest_flowing.kind == "river" and r.nearest_flowing.reach == 161
    assert r.river_seen and r.river_blocks is not None


@test("survey: a DF brook (BROOK, a local feature) is a flowing brook; a cavern's water is still the global feature's")
def _():
    env = world()
    df_river(env, brook=True)
    env.FILL(10, 10, 100, F(flow_size=7, feature_global=True), 1)  # layer 1: Cavern1
    r = env.survey()
    kinds = {b.kind: b for b in waters(r)}
    assert kinds["brook"].flow == "flowing" and kinds["cavern"].cavern == "Cavern1", list(kinds)
    assert r.nearest_flowing.kind == "brook"


@test("survey, near box: a DF river beside the fort is the near box's 'river' (moat, shore well), not 'cavern'")
def _():
    env = world()
    df_river(env, x0=60, z=148, width=2)
    r = env.survey()
    near = {b.kind: b for b in r.bodies.values()}
    assert "river" in near and "cavern" not in near, list(near)
    assert near["river"].tiles > 0 and near["river"].nearest.x == 60 and near["river"].z1 == 148


@test("survey: the 16-body cap never drops the river (rivers first), however many bigger and nearer bodies")
def _():
    env = world()
    for i in range(22):                                           # 22 cavern lakes, each a block of 256, nearer and bigger
        bx, by = 2 + (i % 6) * 2, 2 + (i // 6) * 2
        env.FILL(bx, by, 120, F(flow_size=7, feature_global=True), 1)
    df_river(env, x0=270, y1=0, y2=99, width=1)                  # 100 tiles, far off
    r = env.survey()
    assert r.waters_found >= 23 and len(waters(r)) == env.WATERS_MAX, (r.waters_found, len(waters(r)))
    rivers = [b for b in waters(r) if b.kind == "river"]
    assert rivers and rivers[0].flow == "flowing", [b.kind for b in waters(r)]


@test("survey: a DF river frozen over since a survey saw it is a frozen river (the memory keyed on the river kind)")
def _():
    env = world()
    df_river(env)
    r = env.scan_step(1, 1e9)
    assert r.done and r.river_seen and r.river_blocks is not None
    for y in range(0, 288):                                       # winter: the river is ice
        for x in range(200, 204):
            env.SET(x, y, 149, F(flow_size=0, outside=True, feature_local=True), 4)
    r = env.scan_step(2, 1e9)
    assert r.done and r.frozen_river and r.river_seen, (r.frozen_river, r.river_seen)


@test("survey slice: the brain's longer slice (h1_water_slice_seconds) taken, capped at SLICE_MAX_SECONDS; none: 0.15 s")
def _():
    env = world()
    assert env.slice_seconds(None) == env.SLICE_SECONDS == 0.15
    assert env.slice_seconds(0.3) == 0.3 and env.slice_seconds(5) == env.SLICE_MAX_SECONDS == 0.4
    assert env.slice_seconds(-1) == 0.15 and env.slice_seconds("x") == 0.15
    df_river(env)
    r, _ = env.TIMED(5, env.slice_seconds(0.3))
    assert not r.done and r.ok
    from planner_config import PLANNER_CONFIG
    from planner_wells import _water_rules
    cfg = dict(PLANNER_CONFIG)
    s = {"date": {"year": 250, "tick": 10}, "water": {"ok": True, "scanning": True, "waters_pending": True}}
    props, notes = [], []
    _water_rules(s, cfg, props, notes)
    acts = [p.action for p in props if p.action.get("type") == "survey_water"]
    assert acts and acts[0].get("seconds") == cfg["h1_water_slice_seconds"] == 0.3, acts
    s["water"] = {"ok": True, "none": True}                       # a new survey: the plain slice
    props = []
    _water_rules(s, cfg, props, [])
    assert [p for p in props if p.action.get("type") == "survey_water" and "seconds" not in p.action]


def plain(v):
    """A Lua table as Python dicts and lists (the report's JSON)."""
    if hasattr(v, "items") and not isinstance(v, (str, bytes)):
        keys = list(v.keys())
        if keys and all(isinstance(k, int) for k in keys):
            return [plain(v[k]) for k in sorted(keys)]
        return {k: plain(x) for k, x in v.items()}
    return v


@test("digest: the WATER line names the DF river (on region4 it said 'nearest flowing: none on the map')")
def _():
    from digest import water_line
    env = world()
    df_river(env)
    r = plain(env.survey())
    line = water_line({"water": r, "map": {"elevation_offset": -129}})
    assert "nearest flowing: river 162 tiles off, reach 161" in line, line


# --- the river-fed cistern (lua/ai-builder-cistern.lua) on test_builder's fake fort -------

BUILDER_HARNESS = lua_const("test_builder.py", "HARNESS")
BL = LuaRuntime(unpack_returned_tuples=True)
BL.globals().LUA_DIR = str(ROOT / "lua")
B, BW = BL.execute(BUILDER_HARNESS, (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8"),
                   (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8"))
CISTERN_GAME = lua_const("test_builder.py", "CISTERN_GAME")

# the fort's floor at z80 (test_builder's fort), the cistern's rock at z79; a
# river one level over the fort's floor, 24-27 tiles east of the fort's floor,
# as DF makes it; the survey's list says where (FAKEW)
RIVER_FORT = r"""
local W, river_z, with_survey = ...
W.reset(); W.citizens = {}
for i = 1, 20 do table.insert(W.citizens, {x = 50 + i % 10, y = 60, z = 80}) end
for x = 30, 90 do for y = 45, 75 do
  if not (x == 60 and y == 60) then W.set(x, y, 79, {shape = 'WALL', material = 'STONE'}) end
end end
for y = 0, 119 do for x = 104, 107 do
  W.set(x, y, river_z, {shape = 'FLOOR', material = 'RIVER', liquid = true, depth = 7, outside = true,
                        feature = true, feature_local = true, feature_global = false})
  W.set(x, y, river_z + 1, {shape = 'EMPTY', material = 'AIR', outside = true})
end end
FAKEW = with_survey and {ok = true, map = {w = 120}, bodies = {}, waters = {{kind = 'river', flow = 'flowing',
         salt_share = 0, tiles = 480, nearest = {x = 104, y = 60, z = river_z}, d = 50, reach = 46,
         z1 = river_z, z2 = river_z}}} or nil
WORKS = nil
"""
# the fake survey and water works in reach of the builder (again after
# test_builder's CISTERN_GAME, which wraps the real reqscript afresh)
WRAP = r"""
local inner = reqscript
_G.reqscript = function(n)
  if n == 'ai-water' and FAKEW then return {last = function() return FAKEW end} end
  if n == 'ai-waterworks' and WORKS then return {load_state = function() return WORKS end} end
  return inner(n)
end
"""


def river_fort(river_z=81, with_survey=True):
    BL.execute("REAL_REQ = REAL_REQ or reqscript; reqscript = REAL_REQ")
    BL.execute(RIVER_FORT, BW, river_z, with_survey)
    BL.execute(WRAP)
    B.cistern_prefs(BL.table_from({}))
    B.CISTERN_FAR_REACH = None
    B.CISTERN_HOLD = False


def plan_of(r):
    return (r, None) if hasattr(r, "cistern") else (r[0], r[1])


@test("cistern: a far river (a local feature) feeds a cistern down the shaft way: tunnel through rock, floodgate, diagonal")
def _():
    river_fort()
    plan, why = plan_of(B.plan_cistern())
    assert plan is not None, why
    assert plan.source == "river" and plan.river is True, (plan.source, plan.river)
    assert plan.shaft is not None and plan.intake_z == 81 and plan.cistern.z == 79 and plan.rise == 2
    c, s, k = plan.cistern, plan.shaft, plan.corner
    assert abs(s.x - k.x) == 1 and abs(s.y - k.y) == 1                    # the diagonal step: no pressure past it
    assert c.x1 <= k.x <= c.x2 and c.y1 <= k.y <= c.y2
    assert plan.tunnel > 15 and plan.water.x == 104                      # through the rock to the river's bank
    assert plan.floodgate.x == plan.tunnel_path[1].x and plan.plug.x == 103 and plan.lever is not None
    for q in plan.tunnel_path.values():                                  # every tunnel tile under rock (capped)
        t = BW.peek(q.x, q.y, 82)
        assert t.shape in ("WALL", "FLOOR") and not t.liquid, (q.x, q.y, t.shape)
    assert B.cistern_sealed(plan) is True


@test("cistern: never a river on the cistern's own level (no diagonal there: its pressure could climb the well)")
def _():
    river_fort(river_z=79)
    plan, why = plan_of(B.plan_cistern())
    assert plan is None or plan.source != "river", (plan.source if plan else None)


@test("cistern: no survey, or far sources off (water_far_reach 0): the far river is not tunnelled to")
def _():
    river_fort(with_survey=False)
    plan, why = plan_of(B.plan_cistern())
    assert plan is None, plan.source
    river_fort()
    B.CISTERN_FAR_REACH = 0
    try:
        plan, why = plan_of(B.plan_cistern())
        assert plan is None, plan.source
    finally:
        B.CISTERN_FAR_REACH = None


@test("cistern step: a river frozen at the plug waits for the thaw; frozen while filling is not 'dried up' (never retired)")
def _():
    river_fort()
    plan, _ = plan_of(B.plan_cistern())
    z = plan.cistern.z
    BL.execute(CISTERN_GAME, BW)
    BL.execute(WRAP)
    gate = BL.globals().MKB(plan.floodgate.x, plan.floodgate.y, plan.intake_z, 1,
                            BL.table_from({"gate_flags": BL.table_from({"closed": False})}))
    gate.built = True
    BW.persist["ai-overseer/cistern"] = BL.table_from({"stage": "filling", "plan": plan, "lever_id": 5, "gate_id": gate.id})
    for x in range(plan.cistern.x1, plan.cistern.x2 + 1):
        for y in range(plan.cistern.y1, plan.cistern.y2 + 1):
            BW.set(x, y, z, BL.table_from({"shape": "FLOOR", "liquid": False, "depth": 0}))
    for q in list(plan.tunnel_path.values()) + [plan.plug]:
        BW.set(q.x, q.y, plan.intake_z, BL.table_from({"shape": "FLOOR", "designated": False}))
    BW.set(plan.water.x, plan.water.y, plan.intake_z,
           BL.table_from({"shape": "WALL", "material": "FROZEN_LIQUID", "liquid": False, "depth": 0}))
    BL.execute("df = df or {}; df.global = {cur_year = 10, cur_year_tick = 0}")
    try:
        r = B.cistern_step(False)
        assert r.waiting and "frozen" in r.error, r.error
        BL.execute("df.global.cur_year_tick = 60 * 1200")                   # two months of ice
        r = B.cistern_step(False)
        assert r.waiting and "frozen" in r.error and not r.retired, dict(r)
        assert B.cistern_data() is not None and B.cistern_data().dry_since is None
        # at the link step (before any water): frozen beside the plug waits, never "the source is gone"
        gate.gate_flags.closed = True
        BL.execute("local g = ... ; LINKS[g] = {5}", gate.id)
        d = B.cistern_data()
        d.stage = "linking"
        BW.persist["ai-overseer/cistern"] = d
        r = B.cistern_step(False)
        assert r.waiting and "frozen" in r.error and "gone" not in r.error, dict(r)
        BW.set(plan.water.x, plan.water.y, plan.intake_z,                 # the thaw: on to the plug
               BL.table_from({"shape": "FLOOR", "material": "RIVER", "liquid": True, "depth": 7}))
        r = B.cistern_step(False)
        assert r.ok and r.stage == "opening", dict(r)
    finally:
        BL.execute("df.global = nil")


@test("cistern wall: the muddied farm level's outlet (its plug and tunnel) is no gap; any other hole still is")
def _():
    river_fort()
    plan, _ = plan_of(B.plan_cistern())
    c, z = plan.cistern, plan.cistern.z
    px, py = c.x1 - 1, c.y1 + 2                                          # a ring tile on the west wall
    BW.set(px, py, z, BL.table_from({"shape": "FLOOR"}))
    BW.set(px - 1, py, z, BL.table_from({"shape": "FLOOR"}))
    ok = B.cistern_sealed(plan)
    assert ok is not True                                                # a hole in its wall
    BL.execute("""local px, py, z, c = ...
      WORKS = {works = {irrigation = {stage = 'filling', plan = {kind = 'irrigation',
        cistern_fed = {x1 = c.x1, y1 = c.y1, z = c.z},
        plug = {x = px, y = py, z = z}, gate = {x = px - 1, y = py, z = z}, upstream = {}}}}}""", px, py, z, c)
    try:
        assert B.cistern_sealed(plan) is True
        BL.execute("WORKS.works.irrigation.stage = 'retired'")
        assert B.cistern_sealed(plan) is not True
    finally:
        BL.execute("WORKS = nil")


# --- the muddied farm level through the river-fed cistern (lua/ai-waterworks.lua) ----------

WW_SRC = module_src("ai-waterworks.lua")   # (r8) the hub and its parts
WW_FAKE = lua_const("test_waterworks.py", "FAKE")


def irrigation_cistern_world(stage="done", river=True, depth=7):
    env = LUA.execute(WW_FAKE, WW_SRC)
    W = env.W
    for zf in (95, 90):                                                  # fort floors at 95 and 90
        for x in range(30, 90):
            for y in range(40, 80):
                W.set(x, y, zf, F(shape="FLOOR"))
    W.citizens = LUA.table_from([F(x=60, y=60, z=95), F(x=60, y=61, z=95), F(x=62, y=62, z=90)])
    # the river-fed cistern under the fort floor at 90 (z89), full; its shaft and tunnel north at z91
    for x in range(60, 65):
        for y in range(60, 65):
            W.set(x, y, 89, F(shape="FLOOR", liquid=True, depth=depth))
    LUA.execute("""local env, stage, river = ...
      local plan = {river = river, cistern = {x1 = 60, y1 = 60, x2 = 64, y2 = 64, z = 89},
                    well = {x = 62, y = 62, z = 90}, intake_z = 91, shaft = {x = 59, y = 59},
                    tunnel_path = {{x = 59, y = 58}, {x = 59, y = 57}}, plug = {x = 59, y = 57}}
      env.reqscript = function(n)
        if n == 'ai-builder' then return {cistern_data = function() return {stage = stage, plan = plan} end} end
        error('no reqscript ' .. n)
      end""", env, stage, river)
    return env, W


def ww_step(env, kind):
    return env.step(kind, LUA.table_from({}))


@test("irrigation: no still water under the fort's top levels, a river-fed cistern done: the farm room fed through it")
def _():
    env, W = irrigation_cistern_world()
    r = ww_step(env, "irrigation")
    assert r.stage == "planned", dict(r)
    p = W.saved["ai-overseer/waterworks"].works.irrigation.plan
    assert p.room.z == 89 and p.cistern_fed.x1 == 60 and p.cistern_fed.z == 89
    c = {"x1": 60, "y1": 60, "x2": 64, "y2": 64}
    # the plug in the cistern's wall, beside its water; no other dug tile beside the cistern
    assert (c["x1"] - 1 <= p.plug.x <= c["x2"] + 1 and c["y1"] - 1 <= p.plug.y <= c["y2"] + 1
            and not (c["x1"] <= p.plug.x <= c["x2"] and c["y1"] <= p.plug.y <= c["y2"])), (p.plug.x, p.plug.y)
    for q in list(p.dig.values()):
        if q.z == 89 and not (q.x == p.plug.x and q.y == p.plug.y):
            assert not (c["x1"] - 1 <= q.x <= c["x2"] + 1 and c["y1"] - 1 <= q.y <= c["y2"] + 1), (q.x, q.y)
    assert p.gate.z == 89 and p.lever.z == 90


@test("irrigation: a cistern not river-fed, not done, or empty is no source (the old refusal stands)")
def _():
    for kw in ({"river": False}, {"stage": "filling"}, {"depth": 0}):
        env, W = irrigation_cistern_world(**kw)
        r = ww_step(env, "irrigation")
        assert r.stage != "planned" and "still, fresh water" in (r.error or ""), (kw, dict(r))


if __name__ == "__main__":
    finish()
