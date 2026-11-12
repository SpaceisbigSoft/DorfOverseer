"""Turn a full fort report into a compact digest for the AI strategist.

The full report (logs/snapshots/*.json) is ~115 KB for a 194-dwarf fort; most of
it is a per-dwarf list the strategist rarely needs. The digest keeps the numbers
that drive decisions and groups repeated things. It never names individual
dwarves: the AI is an overseer that sets fort-wide policy. `diff()` goes further and reports only what changed.

Usage from the command line (prints the digest of the newest snapshot):

    python brain/digest.py [snapshot.json] [--diff older.json]
"""

from __future__ import annotations

import os
import json
import sys
from collections import Counter
from pathlib import Path

STOCK_ORDER = [
    ("drink", "drink"), ("prepared_meals", "meals"), ("meat", "meat"), ("fish", "fish"),
    ("plants", "plants"), ("seeds", "seeds"), ("wood", "wood"), ("boulders", "boulders"),
    ("blocks", "blocks"), ("metal_bars", "bars"), ("cloth", "cloth"), ("thread", "thread"),
    ("leather", "leather"), ("rough_gems", "rough_gems"), ("cut_gems", "cut_gems"),
    ("weapons", "weapons"), ("armor", "armor"), ("ammo", "ammo"), ("barrels", "barrels"),
    ("bins", "bins"),
]
UNHAPPY = ("miserable", "very_unhappy", "unhappy")


def _d(v) -> dict:
    return v if isinstance(v, dict) else {}


def _l(v) -> list:
    return v if isinstance(v, list) else []


def _top(counts: dict, n: int) -> str:
    items = sorted(_d(counts).items(), key=lambda kv: (-kv[1], kv[0]))
    shown = " ".join(f"{k}:{v}" for k, v in items[:n])
    rest = len(items) - n
    return shown + (f" +{rest} more" if rest > 0 else "")


def _reach_word(ts: list) -> str:
    vals = {t.get("can_reach_dwarves") for t in ts}
    fly = "(flier)" if any(t.get("flier") for t in ts) else ""
    if vals == {True}:
        return "CAN_REACH"
    if True in vals:
        return "SOME_CAN_REACH"
    if vals == {False}:
        return "no_walk_path" + fly
    return "no_walk_path_found" + fly  # some unknown: flying/swimming/open air


_NOT_IN_GAME_TEXT = str.maketrans({c: " " for c in "{}[]<>`|\\"})


def game_text(v, n: int = 40) -> str:
    """(0.100, security pass) Text from the game (a name, a nickname, an
    announcement) for the strategist's report: one line, printable, no
    brackets or braces (nothing that reads as JSON or markup), capped. A
    nickname can be anything a player typed."""
    t = "".join(ch if ch.isprintable() else " " for ch in str(v if v is not None else "?"))
    t = " ".join(t.translate(_NOT_IN_GAME_TEXT).split())
    return (t[:n - 1] + "…") if len(t) > n else (t or "?")


def _threat_groups(threats: list) -> list[str]:
    groups: dict[str, list] = {}
    for t in threats:
        # Forgotten beasts have unique names; everything else groups by kind.
        name = game_text(t.get("name", "?"), 60)
        if '"' in name and "," in name:
            name = name.split(",")[-1].strip() + " " + name.split('"')[1]
        groups.setdefault((name, t.get("layer")), []).append(t)
    out = []
    # Reachable threats first: those are the ones that matter now.
    order = sorted(groups.items(), key=lambda kv: (
        not any(t.get("can_reach_dwarves") for t in kv[1]), -len(kv[1])))
    for (name, _layer), ts in order:
        zs = [_d(t.get("pos")).get("z") for t in ts if _d(t.get("pos")).get("z") is not None]
        z = f" z{min(zs)}" + (f"-{max(zs)}" if zs and max(zs) != min(zs) else "") if zs else ""
        layer = f" {ts[0]['layer']}" if ts[0].get("layer") else ""
        tags = ("!" if ts[0].get("great_danger") else "") + ("inv" if ts[0].get("invader") else "")
        # Reports from bridge 0.4+ always carry a layer; there, a missing
        # can_reach_dwarves means "DF's walking map can't say", not "old report".
        reach = f" {_reach_word(ts)}" if any("layer" in t for t in ts) else ""
        out.append(f"{name} x{len(ts)}{layer}{z}{reach}{(' ' + tags) if tags else ''}")
    return out


