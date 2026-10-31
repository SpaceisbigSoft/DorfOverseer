"""planner_core: part of the planner (split out of planner.py in 0.104.83; see planner.py)."""

from __future__ import annotations
import json
import math
import re
from dataclasses import asdict, dataclass, field
from culture import layout_style, new_history, pick_stone, profile_from, stone_for
from learning import held_levels
import masterplan
import phases
from quirks import has_rule
from digest import _d, _l, normalize

__all__ = ["great_present", "all_clear", "STEER_PROTECTED", "STEER_MAX_DAYS", "steer_of", "PLANNER_CONFIG", "BREW_RECIPES", "MEAL_RECIPES", "MANDATE_RECIPES", "BUILDABLE_SHOPS", "SHOP_ALIASES", "SURVIVAL_SHOPS", "TICKS_PER_DAY", "TICKS_PER_YEAR", "NO_COOLDOWN", "MULTI_PER_CYCLE", "EMERGENCY", "STUCK_HOLD_EXEMPT", "LIMIT_EXEMPT", "Proposal", "Memory", "abs_tick", "game_day", "factor", "ADJUST_BOUNDS", "_number", "effective_config", "queued", "_clamp", "MEMORIAL_SPAN", "OPTIONAL_LEVELS", "GEAR_WEAPONS", "GEAR_METALS", "GEAR_RECIPES", "NEEDS_YOU", "ask_player", "player_rules", "MAINTAIN_SKIPS", "level_refused", "_traits", "reachable_threats", "held_off_threats", "_holding_off", "ONE_A_CYCLE", "growth_mode", "growth_target", "JOB_SHOPS", "RECIPE_SHOPS", "WOOD_ELSEWHERE", "recipe_shop", "brew_recipe", "_watchdog_notes", "jobs_reported", "order_job_state", "masons_jammed", "stuck_hold_days", "_stuck_before", "stone_short", "_office_held", "tantrums_recent", "justice_held", "_restraint_order", "manager_needs_office", "suites_short", "wool_route", "thread_plants_here", "MINING_NEED_ONLY", "mining_plan", "noble_room_kinds", "SOCIAL_NEEDS", "care_waiting", "unmet", "_soldier_swap", "LOCATION_UNITS", "_location", "_location_short", "_real_locations", "is_ranged", "STALE_PROJECT_DAYS", "_workshops_busy", "shop_count", "shops_max", "_has_shop", "RAW_FOOD", "ALL_FOOD", "_idle_share", "update_idle", "AGENDA_THEMES", "agenda", "food_per_dwarf", "WINTER_STOCK", "winter_factor", "young_fort", "established", "has_farms", "_best_metal", "REFUSAL_FIRST_DAYS", "REFUSAL_MAX_DAYS", "REFUSAL_KEYS", "refusal_key", "_refused_wait", "note_refusal", "LOOP_LIMITS", "LOOP_LIMIT_DEFAULT", "LOOP_EXEMPT", "_loop_count", "_stalled_days", "_entrance_spot", "_record_any_outcome", "_weapon_gaps"]

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
    "idle_share": 0.25,            # share of adults idle before "idle hands" fires
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
    "strain_unhappy_pct": 20, "strain_unhappy_ok_pct": 12,
    "strain_drink_pd": 2.0, "strain_drink_ok_pd": 4.0,
    "strain_meals_pd": 2.0, "strain_meals_ok_pd": 4.0,
    "beds_ahead": 20,              # Expand: bedrooms up to this many ahead of the population
    "maintain_spare_beds": 2,
    "min_spare_beds": 5,
    "dwarves_per_table": 3,
    "min_dwarves_for_dining": 3,                # (0.100.1) was 7
    "min_dwarves_for_hospital": 20,
    "min_dwarves_for_small_hospital": 10,  # ...or this many with a chief medical dwarf (not a young fort)
    "urgent_hospital_waiting": 2,
    "urgent_temple_share": 0.5,        # (0.103.12) this share of the citizens longing to pray, no real temple: a shrine at once      # (0.103.8) this many waiting for care, no hospital: one with a slot of its own
    "urgent_tavern_share": 0.33,       # (0.104.35) this share badly wanting company, only the stop-gap tavern: a tavern at once
    "train_all_share": 0.15,           # (0.104.53) this share badly wanting to train: every squad trains, none rests
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
    "max_fill_per_cycle": 5,
    "gate_cooldown_ticks": 600,
    "entrance_scan_ticks": 7 * 1200,   # map the entrances again once a week
    "gate_gone_ticks": 28 * 1200,      # a gate built 4 weeks ago and the entrance still open: build again
    "fortify_max_width": 50,           # wider openings are left to the player
    "gate_retry_ticks": 14 * 1200,     # a refused entrance is tried again after 2 weeks (things change)
    "gate_lever_cooldown_ticks": 14 * 1200,
    "found_cooldown_ticks": 3 * 1200,  # the first stair: wait 3 days for the miners before asking again
    "labor_cooldown_ticks": 1200,
    "feeder_cooldown_ticks": 1200,     # a feeder stockpile: at most one a day
    "fps_items_heavy": 30000,          # this many items while the game runs slowly: tidy up
    "tidy_cooldown_ticks": 7 * 1200,
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
    "fat_ban_cooldown_ticks": 7 * 1200,        # (0.104.30) fat and tallow kept from the cooks, a week apart        # (0.104.21) coffin jobs on the bench two days apart          # (0.104.20) walls built back in batches, three days apart         # (0.104.15) the dead unforbidden three days apart      # (0.104.13) the AI's suspended order jobs resumed two days apart
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
    "needs_craft_cooldown_ticks": 28 * 1200,
    "needs_drink_cooldown_ticks": 3 * 1200,
    "needs_meal_cooldown_ticks": 3 * 1200,
    "needs_build_at": 3,               # this many distracted by a need a tavern/library/shrine serves: build it early
    "needs_note_at": 2,                # a need this many are distracted by is named
    "gems_cut_at": 5,                  # rough gems before a jeweller's and gem cutting
    "gems_cooldown_ticks": 14 * 1200,
    "garden_min_citizens": 20,
    "great_hall_min_citizens": 60,     # (0.98) the plan's great hall: a fort this big, in good times         # set pieces: a fort this big...
    "garden_idle_share": 0.2,          # ...with this share idle...
    "garden_every_years": 2,
    "good_times_food_per_dwarf": 15,   # (0.102.1) a set piece's "good times": fed...
    "good_times_drink_per_dwarf": 2,   # ...and watered (a big fort keeps ~2 drinks a dwarf)
    "drink_hoard_share": 1.33,         # (0.103) Thirst-scarred: drink kept x this
    "grandeur_dress_at": 50,           # (0.102.6) a fort this grand puts statues in its halls
    "grandeur_cooldown_ticks": 3 * 1200,
    "temple_more_piety": 50,           # (0.102.1) a devout fort raises a temple to each god many pray to
    "temple_more_worshippers": 5,      # ...this many distracted for want of prayer to that god           # ...and none started this long (halved at Grandeur +100)
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
    "mood_lacking_days": 7,           # (0.103.8) a mood still lacking what no recipe makes: Needs you from this day
    "fuel_min": 10,
    "smelt_batch": 10,
    "metal_kit_bars": 8,               # weapon-grade bars a soldier before a squad goes from leather to metal
    "polish_idle_share": 0.3,          # this share idle: a finished level smoothed, then engraved
    "polish_cooldown_ticks": 3 * 1200,
    "thirsty_still_backlog": 5,        # (0.103.3) brew jobs waiting on each still before another, while thirsty
    "shop_backlog": 15,                # the AI's jobs waiting per workshop of a kind before another is built...
    "shops_max_each": 3,               # ...up to this many of a kind
    "bottleneck_cooldown_ticks": 14 * 1200,
    "cloth_min": 15,                   # cloth kept on hand (dressings, bags, rope, clothes)...
    "cloth_per_dwarf": 1.0,            # ...or a bolt a dwarf
    "cloth_batch": 5,
    "coke_when_fuel_below": 40,        # coke made from coal while fuel is under this
    "coke_batch": 5,
    "stone_low": 10,
    "quarry_when_dig_below": 20,       # a quarry only while little other digging waits...
    "quarry_dry_days": 10,             # (0.104.4) ...or, with no usable stone at all, every this many days
    "quarry_cooldown_ticks": 2 * 1200, # ...and at most every 2 days (0.99.4: was a week; region2's 30-tile quarries were dug out in days)
    "picks_per_dwarves": 30,           # (0.99.4) a pick for every this many dwarves while stone is short (3 at least)...
    "picks_max": 10,
    "picks_per_backlog": 40,           # (0.104.4) a pick more for every this many tiles waiting to be dug
    "fishery_raw_fish": 50,
    "unstick_uniforms_cooldown_ticks": 14 * 1200,   # (0.99.7) at most every two weeks
    "stray_gear_cooldown_ticks": 3 * 1200,   # (0.104.58) lost gear put back three days apart
    "assign_weapons_cooldown_ticks": 3 * 1200,   # (0.104.60) weapons handed out by the AI three days apart
    "soldier_swap_cooldown_ticks": 2 * 1200,    # (0.104.64) a starved soldier let go two days apart
    "soldier_swap_month_min": 2,                 # (0.104.114) swaps allowed in 28 days: this many at least ...
    "soldier_swap_month_share": 10,              # ... or one per this many soldiers
    "soldier_swap_keen_min": 5,                  # ...while at least this many civilians badly want to train
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
    "assign_weapons_wait_ticks": 7 * 1200,       # (0.104.60) ...once DF has left the places empty a week
    "crop_brew_threshold": 300,        # (0.99.6) autofarm's threshold for brewable crops while drink is short...
    "crop_other_threshold": 10,        # ...and for the rest (food is a fort's smaller worry by then)
    "crop_default_threshold": 50,      # autofarm's own default, put back once drink recovers
    "drink_recovered_per_dwarf": 4,
    "surface_farm_seeds": 50,          # (0.99.6) brewable surface seeds before surface plots are laid out...
    "seeds_per_plot": 10,              # ...while the underground plots have fewer seeds than this each
    "surface_farm_tiles": 60,    # drinks a dwarf before the crops go back to autofarm's way            # (0.99.4) raw fish waiting before a fishery is built (any fort's age)                   # ...up to the miners that don't get in each other's way                   # fewer usable boulders than this: free an economic stone, or wood
    "steel_want": 60,                  # steel bars made while there are fewer than this
    "iron_keep": 6,                    # iron bars never turned into steel (gear being made now)
    "steel_batch": 5,
    "order_stuck_days": 14,            # a work order that hasn't moved this long is named...
    "order_stuck_you_days": 28,
    "order_hold_days": 3,              # (0.104.0, was 7: the run check found 89 bag orders, 66 cancelled as stuck, in a day)
    "loop_hold_days": 28,              # an action done too often in a year (a loop) waits this long
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
    "petition_citizen_margin": 5,      # citizenship while citizens are this far under the population target
    "bag_sink_days": 28,               # this many bag orders in so many days with no empty bag: a sink (0.87.1)
    "bag_sink_orders": 3,
    "seed_bags_max": 30,
    "hospital_traction": 1,            # traction benches a hospital keeps (0.88)
    "traction_cooldown_ticks": 14 * 1200,
    "traction_parts_cooldown_ticks": 3 * 1200,
    "alert_keep_days": 1,              # alert icons cleared once this old (0.88)
    "alert_danger_days": 7,            # deaths, ambushes, beasts... kept this long
    "alerts_per_cycle": 50,
    "alerts_cooldown_ticks": 1200,
    "tree_quota_share": 0.8,           # felling stops at this share of the elves' yearly cap (0.89)
    "location_petitions_open": 1,      # agreed temple/guildhall petitions not yet built at once (0.89)
    "location_value_tier1": 2000,      # zone value of a temple or guildhall (DF wiki, Guildhall)
    "location_value_tier2": 10000,     # of a temple complex or grand guildhall
    "petition_answer_cooldown_ticks": 1200,
    "petition_build_cooldown_ticks": 7 * 1200,
    "location_value_cooldown_ticks": 2 * 1200,  # a statue every 2 days at most (0.90)               # bags made on top for the kinds of seed lying loose (0.88)
    "good_meals_pd": 2,                # meals worth over 20 kept a dwarf (EatGoodMeal; 0.83)
    "meals_hard_max_pd": 60,           # ... but no lavish meals past this many meals of any kind a dwarf
    "craft_shops_at": 10,              # this many want to craft: more Craftsdwarf's workshops for idle crafting
    "craft_shop_per": 8,               # ... one for every this many (0.104.53: 15 -> 8)
    "craft_shops_max": 8,              # (0.104.53: 4 -> 8; Enxah: 31 badly wanting to craft, 4 shops)
    "needs_shops_cooldown_ticks": 7 * 1200,
    "trinkets_per_cycle": 25,
    "fight_needs_at": 15,              # this many long to fight or train: more soldiers (they train)
    "fight_soldiers_max": 20,          # ... at most this many more
    "fight_share_max": 0.3,            # ... and never past this share of the citizens
    "idle_train_share": 0.4,           # this share of adults idle: every squad trains, and more may join (0.83)
    "idle_train_off_share": 0.25,      # ... until idle falls under this share
    "idle_avg_weight": 0.1,            # ... judged on a running average (this weight for each new reading)
    "idle_fight_soldiers_max": 30,     # ... then at most this many more soldiers for the needs
    "idle_fight_share_max": 0.45,      # ... and at most this share of the citizens
    "fight_min_citizens": 15,          # (0.103.9; was 30)
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
    "excess_shops_cooldown_ticks": 1200,           # good meals for the need: not past this many meals a dwarf in store              # no new order of a recipe whose AI order has stood still this long
    "stuck_order_cooldown_ticks": 0,   # (cancelling the AI's own stuck orders: several a cycle)
    "stuck_cancel_max": 5,             # ...at most this many a cycle
    "stuck_retry_days": 28,            # an order the AI cancelled as stuck isn't placed again for this long...
    "stuck_retry_max_days": 112,       # (0.104.37) ...doubled each time it sticks again, to this
    "stuck_again_days": 90,            # ...and stuck again within this long is Needs you        # ...and the AI's own is Needs you after this long                 # ore stones smelted per order
    "ore_stock_max": 30,               # dug ore waiting for the smelter: no new vein past this
    "trade_cooldown_ticks": 2 * 1200,
    "trade_margin": 1.2,
    "trade_anyone_after_ticks": 1200,  # the broker not at the depot a day after a caravan got there: anyone may trade
    "call_trader_cooldown_ticks": 300,               # the fort gives this much more value than it takes
    "trade_deal_cooldown_ticks": 600,  # a deal on the open trade screen: at most every half day
    "trade_bars_iron": 30,             # bought up to this many of each...
    "trade_leather": 10,
    "trade_thread": 10,
    "trade_wood": 50,
    "trade_drink_per_dwarf": 20,
    "soap_keep": 5,                    # soap bars kept for the hospital
    "soap_cooldown_ticks": 2 * 1200,
    "noble_rooms_cooldown_ticks": 1200,
    "uniform_cooldown_ticks": 1200,       # a squad's uniform: once a day   # rooms given to nobles: once a day  # goods to the depot: every 2 days while a caravan is here
    "crafts_cooldown_ticks": 14 * 1200,
    "hauling_cooldown_ticks": 14 * 1200,                    # charcoal or coke kept for the smelter
    "ore_cooldown_ticks": 7 * 1200,    # a vein mined: at most once a week
    "industry_cooldown_ticks": 7 * 1200,               # a mood gathering materials this long: say what's missing
    "gather_cooldown_ticks": 7 * 1200, # shrubs marked for gathering: at most once a week
    "train_min_citizens": 15,
    "train_rotate_days": 28,           # squads the AI trains take turns, half at a time, a month each...
    "train_rotate_below_militarism": 50,   # ...unless the fort is militant: then all train
    "young_fort": 20,                  # under this many dwarves the fort is young: food first, small and plain
    "found_food_per_dwarf": 15,
    "established_food_per_dwarf": 40,  # a small fort with farms, this much food and the drink below is no longer young
    "established_drink_per_dwarf": 15,
    "gather_jobs_max": 60,             # more plant-gathering jobs than this in a fed fort: trimmed...
    "gather_jobs_keep": 20,            # ...to this many        # a young fort without this much food a dwarf digs no new homes
    "dig_backlog_per_miner": 50,       # no new level while more than this waits to be dug, per miner          # a smaller fort keeps its soldiers at work (they train once it grows)
    "water_gate_recheck_ticks": 3 * 28 * 1200,  # a water gate is looked at again each season   # a lever link asked for: wait 2 weeks for the mechanic
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
    "slow_dig_days": 336,              # (0.104.12) a project under half dug in a game year is given up
    "statue_wait_days": 56,            # (0.104.12) a level waiting only for statues (no stone) this long is finished
    "statue_wait_days_any": 112,         # (0.104.33) a level finished without its statues after this long, stone or not
    "stuck_project_days": 21,          # (0.100.1) a level whose digging stopped is given up after this          # (0.100.1) no soldiers below this unless threatened
    "min_dwarves_for_farms": 3,                 # (0.100.1) was 7: one early death stopped the farms
    # Farms (docs/building.md): tiles per dwarf at Agriculture 0, for the
    # population the fort is growing toward; x2 at +100 ("Big farms")
    "farm_tiles_per_dwarf": 1.0,
    "min_farm_tiles": 9,
    "max_farm_tiles": 400,
    "farm_refill_share": 0.75,     # lay out more when below this share of the target
    "farms_cooldown_ticks": 3 * 1200,
    "farm_dig_retry_days": 28,     # no soil for a farm level: look again (and ask again) after this
    "well_cooldown_ticks": 3 * 1200,
    "new_pasture_cooldown_ticks": 3 * 1200,
    "pasture_margin": 1.25,        # a new pasture: the waiting herd's grass x this (x more at high Husbandry)
    "well_parts_days": 3,          # a well waiting this long for parts: say what to make
    # bars each item takes, roughly (conservative, so orders never outrun the bars)
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
}

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
                   "Kiln", "SoapMaker", "GlassFurnace"}
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

