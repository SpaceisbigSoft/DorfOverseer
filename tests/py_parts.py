"""(r7) A split brain module's text as when it was one file, for the tests that
read the source itself (not run it).

    py_family_src("overseer")   brain/overseer.py with each part it imports
                                (`from overseer_<theme> import *`) put back in
                                place of that line, so the text reads in the
                                order it had before the split
"""

from __future__ import annotations

import re
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent / "brain"
PY_SPLIT = {"overseer": ("overseer_words", "overseer_cycle", "overseer_world", "overseer_loop")}


def py_family_src(name: str) -> str:
    stem = name[:-3] if name.endswith(".py") else name
    out = (BRAIN / (stem + ".py")).read_text(encoding="utf-8")
    for p in PY_SPLIT.get(stem, ()):
        part = (BRAIN / (p + ".py")).read_text(encoding="utf-8")
        line = re.search(rf"^from {p} import \*.*$", out, re.M)
        assert line, f"{stem}.py no longer imports {p}"
        out = out[:line.start()] + part + out[line.end():]
    return out
