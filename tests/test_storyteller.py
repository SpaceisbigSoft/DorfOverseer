"""Tests for brain/storyteller.py (the AI-written chronicle), with a fake backend.

    python tests/test_storyteller.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

import chronicle  # noqa: E402
from backends import Reply  # noqa: E402
from planner import Memory  # noqa: E402
from storyteller import maybe_tell  # noqa: E402
from tokens import TokenBank  # noqa: E402

RESULTS = []


def test(name):
    def wrap(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


class FakeBackend:
    def __init__(self, text="The dwarves dug, and the dwarves drank."):
        self.calls, self.text = [], text

    def ask(self, instructions, message, important=False, effort=None):
        self.calls.append((instructions, message, effort))
        return Reply(text=self.text, input_tokens=400, output_tokens=90)


def state(season="spring", year=101, on=True):
    return {"date": {"year": year, "season": season, "day": 1, "month": "Granite", "tick": 0},
            "fort": {"name": "Boltedcastle"}, "dwarves": {"total": 40},
            "settings": {"ai_chronicle": on, "ai_frequency": 0, "ai_effort": 0, "real_day_token_cap": 0}}


@test("off by default and without --ai: no story, nothing spent")
def _():
    m, bank, b = Memory(), TokenBank(balance=1e6), FakeBackend()
    chronicle.add(m, state(), "siege", "goblins came and went")
    assert not maybe_tell(state(on=False), m, bank, b).text and not b.calls
    assert not maybe_tell(state(), m, bank, None).text


@test("on: the first story waits for the season to turn; then one a season, from the plain entries only")
def _():
    m, bank, b = Memory(), TokenBank(balance=1e6), FakeBackend()
    chronicle.add(m, state(), "siege", "goblins came and went")
    assert not maybe_tell(state(), m, bank, b).text and not b.calls       # switched on mid-season
    out = maybe_tell(state("summer"), m, bank, b)
    assert out.text.startswith("The dwarves dug") and len(b.calls) == 1 and out.used == 490, out
    assert b.calls[0][2]["model"] == "small" and b.calls[0][2]["thinking"] == 0
    assert "goblins came and went" in b.calls[0][1] and "Boltedcastle" in b.calls[0][1]
    assert bank.total_used == 490
    assert chronicle._state(m)["entries"][-1]["k"] == "story"
    assert not maybe_tell(state("summer"), m, bank, b).text and len(b.calls) == 1    # once a season
    maybe_tell(state("autumn"), m, bank, b)
    assert "The dwarves dug" not in b.calls[1][1]                          # stories aren't retold


@test("never from the emergency reserve, and never past the real-world daily cap")
def _():
    m, b = Memory(), FakeBackend()
    chronicle.add(m, state(), "siege", "goblins came and went")
    m.story_season = "y101 spring"
    out = maybe_tell(state("summer"), m, TokenBank(balance=10), b)
    assert not out.text and not b.calls and "skipped" in out.say[0], out.say
    s = state("autumn")
    s["settings"]["real_day_token_cap"] = 100000
    bank = TokenBank(balance=1e6)
    from datetime import date
    bank.real_day, bank.real_day_used = date.today().isoformat(), 99900
    out = maybe_tell(s, m, bank, b)
    assert not out.text and not b.calls and "cap" in out.say[0], out.say


@test("a backend failure costs nothing and doesn't retry all season")
def _():
    class Broken(FakeBackend):
        def ask(self, *a, **k):
            self.calls.append(a)
            raise ConnectionError("offline")
    m, bank, b = Memory(), TokenBank(balance=1e6), Broken()
    chronicle.add(m, state(), "siege", "goblins came and went")
    m.story_season = "y101 spring"
    out = maybe_tell(state("summer"), m, bank, b)
    assert not out.text and "failed" in out.say[0] and bank.total_used == 0
    maybe_tell(state("summer"), m, bank, b)
    assert len(b.calls) == 1


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
