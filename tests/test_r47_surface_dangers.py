"""(0.105.47, I7d) Surface dangers: titans and the far-out workers, wild
animals at grips with a dwarf, the ice at the AI's water zones.

  1. planner_near_gates: which dangers count (a titan on the surface, not a
     forgotten beast in the caverns), the matchup (weak squads hide, strong
     ones don't), the burrow taken up, kept, refreshed and let go, the
     weather keep-in, the notes; lua/ai-near-gates.lua in a fake fort (the
     burrow drawn round the surface ways in, its members, the far-out list).
  2. Wild animals: ai-siege field_watch lists a wild animal whose last target
     is a citizen (`attacking`), not one a hunter is after, not a fort
     animal; planner_siege sends a squad at it first; planner_hunt leaves a
     reachable wild animal to the field watch (no double orders).
  3. Ice: planner_ice.ice_season by the season and the temperature, the
     surface water zones retired, the traffic restricted ahead of the freeze
     (the monthly water_traffic dropped), a shore well being dug given up;
     planner_wells' water zones underground only and new wells inside only;
     lua/ai-ice.lua retire (only the AI's own 3x3, only outside, dry runs).
  4. The wiring: actions, DRY_OK, sections, pulse, modules, digest defaults,
     the overseer's words.

    python tests/test_r47_surface_dangers.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
from planner_core import Proposal  # noqa: E402
import planner_near_gates as NG  # noqa: E402
import planner_ice as PI  # noqa: E402
import planner_siege as PS  # noqa: E402
import planner_hunt as PH  # noqa: E402
import planner_wells as PW  # noqa: E402
from digest import normalize, SECTION_DEFAULTS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

DAY = 1200
CFG = dict(PLANNER_CONFIG)
LUA = ROOT / "lua"


def titan(i=900, **kw):
    t = {"id": i, "name": "Savanna Titan", "kinds": ["Titan"], "great_danger": True, "size": 60000 * 30,
         "layer": "upper_levels", "can_reach_dwarves": True, "pos": {"x": 229, "y": 281, "z": 170}}
    t.update(kw)
    return t


def squad(i, power=100.0, members=6):
    return {"id": i, "name": f"Squad {i}", "members": members, "power": {"power": power, "armed": members}}


def st(threats=(), squads=(), near=None, date=None, **extra):
    s = {"date": date or {"year": 258, "tick": 50000, "day": 1, "month": "Granite", "season": "spring"},
         "dwarves": {"total": 60}, "settings": {"traits": {}},
         "others_on_map": {"threats": list(threats)}, "military": {"squads": list(squads)}}
    if near is not None:
        s["near_gates"] = near
    s.update(extra)
    return normalize(s)


def run_ng(s, memory=None, cfg=None):
    props, notes = [], []
    NG._near_gates_rule(s, memory if memory is not None else Memory(), dict(cfg or CFG), props, notes)
    return props, notes


# --- 1. titans: the work kept near the gates ------------------------------------------------

@test("near gates: a titan on the surface counts; a forgotten beast in Cavern1 and a goblin don't")
def _():
    s = st([titan(), titan(901, kinds=["ForgottenBeast"], layer="Cavern1"),
            {"id": 902, "name": "goblin", "great_danger": False, "layer": "upper_levels"},
            {"id": 903, "name": "Bronze Colossus", "kinds": ["Megabeast"], "great_danger": False,
             "layer": "between_layers"}])
    assert [t["id"] for t in NG.surface_dangers(s)] == [900, 903]


@test("near gates: weak squads can't beat the titan; strong ones can; none at all can't; a called-off fight can't")
def _():
    m = Memory()
    assert NG.unbeatable(st([titan()], [squad(1, 10)]), m, CFG, [titan()])[0] is True
    assert NG.unbeatable(st([titan()], [squad(1, 50000)]), m, CFG, [titan()])[0] is False
    bad, why = NG.unbeatable(st([titan()]), m, CFG, [titan()])
    assert bad and "no squad" in why
    m.called_off = {"900": 1}
    assert NG.unbeatable(st([titan()], [squad(1, 50000)]), m, CFG, [titan()])[0] is True
    assert NG.unbeatable(st([]), Memory(), CFG, [])[0] is False


@test("near gates: a titan the squads can't beat and the burrow not in use: taken up at priority 1, radius 25")
def _():
    m = Memory()
    props, _ = run_ng(st([titan()], [squad(1, 10)], near={"on": False, "far": []}), m)
    p = [p for p in props if p.action.get("type") == "near_gates"]
    assert len(p) == 1 and p[0].action == {"type": "near_gates", "on": True, "radius": 25} and p[0].priority == 1, props
    assert p[0].rule == "near_gates" and "Savanna Titan" in p[0].reason
    assert m.near_gates_seen["last"] == 258 * 403200 + 50000


@test("near gates: a titan the squads beat, nothing; no section (older bridge), nothing; switched off, nothing")
def _():
    assert run_ng(st([titan()], [squad(1, 50000)], near={"on": False}))[0] == []
    assert run_ng(st([titan()], [squad(1, 10)]))[0] == []
    assert run_ng(st([titan()], [squad(1, 10)], near={"on": False}), cfg=dict(CFG, near_gates=False))[0] == []


@test("near gates: held a few days after the titan left, then let go at low priority")
def _():
    m = Memory()
    now = 258 * 403200 + 50000
    m.near_gates_seen = {"last": now - 2 * DAY, "who": "Savanna Titan"}
    props, _ = run_ng(st([], [squad(1, 10)], near={"on": True, "far": []}), m)
    assert props == [], props
    props, _ = run_ng(st([], [squad(1, 10)], near={"on": False, "far": []}), m)
    assert props and props[0].action["on"] is True and "left the map" in props[0].reason
    m.near_gates_seen = {"last": now - 4 * DAY}
    props, _ = run_ng(st([], near={"on": True, "far": []}), m)
    assert len(props) == 1 and props[0].action == {"type": "near_gates", "on": False} and props[0].priority == 4


@test("near gates: on, a stray far out who isn't a member: refreshed once a day (own rule); a member far out: a note")
def _():
    far = [{"id": 5, "name": "Rovod", "d": 80}, {"id": 6, "name": "Deduk", "d": 120, "member": True}]
    props, notes = run_ng(st([titan()], [squad(1, 10)], near={"on": True, "far": far, "far_total": 2}))
    assert [p.rule for p in props] == ["near_gates_refresh"] and props[0].action["on"] is True
    assert any("Rovod (80 tiles out)" in n and "Deduk" in n for n in notes), notes
    props, notes = run_ng(st([titan()], [squad(1, 10)], near={"on": True, "far": far[1:], "far_total": 1}))
    assert props == [] and any("Deduk" in n for n in notes)
    assert CFG["near_gates_refresh_cooldown_ticks"] == 1200


@test("near gates: merchants on the map while the titan is about: said (the AI can't stop arrivals)")
def _():
    _, notes = run_ng(st([titan()], [squad(1, 10)], near={"on": True, "far": []}, field_watch={"merchants": 3}))
    assert any("3 merchant(s)" in n and "can't stop" in n for n in notes), notes


@test("near gates: the weather keep-in holds them inside: the burrow is let go, and not taken up meanwhile")
def _():
    m = Memory()
    m.weather_alarm = {"kept_in": 1}
    props, _ = run_ng(st([titan()], [squad(1, 10)], near={"on": True, "far": []}), m)
    assert len(props) == 1 and props[0].action == {"type": "near_gates", "on": False}
    assert run_ng(st([titan()], [squad(1, 10)], near={"on": False, "far": []}), m)[0] == []


@test("near gates: plan() runs the rule (the section read, the proposal in the plan)")
def _():
    s = st([titan()], [squad(1, 10)], near={"on": False, "far": []})
    props, notes = plan(s, Memory())
    assert any(p.action.get("type") == "near_gates" and p.action.get("on") for p in props), \
        [n for n in notes if "near_gates" in n or "failed" in n][:5]


# --- the Lua: ai-near-gates ------------------------------------------------------------------

NG_FAKE = r"""
local src = ...
local W = {site = {}, citizens = {}, burrows = {}, tiles = 0, assigned = {}, cleared = 0, next_burrow = 7,
           patients = {}, outside = {}, filled = 0}
