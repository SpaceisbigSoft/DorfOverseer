"""(0.105.54 merge) The merge's own fixes: a peaceful fort keeps one melee
squad; a flier inside the fort may be fought in melee; the shelter's
hide-or-fight check hides from every beast melee can't close on.

    python tests/test_k54_merge_fixes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from py_parts import py_family_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
import planner_matchup as M  # noqa: E402
import planner_military as PM  # noqa: E402
from planner_core import PLANNER_CONFIG  # noqa: E402


@test("fight_bar: a flier outside is crossbows only; a flier inside may be met in melee")
def _():
    cfg = dict(PLANNER_CONFIG)
    out = M.fight_bar({"flier": True, "name": "a bat"}, cfg)
    inside = M.fight_bar({"flier": True, "name": "a bat", "inside": True}, cfg)
    assert out["ranged_only"] is True and inside["ranged_only"] is False, (out, inside)


@test("peaceful fort: its only melee squad is never turned to crossbows")
def _():
    src = py_family_src("planner_military")      # (r7) the module and its parts
    assert "if len([q for q in manned if not is_ranged(q)]) <= 1:" in src


@test("hiding: a dust-breathing great beast is hidden from like a fire breather")
def _():
    src = (ROOT / "brain" / "planner_army.py").read_text(encoding="utf-8")
    assert "melee_bar(threats[i])" in src
    assert M.melee_bar({"breath": ["dust"]}) and not M.melee_bar({"breath": []})


finish()
