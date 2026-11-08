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
from planner_society import note_heists  # noqa: E402  (0.105.24)
import atlas  # noqa: E402
import backup  # noqa: E402
import health_check  # noqa: E402
import ledger  # noqa: E402
import season as season_mod  # noqa: E402
import calibrate  # noqa: E402
import chronicle  # noqa: E402
import defence  # noqa: E402
import crisis
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
from review import maybe_review, note_events  # noqa: E402
from storyteller import maybe_tell  # noqa: E402
from tokens import TokenBank  # noqa: E402

POLL_SECONDS = 2.0
UNPAUSE_AFTER_S = 30.0           # (unattended) the game paused itself this long ago: unpause it
FPS_WINDOW_S = 600               # (unattended) the game's speed over the last 10 minutes
FPS_FLOOR = 20                   # below this (the median), newcomers and new luxury levels wait
FPS_CLEAR = 28                   # ... until it's back above this (under a 30 FPS cap too)
TRADE_CYCLES_MAX = 4             # cycles while DF's trade screen is open (time stands still there)...
TRADE_CYCLE_S = 5.0              # ...this many seconds apart
TRADE_STUCK_S = 180.0            # (0.100.1, unattended) still open after its cycles: the AI's own screen closed
TRADE_FORCE_S = 900.0            # ...and any screen, after this long (nobody is at the game)
SOAK_MAX_BYTES = 10_000_000    # (then soak.old.jsonl: ~ten weeks of rows each)
ERRORS_MAX_BYTES = 2_000_000
SOAK = LOG_DIR / "soak.jsonl"    # (unattended) one row every SOAK_EVERY_S of real time: brain/soak_report.py
SOAK_EVERY_S = 600
LAST_CYCLE: dict = {}            # the last cycle's numbers, for the soak row
MEETING_CLOSE_S = 600.0          # (0.104.0, unattended) a meeting screen holding the game this long is left
MEETING_ANSWER_S = 20.0          # (0.105.0) a meeting screen holding the game this long is answered (every 30 s)
MEETING_GIVEUP_S = 120.0         # (0.105.24) left this soon when the AI knows it can't answer it (no button shown
                                 # yet, or a press changed nothing): nobody else will, so no 10-minute stall


def meeting_leave_after(cant_answer: bool) -> float:
    """(0.105.24) How long DF's meeting screen may hold an unattended game
    before the overseer leaves it: 10 minutes for a player to answer, or 2
    when the AI's own answer came back "no button known" or a press changed
    nothing (either way nobody will answer it). Leaving ends the meeting
    without an agreement, as the 10-minute leave always did."""
    return MEETING_GIVEUP_S if cant_answer else MEETING_CLOSE_S
STALL_AFTER_S = 60.0             # (unattended) running, but the date hasn't moved this long: a popup
HEARTBEAT = LOG_DIR / "heartbeat"   # touched every loop: brain/keeper.py restarts a stuck overseer
PLAN_EVERY_TICKS = 1200          # one in-game day
SLOW_PLAN_FACTOR = 2             # (0.104.0) the full report this many times further apart while FPS is low
EVENT_CYCLE_MIN_TICKS = 100      # after an event, plan again this soon at the earliest
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
    # (0.105.0) a scenario copy (marked with a run id in the save) logs apart
    # from the real fort: "<save>@<run id>#<site>" (the site stays last)
    run = f.get("run_id")
    if isinstance(run, str) and run:
        return f"{f['save_dir']}@{run}#{f['site_id']}"
    return f"{f['save_dir']}#{f['site_id']}"


MEMORY_CACHE: dict = {}       # fort -> {"memory", "bank", "tick", "prefer_logs"}: what the last cycle used
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
    if (THROTTLE_MEMORY_SAVE and c is not None and now is not None and c["prefer_logs"] == prefer_logs
            and 0 <= now - c["tick"] <= MEMORY_REREAD_GAP):
        c["tick"] = now
        return c["memory"], c["bank"]
    memory, bank = memstore.load(key, bridge, prefer_logs)
    seed_squads_made(memory, key)
    # (0.104.0) what the AI must not forget, as saved with this very game
    if state is not None and ledger.apply(memory, state.get("ledger")):
        say("Ledger: the alert, gate, memorials, petitions and the like read back as saved with the game")
    # (0.104.45) not kept when the save couldn't be read: one timeout at 08:36
    # was kept for good, so nothing reached the save for the rest of the night
    if now is not None and not (getattr(memory, "_texts", None) or {}).get("save_unread"):
        MEMORY_CACHE[key] = {"memory": memory, "bank": bank, "tick": now, "prefer_logs": prefer_logs}
    else:
        MEMORY_CACHE.pop(key, None)
    return memory, bank


def write_ledger(bridge, state: dict, memory: Memory) -> None:
    """(0.104.0) The ledger into the save when it differs from the one the
    game holds (a bridge from before 0.104.0 has none: nothing written)."""
    held = state.get("ledger") if isinstance(state, dict) else None
    if not isinstance(held, dict) or "error" in held:
        return
    snap = ledger.snapshot(memory)
    if ledger.same(snap, held):
        return
    try:
        r = bridge.act({"type": "ledger_set", "values": snap})
        if r.get("ok"):
            state["ledger"] = snap                 # (the next cycle's report will say so too)
        else:
            say(f"Ledger: not saved with the game ({r.get('error')})")
    except (BridgeError, DFHackError) as e:
        say(f"Ledger: not saved with the game ({e})")


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


MODES = {"advisor": "Advisor", "copilot": "Co-pilot", "autopilot": "Autopilot"}
# What the co-pilot asks you about first (in the game's on-screen panel).
BIG_MOVES = {"start_project", "cancel_project", "cancel_work_order", "squad_fill", "import_orders",
             "build_gate_doors", "fortify_entrance", "expel_dwarf", "place_well", "link_lever", "place_traps",
             "remove_workshops", "deep_depot",      # (0.105.23) a wagon road and a hall dug
             "cut_entrance",                     # (0.105.0) hatches across the fort's stairs: asked first
             "build_gatehouse"}                  # (0.105.23) walls and a drawbridge on the surface
DECLINE_DAYS = 7          # a "No" holds this many in-game days before it may ask again


def is_big(action: dict) -> bool:
    return (action["type"] in BIG_MOVES or (action["type"] == "tool" and action.get("enabled") is False)
            # plots on existing floor are routine; digging a farm level is a project
            or (action["type"] == "farm_plots" and action.get("dig") is True))


ID_KEYS = ("type", "kind", "name", "size", "project_id", "order_id", "recipe", "squad_id")


def proposal_id(p) -> str:
    """Stable id for a proposal, so an answer in the game matches it next cycle.
    Sizes and counts are left out: a new bedroom level for 30 or for 32 rooms
    is the same question."""
    a = {k: p.action.get(k) for k in ID_KEYS if k in p.action}
    return hashlib.sha1((p.rule + json.dumps(a, sort_keys=True)).encode()).hexdigest()[:8]


CAMERA_QUIET = {"census", "join_levels", "dismiss_alerts", "sand_zone", "report_status", "survey_water", "scan_entrances", "recreation", "hospital_burrow",
                "calm_burrow",   # (0.104.169)
                "cistern_step", "water_work", "restrict_water", "save_memory", "pair_chairs", "approve_orders"}


_CAMERA_LEVELS: list = []   # (0.104.91) the newest "dig a new ... level" lines, while the keeper runs


def death_words(ev: dict) -> str:
    """(0.104.100) A death in a line: who, how (DF's cause), by whom, where."""
    who = " ".join(str(ev.get("name") or "someone").split())
    cause = str(ev.get("cause") or "").replace("_", " ").lower()
    bits = [who]
    if ev.get("again"):
        bits.append("(laid to rest: died before)" if not ev.get("ghost") else "(a ghost laid to rest)")
    elif cause:
        bits.append(cause)
    if ev.get("killer") and not ev.get("again"):
        bits.append(f"by {' '.join(str(ev['killer']).split())} ({ev.get('killer_kind') or '?'})")
    # (0.104.139) the fight's level, the killer's state and the victim's
    extra = [w for w in (ev.get("conflict") not in (None, "None") and f"a {str(ev['conflict']).lower()} fight",
                         ev.get("killer_mood") and f"the killer {str(ev['killer_mood']).lower()}",
                         # (0.105.24) which outsider: a visitor; or an old wound (the killer died first)
                         ev.get("killer_visitor") and "the killer a visitor",
                         ev.get("killer_dead") and "an old wound (the killer died before)",
                         ev.get("patient") and "a patient waiting for care",
                         ev.get("infected") and "infected",
                         # (0.104.148) the victim insane or in a mood (melancholy and raving dwarves stop drinking)
                         ev.get("mood") and f"in a {str(ev['mood']).lower()} mood") if w]
    if extra and not ev.get("again"):
        bits.append("; ".join(extra))
    if ev.get("x") is not None:
        bits.append(f"at x{ev['x']} y{ev['y']} z{ev['z']}")
    return ", ".join(bits)


def camera_feed(memory) -> dict:
    """(0.104.90) For the in-game camera: the plan's district names and the
    reasons for the AI's newest work (the camera shows them under a new or
    finished level of that kind). (0.104.91) Memory keeps only 10 actions and
    clearing alert icons crowded the levels out within a few cycles: the
    routine ones are left out, and each "dig a new ... level" line is kept
    here (4 at most) and put first, so a finished level's caption carries why
    it was dug too."""
    other = []
    for a in reversed(memory.recent_actions):
        act = a.get("action") if isinstance(a, dict) else None
        if not isinstance(act, dict) or act.get("type") in CAMERA_QUIET:
            continue
        line = f"{short(act)}: {a.get('reason', '')}".rstrip(": ")[:100]
        if act.get("type") == "start_project":
            if line not in _CAMERA_LEVELS:
                _CAMERA_LEVELS.insert(0, line)
                del _CAMERA_LEVELS[4:]
        elif line and line not in other:
            other.append(line)
    return {"districts": masterplan.camera_districts(memory), "news": (list(_CAMERA_LEVELS) + other)[:6]}


