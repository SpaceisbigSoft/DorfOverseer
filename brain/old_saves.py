"""(0.105.46, I6) Old test saves, told to the player once.

The run check (brain/health_check.py housekeeping) finds the test saves
("AI Run...", "AI Test...", any "test" folder) not written to for
OLD_SAVE_DAYS in the game's save folders, with their sizes (985 MB of them
on 13 Nov). The AI never deletes a game save: they are the player's. So the
list goes to the player as one Needs you line, shown for SHOW_HOURS real
hours after it is first shown, and again only when a save not told before
joins the list (a save the player deleted simply drops out of it).

    old_saves.note(found)          # the run check: [(path, age days, bytes)]; True when one is new
    old_saves.needs_you()          # the overseer, each cycle: [] or [one line]

The list lives in logs/old-saves.json (written by the run check, read by the
overseer: a small file, read again only when it changed).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = Path(os.environ.get("DFAI_LOG_DIR") or ROOT / "logs")
LIST = LOG_DIR / "old-saves.json"
SHOW_HOURS = 6        # the line stands this long once shown (the run check flags lines past 12 h)
NAMES_MAX = 6         # saves named in the line (the rest counted)

_CACHE: dict = {"mtime": None, "data": None, "path": None}


def _load(path: Path) -> dict:
    try:
        mt = path.stat().st_mtime
    except OSError:
        return {}
    if _CACHE["path"] == str(path) and _CACHE["mtime"] == mt and isinstance(_CACHE["data"], dict):
        return _CACHE["data"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    _CACHE.update(mtime=mt, data=data, path=str(path))
    return data


def _write(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        _CACHE.update(mtime=None, data=None, path=None)
    except OSError:
        pass


def note(found: list, now: float | None = None, path: Path | None = None) -> bool:
    """The run check's list: [(path, age in days, bytes)]. Kept for the
    overseer; what was told before is kept too. True when a save on the list
    has not been told to the player yet."""
    path = path or LIST
    now = time.time() if now is None else now
    old = _load(path)
    told = [str(x) for x in old.get("told") or [] if isinstance(x, str)]
    saves = [{"path": str(p), "name": Path(str(p)).name, "days": round(float(age)), "mb": round(int(size) / 1e6)}
             for p, age, size in found]
    _write(path, {"at": now, "saves": saves, "told": told, "told_at": old.get("told_at")})
    return any(s["path"] not in told for s in saves)


def line_for(saves: list) -> str:
    total = sum(int(s.get("mb") or 0) for s in saves)
    named = ", ".join(f"{s.get('name')} ({s.get('mb')} MB)" for s in saves[:NAMES_MAX])
    more = f" and {len(saves) - NAMES_MAX} more" if len(saves) > NAMES_MAX else ""
    folder = str(Path(saves[0]["path"]).parent) if saves else ""
    return (f"old test saves you could delete ({len(saves)}, {total} MB, in {folder}): {named}{more}. "
            "The AI never deletes a save: delete them yourself if you don't need them")


def needs_you(now: float | None = None, path: Path | None = None, exists=None) -> list[str]:
    """[] or the one Needs you line: the listed saves still there, while
    SHOW_HOURS have not passed since they were first told; told again only
    when one not told before is on the list. Never raises."""
    try:
        path = path or LIST
        now = time.time() if now is None else now
        exists = exists or (lambda p: Path(p).is_dir())
        data = _load(path)
        saves = [s for s in data.get("saves") or [] if isinstance(s, dict) and s.get("path")]
        if not saves:
            return []
        saves = [s for s in saves if exists(s["path"])]
        if not saves:
            return []
        told = set(str(x) for x in data.get("told") or [])
        if any(s["path"] not in told for s in saves):
            data = dict(data, told=sorted(told | {s["path"] for s in saves}), told_at=now)
            _write(path, data)
        at = data.get("told_at")
        if isinstance(at, (int, float)) and now - at < SHOW_HOURS * 3600:
            return [line_for(saves)]
        return []
    except Exception:  # noqa: BLE001  (a Needs you line never stops the fort)
        return []
