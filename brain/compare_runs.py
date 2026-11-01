"""Compare scenario runs by what each fort did and became (14.1's exit test).

    python brain/compare_runs.py                    the two newest runs
    python brain/compare_runs.py war-hold monastery runs whose folder names contain these
    python brain/compare_runs.py A B --end-state A=path\\to\\state.json
                                                    a run without end-state.json (runs before
                                                    0.100): use a saved fort report instead

`scenario.py compare` lines up the daily numbers (population, unhappiness,
wealth). This answers the other question: do two forts with opposite presets
look and run differently? It reads each run's journal (decisions.jsonl), its
daily numbers (metrics.csv) and, since 0.100, the fort's report at the start
and end of the run (start-state.json, end-state.json), and writes a side by
side report to logs/runs/compare-<a>-vs-<b>.md as well as printing it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bridge import LOG_DIR  # noqa: E402

RUNS_DIR = LOG_DIR / "runs"

# what the presets lean on, in the order the report shows them
TRAITS = ("militarism", "fortification", "caution", "justice", "piety", "welfare", "outsiders", "trade",
          "greed", "grandeur", "craftsmanship", "growth", "mining", "agriculture", "surface", "engineering",
          "industriousness", "deference", "spacing", "verticality", "husbandry", "stockpile")
ZONES = ("Barracks", "ArcheryRange", "Dungeon", "DiningHall", "MeetingHall", "Office", "Bedroom", "Tomb", "Pen")
LOCATIONS = ("TEMPLE", "GUILDHALL", "INN_TAVERN", "LIBRARY", "HOSPITAL")


def _d(x) -> dict:
    return x if isinstance(x, dict) else {}


def _l(x) -> list:
    return x if isinstance(x, list) else []


def find_runs(names: list[str]) -> list[list[Path]]:
    """Each side of the comparison: one run folder, or several joined with +
    (a run stopped and started again on the same fort counts as one)."""
    runs = sorted(p for p in RUNS_DIR.iterdir() if p.is_dir()) if RUNS_DIR.is_dir() else []
    if not names:
        return [[p] for p in runs[-2:]]
    out = []
    for n in names:
        side = []
        for part in n.split("+"):
            hits = [p for p in runs if part.lower() in p.name.lower()]
            if not hits:
                raise SystemExit(f"No run folder in {RUNS_DIR} matches {part!r}")
            side.append(hits[-1])                # the newest of the matches
        out.append(sorted(side))
    return out


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_lines(path: Path) -> list[dict]:
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def read_metrics(path: Path) -> list[dict]:
    try:
        import metrics
        return metrics.read_rows(path)
    except Exception:  # noqa: BLE001  (a run without metrics still compares by its journal)
        return []


def fort_facts(state: dict | None) -> dict:
    """The numbers a fort's report gives about its character."""
    if not state:
        return {}
    mil = _d(state.get("military"))
    gear = _d(mil.get("gear"))
    squads = [q for q in _l(mil.get("squads")) if isinstance(q, dict)]
    dw = _d(state.get("dwarves"))
    b = _d(state.get("buildings"))
    zones = _d(b.get("zones"))
    locs = _d(_d(state.get("locations")).get("count"))
    shops = sum(int(v or 0) for v in _d(b.get("workshops")).values()) + sum(int(v or 0) for v in _d(b.get("furnaces")).values())
    pop = int(dw.get("total") or 0)
    soldiers = int(gear.get("soldiers") or 0)
    out = {
        "population": pop,
        "soldiers": soldiers,
        "soldier share %": round(100 * soldiers / pop, 1) if pop else 0,
        "squads": len(squads),
        "squads training": sum(1 for q in squads if "train" in str(q.get("routine") or "").lower()),
        "crossbow squads": sum(1 for q in squads if "crossbow" in str(q.get("ai_uniform") or "").lower()),
        "soldiers armed": int(gear.get("armed") or 0),
        "wealth": int(state.get("wealth") or 0) if isinstance(state.get("wealth"), (int, float)) else 0,
        "workshops": shops,
        "statues": int(_d(b.get("other")).get("Statue") or 0),
        "stockpiles": int(b.get("stockpiles") or 0),
        "levels finished": int(_d(state.get("projects")).get("finished") or 0),
        "drink": int(_d(state.get("stocks")).get("drink") or 0),
    }
    for z in ZONES:
        out[f"zone: {z}"] = int(zones.get(z) or 0)
    for k in LOCATIONS:
        out[f"location: {k.lower()}"] = int(locs.get(k) or 0)
    return out


