"""(0.105.75) The fort's staircases blocked by water: every new level by them
refused for water or magma lately (planner_building_rooms._stairwell_rule
then digs a new stairwell away from them)."""

from __future__ import annotations

from digest import _d
from planner_core import TICKS_PER_DAY

__all__ = ["stairs_blocked", "STAIRS_BLOCKED_RULES", "STAIRS_BLOCKED_DAYS", "STAIRS_BLOCKED_WORDS"]

# the stored reason is cut at 100 characters (planner_refusal_streak.WHY_MAX):
# D's reads "... (under the surface only) (z#: water " (live 22 Nov), so the
# level's own reason is matched by its first word
STAIRS_BLOCKED_WORDS = ("no safe level found near", ": water")
STAIRS_BLOCKED_RULES = 2                 # different rules refused so, lately
STAIRS_BLOCKED_DAYS = 30


def stairs_blocked(memory, now: int) -> list:
    """(0.105.75) The rules whose new levels were all refused lately because
    every level by the fort's staircases meets water or magma (the builder's
    "no safe level found near N staircase(s) ... (zN: water or magma ...)",
    kept in Memory.refusal_streaks). Live 22 Nov, D (the Hermit hold): one
    staircase (x108 y149), a stagnant pool under its first floor at x109 y149
    (elevation 39): arms_forge, bags, build, fishery, industry, homes_dig...
    all refused for seasons; 17 dwarves, unhappy 32%, idle 46%."""
    out = []
    for r in _d(getattr(memory, "refusal_streaks", None)).values():
        r = _d(r)
        why = str(r.get("why") or "")
        at = r.get("at")
        if (all(w in why for w in STAIRS_BLOCKED_WORDS) and isinstance(at, int)
                and 0 <= now - at <= STAIRS_BLOCKED_DAYS * TICKS_PER_DAY and r.get("rule") not in out):
            out.append(r.get("rule"))
    return out
