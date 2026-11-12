"""(0.105.40b) The insane: lua/ai-insane.lua in a fake fort (each kind
reported with where they are and the deadly ground near them; the AI's own
doors locked between a melancholy or raving dwarf and deep water, magma or a
drop while they are near, freed as they move off, after two days, never the
player's, a lever's, a gate's, a well's or one already locked; the
near-breaking listed), the bridge's wiring, the brain (brain/planner_insane.py:
a note per kind that says what the AI does, the guard proposed, the
near-breaking first in the stress care) and plan() without the section the
same as main's on every fixture.

    python tests/test_r41_insane.py
"""

from __future__ import annotations

import atexit
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
import planner_insane as PI  # noqa: E402
import planner_society as PS  # noqa: E402
from digest import normalize, SECTION_DEFAULTS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
DAY = 1200

# The fake fort: tiles W.tiles["x,y,z"] = {flow_size, liquid_type, hidden,
# shape} (default: a dry floor); units W.unit{...}; doors W.door{...};
# the AI's levels W.projects (each {kind, areas = {{x1, y1, x2, y2, z}}}).
FAKE = r"""
local src = ...
local W = {units = {}, tiles = {}, doors = {}, hatches = {}, projects = {}, old_areas = {}, site = {},
           citizens = {}, gates = {}, zones = {}, claimed = {}}
local env = setmetatable({}, {__index = _G})
local key = function(x, y, z) return x .. ',' .. y .. ',' .. z end
local MOODS = {[0] = 'Fey', 'Secretive', 'Possessed', 'Macabre', 'Fell', 'Melancholy', 'Raving', 'Berserk',
               'Baby', 'Traumatized'}
W.MOOD = {}
for i, n in pairs(MOODS) do W.MOOD[n] = i end
function W.unit(t)
    t.civ_id = t.civ_id or 10
    t.mood = t.mood or -1
    t.pos = t.pos or {x = 50, y = 50, z = 100}
    table.insert(W.units, t)
    if t.citizen then table.insert(W.citizens, t) end
    return t
end
function W.door(t)
    t.centerx, t.centery = t.x, t.y
    t.door_flags = t.door_flags or {forbidden = false, operated_by_mechanisms = false}
    t.stage = t.stage or 1
    t.getBuildStage = function(self) return self.stage end
    t.getMaxBuildStage = function() return 1 end
    if t.hatch then table.insert(W.hatches, t) else table.insert(W.doors, t) end
    return t
end
function W.tile(x, y, z, t) W.tiles[key(x, y, z)] = t end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {
    global = {cur_year = 200, cur_year_tick = 0,
              world = {units = {active = W.units},
                       buildings = {other = {DOOR = W.doors, HATCH = W.hatches}, all = {}}},
              plotinfo = {civ_id = 10}},
    mood_type = MOODS,
    tiletype = {attrs = setmetatable({}, {__index = function(_, k) return {shape = k} end})},
    tiletype_shape = setmetatable({}, {__index = function(_, k) return k end}),
    building = {find = function(id)
        for _, l in ipairs({W.doors, W.hatches}) do
            for _, b in ipairs(l) do if b.id == id and not b.gone then return b end end
        end
    end},
    building_civzonest = {is_instance = function(_, b) return b.zone == true end},
    civzone_type = setmetatable({}, {__index = function(_, k) return k end}),
}
env.dfhack = {
    df2utf = function(s) return s end,
    units = {isDead = function(u) return u.dead == true end,
             isOwnGroup = function(u) return u.own == true end,
             getReadableName = function(u) return u.name or ('dwarf ' .. u.id) end,
             getPosition = function(u) return u.pos.x, u.pos.y, u.pos.z end,
             getStressCategory = function(u) return u.cat or 3 end,
             getCitizens = function() return W.citizens end},
    maps = {getTileFlags = function(x, y, z)
                local t = W.tiles[key(x, y, z)] or {}
                return {flow_size = t.flow_size or 0, liquid_type = t.liquid_type or false, hidden = t.hidden or false}
            end,
            getTileType = function(x, y, z)
                local t = W.tiles[key(x, y, z)] or {}
                return t.shape or 'FLOOR'
            end},
    buildings = {findCivzonesAt = function(p) return W.zones[key(p.x, p.y, p.z)] end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
env.reqscript = function(name)
    if name == 'ai-builder' then
        return {load_projects = function() return {list = W.projects, old_areas = W.old_areas} end,
                project_areas = function(p) return p.areas end}
    elseif name == 'ai-gates' then
        return {GATES = {entrances = {{equipment = W.gates}}}}
    elseif name == 'ai-threats' then
        return {claimed_doors = function() return W.claimed end}
    end
    error('no module ' .. tostring(name))
end
assert(load(src, 'ai-insane', 't', env))()
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-insane.lua"))
    return lua, env, w


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
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in sorted(keys)]
    return {k: py(v[k]) for k in keys}


def fort(lua, w, kind="Melancholy", pos=(50, 50, 100), wall=True):
    """An insane dwarf at `pos`, deep water at x 57-59 on their level, the AI's
    level (a box round x 40-60) holding a door at (55, 50) between them, in a
    wall along x 55 (y 30-70) with no other way through."""
    u = w.unit(T(lua, {"id": 7, "name": "Urist", "mood": w.MOOD[kind], "own": True,
                       "pos": {"x": pos[0], "y": pos[1], "z": pos[2]}}))
    if wall:
        for y in range(30, 71):
            if y != 50:
                w.tile(55, y, 100, T(lua, {"shape": "WALL"}))
    for x in (57, 58, 59):
        for y in (49, 50, 51):
            w.tile(x, y, 100, T(lua, {"flow_size": 7}))
    w.projects[1] = T(lua, {"kind": "bedrooms", "areas": [{"x1": 40, "y1": 40, "x2": 60, "y2": 60, "z": 100}]})
    d = w.door(T(lua, {"id": 300, "x": 55, "y": 50, "z": 100}))
    return u, d


def advance(env, ticks):
    g = env.df["global"]
    g.cur_year_tick = g.cur_year_tick + ticks


def guard(lua, env, units=None, dry=False):
    o = T(lua, {"units": units}) if units is not None else T(lua, {})
    return py(env.guard(o, dry))


# --- 1. the report: each kind ------------------------------------------------------

@test("report: a melancholy dwarf: kind, where, the deep water near them, the AI's door between that the guard would lock")
def _():
    lua, env, w = world()
    fort(lua, w)
    w.zones["50,50,100"] = T(lua, [{"type": "DiningHall"}])
    r = py(env.report())
    assert len(r["list"]) == 1 and r["locks"] == 0, r
    row = r["list"][0]
    assert row["kind"] == "melancholy" and row["mood"] == "Melancholy" and row["id"] == 7, row
    assert (row["x"], row["y"], row["z"]) == (50, 50, 100) and row["place"] == "DiningHall", row
    assert row["hazards"] == {"water": 7} and row["doors"] == 1 and row["locked"] == 0, row


@test("report: raving near magma is guarded too; catatonic and berserk are listed without a scan or doors")
def _():
    lua, env, w = world()
    w.unit(T(lua, {"id": 1, "mood": w.MOOD["Raving"], "own": True, "pos": {"x": 50, "y": 50, "z": 100}}))
    w.unit(T(lua, {"id": 2, "mood": w.MOOD["Traumatized"], "own": True, "pos": {"x": 20, "y": 20, "z": 100}}))
    w.unit(T(lua, {"id": 3, "mood": w.MOOD["Berserk"], "own": True, "pos": {"x": 80, "y": 80, "z": 100}}))
    w.tile(52, 50, 99, T(lua, {"flow_size": 1, "liquid_type": True}))
    w.tile(22, 20, 100, T(lua, {"flow_size": 7}))
    rows = {r["id"]: r for r in py(env.report())["list"]}
    assert rows[1]["kind"] == "raving" and rows[1]["hazards"] == {"magma": 5} and rows[1]["doors"] == 0, rows[1]
    assert rows[2]["kind"] == "catatonic" and "hazards" not in rows[2] and "doors" not in rows[2], rows[2]
    assert rows[3]["kind"] == "berserk" and "hazards" not in rows[3] and "doors" not in rows[3], rows[3]


@test("report: only the fort's own, alive, insane; a strange mood or a baby is no insanity")
def _():
    lua, env, w = world()
    w.unit(T(lua, {"id": 1, "mood": w.MOOD["Melancholy"], "civ_id": 99}))          # a visitor
    w.unit(T(lua, {"id": 2, "mood": w.MOOD["Melancholy"], "own": True, "dead": True}))
    w.unit(T(lua, {"id": 3, "mood": w.MOOD["Fey"], "own": True}))
    w.unit(T(lua, {"id": 4, "mood": w.MOOD["Baby"], "own": True}))
    w.unit(T(lua, {"id": 5, "mood": w.MOOD["Melancholy"], "civ_id": 10}))          # the fort's civ: own
    rows = py(env.report())["list"] or []
    assert [r["id"] for r in rows] == [5], rows


@test("report: deadly ground: shallow or unseen water is none, a drop is open space over open space, magma at any depth")
def _():
    lua, env, w = world()
    w.unit(T(lua, {"id": 1, "mood": w.MOOD["Melancholy"], "own": True, "pos": {"x": 50, "y": 50, "z": 100}}))
    w.tile(51, 50, 100, T(lua, {"flow_size": 3}))                    # shallow
    w.tile(52, 50, 100, T(lua, {"flow_size": 7, "hidden": True}))    # unseen
    w.tile(53, 50, 100, T(lua, {"shape": "EMPTY"}))                  # a hole onto a floor below: no drop
    assert py(env.report())["list"][0]["hazards"] == {}, py(env.report())
    w.tile(53, 50, 99, T(lua, {"shape": "EMPTY"}))                   # now a fall of two levels
    w.tile(56, 50, 98, T(lua, {"flow_size": 2, "liquid_type": True}))
    assert py(env.report())["list"][0]["hazards"] == {"drop": 3, "magma": 12}, py(env.report())


# --- 2. the guard: the doors ------------------------------------------------------------

@test("guard: the AI's door between a melancholy dwarf and deep water is locked and recorded; a dry run changes nothing")
def _():
    lua, env, w = world()
    _, d = fort(lua, w)
    r = guard(lua, env, dry=True)
    assert r["locked"] == 1 and r["dry_run"] is True and d.door_flags.forbidden is False and not list(w.site.keys()), r
    r = guard(lua, env, [7])
    assert r["ok"] and r["locked"] == 1 and r["held"] == 1 and r["doors"] == [{"id": 300, "unit": 7, "hazard": "water"}], r
    assert d.door_flags.forbidden is True
    rep = py(env.report())
    assert rep["locks"] == 1 and rep["list"][0]["locked"] == 1 and rep["list"][0]["doors"] == 0, rep
    # again: nothing more
    assert guard(lua, env, [7])["locked"] == 0 and d.door_flags.forbidden is True


@test("guard: opened again as soon as the dwarf moves off, and when they die")
def _():
    lua, env, w = world()
    u, d = fort(lua, w)
    guard(lua, env, [7])
    u.pos.x = 20                                    # far off
    r = guard(lua, env, [7])
    assert r["released"] == 1 and r["held"] == 0 and d.door_flags.forbidden is False, r
    u.pos.x = 50
    guard(lua, env, [7])
    assert d.door_flags.forbidden is True
    u.dead = True
    r = guard(lua, env, [])
    assert r["released"] == 1 and d.door_flags.forbidden is False, r


@test("guard: a lock is held two days at most, then left open half a day before it may be locked again")
def _():
    lua, env, w = world()
    _, d = fort(lua, w)
    guard(lua, env, [7])
    advance(env, 2399)
    assert guard(lua, env, [7])["released"] == 0 and d.door_flags.forbidden is True
    advance(env, 1)
    r = guard(lua, env, [7])
    assert r["released"] == 1 and r["locked"] == 0 and d.door_flags.forbidden is False, r
    advance(env, 599)
    assert guard(lua, env, [7])["locked"] == 0 and d.door_flags.forbidden is False
    assert py(env.report())["list"][0]["doors"] == 0          # resting: not counted as one to lock
    advance(env, 1)
    assert guard(lua, env, [7])["locked"] == 1 and d.door_flags.forbidden is True


@test("guard: never the player's door (outside the AI's levels), a lever's, a gate's, a well's, one unbuilt or already locked")
def _():
    cases = {
        "player": lambda lua, w, d: setattr(w.projects[1], "areas", T(lua, [{"x1": 0, "y1": 0, "x2": 10, "y2": 10, "z": 100}])),
        "lever": lambda lua, w, d: setattr(d.door_flags, "operated_by_mechanisms", True),
        "gate_live": lambda lua, w, d: w.gates.__setitem__(1, T(lua, {"id": 300})),
        "gate_saved": lambda lua, w, d: w.site.__setitem__("ai-overseer/gates", T(lua, {"gates": [{"id": 300}]})),
        "well": lambda lua, w, d: setattr(w.projects[1], "kind", "well"),
        "unbuilt": lambda lua, w, d: setattr(d, "stage", 0),
    }
    for why, setup in cases.items():
        lua, env, w = world()
        _, d = fort(lua, w)
        setup(lua, w, d)
        r = guard(lua, env, [7])
        assert r["locked"] == 0 and d.door_flags.forbidden is False, (why, r)
        assert py(env.report())["list"][0]["doors"] == 0, why
    # an old level's outline (dropped from the list) is still the AI's
    lua, env, w = world()
    _, d = fort(lua, w)
    w.projects[1] = None
    w.old_areas[1] = T(lua, {"x1": 40, "y1": 40, "x2": 60, "y2": 60, "z": 100})
    assert guard(lua, env, [7])["locked"] == 1
    # already locked (the player's, or another rule's): left alone, and never opened by the guard
    lua, env, w = world()
    u, d = fort(lua, w)
    d.door_flags.forbidden = True
    assert guard(lua, env, [7])["locked"] == 0
    u.pos.x = 10
    assert guard(lua, env, [7])["released"] == 0 and d.door_flags.forbidden is True


@test("guard: a door not in the way (behind the dwarf, or far from the water) is left open")
def _():
    lua, env, w = world()
    u, d = fort(lua, w, pos=(58, 47, 100))     # by the water already, the door behind
    d.x = d.centerx = 52
    assert guard(lua, env, [7])["locked"] == 0 and d.door_flags.forbidden is False
    lua, env, w = world()
    u, d = fort(lua, w)
    d.centerx, d.centery = 51, 40               # 10 from the dwarf, 17 from the water
    assert guard(lua, env, [7])["locked"] == 0


@test("guard: a hatch is never locked (a way between levels); a raving dwarf is guarded; a catatonic, a berserk "
      "or one not asked for is not")
def _():
    lua, env, w = world()
    _, d = fort(lua, w, kind="Raving")
    assert guard(lua, env, [7])["locked"] == 1 and d.door_flags.forbidden is True
    lua, env, w = world()
    _, d = fort(lua, w, kind="Raving")
    d.hatch = True
    w.doors[1] = None
    w.hatches[1] = d
    assert guard(lua, env, [7])["locked"] == 0 and d.door_flags.forbidden is False
    for kind in ("Traumatized", "Berserk"):
        lua, env, w = world()
        _, d = fort(lua, w, kind=kind)
        assert guard(lua, env)["locked"] == 0, kind
    lua, env, w = world()
    _, d = fort(lua, w)
    assert guard(lua, env, [99])["locked"] == 0 and guard(lua, env)["locked"] == 1


@test("guard: a lock someone else opened is forgotten and not locked again for a week")
def _():
    lua, env, w = world()
    _, d = fort(lua, w)
    guard(lua, env, [7])
    d.door_flags.forbidden = False                   # the player opened it
    r = guard(lua, env, [7])
    assert r["released"] == 0 and r["locked"] == 0 and r["held"] == 0 and d.door_flags.forbidden is False, r
    advance(env, 7 * DAY - 1)
    assert guard(lua, env, [7])["locked"] == 0
    advance(env, 1)
    assert guard(lua, env, [7])["locked"] == 1


@test("guard: never more than 12 locks held")
def _():
    lua, env, w = world()
    fort(lua, w)
    for x in (57, 58, 59):
        for y in range(41, 60):
            w.tile(x, y, 100, T(lua, {"flow_size": 7}))
    spots = [(55, y) for y in range(41, 60) if y != 50]       # a wall of doors, all between
    for i, (x, y) in enumerate(spots):
        w.tile(x, y, 100, T(lua, {"shape": "FLOOR"}))
        w.door(T(lua, {"id": 400 + i, "x": x, "y": y, "z": 100}))
    assert py(env.report())["list"][0]["doors"] == len(spots) + 1
    r = guard(lua, env, [7])
    assert r["held"] == 12 and r["locked"] == 12, r
    assert guard(lua, env, [7])["locked"] == 0


# --- 3. the near-breaking -----------------------------------------------------------------

@test("at risk: long-term stress 25000+ while unhappy or worse, the most first, with their room and squad; read once a day")
def _():
    lua, env, w = world()
    def cit(i, lt, cat, **kw):
        t = {"id": i, "citizen": True, "cat": cat, "own": True,
             "status": {"current_soul": {"personality": {"longterm_stress": lt}}},
             "military": {"squad_id": kw.get("squad", -1), "squad_position": kw.get("pos", 1)},
             "owned_buildings": [{"zone": True, "type": "Bedroom"}] if kw.get("bed") else []}
        w.unit(T(lua, t))
    cit(1, 30000, 1)
    cit(2, 120000, 2, squad=4, pos=0, bed=True)
    cit(3, 90000, 3)        # fine: not at risk
    cit(4, 10000, 0)        # little long-term stress
    r = py(env.report())
    assert [x["id"] for x in r["at_risk"]] == [2, 1] and r["at_risk_total"] == 2, r
    two = r["at_risk"][0]
    assert two["stress"] == "unhappy" and two["longterm"] == 120000 and two["bedroom"] is True, two
    assert two["squad"] is True and two["leader"] is True, two
    assert r["at_risk"][1]["bedroom"] is False and r["at_risk"][1].get("squad") is None, r
    w.citizens[3].cat = 0
    assert [x["id"] for x in py(env.report())["at_risk"]] == [2, 1]      # the same day: as read
    advance(env, DAY)
    assert [x["id"] for x in py(env.report())["at_risk"]] == [2, 3, 1]


# --- 4. the bridge's wiring ---------------------------------------------------------------

@test("bridge: the insane section (safe, in the pulse), the insane_guard action (its dry run, ids checked), the module listed")
def _():
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "insane = function() return safe(function() return reqscript('ai-insane').report() end) end," in src
    pulse = src[src.index("PULSE_SECTIONS = {"):src.index("}", src.index("PULSE_SECTIONS = {"))]
    assert "'insane'" in pulse
    actions = src[src.index("ACTIONS = {"):src.index("DRY_OK = {}")]
    assert "insane_guard = function(a)" in actions and "reqscript('ai-insane').guard" in actions
    dry = src[src.index("DRY_OK = {}"):src.index("}) do DRY_OK[name] = true end")]
    assert "'insane_guard'" in dry
    mods = src[src.index("BRIDGE_MODULES = {"):src.index("}", src.index("BRIDGE_MODULES = {"))]
    assert "'ai-insane'" in mods
    assert SECTION_DEFAULTS["insane"] == {}
    import overseer
    assert "insane_guard" in overseer.SHORT_WORDS and "insane_guard" in overseer.CAMERA_QUIET


@test("bridge: insane_guard's validator refuses a units value that isn't a list of ids, and passes ids on")
def _():
    if LuaRuntime is None:
        return
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    i = src.index("    insane_guard = function(a)")
    j = src.index("    end,\n", i) + len("    end,\n")
    fn = src[i:j].strip().rstrip(",").replace("insane_guard = function(a)", "return function(a)", 1)
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
        GOT = nil
        function reject(r) return {ok = false, rejected = true, error = r} end
        function reqscript() return {guard = function(o, dry) GOT = {o = o, dry = dry}; return {ok = true} end} end
    """)
    f = lua.execute(fn)
    assert f(lua.table_from({"units": "x"}))["rejected"] is True
    assert f(lua.table_from({"units": lua.table_from([1.5])}))["rejected"] is True
    assert f(lua.table_from({"units": lua.table_from([7, 8.0])}))["ok"] is True
    got = lua.globals().GOT
    assert list(got.o.units.values()) == [7, 8] and got.dry is False
    f(lua.table_from({"dry_run": True}))
    got = lua.globals().GOT
    assert got.o.units is None and got.dry is True


