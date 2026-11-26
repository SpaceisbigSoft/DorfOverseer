"""r7 d2: brain/planner.py split into parts (behaviour unchanged).

planner.py keeps plan() (one 73 KB function: splitting it would change code)
and the import header its globals come from; select() and its squad helpers
went to planner_select, record() to planner_record, note_cycle() and
note_gate_lever to planner_cycle. planner re-exports every name.

    python tests/test_r7_d2.py
"""

from __future__ import annotations

import itertools
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402

import planner  # noqa: E402
import planner_cycle  # noqa: E402
import planner_record  # noqa: E402
import planner_select  # noqa: E402

PARTS = {planner_select: ("SHOPS_RETRY_DAYS", "SHOPS_RETRY_MAX", "SQUAD_ORDER_KEYS", "SQUAD_WHOLE", "_is_kill",
                          "free_squad_for", "ordered_squads", "select", "squad_claim"),
         planner_record: ("ACTION_LOG_MAX", "RECORD_STEPS", "record"),
         planner_cycle: ("ASKED_TICKS", "GATE_PULL_SEEN_DAYS", "note_cycle", "note_gate_lever")}
# names the tests patch on `planner` that the moved code calls: looked up through planner at call time
LATE = {planner_select: ("mood_blocked", "order_gate", "reserve_room"),
        planner_record: ("note_gate_stuck", "note_holdfast", "note_way_out")}

