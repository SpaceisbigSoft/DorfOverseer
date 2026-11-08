"""Scenario runs: let a test fort play for a set time and measure how it does.

    python brain/scenario.py prepare --name "AI Run A"
        copy the backup test save (saves/AI Test Save) into the game's save
        folder under a new name; then load that save in Dwarf Fortress

    python brain/scenario.py run --mode planner --days 84 --label planner-a
        play 84 in-game days, one day at a time, recording numbers each day
        modes:  planner   the local planner on autopilot (no tokens)
                ai        planner + AI strategist (uses tokens; see docs/ai-setup.md)
                baseline  DFHack's automation tools only, no AI (for comparison)
                none      nothing at all

    python brain/scenario.py compare             compare the latest runs
    python brain/scenario.py compare RUN RUN...  compare these runs
    python brain/scenario.py fps                 does the overseer slow the game?

Runs go in logs/runs/<time>-<label>/: metrics.csv (one row per day),
days.jsonl (each day's numbers, events and decisions, for brain/replay.py),
summary.json. Use a TEST save: the run plays the fort for real.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import metrics  # noqa: E402
import overseer  # noqa: E402
from bridge import LOG_DIR, Bridge, BridgeError  # noqa: E402
from dfhack import PROJECT_ROOT, DFHackError, GameNotRunning, read_config, save_root  # noqa: E402
from planner import TICKS_PER_DAY  # noqa: E402
from util import date_tick as abs_tick  # noqa: E402

RUNS_DIR = LOG_DIR / "runs"
BACKUP_SAVES = PROJECT_ROOT / "saves"
# "DFHack's automation tools alone": what a player typically turns on.
BASELINE_TOOLS = ["autochop", "autobutcher", "seedwatch", "nestboxes", "tailor", "autofarm",
                  "autoclothing", "suspendmanager", "buildingplan"]


def say(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


class EventTap:
    """The bridge, but every batch of events is also kept for the day's record."""

    def __init__(self, bridge: Bridge):
        self._bridge = bridge
        self.caught: list[dict] = []

    def events(self):
        ev = self._bridge.events()
        self.caught.extend(ev)
        return ev

    def take(self) -> list[dict]:
        ev, self.caught = self.caught, []
        return ev

    def __getattr__(self, name):
        return getattr(self._bridge, name)


def clear_popups(bridge: Bridge) -> None:
    """(0.100) Time stands still with the game running: DF waits on a popup
    (an artifact, a mood). Like the keeper's unattended loop, the popup is
    taken off (its text is in the reports anyway); the run carries on. A
    menu or screen only a click closes is left, with a word to the player."""
    try:
        r = bridge.act({"type": "unpause", "unstick": True})
    except (BridgeError, DFHackError) as e:
        say(f"The game isn't advancing and the popup couldn't be taken off ({e}): close it in DF to continue.")
        return
    n = r.get("popups_cleared", 0) if r.get("ok") else 0
    if n:
        say(f"The game stood still on {n} popup(s) waiting for a click: taken off, carrying on.")
    else:
        say("The game isn't advancing and there's no popup to take off: is a menu or screen open in DF? "
            "Close it to continue." + ("" if r.get("ok") else f" ({r.get('error')})"))


def quiet_announcements(bridge: Bridge) -> None:
    """(0.100) No announcement pauses the run or opens a box (in DF's memory
    only, until DF restarts), as the keeper does unattended. Time runs the
    same either way; it only spares the run waiting on popups."""
    try:
        r = bridge.act({"type": "quiet_announcements"})
    except (BridgeError, DFHackError) as e:
        say(f"Couldn't quiet the announcements ({e}); popups are taken off when they stall the run.")
        return
    if r.get("ok"):
        say(f"Announcements won't pause the run or open a box ({r.get('pausing', 0)} paused, "
            f"{r.get('boxes', 0)} opened one; until DF is restarted).")
    else:
        say(f"Couldn't quiet the announcements ({r.get('error')}); popups are taken off when they stall the run.")


def run_one_day(bridge: Bridge) -> bool:
    """Let exactly one in-game day pass. DF pauses itself for some
    announcements; the run simply carries on. False if it couldn't."""
    start = abs_tick(bridge.status()["date"])
    target = start + TICKS_PER_DAY
    for _ in range(8):
        now = abs_tick(bridge.status()["date"])
        remaining = target - now
        if remaining <= 0:
            return True
        bridge.run_ticks(remaining)
        try:
            bridge.wait_for_run(remaining, on_stall=lambda: clear_popups(bridge))
        except BridgeError as e:
            if "did not finish in time" not in str(e):
                raise
            # Very slow, but moving: keep going with what's left of the day.
            say(f"The game is running very slowly (fps {bridge.status().get('fps')}); carrying on.")
    return abs_tick(bridge.status()["date"]) >= target


