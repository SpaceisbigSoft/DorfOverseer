"""The phases of a fort's life: founding, growth, siege, recovery, prosperity,
decline. A small state machine, read from the timeline and the fort's history
once a cycle. No tokens.

    change = phases.update(state, memory, events)   # -> words when the phase changed
    phases.current(memory)                          # "growth"
    phases.held_kinds(memory)                       # level kinds the phase holds back, with why

What each phase means and does (milestone 4a; set pieces in prosperity come
with milestone 7):

  founding    the first year of the plan in a fort of under 50 dwarves, or
              fewer than 20 dwarves
  growth      the ordinary state
  siege       an invasion in the last 14 days, or invaders or great beasts
              able to reach the dwarves on 3 of the last 5 days (wildlife and
              cavern creatures don't count): no libraries or memorials are
              started (for at most 4 weeks)
  recovery    up to 8 weeks after a siege, or after many deaths in 4 weeks:
              no grand halls (libraries, memorials)
  prosperity  4 weeks with drink and meals at their targets, under 8% unhappy,
              no deaths and no threats near
  decline     the population fell by more than 15% in a season, or more than
              25% are unhappy: no libraries (temples and taverns, which ease
              unhappiness, still go ahead)

A phase lasts at least 14 days (a siege starts at once). The phase and its
history are kept with the chronicle (memory.chronicle["phase"]).
"""

from __future__ import annotations

import timeline
from digest import _d

DAY = 1200
YEAR_TICKS = 403200
MIN_DAYS = 14
# Only grand halls are held back: taverns and temples meet needs that keep
# dwarves happy, which a fort under strain needs most.
HOLDS = {
    "siege": ("library", "memorial"),
    "recovery": ("library", "memorial"),
    "decline": ("library",),
}
SIEGE_HOLD_DAYS = 28       # a long siege stops holding anything back after this
WHY = {
    "siege": "the fort is under siege: no new {kind} until it's over",
    "recovery": "the fort is recovering: no grand halls (a new {kind}) for now",
    "decline": "the fort is in decline: no new {kind} until it steadies",
}
PHASES = ("founding", "growth", "siege", "recovery", "prosperity", "decline")


def _state(memory) -> dict:
    c = memory.chronicle if isinstance(memory.chronicle, dict) else {}
    memory.chronicle = c
    ph = c.get("phase")
    if not isinstance(ph, dict) or (ph.get("now") not in PHASES and ph.get("now") is not None):
        ph = c["phase"] = {"now": None, "since": None, "since_date": None, "log": []}
    if not isinstance(ph.get("log"), list):
        ph["log"] = []
    return ph


def current(memory) -> str:
    """The phase now (read only: never changes memory)."""
    c = memory.chronicle if isinstance(memory.chronicle, dict) else {}
    ph = c.get("phase") if isinstance(c.get("phase"), dict) else {}
    return ph.get("now") if ph.get("now") in PHASES else "growth"


def _now(state: dict) -> int:
    d = state["date"]
    return d["year"] * YEAR_TICKS + d["tick"]


def _avg(memory, metric, a, b, n=7):
    return timeline.avg(memory, metric, a, b, n)[0]


def judge(state: dict, memory, events: list[dict] | None = None) -> str:
    """Which phase the fort is in now, from the evidence (before the minimum
    time is applied)."""
    ph = _state(memory)
    now = _now(state)
    today = now // DAY
    pop = _d(state.get("dwarves")).get("total") or 0
    rows = timeline.window(memory, today - 4, today)
    # a siege: an invasion seen lately, or threats able to reach the dwarves
    # (an older save: forget invasions and danger days that haven't happened yet)
    ph["invasions"] = [t for t in ph.get("invasions") or [] if isinstance(t, int) and t <= now]
    ph["danger_days"] = [t for t in ph.get("danger_days") or [] if isinstance(t, int) and t <= today]
    sieges = [t for t in ph["invasions"] if now - t <= 14 * DAY]
    if any(isinstance(e, dict) and e.get("kind") == "invasion" for e in events or []):
        ph["invasions"] = (ph["invasions"] + [now])[-10:]
        sieges.append(now)
    # invaders or great beasts that can reach the dwarves (not wildlife or cavern creatures)
    oth = _d(state.get("others_on_map"))
    danger = any(isinstance(t, dict) and t.get("can_reach_dwarves") and (t.get("invader") or t.get("great_danger"))
                 for t in oth.get("threats") or [])
    if danger and today not in ph["danger_days"]:
        ph["danger_days"] = (ph["danger_days"] + [today])[-10:]
    threat_days = sum(1 for t in ph["danger_days"] if today - t < 5)
    if sieges or threat_days >= 3:
        return "siege"
    last_siege = max(ph["invasions"]) if ph["invasions"] else None
    deaths_4w = sum(r.get("deaths") or 0 for r in timeline.window(memory, today - 27, today))
    if (last_siege is not None and now - last_siege <= 56 * DAY) or deaths_4w >= max(3, 0.1 * (pop or 1)):
        return "recovery"
    pop_now = _avg(memory, "pop", today - 27, today)
    pop_then = _avg(memory, "pop", today - 111, today - 84)
    unhappy = _avg(memory, "unhappy_pct", today - 27, today)
    if (pop_now is not None and pop_then and pop_now < 0.85 * pop_then) or (unhappy is not None and unhappy > 25):
        return "decline"
    plan = (memory.atlas or {}).get("plan") or {}
    drawn = plan.get("tick")
    young = isinstance(drawn, int) and 0 <= now - drawn < YEAR_TICKS
    if pop < 20:
        return "founding"
    if young and pop < 50 and (plan.get("pop_at_draw") or 0) < 20 and not ph.get("left_founding"):
        return "founding"               # a new fort's first year (not an old fort the AI just took over)
    drink = _avg(memory, "drink_ratio", today - 27, today, 14)
    meals = _avg(memory, "meals_ratio", today - 27, today, 14)
    month = timeline.window(memory, today - 27, today)
    if (drink is not None and meals is not None and drink >= 1 and meals >= 1 and unhappy is not None
            and unhappy < 8 and not deaths_4w and not any((r.get("threats") or 0) > 0 for r in month)):
        return "prosperity"
    return "growth"


