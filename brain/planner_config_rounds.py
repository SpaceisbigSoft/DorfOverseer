"""planner_config_rounds: part of PLANNER_CONFIG (brain/planner_config.py), split out in
r7 d6 and applied fifth (last before the blocks in planner_config.py itself): the
PLANNER_CONFIG.update blocks of 0.105.47 to r5, in their order (the herd, missions,
the way out, raids, claimed artifacts, shelter, thirst, ... refusal streaks).
Moved verbatim: keys, values, order and comments as they were."""

__all__ = ["PART"]

PART = {}
# (0.105.47) the herd by Husbandry (brain/planner_husbandry.py, lua/ai-herd.lua).
# The herd cap is the tools rule's: max(herd_min, citizens x herd_per_dwarf) x
# the Husbandry factor (and autobutcher on everywhere while the game runs slowly).
PART.update({
    "husbandry_high": 30,                 # Husbandry from here: breeders kept, wild ones tamed, pastures ahead of the herd
    "husbandry_low": -30,                 # ...to here: a small herd, the surplus to the butcher (autobutcher on)
    "herd_breed_females": 2,              # females kept a kind (x the Husbandry factor, up to 8), with one male
    "herd_breeders_cooldown_ticks": 7 * 1200,
    "herd_low_min": 8,                    # low Husbandry: autobutcher on past this many tame animals
    "herd_cull_cooldown_ticks": 7 * 1200,
    # autobutcher's targets (kids f, kids m, adults f, adults m) a kind keeps, by Husbandry
    "herd_targets_low": (0, 0, 2, 1),
    "herd_targets_mid": (1, 1, 3, 1),
    "herd_targets_high": (3, 2, 6, 2),
    "herd_targets_cooldown_ticks": 7 * 1200,
    "tame_wild_max": 2,                   # caged wild animals put to taming a call
    "tame_wild_cooldown_ticks": 3 * 1200,
    "herd_pasture_margin": 1.25,          # high Husbandry: the AI's grass kept at the grazers' need x this x the factor
    "herd_pasture_min_deficit": 20,       # ...when short by at least this many tiles
    "herd_pastures_max": 12,              # the AI's own pastures at most
    "shearing_cooldown_ticks": 14 * 1200, # wool shorn a fortnight apart (only the animals with wool grown)
    "milking_cooldown_ticks": 3 * 1200,   # milked every few days (only the ones with milk now)
    "herd_produce_batch": 10,             # shear or milk jobs an order at most
    "war_animals_cap": 24,                # war animals at most, at any Militarism
    "hunt_animals_militarism": 50,        # hunting training from this Militarism
    "hunt_animals_max": 4,                # hunting animals (trained or in training) x the Militarism factor
    "train_hunt_cooldown_ticks": 3 * 1200,
})
# (0.105.47) missions by the World screen: a site DF said is INACCESSIBLE
# (an island) is not named again for this long (brain/planner_missions.py)
PART.update({
    "mission_unreachable_ticks": 3 * 403200,
    # a mission set up but not yet set out (no army for its controller): noted after this many days
    "mission_depart_wait_days": 14,
    # a mission set up whose travellers can't walk off the map this long: one of the AI's gates opened, once
    "mission_way_stuck_hours": 6,
})
# (0.105.47, J16) the way out: a fort sealed in by the AI's own gates is
# opened once the cause is gone (brain/planner_way_out.py)
PART.update({
    "way_out_cause_gone_ticks": 600,      # the cause gone this long (half a day, the watcher's reopen): opened
    "way_out_danger_tiles": 60,           # a danger in sight this near a surface gate keeps it shut (the watcher's WIDE)
    "way_out_soft_days": 2,               # the alert, the alarm's hold, danger unread keep it shut this long at most
    "way_out_tries": 2,                   # openings tried before a way is dug out
    "way_out_retry_ticks": 150,           # between two openings (the walk map redone, a bridge's pull walked)
    "way_out_dig_tries": 2,               # digs asked for before Needs you
    "way_out_dig_retry_days": 4,
    # (0.105.51) a refused dig: asked again after way_out_dig_retry_days, doubled with each refusal in a
    # row, this many days at most; the refusal remembered this long past the way reading open again
    "way_out_dig_backoff_max_days": 32,
    "way_out_dig_refusal_keep_days": 32,
    "way_out_ask_after_ticks": 600,       # sealed this long (read fresh) before the player is asked
})
# (0.105.47, J17) the raid policy by the fort's character (brain/planner_raids.py)
PART.update({
    "raid_aggressive_militarism": 100,    # Militarism at or past this (the War-hold's 150): aggressive
    "raid_timid_militarism": -50,         # at or below this (the Monastery's -60): only a sure win, a threat close by
    "raid_retaliate_years": 3,            # a civ that attacked the fort within this many years may be raided back
    "raid_near_tiles": 8,                 # a hostile (or ownerless) camp or fort this near: removed before it grows
    "raid_new_tiles": 16,                 # ...one that appeared since the AI began watching, this near
    "raid_timid_tiles": 4,                # the timid fort's threat distance
    "raid_ratio": 2.0,                    # the squads at least this many times the site's strength: a clear win
    "raid_ratio_timid": 3.0,              # ...for the timid fort
    "raid_ratio_caution": 0.5,            # ...plus this at Caution 100 (scaled; never less)
    "raid_site_base": 4.0,                # a site's strength: base + per resident (capped) x its type's weight
    "raid_resident_power": 0.5,
    "raid_resident_cap": 200,
    "raid_unknown_pop": 60,               # residents assumed when the report can't say
    "raid_cooldown_days": 84,             # a season between two offensive missions
    "raid_friends_min": 2,                # civs kept as friends by the aggressive fort (traders, contact) at least
    "raid_greed_rich": 60,                # Greed at or past this: the aggressive fort prefers the richest clear win
    "raid_pet_restore_days": 2,           # pets let out for a mission put back this long after, once all are home
})
# (r1 g7) visitors who come for the fort's artifacts (B, 16 Nov: lone heroes
# came in as guests for claimed artifacts and killed 24 citizens; F lost its
# last 4 to two visiting humans). While an artifact another civ claims (or a
# figure from afar, or a hero named when spotted) lies in the fort, the
# tavern, temples, library and guildhalls stay shut to visitors, whatever
# Outsiders says (planner_visitors.claimed_shut)
PART.update({
    "g7_claimed_shut": True,              # the lockout while claimed artifacts are in the fort (off: never)
    "g7_hf_claims_risk": True,            # an artifact a historical figure from afar claims counts too (remote_claims)
    "g7_risk_hold_days": 7,               # the last artifacts report saying "at risk" holds this long without a newer one
    "g7_sought_keep_days": 1008,          # an artifact a spotted hero named ("stand between me and X") is sought this long (3 years)
    "g7_sought_keep_max": 30,             # names of sought artifacts remembered at most
})

