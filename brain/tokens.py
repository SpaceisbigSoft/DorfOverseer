"""The token bank and review scheduler for the AI strategist.

Two sliders on the panel's AI & tokens tab decide everything (ai_plan below):
  How often   Rare .. Normal .. Often  (Extreme: Very rare / Very often)
              -> how often routine reviews come, and how many event reviews
  How long    Short .. Normal .. Long  (Extreme: Very short / Very long)
              -> which model, how much it may think, how long its answer and
                 the fort summary may be
The token bank's daily amount and size follow from the two (with room to
spare); the real-world daily cap stays a hard ceiling you set yourself.

Token bank (settings from the in-game panel):
  - each in-game day adds `tokens_per_game_day`, saved up to `token_bank_max`
  - each review spends what it actually used
  - big events add a one-time top-up (capped per in-game day, with cooldowns)
  - part of the bank is reserved: only event reviews may dip into it
  - an optional cap per real-world day is a hard ceiling on top of all that

Scheduler (activity level 10-100%):
  - routine review every 7 in-game days at 100%, every 14 at 50%, every 70 at 10%
  - event reviews: at most 2 per in-game month at 100%, scaled down with activity

Pure logic plus a small JSON file per fort; no tokens are spent here.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from util import load_json

# (0.99.1, B10) Today's real-world spend across every fort and save on this
# PC: {"day", "used"}. The bank in each save counted only itself, so a reload
# or another fort started the day's cap again. Set by the overseer's main()
# (logs/tokens-today.json); None (tests, imports) keeps the bank's own count.
DAY_FILE: Path | None = None


def pc_used_today(today: date) -> int:
    if DAY_FILE is None:
        return 0
    d = load_json(DAY_FILE, {})
    try:
        return int(d.get("used") or 0) if d.get("day") == today.isoformat() else 0
    except (TypeError, ValueError):
        return 0


def pc_add_today(today: date, used: int) -> None:
    if DAY_FILE is None or used <= 0:
        return
    try:
        DAY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = DAY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"day": today.isoformat(), "used": pc_used_today(today) + int(used)}),
                       encoding="utf-8")
        tmp.replace(DAY_FILE)
    except OSError:
        pass

TICKS_PER_DAY = 1200
TICKS_PER_MONTH = 28 * TICKS_PER_DAY
TICKS_PER_YEAR = 12 * TICKS_PER_MONTH

ROUTINE_DAYS_AT_100 = 7
EVENT_REVIEWS_PER_MONTH_AT_100 = 2
RESERVE_SHARE = 0.25            # of the bank max, kept for event reviews
START_SHARE = 0.5               # a new fort's bank: above the reserve, so reviews can start
TOPUP_DAILY_CAP_SHARE = 0.5     # top-ups per in-game day, as a share of the bank max

# Event top-ups as a share of the bank max, and how many in-game days before the
# same kind of event can top up again.
TOPUPS = {
    "siege": (0.30, 14),
    "great_danger_near": (0.30, 14),
    "citizen_death": (0.15, 3),
    "many_unhappy": (0.15, 7),
    "disaster": (0.15, 7),
    "caravan": (0.05, 14),
    "migrants": (0.05, 14),
    # from announcements
    "strange_mood": (0.05, 7),
    "insanity": (0.10, 7),
    "tantrum": (0.10, 7),
    "ghost": (0.10, 14),
    "crime": (0.05, 14),
    "thief": (0.05, 14),
    "curse": (0.15, 14),
}


@dataclass
class TokenBank:
    balance: float = 0.0
    last_tick: int | None = None
    real_day: str = ""
    real_day_used: int = 0
    last_topup: dict = field(default_factory=dict)      # kind -> abs tick
    topups_by_day: dict = field(default_factory=dict)   # game day number -> tokens added
    last_routine_tick: int | None = None
    event_reviews: list = field(default_factory=list)   # abs ticks of recent event reviews
    total_used: int = 0
    log: list = field(default_factory=list)             # last few spends, for the panel

    @classmethod
    def from_dict(cls, d: dict | None) -> "TokenBank":
        b = cls()
        for k, v in (d or {}).items():
            if hasattr(b, k):
                setattr(b, k, v)
        return b

    def to_dict(self) -> dict:
        return asdict(self)

    # --- accrual ---------------------------------------------------------
    def accrue(self, now_tick: int, settings: dict) -> None:
        """Add the tokens earned since the last call (in-game days elapsed)."""
        cap = settings["token_bank_max"]
        if self.last_tick is None or now_tick < self.last_tick:
            # First run, or an older save was loaded: start at half the max.
            self.balance = min(max(self.balance, cap * START_SHARE), cap)
            self.last_tick = now_tick
            return
        days = (now_tick - self.last_tick) / TICKS_PER_DAY
        self.balance = min(cap, self.balance + days * settings["tokens_per_game_day"])
        self.last_tick = now_tick

    def top_up(self, kind: str, now_tick: int, settings: dict) -> int:
        """One-time extra tokens for a significant event. Returns tokens added."""
        if kind not in TOPUPS:
            return 0
        share, cooldown_days = TOPUPS[kind]
        last = self.last_topup.get(kind)
        if last is not None and 0 <= now_tick - last < cooldown_days * TICKS_PER_DAY:
            return 0
        cap = settings["token_bank_max"]
        day = str(now_tick // TICKS_PER_DAY)
        room_today = cap * TOPUP_DAILY_CAP_SHARE - self.topups_by_day.get(day, 0)
        amount = int(max(0, min(cap * share, room_today, cap - self.balance)))
        if amount <= 0:
            return 0
        self.balance += amount
        self.last_topup[kind] = now_tick
        self.topups_by_day = {day: self.topups_by_day.get(day, 0) + amount}
        return amount

    # --- spending ------------------------------------------------------------
    def _real_day_reset(self, today: date) -> None:
        if self.real_day != today.isoformat():
            self.real_day, self.real_day_used = today.isoformat(), 0

    def can_spend(self, estimate: int, settings: dict, is_event: bool,
                  today: date | None = None) -> tuple[bool, str]:
        today = today or date.today()
        self._real_day_reset(today)
        cap = settings.get("real_day_token_cap") or 0
        used = max(self.real_day_used, pc_used_today(today))     # (B10) every fort on this PC
        if cap and used + estimate > cap:
            return False, f"real-world daily cap reached ({used:,} of {cap:,}, all forts on this PC)"
        reserve = 0 if is_event else settings["token_bank_max"] * RESERVE_SHARE
        if self.balance - estimate < reserve:
            need = "for an event review" if is_event else "above the emergency reserve"
            return False, f"not enough tokens saved {need} ({int(self.balance):,} available)"
        return True, ""

    def spend(self, used: int, now_tick: int, why: str, today: date | None = None) -> None:
        today = today or date.today()
        self._real_day_reset(today)
        self.balance = max(0.0, self.balance - used)
        self.real_day_used += used
        pc_add_today(today, used)
        self.total_used += used
        self.log = (self.log + [{"tick": now_tick, "used": used, "why": why}])[-20:]


# --- the two AI sliders ----------------------------------------------------------

NORMAL_INTERVAL_DAYS = 14        # How often = Normal: a routine review every 2 weeks
NORMAL_EVENTS_PER_MONTH = 1      # and up to 1 event review a month
REVIEW_TOKENS = 3100             # a Normal review: digest + cached instructions + answer
DAYS_PER_YEAR = 336
BUDGET_HEADROOM = 1.5            # the bank fills 1.5x faster than the plan spends
BANK_DAYS = 60                   # and holds 60 days of it
MIN_BANK = 20000
BANK_EVENT_REVIEWS = 5           # (0.105.26) and room for 5 event reviews: a new fort's half-full bank
                                 # clears the reserve for its first review at any slider setting
THINKING_MIN = 1024              # the API's smallest thinking budget
FREQ_WORDS = ("Very rare", "Rare", "Normal", "Often", "Very often")
EFFORT_WORDS = ("Very short", "Short", "Normal", "Long", "Very long")


def slider_word(v: float, words: tuple) -> str:
    """-200..200 (Extreme doubles the slider) -> one of 5 words."""
    return words[0 if v <= -150 else 1 if v <= -50 else 2 if v < 50 else 3 if v < 150 else 4]


def _frequency(settings: dict) -> float:
    if "ai_frequency" in settings:
        return max(-200.0, min(200.0, float(settings.get("ai_frequency") or 0)))
    # an older panel: its activity % (50 = normal, 100 = twice as often)
    activity = max(10, min(100, settings.get("activity") or 50))
    return max(-200.0, min(200.0, 100 * math.log2(activity / 50)))


def ai_plan(settings: dict) -> dict:
    """How often and how hard the strategist thinks, from the two sliders, and
    what that costs. The panel shows the same numbers (lua/gui/ai-overseer.lua
    ai_plan; tests/test_strategist.py checks the two agree)."""
    f = _frequency(settings)
    e = max(-200.0, min(200.0, float(settings.get("ai_effort") or 0)))
    interval = max(1, int(NORMAL_INTERVAL_DAYS * 2 ** (-f / 100) + 0.5))
    events = NORMAL_EVENTS_PER_MONTH * 2 ** (f / 100)
    think_routine = int(e * 20) if e * 20 >= THINKING_MIN else 0
    think_events = int(e * 30) if e * 30 >= THINKING_MIN else 0
    answer = max(600, min(2400, int(1200 * 2 ** (e / 200) + 0.5)))
    base = int(REVIEW_TOKENS * 2 ** (e / 200))
    est_routine, est_event = base + think_routine, base + think_events
    routine_year = DAYS_PER_YEAR / interval
    events_year = 12 * events
    per_year = int(routine_year * est_routine + events_year * est_event)
    per_day = int(math.ceil(per_year / DAYS_PER_YEAR * BUDGET_HEADROOM))
    return {
        "frequency": f, "effort": e,
        "frequency_word": slider_word(f, FREQ_WORDS), "effort_word": slider_word(e, EFFORT_WORDS),
        "interval_days": interval, "events_per_month": events,
        # model sizes: small for routine, large for events; longer thinking
        # moves both up, shorter moves events down
        "model_routine": "large" if e >= 100 else "small",
        "model_events": "small" if e <= -100 else "top" if e >= 200 else "large",
        "thinking_routine": think_routine, "thinking_events": think_events,
        "answer_tokens": answer, "news": max(1, min(8, 4 + int(e // 50))),
        "est_routine": est_routine, "est_event": est_event,
        "reviews_per_year": int(routine_year + events_year + 0.5), "tokens_per_year": per_year,
        "tokens_per_game_day": per_day,
        "token_bank_max": max(MIN_BANK, per_day * BANK_DAYS, BANK_EVENT_REVIEWS * est_event),
    }


def budget_settings(settings: dict) -> dict:
    """The settings the bank works from: the panel's own numbers from an older
    panel, otherwise what the two sliders call for."""
    if "ai_frequency" not in settings and "token_bank_max" in settings:
        return settings
    plan = ai_plan(settings)
    return dict(settings, tokens_per_game_day=plan["tokens_per_game_day"],
                token_bank_max=plan["token_bank_max"])


def _interval_days(how) -> float:
    if isinstance(how, dict):
        return how["interval_days"]
    return ROUTINE_DAYS_AT_100 * 100 / max(10, min(100, how))      # an activity %


def _events_per_month(how) -> float:
    if isinstance(how, dict):
        return how["events_per_month"]
    return EVENT_REVIEWS_PER_MONTH_AT_100 * max(10, min(100, how)) / 100


def routine_interval_ticks(how) -> int:
    """`how` is an ai_plan, or an older activity % (100: weekly, 50: every 2 weeks)."""
    return round(_interval_days(how)) * TICKS_PER_DAY


def routine_due(bank: TokenBank, now_tick: int, how) -> bool:
    if bank.last_routine_tick is None or now_tick < bank.last_routine_tick:
        return True
    return now_tick - bank.last_routine_tick >= routine_interval_ticks(how)


def event_review_allowed(bank: TokenBank, now_tick: int, how) -> bool:
    per_month = _events_per_month(how)
    # Fractional allowances (e.g. 0.6/month at 30%) become "one per N months".
    window = TICKS_PER_MONTH / per_month if per_month < 1 else TICKS_PER_MONTH
    allowed = 1 if per_month < 1 else int(per_month)
    bank.event_reviews = [t for t in bank.event_reviews if 0 <= now_tick - t < window]
    return len(bank.event_reviews) < allowed
