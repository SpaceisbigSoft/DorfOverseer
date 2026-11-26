"""R29 W9 (Phase 14.3): the AI window (logs/ai-window.json: the strategist on
for one fort for a game year, ending by itself), its caps and per-season
counts, the siege's event review, and the season decision on a current
(0.105.121) live report. No tokens: every backend here is a fake.

    python tests/test_r29_w9.py
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import overseer  # noqa: E402
import ai_window  # noqa: E402
from ai_window import TICKS_PER_YEAR, Capped, Window, WindowClosed  # noqa: E402
from backends import Reply  # noqa: E402
from planner import Memory, TICKS_PER_DAY, plan  # noqa: E402
from review import maybe_review, note_events, snapshot, urgent_allowed  # noqa: E402
from strategist import detect  # noqa: E402
from tokens import TokenBank  # noqa: E402
import test_overseer as T  # noqa: E402   (its fakes and its reset; its tests don't run here)

LIVE = json.loads((ROOT / "tests" / "fixtures" / "w9" / "a-0.105.121-y256-winter.json").read_text(encoding="utf-8"))
DIRS: list = []


def _fresh_dir() -> Path:
    d = Path(tempfile.mkdtemp(prefix="w9-"))
    DIRS.append(d)
    return d


def _before():
    T._before()
    ai_window.WINDOW = Window(_fresh_dir())


test = T.make_test(before=_before) if hasattr(T, "make_test") else T.test


class Fake:
    name = "subscription"

    def __init__(self, text='{"note":"steady"}', used=6000):
        self.text, self.used, self.calls = text, used, []

    def ask(self, instr, msg, important=False, effort=None, **kw):
        self.calls.append((instr, msg, important))
        return Reply(text=self.text, input_tokens=self.used - 300, output_tokens=300, model="fake")


def _state(year=256, tick=303442, season="winter", key_site=1430):
    s = copy.deepcopy(T.BASE)
    s["date"] = dict(s["date"], year=year, tick=tick, season=season)
    return s


def _req(w: Window, req: dict):
    (w._dir() / ai_window.REQUEST_FILE).write_text(json.dumps(req), encoding="utf-8")


def _run(w, state, key="A#1430", cli=None, made=None):
    said, jr = [], []
    made = made if made is not None else []

    def make():
        b = Fake()
        made.append(b)
        return b
    b = w.backend(cli, state, key, make, said.append, jr.append)
    return b, said, jr, made


# --- the window ----------------------------------------------------------------

@test("no request, or \"on\" not true: no backend, nothing made, nothing written")
def _():
    w = ai_window.WINDOW
    b, said, jr, made = _run(w, _state())
    assert b is None and not made and not jr and not (w._dir() / ai_window.STATE_FILE).exists()
    _req(w, {"on": False, "years": 1})
    b, said, jr, made = _run(w, _state())
    assert b is None and not made and not jr


@test("--ai on the command line: its backend as before, the window never makes or caps one")
def _():
    w = ai_window.WINDOW
    _req(w, {"on": True, "years": 1})
    cli = Fake()
    b, said, jr, made = _run(w, _state(), cli=cli)
    assert b is cli and not made and not w.active
    assert w.can_spend(10 ** 9, False) == (True, "")


@test("a request opens one game year on the fort loaded: stamped, journaled, the backend made once and kept")
def _():
    w = ai_window.WINDOW
    _req(w, {"on": True, "years": 1})
    s = _state()
    b, said, jr, made = _run(w, s)
    assert isinstance(b, Capped) and len(made) == 1
    st = w.state()
    start = 256 * TICKS_PER_YEAR + 303442
    assert st["fort"] == "A#1430" and st["start_tick"] == start and st["until_tick"] == start + TICKS_PER_YEAR
    assert jr and jr[0]["kind"] == "ai_window" and jr[0]["event"] == "opened"
    assert any("AI window open" in x and "until y257 winter" in x for x in said), said
    b2, _, jr2, made2 = _run(w, s, made=made)
    assert b2 is b and len(made) == 1 and not jr2


@test("until_year ends at that year's start; a past end is refused, never opened")
def _():
    w = ai_window.WINDOW
    _req(w, {"on": True, "until_year": 257})
    b, said, jr, made = _run(w, _state())
    assert b is not None and w.state()["until_tick"] == 257 * TICKS_PER_YEAR
    w2 = ai_window.WINDOW = Window(_fresh_dir())
    _req(w2, {"on": True, "until_year": 250})
    b, said, jr, made = _run(w2, _state())
    assert b is None and not made and w2.state()["ended"] and jr[0]["event"] == "refused"


@test("the year over: closed with the spend journaled, the backend dropped; the same request never reopens, a new one does")
def _():
    w = ai_window.WINDOW
    _req(w, {"on": True, "years": 1})
    b, said, jr, made = _run(w, _state())
    b.ask("i", "m", important=False)
    b.ask("i", "m", important=True)
    later = _state(year=257, tick=303442 + 1)
    b, said, jr, made = _run(w, later)
    assert b is None
    ended = [e for e in jr if e.get("event") == "ended"]
    assert ended and ended[0]["spent"]["total"] == 12000 and ended[0]["spent"]["calls"] == 2
    assert ended[0]["spent"]["events"] == 1 and "game time is over" in ended[0]["why"]
    assert any("AI window closed" in x and "12,000 tokens" in x for x in said), said
    b, said, jr, made = _run(w, later)
    assert b is None and not made and not jr
    _req(w, {"on": True, "years": 1, "note": "again"})
    b, said, jr, made = _run(w, later)
    assert b is not None and any(e.get("event") == "opened" for e in jr)


@test("\"on\": false or the file removed closes an open window; another fort loaded closes it too")
def _():
    w = ai_window.WINDOW
    _req(w, {"on": True, "years": 1})
    _run(w, _state())
    _req(w, {"on": False, "years": 1})
    b, said, jr, made = _run(w, _state())
    assert b is None and any(e.get("event") == "ended" for e in jr)
    w2 = ai_window.WINDOW = Window(_fresh_dir())
    _req(w2, {"on": True, "years": 1})
    _run(w2, _state())
    (w2._dir() / ai_window.REQUEST_FILE).unlink()
    b, said, jr, made = _run(w2, _state())
    assert b is None and w2.state()["ended"]
    w3 = ai_window.WINDOW = Window(_fresh_dir())
    _req(w3, {"on": True, "years": 1})
    _run(w3, _state())
    b, said, jr, made = _run(w3, _state(), key="B#77")
    assert b is None and "another fort" in w3.state()["ended"]["why"]


@test("caps: a season's routine reviews stop at 80% (the rest kept for events), events to 100%, the whole cap a hard stop")
def _():
    w = ai_window.WINDOW
    _req(w, {"on": True, "years": 1, "max_tokens": 30000, "season_tokens": 20000})
    b, *_ = _run(w, _state())
    assert w.can_spend(6000, False)[0]
    b.ask("i", "m")
    b.ask("i", "m")            # 12,000 this season
    ok, why = w.can_spend(6000, False)
    assert not ok and "season cap" in why and "event reviews" in why
    assert w.can_spend(6000, True)[0]
    b.ask("i", "m", important=True)      # 18,000
    assert not w.can_spend(6000, True)[0]
    # next season: the season's room is back, the window's cap is not
    b, *_ = _run(w, _state(year=257, tick=10, season="spring"))
    ok, why = w.can_spend(13000, True)
    assert not ok and "window's cap" in why, why
    b.ask("i", "m", important=True)      # 24,000
    b.ask("i", "m", important=True)      # 30,000: the cap
    try:
        b.ask("i", "m")
        raise AssertionError("asked past the cap")
    except WindowClosed:
        pass
    b, said, jr, made = _run(w, _state(year=257, tick=20, season="spring"))
    assert b is None and "token cap" in w.state()["ended"]["why"]


@test("the spend by season: counted per game season, each season journaled as it turns; the report says it")
def _():
    w = ai_window.WINDOW
    _req(w, {"on": True, "years": 1})
    b, *_ = _run(w, _state())
    b.ask("i", "m")
    b, said, jr, made = _run(w, _state(year=257, tick=10, season="spring"))
    rows = [e for e in jr if e.get("event") == "season"]
    assert rows and rows[0]["season"] == "256-winter" and rows[0]["tokens"] == 6000 and rows[0]["calls"] == 1
    b.ask("i", "m", important=True)
    seasons = w.state()["spent"]["seasons"]
    assert seasons["256-winter"]["tokens"] == 6000 and seasons["257-spring"]["events"] == 1
    text = ai_window.report(w._dir())
    assert "12,000 tokens, 2 call(s)" in text and "257-spring: 6,000 tokens" in text, text


@test("a broken request or state file never stops the cycle")
def _():
    w = ai_window.WINDOW
    (w._dir() / ai_window.REQUEST_FILE).write_text("{not json", encoding="utf-8")
    b, *_ = _run(w, _state())
    assert b is None
    _req(w, {"on": True, "years": "one", "max_tokens": "lots", "season_tokens": -5, "event_reserve": 7})
    (w._dir() / ai_window.STATE_FILE).write_text("[]", encoding="utf-8")
    b, *_ = _run(w, _state())
    assert b is not None and w.state()["caps"] == {"max_tokens": ai_window.MAX_TOKENS_DEFAULT,
                                                    "season_tokens": 1, "event_reserve": 0.2}
    assert w.state()["until_tick"] - w.state()["start_tick"] == TICKS_PER_YEAR


# --- through the overseer's cycle ---------------------------------------------------

@test("one_cycle: the window's backend reviews this fort (autopilot), a dry run beside it spends nothing")
def _():
    w = ai_window.WINDOW
    _req(w, {"on": True, "years": 1})
    made = []

    def make():
        c = T.FakeClaude()
        made.append(c)
        return c
    old = overseer.make_backend
    overseer.make_backend = make
    try:
        overseer.one_cycle(T.FakeBridge(state=copy.deepcopy(T.BASE)), autopilot=False, backend=None)
        assert not made and not (w._dir() / ai_window.STATE_FILE).exists()
        overseer.one_cycle(T.FakeBridge(state=copy.deepcopy(T.BASE)), autopilot=True, backend=None)
        assert len(made) == 1 and len(made[0].calls) == 1
        assert [e for e in T.entries("ai_window") if e.get("event") == "opened"]
        assert T.entries("review") and w.state()["spent"]["calls"] == 1
        # a year on: closed, and the cycle plans on alone
        s = copy.deepcopy(T.BASE)
        s["date"]["year"] += 1
        s["date"]["tick"] += 1
        overseer.one_cycle(T.FakeBridge(state=s), autopilot=True, backend=None)
        assert len(made[0].calls) == 1
        assert [e for e in T.entries("ai_window") if e.get("event") == "ended"]
    finally:
        overseer.make_backend = old


# --- the review with the window ----------------------------------------------------

def _ai(state):
    s = copy.deepcopy(state)
    s.setdefault("settings", {}).update({"ai_frequency": 0, "ai_effort": 0, "real_day_token_cap": 0})
    return s


@test("maybe_review: a review the window's season cap can't hold is skipped, said and counted, tried again tomorrow")
def _():
    w = ai_window.WINDOW
    _req(w, {"on": True, "years": 1, "season_tokens": 1000})
    s = _ai(LIVE)
    _run(w, s)
    c = Fake()
    out = maybe_review(s, Memory(), TokenBank(), c, {"recipes": ["brew_drink"], "tools": []}, [])
    assert not c.calls and out.journal["kind"] == "review_skipped" and "season cap" in out.journal["why"]
    assert w.state()["spent"]["skipped"] == 1


@test("the live report (fort A, 0.105.121, y256 winter): the season review is asked, its choice checked, shadow and not")
def _():
    import os
    for shadow in ("1", "0"):
        os.environ["DFAI_STRATEGIST_SHADOW"] = shadow
        try:
            s, m, bank = _ai(LIVE), Memory(), TokenBank()
            props, notes = plan(copy.deepcopy(s), m)
            c = Fake(json.dumps({"note": "winter", "season": {"choice": "keep", "why": "steady"}}))
            out = maybe_review(s, m, bank, c, {"recipes": ["brew_drink"], "tools": []}, notes, proposals=props)
            assert len(c.calls) == 1, out.say
            instr, msg, _ = c.calls[0]
            assert "CHARACTER DECISION" in instr and "DATE 1 Moonstone y256 winter" in msg
            assert "MISSING_SECTIONS" not in msg, [x for x in msg.splitlines() if "MISSING" in x]
            assert "ways in 3: 1 levered, 0 shut" in msg
            assert out.journal["season"]["choice"] == "keep" and not out.journal["rejected"], out.journal
            if shadow == "1":
                assert out.journal["shadow"] is True and "season_choice" not in (m.culture or {})
            else:
                assert m.culture["season_choice"]["choice"] == "keep"
        finally:
            os.environ["DFAI_STRATEGIST_SHADOW"] = "0"


# --- the siege's review --------------------------------------------------------------

def _threats(n):
    return [{"invader": True, "can_reach_dwarves": True, "race": "GOBLIN"} for _ in range(n)]


@test("detect: a lone invader (a thief's invasion) is a thief, an army a siege, at the event or walking on later")
def _():
    s = copy.deepcopy(LIVE)
    assert detect(None, s, [{"kind": "invasion", "invaders_now": 1}]) == ["thief"]
    assert "siege" in detect(None, s, [{"kind": "invasion", "invaders_now": 6}])
    prev = snapshot(s)
    assert prev["others_on_map"]["invaders"] == 0
    s2 = copy.deepcopy(s)
    s2["others_on_map"]["threats"] = _threats(8)
    assert "siege" in detect(prev, s2, [])
    assert "siege" not in detect(snapshot(s2), s2, [])          # still there: not a new siege
    old = {"others_on_map": {"threats_that_can_reach_dwarves": 0, "merchants": 0}, "dwarves": {}}
    assert "siege" not in detect(old, s2, [])                    # an older snapshot: no count to compare


@test("a siege mid-year gets its review though the month's event review was used, within the caps")
def _():
    w = ai_window.WINDOW
    _req(w, {"on": True, "years": 1})
    s, m, bank = _ai(LIVE), Memory(), TokenBank()
    _run(w, s)
    info = {"recipes": ["brew_drink"], "tools": []}
    inner = Fake()
    c = Capped(inner, w)                                         # counted to the window, as the cycle's
    c.calls = inner.calls
    maybe_review(s, m, bank, c, info, [])                        # the season's review
    now = s["date"]["tick"]
    s1 = copy.deepcopy(s)
    s1["date"]["tick"] = now + 2 * TICKS_PER_DAY
    note_events(s1, m, bank, [{"kind": "arrival", "own_civ": True}] * 3)   # migrants: an event review
    maybe_review(s1, m, bank, c, info, [])
    assert len(c.calls) == 2 and c.calls[1][2] is True
    s2 = copy.deepcopy(s1)
    s2["date"]["tick"] = now + 6 * TICKS_PER_DAY
    s2["others_on_map"]["threats"] = _threats(8)
    note_events(s2, m, bank, [{"kind": "invasion", "invaders_now": 0}])
    assert any(k["kind"] == "siege" for k in m.pending_kinds), m.pending_kinds
    out = maybe_review(s2, m, bank, c, info, [])
    assert len(c.calls) == 3 and c.calls[2][2] is True and "siege" in out.journal["reason"], out.say
    assert w.state()["spent"]["events"] == 2
    # a second siege a day later waits (one urgent review per 3 days)
    assert not urgent_allowed(bank, s2["date"]["year"] * TICKS_PER_YEAR + s2["date"]["tick"] + TICKS_PER_DAY,
                              ["siege"])


if __name__ == "__main__":
    try:
        finish()
    finally:
        for d in DIRS:
            shutil.rmtree(d, ignore_errors=True)
