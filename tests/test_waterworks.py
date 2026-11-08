"""(0.105.0) Tests for lua/ai-waterworks.lua (the moat, magma workshops, the
muddied farm level, the pump stack) on a fake map, and the planner's rule
(brain/planner_water.py). pip install lupa.

    python tests/test_waterworks.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

try:
    from lupa import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

SRC = (ROOT / "lua" / "ai-waterworks.lua").read_text(encoding="utf-8")

# The fake map: the surface floor at z 100 (outside, over stone), open sky
# above, natural stone below; tiles set by the tests in W.tiles.
FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local W = {tiles = {}, saved = {}, designated = {}, buildings = {}, links = {}, pulls = {}, occ = {},
           citizens = {}, survey = nil, entrances = {}, tick = 1000, mud = {}}
env.W = W
function W.key(x, y, z) return x .. ',' .. y .. ',' .. z end
function W.get(x, y, z)
  local t = W.tiles[W.key(x, y, z)]
  if t then return t end
  if z > 100 then return {shape = 'OPEN_SPACE', material = 'AIR', outside = true} end
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
    local shape = ({h = 'OPEN_SPACE', j = 'STAIR_DOWN', u = 'STAIR_UP', i = 'STAIR_UPDOWN', z = 'FLOOR'})[c.text] or 'FLOOR'
    W.set(c.x, c.y, c.z, {shape = shape})
  end
end
function W.build_all(closed)
  for k, b in pairs(W.buildings) do b.built = true end
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
      local kind = c.text == 'x' and 'Floodgate' or c.text == 'Tl' and 'Trap' or c.text == 'H' and 'Hatch'
        or c.text:match('^g') and 'Bridge' or c.text:match('^Ms') and 'ScrewPump' or c.text == 'p' and 'FarmPlot'
        or c.text == 'wv' and 'Workshop' or 'Furnace'
      W.nextid = (W.nextid or 0) + 1
      W.buildings[W.key(c.x, c.y, z) .. kind] = {id = W.nextid, built = false, closed = kind == 'Floodgate' or nil}
    end
  end
  return true
end
env.building = function(x, y, z, kind) return W.buildings[W.key(x, y, z) .. kind] end
env.link = function(l, t) W.links[t] = l; return {ok = true} end
env.is_linked = function(l, t) return W.links[t] == l end
env.link_pending = function() return false end
env.pull = function(id, instant)
  table.insert(W.pulls, {id = id, instant = instant == true})
  for _, b in pairs(W.buildings) do if b.closed ~= nil then b.closed = not b.closed end end
  return true
end
env.dig_now = function(x, y, z) W.set(x, y, z, {shape = 'OPEN_SPACE'}) end
env.citizens = function() return W.citizens end
env.water_survey = function() return W.survey end
env.mud = function(x, y, z) return W.mud[W.key(x, y, z)] == true end
env.now = function() return W.tick end
env.entrances = function() return W.entrances end
env.set_name = function() end
env.lock_hatch = function(id) W.locked = id end
env.ez = function(z) return z - 100 end
env.reqscript = function() error('no reqscript in the tests') end
-- (0.105.0 review) magma-safe parts at hand unless a test says otherwise
env.magma_parts = function() return W.parts or {floodgates = 1, hatches = 1, mechanisms = 3} end
env.building_magma_safe = function(id) if W.unsafe and W.unsafe[id] then return false end return true end
env.magma_filter = function(on) W.filter = on return on == true and {} or nil end
return env
"""


LUA = LuaRuntime(unpack_returned_tuples=True)


def T(**kw):
    return LUA.table_from(kw)


def L(*items):
    return LUA.table_from(list(items))


def opts(**kw):
    return LUA.table_from(kw)


def moat_world():
    env = LUA.execute(FAKE, SRC)
    W = env.W
    # the fort's courtyard (inside, not under the sky) north of the gate at (50, 50)
    for x in range(40, 61):
        for y in range(30, 51):
            W.set(x, y, 100, T(outside=False))
    W.entrances = L(T(x=50, y=50, z=100, id=1))
    W.citizens = L(T(x=50, y=40, z=100), T(x=52, y=40, z=100))
    # a river one level under the ground, west of the approach
    for y in range(52, 58):
        W.set(40, y, 99, T(shape="FLOOR", material="RIVER", liquid=True, depth=7, outside=True))
        W.set(40, y, 100, T(shape="OPEN_SPACE", outside=True))
    W.survey = T(bodies=L(T(kind="river", tiles=6, nearest=T(x=40, y=54, z=99))))
    return env, W


def step(env, kind, **kw):
    return env.step(kind, opts(**kw))


