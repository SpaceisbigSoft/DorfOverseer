"""(0.105.48, K16) Threat response, round 2 (audit A6 and round 1's leftovers):
a snatcher keeps the alarm (not the gates or the sortie); the gates the
watcher shut open after the reach alarm's cap when no enemy is near one;
squads out on a fight the matchup finds lost come back (station or
shelter) under every policy; hiding() under "attack everything" after a
fight is called off; the wildlife and caravan squads kept on past the edge
(A6 #16); no kill order on a squad under the player's own orders (A6 #17);
an unread facts row judged the old way (A6 #12); a second kill order goes to
a free squad (select).

    python tests/test_k48_threat_followups.py
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
from planner import Memory, PLANNER_CONFIG, plan, note_cycle, select  # noqa: E402
from planner_core import Proposal, abs_tick, reachable_threats  # noqa: E402
from planner_alarm import note_alarm_change, REACH_CAP_WHY  # noqa: E402
from planner_military import threat_power  # noqa: E402
import planner_army  # noqa: E402
import digest  # noqa: E402

CFG = dict(PLANNER_CONFIG)
DAY = 1200
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def goblin(i=8000, **kw):
    t = {"id": i, "name": "goblin", "invader": True, "great_danger": False, "flier": False, "size": 60000,
         "can_reach_dwarves": True, "layer": "upper_levels", "distance_to_nearest_dwarf": 40,
         "levels_from_nearest_dwarf": 0, "pos": {"x": 60, "y": 60, "z": 170}}
    t.update(kw)
    return t


def titan(i=6001, **kw):
    t = {"id": i, "name": "a titan", "great_danger": True, "kinds": ["Titan"], "size": 9000000,
         "can_reach_dwarves": True, "layer": "upper_levels", "distance_to_nearest_dwarf": 150,
         "levels_from_nearest_dwarf": 0, "pos": {"x": 10, "y": 10, "z": 170}}
    t.update(kw)
    return t


def wolf(i=7002, **kw):
    t = {"id": i, "name": "wolf", "animal": True, "agitated": True, "invader": False, "great_danger": False,
         "flier": False, "size": 50000, "can_reach_dwarves": True, "layer": "Cavern1",
         "distance_to_nearest_dwarf": 12, "levels_from_nearest_dwarf": 0, "pos": {"x": 50, "y": 50, "z": 120}}
    t.update(kw)
    return t


def sq(i, power, members=7, **kw):
    q = {"id": i, "name": f"Squad {i}", "members": members, "size": 10, "orders": 0, "ai_orders": 0,
         "power": {"power": power, "armed": members, "melee_power": power, "ranged_power": 0}}
    q.update(kw)
    return q


def fort(threats, squads=None, alert=False, policy="ordinary", **extra) -> dict:
    s = copy.deepcopy(BASE)
    s["others_on_map"]["threats"] = threats
    s["others_on_map"]["threats_that_can_reach_dwarves"] = sum(1 for t in threats if t.get("can_reach_dwarves") is True)
    if squads is not None:
        s["military"]["squads"] = squads
    s["civ_alert"] = alert
    s["civ_alert_ready"] = True
    s["settings"]["attack_policy"] = policy
    s.update(extra)
    return digest.normalize(s)


def by(props, rule=None, typ=None):
    return [p for p in props if (rule is None or p.rule == rule) and (typ is None or p.action.get("type") == typ)]


def alarm(props, on):
    return [p for p in props if p.action == {"type": "civ_alert", "on": on}]


def recalled(props) -> set:
    out = set()
    for p in by(props, "squad_recall"):
        a = p.action
        if a.get("type") == "squad_orders" and a.get("clear"):
            out.add(a.get("squad_id"))
        out.update(a.get("squads") or [])
    return out


# --- 1. a snatcher keeps the alarm ---------------------------------------------------------

def snatch_fort(kind="snatcher", i=9001, alert=False, **kw):
    k = goblin(i, name="goblin snatcher", invader=True, distance_to_nearest_dwarf=5)
    s = fort([k], [sq(10 + j, 60) for j in range(4)], alert=alert, **kw)
    s["threats"] = {"thieves": {"list": [{"id": i, "name": "goblin snatcher", "kind": kind, "inside": True,
                                          "can_reach_dwarves": True}]}}
    s["entrances"]["intruders_inside"] = [i]
    return s


@test("snatcher: out of reach like a thief (no gates, no sortie), but the alarm goes up; a thief: no alarm")
def _():
    s = snatch_fort()
    assert reachable_threats(s, {}, CFG) == []
    m = Memory()
    note_cycle(s, m)
    props, notes = plan(s, m)
    on = alarm(props, True)
    assert on and "snatcher" in on[0].reason, [(p.rule, p.action, p.reason) for p in props if p.rule == "threat_alert"]
    assert not by(props, "gates", "arm_gates"), [(p.rule, p.action) for p in props if p.rule == "gates"]
    kills = [p for p in by(props, typ="squad_orders") if 9001 in (p.action.get("kill") or [])]
    assert len(kills) == 1, [(p.rule, p.action) for p in kills]
    t = snatch_fort("thief")
    m = Memory()
    note_cycle(t, m)
    assert not alarm(plan(t, m)[0], True)


@test("snatcher: the alarm held while it is about, down after snatcher_alert_ticks; not raised again for the "
      "same one, raised for a new one")
def _():
    s = snatch_fort(alert=True)
    now = abs_tick(s)
    m = Memory(ai_alert_raised=True)
    note_alarm_change(m, now - 100, True, "1 snatcher(s) among the dwarves (a snatcher takes children): ...")
    note_cycle(s, m)
    props, notes = plan(s, m)
    assert not alarm(props, False) and any("snatcher" in n and "stays up" in n for n in notes), \
        [n for n in notes if "alarm" in n][:5]
    m2 = Memory(ai_alert_raised=True)
    note_alarm_change(m2, now - CFG["snatcher_alert_ticks"] - 10, True, "1 snatcher(s) among the dwarves ...")
    note_cycle(s, m2)
    props, _ = plan(s, m2)
    off = alarm(props, False)
    assert off and "snatcher" in off[0].reason, [(p.action, p.reason) for p in props if p.rule == "threat_alert"]
    # lowered: the same snatcher doesn't sound it again; a new one does
    note_alarm_change(m2, now, False, off[0].reason)
    m2.ai_alert_raised = False
    down = snatch_fort()
    assert not alarm(plan(down, m2)[0], True)
    assert alarm(plan(snatch_fort(i=9002), m2)[0], True)


# --- 2. the gates follow the reach alarm's cap --------------------------------------------

def capped(s):
    t0 = abs_tick(s)
    m = Memory()
    m.atlas = {"lockdown": {"new": t0 - 5 * DAY, "seen": [6001]}}
    note_alarm_change(m, t0 - DAY, True, "1 threat(s) can reach the dwarves")
    note_alarm_change(m, t0 - DAY // 2, False, REACH_CAP_WHY + " 3 days and none ...")
    return m


def armed_fort(beast):
    s = fort([beast], [])
    s["entrances"]["armed"] = True
    s["entrances"]["entrances"][0]["closed"] = True
    return s


@test("reach cap: the alarm down at its cap and no enemy within 60 tiles of a gate: the gates the watcher shut "
      "open; an enemy near a gate, a new one, or no cap: they stay")
def _():
    far = armed_fort(titan(pos={"x": 200, "y": 10, "z": 170}))          # the gate is at x31 y140 z173
    m = capped(far)
    props, _ = plan(far, m)
    opens = by(props, "gates", "open_gates")
    assert opens and "maximum time" in opens[0].reason, [(p.action, p.reason) for p in by(props, "gates")]
    near = armed_fort(titan(pos={"x": 40, "y": 120, "z": 173}))
    assert not by(plan(near, capped(near))[0], "gates", "open_gates")
    assert not by(plan(far, Memory())[0], "gates", "open_gates")
    m = capped(far)
    m.atlas["lockdown"]["new"] = abs_tick(far)                          # a new enemy since
    assert not by(plan(far, m)[0], "gates", "open_gates")
    # opened, not armed: armed again (the watcher closes late)
    s = fort([titan(pos={"x": 200, "y": 10, "z": 170})], [])
    assert by(plan(s, capped(s))[0], "gates", "arm_gates")


# --- 3. a fight the matchup finds lost ------------------------------------------------------

@test("lost fight: a squad out on 3 goblins when 40 more come is called back, under 'ordinary' and 'all'; "
      "into the shelter with the alarm up; still winning: it stays")
def _():
    for policy in ("ordinary", "all"):
        gobs = [goblin(8000 + i) for i in range(43)]
        out = sq(10, 70, ai_orders=1, orders=1, kill_ids=[8000, 8001, 8002])
        s = fort(gobs, [out, sq(11, 40)], alert=True, policy=policy)
        m = Memory(ai_alert_raised=True)
        note_cycle(s, m)
        props, notes = plan(s, m)
        assert 10 in recalled(props), (policy, [(p.rule, p.action) for p in props if "squad" in p.rule])
        back = [p for p in by(props, "squad_recall") if 10 in (p.action.get("squads") or [p.action.get("squad_id")])]
        assert back[0].action["type"] == "shelter_squads" and "can't win" in back[0].reason, back[0].action
        assert not [p for p in by(props, "squad_attack")], [p.action for p in by(props, "squad_attack")]
    gobs = [goblin(8000 + i) for i in range(4)]
    out = sq(10, 70, ai_orders=1, orders=1, kill_ids=[8000, 8001, 8002])
    s = fort(gobs, [out, sq(11, 40)], alert=True)
    props, _ = plan(s, Memory(ai_alert_raised=True))
    assert 10 not in recalled(props), [(p.rule, p.action) for p in by(props, "squad_recall")]


@test("lost fight: a squad out on a titan the verdict now holds back comes back (the shelter rule off too); "
      "a hunting party is the hunt's")
def _():
    out = sq(10, 70, ai_orders=1, orders=1, kill_ids=[6001])
    s = fort([titan(distance_to_nearest_dwarf=20)], [out], alert=True)
    s["settings"]["squads_shelter"] = False
    props, _ = plan(s, Memory(ai_alert_raised=True))
    assert 10 in recalled(props), [(p.rule, p.action, p.reason) for p in props if "squad" in p.rule]


@test("hiding: under 'attack everything' a called-off great danger with nothing else in reach: hide; with a "
      "goblin too, or not called off: no hiding")
def _():
    s = fort([titan()], [sq(10, 70)], policy="all")
    m = Memory()
    assert planner_army.hiding(s, m, CFG) == (False, [6001])
    m.called_off = {"6001": abs_tick(s)}
    assert planner_army.hiding(s, m, CFG) == (True, [])
    s2 = fort([titan(), goblin()], [sq(10, 70)], policy="all")
    assert planner_army.hiding(s2, m, CFG) == (False, [8000])


# --- 5. wildlife hysteresis, the player's squads, unread facts ----------------------------

@test("wildlife: a squad on a wild animal just past the 25 tiles is kept on (a day at most); far past it, or an old "
      "order, it is called back")
def _():
    def case(d, since_ago=None):
        # a hostile wild animal the field watch lists (not agitated: no threat row, no day's kill hold)
        q = sq(10, 60, ai_orders=1, orders=1, kill_ids=[7100])
        fw = {"merchants": 0, "caravan": [], "wild_total": 1,
              "wild": [{"id": 7100, "name": "giant badger", "wild": True, "reach": True, "size": 80000,
                        "distance": d, "distance_outside": d, "outside": True}]}
        s = fort([], [q], field_watch=fw)
        m = Memory()
        note_cycle(s, m)
        if since_ago is not None:
            m.holdfast["kill"]["10"]["since"] = abs_tick(s) - since_ago
        props, _ = plan(s, m)
        return 10 in recalled(props)
    assert not case(35), "kept on just past the edge"
    assert case(80), "far off: called back"
    assert case(35, 2 * DAY), "an order older than wild_keep_ticks: called back"


@test("player's squads: squad_attack never puts a kill order on a squad on the player's orders at an enemy "
      "outside; one inside, yes")
def _():
    mine = sq(10, 200, orders=1, ai_orders=0)
    s = fort([goblin()], [mine, sq(11, 200)])
    sent = {p.action["squad_id"] for p in by(plan(s, Memory())[0], "squad_attack")}
    assert 10 not in sent and 11 in sent, sent
    s = fort([goblin()], [mine])
    s["entrances"]["intruders_inside"] = [8000]
    sent = {p.action["squad_id"] for p in by(plan(s, Memory())[0], "squad_attack")}
    assert 10 in sent, sent


@test("facts: a row whose raws weren't read (facts_unread, no facts) keeps the old x3 for its abilities, "
      "not the read row's x1.5")
def _():
    base = {"size": 9000000, "kinds": ["Titan"], "great_danger": True, "abilities": 2}
    unread = threat_power(dict(base, facts_unread=True, speed=1.0))
    read = threat_power(dict(base, facts=1))
    assert unread >= 2 * read * 0.99, (unread, read)


# --- 6. a second kill order goes to a free squad ---------------------------------------------

@test("select: a second kill order at a squad taken this cycle goes to the first free squad; none free (or the "
      "free one named by another proposal): folded in as before")
def _():
    s = fort([], [sq(11, 60), sq(12, 60), sq(13, 60, orders=1)])
    a = Proposal("killer", {"type": "squad_orders", "squad_id": 11, "kill": [5]}, "killer", 0)
    b = Proposal("thieves", {"type": "squad_orders", "squad_id": 11, "kill": [6]}, "thief", 1)
    allowed, held = select([a, b], s, Memory())
    got = {p.action["squad_id"]: p.action["kill"] for p in allowed}
    assert got == {11: [5], 12: [6]}, got
    a = Proposal("killer", {"type": "squad_orders", "squad_id": 11, "kill": [5]}, "killer", 0)
    b = Proposal("thieves", {"type": "squad_orders", "squad_id": 11, "kill": [6]}, "thief", 1)
    c = Proposal("shelter_squads", {"type": "shelter_squads", "squads": [12]}, "hide", 2)
    allowed, held = select([a, b, c], s, Memory())
    got = {p.action.get("squad_id"): p.action.get("kill") for p in allowed if p.rule != "shelter_squads"}
    assert got == {11: [5, 6]}, got                       # 13 is the player's; 12 has the shelter order


finish()
