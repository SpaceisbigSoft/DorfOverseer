"""(r7) A split Python module's text as when it was one file: brain/<name>.py
and the parts split off it (brain/<name>_<theme>.py), for the tests that read
source. PY_SPLIT names each split module's parts in the order they apply."""

from pathlib import Path

BRAIN_DIR = Path(__file__).resolve().parent.parent / "brain"

# (r7 d6) planner_config's themed parts, in the order planner_config applies them
PY_SPLIT = {
    "planner_config": ["planner_config_base", "planner_config_society", "planner_config_works",
                       "planner_config_features", "planner_config_rounds"],
}


def py_parts(name: str) -> list:
    """The parts split off brain/<name>.py, in order ([] for an unsplit module)."""
    return list(PY_SPLIT.get(name[:-3] if name.endswith(".py") else name, []))


def py_family_src(name: str) -> str:
    """brain/<name>.py's text followed by each of its parts' texts."""
    stem = name[:-3] if name.endswith(".py") else name
    out = (BRAIN_DIR / (stem + ".py")).read_text(encoding="utf-8")
    for p in py_parts(stem):
        out += "\n" + (BRAIN_DIR / (p + ".py")).read_text(encoding="utf-8")
    return out
