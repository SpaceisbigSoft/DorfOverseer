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

## The messenger (r10)

Round 10 p2 (Phase 13b). No fort had a messenger, so the sender always stopped at "the fort has no
messenger's post" (`lua/ai-mission-send-run.lua` `messenger_home`) and Mission details said "No
messengers available". These notes cover what the DFHack repos show (cloned 22 Nov: df-structures,
dfhack, scripts) and what they don't. DF's own raws are not in those repos and could not be found
online, so the `[POSITION:MESSENGER]` tokens themselves are **not confirmed**. The probe below reads
them in game.

**What the structures show (df-structures):**

- The duty: `entity_position_responsibility` has `DELIVER_MESSAGES` (`df.d_basics.xml`, the last
  item of the enum, after `MAINTAIN_TUNNELS`). A messenger's post is found by that duty, or by the
  code `MESSENGER`.
- Where posts live (`df.entity.xml`, `historical_entity.positions`): `own` (`position`, the
  entity's posts), `site` (`site_position_template`), `conquered_site`, `assignments`
  (`position_profile`, the slots), `next_assignment_id`, plus the `possible_appointable` /
  `possible_elected` / ... evaluation lists. A civilisation therefore keeps **templates** for its
  sites' posts, and a site government (the fort, `plotinfo.group_id`) has its own posts in `own`.
- A post (`entity_position`): `requires_population` (`population_requirement`), `number`
  (`init-value 1`), `appointed_by` / `appointed_by_civ`, `responsibilities`, and flags
  (`entity_position_flags`) including **`HAS_MET_POP_REQ`**, `HAS_BEEN_REPLACED`,
  `HAS_RECEIVED_POSITIONS`, `ACTIVE`.
- The raws (`entity_position_raw`, `historical_entity.entity_raw.positions`): `code`, flags
  (`entity_position_raw_flags`: `SITE`, `ELECTED`, `DUTY_BOUND`, ...), `number`,
  `requires_population`, `appointed_by_str`, `responsibilities`. The entity raw also has
  `variable_positions` and `site_variable_positions` (indexed by responsibility). This is where
  `[POSITION:MESSENGER]` with `[SITE]`, `[REQUIRES_POPULATION]` and `[APPOINTED_BY]` can be read in
  game: the probe does that.
- A slot (`entity_position_assignment`, bay12 `entity_position_profilest`): `id`, `histfig`
  (holder), `histfig2` (last holder), `position_id`, `position_vector_idx`, `flags`, `squad_id`,
  `assigned_army_controller_id`. The holder's side is `histfig_entity_link_positionst`
  (`df.history_figure.xml`: `entity_id`, `assignment_id`, `assignment_vector_idx`, `start_year`).
- The Nobles screen (`df.d_interface.xml` `administrators_interfacest`): rows are `noblelistst`
  (`un`, `nem`, `ep`, `epp`, `enid`), so it lists posts of more than one entity. The candidate
  list is `candidate` (`appointment_candidatest`: `un`, `value`), with `choosing_candidate` and
  `candidate_noblelist_ind`. Nothing shows what DF writes on a click beyond those two records.
- The World screen (`viewscreen_worldst`): `messenger_epp` (slots), `messenger_ent` (their
  entities), `messenger_flag` (`civlist_messenger_flag.LOCKED_IN`),
  `focus_site_messenger_candidate`. The messengers on offer are slots, possibly of more than one
  entity.

**What DFHack does:**

- `Units::getNoblePositions` (`library/modules/Units.cpp`) walks the figure's
  `histfig_entity_link_positionst` links to the entity's assignment and position. That is the
  read-back `ai-nobles.write_appointment` checks.
- `getUnitsByNobleRole(code)` looks at **both** `plotinfo.civ_id` and `plotinfo.group_id`.
  `scripts/fix/stuck-squad.lua` calls it with `'Messenger'`, so DFHack expects a messenger as a
  post of one of those two entities.
- `scripts/make-monarch.lua` is the only DFHack script that writes an appointment: the same two
  records (`assignment.histfig` and a position link). `scripts/internal/emigration/unit-link-utils.lua`
  does the reverse for an emigrating mayor: `histfig`/`histfig2` set to -1, the position link
  erased and replaced by a `histfig_entity_link_former_positionst`. No DFHack code creates a post (an
  `entity_position` in `own`) or copies a civilisation's site template into a site government.
  `Military::makeSquad` creates squads only for an assignment that already exists.

**What the wiki says** (dwarffortresswiki.org, *Advanced entity position mechanics*; not code):
posts with `[REQUIRES_POPULATION]` of 7 or less are open at embark. Above that, DF "does not
continuously check whether positions should become available" and only evaluates them at certain
events (deaths, Election Day, manual (re)assignment, ...). `AS_NEEDED` posts can be made by the
player at will, and the only AS_NEEDED post made in worldgen is the site-level DELIVER_MESSAGES
one. The *Messenger* page says messengers are appointed on the Nobles screen and sent from the
World screen. It gives no population.

**The rule the AI follows** (`lua/ai-nobles.lua` `messenger_status`, `pop_gate`):

- **The post is in the fort's `own`** (by code or duty), open (no `requires_population`, or
  `HAS_MET_POP_REQ` set, or that flag unreadable and the citizens counted at least that many):
  appointed by the existing mechanism (r2 h9: `add_slot` adds the AS_NEEDED slot as the screen
  does, then `write_appointment` writes the slot's holder and the figure's position link, reads it
  back through `getNoblePositions`, and undoes both if DFHack doesn't see it). This is the same
  path as the manager, bookkeeper, broker and chief medical dwarf. It works for any post once its
  slot exists and its appointer (`appointed_by`, an office of the fort's own government) is held.
  The holder is the best talker who is not a soldier, holds no other office, is not hospital or
  location staff, a patient, wounded, a mother of a baby, a child or in a mood.
- **The post is in `own` but not open** (needs N, `HAS_MET_POP_REQ` false): never filled. The why
  is "no post until population N (now M)" or "post listed but not open yet".
- **Not in `own`, only a civilisation template** (`positions.site`) **or only in the raws**: the AI
  **does not write a post**. No code or evidence shows how DF copies a template, which ids and
  indices it gives the post (`next_position_id`, `position_vector_idx`, the possible_* lists) or
  what else it sets. The why: "no post until population N (now M)", or "no post yet: ... DF has
  not given it to this fort".
- **Only a post of the civilisation itself**: "not this fort's to fill".
- **Nowhere**: "no post: this civilisation has no messenger position".

The why is in `offices.messenger.why` and `missions.messenger.why`, and the planner turns it into
a note (`brain/planner_world.py` `_messenger_rule`). It is also part of the sender's stop reason.
Sending stays behind `send_messenger` (off by default).

**Open, for the probe** (`lua/probes/probe-messenger.lua`, read only, one JSON object): which of
the cases above a real fort is in. It prints the fort's posts (flags, duties, requires_population,
number, appointers), slots and holders; the civilisation's site templates, its own messenger post
and its raw positions (`SITE`, `REQUIRES_POPULATION`, `APPOINTED_BY`, `NUMBER`); the citizens
counted; and `ai.why`. If a fort with enough dwarves still has only a template, the next step is
the Nobles screen (word-found buttons, as trade does), not a data write.

## Petitions (r10)

(r10 p1, Phase 12b, 22 Nov.) Evidence from `git clone --depth 1` of DFHack/df-structures
(611369f), DFHack/dfhack (master; tag `53.17-r1` fetched: its `library/xml` submodule is the
same df-structures commit 611369f) and DFHack/scripts. File references are to those repos.

**Where pending petitions live.** `df.global.plotinfo.petitions`: a vector of agreement ids,
DF's `unapproved_agreement_id` (df.plotinfo.xml:1027, "unapproved agreements"). Each is a
`df.agreement` (df.agreement.xml:225, instance vector `world.agreements.all`): `parties`
(`agreement_party`: `id`, `histfig_ids`, `entity_ids`), `details[0]` with `type`
(`agreement_details_type`: `Residency` = BECOME_RESIDENT, `Citizenship` = BECOME_CITIZEN,
`Location` = BUILD_LOCATION) and `data.Residency` {`reason`, `applicant`, `government`, `site`,
`end_year`, `end_season_tick`} or `data.Citizenship` {the same without `reason`}
(df.agreement.xml:46-62); `applicant` and `government` are party ids. `flags`: only
`petition_not_accepted` (NOT_APPROVED, "this gets unset by accepting a petition") and
`convicted_accepted` (CONCLUDED) (df.agreement.xml:220-223).

**What approval and denial change.** Not in the repos beyond that flag. scripts/list-agreements.lua
`is_resolved` (temple/guildhall agreements only) reads an agreement off the list with
`petition_not_accepted` still set as "denied", which fits the AI's decline (take it off the
list, the flag left). DF gives the applicant a thought either way (df.personality.xml:984-998:
`BecomeResident`/`BecomeCitizen` = RESIDENCY/CITIZENSHIP_PETITION_ACCEPTED, `DenyResident`/`DenyCitizen`),
so DF's own approval does more than clear the flag; what (unit flags2.resident CURRENT_RESIDENT
df.unit.xml:1390, histfig entity links, the thought) is not documented anywhere in the three repos.
0.105.11 saw it live: clearing the flag left B's visitor a guest. So route (a), setting the data
DF sets on approval, has no evidence and is not taken.

