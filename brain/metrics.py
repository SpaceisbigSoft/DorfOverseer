"""Measuring how a fort does: one row per in-game day, a summary per run, and
a side-by-side comparison of runs. Pure logic (see brain/scenario.py for the
part that drives the game).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from digest import _d, _l, normalize

UNHAPPY = ("miserable", "very_unhappy", "unhappy")
HAPPY = ("happy", "ecstatic")

FIELDS = ["day", "date", "population", "adults", "idle_pct", "unhappy", "unhappy_pct", "happy_pct",
          "needs_care", "wealth", "drink_per_dwarf", "meals_per_dwarf", "citizen_deaths",
          "arrivals", "threats_reaching", "alert_on", "projects_open", "projects_finished",
          "ai_actions", "tokens_used", "fps", "report_ms",
          "moods", "artifacts", "insanity", "tantrums", "ghosts", "crimes"]

# announcement topics counted each day (lua/ai-reports.lua)
REPORT_COUNTS = {"moods": "mood", "artifacts": "artifact_made", "insanity": "insanity",
                 "tantrums": "tantrum", "ghosts": "ghost", "crimes": "crime"}


def _pct(part, whole) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def day_row(day: int, state: dict, events: list[dict], *, ai_actions: int = 0, tokens_used: int = 0,
            fps: float | None = None) -> dict:
    """One day's numbers from a fort report and that day's events."""
    s = normalize(state)
    dw = _d(s.get("dwarves"))
    stress = _d(dw.get("stress"))
    pop = dw.get("total") or 0
    adults = dw.get("adults") or 0
    st = _d(s.get("stocks"))
    pr = _d(s.get("projects"))
    d = _d(s.get("date"))
    unhappy = sum(stress.get(k, 0) for k in UNHAPPY)
    topics = [e.get("topic") for e in events if e.get("kind") == "report"]
    counts = {field: topics.count(topic) for field, topic in REPORT_COUNTS.items()}
    return {**counts,
        "day": day,
        "date": f"{d.get('day')} {d.get('month')} {d.get('year')}",
        "population": pop,
        "adults": adults,
        "idle_pct": _pct(dw.get("idle_adults") or 0, adults),
        "unhappy": unhappy,
        "unhappy_pct": _pct(unhappy, pop),
        "happy_pct": _pct(sum(stress.get(k, 0) for k in HAPPY), pop),
        "needs_care": dw.get("needs_medical_care") or 0,
        "wealth": s.get("wealth") if isinstance(s.get("wealth"), (int, float)) else None,
        "drink_per_dwarf": round(st.get("drink", 0) / pop, 1) if pop else 0,
        "meals_per_dwarf": round(st.get("prepared_meals", 0) / pop, 1) if pop else 0,
        "citizen_deaths": sum(1 for e in events if e.get("kind") == "death"
                              and e.get("own_civ") and not e.get("animal") and not e.get("again")),
        "arrivals": sum(1 for e in events if e.get("kind") == "arrival"
                        and e.get("own_civ") and not e.get("hostile")),
        "threats_reaching": _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves", 0),
        "alert_on": 1 if s.get("civ_alert") else 0,
        "projects_open": len(_l(pr.get("open"))),
        "projects_finished": pr.get("finished", 0) or 0,
        "ai_actions": ai_actions,
        "tokens_used": tokens_used,
        "fps": fps,
        "report_ms": _d(s.get("_meta")).get("build_ms"),
    }


def _avg(rows, key):
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
    return round(sum(vals) / len(vals), 1) if vals else None


def new_citizens(rows: list[dict]) -> int:
    """Dwarves who joined (migrants, births): each day's rise in population,
    plus that day's deaths (someone died and someone joined = still one new)."""
    n = 0
    for prev, cur in zip(rows, rows[1:]):
        n += max(0, cur["population"] - prev["population"] + cur["citizen_deaths"])
    return n


