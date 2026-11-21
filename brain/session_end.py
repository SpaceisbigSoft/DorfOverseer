"""(r1g9) Windows ending the session: nothing is started or loaded again.

16 Nov 10:40-10:44 (R-AD section 6): Windows shut down (or logged off).
Every game unloaded and closed within 16 seconds, then the keepers' consoles
were ended (dfhack-run exit 0xC000013A). In between, the keepers took it for a
crash: C's reloaded `autosave 1` at the title (its last state a month older
than its last cycle), F's and A's started their games again. Now:

  * `GetSystemMetrics(SM_SHUTTINGDOWN)` (Windows: the session is ending) and
    a console close, logoff or shutdown signal the keeper received (its
    handler, `install`) each hold the reviver: no launch, no load, no close;
  * this folder's game closed while no Dwarf Fortress at all is left on the
    PC (all of them closed together, as at a shutdown) holds a relaunch for
    `g9_all_closed_hold_s` from when it went: the console's signal comes
    within that time when the session is ending (in the run, 4 minutes on).

    why = session_end.ending()        # None, or why nothing is to be started
    session_end.install(on_signal)    # the keeper, once (Windows)
"""

from __future__ import annotations

import os
import time

SM_SHUTTINGDOWN = 0x2000
CTRL_NAMES = {2: "the console window closing", 5: "Windows logging off", 6: "Windows shutting down"}
SIGNAL: dict = {"at": None, "kind": None}
_HANDLER: list = []          # the ctypes callback, kept alive while the keeper runs


def _cfg(name: str, default: float) -> float:
    try:
        from planner_config import PLANNER_CONFIG
        v = PLANNER_CONFIG.get(name, default)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default
    except Exception:  # noqa: BLE001
        return default


def windows_ending(metrics=None) -> bool:
    """True when Windows says the session is shutting down (logoff, restart
    or shutdown). False elsewhere or when it can't tell. `metrics`: tests."""
    if metrics is None:
        if os.name != "nt":
            return False
        try:
            import ctypes
            metrics = ctypes.windll.user32.GetSystemMetrics
        except Exception:  # noqa: BLE001
            return False
    try:
        return bool(metrics(SM_SHUTTINGDOWN))
    except Exception:  # noqa: BLE001
        return False


def note_signal(ctrl: int, now: float | None = None) -> str:
    """A console control event the keeper received: kept, and its words."""
    SIGNAL["at"] = time.time() if now is None else now
    SIGNAL["kind"] = CTRL_NAMES.get(ctrl, f"console event {ctrl}")
    return SIGNAL["kind"]


def ending(now: float | None = None, metrics=None) -> str | None:
    """Why the session seems to be ending (nothing is started, loaded or
    closed), or None."""
    now = time.time() if now is None else now
    at = SIGNAL.get("at")
    if isinstance(at, (int, float)) and now - at < _cfg("g9_signal_hold_s", 3600.0):
        return f"the keeper's console got a close signal ({SIGNAL.get('kind')})"
    if windows_ending(metrics):
        return "Windows is shutting down, restarting or logging off"
    return None


def all_closed_hold_s() -> float:
    return _cfg("g9_all_closed_hold_s", 600.0)


def install(on_signal=None) -> bool:
    """The keeper's console handler (Windows): a close, logoff or shutdown
    event is noted (`note_signal`) and `on_signal(words)` called (the keeper
    logs it and writes its status) before Windows ends the process; Ctrl-C
    and Ctrl-Break go on to Python's own handler (KeyboardInterrupt). True
    when installed."""
    if os.name != "nt" or _HANDLER:
        return bool(_HANDLER)
    try:
        import ctypes
        from ctypes import wintypes

        routine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

        def handler(ctrl):
            return 1 if handle(int(ctrl), on_signal) else 0
        cb = routine(handler)
        if not ctypes.windll.kernel32.SetConsoleCtrlHandler(cb, True):
            return False
        _HANDLER.append(cb)
        return True
    except Exception:  # noqa: BLE001  (no handler: the keeper runs as before)
        return False


def handle(ctrl: int, on_signal=None) -> bool:
    """One console event: True when it was ours (close, logoff, shutdown)."""
    if ctrl not in CTRL_NAMES:
        return False                        # Ctrl-C, Ctrl-Break: Python's KeyboardInterrupt
    words = note_signal(ctrl)
    if on_signal is not None:
        try:
            on_signal(words)
        except Exception:  # noqa: BLE001  (Windows ends the process anyway)
            pass
    return True
