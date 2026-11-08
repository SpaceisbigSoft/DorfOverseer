"""Measure how many tokens each way of describing the fort costs.

Uses the newest fort report in logs/snapshots/ (run show_fort.py first).

Without an API key it estimates (about 2.5 characters per token on current
Claude models). With a key it asks Anthropic's token-counting endpoint for
exact numbers. Counting is free; it does not run the model.

    python brain/tools/token_test.py

To get exact counts:
    pip install anthropic
    put ANTHROPIC_API_KEY=sk-ant-... in a file named .env in the project folder
    (.env is in .gitignore, so it never ends up in git)
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # (13c) brain/tools/ -> brain/

from digest import _latest_snapshots, diff, digest  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent.parent
CHARS_PER_TOKEN = 2.5
MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]


def load_key() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    env = PROJECT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    return None


def variants(snaps: list[Path]) -> list[tuple[str, str]]:
    raw = snaps[-1].read_text(encoding="utf-8")
    s = json.loads(raw)
    s.pop("_meta", None)
    no_units = copy.deepcopy(s)
    no_units.pop("units", None)
    out = [
        ("Full report, as saved", raw),
        ("Full report, minified", json.dumps(s, separators=(",", ":"), ensure_ascii=False)),
        ("Report without per-dwarf list", json.dumps(no_units, separators=(",", ":"), ensure_ascii=False)),
        ("Compact digest", digest(s)),
    ]
    if len(snaps) >= 2:
        older = json.loads(snaps[-2].read_text(encoding="utf-8"))
        out.append((f"Change-only diff vs {snaps[-2].name}", diff(older, s)))
    return out


def main() -> int:
    snaps = _latest_snapshots(2)
    if not snaps:
        print("No fort reports yet. Run: python brain/show_fort.py")
        return 1
    rows = variants(snaps)
    key = load_key()

    counter = None
    if key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)

            def counter(model: str, text: str) -> int:
                msgs = [{"role": "user", "content": text}]
                empty = [{"role": "user", "content": "."}]
                full = client.messages.count_tokens(model=model, messages=msgs).input_tokens
                base = client.messages.count_tokens(model=model, messages=empty).input_tokens
                return full - base + 1
        except ImportError:
            print("Found an API key but the anthropic package isn't installed: pip install anthropic\n")

    print(f"Fort report: {snaps[-1].name}\n")
    if counter:
        print(f"{'Variant':40s} {'chars':>8s}  " + "  ".join(f"{m:>18s}" for m in MODELS))
        for name, text in rows:
            counts = [counter(m, text) for m in MODELS]
            print(f"{name[:40]:40s} {len(text):>8,}  " + "  ".join(f"{c:>18,}" for c in counts))
        print("\nExact counts from Anthropic's token-counting endpoint (free; nothing was run).")
    else:
        base = len(rows[0][1]) / CHARS_PER_TOKEN
        print(f"{'Variant':40s} {'chars':>8s} {'~tokens':>9s} {'vs full':>8s}")
        for name, text in rows:
            tok = len(text) / CHARS_PER_TOKEN
            print(f"{name[:40]:40s} {len(text):>8,} {tok:>9,.0f} {tok / base * 100:>7.1f}%")
        print(f"\nEstimates at {CHARS_PER_TOKEN} characters per token. For exact counts, see the top of this file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
