# Two forts side by side (0.105.1)

Two copies of Dwarf Fortress run at once, each with its own DFHack port, save
folder and DF-AI folder, so two forts with different sliders play from the same
embark overnight.

| | Game A (Steam) | Game B (a copy) |
| --- | --- | --- |
| Game folder | `D:\SteamLibrary\steamapps\common\Dwarf Fortress` | `D:\DF-B` |
| Saves | `%APPDATA%\Bay 12 Games\Dwarf Fortress\save` | `D:\DF-B\save` (`prefs\portable.txt`) |
| DFHack port | 5000 | 5001 (`dfhack-config\remote-server.json`) |
| Brain | `Documents\DF-AI` | `Documents\DF-AI-B` |
| config.json | as before | `"dfhack_port": 5001`, `"df_launch": "D:\\DF-B\\Dwarf Fortress.exe"`, `"df_save_dir": "D:\\DF-B\\save"` |
| Started by | Steam (DFHack) | double-click `D:\DF-B\Dwarf Fortress.exe` (`steam_appid.txt` beside it) |

- Game B's DFHack is the same Steam DFHack (`dfhooks_dfhack.ini`); its
  `dfhack-config\script-paths.txt` points at `DF-AI-B\lua`.
- dfhack-run and DFHack's server both take the port from `DFHACK_PORT` first,
  then `dfhack-config\remote-server.json` in the game's folder. The brain sets
  `DFHACK_PORT` from config's `dfhack_port` for every dfhack-run call and for
  a game revive starts.
- Revive closes a hung game by the process listening on its port, never the
  other game; it starts game B's `.exe` in its own folder.
- Each keeper keeps its own pin, lock, logs and backups (its DF-AI folder).
- Code changes go to both DF-AI folders.

## N forts, one preset each (0.105.4)

The same way scales past two: each fort gets its own copy of Dwarf Fortress
(its own game folder, `prefs\portable.txt` and save folder), its own DF-AI
folder (`DF-AI-C`, `DF-AI-D`... with that game's `script-paths.txt` pointing at
its `lua`), its own DFHack port (5002, 5003... in the game's
`remote-server.json` and the folder's `config.json` `"dfhack_port"`) and its
own preset. Copy the same embark save into every game, then start one keeper
per DF-AI folder with `python brain\keeper.py --revive --preset "War-hold"`
(then `"Monastery"`, `"Merchant city"`, `"Hermit hold"`, `"Deep mine"`,
`"Garden fort"`). Before the fort's first cycle the overseer applies the preset
exactly as the window's Load preset does (sliders with Extreme, and the Rules
it carries; the bridge's `apply_preset` action), saves it in the fort's site
data, logs `Preset: NAME applied (...)` and records it in
`logs\keeper-preset.json`. A restart or a revive doesn't apply it again over
changes made in the window afterwards, unless the loaded save shows no preset
at all. An unknown name is refused, and the log names the valid ones.
