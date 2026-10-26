"""Copies of the fort's save, so a long run alone can't lose the fort.

DF keeps three autosaves and writes over the oldest; a save that goes bad
(a crash while saving, or a record the AI wrote that the game dislikes) can
take the fort with it. Once a real day while unattended, the overseer copies
the fort's newest save folder into backups/<save folder>/<date time>/ beside
DF-AI's logs, and keeps the newest KEEP copies. No tokens.

    line = backup.maybe(save_root, save_dir)     # once a cycle; None or a line to print
"""

from __future__ import annotations

import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from bridge import PROJECT_ROOT

BACKUP_DIR = PROJECT_ROOT / "backups"
STATE = BACKUP_DIR / "last.json"
EVERY_S = 24 * 3600          # a copy a real day
KEEP = 3                     # copies kept per save
QUIET_S = 120                # a folder written to in the last 2 minutes may be mid-save: wait


COPY_NAME = re.compile(r"^\d{4}-\d\d-\d\d \d{4}$")     # a finished copy's folder name
SAFE_SAVE = re.compile(r"^[\w .()'-]{1,80}$")          # letters of any language, digits


# (0.104.81) Called now and then during a long copy (the overseer sets its
# heartbeat here): a big save copied in more than 10 minutes made the keeper
# think the overseer stuck and restart it mid-copy.
on_progress = None
_last_beat = [0.0]


def _copy_beating(src, dst, *, follow_symlinks=True):
    shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
    if on_progress and time.time() - _last_beat[0] >= 30:
        _last_beat[0] = time.time()
        try:
            on_progress()
        except Exception:  # noqa: BLE001 - a heartbeat must never break the copy
            pass
    return dst


def safe_save_dir(save_dir) -> bool:
    """(0.100, security pass) The game's save folder name, used to build a
    path that's later cleared out: one plain folder name only (never "..",
    a drive, a separator or a reserved device name)."""
    if not isinstance(save_dir, str) or not SAFE_SAVE.match(save_dir):
        return False
    if save_dir.strip(" .") == "" or save_dir != save_dir.rstrip(" ."):
        return False
    return save_dir.split(".")[0].strip().upper() not in {
        "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}


def folder_mtime(p: Path) -> float:
    newest = p.stat().st_mtime
    for f in p.rglob("*"):
        try:
            newest = max(newest, f.stat().st_mtime)
        except OSError:
            pass
    return newest


def newest_folder(save_root: Path, save_dir: str) -> Path | None:
    """The loaded save's folder or one of DF's autosaves, whichever was
    written last (DF saves a season's autosave under "autosave N", not under
    the save's own name)."""
    cands = [save_root / save_dir] + sorted(save_root.glob("autosave*"))
    cands = [c for c in cands if c.is_dir()]
    if not cands:
        return None
    return max(cands, key=folder_mtime)


def _last() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def due(now: float | None = None) -> bool:
    """(0.99.13) Has a day passed since the last copy? Cheap: callers look up
    the save folder (a walk of the save trees) only when it has."""
    now = time.time() if now is None else now
    return now - float(_last().get("at") or 0) >= EVERY_S


RETRY_S = 3600                # after a failed copy


def _rename(src: Path, dest: Path) -> None:
    """Windows may hold freshly written files a moment (a virus scan, the
    search indexer): the rename is tried a few times before it fails."""
    for attempt in range(6):
        try:
            src.rename(dest)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.5 * (attempt + 1))


def _mark(now: float, copy: str, src: str) -> None:
    try:
        BACKUP_DIR.mkdir(exist_ok=True)
        STATE.write_text(json.dumps({"at": now, "copy": copy, "from": src}), encoding="utf-8")
    except OSError:
        pass


def maybe(save_root, save_dir: str | None, now: float | None = None,
          force: bool = False) -> str | None:
    """Copy the newest save folder if a day has passed since the last copy.
    `save_root` may be a callable, called only when a copy is due.
    Returns a line for the overseer's window, or None."""
    if not save_dir:
        return None
    now = time.time() if now is None else now
    if not force and not due(now):
        return None
    if not safe_save_dir(save_dir):
        _mark(now, "", "")                              # said once a day, not every cycle
        return f"no copy of the save: its folder name {str(save_dir)[:40]!r} isn't a plain folder name"
    if callable(save_root):
        save_root = save_root()
    if not save_root:
        return None
    src = newest_folder(Path(save_root), save_dir)
    if src is None:
        return None
    if now - folder_mtime(src) < QUIET_S:
        return None                                    # being written: next cycle
    dest_root = BACKUP_DIR / save_dir
    try:
        if dest_root.resolve().parent != BACKUP_DIR.resolve():
            return f"no copy of the save: {save_dir!r} would land outside the backups folder"
    except OSError as e:
        return f"couldn't check the backups folder ({e})"
    dest = dest_root / datetime.fromtimestamp(now).strftime("%Y-%m-%d %H%M")
    # copied under a ".partial" name first and renamed when whole: a copy cut
    # short (a crash, the keeper restarting) never counts as one of the KEEP
    part = dest.with_name(dest.name + ".partial")
    # partial copies left by a crash (at another minute) are cleared out
    try:
        for p in dest_root.iterdir():
            if p.is_dir() and p.name.endswith(".partial") and p != part and now - p.stat().st_mtime > QUIET_S:
                shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass
    # (0.100.1, review) marked before copying: a copy cut off (the keeper
    # restarting a slow cycle) is tried again in an hour, not at every restart
    _mark(now - EVERY_S + RETRY_S, "", "")
    try:
        if not dest.exists():
            shutil.rmtree(part, ignore_errors=True)
            before = folder_mtime(src)
            shutil.copytree(src, part, copy_function=_copy_beating)
            if folder_mtime(src) > before:
                # the game wrote to the save while it was copied: a torn copy
                shutil.rmtree(part, ignore_errors=True)
                return "the save changed while it was copied (the game was saving): trying again in an hour"
            _rename(part, dest)
    except OSError as e:
        shutil.rmtree(part, ignore_errors=True)
        _mark(now - EVERY_S + RETRY_S, "", "")          # tried: again in an hour, not every cycle
        return f"couldn't copy the save to {dest} ({e}); trying again in an hour"
    # only the finished copies this module made (dated names) are cleared out
    copies = sorted((p for p in dest_root.iterdir() if p.is_dir() and COPY_NAME.match(p.name)),
                    key=lambda p: p.name)
    for old in copies[:-KEEP]:
        shutil.rmtree(old, ignore_errors=True)
    _mark(now, str(dest), str(src))
    return f"a copy of the save ({src.name}) is in {dest}; the newest {KEEP} are kept"
