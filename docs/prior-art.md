# Prior art: what earlier projects teach us

## df-ai (BenLubar)

The best-known "Dwarf Fortress plays itself" project: a DFHack plugin in C++, about 29,000
lines. Source: https://github.com/BenLubar/df-ai. Last commit October 2022, before DF's Steam
release, so it **will not run on DF 53**. Its design is still the best guide we have.

### How it is built

One `AI` object owns five managers, each with its own update timer:

| Manager | Job | How often |
| --- | --- | --- |
| Population | citizens, nobles, jobs, military, crimes, pets, the dead, cages, locations, trade | every 25 ticks, but only **one** of 10 sub-tasks per call, round-robin |
| Plan | digging and building rooms from blueprints | every 240 ticks |
| Stocks | counts items, queues manager orders to keep targets | own timer |
| Camera | follows interesting units (for viewers) | every tick + every 2000 ticks |
| Trade | caravans and the depot | inside Population's cycle |

Plus: a death watch and an announcement watcher every tick, enemy tagging every 1200 ticks.

### Ideas worth copying

1. **Spread the work across ticks.** Population does one of ten checks each time it runs, so
   no single frame pays for everything. Our reflex layer should do the same to protect FPS.
2. **Rooms from data, not code.** The fort layout lives in JSON: a floor plan
   (`plans/generic01.json`) plus room templates (bedroom, barracks, depot...). The plan says which
   rooms go outdoors, which go off corridors, and min/max counts per room type (for example
   bedrooms 120 to 300, depot exactly 1). Our trait sliders can change exactly these numbers:
   Fort size scales the counts, Surface vs underground moves rooms between the outdoor and
   underground lists.
3. **A priority list drives the plan.** `plan_priorities` is an ordered list of actions (dig,
   finish rooms, start ore search, dig the next cavern outpost...). Our planner's goal list is
   the same idea, with the sliders reordering it.
4. **Delegate labor.** df-ai simply enables DFHack's `autolabor` (configurable to
   `labormanager`) instead of writing its own. We should do the same.
5. **Settings in a JSON file** (`dfhack-config/df-ai.json`), including a log file and a
   "lockstep" mode that runs the game as fast as possible for testing.

### Where we go further

- df-ai is rules only; it cannot explain itself or adapt its strategy. We add the planner
  weights from the trait panel and an LLM strategist that writes down its reasons.
- df-ai only handles fresh embarks (or its own saves). We want to take over existing forts,
  like your 194-citizen one, which means reading the fort as it is instead of assuming our layout.
- df-ai is a compiled C++ plugin that must be rebuilt for every DFHack release, which is a big
  part of why it died. We stay in Lua + Python, which keeps working across DF updates far more often.

## DFHack's own automation tools

Already in DFHack and maintained alongside it: `autolabor`, `autobutcher`, `autochop`,
`autofarm`, `seedwatch`, `nestboxes`, `tailor`, `autoclothing`, `suspendmanager`, plus
`quickfort` and the Dreamfort blueprint set. Each one handles a narrow job well.
**Our AI's job is to configure and orchestrate them**, deciding targets and turning them on and
off, rather than re-implementing them. See `dfhack-notes.md` section 5.