# --- 5. the brain ---------------------------------------------------------------------------

def state(insane=None, moods=None, needs=None, **extra):
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    if insane is not None:
        base["insane"] = insane
    if moods is not None:
        base["moods"] = moods
    if needs is not None:
        base["needs"] = needs
    base.update(extra)
    return normalize(base)


def run_rule(s):
    props, notes = [], []
    PI._insane_rule(s, PLANNER_CONFIG, props, notes, Memory())
    return props, notes


@test("brain: melancholy near water with an AI door: the guard proposed; the note says kind, where, the water and what the AI does")
def _():
    s = state({"list": [{"id": 7, "name": "Urist", "kind": "melancholy", "mood": "Melancholy", "place": "DiningHall",
                         "hazards": {"water": 7}, "doors": 1, "locked": 0}], "locks": 0, "at_risk": []})
    props, notes = run_rule(s)
    assert [(p.rule, p.action) for p in props] == [("insane", {"type": "insane_guard", "units": [7]})], props
    n = notes[0]
    assert n.startswith("Urist has fallen into melancholy (in the dining hall): insane for good"), n
    assert "deep water 7 tiles away" in n and "the AI locks 1 of its own door between them" in n, n
    assert "nothing more can be done" in n and "room and things go back to the fort" in n, n
    assert not any(x.startswith("[you]") for x in notes), notes


