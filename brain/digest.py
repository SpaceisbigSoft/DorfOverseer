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
    "projects": {"open": [], "decorating": [], "finished": 0, "max_open": 2},
    "stone_types": [],
    "stone_use": {},          # {usable, economic: {TOKEN: {n, ore, flux}}} (bridge 0.51)
    "locations": {"count": {}, "total": 0},
    "petitions": {},
    "alerts": {},
    "diplomacy": {},
    "meetings": {},
    "world": {},                  # (0.105.0) civs, war and peace, sieges, tribute, agreements, the meeting screen
    "ledger": {},                 # (0.104.0) the AI's ledger saved with the game
    "instruments": {},            # (0.104.7) a probe: the instruments the civ knows
    "supplies": {},
    "dead": {},
    "room_gaps": {},              # (0.104.20) rooms whose walls were dug open
    "planned": {},                # (0.104.154) buildings buildingplan waits on: what each lacks, why suspended
    "justice": {},                # (0.104.52) jail zones, restraints, punishments waiting
    "moods": {"list": []},
    "missions": {"controllers": [], "squads": [], "reports": {"n": 0, "unviewed": 0},   # (0.104.95, 13b)
                 "spoils": {"n": 0}, "sites": {}, "unknown": []},
    "hazards": {},
    "threats": {},                # (0.105.0) round 3: fire, prisoners, thieves, undead, werebeasts (lua/ai-threats.lua)
    "health": {},
    "waterworks": {"works": {}, "refused": {}},   # (0.105.0) moat, pumps, irrigation, magma workshops (lua/ai-waterworks.lua)
    "infection": {},              # (0.104.168) the infected: untreated, bleeding, beds free (lua/ai-health.lua)
    "military": {"squads": [], "soldiers": 0, "routines": [], "gates": []},
    "society": {},
    "entrances": {},
    "farms": {"plots": 0, "tiles": 0, "built": 0},
    "registry": [],          # every AI project with its bounds (lua/ai-builder.lua registry_report)
    "labor": {},
    "industry": {},
    "homes": {},             # (0.104.168) households: bedrooms, couples in one room or two, rough sleepers (lua/ai-homes.lua)
    "noble_rooms": {},       # {nobles: [{unit_id, name, office, needs}], free: {office, bedroom...}} (lua/ai-nobles.lua)
    "trade": {},             # {depot, caravans: [{civ, state}], goods, goods_value, at_depot} (lua/ai-trade.lua)          # {ores: {METAL: {tiles, ore}}} uncovered near the fort (lua/ai-industry.lua)             # {miners, picks, soldier_picks, dig, want, need, candidates} (lua/ai-labor.lua)
    "founding": {},          # {stairs: has the fort a staircase, near: the wagon or the dwarves}
}

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
            if key in REQUIRED and key not in errors:
                errors[key] = "missing from the report (older ai-bridge?)"
            s[key] = json.loads(json.dumps(default))
        elif isinstance(default, dict) and v == []:
            # DFHack's JSON writes an empty Lua table as [], not {}
            s[key] = json.loads(json.dumps(default))
        elif not isinstance(v, type(default)):
            errors[key] = f"unexpected type {type(v).__name__}"
            s[key] = json.loads(json.dumps(default))
    m = s.get("map")
    if isinstance(m, dict):
        for key in ("layers", "dwarves"):
            v = m.get(key)
            if isinstance(v, dict) and "error" in v and len(v) == 1:
                errors[f"map.{key}"] = v["error"]
                m[key] = [] if key == "layers" else {}
    s["_errors"] = errors
    _magma_aliases(s)
    return s


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
    dw, st, b = s["dwarves"], _d(s["stocks"]), s["buildings"]
    stress = _d(dw["stress"])
    n = {
        "citizens": dw["total"], "children": dw["children"], "idle": dw["idle_adults"],
        "soldiers": dw["in_squads"], "need_care": dw.get("needs_medical_care", 0),
        "unhappy": sum(stress.get(k, 0) for k in UNHAPPY),
        "jobs": s["jobs"]["total"], "suspended": s["jobs"]["suspended"],
        "threats": len(_l(s["others_on_map"]["threats"])),
        "threats_can_reach": s["others_on_map"].get("threats_that_can_reach_dwarves", 0),
        "wealth_k": int(s.get("wealth") or 0) // 1000,
        "building": b["under_construction"], "queued": b["workshop_jobs_queued"],
    }
    for key, label in STOCK_ORDER:
        n[label] = st.get(key, 0)
    return n