def snapshot(path: Path, state: dict) -> None:
    """(0.100) The fort's report at a run's start or end, for
    brain/compare_runs.py (what each fort built and became, not only the
    daily numbers). Never stops the run."""
    try:
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except (OSError, TypeError, ValueError) as e:
        say(f"Couldn't write {path.name}: {e}")


def settle_trade(bridge: Bridge, tap, backend, mode: str) -> None:
    """(0.99.13) DF's trade screen holds time still, so a run that plans once
    a day never reaches the next day while it's open (the War-hold run sat at
    the screen). Like the keeper's loop: a few cycles while it's open, so the
    AI can finish its deal and close it; then it's closed outright."""
    for _ in range(overseer.TRADE_CYCLES_MAX + 2):
        st = bridge.status()
        if not st.get("trade_open"):
            return
        if mode in ("planner", "ai"):
            controls = {"halted": st.get("halted") is True, "decisions": st.get("decisions") or {}}
            overseer.one_cycle(tap, autopilot=True, backend=backend, controls=controls, mode_override="autopilot")
        time.sleep(1)
    if bridge.status().get("trade_open"):
        try:
            # (0.100) force: no player trades during a run, and a screen the AI
            # didn't recognise as its own would otherwise hold time still for good
            r = bridge.act({"type": "close_trade", "force": True})
            say("The trade screen stayed open: closed it" + ("" if r.get("ok") else f" (failed: {r.get('error')})"))
        except (BridgeError, DFHackError) as e:
            say(f"The trade screen stayed open and couldn't be closed: {e}")


def df_save_dir(bridge: Bridge | None) -> Path:
    """The game's save folder (0.99.13: DF's user folder first, where the
    Steam game keeps its saves; the game's own folder only for portable ones)."""
    df_path = None
    if bridge is not None and bridge.version and bridge.version.get("df_path"):
        df_path = bridge.version["df_path"]
    if df_path is None:
        # ...\steamapps\common\DFHack\hack\dfhack-run.exe -> ...\steamapps\common\Dwarf Fortress
        df_path = Path(read_config()["dfhack_run"]).parents[2] / "Dwarf Fortress"
    root = save_root(df_path)
    return root if root is not None else Path(df_path) / "save"


# --- prepare ----------------------------------------------------------------------

def cmd_prepare(args) -> int:
    src = BACKUP_SAVES / args.source
    if not src.is_dir():
        say(f"No backup save at {src}. See saves/README.md.")
        return 1
    bridge = None
    try:
        bridge = Bridge()
        bridge.handshake()
    except (GameNotRunning, DFHackError):
        bridge = None
    dest = df_save_dir(bridge) / args.name
    if dest.exists():
        say(f"{dest} already exists. Pick another --name (runs should start from a fresh copy).")
        return 1
    say(f"Copying {src.name} to {dest} ...")
    shutil.copytree(src, dest)
    # (0.105.0) a run id, written into the save the first time it's played:
    # the copy logs apart from the real fort (brain/scenario_mark.py)
    import scenario_mark
    run_id = scenario_mark.new_run(args.name)
    say(f"Done (run id {run_id}). In Dwarf Fortress: Continue Playing -> {args.name}. Then run:\n"
        f'  python brain\\scenario.py run --mode planner --days 84 --label "{args.name}"')
    return 0


# --- run -----------------------------------------------------------------------------

def looks_like_test(save_dir: str) -> bool:
    s = save_dir.lower()
    return "test" in s or s.startswith("ai run")


