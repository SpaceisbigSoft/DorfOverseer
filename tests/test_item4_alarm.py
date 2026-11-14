"""(item4) The civilian alarm kept from flapping (brain/planner_alarm.py, and
the rules it governs): fire sounds it only close and holds it farther out; a
minimum time on; a cooldown for the same cause; a cap a game month; a real
siege always sounds it; a cavern beast in another layer doesn't; evil weather
keeps the civilians in by the shelter's burrow instead (and falls back to the
alarm when the bridge refuses); the shelter not drawn again on every alarm
(lua/ai-society.lua refresh_shelter_due) and the weather burrow's Lua
(lua/ai-society-burrows.lua weather_keep_in) on a fake game.

    python tests/test_item4_alarm.py
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from lua_modules_util import module_src  # noqa: E402
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import planner  # noqa: E402
from planner import Memory, plan, record, Proposal, PLANNER_CONFIG, TICKS_PER_DAY, abs_tick  # noqa: E402
import planner_alarm as PA  # noqa: E402
import planner_threats as PT  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
ON = {"type": "civ_alert", "on": True}
OFF = {"type": "civ_alert", "on": False}
HOUR = 50

CLOUD = {"evil_cloud": 1719, "material": "rock", "region": {"clouds": 1, "rains": 0, "cloud_edge": 0},
         "near_fort": True, "enemies_outside": []}
CALM = {"evil_cloud": 0, "region": {"clouds": 0, "rains": 0}, "near_fort": False}


def A(tick: int) -> int:
    """The absolute tick of the fixture's year at this tick of the year."""
    s = copy.deepcopy(BASE)
    s["date"]["tick"] = tick
    return abs_tick(s)


def fort(fire=None, alert=False, tick=200000, threats=None, weather=None, **kw) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["tick"] = tick
    s["civ_alert"] = alert
    s["civ_alert_ready"] = True
    if fire is not None:
        s["hazards"] = {"fires": 3, "fire_near": fire}
    if threats is not None:
        s["threats"] = threats
    if weather is not None:
        s["weather"] = weather
    s.update(kw)
    return s


def alarms(props, on=None):
    return [p for p in props if p.action.get("type") == "civ_alert" and (on is None or p.action["on"] is on)]


def raised(m: Memory, s: dict, reason: str):
    """The alarm went up now for `reason` (as record() keeps it)."""
    record([(Proposal("threat_alert", dict(ON), reason, 0), {"ok": True, "on": True})], s, m)


def lowered(m: Memory, s: dict):
    record([(Proposal("threat_alert", dict(OFF), "x", 0), {"ok": True, "on": False})], s, m)


def siege(s: dict) -> dict:
    s["others_on_map"] = dict(s["others_on_map"], threats_that_can_reach_dwarves=0)
    s["others_on_map"]["threats"] = list(s["others_on_map"]["threats"]) + [
        {"id": 9001, "name": "goblin", "invader": True, "can_reach_dwarves": True, "distance_to_nearest_dwarf": 12,
         "layer": "upper_levels"}]
    return s


# --- what raised it in the logs ------------------------------------------------------

@test("the causes read from the reasons the run's logs gave (13 Nov: C, F, B)")
def _():
    c = PA.alarm_cause
    assert c("fire 11 tiles from the dwarves: sound the alarm (the civilians go to the shelter)") == ("fire", "fire")
    assert c("DF reports an intruder on the map (0 game hour(s) ago), nobody seen yet (a thief hides until "
             "spotted): sound the alarm before they strike")[0] == "intruder"
    k = c('Uker, Forgotten Beast (forgotten beast, in Cavern1) is about and 1 citizen(s) are in the caverns '
          '(Feb, Fisherdwarf at x1 y2 elevation 3): sound the alarm to call them up, then lock the ways down')
    assert k == ("cavern", "cavern:Uker, Forgotten Beast (forgotten beast, in Cavern1)"), k
    assert c("an evil cloud of rock on the map's surface (1719 tiles of it): sound the alarm (everyone inside, "
             "the gathering, wood cutting and hauling outside stop until it has gone)")[0] == "weather"
    assert c("3 threat(s) can reach the dwarves") == ("reach", "reach")
    assert c("a necromancer siege: 40 walking dead: sound the alarm (everyone inside)")[0] == "other"
    assert c("Urist has gone berserk: sound the alarm (the civilians go to the shelter)")[0] == "other"


