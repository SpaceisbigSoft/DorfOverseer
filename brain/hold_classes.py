"""(0.105.48, K5) One table for what waits while the fort is in crisis or in
collapse recovery: every planner rule and every bridge action kind is
classed survival, defence or expansion. Crisis mode (crisis.py) and
recovery (planner_recovery.py) both hold the expansion steps and nothing
else; survival and defence steps always go. tests/test_k48_holds.py fails
when a rule the planner can make, or an action kind the bridge knows, is in
no class (or in two).

Why (audit A7): the two hand-kept name lists held the step that shuts a
leaking floodgate (waterworks_moat shut), a vampire's expulsion, traps,
cavern doors and wild_hunt; let ~30 expansion rules through; held squad_make
in a crisis; let a start_project's kind outrank its rule (a Jeweler's level
from `gems` passed, and was even boosted as "recovery" in a crisis).

How a step is classed (step_class):
  * a new level (start_project): urgent, or a strange mood's: survival; a
    rule classed expansion: expansion; a crisis recovery rule: survival;
    else by its kind (SURVIVAL_KINDS, never a set piece, a growth hall or a
    landmark level);
  * a step that makes a work safe (shut, retire, recheck): survival, whatever
    the rule (the waterworks' floodgate shut on a leak);
  * STEP_CLASS for the rules whose actions differ (the depot's deep depot);
  * the rule's class; a rule not in the table (the strategist's) by its
    action kind; an unknown kind: survival (never hold by mistake).
"""

from __future__ import annotations

SURVIVAL, DEFENCE, EXPANSION = "survival", "defence", "expansion"
CLASSES = (SURVIVAL, DEFENCE, EXPANSION)

# levels that keep a fort alive or put it back on its feet (a set piece,
# a growth hall or a landmark level of these kinds still waits)
SURVIVAL_KINDS = {"bedrooms", "dining", "hospital", "well", "farms", "storage", "workshops", "tombs",
                  "tavern", "temple", "jail", "suites"}

# a step with one of these set makes a work safe or ends it: always goes
SAFE_FLAGS = ("shut", "retire", "recheck")

# rules decided by their action kind (they carry any action)
BY_ACTION = {"strategist"}

_EXPANSION_RULES = {
    # hunts, kill zones, lures, missions and contact
    "hunt", "killzone", "killzone_parts", "lure_build", "lure_open", "lure_archer",
    "beast_hunt",   # (0.105.54) the seal opened for a fight with the cavern beast: waits in a crisis
    "mission", "mission_pets", "mission_way", "contact", "training_squad",
    # building above ground and set pieces, landmarks, the grove, the garden court
    "hall", "wings", "soil_floor", "keep", "construct_blocks", "stairwell", "garden_court",
    "landmark", "landmark_level", "landmark_sites", "landmark_step", "grove", "grove_guard",
    # siege works, gatehouses, the cut entrance, walls on the gates (not the cavern doors)
    "siege_engine", "siege_shop", "siege_parts", "siege_ammo", "siege_operator", "fortify_post",
    "gatehouse", "fortify", "gate_cut",
    # value, polish, show
    "polish", "grandeur", "location_value", "noble_value", "encrust", "gems", "gem_cutting", "glass",
    "instruments", "artifact_display", "artifact_furniture", "artifact_pedestals", "library_chest",
    # industry that can wait
    "export", "paper", "paper_shop", "alloy", "leather_gear", "industry", "bottleneck", "kiln", "idle",
    "war_animals", "quarry", "ore", "reserve_storage", "cavern_logging", "cavern_farm",
    # the fort's reach: new ways, crossings, the deep
    "crossing", "deep_descent", "prisoner_pit",   # (0.105.48 merge) join_levels: survival (cut-off levels, the thirst watch)
    # petitions agreed to, rooms furnished to taste
    "petition_answer", "petition_build", "homes_furnish",
    # the herd's extras
    "tame_wild", "train_hunt", "herd_breeders",
    # waterworks begun or advanced (their shut, retire and recheck still go: SAFE_FLAGS)
    "waterworks_moat", "waterworks_magma", "waterworks_power", "waterworks_irrigation", "waterworks_pump",
    "waterworks_pump_labor",
    # Extreme-low Growth sends a dwarf away
    "expel",
}

