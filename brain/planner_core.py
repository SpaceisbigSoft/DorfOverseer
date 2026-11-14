"""planner_core: part of the planner (split out of planner.py in 0.104.83; see planner.py)."""

from __future__ import annotations
import json
import math
from dataclasses import asdict, dataclass, field
from quirks import has_rule
from digest import _d, _l, normalize
from planner_config import PLANNER_CONFIG, DISPOSAL_ACTION_MAX  # noqa: F401  (13c: the tuning numbers, split out)

__all__ = ["great_present", "all_clear", "STEER_PROTECTED", "STEER_MAX_DAYS", "steer_of", "PLANNER_CONFIG", "BREW_RECIPES", "MEAL_RECIPES", "MANDATE_RECIPES", "BUILDABLE_SHOPS", "SHOP_ALIASES", "SURVIVAL_SHOPS", "TICKS_PER_DAY", "TICKS_PER_YEAR", "NO_COOLDOWN", "COOLDOWN_KEYS", "MULTI_PER_CYCLE", "EMERGENCY", "STUCK_HOLD_EXEMPT", "ORDER_HOLD_EXEMPT", "LIMIT_EXEMPT", "Proposal", "Memory", "abs_tick", "stamp_tick", "game_day", "factor", "ADJUST_BOUNDS", "_number", "effective_config", "queued", "unstored_cups", "free_stock", "watch_since", "_clamp", "MEMORIAL_SPAN", "OPTIONAL_LEVELS", "GEAR_WEAPONS", "GEAR_METALS", "NEEDS_YOU", "ask_player", "DISPOSAL_LEVELS", "DISPOSAL_ACTION_MAX", "player_rules", "OPEN_CAVERNS_MODES", "open_caverns_mode", "MAINTAIN_SKIPS", "level_refused", "_traits", "reachable_threats", "held_off_threats", "_holding_off", "ONE_A_CYCLE", "growth_mode", "growth_target", "JOB_SHOPS", "RECIPE_SHOPS", "WOOD_ELSEWHERE", "recipe_shop", "brewable_counts", "brew_recipe", "_watchdog_notes", "jobs_reported", "order_job_state", "masons_jammed", "stuck_hold_days", "_stuck_before", "stone_short", "_office_held", "tantrums_recent", "justice_held", "_restraint_order", "manager_needs_office", "suites_short", "wool_route", "thread_plants_here", "MINING_NEED_ONLY", "mining_plan", "noble_room_kinds", "SOCIAL_NEEDS", "care_waiting", "unmet", "_soldier_swap", "recently_home", "LOCATION_UNITS", "_location", "_location_short", "_real_locations", "can_fight", "is_ranged", "STALE_PROJECT_DAYS", "_workshops_busy", "shop_count", "shops_max", "_has_shop", "RAW_FOOD", "ALL_FOOD", "_idle_share", "idle_line", "IDLE_OLD_LINES", "levels_done", "_lever_state", "update_idle", "AGENDA_THEMES", "agenda", "food_per_dwarf", "WINTER_STOCK", "winter_factor", "young_fort", "established", "has_farms", "_best_metal", "REFUSAL_FIRST_DAYS", "REFUSAL_MAX_DAYS", "REFUSAL_IDLE_DAYS", "REFUSAL_KEYS", "LABOR_CAPS", "labor_given", "note_labor_given", "REFUSAL_ID_TYPES", "PER_ID_COOLDOWN", "refusal_key", "cooldown_key", "_refused_wait", "note_refusal", "TIMEOUT_TRIES", "timeout_streak", "brief_timeout", "LOOP_LIMITS", "LOOP_LIMIT_DEFAULT", "LOOP_EXEMPT", "_loop_count", "NO_EFFECT_RULES", "NO_EFFECT_WHY", "note_no_effect", "no_effect_wait", "_stalled_days", "_entrance_spot", "_record_any_outcome", "_weapon_gaps", "spare_sig", "MOOD_BODY_FLAGS", "mood_kind", "mood_on_hand", "mood_waits", "_stuck_again_rule"]

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
               "gate_stuck", "way_in"}            # (0.105.32) they pace themselves (planner_gates)
# (0.105.26) a rule whose cooldown key isn't "<rule>_cooldown_ticks" (select()):
# the prisoners rule waited the 2-day default instead of its 7 days
COOLDOWN_KEYS = {"prisoners": "prisoner_room_cooldown_ticks"}
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
             "archer_post", "caravan_guard"}   # (item5) crossbows to the posts in a siege; a caravan attacked
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
                               "insane"}   # (0.105.40b) doors between the insane and deadly ground
STEER_MAX_DAYS = 84


def steer_of(memory, rule: str, now: int) -> dict | None:
    """(0.104.89) The strategist's standing word on a rule, if it holds now:
    {"mode": "raise" | "hold", "until": tick, "why": text}."""
    s = _d(_d(getattr(memory, "steer", None)).get(rule))
    if s.get("mode") in ("raise", "hold") and isinstance(s.get("until"), int) and now < s["until"]:
        if s["mode"] == "hold" and rule in STEER_PROTECTED:
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
                            "hunting_stop"}   # (fix3) the AI's hunters called in when danger comes: no slot to wait for


@dataclass
class Proposal:
    rule: str
    action: dict
    reason: str
    priority: int  # lower runs first
    is_order: bool = False
    guard: bool = False    # (v35 fix) an EMERGENCY rule's proposal the loop guard still counts


