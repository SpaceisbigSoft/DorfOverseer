"""(r34b) A hostile come to the map is a threat at once, seen or not.

B, 26 Nov 15:15:57: the Weregiraffe Child came hostile at the map's edge (the
journal's arrival event) and for 76 s was no threat row (DF hid it); it killed
the tavern keeper 100 tiles from the gates before the alarm, the gates or a
squad. brain/planner_hostile_arrivals.py, planner_core.reachable_threats,
planner_near_gates, lua get_others_on_map (sneak_threat, were_curse) and
ai-military-duty kill_target_ok.

    python3 tests/test_r34b_hostile_arrival.py
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
from planner_core import reachable_threats  # noqa: E402
import planner_hostile_arrivals as H  # noqa: E402

CFG = dict(PLANNER_CONFIG)
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
NAME = 'Lastta Geltaram "Keysold", Weregiraffe Child'
ARRIVAL = {"animal": False, "great": False, "hostile": True, "kind": "arrival", "name": NAME,
           "own_civ": False, "x": 1, "y": 4, "z": 161, "unit_id": 7701}


def fort(threats=None) -> dict:
    s = copy.deepcopy(BASE)
    # the fixture's beasts down in the caverns and below stay (no near-gates for them); its
    # specters on 'fort_levels' go (a great danger the squads can't beat: near-gates already)
    deep = [t for t in s["others_on_map"]["threats"] if H._deep(t.get("layer"))]
    s["others_on_map"]["threats"] = deep + list(threats or [])
    s["near_gates"] = {"on": False, "radius": 25,
                       "far": [{"id": 50, "name": "Medtob, Tavern Keeper", "d": 100}], "far_total": 1}
    return s


def sq(i, members=10, power=20):
    return {"id": i, "name": f"Squad {i}", "members": members, "size": 10, "orders": 0, "ai_orders": 0,
            "power": {"power": power, "melee_power": power, "armed": members}, "routine": "Constant training"}


def rules(props):
    return {p.rule: p for p in props}


def human(i=7702, **kw):
    """A were outsider in its own (human) form, its curse known, walking the surface."""
    t = {"id": i, "name": "Lastta Geltaram, Human", "can_reach_dwarves": True, "great_danger": False,
         "flier": False, "invader": False, "layer": "upper_levels", "size": 70000, "hostile": True,
         "pos": {"x": 50, "y": 75, "z": 170}, "distance_to_nearest_dwarf": 30, "levels_from_nearest_dwarf": 0,
         "were_curse": True}
    t.update(kw)
    return t


@test("B's Weregiraffe Child: the arrival event alone raises the alarm, arms the gates and the near-gates burrow, "
      "in the same cycle")
def _():
    s, m = fort(), Memory()
    assert H.note_hostile_arrivals(s, m, [ARRIVAL]) == 1
    assert m.hostile_arrivals and m.hostile_arrivals[0]["id"] == 7701
    props, notes = plan(s, m)
    r = rules(props)
    assert "threat_alert" in r and r["threat_alert"].action.get("on") is True, \
        [(p.rule, p.reason) for p in props][:20]
    assert "gates" in r and r["gates"].action["type"] == "arm_gates", [(p.rule, p.reason) for p in props][:20]
    assert "near_gates" in r and r["near_gates"].action.get("on") is True, [(p.rule, p.reason) for p in props][:20]
    assert NAME in r["near_gates"].reason


@test("the arrival's row: on the surface (map layers), a were by name, hidden; never one down in the caverns")
def _():
    s, m = fort(), Memory()
    H.note_hostile_arrivals(s, m, [ARRIVAL])
    add = H.merge_arrivals(s, m, CFG)
    assert len(add) == 1 and add[0]["layer"] == "upper_levels" and add[0]["transformed"] is True
    assert add[0]["hidden"] is True and add[0]["can_reach_dwarves"] is None
    assert 7701 in reachable_threats(s, {}, CFG)
    s2, m2 = fort(), Memory()
    H.note_hostile_arrivals(s2, m2, [dict(ARRIVAL, z=125, unit_id=7703, name="Bogeyman")])    # Cavern1
    assert H.merge_arrivals(s2, m2, CFG) == []


@test("not kept: an animal, a great danger (hidden_great), one of the fort's own, a peaceful arrival")
def _():
    s, m = fort(), Memory()
    evs = [dict(ARRIVAL, unit_id=1, animal=True, name="Giant Dingo"), dict(ARRIVAL, unit_id=2, great=True),
           dict(ARRIVAL, unit_id=3, own_civ=True), dict(ARRIVAL, unit_id=4, hostile=False)]
    assert H.note_hostile_arrivals(s, m, evs) == 0 and m.hostile_arrivals == []
    # a were in beast form is no wildlife, animal or not
    assert H.note_hostile_arrivals(s, m, [dict(ARRIVAL, animal=True)]) == 1


@test("dropped at its death, once the bridge lists it, and after the hold")
def _():
    s, m = fort(), Memory()
    H.note_hostile_arrivals(s, m, [ARRIVAL])
    H.note_hostile_arrivals(s, m, [{"kind": "death", "unit_id": 7701}])
    assert m.hostile_arrivals == []
    H.note_hostile_arrivals(s, m, [ARRIVAL])
    s["others_on_map"]["threats"].append(human(7701))
    H.note_hostile_arrivals(s, m, [])
    assert m.hostile_arrivals == []
    s, m = fort(), Memory()
    H.note_hostile_arrivals(s, m, [ARRIVAL])
    s["date"]["tick"] += H.HOLD_TICKS + 1
    H.note_hostile_arrivals(s, m, [])
    assert m.hostile_arrivals == []


@test("the bridge's hidden row (sneak_threat), reach unknown: a threat that can reach the dwarves")
def _():
    t = human(7704, hidden=True, can_reach_dwarves=None, were_curse=None, kinds=["NightCreature"])
    s = fort([t])
    assert 7704 in reachable_threats(s, {}, CFG)
    # its walk group says it can't: not counted; nor one in the caverns
    assert 7704 not in reachable_threats(fort([dict(t, can_reach_dwarves=False)]), {}, CFG)
    assert 7704 not in reachable_threats(fort([dict(t, layer="Cavern2")]), {}, CFG)


@test("a were outsider in human form flagged hostile (were_curse): counted, the alarm and the squads go")
def _():
    s = fort([human()])
    s["military"]["squads"] = [sq(183), sq(201)]
    assert H.stalker(human()) and 7702 in reachable_threats(s, {}, CFG)
    props, notes = plan(s, Memory())
    r = rules(props)
    assert r.get("threat_alert") and r["threat_alert"].action.get("on") is True
    assert any(p.rule in ("squad_attack", "squad_hunt", "hunt") and 7702 in (p.action.get("kill") or [])
               for p in props), [(p.rule, p.reason) for p in props if "squad" in p.rule or "hunt" in p.rule]
    assert r.get("near_gates") and r["near_gates"].action.get("on") is True


@test("an ordinary visitor (no curse, not hidden) is no stalker; nor a caged were")
def _():
    assert not H.stalker({"id": 1, "name": "Urist, Poet", "can_reach_dwarves": True, "layer": "upper_levels"})
    assert not H.stalker(human(caged=True))


@test("lua: the bridge counts hidden hostile night creatures, weres and ambushers, and were outsiders in their "
      "own form; kill_target_ok takes a were outsider; both compile")
def _():
    src = (ROOT / "lua" / "ai-bridge-report-world.lua").read_text(encoding="utf-8")
    assert "function sneak_threat(u, layer, TH)" in src and "function were_curse(u, TH)" in src
    assert "(not hidden or sneak)" in src and "hidden = sneak or nil" in src and "were_curse = cursed or nil" in src
    assert "hidden_in_ambush" in src and "isOwnGroup" in src
    duty = (ROOT / "lua" / "ai-military-duty.lua").read_text(encoding="utf-8")
    assert "reqscript('ai-threats').were_cursed(u)" in duty
    for f in ("ai-bridge-report-world.lua", "ai-military-duty.lua"):
        try:
            r = subprocess.run(["texluac", "-p", str(ROOT / "lua" / f)], capture_output=True, text=True)
        except FileNotFoundError:
            continue
        assert r.returncode == 0, r.stderr


LUA_STUB = """
dfhack = {units = {}}
local U = dfhack.units
function U.isDanger(u) return u.danger == true end
function U.isNightCreature(u) return u.night == true end
"""


def lua_part():
    from lupa.lua53 import LuaRuntime
    src = (ROOT / "lua" / "ai-bridge-report-world.lua").read_text(encoding="utf-8")
    part = src[src.index("function were_curse(u, TH)"):src.index("function get_others_on_map()")]
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(LUA_STUB + part)
    return lua


@test("lua (lupa): sneak_threat takes a hidden hostile were or night creature off the deep layers and an "
      "ambusher anywhere; were_curse reads were_race (not its own race) or the WERECURSE syndrome")
def _():
    need_lua()
    lua = lua_part()
    mk = lua.eval("""function(t)
        t.flags1 = t.flags1 or {}
        t.enemy = t.enemy or {normal_race = -1, were_race = t.race}
        return t end""")
    sneak, curse = lua.globals().sneak_threat, lua.globals().were_curse
    giraffe = mk(lua.table_from({"danger": True, "race": 5,
                                 "enemy": lua.table_from({"normal_race": 1, "were_race": 5})}))
    assert sneak(giraffe, "upper_levels", None)[0] is True          # changed: its race not its birth race
    assert sneak(giraffe, "Cavern1", None)[0] is False
    human = mk(lua.table_from({"danger": True, "race": 1,
                               "enemy": lua.table_from({"normal_race": 1, "were_race": 5})}))
    assert curse(human, None) is True and sneak(human, "upper_levels", None)[0] is True
    plain = mk(lua.table_from({"danger": True, "race": 1}))
    assert curse(plain, None) is False and sneak(plain, "upper_levels", None)[0] is False
    ambusher = mk(lua.table_from({"danger": True, "race": 1,
                                  "flags1": lua.table_from({"hidden_in_ambush": True})}))
    r = sneak(ambusher, "Cavern2", None)
    assert r[0] is True and r[1] is True
    calm = mk(lua.table_from({"danger": False, "race": 5, "night": True}))
    assert sneak(calm, "upper_levels", None)[0] is False
    caged = mk(lua.table_from({"danger": True, "night": True, "race": 2,
                               "flags1": lua.table_from({"caged": True})}))
    assert sneak(caged, "upper_levels", None)[0] is False
    night = mk(lua.table_from({"danger": True, "night": True, "race": 2}))
    assert sneak(night, "upper_levels", None)[0] is True
    th = lua.table_from({"were_cursed": lua.eval("function(u) return u.syn == true end")})
    assert curse(mk(lua.table_from({"race": 1, "syn": True})), th) is True


finish()
