# What the AI learns

The overseer learns three things, all by script and for **no tokens**:

1. **What you don't want**, from how you correct it.
2. **Targets that fit this fort**, by tuning a few of its rules of thumb.
3. **Whether its decisions helped**, by judging them against the fort's numbers.

You can see all of it on the panel: **Culture** tab, then **Shift-V** ("What
the AI has learned"). **Shift-W** there wipes it. The code is in
`brain/learning.py`, `brain/calibrate.py` and `brain/outcomes.py`.

## Learning from you

These count as one signal each against that kind of thing:

| You... | Counts against |
| --- | --- |
| answer No to a co-pilot question | what it asked to do |
| remove a zone named "AI pasture" | making new pastures |
| cancel an order the AI made, with 20+ jobs (and half of it) still to do | that recipe |
| switch off a DFHack tool the AI switched on | switching that tool on |
| move a slider against an AI action within 3 in-game days of it, by 20+ (lower Piety after a temple is started) | that action |
| switch its Rules option off within 3 days of it | that action |

The kinds are things like temples, taverns, memorial halls, gate styles
(gatehouse, fortified...), farm levels, new pastures, sending dwarves away, a
DFHack tool, or one recipe.

**What one signal does:** the AI waits 4 weeks before doing that kind of thing
again (longer for a heavier preference: 6 weeks at 1.5, say, from your other
forts' lessons), and the weights engine
leans away from the matching option. A declined gatehouse pushes the fort's
Defence choice toward another gate style; a declined temple pushes Worship
toward none. The Culture tab's Choices then say "leaning away from ... (you
turned it down)".

**Two of the same kind make a lesson:** the AI no longer does it on its own and
says so in a note ("left to you: temples"). Lessons go into **your memory**,
`logs\player-memory.json`, which all your forts share. A new fort starts with
your lessons at **half weight**: it waits before doing that kind of thing, but
doesn't refuse it.

**What undoes it:**

- a co-pilot **Yes** for that kind of thing takes one signal back (and drops a
  lesson inherited from your other forts, for this fort);
- moving the slider behind it **the other way by 40 or more** (raising Piety
  after you'd turned temples down): the AI forgets it, since you changed your
  mind;
- a single signal fades after an in-game year with no new one; lessons stay
  until you wipe them.

**Never held back:** what keeps the fort alive or safe: drink and food orders,
containers, hospital supplies, the civilian alert and shelter, the gates and
squads in a fight, furnishing projects already started, the population cap,
noble mandates, and bedroom, dining, workshop, storage and tomb levels. A
preference about one of these is still recorded and shown ("still done when the
fort needs it"), but the AI does it when needed.

## Targets that tune themselves

Each value moves slowly, within fixed bounds, on evidence gathered over a
window of in-game days. After a change it waits before it moves again.

| Value | Starts at | Bounds | Goes up when | Goes down when | Window, wait |
| --- | --- | --- | --- | --- | --- |
| Drink kept per dwarf | 10 | 6 to 20 | drink fell below 2 per dwarf: +2 | it fell below 60% of the target but never below 2 per dwarf: -1 | 14 days, 28 |
| Meals kept per dwarf | 8 | 5 to 16 | the same with meals | the same | 14 days, 28 |
| Farm tiles per dwarf | 1.0 | 0.5 to 2.0 | food ran thin with the farms at full size: x1.15 | 8+ food plants per dwarf all the time and 25%+ of adults idle, farms at full size: x0.9 | 28 days, 28 |
| Room in a new pasture | 1.25x the herd | 1.1 to 2.0 | a new pasture was needed again within a season of the last: +0.15 | the AI's pastures stood more than half empty for a season: -0.05 | 84 days, 84 |

A value the AI strategist has set itself (its `adjust`) isn't tuned: its call
wins. The strategist sees the tuned values in each review and may undo them.

## The outcome log

Decisions that should show in the fort's numbers open an entry: what was done,
by whom (planner, strategist, weights engine, self-tuning), which number should
move which way, the number before, and the day to judge it.

| Decision | Judged on | After |
| --- | --- | --- |
| Brewing / cooking orders | drink / meals per dwarf, up | 14 days |
| Block orders for idle hands | idle adults %, down | 7 days |
| Farm plots / a farm level | food plants per dwarf, up | 56 / 84 days |
| A new pasture; putting grazers in one | grazers without a pasture, down | 7 / 3 days |
| Bedroom level | free beds, up | 28 days |
| Dining hall, tavern, temple, library, memorial | unhappy %, down | 28 to 56 days |
| Hospital | dwarves needing care, down | 28 days |
| A change of style (halls, finish, statues, materials, worship) | happy %, up | 84 days |
| A raised drink, meal or farm target | that stock, up | 28 to 56 days |
| A bigger pasture margin | grazers without a pasture, down | 84 days |

One entry per kind is open at a time, so ten brewing orders are judged once.
The verdict is **helped**, **no effect** or **hurt** (the number moved at least
a set amount, e.g. 1 drink per dwarf or 3 points of unhappiness), or
**unclear** when a siege came, the population changed by more than a quarter,
many dwarves died, or the number couldn't be read. When one verdict holds for
60% of at least 3 judged entries of a kind, the page shows it as a line, e.g.
"brewing orders: helped (4 of 5)".

Defence (gates, squads) isn't judged yet: its test is the next siege, which
can be a long way off. Showing the outcome lessons to the strategist comes with
milestone 7.

## Wiping

Shift-W on the learned view asks which:

- **This fort only:** its preferences, lessons, tuned values and outcome log.
  Lessons it shared with your other forts come out of your memory; lessons
  your other forts made stay theirs, and this fort stops inheriting them.
- **This fort and the lessons shared by all your forts:** the same, and your
  memory file is emptied.

The overseer clears it at its next check (the panel only records the press).

## Where it's kept

- In the fort's memory, as its "knowledge" (since 0.31 each kind of memory has
  its own key in the save, `ai-overseer/mem/knowledge`, with a copy in
  `logs\forts\<fort>\memory.json`; see `brain/memstore.py`):
  `learning`, `calibration` and `outcomes`.
- Your lessons: `logs\player-memory.json`.
- A copy for the panel, written into the save (display only), only when it
  changes and only in autopilot.
- Every signal, lesson, tuned value and verdict is also written to the fort's
  journal, `logs\forts\<fort>\journal.jsonl` (kinds `learned`, `calibration`,
  `outcome`).
- Since 0.31 verdicts compare the timeline's averages (the week before a
  decision against its last days), and the learned view also shows the
  season's trends, notable places and the latest of the fort's story.

## Since 0.97.1: one fort, ageing lessons, durable wipes

- **One fort, whatever folder.** Your memory on the PC (`logs/player-memory.json`) knows a fort by its line: `line:<world>#<site>`. Its autosaves and copies are the same fort, so it never inherits its own lessons back. Entries from before 0.97.1 for the same site are folded away the first time the fort runs.
- **Lessons age.** Each fort's entry carries the real date its fort last confirmed it. Past 30 days it counts half, past 60 a quarter, then not at all.
- **Inheritance is a lean.** Another fort's lesson arrives at half its weight, aged, and at most 1.5: the AI waits and leans away, but never "leaves it to you" until this fort turns it down itself.
- **Wipes stick.** "Wipe all forts" stamps the PC file. Every other fort honours the stamp once, the next time it runs, by forgetting its own lessons instead of writing them back.
- **Forgiving sticks.** Moving a slider the other way forgets a lesson in this fort and stops it being inherited again here.
- **Dry runs** read the PC file and never write it.
- **The strategist's adjustments** last a season from when it set them, unless it sets them again; the planner's own (self-tuned) values come back after.
- An autosave's logs go to its own world's folder for that site.
- (0.99.1) The real-day token cap counts every fort and save on this PC (`logs/tokens-today.json`), so a reload or another fort no longer starts the day again.
