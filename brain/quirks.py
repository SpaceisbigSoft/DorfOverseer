"""Fortress quirks: earned, never chosen (see docs/culture.md).

    changes = update(history, traits, stocks, date)

Scripts check every quirk each cycle, at no token cost. A quirk is earned
when its "earn" conditions have held for `earn_days` (sliders nudged for a
moment earn nothing), and lost only when its much stronger "lose" conditions
have held for `lose_days`. At most `max` quirks at once, and at most one new
quirk every `days_between` days. The AI never grants or removes a quirk.

Everything lives in the fort's culture history (kept in the save):
  quirks       {id: {"year", "why"}}
  quirk_watch  {id: {"earn": tick, "lose": tick}}   since when a condition held
  quirk_log    [{"year", "quirk", "change", "why"}]  the newest 20
  quirk_last   tick of the last quirk earned
"""

from __future__ import annotations

from weights import TRAIT_NAMES, data

DAY = 1200
YEAR_TICKS = 403200
LOG_MAX = 20

FACT_TEXT = {
    "stone_per_wood": "more stone than wood",
    "wood_per_stone": "wood stock {v:g}x the stone",
    "eras_last_2_years": "{v:g} new styles in 2 years",
    "eras_last_year": "{v:g} new styles in a year",
    "years_since_new_era": "no new style for {v:g} years",
    "sieges": "{v:g} sieges survived",
    "caverns_reached": "{v:g} caverns reached",
    "deaths_inside_in_siege": "{v:g} citizens killed inside the fort in a siege",
    "years_since_inside_death": "{v:g} years without a siege reaching inside",
    "years_since_siege": "{v:g} years without a siege",
    "surface_water_tiles": "{v:g} tiles of open water by the fort",
    "crossings_built": "{v:g} crossing(s) built over it",
    "crossings_possible": "{v:g} crossing(s) the land needs",
    "freezes": "water freezes here in winter",
    "dry_seasons": "{v:g} seasons with almost no drink",
    "years_since_dry": "{v:g} years since the fort went dry",
    "ghosts": "{v:g} ghost(s) walking the fort",
    "citizen_deaths": "{v:g} citizens dead",
    "trades": "{v:g} caravans traded with",
    "children": "{v:g} children in the fort",
    "tame_animals": "{v:g} tame animals",
    "legendary": "{v:g} legendary dwarf(s)",
    "drink_pd_season": "{v:g} drinks a dwarf last season",
    "libraries": "{v:g} librar(ies)",
    "library_years": "a library for {v:g} years",
    "goblin_wars": "at war with {v:g} goblin civilisation(s)",
    "elf_peace": "at peace with the elves",
    "tree_quota_share": "{v:g} of the elves' tree quota felled this year",
    "forges": "{v:g} forge(s)",
    "magma_forges": "{v:g} magma forge(s)",
    "magma_tiles": "magma below the fort",
    "beds_per_dwarf": "{v:g} beds a dwarf",
    "gems": "{v:g} gems in store",
    "cut_gems": "{v:g} cut gems",
    "jewelers": "{v:g} jeweller's workshop(s)",
    "nobles": "{v:g} noble offices held",
    "top_stone_share": "{v:g} of the stone one kind",
    "years_since_trade": "{v:g} years without a trade",
    "surface_share": "{v:g} of the dwarves living out under the sky",
    "materials_pd": "{v:g} logs and stones a dwarf",
}


def abs_tick(date: dict) -> int:
    return int(date.get("year", 0)) * YEAR_TICKS + int(date.get("tick", 0))


