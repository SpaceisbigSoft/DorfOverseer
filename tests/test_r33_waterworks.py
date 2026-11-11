"""(0.105.33) Round 33, the waterworks group: lua/ai-waterworks.lua (open
space is EMPTY; the floodgate never bypassed diagonally; the emergency stop
kept until reopened; filling with an end; river pressure in the moat's dry
run), lua/ai-water.lua (a sliced survey never carried into another fort),
brain/planner_water.py (no step while shut; the pump stack proposed).

    python tests/test_r33_waterworks.py
"""

from __future__ import annotations

import re
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
WATER_SRC = (ROOT / "lua" / "ai-water.lua").read_text(encoding="utf-8")
# the fake map of tests/test_waterworks.py (one copy)
FAKE = re.search(r'FAKE = r"""(.*?)"""', (ROOT / "tests" / "test_waterworks.py").read_text(encoding="utf-8"),
                 re.S).group(1)
LUA = LuaRuntime(unpack_returned_tuples=True)
DAY = 1200


def T(**kw):
    return LUA.table_from(kw)


def L(*items):
    return LUA.table_from(list(items))


def step(env, kind, **kw):
    return env.step(kind, T(**kw))


def works(W):
    return W.saved["ai-overseer/waterworks"].works


def moat_world(river_y0=52, z2=None, fake=FAKE):
    env = LUA.execute(fake, SRC)
    W = env.W
    for x in range(40, 61):
        for y in range(30, 51):
            W.set(x, y, 100, T(outside=False))
    W.entrances = L(T(x=50, y=50, z=100, id=1))
    W.citizens = L(T(x=50, y=40, z=100), T(x=52, y=40, z=100))
    for y in range(river_y0, river_y0 + 6):
        W.set(40, y, 99, T(shape="FLOOR", material="RIVER", liquid=True, depth=7, outside=True))
        W.set(40, y, 100, T(shape="EMPTY", outside=True))
    body = dict(kind="river", tiles=6, nearest=T(x=40, y=river_y0 + 2 if river_y0 == 52 else river_y0, z=99))
    if z2 is not None:
        body["z2"] = z2
    W.survey = T(bodies=L(T(**body)))
    return env, W


def magma_world(magma=((60, 60),)):
    env = LUA.execute(FAKE, SRC)
    W = env.W
    for x in range(40, 80):
        for y in range(40, 80):
            W.set(x, y, 90, T(shape="FLOOR"))
    W.citizens = L(T(x=60, y=60, z=90), T(x=61, y=60, z=92))
    for (x, y) in magma:
        W.set(x, y, 40, T(shape="FLOOR", liquid=True, magma=True, depth=7, material="STONE"))
    W.survey = T(bodies=L(), magma=T(z1=30, z2=40, tiles=9, top_nearest=T(x=60, y=60, z=40)))
    return env, W


def irrigation_world():
    env = LUA.execute(FAKE, SRC)
    W = env.W
    for x in range(30, 90):
        for y in range(40, 80):
            W.set(x, y, 95, T(shape="FLOOR"))
    W.citizens = L(T(x=60, y=60, z=95), T(x=60, y=61, z=95))
    W.set(70, 60, 94, T(shape="FLOOR", liquid=True, depth=7))
    return env, W


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


def to_filling(env, W, kind, **kw):
    """Every stage up to filling, the plug dug and the floodgate opened."""
    step(env, kind, **kw)
    step(env, kind, **kw)
    wk = works(W)[next(iter(works(W).keys()))]
    W.dig_all(wk.plan.dig)
    if wk.plan.dig2:
        step(env, kind, **kw)
        W.dig_all(wk.plan.dig2)
    assert step(env, kind, **kw).stage == "building"
    W.build_all()
    assert step(env, kind, **kw).stage == "linking"
    assert step(env, kind, **kw).stage == "filling"
    r = step(env, kind, **kw)
    assert r.plug_dug, dict(r)
    wk = works(W)[next(iter(works(W).keys()))]
    gate = env.building(wk.plan.gate.x, wk.plan.gate.y, wk.plan.gate.z, "Floodgate")
    return wk, gate


