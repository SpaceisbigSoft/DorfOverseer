"""(F1a) Every action the bridge lets dry-run, dry-run in the game.

    python brain/selftest.py --dry-all [--port N]

The bridge's DRY_OK set (lua/ai-bridge-catalog.lua) names the actions whose
dry run changes nothing in the fort. Each one is sent here with dry_run true
and the arguments the planner sends it (the shapes of its rules' action
dicts, the ids taken from this fort's own report where it has them), so the
dry run walks the handler's real path. A clean refusal ("no site", "nothing
to do", a bad id) passes; Lua error text in the answer (a stack traceback,
"attempt to index", "file.lua:12:") fails, as does an action DRY_OK lists
that the bridge doesn't know or won't dry-run.

ARGS holds one argument builder per DRY_OK action: a new action added to
DRY_OK without one fails tests/test_f1a_dry_all.py.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "lua" / "ai-bridge-catalog.lua"

MISSING_ID = 999999      # an id no fort has: the handler's own refusal is the answer


# --- DRY_OK, read from the catalog ------------------------------------------

def dry_ok_actions(path: Path = CATALOG) -> list[str]:
    """The names in the catalog's DRY_OK list, in its order (comments left
    out): the block from `DRY_OK = {}` to `do DRY_OK[name] = true end`, and
    any `DRY_OK.name = true` / `DRY_OK['name'] = true` set later."""
    text = Path(path).read_text(encoding="utf-8")
    text = re.sub(r"--[^\n]*", "", text)
    out: list[str] = []
    m = re.search(r"DRY_OK\s*=\s*\{\s*\}\s*for\s+_\s*,\s*name\s+in\s+ipairs\s*\(\s*\{(.*?)\}\s*\)\s*do\s+DRY_OK\[name\]",
                  text, re.S)
    if m:
        out += re.findall(r"['\"]([A-Za-z_][A-Za-z_0-9]*)['\"]", m.group(1))
    for one in re.findall(r"DRY_OK(?:\.([A-Za-z_][A-Za-z_0-9]*)|\[['\"]([A-Za-z_][A-Za-z_0-9]*)['\"]\])\s*=\s*true", text):
        name = one[0] or one[1]
        if name not in out:
            out.append(name)
    seen: set[str] = set()
    return [n for n in out if not (n in seen or seen.add(n))]


def catalog_actions(path: Path = CATALOG) -> set[str]:
    """The names in the catalog's ACTIONS table: its entries stand at four
    spaces' indent (`name = act_name,` or `name = function(a)`, a few side
    by side on one line); the handlers' own lines are indented deeper."""
    text = Path(path).read_text(encoding="utf-8")
    i, j = text.find("\nACTIONS = {"), text.find("\nDRY_OK = {}")
    names: set[str] = set()
    for line in text[i:j].splitlines():
        line = re.sub(r"--.*", "", line)
        if re.match(r"    [A-Za-z_][A-Za-z_0-9]*\s*=[^=]", line):
            names.add(re.match(r"    ([A-Za-z_][A-Za-z_0-9]*)", line).group(1))
            names.update(re.findall(r",\s*([A-Za-z_][A-Za-z_0-9]*)\s*=\s*act_", line))
    return names


# --- Lua error text ---------------------------------------------------------

LUA_ERROR = re.compile(
    r"stack traceback"
    r"|attempt to (?:index|call|perform arithmetic|do arithmetic|compare|concatenate|get length)"
    r"|bad argument #\d"
    r"|\.lua:\d+:"
    r"|\(a nil value\)|\(a [a-z]+ value\)"
    r"|table index is (?:nil|NaN)"
    r"|C stack overflow|stack overflow"
    r"|Cannot (?:read|write) field"
    r"|unknown field \S+ in|invalid field"
    r"|in function <"
    r"|module '[^']+' not found"
    r"|unexpected symbol near",
    re.I)


def lua_error(reply) -> str | None:
    """The Lua error text in an answer (the reply as a dict, or the text of
    an error), or None. Looks through every string in it."""
    text = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False, default=str)
    m = LUA_ERROR.search(text or "")
    if not m:
        return None
    a = max(0, m.start() - 80)
    return re.sub(r"\s+", " ", text[a:m.end() + 120]).strip()


# --- what this fort's report offers the builders ----------------------------

from util import as_dict as _d  # noqa: E402  (util's helper)


from util import as_list as _l  # noqa: E402  (util's helper)


from util import int_or_none as _int  # noqa: E402  (util's helper)


def _first(*vals):
    """The first value that isn't None (an id of 0 is an id)."""
    return next((v for v in vals if v is not None), None)


def _walk_int(v, keys: tuple, depth: int = 0, limit: int = 7):
    """The first whole number under one of `keys` anywhere in v (breadth first)."""
    level = [v]
    for _ in range(limit):
        nxt = []
        for x in level:
            if isinstance(x, dict):
                for k in keys:
                    n = _int(x.get(k))
                    if n is not None:
                        return n
                nxt += [y for y in x.values() if isinstance(y, (dict, list))]
            elif isinstance(x, list):
                nxt += [y for y in x[:200] if isinstance(y, (dict, list))]
        if not nxt:
            return None
        level = nxt
    return None


