# Fortress culture

Every fort develops its own way of building. Your trait sliders set its
character, and what happens to the fort shifts it over time. The AI then digs,
furnishes and decorates every new level in that style. The panel's **Culture**
tab (Ctrl-Shift-O) shows the current style, its written guide, and the fort's
eras.

## From sliders to style: the weights engine

Each style choice is a **decision area** with a few options. Every option has an
affinity (-1 to +1) for some sliders, and an option's score is the sliders times
those affinities, plus the fort's history, plus its quirks. The best score wins.
The areas, options and numbers live in `brain/choices.json` (data, easy to tune);
the scoring is `brain/weights.py`.

| Area | Options | Sliders that weigh most |
| --- | --- | --- |
| Halls and rooms | square, rounded, pillared | Grandeur, Fortification, Welfare, Craftsmanship |
| Finish | rough, smoothed floors, floors and walls, engraved | Grandeur, Welfare, Craftsmanship |
| Statues | 0 to 4 per hall | Grandeur, Craftsmanship, Piety |
| Materials | plentiful, dark, pale, warm, cool, most valuable stone; stone by purpose (dark doors and racks, warm tables and chairs, pale coffins and statues, cool bookcases); wood where it will do (while the fort has wood to spare; beds and bins are always wood) | Greed, Hostility, Piety, Welfare, Craftsmanship, Surface, Agriculture |
| Defence | plain doorway, narrow door, two doors, gatehouse, grand doors | Fortification, Caution, Engineering, Grandeur |
| Level doors | open, a door on each level | Fortification, Caution, Hospitality |
| Worship | none, shrine, grand temple | Piety, Welfare, Hostility |
| Layout pattern | grid, rings, branching, stacked | Industriousness, Fortification, Mining, Verticality (used from milestone 4) |

Spacing and Room size act directly, not through the engine.

What you turn down also counts: a declined or undone gate style or temple
leans its area away from that option (0.15 per signal, at most 0.45), shown as
"leaning away from ... (you turned it down)". See [learning.md](learning.md).

Two things keep forts individual but steady:

- **Close calls** (runner-up within 0.15; 0.08 before 0.95) are settled by a number seeded from
  the fort, so two forts with the same sliders differ a little, but a reload
  never changes a choice.
- **Choices stick:** once made, a choice stays until another option beats it by
  0.15, so nudging a slider doesn't flip the fort's style.

The **Culture** tab lists each area's choice and the two or three sliders (or
history) that pushed it most, e.g. "Defence: Two doors, one behind the other -
Fortification +80, 3 sieges". The AI strategist sees the same list and may
overrule a choice with a reason, shown as [AI] with its reason; that holds only
until you move the sliders behind it.

## How history shapes it

| What happens | Effect |
| --- | --- |
| A siege | pushes Defence toward two doors, Level doors toward doors, Materials toward dark stone (up to 4 sieges); -15 Spacing each (up to -45) |
| A great beast is slain | pushes Halls, Finish and Statues toward the grand options (up to 3), and a memorial hall named after it |
| Citizens die | pushes Worship slightly toward a shrine |

Since 0.95 these also push the sliders the engine reads (each capped): a siege
+20 Fortification (up to +60), a slain beast +10 Grandeur (up to +40), every 5
citizen deaths +5 Piety (up to +25). They show in a choice's "why" as "its
history (Piety +10)".

## The fort's own leanings and the site's (0.95, brain/leanings.py)

So that two forts with the same sliders still build differently:

- **Its own leaning**: when the AI first keeps a fort's memory, each trait gets
  a small offset (-15 to +15) drawn from the fort's seed, kept in the save.
  Militarism and Growth never lean: they are your targets.
- **The site's**: read from each full report: rich ore +10 Craft, precious
  metal +10 Greed, magma +5 Craft and +5 Engineering, running water +10
  Engineering, a cavern close below or already worked +10 Caution, goblins in
  the world +10 Fortification (+15 at war), the elves' tree quota +10 Mining
  (stone over wood), human traders +5 Outsiders. At most 20 on one trait.