# Rules exempt from the per-rule cooldown and the one-per-cycle limit.
NO_COOLDOWN = {"threat_alert", "strategist", "squad_attack", "squad_recall", "train", "gates", "water", "flood",
               "trade_deal", "close_trade"}   # (time stands still while the trade screen is open)
MULTI_PER_CYCLE = {"stuck_order", "uniform", "noble_rooms", "tools", "strategist", "squad_attack", "squad_recall", "train", "labor", "well_parts"}
# Responses to an attack: never held back by the per-cycle action limit.
EMERGENCY = {"threat_alert", "gate", "gates", "squad_attack", "flood", "gate_guard"}   # (0.104.83 gate_guard)
# (0.104.89) rules the strategist may never hold: survival, safety and the
# answers to danger (it may still raise them)
STEER_PROTECTED = EMERGENCY | {"shelter", "alerts", "squad_recall", "hazard", "water", "well", "drink",
                               "needs_drink", "food", "farm", "gather", "care", "staff", "burial", "unsuspend",
                               "stuck_order", "tools", "found", "entrances", "trouble"}
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
STUCK_HOLD_EXEMPT = {"drink", "drink_fruit", "food", "well_parts"}   # (0.104.2) a well's parts: water for the injured     # (0.100.1) see select()
# Also outside the limit: switching a squad's schedule (instant, undoable).
LIMIT_EXEMPT = EMERGENCY | {"join_levels", "census", "train", "shelter", "entrances", "labor", "gather", "stuck_order", "alerts",
                            "kitchen"}   # (0.100) a kitchen setting, once per drink shortage: no slot of its own