@test("brain: no door to lock: no proposal, and the note says why; held locks are proposed again (to free them)")
def _():
    s = state({"list": [{"id": 7, "name": "Urist", "kind": "melancholy", "hazards": {"drop": 2}, "doors": 0,
                         "locked": 0}], "locks": 0})
    props, notes = run_rule(s)
    assert props == [] and "no door of the AI's own stands between" in notes[0], notes
    s = state({"list": [], "locks": 2})
    props, notes = run_rule(s)
    assert [p.action for p in props] == [{"type": "insane_guard", "units": []}] and notes == [], (props, notes)
    assert "opened again once nobody insane is near" in props[0].reason


@test("brain: raving (no alarm, ignores danger), catatonic (nothing to do), berserk (the military's) each said plainly")
def _():
    s = state({"list": [{"id": 1, "name": "A", "kind": "raving", "hazards": {}, "doors": 0, "locked": 0},
                        {"id": 2, "name": "B", "kind": "catatonic"},
                        {"id": 3, "name": "C", "kind": "berserk"}], "locks": 0})
    props, notes = run_rule(s)
    assert props == [], props
    assert "stark raving mad" in notes[0] and "attack no one (no alarm is raised" in notes[0], notes[0]
    assert "no deadly ground near them now" in notes[0], notes[0]
    assert "catatonic" in notes[1] and "nothing the AI can do" in notes[1], notes[1]
    assert "berserk" in notes[2] and "military rules" in notes[2], notes[2]
    # each kind says what the AI does
    assert all(("the AI" in n) or ("military" in n) for n in notes), notes


