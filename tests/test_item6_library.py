"""(item6) Libraries open to visitors, and the true wait of a stopped World-screen run.

 1. The player (26 Nov 00:02): "open". A library stays open to visitors
    (visiting scholars come and write) whatever a theft, a stranger's
    meeting, a claimed artifact or the mayor's rest shut; only a fort that
    keeps to itself (the Outsiders slider) or a visitor's killing of one of
    the fort's own (visitor_danger, heist_lockout_days, the Rules switch
    heist_lockout) shuts it. A library the AI shut before is opened again.
 2. "tried again tomorrow" said the true wait instead (retry_words): a day
    for an interrupted run, STUCK_RETRY_DAYS for a click DF kept missing.

    python tests/test_item6_library.py
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

from planner import PLANNER_CONFIG, TICKS_PER_DAY, Memory, abs_tick, record  # noqa: E402
from planner_visitors import _location_access_rule, note_heists, visitor_danger  # noqa: E402
import planner_missions as PM  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
BOTH = ["VISITORS_ALLOWED", "NON_CITIZENS_ALLOWED"]
SHUT = ["NON_CITIZENS_ALLOWED"]
THEFT = {"kind": "report", "topic": "thief", "text": "The Human baroness consort Lalgi Aspaescu was spotted "
         "sneaking around!  \"You will not stand between me and Oiledgullies the Drips of Helping!\""}
KILL = {"kind": "death", "own_civ": True, "killer": "Lor Kadolmigrur, Scholar", "killer_kind": "outsider",
        "killer_visitor": True}


def town(outsiders=0, library=BOTH) -> dict:
    s = copy.deepcopy(BASE)
    s["settings"]["traits"] = {"outsiders": outsiders}
    s["locations"] = {"count": {}, "built": abs_tick(s), "list": [
        {"id": 1, "type": "INN_TAVERN", "flags": list(BOTH)},
        {"id": 2, "type": "HOSPITAL", "flags": list(BOTH)},
        {"id": 3, "type": "LIBRARY", "flags": list(library)},
        {"id": 4, "type": "TEMPLE", "flags": list(BOTH)}]}
    return s


def rule(s, m, notes=None):
    props = []
    _location_access_rule(s, m, PLANNER_CONFIG, props, notes if notes is not None else [])
    return props


def closing(props):
    return [p for p in props if p.action.get("visitors") is False]


def opening(props):
    return [p for p in props if p.action.get("visitors") is True]


@test("1 a theft shuts the tavern and temple, never the library (visiting scholars come and write)")
def _():
    s, m = town(), Memory()
    assert note_heists(s, m, [THEFT]) == 1 and m.visitor_kills == [] and visitor_danger(s, m, PLANNER_CONFIG) is None
    c = closing(rule(s, m))
    assert len(c) == 1 and c[0].action["ids"] == [1, 4], [p.action for p in c]


@test("1 a visitor who killed a citizen: the library shuts with the rest; 168 days on all of them reopen")
def _():
    s, m = town(), Memory()
    assert note_heists(s, m, [KILL]) == 1
    assert m.visitor_kills and m.visitor_kills[0][1] == "Lor Kadolmigrur", m.visitor_kills
    assert visitor_danger(s, m, PLANNER_CONFIG) == m.visitor_kills[0]
    c = closing(rule(s, m))
    assert len(c) == 1 and c[0].action["ids"] == [1, 3, 4], [p.action for p in c]
    record([(c[0], {"ok": True, "changed": [1, 3, 4]})], s, m)
    later = copy.deepcopy(s)
    later["date"]["tick"] += 169 * TICKS_PER_DAY
    for e in later["locations"]["list"]:
        if e["id"] in (1, 3, 4):
            e["flags"] = list(SHUT)
    later["locations"]["built"] = abs_tick(later)
    assert visitor_danger(later, m, PLANNER_CONFIG) is None
    o = opening(rule(later, m))
    assert len(o) == 1 and sorted(o[0].action["ids"]) == [1, 3, 4], [p.action for p in o]


@test("1 the Rules switch heist_lockout off: a visitor's killing shuts nothing, the library included")
def _():
    s, m = town(), Memory()
    s["settings"]["heist_lockout"] = False
    note_heists(s, m, [KILL])
    assert visitor_danger(s, m, PLANNER_CONFIG) is None and not closing(rule(s, m))


@test("1 a library the AI shut earlier is opened again during a theft lockout, alone, carrying no mayor's rest")
def _():
    s = town(library=SHUT)
    m = Memory(locations_closed=[3])
    m.visitor_shut = {"tick": abs_tick(s) - 10, "until": abs_tick(s) + 40 * TICKS_PER_DAY,
                      "visitors": 4, "meetings": 5, "unheard": 6}
    note_heists(s, m, [THEFT])
    props = rule(s, m)
    o = opening(props)
    assert len(o) == 1 and o[0].action == {"type": "location_access", "ids": [3], "visitors": True}, [p.action for p in o]
    assert "libraries stay open to visitors" in o[0].reason and "the library" in o[0].reason, o[0].reason
    assert closing(props) and 3 not in closing(props)[0].action["ids"]
    before = dict(m.visitor_shut)
    record([(o[0], {"ok": True, "changed": [3]})], s, m)
    assert m.locations_closed == [] and m.visitor_shut == before, (m.locations_closed, m.visitor_shut)
    # with nothing else shut, the plain reopen takes the library too (as before)
    m2 = Memory(locations_closed=[3])
    o = opening(rule(town(library=SHUT), m2))
    assert o and o[0].action["ids"] == [3], [p.action for p in o]


@test("1 a library the AI shut stays shut while a visitor's killing holds, and in a fort that keeps to itself")
def _():
    s = town(library=SHUT)
    m = Memory(locations_closed=[3])
    note_heists(s, m, [KILL])
    props = rule(s, m)
    assert not opening(props), [p.action for p in props]
    closed = town(outsiders=-150)
    c = closing(rule(closed, Memory()))
    assert c and 3 in c[0].action["ids"] and "keeps to itself" in c[0].reason, [p.action for p in c]
    assert not opening(rule(town(outsiders=-150, library=SHUT), Memory(locations_closed=[3])))


@test("1 memory: visitor_kills kept through to_dict / from_dict")
def _():
    m = Memory()
    m.visitor_kills = [[5, "a scholar"]]
    assert Memory.from_dict(m.to_dict()).visitor_kills == [[5, "a scholar"]]


@test("2 retry_words: a day for an interrupted run, STUCK_RETRY_DAYS for a stuck click, a year otherwise")
def _():
    year = PLANNER_CONFIG["mission_retry_ticks"]
    assert PM.retry_words({"reason": "player_busy"}, year) == "tried again in 1 day"
    assert PM.retry_words({"reason": "click_missed"}, year) == "tried again in 1 day"
    stuck = {"step": "site", "reason": "unexpected",
             "why": "still on world/NORMAL after the click (miss 4 this DF session)"}
    assert PM.stuck_click(stuck)
    assert PM.retry_words(stuck, year) == f"tried again in {PM.STUCK_RETRY_DAYS} days"
    assert PM.retry_words({"reason": "not_recorded"}, year) == "tried again in a year"


@test("2 Make contact after a click DF kept missing: the note says the week's wait, not tomorrow")
def _():
    import planner_world as pw
    now = 120 * 403200 + 5000
    s = {"date": {"year": 120, "tick": 5000}, "others_on_map": {"threats_that_can_reach_dwarves": 0},
         "settings": {"traits": {}}, "offices": {"offices": {"MESSENGER": {"held": ["Led Glidedgorges"]}}},
         "missions": {"sites": {"nearest": [{"id": 59, "relation": "NoContact", "dist": 6}]},
                      "send": {"buttons": ["World"], "last_by_goal": {"make_contact": {
                          "result": "stopped", "reason": "unexpected", "step": "site", "site_id": 59,
                          "why": "still on world/NORMAL after the click (miss 4 this DF session)",
                          "tick": now - 2 * TICKS_PER_DAY}}}}}
    orig = pw.player_rules
    try:
        pw.player_rules = lambda st: {**orig(st), "send_messenger": True, "make_contact": True}
        props, notes = [], []
        pw._contact_rule(s, pw.PLANNER_CONFIG, props, notes, None)
        assert props == [] and any(f"tried again in {PM.STUCK_RETRY_DAYS} days" in n for n in notes), notes
        assert not any("tomorrow" in n for n in notes), notes
        # an interrupted one: a day
        s["missions"]["send"]["last_by_goal"]["make_contact"].update(reason="player_busy", why="another screen",
                                                                     tick=now - 100)
        props, notes = [], []
        pw._contact_rule(s, pw.PLANNER_CONFIG, props, notes, None)
        assert props == [] and any("interrupted by the player; tried again in 1 day" in n for n in notes), notes
    finally:
        pw.player_rules = orig


if __name__ == "__main__":
    finish()
