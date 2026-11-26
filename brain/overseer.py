"""The overseer: runs the local planner (and optionally the AI strategist)
alongside your game.

    python brain/overseer.py                   dry run: shows what it WOULD do
    python brain/overseer.py --autopilot       actually does it (one autopilot per DF-AI folder:
                                               it refuses while a keeper runs, logs/keeper.lock)
    python brain/overseer.py --ai --autopilot  ...and lets the AI strategist steer
    python brain/overseer.py --once            plan a single cycle and exit

Plans once per in-game day while the game is running (you control the game
speed and pausing as usual), and straight away when something happens (a
siege, a death). The planner costs no tokens. With --ai, the strategist reviews
the fort now and then, spending from the token bank you set in the in-game panel
(Ctrl-Shift-O, "AI & tokens"); see docs/ai-setup.md to connect it.

Stop with Ctrl-C, or create a file named STOP in the project folder to halt all
actions without quitting. Everything is written to the fort's journal in
logs/forts/<fort>/journal.jsonl.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import os
import sys
import time
import traceback
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bridge import LOG_DIR, Bridge, BridgeError  # noqa: E402
from dfhack import PROJECT_ROOT, DFHackError, GameNotRunning  # noqa: E402
from util import folder_lock, load_json  # noqa: E402
from planner import (NEEDS_YOU, PLANNER_CONFIG, TICKS_PER_YEAR, Memory, abs_tick,  # noqa: E402
                     effective_config, note_cycle, note_tantrums, plan, record, select)
from planner_guards import guard_fail, guard_lines, guard_ok  # noqa: E402  (0.105.48, K6) the cycle's guards
from planner_core import limit_exempt  # noqa: E402  (0.105.48, K6)
from planner_tantrums import note_tantrum_book  # noqa: E402  (0.105.47)
from planner_society import note_heists  # noqa: E402  (0.105.24)
from planner_moods import mood_journal  # noqa: E402  (0.105.30)
from planner_missions import mission_journal  # noqa: E402  (0.105.39)
from planner_cleanup import CLEANUP_ACTIONS, cleanup_journal, cleanup_words  # noqa: E402  (0.105.40)
from planner_thirst import thirst_journal  # noqa: E402  (0.105.46, I2) deaths of thirst for the journal
from planner_recovery import recovery_journal  # noqa: E402  (0.105.46, I4) collapse recovery
from planner_shopslots import shop_level_action  # noqa: E402  (0.105.54) workshops onto shared levels
from planner_floors import floor_action, floor_outcome, not_on_floor_words  # noqa: E402  (layout B) hallway-first floors
from planner_floors import journal_hint as floor_journal_hint  # noqa: E402  (r3 g3) the hint sent, journaled
from planner_floors import forget_sent as floor_forget_sent  # noqa: E402  (r3 V4)
from planner_meetings import meeting_open_due, meeting_open_said, meeting_reopen_wait  # noqa: E402  (0.105.47) meetings opened unattended
from planner_meetings import meeting_entry, meeting_report_lines  # noqa: E402  (r5 p2) meetings journaled
from planner_threats import note_intrusions  # noqa: E402  (0.105.30 live fixes)
from planner_holdfast import note_thief_targets  # noqa: E402  (0.105.47, R2 item 7)
import planner_stuck  # noqa: E402  (0.105.45) the stuck sweep's soak summary
import seen as seen_ledger  # noqa: E402  (0.105.46, I1) each full report's sections tallied
import atlas  # noqa: E402
import backup  # noqa: E402
import fort_run as runid  # noqa: E402  (0.105.48, K8) the run id (overseer.fort_run is the preset stamp)
import fallen  # noqa: E402  (r1g9) a fallen fort: marked once, the AI and the keeper idle
import health_check  # noqa: E402
import ledger  # noqa: E402
import season as season_mod  # noqa: E402
import calibrate  # noqa: E402
import chronicle  # noqa: E402
import defence  # noqa: E402
import crisis
import rests  # noqa: E402  (r5 p2) a ghost laid to rest is no death
import learning  # noqa: E402
import masterplan  # noqa: E402
import leanings  # noqa: E402
import temperament  # noqa: E402
import memstore  # noqa: E402
import outcomes  # noqa: E402
import phases  # noqa: E402
import report  # noqa: E402
import timeline  # noqa: E402
from culture import explain, new_history, pick_stone, profile_from, style_guide, update_eras  # noqa: E402
from quirks import describe as describe_quirks  # noqa: E402
from quirks import update as update_quirks  # noqa: E402
from weights import choose_all  # noqa: E402
from culture import note_events as culture_events  # noqa: E402
from digest import _d, _l, normalize, project_text  # noqa: E402
from review import SHADOW_WORDS, hold_review_proposals, maybe_review, note_events, shadow_on  # noqa: E402
from storyteller import maybe_tell  # noqa: E402
from tokens import TokenBank  # noqa: E402
import perf  # noqa: E402  (0.105.40)

# (r7 d1) the main loop's timings (POLL_SECONDS, UNPAUSE_AFTER_S, TRADE_*, MEETING_*, STALL_AFTER_S,
# PLAN_EVERY_TICKS, ...) moved with it to overseer_loop.py; this module re-exports them
FPS_FLOOR = 20                  # below this (the median), newcomers and new luxury levels wait
FPS_CLEAR = 28                   # ... until it's back above this (under a 30 FPS cap too)
SOAK_MAX_BYTES = 10_000_000    # (then soak.old.jsonl: ~ten weeks of rows each)
SOAK = LOG_DIR / "soak.jsonl"    # (unattended) one row every SOAK_EVERY_S of real time: brain/soak_report.py
LAST_CYCLE: dict = {}            # the last cycle's numbers, for the soak row


def meeting_leave_after(cant_answer: bool) -> float:
    """(0.105.24) How long DF's meeting screen may hold an unattended game
    before the overseer leaves it: 10 minutes for a player to answer, or 2
    when the AI's own answer came back "no button known" or a press changed
    nothing (either way nobody will answer it). Leaving ends the meeting
    without an agreement, as the 10-minute leave always did."""
    return MEETING_GIVEUP_S if cant_answer else MEETING_CLOSE_S


WORLD_CLOSE_S = 360.0            # (0.105.48, K9, unattended) DF's World screen open this long is left


def world_leave_due(status: dict, open_since, tried_at, now: float, unattended: bool, autopilot: bool,
                    halted: bool, held_pin, stopped: bool) -> bool:
    """(0.105.48, K9) The World screen's backstop, as the trade and meeting
    screens have theirs: open WORLD_CLOSE_S (longer than the mission
    sender's own stale time, 5 minutes) in an unattended run with nobody to
    close it (the date stands still, so no cycle and no new send comes to
    shut it), it is left; tried again every WORLD_CLOSE_S."""
    st = status or {}
    if not (unattended and autopilot and st.get("in_fort") and st.get("world_open")):
        return False
    if halted or held_pin or stopped or open_since is None:
        return False
    return now - open_since >= WORLD_CLOSE_S and now - tried_at >= WORLD_CLOSE_S


HEARTBEAT = LOG_DIR / "heartbeat"   # touched every loop: brain/keeper.py restarts a stuck overseer
SLOW_PLAN_FACTOR = 2             # (0.104.0) the full report this many times further apart while FPS is low
                                 # (0.105.40: PLANNER_CONFIG perf_slow_cycle_factor, never while a threat is on)
PERF_METER = perf.Meter()        # (0.105.40, 13e) the AI's ms per game day, per fort (logs/forts/<fort>/perf.jsonl)
PERF_LAST: dict = {}             # the last cycle's: threat (the back-off's exemption), ai_ms_day, perf_slow (soak row)
STOP_FILE = PROJECT_ROOT / "STOP"
JOURNAL: Path | None = None     # None: each fort's own journal (memstore.journal_path)
# announcement topics too routine to print (still recorded and used)
QUIET_TOPICS = {"birth", "dig_cancelled", "caravan", "migrants"}


ADJUST_LASTS_TICKS = 100_800     # (0.97.1, B7) a strategist adjustment lasts a season unless renewed


def expire_adjustments(memory, state: dict) -> list:
    """The strategist's planner adjustments last a season from when it set
    them (they used to last for ever, and stopped that target's self-tuning
    for good). One with no date (from before 0.97.1) starts its season now."""
    now = abs_tick(state)
    at = memory.adjust_at if isinstance(memory.adjust_at, dict) else {}
    memory.adjust_at = at
    gone = []
    for k in list(memory.adjust):
        t = at.get(k)
        if not isinstance(t, int) or t > now:
            at[k] = now
        elif now - t >= ADJUST_LASTS_TICKS:
            del memory.adjust[k]
            at.pop(k, None)
            gone.append(k)
    for k in [k for k in at if k not in memory.adjust]:
        del at[k]
    return gone


def fort_key(state: dict) -> str | None:
    """Which fort this is, or None if the report can't say (then we don't act:
    acting with the wrong fort's memory would be worse than waiting)."""
    f = state.get("fort")
    if not isinstance(f, dict) or "error" in f or not f.get("save_dir") or f.get("site_id") is None:
        return None
    # (r1g9) the world and the site ("Usnuspbuzong#1430"), never the save
    # folder's name: DF's seasonal autosave rotates it (autosave 1, 2, 3), and
    # each new name was a new fort to the overseer (its memory read again, a
    # new run id, the run check's game time counted three times over). The
    # logs folder is still chosen by the save folder (memstore.note_world's
    # save_dir). Without a world name, the save folder as before.
    world = f.get("world")
    head = world.strip() if isinstance(world, str) and world.strip() else f["save_dir"]
    # (0.105.0) a scenario copy (marked with a run id in the save) logs apart
    # from the real fort: "<world>@<run id>#<site>" (the site stays last)
    run = f.get("run_id")
    if isinstance(run, str) and run:
        return f"{head}@{run}#{f['site_id']}"
    return f"{head}#{f['site_id']}"


MEMORY_CACHE: dict = {}       # fort -> {"memory", "bank", "tick", "prefer_logs", "folder"}: what the last cycle used


def _folder_of(key: str) -> str | None:
    """(r1g9) The logs folder of the fort key now (memstore.note_world's alias)."""
    try:
        return str(memstore.fort_dir(key))
    except Exception:  # noqa: BLE001
        return None
MEMORY_REREAD_GAP = 30 * 1200 # game time jumping further ahead than this (another save?): read it again


def load(key: str, bridge=None, prefer_logs: bool = False, state: dict | None = None) -> tuple[Memory, TokenBank]:
    """The memory stored in the loaded save comes first: it matches the game
    exactly, even after reloading an older save. The copy in logs/ is the
    fallback (first run, or a save made before this existed); a dry run
    carries on from it. See memstore.py.

    Reading it from the save froze the game ~3.5 s every cycle (Oct 23, the
    largest share of the keeper's lag), so it is read once and then kept
    here while the game's clock runs on; a clock that went back (an older
    save reloaded) or jumped far ahead reads the save again."""
    d = state.get("date") if state else None
    # (0.105.26) a date that failed in the game ({"error": ...}) is no clock: read the save, cache nothing
    now = (abs_tick(state) if isinstance(d, dict) and isinstance(d.get("year"), int)
           and isinstance(d.get("tick"), int) else None)
    c = MEMORY_CACHE.get(key)
    folder = _folder_of(key)
    if (THROTTLE_MEMORY_SAVE and c is not None and now is not None and c["prefer_logs"] == prefer_logs
            and c.get("folder") == folder      # (r1g9) another save's folder (a test copy) is another fort's
            and 0 <= now - c["tick"] <= MEMORY_REREAD_GAP):
        c["tick"] = now
        return c["memory"], c["bank"]
    memory, bank = memstore.load(key, bridge, prefer_logs)
    if state is not None:
        # (0.105.48, K8) this fort's run (brain/fort_run.py): another run's logs
        # copy set aside; a save holding no run id gets one (written with the ledger)
        try:
            memory, bank = runid.settle(memory, bank, state, say)
        except Exception as e:  # noqa: BLE001  (the run id never stops the fort)
            say(f"Run: couldn't settle this fort's run id ({type(e).__name__}: {str(e)[:100]})")
    seed_squads_made(memory, key)
    # (0.104.0) what the AI must not forget, as saved with this very game
    if state is not None and ledger.apply(memory, state.get("ledger")):
        say("Ledger: the alert, gate, memorials, petitions and the like read back as saved with the game")
    # (0.104.45) not kept when the save couldn't be read: one timeout at 08:36
    # was kept for good, so nothing reached the save for the rest of the night
    if now is not None and not (getattr(memory, "_texts", None) or {}).get("save_unread"):
        MEMORY_CACHE[key] = {"memory": memory, "bank": bank, "tick": now, "prefer_logs": prefer_logs,
                             "folder": folder}
    else:
        MEMORY_CACHE.pop(key, None)
    return memory, bank


# (0.105.40, Phase 13e) The cycle's bookkeeping actions (report_status,
# ledger_set, set_learned, set_culture) are held and go to the game in one
# `batch` call with the next action or the memory's save_memory (Bridge.defer):
# each dfhack-run call costs ~35 ms before it does anything. Each one's answer
# is handled as before, by its own callback, in the order they were made.
HELD_BEFORE_SAVE = {"set_learned", "set_culture"}   # their answers are written into the memory


def defer_act(bridge, action: dict, on_result) -> None:
    """Send `action` with the next call (a bridge with defer()), else now;
    on_result(reply, error) gets the answer (error: the BridgeError or
    DFHackError act() would raise)."""
    d = getattr(bridge, "defer", None)
    if callable(d) and isinstance(getattr(bridge, "pending", None), list):
        d(action, on_result)
        return
    try:
        r = bridge.act(action)
    except (BridgeError, DFHackError) as e:
        on_result(None, e)
        return
    on_result(r, None)


def flush_held(bridge, only: set | None = None) -> None:
    """Send what defer_act held (only when one of `only` is among it, if given).
    Never raises."""
    held = getattr(bridge, "pending", None)
    if not isinstance(held, list) or not held:
        return
    if only and not any(isinstance(a, dict) and a.get("type") in only for a, _ in held):
        return
    try:
        bridge.flush()
    except Exception:  # noqa: BLE001  (each held action's own answer says what happened)
        pass


def write_ledger(bridge, state: dict, memory: Memory, defer: bool = False) -> None:
    """(0.104.0) The ledger into the save when it differs from the one the
    game holds (a bridge from before 0.104.0 has none: nothing written).
    (0.105.40) defer: sent with the cycle's next call (the end of the cycle)."""
    held = state.get("ledger") if isinstance(state, dict) else None
    if not isinstance(held, dict) or "error" in held:
        return
    snap = ledger.snapshot(memory)
    if ledger.same(snap, held):
        return

    def done(r, err):
        if err is not None:
            say(f"Ledger: not saved with the game ({err})")
        elif r.get("ok"):
            state["ledger"] = snap                 # (the next cycle's report will say so too)
        else:
            say(f"Ledger: not saved with the game ({r.get('error')})")

    action = {"type": "ledger_set", "values": snap}
    if defer:
        defer_act(bridge, action, done)
        return
    try:
        r = bridge.act(action)
    except (BridgeError, DFHackError) as e:
        done(None, e)
        return
    done(r, None)


def seed_squads_made(memory: Memory, key: str) -> None:
    """Squads the AI made before 0.82 (when memory.squads_made began) are
    read once from the fort's journal: each make_squad that answered with
    a squad id. Never raises."""
    if getattr(memory, "squads_made", None):
        return
    found: list = []
    try:
        base = memstore.journal_path(key)
        for path in [base.with_name(base.stem + ".1" + base.suffix), base]:
            if not path.exists():
                continue
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"make_squad"' not in line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    r = _d(e.get("result"))
                    if (e.get("action") or {}).get("type") == "make_squad" and r.get("ok") is True \
                            and isinstance(r.get("squad_id"), int) and r["squad_id"] not in found:
                        found.append(r["squad_id"])
    except Exception:  # noqa: BLE001
        return
    if found:
        memory.squads_made = found


MEMORY_SAVE_EVERY_TICKS = 7 * 1200     # the AI's memory into the game's save: once a game week...
SEASON_TICKS = 84 * 1200
SEASON_END_TICKS = 3 * 1200            # ...and every day in the last 3 days of a season (DF autosaves then)
LAST_MEMORY_SAVE: dict = {}            # fort -> abs tick of the last write into the game's save
THROTTLE_MEMORY_SAVE = True            # (the tests switch it off to see every write)
MEMORY_KINDS_PER_CALL = 1              # kinds of memory written into the save per cycle
MEMORY_SAVE_LEFT: dict = {}            # fort -> kinds still to write


def memory_save_due(key: str, state: dict | None) -> bool:
    """Writing the memory into the game's save froze the game about a second
    every cycle (Oct 23: 254 writes, 1.0 s each, the largest share of the
    keeper's lag). The logs copy is still written every cycle."""
    if not THROTTLE_MEMORY_SAVE or not state or not isinstance(state.get("date"), dict):
        return True
    now = abs_tick(state)
    last = LAST_MEMORY_SAVE.get(key)
    tick = int(state["date"].get("tick") or 0)
    if last is None or now < last or now - last >= MEMORY_SAVE_EVERY_TICKS:
        return True
    return tick % SEASON_TICKS >= SEASON_TICKS - SEASON_END_TICKS


def save(key: str, memory: Memory, bank: TokenBank, bridge=None, state: dict | None = None) -> None:
    """Always to logs/; also into the game's save when a bridge is given and
    it's due (memory_save_due). Only the kinds of memory that changed are written."""
    if bridge is not None and not memory_save_due(key, state) and not MEMORY_SAVE_LEFT.get(key):
        bridge = None
    out = memstore.save(key, memory, bank, bridge, limit=MEMORY_KINDS_PER_CALL if THROTTLE_MEMORY_SAVE else None)
    if (out or {}).get("error"):
        say(f"Memory: {out['error']}")          # (0.100) said, not raised out of the cycle's cleanup
    if bridge is not None:
        # the kinds left over go one or two a cycle until all are in
        MEMORY_SAVE_LEFT[key] = (out or {}).get("save_left", 0)
        if not MEMORY_SAVE_LEFT[key] and state and isinstance(state.get("date"), dict):
            LAST_MEMORY_SAVE[key] = abs_tick(state)


LAST_FORT: dict = {}     # (r5 p2) the fort and date of the last cycle: the main loop's meeting lines go to its journal


def journal_meeting(action: str, r, held_s=None) -> None:
    """(r5 p2, A3 B2) A meeting action from the main loop as a journal line of
    its own (planner_meetings.meeting_entry); never raises."""
    try:
        e = meeting_entry(action, r, held_s)
        if e is not None:
            journal({"kind": "meeting", "fort": LAST_FORT.get("key"), "date": LAST_FORT.get("date"), **e})
    except Exception:  # noqa: BLE001 - a log line never stops the loop
        pass


def journal(entry: dict) -> None:
    """Decisions and events go to the fort's own journal (logs/forts/<fort>/,
    rotated by size). JOURNAL, when set, takes everything instead (scenario
    runs and tests)."""
    entry = {"time": datetime.now().isoformat(timespec="seconds"), **entry}
    path = JOURNAL if JOURNAL is not None else memstore.journal_path(entry.get("fort"))
    memstore.append_journal(path, entry)


def say(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)
    heartbeat()                  # (a long cycle that still prints isn't stuck)


def date_str(state: dict) -> str:
    d = state["date"]
    return f"{d['day']} {d['month']} y{d['year']}"


from overseer_words import *  # noqa: E402,F401,F403  (r7 d1) MODES, BIG_MOVES, DECLINE_DAYS, ... moved there
from overseer_words import _CAMERA_LEVELS, _victim_mood  # noqa: E402,F401  (* skips these)


STATES_KEPT = 80          # (0.100.1) every season of a long run (~60 KB each)


from util import state_run  # noqa: E402  (r6 c2) was a copy here


def _season_order(stem: str):
    y, _, sn = stem.partition("-")
    try:
        return int(y), report.SEASONS.index(sn)
    except ValueError:
        return None


def later_seasons(d: Path, name: str, run: str | None) -> list:
    """(0.105.47) The kept season states of this run later than `name`
    ("257-summer.json"): there are some only when the game went back."""
    me = _season_order(Path(name).stem)
    if me is None:
        return []
    out = []
    for p in d.glob("*.json"):
        o = _season_order(p.stem)
        if o is not None and o > me and (run is None or state_run(p) == run):
            out.append(p)
    return out


def set_aside(d: Path, files: list) -> None:
    """(0.105.47) Season states of a dropped line moved to states/dropped/
    (kept for a look, out of the scorecard's way; an older copy replaced)."""
    to = d / "dropped"
    to.mkdir(parents=True, exist_ok=True)
    for p in files:
        try:
            p.replace(to / p.name)
        except OSError:
            pass


def keep_state(state: dict, key: str) -> None:
    """One full report per in-game season in logs/forts/<fort>/states/: real
    game states for the tests (the fake forts in the tests hold only what we
    believed the game looks like). The newest STATES_KEPT are kept."""
    try:
        d = memstore.fort_dir(key) / "states"
        name = report.season_key(state).replace(" ", "-") + ".json"
        path = d / name
        # (0.105.26) a fresh start from the same save (14.1 step 5: six forts
        # restarted from region4) finds the old run's files under the same
        # names: one from an older run (another "_run", or none) is replaced
        run = fort_run(key, world_of(state))     # (r9) by the world too
        if path.exists() and (run is None or state_run(path) == run):
            # (0.105.47) the same run gone back to an earlier save (the
            # keeper's restore, a reload): kept seasons later than this one
            # belong to the line that was dropped. A (8-13 Nov) was restored
            # to its start at 258 spring and replayed to 258 spring, building
            # its gatehouse and wings (18 walls); every season file stayed the
            # dropped line's, and the scorecard read its 0 walls. Those later
            # files are set aside (states/dropped/) and this one replaced.
            later = later_seasons(d, name, run)
            if not later:
                return
            set_aside(d, later)
        d.mkdir(parents=True, exist_ok=True)
        body = {"_run": run} if run else {}         # first, so a reader finds it in the first bytes
        body.update((k, v) for k, v in state.items() if k not in ("_errors", "_run"))
        path.write_text(json.dumps(body), encoding="utf-8")
        files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime)
        for old in files[:-STATES_KEPT]:
            old.unlink(missing_ok=True)
    except (OSError, TypeError, ValueError):
        pass