@dataclass
class Proposal:
    rule: str
    action: dict
    reason: str
    priority: int  # lower runs first
    is_order: bool = False


@dataclass
class Memory:
    """What the overseer remembers between cycles, saved per fort."""
    last_fired: dict = field(default_factory=dict)       # rule -> absolute tick
    orders_by_day: dict = field(default_factory=dict)    # absolute game day (str) -> count
    ai_alert_raised: bool = False
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
    farm_steer: str = ""                                 # (0.99.6) "drink" while autofarm's thresholds favour brewable crops
    kitchen_ban: bool = False                            # (0.100) the AI banned cooking brewables while drink is short
    fat_ban: bool = False                                # (0.104.30) the AI kept fat and tallow from the cooks
    storage_started: int | None = None                   # (0.104.38) when the AI last began a storage level for full piles
    tantrums: list = field(default_factory=list)         # (0.104.31) [tick, who] of recent tantrums, a day each
    shops_seen: dict = field(default_factory=dict)       # (0.99.4) workshop name -> how many stood at its last start
    tree_year: dict = field(default_factory=dict)        # (0.89) {year, base}: trees_removed when the game year began
    polished_upto: int | None = None                     # finished-level count when every level was found polished
    story_season: str = ""                                # the last season the AI-written chronicle told ("y<year> <season>")
    gate_closed_by_ai: bool = False                      # the AI pulled the gate lever to close it
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
    gate_doors_requested: list = field(default_factory=list)  # entrances ("x,y,z") given doors
    rescan_entrances: bool = False                       # map the entrances again next cycle
    caverns_open: list = field(default_factory=list)     # caverns seen joined to the fort's ground
    gates_fortified: dict = field(default_factory=dict)  # entrance "x,y,z" -> gate style built there
    gates_fortified_ticks: dict = field(default_factory=dict)  # entrance "x,y,z" -> when (first seen open since)
    gate_failures: dict = field(default_factory=dict)    # entrance "x,y,z" -> why the game refused
    gate_failure_ticks: dict = field(default_factory=dict)  # entrance "x,y,z" -> when (tried again later)
    well_failure: str = ""                               # why no well could be placed (Needs you)
    cavern_well_failure: str = ""                        # why no cavern well could be placed either
    cavern_shaft_stairs: bool = False                     # (0.104.13) the old shaft's give-up was cleared once
    patient_since: dict = field(default_factory=dict)    # citizen id (str) -> tick first seen needing care
    pasture_failure: str = ""                            # why no pasture could be made (Needs you)
    farm_failure: str = ""                               # why no farm plots could be placed (Needs you)
    farm_failure_tick: int | None = None                 # when a farm level last couldn't be dug
    report_season: str = ""                              # the last season the player's report was written for
    found_failure: str = ""                              # why the first staircase couldn't be dug (Needs you)
    fps_cap: int | None = None                           # the population cap held while the game runs slowly
    strain_hold: bool = False                            # (0.104.106) newcomers held while the fort is strained
    gear_spare_since: dict = field(default_factory=dict)  # "weapons"/"body"/"helms" -> when 3+ spares sat unused
    swapped: dict = field(default_factory=dict)  # (0.104.78) unit id -> when the swap sent them home
    steer: dict = field(default_factory=dict)    # (0.104.89) the strategist's raised and held rules: rule -> {mode, until, why}
    strategist_wants: list = field(default_factory=list)   # (0.104.89) report sections it asked to see in full next time
    token_ratio: float = 1.0                     # (0.104.89) a review's real cost against its estimate, learned
    maintain_pop: int | None = None                      # Maintain: the population being kept
    last_expel_tick: int | None = None                   # when a dwarf was last sent away
    last_join_tick: int | None = None                    # (0.104.108) when areas on a level were last looked at for joining
    census: dict = field(default_factory=dict)           # (0.104.113) the last census of creatures and items (with "tick")
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
    for k, v in (adjust if isinstance(adjust, dict) else {}).items():
        if k in cfg and k in ADJUST_BOUNDS and _number(v):
            lo, hi = ADJUST_BOUNDS[k]
            cfg[k] = max(lo, min(hi, v))
    return cfg


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