@test("brain: with the section, the moods rule leaves the insane to it; without, it says what it always said")
def _():
    moods = {"list": [{"unit_id": 7, "name": "Urist", "mood": "Melancholy", "craft": False},
                      {"unit_id": 8, "name": "Bim", "mood": "Traumatized", "craft": False}]}
    _, notes = plan(state(moods=moods), Memory())
    assert any("Urist has gone melancholy: lost to the fort" in n for n in notes), notes
    assert any(n == "Bim: Traumatized" for n in notes), notes
    ins = {"list": [{"id": 7, "name": "Urist", "kind": "melancholy", "hazards": {}, "doors": 0, "locked": 0},
                    {"id": 8, "name": "Bim", "kind": "catatonic"}], "locks": 0}
    _, notes = plan(state(ins, moods=moods), Memory())
    assert not any("lost to the fort" in n or n == "Bim: Traumatized" for n in notes), notes
    assert any(n.startswith("Urist has fallen into melancholy") for n in notes), notes
    assert any(n.startswith("Bim is catatonic") for n in notes), notes


@test("brain: the near-breaking go first in the stress care, at a higher priority; one the needs list left out still gets a room")
def _():
    worst = [{"id": 1, "name": "Calm", "stress": "miserable", "bedroom": False},
             {"id": 2, "name": "Near", "stress": "miserable", "bedroom": False}]
    s = state({"list": [], "locks": 0, "at_risk": [{"id": 2, "name": "Near", "longterm": 60000, "stress": "miserable",
                                                    "bedroom": False}]},
              noble_rooms={"free": {"bedroom": 3}})
    props = []
    PS._stress_care(s, PLANNER_CONFIG, worst, props, Memory())
    assert [(p.action["unit_id"], p.priority) for p in props] == [(2, 2)], props
    assert "near breaking" in props[0].reason
    # without the section: the first of the list, as before
    s0 = state(noble_rooms={"free": {"bedroom": 3}})
    props = []
    PS._stress_care(s0, PLANNER_CONFIG, worst, props, Memory())
    assert [(p.action["unit_id"], p.priority) for p in props] == [(1, 3)], props
    assert props[0].reason == "Calm is miserable and has no room of their own: give them a free bedroom"
    # one not in the needs list (it keeps the worst 8): from the section's row, a room only
    s = state({"list": [], "at_risk": [{"id": 9, "name": "Far", "longterm": 110000, "stress": "unhappy",
                                        "bedroom": False, "squad": True}]},
              noble_rooms={"free": {"bedroom": 1}})
    props = []
    PS._stress_care(s, PLANNER_CONFIG, [], props, Memory())
    assert [(p.action["type"], p.action["unit_id"], p.priority) for p in props] == [("give_room", 9, 2)], props
    # below the thresholds: nobody
    s = state({"list": [], "at_risk": [{"id": 9, "name": "Far", "longterm": 40000, "stress": "miserable",
                                        "bedroom": False}]}, noble_rooms={"free": {"bedroom": 1}})
    props = []
    PS._stress_care(s, PLANNER_CONFIG, [], props, Memory())
    assert props == [], props


