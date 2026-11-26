# DF AI Overseer: Handoff

25 Nov 2026 (21:25) · @Scott · the one doc to carry between chats: what this is, the plan, how to work, where things live and where to start. History and long lists live in local files (see "Files kept outside this note").

## Standing instructions

Every chat follows the project doc **"DF AI Overseer Standing Instructions"**: read this handoff first and follow its plan and working rules; ask for access to the local log folder at the start (or ask for the files a task needs); read the local files when a task needs them; at the end of every version or milestone, update the changelog, the plan, the start notes, the local files, save this handoff back to the project and send it. Keep this note small: history goes to the archive file.

## How this document is organised

- **What this is**: the project and where it stands now (the latest version).
- **Current plan and checklist**: the road to completion, phase by phase, ticked as done. Updated whenever the plan changes.
- **How to work**: the agreed working rules (standing decisions, key and cost rules, how changes are tested and shipped).
- **Where things live**: folders, the game and DFHack, commands, and what each code file does.
- **Files kept outside this note**: the local reference files and when to read or update each.
- **Starting the next step**: notes for the next chat only. When they're done, they move to the archive file.
- **Changelog**: one line per version, newest first.

## What this is

The AI Overseer runs a Dwarf Fortress fort through DFHack while the player watches. A Python brain reads the fort through a Lua bridge, plans with a free local planner (and an optional AI strategist that spends tokens), and acts in the game. The player steers it with sliders, a Rules tab and a Needs you tab in the in-game window. It's for the player's own use only.

**AI module work (Phase 14.3, 14a-14d) has its own note: `handoff-ai.md` (project doc "DF AI Overseer AI Module Handoff"), written 11 Nov; read it with this one.**

**Latest version: 0.105.121** (25 Nov 20:47, `main` `1a540b9`, 1005 files, 0 differ in all six; the keepers run it). 0.105.120-121 fixed what 0.105.119 broke or missed live: `kitchen_cheap` (`flags.forbid`; fish and eggs by `getActualMaterial`), a kill order's dead targets dropped (E: 228 refusals), a gate bridge never moved with one of the fort's own on it (B 19:42: a stoneworker killed). C restarted fresh 19:20 (a werellama outbreak: 24 of 91 cursed; old run `D:\DF-C\old-saves\2026-11-25c-C`).