def update(state: dict, memory, events: list[dict] | None = None) -> str | None:
    """Move to the phase the evidence says, if the current one has lasted long
    enough (a siege starts at once). Returns the change in words, or None."""
    ph = _state(memory)
    now = _now(state)
    if isinstance(ph.get("since"), int) and ph["since"] > now:
        ph["since"] = now                 # an older save: start the count again
    want = judge(state, memory, events)
    if ph["now"] is None:                 # the first look: no announcement
        d = state.get("date") or {}
        ph.update(now=want, since=now, since_date=f"{d.get('day')} {d.get('month')} y{d.get('year')}")
        if want == "founding":
            return None
        ph["left_founding"] = True
        return None
    if want == ph["now"]:
        if ph.get("since") is None:
            ph["since"] = now
        return None
    held = now - ph["since"] if isinstance(ph.get("since"), int) else MIN_DAYS * DAY
    if want != "siege" and held < MIN_DAYS * DAY:
        return None
    old = ph["now"]
    if old == "founding":
        ph["left_founding"] = True
    d = state.get("date") or {}
    date = f"{d.get('day')} {d.get('month')} y{d.get('year')}"
    ph.update(now=want, since=now, since_date=date)
    ph["log"] = (ph["log"] + [{"phase": want, "from": old, "date": date, "tick": now}])[-20:]
    return {"siege": "a siege: the fort turns to its defence",
            "recovery": "the fort begins to recover",
            "prosperity": "a time of prosperity begins",
            "decline": "the fort is in decline",
            "growth": "the fort is growing again" if old != "founding" else "the founding years are over: the fort grows",
            "founding": "the fort is founding again"}.get(want, want)


def held_kinds(memory, now_tick: int | None = None) -> dict:
    """{level kind: why} the current phase holds back (read only). A siege
    stops holding anything back after SIEGE_HOLD_DAYS."""
    phase = current(memory)
    c = memory.chronicle if isinstance(memory.chronicle, dict) else {}
    ph = c.get("phase") if isinstance(c.get("phase"), dict) else {}
    since = ph.get("since")
    if (phase == "siege" and isinstance(now_tick, int) and isinstance(since, int)
            and now_tick - since > SIEGE_HOLD_DAYS * DAY):
        return {}
    return {k: WHY[phase].format(kind=k) for k in HOLDS.get(phase, ())}


def siege_spans(memory, now: int) -> list[tuple[int, int]]:
    """(start, end) ticks of the sieges in the phase log (the current one ends now)."""
    c = memory.chronicle if isinstance(memory.chronicle, dict) else {}
    ph = c.get("phase") if isinstance(c.get("phase"), dict) else {}
    log = [e for e in ph.get("log") or [] if isinstance(e, dict) and isinstance(e.get("tick"), int)]
    spans = []
    for i, e in enumerate(log):
        if e.get("phase") == "siege":
            end = log[i + 1]["tick"] if i + 1 < len(log) else (now if ph.get("now") == "siege" else e["tick"])
            spans.append((e["tick"], end))
    return spans


def line(memory) -> str:
    c = memory.chronicle if isinstance(memory.chronicle, dict) else {}
    ph = c.get("phase") if isinstance(c.get("phase"), dict) else {}
    return current(memory) + (f" since {ph['since_date']}" if ph.get("since_date") else "")
