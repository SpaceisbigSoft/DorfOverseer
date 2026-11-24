"""(0.105.96) Werebeast citizens reach their moon cells in time.

Live 23 Nov, B (the Monastery): two citizens carried the werepanther curse.
The planner sent each to a moon cell only 3 phases (~3 days) before the full
moon; B runs ~1300 ticks a keeper cycle, so that was 2-3 cycles. Both were in
squads (Mafol the captain of the guard, Ineth a wrestler): the squads' orders
took them past the cell's burrow, they "waited" 4 cycles each, changed outside
and killed a bone doctor before the militia shot them. Now: the cursed go in
8 phases ahead; moon_cell takes a soldier out of the squad first; the squad
fill never drafts a cursed dwarf back.

    python tests/test_r96_were.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402

import planner_threats as PT  # noqa: E402
from planner import Memory, plan  # noqa: E402

B_CHANGES = [{"phase": 27, "tick": 105450000}]


def fort(were):
    from test_threats import fort as tfort
    return tfort({"were": were})


@test("B's case: a cursed citizen goes in 8 phases before the change (phases 19-27, 0-1), not at 18 or 2-17")
def _():
    rows = [{"id": 17327, "name": "Mafol", "by_syndrome": True}]
    got = {}
    for ph in range(28):
        s = fort({"list": rows, "changes": B_CHANGES, "moon_phase": ph, "cells": []})
        got[ph] = bool([p for p in plan(s, Memory())[0] if p.rule == "moon_cell" and not p.action.get("release")])
    assert [p for p, v in got.items() if v] == [0, 1] + list(range(19, 28)), got
    assert PT.WERE_LEAD_PHASES == 8


@test("moon_phase_due itself is unchanged (the lead is the were rule's own config copy)")
def _():
    from planner import PLANNER_CONFIG
    due = [p for p in range(28) if PT.moon_phase_due(B_CHANGES, p, PLANNER_CONFIG)]
    assert due == [0, 1, 24, 25, 26, 27], due


@test("lua: moon_cell takes a cursed soldier out of the squad (removeFromSquad, said in unsquad) before the cell; "
      "the squad fill's draftable refuses a cursed dwarf; both files compile")
def _():
    act = (ROOT / "lua" / "ai-threats-actions.lua").read_text(encoding="utf-8")
    body = act[act.index("function moon_cell("):]
    i = body.index("dfhack.military.removeFromSquad(u.id)")
    assert i < body.index("cell_room(u.pos, taken, u.id)") and "out.unsquad" in body[:i + 400]
    draft = (ROOT / "lua" / "ai-military-draft.lua").read_text(encoding="utf-8")
    d = draft[draft.index("function draftable("):]
    assert d.index("were_cursed(u)") < d.index("local ok, yes = pcall")
    need_lua()
    from lupa.lua53 import LuaRuntime
    f = LuaRuntime().eval("function(s) local f, e = load(s, 'b', 't', {}) return e end")
    for src in (act, draft):
        assert f(src) is None, f(src)


finish()
