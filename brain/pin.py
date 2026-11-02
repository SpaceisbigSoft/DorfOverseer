"""(0.105.0) The keeper's pin: the world and site an unattended run started
with, so the run can't cross into another world's fort.

DF's "autosave N" folders are shared by every world, and logs/last-fort.json
follows whichever fort the overseer last ran (a manual daytime run changes
it). The keeper pins the fort it starts with (logs/keeper-pin.json); the
reviver loads only that world's saves, the daily backup copies only that
fort, and the overseer under the keeper (DFAI_PIN=1) refuses to act on any
other fort, saying so.

    p = pin.current()                  # {"world", "site", "save_dir", "df_path"} or None
    pin.take(keeper_started)           # the keeper: pin the fort once it is known
    pin.matches(world, site)           # True when nothing is pinned
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from dfhack import PROJECT_ROOT


def _log_dir() -> Path:
    return Path(os.environ.get("DFAI_LOG_DIR") or PROJECT_ROOT / "logs")


PIN_FILE = _log_dir() / "keeper-pin.json"
LAST_FORT = _log_dir() / "last-fort.json"


def _read(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def site_of(fort_key) -> str:
    """The site id from a fort key ("<save folder>#<site id>")."""
    return str(fort_key or "").rpartition("#")[2]


def current() -> dict | None:
    d = _read(PIN_FILE)
    return d if d.get("world") and d.get("site") else None


def clear() -> None:
    try:
        PIN_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def take(started: float, at_title: bool = False, log=None) -> dict | None:
    """Pin the fort from logs/last-fort.json: written since the keeper started
    (the overseer ran it this run), or, with the game at the title screen
    (nothing ran yet), the last fort played. Returns the pin, or None while
    the fort isn't known yet. A first run in a fresh world has no
    last-fort.json: nothing is pinned until the overseer has run once."""
    p = current()
    if p and p.get("started") == started:
        return p
    try:
        fresh = LAST_FORT.stat().st_mtime >= started
    except OSError:
        return None
    if not fresh and not at_title:
        return None
    d = _read(LAST_FORT)
    site = site_of(d.get("fort"))
    if not d.get("world") or not site or not d.get("save_dir"):
        return None
    p = {"world": d["world"], "site": site, "save_dir": d["save_dir"], "df_path": d.get("df_path"),
         "started": started, "pinned_at": time.time()}
    try:
        PIN_FILE.parent.mkdir(parents=True, exist_ok=True)
        from dfhack import write_atomic
        write_atomic(PIN_FILE, json.dumps(p))
    except OSError:
        return None
    if log:
        log(f"Keeper: pinned to the world '{p['world']}', site {p['site']} (save folder '{p['save_dir']}'): "
            "only this fort is loaded, copied and run until the keeper stops.")
    return p


def matches(world, site) -> bool:
    p = current()
    if not p:
        return True
    return str(world or "") == str(p["world"]) and str(site if site is not None else "") == str(p["site"])


def refusal(world, site) -> str | None:
    """The overseer under the keeper: a line saying why it won't act on this
    fort, or None when it may (DFAI_PIN unset: the player's own run)."""
    if not os.environ.get("DFAI_PIN") or matches(world, site):
        return None
    p = current() or {}
    return (f"Pinned: the keeper runs the world '{p.get('world')}', site {p.get('site')}; the game has "
            f"'{world}', site {site} loaded. Not acting on it (load the pinned fort, or stop the keeper).")
