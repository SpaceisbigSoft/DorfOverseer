"""(r7 d4) The split of brain/planner_industry.py, planner_building.py and
planner_wells.py into parts by theme (whole functions, constants and their
comments moved unchanged; the original re-exports every name):

- each original exposes exactly the names (dir()) it had at 6298b4a;
- each name a part defines is the same object in its original, and every
  global a part's code reads is the original's own binding (so the moved
  code sees what it saw before);
- the names tests patch on an original still live (and are read) there;
- each file is under its size limit;
- the modules import cleanly in a fresh interpreter in any order.

    python tests/test_r7_d4.py
"""

from __future__ import annotations

import builtins
import dis
import importlib
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from py_parts import PARTS as FAMILY_PARTS  # noqa: E402

BRAIN = ROOT / "brain"
ORIGINALS = ("planner_industry", "planner_building", "planner_wells")
PARTS = {o: FAMILY_PARTS[o] for o in ORIGINALS}
ALL = [m for o in ORIGINALS for m in [o] + PARTS[o]]
KB = 1024
# planner_building keeps _project_rules (57.6 KB by itself: tests patch the
# names it reads on planner_building and test_hygiene_planner checks it is
# defined there), social_shortfall, temple_size and the placement customs
# (test_customs_fixes patches planner_building.apply_customs, which
# customs_pass reads): it stands over 60 KB, all of it one function and the
# names patched where it reads them
LIMIT = {"planner_building": 70 * KB}

