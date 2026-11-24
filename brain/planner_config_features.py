"""planner_config_features: part of PLANNER_CONFIG (brain/planner_config.py), split out in
r7 d6 and applied fourth: the 0.105.41-0.105.47 features: provisions, captives, peace, paper, forestry,
benches, hunting, shelter, the stuck sweep, kill zones, the order loop, thirst,
collapse recovery, mood help, meetings, tantrums, training squads, welfare,
well safety, holding fast, ice, descent, the storage district, gardens.
Moved verbatim: keys, values, order and comments as they were."""

__all__ = ["PART"]

PART = {
    # (0.105.41, item 4) provisions from the land (brain/planner_provisions.py)
    "hunt_min_citizens": 7,               # hunters only in a fort of this many
    "hunt_game_min": 1,                   # wild animals (no danger) on the surface before hunters go out
    "hunters_max": 2,                     # a hunter or two
    "hunt_bolts_per_hunter": 25,          # bolts to spare (after the crossbow squads' own) for each hunter
    "hunt_quiet_days": 3,                 # no hunting this soon after a threat could reach the dwarves
    "hunting_cooldown_ticks": 7 * 1200,
    "hunting_stop_cooldown_ticks": 300,   # the AI's hunters called in: asked every quarter day while danger lasts
    "butcher_corpses_min": 1,             # unbutchered bodies before a butcher is wanted
    "butcher_shop_corpses": 3,            # ...and before a butcher's shop is built for them
    "tan_hides_min": 2,                   # raw hides lying about before a tanner, a tanner's and a tan order
    "tan_order_max": 10,
    "food_standing_cooldown_ticks": 7 * 1200,
    "butchery_labor_cooldown_ticks": 3 * 1200,
    "butchery_shop_cooldown_ticks": 14 * 1200,
    "tanning_cooldown_ticks": 3 * 1200,
    "fruit_trees_min": 5,                 # fruit trees near the fort before a fruit-gathering zone
    "fruit_stand_min": 3,                 # ...and at least this many in its stand
    "fruit_min_citizens": 7,
    "fruit_pickers": 1,                   # gatherers wanted while a fruit zone stands and nobody gathers
    "fruit_zone_cooldown_ticks": 28 * 1200,
    "fruit_pickers_cooldown_ticks": 7 * 1200,
    "meal_variety_min_pd": 2,             # meals a dwarf before their kinds are looked at (the food rule fills short stores)
    "meal_variety_share": 0.75,           # one kind this much of the servings...
    "meal_variety_low": 0.15,             # ...and another under this much: a few jobs of it
    "meal_variety_jobs": 3,
    "meal_variety_cooldown_ticks": 7 * 1200,
    "cavern_farm_tiles": 24,              # tiles of plots a call on cavern soil...
    "cavern_farm_max_tiles": 60,          # ...and at most this many of the AI's there in all
    "cavern_farm_cooldown_ticks": 14 * 1200,
    # (item6) prisoners' outcomes and necromancer sieges (brain/planner_captives.py)
    "pit_min_drop": 7,                        # levels of open space under the AI's pit: a fall that kills
    "pit_batch": 3,                           # prisoners sent to the pit a call
    "prisoner_pit_cooldown_ticks": 7 * 1200,  # the pit zone looked for a week apart
    "pit_prisoners_cooldown_ticks": 1200,
    "undead_overwhelm_min": 6,                # this many walking dead in a siege before they can overwhelm...
    "undead_per_soldier": 2.0,                # ...and more than this many to an armed soldier
    "undead_per_soldier_raiser": 1.0,         # ...or this many with a raiser on the map (the fallen rise)
    "necro_corpses_min": 3,                   # bodies outside with the dead about: rotted away
    "necro_corpses_cooldown_ticks": 1200,
    "necro_tower_near": 40,                   # world tiles: a necromancer tower this close is said
    # (0.105.41, item 8) war and peace (brain/planner_peace.py, lua/ai-diplomacy.lua peace_verdict)
    "peace_min_sieges": 2,                # the Rules' "AI decides": peace from a civ that besieged the fort this often...
    "peace_slider_step": 50,              # ...one more siege wanted a step of Militarism, one fewer a step of Caution
    "peace_forgive": 100,                 # a civ the fort attacked: peace only when Caution beats Militarism by this
    "peace_attacked_keep": 40,            # civs the fort attacked, kept in memory (the newest)
    # (item9) paper from plants, scrolls and codices for the library (brain/planner_paper.py)
    "paper_batch": 5,                     # reactions an order
    "paper_plants_keep": 10,              # papyrus sedge or slurry plants never milled (food, drink, seeds' plants)
    "paper_food_per_dwarf_min": 10,       # plants go to paper only with this much food a dwarf (and drink on target)
    "paper_scrolls_keep": 4,              # blank scrolls kept once the library has its paper
    "paper_scroll_sheets_spare": 2,       # sheets kept back for quires before any is rolled into a scroll
    "paper_codex_batch": 2,               # written quires bound into codices an order
    "paper_wood_min": 10,                 # logs before scroll rollers or book bindings are carved
    "paper_cooldown_ticks": 1200,
    "paper_shop_cooldown_ticks": 14 * 1200,
    # (item10) cavern logging and the grove (brain/planner_forestry.py)
    "cavern_logging_surface_min": 20,     # cavern trees felled while fewer surface trees than this stand (the grove's not counted)
    "cavern_logging_batch": 10,           # trees the AI keeps marked in the caverns at a time
    "cavern_logging_cooldown_ticks": 2 * 1200,
    "grove_min_saplings": 6,              # saplings on the surface before a grove is kept
    "grove_release_wood": 5,              # fewer logs than this: the grove's trees are left to the woodcutters
    "grove_cooldown_ticks": 7 * 1200,         # choosing the grove (a refusal waits this long)
    "grove_guard_cooldown_ticks": 100,        # the grove's marks lifted at most this often (autochop re-marks each cycle)
    # (item10) training benches (brain/planner_benches.py)
    "bench_training_max_level": 5,        # the training bench's max skill (df skill rating: 5 Proficient)
    "bench_learners_min": 2,              # workers below it before a bench is capped
    "bench_caps_cooldown_ticks": 1200,
    # (0.105.45) hunting: squads sent after a threat they clearly beat (brain/planner_hunt.py)
    "hunt_ratio": 3.0,                    # the party's strength at least this times the target's (1.5 x fight_ratio: optional)
    "hunt_slider_weight": 0.5,            # Caution over Militarism by 200 raises the bar by 2^this (and the other way)
    "hunt_ratio_min": 2.4,                # ...never below this (nor below fight_ratio)...
    "hunt_ratio_max": 6.0,                # ...nor above this
    "hunt_reserve_min": 3,                # soldiers left home at least ("a guard in every fort")...
    "hunt_reserve_share": 0.34,           # ...and at least this share of all soldiers (one whole squad stays with 2+)
    "hunt_max_days": 3,                   # a hunt longer than this is called back
    "hunt_rest_days": 5,                  # a timed-out target rests this long before another hunt
    "hunt_great_militarism_min": -100,    # great dangers hunted only with Militarism above this...
    "hunt_great_caution_max": 150,        # ...and Caution below this
    "hunt_learned_keep": 60,              # history outcomes remembered as learned (each counted once)
    "hunt_cooldown_ticks": 300,           # a new hunt at most every quarter day
    # (0.105.45) the shelter away from the threat, the squads between (brain/planner_shelter.py)
    "shelter_pick_margin": 5,             # the threat's walk to a shelter this many steps longer than the civilians' (90%) at least
    "shelter_pick_max_levels": 3,         # levels one shelter spans at most (for room and drink)
    "shelter_pick_hysteresis": 10,        # a pick in use kept unless the new one is this much farther from the threat
    "shelter_pick_cooldown_ticks": 300,   # the shelter redrawn at most this often (shelter_flee: at once)
    "shelter_flee_tiles": 20,             # a great danger inside the fort this close (walk) to the shelter: moved at once
    # (0.105.48, K1) a shelter must hold the civilians: room, drink and food for the stay, or a bigger one
    "shelter_pick_food_per_civ": 2,       # food units a civilian (as the bridge's SHELTER_FOOD_PER_CITIZEN)
    "shelter_pick_wide_levels": 6,        # a shelter that can't hold them in shelter_pick_max_levels: up to this many
    "shelter_widen_ticks": 600,           # no danger that can come this long: the whole fort again, alarm up or not
    "shelter_choke_min_tiles": 10,        # the squads' choke this many steps from the shelter at least
    "shelter_choke_max_width": 4,         # ...and no wider than this (walkable neighbours on its level)
    # (0.105.45) the sweep for things stuck "in progress" (brain/planner_stuck.py, lua/ai-stuck.lua):
    # game days without progress before the sweep acts, per kind (the things' own rules act sooner)
    "stuck_sweep_project_days": 84,           # a level's dig or furnishing (the level rules act at 14-56 days)
    "stuck_sweep_cistern_days": 84,           # a cistern step
    "stuck_sweep_waterwork_days": 84,         # a moat, pump, irrigation, magma or power step
    "stuck_sweep_lever_days": 2,              # a pull job on an AI lever nobody does
    "stuck_sweep_squad_days": 1,              # an AI kill order whose targets are all dead, gone or caged
    "stuck_sweep_order_days": 56,             # an AI work order (the orders rule cancels at 28)
    "stuck_sweep_gate_days": 42,              # gate pieces the AI planned (the gate rules act at 7-14)
    "stuck_sweep_nudge_wait_days": 14,        # after the nudge, this long (at most half the timeout) before the retire
    "stuck_sweep_backoff_days": 112,          # after a retire: the thing left this long
    "stuck_sweep_family_max": 3,              # retires of one kind of thing a game year; past it, only said
    "stuck_sweep_actions_max": 2,             # the sweep's actions a cycle
    "stuck_sweep_notes_max": 6,               # its notes a cycle
    "stuck_sweep_cooldown_ticks": 0,          # (it paces each thing itself)
    # (0.105.45) kill zones at the gates and cavern openings (brain/planner_killzone.py, lua/ai-killzone.lua)
    "killzone_min_citizens": 8,           # a fort this big before it builds kill zones (a crisis or a fight: none)
    "killzone_slider": 0,                 # Fortification or Caution at least this: entrances enemies used, the beasts' caverns
    "killzone_all_slider": 80,            # ...this: every gate and cavern opening the AI holds
    "killzone_closed_outsiders": -50,     # Outsiders this low (a closed fort, the Hermit hold): every entrance, first
    "killzone_used_min": 1,               # enemies seen at an entrance (the atlas' per-gate records) before it is "used"
    "killzone_traps": 4,                  # traps a zone (the stretch allows 3-6)
    "killzone_traps_high": 6,             # ...at Fortification or Caution killzone_all_slider and up
    "killzone_cooldown_ticks": 1200,      # one step (a zone, or the next step of its drawbridge) a game day
    "killzone_stage_days": 20,            # (0.105.48) a zone still building this long no longer holds the next one
    # (0.105.45) a great beast sealed in a cavern lured into a pocket and cut off (brain/planner_lure.py)
    "lure_after_days": 7,                 # a great danger sealed in the caverns this long: the lure is built
    "lure_open_days": 3,                  # open this long with nothing caught: shut again...
    "lure_retry_days": 4,                 # ...and opened again after this, doubled each try...
    "lure_retry_max_days": 56,            # ...up to this
    "lure_build_cooldown_ticks": 600,     # the pocket's next step (pieces, levers, links) twice a day at most
    "lure_open_cooldown_ticks": 300,
    "lure_shut_cooldown_ticks": 25,       # shutting is safety: soon again if it didn't take
    "lure_archer_cooldown_ticks": 1200,
    # (0.105.46, I3) the order loop (brain/order_check.py)
    "order_check": True,                  # inputs, fuel, a free workshop and a worker checked before any order
    "order_miss_days": 56,                # a stuck cancel's recipe (and metal) not ordered again until what it lacked changes, or this long
    "approve_on_place_days": 112,         # the AI approved its own orders this recently: its new ones are approved as placed
    # (0.105.46, I2) the thirst watch (brain/planner_thirst.py, lua/ai-thirst.lua)
    "thirst_act_timer": 35000,            # a dwarf this thirsty gets a remedy (DF: thirsty 25000, dehydrated 50000)
    "thirst_note_timer": 25000,           # ...and a note from here (only with a reason the AI can name)
    "thirst_retry_ticks": 600,            # the same remedy for the same dwarf again after half a day at the soonest
    "thirst_notes_max": 8,                # dwarves noted one by one a cycle (the rest in one line)
    "thirst_actions_max": 6,              # remedies a cycle
    "thirst_unforbid_max": 10,            # drinks let go for one dwarf
    "thirst_cooldown_ticks": 0,           # (it paces each dwarf itself)
    # (0.105.46, I4) collapse recovery (brain/planner_recovery.py): survival mode for a fallen fort
    "recovery_floor_min": 12,             # the floor: at least this many citizens...
    "recovery_floor_peak_share": 0.25,    # ...or this share of the most the fort ever had
    "recovery_drop_share": 1 / 3,         # or a fall of this share within a game year...
    "recovery_drop_min": 15,              # ...from a year's high of at least this many
    "recovery_leave_days": 84,            # back at the floor or over this long (a season): recovery ends
    "recovery_min_days": 84,              # and it lasts at least this long
    "recovery_cap_room": 10,              # DF's cap opened to at least this many over the citizens
    "recovery_migrants_wait_days": 168,   # no newcomer this long while recovering: a migrant wave is called
    "recovery_migrants_cooldown_ticks": 112 * 1200,   # one call a season at most
    "recovery_migrants_max_calls": 3,     # calls that brought nobody before it stops (a Needs you)
    "recovery_stall_days": 336,           # under the survival floor with no newcomer this long: called too
    # (0.105.47, J1) the strange moods' failures (brain/planner_mood_help.py, lua/ai-mood-help.lua; I7a)
    "mood_dead_cancels": 2,               # an order whose jobs DF cancelled this often lately is a failed route
    "mood_webs_keep": 50,                 # webs a weaver can reach kept from remove_webs while silk is wanted
    "mood_webs_collect": 5,               # webs collected (CollectWebs jobs) an order
    "mood_shelter_cooldown_ticks": 100,   # a gathering mood's tiles put in the shelter again after this
    "mood_claim_cap_days": 6,             # no workshop claimed this long: one more built past the AI's cap
    # (0.105.47) meetings (brain/planner_meetings.py, lua/ai-meeting-open.lua)
    "meeting_open_every_s": 60,           # a meeting waiting behind DF's diplomacy light clicked at most this often (real s)
    "meeting_reopen_after_s": 1800,       # ...and after leaving one it couldn't answer, not again for this long (real s)
    # (0.105.47, R2 item 3) tantrums one dwarf at a time (brain/planner_tantrums.py, lua/ai-tantrums.lua)
    "staff_tantrum_cooldown_ticks": 100,  # a post taken from a tantrum-thrower (one a cycle, soon the next)
    "break_fights_report_ticks": 600,     # a tantrum, berserk or possession report this recent: fix/loyaltycascade
    "hospital_guard_on": True,            # a calm squad stationed at each hospital while a tantrum is loose
    "hospital_guard_hold_ticks": 3600,    # ...kept 3 days after the last tantrum seen loose (0.105.93: B runs ~1300 ticks a cycle, a day ran out every cycle: 58 posts and recalls an hour)...
    "hospital_guard_max_days": 7,         # ...and never longer than this at a stretch (they eat, drink and train)
    "hospital_guard_cooldown_ticks": 50,
    "chronic_tantrums": 3,                # tantrums in a year that make a chronic case (handled one dwarf at a time)
    "chronic_posts_cooldown_ticks": 300,
    "chronic_care_cooldown_ticks": 1200,  # one of their unmet needs met a day, in turn
    "chronic_convict_on": True,           # the last resort: that dwarf's own solved cases convicted, behind the checks...
    "chronic_convict_tantrums": 5,        # ...only after this many in a year...
    "chronic_convict_after_days": 28,     # ...this long after they became a chronic case (their needs tried first)
    "chronic_convict_cooldown_ticks": 8400,
    "crisis_kill_days": 14,               # a citizen killed by a citizen this recently: crisis mode
    "crisis_repeat_dwarves": 2,           # ...or this many dwarves...
    "crisis_repeat_tantrums": 2,          # ...each with this many tantrums in 28 days
    "crisis_tantrum_quiet_days": 14,      # a crisis is not over while a tantrum was seen this recently
    # (0.105.47, R2) the training squad and the end of the squad ping-pong (brain/planner_training.py)
    "training_squad_welfare": 50,         # Welfare this high or more allows a training-only squad (the Monastery: 80)
    "training_squad_max": 10,             # its size: at most this many (a DF squad holds 10)...
    "training_squad_adults_per": 5,       # ...and at most one per this many adults (a fifth)
    "training_squad_min": 2,              # no training squad where the cap comes out under this
    "training_squad_keen_min": 2,         # made once this many civilians badly want to fight or train
    "training_squad_fill_max": 3,         # volunteers added a cycle at most
    "training_hall_beds": 4,              # (0.105.51) the training hall dug when the fort has no barracks (the least a barracks level takes)
    "training_squad_cooldown_ticks": 1200,   # a day between its steps
    "never_draft_days": 672,              # stress care's "never draft" kept two years at most...
    # (0.105.47, I7b) the unburied dead and welfare in small forts (brain/planner_welfare.py, lua/ai-welfare.lua)
    # (0.105.51) was 84 days and 10 dead: C's 9 dead lay unburied a season before any coffin, and a ghost killed a dwarf
    "burial_fallback_days": 14,           # the dead outnumber the free tombs this long while a tomb level is under way: coffins anywhere
    "burial_fallback_refused_days": 7,    # ...or this long after a tomb level's search failed
    "burial_fallback_unburied": 1,        # ...or at once when this many more dead than free tombs wait and no tomb level is under way
    "burial_others_max": 50,              # (0.105.51) the bodies DF never buries (visitors', other civs') marked for the dump in one go
    "burial_others_cooldown_ticks": 3 * 1200,
    "burial_corner_max": 10,              # coffins placed on the AI's other levels in one go
    "burial_corner_cooldown_ticks": 7 * 1200,
    "burial_coffins_cooldown_ticks": 3 * 1200,
    "slabs_ahead_max": 5,                 # memorial slab orders for the dead nobody can reach, a go
    "slabs_ahead_cooldown_ticks": 3 * 1200,
    "slabs_ahead_blanks_cooldown_ticks": 3 * 1200,
    "slabs_ahead_place_cooldown_ticks": 2 * 1200,
    "stress_need_care": True,             # stress care answers the dwarf's top unmet need when bedroom and squad aren't it
    "meals_cap_skip_share": 0.25,         # lavish meals past meals_hard_max_pd while this share of the fort badly wants a good meal
    "cook_train_max_citizens": 40,        # a fort this small or smaller keeps one cook at the kitchens to learn...
    "cook_train_below": 5,                # ...while the best free cook is under this skill (5: proficient)
    "cook_train_cooldown_ticks": 7 * 1200,
    # (0.105.47) cavern wells made safe (brain/planner_wellsafe.py, lua/ai-well-safety.lua)
    "cavern_well_cooldown_days": 84,      # no new cavern well this long after one was given up (a season)
    "cavern_well_site_tries": 2,          # a shaft site given up this often is kept free
    "well_safety_cooldown_ticks": 300,    # the watcher, the column's traffic, the door, the next level: a few times a day
    "well_rescue_after_ticks": 200,       # stranded under a well this long (DF's no path): a way up
    "well_rescue_near": 15,               # a stranded dwarf this near a well's shaft (across) is under it
    "well_rescue_cooldown_ticks": 300,    # tried again this often (it waits while a danger is near)
    # (0.105.47, R2 item 7) holding fast: titans and thieves (brain/planner_holdfast.py)
    "one_enemy_gate_tiles": 20,           # one ordinary enemy this close to a gate: the gates stay shut for it
    "kill_hold_ticks": 1200,              # a squad's kill order held a game day at least (no recall flapping)
    "destroyer_wall_min_tiles": 15,       # a building destroyer this close to a door-only gate: nothing built there now
    "post_rest_min_ticks": 300,           # a squad out to eat comes back once fed, after this at least
    # (0.105.47, I7d) surface work kept near the gates while a great danger the
    # squads can't beat is about (brain/planner_near_gates.py, lua/ai-near-gates.lua)
    "near_gates": True,                   # the rule on (False: never)
    "near_gates_radius": 25,              # outside tiles this near a surface way in stay in the work burrow
    "near_gates_hold_days": 3,            # kept this long after the last such danger left the map
    "near_gates_cooldown_ticks": 300,     # the burrow taken up or let go at most this often
    "near_gates_refresh_cooldown_ticks": 1200,   # newcomers taken into it once a day at most
    # (0.105.47, I7d 2f) ice: surface water zones, shore wells and traffic before the freeze (brain/planner_ice.py)
    "ice_late_autumn_tick": 285600,       # the year's tick from which surface water counts as freezing (15 Timber)
    "ice_temp_margin": 15,                # surface this near freezing (Urist degrees over 10000): ice season any month
    "ice_warm_margin": 40,                # ...this far over it in late autumn and no ice ever seen: a warm biome, no guard
    "ice_traffic_cooldown_ticks": 7 * 1200,
    "ice_zones_cooldown_ticks": 1200,
    "ice_shore_well_cooldown_ticks": 1200,
    # (0.105.47) Verticality: the stair past the first cavern (brain/planner_descent.py, lua/ai-descent.lua)
    "deep_descent": False,                # (0.105.48) off: no crossing, no level under it; on here or by the Rules switch
    "descent_min_citizens": 20,           # the fort this big before its stair goes past the first cavern...
    "descent_min_levels": 8,              # ...and this many levels in its plan's districts
    "descent_storage_citizens": 40,       # the storage district's new levels go under it from this many citizens
    "descent_homes_verticality": 150,     # and the homes' too at this Verticality...
    "descent_homes_citizens": 60,         # ...from this many citizens
    "descent_band_levels": 6,             # the band of levels under the crossing
    "deep_descent_cooldown_ticks": 600,   # a step a half day at most (each waits for the last to be dug or built)
    # (0.105.47) Stockpile: the storage district (brain/planner_reserves.py)
    "stockpile_signature": True,          # off: 2^(Stockpile/100) on the targets alone, as before
    "reserve_storage_min": 30,            # from this Stockpile a fort digs storage levels for its reserves...
    "reserve_vault_citizens": 20,         # ...one more for this many citizens / (stock factor - 1)
    "reserve_vault_max": 8,               # at most this many storage levels for it
    "reserve_vault_min_citizens": 15,
    # (0.105.47) the Garden fort's gardens (brain/planner_garden.py, lua/ai-builder-court.lua)
    "garden_fort": True,                  # all of it: the field customs under surface fields, the court, gardens in soil, sooner
    "garden_court_agriculture": 100,      # the garden court above ground: Agriculture this high...
    "garden_court_grandeur": 30,          # ...Grandeur this high...
    "garden_court_surface": 50,           # ...and Surface this high (the Garden fort: 120, 40, 80)
    "garden_court_wish_surface": -50,     # a design wish for one (nature lovers): any fort above this Surface
    "garden_court_min_citizens": 20,
    "garden_court_material": 50,          # blocks, stone or logs free for its walls (and paths)
    "garden_court_paths_grandeur": 30,    # block paths with Grandeur this high
    "garden_court_cooldown_ticks": 1200,  # a step a day at most
    "garden_court_lift_ticks": 1200,      # (r9 c1) its meeting area on again a day after the last danger read (the gates' lift)
    "court_meeting_cooldown_ticks": 100,  # (r9 c1) the meeting area switched at most every 100 ticks (the watcher's look)
    "garden_agri_pace_div": 150,          # statue gardens sooner by Agriculture: x2 ** (Agriculture / this) (120: x1.7)
}
