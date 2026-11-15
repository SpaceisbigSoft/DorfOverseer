"""(0.105.48, K1 part a) Threat triage (audit A6 findings 3, 4, 9, 10, 11):
wildlife and a lone thief never sound the fort-wide alarm or arm the gates
(planner_core.reachable_threats), a hunting squad at most (planner_siege's
wildlife rule: walkers in reach, a flier only by crossbows); an ambush or a
siege judged by the matchup (the smallest party over fight_ratio, no sortie
short of it: planner_holdfast); the "can reach" alarm's maximum time
(planner_alarm); the power scale below a dwarf's size
(planner_military.threat_power); agitated animals in the field watch
(lua/ai-siege.lua) and out of the gate watcher (lua/ai-gates-watch.lua).
The werebeast test (lua/ai-killers.lua) is in tests/test_item3_killers.py.

    python tests/test_k48_threat_triage.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan, note_cycle  # noqa: E402
from planner_core import reachable_threats, held_off_threats, wildlife_threat  # noqa: E402
from planner_military import threat_power  # noqa: E402
from planner_alarm import note_alarm_change, reach_alarm_over, reach_raise_held  # noqa: E402
import digest  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = dict(PLANNER_CONFIG)
DAY = 1200
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def falcon(i=7001, **kw):
    t = {"id": i, "name": "peregrine falcon", "animal": True, "agitated": True, "invader": False,
         "great_danger": False, "flier": True, "size": 129, "layer": "upper_levels",
         "distance_to_nearest_dwarf": 10, "levels_from_nearest_dwarf": 0, "pos": {"x": 50, "y": 50, "z": 170}}
    t.update(kw)
    return t


def wolf(i=7002, **kw):
    t = {"id": i, "name": "wolf", "animal": True, "agitated": True, "invader": False, "great_danger": False,
         "flier": False, "size": 50000, "can_reach_dwarves": True, "layer": "Cavern1",
         "distance_to_nearest_dwarf": 12, "levels_from_nearest_dwarf": 0, "pos": {"x": 50, "y": 50, "z": 120}}
    t.update(kw)
    return t


def goblin(i=8000, **kw):
    t = {"id": i, "name": "goblin", "invader": True, "great_danger": False, "flier": False, "size": 60000,
         "can_reach_dwarves": True, "layer": "upper_levels", "distance_to_nearest_dwarf": 40,
         "levels_from_nearest_dwarf": 0, "pos": {"x": 60, "y": 60, "z": 170}}
    t.update(kw)
    return t


def sq(i, power, members=7, **kw):
    q = {"id": i, "name": f"Squad {i}", "members": members, "size": 10, "orders": 0, "ai_orders": 0,
         "power": {"power": power, "armed": members, "melee_power": power, "ranged_power": 0}}
    q.update(kw)
    return q


def fort(threats, squads=None, alert=False, **extra) -> dict:
    s = copy.deepcopy(BASE)
    s["others_on_map"]["threats"] = threats
    s["others_on_map"]["threats_that_can_reach_dwarves"] = sum(1 for t in threats if t.get("can_reach_dwarves") is True)
    if squads is not None:
        s["military"]["squads"] = squads
    s["civ_alert"] = alert
    s["civ_alert_ready"] = True
    s["settings"]["attack_policy"] = "ordinary"
    s.update(extra)
    return digest.normalize(s)


def by(props, rule=None, typ=None):
    return [p for p in props if (rule is None or p.rule == rule) and (typ is None or p.action.get("type") == typ)]


def alarm_on(props):
    return [p for p in props if p.action == {"type": "civ_alert", "on": True}]


# --- the triage: who sounds the alarm ---------------------------------------------------

@test("triage: a falcon, an agitated wolf are wildlife (not in reach, not held off); goblins, an elephant, an "
      "invader's war animal and an older bridge's row still are; the count of unlisted ones is kept")
def _():
    s = fort([falcon(can_reach_dwarves=None), wolf(), goblin()])
    assert reachable_threats(s, {}, CFG) == [8000], reachable_threats(s, {}, CFG)
    assert wildlife_threat(falcon(), CFG) and wildlife_threat(wolf(), CFG)
    assert not held_off_threats(fort([falcon(can_reach_dwarves=False)]))
    big = wolf(size=5000000, name="elephant")
    war = wolf(invader=True, name="war wolf")
    old = {k: v for k, v in wolf().items() if k not in ("animal", "agitated")}
    beast = wolf(kinds=["NightCreature"])
    for t in (big, war, old, beast):
        assert reachable_threats(fort([t]), {}, CFG) == [t["id"]], t
    s = fort([wolf()])
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 3         # two more counted, not listed
    assert reachable_threats(s, {}, CFG) == ["unlisted0", "unlisted1"], reachable_threats(s, {}, CFG)


@test("triage: a lone thief (the threats section's thieves) is out of reach; two thieves too; with a goblin, "
      "three thieves, a flier among them or a siege held off: as before")
def _():
    def with_thieves(rows, n_thieves, extra=()):
        s = fort(rows + list(extra))
        s["threats"] = {"thieves": {"list": [{"id": r["id"], "kind": "thief", "inside": True}
                                              for r in rows[:n_thieves]]}}
        return s
    k1, k2, k3 = goblin(9001, name="kobold thief", invader=False, size=20000), goblin(9002), goblin(9003)
    assert reachable_threats(with_thieves([k1], 1), {}, CFG) == []
    assert reachable_threats(with_thieves([k1, k2], 2), {}, CFG) == []
    assert reachable_threats(with_thieves([k1, k2], 1), {}, CFG) == [9001, 9002]
    assert len(reachable_threats(with_thieves([k1, k2, k3], 3), {}, CFG)) == 3
    assert reachable_threats(with_thieves([dict(k1, flier=True)], 1), {}, CFG) == [9001]
    held = goblin(9500, can_reach_dwarves=False)
    assert reachable_threats(with_thieves([k1], 1, [held]), {}, CFG) == [9001]


@test("plan: a falcon over the fields: no alarm, no gates armed, no squad of the defence; a crossbow squad "
      "with bolts goes at it, never a melee one")
def _():
    f = falcon(can_reach_dwarves=None)
    fw = {"merchants": 0, "caravan": [], "wild": [{"id": f["id"], "name": "peregrine falcon", "wild": True,
                                                    "flier": True, "outside": True, "size": 129,
                                                    "distance_outside": 8, "distance": 8}], "wild_total": 1}
    melee = sq(11, 60)
    xbow = sq(12, 20, ai_uniform="AI crossbow")
    xbow["power"].update(ranged=3, ranged_power=20, melee_power=2)
    s = fort([f], [melee, xbow], field_watch=fw)
    m = Memory()
    note_cycle(s, m)
    props, notes = plan(s, m)
    assert not alarm_on(props) and not by(props, "gates") and not by(props, "squad_attack"), \
        [(p.rule, p.action) for p in props if p.rule in ("threat_alert", "gates", "squad_attack")]
    hunt = by(props, "wild_hunt")
    assert len(hunt) == 1 and hunt[0].action["squad_id"] == 12, [(p.rule, p.action) for p in hunt]
    s2 = fort([f], [melee], field_watch=fw)
    props, notes = plan(s2, Memory())
    assert not by(props, "wild_hunt") and any("crossbow squad with bolts" in n for n in notes), \
        [n for n in notes if "falcon" in n]


@test("plan: an agitated wolf in the caverns that can walk to a dwarf: one squad hunts it (strong enough), no "
      "alarm, no gates; the six-squad answer is gone")
def _():
    squads = [sq(10 + i, 60) for i in range(6)]
    s = fort([wolf()], squads)
    m = Memory()
    note_cycle(s, m)
    props, notes = plan(s, m)
    assert not alarm_on(props) and not by(props, "gates") and not by(props, "squad_attack")
    hunt = by(props, "wild_hunt")
    assert len(hunt) == 1 and hunt[0].action["kill"] == [7002], [(p.rule, p.action) for p in hunt]
    far = fort([wolf(distance_to_nearest_dwarf=80)], squads)
    assert not by(plan(far, Memory())[0], "wild_hunt")


@test("plan: a kobold thief inside: no alarm, no gates; the thieves rule's one squad")
def _():
    k = goblin(9001, name="kobold thief", invader=False, size=20000, distance_to_nearest_dwarf=5)
    s = fort([k], [sq(10 + i, 60) for i in range(6)])
    s["threats"] = {"thieves": {"list": [{"id": 9001, "name": "kobold thief", "kind": "thief", "inside": True,
                                          "can_reach_dwarves": True}]}}
    s["entrances"]["intruders_inside"] = [9001]
    m = Memory()
    note_cycle(s, m)
    props, _ = plan(s, m)
    assert not alarm_on(props) and not by(props, "gates", "arm_gates"), \
        [(p.rule, p.action) for p in props if p.rule in ("threat_alert", "gates")]
    kills = [p for p in by(props, typ="squad_orders") if 9001 in (p.action.get("kill") or [])]
    assert len(kills) == 1, [(p.rule, p.action) for p in kills]


@test("hunt: a target another rule sent a squad at this cycle (the wildlife guard's falcon) is not hunted too")
def _():
    import planner_hunt as PH
    from planner_core import Proposal
    tgt = {"id": 7001, "name": "falcon", "kinds": [], "great_danger": False, "size": 129, "flier": True,
           "pos": {"x": 10, "y": 10, "z": 50}, "layer": "surface", "region": "surface", "fire_breather": False,
           "route": {"ok": True, "length": 20, "blocked_by": "none"}, "near_workers": 2, "seen_ticks": 600,
           "can_reach_dwarves": None, "why": "danger"}
    q = {"id": 3, "name": "Bows", "soldiers": 5, "power": 50.0, "armed": 5, "armored": 5, "ranged": 5,
         "at_home": True, "hunting": None, "sheltering": False, "ai_uniform": "AI crossbow"}
    base = {"date": {"year": 200, "tick": 50000, "day": 1, "month": "Granite", "season": "spring"},
            "dwarves": {"total": 60, "adults": 50}, "settings": {"traits": {}, "hunt_mode": "ai"},
            "others_on_map": {"threats": []}, "civ_alert": False,
            "hunt": {"targets": [tgt], "squads": [q, dict(q, id=4), dict(q, id=5)], "hunts": []}}
    s = digest.normalize(copy.deepcopy(base))
    props, notes = [], []
    PH._hunt_rule(s, dict(CFG), props, notes, None)
    assert [p for p in props if p.action.get("type") == "hunt_send"], (props, notes)   # hunted alone
    props = [Proposal("wild_hunt", {"type": "squad_orders", "squad_id": 9, "kill": [7001]}, "the falcon", 2)]
    notes = []
    PH._hunt_rule(digest.normalize(copy.deepcopy(base)), dict(CFG), props, notes, None)
    assert not [p for p in props if p.action.get("type") == "hunt_send"], [p.action for p in props]
    assert any("another rule" in n for n in notes), notes


# --- the matchup for an ambush or a siege -------------------------------------------------

@test("60 goblins at 0.7x (War-hold's six squads, 423 against ~600): no squad sent out, said; the alarm and "
      "the gates as before")
def _():
    gobs = [goblin(8000 + i) for i in range(60)]
    squads = [sq(10 + i, p) for i, p in enumerate((102.7, 22.9, 75.4, 66.3, 74.4, 81.7))]
    s = fort(gobs, squads)
    m = Memory()
    note_cycle(s, m)
    props, notes = plan(s, m)
    assert alarm_on(props) and by(props, "gates", "arm_gates")
    assert not by(props, "squad_attack"), [(p.rule, p.action.get("squad_id")) for p in by(props, "squad_attack")]
    assert any("no sortie" in n for n in notes), [n for n in notes if "goblin" in n][:4]


@test("ten goblins and six strong squads: the smallest party of the strongest that clears fight_ratio goes, "
      "the rest stay home; a few inside of a siege too strong: the squads go at those only")
def _():
    gobs = [goblin(8000 + i) for i in range(10)]                    # need 100, x2 = 200
    squads = [sq(10 + i, p) for i, p in enumerate((150, 120, 40, 30, 20, 10))]
    s = fort(gobs, squads)
    props, _ = plan(s, Memory())
    sent = sorted(p.action["squad_id"] for p in by(props, "squad_attack"))
    assert sent == [10, 11], sent
    big = fort([goblin(8000 + i) for i in range(40)], squads)       # need 400: short
    big["entrances"]["intruders_inside"] = [8000, 8001]
    props, _ = plan(big, Memory())
    att = by(props, "squad_attack")
    assert att and all(sorted(p.action["kill"]) == [8000, 8001] for p in att), [(p.action) for p in att]
    assert len(att) == 1, [p.action for p in att]                   # one squad (150) clears 20 at 1x


# --- the power scale -----------------------------------------------------------------------

@test("power: a falcon is well under one soldier (a steel axe lord ~11.4); a goblin, a titan as before")
def _():
    assert threat_power(falcon()) < 1.0, threat_power(falcon())
    assert threat_power({"size": 5000}) < 4 and threat_power({"size": 20000}) < 7
    assert abs(threat_power({"size": 60000}) - 10.0) < 1e-9
    assert abs(threat_power({"size": 9000000, "kinds": ["Titan"], "great_danger": True})
               - (8 + 2 * (150 ** 0.5)) * 1.2) < 1e-9
    assert abs(threat_power({"size": 129, "great_danger": True}) - (8 + 2 * (129 / 60000) ** 0.5)) < 1e-9
    import planner_siege as PSG
    assert PSG.SIEGE_CONFIG["wild_big_power"] >= 2 * threat_power({"size": PSG.SIEGE_CONFIG["wild_big_size"]})


# --- the "can reach" alarm's maximum time ---------------------------------------------------

def far_beast(**kw):
    t = {"id": 6001, "name": "a titan", "great_danger": True, "kinds": ["Titan"], "size": 9000000,
         "can_reach_dwarves": True, "layer": "upper_levels", "distance_to_nearest_dwarf": 150,
         "levels_from_nearest_dwarf": 0, "pos": {"x": 10, "y": 10, "z": 170}}
    t.update(kw)
    return t


@test("reach cap: an AI alarm up 3 days for an enemy in reach that never came near comes down; near or "
      "inside, or under 3 days: it stays")
def _():
    s = fort([far_beast()], [], alert=True)
    m = Memory(ai_alert_raised=True)
    from planner_core import abs_tick
    t0 = abs_tick(s)
    note_alarm_change(m, t0 - 3 * DAY, True, "1 threat(s) can reach the dwarves")
    assert reach_alarm_over(s, m, CFG, [6001]).startswith("the alarm has been up 3 days")
    props, _ = plan(s, m)
    offs = [p for p in props if p.action == {"type": "civ_alert", "on": False}]
    assert offs and "has been up" in offs[0].reason, [(p.rule, p.action, p.reason) for p in props
                                                      if p.rule == "threat_alert"]
    assert not reach_alarm_over(fort([far_beast(distance_to_nearest_dwarf=40)], [], alert=True), m, CFG, [6001])
    s_in = fort([far_beast(great_danger=False, kinds=[])], [], alert=True)
    s_in["entrances"]["intruders_inside"] = [6001]
    assert not reach_alarm_over(s_in, m, CFG, [6001])
    m2 = Memory(ai_alert_raised=True)
    note_alarm_change(m2, t0 - 2 * DAY, True, "1 threat(s) can reach the dwarves")
    assert not reach_alarm_over(s, m2, CFG, [6001])


@test("reach cap: lowered for its maximum time, not raised again for the same far enemies; raised for one "
      "that comes near or a new one")
def _():
    from planner_core import abs_tick
    s = fort([far_beast()], [])
    t0 = abs_tick(s)
    m = Memory()
    m.atlas = {"lockdown": {"new": t0 - 4 * DAY, "seen": [6001]}}
    note_alarm_change(m, t0 - DAY, False, "the alarm has been up 3 days and none of ...")
    assert reach_raise_held(s, m, CFG, [6001])
    props, notes = plan(s, m)
    assert not alarm_on(props) and any("maximum time" in n for n in notes), [n for n in notes if "alarm" in n]
    near = fort([far_beast(distance_to_nearest_dwarf=30)], [])
    assert not reach_raise_held(near, m, CFG, [6001])
    m.atlas["lockdown"]["new"] = t0
    assert not reach_raise_held(s, m, CFG, [6001])
    note_alarm_change(m, t0, True, "1 threat(s) can reach the dwarves")
    assert "reach_capped" not in m.alarm_gov


# --- the bridge (Lua) ------------------------------------------------------------------------

SIEGE_SRC = (ROOT / "tests" / "test_siege.py").read_text(encoding="utf-8")
SIEGE_FAKE = re.search(r'^FAKE = r"""(.*?)"""', SIEGE_SRC, re.S | re.M).group(1)


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


if LuaRuntime is not None:
    @test("field_watch: an agitated animal (DF's isDanger) is listed wild; an invader's animal or a "
          "non-animal danger is not")
    def _():
        lua = LuaRuntime(unpack_returned_tuples=True)
        env, w = lua.execute(SIEGE_FAKE, module_src("ai-siege.lua"))
        lua.execute("""local env = ...
            env.dfhack.units.isAnimal = function(u) return u.animal == true end
            env.dfhack.units.isFortControlled = function(u) return false end
            env.dfhack.units.isNightCreature = function(u) return false end
            env.dfhack.units.isUndead = function(u) return false end""", env)
        w.unit(T(lua, {"id": 1, "citizen": True, "pos": {"x": 20, "y": 3, "z": 100}}))
        w.unit(T(lua, {"id": 30, "danger": True, "wild": True, "animal": True, "name": "falcon",
                       "pos": {"x": 25, "y": 4, "z": 100}}))
        w.unit(T(lua, {"id": 31, "danger": True, "wild": True, "animal": True, "invader": True, "name": "war dog",
                       "pos": {"x": 26, "y": 4, "z": 100}}))
        w.unit(T(lua, {"id": 32, "danger": True, "name": "thief", "pos": {"x": 27, "y": 4, "z": 100}}))
        r = env.field_watch(None)
        ids = {r.wild[k].id for k in r.wild}
        assert ids == {30}, ids

    @test("gate watcher: small wildlife is no visible danger (a falcon); a big animal, an invader's animal "
          "and an invader are")
    def _():
        lua = LuaRuntime(unpack_returned_tuples=True)
        src = module_src("ai-gates-watch.lua")
        M = lua.execute("""local src = ...
            local env = setmetatable({}, {__index = _G})
            local units = {}
            local function f(k) return function(u) return u[k] == true end end
            env.df = {global = {world = {units = {active = units}}}}
            env.dfhack = {units = {isAlive = function() return true end, isCitizen = f('citizen'),
                isHidden = f('hidden'), isDanger = f('danger'), isInvader = f('invader'),
                isGreatDanger = f('great'), isAnimal = f('animal'), isNightCreature = f('night'),
                isUndead = f('undead')}}
            env.reqscript = function() return setmetatable({}, {__index = function() return function() end end}) end
            env.dfhack.timeout = function() end
            local chunk = assert(load(src, 'ai-gates-watch', 't', env))
            pcall(chunk)
            env._units = units
            return env""", src)
        rows = [{"id": 1, "danger": True, "animal": True, "size": 129},
                {"id": 2, "danger": True, "animal": True, "size": 5000000},
                {"id": 3, "danger": True, "animal": True, "invader": True, "size": 129},
                {"id": 4, "danger": True, "invader": True, "size": 60000}]
        for r in rows:
            u = T(lua, {"id": r["id"], "danger": r.get("danger"), "animal": r.get("animal"),
                        "invader": r.get("invader"), "flags1": {}, "pos": {"x": 1, "y": 1, "z": 1},
                        "body": {"size_info": {"size_cur": r["size"]}}})
            M._units[len(M._units) + 1] = u
        if M.visible_dangers is None:
            raise AssertionError("visible_dangers not loaded")
        seen = M.visible_dangers()
        assert len(seen) == 3, len(seen)
        assert M.small_wildlife(M._units[1]) is True and M.small_wildlife(M._units[2]) is False

    @test("the bridge's threat rows say animal and agitated (DFHack isAnimal / isAgitated)")
    def _():
        src = module_src("ai-bridge-report.lua")
        assert "dfhack.units.isAnimal, u" in src and "dfhack.units.isAgitated, u" in src


if LuaRuntime is None:
    finish("the Lua tests need the lupa package (pip install lupa)")
finish()
