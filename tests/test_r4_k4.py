"""(r4 k4, audit A7 B6 and B7) The strategist's own work orders, and its
proposals through the crisis and recovery holds.

B6: the bridge marks every order it makes `by_ai`; the strategist was shown
all of them as "YOUR OPEN ORDERS" and could cancel the planner's (drink
orders too). Now its orders are sent by="strategist", the bridge records
them apart (`by_strategist`), only those are shown to it and only those it
may cancel (checked in the brain and refused again in the bridge).

B7: crisis.apply and recovery_apply ran inside plan(); the review's
proposals were put in front afterwards, so a tavern level could start in a
crisis. Now they go through the same holds (review.hold_review_proposals,
called by the overseer), and a level the strategist chose is expansion.

    python tests/test_r4_k4.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, have_lua  # noqa: E402
from lua_modules_util import bridge_part_src  # noqa: E402
from py_parts import py_family_src  # noqa: E402  (r7) overseer.py and its parts

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, Proposal, abs_tick  # noqa: E402
from tokens import TokenBank  # noqa: E402
from backends import Reply  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
RECIPES = ["brew_drink", "stone_blocks", "prepare_fine_meal"]
TOOLS = ["autochop", "seedwatch"]
KINDS = ["tavern", "bedrooms", "dining", "library"]
LUA_DIR = ROOT / "lua"

PLANNER_ORDER = {"id": 1740, "recipe": "brew_drink", "amount_left": 20, "amount_total": 30, "by_ai": True}
AI_ORDER = {"id": 1801, "recipe": "stone_blocks", "amount_left": 5, "amount_total": 10, "by_ai": True,
            "by_strategist": True}
PLAYER_ORDER = {"id": 900, "recipe": "prepare_fine_meal", "amount_left": 3, "amount_total": 3, "by_ai": False}


def fort(orders=None) -> dict:
    s = copy.deepcopy(BASE)
    s["orders"] = copy.deepcopy(orders if orders is not None else [PLANNER_ORDER, AI_ORDER, PLAYER_ORDER])
    s["settings"] = dict(s.get("settings") or {}, traits={}, ai_frequency=100, ai_effort=100,
                         real_day_token_cap=0)
    return s


class Claude:
    """The fake model: one fixed answer, every call recorded (no network)."""

    def __init__(self, answer: dict):
        self.text = json.dumps(answer)
        self.messages = []

    def ask(self, instructions, message, important=False, effort=None, **kw):
        self.messages.append(message)
        return Reply(text=self.text, input_tokens=3000, output_tokens=200, model="m")


def review(answer: dict, orders=None, memory=None):
    from review import maybe_review
    s, m, c = fort(orders), memory or Memory(), Claude(answer)
    info = {"recipes": RECIPES, "tools": TOOLS, "level_kinds": KINDS}
    out = maybe_review(s, m, TokenBank(), c, info, [])
    assert c.messages, ("no review ran", out.say)
    return out, c, s, m


# --- B6: what the strategist is told is its own -------------------------------------------------

@test("B6: YOUR OPEN ORDERS lists only the strategist's own orders, never the planner's or the player's")
def _():
    from strategist import review_message
    msg = review_message(fort(), "routine", [], [], {}, [])
    line = next((x for x in msg.splitlines() if x.startswith("YOUR OPEN ORDERS")), "")
    assert "#1801" in line, msg[-600:]
    assert "#1740" not in line and "#900" not in line, line
    msg = review_message(fort([PLANNER_ORDER, PLAYER_ORDER]), "routine", [], [], {}, [])
    assert "YOUR OPEN ORDERS" not in msg, "the planner's orders shown as the strategist's"


@test("B6: in a whole review the message sent to the model shows the strategist's order only")
def _():
    _out, c, _s, _m = review({"note": "ok", "actions": []})
    line = next((x for x in c.messages[0].splitlines() if x.startswith("YOUR OPEN ORDERS")), "")
    assert "#1801" in line and "#1740" not in line, line


@test("B6: the strategist cannot cancel the planner's order (#1740 brew_drink); its own it can, marked")
def _():
    out, *_ = review({"note": "x", "actions": [{"type": "cancel_work_order", "order_id": 1740}]})
    assert not [p for p in out.proposals if p.action.get("type") == "cancel_work_order"], \
        [p.action for p in out.proposals]
    out, *_ = review({"note": "x", "actions": [{"type": "cancel_work_order", "order_id": 1801}]})
    got = [p.action for p in out.proposals if p.action.get("type") == "cancel_work_order"]
    assert got == [{"type": "cancel_work_order", "order_id": 1801, "by": "strategist"}], got


@test("B6: a strategist's work order goes to the bridge marked by=strategist (the bridge records it apart)")
def _():
    out, *_ = review({"note": "x", "actions": [{"type": "work_order", "recipe": "stone_blocks", "amount": 5}]})
    got = [p for p in out.proposals if p.action.get("type") == "work_order"]
    assert got and got[0].action.get("by") == "strategist" and got[0].rule == "strategist", \
        [(p.rule, p.action) for p in out.proposals]


def _lua_env():
    from lupa.lua53 import LuaRuntime
    src = bridge_part_src("ai-bridge-orders")   # (0.105.119) act_cancel_work_order in ai-bridge-orders-jobs
    bodies = []
    for name in ("ai_orders", "save_ai_orders", "record_ai_order", "get_orders", "act_cancel_work_order"):
        start = src.index(f"\nfunction {name}(")
        bodies.append(src[start:src.index("\nend\n", start) + 5])
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(r"""
local body = ...
local env = setmetatable({}, {__index = _G})
local store = {}
local function vec(items)
    local v = {_vec = true, n = #items}
    for i, x in ipairs(items) do v[i - 1] = x end
    v.erase = function(self, i)
        for k = i, self.n - 2 do self[k] = self[k + 1] end
        self[self.n - 1] = nil
        self.n = self.n - 1
    end
    return setmetatable(v, {__len = function(t) return t.n end})
end
env.vec = vec
env.newtable = function() return {} end
env.ipairs = function(t)
    if type(t) == 'table' and t._vec then
        local i = -1
        return function() i = i + 1; if i < t.n then return i, t[i] end end
    end
    return ipairs(t)
end
local function order(id)
    return {id = id, job_type = 1, reaction_name = '', amount_left = 1, amount_total = 1, frequency = 0,
            status = {}, item_conditions = vec({}), order_conditions = vec({}), mat_type = -1,
            finished_year = -1, workshop_id = -1, max_workshops = 0}
end
env.df = {global = {world = {manager_orders = {all = vec({order(1740), order(1801), order(900)})}},
                    plotinfo = {manager_timer = 0}},
          job_type = {[1] = 'ConstructBlocks'}, workquota_frequency_type = {[0] = 'OneTime'}}
env.dfhack = {persistent = {getSiteData = function(k, d) return store[k] or d end,
                            saveSiteData = function(k, v) store[k] = v end}}
env.AI_ORDERS_KEY = 'ai-overseer/orders'
env.reject = function(msg) return {ok = false, rejected = true, error = msg} end
env.whole_number = function(x) return math.tointeger(x) end
env.order_in_use_by_ui = function() return false end
env.free_order = function() end
env.orphan_jobs = function() return 0 end
env.order_jobs = function() return {} end
env.recipe_of = function(o) return 'r' .. o.id end
assert(load(body, 'orders', 't', env))()
return env
""", "\n".join(bodies))
    return env


def _tbl(env, **kw):
    t = env.newtable()
    for k, v in kw.items():
        t[k] = v
    return t


if have_lua():
    @test("B6 (lua): the bridge records the strategist's order apart; get_orders marks only it by_strategist")
    def _():
        env = _lua_env()
        data = env.ai_orders()
        env.record_ai_order(data, 1740, None)            # the planner's
        env.record_ai_order(data, 1801, "strategist")    # the strategist's
        env.save_ai_orders(data)
        rows = {r.id: r for r in env.get_orders().values()}
        assert rows[1740].by_ai and not rows[1740].by_strategist, dict(rows[1740])
        assert rows[1801].by_ai and rows[1801].by_strategist, dict(rows[1801])
        assert not rows[900].by_ai and not rows[900].by_strategist, dict(rows[900])

    @test("B6 (lua): the bridge refuses the strategist's cancel of the planner's order; the planner's own "
          "cancel and the strategist's of its own order go")
    def _():
        env = _lua_env()
        data = env.ai_orders()
        env.record_ai_order(data, 1740, None)
        env.record_ai_order(data, 1801, "strategist")
        env.save_ai_orders(data)
        lua_t = env.ai_orders
        r = env.act_cancel_work_order(_tbl(env, order_id=1740, by="strategist"))
        assert r.rejected and "planner" in r.error, dict(r)
        r = env.act_cancel_work_order(_tbl(env, order_id=1801, by="strategist"))
        assert r.ok and r.cancelled, dict(r)
        assert lua_t().by["1801"] is None and lua_t().ids["1801"] is None
        r = env.act_cancel_work_order(_tbl(env, order_id=1740))   # the planner's own cancel (no by)
        assert r.ok and r.cancelled, dict(r)
        r = env.act_cancel_work_order(_tbl(env, order_id=900))    # the player's: never
        assert r.rejected, dict(r)


# --- B7: the crisis and recovery holds ---------------------------------------------------------

def _tavern(by="strategist"):
    a = {"type": "start_project", "kind": "tavern", "tables": 8}
    if by:
        a["by"] = by
    return Proposal("build", a, "strategist: a tavern", 1, False)


def _order():
    return Proposal("strategist", {"type": "work_order", "recipe": "brew_drink", "amount": 5, "by": "strategist"},
                    "strategist: drink", 1, True)


def _crisis_memory():
    m = Memory()
    m.crisis = {"since": 1, "why": ["12 dead in 28 days"]}
    return m


@test("B7: a strategist's level is expansion (held in a crisis or recovery), whatever its kind")
def _():
    import hold_classes as hc
    assert hc.step_class(_tavern()) == hc.EXPANSION
    assert hc.step_class(_tavern(by=None)) == hc.SURVIVAL      # the planner's own tavern still goes
    assert hc.step_class(_order()) == hc.SURVIVAL


@test("B7: in a crisis the review's tavern level waits (said); its drink order and civ alert go")
def _():
    from review import hold_review_proposals
    alert = Proposal("strategist", {"type": "civ_alert", "on": True}, "strategist: danger", 1, False)
    notes = []
    kept = hold_review_proposals(fort(), _crisis_memory(), [_tavern(), _order(), alert], notes)
    assert [p.action["type"] for p in kept] == ["work_order", "civ_alert"], [p.action for p in kept]
    assert any("crisis" in n and "tavern" in n for n in notes), notes
    # no crisis, no recovery: everything goes
    notes = []
    kept = hold_review_proposals(fort(), Memory(), [_tavern(), _order()], notes)
    assert len(kept) == 2 and not notes, (kept, notes)


@test("B7: in collapse recovery the review's tavern level waits too")
def _():
    from review import hold_review_proposals
    m = Memory()
    m.recovery = {"since": 1, "why": "the fort fell from 60 to 20", "peak": 60}
    import planner_recovery
    assert planner_recovery.in_recovery(m), "the recovery memory's shape changed"
    notes = []
    kept = hold_review_proposals(fort(), m, [_tavern(), _order()], notes)
    assert [p.action["type"] for p in kept] == ["work_order"], [p.action for p in kept]
    assert any("recovery" in n for n in notes), notes


@test("B7: end to end: a review in a crisis proposes a tavern; the overseer's hold keeps it out")
def _():
    from review import hold_review_proposals
    m = _crisis_memory()
    out, _c, s, m = review({"note": "build a tavern", "actions": [
        {"type": "start_project", "kind": "tavern", "tables": 8},
        {"type": "work_order", "recipe": "brew_drink", "amount": 5}]}, memory=m)
    assert any(p.action.get("type") == "start_project" for p in out.proposals), (out.say, [p.action for p in out.proposals])
    kept = hold_review_proposals(s, m, out.proposals, [])
    assert [p.action["type"] for p in kept] == ["work_order"], [p.action for p in kept]


@test("B7: the overseer runs the review's proposals through the holds before putting them in front")
def _():
    src = py_family_src("overseer")
    i = src.index("def _review():")
    j = src.index('cycle_step(memory, state, "strategist", _review', i)
    assert "hold_review_proposals(state, memory, list(ai_props)" in src[i:j], "not called in _review"


@test("B7: the hold fails closed: a broken crisis check keeps only the non-expansion steps")
def _():
    import review as R
    import crisis
    real = crisis.apply
    try:
        def boom(*a, **k):
            raise RuntimeError("x")
        crisis.apply = boom
        notes = []
        kept = R.hold_review_proposals(fort(), _crisis_memory(), [_tavern(), _order()], notes)
        assert [p.action["type"] for p in kept] == ["work_order"] and notes, (kept, notes)
    finally:
        crisis.apply = real


finish()