# dir() of each original at 6298b4a (0.105.62), before the split
NAMES_AT_6298B4A = {}
NAMES_AT_6298B4A["planner_industry"] = """
    "ADJUST_BOUNDS", "AGENDA_THEMES", "ALL_FOOD", "BREW_RECIPES", "BUILDABLE_SHOPS", "COAL_STONES",
    "CONTAINER_RECIPES", "COOLDOWN_KEYS", "CROWD_LOCATIONS", "DEAD_LABORS", "DEEP_SURFACE_KINDS",
    "DISPOSAL_ACTION_MAX", "DISPOSAL_LEVELS", "DISPOSAL_REASON_WORDS", "DISPOSAL_RULES", "EMERGENCY",
    "EXCESS_SHOPS", "FEEDER_ORDER", "GEAR_METALS", "GEAR_ORDER_METALS", "GEAR_WEAPONS", "GEMS_GENEROUS_GREED",
    "GREAT_LIKE_KINDS", "IDLE_OLD_LINES", "INDUSTRY_SHOPS", "JOB_SHOPS", "KEEP_TREASURES_GREED", "LABOR_CAPS",
    "LABOR_MODES_FIXED", "LIMIT_EXEMPT", "LOCATION_UNITS", "LOOP_EXEMPT", "LOOP_LIMITS", "LOOP_LIMIT_DEFAULT",
    "MAINTAIN_SKIPS", "MANDATE_RECIPES", "MEAL_RECIPES", "MEMORIAL_SPAN", "MINING_NEED_ONLY", "MOOD_BODY_FLAGS",
    "MULTI_PER_CYCLE", "Memory", "NEEDS_YOU", "NO_COOLDOWN", "NO_EFFECT_RULES", "NO_EFFECT_WHY", "ONE_A_CYCLE",
    "OPEN_CAVERNS_MODES", "OPTIONAL_LEVELS", "ORDER_HOLD_EXEMPT", "OWN_LABOR_RULES", "PASTURE_TILES_GUESS",
    "PER_ID_COOLDOWN", "PLANNER_CONFIG", "PRECIOUS_METALS", "PRECIOUS_ORES", "Proposal", "RAW_FOOD",
    "RECIPE_SHOPS", "REFUSAL_FIRST_DAYS", "REFUSAL_IDLE_DAYS", "REFUSAL_ID_TYPES", "REFUSAL_KEYS",
    "REFUSAL_MAX_DAYS", "SHOP_ALIASES", "SOCIAL_NEEDS", "STALE_PROJECT_DAYS", "STEER_MAX_DAYS",
    "STEER_PROTECTED", "STONE_CRAFTS", "STUCK_HOLD_EXEMPT", "SURVIVAL_SHOPS", "TICKS_PER_DAY", "TICKS_PER_YEAR",
    "TIMEOUT_TRIES", "WINTER_STOCK", "WOOD_ELSEWHERE", "ZONE_FULL_FIRST_DAYS", "ZONE_FULL_MAX_DAYS", "__all__",
    "__builtins__", "__cached__", "__doc__", "__file__", "__loader__", "__name__", "__package__", "__spec__",
    "_approve_rule", "_bench_coffins_rule", "_best_metal", "_bottleneck_rule", "_clamp", "_cloth_rule",
    "_clutter_rules", "_coal_rule", "_crop_rules", "_d", "_dairy_rule", "_deep_depot_choice",
    "_deep_depot_watch", "_deep_plan_hint", "_deep_surface_filter", "_disposal_rules", "_dry_containers",
    "_eggs_rule", "_entrance_spot", "_excess_shops_rule", "_farm_crops_rule", "_farm_rule", "_feeder_rule",
    "_fishery_rule", "_free_time_rule", "_gems_rule", "_glass_rule", "_has_shop", "_hauling_rule",
    "_holding_off", "_idle_share", "_industry_rules", "_keep_rule", "_kiln_rules", "_kitchen_rule", "_l",
    "_labor_rules", "_labor_waiting_rule", "_lever_state", "_location", "_location_short", "_loop_count",
    "_number", "_office_held", "_order_slots_rule", "_orphan_jobs_rule", "_pasture_rule", "_picks_order",
    "_quarry_status", "_quarry_stock", "_real_locations", "_record_any_outcome", "_refused_wait",
    "_restraint_order", "_seed_reserve_rule", "_shoes_recipe", "_slow_game_rules", "_smelting_rule",
    "_soap_rule", "_soldier_swap", "_spare_mechanisms_rule", "_stalled_days", "_standing_key", "_steel_rule",
    "_order_remake_rule", "remake_due", "_stone_rule", "_stuck_again_rule", "_stuck_before", "_stuck_orders_rule", "_supply_rules",
    "_surface_basics", "_trade_rules", "_traits", "_unknown_reachable", "_unsuspend_rule", "_watchdog_notes",
    "_weapon_gaps", "_workshops_busy", "abs_tick", "agenda", "all_clear", "annotations", "asdict", "ask_player",
    "brew_jobs_open", "brew_recipe", "brewable_counts", "brief_timeout", "can_fight", "care_waiting",
    "cooldown_key", "crisis_brew_room", "crops_owned", "crowded_thief", "customs", "dataclass",
    "disposal_places_dump", "disposal_report", "drink_below_target", "drink_crisis", "drink_known_short",
    "drink_lacks_containers", "drink_short", "drink_swap_wanted", "drink_target_per_dwarf", "effective_config",
    "emergency", "established", "factor", "farm_plots_live", "farm_target", "field", "food_containers_want",
    "food_per_dwarf", "free_stock", "game_day", "gatherers", "great_present", "growth_mode", "growth_target",
    "has_farms", "has_rule", "held_levels", "held_off_threats", "idle_line", "is_ranged", "is_release",
    "jobs_reported", "json", "justice_held", "keeps_treasures", "labor_given", "layout_style", "level_refused",
    "levels_done", "limit_exempt", "manager_needs_office", "masons_jammed", "masterplan", "math", "mining_plan",
    "mood_kind", "mood_on_hand", "mood_waits", "new_history", "no_effect_wait", "noble_room_kinds", "normalize",
    "note_labor_given", "note_no_effect", "note_quarry", "note_quarry_dug", "note_refusal", "note_zone_full",
    "open_caverns_mode", "order_job_state", "order_shop", "phases", "pick_stone", "player_rules",
    "precious_metal", "profile_from", "quarry_size", "quarry_wait", "queued", "re", "reachable_threats",
    "recently_home", "recipe_shop", "refusal_key", "shop_count", "shops_max", "snatcher_ids",
    "spare_mechanisms", "spare_sig", "stamp_tick", "steer_of", "steer_protected", "stone_crisis", "stone_for",
    "stone_short", "stuck_days", "stuck_hold_days", "suites_short", "supply_order_kept", "tantrums_recent",
    "thief_ids", "thief_rows", "thirsty_farm_extra", "thread_plants_here", "timeout_streak", "trade_margin_for",
    "trade_wants", "trees_this_year", "unmet", "unstored_cups", "update_idle", "watch_since", "wild_pack",
    "wild_rows", "wildlife_threat", "wildlife_threats", "winter_factor", "woodcutters", "wool_route",
    "young_fort", "zone_full_days"
"""
NAMES_AT_6298B4A["planner_building"] = """
    "ADJUST_BOUNDS", "AGENDA_THEMES", "ALL_FOOD", "BAG_KIND", "BASIC_STOCKPILES", "BASIC_WORKSHOPS",
    "BREW_RECIPES", "BUILDABLE_SHOPS", "CHAIN_SKIP", "CHARACTER_KINDS", "CISTERN_RELINK_ROUNDS",
    "CISTERN_RETRY_SEALS", "CISTERN_SHUT_RULE", "CISTERN_WORDS", "COOLDOWN_KEYS", "CROWD_LOCATIONS",
    "DIG_FIRST_KINDS", "DISPOSAL_ACTION_MAX", "DISPOSAL_LEVELS", "EMERGENCY", "FURNITURE_RECIPES",
    "GEAR_METALS", "GEAR_WEAPONS", "GREAT_LIKE_KINDS", "GROWTH", "GROWTH_AT", "GROWTH_EXTRA_SCORE",
    "GROWTH_MAX", "GROWTH_MAX_OF", "GROWTH_SOLDIERS", "GROWTH_ZONES", "IDLE_OLD_LINES", "JOB_SHOPS",
    "LABOR_CAPS", "LADDER_BASE", "LADDER_TRAITS", "LEARNING_NEEDS", "LIMIT_EXEMPT", "LOCATION_UNITS",
    "LOOP_EXEMPT", "LOOP_LIMITS", "LOOP_LIMIT_DEFAULT", "MAINTAIN_SKIPS", "MANDATE_RECIPES", "MEAL_RECIPES",
    "MEMORIAL_SPAN", "METAL_FURNITURE", "MINING_NEED_ONLY", "MOOD_BODY_FLAGS", "MULTI_PER_CYCLE", "Memory",
    "NEEDS_YOU", "NO_COOLDOWN", "NO_EFFECT_RULES", "NO_EFFECT_WHY", "ONE_A_CYCLE", "OPEN_CAVERNS_MODES",
    "OPTIONAL_LEVELS", "ORDER_HOLD_EXEMPT", "ORDINALS", "PER_ID_COOLDOWN", "PLACEMENT_CUSTOMS",
    "PLANNED_RECIPES", "PLANNED_SAID", "PLANNER_CONFIG", "Proposal", "RAW_FOOD", "RECIPES_WITH_METAL",
    "RECIPE_SHOPS", "REFUSAL_FIRST_DAYS", "REFUSAL_IDLE_DAYS", "REFUSAL_ID_TYPES", "REFUSAL_KEYS",
    "REFUSAL_MAX_DAYS", "SHAFT_DANGER_OPEN", "SHAFT_DANGER_TILES", "SHAFT_DRY_REACH", "SHAFT_LINK_LOST_MAX",
    "SHOP_ALIASES", "SHOP_KINDS", "SHOP_PIECE_RECIPES", "SHOP_PIECE_WORDS", "SOCIAL_KINDS", "SOCIAL_NEEDS",
    "STALE_PROJECT_DAYS", "STEER_MAX_DAYS", "STEER_PROTECTED", "STORE_GROW", "STUCK_FALLBACKS",
    "STUCK_HOLD_EXEMPT", "SURVIVAL_SHOPS", "TICKS_PER_DAY", "TICKS_PER_YEAR", "TIMEOUT_TRIES",
    "TRAIT_NAMES_SHORT", "WATER_WORDS", "WEAVE_KIND", "WELLS_CONFIG", "WELL_DIG_ASK", "WELL_MIN_DEPTH",
    "WELL_PARTS_SHOPS", "WINTER_CISTERN_WORDS", "WINTER_STOCK", "WOODEN_FURNITURE", "WOOD_ELSEWHERE",
    "ZONE_FULL_FIRST_DAYS", "ZONE_FULL_MAX_DAYS", "__all__", "__builtins__", "__cached__", "__doc__",
    "__file__", "__loader__", "__name__", "__package__", "__spec__", "_best_metal", "_cistern_parts",
    "_cistern_rule", "_clamp", "_cleanup_rule", "_d", "_deep_notes", "_dig_stall_rule", "_entrance_spot",
    "_has_shop", "_holding_off", "_idle_share", "_join_rule", "_l", "_ladder_kind", "_ladder_word",
    "_lever_state", "_location", "_location_short", "_loop_count", "_number", "_office_held", "_planned_note",
    "_planned_parts_rule", "_pop_cap_rule", "_project_rules", "_real_locations", "_record_any_outcome",
    "_redig_rule", "_refused_wait", "_restraint_order", "_room_repair_rule", "_shrink_rule", "_soil_floor_rule",
    "_soldier_swap", "_stairwell_rule", "_stalled_days", "_stuck_again_rule", "_stuck_before", "_traits",
    "_watchdog_notes", "_water_rules", "_water_traffic_rule", "_water_zone_rule", "_weapon_gaps",
    "_well_dig_rule", "_well_lid_rule", "_well_parts", "_well_rule", "_winter_water_rule", "_workshops_busy",
    "abs_tick", "agenda", "ai_opens_cavern", "all_clear", "annotations", "apply_customs", "ask_player",
    "bad_wells", "barracks_wanted", "brew_recipe", "brewable_counts", "brief_timeout", "can_fight",
    "care_waiting", "cavern_action", "cavern_danger", "cavern_failure_now", "cavern_open_danger",
    "cavern_open_words", "cavern_points", "cavern_soldiers_ready", "cavern_well_need", "cavern_well_safe",
    "chain_metal", "character_slot_filter", "character_slot_reserved", "cistern_pop", "climate_freezes_now",
    "cooldown_key", "crowded_thief", "customs", "customs_pass", "design", "dining_shortfall",
    "drinkable_frost_wells", "effective_config", "emergency", "established", "factor", "filling_cisterns",
    "food_per_dwarf", "fort_strain", "free_stock", "frost_zone_case", "full_stores", "game_day", "garden_name",
    "garden_pace", "gear_metals", "good_times", "great_present", "growth_candidates", "growth_mode",
    "growth_target", "growth_wait", "growth_want", "has_farms", "has_grand_temple", "has_rule", "held_levels",
    "held_off_threats", "hospital_shortfall", "idle_line", "is_character_level", "is_ranged", "is_release",
    "jail_plan", "jailed", "jobs_reported", "justice_held", "labor_given", "ladder_score", "layout_style",
    "level_refused", "levels_done", "limit_exempt", "magma_access", "manager_needs_office", "masons_jammed",
    "masterplan", "math", "memorial_due", "mining_plan", "mood_kind", "mood_on_hand", "mood_waits",
    "more_temple", "new_history", "no_effect_wait", "no_water_cancels", "noble_room_kinds", "normalize",
    "note_labor_given", "note_no_effect", "note_pop_cap", "note_refusal", "note_zone_full", "open_caverns_mode",
    "order_job_state", "phases", "pick_stone", "piety_slot", "planned_wants", "player_rules",
    "prayer_uncovered", "profile_from", "queued", "re", "reachable_threats", "recently_home", "recipe_shop",
    "refusal_key", "room_size", "settled_times", "shaft_danger_words", "shaft_far_walker", "shaft_judged",
    "shaft_water_short", "shop_count", "shops_max", "shut_columns", "shut_wells", "snatcher_ids",
    "social_shortfall", "spare_metal", "spare_sig", "stamp_tick", "steer_of", "steer_protected", "stone_for",
    "stone_short", "stone_tidiness", "strain_hold", "strain_unhappy_lines", "stuck_days", "stuck_fallback",
    "stuck_hold_days", "suites_short", "supply_order_kept", "tantrums_recent", "tavern_factor", "temple_size",
    "thief_ids", "thief_rows", "thread_plants_here", "timeout_streak", "tombs_short", "unfound_cavern", "unmet",
    "unstored_cups", "update_idle", "usable_wells", "waiting_shops", "watch_since", "water_summary",
    "water_zones_usable", "well_parts_plan", "wild_pack", "wild_rows", "wildlife_threat", "wildlife_threats",
    "winter_cistern_action", "winter_factor", "winter_water_need", "winter_wells", "wool_route", "young_fort",
    "zone_full_days"
"""
NAMES_AT_6298B4A["planner_wells"] = """
    "ADJUST_BOUNDS", "AGENDA_THEMES", "ALL_FOOD", "BREW_RECIPES", "BUILDABLE_SHOPS", "CHAIN_SKIP",
    "CISTERN_RELINK_ROUNDS", "CISTERN_RETRY_SEALS", "CISTERN_SHUT_RULE", "CISTERN_WORDS", "COOLDOWN_KEYS",
    "CROWD_LOCATIONS", "DISPOSAL_ACTION_MAX", "DISPOSAL_LEVELS", "EMERGENCY", "GEAR_METALS", "GEAR_WEAPONS",
    "GREAT_LIKE_KINDS", "IDLE_OLD_LINES", "JOB_SHOPS", "LABOR_CAPS", "LIMIT_EXEMPT", "LOCATION_UNITS",
    "LOOP_EXEMPT", "LOOP_LIMITS", "LOOP_LIMIT_DEFAULT", "MAINTAIN_SKIPS", "MANDATE_RECIPES", "MEAL_RECIPES",
    "MEMORIAL_SPAN", "MINING_NEED_ONLY", "MOOD_BODY_FLAGS", "MULTI_PER_CYCLE", "Memory", "NEEDS_YOU",
    "NO_COOLDOWN", "NO_EFFECT_RULES", "NO_EFFECT_WHY", "NO_WATER_WORDS", "ONE_A_CYCLE", "OPEN_CAVERNS_MODES",
    "OPTIONAL_LEVELS", "ORDER_HOLD_EXEMPT", "PER_ID_COOLDOWN", "PLANNER_CONFIG", "Proposal", "RAW_FOOD",
    "RECIPE_SHOPS", "REFUSAL_FIRST_DAYS", "REFUSAL_IDLE_DAYS", "REFUSAL_ID_TYPES", "REFUSAL_KEYS",
    "REFUSAL_MAX_DAYS", "SHAFT_DANGER_OPEN", "SHAFT_DANGER_TILES", "SHAFT_DRY_REACH", "SHAFT_LINK_LOST_MAX",
    "SHOP_ALIASES", "SOCIAL_NEEDS", "STALE_PROJECT_DAYS", "STEER_MAX_DAYS", "STEER_PROTECTED",
    "STUCK_HOLD_EXEMPT", "SURVIVAL_SHOPS", "TICKS_PER_DAY", "TICKS_PER_YEAR", "TIMEOUT_TRIES", "WATER_WORDS",
    "WELLS_CONFIG", "WELL_MIN_DEPTH", "WELL_PARTS_SHOPS", "WINTER_CISTERN_WORDS", "WINTER_STOCK",
    "WINTER_WATER_RULE", "WOOD_ELSEWHERE", "ZONE_FULL_FIRST_DAYS", "ZONE_FULL_MAX_DAYS", "__all__",
    "__builtins__", "__cached__", "__doc__", "__file__", "__loader__", "__name__", "__package__", "__spec__",
    "_best_metal", "_cistern_buckets", "_cistern_coming", "_cistern_parts", "_cistern_rule", "_cistern_works",
    "_clamp", "_d", "_entrance_spot", "_far_args", "_fill_source", "_frost_wells", "_has_shop", "_holding_off",
    "_ice_now", "_idle_share", "_l", "_lever_state", "_location", "_location_short", "_loop_count", "_number",
    "_office_held", "_real_locations", "_record_any_outcome", "_refused_wait", "_restraint_order",
    "_shaft_build_words", "_shaft_turn", "_shut_rows", "_soldier_swap", "_stalled_days", "_stuck_again_rule",
    "_stuck_before", "_traits", "_watchdog_notes", "_water_rules", "_water_traffic_rule", "_water_zone_rule",
    "_weapon_gaps", "_well_lid_rule", "_well_parts", "_well_rule", "_winter_cistern_wait", "_winter_water_rule",
    "_workshops_busy", "abs_tick", "agenda", "ai_opens_cavern", "all_clear", "annotations", "ask_player",
    "bad_wells", "brew_recipe", "brewable_counts", "brief_timeout", "can_fight", "care_waiting",
    "cavern_action", "cavern_danger", "cavern_failure_now", "cavern_open_danger", "cavern_open_words",
    "cavern_points", "cavern_soldiers_ready", "cavern_well_need", "cavern_well_safe", "chain_metal",
    "cistern_pop", "climate_freezes_now", "cooldown_key", "crowded_thief", "drinkable_frost_wells",
    "effective_config", "emergency", "established", "factor", "filling_cisterns", "food_per_dwarf",
    "free_stock", "frost_zone_case", "game_day", "great_present", "growth_mode", "growth_target", "has_farms",
    "held_off_threats", "idle_line", "is_ranged", "is_release", "jailed", "jobs_reported", "justice_held",
    "labor_given", "level_refused", "levels_done", "limit_exempt", "magma_access", "manager_needs_office",
    "masons_jammed", "math", "mining_plan", "mood_kind", "mood_on_hand", "mood_waits", "need_slots_free",
    "no_effect_wait", "no_water_cancels", "noble_room_kinds", "note_labor_given", "note_no_effect",
    "note_refusal", "note_zone_full", "open_caverns_mode", "order_job_state", "player_rules", "queued",
    "reachable_threats", "recently_home", "recipe_shop", "refusal_key", "shaft_danger_words",
    "shaft_far_walker", "shaft_judged", "shaft_water_short", "shop_count", "shops_max", "shut_columns",
    "shut_wells", "snatcher_ids", "spare_sig", "stamp_tick", "steer_of", "steer_protected", "stone_short",
    "stuck_days", "stuck_hold_days", "suites_short", "supply_order_kept", "tantrums_recent", "thief_ids",
    "thief_rows", "thread_plants_here", "timeout_streak", "unfound_cavern", "unmet", "unstored_cups",
    "update_idle", "usable_wells", "watch_since", "water_summary", "water_zones_usable", "well_parts_plan",
    "wild_pack", "wild_rows", "wildlife_threat", "wildlife_threats", "winter_cistern_action", "winter_factor",
    "winter_water_need", "winter_wells", "wool_route", "young_fort", "zone_full_days"
"""
NAMES_AT_6298B4A = {k: [x.strip().strip('"') for x in v.replace("\n", " ").split(",") if x.strip()]
                    for k, v in NAMES_AT_6298B4A.items()}


