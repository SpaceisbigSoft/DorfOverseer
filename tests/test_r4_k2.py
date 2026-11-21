"""(r4 k2) The strategist made safe to switch on, three of A7's bugs:

  B5  check_answer never raises, whatever the reply's JSON shape; an odd part
      is refused with a reason and the rest is kept.
  B8  a failing or rate-limited backend backs off: counted, doubling waits up
      to a cap, a note in the journal, reset by a call that works; never
      asked every game day.
  B9  the default backend is the subscription: an API key in the environment
      is used only when config.json says "api".

Everything offline: the backends and the Agent SDK are fakes.

    python tests/test_r4_k2.py
"""

from __future__ import annotations

import asyncio
import copy
import itertools
import json
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
import backends  # noqa: E402
from backends import Reply  # noqa: E402
from planner import Memory, PLANNER_CONFIG  # noqa: E402
from strategist import check_answer  # noqa: E402
from tokens import TICKS_PER_DAY, TokenBank  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
RECIPES = {"brew_drink", "stone_blocks"}
TOOLS = {"autochop", "seedwatch"}
BUILD = {"level_kinds": ["bedrooms", "dining", "storage", "workshops", "temple", "memorial", "jail"],
         "stockpiles": ["food"], "workshops": ["still"], "digging_ids": [3], "memorials": ["Urist"]}
INFO = {"recipes": sorted(RECIPES), "tools": sorted(TOOLS)}

ODD = [None, 0, -3, 2.5, 1e308, True, "", "x", [], [1], ["brew_drink"], [[1]], [{}], {}, {"a": 1}, {"x": [1]}]
FIELDS = ("note", "adjust", "actions", "want", "season", "design", "blueprint")
ACTION_TYPES = ("work_order", "tool", "civ_alert", "start_project", "set_style", "cancel_project",
                "cancel_work_order", "raise", "hold")
ACTION_KEYS = ("type", "recipe", "amount", "name", "enabled", "on", "kind", "rooms", "room_size", "tables",
               "piles", "shops", "beds", "coffins", "bookcases", "size", "project_id", "order_id", "rule",
               "why", "days", "guide", "hall", "palette", "temple", "gate", "smooth", "statues", "entry_doors")
DESIGN_CTXS = (None, {"ask": "language", "stones": set(), "names": set(), "kinds": set()},
               {"ask": "blueprint", "site_ids": ["s1"]})


UNREAD: list = []      # refusals for a part that raised inside: each a bug to fix, not a shape refused


def check(obj, ctx=None):
    text = obj if isinstance(obj, str) else json.dumps(obj)
    a = check_answer(text, RECIPES, TOOLS, {7}, BUILD, shown={"farm_plots"},
                     **({"design_ctx": ctx} if ctx else {}))
    UNREAD.extend((text[:120], r) for r in a.rejected if "could not be read" in r)
    return a


def review_state(freq=100):
    s = copy.deepcopy(BASE)
    s["settings"] = {"traits": {}, "ai_frequency": freq, "ai_effort": 0, "real_day_token_cap": 0}
    return s


# --- B5 -----------------------------------------------------------------------------

@test("B5: the audit's four replies are refused with a reason, not raised")
def _():
    cases = [
        ({"actions": [{"type": "work_order", "recipe": ["brew_drink"], "amount": 5}]}, "work_order: unknown recipe"),
        ({"actions": [{"type": "tool", "name": {"a": 1}, "enabled": True}]}, "tool: not allowed"),
        ({"actions": [{"type": "start_project", "kind": ["bedrooms"]}]}, "start_project: unknown kind"),
        ({"season": {"choice": ["keep"]}}, "season: unknown choice"),
        ({"season": {"choice": {"raise": "tavern"}}}, "season: unknown choice"),
        ({"actions": [{"type": "work_order", "recipe": {"r": 1}, "amount": 5}]}, "work_order: unknown recipe"),
    ]
    for obj, words in cases:
        a = check(obj)
        assert not a.actions and a.season is None, (obj, a)
        assert any(r.startswith(words) for r in a.rejected), (obj, a.rejected)


