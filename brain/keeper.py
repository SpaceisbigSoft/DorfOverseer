"""Keep the overseer running for a long unattended run.

    python brain\\keeper.py            (autopilot, unattended, no AI strategist)
    python brain\\keeper.py --ai       (also lets the strategist review: spends tokens)

It starts `overseer.py --autopilot --unattended`, shows and logs everything it
prints (logs/unattended.log), and restarts it when it stops on an error or
stops answering (its heartbeat file goes stale for 10 minutes), waiting a
little longer after each restart in a row (30 s up to 10 minutes). Ctrl-C
stops both. The overseer still obeys the in-game halt (Ctrl-Shift-H) and the
STOP file; so does this, in that it never restarts anything they stopped:
they don't stop the overseer, they only stop its actions.

No tokens are spent unless --ai is given.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LOG_DIR = Path(os.environ.get("DFAI_LOG_DIR") or ROOT / "logs")   # (13c) tests: a temp folder
LOG = LOG_DIR / "unattended.log"
STATUS = LOG_DIR / "unattended-status.txt"
HEARTBEAT = LOG_DIR / "heartbeat"
STALE_S = 600                 # no heartbeat for this long: the overseer is stuck
BACKOFF = [30, 60, 120, 300, 600]
GOOD_RUN_S = 1800             # running this long resets the back-off
LOG_OLD_KEPT = 5                # old copies kept
LOG_MAX = 5_000_000           # the log is rotated past this (one old copy kept)


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


LOCK = threading.Lock()


def log(line: str) -> None:
    """To the log file first, then the console; never raises (a failing
    console or a log someone has open must not stop the run)."""
    text = f"[{stamp()}] {line}"
    with LOCK:
        try:
            LOG_DIR.mkdir(exist_ok=True)
            if LOG.exists() and LOG.stat().st_size > LOG_MAX:
                try:
                    # (0.100.1) five old copies (unattended.old.log, .old2 ... .old5):
                    # a whole night stays for the morning's review
                    for i in range(LOG_OLD_KEPT, 1, -1):
                        older = LOG.with_suffix(f".old{i}.log")
                        newer = LOG.with_suffix(".old.log" if i == 2 else f".old{i - 1}.log")
                        if newer.exists():
                            newer.replace(older)
                    LOG.replace(LOG.with_suffix(".old.log"))
                except OSError:
                    pass                      # (open in a viewer: rotate later, keep appending)
            with LOG.open("a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass
        try:
            print(text, flush=True)
        except Exception:  # noqa: BLE001
            pass


def heartbeat_age() -> float | None:
    try:
        return time.time() - HEARTBEAT.stat().st_mtime
    except OSError:
        return None


def write_status(started: str, restarts: int, note: str) -> None:
    try:
        STATUS.write_text(f"keeper started {started}\nrestarts: {restarts}\nlast: {stamp()} {note}\n",
                          encoding="utf-8")
    except OSError:
        pass


def command(ai: bool) -> list[str]:
    cmd = [sys.executable, "-u", str(HERE / "overseer.py"), "--autopilot", "--unattended"]
    return cmd + (["--ai"] if ai else [])


def pump(proc: subprocess.Popen) -> None:
    """Copy the overseer's output to the console and the log."""
    while True:
        try:
            raw = proc.stdout.readline() if hasattr(proc.stdout, "readline") else next(proc.stdout, "")
        except Exception:  # noqa: BLE001  (keep reading: a stopped reader would block the overseer)
            continue
        if not raw:
            return
        line = raw.rstrip("\r\n")
        if line:
            log("  " + line)


# chores while the overseer runs: bringing the game back (--revive), the
# hourly summary of what the AI did (brain/run_summary.py) and the run check
# after each copy of the save (brain/health_check.py)
EXTRAS: dict = {"reviver": None, "run_start": None, "last_summary": None,
                "check_copy": None, "last_check": None, "check_thread": None, "copy_seen_at": 0.0}
SUMMARY_EVERY_S = 3600
CHECK_EVERY_S = 24 * 3600     # (0.104.0) the run check at least this often, copy or not
CHECK_FIRST_S = 3600          # ... the first one an hour into a run (a whole day without a check is long)
COPY_LOOK_S = 60              # backups/last.json looked at this often


