# DorfOverseer: an AI that runs your Dwarf Fortress fort

An AI overseer runs a Dwarf Fortress fort through DFHack while you watch. A
Python "brain" reads the fort through a Lua bridge inside the game. It plans
with a free local planner and acts in the game. An optional AI strategist,
which spends tokens, can steer it.

You steer it from an in-game window:
- sliders give the fort its character;
- a **Rules** tab says what it may do;
- a **Needs you** tab lists what only you can do.

For your own use only.

**Status:** version 0.105.25, Phase 14 of the plan (`handoff.md` holds the plan, the changelog and where things stand).
- **Seen working in game:**
  - founding a fort from scratch, then digging and furnishing levels from a master plan;
  - labour, farms, wells, pastures, metal and smelting;
  - trade end to end;
  - nobles and offices;
  - squads made, filled and armed;
  - dwarves' needs, locations staffed;
  - the camera director;
  - the keeper's unattended run, relaunching DF when it closes.
- **Built but not yet seen in game:** most combat responses, presets and their signatures, the keep, the cavern well's landing, the messenger, the visitor lockouts and the mood materials.

## Quick start

On a PC that already has Dwarf Fortress 53.16 (Steam), DFHack and Python 3.10 or newer
(the full guide is [docs/setup-guide.md](docs/setup-guide.md)):

1. Put this folder at `Documents\DF-AI`.
2. Point DFHack at its scripts: add the line `+C:\Users\<you>\Documents\DF-AI\lua` to the game's `dfhack-config\script-paths.txt`.
3. Copy `config.example.json` to `config.json` and set `dfhack_run` to your `dfhack-run.exe`.
4. Optional: `pip install -r requirements.txt` (the AI strategist and the Lua tests).
5. Start DF from Steam's DFHack entry, load a fort, then check the connection:
   ```
   python brain\check_connection.py
   ```
6. Watch it plan without acting (a dry run):
   ```
   python brain\overseer.py
   ```
7. Let it run the fort unattended (autopilot, unpauses, saves each season, restarts itself):
   ```
   python brain\keeper.py --revive --preset "War-hold"
   ```

In the game, **Ctrl-Shift-O** opens the control window and **Ctrl-Shift-H** halts every AI action at once.

## Running it

From the DF-AI folder, with the game running and a fort loaded:

| Command | What it does |
| --- | --- |
| `python brain\overseer.py` | A dry run: shows what it would do and changes nothing |
| `python brain\overseer.py --autopilot` | Does it. A hand-run autopilot refuses to start beside a running keeper (they share `logs\keeper.lock`) |
| `python brain\keeper.py` | The long unattended run: autopilot, unpauses, saves each season, takes off popups, restarts the overseer if it stops, and runs the health check daily |
| `... keeper.py --revive` | Also starts DF again if it closes (`df_launch` in `config.json`) and loads the fort's newest save from the title screen |
| `... keeper.py --preset "Monastery"` | Applies a built-in or saved preset once, before the first cycle. A restart doesn't apply it again over your changes |
| `... --ai` | Lets the AI strategist review now and then (spends tokens; set it up with [docs/ai-setup.md](docs/ai-setup.md)) |
| `python brain\selftest.py` | Checks the bridge inside the running game, changing nothing |
| `python brain\health_check.py` | The run check by hand (`--hours N`, `--no-selftest`): self-test, loops, refusals, standing Needs you, FPS, housekeeping |
| `python brain\scorecard.py` | The slider scorecard: compares the forts in the DF-AI folders beside this one (`DF-AI`, `DF-AI-B`, ...) at one game season, writes `logs\scorecard.md` |
| `python brain\show_fort.py` | Prints a readable fort report and saves the raw one to `logs\snapshots\` |
| `python tests\run_all.py` | Every test, no game needed (about 30 s; the Lua tests need `lupa`) |

To stop all AI actions at once:
- press Ctrl-Shift-H in the game, or the panel's [Halt];
- or create a file named `STOP` in this folder.

Each fort's record goes to `logs\forts\<fort>\`:
- every decision and its answer (`journal.jsonl`);
- a copy of the AI's memory;
- the daily numbers;
- the season reports (`report.md`, `states\`).

The keeper's own log is `logs\unattended.log`.

## Six forts at once

Each fort is its own copy of Dwarf Fortress. It gets its own save folder, DFHack port, DF-AI folder and preset:
- `DF-AI` runs the Steam game on port 5000;
- `DF-AI-B` to `DF-AI-F` run copies at `D:\DF-B` to `D:\DF-F` on ports 5001-5005.

The six built-in presets are War-hold, Monastery, Merchant city, Hermit hold, Deep mine and Garden fort. One keeper runs per folder, and `start-keepers.bat` starts all six. See [docs/setup-guide.md](docs/setup-guide.md) and [docs/two-forts.md](docs/two-forts.md).

## In the game

**The on-screen panel** sits on the right of the fort screen and shows:
- the mode and the building project under way;
- the last actions and why each was taken;
- notes, the first Needs you line, and [Halt].

In Co-pilot mode it also shows the AI's questions with Yes/No buttons.

**The control window** opens with Ctrl-Shift-O, or `gui/ai-overseer` in the DFHack launcher. It has these tabs:
- **Temperament, Construction, Economy, Society**: 23 sliders for the fort's character, -100 to +100, each with an Extreme toggle that doubles it. Each slider has a "Now:" line saying what it does in this fort. Presets are loaded and saved here (Shift-S / Shift-L).
- **AI & tokens**: the mode, chosen from these:
  - Advisor suggests only;
  - Co-pilot asks before big moves;
  - Autopilot does everything.

  The tab also holds how often the strategist reviews and how long it thinks, the token cost and an optional daily cap, and "save before each new level".
- **Rules**: what the AI may build and do on its own. It has about 40 switches: the fort goal (Expand or Maintain), the levels it may dig, the hospital and calm burrows, the visitor shut-outs, tribute and the messenger, water works and the cavern well, the camera, the military, prisoners and the caverns. See [docs/controls.md](docs/controls.md).
- **Needs you**: what only you can do, and why the AI couldn't.
- **Culture**: the fort's style, phase, master plan and story. Shift-V shows what the AI has learned; Shift-W wipes it.
- **Camera**: what the camera director showed last. While the keeper runs unattended, the view moves to fights, arrivals, moods and artifacts, and tours the fort in between.

The fort's settings and the AI's memory are saved with the fort. Load an older save and the AI remembers exactly what it knew then.

## What it does

All of this comes from the local planner, with no tokens:
- **Building:** a master plan drawn for the site, then levels dug and furnished to it. These include bedrooms, dining halls, workshops, storage, tombs, a hospital, taverns, temples, a library, barracks and jails, statue gardens and the keep. Every tile is checked for water, aquifers, caverns and the surface first. Each fort builds in its own style. See [docs/building.md](docs/building.md) and [docs/culture.md](docs/culture.md).
- **Supplies:** drink, food, farms and crops, wells and cisterns, smelting, gear, cloth, soap, containers and work orders kept moving. See [docs/local-planner.md](docs/local-planner.md).
- **People:** labour through DF's work details, offices and appointments, needs (trinkets, instruments, lavish meals, temples), the hospital burrow, calm burrows, strange moods' materials, burials and ghosts, and justice.
- **Defence:** the AI maps the entrances and builds gates, doors, hatches on levers, traps and the War-hold's gatehouse. On an alarm it fills a shelter and closes the gates. It makes squads, fills, arms and trains them, sends them at what can reach the dwarves, or hides from a great danger. It also handles fire, thieves, prisoners, werebeasts and the caverns. See [docs/military.md](docs/military.md).
- **The world outside:** trade by the Trade slider (the AI opens the screen, makes the deal and presses Trade), petitions answered by the Outsiders slider, meetings, tribute, the elves' tree quota, and visitors shut out after a theft. A messenger is sent by the World screen; this is a trial, off by default.
- **Learning:** what you decline or undo becomes a lesson, and targets tune themselves to the fort. See [docs/learning.md](docs/learning.md).

## Military

The AI does the military itself:
- **Squads:** it makes squads (with a captain's post when none is free), fills them up to the Militarism slider's share, with a guard of 3 in any fort of 15+ adults, and arms, equips and trains them.
- **Levers:** it builds the gate levers, names them `AI gate N`, links them to the gate and pulls them on an alarm.

The Rules tab sets:
- what squads are sent against;
- whether it raises squads, closes gates or walls entrances;
- which weapon it makes;
- whether squads wait in the shelter when it hides.

See [docs/military.md](docs/military.md).

## Folders

| Folder | What's in it |
| --- | --- |
| `lua/` | The scripts that run inside the game; DFHack loads them from here (`script-paths.txt`). `ai-bridge.lua`, `ai-builder.lua` and `ai-gates.lua` are hubs that load their `ai-bridge-*`, `ai-builder-*` and `ai-gates-*` parts; `gui/ai-overseer.lua` is the window |
| `brain/` | The Python side: `overseer.py` (the loop), `keeper.py` (unattended runs), `planner.py` and the `planner_*.py` rule modules (`PLANNER_CONFIG` in `planner_config.py`), the strategist; one-off scripts in `brain/tools/` |
| `tests/` | Tests that run without the game (`python tests\run_all.py`) |
| `docs/` | Setup, controls, and design notes per area |
| `blueprints/` | Quickfort layouts |
| `logs/`, `backups/` | Run output and save copies (local, not in git) |

## Versions

Dwarf Fortress 53.16 (Steam) on Windows, with DFHack 53.16-r3. Answering residency and citizenship petitions through DF's standing orders needs a DFHack newer than 53.16-r3. On 53.16-r3 they wait for you, or arrive as a Needs you.