# dir(planner) at main 6298b4a (0.105.62), before the split; (r11 n1) + _office_swap_rule; (0.105.78) + meal_glut_filter;
# (item2) + mood_hospital_rule; (0.105.112 item4) + hospital_stock_rule
NAMES_6298B4A = (
    'meal_glut_filter',
    'mood_hospital_rule',   # (item2) a mood's cloth or thread out of the hospital's stock
    'hospital_stock_rule',   # (0.105.112 item4) the hospitals' standing thread/cloth cap
    '_mechanism_stock_rule',   # (0.105.119 item30) enough free mechanisms for the lever links
    'cap_full_pass',   # (0.105.119 item39) no new level the full building cap would refuse
    '_order_remake_rule', 'remake_due',   # (0.105.112 item8) a one-stone order with no job remade in any stone
    'ACTION_LOG_MAX', 'ADJUST_BOUNDS', 'AGENDA_THEMES', 'AI_OFFICES', 'ALERT_DANGERS', 'ALL_FOOD',
    'ASKED_TICKS', 'BASIC_STOCKPILES', 'BASIC_WORKSHOPS', 'BREW_RECIPES', 'BUILDABLE_SHOPS', 'CHARACTER_KINDS',
    'CISTERN_WORDS', 'COAL_STONES', 'COMPLAINT_WORDS', 'CONTAINER_RECIPES', 'COOLDOWN_KEYS', 'CROWD_LOCATIONS',
    'DEEP_SURFACE_KINDS', 'DISPOSAL_ACTION_MAX', 'DISPOSAL_LEVELS', 'DISPOSAL_RULES', 'EMERGENCY',
    'EXCESS_SHOPS', 'FEEDER_ORDER', 'FIGHT_FACTOR_MAX', 'FURNITURE_RECIPES', 'GATE_PULL_SEEN_DAYS',
    'GEAR_HELD', 'GEAR_METALS', 'GEAR_ORDER_METALS', 'GEAR_WEAPONS', 'GEMS_GENEROUS_GREED', 'GREAT_LIKE_KINDS',
    'GROWTH', 'GROWTH_AT', 'GROWTH_EXTRA_SCORE', 'GROWTH_MAX', 'GROWTH_MAX_OF', 'GROWTH_SOLDIERS',
    'GROWTH_ZONES', 'HEISTS_KEEP', 'IDLE_CRAFTS', 'IDLE_OLD_LINES', 'IDLE_STOCK_FURNITURE', 'INDUSTRY_SHOPS',
    'JEWEL_RECIPES', 'JOB_SHOPS', 'LABOR_CAPS', 'LABOR_MODES_FIXED', 'LADDER_BASE', 'LADDER_TRAITS',
    'LEARNING_NEEDS', 'LIMIT_EXEMPT', 'LOCATION_UNITS', 'LOOP_EXEMPT', 'LOOP_LIMITS', 'LOOP_LIMIT_DEFAULT',
    'MAINTAIN_SKIPS', 'MANDATE_RECIPES', 'MEAL_RECIPES', 'MEMORIAL_SPAN', 'METAL_FURNITURE',
    'MINING_NEED_ONLY', 'MOOD_BODY_FLAGS', 'MOOD_CONSUMERS', 'MOOD_TRADE_KEYS', 'MOOD_WORKSHOPS',
    'MULTI_PER_CYCLE', 'Memory', 'NEEDS_YOU', 'NEED_ADVICE', 'NO_COOLDOWN', 'NO_EFFECT_RULES', 'NO_EFFECT_WHY',
    'OFFICE_FIRST', 'ONE_A_CYCLE', 'OPEN_CAVERNS_MODES', 'OPTIONAL_LEVELS', 'ORDER_HOLD_EXEMPT', 'ORDINALS',
    'OWN_LABOR_RULES', 'PASTURE_ACTIONS', 'PER_ID_COOLDOWN', 'PETITION_KINDS', 'PLACEMENT_CUSTOMS',
    'PLANNER_CONFIG', 'POST_LABORS', 'PRECIOUS_METALS', 'PRECIOUS_ORES', 'Proposal', 'RAW_FOOD',
    'RECIPE_SHOPS', 'RECORD_STEPS', 'REFUSAL_FIRST_DAYS', 'REFUSAL_IDLE_DAYS', 'REFUSAL_ID_TYPES',
    'REFUSAL_KEYS', 'REFUSAL_MAX_DAYS', 'SHELTER_RETRY_DAYS', 'SHELTER_RETRY_THREAT_DAYS', 'SHOPS_RETRY_DAYS',
    'SHOPS_RETRY_MAX', 'SHOP_ALIASES', 'SHOP_PIECE_RECIPES', 'SOCIAL_KINDS', 'SOCIAL_NEEDS',
    'SQUAD_ORDER_KEYS', 'SQUAD_WHOLE', 'STAFF_MAX', 'STAFF_POSTS', 'STALE_PROJECT_DAYS', 'STEER_MAX_DAYS',
    'STEER_PROTECTED', 'STONE_CRAFTS', 'STORE_GROW', 'STUCK_FALLBACKS', 'STUCK_HOLD_EXEMPT', 'SURVIVAL_SHOPS',
    'TANTRUM_KEEP', 'THOUGHT_WORDS', 'TICKS_PER_DAY', 'TICKS_PER_YEAR', 'TIMEOUT_TRIES', 'TRAIT_NAMES_SHORT',
    'WATER_WORDS', 'WEAPON_IDS', 'WELL_PARTS_SHOPS', 'WINTER_STOCK', 'WOODEN_FURNITURE', 'WOOD_ELSEWHERE',
    'ZONE_FULL_FIRST_DAYS', 'ZONE_FULL_MAX_DAYS', '__builtins__', '__cached__', '__doc__', '__file__',
    '__loader__', '__name__', '__package__', '__spec__', '_alerts_rule', '_alloy_rule', '_anvil_rule',
    '_approve_rule', '_army_gear_rule', '_artifact_rule', '_bench_caps_rule', '_bench_coffins_rule',
    '_best_metal', '_bolts_rule', '_booze_variety_rule', '_bottleneck_rule', '_bowyer_rule',
    '_break_fights_rule', '_calm_burrow_rule', '_captives_rule', '_cavern_logging_rule', '_cistern_parts',
    '_cistern_rule', '_citizenship_notes', '_clamp', '_cleanup_rule', '_cloth_rule', '_clutter_rules',
    '_coal_rule', '_comfort_rules', '_complaint_notes', '_construction_blocks_rule', '_contact_rule',
    '_convict_rule', '_crop_rules', '_crossbow_order', '_crossing_rule', '_d', '_dairy_rule', '_dead_notes',
    '_deep_depot_choice', '_deep_depot_watch', '_deep_hazard_rule', '_deep_notes', '_deep_plan_hint',
    '_deep_surface_filter', '_descent_rule', '_destroyer_gate_rule', '_dig_stall_rule', '_disposal_rules',
    '_doctor_patient_rule', '_doctor_post_rule', '_drought_rule', '_eggs_rule', '_entrance_spot',
    '_excess_shops_rule', '_export_bans_notes', '_export_rule', '_farm_crops_rule', '_farm_rule',
    '_feeder_rule', '_fire_breather_rule', '_fishery_rule', '_flask_rule', '_floor_notes', '_food_store_rule',
    '_free_gate_levers', '_free_time_rule', '_garden_court_rule', '_gate_cut_rule', '_gate_dogs_rule',
    '_gate_guard_rule', '_gate_rules', '_gatehouse_rule', '_gems_rule', '_glass_rule', '_grandeur_rule',
    '_grove_rule', '_hall_rule', '_has_shop', '_hauling_labor_rule', '_hauling_rule', '_hazard_rules',
    '_hazards_rule', '_health_rules', '_holding_off', '_homes_rules', '_hospital_burrow_rule',
    '_hostile_trade_filter', '_hunt_rule', '_husbandry_rules', '_ice_rule', '_idle_at_cap', '_idle_share',
    '_industry_rules', '_infection_rule', '_insane_rule', '_intruder_guard_rule', '_is_kill',
    '_jail_size_rule', '_join_rule', '_keep_rule', '_kill_hold_filter', '_killer_rule', '_killzone_rule',
    '_kiln_rules', '_kitchen_rule', '_l', '_labor_rules', '_labor_waiting_rule', '_ladder_kind',
    '_ladder_word', '_leather_gear_rule', '_lever_far_enough', '_lever_hatches_ok', '_lever_rule',
    '_lever_state', '_link_wanted', '_location', '_location_access_rule', '_location_petition_rules',
    '_location_short', '_location_supply_rules', '_location_value_rule', '_lone_squad', '_loop_count',
    '_lure_rule', '_meeting_answer_rule', '_meeting_notes', '_messenger_rule', '_miasma_rule',
    '_migrants_rule', '_military_rules', '_mission_rule', '_office_swap_rule', '_mood_make', '_mood_materials',
    '_mood_reserve_rule', '_mood_rules', '_mood_slaughter', '_near_gates_rule', '_near_spot', '_necro_rule',
    '_needs_notes', '_needs_rules', '_no_shelter_note', '_noble_rooms_rule', '_noble_value_rule', '_number',
    '_office_held', '_offices_refill_rule', '_order_slots_rule', '_orphan_jobs_rule', '_paper_rule',
    '_pasture_hold', '_pasture_rule', '_peace_notes', '_people_rules', '_petition_rules', '_picks_order',
    '_pile_links_rule', '_planned_note', '_planned_parts_rule', '_pop_cap_rule', '_prisoner_water_rule',
    '_project_rules', '_prospect_rule', '_provisions_rules', '_quick_location_rule', '_quiver_rule', '_ranged_squad_rule',
    '_real_locations', '_record_any_outcome', '_recreation_rule', '_refused_wait', '_reserve_storage_rule',
    '_residency_rule', '_restraint_order', '_room_repair_rule', '_seed_reserve_rule', '_set_adopted',
    '_shelter_due', '_shelter_pick_rule', '_shelter_possible', '_shelter_squads_rule', '_shoes_recipe',
    '_shrink_rule', '_siege_rules', '_slow_game_rules', '_smelting_rule', '_soap_rule', '_society_notes',
    '_soldier_swap', '_spare_mechanisms_rule', '_squad_matchup_filter', '_staff_rule', '_stairwell_rule',
    '_stalled_days', '_steel_rule', '_stone_rule', '_stress_care', '_stuck_again_rule', '_stuck_before',
    '_stuck_orders_rule', '_stuck_rule', '_supply_rules', '_surface_basics', '_sync_offices_rule',
    '_syndrome_rule', '_tantrum_rules', '_thirst_rule', '_threat_rules', '_traction_rest_rule',
    '_traction_rule', '_trade_rules', '_traffic_rule', '_training_rotation', '_training_squad_rule', '_traits',
    '_trap_rule', '_uniform_weapon_rule', '_unsuspend_rule', '_vermin_rule', '_war_animal_rule',
    '_watchdog_notes', '_water_rules', '_water_traffic_rule', '_water_zone_rule', '_waterworks_rule',
    '_way_out_rule', '_weapon_gaps', '_weather_rules', '_weather_squad_filter', '_welfare_rules',
    '_well_lid_rule', '_well_parts', '_well_rule', '_well_safety_rule', '_winter_water_rule', '_wish_met',
    '_wish_words', '_workshops_busy', '_world_cleanup_rule', '_world_notes', 'abs_tick', 'agenda',
    'ai_gates_shut', 'alarm_held', 'alert_ages', 'all_clear', 'annotations', 'apply_customs',
    'approve_on_place', 'ask_player', 'book_unfought', 'brew_jobs_open', 'brew_recipe', 'brewable_counts',
    'brief_timeout', 'called_off_ids', 'can_fight', 'care_waiting', 'cavern_action', 'cavern_danger',
    'cavern_points', 'cavern_well_need', 'cavern_well_safe', 'chain_metal', 'character_slot_filter',
    'character_slot_reserved', 'cistern_pop', 'citizens_taste', 'civilian_cap', 'cooldown_key', 'crisis',
    'crisis_brew_room', 'crops_owned', 'crossbows_wanted', 'crossing_value', 'crowded_thief', 'customs_pass',
    'deep_pass', 'design_rule', 'dining_shortfall', 'disposal_places_dump', 'disposal_report',
    'drink_below_target', 'drink_crisis', 'drink_known_short', 'drink_known_short_s', 'drink_lacks_containers',
    'drink_short', 'drink_target_per_dwarf', 'effective_config', 'emergency', 'established', 'factor',
    'farm_plots_live', 'farm_target', 'few_alert_over', 'few_ordinary', 'fields', 'floors_line', 'floors_view',
    'food_per_dwarf', 'fort_strain', 'free_squad_for', 'free_stock', 'full_stores', 'game_day', 'garden_name',
    'garden_pace', 'gate_invaders', 'gatherers', 'ghost_work_blocked', 'good_times', 'govern_alarm',
    'great_present', 'growth_candidates', 'growth_mode', 'growth_target', 'growth_wait', 'growth_want',
    'guard_fail', 'guard_lines', 'guard_ok', 'guard_training_orders', 'guided_pass', 'has_farms',
    'has_grand_temple', 'has_rule', 'hazard_alert', 'heist_lockout', 'heist_lockout_days', 'held_off_threats',
    'hold_lifted', 'homes_census', 'hospital_shortfall', 'hunted_outside', 'idle_hands', 'idle_line',
    'is_character_level', 'is_ranged', 'is_release', 'jail_plan', 'jobs_reported', 'justice_held',
    'keeps_treasures', 'labor_given', 'ladder_score', 'level_refused', 'levels_done', 'limit_exempt',
    'location_stale', 'lockdown_released', 'lone_alert_over', 'lone_hunted', 'lone_intruders', 'lone_sneaker',
    'magma_access', 'magma_alarm', 'main_gate', 'manager_needs_office', 'masons_jammed', 'masterplan', 'math',
    'mayor_meetings', 'meeting_open_due', 'meeting_open_said', 'memorial_due', 'mining_plan', 'mood_blocked',
    'mood_item_text', 'mood_kind', 'mood_on_hand', 'mood_shelter_rule', 'mood_trade_wants', 'mood_waits',
    'more_temple', 'needs_pass', 'no_effect_wait', 'no_shelter', 'noble_room_kinds', 'noble_room_plan',
    'nobles_view', 'normalize', 'note_alarm_change', 'note_captives', 'note_cleanup', 'note_construct',
    'note_construct_cycle', 'note_contact_sent', 'note_cycle', 'note_design', 'note_food', 'note_food_level',
    'note_gate_lever', 'note_gate_stuck', 'note_gate_stuck_cycle', 'note_hauling', 'note_heists',
    'note_holdfast', 'note_holdfast_cycle', 'note_hunt_cycle', 'note_keep_in', 'note_labor_given',
    'note_locations', 'note_lockdown', 'note_missions', 'note_mood_help', 'note_never_draft', 'note_no_effect',
    'note_order_loop', 'note_outside', 'note_pop_cap', 'note_quarry', 'note_quarry_dug', 'note_ranged_need',
    'note_recovery', 'note_refusal', 'note_reserve_swap', 'note_residency', 'note_stuck', 'note_syndromes',
    'note_tantrum_book', 'note_tantrums', 'note_thirst', 'note_training', 'note_war_hold', 'note_way_out',
    'note_way_out_cycle', 'note_world', 'note_zone_full', 'open_caverns_mode', 'order_gate', 'order_job_state',
    'order_shop', 'ordered_squads', 'outdoor_filter', 'outsider_orders', 'patient_waits', 'petition_lean',
    'petition_orders_wanted', 'piety_slot', 'plan', 'planned_wants', 'planner_design', 'player_rules',
    'polish_paused', 'precious_metal', 'prepare_training', 'quarry_size', 'quarry_wait', 'queued',
    'quick_clear', 'reach_alarm_over', 'reach_raise_held', 'reachable_threats', 'recently_home', 'recipe_shop',
    'record', 'recovery_apply', 'refusal_key', 'refusal_streak', 'reserve_cfg', 'reserve_room',
    'reserves_pass', 'residency_stance', 'room_size', 'select', 'settled_times', 'shop_count', 'shops_max',
    'slots_rules', 'snatch_alarm', 'snatcher_ids', 'social_shortfall', 'soldier_share', 'soldiers_wanted',
    'spare_mechanisms', 'spare_metal', 'spare_sig', 'squad_claim', 'stamp_tick', 'steer_guard', 'steer_of',
    'steer_protected', 'stock_factor', 'stone_crisis', 'stone_short', 'stone_tidiness', 'stress_causes',
    'stuck_days', 'stuck_fallback', 'stuck_hold_days', 'suites_short', 'supply_order_kept', 'tantrums_recent',
    'taste_on', 'tavern_factor', 'temple_size', 'thief_ids', 'thief_rows', 'thirst_journal',
    'thirsty_farm_extra', 'thread_plants_here', 'timeout_streak', 'tombs_short', 'trade_margin_for',
    'trade_wants', 'trees_this_year', 'unfought', 'unfought_raise_held', 'unknown_filter', 'unmet',
    'unseen_intrusion', 'unstored_cups', 'update_idle', 'visitor_shut', 'waiting_shops', 'war_hold_filter',
    'watch_since', 'watched_gate_levers', 'water_summary', 'weak_squad', 'well_parts_plan', 'wild_pack',
    'wild_rows', 'wildlife_threat', 'wildlife_threats', 'winter_factor', 'wish_key', 'woodcutters',
    'wool_route', 'young_fort', 'zone_full_days',
)