SECTION_DEFAULTS = {
    # (13c) read directly by the planner, digest and strategist: a missing or
    # failed one used to raise and lose the whole cycle
    "dwarves": {"total": 0, "adults": 0, "children": 0, "idle_adults": 0, "in_squads": 0,
                "needs_medical_care": 0, "professions": {}, "stress": {}},
    "date": {"year": 0, "tick": 0, "day": 1, "month": "Granite", "season": "spring"},
    "paused": False,
    "stocks": {},
    "buildings": {"workshops": {}, "furnaces": {}, "zones": {}, "other": {}, "stockpiles": 0,
                  "under_construction": 0, "workshop_jobs_queued": 0},
    "jobs": {"total": 0, "suspended": 0, "by_type": {}},
    "others_on_map": {"threats": [], "threats_that_can_reach_dwarves": 0, "contained_dangers": 0,
                      "visitors": 0, "merchants": 0, "diplomats": 0, "tame_animals": 0},
    "nobles": [],
    "mandates": [],
    "recent_announcements": [],
    "orders": [],
    "tools": {},
    "settings": {"traits": {}},
    "projects": {"open": [], "decorating": [], "finished": 0, "done_total": 0, "max_open": 2},   # (0.105.33) done_total: levels ever finished
    "stone_types": [],
    "stone_use": {},          # {usable, economic: {TOKEN: {n, ore, flux}}} (bridge 0.51)
    "locations": {"count": {}, "total": 0},
    "petitions": {},
    "alerts": {},
    "diplomacy": {},
    "meetings": {},
    "world": {},                  # (0.105.0) civs, war and peace, sieges, tribute, agreements, the meeting screen
    "ledger": {},                 # (0.104.0) the AI's ledger saved with the game
    "supplies": {},
    "dead": {},
    "room_gaps": {},              # (0.104.20) rooms whose walls were dug open
    "planned": {},                # (0.104.154) buildings buildingplan waits on: what each lacks, why suspended
    "justice": {},                # (0.104.52) jail zones, restraints, punishments waiting
    "moods": {"list": []},
    "missions": {"controllers": [], "squads": [], "reports": {"n": 0, "unviewed": 0},   # (0.104.95, 13b)
                 "spoils": {"n": 0}, "sites": {}, "unknown": [],
                 "targets": []},          # (0.105.39) what a mission could go for, best first (lua/ai-missions.lua)
    "hazards": {},
    "threats": {},                # (0.105.0) round 3: fire, prisoners, thieves, undead, werebeasts (lua/ai-threats.lua)
    "health": {},
    "waterworks": {"works": {}, "refused": {}},   # (0.105.0) moat, pumps, irrigation, magma workshops (lua/ai-waterworks.lua)
    "infection": {},              # (0.104.168) the infected: untreated, bleeding, beds free (lua/ai-health.lua)
    "military": {"squads": [], "soldiers": 0, "routines": [], "gates": []},
    "society": {},
    "entrances": {},              # (0.105.3) intruders_inside (ids) left out: unknown, the old gate rules
    "farms": {"plots": 0, "tiles": 0, "built": 0},
    "registry": [],          # every AI project with its bounds (lua/ai-builder.lua registry_report)
    "labor": {},
    "industry": {},
    "homes": {},             # (0.104.168) households: bedrooms, couples in one room or two, rough sleepers (lua/ai-homes.lua)
    "citizens_taste": {},    # (E4) the grown-ups' leanings, dreams, values and likes, summed (lua/ai-homes.lua citizens_taste)
    "noble_demands": {},     # (0.105.41) {nobles: [{unit_id, name, title, positions, rooms: [{kind, need, zone_id, value...}]}], monarch, capital, land_holders} (lua/ai-noble-demands.lua)
    "noble_rooms": {},       # {nobles: [{unit_id, name, office, needs}], free: {office, bedroom...}} (lua/ai-nobles.lua)
    "trade": {},             # {depot, caravans: [{civ, state}], goods, goods_value, at_depot} (lua/ai-trade.lua)          # {ores: {METAL: {tiles, ore}}} uncovered near the fort (lua/ai-industry.lua)             # {miners, picks, soldier_picks, dig, want, need, candidates} (lua/ai-labor.lua)
    "founding": {},          # {stairs: has the fort a staircase, near: the wagon or the dwarves}
    "constructions": {},     # (0.105.30) built walls, floors...: by shape, item, surface (lua/ai-constructions.lua)
    "landmarks": {"list": []},   # (D0) the Design track's landmarks: id, name, purpose, status, stage, levels, project_ids
    "civ_alert": False,      # (0.105.33) a failed read ({error}) read as "the alarm is on"
    "perf": {},              # (0.105.40) the report's own cost: sections' ms, cached, total_ms, fps (lua/ai-bridge.lua perf_section)
    "cleanup": {},           # (0.105.40) world cleanup: unreachable items and creatures, spatter, dead units (lua/ai-cleanup.lua)
    "weather": {},           # (fix41) evil weather, read each pulse too (lua/ai-threats.lua weather_section)
    "captives": {},          # (item6) caged prisoners one by one, the AI's pit (lua/ai-captives.lua)
    "necro": {},             # (item6) a necromancer siege: the dead, raisers, bodies outside, towers near (lua/ai-captives.lua)
    "insane": {},            # (0.105.40b) the insane, the deadly ground near them, the AI's doors locked, the near-breaking (lua/ai-insane.lua)
    "hauling": {},           # (0.105.40 M5) haul jobs waiting, haulers, key workers hauling (lua/ai-hauling.lua)
    "traffic": {},           # (0.105.41) traffic zones on the AI's finished levels: waiting, in progress, rechecks (lua/ai-traffic.lua)
    "food_store": {},        # (0.105.40b, M6) food piles, their barrels and fullness, food out of piles, rotten (lua/ai-food-store.lua)
    "pile_links": {},        # (0.105.41, item 2) wheelbarrows, the AI's stone piles, its feeders' links (lua/ai-pile-links.lua)
    "provisions": {},        # (0.105.41, item 4) game and hunters, butchery and tanning, fruit trees, meals by kind, cavern farms (lua/ai-provisions.lua)
    "siege": {},             # (item5) entrances' fortifications and posts, siege engines, parts, arrows, operators (lua/ai-siege.lua)
    "field_watch": {},       # (item5) hostiles near a caravan, hostile wild animals near the dwarves outside (lua/ai-siege.lua)
}
# (0.105.36) not REQUIRED (the plan goes on without them), but a missing one is
# listed in _errors as a failed one is: the default (civ_alert False) is not
# what the game said, and note_cycle must not take it as the player's lowering
UNREAD_IS_ERROR = ("civ_alert",)