def facts(history: dict, stocks: dict | None, year: int, extra: dict | None = None) -> dict:
    """The numbers quirk conditions can test (only those that are known).
    `extra`: facts from the atlas and the phases (brain/overseer.py world_facts)."""
    f = {k: v for k, v in (extra or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    f["sieges"] = int(history.get("sieges", 0) or 0)
    f["citizen_deaths"] = int(history.get("citizen_deaths", 0) or 0)     # (0.103.2)
    f["trades"] = int(history.get("trades", 0) or 0)                     # (0.103.5)
    # (0.103.18) Hermit Kingdom: years since the last trade (or since the founding)
    lt = history.get("last_trade_year")
    eras0 = (history.get("eras") or [{}])[0] if isinstance(history.get("eras"), list) and history.get("eras") else {}
    since = lt if isinstance(lt, int) else (eras0.get("year") if isinstance(eras0, dict) else None)
    if isinstance(since, int):
        f["years_since_trade"] = max(0, year - since)
    last = history.get("last_siege_year")
    if isinstance(last, int):
        f["years_since_siege"] = year - last
    # (0.105.0) Grudge-keepers: the sieges on the game's own record (brain/planner_world.py
    # grudge_facts) count too, so a fort the AI took over remembers the sieges before it
    if isinstance(f.get("sieges_on_record"), (int, float)):
        f["sieges"] = max(f["sieges"], int(f["sieges_on_record"]))
    if isinstance(f.get("years_since_siege_on_record"), (int, float)):
        f["years_since_siege"] = min(f.get("years_since_siege", 10 ** 6), int(f["years_since_siege_on_record"]))
    if isinstance(stocks, dict) and "wood" in stocks and "boulders" in stocks:
        wood, stone = max(0, stocks.get("wood") or 0), max(0, stocks.get("boulders") or 0)
        f["stone_per_wood"] = stone / max(1, wood)
        f["wood_per_stone"] = wood / max(1, stone)
    eras = history.get("eras") or []
    changes = [e.get("year", 0) for e in eras[1:]]            # the first era is the founding
    f["eras_last_2_years"] = sum(1 for y in changes if y > year - 2)
    f["eras_last_year"] = sum(1 for y in changes if y > year - 1)
    if eras:
        f["years_since_new_era"] = year - (eras[-1].get("year") or year)
    return f


def _clause(c: dict, traits: dict, f: dict) -> tuple[bool | None, float, str]:
    """(holds, how strongly (0 at the threshold), text). None: not known yet."""
    if "slider" in c:
        try:
            v = float((traits or {}).get(c["slider"], 0) or 0)
        except (TypeError, ValueError):
            v = 0.0
        text = f"{TRAIT_NAMES.get(c['slider'], c['slider'])} {int(v):+d}"
        scale = 100.0
    else:
        if c["fact"] not in f:
            return None, 0.0, ""
        v = f[c["fact"]]
        text = FACT_TEXT.get(c["fact"], c["fact"]).format(v=round(v, 1))
        scale = max(1.0, abs(c.get("min", c.get("max", 1))))
    if "min" in c:
        return v >= c["min"], (v - c["min"]) / scale, text
    return v <= c["max"], (c["max"] - v) / scale, text


def _one(c: dict, traits: dict, f: dict) -> tuple[bool | None, float, str]:
    """A clause, or a nested {"all"}/{"any"} group (its texts joined)."""
    if "all" in c or "any" in c:
        ok, strength, texts = _test(c, traits, f)
        return ok, strength, ", ".join(t for t in texts if t)
    return _clause(c, traits, f)


def _test(cond: dict, traits: dict, f: dict) -> tuple[bool, float, list[str]]:
    """{"all": [...]} or {"any": [...]} -> (holds, strength, texts of the clauses that hold).
    A clause may itself be an {"all"} or {"any"} group."""
    if "all" in cond:
        res = [_one(c, traits, f) for c in cond["all"]]
        ok = all(r[0] for r in res)
        return ok, (min(r[1] for r in res) if ok else 0.0), [r[2] for r in res if r[0]]
    res = [_one(c, traits, f) for c in cond.get("any", [])]
    hits = [r for r in res if r[0]]
    return bool(hits), max((r[1] for r in hits), default=0.0), [r[2] for r in hits]


def fade_text(qid: str) -> str:
    """What would make a quirk fade, in words."""
    q = data()["quirks"][qid]
    parts = []
    clauses = []
    for c in q["lose"].get("any", q["lose"].get("all", [])):
        clauses += c.get("all", c.get("any", [])) if ("all" in c or "any" in c) else [c]
    for c in clauses:
        if "slider" in c:
            name = TRAIT_NAMES.get(c["slider"], c["slider"])
            parts.append(f"{name} {'at least' if 'min' in c else 'at most'} {c.get('min', c.get('max')):+d}")
        else:
            t = FACT_TEXT.get(c["fact"], c["fact"]).format(v=c.get("min", c.get("max")))
            parts.append(t)
    days = q.get("lose_days", 0)
    hold = " for a year" if days >= 300 else f" for {days} days" if days else ""
    return " or ".join(parts) + hold


def _dict(history: dict, key: str) -> dict:
    v = history.get(key)
    if not isinstance(v, dict):
        v = history[key] = {}
    return v


def update(history: dict, traits: dict, stocks: dict | None, date: dict,
           extra: dict | None = None) -> list[str]:
    """Check every quirk; earn and lose them. Returns what changed, in words."""
    qs, limits = data()["quirks"], data()["quirk_limits"]
    now, year = abs_tick(date), int(date.get("year", 0))
    f = facts(history, stocks, year, extra)
    # (the game's save turns an empty {} into [], so mend those first)
    held = _dict(history, "quirks")
    watch = _dict(history, "quirk_watch")
    for k in list(watch):
        if not isinstance(watch[k], dict):
            watch[k] = {}
    log = history.get("quirk_log") if isinstance(history.get("quirk_log"), list) else []
    history["quirk_log"] = log
    changes = []

    # losing first: a quirk that goes makes room
    for qid in list(held):
        if qid not in qs:
            continue
        w = watch.setdefault(qid, {})
        ok, _, texts = _test(qs[qid]["lose"], traits, f)
        if not ok:
            w.pop("lose", None)
            continue
        w.setdefault("lose", now)
        if now - w["lose"] >= qs[qid].get("lose_days", 0) * DAY:
            why = ", ".join(texts)
            del held[qid]
            watch.pop(qid, None)
            log.append({"year": year, "quirk": qid, "change": "lost", "why": why})
            changes.append(f"the fort is no longer {qs[qid]['name']} ({why})")

    # then earning: candidates whose conditions have held long enough
    ready = []
    for qid, q in qs.items():
        if qid in held:
            continue
        w = watch.setdefault(qid, {})
        ok, strength, texts = _test(q["earn"], traits, f)
        if not ok:
            w.pop("earn", None)
            continue
        w.setdefault("earn", now)
        if now - w["earn"] >= q.get("earn_days", 0) * DAY:
            ready.append((strength, qid, texts))
    ready.sort(key=lambda r: -r[0])
    last = history.get("quirk_last")
    spaced = last is None or now - last >= limits["days_between"] * DAY
    for strength, qid, texts in ready:
        if not spaced or len(held) >= limits["max"]:
            break
        if any(c in held for c in qs[qid].get("clashes", [])):
            continue                       # waits until the other one is gone
        why = ", ".join(texts)
        held[qid] = {"year": year, "why": why}
        history["quirk_last"] = now
        watch.pop(qid, None)
        log.append({"year": year, "quirk": qid, "change": "earned", "why": why})
        changes.append(f"the fort became {qs[qid]['name']} ({why})")
        break                              # one new quirk at a time
    del log[:-LOG_MAX]
    return changes


def describe(history: dict | None) -> list[dict]:
    """The quirks held, for the panel and the strategist."""
    qs = data()["quirks"]
    out = []
    held = (history or {}).get("quirks")
    for qid, info in (held.items() if isinstance(held, dict) else []):
        if qid in qs and isinstance(info, dict):
            out.append({"id": qid, "name": qs[qid]["name"], "since": info.get("year"),
                        "why": info.get("why", ""), "does": qs[qid]["does"], "fade": fade_text(qid),
                        "ai": qs[qid]["ai"]})
    return out


def has_rule(history: dict | None, rule: str) -> bool:
    qs = data()["quirks"]
    held = (history or {}).get("quirks")
    return isinstance(held, dict) and any(rule in (qs[q].get("rules") or []) for q in held if q in qs)
