"""planner_core: part of the planner (split out of planner.py in 0.104.83; see planner.py)."""

from __future__ import annotations
import json
import math
from dataclasses import asdict, dataclass, field
from quirks import has_rule
from digest import _d, _l, normalize
from planner_config import PLANNER_CONFIG, DISPOSAL_ACTION_MAX  # noqa: F401  (13c: the tuning numbers, split out)

__all__ = ["great_present", "all_clear", "STEER_PROTECTED", "STEER_MAX_DAYS", "steer_of", "PLANNER_CONFIG", "BREW_RECIPES", "MEAL_RECIPES", "MANDATE_RECIPES", "BUILDABLE_SHOPS", "SHOP_ALIASES", "SURVIVAL_SHOPS", "TICKS_PER_DAY", "TICKS_PER_YEAR", "NO_COOLDOWN", "COOLDOWN_KEYS", "MULTI_PER_CYCLE", "EMERGENCY", "STUCK_HOLD_EXEMPT", "ORDER_HOLD_EXEMPT", "LIMIT_EXEMPT", "emergency", "limit_exempt", "steer_protected", "Proposal", "Memory", "abs_tick", "stamp_tick", "game_day", "factor", "ADJUST_BOUNDS", "_number", "effective_config", "queued", "unstored_cups", "free_stock", "watch_since", "stuck_days", "supply_order_kept", "_clamp", "MEMORIAL_SPAN", "OPTIONAL_LEVELS", "GEAR_WEAPONS", "GEAR_METALS", "NEEDS_YOU", "ask_player", "DISPOSAL_LEVELS", "DISPOSAL_ACTION_MAX", "player_rules", "OPEN_CAVERNS_MODES", "open_caverns_mode", "MAINTAIN_SKIPS", "level_refused", "_traits", "reachable_threats", "held_off_threats", "_holding_off", "ONE_A_CYCLE", "growth_mode", "growth_target", "JOB_SHOPS", "RECIPE_SHOPS", "WOOD_ELSEWHERE", "recipe_shop", "brewable_counts", "brew_recipe", "_watchdog_notes", "jobs_reported", "order_job_state", "masons_jammed", "stuck_hold_days", "_stuck_before", "stone_short", "_office_held", "tantrums_recent", "justice_held", "_restraint_order", "manager_needs_office", "suites_short", "wool_route", "thread_plants_here", "MINING_NEED_ONLY", "mining_plan", "noble_room_kinds", "SOCIAL_NEEDS", "care_waiting", "unmet", "_soldier_swap", "recently_home", "LOCATION_UNITS", "_location", "_location_short", "_real_locations", "can_fight", "is_ranged", "STALE_PROJECT_DAYS", "_workshops_busy", "shop_count", "shops_max", "_has_shop", "RAW_FOOD", "ALL_FOOD", "_idle_share", "idle_line", "IDLE_OLD_LINES", "levels_done", "_lever_state", "update_idle", "AGENDA_THEMES", "agenda", "food_per_dwarf", "WINTER_STOCK", "winter_factor", "young_fort", "established", "has_farms", "_best_metal", "REFUSAL_FIRST_DAYS", "REFUSAL_MAX_DAYS", "REFUSAL_IDLE_DAYS", "REFUSAL_KEYS", "LABOR_CAPS", "labor_given", "note_labor_given", "REFUSAL_ID_TYPES", "PER_ID_COOLDOWN", "refusal_key", "cooldown_key", "_refused_wait", "note_refusal", "zone_full_days", "note_zone_full", "ZONE_FULL_FIRST_DAYS", "ZONE_FULL_MAX_DAYS", "TIMEOUT_TRIES", "timeout_streak", "brief_timeout", "LOOP_LIMITS", "LOOP_LIMIT_DEFAULT", "LOOP_EXEMPT", "_loop_count", "NO_EFFECT_RULES", "NO_EFFECT_WHY", "note_no_effect", "no_effect_wait", "_stalled_days", "_entrance_spot", "_record_any_outcome", "_weapon_gaps", "spare_sig", "MOOD_BODY_FLAGS", "mood_kind", "mood_on_hand", "mood_waits", "_stuck_again_rule", "wildlife_threat", "wildlife_threats", "wild_rows", "wild_pack", "thief_ids", "snatcher_ids", "GREAT_LIKE_KINDS", "is_release", "thief_rows", "crowded_thief", "CROWD_LOCATIONS"]

