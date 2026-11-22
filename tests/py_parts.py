"""(r7) Support for the tests that read a brain module's SOURCE text: a module
split into parts in r7 is read as the original followed by its parts, so a
test's `"x" in src` (or `"x" not in src`) still means what it did before the
split. The original comes first, so `src.index(...)` of text that stayed in it
is unchanged.

Not a test file itself (run_all runs test_*.py only).
"""

from __future__ import annotations

from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent / "brain"

# the original module -> the parts split out of it in r7, in order
PY_PARTS = {
    "planner": ("planner_select", "planner_record", "planner_cycle"),     # (r7 d2)
}


def py_family_src(name: str) -> str:
    """brain/<name>.py's text followed by each of its r7 parts' text."""
    return "\n".join((BRAIN / f"{n}.py").read_text(encoding="utf-8") for n in (name, *PY_PARTS.get(name, ())))