@test("B5: a part of the wrong shape is refused by name; the good parts are kept")
def _():
    a = check({"note": 5, "adjust": [1, 2], "want": "needs", "actions": {"type": "civ_alert"}})
    for words in ("note: not text", "adjust: not an object", "want: not a list", "actions: not a list"):
        assert any(r.startswith(words) for r in a.rejected), (words, a.rejected)
    a = check({"note": "ok", "actions": [{"type": "work_order", "recipe": [1], "amount": 2},
                                         {"type": "work_order", "recipe": "brew_drink", "amount": 2}]})
    assert a.note == "ok" and a.actions == [{"type": "work_order", "recipe": "brew_drink", "amount": 2}], a
    assert len(a.rejected) == 1, a.rejected
    # a refusal never copies a huge object out
    a = check({"actions": [{"type": "work_order", "recipe": ["x" * 5000], "amount": 1}]})
    assert all(len(r) < 200 for r in a.rejected), a.rejected


@test("B5: fuzz: every field and every action key with lists, dicts, numbers and nulls never raises")
def _():
    n = 0
    for f, v, ctx in itertools.product(FIELDS, ODD, DESIGN_CTXS):
        check({f: v}, ctx)
        n += 1
    for t, k, v in itertools.product(ACTION_TYPES, ACTION_KEYS, ODD):
        for kind in ("bedrooms", "storage", "workshops", "temple", "memorial", "jail"):
            check({"actions": [{"type": t, "kind": kind, k: v}]})
            n += 1
    for v in ODD:
        check({"actions": [v, {"type": v}]})
        for k in ("choice", "name", "line", "why"):
            check({"season": {"choice": "keep", k: v}})
        check({"adjust": {"drink_per_dwarf": v}})
        for ctx in DESIGN_CTXS[1:]:
            check({"design": v, "blueprint": v}, ctx)
            check({"design": {"x": v}, "blueprint": {"bp": {"v": v, "levels": v, "legend": v, "zone": v},
                                                     "site": v, "name": v}}, ctx)
            check({"blueprint": {"bp": {"v": 1, "levels": [{"grid": v}], "legend": {"a": v},
                                        "zone": [{"kind": v, "level": v}], "finish": {"smooth": v}},
                                 "site": "s1", "name": "Ok"}}, ctx)
        n += 8
    for text in ("[1, 2]", "null", "5", '"x"', "{", "", "{}", '{"actions": null}'):
        a = check(text)
        assert isinstance(a.rejected, list)
    assert n > 10000, n
    assert not UNREAD, UNREAD[:5]      # every odd shape refused by its own check, none by the safety net


@test("B5: check_answer survives a checker that raises inside it (each part read on its own)")
def _():
    import strategist
    real = strategist._check_action

    def boom(*a, **k):
        raise KeyError("inside")
    strategist._check_action = boom
    try:
        a = check({"note": "n", "adjust": {"drink_per_dwarf": 3},
                   "actions": [{"type": "work_order", "recipe": "brew_drink", "amount": 2}]})
    finally:
        strategist._check_action = real
        UNREAD.clear()
    assert a.note == "n" and a.adjust and not a.actions, a
    assert any("could not be read (KeyError)" in r for r in a.rejected), a.rejected


@test("B5: a review whose reply had a list for a recipe ends with a review line (season waits, events cleared)")
def _():
    from review import maybe_review

    class Claude:
        calls = 0

        def ask(self, instructions, message, important=False, effort=None):
            Claude.calls += 1
            return Reply(text='{"note":"odd","actions":[{"type":"work_order","recipe":["brew_drink"],"amount":5}],'
                              '"season":{"choice":["keep"]}}', input_tokens=3000, output_tokens=100, model="m")

    s, m, bank = review_state(), Memory(), TokenBank()
    m.pending_kinds = []
    out = maybe_review(s, m, bank, Claude(), INFO, [])
    assert Claude.calls == 1 and out.journal and out.journal["kind"] == "review", out.journal
    assert any("unknown recipe" in r for r in out.journal["rejected"]), out.journal["rejected"]
    assert not out.proposals