class Fort:
    """Ids and places from a fort report, each falling back to MISSING_ID (or
    a plain spot) when the report hasn't one: the handler refuses then."""

    def __init__(self, state: dict | None):
        s = self.s = state if isinstance(state, dict) else {}
        mil = _d(s.get("military"))
        squads = [q for q in _l(mil.get("squads")) if isinstance(q, dict) and _int(q.get("id")) is not None]
        self.squads = [q["id"] for q in squads][:3] or [MISSING_ID]
        self.squad = self.squads[0]
        ents = [e for e in _l(_d(s.get("entrances")).get("entrances")) if isinstance(e, dict)]
        e0 = next((e for e in ents if _int(e.get("id")) is not None), {})
        self.entrance = _int(e0.get("id")) if e0 else None
        if self.entrance is None:
            self.entrance = MISSING_ID
        spot = next((e for e in ents if all(_int(e.get(k)) is not None for k in "xyz")), None)
        if spot is None:
            spot = self._first_xyz(s) or {"x": 1, "y": 1, "z": 1}
        self.xyz = {k: spot[k] for k in "xyz"}
        self.opening = f"{self.xyz['x']},{self.xyz['y']},{self.xyz['z']}"
        gates = [g for g in _l(mil.get("gates")) if isinstance(g, dict) and _int(g.get("id")) is not None]
        self.lever = gates[0]["id"] if gates else MISSING_ID
        reg = [p for p in _l(s.get("registry")) if isinstance(p, dict) and _int(p.get("id")) is not None]
        opn = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict) and _int(p.get("id")) is not None]
        self.project = (opn or reg or [{"id": MISSING_ID}])[0]["id"]
        locs = [x for x in _l(_d(s.get("locations")).get("list")) if isinstance(x, dict) and _int(x.get("id")) is not None]
        self.location = locs[0]["id"] if locs else MISSING_ID
        self.locations = [x["id"] for x in locs][:3] or [MISSING_ID]
        zone = None
        for x in locs:
            zs = [z for z in _l(x.get("zones")) if _int(z) is not None]
            if zs:
                zone = zs[0]
                break
        if zone is None:
            zone = _walk_int({k: s.get(k) for k in ("noble_rooms", "health", "locations", "society")}, ("zone_id",))
        if zone is None:
            bk = [b for b in _l(mil.get("barracks")) if isinstance(b, dict) and _int(b.get("id")) is not None]
            zone = bk[0]["id"] if bk else MISSING_ID
        self.zone = zone
        hosp = [h for h in _l(_d(s.get("health")).get("hospital")) if isinstance(h, dict)]
        self.hospital = next((_int(h.get("id")) for h in hosp if _int(h.get("id")) is not None), self.location)
        hz = _walk_int([h.get("zones") for h in hosp], ("id",)) if hosp else None
        self.hospital_zone = _first(hz, _walk_int(hosp, ("zone_id",)), self.zone)
        units = [u for u in _l(s.get("units")) if isinstance(u, dict) and _int(u.get("id")) is not None]
        unit = units[0]["id"] if units else _walk_int(s, ("unit_id",))
        if unit is None:
            unit = _first(_walk_int(_d(s.get("needs")).get("stressed"), ("id",)),
                          _walk_int(_d(s.get("health")).get("patients"), ("id",)))
        self.unit = unit if unit is not None else MISSING_ID
        self.units = [u["id"] for u in units][:3] or [self.unit]
        shops = _walk_int({"d": _d(s.get("order_desk")).get("workshops"), "s": s.get("shops")}, ("shop_id", "id"))
        self.building = _first(shops, _walk_int(s, ("shop_id", "workshop_id", "building_id")), MISSING_ID)
        self.pile = _first(_walk_int(s, ("pile_id",)), MISSING_ID)
        self.item = _first(_walk_int(s, ("item_id",)), MISSING_ID)
        self.landmark = _first(_walk_int(s, ("landmark_id",)), MISSING_ID)
        self.site = _first(_walk_int({"d": s.get("diplomacy"), "w": s.get("world")}, ("site_id",)), MISSING_ID)
        self.entity = _first(_walk_int({"t": s.get("trade"), "o": s.get("others_on_map")}, ("entity", "civ_id")),
                             _walk_int(_d(s.get("diplomacy")).get("civs"), ("id",)), MISSING_ID)
        others = [u for u in _l(_d(s.get("others_on_map")).get("list")) if isinstance(u, dict)]
        self.target = next((_int(u.get("id")) for u in others if _int(u.get("id")) is not None), MISSING_ID)
        self.z = self.xyz["z"]
        self.ledger = {k: v for k, v in _d(s.get("ledger")).items() if k != "error"}

    @staticmethod
    def _first_xyz(s: dict) -> dict | None:
        level = [s]
        for _ in range(6):
            nxt = []
            for x in level:
                if isinstance(x, dict):
                    if all(_int(x.get(k)) is not None for k in "xyz"):
                        return x
                    nxt += [y for y in x.values() if isinstance(y, (dict, list))]
                elif isinstance(x, list):
                    nxt += [y for y in x[:100] if isinstance(y, (dict, list))]
            level = nxt
        return None


