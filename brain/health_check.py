"""The unattended run's check: what a long run alone got wrong, in one page.

    python brain\\health_check.py               the last 24 real hours, with the in-game self-test
    python brain\\health_check.py --hours 6 --no-selftest

The keeper runs it after each daily copy of the save (backups/last.json
changes) and once a real day besides, and writes its short form to its log
("Check: ..."). The whole page is logs/health-check.txt, the flags
logs/health-check.json. No tokens, and it changes nothing in the game.

It flags:
- the self-test's failures (brain/selftest.py, run as its own process);
- loops: the same action again and again (per game year, not per real hour:
  a fast game does more in an hour);
- the same refusal repeating (the game keeps saying no for the same reason);
- churn: work orders placed and cancelled as stuck in turn; soldiers drafted
  and released in turn;
- Needs you lines and "rule X failed" notes that never clear (the overseer
  keeps them in logs/standing.json: when each was first and last shown);
- the keeper's own trouble: restarts, Python errors, revive problems;
- the game slowing down (FPS from the soak rows) and the report sections
  that cost the most;
- (0.105.45) things stuck "in progress": the AI's own things past their
  timeout without progress (the stuck sweep's count in the soak rows), a
  flag when some stay past it over the last STUCK_ROWS rows;
- (0.105.46) what of the new versions the game has shown: the seen ledger
  (brain/seen.py, logs/seen-ledger.md) in counts, and a flag for a report
  section returning an error;
- housekeeping: old test saves and backups of forts no longer played (old
  backup copies of those are thinned to the newest; game saves are only
  listed, deleting them is yours).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from util import load_json  # noqa: E402
from util import YEAR_TICKS as TICKS_PER_YEAR  # noqa: E402
LOG_DIR = Path(os.environ.get("DFAI_LOG_DIR") or ROOT / "logs")
STANDING = LOG_DIR / "standing.json"
REPORT = LOG_DIR / "health-check.txt"
FLAGS = LOG_DIR / "health-check.json"

TICKS_PER_DAY = 1200

# thresholds
LOOP_MIN = 12                 # the same action at least this often in the window ...
LOOP_PER_YEAR = 24            # ... and this often per game year: a loop
LOOP_EXPECTED = {"join_levels", "scan_entrances", "dismiss_alerts", "survey_water", "cistern_step", "open_trade",
                 "trade_deal", "close_trade", "call_trader", "unpause"}
REFUSAL_MIN = 5               # the same refusal (same rule, same action, same reason) this often ...
REFUSAL_PER_YEAR = 6          # ... and this often per game year (the planner's back-off allows fewer)
CHURN_MIN = 3                 # placed and cancelled (drafted and released) each this often
SQUAD_CHURN_PER_YEAR = 6      # soldiers drafted and released, each this often a game year
STANDING_HOURS = 12           # a Needs you or failure note shown this long (real hours) ...
STANDING_DAYS = 28            # ... or this many game days: it never clears
FPS_LOW = 40                  # the run's late FPS median under this: flagged
FPS_DROP = 0.3                # or fallen this share from the run's early median
SECTION_SLOW_MS = 150         # a report section whose median build time is over this
OLD_SAVE_DAYS = 14            # test saves and other forts' backups untouched this long
STUCK_ROWS = 12               # (0.105.45) things past their timeout in each of the last rows (2 real hours): flagged
TEST_SAVE = re.compile(r"^(AI Run|AI Test)\b|test", re.I)

FAIL_NOTE = re.compile(r"^(rule \w+ failed|skipped rules that need report section)")


def _shape(text: str) -> str:
    """A line with its numbers taken out (counts and countdowns tick along)."""
    return re.sub(r"\d+", "#", str(text))[:160]


def _write_atomic(path: Path, text: str) -> None:
    try:
        from dfhack import write_atomic
        write_atomic(path, text)
    except Exception:  # noqa: BLE001
        try:
            path.write_text(text, encoding="utf-8")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# standing lines (written by the overseer each cycle)
# ---------------------------------------------------------------------------

_STANDING_CACHE: dict = {"data": None, "written": 0.0, "shapes": None}
STANDING_WRITE_S = 300        # the file is rewritten at least this often while lines stand
STANDING_MAX = 60             # lines kept per fort
STANDING_FORTS = 10           # forts kept


def _load_standing(path: Path) -> dict:
    return load_json(path, {})


def track_standing(fort: str, todo: list, notes: list, tick: int | None,
                   now: float | None = None, path: Path | None = None) -> None:
    """Called by the overseer each full cycle: the Needs you lines and the
    "rule X failed" notes now showing, with when each was first and last seen
    (real time and game tick). A line no longer showing is dropped. Never
    raises (it's only a log)."""
    try:
        path = path or STANDING
        now = time.time() if now is None else now
        if _STANDING_CACHE["data"] is None or _STANDING_CACHE.get("path") != str(path):
            _STANDING_CACHE.update(data=_load_standing(path), path=str(path), written=0.0, shapes=None)
        data = _STANDING_CACHE["data"]
        old = data.get(fort) if isinstance(data.get(fort), dict) else {}
        lines = [("needs_you", str(t)) for t in todo or []]
        lines += [("failed", str(n)) for n in notes or [] if FAIL_NOTE.match(str(n))]
        cur: dict = {}
        for kind, text in lines[:STANDING_MAX]:
            sh = _shape(text)
            e = old.get(sh) if isinstance(old.get(sh), dict) else None
            if e is None:
                e = {"kind": kind, "first": now, "first_tick": tick}
            e.update(text=text[:300], last=now, last_tick=tick)
            cur[sh] = e
        data[fort] = cur
        # forts: the most recently seen kept
        if len(data) > STANDING_FORTS:
            def seen(f):
                v = data.get(f) or {}
                return max([e.get("last") or 0 for e in v.values() if isinstance(e, dict)] or [0])
            for f in sorted(data, key=seen)[:len(data) - STANDING_FORTS]:
                if f != fort:
                    data.pop(f, None)
        shapes = (fort, tuple(sorted(cur)))
        if shapes != _STANDING_CACHE["shapes"] or now - _STANDING_CACHE["written"] >= STANDING_WRITE_S:
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(path, json.dumps(data, ensure_ascii=False, indent=1))
            _STANDING_CACHE.update(written=now, shapes=shapes)
    except Exception:  # noqa: BLE001  (a log never stops the fort)
        pass


def standing_flags(data: dict, now: float | None = None) -> list[str]:
    """Lines still showing at the fort's last cycle that have stood for
    STANDING_HOURS real hours or STANDING_DAYS game days."""
    now = time.time() if now is None else now
    out = []
    for fort, lines in (data or {}).items():
        if not isinstance(lines, dict) or not lines:
            continue
        newest = max((e.get("last") or 0) for e in lines.values() if isinstance(e, dict))
        if now - newest > 2 * 3600:
            continue                          # a fort not run lately: its lines are history
        for e in lines.values():
            if not isinstance(e, dict) or (e.get("last") or 0) < newest - 600:
                continue
            hours = ((e.get("last") or 0) - (e.get("first") or 0)) / 3600
            ft, lt = e.get("first_tick"), e.get("last_tick")
            days = (lt - ft) / TICKS_PER_DAY if isinstance(ft, int) and isinstance(lt, int) and lt >= ft else 0
            if hours >= STANDING_HOURS or days >= STANDING_DAYS:
                what = "Needs you" if e.get("kind") == "needs_you" else "a failing rule"
                out.append(f"{what} that never clears ({fort}, {hours:.0f} h, {days:.0f} game days): "
                           f"{str(e.get('text'))[:200]}")
    return out


# ---------------------------------------------------------------------------
# the forts' journals: loops, refusals, churn
# ---------------------------------------------------------------------------

def _gtick(e: dict) -> int | None:
    d = e.get("date")
    if isinstance(d, dict) and isinstance(d.get("year"), int) and isinstance(d.get("tick"), int):
        return d["year"] * TICKS_PER_YEAR + d["tick"]
    return None


ORDER_OF = re.compile(r"of the AI's (\w+) orders")


def journal_flags(entries) -> tuple[list[str], list[str]]:
    """(flags, plain lines) from the journals' decisions."""
    import run_summary
    done, refused, why = Counter(), Counter(), {}
    span: dict = {}
    placed, cancelled = Counter(), Counter()
    drafted, released = 0, 0
    n = 0
    for e in entries:
        if e.get("mode") not in (None, "autopilot"):
            continue
        n += 1
        a = e.get("action") if isinstance(e.get("action"), dict) else {}
        r = e.get("result") if isinstance(e.get("result"), dict) else {}
        key = (str(e.get("rule")), run_summary._what(a))
        g = _gtick(e)
        fort = str(e.get("fort"))
        if g is not None:
            lo, hi = span.get(fort, (g, g))
            span[fort] = (min(lo, g), max(hi, g))
        if r.get("waiting"):
            continue                      # work under way (a cistern being dug): not the game saying no
        if r.get("ok") is False:
            err = _shape(r.get("error") or "")[:110]
            refused[key + (err,)] += 1
            why[key + (err,)] = str(r.get("error") or "")[:110]
            continue
        done[key] += 1
        t = a.get("type")
        if t == "work_order" and a.get("recipe"):
            placed[str(a["recipe"])] += 1
        elif t == "cancel_work_order":
            m = ORDER_OF.search(str(e.get("reason") or ""))
            if m:
                cancelled[m.group(1)] += 1
        elif t == "squad_fill":
            drafted += 1
        elif t in ("squad_release", "squad_trim"):
            released += 1
    lines = [f"{n} action(s) in the journals"]
    flags = []
    years = sum(max(0, hi - lo) for lo, hi in span.values()) / TICKS_PER_YEAR
    if years > 0:
        lines.append(f"game time covered: {years:.1f} year(s)")
    for (rule, what), c in done.most_common():
        if c < LOOP_MIN or what.split(" ")[0] in LOOP_EXPECTED:
            continue
        per_year = c / years if years > 0.05 else float(c)
        if per_year >= LOOP_PER_YEAR:
            flags.append(f"possible loop: {rule}: {what} x{c} ({per_year:.0f} a game year)")
    for (rule, what, _err), c in refused.most_common():
        per_year = c / years if years > 0.05 else float(c)
        if c >= REFUSAL_MIN and per_year >= REFUSAL_PER_YEAR:
            flags.append(f"the same refusal repeating: {rule}: {what} x{c} ({why[(rule, what, _err)]})")
    for recipe, c in cancelled.most_common():
        if c >= CHURN_MIN and placed[recipe] >= CHURN_MIN:
            flags.append(f"churn: {recipe} ordered {placed[recipe]} times and cancelled as stuck {c} times")
    if (drafted >= CHURN_MIN and released >= CHURN_MIN
            and min(drafted, released) / (years if years > 0.05 else 1.0) >= SQUAD_CHURN_PER_YEAR):
        flags.append(f"churn: soldiers drafted {drafted} times and released {released} times")
    return flags, lines


# ---------------------------------------------------------------------------
# the keeper's log and the soak rows
# ---------------------------------------------------------------------------

LOG_LIMITS = {  # (label in soak_report.EVENTS, flagged from this many)
    "overseer restarted by the keeper": 3,
    "Python errors (tracebacks)": 1,
    "revive problems": 1,
    "problems talking to the game": 10,
    "unexpected problems (see logs/overseer-errors.log)": 1,
    "time stood still (popups)": 6,
}


def log_flags(lines: list[str]) -> tuple[list[str], list[str]]:
    import soak_report
    counts, example = Counter(), {}
    for line in lines:
        for label, pat in soak_report.EVENTS:
            if re.search(pat, line):
                counts[label] += 1
                example.setdefault(label, line[:200])
    flags = [f"{label}: {counts[label]} (e.g. {example[label]})"
             for label, at in LOG_LIMITS.items() if counts[label] >= at]
    plain = [f"keeper log: {len(lines)} lines; " + (", ".join(f"{k} {v}" for k, v in counts.items()) or "nothing unusual")]
    return flags, plain


def _median(vals):
    vals = sorted(v for v in vals if isinstance(v, (int, float)))
    return vals[len(vals) // 2] if vals else None


def fps_flags(rows: list[dict]) -> tuple[list[str], list[str]]:
    """The game's speed over the window, per fort, and the bridge's slowest
    report sections."""
    flags, plain = [], []
    by_fort = defaultdict(list)
    # (0.105.8) one fort is its site, whichever autosave it was read from
    # ("autosave 1#1430", "autosave 3#1430"), and only the fort played now
    # (the last row's site): the check flagged the old fort's FPS
    # (A: "autosave 1#239") a day after the new one began
    def site(r):
        f = str(r.get("fort") or "")
        return f.rsplit("#", 1)[1] if "#" in f else f
    current = next((site(r) for r in reversed(rows) if r.get("fort")), None)
    for r in rows:
        if (r.get("in_fort") and not r.get("paused") and isinstance(r.get("fps"), (int, float)) and r.get("fort")
                and site(r) == current):
            by_fort[f"site {current}"].append(r)
    for fort, rs in by_fort.items():
        if len(rs) < 6:
            continue
        third = max(2, len(rs) // 3)
        early, late = _median(r["fps"] for r in rs[:third]), _median(r["fps"] for r in rs[-third:])
        pops = [r.get("pop") for r in rs if isinstance(r.get("pop"), int)]
        plain.append(f"FPS {fort}: {early} early, {late} late ({len(rs)} rows"
                     + (f"; population {pops[0]} -> {pops[-1]}" if pops else "") + ")")
        if late is not None and late < FPS_LOW:
            flags.append(f"the game runs slowly in {fort}: FPS median {late} lately (was {early})")
        elif early and late is not None and late < early * (1 - FPS_DROP):
            flags.append(f"the game is slowing down in {fort}: FPS median {early} -> {late}")
    flags_ai, plain_ai = ai_cost_lines(rows)
    flags += flags_ai
    plain += plain_ai
    timing = defaultdict(list)
    for r in rows:
        for k, v in (r.get("report_timing") or {}).items():
            if isinstance(v, (int, float)):
                timing[k].append(v)
    if timing:
        meds = sorted(((k, _median(v)) for k, v in timing.items()), key=lambda kv: -(kv[1] or 0))
        plain.append("report sections, median ms: " + ", ".join(f"{k} {v}" for k, v in meds[:6]))
        for k, v in meds:
            if v is not None and v >= SECTION_SLOW_MS:
                flags.append(f"report section '{k}' is slow: {v} ms median (the game waits while it's built)")
    return flags, plain


def ai_cost_lines(rows: list[dict]) -> tuple[list[str], list[str]]:
    """(0.105.40, 13e) The AI's own cost from the soak rows: its ms per game
    day (every bridge call's time over the game days passed, brain/perf.py),
    median and latest; the slowest report sections by the perf section;
    and the FPS trend by thirds of the window. Plain lines only."""
    plain = []
    days = [r.get("ai_ms_day") for r in rows if isinstance(r.get("ai_ms_day"), (int, float))]
    if days:
        plain.append(f"AI ms per game day: median {_median(days):.0f}, latest {days[-1]:.0f} ({len(days)} rows)")
    slow = defaultdict(list)
    for r in rows:
        for k, v in (r.get("perf_slow") or {}).items():
            if isinstance(v, (int, float)):
                slow[k].append(v)
    if slow:
        meds = sorted(((k, _median(v)) for k, v in slow.items()), key=lambda kv: (-(kv[1] or 0), kv[0]))
        plain.append("slowest sections (perf), median ms: " + ", ".join(f"{k} {v:.0f}" for k, v in meds[:5]))
    fps = [r["fps"] for r in rows if r.get("in_fort") and not r.get("paused")
           and isinstance(r.get("fps"), (int, float))]
    if len(fps) >= 6 and (days or slow):
        third = len(fps) // 3
        parts = [_median(fps[:third]), _median(fps[third:-third]), _median(fps[-third:])]
        plain.append("FPS trend: " + " -> ".join(str(x) for x in parts))
    return [], plain


def stuck_flags(rows: list[dict]) -> tuple[list[str], list[str]]:
    """(0.105.45) The stuck sweep's count (brain/planner_stuck.py soak_summary):
    the AI's own things past their timeout without progress, from the latest
    soak row of the fort played now; flagged when some were past it in each of
    the last STUCK_ROWS rows (the sweep nudges and retires them: one that
    stays is past what its remedies reach)."""
    have = [r for r in rows if isinstance(r.get("stuck"), dict)]
    if not have:
        return [], ["stuck: no count yet (an older overseer, or no full report in the window)"]
    fort = have[-1].get("fort")
    have = [r for r in have if r.get("fort") == fort]
    last = have[-1]["stuck"]
    n = last.get("past") if isinstance(last.get("past"), int) else 0
    kinds = {k: v for k, v in (last.get("kinds") or {}).items() if isinstance(v, int) and v}
    line = (f"stuck: {n} thing(s) past their timeout"
            + (" (" + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) + ")" if kinds else ""))
    flags = []
    tail = have[-STUCK_ROWS:]
    if n > 0 and len(tail) >= STUCK_ROWS and all(int((r["stuck"].get("past") or 0)) > 0 for r in tail):
        flags.append(f"{line}, in each of the last {STUCK_ROWS} soak rows (see the `stuck` notes and section)")
    return flags, [line]


def seen_part(hours: float, now: datetime) -> tuple[list[str], list[str]]:
    """(0.105.46, I1) The seen ledger (brain/seen.py) for this folder, written
    to logs/seen-ledger.md: what of 0.105.32 on the game has shown, in
    counts; flagged: a report section returning an error (in the last
    report, or one of the new ones within the window)."""
    import seen
    L = seen.ledger(ROOT, log_dir=LOG_DIR, code_root=ROOT, now=now)
    return seen.health_part(L, hours, now)


# ---------------------------------------------------------------------------
# the self-test, run as its own process
# ---------------------------------------------------------------------------

SELFTEST_TIMEOUT_S = 300
SUMMARY_RE = re.compile(r"(\d+) passed, (\d+) warnings, (\d+) failed")


def run_selftest(runner=subprocess.run, timeout: int = SELFTEST_TIMEOUT_S) -> tuple[list[str], list[str]]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    try:
        p = runner([sys.executable, "-u", str(HERE / "selftest.py")], cwd=str(ROOT), capture_output=True,
                   text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env)
        out = p.stdout or ""
    except subprocess.TimeoutExpired:
        return [f"the self-test didn't finish in {timeout // 60} minutes"], []
    except Exception as e:  # noqa: BLE001
        return [], [f"self-test not run ({e})"]
    if "isn't running" in out:
        return [], ["self-test: the game isn't running"]
    m = SUMMARY_RE.search(out)
    # (0.104.12) each failure with its detail line (the indented one after it)
    lines = out.splitlines()
    fails = []
    for i, ln in enumerate(lines):
        if ln.startswith("[FAIL]"):
            detail = lines[i + 1].strip() if i + 1 < len(lines) and lines[i + 1].startswith(" ") else ""
            fails.append(ln.strip()[7:] + (f" ({detail[:200]})" if detail else ""))
    plain = [f"self-test: {m.group(1)} passed, {m.group(2)} warnings, {m.group(3)} failed"] if m else \
            ["self-test: no summary (" + out.strip().splitlines()[-1][:120] + ")" if out.strip() else "self-test: no output"]
    return [f"self-test failed: {f}" for f in fails], plain


# ---------------------------------------------------------------------------
# housekeeping
# ---------------------------------------------------------------------------

def _size(p: Path) -> int:
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def _mb(n: int) -> str:
    return f"{n / 1e6:.0f} MB"


def housekeeping(save_roots: list[Path], current: str | None, backup_dir: Path,
                 now: float | None = None, thin: bool = True) -> tuple[list[str], list[str]]:
    """Old test saves listed (yours to delete); the AI's own backups of saves
    not copied for OLD_SAVE_DAYS thinned to their newest copy."""
    import backup
    now = time.time() if now is None else now
    flags, plain = [], []
    old_tests = []
    for root in save_roots:
        try:
            for d in root.iterdir():
                if not d.is_dir() or d.name == current or not TEST_SAVE.search(d.name):
                    continue
                age = (now - d.stat().st_mtime) / 86400
                if age >= OLD_SAVE_DAYS:
                    old_tests.append((d, age))
        except OSError:
            continue
    if old_tests:
        sizes = [(d, age, _size(d)) for d, age in old_tests]
        text = (f"old test saves ({len(sizes)}, {_mb(sum(s for _, _, s in sizes))}) you could delete: "
                + "; ".join(f"{d} ({age:.0f} days, {_mb(s)})" for d, age, s in sizes[:6]))
        # (0.105.46, I6) told to the player once, as a Needs you line (brain/old_saves.py):
        # flagged here only while one on the list hasn't been told yet
        try:
            import old_saves
            new = old_saves.note(sizes, now)
        except Exception:  # noqa: BLE001
            new = True
        (flags if new else plain).append(text if new else text + " (told on the Needs you list)")
    thinned = 0
    if backup_dir.is_dir():
        for d in backup_dir.iterdir():
            if not d.is_dir() or d.name == current:
                continue
            copies = sorted((p for p in d.iterdir() if p.is_dir() and backup.COPY_NAME.match(p.name)),
                            key=lambda p: p.name)
            if len(copies) < 2:
                continue
            try:
                newest = copies[-1].stat().st_mtime
            except OSError:
                continue
            if now - newest >= OLD_SAVE_DAYS * 86400 and thin:
                for old in copies[:-1]:
                    shutil.rmtree(old, ignore_errors=True)
                    thinned += 1
        plain.append(f"backups: {_mb(_size(backup_dir))}" + (f"; {thinned} old copies of forts no longer "
                                                               "played thinned (the newest kept)" if thinned else ""))
    return flags, plain


# ---------------------------------------------------------------------------
# the whole check
# ---------------------------------------------------------------------------

def _last_fort() -> dict:
    return load_json(LOG_DIR / "last-fort.json", {})


def check(hours: float = 24.0, selftest: bool = True, now: datetime | None = None,
          runner=subprocess.run) -> tuple[list[str], list[str]]:
    """Run every check. Returns (flags, the whole page's lines); writes both
    files. Never raises."""
    now = now or datetime.now()
    since = now - timedelta(hours=hours)
    flags, page = [], [f"Run check, {since:%Y-%m-%d %H:%M} to {now:%Y-%m-%d %H:%M} ({hours:g} h)", ""]

    def part(title, fn):
        try:
            f, p = fn()
        except Exception as e:  # noqa: BLE001  (one part failing never stops the others)
            f, p = [], [f"({title} not checked: {type(e).__name__}: {e})"]
        flags.extend(f)
        page.append(f"{title}:")
        page.extend("  " + x for x in p)
        page.extend("  ! " + x for x in f)

    import run_summary
    import soak_report
    if selftest:
        part("self-test", lambda: run_selftest(runner))
    part("what the AI did", lambda: journal_flags(run_summary.entries(since, LOG_DIR / "forts")))
    part("standing lines", lambda: (standing_flags(_load_standing(STANDING), now.timestamp()),
                                    [f"{sum(len(v) for v in _load_standing(STANDING).values() if isinstance(v, dict))} "
                                     "Needs you and failure lines showing"]))
    part("the keeper", lambda: log_flags(soak_report.log_lines(since, LOG_DIR / "unattended.log")))
    part("speed", lambda: fps_flags(soak_report.soak_rows(since, LOG_DIR / "soak.jsonl")))
    part("stuck", lambda: stuck_flags(soak_report.soak_rows(since, LOG_DIR / "soak.jsonl")))   # (0.105.45)
    part("seen", lambda: seen_part(hours, now))   # (0.105.46, I1) logs/seen-ledger.md written too

    def house():
        from dfhack import save_roots
        import backup
        lf = _last_fort()
        return housekeeping(save_roots(lf.get("df_path")), lf.get("save_dir"), backup.BACKUP_DIR)
    part("housekeeping", house)
    page.insert(1, f"{len(flags)} flag(s)" + (": " + "; ".join(f[:80] for f in flags[:4]) if flags else ""))
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _write_atomic(REPORT, "\n".join(page) + "\n")
        _write_atomic(FLAGS, json.dumps({"time": now.isoformat(timespec="seconds"), "hours": hours,
                                         "flags": flags}, ensure_ascii=False, indent=1))
    except Exception:  # noqa: BLE001
        pass
    return flags, page


def summary(flags: list[str]) -> list[str]:
    """The short form for the keeper's log."""
    if not flags:
        return ["Check: nothing flagged (logs/health-check.txt)"]
    return [f"Check: {len(flags)} thing(s) flagged (logs/health-check.txt):"] + [f"Check:   {f[:240]}" for f in flags[:12]]


def main(argv: list[str]) -> int:
    hours = 24.0
    if "--hours" in argv:
        try:
            hours = float(argv[argv.index("--hours") + 1])
        except (IndexError, ValueError):
            print("--hours needs a number")
            return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    flags, page = check(hours, selftest="--no-selftest" not in argv)
    print("\n".join(page))
    return 1 if flags else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
