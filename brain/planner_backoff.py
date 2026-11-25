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
