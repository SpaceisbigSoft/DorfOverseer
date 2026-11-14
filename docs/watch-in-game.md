# Watch in game

What to look for in the six forts after each delivery, kept with the code (moved out of the handoff 8 Nov). Close a line here once it is seen to work, or move it to the Gap Checklist if it fails.

Where to look:
- **state.json**: the live report, `dfhack-config\ai-overseer\state.json` in each game's folder.
- **journal**: `DF-AI-x\logs\forts\<fort>\journal.jsonl`, the AI's actions and their answers.
- **keeper log**: `DF-AI-x\logs\unattended.log`, the overseer's lines, including `Died:` lines and notes.
- **bridge log**: `DF-AI-x\logs\bridge.log`, every call and its JSON answer.

The forts are A War-hold, B Monastery, C Merchant city, D Hermit hold, E Deep mine and F Garden fort. "All" means every fort.


## 0.105.45 (14 Nov): H7, a threat judged against the squads (Phase 11 (a), the judging half)

- **All, state.json**: each `others_on_map.threats` row has `facts: 1` and, as its raws give, `attacks` (`count`, `best`, `syndrome`, `deadly`), `syndrome_attack`, `breath` (e.g. `["fire"]`, `["dust","deadly"]`, `["web"]`), `webs`, `no_pain`, `no_exert`, `no_stun`, `trap_avoid`, `immune_fire`, `regenerates`, `armor`/`armor_kind`, `undead_raiser`, `speed` (1.0 = a dwarf; check a dwarf-sized goblin reads near 1, not 0.1 or 10: `move` is DFHack's raw number), `wounds`, `blood_lost`. No `error` in the section; the report's time for `others_on_map` no worse than before.
- **A forgotten beast or titan on the map**: compare its `breath` and `attacks` with its description in the game (the unit's sheet: "it breathes fire", "beware its deadly dust", "its bite is poisonous"); a generated beast's dust or gas should read `deadly` when DF's description says it kills or rots.
- **All, state.json**: each squad's `power` has `melee_power`, `ranged_power`, `ranged` (shooters with bolts), `coverage` (0-1), `weapons` (by class: steel, iron, bronze...), `wounded`, `tired`; `power` the two summed. A crossbow squad with no bolts in the quivers shows a small `ranged_power`.
- **A great danger in reach**: the note "the squads go (squads X against Y; ...)" or "hide behind the gates (...)" now names the reasons (its breath, venom, armour, "only ranged squads count against its fire", "the squads are mostly melee"). A fire- or deadly-dust-breathing titan against melee squads: hide; an ordinary forgotten beast without breath against squads of ~150: fight. Watch how a fight it called goes (the `fights` in memory) and tune `planner_matchup.py`'s weights from that.
## 0.105.45 (14 Nov): hunting, the Lua side (H1, lua/ai-hunt.lua)

- **All, state.json**: `hunt` with `targets`, `squads`, `hunts`, `history`; no `error`. Each target's `route` (`ok`, `length`, `blocked_by`): a forgotten beast in a cavern the AI sealed reads `seal`; a goblin at the gate with the gates open reads `none`; one outside with an AI gate shut reads `gate`. `layer` is layer_at's name (`upper_levels`, `Cavern1`...); `region` is `surface` / `cavern` / `inside`.
- **Never in `targets`**: merchants, diplomats, pets and tame animals, citizens and residents, caged beasts, or an unhurt visitor. A beaten visitor DF shows interrupting the dwarves appears with `wounded_visitor: true`.
- **`squads`**: `power` / `armed` / `armored` as in `military.squads[].power`; `ranged` true only for a crossbow squad whose soldiers carry bolts; `at_home` false while a kill order stands or most soldiers are outside or in a cavern; `sheltering` as the military section says.
- **A `hunt_send` in the journal**: the squads' kill order in the squad screen (title "AI overseer"), `ai-overseer/hunts` in the save's site data, `hunt.hunts` with `soldiers_now` / `wounded` changing as they fight. A squad on the player's own orders, or with fewer than 2 armed, is refused.
- **The target killed / gone**: the next full report moves the hunt to `hunt.history` with `won` (and `soldiers_lost`) or `gone`; a kill order another rule cleared shows `dropped`. A `hunt_recall` clears the AI's orders (the soldiers walk back to their barracks) and adds `recalled` with its reason.
- **Cost**: the `hunt` section's ms in `perf` (one pass over the units; it is not in the pulse).
## 0.105.45 (14 Nov): hunting (H2, brain/planner_hunt.py; the bridge's `hunt` section is H1's)

- **All, Rules tab (Military page)**: "Hunt threats:" at the right of "Send missions by the World screen", cycling off / thieves, ambushes / AI decides (beasts too); default AI decides; the setting kept after reopening the window.
- **A thief, an ambush near workers, or the wounded visitor that interrupts the dwarves** (not yet in reach of the dwarves): a `hunt_send` journal line ("hunt ...: send <squads> (N soldiers, strength X against Y: Rx, 3x needed); M soldier(s) stay home"); at least 3 soldiers (a third of all) and, with 2+ squads, one whole squad stay home; the squad walks out and the target dies; then a "hunt learned: a won hunt ..." note and `fight_factor` for that kind lower in the memory.
- **A forgotten beast in an unsealed cavern, a titan on the surface** (A War-hold first): hunted only with a party clearly stronger, one at a time; a fire breather or a flier only with a squad of crossbows (else the note "it breathes fire and no free squad of crossbows can go"). A beast behind the AI's cavern seal: the note "behind the AI's cavern seal; left to the lure and cut-off rules".
- **A hunt going badly**: a `hunt_recall` line ("a third of the soldiers lost", "half wounded", "over 3 days") and the squad home; that target then noted "called off; not hunted again while it is here", and the kind's `fight_factor` 1.5x.
- **Never**: a `hunt_send` during a siege, with the alarm up, in a crisis, or while a great danger's fight is on; a siege arriving calls the hunters home ("the hunters come home").
## 0.105.45 (H6): the sweep for things stuck "in progress" (Phase 11 (d))

- **All, state.json**: the `stuck` section (`list`, `total`, `tick`, no `errors`): the AI's own things not yet final, oldest first, each with `kind` (project, cistern, waterwork, lever, squad, order, gate), `state`, `since`, `moved`, `age_days`, `still_days`, and its evidence (`progress`, `job`, `worker`, `pulls`, `live`/`dead`/`gone`/`caged`, `pieces`). The player's levers (a plain "AI gate"), orders and squads' own orders never listed. The save gains `ai-overseer/stuck` (written only when something changed).
- **Notes**: "stuck: <thing> hasn't moved in N days: ..." one line a thing past its timeout (levels 84 days, cistern and water works 84, a lever's pull 2, a dead kill order 1, an AI work order 56, a planned gate 42), saying nudged / given up / retired / left to its own rule. Not every cycle a new action: nudge first, the retire 1-14 days later, then 112 days left alone.
- **Journal, `stuck_sweep`**: `stuck_reset` (reissue, then drop) on an AI lever whose pull job nobody took (the cavern well's shaft lever, the cistern's, the gate lever); `squad_orders clear` for a kill order on targets dead, gone or caged while other threats keep the squads out; `cancel_work_order` with `stuck` for an AI order that sat 56 days; `free_dig_jobs` / `prioritize_dig` then `cancel_project` for a level dug part way and stalled for months; `finish_project stalled` for one furnishing for ever; `cistern_step retire` / `water_work retire` for a step that never moved. Never beside the same thing's own rule in a cycle (dig_jobs, gate_stuck, way_in, gate_jobs, squad_recall, stuck_order, the cistern's own retire).
- **stuck_reset in game**: the PullLever job gone from the lever (the building's job list), a fresh one posted on reissue (`lever pull --id`), none on drop; the pull then asked again by its own rule if still wanted.
- **health_check.txt**: a `stuck:` part, "stuck: N thing(s) past their timeout (kinds)", flagged only when some stay past it over 12 soak rows; the soak rows carry `stuck` {past, kinds}.
## 0.105.45 (14 Nov): kill zones at the gates and cavern openings (Phase 11 b)

- **All, state.json**: `killzones.entrances` (per entrance: `state` possible / none with `why` / building / standing / gatehouse, `corridor` length, `drawbridge` possible and `channel`, `fortifications`), `killzones.threats` with `trapavoid` for each enemy, `free_mechanisms`, `trap_weapons`, `mechanics`. No `error`. Is a `possible` stretch really a 1-wide way every enemy must walk (look at it on the map)?
- **A fort where enemies came through an entrance (the atlas' threats there), A War-hold, D Hermit hold**: a `build_killzone` journal line; cage traps (`Tc`) in the narrow way in, never on the first tile behind the gate; a drawbridge named "AI killzone bridge" and an "AI gate lever" where the dwarves are; the gate rule (or the zone's own rule) links the lever to it.
- **The founding stair's only way in**: no channel dug there (the bridge stands flat, lowered); citizens walk in and out over it the whole time.
- **A second way in, rock below**: a channel dug under the bridge's tile, then its ramp removed (`z`), then the bridge placed over the pit, one step a day; never over water, an aquifer, a cavern or a fort level below.
- **TRAPAVOID**: a titan or forgotten beast at a gate shows `trapavoid` true or false in `killzones.threats`; when true the note says the traps never touch it and the zone gets only the drawbridge. Does a cage trap catch a goblin (and the full cage get hauled to an animal stockpile by DF itself, the trap loaded again)?
- **Weapon traps (Fortification 80+)**: a `metal_trap_blades` order at the forge is accepted by DF (MakeTrapComponent, ITEM_TRAPCOMP_GIANTAXEBLADE) and the `Tw` traps get their blades.
- **Army tab**: the switch **Kill zones at the gates** (on), in the right-hand column beside the missions row.
## 0.105.45 (H4): a sealed cavern beast lured in and cut off

- **All, state.json**: `lures` (each pulse): `beasts` (each great danger with `immune` read from its caste's TRAPAVOID: **check it reads true/false, not missing**, for a forgotten beast and for a titan or megabeast if one comes), `candidates` (the AI's cavern doors with `fits` or the `why` not), `lures` (per pocket: `phase`, `traps_built`, `traps_loaded`, `traps_full`, `inner`/`mouth` `built`/`shut`/`linked`, `seal.locked`, `citizens_near`), `cavern_citizens`, `mechanisms`. No `error`.
- **A forgotten beast sealed 7+ days** (`threats.sealed["all caverns"].days`): `build_lure` in the journal; the pieces planned behind the cavern door: cage traps on the 1-wide way (3-6 tiles) and a door named "AI lure gate" where it ends (or two drawbridges and two levers named "AI lure lever" for a trap-immune beast, the links made once built). Nothing on a room, a workshop's floor or the depot's road.
- **Cage traps**: whether DF loads an empty cage into each (`traps_loaded`) or needs none (the AI opens on `built` alone): say which.
- **Ready**: `lure_shut` locks the inner door (raises the bridges) first; then `lure_open` only with nobody in the caverns and nobody in or beside the pocket (a refusal says why); the cavern door unlocked, `threats.openings.list[].lure_open` true, and **no `seal_cavern` re-lock of it** while open; the gate watcher not closing that entrance.
- **Open**: the beast walks in? caught in a cage (`phase` caught, then `lure_shut` and `done.how` "caught"; the cage stays where it is: watch that nothing pits or frees it), or for a trap-immune one the mouth raised behind it (`shut_in`, `held_beasts`, the caverns' seal opened again by planner_threats). Nothing within 3 days: `lure_shut` with "try N", opened again after 4, 8, 16... days.
- **Risks to watch**: a building destroyer bashing the locked inner door (a cage-trap pocket has a door there); the gates scan taking the lure's door or bridges as the cavern entrance's gates (renamed "AI gate N"?); the alarm/military rules reacting to a beast shut in the pocket; DF's pathing ignoring the open door (the beast never comes).

## 0.105.46 (I2): the thirst watch (186 dead of thirst in the 8-13 Nov run)

- **All, state.json**: `thirst` (in the pulse) with `thirsty`, `dehydrated`, `list` (each: `timer`, `group`, `reason`, `drink_group`, `forbidden_group`, `wells_group`, `water_group`, `drink_elsewhere`, `burrows`, `alert`, `jailed`, `insane`, `mood`, `stranded`, `cancel` {why, by, n}, `job`), `deaths`; no `{"error"}`. Check the fields DF names otherwise: `unit.burrows`, `alerts.list[..].burrows`, `buildings.other.ZONE_WATER_SOURCE`, `job_type` "Drink" on a dwarf drinking, `dfhack.burrows.isAssignedTile`. The bridge log's `ms` for `thirst` small with nobody thirsty.
- **The cancel match**: a dwarf whose gamelog shows "X cancels Drink: ..." gets that `cancel.why` in the row (the name in DF's report matched to the dwarf; nicknames and the profession left out). If `cancel` is always missing while the gamelog has such lines, the names don't match.
- **Reasons that look wrong**: many `no_path` dwarves standing beside barrels (the walk group read at the item's tile vs the dwarf's), `unknown` for a dwarf in a cut-off room, `burrow` for a dwarf whose burrow DF doesn't restrict.
- **Remedies in the journal** (rule `thirst`): `thirst_unforbid` (the drink near them unforbidden, never with the gates armed or near an enemy), `release_prisoners` with one id, `refresh_shelter` with the alarm on, `join_levels`; each at most every half day per dwarf; none of them doubling a `prisoners_water`, `gate_stuck`/`stranded`/`way_in` or `squad_attack` of the same cycle. Notes "<name> thirsty (..) at x y z: <reason>; <remedy>".
- **Every death of thirst**: a note and a journal line `thirst_death` with place, `reason` and the last cancelled Drink. The exit: no thirst death in a two-year run in any fort; any that come, their `reason` says which remedy failed.

## item1 (14 Nov): the thirst trap (B, 13 Nov: 66 dead of thirst beside 845 drinks)

- **All, state.json**: `threats.interrupters` (`cancels`, `by_who`, `reasons.drink` / `reasons.eat`, and `list` with each unit DF shows keeping the dwarves from drink, food or sleep: `who`, `near`, `visitor`, `merchant`, `kill_ok`). Normally empty or small; no `error`.
- **A visitor or other non-citizen that DF says interrupts the dwarves** ("cancels Drink: Interrupted by a ..." in the gamelog, again and again): a `squad_attack` journal line naming it ("keeps the dwarves from their drink and food"), `squad_orders` accepted by the bridge (not "none of those units is a threat"), the squad not recalled for "no more threats" while it lives, and the Drink cancellations stopping. Never a merchant or diplomat (a note instead).
- **Parched dwarves**: a note "N parched, M starving; in the last 2 days Drink jobs dropped: ..." naming DF's reasons.

## 0.105.39 (12 Nov): missions (13b)

- **All**: the Army tab's new rows, **Missions to send out** (*rescue and recover* by default) and **Send missions by the World screen** (off), under the caverns' switch and clear of the help text; an old save reading those defaults.
- **All, state.json**: `missions.targets` (best first: goal, site, distance, why, the citizen or artifact); only goals the `missions` switch allows proposed; raids and the rest only at *all* and only against hostile or at-war civilisations.
- **With `send_missions` off (the default)**: a note naming the target and the squads, and Needs you saying what to send; the reserve kept home (at least 3, more at low Militarism); nothing while a threat is near, during a siege, or while another mission is out.
- **Record the buttons first, once**: send one mission by hand (rescue, recover an artifact or explore, as the fort has one) while `python brain\probe_missions.py --watch` runs (`--watch 300` for 5 minutes): open the World screen, pick the site, the goal, the squads and confirm. Then show the AI each button with the mouse on it and `python brain\probe_missions.py --here <Name>` (the goal's button on the New mission screen; the names `missions.send.goals` lists). `missions.send.goals.<goal>.button` should then be true.
- **With `send_missions` on**: `send_mission` in the journal with its goal, site and squads; `missions.send` and `dfhack-config\ai-overseer\mission-send.json`; the run stopping at the first unrecorded step with what it saw, the World screen shut after, and that goal not tried again for a year.
- **A mission back**: the journal line and chronicle entry from the game's report and spoils (quoted, cut short); memory `missions_sent`, `missions_back`, `rescued`, `artifacts_recovered`.

## 0.105.33 (11 Nov): the audit's fixes and the slider changes

- **All**: `python brain\selftest.py`; the first report of each fort for `{"error"}` sections; the window's new **Army** tab (military, junk, prisoners) and the Rules tab fitting.
- **All, thirst**: the recreation burrow letting out the thirsty (journal `recreation` with `release`), the shelter holding its well, a refused well retried after 28 days, a drink-short plot swapped to a brewable crop.
- **All, sliders**: `dwarves.idle_free` and `projects.done_total` in state.json; polishing going on past 20 finished levels; the stone list (`stone_types`) no longer empty; Greed forts keeping cut gems; War-hold and Hermit hold digging a second stairwell; `python brain\scorecard.py --every 2y` with the new lines.
- **Forts of 30+ with one way in**: a `way_in` project with `second: true` dug 15-40 tiles from the entrance, then seen by the gate scan as an entrance and fortified; never for the Hermit hold unless citizens were stranded.
- **Unattended**: revive at the title with a failed load counts it and restores a backup (`<copy>.fort.json` beside each copy); a cycle whose date failed says so and does nothing else.
- **Moods**: no glass counted from plain rough gems; the hospital's thread and cloth not counted for moods; a mood stalled 7 days on an "on hand" item made anyway.

## 0.105.32 (11 Nov): an open gate the game holds shut

First on E's own save (8 Nov 17:05, 23 stranded at the founding hatch), then on all six.
- **state.json** `entrances.entrances[].split` on E's hatch 7 (x108 y149 z171): `outside_group` / `inside_group` differ, and `flags`, `tiles` (above, at, below) and `link`. **Record them**: they say why DF holds it shut (a flag such as `forbidden` or `operated_by_mechanisms`, the half-done link, or a stale walk map). Does `pairs(door_flags)` list the flags on 53.16-r3?
- **journal** `unstick_gate` step 1 in the first cycle on E; its `split_after`. If still split, step 2 six game hours later, then step 3 (the hatch deconstructed). Which step joins the groups? Does `world.reindex_pathfinding` exist (step 1's `done` says)?
- **state.json** stranded rows with `cause: "gate_stuck"` and `stuck_gate: 7`, then the stranded coming in and drinking.
- **journal** after step 3, if the dwarves are still out: `dig_way_in` (a `way_in` project, its column and tunnel); do DF and Quickfort take the `u1`/`i1`/`j1` designations; does the next gate scan list it as a surface entrance; is it finished once dug.
- **All**: no `split` on a hatch that is really shut, a locked door or a raised bridge; no `dig_way_in` for a lone dwarf on a ledge before 3 days, and none after 3 refusals.
- **All**: in a siege or with the watcher armed, steps 2-3 and `dig_way_in` held (a note says why).

## 0.105.22 to 0.105.26

Suggested placement: in "Starting the next step", in place of the current "then watch:" bullets. It covers them and the three versions before.

**First start (0.105.25 split, all).** In each game, `ai-bridge version` should answer with the delivered `BRIDGE_VERSION` and no load error. The self-test should pass. In the first full report (state.json), no section should hold `{"error": ...}`. Look especially at sections served by the split parts: `ai-bridge-report/-actions/-orders/-probes`, `ai-builder-*`, `ai-military-gear`, `ai-society-burrows` and `ai-util`. A part that fails to load names itself in the keeper log. Also check:
- that `touch lua/*.lua` ran in every folder, or the game keeps the old hub;
- that a hand-run `overseer.py --autopilot` beside a keeper refuses (`logs\keeper.lock`).

**0.105.22: the 3-5 Nov deaths**
- **Shelter (B most, all).** A squad on the shelter order comes off it after `shelter_max_days` (3) and stays off for `shelter_rest_days` (2). Look in the journal for squad orders, and in memory for `shelter_since` and `shelter_rest`. No soldier should appear in the keeper log's `Died:` lines with thirst as the cause.
- **Hospital burrow (A, B, E).** In state.json's `society.hospital_burrow`, members past thirst 25000 or hunger 50000 are let out, and no such dwarf is moved in. Bedridden patients are kept in only where the burrow has a well (`drink` reads `well`).
- **Fight or hide (A: titans).** Once a third of the soldiers sent are lost, the fight is called off at once, noted in the keeper log and journal. The threat's kind then counts 1.5x, once (`learned`). A great danger at ability 3 or more is hidden from, not fought.
- **Ghosts (B, C, F).** No `stone_slab` or `stone_coffin` order is cancelled as stuck while ghosts walk or bodies wait. While the fort is haunted, one waiting MASON, DETAIL or STONE_CRAFT job gets a worker.
- **Unreached levels (all).** A level with nothing dug for 56 days (`unreached_dig_days`) is cancelled with `unreached: true` in the journal. No new level is placed in its area for 5 years (`UNREACHED_YEARS`).

**0.105.23: 14.1 step 4 and the shelter**
- **Shelter away from open entrances (A first).** In the bridge log, the `civ_alert` (`setup_shelter`/`refresh_shelter`) result should carry `excluded_tiles`, `excluded_why` and `open_entrances`. A `fallback` or `taken_back` note means the shelter was small, so less was left out.
- **4a: the hatch lever and the gatehouse (A, D).**
  - The founding hatch gets a lever (`hatch_levers` on). The gate watcher drives it by `lever pull --instant`; `open_lever_hatches` reopens a hatch the link shut. The hatch should be open in quiet times, shut only when danger is near.
  - The gatehouse is built at Fortification 80+: A at 120, D at 100. Look for `build_gatehouse` in the journal, then "AI gatehouse bridge" in game: a walled corridor of 2-4 traps in front of the hatch. The gate scan should report the bridge as the entrance's outer gate. Expect the scorecard's Fortification and Engineering lines to move for A and D.
- **4b: the Monastery (B).**
  - Farms get +50% (`thirsty_farm_extra`) while drink is under its target.
  - Brewing takes the larger brewable source, fruit first.
  - A temple per god that 5+ citizens pray to (state.json `needs.worship`), then a grand temple at Piety 120+.
  - A shrine may take the character slot before food and drink are met (`piety_slot`).
  - Fort E's temple with no size: no more refusals of `start_project` "temple".
- **4c: the Garden fort and the Deep mine (F, E).**
  - F's keep: `place_keep` finds a court (`find_keep_court`) instead of "no ring of open ground around the way in".
  - E: nothing above the surface (`max_elev` on every new level), and the trade depot underground. Look at state.json `buildings.deep_depot`: its `stage`, `tiles_left`, `stalled`, `depot` and `wagon_access`. When the game says wagons can't reach it, a Needs you line appears. With no road found, `no_road` and a surface depot.

**0.105.24: items 6-11**
- **Cavern well (C, F).**
  - Old projects #110 and #114 are taken up again (`revive_cavern_well`), and a landing is dug beside the shaft top (`well_landing`, `well_floor_beside`).
  - If quickfort refuses the well, the project holds `well_refused` and `well_diag` with tile names. It is retried and given up after 3 refusals.
  - Then the hospital burrow's `drink` should read `well`.
- **Squads (all).**
  - A recall, gate hold or shelter clears the AI's order off each soldier's own list. The `squad_order` recall result says `member_orders` (does DF copy orders onto soldiers?).
  - A squad with a soldier at thirst 25000 or hunger 50000 (`parched` in the military report's squads) is never sheltered, and is let out at once.
  - In DF's squad screen, sheltered squads carry water and food.
- **Moods (all; B and E for drink variety).**
  - In state.json's moods, `missing[i].avail` is filled per request, and cloth reads "1 cloth" (not 10000).
  - Journal results to read: `mood_free_items`, and the orders `tan_hide`, `raw_green_glass`, `smelt_ore`, weave, cut, blocks and one animal butchered. Two job names and DFHack's `isSuitableItem`/`isSuitableMaterial` are unverified. A wrong name is refused and the old behaviour comes back.
  - The failed share of moods should fall from 45%. A Needs you line names a material the fort can't supply.
  - Keeper log: a "calm burrows retired" note once 90% of 40+ tantrum sightings are outside the burrow. The 2-5 Nov logs had 344 of 349 outside.
  - SameBooze stress shrinking (`_booze_variety_rule`: a fruit brew, a second brewable crop; supplies `drink_kinds`).
- **Visitors (all; B and F for meetings, C never).**
  - After a heist or a visitor's killing, the tavern, temples, library and guildhalls are shut to visitors for `heist_lockout_days` (168). Look for `location_access` in the journal, and for `killer_visitor` or `killer_dead` on the `Died:` lines.
  - With 5+ citizens unable to complain and at least 3 meetings that are half or more with visitors, the same locations shut for 56 days (`visitor_shut`). This never happens at Outsiders 100+, and the Merchant city preset has it off.
  - "Unable to complain" in `needs.stress_causes` should fall. The bridge counts every non-citizen, residents too, as a visitor in meetings.
  - An unattended meeting screen is left after 2 minutes.
  - Citizenship petitions show as Needs you with counts.
  - The two new Rules toggles (`heist_lockout`, `shut_to_visitors`) should sit in the right-hand column without overlap.
- **Messenger (any fort with `send_messenger` switched on; off by default).**
  - `send_mission` in the journal; `missions.send` in state.json; and `dfhack-config\ai-overseer\mission-send.json`.
  - The run should stop at step 4 of 6 (Make contact, the messenger and the confirm were never recorded), and the World screen should be shut after.
  - Record the later steps first with `probe_missions.py --here World|Diplomacy` and `--watch`.
- **Phase 12 leftovers (C, D, E; F for quivers).**
  - Library: a dwarf takes the quire or parchment job (`_labor_waiting_rule`: 1 waiting job when nobody outside the squads holds the labour), and quires reach the library.
  - Traction: state.json `infection.traction` lists patients and free benches. `traction_rest` lifts a patient onto a free bench after 7 days' wait.
  - Quarry counts stay at 30 or less: no "quarry needs count 1-30" refusal.
  - A stone door cancelled as stuck is ordered in wood next (`stuck_fallback`).
  - Crossbow and quiver orders done 4 times for the same reason are held 56 days (memory `no_effect`). Still unexplained: where C's 962 crossbows went, and why the game takes a handed-out quiver back.

**0.105.25: Phase 13c (meant to change nothing the forts do)**
- **Searches cut short (all; E and F for the outdoor farm).** Farm, well, cistern, pasture, sand and surface searches that hit their time limit answer `timed_out` with "search cut short", not "nothing found". From 0.105.26 the brain retries them in 1-2 days, the long back-off only after 3 in a row.
- **Speed (all).** Full report time `_timing` in the bridge log should be the same or lower: boulders, caverns, pastures and gate floods are walked once. FPS should be the same.
- **Dry runs while halted.** With Ctrl-Shift-H on, dry runs of the actions in `DRY_OK` go through (0.105.26: about 90, and a dry run of anything else is refused with "has no dry run" in the bridge log). `tidy` is gone in 0.105.26.
- **No new `water-map.txt`** in `dfhack-config\ai-overseer` (the weekly probe is gone).
- **Window.** The six actions that had no panel words now show them, and the slider says "Outsiders", not "Hostility".

**0.105.26: the fix round (eight groups)**
- **First start (all).** `python brain\selftest.py` passes "every Lua module and part loads" and "every part is from this version" (the bridge's new `modules` command; `ai-bridge version` lists `stale_parts`, which should be empty). Per-command time in the bridge log drops (parts no longer compiled every call). No "has no dry run" refusals of the overseer's own dry runs.
- **Titans and great beasts (A first).** A fight called off: every squad with the danger in its kill list gets `squad_recall`, memory `called_off` holds the enemy until it leaves or dies, no squad sent at it meanwhile, the learned factor jumps (A's titan: 6.75, not 1.5). The Rules tab's "attack everything" still overrides.
- **Shelter (all; B, E).** The alarm's `civ_alert` result has `drink_tiles`/`well_tiles` > 0 (or `drink_back` when they were taken back; `no_water` if none). Lever hatches count as shut; a destroyer on the map marks gates open; `military.shelter_stale` > 0 during an alarm proposes `refresh_shelter`. E: `deep_depot_tiles` left out. Sheltered squads stay in while a great danger or siege is within 20 tiles (`shelter_hold_tiles`).
- **Water for soldiers (all).** `military.gear.flask_places`/`flasks_assigned`/`flasks_free`; leather waterskin (or green-glass vial) orders for the shortfall; check `pos.equipment.flask` holds an item.
- **Visitors (B, C, F).** After a `location_access` shut the next report's `locations` shows the places shut (cache cleared; `locations.built`), and they reopen when the window ends (no longer filed under `locations_yours`). C's heist lockout 28 days. The swamped-mayor shut repeats only on new complaints; `meetings.requests_residents` and `activities[].resident` mark residents (check `isResident` tells residents from performers).
- **Moods (all).** `tan_hide` runs as the `TAN_A_HIDE` reaction at the tanner's; a mood's orders never held; while a mood waits, other orders of its material are dropped (an iron-bar mood holds iron weapon orders too).
- **Holds and loops (all).** A timed-out search retried in 1-2 days, back-off from the 3rd; one fruit brew, not two; a stuck brew waits 5 days (none when urgent); `needs_drink` gone; the prison room's 7-day cooldown; `unreached` only when nothing was dug, and B's unreachable stair column dropped at every level (check `getWalkableGroup` on stairs); ghost slabs that can't be made: a Needs you saying why.
- **Stranded outside (any; E's case).** `entrances.stranded` rows (cause `lockdown`/`gate_shut`/`no_path`, `in_cavern`); after about 4 game hours an AI-shut gate is opened (`open_gates`) when no enemy is within 30 tiles, otherwise a Needs you. Watch the gate watcher doesn't re-close at once.
- **Cavern openings (C, F, E).** `threats.openings` lists cavern entrances, well shaft hatches and doors (capped 60); a cavern entrance gets doors at once (`cavern_openings`); a forgotten beast or other great danger in the caverns seals every opening ("all caverns", announced), the cavern well's shaft hatch shut too (the brain says the well is dry; Needs you if injured wait on it); never with citizens below; reopened once it's gone. Whether a locked door or hatch really keeps a forgotten beast out is the open question.
- **Strategist (`--ai`, when tried).** The first live review returns JSON; life-saving rules can't be held; the shown rules can be steered; the API backend uses adaptive thinking on 4.6+ models (the subscription backend unchanged).
- **Scorecard (the exit test).** `keeper-preset.json` entries carry a `"run"` stamp after the fresh start, unchanged by a revive; each kept state starts with `"_run"`; `python brain\scorecard.py --every 2y` writes `logs\scorecards\<season>.md` and `summary.md`, with no "older run left out" notes.

**0.105.27: disposal of forbidden clutter (all six)**
- The census's `items.forbidden` in memory: counts by reason and place; `dead.standing` lists the standing orders with real 0/1 values.
- The journal shows `set_standing_orders` (gather_refuse on), then `unforbid_items` batches (used ammo, dead enemies' things, dead citizens' things once all are buried), `mark_melt` with a melt work order when a smelter stands, `place_dump` (inside for D, the Hermit hold), `mark_dump`, and `empty_dump` once a dump holds 150+.
- Lock symbols on the map should thin out over a few game months; nothing near enemies or in a siege is touched; no citizen's body vanishes; picks and axes stay.
- The Rules tab's "Forbidden items and junk" block fits the window (Dispose / Yours too / Keep enemy gear).
- A Needs you appears if 200+ locked items match no game reason (maybe yours).

**0.105.29: fort customs (two per preset, new levels only)**
- **All.** New `start_project` lines in the journal carry `"customs"` only in the fort whose preset owns them (none at default sliders), and the scorecard's six custom lines (Piety "cloister temples and cells" ... Agriculture "halls and kitchens by the fields") are won by their own fort. Levels already dug are not changed.
- **B Monastery.** A new temple has a ring of rock pillars 1 tile in from its walls, the doorway row and statue column clear (`cloister`). New bedroom levels go to the halls district beside the temple, and the homes district does not grow from "misses" (memory: homes `missed` stays low).
- **C Merchant city.** New levels' approach corridors are 3 wide (`wide_ways`). The tavern level sits 1-3 levels under the way in (`market_gate`).
- **D Hermit hold.** Approach corridors 1 wide with a dog-leg while the fort has 80 citizens or fewer, 2 wide again above that (`winding_ways`). No new level at or above the surface; new `start_project` actions carry `max_elev` and `hidden_hold` (`levels_up` stays flat).
- **A War-hold.** New barracks and archery levels 1-3 levels under the hatch, on the side facing the way in (`gate_barracks`). Barracks have an alcove past the racks with a weapon and an armour pile (`armoury`; layout summary `armoury = true`).
- **E Deep mine.** A new dining level in the forge (industry) band (`deep_hall`). Workshop levels get one 5x5 stone stockpile room (`ore_piles`; check stone is hauled there and stone tidiness does not fight it).
- **F Garden fort.** A new dining level and food-only workshop levels (still, kitchen, farmer's, quern, millstone, butcher's, fishery) on the farm level (`field_hall`, `field_kitchens`); a mixed workshop level goes where it always did.

**0.105.30: construction (the keeper builds, not only digs)**
- **Check first (the spec's [verify] points; any fort).**
  - Quickfort takes `Cu`, `Cd`, `y` and `CF`: a dry run of `place_hall` should not list them in `invalid_keys` (bridge log). A key refused there only drops that piece (window, stair).
  - The roof at z+1 over a walled court or hall: built from below, or suspended as inaccessible? Look at state.json `planned` (suspendmanager's reason) and the `roof_planned` count in `buildings.keep` / `buildings.halls`. If it stays stuck, the corner stair (`ROOF_STAIR`) must be on.
  - A built wall makes a walkable floor on the tile above (wall top).
  - buildingplan's per-building item filter: the bridge log says whether "blocks only" was set or the build fell back to any material.
  - `df.global.world.constructions` exists with `item_type` and `flags.top_of_wall`: state.json `constructions` has a `total` and no `{"error": ...}`.
  - `BUILD_CONSTRUCTION` reaches enough dwarves: waiting construction jobs in `labor` get hands.
  - A roofed hall reads `outside = false`, `subterranean = false`, and the alarm's `civ_alert` result shows `surface_out` > 0 (those tiles left out of the shelter).
  - FPS with about 100 planned tiles waiting.
- **Digest (all).** The keeper's digest has a `BUILT ... walls, ... floors (..% blocks), .. above ground` line once anything is built; the block share should rise as `stone_blocks` orders from the construction rule come through.
- **F Garden fort.** `place_hall` with `field_hall` in the journal, by the surface fields; stage by stage to `done`, then a dining zone over it. Soil floors (`floor_rooms`) in the farm-level dining hall. F's keep refusals (133 last run) should not hold the hall back once 3 have failed.
- **C Merchant city.** `place_hall` with `market_hall`, 6-15 tiles from the depot and not on the wagon road: wagons still reach the depot (`trade.depot`, no "wagons can't reach" Needs you). Its first building above ground.
- **A War-hold.** `build_wings` after the gatehouse stands: two arms of up to 5 walls, no new entrance appearing in `entrances` (no courtyard), and the gate's `pieces` list holds them.
- **D Hermit hold.** Small cavern openings walled (`sealed`), never with a citizen beyond or with a cavern well on that layer; nothing new above ground (`built_up` flat).
- **E Deep mine.** Nothing new above ground; only blocks orders may change.
- **B Monastery.** Nothing new built at its sliders except soil floors if a finished hall sits on soil.
- **Scorecard (all).** The six new lines (Surface "constructed tiles above ground" and "roofed surface tiles", Fortification "gate walls and wings" and "cavern openings walled", Craftsmanship "constructions of blocks, %", Grandeur "soil floors finished") read numbers, not "no data", and are won by F/C, A, D and C/B as the table in building.md says.

**0.105.45 (H5): the shelter away from the threat, the squads between (Phase 11 brief (c))**
- **A great danger or siege on the map (any fort; F's hill titan case).** state.json `shelter_plan` has `danger: true`, each danger's `way_in` (an entrance id), `candidates` (levels with `d_threat`, `civ_p90`, `civ_late`, `drink`, `wells`, `chokes`) and `current` once a pick is made. The bridge log's `ms` for `shelter_plan` (pulse) stays small with no danger and bearable with one (the walk is redone at most every half day, or when the ways in or the pick change).
- **The pick.** The journal shows `shelter_pick` with `levels` and a reason naming the way in ("the surface at x.. y.. z.."); the AI shelter burrow (DF's burrow screen) covers only those levels, and they hold drink or a well. With the alarm up, the civilians walk there, not towards the gate. A player's own alert burrow is never touched (a note says so).
- **Rule 3.** A titan or forgotten beast that gets inside and comes within 20 steps (walk) of the shelter: `shelter_flee` at once, a note "the shelter moved: ...", the civilians walk to the other level. Watch that they don't have to pass the beast to get there (the pick never takes a level the beast reaches before them, but look).
- **Squads.** While the dwarves hide, `shelter_squads` carries `station` x/y/z: the squads stand on a corridor or stair tile just inside the gate the threat faces (DF's squad screen: a Station order), not in the shelter burrow; with no choke, at a barracks off the shelter's levels; with neither, a squad in the shelter is called out and a note says so. Check the move order really holds them there (`squad_order_movest`, `pos`) and that they come back when the alarm is over (`squad_recall`).
- **After.** The danger gone and the alarm down: `shelter_pick` with `clear` (the whole fort again). The Rules tab's switch now reads "When hiding, squads guard the way in".
