"""Check that the AI strategist can reach Claude. Costs a few hundred tokens.

    python brain/check_ai.py

Tells you which route it used (API key or your Pro/Max subscription) and how
many tokens the test took. Doesn't need the game running.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backends import BackendUnavailable, get_backend  # noqa: E402
from strategist import check_answer  # noqa: E402

HELP = """
How to set it up (pick one):

  Your Pro/Max subscription (no extra cost; uses your plan's usage limits):
    1. Install Claude Code: in PowerShell run
         irm https://claude.ai/install.ps1 | iex
    2. Run:  claude
       and sign in with your Claude account when the browser opens, then type /exit
    3. Run:  pip install claude-agent-sdk
    4. Run this check again.

  An API key (e.g. from the monthly credits a Max plan includes):
    1. pip install anthropic
    2. Put ANTHROPIC_API_KEY=sk-ant-... in a file named .env in the project folder
    3. Run this check again.
"""

TEST_INSTRUCTIONS = ("You are testing a connection. Answer with exactly this JSON and nothing else: "
                     '{"note":"connection works","actions":[]}')


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    try:
        backend = get_backend()
    except BackendUnavailable as e:
        print("The AI strategist can't connect yet:")
        for part in str(e).split("; "):
            print("  -", part)
        print(HELP)
        return 1

    print(f"Using: {backend.name} ({'API key' if backend.name == 'api' else 'your Claude subscription'})")
    print("Asking Claude a one-line test question...")
    try:
        reply = backend.ask(TEST_INSTRUCTIONS, "Test.", important=False)
    except Exception as e:  # noqa: BLE001 - show any connection problem plainly
        print(f"FAILED: {type(e).__name__}: {e}")
        if backend.name == "subscription":
            print("\nIf it says you're not signed in: run `claude`, sign in, type /exit, and try again.")
        else:
            print("\nCheck the key in .env, and that its Console organization has credits.")
        return 1

    answer = check_answer(reply.text, set(), set(), set())
    ok = answer.note == "connection works"
    print(f"Reply: {reply.text.strip()[:200]}")
    print(f"Model: {reply.model}")
    print(f"Tokens: {reply.input_tokens} in, {reply.output_tokens} out, "
          f"{reply.cache_write_tokens} cache-write, {reply.cache_read_tokens} cache-read "
          f"(counts as {reply.budget_tokens} against the token bank)")
    print("\nConnection works." if ok else "\nConnected, but the reply wasn't in the expected format.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
