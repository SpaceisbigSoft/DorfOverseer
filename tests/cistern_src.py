"""(r8 s8) lua/ai-builder-cistern.lua split by theme into three builder parts
(ai-builder-cistern, -cistern-status, -cistern-step, loaded in this order by
ai-builder.lua's PARTS). For the tests that read the cistern's text or load it
alone: the family's names from the hub's list, and the texts together (run in
one env they do what the parts do loaded one after another)."""

from __future__ import annotations

import re
from pathlib import Path

LUA_DIR = Path(__file__).resolve().parent.parent / "lua"


def builder_parts() -> list[str]:
    """ai-builder.lua's PARTS, in load order ('sites', ..., 'cistern', 'cistern-status', ...)."""
    hub = (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8")
    return re.findall(r"'([\w-]+)'", re.search(r"^PARTS = \{(.*?)\}", hub, re.M | re.S).group(1))


def cistern_parts() -> list[str]:
    """The cistern's files by stem, in load order."""
    return ["ai-builder-" + p for p in builder_parts() if p == "cistern" or p.startswith("cistern-")]


def cistern_src() -> str:
    """The cistern's text as when it was one file: the three files in load order."""
    return "\n".join((LUA_DIR / f"{n}.lua").read_text(encoding="utf-8") for n in cistern_parts())