def cheb(a, b):
    return max(abs(a.x - b.x), abs(a.y - b.y))


# --- shapes: open space is EMPTY ------------------------------------------------------

@test("waterworks (L5 45/775): no shape test for 'OPEN_SPACE' (tile_info gives EMPTY); a channel dug to EMPTY counts")
def _():
    code = "\n".join(line.split("--")[0] for line in SRC.splitlines())
    assert "OPEN_SPACE" not in code
    env, W = magma_world()
    step(env, "magma", shop="MagmaForge")
    step(env, "magma", shop="MagmaForge")
    p = works(W)["magma:MagmaForge"].plan
    W.dig_all(p.dig)
    for c in p.dig.values():
        if c.text == "h":
            W.set(c.x, c.y, c.z, T(shape="EMPTY"))
    r = step(env, "magma", shop="MagmaForge")
    assert r.stage == "building", dict(r)


@test("waterworks (L5 370-375): the dry run follows water falling through open space (EMPTY) to the fort below")
def _():
    env, W = moat_world()
    W.set(50, 55, 99, T(shape="EMPTY", outside=True))
    W.set(50, 55, 98, T(shape="FLOOR", outside=False))
    r = step(env, "moat", dry_run=True)
    assert not r.ok and "fort's inside" in r.error and "x50 y55" in r.error, dict(r)


@test("waterworks (L5 365): pumped water climbs through open space (EMPTY) above the stack in the dry run")
def _():
    env, W = pump_world()
    r = step(env, "pump", dry_run=True)
    assert r.ok, dict(r)
    p = r.plan
    rv = p.reservoir                     # open space over a reservoir corner, a room above it
    W.set(rv.x + 1, rv.y + 1, rv.z + 1, T(shape="EMPTY"))
    r2 = env.path_check(p)
    assert not r2.ok and "spread past" in r2.why and (r2.at.x, r2.at.y, r2.at.z) == (rv.x + 1, rv.y + 1, rv.z + 1), dict(r2)


# --- the floodgate never bypassed -------------------------------------------------------

@test("waterworks (L5 466-478): the moat's feed never turns its corner at the floodgate (water round it diagonally)")
def _():
    env, W = moat_world(river_y0=56)
    r = step(env, "moat", dry_run=True)
    assert r.ok, dict(r)
    p = r.plan
    for c in p.wet.values():
        if c.z == p.gate.z and not (c.x == p.plug.x and c.y == p.plug.y) and not (c.x == p.gate.x and c.y == p.gate.y):
            assert cheb(c, p.plug) > 1, ("wet tile beside the plug", c.x, c.y)
    assert env.bypass(p) is None
    # the old plan's shape (the corner at the gate) is refused by the check
    p.gate.x, p.gate.y = 40, 54          # gate (40,54), plug (40,55): feed tile (41,54) beside the plug
    p.plug.x, p.plug.y = 40, 55
    p.wet = L(T(x=41, y=54, z=99), T(x=40, y=54, z=99), T(x=40, y=55, z=99))
    p.tiles, p.dig, p.dig2 = p.wet, L(), L()
    b = env.bypass(p)
    assert b and "round the floodgate" in b.why and (b.x, b.y) == (41, 54), b and dict(b)


@test("waterworks (L5 697/744-749): magma beside the pit or the gate: that site refused, never planned beside it")
def _():
    hot = [(62, 61), (61, 61), (60, 61)]
    env, W = magma_world(magma=[(60, 60)] + hot)
    r = step(env, "magma", shop="MagmaForge", dry_run=True)
    if r.ok:
        p = r.plan
        for c in list(p.dig.values()) + list(p.wet.values()):
            if c.z == 40 and not (c.x == p.plug.x and c.y == p.plug.y):
                for (mx, my) in hot + [(60, 60)]:
                    assert max(abs(c.x - mx), abs(c.y - my)) > 1, ("dug tile beside magma", c.x, c.y)
    # the plan the audit found (pit (63,60), gate (62,60), plug (61,60)) with magma at (62,61): refused
    env, W = magma_world()
    p = step(env, "magma", shop="MagmaForge", dry_run=True).plan
    assert (p.pit.x, p.gate.x, p.plug.x) == (63, 62, 61) and env.bypass(p) is None
    W.set(62, 61, 40, T(shape="FLOOR", liquid=True, magma=True, depth=7))
    b = env.bypass(p)
    assert b and "round the floodgate" in b.why, b and dict(b)
    assert not env.path_check(p).ok