STATUS_SENT: dict = {}      # (13c) the panel's last report: {"bridge", "payload", "at"}
STATUS_REFRESH_S = 300      # the same report again after this long (a reloaded game forgot it)


def report_status(bridge: Bridge, payload: dict) -> None:
    """Tell the on-screen panel what's going on (display only; never fails the
    cycle). (13c) Not sent again when it says what the last one said, unless
    that was STATUS_REFRESH_S ago (the panel forgets it when a map unloads)."""
    if (STATUS_SENT.get("bridge") is bridge and STATUS_SENT.get("payload") == payload
            and time.monotonic() - STATUS_SENT.get("at", 0.0) < STATUS_REFRESH_S):
        return
    def done(r, err):
        if err is not None:
            STATUS_SENT.clear()
        else:
            STATUS_SENT.update(bridge=bridge, payload=payload, at=time.monotonic())

    # (0.105.40) held: it goes with the cycle's next call (Bridge.defer)
    defer_act(bridge, {"type": "report_status", "status": payload}, done)


# The last full (daily) report, so a cycle in between (after an event, or
# your answer in the game) can ask for the small pulse report and fill in the
# rest from it.
LAST_FULL: dict = {}


def get_state(bridge: Bridge, tier: str = "daily") -> dict:
    """The fort report. A pulse is the small report (date, threats, stocks,
    orders, projects, gates, moods, military, settings) merged over the last
    full one when that is under a day old; otherwise, or if the bridge can't,
    the full report."""
    if tier == "pulse" and LAST_FULL.get("state"):
        try:
            pulse = bridge.state(include_units=False, tier="pulse")
        except (TypeError, BridgeError):
            pulse = None                    # an older bridge (or a fake one): the full report
        full = LAST_FULL["state"]
        if (isinstance(pulse, dict) and pulse.get("tier") == "pulse" and pulse.get("fort") == full.get("fort")
                and isinstance(pulse.get("date"), dict) and isinstance(full.get("date"), dict)):
            d0, d1 = full["date"], pulse["date"]
            t0, t1 = d0.get("tick") or 0, d1.get("tick") or 0
            # under a day old (a new year always gets a full report)
            fresh = d1.get("year") == d0.get("year") and 0 <= t1 - t0 < PLAN_EVERY_TICKS
            if fresh:
                merged = json.loads(json.dumps(full))
                merged.update(pulse)
                merged.pop("_errors", None)     # worked out again from this report
                return merged
        if isinstance(pulse, dict) and pulse.get("tier") is None and isinstance(pulse.get("date"), dict):
            # a bridge from before 0.31 ignores --tier and sends the full report: use it
            LAST_FULL["state"] = json.loads(json.dumps({k: v for k, v in pulse.items() if k != "_errors"}))
            return pulse
    state = bridge.state(include_units=False)
    if state.get("tier") in (None, "daily", "survey"):
        LAST_FULL["state"] = json.loads(json.dumps({k: v for k, v in state.items() if k != "_errors"}))
    return state


