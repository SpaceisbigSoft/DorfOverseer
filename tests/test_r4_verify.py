"""(r4 verify) Failing proofs for the seams of round 4 (k1-k5 merged on r4-merge).

Each test here fails on r4-merge and should pass once its finding is fixed.
Everything offline: fake backends, no model, no network.

    python tests/test_r4_verify.py
"""

from __future__ import annotations

import copy
import json
import os
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from backends import RateLimited, Reply  # noqa: E402
from planner import Memory  # noqa: E402
from tokens import TICKS_PER_DAY, TokenBank  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
INFO = {"recipes": ["brew_drink", "stone_blocks"], "tools": ["autochop", "seedwatch"]}
FAKE_KEY = "sk-ant-api03-VERIFYFAKEKEY0123456789abcdefABCDEF"


class Shadow:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self.old = os.environ.get("DFAI_STRATEGIST_SHADOW")
        os.environ["DFAI_STRATEGIST_SHADOW"] = self.value

    def __exit__(self, *a):
        if self.old is None:
            os.environ.pop("DFAI_STRATEGIST_SHADOW", None)
        else:
            os.environ["DFAI_STRATEGIST_SHADOW"] = self.old


class StoryBackend:
    def __init__(self, exc=None):
        self.calls, self.exc = [], exc

    def ask(self, instructions, message, important=False, effort=None, **kw):
        self.calls.append(1)
        if self.exc:
            raise self.exc
        return Reply(text="The dwarves dug, and the dwarves drank.", input_tokens=400, output_tokens=90)


def story_state(season="summer"):
    return {"date": {"year": 101, "season": season, "day": 1, "month": "Granite", "tick": 0},
            "fort": {"name": "Boltedcastle"}, "dwarves": {"total": 40},
            "settings": {"ai_chronicle": True, "ai_frequency": 0, "ai_effort": 0, "real_day_token_cap": 0}}


def story_memory():
    import chronicle
    m = Memory()
    chronicle.add(m, story_state("spring"), "siege", "goblins came and went")
    m.story_season = "101-spring"            # switched on last season: a story is due now
    return m


# --- W1: shadow mode still opens an outcome entry for the adjustment it never made ----------

@test("W1 shadow: an adjustment the review only advised opens no 'strategist' outcome entry (overseer._note_adjust)")
def _():
    import test_overseer as T
    import overseer
    T._before()
    c = T.FakeClaude(json.dumps({"note": "drink!", "adjust": {"drink_per_dwarf": 12}, "actions": []}))
    with Shadow("1"):
        overseer.one_cycle(T.FakeBridge(), autopilot=True, backend=c)
    rev = T.entries("review")
    assert rev and rev[0].get("shadow") is True and rev[0].get("applied") is False, rev
    opened = [e for e in (T.saved()["memory"].get("outcomes") or {}).get("open", []) if e.get("by") == "strategist"]
    assert not opened, f"shadow review opened an outcome for a change never applied: {opened}"


# --- W2: the storyteller makes its own calls past the back-off and the overage stop ----------

@test("W2 storyteller: no story call while the strategist backs off (here: the 28-day overage stop)")
def _():
    from storyteller import maybe_tell
    m, b = story_memory(), StoryBackend()
    from planner import abs_tick
    now = abs_tick(story_state())          # (fix) the overseer's clock: game ticks since the world began
    m.ai_backoff = {"fails": 1, "wait_days": 28, "until": now + 28 * TICKS_PER_DAY, "since": now,
                    "rate_limited": True, "overage": True, "error": "RateLimited: extra usage"}
    maybe_tell(story_state(), m, TokenBank(balance=1e6), b)
    assert not b.calls, "the chronicle asked the backend during the overage back-off"


@test("W2 storyteller: a story call refused for a rate limit / overage starts the back-off")
def _():
    from storyteller import maybe_tell
    m = story_memory()
    b = StoryBackend(RateLimited("the subscription would use pay-as-you-go extra usage", overage=True))
    maybe_tell(story_state(), m, TokenBank(balance=1e6), b)
    assert len(b.calls) == 1
    bo = m.ai_backoff if isinstance(m.ai_backoff, dict) else {}
    assert bo.get("fails") and bo.get("overage") is True, f"no back-off recorded after an overage drop: {bo}"


# --- W3: error text goes to the journal, the log and memory unscrubbed --------------------

@test("W3 key: a backend error carrying the key (httpx 'Illegal header value') never reaches journal/log/memory")
def _():
    from review import maybe_review

    class Leaky:
        def ask(self, *a, **k):
            # what h11/httpx raise for a key with a stray \r from a .bat 'set' line
            raise RuntimeError(f"Illegal header value b'{FAKE_KEY}\\r'")
    s = copy.deepcopy(BASE)
    s["settings"] = {"traits": {}, "ai_frequency": 100, "ai_effort": 0, "real_day_token_cap": 0}
    m = Memory()
    out = maybe_review(s, m, TokenBank(balance=10 ** 6), Leaky(), INFO, [])
    assert out.journal and out.journal.get("kind") == "review_failed", out.journal
    blob = json.dumps(out.journal) + "\n".join(out.say) + json.dumps(m.ai_backoff)
    assert "sk-ant-" not in blob, "the API key is written to the journal / log / saved memory"


@test("W3 key: load_api_key strips an environment key as it strips the .env one (a trailing \\r)")
def _():
    import backends
    old = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = FAKE_KEY + "\r"
    try:
        assert backends.load_api_key() == FAKE_KEY, repr(backends.load_api_key()[-3:])
    finally:
        if old is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = old


# --- W4: pc_token_cap read from config.json can crash main() or switch the cap off ----------

@test("W4 cap: pc_cap_from never raises (json reads Infinity/NaN) and a fraction does not switch the cap off")
def _():
    import tokens
    for v in (float("inf"), float("nan")):
        try:
            c = tokens.pc_cap_from({"pc_token_cap": v})
        except Exception as e:  # noqa: BLE001
            raise AssertionError(f"pc_cap_from({v}) raised {type(e).__name__}: configure_pc in main() stops the "
                                 "overseer") from None
        assert c > 0, (v, c)
    assert tokens.pc_cap_from({"pc_token_cap": 0.5}) != 0, "0.5 reads as 0 = the PC cap switched off"


# --- W5: a trade step still raisable ---------------------------------------------------

@test("W5 raise: unload_depot (a trade step, hold_classes 'trade and diplomacy') is refused a raise")
def _():
    from strategist import check_answer, STEER_RULES
    assert "unload_depot" in STEER_RULES
    a = check_answer(json.dumps({"note": "x", "actions": [{"type": "raise", "rule": "unload_depot", "why": "y"}]}),
                     set(), set(), set(), {})
    assert not a.steer, f"raise of a trade rule accepted: {a.steer}"


# --- W6: handoff-ai.md on the PC cap ------------------------------------------------------

@test("W6 handoff-ai.md: names the PC-wide cap's real keys (pc_token_cap, its file) and plan_ratio")
def _():
    text = (ROOT / "handoff-ai.md").read_text(encoding="utf-8")
    assert "pc_token_cap" in text, "the PC cap is described as the panel's real_day_token_cap"
    assert "plan_ratio" in text, "says token_ratio feeds ai_plan; it is bank.plan_ratio"


# --- W7: tokens.py docstring escape ---------------------------------------------------------

@test("W7 tokens.py compiles without a SyntaxWarning (the '\\D' in default_pc_file's docstring)")
def _():
    src = (ROOT / "brain" / "tokens.py").read_text(encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        compile(src, "tokens.py", "exec")


if __name__ == "__main__":
    finish()
