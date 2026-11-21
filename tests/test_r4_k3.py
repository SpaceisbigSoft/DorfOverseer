"""(r4 k3) Before the first --ai run: one PC-wide real-day token cap, on by
default (A7 B4); the token plan follows what reviews really cost (A7 B3);
every review's tokens journaled so a digest can sum them per fort per day.

    python tests/test_r4_k3.py
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
import tokens  # noqa: E402
from backends import Reply  # noqa: E402
from planner import Memory  # noqa: E402
from tokens import TokenBank  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
INFO = {"recipes": ["brew_drink", "stone_blocks"], "tools": ["autochop"], "level_kinds": ["bedrooms"],
        "stockpiles": [], "workshops": []}
TODAY = date(2026, 11, 21)


class Fake:
    name = "subscription"

    def __init__(self, text='{"note":"x"}', used_in=None, out=200):
        self.text, self.used_in, self.out, self.calls = text, used_in, out, 0

    def ask(self, instr, msg, important=False, effort=None, **kw):
        self.calls += 1
        n = self.used_in if self.used_in is not None else int((len(instr) + len(msg)) / 2.5)
        return Reply(text=self.text, input_tokens=n, output_tokens=self.out, cache_read_tokens=1000, model="haiku")


def _ai(state, cap=0):
    s = copy.deepcopy(state)
    s.setdefault("settings", {}).update({"ai_frequency": 0, "ai_effort": 0, "real_day_token_cap": cap})
    return s


class PcFile:
    """tokens' module switches pointed at a temporary PC file, put back after."""

    def __init__(self, cap=None, label="DF-AI-A"):
        self.dir = Path(tempfile.mkdtemp())
        self.cap, self.label = cap, label

    def __enter__(self):
        self.saved = (tokens.DAY_FILE, tokens.PC_CAP, tokens.FORT_LABEL)
        tokens.DAY_FILE = self.dir / "tokens-today.json"
        tokens.PC_CAP, tokens.FORT_LABEL = self.cap, self.label
        return self

    def __exit__(self, *a):
        tokens.DAY_FILE, tokens.PC_CAP, tokens.FORT_LABEL = self.saved


# --- B4: one file for the PC, a cap on by default ----------------------------------

@test("B4: configured from an empty config.json, the day file is outside the fort folder and the cap is on")
def _():
    saved = (tokens.DAY_FILE, tokens.PC_CAP, tokens.FORT_LABEL)
    try:
        root = Path(tempfile.mkdtemp()) / "DF-AI-A"
        root.mkdir()
        tokens.configure_pc({}, project_root=root)
        assert tokens.PC_CAP and tokens.PC_CAP > 0 and tokens.PC_CAP == tokens.PC_CAP_DEFAULT
        f = tokens.DAY_FILE.resolve()
        assert root.resolve() not in f.parents, f
        assert tokens.FORT_LABEL == "DF-AI-A"
        assert tokens.day_cap({"real_day_token_cap": 0}) == tokens.PC_CAP_DEFAULT   # the panel's 0 no longer means none
        assert tokens.day_cap({"real_day_token_cap": 100000}) == 100000            # the smaller holds
    finally:
        tokens.DAY_FILE, tokens.PC_CAP, tokens.FORT_LABEL = saved


@test("B4: the default file is under %LOCALAPPDATA%\\DF-AI when that is set")
def _():
    old = os.environ.get("LOCALAPPDATA")
    try:
        os.environ["LOCALAPPDATA"] = str(Path(tempfile.gettempdir()) / "lad")
        assert tokens.default_pc_file() == Path(os.environ["LOCALAPPDATA"]) / "DF-AI" / "tokens-today.json"
        os.environ.pop("LOCALAPPDATA")
        assert tokens.default_pc_file() == Path.home() / ".df-ai" / "tokens-today.json"
    finally:
        if old is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = old


@test("B4: config.json's pc_token_file: six folders' relative paths name one file beside them; a folder gets the file")
def _():
    top = Path(tempfile.mkdtemp())
    files = {tokens.pc_file_from({"pc_token_file": "logs/tokens-today.json"}, top / f"DF-AI-{x}") for x in "ABCDEF"}
    assert files == {top / "logs" / "tokens-today.json"}, files
    assert tokens.pc_file_from({"pc_token_file": str(top / "shared")}) == top / "shared" / "tokens-today.json"
    assert tokens.pc_file_from({"pc_token_file": ""}) == tokens.default_pc_file()
    assert tokens.pc_file_from({"pc_token_file": 5}) == tokens.default_pc_file()


