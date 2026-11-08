"""Self-calibration: a few of the planner's rules of thumb tune themselves to
the fort, slowly and within fixed bounds. No tokens.

    changes = update(state, memory, cfg)    # once per cycle, before planning
    cfg = effective_config(memory.adjust, calibration=values(memory))

What tunes itself, and on what evidence (each over a window of in-game days):

  drink_per_dwarf   the stock fell below the urgent line (2 per dwarf): +2.
                    The reserve was drawn below 60% of the target but never got
                    that low: the target is more than the fort needs, -1.
  meals_per_dwarf   the same, with meals.
  farm_tiles_per_dwarf  only while the farms are at their target size: food
                    ran thin, x1.15; plenty of food plants (8+ per dwarf) the
                    whole time and many idle hands, x0.9.
  pasture_margin    a new pasture was needed again within a season of the AI
                    making one: +0.15. The AI's pastures stood more than half
                    empty for a whole season: -0.05.

After a change a value waits before it moves again. A value the strategist has
set itself (memory.adjust) is left alone: its call wins. Kept in the fort's
memory (memory.calibration): values, windows, last changes, and a short log.
"""

from __future__ import annotations

from digest import _d, normalize
from util import state_tick as _now

DAY = 1200
LOG_MAX = 12

# key -> (low, high, raise step, lower step, multiply?, window days, wait days after a change)
BOUNDS = {
    "drink_per_dwarf": (6, 20, 2, 1, False, 14, 28),
    "meals_per_dwarf": (5, 16, 2, 1, False, 14, 28),
    "farm_tiles_per_dwarf": (0.5, 2.0, 1.15, 0.9, True, 28, 28),
    "pasture_margin": (1.1, 2.0, 0.15, 0.05, False, 84, 84),
}
NAMES = {"drink_per_dwarf": "drink kept per dwarf", "meals_per_dwarf": "meals kept per dwarf",
         "farm_tiles_per_dwarf": "farm tiles per dwarf", "pasture_margin": "room in a new pasture (x the herd)"}
# Each key's evidence revision. When how a key is judged changes (or a bug
# fed it wrong evidence), its number goes up and values learned under the
# old one are dropped and learned again: a fort never keeps a value a bug
# taught it. 2 (bridge 0.41): meals and farms judge "thin" by all food a
# dwarf, not by cooked meals (a young fort eats raw food; 0.39 raised the
# meal target to 16 because nothing was cooked yet).
REVISIONS = {"drink_per_dwarf": 1, "meals_per_dwarf": 2, "farm_tiles_per_dwarf": 2, "pasture_margin": 1}
PLENTY_PLANTS_PD = 8
IDLE_PLENTY_PCT = 25
DRAWN_SHARE = 0.6


def _state(memory) -> dict:
    c = memory.calibration if isinstance(memory.calibration, dict) else {}
    memory.calibration = c
    for k, default in (("values", {}), ("windows", {}), ("changed", {}), ("log", []), ("revisions", {})):
        if not isinstance(c.get(k), type(default)):
            c[k] = default            # (the save turns an empty {} into [])
    for key, rev in REVISIONS.items():
        had = c["revisions"].get(key, 1)
        if not isinstance(had, int) or had < rev:
            # learned under older evidence: forget it and learn again
            if key in c["values"]:
                c["log"].append({"key": key, "old": c["values"][key], "new": None,
                                 "why": "learned from evidence that has since been corrected: learning again"})
                del c["log"][:-LOG_MAX]
            for part in ("values", "windows", "changed"):
                c[part].pop(key, None)
        c["revisions"][key] = rev
    # values outside today's bounds (the bounds changed): brought inside
    for key, v in list(c["values"].items()):
        if key in BOUNDS and isinstance(v, (int, float)):
            lo, hi = BOUNDS[key][0], BOUNDS[key][1]
            c["values"][key] = max(lo, min(hi, v))
    return c


def values(memory) -> dict:
    """The tuned values, for effective_config (only ones that moved)."""
    vals = _state(memory)["values"]
    return {k: v for k, v in vals.items() if k in BOUNDS and isinstance(v, (int, float))}


def _window(c: dict, key: str, now: int) -> dict:
    w = c["windows"].get(key)
    if not isinstance(w, dict) or w.get("start", 0) > now:
        w = c["windows"][key] = {"start": now, "days": []}
    if not isinstance(w.get("days"), list):
        w["days"] = []
    return w


def _step(key: str, value: float, up: bool) -> float:
    lo, hi, rise, fall, mult, _, _ = BOUNDS[key]
    if mult:
        v = value * (rise if up else fall)
    else:
        v = value + (rise if up else -fall)
    v = max(lo, min(hi, v))
    return round(v, 2) if mult or isinstance(rise, float) else int(round(v))


