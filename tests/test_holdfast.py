"""(0.105.47, R2 item 7) Holding fast against titans and thieves
(brain/planner_holdfast.py, forensics I7d 2a and 2c): one ordinary enemy
judged before the gates open (and the citizens let in by another gate);
never recruits alone at an enemy; a kill order held a day (no recall
flapping); gates held only by doors or hatches counted open while a
building destroyer is about (the shelter plan's way in, the shelter's
margins, a drawbridge or a wall there); a squad on the main stair and the
named artifact while an intruder hides; squads out to eat one at a time and
back once fed, their post on a level with drink. The wiring.

    python tests/test_holdfast.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from py_parts import py_family_src  # noqa: E402  (r7) overseer.py and its parts
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
from planner_core import Proposal  # noqa: E402
import planner_holdfast as HF  # noqa: E402
import planner_army as PA  # noqa: E402
import planner_shelter as PS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = dict(PLANNER_CONFIG)
DAY = 1200
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
NOW = 148 * 403200 + 332256


def acts(props, typ=None, rule=None):
    return [p for p in props if (typ is None or p.action.get("type") == typ) and (rule is None or p.rule == rule)]


def goblin(i=6000, x=31, y=135, z=173, **kw):
    t = {"id": i, "name": "Rakfil the goblin hammerman", "can_reach_dwarves": True, "great_danger": False,
         "invader": False, "layer": "surface", "size": 60000, "pos": {"x": x, "y": y, "z": z},
         "distance_to_nearest_dwarf": 6, "levels_from_nearest_dwarf": 0}
    t.update(kw)
    return t


def sq(i, power, members=5, **kw):
    q = {"id": i, "name": f"Squad {i}", "members": members, "size": 10, "orders": 0, "ai_orders": 0,
         "power": {"power": power, "armed": members}}
    q.update(kw)
    return q


def fort(threats, squads, ents=None, **ent_kw) -> dict:
    s = copy.deepcopy(BASE)
    s["others_on_map"]["threats"] = threats
    s["others_on_map"]["threats_that_can_reach_dwarves"] = sum(1 for t in threats if t.get("can_reach_dwarves"))
    s["military"]["squads"] = squads
    e = s["entrances"]
    if ents is not None:
        e["entrances"] = ents
    e.update(ent_kw)
    return s


def gate(i, x, y, z=173, closed=True, kinds=("door",), **kw):
    e = {"id": i, "kind": "surface", "x": x, "y": y, "z": z, "width": 1, "sealed": True, "closed": closed,
         "equipment": [{"id": 500 + i, "kind": k} for k in kinds], "door_spots": 0}
    e.update(kw)
    return e


# --- 1. one ordinary enemy at the gates -----------------------------------------------

@test("one_enemy_hold: a goblin 5 tiles from a gate (squad strong): held; far off: none; inside: none")
def _():
    on = sq(11, 5000, ai_orders=1, kill_ids=[6000])
    s = fort([goblin()], [on], ents=[gate(1, 31, 140)], intruders_inside=[])
    h = HF.one_enemy_hold(s, CFG)
    assert h and h["near"] == 5 and "tiles from a gate" in h["why"], h
    s = fort([goblin(y=60, distance_to_nearest_dwarf=80)], [on], ents=[gate(1, 31, 140)], intruders_inside=[])
    assert HF.one_enemy_hold(s, CFG) is None
    s = fort([goblin()], [on], ents=[gate(1, 31, 140)], intruders_inside=[6000])
    assert HF.one_enemy_hold(s, CFG) is None


@test("one_enemy_hold: far off but the squads on it are too weak (the matchup): held")
def _():
    on = sq(11, 3, ai_orders=1, kill_ids=[6000])          # B's recruits
    s = fort([goblin(y=60, distance_to_nearest_dwarf=80)], [on], ents=[gate(1, 31, 140)], intruders_inside=[])
    h = HF.one_enemy_hold(s, CFG)
    assert h and "too weak" in h["why"] and h["ratio"] < CFG["fight_ratio"], h


@test("E 254: armed gates, a squad on the goblin at the gate, 3 shut out: no open_gates; far off: opened as before")
def _():
    on = sq(11, 5000, members=10, ai_orders=1, kill_ids=[6000])
    s = fort([goblin()], [on, sq(12, 5000, members=10)], ents=[gate(1, 31, 140)], armed=True,
             citizens_outside=3, intruders_inside=[])
    props, notes = plan(s, Memory())
    assert not acts(props, "open_gates"), [(p.rule, p.action) for p in props if p.rule in ("gates", "stranded")]
    assert any("gates stay shut" in n for n in notes), [n for n in notes if "gate" in n][:8]
    s = fort([goblin(y=60, distance_to_nearest_dwarf=80)], [on, sq(12, 5000, members=10)],
             ents=[gate(1, 31, 140)], armed=True, citizens_outside=3, intruders_inside=[])
    props, _ = plan(s, Memory())
    assert acts(props, "open_gates"), [(p.rule, p.action) for p in props if p.rule in ("gates", "stranded")]


@test("the shut-out citizens let in by the other gate, far from the enemy (open_entrance)")
def _():
    on = sq(11, 5000, members=10, ai_orders=1, kill_ids=[6000])
    row = {"id": 1, "name": "Moldath", "x": 31, "y": 145, "z": 173, "out_ticks": 400, "cause": "gate_shut",
           "by_ai": True, "entrance": {"id": 1, "kind": "surface", "x": 31, "y": 140, "z": 173},
           "gate_danger": 8, "danger_near": 8}
    s = fort([goblin(y=125)], [on, sq(12, 5000, members=10)], ents=[gate(1, 31, 140), gate(2, 90, 140)],
             armed=True, citizens_outside=1, intruders_inside=[], stranded=[row])
    props, notes = plan(s, Memory())
    oe = acts(props, "open_entrance")
    assert oe and oe[0].action["id"] == 2 and "instead" in oe[0].reason, [(p.rule, p.action) for p in oe]
    h = HF.one_enemy_hold(s, CFG)
    assert HF.other_gate(s, h, 1)["id"] == 2
    assert HF.other_gate(s, h, 2)["id"] != 2 if HF.other_gate(s, h, 2) else True


# --- 2. never recruits alone ----------------------------------------------------------

@test("matchup filter: recruits alone at a thief inside -> the strongest squad goes instead")
def _():
    s = fort([goblin()], [sq(11, 3), sq(12, 5000)], intruders_inside=[6000])
    p = Proposal("squad_attack", {"type": "squad_orders", "squad_id": 11, "kill": [6000]}, "send 11", 0)
    notes = []
    out = HF._squad_matchup_filter(s, Memory(), CFG, [p], notes)
    ks = acts(out, "squad_orders")
    assert [q.action["squad_id"] for q in ks] == [12], [(q.action, q.reason) for q in ks]
    assert "alone was too weak" in ks[0].reason


@test("matchup filter: strong enough alone: unchanged; all too weak at one outside: none sent, said")
def _():
    s = fort([goblin(y=60)], [sq(11, 5000), sq(12, 3)], intruders_inside=[])
    p = Proposal("squad_attack", {"type": "squad_orders", "squad_id": 11, "kill": [6000]}, "send 11", 0)
    assert HF._squad_matchup_filter(s, Memory(), CFG, [p], []) == [p]
    s = fort([goblin(y=60)], [sq(11, 2), sq(12, 3)], intruders_inside=[])
    p = Proposal("squad_attack", {"type": "squad_orders", "squad_id": 11, "kill": [6000]}, "send 11", 0)
    notes = []
    assert HF._squad_matchup_filter(s, Memory(), CFG, [p], notes) == []
    assert any("too weak" in n for n in notes), notes
    # ...but inside the fort every free squad goes together
    s = fort([goblin()], [sq(11, 2), sq(12, 3)], intruders_inside=[6000])
    p = Proposal("squad_attack", {"type": "squad_orders", "squad_id": 11, "kill": [6000]}, "send 11", 0)
    out = HF._squad_matchup_filter(s, Memory(), CFG, [p], [])
    assert sorted(q.action["squad_id"] for q in out) == [11, 12], [q.action for q in out]


@test("matchup filter: a great danger's order and an unknown target are left alone")
def _():
    s = fort([goblin(great_danger=True, kinds=["Titan"])], [sq(11, 3)], intruders_inside=[])
    p = Proposal("squad_attack", {"type": "squad_orders", "squad_id": 11, "kill": [6000]}, "", 0)
    q = Proposal("squad_attack", {"type": "squad_orders", "squad_id": 11, "kill": [77]}, "", 0)
    assert HF._squad_matchup_filter(s, Memory(), CFG, [p, q], []) == [p, q]


# --- 3. no recall flapping -------------------------------------------------------------

def _recall(sid=11):
    return Proposal("squad_recall", {"type": "squad_orders", "squad_id": sid, "clear": True},
                    "no more threats: call it back", 1)


@test("kill hold: a kill order younger than a day is held while its target is about and beatable")
def _():
    m = Memory()
    q = sq(11, 5000, ai_orders=1, kill_ids=[6000])
    s = fort([goblin(can_reach_dwarves=False)], [q])
    notes = []
    out = HF._kill_hold_filter(s, m, CFG, [_recall()], notes)       # not booked yet: a new order
    assert out == [] and any("keeps its kill order" in n for n in notes), notes
    assert m.holdfast == {}                                          # plan() writes no memory
    HF.note_holdfast_cycle(s, m, CFG)                                # note_cycle books it
    assert m.holdfast["kill"]["11"] == {"ids": [6000], "since": NOW, "members": q["members"]}   # (0.105.54) + members
    assert HF._kill_hold_filter(s, m, CFG, [_recall()], []) == []
    # a day on: the recall goes through
    m.holdfast["kill"]["11"]["since"] -= DAY + 1
    assert len(HF._kill_hold_filter(s, m, CFG, [_recall()], [])) == 1


@test("kill hold: target dead or gone, the matchup turned to hide, an urgent recall: not held")
def _():
    q = sq(11, 5000, ai_orders=1, kill_ids=[6000])
    s = fort([], [q])
    assert len(HF._kill_hold_filter(s, Memory(), CFG, [_recall()], [])) == 1          # gone
    q2 = sq(11, 3, ai_orders=1, kill_ids=[6000])
    s = fort([goblin(can_reach_dwarves=False)], [q2])
    assert len(HF._kill_hold_filter(s, Memory(), CFG, [_recall()], [])) == 1          # too weak: hide
    s = fort([goblin(can_reach_dwarves=False)], [q])
    urgent = Proposal("squad_recall", {"type": "squad_orders", "squad_id": 11, "clear": True}, "called off", 0)
    assert len(HF._kill_hold_filter(s, Memory(), CFG, [urgent], [])) == 1
    titan = goblin(great_danger=True, kinds=["Titan"], size=20_000_000, can_reach_dwarves=False,
                   layer="upper_levels")
    # (0.105.54) ~53 needed, about even odds now (was 2x with 60): 30 hides
    s = fort([titan], [sq(11, 30, ai_orders=1, kill_ids=[6000])])
    assert len(HF._kill_hold_filter(s, Memory(), CFG, [_recall()], [])) == 1          # fight_or_hide: hide
    s = fort([titan], [q])                                             # strong enough: held
    assert HF._kill_hold_filter(s, Memory(), CFG, [_recall()], []) == []


# --- 4. building destroyers --------------------------------------------------------------

def titan(**kw):
    t = goblin(i=900, name="Savanna Titan", great_danger=True, destroyer=True, kinds=["Titan"],
               size=20_000_000, y=60, distance_to_nearest_dwarf=80, can_reach_dwarves=False, layer="upper_levels")
    t.update(kw)
    return t


@test("door_only: doors/hatches alone yes; a drawbridge in it or in front of it no")
def _():
    assert HF.door_only(gate(1, 1, 1, kinds=("hatch",)))
    assert not HF.door_only(gate(1, 1, 1, kinds=("hatch", "bridge")))
    assert not HF.door_only(gate(1, 1, 1, outer=[{"id": 9, "kind": "bridge"}]))
    assert not HF.door_only({"equipment": []})


@test("a titan that breaks buildings: the hatch-only gate said open and a drawbridge put there; "
      "refused: walled when another way in stays; citizens out: nothing built")
def _():
    m = Memory()
    ents = [gate(1, 31, 140, kinds=("bridge",)), gate(2, 131, 126, z=165, kinds=("hatch",))]
    s = fort([titan()], [], ents=ents, citizens_outside=0, stranded=[])
    props, notes = [], []
    HF._destroyer_gate_rule(s, CFG, props, notes, m)
    assert any("counts as open though its gate is shut" in n for n in notes), notes
    assert props and props[0].action == {"type": "fortify_entrance", "entrance_id": 2, "style": "drawbridge"}
    HF.note_holdfast(props[0], {"ok": False}, s, m, NOW + 5)          # record(): tried, refused
    # the drawbridge refused (record() books gate_failures by spot)
    m.gate_failures["131,126,165"] = "a stair updown, which walls and doors can't stand on"
    m.gate_failure_ticks["131,126,165"] = NOW + 5
    props = []
    HF._destroyer_gate_rule(s, CFG, props, [], m)
    assert props and props[0].action["style"] == "sealed", [p.action for p in props]
    HF.note_holdfast(props[0], {"ok": False}, s, m, NOW + 10)
    m.gate_failure_ticks["131,126,165"] = NOW + 500
    props, notes = [], []
    HF._destroyer_gate_rule(s, CFG, props, notes, m)
    assert not props and any("neither bridged nor walled" in n for n in notes), notes
    s = fort([titan()], [], ents=ents, citizens_outside=2, stranded=[])
    props, notes = [], []
    HF._destroyer_gate_rule(s, CFG, props, notes, Memory())
    assert not props and any("citizens are shut out" in n for n in notes), notes
    # no destroyer: nothing
    s = fort([titan(destroyer=None)], [], ents=ents)
    props, notes = [], []
    HF._destroyer_gate_rule(s, CFG, props, notes, Memory())
    assert not props and not notes


@test("lua: the shelter plan takes a destroyer's door-only entrances as its ways in (ways_in, door_only)")
def _():
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute("""local src = ...
        local env = setmetatable({}, {__index = _G})
        env.reqscript = function(n) return {} end
        assert(load(src, 'ai-shelter-plan', 't', env))()
        return env""", module_src("ai-shelter-plan.lua"))
    lua.execute("""local env = ...
        local ents = {{id = 1, kind = 'surface', x = 10, y = 10, z = 100},
                      {id = 2, kind = 'surface', x = 80, y = 80, z = 95, door_only = true},
                      {id = 3, kind = 'cavern', x = 50, y = 50, z = 60, door_only = true}}
        local list = {{id = 900, x = 9, y = 9, z = 100, destroyer = true}, {id = 901, x = 11, y = 9, z = 100}}
        local ways = env.ways_in(list, ents)
        assert(#ways == 2 and ways[1].id == 1 and ways[2].id == 2, 'ways ' .. #ways)
        assert(list[1].way_in == 1 and list[1].door_ways[1] == 2 and #list[1].door_ways == 1)
        assert(list[2].door_ways == nil)
        local plain = {{id = 902, x = 9, y = 9, z = 100}}
        assert(#env.ways_in(plain, ents) == 1)
        assert(env.door_only({equipment = {{kind = 'hatch'}}}) == true)
        assert(env.door_only({equipment = {{kind = 'hatch'}, {kind = 'bridge'}}}) == false)
        assert(env.door_only({equipment = {{kind = 'door'}}, outer = {{kind = 'bridge'}}}) == false)
        assert(env.destroyer_of({race = 1, caste = 0}) == nil)""", env)


@test("lua: ai-society's shelter margins count a door-only gate open while a destroyer is on the map")
def _():
    src = (ROOT / "lua" / "ai-society.lua").read_text(encoding="utf-8")
    assert "if dgroups and door_only(e) then return false end" in src
    assert "function door_only(e)" in src


# --- 5. hidden intruders -----------------------------------------------------------------

def _arts(s):
    s["artifacts"] = {"artifacts": [{"id": 3, "item_id": 77, "name": "Ostagzokun the Glimmer of Ends",
                                     "x": 100, "y": 120, "z": 160, "state": "displayed"}]}
    return s


@test("an intruder DF reports and nobody has seen: a squad on the main stair, one at the named artifact")
def _():
    m = Memory()
    m.intrusion = {"tick": NOW - 100, "civ": -1, "invaders": 1}
    ents = [gate(1, 31, 140, lid=True)]
    s = _arts(fort([], [sq(11, 5000), sq(12, 4000)], ents=ents))
    n = HF.note_thief_targets(s, m, [{"kind": "report", "text": 'The goblin thief was spotted sneaking around! '
                                                                 '"You will not stand between me and Ostagzokun '
                                                                 'the Glimmer of Ends!"'}])
    assert n == 1 and m.holdfast["named"]["name"] == "Ostagzokun the Glimmer of Ends", m.holdfast
    props, notes = [], []
    HF._intruder_guard_rule(s, CFG, props, notes, m)
    st = acts(props, "squad_station")
    assert [(p.action["squad_id"], p.action["x"], p.action["z"]) for p in st] == [(11, 31, 173), (12, 100, 160)], \
        [p.action for p in st]
    assert "main stair" in st[0].reason and "the thief named" in st[1].reason
    assert "guards" not in m.holdfast                                # booked by record() once done
    HF.note_holdfast(st[0], {"ok": True}, s, m, NOW)
    assert m.holdfast["guards"]["11"]["x"] == 31


@test("the intruder seen (or gone): the guards come off their posts")
def _():
    m = Memory()
    m.intrusion = {"tick": NOW - 100, "civ": -1, "invaders": 1}
    m.holdfast = {"guards": {"11": {"x": 31, "y": 140, "z": 173, "what": "main stair", "tick": NOW - 90}}}
    m.last_threat_tick = NOW - 10                 # seen since
    s = fort([], [sq(11, 5000, ai_orders=1, stationed={"x": 31, "y": 140, "z": 173})], ents=[gate(1, 31, 140, lid=True)])
    props = []
    HF._intruder_guard_rule(s, CFG, props, [], m)
    rc = acts(props, "squad_orders")
    assert rc and rc[0].action == {"type": "squad_orders", "squad_id": 11, "clear": True}, [p.action for p in props]


@test("the full plan: an unseen intrusion puts a squad on the stair (squad_station)")
def _():
    m = Memory()
    m.intrusion = {"tick": NOW - 100, "civ": -1, "invaders": 1}
    s = fort([], [sq(11, 5000, members=10), sq(12, 4000, members=10)], ents=[gate(1, 31, 140, lid=True, closed=False)])
    props, notes = plan(s, m)
    assert acts(props, "squad_station", "intruder_guard"), [(p.rule, p.action) for p in props][:20]


@test("plan() writes no memory in these cases (intrusion guard, destroyer gate, a kill order)")
def _():
    m = Memory()
    m.intrusion = {"tick": NOW - 100, "civ": -1, "invaders": 1}
    ents = [gate(1, 31, 140, kinds=("bridge",)), gate(2, 131, 126, z=165, kinds=("hatch",))]
    s = fort([titan()], [sq(11, 5000, members=10), sq(12, 4000, members=10, ai_orders=1, kill_ids=[900])],
             ents=ents, citizens_outside=0, stranded=[])
    before = json.dumps({k: v for k, v in m.to_dict().items() if k != "second_way"}, sort_keys=True)
    plan(s, m)
    # (the second-way rule's own mark aside: not this module's)
    assert json.dumps({k: v for k, v in m.to_dict().items() if k != "second_way"}, sort_keys=True) == before


# --- 6. out to eat one at a time; the post with drink -------------------------------------

@test("rest_turn / rest_done: one squad out at a time; back once fed after post_rest_min_ticks")
def _():
    rest = {"11": NOW + 2 * DAY - 100}
    assert HF.rest_turn(rest, NOW, 12) and not HF.rest_turn(rest, NOW, 11)
    qs = [{"id": 11, "parched": 2}]
    assert HF.rest_done(rest, qs, NOW, CFG) == [] and "11" in rest
    qs = [{"id": 11, "parched": 0}]
    assert HF.rest_done(rest, qs, NOW, CFG) == [] and "11" in rest           # out only 100 ticks
    rest = {"11": NOW + 2 * DAY - 400}
    assert HF.rest_done(rest, qs, NOW, CFG) == [11] and not rest


@test("sheltered squads thirsty while hiding from a titan: only one goes out to eat")
def _():
    t = titan(can_reach_dwarves=True, distance_to_nearest_dwarf=10, y=135)
    qs = [sq(11, 10, sheltering=True, ai_orders=1, parched=3), sq(12, 10, sheltering=True, ai_orders=1, parched=2)]
    s = fort([t], qs)
    s["civ_alert"] = True
    m = Memory()
    props, notes = [], []
    PA._shelter_squads_rule(s, m, CFG, props, notes)
    rc = [p for p in props if p.action.get("clear")]
    assert len(rc) == 1 and rc[0].action["squad_id"] == 11, [(p.action, p.reason) for p in props]
    assert any("one at a time" in n for n in notes), notes


@test("squad_station_spot: of the chokes on the threat's path, the one on a level with drink")
def _():
    plan_ = {"danger": True, "candidates": [
        {"z": 98, "d_threat": 30, "drink": 0, "chokes": [
            {"x": 5, "y": 5, "z": 100, "to_shelter": 20, "width": 2, "from_src": 2},
            {"x": 6, "y": 6, "z": 99, "to_shelter": 15, "width": 2, "from_src": 5}]},
        {"z": 99, "d_threat": 40, "drink": 12}],
        "other_levels": [], "barracks": []}
    s = {"shelter_plan": plan_, "military": {"squads": []}}
    spot = PS.squad_station_spot(s, CFG)
    assert spot and spot["z"] == 99 and spot["drink"] is True and "drink on its level" in spot["why"], spot
    plan_["candidates"][1]["drink"] = 0
    spot = PS.squad_station_spot(s, CFG)
    assert spot["z"] == 100 and spot["drink"] is False, spot


# --- 7. the wiring --------------------------------------------------------------------------

@test("wiring: planner imports and calls, overseer note, config keys, the memory field")
def _():
    pl = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")
    for name in ("_destroyer_gate_rule", "_intruder_guard_rule", "_squad_matchup_filter", "_kill_hold_filter"):
        assert pl.count(name) >= 2, name
    ov = py_family_src("overseer")
    assert "note_thief_targets(state, memory, events)" in ov
    for k in ("one_enemy_gate_tiles", "kill_hold_ticks", "destroyer_wall_min_tiles", "post_rest_min_ticks"):
        assert k in PLANNER_CONFIG, k
    assert isinstance(Memory().holdfast, dict)
    assert isinstance(Memory.from_dict({"holdfast": {"kill": {}}}).holdfast, dict)


if __name__ == "__main__":
    finish()
