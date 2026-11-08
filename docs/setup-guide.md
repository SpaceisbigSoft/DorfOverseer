# Setup guide

How to set the AI Overseer up on a fresh Windows PC: one fort first, then
several side by side. Budget about 30 minutes for the first fort.

This is for your own use only. The strategist's Claude sign-in must not be
shared in a program given to others.

## What you need

| What | Version | Notes |
| --- | --- | --- |
| Dwarf Fortress | 53.16 (Steam) | the game |
| DFHack | 53.16-r3 or newer (Steam, "DFHack") | Start the game from DFHack's Steam entry. Petitions to stay and citizenship are answered through DF's standing orders, which need a DFHack **newer than 53.16-r3**. On 53.16-r3 they wait for you, or show as a Needs you line. |
| Python | 3.10 or newer | from python.org; tick "Add python.exe to PATH" in the installer |
| `lupa` | any | optional: only for the Lua tests (`pip install lupa`) |
| `claude-agent-sdk` or `anthropic` | any | optional: only for the AI strategist (`--ai`); see [ai-setup.md](ai-setup.md) |

The overseer, the keeper and the local planner need only Python's standard
library. `requirements.txt` lists the optional packages and what each is for.

## 1. Put the project in place

Copy (or unpack, or clone) the project to `C:\Users\<you>\Documents\DF-AI`.
The rest of this guide calls that folder `DF-AI`. It holds `lua\`, `brain\`,
`tests\`, `docs\` and `config.example.json`.

Then, in a new PowerShell window:

```
cd $HOME\Documents\DF-AI
python --version
pip install -r requirements.txt
```

`python --version` should print `Python 3.10` or later. If it opens the
Microsoft Store instead, re-run the Python installer, choose Modify, and tick
"Add python.exe to PATH".

`requirements.txt` holds only comments. To install the optional packages,
name them: `pip install lupa` for the Lua tests, and `pip install
claude-agent-sdk` or `pip install anthropic` for the strategist.

## 2. Point DFHack at the AI's scripts

DFHack finds scripts through `script-paths.txt` in the **game's**
`dfhack-config` folder. For the Steam game that is
`...\steamapps\common\Dwarf Fortress\dfhack-config\script-paths.txt`. Add one
line, with a leading `+`, naming this project's `lua` folder:

```
+C:\Users\<you>\Documents\DF-AI\lua
```

Each copy of the game has its own `script-paths.txt`, pointing at its own
`DF-AI...\lua` (see "Several forts" below).

DFHack reads the file only at start-up:
1. Quit Dwarf Fortress completely.
2. Start it again from the **DFHack** entry in Steam.
3. Load a fort.
4. In the DFHack launcher (the DFHack logo, or the backtick key), type `ai-ping`.

It answers with one line of JSON: `{"bridge":"ai-ping", "bridge_version": ...,
"citizens": <your fort's count>, ...}`. If DFHack says the command isn't found,
check the path in `script-paths.txt` and restart the game.

**The two keys.** **Ctrl-Shift-O** opens the AI's window and **Ctrl-Shift-H**
halts the AI. They are set in the game's `dfhack-config\init\dfhack.init`. If
they don't work, add these lines there and restart the game:

```
keybinding add Ctrl-Shift-O@dwarfmode gui/ai-overseer
keybinding add Ctrl-Shift-H "ai-bridge halt"
```

The on-screen panel (`ai-overlay`) comes up by itself. Hide it with
`overlay disable ai-overlay.status`.

## 3. config.json

Copy `config.example.json` to `config.json` in `DF-AI` and edit it. JSON
allows no comments, and backslashes are written twice. `config.json` is
gitignored: it holds this PC's paths. Put an API key, if you use one, in
`.env`, never here.

| Key | Needed | What it is |
| --- | --- | --- |
| `dfhack_run` | **yes** | Full path to `dfhack-run.exe`, e.g. `D:\\SteamLibrary\\steamapps\\common\\DFHack\\hack\\dfhack-run.exe` for Steam's DFHack. It must be the `.exe` itself, never a `.bat` wrapper. |
| `timeout_s` | no (10) | Seconds a bridge call may take before it counts as failed (the full report has its own 30 s). |
| `dfhack_port` | no (5000) | The DFHack port of **this folder's** game. Set it when more than one game runs: 5001, 5002 and so on. The brain passes it to dfhack-run (as `DFHACK_PORT`) and to any game it starts. |
| `df_launch` | for `--revive` | How the keeper starts this game again when it closes: the path to that game's `Dwarf Fortress.exe` (a copy), or a `steam://rungameid/...` link to DFHack's Steam entry (the Steam game). Without it, `--revive` only says it can't. |
| `df_save_dir` | no | The save folder, when it isn't where the tools look by themselves. Set it for a portable copy, e.g. `D:\\DF-B\\save`. By default the tools look in `%APPDATA%\Bay 12 Games\Dwarf Fortress\save`, then the game's own `save`. |
| `strategist_backend` | no (`auto`) | `subscription` (your Pro/Max sign-in), `api` (a key in `.env`) or `auto` (the key if there is one). The example sets `subscription`, so a key in Windows' environment never turns reviews into paid calls. |
| `strategist_model`, `strategist_model_events`, `strategist_model_top` | no | The models for routine reviews, event reviews and the longest thinking. The defaults are in `brain/backends.py`. |

## 4. Check the connection

With the game running and a fort loaded:

```
python brain\check_connection.py
python brain\selftest.py
```

The first prints the DFHack and DF versions, your citizen count and the
in-game year, then the round-trip time. The second checks the bridge inside
the game, changing nothing. It should pass, with at most a few warnings, such
as "no farm spot" on a crowded map.

## 5. First run

```
python brain\overseer.py
```

This is a dry run: each cycle it prints what it would do, and the window's
panel shows the same. Nothing in the game changes. When you're happy, let it
act:

```
python brain\overseer.py --autopilot
```

To leave it running unattended, use the keeper. The keeper:
- runs the overseer on autopilot and unpauses the game;
- saves each season and copies the save once a real day (`backups\`);
- takes popups off;
- restarts the overseer if it stops;
- runs the health check.

```
python brain\keeper.py --revive --preset "Garden fort"
```

`--revive` (with `df_launch` set) starts the game again if it closes, and
loads the fort's newest save from the title screen. `--preset` applies one of
the six built-in presets once, before the first cycle: War-hold, Monastery,
Merchant city, Hermit hold, Deep mine or Garden fort. It can also apply a
preset you saved with Shift-S. Leave `--preset` out to keep the window's
sliders. Add `--ai` only if tokens may be spent.

Only one keeper runs per folder (`logs\keeper.lock`). A hand-run
`overseer.py --autopilot` refuses while a keeper runs there.

Read `logs\unattended.log` (the keeper) and `logs\forts\<fort>\` (each fort's
journal, report and states). `python brain\soak_report.py` sums up the last
12 hours.

## 6. Several forts side by side (the six-preset layout)

Each fort needs its own copy of Dwarf Fortress, DFHack port, save folder and
DF-AI folder. This is the layout used for the six-preset test:

| Fort | Game folder | Port | Brain folder | Preset |
| --- | --- | --- | --- | --- |
| A | the Steam game (`...\steamapps\common\Dwarf Fortress`) | 5000 | `Documents\DF-AI` | War-hold |
| B | `D:\DF-B` | 5001 | `Documents\DF-AI-B` | Monastery |
| C | `D:\DF-C` | 5002 | `Documents\DF-AI-C` | Merchant city |
| D | `D:\DF-D` | 5003 | `Documents\DF-AI-D` | Hermit hold |
| E | `D:\DF-E` | 5004 | `Documents\DF-AI-E` | Deep mine |
| F | `D:\DF-F` | 5005 | `Documents\DF-AI-F` | Garden fort |

For each copy (B to F):

1. Copy the Steam game's folder to `D:\DF-x`.
2. Make the copy portable: create `prefs\portable.txt`, so its saves go to `D:\DF-x\save`. Keep `steam_appid.txt` beside `Dwarf Fortress.exe`, so a double-click starts it with DFHack through `dfhooks_dfhack.ini`.
3. Give it its own DFHack port in `D:\DF-x\dfhack-config\remote-server.json`, e.g. `"port": 5001`.
4. Copy `DF-AI` to `Documents\DF-AI-x`, and point `D:\DF-x\dfhack-config\script-paths.txt` at `+C:\Users\<you>\Documents\DF-AI-x\lua`. Every game must use its own folder's scripts.
5. In `DF-AI-x\config.json`, set:
   ```
   "dfhack_port": 5001,
   "df_launch": "D:\\DF-B\\Dwarf Fortress.exe",
   "df_save_dir": "D:\\DF-B\\save"
   ```
   Change the numbers and letters for each copy. `dfhack_run` stays the Steam DFHack's `dfhack-run.exe`.
6. Copy the same embark save into every game's save folder, so the forts start from one embark.

**start-keepers.bat** starts one keeper per folder, each in its own window.
It isn't part of the repo: keep it on your desktop or in `Documents`. A
version for the layout above:

```
@echo off
set DOCS=%USERPROFILE%\Documents
start "A War-hold"      /D "%DOCS%\DF-AI"   cmd /k python brain\keeper.py --revive --preset "War-hold"
start "B Monastery"     /D "%DOCS%\DF-AI-B" cmd /k python brain\keeper.py --revive --preset "Monastery"
start "C Merchant city" /D "%DOCS%\DF-AI-C" cmd /k python brain\keeper.py --revive --preset "Merchant city"
start "D Hermit hold"   /D "%DOCS%\DF-AI-D" cmd /k python brain\keeper.py --revive --preset "Hermit hold"
start "E Deep mine"     /D "%DOCS%\DF-AI-E" cmd /k python brain\keeper.py --revive --preset "Deep mine"
start "F Garden fort"   /D "%DOCS%\DF-AI-F" cmd /k python brain\keeper.py --revive --preset "Garden fort"
```

With `--revive`, a keeper starts its own game about 15 seconds after it
finds nothing on its port. So either start all six games first and load
their forts, or let the keepers start them. Never both: two copies of one
game fight over the port, and the window you play in gets no bridge.

Each keeper keeps its own lock, pin (the world and site it started with),
logs and backups. `python brain\scorecard.py`, run from any of the folders,
compares the forts beside it at one game season. See
[two-forts.md](two-forts.md) for how the ports and revive keep the games
apart.

## 7. Updating the code

A new version goes into **every** DF-AI folder (A to F). Then touch the Lua
files, so the running games load them:

```
(Get-ChildItem lua\*.lua, lua\gui\*.lua) | ForEach-Object { $_.LastWriteTime = Get-Date }
```

DFHack reloads a script only when its own file changes. The bridge, builder,
military and society are hubs that load their parts, so a change to a part
alone wouldn't load until the game restarts. Lua changes take effect at the
next call. Python changes need the keepers restarted.

## 8. Tests (no game needed)

```
python tests\run_all.py
```

Every test runs in parallel, in about 30 seconds. The Lua tests need `lupa`.
`python tests\run_all.py builder` runs the files whose names match. More is
in [testing.md](testing.md).

## Optional: editing the code

Open `DF-AI.code-workspace` in VS Code and install the recommended
extensions (Lua by sumneko, Python by Microsoft). `.luarc.json` tells the Lua
extension about DFHack's globals.