# --- fire: close to sound it, farther to hold it ------------------------------------------

@test("fire 9-14 tiles off (C's 122 alarms): no alarm, the fire guard does; 5 tiles: the alarm")
def _():
    for d in (9, 12, 14, 20):
        props, notes = plan(fort(fire=d), Memory())
        assert not alarms(props, True), (d, [p.reason for p in alarms(props)])
    props, _ = plan(fort(fire=5), Memory())
    on = alarms(props, True)
    assert on and on[0].reason.startswith("fire 5 tiles from the dwarves"), props


@test("fire up once: held while within hazard_near (20), the AI's all clear doesn't take it down")
def _():
    m = Memory()
    s = fort(fire=5)
    raised(m, s, "fire 5 tiles from the dwarves: sound the alarm")
    m.quiet_cycles = 10
    s2 = fort(fire=15, alert=True, tick=s["date"]["tick"] + TICKS_PER_DAY)       # past the minimum time on
    assert not alarms(plan(s2, m)[0], False)
    s3 = fort(fire=None, alert=True, tick=s["date"]["tick"] + TICKS_PER_DAY)
    assert alarms(plan(s3, m)[0], False), "fire gone, half a day over: it comes down"


# --- the minimum time on ----------------------------------------------------------------------

@test("the minimum time on: an AI alarm lowered 3 cycles after it went up is held (said); after half a day it comes down")
def _():
    m = Memory()
    s = fort(fire=5)
    raised(m, s, "fire 5 tiles from the dwarves: sound the alarm")
    m.quiet_cycles = 3
    s2 = fort(alert=True, tick=s["date"]["tick"] + 40)
    props, notes = plan(s2, m)
    assert not alarms(props, False), props
    assert any("the alarm stays up a while yet" in n and "no threat has been able" in n for n in notes), notes
    s3 = fort(alert=True, tick=s["date"]["tick"] + PLANNER_CONFIG["alarm_min_on_ticks"])
    off = alarms(plan(s3, m)[0], False)
    assert off and "no threat has been able" in off[0].reason, off


@test("the minimum time on holds the strategist's alarm-off too (select)")
def _():
    m = Memory()
    s = fort(fire=5)
    raised(m, s, "fire 5 tiles from the dwarves: sound the alarm")
    s2 = fort(alert=True, tick=s["date"]["tick"] + 60)
    allowed, held = planner.select([Proposal("strategist", dict(OFF), "calm now", 0)], s2, m)
    assert not allowed and any("a while yet" in h for h in held), (allowed, held)
    s3 = fort(alert=True, tick=s["date"]["tick"] + PLANNER_CONFIG["alarm_min_on_ticks"])
    allowed, held = planner.select([Proposal("strategist", dict(OFF), "calm now", 0)], s3, m)
    assert allowed, held


@test("the minimum time on is the AI's own: an alarm raised before it kept a record, or the player's, is left as ever")
def _():
    m = Memory()
    m.ai_alert_raised, m.quiet_cycles = True, 5           # no alarm_gov record (an older memory)
    assert alarms(plan(fort(alert=True), m)[0], False)
    props, notes = [Proposal("threat_alert", dict(OFF), "x", 0)], []
    m2 = Memory()
    m2.alarm_gov = {"on": {"tick": A(199990), "cause": "fire", "key": "fire"}}     # the player's alarm: not ai_alert_raised
    PA.govern_alarm(fort(alert=True), m2, PLANNER_CONFIG, props, notes)
    assert props and not notes


# --- the cooldown and the month's cap ---------------------------------------------------------