def cmd_run(args) -> int:
    days = args.days if args.days else round(args.years * 336)
    try:
        bridge = Bridge()
        info = bridge.handshake()
    except GameNotRunning:
        say("Dwarf Fortress isn't running.")
        return 1
    st = bridge.status()
    if not st.get("in_fort"):
        say("Load the fort to test first.")
        return 1
    state = bridge.state(include_units=False)
    fort = state.get("fort") if isinstance(state.get("fort"), dict) else {}
    save_dir = str(fort.get("save_dir") or "?")
    if not looks_like_test(save_dir) and not args.yes:
        say(f'The loaded save is "{save_dir}". Scenario runs play the fort for real, so they only run on '
            'saves whose folder name contains "test" or starts with "AI Run" (see the prepare command). '
            "Add --yes to run anyway.")
        return 1
    backend = None
    if args.mode == "ai":
        backend = overseer.make_backend()
        if backend is None:
            return 1

    label = args.label or args.mode
    run_dir = RUNS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{''.join(c if c.isalnum() or c in '-_' else '-' for c in label)}"
    run_dir.mkdir(parents=True)
    overseer.JOURNAL = run_dir / "decisions.jsonl"        # this run's decisions only
    (run_dir / "run.json").write_text(json.dumps({
        "label": label, "mode": args.mode, "days": days, "save_dir": save_dir,
        "start_date": state.get("date"), "bridge_version": info.get("bridge_version"),
        "started": datetime.now().isoformat(timespec="seconds")}, indent=1), encoding="utf-8")
    say(f'Run "{label}" ({args.mode}) on "{save_dir}" for {days} in-game days -> {run_dir}')
    snapshot(run_dir / "start-state.json", state)     # (0.100) for brain/compare_runs.py
    say("Ctrl-C stops the run cleanly (the summary is still written). Ctrl-Shift-H in game halts the AI.")
    say("Don't run brain/overseer.py at the same time: the run does the overseer's job itself.")
    if st.get("halted") is True and args.mode in ("planner", "ai", "baseline"):
        say("Note: the AI is halted in this save (Ctrl-Shift-H), so it will only watch. Resume it to test it.")

    if args.mode == "baseline":
        for name in BASELINE_TOOLS:
            try:
                r = bridge.act({"type": "tool", "name": name, "enabled": True})
                say(f"  baseline: {name} {'on' if r.get('ok') else 'not available: ' + str(r.get('error'))}")
            except (BridgeError, DFHackError) as e:
                say(f"  baseline: {name} failed: {e}")

    quiet_announcements(bridge)
    tap = EventTap(bridge)
    import scenario_mark
    scenario_mark.mark(bridge, state, say)                # (0.105.0) a prepared copy: its own logs
    key = overseer.fort_key(state)
    rows, fell, journal_pos = [], False, 0
    tokens_start = overseer.load(key)[1].total_used if key else 0
    try:
        for day in range(1, days + 1):
            settle_trade(bridge, tap, backend, args.mode)
            ok = run_one_day(bridge)
            if not ok:
                settle_trade(bridge, tap, backend, args.mode)       # a trade screen opened mid-day
                ok = run_one_day(bridge)
            if not ok:
                say("Couldn't get the game to advance; stopping.")
                break
            controls = None
            if args.mode in ("planner", "ai"):
                st = bridge.status()
                controls = {"halted": st.get("halted") is True, "decisions": st.get("decisions") or {}}
                overseer.one_cycle(tap, autopilot=True, backend=backend, controls=controls,
                                   mode_override="autopilot")
            else:
                tap.events()
            st = bridge.status()
            if not st.get("in_fort"):
                say("The fort is gone (lost or unloaded).")
                fell = True
                break
            # (0.100) the report the cycle just took, when it is of this moment:
            # fetching it again froze the game a second time each day (~250 ms)
            full = overseer.LAST_FULL.get("state") if args.mode in ("planner", "ai") else None
            if isinstance(full, dict) and full.get("date") == st.get("date"):
                state = json.loads(json.dumps(full))
            else:
                state = bridge.state(include_units=False)
            events = tap.take()
            decisions, journal_pos = new_decisions(run_dir / "decisions.jsonl", journal_pos)
            done = count_actions(decisions)
            tokens = (overseer.load(key)[1].total_used - tokens_start) if key and backend else 0
            row = metrics.day_row(day, state, events, ai_actions=done, tokens_used=tokens, fps=st.get("fps"))
            rows.append(row)
            metrics.write_row(run_dir / "metrics.csv", row)
            with (run_dir / "days.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"day": day, "row": row, "events": events, "decisions": decisions},
                                   ensure_ascii=False) + "\n")
            if day % 7 == 0 or day == days:
                say(f"  day {day}/{days} ({row['date']}): {row['population']} dwarves, "
                    f"{row['unhappy_pct']}% unhappy, {row['idle_pct']}% idle, wealth {row['wealth']}, fps {row['fps']}")
            if row["population"] == 0:
                say("No citizens are left: the fort has fallen.")
                fell = True
                break
    except KeyboardInterrupt:
        say("Stopped by you.")
    except (BridgeError, DFHackError) as e:
        say(f"Stopped: problem talking to the game: {e}")
    try:
        snapshot(run_dir / "end-state.json", bridge.state(include_units=False))
    except (BridgeError, DFHackError) as e:
        say(f"Couldn't save the fort's end state: {e}")
    summary = metrics.summarize(rows, label, args.mode, fell)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    say(f"Done: {len(rows)} days recorded. Summary:")
    print(metrics.compare_table([summary]))
    return 0


DISPLAY_ONLY = {"report_status", "set_culture", "save_memory"}


def count_actions(decisions: list[dict]) -> int:
    """Actions that changed the fort (not the panel's display updates)."""
    return sum(1 for d in decisions if d.get("kind") == "decision"
               and (d.get("result") or {}).get("ok") is True
               and (d.get("action") or {}).get("type") not in DISPLAY_ONLY)