# (R1 g4) the civilians' shelter (brain/planner_shelter.py; before the floors'
# block, which test_b10_floor_grammar wants last; the walk's own
# numbers are lua/ai-shelter-plan.lua SHELTER_DANGER_*): A2/E's flee and
# pick undid each other every cycle (18 moves in two minutes, civilians on
# levels with 0 drink); B's pick sent them past the killer
PART.update({
    "g4_shelter_hold_ticks": 1200,        # once the shelter moved (or went back to the whole fort) for the dangers
                                          # on the map, it is held this long: only a new danger, a picked shelter
                                          # an intruder comes close to, or one that no longer holds them moves it
})

# (R1 g2) the thirst watch's real remedies (brain/planner_thirst.py, lua/ai-thirst.lua)
PART.update({
    "g2_thirst_join_tries": 1,            # no_path: join_levels asked for one dwarf at most this often (37 no-ops in F)
    "g2_thirst_join_noop_days": 7,        # ...and not again this long after one changed nothing
    "g2_thirst_way_tries": 3,             # no_path: thirst_way (the AI's walls, doors, a dig) at most this often a dwarf
    "g2_thirst_way_dig": 30,              # ...rock tiles dug for one dwarf at most
    "g2_thirst_patient_tries": 3,         # a patient: thirst_patient (hospital burrow lifted, carrying counted) this often
    "g2_thirst_probe_tries": 3,           # "unknown": thirst_probe at most this often a dwarf
    "g2_thirst_probe_timer": 35000,       # ...from this thirst (was: said only once dehydrated)
    "g2_thirst_buckets": 3,               # a patient thirsty and no bucket: this many ordered
})