# (0.105.33) Sections the rules read through their own guards (`"error" in d`,
# `is True`, or "None: no such section"): a failure is listed in _errors, so
# the planner sees "failed", not "nothing there", but the value is left as
# it came (an empty default would read as a working, empty section).
LISTED_ONLY = ("needs", "deep", "water", "disposal", "offices", "crossings", "logistics",
               "order_desk", "civ_alert_ready", "civ_alert_shelter", "units")

# Sections the planner decides from. If one of these is MISSING (e.g. a report
# from an older bridge), that's treated as a failure, not as "nothing there":
# otherwise "no orders key" would read as "0 queued" and duplicate orders.
REQUIRED = ("date", "dwarves", "stocks", "orders", "tools", "settings", "others_on_map", "mandates", "projects", "locations",
            "supplies", "dead", "moods", "military", "society", "farms")


def normalize(s: dict) -> dict:
    """If a report section failed inside the game it arrives as {"error": ...}.
    Swap in an empty default so everything else still works, and list the
    failures in s["_errors"]. Safe to call more than once on the same report:
    errors found earlier are kept."""
    errors = dict(s.get("_errors") or {})
    for key, default in SECTION_DEFAULTS.items():
        v = s.get(key)
        if isinstance(v, dict) and "error" in v:
            errors[key] = v["error"]
            s[key] = json.loads(json.dumps(default))
        elif v is None:
            if (key in REQUIRED or key in UNREAD_IS_ERROR) and key not in errors:
                errors[key] = "missing from the report (older ai-bridge?)"
            s[key] = json.loads(json.dumps(default))
        elif isinstance(default, dict) and v == []:
            # DFHack's JSON writes an empty Lua table as [], not {}
            s[key] = json.loads(json.dumps(default))
        elif not isinstance(v, type(default)):
            errors[key] = f"unexpected type {type(v).__name__}"
            s[key] = json.loads(json.dumps(default))
    # (0.105.26) the fort's wealth: a number, or failed / missing (digest() says "?")
    w = s.get("wealth")
    if isinstance(w, dict) and "error" in w:
        errors["wealth"] = w["error"]
        s["wealth"] = None
    elif w is not None and (isinstance(w, bool) or not isinstance(w, (int, float))):
        errors["wealth"] = f"unexpected type {type(w).__name__}"
        s["wealth"] = None
    for key in LISTED_ONLY:
        v = s.get(key)
        if isinstance(v, dict) and "error" in v and key not in errors:
            errors[key] = v["error"]
    m = s.get("map")
    # (0.105.26) the whole map section failed: said, not shown as an empty map
    if isinstance(m, dict) and "error" in m and not isinstance(m.get("layers"), list):
        errors["map"] = m["error"]
        s["map"] = m = {}
    elif m is not None and not isinstance(m, dict):
        errors["map"] = f"unexpected type {type(m).__name__}"
        s["map"] = m = {}
    elif isinstance(m, dict) and "error" in m:
        errors["map.size"] = m["error"]          # (0.105.33) only the header (size, elevation) failed
    if isinstance(m, dict):
        for key in ("layers", "dwarves"):
            v = m.get(key)
            if isinstance(v, dict) and "error" in v and len(v) == 1:
                errors[f"map.{key}"] = v["error"]
                m[key] = [] if key == "layers" else {}
    # (0.105.38) the whole-map water survey's list: a default when absent (an
    # older bridge or survey) or of the wrong type; a failed section stays
    # as it came (LISTED_ONLY)
    w = s.get("water")
    if isinstance(w, dict) and "error" not in w:
        for key, default in WATER_DEFAULTS.items():
            if not isinstance(w.get(key), type(default)) or isinstance(w.get(key), bool):
                w[key] = json.loads(json.dumps(default))
    # (0.105.39) the missions' targets: [] when absent (an older bridge) or not a list
    ms = s.get("missions")
    if isinstance(ms, dict) and "error" not in ms and not isinstance(ms.get("targets"), list):
        ms["targets"] = []
    s["_errors"] = errors
    _magma_aliases(s)
    return s


WATER_DEFAULTS = {"waters": [], "waters_found": 0}      # (0.105.38) lua/ai-water.lua


def perf_line(s: dict) -> str:
    """(0.105.40) PERF: the report's total ms, its slowest sections, the FPS
    (brain/perf.py); "" without a perf section."""
    import perf
    return perf.perf_line(s)


