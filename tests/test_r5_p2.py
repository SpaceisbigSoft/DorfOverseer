"""(r5 p2) Honest numbers in the journal.

(a) A ghost laid to rest ("... has been put to rest.", DF's CITIZEN_DEATH,
    and often the unit's death told again) is marked `rest`: never a death
    (crisis.note_deaths / deaths_seen, the timeline and seasons.csv, metrics,
    the scorecard, the strategist) and never a ghost risen (R-B item 11: B
    journaled 11 such deaths; the bridge's `again` is lost when DF restarts).
(b) Crisis mode entered and left, and meetings (opened, answered, left, DF's
    word that the diplomats left), are journal lines of their own (A3 B2,
    B11), read by seen.py.
(c) The truly idle non-soldiers' share (the exit's measure, idle_free over
    the adults outside squads) is recorded per day and per season
    (seasons.csv avg_idle_free_pct); avg_idle_pct was the old idle_adults /
    adults (A3 item 2, stale statement 13: F 45-59% "idle" against a true 3.5%).

    python tests/test_r5_p2.py
"""

from __future__ import annotations

import copy
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))

from harness import make_test, finish  # noqa: E402
import test_overseer as TO  # noqa: E402  (its fake bridge; its tests run only when it is run itself)
from planner import Memory, PLANNER_CONFIG, TICKS_PER_DAY  # noqa: E402

ov = TO.overseer
test = make_test(before=TO._before)
KEY = "AI Test Run#1234"
Y, T = TO.BASE["date"]["year"], TO.BASE["date"]["tick"]

# the shapes seen in the 15-16 Nov run (B, Mörul; A, Zulban)
DEATH = {"kind": "death", "unit_id": 16786, "name": "Mörul Shagogèrith \"Staticlabor\", Recruit",
         "own_civ": True, "animal": False, "hostile": False, "cause": "STRUCK_DOWN", "year": Y, "tick": T - 500}
REST_REPORT = {"kind": "report", "topic": "ghost", "type": "CITIZEN_DEATH", "report_id": 574862,
               "text": "Mörul Shagogèrith, Ghostly Recruit has been put to rest.", "year": Y, "tick": T}


def journal_lines():
    p = ov.JOURNAL
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _lua():
    try:
        from lupa.lua53 import LuaRuntime
    except ImportError:
        return None
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua.execute(r"""
local src = ...
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-reports', 't', env))()
return env
""", (ROOT / "lua" / "ai-reports.lua").read_text(encoding="utf-8"))


# --- (a) a ghost laid to rest -------------------------------------------------------------------

@test("(a) bridge: DF's 'put to rest' (CITIZEN_DEATH) is the topic 'rest', not 'ghost'; a risen ghost still 'ghost'")
def _():
    R = _lua()
    if R is None:
        from harness import skip
        skip("lupa missing")
    assert R.classify("CITIZEN_DEATH", "Zulban Dakostag, Ghostly Axedwarf has been put to rest.") == "rest"
    assert R.classify("GHOST_ATTACK", "Urist, Ghostly Miner has been laid to rest.") == "rest"
    assert R.classify("X", "The ghost of Urist McMiner has risen and is haunting the fortress!") == "ghost"
    # (b) the diplomats' meeting words get a topic of their own
    assert R.classify("X", "The diplomat could not complete a meeting and has left unhappy.") == "meeting"
    assert R.classify("CARAVAN_ARRIVAL", "Merchants from Nish have arrived.") == "caravan"


@test("(a) the overseer: a death told again after DF restarted (no `again`) beside 'put to rest' is a rest: "
      "journaled laid_to_rest, the report topic 'rest'; deaths_seen and the timeline count one death")
def _():
    b = TO.FakeBridge(events=[dict(DEATH)])
    ov.one_cycle(b, autopilot=True)
    b.advance(2)
    ov.MEMORY_CACHE.clear()               # the overseer restarted too: only the saved memory knows
    # DF restarted: the bridge's DEATHS_TOLD is gone and the incident was not read: no `again`
    b._events = [dict(DEATH, tick=T + 2 * TICKS_PER_DAY - 10), dict(REST_REPORT, tick=T + 2 * TICKS_PER_DAY)]
    ov.one_cycle(b, autopilot=True)
    ev = [e["event"] for e in journal_lines() if e.get("kind") == "event"]
    assert [e["kind"] for e in ev] == ["death", "laid_to_rest", "report"], ev
    assert ev[1]["rest"] and ev[2]["topic"] == "rest" and ev[2]["was_topic"] == "ghost", ev
    mem, _ = ov.load(KEY, b, state=b.state())
    assert len(mem.deaths_seen) == 1, mem.deaths_seen
    assert sum((dict(zip(mem.timeline["fields"], r)).get("deaths") or 0) for r in mem.timeline["days"]) == 1
    assert [x[0] for x in mem.dead_told] == [16786], mem.dead_told
    assert sum(1 for x in TO.SAID if x.startswith("Died:") and "Mörul" in x) == 1, [x for x in TO.SAID if "Mörul" in x]
    assert any(x.startswith("Laid to rest:") for x in TO.SAID), TO.SAID[-10:]


