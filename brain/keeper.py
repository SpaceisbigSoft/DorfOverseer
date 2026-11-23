"""Keep the overseer running for a long unattended run.

    python brain\\keeper.py            (autopilot, unattended, no AI strategist)
    python brain\\keeper.py --ai       (also lets the strategist review: spends tokens)
    python brain\\keeper.py --preset "War-hold"   (the fort given that preset once, at the start)

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

from util import folder_lock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LOG_DIR = Path(os.environ.get("DFAI_LOG_DIR") or ROOT / "logs")   # (13c) tests: a temp folder
LOG = LOG_DIR / "unattended.log"
STATUS = LOG_DIR / "unattended-status.txt"
HEARTBEAT = LOG_DIR / "heartbeat"
STOP_FILE = LOG_DIR / "keeper-stop"   # (0.105.77) the keepers' window asks a keeper without a console to stop
STALE_S = 600                 # no heartbeat for this long: the overseer is stuck
BACKOFF = [30, 60, 120, 300, 600]
GOOD_RUN_S = 1800             # running this long resets the back-off
SHORT_RUNS_LOUD = 5           # (0.105.48, K8) this many short runs in a row: said loudly
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
            LOG_DIR.mkdir(parents=True, exist_ok=True)   # (0.105.0) a first run: no logs folder yet
            if LOG.exists() and LOG.stat().st_size > LOG_MAX:
                try:
                    # (0.100.1) five old copies (unattended.old.log, .old2 ... .old5):
                    # a whole night stays for the morning's review
                    # (0.105.77, verifier) the live log renamed first: a viewer
                    # holding it (the keepers' window's live log) then shifts
                    # nothing, so the old copies aren't run together line by line
                    tmp = LOG.with_suffix(".rotating.log")
                    LOG.replace(tmp)
                    for i in range(LOG_OLD_KEPT, 1, -1):
                        older = LOG.with_suffix(f".old{i}.log")
                        newer = LOG.with_suffix(".old.log" if i == 2 else f".old{i - 1}.log")
                        if newer.exists():
                            newer.replace(older)
                    tmp.replace(LOG.with_suffix(".old.log"))
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


def command(ai: bool, preset: str | None = None) -> list[str]:
    cmd = [sys.executable, "-u", str(HERE / "overseer.py"), "--autopilot", "--unattended"]
    # (0.105.4) --preset: the overseer applies it once, before the fort's first
    # cycle, and records it (logs/keeper-preset.json): a restart or a revive
    # passes it again, but it isn't applied again over the player's changes
    return cmd + (["--ai"] if ai else []) + (["--preset", preset] if preset else [])


PUMP_ERRORS_MAX = 20          # (0.105.48, K17) reads failing this many times in a row: the reader gives up


def pump(proc: subprocess.Popen, sleep=time.sleep) -> None:
    """Copy the overseer's output to the console and the log.

    (0.105.48, K17) A read that fails is tried again (a stopped reader would
    block the overseer), but not for ever: a reader that keeps raising spun
    a core at full speed. After PUMP_ERRORS_MAX failures in a row it says so
    and stops; the heartbeat watch still restarts a blocked overseer."""
    errors = 0
    while True:
        try:
            raw = proc.stdout.readline() if hasattr(proc.stdout, "readline") else next(proc.stdout, "")
        except Exception as e:  # noqa: BLE001  (keep reading: a stopped reader would block the overseer)
            errors += 1
            if errors >= PUMP_ERRORS_MAX:
                log(f"Keeper: the overseer's output can't be read ({type(e).__name__}: {str(e)[:120]}), "
                    f"{errors} times in a row: no longer copied to this log.")
                return
            sleep(0.05 * errors)
            continue
        errors = 0
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
        # (0.105.33) left None, so the next chore tries again (an error dict
        # was truthy: the run went unpinned for good); said once
        if not EXTRAS.get("pin_error_said"):
            log(f"Keeper: couldn't pin the fort ({e}); trying again")
            EXTRAS["pin_error_said"] = True
        EXTRAS["pinned"] = None


class StopAsked(KeyboardInterrupt):
    """(0.105.77) logs/keeper-stop found: stopped as Ctrl-C stops it."""


def stop_asked() -> None:
    """(0.105.77) The one-window keepers launcher (start-keepers.ps1) runs the
    keepers with no console of their own, so Ctrl-C can't reach them: it
    writes logs/keeper-stop instead. Found (every 5 s, with the chores): the
    file removed and the keeper stopped as by Ctrl-C (the overseer ended, the
    fort left open, the summary and the status written)."""
    try:
        if not STOP_FILE.exists():
            return
        STOP_FILE.unlink(missing_ok=True)
    except OSError:
        return
    log("Keeper: asked to stop (logs/keeper-stop, from the keepers' window).")
    raise StopAsked()


def chores() -> None:
    stop_asked()
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


def run_once(ai: bool, popen=subprocess.Popen, preset: str | None = None) -> tuple[int | None, str]:
    """Run the overseer until it exits or gets stuck. Returns (exit code or
    None if it was stopped for being stuck, why)."""
    try:
        HEARTBEAT.unlink(missing_ok=True)
    except OSError:
        pass
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",   # (dwarves' names have accents)
           "DFAI_PIN": "1"}       # (0.105.0) the overseer acts only on the pinned fort (brain/pin.py)
    proc = popen(command(ai, preset), cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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


LEAVE_BRIDGE = None        # tests replace this: a factory for the bridge


def leave_fort_open() -> None:
    """(0.105.47, J16) The keeper stopping (Ctrl-C; the overseer it ran was
    killed without a word): the fort left open through the bridge if no
    enemy is in reach (brain/planner_way_out.py leave_open), logged. Never
    raises (the game may be closed)."""
    try:
        import planner_way_out
        if LEAVE_BRIDGE is not None:
            bridge = LEAVE_BRIDGE()
        else:
            from bridge import Bridge
            bridge = Bridge()
        planner_way_out.leave_open(bridge, log)
    except BaseException as e:  # noqa: BLE001 - a second Ctrl-C, no game: the keeper still stops
        log(f"Leaving the fort open: not done ({type(e).__name__}: {str(e)[:100]}).")


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


def close_handler(started: str) -> bool:
    """(r1g9) Windows closing the keeper's console (the window closed, a
    logoff, a shutdown): said in the log and the status file before Windows
    ends the process, and the reviver holds from then on (brain/session_end.py):
    on 16 Nov the keepers started and reloaded games while Windows shut down,
    and their logs ended on dfhack-run's exit code 0xC000013A, unexplained.
    Ctrl-C stops the keeper as before. True when installed."""
    def on_signal(words: str) -> None:
        log(f"Keeper: {words}: the console is closing. Nothing is started or loaded again; the keeper and its "
            "overseer end with it.")
        write_status(started, int(EXTRAS.get("restarts") or 0), f"Keeper stopped: {words} (the console was closed)")
    try:
        import session_end
        return session_end.install(on_signal)
    except Exception:  # noqa: BLE001  (no handler: the keeper runs as before)
        return False


def single_instance():
    """An open, locked file (logs/keeper.lock) while this keeper runs: a second
    keeper, or a manual overseer.py --autopilot, refuses (two autopilots on
    one fort would fight). Returns the file, or None."""
    return folder_lock(LOG_DIR)


def sleep_doing_chores(wait: float, step: float = 5.0, sleep=time.sleep) -> None:
    """(0.105.33) The back-off between overseer runs, in 5-s steps with the
    chores between (revive probe, pin, check): a run of overseer crashes no
    longer delays bringing DF back by up to 10 minutes each."""
    left = float(wait)
    while left > 0:
        sleep(min(step, left))
        left -= step
        chores()


def main(argv=None, popen=subprocess.Popen, sleep=None, max_runs: int | None = None) -> int:
    ap = argparse.ArgumentParser(description="Keep the overseer running, unattended.")
    ap.add_argument("--ai", action="store_true", help="let the AI strategist review now and then (spends tokens)")
    ap.add_argument("--revive", action="store_true",
                    help="start Dwarf Fortress again if it closes (config.json \"df_launch\") and load the "
                         "fort's newest save when the game sits at the title screen")
    ap.add_argument("--preset", metavar="NAME",
                    help="apply this built-in or saved preset (e.g. \"War-hold\") to the fort once at the start "
                         "(as the window's Load preset); a restart or revive doesn't apply it again over your changes")
    args = ap.parse_args(argv)
    preset = (args.preset or "").strip() or None
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    lock = single_instance()
    if lock is None:
        log("Another keeper is already running for this folder: not starting a second one.")
        return 1
    try:
        STOP_FILE.unlink(missing_ok=True)       # (0.105.77) an old ask never stops a new run (at once: verifier)
    except OSError:
        pass
    quick_edit_off()
    started = stamp()
    close_handler(started)
    log(f"Keeper starting: overseer.py {' '.join(command(args.ai, preset)[3:])}. Ctrl-C stops it.")
    if preset:
        log(f"Preset: {preset} asked for: applied to the fort before its first cycle, unless this fort "
            "already had it from --preset (logs/keeper-preset.json).")
    EXTRAS["run_start"] = datetime.now()
    # (0.105.0) a new run pins afresh: the fort the overseer names first
    try:
        import pin
        pin.clear()
    except Exception:  # noqa: BLE001
        pass
    EXTRAS["start_ts"], EXTRAS["pinned"] = time.time(), None
    port_note()
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
    write_status(started, restarts, "running")      # (0.105.48, K8) health_check reads how it ended
    try:
        while max_runs is None or runs < max_runs:
            runs += 1
            t0 = time.time()
            try:
                code, why = run_once(args.ai, popen, preset)
            except Exception as e:  # noqa: BLE001  (0.105.48, K8) e.g. OSError from popen: logged, retried
                code, why = None, f"the overseer couldn't be run ({type(e).__name__}: {str(e)[:200]})"
                log_exception(e)
            log(why)
            if time.time() - t0 >= GOOD_RUN_S:
                streak = 0
            wait = BACKOFF[min(streak, len(BACKOFF) - 1)]
            streak += 1
            restarts += 1
            EXTRAS["restarts"] = restarts
            if streak >= SHORT_RUNS_LOUD and streak % SHORT_RUNS_LOUD == 0:
                # (0.105.48, K8) the overseer dies at start every time (a bad
                # delivery?): the game runs on with no AI; said loudly
                log(f"Keeper: the overseer has stopped {streak} times in a row, each within "
                    f"{GOOD_RUN_S // 60} minutes (last: {why}): the game is running with no AI. "
                    "Look at logs/overseer-errors.log and this log.")
            write_status(started, restarts, f"{why}; restarting in {wait} s"
                         + (f" ({streak} short runs in a row: the game runs with no AI)"
                            if streak >= SHORT_RUNS_LOUD else ""))
            log(f"Restarting the overseer in {wait} s (restart {restarts}).")
            if sleep is None:
                sleep_doing_chores(wait)
            else:
                sleep(wait)                   # (tests)
    except KeyboardInterrupt as e:
        how = "asked by the keepers' window" if isinstance(e, StopAsked) else "Ctrl-C"
        leave_fort_open()             # (0.105.47, J16) a fort left alone is never sealed
        for line in summary_lines():
            log("Summary: " + line)
        write_soak_report()
        log(f"Keeper stopped ({how}).")
        write_status(started, restarts, f"Keeper stopped ({how})")
        return 0
    except BaseException as e:  # noqa: BLE001  (0.105.48, K8) never silently: logged, status written
        if isinstance(e, SystemExit) and e.code in (0, None):
            raise
        log_exception(e)
        log(f"Keeper stopped unexpectedly ({type(e).__name__}: {str(e)[:200]}); exit status 2. "
            "Nothing restarts the overseer until the keeper is started again.")
        write_status(started, restarts, f"Keeper stopped unexpectedly ({type(e).__name__}: {str(e)[:200]})")
        leave_fort_open()
        return 2
    finally:
        lock.close()
    write_status(started, restarts, f"Keeper stopped (after {runs} runs)")
    return 0


def port_note() -> str | None:
    """(0.105.48, K17) Six keepers run at once, one game each: a config.json
    without its own "dfhack_port" talks to DFHack's 5000 (A's game), and one
    without a df_launch .exe can't tell its game from the others. Said at
    the start; returns the line (None when both are set)."""
    try:
        from dfhack import read_config
        cfg = read_config()
        from util import own_df_folder
    except Exception:  # noqa: BLE001
        return None
    missing = []
    if not isinstance(cfg.get("dfhack_port"), int):
        missing.append('"dfhack_port" (DFHack\'s default 5000 is used: the first game\'s port)')
    if not own_df_folder():
        missing.append('"df_launch" naming this copy\'s Dwarf Fortress.exe (its game can\'t be told from the '
                       "others: no check that the game answering is this folder's)")
    if not missing:
        return None
    line = "Keeper: config.json has no " + "; no ".join(missing) + ". With several games on this PC, set both."
    log(line)
    return line


def log_exception(e: BaseException) -> None:
    """(0.105.48, K8) The traceback into the log (the console window may be
    closed or scrolled away), "Traceback" first so the run check counts it."""
    import traceback
    try:
        text = "".join(traceback.format_exception(type(e), e, e.__traceback__))
    except Exception:  # noqa: BLE001
        text = f"Traceback: {type(e).__name__}: {e}"
    for line in text.rstrip().splitlines()[-30:]:
        log("  " + line)


if __name__ == "__main__":
    try:
        status = main()
    except BaseException as e:  # noqa: BLE001  (0.105.48, K8) e.g. before the loop: still logged
        if isinstance(e, SystemExit):
            raise
        log_exception(e)
        log(f"Keeper stopped unexpectedly ({type(e).__name__}: {str(e)[:200]}); exit status 2.")
        status = 2
    if status:
        log(f"Keeper exit status {status}.")
    sys.exit(status)