# --- B8 -----------------------------------------------------------------------------

class Failing:
    def __init__(self, exc=None):
        self.calls, self.exc = [], exc or ConnectionError("no network")

    def ask(self, instructions, message, important=False, effort=None, **kw):
        self.calls.append(1)
        raise self.exc


class Working:
    calls = 0

    def ask(self, instructions, message, important=False, effort=None, **kw):
        Working.calls += 1
        return Reply(text='{"note":"fine","actions":[]}', input_tokens=3000, output_tokens=100, model="m")


def day_loop(backend, days, s=None, m=None, bank=None):
    """maybe_review once a game day; returns (state, memory, bank, [(day, journal)])."""
    from review import maybe_review
    s, m, bank = s or review_state(), m or Memory(), bank or TokenBank(balance=10 ** 6)
    seen = []
    for d in range(days):
        out = maybe_review(s, m, bank, backend, INFO, [])
        if out.journal and out.journal.get("kind") in ("review", "review_failed"):
            seen.append((d, out.journal))
        s["date"]["tick"] += TICKS_PER_DAY
        if s["date"]["tick"] >= 403200:
            s["date"]["tick"] -= 403200
            s["date"]["year"] += 1
    return s, m, bank, seen


@test("B8: a failing backend is not asked every game day: counted, waits double to the cap")
def _():
    first, most = PLANNER_CONFIG["r4k2_backoff_first_days"], PLANNER_CONFIG["r4k2_backoff_max_days"]
    assert 1 < first <= most
    f = Failing()
    s, m, bank, seen = day_loop(f, 120)
    days = [d for d, _ in seen]
    assert all(j["kind"] == "review_failed" for _, j in seen)
    assert len(f.calls) == len(seen) and len(f.calls) <= 9, (len(f.calls), days)
    gaps = [b - a for a, b in zip(days, days[1:])]
    want = [min(most, first * 2 ** i) for i in range(len(gaps))]
    assert gaps == want, (gaps, want)
    last = seen[-1][1]["backoff"]
    assert last["fails"] == len(f.calls) and last["wait_days"] == most and not last["rate_limited"], last
    assert m.ai_backoff["fails"] == len(f.calls)
    # kept across a restart (the memory is saved)
    assert Memory.from_dict(json.loads(json.dumps(m.to_dict()))).ai_backoff == m.ai_backoff


@test("B8: a call that works ends the back-off (said in the journal); the next failure starts at the first wait")
def _():
    f = Failing()
    s, m, bank, seen = day_loop(f, 15)
    fails = m.ai_backoff["fails"]
    assert fails >= 3, fails
    s, m, bank, seen = day_loop(Working(), 40, s, m, bank)
    ok = [j for _, j in seen if j["kind"] == "review"]
    assert ok and ok[0]["backoff_cleared"]["fails"] == fails, ok[:1]
    assert m.ai_backoff == {} and "backoff_cleared" not in (ok[1] if len(ok) > 1 else {})
    f2 = Failing()
    s, m, bank, seen = day_loop(f2, 1, s, m, bank)
    # the routine may not be due on that day: run on until the first failure
    while not f2.calls:
        s, m, bank, seen = day_loop(f2, 1, s, m, bank)
    assert m.ai_backoff["fails"] == 1 and m.ai_backoff["wait_days"] == PLANNER_CONFIG["r4k2_backoff_first_days"]


@test("B8: a rate or usage limit waits at least the limit's days; read from either backend's error")
def _():
    from backends import RateLimited, is_rate_limit
    f = Failing(RateLimited("usage limit reached"))
    s, m, bank, seen = day_loop(f, 3)
    bo = seen[0][1]["backoff"]
    assert bo["rate_limited"] and bo["wait_days"] >= PLANNER_CONFIG["r4k2_backoff_limit_days"], bo
    assert len(f.calls) == 1

    class RateLimitError(Exception):          # the anthropic package's name
        pass

    class Status(Exception):
        status_code = 429
    assert is_rate_limit(RateLimitError("x")) and is_rate_limit(Status("x"))
    assert not is_rate_limit(ConnectionError("no network")) and not is_rate_limit(ValueError("bad"))