def mod(name):
    return importlib.import_module(name)


@test("each original exposes exactly the names it had at 6298b4a")
def _():
    for o in ORIGINALS:
        want, got = set(NAMES_AT_6298B4A[o]), set(dir(mod(o)))
        assert len(want) == len(NAMES_AT_6298B4A[o]) > 200, o
        assert got == want, (o, sorted(want - got), sorted(got - want))


@test("every name a part defines is in its __all__, exists in the original, and is the same object there")
def _():
    import ast
    for o in ORIGINALS:
        om = mod(o)
        for p in PARTS[o]:
            pm = mod(p)
            tree = ast.parse((BRAIN / f"{p}.py").read_text(encoding="utf-8"))
            defined = set()
            for n in tree.body:
                if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                    defined.add(n.name)
                elif isinstance(n, ast.Assign):
                    defined |= {t.id for t in n.targets if isinstance(t, ast.Name)} - {"__all__"}
            assert defined and defined == set(pm.__all__), (p, sorted(defined ^ set(pm.__all__)))
            for n in pm.__all__:
                assert n in NAMES_AT_6298B4A[o], (p, n)
                assert getattr(om, n) is getattr(pm, n), (o, n)
                obj = getattr(pm, n)
                if isinstance(obj, types.FunctionType):
                    assert obj.__module__ == p, (p, n, obj.__module__)


