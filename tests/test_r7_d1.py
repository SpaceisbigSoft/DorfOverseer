"""(r7 d1) brain/overseer.py split by theme into parts under 60 KB:

    overseer_words.py   short / SHORT_WORDS, the big moves, answer ids, the camera feed, event lines
    overseer_cycle.py   one_cycle and its guarded steps
    overseer_world.py   remember_world, the world facts, the culture and learned pushes
    overseer_loop.py    _run (the main loop) and its timings

overseer.py re-exports every name it had; the parts look up what they use from
overseer at call time (so a patch of overseer.say, .plan, .Bridge, ... holds).
This proves:

- overseer exposes exactly the names it had at 6298b4a (dir());
- each moved name is the part's own object, and the parts' forwarders reach
  overseer's current attribute (a patch too);
- every file is under 60 KB;
- the modules import cleanly in a fresh interpreter in any order, and run as
  the main script overseer binds the parts to itself (no second copy).

    python tests/test_r7_d1.py
"""

from __future__ import annotations

import itertools
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from py_parts import PY_SPLIT, py_family_src  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import overseer  # noqa: E402
import overseer_cycle  # noqa: E402
import overseer_loop  # noqa: E402
import overseer_words  # noqa: E402
import overseer_world  # noqa: E402

BRAIN = ROOT / "brain"
PARTS = {"overseer_words": overseer_words, "overseer_cycle": overseer_cycle, "overseer_world": overseer_world,
         "overseer_loop": overseer_loop}
PRIVATE = {"overseer_words": ("_CAMERA_LEVELS", "_victim_mood"),
           "overseer_cycle": ("_calibrate_step", "_outcomes_step"),
           "overseer_world": ("_style_choices", "_note_adjust", "_newest_season"),
           "overseer_loop": ("_run",)}
LIMIT = 60 * 1024

