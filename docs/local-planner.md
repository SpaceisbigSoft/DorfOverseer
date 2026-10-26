# The local planner (Phase 4, layer 1)

The local planner runs on your PC, costs **no tokens**, and keeps the fort
running on its own. The AI strategist (layer 2, optional) only adjusts its
priorities and handles what rules can't. The more the planner handles, the
fewer tokens the strategist needs.

## Design rules

1. **Overseer, not puppeteer.** Fort-wide actions only: work orders, automation
   tools, the civilian alert. Never individual dwarves.
2. **Never fight the player.** Never cancels or edits your orders. Once a tool
   has been seen running and then gets switched off, the planner leaves it off.
   If you clear an alert the AI raised, it won't raise it again for those same
   threats (a new threat still counts). It never lowers an alert you raised.
3. **Never duplicate.** Counts what's already queued (anyone's orders) before
   ordering more.
4. **Small, steady steps.** Limits on actions per cycle and per in-game day, a
   cooldown per rule, and a cap on order size.
5. **Refuse to act on bad data.** If a report section a rule needs failed or is
   missing, that rule skips the cycle. If it can't tell which fort is loaded,
   nothing happens at all.
6. **Everything is explained.** Every proposal carries its rule and reason, and
   every action goes into the fort's journal, `logs\forts\<fort>\journal.jsonl`.
7. **Safe by default.** Dry-run (shows what it would do) unless started with
   `--autopilot`. A file named `STOP` in the project folder halts all actions.

## The loop

`python brain\overseer.py [--autopilot] [--ai] [--once]`

- Checks the game every 2 seconds (cheap status call).
- Each time an in-game day passes while the game runs, and soon after any
  event (siege, death, arrival), it reads the fort report, collects events,
  plans, and (in autopilot) acts.
- If the game doesn't answer mid-action, the result is logged as UNKNOWN and
  the rule's cooldown starts anyway, so it never does the same thing twice.
- Loading an older save of the same fort is handled: cooldowns reset.
- If DF closes or goes to the menu, it waits and reconnects.
- `--once` plans a single cycle and exits, which is useful for testing.

## Rules, in priority order

Trait values come from the control panel (-200..200 after Extreme). A trait
**factor** of 2^(trait/100) turns them into multipliers: 0 gives x1, +100 gives
x2, -100 gives x0.5, and the Extreme range gives x0.25 to x4.

| # | Rule | Fires when | Action | Traits that shift it |
| --- | --- | --- | --- | --- |
| 1 | Threat alert | a threat can walk to the dwarves | civilian alert on (if a burrow is set up); off again after 3 quiet cycles, only if the AI raised it | Caution: at +100 also reacts to threats of unknown reach within 10 levels |
| 2 | Drink | drink + queued < target (10 per dwarf) | brew_drink, 10 to 100 jobs (about 5 drinks each) | Stockpile buffer scales the target |
| 3 | Food | meals + queued < target (8 per dwarf), and raw food is available | easy / fine / lavish meals | Stockpile buffer scales the target; Welfare picks the meal grade |
| 4 | Mandates | a noble's Make mandate matches a known recipe and isn't queued | queue the remaining amount (max 10); a named stone is used; other materials (gold, iron...) are left to you | skipped if Noble deference < -50 |
| 5 | Automation tools | a useful tool is off | switch it on | Agriculture (seedwatch; autofarm once there are farm plots, so they get crops), Husbandry (nestboxes; autobutcher only when herds are large and Husbandry is 0 or lower), Welfare (tailor), wood need (autochop); suspendmanager always |
| 6 | Idle hands | more than 25% of adults idle, plenty of boulders, blocks below target | stone_blocks, 20 to 50 | Industriousness lowers the idle threshold; Stockpile buffer scales the block target |

Targets per dwarf (10 drinks, 8 meals, 5 blocks) are item counts; work orders
count jobs, and one job makes several items (5 drinks, 4 blocks, at least 2
meals), so order sizes are converted. These are starting guesses, kept in one
place (`PLANNER_CONFIG` in `brain\planner.py`), and the AI strategist may tune
the per-dwarf targets within fixed bounds.

## Limits (defaults)

- At most 3 actions per cycle, and 8 new work orders per in-game day
- Each rule waits 2 in-game days after acting before it may act again
- Work orders capped at 100 per order

## What the strategist gets from it

A short summary of what the planner did and what it couldn't do ("no plants to
brew"), so the strategist spends tokens only on real decisions. The
strategist's actions go through the same limits as the planner's, ahead of the
planner's routine rules (the alert still comes first).

## Announcements the overseer reads

Besides deaths, arrivals and invasions, the overseer reads the game's
announcements and sorts them into topics (`lua/ai-reports.lua`): strange
moods (and their workshop claims, construction, artifacts), insanity,
tantrums, stress, ghosts, thieves, sieges, curses (vampires, werebeasts,
necromancers), crimes, petitions, births, migrants, caravans, cave-ins,
floods and cancelled digging.

- The overseer prints the important ones as `Seen: tantrum: ...`.
- Moods, insanity, tantrums, ghosts, crimes, thieves, curses and disasters
  count as big events: they top up the token bank and prompt an AI review.
- Scenario runs count moods, artifacts, insanity, tantrums, ghosts and crimes
  per day, and `compare` shows them.
- `python brain\selftest.py` shows how the latest announcements were sorted.

