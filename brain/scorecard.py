"""The slider scorecard (14.1): does each preset's fort win its own lines?

    python brain/scorecard.py                  the DF-AI folders beside this one (DF-AI, DF-AI-B...),
                                               compared at the newest season every fort has
    python brain/scorecard.py --now            each fort's newest season instead (unequal ages)
    python brain/scorecard.py --at 252-spring  that season
    python brain/scorecard.py --fort A=C:\\...\\DF-AI --fort B=...   other folders

Each fort's keeper saves a copy of the full report at the start of every season
(logs/forts/<fort>/states/<year>-<season>.json) and its journal
(journal*.jsonl). Forts that began from the same embark are compared at the
same game date, so a fort restarted later is judged at its own age. Per slider,
2-4 lines of things seen in the game, and the presets that should come out on
top (high) or at the bottom (low). A line passes when the best (and the worst)
fort is one of those, "half" when only one side is; "flat" when every fort has the same value; "no data" when the
report doesn't carry it. Written to logs/scorecard.md and printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

SEASONS = ("spring", "summer", "autumn", "winter")

# what the presets are, short names for the table
SHORT = {"War-hold": "War", "Monastery": "Mon", "Merchant city": "Mer", "Hermit hold": "Her",
         "Deep mine": "Deep", "Garden fort": "Gar"}

# The actions that are a fort's gate works
GATE_WORKS = ("build_gate_doors", "fortify_entrance", "cut_entrance", "link_lever", "place_traps",
              "guard_gate", "gate_dogs", "arm_gates")


def _d(x) -> dict:
    return x if isinstance(x, dict) else {}


def _l(x) -> list:
    return x if isinstance(x, list) else []


def season_key(name: str) -> tuple[int, int] | None:
    """'252-spring' -> (252, 0)."""
    try:
        y, s = name.split("-", 1)
        return int(y), SEASONS.index(s)
    except (ValueError, IndexError):
        return None


def read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- one fort

class Fort:
    """A DF-AI folder: its preset, its season states and its journal."""

    def __init__(self, label: str, folder: Path):
        self.label, self.folder = label, Path(folder)
        self.fort_dir = self._fort_dir()
        self.states = {}
        if self.fort_dir:
            for p in (self.fort_dir / "states").glob("*.json"):
                k = season_key(p.stem)
                if k:
                    self.states[k] = p
        self.preset = self._preset()
        self._journal = None

    def _fort_dir(self) -> Path | None:
        """The fort with the newest season state (a folder can hold old forts)."""
        best, when = None, -1.0
        for d in (self.folder / "logs" / "forts").glob("*"):
            st = list((d / "states").glob("*.json")) if d.is_dir() else []
            if st:
                t = max(p.stat().st_mtime for p in st)
                if t > when:
                    best, when = d, t
        return best

    def _preset(self) -> str:
        if self.states:
            s = read_json(self.states[max(self.states)]) or {}
            p = _d(s.get("settings")).get("preset")
            if p:
                return p
        kp = read_json(self.folder / "logs" / "keeper-preset.json") or {}
        names = [_d(v).get("name") for v in kp.values() if _d(v).get("name")]
        return names[-1] if names else "?"

    def journal(self) -> list[dict]:
        if self._journal is None:
            out = []
            if self.fort_dir:
                files = sorted(self.fort_dir.glob("journal.*.jsonl"), key=lambda p: -int(p.suffixes[0][1:])
                               if p.suffixes[0][1:].isdigit() else 0)
                files.append(self.fort_dir / "journal.jsonl")
                for f in files:
                    try:
                        text = f.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    for line in text.splitlines():
                        try:
                            out.append(json.loads(line))
                        except ValueError:
                            pass
            self._journal = out
        return self._journal

    def state_at(self, key) -> dict | None:
        p = self.states.get(key)
        return read_json(p) if p else None


def before(entry: dict, date: dict) -> bool:
    """Is a journal entry dated before the state's date (year, tick)?"""
    d = entry.get("date")
    if isinstance(d, dict) and "year" in d:
        return (d.get("year", 0), d.get("tick", 0)) < (date.get("year", 0), date.get("tick", 0))
    ev = _d(entry.get("event"))
    if "year" in ev:
        return (ev.get("year", 0), ev.get("tick", 0)) < (date.get("year", 0), date.get("tick", 0))
    return False


