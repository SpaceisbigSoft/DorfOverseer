# Watching and controlling the AI (Phase 5)

## The on-screen panel

A small **AI Overseer** panel sits on the right side of the main fort screen
(a DFHack overlay; it's on by default). It shows:

- the mode (Advisor, Co-pilot, Autopilot) and whether the AI is acting,
  watching only, halted, or not running at all
- the building project under way, e.g. `#3 bedrooms level44 dig 40/99`
- the last 5 actions and why each was taken (in Advisor mode or a dry run:
  what it would do)
- up to 2 notes, e.g. "drink is low but there are no plants to brew"
- in Co-pilot mode, its questions, each with **[Yes]** and **[No]** to click
- a **[Halt]** / **[Resume]** button

Move it with `gui/overlay` (DFHack's overlay editor), or hide it with
`overlay disable ai-overlay.status` in the DFHack launcher.

## The kill switch: Ctrl-Shift-H

Press **Ctrl-Shift-H** (works on the main fort screen and while a DFHack
window is open), or click [Halt], and the AI stops changing anything, at once:

- the game side refuses every action that would change the fort, whatever
  the overseer sends (only the on-screen panel keeps updating)
- the overseer keeps watching and planning, so you can see what it *would* do
- it's saved with the fort, so a halted AI stays halted after a reload

Press it again to resume. The STOP file in the project folder still works too.
The key is set up in `dfhack-config\init\dfhack.init`; it takes effect after
restarting Dwarf Fortress.

## Modes

Set on the panel's **AI & tokens** tab (Ctrl-Shift-O):

| Mode | What the AI does on its own | What it asks you first |
| --- | --- | --- |
| Advisor | nothing; it only suggests | (shows suggestions) |
| Co-pilot | routine work: orders, helper tools, the civilian alert, finishing levels it started | new levels, cancelling a level or order, switching a tool off |
| Autopilot | everything | nothing |

The overseer must still be started with `--autopilot` before it acts at all;
without it, every mode only watches.

In Co-pilot, answer in the panel: **Yes** and it acts within seconds (even
while paused); **No** and it won't ask about that again for 7 in-game days.
It also learns from the No: it holds back on that kind of thing for 4 weeks,
and after a second No it leaves it to you (see below).

## Needs you

Some things only you can do: set up the civilian-alert burrow, link the "AI
gate" lever, give squads a uniform, build a workshop the AI can't (a glass
furnace for a mood), dig a well, engrave a memorial slab for a ghost... When
the AI needs one of these, it says so in three places:

- the on-screen panel: a purple "Needs you" line with the first one
- the panel's **Needs you** tab (Ctrl-Shift-O): the full list
- the overseer's window: lines starting `NEEDS YOU:`

An item disappears at the AI's next check once it's done.

## What the AI has learned

Ctrl-Shift-O, **Culture** tab, then **Shift-V**: what you don't want (from your
No answers, the AI pastures you removed, the AI orders you cancelled, tools you
switched off, sliders you moved right after it acted), the targets it tuned to
this fort, and how its decisions turned out. **Shift-W** wipes it, for this fort
or for all your forts; Shift-V again goes back to the culture. Details:
[learning.md](learning.md).

## The Rules tab

Ctrl-Shift-O, **Rules** tab: what the AI may build and do on its own.

- **The fort should:** *Expand toward the Growth target* (the default) or
  *Maintain: keep it as it is*. Expand digs bedrooms up to 20 ahead of the
  population, toward the target, and builds new halls. Maintain holds the
  population where it was when you chose it (no new migrants; births only
  replace losses), keeps everything running, and builds no new memorials,
  temples or libraries. Sending dwarves away (Extreme low Growth) is asked
  first in Co-pilot mode.
- **Set the population cap from Growth:** the AI sets DF's population cap
  (which decides how many migrants come) to the Growth target, or to the
  held size in Maintain. It lasts for the session; the AI sets it again
  after a restart.

The **Growth** slider (Society tab) sets the target population:

| Slider | What the AI does |
| --- | --- |
| Extreme on, below 0 | the fort shrinks: no newcomers, and one dwarf is sent away every 28 days at -100 (56 at -50...), never below 7. The least skilled adult who isn't a noble or a soldier leaves, the way DFHack's emigration tool sends dwarves off |
| -100 (low) | about 25 dwarves |
| 0 (average) | about 100 |
| +100 (high) | about 250 |
| Extreme on, above 0 | no population cap at all |

Without Extreme it goes in a straight line between those (-50 = 63,
+50 = 175). The window shows what the value you pick means. Maintain wins
over Growth: a fort set to Maintain never shrinks or grows.

- **Memorial halls for slain beasts:** one for every beast, at most one per
  season (the default), at most one per year, or never. A memorial that has
  to wait is shown as a note.
- **Levels the AI may build when needed:** tombs, hospital, tavern, library,
  barracks, temple. Switch one off and the AI moves on to its next need.
  Bedrooms, the dining hall, basic workshops and stockpiles are always built
  when missing.
- **Order barrels, pots, bags, hospital supplies:** on by default. Off, the
  shortages are still reported.