local env = setmetatable({}, {__index = _G})
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {unit = {find = function(id) for _, u in ipairs(W.citizens) do if u.id == id then return u end end end},
          global = {cur_year = 258, cur_year_tick = 1000}}
env.dfhack = {
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
    units = {getCitizens = function() return W.citizens end,
             getReadableName = function(u) return u.name end},
    maps = {getTileFlags = function(p) return {outside = W.outside[p.x .. ',' .. p.y .. ',' .. p.z] == true or p.z >= 100} end,
            getTileSize = function() return 200, 200, 120 end},
    burrows = {clearTiles = function(b) b.tiles = 0; W.cleared = W.cleared + 1 end,
               setAssignedTile = function(b, p, on) b.tiles = (b.tiles or 0) + 1 end,
               setAssignedUnit = function(b, u, on)
                   local list = {}
                   for _, id in ipairs(u.burrows) do if id ~= b.id then table.insert(list, id) end end
                   if on then table.insert(list, b.id) end
                   u.burrows = list
               end},
}
local S = {}
function S.find_burrow(name) for _, b in ipairs(W.burrows) do if b.name == name then return b end end end
function S.new_burrow(name)
    local b = {id = W.next_burrow, name = name, tiles = 0}
    W.next_burrow = W.next_burrow + 1
    table.insert(W.burrows, b)
    return b