@test("every global a part's code reads is the original's own binding (nothing rebound by the move)")
def _():
    bad = []
    for o in ORIGINALS:
        om = mod(o)
        for p in PARTS[o]:
            pm = mod(p)
            names = set()

            def walk(code):
                for ins in dis.get_instructions(code):
                    if ins.opname in ("LOAD_GLOBAL", "LOAD_NAME"):
                        names.add(str(ins.argval).replace(" + NULL", "").replace("NULL + ", ""))
                for c in code.co_consts:
                    if isinstance(c, types.CodeType):
                        walk(c)
            walk(compile((BRAIN / f"{p}.py").read_text(encoding="utf-8"), p, "exec"))
            for n in sorted(names):
                if hasattr(builtins, n) or n in ("__name__", "__doc__", "annotations"):
                    continue
                if n not in pm.__dict__ or n not in om.__dict__ or pm.__dict__[n] is not om.__dict__[n]:
                    bad.append(f"{p}.{n}")
    assert not bad, bad


@test("the names tests patch on an original are still defined and read there")
def _():
    import planner_building
    import planner_industry
    import planner_wells
    # test_planner: planner_building.social_shortfall / temple_size, read by _project_rules
    for n in ("_project_rules", "social_shortfall", "temple_size"):
        assert getattr(planner_building, n).__module__ == "planner_building", n
    names = planner_building._project_rules.__code__.co_names
    assert "social_shortfall" in names and "temple_size" in names
    # test_customs_urgent: dining/social/hospital_shortfall, prayer_uncovered, manager_needs_office,
    # read by _project_rules; test_customs_fixes: apply_customs, read by customs_pass
    for n in ("dining_shortfall", "hospital_shortfall", "prayer_uncovered", "manager_needs_office"):
        assert n in names, n
    for n in ("apply_customs", "customs_pass"):
        assert getattr(planner_building, n).__module__ == "planner_building", n
    assert "apply_customs" in planner_building.customs_pass.__code__.co_names
    # test_r41_food_fixes: planner_wells.chain_metal, read by well_parts_plan
    for n in ("chain_metal", "well_parts_plan"):
        assert getattr(planner_wells, n).__module__ == "planner_wells", n
    assert "chain_metal" in planner_wells.well_parts_plan.__code__.co_names
    # test_r41_food_fixes: planner_industry.drink_crisis / drink_target_per_dwarf, read by _supply_rules
    assert planner_industry._supply_rules.__module__ == "planner_industry"
    names = planner_industry._supply_rules.__code__.co_names
    assert "drink_crisis" in names and "drink_target_per_dwarf" in names
    # test_k48_holds knows _deep_depot_choice's Proposal(p.rule, ...) in planner_industry.py
    assert planner_industry._deep_depot_choice.__module__ == "planner_industry"


