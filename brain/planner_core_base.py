"""planner_core_base: part of planner_core (split out of planner_core.py in r7, which re-exports every
name): the shared constants (recipes, shops, ticks, the cooldown/emergency/steer sets) and the small
state helpers (ticks, config, stocks, order watches)."""

from __future__ import annotations
import math
from digest import _d
from planner_config import PLANNER_CONFIG


BREW_RECIPES = {"brew_drink", "brew_drink_from_fruit", "make_mead"}
MEAL_RECIPES = {"prepare_easy_meal", "prepare_fine_meal", "prepare_lavish_meal"}

# Noble mandates ("Make N <item>") we can satisfy with an approved recipe.
MANDATE_RECIPES = {
    "TABLE": "stone_table", "CHAIR": "stone_chair", "DOOR": "stone_door",
    "CABINET": "stone_cabinet", "BOX": "stone_chest", "COFFIN": "stone_coffin",
    "STATUE": "stone_statue", "SLAB": "stone_slab", "ARMORSTAND": "stone_armor_stand",
    "WEAPONRACK": "stone_weapon_rack", "BED": "wooden_bed", "BIN": "wooden_bin",
    "BUCKET": "wooden_bucket", "CAGE": "wooden_cage", "BARREL": "wooden_barrel",
}
# Workshops the AI can build itself (lua/ai-layouts.lua WORKSHOPS)
BUILDABLE_SHOPS = {"Carpenters", "Masons", "Craftsdwarfs", "Still", "Kitchen", "Butchers", "Tanners",
                   "Leatherworks", "Loom", "Clothiers", "Farmers", "Fishery", "Mechanics", "Jewelers",
                   "Ashery", "Millstone", "Quern", "Bowyers", "WoodFurnace", "Smelter", "MetalsmithsForge",
                   "Kiln", "SoapMaker", "GlassFurnace",
                   "ScrewPress"}                   # (item9) paper from slurry (Quickfort 'wp')
# a forge also counts as the magma one, a glass furnace as the magma one
SHOP_ALIASES = {"MetalsmithsForge": ("MetalsmithsForge", "MagmaForge"),
                # (bridges before 0.75.1 reported the soap maker's by its raws code: 116 were built overnight)
                "SoapMaker": ("SoapMaker", "Custom:SOAP_MAKER", "Custom:SOAP_MAKERS"),
                "ScrewPress": ("ScrewPress", "Custom:SCREW_PRESS"),
                "GlassFurnace": ("GlassFurnace", "MagmaGlassFurnace"),
                # (0.104.96) the magma smelter and kiln count too (a fort with only those smelted nothing)
                "Smelter": ("Smelter", "MagmaSmelter"), "Kiln": ("Kiln", "MagmaKiln")}
SURVIVAL_SHOPS = ["Still", "Kitchen", "Carpenters"]       # (0.100.1) drink, food, and the furniture

TICKS_PER_DAY = 1200
TICKS_PER_YEAR = 403200

# Rules exempt from the per-rule cooldown (select()).
NO_COOLDOWN = {"threat_alert", "strategist", "squad_attack", "squad_recall", "train", "gates", "water", "flood",
               "trade_deal", "close_trade",       # time stands still while the trade screen is open
               "shelter_squads",                  # (0.105.0 review) an emergency, as in EMERGENCY
               "gate_stuck", "way_in",            # (0.105.32) they pace themselves (planner_gates)
               "shelter_flee"}                    # (0.105.45) a great danger inside, close to the shelter
# (0.105.26) a rule whose cooldown key isn't "<rule>_cooldown_ticks" (select()):
# the prisoners rule waited the 2-day default instead of its 7 days
COOLDOWN_KEYS = {"prisoners": "prisoner_room_cooldown_ticks",
                 # (r2 h9) one called wave a season; a stuck caravan's merchants told once a month
                 "migrant_drought": "h9_drought_cooldown_ticks", "stuck_caravan": "h9_caravan_cooldown_ticks"}
# Rules that may act more than once a cycle (select()).
MULTI_PER_CYCLE = {"stuck_order", "uniform", "noble_rooms", "tools", "strategist", "squad_attack", "squad_recall", "train",
                   "labor", "well_parts",
                   "mood",   # (0.105.24) a mood's materials: weave, tan, smelt, free, cancel in one cycle
                   "gate_stuck"}   # (0.105.32) each split gate piece its own step