def _observe(key: str, state: dict, memory, cfg: dict) -> dict | None:
    """Today's evidence for one key (None: nothing to learn from today)."""
    s = normalize(state)
    err = s["_errors"]
    pop = _d(s.get("dwarves")).get("total") or 0
    if pop < cfg.get("min_citizens", 7) or "stocks" in err:
        return None
    st = _d(s.get("stocks"))
    from planner import food_per_dwarf                   # (planner imports nothing from here)
    food_thin = food_per_dwarf(s) < cfg["urgent_meals_per_dwarf"]
    if key in ("drink_per_dwarf", "meals_per_dwarf"):
        stock = st.get("drink" if key == "drink_per_dwarf" else "prepared_meals") or 0
        urgent = cfg["urgent_drink_per_dwarf" if key == "drink_per_dwarf" else "urgent_meals_per_dwarf"]
        target = pop * cfg[key] * 2 ** (_d(_d(s.get("settings")).get("traits")).get("stockpile", 0) / 100)
        # meals: thin only when the fort is short of food altogether (dwarves eat
        # raw food too; few meals with plenty of food is the cooks' problem)
        thin = stock < urgent * pop if key == "drink_per_dwarf" else food_thin
        return {"thin": thin, "ratio": round(stock / target, 3) if target else 1.0}
    if key == "farm_tiles_per_dwarf":
        if "farms" in err or "settings" in err:
            return None
        from planner import farm_target                      # (planner imports nothing from here)
        traits = _d(_d(s.get("settings")).get("traits"))
        if traits.get("agriculture", 0) <= -100:
            return None
        have = int(_d(s.get("farms")).get("tiles") or 0)
        want = farm_target(s, traits, pop, cfg)
        thin = st.get("drink", 0) < cfg["urgent_drink_per_dwarf"] * pop or food_thin
        dw = _d(s.get("dwarves"))
        idle = 100 * (dw.get("idle_adults") or 0) / max(1, dw.get("adults") or 0)
        return {"full": have >= 0.9 * want, "thin": thin, "plants_pd": round(sum(st.get(k) or 0 for k in ("plants", "plant_growths")) / pop, 2),
                "idle": round(idle, 1)}
    if key == "pasture_margin":
        if "society" in err:
            return None
        so = _d(s.get("society"))
        waiting = so.get("grazers_unpastured") or 0
        spare, smallest = so.get("pasture_spare"), so.get("grazer_tiles_smallest") or 1
        made = memory.last_fired.get("new_pasture")
        now = _now(state)
        recent = made is not None and 0 <= now - made < 84 * DAY
        no_room = bool(waiting) and (not so.get("pastures") or (spare is not None and spare < smallest))
        tiles, free = so.get("ai_pasture_tiles"), so.get("ai_pasture_spare")
        share = (free / tiles) if isinstance(tiles, (int, float)) and tiles and isinstance(free, (int, float)) else None
        return {"too_small": recent and no_room and bool(memory.calibration.get("pasture_made_once")),
                "empty_share": share, "waiting": waiting}
    return None


def _decide(key: str, days: list[dict]) -> tuple[bool | None, str]:
    """(True: raise, False: lower, None: keep) and why, from a window's days."""
    if not days:
        return None, ""
    if key in ("drink_per_dwarf", "meals_per_dwarf"):
        what = "drink" if key == "drink_per_dwarf" else "meals"
        if any(d.get("thin") for d in days):
            return True, f"{what} fell below the urgent line"
        low = min(d.get("ratio", 1.0) for d in days)
        if low < DRAWN_SHARE:
            return False, f"{what} fell to {round(100 * low)}% of the target and the fort never ran short"
        return None, ""
    if key == "farm_tiles_per_dwarf":
        if not all(d.get("full") for d in days):
            return None, ""               # the farms aren't at their size yet: the size can't be judged
        if any(d.get("thin") for d in days):
            return True, "food ran thin with the farms at their full size"
        if (min(d.get("plants_pd", 0) for d in days) >= PLENTY_PLANTS_PD
                and sum(d.get("idle", 0) for d in days) / len(days) >= IDLE_PLENTY_PCT):
            return False, (f"at least {PLENTY_PLANTS_PD} food plants per dwarf all the time, "
                           "with many idle hands")
        return None, ""
    if key == "pasture_margin":
        if any(d.get("too_small") for d in days):
            return True, "a new pasture was needed again within a season of the last one"
        shares = [d.get("empty_share") for d in days]
        if shares and all(isinstance(x, (int, float)) and x > 0.5 for x in shares) \
                and not any(d.get("waiting") for d in days):
            return False, "the AI's pastures stood more than half empty for a whole season"
        return None, ""
    return None, ""


