# Military and defence

The AI runs the fort's squads, and makes them too. When it wants soldiers
and no squad has room, it makes a new squad with a captain's post (`make_squad`
in `lua/ai-military.lua`). Every fort of 15+ adults keeps at least 3 soldiers,
whatever the Militarism slider says. From then on the AI:

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
  off. Wider than 50 tiles (or refused for what stands in it): the AI cuts
  it below instead (0.105.0): the open area behind the opening is followed
  to the stairs that lead down from it into the fort, and each gets a
  hatch, locked by the gate watcher like any other gate. A ramp down, or
  dwarves living in that open area: Needs you. Citizens standing on a ledge
  or a treetop outside no longer make "entrances" of their own. The map is
  redone weekly, which picks up the new doors once the dwarves have built them.
- **Arms the soldiers (0.105.0).** Every empty weapon or shield entry is
  checked against every item of its kind, and the report says why it stays
  empty (`weapon_gaps_why`). The AI mends what it can (a stale claim on a
  soldier's list, a material the fort lacks in a uniform it set, a shield
  entry for its metal melee squads while shields lie spare), makes the
  weapon the entries name when there is none at all, gives each crossbow
  soldier a free quiver, and sets bolts for a crossbow squad that has none.
  When it hides from a great danger, the squads wait in the civilian
  shelter (Rules tab: "When hiding, squads wait in the shelter").
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
  pulled too. If you pull that lever yourself, the AI reads it as its own
  close and opens it again at the all-clear.
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

**No lockdown without end (0.105.3).** Fort B sat behind its one shut hatch
for 2.5 hours for a single thief already inside (1-3 FPS, citizens and
visitors shut out); fort A shut its hatch on 9 citizens for a sneaker who
then hid again. Now:

- A few (`lone_intruder_max`, 2) ordinary enemies already inside the fort
  (the gate scan's map of the inside, `entrances.intruders_inside`), with
  nothing hostile outside: the gates are not shut for them (opened if they
  are), the alarm is held half a day at most, and one armed squad goes after
  them whatever "Send squads against" says. No armed squad: Needs you, once.
- The gate watcher counts only enemies in sight, and opens a gate it shut
  again after half a day with no invader in sight and nothing within 80
  tiles of it (it stays armed: danger shuts it again).
- Nothing hostile in sight and no siege held off at the gates: the AI's gates
  and alarm are lifted after 6 game hours when citizens or 20+ visitors are
  shut out, or after a day when only one or two ordinary enemies were seen.
- The AI's lockdown held 2 days with no new enemy and only 1-2 ordinary ones
  left, the game slow or citizens shut out: lifted until a new enemy comes.
- While the AI's gates are shut, no new pasture assignments (animals led to
  pastures outside piled up 26 jobs at B's gate).
- A siege in sight or a great danger keeps everything as before.

## Rules tab

The military block, on the Army tab beside Rules (0.105.33; all of it is in [controls.md](controls.md)):

| Setting | Default |
| --- | --- |
| Send squads against | ordinary enemies, not great beasts (or: everything that can reach us, never) |
| Raise and fill squads | on |
| Put idle squads on training | on |
| Close gates and link levers | on |
| Put doors on entrances that have none | on |
| Wall entrances, trap behind | on |
| Make weapons, armour and helms | on |
| Appoint the six officials | on |
| When hiding, squads wait in the shelter | on |
| Weapon to make | battle axes (or spears, maces) |
| Invaders caught in cages | keep them caged (release and put to death only ask you) |
| Lock werebeasts in at the full moon | on |
| Seal a cavern a beast is in | on |

## Not done yet

Siege engines and archers' fortifications; missions other than Make contact
(raids, rescues, tribute and artifacts: Phase 13b). The messenger itself is
sent by the World screen only with the Rules trial switch on, and only up to
the step nobody has recorded yet.
