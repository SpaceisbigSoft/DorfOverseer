"""(R29, Phase 13b) The brain's side of the World screen: each run's steps
in the journal, the messenger's Make contact followed out and back, and a
click DF kept missing retried in a week instead of a year.

Live (25 Nov): every fort's Make contact sat in a year's block after its 4th
missed click or unread goal of a DF session ("(miss 4 this DF session)",
"(unread 7 ...)"), and the journal had no line for any of the runs.

    python tests/test_r29_world_map_brain.py
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

from planner import Memory, TICKS_PER_YEAR, abs_tick, note_cycle  # noqa: E402
from planner_core import TICKS_PER_DAY  # noqa: E402
import planner_missions as PM  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort(send=None, controllers=None) -> dict:
    s = copy.deepcopy(BASE)
    s["missions"] = {"controllers": controllers or [], "reports": {"n": 0, "unviewed": 0}, "spoils": {"n": 0},
                     "sites": {}, "unknown": [], "squads": [], "targets": [], "raid_sites": {"rows": []}}
    if send is not None:
        s["missions"]["send"] = send
    return s


def outcome(tick, result="stopped", step="goal", reason="goal_unread", why="none of Diplomacy is on New mission",
            results=None, **kw):
    o = {"goal": "make_contact", "site": "Pantswordy", "site_id": 1211, "result": result, "step": step,
         "reason": reason, "why": why, "tick": tick,
         "results": results if results is not None else [
             {"step": "open", "result": "ok", "frame": 4},
             {"step": "site", "result": "ok", "frame": 30, "clicks": 2},
             {"step": "goal", "result": "stop: not_found", "frame": 72, "tries": 21,
              "why": "none of Diplomacy is on New mission"}]}
    o.update(kw)
    return o


def journal_of(m):
    return PM.mission_journal(m)


@test("each World-screen run journalled once, with each step's result; outcomes already there when the memory "
      "first sees them are not")
def _():
    m = Memory()
    s = fort(send={"last_by_goal": {"make_contact": outcome(1000)}})
    t0 = abs_tick(s)
    s["missions"]["send"]["last_by_goal"]["make_contact"]["tick"] = t0 - 50
    note_cycle(copy.deepcopy(s), m)
    assert not [e for e in journal_of(m) if e.get("event") == "send"]          # from before: not again
    s2 = copy.deepcopy(s)
    s2["missions"]["send"]["last_by_goal"]["make_contact"]["tick"] = t0
    notes = note_cycle(copy.deepcopy(s2), m)
    sends = [e for e in journal_of(m) if e.get("event") == "send"]
    assert len(sends) == 1, sends
    e = sends[0]
    assert e["goal"] == "make_contact" and e["step"] == "goal" and e["reason"] == "goal_unread", e
    assert e["steps"] == ["open ok", "site ok (2 click(s))",
                          "goal stop: not_found (read 21 times): none of Diplomacy is on New mission"], e["steps"]
    assert any(n.startswith("World screen: make contact") and "stopped at goal" in n for n in notes), notes
    note_cycle(copy.deepcopy(s2), m)                                           # the same outcome: once
    assert not [x for x in journal_of(m) if x.get("event") == "send"]


@test("a run that set the mission up: 'set up' with every step ok")
def _():
    m = Memory()
    s = fort(send={"last_by_goal": {}})
    note_cycle(copy.deepcopy(s), m)
    steps = [{"step": n, "result": "ok", "frame": 4 * i} for i, n in
             enumerate(("open", "site", "goal", "make_contact", "messenger", "confirm"))]
    s["missions"]["send"]["last_by_goal"]["make_contact"] = outcome(abs_tick(s), result="sent", step="confirm",
                                                                    reason=None, why=None, results=steps)
    notes = note_cycle(copy.deepcopy(s), m)
    e = [x for x in journal_of(m) if x.get("event") == "send"][0]
    assert e["result"] == "sent" and all(w.endswith(" ok") for w in e["steps"]) and len(e["steps"]) == 6
    assert any("set up (" in n for n in notes), notes


@test("the messenger's Make contact followed: out once its controller carries the messenger, back when it is gone; "
      "a leftover of a stopped run never counts")
def _():
    m = Memory()
    c = {"id": 3461425, "goal": "DIPLOMACY", "site_id": 1211, "site": "Pantswordy", "squads": [], "away": 0,
         "epp": [77]}
    left = {"id": 555, "goal": "DIPLOMACY", "site_id": 1211, "squads": [], "away": 0, "epp": [77]}
    send = {"last_by_goal": {"make_contact": {"goal": "make_contact", "result": "stopped", "tick": 1,
                                              "left_ids": [555]}}}
    s = fort(send=send, controllers=[c, left])
    notes = note_cycle(copy.deepcopy(s), m)
    j = journal_of(m)
    outs = [e for e in j if e.get("event") == "out" and e.get("messenger")]
    assert len(outs) == 1 and outs[0]["site_id"] == 1211, j
    assert any("the messenger set off to make contact" in n for n in notes), notes
    assert m.missions_seen["messenger_sent"] == 1 and list(m.missions_seen["trips"]) == ["3461425"]
    note_cycle(copy.deepcopy(s), m)                                           # still out: nothing new
    assert not [e for e in journal_of(m) if e.get("messenger")]
    s2 = copy.deepcopy(s)
    s2["date"]["tick"] += 30 * TICKS_PER_DAY
    s2["missions"]["controllers"] = [left]
    notes = note_cycle(s2, m)
    backs = [e for e in journal_of(m) if e.get("event") == "back" and e.get("messenger")]
    assert len(backs) == 1 and backs[0]["days"] == 30, backs
    assert m.missions_seen["messenger_back"] == 1 and m.missions_seen["trips"] == {}
    assert any("is over after 30 day(s)" in n for n in notes), notes


@test("a Diplomacy controller without a messenger isn't a trip; an unread report judges nothing gone")
def _():
    m = Memory()
    c = {"id": 9, "goal": "DIPLOMACY", "site_id": 1211, "squads": [], "away": 0, "epp": []}
    s = fort(send={}, controllers=[c])
    note_cycle(copy.deepcopy(s), m)
    assert not [e for e in journal_of(m) if e.get("messenger")]
    c["epp"] = [77]
    note_cycle(copy.deepcopy(fort(send={}, controllers=[c])), m)
    assert m.missions_seen["messenger_sent"] == 1
    s3 = fort(send={}, controllers=[])
    s3["missions"].pop("controllers")
    note_cycle(s3, m)
    assert "9" in m.missions_seen["trips"]                                    # not taken for back


@test("a click DF kept missing past 3 a session (site or goal): a week's wait, no longer a year's")
def _():
    site4 = {"result": "stopped", "step": "site", "reason": "unexpected",
             "why": "still on world/NORMAL after 4 click(s) (focus_site 1211) (80 frames) (miss 4 this DF session)"}
    goal7 = {"result": "stopped", "step": "goal", "reason": "not_found",
             "why": "none of Diplomacy is on New mission (unread 7 this DF session)"}
    other = {"result": "stopped", "step": "messenger", "reason": "not_found", "why": "row 1 reads ..."}
    for o in (site4, goal7):
        assert PM.stuck_click(o) and PM.click_missed(o), o
        assert PM.retry_ticks(o, TICKS_PER_YEAR) == 7 * TICKS_PER_DAY
    assert not PM.stuck_click(other) and PM.retry_ticks(other, TICKS_PER_YEAR) == TICKS_PER_YEAR
    # the next-day ones are unchanged
    new = {"result": "stopped", "step": "site", "reason": "click_missed", "why": "still on world/NORMAL after 4 click(s)"}
    assert PM.retry_ticks(new, TICKS_PER_YEAR) == TICKS_PER_DAY


@test("send_steps: words for the journal, cut short, nothing but the bridge's results")
def _():
    o = {"results": [{"step": "site", "result": "stop: unexpected", "clicks": 4,
                      "why": "still on world/NORMAL after 4 click(s) " + "x" * 300}]}
    w = PM.send_steps(o)
    assert len(w) == 1 and w[0].startswith("site stop: unexpected (4 click(s)): still on world/NORMAL") and len(w[0]) < 200
    assert PM.send_steps({}) == [] and PM.send_steps({"results": "junk"}) == []


if __name__ == "__main__":
    finish()