@test("(a) mark_rests: a ghost's death, a told unit, a name beside 'put to rest'; a reload forgets deaths after it")
def _():
    import rests
    told = []
    out = rests.mark_rests([dict(DEATH)], told, (Y * 403200) + T)
    assert not out[0].get("rest") and told == [[16786, Y * 403200 + T - 500]], (out, told)
    # the same unit told again: a rest
    assert rests.mark_rests([dict(DEATH)], told, Y * 403200 + T + 10)[0]["rest"]
    # a ghost's own death, and one named by a rest announcement in the batch (another unit id)
    g = rests.mark_rests([dict(DEATH, unit_id=5, ghost=True)], [], 0)[0]
    # (r5 Z1) a death told again: it happened over a day before now
    n = rests.mark_rests([dict(DEATH, unit_id=6), dict(REST_REPORT)], [], Y * 403200 + T + 5000)
    assert g["rest"] and g["again"] and n[0]["rest"] and n[1]["topic"] == "rest", (g, n)
    # an older save loaded (now before the death): the death never happened; told again later it is a death
    told = [[16786, Y * 403200 + T - 500]]
    again = rests.mark_rests([dict(DEATH, tick=T + 100)], told, Y * 403200 + T - 2000)
    assert not again[0].get("rest") and told == [[16786, Y * 403200 + T + 100]], (again, told)
    # switched off: as before
    PLANNER_CONFIG["r5p2_rests"] = False
    try:
        assert rests.mark_rests([dict(REST_REPORT)], [], 0)[0]["topic"] == "ghost"
    finally:
        PLANNER_CONFIG["r5p2_rests"] = True


@test("(a) no reader counts a rest: crisis, metrics (deaths, ghosts), timeline, scorecard, strategist, culture")
def _():
    import crisis
    import culture
    import metrics
    import scorecard
    import strategist
    import timeline
    rest_death = dict(DEATH, rest=True)                 # marked by mark_rests, no `again`
    laid = dict(DEATH, kind="laid_to_rest", was="death")
    s = copy.deepcopy(TO.BASE)
    m = Memory()
    assert crisis.note_deaths(s, m, [rest_death, laid]) == 0 and m.deaths_seen == []
    assert crisis.note_deaths(s, m, [dict(DEATH)]) == 1
    row = metrics.day_row(1, s, [rest_death, dict(REST_REPORT)])
    assert row["citizen_deaths"] == 0 and row["ghosts"] == 0, row
    assert timeline.row_for(s, [rest_death])["deaths"] == 0
    assert "citizen_death" not in strategist.detect(None, s, [rest_death])
    assert "ghost" not in strategist.detect(None, s, [dict(REST_REPORT)])
    h: dict = {}
    culture.note_events(h, [rest_death])
    assert not h.get("citizen_deaths"), h
    date = {"year": Y, "tick": T + 5000, "day": 1, "month": "Granite"}
    entries = [{"kind": "event", "event": rest_death, "date": date},
               {"kind": "event", "event": dict(REST_REPORT), "date": date},       # an old journal's shape
               {"kind": "event", "event": dict(DEATH, unit_id=1), "date": date}]
    j = scorecard.journal_counts(entries, {"year": Y + 1, "tick": 0})
    assert j["reports"].get("ghost", 0) == 0 and j["reports"].get("rest") == 1, j["reports"]
    assert sum(Counter(j["deaths"]).values()) == 1, j["deaths"]


# --- (b) crisis and meetings in the journal -----------------------------------------------------

@test("(b) crisis mode: entering and leaving each queue a journal entry with its date, why and how long")
def _():
    import crisis
    cfg = dict(PLANNER_CONFIG, crisis_min_days=0)
    s = copy.deepcopy(TO.BASE)
    s["dwarves"]["stress"] = {"miserable": 100, "unhappy": 50}
    m, notes = Memory(), []
    assert crisis.update(s, m, cfg, notes)
    e = crisis.crisis_journal(m)
    assert len(e) == 1 and e[0]["step"] == "entered" and e[0]["date"] == s["date"] and "unhappy" in e[0]["why"][0], e
    assert crisis.crisis_journal(m) == []                     # each written once
    s["dwarves"]["stress"] = {}
    s["date"]["tick"] += 3 * TICKS_PER_DAY
    assert crisis.update(s, m, cfg, notes) == []
    e = crisis.crisis_journal(m)
    assert len(e) == 1 and e[0]["step"] == "left" and e[0]["days"] == 3.0 and e[0]["why_was"], e