# ---------------------------------------------------------------- measures

def journal_counts(entries: list[dict], date: dict) -> dict:
    """What the fort did up to the date: actions that worked, by type, and a few sums."""
    ok, seen = Counter(), Counter()
    trade_value, petitions_yes, petitions_no = 0, 0, 0
    levels = []
    for e in entries:
        if e.get("kind") != "decision" or not before(e, date):
            continue
        a, r = _d(e.get("action")), _d(e.get("result"))
        t = a.get("type")
        if not t:
            continue
        seen[t] += 1
        if not r.get("ok"):
            continue
        ok[t] += 1
        if t == "bring_goods":
            trade_value += r.get("value") or 0
        elif t == "answer_petition":
            if r.get("accepted") or a.get("accept"):
                petitions_yes += 1
            else:
                petitions_no += 1
        elif t == "start_project":
            levels.append({"kind": r.get("kind") or a.get("kind"), "z": r.get("z"),
                           "tiles": r.get("tiles") or r.get("designated")})
    return {"ok": ok, "seen": seen, "trade_value": trade_value, "petitions_yes": petitions_yes,
            "petitions_no": petitions_no, "levels": levels}


def pct(a, b):
    return round(100.0 * a / b, 1) if a is not None and b else None


def per(a, b):
    return round(a / b, 1) if a is not None and b else None