def settings_of(state: dict | None) -> tuple[dict, dict]:
    se = _d(_d(state).get("settings"))
    rules = {k: se.get(k) for k in ("attack_policy", "fill_squads", "train_squads", "gate_lever", "fortify_entrances",
                                    "accept_visitors", "answer_locations", "fort_goal",
                                    "hospital_burrow")}      # (0.104.168)
    levels = _d(se.get("levels"))
    rules.update({f"level {k}": v for k, v in sorted(levels.items())})
    return _d(se.get("traits")), rules


def journal_facts(decisions: list[dict]) -> dict:
    done = [d for d in decisions if d.get("kind") == "decision" and _d(d.get("result")).get("ok") is True]
    by_type = Counter(str(_d(d.get("action")).get("type")) for d in done)
    by_rule = Counter(str(d.get("rule")) for d in done)
    projects = [str(_d(d.get("action")).get("kind")) for d in done if _d(d.get("action")).get("type") == "start_project"]
    petitions = [d for d in done if _d(d.get("action")).get("type") == "answer_petition"]
    return {
        "actions done": len(done),
        "levels started": ", ".join(f"{k} x{n}" for k, n in Counter(projects).most_common()) or "none",
        "squads made": by_type.get("make_squad", 0),
        "uniforms set": by_type.get("set_uniform", 0) + by_type.get("set_uniform_weapon", 0),
        "gear orders": sum(1 for d in done if _d(d.get("action")).get("type") == "work_order"
                           and str(_d(d.get("action")).get("recipe", "")).startswith("metal_")),
        "squad attack orders": by_type.get("squad_attack", 0),
        "gate actions": sum(n for t, n in by_type.items() if "gate" in t or t in ("fortify_entrance", "place_traps", "link_lever")),
        "petitions agreed": sum(1 for d in petitions if _d(d.get("action")).get("accept") is True),
        "petitions declined": sum(1 for d in petitions if _d(d.get("action")).get("accept") is False),
        "trade deals": by_type.get("trade_deal", 0),
        "goods to the depot": by_type.get("bring_goods", 0),
        "trinkets given": by_type.get("give_trinkets", 0),
        "top rules": ", ".join(f"{r} {n}" for r, n in by_rule.most_common(8)),
    }


def metrics_facts(rows: list[dict]) -> dict:
    if not rows:
        return {}
    def avg(k):
        vals = [float(r[k]) for r in rows if isinstance(r.get(k), (int, float))]
        return round(sum(vals) / len(vals), 1) if vals else None
    return {
        "days played": len(rows),
        "dates": f"{rows[0].get('date')} to {rows[-1].get('date')}",
        "unhappy % (average)": avg("unhappy_pct"),
        "idle % (average)": avg("idle_pct"),
        "deaths": sum(int(r.get("citizen_deaths") or 0) for r in rows),
        "arrivals": sum(int(r.get("arrivals") or 0) for r in rows),
        "moods": sum(int(r.get("moods") or 0) for r in rows),
        "tantrums": sum(int(r.get("tantrums") or 0) for r in rows),
    }