# (13c) The actions said the same way every time, for short() below.
SHORT_WORDS = {
    "survey_water": "survey the water near the fort",
    "staff_labors": "give the hospital's staff the labours of their posts",
    "retarget_hall": "give a hall being dug to another petition",
    "dismiss_alerts": "clear old alert icons from the screen",
    "vacate_post": "give a patient's hospital post to a healthy dwarf",  # (0.104.111)
    "give_trinkets": "give trinkets to dwarves who want something to own",
    "place_keep": "build the keep above ground (next step)",
    "deep_depot": "dig a wagon road down to an underground trade depot (next step)",  # (0.105.23)
    "polish": "smooth or engrave a finished level",
    "quarry": "dig a small quarry in ordinary stone",
    "adopt_uniform": "take charge of a squad's copied uniform",
    "idle_crafting": "let idle dwarves craft for themselves",
    "order_instrument": "order instruments for the tavern and temples",
    "slaughter_one": "send a spare animal to the butcher",
    "sand_zone": "make a sand collection zone (for glass)",
    "water_zone": "mark open water as a water source for the injured",
    "close_meeting": "leave DF's meeting screen",
    "answer_meeting": "answer the diplomat's meeting",  # (0.105.0)
    "prune_remains": "let old corpses and useless body parts rot away",
    "feeder_pile": "put a feeder stockpile beside a workshop",
    "squad_barracks": "give a squad its barracks",
    "open_trade": "open the trade screen at the depot",
    "close_trade": "close the trade screen",
    "call_trader": "send someone to the trade depot",
    "place_slabs": "put up the engraved memorial slabs",
    "unload_depot": "take the fort's goods back out of the trade depot",
    "make_squad": "make a squad and appoint its leader",
    "gather_plants": "gather the shrubs near the fort",
    "unstick_uniforms": "untangle the soldiers' uniforms (uniform-unstick)",
    "free_stray_gear": "hand out the gear the game had lost track of",  # (0.104.58)
    "guard_gate": "send the squads to hold the main gate",  # (0.104.83)
    "gate_dogs": "pen the war dogs inside the main gate",  # (0.104.83)
    "train_war": "put tame animals to war training",  # (0.104.81)
    "nest_boxes": "pen the hens together and put nest boxes in their pasture",  # (0.104.80)
    "accept_cups": "let the finished goods piles take the loose cups",  # (0.104.168)
    "prisoner_room": "a cage room for the prisoners inside the fort",
    "traction_rest": "get a patient who needs traction out of an ordinary bed, so the game lays him on the traction bench",  # (0.105.24)
    "mood_free_items": "free the forbidden materials a strange mood is waiting for",  # (0.105.24)
    "add_doctor_post": "add a second doctor's post at a hospital",  # (0.104.168)
    "recreation": "move the unhappiest into the recreation burrow, the recovered back to work",  # (0.104.78)
    "pair_chairs": "put a chair beside each lone chair in the tavern",  # (0.104.77)
    "squad_swap": "send a soldier back to work and draft a keen dwarf in his place",  # (0.104.65)
    "assign_kit": "give the soldiers the free armour the game won't hand out",  # (0.105.8)
    "assign_weapons": "give the soldiers the free weapons the game won't hand out",  # (0.104.60)
    "assign_quivers": "give the crossbow soldiers quivers",
    "squad_bolts": "bolts for a crossbow squad",
    "cut_entrance": "hatches on the stairs down from a wide opening",
    "farm_thresholds": "set which crops the farms favour (autofarm)",
    "pull_gate": "pull the AI gate lever",
    "clear_webs": "clear the spider webs",  # (0.104.116)
    "remove_webs": "remove spider webs far from the fort",  # (0.105.3)
    "scrub_dead_units": "clear old dead creatures from the game's unit list",  # (0.104.158)
    "census": "count what fills the map",  # (0.104.113)
    "seal_well_stairs": "close the cavern wells' stair columns",  # (0.104.151)
    "join_levels": "join areas on one level that meet only through the stairs",  # (0.104.108)
    "scan_entrances": "map the fort's entrances",
    "arm_gates": "watch the gates (close when danger nears)",
    "open_gates": "open the gates",
    "found_fort": "dig the fort's first staircase",
    "link_lever": "link the AI gate lever to a drawbridge or hatch",
    "place_gate_lever": "put a lever inside the fort for the gate",
    "build_gate_doors": "put doors on an open entrance",
    "expel_dwarf": "send a dwarf away",
    "setup_shelter": "set up the AI shelter burrow",
    "refresh_shelter": "make the AI shelter again (a gate was lost)",    # (0.105.26)
    "sync_offices": "put the appointed nobles on the game's duty lists",
    "bootstrap_chair": "make one chair straight at a workshop (for the manager's office)",
    "approve_orders": "approve the AI's waiting work orders (no manager's office yet)",
    "unsuspend_orders": "resume the AI's suspended work-order jobs",
    "restrict_water": "mark the tiles over the water as restricted traffic",
    "free_slabs": "unforbid the memorial slabs and resume their building",
    "clear_orphan_jobs": "take jobs off the benches whose work order is gone",
    "repair_rooms": "build back the walls dug out of rooms",
    "allow_burial": "let the AI's tombs take the fort's dead",
    "unforbid_dead": "unforbid the fort's dead so they can be buried",
    # (0.105.27) forbidden items disposed of
    "unforbid_items": "unforbid the forbidden items worth keeping, so they are stored",
    "mark_melt": "mark surplus and worn metal to melt down",
    "mark_dump": "mark worn-out junk for the garbage dump",
    "place_dump": "make a garbage dump",
    "empty_dump": "remove the items piled in the garbage dump (DFHack)",
    "set_standing_orders": "set the game's standing orders",
    # (13c) planner actions that had no words (the panel showed their type)
    "break_fights": "end the citizens' fights (fix/loyaltycascade)",
    "build_crossing": "build a bridge across a gap",
    "remove_crossing": "take down one of the AI's bridges",
    "free_dig_jobs": "free the workers held by a stalled level's dig jobs",
    "trim_instrument_orders": "cancel extra instrument orders",
}


def short(a: dict) -> str:
    """An action in a few words, for the on-screen panel."""
    t = a.get("type")
    words = SHORT_WORDS.get(t)
    if words is not None:
        return words
    if t == "set_population_cap":
        return f"set the population cap to {a.get('cap')}"
    if t == "work_order":
        return f"order {a.get('amount')} x {str(a.get('recipe')).replace('_', ' ')}"
    if t == "tool":
        return f"{a.get('name')} {'on' if a.get('enabled') else 'off'}"
    if t == "civ_alert":
        return f"civilian alert {'on' if a.get('on') else 'off'}"
    if t == "squad_fill":
        return f"add {a.get('count')} soldiers to a squad"
    if t == "squad_orders":
        return "call the squad back" if a.get("clear") else f"send a squad at {len(a.get('kill') or [])} enemies"
    if t == "squad_routine":
        return f"squad on {str(a.get('routine')).lower()}"
    if t == "assign_labor":
        return (f"put {a.get('count')} more dwarves on {a.get('job')}" if a.get("count")
                else "put the work details in order")
    if t == "place_surface":
        return {"refuse": "put a refuse pile outside", "dump": "make a garbage dump outside",
                "cages": "make a stockpile for full cages"}.get(
            a.get("kind"), "build a trade depot outside")
    if t == "cistern_step":
        return "shut the cistern's floodgate" if a.get("shut") else "the cistern: next step"
    if t == "water_work":        # (0.105.0)
        what = {"moat": "the moat", "pump": "the pump stack", "irrigation": "the muddied farm level",
                "magma": f"the {a.get('shop') or 'magma workshop'}"}.get(a.get("kind"), "a water work")
        if a.get("shut"):
            return f"shut {what}'s floodgate"
        return f"{what}: next step"
    if t == "answer_petition":
        if a.get("ids"):
            return ("agree to" if a.get("accept") else "decline") + f" {len(a['ids'])} petitions to stay"
        if a.get("residency"):
            return ("agree to" if a.get("accept") else "decline") + " a petition to stay"
        return ("agree to" if a.get("accept") else "decline") + " a petition for a temple or guildhall"
    if t == "place_in_zone":
        return f"put {str(a.get('what') or 'furniture').replace('_', ' ')} in a zone"
    if t == "petition_orders":
        return "answer petitions: " + ", ".join(
            f"{'accept' if v else 'ask about'} {str(k).replace('_', ' ')}" for k, v in (a.get("orders") or {}).items())
    if t == "add_posts":
        return "make posts at a location (" + ", ".join(str(k).lower().replace("_", " ") for k in (a.get("posts") or [])) + ")"
    if t == "staff_location":
        return f"give a dwarf the {str(a.get('post') or 'post').lower().replace('_', ' ')} post"
    if t == "house_dwarves":     # (0.104.168)
        return ("move stressed dwarves to rooms they like better" if not a.get("house")
                else "one bedroom per household (couples together, a room for those with none)")
    if t == "remove_workshops":
        return f"take down extra {a.get('kind')} workshops"
    if t == "trim_gathering":
        return f"cancel waiting plant-gathering jobs, keeping {a.get('keep')}"
    if t == "allow_stone":
        stone = str(a.get('stone')).lower().replace('_', ' ')
        return f"keep {stone} from the masons" if a.get("keep") else f"let the masons use {stone}"
    if t == "set_uniform_weapon":
        return f"arm a squad with {str(a.get('weapon')).replace('ITEM_WEAPON_', '').lower().replace('_', ' ')}s"
    if t == "set_uniform":
        return f"give a squad the {a.get('kind')} {'crossbow ' if a.get('ranged') else ''}uniform"
    if t == "give_room":
        return f"give {a.get('name') or 'a noble'} a {a.get('kind')}"
    if t == "trim_labor":
        return f"take all but {a.get('keep')} off the {a.get('job')} work detail"
    if t == "narrow_detail":
        return f"{'widen' if a.get('widen') else 'narrow'} the {a.get('job')} work detail"
    if t == "send_mission":      # (0.105.24, 13b)
        return f"send the messenger to make contact with site {a.get('site_id')} (World screen)"
    if t == "keep_mousers":      # (0.104.168)
        return f"keep {a.get('count') or 'a few'} cats from the butcher to hunt the vermin"
    if t == "trade_deal":
        return "trade with the caravan" + (" (and press Trade)" if a.get("press") else "")
    if t == "bring_goods":
        return f"take {a.get('count')} crafts to the trade depot"
    if t == "kitchen_skill":
        return (f"let only cooks of skill {a.get('min_level')}+ work the kitchens" if a.get("min_level") else
                "let any cook work the kitchens again")
    if t == "clear_gate":
        return f"take down the gate at x{a.get('x')} y{a.get('y')}"
    if t == "mine_ore":
        return f"mine a vein of {str(a.get('metal')).lower()} ore"
    if t == "appoint":
        return f"appoint a {str(a.get('office')).lower().replace('_', ' ')}"
    if t == "dig_stairwell":     # (0.104.82)
        return f"dig a new stairwell {a.get('dir')} of the main stair"
    if t == "hospital_burrow":   # (0.104.167)
        if a.get("release"):
            return "let every patient out of the hospital burrow"
        return "keep the wounded inside the hospital, the healed back to work"
    if t == "calm_burrow":       # (0.104.169)
        if a.get("release"):
            return "let every dwarf out of the calm-down burrows"
        return "keep each dwarf in a tantrum in a free bedroom away from the patients till calm, the calm let out"
    # (0.105.0) round 3: threats answered
    if t == "fire_guard":
        return "the fire is out: paths round it back to normal" if a.get("lift") else "keep the dwarves away from the fire"
    if t == "moon_cell":
        return "let the werebeasts out of their cells" if a.get("release") else "lock the werebeasts in for the full moon"
    if t == "seal_cavern":
        if a.get("openings") or a.get("layer") == "all caverns":       # (0.105.26) every cavern opening
            return "open the ways into the caverns again" if a.get("open") else "lock every way into the caverns"
        return f"unlock the way down to {a.get('layer')}" if a.get("open") else f"lock the way down to {a.get('layer')}"
    if t == "rest_infected":     # (0.104.168)
        return f"put up to {a.get('max', 3)} dwarves with infected wounds to bed in the hospital, for the doctors"
    # (0.105.0, round 2) an army that can fight
    if t == "fix_gear_gaps":
        return "mend the uniforms so the soldiers get weapons" + (" and shields" if a.get("shields") else "")
    if t == "shelter_squads":
        return f"send {len(a.get('squads') or [])} squad(s) to wait in the shelter"
    if t == "set_farm_crops":      # (0.105.5) Hammerstirred: the plots lay fallow under autofarm
        return ("set each farm plot's crops" + (" (brewable first)" if a.get("drink") else "")
                + (" (a second brewable crop: drinks of more kinds)" if a.get("variety") else ""))
    if t == "kitchen_brewables":   # (0.100) the kitchen ban on cooking brewables
        return ("stop the kitchen cooking brewable plants" if a.get("ban") else
                "let the kitchen cook brewable plants again")
    if t == "set_rules":         # (0.105.20) logs/rules-request.json
        return "set Rules switches: " + ", ".join(f"{k} {'on' if v else 'off'}" for k, v in sorted(_d(a.get("rules")).items()))
    if t == "apply_preset":      # (0.105.4) keeper.py --preset
        return f"apply the {a.get('name')} preset"
    if t == "convict":           # (0.104.131)
        return f"convict {a.get('max')} solved case(s)"
    if t == "well_shaft":        # (0.104.152)
        return "shut the cavern well's shaft" if a.get("close") else "the cavern well's shaft gate: its next step"
    if t == "prioritize_dig":    # (0.104.128)
        return f"dig level {a.get('project_id')} before the rest"
    if t == "mark_run":          # (0.105.0)
        return f"mark this save as test run {a.get('run_id')}"
    if t == "place_traps":
        return f"put {a.get('count')} {a.get('kind')} traps behind a gate"
    if t == "build_gatehouse":     # (0.105.23, 14.1 step 4a)
        return f"build a gatehouse at the founding stair (drawbridge, walls, {a.get('kind') or 'cage'} trap corridor)"
    if t == "location_access":
        return ("open" if a.get("visitors") else "close") + f" {len(a.get('ids') or [])} location(s) to visitors"
    if t == "fortify_entrance":
        return f"wall an entrance down to a {a.get('style')} gate"
    if t == "pasture":
        return f"put {a.get('count')} animals in a pasture"
    if t == "import_orders":
        return f"add DFHack's {a.get('library')} orders"
    if t == "make_pasture":
        return f"make a {a.get('tiles')}-tile pasture"
    if t == "place_well":
        return "dig a shaft to a cavern lake for a well" if a.get("cavern") else "dig a well over water"
    if t == "farm_plots":
        return (f"lay out {a.get('tiles')} farm tiles" + (" underground" if a.get("underground") else "")   # (0.105.5)
                + (" (or dig a farm level)" if a.get("dig") else ""))
    if t == "start_project":
        what = a.get("name") and f"memorial for {a['name']}" or a.get("kind")
        return f"dig a new {what} level"
    if t in ("furnish_project", "finish_project", "engrave_project", "cancel_project"):
        return f"{t.split('_')[0]} level #{a.get('project_id')}"
    if t == "cancel_work_order":
        return f"cancel order #{a.get('order_id')}"
    if t == "quick_location":
        return f"make the dining hall a {a.get('kind')} for now"
    if t == "squad_release":
        return f"take unit {a.get('unit_id')} out of the squad"
    if t == "squad_trim":
        return f"send {a.get('count')} soldier(s) back to work"
    if t == "kitchen_fat":
        return "keep fat and tallow from the cooks" if a.get("ban") else "let the cooks use fat and tallow again"
    if t == "order_slots":
        return f"let workshop #{a.get('workshop_id')} take {a.get('max')} jobs from work orders"
    if t == "bench_jobs":
        return f"put {a.get('count')} {a.get('kind')} job(s) straight on a workshop's bench"
    return str(t)


