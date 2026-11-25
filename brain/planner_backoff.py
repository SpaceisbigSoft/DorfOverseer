"""(item4, 0.105.109) The back-offs for answers that come back the same: an
action's "wait" answer word for word (unload_depot), and a no-effect streak
judged by a count that didn't drop (gather_trim). Kept out of
planner_core_refusals so planner_core's names stay as pinned (tests/test_r7_d3.py)."""

from __future__ import annotations
import re


# (item4) actions whose "wait" answer backs off when it comes back the same:
# 2 days, then 4, 8 ... at most WAIT_BACKOFF_MAX_DAYS (B, 24 Nov: unload_depot
# answered "4 item(s) are being hauled out of the depot" 107 times in 2 hours,
# the same 4 items on a job for hours, every 2 days of a fast game)
WAIT_BACKOFF_TYPES = {"unload_depot"}
WAIT_BACKOFF_MAX_DAYS = 28


def _first_int(text) -> int | None:
    m = re.search(r"\d+", str(text or ""))
    return int(m.group()) if m else None


# (item4) rules whose "same reason" is a count that didn't drop (by a fifth)
# since the streak began, not the very same words: gather_trim's reason
# carries the food a dwarf too, which moves each cycle (B, 24 Nov: "135
# plant-gathering jobs wait ... cancel all but 20" done 29 times in 1.5 hours,
# DF making the jobs again each time)
NO_EFFECT_COUNT = {"gather_trim": lambda p: _first_int(getattr(p, "reason", ""))}
NO_EFFECT_DROP = 0.8


def _no_effect_same(p, rec: dict) -> bool:
    count = NO_EFFECT_COUNT.get(p.rule)
    if count is None:
        return rec.get("reason") == p.reason
    c, was = count(p), rec.get("count")
    return isinstance(c, int) and isinstance(was, int) and c >= was * NO_EFFECT_DROP


# (0.105.112 item7) a hospital post while patients wait for care: its "nobody
# free" asked again once a game day (never the 32-84 days of the back-off: a
# dwarf may be free tomorrow and the surgeon's patient is waiting)
CARE_POSTS = {"DOCTOR", "SURGEON", "DIAGNOSTICIAN", "BONE_DOCTOR", "CHIEF_MEDICAL_DWARF"}
CARE_POST_MAX_DAYS = 1


def care_post(p) -> bool:
    a = getattr(p, "action", None)
    a = a if isinstance(a, dict) else {}
    return (a.get("type") == "staff_location" and str(a.get("post") or "").upper() in CARE_POSTS
            and "need care" in str(getattr(p, "reason", "") or ""))


# (0.105.115 item20) waits measured in real time too. A game day is 1200
# ticks; at the 100+ fps of a small fort (E, 25 Nov: perf.fps 109, a game day
# ~15-25 s) a cap of a day or a week asked the game again every few seconds:
# E's hospital asked "nobody free" for its doctor 217 times in 2.5 h, once a
# game day. A short cap (a care post, an answer to wait, a defence step in
# peace) is now the longer of its game days and REAL_CAP_MINUTES real minutes,
# at the fps the bridge measured (state perf.fps); without a measure, game days only.
REAL_CAP_MINUTES = 10
FPS_MAX = 1000          # a reading past this is taken as this (a paused or odd frame)


def fps(state) -> float | None:
    """The game's frames (ticks) a real second, as the bridge read it, or None."""
    perf = state.get("perf") if isinstance(state, dict) else None
    v = perf.get("fps") if isinstance(perf, dict) else None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
        return None
    return float(min(v, FPS_MAX))


def real_ticks(state, minutes: float) -> int:
    """Ticks in `minutes` real minutes at the fort's fps (0 when unknown)."""
    f = fps(state)
    return int(f * 60 * minutes) if f else 0


def care_cap_ticks(state, ticks_per_day: int, days: float = CARE_POST_MAX_DAYS) -> int:
    """(item20) A hospital post's longest wait while patients wait: a game day,
    or REAL_CAP_MINUTES real minutes in a fort fast enough that a day is less."""
    return max(int(days * ticks_per_day), real_ticks(state, REAL_CAP_MINUTES))


def repeat_book(memory, name: str) -> dict:
    """(item20) A rule's own record of what it tried (Memory.repeat_book[name])."""
    if memory is None:
        return {}
    b = getattr(memory, "repeat_book", None)
    if not isinstance(b, dict):
        b = {}
        try:
            memory.repeat_book = b
        except AttributeError:
            return {}
    if not isinstance(b.get(name), dict):
        b[name] = {}
    return b[name]