# What this run has already printed under each cycle (needs you, notes, held),
# per fort. Kept only while the overseer runs: after a restart you see it all once.
PRINTED: dict[str, set] = {}
WARNED: set = set()


def _shape(line: str) -> str:
    """A line with its numbers taken out: a countdown ("for 3 more days") or a
    count that ticks along is the same line as before."""
    return re.sub(r"\d+", "#", line)


def show_changed(key: str, lines: list[str]) -> None:
    """Print the lines that are new since the last cycle; the rest in one line.
    Lines that differ only in their numbers count as the same."""
    before = PRINTED.get(key, set())
    lines = list(dict.fromkeys(lines))
    shapes = {_shape(ln) for ln in lines}
    new = [ln for ln in lines if _shape(ln) not in before]
    for ln in new:
        say(ln)
    same = len(lines) - len(new)
    if same:
        say(f"  ({same} line{'s' if same != 1 else ''} as before: needs you, notes, held)")
    gone = len(before - shapes)
    if gone:
        say(f"  ({gone} earlier line{'s no longer apply' if gone != 1 else ' no longer applies'})")
    PRINTED[key] = shapes


def _log_error() -> None:
    """The traceback of the exception being handled, into logs/overseer-errors.log (never raises)."""
    try:
        LOG_DIR.mkdir(exist_ok=True)
        memstore.cap_file(LOG_DIR / "overseer-errors.log", ERRORS_MAX_BYTES)
        with (LOG_DIR / "overseer-errors.log").open("a", encoding="utf-8") as f:
            f.write(f"--- {datetime.now().isoformat(timespec='seconds')}\n{traceback.format_exc()}\n")
    except Exception:  # noqa: BLE001
        pass


