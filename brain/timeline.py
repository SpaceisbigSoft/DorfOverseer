"""The timeline: one row of numbers per in-game day, kept as the fort ages.

    timeline.record(state, memory, events, cfg)   # once per cycle (a day's row
                                                  # is updated until the day ends)
    timeline.avg(memory, "drink_pd", first_day, last_day)
    timeline.trend_lines(memory)                  # for the panel and the strategist

The numbers are the outcome log's (outcomes.measure), so verdicts can be
judged on averages instead of two single days, plus a few more.

Ageing, so a long fort keeps the shape of its whole life in a bounded size:
  days     the last DAYS_KEPT days in full (two seasons; the save keeps these
           too, so verdicts still work after reloading an older save)
  seasons  each finished season rolled up (averages, lows, highs, deaths),
           the last SEASONS_KEPT of them
  years    each finished year rolled up from its seasons, all of them

The long daily copy goes to logs/forts/<fort>/timeline.csv (memstore.py).
Kept in memory.timeline: {"fields": [...], "days": [[...], ...], "seasons": [...], "years": [...]}.
Days are stored as lists in FIELDS order, which keeps the save small.
"""

from __future__ import annotations

from digest import _d, normalize
import outcomes

DAY = 1200
DAYS_PER_SEASON = 84
DAYS_PER_YEAR = 336
DAYS_KEPT = 2 * DAYS_PER_SEASON
SEASONS_KEPT = 24                 # six years of seasons; older ones live on as years
SEASON_NAMES = ("spring", "summer", "autumn", "winter")

# One day's row. "day" is the absolute game day (year * 336 + day of year).
FIELDS = ["day", "pop", "drink_pd", "meals_pd", "plants_pd", "unhappy_pct", "happy_pct", "idle_pct",
          "needs_care", "hungry", "unpastured", "free_beds", "wealth", "deaths", "threats",
          "drink_ratio", "meals_ratio", "report_ms"]
# what a season or year keeps of them
AVERAGED = ["pop", "drink_pd", "meals_pd", "plants_pd", "unhappy_pct", "happy_pct", "idle_pct",
            "needs_care", "hungry", "wealth", "drink_ratio", "meals_ratio", "report_ms"]
LOWS = ["pop", "drink_pd", "meals_pd"]
HIGHS = ["pop", "unhappy_pct", "hungry"]
# a year keeps less (it's kept for ever)
YEAR_AVERAGED = ["pop", "drink_pd", "meals_pd", "plants_pd", "unhappy_pct", "happy_pct", "idle_pct", "wealth"]
YEAR_LOWS = ["drink_pd", "meals_pd"]
YEAR_HIGHS = ["pop", "unhappy_pct"]
WORDS = {"pop": "dwarves", "drink_pd": "drink per dwarf", "meals_pd": "meals per dwarf",
         "plants_pd": "food plants per dwarf", "unhappy_pct": "unhappy %", "happy_pct": "happy %",
         "idle_pct": "idle adults %", "wealth": "wealth", "needs_care": "dwarves needing care",
         "hungry": "hungry or thirsty dwarves", "report_ms": "report time (ms)"}
# smallest change between seasons worth a word
TREND_TOL = {"drink_pd": 1.0, "meals_pd": 1.0, "plants_pd": 1.0, "unhappy_pct": 3.0, "happy_pct": 3.0,
             "idle_pct": 5.0, "pop": 3, "wealth": None, "needs_care": 1.0, "hungry": 1.0, "report_ms": 50}


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _state(memory) -> dict:
    t = memory.timeline if isinstance(memory.timeline, dict) else {}
    memory.timeline = t
    for k in ("days", "seasons", "years"):
        if not isinstance(t.get(k), list):
            t[k] = []
    if t.get("fields") != FIELDS:
        # rows written with another field list: re-map them by name
        old = t.get("fields") if isinstance(t.get("fields"), list) else None
        if old and t["days"]:
            t["days"] = [[dict(zip(old, r)).get(f) for f in FIELDS] for r in t["days"] if isinstance(r, list)]
        elif not old:
            t["days"] = []
        t["fields"] = list(FIELDS)
    return t


def today(state: dict) -> int:
    d = state["date"]
    return d["year"] * DAYS_PER_YEAR + d["tick"] // DAY


def season_of(day: int) -> int:
    return day // DAYS_PER_SEASON


def year_of(day: int) -> int:
    return day // DAYS_PER_YEAR


def season_name(season: int) -> str:
    return f"{SEASON_NAMES[season % 4]} {season // 4}"


