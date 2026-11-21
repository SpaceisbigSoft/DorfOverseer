"""(r1g9) A fallen fort: no citizens left and no migrant wave on its way.

F fell at 01:47 (16 Nov): the keeper then logged "time stood still" 65
times for 9 hours over a dead fort. B sat at 0 citizens for 2.5 game years
while the AI ran thousands of useless actions (survey slices, labour refused
"nobody", projects refused "no citizens"). Now the fall is seen once:

  * said plainly in the log, once;
  * a mark (fallen.json) and the evidence (the last report as it came,
    fallen-<time>-state.json) written into the fort's logs folder, and the
    mark copied to logs/fallen.json for the keeper;
  * the overseer proposes nothing while it stands (the plan is not run), and
    neither the overseer nor the keeper touches the game: no unpausing, no
    popups taken off, no relaunch or reload of a closed game (revive.py);
  * it ends when the player acts: citizens are back (migrants, another save
    loaded), another fort or an earlier date of it is loaded, or the player
    deletes logs/fallen.json (the AI acts again on that fort until it has
    citizens and falls again).

  * (x3, V7) the mark is for the fort and date it names: the overseer's loop
    checks it against the game loaded now (fallen.idle(status, probe)), as DF
    loads every save paused and no cycle runs while paused; the keeper holds
    only for a mark of its pinned fort (holds_for).

    why = fallen.falls(state)                      # before normalize(): the raw report
    fallen.note(state, key, folder, say)           # each cycle: True while fallen
    fallen.idle(status, probe, say, journal)       # each poll of the loop: the mark, or None
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from util import load_json

LOG_DIR = Path(os.environ.get("DFAI_LOG_DIR") or Path(__file__).resolve().parent.parent / "logs")   # (tests: DFAI_LOG_DIR)
MARK_NAME = "fallen.json"
STATE: dict = {"mark": None, "dismissed": None}   # the mark in force; a fall the player dismissed


def mark_path() -> Path:
    return LOG_DIR / MARK_NAME


def _site(key) -> str:
    return str(key or "").rpartition("#")[2]


def _tick(state: dict) -> int | None:
    d = state.get("date") if isinstance(state, dict) else None
    if isinstance(d, dict) and isinstance(d.get("year"), int) and isinstance(d.get("tick"), int):
        from util import YEAR_TICKS
        return d["year"] * YEAR_TICKS + d["tick"]
    return None


def citizens(state: dict) -> int | None:
    """The report's citizen count, or None when it can't be read (a section
    that failed is never read as 0: normalize would have made it 0)."""
    dw = state.get("dwarves") if isinstance(state, dict) else None
    if not isinstance(dw, dict) or "error" in dw:
        return None
    n = dw.get("total")
    return n if isinstance(n, int) and not isinstance(n, bool) else None


def migrants_on_way(state: dict) -> int:
    """DF's migrant waves already queued (the migration section's `queued`),
    0 when none or unknown."""
    m = state.get("migration") if isinstance(state, dict) else None
    q = m.get("queued") if isinstance(m, dict) and "error" not in m else None
    return q if isinstance(q, int) and not isinstance(q, bool) and q > 0 else 0


def falls(state: dict) -> str | None:
    """Why the fort in this (raw) report has fallen, or None."""
    if _tick(state) is None:
        return None
    n = citizens(state)
    if n != 0:
        return None
    if migrants_on_way(state):
        return None
    return "no citizens left and no migrant wave on its way"


def current() -> dict | None:
    """The mark in force (logs/fallen.json), or None. Never raises."""
    try:
        d = load_json(mark_path(), None)
    except Exception:  # noqa: BLE001
        return None
    return d if isinstance(d, dict) and d.get("fort") else None


def _cfg(name: str, default: float) -> float:
    try:
        from planner_config import PLANNER_CONFIG
        v = PLANNER_CONFIG.get(name, default)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default
    except Exception:  # noqa: BLE001
        return default


def _date_key(st: dict):
    d = st.get("date") if isinstance(st, dict) else None
    return (d.get("year"), d.get("tick")) if isinstance(d, dict) else None


def idle(st: dict | None = None, probe=None, say=print, journal=None) -> dict | None:
    """For the overseer's loop and the keeper: the mark when the game is to
    be left alone (no unpausing, no unsticking, no relaunch or reload).

    (x3, V7) With the loop's status `st`, the mark holds only for the fort and
    date it names. DF loads every save paused, and while the mark stands the
    loop neither unpauses nor runs a cycle (where note() would end it): so it
    is checked here, against the game loaded now. It lapses at once (said,
    taken off, the loop runs as usual) when the status's date is earlier than
    the fall's, or when `probe()` (the loaded fort's raw pulse report and its
    key, or None when it can't be read; asked at once on a new date while
    paused, else every x3_fallen_probe_s) shows another fort, citizens again, an earlier
    date or a migrant wave on its way. Without `st` (the keeper), the mark as
    it stands. Never raises: a check that fails (not a report that can't be
    read) lets the game run rather than hold a living fort paused."""
    mark = current()
    if mark is None or st is None:
        return mark
    try:
        if not isinstance(st, dict) or not st.get("in_fort"):
            STATE.pop("probe", None)          # nothing loaded: whatever comes next is read at once
            return mark
        why, key, seen = None, mark.get("fort"), st
        t, at = _tick(st), mark.get("tick")
        if isinstance(t, int) and isinstance(at, int) and t < at:
            why = "an earlier date is loaded (an earlier save, or another fort)"
        elif probe is not None:
            import time
            last, now, dk = STATE.get("probe") or {}, time.monotonic(), _date_key(st)
            # a new date read at once only while paused (a load): a running game's
            # date moves each poll, and its cycles end the fall (note) anyway
            if (last.get("mark") != mark.get("since") or (st.get("paused") and last.get("date") != dk)
                    or now - float(last.get("at") or 0.0) >= _cfg("x3_fallen_probe_s", 30.0)):
                STATE["probe"] = {"at": now, "date": dk, "mark": mark.get("since")}
                got = probe()
                if isinstance(got, tuple) and len(got) == 2 and isinstance(got[0], dict) and got[1]:
                    seen, key = got[0], got[1]
                    why = _ended(seen, key, mark)
        if why is None:
            return mark
        _end(mark, why, key, seen.get("date"), say, journal)
        return None
    except Exception as e:  # noqa: BLE001  (never a living fort held paused by a fault here)
        try:
            say(f"Fallen: the mark couldn't be checked against the loaded fort ({type(e).__name__}: "
                f"{str(e)[:120]}): the game is looked after as usual.")
        except Exception:  # noqa: BLE001
            pass
        return None


def holds_for(mark: dict | None, pin: dict | None) -> bool:
    """(x3, V7) The keeper: does this mark hold its game? Not when the keeper
    is pinned to another fort (another world or site than the fall's): a mark
    left by another run must not keep the pinned fort from being started or
    loaded. Without a pin (or without the mark's world and site), it holds."""
    if not mark:
        return False
    if not isinstance(pin, dict) or not pin.get("world") or pin.get("site") is None:
        return True
    key = str(mark.get("fort") or "")
    world = mark.get("world") or key.rpartition("#")[0].partition("@")[0]
    site = mark.get("site") if mark.get("site") is not None else _site(key)
    if not world or site in (None, ""):
        return True
    return str(world) == str(pin["world"]) and str(site) == str(pin["site"])


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from dfhack import write_atomic
        write_atomic(path, json.dumps(data, ensure_ascii=False, indent=1))
    except ImportError:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _date_words(state: dict) -> str:
    d = state.get("date") if isinstance(state, dict) else None
    if isinstance(d, dict):
        return " ".join(str(d.get(k)) for k in ("day", "month", "year") if d.get(k) is not None) or "?"
    return "?"


def _ended(state: dict, key: str, mark: dict) -> str | None:
    """Why the fall in `mark` no longer holds for this report, or None."""
    if str(mark.get("fort")) != str(key):
        return f"another fort is loaded ({key})"
    n = citizens(state)
    if isinstance(n, int) and n > 0:
        return f"{n} citizen(s) in the fort again"
    t, at = _tick(state), mark.get("tick")
    if isinstance(t, int) and isinstance(at, int) and t < at:
        return "an earlier save of the fort is loaded"
    if migrants_on_way(state):
        return "a migrant wave is on its way"
    return None


def note(state: dict, key: str, folder: Path | None, say=print, journal=None) -> bool:
    """Each cycle, with the raw report (before normalize): True while the fort
    stands fallen (the caller proposes nothing). The fall is said, marked and
    its evidence written once. Never raises (False: the cycle goes on as before)."""
    try:
        return _note(state, key, folder, say, journal)
    except Exception as e:  # noqa: BLE001  (a fall's bookkeeping never stops the cycle)
        try:
            say(f"Fallen: couldn't be checked ({type(e).__name__}: {str(e)[:120]})")
        except Exception:  # noqa: BLE001
            pass
        return False


def _note(state: dict, key: str, folder: Path | None, say, journal) -> bool:
    mark = current()
    if mark is None and STATE.get("mark") is not None:
        # the player took logs/fallen.json away: the AI acts again on this fall
        old = STATE["mark"]
        STATE["mark"] = None
        STATE["dismissed"] = {"fort": old.get("fort"), "tick": old.get("tick")}
        say("Fallen: logs/fallen.json was removed: the AI acts on this fort again.")
        _clear_fort_mark(old, "dismissed")
    if mark is not None:
        why = _ended(state, key, mark)
        if why is None:
            STATE["mark"] = mark
            return True
        _end(mark, why, key, state.get("date"), say, journal)
        return False
    why = falls(state)
    if why is None:
        if citizens(state):
            STATE["dismissed"] = None        # a fort with citizens: the next fall is said again
        return False
    dis = STATE.get("dismissed")
    if isinstance(dis, dict) and dis.get("fort") == key:
        return False                         # the player dismissed this fall: acting as asked
    now = datetime.now()
    f = state.get("fort") if isinstance(state.get("fort"), dict) else {}
    mark = {"fort": key, "world": f.get("world"), "site": f.get("site_id"), "save_dir": f.get("save_dir"),
            "run": f.get("fort_run"), "name": f.get("name"), "date": state.get("date"), "tick": _tick(state),
            "since": now.isoformat(timespec="seconds"), "why": why,
            "folder": str(folder) if folder is not None else None}
    evidence = None
    if folder is not None:
        evidence = Path(folder) / f"fallen-{now:%Y%m%d-%H%M%S}-state.json"
        try:
            _write(evidence, {k: v for k, v in state.items() if k != "_errors"})
            mark["evidence"] = str(evidence)
        except (OSError, TypeError, ValueError) as e:
            evidence = None
            say(f"Fallen: the last report couldn't be kept ({type(e).__name__}: {str(e)[:100]})")
        try:
            _write(Path(folder) / MARK_NAME, mark)
        except OSError:
            pass
    _write(mark_path(), mark)
    STATE["mark"] = mark
    say(f"THE FORT HAS FALLEN ({_date_words(state)}): {why}. The AI stops acting on it, and the game is left "
        "alone (not unpaused, no popups taken off, not started again or reloaded if it closes) until you act: "
        "load a save, or delete logs/fallen.json to let the AI carry on."
        + (f" The last report is kept in {evidence}." if evidence else ""))
    if journal:
        journal({"kind": "fallen", "fort": key, "event": "fallen", "why": why, "date": state.get("date"),
                 "evidence": str(evidence) if evidence else None})
    return True


def _end(mark: dict, why: str, key, date, say, journal) -> None:
    """The fall in `mark` is over: said, journalled, the mark taken off."""
    say(f"Fallen: the fort's fall is over ({why}): the AI acts again, and the keeper looks after the game again.")
    if journal:
        journal({"kind": "fallen", "fort": key, "event": "ended", "why": why, "date": date})
    _clear(mark, why)
    STATE["mark"] = None
    STATE["dismissed"] = None


def _clear_fort_mark(mark: dict, why: str) -> None:
    folder = mark.get("folder")
    if not folder:
        return
    p = Path(folder) / MARK_NAME
    try:
        if p.exists():
            # kept beside the evidence, renamed: the fall is history now
            done = dict(load_json(p, {}) or {}, ended=datetime.now().isoformat(timespec="seconds"), ended_why=why)
            _write(p.with_name(f"fallen-{datetime.now():%Y%m%d-%H%M%S}-ended.json"), done)
            p.unlink()
    except OSError:
        pass


def _clear(mark: dict, why: str) -> None:
    _clear_fort_mark(mark, why)
    try:
        mark_path().unlink(missing_ok=True)
    except OSError:
        pass
