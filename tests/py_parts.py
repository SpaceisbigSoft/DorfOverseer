"""(r7) Support for the tests that read a brain module's source text: a
module split into parts in r7 (the original re-exports every name) is read
as the original followed by its parts, so a test that looks for a line in
`brain/<name>.py` still finds it wherever the line went.

Not a test file itself (run_all runs test_*.py only).
"""

from __future__ import annotations

from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent / "brain"

# the original module -> its parts (in the order the original imports them)
PY_PARTS = {
    "planner_military": ["planner_military_squads", "planner_military_threats"],   # (r7 d5)
    "planner_gates": ["planner_gates_stuck", "planner_gates_lockdown"],            # (r7 d5)
}


def py_family(name: str) -> list[str]:
    """The module and its parts, by module name."""
    return [name] + list(PY_PARTS.get(name, []))


def py_family_src(name: str) -> str:
    """brain/<name>.py's source followed by its parts' sources."""
    return "".join((BRAIN / f"{n}.py").read_text(encoding="utf-8") for n in py_family(name))