def measures(s: dict, j: dict) -> dict:
    """Every number the lines use, from one season state and the journal up to it."""
    dw = _d(s.get("dwarves"))
    adults, total = dw.get("adults") or 0, dw.get("total") or 0
    b = _d(s.get("buildings"))
    other, zones = _d(b.get("other")), _d(b.get("zones"))
    stress = _d(dw.get("stress"))
    unhappy = sum(stress.get(k, 0) for k in ("unhappy", "very_unhappy", "miserable"))
    locs = _d(_d(s.get("locations")).get("count"))
    temples = [x for x in _l(_d(s.get("locations")).get("list")) if _d(x).get("type") == "TEMPLE"]
    farms = _d(s.get("farms"))
    stocks = _d(s.get("stocks"))
    others = _d(s.get("others_on_map"))
    surface_z = _d(s.get("crossings")).get("z")
    levels = j["levels"]
    lz = [lv["z"] for lv in levels if isinstance(lv.get("z"), int)]
    tiles = [lv["tiles"] for lv in levels if isinstance(lv.get("tiles"), (int, float)) and lv["tiles"] > 0]
    kinds = Counter(lv.get("kind") for lv in levels)
    ok = j["ok"]
    traps = sum(v for k, v in other.items() if "Trap" in k and k != "TractionBench")
    meals = _d(s.get("supplies")).get("meal_servings")
    good_meals = _d(s.get("supplies")).get("good_meals")
    return {
        "pop": total,
        "soldier_pct": pct(dw.get("in_squads"), adults),
        "barracks": zones.get("Barracks", 0) + zones.get("ArcheryRange", 0) + kinds.get("barracks", 0),
        "traps": traps,
        "bridges": other.get("Bridge", 0) + other.get("Floodgate", 0) + other.get("Hatch", 0),
        "gate_works": sum(ok.get(t, 0) for t in GATE_WORKS),
        "levers": other.get("Lever", 0),
        "mechanisms": stocks.get("mechanisms"),
        "alerts": ok.get("civ_alert", 0),
        "jails": zones.get("Dungeon", 0) + len(_l(_d(s.get("justice")).get("jails"))),
        "restraints": _d(s.get("justice")).get("restraints"),
        "temples": locs.get("TEMPLE", 0),
        "temple_value": max((_d(t).get("value") or 0 for t in temples), default=0),
        "unhappy_pct": pct(unhappy, total),
        "good_meals_pd": per(good_meals, total),
        "visitors": others.get("visitors"),
        "guildhalls": locs.get("GUILDHALL", 0),
        "petitions_yes": j["petitions_yes"],
        "petitions_no": j["petitions_no"],
        "petitions_waiting": len(_l(_d(s.get("petitions")).get("pending"))),
        "trade_runs": ok.get("bring_goods", 0),
        "trade_value": j["trade_value"],
        "wealth_pd": per(s.get("wealth"), total),
        "gems": (stocks.get("cut_gems") or 0) + (stocks.get("rough_gems") or 0),
        "statues": other.get("Statue", 0),
        "halls": zones.get("MeetingHall", 0),
        "gardens": kinds.get("garden", 0),
        "legendary_pct": pct(dw.get("legendary"), adults),
        "craft_shops": _d(b.get("workshops")).get("Craftsdwarfs", 0),
        "ore": _d(s.get("industry")).get("ore_stock"),
        "ore_runs": ok.get("mine_ore", 0),
        "z_span": (max(lz) - min(lz) + 1) if lz else None,
        "depth": (surface_z - min(lz)) if lz and isinstance(surface_z, int) else None,
        "levels_up": sum(1 for z in lz if isinstance(surface_z, int) and z >= surface_z) if lz else None,
        "surface_plots": farms.get("plots_surface"),
        "farm_tiles": farms.get("tiles"),
        "plots": farms.get("plots"),
        "animals": others.get("tame_animals"),
        "pastures": _d(s.get("society")).get("pastures"),
        "idle_pct": pct(dw.get("idle_adults"), adults),
        "suites": kinds.get("suites", 0),
        "offices": zones.get("Office", 0),
        "level_tiles": round(sum(tiles) / len(tiles)) if tiles else None,
        "stockpiles": b.get("stockpiles"),
        "stores_pd": per((stocks.get("drink") or 0) + (meals or 0), total),
        "levels": len(levels),
        "kinds": dict(kinds),
    }


# ---------------------------------------------------------------- the lines

