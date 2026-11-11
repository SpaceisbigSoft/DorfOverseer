# Building and digging (Phase 3)

The AI grows the fort the way most players do: **one level at a time around a
central staircase.** It decides *what* to build (bedrooms, a dining hall,
storage, workshops) and how big; the bridge decides *where*, checks every tile,
and does the work in phases with DFHack's Quickfort.

## Who decides what

| Decision | Made by |
| --- | --- |
| Which kind of level, and how many rooms | Local planner (rules), or the strategist |
| Room size | The **Room size** trait (-50 or lower: 2x2 rooms, -50 to 50: 3x3, 50 or higher: 4x4) |
| How close together | The **Spacing** trait: the length of the new corridor from the fort to a new level (-100: 0 to 8 tiles, 0: 0 to 25, +100: 10 to 25), and at +50 or higher two tiles of rock between rooms instead of one. Each siege pulls it 15 tighter (up to 45) |
| Where it goes | The bridge, never the AI: it never sends coordinates |
| Exact layout | The bridge's layout generator (`lua/ai-layouts.lua`) |

## Where a new level goes

1. **Find the staircases:** the stair columns with the most stair tiles on the
   levels where your dwarves live. The 5 most used are tried, most used first.
2. **For each staircase, try levels it already passes through**, nearest your
   dwarves first:
   - **centred on the stairs**, if the level around them is still solid rock;
   - otherwise **beside the stairs**: a corridor leads from the stairs (first
     through your existing rooms or halls, up to 15 tiles, then through new
     rock, up to 25 tiles) to where the new level fits. The new level only
     touches your existing fort where that corridor joins it.
3. **Then levels just below the staircase's bottom** (the stairs are extended
   down), never more than 15 levels.

**With the master plan (bridge 0.32+, see `brain/masterplan.py`):** each new
level comes with a hint: its district's band of elevations, the directions to
grow in, and the main stair (the spine). A first pass tries only the band, on
the spine first, for at most 40% of the search time, and extends only the
spine, by at most 3 levels. If it finds nothing, the search above runs as
always, with its own full time, skipping what was already tried. So a plan
never stops a level that would have been built without one.

**Corridor grammar (bridge 0.33+):** the hint also says how wide the corridor
is (1 to 3 tiles; the first and last tiles stay 1 wide, as doorways) and
whether it runs straight or as a dog-leg (corridors of 4+ tiles step 2 tiles
sideways half way). The door rule: "open" puts no door where the corridor
leaves the fort, "doored" one (the fort's style decides, as before),
"fortified" one there and a second where the corridor meets the level. A wide
or jogging corridor may brush a hall or the hub (the same open space) but is
refused where it would touch a room past its door.
4. **Check every tile** of the new level and corridor, plus a 1-tile border.
   Every tile must be natural rock or soil wall (not built, not dug, not
   designated), and must not be:
   - aquifer (light or heavy)
   - water or magma (any amount)
   - part of a cavern, the magma sea, the underworld, or an adamantine vein
   - open to the sky (surface)
   - warm (heated by nearby magma)
   - inside another AI project's area

   The only exception is right where the corridor joins your fort: there the
   border may be your existing (dry, connected) rooms.

   Tiles to be dug also must not have water, magma or an aquifer **directly
   above** them. DF treats such stone as "damp" and cancels digging there
   itself.
5. **Check the staircase extension** too (each new stair tile and its 8
   neighbours, same rules).
6. The first site that passes everything is used. The search stops after about
   4 seconds; if nothing passes, nothing is dug, and the planner gets a note
   saying why.

This reads the real map, including hidden tiles, so the AI won't dig into an
aquifer or a cavern you haven't discovered yet. Quickfort itself does not check
for these.

## Phases

| Phase | What happens | Moves on when |
| --- | --- | --- |
| `dig` | rooms, corridors and stairs are designated | every tile is dug out |
| `furnish` | doors, beds, tables, workshops, stockpiles, room zones; smoothing designated | everything placed is built (a storage level, with only stockpiles, finishes at once) |
| `decorate` | (only if the style engraves) waits for the smoothing; no longer takes a building slot | smoothing is done, then the halls are engraved |
| `done` | nothing more to do | |

Furniture is placed through DFHack's **buildingplan**, so missing beds or doors
don't make the plan vanish: the buildings wait for materials, and the planner
orders what's missing. The planner turns buildingplan on if it's off.

## Level types

Each is built around a 3x3 hub: centred on the staircase, or at the end of a
corridor from it. The descriptions below are of a level as drawn; since 0.33
each level gets a seeded orientation (as drawn, mirrored east-west, turned so
"east" becomes south, or a quarter turn) and its pillars a seeded rhythm
(every 3 to 6 tiles), so two levels of the same kind needn't look alike.

- **bedrooms**: two corridors (east and west) with rooms on both sides. Each
  room has a door, a bed, and (3x3 or larger) a cabinet and a chest, plus a
  bedroom zone. Up to 32 rooms per level.
- **dining**: a hall east of the hub with tables and chairs and a dining zone.
- **storage**: stockpile rooms for food, stone, wood, furniture, bars and
  blocks, finished goods.
- **workshops**: a corridor of 5x5 rooms, one workshop in each (only the
  workshops the fort is missing).
- **farms** (too few farm tiles and no free soil floor): 5x3 farm plots on
  dug soil; see Farm plots below.
- **hospital** (a fort of 20+ without one): beds along both walls, a table and
  chests for supplies, and a hospital zone. More beds with higher Welfare.
- **tombs** (fewer free tombs than needed): coffins along both walls, each in
  its own tomb zone.
- **tavern** (15+ citizens, no tavern): tables with chairs, chests, a tavern zone.
- **library** (40+ citizens, no library): bookcases, reading tables, a library zone.
- **barracks** (Militarism 50+, no barracks yet): beds with an armor stand
  beside each, weapon racks, and a barracks zone; assign squads to it in game.
- **temple** and **memorial** halls come from the fort's culture; see
  [culture.md](culture.md).

The planner builds, in order of need: bedrooms, a dining hall, basic
workshops, tombs, storage, a hospital, a tavern, a library, barracks,
memorials, a temple. A workshop a strange mood needs comes first of all.

## Limits

- At most **2 unfinished projects** at a time, and the planner starts at most
  one every 5 in-game days.
- Projects only ever dig rock; they never channel, remove floors, or dig up.
- The AI can cancel only its own projects, and only while they're being dug.
  Cancelling removes the dig designations on the project's own tiles (anything
  you designated on those same tiles goes too); dug tiles stay dug, and stairs
  are never removed.