def _backup_copy() -> str:
    """The newest copy of the save the overseer made (backups/last.json), or ""."""
    try:
        import backup
        return str(backup._last().get("copy") or "")
    except Exception:  # noqa: BLE001
        return ""


def _run_check(why: str) -> None:
    """The run check (self-test, log review, speed, housekeeping), its short
    form in this log. Runs in its own thread: the self-test takes a minute."""
    try:
        import health_check
        log(f"Check: {why}: the self-test and a look over the last day's logs...")
        flags, _page = health_check.check(24.0, selftest=True)
        for line in health_check.summary(flags):
            log(line)
    except Exception as e:  # noqa: BLE001  (a check never stops the run)
        log(f"Check: couldn't run ({e})")


def check_due(now: float) -> str | None:
    """Why a run check is due now, or None: a new copy of the save, or a
    day since the last check (the first an hour into the run)."""
    if now - EXTRAS.get("copy_seen_at", 0.0) >= COPY_LOOK_S:
        EXTRAS["copy_seen_at"] = now
        copy = _backup_copy()
        if EXTRAS.get("check_copy") is None:
            EXTRAS["check_copy"] = copy                 # the copy before this keeper started: not new
        elif copy and copy != EXTRAS["check_copy"]:
            EXTRAS["check_copy"] = copy
            return "after the day's copy of the save"
    last = EXTRAS.get("last_check")
    if last is None:
        EXTRAS["last_check"] = now - CHECK_EVERY_S + CHECK_FIRST_S
    elif now - last >= CHECK_EVERY_S:
        return "a day since the last check"
    return None


def maybe_check(now: float | None = None, start=None) -> bool:
    """Starts the run check when due and none is running. True if started."""
    now = time.time() if now is None else now
    t = EXTRAS.get("check_thread")
    if t is not None and t.is_alive():
        return False
    why = check_due(now)
    if not why:
        return False
    EXTRAS["last_check"] = now
    if start is None:
        th = threading.Thread(target=_run_check, args=(why,), daemon=True)
        th.start()
        EXTRAS["check_thread"] = th
    else:
        start(why)
    return True


def summary_lines(since=None) -> list[str]:
    try:
        import run_summary
        return run_summary.summarize(since or EXTRAS["run_start"] or datetime.now())
    except Exception as e:  # noqa: BLE001  (a summary never stops the run)
        return [f"(no summary: {e})"]


def pin_fort() -> None:
    """(0.105.0) The fort this run is pinned to (brain/pin.py), taken once the
    overseer has named it (or, with the game at the title, the last one played)."""
    if EXTRAS.get("pinned") or not EXTRAS.get("start_ts"):
        return
    try:
        import pin
        rv = EXTRAS.get("reviver")
        at_title = bool(rv is not None and getattr(rv, "title_since", None))
        EXTRAS["pinned"] = pin.take(EXTRAS["start_ts"], at_title=at_title, log=log)
    except Exception as e:  # noqa: BLE001  (a pin never stops the run)
        log(f"Keeper: couldn't pin the fort ({e})")
        EXTRAS["pinned"] = {"error": str(e)}


def chores() -> None:
    pin_fort()
    rv = EXTRAS.get("reviver")
    if rv is not None:
        try:
            rv.tick()
        except Exception as e:  # noqa: BLE001
            log(f"Revive: check failed ({e})")
    last = EXTRAS.get("last_summary")
    if EXTRAS.get("run_start") and (last is None or time.time() - last >= SUMMARY_EVERY_S):
        if last is not None:
            for line in summary_lines():
                log("Summary: " + line)
            write_soak_report()
        EXTRAS["last_summary"] = time.time()
    if EXTRAS.get("run_start"):
        try:
            maybe_check()
        except Exception as e:  # noqa: BLE001
            log(f"Check: couldn't start ({e})")


def write_soak_report() -> None:
    """logs/soak-report.txt brought up to date (the whole run so far)."""
    try:
        import soak_report
        hours = max(1.0, (datetime.now() - EXTRAS["run_start"]).total_seconds() / 3600)
        text = "\n".join(soak_report.report(round(hours + 0.5, 1)))
        (LOG_DIR / "soak-report.txt").write_text(text + "\n", encoding="utf-8")
    except Exception as e:  # noqa: BLE001  (a report never stops the run)
        log(f"(no soak report: {e})")


