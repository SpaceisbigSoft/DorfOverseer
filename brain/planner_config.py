"""planner_config: the planner's tuning numbers (PLANNER_CONFIG), split out of
planner_core in 0.105.25 (13c). Every rule reads them as `cfg[...]`; select()
reads `<rule>_cooldown_ticks` by the rule's name (default rule_cooldown_ticks).
planner_core re-exports PLANNER_CONFIG, so `from planner_core import PLANNER_CONFIG`
works as before."""

__all__ = ["PLANNER_CONFIG", "DISPOSAL_ACTION_MAX"]

# (0.105.27 fixes) The most items one disposal action (unforbid_items,
# mark_melt, mark_dump, empty_dump) may take a call: the bridge refuses a
# bigger max (lua/ai-bridge-actions.lua DISPOSAL_MAX, lua/ai-disposal.lua
# MAX_CAP, both 500; tests/test_disposal_fixes.py checks the three agree).
# _disposal_rules caps every disposal max here.
DISPOSAL_ACTION_MAX = 500

PLANNER_CONFIG = {
    # Starting guesses, tuned from experience. Per citizen, before trait factors.
    # These are ITEM counts (what the stocks report counts).
    "drink_per_dwarf": 10,
    "meals_per_dwarf": 8,
    "blocks_per_dwarf": 5,
    "wood_per_dwarf": 2,
    "urgent_drink_per_dwarf": 2,
    "urgent_meals_per_dwarf": 2,
    # Work orders count JOBS, and one job makes several items. Conservative
    # (low) guesses, so the AI under-orders rather than over-orders.
    "drinks_per_job": 5,     # one plant -> 5 drinks
    "blocks_per_job": 4,     # one boulder -> 4 blocks
    "meals_per_job": 10,     # (0.100) a job's 2-4 ingredient stacks make some 10-20 servings (DF wiki, Kitchen)
    "food_stack_size": 5,    # (0.100) raw food items per ingredient stack, when the bridge sends no stack count
    # Order sizes (jobs)
    "min_order": 10,
    "max_order": 100,
    "idle_order_min": 20,          # jobs: it's about giving idle hands work
    "idle_order_max": 50,
    "mandate_max": 10,
    # Rules
    "idle_share": 0.25,            # share of adults idle before "idle hands" fires (idle_adults/adults: the industry, trade and world rules)
    "idle_blocks_share": 0.14,     # (0.105.33 fix) the blocks rule's line on the stricter idle measure (_idle_share): was idle_share
                                   # (0.25) on idle_adults/adults, 54 states over it in the 8 Nov run; 53 at 0.14. Leans with idle_share
    "glass_fuel_min": 2,           # (0.104.95) coal bars before a glass job is ordered
    "glass_sand_bags": 3,          # bags of sand kept filled
    "precious_crafts_bars": 10,    # bars of a precious metal kept back before crafts are made of it
    "min_boulders_for_blocks": 100,
    "blocks_cap": 500,                 # (0.104.110) idle hands never make blocks past this many
    "alert_quiet_cycles": 3,       # quiet cycles before the AI lowers its own alert
    # (0.104.100) ...and game days since a threat last could reach the dwarves, and
    # since a great danger (titan, beast) was last on the surface or in reach: the
    # alert dropped 10 s after a titan died and 15 dwarves died outside in the next 50
    "alert_quiet_days": 3,
    "alert_quiet_days_great": 7,
    "shelter_max_days": 3,             # (0.105.22) a squad on the shelter order this long at most...
    "shelter_rest_days": 2,            # ...then this long off it to eat and drink
    "shelter_hold_tiles": 20,          # (0.105.26) ...but not while a great danger or siege is this close to the dwarves
    "fight_ratio": 2.0,            # (0.104.118) squads at least this many times a great danger's strength: they go
    "cautious_alert_levels": 10,   # Caution +100: react to unknown-reach threats this close
    # Building (docs/building.md)
    "spare_beds_share": 0.1,       # beds wanted beyond one per citizen
    # Growth slider -> target population: -100 / 0 / +100; past +100 (Extreme) it
    # keeps rising, no cap at +200; past -100 no newcomers, one dwarf sent away
    # every shrink_days * 100/(|v|-100) days (0.94: Extreme doubles, as everywhere).
    "growth_points": {"low": 25, "average": 100, "high": 250},
    "shrink_days": 28,
    "min_citizens": 7,             # never sent away below this
    "uncapped": 1000,              # the population cap used for "no cap"
    # (0.104.106, the 38-year soak) newcomers wait while the fort can't carry
    # the dwarves it has: Teacheroar grew 98 -> 438 under "no cap", drink fell
    # to 0.08 a dwarf, 50-60% unhappy for 7 years, FPS 87 -> 18. Held at its
    # size while any of these holds; let go once all are back past the "ok" side
    "strain_unhappy_pct": 20, "strain_unhappy_ok_pct": 12, "strain_unhappy_min": 3,   # (0.105.8) and this many unhappy dwarves at least
    "strain_drink_pd": 2.0, "strain_drink_ok_pd": 4.0,
    "strain_meals_pd": 2.0, "strain_meals_ok_pd": 4.0,
    "beds_ahead": 20,              # Expand: bedrooms up to this many ahead of the population
    "maintain_spare_beds": 2,
    "min_spare_beds": 5,
    "dwarves_per_table": 3,
    "dining_short_share": 0.5,
    "tavern_badly_per": 30, "temple_badly_per": 25,   # (0.104.137) a tavern / temple for every this many badly missing...
    "social_badly_share": 0.15, "social_halls_max": 6,   # ...once that many of the fort badly miss it; at most this many
    "min_dwarves_for_dining": 3,                # (0.100.1) was 7
    "min_dwarves_for_hospital": 20,
    "min_dwarves_for_small_hospital": 10,  # ...or this many with a chief medical dwarf (not a young fort)
    "urgent_hospital_waiting": 2,
    "hospital_outside_min": 5,         # (0.104.121) wounded resting with no hospital bed before another is dug...
    "hospital_beds_max": 30,           # ...up to this many hospital beds in all
    "urgent_temple_share": 0.5,        # (0.103.12) this share of the citizens longing to pray, no real temple: a shrine at once
    "urgent_tavern_share": 0.33,       # (0.104.35) this share badly wanting company, only the stop-gap tavern: a tavern at once
    "train_all_share": 0.15,           # (0.104.53) this share badly wanting to train: every squad trains, none rests
    "train_all_off_share": 0.07,       # (0.104.149) ...and once all train, they keep on until under this share
    "dwarves_per_restraint": 10,       # (0.104.52) a jail restraint for this many citizens...
    "jail_restraints_max": 12,         # ...up to this many
    # Supplies (docs/local-planner.md)
    "empty_containers_per_dwarf": 0.1,   # free barrels + pots wanted, per citizen
    "min_empty_containers": 10,
    "empty_bags_per_dwarf": 0.05,
    "bins_per_dwarf": 0.5,
    "min_bins": 6,
    "bins_for_goods_step": 40,         # (0.104.75) at most this many more bins at a time for full goods piles
    "bring_goods_full": 120,           # (0.104.78) crafts to the depot a call while the goods piles are full
    "min_empty_bags": 5,
    "hospital_items_per_dwarf": 0.025,   # splints, crutches: 1 per 40 citizens
    "min_hospital_items": 2,
    "min_buckets": 3,
    # The dead, moods, leisure (game systems audit, step 3)
    "min_free_tombs": 2,
    "free_tombs_per_dwarf": 0.02,
    "min_dwarves_for_tavern": 15,
    "urgent_jail_tantrums": 5,           # (0.104.31) tantrums in 28 days that bring the jail ahead of the levels
    "min_dwarves_for_jail": 15,          # a jail once the fort has a sheriff and this many dwarves
    "dwarves_per_cell": 25,              # a jail cell per this many dwarves (2 to 8)
    "min_dwarves_for_library": 40,
    "mood_claim_days": 2,          # days before "hasn't claimed a workshop" is said
    # Military (docs/military.md)
    # soldiers as a share of citizens, from the Militarism slider:
    # -100 -> 5%, 0 -> 10%, +100 -> 40% (straight lines between);
    # past +100 (Extreme) up to 90% at +200; past -100 down to none at -200 (0.94)
    "soldier_share_low": 0.05,
    "soldier_share_mid": 0.10,
    "soldier_share_high": 0.40,
    "soldier_share_extreme_high": 0.90,
    "min_squad_to_fight": 3,       # members a squad needs before it's sent at a threat
    "berserk_resend_ticks": 1200,  # (v35 fix) a squad sent at a berserk dwarf is not sent at them again for a day
    # (v35 fix) the most dwarves a labour rule gives its labour in a game year
    "care_feed_labor_cap": 4, "care_clean_labor_cap": 4, "care_diagnose_labor_cap": 4,
    "ghost_mason_labor_cap": 4, "pump_labor_cap": 6,
    "max_fill_per_cycle": 5,
    "gate_cooldown_ticks": 600,
    "entrance_scan_ticks": 7 * 1200,   # map the entrances again once a week
    "gate_gone_ticks": 28 * 1200,      # a gate built 4 weeks ago and the entrance still open: build again
    "fortify_max_width": 50,           # wider openings are left to the player
    "gate_retry_ticks": 14 * 1200,     # a refused entrance is tried again after 2 weeks (things change)
    "gate_lever_cooldown_ticks": 14 * 1200,
    "found_cooldown_ticks": 3 * 1200,  # the first stair: wait 3 days for the miners before asking again
    "labor_cooldown_ticks": 1200,
    "labor_trim_margin": 5,              # (0.104.166) a detail this many over what the job wants: cut back
    "labor_trim_cooldown_ticks": 7 * 1200,   # ...a week apart
    "feeder_cooldown_ticks": 1200,     # a feeder stockpile: at most one a day
    "perf_slow_cycle_factor": 2,      # (0.105.40) while the game runs slowly the full report this many times further apart
                                      # (never while a threat or a siege is on: brain/perf.py cycle_factor)
    "fps_items_heavy": 30000,          # this many items while the game runs slowly: tidy up
    "urgent_unburied": 10,             # (0.104.12) this many dead unburied: a tomb level of its own slot
    "free_time_cooldown_ticks": 7 * 1200,   # (0.104.10) work details narrowed (or widened) a week apart
    "free_time_min_pop": 30,
    "free_time_friends_share": 0.2,         # this share badly wanting friends ...
    "free_time_idle_below": 0.1,            # ... while fewer than this share are idle: narrow
    "free_time_widen_share": 0.05,          # back to everybody below this share
    "instruments_cooldown_ticks": 28 * 1200,   # (0.104.8) an instrument order a month
    "unsuspend_cooldown_ticks": 2 * 1200,
    "burial_cooldown_ticks": 3 * 1200,
    "rooms_cooldown_ticks": 3 * 1200,
    "coffins_cooldown_ticks": 2 * 1200,
    "jail_size_cooldown_ticks": 7 * 1200,      # (0.104.52) a chain a week at most
    "water_traffic_cooldown_ticks": 28 * 1200,   # (0.104.45) the water re-checked once a month
    "fat_ban_cooldown_ticks": 7 * 1200,        # (0.104.30) fat and tallow kept from the cooks, a week apart
    "slaughter_cooldown_ticks": 14 * 1200,  # (0.104.7) one animal to the butcher a fortnight, while there's no fat for soap
    "slaughter_min_tame": 10,
    "tavern_cooldown_ticks": 14 * 1200,   # (0.104.6) goblets a fortnight apart: a finished order isn't a full tavern
                                          # (cups made and not yet in its chest read as 0: ordered again every cycle)
    "prune_cooldown_ticks": 403200,    # (0.104.0) once a game year: deteriorate stays on in the save
    "dump_cooldown_ticks": 7 * 1200,
    # the keep above ground (Surface ambition): one step a day at most
    "keep_cooldown_ticks": 1200,
    "keep_surface_min": 50,
    "keep_min_citizens": 15,
    "keep_min_material": 60,
    # (0.105.30, construction G4: brain/planner_construct.py) building above ground.
    # Every construction waits out a threat seen this recently
    "construct_quiet_ticks": 3 * 1200,
    # the surface hall: one stage every 2 days at most (and only once the last is built)
    "hall_cooldown_ticks": 2 * 1200,
    "hall_surface_min": 50,                  # the Garden fort's field hall
    "hall_merchant_surface_min": 30,         # the Merchant city's market hall by the depot...
    "hall_merchant_trade_min": 80,           # ...with Trade this high
    "hall_min_citizens": 30,
    "hall_keep_failures": 3,                 # the keep refused this often in a row: the hall may go first
    "hall_floor_craftsmanship": 40,          # a block floor over the soil inside
    "hall_windows_grandeur": 40,             # (0.105.30 seams) glass windows on its long sides
    "hall_statue_grandeur": 40,              # (0.105.30 seams) a statue inside, when one is free
    "hall_max_planned": 100,                 # planned construction tiles at once, the fort over (FPS)
    "hall_stage_tiles": {"walls": 28, "floor": 35, "roof": 36},
    "hall_block_wait_ticks": 2 * 84 * 1200,  # two seasons short of blocks: build with any material
    # stone blocks for what is to be built (outside the idle-hands cap)
    "construct_blocks_cooldown_ticks": 3 * 1200,
    "construct_blocks_max_jobs": 10,
    "construct_blocks_margin": 1.1,
    # wing walls at a standing gatehouse (the War-hold), once per entrance
    "wings_cooldown_ticks": 7 * 1200,
    "wings_fortification": 100,
    "wings_surface_above": -50,
    "wings_len": 5,
    "wings_blocks": 10,
    # block floors over the soil of a finished hall, once per project
    "soil_floor_cooldown_ticks": 3 * 1200,
    "soil_floor_grandeur": 40,
    "soil_floor_craftsmanship": 60,
    "soil_floor_max_tiles": 60,
    "soil_floor_tries": 3,                   # refused this often: that project is left as it is
    # the Hermit's cavern walls (gate style `sealed`)
    "cavern_wall_fortification": 80,
    "cavern_wall_surface_max": -50,
    "cavern_wall_outsiders_max": -100,
    "cavern_wall_max_width": 3,
    "cavern_wall_retry_ticks": 112 * 1200,   # a refused seal: the usual gate there for a while
    "needs_craft_cooldown_ticks": 28 * 1200,
    "needs_meal_cooldown_ticks": 3 * 1200,
    "needs_build_at": 3,               # this many distracted by a need a tavern/library/shrine serves: build it early
    "needs_note_at": 2,                # a need this many are distracted by is named
    "gems_cut_at": 5,                  # rough gems before a jeweller's and gem cutting
    "gems_cooldown_ticks": 14 * 1200,
    "garden_min_citizens": 20,
    "great_hall_min_citizens": 60,     # (0.98) the plan's great hall: a fort this big, in good times; set pieces: a fort this big...
    "garden_idle_share": 0.14,         # ...with this share idle... (0.105.33 fix: 0.2 on the old idle measure; 60/59 states, 8 Nov run)
    "garden_every_years": 2,
    "good_times_food_per_dwarf": 15,   # (0.102.1) a set piece's "good times": fed...
    "good_times_drink_per_dwarf": 2,   # ...and watered (a big fort keeps ~2 drinks a dwarf)
    "drink_hoard_share": 1.33,         # (0.103) Thirst-scarred: drink kept x this
    "grandeur_dress_at": 50,           # (0.102.6) a fort this grand puts statues in its halls
    "grandeur_cooldown_ticks": 3 * 1200,
    "social_distracted_per": 40,       # (0.104.146) a tavern / temple for every this many distracted (any level)...
    "social_distracted_share": 0.3,    # ...once that share of the fort is
    "temple_uncovered_min": 10,        # (0.104.146) dwarves praying to gods no temple serves, before a temple to all...
    "temple_uncovered_share": 0.05,    # ...or this share of the fort
    "temple_more_piety": 50,           # (0.102.1) a devout fort raises a temple to each god many pray to
    "temple_god_piety": 120,           # (0.105.23, 14.1 step 4b) a fort this devout raises a temple to each god...
    "temple_god_worshippers": 5,       # ...this many citizens pray to (met or not: one to all gods doesn't do)
    "temple_grand_piety": 120,         # (0.105.23) a fort this devout has a grand temple (one, to all gods if no god wants one)
    "temple_more_worshippers": 5,      # ...this many distracted for want of prayer to that god
    "metal_furniture_bars": 10,        # bars of a non-gear metal kept after furniture is made from it
    "encrust_cooldown_ticks": 3 * 1200,
    "store_full_share": 0.9,           # a kind's piles this full...
    "store_loose_min": 20,             # ...and this many of its things loose: more storage for it
    "storage_gap_days": 168,           # (0.104.38) at most one storage level for full piles this often
    "store_stone_loose": 200,          # (0.93) loose stone and ore before stone storage grows (Industriousness 0)
    "store_stone_max_tiles": 600,      # (0.93) stone storage stops growing here (Industriousness 0)
    "labor_waiting_jobs": 3,           # jobs of a labour nobody has taken before more dwarves are put on it
    "labor_moves_per_cycle": 3,      # more dwarves on a job: at most once a day
    "appoint_cooldown_ticks": 1200,    # an office filled: at most one a day
    "mood_wait_days": 3,
    "mood_stall_days": 7,             # (0.105.30) a mood that fetched nothing this long: Needs you with the counts
    "mood_lacking_days": 7,           # (0.103.8) a mood still lacking what no recipe makes: Needs you from this day
    "mood_cooldown_ticks": 300,       # (0.105.24) a quarter day (was the 2-day default): a mood fails in 30-40 days
    "fuel_min": 10,
    "smelt_batch": 10,
    "metal_kit_bars": 8,               # weapon-grade bars a soldier before a squad goes from leather to metal
    "polish_idle_share": 0.15,         # this share idle: a finished level smoothed, then engraved (0.105.33 fix: 0.3 on the old measure; 47/47)
    "polish_cooldown_ticks": 3 * 1200,
    "thirsty_still_backlog": 5,        # (0.103.3) brew jobs waiting on each still before another, while thirsty
    "shop_backlog": 15,                # the AI's jobs waiting per workshop of a kind before another is built...
    "shops_max_each": 3,               # ...up to this many of a kind
    "bottleneck_cooldown_ticks": 14 * 1200,
    # (0.104.157) shoes for the barefoot and cups to drink from (the stress census)
    "barefoot_share": 0.05,            # this share of the citizens barefoot (or 3): shoes made
    "shoes_batch": 30,                 # pairs an order at most
    "citizens_per_free_cup": 3,        # a free cup in store for every 3 citizens (10 at least)...
    "cups_batch": 20,                  # ...20 an order at most
    "cupless_share": 0.1,              # ...while this share drank without one lately
    # (0.104.161, 14.1) the sliders change what a mature fort builds and agrees to
    "petition_decline_lean": -35,      # a temple or guildhall petition the fort's leaning for it (petition_lean) is this low or lower: declined
    "season_slider_weight": 1.0,       # (0.104.162, 14.1) the sliders' push on the scripted season choice (season.py; 0 = needs and quirks alone)...
    "season_crisis_slider_weight": 0.0,   # ...and while the fort is in crisis (needs alone choose)
    "growth_gap_days": 84,             # a further hall of one kind (growth_candidates) at most once a season...
    "growth_levels_max": 6,            # ...and at most this many of a kind in the fort's life (a count that never rises can't loop)
    "prison_justice_at": 50,           # Justice this harsh: more jail cells as the fort grows (a prison)
    "archery_more_militarism": 50,     # Militarism this high: more archery ranges as the army grows
    "dead_scrub_min": 1000,            # (0.104.158) dead units fix/dead-units could scrub before it runs...
    "dead_scrub_days": 28,             # ...once a month at most
    "herd_per_dwarf": 2.0,             # (0.104.158) tame animals the fort keeps per citizen (60 at least),
    "herd_min": 60,                    # ...by Husbandry; past it nestboxes stop hatching every egg
    "herd_resume_share": 0.5,          # ...and come back on under this share of it
    "cloth_min": 15,                   # cloth kept on hand (dressings, bags, rope, clothes)...
    "cloth_per_dwarf": 1.0,            # ...or a bolt a dwarf
    "cloth_batch": 5,
    "cloth_batch_max": 20, "dressings_per_extra_bolt": 4,   # (0.104.132) larger batches while wounds wait for dressings
    "coke_when_fuel_below": 40,        # coke made from coal while fuel is under this
    "coke_batch": 5,
    "stone_low": 10,
    "crisis_unhappy_pct": 40, "crisis_unhappy_clear_pct": 25,   # (0.104.137) crisis mode: enter / leave
    "crisis_deaths": 5, "crisis_deaths_share": 0.03, "crisis_deaths_clear": 2, "crisis_deaths_clear_share": 0.01,
    "crisis_ghosts": 5, "crisis_ghosts_clear": 2,
    "crisis_tantrums": 10, "crisis_tantrums_clear": 4,
    "crisis_min_days": 14,                 # ...lasting at least this long
    "crisis_extra_actions": 5,             # ...recovery's extra action slots a cycle
    "convict_per_cycle": 3,            # (0.104.131) solved cases convicted a cycle...
    "near_threat_tiles": 30,
    "depot_guard_tiles": 15,           # (0.104.140) an invader this near the depot while a caravan is in reaches
    "break_fights_days": 3,            # (0.104.139) a citizen killed by a citizen this recently: break the fights up
    "break_fights_cooldown_ticks": 600,   # ...at most every half day while it goes on (review: it takes
                                          # every citizen out of every conflict, sparring and beatings too)
    "fight_freeze_days": 7,            # (0.104.139) squads not refilled this long into a fight with a great danger
    "convict_check_after": 30,         # (0.104.138) convictions before asking whether they bring sentences...
    "convict_check_sentences": 3,      # ...at least this many more sentenced, else the rule rests
    "convict_rest_days": 84,
    "dig_raise_days": 14,               # (0.104.128) a level with nothing dug this long is dug before the rest
    "dig_raise_again_days": 7,         # (0.104.134) ...and again a week on while still nothing is dug
    # (0.105.31) small reserves of what strange moods ask for most, kept so a
    # mood (about 40 days, too short to grow fibre) finds them on hand (F, 8
    # Nov: two weavers died wanting plant cloth): made by the existing
    # recipes, and the AI's other orders that would use them up wait at or
    # under the reserve. 0 turns one off.
    "reserve_plant_cloth": 3,          # plant cloth (a fibre crop, its plants processed for thread, woven)
    "reserve_animal_cloth": 2,         # silk or yarn cloth (woven from silk or yarn thread at hand)
    "reserve_leather": 2,              # leather (a hide tanned)
    "reserve_bones": 5,                # bones (bone crafts stop at it)
    "reserve_rough_gems": 2,           # rough gems (gem cutting stops at it)
    "reserve_cut_gems": 2,             # cut gems (cut from rough over its reserve; encrusting stops at it)
    "reserve_bars": 3,                 # metal bars (metal crafts and jewellery stop at it)
    "reserve_blocks": 5,               # stone blocks (made at the mason's)
    "reserve_logs": 5,                 # logs (only said: felling is the wood rule's)
    "well_renew_days": 7,              # (0.105.31) a well's channel not dug this long: its job renewed (then weekly)
    "stone_ore_ghost_min": 10,         # (0.105.19) ...or this many while ghosts wait for slabs
    "stone_ore_min": 30,               # (0.104.124) an ore freed for the masons in a crisis only with this many boulders
    "stone_crisis_unburied": 5,        # ...a crisis: ghosts, this many dead with no tomb, or a strained fort
    "quarry_when_dig_below": 20,       # a quarry only while little other digging waits...
    "quarry_dry_days": 10,             # (0.104.4) ...or, with no usable stone at all, every this many days
    "quarry_cooldown_ticks": 2 * 1200, # ...and at most every 2 days (0.99.4: was a week; region2's 30-tile quarries were dug out in days)
    "picks_per_dwarves": 30,           # (0.99.4) a pick for every this many dwarves while stone is short (3 at least)...
    "picks_max": 20,                   # (0.104.117) was 10: a fort of 300 dug with 9 miners, two levels stalled for years
    "picks_per_backlog": 40,           # (0.104.4) a pick more for every this many tiles waiting to be dug
    "fishery_raw_fish": 50,
    "unstick_uniforms_cooldown_ticks": 14 * 1200,   # (0.99.7) at most every two weeks
    "stray_gear_cooldown_ticks": 3 * 1200,   # (0.104.58) lost gear put back three days apart
    "assign_weapons_cooldown_ticks": 3 * 1200,   # (0.104.60) weapons handed out by the AI three days apart
    "soldier_swap_cooldown_ticks": 2 * 1200,    # (0.104.64) a starved soldier let go two days apart
    "webs_clear_min": 2000,                      # (0.104.116) spider webs on the map: past this they are cleared (a season apart)
    "prune_parts_min": 2000,                     # (0.104.115) butchered parts on the ground: past this, usable ones rot too
    # (0.105.3) B (2 Nov, census 07:38): 17,471 items (5,530 webs) and 151
    # scrubbable dead at 1-3 FPS, yet nothing was cleaned: every clean-up sat
    # behind 30,000 items and the dead behind 1,000. Now from the census' own counts:
    "remove_webs_slow_min": 1000,                # loose webs outside the fort: removed past this while slow...
    "remove_webs_min": 5000,                     # ...or past this at any speed
    "remove_webs_days": 7,                       # ...a week apart
    "remove_webs_more_days": 2,                  # ...a batch every two days while the last call left more
    "remove_webs_max": 2000,                     # ...at most this many a call (one call stays quick)
    "dead_scrub_slow_min": 100,                  # dead fix/dead-units could scrub: scrubbed past this while slow...
    "dead_scrub_slow_days": 14,                  # ...two weeks apart while slow (dead_scrub_min/_days at any speed)
    "corpses_ground_min": 100,                   # corpses, parts and remains on the ground: past this they rot (prune) while slow
    "prune_worn_min": 200,                       # (0.104.115) worn clothes: past this, those thrown down rot
    # (0.105.27) forbidden items lying about (the census' items.forbidden and
    # the disposal report; planner_industry._disposal_rules). Each action waits
    # for a census taken after its last batch, and its own cooldown:
    "disposal_census_days": 28,                  # no census this long and a disposal report: count again
    "disposal_recount_days": 5,                  # ...a batch done since the last census: count again after this
    "disposal_unforbid_min": 25,                 # useful forbidden items (ammo, the enemy's and the buried dead's) before unforbidding...
    "disposal_unforbid_max": 300,                # ...at most this many a call
    "disposal_unforbid_cooldown_ticks": 5 * 1200,
    "disposal_melt_min": 10,                     # forbidden metal items before marking metal to melt...
    "disposal_melt_max": 40,                     # ...at most this many marked a call
    "disposal_melt_backlog": 60,                 # ...none while this many marked still wait for a smelter
    "disposal_melt_cooldown_ticks": 7 * 1200,
    "disposal_dump_min": 30,                     # worn clothes and the enemy's junk before marking them for the dump...
    "disposal_dump_max": 200,                    # ...at most this many a call
    "disposal_dump_backlog": 300,                # ...none while this many marked wait for the haulers
    "disposal_dump_cooldown_ticks": 7 * 1200,
    "disposal_place_dump_cooldown_ticks": 7 * 1200,   # a garbage dump asked for a week apart (refusals back off)
    "disposal_destroy_min": 150,                 # items lying in the dump before DFHack removes them...
    "disposal_empty_max": 500,                   # ...at most this many a call (<= DISPOSAL_ACTION_MAX)
    "disposal_empty_cooldown_ticks": 7 * 1200,
    "disposal_orders_cooldown_ticks": 28 * 1200,  # the refuse standing order set at most once a month
    "disposal_unknown_note": 200,                # forbidden for no reason the game gives: past this, Needs you
    "soldier_swap_month_min": 2,                 # (0.104.114) swaps allowed in 28 days: this many at least ...
    "soldier_swap_month_share": 10,              # ... or one per this many soldiers
    "soldier_swap_keen_min": 5,                  # ...while at least this many civilians badly want to train
    "soldier_swap_month_keen": 4,                # (0.104.142) ... or one per this many keen civilians waiting
    # (0.104.168) the keen in a crisis, the training turns held, complaints, vermin
    "soldier_swap_month_keen_crisis": 2,         # ...in a crisis, one per this many keen (training eases stress)
    "keen_lift_max": 20,                         # in a crisis, the soldiers wanted rise by up to this for the keen...
    "keen_lift_days": 56,                        # ...held this long after the keen were last many (no fill-then-trim)
    "fill_tantrum_hold_days": 1,                 # no drafting while a tantrum this recent is under way (or a berserk dwarf)
    "train_all_hold_days": 14,                   # every squad training: kept at least this long before half rest
    "train_half_hold_days": 7,                   # half resting: kept at least this long before all train again
    "complaint_note_min": 5,                     # citizens unable to complain lately: said, with why
    "vermin_note_min": 5,                        # citizens upset by hated vermin lately: cats kept, or said
    "citizens_per_mouser": 25,                   # cats kept from the butcher: one per this many citizens...
    "mousers_min": 4, "mousers_max": 8,          # ...within these
    "vermin_cooldown_ticks": 7 * 1200,           # the cats looked at once a week
    "staggered_starved_min": 3,                  # (0.104.72) this many starved soldiers: back to staggered training
    "pair_chairs_friends_share": 0.2,            # (0.104.77) this share badly wanting friends: chairs paired in taverns
    "pair_chairs_cooldown_ticks": 7 * 1200,
    "recreation_max": 8,                         # (0.104.78) at most this many in the recreation burrow
    "dairy_batch": 5,                            # (0.104.79) milkings or cheeses an order
    "crop_per_dwarf": 2,                         # (0.104.79) autofarm's threshold a dwarf for a food crop...
    "crop_brew_per_dwarf": 4,                    # ...and for a brewable one
    "cheese_per_dwarf": 1,                       # ...while less cheese than this a dwarf is kept
    "nest_box_max": 10,                          # (0.104.80) nest boxes at most (one a hen)
    "eggs_cooldown_ticks": 7 * 1200,
    "nest_box_order_cooldown_ticks": 7 * 1200,
    "stairwell_cooldown_ticks": 84 * 1200,       # (0.104.82) one new stairwell a season at most
    "stairwell_min_citizens": 30,
    "gate_dogs_cooldown_ticks": 7 * 1200,        # (0.104.83)
    "gate_guard_cooldown_ticks": 1200,
    "war_animals_max": 8,                        # (0.104.81) war-trained animals (and in training) at most
    "war_animals_cooldown_ticks": 7 * 1200,
    "animal_trainer_cooldown_ticks": 28 * 1200,
    "recreation_days": 28,                       # ...each at most this long
    "recreation_friends": 4,                     # (0.104.80) and places for those badly wanting friends...
    "recreation_friend_days": 7,                 # ...a week each...
    "recreation_friends_share": 0.2,             # ...while this share of the citizens badly want friends
    "recreation_min_citizens": 30,
    "recreation_cooldown_ticks": 7 * 1200,           # (0.104.80) a week: members stay up to 28 days; the burrow is refilled weekly
    "hospital_burrow_max": 30,                   # (0.104.167) at most this many patients kept in the hospital burrow...
    "hospital_burrow_per": 10,                   # ...this many new a call
    "hospital_burrow_days": 28,                  # ...each at most this long (then out a week)
    "hospital_burrow_cooldown_ticks": 1200,      # ...asked once a day (each call looks for the drink again)
    "calm_burrow_max": 6,                        # (0.104.169) at most this many dwarves in a tantrum kept in a calm burrow...
    "calm_burrow_days": 3,                       # ...each at most this long (then out a day), let out sooner once calm
    "calm_burrow_cooldown_ticks": 300,           # ...asked every quarter day while a tantrum walks free
    "calm_burrow_judge_after": 20,               # ...members seen this often (inside or out) before judging...
    "calm_burrow_outside_share": 0.5,            # ...and seen outside this share of the time: said as a note
    "booze_variety_min": 3,                      # (0.105.24) citizens upset by the same booze before...
    "booze_variety_share": 0.1,                  # ...or this share of the citizens: drinks of more kinds
    "booze_kinds_enough": 3,                     # ...unless this many kinds are in store already
    "booze_fruit_min": 10,                       # ...fruit brewed from this many fermentable growths
    "booze_fruit_batch": 5,
    "booze_variety_cooldown_ticks": 7 * 1200,    # ...a week between tries (the crops take a season)
    "calm_burrow_retire_after": 40,              # (0.105.24) seen this often (in or out) and...
    "calm_burrow_retire_share": 0.9,             # ...outside this share: the lever retired (members let out)
    "guard_min_adults": 15,                      # (0.105.8) every fort this big keeps a guard...
    "guard_min_soldiers": 3,                     # ...of this many soldiers, whatever the Militarism
    "assign_kit_wait_ticks": 3 * 1200,           # (0.105.8) armour handed out by the AI once DF left it 3 days
    "assign_kit_cooldown_ticks": 1200,           # ...a day apart
    "assign_weapons_wait_ticks": 7 * 1200,       # (0.104.60) ...once DF has left the places empty a week
    "crop_brew_threshold": 300,        # (0.99.6) autofarm's threshold for brewable crops while drink is short...
    "crop_other_threshold": 10,        # ...and for the rest (food is a fort's smaller worry by then)
    "crop_default_threshold": 50,      # autofarm's own default, put back once drink recovers
    "drink_recovered_per_dwarf": 4,
    "kitchen_ban_meals_factor": 3,     # (0.105.16) meals this many times their target: no brewables cooked while drink is under its own
    # (0.104.169) drink as a crisis lever (Teacheroar: being drunk eased -1932
    # stress across 149 citizens, the next relief -130): in a crisis the fort
    # keeps more drink and brews it sooner
    "crisis_drink_share": 1.5,             # the drink target x this while the fort is in crisis...
    "crisis_drink_far_share": 0.75,        # ...under this share of it the next brew batch is queued early...
    "crisis_brew_orders_max": 2,           # ...at most this many AI brew orders of a recipe at once
    "crisis_drink_food_floor_per_dwarf": 15,   # ...and only while food a dwarf is at least this (food first)
    "crisis_plants_keep_per_dwarf": 5,     # the crisis's extra brewing leaves this many brewable plants a dwarf
    "crisis_stills_cap_factor": 3,         # stills up to the workshop cap x this while short in a crisis (x2 otherwise)
    "crisis_containers_max": 60,           # empty barrels/pots wanted for the crisis's brewing, at most
    "surface_farm_seeds": 50,          # (0.99.6) brewable surface seeds before surface plots are laid out...
    "water_zone_max_d": 150,           # (0.105.7 review) water farther than this (survey distance) isn't zoned
    "farm_under_wait_days": 14,        # (0.105.7 review) underground plots laid out count this long before the report shows them
    "under_farm_tiles": 40,            # (0.105.5) underground plot tiles wanted for underground crops' seeds (at most)
    "farm_crops_cooldown_ticks": 1200,  # (0.105.5) the plots' crops set again a day apart at most
    "seeds_per_plot": 10,              # ...while the underground plots have fewer seeds than this each
    "surface_farm_tiles": 60,
    "steel_want": 60,                  # steel bars made while there are fewer than this
    "iron_keep": 6,                    # iron bars never turned into steel (gear being made now)
    "steel_batch": 5,
    "order_stuck_days": 14,            # a work order that hasn't moved this long is named...
    "order_stuck_you_days": 28,
    "order_hold_days": 3,              # (0.104.0, was 7: the run check found 89 bag orders, 66 cancelled as stuck, in a day)
    "loop_hold_days": 28,              # an action done too often in a year (a loop) waits this long
    "no_effect_max": 4,                # (0.105.24) done this often, each time for the very same reason ...
    "no_effect_hold_days": 56,         # ... (nothing it did changed what asked for it): held this long
    "needs_meal_max_pd": 15,
    "unload_depot_max": 50,            # (0.103.9) goods taken back out of the depot at a time
    "unload_depot_cooldown_ticks": 2 * 1200,
    "lavish_meals_max": 20,
    "good_cook_min": 3,                # (0.103.14) kitchens kept to cooks this skilled at least (when the best is)
    "good_cook_store_pd": 10,          # ...while this many meals a dwarf are stored
    "good_cook_release_pd": 5,         # ...and opened to any cook below this many
    "good_cooks_cooldown_ticks": 3 * 1200,            # (0.103.8) a lavish meal order: one a distracted dwarf, up to this
    "hospital_thread_min": 10,         # thread kept for the hospital's stitches (0.83)
    "petition_hunters_militarism": 0,  # monster hunters may stay from this Militarism (0.87)
    "petition_mercenaries_militarism": 30,  # mercenaries from this
    "residency_probe_days": 3,         # (0.105.9) an agreed residency petition: seen as a resident within this
    "residency_batch": 25,             # residency petitions answered in one go
    "hatch_levers": True,              # (0.105.12 review) off: a lever linked to the founding hatch shuts it, and the
                                       # watcher only locked hatches. (0.105.23) on: the watcher drives a hatch on a
                                       # lever by `lever pull --instant`, and a hatch its link shut is opened at once
    "hatch_lever_mechanisms": 3,       # (0.105.23) free mechanisms before a gate lever is placed (1 lever, 2 link)
    "hatch_lever_max_hatches": 2,      # (0.105.23) an entrance with more hatches (a cut) gets no levers: one each
    "gatehouse_fortification": 80,     # (0.105.23, 14.1 step 4a) a gatehouse at the founding stair from this
                                       # Fortification (the War-hold's 120)
    "residency_accept_by_flag": False, # (0.105.11) seen 2 Nov in B: an agreement set by the flag left the visitor a
                                       # guest (DF's Other list, not Residents): welcoming forts leave them to you
    "residency_cooldown_ticks": 1200,  # (review) a batch a day, not the default 2 days
    "residency_reprobe_days": 336,     # a failed probe is tried again a year on (a DFHack update may help)
    "heist_lockout_days": 168,         # (0.105.24) after an artifact heist (or a visitor killing a citizen) the tavern,
                                       # temples, library and guildhalls are shut to visitors this long (0: never).
                                       # 2-5 Nov: the thieves came as visitors (19 of 23 had asked the mayor for a
                                       # meeting); D shut its locations at 23:06 2 Nov: 8 heists before, none after
                                       # (0.105.24) the Rules switch heist_lockout (on by default) turns it off
    "heist_lockout_days_welcoming": 28,  # (0.105.26) ...but this long at Outsiders visitor_shut_welcoming (100) or
                                       # more: the Merchant city's visitors are its point, not shut half a year a heist
    "location_stale_days": 4,          # (0.105.26) a location the AI shut that reads open within this many days of
                                       # the shut, in a report not built since (the locations section is cached 2
                                       # days), is the old report, not the player opening it
    # (0.105.24) the mayor swamped by visitors: B and F (2-5 Nov) met poets, dancers and bards (asking to
    # stay) about as often as citizens, and citizens went "unable to complain". When the mayor's meetings
    # (under way and waiting) are mostly with visitors and enough citizens went unheard, the tavern,
    # temples, library and guildhalls are shut to visitors a while (Rules switch shut_to_visitors)
    "visitor_shut_unheard_min": 5,     # ...at least this many citizens unable to complain lately (the note's 5)
    "visitor_shut_meetings_min": 3,    # ...at least this many of the mayor's meetings with visitors
    "visitor_shut_share": 0.5,         # ...and at least this share of them (B and F: about half)
    "visitor_shut_days": 56,           # ...shut this long (two months), then open again and looked at afresh
    "visitor_shut_welcoming": 100,     # never at this Outsiders or more (the Merchant city's 100: visitors its point)
    # (0.105.30 live fixes) 19 of 23 thieves (2-5 Nov) asked the mayor for a meeting first; E's (8 Nov) asked
    # from 13:44 and struck at 13:51. A visitor not of the fort's race and not a resident seeking a meeting
    # shuts the tavern, temples, library and guildhalls to visitors a while (the Rules switch heist_lockout)
    "stranger_shut_days": 7,           # ...this long after the last such meeting seen
    "stranger_shut_outsiders": 50,     # ...only below this Outsiders (the Merchant city, 100, stays open)
    "residency_accept_outsiders": 30,  # agree from this Outsiders (welcoming); decline below -30 (closed)
    "petition_citizen_margin": 5,      # citizenship while citizens are this far under the population target
    "bag_sink_days": 28,               # this many bag orders in so many days with no empty bag: a sink (0.87.1)
    "bag_sink_orders": 3,
    "seed_bags_max": 30,
    "hospital_traction": 1,            # traction benches a hospital keeps (0.88)
    "traction_cooldown_ticks": 14 * 1200,
    "traction_parts_cooldown_ticks": 3 * 1200,
    "traction_rest_wait_days": 7,      # (0.105.24) a traction patient in an ordinary bed this long is got up
    "traction_rest_cooldown_ticks": 3 * 1200,
    "alert_keep_days": 1,              # alert icons cleared once this old (0.88)
    "alert_danger_days": 7,            # deaths, ambushes, beasts... kept this long
    "alerts_per_cycle": 50,
    "alerts_cooldown_ticks": 7 * 1200,      # (0.105.2) a week: DF raises job_failed, sparring, agreement and guest icons again at once (933 clears a night at a day apart)
    "dwarves_per_woodcutter": 30,      # (0.104.142) while wood is short: up to one cutter per this many dwarves...
    "wood_short_per_cutter": 100,      # ...one more per this many logs short
    "tree_quota_share": 0.8,           # felling stops at this share of the elves' yearly cap (0.89)
    "location_petitions_open": 1,      # agreed temple/guildhall petitions not yet built at once (0.89)
    "location_value_tier1": 2000,      # zone value of a temple or guildhall (DF wiki, Guildhall)
    "location_value_tier2": 10000,     # of a temple complex or grand guildhall
    "petition_answer_cooldown_ticks": 1200,
    "petition_build_cooldown_ticks": 7 * 1200,
    "location_value_cooldown_ticks": 2 * 1200,  # a statue every 2 days at most (0.90)
    "good_meals_pd": 2,                # meals worth over 20 kept a dwarf (EatGoodMeal; 0.83)
    "meals_hard_max_pd": 60,           # ... but no lavish meals past this many meals of any kind a dwarf
    "craft_shops_at": 10,              # this many want to craft: more Craftsdwarf's workshops for idle crafting
    "craft_shop_per": 8,               # ... one for every this many (0.104.53: 15 -> 8)
    "craft_shops_max": 8,              # (0.104.53: 4 -> 8; Enxah: 31 badly wanting to craft, 4 shops)
    "craft_shop_citizens": 15,         # (0.104.137) ...or one per this many dwarves
    "needs_shops_cooldown_ticks": 7 * 1200,
    "trinkets_per_cycle": 25,          # (0.104.137) or a quarter of those wanting, up to 50
    "trinket_order_max": 60,           # (0.104.137) crafts ordered at a time: half of those wanting, 20 to this
    "trinket_parallel": 2,             # (0.104.141) trinket orders of different materials at once
    "trinket_parallel_max": 30,        # (0.104.141) the second one's size at most
    "bone_crafts_min": 20,             # (0.104.141) free bones before bone crafts are ordered
    "finery_metal_bars": 10,           # (0.104.137) jewellery in copper when this many bars spare
    "fight_needs_at": 15,              # this many long to fight or train: more soldiers (they train)
    "fight_soldiers_max": 20,          # ... at most this many more
    "fight_share_max": 0.3,            # ... and never past this share of the citizens
    "idle_train_share": 0.2,           # this share of adults idle: every squad trains, and more may join (0.83)
    "idle_train_off_share": 0.14,      # ... until idle falls under this share
                                       # (0.105.33 fix: were 0.4 / 0.25 on the old idle measure; 34/34 and 53/53 states, 8 Nov run)
    "idle_avg_weight": 0.1,            # ... judged on a running average (this weight for each new reading)
    "idle_fight_soldiers_max": 40,     # ... then at most this many more soldiers for the needs (0.104.142: was 30)
    "idle_fight_share_max": 0.45,      # ... and at most this share of the citizens
    "fight_min_citizens": 15,          # (0.103.9; was 30)
    "civilians_min": 12,               # (0.105.2) never fewer civilians than this ...
    "civilians_min_share": 0.3,        # ... or this share of the adults (the larger): soldiers are the rest at most
    "fight_needs_share": 0.4,          # (0.103.9) ...or this share of the citizens, if fewer
    "fight_badly_share": 0.25,         # (0.104.61) this share BADLY wanting to train or fight: the idle caps
    "cavern_well_drink_pd": 3,         # a cavern well when drink falls below this a dwarf...
    "cavern_well_hospital_pop": 40,    # ...or a fort this big has a hospital and no water
    "cavern_well_min_pop": 20,
    "water_survey_ticks": 84 * 1200,   # the water near the fort surveyed again once a season
    "cistern_min_pop": 30,
    "hazard_near": 20,                 # fire or a cloud this close (tiles; levels count 3) sounds the alarm
    "flood_wet_dwarves": 2,            # this many dwarves in deep water: a flood
    "miasma_note": 5,
    "cistern_cooldown_ticks": 1200,
    "excess_shops_cooldown_ticks": 1200,
    "stuck_order_cooldown_ticks": 0,   # (cancelling the AI's own stuck orders: several a cycle)
    "stuck_cancel_max": 5,             # ...at most this many a cycle
    "stuck_retry_days": 28,            # an order the AI cancelled as stuck isn't placed again for this long...
    "drink_stuck_wait_days": 5,        # (0.105.26) a brew source whose order was cancelled as stuck waits this long (none while drink is urgent)
    "stuck_retry_max_days": 112,       # (0.104.37) ...doubled each time it sticks again, to this
    "stuck_again_days": 90,            # ...and stuck again within this long: held longer (doubled, up to stuck_retry_max_days)
    "ore_stock_max": 30,               # dug ore waiting for the smelter: no new vein past this
    "trade_cooldown_ticks": 2 * 1200,
    "trade_margin": 1.2,               # the fort gives this much more value than it takes
    "trade_anyone_after_ticks": 1200,  # the broker not at the depot a day after a caravan got there: anyone may trade
    "call_trader_cooldown_ticks": 300,
    "trade_deal_cooldown_ticks": 600,  # a deal on the open trade screen: at most every half day
    "trade_bars_iron": 30,             # bought up to this many of each...
    "trade_leather": 10,
    "trade_thread": 10,
    "trade_wood": 50,
    "trade_drink_per_dwarf": 20,
    "soap_keep": 5,                    # soap bars kept for the hospital
    "wood_crafts_min_logs": 30,        # (0.104.122) trinkets of wood while stone is short, with this many logs
    "soap_keep_max": 15, "infected_per_soap": 3,   # (0.104.121) a bar for every 3 infected wounds, up to 15
    "soap_cooldown_ticks": 2 * 1200,
    # (0.104.168) disease and care: with this many infected the soap chain
    # runs two steps a cycle in batches of 5; idle infected dwarves DF asks
    # no treatment for are put to rest in free hospital beds, 3 a day (stopped
    # when DF keeps none of 3 sent); a hospital gets a second doctor's post
    # while more than 3 treatments wait for each dwarf who can diagnose
    "soap_rush_infected": 20, "soap_rush_batch": 5, "soap_rush_cooldown_ticks": 2 * 1200,
    "infected_rest_max": 3, "infected_rest_cooldown_ticks": 1200, "infected_rest_give_up": 3,
    "infected_rest_cap": 3, "infected_rest_keep_free": 2,   # (review) sleepers at once; beds left for DF's patients
    "doctor_post_per_diagnoser": 3, "doctor_post_cooldown_ticks": 3 * 1200,
    "noble_rooms_cooldown_ticks": 1200,
    # (0.105.41) a noble's room under its office's value: a step a day (a statue,
    # smoothing, engraving, statues ordered); at most this many statues a room;
    # statues ordered only with this many usable boulders
    "noble_value_cooldown_ticks": 1200, "noble_room_statues_max": 6, "noble_statue_stone_min": 10,
    # (0.104.168) homes: one bedroom per household, the stressed to rooms they like
    "homes_cooldown_ticks": 1200,
    "homes_dig_cooldown_ticks": 7 * 1200,
    "homes_liked_cooldown_ticks": 7 * 1200,
    "homes_liked_min_stressed": 5,     # unhappy or worse citizens before a move is looked for
    "homes_liked_max": 10,             # moves at a time
    "homes_rough_note_at": 3,          # citizens who slept rough lately before a note says why
    # (E4) the citizens' taste (Design Guided or Architect only): a piece they like in their own room
    "homes_furnish_cooldown_ticks": 7 * 1200,
    "homes_furnish_max": 5,            # rooms furnished at a time
    "uniform_cooldown_ticks": 1200,       # a squad's uniform: once a day
    "crafts_cooldown_ticks": 14 * 1200,
    "hauling_cooldown_ticks": 14 * 1200,
    "ore_cooldown_ticks": 7 * 1200,    # a vein mined: at most once a week
    "industry_cooldown_ticks": 7 * 1200,
    "gather_cooldown_ticks": 7 * 1200, # shrubs marked for gathering: at most once a week
    "train_min_citizens": 15,
    "train_rotate_days": 28,           # squads the AI trains take turns, half at a time, a month each...
    "train_rotate_below_militarism": 50,   # ...unless the fort is militant: then all train
    "young_fort": 20,                  # under this many dwarves the fort is young: food first, small and plain
    "found_food_per_dwarf": 15,
    "character_food_per_dwarf": 10,    # (0.105.10, 14.1 step 3) the basics met before a slot is the character's:
    "character_drink_per_dwarf": 10,   # ... food and drink a dwarf, beds for all, the basic workshops, a dining hall
    "character_piety_bend": 120,       # (0.105.23, 14.1 step 4b) Piety this high: a shrine may take the slot before food and drink are met...
    "character_piety_food_per_dwarf": 5,    # ...with this much food a dwarf...
    "character_piety_drink_per_dwarf": 3,   # ...and drink (beds, dining hall and workshops still met; never in a crisis)
    "established_food_per_dwarf": 40,  # a small fort with farms, this much food and the drink below is no longer young
    "established_drink_per_dwarf": 15,
    "gather_jobs_max": 60,             # more plant-gathering jobs than this in a fed fort: trimmed...
    "gather_jobs_keep": 20,            # ...to this many
    "dig_backlog_per_miner": 50,       # no new level while more than this waits to be dug, per miner
    "water_gate_recheck_ticks": 3 * 28 * 1200,  # a water gate is looked at again each season
    "mechanisms_cooldown_ticks": 7 * 1200,    # mechanisms ordered for a link: once a week at most
    "link_mechanisms_retry_ticks": 3 * 1200,  # no free mechanisms: try the link again after 3 days
    "max_gear_order": 10,
    "gear_spare_stop": 3,          # this many unused spares: soldiers haven't picked them up; make no more
    "gear_unused_ticks": 7 * 1200, # spares unused this long: tell the player (uniforms?)
    "gear_weapons_anyway_ticks": 28 * 1200,   # (0.104.57) spare weapons unused this long: make new ones anyway
    "gear_wait_ticks": 3 * 1200,   # after putting squads on training, let them pick up gear first
    "smelt_when_bars_below": 50,   # weapon-grade bars (steel, iron, bronze, copper) in all
    "health_wait_days": 28,        # a patient waiting this long for care is said (Needs you)
    "squad_min_citizens": 10,
    "trim_margin_min": 3,              # (0.102) soldiers over the wanted number kept before trimming...
    "trim_margin_share": 0.25,         # ...or this share of it, whichever is more
    "max_trim_per_cycle": 2,
    "squad_trim_cooldown_ticks": 3 * 1200,
    "bootstrap_chair_cooldown_ticks": 7 * 1200,   # (0.101.4) one chair job a week at most
    "approve_after_days": 3,           # (0.101.2) the AI approves its own orders the manager hasn't
    "crossing_min_value": 30,          # (0.101) the far side's worth before a bridge (crossing_value)
    "crossing_far_share": 0.4,         # ...and against the fort's own side
    "crossing_refine_citizens": 30,    # a wider bridge once the fort has this many dwarves
    "crossing_refine_wealth": 20000,   # ...and this much wealth
    "crossing_cooldown_ticks": 14 * 1200,
    "dig_stall_days": 28,              # (0.104.110) no tile dug on a level this long: its dig jobs let go of their workers
    "dig_stall_furnish_days": 56,      # ... and a level 90%+ dug is furnished without its last tiles
    "unreached_dig_days": 56,          # (0.105.22) nothing dug at all in this many days (no one gets to it): given up
    "slow_dig_days": 336,              # (0.104.12) a project under half dug in a game year is given up
    "furniture_parallel_backlog": 4,   # (0.104.141) the stone order's pieces left per Masons' workshop before part goes to wood too
    "furniture_parallel_min": 3,       # (0.104.141) the smallest wooden part worth ordering
    "furniture_short_pieces": 40,      # (0.104.141) furniture waiting in open levels: Masons' workshops past the cap
    "furnish_stalled_days": 30,        # (0.104.141) a level furnished but for buildings never finished this long: its slot freed
    "convict_on": False,               # (0.104.147) the AI convicts solved cases (off: the guard's beatings killed patients)
    "jail_convicts_wait": 10,          # (0.104.141) solved cases waiting: the jail grows by them (to twice the restraints wanted)
    "statue_wait_days": 56,            # (0.104.12) a level waiting only for statues (no stone) this long is finished
    "statue_wait_days_any": 112,         # (0.104.33) a level finished without its statues after this long, stone or not
    "stuck_project_days": 21,          # (0.100.1) a level whose digging stopped is given up after this
    "min_dwarves_for_farms": 3,                 # (0.100.1) was 7: one early death stopped the farms
    # Farms (docs/building.md): tiles per dwarf at Agriculture 0, for the
    # population the fort is growing toward; x2 at +100 ("Big farms")
    "farm_tiles_per_dwarf": 1.0,
    "min_farm_tiles": 9,
    "max_farm_tiles": 400,
    "farm_refill_share": 0.75,     # lay out more when below this share of the target
    "farm_thirsty_share": 0.5,     # (0.105.23) drink under its target: the farm target x (1 + this), for brewable seeds...
    "farm_thirsty_max_tiles": 60,  # ...at most this many tiles more (and no more than the brewable seeds)
    "farms_cooldown_ticks": 3 * 1200,
    "farm_dig_retry_days": 28,     # no soil for a farm level: look again (and ask again) after this
    "well_cooldown_ticks": 3 * 1200,
    # (0.105.0) water works and magma (brain/planner_water.py)
    "moat_fortification": 50,          # a moat from this Fortification up (a river near the gate)
    "moat_drawbridge_engineering": -50,   # below this Engineering a plain bridge over it, no drawbridge
    "pump_engineering": 0,             # a pump stack from this Engineering up
    "waterworks_magma_retry_ticks": 84 * 1200,   # (0.105.38 review) a refused magma workshop: tried again a season on
    "waterworks_later_retry_ticks": 3 * 1200,    # (0.105.38 review) a search cut short (its time budget): 3 days on
    "waterworks_retry_ticks": 28 * 1200,  # a work refused (no site, path blocked): tried again 4 weeks on
    "waterworks_moat_cooldown_ticks": 1200, "waterworks_magma_cooldown_ticks": 1200,
    "waterworks_irrigation_cooldown_ticks": 1200, "waterworks_pump_cooldown_ticks": 1200,
    "waterworks_check_cooldown_ticks": 3 * 1200,   # (0.105.0 review) a done work's leak check every 3 days
    "cistern_hold": False,             # (0.104.144) on hold (the player: the first design would flood the fort); released 0.104.145 (the second)
    "dwarves_per_well": 70,            # (0.104.141) another well for every this many dwarves (0: one well)
    "extra_well_retry_days": 84,       # (0.104.141) another well that couldn't be placed: tried again a season on
    # (0.105.3) Hammerstirred (2 Nov): no well in either fort; the water was all
    # further off than the AI looked (the pool 53-66 tiles, the pond 51 from the
    # gate, the cavern lake beside the fort, not under it)
    "cavern_well_gallery": 80,         # a tunnel this long at most out to a column over the cavern lake (0: none)
    "well_shore_reach": 60,            # a well on a pond's bank this far from a surface gate (40 before)
    "cistern_tunnel_max": 70,          # the cistern's tunnel to still water this long at most (30 before)
    # (0.105.38) far sources (the player, 12 Nov: the whole map, not only near
    # the fort). The keys above stay the near reach, tried first as before;
    # past them each work weighs the whole-map survey's bodies by the dig's
    # length (cheapest first) up to these:
    "water_far_reach": -1,             # tiles a far source may lie off at most (-1: the map's width; 0: far sources off)
    "water_job_max": 600,              # tiles a far water work digs and builds in all at most (0: no far works)
    "water_dig_segment": 40,           # a long dig designated this many tiles a step (the dry run walked again before each)
    "new_pasture_cooldown_ticks": 3 * 1200,
    "pasture_margin": 1.25,        # a new pasture: the waiting herd's grass x this (x more at high Husbandry)
    "well_parts_days": 3,          # a well waiting this long for parts: say what to make
    "ranged_from_squads": 2,           # a crossbow squad once the fort has this many squads
    "bolts_per_soldier": 50,
    "bolt_bars_keep": 20,              # metal bolts only while this many bars are left for armour
    "max_quiver_order": 5,         # (0.100) leather quivers for crossbow soldiers, per order
    # (0.100) bars a job takes (DF wiki); boots and gloves are ordered by the
    # pair and one bar makes a pair, so 1 each
    "gear_bars": {"weapons": 1, "body": 2, "helms": 1, "shields": 1, "pants": 2, "boots": 1, "gloves": 1},
    # Limits
    "max_actions_per_cycle": 3,
    "max_orders_per_game_day": 8,
    "rule_cooldown_ticks": 2 * 1200,
    "build_cooldown_ticks": 5 * 1200,   # a new building project at most every 5 days
    # (0.105.0, round 2) an army that can fight (brain/planner_army.py)
    "gear_fix_cooldown_ticks": 3 * 1200,        # the uniforms mended and gear handed out three days apart
    "gear_fix_order_cooldown_ticks": 7 * 1200,  # a weapon the entries name and the fort lacks: a week apart
    "quivers_cooldown_ticks": 1200,             # free quivers handed out once a day
    "quivers_order_cooldown_ticks": 7 * 1200,
    "bolts_cooldown_ticks": 3 * 1200,
    "gate_cut_cooldown_ticks": 3 * 1200,
    # (0.105.3) B (2 Nov): one thief left inside after a siege kept the only
    # hatch shut and the alarm up for 2.5 real hours (1-3 FPS, 6 citizens and
    # 51 visitors shut out). See planner_military lone_intruders / note_lockdown.
    "lone_intruder_max": 2,             # this many ordinary enemies already inside, or fewer: no shut gates for them
    "lone_intruder_alert_ticks": 600,   # ...and the alarm held for them at most half a day
    "lockdown_max_days": 2,             # the AI's shut gates and alarm with no new enemy this long...
    "lockdown_cap_threats": 2,          # ...this many ordinary enemies left or fewer, the game slow or
                                        # dwarves shut out: opened again
    # (0.105.3) A (2 Nov 09:36): a sneaker spotted, the hatch shut with 9
    # citizens outside, then he hid again: nothing visible, the fort kept shut
    # for the 3 quiet days (1 FPS). With nothing hostile in sight (no siege
    # held off at the gates either):
    "lockdown_clear_ticks": 300,        # ...citizens or visitors shut out: open after 6 game hours
    "lockdown_visitors": 20,            # ...this many visitors outside the fort count as shut out (0.105.4: outside only)
    "small_alert_ticks": 1200,          # ...only a few ordinary enemies all along (a sneaker): after a day
    # (0.105.30 live fixes) E (8 Nov 13:50): DF's invasion record of a lone
    # thief (civ -1, 1 invader) came 2,000 ticks before she was "spotted
    # sneaking around" in the middle of the fort; the alarm only sounded then,
    # and a mass fight killed 3 citizens. The alarm sounds on the record itself:
    "intrusion_alert_days": 2,          # ...and is held this long while nobody is seen (phases' CONFIRM_DAYS)
    # ...and the half-day for a few ordinary enemies counts from the last
    # cycle one was this near a dwarf (E: the alarm came down 635 ticks after
    # it went up, the thief 1 tile from the citizens and still alive)
    "few_alert_near_tiles": 12,
    # (0.105.32) E (8 Nov): the founding stair's hatch read open after an
    # instant lever pull, but DF's walk map was split at it; every citizen who
    # went out was stranded there and 64 died of thirst. planner_gates
    # _stranded_rule: unstick_gate at once, one step at a time:
    "gate_stuck_step_hours": 6,         # ...this many game hours between steps (the split still there)
    "gate_stuck_prevent_days": 1,       # ...a split with nobody shut out yet: step 1 at most this often
    # ...and citizens cut off with no gate to blame (no split): dig_way_in
    "way_in_after_days": 2,             # ...once they've been out this many game days
    "way_in_min_stranded": 1,           # ...and at least this many are
    # (merge32 review) ...refused: again in an area after 1, 2, 4 days, and after this many refusals only the Needs you;
    # one dug there and they're still out: no more there
    "way_in_max_refusals": 3,
    "way_in_single_days": 3,            # ...one dwarf alone: once out this many game days
    "way_in_area_tiles": 20,            # ...an "area": within this many tiles of the last one
    # (0.105.33) a second way to the surface by design (planner_gates _second_way_rule):
    "second_way_min_citizens": 30,      # ...a fort this big with one surface entrance digs another
    "second_way_retry_days": 60,        # ...refused (or dug and not seen): again after this many game days
    "second_way_hermit_outsiders": -50,  # ...not at Outsiders this low (nor hidden_hold, winding_ways) unless ever stranded
    # (0.105.39, 13b) missions on the world map (planner_missions): the share of
    # soldiers kept home at Militarism -100 / 0 / +100 (linear between), never
    # fewer than guard_min_soldiers...
    "mission_home_share_low": 0.75,
    "mission_home_share_mid": 0.5,
    "mission_home_share_high": 0.25,
    "mission_min_soldiers": 2,          # ...and a mission only with this many sendable soldiers in whole squads
    "mission_retry_ticks": 403200,      # a World-screen run for a goal that stopped: not tried again for a year
    "mission_sent_wait_ticks": 100800,  # a mission sent: not proposed again for a season while its controller shows
    "mission_cooldown_ticks": 7 * 1200,  # the mission rule's proposals a week apart
    # (0.105.40b) the insane (brain/planner_insane.py): the AI's doors between a
    # melancholy or raving dwarf and deadly ground checked this often...
    "insane_cooldown_ticks": 100,
    # ...and (DF wiki, Stress) the citizens near breaking: long-term stress this
    # high ("haggard") while very unhappy or worse, or this high ("harrowed")
    # while unhappy or worse, first in the stress care
    "insane_risk_longterm": 50000,
    "insane_risk_harrowed": 100000,
    # (0.105.40, 13e) world cleanup (brain/planner_cleanup.py), only past these
    # counts; while the game runs slowly each threshold is divided by
    # cleanup_slow_factor, and the item one grows with the items on the map
    "cleanup_slow_factor": 4,
    "cleanup_spatter_min": 20000,         # spatter events outside the fort's areas: cleaned past this...
    "cleanup_spatter_all_min": 100000,    # ...and inside too, only while slow, past this many in all
    "cleanup_spatter_budget_ms": 150,     # ...a call's walk of the map's blocks at most
    "cleanup_dead_min": 400,              # dead units long dead and unreferenced on the active list
    "cleanup_dead_age_ticks": 403200,     # ...dead this long at least (a year)
    "cleanup_items_min": 4000,            # items no citizen has reached for a year: deleted past this...
    "cleanup_items_share": 0.08,          # ...or past this share of the items on the map, the larger
    "cleanup_items_age_ticks": 403200,    # ...unreachable this long at least (a year)
    "cleanup_items_batch": 500,           # ...oldest first, this many a call
    "cleanup_units_min": 40,              # (Rules full) hostile or wild creatures unreachable a season
    "cleanup_units_age_ticks": 100800,    # ...unreachable this long at least (a season)
    "cleanup_units_batch": 50,            # ...this many a call
    # (0.105.40 review) a real call that removed nothing: that kind (at that level) waits this long
    "cleanup_empty_backoff_ticks": 100800,
    # the rules' pace (select() reads <rule>_cooldown_ticks): a trial dry run
    # first per kind, then the real call; a batch a day while more is left
    "cleanup_spatter_cooldown_ticks": 7 * 1200,
    "cleanup_dead_cooldown_ticks": 28 * 1200,
    "cleanup_items_cooldown_ticks": 1200,
    "cleanup_units_cooldown_ticks": 7 * 1200,
    "cleanup_spatter_dry_cooldown_ticks": 1200,
    "cleanup_dead_dry_cooldown_ticks": 1200,
    "cleanup_items_dry_cooldown_ticks": 1200,
    "cleanup_units_dry_cooldown_ticks": 1200,
    # (0.105.40b) evil weather (brain/planner_weather.py): the alarm while an
    # evil cloud is on the map's surface or this close to its edge, or evil
    # rain falls on the fort; lifted once it has been gone this many game hours
    "weather_edge_near": 150,             # DF's evil cloud this many tiles from the map's edge (about a day's drift; fix41)
    "weather_lift_hours": 6,              # gone this long (50 ticks an hour) before the alarm comes down
    "weather_alarm_max_days": 4,          # held at most this long in one spell (the fort can't stay in for ever)
    "weather_blood_rain_alarm": False,    # plain blood rain (no syndrome) only stains: work goes on
    # (0.105.40 M5) hauling balanced (brain/planner_hauling.py): haulers wanted =
    # the larger of hauling_min_share of the civilians (hauling_min_haulers at
    # least) and one per hauling_jobs_per_hauler jobs waiting, at most
    # hauling_max_share; a stall: this many waiting, the oldest this many days,
    # at most hauling_idle_max haulers idle
    "hauling_min_haulers": 3,
    "hauling_min_share": 0.15,
    "hauling_jobs_per_hauler": 8,
    "hauling_max_share": 0.6,
    "hauling_backlog_min": 20,
    "hauling_wait_days": 1,
    "hauling_idle_max": 0,
    "hauling_add_max": 5,                 # idle civilians made haulers a call
    "hauling_relieve_max": 2,             # key workers taken off (or given back) hauling a call
    "hauling_relieve_margin": 2,          # ...only while this many haulers more than wanted remain
    "hauling_add_cooldown_ticks": 1200,
    "hauling_relieve_cooldown_ticks": 7 * 1200,
    "hauling_back_cooldown_ticks": 3 * 1200,
    # (0.105.40b fix) the AI's own detail shrinks: while haulers > wanted +
    # hauling_relieve_margin for hauling_shrink_days, up to hauling_shrink_max
    # of the dwarves it added (a week or more on it) taken off a call
    "hauling_shrink_days": 7,
    "hauling_shrink_max": 2,
    "hauling_shrink_cooldown_ticks": 3 * 1200,
    # (0.105.40b, M6) the food store (brain/planner_food.py): a roofed food pile
    # taking barrels within reach of each kitchen and still, sized to the fort
    # (item 12) the fort's artifacts shown (brain/planner_artifacts.py): items a
    # pedestal / display case holds (a guess until seen in game), only rooms
    # shut in by doors, rooms open to visitors allowed (after the closed ones),
    # pedestals ordered at a time, the stone a pedestal order waits for
    "artifact_pedestal_holds": 1,
    "artifact_case_holds": 3,
    "artifact_display_need_doors": True,
    "artifact_display_open_rooms": True,
    "artifact_pedestals_max": 3,
    "artifact_pedestal_stone_min": 10,
    "artifact_display_cooldown_ticks": 1200,
    "artifact_furniture_cooldown_ticks": 7 * 1200,
    "artifact_pedestals_cooldown_ticks": 14 * 1200,
    "food_store_min_citizens": 7,
    "food_store_reach": 20,               # tiles from the kitchen or still (a z-level counts food_store_dz_cost)
    "food_store_dz_cost": 3,
    "food_store_tiles_per_citizen": 0.5,  # tiles of food pile a citizen (a barrel a tile holds much)...
    "food_store_tiles_min": 9,            # ...within these
    "food_store_tiles_max": 49,
    "food_store_barrel_share": 1.0,       # max barrels: a barrel a tile...
    "food_store_barrels_max": 64,         # ...at most
    "food_store_full_share": 0.9,         # the near piles this full, and...
    "food_store_loose_min": 10,           # ...this much food lying outside a pile: another pile beside them
    "food_store_tiles_cap_factor": 3,     # the AI's near food piles at most this many times the size wanted
    "food_store_exposed_min": 10,         # food out of barrels (in piles or out): empty barrels wanted for it past this...
    "food_store_per_container": 10,       # ...one per this many items...
    "food_store_containers_max": 20,      # ...at most
    "food_store_rot_rise_min": 10,        # rotten food risen this much within the window: said, cats kept
    "food_store_rot_window_days": 28,
    "food_store_cooldown_ticks": 3 * 1200,
    "food_barrels_cooldown_ticks": 1200,
    "food_store_level_cooldown_ticks": 28 * 1200,
    # (0.105.41, item 2) wheelbarrows for the AI's stone piles, feeders linked (brain/planner_piles.py)
    "barrow_pile_min_tiles": 4,           # an AI stone pile this big at least takes wheelbarrows...
    "barrow_tiles_per": 12,               # ...one per this many tiles...
    "barrow_pile_max": 2,                 # ...at most this many (and its tiles - 1, as quickfort sets)
    "barrow_ai_min": 2,                   # the AI's piles take this many wheelbarrows in all at least...
    "barrow_citizens_per": 10,            # ...or one per this many citizens, if more
    "barrow_order_max": 3,                # wheelbarrows ordered at once for the piles' unmet want
    "barrow_order_wood_min": 10,          # wood in stock before they're ordered
    "barrows_cooldown_ticks": 1200,
    "barrow_order_cooldown_ticks": 7 * 1200,
    "feeder_link_cooldown_ticks": 1200,
    "feeder_links_only": True,            # a linked feeder fed from the AI's bigger pile of its kind takes from links only
    "feeder_starve_days": 2,              # a linked feeder empty this many days while its workshop has work: unlinked
    "feeder_idle_days": 4,                # a linked workshop with work and nobody at it this many days: unlinked
    # (0.105.40 M7) alloys at the smelter (brain/planner_alloys.py)
    "alloy_iron_route_bars": 10,          # iron, pig iron and steel bars that make a fort an iron fort (no bronze for gear)
    "alloy_bronze_want": 40,              # bronze and bismuth bronze bars made while there are fewer than this
    "alloy_copper_keep": 2,               # copper bars never alloyed for gear (a job being made now)
    "alloy_batch": 5,                     # reactions an order
    "alloy_fuel_min": 3,                  # charcoal or coke the gear alloy needs (none at a magma smelter)
    "alloy_tin_copper_bars": 10,          # copper bars that make the tin ore worth smelting and mining (no iron)
    "alloy_value_fuel_min": 30,           # charcoal or coke before a value alloy is made (none at a magma smelter)
    "alloy_value_keep": 20,               # bars of each metal kept back before it's alloyed for value
    "alloy_value_want": 30,               # a value alloy's bars made while there are fewer than this
    "alloy_value_gain": 1.25,             # the alloy's bars worth this many times its parts, at least
    # (0.105.41, 13e) traffic zones on the AI's finished levels (brain/planner_traffic.py, lua/ai-traffic.lua)
    "traffic_slice_tiles": 1500,          # tiles a paint_traffic call reads (and paints) at most
    "traffic_budget_ms": 40,              # ...and the ms it may take (it stops early, resumes next call)
    "traffic_paint_cooldown_ticks": 300,  # a slice every quarter day at most while a level waits
    "traffic_audit_cooldown_ticks": 7 * 1200,   # one painted level rechecked a week at most...
    "traffic_recheck_days": 168,          # ...only once it was painted (or last checked) this long ago
    "traffic_priority": 8,                # low: paths only
    "traffic_priority_slow": 6,           # while the game runs slowly (the paths are part of the cost)
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
    "grove_cooldown_ticks": 7 * 1200,
    # (item10) training benches (brain/planner_benches.py)
    "bench_training_max_level": 5,        # the training bench's max skill (df skill rating: 5 Proficient)
    "bench_learners_min": 2,              # workers below it before a bench is capped
    "bench_caps_cooldown_ticks": 1200,
}