**makeown.** `dfhack.units.makeown` calls DF's own `unitst::make_own` (dfhack
library/modules/Units.cpp:1126, global `unitst_make_own` in every 53.17 symbol table); the
`makeown` script (scripts/makeown.lua) adds an armok fix-up: clears merchant/visitor/resident/guest
flags, sets the unit's and histfig's civ, makes them former members of other civs and members of
the fort's civ and site government, history events, clothing ownership. That is citizenship by
force, not DF's answer to a petition (no agreement touched, no thought, no event of the
petition), and nothing makes a *resident*. Route (c) is not taken.

**The Petitions screen.** `game.main_interface.petitions` is `petitions_interfacest`
(df.d_interface.xml:854): `open`, `have_responsible_person`, `agreement_id` (the list shown),
`selected_agreement_id`, `scroll_position`, `scrolling`. DFHack's focus string is
`dwarfmode/Petitions` (library/modules/Gui.cpp:691). There is no interface key for it or for
approve/deny (df.g_src.keybindings.xml has none), and the buttons' words are not in any repo, so
word-found buttons (lua/ai-screen-buttons.lua) would need the player to show them once. Route (b)
is left for if the route below proves not enough.

**The real cause, and the route taken: DF's own standing orders.** df.game_v.xml:218-223 declares
`standing_orders_petition_resident_{monster_hunter,performer,mercenary,scholar,sanctuary}` and
`standing_orders_petition_citizenship` (uint8, original-name `standingorder_petition_*`). DFHack
binds a global by its `name` only (library/DataStatics.cpp `INIT_GLOBAL_FUNCTION_ITEM`:
`getAddress(#name)`; VersionInfo.h:134 a plain map lookup). symbols.xml's win64 tables (STEAM
:274-279, ITCH :1388-1393, CLASSIC :2502-2507) list the six under DF's names
`standingorder_petition_*` (as some other orders: `standingorder_ignore_damp_stone`,
`standingorder_forbid_*`); the linux64 tables use DFHack's names (:3586-3591, ...). So on Windows
DFHack 53.17-r1 has no address for `df.global.standing_orders_petition_*` ("global address not
known", LuaTypes.cpp:1132): the report's `orders: []` in all six forts. Not a DFHack version
problem (the setup guide's "needs a DFHack newer than 53.16-r3" was wrong).

The bridge now (lua/ai-bridge-report-fort.lua `petition_orders_bind`) asks
`dfhack.internal.getAddress` for DF's names and, when DFHack's name has none, binds it with
`dfhack.internal.setAddress(name, addr)` (LuaApi.cpp:4086: sets the VersionInfo entry and the
global's pointer, so `df.global.<name>` reads and writes the byte, LuaTypes.cpp:1125-1150).
Guards: every address within 128 bytes of `standing_orders_auto_collect_webs` (bound by DFHack's
name on every platform; the petition bytes sit 2-7 bytes from it on win64, 16-21 on linux64),
six different addresses, every byte 0 or 1 once bound (else all six unbound again: address 0),
tried once a session; the report says `orders_via` (`names`, `symbols`) or `orders_why`. Then the
existing `petition_orders` action (0.87) and `_petition_rules` set DF's orders from the weighing
(performers, scholars, sanctuary by Outsiders; hunters and mercenaries by Militarism; citizenship
under the population target) and DF itself answers the petitions.

Not known from the repos (the probe and the planner's memory will show): whether DF applies an
order to petitions already waiting when it is switched on, or only to new ones. The planner
records it (`memory.petition_orders.swept[kind]`, r10p1_orders_sweep_days after the order was
set) and keeps the Needs you for the old ones when DF leaves them.

**Safety.** Nothing about petitions changes while DF's petitions screen or the standing orders'
Petitions tab (`.../STANDING_ORDERS/PETITIONS`, Gui.cpp:403) is open (`waiting`, no back-off) or
while threats can reach the dwarves; a refusal goes through the general back-off; an order you
change after the AI set it is left alone a year; the Rules switch "accept visitors" off puts only
the AI's accepts back to ask. Citizenship is declined (off the list, as residency since 0.105.9)
for a visitor who left or died, a vampire, a closed fort, or after 28 days when not wanted; it is
agreed only by DF's order or by you. Risk: a standing order set to accept lets DF take a vampire
the AI would have declined (the orders are by kind, not by person).

**The probe.** `lua/probes/probe-petitions.lua` (read only, one line of JSON): both names'
addresses and values of the six orders, the waiting petitions with their agreement and applicant
(histfig entity links, whereabouts, unit flags, DFHack's citizen/resident tests), the newest 40
residency/citizenship agreements of the site no longer waiting (an approved one against a denied
one shows what DF changes), and the petitions screen. Run it on a fort or two (runner `probe`,
`probe-petitions`) before trusting the fix: `orders.*.df_name` set and `dfhack_name` nil on a
fort the bridge hasn't reported from yet; after a report, `dfhack_name` = `df_name` and a value.