# (r7) the rule groups and helpers live in their own parts; every name is re-exported here
# (Proposal and Memory stay: saved memory and memstore name them here; so do the three rules that build Proposals)
from planner_core_base import (BREW_RECIPES, MEAL_RECIPES, MANDATE_RECIPES, BUILDABLE_SHOPS, SHOP_ALIASES,
    SURVIVAL_SHOPS, TICKS_PER_DAY, TICKS_PER_YEAR, NO_COOLDOWN, COOLDOWN_KEYS, MULTI_PER_CYCLE, EMERGENCY,
    STEER_PROTECTED, STEER_MAX_DAYS, steer_of, STUCK_HOLD_EXEMPT, ORDER_HOLD_EXEMPT, LIMIT_EXEMPT, emergency,
    limit_exempt, steer_protected, abs_tick, stamp_tick, game_day, factor, ADJUST_BOUNDS, _number,
    effective_config, unstored_cups, free_stock, queued, WORKED_MAX_DAYS, watch_since, stuck_days,
    supply_order_kept, _clamp, MEMORIAL_SPAN, OPTIONAL_LEVELS, GEAR_WEAPONS, GEAR_METALS)  # noqa: F401
from planner_core_rules import (NEEDS_YOU, ask_player, DISPOSAL_LEVELS, player_rules, OPEN_CAVERNS_MODES,
    open_caverns_mode, MAINTAIN_SKIPS, level_refused, _traits, ONE_A_CYCLE, growth_mode, growth_target,
    MINING_NEED_ONLY, mining_plan, noble_room_kinds)  # noqa: F401
from planner_core_threats import (GREAT_LIKE_KINDS, wildlife_threat, wildlife_threats, _is_cavern, _num_,
    wild_rows, _wild_free_squads, wild_pack, thief_ids, CROWD_LOCATIONS, thief_rows, crowded_thief,
    snatcher_ids, _lone_thieves, reachable_threats, great_present, all_clear, held_off_threats, _holding_off,
    can_fight, is_ranged)  # noqa: F401
from planner_core_fort import (JOB_SHOPS, RECIPE_SHOPS, WOOD_ELSEWHERE, recipe_shop, brewable_counts,
    brew_recipe, _watchdog_notes, jobs_reported, order_job_state, masons_jammed, stuck_hold_days,
    _stuck_before, stone_short, _office_held, tantrums_recent, justice_held, manager_needs_office,
    suites_short, wool_route, MOOD_BODY_FLAGS, mood_kind, mood_on_hand, mood_waits, thread_plants_here,
    SOCIAL_NEEDS, care_waiting, unmet, recently_home, LOCATION_UNITS, _location, _location_short,
    _real_locations, STALE_PROJECT_DAYS, _workshops_busy, shop_count, shops_max, _has_shop, RAW_FOOD, ALL_FOOD,
    _idle_free_known, _idle_share, IDLE_OLD_LINES, idle_line, levels_done, _lever_state, update_idle,
    AGENDA_THEMES, agenda, food_per_dwarf, WINTER_STOCK, winter_factor, young_fort, established, has_farms,
    _best_metal, spare_sig, _weapon_gaps)  # noqa: F401
