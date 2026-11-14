"""(0.105.35, group mil) Nothing waits for the player: the military, army and
threats rules act where they asked the player before (a shelter made, a
squad sent, a forge built, weapons made, the citizens called up from the
caverns, the entrances mapped again), and keep a Needs you only for what the
game won't let the AI do, saying what the AI does meanwhile. Fake reports,
no Lua.

    python tests/test_r35_mil.py
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

from planner import Memory, plan, PLANNER_CONFIG  # noqa: E402
import planner_military as pm  # noqa: E402
import planner_threats as pt  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def you(notes):
    return [n for n in notes if isinstance(n, str) and n.startswith("[you] ")]


def hazards(s, memory=None, rules_=None):
    props, notes = [], []
    pm._hazard_rules(s, memory if memory is not None else Memory(), CFG, props, notes,
                     rules_ if rules_ is not None else pm.player_rules(s))
    return props, notes


@test("a fire near and no alarm burrow: the AI makes its shelter at once (not Needs you)")
def _():
    s = fort()
    s["hazards"] = {"fire_near": 3}
    s["civ_alert"], s["civ_alert_ready"] = False, False
    props, notes = hazards(s)
    sh = [p for p in props if p.action == {"type": "setup_shelter"}]
    assert sh and sh[0].priority == 0 and sh[0].rule == "shelter", props
    assert not you(notes), notes
    # the player's Rules switch off: said, the switch respected
    s["settings"]["alert_shelter"] = False
    props, notes = hazards(s)
    assert not [p for p in props if p.action == {"type": "setup_shelter"}] and not you(notes), notes
    assert any("off on the Rules tab" in n for n in notes), notes
    # DF refused the AI's burrow twice, just now: (0.105.36) said as a note with
    # what the AI does meanwhile and when it tries again (was a Needs you for good)
    s["settings"]["alert_shelter"] = True
    props, notes = hazards(s, Memory(shelter_attempts=2, shelter_tick=pm.abs_tick(s)))
    line = [n for n in notes if "refused" in n]
    assert not you(notes) and line and "meanwhile" in line[0] and "tried again in 3 day(s)" in line[0], notes
    assert not [p for p in props if p.action == {"type": "setup_shelter"}], props


@test("a berserk dwarf, no squad free: a busy squad takes them on too, else the best with anyone armed; else said")
def _():
    s = fort()
    s["civ_alert"] = True
    s["hazards"] = {"berserk": [{"id": 900, "name": "Urist"}]}
    q1, q2 = s["military"]["squads"][:2]
    q1.update(members=8, power={"armed": 6}, ai_orders=1, kill_ids=[500, 501])
    q2.update(members=8, power={"armed": 0}, ai_orders=0)
    props, notes = hazards(s)
    a = [p for p in props if p.rule == "squad_attack"]
    assert a and a[0].action["squad_id"] == q1["id"] and set(a[0].action["kill"]) >= {900, 500, 501}, props
    assert not you(notes), notes
    q1["kill_ids"] = [500, 900]                                    # already on them: said, no new order
    props, notes = hazards(s)
    assert not [p for p in props if p.rule == "squad_attack"] and any("is after them" in n for n in notes)
    # nobody with enough armed: the best squad with anyone armed
    q1.update(ai_orders=0, power={"armed": 1}, kill_ids=None)
    props, notes = hazards(s)
    a = [p for p in props if p.rule == "squad_attack"]
    assert a and a[0].action == {"type": "squad_orders", "squad_id": q1["id"], "kill": [900]}, props
    # nobody armed at all: said, not asked
    q1["power"] = {"armed": 0}
    props, notes = hazards(s)
    assert not [p for p in props if p.rule == "squad_attack"] and not you(notes), notes
    assert any("no squad has anyone armed" in n for n in notes), notes


@test("dwarves in magma: a plain note; in deep water: the floodgate shut and said, else kept with what the AI does")
def _():
    s = fort()
    s["civ_alert"] = True
    s["hazards"] = {"burning": [{"name": "Kib"}]}
    props, notes = hazards(s)
    assert not you(notes) and any("in magma" in n for n in notes), notes
    s["hazards"] = {"wet": [{"name": "A"}, {"name": "B"}, {"name": "C"}, {"name": "D"}, {"name": "E"}]}
    s.setdefault("water", {})["cistern_status"] = {"gate": "open"}
    props, notes = hazards(s)
    assert [p for p in props if p.action == {"type": "cistern_step", "shut": True}] and not you(notes), notes
    s["water"]["cistern_status"] = {"gate": "closed"}
    props, notes = hazards(s)
    assert len(you(notes)) == 1 and "meanwhile" in you(notes)[0] and "doesn't say where" in you(notes)[0], notes


@test("a lone intruder inside, no squad with 3+ armed: the best squad with anyone armed goes")
def _():
    squads = [{"id": 1, "members": 8, "power": {"armed": 0}}, {"id": 2, "members": 5, "power": {"armed": 2}}]
    rows = {7: {"name": "Trustdaub"}}
    props, notes = [], []
    pm._lone_squad(fort(), Memory(), CFG, squads, [7], rows, props, notes)
    assert props and props[0].action == {"type": "squad_orders", "squad_id": 2, "kill": [7]}, props
    assert not you(notes)
    squads[1]["power"]["armed"] = 0
    props, notes = [], []
    pm._lone_squad(fort(), Memory(), CFG, squads, [7], rows, props, notes)
    assert not props and not you(notes) and any("no squad has anyone armed" in n for n in notes), notes


@test("a thief in the fort and no squad with enough armed free: the best free one with anyone armed")
def _():
    s = fort()
    for q in s["military"]["squads"]:
        q.update(members=6, power={"armed": 0}, ai_orders=0)
    s["military"]["squads"][1]["power"] = {"armed": 1}
    t = {"thieves": {"list": [{"id": 77, "name": "Snatch", "kind": "goblin", "inside": True}], "seen_total": 1}}
    props, notes = [], []
    pt._thieves(s, CFG, t, Memory(), props, notes)
    a = [p for p in props if p.rule == "squad_attack"]
    assert a and a[0].action == {"type": "squad_orders", "squad_id": s["military"]["squads"][1]["id"], "kill": [77]}, props


def cave(**kw):
    s = fort()
    s["threats"] = {"sealed": {}}
    s["deep"] = {"caverns": [{"name": "Cavern1", "discovered": True, "open": True, "z_top": 120, "z_bottom": 110}],
                 "dangers": [{"id": 50, "name": "Ozkak", "kind": "forgotten beast", "layer": "Cavern1"}],
                 "cursed": []}
    s.update(kw)
    return s


@test("a cavern beast, the fort open to the caverns and no door known: the entrances mapped again; kept once fresh")
def _():
    s = cave()
    s["entrances"]["scanned_tick"] = pm.abs_tick(s) - 5 * 1200
    props, notes = [], []
    pt._cavern_beasts(s, CFG, Memory(), s["threats"], pt.threat_rules_of(s), props, notes)
    sc = [p for p in props if p.rule == "cavern_scan"]
    assert sc and sc[0].action == {"type": "scan_entrances"}, props
    assert not you(notes), notes
    s["entrances"]["scanned_tick"] = pm.abs_tick(s) - 100
    props, notes = [], []
    pt._cavern_beasts(s, CFG, Memory(), s["threats"], pt.threat_rules_of(s), props, notes)
    assert not [p for p in props if p.rule == "cavern_scan"], props
    # (item7) a fresh, whole map with no cavern opening: the fort's own ground
    # has no way down, said (no Needs you, no seal the bridge must refuse)
    assert not you(notes) and any("no way down" in n for n in notes), notes
    assert not [p for p in props if p.rule == "seal_cavern"], props
    # a map cut short at its limit can't say so: put to the player as before
    s["entrances"]["inside_tiles"] = 250000
    props, notes = [], []
    pt._cavern_beasts(s, CFG, Memory(), s["threats"], pt.threat_rules_of(s), props, notes)
    assert len(you(notes)) == 1 and "meanwhile" in you(notes)[0], notes


@test("citizens down in the caverns with a beast about: the alarm calls them up, and an AI 'all clear' is held")
def _():
    s = cave()
    s["threats"]["cavern_citizens"] = {"n": 1, "list": [{"name": "Kib", "x": 1, "y": 2, "z": 3}]}
    s["civ_alert"], s["civ_alert_ready"] = True, True
    props = [pm.Proposal("threat_alert", {"type": "civ_alert", "on": False}, "all clear", 0)]
    notes = []
    pt._cavern_beasts(s, CFG, Memory(), s["threats"], pt.threat_rules_of(s), props, notes)
    assert not [p for p in props if p.action == {"type": "civ_alert", "on": False}], props
    assert not you(notes) and any("calls them up" in n for n in notes), notes
    s["civ_alert"], s["civ_alert_ready"] = False, False
    props, notes = [], []
    pt._cavern_beasts(s, CFG, Memory(), s["threats"], pt.threat_rules_of(s), props, notes)
    assert [p for p in props if p.action == {"type": "setup_shelter"}] and not you(notes), (props, notes)


@test("the threat alarm held its longest: let down, said, not put to the player")
def _():
    s = fort()
    s["civ_alert"] = True
    s["threats"] = {"undead": {"list": [{"name": "zombie", "can_reach_dwarves": True, "distance": 3}]}}
    m = Memory()
    m.threat_alarm = {"since": pm.abs_tick(s) - 40 * 1200, "why": "x"}
    props, notes = [], []
    pt._threat_rules(s, m, CFG, props, notes)
    assert not you(notes) and any("no longer holds the alarm" in n for n in notes), notes


@test("unreachable weapons while twice as many lie spare: no more made, said")
def _():
    s = fort()
    s["military"]["gear"] = {"soldiers": 20, "on_duty": 20, "armed": 10, "weapon_gaps": 6, "squads": 2,
                             "squads_with_uniform": 2, "weapon_gaps_why": {"unreachable": 4},
                             "spare_weapons": {"ITEM_WEAPON_AXE_BATTLE": 9}, "bars": {"IRON": 200}, "forges": 1}
    s["orders"] = []
    props, notes = plan(s, Memory())
    assert not [p for p in props if p.rule == "gear_fix_order"], props
    assert any("can't get to the free weapons" in n and "no more made" in n for n in notes), notes
    assert not [n for n in you(notes) if "free weapons" in n], notes


@test("squads without a uniform and gear making off on the Rules tab: said, not asked")
def _():
    s = fort()
    s["military"]["gear"] = {"soldiers": 10, "squads": 2, "squads_with_uniform": 0}
    s["settings"]["make_gear"] = False
    notes = plan(s, Memory())[1]
    assert not [n for n in you(notes) if "uniform" in n], notes
    assert any("no uniform" in n and "off on the Rules tab" in n for n in notes), notes


@test("no military office free for another squad: said with the game's reason, not asked")
def _():
    from planner_core import refusal_key, Proposal
    s = fort()
    for q in s["military"]["squads"]:
        q.update(size=10, members=10)
    s["settings"]["traits"] = dict(s["settings"].get("traits") or {}, militarism=200)
    m = Memory()
    m.refusals = {refusal_key(Proposal("squad_make", {"type": "make_squad"}, "", 3)):
                  {"why": "no military office is free to lead a new squad (no militia commander to appoint captains)"}}
    notes = plan(s, m)[1]
    assert not [n for n in you(notes) if "military office" in n], notes
    said = [n for n in notes if "no military office is free" in n]
    assert said and "no militia commander" in said[0], notes


finish()
