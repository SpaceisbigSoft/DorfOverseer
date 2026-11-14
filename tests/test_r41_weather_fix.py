"""(fix41) The verifier's findings on evil weather and fire breathers:

  1. an unread alarm (civ_alert in _errors): the spell kept current, the
     alarm-off proposals still stripped, no bookkeeping, nothing raised;
  2. the weather lifts only the alarm it raised itself, with no threat or
     great danger seen since the spell began and none held off;
  3. the weather is its own section read in the pulse (the brain prefers it
     to threats.weather), an event when a cloud comes within a day's drift
     or DF announces evil weather; weather_edge_near 150, Lua's the same;
  4. evil rain read as a region tile only past the world's size;
  5. a fire breather standing in the evil weather: no crossbows sent, the
     squad stays in the shelter, one note;
  6. crossbows only at a fire breather at the fort's walls (never out along a
     path the gates don't close); the Lua list of those at the walls;
  8. the fire-breath cache is one world's;
  9. weather_report's citizen distances: positions read once, tiles capped.

    python tests/test_r41_weather_fix.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

import planner  # noqa: E402
from planner import Memory, plan, Proposal, PLANNER_CONFIG  # noqa: E402
import planner_weather as PW  # noqa: E402
import planner_firebreath as PF  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
# (item4) these tests cover the alarm for evil weather, now the fallback when the
# shelter's burrow is refused (no shelter yet, an older bridge); the burrow itself
# (weather_burrow, the default) is tests/test_item4_alarm.py's
PLANNER_CONFIG["weather_keep_in"] = False
HOUR = 50
LIFT = PLANNER_CONFIG["weather_lift_hours"]

CLOUD = {"evil_cloud": 12, "material": "thick fog", "syndrome": "thrall's breath",
         "region": {"clouds": 1, "rains": 0, "cloud_edge": 0, "announced": True},
         "near_fort": True, "enemies_outside": []}
CALM = {"evil_cloud": 0, "region": {"clouds": 0, "rains": 0}, "near_fort": False}


def fort(wx, tick=100000, own=False, **kw) -> dict:
    """own: the weather in its own section (the pulse's), else in threats."""
    s = copy.deepcopy(BASE)
    s["date"]["tick"] = tick
    if own:
        s["weather"] = wx
        s["threats"] = {}
    else:
        s["threats"] = {} if wx is None else {"weather": wx}
    s.setdefault("civ_alert", False)
    s["civ_alert_ready"] = True
    s.update(kw)
    return s


def at(t: int) -> int:
    """The absolute tick of the fixture's year at year tick t."""
    return planner.abs_tick(fort(CALM, t))


def alarms(props, on=None):
    return [p for p in props if p.action.get("type") == "civ_alert" and (on is None or p.action["on"] is on)]


def raised(t0=100000) -> Memory:
    """A spell the weather raised the alarm for, the alarm seen up."""
    m = Memory()
    plan(fort(CLOUD, t0), m)
    m.ai_alert_raised = True
    plan(fort(CLOUD, t0 + HOUR, civ_alert=True), m)
    assert m.weather_alarm.get("asked") and m.weather_alarm.get("on_seen") and m.weather_alarm.get("was_off")
    return m


# --- 1. the alarm unread --------------------------------------------------------------

@test("1: civ_alert unread: the spell kept current, alarm-off stripped, no bookkeeping, nothing raised on a guess")
def _():
    m = Memory()
    s = planner.normalize(fort(CLOUD, 100000, civ_alert={"error": "boom"}))
    assert "civ_alert" in s["_errors"]
    props = [Proposal("strategist", {"type": "civ_alert", "on": False}, "x", 0)]
    notes = []
    PW._weather_rules(s, m, PLANNER_CONFIG, props, notes)
    assert props == [], [p.action for p in props]                         # the lowering stripped
    wa = m.weather_alarm
    assert wa.get("seen") == at(100000) and "evil cloud" in wa.get("why", ""), wa
    assert not any(k in wa for k in ("on_seen", "was_off", "cleared", "asked")), wa
    assert any("couldn't be read" in n for n in notes), notes
    # through plan(): no alarm and no shelter set up on a guess
    props, notes = plan(fort(CLOUD, 100000, civ_alert={"error": "boom"}), Memory())
    assert not alarms(props) and not [p for p in props if p.action.get("type") == "setup_shelter"], \
        [p.action for p in props]
    # a spell the AI owns, the alarm unread mid-spell: not read as the player's lowering
    m = raised()
    plan(fort(CLOUD, 100000 + 2 * HOUR, civ_alert={"error": "boom"}), m)
    assert not m.weather_alarm.get("cleared") and m.weather_alarm.get("seen") == at(100000 + 2 * HOUR)
    # gone past the lift, the alarm unread: kept for the next good read, then lowered
    t = 100000 + 3 * HOUR + LIFT * HOUR
    props, notes = plan(fort(CALM, t, civ_alert={"error": "boom"}), m)
    assert not alarms(props) and m.weather_alarm.get("asked"), (props, m.weather_alarm)
    m.quiet_cycles = 0
    props, _ = plan(fort(CALM, t + HOUR, civ_alert=True), m)
    assert [p for p in alarms(props, False) if "has been gone" in p.reason], [p.action for p in props]


# --- 2. the lift: only the weather's own alarm -------------------------------------------

@test("2: the lift: not when a threat or great danger was seen during the spell, one is held off, or the "
      "alarm wasn't the weather's own")
def _():
    t = 100000 + 2 * HOUR + LIFT * HOUR

    def lifted(m, s=None):
        m.quiet_cycles = 0                                  # the main rule holds it: only the weather lowers
        props, _ = plan(s or fort(CALM, t, civ_alert=True), m)
        return [p for p in alarms(props, False) if "has been gone" in p.reason]

    assert lifted(raised())                                # the baseline: lowered
    m = raised()
    m.last_threat_tick = at(100000 + HOUR)                     # a goblin during the spell: its alarm
    assert not lifted(m)
    m = raised()
    m.last_great_tick = at(100000 + 2 * HOUR)
    assert not lifted(m)
    m = raised()
    m.last_threat_tick = at(100000 - 10 * 1200)               # before the spell: doesn't count
    assert lifted(m)
    m = raised()
    s = fort(CALM, t, civ_alert=True)
    s["others_on_map"]["threats"] = [{"id": 77, "invader": True, "can_reach_dwarves": False, "layer": "surface"}]
    assert not lifted(m, s)                                # an invader held off at the gates
    # another rule raised the alarm during the spell (the weather asked nothing)
    m = Memory()
    s = planner.normalize(fort(CLOUD, 100000))
    props = [Proposal("threat_alert", {"type": "civ_alert", "on": True}, "a goblin", 0)]
    PW._weather_rules(s, m, PLANNER_CONFIG, props, [])
    assert not m.weather_alarm.get("asked") and len(alarms(props, True)) == 1
    m.ai_alert_raised = True
    plan(fort(CLOUD, 100000 + HOUR, civ_alert=True), m)
    assert not lifted(m)


# --- (fix41-ff) the re-review ----------------------------------------------------------------

@test("ff 4: the weather unread (failed or missing) while its spell holds the alarm: the alarm-off "
      "proposals still stripped; with no spell, nothing touched")
def _():
    m = raised()
    for wx in ({"error": "boom"}, None):
        s = planner.normalize(fort(None, 100000 + 2 * HOUR, civ_alert=True, weather=wx) if wx else
                              fort(None, 100000 + 2 * HOUR, civ_alert=True))
        props = [Proposal("strategist", {"type": "civ_alert", "on": False}, "x", 0)]
        notes = []
        PW._weather_rules(s, m, PLANNER_CONFIG, props, notes)
        assert props == [] and any("couldn't be read" in n for n in notes), (wx, notes)
    s = planner.normalize(fort(None, civ_alert=True, weather={"error": "boom"}))
    props = [Proposal("strategist", {"type": "civ_alert", "on": False}, "x", 0)]
    PW._weather_rules(s, Memory(), PLANNER_CONFIG, props, [])
    assert len(props) == 1
    # through plan(): the threats and the weather both failed, the rule still runs
    m = raised()
    m.quiet_cycles = 50
    props, _ = plan(fort(None, 100000 + 2 * HOUR, civ_alert=True, weather={"error": "x"},
                         threats={"error": "y"}), m)
    assert not alarms(props, False), [p.action for p in props]


@test("ff 7: the digest names a cloud off the map only within weather_edge_near")
def _():
    far = dict(CALM, region={"clouds": 1, "rains": 0, "cloud_edge": 300, "approaching": True})
    assert PW.weather_line(fort(far, own=True)) == ""
    near = dict(CALM, region={"clouds": 1, "rains": 0, "cloud_edge": 140, "approaching": True})
    assert "evil_cloud_from_map_edge:140(approaching)" in PW.weather_line(fort(near, own=True))
    assert PW.weather_line(fort(near, own=True), dict(PLANNER_CONFIG, weather_edge_near=100)) == ""


def ff7_lua():
    for dx, walked in ((300, False), (140, True)):
        E = game()
        LUA.execute("""local G, dx = ...; table.insert(G.rw, {type = 'CreepingGas', mat_type = 1, mat_index = 1,
            flags = {}, world_in_game_x = 7680 - dx, world_in_game_y = 15400, cloud_x_movement = 1,
            cloud_y_movement = 0, remaining_duration = 900})
            table.insert(G.units, {id = 501, invader = true, flags1 = {}, pos = {x = 30, y = 30, z = 100}})""",
                    E.G, dx)
        r = E.weather_report(LUA.table_from([]))
        assert r.region.cloud_edge == dx and bool(r.near_fort) is walked, (dx, r.near_fort)
        assert (r.enemies_outside is not None) is walked


# --- 3. the pulse's weather section, the event, the edge --------------------------------

@test("3: the brain reads the weather section first (threats.weather from an older bridge); the rule runs "
      "with threats failed; a cloud 140 tiles off drifting in sounds the alarm (weather_edge_near 150)")
def _():
    s = fort(CLOUD, own=True)
    s["threats"] = {"weather": CALM}
    assert PW.weather_of(s) is s["weather"]
    assert PW.weather_of(fort(CLOUD)) == CLOUD                       # an older bridge
    assert PW.weather_of(fort(CLOUD, weather={})) == CLOUD           # an empty section: the threats copy
    assert PW.weather_of(planner.normalize(fort(None, weather={"error": "x"}))) == {}
    s = fort(CLOUD, own=True)
    s["threats"] = {"error": "boom"}
    props, _ = plan(s, Memory())
    assert alarms(props, True), "the weather section alone: the rule runs"
    assert PLANNER_CONFIG["weather_edge_near"] == 150
    near = dict(CALM, region={"clouds": 1, "rains": 0, "cloud_edge": 140, "approaching": True})
    assert alarms(plan(fort(near, own=True), Memory())[0], True)
    import digest
    assert "evil_cloud_tiles:12" in digest.threat_line(fort(CLOUD, own=True))


if LuaRuntime:
    LUA = LuaRuntime(unpack_returned_tuples=True)
    SRC = module_src("ai-threats.lua")

    def T(d):
        if isinstance(d, dict):
            return LUA.table_from({k: T(v) for k, v in d.items()})
        if isinstance(d, list):
            return LUA.table_from([T(v) for v in d])
        return d

    GAME = r"""
local src, setup = ...
local G = {}
local e = setmetatable({G = G}, {__index = _G})
e.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
local MATS = {
    ['1:1'] = {name = 'thick fog', id = 'FOG', syn = 'thrall'},
    ['4:4'] = {name = 'vile ooze', id = 'OOZE', syn = 'husking'},
}
G.flows, G.rw, G.units = {}, {}, {}
G.save = 'region1'
e.df = {global = {cur_year = 1, cur_year_tick = 0, flows = G.flows, current_weather = {},
                  world = {units = {active = G.units}, cur_savegame = setmetatable({}, {__index = function(_, k)
                               if k == 'save_dir' then return G.save end end}),
                           map = {region_x = 160, region_y = 320, x_count = 144, y_count = 144},
                           world_data = {region_weather = G.rw, world_width = 65, world_height = 65}}},
        flow_type = {MaterialGas = 'MaterialGas'}, weather_type = {Rain = 1},
        region_weather_type = {FallingMaterial = 'FallingMaterial', CreepingGas = 'CreepingGas'},
        creature_interaction_effect_type = setmetatable({}, {__index = function(_, k) return k end})}
e.dfhack = {
    maps = {getTileFlags = function(x, y, z) return {outside = z >= 100} end,
            getWalkableGroup = function() return 1 end},
    units = {getCitizens = function() return G.citizens or {} end, isActive = function() return true end,
             isDead = function() return false end, isHidden = function() return false end,
             isCitizen = function(u) return u.citizen end, isInvader = function(u) return u.invader end,
             isUndead = function() return false end, isGreatDanger = function() return false end,
             isDanger = function() return false end},
    matinfo = {decode = function(t, i)
        local m = MATS[tostring(t) .. ':' .. tostring(i)]
        if not m then return nil end
        return {material = {id = m.id, syndrome = {syndrome = {{syn_name = m.syn, ce = {}}}}},
                toString = function() return m.name end}
    end},
    persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end},
}
assert(load(src, 'ai-threats', 't', e))()
if setup then setup(G) end
return e
"""

    def game(setup="function(G) end"):
        return LUA.execute(GAME, SRC, LUA.eval(setup))

    @test("3 lua: the event watch: a cloud within a day's drift (120) drifting in, DF's announcement, evil rain: "
          "one event as each begins, read at most once a game hour; another save starts afresh")
    def _():
        E = game()
        assert E.WEATHER_EDGE_NEAR == PLANNER_CONFIG["weather_edge_near"]
        assert E.WEATHER_EDGE_REPORT >= E.WEATHER_EDGE_NEAR and E.WEATHER_EVENT_NEAR <= E.WEATHER_EDGE_NEAR
        G = E.G
        assert E.weather_watch(1000, "a") is None                      # nothing about
        LUA.execute("""local G = ...; table.insert(G.rw, {type = 'CreepingGas', mat_type = 1, mat_index = 1,
            flags = {}, world_in_game_x = 7680 - 100, world_in_game_y = 15400, cloud_x_movement = 1,
            cloud_y_movement = 0, remaining_duration = 900})""", G)
        assert E.weather_watch(1010, "a") is None                      # within the hour: not read again
        ev = E.weather_watch(1050, "a")
        assert ev and ev.kind == "weather" and ev.cloud_edge == 100 and ev.material == "thick fog", ev
        assert E.weather_watch(1100, "a") is None                      # still there: no second event
        G.rw[1].world_in_game_x = 7680 - 130                           # drifted past a day's drift
        assert E.weather_watch(1150, "a") is None
        G.rw[1].world_in_game_x = 7680 - 90
        assert E.weather_watch(1200, "a").cloud_edge == 90             # back: a new event
        G.rw[1].flags.announced = True
        assert E.weather_watch(1250, "a").announced                     # DF's announcement
        assert E.weather_watch(1260, "b") is not None                   # another save: afresh
        # the hook in the status call the overseer polls, and the pulse section
        br = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
        status = br[br.index("local function cmd_status()"):]
        status = status[:status.index("\nend\n")]
        assert "weather_watch(abs_tick(), fort_key())" in status and "push_event(ev)" in status

    @test("3 lua: weather_report reports clouds out to WEATHER_EDGE_REPORT (the brain applies its own edge); "
          "a nearer cloud drifting away doesn't hide one drifting in")
    def _():
        mp = T({"rx": 160, "ry": 320, "w": 144, "h": 144, "ww": 65, "wh": 65})
        E = game()
        S = E.weather_rows_summary
        r = S(T([{"kind": "cloud", "gx": 7680 - 300, "gy": 15400, "mx": 1, "mat": {}}]), mp, E.WEATHER_EDGE_REPORT)
        assert r.cloud_edge == 300 and r.approaching
        r = S(T([{"kind": "cloud", "gx": 7680 - 20, "gy": 15400, "mx": -1, "mat": {"name": "away"}},
                 {"kind": "cloud", "gx": 7680 - 80, "gy": 15400, "mx": 1, "mat": {"name": "coming"}}]), mp)
        assert r.cloud_edge == 80 and r.approaching and r.cloud_mat.name == "coming", (r.cloud_edge, r.approaching)
        r = S(T([{"kind": "cloud", "gx": 7680 - 20, "gy": 15400, "mx": -1, "mat": {}}]), mp)
        assert r.cloud_edge == 20 and not r.approaching

    # --- 4. rain: a region tile only past the world's size -----------------------------

    @test("4 lua: evil rain read as a region tile only when the number can't be a world tile")
    def _():
        E = game()
        S = E.weather_rows_summary
        small = T({"rx": 10, "ry": 20, "w": 144, "h": 144, "ww": 65, "wh": 65})   # world tile (0, 1)
        rain = lambda rx, ry: T([{"kind": "rain", "rx": rx, "ry": ry, "mat": {"syndrome": "husk"}}])
        assert S(rain(0, 1), small).rain_here                           # the world tile
        assert not S(rain(11, 21), small).rain_here                     # a world tile elsewhere, not the region's
        big = T({"rx": 160, "ry": 320, "w": 144, "h": 144, "ww": 65, "wh": 65})
        assert S(rain(161, 321), big).rain_here                         # past the world's size: a region tile
        nosize = T({"rx": 10, "ry": 20, "w": 144, "h": 144})
        assert not S(rain(11, 21), nosize).rain_here and S(rain(0, 1), nosize).rain_here

    # --- 9. bounded citizen walks ----------------------------------------------------------

    @test("9 lua: weather_report reads each citizen's position once and measures from at most "
          "WEATHER_MAX_NEAR_TILES cloud tiles")
    def _():
        E = game("""function(G)
            for i = 1, 40 do
                table.insert(G.flows, {type = 'MaterialGas', mat_type = 1, mat_index = 1, density = 50,
                                       pos = {x = 20 + i, y = 10, z = 100}, guide_id = 7})
            end
            end""")
        E.WEATHER_MAX_NEAR_TILES = 5
        cit = LUA.execute("""
            local reads = {n = 0}
            local list = {}
            for i = 1, 30 do
                local raw = {x = 10, y = 10 + i, z = 100, outside = i % 2 == 0}
                list[i] = setmetatable({}, {__index = function(_, k) reads.n = reads.n + 1; return raw[k] end})
            end
            return list, reads""")
        lst, reads = cit
        r = E.weather_report(lst)
        assert r.evil_cloud == 40 and r.near_capped and r.cloud_near == 11, (r.evil_cloud, r.cloud_near)
        assert reads.n <= 30 * 4, reads.n                              # x, y, z, outside: once each

    # --- 6. at the fort's walls (the gate scan) ---------------------------------------------

    @test("6 lua: the gate scan lists the enemies at the fort's walls apart from those inside")
    def _():
        src = (ROOT / "lua" / "ai-gates-watch.lua").read_text(encoding="utf-8")
        env = LUA.execute(r"""
local src = ...
local e = setmetatable({}, {__index = _G})
e.key = function(x, y, z) return x .. ',' .. y .. ',' .. z end
e.unkey = function(k) local x, y, z = k:match('^(-?%d+),(-?%d+),(-?%d+)$'); return tonumber(x), tonumber(y), tonumber(z) end
e.U, e.gate_name = {}, function() return 'g' end
local inside = {}
for x = 30, 60 do for y = 0, 20 do inside[x .. ',' .. y .. ',0'] = true end end
e.GATES = {scanned = true, inside = inside, entrances = {{inside_list = {'30,10,0'}, outs = {['29,10,0'] = true}}}}
local function u(id, x, y, z) return {id = id, pos = {x = x, y = y, z = z or 0}, flags1 = {}} end
local all = {u(1, 55, 10), u(2, 28, 10), u(3, 10, 10), u(4, 32, 10), u(5, 28, 0), u(6, 28, 10, 1)}
local by = {}
for _, x in ipairs(all) do by[x.id] = x end
e.df = {global = {world = {units = {active = all}}}, unit = {find = function(id) return by[id] end}}
e.dfhack = {units = {isAlive = function() return true end, isCitizen = function() return false end,
                     isDanger = function() return true end, isInvader = function() return false end},
            getCitizens = function() return {} end}
assert(load(src, 'ai-gates-watch', 't', e))()
return e
""", src)
        walls = env.intruders_at_walls()
        # 2: a tile from the gate's outside; 4: in the gate's tunnel. (fix41-ff) not 5 (beside a wall of
        # the fort far from any entrance), not 6 (a level up)
        assert sorted(walls.values()) == [2, 4], list(walls.values())
        assert list(env.intruders_at_walls(LUA.table_from([5, 2])).values()) == [2]   # only the ids asked
        assert list(env.intruders_inside().values()) == [1]                 # deep inside: not "at the walls"
        env.GATES.scanned = False
        assert env.intruders_at_walls() is None                             # no map: can't say
        br = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
        assert "o.intruders_at_walls = reqscript('ai-gates').intruders_at_walls(ids)" in br

    # --- 8. the fire-breath cache: one world's ------------------------------------------------

    @test("8 lua: fire_breath_of's cache is one world's: another save reads the raws again")
    def _():
        lua = LuaRuntime(unpack_returned_tuples=True)
        env = lua.execute(r"""
local src = ...
local e = setmetatable({}, {__index = _G})
local races = {[1] = {caste = {[0] = {body_info = {interactions = {{interaction = {material_breath = 9, type_id = -1}}}},
                                     flags = {}}}}}
e.RACES = races
e.SAVE = {save_dir = 'one'}
e.df = {breath_attack_type = {DRAGONFIRE = 9, FIREJET = 10, FIREBALL = 11},
        interaction = {find = function() return nil end},
        creature_raw = {find = function(id) return races[id] end},
        global = {world = {cur_savegame = e.SAVE, units = {active = {}}}}}
e.dfhack = {units = {}, maps = {}, persistent = {}}
assert(load(src, 'ai-threats', 't', e))()
return e
""", module_src("ai-threats.lua"))
        assert env.fire_breath_of(1, 0) == "breath"
        lua.execute("local e = ...; e.RACES[1].caste[0].body_info.interactions = {}", env)   # another world's race 1
        assert env.fire_breath_of(1, 0) == "breath"                     # the same world: cached
        env.SAVE.save_dir = "two"
        assert env.fire_breath_of(1, 0) is False                        # another save: read again


# --- 5 and 6: the fire breather's crossbows -----------------------------------------------

def dragon_fort(*, at_walls=True, weather=None):
    s = copy.deepcopy(BASE)
    s["others_on_map"]["threats"] = [{"id": 5000, "name": "Ostuk the dragon", "can_reach_dwarves": True,
                                      "great_danger": True, "flier": True, "destroyer": True, "invader": False,
                                      "layer": "surface", "distance_to_nearest_dwarf": 15,
                                      "levels_from_nearest_dwarf": 0, "size": 25_000_000, "kinds": ["Megabeast"],
                                      "fire_breather": True, "fire_how": "breath"}]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    for q in s["military"]["squads"]:
        q["power"] = {"power": 5000, "armed": 10}
    s["military"]["squads"][1]["ai_uniform"] = "AI crossbows"
    ent = s["entrances"]
    ent["armed"] = True
    ent["entrances"] = [{"id": 1, "kind": "surface", "x": 31, "y": 140, "z": 173, "width": 1, "sealed": True,
                         "closed": True, "equipment": [{"id": 500, "kind": "door"}], "door_spots": 0}]
    ent["intruders_inside"] = []
    if at_walls is not None:
        ent["intruders_at_walls"] = [5000] if at_walls else []
    if weather is not None:
        s["weather"] = weather
    return s


def at_dragon(props):
    return [p for p in props if p.action.get("type") == "squad_orders" and 5000 in (p.action.get("kill") or [])]


@test("5: a fire breather standing in the evil weather: no crossbows sent, the crossbow squad stays in the "
      "shelter, one note says why")
def _():
    props, notes = plan(dragon_fort(), Memory())
    assert at_dragon(props), "the baseline: the crossbows shoot from inside"
    props, notes = plan(dragon_fort(weather=dict(CLOUD, enemies_outside=[5000])), Memory())
    assert not at_dragon(props), [p.action for p in props]
    sh = [p for p in props if p.action.get("type") == "shelter_squads"]
    assert sh and any(12 in p.action["squads"] for p in sh), [p.action for p in props]
    assert any("evil weather" in n and "Ostuk" in n for n in notes), notes
    assert not any("not sent out at enemies standing in the evil weather" in n for n in notes), notes
    # a crossbow squad already on it is called back, saying why
    s = dragon_fort(weather=dict(CLOUD, enemies_outside=[5000]))
    q = s["military"]["squads"][1]
    q["ai_orders"], q["kill_ids"] = 1, [5000]
    props, _ = plan(s, Memory())
    rec = [p for p in props if p.rule == "squad_recall" and p.action.get("squad_id") == 12]
    assert rec and "evil weather" in rec[0].reason, [(p.rule, p.action) for p in props]


@test("6: crossbows only at a fire breather at the fort's walls: not one away from them, not without the "
      "gate scan's map")
def _():
    for at, word in ((False, "isn't at the fort's walls"), (None, "no map of the fort's walls")):
        props, notes = plan(dragon_fort(at_walls=at), Memory())
        assert not at_dragon(props), (at, [p.action for p in props])
        assert any(word in n for n in notes), (at, notes)
    t = dragon_fort()["others_on_map"]["threats"][0]
    assert PF.fire_ranged_ok(dragon_fort(), Memory(), t) == ""
    doc = (ROOT / "brain" / "planner_firebreath.py").read_text(encoding="utf-8")
    assert "lua/ai-threats.lua fire_breath_of" in doc and "leaky path" in doc


if LuaRuntime:
    test("ff 7 lua: the units outside walked only for a cloud within WEATHER_EDGE_NEAR (not every one "
         "reported out to WEATHER_EDGE_REPORT)")(ff7_lua)


if __name__ == "__main__":
    finish()
