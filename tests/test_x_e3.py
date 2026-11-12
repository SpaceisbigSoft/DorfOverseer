"""(0.105.37 E3) W7: power for the pump stack (lua/ai-waterworks.lua `power`,
brain/planner_water.py) on a fake map: a water wheel on the river or a
windmill, the shaft of axles through solid rock to the top pump, the power
check, the lever-worked switch gear keeping the reservoir filled, the
water's safety (water in the shaft, a flood, the stack held), retiring a dry
wheel; and the planner: begun only at Guided/Architect, byte-identical at
Scripts. pip install lupa.

    python tests/test_x_e3.py
"""

from __future__ import annotations

import copy
import json
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

SRC = (ROOT / "lua" / "ai-waterworks.lua").read_text(encoding="utf-8")

# The fake map (as tests/test_waterworks.py): the surface floor at z 100
# (outside, over stone), open sky above, natural stone below; the machines
# placed by their quickfort keys; a gear's engagement toggled by its lever.
FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local W = {tiles = {}, saved = {}, designated = {}, buildings = {}, links = {}, pulls = {}, occ = {},
           citizens = {}, survey = nil, entrances = {}, tick = 1000, mud = {}, engaged = {}, turning = {},
           power = {}, manual = {}}
env.W = W
function W.key(x, y, z) return x .. ',' .. y .. ',' .. z end
function W.get(x, y, z)
  local t = W.tiles[W.key(x, y, z)]
  if t then return t end
  if z > 100 then return {shape = 'EMPTY', material = 'AIR', outside = true} end
  if z == 100 then return {shape = 'FLOOR', material = 'SOIL', outside = true} end
  return {shape = 'WALL', material = 'STONE'}
end
function W.set(x, y, z, f)
  local t = {}
  for k, v in pairs(W.get(x, y, z)) do t[k] = v end
  for k, v in pairs(f) do t[k] = v end
  W.tiles[W.key(x, y, z)] = t
end
function W.dig_all(cells)
  for _, c in ipairs(cells) do
    local shape = ({h = 'EMPTY', j = 'STAIR_DOWN', u = 'STAIR_UP', i = 'STAIR_UPDOWN', z = 'FLOOR'})[c.text] or 'FLOOR'
    W.set(c.x, c.y, c.z, {shape = shape})
  end
end
function W.build_all()
  local n = 0
  for k, b in pairs(W.buildings) do if not b.built then b.built = true; n = n + 1 end end
  return n
end
local KIND = {x = 'Floodgate', Tl = 'Trap', H = 'Hatch', Mg = 'GearAssembly', Mv = 'AxleVertical', p = 'FarmPlot'}
local function kind_of(text)
  if KIND[text] then return KIND[text] end
  if text:match('^Ms') then return 'ScrewPump' end
  if text:match('^Mh') then return 'AxleHorizontal' end
  if text:match('^Mw') then return 'WaterWheel' end
  if text:match('^g') then return 'Bridge' end
  return 'Furnace'
end
local function add_building(x, y, z, kind)
  W.nextid = (W.nextid or 0) + 1
  W.buildings[W.key(x, y, z) .. kind] = {id = W.nextid, built = false, closed = kind == 'Floodgate' or nil, kind = kind}
  if kind == 'GearAssembly' then W.engaged[W.nextid] = true end
  return W.nextid
end
dfhack = {persistent = {saveSiteData = function(k, v) W.saved[k] = v end,
                        getSiteData = function(k, d) return W.saved[k] or d end}}
assert(load(src, 'ai-waterworks', 't', env))()
env.T = function(x, y, z) local t = W.get(x, y, z); local c = {}; for k, v in pairs(t) do c[k] = v end; return c end
env.occupants = function(box) return W.occ end
env.designate = function(cells, z, mode)
  for _, c in ipairs(cells) do
    table.insert(W.designated, {x = c.x, y = c.y, z = z, text = c.text, mode = mode})
    if mode == 'build' then
      local kind = kind_of(c.text)
      local x, y = c.x, c.y
      if kind == 'WaterWheel' then           -- found at its centre
        if c.text:match('3x1') then x = x + 1 else y = y + 1 end
      end
      add_building(x, y, z, kind)
    end
  end
  return true
