"""(r8 s4) lua/ai-builder-wells.lua split by theme: the family's files (the
first one and the parts cut from it, as ai-builder.lua's PARTS loads them) and
their text together, for the tests that read "the wells file" by name."""

from __future__ import annotations

import re
from pathlib import Path

LUA_DIR = Path(__file__).resolve().parent.parent / "lua"


def wells_parts() -> list[str]:
    """'ai-builder-wells' and its later parts, in the hub's load order."""
    hub = (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8")
    listed = re.findall(r"'([\w-]+)'", re.search(r"^PARTS = \{([^}]*)\}", hub, re.M).group(1))
    return ["ai-builder-" + p for p in listed if p == "wells" or p.startswith("wells-")]


def wells_src() -> str:
    """The family's text in one piece (loads as one chunk too)."""
    return "\n".join((LUA_DIR / f"{n}.lua").read_text(encoding="utf-8") for n in wells_parts())
