"""(r5 p3) Repeated refusals backed off: the same rule and action refused for
the same reason r5p3_refusal_streak times in a row waits 1, 2, 4 ... game
days (at most r5p3_refusal_wait_max_days), kept a year; reset by an
acceptance, another reason, or a change in what the refusal depends on (a new
level, a new well, the bridge); said once in the notes; never for the
transient survival steps, the alarm, gates, and never for drink and water in
a crisis.

Evidence: run of 15-16 Nov, B place_well refused 92 times in 13 game years
("no open drop from a free floor inside the fort to clean water; ... freezes
in winter"), seven each autumn, the general back-off forgotten each year
(run2/R-B.md); C's well 54, E's farm_plots 38+ (run2/R-CE.md).

    python tests/test_r5_p3.py
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
from planner import (PLANNER_CONFIG, Memory, plan, record, select, abs_tick, TICKS_PER_DAY,  # noqa: E402
                     TICKS_PER_YEAR)
from planner_core import Proposal  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = dict(PLANNER_CONFIG)
NO_DROP = ("no open drop from a free floor inside the fort to clean water; and the water near the surface "
           "freezes in winter (a well over it would be taken down), so the AI looks only inside the fort")


def fort(year=250, tick=300000, **extra):
    s = copy.deepcopy(BASE)
    s["date"] = dict(s["date"], year=year, tick=tick, season="autumn")
    s["bridge_version"] = "0.105.60"
    s["projects"] = dict(s.get("projects") or {}, done_total=57)
    s.setdefault("buildings", {}).setdefault("other", {})["Well"] = 0
    s.update(extra)
    return s


def at(s, days):
    """The same fort `days` game days later."""
    t = abs_tick(s) + int(days * TICKS_PER_DAY)
    s = copy.deepcopy(s)
    s["date"] = dict(s["date"], year=t // TICKS_PER_YEAR, tick=t % TICKS_PER_YEAR)
    return s


def well():
    return Proposal("well", {"type": "place_well", "shore_reach": 60, "inside_only": True},
                    "no well yet", 3)


def asked(p, s, m, cfg=CFG):
    """One cycle: select, and the bridge refuses whatever is let through
    (NO_DROP). True when the step was sent."""
    m.last_fired.clear()              # (the rule's own cooldown is not what is tested)
    allowed, _held = select([p], s, m, cfg)
    if allowed:
        record([(allowed[0], {"ok": False, "error": NO_DROP})], s, m, cfg)
    return bool(allowed)


def refuse(p, s, m, n, why=NO_DROP, cfg=CFG):
    for _ in range(n):
        record([(p, {"ok": False, "error": why})], s, m, cfg)


def held_by_streak(p, s, m, cfg=CFG):
    m.last_fired.clear()
    allowed, held = select([p], s, m, cfg)
    return not allowed and any("in a row for the same reason" in h for h in held), held


@test("B's well: three refusals in a row for the same reason, then it waits 1, 2, 4 ... days, at most 28")
def _():
    s, m, p = fort(), Memory(), well()
    refuse(p, s, m, 2)
    m.refusals.clear()                          # (the general back-off aside)
    assert not held_by_streak(p, s, m)[0], "two refusals: not yet"
    refuse(p, s, m, 1)
    m.refusals.clear()
    ok, held = held_by_streak(p, s, m)
    assert ok, held
    assert "refused 3 times in a row" in held[0] and "1 day(s)" in held[0], held
    rec = next(iter(m.refusal_streaks.values()))
    assert rec["days"] == 1 and rec["n"] == 3, rec
    assert not held_by_streak(p, at(s, 1.01), m)[0], "the day is over"
    days = []
    for _ in range(6):
        refuse(p, s, m, 1)
        days.append(next(iter(m.refusal_streaks.values()))["days"])
    assert days == [2, 4, 8, 16, 28, 28], days


@test("B's well over five autumns: the streak outlives the general back-off's 60 days, so far fewer asks")
def _():
    def autumns(cfg):
        m, p, sent = Memory(), well(), 0
        for year in range(250, 255):
            for day in range(0, 84, 3):            # a cycle every 3 game days, autumn and winter
                s = fort(year=year, tick=300000 + day * TICKS_PER_DAY)
                sent += asked(p, s, m, cfg)
            # the rest of the year: other rules' refusals (B: hundreds) prune the general back-off's book
            for day in range(90, 300, 7):
                o = Proposal("homes", {"type": "give_room", "unit_id": day}, "x", 6)
                record([(o, {"ok": False, "error": "no room"})], at(fort(year=year), day), m, cfg)
        return sent, m
    on, m = autumns(CFG)
    off, _ = autumns(dict(CFG, r5p3_refusal_backoff=False))
    assert off >= 30, off                         # main: seven an autumn (B: 92 in 13 years)
    assert on <= 20 and on < off, (on, off)
    rec = next(iter(m.refusal_streaks.values()))
    assert rec["n"] == on and rec["days"] == 28, rec


@test("an acceptance ends the streak; another reason begins a new one")
def _():
    s, m, p = fort(), Memory(), well()
    refuse(p, s, m, 4)
    m.refusals.clear()
    assert held_by_streak(p, s, m)[0]
    record([(p, {"ok": True, "project_id": 9})], s, m, CFG)
    assert not m.refusal_streaks, m.refusal_streaks
    m.refusals.clear()
    assert not held_by_streak(p, s, m)[0]
    refuse(p, s, m, 4)
    refuse(p, s, m, 1, why="already 4 unfinished building projects")
    m.refusals.clear()
    assert not held_by_streak(p, s, m)[0], "the reason changed: a new streak of one"
    assert next(iter(m.refusal_streaks.values()))["n"] == 1
    # numbers aside it is the same reason ("4 buildings" / "5 buildings")
    q = Proposal("stuck_sweep", {"type": "finish_project", "project_id": 54, "stalled": True}, "x", 5)
    for k in (4, 5, 4):
        refuse(q, s, m, 1, why=f"{k} buildings still waiting")
    m.refusals.clear()
    assert held_by_streak(q, s, m)[0]


@test("what the refusal depends on changes: a new level, a new well, a new farm plot, another bridge: asked at once")
def _():
    p = well()
    for change in ("levels", "well", "bridge"):
        s, m = fort(), Memory()
        refuse(p, s, m, 5)
        m.refusals.clear()
        assert held_by_streak(p, s, m)[0]
        s2 = copy.deepcopy(s)
        if change == "levels":
            s2["projects"]["done_total"] += 1
        elif change == "well":
            s2["buildings"]["other"]["Well"] = 1
        else:
            s2["bridge_version"] = "0.105.61"
        assert not held_by_streak(p, s2, m)[0], change
        refuse(p, s2, m, 1)
        assert next(iter(m.refusal_streaks.values()))["n"] == 1, change
    farms = Proposal("farms", {"type": "farm_plots", "tiles": 40, "dig": False, "underground": True}, "x", 4)
    s, m = fort(), Memory()
    s["farms"] = {"plots": 11}
    refuse(farms, s, m, 3, why="no free soil or muddy floor near the dwarves; and no safe spot for a farm level")
    m.refusals.clear()
    assert held_by_streak(farms, s, m)[0]
    s2 = copy.deepcopy(s)
    s2["farms"]["plots"] = 12
    assert not held_by_streak(farms, s2, m)[0]
    # a well is not what the farms wait on
    s3 = copy.deepcopy(s)
    s3["buildings"]["other"]["Well"] = 3
    assert held_by_streak(farms, s3, m)[0]


@test("said once: the note when the wait begins, not on the cycles after")
def _():
    s, m, p = fort(), Memory(), well()
    refuse(p, s, m, 3)
    _props, notes = plan(s, m)
    said = [n for n in notes if "in a row for the same reason" in n]
    assert len(said) == 1 and "place well" in said[0] and "28" in said[0], said
    select([], s, m, CFG)
    _props, notes = plan(s, m)
    assert not [n for n in notes if "in a row for the same reason" in n], notes
    refuse(p, s, m, 1)                       # the wait grows: not said again
    _props, notes = plan(s, m)
    assert not [n for n in notes if "in a row for the same reason" in n], notes


@test("never held: the alarm, gates, thirst, a way out; drink and water in a crisis or urgent; the switch off")
def _():
    s = fort()
    steps = [Proposal("alerts", {"type": "civ_alert", "on": True}, "x", 1),
             Proposal("gate_doors", {"type": "build_gate_doors", "id": 3}, "x", 1),
             Proposal("thirst", {"type": "thirst_unforbid"}, "x", 1),
             Proposal("way_out", {"type": "way_out_open", "id": 4}, "x", 1),
             Proposal("calm_burrow", {"type": "calm_burrow", "release": True}, "x", 1)]
    for q in steps:
        m = Memory()
        refuse(q, s, m, 6, why="nobody can reach it")
        m.refusals.clear()
        assert not held_by_streak(q, s, m)[0], q.rule
    m, p = Memory(), well()
    refuse(p, s, m, 5)
    m.refusals.clear()
    assert held_by_streak(p, s, m)[0]
    m.crisis = {"since": abs_tick(s), "why": "thirst"}
    assert not held_by_streak(p, s, m)[0], "a crisis lifts the wait for water"
    homes = Proposal("homes_liked", {"type": "house_dwarves"}, "x", 6)
    refuse(homes, s, m, 4, why="every household has one room, and no free room is much better")
    m.refusals.clear()
    assert held_by_streak(homes, s, m)[0], "a crisis lifts only drink and water"
    m.crisis = {}
    urgent = Proposal("well", dict(p.action, urgent=True), "x", 1)
    assert not held_by_streak(urgent, s, m)[0], "an urgent well step"
    assert not held_by_streak(p, s, m, dict(CFG, r5p3_refusal_backoff=False))[0], "the switch"


@test("kept a year and through the save; at most r5p3_refusal_keep streaks")
def _():
    s, m, p = fort(), Memory(), well()
    refuse(p, s, m, 4)
    m2 = Memory.from_dict(json.loads(json.dumps(m.to_dict())))
    assert m2.refusal_streaks == m.refusal_streaks and m2.refusal_streaks
    later = at(s, 300)
    q = Proposal("homes_liked", {"type": "house_dwarves"}, "x", 6)
    refuse(q, later, m, 1, why="no room")
    assert len(m.refusal_streaks) == 2, "300 days on: the well's streak is still kept"
    refuse(q, at(s, 340), m, 1, why="no room")
    assert len(m.refusal_streaks) == 1, "a year on: forgotten"
    cfg = dict(CFG, r5p3_refusal_keep=5)
    for i in range(9):
        refuse(Proposal("homes", {"type": "give_room", "unit_id": i}, "x", 6), at(s, i / 10), m, 1,
               why="no room", cfg=cfg)
    assert len(m.refusal_streaks) == 5, len(m.refusal_streaks)


@test("left alone: unknown answers, the in-game halt, a search cut short (item7: an answer to wait counts)")
def _():
    s, m, p = fort(), Memory(), well()
    for r in ({"ok": None}, {"ok": False, "halted": True, "error": "halted"},
              {"ok": False, "timed_out": True, "error": "search cut short"}):
        record([(p, r)], s, m, CFG)
    assert not m.refusal_streaks, m.refusal_streaks


finish()
