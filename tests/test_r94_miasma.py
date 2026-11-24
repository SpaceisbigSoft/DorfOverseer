"""(0.105.94) F (the Garden fort): a ghost's memorial slab never engraved.

Live 23 Nov, F: Urvad's EngraveSlab order (09:38) had a job on a mason's bench
from the start, with no slab to take: F held no blank slab. Its one slab was a
bismuth bronze "Secrets" slab (engraving_type Secrets), and the supplies
report counted every slab as blank, so the planner's `slabs < ghosts` (1 < 1)
never held and no blank slab was ordered in 11 hours. The report now counts
blank slabs only (engraving_type Slab, -1). (F's miasma, the reason it was on
the list, had cleared by 20:30: unhappy 8%, from 48%, one miasma tile.)

    python tests/test_r94_miasma.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402

from planner import Memory, plan  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
SUP = (ROOT / "lua" / "ai-bridge-report-supplies.lua").read_text(encoding="utf-8")


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


@test("the supplies report counts blank slabs only (engraving_type Slab / -1), not engraved ones")
def _():
    i = SUP.index("each('SLAB'")
    body = SUP[i - 600:i + 300]
    assert re.search(r"it\.engraving_type == BLANK", body), body
    assert "df.slab_engraving_type.Slab" in body and "local BLANK = -1" in body


@test("F's case: one ghost, no blank slab (the Secrets slab no longer counted), autoslab, stone: a stone slab ordered")
def _():
    s = copy.deepcopy(BASE)
    s["dead"] = {"ghosts": 1, "ghost_names": ["Urvad"], "free_tombs": 24, "unburied": 1, "memorial_orders": 2}
    s["supplies"]["slabs"] = 0
    s["supplies"]["memorial_slabs"] = 0
    s["tools"] = dict(s.get("tools") or {}, autoslab=True)
    s["stone_use"] = {"usable": 30, "economic": {}}
    got = [p for p in by_rule(plan(s, Memory())[0], "slabs") if p.action.get("recipe") == "stone_slab"]
    assert got and got[0].action.get("amount", 0) >= 1, got
    s["supplies"]["slabs"] = 1                       # as the old count had it: nothing ordered
    assert not [p for p in by_rule(plan(s, Memory())[0], "slabs") if p.action.get("recipe") == "stone_slab"]


@test("ai-bridge-report-supplies.lua compiles under Lua 5.3")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    f = LuaRuntime().eval("function(s) local f, e = load(s, 'b', 't', {}) return e end")
    assert f(SUP) is None, f(SUP)


finish()