def _clamp(v: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, round(v))))


MEMORIAL_SPAN = {"every": 0, "season": TICKS_PER_YEAR // 4, "year": TICKS_PER_YEAR}
OPTIONAL_LEVELS = ("tombs", "hospital", "tavern", "library", "barracks", "temple", "jail", "archery", "garden")
GEAR_WEAPONS = {"axe": "metal_battle_axe", "spear": "metal_spear", "mace": "metal_mace"}
GEAR_METALS = ("STEEL", "IRON", "BRONZE", "BISMUTH_BRONZE", "COPPER")     # best first
GEAR_RECIPES = set(GEAR_WEAPONS.values()) | {"metal_mail_shirt", "metal_breastplate", "metal_helm"}


# Notes that ask the PLAYER to do something the AI can't (set up a burrow,
# link a lever...). The overseer shows them apart: "Needs you".
NEEDS_YOU = "[you] "


def ask_player(notes: list, text: str) -> None:
    notes.append(NEEDS_YOU + text)


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
            "clear_alerts": st.get("clear_alerts") if st.get("clear_alerts") in ("all", "quiet", "none") else "quiet"}


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
    return t if isinstance(t, dict) else {}


def reachable_threats(s: dict, traits: dict, cfg: dict) -> list:
    """Ids of threats that can reach the dwarves (plus, at Caution +100, nearby
    ones whose reach is unknown). Threats counted but not listed get stand-in ids."""
    o = s["others_on_map"]
    threats = o.get("threats") or []
    ids = [t.get("id") for t in threats if t.get("can_reach_dwarves") is True]
    unlisted = max(0, (o.get("threats_that_can_reach_dwarves") or 0) - len(ids))
    ids += [f"unlisted{i}" for i in range(unlisted)]
    if traits.get("caution", 0) >= 100:
        for t in threats:
            lv = t.get("levels_from_nearest_dwarf")
            if t.get("can_reach_dwarves") is None and lv is not None and lv <= cfg["cautious_alert_levels"]:
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
        return False, f"the last threat was {days} day(s) ago"
    return True, ""


