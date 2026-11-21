"""(r1g5) The alarm and the squads in a real threat (brain/planner_war_hold.py).

Built from the run of 15-16 Nov (0.105.55):
  * B y262 (R-B.md finding 4): Len Karaura (unit 15366), a lone axeman
    inside at x108 y149, the alarm up at tick 283203 and lowered at 283953
    "and a squad on them" with no squad sent; squad_trim and train (off
    duty) at 285462, one cycle after he was last in reach;
  * E y256-259 (R-CE.md finding 1): Hill Titan "Fishlobster", a fire
    breather inside, the alarm up 812 days, no squad ever sent;
  * C y255 (R-CE.md section 3): five squads sent at the Mountain Titan at
    tick 248529 and recalled at 248950 for "0.5x";
  * F y256 (R-F.md): training at 01:46:36, off duty 16 s later;
  * A y260 (R-AD.md): 22 of 57 soldiers armed, 68 steel bars, 220 swaps.

    python tests/test_r1_g5.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan, note_cycle, Proposal  # noqa: E402
from planner_core import abs_tick, _soldier_swap  # noqa: E402
import planner_war_hold as wh  # noqa: E402
import digest  # noqa: E402

CFG = dict(PLANNER_CONFIG)
DAY = 1200
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
OFF = {"type": "civ_alert", "on": False}
ON = {"type": "civ_alert", "on": True}


def sq(i, members=4, armed=0, power=3.0, **kw):
    q = {"id": i, "name": f"Squad {i}", "members": members, "size": 10, "leader": True, "orders": 0, "ai_orders": 0,
         "routine": "Staggered training",
         "power": {"power": power, "armed": armed, "melee_power": power, "ranged_power": 0}}
    q.update(kw)
    return q


def len_row(**kw):
    t = {"id": 15366, "name": 'Len Karaura "Heatdied", Human Axeman', "invader": True, "great_danger": False,
         "flier": False, "can_reach_dwarves": True, "size": 70000, "layer": "fort_levels",
         "distance_to_nearest_dwarf": 1, "levels_from_nearest_dwarf": 0, "pos": {"x": 108, "y": 149, "z": 166}}
    t.update(kw)
    return t


def fort(threats, squads, alert=False, tick=283203, inside=(), year=262, **extra) -> dict:
    s = copy.deepcopy(BASE)
    s["date"] = {"day": 13, "month": "Timber", "season": "autumn", "tick": tick, "year": year}
    s["others_on_map"]["threats"] = threats
    s["others_on_map"]["threats_that_can_reach_dwarves"] = sum(1 for t in threats if t.get("can_reach_dwarves") is True)
    s["military"]["squads"] = squads
    s["military"]["soldiers"] = sum(int(q.get("members") or 0) for q in squads)
    s["civ_alert"] = alert
    s["civ_alert_ready"] = True
    s["settings"]["attack_policy"] = "ordinary"
    s["entrances"]["intruders_inside"] = list(inside)
    s["entrances"]["scanned_tick"] = year * 403200 + tick - 100
    s.update(extra)
    return digest.normalize(s)


def at(s, tick):
    s = copy.deepcopy(s)
    s["date"]["tick"] = tick
    return s


def offs(props):
    return [p for p in props if p.action == OFF]


def by(props, rule=None, typ=None):
    return [p for p in props if (rule is None or p.rule == rule) and (typ is None or p.action.get("type") == typ)]


# --- (1) the lone intruder's alarm ----------------------------------------------------------

@test("B y262: Len inside, the alarm up 750 ticks, no squad's kill order names him: the alarm stays up "
      "(was: lowered 'and a squad on them')")
def _():
    s0 = fort([len_row()], [sq(185, 4, 0)], alert=True, tick=283203, inside=[15366])
    m = Memory(ai_alert_raised=True)
    note_cycle(s0, m)                                    # read as inside: the lone record begins
    s1 = at(s0, 283953)                                  # the run's stand-down cycle
    note_cycle(s1, m)
    p, notes = plan(s1, m)
    assert not offs(p), [x.reason for x in offs(p)]
    assert any("no squad's kill order names them" in n for n in notes), notes
    # a squad sent at him (its kill order names him): now it may come down
    s2 = copy.deepcopy(s1)
    s2["military"]["squads"][0].update(ai_orders=1, kill_ids=[15366])
    p2, _ = plan(s2, m)
    o = offs(p2)
    assert o and "a squad on them" in o[0].reason, [x.reason for x in p2 if x.rule == "threat_alert"]
    # a squad on someone else, or guarding the stair: not on him
    s3 = copy.deepcopy(s1)
    s3["military"]["squads"][0].update(ai_orders=1, kill_ids=[9999])
    assert not offs(plan(s3, m)[0])
    s4 = copy.deepcopy(s1)
    s4["military"]["squads"][0].update(ai_orders=1, kill_ids=[15366], guarding=True)
    assert not offs(plan(s4, m)[0])


@test("lone_hunted: every lone intruder named by an AI squad's kill order (not guarding, not in the shelter)")
def _():
    s = fort([len_row(), len_row(id=15367)], [sq(1, ai_orders=1, kill_ids=[15366]), sq(2)])
    assert not wh.lone_hunted(s, [15366, 15367])
    s["military"]["squads"][1].update(ai_orders=1, kill_ids=[15367])
    assert wh.lone_hunted(s, [15366, 15367])
    s["military"]["squads"][1]["sheltering"] = True
    assert not wh.lone_hunted(s, [15366, 15367])
    assert not wh.lone_hunted(s, [])


# --- (2) the alarm nobody fights ------------------------------------------------------------

def titan(**kw):
    t = {"id": 20001, "name": 'Fishlobster, Hill Titan', "invader": False, "great_danger": True, "flier": False,
         "fire_breather": True, "kinds": ["Titan"], "can_reach_dwarves": True, "size": 5000000,
         "layer": "fort_levels", "distance_to_nearest_dwarf": 0, "levels_from_nearest_dwarf": 0,
         "pos": {"x": 108, "y": 152, "z": 153}}
    t.update(kw)
    return t


def e_fort(days, squads=None, **kw):
    s = fort([titan(**kw)], squads if squads is not None else [sq(1, 4, 1, 4.0)], alert=True,
             tick=100000, year=257, inside=[20001])
    m = Memory(ai_alert_raised=True)
    m.alarm_gov = {"on": {"tick": abs_tick(s) - days * DAY, "cause": "reach", "key": "reach", "why": "1 threat(s)"}}
    return s, m


@test("E y256-259: the fire-spitting titan inside, no squad sent, the alarm up 31 days, a fight hopeless: the "
      "alarm comes down (was: up 812 days) and is not raised again for it")
def _():
    s, m = e_fort(20)
    assert not offs(plan(s, m)[0])                       # 20 days: not yet
    s, m = e_fort(31)
    note_cycle(s, m)
    p, notes = plan(s, m)
    o = offs(p)
    assert o and o[0].reason.startswith(wh.UNFOUGHT_WHY) and "hopeless" in o[0].reason, \
        [x.reason for x in p if x.rule == "threat_alert"]
    assert not by(p, "squad_attack")                     # no melee squad at a fire breather
    # lowered: the same titan does not raise it again; a new enemy does
    down = copy.deepcopy(s)
    down["civ_alert"] = False
    m.ai_alert_raised = False
    m.alarm_gov = {}
    note_cycle(down, m)
    p2, n2 = plan(down, m)
    assert not [x for x in p2 if x.action == ON], [x.reason for x in p2 if x.action == ON]
    assert any("lifted for them" in n for n in n2), n2
    more = copy.deepcopy(down)
    more["others_on_map"]["threats"].append(len_row(id=30001, name="goblin", distance_to_nearest_dwarf=30))
    more["others_on_map"]["threats_that_can_reach_dwarves"] = 2
    assert [x for x in plan(more, m)[0] if x.action == ON]


@test("long alarm: a web-spinning beast no melee squad may face, crossbows at 0.4x (short of even odds): after "
      "30 days every squad with anyone armed that may go at it goes (the all-out attack); the alarm stays")
def _():
    xb = sq(2, 6, 6, 20.0, ai_uniform="metal crossbow")
    xb["power"] = {"power": 20.0, "armed": 6, "melee_power": 0, "ranged_power": 20.0}
    melee = sq(1, 6, 6, 20.0)
    s, m = e_fort(31, [melee, xb], fire_breather=False, webs=True, name="Webspinner, Forgotten Beast",
                  kinds=["ForgottenBeast"], size=900000)
    uf = wh.unfought(s, m, CFG, [20001])
    assert uf["mode"] == "fight", uf
    p, notes = plan(s, m)
    a = by(p, "squad_attack")
    assert [x.action["squad_id"] for x in a if 20001 in x.action.get("kill", [])] == [2], [x.action for x in a]
    assert not offs(p)
    # the fight turned bad (a third of the soldiers lost): the alarm comes down
    later = copy.deepcopy(s)
    later["military"]["squads"][1].update(ai_orders=1, kill_ids=[20001], members=2)
    later["military"]["soldiers"] = 8
    later["date"]["tick"] += 300
    p2, _ = plan(later, m)
    o = offs(p2)
    assert o and "turned bad" in o[0].reason, [x.reason for x in p2 if x.rule == "threat_alert"]


@test("long alarm: never more than r1g5_alarm_hard_days, whoever is on it")
def _():
    s, m = e_fort(61, [sq(1, 6, 6, 20.0, ai_orders=1, kill_ids=[20001])], fire_breather=False)
    o = offs(plan(s, m)[0])
    assert o and "has stood 61 days" in o[0].reason, o


# --- (3) the squads left as they are while danger is about ----------------------------------

def b_quiet(tick=285462):
    """B at 09:32:31: Len out of reach for this one cycle, 4 soldiers, Militarism -60, 10 citizens."""
    q = sq(185, 4, 0)
    s = fort([], [q], alert=False, tick=tick)
    s["settings"]["traits"] = {"militarism": -60}
    s["dwarves"]["total"] = 10
    s["dwarves"]["adults"] = 10
    return s


@test("B y262, F y256: one cycle after the axeman was in reach (B 09:32:31): no squad_trim, no off duty "
      "(was: 2 soldiers trimmed and the squad sent off duty)")
def _():
    s = b_quiet()
    m = Memory()
    m.squads_trained = [185]
    quiet, _ = plan(s, m)
    trims = by(quiet, "squad_trim") + [x for x in by(quiet, "train") if "off duty" in str(x.action.get("routine")).lower()]
    assert trims, "the scenario must trim or rest the squad when all is quiet"
    m.last_threat_tick = abs_tick(s) - 1212                 # the cycle before (tick 284250)
    p, notes = plan(s, m)
    assert not by(p, "squad_trim"), [x.reason for x in by(p, "squad_trim")]
    assert not [x for x in by(p, "train") if "off duty" in str(x.action.get("routine")).lower()], by(p, "train")
    assert any("the squads are left as they are" in n for n in notes), notes


@test("war_hold_filter: off duty -> training still goes; training -> off duty, training -> training, trims and "
      "swaps are held while an enemy is inside")
def _():
    s = fort([], [sq(1, routine="Off duty"), sq(2, routine="Constant training")], inside=[15366])
    props = [Proposal("train", {"type": "squad_routine", "squad_id": 1, "routine": "Staggered training"}, "a", 2),
             Proposal("train", {"type": "squad_routine", "squad_id": 2, "routine": "Off duty"}, "b", 4),
             Proposal("train", {"type": "squad_routine", "squad_id": 2, "routine": "Staggered training"}, "c", 4),
             Proposal("squad_trim", {"type": "squad_trim", "count": 2}, "d", 5),
             Proposal("soldier_swap", {"type": "squad_swap", "unit_id": 5}, "e", 4),
             Proposal("drink", {"type": "work_order", "recipe": "brew_drink", "amount": 5}, "f", 1)]
    notes = []
    out = wh.war_hold_filter(s, Memory(), CFG, list(props), notes)
    assert [p.reason for p in out] == ["a", "f"], [p.reason for p in out]
    calm = fort([], [sq(1)])
    assert len(wh.war_hold_filter(calm, Memory(), CFG, list(props), [])) == len(props)


# --- (4) arm before drafting or swapping ----------------------------------------------------

def a_gear(on_duty=52, armed=22, steel=68, forges=1):
    return {"soldiers": on_duty, "on_duty": on_duty, "armed": armed, "armored": 27, "helmed": 15,
            "spare": {}, "bars": {"STEEL": steel, "IRON": 23}, "forges": forges}


@test("arm_first (A y260, B y262): unarmed soldiers on duty and bars to arm them: no drafting meanwhile; "
      "few unarmed, no bars, no forge, or off duty: drafting as before")
def _():
    rules_ = {"make_gear": True}
    s = fort([], [sq(1, 10, 2)], military_extra=None)
    s["military"]["gear"] = a_gear()
    assert "22 of the 52 soldiers on duty armed" in wh.arm_first(s, CFG, rules_)
    s["military"]["gear"] = a_gear(armed=50)
    assert wh.arm_first(s, CFG, rules_) == ""
    s["military"]["gear"] = a_gear(steel=5)
    assert wh.arm_first(s, CFG, rules_) == ""
    s["military"]["gear"] = a_gear(forges=0)
    assert wh.arm_first(s, CFG, rules_) == ""
    s["military"]["gear"] = a_gear(on_duty=0, armed=0)
    assert wh.arm_first(s, CFG, rules_) == ""
    s["military"]["gear"] = {**a_gear(on_duty=6, armed=0, steel=0), "bars": {"IRON": 52}}     # B: 6 unarmed, 52 iron
    assert "52 iron bars" in wh.arm_first(s, CFG, rules_)
    # held 56 days at most (note_cycle books since when)
    m = Memory()
    note_cycle(s, m)
    assert wh.arm_first(s, CFG, rules_, m)
    late = at(s, s["date"]["tick"] + 57 * DAY)
    note_cycle(late, m)
    assert wh.arm_first(late, CFG, rules_, m) == ""


@test("plan (B y262): the defence floor wants more soldiers, 6 on duty and none armed, 52 iron bars: no "
      "squad_fill, a weapons order instead")
def _():
    s = fort([], [sq(185, 6, 0, routine="Staggered training"), sq(186, 0, 0)], tick=200000)
    s["military"]["gear"] = {"soldiers": 6, "on_duty": 6, "armed": 0, "armored": 0, "helmed": 0, "spare": {},
                             "bars": {"IRON": 52}, "forges": 1, "squads_with_uniform": 2}
    s["military"]["uniform_templates"] = ["metal"]
    for q in s["military"]["squads"]:
        q["uniform"] = True
    m = Memory()
    m.defence_floor = {"peak": {"power": 300.0, "tick": abs_tick(s) - DAY, "why": "a titan"}}
    p, notes = plan(s, m)
    assert not by(p, "squad_fill") and not by(p, "squad_make"), [x.reason for x in by(p, "squad_fill")]
    assert any("armed first" in n and "before more soldiers are drafted" in n for n in notes), \
        [n for n in notes if "soldiers" in n][:5]
    arms = by(p, "arms")
    assert arms and "weapon" in arms[0].reason or arms and arms[0].action.get("recipe", "").endswith(
        ("axe", "sword", "spear", "mace", "hammer", "pick")), [x.action for x in arms]


@test("soldier_swap (A: 220 swaps, 22 of 57 armed): no swap while under 3/4 of the soldiers on duty are armed")
def _():
    s = fort([], [sq(1, 10, 2)])
    s["needs"] = {"keen_civilians": 30, "starved_soldiers": [{"id": 77, "name": "Erush", "unmet": ["Craft", "Pray"]}]}
    s["military"]["gear"] = a_gear(on_duty=10, armed=10)
    got = []
    _soldier_swap(s, CFG, got, Memory())
    assert got and got[0].action["type"] == "squad_swap", got
    s["military"]["gear"] = a_gear(on_duty=10, armed=4)
    got = []
    _soldier_swap(s, CFG, got, Memory())
    assert not got, got


# --- (5) a sent squad held ------------------------------------------------------------------

def c_titan(**kw):
    t = {"id": 16481, "name": '"Chantbeaches", Mountain Titan', "invader": False, "great_danger": True,
         "flier": False, "kinds": ["Titan"], "can_reach_dwarves": True, "size": 3000000, "layer": "upper_levels",
         "distance_to_nearest_dwarf": 30, "levels_from_nearest_dwarf": 0, "pos": {"x": 93, "y": 154, "z": 168}}
    t.update(kw)
    return t


def c_fort(members=9):
    # 5 x 2.6 against the titan's 26.6: about 0.5x, as the run read it
    squads = [sq(i, members, members, 2.6, ai_orders=1, kill_ids=[16481]) for i in (185, 208, 213, 216, 217)]
    return fort([c_titan()], squads, alert=True, tick=248950, year=255)


@test("C y255: five squads sent at the titan 421 ticks ago, the odds read 0.5x this cycle: not called back "
      "(was: recalled 12 s after being sent); a third of them lost: back they come")
def _():
    s = c_fort()
    m = Memory(ai_alert_raised=True)
    sent = at(s, 248529)
    note_cycle(sent, m)                                   # the kill orders booked at the send
    m.kill_sent_at = {str(q["id"]): abs_tick(sent) for q in s["military"]["squads"]}   # record(): the AI sent them
    note_cycle(s, m)
    p, notes = plan(s, m)
    rec = [x for x in p if x.rule == "squad_recall"]
    assert not rec, [(x.action, x.reason[:120]) for x in rec]
    # losing: each squad down from 9 to 5
    lose = copy.deepcopy(s)
    for q in lose["military"]["squads"]:
        q["members"] = 5
        q["power"]["armed"] = 5
    lose["military"]["soldiers"] = 25
    p2, _ = plan(lose, m)
    assert [x for x in p2 if x.rule == "squad_recall"], "a losing squad comes back"


@test("recall_hold: held a day from the AI's send, unless losing or hopeless; a squad it didn't send is not held")
def _():
    s = c_fort()
    m = Memory()
    q = s["military"]["squads"][0]
    assert wh.recall_hold(s, m, CFG, q, [c_titan()], 0.5) == ""          # not sent by the AI
    note_cycle(at(s, 248529), m)
    m.kill_sent_at = {str(q["id"]): abs_tick(at(s, 248529))}
    assert wh.recall_hold(s, m, CFG, q, [c_titan()], 0.5)
    assert wh.recall_hold(s, m, CFG, q, [c_titan()])                     # judged: 13 against 26.6
    assert wh.recall_hold(s, m, CFG, q, [c_titan()], 0.1) == ""          # hopeless
    assert wh.recall_hold(at(s, 248529 + DAY + 1), m, CFG, q, [c_titan()], 0.5) == ""   # a day on


if __name__ == "__main__":
    finish()
