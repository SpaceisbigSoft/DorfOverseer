# Token efficiency: first measurements

Measured 2026-10-19 on the real "AI Test Run" fort (194 citizens, year 148).
Token counts are **estimates** at 2.5 characters per token (Anthropic's figure for
current Claude models). Run `python brain\tools\token_test.py` with an API key for
exact counts; Anthropic's token-counting endpoint is free and runs no model.

## How to describe the fort to the AI

| Variant | Characters | ~Tokens | vs raw |
| --- | --- | --- | --- |
| Full report, as saved (pretty JSON) | 110,289 | 44,116 | 100% |
| Full report, minified JSON | 62,964 | 25,186 | 57% |
| Report without the per-dwarf list | 9,371 | 3,748 | 8.5% |
| **Compact digest** (`brain/digest.py`) | 1,831 | 732 | **1.7%** |
| **Change-only diff**, one day later (simulated) | 111 | 44 | **0.1%** |

The digest keeps every number the strategist needs, groups repeats (29 Specters
of Steam become one line with their depth range), names only the dwarves who
need attention (the 5 unhappy ones), and summarizes the rest (idle dwarves by
profession). The diff reports only numbers that moved by 2% or more, plus any
change in citizens, threats, injuries, mood or soldiers, and new announcements.

## Tokens per review and per in-game year (50% activity = 36 reviews/year)

Assumptions until the strategist exists: about 4,000 tokens of fixed instructions
(rules, action list, style guide) and about 1,500 tokens of answer and thinking
per review. Caching uses the 1-hour cache: one write per hour at 2x, then reads at
0.05x (Sonnet 5.5 / Opus 5.5), with roughly 12 reviews per real hour.

| Strategy | Per review | Per in-game year |
| --- | --- | --- |
| Raw report every review, no caching | ~49,600 | ~1.79 million |
| Digest every review, no caching | ~6,200 | ~0.22 million |
| Digest + cached instructions | ~3,100 | ~0.11 million |
| Digest for routine reviews, diff for event reviews, cached | ~3,100 / ~2,400 | **~0.10 million** |

"Per review" counts cached instructions at their billed weight, which is what a
token budget should track.

## What this tells us

1. **The digest is the big win:** about 60x smaller than the raw report, losing
   nothing the strategist uses.
2. **After that, the AI's own answer dominates** (~1,500 of ~3,100 tokens per
   review). Next levers to test once the strategist exists:
   - a lower `effort` setting for routine reviews (less thinking)
   - short, structured answers: actions as tool calls, one-line reasons
   - a smaller, cheaper model for routine reviews, and a larger one only for big events
3. **Caching the fixed instructions** halves the remaining cost. The 1-hour cache
   suits us because reviews are minutes apart in real time.
4. **Diffs** make event reviews nearly free on the context side; use a full
   digest at the start of each session and periodically to avoid drift.

## Still to measure (Phase 4 and 6)

- [ ] Exact counts via `token_test.py` with an API key
- [ ] Real size of the fixed instructions once written
- [ ] Real answer + thinking tokens per review at each effort level
- [ ] Reviews per real hour at your FPS (sets the cache benefit)
- [ ] Decision quality: digest vs full report on the same situations
