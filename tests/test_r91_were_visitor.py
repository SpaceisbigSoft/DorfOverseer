"""(0.105.91) A werebeast visitor killed while it is a dwarf.

Live 23 Nov, C (the Merchant city): the representative Thob Letmosmozib, an
outsider carrying DF's werebeast curse (syndrome 344, class WERECURSE), walked
the fort as a dwarf, turned into a weregecko at the full moon (19:44) and
killed 6 (a baby, three children, a patient, a wrestler) in 17 s; seven squads
got kill orders once he changed, too late. 0.105.76's were list held citizens
only. The were report now lists cursed outsiders in their own form
(`were.outsiders`), and the planner sends one squad at them at once.

    python tests/test_r91_were_visitor.py
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
THOB = {"id": 5629, "name": "Thob Letmosmozib \"Cobaltswallows\", representative", "visitor": True, "hfid": 4580,
        "pos": {"x": 114, "y": 150, "z": 171}}


def sq(i, members=6, **kw):
    q = {"id": i, "name": f"Squad {i}", "members": members, "size": 10, "orders": 0, "ai_orders": 0,
         "power": {"power": 5000, "armed": members}}
    q.update(kw)
    return q


def fort(were, squads=None) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "summer"
    s["threats"] = {"were": were}
    if squads is not None:
        s["military"]["squads"] = squads
    return s


def attacks(props, uid=5629):
    return [p for p in props if p.rule == "squad_attack" and uid in (p.action.get("kill") or [])]


@test("C's Thob, cursed and a dwarf now, phase 1 (far from the full moon): one squad sent to kill him, the reason "
      "names the curse")
def _():
    s = fort({"list": [], "cells": [], "moon_phase": 1, "outsiders": [THOB]}, squads=[sq(185), sq(208)])
    a = attacks(plan(s, Memory())[0])
    assert len(a) == 1, a
    assert a[0].action["squad_id"] in (185, 208) and "werebeast visitor" in a[0].reason, a[0]


@test("a squad already after him: no second one, a note says so")
def _():
    s = fort({"list": [], "cells": [], "moon_phase": 20, "outsiders": [THOB]},
             squads=[sq(185, ai_orders=1, kill_ids=[5629]), sq(208)])
    props, notes = plan(s, Memory())
    assert not [p for p in attacks(props) if p.action["squad_id"] == 208], props
    assert any("is after them" in n for n in notes), notes


@test("a caged werebeast visitor: left alone; no outsiders: nothing")
def _():
    s = fort({"list": [], "cells": [], "moon_phase": 20, "outsiders": [dict(THOB, caged=True)]}, squads=[sq(185)])
    assert not attacks(plan(s, Memory())[0])
    s = fort({"list": [], "cells": [], "moon_phase": 20}, squads=[sq(185)])
    assert not attacks(plan(s, Memory())[0])


@test("no squad at all: a note, no order")
def _():
    s = fort({"list": [], "cells": [], "moon_phase": 20, "outsiders": [THOB]}, squads=[])
    props, notes = plan(s, Memory())
    assert not attacks(props), props
    assert any("werebeast visitor" in n and "no squad free" in n for n in notes), notes


@test("ai-threats.lua: were_report lists cursed outsiders (not own, not changed, were_cursed) in were.outsiders")
def _():
    src = (ROOT / "lua" / "ai-threats.lua").read_text(encoding="utf-8")
    body = src[src.index("local function were_report"):src.index("local function surface_report")]
    assert re.search(r"elseif not own and not changed\(u\) and were_cursed\(u\) then", body), body[:400]
    assert "out.outsiders" in body


@test("ai-threats.lua compiles under Lua 5.3")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime()
    src = (ROOT / "lua" / "ai-threats.lua").read_text(encoding="utf-8")
    f = lua.eval("function(s) local f, e = load(s, 'b', 't', {}) return e end")
    assert f(src) is None, f(src)


finish()