def run_once(ai: bool, popen=subprocess.Popen) -> tuple[int | None, str]:
    """Run the overseer until it exits or gets stuck. Returns (exit code or
    None if it was stopped for being stuck, why)."""
    try:
        HEARTBEAT.unlink(missing_ok=True)
    except OSError:
        pass
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",   # (dwarves' names have accents)
           "DFAI_PIN": "1"}       # (0.105.0) the overseer acts only on the pinned fort (brain/pin.py)
    proc = popen(command(ai), cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                 text=True, encoding="utf-8", errors="replace", env=env)
    t = threading.Thread(target=pump, args=(proc,), daemon=True)
    t.start()
    started = time.time()
    try:
        return _watch(proc, t, started)
    except KeyboardInterrupt:
        proc.kill()
        raise


def _watch(proc, t, started) -> tuple[int | None, str]:
    while True:
        code = proc.poll()
        if code is not None:
            t.join(timeout=5)
            return code, f"the overseer stopped (exit code {code})"
        chores()
        age = heartbeat_age()
        if (age is not None and age > STALE_S) or (age is None and time.time() - started > STALE_S):
            proc.kill()
            t.join(timeout=5)
            return None, f"the overseer stopped answering for {STALE_S // 60} minutes; restarted it"
        time.sleep(5)


def quick_edit_off() -> None:
    """Windows: a click in the console window (QuickEdit) freezes its output,
    which would freeze the overseer behind it. Turned off for this window."""
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-10)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, (mode.value & ~0x0040) | 0x0080)
    except Exception:  # noqa: BLE001
        pass


def single_instance():
    """An open, locked file while this keeper runs: a second keeper refuses
    (two autopilots on one fort would fight). Returns the file, or None."""
    LOG_DIR.mkdir(exist_ok=True)
    f = open(LOG_DIR / "keeper.lock", "a+")
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


def main(argv=None, popen=subprocess.Popen, sleep=time.sleep, max_runs: int | None = None) -> int:
    ap = argparse.ArgumentParser(description="Keep the overseer running, unattended.")
    ap.add_argument("--ai", action="store_true", help="let the AI strategist review now and then (spends tokens)")
    ap.add_argument("--revive", action="store_true",
                    help="start Dwarf Fortress again if it closes (config.json \"df_launch\") and load the "
                         "fort's newest save when the game sits at the title screen")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    lock = single_instance()
    if lock is None:
        log("Another keeper is already running for this folder: not starting a second one.")
        return 1
    quick_edit_off()
    started = stamp()
    log(f"Keeper starting: overseer.py {' '.join(command(args.ai)[3:])}. Ctrl-C stops it.")
    EXTRAS["run_start"] = datetime.now()
    # (0.105.0) a new run pins afresh: the fort the overseer names first
    try:
        import pin
        pin.clear()
    except Exception:  # noqa: BLE001
        pass
    EXTRAS["start_ts"], EXTRAS["pinned"] = time.time(), None
    if args.revive:
        try:
            import revive
            EXTRAS["reviver"] = revive.Reviver(log)
            log("Revive is on: a closed game is started again"
                + ("" if revive.launch_command() else " (no \"df_launch\" in config.json yet: it can't be)")
                + ", and a game left at the title screen loads the fort's newest save.")
        except Exception as e:  # noqa: BLE001
            log(f"Revive couldn't start ({e}); running without it.")
    restarts, streak, runs = 0, 0, 0
    try:
        while max_runs is None or runs < max_runs:
            runs += 1
            t0 = time.time()
            code, why = run_once(args.ai, popen)
            log(why)
            if time.time() - t0 >= GOOD_RUN_S:
                streak = 0
            wait = BACKOFF[min(streak, len(BACKOFF) - 1)]
            streak += 1
            restarts += 1
            write_status(started, restarts, f"{why}; restarting in {wait} s")
            log(f"Restarting the overseer in {wait} s (restart {restarts}).")
            sleep(wait)
    except KeyboardInterrupt:
        for line in summary_lines():
            log("Summary: " + line)
        write_soak_report()
        log("Keeper stopped (Ctrl-C).")
        return 0
    finally:
        lock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