FAILED_CYCLES_KEY = "_overseer"     # (0.105.48, K6) the standing lines' key for whole cycles that failed


def note_failed_cycles(n: int, e: BaseException | None) -> None:
    """(0.105.48, K6) Whole cycles failing in a row, as a standing "rule cycle
    failed" line (logs/standing.json: the health check flags it once it stands
    long); n=0 clears it. Never raises."""
    try:
        notes = ([f"rule cycle failed ({type(e).__name__}: {str(e)[:120]}): nothing planned "
                  f"({n} cycle(s) in a row)"] if n and e is not None else [])
        health_check.track_standing(FAILED_CYCLES_KEY, [], notes, None)
    except Exception:  # noqa: BLE001
        pass


from overseer_cycle import *  # noqa: E402,F401,F403  (r7 d1) cycle_step, _calibrate_step, _outcomes_step, ... moved there
from overseer_cycle import _calibrate_step, _outcomes_step  # noqa: E402,F401  (* skips these)
sys.modules["overseer_cycle"]._ov = sys.modules[__name__]   # its call-time lookups (also as __main__)


from overseer_world import *  # noqa: E402,F401,F403  (r7 d1) STYLE_AREAS, _style_choices, _note_adjust, ... moved there
from overseer_world import _style_choices, _note_adjust, _newest_season  # noqa: E402,F401  (* skips these)
sys.modules["overseer_world"]._ov = sys.modules[__name__]   # its call-time lookups (also as __main__)