end
function S.fill_shelter(b) W.filled = W.filled + 1; b.tiles = b.tiles + 500; return 500 end
function S.is_patient(u) return W.patients[u.id] == true end
W.G = {GATES = {scanned = true, entrances = {
    {id = 1, kind = 'surface', x = 100, y = 100, z = 100},
    {id = 2, kind = 'cavern', x = 50, y = 50, z = 40}}}}
env.reqscript = function(n)
    if n == 'ai-society' then return S end
    if n == 'ai-gates' then return W.G end
    error('reqscript ' .. tostring(n))
end
function W.cit(t)
    t.burrows = t.burrows or {}
    t.military = {squad_id = t.squad or -1}
    t.pos = t.pos or {x = 100, y = 110, z = 90}
    t.name = t.name or ('dwarf ' .. t.id)
    table.insert(W.citizens, t)
    return t
end
assert(load(src, 'ai-near-gates', 't', env))()
return env, W
"""


def lua_world(fake, name):
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(fake, module_src(name))
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


if LuaRuntime is not None:
    @test("ai-near-gates: the pure parts: surface ways in only, the box round each, who joins and who is let out")
    def _():
        lua, env, w = lua_world(NG_FAKE, "ai-near-gates.lua")
        gates = env.gate_list(w.G.GATES.entrances)
        assert py(gates) == [{"x": 100, "y": 100, "z": 100}]
        d, inside = env.reach(T(lua, {"x": 120, "y": 90, "z": 102}), gates, 25)
        assert d == 26 and inside is True
        d, inside = env.reach(T(lua, {"x": 130, "y": 100, "z": 100}), gates, 25)
        assert d == 30 and inside is False
        d, inside = env.reach(T(lua, {"x": 100, "y": 100, "z": 96}), gates, 25)
        assert inside is False                                        # 4 levels: past NEAR_Z
        v = lambda **f: env.member_verdict(T(lua, f))  # noqa: E731
        assert v() == "add" and v(soldier=True) == "skip" and v(patient=True) == "skip" and v(other=True) == "skip"
        assert v(member=True) == "keep" and v(member=True, patient=True) == "out" and v(member=True, other=True) == "out"

    @test("ai-near-gates: set on draws the inside and the box round the surface way in, takes the civilians "
          "(not a soldier, a patient or one in another burrow); off lets out exactly those")
    def _():
        lua, env, w = lua_world(NG_FAKE, "ai-near-gates.lua")
        w.cit(T(lua, {"id": 1}))
        w.cit(T(lua, {"id": 2, "squad": 4}))                         # a soldier
        w.cit(T(lua, {"id": 3}))
        w.patients[3] = True                                          # a patient
        w.cit(T(lua, {"id": 4, "burrows": [55]}))                     # the player's burrow
        w.cit(T(lua, {"id": 5}))
        r = py(env.set(True, 25, True, None))                         # a dry run
        assert r["ok"] and r["added"] == 2 and r["drawn"] is True, r
        assert len(py(w.burrows) or []) == 0 and w.site["ai-overseer/near-gates"] is None and w.filled == 0
        r = py(env.set(True, 25, False, None))
        assert r["ok"] and r["added"] == 2 and r["members"] == 2 and r["skipped"] == 3, r
        b = w.burrows[1]
        assert b.name == "AI near gates" and w.filled == 1
        assert b.tiles == 500 + 51 * 51 * 7, b.tiles                  # the inside + the box (7 levels)
        assert list(w.citizens[1].burrows.values()) == [b.id] and list(w.citizens[4].burrows.values()) == [55]
        # again: nothing redrawn, nobody added twice; the patient member let out
        w.patients[1] = True
        r = py(env.set(True, 25, False, None))
        assert r.get("drawn") is None and r["added"] == 0 and r["let_out"] == 1 and r["members"] == 1, r
        assert w.filled == 1
        r = py(env.set(False, None, False, None))
        assert r["ok"] and r["released"] == 1 and list(w.citizens[5].burrows.values()) == []
        assert py(env.set(False, None, False, None))["nothing_to_do"] is True

    @test("ai-near-gates: the burrow removed (by the player) while on: made and drawn again")
    def _():
        lua, env, w = lua_world(NG_FAKE, "ai-near-gates.lua")
        w.cit(T(lua, {"id": 1}))
        assert py(env.set(True, 25, False, None))["drawn"] is True
        w.burrows[1] = None
        r = py(env.set(True, 25, False, None))
        assert r["drawn"] is True and w.filled == 2 and w.burrows[1].tiles > 500, r

    @test("ai-near-gates: refused with no surface way in known, or a radius out of bounds")
    def _():
        lua, env, w = lua_world(NG_FAKE, "ai-near-gates.lua")
        assert "radius" in py(env.set(True, 200, False, None))["error"]
        w.G.GATES.scanned = False
        r = py(env.set(True, 25, False, None))
        assert r["rejected"] and "no surface way in" in r["error"]

    @test("ai-near-gates: status lists the citizens outside farther than the radius from every surface way in")
    def _():
        lua, env, w = lua_world(NG_FAKE, "ai-near-gates.lua")
        w.cit(T(lua, {"id": 1, "name": "Rovod", "pos": {"x": 194, "y": 207, "z": 101}}))   # far out
        w.cit(T(lua, {"id": 2, "pos": {"x": 110, "y": 110, "z": 100}}))                   # by the gate
        w.cit(T(lua, {"id": 3, "pos": {"x": 10, "y": 10, "z": 90}}))                      # inside
        r = py(env.status(None))
        assert r["on"] is False and r["outside"] == 2 and r["far_total"] == 1 and r["gates"] == 1, r
        assert r["far"][0]["name"] == "Rovod" and r["far"][0]["d"] == 107 + 3
else:
    @test("the 5 Lua test(s) of the block at line 252: not run")
    def _():
        skip("needs the lupa package (pip install lupa)")      # (0.105.48) counted, not passed


# --- 2. wild animals at grips with a dwarf ---------------------------------------------------

SIEGE_FAKE = r"""
local src = ...
local W = {units = {}, citizens = {}, site = {}}
local env = setmetatable({}, {__index = _G})
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {global = {world = {units = {active = W.units}}}, job_type = {Hunt = 'Hunt', Fish = 'Fish'}}
env.dfhack = {
    maps = {getTileFlags = function(p) return {outside = p.z >= 100} end,
            getWalkableGroup = function(p) return 1 end},
    units = {
        getCitizens = function() return W.citizens end,
        isDead = function(u) return false end, isActive = function(u) return true end,
        isCitizen = function(u) return u.citizen == true end, isMerchant = function(u) return false end,
        isDiplomat = function(u) return false end, isVisitor = function(u) return false end,
        isTame = function(u) return u.tame == true end, isDanger = function(u) return false end,
        isInvader = function(u) return false end, isGreatDanger = function(u) return false end,
        isAnimal = function(u) return u.animal == true end,
        isFortControlled = function(u) return u.fort == true end,
        getReadableName = function(u) return u.name or ('#' .. u.id) end,
    },
    persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end},
}
env.reqscript = function(n)
    if n == 'ai-threats' then return {fire_breath_of = function() return false end} end
    error('reqscript ' .. tostring(n))
