"""(0.105.115 item20) planner_gate_jobs: a planned gate's suspended jobs
resumed (planner_gates._gate_parts_rule's free_gate_jobs) paced when DF
suspends them again. Kept out of planner_gates, whose names are pinned
(tests/test_r7_d5.py)."""

from __future__ import annotations

from digest import _d, _l
from planner_core import PLANNER_CONFIG, TICKS_PER_DAY, abs_tick

__all__ = ["GATE_JOBS_TRIES", "GATE_JOBS_PACE_DAYS", "GATE_JOBS_REAL_MINUTES", "gate_jobs_paced"]

# (0.105.115 item20) B, 25 Nov (2.5 h): free_gate_jobs at the hatch over the surface entrance
# 131 times, every second game day (~50 s): "unsuspended 1" 100 times (DF suspends the job
# again: what holds it is past what the AI sees) and 31 "no suspended job at the 1 piece(s)
# planned there". The same pieces resumed GATE_JOBS_TRIES times: then once every
# GATE_JOBS_PACE_DAYS game days or GATE_JOBS_REAL_MINUTES real minutes (the longer), in peace;
# at once again when the pieces planned there change or danger is about
GATE_JOBS_TRIES = 3
GATE_JOBS_PACE_DAYS = 7
GATE_JOBS_REAL_MINUTES = 10


def gate_jobs_paced(s: dict, e: dict, memory) -> bool:
    """(item20) Is this entrance's free_gate_jobs to wait (the same pieces
    resumed GATE_JOBS_TRIES times lately, in peace)? Counts the try when not."""
    if memory is None or not isinstance(e.get("id"), int):
        return False
    from planner_backoff import repeat_book, real_ticks
    from planner_refusal_streak import danger
    book = repeat_book(memory, "gate_jobs")
    k = str(e["id"])
    ids = sorted(i for i in _l(e.get("pending_ids")) if isinstance(i, int))
    now = abs_tick(s)
    rec = _d(book.get(k))
    same = rec.get("ids") == ids and isinstance(rec.get("at"), int) and 0 <= now - rec["at"]
    pace = max(GATE_JOBS_PACE_DAYS * TICKS_PER_DAY, real_ticks(s, GATE_JOBS_REAL_MINUTES))
    if (same and int(rec.get("n") or 0) >= GATE_JOBS_TRIES and now - rec["at"] < pace
            and not danger(memory, s, PLANNER_CONFIG)):
        return True
    if same and now - rec["at"] < PLANNER_CONFIG["rule_cooldown_ticks"]:
        return False        # the rule's cooldown holds it: the same try, not counted again
    book[k] = {"ids": ids, "n": int(rec.get("n") or 0) + 1 if same else 1, "at": now}
    for kk in [x for x, v in book.items() if not isinstance(v, dict) or not isinstance(v.get("at"), int)
               or not 0 <= now - v["at"] < 336 * TICKS_PER_DAY]:
        book.pop(kk, None)
    return False