# --- the planner's own helpers (their shapes are the planner's) -------------

def _cfg() -> dict:
    from planner_config import PLANNER_CONFIG
    return PLANNER_CONFIG


def _safe(fn: Callable[[], dict], fallback: dict) -> dict:
    """A planner helper's answer, or the fallback when a thin report (no
    settings, no threats read) trips it: the shape is the same."""
    try:
        got = fn()
        return got if isinstance(got, dict) and got else fallback
    except Exception:  # noqa: BLE001
        return fallback


def _herd_targets(f: Fort) -> dict:
    from planner_husbandry import herd_targets_for
    return herd_targets_for({}, _cfg())


def _court(f: Fort) -> dict:
    from planner_garden import court_opts
    o = dict(_safe(lambda: court_opts(f.s, {}, _cfg(), None), {"paths": False, "statues": 2}))
    if not isinstance(o.get("name"), str):
        o.pop("name", None)
    return o


def _hall(f: Fort) -> dict:
    from planner_construct import hall_opts
    return hall_opts({}, _cfg())


def _far(f: Fort) -> dict:
    from planner_water import far_args
    return far_args(_cfg())


def _alert_ages(f: Fort) -> dict:
    from planner_military_threats import alert_ages
    return _safe(lambda: alert_ages(f.s, _cfg(), "quiet"), {"default": int(_cfg()["alert_keep_days"]) * 1200})


def _petitions(f: Fort) -> dict:
    try:
        from planner_visitors import petition_orders_wanted
        o = petition_orders_wanted(f.s, _cfg())
        if isinstance(o, dict) and o:
            return o
    except Exception:  # noqa: BLE001  (a thin report: the planner's kinds, asked about)
        pass
    return {"performer": 1, "scholar": 1}


def _trade_wants(f: Fort) -> list:
    fb = _cfg().get("h5_trade_fallback_wants") or {"DRINK": 20}
    return [{"key": k, "count": int(n)} for k, n in fb.items() if int(n) > 0][:4]


def _crops(f: Fort) -> dict:
    crops = [k for k, v in _d(_d(f.s.get("farms")).get("crops")).items() if isinstance(v, dict)]
    cfg = _cfg()
    return {k: cfg["crop_brew_threshold"] for k in crops[:3]} or {"MUSHROOM_HELMET_PLUMP": cfg["crop_brew_threshold"]}


def _blueprint(f: Fort) -> dict:
    from planner_design import landmark_cap, library
    lib = library()
    kind = sorted(lib)[0] if lib else "statue_garden"
    bp = lib.get(kind) if lib else {}
    return {"bp": bp if isinstance(bp, dict) else {}, "site": "S1", "name": "The Landmark", "purpose": kind,
            "cap": landmark_cap(int(_d(f.s.get("dwarves")).get("total") or 20), 0), "by": "library"}


def _standing(f: Fort, name: str) -> str:
    st = _d(_d(f.s.get("dead")).get("standing"))
    return next((k for k in (name, "standing_orders_" + name) if k in st), name)


# --- one argument builder per DRY_OK action ---------------------------------
# Each takes the Fort and gives the action's arguments (no "type", no
# "dry_run"): a dict, or a list of dicts for the planner's different calls.

Builder = Callable[[Fort], "dict | list[dict]"]
c = _cfg  # (short: the planner's config, read when a builder runs)