- **Build the workshop a strange mood needs:** on by default. Off, the AI
  says which workshop to build instead.

Changes are saved with the fort and apply at the AI's next check.

## Token use

With `--ai`, the panel's AI & tokens tab shows tokens saved, used today and
used in total, and the on-screen panel shows the bank's balance.

## The AI's memory lives in the save

Everything the overseer remembers about a fort (cooldowns, culture history,
eras, the token bank, your No answers, its daily numbers, its map of what it
built and where things happened, the fort's story) is stored inside the game's
save, one key per kind of memory, with a copy in `logs\forts\<fort>\`. Load an
older save and the AI remembers exactly what it knew then. A dry run never
writes into the save.

## Save before each new level

Also on the AI & tokens tab: **Save the game before each new level**. With it
on, the overseer saves the game (like DFHack's `quicksave`), and starts the new
level on its next cycle, after the save. If anything goes wrong you can load
the save from just before.

## What the seven graded sliders do (0.96)

Each acts across its whole range (the numbers live in `brain/planner.py`, beside
`stone_tidiness`; the window's "Now:" line shows them for your fort):

| Slider | Low end | 0 | High end |
| --- | --- | --- | --- |
| Mining | -100: only needed levels (no library, archery, garden, barracks, temple or jail level); -50: no ore veins (metal by trade) | veins while bars < 50, 40 tiles; quarries of 30 | +100: veins while bars < 100, 80 tiles; quarries of 60 |
| Surface | -50: 1 woodcutter, a gatherer fewer | 2 woodcutters, 3 gatherers | +50: one more of each; the keep from +50 |
| Justice | -100: no jail | a jail from 15 dwarves, a cell per 25 | +100: from 8 dwarves, a cell per 12 (up to 8, the bridge's limit) |
| Deference | -100: no rooms, mandates ignored; -50: a bedroom only | all four rooms | +50: suites dug early, even in a young fort |
| Greed | -100: gives 1.35x in trade | 1.2x | +100: 1.05x; from +50 gems and precious metal stay home |
| Engineering | -100: the cistern from 60 dwarves; -150: none | from 30 | +100: from 15; from +50, 2 spare mechanisms per 50 |
| Outsiders | -30: guests asked about; -50: no residents, hunters, mercenaries or new citizens; tavern x0.71 at -100 | guests accepted | tavern x1.41 at +100 |

Outsiders acts through DF's petition standing orders, which DFHack 53.16-r3
can't reach yet: until a newer DFHack, only the tavern's size shows it.

## The Rules tab, untangled (0.97)

Each switch now does what its label says, and only that:

- **Raise and fill squads**: filling squads and making new ones (new squads used to follow "Appoint", which said nothing about them).
- **Close gates and link levers**: only closing and opening the entrances in danger, and linking the AI gate lever. Mapping the entrances, walls, doors and traps go on when it's off (they used to stop too).
- **Wall entrances, trap behind**: walling wide entrances to a gate, and the traps behind each gate.
- **Appoint the six officials**: manager, bookkeeper, broker, chief medical dwarf, sheriff, captain of the guard. Nothing else.
- **DF pop cap from Growth/Maintain**: Growth (or Maintain) is the one population target; this switch only says whether DF's own cap is set to it. Growth's "Now:" line says which.
- **Smelt ore when metal runs low**: the AI's own smelting orders (it used to be DFHack's smelting library, which current bridges no longer use, so it did nothing).
- **The Temple level** and **Maintain** now also cover temples asked for in petitions (left to you); guildhalls go on.
- The strategist's new levels obey the level switches, Maintain and Mining -100, as the planner's do (`planner.level_refused`).

## Presets (0.99)

Six ready-made fort characters, in opposite pairs, each with the Rules choices that go with it (anything a preset doesn't name stays as you had it). Loading one sets every slider; a saved preset now keeps its Rules choices too.

| Preset | Character | Rules it brings |
| --- | --- | --- |
| War-hold | Militarism and Fortification at Extreme, Caution, Engineering, Justice harsh, closed to outsiders, plain and cramped | squads attack all, raise, fill and train; close gates, wall entrances; no garden |
| Monastery | Piety at Extreme, Welfare, Grandeur, open to guests; few soldiers, lenient, generous | squads never attack; no barracks, archery or jail |
| Merchant city | Trade at Extreme, Greed, Outsiders (welcoming), Craft, Growth, Surface | visitors in; petition halls built |
| Hermit hold | Outsiders at Extreme closed, no trade, small, careful, underground, nobles ignored | no visitors; petition halls left to you; entrances walled |
| Deep mine | Mining and Depth at Extreme, all underground, Engineering, Industry, bold | water works; no garden |
| Garden fort | Farming and Animals at Extreme, Surface, Welfare, Grandeur; shallow mining | pastures; no archery |

The exit test (`tests/test_strategist.py`, "opposite forts"): on the same fort, each pair differs in at least 3 style choices and 6 sliders' "Now:" lines, and in what it builds first or its Rules. The in-game version (two copies of one save, a game year each, `brain/scenario.py`) is for the next chat.