@test("moat: planned (trench across the approach, fed from the river, a floodgate and a drawbridge), dry run first")
def _():
    env, W = moat_world()
    r = step(env, "moat", dry_run=True)
    assert r.ok and r.dry_run and r.stage == "planned", dict(r)
    p = r.plan
    assert p.gate.z == 99 and p.plug.z == 100 and p.lever.name == "AI moat"
    trench = [c for c in p.dig.values() if c.y == 54]
    assert len(trench) >= 7, len(trench)
    assert p.bridge.drawbridge and p.bridge.w == 3
    assert not list(W.designated.values()) and env.W.saved["ai-overseer/waterworks"] is None   # a dry run changes nothing
    r = step(env, "moat", plain=True, dry_run=True)
    assert not r.plan.bridge.drawbridge      # Engineering low: a plain bridge


@test("moat: refused where its water would reach the fort's inside or a citizen, saying where")
def _():
    env, W = moat_world()
    W.set(45, 55, 99, T(shape="FLOOR"))        # an underground room beside the feed channel
    r = step(env, "moat")
    assert r.rejected and "fort's inside" in r.error and "x45 y55" in r.error, r.error
    assert not list(W.designated.values())
    assert W.saved["ai-overseer/waterworks"].refused.moat.why == r.error
    env, W = moat_world()
    W.occ = T(**{"50,54,99": "a citizen"})
    r = step(env, "moat")
    assert r.rejected and "a citizen in the way" in r.error, r.error


@test("moat: refused with no river, or the river not one level under the gate's ground")
def _():
    env, W = moat_world()
    W.survey = T(bodies=L(T(kind="cavern", tiles=6, nearest=T(x=40, y=54, z=60))))
    assert "no river" in step(env, "moat").error
    env, W = moat_world()
    W.survey = T(bodies=L(T(kind="river", tiles=6, nearest=T(x=40, y=54, z=95))))
    assert "overflow or stay dry" in step(env, "moat").error


@test("moat: every stage, plug dug with the floodgate shut, opened, deep enough, done; a leak shuts it")
def _():
    env, W = moat_world()
    assert step(env, "moat").stage == "planned"
    assert step(env, "moat").stage == "digging"
    r = step(env, "moat")
    assert r.waiting and "left to dig" in r.error
    wk = W.saved["ai-overseer/waterworks"].works.moat
    W.dig_all(wk.plan.dig)
    r = step(env, "moat")
    assert r.waiting and "floodgate's floor" in r.error          # the ramp under the floodgate removed first
    W.dig_all(wk.plan.dig2)
    assert step(env, "moat").stage == "building"
    assert "being built" in step(env, "moat").error
    W.build_all()
    assert step(env, "moat").stage == "linking"
    assert step(env, "moat").stage == "filling"
    gate = env.building(wk.plan.gate.x, wk.plan.gate.y, wk.plan.gate.z, "Floodgate")
    assert gate.closed
    r = step(env, "moat")
    assert r.plug_dug and r.opening and not gate.closed
    r = step(env, "moat")
    assert r.waiting and "filling: 0/7" in r.error
    W.set(50, 54, 99, T(liquid=True, depth=5, shape="RAMP"))
    assert step(env, "moat").stage == "finishing"
    assert step(env, "moat").stage == "done"
    W.set(45, 55, 99, T(shape="FLOOR", liquid=True, depth=2))     # water where it shouldn't be
    r = step(env, "moat")
    assert r.stage == "held" and "got out" in r.error and gate.closed, dict(r)
    assert W.pulls[len(W.pulls)].instant


@test("moat: the emergency stop shuts the floodgate at once")
def _():
    env, W = moat_world()
    step(env, "moat")
    wk = W.saved["ai-overseer/waterworks"].works.moat
    wk.stage, wk.lever_id = "filling", 7
    W.buildings[W.key(wk.plan.gate.x, wk.plan.gate.y, wk.plan.gate.z) + "Floodgate"] = T(id=9, built=True, closed=False)
    r = step(env, "moat", shut=True, why="dwarves in deep water")
    assert r.shut and W.pulls[1].instant and W.pulls[1].id == 7


def magma_world():
    env = LUA.execute(FAKE, SRC)
    W = env.W
    for x in range(40, 80):
        for y in range(40, 80):
            W.set(x, y, 90, T(shape="FLOOR"))
    W.citizens = L(T(x=60, y=60, z=90), T(x=61, y=60, z=92))
    W.set(60, 60, 40, T(shape="FLOOR", liquid=True, magma=True, depth=7, material="STONE"))
    W.survey = T(bodies=L(), magma=T(z1=30, z2=40, tiles=9, top_nearest=T(x=60, y=60, z=40)))
    return env, W