@test("planner exposes exactly the names it had at 6298b4a")
def _():
    now = sorted(dir(planner))
    assert now == sorted(NAMES_6298B4A), (sorted(set(now) - set(NAMES_6298B4A)), sorted(set(NAMES_6298B4A) - set(now)))


@test("every moved name is the same object in planner and in its part, and defined in the part")
def _():
    bad = []
    for mod, names in PARTS.items():
        for n in names:
            if getattr(planner, n) is not getattr(mod, n):
                bad.append(f"{mod.__name__}.{n}")
            f = getattr(mod, n)
            if callable(f) and getattr(f, "__module__", None) != mod.__name__:
                bad.append(f"{mod.__name__}.{n} from {f.__module__}")
    assert not bad, bad


@test("every other global a part holds is planner's own object (the same imports), but the late-bound names")
def _():
    bad = []
    for mod in PARTS:
        late = LATE.get(mod, ())
        for k, v in vars(mod).items():
            if k.startswith("__") or k == "_late" or k in PARTS[mod]:
                continue
            if k in late:
                if v is getattr(planner, k) or v.__name__ != k:
                    bad.append(f"{mod.__name__}.{k} not late")
            elif planner.__dict__.get(k, None) is not v:
                bad.append(f"{mod.__name__}.{k}")
    assert not bad, bad