@test("brain: the near-breaking said with what the AI does; plan() sends the guard through select()")
def _():
    s = state({"list": [{"id": 7, "name": "Urist", "kind": "melancholy", "hazards": {"water": 3}, "doors": 2,
                         "locked": 0}], "locks": 0,
               "at_risk": [{"id": 2, "name": "Near", "longterm": 60000, "stress": "very_unhappy"}]})
    props, notes = plan(s, Memory())
    assert any(p.rule == "insane" and p.action["type"] == "insane_guard" for p in props), [p.rule for p in props]
    line = next(n for n in notes if "near breaking" in n)
    assert "1 citizen(s) near breaking" in line and "stress care sees to them first" in line, line
    from planner import select
    allowed, _ = select(props, s, Memory())
    assert any(p.rule == "insane" for p in allowed)


# --- (0.105.40b fix) the verifier's findings --------------------------------------------------

@test("fix 1: only a door that truly separates: none in an open room, none with another way round, none with a "
      "sane citizen on the deadly side; a locked door elsewhere in the wall closes the other way")
def _():
    lua, env, w = world()
    _, d = fort(lua, w, wall=False)                       # an open room: the water is reached round the door
    assert guard(lua, env, [7])["locked"] == 0 and py(env.report())["list"][0]["doors"] == 0
    lua, env, w = world()
    _, d = fort(lua, w)
    w.tile(55, 53, 100, T(lua, {"shape": "FLOOR"}))       # a gap in the wall
    assert guard(lua, env, [7])["locked"] == 0 and d.door_flags.forbidden is False
    # the gap holds a door the player locked: the AI's door now separates
    w.door(T(lua, {"id": 301, "x": 55, "y": 53, "z": 100, "door_flags": {"forbidden": True,
                                                                         "operated_by_mechanisms": False}}))
    assert guard(lua, env, [7])["locked"] == 1 and d.door_flags.forbidden is True
    # a sane citizen on the water's side: never shut in there
    lua, env, w = world()
    _, d = fort(lua, w)
    w.unit(T(lua, {"id": 20, "citizen": True, "own": True, "pos": {"x": 56, "y": 53, "z": 100}}))
    assert guard(lua, env, [7])["locked"] == 0 and d.door_flags.forbidden is False
    assert py(env.report())["list"][0]["doors"] == 0
    # ...on the dwarf's side: no matter
    w.citizens[1].pos.x = 45
    assert guard(lua, env, [7])["locked"] == 1
    # the way round goes down a stair and up again: no lock either
    lua, env, w = world()
    _, d = fort(lua, w)
    w.tile(53, 52, 100, T(lua, {"shape": "STAIR_DOWN"}))
    w.tile(53, 52, 99, T(lua, {"shape": "STAIR_UPDOWN"}))
    for x in range(54, 57):
        w.tile(x, 52, 99, T(lua, {"shape": "FLOOR"}))
    w.tile(57, 52, 99, T(lua, {"shape": "STAIR_UP"}))
    w.tile(57, 52, 100, T(lua, {"shape": "STAIR_DOWN"}))
    for x in range(52, 59):                                # the rest of level 99 is rock
        for y in range(44, 57):
            if y != 52:
                w.tile(x, y, 99, T(lua, {"shape": "WALL"}))
    w.tile(52, 52, 99, T(lua, {"shape": "WALL"}))
    w.tile(58, 52, 99, T(lua, {"shape": "WALL"}))
    assert guard(lua, env, [7])["locked"] == 0, "a way round by the stairs"