def fake_sdk(messages):
    """A stand-in claude_agent_sdk whose query() yields `messages`."""
    mod = types.ModuleType("claude_agent_sdk")

    class ClaudeAgentOptions:
        def __init__(self, **kw):
            self.kw = kw

    class ResultMessage:
        def __init__(self, **kw):
            self.is_error, self.result, self.usage, self.api_error_status = False, "", {}, None
            self.__dict__.update(kw)

    class RateLimitInfo:
        def __init__(self, status):
            self.status = status

    class RateLimitEvent:
        def __init__(self, status):
            self.rate_limit_info = RateLimitInfo(status)

    async def query(prompt, options):
        for make in messages:
            yield make(mod)

    mod.ClaudeAgentOptions, mod.ResultMessage, mod.RateLimitEvent, mod.query = (
        ClaudeAgentOptions, ResultMessage, RateLimitEvent, query)
    return mod


def ask_sdk(messages):
    old = sys.modules.get("claude_agent_sdk")
    sys.modules["claude_agent_sdk"] = fake_sdk(messages)
    try:
        b = object.__new__(backends.SubscriptionBackend)     # no sandbox folder, no environment change
        b.model, b.model_events, b.model_top = "haiku", "sonnet", "opus"
        return asyncio.run(b._ask("i", "m", False, None))
    finally:
        if old is None:
            sys.modules.pop("claude_agent_sdk", None)
        else:
            sys.modules["claude_agent_sdk"] = old


@test("B8: the subscription path reads the SDK's rate-limit event and the 429 status")
def _():
    from backends import RateLimited
    for msgs in ([lambda m: m.RateLimitEvent("rejected")],
                 [lambda m: m.RateLimitEvent("rejected"), lambda m: m.ResultMessage(is_error=True, result="x")],
                 [lambda m: m.ResultMessage(is_error=True, result="limit", api_error_status=429)]):
        try:
            ask_sdk(msgs)
        except RateLimited:
            pass
        else:
            raise AssertionError(f"not read as a rate limit: {msgs}")
    # a warning is not a refusal: the answer comes
    r = ask_sdk([lambda m: m.RateLimitEvent("allowed_warning"),
                 lambda m: m.ResultMessage(result='{"note":"ok"}', usage={"input_tokens": 5})])
    assert r.text == '{"note":"ok"}' and r.input_tokens == 5
    # another error is an ordinary failure (backs off from the first wait)
    try:
        ask_sdk([lambda m: m.ResultMessage(is_error=True, result="boom", api_error_status=500)])
    except RateLimited:
        raise AssertionError("a 500 is not a rate limit")
    except RuntimeError:
        pass


# --- B9 -----------------------------------------------------------------------------

def which_backend(cfg: dict) -> str:
    class FakeApi:
        name = "api"

        def __init__(self, c):
            pass

    class FakeSub:
        name = "subscription"

        def __init__(self, c):
            pass
    saved = (backends._config, backends.ApiBackend, backends.SubscriptionBackend)
    backends._config, backends.ApiBackend, backends.SubscriptionBackend = (lambda: cfg), FakeApi, FakeSub
    try:
        return backends.get_backend().name
    finally:
        backends._config, backends.ApiBackend, backends.SubscriptionBackend = saved


@test("B9: with no setting (or the old 'auto') the subscription is used, even with a key in the environment")
def _():
    old = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "test-placeholder-not-a-key"
    try:
        assert backends.load_api_key()          # a key is there to be found
        assert which_backend({}) == "subscription"
        assert which_backend({"strategist_backend": "auto"}) == "subscription"
        assert which_backend({"strategist_backend": "subscription"}) == "subscription"
        assert which_backend({"strategist_backend": "api"}) == "api"
        for bad in ("paid", ["api"], 3):
            try:
                which_backend({"strategist_backend": bad})
            except backends.BackendUnavailable:
                pass
            else:
                raise AssertionError(bad)
    finally:
        if old is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = old


if __name__ == "__main__":
    finish()