Both lean **only the style engine** (the close calls above): your soldier
share, population target, reserves and every other direct effect stay what
you set. The window shows them under the selected slider ("This fort leans
+21: own +11, the caverns +10 (style only)"); the Culture tab names them in
each choice's why. At default sliders the top two options of every area now
sit within the close-call band (0.15; the defaults' head start cut to 0.1), so
the seed and the leanings decide: over 300 seeds a default fort takes 180 or
so different styles (one before 0.95), the plain default still the most common.

## Quirks (earned, never chosen)

A fort earns a quirk when its sliders lean far one way for a season and the
right things happen to it. Nothing is picked in the panel. Once earned, a quirk
stays until a much stronger opposite holds (usually for a year). At most 4 at
once, and at most one new one per season. Scripts check them every cycle (no
tokens); the AI never grants or removes one. The Culture tab shows each quirk,
when and why it was earned, what it does, and what would make it fade.

| Quirk | Earned when | Lost when | What it does |
| --- | --- | --- | --- |
| Stonebound | Craftsmanship 50+ and Greed 30+, with more stone than wood, for a season | wood 3x the stone, or Craftsmanship -50 or lower, for a year | rock pots instead of wooden barrels; never picks wooden furniture |
| Restless | 3 new styles (eras) in 2 years | no new style for 3 years | choices follow the sliders at once; close calls go either way |
| Traditionalist | no new style for 5 years and Caution 30+ (for a season) | 2 new styles in a year | choices change only when the sliders push hard the other way |

Restless and Traditionalist exclude each other. More quirks arrive with the
systems they bend (see the roadmap).

## Eras

When the style changes, because you moved a slider or history pushed it, a new
era starts, e.g. "Dark Engraved Pillared era". Levels built in each era keep
that era's look, so an old fort shows its history. The last 12 eras are kept.

## What the AI builds with it

- **Rounded halls:** dining halls, temples, storage and workshop rooms lose
  their corners. Bedrooms stay square, since beds sit in the corners.
- **Pillared halls:** rock pillars left standing along the walkways of big halls.
- **Statues:** along the free row of dining halls, along the far wall of
  temples, and around the centre of memorials.
- **Smoothing** is designated as soon as a level is furnished. It covers only the
  level's own new floors and the rock walls around them, never your existing
  rooms and never floors where furniture or a workshop will stand.
- **Engraving** follows once smoothing is done (it needs smooth stone). A
  level waiting for engravers no longer takes up a building slot.
- **Temples:** a hall with a temple zone open to all gods.
- **Memorial halls:** a round 9x9 hall with a statue at its centre, always
  smoothed and engraved, with a meeting zone named "Hall of <beast>".
- **Furniture** that projects are waiting for is ordered in the signature stone
  (beds stay wooden).
- **Entrances** are walled down to a gate in the fort's own style (the first
  match wins):

  | Gate | When | What gets built |
  | --- | --- | --- |
  | Gatehouse | Fortification 100+ and Engineering 50+ | a 1-tile gap with a door, a second door behind it, up to 3 cage traps in the passage behind |
  | Fortified | Fortification 50+, or 2+ sieges in its history | a 1-tile gap with two doors in a row |
  | Grand | Grandeur 100+ | a 2-tile gap with 2 doors, statues flanking it on the inside |
  | Narrow | Caution 50+ | a 1-tile gap with one door |
  | Plain | otherwise | a 2-tile gap with doors (1 tile into a cavern) |

Walls go up first. DF only builds a door with a wall right beside it, so the
doors follow once the walls are built: the next entrance scans see a narrow
gap between built walls and put the doors in. A stockpile in the opening is
moved by the AI first: what's left of it clear of the opening keeps its
settings, or, if too little is left, the same stockpile goes on free floor
nearby.

  The style is picked when each entrance is built, so a fort that lives
  through sieges builds its later gates heavier than its first ones.

## The written style guide

The overseer writes a short guide from the style ("Grand pillared halls,
smoothed and richly engraved; 4 statues in every hall. Furniture in dark stone
(obsidian)..."). With `--ai`, the strategist may rewrite it and refine the
style (hall shape, finish, statues, stone, doors, temple), always within the
options above. It cannot dig anything just by changing the style.

## Where it's kept

- The overseer keeps the history with the fort's chronicle (the save's
  `ai-overseer/mem/chronicle`, copied to `logs\forts\<fort>\memory.json`).
- A copy goes into the save (display only) so the panel can show it, and is
  updated only when something changes, only in autopilot.
