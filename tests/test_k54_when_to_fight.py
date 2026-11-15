"""(0.105.54, builder 42) When to fight: the player's "fight when roughly
even". The sortie bar is about even odds (planner_matchup.fight_bar,
`fight_even_ratio`), a clear win only against a fire breather (crossbows
only) or abilities the AI can't read; a strike at an opening below even odds
against the whole (a group apart, a wounded or retreating enemy); an
all-out attack once the wait is over (a siege of `siege_wait_max_days`, a
shelter short of drink or food, thirst deaths, the unhappy share rising, an
enemy inside); the losses guard (a third lost, half wounded) still calls the
squads back, and they go again when the odds return.

    python tests/test_k54_when_to_fight.py
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
from planner import Memory, PLANNER_CONFIG, plan, note_cycle  # noqa: E402
from planner_core import abs_tick, wild_pack  # noqa: E402
import planner_holdfast as HF  # noqa: E402
import planner_matchup as PM  # noqa: E402
from planner_military import fight_or_hide  # noqa: E402
import digest  # noqa: E402

CFG = dict(PLANNER_CONFIG)
DAY = 1200
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def goblin(i=8000, x=60, y=60, **kw):
    t = {"id": i, "name": "goblin", "invader": True, "great_danger": False, "flier": False, "size": 60000,
         "can_reach_dwarves": True, "layer": "upper_levels", "distance_to_nearest_dwarf": 40,
         "levels_from_nearest_dwarf": 0, "pos": {"x": x, "y": y, "z": 170}}
    t.update(kw)
    return t


def titan(i=6001, **kw):
    t = {"id": i, "name": "a titan", "great_danger": True, "kinds": ["Titan"], "size": 9000000,
         "can_reach_dwarves": True, "layer": "upper_levels", "distance_to_nearest_dwarf": 150,
         "levels_from_nearest_dwarf": 0, "pos": {"x": 10, "y": 10, "z": 170}}
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


def attacks(props):
    return [p for p in props if p.rule == "squad_attack"]


def sent(props):
    return sorted(p.action["squad_id"] for p in attacks(props))


def recalled(props) -> set:
    out = set()
    for p in props:
        if p.rule != "squad_recall":
            continue
        a = p.action
        if a.get("type") == "squad_orders" and a.get("clear"):
            out.add(a.get("squad_id"))
        out.update(a.get("squads") or [])
    return out


def siege_since(m, s, days_ago, unhappy=None):
    now = abs_tick(s)
    m.holdfast["siege"] = {"since": now - int(days_ago * DAY), "last": now, "unhappy": unhappy}


# --- the bar ---------------------------------------------------------------------------------

@test("fight_bar: goblins and a beast whose facts are read: about even odds; a fire breather: a clear win, "
      "crossbows only; abilities the AI can't read: a clear win; a flier: crossbows")
def _():
    assert PM.fight_bar(goblin(), CFG)["bar"] == 1.0
    assert "even" in PM.fight_bar(goblin(), CFG)["why"]
    beast = titan(kinds=["ForgottenBeast"], abilities=1, facts=1, breath=["web"])
    assert PM.fight_bar(beast, CFG)["bar"] == 1.0
    fire = PM.fight_bar(titan(fire_breather=True, facts=1, breath=["fire"]), CFG)
    assert fire["bar"] == 2.0 and fire["ranged_only"] and "never melee" in fire["why"], fire
    unread = PM.fight_bar(titan(kinds=["ForgottenBeast"], abilities=2), CFG)          # an older bridge's row
    assert unread["bar"] == 2.0 and "can't be read" in unread["why"], unread
    assert PM.fight_bar(titan(abilities=1, facts=1, breath=["other"]), CFG)["bar"] == 2.0
    fly = PM.fight_bar(goblin(flier=True), CFG)
    assert fly["bar"] == 1.0 and fly["ranged_only"], fly
    # a mixed group: the strictest
    assert PM.fight_bar([goblin(), titan(fire_breather=True)], CFG)["bar"] == 2.0


@test("strike_bar: all wounded or falling back lowers the bar (x0.8); one hale among them, or a fire breather: not")
def _():
    hurt = goblin(blood_lost=0.4)
    bar, why = PM.strike_bar([hurt, goblin(8001, wounds=8)], CFG)
    assert abs(bar - 0.8) < 1e-9 and "wounded" in why, (bar, why)
    assert PM.strike_bar([hurt, goblin(8001)], CFG)[0] == 1.0
    bar, why = PM.strike_bar([goblin(8001)], CFG, retreating={8001})
    assert abs(bar - 0.8) < 1e-9 and "falling back" in why, why
    assert PM.strike_bar([titan(fire_breather=True, blood_lost=0.5)], CFG)[0] == 2.0


@test("clusters: threats grouped by distance (a level counts 3); the largest is the main body, the rest apart")
def _():
    body = [goblin(8000 + i, x=60 + i, y=60) for i in range(10)]
    strag = [goblin(8100, x=120, y=60), goblin(8101, x=122, y=61)]
    lone = goblin(8200, x=60, y=60, pos={"x": 60, "y": 60, "z": 160})      # 10 levels down: 30 away
    gs = PM.clusters(body + strag + [lone], 15)
    assert [len(g) for g in gs] == [10, 2, 1], [len(g) for g in gs]
    apart = PM.groups_apart(body + strag + [lone], CFG)
    assert {t["id"] for g in apart for t in g} == {8100, 8101, 8200}
    assert PM.groups_apart(body, CFG) == []
    nopos = goblin(8300)
    del nopos["pos"]
    assert len(PM.clusters(body + [nopos], 15)) == 1                         # where it is unknown: the main body


# --- the sortie at about even odds -------------------------------------------------------------

@test("even odds: ten goblins (100) and one squad of 110: it goes (the 2x bar kept it home); the note says why")
def _():
    s = fort([goblin(8000 + i, x=60 + i) for i in range(10)], [sq(10, 110), sq(11, 40)])
    props, notes = plan(s, Memory())
    assert sent(props) == [10], (sent(props), [n for n in notes if "goblin" in n])
    assert "even odds" in attacks(props)[0].reason, attacks(props)[0].reason


@test("even odds short: 20 goblins (200) and squads of 120: no sortie, said with the bar's reason")
def _():
    s = fort([goblin(8000 + i, x=60 + i % 10, y=60 + i // 10) for i in range(20)], [sq(10, 70), sq(11, 50)])
    m = Memory()
    note_cycle(s, m)
    props, notes = plan(s, m)
    assert not attacks(props), sent(props)
    assert any("no sortie" in n and "even odds" in n for n in notes), [n for n in notes if "enem" in n]


# --- openings ----------------------------------------------------------------------------------

@test("opening: 20 goblins and 3 stragglers 60 tiles behind; squads too weak for all: a strike at the stragglers "
      "only, said; the squads already on them keep them and no more are sent")
def _():
    body = [goblin(8000 + i, x=60 + i % 10, y=60 + i // 10) for i in range(20)]
    strag = [goblin(8100 + i, x=130 + i, y=60) for i in range(3)]
    s = fort(body + strag, [sq(10, 70), sq(11, 50)])
    m = Memory()
    note_cycle(s, m)
    props, notes = plan(s, m)
    att = attacks(props)
    assert att and all(sorted(p.action["kill"]) == [8100, 8101, 8102] for p in att), [p.action for p in att]
    assert [p.action["squad_id"] for p in att] == [10], [p.action for p in att]       # 70 clears 30 alone
    assert "apart from the main body" in att[0].reason, att[0].reason
    # next cycle: the squad is out on them: kept, nobody else sent
    s2 = fort(body + strag, [sq(10, 70, ai_orders=1, orders=1, kill_ids=[8100, 8101, 8102]), sq(11, 50)])
    note_cycle(s2, m)
    props, notes = plan(s2, m)
    assert 11 not in sent(props) and 10 not in recalled(props), (sent(props), recalled(props))


@test("opening: a wounded rearguard is struck at below even odds (x0.8); hale, not")
def _():
    body = [goblin(8000 + i, x=60 + i % 10, y=60 + i // 10) for i in range(20)]
    rear = [goblin(8100 + i, x=130 + i, y=60) for i in range(4)]                     # need 40
    s = fort(body + rear, [sq(10, 34), sq(11, 1)])                                   # 0.85x of them
    m = Memory()
    note_cycle(s, m)
    assert 10 not in sent(plan(s, m)[0])
    hurt = [dict(t, blood_lost=0.5) for t in rear]
    s = fort(body + hurt, [sq(10, 34), sq(11, 1)])
    note_cycle(s, m)
    props, _ = plan(s, m)
    att = [p for p in attacks(props) if p.action["squad_id"] == 10]
    assert att and sorted(att[0].action["kill"]) == [8100, 8101, 8102, 8103], [p.action for p in attacks(props)]
    assert "wounded" in att[0].reason, att[0].reason


@test("falling back: an enemy farther from the dwarves than last cycle (note_siege's record) lowers the bar")
def _():
    m = Memory()
    s = fort([goblin(distance_to_nearest_dwarf=20)], [])
    HF.note_holdfast_cycle(s, m, CFG)
    s2 = fort([goblin(distance_to_nearest_dwarf=30)], [])
    s2["date"] = dict(s2["date"], tick=s2["date"]["tick"] + 100)
    s2 = digest.normalize(s2)
    HF.note_holdfast_cycle(s2, m, CFG)
    assert HF.retreating_ids(m, CFG) == {8000}, m.holdfast.get("dist")


# --- the wait's end ----------------------------------------------------------------------------

@test("bookkeeping: a siege's start and its unhappy share kept while it lasts; gone after half a day's quiet")
def _():
    m = Memory()
    s = fort([goblin()], [])
    HF.note_holdfast_cycle(s, m, CFG)
    sg = m.holdfast["siege"]
    t0 = abs_tick(s)
    assert sg["since"] == t0 and sg["last"] == t0 and "unhappy" in sg, sg
    later = copy.deepcopy(s)
    later["date"] = dict(later["date"], tick=later["date"]["tick"] + 400)
    HF.note_holdfast_cycle(digest.normalize(later), m, CFG)
    assert m.holdfast["siege"]["since"] == t0
    quiet = fort([], [])
    quiet["date"] = dict(quiet["date"], tick=quiet["date"]["tick"] + 1200)
    HF.note_holdfast_cycle(digest.normalize(quiet), m, CFG)
    assert "siege" not in m.holdfast
    thief = fort([goblin(thief="snatcher")], [])
    m2 = Memory()
    HF.note_holdfast_cycle(thief, m2, CFG)
    assert "siege" not in m2.holdfast                                   # a thief is no siege


@test("all-out: a siege of 4 days (20 goblins, squads 0.6x): every squad goes, the militia too, said; at 1 day: "
      "no sortie; under all_out_min_ratio: still none, said")
def _():
    gobs = [goblin(8000 + i, x=60 + i % 10, y=60 + i // 10) for i in range(20)]
    squads = [sq(10, 70), sq(11, 50), sq(12, 5, members=2)]                # 12: militia (2 of the 3 needed)
    s = fort(gobs, squads)
    m = Memory()
    note_cycle(s, m)
    siege_since(m, s, 1)
    assert not attacks(plan(s, m)[0])
    siege_since(m, s, 4.5)
    props, notes = plan(s, m)
    assert sent(props) == [10, 11, 12], (sent(props), [n for n in notes if "enem" in n])
    assert all("all-out" in p.reason and "lasted" in p.reason for p in attacks(props)), attacks(props)[0].reason
    weak = fort(gobs, [sq(10, 20), sq(11, 10)])                             # 0.15x
    note_cycle(weak, m)
    siege_since(m, weak, 5)
    props, notes = plan(weak, m)
    assert not attacks(props) and any("the wait is over" in n for n in notes), [n for n in notes if "enem" in n]


@test("all-out: a shelter short of drink, thirst deaths during the siege, the unhappy share risen: each ends the "
      "wait (planner_matchup.all_out)")
def _():
    s = fort([goblin()], [], alert=True)
    m = Memory()
    siege_since(m, s, 0.5, unhappy=0.1)
    assert PM.all_out(s, m, CFG) == ""
    m.shelter_supply = {"tick": abs_tick(s), "drink_short": "drink for 3 of 40"}
    assert "short" in PM.all_out(s, m, CFG)
    m.shelter_supply = {}
    s["thirst"] = {"deaths": [{"id": 5, "tick": abs_tick(s) - 100}, {"id": 6, "tick": abs_tick(s) - 5 * DAY}]}
    assert PM.all_out(s, m, CFG) == "1 citizen(s) died of thirst during the siege"
    s["thirst"] = {}
    s["dwarves"]["stress"] = {"miserable": 5, "very_unhappy": 5, "unhappy": 5, "fine": 15}       # 50%
    assert "unhappy share rose" in PM.all_out(s, m, CFG)
    m.holdfast["siege"]["unhappy"] = 0.45
    assert PM.all_out(s, m, CFG) == ""
    assert PM.all_out(s, Memory(), CFG) == ""                                # no siege: no wait to end


@test("all-out: great dangers too (a titan at 0.5x after the wait: the squads go, said); a fire breather never")
def _():
    t = titan()
    s = fort([t], [sq(10, 15), sq(11, 15)])
    m = Memory()
    need = PM.judge([t], s["military"]["squads"])["need"]
    assert 0.25 < 30 / need < 1.0, need
    fight, why = fight_or_hide(s, m, CFG, [t], s["military"]["squads"])
    assert not fight
    siege_since(m, s, 5)
    fight, why = fight_or_hide(s, m, CFG, [t], s["military"]["squads"])
    assert fight and "all-out" in why, why
    fire = fort([titan(fire_breather=True)], [sq(10, 15), sq(11, 15)])
    note_cycle(fire, m)
    siege_since(m, fire, 5)
    props, _ = plan(fire, m)
    assert not attacks(props), [p.action for p in attacks(props)]


@test("great danger at about even odds: a titan at 1.2x is fought (the 2x bar hid from it); a wounded one at "
      "0.85x too")
def _():
    t = titan()
    need = PM.judge([t], [sq(1, 1)])["need"]
    s = fort([t], [sq(10, need * 0.6), sq(11, need * 0.6)])
    fight, why = fight_or_hide(s, Memory(), CFG, [t], s["military"]["squads"])
    assert fight and "even odds" in why, why
    s = fort([t], [sq(10, need * 0.425), sq(11, need * 0.425)])
    assert not fight_or_hide(s, Memory(), CFG, [t], s["military"]["squads"])[0]
    hurt = titan(blood_lost=0.3, facts=1)
    need_h = PM.judge([hurt], [sq(1, 1)])["need"]
    s = fort([hurt], [sq(10, need_h * 0.425), sq(11, need_h * 0.425)])
    fight, why = fight_or_hide(s, Memory(), CFG, [hurt], s["military"]["squads"])
    assert fight and "wounded" in why, why


# --- the losses guard ----------------------------------------------------------------------------

@test("losses: a squad out on goblins that lost a third of its soldiers falls back, said; once its order is gone "
      "it regroups half a day, then the odds decide again")
def _():
    gobs = [goblin(8000 + i) for i in range(3)]
    q = sq(10, 300, members=9, ai_orders=1, orders=1, kill_ids=[8000, 8001, 8002])
    s = fort(gobs, [q])
    m = Memory()
    note_cycle(s, m)
    assert m.holdfast["kill"]["10"]["members"] == 9
    s2 = fort(gobs, [dict(q, members=5)])
    note_cycle(s2, m)
    props, notes = plan(s2, m)
    assert 10 in recalled(props), [(p.rule, p.action) for p in props if "squad" in p.rule]
    assert any("turned bad" in n and "4 of the 9" in n for n in notes), [n for n in notes if "bad" in n]
    # the order gone: regrouping (not sent again at once), then free again
    s3 = fort(gobs, [dict(q, members=5, ai_orders=0, orders=0, kill_ids=[])])
    note_cycle(s3, m)
    assert "10" in m.holdfast.get("fell_back", {}), m.holdfast
    assert "10" in HF.regrouping(s3, m, CFG)
    assert 10 not in sent(plan(s3, m)[0])
    s4 = copy.deepcopy(s3)
    s4["date"] = dict(s4["date"], tick=s4["date"]["tick"] + 700)
    s4 = digest.normalize(s4)
    assert "10" not in HF.regrouping(s4, m, CFG)


@test("losses: half the soldiers wounded falls back too; a fight with few losses goes on")
def _():
    assert PM.losses_turned([dict(sq(10, 50, members=6), power={"power": 50, "wounded": 3})], {}, CFG)
    assert not PM.losses_turned([dict(sq(10, 50, members=6), power={"power": 50, "wounded": 2})], {"10": 7}, CFG)
    assert "3 of the 9" in PM.losses_turned([sq(10, 50, members=6)], {"10": 9}, CFG)


@test("called off: a titan fight called off for its losses stays off at the learned odds; after the wait (siege "
      "days since the call-off) an all-out attack takes it up again")
def _():
    t = titan()
    s = fort([t], [sq(10, 15), sq(11, 15)])
    m = Memory()
    m.called_off = {"6001": abs_tick(s) - DAY}
    m.fight_factor = {"Titan": 3.0}
    siege_since(m, s, 5)
    fight, why = fight_or_hide(s, m, CFG, [t], s["military"]["squads"])
    assert not fight and "when the odds return" in why, why
    m.called_off = {"6001": abs_tick(s) - 5 * DAY}
    m.fight_factor = {"Titan": 1.0}
    fight, why = fight_or_hide(s, m, CFG, [t], s["military"]["squads"])
    assert fight and "all-out" in why and not m.called_off, why


@test("fliers: crossbows only (a melee squad strong enough stays home, the crossbow squad goes)")
def _():
    bats = [goblin(8000 + i, x=60 + i, flier=True, name="goblin on a giant bat") for i in range(4)]
    bows = dict(sq(11, 60), power={"power": 60, "armed": 7, "melee_power": 10, "ranged_power": 50},
                ai_uniform="AI crossbow")
    s = fort(bats, [sq(10, 200), bows])
    m = Memory()
    note_cycle(s, m)
    props, _ = plan(s, m)
    assert sent(props) == [11], sent(props)


# --- wildlife ------------------------------------------------------------------------------------

@test("wild pack: the free squads beat it at about even odds now (fight True at 1.2x)")
def _():
    pack = [{"id": 7000 + i, "name": "giant dingo", "animal": True, "agitated": True, "invader": False,
             "great_danger": False, "size": 30000, "can_reach_dwarves": True, "layer": "upper_levels",
             "distance_to_nearest_dwarf": 20, "levels_from_nearest_dwarf": 0,
             "pos": {"x": 50 + i, "y": 50, "z": 170}} for i in range(4)]
    need = PM.judge(pack, [sq(1, 1)])["need"]
    s = fort(pack, [sq(10, need * 1.2)])
    wp = wild_pack(s, CFG)
    assert wp["danger"] and wp["fight"], wp



@test("wild hunt: a big beast (2,500,000, ~21) goes to a squad of 25 that beats it alone at about even odds (the "
      "40 of wild_big_power was set for 2x); a squad of 15 stays")
def _():
    def case(power):
        fw = {"merchants": 0, "caravan": [], "wild_total": 1,
              "wild": [{"id": 7100, "name": "giant moose", "wild": True, "reach": True, "size": 2500000,
                        "distance": 10, "distance_outside": 10, "outside": True}]}
        s = fort([], [sq(10, power)], field_watch=fw)
        m = Memory()
        note_cycle(s, m)
        props, _ = plan(s, m)
        return [p for p in props if p.rule == "wild_hunt"]
    assert case(25), "a squad of 25 hunts it"
    assert not case(15)


if __name__ == "__main__":
    finish()
