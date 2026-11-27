"""(0.105.40, 13e) What the AI costs the game, and backing off when it's slow.

- The bridge's `perf` report section (lua/ai-bridge.lua perf_section): each
  section's ms this report, the cached ones, the report's total, the FPS.
- The AI's own cost per game day: every bridge call's time (brain/bridge.py
  CALL_MS: reports, actions, status, memory) summed and divided by the game
  days that passed, one row a game day per fort in
  logs/forts/<fort>/perf.jsonl (capped: one old copy, memstore.cap_file).
- The back-off: while the game runs slowly (the overseer's fps_low: under
  35% of the session's best FPS, overseer.fps_state) the full report comes
  `perf_slow_cycle_factor` times further apart, but never while a threat
  or a siege is on the map (the safety rules keep their cadence).

- (R29 W7) each row also says the population (state dwarves.total), the
  full and pulse reports of that day and each kind's median ms, the real
  seconds the day took and the AI's share of them (`ai_share`: the game
  stands still while a bridge call runs), and the day's costliest
  sections summed over all its reports (`sections`, built ones only).
- (F3a) and the game ticks a real second over the row (`tps`, from the
  reports' perf.game_tick over the real seconds between rows, every stall
  included: the measure of what the AI costs the game).
- (R29 W7) the soak comparison (Phase 13e's exit): `python brain/perf.py
  compare <fort folder or perf.jsonl>` sets each later game year beside
  year one at the same population (bins of `--bin` dwarves; a row without
  `pop` takes it from the folder's timeline.csv) and says whether the FPS
  stays within `--tol` (20%) of year one's, with the AI's ms per game day
  and share beside it.

Pure functions and one small per-fort meter; nothing here raises into a
cycle (Meter.note swallows its own trouble).
"""

from __future__ import annotations

import json
import time
from collections import deque
from datetime import datetime

TICKS_PER_DAY = 1200
TICKS_PER_YEAR = TICKS_PER_DAY * 28 * 12   # (R29 W7) a game year
SECTIONS_KEPT = 6               # (R29 W7) the day's costliest sections kept in a row
PERF_FILE = "perf.jsonl"
PERF_MAX_BYTES = 1_000_000      # ~5000 rows (some 14 game years a file), then perf.old.jsonl
RECENT_ROWS = 60                # the last rows kept in memory per fort


from util import as_dict as _d  # noqa: E402  (r6 c2) was a copy here


from util import is_num as _num  # noqa: E402  (r6 c2) was a copy here


def _wall() -> float:
    return time.monotonic()


def slow_sections(perf: dict, n: int = 3) -> list[tuple[str, float]]:
    """The n slowest sections of a perf section built this report (cached
    ones left out: their time is only the copy's), slowest first."""
    p = _d(perf)
    cached = _d(p.get("cached"))
    secs = [(k, v) for k, v in _d(p.get("sections")).items() if _num(v) and not cached.get(k)]
    secs.sort(key=lambda kv: (-kv[1], kv[0]))
    return secs[:n]


def section_age(s: dict, name: str) -> float | None:
    """(0.105.48, K7c) How many game days old the report's copy of a section
    is: 0.0 when it was built for this report, its cached copy's age when it
    came from the bridge's cache (perf.cache_age), None when the report has
    no such section or no perf section (an older bridge)."""
    if not isinstance(s, dict) or name not in s:
        return None
    p = _d(s.get("perf"))
    if not p or "error" in p:
        return None
    age = _d(p.get("cache_age")).get(name)
    if _num(age):
        return float(age)
    return None if _d(p.get("cached")).get(name) else 0.0


def stale_sections(s: dict) -> list[tuple[str, float]]:
    """(0.105.48, K7c) The cached sections sent past their own cache days
    (perf.cache_due), oldest first, with their age in game days."""
    p = _d(_d(s).get("perf"))
    ages = _d(p.get("cache_age"))
    out = [(k, float(ages[k])) for k, v in _d(p.get("cache_due")).items() if v and _num(ages.get(k))]
    out.sort(key=lambda kv: (-kv[1], kv[0]))
    return out


def _ms(v) -> str:
    return f"{v:.0f}" if _num(v) else "?"


