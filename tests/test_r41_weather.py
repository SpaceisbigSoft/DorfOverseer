"""(0.105.40b) Evil weather: the bridge's threats.weather (lua/ai-threats.lua
weather_report, weather_rows_summary) on fakes, and the planner's rule
(brain/planner_weather.py): the alarm on, held, lifted hours after, capped,
the player's lowering obeyed, squads not sent out into it; nothing changed
on fixtures without weather data.

    python tests/test_r41_weather.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from lua_modules_util import module_src  # noqa: E402
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import planner  # noqa: E402
from planner import Memory, plan, select, Proposal, PLANNER_CONFIG, TICKS_PER_DAY, abs_tick  # noqa: E402
import planner_weather as PW  # noqa: E402
from planner_threats import alarm_held  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
HOUR = 50

CLOUD = {"evil_cloud": 12, "cloud_near": 70, "material": "thick fog", "syndrome": "thrall's breath",
         "effects": ["ADD_TAG"], "region": {"clouds": 1, "rains": 0, "cloud_edge": 0, "announced": True},
         "near_fort": True, "enemies_outside": []}
CALM = {"evil_cloud": 0, "region": {"clouds": 0, "rains": 0}, "near_fort": False}


def fort(weather, tick=100000, **kw) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["tick"] = tick
    s["threats"] = {} if weather is None else {"weather": weather}
    s.setdefault("civ_alert", False)
    s["civ_alert_ready"] = True
    s.update(kw)
    return s


def alarms(props, on=None):
    return [p for p in props if p.action.get("type") == "civ_alert" and (on is None or p.action["on"] is on)]


def strip(props):
    return [(p.rule, json.dumps(p.action, sort_keys=True), p.priority) for p in props]


# --- the rule ----------------------------------------------------------------------

@test("an evil cloud on the map's surface: the alarm sounds, the reason names it")
def _():
    m = Memory()
    props, notes = plan(fort(CLOUD), m)
    on = alarms(props, True)
    assert on and on[0].rule == "threat_alert" and "evil cloud of thick fog" in on[0].reason, props
    assert "thrall's breath" in on[0].reason and "outside stop" in on[0].reason, on[0].reason
    assert m.weather_alarm.get("was_off") and m.weather_alarm.get("seen") == m.weather_alarm.get("since")


@test("nothing about: no alarm, no note, memory untouched; a cloud far off and drifting away: none either")
def _():
    m = Memory()
    props, notes = plan(fort(CALM), m)
    assert not alarms(props) and m.weather_alarm == {} and not any("evil" in n for n in notes)
    far = dict(CALM, region={"clouds": 1, "rains": 0, "cloud_edge": 30})            # not approaching
    assert not alarms(plan(fort(far), Memory())[0])
    near = dict(CALM, region={"clouds": 1, "rains": 0, "cloud_edge": 30, "approaching": True})
    p = alarms(plan(fort(near), Memory())[0], True)
    assert p and "30 tiles from the map's edge, drifting this way" in p[0].reason, p
    out = dict(CALM, region={"clouds": 1, "rains": 0, "cloud_edge": 160, "approaching": True})  # past weather_edge_near
    assert not alarms(plan(fort(out), Memory())[0])


@test("evil rain on the fort: the alarm; plain blood rain: a note, work goes on (unless the config says)")
def _():
    rain = dict(CALM, rain="evil", rain_material="vile ooze", rain_syndrome="husking", near_fort=True)
    p = alarms(plan(fort(rain), Memory())[0], True)
    assert p and "evil rain of vile ooze falling on the fort (husking)" in p[0].reason, p
    blood = dict(CALM, rain="blood", rain_material="goblin blood", near_fort=True)
    props, notes = plan(fort(blood), Memory())
    assert not alarms(props) and any("only stains" in n for n in notes), notes
    cfg = dict(PLANNER_CONFIG, weather_blood_rain_alarm=True)
    assert alarms(plan(fort(blood), Memory(), cfg)[0], True)


@test("held while it lasts and weather_lift_hours after; then lowered by the AI that raised it")
def _():
    m = Memory()
    t0 = 100000
    plan(fort(CLOUD, t0), m)                                   # raised (off -> was_off)
    m.ai_alert_raised = True
    m.quiet_cycles = 50                                        # the main rule would lower it (all clear)
    props, notes = plan(fort(CLOUD, t0 + HOUR, civ_alert=True), m)
    assert m.weather_alarm.get("on_seen") and not alarms(props, False), props
    assert any("alarm stays up" in n for n in notes), notes
    # gone 2 hours: still held (the main rule's lowering is taken back)
    t = t0 + 3 * HOUR
    s = fort(CALM, t, civ_alert=True)
    props, notes = plan(s, m)
    assert not alarms(props, False) and any("gone 2 game hour(s) ago" in n for n in notes), (props, notes)
    m2 = copy.deepcopy(m)
    m2.weather_alarm = {}
    assert alarms(plan(s, m2)[0], False), "without the spell the main rule lowers it (so the hold is real)"
    assert alarm_held(planner.normalize(s), m, PLANNER_CONFIG), "the strategist's alarm-off is held too"
    sp = Proposal("strategist", {"type": "civ_alert", "on": False}, "x", 0)
    a, h = select([sp], s, m)
    assert not a and any("alarm stays up" in x for x in h), (a, h)
    # gone weather_lift_hours: lowered, the spell forgotten
    t = t0 + HOUR + PLANNER_CONFIG["weather_lift_hours"] * HOUR
    m3 = copy.deepcopy(m)
    props, notes = plan(fort(CALM, t, civ_alert=True), m)
    assert alarms(props, False) and m.weather_alarm == {}, (props, notes)    # (the main rule's own lowering)
    m3.quiet_cycles = 0                                                     # the main rule would hold it
    props, notes = plan(fort(CALM, t, civ_alert=True), m3)
    off = alarms(props, False)
    assert off and "has been gone" in off[0].reason, (props, notes)
    assert m3.weather_alarm == {}


@test("the alarm up before the weather (the player's or another rule's): the weather never lowers it")
def _():
    m = Memory(ai_alert_raised=False)
    plan(fort(CLOUD, 100000, civ_alert=True), m)
    assert m.weather_alarm.get("on_seen") and not m.weather_alarm.get("was_off")
    props, _ = plan(fort(CALM, 100000 + 20 * HOUR, civ_alert=True), m)
    assert not [p for p in alarms(props, False) if "has been gone" in p.reason], props


@test("the player lowers it during the spell: not sounded again till a new spell")
def _():
    m = Memory()
    plan(fort(CLOUD, 100000), m)
    m.ai_alert_raised = True
    plan(fort(CLOUD, 100000 + HOUR, civ_alert=True), m)
    props, notes = plan(fort(CLOUD, 100000 + 2 * HOUR, civ_alert=False), m)
    assert not alarms(props, True) and m.weather_alarm.get("cleared"), props
    assert any("leaves it down for this spell" in n for n in notes), notes
    assert not alarms(plan(fort(CLOUD, 100000 + 3 * HOUR), m)[0], True)
    # gone, then a new cloud: sounded again
    plan(fort(CALM, 100000 + 20 * HOUR), m)
    assert m.weather_alarm == {}
    assert alarms(plan(fort(CLOUD, 100000 + 21 * HOUR), m)[0], True)


@test("held weather_alarm_max_days at most in one spell, then said and let be")
def _():
    m = Memory()
    plan(fort(CLOUD, 100000), m)
    m.ai_alert_raised = True
    days = PLANNER_CONFIG["weather_alarm_max_days"]
    s = fort(CLOUD, 100000 + days * TICKS_PER_DAY, civ_alert=True)
    props, notes = plan(s, m)
    assert m.weather_alarm.get("capped") and any("no longer holds it" in n for n in notes), notes
    assert not PW.weather_held(planner.normalize(s), m, PLANNER_CONFIG)


@test("no civilian-alert burrow: the AI's own shelter is set up for it")
def _():
    s = fort(CLOUD)
    s["civ_alert_ready"] = False
    props, notes = plan(s, Memory())
    assert any(p.action.get("type") == "setup_shelter" for p in props) or any("shelter" in n for n in notes), notes


@test("squads: not sent out at enemies standing in it; sent when enemies are inside")
def _():
    w = dict(CLOUD, enemies_outside=[501, 502])
    s = planner.normalize(fort(w))
    mk = lambda kill: Proposal("squad_attack", {"type": "squad_orders", "squad_id": 1, "kill": kill}, "x", 0)
    props = [mk([501, 502]), mk([501, 900]), Proposal("drink", {"type": "work_order"}, "x", 3)]
    notes = []
    out = PW._weather_squad_filter(s, Memory(), PLANNER_CONFIG, props, notes)
    kills = [p.action.get("kill") for p in out if p.action.get("type") == "squad_orders"]
    assert kills == [[900]] and len(out) == 2 and any("not sent out" in n for n in notes), (kills, notes)
    # an enemy inside that can reach the dwarves: the squads are left alone
    s["others_on_map"] = {"threats": [{"id": 900, "can_reach_dwarves": True}], "threats_that_can_reach_dwarves": 1}
    props = [mk([501, 502])]
    assert PW._weather_squad_filter(s, Memory(), PLANNER_CONFIG, props, []) == props
    # no weather: nothing touched
    s = planner.normalize(fort(CALM))
    props = [mk([501])]
    assert PW._weather_squad_filter(s, Memory(), PLANNER_CONFIG, props, []) is props


@test("identity: fixtures without weather data plan exactly as before; a failed weather part is ignored")
def _():
    for extra in (None, {"error": "boom"}):
        base = copy.deepcopy(BASE)
        m1, m2 = Memory(), Memory()
        p1, n1 = plan(base, m1)
        s2 = copy.deepcopy(BASE)
        if extra is not None:
            s2["threats"] = {"weather": extra}
        p2, n2 = plan(s2, m2)
        assert strip(p1) == strip(p2) and n1 == n2, extra
        assert m2.weather_alarm == {}
    assert PW.weather_line(BASE) == "" and PW.weather_held(BASE, Memory(), PLANNER_CONFIG) == ""
    assert alarm_held(planner.normalize(copy.deepcopy(BASE)), Memory(), PLANNER_CONFIG) == \
        alarm_held(planner.normalize(copy.deepcopy(BASE)), None, PLANNER_CONFIG)


@test("digest: the threats line names the evil weather")
def _():
    import digest
    line = digest.threat_line(fort(dict(CLOUD, rain="evil")))
    assert "evil_cloud_tiles:12" in line and "evil_rain" in line and "syndrome:thrall's breath" in line, line
    assert digest.threat_line(fort(CALM)) == ""


# --- the Lua side ----------------------------------------------------------------

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

if LuaRuntime:
    LUA = LuaRuntime(unpack_returned_tuples=True)
    SRC = module_src("ai-threats.lua")

    def T(d):
        if isinstance(d, dict):
            return LUA.table_from({k: T(v) for k, v in d.items()})
        if isinstance(d, list):
            return LUA.table_from([T(v) for v in d])
        return d

    ENV = LUA.execute("local src = ...; local e = setmetatable({}, {__index = _G}); "
                      "assert(load(src, 'ai-threats', 't', e))(); return e", SRC)

    @test("lua: DF's evil weather records against the map (clouds over, approaching, away; rain here or not)")
    def _():
        mp = T({"rx": 160, "ry": 320, "w": 144, "h": 144, "ww": 65, "wh": 65})   # world tile (10, 20); map at 7680, 15360
        S = ENV.weather_rows_summary
        r = S(T([{"kind": "cloud", "gx": 7700, "gy": 15400, "announced": True, "left": 900,
                  "mat": {"name": "fog", "syndrome": "thrall"}}]), mp)
        assert r.clouds == 1 and r.cloud_edge == 0 and r.approaching and r.announced and r.left == 900
        r = S(T([{"kind": "cloud", "gx": 7650, "gy": 15400, "mx": 1, "my": 0, "mat": {}}]), mp)
        assert r.cloud_edge == 30 and r.approaching, (r.cloud_edge, r.approaching)
        r = S(T([{"kind": "cloud", "gx": 7650, "gy": 15400, "mx": -1, "my": 0, "mat": {}}]), mp)
        assert r.cloud_edge == 30 and not r.approaching
        r = S(T([{"kind": "cloud", "gx": 7000, "gy": 15400, "mx": 1, "mat": {}}]), mp)
        assert r.clouds == 1 and r.cloud_edge is None
        r = S(T([{"kind": "cloud", "gx": -30000, "gy": -30000}]), mp)
        assert r.clouds == 0
        for rx, ry in ((10, 20), (161, 321)):                     # the world tile; a region tile of the embark
            r = S(T([{"kind": "rain", "rx": rx, "ry": ry, "mat": {"name": "ooze", "syndrome": "husk"}}]), mp)
            assert r.rain_here and r.rains == 1 and r.rain_mat.syndrome == "husk", (rx, ry)
        r = S(T([{"kind": "rain", "rx": 11, "ry": 20, "mat": {}}]), mp)
        assert not r.rain_here and r.rains == 0

    GAME = r"""