# (r1g9) the keeper and a session's end (brain/session_end.py, brain/revive.py)
PART.update({
    "g9_all_closed_hold_s": 600,          # this folder's game closed with no Dwarf Fortress left on the PC: no relaunch this long
    "g9_signal_hold_s": 3600,             # a console close, logoff or shutdown signal: nothing started or loaded this long
})

# (x3, V7) the fallen mark against the fort now loaded (brain/fallen.py idle)
PART.update({
    "x3_fallen_probe_s": 30,              # while a mark stands: the loaded fort's pulse read again this often (at once on a new date)
})

# (R1 g6) strange moods must not fail for want of materials (R-AD 1-2, R-CE 4)
PART.update({
    "g6_mood_slaughter_again_days": 8,    # a mood still waiting on bone or leather: another animal after this long
    "g6_reserve_bones_min": 2,            # bones under this: one spare animal to the butcher (the ordinary rule)
    "g6_reserve_cut_gems_min": 1,         # a cut gem kept whenever a rough gem lies about
    "g6_mood_trade_goods": 10,            # a no-trade fort: crafts taken to the depot to pay for a mood's goods
})


# (r1g5) the alarm and the squads in a real threat (brain/planner_war_hold.py)
PART.update({
    "r1g5_unfought_alarm_days": 30,       # an AI alarm for enemies no squad goes at: fight or lift after this long
    "r1g5_alarm_hard_days": 60,           # the most such an alarm stands, fight or not
    # (x4) was 0.25 (the enemy four times stronger): the all-out attack goes at the matchup's own
    # sortie bar (planner_matchup.fight_bar: about even, fight_even_ratio, a clear win for a fire
    # breather or unread powers) and never below this; times r1x4_unfought_inside_factor where the enemy is
    # inside the fort near a dwarf
    "r1g5_unfought_fight_ratio": 1.0,
    "r1g5_army_hold_ticks": 2400,         # no trim, swap or off duty this long after an enemy could reach the dwarves
    "r1g5_arm_first_unarmed": 2,          # more unarmed soldiers on duty than this (and a quarter): weapons before drafting
    "r1g5_arm_first_max_days": 56,        # ...held this long at most (gear DF never hands out must not stop the squads)
    "r1g5_swap_armed_share": 0.75,        # no soldier swap while fewer of the soldiers on duty are armed
    "r1g5_recall_hopeless_ratio": 0.25,   # a young kill order is called back for the odds only below this
})

# (r1g8) drink and food in a crisis, and ghosts
PART.update({
    "r1g8_dry_containers_min": 3,         # brewing waits on containers: the least barrels/pots worth ordering from what wood or stone there is
})

# (r1 g3) Water in winter, and wells that count only when they serve
# (brain/planner_wells.py _winter_water_rule, _well_rule; planner_shelter
# _shortfalls; lua/ai-society.lua's shelter water test)
PART.update({
    "g3_civs_per_well": 40,               # a shelter's well gives water to this many civilians (a level's wells weighed)
    "g3_winter_temp_margin": 40,          # autumn, the surface this near freezing (Urist degrees): it will freeze
    "g3_extra_well_slots": 1,             # building slots over max_open another well may take when wells are short
    "g3_winter_well_slots": 2,            # ...a winter water source, in the ice season or with patients waiting
    "winter_water_cooldown_ticks": 3 * 1200,   # the winter water rule asked again at most this often
})


# (x4) the arming hold, the all-out attack and the long alarm's lift (brain/planner_war_hold.py)
PART.update({
    "r1x4_unfought_inside_factor": 0.5,   # the all-out attack's bar times this while the enemy is inside, near a dwarf
    "r1x4_poor_odds_losses": 1,           # a fight begun below even odds: this many soldiers lost ends it (not a third)
    "r1x4_inside_near_tiles": 30,         # inside the fort and this near a dwarf: "among the civilians" (a great danger: the long alarm stays)
    "r1x4_arm_stall_days": 4,             # the AI's weapon orders stood still this long: the arming hold ends
    "r1x4_arm_no_order_days": 4,          # ...or held this long with no weapon order of the AI's and none spare to hand out
})