@test("waterworks: the magma service tunnel joins the pit's side, never the gate's flank (it touched the plug)")
def _():
    env, W = magma_world()
    r = step(env, "magma", shop="MagmaForge", dry_run=True)
    assert r.ok, dict(r)
    p = r.plan
    assert env.bypass(p) is None
    up = [p.plug] + list((p.upstream or T()).values())
    for c in p.dig.values():
        if c.z != 40 or (c.x, c.y) in [(p.gate.x, p.gate.y)] + [(u.x, u.y) for u in up]:
            continue
        for u in up:
            assert cheb(c, u) > 1, ("fort-side tile beside the source side", c.x, c.y)


@test("waterworks (L5 646): irrigation's tunnel never dug beside other water (diagonal)")
def _():
    env, W = irrigation_world()
    r = step(env, "irrigation", dry_run=True)
    assert r.ok, dict(r)
    p = r.plan
    mid = [c for c in p.dig.values() if c.z == 94 and not (c.x == p.plug.x and c.y == p.plug.y)
           and not (p.room.x1 <= c.x <= p.room.x2 and p.room.y1 <= c.y <= p.room.y2)][0]
    W.set(mid.x + 1, mid.y + 1, 94, T(shape="FLOOR", liquid=True, depth=3))
    b = env.bypass(p)
    assert b and "liquid beside" in b.why, b and dict(b)
    assert not env.path_check(p).ok


@test("waterworks (L5 541/358): liquid met from the fort's side in the dry run is refused, not taken for the source")
def _():
    env, W = pump_world()
    p = step(env, "pump", dry_run=True).plan
    # a pocket of water one level under the sump: met from a fort-side tile
    sump = [c for c in p.dig.values() if c.z == 86 and c.text == "d" and cheb(c, p.plug) == 2][0]
    W.set(sump.x, sump.y, 86, T(shape="EMPTY"))
    W.set(sump.x, sump.y, 85, T(shape="FLOOR", liquid=True, depth=4))
    r = env.path_check(p)
    assert not r.ok and "round the floodgate" in r.why, dict(r)


@test("waterworks (L5 448 Med): river pressure: climbs onto the ground only when the river runs higher than the gate's ground")
def _():
    env, W = moat_world()
    p = step(env, "moat", dry_run=True).plan
    assert p.pressure and p.pressure_top == 98
    env, W = moat_world(z2=101)               # the river's upper reach two levels up: water could rise to 100
    r = step(env, "moat", dry_run=True)
    assert not r.ok, dict(r)                  # up through the channels onto the ground: refused
    env, W = moat_world(z2=99)                # the river no higher than here: no climb, planned
    assert step(env, "moat", dry_run=True).ok


# --- the emergency stop ---------------------------------------------------------------

@test("waterworks (L5 853-865): a shut floodgate stays shut; the steps wait; reopened only when asked, days later")
def _():
    env, W = moat_world()
    wk, gate = to_filling(env, W, "moat")
    assert not gate.closed
    r = step(env, "moat", shut=True, why="dwarves in deep water")
    assert r.shut and gate.closed and W.cancelled, dict(r)       # the pending pull called off too
    n = len(W.pulls)
    for _ in range(3):
        W.tick += 3 * DAY
        r = step(env, "moat")
        assert r.waiting and "shut" in r.error and gate.closed, dict(r)
    assert len(W.pulls) == n
    W.tick += 3 * DAY
    step(env, "moat", shut=True, why="dwarves in deep water")     # (gate already shut: nothing pulled)
    assert len(W.pulls) == n and gate.closed
    r = step(env, "moat", why="reopen: no dwarves in deep water now")
    assert r.waiting and "under 3 days" in r.error and gate.closed, dict(r)
    W.tick += 4 * DAY
    r = step(env, "moat", reopen=True)
    assert r.reopened and r.opening and not gate.closed and not W.pulls[len(W.pulls)].instant, dict(r)
    assert works(W).moat.shut is None
    r = step(env, "moat")
    assert r.waiting and "filling" in r.error, dict(r)