def new_decisions(path: Path, pos: int) -> tuple[list[dict], int]:
    if not path.exists():
        return [], pos
    with path.open(encoding="utf-8") as f:
        f.seek(pos)
        lines = f.read()
        pos = f.tell()
    return [json.loads(x) for x in lines.splitlines() if x.strip()], pos


# --- compare -----------------------------------------------------------------------------

def find_runs(names: list[str], latest: int) -> list[Path]:
    if names:
        out = []
        for n in names:
            p = Path(n) if Path(n).is_dir() else RUNS_DIR / n
            if not p.is_dir():
                matches = sorted(RUNS_DIR.glob(f"*{n}*"))
                p = matches[-1] if matches else p
            out.append(p)
        return out
    return sorted(p for p in RUNS_DIR.glob("*") if (p / "summary.json").exists())[-latest:]


def fresh_summary(run_dir: Path) -> dict:
    """The run's summary, recomputed from its daily rows, so runs recorded
    before a new measure was added still get it."""
    saved = metrics.load_summary(run_dir)
    csv_path = run_dir / "metrics.csv"
    if not csv_path.exists():
        return saved
    rows = metrics.read_rows(csv_path)
    if not rows:
        return saved
    fresh = metrics.summarize(rows, saved.get("label", ""), saved.get("mode", ""), saved.get("fell", False))
    return {**saved, **fresh}


def cmd_compare(args) -> int:
    runs = find_runs(args.runs, args.latest)
    summaries = []
    for r in runs:
        try:
            summaries.append(fresh_summary(r))
        except (OSError, ValueError):
            say(f"No summary in {r}")
    if not summaries:
        say("No finished runs found in logs\\runs.")
        return 1
    print(metrics.compare_table(summaries))
    print("\n* = better. Runs started from the same save are the fair comparison.")
    return 0


# --- fps --------------------------------------------------------------------------------------

def cmd_fps(args) -> int:
    """Run the game twice for the same time: once barely checked on, once
    checked as often as the overseer does (every 2 s), and compare FPS. Also
    times one full fort report (the game waits while it's built)."""
    bridge = Bridge()
    bridge.handshake()
    if not bridge.status().get("in_fort"):
        say("Load a fort first.")
        return 1
    secs = args.seconds

    def sample(poll_every: float) -> list[int]:
        bridge.run_ticks(100000)
        fps, end = [], time.monotonic() + secs
        time.sleep(3)                                   # let FPS settle
        while time.monotonic() < end:
            time.sleep(poll_every)
            st = bridge.status()
            if st.get("paused"):                       # DF paused itself: carry on
                bridge.run_ticks(100000)
                continue
            if st.get("fps"):
                fps.append(st["fps"])
        bridge.pause()
        return fps

    say(f"Measuring for {secs} s without the overseer's polling (one check every 10 s)...")
    quiet = sample(10.0)
    say(f"Measuring for {secs} s with polling every 2 s, like the overseer...")
    busy = sample(2.0)
    t0 = time.perf_counter()
    state = bridge.state(include_units=False)
    report_ms = (time.perf_counter() - t0) * 1000
    q = sum(quiet) / len(quiet) if quiet else 0
    b = sum(busy) / len(busy) if busy else 0
    say(f"FPS without polling: {q:.0f}   with polling: {b:.0f}   "
        f"difference: {(b - q) / q * 100 if q else 0:+.1f}%")
    say(f"One full fort report takes {report_ms:.0f} ms (the game waits for it); "
        f"in-game build time {state.get('_meta', {}).get('build_ms')} ms. The overseer makes one per in-game day.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Scenario runs: play a test fort and measure it.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="copy the backup test save into the game under a new name")
    p.add_argument("--name", required=True, help='e.g. "AI Run A"')
    p.add_argument("--source", default="AI Test Save", help="folder in saves/ to copy")
    r = sub.add_parser("run", help="play the loaded fort for a while and record numbers")
    r.add_argument("--mode", choices=["planner", "ai", "baseline", "none"], default="planner")
    r.add_argument("--days", type=int, default=0, help="in-game days to play")
    r.add_argument("--years", type=float, default=0.25, help="or in-game years (default 0.25 = 84 days)")
    r.add_argument("--label", default="", help="a name for this run")
    r.add_argument("--yes", action="store_true", help="allow a save not named like a test")
    c = sub.add_parser("compare", help="compare finished runs side by side")
    c.add_argument("runs", nargs="*", help="run folder names (or parts of them); default: the latest")
    c.add_argument("--latest", type=int, default=4)
    f = sub.add_parser("fps", help="measure whether the overseer slows the game")
    f.add_argument("--seconds", type=int, default=30)
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    return {"prepare": cmd_prepare, "run": cmd_run, "compare": cmd_compare, "fps": cmd_fps}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