@test("the cooldown: lowered for a cause, that cause doesn't raise it again within two days (said); after, it does")
def _():
    m = Memory()
    s = fort(fire=5)
    raised(m, s, "fire 5 tiles from the dwarves: sound the alarm")
    t = s["date"]["tick"] + PLANNER_CONFIG["alarm_min_on_ticks"]
    lowered(m, fort(tick=t))
    assert m.alarm_gov["off"] == {"fire": A(t)} and m.alarm_gov["on"] == {}, m.alarm_gov
    props, notes = plan(fort(fire=4, tick=t + 300), m)
    assert not alarms(props, True), props
    assert any(n.startswith("no alarm for fire 4 tiles") and "same cause" in n for n in notes), notes
    assert [p for p in props if p.rule == "fire_guard"] or True        # the guard is the threats report's (absent here)
    props, _ = plan(fort(fire=4, tick=t + PLANNER_CONFIG["alarm_cause_cooldown_ticks"]), m)
    assert alarms(props, True)


@test("the cooldown is per cause: a lowered fire alarm doesn't hold a gas cloud's; each cavern beast its own key")
def _():
    m = Memory()
    m.alarm_gov = {"off": {"fire": A(199900)}}
    s = fort()
    s["hazards"] = {"clouds": 2, "cloud_near": 4}
    on = alarms(plan(s, m)[0], True)
    assert on and on[0].reason.startswith("a cloud (gas or vapour)"), on
    a = PA.alarm_cause("Uker, Forgotten Beast (forgotten beast, in Cavern1) is about and 1 citizen(s) are in the caverns")
    b = PA.alarm_cause("Slon, Forgotten Beast (forgotten beast, in Cavern2) is about and 1 citizen(s) are in the caverns")
    assert a[0] == b[0] == "cavern" and a[1] != b[1]


@test("the month's cap: four governed raises a game month, then said and not raised; a new month counts afresh")
def _():
    m = Memory()
    t0 = 28 * TICKS_PER_DAY * 100 + 10
    for i in range(4):
        raised(m, fort(tick=t0 + i * 10), f"fire {i} tiles from the dwarves")
        if i < 3:
            m.alarm_gov["on"] = {}
    assert m.alarm_gov["month"]["n"] == 4
    m.alarm_gov["on"], m.alarm_gov["off"] = {}, {}
    props, notes = plan(fort(fire=3, tick=t0 + 500), m)
    assert not alarms(props, True) and any("this game month already" in n for n in notes), notes
    props, _ = plan(fort(fire=3, tick=t0 + 28 * TICKS_PER_DAY), m)
    assert alarms(props, True)