def perf_line(s: dict) -> str:
    """The digest's PERF line: the report's total ms, its three slowest
    sections, the FPS; "" when the report has no perf section (an older
    bridge) or it failed."""
    p = s.get("perf")
    if not isinstance(p, dict) or "error" in p or not isinstance(p.get("sections"), dict):
        return ""
    slow = slow_sections(p)
    cached = sum(1 for v in _d(p.get("cached")).values() if v)
    fps = p.get("fps")
    stale = stale_sections(s)
    return (f"PERF report {_ms(p.get('total_ms'))} ms"
            + (" | slowest " + ", ".join(f"{k} {_ms(v)}" for k, v in slow) if slow else "")
            + (f" | cached {cached}" if cached else "")
            + (" | stale " + ", ".join(f"{k} {v:.1f}d" for k, v in stale[:3]) if stale else "")
            + f" | fps {_ms(fps)}")


def ms_per_day(ms: float, ticks: int) -> float | None:
    """The AI's ms per game day: ms over ticks (1200 a day); None when no
    game time passed."""
    if not _num(ms) or not _num(ticks) or ticks <= 0:
        return None
    return round(ms * TICKS_PER_DAY / ticks, 1)


def tps(game_tick, base_game_tick, tick, base_tick, wall) -> float | None:
    """(F3a) Game ticks per real second over a perf row: the reports'
    perf.game_tick at both ends when both are there (else the date's absolute
    tick), over the real seconds between; the bridge calls, the quicksave and
    any pause count as time the game stood still. None under a real second."""
    if not _num(wall) or wall < 1:
        return None
    if _num(game_tick) and _num(base_game_tick) and game_tick >= base_game_tick:
        ticks = game_tick - base_game_tick
    elif _num(tick) and _num(base_tick) and tick >= base_tick:
        ticks = tick - base_tick
    else:
        return None
    return round(ticks / wall, 1)


def threat_active(s: dict) -> bool:
    """A threat or a siege the safety rules answer: a threat that can reach
    the dwarves, an invader or a great danger on the map, a siege now, or the
    civilian alarm on. While it holds the overseer keeps its cadence."""
    o = _d(s.get("others_on_map"))
    n = o.get("threats_that_can_reach_dwarves")
    if _num(n) and n > 0:
        return True
    for t in o.get("threats") or []:
        if isinstance(t, dict) and (t.get("invader") or t.get("great_danger") or t.get("can_reach_dwarves")):
            return True
    for e in _d(s.get("world")).get("sieges") or []:
        if isinstance(e, dict) and e.get("active"):
            return True
    return s.get("civ_alert") is True


def cycle_factor(slow: bool, threat: bool, factor) -> int:
    """How many times further apart the full report comes: `factor` while
    the game runs slowly, 1 otherwise and always while a threat is on."""
    if not slow or threat:
        return 1
    try:
        return max(1, int(factor))
    except (TypeError, ValueError):
        return 1


