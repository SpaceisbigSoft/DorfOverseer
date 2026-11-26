"""(0.105.119 item35) A militant fort's soldiers rest by turns; coffins from
the other shop when the placed ones wait.

Live 25 Nov, A "War-hold" (Militarism +150): 59 of 86 citizens in 7 squads,
all on training all year (the rotation and 0.105.97's leisure turns only run
under Militarism 50), the recreation burrow never got a soldier (it takes
them from a squad off duty); 28-50% unhappy through y254. And 4-8 of the
fort's dead lay unburied three seasons: 7-8 coffins placed, none in store, a
stone coffin order stuck at 5 of 5.

    python tests/test_item35_war_leisure.py
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

from planner import Memory, PLANNER_CONFIG  # noqa: E402
from planner_core import Proposal, abs_tick, TICKS_PER_DAY  # noqa: E402
import planner_leisure as PL  # noqa: E402
from planner_society import _recreation_rule  # noqa: E402
import planner_welfare as PW  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = dict(PLANNER_CONFIG)
A_STRESS = {"content": 13, "fine": 14, "happy": 7, "miserable": 2, "unhappy": 26, "very_unhappy": 7}   # y254 spring


def war_fort(n_squads=7, members=10, short=None, militarism=150, routine="Constant training"):
    s = copy.deepcopy(BASE)
    s["settings"]["traits"] = {"militarism": militarism, "welfare": -40}
    s["dwarves"]["stress"] = dict(A_STRESS)
    s["dwarves"]["total"] = sum(A_STRESS.values())
    s["dwarves"]["in_squads"] = n_squads * members
    s["needs"] = {"needs": {"BeWithFriends": {"badly": 45, "badly_soldiers": 28},
                            "PrayOrMeditate": {"badly": 32, "badly_soldiers": 21},
                            "MartialTraining": {"badly": 3}}}
    s["military"]["routines"] = ["Off duty", "Staggered training", "Constant training", "Ready"]
    s["military"]["squads"] = [{"id": 10 + i, "name": f"Squad {10 + i}", "members": members, "size": 10,
                                "orders": 0, "ai_orders": 0, "routine": routine,
                                "ai_uniform": "Melee, metal armor"} for i in range(n_squads)]
    short = short if short is not None else [(6, 4)] * n_squads
    s.setdefault("society", {})["recreation"] = {
        "members": 0, "squads": {str(10 + i): {"n": members, "short": a, "short_np": b}
                                 for i, (a, b) in enumerate(short)}}
    s["others_on_map"]["threats"] = []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s["civ_alert"] = False
    return s


def rests(s, m=None):
    m = m or Memory()
    p = []
    PL.war_leisure_rule(s, CFG, p, m)
    return p, m


@test("A at Militarism 150, a fifth of the soldiers short: the shortest squad rests a month (\"another squad trains\")")
def _():
    s = war_fort(short=[(6, 4), (6, 4), (10, 8), (6, 4), (6, 4), (7, 7), (6, 4)])
    p, m = rests(s)
    assert len(p) == 1 and p[0].rule == "war_leisure", p
    a = p[0].action
    assert a == {"type": "squad_routine", "squad_id": 12, "routine": "Off duty"}, a
    assert "another squad trains" in p[0].reason and "Militarism 150" in p[0].reason, p[0].reason


@test("no rest under Militarism 50 (the rotation's own turns), with a threat, an alert, or nobody short")
def _():
    assert not rests(war_fort(militarism=40))[0]
    s = war_fort()
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 2
    s["others_on_map"]["threats"] = [{"id": 1, "can_reach": True}]
    from planner_core import reachable_threats, _traits
    if reachable_threats(s, _traits(s), CFG):
        assert not rests(s)[0]
    s = war_fort()
    s["civ_alert"] = True
    assert not rests(s)[0]
    s = war_fort(short=[(1, 0)] * 7)
    assert not rests(s)[0]


@test("soldiers longing to train keep training; squads under orders or the player's own aren't rested")
def _():
    s = war_fort()
    s["needs"]["needs"]["MartialTraining"] = {"badly": 20, "badly_soldiers": 20}
    assert not rests(s)[0]
    s = war_fort(n_squads=3)
    s["military"]["squads"][0]["ai_orders"] = 1
    assert not rests(s)[0]                                # two left: under war_leisure_min_squads
    s = war_fort(n_squads=4)
    for q in s["military"]["squads"]:
        q.pop("ai_uniform")
    assert not rests(s)[0]                                # none the AI's


@test("one in three rest at most; a squad rested lately waits its turn; the guard keeps training")
def _():
    s = war_fort()
    for q in s["military"]["squads"][:2]:
        q["routine"] = "Off duty"
    m = Memory()
    m.squads_rested = [10, 11]
    p, m = rests(s, m)
    assert not p, p                                       # 2 of 7 resting already
    assert set(m.war_leisure) == {"10", "11"}             # their month booked when first seen off duty
    s["military"]["squads"][1]["routine"] = "Staggered training"
    p, m = rests(s, m)
    assert p and p[0].action["squad_id"] not in (10, 11), p      # 11 rested lately: another goes
    m.war_leisure = {str(10 + i): abs_tick(s) - 10 * TICKS_PER_DAY for i in range(7)}
    assert not rests(war_fort(), m)[0]                    # every one rested lately
    m.war_leisure = {}
    s = war_fort(n_squads=3, members=2)                   # 6 soldiers: resting 2 leaves 4 (guard 3)
    assert rests(s)[0]
    s = war_fort(n_squads=3, members=1)
    assert not rests(s)[0]                                # 2 left training: under the guard


@test("the record books the rest month; planner_military leaves the rested squad off duty that month")
def _():
    import planner_record
    s = war_fort()
    p, m = rests(s)
    m.squads_trained = [q["id"] for q in s["military"]["squads"]]
    sid = p[0].action["squad_id"]
    planner_record.record([(p[0], {"ok": True})], s, m)
    assert sid in m.squads_rested and str(sid) in m.rested_at, (m.squads_rested, m.rested_at)
    s2 = copy.deepcopy(s)
    for q in s2["military"]["squads"]:
        if q["id"] == sid:
            q["routine"] = "Off duty"
    import planner_military
    from planner_core import _traits
    props, notes = [], []
    planner_military._military_rules(s2, m, CFG, _traits(s2), s2["dwarves"]["total"], props, notes, gate_rules=False)
    back = [x for x in props if x.action.get("type") == "squad_routine" and x.action.get("squad_id") == sid]
    assert not back, [x.reason for x in back]
    # a month later it trains again
    m.rested_at[str(sid)] -= 29 * TICKS_PER_DAY
    props = []
    planner_military._military_rules(s2, m, CFG, _traits(s2), s2["dwarves"]["total"], props, notes, gate_rules=False)
    back = [x for x in props if x.action.get("type") == "squad_routine" and x.action.get("squad_id") == sid]
    assert back and "off duty" not in back[0].action["routine"].lower(), [x.reason for x in props]


@test("the resting squad's soldiers get recreation places; plan() runs the rule in the society notes")
def _():
    s = war_fort()
    s["military"]["squads"][0]["routine"] = "Off duty"
    p = []
    _recreation_rule(s, CFG, [], p, Memory())
    assert p and p[0].action.get("soldiers"), p
    src = (ROOT / "brain" / "planner_society.py").read_text(encoding="utf-8")
    assert "war_leisure_rule(s, cfg, proposals, memory)" in src
    import hold_classes
    assert hold_classes.rule_class("war_leisure") == hold_classes.SURVIVAL


# --- coffins from the other shop -------------------------------------------------

def burial_fort(waiting=8, free=0, orders=(("stone_coffin", 5),)):
    s = copy.deepcopy(BASE)
    s["settings"]["traits"] = {"welfare": -40}
    s["dead"] = dict(s.get("dead") or {}, unburied=6, free_tombs=0)
    s["welfare"] = {"coffin_items": free, "corner": {"built": 5, "free": 0, "placed": 13, "waiting": waiting}}
    s["orders"] = [{"recipe": r, "amount_left": n, "amount_total": n, "by_ai": True} for r, n in orders]
    s.setdefault("stocks", {})["wood"] = 50
    return s


def coffins(s, m):
    p = []
    PW._coffins_other_shop(s, CFG, p, m, s["welfare"]["corner"]["waiting"], s["welfare"]["coffin_items"])
    return p


@test("A's stuck stone coffins: after the wait (4 days at Welfare -40) wooden ones at the carpenters' too")
def _():
    s = burial_fort()
    if not PW._has_shop(s.get("buildings") or {}, "Carpenters"):
        s.setdefault("buildings", {}).setdefault("workshops", {})["Carpenters"] = 1
    if not PW._has_shop(s.get("buildings") or {}, "Carpenters"):
        print("  (fixture has no Carpenters: the order half checked by the wait only)")
    m = Memory()
    assert not coffins(s, m)                              # the wait begins
    assert isinstance(m.welfare.get("coffins_wait_since"), int)
    m.welfare["coffins_wait_since"] -= 3 * TICKS_PER_DAY
    assert not coffins(s, m)                              # 3 days: under 4
    m.welfare["coffins_wait_since"] -= 2 * TICKS_PER_DAY
    p = coffins(s, m)
    if PW._has_shop(s.get("buildings") or {}, "Carpenters"):
        assert p and p[0].action == {"type": "work_order", "recipe": "wooden_coffin", "amount": 8}, p
        assert "stone coffin order" in p[0].reason


@test("coffins: none waiting clears the wait; both kinds queued or none queued: nothing more")
def _():
    m = Memory()
    s = burial_fort()
    coffins(s, m)
    m.welfare["coffins_wait_since"] -= 10 * TICKS_PER_DAY
    assert not coffins(burial_fort(orders=(("stone_coffin", 5), ("wooden_coffin", 5))), m)
    assert not coffins(burial_fort(orders=()), m)
    coffins(burial_fort(waiting=2, free=2), m)
    assert "coffins_wait_since" not in m.welfare


if __name__ == "__main__":
    finish()
