"""Copies of the fort's save, so a long run alone can't lose the fort.

DF keeps three autosaves and writes over the oldest; a save that goes bad
(a crash while saving, or a record the AI wrote that the game dislikes) can
take the fort with it. Once a real day while unattended, the overseer copies
the fort's newest save folder into backups/<save folder>/<date time>/ beside
DF-AI's logs. (0.105.46, I6) Kept by age, per fort (whichever save folder
each copy came from): the newest of each day for a week, the newest of each
week for five weeks, the newest always; and the fort's copies together under
MAX_MB (the oldest go first). Only the copies this module made are ever
removed: the game's own saves are never touched. No tokens.

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
from util import load_json

BACKUP_DIR = PROJECT_ROOT / "backups"
STATE = BACKUP_DIR / "last.json"
EVERY_S = 24 * 3600          # a copy a real day
KEEP = 3                     # (before 0.105.46) copies kept per save; now by age (KEEP_DAILY_DAYS...)
KEEP_DAILY_DAYS = 7          # (0.105.46, I6) the newest copy of each day this many days back
KEEP_WEEKLY_WEEKS = 5        # ... and of each week this many weeks back
MAX_MB = 500                 # ... and a fort's copies together under this (the oldest go first; never the newest)
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


def save_mtime(p: Path) -> float:
    """(0.105.42) When a save was written: its world.sav's time (DF writes it
    once a save; the folder's other files, DFHack's own among them, change at
    other times and once put an older autosave first). The newest file in the
    folder when it has no world.sav."""
    try:
        return (p / "world.sav").stat().st_mtime
    except OSError:
        return folder_mtime(p)


def newest_folder(save_root: Path, save_dir: str) -> Path | None:
    """The loaded save's folder or one of DF's autosaves, whichever was
    written last (DF saves a season's autosave under "autosave N", not under
    the save's own name)."""
    cands = [save_root / save_dir] + sorted(save_root.glob("autosave*"))
    cands = [c for c in cands if c.is_dir()]
    if not cands:
        return None
    return max(cands, key=save_mtime)


def fort_mark_path(copy: Path) -> Path:
    """(0.105.33) Beside each copy (never inside: the copy is restored whole
    into DF's saves): "<date time>.fort.json", the world and site it holds."""
    return copy.with_name(copy.name + ".fort.json")


def _write_fort_mark(copy: Path, fort: dict, save_dir: str) -> None:
    try:
        fort_mark_path(copy).write_text(json.dumps({
            "world": fort.get("world"), "site": str(fort.get("site_id") if fort.get("site_id") is not None else ""),
            "save_dir": save_dir}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def copy_fort(copy: Path) -> dict | None:
    """(0.105.33) The world and site a copy holds, or None (a copy made before
    they were marked, or without the report's fort section)."""
    d = load_json(fort_mark_path(copy), None)
    return d if isinstance(d, dict) and d.get("world") else None


SHARED_PREFIXES = ("autosave", "ai restore")     # save folders any world may write


def copies_of(world, site, save_dir: str | None) -> list[Path]:
    """(0.105.33) Every finished copy in backups/ of the fort (world, site),
    newest first, whichever save folder it was copied from (a revive loading
    "autosave 2", or a restore, changes the folder the copies go to). A copy
    with no mark counts only under backups/<save_dir>, and never when that is
    one of DF's shared autosave folders (another world's may be there)."""
    out = []
    try:
        dirs = [d for d in BACKUP_DIR.iterdir() if d.is_dir()]
    except OSError:
        return []
    legacy_ok = bool(save_dir) and not str(save_dir).lower().startswith(SHARED_PREFIXES)
    for d in dirs:
        try:
            copies = [c for c in d.iterdir() if c.is_dir() and COPY_NAME.match(c.name)]
        except OSError:
            continue
        for c in copies:
            m = copy_fort(c)
            if m is not None:
                if str(m.get("world")) == str(world) and str(m.get("site")) == str(site):
                    out.append(c)
            elif legacy_ok and d.name == save_dir:
                out.append(c)
    return sorted(out, key=lambda c: c.name, reverse=True)


def _last() -> dict:
    return load_json(STATE, {})


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


# (0.105.0) DF autosaves in a season's last days: no copy then (a copy
# begun as DF starts its autosave was torn or missed the newest save)
SEASON_TICKS = 84 * 1200
SEASON_END_TICKS = 3 * 1200
# fort (world#site) -> when this process first saw it loaded: an "autosave N"
# folder written since then is this fort's (the folders are shared by every
# world; one written before may be another world's)
SESSION: dict = {}


def season_end(date) -> bool:
    tick = date.get("tick") if isinstance(date, dict) else None
    return isinstance(tick, int) and tick % SEASON_TICKS >= SEASON_TICKS - SEASON_END_TICKS


def _ours(save_root: Path, save_dir: str, since: float | None) -> Path | None:
    """(0.105.0) The newest folder that is surely the loaded fort's: its own
    folder, or an autosave written since the fort was seen loaded."""
    cands = [save_root / save_dir]
    if since is not None:
        cands += [c for c in sorted(save_root.glob("autosave*"))
                  if c.is_dir() and c.name != save_dir and folder_mtime(c) >= since]
    cands = [c for c in cands if c.is_dir()]
    return max(cands, key=save_mtime) if cands else None


def maybe(save_root, save_dir: str | None, now: float | None = None,
          force: bool = False, fort: dict | None = None, date: dict | None = None) -> str | None:
    """Copy the newest save folder if a day has passed since the last copy.
    `save_root` may be a callable, called only when a copy is due.
    Returns a line for the overseer's window, or None.

    (0.105.0) With `fort` (the report's fort section): only the keeper's
    pinned world and site, and of DF's shared autosaves only those written
    while this fort was loaded. With `date`: never in a season's last 3 days."""
    if not save_dir:
        return None
    now = time.time() if now is None else now
    since = None
    if fort is not None:
        fk = f"{fort.get('world')}#{fort.get('site_id')}"
        since = SESSION.setdefault(fk, now)
        try:
            import pin
            if not pin.matches(fort.get("world"), fort.get("site_id")):
                return None                            # another world's fort: never copied for the pinned one
        except ImportError:
            pass
    if not force and not due(now):
        return None
    if season_end(date):
        return None                                    # DF is about to autosave: after it
    if not safe_save_dir(save_dir):
        _mark(now, "", "")                              # said once a day, not every cycle
        return f"no copy of the save: its folder name {str(save_dir)[:40]!r} isn't a plain folder name"
    if callable(save_root):
        save_root = save_root()
    if not save_root:
        return None
    src = newest_folder(Path(save_root), save_dir) if fort is None else _ours(Path(save_root), save_dir, since)
    if src is None:
        return None
    if now - folder_mtime(src) < QUIET_S:
        return None                                    # being written: next cycle
    if fort is not None:
        # (0.105.0) DF writing any save folder (its autosave goes to the oldest
        # "autosave N", not the newest): it is saving, wait
        for c in [Path(save_root) / save_dir] + sorted(Path(save_root).glob("autosave*")):
            try:
                if c.is_dir() and now - folder_mtime(c) < QUIET_S:
                    return None
            except OSError:
                pass
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
    if fort is not None:
        _write_fort_mark(dest, fort, save_dir)
    # only the finished copies this module made (dated names) are cleared out;
    # (0.105.33) per fort: DF's "autosave N" folders are shared by every
    # world, so another world's copies never push this fort's out
    # (0.105.46, I6) by age, over every folder the fort's copies are in
    kept = prune(dest_root, fort, save_dir, now)
    _mark(now, str(dest), str(src))
    return (f"a copy of the save ({src.name}) is in {dest}; {kept} kept (a day's for a week, "
            f"a week's for {KEEP_WEEKLY_WEEKS} weeks, under {MAX_MB} MB)")


# ---------------------------------------------------------------------------
# (0.105.46, I6) retention by age
# ---------------------------------------------------------------------------

def copy_time(c: Path) -> float | None:
    """When a copy was made, from its folder name ("2026-11-14 0310"), or None."""
    try:
        return datetime.strptime(c.name, "%Y-%m-%d %H%M").timestamp()
    except (ValueError, OSError):
        return None


def tree_size(p: Path) -> int:
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def choose_keep(copies: list, now: float, sizes: dict | None = None,
                max_bytes: int | None = None) -> list:
    """Which of one fort's copies stay (pure: nothing is removed here): the
    newest always; the newest of each calendar day for KEEP_DAILY_DAYS days;
    the newest of each week (7-day spans back from now) for
    KEEP_WEEKLY_WEEKS weeks; then, with `sizes` and `max_bytes`, the oldest
    kept go until the rest fit (the newest stays whatever its size). A copy
    whose name has no date is kept (not ours to judge). Newest first."""
    dated = [(copy_time(c), c) for c in copies]
    keep = [c for t, c in dated if t is None]
    dated = sorted(((t, c) for t, c in dated if t is not None), key=lambda tc: (tc[0], tc[1].name), reverse=True)
    if not dated:
        return keep
    chosen = [dated[0][1]]
    days, weeks = set(), set()
    for t, c in dated:
        age = max(0.0, now - t)
        day = datetime.fromtimestamp(t).strftime("%Y-%m-%d")
        week = int(age // (7 * 86400))
        if age < KEEP_DAILY_DAYS * 86400 and day not in days:
            days.add(day)
            weeks.add(week)
            if c not in chosen:
                chosen.append(c)
        elif age < KEEP_WEEKLY_WEEKS * 7 * 86400 and week not in weeks:
            weeks.add(week)
            if c not in chosen:
                chosen.append(c)
    if sizes is not None and max_bytes is not None:
        order = sorted(chosen, key=lambda c: copy_time(c) or 0.0, reverse=True)
        total = sum(sizes.get(c, 0) for c in order)
        while total > max_bytes and len(order) > 1:
            gone = order.pop()                      # the oldest kept
            total -= sizes.get(gone, 0)
        chosen = order
    return keep + sorted(chosen, key=lambda c: copy_time(c) or 0.0, reverse=True)


def _ours_to_remove(c: Path) -> bool:
    """A finished copy this module made: a dated folder two levels inside
    backups/ (backups/<save folder>/<date time>), never anything else."""
    try:
        return (c.is_dir() and COPY_NAME.match(c.name) is not None
                and c.resolve().parent.parent == BACKUP_DIR.resolve())
    except OSError:
        return False


def _remove_copy(c: Path) -> bool:
    if not _ours_to_remove(c):
        return False
    shutil.rmtree(c, ignore_errors=True)
    try:
        fort_mark_path(c).unlink(missing_ok=True)
    except OSError:
        pass
    return True


def prune(dest_root: Path, fort: dict | None, save_dir: str | None, now: float) -> int:
    """(0.105.46, I6) The fort's copies thinned by age (choose_keep): with
    `fort`, every copy of that world and site in any folder; without, each
    fort's copies in dest_root as marked (as before). Other forts' copies in
    the folder are left alone (the run check thins forts no longer played).
    Returns how many of the fort's copies are kept."""
    groups: list = []
    if fort is not None:
        groups.append(copies_of(fort.get("world"), fort.get("site_id"), save_dir))
    else:
        try:
            copies = [p for p in dest_root.iterdir() if p.is_dir() and COPY_NAME.match(p.name)]
        except OSError:
            copies = []
        by: dict = {}
        for c in copies:
            m = copy_fort(c)
            by.setdefault((m.get("world"), m.get("site")) if m else None, []).append(c)
        groups = list(by.values())
    kept = 0
    for group in groups:
        sizes = {c: tree_size(c) for c in group}
        stay = set(choose_keep(group, now, sizes, MAX_MB * 1_000_000))
        for c in group:
            if c not in stay:
                _remove_copy(c)
        kept = max(kept, len(stay))
    return kept