# Responses to an attack: never held back by the per-cycle action limit.
EMERGENCY = {"threat_alert", "gate", "gates", "squad_attack", "flood", "gate_guard",   # (0.104.83 gate_guard)
             "shelter_squads", "shelter_refresh",                                   # (0.105.0; 0.105.26)
             # (0.105.32) E (8 Nov): an open hatch DF's walk map held shut, 64
             # dead of thirst outside it; and a way dug in for the cut off. A
             # life on each: no action limit, no refusal back-off or loop hold
             # (each rule paces its own tries: planner_gates)
             "gate_stuck", "way_in",
             "archer_post", "caravan_guard",   # (item5) crossbows to the posts in a siege; a caravan attacked
             "shelter_pick", "shelter_flee"}   # (0.105.45) the shelter away from the threat
# (0.104.89) rules the strategist may never hold: survival, safety and the
# answers to danger (it may still raise them)
STEER_PROTECTED = EMERGENCY | {"shelter", "alerts", "squad_recall", "water", "well", "drink",
                               "food", "farm_crops", "gather", "staff", "burial", "unsuspend",
                               "stuck_order", "tools", "found", "entrances",
                               "hospital_burrow",   # (0.104.167, review) never held: members are let out by it
                               "calm_burrow",       # (0.104.169) likewise
                               # (0.105.26) a life on each: a held mood goes insane; the infected, the
                               # injured, the hospital's soap and staff; fights among the fort's own
                               "mood", "infected_rest", "traction_rest", "traction", "traction_parts",
                               "soap_rush", "break_fights", "hospital", "doctor_post", "doctor_patient",
                               "rescue_labor", "stress_care", "jail_urgent",
                               # thirst and water: the well's parts and lids, the cistern's shut, drownings
                               "drink_fruit", "well_parts", "well_lid", "well_shaft", "cistern",
                               "water_traffic", "waterworks_shut",
                               # the gate that closes in an attack; the undead, curses, webs; the heist lockout
                               "gate_lever", "gate_doors", "gate_parts", "cursed", "reanimation",
                               "siege_cleanup", "webs", "remove_webs", "location_access",
                               # (0.105.26 seal fix) a soldier's water; doors on a cavern opening, the
                               # caverns sealed against a great beast; citizens shut outside
                               "flasks_order", "cavern_openings", "seal_cavern", "stranded",
                               # (0.105.32) an open gate the game holds shut; a way dug in
                               "gate_stuck", "way_in",
                               "insane",   # (0.105.40b) doors between the insane and deadly ground
                               "killer"}   # (item3) a killer among the fort's own locked away
STEER_MAX_DAYS = 84


def steer_of(memory, rule: str, now: int) -> dict | None:
    """(0.104.89) The strategist's standing word on a rule, if it holds now:
    {"mode": "raise" | "hold", "until": tick, "why": text}."""
    s = _d(_d(getattr(memory, "steer", None)).get(rule))
    if s.get("mode") in ("raise", "hold") and isinstance(s.get("until"), int) and now < s["until"]:
        if s["mode"] == "hold" and steer_protected(rule):      # (0.105.48, K6) EMERGENCY too
            return None
        return s
    return None


# (0.100.1) never held back by an earlier stuck order of the same recipe (see
# select()); (0.104.2) a well's parts: water for the injured; (0.105.26) a
# strange mood's materials (a life on it: a cloth order a mood needed was held
# 28 days; never swapped for a fallback recipe either)
STUCK_HOLD_EXEMPT = {"drink", "drink_fruit", "food", "well_parts", "mood"}
# (0.105.26) work orders never held by the stalled-order check or the daily
# work-order limit (select()): a strange mood's own materials
ORDER_HOLD_EXEMPT = {"mood"}
# Also outside the per-cycle action limit: switching a squad's schedule (instant, undoable).
# (0.104.169) calm_burrow too: a tantrum near the patients waits for no slot
LIMIT_EXEMPT = EMERGENCY | {"break_fights", "calm_burrow", "join_levels", "census", "train", "shelter", "entrances", "labor",
                            "gather", "stuck_order", "alerts",
                            "kitchen",   # (0.100) a kitchen setting, once per drink shortage: no slot of its own
                            "mood",      # (0.105.24) a strange mood's materials (a life on it; a handful of actions at most)
                            "insane",    # (0.105.40b) doors between the insane and deadly ground (one action)
                            "hunting_stop",   # (fix3) the AI's hunters called in when danger comes: no slot to wait for
                            # (0.105.48 K1b, audit A9 #2) a squad called back from a fight it loses
                            # (fire breather, necromancer siege, matchup, hunt retreat, called off):
                            # six recalls held three squads on their kill orders a cycle longer and
                            # the drink order behind them
                            "squad_recall"}