STATES_KEPT = 80          # (0.100.1) every season of a long run (~60 KB each)


def state_run(path: Path) -> str | None:
    """(0.105.26) The run a kept season state belongs to: its leading "_run"
    (None for one kept before runs were marked)."""
    try:
        with open(path, "rb") as f:
            head = f.read(200).decode("utf-8", "replace")
    except OSError:
        return None
    m = re.match(r'\{"_run": "([^"]*)"', head)
    return m.group(1) if m else None


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
        run = fort_run(key)
        if path.exists() and (run is None or state_run(path) == run):
            return
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
    try:
        bridge.act({"type": "report_status", "status": payload})
        STATUS_SENT.update(bridge=bridge, payload=payload, at=time.monotonic())
    except (BridgeError, DFHackError):
        STATUS_SENT.clear()


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


def one_cycle(bridge: Bridge, autopilot: bool, backend=None, controls: dict | None = None,
              mode_override: str | None = None, tier: str = "daily") -> None:
    if controls is None:
        try:
            st = bridge.status()
        except (BridgeError, DFHackError):
            st = {}
        controls = {"halted": st.get("halted") is True, "decisions": st.get("decisions") or {}}
    state = get_state(bridge, tier)
    if controls.get("fps_low"):
        state["fps_low"] = controls["fps_low"]     # measured by the main loop (unattended)
    key = fort_key(state)
    if key is None:
        say("Couldn't tell which fort is loaded (report section 'fort' failed); skipping this cycle.")
        return
    # (0.105.0) under the keeper: only the fort it pinned (brain/pin.py)
    try:
        import pin
        _f = _d(state.get("fort"))
        refused = pin.refusal(_f.get("world"), _f.get("site_id"))
    except Exception:  # noqa: BLE001
        refused = None
    if refused:
        if refused not in WARNED:
            WARNED.add(refused)
            say(refused)
        return
    try:
        import scenario_mark                       # (0.105.0) a scenario copy waiting for its run id
        if scenario_mark.mark(bridge, state, say):
            key = fort_key(state)
    except Exception:  # noqa: BLE001
        pass
    try:
        memstore.note_world(key, (state.get("fort") or {}).get("world"))
    except Exception:  # noqa: BLE001  (the logs folder's name never stops the fort)
        pass
    if PRESET:
        apply_preset(bridge, state, key, autopilot)    # (0.105.4) keeper.py --preset, before the first plan
    rules_request(bridge, autopilot)                   # (0.105.20) logs/rules-request.json
    memory, bank = load(key, bridge, prefer_logs=not autopilot, state=state)
    for k in sorted(memory._texts.get("frozen") or ()):
        if (key, k) not in WARNED:
            WARNED.add((key, k))
            say(f"Memory: the {k} part of this fort's memory couldn't be read (or comes from a newer "
                "version); it is left exactly as it is, and that part starts afresh for now.")
    if memory._texts.get("save_unread"):
        say("Memory: the save's memory couldn't be read this time; nothing is written into the save this cycle"
            + (f" ({memory._texts.get('save_unread_why')})" if memory._texts.get("save_unread_why") else "") + ".")
    to_save = False
    try:
        events = bridge.events()
        seen: dict[str, int] = {}
        for ev in events:
            journal({"kind": "event", "fort": key, "event": ev})
            if ev.get("kind") == "report" and ev.get("topic") not in QUIET_TOPICS:
                # one line however the text runs (a name can hold a line break)
                line = f"Seen: {ev.get('topic')}: {' '.join(str(ev.get('text', '')).split())[:120]}"
                seen[line] = seen.get(line, 0) + 1
            elif (ev.get("kind") == "death" and ev.get("own_civ") and not ev.get("animal")) \
                    or (ev.get("kind") == "death" and ev.get("great")):
                line = "Died: " + death_words(ev)    # (0.104.100) how each one died, in the log
                seen[line] = seen.get(line, 0) + 1
        for line, n in seen.items():          # the same announcement 9 times is one line
            say(line + (f" (x{n})" if n > 1 else ""))

        # (0.97.1) your memory on the PC knows the fort by its line (world and
        # site: its autosaves and copies are one fort); a dry run doesn't write it
        line = learning.line_key(key, (state.get("fort") or {}).get("world"))
        normalize(state)      # (13c) once, in place: the steps below read the sections as they are
        learned_now = learning.observe(state, memory, line, write_pc=autopilot)   # before note_cycle: it reads the tools
        expire_adjustments(memory, state)
        notes = note_cycle(state, memory)
        note_tantrums(state, memory, events)     # (0.104.31) tantrums counted for the jail
        note_heists(state, memory, events)       # (0.105.24) heists and visitors' killings: visitors kept out a while
        crisis.note_deaths(state, memory, events)   # (0.104.137) deaths counted for crisis mode
        note_events(state, memory, bank if backend else None, events)
        for line in learned_now:
            say(f"Learned: {line}")
            journal({"kind": "learned", "fort": key, "date": state["date"], "text": line})
        cfg = effective_config(memory.adjust, calibration=calibrate.values(memory))
        remember_world(state, memory, events, key, cfg, learned_now, bridge)
        for ch in calibrate.update(state, memory, cfg, memory.adjust):
            say(f"Self-tuned: {ch['name']} {ch['old']} -> {ch['new']} ({ch['why']})")
            journal({"kind": "calibration", "fort": key, "date": state["date"], **ch})
            if ch["up"]:
                kind = {"drink_per_dwarf": "drink_target", "meals_per_dwarf": "meal_target",
                        "farm_tiles_per_dwarf": "farm_target", "pasture_margin": "pasture_margin"}[ch["key"]]
                ent = outcomes.open_entry(state, memory, kind, f"{ch['name']} {ch['old']} -> {ch['new']}",
                                          "self-tuning", expect="down" if kind == "pasture_margin" else "up")
                if ent is not None:     # (0.102.7, B6) so a bad verdict can take it back
                    ent.update(tune_key=ch["key"], tune_old=ch["old"], tune_new=ch["new"])
        cfg = effective_config(memory.adjust, calibration=calibrate.values(memory))
        for e in outcomes.judge(state, memory):
            say(f"Outcome: {outcomes.KINDS[e['kind']][3]} ({e['by']}): "
                f"{outcomes.VERDICT_TEXT[e['verdict']]}, {e['why']}")
            journal({"kind": "outcome", "fort": key, "date": state["date"], "of": e.get("kind"),
                     **{k: e.get(k) for k in ("what", "by", "metric", "expect", "before", "verdict", "why")}})
            back = calibrate.heed(e, memory, state)
            if back:
                say(f"Self-tuned: {back['name']} {back['old']} -> {back['new']} ({back['why']})")
                journal({"kind": "calibration", "fort": key, "date": state["date"], **back})
        style_before = _style_choices(memory)
        culture_update(state, memory, events, key)
        style_after = _style_choices(memory)
        if style_before and style_after != style_before:
            changed = [a for a in style_after if style_after.get(a) != style_before.get(a)]
            outcomes.open_entry(state, memory, "style", "new style: " + ", ".join(
                f"{a} {style_after[a]}" for a in changed), "weights engine")
        proposals, plan_notes = plan(state, memory, cfg)
        try:
            from planner import agenda as _agenda
            if proposals or plan_notes:
                memory.agenda = _agenda(proposals, plan_notes)
        except Exception:  # noqa: BLE001  (the agenda is only words)
            pass
        notes += plan_notes

        # (0.104.3) the season's character decision by script: forts without
        # tokens, or whose AI review made no choice in the season's first two weeks
        if autopilot and season_mod.due(state, memory) and (backend is None or season_mod.ai_gave_up(state, memory)):
            try:
                choice = season_mod.pick(state, memory, cfg)
                said = season_mod.apply(choice, state, memory, memory.adjust)
                chronicle.add(memory, state, "season", choice.get("line") or "; ".join(said))
                for line in said:
                    say(f"  Season (script): {line} ({choice.get('why')})")
                journal({"fort": key, "date": state["date"], "kind": "season", "by": "script", "choice": choice,
                         "scores": {k: v[0] for k, v in season_mod.score_options(state, memory, cfg).items()}})
            except Exception as e:  # noqa: BLE001  (a season's choice never stops the fort)
                say(f"Season: no scripted choice ({type(e).__name__}: {e})")
        if backend is not None:
            outcome = maybe_review(state, memory, bank, backend, bridge.version or {}, notes, proposals=proposals)
            for line in outcome.say:
                say(line)
            if outcome.journal:
                journal({"fort": key, "date": state["date"], **outcome.journal})
            ai_props = outcome.proposals
            try:     # (0.105.23) the strategist's levels keep under the surface in the Deep mine too
                from planner import _deep_surface_filter, _traits as _plan_traits
                ai_props = _deep_surface_filter(state, _plan_traits(state), memory, list(ai_props), notes)
            except Exception:  # noqa: BLE001  (never stops the cycle; the bridge's own checks still hold)
                pass
            proposals = ai_props + proposals
            _note_adjust(state, memory, outcome.journal, cfg)
            try:
                story = maybe_tell(state, memory, bank, backend)
                for line in story.say:
                    say(line)
                if story.text:
                    journal({"fort": key, "date": state["date"], "kind": "story", "text": story.text,
                             "tokens": story.used})
            except Exception as e:  # noqa: BLE001 - a story is never worth stopping the overseer for
                say(f"AI chronicle failed: {type(e).__name__}: {e}")

        # what you've turned down waits (or is left to you)
        proposals, learned_notes = learning.apply(proposals, memory, abs_tick(state))
        notes += [n for n in learned_notes if n not in notes]
        allowed, held = select(proposals, state, memory, cfg)
        stopped = STOP_FILE.exists()
        halted = controls.get("halted") is True
        decisions = _d(controls.get("decisions"))
        settings = _d(state["settings"])
        mode = settings.get("mode") if settings.get("mode") in MODES else "autopilot"
        if mode_override in MODES:
            mode = mode_override      # scenario runs play unattended: nobody to ask
        acting = autopilot and not stopped and not halted and mode != "advisor"
        to_save = autopilot           # a dry run never writes into the save
        why_not = ("halted in the game" if halted else "STOP file present" if stopped
                   else "advisor mode: suggesting only" if mode == "advisor" else "")
        say(f"{date_str(state)}: {len(proposals)} proposal(s), {len(allowed)} allowed"
            + (f" [{why_not}: not acting]" if autopilot and why_not else ""))
        todo = [n[len(NEEDS_YOU):] for n in notes if n.startswith(NEEDS_YOU)]
        notes = [n for n in notes if not n.startswith(NEEDS_YOU)]
        # (0.104.0) how long each Needs you and failing-rule line has stood (the run check)
        health_check.track_standing(key, todo, notes, abs_tick(state))
        show_changed(key, [f"  NEEDS YOU: {n}" for n in todo] + [f"  note: {n}" for n in notes]
                     + [f"  held: {h}" for h in held])

        if acting:
            push_culture(bridge, state, memory)
            push_learned(bridge, state, memory)
        now = abs_tick(state)
        pending, would = [], []
        memory.declined = {k: t for k, t in memory.declined.items() if 0 <= now - t < DECLINE_DAYS * 1200}
        results = []
        no_answer = False            # (0.104.138) an action the game didn't answer: the rest wait
        try:
            for p in allowed:
                r = None
                if no_answer and acting:
                    say(f"  held: {short(p.action)} (the game didn't answer the last action; next cycle)")
                    continue
                if acting and mode == "copilot" and is_big(p.action):
                    pid = proposal_id(p)
                    answer = decisions.get(pid)
                    if memory.saved_before == pid:
                        answer = "yes"        # you said Yes; the game was saved first
                    if answer == "no":
                        memory.declined[pid] = now
                        say(f"  you declined: {short(p.action)}")
                        lesson = learning.note_decline(memory, p.action, state)
                        if lesson:
                            say(f"  learned: {lesson}")
                            if "lesson" in lesson:
                                chronicle.add(memory, state, "learned", lesson)
                        journal({"kind": "declined", "fort": key, "date": state["date"], "rule": p.rule,
                                 "reason": p.reason, "action": p.action})
                        continue
                    if answer != "yes":
                        if pid not in memory.declined:
                            pending.append({"id": pid, "text": f"{short(p.action)} ({p.reason})"})
                            say(f"  asking you in the game: {short(p.action)} ({p.reason})")
                        continue
                    say(f"  you approved: {short(p.action)}")
                    if answer == "yes":
                        learning.note_approve(memory, p.action, state)
                if acting and p.action["type"] == "start_project" and settings.get("save_before_projects"):
                    pid = proposal_id(p)
                    if memory.saved_before != pid:
                        # Save first; the new level starts next cycle, after the save.
                        try:
                            write_ledger(bridge, state, memory)    # (0.104.0) the save carries the ledger as of now
                            bridge.df.run("quicksave")
                            memory.saved_before = pid
                            say("  saving the game before digging a new level; it starts next cycle")
                        except DFHackError as e:
                            say(f"  could not save the game first ({e}); not starting the new level")
                        continue
                if acting:
                    try:
                        r = bridge.act(p.action)
                    except BridgeError as e:
                        r = {"ok": False, "error": str(e)}
                    except DFHackError as e:
                        # The command may or may not have happened in the game.
                        r = {"ok": None, "error": f"no reply from the game ({e})"}
                        no_answer = True     # (0.104.138) the next would only queue behind it
                    results.append((p, r))
                    if p.action["type"] == "start_project" and r.get("ok") is True:
                        memory.saved_before = ""
                    outcome_txt = {True: "done", None: f"UNKNOWN: {r.get('error')}"}.get(
                        r.get("ok"), f"refused: {r.get('error')}")
                    if r.get("ok") is True and r.get("clearing"):
                        outcome_txt = (f"started: {r.get('trees')} tree(s) at x{r.get('x')} y{r.get('y')} "
                                       "marked for felling first; placed once they're down")
                    elif r.get("ok") is True and p.action["type"] == "open_trade" and r.get("clicking"):
                        outcome_txt = f"clicked the depot's Trade button at {r.get('at')} (the screen is checked next cycle)"
                    elif r.get("ok") is True and p.action["type"] == "send_mission" and r.get("sending"):   # (0.105.24)
                        outcome_txt = (f"the World screen driven to send the messenger to {r.get('site') or r.get('site_id')} "
                                       "(each step checked over the next frames; the outcome in the missions report)")
                    elif r.get("ok") is True and p.action["type"] == "call_trader" and not r.get("waiting"):
                        outcome_txt = ("the trader is at the depot" if r.get("at_depot") else
                                       "anyone may trade now (the broker didn't come)" if r.get("anyone") else
                                       "broker asked for" if r.get("requested") else
                                       f"waiting for {r.get('coming') or 'the broker'} ({r.get('waiting_ticks')} ticks)")
                    elif r.get("ok") is True and p.action["type"] == "trade_deal" and not r.get("dry_run") and not r.get("waiting"):
                        outcome_txt = (f"ticked {len(r.get('bought') or [])} of their goods (value {r.get('buy_value')}) "
                                       f"for {r.get('given')} of ours (value {r.get('give_value')})")
                        if r.get("answer"):
                            outcome_txt += f"; pressed Trade: {r.get('answer')}, " + ("traded" if r.get("traded") else "NOT traded")
                            c = r.get("counter") or {}
                            if c:
                                outcome_txt += (f" (they asked for {c.get('items')} more worth {c.get('value')}: "
                                                + ("given" if c.get("accepted") else "refused, left to you") + ")")
                            if r.get("traded") and not r.get("closed"):
                                outcome_txt += "; the trade screen is still open"
                        elif not r.get("calibrated"):
                            outcome_txt += "; press Trade yourself (the AI hasn't been shown the button)"
                    elif r.get("waiting"):
                        outcome_txt = f"waiting: {r.get('error')}"
                    say(f"  {p.rule}: {p.reason} -> {json.dumps(p.action)} [{outcome_txt}]")
                else:
                    would.append(f"would {short(p.action)}: {p.reason}")
                    say(f"  would do ({p.rule}): {p.reason} -> {json.dumps(p.action)}")
                journal({"kind": "decision", "fort": key, "date": state["date"], "rule": p.rule,
                         "reason": p.reason, "action": p.action,
                         "mode": "autopilot" if acting else "dry-run", "result": r})
        finally:
            if results:
                LAST_FULL.clear()                 # the fort changed: the next cycle reads the full report
                record(results, state, memory, cfg)
                learning.note_actions(results, state, memory)
                outcomes.record_actions(results, state, memory)
                for line in atlas.note_actions(results, state, memory):
                    say(f"Atlas: {line}")              # what was built, or what the AI found and chose
                    chronicle.add(memory, state, "gate", line)
                for p, r in results:
                    line = masterplan.note_result(memory, p.action, r, state)
                    if line:
                        say(f"Plan: {line}")
                        chronicle.add(memory, state, "plan", line)
        memory.notes = notes + [NEEDS_YOU + t for t in todo]
        if acting:
            write_ledger(bridge, state, memory)
        if autopilot:
            try:
                bad = "; ".join(report.trouble(state, memory))
            except Exception:  # noqa: BLE001  (a report problem never stops the fort)
                bad = memory.trouble_seen
            if bad != memory.trouble_seen:
                say(f"THE FORT IS IN TROUBLE: {bad}" if bad else "The fort is out of trouble.")
                chronicle.add(memory, state, "trouble", bad or "out of trouble")
                memory.trouble_seen = bad
            line = report.maybe_write(state, memory, key, todo, controls.get("fps"))
            if line:
                say(f"Report: {line}")
                if controls.get("save_seasons") and acting and not line.startswith("couldn't"):
                    # only with --save-seasons: DF's own seasonal autosave does this (Oct 21: it
                    # saved every season by itself, and a second save only made the game stall)
                    try:
                        r = bridge.act({"type": "save_game"})
                        say(f"No extra save for the new season: {r.get('by')}." if r.get("already")
                            else "Asked DFHack to save the game for the new season." if r.get("ok")
                            else f"Couldn't save the game: {r.get('error')}")
                    except (BridgeError, DFHackError) as e:
                        say(f"Couldn't save the game: {e}")
        if state.get("tier") in (None, "daily", "survey"):
            keep_state(state, key)
            probe_gear(bridge, state, key)
            probe_posts(bridge, state, key)
        try:
            # where the save lives, for the keeper's --revive (load-save after a crash)
            import revive
            f0 = _d(state.get("fort"))
            revive.write_last_fort((bridge.version or {}).get("df_path"), f0.get("save_dir"), key,
                                   world=f0.get("world"))
        except Exception:  # noqa: BLE001
            pass
        if controls.get("unattended") and not controls.get("no_backup"):
            # a long run alone: a copy of the save once a real day (backups/)
            try:
                f = _d(state.get("fort"))
                root = (bridge.version or {}).get("df_path")
                # (0.99.13) the folder the save is really in (DF's user folder, not the game's)
                # only when a copy is due: the lookup can walk both save trees
                from dfhack import save_root
                line = backup.maybe((lambda: save_root(root, f.get("save_dir")) or Path(root) / "save")
                                    if root else None, f.get("save_dir"),
                                    fort=f, date=state.get("date"))   # (0.105.0) the pinned fort, never mid-save
                if line:
                    say(f"Backup: {line}")
            except Exception as e:  # noqa: BLE001  (a failed copy never stops the fort)
                say(f"Backup: couldn't copy the save ({e})")
        acting_text = ("acting" if acting else "dry run (watching only)" if not autopilot
                       else why_not or "not acting")
        recent = [f"{short(a['action'])}: {a.get('reason', '')}".rstrip(": ")
                  for a in memory.recent_actions[-5:]][::-1]
        report_status(bridge, {
            "mode": MODES[mode], "acting": acting_text, "date": date_str(state),
            "last": (recent if acting else would[:5] or recent),
            "notes": notes[:2],
            "todo": list(dict.fromkeys(todo))[:10],   # things only the player can do
            "building": [t for t in project_text(state["projects"]).split("; ") if t][:2],
            "ai": (f"AI strategist: {int(bank.balance):,} tokens saved" if backend else None),
            "tokens": ({"saved": int(bank.balance), "total": int(bank.total_used),
                        "today": int(bank.real_day_used) if bank.real_day == date.today().isoformat() else 0}
                       if backend else None),
            "pending": pending,
            "ack": list(decisions.keys()),       # answers seen; the panel forgets them
            "unattended": UNATTENDED,             # (0.104.88) the camera director runs only then
            # (0.104.90) what only the brain knows, for the camera's captions
            "camera": camera_feed(memory) if UNATTENDED else None,
        })
    finally:
        save(key, memory, bank, bridge if to_save else None, state)


