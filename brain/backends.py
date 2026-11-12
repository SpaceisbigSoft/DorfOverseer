"""How the strategist reaches Claude. Two backends, same interface:

  api           Claude API key (in .env). Uses prompt caching. With a Max plan,
                the key's Console organization can be linked to the plan's
                monthly API credits, so nothing extra is spent.
  subscription  Your Pro/Max sign-in, through the Claude Agent SDK
                (pip install claude-agent-sdk; sign in once with `claude`).
                Uses your plan's normal usage limits. Personal use only:
                Anthropic doesn't allow sharing claude.ai sign-in in programs
                given to other people.

Both run with NO tools: the model can only answer in text. Its answer is then
checked by strategist.check_answer() before anything reaches the game.

config.json keys (all optional):
  "strategist_backend": "auto" | "api" | "subscription"   (auto: api if a key exists;
      set "subscription" to be sure a key in the environment never switches to paid calls)
  "strategist_model": model for routine reviews  (api: "claude-haiku-5-5", subscription: "haiku")
  "strategist_model_events": model for event reviews (api: "claude-sonnet-5-5", subscription: "sonnet")
  "strategist_model_top": the largest model, for event reviews at Very long thinking
                          (api: "claude-opus-5-5", subscription: "opus")

Which of the three a review uses, and how long it may think, comes from the
panel's How long slider (tokens.ai_plan): ask(..., effort={"model": "small" |
"large" | "top", "thinking": tokens (0 = off), "answer_tokens": n}).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from dfhack import PROJECT_ROOT, read_config

MAX_ANSWER_TOKENS = 1200
SANDBOX = PROJECT_ROOT / "logs" / "strategist-sandbox"   # empty folder: no project files visible


@dataclass
class Reply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    model: str = ""

    @property
    def budget_tokens(self) -> int:
        """What a review costs against the token bank. Cache reads are billed at a
        small fraction of normal input (5-10% on current models), so they count 10%."""
        return int(self.input_tokens + self.output_tokens + self.cache_write_tokens
                   + 0.1 * self.cache_read_tokens)


class BackendUnavailable(RuntimeError):
    pass


ASK_TIMEOUT_S = 480   # (0.104.81) seconds a strategist call may take (the keeper restarts a 600 s silence)


def _config() -> dict:
    return read_config()


def load_api_key() -> str | None:
    """From the environment or the project's .env file. Never printed or logged."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    env = PROJECT_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                return value or None
    return None


# --- API key backend -------------------------------------------------------------

