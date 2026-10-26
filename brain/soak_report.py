"""How a long unattended run went, in one page: read it in the morning.

    python brain\\soak_report.py              the last 12 real hours
    python brain\\soak_report.py --hours 20

Reads logs/soak.jsonl (a row every 10 real minutes, written by the overseer
while unattended), logs/unattended.log (the keeper: restarts, revives,
errors) and the forts' journals (what the AI did: brain/run_summary.py).
Prints the report and writes it to logs/soak-report.txt.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
sys.path.insert(0, str(ROOT / "brain"))

# keeper/overseer log lines worth counting (label, pattern)
EVENTS = [
    ("overseer restarted by the keeper", r"Restarting the overseer"),
    ("revive: DF started again", r"Revive: Dwarf Fortress wasn't running"),
    ("revive: save loaded from the title screen", r"Revive: the game sat at the title"),
    ("revive problems", r"Revive: couldn't"),
    ("game not running", r"Dwarf Fortress isn't running"),
    ("problems talking to the game", r"Problem talking to the game"),
    ("Python errors (tracebacks)", r"Traceback"),
    ("self-pauses unpaused", r"the game had paused itself"),
    ("time stood still (popups)", r"time stood still"),
    ("AI chronicle stories", r"AI chronicle \("),
    ("unexpected problems (see logs/overseer-errors.log)", r"Unexpected problem"),
]


def soak_rows(since: datetime, path: Path | None = None) -> list[dict]:
    path = path or LOGS / "soak.jsonl"
    out = []
    for p in (path.with_name(f"{path.stem}.old{path.suffix}"), path):   # (rotated: the older rows first)
        try:
            with p.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        if datetime.fromisoformat(r["time"]) >= since:
                            out.append(r)
                    except (ValueError, KeyError, TypeError):
                        continue
        except OSError:
            continue
    return out


def log_lines(since: datetime, path: Path | None = None) -> list[str]:
    path = path or LOGS / "unattended.log"
    out = []
    for p in (path.with_suffix(".old.log"), path):
        try:
            with p.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = re.match(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]", line)
                    if m and datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") >= since:
                        out.append(line.rstrip("\n"))
        except OSError:
            continue
    return out


def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def report(hours: float, now: datetime | None = None) -> list[str]:
    now = now or datetime.now()
    since = now - timedelta(hours=hours)
    rows = soak_rows(since)
    out = [f"Soak report, {since:%Y-%m-%d %H:%M} to {now:%Y-%m-%d %H:%M} ({hours:g} h)"]
    if rows:
        first, last = rows[0], rows[-1]
        in_fort = [r for r in rows if r.get("in_fort")]
        out.append(f"{len(rows)} soak rows (one per 10 min); in a fort in {len(in_fort)}; "
                   f"paused in {sum(1 for r in rows if r.get('paused'))}; halted in "
                   f"{sum(1 for r in rows if r.get('halted'))}; time standing still (60 s+) in "
                   f"{sum(1 for r in rows if (r.get('time_still_s') or 0) >= 60)}")
        out.append(f"game time: {first.get('date')} -> {last.get('date')}  (fort {last.get('fort')})")
        # gaps: the overseer wasn't writing (stopped, crashed, PC asleep)
        gaps = []
        for a, b in zip(rows, rows[1:]):
            ta, tb = datetime.fromisoformat(a["time"]), datetime.fromisoformat(b["time"])
            if (tb - ta).total_seconds() > 25 * 60:
                gaps.append(f"{ta:%H:%M}-{tb:%H:%M}")
        out.append("gaps in the soak log (overseer not running): " + (", ".join(gaps) if gaps else "none"))
        # hour by hour
        out.append("")
        out.append("hour   date            pop  fps(min)  drink/d meals/d unhappy% idle% hungry wealth     proj")
        by_hour: dict[str, dict] = {}
        for r in rows:
            by_hour[r["time"][:13]] = r                     # the last row of each hour
        for h, r in by_hour.items():
            out.append(f"{h[11:13]}:00  {str(r.get('date') or '-'):15} {_fmt(r.get('pop')):>4} "
                       f"{_fmt(r.get('fps')):>4}({_fmt(r.get('fps_min'))})  {_fmt(r.get('drink_pd')):>7} "
                       f"{_fmt(r.get('meals_pd')):>7} {_fmt(r.get('unhappy_pct')):>8} {_fmt(r.get('idle_pct')):>5} "
                       f"{_fmt(r.get('hungry')):>6} {_fmt(r.get('wealth')):>10} {_fmt(r.get('projects_open'))}")
        pops = [r.get("pop") for r in in_fort if isinstance(r.get("pop"), int)]
        if pops:
            out.append(f"population {pops[0]} -> {pops[-1]} (low {min(pops)}, high {max(pops)})")
        firsts = next((r for r in in_fort if r.get("needs")), None)
        if firsts and last.get("needs"):
            out.append("needs distracting the most dwarves: at the start " +
                       ", ".join(f"{k} {v}" for k, v in firsts["needs"].items()) +
                       "; at the end " + ", ".join(f"{k} {v}" for k, v in last["needs"].items()))
        if last.get("agenda"):
            out.append("the AI's agenda at the end: " + "; ".join(map(str, last["agenda"])))
    else:
        out.append("no soak rows: the overseer wasn't running unattended (keeper) in this time, "
                   "or this is an older overseer")
    # the keeper's log
    lines = log_lines(since)
    out.append("")
    counts = Counter()
    examples: dict[str, str] = {}
    for line in lines:
        for label, pat in EVENTS:
            if re.search(pat, line):
                counts[label] += 1
                examples.setdefault(label, line[:220])
    out.append(f"keeper log: {len(lines)} lines")
    for label, _ in EVENTS:
        if counts[label]:
            out.append(f"  {label}: {counts[label]}  e.g. {examples[label]}")
    # what the AI did
    try:
        import run_summary
        out.append("")
        out.append("what the AI did:")
        out += ["  " + x for x in run_summary.summarize(since)]
    except Exception as e:  # noqa: BLE001
        out.append(f"(no action summary: {e})")
    return out


def main(argv: list[str]) -> int:
    hours = 12.0
    if "--hours" in argv:
        try:
            hours = float(argv[argv.index("--hours") + 1])
        except (IndexError, ValueError):
            print("--hours needs a number")
            return 2
    lines = report(hours)
    text = "\n".join(lines)
    print(text)
    try:
        (LOGS / "soak-report.txt").write_text(text + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
