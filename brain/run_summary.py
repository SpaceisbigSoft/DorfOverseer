"""What the AI did over a run, by rule: its most repeated actions and its
refusals, to catch loops early (a rule doing the same thing again and again,
or the game refusing the same thing).

    python brain\\run_summary.py              the last 24 real hours
    python brain\\run_summary.py --hours 3

Reads the forts' journals (logs/forts/<fort>/journal*.jsonl). The keeper
writes a short version to its log every hour and when it stops.
"""

from __future__ import annotations

import os
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORTS = Path(os.environ.get("DFAI_LOG_DIR") or ROOT / "logs") / "forts"
LOOP_AT = 10            # the same action this many times: named as a possible loop
# repeated by design (the entrances are mapped weekly; (0.104.141) old alert
# icons cleared, the manager's approvals, the recreation burrow refilled, a few
# the level joins: each call different work)
EXPECTED = {"scan_entrances", "dismiss_alerts", "approve_orders", "recreation", "join_levels"}


def _what(a: dict) -> str:
    t = str(a.get("type"))
    for k in ("recipe", "kind", "job", "name", "library"):
        if a.get(k):
            return f"{t} {a[k]}"
    return t


def entries(since: datetime, root: Path = FORTS):
    for path in sorted(root.glob("*/journal*.jsonl")) if root.exists() else []:
        try:
            if datetime.fromtimestamp(path.stat().st_mtime) < since:
                continue
            with path.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                        if e.get("kind") == "decision" and datetime.fromisoformat(e.get("time", "")) >= since:
                            yield e
                    except (ValueError, TypeError):
                        continue
        except OSError:
            continue


def summarize(since: datetime, root: Path = FORTS, top: int = 5) -> list[str]:
    done, refused, why = Counter(), Counter(), {}
    n = 0
    for e in entries(since, root):
        if e.get("mode") != "autopilot":
            continue
        n += 1
        key = (str(e.get("rule")), _what(e.get("action") or {}))
        r = e.get("result") or {}
        if r.get("ok") is False:
            refused[key] += 1
            why[key] = str(r.get("error") or "")[:90]
        else:
            done[key] += 1
    if not n:
        return [f"no actions since {since:%Y-%m-%d %H:%M}"]
    lines = [f"{n} action(s) since {since:%Y-%m-%d %H:%M}: {sum(done.values())} done, {sum(refused.values())} refused"]
    if done:
        lines.append("most done: " + "; ".join(f"{r}: {w} x{c}" for (r, w), c in done.most_common(top)))
    if refused:
        lines.append("most refused: " + "; ".join(f"{r}: {w} x{c} ({why[(r, w)]})"
                                                   for (r, w), c in refused.most_common(top)))
    loops = [(k, c) for k, c in (done + refused).most_common() if c >= LOOP_AT and k[1] not in EXPECTED]
    if loops:
        lines.append("POSSIBLE LOOPS (the same thing " + f"{LOOP_AT}+ times): "
                     + "; ".join(f"{r}: {w} x{c}" for (r, w), c in loops[:top]))
    return lines


def main(argv: list[str]) -> int:
    hours = 24.0
    if "--hours" in argv:
        try:
            hours = float(argv[argv.index("--hours") + 1])
        except (IndexError, ValueError):
            print("--hours needs a number")
            return 2
    for line in summarize(datetime.now() - timedelta(hours=hours)):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