def summarize(rows: list[dict], label: str = "", mode: str = "", fell: bool = False) -> dict:
    """A run in one line of numbers."""
    if not rows:
        return {"label": label, "mode": mode, "days": 0}
    first, last = rows[0], rows[-1]
    w0, w1 = first.get("wealth"), last.get("wealth")
    return {
        "label": label, "mode": mode,
        "days": len(rows), "years": round(len(rows) / 336, 2), "fell": fell,
        "population_start": first["population"], "population_end": last["population"],
        "population_min": min(r["population"] for r in rows),
        "citizen_deaths": sum(r["citizen_deaths"] for r in rows),
        # From the population, not arrival events: DF doesn't announce
        # migrants to DFHack's event watcher the way it does nobles.
        "new_citizens": new_citizens(rows),
        "wealth_start": w0, "wealth_end": w1,
        "wealth_change_pct": round(100.0 * (w1 - w0) / w0, 1) if w0 and w1 is not None else None,
        "unhappy_pct_avg": _avg(rows, "unhappy_pct"),
        "unhappy_pct_max": max(r["unhappy_pct"] for r in rows),
        "happy_pct_avg": _avg(rows, "happy_pct"),
        "idle_pct_avg": _avg(rows, "idle_pct"),
        "drink_per_dwarf_end": last["drink_per_dwarf"],
        "meals_per_dwarf_end": last["meals_per_dwarf"],
        "days_with_reachable_threat": sum(1 for r in rows if r["threats_reaching"]),
        "projects_finished": last["projects_finished"] - first["projects_finished"],
        "ai_actions": sum(r["ai_actions"] for r in rows),
        "tokens_used": last["tokens_used"] - first["tokens_used"],
        **{field: sum(r.get(field) or 0 for r in rows) for field in REPORT_COUNTS},
        "fps_avg": _avg(rows, "fps"),
        "report_ms_avg": _avg(rows, "report_ms"),
    }


# What the comparison table shows, and which way is better.
COMPARE = [
    ("Days played", "days", None), ("Fort fell", "fell", "low"),
    ("Population: start", "population_start", None), ("Population: end", "population_end", "high"),
    ("Lowest population", "population_min", "high"), ("Citizen deaths", "citizen_deaths", "low"),
    ("New citizens (migrants, births)", "new_citizens", None),
    ("Wealth change %", "wealth_change_pct", "high"),
    ("Unhappy % (average)", "unhappy_pct_avg", "low"), ("Unhappy % (worst)", "unhappy_pct_max", "low"),
    ("Happy % (average)", "happy_pct_avg", "high"), ("Idle adults % (average)", "idle_pct_avg", "low"),
    ("Drink per dwarf at end", "drink_per_dwarf_end", "high"),
    ("Meals per dwarf at end", "meals_per_dwarf_end", "high"),
    ("Days a threat could reach them", "days_with_reachable_threat", "low"),
    ("Strange moods", "moods", None), ("Artifacts made", "artifacts", "high"),
    ("Went insane", "insanity", "low"), ("Tantrums", "tantrums", "low"),
    ("Ghosts", "ghosts", "low"), ("Crimes", "crimes", "low"),
    ("Levels built", "projects_finished", None), ("AI actions", "ai_actions", None),
    ("Tokens used", "tokens_used", "low"), ("FPS (average)", "fps_avg", "high"),
]


def compare_table(summaries: list[dict]) -> str:
    """A plain-text table, one column per run; the better value is marked *."""
    heads = [f"{s.get('label') or '?'} ({s.get('mode') or '?'})" for s in summaries]
    width = max([24] + [len(h) + 2 for h in heads])
    lines = ["".ljust(32) + "".join(h.rjust(width) for h in heads)]
    for name, key, better in COMPARE:
        vals = [s.get(key) for s in summaries]
        nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
        best = None
        if better and len(nums) > 1 and len(set(nums)) > 1:
            best = max(nums) if better == "high" else min(nums)
        cells = []
        for v in vals:
            if v is None:
                txt = "-"
            elif isinstance(v, bool):
                txt = "yes" if v else "no"
            elif isinstance(v, float):
                txt = f"{v:,.1f}"
            else:
                txt = f"{v:,}" if isinstance(v, int) else str(v)
            if best is not None and v == best and not isinstance(v, bool):
                txt += " *"
            cells.append(txt.rjust(width))
        lines.append(name.ljust(32) + "".join(cells))
    return "\n".join(lines)


def write_row(path: Path, row: dict) -> None:
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def read_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out = {}
            for k, v in r.items():
                if v in ("", None):
                    out[k] = None
                    continue
                try:
                    out[k] = int(v)
                except ValueError:
                    try:
                        out[k] = float(v)
                    except ValueError:
                        out[k] = v
            rows.append(out)
    return rows


def load_summary(run_dir: Path) -> dict:
    return json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
