"""Replay: step through what happened, day by day, and what the AI did about it.

    python brain/replay.py                 the latest scenario run
    python brain/replay.py planner-a       a run (folder name or part of it)
    python brain/replay.py --journal       your normal games (the latest logs/forts/<fort>/journal.jsonl)
    python brain/replay.py --list          list the recorded runs
    python brain/replay.py RUN --all       print everything at once (no stepping)

While stepping: Enter = next day, b = back, a number = jump to that day,
/word = next day mentioning that word, q = quit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bridge import LOG_DIR  # noqa: E402

RUNS_DIR = LOG_DIR / "runs"
DISPLAY_ONLY = {"report_status", "set_culture", "save_memory"}


def load_run(run_dir: Path) -> list[dict]:
    days = []
    with (run_dir / "days.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                days.append(json.loads(line))
    return days


def date_key(d: dict | None) -> tuple:
    d = d or {}
    return (d.get("year", 0), (d.get("tick", 0) // 1200))


def load_journal(path: Path) -> list[dict]:
    """The overseer's journal grouped into in-game days. Events carry no date,
    so each one joins the next dated entry's day."""
    days: dict[tuple, dict] = {}
    waiting_events: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("kind") == "event":
                waiting_events.append(e.get("event") or {})
                continue
            if "date" not in e:
                continue
            k = date_key(e["date"])
            day = days.setdefault(k, {"date": e["date"], "events": [], "decisions": []})
            day["events"] += waiting_events
            waiting_events = []
            day["decisions"].append(e)
    out = []
    for i, k in enumerate(sorted(days), 1):
        d = days[k]
        dt = d["date"]
        out.append({"day": i, "row": {"date": f"{dt.get('day')} {dt.get('month')} {dt.get('year')}"},
                    "events": d["events"], "decisions": d["decisions"]})
    return out


def event_text(e: dict) -> str:
    who = e.get("name") or f"unit {e.get('unit_id', '?')}"
    kind = e.get("kind")
    if kind == "death":
        return f"died: {who}" + (" (animal)" if e.get("animal") else " (citizen)" if e.get("own_civ") else "")
    if kind == "arrival":
        tag = "hostile" if e.get("hostile") else "own civ" if e.get("own_civ") else "visitor"
        return f"arrived: {who} ({tag})"
    if kind == "invasion":
        return "INVASION"
    if kind == "report":
        return f"{e.get('topic')}: {e.get('text', '')}"[:160]
    return json.dumps(e)[:100]


def decision_text(d: dict) -> str:
    a = d.get("action") or {}
    r = d.get("result")
    outcome = ("would do" if d.get("mode") == "dry-run" else
               "done" if isinstance(r, dict) and r.get("ok") is True else
               "unknown" if isinstance(r, dict) and r.get("ok") is None else
               f"refused: {r.get('error')}" if isinstance(r, dict) else "?")
    if d.get("kind") == "declined":
        outcome = "you said no"
    detail = ", ".join(f"{k}={v}" for k, v in a.items() if k != "type" and not isinstance(v, (dict, list)))
    return f"{d.get('rule', '?')}: {a.get('type', '?')} {detail}  [{outcome}]\n        why: {d.get('reason', '')}"


def show_day(d: dict, total: int) -> str:
    r = d.get("row") or {}
    lines = [f"=== Day {d['day']}/{total}   {r.get('date', '')} ==="]
    if "population" in r:
        lines.append(f"  {r['population']} dwarves | unhappy {r.get('unhappy_pct')}% | idle {r.get('idle_pct')}% | "
                     f"wealth {r.get('wealth')} | drink/dwarf {r.get('drink_per_dwarf')} | "
                     f"meals/dwarf {r.get('meals_per_dwarf')} | fps {r.get('fps')}")
    for e in d.get("events") or []:
        lines.append(f"  event   {event_text(e)}")
    for x in d.get("decisions") or []:
        if x.get("kind") == "culture":
            lines.append(f"  culture {x.get('era') or x.get('change')}")
        elif x.get("kind") in ("decision", "declined") and (x.get("action") or {}).get("type") not in DISPLAY_ONLY:
            lines.append(f"  AI      {decision_text(x)}")
    header_lines = 2 if "population" in r else 1
    if len(lines) == header_lines:
        lines.append("  (quiet day)")
    return "\n".join(lines)


def find_run(name: str | None) -> Path | None:
    runs = sorted(p for p in RUNS_DIR.glob("*") if (p / "days.jsonl").exists())
    if not name:
        return runs[-1] if runs else None
    if Path(name).is_dir():
        return Path(name)
    matches = [p for p in runs if name in p.name]
    return matches[-1] if matches else None


def step(days: list[dict]) -> None:
    i = 0
    while 0 <= i < len(days):
        print(show_day(days[i], len(days)))
        try:
            cmd = input("[Enter] next  b back  N jump  /word find  q quit > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if cmd == "q":
            return
        if cmd == "b":
            i = max(0, i - 1)
        elif cmd.isdigit():
            i = min(len(days) - 1, max(0, int(cmd) - 1))
        elif cmd.startswith("/") and len(cmd) > 1:
            word = cmd[1:].lower()
            hit = next((j for j in range(i + 1, len(days))
                        if word in show_day(days[j], len(days)).lower()), None)
            if hit is None:
                print(f"  (no later day mentions '{word}')")
            else:
                i = hit
        else:
            i += 1
    print("(end of the record)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Step through a run or your games, day by day.")
    ap.add_argument("run", nargs="?", help="run folder name or part of it (default: latest run)")
    ap.add_argument("--journal", action="store_true", help="replay your latest fort journal instead of a run")
    ap.add_argument("--list", action="store_true", help="list recorded runs")
    ap.add_argument("--all", action="store_true", help="print every day at once")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    if args.list:
        runs = sorted(p for p in RUNS_DIR.glob("*") if (p / "days.jsonl").exists())
        for p in runs:
            n = sum(1 for _ in (p / "days.jsonl").open(encoding="utf-8"))
            info = {}
            if (p / "run.json").exists():
                info = json.loads((p / "run.json").read_text(encoding="utf-8"))
            print(f"{p.name:40} {info.get('mode', '?'):9} {n} days  on {info.get('save_dir', '?')}")
        if not runs:
            print("No runs yet (python brain/scenario.py run ...).")
        return 0

    if args.journal:
        # the most recently written fort journal (logs/forts/<fort>/journal.jsonl,
        # since 0.31), else the old shared one
        journals = sorted((LOG_DIR / "forts").glob("*/journal.jsonl"), key=lambda p: p.stat().st_mtime)
        path = journals[-1] if journals else LOG_DIR / "decisions.jsonl"
        if journals:
            print(f"Journal: {path.parent.name}")
        if not path.exists():
            print("No journal yet: run the overseer first.")
            return 1
        days = load_journal(path)
    else:
        run = find_run(args.run)
        if run is None:
            print("No such run. Try --list.")
            return 1
        print(f"Run: {run.name}")
        days = load_run(run)
    if not days:
        print("Nothing recorded.")
        return 1
    if args.all or not sys.stdin.isatty():
        for d in days:
            print(show_day(d, len(days)))
    else:
        step(days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
