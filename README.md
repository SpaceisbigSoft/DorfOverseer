# DF-AI: Dwarf Fortress Autorun

An AI overseer that runs your fortress in real time through DFHack, while you watch.

**Status:** Phase 1 (the bridge). Python can read a full fort report from the
live game and pause or resume it. No AI decisions yet.
The full plan lives in the "DF AI Overseer — Project To-Do" doc.

## See your fort the way the AI does

With a fort loaded in DF:

```
python brain\show_fort.py
```

Prints a summary (dwarves, moods, stocks, buildings, jobs, threats, recent
announcements) and saves the full report to `logs\snapshots\`.

In-game, the DFHack launcher also accepts `ai-bridge version`, `ai-bridge status`,
`ai-bridge state`, `ai-bridge pause` and `ai-bridge run <ticks>` (1200 ticks = 1 day),
plus `ai-bridge map` (caverns, magma sea and underworld depths) and
`ai-bridge events` (deaths, arrivals and invasions since it was last asked).

The fort report includes:
- dwarves as population summaries (moods, idle and soldier counts, professions)
- stocks, workshops, zones and jobs
- threats grouped by kind, with the layer they're in and whether they can
  actually reach your dwarves
- the map's cavern / magma / underworld layers and which are discovered
- nobles, their mandates, and the civilian alert state

**Design rule:** the AI is an overseer. It sets fort-wide policy and never
manages individual dwarves, so what it reads is summarized the same way.

## The control panel

In fortress mode press **Ctrl-Shift-O** (or type `gui/ai-overseer` in the
DFHack launcher). Tabs:

- **Temperament, Construction, Economy, Society**: 23 personality traits. Each
  has a slider from -100 to +100 (steps of 10) and an **Extreme** toggle that
  doubles it. Click a trait's name to see what its ends mean; Ctrl-E types an
  exact value for the selected trait.
- **AI & tokens**: two sliders, **How often it reviews** (Rare to Often) and
  **How long it thinks** (Short to Long), Normal by default, each with Extreme;
  the estimated token cost per review and per in-game year; an optional
  real-world daily cap; and what the AI may do.

Shift-R resets the selected trait, Shift-X resets all, Shift-S / Shift-L save
and load named presets (shared between forts). Settings save automatically
with the fort and appear in the fort report under "AI SETTINGS".

## Check that the AI can act, safely

With your TEST fort loaded:

```
python brain\tools\try_actions.py
```

Queues a 1-drink brewing order and cancels it, proves four unsafe actions are
refused, then lets exactly one in-game day pass.

What the AI can do so far (all easy to undo):
- **work_order**: queue one of 44 approved recipes (brewing, meals, furniture,
  blocks...), copied from DFHack's own order sets; max 500 per order
- **cancel_work_order**: only orders the AI created itself, never yours
- **tool**: switch 8 DFHack automation tools on or off (not autolabor)
- **civ_alert**: sound or clear the civilian alert (needs a burrow you set up)
- **start_project**: dig and furnish a new level by the main staircase
  (bedrooms, dining hall, storage, workshops). The AI names only the kind and
  size; the game picks a safe spot and checks every tile for aquifers, water,
  caverns and the surface first. See [docs/building.md](docs/building.md).
  `python brain\tools\try_building.py` shows where each kind would go, changing nothing.
- **Culture:** every fort builds in its own style (hall shapes, smoothing and
  engraving, statues, a signature stone, temples, memorial halls for slain
  beasts), set by your sliders and shaped by the fort's history. See the
  panel's Culture tab and [docs/culture.md](docs/culture.md).
- **Learning:** what you decline or undo becomes a preference (two of a kind,
  a lesson shared by all your forts); drink, meal, farm and pasture targets tune
  themselves to the fort; and each decision is judged by the fort's numbers.
  Culture tab, Shift-V. See [docs/learning.md](docs/learning.md).
- **run**: let the game run for a set time, then pause. There is no plain
  "unpause", so the game is never left running unattended.

## Let the overseer run the fort

```
python brain\overseer.py               (dry run: only shows what it would do)
python brain\overseer.py --autopilot   (does it)
```

The local planner keeps drink, food, noble mandates, automation tools and the
civilian alert in hand, once per in-game day, for **no tokens**. Add `--ai` to
let the AI strategist review the fort now and then and steer the planner
(set it up first with [docs/ai-setup.md](docs/ai-setup.md)). Create a file
named `STOP` in this folder to halt all actions at once. Every decision is
logged in the fort's journal (`logs\forts\<fort>\journal.jsonl`). Details: [docs/local-planner.md](docs/local-planner.md).

Tests (no game needed): `python tests\test_planner.py`, `python tests\test_strategist.py`,
`python tests\test_overseer.py`, `python tests\test_culture.py`, `python tests\test_weights.py`,
`python tests\test_learning.py`, and (with `pip install lupa`) `python tests\test_layouts.py`,
`python tests\test_builder.py`, `python tests\test_status.py`.

## Watching and stopping it in the game

- An **AI Overseer panel** on the main fort screen shows what it's doing and
  why, the building project, and (in Co-pilot mode) its questions with Yes/No
  buttons.
- **Ctrl-Shift-H** halts every AI action at once; press again to resume.
- **Modes** (panel, AI & tokens tab): Advisor (suggests only), Co-pilot (asks
  before big moves like new levels), Autopilot.

See [docs/controls.md](docs/controls.md).

## Military

Create your squads in the military screen; the AI fills them, trains them,
sends them at threats that can reach the dwarves, and pulls a lever you name
**AI gate**. See [docs/military.md](docs/military.md).

## Testing and measuring it

- `python tests\run_all.py`: every test, without the game.
- `python brain\selftest.py`: checks the bridge inside the running game,
  changing nothing.
- `python brain\scenario.py`: lets a copy of a test fort play for a set
  number of in-game days (planner, AI, DFHack tools only, or nobody) and
  records population, deaths, wealth, stress, idle time, tokens and FPS each
  day; `compare` puts runs side by side; `fps` measures the overseer's cost.
- `python brain\replay.py`: step through a run (or your games) day by day:
  what happened and what the AI did about it.

See [docs/testing.md](docs/testing.md).

## Token use

`python brain\digest.py` prints the compact fort summary the AI will read
(about 2% of the raw report). See `docs\token-efficiency.md`.

## Folders

| Folder | What's in it |
| --- | --- |
| `lua/` | Scripts that run inside the game. DFHack loads them directly from here (see `docs/setup-guide.md`) |
| `brain/` | The Python side: talks to the game, plans and decides |
| `tests/` | Tests that run without the game (`python tests\run_all.py`) |
| `blueprints/` | Quickfort layouts the AI will build from |
| `saves/` | Backup copies of test fortresses (not tracked in git) |
| `logs/runs/` | Scenario runs: daily numbers, events, decisions, summaries |
| `docs/` | Setup guide, DFHack reference notes, notes on earlier projects |

## Quick check

With Dwarf Fortress running (started from the DFHack entry in Steam):

```
python brain\check_connection.py
```

It should print your DF and DFHack versions, your citizen count and the in-game year.

## Setup

See [docs/setup-guide.md](docs/setup-guide.md).

## Current versions

Dwarf Fortress 53.16 (Steam) with DFHack 53.16-r3, on Windows.
