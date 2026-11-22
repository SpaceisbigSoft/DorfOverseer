"""(r7) A split brain module's SOURCE text as when it was one file, for the tests
that read the source itself (not run it). Not a test file (run_all runs test_*.py).

    py_family_src("overseer")         the parts put back in place of their import lines (old order)
    py_family_src("planner_wells")    the original followed by its parts
    py_parts(name), py_family(name)   the parts / the module and its parts, by module name

(merged from the six r7 groups' copies: d1 overseer, d2 planner, d3 planner_core (parts found from
its imports), d4 industry/building/wells, d5 military/gates, d6 planner_config)
"""

from __future__ import annotations

import re
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent / "brain"
BRAIN_DIR = BRAIN

PY_SPLIT = {
    "overseer": ("overseer_words", "overseer_cycle", "overseer_world", "overseer_loop"),          # d1 (a tuple: its test)
    "planner": ["planner_select", "planner_record", "planner_cycle"],                            # d2
    "planner_industry": ["planner_industry_disposal", "planner_industry_stone", "planner_industry_crafts"],
    "planner_building": ["planner_building_stores", "planner_building_rooms"],                  # d4
    "planner_wells": ["planner_wells_caverns", "planner_wells_water"],                          # d4
    "planner_military": ["planner_military_squads", "planner_military_threats"],                # d5
    "planner_gates": ["planner_gates_stuck", "planner_gates_lockdown"],                         # d5
    "planner_config": ["planner_config_base", "planner_config_society", "planner_config_works",
                       "planner_config_features", "planner_config_rounds"],                    # d6
}
PY_PARTS = PY_SPLIT
PARTS = PY_SPLIT
INLINE = {"overseer"}          # read in the old order: each part in place of its `from <part> import *` line


def _stem(name: str) -> str:
    return name[:-3] if name.endswith(".py") else name


def py_parts(name: str) -> list:
    """The parts split off brain/<name>.py, in order ([] for an unsplit module). planner_core's
    (d3) are found from its own imports (`from planner_core_<theme> import`)."""
    stem = _stem(name)
    if stem in PY_SPLIT:
        return list(PY_SPLIT[stem])
    src = (BRAIN / f"{stem}.py").read_text(encoding="utf-8")
    out = []
    for m in re.finditer(rf"^from ({re.escape(stem)}_\w+) import", src, re.M):
        if m.group(1) not in out and (BRAIN / f"{m.group(1)}.py").exists():
            out.append(m.group(1))
    return out


def py_family(name: str) -> list:
    """The module and its parts, as names (an unsplit module: itself alone)."""
    return [_stem(name)] + py_parts(name)


def py_family_src(name: str) -> str:
    stem = _stem(name)
    out = (BRAIN / f"{stem}.py").read_text(encoding="utf-8")
    if stem in INLINE:
        for p in py_parts(stem):
            part = (BRAIN / f"{p}.py").read_text(encoding="utf-8")
            line = re.search(rf"^from {p} import \*.*$", out, re.M)
            assert line, f"{stem}.py no longer imports {p}"
            out = out[:line.start()] + part + out[line.end():]
        return out
    for p in py_parts(stem):
        out += "\n" + (BRAIN / f"{p}.py").read_text(encoding="utf-8")
    return out