@test("magma: a forge over a pit fed through a floodgate, its service stair under a locked hatch; done when full")
def _():
    env, W = magma_world()
    r = step(env, "magma", shop="MagmaForge")
    assert r.ok and r.stage == "planned", dict(r)
    wk = W.saved["ai-overseer/waterworks"].works["magma:MagmaForge"]
    p = wk.plan
    assert p.gate.z == 40 and p.room.z == 41 and p.lever.name == "AI magma"
    assert p.builds[1].kind == "Hatch" and p.builds[1].lock
    step(env, "magma", shop="MagmaForge")
    W.dig_all(p.dig)
    assert step(env, "magma", shop="MagmaForge").stage == "building"
    W.build_all()
    assert step(env, "magma", shop="MagmaForge").stage == "linking"
    assert W.locked is not None                  # the service stair's hatch locked
    assert step(env, "magma", shop="MagmaForge").stage == "filling"
    assert step(env, "magma", shop="MagmaForge").plug_dug
    W.set(p.pit.x, p.pit.y, p.pit.z, T(liquid=True, magma=True, depth=6))
    assert step(env, "magma", shop="MagmaForge").stage == "finishing"
    r = step(env, "magma", shop="MagmaForge")
    assert r.waiting and "placed over the magma" in r.error
    W.build_all()
    assert step(env, "magma", shop="MagmaForge").stage == "done"


@test("magma (0.105.0 review): no building without magma-safe parts; a part built of the wrong stuff holds it")
def _():
    env, W = magma_world()
    step(env, "magma", shop="MagmaForge")
    wk = W.saved["ai-overseer/waterworks"].works["magma:MagmaForge"]
    p = wk.plan
    step(env, "magma", shop="MagmaForge")
    W.dig_all(p.dig)
    W.parts = T(floodgates=1, hatches=0, mechanisms=1)
    r = step(env, "magma", shop="MagmaForge")
    assert r.waiting and "magma-safe" in r.error and "hatches" in r.error and "mechanisms" in r.error, dict(r)
    assert not [d for d in W.designated.values() if d.mode == "build"]          # nothing placed
    W.parts = None
    assert step(env, "magma", shop="MagmaForge").stage == "building" and W.filter is not True  # on, then restored
    W.build_all()
    gate = env.building(p.gate.x, p.gate.y, p.gate.z, "Floodgate")
    W.unsafe = LUA.table_from({gate.id: True})
    r = step(env, "magma", shop="MagmaForge")
    assert r.stage == "held" and "not magma-safe" in r.error and "floodgate" in r.error, dict(r)
    # the material test, as DF: fixed temperature, or every point above 12000
    assert env.magma_safe_heat(T(mat_fixed_temp=60001, melting_point=13600, boiling_point=16000,
                                 ignite_point=60001, heatdam_point=60001))           # green glass-like
    assert not env.magma_safe_heat(T(mat_fixed_temp=60001, melting_point=60001, boiling_point=60001,
                                     ignite_point=10400, heatdam_point=10250))        # wood
    assert not env.magma_safe_heat(T(mat_fixed_temp=60001, melting_point=11000, boiling_point=14000,
                                     ignite_point=60001, heatdam_point=60001))        # a low-melting metal
    assert env.magma_safe_heat(T(mat_fixed_temp=10000))
    assert not env.magma_safe_heat(None)


@test("magma: refused when the way down crosses a cavern, or with no magma outside the caverns")
def _():
    env, W = magma_world()
    for x in range(40, 80):
        for y in range(40, 80):
            W.set(x, y, 70, T(shape="OPEN_SPACE", feature=True))
    r = step(env, "magma")
    assert r.rejected and "cavern" in r.error, r.error
    env, W = magma_world()
    W.survey = T(bodies=L(), magma=T(z1=30, z2=40, tiles=9))
    assert "no magma found" in step(env, "magma").error


def irrigation_world():
    env = LUA.execute(FAKE, SRC)
    W = env.W
    for x in range(30, 90):
        for y in range(40, 80):
            W.set(x, y, 95, T(shape="FLOOR"))
    W.citizens = L(T(x=60, y=60, z=95), T(x=60, y=61, z=95))
    W.set(70, 60, 94, T(shape="FLOOR", liquid=True, depth=7))      # an underground pool beside the rock
    return env, W