# sorted(dir(overseer)) at 6298b4a
NAMES_6298B4A = (
    "ADJUST_LASTS_TICKS", "BIG_MOVES", "Bridge", "BridgeError", "CAMERA_QUIET", "CLEANUP_ACTIONS", "DECLINE_DAYS",
    "DFHackError", "ERRORS_MAX_BYTES", "EVENT_CYCLE_MIN_TICKS", "FAILED_CYCLES_KEY", "FAILED_MOOD_WORDS",
    "FPS_CLEAR", "FPS_CLEAR_SHARE", "FPS_FLOOR", "FPS_FLOOR_SHARE", "FPS_PEAK", "FPS_WINDOW_S",
    "GEAR_PROBE_EVERY_TICKS", "GameNotRunning", "HEARTBEAT", "HELD_BEFORE_SAVE", "ID_KEYS", "JOURNAL",
    "LAST_CYCLE", "LAST_FORT", "LAST_FULL", "LAST_GEAR_PROBE", "LAST_MEMORY_SAVE", "LAST_POSTS", "LOG_DIR",
    "MEETING_ANSWER_S", "MEETING_CLOSE_S", "MEETING_GIVEUP_S", "MEMORY_CACHE", "MEMORY_KINDS_PER_CALL",
    "MEMORY_REREAD_GAP", "MEMORY_SAVE_EVERY_TICKS", "MEMORY_SAVE_LEFT", "MODES", "Memory", "NEEDS_YOU",
    "PERF_LAST", "PERF_METER", "PIN_RETRY_S", "PIN_SEEN", "PLANNER_CONFIG", "PLAN_EVERY_TICKS", "POLL_SECONDS",
    "PRESET", "PRESET_DONE", "PRESET_FILE", "PRINTED", "PROJECT_ROOT", "Path", "QUIET_TOPICS", "RULES_REQUEST",
    "SEASON_END_TICKS", "SEASON_TICKS", "SHADOW_WORDS", "SHORT_WORDS", "SLOW_PLAN_FACTOR", "SOAK", "SOAK_EVERY_S",
    "SOAK_MAX_BYTES", "STALL_AFTER_S", "STATES_KEPT", "STATUS_REFRESH_S", "STATUS_SENT", "STOP_FILE",
    "STYLE_AREAS", "THROTTLE_MEMORY_SAVE", "TICKS_PER_YEAR", "TRADE_CYCLES_MAX", "TRADE_CYCLE_S", "TRADE_FORCE_S",
    "TRADE_STUCK_S", "TokenBank", "UNATTENDED", "UNPAUSE_AFTER_S", "WARNED", "WORLD_CLOSE_S", "_CAMERA_LEVELS",
    "__annotations__", "__builtins__", "__cached__", "__doc__", "__file__", "__loader__", "__name__",
    "__package__", "__spec__", "_calibrate_step", "_d", "_folder_of", "_l", "_leave_open", "_log_error",
    "_newest_season", "_note_adjust", "_onoff", "_outcomes_step", "_run", "_season_order", "_shape", "_site",
    "_style_choices", "_victim_mood", "abs_tick", "acknowledged", "annotations", "apply_preset", "argparse",
    "atlas", "backup", "calibrate", "camera_feed", "check_pin", "choose_all", "chronicle", "cleanup_journal",
    "cleanup_words", "crisis", "culture_events", "culture_update", "cycle_step", "date", "date_str", "datetime",
    "death_words", "defence", "defer_act", "describe_quirks", "design_due", "design_switch", "effective_config",
    "expire_adjustments", "explain", "fallen", "fallen_probe", "floor_action", "floor_forget_sent",
    "floor_journal_hint", "floor_outcome", "flush_held", "folder_lock", "fort_key", "fort_run", "fps_state",
    "get_state", "guard_fail", "guard_lines", "guard_ok", "hashlib", "health_check", "heartbeat",
    "hold_review_proposals", "is_big", "journal", "journal_event", "journal_meeting", "json", "keep_state",
    "later_seasons", "leanings", "learned_payload", "learning", "ledger", "limit_exempt", "load", "load_json",
    "main", "make_backend", "masterplan", "maybe_review", "maybe_tell", "meeting_entry", "meeting_leave_after",
    "meeting_open_due", "meeting_open_said", "meeting_reopen_wait", "meeting_report_lines", "meeting_unattended",
    "memory_save_due", "memstore", "mission_journal", "mood_journal", "new_history", "normalize",
    "not_on_floor_words", "note_cycle", "note_events", "note_failed_cycles", "note_heists", "note_intrusions",
    "note_perf", "note_preset", "note_tantrum_book", "note_tantrums", "note_thief_targets", "one_cycle", "os",
    "outcomes", "perf", "phases", "pick_stone", "pin_hold", "plan", "planner_stuck", "preset_due", "probe_gear",
    "probe_posts", "profile_from", "project_text", "proposal_id", "push_culture", "push_learned", "re", "record",
    "recovery_journal", "remember_world", "report", "report_status", "rests", "rules_request", "runid", "save",
    "say", "season_mod", "seed_squads_made", "seen_ledger", "select", "set_aside", "shadow_on",
    "shop_level_action", "short", "show_changed", "slow_factor", "state_run", "style_guide", "survey_site", "sys",
    "temperament", "thirst_journal", "time", "timeline", "traceback", "update_eras", "update_quirks",
    "world_facts", "world_leave_due", "write_ledger", "write_soak",
)


@test("overseer exposes exactly the names it had at 6298b4a")
def _():
    now = set(dir(overseer))
    assert now == set(NAMES_6298B4A), (sorted(now - set(NAMES_6298B4A)), sorted(set(NAMES_6298B4A) - now))


@test("each moved name is the part's own object (public via __all__, the private ones imported by name)")
def _():
    seen = set()
    for p, mod in PARTS.items():
        names = list(mod.__all__) + list(PRIVATE[p])
        assert names, p
        for n in names:
            assert n not in seen, n
            seen.add(n)
            assert n in NAMES_6298B4A, (p, n)
            assert getattr(overseer, n) is getattr(mod, n), (p, n)
            obj = getattr(mod, n)
            if callable(obj) and hasattr(obj, "__module__"):
                assert obj.__module__ == p, (p, n, obj.__module__)
    # moved functions are defined in their part, not forwarded
    assert overseer.one_cycle.__module__ == "overseer_cycle" and overseer._run.__module__ == "overseer_loop"
    assert overseer.short.__module__ == "overseer_words" and overseer.remember_world.__module__ == "overseer_world"