end
assert(load(src, 'ai-siege', 't', env))()
env.builder = function() return {hostile_wild = function(u) return u.predator == true end} end
function W.unit(t)
    t.pos = t.pos or {x = 0, y = 0, z = 100}
    t.flags1 = t.flags1 or {}
    t.race, t.caste = t.race or 1, 0
    t.body = {size_info = {size_cur = t.size or 70000}}
    t.enemy = {caste_flags = {}}
    t.opponent = {unit_id = t.target or -1}
    t.job = {current_job = t.hunting and {job_type = 'Hunt'} or nil}
    table.insert(W.units, t)
    if t.citizen then table.insert(W.citizens, t) end
    return t
end
return env, W
"""

if LuaRuntime is not None:
    @test("field_watch: a giant coyote (no predator, not agitated) that went for a fisherdwarf is listed as "
          "attacking; one going for a hunter, a fort animal, one going for a non-citizen, a peaceful one: not")
    def _():
        lua, env, w = lua_world(SIEGE_FAKE, "ai-siege.lua")
        w.unit(T(lua, {"id": 1, "citizen": True, "pos": {"x": 150, "y": 143, "z": 100}}))
        w.unit(T(lua, {"id": 2, "citizen": True, "hunting": True, "pos": {"x": 20, "y": 20, "z": 100}}))
        w.unit(T(lua, {"id": 3, "name": "visitor", "pos": {"x": 30, "y": 30, "z": 100}}))
        w.unit(T(lua, {"id": 10, "animal": True, "name": "giant coyote", "target": 1, "size": 200000,
                       "pos": {"x": 152, "y": 143, "z": 100}}))
        w.unit(T(lua, {"id": 11, "animal": True, "name": "deer", "target": 2, "pos": {"x": 21, "y": 20, "z": 100}}))
        w.unit(T(lua, {"id": 12, "animal": True, "fort": True, "target": 1, "pos": {"x": 151, "y": 143, "z": 100}}))
        w.unit(T(lua, {"id": 13, "animal": True, "target": 3, "pos": {"x": 31, "y": 30, "z": 100}}))
        w.unit(T(lua, {"id": 14, "animal": True, "name": "giant chipmunk", "pos": {"x": 151, "y": 144, "z": 100}}))
        w.unit(T(lua, {"id": 15, "animal": True, "predator": True, "name": "bear", "target": 1,
                       "pos": {"x": 155, "y": 143, "z": 100}}))
        r = py(env.field_watch(None))
        wild = {x["id"]: x for x in r["wild"]}
        assert set(wild) == {10, 15}, wild
        assert wild[10]["attacking"] is True and wild[10]["wild"] is True and wild[10]["distance_outside"] == 2
        # (0.105.51) a predator at grips with a citizen says so too (the brain's wild_pack: a lone
        # one attacking with no squad that beats it sounds the alarm)
        assert wild[15].get("attacking") is True and wild[15]["wild"] is True

    @test("field_watch: wild_attacking reads the creature's last target only, in a pcall")
    def _():
        lua, env, w = lua_world(SIEGE_FAKE, "ai-siege.lua")
        c = w.unit(T(lua, {"id": 1, "citizen": True}))
        a = w.unit(T(lua, {"id": 10, "animal": True, "target": 1}))
        cits = lua.table_from({1: c})
        assert env.wild_attacking(a, cits) is True
        a.opponent = None
        assert env.wild_attacking(a, cits) is False
        assert env.wild_attacking(a, None) is False
else:
    @test("the 2 Lua test(s) of the block at line 369: not run")
    def _():
        skip("needs the lupa package (pip install lupa)")      # (0.105.48) counted, not passed


def fw_state(rows, squads=None, **extra):
    s = {"date": {"year": 258, "tick": 50000, "season": "spring"}, "settings": {"traits": {}},
         "field_watch": {"merchants": 0, "caravan": [], "wild": rows, "wild_total": len(rows)},
         "military": {"squads": squads if squads is not None else [
             {"id": 1, "name": "Axes", "members": 5, "power": {"power": 400, "armed": 5}}]}}
    s.update(extra)
    return normalize(s)


@test("wildlife_hunts: one attacking a dwarf goes first, at priority 1, killed first; a squad is sent")
def _():
    rows = [{"id": 20, "name": "wolf", "wild": True, "reach": True, "distance_outside": 15, "size": 30000},
            {"id": 10, "name": "giant coyote", "wild": True, "attacking": True, "reach": True,
             "distance_outside": 2, "size": 30000}]
    props, notes = [], []
    PS._wild_rule(fw_state(rows), Memory(), dict(CFG), props, notes)
    assert len(props) == 1, (props, notes)
    p = props[0]
    assert p.rule == "wild_hunt" and p.priority == 1 and p.action["kill"] == [10, 20] and "attacking a dwarf" in p.reason


@test("hunt: a hostile wild animal that can reach the dwarves is the field watch's (said), never hunted too")
def _():
    t = {"id": 500, "name": "giant coyote", "kinds": [], "great_danger": False, "why": "hostile_wild",
         "region": "surface", "route": {"ok": True, "length": 30, "blocked_by": "none"}, "near_workers": 2,
         "can_reach_dwarves": True}
    q = {"id": 1, "name": "Axes", "soldiers": 5, "power": 400.0, "armed": 5, "armored": 5, "ranged": 0,
         "at_home": True, "hunting": None, "sheltering": False}
    s = normalize({"date": {"year": 200, "tick": 50000, "season": "spring"}, "dwarves": {"total": 60},
                   "settings": {"traits": {}}, "others_on_map": {"threats": []}, "civ_alert": False,
                   "hunt": {"targets": [t], "squads": [q], "hunts": []}})
    props, notes = [], []
    PH._hunt_rule(s, dict(CFG), props, notes, Memory())
    assert not [p for p in props if p.action.get("type") == "hunt_send"]
    assert any("wildlife guard" in n for n in notes), notes


# --- 3. ice ------------------------------------------------------------------------------------

def ice_state(tick=50000, season="spring", temp=None, freezing=None, zones=(), projects=(), water=None, **extra):
    frost = {"zones": list(zones), "wells": []}
    if temp is not None:
        frost["surface_temp"] = temp
    if freezing is not None:
        frost["freezing"] = freezing
    s = {"date": {"year": 252, "tick": tick, "season": season}, "env_hazards": {"frost": frost},
         "projects": {"open": list(projects)}, "dwarves": {"total": 40}}
    if water is not None:
        s["water"] = water
    s.update(extra)
    return normalize(s)


LATE = 8 * 33600 + 15 * 1200        # 16 Timber


@test("ice_season: from the last half-month of autumn and through winter; not mid-autumn, not spring")
def _():
    assert PI.ice_season(ice_state(LATE, "autumn"))[0] is True
    assert PI.ice_season(ice_state(LATE - 2 * 1200, "autumn"))[0] is False
    assert PI.ice_season(ice_state(305760, "winter"))[0] is True
    assert PI.ice_season(ice_state(50000, "spring"))[0] is False
    assert CFG["ice_late_autumn_tick"] == 285600


@test("ice_season: by the biome: a warm one (never iced, well over freezing) has none; a cold one any month")
def _():
    assert PI.ice_season(ice_state(305760, "winter", temp=10070))[0] is False
    m = Memory()
    m.climate_freezes = True
    assert PI.ice_season(ice_state(305760, "winter", temp=10070), m)[0] is True
    on, why = PI.ice_season(ice_state(200000, "summer", temp=10010))
    assert on and "over freezing" in why
    assert PI.ice_season(ice_state(150000, "summer", freezing=True))[0] is True
    assert PI.ice_season(ice_state(150000, "summer", temp=10050))[0] is False


@test("ice_season: no frost reading (an older bridge): never; planner_wells keeps its old winter rule then")
def _():
    s = normalize({"date": {"year": 252, "tick": 305760, "season": "winter"}})
    assert PI.ice_season(s)[0] is False
    m = Memory()
    assert PW._ice_now(s, m, CFG) is False
    m.climate_freezes = True
    assert PW._ice_now(s, m, CFG) is True
    props = []
    PI._ice_rule(s, m, dict(CFG), props, [])
    assert props == []


WATER = {"middle": {"x": 64, "y": 124, "z_high": 170},
         "bodies": [{"kind": "surface", "z1": 169, "z2": 170, "nearest": {"x": 64, "y": 124, "z": 170, "d": 20}},
                    {"kind": "pool", "underground": True, "z1": 120, "z2": 120,
                     "nearest": {"x": 90, "y": 90, "z": 120, "d": 60}}]}


@test("ice rule: the surface water zone retired, traffic restricted now (priority 2, the monthly one dropped), "
      "a shore well being dug given up; nothing out of season")
def _():
    zones = [{"x": 66, "y": 123, "z": 170, "water": "water", "outside": True},
             {"x": 90, "y": 90, "z": 120, "water": "water"}]
    projects = [{"id": 31, "kind": "well", "phase": "dig", "summary": {"well": 1, "shore": True}},
                {"id": 32, "kind": "well", "phase": "dig", "summary": {"well": 1}}]
    s = ice_state(LATE, "autumn", zones=zones, projects=projects, water=WATER)
    props = [Proposal("water_traffic", {"type": "restrict_water"}, "monthly", 6)]
    notes = []
    PI._ice_rule(s, Memory(), dict(CFG), props, notes)
    by = {p.rule: p for p in props}
    assert set(by) == {"ice_zones", "ice_traffic", "ice_shore_well"}, by
    assert by["ice_zones"].action == {"type": "retire_water_zones", "outside_only": True} and "x66 y123" in by["ice_zones"].reason
    a = by["ice_traffic"].action
    assert a["type"] == "restrict_water" and 170 in a["levels"] and by["ice_traffic"].priority == 2
    assert by["ice_shore_well"].action == {"type": "cancel_project", "project_id": 31}
    props = []
    PI._ice_rule(ice_state(100000, "spring", zones=zones, projects=projects, water=WATER), Memory(), dict(CFG), props, [])
    assert props == []
    for k in ("ice_traffic", "ice_zones", "ice_shore_well"):
        assert isinstance(CFG[f"{k}_cooldown_ticks"], int)


@test("planner_wells: in ice season a water zone goes on underground water only")
def _():
    base = dict(dwarves={"total": 40, "needs_medical_care": 3}, buildings={"zones": {}}, water=WATER)
    props, notes = [], []
    PW._water_zone_rule(ice_state(LATE, "autumn", **base), props, notes, dict(CFG))
    assert props and props[0].action["points"] == [{"x": 90, "y": 90, "z": 120}], (props, notes)
    props = []
    PW._water_zone_rule(ice_state(100000, "spring", **base), props, [], dict(CFG))
    assert props[0].action["points"][0] == {"x": 64, "y": 124, "z": 170}


@test("planner_wells: a new well goes inside only from the last half-month of autumn (was winter, ice seen)")
def _():
    src = (ROOT / "brain" / "planner_wells.py").read_text(encoding="utf-8")
    assert src.count("if _ice_now(s, memory, cfg):") == 2 and 'get("season") == "winter":\n            action["inside_only"]' not in src
    assert PW._ice_now(ice_state(LATE, "autumn"), Memory(), CFG) is True
    assert PW._ice_now(ice_state(LATE - 2 * 1200, "autumn"), Memory(), CFG) is False


ICE_FAKE = r"""
local src = ...
local W = {site = {}, zones = {}, removed = {}}
local env = setmetatable({}, {__index = _G})
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {civzone_type = setmetatable({}, {__index = function(_, k) return k end})}
env.dfhack = {
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
    maps = {getTileFlags = function(p) return {outside = p.z >= 150} end},
    buildings = {
        findCivzonesAt = function(p)
            local out = {}
            for _, z in ipairs(W.zones) do
                if p.x >= z.x1 and p.x <= z.x2 and p.y >= z.y1 and p.y <= z.y2 and p.z == z.z then table.insert(out, z) end
            end
            return out
        end,
        deconstruct = function(b) table.insert(W.removed, b.id) end},
}
env.reqscript = function(n) error('reqscript ' .. tostring(n)) end
assert(load(src, 'ai-ice', 't', env))()
return env, W
"""

if LuaRuntime is not None:
    @test("ai-ice retire: the AI's 3x3 on surface water taken down; underground kept; a player's zone never "
          "touched (the record dropped); dry run changes nothing; nothing left: nothing_to_do")
    def _():
        lua, env, w = lua_world(ICE_FAKE, "ai-ice.lua")
        w.site["ai-overseer/water_zones"] = T(lua, [{"x": 66, "y": 123, "z": 170}, {"x": 90, "y": 90, "z": 120},
                                                    {"x": 40, "y": 40, "z": 170}])
        w.zones = T(lua, [{"id": 1, "type": "WaterSource", "x1": 65, "y1": 122, "x2": 67, "y2": 124, "z": 170},
                          {"id": 2, "type": "WaterSource", "x1": 89, "y1": 89, "x2": 91, "y2": 91, "z": 120},
                          {"id": 3, "type": "WaterSource", "x1": 35, "y1": 35, "x2": 45, "y2": 45, "z": 170}])
        r = py(env.retire(True, True))
        assert r["ok"] and r["dry_run"] and len(r["removed"]) == 1 and r["dropped"] == 1, r
        assert len(py(w.removed) or []) == 0 and len(py(w.site["ai-overseer/water_zones"])) == 3
        r = py(env.retire(True, False))
        assert r["removed"] == [{"x": 66, "y": 123, "z": 170}] and r["kept"] == 1, r
        assert py(w.removed) == [1]
        assert py(w.site["ai-overseer/water_zones"]) == [{"x": 90, "y": 90, "z": 120}]
        r = py(env.retire(True, False))
        assert r["rejected"] and r["nothing_to_do"], r
else:
    @test("the 1 Lua test(s) of the block at line 567: not run")
    def _():
        skip("needs the lupa package (pip install lupa)")      # (0.105.48) counted, not passed


# --- 4. the wiring -----------------------------------------------------------------------------

@test("wiring: actions, DRY_OK, the section in SECTIONS and the pulse, the modules, digest, the overseer's words")
def _():
    hub = (LUA / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "    near_gates = function(a)\n" in hub and "    retire_water_zones = function(a)\n" in hub
    assert "'near_gates', 'retire_water_zones',   -- (0.105.47, I7d)" in hub
    assert "    near_gates = function() return safe(function() return reqscript('ai-near-gates').status(txt)" in hub
    assert "    'near_gates',    -- (0.105.47, I7d)" in hub
    assert "'ai-near-gates', 'ai-ice'," in hub
    assert SECTION_DEFAULTS["near_gates"] == {}


@test("wiring: overseer labels, planner imports, the wells' summary says shore")
def _():
    ov = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    assert '"near_gates": "keep the civilians' in ov and '"retire_water_zones": "take down' in ov
    pl = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")
    assert "_guard(_near_gates_rule, s, memory, cfg, proposals, notes)" in pl
    assert "_guard(_ice_rule, s, memory, cfg, proposals, notes)" in pl
    wl = (LUA / "ai-builder-wells.lua").read_text(encoding="utf-8")
    assert "cavern = spot.cavern, shore = spot.shore}" in wl
    m = Memory()
    m.near_gates_seen = {"last": 5}
    assert Memory.from_dict(m.to_dict()).near_gates_seen == {"last": 5}


if __name__ == "__main__":
    finish()
