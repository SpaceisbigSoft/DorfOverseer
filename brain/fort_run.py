"""(0.105.48, K8) One fort's run: an id that tells this run of a fort from
every other.

Six forts run at once, each started fresh from the same embark (region4):
world, site and save folder names are the same in all of them and across
restarts, and "autosave N" is reused every season. Nothing told this run's
saves, backups and memory from the last run's. The run id does:

  * made by the overseer the first time it sees a fort whose save holds
    none (a fresh embark, or a save from before 0.105.48), kept in the
    memory (Memory.fort_run) and written into the save with the ledger
    (ledger_set's fort_run), so every later save and autosave of this run
    carries it and a fresh embark never does;
  * put in the report's fort section as "fort_run" for the cycle, and in
    logs/last-fort.json (the keeper's pin takes it): the backup marks each
    copy with it (brain/backup.py), and the restore and the run check's
    housekeeping take only this run's copies as this fort's;
  * a memory read from the logs copy that belongs to another run (its
    fort_run differs from the save's; or the save holds none and the memory
    knew the fort well past the game's date: a fresh embark) is set aside:
    the old run's master plan and cooldowns never steer a fresh embark.

    memory, bank = fort_run.settle(memory, bank, state, say)   # the overseer, once a memory is read
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime

RUN_ID = re.compile(r"^[A-Za-z0-9_-]{4,40}$")
LOGS_SOURCES = ("logs", "logs (migrated)")


def new_id(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d%H%M") + "-" + secrets.token_hex(2)


def valid(run) -> bool:
    return isinstance(run, str) and RUN_ID.match(run) is not None


def held(state: dict) -> tuple[bool, str | None]:
    """(readable, run): whether the save's ledger section was read, and the
    run id it holds (None when it holds none)."""
    led = state.get("ledger") if isinstance(state, dict) else None
    if not isinstance(led, dict) or "error" in led:
        return False, None
    run = led.get("fort_run")
    return True, run if valid(run) else None


def settle(memory, bank, state: dict, say=print, make=None):
    """The memory's run made to agree with the save's. Returns (memory, bank):
    a blank pair when the memory came from the logs copy of another run.
    With the save's ledger unread nothing changes (it can't be told)."""
    readable, saved = held(state)
    if not readable:
        return memory, bank
    texts = getattr(memory, "_texts", None) or {}
    mine = getattr(memory, "fort_run", "")
    if texts.get("source") in LOGS_SOURCES and valid(mine) and mine != saved and _other_run(memory, state, saved):
        from planner_core import Memory
        fresh = Memory()                  # (the token bank is real money spent, not the fort's: kept)
        fresh._texts = dict(texts, source="new (the logs copy was another run's)", set_aside_run=mine)
        say(f"Memory: the copy in logs/ belongs to another run of this fort ({mine}; the save holds "
            f"{saved or 'no run'}): set aside, this fort's memory starts afresh.")
        memory = fresh
    if saved:
        memory.fort_run = saved
    elif not valid(getattr(memory, "fort_run", "")):
        memory.fort_run = (make or new_id)()
        say(f"Run: this fort's save holds no run id: it is run {memory.fort_run} from now on "
            "(kept in the save with the ledger; its backups are marked with it).")
    return memory, bank


BEHIND_TICKS = 28 * 1200      # a memory that knew the fort this far past the game's date


def _abs_tick(state: dict) -> int | None:
    d = state.get("date") if isinstance(state, dict) else None
    if isinstance(d, dict) and isinstance(d.get("year"), int) and isinstance(d.get("tick"), int):
        from util import YEAR_TICKS
        return d["year"] * YEAR_TICKS + d["tick"]
    return None


def _other_run(memory, state: dict, saved: str | None) -> bool:
    """The logs copy (run `memory.fort_run`) is another run's: the save holds
    another run id; or it holds none (a fresh embark, or a save from before
    0.105.48) and the memory knew this fort more than a game month past the
    game's date (a new run from the embark). A save holding none whose game
    is not behind the memory is this run's, its ledger not written yet (the
    AI not acting, a write that failed): kept."""
    if saved:
        return True
    now = _abs_tick(state)
    fired = getattr(memory, "last_fired", None)
    ticks = [v for v in (fired.values() if isinstance(fired, dict) else ())
             if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return now is not None and bool(ticks) and max(ticks) > now + BEHIND_TICKS


def of(memory) -> str | None:
    run = getattr(memory, "fort_run", "")
    return run if valid(run) else None
