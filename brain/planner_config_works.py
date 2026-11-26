"""planner_config_works: part of PLANNER_CONFIG (brain/planner_config.py), split out in
r7 d6 and applied third: farms, water works and magma, wells, bars a job takes, limits, the army,
threat triage, gates and ways in, missions, the insane, world clean-up,
evil weather, hauling, the food store, wheelbarrows, alloys, traffic.
Moved verbatim: keys, values, order and comments as they were."""

__all__ = ["PART"]

PART = {
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
    # (r1 g3) 40 (was 70): E had one cavern well for 80-94 dwarves; a well
    # serves the patients and the thirsty of about 40 (R-CE, A3 B8)
    "dwarves_per_well": 40,            # (0.104.141) another well for every this many dwarves (0: one well)
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
    # (item2) bolts: one open order at a time, sized to the gap (lots of 25) up
    # to this; one standing still this many days gets another material beside it
    "bolts_order_max": 10,
    "bolts_stall_days": 7,
    "bolts_reserve_per_soldier": 25,   # at war: a combat-only share of each crossbow squad's bolts (0: none)
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
    # (0.105.48, K1) threat triage (planner_core.reachable_threats): wildlife smaller than this
    # (a dwarf is ~60,000; a falcon 129, a wolf ~50,000) never sounds the alarm or shuts the gates
    "wildlife_alarm_size": 2000000,
    # (0.105.51) ...but wildlife is small only alone or weak: `wild_pack_min` animals of
    # `wild_pack_member_size` or more that can reach the dwarves (C, winter 251: 9 giant dingoes
    # killed 10 of 14 with no alarm), one inside, two or more the free squads don't beat at
    # fight_ratio, or a lone one at grips with a dwarf and no squad that beats it: the alarm
    "wild_pack_min": 3,
    "wild_pack_member_size": 10000,     # a dwarf ~60,000, a giant dingo ~30,000; a falcon 129, a kea ~400
    # (0.105.48, K1) the "can reach" alarm's maximum time (War-hold: up 30 days for a falcon): after
    # this long with no enemy near a dwarf or inside, it comes down, and is not raised again for the
    # same enemies until one comes near or a new one comes
    "reach_alarm_max_days": 3,
    "fight_ratio_inside": 1.0,          # (K1) an ambush too strong for the squads: they go at the ones inside at this

    "reach_alarm_near_tiles": 25,       # ...near: this close to a dwarf (levels count 3)
    "reach_alarm_near_tiles_fast": 60,  # ...for a great danger or a flier
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
    "gate_stuck_prevent_max": 4,        # (0.105.48) ...and tried this many times at most (waits 1, 3, 7 days x the above)
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
    # (item11) the close kin of the living insane cared for first too (planner_insane.insane_kin):
    # very unhappy or worse, or unhappy with long-term stress this high
    "insane_kin_care": True,
    "insane_kin_longterm": 25000,
    # (item7, the player's "Bring water to them") DF lets no insane dwarf drink or
    # eat: the melancholy and raving get their thirst timer set back to 0 from
    # this thirst (DF: dehydrated 50000, dead 75000) and their hunger timer from
    # this hunger (starving 75000), directly through DFHack (insane_water action;
    # the bridge never goes below its own 40000 / 65000); a try that did not take
    # is asked again after insane_water_retry_ticks. False: off (they die of thirst).
    "insane_water": True,
    "insane_water_thirst": 40000,
    "insane_water_hunger": 65000,
    "insane_water_retry_ticks": 600,
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
    "weather_keep_in": True,              # (item4) the civilians kept in by the shelter's burrow, not the alarm
    "weather_keep_in_ticks": 100,         # ...sent again this often while it lasts (newcomers kept in too)
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
}