def missions_line(s: dict) -> str:
    """(0.105.39) MISSIONS: the targets a mission could go for and the
    missions out, no coordinates (brain/planner_missions.py mission_line);
    "" with neither."""
    try:
        from planner_missions import mission_line
    except Exception:  # noqa: BLE001
        return ""
    return mission_line(s)


def cleanup_line(s: dict) -> str:
    """(0.105.40) The world cleanup's counts in one line (brain/planner_cleanup.py
    cleanup_line); "" without a cleanup section."""
    try:
        from planner_cleanup import cleanup_line as _line
        return _line(s)
    except Exception:  # noqa: BLE001  (a digest line never stops the digest)
        return ""


def traffic_line(s: dict) -> str:
    """(0.105.41) The traffic zones in one line (brain/planner_traffic.py
    traffic_line); "" without a traffic section."""
    try:
        from planner_traffic import traffic_line as _line
        return _line(s)
    except Exception:  # noqa: BLE001  (a digest line never stops the digest)
        return ""


def hauling_line(s: dict) -> str:
    """(0.105.40 M5) The hauling in one line (brain/planner_hauling.py
    hauling_line); "" without a hauling section."""
    try:
        from planner_hauling import hauling_line as _line
        return _line(s)
    except Exception:  # noqa: BLE001  (a digest line never stops the digest)
        return ""


def food_line(s: dict) -> str:
    """(0.105.40b, M6) The food store in one line (brain/planner_food.py
    food_line); "" without a food_store section."""
    try:
        from planner_food import food_line as _line
        return _line(s)
    except Exception:  # noqa: BLE001  (a digest line never stops the digest)
        return ""


def pile_links_line(s: dict) -> str:
    """(0.105.41, item 2) The wheelbarrows and the AI's feeder links in one
    line (brain/planner_piles.py pile_links_line); "" without the section."""
    try:
        from planner_piles import pile_links_line as _line
        return _line(s)
    except Exception:  # noqa: BLE001  (a digest line never stops the digest)
        return ""


def deep_hazard_line(s: dict) -> str:
    """(0.105.40b) Raw adamantine seen and the dig guard's refusals in one
    line (brain/planner_deep.py deep_hazard_line); "" without them."""
    try:
        from planner_deep import deep_hazard_line as _line
        return _line(s)
    except Exception:  # noqa: BLE001  (a digest line never stops the digest)
        return ""


def water_line(s: dict) -> str:
    """(0.105.38) The whole-map water survey in a line: the nearest flowing
    water (its distance and the dig's reach, or why none), how many bodies,
    the magma's kinds. "" when the survey has no whole-map list (older)."""
    w = _d(s.get("water"))
    waters = [b for b in _l(w.get("waters")) if isinstance(b, dict)]
    if not waters:
        return ""
    off = _d(s.get("map")).get("elevation_offset")
    off = off if isinstance(off, int) and not isinstance(off, bool) else 0
    flowing = sorted((b for b in waters if b.get("flow") == "flowing"),
                     key=lambda b: b.get("d") if isinstance(b.get("d"), int) else 10 ** 6)
    if flowing:
        b = flowing[0]
        reach = (f"reach {b['reach']}" if isinstance(b.get("reach"), int)
                 else "no safe dig" + (f" (opens {game_text(b.get('opens_cavern'), 20)})" if b.get("opens_cavern")
                                       else " (aquifer)" if b.get("aquifer") else ""))
        line = f"WATER nearest flowing: {b.get('kind')} {b.get('d')} tiles off, {reach}"
    else:
        line = "WATER nearest flowing: none on the map"
    line += f" | {len(waters)} bodies listed of {_n(w.get('waters_found')) or len(waters)}"
    mags = []
    for b in waters:
        if b.get("kind") != "magma":
            continue
        top = _d(b.get("top")).get("z")
        bit = str(b.get("magma") or "magma")
        if isinstance(top, int):
            bit += f" top {top + off}"
        if b.get("opens_cavern"):
            bit += f" (opens {game_text(b.get('opens_cavern'), 20)})"
        mags.append(bit)
    if mags:
        line += " | magma: " + ", ".join(mags[:4])
    return line


# (0.104.81) A magma furnace or forge does its plain twin's work: the rules
# that ask for a "Smelter" or a "MetalsmithsForge" count it too (13c: a fort
# with only a magma smelter never smelted). Once a report.
MAGMA_TWINS = {"MagmaSmelter": "Smelter", "MagmaKiln": "Kiln", "MagmaGlassFurnace": "GlassFurnace",
               "MagmaForge": "MetalsmithsForge"}


def _magma_aliases(s: dict) -> None:
    if s.get("_magma_aliased"):
        return
    b = s.get("buildings")
    if not isinstance(b, dict):
        return
    for group in ("furnaces", "workshops"):
        g = b.get(group)
        if not isinstance(g, dict):
            continue
        for magma, twin in MAGMA_TWINS.items():
            n = g.get(magma)
            if isinstance(n, int) and n > 0:
                g[twin] = int(g.get(twin) or 0) + n
    s["_magma_aliased"] = True