**0.105.119** (25 Nov 19:13, `2293833`): one large round from the fresh run's first years (all six from embark 11:40, B again 14:50; by 18:30 years 252-254), twelve builders + a split + a merge fixer:
- **Werebeasts** (A's outbreak 16:38 y253, 25 dead; F's wereskink, werellama and weremole children; E's werepanther child: all wild weres from the map edge): `moon_cell`'s `cell_room` had thrown on `z.were` (a DF zone) since 0.105.115, so no jail/bedroom was ever found: fixed, with fallbacks to an office/tomb/a dug side cell/an unlinked were cell, a room reserved as soon as a cursed citizen is known, the move-in at the lead's first call, escapes caught (item31). Every free squad at a were in beast form, no odds filter, kill orders cleared in dwarf form (item32, `planner_military_weres`). `mechanism_stock` for the lever links, sized to ordinary stone, a quarry when short (D: "Needs non-economic hard stone boulders") (item30). A were-bitten dwarf's strangling hold broken (`cursed_choke`, item34).
- **Moods:** a cut-short shop search no longer backed off, `place_mood_shop` while a level is only coming (A's armorer and gem-cutter), spare tame animals counted right (item36); coke burns a fuel (charcoal at 0), 3x3 mood shops, no sand on region4: glass moods noted and `ROUGH:GLASS` asked of caravans (item41).
- **D's idle 51%:** its 3 picks were blades in weapon traps: picks forged when none usable (item33); weapon traps take trap blades only (item40). Labour asks DF can take; `cook_staff` + the kitchen floor at the best cook (item33). **A's 28-50% unhappy:** every squad trained all year (Militarism 150 turns the rotation off): `war_leisure` rests one in three a month; coffins of the other material when an order stalls (item35). `meal_cheap` keeps cheap ingredients from the cooks (item37). Old levels' boxes no longer block floors (item38). Fifteen repeating refusals stopped at the source, `cap_full_pass` (item39). Six Lua files split (`ai-trade-unload`, `ai-fights-scan`, `ai-threats-seal`, `ai-bridge-report-civic`, `ai-bridge-orders-jobs`, `ai-bridge-actions-trade`); `ai-werecells` now requires `dfhack.buildings`.

0.105.115-118 (25 Nov): drawbridge were cells, beatings spared, the recreation burrow, Room size presets (115); moods' bars and shops, the cistern that sealed its digger (116); the keeper's title screen ~15 s (117) and relaunch after 60 s (118) (the archive has the full notes).

Older notes (0.105.113 and before, the forts of 24 Nov, the exit test so far, what works as audited 21 Nov): the archive, "Moved out 25 Nov 2026 (21:25)".

## Current plan and checklist

The road to completion: each phase a few rounds, each checked against the live keeper log; what can lose the fort first, the agent last. Open gaps per phase: the Gap Checklist file. **The full text of every phase below (dates, the history of each decision, what each round built): the archive, "Moved out 22 Nov 2026 (12:00)"; read it before changing a phase.** Order (agreed 21 Nov 11:20, the audit): survival before features; then make built things run; then the agent.

- [ ] **R29 0.105.122, "the never-seen features" (planned 25 Nov 21:25; build in the next chat, all at once while the run goes on).** One builder per workstream, each in its own copy, files apart (below); one merge, one full suite, one release. **Ask the player first** (one AskUserQuestion): (a) may one fort be sent a siege on purpose (DFHack `force`), and which; (b) may tokens be spent on one `--ai` season (Phase 14.3); (c) `spare_beatings` as a Rules switch?
  - [ ] **W1 verify (investigator, no code; at ~2 game years from 21:20, ~1 real hour):** moods failed per fort since 19:21; weres (`moon_cell` `reserved`/`moved`/`side`/`escaped`, `were_cells` linked, `squad_attack` "beast form", deaths by weres); `beatings_spared`/`beating_stopped`; killers held; A `war_leisure` and unhappy; `cook_staff`, `meal_cheap`, `supplies.good_meals`; D `picks`, idle; the fifteen repeats; then the scorecard (`python brain\scorecard.py --every 2y` with all six `--fort` folders) = **Phase 14.1 step 5's verdict** (each preset wins its own lines; Room size and Welfare lines judged now). Tick the changelog's statuses.
  - [ ] **W2 sieges (Phase 11):** files `brain/planner_siege.py`, `brain/planner_holdfast.py`, `brain/planner_defence*.py`, `lua/ai-siege.lua` (also holds `place_mood_shop`: keep it), a new `brain/scenario_siege.py`. A Rules switch "Invite a siege (test)" (off) that, when on, has DFHack `force` an invasion at that fort once; then the exit check: the fort survives it on its own and the per-gate records fill (`gates`, `kill zones`, the shelter, squads, `field_watch`). Only with the player's yes (a).
  - [ ] **W3 water works that finish (Phase 13):** files `brain/planner_water*.py`, `brain/planner_wells_water.py`, `lua/ai-waterworks*.lua`, `lua/ai-builder-cistern*.lua`. Live (25 Nov): irrigation stops at "being built: the floodgate" (B, C, F `stuck_sweep` 8-9 an hour), "dry run: a stockpile / a building (civzone) in the way"; D's moat "the gate has no open ground outside it"; the magma pipe "other water on the way/beside the way" (A, B, D, E); D's cistern search times out. Exit: one of each (irrigation, moat, magma works, cistern) built on a real map and its emergency gate shown to work.
  - [ ] **W4 the world map (Phase 13b):** files `lua/ai-mission-send*.lua`, `lua/ai-mission-way.lua`, `lua/ai-missions*.lua`, `brain/planner_missions.py`, `brain/probe_missions.py`. The AI's own run reaches the World screen (0.105.68) but not past the site's click: make Make contact go through (the player's clicks of 14 Nov are in the archive). Exit: a messenger appointed, sent and back.
  - [ ] **W5 library and books:** 0 books in every fort ever. Find why (scholars' labours, paper: papyrus/parchment/quire making, bookcases, the library location's settings: allow writing, scribes, `library` level); fix. Files: the library/locations code (`grep -rln "library" brain lua`), not `lua/ai-bridge-report-civic.lua`'s locations report beyond a key.
  - [ ] **W6 hunts, lures, sorties:** files `brain/planner_hunt.py`, `brain/planner_lure.py`, `lua/ai-hunt.lua`, `lua/ai-lure.lua`, the sortie code. Never seen: find each one's trigger and why it never fired (thresholds, `beatable` odds, no target in reach), make them fire on wildlife and cavern beasts judged beatable. Exit: one hunt, one lure, one sortie logged with a result.
  - [ ] **W7 performance (Phase 13e):** files `brain/perf.py`, the costliest report sections (`perf.jsonl` `report_ms`, `logs\forts\*\perf.jsonl`) and rules. FPS 36-60 in the big forts against ~100 at embark: measure the AI's own share per cycle by section, cut the top three, then the soak comparison (within ~20% of year one at the same population).
  - [ ] **W8 small items:** D's second stairwell through dug floors by **constructed** stairs (`lua/ai-builder-sites.lua` `check_extension`/`dig_stairwell`); F's weremole leaving a raised-bridge cell (17:21-17:27 25 Nov: a read-only probe of `lua/ai-werecells.lua`'s cells: bridge raised? the cell's tiles closed on all sides incl. diagonals and above/below?); `spare_beatings` on the Rules tab if (c) is yes.
  - [ ] **W9 the thinking AI (Phase 14.3, `handoff-ai.md`):** with the player's yes (b), one live season with `--ai` on one fort within the token caps; else plan only.
  - Files kept apart: W2 owns `ai-siege.lua`; W3 the water/cistern files; W8 `ai-builder-sites.lua` and `ai-werecells.lua`; W5 doesn't touch the civic report's layout; nobody but W7 edits `perf.py`. Lua 60 KB limit: split before adding (0.105.119's splits left 11-18 KB in each big file).
- [x] **The 24 Nov audit** (local file `DF AI Overseer Audit 2026-11-24.md`): its nine groups built as 0.105.112-113, then 0.105.114-121 for what the fresh run showed (the archive, 25 Nov, has the block).
- [x] **The audit plan (21 Nov; local file `DF AI Overseer Audit 2026-11-21.md`):** rounds R1-R28, 0.105.56-0.105.121, all built (the archive, 25 Nov 21:25, has the list); what is still unseen is W1's to check.
- [ ] **The improvement plan (14 Nov; Gap Checklist, "Improvement plan 14 Nov"):** R1-R2b and layout option B built; **R3 in game** = this run (also 14.1 step 5's exit test); later: minecarts, beekeeping, dyes and ceramics, a zoo, toys.
- [x] **Before the road (Oct 20-23)** and **Phase 10 (verification sweep)**: done; hand checks left in the Gap Checklist's in-game list.
- [ ] **Phase 11 - Combat, enemies on.** The "fight back" brief built (0.105.45): threats judged against the squads, hunts when clearly beatable, kill zones, the civilians' shelter, the stuck sweep; E's stuck hatch (0.105.32). Exit: the fort survives a siege on its own and the per-gate records fill in.
- [ ] **Phase 12 - A fort that lasts.** Every code item built (1 Nov); left: seen in game. Exit: a multi-year soak with stable FPS, unhappy under 10%, truly idle non-soldiers under 25%. Open: **12i tantrum spirals** (the main problem; hospitals, fisherdwarves, drink as a lever, calm-down burrows built), the library (0 books), 12n training and friends, bridge timeouts, "unable to complain".
- [ ] **Phase 12b - The world outside.** Exit: good relations with the neighbours for years, every petition answered. Built: temple/guildhall petitions, meetings answered, trade agreements, tribute, war and peace, troublesome visitors, the heist lockout; petitions to stay and citizenship by DF's own orders (0.105.66, seen set live; whether DF takes the ones already waiting: `swept`). Open: liaison meetings from a real one; agreements and requested goods.
- [ ] **Phase 13 - Water and industry.** region4 has a river (~x184 y64 z160; the survey's kind fixed 0.105.57; `probe-river` on C still to run); W3-W7 (cistern, moat, irrigation, pumps, power) and the magma works built, never run. Exit: each work built once on a real map, its emergency gate shown to work.
- [ ] **Phase 13b - Offence and the world map.** Targets, the sender for every goal, the planner with its reserve, the Army tab; Make contact's steps recorded 14 Nov (the player's clicks); the AI's own run reaches the World screen (0.105.68) but not yet past the site's click. Exit: a messenger appointed, sent (Make contact) and back. Left: rescues and artifacts.
- [ ] **Phase 13c - Code health.** Done in code (0.105.62-0.105.65: helpers merged, no Lua file over 60 KB, the audits' findings). Exit left: an FPS / cycle comparison on one save against the 15-16 Nov run, once the PC is quiet.
- [x] **Phase 13d - The camera director** (0.104.88-0.104.93; hand checks in the Gap Checklist).
- [ ] **Phase 13e - Performance.** The perf section, batch, shared walks, world cleanup (0.105.39). Exit: a multi-year soak within ~20% of the first year's FPS at the same population, the AI's own share measured and small.
- [ ] **Phase 14 - The thinking AI** (design: the Design Notes file; AI module work: `handoff-ai.md`).
  - [x] 14.0 fort identity, the full detailing · 14.2 quirks (36, built)
  - [ ] **14.1 sliders:** the scorecard, signatures, the character slot, preset signatures built; **5. the exit test** = this run (six from `region4`, the scorecard every couple of game years; passed when each preset wins its own lines; sliders that still show nothing: merge or drop, the player's call).
  - [ ] 14.3 token use (the season's character decision built; a live season with `--ai` next) · scripts first (built) · 14e the design track (D0 built; D1 Guided live, D2 Architect, D3 comparisons) · 14a-14d the agent (14a built, 14b Director loop, 14c Agent, 14d comparison runs). Exit: a game decade run by the agent within budget, at least as well as the scripts, every fort visibly its own.
- [ ] **Phase 15 - Final tests and completion:** the distinctiveness run, a long soak with the agent on, a performance pass, a crash and relaunch on purpose, packaging and the docs.

## How to work

### Standing decisions

These are the player's rules for all future work.

- **Work in parallel (the player's rule, 7 Nov 19:46).** Every task is split into small, separate groups that each touch their own part of the code, and each group goes to its own builder agent running at the same time, each in its own copy of the repo on its own branch (`cp -r` the clone to `work<n>`, `git checkout -b item<n>`). More, smaller groups beat fewer, bigger ones; one builder per group, no helpers inside a group (they would share one copy). Each brief says: work only in its copy, don't bump `BRIDGE_VERSION` or edit the handoff, don't push, commit when all tests pass, and report what changed, the tests, what needs an in-game look and the risks. Claude merges the branches (a `merge<version>` branch, conflicts resolved by hand), runs every test and the Lua compile check, bumps the version once, delivers to all six folders with the hash check, and updates the handoff. Investigations (log forensics) are split the same way, one agent per question. Only a step that truly depends on another's result waits for it.
- **Context warning.** Tell the player when the conversation's context reaches 60% of its limit, so the work can move to a new chat with this handoff.
- **One handoff, small.** This handoff and the standing-instructions doc are the only project docs. Any roadmap, design, plan or notes doc that turns up is folded into the handoff (if it's needed every chat) or into one of the local files (see "Files kept outside this note"), and deleted. Keep the handoff under about 70 KB: history and long lists go into the local files, never into a new project doc. (Set up 23 Oct 2026, replacing "one document only".)
- **Keep the changelog.** Every new version gets a line in the Changelog section (what changed, in game or built), and its "Status" is updated once it's seen in the game.
- **Keep the plan current.** Whenever the plan changes (a step done, added, moved or dropped), update "Current plan and checklist" and "Starting the next step" in the same round. At the end of a version, the old start notes move to the archive file.
- **Use helper agents.** Start more agents (sub-agents) whenever it would speed the work up, for example to read several parts of the code at once, check work independently, or build separate pieces in parallel.
- **The AI does it itself.** If something can be decided or set up in the game, the AI does it rather than asking. Examples: picking the entrance, placing and naming levers and doors, making the shelter burrow.
- **Placement follows the fort's character.** The AI places all buildings and objects where the fort's history and personality say they belong.
- **Nothing waits for the player (11 Nov).** The AI decides every case itself, even in a siege or a crisis; it never leaves something for the player to choose or do when it can act. A Needs you note is only for what the game truly won't let the AI do, and says what the AI does meanwhile. Old "open it yourself" or "put to the player" paths are to be turned into the AI's own choice as they're found.
- **Thirst before forbids (14 Nov):** a dwarf whose only drink is forbidden gets it let go, the player's forbid included (not with the gates armed or an enemy within 15 tiles).
- **Training for the keen in peaceful forts (14 Nov):** high Welfare allows a small training-only squad for civilians who badly want to fight, whatever the Militarism.
- **Raids by character (14 Nov):** aggressive forts (high Militarism) may raid any reachable civ but keep their friends (own civ, allies, trade partners, peace pending, at least two at peace); the rest are reactive: retaliation against attackers and hostile sites setting up nearby; very peaceful forts only clear wins close by. The Army tab's "Raids" switch overrides. **(22 Nov 00:51, the player, replaces 14 Nov 21:54's "off" and "the Hermit hold sends no messenger"):** every fort makes at least some initial contact with nearby towns and forts; then the AI decides how much contact and what kind, raids included; the Hermit hold makes its initial contacts, then contacts others only when the AI judges the situation calls for it. On by default (0.105.66); the Rules/Army switches stay overrides (off = never).
- **Never sealed in (14 Nov):** the AI opens its gates by their levers; the fort must always reach the map edge unless a live danger holds it shut; a keeper stopping leaves the fort open.
- **Office holders (22 Nov 01:43):** a tiny fort lets an office holder double as messenger, replaced once a suitable free dwarf exists; any office holder is replaced when a far better-suited dwarf is available (0.105.67).
- **Spacing and Room size stay separate sliders (11 Nov):** Room size is how large rooms are; Spacing is how far apart they are.
- **Needs you.** When something missing in the game world blocks the AI (like the old "no civilian-alert burrow" warning), it shows a note on the Needs you tab. Only things the AI truly can't do go there.
- **Taste goes on the Rules tab.** Options like memorial pace are switches the player can change there. Example: one memorial per season is the default.
- **A guard in every fort.** Every fort of 15+ adults keeps at least 3 soldiers, whatever the Militarism slider or preset (2 Nov).
- **The insane are not killed (24 Nov 22:36).** No switch or rule has soldiers kill an insane dwarf; berserk ones stay as DF handles them (an enemy to the fort).
- **Gates close late.** Gates close only when danger is near (within 12 tiles), or when it's coming and every citizen is inside, so dwarves have time to get back.

| Slider | -100 | 0 | +100 | With Extreme |
| --- | --- | --- | --- | --- |
| Militarism (share of citizens who are soldiers) | 5% | 10% | 40% | positive: 50% to 90%; negative: from 5% down to none |
| Growth (population target) | 25 | 100 | 250 | negative: the fort slowly sends dwarves away; positive: no cap |

The fort goal on the Rules tab is Expand or Maintain. Maintain skips the library, memorial and temple and keeps the population where it is.

### Key and cost

**Rules for the key and cost:** never paste the API key into chat, print it or log it. Spend no extra money: no purchased credits, no auto-reload. The subscription is for personal use only and must not be distributed.

### How changes are tested and delivered

1. Change the files in a working copy and run every test; all must pass. **From the PC clone (22 Nov 17:20, "work off the cloud"):** Claude Helper keeps a clone of the repo in the log folder's `Work\DorfOverseer` (`git` status / pull, preview then `apply` with `expect`: pull after every push). The runner's `git_source.py` builds jobs from it: a `verify-<v>.json` of `{"git": {"head": <commit>}}` makes the md5 list of every tracked file and the backup zip (`"backup": false` for none), so no verify json or zip is uploaded (checked 17:21); a `deliver-<v>.json` of `{"git": {"base", "head"}}` and `run_tests` named `git-<commit>` are built there too, (`install` takes the git json since 0.105.73; `run_tests` `git-<commit>` untried: upload the tars). **Tests when work runs in parallel (the owner, 21 Nov):** each builder in the cloud runs only the tests for its own change, then commits and reports; none runs the full suite there (2 cores). After the merge the full suite runs once, on the PC through Claude Helper. Full runs go to the PC runner through Claude Helper (below): `git archive --format=tar HEAD` as `run-<name>.tar` into `inbox-ext`, then `run_tests` (`project: "df"`, `name`, `tar_md5`); ~100 s. Known Windows-only failures (they pass on Linux): test_builder "band pass", test_fix26_bridge "compiled once", test_r33_keeper "autosave 2", test_r38_water "288x288x194", test_revive "game closed" (DF running), at times test_k48_shelter "slices" and test_d0_merge under load. The cloud has 2 cores: there, run only named test files.
**Since 24 Nov: one call, Claude Helper's `release` (version, head; the base is the last verified delivery, remembered), does the pull, the tests on that commit, the delivery json, `install`, `verify` and the code zip; steps 2-3 below are what it does, kept for the manual way (a branch not yet pushed).**
2. Deliver through the PC runner with Claude Helper's `install` (`project: "df"`, `name`), then `verify`: a `deliver-<version>.tar` of the changed files (`git diff --name-only --no-renames --diff-filter=d <delivered>..HEAD -- lua brain tests docs`) and `deliver-<version>.json` `{"base": {path: md5}, "new": {path: md5}}` (md5 = first 8 hex of the file with CR removed; base from the delivered commit), the json written last, into `DF-AI\_stage\testrunner\inbox-ext`. The runner checks every file in each of the six fixed folders matches base or new (a hand edit stops that folder), writes them, touches `lua\*.lua lua\gui\*.lua` and checks every new md5; its report is `results\deliver-<version>.txt`. Deletions are never delivered (the folders refuse deletes). DFHack reloads a script only when its own file's time changes: the touch covers it. **Version bump:** one find-replace of the quoted version across `lua/*.lua` **and `lua/gui/*.lua`** (BRIDGE_VERSION and every part's `PART_VERSIONS` marker) plus `tests/test_bridge_memory.py`. A split hub's parts are found from its `PARTS = {` line; tests list split hubs in `SPLIT` (`tests/lua_modules_util.py`). Deliver a hub's parts with it (DFHack reloads only when the hub's own file changes; the delivery touches every Lua file).
3. Read the copies back and compare them byte for byte (ignoring line endings). Copy from a fresh staging folder each time: re-using a staged path once wrote the old version back (Oct 21).
4. See the result in the game: read the live report (`state.json`) and the keeper log from the PC (the player restarts the keeper for Python changes; the self-test when the bridge's checks changed).
5. Commit the round to the GitHub repo (`SpaceisbigSoft/DF-Overseer`, private, branch `main`: one commit per round, the version in its title, pushed), and at the end of a version save a zip of it (`git archive`) to `DF-AI\backups\code\DF-Overseer-<date>-<commit>.zip` on the PC.
6. Note what changed: a line in the Changelog; the plan and checklist; new start notes (the old ones, and the version's long notes, into the archive file); the Gap Checklist and the other local files; then save the handoff to the project and send it to the player.

When a report section is added, wrap it in `safe()` in the bridge and give it a default in `digest.py`. A new bridge action needs an entry in the action table, a short label in `overseer.py`, and a planner rule with tests.

## Where things live

| What | Where or which |
| --- | --- |
| Game | Dwarf Fortress 53.17 (Steam, updated 9 Nov; B-F copies brought to 53.17 on 11 Nov, the 53.16 files kept in each `D:\DF-x\old-df-53.16`) |
| DFHack | 53.17-r1 (Steam's shared `D:\SteamLibrary\steamapps\common\DFHack`, used by all six copies; the code was built and tested against 53.16-r3: run `selftest.py` and read the first reports after any DFHack update) |
| Project folder | `C:\Users\skulr\Documents\DF-AI` |
| Save folder | (14 Nov) every game portable: A's in `D:\SteamLibrary\steamapps\common\Dwarf Fortress\save`, B-F in `D:\DF-x\save`; the AppData `save` is kept empty (old saves in `AppData\...\Dwarf Fortress\save-archive-2026-11-14`, A's 2023 ones in the game folder's `old-saves-2023`) |
| DFHack config | `D:\SteamLibrary\steamapps\common\Dwarf Fortress\dfhack-config` (its `script-paths.txt` points DFHack at `DF-AI\lua`) |
| API key | `DF-AI\.env` only (gitignored) |
| Local log folder | `C:\Users\skulr\Documents\Claude Project Creation Logs\Dorf AI Overseer` (the reference files below, and `DF AI Overseer Handoff.md`: a copy of this handoff that `start_here`/`wrap_up` read; saved there with every version) |
| PC runner and window | `DF-AI\_stage\testrunner` (PC only): `ext_jobs.py` runs Claude Helper's jobs (tests on its own Python 3.13 `py313` with lupa; deliveries; probes); `watch_tests.py --status-once` the hourly status (`results\status\status-latest.txt`, `alerts.txt`: a fort fallen, 3+ deaths or 2+ thirst deaths an hour, time stood still 3+, 2+ revives, keeper Tracebacks, a keeper silent 10+ min); `dashboard.py` the view. All run from `Documents\Start keepers.bat` (23 Nov); `start-test-runner.bat` retired. |
| Claude Helper extension (DF part) | Claude Helper 0.2.18+ (`project: "df"`): **`start_here`** (`chat`) opens every chat; **`release`** (version, head) delivers; `run_tests` (`name`, `tar_md5`; a `run-<name>.tar` in `_stage\testrunner\inbox-ext`), `install`/`verify` (the manual way), `summary` (the forts' digest), `keepers`, `fort_state` (a JSON path into a fort's live state.json, UTF-8), `journal` (filters), `probe` (`source` = read-only Lua inline), `job_result` (`id`), `edit_file` (`tools:digest.py`, `Documents\start-keepers.ps1`), `handoff_sync` then `wrap_up` after a handoff edit, `git` pull (`expect`), `status`, `running`, `tidy`. Waits are `wait_s` (~70 s at most). Drop files into `inbox-ext` (never `inbox`), the .json last. Changes to the helper itself: `Claude Helper\Requests.md`; the runner's own Python (`_stage\testrunner`) is the DF chat's. |
| Live report | `D:\SteamLibrary\steamapps\common\Dwarf Fortress\dfhack-config\ai-overseer\state.json` (the bridge writes each full report there; read only) |
| Game raws | `D:\SteamLibrary\steamapps\common\Dwarf Fortress\data\vanilla` (read only, for recipes and reactions) |
| Keeper log | `DF-AI\logs\unattended.log`; each fort's journal, memory copy, season report and states in `DF-AI\logs\forts\<fort>\` |
| This handoff | the project doc "DF AI Overseer Handoff", mirrored as `DF-AI\handoff.md` (and in the repo) |
| Code home | GitHub `SpaceisbigSoft/DF-Overseer`, renamed `SpaceisbigSoft/DorfOverseer` (the old address forwards) (private, `main`; first commit `ec4dab5`, 26 Oct 02:13: lua, brain, tests, docs, the handoff). Not in it: `.env`, `config.json`, `logs/`, `backups/`, `saves/`. The PC's `DF-AI` folder stays the copy the game runs; zips of the repo in `DF-AI\backups\code\` |

### Commands

From the DF-AI folder with the game running:

- `python brain\overseer.py`: dry run, shows what it would do (each fort's journal and memory copy: `logs\forts\<fort>\`)
- `python brain\overseer.py --autopilot`: does it (add `--ai` for the strategist)
- `Documents\Start keepers.bat` (22 Nov): the six keepers in one window (above); `Documents\start-keepers.bat`: the old six windows
- `python brain\keeper.py`: the long unattended run (autopilot, unpauses, saves each season, restarts the overseer if it stops; add `--ai` only if tokens may be spent). Read `logs\forts\<fort>\report.md` afterwards. `--revive` relaunches DF through Steam and loads the fort's newest save if the game closes
- `python brain\selftest.py`: checks the bridge inside the game (the health check runs it daily; 15 Nov on 0.105.54: 59-65 pass, 0 failed)
- `python brain\health_check.py`: the run check by hand (self-test, log review, speed, housekeeping; `--hours N`, `--no-selftest`); the keeper runs it daily
- `python tests\run_all.py`: every test, no game needed (Lua tests need `pip install lupa`)
- `python brain\scenario.py` and `python brain\replay.py`: test runs on a copy of a fort, and stepping through a run

### How it fits together

Each cycle the brain calls `dfhack-run ai-bridge <cmd>`, which answers with one JSON line (bulky data goes through files in `dfhack-config/ai-overseer`). The brain turns the report into a digest, the planner proposes actions, limits and cooldowns are applied, and the chosen actions go back through the bridge. Per-fort settings live in the save's persistent site data. Once per in-game day the full report is read; cycles in between (after an event or an answer) read the small pulse report over it. The AI's own memory goes into the save as five kinds of text (`ai-overseer/mem/...`), with a copy in `logs\forts\<fort>\`.

What each code file does: `docs/code-map.md` (the file table, moved out of this note at 0.105.64 for size; add new files there).

Design notes for each area are in `docs/` (building, military, culture, controls, testing, local-planner); `docs/setup-guide.md` sets up a fresh install; `docs/watch-in-game.md` is the in-game watch list.

## Files kept outside this note

In the local log folder (`C:\Users\skulr\Documents\Claude Project Creation Logs\Dorf AI Overseer`). Read them when a task needs them, without being asked; update them at the end of each version or milestone.

| File | What it holds | Read it when | Update it when |
| --- | --- | --- | --- |
| `DF AI Overseer Handoff Archive.md` | the full version-by-version notes with every live run, test and probe (the old "Where it stands"); old plans and reviews; every chat's old start notes; what moved and why | you need how something was found or decided, the details of a version, or what a live run showed | each version: the old start notes move in (newest first), with the version's long notes |
| `DF AI Overseer Audit 2026-11-24.md` | the 24 Nov audit: the survival bars, tonight's findings (pets in the fight watcher, E's killers free, moods' cloth), the plan against the truth, the nine-group plan | planning 0.105.112-113 | a group's finding changes the picture |
| `DF AI Overseer Gap Checklist.md` | open gaps by phase (the Oct 23 holes, the addendum of game systems left out), the in-game check lists, known issues | planning a phase or step, picking what to build next, before phase 15's final tests | a gap is closed or found, an in-game check is seen, a new known issue |
| `DF AI Overseer Design Notes.md` | the brain design (who decides, weights, quirks, memory and learning), the milestone roadmap, the world-data and building designs, the phase 14 agent design, the water engineering roadmap | changing how the brain decides, remembers or builds; starting phase 13 or 14 | a design changes or a new one is agreed |

Inside the project folder: `DF-AI\docs\` (code-level design notes: building, military, culture, controls, testing, local-planner) and `DF-AI\logs\` (run logs, season reports, soak report).

## Starting the next step

Notes for the next chat only (they move to the archive once done).

**25 Nov 21:25 (0.105.121 delivered 20:47; all six on it, stable since ~19:30; A y256, B y253, C y250 (fresh 19:20), D y256, E y256, F y255).** Next, in order:
0. `start_here`; ask for the folders (Documents, and `D:\SteamLibrary\...\Dwarf Fortress`, `D:\DF-B`..`D:\DF-F` when a task touches the games); `add_repo` (push) and clone `main` (`0322f09` or newer).
1. **Ask the player (a)-(c)** of R29, then start **W1-W9 at once** (the plan above): briefs from it, `brief-common` rules as in this chat (each builder `cp -r` the clone, its own branch, named tests in the cloud, Lua on the PC runner, commit, report). W1 waits until ~22:20 (two game years) for its numbers.
2. Merge, the full PC suite, re-record snapshots with a `rec-` run where Lua ones moved (`results\rec\`), bump to 0.105.122, `release`, S then R.
3. **Open from 25 Nov:** caravans rarely carry raw glass (glass moods on this sandless map still fail); the "stair's hub" refusals are genuine; the d0_merge layout lost a Clothiers level when `cap_full_pass` came in (accepted, not traced); Requests.md's five DF lines (fresh_fort, keepers stop + close_game, run_tests branch, record copies, summary deaths).
4. At the end of the chat: the usage breakdown recorded with `chat_usage` (standing instructions 16).

**How a chat works now:** builders in their own copies (`cp -r` the clone, `git checkout -b item<n>`), one per group, in parallel, plus a verifier; named tests in the cloud (no lupa there: Lua tests run on the PC); the full suite on the PC (`git archive` tar into `inbox-ext`, `run_tests` with `tar_md5`); then commit to `main` (squash, the version in the title, the trailers), push, and **`release`** (version, head; base remembered) pulls the PC clone, tests, installs, verifies and zips in one job. Python changes need the keepers restarted (S then R in the keepers' window); Lua reloads itself. Read the forts with `keepers`, `summary`, `fort_state` (UTF-8), `journal`, and `probe` with `source` (read-only Lua inline). After each handoff edit: save to the project, the log folder, the repo, then `handoff_sync` and `wrap_up`.

**Access at the start:** the local log folder, `Documents\DF-AI`, and `DF-AI-B`..`DF-AI-F` when a task reads a fort's logs (the classifier may refuse a request that includes the D: drive: ask for it in the chat). GitHub: `add_repo` SpaceisbigSoft/DorfOverseer (push), `git clone --depth 50`.

**The window (`dashboard.py`, PC only, `_stage\testrunner`, every 30 s from `start-keepers.ps1`):** a fixed 24-line view: the six forts' table (keeper, version, season, pop, **FPS** = the simulation speed (`calculated_fps` from `perf.jsonl`, last 5 min; red <20, yellow <40), unhappy, **idle = truly idle non-soldiers** (`avg_idle_free_pct`; the old `avg_idle_pct` counted the tavern, prayer and soldiers off duty: C read 42% against a true 14.5%), done/refused/deaths an hour, each with an arrow ▲▼ for the change over 10 minutes (`results\status\view-last.json`, half an hour kept), green good / red bad); then "Alerts this hour" (7 lines: up to 6, red first, 2 a fort, the fort's letter, a coloured dot, plain text; deaths, thirst, crisis, hostile or great arrivals, the alarm raised, squads sent, the hourly check's lines; repeats differing only in numbers once); Claude Helper's 3 newest jobs. The view clears the window and its scrollback itself; it reads the journal's rolled-over file too (`journal.1.jsonl`). **Also open:** A has two messengers (Atír, and Catten, the player's test appointment). Delivery by git (push, `git` pull `expect`, `deliver-<v>.json` `{"git": {"base", "head"}}`, `install`, `verify-<v>.json` `{"git": {"head"}}`, `verify`); full suite by an uploaded `run-<name>.tar`. Fort folders connected on the player's ask: `Documents` (all six `DF-AI*`), D's and E's `dfhack-config\ai-overseer`.

**How a chat works:** builders in their own copies, a verifier, named tests in the cloud, the full suite on the PC, `install`/`verify` from the PC clone, probes for live questions (the archive, 23 Nov 19:46, has the 22 Nov notes and the start-of-chat access note: ask for the folders in the chat if the request is refused).

**GitHub (12 Nov on).** The repo `SpaceisbigSoft/DorfOverseer` (`main`) is current. A new chat clones it (`add_repo`, then `git clone --depth 50`). Each round: committed and pushed to `main`; a zip to `DF-AI\backups\code\`.

**Access and the way a round goes.** Access at the start: `Documents\DF-AI` and the local log folder (and `D:\` for the game copies when a task needs them). The PC shell (`device_bash`) has `python3`, no `lupa`, no git login, no deletes. Work and test in the cloud clone (`pip install lupa --break-system-packages`; `python3 tests/run_all.py`, ~3 min), commit as `Claude <noreply@anthropic.com>`, then test, install and verify through Claude Helper ("How changes are tested and delivered").

**Restarting one fort fresh:** stop its keeper; close every window of that game; move its `save\*` to `old-saves\<date>-<fort>`; copy `first-save\region4` to `save\region4` and check the hashes; drop the site's entries (`*#1430`) from `logs\keeper-preset.json` and `logs\standing.json`; move `logs\forts\region4-1430`, `keeper-pin.json` and `last-fort.json` (also any copy in `logs\`) to `logs\old-runs\<date>\`; move that folder's `backups\` aside (0.105.48: backups carry a run id, old ones are not restored); move the game's `dfhack-config\ai-overseer` memory and state files aside; write a `last-fort.json` pointing at `region4`; touch the Lua; start with `--preset`.

## Changelog

One line per version, newest first (0.105.111 and older: the archive file, "Changelog rows moved out" and "Moved out 25 Nov 2026 (21:25)"): what changed, and whether it has run in the game ("in game" = seen working live; "built" = tested, not yet seen). The details of each are in the archive file ("Version-by-version notes"). **Add a line here with every new version.**

| Version | Date | What changed | Status |
| --- | --- | --- | --- |
| 0.105.121 | Nov 25 | `kitchen_cheap` keys fish and eggs by `getActualMaterial` (they have no `mat_type`: it still threw after 0.105.120) | delivered 25 Nov 20:47 (Lua only) |
| 0.105.120 | Nov 25 | `kitchen_cheap` read `flags.forbidden` (threw in every fort: `forbid`); a kill order's dead targets dropped, an all-dead order cleared (E 228 refusals); a gate bridge never raised or lowered with one of the fort's own on it (B 19:42: a stoneworker killed by the closing gate during a weresheep attack). C restarted fresh 19:20 (a werellama outbreak: 24 of 91 cursed) | delivered 25 Nov 20:11 |
| 0.105.119 | Nov 25 | Werebeasts: cells found again (a zone-read bug), rooms reserved before the moon, every squad at a were, mechanisms and quarries for the links; moods' shop searches kept going, coke with fuel, 3x3 shops, no-sand glass; D's picks forged and kept out of traps; A's squads rest by turns; cheap ingredients kept from the cooks, best cooks kept; floors past old levels; fifteen repeats stopped; six Lua files split | delivered 25 Nov 19:13 |
| 0.105.118 | Nov 25 | A closed game started again 60 s after it went down (`DOWN_S`, was 180), at most once every 2 minutes (`LAUNCH_EVERY_S`, was 900; the player's ask); never while its own process still runs | delivered 25 Nov 14:59 |
| 0.105.117 | Nov 25 | A game the keeper started loads its save ~15 s after the title screen shows (`TITLE_OWN_S`; was 2-3 min); a title the player opened keeps 2 minutes. B restarted fresh 14:50 (the cistern); C's DF crashed loading `autosave 1` at 14:53 (DF's own `length_error` in drawing) | delivered 25 Nov 14:56 |
| 0.105.116 | Nov 25 | Moods get their bar and their shop: any metal bar and an anvil asked of caravans, a smelter kept standing, a mood's shop placed on free floor first; the winter cistern never seals its digger in or sits by the stairs; a dwarf sealed in a dug pocket dug out | delivered 25 Nov 14:40 |
| 0.105.115 | Nov 25 | Were cells behind raised drawbridges, the cursed moved in, cell doors guarded; DF's beatings of convicts spared, killing officers swapped; the recreation burrow only the tavern and temple, labours off, friends together; the fort's goods out of the depot; refusals paced in real minutes; Room size in the Monastery and Merchant city | delivered 25 Nov 11:27; the fresh run from 11:40 |
| 0.105.114 | Nov 25 | E's werepanther outbreak: the were list past 10, dead werebeasts' cells freed, every cell door recorded, releases only well past the moon and never backed off; the watcher keeps out of fights with werebeasts (dead ones read as the fort's dead); were or raging killers locked at once; B's shafts remember a hidden beast; the caravan goods taken out of the depot before removal | delivered 25 Nov 08:18 |
| 0.105.113 | Nov 25 | B's social places consolidated (one tavern and temple per 40); meals cooked without drink; merchants' "too heavy" retried lighter; flux and pig iron bought; C's spare quivers handed out; Welfare's extra hospitals and its scorecard line; leather held for leather moods, fuel from one log | delivered 25 Nov 07:41 |
| 0.105.112 | Nov 25 | The fort's pets and guests on its side in the fight watcher, strangling holds separated at once; one kill is a cell, killers held while miserable, chronic attackers held; one reading of a mood's want, part-used cloth by DF's size, fuel for bar moods; the hospitals' thread/cloth capped; patients on the floor carried to bed; refusal streaks that hold; stuck one-stone orders remade, tombs given; F's dump crash; three Lua files split | delivered 25 Nov 07:21; seen 07:38-08:00: pet kinds, killers' `people`, `hospital_cap` (E), mood `partial` |