ARGS: dict[str, Builder] = {
    # projects and building
    "start_project": lambda f: [
        {"kind": "bedrooms", "rooms": 4, "room_size": 3},
        {"kind": "workshops", "shops": ["Craftsdwarfs"], "urgent": True},
        {"kind": "storage", "piles": ["food"], "room_size": 7},
        {"kind": "dining", "tables": 10},
        {"kind": "hospital", "beds": 4},
        {"kind": "tombs", "coffins": 6},
        {"kind": "jail", "cells": 2},
        {"kind": "temple", "size": "shrine"},
        {"kind": "tavern", "tables": 4},
        {"kind": "barracks", "beds": 20},
        {"kind": "archery", "lanes": 3, "length": 12},
        {"kind": "library", "bookcases": 6},
    ],
    "farm_plots": lambda f: {"tiles": 20, "dig": False, "outside": True},
    "place_well": lambda f: {"inside_only": True},
    "make_pasture": lambda f: {"tiles": 40},
    "link_lever": lambda f: {"lever_id": f.lever, "target_id": f.building},
    "save_game": lambda f: {},
    "quiet_announcements": lambda f: {},
    "found_fort": lambda f: {"wide": True},
    "assign_labor": lambda f: [{"job": "mining", "count": 3}, {"job": "DIAGNOSE", "count": 1, "min_skill": 3}],
    "gather_plants": lambda f: {"count": 3},
    "trim_gathering": lambda f: {"keep": int(c()["gather_jobs_keep"])},
    "appoint": lambda f: [{"office": "MANAGER"}, {"office": "MESSENGER", "interim": True},
                          {"office": "MILITIA_CAPTAIN", "replace_stale": True}],
    "place_surface": lambda f: [{"kind": "refuse"}, {"kind": "depot"}, {"kind": "dump"}, {"kind": "cages"}],
    "place_keep": lambda f: {},
    "deep_depot": lambda f: {},
    "make_squad": lambda f: {},
    "mine_ore": lambda f: [{"metal": "IRON", "count": 40, "prospect": True}, {"metal": "GEM"}],
    "explore_dig": lambda f: {"count": 3, "tunnels": 2},
    "clear_gate": lambda f: {**f.xyz, "spot": "gate"},
    "bring_goods": lambda f: {"count": 10},
    "unload_depot": lambda f: {"max": int(c()["unload_depot_max"])},
    "kitchen_skill": lambda f: [{"min_level": 3}, {"min_level": 0}],
    "place_slabs": lambda f: {"max": 5},
    "give_room": lambda f: {"unit_id": f.unit, "kind": "bedroom"},
    "set_uniform": lambda f: [{"squad_id": f.squad, "kind": "leather"}, {"squad_id": f.squad, "kind": "metal", "ranged": True}],
    "adopt_uniform": lambda f: {"squad_id": f.squad},
    "petition_orders": lambda f: {"orders": _petitions(f)},
    "set_uniform_weapon": lambda f: {"squad_id": f.squad, "weapon": "ITEM_WEAPON_CROSSBOW"},
    "allow_stone": lambda f: [{"stone": "GRANITE", "keep": True}, {"stone": "HEMATITE", "ore": True}],
    "prioritize_dig": lambda f: {"project_id": f.project, "priority": 2},
    "renew_well_dig": lambda f: {"project_id": f.project, "priority": 3},
    "redig_projects": lambda f: {},
    "convict": lambda f: {"max": 1, "unit_id": f.unit, "disorderly": True},
    "quarry": lambda f: {"count": 30},
    "polish": lambda f: {},
    "trade_deal": lambda f: {"wants": _trade_wants(f), "margin": 1.2, "press": True, "close": True},
    "call_trader": lambda f: {"wait_ticks": int(c()["trade_anyone_after_ticks"])},
    "open_trade": lambda f: {},
    "close_trade": lambda f: [{}, {"unloading": True}],
    "squad_barracks": lambda f: {"squad_id": f.squad, "zone_id": f.zone},
    "feeder_pile": lambda f: {"building_id": f.building},
    "idle_crafting": lambda f: {},
    "give_trinkets": lambda f: {"max": 5},
    "staff_location": lambda f: {"location_id": f.location, "post": "TAVERN_KEEPER"},
    "vacate_post": lambda f: {"location_id": f.hospital, "unit_id": f.unit},
    "add_posts": lambda f: {"location_id": f.location, "posts": ["SCHOLAR"]},
    "staff_labors": lambda f: {"location_id": f.hospital},
    "dismiss_alerts": lambda f: {"ages": _alert_ages(f), "max": int(c()["alerts_per_cycle"])},
    "place_in_zone": lambda f: [{"zone_id": f.zone, "what": "chest"}, {"zone_id": f.hospital_zone, "what": "traction_bench"},
                                {"zone_id": f.hospital_zone, "what": "bed"}],
    "answer_petition": lambda f: [{"id": MISSING_ID, "accept": True, "wish": "None|None|None|None"},
                                  {"ids": [MISSING_ID], "accept": False, "citizenship": True}],
    "retarget_hall": lambda f: {"project_id": f.project},
    "remove_workshops": lambda f: {"kind": "Craftsdwarfs", "keep": 1, "max": 20},
    "survey_water": lambda f: {},
    "cistern_step": lambda f: [{}, {"prefs": {"freezes": True, "cavern_danger": False}}, {"shut": True}, {"relink": True},
                               {"retire": True, "why": "stuck at its dig step for 9 days"}],
    "water_zone": lambda f: {"points": [dict(f.xyz)]},
    "sand_zone": lambda f: {},
    "water_work": lambda f: [{"kind": "moat", **_far(f)}, {"kind": "pump", **_far(f)}, {"kind": "irrigation", **_far(f)},
                             {"kind": "power", "source": "windmill", **_far(f)},
                             {"kind": "magma", "shop": "Smelter", "shut": True, "why": "spilt magma near it"}],
    "set_farm_crops": lambda f: [{"drink": True}, {"thread": True, "drink": False}, {"variety": True, "drink": False}],
    "kitchen_brewables": lambda f: {"ban": True},
    "farm_thresholds": lambda f: {"thresholds": _crops(f), "steer": "drink"},
    "unstick_uniforms": lambda f: {},
    "set_rules": lambda f: {"rules": {"design": "guided"}},
    # (0.105.26) the second list
    "accept_cups": lambda f: {},
    "add_doctor_post": lambda f: {"location_id": f.hospital},
    "allow_burial": lambda f: {},
    "answer_meeting": lambda f: [{}, {"tribute": "small"}],
    "apply_preset": lambda f: {"name": "Monastery"},
    "approve_orders": lambda f: {},
    "assign_kit": lambda f: {"limit": 20},
    "assign_quivers": lambda f: {"limit": 10},
    "assign_weapons": lambda f: {"limit": 10},
    "bench_jobs": lambda f: [{"kind": "coffin", "count": 3, "material": "stone"}, {"kind": "slab", "count": 2, "make_room": True}],
    "bootstrap_chair": lambda f: {},
    "break_fights": lambda f: {},
    "fight_watch": lambda f: {"on": True, "end_tantrums": False},
    "build_crossing": lambda f: {**f.xyz, "dir": "north", "len": 5, "width": 1, "kind": "cheap"},
    "build_gatehouse": lambda f: [{"entrance_id": f.entrance, "kind": "cage", "count": 0},
                                  {"entrance_id": f.entrance, "kind": "weapon", "count": 2}],
    "calm_burrow": lambda f: {"max": int(c()["calm_burrow_max"]), "days": int(c()["calm_burrow_days"])},
    "clear_orphan_jobs": lambda f: {},
    "clear_webs": lambda f: {},
    "close_meeting": lambda f: {},
    "cut_entrance": lambda f: {"entrance_id": f.entrance},
    "dig_stairwell": lambda f: {"dir": "north", "elev_lo": 100, "elev_hi": 120, "district": None},
    "fire_guard": lambda f: {"radius": int(c().get("fire_guard_radius", 6)), "max_jobs": int(c().get("fire_guard_jobs", 40))},
    "fix_gear_gaps": lambda f: {"shields": True},
    "free_slabs": lambda f: {},
    "free_stray_gear": lambda f: {"limit": 100},
    "gate_dogs": lambda f: {**f.xyz, "max": 2},
    "guard_gate": lambda f: {**f.xyz, "squads": f.squads[:2]},
    "hospital_burrow": lambda f: {"max": int(c()["hospital_burrow_max"]), "per": int(c()["hospital_burrow_per"]),
                                  "days": int(c()["hospital_burrow_days"])},
    "house_dwarves": lambda f: {"house": 0, "upgrade": 2},
    "furnish_liked": lambda f: {"n": 2},
    "join_levels": lambda f: {},
    "keep_mousers": lambda f: {"count": 4},
    "kitchen_fat": lambda f: {"ban": True},
    "kitchen_drinks": lambda f: {"ban": True},
    "kitchen_cheap": lambda f: {"ban": True, "min_value": 3, "keep": 10},
    "seed_reserve": lambda f: {"target": 20},
    "ledger_set": lambda f: {"values": f.ledger},
    "location_access": lambda f: [{"ids": f.locations, "visitors": True}, {"ids": f.locations, "visitors": False}],
    "mark_run": lambda f: {"run_id": "selftest-dry"},
    "mood_free_items": lambda f: {"unit_id": f.unit, "max": 10},
    "moon_cell": lambda f: [{"ids": [], "release": True, "all": True}, {"ids": f.units[:1]}],
    "nest_boxes": lambda f: {"max": 3},
    "order_instrument": lambda f: {"amount": 2},
    "order_slots": lambda f: {"workshop_id": f.building, "max": 10},
    "pair_chairs": lambda f: {"zones": [f.zone], "max": 5},
    "place_gate_lever": lambda f: {"entrance_id": f.entrance},
    "prisoner_room": lambda f: {},
    "prune_remains": lambda f: [{}, {"keep": ["usable-parts"]}],
    "quick_location": lambda f: [{"kind": "tavern"}, {"kind": "temple"}],
    "recreation": lambda f: [{"max": 1, "days": int(c()["recreation_days"])},
                             {"release": True, "max": 1, "days": int(c()["recreation_days"])}],
    "remove_crossing": lambda f: {"index": 1},
    "remove_webs": lambda f: {"max": int(c()["remove_webs_max"])},
    "repair_rooms": lambda f: {},
    "rest_infected": lambda f: {"max": 2, "cap": int(c()["infected_rest_cap"]), "keep_free": int(c()["infected_rest_keep_free"])},
    "bed_rest": lambda f: {"max": 1, "cap": 4, "keep_free": 1, "rediag": True},
    "restrict_water": lambda f: {"levels": [f.z], "x": f.xyz["x"], "y": f.xyz["y"], "radius": 60},
    "scrub_dead_units": lambda f: {},
    "seal_cavern": lambda f: [{"layer": "all caverns", "open": True}, {"layer": "all caverns", "openings": True},
                              {"layer": "Cavern1", "tiles": [dict(f.xyz)]}],
    "seal_well_stairs": lambda f: {},
    "send_mission": lambda f: [{"goal": "make_contact", "site_id": f.site},
                               {"goal": "raid", "site_id": f.site, "squad_ids": f.squads[:1]}],
    "shelter_squads": lambda f: [{"squads": f.squads[:2]}, {"squads": f.squads[:2], "station": dict(f.xyz)}],
    "slaughter_one": lambda f: {"oldest": True, "mood": True},
    "squad_bolts": lambda f: {"squad_id": f.squad},
    "assign_bolts": lambda f: {"limit": 5},
    "split_bolts": lambda f: {"squad_id": f.squad, "reserve": 50},
    "squad_release": lambda f: {"unit_id": f.unit, "mother": True},
    "squad_swap": lambda f: {"unit_id": f.unit, "avoid": []},
    "squad_trim": lambda f: {"count": 1},
    "sync_offices": lambda f: {},
    "traction_rest": lambda f: {"max": 1},
    "train_war": lambda f: {"max": 2},
    "trim_instrument_orders": lambda f: {"keep": 1},
    "trim_labor": lambda f: {"job": "fishing", "keep": 2},
    "unforbid_dead": lambda f: {"max": 20},
    "unsuspend_orders": lambda f: {},
    "well_shaft": lambda f: [{"close": False}, {"close": True}],
    "refresh_shelter": lambda f: {},
    "weather_burrow": lambda f: [{"on": True}, {"on": False}],
    "polish_room": lambda f: {"zone_id": f.zone},
    # disposal
    "unforbid_items": lambda f: {"reasons": ["used_ammo"], "max": 50},
    "mark_melt": lambda f: {"max": 50, "keep_masterwork": True, "keep_enemy_gear": False},
    "mark_dump": lambda f: {"bodies": True, "junk": False, "reasons": ["free", "other_dead"], "max": 50},
    "empty_dump": lambda f: {"max": 50},
    "set_standing_orders": lambda f: {"orders": {_standing(f, "gather_refuse_outside"): 0}},
    "place_dump": lambda f: [{"inside": False, "move": True}, {"inside": True}],
    # construction
    "place_hall": lambda f: {"kind": "dining", **_hall(f)},
    "build_wings": lambda f: {"entrance_id": f.entrance},
    "floor_rooms": lambda f: {"project_id": f.project},
    "open_entrance": lambda f: {"id": f.entrance},
    "close_threatened_gates": lambda f: {},
    "free_gate_jobs": lambda f: {"entrance_id": f.entrance},
    "unstick_gate": lambda f: {"id": f.entrance, "step": 1},
    "dig_way_in": lambda f: {**f.xyz, "cave_in": True},
    "unmark_project_dig": lambda f: {"project_id": f.project},
    "build_blueprint": _blueprint,
    "landmark_step": lambda f: {"landmark_id": f.landmark},
    # world cleanup
    "cleanup_items": lambda f: {"max": 50,
                                "min_age": int(c()["cleanup_items_age_ticks"]), "level": "safe"},
    "cleanup_units": lambda f: {"max": int(c()["cleanup_units_batch"]), "min_age": int(c()["cleanup_units_age_ticks"])},
    "cleanup_spatter": lambda f: {"scope": "outside", "budget_ms": int(c()["cleanup_spatter_budget_ms"])},
    "cleanup_dead_units": lambda f: {"min_age": int(c()["cleanup_dead_age_ticks"])},
    "insane_guard": lambda f: [{}, {"units": f.units[:1]}],
    "insane_water": lambda f: {"units": f.units[:1]},
    "killer_cell": lambda f: {"units": f.units[:1]},
    "shelter_pick": lambda f: [{"levels": [f.z], "why": f"level {f.z}: the self-test's pick"}, {"clear": True}],
    "squad_station": lambda f: {"squad_id": f.squad, **f.xyz, "what": "the self-test's spot"},
    "stuck_reset": lambda f: [{"kind": "lever", "id": f.lever, "mode": "reissue"}, {"kind": "lever", "id": f.lever, "mode": "drop"}],
    "build_lure": lambda f: {"opening": f.opening},
    "lure_open": lambda f: {"opening": f.opening},
    "lure_shut": lambda f: {"opening": f.opening},
    "cavern_way": lambda f: [{"step": "build"}, {"step": "open", "why": "a job"}, {"step": "shut", "shut": True, "why": "a danger"}],
    "add_haulers": lambda f: {"count": 2},
    "relieve_haulers": lambda f: [{"count": 2}, {"count": 2, "back": True}, {"count": 1, "cooks": [], "back": True}],
    "food_pile": lambda f: {"building_id": f.building, "tiles": 20, "barrels": 5, "reach": 30, "more": True},
    "food_barrels": lambda f: {"pile_id": f.pile, "barrels": 5},
    "pile_barrows": lambda f: {"pile_id": f.pile, "barrows": 1},
    "feeder_link": lambda f: [{"pile_id": f.pile}, {"pile_id": f.pile, "unlink": True}],
    "paint_traffic": lambda f: {"max": int(c()["traffic_slice_tiles"]), "budget_ms": int(c()["traffic_budget_ms"])},
    # provisions
    "hunters": lambda f: {"count": 2},
    "food_standing": lambda f: {"orders": {"auto_butcher": 1}},
    "fruit_zone": lambda f: {"min_trees": int(c()["fruit_stand_min"])},
    "cavern_farm": lambda f: {"at": dict(f.xyz), "tiles": 20},
    # siege works
    "fortify_post": lambda f: {"entrance_id": f.entrance, "max": 4},
    "archer_post": lambda f: {"entrance_id": f.entrance, "squads": f.squads[:2]},
    "place_siege_engine": lambda f: {"entrance_id": f.entrance, "kind": "ballista"},
    "place_siege_shop": lambda f: {"entrance_id": f.entrance},
    "place_mood_shop": lambda f: [{"kind": "Craftsdwarfs"}, {"kind": "Smelter"}],
    "make_pit": lambda f: {"min_drop": 3},
    "pit_prisoners": lambda f: {"ids": f.units[:1], "max": 2, "min_drop": 3},
    "magma_guard": lambda f: {"radius": 3, "max_jobs": 40},
    "magma_reclaim": lambda f: {"cool_ticks": 3600, "dig": True},
    "cavern_logging": lambda f: [{"stop": True, "unsafe_only": True}, {}],
    "keep_grove": lambda f: {"guard": True},
    "bench_caps": lambda f: [{"kind": "Carpenters", "level": int(c()["bench_training_max_level"])},
                             {"kind": "Carpenters", "release": True}],
    "clean_contaminants": lambda f: {},
    "quarantine_syndromes": lambda f: {"days": int(c().get("syndrome_quarantine_days", 7)), "max": int(c().get("syndrome_quarantine_max", 20))},
    "clear_miasma": lambda f: {"max": int(c().get("miasma_clear_max", 50))},
    "place_display": lambda f: {"zone_id": f.zone, "kind": "pedestal"},
    "display_artifact": lambda f: {"item_id": f.item, "building_id": f.building},
    "hunt_send": lambda f: {"squad_ids": f.squads[:1], "target_id": f.target},
    "hunt_recall": lambda f: {"squad_ids": f.squads[:1], "reason": "the self-test"},
    "build_killzone": lambda f: [{"entrance_id": f.entrance, "drawbridge": True},
                                 {"entrance_id": f.entrance, "traps": 4, "kind": "cage", "drawbridge": False}],
    "reset_cage_traps": lambda f: {"entrance_id": f.entrance},
    "thirst_unforbid": lambda f: {"unit_id": f.unit, "max": 5},
    "forbid_secrets": lambda f: {"ids": [f.item], "on": True},
    "thirst_way": lambda f: {"unit_id": f.unit, "max_dig": 30},
    "thirst_patient": lambda f: {"unit_id": f.unit, "get_up": True},
    "thirst_probe": lambda f: {"unit_id": f.unit},
    "call_migrants": lambda f: {},
    "clear_caravan_goods": lambda f: {"entity": f.entity, "max": 200},
    "free_caravan": lambda f: [{"entity": f.entity}, {"entity": f.entity, "step": "edge"}, {"entity": f.entity, "step": "dismiss"}],
    "mood_shelter": lambda f: {},
    "hospital_release": lambda f: [{"kind": "plant"}, {"restore": True}],
    "hospital_cap": lambda f: {"caps": [{"id": f.hospital, "thread": 5, "cloth": 5}]},
    "open_meeting": lambda f: {},
    "close_world": lambda f: {},
    "hospital_guard": lambda f: [{"squad_id": f.squad, "zone_id": f.hospital_zone}, {"squad_id": f.squad, "release": True}],
    "tantrum_step_down": lambda f: {"unit_id": f.unit, "medical": True},
    "training_squad": lambda f: [{"mode": "make"}, {"mode": "fill", "squad_id": f.squad, "count": 1},
                                 {"mode": "forget", "squad_id": f.squad}],
    "coffins_anywhere": lambda f: {"max": 3},
    "engrave_memorials": lambda f: {"max": 3, "ghosts": True},
    "train_cook": lambda f: [{}, {"release": True}],
    "prune_memorial_orders": lambda f: {},
    "entomb_dead": lambda f: {"max": 3},
    "well_safety": lambda f: {},
    "well_rescue": lambda f: {**f.xyz, "project_id": f.project},
    "near_gates": lambda f: [{"on": True, "radius": 20}, {"on": False}],
    "retire_water_zones": lambda f: {"outside_only": True},
    "cross_cavern": lambda f: {"x": f.xyz["x"], "y": f.xyz["y"], "elev": 50, "layer": "Cavern1"},
    "herd_breeders": lambda f: [{"females": 3}, {"females": 0}],
    "tame_wild": lambda f: [{"max": 2}, {"max": 2, "predators": True}],
    "train_hunt": lambda f: {"max": 2},
    "herd_targets": _herd_targets,
    "place_garden_court": _court,
    "garden_court_meeting": lambda f: [{"on": False, "lock": True}, {"on": True}],
    "mission_way": lambda f: {"id": f.entrance, "mission": "selftest"},
    "mission_pets": lambda f: [{"op": "restore"}, {"op": "release", "pet_ids": f.units[:1]}],
    "way_out_open": lambda f: {"id": f.entrance},
    "way_out_leave": lambda f: {},
    "park_project": lambda f: {"project_id": f.project, "sig": "selftest"},
    "social_places": lambda f: {"taverns": 3, "temples": 5},
    "were_cells": lambda f: {},
}