# (r2 h2) the winter cistern: a well filled by bucket (brain/planner_wells.py
# _winter_water_rule; lua/ai-builder-wells.lua find_filled_well_spot)
PART.update({
    "h2_winter_cistern": True,            # dig one when no water source works in winter (False: never)
    "h2_winter_cistern_half": 1,          # its chamber's half side: 1 = 3x3 (9 tiles), 2 = 5x5 (the bridge's most)
    "h2_winter_cistern_retry_days": 28,   # after a refusal (no spot), asked again this many days later
})


# (r2h6) the dead animals' bodies, the seed reserve, cups and the guildhall
# petitions (brain/planner_farms.py _seed_reserve_rule; lua/ai-util.lua
# fort_remains; lua/ai-bridge-actions.lua act_seed_reserve)
PART.update({
    "h6_seed_reserve": 30,                # a farmable crop under this many seeds keeps its plant and seed from the cooks
    "h6_seed_lift": 60,                   # ...and the ban lifts at this many (the AI's own bans only)
    "h6_seed_plants_max": 8,              # plants banned in one action at most (underground first, fewest seeds first)
    "h6_seed_brew_min": 10,               # an underground crop short of seed with this many plants in store: brew some
    "h6_seed_brew_amount": 10,            # ...an order of this many (brewing gives the seed back; cooking never does)
})


# (r2h4) crossbows: the Bowyer's workshop, crossbows of wood or metal, bolts of wood, bone or metal
# (brain/planner_military.py _ranged_squad_rule, _bowyer_rule; brain/planner_army.py _bolts_rule)
PART.update({
    "h4_bowyer_min_militarism": -100,     # a fort with a squad and Militarism above this gets a Bowyer's workshop
    "h4_ranged_need_days": 4 * 336,       # a fire breather or a flier met: crossbows wanted this long after
    "h4_bone_bolts_keep": 10,             # bone bolts only while this many bones are left (moods, crafts)
    "h4_crossbow_order_max": 5,           # crossbows in one order at most (wood or metal)
})


# (r2 h8) landmarks kept through a slow dig, the season's training need by Militarism
PART.update({
    "h8_landmark_dig_days": 336,          # a landmark's level with nothing dug is given up only after this (not unreached_dig_days)
    "h8_training_need_base": 0.25,        # the season's barracks: the longing to train counts this much at Militarism 0...
    "h8_training_need_per_100": 0.75,     # ...this much more a +100 Militarism (x1.0 at +100, x1.375 at the War-hold's +150)
    "h8_training_need_min": 0.1,          # ...never under this (a Monastery or Garden fort's trainees)
    "h8_training_need_max": 1.5,          # ...nor over this
})


# (r2h7) the rules refused every time: hunts (brain/planner_hunt.py), residency (planner_visitors)
PART.update({
    "r2h7_hunt_hidden_ratio_mult": 1.5,   # a great beast unseen in a cavern is hunted only at this times the hunt ratio
    "r2h7_residency_neutral_days": 14,    # a neutral fort (no stance) declines a petition to stay this many days after it came
})


# (r2 h5) trade: a deal with every caravan (brain/planner_trade.py, lua/ai-trade.lua)
PART.update({
    # bought after what the fort needs, when the merchants have it and the crafts pay: a fort with
    # crafts at the depot sells to every caravan (no deal in about 40 fort-years, 14-16 Nov runs)
    "h5_trade_fallback_wants": {"FOOD": 20, "DRINK": 20, "CLOTH": 10, "SKIN_TANNED": 5, "THREAD": 5,
                                "WOOD": 20, "BAR:IRON": 10, "BAR:COAL": 10},
    "h5_caravan_overstay_days": 7,        # a caravan past its leaving with merchants on the map this long: said
})