@test("fix 2: never a door the threats rules hold or could need; a held lock claimed since is dropped and left locked")
def _():
    lua, env, w = world()
    _, d = fort(lua, w)
    w.claimed[300] = True
    assert guard(lua, env, [7])["locked"] == 0 and d.door_flags.forbidden is False
    assert py(env.report())["list"][0]["doors"] == 0
    lua, env, w = world()
    u, d = fort(lua, w)
    assert guard(lua, env, [7])["locked"] == 1
    assert py(env.held_ids()) == {300: True}
    w.claimed[300] = True                                 # a cell (or the seal) took it over
    u.pos.x = 20                                          # the dwarf off: would be unlocked
    r = guard(lua, env, [7])
    assert r["released"] == 0 and r["held"] == 0 and d.door_flags.forbidden is True, r
    assert py(env.held_ids()) in ({}, None)


@test("fix 2: the cavern seal adopts a door ai-insane holds locked (on its record, opened with the seal); "
      "claimed_doors lists the cells', the seal's and the openings' doors")
def _():
    src = (ROOT / "tests" / "test_fix26_seal.py").read_text(encoding="utf-8")
    game = re.search(r'THREATS_GAME = r"""(.*?)"""', src, re.S).group(1)
    lua = LuaRuntime(unpack_returned_tuples=True)
    E = lua.execute(game, module_src("ai-threats.lua"))
    door = E.G.tiles["10,10,10"]
    door.door_flags.forbidden = True
    E.G.mods["ai-insane"] = lua.eval("{held_ids = function() return {[30] = true} end}")
    r = py(E.seal_cavern("Cavern1", T(lua, [{"x": 10, "y": 10, "z": 10}]), False, False))
    assert r["ok"] and r["adopted"] == 1, r
    rec = E.G.saved["ai-overseer/threats"].sealed["Cavern1"]
    assert list(rec.ids.values()) == [30]
    assert py(E.claimed_doors()).get(30) is True
    r = py(E.seal_cavern("Cavern1", None, True, False))
    assert r["ok"] and r["unlocked"] == 1 and door.door_flags.forbidden is False, r
    # a door the AI doesn't hold, locked already: not adopted (the player's)
    lua = LuaRuntime(unpack_returned_tuples=True)
    E = lua.execute(game, module_src("ai-threats.lua"))
    E.G.tiles["10,10,10"].door_flags.forbidden = True
    r = py(E.seal_cavern("Cavern1", T(lua, [{"x": 10, "y": 10, "z": 10}]), False, False))
    assert not r["ok"], r
    # the cells' doors and the openings' doors are claimed
    E.G.saved["ai-overseer/threats"] = T(lua, {"cells": {"5": {"doors": [31]}},
                                               "openings": {"a": {"x": 12, "y": 12, "z": 12, "kind": "way_down"}}})
    got = py(E.claimed_doors())
    assert got.get(31) is True and got.get(32) is True, got
    tsrc = (LUA_DIR / "ai-threats.lua").read_text(encoding="utf-8")
    assert "elseif okf and insane[id] and not dry_run then" in tsrc and "table.insert(c.doors, id)" in tsrc


