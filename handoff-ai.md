# DF AI Overseer: AI Module Handoff

Written 11 Nov 2026 for the next chats, which work on **the AI module: Phase 14.3 and 14a-14d**. That covers the strategist going live, the agent loop, and the token budget. This note is the starting point for that work.

The main handoff (project doc "DF AI Overseer Handoff", `DF-AI\handoff.md`) still holds everything else: the whole plan, the changelog, the forts, the Commands, "How it fits together", and the standing decisions. Read both. This note only repeats what the AI work needs.

## 1. Where things stand (11 Nov)

**Code version: 0.105.40** (12 Nov: the seven fort-ending gaps from the coverage audit; 0.105.39 13b missions offline and 13e performance, incl. a `perf` report section and `batch`; 0.105.38 the whole-map water survey; 0.105.37 the design track's D0 with openings, scaffolding, power and personal rooms; see the main handoff) — before it, 0.105.36 (11 Nov), delivered to all six folders, hashes matched; DF and DFHack are now **53.17 / 53.17-r1** (Steam updated them 9 Nov; the copies B-F were brought to 53.17 on 11 Nov). Since 0.105.32: E's stuck-hatch fix, two code audits, the slider fixes, "nothing waits for the player" (0.105.35); the strategist's `RAISE_FORBIDDEN` now also covers trade, slaughter, levers and `stranded`, and holds of containers/soap/farms are refused. `culture.profile_from` is cached (0.105.33).

**The forts.** All six run the **14.1 step 5 exit test**, restarted fresh from the original embark on **11 Nov 21:08**, scripts only, no `--ai`. Start them with `C:\Users\skulr\Documents\start-keepers.bat`. Leave them scripts-only, because the exit test is the agent's baseline.

| Fort | Preset | DF copy | DF-AI folder | Port |
|---|---|---|---|---|
| A | War-hold | `D:\SteamLibrary\steamapps\common\Dwarf Fortress` (saves in AppData) | `DF-AI` | 5000 |
| B | Monastery | `D:\DF-B` | `DF-AI-B` | 5001 |
| C | Merchant city | `D:\DF-C` | `DF-AI-C` | 5002 |
| D | Hermit hold | `D:\DF-D` | `DF-AI-D` | 5003 |
| E | Deep mine | `D:\DF-E` | `DF-AI-E` | 5004 |
| F | Garden fort | `D:\DF-F` | `DF-AI-F` | 5005 |

- **The original embark:** a pristine copy is in each game folder as `first-save\region4`. The source is `DF-AI-B\backups\region4\2026-11-02 0014` (hash `e7fefd17`).
- **The old runs:** saves in `D:\DF-x\old-saves\2026-11-08-<fort>` and `...\2026-11-11-<letter>`, logs in `DF-AI-x\logs\old-runs\<date>\`.

**GitHub is back (12 Nov):** `SpaceisbigSoft/DorfOverseer`, `main` up to date. Clone it in a new chat; push each round to `main`; the PC's `_stage\dorfoverseer-repo.tgz` stays as a local backup.

**Still waiting on the player** (not AI work): whether the stranger rule (0.105.30) should be gentler. While an outsider seeks a meeting, it keeps visitors out of the tavern, temples, library and guildhalls for 7 days, at Outsiders < 50.

## 2. How to work (the player's rules)

- **In parallel.** Split every task into small groups. Each group gets its own builder agent in its own repo copy (`cp -r dorfoverseer workN && git checkout -b <branch>`), and is told it may use subagents. Then merge, test and deliver.
  - Big or structural changes go in two waves: a design agent first, read-only, which writes a spec to a file and splits the work; then builders to that spec.
  - Before every delivery, **an independent verifier** that hasn't seen the work checks the merged code with proof scripts. In every round so far it has found real bugs: fix them, re-run its scripts, then ship.
- **Each group's brief** (see `/tmp/claude-0/review/*-common.md` from earlier rounds for the pattern) covers:
  - the files it owns, and small hunks only elsewhere;
  - tests in a new file, using `tests/harness.py` and `from lupa.lua53 import LuaRuntime`;
  - no version bump, no push;
  - the commit with the attribution lines.
- **Tests:** `python3 tests/run_all.py` (91 files, about 40 s, in parallel processes). Lua must compile under Lua 5.3, which DFHack uses: `load(src,"b","t",{})` through `lupa.lua53` over `lua/*.lua` and `lua/gui/*.lua`.
- **Delivery:**
  1. **Version bump:** one find-replace of the quoted version across `lua/*.lua` (`BRIDGE_VERSION` and every `PART_VERSIONS` mark), plus `tests/test_bridge_memory.py`.
  2. **Build the patch:** `git diff --binary --no-renames --diff-filter=d <delivered>..HEAD -- lua brain tests docs` and an md5 list. Commit both to the PC under a **new file name** each time; a reused staged path can write an old copy back.
  3. **Apply:** `patch -p1 --binary`, dry run first, in all six `Documents\DF-AI*` folders.
  4. **Then** `touch lua/*.lua lua/gui/*.lua`, and check the md5s (`tr -d '\r' | md5sum | cut -c1-8`).
  5. **Live effect:** Lua changes take effect at once; brain changes need the player to restart the keepers.
- **After a version:** update the main handoff (latest-version paragraph, changelog row, under 70 KB), its PC copy and the project copy, and this note when AI work changed.

## 3. The AI module today: built, never run live

Nothing below has ever run against a real fort. `--ai` has never been used in a live keeper, and `check_ai.py` has not been seen to pass on the PC.

**Files**

| File | What it does |
|---|---|
| `brain/strategist.py` | the prompt (`INSTRUCTIONS`, `instructions()`), the review message (`review_message`), `check_answer` (every answer is validated), steering (`_check_steer`, `STEER_RULES`, `shown_rules`), `cut_json`, `rules_line`, event detection (`detect`) |
| `brain/review.py` | `maybe_review`: when a review runs, which model, applying the answer, token learning (`token_ratio`), `apply_steer`, event queue (`note_events`) |
| `brain/backends.py` | `SubscriptionBackend` (the Agent SDK on the player's Claude subscription, the default by `config.json` `"strategist_backend": "subscription"`) and `ApiBackend` (an API key in `.env`, never auto-reload). Models: `strategist_model` haiku, `_events` sonnet, `_top` opus. `thinking_params` uses adaptive thinking for 4.6+ models on the API (0.105.26). The subscription path still uses `max_thinking_tokens`. |
| `brain/tokens.py` | `TokenBank` per fort, the PC-wide real-day cap (`pc_used_today`), `ai_plan` from the two AI sliders (How often, How long it thinks), `routine_due`, `event_review_allowed` |
| `brain/season.py` | the season's character decision: a menu of raises and focuses; the AI chooses within `AI_GRACE_TICKS`, otherwise the script does (14.3 step 1, 0.103.20) |
| `brain/digest.py` | the compact fort description (about 730 tokens; 60x smaller than the raw report), `diff`, and the threat, world, infection and built lines |
| `brain/chronicle.py`, `crisis.py` | the fort's story lines; crisis mode, which holds expansion rules |
| `brain/check_ai.py` | a one-question connection test |
| `docs/ai-setup.md`, `docs/token-efficiency.md` | the player's setup steps and the token measurements |
| tests | `test_strategist.py`, `test_fix26_strategist.py` (an end-to-end fake backend over a real fixture), `test_strategist_sections.py`, `test_season.py`, `test_copilot_ids.py` |

**What one review can do** (one shot, no tools; all of it re-checked by `check_answer`):
- adjust 5 planner keys within `planner_config.ADJUST_BOUNDS`;
- at most 3 actions: `work_order` (known recipes, amount ≤ 100), `tool` (allowlisted DFHack tools on or off), `civ_alert`, `start_project` (kinds and sizes as listed in `INSTRUCTIONS`), `cancel_project` / cancel its own orders, `set_style`;
- up to 4 raises or holds of planner rules, holds at most 84 days. Life-saving rules are in `planner_core.STEER_PROTECTED` and can't be held (0.105.26);
- ask for up to 3 report sections in full for the next review (`want`);
- the season choice;
- a note.

**Safety bounds (keep them):**
- **Never reachable by a model:** kill orders, expulsions, gate clearing, lever links and trading come only from the rules.
- **No tools on the subscription backend:** it runs with `tools=[]`, `disallowed_tools=["*"]` and `setting_sources=[]`, so the player's Claude settings and hooks aren't loaded, and in an empty sandbox folder (`logs/strategist-sandbox`).
- **Game text is quoted as data:** names and news go through `digest.game_text`.
- **No coordinates:** the AI names kinds, sizes and purposes, and the scripts pick the spot.
- **The rest:** the in-game halt, Co-pilot's `BIG_MOVES` (asks the player first) and the Rules tab all apply.

**Token sliders** (the AI & tokens tab):
- **How often:** routine reviews from every 56 to every 4 game days, plus event reviews.
- **How long it thinks:** the model and the thinking size.
- **Cost estimate:** at Normal, about 3,100 tokens a review, about 0.1 million a game year (estimates; `token_ratio` learns the real figure).

## 4. The design (Design Notes, "Design: full token-based AI agent control", and "Fort identity" §3f)

**Control levels** (a new AI-tab slider; the existing modes stay):

| Level | Who decides | Tokens |
|---|---|---|
| Scripts | the planner alone (today, without `--ai`) | none |
| Strategist | the planner; the AI tunes it and adds a few actions (built) | low |
| Director | the AI sets the season's plan and priorities, approves or vetoes the planner's big moves, and answers the Needs-you items it can act on | medium |
| Agent | the AI starts any action in the registry; the planner keeps only reflexes and proposes the rest | high |

**The keeper/agent split** (the player, 8 Nov): the keeper owns basic vocabulary, such as layouts, customs, construction pieces and the safety reflexes. The agent owns grand design: the big moves, landmarks, one-off projects, how the fort grows across eras, and when to break its own pattern. It steers the style and picks the projects; the scripts place them.

**A turn** is a short agent loop with tools, not one prompt:
- **read:** the digest, then any report section on request;
- **act:** one tool per bridge action. Schemas are generated from the bridge's `ACTIONS`, and the same validators and dry runs apply;
- **planner:** see its proposals and why; accept or veto with a reason the planner learns from; change a threshold within bounds; set the season's rule priorities;
- **talk:** a Needs-you note, a chronicle line, the season's agenda.

A turn ends when the agent says so, or at a step or token limit.

**When it runs:**
- a season turn (plan, agenda, priorities);
- a weekly turn;
- event turns: siege, beast, death, mood, caravan, migrants, a stuck rule;
- whenever the scripts hit something they can't decide.

Reflexes never wait for it.

**Budget and safety:**
- **Limits:** the bank and the real-day cap stay; each turn has a token and a step limit.
- **Caching and models:** prompt caching for the instructions and tool schemas; a small model for routine turns, a large one for seasons and events.
- **Money:** no extra spending. The subscription is the default; an API key only if the player chooses, and never auto-reload.
- **Actions:** every action goes through the validators and the halt, with a daily action rate limit. Destructive ones (cancel, remove, expel, open water) need a dry run and a reason, and in Co-pilot the player's Yes.
- **Fallback:** if the backend fails or the budget runs out, control drops a level for that period, and the log says so.

**Memory:** the agent reads the atlas, the chronicle, the lessons, and a rolling summary of its own past turns, which it writes at the end of each turn and which is kept in the save.

**The 14.3 brief:** even the lowest setting must change the fort in a visible way, through few, high-leverage decisions from the identity map: the season's character decision, the next set piece and its name, which industry to grow, a new wing pattern, how to answer a petition or a diplomat.

**Measuring:** comparison runs. The same save and sliders under Scripts and under each level at several budgets, judged on the scorecard (`brain/scorecard.py --every 2y`), the soak measures (unhappy, idle, deaths, wealth, FPS, loops) and distinctiveness. Then set the defaults where more tokens stop paying.

**Phase 14 exit:** a game decade run by the agent within budget, at least as well as the scripts, with every fort visibly its own.

## 5. The proposed plan (for the player to confirm)

**Step 0: connect, on the PC, by the player** (`docs/ai-setup.md` option 1):
1. Claude Code is installed and signed in with the Claude account (`claude auth status` mentions claude.ai).
2. `pip install claude-agent-sdk`.
3. `config.json` has `"strategist_backend": "subscription"` (already set in `DF-AI`).
4. `python brain\check_ai.py` passes.

The agent loop needs tools. The current SDK lock is `tools=[]` and `disallowed_tools=["*"]`. Tools are to be given **only as in-process SDK tools defined by the overseer** (no file, shell or web tools), with `setting_sources=[]` kept. Design that in 14b, and have a security review.

**Step 1: 14a live.** A season with `--ai` on a **seventh fort**, so the exit test stays scripts-only:
- a new DF copy (`D:\DF-G`, port 5006, `DF-AI-G`), started from `first-save\region4` with a preset the player picks. Its scripts-only twin in the exit test is then the comparison;
- `keeper.py --revive --ai --preset "<name>"`;
- the player picks the token sliders; start at How often = Rare and How long = Short.

Read the journal's reviews:
- the tokens per review against `REVIEW_TOKENS`;
- what it chose and whether it showed in the fort;
- refusals by `check_answer`;
- failures and their fallback.

Fix what that shows, in a parallel round.

**Step 2: 14b, the Director loop on the subscription backend.** A design agent first, then groups, roughly:
1. **The tool layer:** read tools generated from `SECTIONS` and the digest; act tools from `ACTIONS` and the validators; planner tools (proposals, accept or veto, thresholds, priorities); talk tools.
2. **The turn runner:** step and token limits, caching, model choice, fallback, the rolling summary in the save.
3. **When turns happen:** season, weekly, events, stuck rules; reflexes never wait.
4. **The window:** the control-level slider on the AI tab; Co-pilot asks for big moves.
5. **Tests** with a fake model that calls tools, and the security review.

**Step 3: 14c, Agent level.** Planner proposals become advice; the agent originates actions; reflexes stay with the scripts.

**Step 4: 14d, comparison runs.** Copies of one save under Scripts, Strategist, Director and Agent at two or three budgets. Compare scorecards and soak measures, then set the default budget and prompts.

## 6. Known gaps that touch the AI work

- **Strategist levels get layout customs only** (`review.py`), never the placement ones such as cells, market gate or deep hall. Decide in 14b whether the agent's levels go through `planner_building.customs_pass`.
- **The digest:** 0.105.26 added threat, world, infection and lockout lines, and 0.105.30 a BUILT line. It has never been checked against a live report.
- **`cut_json`** cuts full sections at 2,500 characters on item boundaries. Check that the sections the agent will ask for most (`needs`, `projects`, `military`) are still useful at that size.
- **Calibration:** `REVIEW_TOKENS` 3,100 and `CHARS_PER_TOKEN` 2.5 are estimates from 19 Oct. The live run should calibrate them (`learn_token_ratio`).
- **The subscription backend's thinking setting** (`max_thinking_tokens`) is unchanged since before the 5.5 models. Check what the SDK accepts now.
- **The SDK's limits:** usage on the subscription shares the player's Claude chat limits. Find out how the SDK reports rate limits, and make the fallback quiet and correct.
- **Code health:** `culture.profile_from` is cached (0.105.33, `plan()` about half the cost); Phase 13e (performance) has the rest.
- **Co-pilot:** `place_keep` isn't in `BIG_MOVES` (the hall and wings are).

## 7. Files outside the repo

- **The local log folder:** `C:\Users\skulr\Documents\Claude Project Creation Logs\Dorf AI Overseer\`:
  - `DF AI Overseer Design Notes.md`: §"Design: full token-based AI agent control" and §"Fort identity: the full detailing" (2f, 3f).
  - `DF AI Overseer Gap Checklist.md`: the in-game lists, and a 0.105.16-0.105.25 section.
  - `DF AI Overseer Handoff Archive.md`: the history.
- **The in-game watch list:** `docs/watch-in-game.md` in the repo (0.105.22 onwards).
- **Proof scripts from the verifiers:** `/tmp/claude-0/.../scratchpad/` (`v30r/`, `v31x/`, `dump_plan.py`, the DFHack loader simulation in `an/sc2.lua` with the `v30/` runner). They're lost with the cloud session; copy any worth keeping into `tests/` or `brain/tools/`.

## 8. The design track (14e, added 11 Nov)

The player wants each fort to have its own fantastical, unique design. A **Design** slider (Scripts / Guided / Architect), separate from the control level. **Guided**: a per-fort design language (motifs, shapes, proportions, symmetry, materials, naming, era changes) that the scripts' layouts and customs follow; rule-made with no tokens (D0) or written by the strategist once per fort and revised per era (D1). **Architect**: the AI draws landmark blueprints (a strict per-level tile grid with a legend; one a season by default), turned into ordinary layouts of kind `landmark` so every existing site check, Quickfort dry run and project step applies; the AI picks a site id (`S1`-`S4`) from the bridge's candidates, never coordinates; up to 2 redraws, then the library piece (D2). D0 (built, 0.105.37) puts the answer fields in `check_answer` behind `design_ai` (off). The full plan: Design Notes "Design track (14e)"; the D0 spec and contract: the archive. Decisions: Guided by rules is the default for new forts; saves without the setting read Scripts; Guided within ±1 of the sliders, Architect landmarks may go past; no surface landmarks for the Hermit hold or Deep mine; cavern-edge landmarks by the cavern switch.