STYLE_AREAS = ("halls", "finish", "statues", "materials", "worship")


def _style_choices(memory) -> dict:
    ch = memory.culture.get("choices") if isinstance(memory.culture, dict) else None
    return {a: ch[a] for a in STYLE_AREAS if a in ch} if isinstance(ch, dict) else {}


def _note_adjust(state: dict, memory, journal_entry: dict | None, cfg: dict) -> None:
    """A strategist review that raised a target opens an outcome entry for it."""
    adj = (journal_entry or {}).get("adjust") if isinstance(journal_entry, dict) else None
    for k, kind in (("drink_per_dwarf", "drink_target"), ("meals_per_dwarf", "meal_target")):
        v = (adj or {}).get(k)
        if isinstance(v, (int, float)) and v != cfg.get(k):
            outcomes.open_entry(state, memory, kind, f"{k.replace('_', ' ')} {cfg.get(k)} -> {v}", "strategist",
                                expect="up" if v > cfg.get(k, 0) else "down")


def remember_world(state: dict, memory, events: list[dict], key: str, cfg: dict,
                   learned_now: list[str] | None = None, bridge=None) -> None:
    """Memory, part two: the day's row of numbers, the atlas (survey, registry,
    entrances, where things happened) and the chronicle. Scripts only, no tokens."""
    now = abs_tick(state)
    year = state["date"]["year"]
    if not (memory.chronicle or {}).get("entries"):
        chronicle.add(memory, state, "founded", "the AI overseer began keeping this fort's memory")
    chronicle.rewind(memory, year)                  # an older save: forget what hasn't happened yet
    # (0.104.86) the newest finished season, not how many: memory keeps 24, so
    # once full the count stood still and seasons.csv stopped (Enxah: at y70)
    seasons_before = _newest_season(memory)
    finished = timeline.record(state, memory, events, cfg)
    try:
        pj = _d(state.get("projects"))
        LAST_CYCLE.clear()
        LAST_CYCLE.update({"fort": key, **outcomes.measure(state),
                           # (0.100.1) how long the report froze the game, by section
                           "report_timing": state.get("_timing") if isinstance(state.get("_timing"), dict) else None,
                           "wealth": state.get("wealth") if isinstance(state.get("wealth"), int) else None,
                           "threats": _d(state.get("others_on_map")).get("threats_that_can_reach_dwarves"),
                           "projects_open": len(pj.get("open") or []), "projects_finished": pj.get("finished"),
                           "agenda": (memory.agenda or [])[:3],
                           # the needs most dwarves are distracted by (name: count)
                           "needs": dict(sorted(((k, int(_d(v).get("distracted") or 0))
                                                 for k, v in _d(_d(state.get("needs")).get("needs")).items()),
                                                key=lambda kv: -kv[1])[:5])})
    except Exception:  # noqa: BLE001  (the soak row is only a log)
        pass
    if finished:
        memstore.log_day(key, finished, timeline.FIELDS)
    seasons = memory.timeline.get("seasons") or []
    if _newest_season(memory) != seasons_before:
        memstore.log_seasons(key, seasons, timeline.season_name)
    surveyed = atlas.survey_due(state, memory)
    if surveyed:
        for line in atlas.survey(state, memory):        # (this notes the entrances too)
            say(f"Atlas: {line}")
            chronicle.add(memory, state, "found" if "found" in line else "registry", line)
    else:
        for line in atlas.note_entrances(state, memory):
            say(f"Atlas: {line}")
            chronicle.add(memory, state, "registry", line)
    if surveyed or not masterplan.has_plan(memory) or masterplan.needs_redraw(memory):
        site = survey_site(bridge, memory)
        s = normalize(state)
        if site and "settings" not in s["_errors"]:
            traits = _d(s["settings"].get("traits"))
            for line in masterplan.ensure(state, memory, site, traits,
                                          profile_from(traits, memory.culture or new_history())):
                say(f"Plan: {line}")
                chronicle.add(memory, state, "plan", line)
    for line in atlas.note_registry(state, memory):
        chronicle.add(memory, state, "built", line)
    atlas.note_events(state, memory, events)
    atlas.consolidate(memory, now)
    change = phases.update(state, memory, events)
    if change:
        say(f"Phase: {change}")
        chronicle.add(memory, state, "phase", change)
    for line in defence.judge_sieges(state, memory):
        say(f"Defence: {line}")
        chronicle.add(memory, state, "siege", line)
    for line in masterplan.apply_quirks(memory):
        say(f"Plan: {line}")
        chronicle.add(memory, state, "plan", line)
    for line in learned_now or []:
        if "lesson" in line:
            chronicle.add(memory, state, "learned", line)
    chronicle.consolidate(memory, year)


