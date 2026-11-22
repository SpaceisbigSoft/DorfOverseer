"""(r7) Support for the tests that read a brain module's SOURCE text: a module
split into parts (whole functions moved, the original re-exporting them) is
read as the original's text followed by its parts' texts, so a test that
looks for a line in "the module" still finds it wherever the line now lives.

    from py_parts import py_family_src
    src = py_family_src("planner_wells")       # planner_wells.py + its parts

Not a test file itself (run_all runs test_*.py only).
"""

from __future__ import annotations

from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent / "brain"

# the original -> its parts, in the order the original imports them
PARTS = {
    # (r7 d4)
    "planner_industry": ["planner_industry_disposal", "planner_industry_stone", "planner_industry_crafts"],
    "planner_building": ["planner_building_stores", "planner_building_rooms"],
    "planner_wells": ["planner_wells_caverns", "planner_wells_water"],
}


def py_family(name: str) -> list:
    """The module and its parts, as names (a module not split: itself alone)."""
    name = name[:-3] if name.endswith(".py") else name
    return [name] + list(PARTS.get(name, []))


def py_family_src(name: str) -> str:
    """The source text of brain/<name>.py followed by its parts' (if split)."""
    return "".join((BRAIN / f"{m}.py").read_text(encoding="utf-8") for m in py_family(name))