@test("waterworks: shut three times for a flood (dwarves in deep water near it, within 28 days): held")
def _():
    env, W = moat_world()
    wk, _g = to_filling(env, W, "moat")
    c = wk.plan.wet[1]                   # (0.105.36) a citizen in deep water in the work itself
    W.set(c.x, c.y, c.z, T(liquid=True, depth=7))
    W.citizens = L(T(x=c.x, y=c.y, z=c.z))
    for _ in range(3):
        r = step(env, "moat", shut=True, why="dwarves in deep water")
    assert r.stage == "held" and "3 times" in works(W).moat.why


@test("waterworks (L5 1044-1051): irrigation's stop shuts the floodgate, never toggles a shut one open")
def _():
    env, W = irrigation_world()
    wk, gate = to_filling(env, W, "irrigation")
    p = wk.plan
    gate.closed = True                    # (the player shut it already)
    wk2 = works(W).irrigation
    wk2.opened_once = True
    W.set(p.room.x1 + 1, p.room.y1 + 1, 94, T(liquid=True, depth=1))
    n = len(W.pulls)
    r = step(env, "irrigation")
    assert r.stage == "drying" and gate.closed and len(W.pulls) == n, dict(r)


# --- filling with an end ----------------------------------------------------------------

@test("waterworks (L5 1021-1048 Med): filling with no rise for 28 days is held, the floodgate shut, saying why")
def _():
    env, W = moat_world()
    wk, gate = to_filling(env, W, "moat")
    assert "filling: 0/7" in step(env, "moat").error
    W.tick += 20 * DAY
    assert step(env, "moat").waiting
    W.tick += 10 * DAY
    r = step(env, "moat")
    assert r.stage == "held" and "has not risen" in r.error and gate.closed, dict(r)
    # irrigation: no water in the room
    env, W = irrigation_world()
    wk, gate = to_filling(env, W, "irrigation")
    assert "on its way" in step(env, "irrigation").error
    W.tick += 29 * DAY
    r = step(env, "irrigation")
    assert r.stage == "held" and "no water reached" in r.error and gate.closed, dict(r)
    # the pump: said at 14 days, held at 28
    env, W = pump_world()
    wk, gate = to_filling(env, W, "pump")
    step(env, "pump")
    W.tick += 20 * DAY
    assert "pump operator" in step(env, "pump").error
    W.tick += 10 * DAY
    r = step(env, "pump")
    assert r.stage == "held" and "not risen" in r.error, dict(r)


@test("waterworks: a floodgate nobody opens is held after 28 days, not waited on for ever")
def _():
    env, W = moat_world()
    wk, gate = to_filling(env, W, "moat")
    gate.closed = True                    # the dwarf never got there
    assert "on the way" in step(env, "moat").error
    W.tick += 29 * DAY
    r = step(env, "moat")
    assert r.stage == "held" and "not opened" in r.error, dict(r)


# --- the Lows ----------------------------------------------------------------------------

@test("waterworks (L5 925 Low): a magma dry run at the building step leaves buildingplan's filter alone")
def _():
    env, W = magma_world()
    step(env, "magma", shop="MagmaForge")
    step(env, "magma", shop="MagmaForge")
    W.dig_all(works(W)["magma:MagmaForge"].plan.dig)
    r = step(env, "magma", shop="MagmaForge", dry_run=True)
    assert r.dry_run and r.stage == "building" and W.filter is None, dict(r)