- If designating fails part-way, everything that call designated is taken back.
- Each project saves the exact cells it designated, so later versions of the
  layouts never change what an existing project thinks it dug.
- If the game cancels some designations anyway (for example damp stone found
  while digging): when at most 1 tile in 5 is affected, the level is furnished as
  dug, with those spots left as rock; otherwise the level is cancelled and built
  elsewhere (a memorial hall stays owed).
- If Quickfort is set to marker (blueprint) mode, designations are made but
  dwarves won't dig them; the planner notes this instead of waiting forever.
- Dry run, autopilot and the STOP file work exactly as for everything else.

## Culture

Each new level is built in the fort's style: hall shapes, smoothing and
engraving, statues, doors, signature stone, plus temple and memorial levels.
See [culture.md](culture.md).

## Farm plots

The AI lays out farm plots itself (the planner decides how many tiles; see
[local-planner.md](local-planner.md)). Crops need soil, or stone that water
has muddied.

1. **Existing floor first.** On the levels where most dwarves are, within 20
   tiles of them, it looks for free floor that is soil or muddy and:
   - inside (not open to the sky), not in a cavern, no water or magma on it
   - walkable from where the dwarves are
   - not under a building, stockpile or zone (a soil-floored bedroom or
     dining hall stays what it is), not designated, not in an AI project
   Plots are rectangles from 2x2 to 6x6 (never a 1-wide corridor), no bigger
   than what's still wanted. Each plot is checked with a Quickfort dry run
   first, then placed. No digging, no materials needed.
2. **Then a farm level.** If that isn't enough, and a project slot is free,
   it digs a **farms** level like any other (same site search and safety
   checks), with one more rule: every tile under a plot must be natural
   soil. The level is a field east of the hub with 5x3 plots in two rows
   either side of a walkway, up to 12 plots. It is not smoothed (soil can't
   be). Plots are placed when it is furnished.

DFHack's `autofarm` is switched on once there are plots, so they get crops.

## Wells

With no well, the AI makes one itself. It looks on the levels where most
dwarves are, within 20 tiles of them, for a **natural floor** (built floors
can't be channelled) that is inside, walkable from the dwarves, free (no
building; no zone except a dining or meeting hall, where a well is welcome),
with a **straight open drop to clean water** under it, at most 30 levels:

- water at least 3/7 deep, or any water over a full 7/7 tile
- never in a cavern (the hole would let cavern creatures in), never magma,
  stagnant or salt water, never open to the sky
- never water that fills the space right under the floor: it may be under
  pressure and would flood up through the hole