# (r2h1) the river: the whole-map survey's slice, and a river-fed cistern
# (lua/ai-water.lua, lua/ai-builder-cistern.lua, brain/planner_wells.py)
PART.update({
    "h1_water_slice_seconds": 0.3,        # a survey slice this long while scanning (0.15 before; the bridge caps it at 0.4)
})


# (r2 h9) population and the world outside: the population cap's hold, the
# migrant drought, a caravan that never left, petitions to stay, the messenger
PART.update({
    # the cap held for strain (planner_growth._pop_cap_rule): F flipped 29 times, E 11 (100 <-> 20)
    "h9_pop_cap_min_hold_days": 28,       # a hold (or its end) stands this long before the cap may go the other way
    "h9_pop_cap_release_days": 14,        # the strain gone this long, without a break, before the hold ends
    "h9_strain_unhappy_max_days": 168,    # unhappiness alone holds newcomers out at most this long (E: 3 years at 20),
                                          # unless beds are short (crowding): then the hold stays
    # no migrants for seasons (brain/planner_outside.py)
    "h9_drought_days": 224,               # no wave this long (two seasons and a half): the drought is reported, its cause
    "h9_drought_cooldown_ticks": 112 * 1200,   # one migrant wave called a season at most (the rule's cooldown)
    "h9_drought_max_calls": 3,            # waves called that brought nobody before the AI stops calling (and says so)
    "h9_wave_min": 2,                     # a rise of this many citizens at once is a migrant wave (one is a birth)
    # a caravan that never left (B, y251-y261: its merchants on the map 10 years, no caravan or migrant since)
    "h9_caravan_stuck_days": 28,          # leaving this long with its merchants still on the map: stuck
    "h9_caravan_free_max": 2,             # tries at sending its merchants off the map before a Needs you
    "h9_caravan_cooldown_ticks": 28 * 1200,   # ...one a month (the rule's cooldown)
    # petitions to stay from a fort between closed and welcoming (A3 finding 3: E 30 waiting, 78 days)
    "h9_residency_neutral_beds": 2,       # spare beds the fort keeps after taking a visitor in
    "h9_residency_neutral_food_pd": 10,   # food and drink a dwarf the fort has before it takes one in
    "h9_residency_neutral_drink_pd": 5,
    "h9_residency_player_days": 28,       # a petition the AI would agree to but can't (DF keeps the visitor a guest):
                                          # left this long for you on DF's petitions screen, then declined
})

# (R2 h3) building slots (brain/planner_slots.py; lua/ai-builder-projects.lua slot_cap,
# need_slot_free, park_project): a level waiting on the same pieces parked, the small
# needs' pool, a dig that never began re-checked
# (r3, 21 Nov: the player's choices "hunting - do as you suggest", "welfare - do what you think is best")
PART.update({
    "r3_hunt_reachable": True,            # a target in reach of the dwarves is the military rules' only when they fight it
    "r3_hunt_lone_beasts": True,          # the one threat in reach the military rules leave (alarm down) may be hunted
    "r3_welfare_burial": True,            # burial waits and memorial slabs follow Welfare (halved at +100)
    "r3_welfare_days_min": 3,             # ...never under this many days
    "r3_welfare_slab_step": 40,           # one more slab order a go for each this much Welfare above 0
    "r3_welfare_grief": True,             # stress care widened after a citizen's death
    "r3_grief_days": 14,                  # ...for this many days
    "r3_grief_welfare_min": 0,            # ...to the very unhappy from this Welfare
    "r3_grief_wide_welfare": 50,          # ...and to the plain unhappy from this Welfare
})

PART.update({
    "h3_park_days": 30,                   # a level being furnished, the same pieces missing this long: parked (holds no slot)
    "h3_park_drop_days": 336,             # ...parked this long on pieces it can't get: they are taken off and the level finished
    "h3_dig_check_days": 21,              # a level with no tile dug this long: why (designations, reach, miners) and unstuck or cancelled
})