def make_backend():
    from backends import BackendUnavailable, get_backend
    try:
        b = get_backend()
    except BackendUnavailable as e:
        say(f"AI strategist not available ({e}). Running the local planner only; "
            "see docs/ai-setup.md, then run python brain/check_ai.py.")
        return None
    say(f"AI strategist connected via {'API key' if b.name == 'api' else 'your Claude subscription'}.")
    return b


def note_perf(state: dict, key: str) -> None:
    """(0.105.40, 13e) The cycle's perf: whether a threat is on (the slow
    back-off's exemption) and the AI's ms per game day (the bridge's summed
    call time over the game days passed: brain/perf.py). Never raises."""
    try:
        PERF_LAST["threat"] = perf.threat_active(state)
        import bridge as _bridge
        cm = _bridge.CALL_MS
        row = PERF_METER.note(key, abs_tick(state), cm["ms"], cm["calls"], state.get("perf"),
                              memstore.fort_dir(key), state=state)   # (R29 W7) the population and the tier
        if row is not None:
            PERF_LAST["ai_ms_day"] = row.get("ms_per_day")
        slow = perf.slow_sections(state.get("perf"))
        if slow:
            PERF_LAST["perf_slow"] = {k: v for k, v in slow}
    except Exception:  # noqa: BLE001  (a measure never stops the fort)
        pass


def slow_factor(fps_low, unattended: bool) -> int:
    """(0.105.40) How many times further apart the full report comes: the
    config's perf_slow_cycle_factor while the game runs slowly (unattended),
    1 otherwise and while the last report showed a threat or a siege."""
    return perf.cycle_factor(bool(fps_low and unattended), bool(PERF_LAST.get("threat")),
                             PLANNER_CONFIG.get("perf_slow_cycle_factor", SLOW_PLAN_FACTOR))