def update(state: dict, memory, cfg: dict, adjust: dict | None = None) -> list[dict]:
    """Gather today's evidence; at the end of a window, maybe move a value.
    Returns the changes: [{"key", "name", "old", "new", "up", "why"}]."""
    c = _state(memory)
    now = _now(state)
    today = now // DAY
    adjust = adjust or {}
    if memory.last_fired.get("new_pasture") is not None:
        c["pasture_made_once"] = True
    changes = []
    for key, (lo, hi, _r, _f, _m, window_days, wait_days) in BOUNDS.items():
        if key in adjust:
            c["windows"].pop(key, None)  # the strategist's value: not tuned here
            continue
        last = c["changed"].get(key)
        if isinstance(last, (int, float)) and last > now:
            c["changed"].pop(key, None)  # an older save: forget the future
            last = None
        if isinstance(last, (int, float)) and now - last < wait_days * DAY:
            c["windows"][key] = {"start": now, "days": []}   # the next window starts after the wait
            continue
        w = _window(c, key, now)
        ev = _observe(key, state, memory, cfg)
        if ev is not None and (not w["days"] or w["days"][-1].get("day") != today):
            w["days"].append(dict(ev, day=today))
            del w["days"][:-120]
        if now - w["start"] < window_days * DAY:
            continue
        days = w["days"]
        c["windows"][key] = {"start": now, "days": []}
        if len(days) < max(3, window_days // 2):
            continue                     # too few days seen (the game wasn't running): no verdict
        up, why = _decide(key, days)
        if up is None:
            continue
        old = c["values"].get(key, cfg.get(key))
        if not isinstance(old, (int, float)):
            continue
        new = _step(key, old, up)
        if new == old:
            continue
        c["values"][key] = new
        c["changed"][key] = now
        ch = {"key": key, "name": NAMES[key], "old": old, "new": new, "up": up, "why": why,
              "date": f"{state['date'].get('day')} {state['date'].get('month')} y{state['date'].get('year')}"}
        c["log"] = (c["log"] + [ch])[-LOG_MAX:]
        changes.append(ch)
    return changes


def describe(memory, base: dict) -> list[dict]:
    """Each tuned value against its starting guess, for the panel and the strategist."""
    c = _state(memory)
    out = []
    for key, v in values(memory).items():
        last = next((x for x in reversed(c["log"]) if x.get("key") == key), None)
        out.append({"key": key, "name": NAMES[key], "value": v, "default": base.get(key),
                    "why": (last or {}).get("why", ""), "date": (last or {}).get("date", "")})
    return out


def evidence(memory, now_day: int | None = None, days: int = 84) -> list[str]:
    """What the timeline says about the tuned targets over the last season,
    in words: 'drink below its target on 30% of the last 84 days'."""
    import timeline                       # (timeline imports nothing from here)
    rows = timeline.days(memory)
    if not rows:
        return []
    if now_day is None:
        now_day = rows[-1]["day"]
    out = []
    for metric, what in (("drink_ratio", "drink"), ("meals_ratio", "meals")):
        share, n = timeline.share(memory, metric, lambda v: v < 1.0, days, now_day)
        if share is not None and n >= 7:
            out.append(f"{what} below its target on {round(100 * share)}% of the last {n} days")
    plants, n = timeline.avg(memory, "plants_pd", now_day - days + 1, now_day, 7)
    if plants is not None:
        out.append(f"food plants per dwarf {plants:g} on average over the last {n} days")
    return out


def heed(e: dict, memory, state: dict) -> dict | None:
    """(0.102.7, learning bug B6: verdicts were never used) A raise this
    script made that the outcome log judged "no effect" or "hurt" is taken
    back: a higher target that didn't lift the stock only ties up work.
    Returns the change, or None."""
    if not isinstance(e, dict) or e.get("by") != "self-tuning" or e.get("verdict") not in ("none", "hurt"):
        return None
    key, old, new = e.get("tune_key"), e.get("tune_old"), e.get("tune_new")
    if key not in BOUNDS or not isinstance(old, (int, float)) or not isinstance(new, (int, float)):
        return None
    c = _state(memory)
    if c["values"].get(key) != new:
        return None                       # moved again since (or set by the strategist): leave it
    c["values"][key] = old
    now = _now(state)
    c["changed"][key] = now
    ch = {"key": key, "name": NAMES[key], "old": new, "new": old, "up": False,
          "why": f"the raise was judged \"{'no effect' if e['verdict'] == 'none' else 'hurt'}\": taken back",
          "date": f"{state['date'].get('day')} {state['date'].get('month')} y{state['date'].get('year')}"}
    c["log"] = (c["log"] + [ch])[-LOG_MAX:]
    return ch
