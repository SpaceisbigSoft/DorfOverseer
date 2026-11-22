"""(0.105.51, builder 22) Intruders, thieves and the tavern massacres (R3 live
run, 15 Nov):

  1. a lone sneaker DF reports (invasion civ_id -1, invaders_now 1: an
     artifact seeker) raises no alarm; the intruder guard still posts a
     squad on the stair (B 4, C 5, F 1 alarms);
  2. E: a sneaker spotted on a pulse cycle (no threats section: the
     day-old thieves list) got "1 threat(s) can reach" -> alarm, gates and
     the defence's squad; the bridge now marks `thief` on the others_on_map
     row and the triage reads it; a night creature held off on the upper
     levels (no invader) no longer keeps a lone thief off the triage;
  3. E: (a) a theft shuts the taverns, temple and library to visitors too,
     even the ones found "yours" before the theft; (b) a thief among a crowd
     (a tavern of guests) gets no squad_attack: a squad waits at the named
     artifact / main stair, and attacks once the thief leaves the crowd.

    python tests/test_k48_thieves_crowd.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402
from lua_modules_util import module_src, bridge_part_src, split_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan, record  # noqa: E402
from planner_core import abs_tick, reachable_threats, thief_ids, thief_rows, crowded_thief, TICKS_PER_DAY  # noqa: E402
from planner_threats import lone_sneaker  # noqa: E402
from planner_visitors import _location_access_rule, note_locations  # noqa: E402

CFG = dict(PLANNER_CONFIG)
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
ON = {"type": "civ_alert", "on": True}


def fort(threats=(), squads=None, **kw) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["threats"] = {"thieves": {"list": [], "now": 0}}        # the day-old full report's list
    s["civ_alert"] = False
    s["civ_alert_ready"] = True
    s["others_on_map"] = dict(s.get("others_on_map") or {}, threats=list(threats),
                              threats_that_can_reach_dwarves=sum(1 for t in threats if t.get("can_reach_dwarves")))
    if squads is not None:
        s["military"]["squads"] = squads
    s.update(kw)
    return s


def sq(i, members=6, **kw):
    q = {"id": i, "name": f"Squad {i}", "members": members, "size": 10, "orders": 0, "ai_orders": 0,
         "power": {"power": 5000, "armed": members}}
    q.update(kw)
    return q


def alarms(props):
    return [p for p in props if p.action == ON]


def attacks(props, uid):
    return [p for p in props if p.rule == "squad_attack" and uid in (p.action.get("kill") or [])]


# E's row (journal 08:13:58, 21 Slate 255): Om Konlihiñer, the spearman who killed the mechanic
OM = {"id": 13479, "name": "Om Konlihiñer \"Oilbaked\", Human Spearman", "can_reach_dwarves": True,
      "great_danger": False, "invader": True, "animal": None, "layer": "upper_levels", "size": 70000,
      "pos": {"x": 164, "y": 168, "z": 162}, "distance_to_nearest_dwarf": 1, "levels_from_nearest_dwarf": 0}


# ---- 1. the lone sneaker DF reports ---------------------------------------------------

@test("1 lone_sneaker: civ -1 and one invader (R3's 17 records) is; a siege's record (a civ, many) isn't")
def _():
    assert lone_sneaker({"tick": 1, "civ": -1, "invaders": 1})
    assert lone_sneaker({"tick": 1, "civ": -1, "invaders": 0})
    assert lone_sneaker({"tick": 1, "civ": None, "invaders": None})
    assert not lone_sneaker({"tick": 1, "civ": 412, "invaders": 1})
    assert not lone_sneaker({"tick": 1, "civ": -1, "invaders": 4})
    assert not lone_sneaker(None)


@test("1 B/C/F: DF reports one hero of no civ, nobody seen: no alarm, a note; the stair guard still posted")
def _():
    s = fort(squads=[sq(11, members=10), sq(12, members=10)])
    s["entrances"]["entrances"] = [{"id": 1, "kind": "surface", "x": 31, "y": 140, "z": 173, "width": 1,
                                    "sealed": True, "closed": False, "lid": True,
                                    "equipment": [{"id": 501, "kind": "door"}]}]
    m = Memory()
    m.intrusion = {"tick": abs_tick(s) - 10, "civ": -1, "invaders": 1}
    props, notes = plan(s, m)
    assert not alarms(props), [p.reason for p in alarms(props)]
    assert any("lone intruder" in n and "no alarm" in n for n in notes), notes
    assert [p for p in props if p.rule == "intruder_guard" and p.action.get("type") == "squad_station"], \
        [(p.rule, p.action) for p in props][:20]
    # a siege's record (a civ, many invaders): the alarm as before
    m2 = Memory()
    m2.intrusion = {"tick": abs_tick(s) - 10, "civ": 412, "invaders": 30}
    a = alarms(plan(s, m2)[0])
    assert a and a[0].reason.startswith("DF reports 30 intruders"), a


@test("1 an AI alarm up while only a lone sneaker's record is about isn't held for it")
def _():
    s = fort()
    s["civ_alert"] = True
    m = Memory(ai_alert_raised=True)
    m.intrusion = {"tick": abs_tick(s) - 10, "civ": -1, "invaders": 1}
    _, notes = plan(s, m)
    assert not any("the alarm stays up: DF reported an intruder" in n for n in notes), notes


# ---- 2. the seen sneaker on a pulse cycle --------------------------------------------------

@test("2 E 21 Slate 255: a thief marked on the others_on_map row (the pulse) is triaged: no alarm, no defence")
def _():
    row = dict(OM, thief="thief", crowd=0)
    s = fort([row], squads=[sq(181)])
    s["threats"] = {"thieves": {"list": [], "now": 0}}        # the day-old full report's list
    assert 13479 in thief_ids(s)
    assert reachable_threats(s, {}, CFG) == []
    props, notes = plan(s, Memory())
    assert not alarms(props), [p.reason for p in alarms(props)]
    assert not [p for p in props if p.action.get("type") == "arm_gates"]
    k = attacks(props, 13479)
    assert len(k) == 1 and "(thief) in the fort" in k[0].reason, [(p.rule, p.reason) for p in k]


@test("2 the unfixed case: no `thief` mark (an older bridge) and no list: the defence as before")
def _():
    s = fort([dict(OM)], squads=[sq(181)])
    assert reachable_threats(s, {}, CFG) == [13479]


@test("2 a night creature walking the upper levels (no invader, reach unknown) keeps no lone thief off the triage")
def _():
    poet = {"id": 777, "name": "èrith Rîsenåm, Olon's Eye Poet", "can_reach_dwarves": None, "invader": False,
            "great_danger": False, "kinds": ["NightCreature"], "layer": "upper_levels", "size": 70000,
            "distance_to_nearest_dwarf": 30, "levels_from_nearest_dwarf": 0}
    s = fort([dict(OM, thief="thief"), poet])
    assert reachable_threats(s, {}, CFG) == [], reachable_threats(s, {}, CFG)
    # a siege held off at the gates still keeps the thief in the defence
    gob = {"id": 900, "name": "goblin", "can_reach_dwarves": False, "invader": True, "great_danger": False,
           "layer": "surface", "size": 60000, "distance_to_nearest_dwarf": 40, "levels_from_nearest_dwarf": 3}
    assert reachable_threats(fort([dict(OM, thief="thief"), gob]), {}, CFG) == [13479]


# ---- 3b. a thief in a crowd --------------------------------------------------------------

@test("3b crowded_thief: 3+ people round them, or any in a tavern/temple/library/guildhall; no field: never")
def _():
    assert crowded_thief({"crowd": 5})
    assert crowded_thief({"crowd": 1, "location": "INN_TAVERN"})
    assert not crowded_thief({"crowd": 0, "location": "INN_TAVERN"})
    assert not crowded_thief({"crowd": 2})
    assert not crowded_thief({"id": 1})


def _arts(s):
    s["artifacts"] = {"artifacts": [{"id": 3, "item_id": 77, "name": "The Profane Blister Escort",
                                     "x": 100, "y": 168, "z": 159, "state": "displayed"}]}
    return s


@test("3b E Moonstone 24 y252: a thief among the tavern's guests: no squad_attack; a squad waits at the artifact")
def _():
    row = dict(OM, thief="thief", crowd=9, location="INN_TAVERN")
    s = _arts(fort([row], squads=[sq(181)]))
    m = Memory()
    m.holdfast = {"named": {"tick": abs_tick(s) - 5, "name": "The Profane Blister Escort"}}
    props, notes = plan(s, m)
    assert not attacks(props, 13479), [(p.rule, p.reason) for p in attacks(props, 13479)]
    w = [p for p in props if p.rule == "thief_watch"]
    assert w and w[0].action == {"type": "squad_station", "squad_id": 181, "x": 100, "y": 168, "z": 159,
                                 "what": "artifact The Profane Blister Escort the thief named"}, [p.action for p in w]
    assert "9 people round them in the tavern" in w[0].reason, w[0].reason
    # the same thief in the threats section's list (a full report): the same answer
    s2 = _arts(fort([], squads=[sq(181)]))
    s2["threats"] = {"thieves": {"list": [{"id": 14129, "name": "Asi Ezifpak, Human Crossbowman", "kind": "thief",
                                           "inside": True, "can_reach_dwarves": True, "crowd": 6,
                                           "location": "INN_TAVERN"}]}}
    props, _ = plan(s2, m)
    assert not attacks(props, 14129) and [p for p in props if p.rule == "thief_watch"]


@test("3b the watcher stays (no 'no more threats' recall) and goes at the thief once out of the crowd")
def _():
    watcher = sq(181, ai_orders=1, orders=1, stationed={"x": 100, "y": 168, "z": 159})
    m = Memory()
    m.holdfast = {"named": {"tick": 1, "name": "The Profane Blister Escort"}}
    s = _arts(fort([dict(OM, thief="thief", crowd=9, location="INN_TAVERN")], squads=[watcher]))
    props, notes = plan(s, m)
    assert not [p for p in props if p.rule == "squad_recall" and p.action.get("squad_id") == 181], \
        [p.reason for p in props if p.rule == "squad_recall"]
    assert any("waits for them" in n for n in notes), notes
    # out of the crowd: the watcher goes at him
    s = _arts(fort([dict(OM, thief="thief", crowd=0)], squads=[watcher]))
    k = attacks(plan(s, m)[0], 13479)
    assert k and k[0].action["squad_id"] == 181, k
    # the thief gone: the watcher comes back
    s = _arts(fort([], squads=[watcher]))
    s["threats"] = {"thieves": {"list": []}}
    assert [p for p in plan(s, m)[0] if p.rule == "squad_recall" and p.action.get("squad_id") == 181]


@test("3b a crowded thief among several enemies (the defence's targets) is left out of the defence's order")
def _():
    gob = {"id": 900, "name": "goblin", "can_reach_dwarves": True, "invader": True, "great_danger": False,
           "layer": "surface", "size": 60000, "distance_to_nearest_dwarf": 5, "levels_from_nearest_dwarf": 0}
    s = fort([dict(OM, thief="thief", crowd=9, location="INN_TAVERN"), gob, dict(gob, id=901), dict(gob, id=902)],
             squads=[sq(181), sq(182)])
    props, _ = plan(s, Memory())
    assert not attacks(props, 13479), [(p.rule, p.action) for p in attacks(props, 13479)]
    assert attacks(props, 900)


@test("3b thief_rows: the pulse's row adds a thief the list lacks and freshens one it has")
def _():
    s = fort([dict(OM, thief="thief", crowd=4, location="TEMPLE")])
    s["threats"] = {"thieves": {"list": [{"id": 13479, "name": "Om", "kind": "thief", "inside": True, "crowd": 0}]}}
    r = thief_rows(s)
    assert len(r) == 1 and r[0]["crowd"] == 4 and r[0]["location"] == "TEMPLE" and r[0]["inside"], r


# ---- 3a. the locations after a theft --------------------------------------------------------

def town(now_heist=True):
    s = fort()
    s["locations"] = {"built": abs_tick(s), "list": [
        {"id": 0, "type": "TEMPLE", "flags": ["VISITORS_ALLOWED", "NON_CITIZENS_ALLOWED"]},
        {"id": 1, "type": "INN_TAVERN", "flags": ["VISITORS_ALLOWED", "NON_CITIZENS_ALLOWED"]},
        {"id": 2, "type": "LIBRARY", "flags": ["VISITORS_ALLOWED", "NON_CITIZENS_ALLOWED"]},
        {"id": 3, "type": "INN_TAVERN", "flags": ["VISITORS_ALLOWED", "NON_CITIZENS_ALLOWED"]},
        {"id": 4, "type": "HOSPITAL", "flags": ["VISITORS_ALLOWED", "NON_CITIZENS_ALLOWED"]},
        {"id": 5, "type": "GUILDHALL", "flags": ["VISITORS_ALLOWED"]}]}
    return s


def shut(s, m):
    props, notes = [], []
    _location_access_rule(s, m, CFG, props, notes)
    return [p for p in props if p.action.get("visitors") is False]


@test("3a E: taverns, temple and library 'yours' from y251 (no time kept): a theft shuts them with the guildhall")
def _():
    s = town()
    m = Memory(locations_yours=[0, 1, 2, 3])
    m.heists = [[abs_tick(s) - 50, "Om Konlihiñer"]]
    p = shut(s, m)
    assert p and p[0].action["ids"] == [0, 1, 2, 3, 5], [x.action for x in p]
    # recorded: the AI's again (no longer yours)
    record([(p[0], {"ok": True, "changed": [0, 1, 2, 3, 5], "visitors": False})], s, m)
    assert m.locations_closed == [0, 1, 2, 3, 5] and m.locations_yours == [], (m.locations_closed, m.locations_yours)


@test("3a one you opened after the theft stays open; a stranger's wary days leave yours alone as before")
def _():
    s = town()
    m = Memory(locations_yours=[1], locations_yours_at={"1": abs_tick(s) - 10})
    m.heists = [[abs_tick(s) - 50, "Om"]]
    p = shut(s, m)
    assert p and 1 not in p[0].action["ids"] and 3 in p[0].action["ids"], [x.action for x in p]
    # no theft, a stranger seeking a meeting: yours (no time) stays open
    m2 = Memory(locations_yours=[1])
    m2.stranger_shut = {"seen": abs_tick(s) - 10, "who": "a goblin poet"}
    p = shut(s, m2)
    assert p and 1 not in p[0].action["ids"], [x.action for x in p]


@test("3a note_locations keeps when a place became yours")
def _():
    s = town()
    m = Memory(locations_closed=[1], locations_acted={"1": abs_tick(s) - 5000})
    note_locations(s, m, CFG)
    assert m.locations_yours == [1] and m.locations_yours_at == {"1": abs_tick(s)}, (m.locations_yours,
                                                                                     m.locations_yours_at)


# ---- the bridge -----------------------------------------------------------------------------

@test("lua: unit_thief_kind and crowd_of over a fake game (the people within 5 tiles, the tavern's type)")
def _():
    try:
        from lupa.lua53 import LuaRuntime
    except ImportError:
        skip("no lupa")
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(r"""
local src = ...
local e = setmetatable({}, {__index = _G})
e.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
e.df = {profession = {[1] = 'SPEARMAN', [2] = 'THIEF', [3] = 'BARD'},
        unit_path_goal = {[7] = 'ThiefTarget', [8] = 'None'},
        abstract_building_type = {[0] = 'INN_TAVERN'}, global = {world = {units = {active = {}}}}}
