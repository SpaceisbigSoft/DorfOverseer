"""The slider scorecard (14.1): does each preset's fort win its own lines?

    python brain/scorecard.py                  the DF-AI folders beside this one (DF-AI, DF-AI-B...),
                                               compared at the newest season every fort has
    python brain/scorecard.py --now            each fort's newest season instead (unequal ages)
    python brain/scorecard.py --at 252-spring  that season
    python brain/scorecard.py --fort A=C:\\...\\DF-AI --fort B=...   other folders
    python brain/scorecard.py --every 2y       a series: every 2 game years (or --every 3 seasons)
                                               back from the newest common season, with a summary

Each fort's keeper saves a copy of the full report at the start of every season
(logs/forts/<fort>/states/<year>-<season>.json) and its journal
(journal*.jsonl). Forts that began from the same embark are compared at the
same game date, so a fort restarted later is judged at its own age. Per slider,
2-4 lines of things seen in the game, and the presets that should come out on
top (high) or at the bottom (low). A line passes when the best (and the worst)
fort is one of those, "half" when only one side is, or when the best (worst)
is shared with a fort that shouldn't be there; "flat" when every fort has the
same value; "no data" when the report doesn't carry it. A health table beside
it, with fixed bars (no ranking): failed moods, thirst deaths, unhappy, idle,
deaths by cause.

(0.105.26) Runs: a fort restarted fresh from the same save keeps its logs in
the same folder. The keeper's logs/keeper-preset.json stamps each run ("run",
set when the site has no entry: clear the site's entries for a fresh start);
each kept state carries its "_run". States and journal lines of an older run
are left out, and said so.

Written to logs/scorecards/<year>-<season>.md (now.md with --now), the newest
also to logs/scorecard.md, and a summary across seasons to
logs/scorecards/summary.md (from summary.json, kept between runs). Printed too.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import customs
from digest import _d, _l
from util import load_json

try:                    # (D0) the design language (brain/design.py): its level signature
    import design as _design
except ImportError:     # pragma: no cover - before the Design track's merge
    _design = None

SEASONS = ("spring", "summer", "autumn", "winter")

# what the presets are, short names for the table
SHORT = {"War-hold": "War", "Monastery": "Mon", "Merchant city": "Mer", "Hermit hold": "Her",
         "Deep mine": "Deep", "Garden fort": "Gar"}

# The actions that are a fort's gate works
GATE_WORKS = ("build_gate_doors", "fortify_entrance", "cut_entrance", "link_lever", "place_traps",
              "guard_gate", "gate_dogs", "arm_gates",
              "build_gatehouse")                 # (0.105.23) the War-hold's gatehouse

# (0.105.29) the customs' measure keys, by owner preset: custom_M = Monastery levels built by its customs
CUSTOM_KEYS = {"War-hold": "W", "Monastery": "M", "Merchant city": "ME", "Hermit hold": "H",
               "Deep mine": "D", "Garden fort": "G"}
CUSTOM_IDS = {o: {c for c, (_cond, own, _w) in customs.CUSTOMS.items() if own == o} for o in CUSTOM_KEYS}



def season_key(name: str) -> tuple[int, int] | None:
    """'252-spring' -> (252, 0)."""
    try:
        y, s = name.split("-", 1)
        return int(y), SEASONS.index(s)
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------- runs

def state_run(path: Path) -> str | None:
    """The run a kept season state belongs to (brain/overseer.py keep_state
    writes "_run" first); None for one kept before runs were marked."""
    try:
        with open(path, "rb") as f:
            head = f.read(200).decode("utf-8", "replace")
    except OSError:
        return None
    m = re.match(r'\{"_run": "([^"]*)"', head)
    return m.group(1) if m else None


def _site(key: str) -> str:
    return str(key).rpartition("#")[2]


def dir_site(name: str) -> str:
    """logs/forts/<save>-<site>, run-<id>-<site>: the site id."""
    return name.rpartition("-")[2]


def canonical_dir(key: str) -> str:
    """The logs/forts folder name brain/memstore.py fort_dir gives a fort key
    (without its aliases): <save>-<site>, or run-<id>-<site> for a marked copy."""
    save_dir, _, site = str(key).rpartition("#")
    if "@" in save_dir:
        _, _, run = save_dir.rpartition("@")
        run = re.sub(r"[^A-Za-z0-9_-]+", "_", run).strip("_")
        if run:
            return f"run-{run}-{site}"
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", save_dir or key).strip("_") or "fort"
    return f"{slug}-{site}" if site else slug


def run_start(run: str | None) -> float | None:
    try:
        return datetime.fromisoformat(run).timestamp() if run else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- one fort

class Fort:
    """A DF-AI folder: its preset, its season states and its journal (of the
    current run only: `refused` holds the older run's season states)."""

    def __init__(self, label: str, folder: Path):
        self.label, self.folder = label, Path(folder)
        kp = load_json(self.folder / "logs" / "keeper-preset.json") or {}
        self.keeper = {k: v for k, v in kp.items() if isinstance(v, dict)} if isinstance(kp, dict) else {}
        self.fort_dir = self._fort_dir()
        # one fort at a time in a DF-AI folder: its site's run, else the newest
        # run stamped (a folder moved aside under another name has no site)
        self.run = (self.run_of(self.fort_dir.name) or self.run_of(None)) if self.fort_dir else None
        self.states, self.refused = {}, []
        if self.fort_dir:
            since = run_start(self.run)
            found = [(season_key(p.stem), p, state_run(p)) for p in (self.fort_dir / "states").glob("*.json")]
            stamped = any(r for _, _, r in found)
            for k, p, r in found:
                if not k:
                    continue
                if self.run is None:
                    # the site's run cleared (a fresh start whose preset isn't applied
                    # yet): every state of a folder that had marked runs is older
                    ok = not stamped
                elif r is not None:
                    ok = r == self.run
                else:                       # kept before runs were marked: by when it was written
                    try:
                        ok = since is None or p.stat().st_mtime >= since
                    except OSError:
                        ok = False
                if ok:
                    self.states[k] = p
                else:
                    self.refused.append(k)
        self.refused.sort()
        self.preset = self._preset()
        self._journal = None

    def run_of(self, dir_name: str | None) -> str | None:
        """The newest run stamped for the site of logs/forts/<dir_name> (for
        any site with None)."""
        site = dir_site(dir_name) if dir_name is not None else None
        runs = [r["run"] for k, r in self.keeper.items()
                if (site is None or _site(k) == site) and isinstance(r.get("run"), str)]
        return max(runs) if runs else None

    def _fort_dir(self) -> Path | None:
        """The fort being run: one whose newest state is of its site's current
        run first, then a folder named as the overseer names its forts (a copy
        moved aside under another name inside logs/forts is passed over), then
        the newest season state (a folder can hold old forts)."""
        names = {canonical_dir(k) for k in self.keeper}
        forts = self.folder / "logs" / "forts"
        for idx in ("index.json", "session.json"):
            v = load_json(forts / idx) or {}
            if isinstance(v, dict):
                names |= {x for x in v.values() if isinstance(x, str)}
        best, rank = None, None
        for d in forts.glob("*"):
            st = list((d / "states").glob("*.json")) if d.is_dir() else []
            if not st:
                continue
            newest = max(st, key=lambda p: p.stat().st_mtime)
            run = self.run_of(d.name)
            r = (bool(run) and state_run(newest) == run, d.name in names, newest.stat().st_mtime)
            if rank is None or r > rank:
                best, rank = d, r
        return best

    def _preset(self) -> str:
        if self.states:
            s = load_json(self.states[max(self.states)]) or {}
            p = _d(s.get("settings")).get("preset")
            if p:
                return p
        names = [_d(v).get("name") for v in self.keeper.values() if _d(v).get("name")]
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
                            e = json.loads(line)
                        except ValueError:
                            continue
                        # (0.105.26) a line written before this run began is the old run's
                        if (self.run and isinstance(e, dict) and isinstance(e.get("time"), str)
                                and e["time"] < self.run):
                            continue
                        out.append(e)
            self._journal = out
        return self._journal

    def timeline(self) -> list[tuple[int, int]]:
        """(0.105.33) The fort's daily (game day, population) rows from
        timeline.csv; [] when there is none."""
        if getattr(self, "_timeline", None) is None:
            rows = []
            f = self.fort_dir / "timeline.csv" if self.fort_dir else None
            try:
                text = f.read_text(encoding="utf-8", errors="replace") if f else ""
            except OSError:
                text = ""
            lines = text.splitlines()
            head = lines[0].split(",") if lines else []
            if "day" in head and "pop" in head:
                di, pi = head.index("day"), head.index("pop")
                for line in lines[1:]:
                    c = line.split(",")
                    try:
                        rows.append((int(float(c[di])), int(float(c[pi]))))
                    except (ValueError, IndexError):
                        continue
            self._timeline = rows
        return self._timeline

    def state_at(self, key) -> dict | None:
        p = self.states.get(key)
        return load_json(p) if p else None


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

TICKS_PER_YEAR, TICKS_PER_DAY = 403200, 1200


def abs_ticks(d: dict) -> int:
    return (d.get("year") or 0) * TICKS_PER_YEAR + (d.get("tick") or 0)


def journal_counts(entries: list[dict], date: dict, timeline: list | None = None) -> dict:
    """What the fort did up to the date: actions that worked, by type, and a few sums.
    `timeline`: the fort's daily (day, population) rows, for welcome_pct."""
    ok, seen = Counter(), Counter()
    alarms_on = 0       # (0.105.33) civ_alert raises (a lowering is not an alarm)
    gems_set = gems_cut = treasures_kept = 0     # (0.105.33) Greed: encrust_goods, cut_gems amounts
    caps = []           # (0.105.33) (when, cap, held) from set_population_cap
    first = None        # the first dated decision of this run (older timeline rows are left out)
    trade_value, petitions_yes, petitions_no = 0, 0, 0
    levels = []
    reports, deaths = Counter(), Counter()
    access = []         # (when, visitors allowed, location ids) from location_access
    soil_floored = 0    # (0.105.30) tiles floor_rooms placed
    landmarks = []      # (D0) build_blueprint decisions (not dry runs)
    for e in entries:
        if e.get("kind") == "event" and before(e, date):
            ev = _d(e.get("event"))
            if ev.get("kind") == "report":
                topic = ev.get("topic")
                # (0.105.33) a soldier naming a weapon (NAMED_ARTIFACT) is not a mood's artifact
                if topic == "artifact_made" and (ev.get("type") == "NAMED_ARTIFACT"
                                                 or "bestowed the name" in str(ev.get("text") or "")):
                    topic = "artifact_named"
                reports[topic] += 1
            elif (ev.get("kind") == "death" and ev.get("own_civ") and not ev.get("animal")
                  and not ev.get("again")):
                deaths[str(ev.get("cause") or "unknown")] += 1
            continue
        if e.get("kind") != "decision" or not before(e, date):
            continue
        a, r = _d(e.get("action")), _d(e.get("result"))
        t = a.get("type")
        if not t:
            continue
        if first is None and isinstance(e.get("date"), dict):
            first = abs_ticks(e["date"])
        seen[t] += 1
        if t == "build_blueprint" and not r.get("dry_run") and not a.get("dry_run"):
            landmarks.append(landmark_entry(a, r))
        if not r.get("ok"):
            continue
        ok[t] += 1
        if t == "bring_goods":
            trade_value += r.get("value") or 0
            treasures_kept += bool(a.get("keep_treasures"))
        elif t == "civ_alert":
            alarms_on += bool(r.get("on") if isinstance(r.get("on"), bool) else a.get("on"))
        elif t == "work_order" and a.get("recipe") in ("encrust_goods", "cut_gems") and not r.get("dry_run"):
            n = r.get("amount") if isinstance(r.get("amount"), int) else a.get("amount")
            n = n if isinstance(n, int) and not isinstance(n, bool) else 0
            if a.get("recipe") == "encrust_goods":
                gems_set += n
            else:
                gems_cut += n
        elif t == "set_population_cap" and isinstance(e.get("date"), dict) and not r.get("dry_run"):
            cap = r.get("cap") if isinstance(r.get("cap"), int) else a.get("cap")
            if isinstance(cap, int):
                caps.append((abs_ticks(e["date"]), cap, "no newcomers for now" in str(e.get("reason") or "")))
        elif t == "answer_petition":
            if r.get("accepted") or a.get("accept"):
                petitions_yes += 1
            else:
                petitions_no += 1
        elif t == "start_project":
            # (0.105.33) Spacing: the new corridor dug for the level (the bridge's
            # `new_corridor`; `corridor`, which also counts walked fort tiles, before it)
            cor = r.get("new_corridor") if _num_or_none(r.get("new_corridor")) is not None else r.get("corridor")
            rooms = _d(r.get("summary")).get("rooms")
            rooms = rooms if _num_or_none(rooms) is not None else a.get("rooms")
            levels.append({"kind": r.get("kind") or a.get("kind"), "z": r.get("z"),
                           "tiles": r.get("tiles") or r.get("designated"),
                           "corridor": _num_or_none(cor), "rooms": _num_or_none(rooms),
                           "customs": [c for c in _l(a.get("customs")) if isinstance(c, str)],
                           # (D0) the level's style (its design signature) and when it began
                           "style": _d(a.get("style")),
                           "when": abs_ticks(e["date"]) if isinstance(e.get("date"), dict) else None,
                           # (group 6) where it lies and the open ground over it (the bridge's ground_z)
                           "x": _d(r.get("anchor")).get("x"), "y": _d(r.get("anchor")).get("y"),
                           "ground": r.get("ground_z") if _whole(r.get("ground_z")) else None})
        elif t == "floor_rooms" and not r.get("dry_run"):
            # (0.105.30) soil floors the keeper finished: tiles placed (any count field the bridge gives)
            n = next((r[k] for k in ("placed", "tiles", "floored", "n") if isinstance(r.get(k), int)
                      and not isinstance(r.get(k), bool)), None)
            soil_floored += n if n is not None else len(_l(r.get("cells")))
        elif t == "location_access" and not r.get("dry_run") and isinstance(e.get("date"), dict):
            ids = r.get("changed") if isinstance(r.get("changed"), list) else _l(a.get("ids"))
            vis = r.get("visitors") if isinstance(r.get("visitors"), bool) else a.get("visitors")
            if isinstance(vis, bool):
                access.append((abs_ticks(e["date"]), vis, ids))
    until = abs_ticks(date)
    return {"ok": ok, "seen": seen, "trade_value": trade_value, "petitions_yes": petitions_yes,
            "petitions_no": petitions_no, "levels": levels, "reports": reports, "deaths": deaths,
            "shut_days": shut_days(access, until), "soil_floored": soil_floored,
            "alarms_on": alarms_on, "gems_set": gems_set, "gems_cut": gems_cut, "treasures_kept": treasures_kept,
            "caps": caps, "welcome": welcome_rows(caps, timeline or [], until, first),
            "landmarks": landmarks, "until": until}


DAYS_PER_YEAR = 336


def welcome_rows(caps: list, timeline: list, until: int, since: int | None = None) -> tuple[int, int] | None:
    """(0.105.33, Growth) Of the last game year's days up to `until` (the
    timeline's daily rows), how many had a population cap above the
    population (newcomers welcome), and how many days had a cap known:
    (welcome, known), or None without a cap change or a timeline. Rows before
    this run's first decision (`since`) are another run's and left out."""
    if not caps or not timeline:
        return None
    caps = sorted(caps, key=lambda c: c[0])
    end = until // TICKS_PER_DAY
    lo = max(end - DAYS_PER_YEAR, (since // TICKS_PER_DAY) if since is not None else end - DAYS_PER_YEAR)
    welcome = known = 0
    i, cap = 0, None
    for day, pop in sorted(timeline):
        if day < lo or day > end:
            continue
        while i < len(caps) and caps[i][0] <= day * TICKS_PER_DAY:
            cap = caps[i][1]
            i += 1
        if cap is None:
            continue
        known += 1
        welcome += cap > pop
    return (welcome, known) if known else None


def shut_days(access: list, until: int) -> float:
    """Days up to `until` with at least one location shut to visitors (the
    planner's location_access: shut, then opened again after a while)."""
    shut, since, total = set(), None, 0
    for when, vis, ids in sorted(access, key=lambda x: x[0]):
        if when > until:
            break
        was = bool(shut)
        if vis:
            shut -= set(ids)
        else:
            shut |= set(ids)
        if shut and not was:
            since = when
        elif was and not shut and since is not None:
            total += when - since
            since = None
    if shut and since is not None:
        total += max(0, until - since)
    return round(total / TICKS_PER_DAY, 1)


def pct(a, b):
    return round(100.0 * a / b, 1) if a is not None and b else None


def per(a, b):
    return round(a / b, 1) if a is not None and b else None


def _whole(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def level_surface(lv: dict, s: dict) -> int | None:
    """(group 6) The surface z over one level, for the Verticality and Surface
    lines: the bridge's own reading (`ground`: the first tile under the sky
    above the level's middle) when the level has it; else the surface way in
    nearest the level (its z; the open ground beside the main way in, the
    crossings' z, for that one); else the main way in's ground, as before.
    Fort E (Deep mine, a mountain site): its main way in lay on a plateau at
    z161, its stair came down from the hilltop at z170, and every level
    between (under the mountain) was counted "at or above the surface"."""
    if _whole(lv.get("ground")):
        return lv["ground"]
    cr = _d(s.get("crossings"))
    main = cr.get("z") if _whole(cr.get("z")) else None
    x, y = lv.get("x"), lv.get("y")
    if _whole(x) and _whole(y):
        ce = _d(cr.get("entrance"))
        best, best_d = None, None
        for e in _l(_d(s.get("entrances")).get("entrances")):
            e = _d(e)
            if e.get("kind") != "surface" or not all(_whole(e.get(k)) for k in ("x", "y", "z")):
                continue
            d = abs(e["x"] - x) + abs(e["y"] - y)
            if best_d is None or d < best_d:
                z = main if main is not None and (e["x"], e["y"]) == (ce.get("x"), ce.get("y")) else e["z"]
                best, best_d = z, d
        if best is not None:
            return best
    return main


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
    levels = j["levels"]
    lz = [lv["z"] for lv in levels if isinstance(lv.get("z"), int)]
    # (group 6) each level's own surface (the ground over it), not the way in's
    grounds = [(lv["z"], level_surface(lv, s)) for lv in levels if isinstance(lv.get("z"), int)]
    grounds = [(z, g) for z, g in grounds if g is not None]
    tiles = [lv["tiles"] for lv in levels if isinstance(lv.get("tiles"), (int, float)) and lv["tiles"] > 0]
    kinds = Counter(lv.get("kind") for lv in levels)
    ok = j["ok"]
    traps = sum(v for k, v in other.items() if "Trap" in k and k != "TractionBench")
    meals = _d(s.get("supplies")).get("meal_servings")
    good_meals = _d(s.get("supplies")).get("good_meals")
    loc_list = [_d(x) for x in _l(_d(s.get("locations")).get("list"))]
    needs = _d(s.get("needs"))
    ents = [_d(e) for e in _l(_d(s.get("entrances")).get("entrances"))]
    # (0.105.26) today's signatures, 14.1 step 4
    gatehouses = max(ok.get("build_gatehouse", 0), sum(1 for e in ents if e.get("gatehouse") == "standing"))
    lever_gates = sum(1 for e in ents for q in _l(e.get("equipment")) if _d(q).get("lever_driven")) \
        if s.get("entrances") is not None else None
    deep = _d(b.get("deep_depot")) if b else None
    worship = needs.get("worship")
    if isinstance(worship, dict):
        ids = _d(needs.get("deity_ids"))
        housed = set()
        for t in temples:
            t = _d(t)
            if t.get("deity_hf") is not None:
                housed.add(t["deity_hf"])
            housed |= set(_l(t.get("religion_deities")))
        gods = [g for g, n in worship.items() if (n or 0) > 0]
        gods_housed = pct(sum(1 for g in gods if ids.get(g) in housed), len(gods)) if gods else None
    else:
        gods_housed = None
    open_locs = [x for x in loc_list if x.get("type") != "HOSPITAL"]
    have_flags = [x for x in open_locs if isinstance(x.get("flags"), list)]
    sc = needs.get("stress_causes")
    if isinstance(sc, dict) and sc.get("citizens"):
        same = next((_d(c) for c in _l(sc.get("causes")) if _d(c).get("thought") == "SameBooze"), {})
        same_booze = pct(same.get("citizens") or 0, sc.get("citizens"))
    else:
        same_booze = None
    # (0.105.33, Industry) idle: adults with no job, no social activity (prayer,
    # the tavern, reading) and not in a squad, of the adults not in squads.
    # The bridge's `idle_free` first; then the needs report's stricter count
    # (needs.social.idle); then the old idle_adults (activity counted as idle)
    in_squads = dw.get("in_squads") if isinstance(dw.get("in_squads"), int) else 0
    civilians = max(0, adults - in_squads)
    social = _d(needs.get("social"))
    if _num_or_none(dw.get("idle_free")) is not None:
        idle_n = dw["idle_free"]
    elif _num_or_none(social.get("idle")) is not None:
        idle_n = social["idle"]
    else:
        idle_n = dw.get("idle_adults")
    cor = [lv["corridor"] for lv in levels if _num_or_none(lv.get("corridor")) is not None]
    beds = [lv for lv in levels if lv.get("kind") == "bedrooms" and (lv.get("rooms") or 0) > 0
            and isinstance(lv.get("tiles"), (int, float)) and lv["tiles"] > 0]
    cut_stock = (stocks.get("cut_gems") or 0) + (stocks.get("rough_gems") or 0)
    wl = j.get("welcome")
    out = {
        "pop": total,
        "soldier_pct": pct(dw.get("in_squads"), adults),
        "barracks": zones.get("Barracks", 0) + zones.get("ArcheryRange", 0) + kinds.get("barracks", 0),
        "traps": traps,
        "bridges": other.get("Bridge", 0) + other.get("Floodgate", 0) + other.get("Hatch", 0),
        "gate_works": sum(ok.get(t, 0) for t in GATE_WORKS),
        "levers": other.get("Lever", 0),
        "mechanisms": stocks.get("mechanisms"),
        "alerts": j.get("alarms_on", 0),                  # (0.105.33) raises only
        "stairwells_dug": ok.get("dig_stairwell", 0),     # (0.105.33) Caution's escape route
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
        "gems": cut_stock,
        # (0.105.33) Greed: gems spent on goods, gems kept of those cut, treasures held from the caravans
        "gems_set": j.get("gems_set", 0),
        "gems_kept_pct": pct(cut_stock, (j.get("gems_cut") or 0) + (stocks.get("rough_gems") or 0)),
        "treasures_kept": j.get("treasures_kept", 0),
        "welcome_pct": pct(wl[0], wl[1]) if wl else None,      # (0.105.33) Growth
        "statues": other.get("Statue", 0),
        "halls": zones.get("MeetingHall", 0),
        "gardens": kinds.get("garden", 0),
        "legendary_pct": pct(dw.get("legendary"), adults),
        "craft_shops": _d(b.get("workshops")).get("Craftsdwarfs", 0),
        "ore": _d(s.get("industry")).get("ore_stock"),
        "ore_runs": ok.get("mine_ore", 0),
        "z_span": (max(lz) - min(lz) + 1) if lz else None,
        "depth": max(g - z for z, g in grounds) if grounds else None,
        "levels_up": sum(1 for z, g in grounds if z >= g) if grounds else None,
        "surface_plots": farms.get("plots_surface"),
        "farm_tiles": farms.get("tiles"),
        "plots": farms.get("plots"),
        "animals": others.get("tame_animals"),
        "pastures": _d(s.get("society")).get("pastures"),
        "idle_pct": pct(idle_n, civilians),
        "polish_runs": ok.get("polish", 0),               # (0.105.33) Industry: levels smoothed or engraved
        "suites": kinds.get("suites", 0),
        "offices": zones.get("Office", 0),
        "level_tiles": round(sum(tiles) / len(tiles)) if tiles else None,
        # (0.105.33) Spacing: the new corridor a level, and tiles a bedroom (room count taken out)
        "corridor_mean": round(sum(cor) / len(cor), 1) if cor else None,
        "bedroom_tiles": round(sum(lv["tiles"] for lv in beds) / sum(lv["rooms"] for lv in beds), 1)
        if beds else None,
        "stockpiles": b.get("stockpiles"),
        "stores_pd": per((stocks.get("drink") or 0) + (meals or 0), total),
        "levels": len(levels),
        "kinds": dict(kinds),
        "gatehouses": gatehouses,
        "lever_gates": lever_gates,
        "deep_depot": (1 if deep.get("depot") == "built" else 0) if deep is not None else None,
        "gods_housed_pct": gods_housed,
        "grand_temples": sum(1 for t in temples if (_d(t).get("tier") or 0) >= 2) if s.get("locations") else None,
        "visitors_open_pct": pct(sum(1 for x in have_flags if "VISITORS_ALLOWED" in x["flags"]), len(have_flags))
        if have_flags else None,
        "shut_days": j.get("shut_days"),
        "drink_kinds": _d(s.get("supplies")).get("drink_kinds"),
        "same_booze_pct": same_booze,
    }
    # (0.105.29) levels that a preset's customs placed or shaped (journal action "customs")
    for owner, k in CUSTOM_KEYS.items():
        out["custom_" + k] = sum(1 for lv in levels if CUSTOM_IDS[owner] & set(lv.get("customs") or []))
    out.update(construction_measures(s, j))
    return out


# ---------------------------------------------------------------- (0.105.30) constructions

def constructions_section(s: dict) -> dict | None:
    """The report's `constructions` section (lua/ai-constructions.lua survey),
    or the census's copy; None when neither is there or the survey failed
    ((0.105.30 fixes) or found no construction list: `missing`, its zeros
    are no data)."""
    for c in (s.get("constructions"), _d(s.get("census")).get("constructions")):
        if isinstance(c, dict) and c and "error" not in c and not c.get("missing"):
            return c
    return None


def _count(v) -> int | None:
    """One of the survey's `ai` registry entries: a number, a list of tiles or
    pieces, or a dict carrying a count (built, walls, tiles, total or n)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, list):
        return len(v)
    if isinstance(v, dict):
        for k in ("built", "walls", "tiles", "total", "n"):
            x = v.get(k)
            if isinstance(x, (int, float)) and not isinstance(x, bool):
                return int(x)
            if isinstance(x, list):
                return len(x)
    return None


def _num_or_none(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def construction_measures(s: dict, j: dict) -> dict:
    """built_up, roofed_up, gate_walls, cavern_walls, block_pct and soil_floors.
    All None when the report has no constructions section (an older bridge),
    so those lines read "no data", never a false 0."""
    c = constructions_section(s)
    out = dict.fromkeys(("built_up", "roofed_up", "gate_walls", "cavern_walls", "block_pct", "soil_floors"))
    floored = j.get("soil_floored") if isinstance(j, dict) else None
    if c is None:
        return out
    total = _num_or_none(c.get("total"))
    surface = c.get("surface")
    out["built_up"] = _num_or_none(_d(surface).get("total")) if isinstance(surface, dict) else _num_or_none(surface)
    out["roofed_up"] = _num_or_none(c.get("roofed_surface_tiles"))
    ai = c.get("ai")
    if isinstance(ai, dict):
        parts = [_count(ai.get(k)) for k in ("gate_pieces", "wings")]
        out["gate_walls"] = sum(x for x in parts if x is not None) if any(x is not None for x in parts) else None
        out["cavern_walls"] = _count(ai.get("cavern_walls"))
        out["soil_floors"] = _count(ai.get("soil_floors"))
    blocks = _num_or_none(_d(c.get("by_item")).get("blocks"))
    out["block_pct"] = (pct(blocks, total) if total else 0.0) if blocks is not None and total is not None else None
    if out["soil_floors"] is None:
        # the survey keeps no soil-floor registry: the tiles floor_rooms placed (journal)
        out["soil_floors"] = floored if isinstance(floored, int) else None
    return out


# ---------------------------------------------------------------- (D0) the Design block

# the style keys the Design track adds (lua/ai-layouts.lua style_of; each is sent
# only when it isn't its default) and its four new halls
DESIGN_STYLE_KEYS = ("scale", "aspect", "arms", "motif", "grand")
DESIGN_HALLS = ("octagonal", "round", "cruciform", "nave")
DISTINCT_PASS = 0.5       # judge_distinct: every pair of forts at least this far apart


def level_signature(kind, style) -> str:
    """A level's design signature: design.signature when brain/design.py is
    there, else the same "<kind>:<hall>:<arms>:<scale//10>:<motif>:<orient>"
    with each key's default."""
    st = _d(style)
    if _design is not None and hasattr(_design, "signature"):
        try:
            return str(_design.signature(kind, st))
        except Exception:       # noqa: BLE001 - a bad style is scored, not fatal
            pass
    scale = st.get("scale") if isinstance(st.get("scale"), int) and not isinstance(st.get("scale"), bool) else 100
    return (f"{kind}:{st.get('hall') or 'plain'}:{st.get('arms') or 'corridor'}:{scale // 10}:"
            f"{st.get('motif') or 'rows'}:{st.get('orient') or 0}")


def in_language(style) -> bool:
    """A level built in a design language: its style carries a Design key."""
    st = _d(style)
    return any(st.get(k) not in (None, False) for k in DESIGN_STYLE_KEYS) or st.get("hall") in DESIGN_HALLS


def grid_key(bp) -> str | None:
    """A short fingerprint of a blueprint's grids (its levels' rows), so two
    landmarks with the same drawing are seen; None without levels."""
    levels = _l(_d(bp).get("levels"))
    if not levels:
        return None
    rows = [_l(_d(lv).get("grid")) or _l(_d(lv).get("rows")) for lv in levels]
    return hashlib.sha1(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def landmark_entry(a: dict, r: dict) -> dict:
    """One build_blueprint decision: what was asked, by whom, and how it went."""
    return {"name": a.get("name"), "purpose": a.get("purpose"),
            "by": a.get("by") if a.get("by") in ("ai", "library") else "library",
            "ok": bool(r.get("ok")), "rejected": not r.get("ok"),
            "landmark_id": r.get("landmark_id"), "grid": grid_key(a.get("bp")) if r.get("ok") else None,
            "codes": [_d(x).get("code") for x in _l(r.get("reasons")) if _d(x).get("code")]}


def design_measures(s: dict, j: dict) -> dict:
    """(D0) The Design block's numbers for one fort (design-track 9): the
    setting, the share of the last year's levels in the language, the hall
    shapes and arm patterns used, landmarks started (library, AI) and built,
    refusals a landmark, and the level signatures."""
    levels = j.get("levels") or []
    until = j.get("until")
    year = [lv for lv in levels if until is None or lv.get("when") is None
            or lv["when"] >= until - TICKS_PER_YEAR]
    styled = [lv for lv in levels if lv.get("style")]
    marks = j.get("landmarks") or []
    started = [m for m in marks if m["ok"]]
    tried = {str(m.get("name") or m.get("purpose") or "?") for m in marks}
    refused = sum(1 for m in marks if m["rejected"])
    lm = s.get("landmarks")
    built = sum(1 for x in _l(_d(lm).get("list")) if _d(x).get("status") == "built") \
        if isinstance(lm, dict) else None
    grids = [m["grid"] for m in started if m.get("grid")]
    return {
        "setting": _d(s.get("settings")).get("design"),
        "language_pct": pct(sum(1 for lv in year if in_language(lv.get("style"))), len(year)),
        "hall_shapes": len({lv["style"].get("hall") or "plain" for lv in styled}) if styled else 0,
        "arm_patterns": len({lv["style"].get("arms") or "corridor" for lv in styled}) if styled else 0,
        "landmarks_library": sum(1 for m in started if m["by"] == "library"),
        "landmarks_ai": sum(1 for m in started if m["by"] == "ai"),
        "landmarks_built": built,
        "refusals_per_landmark": per(refused, len(tried)) if marks else None,
        "signatures": sorted({level_signature(lv.get("kind"), lv.get("style")) for lv in levels if lv.get("kind")}),
        "grids": grids,
        "styled": any(in_language(lv.get("style")) for lv in levels) or bool(marks),
    }


def _sig_sets(forts) -> list[tuple[str, set]]:
    items = forts.items() if isinstance(forts, dict) else enumerate(forts)
    return [(str(k), set(v)) for k, v in items if v]


def jaccard_distance(a: set, b: set) -> float:
    union = a | b
    return 1.0 - len(a & b) / len(union) if union else 0.0


def pair_distances(forts) -> list[tuple[str, str, float]]:
    """Every pair of forts' signature sets (label -> signatures, or a list of
    them) and their Jaccard distance; forts without a level are left out."""
    sets = _sig_sets(forts)
    return [(a, b, round(jaccard_distance(sa, sb), 3))
            for i, (a, sa) in enumerate(sets) for b, sb in sets[i + 1:]]


def distinct(forts) -> float | None:
    """Layout distinctness: the mean pairwise Jaccard distance between the
    forts' level-signature sets (0: the same set; 1: nothing shared). None
    with fewer than two forts that have levels."""
    pairs = pair_distances(forts)
    return round(sum(d for _, _, d in pairs) / len(pairs), 3) if pairs else None


def judge_distinct(forts, bar: float = DISTINCT_PASS) -> str:
    """'pass' when every pair of forts is at least `bar` apart, 'fail' when
    one isn't, 'no data' with fewer than two forts that have levels."""
    pairs = pair_distances(forts)
    if not pairs:
        return "no data"
    return "pass" if all(d >= bar for _, _, d in pairs) else "fail"


def design_section(labels: list, dm: dict) -> tuple[list[str], dict]:
    """The Design block's markdown and its summary (for summary.json)."""
    sigs = {lb: dm[lb]["signatures"] for lb in labels}
    dist, verdict = distinct(sigs), judge_distinct(sigs)
    pairs = pair_distances(sigs)
    md = ["", "## Design", "", "| Measure | " + " | ".join(labels) + " |", "|" + " --- |" * (len(labels) + 1)]
    for what, k in (("Design setting", "setting"), ("levels in the language, % of the last year's", "language_pct"),
                    ("hall shapes used", "hall_shapes"), ("arm patterns used", "arm_patterns"),
                    ("landmarks started from the library", "landmarks_library"),
                    ("landmarks started from the AI's drawings", "landmarks_ai"),
                    ("landmarks built", "landmarks_built"), ("refusals a landmark", "refusals_per_landmark")):
        md.append(f"| {what} | " + " | ".join(fmt(dm[lb].get(k)) for lb in labels) + " |")
    md.append("| level signatures | " + " | ".join(str(len(dm[lb]["signatures"])) for lb in labels) + " |")
    md.append("")
    if dist is None:
        md.append("Layout distinctness: no data (fewer than two forts with levels).")
    else:
        close = min(pairs, key=lambda x: x[2])
        md.append(f"Layout distinctness: {dist:g} (mean pairwise distance; closest pair {close[0]}-{close[1]} "
                  f"at {close[2]:g}): **{verdict}** (every pair {DISTINCT_PASS:g} or more apart).")
    grids = [(lb, g) for lb in labels for g in dm[lb]["grids"]]
    seen = Counter(g for _, g in grids)
    dup = sorted({lb for lb, g in grids if seen[g] > 1})
    md.append(("Landmark grids: every one unique." if not dup else
               f"Landmark grids: {sum(n for n in seen.values() if n > 1)} share a drawing ({', '.join(dup)}).")
              if grids else "Landmark grids: none built yet.")
    return md, {"distinct": dist, "verdict": verdict, "grids_unique": not dup}


# ---------------------------------------------------------------- the lines

# (slider, what, measure, high presets, low presets)
W, M, ME, H, D, G = "War-hold", "Monastery", "Merchant city", "Hermit hold", "Deep mine", "Garden fort"
LINES = [
    ("Militarism", "soldiers, % of adults", "soldier_pct", {W}, {M}),
    ("Militarism", "barracks and ranges", "barracks", {W}, {M}),
    ("Fortification", "traps", "traps", {W}, set()),
    ("Fortification", "bridges, floodgates, hatches", "bridges", {W}, set()),
    ("Fortification", "gate works done", "gate_works", {W, H}, set()),
    ("Fortification", "gatehouses built", "gatehouses", {W, H}, set()),
    ("Engineering", "levers", "levers", {W, D}, set()),
    ("Engineering", "lever-driven gates", "lever_gates", {W, D}, set()),
    ("Engineering", "mechanisms in store", "mechanisms", {W, D}, set()),
    ("Caution", "alarms raised", "alerts", {W, H}, {D}),
    ("Caution", "second stairwells dug", "stairwells_dug", {W, H}, {D}),      # (0.105.33)
    ("Justice", "jail cells", "jails", {W}, {M}),
    ("Justice", "restraints", "restraints", {W}, {M}),
    ("Piety", "temples", "temples", {M}, set()),
    ("Piety", "best temple's value", "temple_value", {M}, set()),
    ("Piety", "worshipped gods with a temple, %", "gods_housed_pct", {M}, set()),
    ("Piety", "grand temples (tier 2+)", "grand_temples", {M}, set()),
    ("Welfare", "unhappy, % (lowest wins)", "-unhappy_pct", {M, G}, {W}),
    ("Welfare", "good meals a dwarf", "good_meals_pd", {M, G}, {W}),
    ("Welfare", "drink kinds", "drink_kinds", {M, G}, set()),
    ("Welfare", "upset by the same booze, % (lowest wins)", "-same_booze_pct", {M, G}, set()),
    # (0.105.26) "visitors on the map" gave way: D at Outsiders -150 had the most
    ("Outsiders", "locations open to visitors, %", "visitors_open_pct", {ME}, {H, W}),
    ("Outsiders", "days shut to visitors", "shut_days", {H, W}, {ME}),
    ("Outsiders", "guildhalls", "guildhalls", {ME, M}, {H, W}),
    ("Outsiders", "petitions agreed", "petitions_yes", {ME, M}, {H, W}),
    ("Outsiders", "petitions declined", "petitions_no", {H, W}, {ME, M}),
    ("Trade", "goods taken to caravans", "trade_runs", {ME}, {H}),
    ("Trade", "value taken to caravans", "trade_value", {ME}, {H}),
    # (0.105.33) "wealth a dwarf" and "gems kept" measured building and mining luck
    ("Greed", "gems set into goods (fewest wins)", "-gems_set", {ME, H}, {M}),
    ("Greed", "gems kept, % of gems cut", "gems_kept_pct", {ME, H}, {M}),
    ("Greed", "treasures kept from the caravans", "treasures_kept", {ME, H}, set()),
    ("Grandeur", "statues", "statues", {M, G}, {W}),
    ("Grandeur", "meeting halls", "halls", {M, G}, {W}),
    ("Grandeur", "garden levels", "gardens", {M, G}, {W}),
    ("Craftsmanship", "legendary, % of adults", "legendary_pct", {ME, M}, set()),
    ("Craftsmanship", "craftsdwarf's shops", "craft_shops", {ME, M}, set()),
    ("Growth", "population", "pop", {ME}, {H}),
    ("Growth", "newcomers welcome, % of the last year's days", "welcome_pct", {ME}, {H}),    # (0.105.33)
    ("Mining", "ore in store", "ore", {D}, {G}),
    ("Mining", "veins mined", "ore_runs", {D}, {G}),
    ("Mining", "underground depot built", "deep_depot", {D}, set()),
    ("Verticality", "levels' height span", "z_span", {D}, set()),
    ("Verticality", "deepest level below the surface", "depth", {D}, set()),
    ("Surface", "levels at or above the surface", "levels_up", {G, ME}, {D, H}),
    ("Surface", "surface farm plots", "surface_plots", {G, ME}, {D, H}),
    ("Agriculture", "farm tiles", "farm_tiles", {G}, {D}),
    ("Agriculture", "farm plots", "plots", {G}, {D}),
    ("Husbandry", "tame animals", "animals", {G}, set()),
    ("Husbandry", "pastures", "pastures", {G}, set()),
    ("Industriousness", "idle, % of adults not in squads (lowest wins)", "-idle_pct", {D}, {M}),
    ("Industriousness", "levels smoothed or engraved", "polish_runs", {D}, {M}),     # (0.105.33)
    ("Deference", "suite levels", "suites", {W, ME}, {H}),
    ("Deference", "offices", "offices", {W, ME}, {H}),
    # (0.105.33) "tiles a level" measured the mix of level kinds
    ("Spacing", "new corridor tiles a level (fewest wins)", "-corridor_mean", {W, D}, set()),
    ("Spacing", "tiles a bedroom (smallest wins)", "-bedroom_tiles", {W, D}, set()),
    ("Stockpile", "stockpiles", "stockpiles", {H, ME}, set()),
    ("Stockpile", "drink and meals a dwarf", "stores_pd", {H, ME}, set()),
    # (0.105.29) the customs: levels each preset's two customs placed or shaped (Hermit also on levels_up)
    ("Piety", "cloister temples and cells", "custom_M", {M}, set()),
    ("Trade", "wide ways, tavern by the gate", "custom_ME", {ME}, set()),
    ("Outsiders", "winding ways, hidden levels", "custom_H", {H}, set()),
    ("Militarism", "barracks by the gate, armouries", "custom_W", {W}, set()),
    ("Mining", "deep halls, ore piles", "custom_D", {D}, set()),
    ("Agriculture", "halls and kitchens by the fields", "custom_G", {G}, set()),
    # (0.105.30) construction: the keeper builds, not only digs (lua/ai-constructions.lua survey)
    ("Surface", "constructed tiles above ground", "built_up", {G, ME}, {D, H}),
    ("Surface", "roofed surface tiles", "roofed_up", {G, ME}, {D, H}),
    ("Fortification", "gate walls and wings", "gate_walls", {W}, set()),
    ("Fortification", "cavern openings walled", "cavern_walls", {H}, set()),
    ("Craftsmanship", "constructions of blocks, %", "block_pct", {ME, M}, set()),
    ("Grandeur", "soil floors finished", "soil_floors", {G, M}, {W}),
]


def judge(values: dict[str, float | None], high: set, low: set) -> str:
    """values: preset -> number (bigger is 'more of the slider'). 'pass', 'fail',
    'flat' or 'no data'; a line with both sides passes when both do, and is
    'half' when only one does. (0.105.26) A side whose best (or worst) is
    shared with a preset outside its group counts half."""
    have = {p: v for p, v in values.items() if v is not None}
    want = (high | low) & set(values)
    if len(have) < 2 or not (want & set(have)):
        return "no data"
    vals = list(have.values())
    if max(vals) == min(vals):
        return "flat"

    def side(group, end):
        at = {p for p, v in have.items() if v == end}
        if not at & group:
            return 0.0
        return 1.0 if at <= group else 0.5

    parts = []
    if high & set(values):
        parts.append(side(high, max(vals)))
    if low & set(values):
        parts.append(side(low, min(vals)))
    if all(x == 1.0 for x in parts):
        return "pass"
    return "half" if any(parts) else "fail"


def fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def health(s: dict, j: dict) -> dict:
    """(0.105.26) The fort's health against fixed bars, not a ranking."""
    dw = _d(s.get("dwarves"))
    adults, total = dw.get("adults") or 0, dw.get("total") or 0
    stress = _d(dw.get("stress"))
    unhappy = sum(stress.get(k, 0) for k in ("unhappy", "very_unhappy", "miserable"))
    rep = j.get("reports") or Counter()
    in_squads = dw.get("in_squads") if isinstance(dw.get("in_squads"), int) else 0
    social = _d(_d(s.get("needs")).get("social"))
    idle_n = next((x for x in (dw.get("idle_free"), social.get("idle")) if _num_or_none(x) is not None),
                  dw.get("idle_adults"))
    working = sum(1 for m in _l(_d(s.get("moods")).get("list")) if _d(m).get("craft"))
    # the journal's deaths (this run), or the game's own count from last year
    # on when that is more (a journal rotated, or deaths before it was kept)
    deaths = Counter(j.get("deaths") or {})
    game = _d(_d(s.get("dead")).get("deaths")).get("by_cause")
    for c, n in _d(game).items():
        if isinstance(n, int) and n > deaths.get(c, 0):
            deaths[c] = n
    return {"failed_moods": max(0, rep.get("mood", 0) - rep.get("artifact_made", 0) - working),
            "moods": rep.get("mood", 0), "artifacts": rep.get("artifact_made", 0),
            "thirst_deaths": deaths.get("THIRST", 0),
            "unhappy_pct": pct(unhappy, total), "idle_pct": pct(idle_n, max(0, adults - in_squads)),
            "deaths": dict(deaths)}


# (what, measure, bar: the value must stay at or under it (or under it, with <))
HEALTH_BARS = [
    ("failed moods", "failed_moods", 0, "<="),
    ("deaths by thirst", "thirst_deaths", 0, "<="),
    ("unhappy, %", "unhappy_pct", 10, "<"),
    ("truly idle adults not in squads, % (no job, no leisure)", "idle_pct", 25, "<"),   # (0.105.34) 25: idle_free counts only the truly idle
]


def ai_ms_day(f) -> float | None:
    """(0.105.40) The median of a fort's AI ms per game day (brain/perf.py's
    perf.jsonl rows, this run's: written since the run began); None without."""
    import perf
    d = getattr(f, "fort_dir", None)
    if not d:
        return None
    rows = perf.read_rows(Path(d) / perf.PERF_FILE)
    run = getattr(f, "run", None)
    if run:
        rows = [r for r in rows if not isinstance(r.get("time"), str) or r["time"] >= run]
    m = perf.median(r.get("ms_per_day") for r in rows)
    return round(m) if m is not None else None


def health_ok(v, bar, how) -> bool | None:
    if v is None:
        return None
    return v <= bar if how == "<=" else v < bar


def pick_keys(forts: list[Fort], at: str | None, now: bool) -> tuple[dict, str]:
    if now:
        return {f.label: max(f.states) for f in forts}, "each fort's newest season"
    if at:
        k = season_key(at)
        if not k:
            raise SystemExit(f"--at wants YEAR-SEASON, like 252-spring (got {at!r})")
    else:
        common = set.intersection(*(set(f.states) for f in forts))
        if not common:
            raise SystemExit("The forts have no season in common: use --now")
        k = max(common)
    return {f.label: k for f in forts}, f"all at {k[0]}-{SEASONS[k[1]]}"


def run_notes(forts: list[Fort]) -> list[str]:
    """(0.105.26) What was left out as another run's."""
    out = []
    for f in forts:
        if f.refused:
            a, b = f.refused[0], f.refused[-1]
            out.append(f"- Fort {f.label}: {len(f.refused)} season state(s) of an older run left out "
                       f"({a[0]}-{SEASONS[a[1]]} .. {b[0]}-{SEASONS[b[1]]})"
                       + (f"; this run began {f.run}" if f.run else
                          "; this site has no run in keeper-preset.json yet (cleared for a fresh start?)") + ".")
        if not f.states:
            out.append(f"- Fort {f.label}: no season state of its current run yet"
                       + (f" in {f.fort_dir}" if f.fort_dir else " (no logs/forts folder with states)") + ".")
    return out


def score(forts: list[Fort], at: str | None, now: bool) -> tuple[str, list[dict]]:
    """The markdown report and the rows."""
    md, rows, _ = score_full(forts, at, now)
    return md, rows


def score_full(forts: list[Fort], at: str | None, now: bool) -> tuple[str, list[dict], dict]:
    """The markdown report, the rows, and a summary for the series."""
    notes = run_notes(forts)
    forts = [f for f in forts if f.states]
    if not forts:
        return "No fort with season states found.\n" + ("\n" + "\n".join(notes) + "\n" if notes else ""), [], {}
    keys, title = pick_keys(forts, at, now)
    data, dm = {}, {}
    for f in forts:
        s = f.state_at(keys[f.label])
        if s is None:
            continue
        j = journal_counts(f.journal(), _d(s.get("date")), f.timeline())
        data[f.label] = (f, s, measures(s, j), health(s, j))
        dm[f.label] = design_measures(s, j)      # (D0)
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
            f, _, m, _ = data[lb]
            v = m.get(k)
            raw[lb] = v
            by_preset[f.preset] = (-v if neg and v is not None else v)
        res = judge(by_preset, high, low)
        should = ", ".join(SHORT.get(p, p) for p in sorted(high)) + \
            ((" / low: " + ", ".join(SHORT.get(p, p) for p in sorted(low))) if low else "")
        rows.append({"slider": slider, "line": what, "values": raw, "result": res})
        out.append([slider, what] + [fmt(raw[lb]) for lb in labels] + [should, res])
    md = [f"# Slider scorecard: {title}", ""]
    if notes:
        md += ["Runs:", ""] + notes + [""]
    md.append("| Fort | Preset | Season | Population | Levels |")
    md.append("| --- | --- | --- | --- | --- |")
    for lb in labels:
        f, s, m, _ = data[lb]
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
    # (0.105.26) health: fixed bars, every fort on its own
    md += ["", "## Health", "", "| Bar | " + " | ".join(labels) + " | Under the bar |",
           "|" + " --- |" * (len(labels) + 2)]
    issues = {}
    for what, k, bar, how in HEALTH_BARS:
        cells, fine = [], 0
        for lb in labels:
            v = data[lb][3].get(k)
            ok = health_ok(v, bar, how)
            cells.append(fmt(v) + ("" if ok is None or ok else " **over**"))
            fine += bool(ok)
            if ok is False:
                issues.setdefault(lb, []).append(f"{what.split(',')[0].split(' (')[0]} {fmt(v)}")
        md.append(f"| {what} {how} {bar} | " + " | ".join(cells) + f" | {fine} of {len(labels)} |")
    # (0.105.40) the AI's own cost, when a fort has logs/forts/<fort>/perf.jsonl
    ai_ms = {lb: ai_ms_day(data[lb][0]) for lb in labels}
    if any(v is not None for v in ai_ms.values()):
        md.append("| AI ms per game day (median, perf.jsonl) | " + " | ".join(
            fmt(ai_ms[lb]) for lb in labels) + " | |")
    md.append("| moods / artifacts | " + " | ".join(
        f"{data[lb][3]['moods']} / {data[lb][3]['artifacts']}" for lb in labels) + " | |")
    causes = sorted({c for lb in labels for c in data[lb][3]["deaths"]})
    md += ["", "Deaths by cause (this run's journal, or the game's count from last year on when that is more):", ""]
    if causes:
        md += ["| Cause | " + " | ".join(labels) + " |", "|" + " --- |" * (len(labels) + 1)]
        for c in causes:
            md.append(f"| {c} | " + " | ".join(str(data[lb][3]["deaths"].get(c, 0)) for lb in labels) + " |")
        md.append("| **all** | " + " | ".join(str(sum(data[lb][3]["deaths"].values())) for lb in labels) + " |")
    else:
        md.append("none.")
    kinds = sorted({k for lb in labels for k in data[lb][2]["kinds"] if k})
    if kinds:
        md += ["", "Levels started, by kind:", "", "| Kind | " + " | ".join(labels) + " |",
               "|" + " --- |" * (len(labels) + 1)]
        for k in kinds:
            md.append(f"| {k} | " + " | ".join(str(data[lb][2]["kinds"].get(k, 0)) for lb in labels) + " |")
    summary = {"title": title, "tally": dict(tally), "lines": len(rows), "good": good,
               "runs": {lb: data[lb][0].run for lb in labels},
               "health": {lb: issues.get(lb, []) for lb in labels},
               "presets": {lb: data[lb][0].preset for lb in labels}}
    # (D0) the Design block: only once a fort has a design (a setting past
    # Scripts, a level in a language, a landmark), so older reports read the same
    if any(dm[lb]["styled"] or dm[lb]["setting"] in ("guided", "architect") for lb in labels):
        dmd, dsum = design_section(labels, dm)
        md += dmd
        summary["design"] = dsum
    return "\n".join(md) + "\n", rows, summary


def season_name(k: tuple[int, int]) -> str:
    return f"{k[0]}-{SEASONS[k[1]]}"


def every_step(text: str) -> int:
    """--every: seasons ('3') or game years ('2y')."""
    t = str(text).strip().lower()
    try:
        n = int(t[:-1]) * 4 if t.endswith("y") else int(t)
    except ValueError:
        raise SystemExit(f"--every wants a number of seasons (3) or game years (2y), got {text!r}")
    if n < 1:
        raise SystemExit("--every wants at least 1")
    return n


def series_keys(forts: list[Fort], step: int, at: str | None = None) -> list[tuple[int, int]]:
    """Seasons every fort has, every `step` seasons back from the newest common
    one (or from --at), oldest first."""
    forts = [f for f in forts if f.states]
    if not forts:
        return []
    common = set.intersection(*(set(f.states) for f in forts))
    if not common:
        return []
    top = season_key(at) if at else max(common)
    if not top:
        raise SystemExit(f"--at wants YEAR-SEASON, like 252-spring (got {at!r})")
    idx = top[0] * 4 + top[1]
    return sorted(k for k in common if k <= top and (idx - (k[0] * 4 + k[1])) % step == 0)


def summary_md(entries: dict) -> str:
    md = ["# Slider scorecard: the series", "",
          "| Season | Pass | Half | Fail | Flat | No data | Sliders winning every line | Health over the bar |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name in sorted(entries, key=lambda n: season_key(n) or (10 ** 9, 0)):
        e = entries[name]
        t = e.get("tally") or {}
        hl = "; ".join(f"{lb}: {', '.join(v)}" for lb, v in sorted((e.get("health") or {}).items()) if v) or "-"
        md.append(f"| {name} | {t.get('pass', 0)} | {t.get('half', 0)} | {t.get('fail', 0)} | {t.get('flat', 0)} "
                  f"| {t.get('no data', 0)} | {', '.join(e.get('good') or []) or '-'} | {hl} |")
    return "\n".join(md) + "\n"


def write_series(out_dir: Path, results: list[tuple[str, str, dict]]) -> Path:
    """Each scorecard to out_dir/<season>.md, and the summary (kept in
    summary.json between runs; seasons scored under other runs dropped)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, md, _ in results:
        (out_dir / f"{name}.md").write_text(md, encoding="utf-8")
    sj = out_dir / "summary.json"
    old = load_json(sj) or {}
    old = old if isinstance(old, dict) else {}
    runs = next((summ.get("runs") for _, _, summ in reversed(results) if summ), None)
    entries = {n: e for n, e in old.items() if isinstance(e, dict) and (runs is None or e.get("runs") == runs)}
    for name, _, summ in results:
        if summ and name != "now":
            entries[name] = summ
    sj.write_text(json.dumps(entries, indent=1), encoding="utf-8")
    (out_dir / "summary.md").write_text(summary_md(entries), encoding="utf-8")
    return out_dir / "summary.md"


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
    ap.add_argument("--at", help="YEAR-SEASON to compare at (with --every: the newest of the series)")
    ap.add_argument("--now", action="store_true", help="each fort's newest season")
    ap.add_argument("--every", help="a series: every N seasons (3) or game years (2y)")
    ap.add_argument("--out", help="where to write the newest report (default logs/scorecard.md)")
    ap.add_argument("--dir", help="where the series goes (default logs/scorecards)")
    a = ap.parse_args(argv)
    here = Path(__file__).resolve().parent.parent
    if a.fort:
        forts = []
        for x in a.fort:
            lb, _, p = x.partition("=")
            forts.append(Fort(lb, Path(p)))
    else:
        forts = default_forts(here)
    results = []
    if a.every:
        keys = series_keys(forts, every_step(a.every), a.at)
        if not keys:
            md, _, _ = score_full(forts, a.at, a.now)    # says why (no states, a run left out...)
            results.append(("now", md, {}))
        for k in keys:
            md, _, summ = score_full(forts, season_name(k), False)
            results.append((season_name(k), md, summ))
    else:
        md, _, summ = score_full(forts, a.at, a.now)
        name = "now" if a.now else (summ.get("title", "")[len("all at "):] or "now")
        results.append((name, md, summ))
    out = Path(a.out) if a.out else here / "logs" / "scorecard.md"
    series = Path(a.dir) if a.dir else here / "logs" / "scorecards"
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(results[-1][1], encoding="utf-8")
        summary = write_series(series, results)
    except OSError as e:
        print(f"(could not write {out} or {series}: {e})")
        summary = None
    for _, md, _ in results:
        print(md)
    if summary and summary.exists():
        print(summary.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