def row_for(state: dict, events: list[dict] | None = None, cfg: dict | None = None) -> dict:
    """Today's row as a dict (only the numbers that could be read)."""
    s = normalize(state)
    m = outcomes.measure(state)
    row = {"day": today(state), "pop": m.get("pop")}
    for k in ("drink_pd", "meals_pd", "plants_pd", "unhappy_pct", "happy_pct", "idle_pct",
              "needs_care", "hungry", "unpastured", "free_beds"):
        row[k] = m.get(k)
    row["wealth"] = _num(s.get("wealth"))
    row["deaths"] = sum(1 for e in events or [] if isinstance(e, dict) and e.get("kind") == "death"
                        and e.get("own_civ") and not e.get("animal") and not e.get("again"))
    if "others_on_map" not in s["_errors"]:
        row["threats"] = _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves", 0) or 0
    # stock against the target it is kept to (1.0 = exactly the target)
    if cfg and m.get("pop") and "stocks" not in s["_errors"]:
        stock_factor = 2 ** (_d(_d(s.get("settings")).get("traits")).get("stockpile", 0) / 100)
        for k, key in (("drink_ratio", "drink_per_dwarf"), ("meals_ratio", "meals_per_dwarf")):
            want = cfg.get(key)
            have = m.get("drink_pd" if k == "drink_ratio" else "meals_pd")
            if isinstance(want, (int, float)) and want > 0 and have is not None:
                row[k] = round(have / (want * stock_factor), 2)
    if s.get("tier") != "pulse":          # the small report's time says nothing about the full one's
        row["report_ms"] = _num(_d(s.get("_meta")).get("build_ms"))
    return row


def _as_row(r: list) -> dict:
    return dict(zip(FIELDS, r))


def days(memory) -> list[dict]:
    return [_as_row(r) for r in _state(memory)["days"] if isinstance(r, list)]


def _roll(rows: list[dict], key: str, value) -> dict:
    out = {key: value, "n": len(rows), "avg": {}, "low": {}, "high": {}}
    for f in AVERAGED:
        vals = [r[f] for r in rows if _num(r.get(f)) is not None]
        if vals:
            out["avg"][f] = _round(sum(vals) / len(vals))
    for f in LOWS:
        vals = [r[f] for r in rows if _num(r.get(f)) is not None]
        if vals:
            out["low"][f] = min(vals)
    for f in HIGHS:
        vals = [r[f] for r in rows if _num(r.get(f)) is not None]
        if vals:
            out["high"][f] = max(vals)
    out["deaths"] = sum(r.get("deaths") or 0 for r in rows)
    out["threat_days"] = sum(1 for r in rows if (r.get("threats") or 0) > 0)
    return out


def _round(v: float):
    return round(v) if abs(v) >= 100 else round(v, 1)


def _merge_rolls(parts: list[dict], key: str, value) -> dict:
    """A year from its seasons: averages weighted by days seen."""
    out = {key: value, "n": sum(p.get("n", 0) for p in parts), "avg": {}, "low": {}, "high": {}}
    for f in YEAR_AVERAGED:
        pairs = [(p["avg"][f], p.get("n", 1)) for p in parts if f in _d(p.get("avg"))]
        w = sum(n for _, n in pairs)
        if pairs and w:
            out["avg"][f] = _round(sum(v * n for v, n in pairs) / w)
    for f in YEAR_LOWS:
        vals = [p["low"][f] for p in parts if f in _d(p.get("low"))]
        if vals:
            out["low"][f] = min(vals)
    for f in YEAR_HIGHS:
        vals = [p["high"][f] for p in parts if f in _d(p.get("high"))]
        if vals:
            out["high"][f] = max(vals)
    out["deaths"] = sum(p.get("deaths", 0) for p in parts)
    out["threat_days"] = sum(p.get("threat_days", 0) for p in parts)
    return out


def _rewind(t: dict, day: int) -> None:
    """An older save was loaded: forget the days after it."""
    t["days"] = [r for r in t["days"] if isinstance(r, list) and r and r[0] < day]
    t["seasons"] = [s for s in t["seasons"] if isinstance(s, dict) and s.get("season", 0) < season_of(day)]
    t["years"] = [y for y in t["years"] if isinstance(y, dict) and y.get("year", 0) < year_of(day)]


def record(state: dict, memory, events: list[dict] | None = None, cfg: dict | None = None) -> dict | None:
    """Add (or update) today's row, and roll up finished seasons and years.
    Returns the finished day's row when a new day began (for the log file), else None.
    (0.105.33, B5) A report whose date failed reads as year 0, tick 0: not an
    older save. Nothing is recorded (or rewound) for it."""
    t = _state(memory)
    if "date" in normalize(state)["_errors"]:
        return None
    row = row_for(state, events, cfg)
    day = row["day"]
    finished = None
    if t["days"] and isinstance(t["days"][-1], list) and t["days"][-1][0] > day:
        _rewind(t, day)
    last = _as_row(t["days"][-1]) if t["days"] else None
    if last and last["day"] == day:
        # the same day again (an event cycle): newest reading, deaths add up
        row["deaths"] = (last.get("deaths") or 0) + row["deaths"]
        for k, v in last.items():
            if row.get(k) is None:
                row[k] = v
        t["days"][-1] = [row.get(f) for f in FIELDS]
    else:
        if last:
            finished = last
        t["days"].append([row.get(f) for f in FIELDS])
    _consolidate(t, day)
    return finished