def project_text(pr: dict) -> str:
    """One line per open building project, e.g. '#3 bedrooms z65 dig 40/120'."""
    out = []
    for p in _l(_d(pr).get("open")):
        t = f"#{p.get('id')} {p.get('kind')} level{p.get('elevation', p.get('z'))} {p.get('phase')}"
        dig, fur = _d(p.get("dig")), _d(p.get("furnish"))
        if p.get("phase") == "dig" and dig:
            t += f" {dig.get('dug', 0)}/{dig.get('total', 0)}"
            if dig.get("stuck"):
                t += f" ({dig['stuck']} tiles no longer designated)"
        if p.get("phase") == "furnish" and fur:
            t += f" built {fur.get('done', 0)}/{fur.get('placed', 0)}"
            if _d(fur.get("waiting")):
                t += " waiting " + " ".join(f"{k}:{v}" for k, v in sorted(fur["waiting"].items()))
        out.append(t)
    return "; ".join(out)


def numbers(s: dict) -> dict[str, int]:
    """The flat set of numbers the diff compares."""
    # (0.105.26) a section that came back partial (a key missing) reads as 0, never raises
    dw, st, b, jobs = _d(s.get("dwarves")), _d(s.get("stocks")), _d(s.get("buildings")), _d(s.get("jobs"))
    o = _d(s.get("others_on_map"))
    stress = _d(dw.get("stress"))
    w = s.get("wealth")
    n = {
        "citizens": _n(dw.get("total")), "children": _n(dw.get("children")), "idle": _n(dw.get("idle_adults")),
        "soldiers": _n(dw.get("in_squads")), "need_care": _n(dw.get("needs_medical_care")),
        "unhappy": sum(_n(stress.get(k)) for k in UNHAPPY),
        "jobs": _n(jobs.get("total")), "suspended": _n(jobs.get("suspended")),
        "threats": len(_l(o.get("threats"))),
        "threats_can_reach": _n(o.get("threats_that_can_reach_dwarves")),
        "wealth_k": int(w) // 1000 if _num(w) else 0,
        "building": _n(b.get("under_construction")), "queued": _n(b.get("workshop_jobs_queued")),
    }
    for key, label in STOCK_ORDER:
        n[label] = _n(st.get(key))
    return n


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _n(v) -> int:
    return int(v) if _num(v) else 0


def _signed(v) -> str:
    return f"{int(v):+d}" if _num(v) else "?"


def _weather_line(s: dict) -> str:
    """(0.105.40b) brain/planner_weather.py's word on evil weather ("" if none or unreadable)."""
    try:
        from planner_weather import weather_line
        return weather_line(s)
    except Exception:  # noqa: BLE001
        return ""


def threat_line(s: dict) -> str:
    """(0.105.26) The threats the bridge tracks (lua/ai-threats.lua), only
    what is there now: "" when the fort is calm."""
    t = _d(s.get("threats"))
    if not t and not _d(s.get("weather")):                  # (fix41) the weather is its own section now
        return ""
    parts = []
    fire = _d(t.get("fire"))
    if _n(fire.get("fires")):
        parts.append(f"fire:{_n(fire['fires'])} tiles")
    u = _d(t.get("undead"))
    if _n(u.get("undead")):
        parts.append(f"undead:{_n(u['undead'])}")
    if _n(u.get("clouds")):
        parts.append(f"evil_clouds:{_n(u['clouds'])}" + (f" (nearest {u['cloud_near']} tiles)"
                                                          if _num(u.get("cloud_near")) else ""))
    if u.get("reanimating") and _n(u.get("surface_corpses")):
        parts.append(f"bodies_outside_that_may_rise:{_n(u['surface_corpses'])}")
    wl = _weather_line(s)                                    # (0.105.40b) evil weather
    if wl:
        parts.append(wl)
    th = _d(t.get("thieves"))
    if _n(th.get("now")):
        parts.append(f"thieves_on_map:{_n(th['now'])}")
    were = _d(t.get("were"))
    if _l(were.get("list")):
        parts.append(f"werebeast_citizens:{len(_l(were['list']))}")
    pr = _d(t.get("prisoners"))
    if _n(pr.get("caged")):
        parts.append(f"caged_prisoners:{_n(pr['caged'])}")
    sf = [x for x in _l(_d(t.get("surface")).get("list")) if isinstance(x, dict)]
    if sf:
        parts.append(f"surface_dangers:{len(sf)}")
    r = _d(t.get("rescue"))
    if _n(r.get("down")):
        parts.append(f"wounded_down:{_n(r['down'])} (rescuers {_n(r.get('holders'))})")
    return ("THREATS " + " ".join(parts)) if parts else ""