@dataclass
class Memory:
    """What the overseer remembers between cycles, saved per fort."""
    last_fired: dict = field(default_factory=dict)       # rule -> absolute tick
    orders_by_day: dict = field(default_factory=dict)    # absolute game day (str) -> count
    ai_alert_raised: bool = False
    threat_alarm: dict = field(default_factory=dict)   # (0.105.0 review) {since, why}: the threats round's alarm, capped
    cavern_alarm: dict = field(default_factory=dict)   # (v35 fix) {since}: the alarm held for citizens in the caverns, capped
    weather_alarm: dict = field(default_factory=dict)  # (0.105.40b) {since, seen, on_seen, cleared, why}: evil weather's alarm
    alarm_gov: dict = field(default_factory=dict)      # (item4) {on {tick, cause, key, why}, off {key: tick}, month {m, n}}: the alarm kept from flapping
    hauling_surplus: dict = field(default_factory=dict)  # (0.105.40b fix) {since}: haulers to spare since then (planner_hauling)
    quiet_cycles: int = 0
    last_threat_tick: int = 0          # (0.104.100) a threat could reach the dwarves
    last_great_tick: int = 0           # (0.104.100) a great danger on the surface or in reach
    alert_suppressed: list = field(default_factory=list)  # threat ids the player chose to ignore
    tools_enabled_by_ai: list = field(default_factory=list)   # the game accepted our "enable"
    tools_confirmed_on: list = field(default_factory=list)    # seen running after we enabled it
    tools_seen_on: list = field(default_factory=list)         # seen running at any time
    tools_player_disabled: list = field(default_factory=list)  # was on, then switched off
    tool_attempts: dict = field(default_factory=dict)          # name -> times we tried to enable
    notes: list = field(default_factory=list)            # last cycle's "couldn't do X"
    # Strategist state
    adjust: dict = field(default_factory=dict)           # bounded planner adjustments
    adjust_at: dict = field(default_factory=dict)        # (0.97.1) when each was set: they last a season
    pending_events: list = field(default_factory=list)   # events since the last review
    pending_kinds: list = field(default_factory=list)    # big events not yet reviewed
    recent_actions: list = field(default_factory=list)   # last few actions taken, any rule
    prev_snapshot: dict = field(default_factory=dict)    # small slice of the last report
    moods_seen: dict = field(default_factory=dict)       # unit id -> tick its mood was first seen
    mood_progress: dict = field(default_factory=dict)    # (0.105.30) unit id -> {have, since}: a mood's items fetched, and since when
    mood_slaughter: dict = field(default_factory=dict)   # (0.105.30) unit id -> tick an animal went to the butcher for that mood (one a mood)
    mood_logged: dict = field(default_factory=dict)      # (0.105.30) unit id -> game day its requests were last journalled
    order_watch: dict = field(default_factory=dict)      # order id (str) -> {left, since, what, by_ai}
    pop_watch: dict = field(default_factory=dict)        # {pop, since}: the population and since when
    quick_locations: dict = field(default_factory=dict)  # (0.102.5) kind -> tick the dining hall was made one
    wishes_agreed: dict = field(default_factory=dict)    # (0.102.2) location petition wish -> tick agreed
    stuck_cancelled: dict = field(default_factory=dict)  # order "what" -> {tick, n}: the AI's own stuck orders it cancelled
    last_memorial_tick: int | None = None                # when the last memorial hall was started
    last_garden_tick: int | None = None                  # when the last set piece (statue garden) was started
    gardens_built: list = field(default_factory=list)    # their names
    agenda: list = field(default_factory=list)           # the season's goals (agenda()), for the season report
    action_log: dict = field(default_factory=dict)       # refusal_key -> ticks it was done, the last game year (loops)
    shops_started: dict = field(default_factory=dict)    # workshop name -> times a workshops project was started for it
    farm_steer: str = ""                                 # (0.99.6) "drink" while autofarm's thresholds favour brewable crops; (0.105.5) "crops": the AI sets the plots' crops (autofarm off)
    kitchen_ban: bool = False                            # (0.100) the AI banned cooking brewables while drink is short
    fat_ban: bool = False                                # (0.104.30) the AI kept fat and tallow from the cooks
    storage_started: int | None = None                   # (0.104.38) when the AI last began a storage level for full piles
    tantrums: list = field(default_factory=list)         # (0.104.31) [tick, who] of recent tantrums, a day each
    shops_seen: dict = field(default_factory=dict)       # (0.99.4) workshop name -> how many stood at its last start
    tree_year: dict = field(default_factory=dict)        # (0.89) {year, base}: trees_removed when the game year began
    world_seen: dict = field(default_factory=dict)       # (0.105.0) grudges (civs that besieged us), export wishes, contact said
    missions_seen: dict = field(default_factory=dict)    # (0.105.39) missions followed out and back, counts, journal entries
    cleanup_seen: dict = field(default_factory=dict)     # (0.105.40) world cleanup: the dry runs done per kind, the counts removed
    captives_seen: dict = field(default_factory=dict)    # (item6) {pit_trial, pitted, siege {since, peak}, tower_year}
    food_store_seen: dict = field(default_factory=dict)  # (0.105.40b, M6) the rotten food followed: {since, low, rotten, rise, rise_tick}
    alloy_seen: dict = field(default_factory=dict)       # (fix41) {fuel_note}: when the bronze-waits-for-fuel note was last said
    syndromes_seen: dict = field(default_factory=dict)   # (0.105.41, item 11) {dry, cleaned, last}: the contaminant clean's trial and counts
    polished_upto: int | None = None                     # finished-level count when every level was found polished
    no_effect: dict = field(default_factory=dict)        # (0.105.24) action key -> {reason, n, tick}: done for the same reason again
    story_season: str = ""                                # the last season the AI-written chronicle told ("y<year> <season>")
    gate_closed_by_ai: bool = False                      # the AI pulled the gate lever to close it
    # (0.105.33) the "AI gate" lever's state when the gate is open (lever id
    # (str) -> state): gate_closed_by_ai is read from the lever each cycle
    # (note_cycle), not toggled on a pull that may never happen
    gate_open_state: dict = field(default_factory=dict)
    gate_pull_asked: int | None = None                   # (0.105.36) when the AI last pulled the gate lever
    # (0.105.33) an alarm change or a tool switch-off whose reply never came
    # (ok None): {on, tick} / tool name -> tick; the next report says whether it went through
    alert_asked: dict = field(default_factory=dict)
    tool_off_asked: dict = field(default_factory=dict)
    squads_trained: list = field(default_factory=list)   # squads the AI put on training (ids)
    squads_rested: list = field(default_factory=list)    # squads the AI sent back to work while the fort is small
    squads_made: list = field(default_factory=list)      # squads the AI made itself (ids; 0.82)
    idle_hands: bool = False                             # many idle adults: every squad trains (0.83)
    idle_avg: float | None = None                        # running average of the idle share (0.84)
    refusals: dict = field(default_factory=dict)         # action key -> {"n": times refused in a row, "until": tick}
    climate_freezes: bool = False                         # ice has been seen near the fort (water freezes in winter)
    trouble_seen: str = ""                                # the last "fort in trouble" signs printed
    last_train_tick: int | None = None                   # when it last did
    libraries_imported: list = field(default_factory=list)  # DFHack order libraries the AI imported
    shelter_attempts: int = 0                            # tries at setting up the alert shelter
    shelter_tick: int | None = None                      # (0.105.35) the last try (after two: tried again later)
    gate_doors_requested: list = field(default_factory=list)  # entrances ("x,y,z") given doors
    rescan_entrances: bool = False                       # map the entrances again next cycle
    caverns_open: list = field(default_factory=list)     # caverns seen joined to the fort's ground
    gates_fortified: dict = field(default_factory=dict)  # entrance "x,y,z" -> gate style built there
    gates_fortified_ticks: dict = field(default_factory=dict)  # entrance "x,y,z" -> when (first seen open since)
    gate_failures: dict = field(default_factory=dict)    # entrance "x,y,z" -> why the game refused
    gate_failure_ticks: dict = field(default_factory=dict)  # entrance "x,y,z" -> when (tried again later)
    well_failure: str = ""                               # why no well could be placed (Needs you)
    extra_well_failure: str = ""                         # (0.104.141) why another well (one exists) couldn't be
    cavern_well_failure: str = ""                        # why no cavern well could be placed either
    cavern_shaft_stairs: bool = False                     # (0.104.13) the old shaft's give-up was cleared once
    cavern_gallery_retried: bool = False                  # (0.105.4 review) the old cavern refusal cleared once for the gallery
    well_floor_retried: bool = False                      # (0.105.24) the old "would not place the well" cleared once (a floor beside it)
    patient_since: dict = field(default_factory=dict)    # citizen id (str) -> tick first seen needing care
    pasture_failure: str = ""                            # why no pasture could be made (Needs you)
    farm_failure: str = ""                               # why no farm plots could be placed (Needs you)
    farm_failure_tick: int | None = None                 # when a farm level last couldn't be dug
    farm_crops_player: bool = False                      # (0.105.7 review) the player switched autofarm back on: the AI leaves the crops to it
    farm_dead_noted: str = ""                            # (0.105.7 review) the season the dead plots were last said
    reserve_noted: str = ""                              # (0.105.31) the mood reserve last said can't be made here
    reserve_swap_off: int | None = None                  # (0.105.31 reserve fixes) the season the fibre swap changed nothing
    farm_under_asked: dict = field(default_factory=dict)  # (0.105.7 review) {tick, tiles}: underground plots last laid out
    report_season: str = ""                              # the last season the player's report was written for
    found_failure: str = ""                              # why the first staircase couldn't be dug near the wagon
    found_wide_failure: str = ""                         # (0.105.35) ...nor further out (found_fort wide): Needs you
    shops_held_since: dict = field(default_factory=dict)  # (0.105.35) workshop -> when its "started twice" hold began
    shops_retried: dict = field(default_factory=dict)     # (v35 fix) workshop -> re-starts after the hold (SHOPS_RETRY_MAX)
    fps_cap: int | None = None                           # the population cap held while the game runs slowly
    strain_hold: bool = False                            # (0.104.106) newcomers held while the fort is strained
    strain_cap: int | None = None                        # (0.104.120) the cap held while strained (its size then)
    ores_freed: list = field(default_factory=list)       # (0.104.124) ores the masons were given in a crisis
    crisis: dict = field(default_factory=dict)          # (0.104.137) the fort in crisis: since, why
    deaths_seen: list = field(default_factory=list)     # (0.104.137) citizens' deaths (ticks), 12 weeks
    convict_watch: dict = field(default_factory=dict)   # (0.104.138) cases convicted, sentences then, held until
    fight_deaths: list = field(default_factory=list)    # (0.104.139) citizens killed by citizens (ticks), 4 weeks
    gate_part_extra: dict = field(default_factory=dict)   # (0.104.139) stuck entrances given one more part
    pruned_after: int = 0                                 # (0.104.140) the threat tick last cleaned up after
    kill_sent: dict = field(default_factory=dict)        # (0.104.140) squad id -> unit ids last sent after
    kill_sent_at: dict = field(default_factory=dict)     # (v35 fix) squad id -> tick it was last sent (kill_sent)
    labor_given: dict = field(default_factory=dict)      # (v35 fix) rule -> [[tick, dwarves], ...]: labours the AI gave (LABOR_CAPS)
    residency: dict = field(default_factory=dict)        # (0.105.9) {probe: {id, unit, tick}, works: True|False, since}
    character_projects: list = field(default_factory=list)   # (0.105.10) project ids the AI started as the fort's own
    locations_closed: list = field(default_factory=list)     # (0.105.12) location ids the AI shut to visitors
    gatehouses: dict = field(default_factory=dict)           # (0.105.23) entrance "x,y,z" -> {tick, bridge} built
    construct: dict = field(default_factory=dict)            # (0.105.30) wings built, soil floors done, the hall's block wait
    locations_yours: list = field(default_factory=list)      # (0.105.12) ones the AI shut and you opened: left alone
    heists: list = field(default_factory=list)               # (0.105.24) [tick, who] artifact heists and visitors' killings
    visitor_shut: dict = field(default_factory=dict)         # (0.105.24) {tick, until, visitors, meetings, unheard}: shut for the mayor
    locations_acted: dict = field(default_factory=dict)      # (0.105.26) location id (str) -> tick the AI last shut or opened it
    intrusion: dict = field(default_factory=dict)            # (0.105.30) {tick, civ, invaders, cleared}: DF's last invasion record
    stranger_shut: dict = field(default_factory=dict)        # (0.105.30) {seen, who}: a stranger last seen seeking a meeting
    gate_unstick: dict = field(default_factory=dict)         # (0.105.32) gate piece id (str) -> {step, tick, ok, split_after, done, prevent}
    way_in: dict = field(default_factory=dict)               # (0.105.32) "x,y,z" -> {tick, ok, project_id, why}: ways dug in
    second_way: dict = field(default_factory=dict)           # (0.105.33) {stranded_ever, tick, ok, project_id, why, done}: a second way to the surface
    gear_spare_since: dict = field(default_factory=dict)  # "weapons"/"body"/"helms" -> when 3+ spares sat unused
    swapped: dict = field(default_factory=dict)  # (0.104.78) unit id -> when the swap sent them home
    drafted: dict = field(default_factory=dict)  # (0.104.138) unit id -> when a fill or swap drafted them
    released: dict = field(default_factory=dict)  # (0.104.164) unit id -> when stress care or a baby sent them home
    train_mode: dict = field(default_factory=dict)  # (0.104.168) the rotation's {all: bool, tick: when it changed}
    keen_lift: dict = field(default_factory=dict)   # (0.104.168) {n, tick}: soldiers wanted raised for the keen in a crisis
    unstick_seen: dict = field(default_factory=dict)   # (0.104.138) the spare gear at the last untangling, times
    steer: dict = field(default_factory=dict)    # (0.104.89) the strategist's raised and held rules: rule -> {mode, until, why}
    strategist_wants: list = field(default_factory=list)   # (0.104.89) report sections it asked to see in full next time
    token_ratio: float = 1.0                     # (0.104.89) a review's real cost against its estimate, learned
    maintain_pop: int | None = None                      # Maintain: the population being kept
    last_expel_tick: int | None = None                   # when a dwarf was last sent away
    last_join_tick: int | None = None                    # (0.104.108) when areas on a level were last looked at for joining
    census: dict = field(default_factory=dict)           # (0.104.113) the last census of creatures and items (with "tick")
    fight: dict = field(default_factory=dict)            # (0.104.118) a fight against great dangers under way
    fight_factor: dict = field(default_factory=dict)     # (0.104.118) kind -> how much stronger than estimated (learned)
    shelter_since: dict = field(default_factory=dict)    # (0.105.22) squad id -> tick it took the shelter order
    shelter_rest: dict = field(default_factory=dict)     # (0.105.22) squad id -> tick it may shelter again
    shelter_supply: dict = field(default_factory=dict)   # (0.105.36, D5) the AI shelter's last fill: {tick, drink_short, no_water, no_food, ...}
    fights: list = field(default_factory=list)           # (0.104.118) the last fights: {tick, keys, lost, of}
    called_off: dict = field(default_factory=dict)       # (0.105.26) great danger id -> tick its fight was called off
    dig_seen: dict = field(default_factory=dict)         # (0.104.110) project id -> {"dug", "tick" (last progress), "freed"}
    join_wait_days: int = 2                              # (0.104.108) days to the next look (longer once all were seen)
    culture: dict = field(default_factory=dict)          # culture history (see culture.py)
    culture_pushed: str = ""                              # what was last written into the save
    declined: dict = field(default_factory=dict)          # proposal id -> tick you said No
    saved_before: str = ""                                # project the game was saved for
    # Memory, part one (brain/outcomes.py, calibrate.py, learning.py)
    outcomes: dict = field(default_factory=dict)          # the outcome log: open entries, verdicts, tallies
    calibration: dict = field(default_factory=dict)       # self-tuned targets, within bounds
    learning: dict = field(default_factory=dict)          # what the player declined or undid
    # Memory, part two (brain/memstore.py: each kind is stored on its own)
    timeline: dict = field(default_factory=dict)          # a row of numbers a day, seasons, years
    atlas: dict = field(default_factory=dict)             # survey, registry, entrances, located events
    chronicle: dict = field(default_factory=dict)         # the fort's story

    @classmethod
    def from_dict(cls, d: dict | None) -> "Memory":
        m = cls()
        for k, v in (d or {}).items():
            if not hasattr(m, k):
                continue
            default = getattr(m, k)
            if default is None:
                # an optional tick or count (None until set): any number is kept
                if v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)):
                    setattr(m, k, v)
            elif isinstance(v, type(default)):
                setattr(m, k, v)
        return m

    def to_dict(self) -> dict:
        return asdict(self)


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


def _clamp(v: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, round(v))))