local src, setup = ...
local G = {}
local e = setmetatable({G = G}, {__index = _G})
e.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
local FT = {MaterialGas = 'MaterialGas', MaterialDust = 'MaterialDust', Miasma = 'Miasma', ItemCloud = 'ItemCloud',
            MaterialVapor = 'MaterialVapor'}
local MATS = {
    ['1:1'] = {name = 'thick fog', id = 'FOG', syn = {{syn_name = "thrall's breath", ce = {{t = 'ADD_TAG'}, {t = 'BODY_TRANSFORMATION'}}}}},
    ['2:2'] = {name = 'dust', id = 'DUST', syn = {}},
    ['3:3'] = {name = 'goblin blood', id = 'BLOOD', syn = {}},
    ['4:4'] = {name = 'vile ooze', id = 'OOZE', syn = {{syn_name = 'husking', ce = {}}}},
}
G.flows, G.rw, G.units = {}, {}, {}
G.weather = {[0] = {[0] = 0, 0, 0, 0, 0}, {[0] = 0, 0, 0, 0, 0}, {[0] = 0, 0, 0, 0, 0}, {[0] = 0, 0, 0, 0, 0},
             {[0] = 0, 0, 0, 0, 0}}
e.df = {global = {cur_year = 1, cur_year_tick = 0, flows = G.flows, current_weather = G.weather,
                  world = {units = {active = G.units}, map = {region_x = 160, region_y = 320, x_count = 144, y_count = 144},
                           world_data = {region_weather = G.rw}}},
        flow_type = FT, weather_type = {Rain = 1},
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
        local syn = {}
        for _, s in ipairs(m.syn) do
            local ce = {}
            for _, c in ipairs(s.ce) do table.insert(ce, {getType = function() return c.t end}) end
            table.insert(syn, {syn_name = s.syn_name, ce = ce})
        end
        return {material = {id = m.id, syndrome = {syndrome = syn}}, toString = function() return m.name end}
    end},
    persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end},
}
assert(load(src, 'ai-threats', 't', e))()
if setup then setup(G) end
return e
"""

    def game(setup):
        return LUA.execute(GAME, SRC, LUA.eval(setup))

    CIT = [{"x": 10, "y": 10, "z": 100, "outside": True}]

    @test("lua: weather_report on a fake game: clouds by guide or syndrome, inside or harmless ones not")
    def _():
        E = game("""function(G)
            local function f(t, mt, mi, z, gid) return {type = t, mat_type = mt, mat_index = mi, density = 50,
                pos = {x = 20, y = 10, z = z}, guide_id = gid} end
            table.insert(G.flows, f('MaterialGas', 2, 2, 100, 7))      -- a trailing cloud (guide), outside
            table.insert(G.flows, f('MaterialDust', 1, 1, 100, -1))    -- no guide, a syndrome: counted
            table.insert(G.flows, f('MaterialDust', 2, 2, 100, -1))    -- no guide, harmless: not
            table.insert(G.flows, f('MaterialGas', 1, 1, 50, 7))       -- inside: not
            table.insert(G.flows, f('Miasma', 1, 1, 100, -1))          -- not a cloud kind
            table.insert(G.units, {id = 501, invader = true, flags1 = {}, pos = {x = 30, y = 30, z = 100}})
            table.insert(G.units, {id = 502, invader = true, flags1 = {}, pos = {x = 30, y = 30, z = 50}})
            table.insert(G.units, {id = 503, citizen = true, flags1 = {}, pos = {x = 30, y = 30, z = 100}})
            end""")
        r = E.weather_report(T(CIT))
        assert r.evil_cloud == 2 and r.cloud_near == 10 and r.cloud_outside_near == 10, (r.evil_cloud, r.cloud_near)
        assert r.syndrome == "thrall's breath" and list(r.effects.values()) == ["ADD_TAG", "BODY_TRANSFORMATION"]
        assert r.near_fort and list(r.enemies_outside.values()) == [501] and r.rain is None and not r.raining

    @test("lua: weather_report: evil and blood rain on the fort's tile, DF's rain, a calm map")
    def _():
        E = game("""function(G)
            table.insert(G.rw, {type = 'FallingMaterial', mat_type = 4, mat_index = 4, flags = {announced = true},
                                region_x = 10, region_y = 20, remaining_duration = 300})
            G.weather[2][3] = 1
            end""")
        r = E.weather_report(T(CIT))
        assert r.rain == "evil" and r.rain_syndrome == "husking" and r.rain_material == "vile ooze" and r.raining
        assert r.near_fort and r.region.rains == 1 and r.region.announced and r.evil_cloud == 0
        E = game("""function(G)
            table.insert(G.rw, {type = 'FallingMaterial', mat_type = 3, mat_index = 3, flags = {},
                                region_x = 10, region_y = 20, remaining_duration = 300})
            end""")
        r = E.weather_report(T(CIT))
        assert r.rain == "blood" and not r.rain_syndrome
        E = game("""function(G)
            table.insert(G.rw, {type = 'CreepingGas', mat_type = 1, mat_index = 1, flags = {},
                                world_in_game_x = 7650, world_in_game_y = 15400, cloud_x_movement = 1,
                                cloud_y_movement = 0, remaining_duration = 500})
            end""")
        r = E.weather_report(T(CIT))
        assert r.region.cloud_edge == 30 and r.region.approaching and r.region.cloud_syndrome == "thrall's breath"
        assert r.near_fort and r.syndrome == "thrall's breath"
        E = game("function(G) end")
        r = E.weather_report(T(CIT))
        assert r.evil_cloud == 0 and not r.near_fort and r.enemies_outside is None and r.region.clouds == 0

    @test("lua (fix41): the weather is its own report section, in the pulse too, not in the daily survey")
    def _():
        src = (ROOT / "lua" / "ai-threats.lua").read_text(encoding="utf-8")
        assert "part('weather'" not in src
        br = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
        assert "weather = function() return safe(function() return reqscript('ai-threats').weather_section() end) end" in br
        pulse = br[br.index("PULSE_SECTIONS = {"):br.index("}", br.index("PULSE_SECTIONS = {"))]
        assert "'weather'" in pulse, pulse
        E = game("""function(G)
            table.insert(G.rw, {type = 'FallingMaterial', mat_type = 4, mat_index = 4, flags = {},
                                region_x = 10, region_y = 20, remaining_duration = 300})
            G.citizens = {{id = 1, pos = {x = 10, y = 10, z = 100}}}
            end""")
        r = E.weather_section()
        assert r.rain == "evil" and r.near_fort and r.region.edge_near == 150, r


if __name__ == "__main__":
    finish()
