# Round 10 briefs (the player, 22 Nov 00:32): petitions (12b) and the messenger (13b)

Written at 0.105.65 (`main` 470f8de) for the next chat. Run them as two parallel builders (the standing
"work in parallel" rule): each in its own copy and branch, **only named test files with -j 1 in the cloud**
(two cores: never two full suites at once; the full suite runs once on the PC through Claude Helper after
the merge). Neither builder pushes, edits the handoff or bumps the version.

## p1: residency and citizenship petitions actually answered (Phase 12b)

The problem: DF's standing orders are out of DFHack 53.17-r1's reach (`orders: []` in all six forts); since
0.105.57 every petition is weighed (the Outsiders slider: closed at -50 or lower declines in batches of 25,
welcoming at 30+ agrees one as a probe, then batches) but declined or left 28 days for the player on DF's
petitions screen; 8 citizenship petitions were waiting. Read the current code first (grep petition,
residency, citizenship, agreement in lua/ and brain/: ai-bridge-report*, ai-bridge-actions-civic,
ai-noble-demands, ai-diplomacy, planner_world / planner_visitors / planner_locations; docs/dfhack-notes.md).

Step 1, find a real route, with evidence (clone github.com/DFHack/df-structures, /dfhack and /scripts into a
scratch folder): where pending petitions live in 53.x (e.g. `plotinfo.petitions`, `df.agreement` with
Residency/Citizenship details, its parties and flags); what DF changes when the player approves or denies
one on the Petitions screen (agreement details/flags, the petitioner's histfig/unit flags and entity links,
the petition list); whether DFHack's `makeown` (script or `dfhack.units.makeown`) covers what approval does;
whether the Petitions screen (`game.main_interface.petitions` or similar) can be driven with the project's
word-found screen buttons (lua/ai-screen-buttons.lua, as trade and the mission sender do). Write the
findings with xml/file references into docs/dfhack-notes.md, "Petitions (r10)".

Step 2, the smallest reliable fix, in this order of preference: (a) set exactly the data DF sets on
approval, if the evidence shows it and it's safe; (b) drive the Petitions screen (word-found buttons, a
calibration record like trade's, never a screen the player is reading, a stall guard); (c) `makeown` plus
removing the petition, if that is what approval amounts to. Keep the existing weighing; make the decision
happen in game; record outcomes; back off after refusals. Prefer extending the existing petition action (a
new action needs ACTIONS/DRY_OK in lua/ai-bridge-catalog.lua, a label in brain/overseer_words.py, a planner
rule, tests). Add a read-only probe `lua/probes/probe-petitions.lua` (laid out like the existing probe
scripts the runner's `probe` job runs: prints JSON of petitions, their agreement details and petitioners'
flags; changes nothing). Tests: tests/test_r10_p1.py (approve and deny each kind on a fake world; nothing
done with the player's screen open or in danger; refusals backed off; dry run changes nothing); existing
petition tests and test_df_names pass.

## p2: a messenger post, so missions can be sent (Phase 13b)

The problem (21 Nov audit B2): no fort has a messenger post, so `_messenger_rule` and Make contact never
run. The sender stops at "the fort has no messenger's post" (lua/ai-mission-send-run.lua ~409-428); Mission
details says "No messengers available" (ai-mission-send-steps.lua ~338-350); lua/ai-nobles.lua ~214
reports `messenger = {position = p ~= nil}`. Read the code first (grep messenger, MESSENGER, assigned_epp,
entity_position, appoint: ai-nobles, ai-missions*, ai-mission-send*, planner_world `_messenger_rule`,
planner_missions).

Step 1, find the real rule, with evidence (same clones; DF's entity raws `[POSITION:MESSENGER]` with
REQUIRES_POPULATION / APPOINTED_BY / SITE, as far as the repos show them): what makes a MESSENGER position
exist or become appointable in a player fort in 53.x (from the start, a population threshold, a noble or
landholder rank, a World-screen unlock); how the Nobles screen appoints someone and what data changes
(`entity_position_assignment.histfig`, the histfig's position link, unit flags); how ai-nobles already
appoints the manager, bookkeeper, broker and chief medical dwarf, and whether that works for any post once
its assignment exists; whether creating an assignment from Lua is safe. Write it into docs/dfhack-notes.md,
"The messenger (r10)".

Step 2, the smallest reliable fix: appoint a suitable citizen (not a soldier on duty, not a noble with
another office, one who can travel) as soon as the post exists, through ai-nobles' mechanism (or the Nobles
screen by word-found buttons if setting data is unsafe); when the game doesn't allow it yet, report exactly
why (`missions.messenger.why`: "no post until population N", "post exists, nobody appointed", ...) with a
planner note. Missions, raids and the messenger stay OFF by default (the player's 14 Nov rule): the
appointment may happen whenever the post exists, sending stays behind the existing switches. Add a read-only
probe `lua/probes/probe-messenger.lua` (JSON of the fortress entity's positions, flags, requirements,
assignments, holders, the population and rank; changes nothing). Tests: tests/test_r10_p2.py (post absent:
the why; post present and empty: a suitable citizen appointed, soldiers and nobles skipped; held: nothing;
dry run changes nothing); existing nobles/missions tests and test_df_names pass.

## After both

Merge on `merge0.105.66`, run the named tests, bump the version across lua/*.lua **and lua/gui/*.lua** plus
tests/test_bridge_memory.py, run the full suite on the PC (Claude Helper `run_tests`), `install`, `verify`,
push, update the handoff. In the next run: the runner's `probe` job with `probe-petitions` and
`probe-messenger` on a fort or two, before trusting either fix.
