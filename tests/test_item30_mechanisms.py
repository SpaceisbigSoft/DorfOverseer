"""(0.105.119 item30) Enough free mechanisms for every lever link waiting.

Journal, 25 Nov 15:00-18:30: A's were cells refused 33 times ("a link needs 2
free mechanisms (1 free; 1 where no dwarf can walk)"), E's "(1 free; 1 an
artifact)", D's gate lever 22 and kill zone 12 ("(0 free)"): each rule
ordered its own two only while no mechanisms order was queued. Now
planner_mechanisms._mechanism_stock_rule adds up what every waiting link
needs (were cells first, then gates, kill zones, buildingplan's parts),
weighs it against the free, queued and proposed mechanisms, and orders the
shortfall and a reserve (urgent while a werebeast citizen is known); with
no Mechanic's workshop one is built, with no mechanic the labour is given.
The link actions say how many free mechanisms they found, apart from the
held ones (ai-gates link_lever, ai-werecells link).

    python tests/test_item30_mechanisms.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402

import hold_classes as H  # noqa: E402
import planner_mechanisms as PM  # noqa: E402
from planner import Memory, plan, PLANNER_CONFIG  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
WERE = [{"id": 1, "name": "Dodok"}]


def fort(free=0, were=None, cells=None, orders=(), **kw) -> dict:
    s = copy.deepcopy(BASE)
    s["stocks"]["mechanisms"] = free
    s["stocks"]["mechanisms_free"] = free
    s["orders"] = list(orders)
    s["threats"] = {"were": {"list": list(were or []), "were_cells": dict(cells or {})}}
    s.update(kw)
    return s


def run(s, proposals=None):
    props, notes = list(proposals or []), []
    PM._mechanism_stock_rule(s, PLANNER_CONFIG, props, notes)
    return [p for p in props if p.rule == "mechanism_stock"], notes


@test("mechanism: were cells' links waiting, none free: the shortfall and the reserve, urgent with a werebeast")
def _():
    s = fort(0, WERE, {"n": 3, "built": 3, "unlinked": 3})
    props, _ = run(s)
    assert len(props) == 1, props
    p = props[0]
    assert p.action == {"type": "work_order", "recipe": "mechanisms", "amount": 6 + 4}, p.action
    assert p.priority == 2 and p.is_order and "Dodok" in p.reason and "were cells: 6" in p.reason, p.reason
    # no werebeast now: the same order, not urgent
    props, _ = run(fort(0, [], {"n": 3, "built": 3, "unlinked": 3}))
    assert props[0].priority == 5 and props[0].action["amount"] == 10, props
    # cells still to build: a lever and its link each
    props, _ = run(fort(0, WERE, {"n": 2, "built": 0}))
    assert props[0].action["amount"] == 6 + 4, props[0].action


@test("mechanism: free, queued and proposed ones count; enough: nothing; the order is capped")
def _():
    cells = {"n": 3, "built": 3, "unlinked": 3}
    assert not run(fort(10, WERE, cells))[0]                                  # 6 + 4 free
    q = [{"recipe": "mechanisms", "amount_left": 4, "amount_total": 4, "by_ai": True}]
    props, _ = run(fort(3, WERE, cells, q))
    assert props[0].action["amount"] == 3 and "4 on order" in props[0].reason, props[0].reason
    from planner_core import Proposal
    other = Proposal("mechanisms", {"type": "work_order", "recipe": "mechanisms", "amount": 2}, "spare", 7, True)
    props, _ = run(fort(3, WERE, cells, q), [other])
    assert props[0].action["amount"] == 1, props[0].action
    props, _ = run(fort(0, WERE, {"n": 16, "built": 0}))
    assert props[0].action["amount"] == PLANNER_CONFIG["mechanism_order_max"], props[0].action
    assert not run(fort(0, [], {}))[0]                                        # nothing waits: nothing


@test("mechanism: gates, kill zones and buildingplan's parts are counted; one bridge counted once")
def _():
    ent = {"entrances": [{"id": 1, "x": 5, "y": 5, "z": 5, "bridges_unworked": [70, 71]}],
           "free_levers": [{"id": 9, "x": 50, "y": 50, "z": 5}], "free_mechanisms": 0}
    kz = {"entrances": [{"id": 1, "x": 5, "y": 5, "z": 5, "drawbridge": {"built": True, "id": 71, "linked": False}},
                        {"id": 2, "x": 8, "y": 8, "z": 5, "drawbridge": {"built": True, "id": 80, "linked": False}}]}
    planned = {"list": [{"kind": "Trap", "items": [{"want": "3 Mechanisms"}]}]}
    s = fort(0, [], {}, entrances=ent, killzones=kz, planned=planned)
    d = {w: n for w, n, _ in PM.mechanism_demand(s)}
    # gates: two bridges' links (4) and a lever beyond the one free (1); kill zone: bridge 80 only
    assert d == {"gates": 5, "kill zones": 2, "the rest": 3}, d
    props, _ = run(s)
    assert props[0].action["amount"] == 10 + 4 and props[0].priority == 5, props[0].action
    # the were cells come first in the words
    s["threats"]["were"]["were_cells"] = {"n": 1, "built": 1, "unlinked": 1}
    assert [w for w, _, _ in PM.mechanism_demand(s)][0] == "were cells"


@test("mechanism: no Mechanic's workshop: one built (not while workshops are dug); no mechanic: the labour")
def _():
    s = fort(0, WERE, {"n": 2, "built": 2, "unlinked": 2})
    s["buildings"]["workshops"].pop("Mechanics")
    props, _ = run(s)
    assert props[0].action == {"type": "start_project", "kind": "workshops", "shops": ["Mechanics"],
                               "urgent": True}, props[0].action
    s["projects"] = {"open": [{"kind": "workshops", "furnish": {"days": 1}}]}
    props, notes = run(s)
    assert not props and any("once the workshops" in n for n in notes), notes
    s = fort(0, WERE, {"n": 2, "built": 2, "unlinked": 2}, order_desk={"labor_holders": {"MECHANIC": 0}})
    props, _ = run(s)
    assert props[0].action == {"type": "assign_labor", "job": "MECHANIC", "count": 1}, props[0].action
    s["order_desk"]["labor_holders"]["MECHANIC"] = 5
    assert run(s)[0][0].action["type"] == "work_order"


@test("mechanism: a were_cells level being dug counts its levers and links ahead")
def _():
    s = fort(0, WERE, {}, projects={"open": [{"kind": "were_cells", "cells": 2, "phase": "dig"}]})
    props, _ = run(s)
    assert props and props[0].action["amount"] == 6 + 4 and "being dug" in props[0].reason, props


@test("mechanism: D's cause: ordered only up to the ordinary stone there is; short of it, a quarry")
def _():
    cells = {"n": 3, "built": 3, "unlinked": 3}
    su = {"usable": 3, "economic": {"MAGNETITE": {"n": 53, "ore": True}}, "forbidden": 0}
    s = fort(0, WERE, cells, stone_use=su, labor={"dig": 1395})
    props, notes = [], []
    PM._mechanism_stock_rule(s, PLANNER_CONFIG, props, notes, Memory())
    m = [p for p in props if p.rule == "mechanism_stock"]
    q = [p for p in props if p.rule == "quarry"]
    assert m and m[0].action["amount"] == 3, props                       # not 10: 3 boulders
    assert q and q[0].action["type"] == "quarry" and "3 boulders" in q[0].reason, props
    # none usable: no order (it would stand still), the quarry only
    s["stone_use"]["usable"] = 1
    props, notes = [], []
    PM._mechanism_stock_rule(s, PLANNER_CONFIG, props, notes, Memory())
    assert [p.rule for p in props] == ["quarry"] and any("none ordered" in n for n in notes), (props, notes)
    # a quarry another rule proposed: not twice
    from planner_core import Proposal
    props = [Proposal("quarry", {"type": "quarry", "count": 10}, "stone", 4)]
    PM._mechanism_stock_rule(s, PLANNER_CONFIG, props, [], Memory())
    assert [p.rule for p in props] == ["quarry"], props
    # stone enough: no quarry
    s["stone_use"]["usable"] = 40
    props = []
    PM._mechanism_stock_rule(s, PLANNER_CONFIG, props, [], Memory())
    assert [p.rule for p in props] == ["mechanism_stock"] and props[0].action["amount"] == 10, props


@test("mechanism: an old stuck cancel of mechanisms holds no mechanism_stock order (it is sized to the stone)")
def _():
    from planner_core import STUCK_HOLD_EXEMPT
    assert "mechanism_stock" in STUCK_HOLD_EXEMPT
    s = fort(0, WERE, {"n": 3, "built": 3, "unlinked": 3})
    mem = Memory()
    from planner import abs_tick
    mem.stuck_cancelled = {"mechanisms": {"tick": abs_tick(s) - 1200, "n": 1}}
    props, _ = plan(s, mem)
    assert any(p.rule == "mechanism_stock" and p.action.get("recipe") == "mechanisms" for p in props), \
        [(p.rule, p.action) for p in props if "mechan" in p.rule]


@test("mechanism: wiring: plan() proposes it, defence class, config keys")
def _():
    s = fort(0, WERE, {"n": 3, "built": 3, "unlinked": 3})
    props, _ = plan(s, Memory())
    m = [p for p in props if p.rule == "mechanism_stock"]
    assert m and m[0].action == {"type": "work_order", "recipe": "mechanisms", "amount": 10}, m
    import planner
    assert planner._mechanism_stock_rule is PM._mechanism_stock_rule
    src = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")
    assert src.index("_guard(_mechanism_stock_rule") > src.index("_guard(_spare_mechanisms_rule")
    assert src.index("_guard(_mechanism_stock_rule") > src.index("_guard(_killzone_rule")
    assert H.RULE_CLASS["mechanism_stock"] == H.DEFENCE
    for k in ("mechanism_reserve", "mechanism_order_max", "mechanism_stock_cooldown_ticks"):
        assert k in PLANNER_CONFIG, k


WERE_LINK = r"""
local src = ...
local G = {links = {}}
local e = setmetatable({G = G}, {__index = _G})
e.df = {job_type = {LinkBuildingToTrigger = 'Link'}}
G.gates = {lever_links = function() return G.links end,
           link_lever = function(l, t, dry) return {ok = false, error = 'a link needs 2 free mechanisms (1 free; 1 an artifact)',
                                                    mechanisms = 1, free_mechanisms = 1, held_mechanisms = {['an artifact'] = 1},
                                                    mechanisms_needed = 2} end,
           name_at = function() end}