def write_soak(st: dict, fps_samples: list, fps_low, unpauses: int, still_s: int, halted: bool) -> None:
    """(unattended) One row of how the run is going, every 10 real minutes, for
    a look over a whole night (brain/soak_report.py). Never raises."""
    try:
        fps = sorted(f for _, f in fps_samples)
        d = st.get("date") or {}
        row = {"time": datetime.now().isoformat(timespec="seconds"), "in_fort": bool(st.get("in_fort")),
               "paused": st.get("paused"), "halted": halted, "trade_open": st.get("trade_open"),
               "date": f"{d.get('day')} {d.get('month')} y{d.get('year')}" if d else None,
               "year": d.get("year"), "tick": d.get("tick"),
               "fps": fps[len(fps) // 2] if fps else None, "fps_min": fps[0] if fps else None,
               "fps_low": bool(fps_low), "unpauses": unpauses, "time_still_s": still_s,
               "stop_file": STOP_FILE.exists(), **LAST_CYCLE,
               **{k: PERF_LAST[k] for k in ("ai_ms_day", "perf_slow") if k in PERF_LAST}}
        LOG_DIR.mkdir(exist_ok=True)
        memstore.cap_file(SOAK, SOAK_MAX_BYTES)
        with SOAK.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


GEAR_PROBE_EVERY_TICKS = 28 * 1200
LAST_GEAR_PROBE: dict = {}


def probe_gear(bridge, state: dict, key: str) -> None:
    """Soldiers short of weapons or armour while spares lie about: once a game
    month, the military probe (what each uniform asks for, what the game
    assigned and where it lies, what they carry) to logs/probe-squads.json,
    so the cause can be read without running the self-test. Never raises."""
    try:
        g = _d(_d(state.get("military")).get("gear"))
        # (0.105.33) armed/helmed count soldiers on duty only (lua/ai-military-gear.lua):
        # against them, not every soldier (one off duty made it "short" each month)
        soldiers = int(g.get("on_duty") if g.get("on_duty") is not None else g.get("soldiers") or 0)
        short = soldiers and (int(g.get("armed") or 0) < soldiers or int(g.get("helmed") or 0) < soldiers)
        now = abs_tick(state)
        last = LAST_GEAR_PROBE.get(key)
        if not short or (last is not None and 0 <= now - last < GEAR_PROBE_EVERY_TICKS):
            return
        LAST_GEAR_PROBE[key] = now
        r = bridge._call("probe_squads")
        LOG_DIR.mkdir(exist_ok=True)
        (LOG_DIR / "probe-squads.json").write_text(
            json.dumps({"date": state.get("date"), "gear": g, "probe": r}, indent=1, ensure_ascii=False),
            encoding="utf-8")
    except Exception as e:  # noqa: BLE001  (a probe never stops the fort; but say why it failed)
        try:
            LOG_DIR.mkdir(exist_ok=True)
            (LOG_DIR / "probe-squads.json").write_text(
                json.dumps({"date": state.get("date"), "error": f"{type(e).__name__}: {e}"}), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


LAST_POSTS: dict = {}


def probe_posts(bridge, state: dict, key: str) -> None:
    """(0.84) The occupation probe (what the game writes for a post at a
    location: a hospital's doctor, a library's scribe) to
    logs/probe-occupations.json whenever the number of posts at the fort's
    locations changes (and at the first daily report), so the records the
    game makes when you assign one by hand can be read and copied. Never raises."""
    try:
        lst = _d(state.get("locations")).get("list")
        if not isinstance(lst, list):
            return
        n = sum(int(_d(j).get("posts") or 0) for e in lst if isinstance(e, dict)
                for j in _d(e.get("jobs")).values())
        if LAST_POSTS.get(key) == n:
            return
        LAST_POSTS[key] = n
        r = bridge._call("probe_occupations")
        LOG_DIR.mkdir(exist_ok=True)
        (LOG_DIR / "probe-occupations.json").write_text(
            json.dumps({"date": state.get("date"), "posts": n, "probe": r}, indent=1, ensure_ascii=False),
            encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        try:
            (LOG_DIR / "probe-occupations.json").write_text(
                json.dumps({"date": state.get("date"), "error": f"{type(e).__name__}: {e}"}), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


# (0.105.33) the pin as one_cycle last found it for the loaded fort (reset when
# no fort is loaded): the main loop's unattended actions (quiet announcements,
# meetings, unpausing, popups, the trade screen) wait for it
PIN_SEEN: dict = {"checked": False, "refused": None}


def pin_hold() -> bool:
    """(0.105.33) Under the keeper (DFAI_PIN): True while the loaded fort
    isn't known to be the pinned one (not yet checked by a cycle, or refused),
    so the main loop runs nothing unattended on another fort."""
    if not os.environ.get("DFAI_PIN"):
        return False
    return not PIN_SEEN.get("checked") or bool(PIN_SEEN.get("refused"))


PIN_RETRY_S = 60.0     # (0.105.33 fix) a pin check that couldn't tell waits this long before the next


def check_pin(bridge) -> None:
    """(0.105.33) The main loop, a fort just loaded under the keeper: the pin
    checked from the small report (one_cycle only runs once the game runs,
    and the loop's unpause waits for this). Left unchecked if it can't tell;
    (0.105.33 fix) then tried again only after PIN_RETRY_S, not every poll."""
    nowm = time.monotonic()
    if nowm - PIN_SEEN.get("failed_at", float("-inf")) < PIN_RETRY_S:
        return
    try:
        import pin
        f = _d(_d(bridge.state(include_units=False, tier="pulse")).get("fort"))
        if not f.get("world") or f.get("site_id") is None:
            PIN_SEEN["failed_at"] = nowm
            return
        refused = pin.refusal(f.get("world"), f.get("site_id"),
                              df_path=_d(getattr(bridge, "version", None)).get("df_path"))   # (K17)
    except (BridgeError, DFHackError, TypeError, ValueError, ImportError):
        PIN_SEEN["failed_at"] = nowm
        return
    PIN_SEEN.pop("failed_at", None)
    PIN_SEEN["checked"], PIN_SEEN["refused"] = True, refused
    if refused and refused not in WARNED:
        WARNED.add(refused)
        say(refused)


def meeting_unattended(args) -> bool:
    """(0.105.0 review) Nobody at the game: --unattended, or run by the keeper
    (brain/keeper.py sets DFAI_PIN for the overseer it starts)."""
    return bool(getattr(args, "unattended", False) or os.environ.get("DFAI_PIN"))


UNATTENDED = False      # (0.104.88) set from --unattended: the in-game camera director runs only then
PRESET: str | None = None   # (0.105.4) --preset NAME (keeper.py --preset): applied once per fort
PRESET_FILE = LOG_DIR / "keeper-preset.json"   # {fort key: {"name", "at"}}: what --preset applied, per fort
PRESET_DONE: set = set()    # fort keys seen this process (asked once per fort, not every cycle)


def acknowledged(decisions: dict, looked: set, memory, now: int) -> list[str]:
    """(0.105.33) The in-game answers the panel may forget: those read this
    cycle, and every "no" (a "no" to a proposal not made this cycle goes
    straight into memory.declined, so it isn't asked again)."""
    out = []
    for pid, ans in decisions.items():
        if pid in looked:
            out.append(pid)
        elif ans == "no":
            memory.declined.setdefault(pid, now)
            out.append(pid)
    return out


def preset_due(key: str, name: str, fort_preset, world: str | None = None) -> str | None:
    """(0.105.4) Why --preset NAME should be applied to this fort now, or None.
    Applied when this fort never had NAME from --preset (logs/keeper-preset.json),
    or when the fort's site data shows no preset at all (an older save, from
    before it was applied). Never over the player's own later choice: once
    applied, a revive or a restart leaves the window's changes alone."""
    # (0.105.33) by the site, as fort_run: the same fort read from another
    # folder ("autosave 2#7" after a revive, "region1#7" before) had no record
    # of its own, and the preset went on again over the player's later choice
    recs = [r for k, r in load_json(PRESET_FILE, {}).items() if _same_fort(k, r, key, world)]
    if not any(r.get("name") == name for r in recs):
        return "first time for this fort" if fort_preset != name else None
    if not fort_preset:
        return "the save shows no preset"
    return None


from util import site_of as _site  # noqa: E402  (r6 c2) was a copy here


def world_of(state: dict) -> str | None:
    """(r9) The report's world name (fort.world), or None when it can't say."""
    w = _d(_d(state).get("fort")).get("world")
    return w.strip() if isinstance(w, str) and w.strip() else None


def _same_fort(k: str, rec, key: str, world: str | None = None) -> bool:
    """(r9) Whether logs/keeper-preset.json's entry k (rec) is fort `key`'s:
    the same site, and the same world when both the entry (note_preset
    writes it now) and the caller (the report's world) name one. The site
    alone matched another world's fort with the same site id (a new world
    played in the same folder): its preset read as applied, its run and its
    Design switch taken over. An older entry (no "world"; its key may be a
    save folder's, "region1#7"), or a report without a world name, matches
    by site as before. The world comes from the report, never from the key:
    a key's head is a save folder's name when the report had no world."""
    if not isinstance(rec, dict) or _site(k) != _site(key):
        return False
    w = rec.get("world")
    return world is None or not isinstance(w, str) or w == world


def fort_run(key: str, world: str | None = None) -> str | None:
    """(0.105.26) This fort's run: the "run" stamp of its site's entries in
    logs/keeper-preset.json (the newest), or None (no preset, or an entry from
    before runs were marked). Clearing the site's entries (the fresh-restart
    checklist) starts a new run when the preset is applied again."""
    runs = [r["run"] for k, r in load_json(PRESET_FILE, {}).items()
            if _same_fort(k, r, key, world) and isinstance(r.get("run"), str)]
    return max(runs) if runs else None


def note_preset(key: str, name: str, design: str | None = None, world: str | None = None) -> None:
    done = load_json(PRESET_FILE, {})
    now = datetime.now().isoformat(timespec="seconds")
    # (0.105.26) the run stamp is set once, when the site has no entry at all
    # (a new fort, or one cleared for a fresh start); a restart, a revive or an
    # autosave's key keeps the site's stamp; an older entry without one stays so
    same = [r for k, r in done.items() if _same_fort(k, r, key, world)]
    runs = [r["run"] for r in same if isinstance(r.get("run"), str)]
    run = max(runs) if runs else (None if same else now)
    # (0.105.47, D1) the Design switch the keeper made for this site (design_due) is kept
    design = design or next((r["design"] for r in same if isinstance(r.get("design"), str)), None)
    # (r9) the world kept on the entry, when the report named it: _same_fort tells
    # another world's fort with the same site id apart
    done[key] = {"name": name, "at": now, **({"world": world} if world else {}), **({"run": run} if run else {}),
                 **({"design": design} if design else {})}
    try:
        from dfhack import write_atomic
        PRESET_FILE.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(PRESET_FILE, json.dumps(done, indent=1))
    except OSError:
        pass


def _onoff(v) -> str:
    """(0.105.36, D7) a Rules value in words: on/off for a switch, the word itself for a three-state one."""
    return ("on" if v else "off") if isinstance(v, bool) or v is None else str(v)


RULES_REQUEST = "rules-request.json"     # (0.105.20) in the logs folder: {"rules": {"open_caverns": true}}


def rules_request(bridge: Bridge, autopilot: bool) -> None:
    """(0.105.20) Rules-tab switches asked for from outside the game (the
    player through Claude: C and F's cavern wells, 3 Nov): logs/
    rules-request.json {"rules": {name: true|false}} is applied to the fort
    this folder runs through the bridge's set_rules, then renamed
    rules-request.done.json with the answer, so it is applied once. A dry
    run only says what it would change."""
    path = LOG_DIR / RULES_REQUEST
    if not path.exists():
        return
    try:
        req = json.loads(path.read_text(encoding="utf-8"))
        rules = req.get("rules") if isinstance(req, dict) else None
        if not isinstance(rules, dict) or not rules:
            raise ValueError("no rules")
    except (OSError, ValueError) as e:
        # (0.105.35) set aside, not left in the way: the next request is read afresh
        # (a dry run moves nothing)
        bad = path.with_name(RULES_REQUEST.replace(".json", ".bad.json"))
        said = "left where it is (a dry run)"
        if autopilot:
            try:
                path.replace(bad)
                said = f"set aside as {bad.name}"
            except OSError:
                said = "left where it is"
        say(f"Rules: {RULES_REQUEST} couldn't be read ({e}); nothing applied, {said}.")
        return
    try:
        r = bridge.act({"type": "set_rules", "rules": rules, "dry_run": not autopilot})
    except (BridgeError, DFHackError) as e:
        say(f"Rules: couldn't set {', '.join(sorted(rules))} ({e}); trying again next cycle.")
        return
    if not autopilot:
        say(f"Rules: would set {rules} (dry run: nothing changed).")
        return
    if r.get("ok"):
        ch = _d(r.get("changed"))
        words = ", ".join(f"{k} {_onoff(_d(v).get('new'))}" for k, v in sorted(ch.items())) or "nothing to change"
        say(f"Rules: set from {RULES_REQUEST}: {words}.")
    else:
        say(f"Rules: {RULES_REQUEST} not applied: {r.get('error')}")
    try:
        done = LOG_DIR / "rules-request.done.json"
        done.write_text(json.dumps({"request": req, "answer": r}, indent=1), encoding="utf-8")
        path.unlink()
    except OSError as e:
        say(f"Rules: applied, but {RULES_REQUEST} couldn't be moved aside ({e}).")


def design_due(key: str, settings: dict, world: str | None = None) -> bool:
    """(0.105.47, D1) Whether the keeper's --preset should take this fort to
    Guided now: its settings read Scripts (every fort founded before the
    Design track does) and the keeper never switched this site before
    (logs/keeper-preset.json's "design"). Once switched, the window's later
    choice stays, Scripts included; a site cleared for a fresh start is
    switched again (the bridge's apply_preset does it then)."""
    if _d(settings).get("design") != "scripts":
        return False
    recs = [r for k, r in load_json(PRESET_FILE, {}).items() if _same_fort(k, r, key, world)]
    return not any(isinstance(r.get("design"), str) for r in recs)


def design_switch(bridge: Bridge, state: dict, key: str, name: str, autopilot: bool) -> None:
    """(0.105.47, D1) A fort the preset was applied to before the Design track
    (the six test forts) is switched to Guided once, through set_rules (the
    Rules' `design` choice). Only its new levels change: what stands is never
    rebuilt (planner_design, planner_guided). A dry run changes nothing."""
    st = _d(state.get("settings"))
    if not design_due(key, st, world_of(state)):
        return
    try:
        r = bridge.act({"type": "set_rules", "rules": {"design": "guided"}, "dry_run": not autopilot})
    except (BridgeError, DFHackError) as e:
        say(f"Design: couldn't switch this fort to Guided ({e}); tried again at the next start.")
        return
    if not autopilot:
        say("Design: this fort would go from Scripts to Guided (dry run: nothing changed).")
        return
    if not r.get("ok"):
        say(f"Design: not switched to Guided: {r.get('error')}")
        return
    note_preset(key, name, "guided", world_of(state))
    say("Design: this fort goes from Scripts to Guided (the keeper's --preset): its new levels follow a design "
        "language; what stands is left as it is.")
    journal({"kind": "design_switch", "fort": key, "from": "scripts", "to": "guided", "preset": name})
    if isinstance(state.get("settings"), dict):
        state["settings"]["design"] = "guided"        # this cycle plans with it


def apply_preset(bridge: Bridge, state: dict, key: str, autopilot: bool) -> None:
    """(0.105.4) --preset NAME: before this fort's first cycle, the preset
    applied to its settings (the bridge's apply_preset, as the window's Load
    preset), when preset_due says so. The cycle then plans with it."""
    name = PRESET
    if not name or key in PRESET_DONE:
        return
    st = _d(state.get("settings"))
    why = preset_due(key, name, st.get("preset"), world_of(state))
    if why is None:
        PRESET_DONE.add(key)
        note_preset(key, name, world=world_of(state))
        say(f"Preset: {name} already applied to this fort (left as it is: later changes in the window stay).")
        design_switch(bridge, state, key, name, autopilot)
        return
    try:
        r = bridge.act({"type": "apply_preset", "name": name, "dry_run": not autopilot})
    except (BridgeError, DFHackError) as e:
        say(f"Preset: couldn't apply {name} ({e}); trying again next cycle.")
        return
    PRESET_DONE.add(key)
    if not r.get("ok"):
        say(f"Preset: {name} not applied: {r.get('error')}")
        return
    traits = _d(r.get("traits"))
    shown = " ".join(f"{k}:{v:+d}" for k, v in sorted(traits.items(), key=lambda kv: -abs(kv[1])) if isinstance(v, int))
    rules = _d(r.get("rules"))
    rule_words = ", ".join(f"{k}={v}" for k, v in sorted(rules.items()) if k != "levels")
    levels = _d(rules.get("levels"))
    if levels:
        rule_words += (", " if rule_words else "") + "levels " + " ".join(
            f"{k}:{'on' if v else 'off'}" for k, v in sorted(levels.items()))
    if not autopilot:
        say(f"Preset: {name} would be applied ({why}; dry run: nothing changed). Traits {shown or 'balanced'}.")
        return
    say(f"Preset: {name} applied ({why}; was {r.get('previous') or 'none'}). Traits {shown or 'balanced'}"
        + (f"; rules {rule_words}" if rule_words else "") + ".")
    # (0.105.47, D1) the bridge's apply_preset took a Scripts fort to Guided: marked
    # for the site, so a later choice in the window stays (design_due)
    note_preset(key, name, _d(r.get("settings")).get("design") if rules.get("design") else None, world_of(state))
    journal({"kind": "preset", "fort": key, "preset": name, "why": why, "previous": r.get("previous"),
             "traits": traits, "rules": rules})
    if isinstance(r.get("settings"), dict):
        state["settings"] = r["settings"]           # this cycle plans with the preset


def heartbeat() -> None:
    try:
        LOG_DIR.mkdir(exist_ok=True)
        HEARTBEAT.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    except OSError:
        pass


backup.on_progress = heartbeat      # (0.104.81) a long save copy keeps the keeper's heartbeat fresh


FPS_PEAK = {"fps": 0}
FPS_FLOOR_SHARE = 0.35           # (0.104.106) ... or this share of the best FPS seen this session,
FPS_CLEAR_SHARE = 0.45           # whichever is higher (a 100 FPS game is held from 35, not 20)


def fps_state(samples: list, low, peak: dict | None = None):
    """The FPS to report as low (the median over the window), or None. Needs a
    minute of samples; once low, stays low until the median is back above
    the clear level, so it doesn't flicker. (0.104.106) The levels follow the
    game's own best FPS: Teacheroar's soak sat at 24-30 FPS for days (fine
    by a fixed 20) while the fort grew 250 -> 438."""
    if len(samples) < 30:
        return low
    vals = sorted(v for _, v in samples)
    med = vals[len(vals) // 2]
    peak = FPS_PEAK if peak is None else peak
    peak["fps"] = max(peak.get("fps") or 0, med)
    floor = max(FPS_FLOOR, FPS_FLOOR_SHARE * peak["fps"])
    clear = max(FPS_CLEAR, FPS_CLEAR_SHARE * peak["fps"])
    if low is None:
        return int(med) if med < floor else None
    return None if med > clear else int(med)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the overseer alongside the game.")
    ap.add_argument("--autopilot", action="store_true", help="actually perform actions")
    ap.add_argument("--ai", action="store_true", help="let the AI strategist review now and then (spends tokens)")
    ap.add_argument("--once", action="store_true", help="plan one cycle now and exit")
    ap.add_argument("--unattended", action="store_true",
                    help="a long run alone: unpause the game when it paused itself, "
                         "hold back when FPS drops (use with --autopilot; brain/keeper.py runs it so)")
    ap.add_argument("--save-seasons", action="store_true",
                    help="also ask DFHack to save each new season (only if DF's own seasonal autosave is off)")
    ap.add_argument("--preset", metavar="NAME",
                    help="apply this preset (as the window's Load preset) to the fort once, before its first "
                         "cycle; not again over later changes (brain/keeper.py --preset passes it)")
    args = ap.parse_args()
    global UNATTENDED, PRESET
    UNATTENDED = bool(getattr(args, "unattended", False))   # (0.104.88) for the camera director
    PRESET = (getattr(args, "preset", None) or "").strip() or None    # (0.105.4)
    import tokens as _tokens
    # (0.99.1, B10) the daily cap across all forts; (r4 k3, B4) one file for the
    # whole PC, outside every fort folder, and a cap on by default (config.json
    # "pc_token_file", "pc_token_cap")
    from dfhack import read_config as _read_config
    _tokens.configure_pc(_read_config())

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    # (13c) one autopilot per folder: a manual --autopilot takes the keeper's
    # lock (logs/keeper.lock), and refuses beside a running keeper; the
    # overseer the keeper starts (DFAI_PIN) runs under the keeper's own lock
    lock = None
    if args.autopilot and not os.environ.get("DFAI_PIN"):
        lock = folder_lock(LOG_DIR)
        if lock is None:
            say("A keeper (or another autopilot) is already running for this folder: not starting a second "
                "autopilot (two would fight over the fort and its memory). A dry run (no --autopilot) can watch.")
            return 1
    try:
        return _run(args)
    finally:
        if lock is not None:
            lock.close()


def fallen_probe(bridge):
    """(x3, V7) For fallen.idle while a mark stands: the loaded fort's raw
    pulse report (before normalize: a failed section is not read as 0) and
    its key, or None when it can't be read. Asked only while a mark stands."""
    def read():
        try:
            try:
                rep = bridge.state(include_units=False, tier="pulse")
            except TypeError:
                rep = bridge.state(include_units=False)     # an older bridge (or a fake one)
        except (BridgeError, DFHackError):
            return None
        if not isinstance(rep, dict):
            return None
        key = fort_key(rep)
        return (rep, key) if key else None
    return read


def _leave_open(bridge) -> None:
    """(0.105.47, J16) The AI stopping: the fort left open if no enemy is in
    reach (brain/planner_way_out.py leave_open). Never raises."""
    try:
        import planner_way_out
        planner_way_out.leave_open(bridge if bridge is not None else Bridge(), say, check=False)
    except Exception as e:  # noqa: BLE001 - stopping never fails on this
        say(f"Leaving the fort open failed: {type(e).__name__}: {str(e)[:120]}")


from overseer_loop import *  # noqa: E402,F401,F403  (r7 d1) POLL_SECONDS, UNPAUSE_AFTER_S, FPS_WINDOW_S, ... moved there
from overseer_loop import _run  # noqa: E402,F401  (* skips these)
sys.modules["overseer_loop"]._ov = sys.modules[__name__]   # its call-time lookups (also as __main__)


if __name__ == "__main__":
    sys.exit(main())
