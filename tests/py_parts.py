"""(r7 file split) Support for tests that read a brain module's SOURCE text.

A large brain/<name>.py was split into parts brain/<name>_<theme>.py that it
re-exports (`from <name>_<theme> import (...)`). A test that asserts on the
module's text reads `py_family_src(name)`: the original's text followed by
each part's it imports, in the order it imports them, so a line that moved
to a part is still found.

Not a test file itself (run_all runs test_*.py only).
"""

from __future__ import annotations

import re
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent / "brain"


def py_parts(name: str) -> list[str]:
    """The parts brain/<name>.py imports from (brain/<name>_*.py), in import order."""
    src = (BRAIN / f"{name}.py").read_text(encoding="utf-8")
    out = []
    for m in re.finditer(rf"^from ({re.escape(name)}_\w+) import", src, re.M):
        if m.group(1) not in out and (BRAIN / f"{m.group(1)}.py").exists():
            out.append(m.group(1))
    return out


def py_family_src(name: str) -> str:
    """brain/<name>.py's text, then each of its parts' (see py_parts)."""
    return "\n".join((BRAIN / f"{n}.py").read_text(encoding="utf-8") for n in [name] + py_parts(name))
