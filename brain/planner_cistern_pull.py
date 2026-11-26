"""(r33b) planner_cistern_pull: the built cistern's top-up pull (shut when
full, open when low) paced, and taken off the dwarves when it gets stuck.
Kept out of planner_wells, whose names are pinned (tests/test_r7_d4.py).

B, 26 Nov (0.105.128-129): "cistern: the cistern is 7/7 deep: shut the
floodgate" every cycle (~15-25 s real) for hours. The lever's PullLever job
was taken by the militia captain and dropped (a soldier on duty or training
leaves it), so the job came and went: the status said pull_pending only in
the few seconds it stood, and the 1-game-day wait after a pull was ~1 cycle
at that speed (a game day ~25 s).

Now: a pull asked for is asked again only after CISTERN_PULL_PACE_DAYS game
days AND CISTERN_PULL_REAL_MINUTES real minutes (at the bridge's fps) AND
CISTERN_PULL_CYCLES brain cycles, whatever the pending flag does between.
After CISTERN_PULL_TRIES asks with the floodgate as it was, it is stuck: said
once, and the next pull is instant (lever pull --instant, the dwarves' queued
pulls taken away first so none walks up and toggles it back): no soldier can
drop it. Shutting a full cistern is always safe; an open is only asked once
the bridge found it closed all round (the done step checks before any pull).
"""

from __future__ import annotations

from digest import _d
from planner_core import TICKS_PER_DAY, abs_tick

__all__ = ["CISTERN_PULL_TRIES", "CISTERN_PULL_PACE_DAYS", "CISTERN_PULL_REAL_MINUTES", "CISTERN_PULL_CYCLES",
           "CISTERN_PULL_BOOK", "cistern_pull_plan"]

CISTERN_PULL_TRIES = 3            # dwarf pulls asked with the floodgate unchanged: then stuck (instant)
CISTERN_PULL_PACE_DAYS = 3        # game days between two asks...
CISTERN_PULL_REAL_MINUTES = 3     # ...and real minutes (at the fps the bridge measured)...
CISTERN_PULL_CYCLES = 4           # ...and brain cycles (distinct ticks the rule looked)
CISTERN_PULL_BOOK = "cistern_pull"    # Memory.repeat_book[...]: {want, n, at, seen, last, said}


def _pace_ticks(s: dict) -> int:
    from planner_backoff import real_ticks
    return max(CISTERN_PULL_PACE_DAYS * TICKS_PER_DAY, real_ticks(s, CISTERN_PULL_REAL_MINUTES))


def cistern_pull_plan(s: dict, st: dict, memory, notes: list) -> str:
    """The top-up pull this cycle: "wait" (a note says why), "ask" (a dwarf
    pull, the plain step) or "instant" (stuck: the lever pulled at once).
    Called only when the cistern is done and wants a pull (full and open, or
    low and shut). The record is reset once the floodgate is as wanted (the
    want changes) or the pull isn't wanted (the caller stops calling: the
    next want starts afresh)."""
    want = "shut" if st.get("gate") == "open" else "opened"
    depth = st.get("depth")
    if memory is None:
        # no memory to pace by: the old way (the pending flag only)
        if st.get("pull_pending"):
            notes.append(f"the cistern is {depth}/7 deep: a dwarf is on the way to its lever to have the "
                         f"floodgate {want}")
            return "wait"
        return "ask"
    from planner_backoff import repeat_book
    book = repeat_book(memory, CISTERN_PULL_BOOK)
    now = abs_tick(s)
    if book.get("want") != want or not isinstance(book.get("at"), int) or not 0 <= now - book["at"]:
        # the floodgate moved (or a first ask, or an older save): afresh
        book.clear()
    n = int(book.get("n") or 0)
    if n and book.get("last") != now:          # one more cycle seen since the ask (not twice a tick)
        book["seen"] = int(book.get("seen") or 0) + 1
        book["last"] = now
    stuck = n >= CISTERN_PULL_TRIES
    if stuck and not book.get("said"):
        book["said"] = True
        notes.append(f"the cistern is {depth}/7 deep and its floodgate still {st.get('gate')} after its lever was "
                     f"asked for {n} times (a dwarf takes the pull and drops it, e.g. a soldier called to duty): "
                     "the AI pulls it at once from now on, no dwarf needed")
    if n:
        waited = now - book["at"] >= _pace_ticks(s) and int(book.get("seen") or 0) >= CISTERN_PULL_CYCLES
        if not waited:
            if st.get("pull_pending") and not stuck:
                notes.append(f"the cistern is {depth}/7 deep: a dwarf is on the way to its lever to have the "
                             f"floodgate {want}")
            else:
                notes.append(f"the cistern is {depth}/7 deep and its floodgate still {st.get('gate')} after its "
                             f"lever was pulled: asked again in {CISTERN_PULL_PACE_DAYS} days")
            return "wait"
    elif st.get("pull_pending"):
        # a pull the AI didn't ask for in this record (asked before a restart):
        # waited on, not counted
        notes.append(f"the cistern is {depth}/7 deep: a dwarf is on the way to its lever to have the "
                     f"floodgate {want}")
        return "wait"
    book.update({"want": want, "n": n + 1, "at": now, "seen": 0, "last": now})
    return "instant" if n + 1 > CISTERN_PULL_TRIES else "ask"
