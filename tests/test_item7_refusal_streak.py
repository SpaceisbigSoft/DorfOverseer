"""(0.105.112 item7) The refusal streak no longer begins again at every new
level, counts an answer to wait, holds the squads in peace, keeps a short cap
for the safety steps and a day for a hospital post while patients wait.

Evidence, 24 Nov (12 h): B staff 91 ("nobody free": the surgeon post),
homes_liked 44, care_feed 33, unload_depot 228; E chronic_convict 41, mood 48
("1 animal(s) already wait for the butcher"); A squad_fill 86, food_store 32.
The live streak book (B, E memory 23:32): homes_liked n=1 against the general
back-off's n=7, chronic_convict n=1 against 6: the signature held the levels
finished ever (158 -> 159), which moved between two refusals.

    python tests/test_item7_refusal_streak.py
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
from planner import PLANNER_CONFIG, Memory, record, select, abs_tick, TICKS_PER_DAY, TICKS_PER_YEAR  # noqa: E402
from planner_core import Proposal, refusal_key, _refused_wait  # noqa: E402
import planner_refusal_streak as rs  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = dict(PLANNER_CONFIG)
NOBODY = ("nobody free to take the post (no child, soldier, office holder, post holder, patient, or dwarf "
          "very unhappy or with a tantrum lately)")


def fort(year=271, tick=100000, levels=158):
    s = copy.deepcopy(BASE)
    s["date"] = dict(s["date"], year=year, tick=tick, season="summer")
    s["bridge_version"] = "0.105.111"
    s["projects"] = dict(s.get("projects") or {}, done_total=levels)
    return s


def at(s, days, levels=None):
    t = abs_tick(s) + int(days * TICKS_PER_DAY)
    s = copy.deepcopy(s)
    s["date"] = dict(s["date"], year=t // TICKS_PER_YEAR, tick=t % TICKS_PER_YEAR)
    if levels is not None:
        s["projects"]["done_total"] = levels
    return s


def peace():
    m = Memory()
    m.quiet_cycles = 50
    return m


def refuse(p, s, m, n, why, **extra):
    for _ in range(n):
        record([(p, dict({"ok": False, "error": why}, **extra))], s, m, CFG)


def held(p, s, m):
    m.last_fired.clear()
    allowed, h = select([p], s, m, CFG)
    return not allowed and any("in a row for the same reason" in x for x in h)


def rec(m, p):
    return m.refusal_streaks.get(refusal_key(p)) or {}


@test("a new level no longer ends a streak that has nothing to do with room (a post, a labour, a trial)")
def _():
    steps = [(Proposal("staff", {"type": "staff_location", "location_id": 14, "post": "DIAGNOSTICIAN"},
                       "the hospital has no diagnostician: give the post to the dwarf best at it", 4), NOBODY),
             (Proposal("care_feed", {"type": "assign_labor", "job": "FEED_WATER_CIVILIANS", "count": 2}, "x", 5),
              "everybody already does this (the Orderlies work detail is set to everybody)"),
             (Proposal("chronic_convict", {"type": "convict", "max": 1, "unit_id": 17912}, "x", 5),
              "no solved case of that culprit waits for a trial (disorderly behaviour only)")]
    for p, why in steps:
        s, m = fort(), peace()
        for i in range(4):          # a level finished between every two refusals (B: 158 -> 159)
            refuse(p, at(s, 2 * i, levels=158 + i), m, 1, why)
        assert rec(m, p).get("n") == 4, (p.rule, rec(m, p))
        assert "levels" not in rec(m, p)["sig"], rec(m, p)
        m.refusals.clear()
        assert held(p, at(s, 6.5, levels=170), m), p.rule
    # a room still waits on a level: a new one asks at once
    homes = Proposal("homes_liked", {"type": "house_dwarves", "house": 0, "upgrade": 10}, "x", 6)
    s, m = fort(), peace()
    refuse(homes, s, m, 4, "every household has one room, and no free room is much better for the stressed")
    m.refusals.clear()
    assert held(homes, s, m)
    assert not held(homes, at(s, 0.1, levels=159), m), "a new level may hold the better room"
    food = Proposal("food_store", {"type": "food_pile", "building_id": 20, "tiles": 47}, "x", 4)
    assert rs.spatial(food, "no free roofed floor within # tiles of the Still for a food pile")


@test("an answer to wait counts: the same one three times waits, at most 7 days; another answer begins again")
def _():
    p = Proposal("unload_depot", {"type": "unload_depot", "max": 50}, "x", 6)
    s, m = fort(), peace()
    refuse(p, s, m, 3, "1 item(s) are being hauled out of the depot", waiting=True, rejected=True)
    r = rec(m, p)
    assert r["n"] == 3 and r["waiting"] and r["why"].startswith("wait: "), r
    m.refusals.clear()
    assert held(p, s, m)
    days = []
    for k in range(6):
        refuse(p, s, m, 1, f"{k + 2} item(s) are being hauled out of the depot", waiting=True)
        days.append(rec(m, p)["days"])
    assert days == [2, 4, 7, 7, 7, 7], days
    refuse(p, s, m, 1, "none moved out of the depot: the game kept it in the depot")
    assert rec(m, p)["n"] == 1, "a refusal is another reason than the wait"


@test("the squads are held in peace (at most 7 days), never while a threat was about lately")
def _():
    p = Proposal("squad_fill", {"type": "squad_fill", "squad_id": 211, "count": 3, "avoid": [1, 2]}, "x", 4)
    why = "no suitable dwarves could be added (25 candidate(s), 0 tried, 3 open place(s), 10 kept out: 9 a post)"
    s, m = fort(), peace()
    refuse(p, s, m, 3, why)
    refuse(p, s, m, 5, why.replace("25", "26"))
    assert rec(m, p)["n"] == 8 and rec(m, p)["days"] == 7, rec(m, p)
    m.refusals.clear()
    assert held(p, s, m)
    assert not held(p, at(s, 7.01), m), "seven days at most"
    m.quiet_cycles = 1
    assert not held(p, s, m), "a threat lately: the squads are never held"
    m.quiet_cycles = 50
    m.ai_alert_raised = True
    assert not held(p, s, m), "the alarm up"
    m.ai_alert_raised = False
    s2 = copy.deepcopy(s)
    s2.setdefault("others_on_map", {})["threats"] = [{"great_danger": True, "can_reach_dwarves": True}]
    assert not held(p, s2, m), "a great danger"
    assert held(p, s, m)


@test("the critical ones are never held, in peace too: the alarm, gates, the shelter, killers, fights, thirst")
def _():
    steps = [Proposal("alerts", {"type": "civ_alert", "on": True}, "x", 1),
             Proposal("gate_doors", {"type": "build_gate_doors", "id": 3}, "x", 1),
             Proposal("shelter", {"type": "setup_shelter"}, "x", 1),
             Proposal("killer", {"type": "killer_cell", "unit_id": 5}, "x", 1),
             Proposal("break_fights", {"type": "break_fights"}, "x", 1),
             Proposal("fight_watch", {"type": "fight_watch"}, "x", 1),
             Proposal("thirst", {"type": "thirst_unforbid"}, "x", 1),
             Proposal("insane", {"type": "insane_guard"}, "x", 1),
             Proposal("mood", {"type": "slaughter_one", "mood": True}, "x", 1)]
    for q in steps:
        m = peace()
        refuse(q, fort(), m, 6, "nobody can reach it")
        m.refusals.clear()
        assert not held(q, fort(), m), q.rule
        assert rs.exempt(q, m, fort(), CFG), q.rule


@test("the safety steps that may wait keep a short cap: half a day (a mood's help, a tantrum's care, the jail)")
def _():
    for q in (Proposal("mood_reserve", {"type": "work_order", "recipe": "cloth"}, "x", 3),
              Proposal("staff_tantrum", {"type": "staff_location", "location_id": 2, "post": "TAVERN_KEEPER"}, "x", 3),
              Proposal("jail_size", {"type": "start_project", "kind": "jail"}, "x", 3),
              Proposal("magma_guard", {"type": "magma_guard"}, "x", 3)):
        s, m = fort(), peace()
        refuse(q, s, m, 8, "nothing to do it with")
        r = rec(m, q)
        assert r["until"] - r["at"] == TICKS_PER_DAY // 2, (q.rule, r)
        m.refusals.clear()
        assert held(q, s, m), q.rule
        assert not held(q, at(s, 0.51), m), q.rule


@test("a hospital post while patients wait: asked once a game day; one post's success isn't another's")
def _():
    surgeon = Proposal("staff", {"type": "staff_location", "location_id": 3, "post": "SURGEON"},
                       "the hospital has no surgeon and 2 need care: give the post to the dwarf best at it", 2)
    doctor = Proposal("staff", {"type": "staff_location", "location_id": 3, "post": "DOCTOR"},
                      "the hospital has no doctor and 2 need care: give the post to the dwarf best at it", 2)
    assert refusal_key(surgeon) != refusal_key(doctor)
    s, m = fort(), peace()
    refuse(surgeon, s, m, 8, NOBODY, rejected=True)
    assert m.refusals[refusal_key(surgeon)]["until"] - m.refusals[refusal_key(surgeon)]["at"] == TICKS_PER_DAY
    r = rec(m, surgeon)
    assert r["until"] - r["at"] == TICKS_PER_DAY, r
    record([(doctor, {"ok": True, "post": "doctor"})], s, m, CFG)
    assert rec(m, surgeon)["n"] == 8, "the doctor given leaves the surgeon's streak"
    assert _refused_wait(m, surgeon, abs_tick(s) + 10, "0.105.111") == 1
    assert _refused_wait(m, surgeon, abs_tick(s) + TICKS_PER_DAY + 1, "0.105.111") is None
    # no patients: the long back-off (a library's or a tavern's post, a hospital with nobody to treat)
    calm = Proposal("staff", {"type": "staff_location", "location_id": 14, "post": "DIAGNOSTICIAN"},
                    "the hospital has no diagnostician: give the post to the dwarf best at it", 4)
    m2 = peace()
    refuse(calm, s, m2, 8, NOBODY)
    assert rec(m2, calm)["days"] == 28, rec(m2, calm)
    # a long wait booked before patients came is cut to a day once they wait
    m2.refusals.clear()
    asks = Proposal("staff", dict(calm.action), "the hospital has no diagnostician and 1 need care: give it", 2)
    assert held(calm, at(s, 3), m2) and not held(asks, at(s, 3), m2)


@test("kept through the save (the keeper restart), the waiting flag too")
def _():
    p = Proposal("unload_depot", {"type": "unload_depot", "max": 50}, "x", 6)
    s, m = fort(), peace()
    refuse(p, s, m, 4, "1 item(s) are being hauled out of the depot", waiting=True)
    m2 = Memory.from_dict(json.loads(json.dumps(m.to_dict())))
    assert m2.refusal_streaks == m.refusal_streaks
    m2.quiet_cycles = 50
    m2.refusals.clear()
    assert held(p, s, m2)


@test("B's fast game (a cycle every 2 game days, a level every 5): far fewer asks than before")
def _():
    def run(levels_move):
        m, sent = peace(), 0
        p = Proposal("care_feed", {"type": "assign_labor", "job": "FEED_WATER_CIVILIANS", "count": 2}, "x", 5)
        for day in range(0, 140, 2):            # one real hour of B: ~140 game days
            s = fort(tick=10000 + day * TICKS_PER_DAY, levels=158 + (day // 5 if levels_move else 0))
            m.last_fired.clear()
            m.refusals.clear()                  # (the general back-off aside: the streak alone)
            allowed, _h = select([p], s, m, CFG)
            if allowed:
                sent += 1
                record([(p, {"ok": False, "error": "everybody already does this (the Orderlies work "
                                                   "detail is set to everybody)"})], s, m, CFG)
        return sent
    a, b = run(True), run(False)
    assert a == b and a <= 12, (a, b)      # 0.105.111: the level count ended each streak (a 70-ask hour)


finish()
