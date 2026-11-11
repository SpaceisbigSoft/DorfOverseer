"""(0.105.35) Nothing waits for the player, the "people" group: moods,
care, health, society, locations and visitors. Each Needs you that handed
the player a task the AI can do is now the AI's own action (or a note of
what it does); what DF truly won't let it do stays, with what the AI does
meanwhile.

    python tests/test_r35_people.py
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

import planner  # noqa: E402
from planner import Memory, PLANNER_CONFIG, abs_tick, plan, TICKS_PER_DAY  # noqa: E402
from planner_core import AGENDA_THEMES  # noqa: E402
import planner_society  # noqa: E402
import planner_locations  # noqa: E402
import planner_visitors  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
NEEDS = planner.NEEDS_YOU


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["orders"] = []
    return s


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


def unclaimed(s, days=3, skill="MECHANICS"):
    s["moods"] = {"list": [{"unit_id": 9, "name": "Kib", "mood": "Fey", "craft": True, "skill": skill}]}
    m = Memory()
    m.moods_seen = {"9": abs_tick(s) - days * TICKS_PER_DAY}
    return m


@test("mood unclaimed for days: another of its workshop is built (urgent), no 'is one free and reachable?'")
def _():
    s = fort()
    props, notes = plan(s, unclaimed(s))
    b = [p for p in by_rule(props, "mood") if p.action.get("type") == "start_project"]
    assert b and b[0].action == {"type": "start_project", "kind": "workshops", "shops": ["Mechanics"],
                                 "urgent": True}, [p.action for p in props]
    assert not any(n.startswith(NEEDS) and "Kib" in n for n in notes), notes
    # a workshops level already under way: a note, nothing more
    s2 = fort()
    s2["projects"]["open"] = [{"id": 3, "kind": "workshops", "phase": "dig",
                               "summary": {"workshops": ["Mechanics"]}}]   # (0.105.36) a level with its kind
    props, notes = plan(s2, unclaimed(s2))
    assert not [p for p in by_rule(props, "mood") if p.action.get("type") == "start_project"]
    assert any("Kib" in n and "already being built" in n for n in notes), notes
    # at the AI's cap for the kind: said, not asked of the player
    s3 = fort()
    s3["buildings"]["workshops"]["Mechanics"] = 40
    props, notes = plan(s3, unclaimed(s3))
    assert not [p for p in by_rule(props, "mood") if p.action.get("type") == "start_project"]
    assert any("Kib" in n and "cap" in n and not n.startswith(NEEDS) for n in notes), notes
    # day 1: not yet
    s4 = fort()
    props, _ = plan(s4, unclaimed(s4, days=1))
    assert not [p for p in by_rule(props, "mood") if p.action.get("type") == "start_project"]


@test("care: no cleaner or no diagnoser: the labour given (assign_labor), each its own rule, a week apart")
def _():
    from planner_care import _infection_rule
    s = fort()
    s["infection"] = {"infected": 5, "untreated": 4, "cleaners": 0, "diagnosers": 0, "hospital_zones": 1,
                      "free_beds": 5, "idle_untreated": 3}
    props, notes = [], []
    _infection_rule(s, PLANNER_CONFIG, props, notes)
    acts = {p.rule: p.action for p in props}
    assert acts.get("care_clean") == {"type": "assign_labor", "job": "CLEAN", "count": 2}, acts
    assert acts.get("care_diagnose") == {"type": "assign_labor", "job": "DIAGNOSE", "count": 1}, acts
    assert not any(n.startswith(NEEDS) for n in notes), notes
    for r in ("care_clean", "care_diagnose", "care_feed", "ghost_masons", "ghost_mason"):
        assert PLANNER_CONFIG[f"{r}_cooldown_ticks"] == 7 * TICKS_PER_DAY and r in AGENDA_THEMES, r
    # no proposals (a dry look): a note only
    notes = []
    _infection_rule(s, PLANNER_CONFIG, None, notes)
    assert any("cleaning labour" in n and not n.startswith(NEEDS) for n in notes), notes


@test("health: long waits and no soap are notes of what the AI does, not Needs you")
def _():
    from planner_health import _health_rules
    s = fort()
    now = abs_tick(s)
    s["health"] = {"patients": [{"id": 1, "name": "Urist", "needs": ["diagnosis"]}], "infected": 3}
    s["supplies"]["soap"] = 0
    s["society"]["vacant"] = ["CHIEF_MEDICAL_DWARF"]
    m = Memory()
    m.patient_since = {"1": now - 200 * TICKS_PER_DAY}
    notes = []
    _health_rules(s, m, PLANNER_CONFIG, notes)
    assert not any(n.startswith(NEEDS) for n in notes), notes
    assert any("waited a long time for care" in n and "the AI appoints one" in n for n in notes), notes
    assert any("no soap" in n and "soap rule" in n for n in notes), notes


@test("society: parched dwarves get water-bringers; switches off are notes; vacant offices never 'appoint someone'")
def _():
    s = fort()
    s["society"] = {"vacant": ["BROKER"], "starving": 1, "parched": 3, "hungry_names": ["Urist"],
                    "grazers_unpastured": 4}
    s["settings"]["appoint_nobles"] = False
    s["settings"]["pasture_animals"] = False
    props, notes = [], []
    planner_society._society_notes(s, {}, 194, PLANNER_CONFIG, notes, props)
    assert [p.action for p in by_rule(props, "care_feed")] == [
        {"type": "assign_labor", "job": "FEED_WATER_CIVILIANS", "count": 2}], [p.action for p in props]
    assert not any(n.startswith(NEEDS) for n in notes), notes
    text = " | ".join(notes)
    assert "check they can reach" not in text and "appoint someone" not in text, text
    assert "switched off on the Rules tab" in text and "pasture switch is off" in text, text


@test("the dead: no free tomb and loose coffins are notes; a ghost's missing mason labour is given")
def _():
    s = fort()
    s["dead"] = {"ghosts": 2, "ghost_names": ["A"], "unburied": 3, "free_tombs": 0, "loose_coffins": 2}
    s["supplies"]["slabs"] = 0
    s["supplies"]["memorial_slabs"] = 0
    s["tools"] = dict(s.get("tools") or {}, autoslab=True)
    s["labor"] = {"waiting": [{"labor": "MASON", "holders": 0, "jobs": 3}]}
    props, notes = [], []
    planner_society._dead_notes(s, notes, props, {"engrave_slabs": True}, Memory())
    assert not any(n.startswith(NEEDS) for n in notes), notes
    assert any("no free tomb" in n and "tomb level" in n for n in notes), notes
    assert [p.action for p in by_rule(props, "ghost_mason")] == [
        {"type": "assign_labor", "job": "MASON", "count": 1}], [p.action for p in props]
    # no autoslab in this DFHack: kept (DF makes the engraving job only so), with what the AI does
    s["tools"]["autoslab"] = None
    notes = []
    planner_society._dead_notes(s, notes, [], {"engrave_slabs": True}, Memory())
    you = [n for n in notes if n.startswith(NEEDS) and "ghost" in n]
    assert you and "can't engrave" in you[0] and "meanwhile" in you[0], notes


@test("meeting: with the buttons known the AI answers it (a note); else Needs you says what it does meanwhile")
def _():
    s = fort()
    s["meetings"] = {"screen": "dwarfmode/Diplomacy/Default"}
    s["world"] = {"meeting": {"open": True, "buttons": ["Yes", "No"]}}
    notes = []
    planner_locations._meeting_notes(s, notes)
    assert notes and not notes[0].startswith(NEEDS) and "the AI answers it" in notes[0], notes
    s["world"] = {"meeting": {"open": True, "buttons": []}}
    notes = []
    planner_locations._meeting_notes(s, notes)
    assert notes[0].startswith(NEEDS) and "meanwhile" in notes[0] and "waits for your answers" not in notes[0], notes


@test("a grand-tier petition a fort without grandeur won't build: declined by the AI, not 'left to you'")
def _():
    s = fort()
    s["petitions"] = {"pending": [{"id": 31, "type": "Location", "loc": "GUILDHALL", "tier": 2,
                                   "profession": "MINER"}]}
    props, notes = plan(s, Memory())[:2]
    d = by_rule(props, "petition_answer")
    assert d and d[0].action["id"] == 31 and d[0].action["accept"] is False, [p.action for p in props]
    assert not any("left to you" in n for n in notes), notes


@test("visitors: what DF won't let the AI agree to stays in Needs you, with what the AI does meanwhile")
def _():
    src = (ROOT / "brain" / "planner_visitors.py").read_text(encoding="utf-8")
    assert "wait for you on DF's petitions screen" not in src and "decline them on DF's petitions" not in src
    s = fort()
    s["petitions"] = {"pending": [{"id": 5, "type": "Residency", "applicant": {"on_map": True, "unit": 77}}]}
    s["settings"]["traits"] = {"outsiders": 60}
    m = Memory()
    props, notes = [], []
    planner_visitors._residency_rule(s, m, PLANNER_CONFIG, props, notes)
    you = [n for n in notes if n.startswith(NEEDS)]
    assert you and "meanwhile" in you[0], notes


@test("no Needs you in these files tells the player to check, open, make or appoint it themselves")
def _():
    import re
    bad = ("is one free and reachable", "check they can reach", "check the doctors' labours", "appoint someone",
           "Make a meeting-area", "bury the body in a coffin", "is the way from the workshop", "make it, dig it",
           "open the way, or bring it in", "assign them to a pasture zone", "yours to judge", "left to you (a fort")
    for f in ("planner_society", "planner_moods", "planner_visitors", "planner_health", "planner_care",
              "planner_locations"):
        src = (ROOT / "brain" / f"{f}.py").read_text(encoding="utf-8")
        for b in bad:
            assert b not in src, (f, b)
        assert len(re.findall(r"\bask_player\(", src)) <= 6, f


if __name__ == "__main__":
    finish()