def digest(s: dict, news: int = 5) -> str:
    s = normalize(s)
    d, dw, b, o = s["date"], s["dwarves"], s["buildings"], s["others_on_map"]
    n = numbers(s)
    stress = _d(dw["stress"])
    lines = [
        f"DATE {d['day']} {d['month']} y{d['year']} {d['season']}{' PAUSED' if s['paused'] else ''}"
        f" | wealth {s['wealth']:,}",
        f"DWARVES {n['citizens']} ({n['children']} children) idle {n['idle']} soldiers {n['soldiers']}"
        f" need_care {n['need_care']}",
        "MOOD " + " ".join(f"{k}:{stress.get(k, 0)}" for k in
                           ("miserable", "very_unhappy", "unhappy", "fine", "content", "happy", "ecstatic")),
        "STOCK " + " ".join(f"{label}:{n[label]}" for _, label in STOCK_ORDER),
        f"WORKSHOPS {_top(b['workshops'], 8)}",
        f"FURNACES {_top(b['furnaces'], 4)} | stockpiles {b['stockpiles']}"
        f" | queued {n['queued']} | under_construction {n['building']}",
        f"ZONES {_top(b['zones'], 8)}",
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
        f"JOBS {n['jobs']} suspended {n['suspended']} | top {_top(s['jobs']['by_type'], 5)}",
        f"ON_MAP threats {n['threats']} (can reach dwarves: {n['threats_can_reach']}): "
        + ("; ".join(_threat_groups(_l(o['threats']))) or "none")
        + f" | visitors {o['visitors']} merchants {o['merchants']} diplomats {o['diplomats']}"
        f" contained {o.get('contained_dangers', 0)}",
    ]

    m = _d(s.get("map"))
    if m:
        # levels as the game shows them (elevation), not DFHack's 0-based z
        off = m.get("elevation_offset") if isinstance(m.get("elevation_offset"), int) else 0
        lv = lambda z: z + off if isinstance(z, int) else z  # noqa: E731
        layers = " ".join(
            f"{l['name']}:{lv(l.get('z_top'))}..{lv(l.get('z_bottom'))}{'' if l.get('discovered') else '(undiscovered)'}"
            for l in _l(m.get("layers")))
        dw_at = _d(m.get("dwarves"))
        lines.append(f"MAP levels: layers {layers or 'none'} | dwarves {lv(dw_at.get('z_bottom'))}..{lv(dw_at.get('z_top'))}"
                     f" {_top(dw_at.get('by_layer'), 4)}")
    for m in _l(_d(s.get("moods")).get("list"))[:4]:
        lines.append(f"MOOD_DWARF {game_text(m.get('name'), 60)}: {game_text(m.get('mood'), 20)}"
                     + (f" skill {m.get('skill')} workshop {m.get('workshop') or 'none yet'}"
                        f" items {m.get('items_have', '?')}/{m.get('items_needed', '?')}" if m.get("craft") else ""))
    if s.get("civ_alert"):
        lines.append("ALERT civilian alert is ON")
    st = _d(s.get("settings"))
    if st and "error" not in st:
        traits = _d(st.get("traits"))
        shown = " ".join(f"{k}:{v:+d}" for k, v in sorted(traits.items(), key=lambda kv: -abs(kv[1])))
        lines.append(f"PERSONALITY {shown or 'all balanced'} (scale -200..200)")
    mandates = _l(s.get("mandates"))
    if mandates:
        lines.append("MANDATES " + "; ".join(
            f"{x['kind']} {x['remaining']}/{x['total']} {x.get('material') or ''} {x['item']}".replace("  ", " ")
            + f" ({x['days_left']}d left)" for x in mandates[:6]))
    nobles = _l(s.get("nobles"))
    if nobles:
        lines.append("NOBLES " + " ".join(sorted({x["position"] for x in nobles})))
    pr = _d(s.get("projects"))
    lines.append("BUILDING " + (project_text(pr) or "no projects in progress")
                 + f" ({pr.get('finished', 0)} finished)")

    # The AI is an overseer: it sees patterns across the population, never
    # individual dwarves. Group by profession instead of naming anyone.
    units = _l(s.get("units"))
    if units:
        sad = Counter(u["profession"] for u in units if u.get("stress") in UNHAPPY)
        if sad:
            lines.append(f"UNHAPPY_BY_PROFESSION {_top(dict(sad), 6)}")
        idle = Counter(u["profession"] for u in units
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
