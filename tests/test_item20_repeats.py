"""(0.105.115 item20) What still repeated under 0.105.114 (25 Nov, 2.5 h to
10:43): E staff 217 ("nobody free" for the doctor, once a game day while
patients waited, a game day being ~15-25 s there), B gate_jobs 131 (31
refused, 100 "resumed" jobs DF suspended again), B hospital_stock 15 refused
of 54, A squad_fill 145 (the bracketed counts changed the reason), C/F build
35 each (three bracketed lists of "no safe level found within the time
limit"), C gather_trim 24 ("all fruit zones' jobs: nothing to cancel").

    python tests/test_item20_repeats.py
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
from planner_core import Proposal, refusal_key, _refused_wait, note_refusal  # noqa: E402
import planner_refusal_streak as rs  # noqa: E402
import planner_backoff as pb  # noqa: E402
import planner_hospital_stock as HS  # noqa: E402
import planner_gates as G  # noqa: E402
import planner_labor as L  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = dict(PLANNER_CONFIG)
NOBODY = ("nobody free to take the post (no child, soldier, office holder, post holder, patient, or dwarf "
          "very unhappy or with a tantrum lately)")
FPS = 73            # E, 25 Nov: 1240 ticks in ~17 s


def fort(year=271, tick=100000, fps=None):
    s = copy.deepcopy(BASE)
    s["date"] = dict(s["date"], year=year, tick=tick, season="summer")
    s["bridge_version"] = "0.105.114"
    if fps is not None:
        s["perf"] = {"fps": fps}
    return s


def at(s, ticks):
    t = abs_tick(s) + int(ticks)
    s = copy.deepcopy(s)
    s["date"] = dict(s["date"], year=t // TICKS_PER_YEAR, tick=t % TICKS_PER_YEAR)
    return s


def peace():
    m = Memory()
    m.quiet_cycles = 50
    return m


def doctor():
    return Proposal("staff", {"type": "staff_location", "location_id": 4, "post": "DOCTOR"},
                    "the hospital has no doctor and 3 need care: give the post to the dwarf best at it", 2)


def run(p, s, m, cycles, step, answer):
    """The planner every `step` ticks for `cycles` cycles: how often p went to the game."""
    sent = 0
    for i in range(cycles):
        si = at(s, i * step)
        m.last_fired.clear()
        allowed, _ = select([p], si, m, CFG)
        if allowed:
            sent += 1
            record([(p, dict(answer))], si, m, CFG)
    return sent


@test("the reason is compared without its brackets: squad_fill's kept-out lists, build's level lists")
def _():
    a = rs.norm_why("no suitable dwarves could be added (25 candidate(s), 0 tried, 1 open place(s), "
                    "3 kept out: 2 a post, 1 very unhappy)")
    b = rs.norm_why("no suitable dwarves could be added (25 candidate(s), 0 tried, 1 open place(s), "
                    "2 kept out: 1 a post, 1 breaking down)")
    assert a == b == "no suitable dwarves could be added", (a, b)
    c = rs.norm_why("no safe level found within the time limit (z40: kept for the main hall of floor 3 (elevation 41); "
                    "z11: cavern, magma sea or special vein at x1 y2 z11)")
    d = rs.norm_why("no safe level found within the time limit (z34: not solid rock (already dug or open) at x1 y2 z34)")
    assert c == d == "no safe level found within the time limit", (c, d)
    assert rs.norm_why("4 buildings still waiting") == "# buildings still waiting"
    # a whole build streak across the three lists
    p = Proposal("build", {"type": "start_project", "kind": "storage", "piles": ["food"]}, "x", 6)
    s, m = fort(), peace()
    for why in (c, d, c.replace("z40", "z41")):
        record([(p, {"ok": False, "error": why})], s, m, CFG)
    assert m.refusal_streaks[refusal_key(p)]["n"] == 3, m.refusal_streaks


@test("E's doctor while patients wait: a game day, or 10 real minutes in a fast fort (2.5 h: 217 asks -> ~20)")
def _():
    p = doctor()
    slow = run(p, fort(), peace(), 530, 1240, {"ok": False, "error": NOBODY, "rejected": True})
    fast = run(p, fort(fps=FPS), peace(), 530, 1240, {"ok": False, "error": NOBODY, "rejected": True})
    assert slow >= 400, slow                    # no fps read: once a game day, as before (item7)
    assert fast <= 25, fast
    # the general back-off's care cap is booked with the record: the wait reads it without the state
    m = peace()
    s = fort(fps=FPS)
    for _ in range(9):
        note_refusal(m, p, {"ok": False, "error": NOBODY}, abs_tick(s), "0.105.114", state=s)
    r = m.refusals[refusal_key(p)]
    assert r["care_cap"] == FPS * 600 and r["until"] - r["at"] == FPS * 600, r
    assert _refused_wait(m, p, abs_tick(s) + 2 * TICKS_PER_DAY, "0.105.114") is not None
    assert _refused_wait(m, p, abs_tick(s) + FPS * 600 + 1, "0.105.114") is None


@test("the streak's short caps are the longer of game days and real minutes; the safety steps keep game time")
def _():
    s = fort(fps=40)
    sq = Proposal("squad_fill", {"type": "squad_fill", "squad_id": 211, "count": 1}, "x", 4)
    assert rs.cap_ticks(sq, {}, CFG) == 7 * TICKS_PER_DAY
    assert rs.cap_ticks(sq, {}, CFG, s) == 40 * 600          # 20 game days at 40 fps
    assert rs.cap_ticks(doctor(), {}, CFG, s) == 40 * 600
    mood = Proposal("mood_reserve", {"type": "work_order", "recipe": "cloth"}, "x", 3)
    assert rs.cap_ticks(mood, {}, CFG, s) == TICKS_PER_DAY // 2
    # never past the streak's own longest wait (28 days) in a very fast fort
    assert rs.cap_ticks(sq, {}, CFG, fort(fps=900)) == 28 * TICKS_PER_DAY
    # and the hold reads it: a squad held past its 7 game days in a fast fort
    s, m = fort(fps=40), peace()
    why = "no suitable dwarves could be added (25 candidate(s), 0 tried, 3 open place(s), 10 kept out: 9 a post)"
    for _ in range(8):
        record([(sq, {"ok": False, "error": why})], s, m, CFG)
    m.refusals.clear()
    assert rs.wait(m, sq, at(s, 7 * TICKS_PER_DAY + 10), abs_tick(s) + 7 * TICKS_PER_DAY + 10, CFG) is not None
    assert rs.wait(m, sq, at(s, 40 * 600 + 10), abs_tick(s) + 40 * 600 + 10, CFG) is None


@test("a fort-wide no is one family: nobody free for one post holds the others; one post given ends it")
def _():
    keeper = Proposal("staff", {"type": "staff_location", "location_id": 1, "post": "TAVERN_KEEPER"},
                      "the inn tavern has no tavern keeper: give the post to the dwarf best at it", 4)
    scribe = Proposal("staff", {"type": "staff_location", "location_id": 3, "post": "SCRIBE"},
                      "the library has no scribe: give the post to the dwarf best at it", 4)
    s, m = fort(), peace()
    for _ in range(4):
        record([(keeper, {"ok": False, "error": NOBODY})], s, m, CFG)
    fam = m.refusal_streaks[rs.family_key("staff")]
    assert fam["n"] == 4 and fam["family"], fam
    assert rs.wait(m, scribe, s, abs_tick(s) + 1, CFG) is not None, "the scribe's post waits too"
    record([(scribe, {"ok": True, "post": "scribe"})], s, m, CFG)
    assert rs.family_key("staff") not in m.refusal_streaks
    assert rs.wait(m, scribe, s, abs_tick(s) + 1, CFG) is None
    # another reason of the same rule is not the family's
    other = Proposal("staff", {"type": "staff_location", "location_id": 9, "post": "SCRIBE"}, "x", 4)
    for _ in range(4):
        record([(other, {"ok": False, "error": "no such location"})], s, m, CFG)
    assert rs.family_key("staff") not in m.refusal_streaks
    # squads: any squad
    a = Proposal("squad_fill", {"type": "squad_fill", "squad_id": 184, "count": 1}, "x", 4)
    b = Proposal("squad_fill", {"type": "squad_fill", "squad_id": 201, "count": 2}, "x", 4)
    m = peace()
    for k in range(3):
        record([(a, {"ok": False, "error": f"no suitable dwarves could be added ({k} candidate(s), 1 kept out: "
                                           f"{k} breaking down)"})], s, m, CFG)
    assert rs.wait(m, b, s, abs_tick(s) + 1, CFG) is not None
    m.quiet_cycles = 0
    assert rs.wait(m, b, s, abs_tick(s) + 1, CFG) is None, "danger: the squads are never held"


@test("the general back-off keeps a long wait's record for four times that wait (C's storage level)")
def _():
    p = Proposal("build", {"type": "start_project", "kind": "storage"}, "x", 6)
    other = Proposal("homes", {"type": "give_room", "unit_id": 1}, "x", 6)
    m, now = Memory(), abs_tick(fort())
    for _ in range(6):
        note_refusal(m, p, {"ok": False, "error": "no safe level found"}, now)
    assert m.refusals[refusal_key(p)]["n"] == 6
    note_refusal(m, other, {"ok": False, "error": "no room"}, now + 113 * TICKS_PER_DAY)   # prunes the book
    assert m.refusals.get(refusal_key(p), {}).get("n") == 6, m.refusals
    note_refusal(m, p, {"ok": False, "error": "no safe level found"}, now + 113 * TICKS_PER_DAY)
    assert m.refusals[refusal_key(p)]["n"] == 7, "the ladder goes on, not from a day"
    note_refusal(m, other, {"ok": False, "error": "no room"}, now + 113 * TICKS_PER_DAY + TICKS_PER_YEAR)
    assert refusal_key(p) not in m.refusals, "forgotten after a year"


def hosp_fort(thread, cloth, stitch=0, tried=None, cap_at=None, quota=2, fps=None):
    s = fort(fps=fps)
    s["locations"] = {"list": [{"id": 3, "type": "HOSPITAL", "chests": 2,
                                "want": {"thread": quota * 15000, "cloth": quota * 10000}}]}
    s.setdefault("supplies", {})["hospital"] = {"thread": thread, "cloth": cloth}
    s["health"] = {"patients": [], "waiting": stitch, "stitch_wait": stitch}
    rec = {"list": [{"id": 3, "thread": quota * 15000, "cloth": quota * 10000}]}
    if cap_at is not None:
        rec["at"] = cap_at
    if tried is not None:
        rec["tried"] = tried
    s["mood_help"] = {"cancels": [], "hospital_cap": rec}
    return s


def hosp_rule(s):
    props = []
    HS.hospital_stock_rule(s, Memory(), CFG, props, [])
    return props


@test("hospital_stock: a stock that didn't move is the same give or take a piece; each kind on its own")
def _():
    s0 = fort()
    now = abs_tick(s0)
    tried = {"thread": 8, "cloth": 18, "moved": 0, "at": now}
    # B 09:14-09:36: 8/9 thread and 16-18 cloth, nothing moved: nothing proposed (was refused 15 times)
    for t, c in ((8, 18), (9, 17), (7, 16), (8, 19)):
        assert hosp_rule(hosp_fort(t, c, tried=tried)) == [], (t, c)
    # 11 thread came: thread set out, the stuck cloth not
    props = hosp_rule(hosp_fort(11, 18, tried=tried))
    assert props and props[0].action["set_out"] == {"thread": 9}, props[0].action
    # after a week (or 30 real minutes in a fast fort) the same stock is tried again
    late = dict(tried, at=now - 7 * TICKS_PER_DAY - 1)
    assert hosp_rule(hosp_fort(8, 18, tried=late))[0].action["set_out"] == {"thread": 6, "cloth": 10}
    assert hosp_rule(hosp_fort(8, 18, tried=late, fps=FPS)) == [], "30 real minutes at 73 fps"


@test("hospital_stock: a quota raised for a patient at once, lowered back only after a while")
def _():
    now = abs_tick(fort())
    # one patient: raised from the AI's own 2 to 3 at once
    props = hosp_rule(hosp_fort(2, 2, stitch=1, cap_at=now - 10))
    assert props and props[0].action["caps"][0]["thread"] == 3, props
    # the patient gone a cycle later: the AI's 3 kept a while (B: 2 -> 3 -> 2 every few cycles)
    assert hosp_rule(hosp_fort(2, 2, stitch=0, quota=3, cap_at=now - 600)) == []
    props = hosp_rule(hosp_fort(2, 2, stitch=0, quota=3, cap_at=now - 3 * TICKS_PER_DAY - 1))
    assert props and props[0].action["caps"][0]["thread"] == 2, props
    # a quota the AI didn't set (DF's 5): lowered at once
    s = hosp_fort(2, 2, stitch=0, quota=5, cap_at=now - 10)
    s["mood_help"]["hospital_cap"]["list"] = []
    props = hosp_rule(s)
    assert props and props[0].action["caps"][0]["thread"] == 2, props


def gate_fort(ids=(501,), fps=None):
    s = fort(fps=fps)
    e = {"id": 1, "kind": "surface", "x": 108, "y": 149, "z": 10, "closing": True, "closing_days": 9,
         "waiting": {"hatch": 1}, "pending_ids": list(ids)}
    return s, {"parts": {"hatch_covers": 1}}, [e]


def gate_props(s, ent, es, m):
    props, notes = [], []
    G._gate_parts_rule(s, ent, es, 0, props, notes, m)
    return [p for p in props if p.rule == "gate_jobs"]


@test("gate_jobs: the same pieces resumed three times, then once a week or 10 real minutes, in peace")
def _():
    s, ent, es = gate_fort()
    m = peace()
    sent = 0
    for i in range(60):                          # B: a cycle each game day, 60 days
        si = at(s, i * TICKS_PER_DAY)
        if gate_props(si, ent, es, m):
            sent += 1
    assert 5 <= sent <= 12, sent                 # was 30 (every second day)
    # new pieces planned there: at once
    m = peace()
    for i in range(6):
        gate_props(at(s, i * 2 * TICKS_PER_DAY), ent, es, m)
    s2, ent2, es2 = gate_fort(ids=(502,))
    assert gate_props(at(s2, 12 * TICKS_PER_DAY + 1), ent2, es2, m), "other pieces: asked at once"
    # danger: never paced
    m = peace()
    for i in range(6):
        gate_props(at(s, i * 2 * TICKS_PER_DAY), ent, es, m)
    assert not gate_props(at(s, 9 * TICKS_PER_DAY), ent, es, m), "paced: a week after the third try"
    m.quiet_cycles = 0
    assert gate_props(at(s, 9 * TICKS_PER_DAY), ent, es, m), "a threat lately: asked"
    # the streak never holds it (critical)
    assert rs.exempt(Proposal("gate_jobs", {"type": "free_gate_jobs", "entrance_id": 1}, "x", 3), peace(), s, CFG)


@test("gather_trim: after 'all fruit zones' jobs' it waits two weeks (or 20 real minutes)")
def _():
    s = fort()
    trim = Proposal("gather_trim", {"type": "trim_gathering", "keep": CFG["gather_jobs_keep"]}, "x", 5)
    m = Memory()
    note_refusal(m, trim, {"ok": False, "error": "157 of the 157 plant-gathering jobs are fruit zones' (the game "
                                                  "makes them again): nothing to cancel"}, abs_tick(s))
    assert L.gather_zones_only(m, trim, at(s, 3 * TICKS_PER_DAY)) == 11
    assert L.gather_zones_only(m, trim, at(s, 14 * TICKS_PER_DAY + 1)) is None
    assert L.gather_zones_only(m, trim, at(fort(fps=40), 14 * TICKS_PER_DAY + 1)) is not None, "20 min at 40 fps"
    m2 = Memory()
    note_refusal(m2, trim, {"ok": False, "error": "only 3 plant-gathering jobs: nothing to cancel"}, abs_tick(s))
    assert L.gather_zones_only(m2, trim, s) is None


if __name__ == "__main__":
    finish()