class ApiBackend:
    name = "api"

    def __init__(self, cfg: dict):
        try:
            import anthropic
        except ImportError as e:
            raise BackendUnavailable("the anthropic package isn't installed (pip install anthropic)") from e
        key = load_api_key()
        if not key:
            raise BackendUnavailable("no ANTHROPIC_API_KEY in .env or the environment")
        # (0.104.81) a call may not outlast the keeper's 10-minute heartbeat check
        self.client = anthropic.Anthropic(api_key=key, timeout=ASK_TIMEOUT_S, max_retries=1)
        self.model = cfg.get("strategist_model", "claude-haiku-5-5")
        self.model_events = cfg.get("strategist_model_events", "claude-sonnet-5-5")
        self.model_top = cfg.get("strategist_model_top", "claude-opus-5-5")

    def ask(self, instructions: str, message: str, important: bool = False, effort: dict | None = None,
            answer_tokens: int | None = None) -> Reply:
        model, thinking, answer = pick(self, important, effort)
        if answer_tokens:                 # (D0) the answer size per call (a blueprint: 2,500)
            answer = int(answer_tokens)
        body, max_tokens = thinking_params(model, thinking, answer)
        extra = {"extra_body": body} if body else {}
        resp = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            # The fixed instructions are cached for an hour: later reviews read
            # them at a fraction of the normal price.
            system=[{"type": "text", "text": instructions,
                     "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
            messages=[{"role": "user", "content": message}],
            **extra,
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        u = resp.usage
        return Reply(text=text, model=model,
                     input_tokens=u.input_tokens or 0, output_tokens=u.output_tokens or 0,
                     cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
                     cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0)


def pick(backend, important: bool, effort: dict | None) -> tuple[str, int, int]:
    """(model, thinking tokens, answer tokens) for one review. Without an
    effort (an older caller): small model for routine, large for events."""
    if not effort:
        return (backend.model_events if important else backend.model), 0, MAX_ANSWER_TOKENS
    model = {"small": backend.model, "large": backend.model_events,
             "top": backend.model_top}.get(effort.get("model"), backend.model)
    thinking = int(effort.get("thinking") or 0)
    return model, (thinking if thinking >= 1024 else 0), int(effort.get("answer_tokens") or MAX_ANSWER_TOKENS)


ADAPTIVE_HEADROOM = 2048   # (0.105.26) output room for a model's own thinking above the answer


def _generation(model: str) -> tuple:
    """(major, minor) from a model id ("claude-haiku-5-5" -> (5, 5),
    "claude-3-5-haiku-20241022" -> (3, 5), "claude-sonnet-4-20250514" -> (4, 0));
    () when it names none (an alias such as "haiku")."""
    nums = [int(x) for x in str(model).split("-") if x.isdigit() and len(x) <= 2]
    return tuple((nums + [0])[:2]) if nums else ()


def thinking_params(model: str, thinking: int, answer: int) -> tuple[dict, int]:
    """(0.105.26) The thinking request and max_tokens for one call. Models
    before 4.6 take the manual {"type": "enabled", "budget_tokens"}; from 4.6
    on the API wants adaptive thinking steered by effort (manual thinking is
    refused on the newest models, and Opus 5.5 thinks always): there, no
    thinking asked means effort "low", and the answer gets headroom so the
    model's own thinking can't eat it."""
    gen = _generation(model)
    if gen and gen < (4, 6):
        if thinking:
            return {"thinking": {"type": "enabled", "budget_tokens": thinking}}, answer + thinking
        return {}, answer
    effort = "low" if not thinking else "medium" if thinking < 3000 else "high"
    body = {"output_config": {"effort": effort}}
    if thinking:
        body["thinking"] = {"type": "adaptive"}
    return body, answer + max(thinking, ADAPTIVE_HEADROOM)


def _options(cls, extra, **kw):
    """ClaudeAgentOptions, with thinking and the newer options this SDK
    version knows: each optional group in `extra` is kept if it's accepted
    (an older SDK refuses an unknown option with a TypeError).
    (0.105.33, B5) A group may be a tuple of alternatives, tried in order
    (the newer option first). Groups are listed least important first: a
    refused one is dropped on its own, so a later one the SDK does know (the
    `tools=[]` lock) is never lost with it."""
    groups = []
    for g in (extra if isinstance(extra, list) else [extra]):
        alts = [a for a in (g if isinstance(g, tuple) else (g,)) if a]
        if alts:
            groups.append(alts)

    def build(choice):
        merged = {k: v for alts, i in zip(groups, choice) if i is not None for k, v in alts[i].items()}
        return cls(**kw, **merged)

    choice = [0] * len(groups)
    while True:
        try:
            return build(choice)
        except TypeError:
            pass
        # which one group is refused: change it alone (next alternative, then none)
        for n in range(len(groups)):
            if choice[n] is None:
                continue
            nxt = choice[n] + 1 if choice[n] + 1 < len(groups[n]) else None
            trial = choice[:n] + [nxt] + choice[n + 1:]
            try:
                return build(trial)
            except TypeError:
                continue
        # more than one refused: step the least important that's left, and go on
        live = [n for n in range(len(groups)) if choice[n] is not None]
        if not live:
            return build(choice)     # (the base options themselves: let its TypeError through)
        n = live[0]
        choice[n] = choice[n] + 1 if choice[n] + 1 < len(groups[n]) else None


# --- Subscription backend (Claude Agent SDK) -----------------------------------------

class SubscriptionBackend:
    name = "subscription"

    def __init__(self, cfg: dict):
        try:
            import claude_agent_sdk  # noqa: F401
        except ImportError as e:
            raise BackendUnavailable(
                "the Claude Agent SDK isn't installed (pip install claude-agent-sdk)") from e
        # An API key in the environment would take priority over the subscription
        # sign-in. Remove it from THIS program's environment so the plan is used.
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
        SANDBOX.mkdir(parents=True, exist_ok=True)
        self.model = cfg.get("strategist_model", "haiku")
        self.model_events = cfg.get("strategist_model_events", "sonnet")
        self.model_top = cfg.get("strategist_model_top", "opus")

    def ask(self, instructions: str, message: str, important: bool = False, effort: dict | None = None,
            answer_tokens: int | None = None) -> Reply:
        # (D0) answer_tokens: the SDK has no answer cap (see _ask); taken for the same interface
        # (0.104.81) cut off before the keeper's 10-minute heartbeat check
        return asyncio.run(asyncio.wait_for(self._ask(instructions, message, important, effort), ASK_TIMEOUT_S))

    async def _ask(self, instructions: str, message: str, important: bool, effort: dict | None) -> Reply:
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

        model, thinking, _answer = pick(self, important, effort)
        # (0.105.33, B5) the same effort as the API path (low with no thinking);
        # `thinking` replaces the deprecated max_thinking_tokens, which stays as
        # the fallback for an older SDK. (The answer cap has no SDK option.)
        level = "low" if not thinking else "medium" if thinking < 3000 else "high"
        # (0.100, security pass) no tools at all: tools=[] is the SDK's own
        # switch for "no built-in tools" (the "*" rule is kept as a second
        # lock for an older SDK). No settings files either: the user's
        # settings may hold allow rules or hooks that run commands.
        # (each group is dropped on its own if the SDK refuses it, least
        # important first: `tools` is kept by any SDK that knows it)
        groups = [{"effort": level},
                  ({"thinking": {"type": "adaptive"} if thinking else {"type": "disabled"}},
                   {"max_thinking_tokens": thinking} if thinking else {}),
                  {"tools": []}]
        options = _options(ClaudeAgentOptions, groups,
            system_prompt=instructions,   # replaces Claude Code's coding prompt
            disallowed_tools=["*"],       # no tools of any kind: text answers only
            max_turns=1,
            permission_mode="dontAsk",
            setting_sources=[],           # no user, project or local settings
            cwd=str(SANDBOX),             # an empty folder: no project files or CLAUDE.md
            mcp_servers={},
            strict_mcp_config=True,       # and no MCP servers
            model=model,
        )
        result = None
        async for msg in query(prompt=message, options=options):
            if isinstance(msg, ResultMessage):
                result = msg
        if result is None:
            raise RuntimeError("no answer from Claude")
        if getattr(result, "is_error", False):
            raise RuntimeError(f"Claude returned an error: {getattr(result, 'result', '')}"[:300])
        u = result.usage or {}
        return Reply(text=result.result or "", model=model,
                     input_tokens=u.get("input_tokens", 0) or 0,
                     output_tokens=u.get("output_tokens", 0) or 0,
                     cache_write_tokens=u.get("cache_creation_input_tokens", 0) or 0,
                     cache_read_tokens=u.get("cache_read_input_tokens", 0) or 0)


# --- Choosing ---------------------------------------------------------------------------

def get_backend():
    """The configured backend, or with "auto" the first one that's ready."""
    cfg = _config()
    choice = cfg.get("strategist_backend", "auto")
    order = {"api": [ApiBackend], "subscription": [SubscriptionBackend],
             "auto": [ApiBackend, SubscriptionBackend]}.get(choice)
    if order is None:
        raise BackendUnavailable(f'strategist_backend must be "auto", "api" or "subscription", not {choice!r}')
    problems = []
    for cls in order:
        try:
            return cls(cfg)
        except BackendUnavailable as e:
            problems.append(f"{cls.name}: {e}")
    raise BackendUnavailable("; ".join(problems))