@test("irrigation: water let into a stone room, the floodgate shut at the first wet tile, dried, plots on the mud")
def _():
    env, W = irrigation_world()
    assert step(env, "irrigation").stage == "planned"
    wk = W.saved["ai-overseer/waterworks"].works.irrigation
    p = wk.plan
    assert p.room.z == 94 and p.lever.name == "AI irrigation"
    step(env, "irrigation")
    W.dig_all(p.dig)
    step(env, "irrigation")
    W.build_all()
    step(env, "irrigation")
    assert step(env, "irrigation").stage == "filling"
    assert step(env, "irrigation").plug_dug
    assert "on its way" in step(env, "irrigation").error
    W.set(p.room.x1 + 1, p.room.y1 + 1, 94, T(liquid=True, depth=1))
    r = step(env, "irrigation")
    assert r.stage == "drying" and W.pulls[len(W.pulls)].instant
    assert "still wet" in step(env, "irrigation").error
    # (0.105.0 review) still wet past IRR_DRY_DAYS: held, saying why
    W.tick = W.tick + (env.IRR_DRY_DAYS + 1) * 1200
    r = step(env, "irrigation")
    assert r.stage == "held" and "still wet after" in r.error, dict(r)
    W.saved["ai-overseer/waterworks"].works.irrigation.stage = "drying"
    W.set(p.room.x1 + 1, p.room.y1 + 1, 94, T(liquid=False, depth=0))
    assert step(env, "irrigation").stage == "finishing"
    r = step(env, "irrigation")
    assert r.stage == "held" and "without mud" in r.error           # no mud: said, not plots on bare stone
    wk = W.saved["ai-overseer/waterworks"].works.irrigation
    wk.stage = "finishing"
    W.mud[W.key(p.room.x1 + 1, p.room.y1 + 1, 94)] = True
    r = step(env, "irrigation")
    assert r.stage == "done" and r.muddy == 1


def pump_world():
    env = LUA.execute(FAKE, SRC)
    W = env.W
    for x in range(30, 90):
        for y in range(40, 80):
            W.set(x, y, 90, T(shape="FLOOR"))
    W.citizens = L(T(x=60, y=60, z=90), T(x=61, y=60, z=92))
    W.set(60, 60, 86, T(shape="FLOOR", liquid=True, depth=7))
    W.survey = T(bodies=L(T(kind="pool", tiles=1, nearest=T(x=60, y=60, z=86))))
    return env, W


@test("pumps: a screw pump stack (one a level), a reservoir under the fort, the stair hatched; done when it rises")
def _():
    env, W = pump_world()
    r = step(env, "pump")
    assert r.ok and r.stage == "planned", dict(r)
    p = W.saved["ai-overseer/waterworks"].works.pump.plan
    pumps = [b for b in p.builds.values() if b.kind == "ScrewPump"]
    assert p.lift == 3 and len(pumps) == 3 and p.lever.name == "AI pump"
    assert any(b.kind == "Hatch" and b.lock for b in p.builds.values())
    step(env, "pump")
    W.dig_all(p.dig)
    step(env, "pump")
    W.build_all()
    step(env, "pump")
    assert step(env, "pump").stage == "filling"
    assert step(env, "pump").plug_dug
    r = step(env, "pump")
    assert r.waiting and "pumping: the reservoir 0/7" in r.error, r.error
    W.tick = W.tick + 20 * 1200
    assert "pump operator" in step(env, "pump").error
    W.set(p.reservoir.x, p.reservoir.y, p.reservoir.z, T(liquid=True, depth=5))
    r = step(env, "pump")
    assert r.stage == "done" and r.rose == 5


@test("pumps: refused when the water lies too deep, or there is none below")
def _():
    env, W = pump_world()
    W.survey = T(bodies=L(T(kind="pool", tiles=1, nearest=T(x=60, y=60, z=70))))
    W.set(60, 60, 70, T(shape="FLOOR", liquid=True, depth=7))
    assert "levels under the fort" in step(env, "pump").error
    W.survey = T(bodies=L())
    assert "no still water under the fort" in step(env, "pump").error


@test("unknown kind refused; report lists each work's stage and the refusals")
def _():
    env, W = moat_world()
    assert step(env, "lake").rejected
    step(env, "moat")
    W.survey = T(bodies=L())
    step(env, "irrigation")
    r = env.report()
    assert r.works.moat.stage == "planned" and r.works.moat.bridge == "drawbridge"
    assert r.refused.irrigation.why


# --- the planner ---------------------------------------------------------------------

