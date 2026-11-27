"""(F3a) The last full report kept after the AI acts.

Before, any cycle that acted cleared overseer.LAST_FULL, so the next cycle
paid for a whole report (2-6 s of a stopped game on a big fort). Now the
bridge's answer to an action names the sections it changed (`invalidates`,
from CACHE_INVALIDATES in lua/ai-bridge-sections.lua, plus any it called
`stale`); those are marked stale in LAST_FULL and the next pulse asks for
them beside its own (`state --tier pulse --sections a,b`), merging them into
the kept report. An action whose answer names none (one the table doesn't
know, a lost reply, an older bridge) clears LAST_FULL as before: the next
cycle reads the full report. The kept report still ages out after a game
day (overseer.get_state's fresh check).
"""

from __future__ import annotations

KEEP_AFTER_ACTIONS = True     # False: every acting cycle clears the kept report (the old rule)


def invalidated(results) -> list[str] | None:
    """The section names the cycle's actions changed, or None when any action's
    answer doesn't say (the full report is needed). results: [(proposal, reply)]."""
    names: list[str] = []
    for _p, r in results or []:
        inv = r.get("invalidates") if isinstance(r, dict) else None
        if isinstance(inv, dict) and not inv:
            inv = []                      # an empty Lua table comes as {}
        if not isinstance(inv, list) or not all(isinstance(n, str) and n for n in inv):
            return None
        names += [n for n in inv if n not in names]
    return names


def after_actions(last_full: dict, results) -> list[str] | None:
    """After an acting cycle: mark the changed sections stale in the kept
    report, or clear it (None returned) when that can't be known."""
    names = invalidated(results) if KEEP_AFTER_ACTIONS else None
    if names is None or not isinstance(last_full.get("state"), dict):
        last_full.clear()
        return None
    stale = last_full.setdefault("stale", [])
    stale += [n for n in names if n not in stale]
    return list(stale)


def stale(last_full: dict) -> list[str]:
    """The sections the next pulse must read again ([] for none)."""
    s = last_full.get("stale")
    return [n for n in s if isinstance(n, str)] if isinstance(s, list) else []


def has_sections(report, names) -> bool:
    """Whether a report carries every asked section (an older bridge ignores
    --sections: then the full report is read)."""
    return isinstance(report, dict) and all(n in report for n in names or [])


def absorb(last_full: dict, report: dict, names) -> None:
    """The freshly read sections written into the kept report; nothing stale left."""
    import json
    full = last_full.get("state")
    if isinstance(full, dict):
        for n in names or []:
            if n in report:
                full[n] = json.loads(json.dumps(report[n]))
    last_full.pop("stale", None)