Each topic is matched on the announcement's type name and on words in its
text, so a renamed type in a new DF version still has a second chance.

## Supplies: containers, hospital, water

Things that stop a fort without anyone noticing:

- **Free barrels and pots.** Brewing and cooking need an empty container;
  the game just stops when there are none. The planner keeps at least 10, or
  1 per 10 citizens, free (barrels plus large pots, not counting any already
  in use). It orders wooden barrels when wood is spare, otherwise rock pots
  (made by a craftsdwarf from stone).
- **Bags** for seeds, flour and gathered plants: at least 5, or 1 per 20
  citizens, from cloth.
- **Hospital supplies**, once there is a hospital or someone needs care:
  splints and crutches (1 per 40 citizens, at least 2) and buckets (at least
  3, or one per well). Soap, thread and cloth are only reported for now: soap
  needs lye and tallow, a longer chain.
- **Water.** Injured dwarves only drink water, carried from a well. With no
  well the AI places one (see Wells below). Wells without buckets get buckets.

The amounts are in `PLANNER_CONFIG` in `brain/planner.py`. The AI's summary
has a `SUPPLIES` line with the same numbers.

## The dead, strange moods, tavern and library

- **Burials.** The game reports ghosts of the fort's own dwarves, citizens'
  bodies not in a coffin, and coffins in a tomb zone that are still free.
  The planner keeps at least 2 free tombs, or 1 per 50 citizens, plus one
  for every body waiting. When it's short, it digs a **tombs** level: coffins
  along the walls, each in its own tomb zone. Ghosts, bodies with nowhere to
  go, and coffins outside any tomb zone are reported.
  Engraving a memorial slab for a ghost is left to you for now (the game
  needs you to pick the dead dwarf).
- **Strange moods.** For a dwarf in a crafting mood the game reports the
  skill, the workshop they claimed, and how many of the wanted items they
  have. If the fort lacks the workshop the mood needs, the planner builds it
  at once (a workshops level) when it can, and otherwise says which one to
  build. A dwarf who hasn't claimed a workshop after 2 days, or whose
  gathering stalls, is reported (DFHack's `showmood` says what's missing).
  Dwarves who went melancholy, raving or berserk are reported.
- **Tavern and library.** From 15 citizens the planner builds a **tavern**
  (tables with chairs, chests for mugs, a tavern zone), and from 40 a
  **library** (bookcases, reading tables, a library zone). They come after
  the hospital in the build order.

Build order now: bedrooms, dining hall, basic workshops, tombs, stockpiles,
hospital, tavern, library, barracks (militant forts), memorials, temple.

## Society, ghosts and the metal industry (step 5)

- **Ghosts.** When there are ghosts, the AI switches on DFHack's `autoslab`,
  which orders a memorial slab engraved for each one, and keeps enough blank
  stone slabs for it. (Rules tab: "Memorial slabs for ghosts".)
- **Metal.** When the fort has fewer than 50 bars of weapon-grade metal
  (steel, iron, bronze, copper) and a smelter, the AI adds DFHack's own
  smelting orders (`orders import library/smelting`) once: they smelt ore
  whenever bars drop below their limits. Co-pilot asks first. (Rules tab:
  "DFHack's smelting orders when metal is low".) No smelter: Needs you.
- **Needs you** (the AI can't do these): empty key offices (manager,
  bookkeeper, broker, chief medical dwarf, sheriff or captain of the guard),
  dwarves starving or parched, and grazing animals without a pasture.

## Set-ups the AI does itself

- **Civilian-alert shelter.** With no civilian-alert burrow, the AI makes a
  burrow named **AI shelter** over the inside of the fort (revealed,
  walkable, not outside, not in a cavern, on the levels where dwarves live)
  and registers it as the alert's burrow. Urgently when a threat can reach
  the dwarves, otherwise when it gets to it. Two tries, then it's on Needs you.
  (Rules tab: "Set up an AI shelter for the alarm".)
- **Pastures.** Grazing animals without a pasture go into a pasture with room
  for them; if none has room, the AI makes a new one on grass near the fort,
  sized for the herd (see [building.md](building.md)). Nowhere: Needs you.
  (Rules tab: "Put grazing animals in a pasture".)
- **Farm plots.** A fort of 7+ gets about 1 farm tile per dwarf of the
  population it is growing toward (as for bedrooms; Maintain: the dwarves it
  has), x2 at Agriculture +100, at least 9 tiles; none at Agriculture -100
  ("Hunt and gather"). Below three quarters of that, the AI lays plots out on
  free soil or muddy floor the fort already has; if that isn't enough and a
  project slot is free, it digs a farm level in a soil layer (see
  [building.md](building.md)). Co-pilot asks only before digging. Nowhere to
  put them (no soil floor and no soil layer to dig): Needs you, with the
  reason. Waits 3 days between tries.
- **Wells.** No well: the AI channels a hole over clean water inside the fort
  and builds one (see [building.md](building.md)); urgently when someone is
  hurt, since the injured drink only water. Co-pilot asks first. Nowhere
  suitable: Needs you, with the reason. Waits 3 days between tries.
- **Footwear mandates.** Shoes in leather (else cloth), socks in cloth, low
  boots in leather, high boots in metal at a forge (the mandate's metal, or
  the best one there are bars for).
- **Linking the AI gate lever stays yours:** only you know which bridge or
  door is the entrance.