def world_facts(state: dict, memory) -> dict:
    """Facts from the atlas and the phases that quirks can test: caverns
    reached, citizens killed inside the fort (away from the gates) during a
    siege, and years since the last such death."""
    now = abs_tick(state)
    a = memory.atlas if isinstance(memory.atlas, dict) else {}
    layers = (a.get("survey") or {}).get("layers") or []
    f = {"caverns_reached": sum(1 for l in layers if isinstance(l, dict)
                                and str(l.get("name", "")).startswith("Cavern")
                                and (l.get("found") or l.get("discovered")))}
    spans = phases.siege_spans(memory, now)
    inside = [e for e in a.get("events") or [] if isinstance(e, dict) and e.get("k") == "death"
              and not str(e.get("near") or "").startswith("entrance:")
              and any(s <= (e.get("t") or -1) <= t for s, t in spans)]
    f["deaths_inside_in_siege"] = len(inside)
    # (0.103, site and story quirks) the land and the fort's own hard times
    st = normalize(state)
    bodies = [b for b in _l(_d(st.get("water")).get("bodies")) if isinstance(b, dict)]
    if bodies:
        f["surface_water_tiles"] = sum(int(b.get("tiles") or 0) for b in bodies if b.get("kind") == "surface")
    cr = _d(st.get("crossings"))
    if "crossings" in cr:
        f["crossings_built"] = sum(1 for c in _l(cr.get("mine")) if isinstance(c, dict) and c.get("built"))
        f["crossings_possible"] = len(_l(cr.get("crossings")))
    f["freezes"] = 1 if getattr(memory, "climate_freezes", False) else 0
    om = _d(st.get("others_on_map"))
    if isinstance(om.get("tame_animals"), int):
        f["tame_animals"] = om["tame_animals"]
    dw = _d(st.get("dwarves"))
    if "children" in dw:
        f["children"] = int(dw.get("children") or 0)
    if "legendary" in dw:
        f["legendary"] = int(dw.get("legendary") or 0)
    # (0.103.11) Forge-born and Communal: the forges, magma, beds for everyone
    bl = _d(st.get("buildings"))
    if "workshops" in bl:
        places = {**_d(bl.get("workshops")), **_d(bl.get("furnaces"))}
        f["magma_forges"] = int(places.get("MagmaForge") or 0)
        f["forges"] = int(places.get("MetalsmithsForge") or 0) + f["magma_forges"]
        if isinstance(_d(bl.get("other")).get("Bed"), int) and int(dw.get("total") or 0) >= 10:
            f["beds_per_dwarf"] = round(_d(bl.get("other"))["Bed"] / max(1, int(dw.get("total") or 1)), 2)
    # (0.103.15) Gem-mad and Nobles' Pride
    sk = _d(st.get("stocks"))
    if "rough_gems" in sk or "cut_gems" in sk:
        f["cut_gems"] = int(sk.get("cut_gems") or 0)
        f["gems"] = int(sk.get("rough_gems") or 0) + f["cut_gems"]
    if "workshops" in bl:
        f["jewelers"] = int(_d(bl.get("workshops")).get("Jewelers") or 0)
    if isinstance(st.get("nobles"), list):
        f["nobles"] = len({str(n.get("position")) for n in st["nobles"] if isinstance(n, dict) and n.get("position")})
    stones = [x for x in _l(st.get("stone_types")) if isinstance(x, dict) and isinstance(x.get("count"), (int, float))]
    if stones and sum(x["count"] for x in stones) >= 20:        # (0.103.18) One Stone
        f["top_stone_share"] = round(max(x["count"] for x in stones) / sum(x["count"] for x in stones), 2)
    # (0.103.19) Waste Not: wood and usable stone a dwarf (a poor site)
    sk2 = _d(st.get("stocks"))
    if "wood" in sk2 and "boulders" in sk2 and int(dw.get("total") or 0) >= 10:
        f["materials_pd"] = round((int(sk2.get("wood") or 0) + int(sk2.get("boulders") or 0)) / int(dw["total"]), 1)
    # (0.103.19) Sky-reachers: the share of citizens out under the sky,
    # smoothed over the days (a slow average kept in the fort's culture)
    md = _d(_d(st.get("map")).get("dwarves"))
    if isinstance(md.get("outside"), int) and int(md.get("citizens") or 0) >= 10 and isinstance(memory.culture, dict):
        share = md["outside"] / md["citizens"]
        avg = memory.culture.get("surface_share_avg")
        avg = share if not isinstance(avg, (int, float)) else avg * 0.97 + share * 0.03
        memory.culture["surface_share_avg"] = round(avg, 3)
        f["surface_share"] = round(avg, 2)
    mg = _d(_d(st.get("water")).get("magma"))
    if "tiles" in mg:
        f["magma_tiles"] = int(mg.get("tiles") or 0)
    dead = _d(st.get("dead"))
    if "ghosts" in dead:
        f["ghosts"] = int(dead.get("ghosts") or 0)
    # (0.105.0) the sieges on the game's own record (the grudge list) for Grudge-keepers
    try:
        from planner_world import grudge_facts
        f.update(grudge_facts(st, memory))
    except Exception:  # noqa: BLE001
        pass
    civs = [c for c in _l(_d(st.get("diplomacy")).get("civs")) if isinstance(c, dict)]
    if civs:
        f["goblin_wars"] = sum(1 for c in civs if c.get("race") == "GOBLIN" and str(c.get("relation")) == "War")
        f["elf_peace"] = 1 if any(c.get("race") == "ELF" and str(c.get("relation")) == "Peace" for c in civs) else 0
    dp = _d(st.get("diplomacy"))
    ty = memory.tree_year if isinstance(getattr(memory, "tree_year", None), dict) else {}
    if isinstance(dp.get("trees_removed"), int) and isinstance(dp.get("tree_cap"), int) and dp["tree_cap"] > 0 \
            and isinstance(ty.get("base"), int):
        f["tree_quota_share"] = round((dp["trees_removed"] - ty["base"]) / dp["tree_cap"], 2)
    tl = memory.timeline if isinstance(getattr(memory, "timeline", None), dict) else {}
    dry = [x.get("season") for x in _l(tl.get("seasons")) if isinstance(x, dict)
           and isinstance(_d(x.get("avg")).get("drink_pd"), (int, float)) and _d(x.get("avg"))["drink_pd"] < 0.5]
    # years only from before the seasons kept (a year rolls up seasons still listed)
    kept = [x.get("season") for x in _l(tl.get("seasons")) if isinstance(x, dict) and isinstance(x.get("season"), int)]
    first_year = (min(kept) // 4) if kept else None
    dry_years = [x.get("year") for x in _l(tl.get("years")) if isinstance(x, dict)
                 and (first_year is None or (isinstance(x.get("year"), int) and x["year"] < first_year))
                 and isinstance(_d(x.get("avg")).get("drink_pd"), (int, float)) and _d(x.get("avg"))["drink_pd"] < 0.5]
    f["dry_seasons"] = len(dry) + 2 * len(dry_years)
    done = [x for x in _l(tl.get("seasons")) if isinstance(x, dict) and isinstance(_d(x.get("avg")).get("drink_pd"), (int, float))]
    if done:
        f["drink_pd_season"] = _d(done[-1].get("avg"))["drink_pd"]
    locs = _d(_d(st.get("locations")).get("count"))
    if "locations" in st:
        f["libraries"] = int(locs.get("LIBRARY") or 0)
        if isinstance(memory.atlas, dict):
            if f["libraries"]:
                memory.atlas.setdefault("library_since", now)
            else:
                memory.atlas.pop("library_since", None)
            since = memory.atlas.get("library_since")
            if isinstance(since, int) and since <= now:
                f["library_years"] = (now - since) // TICKS_PER_YEAR
    seasons = [d for d in dry if isinstance(d, int)]
    if seasons:
        f["years_since_dry"] = max(0, (now // 1200 // 84 - max(seasons)) // 4)
    # (kept in the atlas: located events fold into clusters after a year)
    if isinstance(memory.atlas, dict):
        if inside:
            memory.atlas["last_inside_death"] = max(e["t"] for e in inside)
        last = memory.atlas.get("last_inside_death")
        if isinstance(last, int):
            if last > now:
                memory.atlas.pop("last_inside_death", None)    # an older save
            else:
                f["years_since_inside_death"] = (now - last) // TICKS_PER_YEAR
    return f


def survey_site(bridge, memory) -> dict | None:
    """The bridge's survey (the main stairs, soil, the fort's heart), kept with
    the atlas's survey; asked for at most once a season (atlas.survey_due), or
    until the master plan is drawn."""
    sv = (memory.atlas or {}).get("survey") or {}
    site = sv.get("site") if isinstance(sv.get("site"), dict) else None
    fresh = site is not None and site.get("tick") == sv.get("tick")
    # (0.104.82) a survey from before the stairwell count: asked again once
    if fresh and "stairwells" not in site and not site.get("asked_stairwells") and site.get("stairs"):
        fresh = False
    if fresh or bridge is None or not hasattr(bridge, "survey"):
        return site if site and not site.get("error") else None
    def keep(s):
        if isinstance(memory.atlas, dict) and isinstance(memory.atlas.get("survey"), dict):
            memory.atlas["survey"]["site"] = s
    try:
        r = bridge.survey()
    except (BridgeError, DFHackError, OSError, ValueError) as e:
        keep({"tick": sv.get("tick"), "error": str(e)[:200]})   # an older bridge: ask again next season
        return None
    if not isinstance(r, dict) or not r.get("ok"):
        keep({"tick": sv.get("tick"), "error": "the survey failed"})
        return None
    site = {k: r.get(k) for k in ("stairs", "stairwells", "soil", "citizen_elevation", "elevation_offset") if k in r}
    site["tick"] = sv.get("tick")
    if "stairwells" not in site:
        site["asked_stairwells"] = True      # an older bridge: not asked again this season
    keep(site)
    return site


def culture_update(state: dict, memory, events: list[dict], key: str) -> None:
    """History shapes the fort's culture; a changed style starts a new era."""
    if not memory.culture:
        memory.culture = new_history()
    # what you turned down leans the weights engine away from it
    memory.culture["learned"] = learning.engine_bonuses(memory)
    # how each defence design held up in sieges, here and in your other forts
    memory.culture["design"] = defence.engine_bonuses(memory)
    # (0.105.15) a siege for culture is one phases confirmed (3+ invaders),
    # not DF's invasion record of a lone thief
    year = (state.get("date") or {}).get("year")
    seen = [e for e in events if not (isinstance(e, dict) and e.get("kind") == "invasion")]
    seen += [{"kind": "invasion", "year": year}] * phases.take_new_sieges(memory)
    for change in culture_events(memory.culture, seen):
        say(f"Culture: {change}")
        journal({"kind": "culture", "fort": key, "change": change})
        chronicle.add(memory, state, "siege" if "siege" in change else "beast", change)
    s = normalize(state)
    if "settings" in s["_errors"]:
        return
    traits = _d(s["settings"].get("traits"))
    # the fort's own seed: settles close calls the same way every time
    memory.culture.setdefault("seed", key)
    # (0.95) its own leanings (drawn once from the seed) and the site's (read
    # again from each full report), leaning the style engine beyond the sliders
    for change in leanings.update(memory.culture, state):
        say(f"Culture: {change}")
        journal({"kind": "culture", "fort": key, "leaning": change})
    # how often a promising defence design is tried instead of the best-known (Caution)
    memory.culture["explore"] = defence.explore(traits, state["date"]["year"])
    profile = profile_from(traits, memory.culture)
    # remember each area's choice: it's kept until something clearly beats it
    memory.culture["choices"] = {a: c["id"] for a, c in choose_all(traits, memory.culture).items()}
    era = update_eras(memory.culture, profile, state["date"]["year"])
    if era:
        say(f"Culture: a new era begins: {era}")
        journal({"kind": "culture", "fort": key, "era": era, "year": state["date"]["year"]})
        chronicle.add(memory, state, "era", f"a new era began: {era}")
        for line in masterplan.new_era(memory, len(memory.culture.get("eras") or []), profile, traits):
            say(f"Plan: {line}")
            chronicle.add(memory, state, "plan", line)
    stocks = s["stocks"] if "stocks" not in s["_errors"] else None
    for change in update_quirks(memory.culture, traits, stocks, state["date"], world_facts(state, memory)):
        say(f"Culture: {change}")
        journal({"kind": "culture", "fort": key, "quirk": change, "year": state["date"]["year"]})
        chronicle.add(memory, state, "quirk", change)


def push_culture(bridge: Bridge, state: dict, memory) -> None:
    """Copy the culture into the save (for the panel's Culture page), only when
    it changed. Display only; nothing in the game reads it."""
    s = normalize(state)
    if "settings" in s["_errors"] or not memory.culture:
        return
    traits = _d(s["settings"].get("traits"))
    profile = profile_from(traits, memory.culture)
    stones = s.get("stone_types") if isinstance(s.get("stone_types"), list) else []
    stone = pick_stone(stones, profile["palette"])
    payload = {"profile": profile,
               "guide": style_guide(profile, stone and stone.get("name"), memory.culture),
               "stone": stone and stone.get("name"),
               "eras": [{"year": e["year"], "title": e["title"]} for e in memory.culture.get("eras", [])],
               "beasts_slain": len(memory.culture.get("beasts_slain", [])),
               "sieges": memory.culture.get("sieges", 0),
               "choices": [{k: c[k] for k in ("name", "choice", "why", "by_ai", "later")}
                           for c in explain(traits, memory.culture)],
               "quirks": [{k: q[k] for k in ("name", "since", "why", "does", "fade")}
                          for q in describe_quirks(memory.culture)],
               "plan": masterplan.lines(memory),
               "phase": phases.line(memory),
               "effects": temperament.effects(s),       # (0.94) the panel's "Now:" line per slider
               "leanings": leanings.panel(memory.culture)}   # (0.95) its "Leans:" line
    # (0.97.1, B9) a short hash is kept, not the whole payload (it was stored
    # in the memory, and could push the save's memory past its budget)
    fingerprint = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    if fingerprint == memory.culture_pushed:
        return
    try:
        r = bridge.act({"type": "set_culture", "culture": payload})
    except (BridgeError, DFHackError):
        return
    # (also when refused, e.g. by an older bridge: don't ask again every cycle)
    if r.get("ok") or r.get("rejected"):
        memory.culture_pushed = fingerprint


def learned_payload(state: dict, memory) -> dict:
    """What the AI has learned, for the panel (Culture tab, Shift-V)."""
    now = abs_tick(state)
    return {"prefs": [{k: d[k] for k in ("text", "weight", "lesson", "inherited", "how", "effect")}
                      for d in learning.describe(memory, now)][:12],
            "tuned": [{"name": c["name"], "value": c["value"], "default": c["default"], "why": c["why"],
                       "date": c["date"]} for c in calibrate.describe(memory, PLANNER_CONFIG)],
            "verdicts": outcomes.summary_lines(memory, 6),
            "waiting": outcomes.waiting_lines(memory, 4),
            "lessons": (defence.lesson_lines(memory, 3) + outcomes.lessons(memory))[:6],
            "log": learning.log_lines(memory, 6),
            "trends": (timeline.trend_lines(memory, 4) + calibrate.evidence(memory))[:6],
            "places": atlas.notable(memory, 4),
            "story": chronicle.lines(memory, 4)}


def push_learned(bridge: Bridge, state: dict, memory) -> None:
    """Copy what the AI has learned into the save for the panel, only when it changed."""
    payload = learned_payload(state, memory)
    fingerprint = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()   # (B9)
    seen = memory.learning.get("pushed") if isinstance(memory.learning, dict) else None
    if fingerprint == seen:
        return
    try:
        r = bridge.act({"type": "set_learned", "learned": payload})
    except (BridgeError, DFHackError):
        return
    if r.get("ok") or r.get("rejected"):        # (an older bridge refuses it: don't ask every cycle)
        memory.learning["pushed"] = fingerprint


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
               "stop_file": STOP_FILE.exists(), **LAST_CYCLE}
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
        soldiers = int(g.get("soldiers") or 0)
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


def meeting_unattended(args) -> bool:
    """(0.105.0 review) Nobody at the game: --unattended, or run by the keeper
    (brain/keeper.py sets DFAI_PIN for the overseer it starts)."""
    return bool(getattr(args, "unattended", False) or os.environ.get("DFAI_PIN"))


UNATTENDED = False      # (0.104.88) set from --unattended: the in-game camera director runs only then
PRESET: str | None = None   # (0.105.4) --preset NAME (keeper.py --preset): applied once per fort
PRESET_FILE = LOG_DIR / "keeper-preset.json"   # {fort key: {"name", "at"}}: what --preset applied, per fort
PRESET_DONE: set = set()    # fort keys seen this process (asked once per fort, not every cycle)


def preset_due(key: str, name: str, fort_preset) -> str | None:
    """(0.105.4) Why --preset NAME should be applied to this fort now, or None.
    Applied when this fort never had NAME from --preset (logs/keeper-preset.json),
    or when the fort's site data shows no preset at all (an older save, from
    before it was applied). Never over the player's own later choice: once
    applied, a revive or a restart leaves the window's changes alone."""
    rec = load_json(PRESET_FILE, {}).get(key)
    if not isinstance(rec, dict) or rec.get("name") != name:
        return "first time for this fort" if fort_preset != name else None
    if not fort_preset:
        return "the save shows no preset"
    return None


def _site(key: str) -> str:
    return str(key).rpartition("#")[2]


def fort_run(key: str) -> str | None:
    """(0.105.26) This fort's run: the "run" stamp of its site's entries in
    logs/keeper-preset.json (the newest), or None (no preset, or an entry from
    before runs were marked). Clearing the site's entries (the fresh-restart
    checklist) starts a new run when the preset is applied again."""
    site = _site(key)
    runs = [r["run"] for k, r in load_json(PRESET_FILE, {}).items()
            if _site(k) == site and isinstance(r, dict) and isinstance(r.get("run"), str)]
    return max(runs) if runs else None


def note_preset(key: str, name: str) -> None:
    done = load_json(PRESET_FILE, {})
    now = datetime.now().isoformat(timespec="seconds")
    # (0.105.26) the run stamp is set once, when the site has no entry at all
    # (a new fort, or one cleared for a fresh start); a restart, a revive or an
    # autosave's key keeps the site's stamp; an older entry without one stays so
    same = [r for k, r in done.items() if _site(k) == _site(key) and isinstance(r, dict)]
    runs = [r["run"] for r in same if isinstance(r.get("run"), str)]
    run = max(runs) if runs else (None if same else now)
    done[key] = {"name": name, "at": now, **({"run": run} if run else {})}
    try:
        from dfhack import write_atomic
        PRESET_FILE.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(PRESET_FILE, json.dumps(done, indent=1))
    except OSError:
        pass


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
        say(f"Rules: {RULES_REQUEST} couldn't be read ({e}); left for you to fix.")
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
        words = ", ".join(f"{k} {'on' if v.get('new') else 'off'}" for k, v in sorted(ch.items())) or "nothing to change"
        say(f"Rules: set from {RULES_REQUEST}: {words}.")
    else:
        say(f"Rules: {RULES_REQUEST} not applied: {r.get('error')}")
    try:
        done = LOG_DIR / "rules-request.done.json"
        done.write_text(json.dumps({"request": req, "answer": r}, indent=1), encoding="utf-8")
        path.unlink()
    except OSError as e:
        say(f"Rules: applied, but {RULES_REQUEST} couldn't be moved aside ({e}).")


def apply_preset(bridge: Bridge, state: dict, key: str, autopilot: bool) -> None:
    """(0.105.4) --preset NAME: before this fort's first cycle, the preset
    applied to its settings (the bridge's apply_preset, as the window's Load
    preset), when preset_due says so. The cycle then plans with it."""
    name = PRESET
    if not name or key in PRESET_DONE:
        return
    st = _d(state.get("settings"))
    why = preset_due(key, name, st.get("preset"))
    if why is None:
        PRESET_DONE.add(key)
        note_preset(key, name)
        say(f"Preset: {name} already applied to this fort (left as it is: later changes in the window stay).")
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
    note_preset(key, name)
    journal({"kind": "preset", "fort": key, "preset": name, "why": why, "previous": r.get("previous"),
             "traits": traits, "rules": rules})
    if isinstance(r.get("settings"), dict):
        state["settings"] = r["settings"]           # this cycle plans with the preset


def _newest_season(memory) -> int | None:
    """The newest finished season the memory's timeline holds, or None."""
    ss = [s.get("season") for s in ((getattr(memory, "timeline", None) or {}).get("seasons") or [])
          if isinstance(s, dict) and isinstance(s.get("season"), int)]
    return max(ss) if ss else None


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
    _tokens.DAY_FILE = LOG_DIR / "tokens-today.json"     # (0.99.1, B10) the daily cap across all forts

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


def _run(args) -> int:
    """The main loop (main() above parses the command line and takes the lock)."""
    mode = "AUTOPILOT" if args.autopilot else "DRY RUN (nothing will be changed)"
    say(f"Overseer starting in {mode}. Ctrl-C to quit; create a file named STOP to halt actions.")
    backend = make_backend() if args.ai else None
    if backend and not args.autopilot:
        say("Note: in a dry run the AI still reviews (and uses tokens); its actions are only shown.")

    bridge = None
    last_plan_tick = None
    trade_cycles, trade_cycle_at = 0, float("-inf")   # cycles run while the trade screen is open
    trade_open_since, trade_close_tried = None, float("-inf")   # (0.100.1) a screen left open
    last_full_tick = 0
    waiting_msg = None
    was_halted = False
    seen_decisions: dict = {}
    problems_in_a_row = 0
    paused_since = None          # (unattended) when the game was first seen paused
    unpauses = 0
    fps_samples: list = []       # (time, fps) while the game runs, the last 10 minutes
    fps_low = None
    last_date = None             # (unattended) the game's date, and since when it hasn't moved
    date_since = 0.0
    held_date, held_since, meeting_tried = None, 0.0, float("-inf")   # (0.104.0) paused or not: for meetings
    answer_tried = float("-inf")  # (0.105.0) the last try at answering the meeting screen
    answer_dead = None           # (0.105.0 review) held_since of a meeting where a press changed nothing: no more presses
    answer_cant = None           # (0.105.24) held_since of a meeting the AI can't answer (no button, a dead press)
    stall_said = float("-inf")
    stall_wait = STALL_AFTER_S   # the wait before the next try at the same stall (doubles, up to 10 min)
    quieted = False              # (unattended) announcements told not to pause or pop up, this fort
    soak_at = float("-inf")      # (unattended) when the last soak row was written
    saving_at = float("-inf")    # (0.104.138) when the game last said it was saving
    season_end = False           # (0.104.138) the last date seen was a season's last days (DF autosaves then)
    save_said = False            # (0.104.138) "DF is saving" said for this silence
    quiet_wait = 10              # (0.104.138) the wait after an unanswered call while DF saves (10 -> 60 s)
    while True:
        heartbeat()
        try:
            if bridge is None:
                bridge = Bridge()
                info = bridge.handshake()
                say(f"Connected: bridge {info['bridge_version']}, DFHack {info['dfhack_version']}")
            if args.once:
                one_cycle(bridge, args.autopilot, backend)
                return 0
            st = bridge.status()
            if st.get("saving"):
                saving_at = time.time()
            _d0 = _d(st.get("date"))
            season_end = isinstance(_d0.get("tick"), int) and (_d0["tick"] // 33600) % 3 == 2 and int(_d0.get("day") or 0) >= 26
            save_said, quiet_wait = False, 10
            controls = {"halted": st.get("halted") is True, "decisions": st.get("decisions") or {}}
            if st.get("in_fort") and controls["halted"] != was_halted:
                say("Halted in the game (Ctrl-Shift-H): watching only, changing nothing."
                    if controls["halted"] else "Resumed in the game.")
                was_halted = controls["halted"]
            # An answer starts a cycle right away, once (the cycle acknowledges it;
            # if that cycle can't, don't spin on the same answers).
            answered = bool(controls["decisions"]) and controls["decisions"] != seen_decisions
            seen_decisions = dict(controls["decisions"])
            # (unattended) the game's speed, measured while it runs
            nowt = time.monotonic()
            date_now = (st.get("date") or {}).get("tick"), (st.get("date") or {}).get("year")
            if date_now != last_date or st.get("paused") or not st.get("in_fort") or st.get("trade_open"):
                last_date, date_since = date_now, nowt
                stall_said, stall_wait = float("-inf"), STALL_AFTER_S     # time moves: a new stall starts afresh
            if not st.get("in_fort"):
                quieted = False
            if (args.unattended and args.autopilot and st.get("in_fort") and not quieted
                    and not controls["halted"]):
                quieted = True
                r = bridge.act({"type": "quiet_announcements"})
                say(f"Unattended: announcements no longer pause the game or open a box ({r.get('pausing', 0)} "
                    f"paused, {r.get('boxes', 0)} opened one; until DF is restarted)." if r.get("ok")
                    else f"Unattended: couldn't quiet the announcements ({r.get('error')}); popups are "
                         "taken off when they stall the game.")
            # (0.104.0) DF's meeting screen holds the game until someone answers
            # (paused or not): unattended, it is left after MEETING_CLOSE_S
            if date_now != held_date or not st.get("in_fort"):
                held_date, held_since = date_now, nowt
            # (0.105.0, 12b) before that, answered with the AI's defaults (the
            # tribute by the Rules tab), when the AI knows the screen's buttons
            # (0.105.0 review) only when the run is unattended (--unattended, or the
            # keeper's DFAI_PIN): a player at the screen answers it; and after a press
            # that changed nothing, no more presses for that meeting
            if (args.autopilot and meeting_unattended(args) and st.get("in_fort") and st.get("meeting")
                    and not controls["halted"] and answer_dead != held_since
                    and not STOP_FILE.exists() and MEETING_ANSWER_S <= nowt - held_since < MEETING_CLOSE_S and nowt - answer_tried >= 30):
                answer_tried = nowt
                try:
                    r = bridge.act({"type": "answer_meeting"})
                    if r.get("pressed") and not r.get("ok"):
                        answer_dead = held_since
                    if r.get("needs_button") or (r.get("pressed") and not r.get("ok")):
                        answer_cant = held_since
                    if r.get("pressed") or r.get("needs_button") or r.get("left_to_player"):
                        say("DF's meeting screen: " + (f"answered {r.get('answer')} ({r.get('why') or r.get('topic')})"
                                                       if r.get("ok") else str(r.get("error"))))
                except (BridgeError, DFHackError):
                    pass
            if (args.unattended and args.autopilot and st.get("in_fort") and not controls["halted"]
                    and not STOP_FILE.exists() and nowt - held_since >= meeting_leave_after(answer_cant == held_since)
                    and nowt - meeting_tried >= MEETING_CLOSE_S):
                meeting_tried = nowt
                try:
                    r = bridge.act({"type": "close_meeting"})
                    if r.get("screen"):
                        say(f"Unattended: DF's meeting screen held the game for {int(nowt - held_since)} s with "
                            "nobody to answer: " + ("left it (the meeting ends without an agreement)."
                                                    if r.get("ok") else f"couldn't leave it ({r.get('error')})."))
                except (BridgeError, DFHackError):
                    pass
            stalled = nowt - date_since >= STALL_AFTER_S
            if st.get("in_fort") and not st.get("paused") and not stalled and isinstance(st.get("fps"), (int, float)):
                fps_samples.append((nowt, st["fps"]))
            if stalled and st.get("saving"):
                # (0.104.138) DF is saving itself: time stands still for minutes
                # (2-10 on Teacheroar), nothing to take off or say
                pass
            elif (stalled and args.unattended and args.autopilot and not controls["halted"]
                    and not STOP_FILE.exists() and nowt - stall_said >= stall_wait):
                # running, but time stands still: DF waits on a popup. Take it off
                # (again a minute later if that didn't help, then 2, 4, 8, 10 minutes)
                if stall_said != float("-inf"):
                    stall_wait = min(600.0, stall_wait * 2)
                stall_said = nowt
                r = bridge.act({"type": "unpause", "unstick": True})
                n = r.get("popups_cleared", 0)
                if n:
                    say(f"Unattended: time stood still for {int(nowt - date_since)} s with the game running: "
                        f"{n} popup(s) waiting for a click taken off.")
                else:
                    say(f"Unattended: time stood still for {int(nowt - date_since)} s with the game running and no "
                        "popup to take off (a save, or a window only a click closes); if this repeats every "
                        "10 minutes, the game needs a click from you."
                        + ("" if r.get("ok") else f" ({r.get('error')})"))
            fps_samples = [x for x in fps_samples if nowt - x[0] <= FPS_WINDOW_S]
            fps_low = fps_state(fps_samples, fps_low)
            if args.unattended and nowt - soak_at >= SOAK_EVERY_S:
                soak_at = nowt
                write_soak(st, fps_samples, fps_low, unpauses, int(nowt - date_since), controls["halted"])
            controls["fps"] = fps_samples[-1][1] if fps_samples else None
            controls["fps_low"] = fps_low if args.unattended else None
            controls["unattended"] = args.unattended
            controls["save_seasons"] = args.save_seasons
            if (args.unattended and args.autopilot and st.get("in_fort") and st.get("paused")
                    and not controls["halted"] and not STOP_FILE.exists()):
                paused_since = paused_since or nowt
                if nowt - paused_since >= UNPAUSE_AFTER_S:
                    r = bridge.act({"type": "unpause"})
                    paused_since = None
                    if r.get("ok"):
                        unpauses += 1
                        say(f"Unattended: the game had paused itself; unpaused it ({unpauses} so far).")
                    else:
                        say(f"Unattended: couldn't unpause: {r.get('error')}")
            else:
                paused_since = None
            if not st.get("in_fort"):
                msg = "Waiting for a fortress to be loaded..."
            elif st.get("paused") and not answered:
                msg = ("Game is paused; unpausing it in 30 s (unattended)." if args.unattended and args.autopilot
                       and not controls["halted"] else "Game is paused; planning resumes when it runs.")
            else:
                msg = None
                now = st["date"]["year"] * TICKS_PER_YEAR + st["date"]["tick"]
                # (0.104.0) while the game runs slowly the full report (the bridge's
                # heaviest work, the game paused while it's built) comes every 2 days
                every = PLAN_EVERY_TICKS * (SLOW_PLAN_FACTOR if fps_low and args.unattended else 1)
                daily = (last_plan_tick is None or now < last_plan_tick
                         or now - last_full_tick >= every)
                # DF's trade screen holds time still: a few cycles while it's open
                # (the deal, the press), each a few seconds apart; none once it shuts
                trade_now = False
                if st.get("trade_open") and args.autopilot:
                    if trade_open_since is None:
                        trade_open_since = nowt
                    if trade_cycles < TRADE_CYCLES_MAX and nowt - trade_cycle_at >= TRADE_CYCLE_S:
                        trade_now, trade_cycles, trade_cycle_at = True, trade_cycles + 1, nowt
                    elif (args.unattended and trade_cycles >= TRADE_CYCLES_MAX and not controls["halted"]
                          and nowt - trade_open_since >= TRADE_STUCK_S and nowt - trade_close_tried >= TRADE_STUCK_S):
                        # (0.100.1) time stands still while the screen is open, so it
                        # can't change by itself: the AI's own screen is closed after
                        # 3 minutes; any screen after 15 (nobody is at the game)
                        trade_close_tried = nowt
                        force = nowt - trade_open_since >= TRADE_FORCE_S
                        try:
                            r = bridge.act({"type": "close_trade", "force": force})
                            say("Unattended: the trade screen stood open for "
                                f"{int(nowt - trade_open_since)} s with nothing left to do: "
                                + ("closed it." if r.get("ok") else f"couldn't close it ({r.get('error')})."))
                        except (BridgeError, DFHackError) as e:
                            say(f"Unattended: the trade screen stood open and couldn't be closed: {e}")
                else:
                    trade_cycles, trade_open_since, trade_close_tried = 0, None, float("-inf")
                due = (daily or trade_now
                       or answered     # you answered a question in the game: act on it now
                       or (st.get("events_waiting", 0) > 0 and now - last_plan_tick >= EVENT_CYCLE_MIN_TICKS))
                if due:
                    last_plan_tick = now      # set first: a failed cycle isn't retried at once
                    if daily:
                        last_full_tick = now
                    # between days, the small pulse report (the rest from today's full one)
                    one_cycle(bridge, args.autopilot, backend, controls,
                              tier="daily" if daily or trade_now else "pulse")
            if msg and msg != waiting_msg:
                say(msg)
            waiting_msg = msg
            problems_in_a_row = 0
        except GameNotRunning:
            if args.once:
                say("Dwarf Fortress isn't running (or DFHack isn't loaded).")
                return 1
            if waiting_msg != "not running":
                say("Dwarf Fortress isn't running. Waiting for it...")
            waiting_msg = "not running"
            bridge = None
            time.sleep(10)
            continue
        except (DFHackError, BridgeError) as e:
            if args.once:
                say(f"Problem talking to the game: {e}. Retrying in 10 s.")
                return 1
            # (0.104.138) an unanswered call while DF autosaves (it said it was
            # saving lately, or the season is ending) is the save, not a fault:
            # said once, and asked again less often (10 -> 20 -> 40 -> 60 s)
            if "did not answer" in str(e) and (time.time() - saving_at < 900 or season_end):
                if not save_said:
                    say("DF is saving itself (the season's autosave): the game doesn't answer until it's done.")
                    save_said = True
                bridge = None
                time.sleep(quiet_wait)
                quiet_wait = min(60, quiet_wait * 2)
                continue
            say(f"Problem talking to the game: {e}. Retrying in 10 s.")
            bridge = None
            time.sleep(10)
            continue
        except KeyboardInterrupt:
            say("Overseer stopped.")
            return 0
        except Exception as e:  # noqa: BLE001 - a bug or odd report: log it, keep the overseer alive
            problems_in_a_row += 1
            say(f"Unexpected problem: {type(e).__name__}: {e} (details in logs/overseer-errors.log)")
            LOG_DIR.mkdir(exist_ok=True)
            memstore.cap_file(LOG_DIR / "overseer-errors.log", ERRORS_MAX_BYTES)
            with (LOG_DIR / "overseer-errors.log").open("a", encoding="utf-8") as f:
                f.write(f"--- {datetime.now().isoformat(timespec='seconds')}\n{traceback.format_exc()}\n")
            if args.once or problems_in_a_row >= 5:
                say("Stopping after repeated problems." if not args.once else "Stopping.")
                return 1
            time.sleep(10)
            continue
        try:
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            say("Overseer stopped.")
            return 0


if __name__ == "__main__":
    sys.exit(main())
