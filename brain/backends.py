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
import json
import os
from dataclasses import dataclass
from pathlib import Path

from dfhack import CONFIG_PATH, PROJECT_ROOT

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
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


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

    def ask(self, instructions: str, message: str, important: bool = False, effort: dict | None = None) -> Reply:
        model, thinking, answer = pick(self, important, effort)
        extra = {}
        if thinking:
            extra["thinking"] = {"type": "enabled", "budget_tokens": thinking}
        resp = self.client.messages.create(
            model=model,
            max_tokens=answer + thinking,
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


def _options(cls, extra: dict, **kw):
    """ClaudeAgentOptions, with thinking and the newer options this SDK
    version knows: each optional group in `extra` is kept if it's accepted
    (an older SDK refuses an unknown option with a TypeError)."""
    groups = [g for g in (extra if isinstance(extra, list) else [extra]) if g]
    while True:
        merged = {k: v for g in groups for k, v in g.items()}
        try:
            return cls(**kw, **merged)
        except TypeError:
            if not groups:
                raise
            groups.pop()


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

    def ask(self, instructions: str, message: str, important: bool = False, effort: dict | None = None) -> Reply:
        # (0.104.81) cut off before the keeper's 10-minute heartbeat check
        return asyncio.run(asyncio.wait_for(self._ask(instructions, message, important, effort), ASK_TIMEOUT_S))

    async def _ask(self, instructions: str, message: str, important: bool, effort: dict | None) -> Reply:
        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

        model, thinking, _answer = pick(self, important, effort)
        # (0.100, security pass) no tools at all: tools=[] is the SDK's own
        # switch for "no built-in tools" (the "*" rule is kept as a second
        # lock for an older SDK). No settings files either: the user's
        # settings may hold allow rules or hooks that run commands.
        # (the last group is dropped first if the SDK refuses an option: an
        # SDK that knows thinking but not `tools` keeps its thinking)
        groups = [{"max_thinking_tokens": thinking} if thinking else {}, {"tools": []}]
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