# (0.105.48, K6) the guards added after these sets were made: never held by
# the strategist (a hold lasts up to 84 days). The hold checks and the action
# limit also read EMERGENCY itself (limit_exempt, steer_protected): LIMIT_EXEMPT
# and STEER_PROTECTED are copies made here at import, so a rule a later module
# put in EMERGENCY (way_out, way_out_dig, well_rescue) missed them
STEER_PROTECTED.update({"intruder_guard", "thief_watch", "destroyer_gate", "hospital_guard", "staff_tantrum", "chronic_posts",
                        "tantrum_soldier",   # (0.105.99)
                        "near_gates", "near_gates_refresh", "hunting_stop", "fire_guard", "magma_guard",
                        "magma_shut", "lure_shut", "mood_shelter", "well_rescue", "well_safety"})


def emergency(*rules: str) -> None:
    """(0.105.48, K6) A response to danger: no action limit, no refusal
    back-off or loop hold, never held by the strategist. New modules call this
    rather than adding to each set by hand."""
    for r in rules:
        EMERGENCY.add(r)
        LIMIT_EXEMPT.add(r)
        STEER_PROTECTED.add(r)


def limit_exempt(rule: str) -> bool:
    """(0.105.48, K6) Outside the per-cycle action limit: LIMIT_EXEMPT or any EMERGENCY rule."""
    return rule in LIMIT_EXEMPT or rule in EMERGENCY


def steer_protected(rule: str) -> bool:
    """(0.105.48, K6) Never held by the strategist: STEER_PROTECTED or any EMERGENCY rule."""
    return rule in STEER_PROTECTED or rule in EMERGENCY


def abs_tick(state: dict) -> int:
    d = state["date"]
    return d["year"] * TICKS_PER_YEAR + d["tick"]


def stamp_tick(stamp) -> int | None:
    """A {year, tick} stamp (a project's `started`) as an absolute tick, or
    None when it isn't one."""
    d = _d(stamp)
    if isinstance(d.get("year"), int) and isinstance(d.get("tick"), int):
        return d["year"] * TICKS_PER_YEAR + d["tick"]
    return None


def game_day(state: dict) -> int:
    return abs_tick(state) // TICKS_PER_DAY


def factor(traits: dict, name: str) -> float:
    """Trait -> multiplier: 0 -> 1x, +100 -> 2x, -100 -> 0.5x, +-200 -> 4x / 0.25x."""
    return 2 ** (traits.get(name, 0) / 100)


# What the strategist may tune, and within what bounds (brain/strategist.py
# shows these to the model). (0.100, security pass) kept here so the planner
# applies them however the numbers arrive: a tampered or old save's memory
# can't set other keys (min_citizens, max_order...) or go past the bounds.
ADJUST_BOUNDS = {
    "drink_per_dwarf": (3, 40),
    "meals_per_dwarf": (2, 30),
    "blocks_per_dwarf": (0, 30),
    "wood_per_dwarf": (0, 10),
    "idle_share": (0.05, 0.8),
}


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def effective_config(adjust: dict | None, base: dict = PLANNER_CONFIG,
                     calibration: dict | None = None) -> dict:
    """The planner config: the starting guesses, then what tuned itself to the
    fort (bounded, brain/calibrate.py), then the strategist's adjustments,
    which win: only the ADJUST_BOUNDS keys, clamped to their bounds."""
    cfg = dict(base)
    for k, v in (calibration or {}).items():
        if k in cfg and _number(v):
            cfg[k] = v
    for k, v in _d(adjust).items():
        if k in cfg and k in ADJUST_BOUNDS and _number(v):
            lo, hi = ADJUST_BOUNDS[k]
            cfg[k] = max(lo, min(hi, v))
    return cfg


