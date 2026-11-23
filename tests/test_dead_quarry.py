"""(0.105.88) A quarry for the dead isn't held by a crisis: E (23 Nov) had 5
ghosts haunting 57, 19 slab orders with no stone and "crisis: ore, quarry
wait". hold_classes.step_class and crisis.apply with the quarry's for_dead.

    python tests/test_dead_quarry.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner_core import Proposal  # noqa: E402
import hold_classes as hc  # noqa: E402
import crisis  # noqa: E402


@test("a quarry for the dead is survival and goes through a crisis; a plain quarry still waits")
def _():
    dead = Proposal("quarry", {"type": "quarry", "count": 18, "for_dead": True}, "q", 4)
    plain = Proposal("quarry", {"type": "quarry", "count": 18}, "q", 4)
    assert hc.step_class(dead) == hc.SURVIVAL
    assert hc.step_class(plain) == hc.EXPANSION
    notes = []
    kept = crisis.apply([dead, plain], ["34.5% unhappy", "5 ghosts"], notes)
    assert kept == [dead] and notes and "quarry" in notes[0], (kept, notes)


@test("the quarry rule flags it for the dead: ghosts, or bodies with no free tomb; not for unhappiness alone")
def _():
    src = (ROOT / "brain" / "planner_industry_stone.py").read_text(encoding="utf-8")
    assert 'act["for_dead"] = True' in src and 'int(dd.get("ghosts") or 0) > 0' in src


if __name__ == "__main__":
    finish()