@test("a patch on planner reaches the moved code (planner.<name> = fake, as the tests do)")
def _():
    for mod, names in LATE.items():
        for n in names:
            real = getattr(planner, n)
            seen = []
            setattr(planner, n, lambda *a, **k: seen.append((a, k)) or "faked")
            try:
                assert getattr(mod, n)(1, x=2) == "faked" and seen == [((1,), {"x": 2})], (mod.__name__, n)
            finally:
                setattr(planner, n, real)
            assert getattr(mod, n).__name__ == n


@test("sizes: each part under 60 KB; planner.py down from 156 KB (plan() alone is 73 KB)")
def _():
    for mod in PARTS:
        size = (ROOT / "brain" / f"{mod.__name__}.py").stat().st_size
        assert size < 60_000, (mod.__name__, size)
    assert (ROOT / "brain" / "planner.py").stat().st_size < 92_000


@test("the parts and planner import cleanly in a fresh interpreter, in any order")
def _():
    mods = ["planner", "planner_select", "planner_record", "planner_cycle"]
    progs = []
    for order in itertools.permutations(mods):
        progs.append("import sys; sys.path.insert(0, %r); " % str(ROOT / "brain")
                     + "; ".join(f"import {m}" for m in order)
                     + "; assert planner.select is planner_select.select and planner.note_cycle is planner_cycle.note_cycle")
    for p in progs:
        r = subprocess.run([sys.executable, "-c", p], capture_output=True, text=True, cwd=str(ROOT))
        assert r.returncode == 0, (p[-160:], r.stderr[-600:])


if __name__ == "__main__":
    finish()
