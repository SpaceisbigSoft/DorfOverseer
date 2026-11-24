"""(0.105.99, verifier) The independent check's fixes.

- An urgent mood (thirsty, or stalled 20 days) cancelled every AI order in
  MOOD_CONSUMERS for its kind: a plant-cloth mood cancelled the AI's silk and
  yarn bag orders too, which select() doesn't hold (mood_blocked holds only
  the plant ones), so the bag rule placed them again and the mood cancelled
  them again, each cooldown. Now only the orders select() holds go.
- A log mood marked one more of the fort's underground trees each quarter
  day (the mood's cooldown) while the first stood marked: now it waits while
  one within reach is marked (the forestry report's inside.reach_marked).
- The fill's leader seat went to pick_soldiers(candidates()) unfiltered: a
  dwarf in a breakdown or a recent tantrum-thrower could be appointed the
  squad's captain (draft_bar kept them only from the other places).
- fight_of told any victim with a Conflict thought as a brawl: a dwarf killed
  by an invader or a beast in a fight. Now only a citizen killer's.

    python tests/test_r99_verifier.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

import planner_moods  # noqa: E402
from planner import Memory, PLANNER_CONFIG as CFG  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["orders"] = []
    s["buildings"]["workshops"].update({"Butchers": 1, "Farmers": 1, "Loom": 1, "Tanners": 1})
    s.setdefault("supplies", {})
    s["supplies"].update({"thread_kinds": {"plant": 0, "silk": 0, "yarn": 0}, "hospital": {"thread": 0, "cloth": 0}})
    return s


CLOTH = {"item": "CLOTH", "quantity": 1, "flags": ["plant"], "avail": {"trader": 20}}


@test("urgent plant-cloth mood: the AI's cloth bag cancelled, its silk and yarn bags kept (select holds only those)")
def _():
    s = fort()
    s["orders"] = [{"id": 1, "recipe": "cloth_bag", "by_ai": True, "amount_left": 3, "amount_total": 3},
                   {"id": 2, "recipe": "silk_bag", "by_ai": True, "amount_left": 3, "amount_total": 3},
                   {"id": 3, "recipe": "yarn_bag", "by_ai": True, "amount_left": 3, "amount_total": 3}]
    props, notes = [], []
    planner_moods._mood_materials(s, "Edzul", "Secretive", [copy.deepcopy(CLOTH)], 43, props, notes, CFG,
                                  memory=Memory(), unit_id=1, stalled=41, thirst=30000)
    cancels = sorted(p.action["order_id"] for p in props if p.action.get("type") == "cancel_work_order")
    assert cancels == [1], cancels
    # every cancelled recipe is one select() holds while the mood waits (no re-place, no re-cancel)
    s["moods"] = {"list": [{"craft": True, "missing": [CLOTH]}]}
    held, _ = planner_moods.mood_blocked(s)
    assert "cloth_bag" in held and "silk_bag" not in held, held


@test("a log mood waits while one underground tree within reach is marked (no tree marked each cooldown)")
def _():
    s = fort()
    log = {"item": "WOOD", "quantity": 1, "flags": [], "avail": {"free": 19, "reach": 0}}

    def run(inside):
        s["forestry"] = {"inside": inside}
        props, notes = [], []
        planner_moods._mood_materials(s, "Nil", "Fey", [copy.deepcopy(log)], 41, props, notes, CFG,
                                      memory=Memory(), unit_id=9, stalled=41)
        return [p.action for p in props if p.action.get("type") == "cavern_logging"], notes

    fell, _ = run({"reachable": 4, "marked": 0, "reach_marked": 0})
    assert len(fell) == 1, fell
    fell, notes = run({"reachable": 4, "marked": 1, "reach_marked": 1})
    assert fell == [], fell
    # marked out of reach only: one within reach is still marked
    fell, _ = run({"reachable": 4, "marked": 2, "reach_marked": 0})
    assert len(fell) == 1, fell
    # an older bridge (no reach_marked): any marked one waits
    fell, _ = run({"reachable": 4, "marked": 1})
    assert fell == [], fell


@test("Lua: the fill's leader seat passes draft_bar; fight_of only for a citizen killer; reach_marked reported")
def _():
    draft = (ROOT / "lua" / "ai-military-draft.lua").read_text(encoding="utf-8")
    i = draft.index("function fill(")
    seat = draft[i:draft.index("local places = {}", i)]
    assert "draft_bar(c.unit)" in seat and "pick_soldiers(pool, 1)" in seat, seat
    world = (ROOT / "lua" / "ai-bridge-report-world.lua").read_text(encoding="utf-8")
    assert "ev.kill_kind == nil and ev.killer_kind == 'citizen'" in world
    fo = (ROOT / "lua" / "ai-forestry.lua").read_text(encoding="utf-8")
    assert "reach_marked = 0" in fo and "b.reach_marked = (b.reach_marked or 0) + 1" in fo
    for f in ("ai-military-draft.lua", "ai-bridge-report-world.lua", "ai-forestry.lua"):
        assert (ROOT / "lua" / f).stat().st_size < 60 * 1024, f


if __name__ == "__main__":
    finish()
