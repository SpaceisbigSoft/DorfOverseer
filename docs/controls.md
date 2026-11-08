# Watching and controlling the AI

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

Some things only you can do: answer a citizenship petition (DFHack 53.16-r3
can't), send a Make contact messenger while the trial switch is off, agree to
a residency on DF's petitions screen, answer a meeting the AI can't, give
a strange mood a material the fort can't make or buy... When the AI needs one
of these, it says so in three places:

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

Ctrl-Shift-O, **Rules** tab: what the AI may build and do on its own. Every
control is listed below in the window's order, with its default. Changes are
saved with the fort and apply at the AI's next check.

On/off switches can also be set from outside the game. Put
`logs\rules-request.json`, for example `{"rules": {"open_caverns": true}}`, in
the fort's DF-AI folder. The overseer applies it once, through the bridge's
`set_rules`, and renames it `rules-request.done.json` with the answer. Only
switches whose default is on or off can be set this way, and (0.105.27)
**Dispose of them**, as `{"rules": {"disposal": "dump"}}`
(`store`, `melt`, `dump` or `destroy`).

### The fort

- **The fort should:** *Expand toward the Growth target* (the default) or
  *Maintain: keep it as it is*. Expand digs bedrooms up to 20 ahead of the
  population, toward the target, and builds new halls. Maintain holds the
  population where it was when you chose it: no new migrants, and births only
  replace losses. It keeps everything running, and builds no new memorials,
  temples or libraries. Sending dwarves away (Extreme low Growth) is asked
  first in Co-pilot mode.
- **Memorial halls for slain beasts:** one for every beast, at most one per
  season (the default), at most one per year, or never. A memorial that has
  to wait is shown as a note.
- **DF pop cap from Growth/Maintain** (on): the AI sets DF's population cap,
  which decides how many migrants come, to the Growth target, or to the held
  size under Maintain. It lasts for the session; the AI sets it again after a
  restart.

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

### Levels the AI may build when needed

Tombs (coffins for the dead), Hospital, Tavern, Library, Barracks (militant
forts), Archery range (crossbow squads), Statue gardens (in good times), Jail
(cells for the sheriff) and Temple (devout forts) are all on by default.
Switch one off and the AI moves on to its next need. Bedrooms, the dining
hall, basic workshops and stockpiles are always built when missing.

### Burrows, the world outside and visitors (the right-hand column)

- **Keep the wounded in an "AI hospital" burrow** (on; beside the Hospital
  level, 0.104.168). The patients DF wants treated are kept in a burrow over
  the hospitals and the nearest drink and food, and let out when healed.
  A member who grows very thirsty or hungry is let out at once, and none such
  is moved in. A bedridden patient stays only where the burrow has a well
  (0.105.22). Off: everyone in it is let out at once.
- **Keep a dwarf in a tantrum in an "AI calm" burrow** (on; beside the Jail
  level, 0.104.169). The dwarf goes to a free bedroom away from the patients,
  with drink, until calm. The burrows retire themselves in a fort where
  dwarves in a tantrum are seen outside them 90% of 40+ times: DF doesn't
  hold them to a burrow (0.105.24).
- **Tribute a civilisation asks** (0.105.0): *pay small, refuse large* (the
  default), *always pay* or *always refuse*. It answers a meeting's tribute
  demand.
- **Appoint a messenger, make contact** (on, 0.105.0): a Messenger is
  appointed, and the nearest site not in contact is named for Make contact.
- **Send it by the World screen (trial)** (off, 0.105.24): the AI drives DF's
  World screen to send the messenger itself. It stops at the first step
  nobody has recorded yet, which today is step 4 of 6, logs what it saw and
  shuts the screen. Off, the AI only names the site for you to send.
- **Shut to visitors a while after a theft** (on, 0.105.24): after an
  artifact heist, or a visitor killing a citizen, the tavern, temples,
  library and guildhalls are shut to visitors for 168 days. Residents are
  still welcome, and the hospital is never shut. Only the locations the AI
  shut reopen. Off: no lockout, and one under way is lifted.
- **Shut to visitors when mayor swamped** (on; the Merchant city preset turns
  it off; 0.105.24): the same locations shut for 56 days when 5+ citizens
  can't complain and at least 3 of the mayor's meetings, half or more of
  them, are with visitors. Then they reopen and are looked at afresh. Never
  at Outsiders 100+. A location you shut is never reopened.

### Supplies, care and the fort's works

- **Order barrels, pots, bags, hospital supplies** (on). Off, the shortages
  are still reported.
- **Build the workshop a strange mood needs** (on). Off, the AI says which
  workshop to build instead. Either way, it frees, makes or asks for the
  mood's materials (0.105.24).
- **Memorial slabs for ghosts (autoslab)** (on): DFHack's autoslab, and blank
  slabs for it.
- **Smelt ore when metal runs low** (on): the AI's own smelting orders.
- **Set up an "AI shelter" for the alarm** (on): the burrow the civilian
  alert sends dwarves to. It is remade over the whole fort before each alarm,
  and since 0.105.23 it keeps away from entrances that aren't shut.
- **Put grazing animals in a pasture** (on).
- **Give trinkets to dwarves who want to own** (on): a free trinket for a
  dwarf who badly wants something of their own.
- **Build water works (a cistern, ...)** (on), with its own switches beside
  it (all on, 0.105.0):
  - **A moat from the river at the gate**, only where a river is found;
  - **Magma workshops** (forge, smelter, glass);
  - **Muddy a stone farm level with water**.
- **Cavern well into an unfound cavern** (off, 0.105.4). A cavern well may
  break into a cavern layer the dwarves haven't found yet, and the first
  breach can bring forgotten beasts. Off, a cavern well goes only to a cavern
  already found.
- **Send away vampires found among the dwarves** (on): at most one dwarf a
  game week.
- **Let useful visitors stay (and become citizens)** (on): residency
  petitions are answered by the Outsiders slider. Citizenship petitions are
  shown as a Needs you line with counts; DFHack 53.16-r3 can't answer them.
- **Clear the alert icons:** *old ones; dangers kept a week* (the default),
  *all once a day old*, or *none (yours)*. These are the icons down the left
  of the screen.
- **Build the temples and guildhalls asked for** (on): petitions agreed by
  the fort's leanings, then built and dedicated.
- **Camera (when the keeper runs unattended):** *follows what happens, tours
  between* (the default), *tours the fort only*, or *off (the view is
  yours)*. It runs only while the keeper runs unattended, and never moves
  while you are using the game.
  - **Camera pace:** *normal (20-40 s a place)*, *slow* or *fast*.

### Military

The AI makes and sends squads itself (see [military.md](military.md)).

- **Send squads against:** *ordinary enemies, not great beasts* (the
  default), *everything that can reach us*, or *never (alert and gate only)*.
- **Raise and fill squads** (on): filling squads and making new ones.
- **Put idle squads on training** (on).
- **Close gates and link levers** (on): only closing and opening the
  entrances in danger, and linking the AI's gate levers.
- **Put doors on entrances that have none** (on).
- **Wall entrances, trap behind** (on): walling wide entrances down to a
  gate, and the traps behind each gate.
- **Make weapons, armour and helms** (on).
- **Appoint the six officials** (on): manager, bookkeeper, broker, chief
  medical dwarf, sheriff, captain of the guard.
- **When hiding, squads wait in the shelter** (on, 0.105.0): while the AI
  hides from a great danger, the squads wait with the civilians.
- **Weapon to make:** *battle axes* (the default), *spears* or *maces*.
- **Invaders caught in cages:** *keep them caged* (the default), *release
  outside (asks you)* or *put to death (asks you)*. Only keeping can be done
  safely through DFHack; the other two are said, and the prisoners are kept.
- **Lock werebeasts in at the full moon** (on): a werebeast citizen is locked
  in a cell round the full moon.
- **Seal a cavern a beast is in** (on): the way down is locked while a beast
  the squads can't take is in a cavern.

### Forbidden items and junk (beside Military, 0.105.27)

The game forbids items itself (the lock symbol): used ammo, the dead's
belongings, and everything it dumps. These say what the AI does with them.
Nothing near danger, during a siege, in a sealed cavern, on the cistern's
tiles, an artifact or a living citizen's own is ever touched.

- **Dispose of them** (`disposal`): each choice does everything the ones
  above it do.
  - *store what is useful* (`store`): unforbids useful items (the dead's
    after burial, used ammo, enemy metal gear, cloth, leather, gems, coins)
    so the haulers store them.
  - *store, melt surplus metal* (`melt`): also marks surplus and worn metal
    weapons and armour for melting at a smelter (never masterworks).
  - *store, melt, dump the junk* (`dump`): also marks junk (worn clothes,
    rags, rotten and non-metal enemy items) for a garbage dump, and makes a
    dump zone when there is none: outside, or in a small room dug near the
    entrance for a closed fort (Hermit hold, or Outsiders or Surface at -50
    or lower).
  - *all, and empty a full dump* (`destroy`, the default): also has DFHack
    remove what piles up in the dump past a limit.
- **Also items you forbade** (`disposal_player_items`, off): an item
  forbidden for no reason the game gives is taken to be yours and left
  alone; on, the AI treats it like the rest.
- **Keep invaders' gear (no melting)** (`keep_enemy_gear`, off): enemy
  weapons and armour are stored, never melted. The War-hold preset turns it
  on.

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

Each acts across its whole range (the numbers live in `PLANNER_CONFIG`,
`brain/planner_config.py`, and in helpers such as `stone_tidiness` in
`brain/planner_building.py` and `mining_plan` in `brain/planner_core.py`; the
window's "Now:" line shows them for your fort):

| Slider | Low end | 0 | High end |
| --- | --- | --- | --- |
| Mining | -100: only needed levels (no library, archery, garden, barracks, temple or jail level); -50: no ore veins (metal by trade) | veins while bars < 50, 40 tiles; quarries of 30 | +100: veins while bars < 100, 80 tiles; quarries of 60 |
| Surface | -50: 1 woodcutter, a gatherer fewer | 2 woodcutters, 3 gatherers | +50: one more of each; the keep from +50 |
| Justice | -100: no jail | a jail from 15 dwarves, a cell per 25 | +100: from 8 dwarves, a cell per 12 (up to 8, the bridge's limit) |
| Deference | -100: no rooms, mandates ignored; -50: a bedroom only | all four rooms | +50: suites dug early, even in a young fort |
| Greed | -100: gives 1.35x in trade | 1.2x | +100: 1.05x; from +50 gems and precious metal stay home |
| Engineering | -100: the cistern from 60 dwarves; -150: none | from 30 | +100: from 15; from +50, 2 spare mechanisms per 50 |
| Outsiders | -30: guests asked about; -50: no residents, hunters, mercenaries or new citizens; tavern x0.71 at -100 | guests accepted | tavern x1.41 at +100 |

Outsiders also answers residency petitions (0.105.9: declined in batches when
closed, the visitors who left cleared, welcoming forts told to agree on DF's
petitions screen) and, at -50 or lower, shuts the tavern, temples, library and
guildhalls to visitors (0.105.12). DF's petition standing orders themselves
need a DFHack newer than 53.16-r3.

## What a mature fort keeps building, and which petitions it agrees (0.104.161)

A fort that already has its first tavern, library, hospital, barracks, temple
and jail keeps adding halls as it grows. A kind its sliders lean toward comes
in settled times (established, fed, watered, safe, not strained), at most one
of a kind a season and 6 in the fort's life; a kind they don't lean toward
waits for good times (which need Grandeur or Craft above 0). The level
switches on the Rules tab still hold.

| Kind | Wanted (capped at 4; jail cells at 24) | Only from |
| --- | --- | --- |
| Tavern, library, hospital, barracks | as before (by citizens, or soldiers for barracks) | |
| Archery range | one per 40 soldiers x 2^(Militarism/100) | Militarism +50, a crossbow squad |
| Temple (to all gods: grand from Piety +100) | one per 100 dwarves x 2^(Piety/100) | Piety +50 |
| Jail cells (a prison) | one per 25 dwarves x 2^(Justice/100) | Justice +50, a sheriff or captain of the guard |

Temple and guildhall petitions are declined when the fort's leaning for them is
-35 or lower: a temple's is Piety + Welfare/4; a guildhall's is Craft +
Industry + Trade/2 + Welfare/4, less half of Militarism above +50. War-hold
declines both, Monastery agrees to both. A declined petition makes no promise
(an agreed hall left unbuilt is what upsets the petitioners), and prayer is
still met by the temple to all gods the fort raises when many pray to gods no
temple serves.

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
| War-hold | Militarism and Fortification at Extreme, Caution, Engineering, Justice harsh, closed to outsiders, plain and cramped | squads attack all, raise, fill and train; close gates, wall entrances; no garden; invaders' gear kept |
| Monastery | Piety at Extreme, Welfare, Grandeur, open to guests; few soldiers, lenient, generous | squads never attack; no barracks, archery or jail |
| Merchant city | Trade at Extreme, Greed, Outsiders (welcoming), Craft, Growth, Surface | visitors in; petition halls built |
| Hermit hold | Outsiders at Extreme closed, no trade, small, careful, underground, nobles ignored | no visitors; petition halls left to you; entrances walled |
| Deep mine | Mining and Depth at Extreme, all underground, Engineering, Industry, bold | water works; no garden |
| Garden fort | Farming and Animals at Extreme, Surface, Welfare, Grandeur; shallow mining | pastures; no archery |

The exit test (`tests/test_strategist.py`, "opposite forts"): on the same fort, each pair differs in at least 3 style choices and 6 sliders' "Now:" lines, and in what it builds first or its Rules. The in-game version (two copies of one save, a game year each, `brain/scenario.py`) is for the next chat.