e.reqscript = function(n) if n == 'ai-gates' then return G.gates end error('reqscript ' .. tostring(n)) end
assert(load(src, 'ai-werecells', 't', e))()
e.cells = function() return {{key = 'were:7:1'}, {key = 'were:7:2'}} end
e.cell_state = function(c) return {built = true, linked = false, lever_id = 1, bridge_id = 2} end
return e
"""


@test("mechanism lua: were_cells' refusal says the free mechanisms found, the held ones and the need")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    from lua_modules_util import module_src
    lua = LuaRuntime(unpack_returned_tuples=True)
    E = lua.execute(WERE_LINK, module_src("ai-werecells.lua"))
    r = E.link(False)
    assert not r.ok and r.free_mechanisms == 1 and r.mechanisms_needed == 4, dict(r)
    assert r.held_mechanisms["an artifact"] == 1 and "1 an artifact" in r.error, dict(r)


@test("mechanism lua: link_lever's refusal carries free_mechanisms apart from the held ones (source)")
def _():
    src = (ROOT / "lua" / "ai-gates-works.lua").read_text(encoding="utf-8")
    assert "free_mechanisms = #mechs, held_mechanisms = okc and c.why or nil" in src
    assert len(src.replace("\r", "").encode("utf-8")) < 60000


if __name__ == "__main__":
    finish()