@test("fix 3: the report frees a lock held too long or with nobody near (the guard may not run); while halted "
      "the guard only frees (release_only), and the bridge lets it through halted")
def _():
    lua, env, w = world()
    u, d = fort(lua, w)
    guard(lua, env, [7])
    advance(env, 2400)
    r = py(env.report())
    assert r["locks"] == 0 and d.door_flags.forbidden is False, r
    lua, env, w = world()
    u, d = fort(lua, w)
    guard(lua, env, [7])
    assert py(env.report())["locks"] == 1 and d.door_flags.forbidden is True     # near: kept
    u.pos.x = 20
    assert py(env.report())["locks"] == 0 and d.door_flags.forbidden is False
    # release_only: none locked, the held freed
    lua, env, w = world()
    u, d = fort(lua, w)
    r = py(env.guard(T(lua, {"units": [7], "release_only": True}), False))
    assert r["locked"] == 0 and r["release_only"] is True and d.door_flags.forbidden is False, r
    guard(lua, env, [7])
    u.pos.x = 20
    r = py(env.guard(T(lua, {"units": [7], "release_only": True}), False))
    assert r["released"] == 1 and d.door_flags.forbidden is False, r
    # the bridge: halted, insane_guard runs with release_only; any other action refused
    hyg = (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8")
    harness = re.search(r'HARNESS = r"""(.*?)"""', hyg, re.S).group(1)
    L = LuaRuntime(unpack_returned_tuples=True)
    H = L.execute(harness, (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8"), str(LUA_DIR))
    H.scripts = L.table()
    M = H.module()
    L.execute("""local H = ...
        H.GOT = nil
        H.scripts['ai-insane'] = {guard = function(o, dry) H.GOT = o; return {ok = true} end}""", H)
    H.halted = True
    r = M.run_action(L.table_from({"type": "insane_guard", "units": L.table_from([7])}))
    assert r.ok is True and H.GOT.release_only is True, dict(r)
    r = M.run_action(L.table_from({"type": "add_haulers", "count": 1}))
    assert r.ok is False and r.halted is True
    H.halted = False
    H.GOT = None
    M.run_action(L.table_from({"type": "insane_guard", "units": L.table_from([7])}))
    assert H.GOT.release_only is False


@test("fix 4: a dropped well's outline (marked by the builder) is not the AI's for the guard; the builder marks it")
def _():
    lua, env, w = world()
    _, d = fort(lua, w)
    w.projects[1] = None
    w.old_areas[1] = T(lua, {"x1": 40, "y1": 40, "x2": 60, "y2": 60, "z": 100, "well": True})
    assert guard(lua, env, [7])["locked"] == 0 and d.door_flags.forbidden is False
    bsrc = (LUA_DIR / "ai-builder-projects.lua").read_text(encoding="utf-8")
    assert "well = p.kind == 'well' or nil" in bsrc


@test("fix 5: each lock records the door's state just before (unlocked); a record saying it was locked before "
      "is dropped without opening the door")
def _():
    lua, env, w = world()
    u, d = fort(lua, w)
    guard(lua, env, [7])
    rec = w.site["ai-overseer/insane-locks"].locks["300"]
    assert rec.before is False
    rec.before = True
    u.pos.x = 20
    r = guard(lua, env, [7])
    assert r["released"] == 1 and r["held"] == 0 and d.door_flags.forbidden is True, r


# --- 6. identity: without the section, plan() is main's ------------------------------------

PROBE = r'''
import copy, json, sys
from pathlib import Path
brain = Path(sys.argv[1]); sys.path.insert(0, str(brain))
fixtures = Path(sys.argv[2])
from digest import normalize
from planner import Memory, plan, record, select, note_cycle, TICKS_PER_DAY
out = {}
for path in [fixtures / "test_fort.json"] + sorted((fixtures / "real").glob("*.json")):
    base = json.loads(path.read_text(encoding="utf-8"))
    for slow in (False, True):
        s = copy.deepcopy(base)
        if slow:
            s["fps_low"] = 8
        s = normalize(s)
        m = Memory()
        cycles = []
        for _ in range(3):
            n = note_cycle(copy.deepcopy(s), m)
            props, notes = plan(copy.deepcopy(s), m)
            cycles.append({"props": [[p.rule, json.dumps(p.action, sort_keys=True, default=str), p.reason,
                                      p.priority] for p in props], "notes": notes, "cycle": n})
            allowed, _ = select(props, s, m)
            record([(p, {"ok": False, "error": "refused (test)"}) for p in allowed], s, m)
            s["date"]["tick"] = s["date"].get("tick", 0) + TICKS_PER_DAY
        out[f"{path.name}:{slow}"] = cycles
print(json.dumps(out, sort_keys=True))
'''

_MAIN = {}


def main_brain() -> Path | None:
    if "dir" not in _MAIN:
        tmp = tempfile.mkdtemp(prefix="r41-main-")
        arch = subprocess.run(["git", "-C", str(ROOT), "archive", "main", "brain"], capture_output=True)
        if arch.returncode != 0:
            _MAIN["dir"] = None
        else:
            subprocess.run(["tar", "-x", "-C", tmp], input=arch.stdout, check=True)
            _MAIN["dir"] = Path(tmp) / "brain"
            atexit.register(shutil.rmtree, tmp, True)
    return _MAIN["dir"]


def probe(brain: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "probe.py"
        p.write_text(PROBE, encoding="utf-8")
        r = subprocess.run([sys.executable, "-I", str(p), str(brain), str(ROOT / "tests" / "fixtures")],
                           capture_output=True, text=True, env=dict(os.environ, DFAI_LOG_DIR=tmp), cwd=tmp)
    assert r.returncode == 0, r.stderr[-1500:]
    return r.stdout.strip().splitlines()[-1]


@test("no insane section in the report (every fixture, slow and not, 3 cycles): plan() and note_cycle() are main's, byte for byte")
def _():
    main = main_brain()
    assert main is not None, "no main branch to compare with"
    a, b = probe(main), probe(ROOT / "brain")
    if a != b:
        ja, jb = json.loads(a), json.loads(b)
        bad = [k for k in ja if ja[k] != jb.get(k)]
        raise AssertionError(f"differs from main at {bad[:3]}")


@test("fixtures hold no insane section and no insane dwarf the new rule would act on")
def _():
    for path in [ROOT / "tests" / "fixtures" / "test_fort.json"] + sorted((ROOT / "tests" / "fixtures" / "real").glob("*.json")):
        s = json.loads(path.read_text(encoding="utf-8"))
        assert "insane" not in s, path.name


if LuaRuntime is None:
    finish("these tests need the lupa package (pip install lupa)")
finish()