def build_actions(name: str, fort: Fort) -> list[dict]:
    """The dry-run actions for one action type: its builder's argument sets,
    each with "type" and "dry_run": true. KeyError when it has no builder."""
    got = ARGS[name](fort)
    sets = got if isinstance(got, list) else [got]
    out = []
    for args in sets:
        a = {"type": name, **{k: v for k, v in dict(args).items() if v is not None}}
        a["dry_run"] = True
        out.append(a)
    return out


# --- the run ----------------------------------------------------------------

def classify(reply: dict | None, err: Exception | None) -> tuple[str, str]:
    """(verdict, detail) for one dry run's answer: "ok", "refused" (both
    pass), "lua" (Lua error text), "bad" (the bridge doesn't know the action
    or won't dry-run it, or no JSON came back), "timeout" (no answer in time:
    a warning, not a failure)."""
    if err is not None:
        text = str(err)
        le = lua_error(text)
        if le:
            return "lua", le[:300]
        if type(err).__name__ == "NoAnswer":
            return "timeout", text[:160]
        return "bad", text[:200]
    reply = reply if isinstance(reply, dict) else {}
    le = lua_error(reply)
    if le:
        return "lua", le[:300]
    msg = str(reply.get("error") or "")
    if "has no dry run" in msg or "unknown action type" in msg or "dry_run must be" in msg:
        return "bad", msg[:200]
    if reply.get("ok"):
        return "ok", ""
    return "refused", msg[:120]