class Meter:
    """The AI's ms per game day, per fort. note() is called once a cycle
    with the absolute game tick and the bridge's running call total; once a
    game day has passed since the last row it gives (and writes) a row."""

    def __init__(self, write: bool = True, clock=None) -> None:
        self.write = write
        self.clock = clock or _wall    # (R29 W7) real seconds (the tests swap in their own)
        self.base: dict = {}        # key -> {"tick", "ms", "calls", "wall"}: where the current row began
        self.recent: dict = {}      # key -> deque of rows
        self.reports: dict = {}     # key -> [total_ms of the reports in this row]
        self.tiers: dict = {}       # (R29 W7) key -> {"full": [ms], "pulse": [ms]}
        self.secs: dict = {}        # (R29 W7) key -> {section: ms summed over the row's reports}

    def note(self, key: str, tick: int, call_ms: float, calls: int = 0, perf: dict | None = None,
             folder=None, state: dict | None = None) -> dict | None:
        try:
            return self._note(key, tick, call_ms, calls, perf, folder, state)
        except Exception:  # noqa: BLE001  (a measure never stops the fort)
            return None

    def _reset(self, key, tick, call_ms, calls, game_tick=None) -> None:
        self.base[key] = {"tick": tick, "ms": call_ms, "calls": calls, "wall": self.clock(),
                          "game_tick": game_tick if _num(game_tick) else None}   # (F3a) perf.game_tick
        self.reports[key] = []
        self.tiers[key] = {"full": [], "pulse": []}
        self.secs[key] = {}

    def _note(self, key, tick, call_ms, calls, perf, folder, state=None):
        p = _d(perf)
        st = _d(state)
        if _num(p.get("total_ms")) and "error" not in p:
            self.reports.setdefault(key, []).append(p["total_ms"])
            # (R29 W7) by kind: the pulse between days, every other tier a full report
            kind = "pulse" if st.get("tier") == "pulse" else "full"
            self.tiers.setdefault(key, {"full": [], "pulse": []})[kind].append(p["total_ms"])
            acc = self.secs.setdefault(key, {})
            cached = _d(p.get("cached"))
            for k, v in _d(p.get("sections")).items():
                if _num(v) and not cached.get(k):
                    acc[k] = acc.get(k, 0.0) + v
        gt = p.get("game_tick") if "error" not in p else None
        b = self.base.get(key)
        if b is None or tick < b["tick"]:            # a new fort, or an older save loaded
            self._reset(key, tick, call_ms, calls, gt)
            return None
        ticks = tick - b["tick"]
        if ticks < TICKS_PER_DAY:
            return None
        ms = max(0.0, call_ms - b["ms"])
        rep = sorted(self.reports.get(key) or [])
        tiers = self.tiers.get(key) or {"full": [], "pulse": []}
        wall = self.clock() - b["wall"] if _num(b.get("wall")) else None
        top = sorted(_d(self.secs.get(key)).items(), key=lambda kv: (-kv[1], kv[0]))[:SECTIONS_KEPT]
        pop = _d(st.get("dwarves")).get("total")
        row = {"time": datetime.now().isoformat(timespec="seconds"), "tick": tick,
               "days": round(ticks / TICKS_PER_DAY, 2), "ai_ms": round(ms, 1),
               "ms_per_day": ms_per_day(ms, ticks), "calls": max(0, calls - b["calls"]),
               "report_ms": rep[len(rep) // 2] if rep else None,
               "slow": [[k, v] for k, v in slow_sections(p)], "fps": p.get("fps") if _num(p.get("fps")) else None,
               # (R29 W7) what the soak comparison needs
               "pop": pop if _num(pop) else None,
               "full": len(tiers["full"]), "full_ms": median(tiers["full"]),
               "pulse": len(tiers["pulse"]), "pulse_ms": median(tiers["pulse"]),
               "wall_s": round(wall, 1) if _num(wall) and wall > 0 else None,
               # (a share only over a real second or more: a test's or a replay's instant row has none)
               "ai_share": round(ms / (wall * 1000), 3) if _num(wall) and wall >= 1 else None,
               "sections": [[k, round(v, 1)] for k, v in top],
               # (F3a) game ticks a real second over the row, every stall included
               "tps": tps(gt, b.get("game_tick"), tick, b["tick"], wall)}
        self._reset(key, tick, call_ms, calls, gt)
        self.recent.setdefault(key, deque(maxlen=RECENT_ROWS)).append(row)
        if self.write and folder is not None:
            import memstore
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / PERF_FILE
            memstore.cap_file(path, PERF_MAX_BYTES)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def latest(self, key: str) -> dict | None:
        rows = self.recent.get(key)
        return rows[-1] if rows else None


def read_rows(path) -> list[dict]:
    """A perf.jsonl's rows (bad lines skipped); [] when there is none."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, AttributeError):
        return []
    out = []
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def median(vals) -> float | None:
    v = sorted(x for x in vals if _num(x))
    return v[len(v) // 2] if v else None


# --- (R29 W7, 13e) the soak comparison ---------------------------------------------------

def timeline_pops(path) -> dict:
    """day -> population from a fort's timeline.csv ({} without one)."""
    import csv
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    out[int(r["day"])] = int(float(r["pop"]))
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        return {}
    return out


def fill_pop(rows: list[dict], pops: dict) -> list[dict]:
    """Rows without `pop` (written before R29) take the timeline's population
    of their game day, or the last day before it."""
    if not pops:
        return rows
    days = sorted(pops)
    import bisect
    for r in rows:
        if _num(r.get("pop")) or not _num(r.get("tick")):
            continue
        i = bisect.bisect_right(days, int(r["tick"]) // TICKS_PER_DAY) - 1
        if i >= 0:
            r["pop"] = pops[days[i]]
    return rows


def soak_compare(rows: list[dict], bin_size: int = 10, tol: float = 0.2, ref: str = "year1") -> dict:
    """Each later game year set beside year one at the same population.

    Years count from the first row's tick (year 1 = its first 403,200
    ticks). Rows are put in population bins of `bin_size`; for each later
    year and each bin it shares with year one (3 rows at least on each
    side) the median FPS, AI ms per game day and AI share are compared.
    A bin passes when the later FPS is at least (1 - tol) of year one's.
    ref "first": each bin is set against the first year it was seen in
    (a fort that grows every year meets year one's population only then).
    Returns {"years": {year: [bin rows]}, "verdict": "pass" | "fail" |
    "no overlap", "first_tick", "ref"}."""
    good = [r for r in rows if _num(r.get("tick")) and _num(r.get("pop"))]
    if not good:
        return {"years": {}, "verdict": "no overlap", "first_tick": None}
    t0 = min(r["tick"] for r in good)
    by: dict = {}
    for r in good:
        y = int((r["tick"] - t0) // TICKS_PER_YEAR) + 1
        b = int(r["pop"]) // bin_size * bin_size
        by.setdefault(y, {}).setdefault(b, []).append(r)

    def stats(rs):
        return {"n": len(rs), "fps": median(r.get("fps") for r in rs),
                "ms_per_day": median(r.get("ms_per_day") for r in rs),
                "ai_share": median(r.get("ai_share") for r in rs)}
    base, base_year = {}, {}
    for y in sorted(by):
        if ref != "first" and y != 1:
            break
        for b, rs in by[y].items():
            if b not in base and len(rs) >= 3:
                base[b], base_year[b] = stats(rs), y
    out, fails, compared = {}, 0, 0
    for y in sorted(by):
        lines = []
        for b, rs in sorted(by[y].items()):
            if len(rs) < 3 or b not in base or y <= base_year[b]:
                continue
            now, refs = stats(rs), base[b]
            ratio = (now["fps"] / refs["fps"]) if _num(now["fps"]) and _num(refs["fps"]) and refs["fps"] else None
            ok = ratio is not None and ratio >= 1 - tol
            compared += 1
            fails += 0 if ok else 1
            lines.append({"pop": f"{b}-{b + bin_size - 1}", "year1": refs, "ref_year": base_year[b], "now": now,
                          "fps_ratio": round(ratio, 2) if ratio is not None else None, "ok": ok})
        if lines:
            out[y] = lines
    verdict = "no overlap" if not compared else ("pass" if not fails else "fail")
    return {"years": out, "verdict": verdict, "first_tick": t0, "ref": ref}


def compare_text(res: dict) -> str:
    """The comparison as lines for the console."""
    def f(v, nd=0):
        return "?" if not _num(v) else (f"{v:.{nd}f}")
    lines = [f"soak comparison (year 1 from tick {res.get('first_tick')}, against "
             f"{'the first year at each population' if res.get('ref') == 'first' else 'year 1'}): {res.get('verdict')}"]
    for y, rows in sorted(res.get("years", {}).items()):
        for r in rows:
            a, b = r["year1"], r["now"]
            lines.append(f"year {y} pop {r['pop']:>7}: fps {f(b['fps'])} vs {f(a['fps'])} in year {r['ref_year']}"
                         f" (x{f(r['fps_ratio'], 2)}) "
                         f"{'ok' if r['ok'] else 'SLOWER'} | AI ms/day {f(b['ms_per_day'])} vs {f(a['ms_per_day'])}"
                         f" | AI share {f(b['ai_share'], 3)} vs {f(a['ai_share'], 3)} | rows {b['n']}/{a['n']}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    """python brain/perf.py compare <fort folder | perf.jsonl> [--bin 10] [--tol 0.2] [--first]"""
    from pathlib import Path
    if len(argv) < 2 or argv[0] != "compare":
        print(main.__doc__)
        return 2
    target = Path(argv[1])
    bin_size, tol = 10, 0.2
    if "--bin" in argv:
        bin_size = int(argv[argv.index("--bin") + 1])
    if "--tol" in argv:
        tol = float(argv[argv.index("--tol") + 1])
    folder = target if target.is_dir() else target.parent
    path = target / PERF_FILE if target.is_dir() else target
    rows = read_rows(folder / "perf.old.jsonl") + read_rows(path) if path.name == PERF_FILE else read_rows(path)
    rows = fill_pop(rows, timeline_pops(folder / "timeline.csv"))
    print(compare_text(soak_compare(rows, bin_size, tol, "first" if "--first" in argv else "year1")))
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
