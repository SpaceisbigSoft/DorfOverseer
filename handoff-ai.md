# DF AI Overseer: AI Module Handoff

Last edited 21 Nov 2026, for **round 4** (code 0.105.59 plus the round-4 groups k1-k5; the version is bumped at delivery). It covers the token-using AI: the strategist (14a), its token budget (14.3) and the agent plan (14b-14d). The main handoff (`DF-AI\handoff.md`) holds everything else: the forts, the way a round goes and is delivered (the PC runner), the changelog. Read both.

## 1. Where it stands

Built and tested offline, **never run live**. No journal of any fort has a `review` line; `--ai` has never run in a keeper; `check_ai.py` has never been seen to pass on the PC. The audit of 15 Nov (A7, `r4/A7.md` in the round's folder) listed ten bugs, B1-B10; round 4 fixes them (k1: B1 B2, k2: B5 B8 B9, k3: B3 B4 and token reporting, k4: B6 B7, k5: B10 and the advice-only mode).

The next step is the player's: Step 0 below, then Step 1, a season with `--ai` in **advice-only mode**.

## 2. Step 0: connect (on the PC, by the player)

In the DF-AI folder that will run `--ai`:

1. `claude auth status` shows the claude.ai sign-in (if not: run `claude`, sign in with the Claude account, `/exit`).
2. `pip install claude-agent-sdk` (Windows wheels exist for Python 3.15).
3. `config.json` has `"strategist_backend": "subscription"` (round 4 makes it the code's default too; an API key is used only when the config says `"api"`).
4. `python brain\check_ai.py` passes. Write down the tokens it prints: the project's first real measurement.

Details for the player: `docs/ai-setup.md`. No extra money: no purchased credits, no auto-reload. The subscription is personal; never distribute it, never print or log a key.

## 3. Step 1: a season with `--ai`, advice only

`keeper.py --revive --ai --preset "<name>"` on a seventh fort (`D:\DF-G`, port 5006, `DF-AI-G`) started from `first-save\region4` on the same version and at the same time as its scripts-only twin, so the six-fort exit test stays scripts-only. Sliders: How often = Rare, How long = Short; the daily cap set.

**Advice-only ("shadow") mode** is on by default (`brain/review.py`, `shadow_on()`): config.json `"strategist_shadow"`; only `false` turns it off (missing, `true` or unreadable: on). In it:
- the review is asked as usual (tokens are spent and counted) and its answer goes through `check_answer`;
- **nothing is applied**: no proposal, no planner adjustment, no raise or hold, no style change, no design ask; the season's character choice is made by the script, as without `--ai`, while the review is still asked what it would choose (once a season);
- the journal's `review` line carries `"shadow": true, "applied": false`, everything it would do (`adjust`, `actions`, `steer`, `season`), what `check_answer` refused (`rejected`), a `verdict` (accepted / refused counts) and the reply itself (first 4,000 characters);
- the log says "ADVICE ONLY: nothing applied" and "AI would ..." lines; the overseer says at start that it is advice only.

Only the sections it asked to see (`want`) carry over, since they only shape its next prompt.

Read the shadow reviews: tokens per review against the estimate, what it would do and whether that is sensible, the refusals, the failures and their back-off. When they read well, the player sets `"strategist_shadow": false` and restarts the keeper.

## 4. What a review can do (all through `strategist.check_answer`)

- adjust 5 planner keys within `planner_core.ADJUST_BOUNDS` (drink, meals, blocks, wood per dwarf, idle share), re-clamped by the planner;
- up to 3 actions: `work_order` (known recipes, amount 1-100), `tool` (the bridge's allowlist), `civ_alert`, `start_project` (the 15 kinds of `lua/ai-layouts.lua` KINDS, each with its sizes in `INSTRUCTIONS` and `_check_project`; a kind without a check is refused), `cancel_project` (open, still being dug), `cancel_work_order` (its own orders), `set_style`;
- up to 4 raises (7 days, first in line) or holds (1-84 days, `build` at most 14) of planner rules;
- `want`: up to 3 report sections in full next review: any section of the bridge's report (`WANTABLE`, kept level with `lua/ai-bridge.lua` SECTIONS by `tests/test_r4_k5.py`), each cut to 2,500 characters on item boundaries; the prompt names the most useful (`SECTIONS`);
- the season's character choice; a note.

A new level's place is never the model's: its rooms go along a floor's main hall (`planner_floors.floor_action` adds the floor hint at send time, for the strategist's levels too) or a classic spot.

## 5. Safety bounds (keep them)

- **No tools for the model.** Subscription path: `tools=[]`, `disallowed_tools=["*"]`, `mcp_servers={}`, `strict_mcp_config`, `setting_sources=[]`, `max_turns=1`, an empty sandbox `cwd`. The API path sends no tools.
- **Everything through `check_answer`**, which never raises on any JSON shape (round 4, k2). No action type for squads, gates, levers, trade, expulsions or kills exists there.
- **Holds by rule class:** no hold of a rule `hold_classes.py` classes survival or defence, nor of the protected lists (round 4, k1). **Raises by action kind:** a rule whose actions kill, expel, open gates or seals, link levers, trade, butcher, convict, lure or hunt is never raised (k1).
- **Its proposals pass the crisis and recovery holds** like the planner's (k4); only its own orders are shown as "YOUR OPEN ORDERS" (k4).
- **Game text is data:** names, news, notes quoted through `digest.game_text`. **No coordinates out** (blueprint coordinate keys refused).
- **The halt, Co-pilot's big moves and the Rules tab** apply to its proposals as to the planner's.

## 6. Tokens

- `tokens.TokenBank` per fort, filled by the two AI sliders (`ai_plan`); event top-ups; a reserve kept for event reviews.
- **The daily cap:** `pc_token_cap` in each folder's `config.json` (default 250,000 tokens; 0 turns it off, the player's choice only) is one count for the whole PC in `pc_token_file` (default `%LOCALAPPDATA%\DF-AI\tokens-today.json`, outside every fort folder), shared by every fort. The panel's own `real_day_token_cap` still applies; the smaller of the two holds. A review or chronicle past it is skipped and says so. The subscription shares the player's chat limits, so keep it modest.
- **Back-off:** a failing call waits 2, 4, 8, 16 then at most 28 game days; a rate or usage limit at least 7. **Extra usage:** when the subscription reports pay-as-you-go extra usage in play, the call is dropped at once and every AI call (reviews and the chronicle) waits 28 days: the player spends no extra money. Error text is scrubbed of any API key before it is said, journaled or saved.
- **The chronicle** (`storyteller.py`, off by default) spends tokens too, from the same bank, cap and back-off.
- A failing or rate-limited backend backs off (doubling waits, a journal note) and is never asked every game day (k2).
- Every review journals its tokens (in/out/total, model, backend, fort) (k3).
- Size: the prompt reads about 6,200-6,500 tokens a review uncached (instructions ~2,900, the message ~3,000-3,300, the answer ~400), about twice the old `REVIEW_TOKENS` (3,100). `bank.plan_ratio` learns the real cost against `ai_plan`'s own estimate from the first reviews, and `ai_plan` uses it (k3; `token_ratio` only compares the cost with the prompt-length estimate). The 2.5 characters a token is the code's estimate, never measured.

## 7. Files

| File | What |
|---|---|
| `brain/strategist.py` | `INSTRUCTIONS`, `review_message`, `check_answer`, steering, `SECTIONS` / `WANTABLE`, `cut_json`, `detect` |
| `brain/review.py` | `maybe_review` (when, which model, the bank, applying or advice only), `shadow_on`, `token_ratio`, `apply_steer` |
| `brain/backends.py` | `SubscriptionBackend` (Agent SDK; `effort` and adaptive `thinking`, `max_thinking_tokens` only for an old SDK), `ApiBackend`; models haiku / sonnet / opus by the How long slider |
| `brain/tokens.py` | the bank, the daily cap, `ai_plan` |
| `brain/hold_classes.py`, `planner_core.steer_protected` | what may never be held |
| `brain/season.py`, `digest.py`, `chronicle.py`, `storyteller.py` | the season choice, the compact fort text (~1,900 tokens on a year-258 fort), the story |
| `brain/check_ai.py` | the one-question connection test |
| tests | `test_strategist.py`, `test_fix26_strategist.py`, `test_strategist_sections.py`, `test_season.py`, `test_storyteller.py`, `test_copilot_ids.py`, the `test_d0_*.py`, `test_r4_*.py` |

## 8. Known gaps

- Unverified until a signed-in call: the CLI taking `*` and an empty `--tools`, `--thinking`, the model aliases on the plan, the `usage` key names, how much context the CLI adds (the real cost), caching, what a rate limit looks like.
- Strategist levels get the layout customs only, not the placement ones (`review.py`).
- A raw invasion event (a thief) still counts as a siege in `strategist.detect` (Gap Checklist l.1249): fix before paying for event reviews.
- The cut size of a section (2,500 characters) is a guess: `needs` on fort A is cut to 29%.
- 14b-14d (the tool layer, the turn runner, the control-level slider, Agent level, comparison runs) are not built; the design is in the Design Notes ("Design: full token-based AI agent control"), and tools are to be only in-process SDK tools defined by the overseer, with a security review.
- The design track (14e): D0 built behind `design_ai` (off); never asked in advice-only mode.