def _consolidate(t: dict, day: int) -> None:
    rows = [_as_row(r) for r in t["days"] if isinstance(r, list)]
    done = {s.get("season") for s in t["seasons"] if isinstance(s, dict)}
    current = season_of(day)
    for season in sorted({season_of(r["day"]) for r in rows}):
        if season < current and season not in done:
            t["seasons"].append(_roll([r for r in rows if season_of(r["day"]) == season], "season", season))
    t["seasons"].sort(key=lambda s: s.get("season", 0))
    # years from their seasons (once the year is over)
    have_years = {y.get("year") for y in t["years"] if isinstance(y, dict)}
    by_year: dict[int, list] = {}
    for s in t["seasons"]:
        by_year.setdefault(s["season"] // 4, []).append(s)
    for year, parts in by_year.items():
        if year < year_of(day) and year not in have_years:
            t["years"].append(_merge_rolls(parts, "year", year))
    t["years"].sort(key=lambda y: y.get("year", 0))
    t["days"] = [r for r in t["days"] if isinstance(r, list) and r[0] > day - DAYS_KEPT]
    del t["seasons"][:-SEASONS_KEPT]


def window(memory, first_day: int, last_day: int) -> list[dict]:
    return [r for r in days(memory) if first_day <= r["day"] <= last_day]


def avg(memory, metric: str, first_day: int, last_day: int, min_days: int = 1) -> tuple[float | None, int]:
    """(average, days seen) of one number over a span of days."""
    vals = [r[metric] for r in window(memory, first_day, last_day) if _num(r.get(metric)) is not None]
    if len(vals) < min_days:
        return None, len(vals)
    return round(sum(vals) / len(vals), 2), len(vals)


def share(memory, metric: str, test, last_days: int, now_day: int) -> tuple[float | None, int]:
    """(share of days where test(value) holds, days seen) over the last days."""
    vals = [r[metric] for r in window(memory, now_day - last_days + 1, now_day) if _num(r.get(metric)) is not None]
    if not vals:
        return None, 0
    return round(sum(1 for v in vals if test(v)) / len(vals), 2), len(vals)


def _season_avg(t: dict, season: int) -> tuple[dict, int]:
    for s in t["seasons"]:
        if s.get("season") == season:
            return _d(s.get("avg")), s.get("n", 0)
    rows = [_as_row(r) for r in t["days"] if isinstance(r, list) and season_of(r[0]) == season]
    if not rows:
        return {}, 0
    rolled = _roll(rows, "season", season)
    return rolled["avg"], rolled["n"]


def trends(memory, now_day: int | None = None) -> list[dict]:
    """This season so far against the last one: [{metric, now, before, move}]
    (move: "rising", "falling", "steady")."""
    t = _state(memory)
    if now_day is None:
        if not t["days"]:
            return []
        now_day = t["days"][-1][0]
    cur, n_cur = _season_avg(t, season_of(now_day))
    prev, n_prev = _season_avg(t, season_of(now_day) - 1)
    if n_cur < 7 or n_prev < 7:
        # early in a season: the last 4 weeks against the 4 before
        a = {m: avg(memory, m, now_day - 27, now_day, 7)[0] for m in AVERAGED}
        b = {m: avg(memory, m, now_day - 55, now_day - 28, 7)[0] for m in AVERAGED}
        cur, prev = {k: v for k, v in a.items() if v is not None}, {k: v for k, v in b.items() if v is not None}
    out = []
    for m in ("drink_pd", "meals_pd", "unhappy_pct", "idle_pct", "pop", "hungry", "wealth"):
        if m not in cur or m not in prev:
            continue
        tol = TREND_TOL.get(m)
        if tol is None:
            tol = max(1.0, 0.1 * abs(prev[m]))
        d = cur[m] - prev[m]
        move = "steady" if abs(d) < tol else ("rising" if d > 0 else "falling")
        out.append({"metric": m, "now": cur[m], "before": prev[m], "move": move})
    return out


def _fmt(v) -> str:
    if isinstance(v, float) and abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def trend_lines(memory, limit: int = 6, now_day: int | None = None) -> list[str]:
    """'drink per dwarf 8.1, falling (11.4 the season before)' - changes first."""
    tr = trends(memory, now_day)
    tr.sort(key=lambda x: x["move"] == "steady")
    out = []
    for x in tr[:limit]:
        w = WORDS.get(x["metric"], x["metric"])
        if x["move"] == "steady":
            out.append(f"{w} {_fmt(x['now'])}, steady")
        else:
            out.append(f"{w} {_fmt(x['now'])}, {x['move']} ({_fmt(x['before'])} the season before)")
    return out

