"""(0.104.85) The data behind the fort dashboard (the "Fort Watch" artifact).

    python brain\\dashboard_data.py [fort folder name]

Reads the fort's own logs (logs/forts/<fort>/timeline.csv, seasons.csv,
report.md) and the bridge's last report (dfhack-config/ai-overseer/state.json,
when the game folder is known) and writes logs/dashboard/*.json: days (one row
a game week), seasons, now (one row), stress and notes. Claude reads these
files to refresh the dashboard; nothing is sent anywhere by this script.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
OUT = LOGS / "dashboard"
DAYS_PER_YEAR = 336
MONTHS = ["Granite", "Slate", "Felsite", "Hematite", "Malachite", "Galena", "Limestone", "Sandstone",
          "Timber", "Moonstone", "Opal", "Obsidian"]
STRESS = ["miserable", "very_unhappy", "unhappy", "fine", "content", "happy", "ecstatic"]


def _num(v):
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


def day_label(day: int) -> str:
    """'12 Malachite y77' from the absolute game day the timeline counts."""
    y, d = divmod(int(day), DAYS_PER_YEAR)
    m, dd = divmod(d, 28)
    return f"{dd + 1} {MONTHS[m % 12]} y{y}"


def days_rows(timeline: Path, step: int = 7) -> list[dict]:
    rows = list(csv.DictReader(timeline.open(encoding="utf-8")))
    keep = [r for i, r in enumerate(rows) if i % step == 0 or i == len(rows) - 1]
    out = []
    for r in keep:
        day = _num(r.get("day"))
        if day is None:
            continue
        out.append({"day": int(day), "date": day_label(day), "year": round(day / DAYS_PER_YEAR, 3),
                    **{k: _num(r.get(k)) for k in ("pop", "drink_pd", "meals_pd", "unhappy_pct", "happy_pct",
                                                    "idle_pct", "needs_care", "wealth", "deaths", "threats")}})
    return out


SEASONS = ["spring", "summer", "autumn", "winter"]


def season_rows(timeline: Path) -> list[dict]:
    """Each game season from the daily timeline (the fort's seasons.csv can
    lag behind it): days, deaths, days with threats, average and highest
    population, average drink and meals a dwarf, average and highest
    unhappy share, average idle share, wealth at its end."""
    groups: dict = {}
    for r in csv.DictReader(timeline.open(encoding="utf-8")):
        day = _num(r.get("day"))
        if day is None:
            continue
        y, d = divmod(int(day), DAYS_PER_YEAR)
        groups.setdefault((y, min(3, d // 84)), []).append(r)
    out = []
    for (y, q), rs in sorted(groups.items()):
        def col(k):
            return [v for v in (_num(r.get(k)) for r in rs) if isinstance(v, (int, float))]
        def avg(k):
            v = col(k)
            return round(sum(v) / len(v), 1) if v else None
        out.append({"season": f"{SEASONS[q]} y{y}", "year": y, "q": q, "days": len(rs),
                    "deaths": int(sum(col("deaths"))), "threat_days": sum(1 for v in col("threats") if v > 0),
                    "avg_pop": avg("pop"), "high_pop": max(col("pop") or [0]),
                    "avg_drink_pd": avg("drink_pd"), "avg_meals_pd": avg("meals_pd"),
                    "avg_unhappy_pct": avg("unhappy_pct"), "high_unhappy_pct": max(col("unhappy_pct") or [0]),
                    "avg_idle_pct": avg("idle_pct"), "end_wealth": (col("wealth") or [None])[-1]})
    return out


def last_report(report: Path) -> dict:
    """The newest season block of report.md, read into its parts."""
    text = report.read_text(encoding="utf-8")
    blocks = re.split(r"^## ", text, flags=re.M)
    last = blocks[-1] if len(blocks) > 1 else ""
    out = {"heading": last.split("\n", 1)[0].strip(), "fort": "", "phase": "", "siege": "", "works_to": "",
           "lately": [], "refusing": "", "needs_you": []}
    current = None
    for line in last.split("\n")[1:]:
        m = re.match(r"^- \*\*(.+?)\*\*\s*(.*)$", line)
        if m:
            key, rest = m.group(1).rstrip(":"), m.group(2).strip()
            current = None
            if key.startswith("The fort"):
                out["fort"] = rest
            elif key.startswith("Phase"):
                out["phase"] = rest
            elif key.startswith("Ready for a siege"):
                out["siege"] = rest
            elif key.startswith("This season the AI works to"):
                out["works_to"] = rest
            elif key.startswith("Lately"):
                current = "lately"
            elif key.startswith("The game keeps refusing"):
                out["refusing"] = rest
            elif key.startswith("Needs you"):
                current = "needs_you"
            continue
        m2 = re.match(r"^\s+- (.+)$", line)
        if m2 and current:
            out[current].append(m2.group(1).strip())
    return out


def now_row(state: dict | None, rep: dict, days: list[dict]) -> dict:
    last = days[-1] if days else {}
    row = {"report": rep.get("heading", ""), "phase": rep.get("phase", ""), "siege": rep.get("siege", ""),
           "pop": last.get("pop"), "unhappy_pct": last.get("unhappy_pct"), "idle_pct": last.get("idle_pct"),
           "wealth": last.get("wealth"), "drink_pd": last.get("drink_pd"), "meals_pd": last.get("meals_pd")}
    m = re.search(r"(\d+) FPS", rep.get("fort", ""))
    row["fps"] = int(m.group(1)) if m else None
    if state:
        d = state.get("date") or {}
        row["date"] = f"{d.get('day')} {d.get('month')} y{d.get('year')}"
        g = (state.get("military") or {}).get("gear") or {}
        row.update(soldiers=g.get("soldiers"), on_duty=g.get("on_duty"), armed=g.get("armed"),
                   helmed=g.get("helmed"))
        soc = state.get("society") or {}
        an = soc.get("animals") or {}
        row.update(war_dogs_training=an.get("in_training"), war_dogs=an.get("war_trained"),
                   recreation=(soc.get("recreation") or {}).get("members"))
        st, sp = state.get("stocks") or {}, state.get("supplies") or {}
        row.update(cheese=st.get("cheese"), eggs=st.get("eggs"), rough_gems=st.get("rough_gems"),
                   cut_gems=st.get("cut_gems"), nest_boxes=sp.get("nest_boxes"))
        bwf = ((state.get("needs") or {}).get("needs") or {}).get("BeWithFriends") or {}
        row["want_friends"] = bwf.get("badly")
        row["bridge"] = state.get("bridge_version")
    return row


def stress_rows(state: dict | None) -> list[dict]:
    s = ((state or {}).get("dwarves") or {}).get("stress") or {}
    return [{"level": k.replace("_", " "), "order": i, "dwarves": int(s.get(k) or 0)} for i, k in enumerate(STRESS)]


def notes_rows(rep: dict) -> list[dict]:
    out = []
    for i, t in enumerate(rep.get("needs_you") or []):
        out.append({"id": f"you{i}", "kind": "needs you", "text": t})
    for i, t in enumerate(reversed(rep.get("lately") or [])):
        out.append({"id": f"late{i}", "kind": "lately", "text": t})
    for i, t in enumerate(x.strip() for x in (rep.get("works_to") or "").split(";") if x.strip()):
        out.append({"id": f"work{i}", "kind": "works to", "text": t})
    if rep.get("refusing"):
        out.append({"id": "refuse0", "kind": "refusing", "text": rep["refusing"]})
    return out


def fort_folder(name: str | None) -> Path:
    forts = LOGS / "forts"
    if name:
        return forts / name
    # the fort most recently written
    dirs = [p for p in forts.iterdir() if p.is_dir() and (p / "timeline.csv").exists()]
    return max(dirs, key=lambda p: (p / "timeline.csv").stat().st_mtime)


def state_path() -> Path | None:
    """The bridge's last report, in the game folder the keeper last saw
    (logs/last-fort.json, written by the reviver)."""
    try:
        game = json.loads((LOGS / "last-fort.json").read_text(encoding="utf-8")).get("df_path")
        if game:
            p = Path(game) / "dfhack-config" / "ai-overseer" / "state.json"
            return p if p.exists() else None
    except (OSError, ValueError, AttributeError):
        pass
    return None


def build(folder: Path, state: dict | None, out: Path = OUT) -> dict:
    days = days_rows(folder / "timeline.csv")
    seasons = season_rows(folder / "timeline.csv")
    rep = last_report(folder / "report.md") if (folder / "report.md").exists() else {}
    files = {"days": days, "seasons": seasons, "now": [now_row(state, rep, days)],
             "stress": stress_rows(state), "notes": notes_rows(rep)}
    out.mkdir(parents=True, exist_ok=True)
    for k, rows in files.items():
        (out / f"{k}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return {k: len(v) for k, v in files.items()}


def main(argv: list[str]) -> int:
    folder = fort_folder(argv[1] if len(argv) > 1 else None)
    sp = state_path()
    state = json.loads(sp.read_text(encoding="utf-8")) if sp else None
    counts = build(folder, state)
    print(f"dashboard data for {folder.name}: " + ", ".join(f"{k} {v}" for k, v in counts.items())
          + f" -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
