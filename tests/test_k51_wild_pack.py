"""(0.105.51) Threat triage holes from the R3 live run (15 Nov):

  1. a pack is no small wildlife (C, winter 251: 9 giant dingoes, large
     predators DF never calls a danger, killed 10 of 14 dwarves with no
     alarm, no gates, no shelter): planner_core.wild_pack / reachable_threats,
     no sortie short of fight_ratio (planner_military, planner_siege), the
     gate watcher and the shelter plan count the pack (lua/ai-gates-watch.lua
     wild_pack_ids, lua/ai-shelter-plan.lua dangers);
  2. the reach alarm's cap never lowers it for a great danger, a building
     destroyer or one in reach within near_threat_tiles (C 08:39: lowered
     with a Hill Titan about, gates opened, raised again 15 s later);
  3. a lone wild animal at grips with a dwarf: the wildlife squad's kill
     order is taken (lua/ai-military.lua kill_target_ok: B/C/E's giant coyote
     and chipmunk were refused), or the civilians in when no squad beats it;
     a lone wolf or falcon that attacks nobody: no lockdown.

    python tests/test_k51_wild_pack.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
from planner_core import reachable_threats, wild_pack, abs_tick  # noqa: E402
from planner_alarm import note_alarm_change, reach_alarm_over, reach_raise_held  # noqa: E402
import digest  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = dict(PLANNER_CONFIG)
DAY = 1200
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
DINGOES = json.loads((ROOT / "tests" / "fixtures" / "k51_c_dingoes.json").read_text(encoding="utf-8"))


def sq(i, power, members=7, **kw):
    q = {"id": i, "name": f"Squad {i}", "members": members, "size": 10, "orders": 0, "ai_orders": 0,
         "power": {"power": power, "armed": members, "melee_power": power, "ranged_power": 0}}
    q.update(kw)
    return q


def target(i, name="Giant Dingo", size=35000, region="surface", **kw):
    t = {"id": i, "name": name, "why": "hostile_wild", "can_reach_dwarves": True, "size": size,
         "region": region, "layer": "upper_levels" if region != "cavern" else "Cavern1",
         "great_danger": False, "fire_breather": False, "flier": False, "kinds": [], "near_workers": 0}
    t.update(kw)
    return t


def wild(i, name="Giant Coyote", size=40000, **kw):
    w = {"id": i, "name": name, "wild": True, "outside": True, "reach": True, "size": size,
         "distance": 10, "distance_outside": 10}
    w.update(kw)
    return w


def fort(targets=(), field=(), squads=(), threats=(), alert=False) -> dict:
    s = copy.deepcopy(BASE)
    s["others_on_map"]["threats"] = list(threats)
    s["others_on_map"]["threats_that_can_reach_dwarves"] = sum(1 for t in threats if t.get("can_reach_dwarves"))
    s["hunt"] = {"targets": list(targets), "squads": [], "hunts": []}
    s["field_watch"] = {"wild": list(field), "wild_total": len(field), "caravan": [], "merchants": 0,
                        "citizens_outside": 2}
    s["military"]["squads"] = list(squads)
    s["civ_alert"] = alert
    s["civ_alert_ready"] = True
    s["settings"]["attack_policy"] = "ordinary"
    s["settings"]["wildlife_hunts"] = True
    return digest.normalize(s)


def alarm_on(props):
    return [p for p in props if p.action == {"type": "civ_alert", "on": True}]


def sorties(props):
    return [p for p in props if p.action.get("type") == "squad_orders" and p.action.get("kill")]


# --- 1. the pack -------------------------------------------------------------------------------

@test("C's 9 giant dingoes (real rows: the hunt's targets, the field watch; one untrained soldier): in reach, "
      "the alarm sounds, no squad goes out")
def _():
    s = fort(DINGOES["hunt"]["targets"], DINGOES["field_watch"]["wild"], DINGOES["squads"])
    wp = wild_pack(s, CFG)
    assert wp["danger"] and not wp["fight"] and len(wp["ids"]) == 9, wp
    assert sorted(reachable_threats(s, {}, CFG)) == sorted(wp["ids"])
    props, notes = plan(s, Memory())
    assert alarm_on(props), [(p.rule, p.reason) for p in props if "alert" in p.rule]
    assert not sorties(props), [(p.rule, p.action) for p in sorties(props)]
    assert any("pack of 9" in n for n in notes), [n for n in notes if "ingo" in n]


@test("three giant dingoes and squads that beat them: still the alarm (3+), and the squads go")
def _():
    s = fort([target(1), target(2), target(3)], [wild(1, "Giant Dingo", 35000), wild(2, "Giant Dingo", 35000)],
             [sq(10, 200.0), sq(11, 150.0)])
    wp = wild_pack(s, CFG)
    assert wp["danger"] and wp["fight"], wp
    props, _ = plan(s, Memory())
    assert alarm_on(props)
    # the alarm isn't up yet this cycle (raised by this plan): the next cycle, with it up, a squad goes
    s2 = fort([target(1), target(2), target(3)], [wild(1, "Giant Dingo", 35000), wild(2, "Giant Dingo", 35000)],
              [sq(10, 200.0), sq(11, 150.0)], alert=True)
    props2, _ = plan(s2, Memory(ai_alert_raised=True))
    assert sorties(props2), [(p.rule, p.reason) for p in props2 if "squad" in p.rule or "wild" in p.rule]


@test("two wild animals: stronger than the free squads, the alarm (no sortie); beaten by them, the hunt only")
def _():
    two = [target(1, "Giant Coyote", 40000), target(2, "Giant Coyote", 40000)]
    field = [wild(1), wild(2)]
    weak = fort(two, field, [sq(10, 4.9)])
    assert wild_pack(weak, CFG)["danger"] and reachable_threats(weak, {}, CFG) == [1, 2]
    props, _ = plan(weak, Memory())
    assert alarm_on(props) and not sorties(props)
    strong = fort(two, field, [sq(10, 200.0)])
    assert not wild_pack(strong, CFG)["danger"] and reachable_threats(strong, {}, CFG) == []
    props, _ = plan(strong, Memory())
    assert not alarm_on(props) and [p for p in props if p.rule == "wild_hunt"]


@test("one inside the fort: the alarm; a pack in the caverns or small animals (falcons) count for nothing here")
def _():
    s = fort([target(1, "Giant Coyote", 40000, region="inside")], squads=[sq(10, 200.0)])
    assert wild_pack(s, CFG)["danger"] and reachable_threats(s, {}, CFG) == [1]
    cav = fort([target(i, region="cavern") for i in (1, 2, 3, 4)])
    assert not wild_pack(cav, CFG)["danger"] and reachable_threats(cav, {}, CFG) == []
    birds = fort([target(i, "Peregrine Falcon", 129, flier=True) for i in (1, 2, 3, 4)])
    assert not wild_pack(birds, CFG)["danger"] and reachable_threats(birds, {}, CFG) == []
    # three on the map, one of them out of reach: two the squads beat, no pack
    far = fort([target(1), target(2), target(3, can_reach_dwarves=False)], squads=[sq(10, 200.0)])
    assert not wild_pack(far, CFG)["danger"] and reachable_threats(far, {}, CFG) == []


@test("an agitated pack in the threats rows (DF's danger): kept in reach, not dropped as wildlife")
def _():
    rows = [{"id": i, "name": "wolf", "animal": True, "agitated": True, "invader": False, "great_danger": False,
             "flier": False, "size": 50000, "can_reach_dwarves": True, "layer": "upper_levels",
             "distance_to_nearest_dwarf": 30, "levels_from_nearest_dwarf": 0,
             "pos": {"x": 50, "y": 50, "z": 170}} for i in (71, 72, 73)]
    s = fort(threats=rows)
    assert reachable_threats(s, {}, CFG) == [71, 72, 73]
    assert reachable_threats(fort(threats=rows[:1]), {}, CFG) == []         # a lone wolf: no lockdown


# --- 3. a lone animal ---------------------------------------------------------------------------

@test("a lone giant coyote at grips with a dwarf: no squad that beats it, the alarm (civilians in, no sortie); "
      "a squad that does, the hunt; a lone wolf or falcon attacking nobody: neither alarm nor gates")
def _():
    s = fort(field=[wild(5, attacking=True)], squads=[sq(10, 4.9)])
    assert wild_pack(s, CFG)["danger"] and reachable_threats(s, {}, CFG) == [5]
    props, _ = plan(s, Memory())
    assert alarm_on(props) and not sorties(props)
    none = fort(field=[wild(5, attacking=True)], squads=[])
    assert alarm_on(plan(none, Memory())[0])
    strong = fort(field=[wild(5, attacking=True)], squads=[sq(10, 200.0)])
    props, _ = plan(strong, Memory())
    assert not alarm_on(props) and [p for p in props if p.rule == "wild_hunt"]
    wolf = fort([target(6, "Wolf", 50000)], [wild(6, "Wolf", 50000)], squads=[])
    props, _ = plan(wolf, Memory())
    assert not alarm_on(props) and not [p for p in props if p.action.get("type") == "arm_gates"]
    falcon = fort(field=[wild(7, "Peregrine Falcon", 129, flier=True, attacking=True)], squads=[])
    assert not alarm_on(plan(falcon, Memory())[0])


# --- 2. the reach alarm's cap -------------------------------------------------------------------

def enemy(i=6001, **kw):
    t = {"id": i, "name": "a goblin lasher", "great_danger": False, "kinds": [], "size": 60000, "invader": True,
         "can_reach_dwarves": True, "layer": "upper_levels", "distance_to_nearest_dwarf": 150,
         "levels_from_nearest_dwarf": 0, "pos": {"x": 10, "y": 10, "z": 170}}
    t.update(kw)
    return t


def capped(s):
    m = Memory(ai_alert_raised=True)
    note_alarm_change(m, abs_tick(s) - 29 * DAY, True, "1 threat(s) can reach the dwarves")
    return reach_alarm_over(s, m, CFG, reachable_threats(s, {}, CFG))


@test("reach cap: never lowered for a titan (C 08:39), a building destroyer, or one in reach within "
      "near_threat_tiles; an ordinary one far off: lowered as before")
def _():
    assert capped(fort(threats=[enemy()], alert=True))
    titan = enemy(name="Hill Titan", great_danger=True, kinds=["Titan"], size=9000000, invader=False,
                  distance_to_nearest_dwarf=180)
    assert not capped(fort(threats=[titan], alert=True))
    # a titan on the map held off (not in reach) and a goblin in reach far off: not lowered either
    assert not capped(fort(threats=[enemy(), dict(titan, id=6002, can_reach_dwarves=False)], alert=True))
    assert not capped(fort(threats=[enemy(destroyer=True)], alert=True))
    assert not capped(fort(threats=[enemy(distance_to_nearest_dwarf=28)], alert=True))
    s = fort(threats=[titan], alert=True)
    props, _ = plan(s, Memory(ai_alert_raised=True, alarm_gov={"on": {"tick": abs_tick(s) - 29 * DAY,
                                                                       "cause": "reach", "key": "reach"}}))
    assert not [p for p in props if p.action == {"type": "civ_alert", "on": False}]


@test("reach cap: after a cap, a titan's alarm is raised again (never held), and the pack's own rows "
      "(not in the threats rows) near a dwarf keep the alarm up")
def _():
    titan = enemy(name="Hill Titan", great_danger=True, kinds=["Titan"], size=9000000, invader=False)
    s = fort(threats=[titan])
    m = Memory()
    t0 = abs_tick(s)
    m.atlas = {"lockdown": {"new": t0 - 4 * DAY, "seen": [6001]}}
    note_alarm_change(m, t0 - DAY, False, "the alarm has been up 3 days and none of ...")
    assert not reach_raise_held(s, m, CFG, [6001])
    assert reach_raise_held(fort(threats=[enemy()]), m, CFG, [6001])
    pack = fort([target(i, near_workers=2 if i == 1 else 0) for i in (1, 2, 3)], alert=True)
    assert not capped(pack)
    far = fort([target(i) for i in (1, 2, 3)], alert=True)
    assert capped(far)


# --- the bridge (Lua) ---------------------------------------------------------------------------

def lua_test(name):
    def wrap(fn):
        def run():
            if LuaRuntime is None:
                skip("needs the lupa package (pip install lupa)")
            fn()
        return test(name)(run)
    return wrap


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


GATES_ENV = r"""local src = ...
local env = setmetatable({}, {__index = _G})
local units = {}
local function f(k) return function(u) return u[k] == true end end
env.df = {global = {world = {units = {active = units}}}}
env.FLAGS = {}
env.dfhack = {units = {isAlive = function(u) return u.dead ~= true end, isCitizen = f('citizen'),
    isHidden = f('hidden'), isDanger = f('danger'), isInvader = f('invader'),
    isGreatDanger = f('great'), isAnimal = f('animal'), isNightCreature = f('night'),
    isUndead = f('undead'), isFortControlled = f('fort'), isTame = f('tame')},
    maps = {getTileFlags = function(x, y, z) return env.FLAGS[z] or {outside = true} end}}