def state(**over):
    s = {"date": {"year": 10, "tick": 0}, "dwarves": {"total": 60},
         "settings": {"traits": {"fortification": 100, "engineering": 0}},
         "water": {"bodies": [{"kind": "river", "tiles": 30, "nearest": {"x": 1, "y": 1, "z": 99}}]},
         "entrances": {"entrances": [{"kind": "surface", "id": 1}]},
         "waterworks": {"works": {}, "refused": {}},
         "buildings": {"workshops": {}, "furnaces": {}, "other": {}},
         "others_on_map": {}, "stocks": {"drink": 500, "prepared_meals": 500}, "farms": {"tiles": 100},
         "projects": {"open": []}, "_errors": {}}
    s.update(over)
    return s


def run(s, memory=None):
    from planner_water import _waterworks_rule
    from planner_core import PLANNER_CONFIG
    props, notes = [], []
    _waterworks_rule(s, memory, PLANNER_CONFIG, props, notes)
    return props, notes


@test("planner: a moat at high Fortification with a river and a surface gate; none when switched off or low")
def _():
    props, _ = run(state())
    assert props and props[0].action == {"type": "water_work", "kind": "moat"}, props
    s = state()
    s["settings"]["moat"] = False
    assert not [p for p in run(s)[0] if p.action.get("kind") == "moat"]
    s = state(settings={"traits": {"fortification": 0}})
    assert not run(s)[0]
    s = state(settings={"traits": {"fortification": 100, "engineering": -100}})
    assert run(s)[0][0].action.get("plain") is True
    s = state(water={"bodies": []})
    assert not run(s)[0]


@test("planner: a work under way is stepped on; a held one asks the player; a refusal waits 4 weeks")
def _():
    s = state(waterworks={"works": {"moat": {"kind": "moat", "stage": "digging"}}, "refused": {}})
    props, notes = run(s)
    assert len(props) == 1 and props[0].action == {"type": "water_work", "kind": "moat"} and "being dug" in notes[0]
    s = state(waterworks={"works": {"moat": {"kind": "moat", "stage": "held", "why": "liquid got out"}}, "refused": {}})
    props, notes = run(s)
    assert not props and any("liquid got out" in n for n in notes)
    s = state(waterworks={"works": {}, "refused": {"moat": {"tick": 10 * 403200 - 100, "why": "no gate"}}})
    props, notes = run(s)
    assert not props and any("not built: no gate" in n for n in notes)


@test("planner: a magma forge when the fort has a plain forge and magma outside the caverns; dwarves in water shut a gate")
def _():
    s = state(settings={"traits": {}},
              buildings={"workshops": {"MetalsmithsForge": 1}, "furnaces": {}, "other": {}},
              water={"bodies": [], "magma": {"z1": 30, "z2": 40, "tiles": 9, "top_nearest": {"x": 1, "y": 1, "z": 40}}},
              map={"dwarves": {"z_bottom": 90}, "layers": []})
    props, _ = run(s)
    assert props and props[0].action == {"type": "water_work", "kind": "magma", "shop": "MagmaForge"}, props
    s["map"]["layers"] = [{"name": "Cavern1", "z_top": 60, "z_bottom": 50}]
    props, notes = run(s)
    assert not props and any("beneath a cavern" in n for n in notes)
    s = state(hazards={"wet": [{"name": "a"}, {"name": "b"}]},
              waterworks={"works": {"moat": {"kind": "moat", "stage": "filling", "gate": "open"}}, "refused": {}})
    props, _ = run(s)
    assert props[0].action.get("shut") and props[0].priority == 0


@test("planner (0.105.0 review): a done work with an open floodgate is checked for leaks, and shut in a flood")
def _():
    s = state(waterworks={"works": {"magma:MagmaForge": {"kind": "magma", "stage": "done", "gate": "open",
                                                         "shop": "MagmaForge"}}, "refused": {}})
    props, notes = run(s)
    c = [p for p in props if p.rule == "waterworks_check"]
    assert c and c[0].action == {"type": "water_work", "kind": "magma", "shop": "MagmaForge"}, props
    from planner_core import PLANNER_CONFIG
    assert PLANNER_CONFIG["waterworks_check_cooldown_ticks"] >= 1200
    s["hazards"] = {"wet": [{"name": "a"}, {"name": "b"}]}
    props, _ = run(s)
    assert any(p.action.get("shut") and p.action.get("shop") == "MagmaForge" for p in props), props
    s = state(waterworks={"works": {"moat": {"kind": "moat", "stage": "held", "why": "x"}}, "refused": {}})
    _, notes = run(s)
    assert not any("the AI retires it" in n for n in notes), notes


@test("planner: the muddied farm level when no soil was found for farms")
def _():
    class M:
        farm_failure = "no soil near the fort"
    s = state(settings={"traits": {}})
    props, _ = run(s, M())
    assert props and props[0].action == {"type": "water_work", "kind": "irrigation"}


if __name__ == "__main__":
    finish()
