"""(0.105.76) Werebeast citizens found by their curse, before they change.

Live 22 Nov, E (the Deep mine): 20 citizen deaths in an hour; bitten citizens
turned at four full moons (22:15, 22:27, 22:42, 22:44), each found only once it
had changed ("certain: the game's own curse flag"), so the moon cells never
locked anyone: the were report's list stayed empty (`list: []`) while its
`changes` held four, all at moon phase 27, ~25.5 days apart (the planner's
28-day moon slipped ~2.5 days each turn). DF's curse is a syndrome of class
WERECURSE (data/vanilla interaction_werebeast.txt) from the bite on.

    python tests/test_r76_werecurse.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402

import planner_threats as PT  # noqa: E402
from planner import Memory, plan, PLANNER_CONFIG  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

E_CHANGES = [{"phase": 27, "tick": 102319490}, {"phase": 27, "tick": 102349895},
             {"phase": 27, "tick": 102380800}, {"phase": 27, "tick": 102411763}]


@test("moon_phase_due: E's changes at phase 27: due 3 phases before it (24-26), at it, and 2 after (0-1); not at "
      "23 (E's phase at 22:58) or 2; no phase seen or unread: None (the tick count as before)")
def _():
    due = {p: PT.moon_phase_due(E_CHANGES, p, PLANNER_CONFIG) for p in range(28)}
    assert [p for p, d in due.items() if d] == [0, 1, 24, 25, 26, 27], due
    assert PT.moon_phase_due([{"tick": 5}], 27, PLANNER_CONFIG) is None
    assert PT.moon_phase_due(E_CHANGES, None, PLANNER_CONFIG) is None


def fort(were):
    from test_threats import fort as tfort
    return tfort({"were": were})


@test("plan: a citizen cursed by the syndrome (not changed yet), E's changes, phase 26: into a cell; at phase 18 (0.105.96: 8 phases' lead; was 23): "
      "nothing yet; the 28-day count no longer decides when phases are known")
def _():
    rows = [{"id": 18102, "name": "Urist", "by_syndrome": True}]
    s = fort({"list": rows, "changes": E_CHANGES, "moon_phase": 26, "cells": []})
    props = [p for p in plan(s, Memory())[0] if p.rule == "moon_cell"]
    # (0.105.115 item18) phase 26 is a phase before the change: moved in if still outside (move_in)
    assert props and props[0].action == {"type": "moon_cell", "ids": [18102], "move_in": True}, props
    s = fort({"list": rows, "changes": E_CHANGES, "moon_phase": 18, "cells": []})   # (0.105.96) the lead is 8 phases
    assert not [p for p in plan(s, Memory())[0] if p.rule == "moon_cell"]


@test("(verifier) the first moon: a citizen cursed by the syndrome and no change seen yet: DF's full moon "
      "(phase 27) is taken, locked at phase 24-27 and 0-1, not at 5; a row not by the syndrome still waits for a change")
def _():
    rows = [{"id": 7, "name": "Bitten", "by_syndrome": True}]
    for ph, want in ((24, True), (27, True), (0, True), (5, False)):
        s = fort({"list": rows, "changes": [], "moon_phase": ph, "cells": []})
        got = [p for p in plan(s, Memory())[0] if p.rule == "moon_cell"]
        assert bool(got) == want, (ph, got)
    s = fort({"list": [{"id": 8, "name": "Wolfy"}], "changes": [], "moon_phase": 27, "cells": []})
    assert not [p for p in plan(s, Memory())[0] if p.rule == "moon_cell"]


def _cursed_fn():
    src = (ROOT / "lua" / "ai-threats.lua").read_text(encoding="utf-8")
    m = re.search(r"^function were_cursed\(u\).*?^end\n", src, re.S | re.M)
    assert m, "were_cursed not found"
    return m.group(0)


@test("lua were_cursed: a WERECURSE syndrome (DF's syn_class strings) marks the citizen; another syndrome or none "
      "doesn't; an unreadable unit is not cursed")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package")
    L = LuaRuntime(unpack_returned_tuples=True)
    env = L.execute(r"""
local fn = ...
local env = setmetatable({}, {__index = _G})
env.df = {syndrome = {find = function(id)
  if id == 367 then return {syn_class = {{value = 'WERECURSE'}}} end
  if id == 12 then return {syn_class = {{value = 'POISON'}}} end
  if id == 13 then return {syn_class = {'WERECURSE'}} end
  return nil
end}}
assert(load(fn, 'f', 't', env))()
return env
""", _cursed_fn())
    unit = lambda ids: L.eval("function(ids) local a = {} for i, v in ipairs(ids) do a[i] = {type = v} end "
                              "return {syndromes = {active = a}} end")(L.table_from(ids))
    assert env.were_cursed(unit([12, 367])) is True
    assert env.were_cursed(unit([13])) is True          # a plain string entry
    assert env.were_cursed(unit([12])) is False and env.were_cursed(unit([])) is False
    assert env.were_cursed(L.eval("{}")) is False


@test("lua were_report reads were_cursed (by_syndrome) beside the change and isNightCreature")
def _():
    src = (ROOT / "lua" / "ai-threats.lua").read_text(encoding="utf-8")
    body = src[src.index("local function were_report("):src.index("-- great dangers on the surface")]
    assert "were_cursed(u)" in body and "by_syndrome" in body
    acts = (ROOT / "lua" / "ai-threats-actions.lua").read_text(encoding="utf-8")
    cell = acts[acts.index("local function cell_room("):acts.index("-- (0.105.40b fix) The doors ai-insane")]
    assert "next(zone_doors(z)) == nil" in cell and "z.assigned_unit_id == uid" in cell
    assert "cell_room(u.pos, taken, u.id)" in acts


if __name__ == "__main__":
    finish()