@test("waterworks (L5 1122 Low): the report fetches the levers' links once, not once a work")
def _():
    fake = FAKE.replace("env.is_linked = function(l, t) return W.links[t] == l end", "")
    assert fake != FAKE
    env, W = moat_world(fake=fake)
    calls = []
    env.lever_links = lambda: (calls.append(1), LUA.table_from({9: L(7)}))[1]
    W.saved["ai-overseer/waterworks"] = T(refused=T(), works=T(
        moat=T(kind="moat", stage="done", lever_id=7, gate_id=9, plan=T()),
        pump=T(kind="pump", stage="done", lever_id=8, gate_id=9, plan=T())))
    r = env.report()
    assert len(calls) == 1 and r.works.moat.linked is True and r.works.pump.linked is None, (calls, dict(r.works.moat))


# --- ai-water.lua: the sliced survey ----------------------------------------------------

WATER_FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local F = {site = 1, save = 'region1', put = {}, handlers = {}}
env.F = F
env.SC_MAP_UNLOADED = 5
env.reqscript = function() return {site_put = function(k, v) F.put[k] = v end, site_get = function() return nil end} end
env.dfhack = {onStateChange = F.handlers,
              units = {getCitizens = function() return {{}} end, getPosition = function() return F.x or 50, 50, 100 end},
              maps = {getTileSize = function() return 200, 200, 200 end, getBlock = function() return nil end}}
env.df = setmetatable({}, {__index = function(_, k)
  if k == 'global' then return {plotinfo = {site_id = F.site}, world = {cur_savegame = {save_dir = F.save}}} end
end})
assert(load(src, 'ai-water', 't', env))()
return env
"""


@test("ai-water (L5 188-205 Med): a half-done survey is dropped when the map unloads or another fort is loaded")
def _():
    env = LUA.execute(WATER_FAKE, WATER_SRC)
    F = env.F
    r = env.scan_step(1, 0)                      # one level a call: not done
    assert r.ok and r.done is False and env.scanning()
    F.handlers["ai-water"](env.SC_MAP_UNLOADED)
    assert not env.scanning()
    env.scan_step(1, 0)
    assert env.JOB.mid.x == 50
    F.site, F.x = 2, 120                          # another fort, its citizens elsewhere
    env.scan_step(2, 0)
    assert env.JOB.fort == "region1:2" and env.JOB.mid.x == 120, env.JOB.fort


# --- the planner --------------------------------------------------------------------------

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


@test("planner_water (L5 122): a shut work gets no step while dwarves are in deep water; then it is asked to reopen")
def _():
    row = {"kind": "moat", "stage": "filling", "gate": "shut", "shut": "dwarves in deep water"}
    s = state(hazards={"wet": [{"name": "a"}, {"name": "b"}]}, waterworks={"works": {"moat": row}, "refused": {}})
    props, notes = run(s)
    assert not props and any("was shut" in n for n in notes), (props, notes)
    s = state(waterworks={"works": {"moat": row}, "refused": {}})
    props, _ = run(s)
    assert len(props) == 1 and props[0].action.get("reopen") is True, props
    assert props[0].action["why"].startswith("reopen") and not props[0].action.get("shut")
    assert props[0].rule == "waterworks_moat"


@test("planner_water (T1 203-208 Med): the pump stack when there is no well, no cistern site, and water only below")
def _():
    base = dict(settings={"traits": {"fortification": 0, "engineering": 0}},
                water={"bodies": [{"kind": "pool", "tiles": 4, "nearest": {"x": 1, "y": 1, "z": 80}}],
                       "cistern": {"none": True}},
                map={"dwarves": {"z_bottom": 90}})
    props, _ = run(state(**base))
    assert [p.action for p in props] == [{"type": "water_work", "kind": "pump"}], props
    s = state(**base)
    s["buildings"] = {"workshops": {}, "furnaces": {}, "other": {"Well": 1}}
    assert not run(s)[0]                                     # a well: no pumps
    s = state(**base)
    s["water"] = dict(base["water"], bodies=[{"kind": "pool", "tiles": 4, "nearest": {"x": 1, "y": 1, "z": 95}}])
    assert not run(s)[0]                                     # the water not below the fort
    s = state(**dict(base, settings={"traits": {"fortification": 0, "engineering": -50}}))
    assert not run(s)[0]                                     # Engineering too low


if __name__ == "__main__":
    finish()