def unstored_cups(s: dict) -> int:
    """(0.104.157) Free cups lying off the stockpiles (in workshops, in halls
    where dwarves drank): Teacheroar, 1 Nov, 24 in a meeting hall and 10 in a
    dining hall, both finished goods piles full, so none was put back where
    the others could drink from it (149 of 150 drank without a cup)."""
    place = _d(_d(_d(_d(s.get("needs")).get("clothing")).get("free_cups_detail")).get("place"))
    return sum(int(v) for k, v in place.items() if k not in ("stockpile", "unwalkable") and isinstance(v, int))


def free_stock(state: dict, name: str) -> int:
    """(0.104.155) Items of a kind no job has claimed (`<name>_free`), else the
    plain count (an older bridge). The plain count holds claimed ones: three
    mechanisms "in store", all taken, kept every "make one if none" rule quiet."""
    st = state.get("stocks") if isinstance(state.get("stocks"), dict) else {}
    v = st.get(name + "_free")
    if isinstance(v, int):
        return v
    return int(st.get(name) or 0)


def queued(state: dict, recipes: set, ai_only: bool = False) -> int:
    """Jobs still to do on matching orders. A repeating order counts its full
    size even between repeats (when amount_left is 0). ai_only: the AI's own
    orders only (DFHack's smelting library has 16 SmeltOre orders that wait
    for 100 charcoal: they don't count as smelting)."""
    total = 0
    for o in state["orders"]:
        if ai_only and not o.get("by_ai"):
            continue
        if o.get("recipe") in recipes:
            left = max(0, o.get("amount_left") or 0)
            if o.get("repeats"):
                left = max(left, o.get("amount_total") or 0)
            total += left
    return total


WORKED_MAX_DAYS = 56


def watch_since(w: dict) -> int:
    """(0.104.141) Since when an order has stood still: its amount unchanged
    and nobody at work on one of its jobs."""
    since = w.get("since") if isinstance(w.get("since"), int) else 0
    worked = w.get("worked")
    # (review) at most WORKED_MAX_DAYS later: a job taken and dropped again
    # and again (its item out of reach) looks worked at every sample
    return min(max(since, worked), since + WORKED_MAX_DAYS * TICKS_PER_DAY) if isinstance(worked, int) else since


def stuck_days(w: dict, now: int) -> int:
    """(r1g8) Days an order has stood still, less the days the alarm was up
    (`paused`, counted by orders_seen): an order the sheltered dwarves can't
    reach isn't stuck."""
    since = watch_since(w)
    still = max(0, now - since)
    paused = w.get("paused") if isinstance(w.get("paused"), int) else 0
    return (still - min(max(0, paused), still)) // TICKS_PER_DAY


def supply_order_kept(s: dict, what, cfg: dict) -> str | None:
    """(r1g8) Why an order of the fort's own drink or meals is never cancelled
    as stuck (nor its recipe held back) now, or None. While drink (meals) is
    under its target or the alarm is up, a still's (kitchen's) order that
    stands still waits for the stills: cancelling it only throws away its
    jobs and bans the recipe 28-112 days (E y257-y259: brew orders cancelled
    9 times, drink 1,458 -> 183, dwarves dead of thirst)."""
    what = str(what)
    if what not in BREW_RECIPES and what not in MEAL_RECIPES:
        return None
    if s.get("civ_alert") is True:
        return "the alarm is up"
    citizens = int(_d(s.get("dwarves")).get("total") or 0)
    st = _d(s.get("stocks"))
    if what in BREW_RECIPES:
        have, per = st.get("drink"), cfg.get("drink_per_dwarf", 0)
    else:
        have, per = st.get("prepared_meals"), cfg.get("meals_per_dwarf", 0)
    if not isinstance(have, (int, float)):
        return "the stock is unknown"       # (no stock read: keep it, as when short)
    if citizens > 0 and have < citizens * float(per or 0):
        return f"{'drink' if what in BREW_RECIPES else 'meals'} {have} under the target of {round(citizens * float(per or 0))}"
    return None


# (r6 c2) kept local: unlike util's helpers (rounded to int)
def _clamp(v: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, round(v))))


MEMORIAL_SPAN = {"every": 0, "season": TICKS_PER_YEAR // 4, "year": TICKS_PER_YEAR}
OPTIONAL_LEVELS = ("tombs", "hospital", "tavern", "library", "barracks", "temple", "jail", "archery", "garden")
GEAR_WEAPONS = {"axe": "metal_battle_axe", "spear": "metal_spear", "mace": "metal_mace"}
GEAR_METALS = ("STEEL", "IRON", "BRONZE", "BISMUTH_BRONZE", "COPPER")     # best first
