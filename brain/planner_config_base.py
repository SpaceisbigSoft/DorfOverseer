"""planner_config_base: part of PLANNER_CONFIG (brain/planner_config.py), split out in
r7 d6 and applied first: needs and order sizes, the rules' pace, threats and the fight bar, building,
growth and the fort's floor, supplies, the dead and moods, military, the surface
keep and hall.
Moved verbatim: keys, values, order and comments as they were."""

__all__ = ["PART"]

PART = {
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
    "idle_crafts_per_dwarf": 4,        # (0.105.51) blocks at the cap: idle hands make rock crafts while fewer goods a dwarf than this
    "idle_furniture_stock": 20,        # (0.105.51) ...else stone doors, cabinets, tables, chairs up to this many free of each
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
    # (0.105.54, the player: "fight when roughly even") planner_matchup.fight_bar: the sortie bar is
    # about even odds for invaders and beasts; fight_ratio (a clear win) only where the reasons hold:
    # a fire breather (crossbows only) or a great danger whose abilities the AI can't read
    "fight_even_ratio": 1.0,
    "fight_weak_factor": 0.8,          # an enemy (group) all wounded or falling back: the bar times this
    "fight_wounded_blood": 0.25,       # ...wounded: this share of its blood lost...
    "fight_wounded_wounds": 6,         # ...or this many wounds
    "fight_retreat_tiles": 5,          # ...falling back: this many tiles farther from the dwarves than last cycle
    "fight_split_tiles": 15,           # threats this far (x/y, a level 3) from every other: a group apart (stragglers)
    "siege_wait_max_days": 4,          # a siege (invaders or a great danger in reach) this long: an all-out attack
    "siege_unhappy_rise": 0.15,        # ...or the unhappy share up this much since it began...
    "siege_unhappy_min": 0.3,          # ...and at least this share
    "all_out_min_ratio": 0.25,         # an all-out attack only at this ratio or better (not at an enemy inside)
    "fight_lost_share": 0.33,          # squads out that lost this share (a third) of their soldiers fall back...
    "fight_wounded_share": 0.5,        # ...or with this share of them wounded
    "fight_regroup_ticks": 600,        # ...and regroup this long before they are sent again (save all-out)
    "cautious_alert_levels": 10,   # Caution +100: react to unknown-reach threats this close
    # Building (docs/building.md)
    "spare_beds_share": 0.1,       # beds wanted beyond one per citizen
    # Growth slider -> target population: -100 / 0 / +100; past +100 (Extreme) it
    # keeps rising, no cap at +200; past -100 no newcomers, one dwarf sent away
    # every shrink_days * 100/(|v|-100) days (0.94: Extreme doubles, as everywhere).
    "growth_points": {"low": 25, "average": 100, "high": 250},
    "shrink_days": 28,
    "min_citizens": 7,             # never sent away below this
    # (item5) the fort's floor: under this many citizens DF's population cap
    # opens to migrants whatever the sliders (Growth, the strain and slow-game
    # holds; not Extreme-low Growth, which shrinks the fort on purpose), and
    # the baby caps are raised to at least floor_baby_cap / floor_baby_pct.
    # 20 is also the population DF wants before strange moods come.
    # (Hammerstirred, the Hermit hold: 15 dwarves for 13 years, then 8.)
    "survival_floor": 20,
    "floor_baby_cap": 10, "floor_baby_pct": 100,
    # (item5) a prisoner this thirsty (DF's thirst counter; the report's
    # "parched" is 50000) is let go even where there is a well
    "prisoner_thirst_release": 40000,
    "prisoners_water_cooldown_ticks": 1200,
    # (item5) a Make mandate for shields or bucklers met in wood (off: noted, as before)
    "mandate_shields": True,
    # (item5) Make mandates met at Deference under -50 while someone holds the guard's office (off: ignored, as before)
    "mandates_low_deference": True,
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
    "dining_seat_share": 0.5,      # (0.105.51) a table in a public dining hall for every other dwarf (the bridge's table census)
    "lack_tables_min": 5,          # (0.105.51) citizens upset at eating without a table (28 days) that make the halls short...
    "lack_tables_seat_cap": 0.75,  # ...while their tables seat under this share of the fort
    "tavern_badly_per": 30, "temple_badly_per": 25,   # (0.104.137) a tavern / temple for every this many badly missing...
    "social_badly_share": 0.15, "social_halls_max": 6,   # ...once that many of the fort badly miss it; at most this many
    "argument_crowd_share": 0.25,  # (0.105.51) citizens upset by arguments (28 days): the taverns are crowded...
    "tavern_crowd_per": 40,        # ...while there is under one tavern of its own for every this many dwarves (+1)
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
    "free_time_widen_idle": 0.2,            # (r33c) ...or with this share truly idle (_idle_share; over free_time_idle_below)
    "free_time_wait_per_holder": 2,         # (r33c) ...or its jobs wait, this many a holder (and few holders free)
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
    "drink_containers_low": 5,         # (0.105.51) fewer empty barrels/pots than this while drink is short: a second Carpenters' is urgent
}
