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

Pure functions and one small per-fort meter; nothing here raises into a
cycle (Meter.note swallows its own trouble).
"""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime

TICKS_PER_DAY = 1200
PERF_FILE = "perf.jsonl"
PERF_MAX_BYTES = 1_000_000      # ~5000 rows (some 14 game years a file), then perf.old.jsonl
RECENT_ROWS = 60                # the last rows kept in memory per fort


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def slow_sections(perf: dict, n: int = 3) -> list[tuple[str, float]]:
    """The n slowest sections of a perf section built this report (cached
    ones left out: their time is only the copy's), slowest first."""
    p = _d(perf)
    cached = _d(p.get("cached"))
    secs = [(k, v) for k, v in _d(p.get("sections")).items() if _num(v) and not cached.get(k)]
    secs.sort(key=lambda kv: (-kv[1], kv[0]))
    return secs[:n]


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
    return (f"PERF report {_ms(p.get('total_ms'))} ms"
            + (" | slowest " + ", ".join(f"{k} {_ms(v)}" for k, v in slow) if slow else "")
            + (f" | cached {cached}" if cached else "")
            + f" | fps {_ms(fps)}")


def ms_per_day(ms: float, ticks: int) -> float | None:
    """The AI's ms per game day: ms over ticks (1200 a day); None when no
    game time passed."""
    if not _num(ms) or not _num(ticks) or ticks <= 0:
        return None
    return round(ms * TICKS_PER_DAY / ticks, 1)


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

    def __init__(self, write: bool = True) -> None:
        self.write = write
        self.base: dict = {}        # key -> {"tick", "ms", "calls"}: where the current row began
        self.recent: dict = {}      # key -> deque of rows
        self.reports: dict = {}     # key -> [total_ms of the reports in this row]

    def note(self, key: str, tick: int, call_ms: float, calls: int = 0, perf: dict | None = None,
             folder=None) -> dict | None:
        try:
            return self._note(key, tick, call_ms, calls, perf, folder)
        except Exception:  # noqa: BLE001  (a measure never stops the fort)
            return None

    def _note(self, key, tick, call_ms, calls, perf, folder):
        p = _d(perf)
        if _num(p.get("total_ms")) and "error" not in p:
            self.reports.setdefault(key, []).append(p["total_ms"])
        b = self.base.get(key)
        if b is None or tick < b["tick"]:            # a new fort, or an older save loaded
            self.base[key] = {"tick": tick, "ms": call_ms, "calls": calls}
            self.reports[key] = []
            return None
        ticks = tick - b["tick"]
        if ticks < TICKS_PER_DAY:
            return None
        ms = max(0.0, call_ms - b["ms"])
        rep = sorted(self.reports.get(key) or [])
        row = {"time": datetime.now().isoformat(timespec="seconds"), "tick": tick,
               "days": round(ticks / TICKS_PER_DAY, 2), "ai_ms": round(ms, 1),
               "ms_per_day": ms_per_day(ms, ticks), "calls": max(0, calls - b["calls"]),
               "report_ms": rep[len(rep) // 2] if rep else None,
               "slow": [[k, v] for k, v in slow_sections(p)], "fps": p.get("fps") if _num(p.get("fps")) else None}
        self.base[key] = {"tick": tick, "ms": call_ms, "calls": calls}
        self.reports[key] = []
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
