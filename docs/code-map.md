# Code map: what each file does

Moved out of the handoff at 0.105.64 (its "How it fits together" table). Add a row when a file or family is added.

| File | Job |
| --- | --- |
| `lua/ai-bridge.lua` | (0.105.25: the hub) commands, `BRIDGE_VERSION`, `ACTIONS`, `DRY_OK`, `SECTIONS`, the section cache; loads its parts into its own environment; `version`, `modules` |
| `lua/ai-bridge-report.lua`, `-actions`, `-orders`, `-probes` | the report's readers and event feed; action handlers; work orders, recipes, tools; probes and screen recording |
| `lua/ai-builder.lua` + its parts (`PARTS`, 27 at 0.105.64): `ai-builder-sites`, `-projects` (+ `-progress`, `-finish`, `-founding`, `-wayin`, `-polish`), `-farms`, `-wells` (+ `-shaft`, `-watch`, `-place`), `-cistern` (+ `-status`, `-step`), `-surface`, `-keep`, `-deepdepot`, `-wagonroad`, `-dump`, `-rooms`, `-halls`, `-landmarks`, `-court`, `-floorstore`, `-floorpiles`, `-floors` | a 30 KB hub and its parts: where a level goes; the project lifecycle (progress, finishing, founding and cancelling, the way in, polish); farms, water and sand zones, pastures; wells; the cistern; the surface crossings, the keep, the deep depot, the wagon road, the dump; rooms, feeder piles, slabs; the surface halls; the Design track's landmarks; the garden court; the hallway-first floors |
| `lua/ai-util.lua` | shared helpers: `fort_entity`, `abs_tick`, `site_get`/`site_put`, the one item-free check |
| `lua/ai-military-gear.lua` (a hub since r9: parts `-why`, `-ammo`, `-fixes`, `-kit`), `ai-society-burrows.lua` (r9: a hub, its parts `-hospital`, `-calm`, `-weather`) | the gear half of ai-military; the recreation, hospital and calm burrows and the weather keep-in (the old modules forward every name) |
| `lua/ai-moods.lua`, `ai-missions.lua`, `ai-mission-send.lua`, `ai-camera.lua` | a mood's missing materials; the missions report; sending the messenger by the World screen; the camera director |
| `lua/ai-builder.lua`, `ai-layouts.lua` (hub; `ai-layouts-kinds`), `ai-blueprints.lua` (hub; `-translate`, `-stages`) | Digging and furnishing projects; room layouts for each kind; the landmarks' blueprint format |
| `lua/ai-gates.lua` | Maps entrances, finds what closes them, the gate watcher, doors and fortified gates |
| `lua/ai-military.lua` | Squads, routines, kill orders, gear report |
| `lua/ai-society.lua` | Shelter burrow, pastures, population cap, sending dwarves away |
| `lua/ai-industry.lua` | Ore uncovered near the fort, by metal; mining a vein safely |
| `lua/ai-trade.lua` | Caravans and the depot: the fort's crafts taken there for a caravan |
| `lua/ai-nobles.lua` | The fort's offices: appointing the manager, bookkeeper, broker and chief medical dwarf |
| `brain/backup.py` | A copy of the save once a real day while unattended (backups/) |
| `lua/ai-health.lua`, `ai-homes.lua` | (0.104.168) The infected and their hospital beds; homes: couples, rooms, upgrades |
| `brain/planner_care.py`, `planner_homes.py` | (0.104.168) Care (infected to bed, doctors, offices refilled); homes rules |
| `lua/ai-threats.lua`, `brain/planner_threats.py` | (0.105.0) Fire guard, prisoners, thieves, undead, werebeast cells, cavern seals, surface beasts, the wounded |
| `lua/ai-diplomacy.lua`, `brain/planner_world.py`, `probe_meeting.py` | (0.105.0) Meetings answered, the world report, exports, tribute, the Messenger and Make contact |
| `lua/ai-waterworks.lua`, `brain/planner_water.py` | (0.105.0) Moat, magma workshops, irrigation, pumps (staged, with flood-path dry runs) |
| `brain/planner_army.py`, `pin.py`, `scenario_mark.py` | (0.105.0) Gear gaps, quivers, bolts, shelter, the vertical cut; the keeper's pin; test-copy marks |
| (0.105.41) `lua/ai-noble-demands`, `ai-pile-links`, `ai-traffic`, `ai-provisions`, `ai-siege`, `ai-captives`, `ai-hazards`, `ai-bans`, `ai-paper`, `ai-benches`, `ai-forestry`, `ai-leather-gear`, `ai-syndromes`, `ai-artifacts`; `brain/planner_<same topics>.py` (peace for ai-diplomacy's peace answer) | nobles' rooms; barrows and feeder links; traffic zones; hunting, butchery, fruit, meals, cavern farms; fortifications, ballistae, posts, caravan guard, wildlife; prisoners' pit, undead sieges; spilt magma, cave-ins, frost, heat; export bans; paper; training benches; cavern logging and the grove; leather armour; syndromes and miasma; artifacts on display |
| (0.105.45) `lua/ai-hunt`, `ai-threat-facts`, `ai-killzone`, `ai-lure`, `ai-shelter-plan`, `ai-stuck`; `brain/planner_hunt`, `planner_matchup`, `planner_killzone`, `planner_lure`, `planner_shelter`, `planner_stuck` | hunting; a threat's facts and the matchup; kill zones at gates; the lure pocket; the shelter away from the threat; the sweep for things stuck in progress |
| (0.105.46) `brain/seen.py`, `order_check.py`, `planner_thirst`, `planner_recovery`, `old_saves.py`; `lua/ai-thirst`, `ai-recovery`, `ai-slices`, `ai-cavern-scan` | the seen-in-game ledger; the order check; the thirst watch; collapse recovery; old test saves; long walks sliced; caverns' seen samples |
| (0.105.47) `lua/ai-way-out`, `ai-mission-way`, `ai-raids`, `ai-tantrums`, `ai-welfare`, `ai-well-safety`, `ai-herd`, `ai-descent`, `ai-builder-court`, `ai-meeting-open`, `ai-screen-buttons`; `brain/planner_way_out`, `planner_raids`, `planner_tantrums`, `planner_welfare`, `planner_wellsafe`, `planner_husbandry`, `planner_descent`, `planner_garden`, `planner_guided` | the way out; missions' way and raids; tantrums; the dead and small forts; cavern wells' safety; the herd; the cavern crossing; the garden court; meetings; Guided live |
| (0.105.48) `brain/hold_classes.py`, `fort_run.py`, `planner_guards.py`; `tests/snapshots.py`, `test_df_names.py`, `brain/tools/gen_df_names.py` | every rule and action classed survival/defence/expansion (crisis and recovery hold by it); the run's own id; unread sections and outdoor work in danger; the committed plan snapshots; the DF-names check and its generator |
| (0.105.55) `lua/ai-floorplan`, `ai-floorplace`, `ai-floorunits`, `ai-builder-floorstore`, `ai-builder-floors`, `ai-builder-floorpiles`; `brain/floor_grammar`, `masterplan_floors`, `planner_floors`, `planner_floor_notes`; `brain/tools/draw_level.py` | the floor record; the hall and slots; levels cut into room units; the saved record and the `floors` report; the site on a floor; workshops' pile rooms; the hall's proportions from sliders and style; each kind's district and floor; the hint on each level; notes and the digest line; levels drawn as text |
| (0.105.64) hubs `ai-waterworks`, `ai-society`, `ai-military`, `ai-threats` + `<hub>-<theme>.lua` parts (PARTS); builder parts `projects-*`, `wells-*`, `cistern-*`, `keep`, `deepdepot`, `wagonroad`, `dump`; `ai-bridge-catalog`, `ai-bridge-sections` (HUB_PARTS) | the 13c splits: names stay `reqscript('<hub>').name`; tests read a family with `split_src`, `builder_part_src`, `bridge_hub_src` (`tests/lua_modules_util.py`) |
| `lua/ai-labor.lua` | Who does what: miners, woodcutters, plant gatherers, fishers, farmers through the game's work details; shrubs marked for gathering; water to fish in |
| `lua/ai-reports.lua` | Turns game announcements into events (moods, tantrums, sieges...) |
| `lua/ai-overseer-settings.lua`, `gui/ai-overseer.lua` (+ `gui/ai-overseer-rules`: Rules and Army tabs; `gui/ai-overseer-culture`: Needs you, Culture, Camera tabs) | Sliders, Rules tab, Needs you tab |
| `lua/ai-status.lua`, `ai-overlay.lua` | Status and the on-screen overlay |
| `brain/overseer.py` | The main loop, modes (Advisor, Co-pilot, Autopilot), Needs you list |
| `brain/planner.py` | `plan()`, `note_cycle()`, `select()`, `record()`; re-exports every rule module |
| `brain/planner_core.py`, `planner_config.py` | Memory, proposals, the holds and back-offs; `PLANNER_CONFIG` (every tuning number) |
| `brain/planner_*.py` | the rules by theme: building, wells, growth, society, moods, visitors, health, locations, industry, farms, labor, trade, orders, military, gates, army, threats, water, world, care |
| `brain/util.py`, `brain/tools/` | `load_json`, ticks, `folder_lock`; one-off scripts (`try_actions`, `try_building`, `token_test`, `probe_title`) |
| `brain/scorecard.py` | the slider scorecard (`--every 2y`, run stamps, the health table) |
| `brain/culture.py` | Fort personality: hall style, stone palette, gate style, memorials |
| `brain/leanings.py`, `temperament.py` | The fort's own and the site's leanings, history pushes (0.95); each slider's effects in words, the window's "Now:" line (0.94) |
| `brain/strategist.py`, `tokens.py` | The optional AI strategist and its token budget |
| `brain/weights.py`, `choices.json`, `quirks.py` | The weights engine, its data, and earned quirks |
| `brain/learning.py`, `calibrate.py`, `outcomes.py` | Learning from the player, self-tuned targets, the outcome log |
| `brain/memstore.py` | The six kinds of memory: save keys, schema versions and migrations, logs per fort, size budgets |
| `brain/timeline.py`, `atlas.py`, `chronicle.py` | Daily numbers with seasons and years; the survey, registry, entrances and located events; the fort's story |
| `brain/masterplan.py`, `phases.py` | The master plan (spine, districts, names, placement hints); the fort's phases of life |
| `brain/digest.py` | Compact fort summary; lists required report sections |
| `brain/selftest.py`, `scenario.py`, `replay.py`, `metrics.py` | In-game checks and test runs |
| `brain/health_check.py` | The unattended run's check: loops, refusals, churn, standing Needs you, FPS, housekeeping |