_DEFENCE_RULES = {
    "threat_alert", "alerts", "gate", "gates", "gate_guard", "gate_doors", "gate_lever", "gate_parts", "gate_jobs",
    "gate_stuck", "gate_dogs", "entrances", "cavern_openings", "cavern_scan", "seal_cavern", "destroyer_gate",
    "intruder_guard", "thief_watch", "traps", "cages", "near_gates", "near_gates_refresh", "fire_guard", "moon_cell",
    "squad_make", "squad_fill", "squad_trim", "squad_attack", "squad_recall", "soldier_swap", "train",
    "uniform", "uniform_adopt", "unstick_uniforms", "assign_kit", "assign_weapons", "barracks_assign", "kit",
    "arms", "arms_forge", "anvil", "bolts", "crossbow_shop", "quivers", "quivers_order", "gear_fix", "gear_fix_order", "stray_gear",
    "flasks_order", "shelter", "shelter_flee", "shelter_pick", "shelter_refresh", "shelter_squads",
    "shelter_supply", "archer_post", "caravan_guard", "wild_hunt", "cursed", "killer", "prisoners",
    "reanimation", "siege_cleanup", "flood", "animal_trainer",
}

_SURVIVAL_RULES = {
    # water and wells
    "water", "water_traffic", "water_zone", "well", "well_dig", "well_lid", "well_parts", "well_rescue",
    "well_safety", "well_shaft", "cistern", "cistern_parts", "cistern_shut", "frost_water_zone", "frost_well",
    "ice_shore_well", "ice_traffic", "ice_zones", "winter_water", "thirst", "waterworks_shut", "waterworks_check",
    "waterworks_power_run", "magma_guard", "magma_reclaim", "magma_shut", "lure_shut",
    # drink and food
    "drink", "drink_fruit", "booze_variety", "food", "food_barrels", "food_standing", "food_store",
    "food_store_level", "farms", "farm_crops", "surface_farm", "crops", "kitchen", "fat_ban", "meal_variety",
    "good_cooks", "train_cook", "needs_meal", "dairy", "milking", "eggs", "nest_box_order", "fishery",
    "butchery_labor", "butchery_shop", "slaughter", "hunting", "hunting_stop", "fruit_pickers", "fruit_zone",
    "gather", "gather_trim", "tree_quota", "vermin", "herd", "herd_cull", "herd_targets", "pasture",
    "new_pasture", "shearing", "tanning", "containers", "bags",
    # beds, rooms and homes
    "rooms", "homes", "homes_dig", "homes_liked", "noble_rooms", "sync_offices", "furniture", "bootstrap_chair",
    "pair_chairs", "comfort", "cups_home",
    # health and care
    "hospital", "hospital_burrow", "hospital_guard", "doctor_patient", "doctor_post", "staff", "staff_tantrum",
    "care_clean", "care_diagnose", "care_feed", "infected_rest", "traction", "traction_parts", "traction_rest",
    "soap", "soap_rush", "syndrome_clean", "syndrome_quarantine", "miasma_clear", "miasma_dump", "miasma_refuse",
    "rescue_labor", "stranded", "insane", "cave_in_dig_out", "way_in", "way_out", "way_out_dig", "second_way",
    "webs", "remove_webs",
    # the dead
    "burial", "burial_coffins", "burial_corner", "burial_others", "coffins", "slabs", "slabs_free", "slabs_ahead",
    "slabs_ahead_blanks", "slabs_ahead_place", "slabs_ghost", "tombs_ghosts", "ghost_mason", "ghost_masons", "dead_units",
    "necro_corpses",
    # the mind: needs, stress, tantrums, justice, moods
    "stress_care", "needs_craft", "needs_shops", "needs_trinkets", "trinket_orders", "needs_finery",
    "recreation", "calm_burrow", "free_time", "tavern", "tavern_chest", "tavern_urgent", "temple_chest",
    "quick_temple", "quick_tavern", "break_fights", "convict", "chronic_care", "chronic_convict", "chronic_posts",
    "jail_urgent", "jail_size", "jail_more", "prisoners_water", "pit_prisoners", "mothers", "mood",
    "mood_reserve", "mood_shelter", "instrument_orders", "join_levels",
    # the fort's offices and people
    "appoint", "messenger", "pop_cap", "recovery_migrants", "census", "labor", "labor_trim", "petitions",
    "petition_retarget", "residency", "location_access",
    # the work itself: orders, shops, stone, hauling, the dumps
    "stone", "dig_first", "dig_jobs", "project", "build", "planned_parts", "found", "mandate", "cleanup",
    "cleanup_spatter", "cleanup_spatter_dry", "cleanup_dead", "cleanup_dead_dry", "cleanup_items",
    "cleanup_items_dry", "cleanup_units", "cleanup_units_dry", "approve_orders", "order_slots", "orphan_jobs",
    "unsuspend", "stuck_order", "stuck_sweep", "tools", "mechanisms", "bins", "picks", "fuel", "fuel_trim",
    "smelt", "smelting", "steel", "cloth", "crafts", "hauling", "hauling_add", "hauling_back", "hauling_relieve",
    "hauling_shrink", "barrows", "barrow_order", "feeder", "feeder_link", "bench_caps", "excess_shops",
    "disposal_dump", "disposal_empty", "disposal_melt", "disposal_melt_order", "redig", "disposal_orders", "disposal_place_dump",
    "disposal_unforbid", "dump", "refuse", "prune", "prune_keep_parts", "depot", "traffic_audit", "traffic_paint",
    "cavern_logging_stop",
    # trade (the wealth DF sends migrants by)
    "trade", "trade_deal", "call_trader", "open_trade", "close_trade", "unload_depot", "meeting",
}