end
env.place_windmill = function(x, y, z) add_building(x, y, z, 'Windmill'); W.windmill_at = {x, y, z}; return true end
env.building = function(x, y, z, kind) return W.buildings[W.key(x, y, z) .. kind] end
env.link = function(l, t) W.links[t] = l; return {ok = true} end
env.is_linked = function(l, t) return W.links[t] == l end
env.link_pending = function() return false end
env.pull = function(id, instant)
  table.insert(W.pulls, {id = id, instant = instant == true})
  for _, b in pairs(W.buildings) do
    if W.links[b.id] == id then
      if b.closed ~= nil then b.closed = not b.closed end
      if b.kind == 'GearAssembly' then W.engaged[b.id] = not W.engaged[b.id] end
    end
  end
  return true
end
env.cancel_pulls = function(id) W.cancelled = (W.cancelled or 0) + 1 end
env.dig_now = function(x, y, z) W.set(x, y, z, {shape = 'EMPTY'}) end
env.citizens = function() return W.citizens end
env.water_survey = function() return W.survey end
env.mud = function(x, y, z) return W.mud[W.key(x, y, z)] == true end
env.now = function() return W.tick end
env.entrances = function() return W.entrances end
env.set_name = function(id, name) W.named = W.named or {}; W.named[id] = name end
env.lock_hatch = function(id) W.locked = id end
env.ez = function(z) return z - 100 end
env.reqscript = function() error('no reqscript in the tests') end
env.magma_parts = function() return {floodgates = 1, hatches = 1, mechanisms = 3} end
env.building_magma_safe = function(id) return true end
env.magma_filter = function(on) return on == true and {} or nil end
env.set_pump_manual = function(id, on) W.manual[id] = on == true; return true end
env.gear_engaged = function(id) return W.engaged[id] end
env.wheel_turning = function(id) local t = W.turning[id]; if t == nil then return true end return t end
env.windmill_turning = function(id) local t = W.turning[id]; if t == nil then return true end return t end
env.machine_power = function(id) return W.power[id] end
return env
"""

LUA = LuaRuntime(unpack_returned_tuples=True)
KEY = "ai-overseer/waterworks"


def T(**kw):
    return LUA.table_from(kw)


def L(*items):
    return LUA.table_from(list(items))


def opts(**kw):
    return LUA.table_from(kw)


def step(env, kind, **kw):
    return env.step(kind, opts(**kw))


def works(W):
    return W.saved[KEY].works


def tolist(t):
    return [t[i] for i in range(1, len(t) + 1)] if t is not None else []


def stack_world(water_z=86, river=True):
    """The pump stack (W4) planned on a full floor at z 90 and built to done,
    then the fort's lowest level cut back to a corridor from the stack's
    hatch and the reservoir's top (the shaft's column all rock); a river two
    columns wide at x 70-72, one level under the ground."""
    env = LUA.execute(FAKE, SRC)
    W = env.W
    for x in range(30, 90):
        for y in range(40, 80):
            W.set(x, y, 90, T(shape="FLOOR"))
    W.citizens = L(T(x=60, y=60, z=90), T(x=61, y=60, z=92))
    W.set(60, 60, water_z, T(shape="FLOOR", liquid=True, depth=7))
    W.survey = T(bodies=L(T(kind="pool", tiles=1, nearest=T(x=60, y=60, z=water_z))))
    assert step(env, "pump").stage == "planned"
    wk = works(W).pump
    p = wk.plan
    step(env, "pump")
    W.dig_all(p.dig)
    step(env, "pump")
    W.build_all()
    step(env, "pump")
    assert step(env, "pump").stage == "filling"
    assert step(env, "pump").plug_dug
    W.set(p.reservoir.x, p.reservoir.y, p.reservoir.z, T(liquid=True, depth=4))
    assert step(env, "pump").stage == "done"
    # the fort's lowest level: only the stack's hatch, a corridor south of it, the reservoir's top
    hatch = [b for b in tolist(p.builds) if b.kind == "Hatch"][0]
    keep = {(hatch.x, hatch.y), (p.reservoir.x, p.reservoir.y)}
    for y in range(hatch.y, 66):
        keep.add((hatch.x, y))
    for x in range(min(hatch.x, p.reservoir.x), max(hatch.x, p.reservoir.x) + 1):
        keep.add((x, 65))
    for y in range(p.reservoir.y, 66):
        keep.add((p.reservoir.x, y))
    for x in range(30, 90):
        for y in range(40, 80):
            if (x, y) not in keep:
                W.tiles[f"{x},{y},90"] = None
    for (x, y) in keep:
        W.set(x, y, 90, T(shape="FLOOR"))
    W.set(hatch.x, hatch.y, 90, T(shape="STAIR_DOWN"))
    if river:
        for x in range(70, 73):
            for y in range(45, 76):
                W.set(x, y, 99, T(shape="FLOOR", material="RIVER", liquid=True, depth=7, outside=True))
                W.set(x, y, 100, T(shape="EMPTY", outside=True))
        W.survey = T(bodies=L(T(kind="pool", tiles=1, nearest=T(x=60, y=60, z=water_z)),
                              T(kind="river", tiles=93, nearest=T(x=70, y=60, z=99), z2=99)))
    return env, W


def build_power(env, W, **kw):
    """The power from planned to running: dug, channelled, built wave by wave, linked."""
    r = step(env, "power", **kw)
    assert r.ok and r.stage == "planned", dict(r)
    p = works(W).power.plan
    assert step(env, "power").stage == "digging"
    W.dig_all(p.dig)
    assert "channelled" in step(env, "power").error
    W.dig_all(p.dig2)
    assert step(env, "power").stage == "building"          # (0.105.37 fix) the plug is cut once the foot's pump stands
    for _ in range(60):
        r = step(env, "power")
        if r.stage != "building":
            break
        W.build_all()
        if works(W).power.dig3:
            W.dig_all(p.dig3)
    assert r.stage == "linking", dict(r)
    assert step(env, "power").stage == "running"
    return p


@test("power: a water wheel on the river, a shaft of axles through solid rock to the top pump, the power checked")
def _():
    env, W = stack_world()
    r = step(env, "power", dry_run=True)
    assert r.ok and r.dry_run and r.plan.source == "wheel", dict(r)
    assert works(W)["power"] is None                     # a dry run changes nothing
    p = r.plan
    # the shaft: straight over the top pump's output, from the level above it to under the ground
    # (0.105.37 fix: sealed by a screw pump at its foot and one at its top)
    pp = works(W).pump.plan
    top = max((b for b in tolist(pp.builds) if b.kind == "ScrewPump"), key=lambda b: b.z)
    assert p.shaft.x in (top.x, top.x + 1) and p.shaft.z1 == top.z + 1 and p.shaft.z2 == 99
    builds = tolist(p.builds)
    kinds = [b.kind for b in builds]
    assert kinds[0] == "ScrewPump" and builds[0].z == top.z + 1 and builds[0].seal == "foot"   # on the top pump
    assert kinds.count("AxleVertical") == 99 - (top.z + 2)                           # one a level
    assert kinds.count("ScrewPump") == 2 and builds[p.top - 1].z == 99                # the foot's and the top seal
    assert kinds.count("WaterWheel") == 1 and p.wheels == 1
    wheel = [b for b in builds if b.kind == "WaterWheel"][0]
    assert wheel.text == "Mw(1x3)" and wheel.cx == 70                                # over the river, N-S
    assert any(b.kind == "AxleHorizontal" for b in builds)
    sw = builds[p.switch - 1]
    assert sw.kind == "GearAssembly" and sw.z == 99 and sw.x == p.shaft.x           # the switch bears nothing
    assert not any(b.after == p.switch for b in builds)
    # DF's numbers: 3 pumps and 2 seals x 10, 3 gears x 5, 8 vertical + 2 horizontal axles, the wheel's own 10
    assert p.pumps == 3 and p.need == 50 + 15 + 8 + 2 + 10 and p.have == 100, (p.need, p.have)
    assert p.lever.name == "AI pump power" and p.hatch.lock


@test("power: the pocket joins nothing of the fort (a room beside the shaft refuses it, saying where)")
def _():
    env, W = stack_world()
    p = step(env, "power", dry_run=True).plan
    for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):              # a room's corners beside the shaft
        W.set(p.shaft.x + dx, p.shaft.y + dy, 95, T(shape="FLOOR"))
    r = step(env, "power")
    assert r.rejected and "touch something other than solid rock" in r.error and "elevation -5" in r.error, r.error
    assert works(W)["power"] is None and W.saved[KEY].refused.power.why == r.error
    env, W = stack_world()
    p = step(env, "power", dry_run=True).plan
    W.set(p.shaft.x, p.shaft.y, 94, T(shape="FLOOR"))              # the shaft's own column dug through a room
    r = step(env, "power")
    assert r.rejected and "would cross something other than solid rock" in r.error, r.error


@test("power: not begun before the pump stack is done; a windmill too weak for three pumps is refused with the numbers")
def _():
    env, W = stack_world()
    works(W).pump.stage = "filling"
    r = step(env, "power")
    assert r.rejected and "not done yet" in r.error
    env, W = stack_world(river=False)
    r = step(env, "power")
    assert r.rejected and "no river" in r.error and "more than a windmill gives (40 at most)" in r.error, r.error


@test("power: a windmill for a one-pump stack, its centre over a gear under the ground, the shaft roofed")
def _():
    env, W = stack_world(water_z=88, river=False)
    r = step(env, "power", dry_run=True)
    assert r.ok and r.plan.source == "windmill", dict(r)
    p = r.plan
    builds = tolist(p.builds)
    mill = [b for b in builds if b.kind == "Windmill"][0]
    assert mill.z == 100 and builds[mill.after - 1].kind == "GearAssembly" and builds[mill.after - 1].z == 99
    sw = builds[p.switch - 1]
    assert sw.z == 99 and sw.x == p.shaft.x                       # the switch under the ground
    assert not any(c.z == 100 and c.x == p.shaft.x and c.y == p.shaft.y for c in tolist(p.dig2))   # roofed
    assert p.need == 20 + 10 + 8 + 1 and p.have == 40, p.need          # (0.105.37 fix) the foot's pump too
    p = build_power(env, W)
    assert W.windmill_at is not None and W.windmill_at[3] == 100


@test("power: built a wave at a time (nothing over open space before what bears it), the hatch last and locked")
def _():
    env, W = stack_world()
    step(env, "power")
    p = works(W).power.plan
    step(env, "power")
    W.dig_all(p.dig)
    step(env, "power")
    W.dig_all(p.dig2)
    assert step(env, "power").stage == "building"
    step(env, "power")
    builds = tolist(p.builds)
    placed = {(d.x, d.y, d.z, d.text) for d in tolist(W.designated) if d.mode == "build"}
    assert (builds[0].x, builds[0].y, builds[0].z, builds[0].text) in placed  # the foot's pump on the top pump
    assert (builds[1].x, builds[1].y, builds[1].z, "Mv") not in placed        # not before the gear is built
    assert not any(b.kind == "WaterWheel" for b in builds if (b.x, b.y, b.z, b.text) in placed)
    assert not any(d.text == "H" and d.z == 100 for d in tolist(W.designated))
    for _ in range(40):
        r = step(env, "power")
        if r.stage != "building":
            break
        W.build_all()
        if works(W).power.dig3:
            W.dig_all(p.dig3)
    assert r.stage == "linking" and W.locked is not None
    assert step(env, "power").stage == "running"


@test("power: running keeps the reservoir between 3/7 and 5/7 with the switch, no dwarf at the pumps")
def _():
    env, W = stack_world()
    p = build_power(env, W)
    wk = works(W).power
    res = p.test
    gear = env.building(p.shaft.x, p.shaft.y, 99, "GearAssembly")
    assert W.engaged[gear.id] is True
    W.power[gear.id] = T(cur=100, need=69)
    r = step(env, "power")
    assert r.waiting and "running: the reservoir 4/7, the power on (100 for 69 needed)" in r.error, r.error
    pumps = [b for b in tolist(works(W).pump.plan.builds) if b.kind == "ScrewPump"]
    assert all(W.manual[env.building(b.x, b.y, b.z, "ScrewPump").id] is False for b in pumps)
    W.set(res.x, res.y, res.z, T(liquid=True, depth=5))
    r = step(env, "power")
    assert "switched off" in r.error and W.engaged[gear.id] is False and W.pulls[len(W.pulls)].instant
    W.set(res.x, res.y, res.z, T(liquid=True, depth=3))
    r = step(env, "power")
    assert "switched on" in r.error and W.engaged[gear.id] is True
    assert wk.depth == 3


@test("power: water in the shaft stops it, shuts the stack's floodgate and holds it; a flood switches it off")
def _():
    env, W = stack_world()
    p = build_power(env, W)
    gear = env.building(p.shaft.x, p.shaft.y, 99, "GearAssembly")
    c = tolist(p.pocket)[3]
    W.set(c.x, c.y, c.z, T(liquid=True, depth=2))
    r = step(env, "power")
    assert r.stage == "held" and "water (2/7) in the power shaft" in r.error, dict(r)
    assert W.engaged[gear.id] is False
    assert works(W).pump.shut == "water in the power shaft"
    env, W = stack_world()
    p = build_power(env, W)
    gear = env.building(p.shaft.x, p.shaft.y, 99, "GearAssembly")
    r = step(env, "power", shut=True, why="dwarves in deep water")
    assert r.ok and r.shut and W.engaged[gear.id] is False
    assert "waiting to be switched on again" in step(env, "power").error
    W.tick = W.tick + 5 * 1200
    assert step(env, "power", reopen=True).reopened
    W.set(p.test.x, p.test.y, p.test.z, T(liquid=True, depth=2))
    assert "switched on" in step(env, "power").error


@test("power: a wheel that stops turning is paused (0.105.37 fix), held only after a season still over unfrozen water")
def _():
    env, W = stack_world()
    p = build_power(env, W)
    wheel = [b for b in tolist(p.builds) if b.kind == "WaterWheel"][0]
    wid = env.building(wheel.cx, wheel.cy, wheel.z, "WaterWheel").id
    W.turning[wid] = False
    assert step(env, "power").waiting
    W.tick = W.tick + 15 * 1200
    r = step(env, "power")
    assert r.waiting and "paused" in r.error, dict(r)
    W.tick = W.tick + 85 * 1200
    r = step(env, "power")
    assert r.stage == "held" and "84 days of unfrozen river" in r.error, dict(r)
    r = step(env, "power", retire=True, why="held: the wheel is dry")
    assert r.ok and works(W).power.stage == "retired"
    assert W.saved[KEY].refused.power.retired == 1


@test("power: the other kinds' plans and steps are unchanged (the moat/pump paths never see `power`)")
def _():
    env, W = stack_world()
    r = env.report()
    assert r.works.pump.source is None and r.works.pump.need is None    # no power fields on other rows
    build_power(env, W)
    r = env.report()
    row = r.works.power
    assert row.kind == "power" and row.source == "wheel" and row.engaged and row.lever_at is not None
    assert row.gate is None


# --- the planner ---------------------------------------------------------

import planner_water  # noqa: E402
from planner_core import PLANNER_CONFIG  # noqa: E402


def state(design=None, pump_stage="done", power=None, river=True):
    s = {"waterworks": {"works": {"pump": {"kind": "pump", "stage": pump_stage, "gate": "open", "lift": 3}},
                        "refused": {}},
         "water": {"bodies": [{"kind": "river", "tiles": 40}] if river else []},
         "traits": {"engineering": 200},
         "date": {"year": 3, "tick": 1000},
         "settings": {"rules": {}},
         "map": {"dwarves": {"z_bottom": 90}},
         "population": {"citizens": 40}}
    if design is not None:
        s["settings"]["design"] = design
    if power is not None:
        s["waterworks"]["works"]["power"] = power
    return s


def run(s):
    props, notes = [], []
    cfg = dict(PLANNER_CONFIG)
    planner_water._waterworks_rule(s, None, cfg, props, notes)
    return props, notes


def summary(props):
    return [(p.rule, json.dumps(p.action, sort_keys=True), p.reason, p.priority) for p in props]


@test("planner: the power is begun at Guided and Architect, never at Scripts (no design setting reads Scripts)")
def _():
    from unittest import mock
    with mock.patch.object(planner_water, "young_fort", lambda s, c: False):
        for mode in ("guided", "architect"):
            props, _ = run(state(design=mode))
            pw = [p for p in props if p.action.get("kind") == "power"]
            assert pw and pw[0].action == {"type": "water_work", "kind": "power", "source": "wheel"}, summary(props)
        props, _ = run(state(design="guided", river=False))
        assert [p for p in props if p.action.get("kind") == "power"][0].action["source"] == "windmill"
        for mode in (None, "scripts"):
            props, _ = run(state(design=mode))
            assert not [p for p in props if p.action.get("kind") == "power"], summary(props)
        props, _ = run(state(design="guided", pump_stage="filling"))
        assert not [p for p in props if p.action.get("kind") == "power"]


def merged0(path: str) -> str | None:
    import subprocess
    try:
        return subprocess.run(["git", "-C", str(ROOT), "show", f"4b0de9a:{path}"], capture_output=True, text=True,
                              check=True).stdout
    except Exception:  # noqa: BLE001
        return None


@test("planner: at Scripts (and with no power work) the proposals and notes are byte-identical to merged0's rule")
def _():
    import types
    from unittest import mock
    old_src = merged0("brain/planner_water.py")
    if old_src is None:
        print("        (merged0 not reachable: skipped)")
        return
    old = types.ModuleType("planner_water_merged0")
    exec(compile(old_src, "planner_water_merged0", "exec"), old.__dict__)
    rows = [None,
            {"kind": "moat", "stage": "filling", "gate": "open", "depth": 2},
            {"kind": "irrigation", "stage": "held", "why": "water is still getting in", "gate": "shut"},
            {"kind": "magma", "stage": "done", "gate": "open", "shop": "MagmaForge"},
            {"kind": "moat", "stage": "held", "why": "liquid got out"},
            {"kind": "moat", "stage": "done", "gate": "open", "shut": "dwarves in deep water"}]
    n = 0
    for design in (None, "scripts"):
        for pump_stage in ("done", "filling", "held", "retired"):
            for river in (True, False):
                for extra in rows:
                    for wet in (0, 10):
                        st = state(design=design, pump_stage=pump_stage, river=river)
                        if extra:
                            st["waterworks"]["works"][extra["kind"]] = dict(extra)
                        if wet:
                            st["hazards"] = {"wet": [{"id": i} for i in range(wet)]}
                        outs = []
                        for mod in (planner_water, old):
                            with mock.patch.object(mod, "young_fort", lambda s, c: False):
                                props, notes = [], []
                                mod._waterworks_rule(copy.deepcopy(st), None, dict(PLANNER_CONFIG), props, notes)
                                outs.append((summary(props), notes))
                        assert outs[0] == outs[1], (st, outs)
                        n += 1
    assert n == 2 * 4 * 2 * len(rows) * 2


@test("the other kinds' steps are byte-identical to merged0's ai-waterworks.lua (a moat and a pump stack run through)")
def _():
    old_src = merged0("lua/ai-waterworks.lua")
    if old_src is None:
        print("        (merged0 not reachable: skipped)")
        return

    def trace(src):
        env = LUA.execute(FAKE, src)
        W = env.W
        for x in range(30, 90):
            for y in range(40, 80):
                W.set(x, y, 90, T(shape="FLOOR"))
        W.citizens = L(T(x=60, y=60, z=90), T(x=61, y=60, z=92))
        W.set(60, 60, 86, T(shape="FLOOR", liquid=True, depth=7))
        W.survey = T(bodies=L(T(kind="pool", tiles=1, nearest=T(x=60, y=60, z=86))))
        out = []
        for i in range(12):
            r = step(env, "pump")
            out.append(json.dumps({k: r[k] for k in ("ok", "stage", "error", "waiting") if r[k] is not None},
                                  sort_keys=True))
            wk = works(W).pump
            if i == 1:
                W.dig_all(wk.plan.dig)
            if i == 3:
                W.build_all()
            if i == 8:
                W.set(wk.plan.reservoir.x, wk.plan.reservoir.y, wk.plan.reservoir.z, T(liquid=True, depth=5))
        out.append(json.dumps([(d.x, d.y, d.z, d.text, d.mode) for d in tolist(W.designated)]))
        rep = env.report()
        out.append(json.dumps(sorted((k, v) for k, v in rep.works.pump.items() if not hasattr(v, "items"))))
        return out
    assert trace(SRC) == trace(old_src)


@test("planner: a running power is stepped each cycle (not busy), switched off in a flood, retired when held")
def _():
    from unittest import mock
    with mock.patch.object(planner_water, "young_fort", lambda s, c: False):
        row = {"kind": "power", "stage": "running", "engaged": True, "source": "wheel", "wheels": 1,
               "need": 69, "have": 100, "power": 100, "power_need": 69}
        props, notes = run(state(design="guided", power=row))
        steps = [p for p in props if p.rule == "waterworks_power_run"]
        assert steps and steps[0].action == {"type": "water_work", "kind": "power"}
        assert any("a water wheel, 100 power for 69 needed" in n for n in notes), notes
        s = state(design="scripts", power=row)
        s["hazards"] = {"wet": [{"id": i} for i in range(10)]}
        props, _ = run(s)
        shut = [p for p in props if p.rule == "waterworks_shut" and p.action.get("kind") == "power"]
        assert shut and shut[0].action["shut"] and "switch off the pump stack's power" in shut[0].reason
        props, _ = run(state(design="scripts", power=dict(row, stage="held", why="the water wheel has not turned")))
        assert any(p.action.get("retire") and p.action.get("kind") == "power" for p in props)


@test("the bridge's label and the action check know the power")
def _():
    import overseer
    assert overseer.short({"type": "water_work", "kind": "power"}) == "the pump stack's power: next step"
    assert overseer.short({"type": "water_work", "kind": "power", "shut": True}) == \
        "switch off the pump stack's power"
    act = (ROOT / "lua" / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    assert "source is wheel or windmill" in act and "source = a.source" in act
    from lua_modules_util import split_src   # (13e) the hub and its parts
    gates = split_src("ai-gates.lua")
    assert "GearAssembly = true" in gates


if __name__ == "__main__":      # (0.105.38) imported by test_r38_water.py for its fake
    finish()