# (r3 g3) floors: placement sense and the record (brain/floor_soil.py, brain/planner_floors.py,
# brain/planner_floor_notes.py; lua/ai-builder-floorstore.lua floor_fallback's reason tally)
PART.update({
    "r3g3_soil_skip": True,               # an elevation a floor was refused at for soil or roots is kept and skipped
    "r3g3_soil_days": 14,                 # ...not offered to any level for this many days (unless nothing else is left)
    "r3g3_sacred_roles": ["worship", "crypt"],   # the holy levels (temple, memorial, library, garden; tombs)
    "r3g3_sacred_soil_days": 336,         # ...never on an elevation refused for soil this recently, nor on the survey's soil levels
    "r3g3_sacred_surface_gap": 3,         # ...and at least this many levels under the surface
    "r3g3_sacred_deeper": 4,              # ...the floors taken out made up from at most this many elevations under the band
    "r3g3_journal_floor_hint": True,      # the floor hint actually sent journaled with the start_project action
    "r3g3_floor_reasons": True,           # the FLOORS digest line counts the classic placements by reason
})


# (r3 g1) hallway floors that keep opening (brain/masterplan_floors.py elevs_for, hint;
# lua/ai-builder-floors.lua floor_stairs, floor_search; lua/ai-floorplan.lua dead_floor)
PART.update({
    "r3g1_floor_more_elevs": True,        # the planned floors full or refused: the band's others and deeper ones offered
    "r3g1_floor_open_min": 2,             # ...when fewer than this many of the planned ones are still open
    "r3g1_floor_deeper_max": 12,          # ...down to this many levels under the district's band (the plan's range at most)
    "r3g1_floor_skip_no_hall": True,      # a level no hall can start on (no hall, the hub refused) or refused lately: as full
    "r3g1_floor_stair_tries": 1,          # floors tried on each other stair after the first stair's (0: the first stair's only)
    "r3g1_floor_stairs": True,            # the hint names the plan's other stairwells and the survey's stairs
})


# (r3 g2) floors that fill properly (lua/ai-floorplace.lua spill, need_run; lua/ai-builder-floors.lua; brain/masterplan_floors.py)
PART.update({
    "r3g2_floor_spill": True,             # a floor full by its grammar opens another arm out of the hub before 'no room' (False: the hint says spill = false)
    "r3g2_floor_big": True,               # a level too big for a run: the next of its kind and size asks for a run that holds it, or goes the classic way at once
    "r3g2_floor_big_keep": 40,            # ...sizes remembered (the newest)
})


# (r4 k2, B8) a failing or rate-limited strategist backs off (brain/review.py maybe_review)
PART.update({
    "r4k2_backoff_first_days": 2,         # game days before the first retry after a failed call (doubles each failure)
    "r4k2_backoff_max_days": 28,          # ...never more than this between tries
    "r4k2_backoff_limit_days": 7,         # a rate or usage limit waits at least this long (the plan's window)
})


# (r5 p2) honest numbers in the journal (brain/rests.py, crisis.py, planner_meetings.py, outcomes.idle_free_pct)
PART.update({
    "r5p2_rests": True,                   # a ghost laid to rest is marked `rest` (topic "rest", a death told again): never a death or a ghost risen
    "r5p2_crisis_journal": True,          # crisis mode entered and left: a journal line of its own (kind "crisis")
    "r5p2_meeting_journal": True,         # meetings opened, answered, left, and DF's word the diplomats left: kind "meeting"
    "r5p2_idle_free": True,               # the truly idle non-soldiers' share recorded (timeline, seasons.csv avg_idle_free_pct, metrics)
})


# (r5 p3) repeated refusals backed off (brain/planner_refusal_streak.py): the
# same rule and action refused for the same reason this many times in a row
# waits 1 game day, then 2, 4 ... up to the max; reset by an acceptance, another
# reason, or a change in what the refusal depends on (a new level, a new well)
PART.update({
    "r5p3_refusal_backoff": True,         # the switch (False: only the general back-off of planner_core)
    "r5p3_refusal_streak": 3,             # refusals in a row for the same reason before the wait begins
    "r5p3_refusal_first_days": 1,         # the first wait, game days (doubles each refusal after)
    "r5p3_refusal_wait_max_days": 28,     # ...never more than this
    "r5p3_refusal_forget_days": 336,      # a streak is kept this long after its last refusal (the general one: 60)
    "r5p3_refusal_keep": 30,              # streaks kept at most (the oldest go first; r5 Z2: was 60, past the memory budget)
})