local function has(k) return function(u) return u[k] == true end end
e.dfhack = {units = {isActive = function() return true end, isDead = function() return false end,
                     isAnimal = has('animal'), isDanger = has('danger'), isHidden = function() return false end},
            persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end},
            world = {getCurrentSite = function()
                return {buildings = {{id = 42, getType = function() return 0 end}}} end},
            buildings = {findCivzonesAt = function(p)
                if p.x >= 10 and p.x <= 20 then return {{id = 9, location_id = 42}} end
                return {} end}}
e.reqscript = function(name) error('no ' .. name) end
assert(load(src, 'ai-threats', 't', e))()
return e
""", module_src("ai-threats.lua"))
    T = lua.table_from
    hero = T({"id": 1, "profession": 1, "path": T({"goal": 7}), "pos": T({"x": 12, "y": 12, "z": 100}), "danger": True})
    assert env.unit_thief_kind(hero) == "thief"
    assert env.unit_thief_kind(T({"id": 5, "profession": 3, "path": T({"goal": 8})})) is None
    units = T([hero] + [T({"id": 10 + i, "pos": T({"x": 12 + i, "y": 12, "z": 100})}) for i in range(4)]
              + [T({"id": 20, "pos": T({"x": 30, "y": 12, "z": 100})}),            # far
                 T({"id": 21, "pos": T({"x": 12, "y": 12, "z": 99})}),             # another level
                 T({"id": 22, "pos": T({"x": 13, "y": 12, "z": 100}), "animal": True}),
                 T({"id": 23, "pos": T({"x": 13, "y": 12, "z": 100}), "danger": True})])
    n, loc = env.crowd_of(hero, units)
    assert (n, loc) == (4, "INN_TAVERN"), (n, loc)
    out = T({"id": 2, "pos": T({"x": 50, "y": 50, "z": 100})})
    n, loc = env.crowd_of(out, units)
    assert (n, loc) == (0, None), (n, loc)


@test("lua: the others_on_map rows carry the thief mark and the crowd (the pulse); the thieves list its crowd")
def _():
    src = bridge_part_src("ai-bridge-report")
    assert "TH.unit_thief_kind(u)" in src and "TH.crowd_of(u, report_units())" in src
    th = split_src("ai-threats.lua")   # (r8) ai-threats is a hub and parts: their texts together
    assert "row.crowd, row.location = crowd_of(u, report_units())" in th


if __name__ == "__main__":
    finish()