def run_dry_all(bridge, state: dict, out: Callable[[str], None] = print, only: list[str] | None = None,
                names: list[str] | None = None) -> int:
    """Dry-run every DRY_OK action (or `only` those) in the game; one line
    each and a summary through out(). Returns 1 on any Lua error (or an
    action the bridge doesn't know or won't dry-run), else 0."""
    from dfhack import DFHackError, GameNotRunning
    fort = Fort(state)
    names = names if names is not None else dry_ok_actions()
    if only:
        names = [n for n in names if n in only]
    counts = {"ok": 0, "refused": 0, "lua": 0, "bad": 0, "timeout": 0, "builder": 0}
    failed: list[str] = []
    for name in names:
        try:
            actions = build_actions(name, fort)
        except Exception as e:  # noqa: BLE001  (the builder's fault, said as such)
            counts["builder"] += 1
            failed.append(name)
            out(f"[FAIL] {name}: no arguments built ({type(e).__name__}: {e})"[:300])
            continue
        for a in actions:
            payload = json.dumps(a, separators=(",", ":"), default=str)
            reply, err = None, None
            t0 = time.perf_counter()
            try:
                reply = bridge.df.run_json("ai-bridge", "act", payload)
            except GameNotRunning:
                raise
            except DFHackError as e:
                err = e
            ms = (time.perf_counter() - t0) * 1000
            verdict, detail = classify(reply, err)
            counts[verdict] += 1
            args = {k: v for k, v in a.items() if k not in ("type", "dry_run")}
            label = name + (" " + json.dumps(args, separators=(",", ":"), default=str)[:70] if len(actions) > 1 else "")
            if verdict in ("lua", "bad"):
                failed.append(name)
                out(f"[FAIL] {label}: {'Lua error' if verdict == 'lua' else 'not a clean answer'}: {detail}")
            elif verdict == "timeout":
                out(f"[WARN] {label}: no answer in time ({detail})")
            else:
                out(f"[PASS] {label}: " + ("ok" if verdict == "ok" else f"refused: {detail}")
                    + (f" ({ms:.0f} ms)" if ms >= 1000 else ""))
    runs = sum(counts.values()) - counts["builder"]
    out(f"\n{len(names)} actions, {runs} dry runs: {counts['ok']} ok, {counts['refused']} refused cleanly, "
        f"{counts['lua']} Lua errors, {counts['bad']} not clean, {counts['timeout']} no answer in time"
        + (f", {counts['builder']} without arguments" if counts["builder"] else ""))
    if failed:
        out("FAILED: " + ", ".join(sorted(set(failed))))
    return 1 if failed else 0