from planner_core_refusals import (REFUSAL_FIRST_DAYS, REFUSAL_MAX_DAYS, REFUSAL_IDLE_DAYS, REFUSAL_KEYS,
    is_release, LABOR_CAPS, labor_given, note_labor_given, REFUSAL_ID_TYPES, PER_ID_COOLDOWN, _key_value,
    refusal_key, cooldown_key, OWN_PACE, _refused_wait, TIMEOUT_TRIES, timeout_streak, brief_timeout,
    ZONE_FULL_FIRST_DAYS, ZONE_FULL_MAX_DAYS, zone_full_days, note_zone_full, note_refusal, LOOP_LIMITS,
    LOOP_LIMIT_DEFAULT, LOOP_EXEMPT, _loop_count, NO_EFFECT_RULES, NO_EFFECT_WHY, note_no_effect,
    no_effect_wait, _stalled_days)  # noqa: F401
from planner_core_outcomes import (_entrance_spot, _record_any_outcome)  # noqa: F401


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
    # (0.105.48, K6) the cycle's own steps that failed (select, record's hooks, the
    # pre-plan steps): {step: {"n": cycles in a row, "tick", "why"}}; shown as
    # "rule <step> failed" notes (the health check's standing lines) until it runs again
    guard_fails: dict = field(default_factory=dict)
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
    mood_help: dict = field(default_factory=dict)        # (0.105.47, J1) {free_none: {uid: sig}, cap_built: {uid: tick}}: planner_mood_help
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
    drink_cook_ban: bool = False                         # (0.105.113 item10) the AI keeps drink from the cooks
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
    hunt_seen: dict = field(default_factory=dict)        # (0.105.45) {off {target id: {tick, why}}, learned [keys]}: planner_hunt
    polished_upto: int | None = None                     # finished-level count when every level was found polished
    polish_seen: dict = field(default_factory=dict)      # (item7) {n, tick}: "every level polished" refusals in a row, the last one
    quarry_seen: dict = field(default_factory=dict)      # (item7) the last quarry: {tick, tiles, before, settled, strikes, until, why}
    place_full: dict = field(default_factory=dict)       # (item7) "rule:zone" -> {n, until}: a zone with no free floor for a statue
    no_effect: dict = field(default_factory=dict)        # (0.105.24) action key -> {reason, n, tick}: done for the same reason again
    stuck_seen: dict = field(default_factory=dict)       # (0.105.45) the stuck sweep: {items {key: {state, sig, moved, step, at}}, families {fam: [ticks]}, past {kind: n}, tick}
    thirst_book: dict = field(default_factory=dict)      # (0.105.46, I2) the thirst watch: {acted {"action:unit": tick}, told {unit: tick}}
    cook_watch: dict = field(default_factory=dict)       # (0.105.51) {unit, since}: the trainee cook not free to cook since then
    burial_watch: dict = field(default_factory=dict)     # (item8) {since, n}: the fort's own dead lying free in reach with free tombs since then
    near_gates_seen: dict = field(default_factory=dict)  # (0.105.47, I7d) {last: tick a great danger kept the work near the gates, who}
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
    refusal_streaks: dict = field(default_factory=dict)  # (r5 p3) action key -> {n, why, sig, at, until, days, rule, type, say}: the same no in a row (planner_refusal_streak)
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
    cavern_well_failure_at: int | None = None            # (K48-K4) when: tried again well_retry_days later
    filled_well_failure: str = ""                        # (r2 h2) why no winter cistern could be placed
    filled_well_failure_at: int | None = None            # (r2 h2) when: tried again h2_winter_cistern_retry_days later
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
    reserve_process: dict = field(default_factory=dict)  # (item1) the plant-cloth reserve's process_plants orders: {last: [thread, cloth], fruitless, paused_until}
    farm_under_asked: dict = field(default_factory=dict)  # (0.105.7 review) {tick, tiles}: underground plots last laid out
    report_season: str = ""                              # the last season the player's report was written for
    found_failure: str = ""                              # why the first staircase couldn't be dug near the wagon
    found_wide_failure: str = ""                         # (0.105.35) ...nor further out (found_fort wide): Needs you
    shops_held_since: dict = field(default_factory=dict)  # (0.105.35) workshop -> when its "started twice" hold began
    shops_retried: dict = field(default_factory=dict)     # (v35 fix) workshop -> re-starts after the hold (SHOPS_RETRY_MAX)
    fps_cap: int | None = None                           # the population cap held while the game runs slowly
    strain_hold: bool = False                            # (0.104.106) newcomers held while the fort is strained
    strain_cap: int | None = None                        # (0.104.120) the cap held while strained (its size then)
    pop_cap_hold: dict = field(default_factory=dict)     # (r2 h9) {regime: held|open, since, clear_since, unhappy_since, unhappy_spent}
    outside: dict = field(default_factory=dict)          # (r2 h9) the migrant drought and a stuck caravan (brain/planner_outside.py)
    ores_freed: list = field(default_factory=list)       # (0.104.124) ores the masons were given in a crisis
    crisis: dict = field(default_factory=dict)          # (0.104.137) the fort in crisis: since, why
    deaths_seen: list = field(default_factory=list)     # (0.104.137) citizens' deaths (ticks), 12 weeks
    dead_told: list = field(default_factory=list)       # (r5 p2) [unit id, tick] of citizens told dead: a later death of one is a ghost laid to rest
    shaft_beasts: dict = field(default_factory=dict)    # (item16) {beasts {id: {name, layer, seen, ...}}, held {project id: tick}}: the shaft guard's great beasts remembered (planner_shaft_guard)
    crisis_journal: list = field(default_factory=list)  # (r5 p2) crisis mode entered and left, waiting for the journal
    convict_watch: dict = field(default_factory=dict)   # (0.104.138) cases convicted, sentences then, held until
    fight_deaths: list = field(default_factory=list)    # (0.104.139) citizens killed by citizens (ticks), 4 weeks
    gate_part_extra: dict = field(default_factory=dict)   # (0.104.139) stuck entrances given one more part
    pruned_after: int = 0                                 # (0.104.140) the threat tick last cleaned up after
    kill_sent: dict = field(default_factory=dict)        # (0.104.140) squad id -> unit ids last sent after
    kill_sent_at: dict = field(default_factory=dict)     # (v35 fix) squad id -> tick it was last sent (kill_sent)
    labor_given: dict = field(default_factory=dict)      # (v35 fix) rule -> [[tick, dwarves], ...]: labours the AI gave (LABOR_CAPS)
    residency: dict = field(default_factory=dict)        # (0.105.9) {probe: {id, unit, tick}, works: True|False, since}
    petition_orders: dict = field(default_factory=dict)  # (r10 p1) DF's petition standing orders: {set: {kind: 0|1}, at: {kind: tick}, before: {kind: [ids]}, swept: {kind: bool}, yours: {kind: tick}}
    character_projects: list = field(default_factory=list)   # (0.105.10) project ids the AI started as the fort's own
    locations_closed: list = field(default_factory=list)     # (0.105.12) location ids the AI shut to visitors
    gatehouses: dict = field(default_factory=dict)           # (0.105.23) entrance "x,y,z" -> {tick, bridge} built
    construct: dict = field(default_factory=dict)            # (0.105.30) wings built, soil floors done, the hall's block wait
    locations_yours: list = field(default_factory=list)      # (0.105.12) ones the AI shut and you opened: left alone
    locations_yours_at: dict = field(default_factory=dict)   # (0.105.51) location id (str) -> tick it was found yours
    heists: list = field(default_factory=list)               # (0.105.24) [tick, who] artifact heists and visitors' killings
    visitor_shut: dict = field(default_factory=dict)         # (0.105.24) {tick, until, visitors, meetings, unheard}: shut for the mayor
    locations_acted: dict = field(default_factory=dict)      # (0.105.26) location id (str) -> tick the AI last shut or opened it
    intrusion: dict = field(default_factory=dict)            # (0.105.30) {tick, civ, invaders, cleared}: DF's last invasion record
    stranger_shut: dict = field(default_factory=dict)        # (0.105.30) {seen, who}: a stranger last seen seeking a meeting
    artifacts_sought: dict = field(default_factory=dict)     # (r1 g7) artifact name -> tick a spotted hero named it
    artifact_risk: dict = field(default_factory=dict)        # (r1 g7) {seen, n, names} claimed/sought artifacts last seen in the fort, or {clear}
    gate_unstick: dict = field(default_factory=dict)         # (0.105.32) gate piece id (str) -> {step, tick, ok, split_after, done, prevent}
    way_in: dict = field(default_factory=dict)               # (0.105.32) "x,y,z" -> {tick, ok, project_id, why}: ways dug in
    way_out: dict = field(default_factory=dict)              # (0.105.47, J16) {since, cause_tick, cause, tries, last_try, digs, dig_tick}: the fort sealed in
    second_way: dict = field(default_factory=dict)           # (0.105.33) {stranded_ever, tick, ok, project_id, why, done}: a second way to the surface
    gear_spare_since: dict = field(default_factory=dict)  # "weapons"/"body"/"helms" -> when 3+ spares sat unused
    swapped: dict = field(default_factory=dict)  # (0.104.78) unit id -> when the swap sent them home
    drafted: dict = field(default_factory=dict)  # (0.104.138) unit id -> when a fill or swap drafted them
    released: dict = field(default_factory=dict)  # (0.104.164) unit id -> when stress care or a baby sent them home
    never_draft: dict = field(default_factory=dict)  # (0.105.47) unit id -> {at, stress}: stress care sent them home for good (planner_training)
    train_mode: dict = field(default_factory=dict)  # (0.104.168) the rotation's {all: bool, tick: when it changed}
    rested_at: dict = field(default_factory=dict)     # (0.105.99) squad id -> when the AI last sent it off duty (the rotation's rest month)
    leisure_hold: dict = field(default_factory=dict)  # (0.105.97) squad id -> when the rotation first held it off duty for its soldiers' leisure
    keen_lift: dict = field(default_factory=dict)   # (0.104.168) {n, tick}: soldiers wanted raised for the keen in a crisis
    unstick_seen: dict = field(default_factory=dict)   # (0.104.138) the spare gear at the last untangling, times
    steer: dict = field(default_factory=dict)    # (0.104.89) the strategist's raised and held rules: rule -> {mode, until, why}
    strategist_wants: list = field(default_factory=list)   # (0.104.89) report sections it asked to see in full next time
    token_ratio: float = 1.0                     # (0.104.89) a review's real cost against its estimate, learned
    ai_backoff: dict = field(default_factory=dict)   # (r4 k2, B8) a failing backend: {fails, until, wait_days, rate_limited, error}
    maintain_pop: int | None = None                      # Maintain: the population being kept
    last_expel_tick: int | None = None                   # when a dwarf was last sent away
    last_join_tick: int | None = None                    # (0.104.108) when areas on a level were last looked at for joining
    census: dict = field(default_factory=dict)           # (0.104.113) the last census of creatures and items (with "tick")
    fight: dict = field(default_factory=dict)            # (0.104.118) a fight against great dangers under way
    fight_factor: dict = field(default_factory=dict)     # (0.104.118) kind -> how much stronger than estimated (learned)
    shelter_since: dict = field(default_factory=dict)    # (0.105.22) squad id -> tick it took the shelter order
    shelter_rest: dict = field(default_factory=dict)     # (0.105.22) squad id -> tick it may shelter again
    thirst_alarm_off_until: int = 0   # (0.105.52) the AI's alarm let down for the thirsty: not raised before this tick
    shelter_supply: dict = field(default_factory=dict)   # (0.105.36, D5) the AI shelter's last fill: {tick, drink_short, no_water, no_food, ...}
    shelter_hold: dict = field(default_factory=dict)     # (R1 g4) {levels, tick, ids}: the shelter as last seen and since when (planner_shelter: one move a threat)
    fights: list = field(default_factory=list)           # (0.104.118) the last fights: {tick, keys, lost, of}
    called_off: dict = field(default_factory=dict)       # (0.105.26) great danger id -> tick its fight was called off
    recovery: dict = field(default_factory=dict)         # (0.105.46, I4) collapse recovery: {since, why, floor, peak, weeks, last_rise, calls, journal} (planner_recovery)
    tantrum_book: dict = field(default_factory=dict)     # (0.105.47) {breaks: [ticks of tantrum/berserk/possession reports], loose_last: tick} (planner_tantrums)
    killer_book: dict = field(default_factory=dict)      # (0.105.112) {kills: {uid: {last, name}}, attacks: {uid: [ticks]}}: citizens who killed or attacked citizens (planner_killers)
    welfare: dict = field(default_factory=dict)          # (0.105.47, I7b) {short_since: tick the dead first outnumbered the free tombs} (planner_welfare)
    beast_hunt: dict = field(default_factory=dict)       # (0.105.54) the cavern beast's kill plan: {id, name, tactic, goal, stage, since, opened, retry, squads} (planner_threats)
    lure: dict = field(default_factory=dict)             # (0.105.45) opening "x,y,z" -> {tries, opened, next_try, caught, phase}: the lure pockets (planner_lure)
    holdfast: dict = field(default_factory=dict)         # (0.105.47, R2 item 7) {kill, guards, named, walls}: planner_holdfast
    defence_floor: dict = field(default_factory=dict)    # (0.105.54) {peak {power, tick, why}}: the biggest threat seen (planner_defence_floor)
    ranged_need: dict = field(default_factory=dict)      # (r2h4) {tick, why}: a fire breather or a flier was met (crossbows wanted: planner_military)
    order_loop: dict = field(default_factory=dict)       # (0.105.46, I3) {misses: {"recipe|MATERIAL": {tick, missing, what, snap}}, approved, approved_ids} (order_check)
    dig_seen: dict = field(default_factory=dict)         # (0.104.110) project id -> {"dug", "tick" (last progress), "freed"}
    furnish_seen: dict = field(default_factory=dict)     # (R2 h3) project id -> {"sig" (its missing pieces), "tick" (since)} (planner_slots)
    join_wait_days: int = 2                              # (0.104.108) days to the next look (longer once all were seen)
    culture: dict = field(default_factory=dict)          # culture history (see culture.py)
    culture_pushed: str = ""                              # what was last written into the save
    declined: dict = field(default_factory=dict)          # proposal id -> tick you said No
    saved_before: str = ""                                # project the game was saved for
    fort_run: str = ""                                    # (0.105.48, K8) this fort's run id (brain/fort_run.py), kept in the save's ledger
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
        days = stuck_days(w, now)           # (r1g8) less the alarm's days
        if days < cfg["order_stuck_you_days"] or not _stuck_before(memory, what, now, cfg):
            continue
        if dead and what in ("stone_slab", "stone_coffin"):
            continue
        if supply_order_kept(s, what, cfg):   # (r1g8) drink and meals in a pinch stay
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
    # (0.105.97) never a held killer: the killer cell takes him out of the squad
    # itself, and a swap's reason named him (B, 23 Nov: Fath Shemnish, 2 kills)
    from planner_killers import held_killer_ids
    held = held_killer_ids(s)
    starved = [x for x in starved if x["id"] not in held]
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
    # (r1g5) A: 220 swaps, 22 of 57 armed: no swap while the soldiers on duty
    # are short of weapons, nor while danger is about (planner_war_hold)
    from planner_war_hold import army_danger, swap_armed_short
    if swap_armed_short(s, cfg) or army_danger(s, memory, cfg):
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