@test("B4: pc_token_cap: a number is kept, 0 switches it off on purpose, a bad value reads as the default")
def _():
    assert tokens.pc_cap_from({"pc_token_cap": 100000}) == 100000
    assert tokens.pc_cap_from({"pc_token_cap": 0}) == 0
    for bad in ("lots", -5, True, None, [1]):
        assert tokens.pc_cap_from({"pc_token_cap": bad}) == tokens.PC_CAP_DEFAULT, bad
    assert tokens.pc_cap_from(None) == tokens.PC_CAP_DEFAULT


@test("B4: what one fort folder spends counts against another's cap (one file), per folder in the file")
def _():
    with PcFile(cap=10000, label="DF-AI-A"):
        a, b = TokenBank(balance=100000), TokenBank(balance=100000)
        s = dict(tokens.budget_settings({"ai_frequency": 0, "ai_effort": 0}), token_bank_max=100000,
                 real_day_token_cap=0)
        a.spend(8000, 0, "routine", today=TODAY)
        tokens.FORT_LABEL = "DF-AI-B"
        ok, why = b.can_spend(5000, s, False, today=TODAY)
        assert not ok and "cap reached" in why and "8,000 of 10,000" in why, why
        b.spend(500, 0, "routine", today=TODAY)
        rec = tokens.pc_today(TODAY)
        assert rec["used"] == 8500 and rec["forts"] == {"DF-AI-A": 8000, "DF-AI-B": 500}, rec
        assert b.can_spend(5000, s, False, today=date(2026, 11, 22))[0]       # a new real day


@test("B4: a review is skipped, and said, when the PC's day cap is reached; no call is made")
def _():
    from review import maybe_review
    with PcFile(cap=5000):
        tokens.pc_add_today(TODAY, 4999, "DF-AI-C")
        c, m = Fake(), Memory()
        out = maybe_review(_ai(BASE), m, TokenBank(), c, INFO, [], today=TODAY)
        assert c.calls == 0
        assert out.journal["kind"] == "review_skipped" and "daily cap reached" in out.journal["why"], out.journal
        assert any("skipped" in x and "cap" in x for x in out.say), out.say


_WORKER = r"""
import sys
from datetime import date
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import tokens
tokens.DAY_FILE = Path(sys.argv[2])
for _ in range(int(sys.argv[4])):
    tokens.pc_add_today(date(2026, 11, 21), 7, sys.argv[3])
"""


@test("B4: six processes adding at once lose no count (the lock), and the file stays whole")
def _():
    d = Path(tempfile.mkdtemp())
    f, script = d / "tokens-today.json", d / "w.py"
    script.write_text(_WORKER, encoding="utf-8")
    n = 40
    ps = [subprocess.Popen([sys.executable, "-I", str(script), str(ROOT / "brain"), str(f), f"DF-AI-{x}", str(n)])
          for x in "ABCDEF"]
    assert all(p.wait(timeout=120) == 0 for p in ps)
    rec = json.loads(f.read_text(encoding="utf-8"))
    assert rec["used"] == 6 * n * 7, rec
    assert rec["forts"] == {f"DF-AI-{x}": n * 7 for x in "ABCDEF"}, rec
    assert not list(d.glob("*.lock")) and not list(d.glob("*.tmp")), list(d.iterdir())


@test("B4: a lock left by a killed process is broken, and the count goes on")
def _():
    with PcFile():
        lock = tokens.DAY_FILE.with_name(tokens.DAY_FILE.name + ".lock")
        lock.write_text("")
        old = os.path.getmtime(lock) - 2 * tokens.LOCK_STALE_S
        os.utime(lock, (old, old))
        tokens.pc_add_today(TODAY, 300)
        assert tokens.pc_used_today(TODAY) == 300 and not lock.exists()


# --- B3: the plan follows what reviews cost ---------------------------------------