def world_line(s: dict) -> str:
    """(0.105.26) War, sieges and hostile visitors (lua/ai-diplomacy.lua
    world_report): "" when the fort is at peace with no siege on record."""
    w = _d(s.get("world"))
    if not w:
        return ""
    war = [c for c in _l(w.get("civs")) if isinstance(c, dict) and c.get("hostile")]
    sieges = [e for e in _l(w.get("sieges")) if isinstance(e, dict)]
    active = [e for e in sieges if e.get("active")]
    parts = []
    if war:
        parts.append("at war with " + ", ".join(
            f"{game_text(c.get('name'), 30)} ({game_text(c.get('race'), 12)})" for c in war[:4])
            + (f" +{len(war) - 4} more" if len(war) > 4 else ""))
    if active:
        parts.append("SIEGE NOW by " + ", ".join(game_text(e.get("name") or e.get("race"), 30) for e in active[:3]))
    if sieges:
        parts.append(f"sieges on record {sum(_n(e.get('n')) for e in sieges)}"
                     + (f" (last y{max(_n(e.get('last_year')) for e in sieges)})" if any(
                         _num(e.get("last_year")) for e in sieges) else ""))
    if _n(w.get("visitors_from_hostile")):
        parts.append(f"visitors from a civ at war on the map: {_n(w['visitors_from_hostile'])}")
    return ("WORLD " + " | ".join(parts)) if parts else ""


def infection_line(s: dict) -> str:
    """(0.105.26) Infected wounds (lua/ai-health.lua): "" when none."""
    inf = _d(s.get("infection"))
    n = _n(inf.get("infected"))
    if not n:
        return ""
    return (f"INFECTION {n} citizens with infected wounds, untreated {_n(inf.get('untreated'))}, "
            f"bleeding from it {_n(inf.get('bleeding'))}"
            + (", nobody can clean wounds" if inf.get("cleaners") == 0 else ""))


def _stage_word(name: str, v) -> str:
    """'hall walls' from a keep or hall status ({stage, ...}); "" when done or absent."""
    v = _d(v)
    st = v.get("stage")
    if not isinstance(st, str) or not st or st == "done":
        return ""
    key = {"clearing": "trees_left", "walls": "walls_planned", "roof": "roof_planned"}.get(st)
    left = _n(v.get(key)) if key else 0
    return f"{name} {st}" + (f" ({left} left)" if left else "")


def built_line(s: dict) -> str:
    """(0.105.30) "BUILT 40 walls, 35 floors (80% blocks), 75 above ground; 12 waiting",
    from the constructions survey, with the keep's, halls' and wings' stages.
    "" when the report has no survey (an older bridge) or nothing is built or planned."""
    c = _d(s.get("constructions"))
    if not c or "error" in c or c.get("missing"):       # (0.105.30 fixes) no list read: no data, not zeros
        return ""
    shape, item = _d(c.get("by_shape")), _d(c.get("by_item"))
    total = _n(c.get("total"))
    sur = c.get("surface")
    up = _n(_d(sur).get("total")) if isinstance(sur, dict) else _n(sur)
    waiting = _n(_d(c.get("planned")).get("n"))
    b = _d(s.get("buildings"))
    stages = [w for w in [_stage_word("keep", b.get("keep"))] if w]
    halls = b.get("halls")
    hall_list = _l(_d(halls).get("list")) if isinstance(halls, dict) and "list" in halls else (
        _l(halls) if isinstance(halls, list) else ([halls] if isinstance(halls, dict) and halls.get("stage") else []))
    for h in hall_list:
        w = _stage_word(str(_d(h).get("kind") or "hall").replace("_", " "), h)
        if w:
            stages.append(w)
    if not total and not waiting and not stages:
        return ""
    blocks = _n(item.get("blocks"))
    p = round(100 * blocks / total) if total else 0
    line = (f"BUILT {_n(shape.get('wall'))} walls, {_n(shape.get('floor'))} floors ({p}% blocks), "
            f"{up} above ground")
    if waiting:
        line += f"; {waiting} waiting"
    roofed = _n(c.get("roofed_surface_tiles"))
    if roofed:
        line += f" | roofed surface {roofed}"
    if stages:
        line += " | " + ", ".join(stages)
    return line


def gate_split_line(s: dict) -> str:
    """(0.105.32) A gate piece that reads open while DF's walk map is split
    at it (an entrance's `split`): who it shuts out. '' when there's none."""
    ent = _d(s.get("entrances"))
    off = _d(s.get("map")).get("elevation_offset")
    off = off if isinstance(off, int) else 0
    pieces = [pc for e in _l(ent.get("entrances")) if isinstance(e, dict)
              for pc in _l(e.get("split")) if isinstance(pc, dict)]
    if not pieces:
        return ""
    stuck = [r for r in _l(ent.get("stranded")) if isinstance(r, dict) and r.get("cause") == "gate_stuck"]
    parts = []
    for pc in pieces[:3]:
        z = pc.get("z")
        n = sum(1 for r in stuck if r.get("stuck_gate") == pc.get("id"))
        parts.append(f"{pc.get('kind') or 'gate'} #{pc.get('id')} x{pc.get('x')} y{pc.get('y')} elevation "
                     f"{z + off if isinstance(z, int) else '?'} (walk groups {pc.get('outside_group')} | "
                     f"{pc.get('inside_group')}, {n} shut out)")
    return "GATE_SPLIT open but the game holds it shut: " + "; ".join(parts)