def held_off_threats(s: dict) -> list:
    """(0.100.1) Threats on the map that can't walk in right now (a raised
    bridge, a shut door) but are still there: invaders anywhere, and dangers
    up on the surface. Cavern creatures that can't reach aren't counted (they
    never leave, and would keep the fort shut for good)."""
    o = _d(s.get("others_on_map"))
    return [t for t in _l(o.get("threats")) if isinstance(t, dict) and t.get("can_reach_dwarves") is not True
            and (t.get("invader") or t.get("layer") == "upper_levels")]


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
                "coke_lignite": "Smelter", "smelt_ore": "Smelter", "brew_drink": "Still",
                "brew_drink_from_fruit": "Still", "make_mead": "Still", "make_charcoal": "WoodFurnace",
                "weave_plant_cloth": "Loom", "process_plants": "Farmers", "make_quicklime": "Kiln",
                "make_plaster_powder": "Kiln", "make_milk_of_lime": "Ashery", "make_parchment": "Tanners",
                "make_quire": "Craftsdwarfs",
                # (0.104.87) sewn at a clothier's (an order for one the fort hasn't waits)
                "cloth_bag": "Clothiers", "silk_bag": "Clothiers", "yarn_bag": "Clothiers",
                # (0.104.95) glass is made at a glass furnace, precious metal crafts at the forge
                "collect_sand": "GlassFurnace", "metal_crafts": "MetalsmithsForge"}


