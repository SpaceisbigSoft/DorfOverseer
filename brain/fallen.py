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

    why = fallen.falls(state)                      # before normalize(): the raw report
    fallen.note(state, key, folder, say)           # each cycle: True while fallen
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


def idle() -> dict | None:
    """For the overseer's loop and the keeper: the mark when the game is to
    be left alone (no unpausing, no unsticking, no relaunch or reload)."""
    return current()


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
        say(f"Fallen: the fort's fall is over ({why}): the AI acts again, and the keeper looks after the game again.")
        if journal:
            journal({"kind": "fallen", "fort": key, "event": "ended", "why": why, "date": state.get("date")})
        _clear(mark, why)
        STATE["mark"] = None
        STATE["dismissed"] = None
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