@test("the module-level statements stay where they ran (config merge, rule sets, agenda themes)")
def _():
    import planner_core
    import planner_wells
    import planner_wells_caverns
    assert planner_wells.CISTERN_SHUT_RULE in planner_core.STEER_PROTECTED
    assert planner_wells.WINTER_WATER_RULE in planner_core.STEER_PROTECTED
    assert planner_wells.WINTER_WATER_RULE in planner_core.AGENDA_THEMES
    for k in planner_wells_caverns.WELLS_CONFIG:
        assert k in planner_core.PLANNER_CONFIG, k
    src = (BRAIN / "planner_wells.py").read_text(encoding="utf-8")
    assert "NO_COOLDOWN.add(CISTERN_SHUT_RULE)" in src and "STEER_PROTECTED.add(WINTER_WATER_RULE)" in src


@test("each file is under its size limit")
def _():
    for m in ALL:
        size = (BRAIN / f"{m}.py").stat().st_size
        assert size < LIMIT.get(m, 60 * KB), (m, size)


@test("the modules import cleanly in a fresh interpreter, in any order")
def _():
    orders = [[m] for m in ALL] + [list(reversed(ALL)), sorted(ALL), ["planner"] + ALL, ALL + ["planner"]]
    code = ("import sys, importlib; sys.path.insert(0, sys.argv[1]); "
            "[importlib.import_module(m) for m in sys.argv[2:]]; "
            "import planner_industry as a, planner_building as b, planner_wells as c, planner as p; "
            "assert b.magma_access is c.magma_access and p.PLANNER_CONFIG is b.PLANNER_CONFIG; print('ok')")
    for order in orders:
        r = subprocess.run([sys.executable, "-c", code, str(BRAIN), *order], capture_output=True, text=True,
                           timeout=120, cwd=str(ROOT))
        assert r.returncode == 0 and r.stdout.strip().endswith("ok"), (order, r.stderr[-800:])


if __name__ == "__main__":
    finish()