It prefers a dining or meeting hall, then the middle of the fort on the
busiest level. The spot is channelled (a one-tile project, using a project
slot), and once the hole is dug the well is placed through buildingplan. It
needs a block, a bucket, a mechanism (the AI orders these) and a rope or
chain, which the AI can't order: after 3 days of waiting, Needs you says so.
If the game won't place the well over the hole, the project ends and Needs
you says why; the AI doesn't dig a second hole. Nowhere suitable: Needs you,
with the reasons it found (for example, the only water is in a cavern).

**Far water (0.105.3).** Hammerstirred (2 Nov) had no well in either fort:
its water was all further off than the AI looked. Three paths now reach
further, each still bounded and with the same safety checks:

- *Cavern well by a gallery.* When no fort floor stands over the cavern lake,
  the AI digs a one-tile gallery (up to `cavern_well_gallery` = 80 tiles) on a
  fort level, through solid rock only (no aquifer, water, warm stone or open
  space beside it, rock under it, a wall or floor over it), out to a column
  over the lake round the survey's nearest cavern water; then the usual shaft,
  the stair column beside it and the shaft gate. Nothing moves water. Set it
  to 0 to switch galleries off.
- *The breach (0.105.4 review).* Every cavern well (gallery or not) is dug
  down to the level above the cavern and stops there: the shaft's last level
  and the stair step beside it stay undug until the gate's lever stands and a
  hatch cover and 2 mechanisms are in store. Only then is that level dug, and
  the hatch goes on the opening straight after. A cavern no dwarf has found
  yet is opened only when the Rules tab's "Cavern well into an unfound
  cavern" is "Always", or, at "AI decides" (the default), when the AI
  decides the fort is short of water and has armed soldiers for what comes
  out (never at "Never"): the
  first breach brings cavern creatures and forgotten beasts. The cavern and gallery searches take at most 1.5 s of
  the game's time, and a "no spot" answer is kept until the next water survey
  (or 28 days).
- *Cistern tunnel.* The cistern's tunnel to still water may be up to
  `cistern_tunnel_max` = 70 tiles (30 before); a stagnant pool is still taken
  when it is the only source (it scores worse than fresh water).
- *Shore well.* A pond up to `well_shore_reach` = 60 tiles from a surface gate
  (40 before) gets a well on its bank, searched only round the survey's
  nearest surface water (the 3 nearest ponds at most, one time limit for all).

Each refusal says how far the water was, so the log shows what limited it.

## Pastures

Grazers eat living grass (dead grass doesn't feed them; eaten grass grows
back). Each animal needs about 20000 / its GRAZER value tiles of grass, DF's
own rule of thumb: a cow about 38, a horse 33, a llama 16, a sheep or goat 6.

- **Existing pastures first.** Waiting grazers go into the pasture with the
  most room left (its area minus what the animals already in it need), big
  animals first, and only where they fit.
