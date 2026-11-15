"""(0.105.25, 13c) Small helpers the brain's modules shared as copies.

    load_json(path, default)   a JSON file, or the default when it is missing,
                               unreadable or of another type
    YEAR_TICKS, date_tick(d)   the game's clock: a date's absolute tick
    folder_lock(dir)           the folder's single-run lock (keeper.py, and a
                               manual overseer.py --autopilot)
    same_path(a, b)            two paths name the same folder (Windows' case
                               and slashes ignored)
    own_df_folder()            this DF-AI folder's own game folder (config's
                               df_launch .exe's folder), or None

`_d` / `_l` (a dict or list, else an empty one) live in digest.py; config.json
is read by dfhack.read_config.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DAY_TICKS = 1200
YEAR_TICKS = 403200        # 12 months x 28 days x 1200 ticks


def date_tick(date) -> int:
    """A report date's absolute tick (year * YEAR_TICKS + tick); 0 for what
    is missing."""
    d = date if isinstance(date, dict) else {}
    return int(d.get("year") or 0) * YEAR_TICKS + int(d.get("tick") or 0)


def load_json(path, default=None):
    """The JSON in `path`; `default` when the file is missing or unreadable,
    or (a dict or list default) when it holds another type."""
    try:
        v = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    if isinstance(default, (dict, list)) and not isinstance(v, type(default)):
        return default
    return v


LOCK_NAME = "keeper.lock"


def folder_lock(folder: Path):
    """An open, locked file (`folder`/keeper.lock) while this process runs,
    or None when another process holds it. Close the file to let go. One
    autopilot per DF-AI folder: two would fight over the fort, its memory,
    the journal and the token count."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    f = open(folder / LOCK_NAME, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def _norm_path(p) -> str:
    s = str(p or "").strip().strip('"').replace("\\", "/")
    while len(s) > 1 and s.endswith("/") and not s.endswith(":/"):
        s = s[:-1]
    return os.path.normpath(s).replace("\\", "/").lower() if s else ""


def same_path(a, b) -> bool:
    """(0.105.48, K17) `a` and `b` name the same folder: DF's getDFPath and
    config.json may differ in case, slashes and a trailing slash. False when
    either is empty."""
    na, nb = _norm_path(a), _norm_path(b)
    return bool(na) and na == nb


def own_df_folder() -> str | None:
    """(0.105.48, K17) This DF-AI folder's own Dwarf Fortress folder: the
    folder of config.json's "df_launch" when it names the game's .exe; None
    for a steam:// link or no df_launch (then the game can't be told from
    the other five on the PC, and nothing is checked)."""
    try:
        from dfhack import read_config
        cmd = read_config().get("df_launch")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(cmd, str) or not cmd.strip().lower().endswith(".exe"):
        return None
    s = cmd.strip().strip('"').replace("\\", "/")
    parent = s.rpartition("/")[0]
    return parent or None


def state_tick(state: dict) -> int:
    """A report's absolute tick, strictly (planner_core.abs_tick's twin, for
    the modules below the planner): a report without its date raises."""
    d = state["date"]
    return d["year"] * YEAR_TICKS + d["tick"]