def load(side: list[Path], end_override: Path | None) -> dict:
    """One side: its runs in order, the first one's start, the last one's end."""
    first, last = side[0], side[-1]
    start = read_json(first / "start-state.json")
    end = read_json(end_override) if end_override else read_json(last / "end-state.json")
    decisions, rows = [], []
    for run in side:
        decisions += read_lines(run / "decisions.jsonl")
        rows += read_metrics(run / "metrics.csv")
    return {"name": "+".join(p.name for p in side), "run": read_json(last / "run.json") or {},
            "start": start, "end": end,
            "journal": journal_facts(decisions),
            "metrics": metrics_facts(rows)}


def fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int) and abs(v) >= 10000:
        return f"{v:,}"
    return str(v)


def table(title: str, rows: list[tuple[str, list]], names: list[str]) -> list[str]:
    out = [f"## {title}", "", "| | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for label, vals in rows:
        mark = " **≠**" if len({fmt(v) for v in vals}) > 1 else ""
        out.append(f"| {label}{mark} | " + " | ".join(fmt(v) for v in vals) + " |")
    return out + [""]


def report(runs: list[dict]) -> str:
    names = [r["run"].get("label") or r["name"] for r in runs]
    lines = [f"# {' vs '.join(names)}", "",
             "Rows marked **≠** differ between the runs. 'Start' and 'end' come from the fort's report at the "
             "run's first and last day; a run without end-state.json shows '-'.", ""]
    traits = [settings_of(r["end"] or r["start"])[0] for r in runs]
    keys = [k for k in TRAITS if any(t.get(k) for t in traits)]
    lines += table("Sliders (the preset)", [(k, [t.get(k, 0) for t in traits]) for k in keys], names)
    rules = [settings_of(r["end"] or r["start"])[1] for r in runs]
    rkeys = sorted({k for r in rules for k in r})
    lines += table("Rules tab", [(k, [r.get(k) for r in rules]) for k in rkeys], names)
    ends = [fort_facts(r["end"]) for r in runs]
    starts = [fort_facts(r["start"]) for r in runs]
    fkeys = list(dict.fromkeys(k for f in ends + starts for k in f))
    rows = []
    for k in fkeys:
        vals = []
        for s, e in zip(starts, ends):
            if k in e and k in s and isinstance(e[k], (int, float)) and isinstance(s[k], (int, float)) and e[k] != s[k]:
                d = e[k] - s[k]
                vals.append(f"{fmt(e[k])} ({'+' if d > 0 else ''}{round(d, 1) if isinstance(d, float) else d})")
            else:
                vals.append(e.get(k, s.get(k)))
        rows.append((k, vals))
    lines += table("The fort at the end (change over the run)", rows, names)
    jkeys = list(dict.fromkeys(k for r in runs for k in r["journal"]))
    lines += table("What the AI did", [(k, [r["journal"].get(k) for r in runs]) for k in jkeys], names)
    mkeys = list(dict.fromkeys(k for r in runs for k in r["metrics"]))
    lines += table("Day by day", [(k, [r["metrics"].get(k) for r in runs]) for k in mkeys], names)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="*", help="parts of run folder names (default: the two newest)")
    ap.add_argument("--end-state", action="append", default=[],
                    help="NAME=path: a fort report to use as that run's end state")
    args = ap.parse_args(argv)
    paths = find_runs(args.runs)
    if len(paths) < 2:
        print("Need two runs to compare.")
        return 1
    overrides = {}
    for item in args.end_state:
        name, _, path = item.partition("=")
        overrides[name.lower()] = Path(path)
    runs = []
    for side in paths:
        ov = next((v for k, v in overrides.items() if any(k in p.name.lower() for p in side)), None)
        runs.append(load(side, ov))
    text = report(runs)
    print(text)
    out = RUNS_DIR / ("compare-" + "-vs-".join((r["run"].get("label") or r["name"]) for r in runs) + ".md")
    try:
        out.write_text(text, encoding="utf-8")
        print(f"\n(written to {out})")
    except OSError as e:
        print(f"\n(couldn't write {out}: {e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