def digest(s: dict, news: int = 5) -> str:
    s = normalize(s)
    d, dw, b, o = _d(s.get("date")), _d(s.get("dwarves")), _d(s.get("buildings")), _d(s.get("others_on_map"))
    n = numbers(s)
    stress = _d(dw.get("stress"))
    w = s.get("wealth")
    when = ("DATE unknown (the date couldn't be read)" if "date" in s["_errors"]
            else f"DATE {d.get('day', '?')} {d.get('month', '?')} y{d.get('year', '?')} {d.get('season', '?')}")
    lines = [
        f"{when}{' PAUSED' if s.get('paused') else ''}"
        f" | wealth {f'{int(w):,}' if _num(w) else '?'}",
        f"DWARVES {n['citizens']} ({n['children']} children) idle {n['idle']} soldiers {n['soldiers']}"
        f" need_care {n['need_care']}",
        "MOOD " + " ".join(f"{k}:{stress.get(k, 0)}" for k in
                           ("miserable", "very_unhappy", "unhappy", "fine", "content", "happy", "ecstatic")),
        "STOCK " + " ".join(f"{label}:{n[label]}" for _, label in STOCK_ORDER),
        f"WORKSHOPS {_top(b.get('workshops'), 8)}",
        f"FURNACES {_top(b.get('furnaces'), 4)} | stockpiles {b.get('stockpiles', 0)}"
        f" | queued {n['queued']} | under_construction {n['building']}",
        f"ZONES {_top(b.get('zones'), 8)}",
        "SUPPLIES " + " ".join(f"{k}:{v}" for k, v in _d(s.get("supplies")).items() if isinstance(v, int))
        + f" wells:{_d(b.get('other')).get('Well', 0)}",
        "MILITARY soldiers " + str(_d(s.get("military")).get("soldiers", 0)) + " | "
        + ("; ".join(f"{game_text(q.get('name'))} {q.get('members')}/{q.get('size')} {q.get('routine') or '?'}"
                     + (" ON ORDERS" if q.get("orders") else "")
                     for q in _l(_d(s.get("military")).get("squads"))[:5]) or "no squads")
        + f" | gate levers {len(_l(_d(s.get('military')).get('gates')))}"
        + (lambda g: f" | gear: {g.get('armed')}/{g.get('soldiers')} armed, {g.get('armored')} armoured,"
                     f" {g.get('squads_with_uniform')} squads with a uniform" if g.get("soldiers") else "")(
            _d(_d(s.get("military")).get("gear"))),
        "SOCIETY vacant offices: " + (", ".join(_l(_d(s.get("society")).get("vacant"))) or "none")
        + f" | starving {_d(s.get('society')).get('starving', 0)} parched {_d(s.get('society')).get('parched', 0)}"
        + f" | grazers without pasture {_d(s.get('society')).get('grazers_unpastured', 0)}",
        "DEAD " + " ".join(f"{k}:{v}" for k, v in _d(s.get("dead")).items() if isinstance(v, int)),
        f"JOBS {n['jobs']} suspended {n['suspended']} | top {_top(_d(s.get('jobs')).get('by_type'), 5)}",
        f"ON_MAP threats {n['threats']} (can reach dwarves: {n['threats_can_reach']}): "
        + ("; ".join(_threat_groups([t for t in _l(o.get('threats')) if isinstance(t, dict)])) or "none")
        + f" | visitors {o.get('visitors', 0)} merchants {o.get('merchants', 0)} diplomats {o.get('diplomats', 0)}"
        f" contained {o.get('contained_dangers', 0)}",
    ]

    for extra in (threat_line(s), world_line(s), infection_line(s), built_line(s), gate_split_line(s), water_line(s),
                  missions_line(s), perf_line(s), cleanup_line(s), hauling_line(s), food_line(s),
                  pile_links_line(s), deep_hazard_line(s), traffic_line(s)):
        if extra:
            lines.append(extra)
    m = _d(s.get("map"))
    if "map" in s["_errors"]:
        lines.append(f"MAP unknown: the map section failed ({game_text(s['_errors']['map'], 80)})")
    elif m:
        # levels as the game shows them (elevation), not DFHack's 0-based z
        off = m.get("elevation_offset") if isinstance(m.get("elevation_offset"), int) else 0
        lv = lambda z: z + off if isinstance(z, int) else z  # noqa: E731
        layers = " ".join(
            f"{l['name']}:{lv(l.get('z_top'))}..{lv(l.get('z_bottom'))}{'' if l.get('discovered') else '(undiscovered)'}"
            for l in _l(m.get("layers")) if isinstance(l, dict))
        dw_at = _d(m.get("dwarves"))
        lines.append(f"MAP levels: layers {layers or 'none'} | dwarves {lv(dw_at.get('z_bottom'))}..{lv(dw_at.get('z_top'))}"
                     f" {_top(dw_at.get('by_layer'), 4)}")
    for m in [x for x in _l(_d(s.get("moods")).get("list")) if isinstance(x, dict)][:4]:
        lines.append(f"MOOD_DWARF {game_text(m.get('name'), 60)}: {game_text(m.get('mood'), 20)}"
                     + (f" skill {m.get('skill')} workshop {m.get('workshop') or 'none yet'}"
                        f" items {m.get('items_have', '?')}/{m.get('items_needed', '?')}" if m.get("craft") else ""))
    if s.get("civ_alert"):
        lines.append("ALERT civilian alert is ON")
    st = _d(s.get("settings"))
    if st and "error" not in st:
        traits = _d(st.get("traits"))
        shown = " ".join(f"{k}:{_signed(v)}" for k, v in sorted(traits.items(), key=lambda kv: -abs(_n(kv[1]))))
        lines.append(f"PERSONALITY {shown or 'all balanced'} (scale -200..200)")
    mandates = [x for x in _l(s.get("mandates")) if isinstance(x, dict)]
    if mandates:
        lines.append("MANDATES " + "; ".join(
            f"{x.get('kind')} {x.get('remaining')}/{x.get('total')} {x.get('material') or ''} {x.get('item')}".replace("  ", " ")
            + f" ({x.get('days_left', '?')}d left)" for x in mandates[:6]))
    nobles = _l(s.get("nobles"))
    if nobles:
        lines.append("NOBLES " + " ".join(sorted({str(x.get("position")) for x in nobles if isinstance(x, dict)})))
    nd = _d(s.get("noble_demands"))
    if nd.get("capital") or _l(nd.get("land_holders")):
        # (0.105.41) the capital and the land holders
        lines.append("TITLES " + "; ".join(
            ([f"capital (monarch {nd.get('monarch')})"] if nd.get("capital") else [])
            + [f"{h.get('title')} {h.get('name')}" for h in _l(nd.get("land_holders")) if isinstance(h, dict)]))
    short = [f"{n.get('name')} {r.get('kind')} {r.get('value')}/{r.get('need')}"
             for n in _l(nd.get("nobles")) if isinstance(n, dict)
             for r in _l(n.get("rooms")) if isinstance(r, dict) and r.get("zone_id") is not None
             and int(r.get("value") or 0) < int(r.get("need") or 0)]
    if short:
        lines.append("NOBLE ROOMS UNDER VALUE " + "; ".join(short[:4]))
    pr = _d(s.get("projects"))
    lines.append("BUILDING " + (project_text(pr) or "no projects in progress")
                 + f" ({pr.get('finished', 0)} finished)")

    # The AI is an overseer: it sees patterns across the population, never
    # individual dwarves. Group by profession instead of naming anyone.
    units = [u for u in _l(s.get("units")) if isinstance(u, dict)]
    if units:
        sad = Counter(u.get("profession") or "?" for u in units if u.get("stress") in UNHAPPY)
        if sad:
            lines.append(f"UNHAPPY_BY_PROFESSION {_top(dict(sad), 6)}")
        idle = Counter(u.get("profession") or "?" for u in units
                       if not u.get("child") and not u.get("job") and not u.get("in_squad"))
        if idle:
            lines.append(f"IDLE_BY_PROFESSION {_top(dict(idle), 8)}")

    if s["_errors"]:
        lines.append("MISSING_SECTIONS " + " ".join(sorted(s["_errors"])))
    for a in _l(s.get("recent_announcements"))[-news:]:
        lines.append(f"NEWS {game_text(a.get('text'), 140)}")
    return "\n".join(lines)


