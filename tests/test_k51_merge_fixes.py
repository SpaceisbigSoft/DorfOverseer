"""(0.105.51 merge) The merge's own fixes: a dwarf in a strange mood is never
put in the calm-down or near-gates burrows (R3: moods failed inside the AI's
burrows); the hunt never goes after a thief among a crowd.

    python tests/test_k51_merge_fixes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import split_src  # noqa: E402  (r9) ai-society-burrows split

sys.path.insert(0, str(ROOT / "brain"))
import planner_hunt  # noqa: E402
from planner_core import PLANNER_CONFIG  # noqa: E402


@test("calm-down and near-gates burrows skip a dwarf in a mood (source)")
def _():
    calm = split_src("ai-society-burrows.lua")   # (r9) the hub and its parts
    i = calm.index("function calm_burrow_tick")
    assert "not in_mood(u)" in calm[i:i + 4000]
    ng = (ROOT / "lua" / "ai-near-gates.lua").read_text(encoding="utf-8")
    assert "mood >= 0 then v = 'skip'" in ng


@test("hunt: a thief in a crowd is not hunted; one alone may be")
def _():
    def state(crowd):
        th = {"id": 5, "name": "a thief", "thief": "thief", "crowd": crowd, "location": "INN_TAVERN" if crowd else None,
              "can_reach_dwarves": False, "pos": {"x": 1, "y": 1, "z": 1}}
        return {"date": {"year": 252, "tick": 1000}, "settings": {},
                "others_on_map": {"threats": [th]},
                "hunt": {"targets": [{"id": 5, "name": "a thief", "thief": True, "can_reach_dwarves": False}]},
                "military": {"squads": []}}
    props, notes = [], []
    orig = planner_hunt._blocked
    planner_hunt._blocked = lambda *a, **k: None          # the fort's other holds aren't this test's
    try:
        planner_hunt._hunt_rule(state(4), dict(PLANNER_CONFIG), props, notes)
    finally:
        planner_hunt._blocked = orig
    assert any("among a crowd" in n for n in notes), notes


finish()