- **Then a new pasture.** If no pasture has room, the AI makes one on living
  grass near the fort's surface entrances (or the top of the main staircase,
  before the entrances are mapped), within 40 tiles and 2 levels: free grass
  the dwarves can walk to, no water, building or zone, and never within 3
  tiles of an entrance (that's where its gate goes). Nearest grass first, in
  rectangles from 3x3 to 15x15, up to 4 of them. It is sized for the waiting
  herd, +25%, and more at a higher Husbandry (x2 at +100: room for the herd
  to grow). The zones are named "AI pasture", and the waiting animals go in
  straight away.
- Nowhere: Needs you, with the reason. The Rules tab's "Put grazing animals
  in a pasture" switch turns all of this off.

## Not yet

- Grand design above ground: towers, second storeys, surface houses, a walled
  town (left to the future AI agent; the keeper's fixed pieces are below)

## Since 0.98: the plan keeps acting, set pieces, the weighted ladder

- **The weighted ladder.** After the levels a fort needs to live (workshops, storage, bedrooms, dining, tombs, hospital), every optional level whose time has come is scored (`planner.ladder_score`): its old place (jail 9.5, suites 9, tavern 8.5, library 8, barracks 7.5, archery 7, memorial 6.5, temple 6, garden 5.5, great hall 5), plus the sliders that care for it (Militarism +100 adds 2.5 to barracks, Piety +100 adds 3 to the temple, Grandeur +100 adds 2.5 to the great hall ...), plus 2 when dwarves are distracted by the need it meets, plus half the fort's own leanings on those sliders as a tie-breaker. Neutral sliders keep the old order. The notes show the top four scores.
- **Set pieces.** The plan's places kept for a great hall, a temple and memorials are filled by those levels (and shown as built). The great hall is a dining hall of up to 90 tables among the halls, raised in good times once the fort has 60 dwarves and a first dining hall. The inner keep's place (Last Stand) has no builder yet.
- **The plan keeps acting.** A new era's wings take their direction from the layout the engine picks today (and say so when it changed), and a deep fort (Depth +40) reaches each district a level deeper. New levels' corridors follow today's Grandeur, Spacing and Fortification, not the founding ones.

## Construction (0.105.30)

Until 0.105.29 the only constructions the AI placed were bedroom wall repairs
(`repair_rooms`); the keep was refused 130+ times in C and F for want of open
ground, and the gates are hatches over stairs. 0.105.30 adds a fixed,
small vocabulary. Every piece goes through quickfort `build` mode and waits on
buildingplan; finished constructions are map tiles and cost no FPS, so at most
about 100 planned tiles stand at once (one stage at a time).

- **Surface hall** (`lua/ai-builder-halls.lua`, brain `planner_construct._hall_rule`).
  One per fort, a 9x7 footprint with a 7x5 dining interior. `field_hall` by the
  surface farms (Garden fort), `market_hall` 6-15 tiles from the depot and off
  the wagon road (Merchant city). The site is flat open ground under the sky,
  no zone, building or liquid within 2, no channel within 2 (cave-ins), clear
  of every way in and within 30 tiles of one. Stages: `clearing` (fell trees),
  `walls` (a ring, one door toward the way in, glass windows on the long sides
  with Grandeur 40+), `floor` (block floor on soil, Craftsmanship 40+), `roof`
  (z+1 over the interior and windows, with a corner stair while `ROOF_STAIR`),
  `furnish` (3 tables, 3 chairs, a statue with Grandeur 40+), `zone` (a dining
  hall zone), `done`. It waits while the keep is between `clearing` and `roof`,
  but goes ahead when the keep has failed 3 times.
- **The keep** counts blocks first in its material check, and gets a `stair`
  stage before `roof` if its roof jobs turn out to be unreachable.
- **Gate wings** (`ai-gates.lua plan_wings`/`build_wings`, brain
  `planner_gates._wings_rule`): War-hold, once a gatehouse stands. The arms are
  added to the gate's pieces, so removing the gate takes them down.
- **Soil floors** (`ai-builder-rooms.lua floor_soil_rooms`, the project step
  `floor` after `finish`): soil and sand can't be smoothed, so finished halls
  on soil get block floors, at most 60 tiles a call, never under a building,
  stair, door or farm plot.
- **Sealed cavern openings** (gate style `sealed`): the Hermit hold walls small
  cavern openings instead of locking doors on them.
- **Blocks** (`planner_construct._construction_blocks_rule`): the sum of what
  the open pieces still need, plus 10%, ordered as `stone_blocks` (up to 10
  jobs) when the masons have usable stone; the idle-hands cap of 500 does not
  apply.
- **The shelter** leaves out roofed surface tiles (inside but not
  subterranean), so civilians never shelter in a hall outside the gate.

**Reporting.** `lua/ai-constructions.lua survey()` counts finished
constructions by shape, by item (blocks, boulder, log, bar), above and below
ground, the roofed surface tiles, the planned ones waiting, and the AI's own by
registry. It is the report section `constructions` (cached 3 days) and part of
the census. The digest shows it as one line:
`BUILT 40 walls, 70 floors (80% blocks), 60 above ground; 12 waiting | roofed surface 35 | keep roof (9 left), field hall walls (20 left)`.

**Scorecard** (`brain/scorecard.py`, measure keys in brackets):

| Slider | Line | Should win | Should lose |
| --- | --- | --- | --- |
| Surface | constructed tiles above ground (`built_up`) | Garden, Merchant | Deep mine, Hermit |
| Surface | roofed surface tiles (`roofed_up`) | Garden, Merchant | Deep mine, Hermit |
| Fortification | gate walls and wings (`gate_walls`) | War-hold | |
| Fortification | cavern openings walled (`cavern_walls`) | Hermit | |
| Craftsmanship | constructions of blocks, % (`block_pct`) | Merchant, Monastery | |
| Grandeur | soil floors finished (`soil_floors`) | Garden, Monastery | War-hold |

A report without the `constructions` section (an older bridge) reads "no data"
on these lines, not 0. `soil_floors` comes from the survey's `ai.soil_floors`
when it has one, else from the tiles the journal's `floor_rooms` placed.

**Left out on purpose:** towers and spires (no preset has both Verticality and
Surface), roofed gatehouses (the gate finds its lid hatch by the open sky),
surface cottages (dwarves would sleep outside the gate), rebuilding rough rock
walls in blocks, the Merchant's surface tavern (phase 2), second storeys.