def diff(old: dict, new: dict, min_change_pct: float = 2.0) -> str:
    """Only what changed since the last review. Small stock wobbles are ignored."""
    old, new = normalize(old), normalize(new)
    a, b = numbers(old), numbers(new)
    d = new["date"]
    lines = [f"SINCE_LAST_REVIEW now {d['day']} {d['month']} y{d['year']}"]
    changes = []
    for k, v in b.items():
        before = a.get(k, 0)
        if v == before:
            continue
        pct = abs(v - before) / max(abs(before), 1) * 100
        if pct >= min_change_pct or k in ("citizens", "threats", "threats_can_reach", "need_care",
                                           "unhappy", "soldiers"):
            changes.append(f"{k} {before}->{v}")
    lines.append("CHANGED " + (" ".join(changes) if changes else "nothing significant"))

    old_news = {x["text"] for x in _l(old.get("recent_announcements"))}
    for x in _l(new.get("recent_announcements")):
        if x["text"] not in old_news:
            lines.append(f"NEWS {game_text(x.get('text'), 140)}")
    old_threats = set(_threat_groups(_l(old["others_on_map"]["threats"])))
    new_threats = [t for t in _threat_groups(_l(new["others_on_map"]["threats"])) if t not in old_threats]
    if new_threats:
        lines.append("THREATS_NOW " + "; ".join(new_threats))
    return "\n".join(lines)


def _latest_snapshots(n: int) -> list[Path]:
    snaps = sorted((Path(os.environ.get("DFAI_LOG_DIR") or Path(__file__).resolve().parent.parent / "logs") / "snapshots").glob("state-*.json"))
    return snaps[-n:]


if __name__ == "__main__":
    args = sys.argv[1:]
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    older = None
    if "--diff" in args:
        i = args.index("--diff")
        older = Path(args[i + 1])
        del args[i:i + 2]
    path = Path(args[0]) if args else _latest_snapshots(1)[0]
    state = json.loads(path.read_text(encoding="utf-8"))
    if older:
        print(diff(json.loads(older.read_text(encoding="utf-8")), state))
    else:
        print(digest(state))
