# DFHack reference notes

What we learned from DFHack's own docs and source, limited to what this project uses.
Checked against the DFHack `develop` branch on 2026-10-19; installed version is 53.16-r3.
Anything marked **(verify in-game)** may differ slightly in the released version.

## 1. Talking to the game from outside

There are two ways for the Python brain to reach the game. Both use DFHack's
remote server: protobuf messages over TCP on `127.0.0.1:5000`.

| Route | How | Good for |
| --- | --- | --- |
| `dfhack-run` | Run `dfhack-run.exe <command> <args>` as a subprocess; it prints the command's output | Prototyping. Any DFHack command or script works, including ours |
| Remote RPC client | Connect to port 5000 directly (Python lib: dfhack-client-python) | Later, when we need speed: no process start-up per call |

**Where dfhack-run lives (Steam build):** `steamapps\common\DFHack\hack\dfhack-run.exe`.
It connects over the network, so it works from any folder.

**Server settings:** `dfhack-config/remote-server.json`
- `port` (default 5000). The `DFHACK_PORT` environment variable overrides it.
- `allow_remote` (default false). Keep it false: only programs on your own PC can connect.

**Built-in RPC methods** (from `library/RemoteTools.cpp`): `RunCommand` (what dfhack-run uses),
`RunLua`, `GetVersion`, `GetDFVersion`, `GetWorldInfo`, `ListUnits`, `ListSquads`,
`SetUnitLabors`, `ListMaterials`, `ListEnums`, `ListJobSkills`.

**RunLua catch:** it only calls functions in Lua *modules* named `rpc.*` (or `*-rpc`), and
modules are looked up in `hack/lua/` inside the DFHack install. That folder belongs to Steam
and may be overwritten by updates. **Decision for now:** call our own *scripts* through
`RunCommand` / `dfhack-run` and have them print one line of JSON. Revisit RunLua later.

**No push notifications.** The remote API can't notify us of changes; the brain must poll.
In-game events (deaths, new units, job completion) can be caught by our Lua side with
`eventful` and queued until the brain asks.

## 2. Where our scripts live

DFHack searches these folders for scripts, in order:

1. `dfhack-config/scripts`
2. `save/<world>/scripts` (only when that save is loaded)
3. `hack/scripts`
4. scripts folders inside installed mods

**Custom paths:** `dfhack-config/script-paths.txt`. A line starting with `+` adds a folder that
is searched *before* the defaults. DFHack's docs recommend this for development: point it at
the project's `lua` folder and edits take effect immediately, with no copying.
The file is read only at startup, so restart DF after changing it.

```
+C:\Users\<you>\Documents\DF-AI\lua
```

**For release (Phase 7):** package as a mod with a `scripts_modactive/` folder. DFHack adds it
to the search path automatically when the mod is active in the loaded world.

**Script header:** DFHack scripts start with `--@ module = true` when other scripts may
`reqscript()` them. Scripts are run by name: `ai-ping.lua` runs as `ai-ping`.

## 3. Lua API we will use

| Need | API |
| --- | --- |
| Versions | `dfhack.getDFHackVersion()`, `dfhack.getDFVersion()` |
| Is a game loaded? | `dfhack.isWorldLoaded()`, `dfhack.isMapLoaded()` |
| Citizens | `dfhack.units.getCitizens([exclude_residents[, include_insane]])` |
| Date | `df.global.cur_year`, `df.global.cur_year_tick` |
| JSON | `local json = require('json')`; `json.encode(data, {pretty=false})`, `json.decode(text)`, `json.encode_file` / `json.decode_file` |
| Save AI state in the fort's save | `dfhack.persistent.saveSiteData(key, table)` / `getSiteData(key, default)` (written when the game saves; survives retire/unretire) |
| World-wide state | `dfhack.persistent.saveWorldData` / `getWorldData` |
| Global config (not per-save) | a JSON file under `dfhack-config/` |
| Run other DFHack commands | `dfhack.run_command(...)` |
| Repeat every N ticks | `repeat-util` module |
| Game events | `eventful` plugin (unit death, new unit, job completed, invasion, ...) |

## 4. In-game UI (for the trait panel, Phase 4b)

From `gui.widgets` in the Lua API docs:

- **`Slider`**: mouse-draggable; `num_stops` sets how many notch positions it has,
  `get_idx_fn` reads the current notch, `on_change` fires when the handle moves.
  The parent owns the value.
- **`RangeSlider`**: two handles (min and max). Not needed for our traits.
- **`ToggleHotkeyLabel`**: On/Off toggle, On shown in green. Use for the Extreme checkbox.
- **`EditField`**: text entry with an `on_char` validator, so we can accept only digits and `-`.
- **`ZScreen`**: the window class DFHack tools use; it lets the game keep running behind it.

Plan: `Slider` with 21 stops (-100 to +100 in steps of 10), plus an `EditField` for exact values.
DFHack maintainers note sliders feel best with few stops, so 201 stops is a bad idea.

## 5. DFHack tools the AI can drive

All of these exist in current DFHack and carry the `fort` tag. **(verify in-game with `help <name>`)**

| Area | Tools |
| --- | --- |
| Layout and building | `quickfort` (dig/build/place/zone blueprints, ships with the Dreamfort set), `buildingplan`, `stockpiles` |
| Production | `workorder`, `orders` (import/export manager orders as JSON) |
| Labor | `autolabor`: three modes. `legacy` writes labors directly; `modern` (the `labormanager` command) works through DF's work details; `monitor` only warns about starved tasks. Switch with `autolabor mode [legacy\|modern\|monitor]` |
| Food and animals | `autofarm`, `seedwatch`, `autobutcher`, `nestboxes` |
| Wood and clothing | `autochop`, `tailor`, `autoclothing` |
| Jobs | `suspendmanager` (unsuspends jobs that can actually be done) |

Tools marked unavailable in this version include `workflow`, `zone`, `stocks`, `dwarfmonitor`,
`manipulator` and `siege-engine`, so we don't plan on them.

## 6. Open items to check in-game

- [ ] `dfhack-config/script-paths.txt` exists in the DF folder (or create it) and the `+` path loads our scripts
- [ ] `help autolabor` shows the three modes in 53.16-r3
- [ ] Speed of `dfhack-run` round trips (target: under 200 ms for a state snapshot)
- [ ] Where saves live on this PC (see setup guide)
