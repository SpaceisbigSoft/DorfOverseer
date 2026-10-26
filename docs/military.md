# Military and defence (step 4)

The AI runs the fort's squads; it doesn't create them. DFHack can add and
remove soldiers, but it can't appoint a squad's captain, so **create the
squads yourself once** in the military screen (like setting up the burrow
for the civilian alert). From then on the AI:

- **Fills them.** The share of citizens the fort wants as soldiers follows
  the Militarism slider: 5% at -100, 10% at 0, 40% at +100 (in a straight
  line between those). With Extreme on, a positive value goes from 50% up to
  90% (at +100), and a negative one drops below 5%, to none at -100. The AI
  adds up to 5 a
  cycle into open places: dwarves with combat skills first, and among the
  rest those whose best trade skill is lowest, so the legendary crafters stay
  at their workshops. Children, nobles with an office and dwarves in
  hospital care are never drafted. It never touches the captain's place. In
  Co-pilot mode it asks first.
- **Trains them.** Every squad with soldiers sitting "Off duty" goes on
  "Staggered training" (not while a threat is about, and not at Militarism
  -50 or below). It does this once per squad: if you put a squad back off
  duty, the AI leaves it there.
- **Sends them at threats.** When enemies can reach the dwarves, every squad
  with 3 or more soldiers gets a kill order against them, at once, and the
  civilian alert goes on too. Great dangers (forgotten beasts, titans,
  demons) are left alone by default: Rules tab, "Send squads against". When
  no threat is left, the AI clears the orders it gave; your own orders are
  never touched.
- **Closes the gates.** The AI finds the fort's entrances itself: starting
  from where the dwarves are, it maps the inside of the fort and marks every
  opening onto the surface or into a cavern. For each it looks for doors,
  hatches, or a drawbridge with a lever linked to it, and checks that closing
  them really cuts that entrance off. It names them "AI gate 1 (surface)",
  "AI gate 2 (cavern)"... (and the lever "... lever") so you can see them.
  An open entrance up to 3 tiles wide gets doors put across it; a wider one
  (up to 50 tiles) is walled down to a gap with doors, in the fort's own
  gate style (see culture.md): plain, narrow, fortified, gatehouse or
  grand. Co-pilot asks first for both. Before building, the AI checks the
  walls would really close the opening and wouldn't cut part of the fort
  off. Wider than 50 tiles: Needs you. The map is redone weekly, which picks
  up the new doors once the dwarves have built them.
  **Openings with something in them (bridge 0.34+):** when the opening itself
  can't take a gate (stairs, water, a workshop or other building, a bridge no
  lever works), the gate goes on the first clear line up to 3 tiles further
  in, and what's in the opening is left outside it. Stairs whose way out is
  straight down get a hatch on the stair instead. A door with no wall to
  hang on (DF builds a door only beside a wall) first gets a wall built
  across the way in beside it; the door follows once that wall stands. If
  the game still refuses, the reason is shown under Needs you and the AI
  tries again after 2 weeks.
  **Water in an opening (0.34.2+):** the AI looks first. It follows the
  water (on its level and below) and notes how big and deep it is, whether
  it's natural (a river, brook, pool, the aquifer) or made by dwarves
  (a quarter or more of its edge built, or built floors under it); pumps,
  floodgates and wells in or over it are noted as the fort's waterworks, and whether a
  well draws from it. Then, safest first: a dry line within 3 tiles; else
  the dry shore round the water is walled to a gate, the water left
  outside, unless a well or the fort's waterworks use it; else, if only
  deep water (4/7+) joins the opening to the outside, nothing is built:
  walkers don't path through deep water, so the water is the gate (swimmers
  and fliers aside), and the atlas records what was found. Magma is never
  walled near. Only when none of these fits does it go under Needs you,
  with what the AI found.
  **Drawbridges and levers (0.34+):** a drawbridge counts as a gate when any
  lever is linked to it (DF keeps the link on the mechanisms; both sides are
  read). The watcher pulls the lever a dwarf can reach from inside the fort,
  away from the gate (20+ tiles or 4+ levels). If a bridge has none, the
  lever you named "AI gate" is linked to it while it's linked to nothing
  else: the AI makes DF's own link job on the lever with 2 free mechanisms
  (ordering 2 if there are none), and a mechanic does it. A lever the AI
  linked to a watched bridge is pulled by the watcher only, never twice.
  When a threat can reach the dwarves, the civilian alarm sounds and a
  watcher starts, looking 12 times an in-game day: it closes an entrance once
  every citizen is inside, or as soon as the danger is within 12 tiles of
  it, so dwarves out working have time to get back. Doors and hatches are
  locked by DFHack directly, at once; no dwarf has to pull anything. After
  3 quiet checks everything opens again. A lever you named "AI gate"
  yourself, and linked to something the watcher doesn't run, is still
  pulled too.
- **Traps and learning (0.35+, milestone 5b).** Each gate the AI runs gets
  traps just inside it (never outside it, never on the tile right behind a
  door) in the fort's trap style, the engine's Traps area: none, cage
  (Caution), stone-fall (Fortification, Mining) or weapon traps (Hostility,
  Engineering); 2 to 8 per gate by Fortification, Engineering and Caution,
  with mechanisms ordered if there are too few. Not during a threat, and not
  at a gatehouse (it has its cage traps). A new gate style, **drawbridge**
  (Engineering, Caution), walls the opening down to a raising drawbridge and
  places a lever "AI gate lever" where the dwarves are; once both are built
  the AI links them. When a siege ends, every gate the enemy came to is
  judged from where things happened: held (no citizen died there), costly
  (deaths, but twice as many enemies killed there) or failed. The verdicts
  add up per design and lean the Defence and Traps areas toward what held
  ("held 3 of 4 sieges" shows as the reason on the Culture tab), with your
  other forts' verdicts at half weight. Now and then the AI tries a
  promising design it hasn't proved: never at Caution +100, about one year in
  seven at 0, up to one in three at -100, and never one that has failed
  more than it held. Not yet: telling an enemy got *past* a gate line (only
  deaths and kills at it count), and how fast a gate closed.
- **Equips them.** For every soldier without a weapon, body armour or a
  helm (and no spare one in the stockpiles), the AI orders one at a forge,
  in the best weapon-grade metal it has enough bars of (steel, iron, bronze,
  bismuth bronze, copper): weapons first, then mail shirts, then helms, up to
  10 at a time. It waits 3 days after putting squads on training, so the
  soldiers have time to collect the gear that's already there. The weapon is battle axes unless you pick spears or maces on
  the Rules tab. It only does this when a squad has a uniform: without one
  the game doesn't hand gear out, so the AI tells you to set one (military
  screen, Equip). No forge or no bars: it says so.
- **Barracks** are built when the fort has soldiers (or Militarism 50+) and
  no barracks yet.

Responses to an attack (alert, gate, squads) are never held back by the
limit of 3 actions per cycle.

## Rules tab

| Setting | Default |
| --- | --- |
| Send squads against | ordinary enemies, not great beasts (or: everything, never) |
| Fill squads with suitable dwarves | on |
| Put idle squads on training | on |
| Close the entrances when danger comes | on |
| Put doors on entrances that have none | on |
| Wall wide entrances to a gate | on |
| Make weapons, armour and helms | on |
| Weapon to make | battle axes (or spears, maces) |

## Not done yet

Setting up uniforms (do that in the military screen), greaves, gauntlets,
boots and shields, ranged squads and ammunition, and building walls, traps
or a moat (the Fortification trait).