# (0.100.1, overnight run) the workshop a recipe is made at, where it's sure:
# an order for a workshop the fort doesn't have never moves (130 brew jobs and
# meals and beds waited five years with no still, kitchen or carpenter, were
# cancelled as stuck and ordered again: 338 cancels in a night)
WOOD_ELSEWHERE = {"wooden_crossbow": "Bowyers", "wooden_bolts": "Bowyers", "wooden_cups": "Craftsdwarfs"}


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


def brew_recipe(s: dict) -> str | None:
    """(13c) The brew recipe a still can do now: from plants if any can be
    brewed, else from fruit, else None. The bridge's brewable counts
    (0.99.5) when it sends them, the raw stocks otherwise."""
    st, sup = _d(s.get("stocks")), _d(s.get("supplies"))
    if isinstance(sup.get("brewable_plants"), int):
        plants, fruit = sup["brewable_plants"], int(sup.get("brewable_growths") or 0)
    else:
        plants, fruit = int(st.get("plants") or 0), int(st.get("plant_growths") or 0)
    return "brew_drink" if plants > 0 else "brew_drink_from_fruit" if fruit > 0 else None


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
        days = (now - w["since"]) // TICKS_PER_DAY
        if days < cfg["order_stuck_days"]:
            continue
        shop = JOB_SHOPS.get(str(w.get("job")))
        state = order_job_state(by_id.get(str(k))) if jobs_reported(s) else ""   # (0.104.13) what its job is doing
        why = (f"the fort has no {shop}" if shop and not _has_shop(_d(s.get("buildings")), shop)
               else (state + "; " if state else "") + "check its workshop, who may do the job, and its materials")
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
        ask_player(notes, f"{len(stuck_you)} of the AI's work order(s) keep getting stuck (cancelled once, "
                   "stuck again): "
                   + "; ".join(sorted(stuck_you)[:3]))
    pw = memory.pop_watch if isinstance(memory.pop_watch, dict) else {}
    cap = _d(s.get("society")).get("pop_cap")
    if isinstance(pw.get("since"), int) and now - pw["since"] >= TICKS_PER_YEAR and (not cap or pw.get("pop", 0) < cap):
        notes.append(f"the fort has had {pw.get('pop')} dwarves for a year or more"
                     + (f" (population cap {cap})" if cap else "")
                     + ": migrants come to a fort that grows richer (crafts for the caravans, built rooms); "
                     "if none come at all, check the population cap in DF's settings")


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
    return f"{j.get('n')} job(s) wait at the workshop for a worker with the labour"


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
    if st.get("cloth"):
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
    time; quarries 30 x factor (10-60)."""
    m = traits.get("mining", 0) or 0
    f = factor(traits, "mining")
    return {"need_only": m <= -100,
            "veins": m > -50,
            "bars_below": int(cfg["smelt_when_bars_below"] * f),
            "ore_stock_max": int(cfg["ore_stock_max"] * f),
            "vein_tiles": max(10, min(80, int(40 * f))),
            "quarry": max(10, min(60, int(30 * f)))}


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
    return sum(1 for p in _l(_d(s.get("health")).get("patients")) if isinstance(p, dict) and _l(p.get("needs")))


def unmet(s: dict, *names: str) -> int:
    """Citizens distracted by any of these needs (the bridge's `needs` report)."""
    n = _d(_d(s.get("needs")).get("needs"))
    return sum(int(_d(n.get(k)).get("distracted") or 0) for k in names)


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
        recent = {str(k) for k, t in _d(getattr(memory, "swapped", None)).items()
                  if isinstance(t, int) and 0 <= now - t < 7 * TICKS_PER_DAY}
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
        if month >= max(cfg["soldier_swap_month_min"], soldiers // cfg["soldier_swap_month_share"]):
            return
    x = max(starved, key=lambda v: len(_l(v.get("unmet"))))
    proposals.append(Proposal("soldier_swap", {"type": "squad_swap", "unit_id": x["id"]},
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


def _idle_share(s: dict) -> float:
    dw = _d(s.get("dwarves"))
    return (dw.get("idle_adults") or 0) / max(1, dw.get("adults") or 1)


def update_idle(s: dict, memory, cfg: dict) -> None:
    """(0.84; called by note_cycle, before planning) The running average of
    the idle share (memory.idle_avg: the count of idle dwarves jumps from
    cycle to cycle; live, 0.83: over 40%, under 25% and back within three
    game days, so the rotation sent a squad off duty and back), and the band
    on it (memory.idle_hands): on from `idle_train_share` (40%), off only
    under `idle_train_off_share` (25%), since the dwarves who then train
    aren't idle any more."""
    share = _idle_share(s)
    avg = memory.idle_avg
    if isinstance(avg, (int, float)):
        share = (1 - cfg["idle_avg_weight"]) * avg + cfg["idle_avg_weight"] * share
    memory.idle_avg = round(share, 4)
    memory.idle_hands = share >= cfg["idle_train_share"] or (memory.idle_hands and share >= cfg["idle_train_off_share"])


# What a rule works toward, in a few words (the season's agenda)
AGENDA_THEMES = {
    "arms": "arm and armour the soldiers", "uniform": "dress the squads", "barracks_assign": "house the squads",
    "squad_fill": "fill the squads", "grandeur": "dress the halls", "quick_temple": "a place to pray", "quick_tavern": "a tavern", "stress_care": "care for dwarves near breaking", "squad_trim": "send extra soldiers back to work", "unload_depot": "empty the depot after the caravans", "needs_finery": "jewellery to wear", "good_cooks": "the best cooks to the kitchen", "squad_make": "raise a new squad", "uniform_adopt": "dress the squads", "staff": "staff the hospital, library and tavern", "tavern": "stock the tavern", "kiln": "plaster and paper", "anvil": "an anvil for a new forge", "petitions": "answer petitions", "train": "train the soldiers",
    "build": "build the fort's next level", "furniture": "furnish the new levels",
    "steel": "make steel", "smelt": "smelt the ore", "ore": "mine ore", "fuel": "make fuel",
    "trade": "trade with the caravans", "trade_deal": "trade with the caravans", "crafts": "make goods to sell",
    "gems": "cut gems", "encrust": "set gems into crafts", "drink": "keep the drink flowing",
    "needs_drink": "keep the drink flowing", "needs_meal": "cook good meals", "needs_craft": "let dwarves craft",
    "food": "keep the fort fed", "farm": "farm", "hospital": "stock the hospital", "soap": "make soap",
    "feeder": "shorten the hauling", "labor": "put idle hands to work", "well": "find water for a well",
    "stuck_order": "clear stuck work", "unsuspend": "resume suspended work", "stray_gear": "hand out lost gear", "assign_weapons": "arm the soldiers", "soldier_swap": "let the keen train", "temple_chest": "a chest for the temple", "instrument_orders": "clear the instrument backlog", "pair_chairs": "seat dwarves together", "recreation": "time off for the unhappiest", "dairy": "milk and cheese", "eggs": "nest boxes for the hens", "war_animals": "train war animals", "gate_guard": "hold the gate", "gate_dogs": "war dogs at the gate", "gem_cutting": "cut the rough gems", "stairwell": "a new stairwell", "animal_trainer": "an animal trainer", "nest_box_order": "make nest boxes", "library_chest": "a chest for the library", "orphan_jobs": "clear jobs whose order is gone", "slabs_free": "free the memorial slabs", "water_traffic": "keep paths off the ice", "jail_size": "a bigger jail", "burial": "bury the dead", "rooms": "mend the rooms' walls", "coffins": "coffins for the tombs", "order_slots": "free the workshop's order slots", "fat_ban": "keep fat for soap", "jail_urgent": "a jail against the beatings", "tavern_urgent": "a tavern for company", "quarry": "quarry stone", "cloth": "weave cloth",
}


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
REFUSAL_KEYS = ("type", "kind", "recipe", "job", "entrance_id", "project_id", "name", "squad_id",
                "lever_id", "target_id", "tool", "unit_id",      # (0.103.12) unit_id: one dwarf's refusal isn't another's
                "zone_id", "order_id", "location_id")            # (0.104.81) nor one zone's, order's or location's


def refusal_key(p: Proposal) -> str:
    a = p.action if isinstance(p.action, dict) else {}
    return p.rule + ":" + json.dumps({k: a.get(k) for k in REFUSAL_KEYS if k in a}, sort_keys=True)


def _refused_wait(memory: Memory, p: Proposal, now: int, bridge: str | None = None) -> int | None:
    """Days left before a refused action may be tried again, or None. A
    refusal booked under another bridge version is tried again at once: new
    code may do what the old couldn't (0.81: squads refused for want of a
    captain's post waited up to 84 days after the bridge learned to add one)."""
    if p.rule in EMERGENCY:
        return None
    r = _d((memory.refusals or {}).get(refusal_key(p)))
    if bridge and r and r.get("v") != bridge:   # (refusals from before 0.81 carry no version: once more)
        return None
    until = r.get("until")
    if isinstance(until, int) and 0 <= now < until:
        return max(1, -(-(until - now) // TICKS_PER_DAY))
    return None


def note_refusal(memory: Memory, p: Proposal, r: dict, now: int, bridge: str | None = None) -> None:
    """Book a refusal (or clear the count after a success), with the bridge
    version that refused it."""
    if not isinstance(memory.refusals, dict):
        memory.refusals = {}
    key = refusal_key(p)
    if r.get("ok") is True and p.action.get("type") == "polish" and r.get("designated") == 0:
        r = {"ok": False, "error": r.get("note") or "nothing to smooth or engrave"}   # nothing done: back off
    if r.get("ok") is True:
        memory.refusals.pop(key, None)
        return
    if r.get("ok") is not False or r.get("halted") or p.rule in EMERGENCY:
        return                     # unknown, or stopped by the in-game halt: not the game saying no
    if r.get("waiting"):           # work under way (trees being felled): look again in 2 days, no back-off
        memory.refusals[key] = {"n": 0, "until": now + 2 * TICKS_PER_DAY, "at": now,
                                "why": str(r.get("error") or "")[:120]}
        if bridge:
            memory.refusals[key]["v"] = str(bridge)
        return
    old = _d(memory.refusals.get(key))
    n = int(old.get("n") or 0) + 1
    days = min(REFUSAL_MAX_DAYS, REFUSAL_FIRST_DAYS * 2 ** (n - 1))
    if p.action.get("type") == "squad_release" and "longs to fight or train" in str(r.get("error") or ""):
        days = max(days, 56)       # (0.104.34) a need that lasts: Enxah asked 368 times, 10 dwarves, all refused
    memory.refusals[key] = {"n": n, "until": now + days * TICKS_PER_DAY, "at": now,
                            "why": str(r.get("error") or "")[:120]}
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
               "dismiss_alerts": 400}
LOOP_LIMIT_DEFAULT = 80
LOOP_EXEMPT = {"entrances", "needs_trinkets", "excess_shops", "cistern", "call_trader", "open_trade",
               "trade_deal", "close_trade", "trade", "train", "water", "project"}


def _loop_count(memory: Memory, p: Proposal, now: int) -> int | None:
    """How often this action was done in the last game year, when that is
    over its limit and it was done again recently (else None)."""
    if p.rule in LOOP_EXEMPT or p.rule in EMERGENCY:
        return None
    log = (getattr(memory, "action_log", None) or {}).get(refusal_key(p)) or []
    recent = [t for t in log if isinstance(t, int) and 0 <= now - t < TICKS_PER_YEAR]
    limit = LOOP_LIMITS.get(str(p.action.get("type")), LOOP_LIMIT_DEFAULT)
    if len(recent) >= limit and recent and now - max(recent) < PLANNER_CONFIG["loop_hold_days"] * TICKS_PER_DAY:
        return len(recent)
    return None


def _stalled_days(memory: Memory, recipe: str, now: int) -> int | None:
    """Days the AI's longest-waiting order of this recipe has stood still (None: no
    unfinished AI order of it). More copies of an order that doesn't move only
    pile up (0.75 overnight prep: drink orders were placed and cancelled as stuck
    in turn, all evening)."""
    best = None
    for w in (getattr(memory, "order_watch", None) or {}).values():
        if (isinstance(w, dict) and w.get("by_ai") and str(w.get("what")) == recipe
                and isinstance(w.get("since"), int) and (w.get("left") or 0) > 0):
            days = max(0, (now - w["since"]) // TICKS_PER_DAY)
            best = days if best is None else max(best, days)
    return best


def _entrance_spot(state: dict, entrance_id) -> str | None:
    for e in _l(_d(state.get("entrances")).get("entrances")):
        if isinstance(e, dict) and e.get("id") == entrance_id:
            return f"{e.get('x')},{e.get('y')},{e.get('z')}"
    return None


def _record_any_outcome(a: dict, r: dict, state: dict, memory, now: int) -> None:
    """Bookkeeping that holds whether the action worked or was refused, so a
    refusal is never simply asked again every cycle."""
    t = a.get("type")
    if t == "clear_gate" and r.get("ok") is False and isinstance(a.get("spot"), str):
        # nothing left, or the game says it's real: don't ask again
        reg = _d(_d(memory.atlas).get("registry"))
        for prefix in ("gate:", "doors:"):
            rec = reg.get(prefix + a["spot"])
            if isinstance(rec, dict):
                rec["status"] = "taken down" if "nothing" in str(r.get("error")) else "kept"
    if t == "setup_shelter":
        memory.shelter_attempts += 1          # refused or not: two tries, then it's yours
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
    elif t == "place_well":
        memory.last_fired["well"] = now          # refused or not: wait the full spell
        if a.get("cavern"):
            if r.get("ok") is False and not r.get("rejected"):
                memory.cavern_well_failure = str(r.get("error") or "refused")[:300]
        elif r.get("ok") is True:
            memory.well_failure = ""
        elif r.get("ok") is False and not r.get("rejected"):
            memory.well_failure = str(r.get("error") or "refused")[:300]
    elif t == "furnish_project" and r.get("ok") is False and "well" in str(r.get("error") or ""):
        memory.well_failure = str(r.get("error"))[:300]
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
            memory.found_failure = ""
        elif r.get("ok") is False and not r.get("rejected"):
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
    elif t == "link_lever" and not a.get("dry_run"):
        key = f"lever:{a.get('lever_id')}>{a.get('target_id')}"
        if r.get("ok") is False:
            memory.gate_failures[key] = str(r.get("error") or "refused")[:300]
            memory.gate_failure_ticks[key] = now
        else:
            memory.gate_failures.pop(key, None)
            memory.gate_failure_ticks.pop(key, None)
            memory.rescan_entrances = True        # the link shows in the next scan once it's made
    elif t in ("build_gate_doors", "fortify_entrance"):
        spot = _entrance_spot(state, a.get("entrance_id"))
        if not spot:
            return
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


def _weapon_gaps(gear: dict) -> bool:
    """(0.104.60) Soldiers on duty with places whose weapon entry is empty
    while free weapons (or crossbows) lie on the game's unassigned list."""
    free_w = (sum(int(v or 0) for k, v in _d(gear.get("spare_weapons")).items()
                  if isinstance(v, (int, float)) and k != "ITEM_WEAPON_PICK")      # a pick is a miner's tool
              + int(gear.get("spare_crossbows") or 0))
    return int(gear.get("weapon_gaps") or 0) > 0 and free_w > 0 and int(gear.get("on_duty") or 0) > 0