MEMORIAL_SPAN = {"every": 0, "season": TICKS_PER_YEAR // 4, "year": TICKS_PER_YEAR}
OPTIONAL_LEVELS = ("tombs", "hospital", "tavern", "library", "barracks", "temple", "jail", "archery", "garden")
GEAR_WEAPONS = {"axe": "metal_battle_axe", "spear": "metal_spear", "mace": "metal_mace"}
GEAR_METALS = ("STEEL", "IRON", "BRONZE", "BISMUTH_BRONZE", "COPPER")     # best first


# Notes for what the game truly won't let the AI do (a screen it can't press,
# a choice DFHack can't make), each saying what the AI does meanwhile. The
# overseer shows them apart: "Needs you". (0.105.35, the player's standing
# decision: nothing waits for the player; what the AI can do, it does.)
NEEDS_YOU = "[you] "


def ask_player(notes: list, text: str) -> None:
    notes.append(NEEDS_YOU + text)


DISPOSAL_LEVELS = ("store", "melt", "dump", "destroy")   # (0.105.27) the Rules key `disposal`, in order


def player_rules(s: dict) -> dict:
    """The Rules tab (lua/ai-overseer-settings.lua), with its defaults when an
    older panel didn't send them."""
    st = s["settings"] if isinstance(s.get("settings"), dict) else {}
    levels = st.get("levels") if isinstance(st.get("levels"), dict) else {}
    pace = st.get("memorial_pace")
    attack = st.get("attack_policy")
    return {"memorial_pace": pace if pace in MEMORIAL_SPAN or pace == "never" else "season",
            "attack_policy": attack if attack in ("all", "ordinary", "never") else "ordinary",
            "fill_squads": st.get("fill_squads") is not False,
            "train_squads": st.get("train_squads") is not False,
            "appoint_nobles": st.get("appoint_nobles") is not False,
            "gate_lever": st.get("gate_lever") is not False,
            "make_gear": st.get("make_gear") is not False,
            "gear_weapon": st.get("gear_weapon") if st.get("gear_weapon") in GEAR_WEAPONS else "axe",
            "engrave_slabs": st.get("engrave_slabs") is not False,
            "import_smelting": st.get("import_smelting") is not False,
            "alert_shelter": st.get("alert_shelter") is not False,
            "pasture_animals": st.get("pasture_animals") is not False,
            "build_gate_doors": st.get("build_gate_doors") is not False,
            "fortify_entrances": st.get("fortify_entrances") is not False,
            "fort_goal": "maintain" if st.get("fort_goal") == "maintain" else "expand",
            "set_pop_cap": st.get("set_pop_cap") is not False,
            "levels": {k: levels.get(k) is not False for k in OPTIONAL_LEVELS},
            "order_supplies": st.get("order_supplies") is not False,
            "mood_workshops": st.get("mood_workshops") is not False,
            "give_trinkets": st.get("give_trinkets") is not False,
            "water_works": st.get("water_works") is not False,
            "expel_vampires": st.get("expel_vampires") is not False,
            "accept_visitors": st.get("accept_visitors") is not False,
            "answer_locations": st.get("answer_locations") is not False,
            # (0.104.167, review) the hospital burrow: off only when the settings say so (then its members let out)
            "hospital_burrow": st.get("hospital_burrow") is not False,
            # (0.104.169) the calm-down burrows: off only when the settings say so (then their members let out)
            "calm_burrow": st.get("calm_burrow") is not False,
            # (0.105.0) tribute a civilisation asks: pay a small one, refuse a large one (or pay / refuse)
            "tribute": st.get("tribute") if st.get("tribute") in ("small", "pay", "refuse") else "small",
            # (0.105.41, item 8) a peace proposal: the AI decides (sieges, sliders) / accept / refuse
            "peace": st.get("peace") if st.get("peace") in ("ai", "accept", "refuse") else "ai",
            # (0.105.0, 13b) a messenger appointed and sent to make contact with sites not in contact
            "make_contact": st.get("make_contact") is not False,
            # (0.105.24, 13b) the AI drives DF's World screen to send the messenger: on only when the player says so
            "send_messenger": st.get("send_messenger") is True,
            # (0.105.39, 13b) missions on the world map: off / rescue (and stolen artifacts) /
            # explore (and those) / all (raids, pillage, tribute, conquest too: they can start a war)
            "missions": st.get("missions") if st.get("missions") in ("off", "rescue", "explore", "all") else "rescue",
            # (0.105.39) the AI sends them itself by DF's World screen: on only when the player says so
            "send_missions": st.get("send_missions") is True,
            # (0.105.24) locations shut to visitors a while after a heist / when the mayor is swamped by visitors
            "heist_lockout": st.get("heist_lockout") is not False,
            "shut_to_visitors": st.get("shut_to_visitors") is not False,
            # (0.105.30) construction above ground (the hall, gate wings, soil floors): off only when the settings say so
            "construct": st.get("construct") is not False,
            # (0.105.41) traffic zones on the AI's finished levels (lua/ai-traffic.lua): off only when the settings say so
            "traffic": st.get("traffic") is not False,
            # (item 12) the fort's artifacts put on display in the AI's rooms: off only when the settings say so
            "display_artifacts": st.get("display_artifacts") is not False,
            # (0.105.0) water works: the moat (on by default only where the survey found a river:
            # the planner wants one only then), magma workshops, the muddied farm level
            "moat": st.get("moat") is not False,
            "magma_workshops": st.get("magma_workshops") is not False,
            "irrigation": st.get("irrigation") is not False,
            # (0.105.4 review) a cavern well into a cavern layer not yet discovered. (v35 fix)
            # three-state: "ai" (the default: the AI decides), "always", "never"; an old
            # save's true is "always", false "ai"
            "open_caverns": open_caverns_mode(st.get("open_caverns")),
            # (0.105.0) the squads wait in the shelter while the AI hides: off only when the settings say so
            "squads_shelter": st.get("squads_shelter") is not False,
            # (0.105.41, item 2) the AI's feeder piles linked to the AI's own workshops: off only when the settings say so
            "link_feeders": st.get("link_feeders") is not False,
            # (0.105.27) forbidden items: store < melt < dump < destroy (each does the ones before);
            # the player's own forbidden items (no game reason) only when the switch says so; the
            # enemy's gear kept from the smelters (the War-hold preset)
            "disposal": st.get("disposal") if st.get("disposal") in DISPOSAL_LEVELS else "destroy",
            "disposal_player_items": st.get("disposal_player_items") is True,
            "keep_enemy_gear": st.get("keep_enemy_gear") is True,
            # (0.105.40, 13e) world cleanup for the game's speed (brain/planner_cleanup.py):
            # off / safe (the default: spatter, old dead units, items lost a year) / full (and
            # unreachable hostile or wild creatures)
            # (item10) cavern trees felled when the caverns are watched and wood is short: off only when the settings say so
            "cavern_logging": st.get("cavern_logging") is not False,
            # (0.105.41, item 11) syndrome carriers kept apart and their spatter cleaned: off only when the settings say so
            "syndrome_care": st.get("syndrome_care") is not False,
            "world_cleanup": st.get("world_cleanup") if st.get("world_cleanup") in ("off", "safe", "full") else "safe",
            "clear_alerts": st.get("clear_alerts") if st.get("clear_alerts") in ("all", "quiet", "none") else "quiet",
            # (0.105.41, item 4) a hunter or two out while it is safe; farm plots on a known, quiet cavern's soil
            "hunting": st.get("hunting") is not False,
            "cavern_farms": st.get("cavern_farms") is not False}


OPEN_CAVERNS_MODES = ("ai", "always", "never")


def open_caverns_mode(v) -> str:
    """(v35 fix) The Rules switch "Cavern well into an unfound cavern":
    "ai" (the default), "always" or "never"; an old save's true is "always",
    its false "ai"."""
    if v is True:
        return "always"
    return v if v in OPEN_CAVERNS_MODES else "ai"


MAINTAIN_SKIPS = ("library", "memorial", "temple", "garden")


def level_refused(s: dict, kind: str, cfg: dict | None = None) -> str | None:
    """(0.97) Why a new level of this kind is not to be dug (None: it may be):
    its Rules-tab switch, the Maintain goal, Mining -100's needed-only rule.
    The planner's own ladder follows these; the strategist's levels are
    checked against them too (they used to ignore the switches and Maintain)."""
    rules_ = player_rules(s)
    if kind in OPTIONAL_LEVELS and not rules_["levels"].get(kind, True):
        return f"the {kind} level is off on the Rules tab"
    if rules_["fort_goal"] == "maintain" and kind in MAINTAIN_SKIPS:
        return f"the fort's goal is Maintain (no new {kind})"
    if kind in MINING_NEED_ONLY and mining_plan(_traits(s), cfg or PLANNER_CONFIG)["need_only"]:
        return f"Mining is -100: only the levels the fort needs (no {kind})"
    return None


def _traits(s: dict) -> dict:
    t = s["settings"].get("traits")
    return _d(t)


def reachable_threats(s: dict, traits: dict, cfg: dict) -> list:
    """Ids of threats that can reach the dwarves (plus, at Caution +100, nearby
    ones whose reach is unknown). Threats counted but not listed get stand-in ids."""
    o = s["others_on_map"]
    threats = o.get("threats") or []
    ids = [t.get("id") for t in threats if t.get("can_reach_dwarves") is True]
    unlisted = max(0, (o.get("threats_that_can_reach_dwarves") or 0) - len(ids))
    # (0.104.139) a flier in the air (its reach unknown) near the dwarves can
    # reach them whatever DF's walk groups say; and a building destroyer near
    # them isn't held by a shut door, when it is an invader or on the surface
    # (never a cavern beast that can't get up: review)
    ids += [t.get("id") for t in threats
            if t.get("can_reach_dwarves") is not True and t.get("id") not in ids
            and ((t.get("flier") and t.get("can_reach_dwarves") is None)
                 or (t.get("destroyer") and (t.get("invader") or t.get("layer") == "upper_levels")))
            and isinstance(t.get("distance_to_nearest_dwarf"), (int, float))
            and t["distance_to_nearest_dwarf"] <= cfg["near_threat_tiles"]]
    # (0.104.140) an invader by the trade depot while merchants are in: the
    # caravan has no walls (the squads go out to it)
    if int(o.get("merchants") or 0) > 0:
        ids += [t.get("id") for t in threats if t.get("id") not in ids and t.get("invader")
                and t.get("can_reach_dwarves") is not False                       # (review) not behind a wall
                and isinstance(t.get("depot_distance"), (int, float)) and t["depot_distance"] <= cfg["depot_guard_tiles"]]
    ids += [f"unlisted{i}" for i in range(unlisted)]
    if traits.get("caution", 0) >= 100:
        for t in threats:
            lv = t.get("levels_from_nearest_dwarf")
            if (t.get("can_reach_dwarves") is None and lv is not None and lv <= cfg["cautious_alert_levels"]
                    and t.get("id") not in ids):
                ids.append(t.get("id"))
    return ids


def great_present(s: dict) -> bool:
    """(0.104.100) A great danger (titan, forgotten beast, megabeast) that can
    reach the dwarves or walks the surface: cavern ones out of reach don't count
    (they never leave, and would keep the fort shut for good)."""
    o = _d(s.get("others_on_map"))
    return any(isinstance(t, dict) and t.get("great_danger")
               and (t.get("can_reach_dwarves") is True or t.get("layer") == "upper_levels")
               for t in _l(o.get("threats")))


def all_clear(s: dict, memory, cfg: dict) -> tuple[bool, str]:
    """(0.104.100) May the AI lower its alert and open its gates? Quiet for
    `alert_quiet_cycles` cycles, `alert_quiet_days` game days since a threat could
    reach the dwarves, and `alert_quiet_days_great` since a great danger was about.
    (ok, why not) - the why for the log while it holds."""
    if memory.quiet_cycles < cfg["alert_quiet_cycles"]:
        return False, f"quiet for {memory.quiet_cycles} cycle(s)"
    now = abs_tick(s)
    if not isinstance(now, int):
        return True, ""
    gdays = (now - (memory.last_great_tick or 0)) // TICKS_PER_DAY
    if memory.last_great_tick and gdays < cfg["alert_quiet_days_great"]:
        return False, f"a great danger was about {gdays} day(s) ago"
    days = (now - (memory.last_threat_tick or 0)) // TICKS_PER_DAY
    if memory.last_threat_tick and days < cfg["alert_quiet_days"]:
        # (0.105.2) a sealed fort costs more than the wait saves: B (2 Nov)
        # ran at 1-3 FPS behind its shut hatch, 6 citizens and 51 visitors
        # outside re-routing to a way in that wasn't there; unlocking it set
        # the game racing again. With the game slow and nothing hostile left
        # on the map, the quiet days are skipped.
        if s.get("fps_low") and not held_off_threats(s):
            return True, ""
        return False, f"the last threat was {days} day(s) ago"
    return True, ""


def held_off_threats(s: dict) -> list:
    """(0.100.1) Threats on the map that can't walk in right now (a raised
    bridge, a shut door) but are still there: invaders anywhere, and dangers
    up on the surface. Cavern creatures that can't reach aren't counted (they
    never leave, and would keep the fort shut for good)."""
    o = _d(s.get("others_on_map"))
    # (0.104.139) nor the undead an evil land raises on the surface (not
    # invaders, never leaving): they kept the gates shut for good
    return [t for t in _l(o.get("threats")) if isinstance(t, dict) and t.get("can_reach_dwarves") is not True
            and (t.get("invader") or (t.get("layer") == "upper_levels"
                                      and not ("Undead" in _l(t.get("kinds")) and not t.get("great_danger"))))]


def _holding_off(s: dict, memory) -> bool:
    """The AI has the alarm up or is keeping watch over the gates."""
    return bool(memory.ai_alert_raised or _d(s.get("entrances")).get("armed"))


# (0.100) Kinds of level the rules may each ask for in one cycle (about a
# dozen rules propose a workshops level; two may propose a temple): only the
# most urgent that passes the other limits goes ahead in select(); the
# others ask again once it is under way (`_workshops_busy`). (Two rules
# ordering the same recipe are left: each sizes its own need, and the next
# cycle sees both queued.)
ONE_A_CYCLE = ("workshops", "temple")


def growth_mode(s: dict, cfg: dict) -> tuple[str, int | None]:
    """What the Growth slider asks for, from its effective value (Extreme
    doubles it, as on every slider since 0.94):
      ("target", n)    about n dwarves: -100 low (25), 0 average (100), +100
                       high (250); past +100 it keeps rising, 500 at +150
      ("uncapped", None)  +200 (+100 with Extreme): no cap at all
      ("shrink", days) past -100 (Extreme): no newcomers, one dwarf sent away
                       every `days` in-game days (280 at -110, 28 at -200)"""
    v = max(-200.0, min(200.0, float(_traits(s).get("growth", 0))))
    p = cfg["growth_points"]
    if v >= 200:
        return "uncapped", None
    if v > 100:
        return "target", int(p["high"] * 4 ** ((v - 100) / 100) + 0.5)
    if v < -100:
        return "shrink", int(cfg["shrink_days"] * 100 / (abs(v) - 100) + 0.5)
    edge = p["high"] if v >= 0 else p["low"]
    return "target", int(p["average"] + (edge - p["average"]) * abs(v) / 100 + 0.5)


def growth_target(s: dict, cfg: dict) -> int:
    """The population to plan for (bedrooms): the target, or for no cap, far."""
    mode, n = growth_mode(s, cfg)
    if mode == "uncapped":
        return cfg["uncapped"]
    if mode == "shrink":
        return 0
    return n


# Where a work order's jobs are done (for saying why one doesn't move).
JOB_SHOPS = {"MakeCrafts": "Craftsdwarfs", "MakeAmulet": "Craftsdwarfs", "MakeBracelet": "Craftsdwarfs",
             "MakeRing": "Craftsdwarfs", "MakeEarring": "Craftsdwarfs", "SmeltOre": "Smelter", "MakeCharcoal": "WoodFurnace",
             "BrewDrink": "Still", "PrepareMeal": "Kitchen", "ConstructBin": "Carpenters",
             "ConstructBed": "Carpenters", "MakeBarrel": "Carpenters", "ConstructBucket": "Carpenters",
             "MakeWeapon": "MetalsmithsForge", "MakeArmor": "MetalsmithsForge", "MakeHelm": "MetalsmithsForge",
             "MakePants": "MetalsmithsForge", "MakeGloves": "MetalsmithsForge",
             "ConstructMechanisms": "Mechanics", "ConstructBlocks": "Masons", "WeaveCloth": "Loom",
             "MakeLargePot": "Craftsdwarfs", "ConstructChest": "Masons", "ConstructCabinet": "Masons",
             "ConstructDoor": "Masons", "ConstructTable": "Masons", "ConstructThrone": "Masons",
             "ConstructStatue": "Masons", "ConstructCoffin": "Masons", "ConstructArmorStand": "Masons",
             "ConstructWeaponRack": "Masons", "ConstructSlab": "Masons",
             "MakeAsh": "WoodFurnace", "MakeLye": "Ashery", "MAKE_SOAP_FROM_TALLOW": "SoapMaker",
             "CollectSand": "GlassFurnace", "MakeWindow": "GlassFurnace",       # (0.104.95)
             "RENDER_FAT": "Kitchen"}


# The AI's own recipes made by a reaction, by where they're made.
RECIPE_SHOPS = {"pig_iron": "Smelter", "steel": "Smelter", "coke_bituminous": "Smelter",
                **{f"alloy_{m}": "Smelter" for m in ("bronze", "bismuth_bronze", "brass", "electrum", "billon",
                                                     "black_bronze", "rose_gold", "sterling_silver")},   # (0.105.40 M7)
                "coke_lignite": "Smelter", "smelt_ore": "Smelter", "brew_drink": "Still",
                "brew_drink_from_fruit": "Still", "make_mead": "Still", "make_charcoal": "WoodFurnace",
                "weave_plant_cloth": "Loom", "weave_yarn_cloth": "Loom", "weave_silk_cloth": "Loom",
                "cloth_rope": "Clothiers", "yarn_rope": "Clothiers", "silk_rope": "Clothiers",
                "metal_chain": "MetalsmithsForge", "process_plants": "Farmers", "make_quicklime": "Kiln",
                "make_plaster_powder": "Kiln", "make_milk_of_lime": "Ashery", "make_parchment": "Tanners",
                "make_quire": "Craftsdwarfs",
                # (0.104.87) sewn at a clothier's (an order for one the fort hasn't waits)
                "cloth_bag": "Clothiers", "silk_bag": "Clothiers", "yarn_bag": "Clothiers",
                # (0.104.95) glass is made at a glass furnace, precious metal crafts at the forge
                "collect_sand": "GlassFurnace", "metal_crafts": "MetalsmithsForge",
                "metal_amulet": "MetalsmithsForge", "metal_bracelet": "MetalsmithsForge",   # (0.104.137)
                "metal_ring": "MetalsmithsForge", "metal_earring": "MetalsmithsForge",
                "tan_hide": "Tanners", "raw_green_glass": "GlassFurnace"}   # (0.105.24) a strange mood's leather and glass


# (0.100.1, overnight run) the workshop a recipe is made at, where it's sure:
# an order for a workshop the fort doesn't have never moves (130 brew jobs and
# meals and beds waited five years with no still, kitchen or carpenter, were
# cancelled as stuck and ordered again: 338 cancels in a night)
WOOD_ELSEWHERE = {"wooden_crossbow": "Bowyers", "wooden_bolts": "Bowyers", "wooden_cups": "Craftsdwarfs",
                  "wood_crafts": "Craftsdwarfs", "bone_crafts": "Craftsdwarfs"}


def recipe_shop(recipe) -> str | None:
    r = str(recipe or "")
    if r in RECIPE_SHOPS:
        return RECIPE_SHOPS[r]
    if r in WOOD_ELSEWHERE:
        return WOOD_ELSEWHERE[r]
    if r.startswith("brew_"):
        return "Still"
    if r.startswith("prepare_") and r.endswith("_meal"):
        return "Kitchen"
    if r.startswith("wooden_"):
        return "Carpenters"
    if r.startswith("glass_"):
        return "GlassFurnace"
    return None


def brewable_counts(s: dict) -> tuple[int, int]:
    """(0.105.23) (plants, fruit) a still can brew: the bridge's brewable
    counts (0.99.5: each material's DRINK_MAT, items not in a job) when it
    sends them, the raw stocks otherwise."""
    st, sup = _d(s.get("stocks")), _d(s.get("supplies"))
    if isinstance(sup.get("brewable_plants"), int):
        return int(sup["brewable_plants"] or 0), int(sup.get("brewable_growths") or 0)
    return int(st.get("plants") or 0), int(st.get("plant_growths") or 0)


def brew_recipe(s: dict) -> str | None:
    """(13c) The brew recipe a still can do now: from plants if any can be
    brewed, else from fruit, else None. (0.105.23) From fruit when there is
    more of it than of plants: B (the Monastery) had 4 brewable plants, and a
    brew of 10 from plants found 4 and stood still."""
    plants, fruit = brewable_counts(s)
    # (an older bridge's raw growths are mostly leaves, not fruit: plants first then)
    counted = isinstance(_d(s.get("supplies")).get("brewable_plants"), int)
    if plants > 0 and (plants >= fruit or not counted):
        return "brew_drink"
    return "brew_drink_from_fruit" if fruit > 0 else None


def _watchdog_notes(s: dict, memory, cfg: dict, notes: list) -> None:
    """Work that has stopped without anyone saying so (0.48's fort: smelting
    orders that could never start, crafts the trade code couldn't see):
    work orders whose count hasn't moved in 2 weeks are named, with the
    likely reason when it's a missing workshop; the AI's own after 4 weeks
    are Needs you. And a population unchanged for a year is said."""
    now = abs_tick(s)
    shops = {**_d(_d(s.get("buildings")).get("workshops")), **_d(_d(s.get("buildings")).get("furnaces"))}
    stuck_note, stuck_you = [], []
    by_id = {str(o.get("id")): o for o in _l(s.get("orders")) if isinstance(o, dict)}
    for k, w in memory.order_watch.items():
        if not isinstance(w, dict) or not isinstance(w.get("since"), int) or not (w.get("left") or 0) > 0:
            continue
        days = (now - watch_since(w)) // TICKS_PER_DAY
        if days < cfg["order_stuck_days"]:
            continue
        shop = JOB_SHOPS.get(str(w.get("job")))
        state = order_job_state(by_id.get(str(k))) if jobs_reported(s) else ""   # (0.104.13) what its job is doing
        # (0.105.35) what the AI does about it, not "check ..." for the player
        why = (f"the fort has no {shop}" if shop and not _has_shop(_d(s.get("buildings")), shop)
               else state or "its workshop, workers or materials hold it")
        why += (f"; the AI cancels it at {cfg['order_stuck_you_days']} days" if w.get("by_ai")
                and days < cfg["order_stuck_you_days"] else "" if w.get("by_ai") else "; the player's order: left as it is")
        text = f"{w.get('what')} ({w.get('left')} left, {'the AI' if w.get('by_ai') else 'yours'}) for {days} days: {why}"
        if w.get("by_ai") and days >= cfg["order_stuck_you_days"]:
            if _stuck_before(memory, w.get("what"), now, cfg):
                stuck_you.append(text)       # cancelled once already and stuck again
            # (else _stuck_orders_rule cancels it)
        else:
            stuck_note.append(text)
    if stuck_note:
        notes.append(f"{len(stuck_note)} work order(s) haven't moved: " + "; ".join(sorted(stuck_note)[:3]))
    if stuck_you:
        # (0.105.35) said, not Needs you: _stuck_again_rule cancels them again
        # and each is held longer (stuck_hold_days, doubled up to 112 days)
        notes.append(f"{len(stuck_you)} of the AI's work order(s) got stuck again after a cancel: "
                     + "; ".join(sorted(stuck_you)[:3])
                     + " (the AI cancels each again and holds it longer before ordering it again)")
    pw = _d(memory.pop_watch)
    cap = _d(s.get("society")).get("pop_cap")
    if isinstance(pw.get("since"), int) and now - pw["since"] >= TICKS_PER_YEAR and (not cap or pw.get("pop", 0) < cap):
        notes.append(f"the fort has had {pw.get('pop')} dwarves for a year or more"
                     + (f" (population cap {cap})" if cap else "")
                     + ": migrants come to a fort that grows richer (crafts for the caravans, built rooms)"
                     + ("; the AI sets the population cap itself" if player_rules(s)["set_pop_cap"]
                        else "; the population cap is the player's (its Rules switch is off)"))


def _stuck_again_rule(s: dict, memory, cfg: dict, proposals: list) -> None:
    """(0.105.35) Nothing waits for the player: the AI's own order stuck
    again after it was cancelled as stuck (_stuck_before) is cancelled again
    (was Needs you, left standing for good); the cancel's `stuck` books it
    once more, so the recipe is held longer each time (stuck_hold_days, to
    stuck_retry_max_days). As _stuck_orders_rule: not on a stale or unapproved
    order list, not while no order at all has started, and the last slab or
    coffin for the waiting dead stays."""
    if memory is None or "orders" in _d(s.get("_errors")):
        return
    orders = [o for o in _l(s.get("orders")) if isinstance(o, dict)]
    if any("validated" in o for o in orders) and not any(o.get("active") for o in orders):
        return
    unapproved = {str(o.get("id")) for o in orders if o.get("validated") is False}
    live = {str(o.get("id")) for o in orders}
    dead = int(_d(s.get("dead")).get("ghosts") or 0) > 0 or int(_d(s.get("dead")).get("unburied") or 0) > 0
    taken = {p.action.get("order_id") for p in proposals if p.action.get("type") == "cancel_work_order"}
    now = abs_tick(s)
    n = sum(1 for p in proposals if p.rule == "stuck_order")
    for k, w in sorted(memory.order_watch.items()):
        if n >= cfg["stuck_cancel_max"]:
            break
        if (k in unapproved or k not in live or not isinstance(w, dict) or not w.get("by_ai")
                or not isinstance(w.get("since"), int) or not (w.get("left") or 0) > 0):
            continue
        what = str(w.get("what"))
        days = (now - watch_since(w)) // TICKS_PER_DAY
        if days < cfg["order_stuck_you_days"] or not _stuck_before(memory, what, now, cfg):
            continue
        if dead and what in ("stone_slab", "stone_coffin"):
            continue
        try:
            oid = int(k)
        except ValueError:
            continue
        if oid in taken:
            continue
        hold = stuck_hold_days({"n": int(_d(memory.stuck_cancelled.get(what)).get("n") or 1) + 1}, cfg)
        proposals.append(Proposal("stuck_order", {"type": "cancel_work_order", "order_id": oid, "stuck": what},
                                  f"the AI's {what} order ({w.get('left')} left) got stuck again after a cancel "
                                  f"({days} days without moving): cancel it again (not placed again for {hold} days)", 6))
        n += 1


def jobs_reported(s: dict) -> bool:
    """(0.104.13) The bridge counts each AI order's jobs (from 0.104.13)."""
    try:
        return tuple(int(x) for x in str(s.get("bridge_version") or "0").split(".")[:3]) >= (0, 104, 13)
    except ValueError:
        return False


def order_job_state(o: dict) -> str:
    """(0.104.13) What an order's jobs are doing, from the bridge's count of
    them (call only when `jobs_reported`)."""
    if not isinstance(o, dict) or not o.get("by_ai"):
        return ""
    j = o.get("jobs")
    if not isinstance(j, dict):
        return ("no job made from it yet (no free workshop of its kind, or the game finds no material for it)"
                if o.get("active") else "")
    if (j.get("suspended") or 0) > 0:
        return f"its job is suspended at the workshop ({j.get('suspended')} of {j.get('n')})"
    if (j.get("working") or 0) > 0:
        return "a dwarf is on it now"
    who = []
    if j.get("permitted"):                       # (0.104.125) the workshop's worker profile
        who.append(f"only {j['permitted']} named dwarf(s) may work there")
    if j.get("min_skill") or j.get("max_skill"):
        who.append(f"its workers' skill is limited to {j.get('min_skill') or 0}-{j.get('max_skill') or 'any'}")
    return (f"{j.get('n')} job(s) wait at the workshop for a worker with the labour"
            + (f" ({'; '.join(who)})" if who else ""))


def masons_jammed(s: dict) -> int:
    """(0.104.32) Unworked engrave-slab jobs (autoslab's, waiting for blank
    slabs) on a mason's bench whose job list is full (10): Enxah's held 7 of
    the 10, so neither the slabs they wait for nor enough coffins could get
    on. The bench jobs then lift that many to make room."""
    worst = 0
    for w in _l(_d(s.get("order_desk")).get("workshops")):
        if not isinstance(w, dict) or w.get("type") != "Masons" or not isinstance(w.get("job_list"), list):
            continue
        jl = w["job_list"]
        if len(jl) < 10:
            return 0                            # a mason's bench with room: nothing to lift
        if any(isinstance(j, dict) and j.get("type") == "ConstructSlab" and not j.get("order") for j in jl):
            return 0                            # (0.104.33) blank slabs already on the bench: let them come
        stuck = sum(1 for j in jl if isinstance(j, dict) and j.get("type") == "EngraveSlab" and not j.get("worker"))
        worst = max(worst, stuck)
    return worst


def stuck_hold_days(sc: dict, cfg: dict) -> int:
    """(0.104.37) How long a recipe cancelled as stuck waits: 28 days, doubled
    each time it got stuck again soon after (to 112)."""
    n = int(_d(sc).get("n") or 1)
    return min(cfg["stuck_retry_max_days"], cfg["stuck_retry_days"] * 2 ** max(0, n - 1))


def _stuck_before(memory, what, now: int, cfg: dict) -> bool:
    """The AI cancelled an order for this as stuck not long ago."""
    c = _d(_d(getattr(memory, "stuck_cancelled", None)).get(str(what)))
    return isinstance(c.get("tick"), int) and now - c["tick"] < cfg["stuck_again_days"] * TICKS_PER_DAY


def stone_short(s: dict, n: int) -> bool:
    """Fewer than n boulders of stone the masons and crafters may use (only
    known with a bridge from 0.51: otherwise False)."""
    su = s.get("stone_use")
    return isinstance(su, dict) and isinstance(su.get("usable"), int) and su["usable"] < n


def _office_held(s: dict, code: str) -> bool:
    return bool(_l(_d(_d(_d(s.get("offices")).get("offices")).get(code)).get("held")))


def tantrums_recent(s: dict, memory, days: int = 28) -> int:
    if memory is None:
        return 0
    now = abs_tick(s)
    return sum(1 for t in memory.tantrums if isinstance(t, list) and isinstance(t[0], int)
               and 0 <= now - t[0] < days * TICKS_PER_DAY)


def justice_held(s: dict) -> bool:
    """Does someone hold the sheriff's or captain of the guard's office?"""
    offices = _d(_d(s.get("offices")).get("offices"))
    return any(_l(_d(offices.get(c)).get("held")) for c in ("SHERIFF", "CAPTAIN_OF_THE_GUARD"))


def _restraint_order(s: dict, n: int, cfg: dict, proposals: list, notes: list) -> None:
    """A jail's restraints wait for ropes or chains: a rope from cloth, else a
    chain (one bar each) from the commonest metal there are bars for, else
    wait (a note)."""
    if queued(s, {"cloth_rope", "metal_chain"}):
        return
    st = _d(s.get("stocks"))
    amount = min(n, cfg["max_order"])
    # (0.104.138) plant cloth beyond what the hospitals keep (Teacheroar: the
    # rope order stuck, "Needs 1 unused plant cloth", while the 4-5 bolts
    # counted were the hospital's): the rope wants plant cloth
    kinds = _d(_d(s.get("supplies")).get("cloth_kinds"))
    # (0.105.33 merge) a bridge that reports supplies.hospital already leaves
    # the hospital's cloth out of cloth_kinds: not taken off twice
    hosp = 0 if (kinds and isinstance(_d(s.get("supplies")).get("hospital"), dict)) else sum(
        int(_d(e.get("have")).get("cloth") or 0) for e in _l(_d(s.get("locations")).get("list"))
        if isinstance(e, dict) and e.get("type") == "HOSPITAL")
    free_cloth = (int(kinds.get("plant") or 0) if kinds else int(st.get("cloth") or 0)) - hosp
    if free_cloth >= amount:
        proposals.append(Proposal("furniture", {"type": "work_order", "recipe": "cloth_rope", "amount": amount},
                                  f"the jail is waiting for {n} rope(s) or chain(s): make ropes from cloth", 4, True))
        return
    bars = _d(_d(_d(s.get("military")).get("gear")).get("bars"))
    metal = next((m for m in ("IRON", "COPPER", "BRONZE", "STEEL") if (bars.get(m) or 0) >= amount), None)
    if metal:
        proposals.append(Proposal("furniture", {"type": "work_order", "recipe": "metal_chain", "amount": amount,
                                                "material": f"INORGANIC:{metal}"},
                                  f"the jail is waiting for {n} chain(s): forge them in {metal.lower()}", 4, True))
    else:
        notes.append(f"the jail is waiting for {n} rope(s) or chain(s): no cloth and no metal bars yet")


def manager_needs_office(s: dict) -> bool:
    """(0.100.2) The fort has a manager who has no office, and no free office
    to give them."""
    nr = _d(s.get("noble_rooms"))
    if (_d(nr.get("free")).get("office") or 0) > 0:
        return False                           # the noble rooms rule gives it
    return any(isinstance(n, dict) and n.get("office") == "MANAGER" and "office" in _l(n.get("needs"))
               for n in _l(nr.get("nobles")))


def suites_short(s: dict) -> int:
    """Nobles still wanting a bedroom or office with no free one to give:
    a suites level is dug for them (a bedroom and an office each, max 8)."""
    nr = _d(s.get("noble_rooms"))
    free = _d(nr.get("free"))
    short = 0
    for kind in ("bedroom", "office"):
        want = sum(1 for n in _l(nr.get("nobles")) if isinstance(n, dict) and kind in _l(n.get("needs")))
        short = max(short, want - (free.get(kind) or 0))
    return max(0, min(8, short))


def wool_route(s: dict) -> bool:
    """(0.104.28) Thread can come from shorn animals: tame ones that can be
    shorn and a farmer's workshop to shear and spin at."""
    return (int(_d(s.get("supplies")).get("shearable") or 0) > 0
            and _has_shop(_d(s.get("buildings")), "Farmers"))


# (0.105.24) what a strange mood asks for, in kinds the AI can act on
MOOD_BODY_FLAGS = ("bone", "shell", "horn", "pearl", "ivory", "tooth")


def mood_kind(x: dict) -> str:
    """One of a mood request's kinds: cloth, leather, bone, shell, bar,
    rough, glass_rough, cut_gem, stone, block, log, other."""
    item = str(_d(x).get("item") or "").upper()
    flags = set(str(f) for f in _l(_d(x).get("flags")))
    mat = str(_d(x).get("material") or "").lower()
    if item == "CLOTH":
        return "cloth"
    if item == "SKIN_TANNED":
        return "leather"
    if item in ("NONE", "CORPSEPIECE", "") and flags & set(MOOD_BODY_FLAGS):
        return "shell" if "shell" in flags and "bone" not in flags else "bone"
    if item == "BAR":
        return "bar"
    if item == "ROUGH":
        return "glass_rough" if ("glass" in mat or "glass" in flags) else "rough"
    if item == "SMALLGEM":
        return "cut_gem"
    if item == "BOULDER":
        return "stone"
    if item == "BLOCKS":
        return "block"
    if item == "WOOD":
        return "log"
    return "other"


def mood_on_hand(x: dict) -> bool | None:
    """(0.105.24) The bridge's count for a mood request (lua/ai-moods.lua):
    True when enough lies free within the dwarf's walk, False when not, None
    from an older bridge (no count)."""
    av = _d(x).get("avail")
    if not isinstance(av, dict):
        return None
    want = max(1, int(_d(x).get("quantity") or 1))
    # (0.105.30) what the dwarf already carries that suits it counts too
    return bool(av.get("enough")) or int(av.get("reach") or 0) + int(av.get("held") or 0) >= want


def mood_waits(s: dict) -> set:
    """(0.105.24) The kinds the fort's crafting moods wait for and don't have
    within reach (from a bridge that counts; every unmet kind from an older
    one): the gem cutters, bone carvers and the like leave them alone."""
    out = set()
    for m in _l(_d(s.get("moods")).get("list")):
        if not isinstance(m, dict) or not m.get("craft"):
            continue
        for x in _l(m.get("missing")):
            if isinstance(x, dict) and mood_on_hand(x) is not True:
                out.add(mood_kind(x))
    return out


def thread_plants_here(s: dict) -> bool:
    """(0.104.11) Plants in stock that give thread (the bridge counts them
    from 0.104.11; an older one: any plant may)."""
    su = _d(s.get("supplies"))
    if "thread_plants" in su:
        return int(su.get("thread_plants") or 0) > 0
    return int(_d(s.get("stocks")).get("plants") or 0) > 0


# --- (0.96) graded behaviour: each slider's numbers in one place -------------
# (brain/temperament.py shows them on the panel; Design Notes 3c). Extreme
# doubles the slider value before it reaches here, as everywhere.

MINING_NEED_ONLY = ("library", "archery", "garden", "barracks", "temple", "jail")


def mining_plan(traits: dict, cfg: dict) -> dict:
    """Mining (shallow - deep): how much the fort digs beyond its needs.
    -100 or lower: only the levels it needs (no library, archery, garden,
    barracks, temple or jail level; bedrooms, storage, workshops, dining,
    tombs, hospital, tavern, wells and farms still dug); -50 or lower: no ore
    veins mined (metal comes by trade); otherwise veins are mined while bars
    run under 50 x factor (25 at -100, 100 at +100), 40 x factor tiles at a
    time; quarries 20 x factor (10-30: the bridge's quarry takes 1-30)."""
    m = traits.get("mining", 0) or 0
    f = factor(traits, "mining")
    return {"need_only": m <= -100,
            "veins": m > -50,
            "bars_below": int(cfg["smelt_when_bars_below"] * f),
            "ore_stock_max": int(cfg["ore_stock_max"] * f),
            "vein_tiles": max(10, min(80, int(40 * f))),
            # (0.105.24) at most 30, what act_quarry accepts: A, B, D and E (2-5
            # Nov) asked 60 at Mining +100 and were refused "quarry needs count
            # 1-30" 112-174 times each (20 x factor keeps the slider graded)
            "quarry": max(10, min(30, int(20 * f)))}


def noble_room_kinds(traits: dict, memory=None) -> tuple:
    """Deference (ignoring - indulgent): which rooms a noble's office gets
    given: none at -100 or lower, a bedroom at -50 or lower, a bedroom and
    an office below 0, all four (and dining room and tomb) from 0.
    (0.103.15) Nobles' Pride: all four unless Deference is at its lowest."""
    d = traits.get("deference", 0) or 0
    if d <= -100:
        return ()
    if memory is not None and has_rule(getattr(memory, "culture", None), "noble_pride"):
        return ("bedroom", "office", "dining", "tomb")
    if d <= -50:
        return ("bedroom",)
    if d < 0:
        return ("bedroom", "office")
    return ("bedroom", "office", "dining", "tomb")


SOCIAL_NEEDS = ("Socialize", "BeWithFriends", "MakeMerry", "DrinkAlcohol")


def care_waiting(s: dict) -> int:
    """Patients with a treatment waiting (diagnosis, surgery, ...): infected
    wounds alone don't count (0.88.3)."""
    h = _d(s.get("health"))
    if isinstance(h.get("waiting"), int):          # (0.104.133) the full count: the list stops at 30
        return h["waiting"]
    return sum(1 for p in _l(h.get("patients")) if isinstance(p, dict) and _l(p.get("needs")))


def unmet(s: dict, *names: str) -> int:
    """Citizens distracted by any of these needs (the bridge's `needs` report)."""
    n = _d(_d(s.get("needs")).get("needs"))
    return sum(int(_d(n.get(k)).get("distracted") or 0) for k in names)


def recently_home(s: dict, memory) -> list:
    """(0.104.138) Units the AI sent home in the last 168 days (newest 100),
    for the bridge's fill to pass over: swapped, or (0.104.164) released."""
    if memory is None:
        return []
    now = abs_tick(s)
    # (0.104.164) and those released for stress or a baby (the fill drafted
    # one back once he was merely unhappy; they never counted as swaps)
    sent = dict(_d(getattr(memory, "released", None)))
    for k, v in _d(getattr(memory, "swapped", None)).items():
        if isinstance(v, int) and v > (sent.get(k) if isinstance(sent.get(k), int) else -1):
            sent[k] = v
    rows = sorted(((t, k) for k, t in sent.items()
                   if isinstance(t, int) and 0 <= now - t < 168 * TICKS_PER_DAY), reverse=True)[:100]
    return [int(k) for _, k in rows if str(k).isdigit()]


def _soldier_swap(s: dict, cfg: dict, proposals: list | None, memory=None) -> None:
    """(0.104.64) Constant training leaves soldiers no time for their other
    needs (Enxah, spring y75: of those badly wanting to craft 23 of 24 were
    soldiers, of BeWithFriends 27 of 43, PrayOrMeditate 14 of 22) while 33
    civilians badly wanted to train and none of the soldiers did. While
    enough civilians badly want to train, a soldier whose own training is
    met and who badly misses two or more other things goes back to work,
    one at a time; the fill drafts the keen first (bridge 0.104.64). Never
    while threats can reach the fort."""
    if proposals is None:
        return
    nd = _d(s.get("needs"))
    keen = int(nd.get("keen_civilians") or 0)
    starved = [x for x in _l(nd.get("starved_soldiers")) if isinstance(x, dict) and x.get("id") is not None]
    # (0.104.78) not one sent home lately: the list is the day's report, and the
    # cycles between asked for a soldier already out (refused)
    if memory is not None:
        now = abs_tick(s)
        # (0.104.138) and never one swapped this year, nor one drafted in the
        # last 84 days (Teacheroar: the same 20 dwarves swapped 15-22 times)
        recent = {str(k) for k, t in _d(getattr(memory, "swapped", None)).items()
                  if isinstance(t, int) and 0 <= now - t < 336 * TICKS_PER_DAY}
        recent |= {str(k) for k, t in _d(getattr(memory, "drafted", None)).items()
                   if isinstance(t, int) and 0 <= now - t < 84 * TICKS_PER_DAY}
        starved = [x for x in starved if str(x["id"]) not in recent]
    if keen < cfg["soldier_swap_keen_min"] or not starved:
        return
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return
    # (0.104.114, the 38-year soak: 3,122 swaps in 87 hours, a soldier sent
    # home every two minutes, so the squads were always green) at most a
    # tenth of the soldiers swapped in 28 days
    if memory is not None:
        now = abs_tick(s)
        month = sum(1 for t in _d(getattr(memory, "swapped", None)).values()
                    if isinstance(t, int) and 0 <= now - t < 28 * TICKS_PER_DAY)
        soldiers = int(_d(_d(s.get("military")).get("gear")).get("soldiers") or 0)
        # (0.104.142) more while many keen civilians wait (Teacheroar: 44 badly
        # wanting to train, 4 swaps a month); the memory of swaps and drafts
        # (a year, 84 days) keeps it from churning the same dwarves
        # (0.104.168) in a crisis, twice that: training eases the stress of those
        # who long for it (Teacheroar, 1 Nov: 45% unhappy, 89 distracted by
        # unmet MartialTraining, 18 keen civilians, 4 swaps a month)
        per_keen = cfg["soldier_swap_month_keen"]
        if _d(getattr(memory, "crisis", None)).get("why"):
            per_keen = cfg["soldier_swap_month_keen_crisis"]
        if month >= max(cfg["soldier_swap_month_min"], soldiers // cfg["soldier_swap_month_share"],
                        keen // max(1, per_keen)):
            return
    x = max(starved, key=lambda v: len(_l(v.get("unmet"))))
    act = {"type": "squad_swap", "unit_id": x["id"]}
    home = recently_home(s, memory)                  # (0.104.138) the fill passes these over
    if home:
        act["avoid"] = home
    if _d(getattr(memory, "crisis", None)).get("why"):
        act["strict"] = True                         # (0.104.168) in a crisis the place never goes to the very unhappy
    proposals.append(Proposal("soldier_swap", act,
                              f"{x.get('name')} has trained enough and badly misses "
                              f"{', '.join(_l(x.get('unmet'))[:3])}, while {keen} civilians badly want to train: "
                              "back to work, a keen one takes the place", 4))


# DF keeps some location supplies in larger units (abstract_building_contents)
LOCATION_UNITS = {"thread": 15000, "cloth": 10000, "powder": 150, "soap": 150}


def _location(s: dict, kind: str) -> dict | None:
    """The first location of this kind in the bridge's `locations.list` (0.83+)."""
    for e in _l(_d(s.get("locations")).get("list")):
        if isinstance(e, dict) and e.get("type") == kind:
            return e
    return None


def _location_short(loc: dict, keys) -> dict:
    """{supply: (have, want)} in whole items, for what a location keeps less of than it wants."""
    out = {}
    have, want = _d(loc.get("have")), _d(loc.get("want"))
    for k in keys:
        u = LOCATION_UNITS.get(k, 1)
        h, w = int(have.get(k) or 0) // u, int(want.get(k) or 0) // u
        if w > 0 and h < w:
            out[k] = (h, w)
    return out


def _real_locations(counts: dict, key: str, memory, listing: list | None = None) -> int:
    """(0.102.5) Locations of a kind, not counting the AI's stop-gap one laid
    over the dining hall: a proper hall still comes through the ladder.
    (0.103.13) The bridge marks one laid over a dining hall (`over_dining`):
    the memory of the stop-gap was lost with a reload (Enxah: quick_locations
    {} in the save, so its 49 dwarves longing to pray got no shrine)."""
    quick = _d(getattr(memory, "quick_locations", None))
    kind = {"TEMPLE": "temple", "INN_TAVERN": "tavern"}.get(key)
    rows = [x for x in _l(listing) if isinstance(x, dict) and x.get("type") == key]
    if rows:
        marked = any(x.get("over_dining") for x in rows)
        return max(0, sum(1 for x in rows if not x.get("over_dining")) - (1 if kind in quick and not marked else 0))
    return max(0, int(counts.get(key) or 0) - (1 if kind in quick else 0))


def can_fight(q: dict, cfg: dict) -> bool:
    """(0.105.2) A squad worth sending at a threat: `min_squad_to_fight`
    members, and that many of them armed (the bridge's `power.armed`: a
    weapon in hand or one given on a weapon entry). B (2 Nov): all four
    squads went at one thief in turn with no weapon among them, and he
    lived. A bridge without the count: members alone, as before."""
    need = cfg.get("min_squad_to_fight", 3)
    members = q.get("members") or 0
    if members < need:
        return False
    armed = _d(q.get("power")).get("armed")
    if not isinstance(armed, int) or isinstance(armed, bool):
        return True
    return armed >= min(need, members)


def is_ranged(q: dict) -> bool:
    """A squad in a crossbow uniform the AI gave it."""
    return "crossbow" in str(q.get("ai_uniform") or "").lower()


STALE_PROJECT_DAYS = 28


def _workshops_busy(open_: list) -> bool:
    """A workshops project is under way (the AI starts one at a time). One
    stuck furnishing for STALE_PROJECT_DAYS or more doesn't count (0.86:
    region2's second forge waited 104 days for an anvil, and every new
    workshop, the kiln among them, waited behind it)."""
    return any(isinstance(p, dict) and p.get("kind") == "workshops"
               and (_d(p.get("furnish")).get("days") or 0) < STALE_PROJECT_DAYS for p in open_)


def shop_count(b: dict, name: str) -> int:
    """How many workshops (or furnaces) of a kind stand, under any of its names."""
    places = {**_d(b.get("workshops")), **_d(b.get("furnaces"))}
    return sum(int(places.get(n, 0) or 0) for n in SHOP_ALIASES.get(name, (name,)))


def shops_max(cfg: dict, citizens: int) -> int:
    """(0.99.4) The most workshops of one kind the AI builds: 3 for a small
    fort, one for every 50 dwarves once that is more (5 at 228: region2's 3
    stills, all brewing, couldn't keep 228 dwarves in drink)."""
    return max(cfg["shops_max_each"], -(-int(citizens or 0) // 50))


def _has_shop(b: dict, name: str) -> bool:
    places = {**_d(b.get("workshops")), **_d(b.get("furnaces"))}
    return any(places.get(n, 0) > 0 for n in SHOP_ALIASES.get(name, (name,)))


# Food a dwarf can eat or cook: raw (cookable) and everything (with meals,
# and fish still to be cleaned). Stock names as the bridge counts them.
RAW_FOOD = ("meat", "fish", "plants", "plant_growths", "cheese", "eggs")
ALL_FOOD = ("prepared_meals", "raw_fish") + RAW_FOOD


def _idle_free_known(s: dict) -> bool:
    free = _d(s.get("dwarves")).get("idle_free")
    return isinstance(free, int) and not isinstance(free, bool)


def _idle_share(s: dict) -> float:
    """The share of the fort's working adults with nothing to do. (0.105.33)
    From the bridge's `idle_free` (no job, no social activity, not in a
    squad) over the adults outside the squads: prayer, the tavern and reading
    are not idleness, and soldiers are never idle. An older bridge's report
    has no idle_free: its idle_adults over all adults, as before."""
    dw = _d(s.get("dwarves"))
    free = dw.get("idle_free")
    if _idle_free_known(s):
        squads = dw.get("in_squads")
        squads = squads if isinstance(squads, int) and not isinstance(squads, bool) else 0
        return max(0, free) / max(1, int(dw.get("adults") or 0) - max(0, squads))
    return (dw.get("idle_adults") or 0) / max(1, dw.get("adults") or 1)


# (0.105.33 fix) The idle-driven rules' lines were set for the old measure
# (idle_adults/adults); on the stricter one (_idle_share) the truly idle run
# at 12-23% and the rules almost stopped. PLANNER_CONFIG now holds the lines
# for the stricter measure, set to fire as often over the 8 Nov run's season
# states as the old ones did on the old measure (polish 47 states before and
# after, blocks 54/53, garden 60/59, idle_train 34/34, its off line 53/53).
# These are the old lines, for a report with no idle_free (an older bridge):
# there _idle_share is still the old measure.
IDLE_OLD_LINES = {"polish_idle_share": 0.3, "garden_idle_share": 0.2, "idle_blocks_share": 0.25,
                  "idle_train_share": 0.4, "idle_train_off_share": 0.25}


def idle_line(s: dict, cfg: dict, key: str) -> float:
    """(0.105.33 fix) An idle rule's line (`key` in IDLE_OLD_LINES) for the
    measure _idle_share gives this report: cfg's own on the stricter one;
    on the old one, scaled to the old line (a tuned value keeps its lean)."""
    v = cfg[key]
    if _idle_free_known(s):
        return v
    return v * IDLE_OLD_LINES[key] / PLANNER_CONFIG[key]


def levels_done(state: dict):
    """(0.105.33) How many levels the fort has finished, ever: the bridge's
    `done_total` (it never stops counting), else its `finished`, which stops
    at the 20 closed projects it keeps (the polish gate stuck there for good).
    None when the report has neither."""
    pr = _d(state.get("projects"))
    n = pr.get("done_total")
    if isinstance(n, int) and not isinstance(n, bool):
        return n
    return pr.get("finished")


def _lever_state(lever: dict):
    """(0.105.33) A gate lever's reported state (0 or 1, as DF keeps it), or None."""
    v = _d(lever).get("state")
    if isinstance(v, bool):
        return int(v)
    return v if isinstance(v, int) else None


def update_idle(s: dict, memory, cfg: dict) -> None:
    """(0.84; called by note_cycle, before planning) The running average of
    the idle share (memory.idle_avg: the count of idle dwarves jumps from
    cycle to cycle; live, 0.83: over 40%, under 25% and back within three
    game days, so the rotation sent a squad off duty and back), and the band
    on it (memory.idle_hands): on from `idle_train_share` (20%), off only
    under `idle_train_off_share` (14%), since the dwarves who then train
    aren't idle any more. (0.105.33 fix: were 40% / 25% on the old idle
    measure, which counted prayer and the tavern as idle.)"""
    share = _idle_share(s)
    avg = memory.idle_avg
    if isinstance(avg, (int, float)):
        share = (1 - cfg["idle_avg_weight"]) * avg + cfg["idle_avg_weight"] * share
    memory.idle_avg = round(share, 4)
    memory.idle_hands = (share >= idle_line(s, cfg, "idle_train_share")
                         or (memory.idle_hands and share >= idle_line(s, cfg, "idle_train_off_share")))


# What a rule works toward, in a few words (the season's agenda)
AGENDA_THEMES = {
    "arms": "arm and armour the soldiers", "uniform": "dress the squads", "barracks_assign": "house the squads",
    "squad_fill": "fill the squads", "grandeur": "dress the halls", "quick_temple": "a place to pray", "quick_tavern": "a tavern", "stress_care": "care for dwarves near breaking", "squad_trim": "send extra soldiers back to work", "unload_depot": "empty the depot after the caravans", "needs_finery": "jewellery to wear", "good_cooks": "the best cooks to the kitchen", "squad_make": "raise a new squad", "uniform_adopt": "dress the squads", "staff": "staff the hospital, library and tavern", "tavern": "stock the tavern", "kiln": "plaster and paper", "anvil": "an anvil for a new forge", "petitions": "answer petitions", "residency": "answer petitions to stay", "train": "train the soldiers",
    "build": "build the fort's next level", "furniture": "furnish the new levels",
    "steel": "make steel", "alloy": "alloy bronze and finer metals", "smelt": "smelt the ore", "ore": "mine ore", "fuel": "make fuel",
    "trade": "trade with the caravans", "trade_deal": "trade with the caravans", "crafts": "make goods to sell",
    "gems": "cut gems", "encrust": "set gems into crafts", "drink": "keep the drink flowing",
    "needs_meal": "cook good meals", "needs_craft": "let dwarves craft",
    "food": "keep the fort fed", "farms": "farm", "hospital": "stock the hospital", "soap": "make soap",
    "feeder": "shorten the hauling", "labor": "put idle hands to work", "labor_trim": "take the extra hands off fishing", "well": "find water for a well", "well_lid": "close the cavern well's stairs", "well_shaft": "a gate in the cavern well's shaft", "planned_parts": "parts the planned buildings wait for", "comfort": "shoes and cups for the fort", "mothers": "mothers home from the squads", "dead_units": "clear old dead from the unit list", "herd": "keep the herds the fort's size",
    "stuck_order": "clear stuck work", "unsuspend": "resume suspended work", "stray_gear": "hand out lost gear", "assign_weapons": "arm the soldiers", "assign_kit": "armour the soldiers", "soldier_swap": "let the keen train", "temple_chest": "a chest for the temple", "instrument_orders": "clear the instrument backlog", "pair_chairs": "seat dwarves together", "recreation": "time off for the unhappiest", "hospital_burrow": "keep the wounded in the hospital", "calm_burrow": "keep a tantrum away from the others", "dairy": "milk and cheese", "eggs": "nest boxes for the hens", "war_animals": "train war animals", "gate_guard": "hold the gate", "gate_dogs": "war dogs at the gate", "gem_cutting": "cut the rough gems", "stairwell": "a new stairwell", "animal_trainer": "an animal trainer", "nest_box_order": "make nest boxes", "library_chest": "a chest for the library", "orphan_jobs": "clear jobs whose order is gone", "slabs_free": "free the memorial slabs", "water_traffic": "keep paths off the ice", "jail_size": "a bigger jail", "jail_more": "another jail", "break_fights": "break up the fights among the fort's own", "burial": "bury the dead", "rooms": "mend the rooms' walls", "coffins": "coffins for the tombs", "order_slots": "free the workshop's order slots", "fat_ban": "keep fat for soap", "jail_urgent": "a jail against the beatings", "tavern_urgent": "a tavern for company", "quarry": "quarry stone", "cloth": "weave cloth",
}
AGENDA_THEMES["vermin"] = "keep cats against the vermin"     # (0.104.168)
AGENDA_THEMES["food_store"] = AGENDA_THEMES["food_barrels"] = AGENDA_THEMES["food_store_level"] = "keep the food from rotting"   # (0.105.40b)
AGENDA_THEMES["artifact_display"] = AGENDA_THEMES["artifact_furniture"] = AGENDA_THEMES["artifact_pedestals"] = "show the fort's artifacts"   # (item 12)
AGENDA_THEMES["traction_rest"] = "care for the injured"       # (0.105.24)

AGENDA_THEMES["cups_home"] = "shoes and cups for the fort"      # (0.104.168)

AGENDA_THEMES.update({"soap_rush": "make soap", "infected_rest": "care for the infected",   # (0.104.168)
                      "doctor_post": "more doctors"})
AGENDA_THEMES.update({"booze_variety": "drinks of more kinds", "mood": "materials for a strange mood"})   # (0.105.24)


def agenda(proposals: list, notes: list, limit: int = 5) -> list[str]:
    """The season's goals: what the most urgent proposals work toward (by
    rule, most urgent first, each once), then what the player is asked."""
    out = []
    for p in sorted(proposals, key=lambda p: p.priority):
        theme = AGENDA_THEMES.get(p.rule)
        if theme and theme not in out:
            out.append(theme)
        if len(out) >= limit:
            break
    asks = [n[6:].split(":")[0] for n in notes if isinstance(n, str) and n.startswith("[you] ")]
    if asks and len(out) < limit:
        out.append("ask you: " + asks[0][:60])
    return out


def food_per_dwarf(s: dict) -> float:
    """Meals and raw food (meat, fish, plants, fruit and leaves, cheese,
    eggs) a dwarf. (0.39.0 read 'meals', which the bridge doesn't send: meals
    never counted, so the fort always looked hungry and kept gathering.)"""
    st = _d(s.get("stocks"))
    citizens = max(1, _d(s.get("dwarves")).get("total", 0) or 0)
    total = sum(int(st.get(k, 0) or 0) for k in ALL_FOOD)
    return round(total / citizens, 1)


WINTER_STOCK = {"autumn": 1.5, "winter": 1.25}     # food and drink kept, x the usual


def winter_factor(s: dict, memory=None) -> float:
    """Food and drink are stocked up in autumn (crops stop, water may freeze)
    and kept higher through winter; more where the water freezes."""
    season = _d(s.get("date")).get("season")
    f = WINTER_STOCK.get(season, 1.0)
    # (0.103) a Frozen Hold lays in its winter stores from midsummer
    if season == "summer" and memory is not None and has_rule(getattr(memory, "culture", None), "early_winter_stores"):
        f = WINTER_STOCK["winter"]
    if f > 1 and memory is not None and getattr(memory, "climate_freezes", False):
        f += 0.25
    return f


def young_fort(s: dict, cfg: dict) -> bool:
    """A young fort: few dwarves and food not yet secure (food first, small
    and plain). A small fort that is fed (farms, food and drink well in hand)
    is not young however few its dwarves: 0.44's fort sat at 18 dwarves for a
    year, "young" all that time, so it made no crafts to sell, its wealth
    stayed low and no migrants came."""
    pop = _d(s.get("dwarves")).get("total", 0) or 0
    if not 0 < pop < cfg["young_fort"]:
        return False
    return not established(s, cfg)


def established(s: dict, cfg: dict) -> bool:
    """Farms, and food and drink well in hand for every dwarf."""
    pop = max(1, _d(s.get("dwarves")).get("total", 0) or 0)
    drink = (_d(s.get("stocks")).get("drink") or 0) / pop
    return (has_farms(s) and food_per_dwarf(s) >= cfg["established_food_per_dwarf"]
            and drink >= cfg["established_drink_per_dwarf"])


def has_farms(s: dict) -> bool:
    built = _d(_d(s.get("buildings")).get("other")).get("FarmPlot", 0)
    return bool(built or _d(s.get("farms")).get("plots"))


def _best_metal(s: dict, items: int, wanted: str | None = None) -> str | None:
    """INORGANIC:<metal> for gear: the mandate's own metal if named, else the
    best weapon-grade metal with enough bars (2 per item, to be safe)."""
    if wanted and str(wanted).startswith("INORGANIC:"):
        return wanted
    bars = _d(_d(_d(s.get("military")).get("gear")).get("bars"))
    m = next((x for x in GEAR_METALS if (bars.get(x) or 0) >= 2 * items), None)
    return f"INORGANIC:{m}" if m else None


# One back-off for everything the game refuses: the same action refused
# again waits twice as long each time (1 day, 2, 4 ... up to 4 weeks), and a
# success clears it. Responses to an attack never wait.
REFUSAL_FIRST_DAYS = 1
REFUSAL_MAX_DAYS = 84                # (the overnight run: a spot that never fits was asked about every 28 days)
REFUSAL_IDLE_DAYS = 336              # (0.104.138) refused as nothing to do (every chair paired, all water restricted)
REFUSAL_KEYS = ("type", "kind", "recipe", "job", "entrance_id", "project_id", "name", "squad_id",
                "lever_id", "target_id", "tool", "unit_id",      # (0.103.12) unit_id: one dwarf's refusal isn't another's
                "zone_id", "order_id", "location_id",            # (0.104.81) nor one zone's, order's or location's
                "building_id",                                   # (0.104.138) nor one workshop's feeder another's
                "accept",                                        # (0.105.9) declining isn't agreeing
                "pile_id")                                       # (0.105.41, item 2) nor one pile's barrows or link another's


# (v35 fix) labour rules that add dwarves every cooldown while their need
# lasts: each gives at most its config key's dwarves in a game year
LABOR_CAPS = {"care_feed": "care_feed_labor_cap", "care_clean": "care_clean_labor_cap",
              "care_diagnose": "care_diagnose_labor_cap", "ghost_mason": "ghost_mason_labor_cap",
              "waterworks_pump_labor": "pump_labor_cap"}


def labor_given(memory, rule: str, now: int) -> int:
    """(v35 fix) Dwarves the AI gave this rule's labour in the last game year."""
    rows = _l(_d(getattr(memory, "labor_given", None)).get(rule))
    return sum(int(r[1]) for r in rows if isinstance(r, list) and len(r) == 2 and isinstance(r[0], int)
               and isinstance(r[1], int) and 0 <= now - r[0] < TICKS_PER_YEAR)


def note_labor_given(memory, p, r: dict, now: int) -> None:
    """(v35 fix) A LABOR_CAPS rule's labour given: booked (the dwarves named,
    else the count asked). (0.105.36) An unknown answer (ok None: a timeout
    that may have gone through) books the count asked, to be safe against
    passing the yearly cap, as the cooldown does."""
    ok = _d(r).get("ok")
    if p.rule not in LABOR_CAPS or _d(p.action).get("type") != "assign_labor" or ok is False:
        return
    names = _d(r).get("assigned") if ok is True else None
    n = len(names) if isinstance(names, list) else int(_d(p.action).get("count") or 0)
    if n <= 0:
        return
    if not isinstance(getattr(memory, "labor_given", None), dict):
        memory.labor_given = {}
    rows = [x for x in _l(memory.labor_given.get(p.rule)) if isinstance(x, list) and len(x) == 2
            and isinstance(x[0], int) and 0 <= now - x[0] < TICKS_PER_YEAR]
    memory.labor_given[p.rule] = rows + [[now, n]]


# (v35 fix) actions whose "id" names one entrance: one entrance's refusal (the
# cavern seal, an enemy near it) isn't another's
REFUSAL_ID_TYPES = ("open_entrance",)
# (v35 fix) rules whose proposals for different entrances each keep their own
# cooldown (and may act for several entrances in one cycle)
PER_ID_COOLDOWN = {"stranded"}


def refusal_key(p: Proposal) -> str:
    a = _d(p.action)
    keys = REFUSAL_KEYS + (("id",) if a.get("type") in REFUSAL_ID_TYPES else ())
    return p.rule + ":" + json.dumps({k: a.get(k) for k in keys if k in a}, sort_keys=True)


def cooldown_key(p: Proposal) -> str:
    """(v35 fix) The key of p's cooldown in memory.last_fired: its rule, or for
    a PER_ID_COOLDOWN rule's action on one entrance, the rule and that id."""
    a = _d(getattr(p, "action", None))
    if p.rule in PER_ID_COOLDOWN and a.get("id") is not None:
        return f"{p.rule}:{a['id']}"
    return p.rule


# (0.105.36) actions whose rule paces its own tries after a refusal: no
# refusal back-off on top (the shelter's "tried again in 1 day(s)" stretched
# to weeks under a siege: SHELTER_RETRY_*_DAYS is its pace)
OWN_PACE = {"setup_shelter"}


def _refused_wait(memory: Memory, p: Proposal, now: int, bridge: str | None = None) -> int | None:
    """Days left before a refused action may be tried again, or None. A
    refusal booked under another bridge version is tried again at once: new
    code may do what the old couldn't (0.81: squads refused for want of a
    captain's post waited up to 84 days after the bridge learned to add one)."""
    if p.rule in EMERGENCY or p.action.get("type") in OWN_PACE:
        return None
    r = _d((memory.refusals or {}).get(refusal_key(p)))
    if bridge and r and r.get("v") != bridge:   # (refusals from before 0.81 carry no version: once more)
        return None
    until = r.get("until")
    if isinstance(until, int) and 0 <= now < until:
        return max(1, -(-(until - now) // TICKS_PER_DAY))
    return None


# (0.105.26) a search the bridge cut short (timed_out in its answer: no spot
# found in the time it had, not "there is none") is tried again in a day or
# two, with no back-off and no "could not be placed" in Needs you, this many
# times in a row; then it counts as a refusal (the cistern's always times out)
TIMEOUT_TRIES = 3


def timeout_streak(memory, key: str) -> int:
    """(0.105.26) How many searches in a row under this refusal key were cut
    short before this one."""
    return int(_d(_d(getattr(memory, "refusals", None)).get(key)).get("t") or 0)


def brief_timeout(memory, p: Proposal, r: dict) -> bool:
    """(0.105.26) A search cut short that is still to be tried again soon: not
    a lasting failure (see TIMEOUT_TRIES)."""
    return (r.get("ok") is False and bool(r.get("timed_out"))
            and timeout_streak(memory, refusal_key(p)) + 1 < TIMEOUT_TRIES)


def note_refusal(memory: Memory, p: Proposal, r: dict, now: int, bridge: str | None = None) -> None:
    """Book a refusal (or clear the count after a success), with the bridge
    version that refused it."""
    if not isinstance(memory.refusals, dict):
        memory.refusals = {}
    key = refusal_key(p)
    if r.get("ok") is True and p.action.get("type") == "polish" and r.get("designated") == 0:
        r = {"ok": False, "error": r.get("note") or "nothing to smooth or engrave"}   # nothing done: back off
    if r.get("ok") is True:
        # (0.104.138) a success halves the count rather than wiping it: one
        # success among many refusals began the back-off again at a day
        old = _d(memory.refusals.get(key))
        if int(old.get("n") or 0) >= 3:
            memory.refusals[key] = {k: v for k, v in dict(old, n=int(old["n"]) // 2, until=now).items()
                                    if k not in ("why", "t")}
        else:
            memory.refusals.pop(key, None)
        return
    if r.get("ok") is not False or r.get("halted") or p.rule in EMERGENCY or p.action.get("type") in OWN_PACE:
        return                     # unknown, or stopped by the in-game halt: not the game saying no
    if r.get("waiting"):           # work under way (trees being felled): look again in 2 days, no back-off
        memory.refusals[key] = {"n": 0, "until": now + 2 * TICKS_PER_DAY, "at": now,
                                "why": str(r.get("error") or "")[:120]}
        if bridge:
            memory.refusals[key]["v"] = str(bridge)
        return
    old = _d(memory.refusals.get(key))
    if r.get("timed_out"):
        # (0.105.26) a search cut short: again in a day or two, no back-off,
        # TIMEOUT_TRIES times in a row (one timed-out well search began an
        # 84-day back-off and said "no well could be placed")
        t = int(old.get("t") or 0) + 1
        if t < TIMEOUT_TRIES:
            memory.refusals[key] = {"n": int(old.get("n") or 0), "t": t, "at": now,
                                    "until": now + min(2, t) * TICKS_PER_DAY,
                                    "why": ("search cut short: " + str(r.get("error") or ""))[:120]}
            if bridge:
                memory.refusals[key]["v"] = str(bridge)
            return
    n = int(old.get("n") or 0) + 1
    days = min(REFUSAL_MAX_DAYS, REFUSAL_FIRST_DAYS * 2 ** (n - 1))
    if r.get("nothing_to_do"):
        days = REFUSAL_IDLE_DAYS   # (0.104.138) the goal is met: a year, not a loop
    if p.action.get("type") == "squad_release" and "longs to fight or train" in str(r.get("error") or ""):
        days = max(days, 56)       # (0.104.34) a need that lasts: Enxah asked 368 times, 10 dwarves, all refused
    memory.refusals[key] = {"n": n, "until": now + days * TICKS_PER_DAY, "at": now,
                            "why": str(r.get("error") or "")[:120]}
    if r.get("timed_out"):
        memory.refusals[key]["t"] = int(old.get("t") or 0) + 1   # still cut short: the streak goes on
    if bridge:
        memory.refusals[key]["v"] = str(bridge)
    # forget refusals nothing has asked about for two months
    # (0.104.38) but not one still waiting out its back-off: a 56-84 day wait
    # was forgotten at 60 and began again at 1 day (feeder piles refused 120
    # times overnight, squad releases 78)
    for k in [k for k, v in memory.refusals.items()
              if not isinstance(v, dict) or not isinstance(v.get("at"), int)
              or (now - v["at"] > 60 * TICKS_PER_DAY
                  and not (isinstance(v.get("until"), int) and now < v["until"] + 30 * TICKS_PER_DAY))]:
        memory.refusals.pop(k, None)


# the same action (refusal_key) this many times in a game year looks like a
# loop (the soak run: 125 soap-maker levels, 184 meal orders): held a while.
# Rules that repeat by design aren't counted.
LOOP_LIMITS = {"start_project": 12, "place_surface": 12, "place_well": 12, "make_pasture": 20,
               "deep_depot": 12,                                # (0.105.23) the underground depot's road
               "dismiss_alerts": 400, "answer_petition": 400}   # (0.105.9) residency batches by the hundred
LOOP_LIMIT_DEFAULT = 80
LOOP_EXEMPT = {"entrances", "needs_trinkets", "trinket_orders", "excess_shops", "cistern", "call_trader", "open_trade",
               "trade_deal", "close_trade", "trade", "train", "water", "project"}


def _loop_count(memory: Memory, p: Proposal, now: int) -> int | None:
    """How often this action was done in the last game year, when that is
    over its limit and it was done again recently (else None)."""
    if p.rule in LOOP_EXEMPT or (p.rule in EMERGENCY and not getattr(p, "guard", False)):
        return None
    log = (getattr(memory, "action_log", None) or {}).get(refusal_key(p)) or []
    recent = [t for t in log if isinstance(t, int) and 0 <= now - t < TICKS_PER_YEAR]
    limit = LOOP_LIMITS.get(str(p.action.get("type")), LOOP_LIMIT_DEFAULT)
    if len(recent) >= limit and recent and now - max(recent) < PLANNER_CONFIG["loop_hold_days"] * TICKS_PER_DAY:
        return len(recent)
    return None


# (0.105.24) Rules whose action can succeed without changing what asked for
# it: a crossbow made that never reaches the squad, a quiver handed out that
# the game takes back. Done no_effect_max times in a row for the very same
# reason (the same counts in its words), the rule waits no_effect_hold_days,
# then tries once more. C (2-5 Nov) ordered a crossbow every week for 35 game
# years, "4 crossbow soldiers and 3 with a crossbow" each time (962 orders);
# F gave the same one quiver 171 times ("1 without a quiver and 1 free").
NO_EFFECT_RULES = {"arms", "quivers"}
NO_EFFECT_WHY = {"arms": "the crossbows made don't reach the crossbow squad (a hunter may take them, or the "
                         "uniform asks for another kind): look in the game",
                 "quivers": "the quiver handed out doesn't stay with the soldier (the game takes it back): "
                            "look in the game"}


def note_no_effect(memory: Memory, p: Proposal, ok, now: int) -> None:
    """(0.105.24) Count a done action of a NO_EFFECT_RULES rule: again for the
    same reason, or a new count."""
    if p.rule not in NO_EFFECT_RULES or ok is not True:
        return
    if not isinstance(getattr(memory, "no_effect", None), dict):
        memory.no_effect = {}
    k = refusal_key(p)
    old = _d(memory.no_effect.get(k))
    n = int(old.get("n") or 0) + 1 if old.get("reason") == p.reason else 1
    memory.no_effect[k] = {"reason": p.reason, "n": n, "tick": now}
    if len(memory.no_effect) > 40:
        for kk in sorted(memory.no_effect, key=lambda x: int(_d(memory.no_effect[x]).get("tick") or 0))[:-40]:
            del memory.no_effect[kk]


def no_effect_wait(memory: Memory, p: Proposal, now: int, cfg: dict = PLANNER_CONFIG) -> int | None:
    """(0.105.24) Days left to wait when this action was done no_effect_max
    times in a row for this same reason (else None)."""
    if p.rule not in NO_EFFECT_RULES:
        return None
    r = _d(_d(getattr(memory, "no_effect", None)).get(refusal_key(p)))
    most = cfg.get("no_effect_max", PLANNER_CONFIG["no_effect_max"])
    if r.get("reason") != p.reason or int(r.get("n") or 0) < most or not isinstance(r.get("tick"), int):
        return None
    left = r["tick"] + cfg.get("no_effect_hold_days", PLANNER_CONFIG["no_effect_hold_days"]) * TICKS_PER_DAY - now
    return max(1, -(-left // TICKS_PER_DAY)) if 0 < left else None


def _stalled_days(memory: Memory, recipe: str, now: int) -> int | None:
    """Days the AI's longest-waiting order of this recipe has stood still (None: no
    unfinished AI order of it). More copies of an order that doesn't move only
    pile up (0.75 overnight prep: drink orders were placed and cancelled as stuck
    in turn, all evening)."""
    best = None
    for w in (getattr(memory, "order_watch", None) or {}).values():
        if (isinstance(w, dict) and w.get("by_ai") and str(w.get("what")) == recipe
                and isinstance(w.get("since"), int) and (w.get("left") or 0) > 0):
            days = max(0, (now - watch_since(w)) // TICKS_PER_DAY)
            best = days if best is None else max(best, days)
    return best


def _entrance_spot(state: dict, entrance_id) -> str | None:
    for e in _l(_d(state.get("entrances")).get("entrances")):
        if isinstance(e, dict) and e.get("id") == entrance_id:
            return f"{e.get('x')},{e.get('y')},{e.get('z')}"
    return None


def _record_any_outcome(a: dict, r: dict, state: dict, memory, now: int, brief: bool = False) -> None:
    """Bookkeeping that holds whether the action worked or was refused, so a
    refusal is never simply asked again every cycle. brief (0.105.26): a
    search the bridge cut short, to be tried again in a day or two (see
    TIMEOUT_TRIES): no failure booked for Needs you, the rule's wait short."""
    t = a.get("type")
    if brief:
        rule_ = {"make_pasture": "new_pasture", "farm_plots": "farms", "found_fort": "found"}.get(
            t, "extra_well" if t == "place_well" and a.get("extra") else "well" if t == "place_well" else None)
        if rule_:
            cd = PLANNER_CONFIG.get(f"{rule_}_cooldown_ticks", PLANNER_CONFIG["rule_cooldown_ticks"])
            memory.last_fired[rule_] = now - max(0, cd - TICKS_PER_DAY)       # again in a day
        if t == "farm_plots":
            memory.farm_failure_tick = now - max(0, PLANNER_CONFIG["farm_dig_retry_days"] - 1) * TICKS_PER_DAY
        if t in ("make_pasture", "place_well", "farm_plots", "found_fort"):
            return
    if t == "clear_gate" and r.get("ok") is False and isinstance(a.get("spot"), str):
        # nothing left, or the game says it's real: don't ask again
        reg = _d(_d(memory.atlas).get("registry"))
        for prefix in ("gate:", "doors:"):
            rec = reg.get(prefix + a["spot"])
            if isinstance(rec, dict):
                rec["status"] = "taken down" if "nothing" in str(r.get("error")) else "kept"
    # (0.105.36, D5) what the AI shelter holds, from each fill of it (made,
    # made again, or made again as the AI sounds the alarm): read by
    # planner_society's _shelter_supply_rule
    sh = r if t in ("setup_shelter", "refresh_shelter") else (
        r.get("shelter") if t == "civ_alert" and a.get("on") is True else None)
    if isinstance(sh, dict) and sh.get("ok") is not False and isinstance(sh.get("tiles"), int):
        memory.shelter_supply = {"tick": now, "tiles": sh["tiles"],
                                 **{k: sh[k] for k in ("drink_short", "no_water", "no_food", "drink_units",
                                                       "food_units", "well_tiles") if sh.get(k) is not None}}
    # (0.105.36 fix) the alarm's burrow isn't the AI shelter (the player set
    # their own): its fill record forgotten (the AI no longer fills it)
    if t == "refresh_shelter" and r.get("ok") is False and "not the AI shelter" in str(r.get("error") or ""):
        memory.shelter_supply = {}
    if t == "setup_shelter":
        memory.shelter_attempts += 1          # refused or not: two tries, then again after a wait (0.105.35)
        memory.shelter_tick = now
        if r.get("ok") is True:
            # (0.105.36) one that worked isn't a refusal: two good set-ups over a
            # fort's life (the player removed one) read as "refused twice"
            memory.shelter_attempts = 0
    elif t == "scan_entrances":
        memory.rescan_entrances = False
    elif t == "expel_dwarf":
        memory.last_expel_tick = now             # refused or not: wait the full spell
    elif t == "census":
        if r.get("ok"):
            memory.census = {"tick": now, "units": _d(r.get("units")), "items": _d(r.get("items")),
                             "jobs": r.get("jobs")}
    elif t == "join_levels":
        # (0.104.108) a corridor dug: look again soon; every level seen and
        # nothing to join: wait a fortnight (new levels come slowly)
        memory.last_join_tick = now
        memory.join_wait_days = 2 if r.get("joined") or r.get("widened") or not r.get("wrapped") else 14
    elif t == "make_pasture":
        memory.last_fired["new_pasture"] = now   # refused or not: wait the full spell
        if r.get("ok") is True:
            memory.pasture_failure = ""
        elif r.get("ok") is False and not r.get("rejected"):
            memory.pasture_failure = str(r.get("error") or "refused")[:300]
    elif t == "place_well" and a.get("extra"):
        # (0.104.141) another well beside one standing: its failure never says
        # "no well can be placed" (the cavern well and Needs you hang on that)
        memory.last_fired["extra_well"] = now
        if r.get("ok") is True:
            memory.extra_well_failure = ""
        elif r.get("ok") is False:
            memory.extra_well_failure = str(r.get("error") or "refused")[:300]
    elif t == "place_well":
        memory.last_fired["well"] = now          # refused or not: wait the full spell
        if a.get("cavern"):
            # (0.105.4 review) a cavern well tried with a gallery: the old refusal's one retry is spent
            if a.get("gallery"):
                memory.cavern_gallery_retried = True
            if r.get("ok") is False and not r.get("rejected"):
                memory.cavern_well_failure = str(r.get("error") or "refused")[:300]
            elif r.get("ok") is True:
                memory.cavern_well_failure = ""
        elif r.get("ok") is True:
            memory.well_failure = ""
        elif r.get("ok") is False and not r.get("rejected"):
            memory.well_failure = str(r.get("error") or "refused")[:300]
    elif t == "furnish_project" and r.get("ok") is False and "well" in str(r.get("error") or ""):
        # (0.105.24) a well the game refused that the bridge tries again (a
        # floor dug beside it, or a day later) is not "no well can be placed"
        if not r.get("retry"):
            memory.well_failure = str(r.get("error"))[:300]
            # (0.105.36) the well_retry_days wait counts from this refusal (the
            # dig may have taken longer than the wait), not from the place_well
            memory.last_fired["well"] = now
    elif t == "farm_plots":
        memory.last_fired["farms"] = now         # refused or not: wait the full spell
        if r.get("ok") is True:
            memory.farm_failure = ""
        elif r.get("ok") is False:
            # nothing placed: not tried again for a while (see _farm_rule); and
            # when no farm level could be dug either, it's shown under Needs you
            memory.farm_failure_tick = now
            if a.get("dig"):
                memory.farm_failure = str(r.get("error") or "refused")[:300]
            else:
                # (0.100.1, review) only plots were tried (no farm level: before
                # the first staircase, or the surface farm): again in 3 days,
                # not the 4 weeks a level that couldn't be dug waits
                memory.farm_failure_tick = now - max(0, PLANNER_CONFIG["farm_dig_retry_days"] - 3) * TICKS_PER_DAY
    elif t == "found_fort":
        if r.get("ok") is True:
            memory.found_failure = memory.found_wide_failure = ""
        elif r.get("ok") is False and not r.get("rejected"):
            # (0.105.35) a refusal near the wagon is tried further out (wide); only
            # a wide refusal is Needs you
            if a.get("wide"):
                # (v35 nit) a search that ran out of time isn't "no spot further out"
                if not r.get("timed_out"):
                    memory.found_wide_failure = str(r.get("error") or "refused")[:300]
            else:
                memory.found_failure = str(r.get("error") or "refused")[:300]
    elif t == "place_traps":
        spot = _entrance_spot(state, a.get("entrance_id"))
        if spot and r.get("ok") is None:
            # no answer: they may be placed; not asked again for 2 weeks (never twice at once)
            memory.gate_failures["traps:" + spot] = "no answer from the game; looked at again later"
            memory.gate_failure_ticks["traps:" + spot] = now
        elif spot and r.get("ok") is False:
            memory.gate_failures["traps:" + spot] = str(r.get("error") or "refused")[:300]
            memory.gate_failure_ticks["traps:" + spot] = now
        elif spot:
            memory.gate_failures.pop("traps:" + spot, None)
            memory.gate_failure_ticks.pop("traps:" + spot, None)
    elif t == "build_gatehouse" and not a.get("dry_run"):
        # (0.105.23) built once at a spot: never again there (a second would
        # stand beside the first); a refusal waits gate_retry_ticks
        spot = _entrance_spot(state, a.get("entrance_id"))
        if spot and r.get("ok") is True:
            memory.gatehouses[spot] = {"tick": now, "bridge": r.get("bridge"), "dir": r.get("dir")}
            memory.gate_failures.pop("gatehouse:" + spot, None)
            memory.gate_failure_ticks.pop("gatehouse:" + spot, None)
        elif spot:
            memory.gate_failures["gatehouse:" + spot] = str(r.get("error") or "no answer from the game")[:300]
            memory.gate_failure_ticks["gatehouse:" + spot] = now
    elif t == "link_lever" and not a.get("dry_run"):
        key = f"lever:{a.get('lever_id')}>{a.get('target_id')}"
        if r.get("ok") is False:
            memory.gate_failures[key] = str(r.get("error") or "refused")[:300]
            memory.gate_failure_ticks[key] = now
        else:
            memory.gate_failures.pop(key, None)
            memory.gate_failure_ticks.pop(key, None)
            memory.rescan_entrances = True        # the link shows in the next scan once it's made
    elif t in ("build_gate_doors", "fortify_entrance", "cut_entrance"):   # (0.105.0 cut_entrance)
        spot = _entrance_spot(state, a.get("entrance_id"))
        if not spot:
            return
        if t == "cut_entrance":
            # (0.105.0 review) the cut's refusal under its own key: the wall's
            # refusal (why the cut was tried) is kept, not overwritten
            if a.get("dry_run"):
                return
            if r.get("ok") is False:
                memory.gate_failures["cut:" + spot] = str(r.get("error") or "refused")[:400]
                memory.gate_failure_ticks["cut:" + spot] = now
                return
            memory.gate_failures.pop("cut:" + spot, None)
            memory.gate_failure_ticks.pop("cut:" + spot, None)
        if r.get("ok") is False:
            # refused: remembered with the game's reason (shown under Needs you)
            # and when, so it's tried again later
            memory.gate_failures[spot] = str(r.get("error") or "refused")[:400]
            memory.gate_failure_ticks[spot] = now
        else:
            memory.gate_failures.pop(spot, None)        # worked this time
            memory.gate_failure_ticks.pop(spot, None)
            if t == "build_gate_doors":
                if spot not in memory.gate_doors_requested:
                    memory.gate_doors_requested.append(spot)
            else:
                if r.get("water_gate"):
                    # deep water is the gate: nothing to build. Looked at again
                    # each season (water freezes, dries, rises)
                    memory.gates_fortified[spot] = f"water@{now}"
                else:
                    memory.gates_fortified[spot] = (r.get("style") or a.get("style") or "plain") + (
                        ", doors later" if r.get("doors_later") or r.get("support_walls") else "")
                    memory.gates_fortified_ticks[spot] = now


def spare_sig(gear: dict) -> str:
    """(0.104.138) The spare gear counts, as one string to compare."""
    return json.dumps(sorted((str(k), v) for k, v in _d(gear.get("spare")).items()))


def _weapon_gaps(gear: dict) -> bool:
    """(0.104.60) Soldiers on duty with places whose weapon entry is empty
    while free weapons (or crossbows) lie on the game's unassigned list."""
    free_w = (sum(int(v or 0) for k, v in _d(gear.get("spare_weapons")).items()
                  if isinstance(v, (int, float)) and k != "ITEM_WEAPON_PICK")      # a pick is a miner's tool
              + int(gear.get("spare_crossbows") or 0))
    if isinstance(gear.get("weapon_gaps_fillable"), int) and gear["weapon_gaps_fillable"] <= 0:
        return False                 # (0.104.138) the bridge's own dry run fills none
    return int(gear.get("weapon_gaps") or 0) > 0 and free_w > 0 and int(gear.get("on_duty") or 0) > 0
