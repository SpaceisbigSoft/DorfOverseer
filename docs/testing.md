# Testing and measuring the AI (Phase 6)

## 1. Tests without the game

```
python tests\run_all.py
```

Runs every test (planner, building, culture, strategist, overseer loop, the
in-game panel's Lua, metrics, replay). Nothing touches the game and no tokens
are spent. The Lua tests need `pip install lupa`; without it they're skipped.

## 2. Self-test inside the game

With a fort loaded:

```
python brain\selftest.py
```

Checks the bridge in the running game without changing anything: versions
(including whether the game has the current `ai-bridge.lua`), the fort report
and how long it takes, every report section, the AI's summary, map and memory
readers, the event watcher, that bad actions are refused, and a building
**dry run** (finds a site, digs nothing). Each line says PASS, WARN or FAIL.
Safe on any save and while the overseer is running. Run it after a DF or
DFHack update.

## 3. Scenario runs: let a test fort play and measure it

A run plays the loaded fort day by day for as long as you ask, and records
the fort's numbers each day. **Use a copy of a test save**: the run plays it
for real. Don't run `brain\overseer.py` at the same time.

```
python brain\scenario.py prepare --name "AI Run A"
```

copies `saves\AI Test Save` into the game's save folder as "AI Run A". Load it
in DF (Continue Playing), then:

```
python brain\scenario.py run --mode planner --days 84 --label planner-a
```

| Mode | Who runs the fort |
| --- | --- |
| `planner` | the local planner on autopilot (no tokens) |
| `ai` | planner + AI strategist (spends tokens from the bank, as normal) |
| `baseline` | DFHack's automation tools only (autochop, autobutcher, seedwatch, nestboxes, tailor, autofarm, autoclothing, suspendmanager, buildingplan), no AI |
| `none` | nobody: the dwarves on their own |

`--years 0.5` works instead of `--days` (336 days = a year). The game advances
exactly one day at a time; when DF pauses itself for an announcement the run
carries on, and if a popup needs a click it tells you. Scenario runs always use
Autopilot (nobody is there to answer Co-pilot questions). Ctrl-C stops the run
and still writes the summary. Runs only start on saves whose folder name
contains "test" or starts with "AI Run", unless you add `--yes`.

Every 7 days it prints a line like

```
  day 28/84 (14 Slate 149): 196 dwarves, 3.1% unhappy, 22.4% idle, wealth 17120300, fps 41
```

Each run goes in `logs\runs\<date-time>-<label>\`:

| File | What's in it |
| --- | --- |
| `metrics.csv` | one row per day; opens in Excel |
| `days.jsonl` | each day's numbers, events and the AI's decisions (for replay) |
| `decisions.jsonl` | the overseer's journal for this run only |
| `summary.json` | the whole run in one set of numbers |
| `run.json` | mode, save, start date, bridge version |

### What's measured

Each day: population (adults, idle adults %), unhappy and happy %, dwarves
needing medical care, fort wealth, drink and meals per dwarf, citizen deaths,
migrants, threats able to reach the dwarves, whether the civilian alert is
on, building levels open and finished, AI actions taken, tokens used, FPS,
and how long the fort report took to build.

The summary adds: days survived and whether the fort fell, start/end/lowest
population, total deaths, wealth change %, average and worst unhappiness,
average idle %, food and drink at the end, days with a reachable threat,
levels built, AI actions, tokens and average FPS.

## 4. Comparing runs (against the DFHack-only baseline)

The fair comparison is several runs **from the same starting save**, one per
mode. For example, three fresh copies:

```
python brain\scenario.py prepare --name "AI Run baseline"
   (load it)  python brain\scenario.py run --mode baseline --days 168 --label baseline
python brain\scenario.py prepare --name "AI Run planner"
   (load it)  python brain\scenario.py run --mode planner --days 168 --label planner
python brain\scenario.py prepare --name "AI Run ai"
   (load it)  python brain\scenario.py run --mode ai --days 168 --label ai
python brain\scenario.py compare
```

`compare` prints one column per run (the latest 4, or the runs you name) and
marks the better value on each line with `*`. Dwarf Fortress is random, so a
single run of each is a hint, not proof; a handful each is better.

## 5. Does the overseer slow the game?

```
python brain\scenario.py fps --seconds 30
```

Runs the game twice for the same time, once checked every 10 s and once every
2 s like the overseer, and compares FPS. It also times one full fort report,
which the game pauses for; the overseer makes one per in-game day. The panel
updates and FPS of every scenario run are also in its `metrics.csv`.

## 6. Replay: what happened, and what did the AI do about it?

```
python brain\replay.py                  the latest run
python brain\replay.py planner          a run whose name contains "planner"
python brain\replay.py --journal        your normal games (the latest logs\forts\<fort>\journal.jsonl)
python brain\replay.py --list           every recorded run
python brain\replay.py planner --all    everything at once, e.g. to save to a file
```

One day per screen: the fort's numbers, the events (deaths, arrivals,
invasions), and each AI decision with its reason and whether it worked.
Enter = next day, `b` = back, a number = jump to that day, `/word` = next day
mentioning that word (e.g. `/died`, `/bedrooms`), `q` = quit.