# (slider, what, measure, high presets, low presets)
W, M, ME, H, D, G = "War-hold", "Monastery", "Merchant city", "Hermit hold", "Deep mine", "Garden fort"
LINES = [
    ("Militarism", "soldiers, % of adults", "soldier_pct", {W}, {M}),
    ("Militarism", "barracks and ranges", "barracks", {W}, {M}),
    ("Fortification", "traps", "traps", {W}, set()),
    ("Fortification", "bridges, floodgates, hatches", "bridges", {W}, set()),
    ("Fortification", "gate works done", "gate_works", {W, H}, set()),
    ("Engineering", "levers", "levers", {W, D}, set()),
    ("Engineering", "mechanisms in store", "mechanisms", {W, D}, set()),
    ("Caution", "alarms raised", "alerts", {W, H}, {D}),
    ("Justice", "jail cells", "jails", {W}, {M}),
    ("Justice", "restraints", "restraints", {W}, {M}),
    ("Piety", "temples", "temples", {M}, set()),
    ("Piety", "best temple's value", "temple_value", {M}, set()),
    ("Welfare", "unhappy, % (lowest wins)", "-unhappy_pct", {M, G}, {W}),
    ("Welfare", "good meals a dwarf", "good_meals_pd", {M, G}, {W}),
    ("Outsiders", "visitors on the map", "visitors", {ME, M}, {H, W}),
    ("Outsiders", "guildhalls", "guildhalls", {ME, M}, {H, W}),
    ("Outsiders", "petitions agreed", "petitions_yes", {ME, M}, {H, W}),
    ("Outsiders", "petitions declined", "petitions_no", {H, W}, {ME, M}),
    ("Trade", "goods taken to caravans", "trade_runs", {ME}, {H}),
    ("Trade", "value taken to caravans", "trade_value", {ME}, {H}),
    ("Greed", "wealth a dwarf", "wealth_pd", {ME, H}, {M}),
    ("Greed", "gems kept", "gems", {ME, H}, {M}),
    ("Grandeur", "statues", "statues", {M, G}, {W}),
    ("Grandeur", "meeting halls", "halls", {M, G}, {W}),
    ("Grandeur", "garden levels", "gardens", {M, G}, {W}),
    ("Craftsmanship", "legendary, % of adults", "legendary_pct", {ME, M}, set()),
    ("Craftsmanship", "craftsdwarf's shops", "craft_shops", {ME, M}, set()),
    ("Growth", "population", "pop", {ME}, {H}),
    ("Mining", "ore in store", "ore", {D}, {G}),
    ("Mining", "veins mined", "ore_runs", {D}, {G}),
    ("Verticality", "levels' height span", "z_span", {D}, set()),
    ("Verticality", "deepest level below the surface", "depth", {D}, set()),
    ("Surface", "levels at or above the surface", "levels_up", {G, ME}, {D, H}),
    ("Surface", "surface farm plots", "surface_plots", {G, ME}, {D, H}),
    ("Agriculture", "farm tiles", "farm_tiles", {G}, {D}),
    ("Agriculture", "farm plots", "plots", {G}, {D}),
    ("Husbandry", "tame animals", "animals", {G}, set()),
    ("Husbandry", "pastures", "pastures", {G}, set()),
    ("Industriousness", "idle, % of adults (lowest wins)", "-idle_pct", {D}, {M}),
    ("Deference", "suite levels", "suites", {W, ME}, {H}),
    ("Deference", "offices", "offices", {W, ME}, {H}),
    ("Spacing", "tiles a level (smallest wins)", "-level_tiles", {W, D}, set()),
    ("Stockpile", "stockpiles", "stockpiles", {H, ME}, set()),
    ("Stockpile", "drink and meals a dwarf", "stores_pd", {H, ME}, set()),
]


def judge(values: dict[str, float | None], high: set, low: set) -> str:
    """values: preset -> number (bigger is 'more of the slider'). 'pass', 'fail',
    'flat' or 'no data'; a line with both sides passes when both do, and is
    'half' when only one does."""
    have = {p: v for p, v in values.items() if v is not None}
    want = (high | low) & set(values)
    if len(have) < 2 or not (want & set(have)):
        return "no data"
    vals = list(have.values())
    if max(vals) == min(vals):
        return "flat"
    parts = []
    if high & set(values):
        top = max(vals)
        parts.append(any(have.get(p) == top for p in high))
    if low & set(values):
        bottom = min(vals)
        parts.append(any(have.get(p) == bottom for p in low))
    if all(parts):
        return "pass"
    return "half" if any(parts) else "fail"


def fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def score(forts: list[Fort], at: str | None, now: bool) -> tuple[str, list[dict]]:
    """The markdown report and the rows."""
    forts = [f for f in forts if f.states]
    if not forts:
        return "No fort with season states found.\n", []
    if now:
        keys = {f.label: max(f.states) for f in forts}
        title = "each fort's newest season"
    else:
        if at:
            k = season_key(at)
            if not k:
                raise SystemExit(f"--at wants YEAR-SEASON, like 252-spring (got {at!r})")
        else:
            common = set.intersection(*(set(f.states) for f in forts))
            if not common:
                raise SystemExit("The forts have no season in common: use --now")
            k = max(common)
        keys = {f.label: k for f in forts}
        title = f"all at {k[0]}-{SEASONS[k[1]]}"
    data = {}
    for f in forts:
        s = f.state_at(keys[f.label])
        if s is None:
            continue
        data[f.label] = (f, s, measures(s, journal_counts(f.journal(), _d(s.get("date")))))
    labels = list(data)
    head = ["Slider", "Line"] + [f"{lb} {SHORT.get(data[lb][0].preset, data[lb][0].preset)}" for lb in labels] + \
        ["Should win", "Result"]
    rows, out = [], []
    for slider, what, key, high, low in LINES:
        neg = key.startswith("-")
        k = key.lstrip("-")
        by_preset = {}
        raw = {}
        for lb in labels:
            f, _, m = data[lb]
            v = m.get(k)
            raw[lb] = v
            by_preset[f.preset] = (-v if neg and v is not None else v)
        res = judge(by_preset, high, low)
        should = ", ".join(SHORT.get(p, p) for p in sorted(high)) + \
            ((" / low: " + ", ".join(SHORT.get(p, p) for p in sorted(low))) if low else "")
        rows.append({"slider": slider, "line": what, "values": raw, "result": res})
        out.append([slider, what] + [fmt(raw[lb]) for lb in labels] + [should, res])
    md = [f"# Slider scorecard: {title}", ""]
    md.append("| Fort | Preset | Season | Population | Levels |")
    md.append("| --- | --- | --- | --- | --- |")
    for lb in labels:
        f, s, m = data[lb]
        dt = _d(s.get("date"))
        md.append(f"| {lb} | {f.preset} | {dt.get('season', '?')} {dt.get('year', '?')} | {m['pop']} | {m['levels']} |")
    md += ["", "| " + " | ".join(head) + " |", "|" + " --- |" * len(head)]
    md += ["| " + " | ".join(r) + " |" for r in out]
    tally = Counter(r["result"] for r in rows)
    md += ["", "**" + ", ".join(f"{n} {k}" for k, n in tally.most_common()) + "** of " + str(len(rows)) + " lines.", ""]
    by_slider = {}
    for r in rows:
        by_slider.setdefault(r["slider"], []).append(r["result"])
    good = [s for s, rs in by_slider.items() if all(x == "pass" for x in rs)]
    bad = [s for s, rs in by_slider.items() if not any(x in ("pass", "half") for x in rs)]
    md.append("Sliders that win every line: " + (", ".join(good) or "none") + ".")
    md.append("Sliders that win none: " + (", ".join(bad) or "none") + ".")
    kinds = sorted({k for lb in labels for k in data[lb][2]["kinds"] if k})
    if kinds:
        md += ["", "Levels started, by kind:", "", "| Kind | " + " | ".join(labels) + " |",
               "|" + " --- |" * (len(labels) + 1)]
        for k in kinds:
            md.append(f"| {k} | " + " | ".join(str(data[lb][2]["kinds"].get(k, 0)) for lb in labels) + " |")
    return "\n".join(md) + "\n", rows


def default_forts(here: Path) -> list[Fort]:
    """DF-AI and DF-AI-<x> beside this folder, labelled A, B, C..."""
    parent = here.parent
    out = []
    for p in sorted(parent.glob("DF-AI*")):
        if not p.is_dir() or not (p / "logs").is_dir():
            continue
        tail = p.name[len("DF-AI"):].lstrip("-")
        out.append(Fort(tail or "A", p))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fort", action="append", default=[], help="LABEL=DF-AI folder (repeatable)")
    ap.add_argument("--at", help="YEAR-SEASON to compare at")
    ap.add_argument("--now", action="store_true", help="each fort's newest season")
    ap.add_argument("--out", help="where to write the report (default logs/scorecard.md)")
    a = ap.parse_args(argv)
    here = Path(__file__).resolve().parent.parent
    if a.fort:
        forts = []
        for x in a.fort:
            lb, _, p = x.partition("=")
            forts.append(Fort(lb, Path(p)))
    else:
        forts = default_forts(here)
    md, _ = score(forts, a.at, a.now)
    out = Path(a.out) if a.out else here / "logs" / "scorecard.md"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
    except OSError as e:
        print(f"(could not write {out}: {e})")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
