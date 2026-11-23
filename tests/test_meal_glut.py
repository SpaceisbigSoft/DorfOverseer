"""(0.105.78) No meals cooked past three times their target (D, 22 Nov: 2,532
servings for 17 dwarves; the stock rotted and its miasma disgusted the fort):
brain/planner_guards.meal_glut_filter, and its place in planner.plan.

    python tests/test_meal_glut.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner_core import Proposal  # noqa: E402
from planner import PLANNER_CONFIG  # noqa: E402
import planner_guards as G  # noqa: E402

CFG = dict(PLANNER_CONFIG)


def props():
    return [Proposal("meal_variety", {"type": "work_order", "recipe": "prepare_easy_meal", "amount": 3}, "v", 6),
            Proposal("stress_care", {"type": "work_order", "recipe": "prepare_lavish_meal", "amount": 5}, "s", 5),
            Proposal("drink", {"type": "work_order", "recipe": "brew_drink", "amount": 5}, "d", 4),
            Proposal("bolts", {"type": "assign_bolts", "limit": 7}, "b", 6)]


def state(meals, pop=17):
    return {"stocks": {"prepared_meals": meals}, "dwarves": {"total": pop}}


@test("D's glut (2,532 servings, 17 dwarves): every meal order held, the rest kept, one note")
def _():
    notes = []
    kept = G.meal_glut_filter(state(2532), CFG, props(), notes)
    assert [p.rule for p in kept] == ["drink", "bolts"], kept
    assert len(notes) == 1 and "meal_variety" in notes[0] and "stress_care" in notes[0] and "2532" in notes[0], notes


@test("under three times the target: nothing held")
def _():
    cap = 17 * CFG["meals_per_dwarf"] * CFG["kitchen_ban_meals_factor"]
    notes = []
    kept = G.meal_glut_filter(state(cap - 1), CFG, props(), notes)
    assert len(kept) == 4 and not notes
    kept = G.meal_glut_filter(state(cap), CFG, props(), [])
    assert len(kept) == 2


@test("an unread stock, a bool, or no citizens holds nothing")
def _():
    for s in ({}, {"stocks": {}}, state(True), state(5000, pop=0), {"stocks": {"prepared_meals": 5000}}):
        assert len(G.meal_glut_filter(s, CFG, props(), [])) == 4, s


@test("the cap follows a calibrated meals_per_dwarf")
def _():
    cfg = dict(CFG, meals_per_dwarf=30)
    assert len(G.meal_glut_filter(state(2532), cfg, props(), [])) == 2      # 17*30*3 = 1530: 2,532 is over
    cfg = dict(CFG, meals_per_dwarf=60)
    assert len(G.meal_glut_filter(state(2532), cfg, props(), [])) == 4      # 3,060: under


@test("planner.plan runs the filter after the other guards")
def _():
    src = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")
    i, j = src.find("_guard(outdoor_filter"), src.find("_guard(meal_glut_filter")
    assert 0 < i < j, (i, j)


if __name__ == "__main__":
    finish()