@test("the parts' forwarders reach overseer's attribute at call time: a patch there holds")
def _():
    for p in ("overseer_cycle", "overseer_world", "overseer_loop"):
        assert PARTS[p]._ov is overseer, p
    said = []
    real = overseer.say
    overseer.say = said.append
    try:
        out = overseer.cycle_step(overseer.Memory(), {"date": {"year": 1, "tick": 0}}, "x",
                                  lambda: 1 / 0, default="d")
    finally:
        overseer.say = real
    assert out == "d" and said and said[0].startswith("Step x failed (ZeroDivisionError"), said
    calls = []
    real_oc = overseer.one_cycle
    overseer.one_cycle = lambda *a, **k: calls.append(a)
    try:
        overseer_loop.one_cycle(1, 2)
    finally:
        overseer.one_cycle = real_oc
    assert calls == [(1, 2)]
    for p in ("overseer_cycle", "overseer_world", "overseer_loop"):
        mod = PARTS[p]
        for n, v in vars(mod).items():
            if getattr(v, "__qualname__", None) == n and getattr(v, "__module__", None) == p \
                    and n not in mod.__all__ and n not in PRIVATE[p] and n != "_late":
                assert hasattr(overseer, n) and getattr(overseer, n) is not v, (p, n)   # a forwarder to overseer's


@test("overseer.py and each part are under 60 KB")
def _():
    for p in ["overseer"] + list(PARTS):
        n = (BRAIN / (p + ".py")).stat().st_size
        assert n < LIMIT, (p, n)


@test("py_family_src puts each part back in place of its import line")
def _():
    src = py_family_src("overseer")
    assert PY_SPLIT["overseer"] == tuple(PARTS)
    for p in PARTS:
        assert f"from {p} import *" not in src
        assert (BRAIN / (p + ".py")).read_text(encoding="utf-8") in src
    assert src.index("def one_cycle(") < src.index("def remember_world(") < src.index("def main() -> int:") \
        < src.index("def _run(")


def fresh(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                          cwd=str(ROOT))


@test("the modules import cleanly in a fresh interpreter in any order")
def _():
    mods = ["overseer"] + list(PARTS)
    orders = [list(o) for o in itertools.permutations(mods)]
    orders = orders[::len(orders) // 12] + [mods[::-1]]       # a spread of the 120 orders, and the reverse
    for o in orders:
        code = (f"import sys; sys.path.insert(0, {str(BRAIN)!r})\n"
                + "".join(f"import {m}\n" for m in o)
                + "for p in " + repr(list(PARTS)) + ":\n"
                  "    m = sys.modules[p]\n"
                  "    assert getattr(m, '_ov', overseer) is overseer, p\n"
                  "    for n in m.__all__: assert getattr(overseer, n) is getattr(m, n), (p, n)\n"
                  f"assert sorted(dir(overseer)) == {sorted(NAMES_6298B4A)!r}\n"
                  "print('ok')\n")
        r = fresh(code)
        assert r.returncode == 0 and r.stdout.strip().endswith("ok"), (o, r.stdout[-500:], r.stderr[-1500:])


@test("run as the main script, overseer binds the parts to itself (no second copy imported)")
def _():
    code = (f"import runpy, sys; sys.path.insert(0, {str(BRAIN)!r}); sys.argv = ['overseer.py', '--help']\n"
            "try:\n"
            f"    runpy.run_path({str(BRAIN / 'overseer.py')!r}, run_name='__main__')\n"
            "except SystemExit:\n"
            "    pass\n"
            "assert 'overseer' not in sys.modules, 'a second copy'\n"
            "for p in ('overseer_cycle', 'overseer_world', 'overseer_loop'):\n"
            "    assert sys.modules[p]._ov.__name__ == '__main__', p\n"
            "    assert sys.modules[p]._ov.one_cycle is sys.modules['overseer_cycle'].one_cycle\n"
            "print('ok')\n")
    r = fresh(code)
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), (r.stdout[-500:], r.stderr[-1500:])


finish()
