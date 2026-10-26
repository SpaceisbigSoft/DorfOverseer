# Connecting the AI strategist

The local planner works without any of this. The strategist is the optional
"thinking" layer that reviews the fort every couple of in-game weeks and steers
the planner. There are two ways to connect it, and neither needs extra money.

## Option 1: your Pro or Max subscription (works now)

Uses your plan's normal usage limits, the same pool as your Claude chats.
Personal use only: Anthropic doesn't allow building claude.ai sign-in into
programs you give to other people.

1. **Install Claude Code.** In PowerShell:
   ```
   irm https://claude.ai/install.ps1 | iex
   ```
   (This is Anthropic's official installer from code.claude.com.)
2. **Sign in once.** Open a new PowerShell window and run `claude`. Choose to
   sign in with your **Claude account** (not an API key) when your browser
   opens. When it says you're signed in, type `/exit`.
   You can confirm with `claude auth status`; it should mention `claude.ai`.
3. **Install the Agent SDK** for Python:
   ```
   pip install claude-agent-sdk
   ```
4. **Test it** from the DF-AI folder:
   ```
   python brain\check_ai.py
   ```
   It asks Claude one tiny question and shows the tokens used.

If you also have an API key in `.env`, the strategist uses the key first. To
force the subscription, add `"strategist_backend": "subscription"` to `config.json`.

## Option 2: an API key (once your Max plan is 7 days old)

Max includes monthly API credits ($100 or $200 a month) that need no card and
simply stop when used up.

1. Claude app: **Settings → Billing → API credits → Link organization**, and
   create a new Console organization when asked.
2. At platform.claude.com/settings/keys, **Create key** and copy it (shown once).
3. In the DF-AI folder, create a file named `.env` containing:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   Never paste the key into chat or anywhere else.
4. `pip install anthropic`, then `python brain\check_ai.py`.

## Running it

Once `check_ai.py` says the connection works:

```
python brain\overseer.py --ai --autopilot
```

Without `--autopilot` it's a dry run: the AI still reviews (and uses tokens),
but its suggestions are only shown. Without `--ai` only the free local planner
runs. Each review is printed with its token cost and the bank's balance, and
logged in the fort's journal (`logs\forts\<fort>\journal.jsonl`). If the connection fails, the planner carries
on and the AI tries again the next in-game day.

**Two sliders decide how it works** (the panel's AI & tokens tab). Each runs
from -100 to +100 with Normal in the middle, and Extreme doubles it:

| How often it reviews | Routine review | Event reviews a month |
| --- | --- | --- |
| Very rare (Extreme) | every 56 days | up to 1/4 |
| Rare | every 28 days | up to 1/2 |
| **Normal** | every 14 days | up to 1 |
| Often | every 7 days | up to 2 |
| Very often (Extreme) | every 4 days | up to 4 |

Event reviews come after big events: sieges, deaths, forgotten beasts nearby,
waves of unhappiness.

| How long it thinks | Routine reviews | Event reviews | Answer and summary |
| --- | --- | --- | --- |
| Very short (Extreme) | small model | small model | shortest |
| Short | small model | small model | short |
| **Normal** | small model | large model | as before |
| Long | large model, thinks up to 2,000 tokens | large model, up to 3,000 | longer, more news |
| Very long (Extreme) | large model, up to 4,000 | largest model, up to 6,000 | longest |

The tab shows what the two sliders mean in practice: how often reviews come,
which models think how long, and the **estimated tokens per review and per
in-game year**. Normal and Normal come to about 112,000 tokens a year.

**Token bank:** filled automatically from the two sliders, 1.5 times faster
than the plan spends and holding 60 days of it, so the plan isn't cut short.
Big events add a one-time top-up, and a quarter of the bank is kept for event
reviews only. The **real-world daily cap** stays a hard ceiling you set
yourself, whatever the sliders say.

## What the strategist can and can't do

- Its connection has **no tools**: it can only answer in text. It can't read
  your files, run commands or browse.
- Its answer is checked before anything happens: only approved actions, at
  most 3 per review, order sizes 1-100, planner targets within fixed bounds, and
  it may only cancel orders the AI created, and it can't lower an alert you
  raised. Anything else is thrown out and logged.
- It spends from the token bank, which the two sliders on the AI & tokens tab
  fill, under your real-world daily cap.

## Which models

At Normal thinking, routine reviews use a small, fast model (Haiku) and event
reviews (sieges, deaths, beasts) a stronger one (Sonnet); the How long slider
moves both (see above), and Very long uses the largest (Opus) for events.
Change the three in `config.json` with `"strategist_model"`,
`"strategist_model_events"` and `"strategist_model_top"`.