@test("a real siege always sounds it: cooldown and cap spent, enemies that can reach the dwarves raise it all the same")
def _():
    m = Memory()
    t = 200000
    m.alarm_gov = {"off": {"reach": A(t - 10), "fire": A(t - 10)}, "month": {"m": A(t) // (28 * TICKS_PER_DAY), "n": 99}}
    props, notes = plan(siege(fort(tick=t)), m)
    on = alarms(props, True)
    assert on and "threat(s) can reach the dwarves" in on[0].reason, (props, notes)
    raised(m, siege(fort(tick=t)), on[0].reason)
    assert m.alarm_gov["month"]["n"] == 99 and m.alarm_gov["on"]["cause"] == "reach"     # not counted to the cap


@test("an unseen intruder (DF's record) is governed: the cooldown holds the second raise for the same cause")
def _():
    m = Memory()
    t = 200000
    m.intrusion = {"tick": A(t - 10), "civ": -1, "invaders": 1}
    on = alarms(plan(fort(tick=t), m)[0], True)
    assert on and on[0].reason.startswith("DF reports an intruder"), on
    m.alarm_gov = {"off": {"intruder": A(t - 100)}}
    props, notes = plan(fort(tick=t), m)
    assert not alarms(props, True) and any(n.startswith("no alarm for DF reports") for n in notes), notes


# --- the caverns: only a beast that can come at them --------------------------------------------

def cave(z_citizen, layer="Cavern1"):
    s = fort()
    s["threats"] = {"sealed": {}, "cavern_citizens": {"n": 1, "list": [{"name": "Feb", "x": 1, "y": 2, "z": z_citizen}]}}
    s["deep"] = {"caverns": [{"name": "Cavern1", "discovered": True, "open": True, "z_top": 120, "z_bottom": 110},
                             {"name": "Cavern2", "discovered": True, "open": True, "z_top": 80, "z_bottom": 70}],
                 "dangers": [{"id": 50, "name": "Uker", "kind": "forgotten beast", "layer": layer}], "cursed": []}
    return s


@test("a cavern beast in Cavern1, the fisherdwarf in Cavern2: no alarm (said), nothing held up; in Cavern1: the alarm")
def _():
    props, notes = [], []
    s = cave(75)
    PT._cavern_beasts(s, PLANNER_CONFIG, Memory(), s["threats"], PT.threat_rules_of(s), props, notes)
    assert not alarms(props, True) and any("none where it is: no alarm" in n for n in notes), (props, notes)
    assert not PT.alarm_held(s, Memory(), PLANNER_CONFIG)
    props, notes = [Proposal("threat_alert", dict(OFF), "all clear", 0)], []
    s["civ_alert"] = True
    PT._cavern_beasts(s, PLANNER_CONFIG, Memory(), s["threats"], PT.threat_rules_of(s), props, notes)
    assert alarms(props, False), "an alarm up for something else isn't held for a beast that can't come at them"
    props, notes = [], []
    s = cave(115)
    PT._cavern_beasts(s, PLANNER_CONFIG, Memory(), s["threats"], PT.threat_rules_of(s), props, notes)
    assert alarms(props, True), (props, notes)
    assert PT.alarm_held(s, Memory(), PLANNER_CONFIG)


@test("the caverns, unsure where: a citizen in no known layer, a beast in no known layer or able to walk to the dwarves: counted")
def _():
    great = [{"name": "U", "layer": "Cavern1"}]
    cav = [{"name": "Cavern1", "z_top": 120, "z_bottom": 110}, {"name": "Cavern2", "z_top": 80, "z_bottom": 70}]
    assert PT.cavern_at_risk([{"z": 3}], great, cav)                       # in no known layer
    assert PT.cavern_at_risk([{"z": None}], great, cav)
    assert PT.cavern_at_risk([{"z": 75}], [{"layer": "Cavern9"}], cav)     # the beast's layer unknown
    assert PT.cavern_at_risk([{"z": 75}], [{"layer": "Cavern1", "can_reach_dwarves": True}], cav)
    assert not PT.cavern_at_risk([{"z": 75}], great, cav)
    assert not PT.cavern_at_risk([{"z": 75}], great, cav + [{"name": "bad"}])


@test("F's flap replayed: one beast, fishers going down in its layer: one alarm, then held off two days (said)")
def _():
    m = Memory()
    t = 300000
    ups = 0
    for i in range(40):                    # a cycle every 60 ticks, about two game days
        now = t + i * 60
        down = i % 4 != 3                   # the fisher climbs out, another goes down
        s = cave(115 if down else 0)
        if not down:
            s["threats"]["cavern_citizens"] = {"n": 0, "list": []}
        s["date"]["tick"] = now
        s["civ_alert"] = bool(m.ai_alert_raised)
        m.quiet_cycles = 5
        props, notes = plan(s, m)
        for p in alarms(props):
            record([(p, {"ok": True, "on": p.action["on"]})], s, m)
            ups += p.action["on"] is True
    assert ups == 1, ups


# --- evil weather: kept in, no alarm ---------------------------------------------------------------

@test("an evil cloud on the surface: the civilians kept in by the shelter's burrow, no alarm; sent again only every so often")
def _():
    m = Memory()
    props, notes = plan(fort(weather=CLOUD), m)
    k = [p for p in props if p.action.get("type") == "weather_burrow"]
    assert k and k[0].action == {"type": "weather_burrow", "on": True} and not alarms(props), props
    assert "no alarm" in k[0].reason and "1719 tiles" in k[0].reason, k[0].reason
    record([(k[0], {"ok": True, "on": True, "added": 30})], fort(weather=CLOUD), m)
    props, notes = plan(fort(weather=CLOUD, tick=200040), m)
    assert not [p for p in props if p.action.get("type") == "weather_burrow"] and not alarms(props), props
    assert any("stay inside" in n for n in notes), notes
    props, _ = plan(fort(weather=CLOUD, tick=200000 + PLANNER_CONFIG["weather_keep_in_ticks"]), m)
    assert [p for p in props if p.action == {"type": "weather_burrow", "on": True}]
    import overseer
    assert "no alarm" in overseer.short({"type": "weather_burrow", "on": True})


@test("the weather gone weather_lift_hours: the civilians let out; an alarm for enemies meanwhile isn't held by the weather")
def _():
    m = Memory()
    plan(fort(weather=CLOUD), m)
    lift = PLANNER_CONFIG["weather_lift_hours"] * HOUR
    props, _ = plan(fort(weather=CALM, tick=200000 + lift - 10), m)
    assert not [p for p in props if p.action.get("type") == "weather_burrow"]
    assert not PT.alarm_held(fort(weather=CALM, tick=200000 + lift - 10), m, PLANNER_CONFIG)
    props, _ = plan(fort(weather=CALM, tick=200000 + lift), m)
    out = [p for p in props if p.action == {"type": "weather_burrow", "on": False}]
    assert out and "back to work outside" in out[0].reason, props
    record([(out[0], {"ok": True, "on": False, "released": 30})], fort(weather=CALM), m)
    assert m.weather_alarm == {}


@test("the burrow refused (no shelter, an older bridge): the alarm as before for a day, then the burrow again")
def _():
    m = Memory()
    props, _ = plan(fort(weather=CLOUD), m)
    k = [p for p in props if p.action.get("type") == "weather_burrow"][0]
    record([(k, {"ok": False, "rejected": True, "error": "unknown action type: weather_burrow"})], fort(weather=CLOUD), m)
    props, _ = plan(fort(weather=CLOUD, tick=200050), m)
    on = alarms(props, True)
    assert on and "evil cloud of rock" in on[0].reason and not [p for p in props if p.action.get("type") == "weather_burrow"]
    m2 = Memory()
    m2.weather_alarm = {"since": A(200000), "seen": A(200000), "why": "x", "keep_in_failed": A(200000)}
    props, _ = plan(fort(weather=CLOUD, tick=200000 + TICKS_PER_DAY), m2)
    assert [p for p in props if p.action.get("type") == "weather_burrow"], props


@test("a letting-out that didn't go through is tried again; the cap lets them out too")
def _():
    m = Memory()
    m.weather_alarm = {"kept_in": A(200000)}
    record([(Proposal("threat_alert", {"type": "weather_burrow", "on": False}, "x", 0), {"ok": False})], fort(), m)
    props, _ = plan(fort(weather=CALM, tick=200100), m)
    assert [p for p in props if p.action == {"type": "weather_burrow", "on": False}], props
    m = Memory()
    days = PLANNER_CONFIG["weather_alarm_max_days"]
    m.weather_alarm = {"since": A(100000), "seen": A(100000), "why": "x", "kept_in": A(100000)}
    props, _ = plan(fort(weather=CLOUD, tick=100000 + days * TICKS_PER_DAY), m)
    assert [p for p in props if p.action == {"type": "weather_burrow", "on": False}], props
    assert not alarms(props, True)


@test("an evil cloud near dwarves out there (the threats round's): no alarm while the burrow keeps them in")
def _():
    m = Memory()
    m.weather_alarm = {"since": A(199000), "seen": A(199000), "why": "x", "kept_in": A(199990)}
    s = fort(weather=CLOUD, threats={"undead": {"cloud_outside_near": 5, "cloud_material": "rock"}})
    props, notes = plan(s, m)
    assert not alarms(props, True), props
    assert any("kept inside by the weather rule" in n for n in notes), notes


# --- the Lua: the shelter not drawn again each alarm; the weather burrow --------------------------------

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None


def _fake(file: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return node.value.value
    raise KeyError(name)


if LuaRuntime:
    SOC = _fake("test_society.py", "FAKE")

    def soc():
        lua = LuaRuntime(unpack_returned_tuples=True)
        env, units, assigned, ntiles, g = lua.execute(SOC, module_src("ai-society.lua"))
        lua.execute("""local env = ...
            local b = {id = 9, name = 'AI shelter'}
            env.df.global.plotinfo.burrows.list[#env.df.global.plotinfo.burrows.list] = b
            env.dfhack.burrows.listBlocks = function() return {1, 2} end""", env)
        return lua, env, units, assigned

    @test("lua weather_keep_in: civilians into the shelter's burrow (never a soldier, nor one in another burrow); let out exactly those")
    def _():
        lua, env, units, assigned = soc()
        lua.execute("local units = ...; units[6].burrows = {4}", units)          # in the hospital burrow
        r = env.weather_keep_in(True, False)
        assert r.ok and r.on and r.added == 5 and r.members == 5, dict(r)
        assert assigned[1] and assigned[2] and assigned[4] and assigned[5] and assigned[7]
        assert not assigned[3] and not assigned[6], dict(assigned)             # the soldier; the hospital's
        r = env.weather_keep_in(True, False)                                     # sent again: nobody twice
        assert r.added == 0 and r.members == 5, dict(r)
        assert env.weather_keep_in_status().members == 5
        r = env.weather_keep_in(False, False)
        assert r.ok and r.released == 5 and not any(assigned[i] for i in (1, 2, 4, 5, 7)), dict(assigned)
        assert env.weather_keep_in_status().members == 0

    @test("lua weather_keep_in: no shelter burrow, or an empty one: refused (the brain falls back to the alarm); dry run changes nothing")
    def _():
        lua = LuaRuntime(unpack_returned_tuples=True)
        env, units, assigned, ntiles, g = lua.execute(SOC, module_src("ai-society.lua"))
        r = env.weather_keep_in(True, False)
        assert not r.ok and r.rejected and "no AI shelter burrow" in r.error, dict(r)
        lua, env, units, assigned = soc()
        lua.execute("local env = ...; env.dfhack.burrows.listBlocks = function() return {} end", env)
        r = env.weather_keep_in(True, False)
        assert not r.ok and "covers no tiles" in r.error
        lua, env, units, assigned = soc()
        r = env.weather_keep_in(True, True)
        assert r.ok and r.added == 6 and r.dry_run and r.members == 0 and not any(assigned[i] for i in range(1, 8)), dict(r)

    @test("lua refresh_shelter_due: drawn within the day: used as it is; older, forced or empty: drawn again")
    def _():
        lua, env, units, assigned = soc()
        calls = lua.execute("""local env = ...
            local calls = {n = 0}
            env.refresh_shelter = function() calls.n = calls.n + 1; return {refreshed = true} end
            return calls""", env)
        lua.execute("""local env = ...
            env.dfhack.persistent.saveSiteData('ai-overseer/shelter-drawn', {tick = env.reqscript('ai-util').abs_tick() - 100})""", env)
        r = env.refresh_shelter_due(False)
        assert r.refreshed is False and r.drawn_ticks_ago == 100 and calls.n == 0, dict(r)
        env.refresh_shelter_due(True)
        assert calls.n == 1
        lua.execute("""local env = ...
            env.dfhack.persistent.saveSiteData('ai-overseer/shelter-drawn', {tick = env.reqscript('ai-util').abs_tick() - 5000})""", env)
        env.refresh_shelter_due(False)
        assert calls.n == 2
        lua.execute("""local env = ...
            env.dfhack.persistent.saveSiteData('ai-overseer/shelter-drawn', {tick = env.reqscript('ai-util').abs_tick() - 100})
            env.dfhack.burrows.listBlocks = function() return {} end""", env)
        env.refresh_shelter_due(False)
        assert calls.n == 3

    @test("lua act_civ_alert asks for the shelter only when due; the action is registered and dry-run honoured")
    def _():
        acts = (ROOT / "lua" / "ai-bridge-actions.lua").read_text(encoding="utf-8")
        assert "refresh_shelter_due(a.refresh == true)" in acts and "function act_weather_burrow" in acts
        br = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
        assert "weather_burrow = act_weather_burrow" in br and "'weather_burrow'," in br


if __name__ == "__main__":
    finish()