@test("(b) the overseer writes the crisis entries as journal lines of kind 'crisis'")
def _():
    b = TO.FakeBridge()
    ov.one_cycle(b, autopilot=True)
    mem, bank = ov.load(KEY, b, state=b.state())
    mem.crisis_journal.append({"step": "entered", "why": ["40% unhappy"], "date": {"year": Y, "tick": T}})
    ov.save(KEY, mem, bank, None, b.state())
    ov.MEMORY_CACHE.clear()
    b.advance(1)
    ov.one_cycle(b, autopilot=True)
    lines = [e for e in journal_lines() if e.get("kind") == "crisis"]
    assert len(lines) == 1 and lines[0]["step"] == "entered" and lines[0]["fort"] == KEY, lines
    assert lines[0]["date"] == {"year": Y, "tick": T}, lines      # its own date, not the next cycle's


@test("(b) meetings: open, answer, leave and DF's 'left unhappy' are journal lines; seen.py counts the actions")
def _():
    import planner_meetings as PM
    import seen
    b = TO.FakeBridge()
    ov.one_cycle(b, autopilot=True)                  # LAST_FORT: this fort
    ov.journal_meeting("open_meeting", {"ok": True, "clicking": True, "popups": 1})
    ov.journal_meeting("open_meeting", {"ok": True})                 # nothing waited: no line
    ov.journal_meeting("answer_meeting", {"ok": True, "pressed": True, "answer": "yes", "topic": "ImportAgreement"}, 25)
    ov.journal_meeting("close_meeting", {"ok": True, "screen": "meeting"}, 130)
    ov.journal_meeting("close_meeting", {"ok": True})                # no screen left: no line
    lines = [e for e in journal_lines() if e.get("kind") == "meeting"]
    assert [x["step"] for x in lines] == ["opened", "answered", "left"], lines
    assert all(x["fort"] == KEY and x["date"] for x in lines), lines
    assert lines[1]["result"]["answer"] == "yes" and lines[1]["held_s"] == 25, lines[1]
    rep = PM.meeting_report_lines([{"kind": "report", "topic": "meeting",
                                    "text": "The diplomat could not complete a meeting and has left unhappy."}])
    assert rep and rep[0]["step"] == "diplomats_left", rep
    # the seen ledger reads them as actions (it read only decisions: "open_meeting not yet met" everywhere)
    d = ov.JOURNAL.parent / "seen-fort"
    d.mkdir(exist_ok=True)
    (d / "journal.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    acts = seen.read_actions([d], None)
    assert acts["open_meeting"]["ok"] == 1 and acts["answer_meeting"]["ok"] == 1 and acts["close_meeting"]["ok"] == 1
    PLANNER_CONFIG["r5p2_meeting_journal"] = False
    try:
        assert PM.meeting_entry("open_meeting", {"clicking": True}) is None
    finally:
        PLANNER_CONFIG["r5p2_meeting_journal"] = True


# --- (c) the true idle share ---------------------------------------------------------------------

@test("(c) the truly idle share (idle_free over adults outside squads) per day and season; seasons.csv "
      "avg_idle_free_pct beside the old avg_idle_pct, old rows kept")
def _():
    import memstore
    import metrics
    import outcomes
    import timeline
    s = copy.deepcopy(TO.BASE)
    s["dwarves"].update(adults=100, idle_adults=50, idle_free=3, in_squads=14)
    m = outcomes.measure(s)
    assert m["idle_pct"] == 50.0 and m["idle_free_pct"] == 3.5, m          # F: 45-59% "idle", truly 3.5%
    assert metrics.day_row(1, s, [])["idle_free_pct"] == 3.5
    old = copy.deepcopy(TO.BASE)
    old["dwarves"].pop("idle_free", None)
    assert "idle_free_pct" not in outcomes.measure(old)                    # an older bridge: not made up
    mem = Memory()
    for d in range(timeline.DAYS_PER_SEASON + 2):
        st = copy.deepcopy(s)
        st["date"] = {"year": 200, "tick": d * TICKS_PER_DAY, "day": 1, "month": "Granite"}
        timeline.record(st, mem, [], None)
    season = mem.timeline["seasons"][0]
    assert season["avg"]["idle_free_pct"] == 3.5 and season["avg"]["idle_pct"] == 50.0, season
    key = "Idle Test#7"
    path = memstore.fort_dir(key) / "seasons.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    old_head = [f for f in memstore.SEASON_FIELDS if f != "avg_idle_free_pct"]
    with path.open("w", encoding="utf-8", newline="") as f:      # a file from before: an older season in it
        w = csv.writer(f)
        w.writerow(old_head)
        w.writerow(["799", "winter 199", "84", "0", "0", "60", "60", "5", "4", "5", "4", "1", "2", "48", "900"])
    memstore.log_seasons(key, mem.timeline["seasons"], timeline.season_name)
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert [r["season"] for r in rows] == ["799", "800"], rows
    assert rows[0]["avg_idle_pct"] == "48" and rows[0]["avg_idle_free_pct"] == "", rows[0]
    assert rows[1]["avg_idle_free_pct"] == "3.5" and rows[1]["avg_idle_pct"] == "50.0", rows[1]


if __name__ == "__main__":
    finish()