@test("B3: ai_plan scales its estimates, the bank's income and size by the learned ratio")
def _():
    st = {"ai_frequency": 0, "ai_effort": 0}
    p1, p2 = tokens.ai_plan(st), tokens.ai_plan(st, 2.0)
    assert abs(p2["est_routine"] - 2 * p1["est_routine"]) <= 1, (p1["est_routine"], p2["est_routine"])
    assert p2["tokens_per_game_day"] > 1.9 * p1["tokens_per_game_day"]
    assert p2["token_bank_max"] >= p1["token_bank_max"]
    assert tokens.ai_plan(st, 99)["est_routine"] == tokens.ai_plan(st, 4.0)["est_routine"]     # bounded
    assert tokens.ai_plan(st, "x")["est_routine"] == p1["est_routine"]
    assert tokens.budget_settings(st, 2.0)["tokens_per_game_day"] == p2["tokens_per_game_day"]


@test("B3: reviews costing twice the plan teach the bank ~2, and its daily income follows")
def _():
    from review import maybe_review
    st = {"ai_frequency": 0, "ai_effort": 0}
    est = tokens.ai_plan(st)["est_routine"]
    bank, m = TokenBank(), Memory()
    s = _ai(BASE)
    base_income = tokens.budget_settings(s["settings"], tokens.plan_ratio(bank))["tokens_per_game_day"]
    for i in range(12):
        bank.balance, bank.last_routine_tick = 10 ** 6, None
        out = maybe_review(s, m, bank, Fake(used_in=2 * est - 200 - 100), INFO, [], today=TODAY)
        assert out.journal and out.journal["kind"] == "review", out.journal
    assert 1.8 < bank.plan_ratio <= 2.0, bank.plan_ratio
    income = tokens.budget_settings(s["settings"], tokens.plan_ratio(bank))["tokens_per_game_day"]
    assert income > 1.7 * base_income, (base_income, income)
    # it is kept with the bank (the save), and an odd stored value reads as 1
    assert TokenBank.from_dict(bank.to_dict()).plan_ratio == bank.plan_ratio
    assert tokens.plan_ratio(TokenBank.from_dict({"plan_ratio": "x"})) == 1.0
    assert tokens.plan_ratio(TokenBank.from_dict({"plan_ratio": 50})) == 1.0


# --- token journaling --------------------------------------------------------------

@test("journal: a review's line carries tokens in/out/total, model, backend, folder and real day")
def _():
    from review import maybe_review
    with PcFile(cap=10 ** 7, label="DF-AI-D"):
        out = maybe_review(_ai(BASE), Memory(), TokenBank(), Fake(used_in=5000, out=300), INFO, [], today=TODAY)
        j = out.journal
        assert j["kind"] == "review"
        assert j["tokens_in"] == 6000 and j["tokens_out"] == 300 and j["tokens"] == 5000 + 300 + 100, j
        assert j["model"] == "haiku" and j["backend"] == "subscription" and j["folder"] == "DF-AI-D", j
        assert j["real_day"] == "2026-11-21" and j["pc_today"] == j["tokens"], j


@test("journal: tokens_by_fort_day sums reviews and stories per fort per real day, ignoring the rest")
def _():
    lines = [{"time": "2026-11-21T10:00:00", "fort": "A#1", "kind": "review", "tokens": 5000},
             {"time": "2026-11-21T11:00:00", "fort": "A#1", "kind": "review", "tokens": 4000},
             {"time": "2026-11-21T12:00:00", "fort": "A#1", "kind": "story", "tokens": 900},
             {"time": "2026-11-22T00:10:00", "fort": "A#1", "kind": "review", "tokens": 100},
             {"time": "2026-11-21T10:00:00", "fort": "B#2", "kind": "review", "tokens": 7000},
             {"time": "2026-11-21T10:00:00", "fort": "B#2", "kind": "review_skipped", "estimate": 9000},
             {"time": "2026-11-21T10:00:00", "fort": "B#2", "kind": "review", "tokens": "lots"},
             "junk", None]
    assert tokens.tokens_by_fort_day(lines) == {("A#1", "2026-11-21"): 9900, ("A#1", "2026-11-22"): 100,
                                                ("B#2", "2026-11-21"): 7000}


if __name__ == "__main__":
    finish()