RULE_CLASS: dict = {}
for _cls, _names in ((SURVIVAL, _SURVIVAL_RULES), (DEFENCE, _DEFENCE_RULES), (EXPANSION, _EXPANSION_RULES)):
    for _n in _names:
        RULE_CLASS[_n] = _cls
RULE_CLASS["strategist"] = SURVIVAL      # (BY_ACTION) its action kind decides

# (rule, action kind) whose step differs from the rule's class
STEP_CLASS = {
    ("depot", "deep_depot"): EXPANSION,     # the depot moved deep (the trade depot itself goes)
    ("bags", "start_project"): EXPANSION,   # a new loom/leather level for bags (the bags order goes)
}

_EXPANSION_ACTIONS = {
    "hunt_send", "build_killzone", "build_lure", "lure_open", "send_mission", "mission_way", "mission_pets",
    "training_squad", "polish", "polish_room", "blueprint_sites", "build_blueprint", "landmark_step",
    "place_hall", "build_wings", "floor_rooms", "place_keep", "place_garden_court", "keep_grove",
    "place_siege_engine", "place_siege_shop", "fortify_post", "build_gatehouse", "cut_entrance",
    "display_artifact", "place_display", "build_crossing", "cross_cavern", "deep_depot", "mine_ore", "quarry",
    "cavern_logging", "cavern_farm", "join_levels", "dig_stairwell", "tame_wild", "train_hunt", "herd_breeders",
    "train_war", "make_pit", "order_instrument", "furnish_liked", "sand_zone", "import_orders", "retarget_hall",
}

_DEFENCE_ACTIONS = {
    "civ_alert", "weather_burrow", "scan_entrances", "build_gate_doors", "fortify_entrance", "arm_gates",
    "link_lever", "place_traps", "reset_cage_traps", "place_gate_lever", "unstick_gate", "open_gates",
    "close_threatened_gates", "free_gate_jobs", "clear_gate", "pull_gate", "guard_gate", "gate_dogs",
    "setup_shelter", "refresh_shelter", "shelter_squads", "shelter_pick", "near_gates", "expel_dwarf",
    "fix_gear_gaps", "assign_quivers", "squad_bolts", "assign_bolts", "squad_fill", "squad_swap", "squad_trim", "make_squad",
    "squad_orders", "squad_routine", "squad_station", "squad_barracks", "hunt_recall", "set_uniform",
    "set_uniform_weapon", "adopt_uniform", "assign_weapons", "assign_kit", "unstick_uniforms", "free_stray_gear",
    "fire_guard", "moon_cell", "seal_cavern", "prisoner_room", "killer_cell", "archer_post", "remove_crossing",
}