env.reqscript = function(n)
    if n == 'ai-builder' then return {hostile_wild = function(u) return u.predator == true end} end
    return setmetatable({}, {__index = function() return function() end end})
end
env.dfhack.timeout = function() end
local chunk = assert(load(src, 'ai-gates-watch', 't', env))
pcall(chunk)
env._units = units
return env"""


def gates_env(rows):
    lua = LuaRuntime(unpack_returned_tuples=True)
    M = lua.execute(GATES_ENV, module_src("ai-gates-watch.lua"))
    for r in rows:
        d = {"animal": True, "flags1": {}, "pos": {"x": 1, "y": 1, "z": r.pop("z", 100)},
             "body": {"size_info": {"size_cur": r.pop("size", 35000)}}}
        d.update(r)
        M._units[len(M._units) + 1] = T(lua, d)
    return lua, M


def ids_of(t):
    return sorted(k for k in t.keys() if t[k])


@lua_test("gate watcher: 3 giant dingoes (large predators, no DF danger) are a pack and visible dangers; 2 are not; "
          "a cavern's, the fort's own, small or tame ones don't count")
def _():
    lua, M = gates_env([{"id": i, "predator": True} for i in (1, 2, 3)])
    assert ids_of(M.wild_pack_ids()) == [1, 2, 3]
    assert len(M.visible_dangers()) == 3
    lua, M = gates_env([{"id": 1, "predator": True}, {"id": 2, "predator": True},
                        {"id": 3, "predator": True, "z": 40}, {"id": 4, "predator": True, "fort": True},
                        {"id": 5, "danger": True, "size": 129}, {"id": 6, "predator": True, "tame": True},
                        {"id": 7, "size": 35000}])
    lua.execute("local M = ...; M.FLAGS[40] = {feature_local = true}", M)
    assert ids_of(M.wild_pack_ids()) == []
    assert len(M.visible_dangers()) == 0
    # an agitated one (DF's danger) with two large predators: a pack
    lua, M = gates_env([{"id": 1, "predator": True}, {"id": 2, "predator": True}, {"id": 3, "danger": True}])
    assert ids_of(M.wild_pack_ids()) == [1, 2, 3]


@lua_test("kill_target_ok: a wild animal whose last opponent is a citizen (a giant coyote) is taken; one "
          "whose opponent isn't, a tame one, or one with no opponent: refused")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    M = lua.execute(r"""
        local src = ...
        local env = setmetatable({}, {__index = _G})
        env.UNITS = {}
        env.reqscript = function(name)
            if name == 'ai-builder' then return {hostile_wild = function() return false end} end
            if name == 'ai-threats' then return {interrupting = function() return false end} end
            error('no ' .. name)
        end
        assert(load(src, 'ai-military', 't', env))()
        env.df = {mood_type = {Berserk = 7}, unit = {find = function(id) return env.UNITS[id] end}}
        local function has(k) return function(u) return u[k] == true end end
        env.dfhack = {units = {isMerchant = has('merchant'), isDiplomat = has('diplomat'), isTame = has('tame'),
            isCitizen = has('citizen'), isDanger = has('danger'), isInvader = has('invader'),
            isAnimal = has('animal'), isFortControlled = has('fort')}}
        env.UNITS[100] = {id = 100, citizen = true}
        env.UNITS[200] = {id = 200}
        return env
        """, module_src("ai-military.lua"))
    t = lambda **kw: T(lua, kw)
    ok = M.kill_target_ok
    assert ok(t(id=5, animal=True, opponent={"unit_id": 100}))
    assert not ok(t(id=6, animal=True, opponent={"unit_id": 200}))
    assert not ok(t(id=7, animal=True, opponent={"unit_id": -1}))
    assert not ok(t(id=8, animal=True, tame=True, opponent={"unit_id": 100}))
    assert not ok(t(id=9, animal=True, fort=True, opponent={"unit_id": 100}))
    assert not ok(t(id=10, opponent={"unit_id": 100}))                     # not an animal


@lua_test("field watch: a large predator at grips with a citizen says `attacking` too")
def _():
    src = (ROOT / "lua" / "ai-siege.lua").read_text(encoding="utf-8")
    assert "local attacking = not danger and outside and wild_attacking(u, cit_ids)" in src
    assert "not danger and not wild and outside and wild_attacking" not in src


@lua_test("shelter plan: the wild pack (ai-gates wild_pack_ids) is a danger (C's plan said danger = false)")
def _():
    import ast
    tree = ast.parse((ROOT / "tests" / "test_h5_shelter_plan.py").read_text(encoding="utf-8"))
    fake_src = next(n.value.value for n in tree.body if isinstance(n, ast.Assign)
                    and any(getattr(t, "id", None) == "FAKE" for t in n.targets))
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(fake_src, module_src("ai-shelter-plan.lua"))
    lua.execute("""local env, W = ...
        W.block(100, {'', ' o............>'})
        local hall = {'', ' .............X'}
        for i = 1, 6 do table.insert(hall, ' ..............') end
        W.block(99, hall)""", env, w)
    cit = T(lua, {"citizen": True, "pos": {"x": 3, "y": 3, "z": 99}, "military": {"squad_id": -1},
                  "flags1": {"caged": False, "chained": False}})
    w.units[len(w.units) + 1] = cit
    w.cits[len(w.cits) + 1] = cit
    dingo = T(lua, {"id": 901, "name": "Giant Dingo", "pos": {"x": 5, "y": 1, "z": 100},
                    "flags1": {"caged": False, "chained": False}})
    w.units[len(w.units) + 1] = dingo
    r = env.report()
    assert r.danger is False, r.danger
    lua.execute("""local env = ...
        local old = env.reqscript
        env.reqscript = function(n)
            local m = old(n)
            if n == 'ai-gates' then m.wild_pack_ids = function() return {[901] = true} end end
            return m
        end""", env)
    r = env.report()
    assert r.danger is True, r.danger


finish()