_SURVIVAL_ACTIONS = {
    # the game, the bridge and the memory
    "set_rules", "apply_preset", "unpause", "found_fort", "quiet_announcements", "save_game", "report_status",
    "save_memory", "ledger_set", "mark_run", "set_culture", "set_learned", "census", "dismiss_alerts",
    # water, wells, the waterworks' own steps, hazards
    "survey_water", "water_zone", "restrict_water", "place_well", "renew_well_dig", "seal_well_stairs",
    "well_shaft", "well_safety", "well_rescue", "cistern_step", "water_work", "retire_water_zones",
    "magma_guard", "magma_reclaim", "lure_shut", "thirst_unforbid", "thirst_way", "thirst_patient", "thirst_probe", "clear_webs", "remove_webs", "clean_contaminants",
    "quarantine_syndromes", "clear_miasma", "insane_guard",
    # ways in and out for the stranded
    "open_entrance", "dig_way_in", "way_out_open", "way_out_leave", "close_world", "redig_projects", "location_access",
    # food, drink, farms, the herd
    "farm_plots", "farm_thresholds", "set_farm_crops", "kitchen_brewables", "kitchen_fat", "kitchen_skill",
    "train_cook", "gather_plants", "trim_gathering", "hunters", "food_standing", "fruit_zone", "food_pile",
    "food_barrels", "keep_mousers", "pasture", "make_pasture", "nest_boxes", "slaughter_one", "herd_targets",
    "tool",
    # beds, rooms, the needs
    "repair_rooms", "give_room", "house_dwarves", "sync_offices", "pair_chairs", "accept_cups", "bootstrap_chair",
    "recreation", "idle_crafting", "give_trinkets", "quick_location", "trim_instrument_orders",
    # health and care, the dead
    "hospital_burrow", "hospital_guard", "calm_burrow", "rest_infected", "traction_rest", "add_doctor_post",
    "vacate_post", "staff_location", "add_posts", "staff_labors", "mood_free_items", "mood_shelter",
    "allow_burial", "unforbid_dead", "coffins_anywhere", "engrave_memorials", "place_slabs", "free_slabs",
    "bench_jobs", "scrub_dead_units", "prune_remains", "pit_prisoners",
    # justice, tantrums, offices, people
    "break_fights", "convict", "release_prisoners", "tantrum_step_down", "squad_release", "appoint",
    "set_population_cap", "call_migrants", "answer_petition", "petition_orders", "narrow_detail", "trim_labor",
    "assign_labor",
    # the work: orders, projects, stone, hauling, dumps, cleanup
    "work_order", "cancel_work_order", "approve_orders", "unsuspend_orders", "clear_orphan_jobs", "order_slots",
    "stuck_reset", "start_project", "cancel_project", "finish_project", "furnish_project", "engrave_project",
    "unmark_project_dig", "free_dig_jobs", "prioritize_dig", "place_in_zone", "place_surface", "allow_stone",
    "remove_workshops", "add_haulers", "relieve_haulers", "pile_barrows", "feeder_pile", "feeder_link",
    "bench_caps", "mark_melt", "mark_dump", "empty_dump", "place_dump", "set_standing_orders", "unforbid_items",
    "cleanup_items", "cleanup_units", "cleanup_spatter", "cleanup_dead_units", "paint_traffic",
    # trade and diplomacy
    "bring_goods", "unload_depot", "trade_deal", "call_trader", "open_trade", "close_trade", "open_meeting",
    "close_meeting", "answer_meeting",
}

ACTION_CLASS: dict = {}
for _cls, _names in ((SURVIVAL, _SURVIVAL_ACTIONS), (DEFENCE, _DEFENCE_ACTIONS), (EXPANSION, _EXPANSION_ACTIONS)):
    for _n in _names:
        ACTION_CLASS[_n] = _cls

RULE_SETS = {SURVIVAL: _SURVIVAL_RULES, DEFENCE: _DEFENCE_RULES, EXPANSION: _EXPANSION_RULES}
ACTION_SETS = {SURVIVAL: _SURVIVAL_ACTIONS, DEFENCE: _DEFENCE_ACTIONS, EXPANSION: _EXPANSION_ACTIONS}
EXPANSION_RULES = frozenset(_EXPANSION_RULES)
EXPANSION_ACTIONS = frozenset(_EXPANSION_ACTIONS)


def _recovery_rules() -> set:
    """crisis.RECOVERY_RULES (crisis.py imports this module: read late)."""
    try:
        import crisis
        return crisis.RECOVERY_RULES
    except Exception:  # noqa: BLE001
        return set()


def rule_class(rule) -> str | None:
    """The rule's class, or None for a rule in no class."""
    return RULE_CLASS.get(rule)


def step_class(p) -> str:
    """survival, defence or expansion for one proposal (see the module's text)."""
    a = getattr(p, "action", None)
    a = a if isinstance(a, dict) else {}
    t = a.get("type")
    rule = getattr(p, "rule", None)
    if t == "start_project":
        if a.get("urgent") or rule == "mood":
            return SURVIVAL
        if RULE_CLASS.get(rule) == EXPANSION or STEP_CLASS.get((rule, t)) == EXPANSION:
            return EXPANSION
        if a.get("set_piece") or a.get("growth") or a.get("landmark"):
            return EXPANSION
        if rule in _recovery_rules() or a.get("kind") in SURVIVAL_KINDS:
            return SURVIVAL
        return EXPANSION
    if any(a.get(k) for k in SAFE_FLAGS):
        return SURVIVAL
    c = STEP_CLASS.get((rule, t))
    if c:
        return c
    c = RULE_CLASS.get(rule)
    if c and rule not in BY_ACTION:
        return c
    return ACTION_CLASS.get(t, SURVIVAL)


def held_words(p) -> str | None:
    """What waits (in words) when the step is expansion, else None."""
    if step_class(p) != EXPANSION:
        return None
    a = getattr(p, "action", None)
    a = a if isinstance(a, dict) else {}
    t = a.get("type")
    if t == "start_project":
        return f"a new {a.get('set_piece') or a.get('kind') or '?'} level"
    if ACTION_CLASS.get(t) == EXPANSION:
        return str(t).replace("_", " ")
    return str(getattr(p, "rule", "?")).replace("_", " ")
