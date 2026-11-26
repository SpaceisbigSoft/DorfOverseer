"""(r33c, Phase 12's exit: truly idle non-soldiers under 25%) Idle hands with
work waiting, and an honest idle count.

The overnight digest (26 Nov) read idle B 38%, E 32%, A 25%:
  * A: 16 plant-gathering jobs (the fruit zones) for the 3 gatherers the
    free-time rule kept; farming and gathering narrowed in A, B and E for
    months at 25-48% idle (widened only once under 5% badly wanted friends);
  * B: "48% of the dwarves are idle" (idle_adults over all adults) while
    12-33% were truly idle; its 10 rock crafts went to 9 workshops in a day;
  * E: 9 boulders of usable rock, its rock crafts stuck 10 days, 33% idle;
  * the labour report's "idle" holders counted prayer and the tavern (B: 17
    idle holders of every labour, 8 free), and the idle count took in the
    recreation burrow's members, the mad and the caged.

    python tests/test_r33c_idle.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from planner import PLANNER_CONFIG, Memory, plan  # noqa: E402
from planner_core import _idle_share  # noqa: E402
from planner_labor import (_free_time_rule, _labor_rules, _labor_waiting_rule, free_holders,  # noqa: E402
                           narrowed_waiting, fort_idle_share)
import outcomes  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LABOR_LUA = (ROOT / "lua" / "ai-labor.lua").read_text(encoding="utf-8")
REPORT_LUA = (ROOT / "lua" / "ai-bridge-report.lua").read_text(encoding="utf-8")
CFG = PLANNER_CONFIG


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


# --- the honest count -----------------------------------------------------------

@test("(r33c) idle share: of the work-capable when the bridge reports them, else the adults outside the squads")
def _():
    dw = {"adults": 87, "in_squads": 21, "idle_free": 8}
    assert outcomes.work_base(dw) == 66
    assert outcomes.idle_free_pct(dw) == round(800 / 66, 1)
    dw["work_capable"] = 60                     # 6 in the recreation burrow or mad
    assert outcomes.work_base(dw) == 60
    assert outcomes.idle_free_pct(dw) == round(800 / 60, 1)
    s = {"dwarves": dw}
    assert abs(_idle_share(s) - 8 / 60) < 1e-9
    dw["work_capable"] = 0                      # unread (an odd report): as before
    assert outcomes.work_base(dw) == 66
    s = {"dwarves": {"adults": 87, "in_squads": 21, "idle_adults": 30}}
    assert abs(_idle_share(s) - 30 / 87) < 1e-9  # an older bridge: the old measure, untouched


@test("(r33c) scorecard health: the truly idle of the work-capable")
def _():
    import scorecard
    s = {"dwarves": {"adults": 87, "in_squads": 21, "idle_free": 6, "work_capable": 60, "total": 98,
                     "stress": {}}}
    h = scorecard.health(s, {})
    assert h["idle_pct"] == scorecard.pct(6, 60), h["idle_pct"]
    s["dwarves"].pop("work_capable")
    assert scorecard.health(s, {})["idle_pct"] == scorecard.pct(6, 66)


@test("(r33c) bridge: the idle with an excuse counted apart; work_capable reported; waiting rows carry `free`")
def _():
    assert re.search(r"function idle_excuse\(u, rec\)", LABOR_LUA)
    for k in ("'recreation'", "'unfit'", "'on_break'", "Melancholy", "Traumatized", "caged", "chained",
              "OnBreak", "isCrazed"):
        assert k in LABOR_LUA, k
    assert "function is_free(u, rec)" in LABOR_LUA
    ww = LABOR_LUA[LABOR_LUA.index("function waiting_work"):LABOR_LUA.index("function skilled_off")]
    assert "free = free[l] or 0" in ww and "is_free(u, rec)" in ww and "rec_member_ids()" in ww
    gd = REPORT_LUA[REPORT_LUA.index("function get_dwarves"):REPORT_LUA.index("function get_needs")]
    assert "idle_excused = {recreation = 0, unfit = 0, on_break = 0}, work_capable = 0" in gd
    assert "LAB.idle_excuse" in gd and "summary.idle_excused[excuse]" in gd
    assert "summary.work_capable = summary.work_capable + 1" in gd
    # the excused never in idle_free; the activity check comes first
    i_act, i_exc, i_free = (gd.index("summary.in_activity = summary.in_activity + 1"),
                            gd.index("summary.idle_excused[excuse]"), gd.index("summary.idle_free = summary.idle_free + 1"))
    assert i_act < i_exc < i_free


# --- the labour rules -----------------------------------------------------------

@test("(r33c) waiting work: holders 'idle' only at prayer or the tavern don't stop more being put on it")
def _():
    row = {"labor": "BREWER", "jobs": 6, "holders": 5, "idle": 3, "free": 0}
    assert free_holders(row) == 0
    props = []
    _labor_waiting_rule({"waiting": [row]}, 60, CFG, props)
    assert [p.action for p in props] == [{"type": "assign_labor", "job": "BREWER", "count": 2}], props
    row.pop("free")                                 # an older bridge: idle as before
    assert free_holders(row) == 3
    props = []
    _labor_waiting_rule({"waiting": [row]}, 60, CFG, props)
    assert not props, props


A_LABOR = {"waiting": [{"labor": "HERBALIST", "jobs": 16, "holders": 3, "idle": 1, "free": 1,
                        "detail": "Plant gatherers", "mode": "OnlySelectedDoesThis"}],
           "narrowed": {"farming": True, "gathering": True},
           "jobs": {"gathering": {"mode": "OnlySelectedDoesThis", "doing": 3, "candidates": 38},
                    "farming": {"mode": "OnlySelectedDoesThis", "doing": 15, "candidates": 26}}}


@test("(r33c) narrowed_waiting: A's 16 gathering jobs for 3 gatherers; not a few jobs, not with holders free")
def _():
    assert narrowed_waiting(A_LABOR, "gathering", CFG)
    assert narrowed_waiting(A_LABOR, "farming", CFG) is None
    lb = copy.deepcopy(A_LABOR)
    lb["waiting"][0].update(jobs=4)                 # 4 jobs for 3 holders: under 2 a holder
    assert narrowed_waiting(lb, "gathering", CFG) is None
    lb["waiting"][0].update(jobs=16, free=4)        # 4 free for 16 jobs: they'll take them
    assert narrowed_waiting(lb, "gathering", CFG) is None


def a_fort(idle_free: int) -> dict:
    s = fort()
    s["dwarves"].update(adults=48, in_squads=7, idle_free=idle_free, idle_adults=idle_free + 3, total=55)
    s["needs"] = {"needs": {"BeWithFriends": {"badly": 20}}, "social": {"idle": idle_free, "citizens": 55}}
    s["labor"] = dict(s.get("labor") or {}, **copy.deepcopy(A_LABOR))
    return s


@test("(r33c) A: gathering jobs wait for the narrowed crew, the fort busy: a few more gatherers, no widening")
def _():
    s = a_fort(3)                                   # 3 of 41: 7% idle
    props, notes = [], []
    _labor_rules(s, 55, CFG, props, notes)
    g = [p for p in props if p.rule == "labor" and p.action.get("job") == "gathering"]
    assert g and g[0].action == {"type": "assign_labor", "job": "gathering", "count": 3}, [p.action for p in props]
    assert "16 gathering job(s) wait" in g[0].reason, g[0].reason
    props = []
    _free_time_rule(s, 55, CFG, props, [])
    assert not [p for p in props if p.action.get("widen")], props
    # the crew never past a quarter of the fort (the detail stays narrowed)
    s["labor"]["jobs"]["gathering"]["doing"] = 12
    props = []
    _labor_rules(s, 55, CFG, props, [])
    g = [p for p in props if p.rule == "labor" and p.action.get("job") == "gathering"]
    assert g and g[0].action["count"] == 1, [p.action for p in props]      # 13 = 55 // 4
    s["labor"]["jobs"]["gathering"]["doing"] = 13
    props = []
    _labor_rules(s, 55, CFG, props, [])
    assert not [p for p in props if p.action.get("job") == "gathering"], [p.action for p in props]


@test("(r33c) the fort idle: a narrowed detail back to everybody (the waiting one first); not narrowed again while idle")
def _():
    s = a_fort(12)                                  # 12 of 41: 29% idle
    assert fort_idle_share(s, 55) >= CFG["free_time_widen_idle"]
    props = []
    _free_time_rule(s, 55, CFG, props, [])
    assert [p.action for p in props] == [{"type": "narrow_detail", "job": "gathering", "widen": True}], props
    assert "idle" in props[0].reason and "16 gathering job(s) wait" in props[0].reason
    props, notes = [], []
    _labor_rules(s, 55, CFG, props, notes)          # the widening does it: no crew asks beside it
    assert not [p for p in props if p.action.get("job") == "gathering"], [p.action for p in props]
    s["labor"]["waiting"] = []                      # nothing waits: farming first by name
    props = []
    _free_time_rule(s, 55, CFG, props, [])
    assert [p.action for p in props] == [{"type": "narrow_detail", "job": "farming", "widen": True}], props
    # under the widening line, over the narrowing one: left as it is (the gap keeps them apart)
    s = a_fort(6)                                   # 6 of 41: 15%
    s["labor"]["waiting"] = []
    props = []
    _free_time_rule(s, 55, CFG, props, [])
    assert not props, props


@test("(r33c) free time: a detail whose jobs wait isn't narrowed")
def _():
    s = a_fort(2)
    s["needs"]["needs"]["BeWithFriends"]["badly"] = 30
    s["labor"]["narrowed"] = {}
    s["labor"]["jobs"]["gathering"]["mode"] = "EverybodyDoesThis"
    s["labor"]["jobs"]["farming"]["mode"] = "EverybodyDoesThis"
    s["farms"] = dict(s.get("farms") or {}, built=6)
    props = []
    _free_time_rule(s, 55, CFG, props, [])
    assert [p.action.get("job") for p in props] == ["farming"], props
    s["labor"]["jobs"]["farming"]["mode"] = "OnlySelectedDoesThis"
    s["labor"]["narrowed"] = {"farming": True}
    props = []
    _free_time_rule(s, 55, CFG, props, [])
    assert not props, props                         # gathering's 16 jobs wait: kept for everybody


# --- standing work: crafts for trade --------------------------------------------

def trade_fort(idle_free=None) -> dict:
    s = fort()
    s["orders"] = []
    s["trade"] = {"goods": 3, "depot": True, "caravans": []}
    s["dwarves"].update(idle_adults=100, adults=167)
    if idle_free is not None:
        s["dwarves"].update(idle_free=idle_free, work_capable=134)
    return s


@test("(r33c) crafts: an older report (no idle_free) as before: 10 rock crafts on idle_adults")
def _():
    c = by_rule(plan(trade_fort(), Memory())[0], "crafts")
    assert c and c[0].action == {"type": "work_order", "recipe": "stone_crafts", "amount": 10}, c
    assert "60% of the dwarves are idle" in c[0].reason, c[0].reason


@test("(r33c) crafts: the truly idle share said, and the order sized to the free hands (two jobs each, to 50)")
def _():
    c = by_rule(plan(trade_fort(20), Memory())[0], "crafts")
    assert c and c[0].action == {"type": "work_order", "recipe": "stone_crafts", "amount": 40}, c
    assert "15% of the dwarves are idle (20 free)" in c[0].reason, c[0].reason
    c = by_rule(plan(trade_fort(40), Memory())[0], "crafts")
    assert c and c[0].action["amount"] == CFG["idle_order_max"], c
    # few truly idle (under the stricter line): none, though idle_adults is high
    assert not by_rule(plan(trade_fort(5), Memory())[0], "crafts")
    # one craft order of any kind at a time
    s = trade_fort(20)
    s["orders"] = [{"id": 5, "recipe": "bone_crafts", "amount_left": 10, "by_ai": True}]
    assert not by_rule(plan(s, Memory())[0], "crafts")


@test("(r33c) crafts: little rock -> bone, else wood to spare, else a note (E: 9 boulders, stone crafts stuck)")
def _():
    s = trade_fort(20)
    s["stone_use"] = {"usable": 4, "economic": {}}
    s["stocks"]["boulders"] = 4
    s.setdefault("needs", {})["bones"] = 60
    p, notes = plan(s, Memory())
    c = by_rule(p, "crafts")
    assert c and c[0].action == {"type": "work_order", "recipe": "bone_crafts", "amount": 40}, (c, notes)
    s["needs"]["bones"] = 5
    s["stocks"]["wood"] = 194 * CFG["wood_per_dwarf"] + 100
    c = by_rule(plan(s, Memory())[0], "crafts")
    assert c and c[0].action["recipe"] == "wood_crafts", c
    s["stocks"]["wood"] = 0
    p, notes = plan(s, Memory())
    assert not by_rule(p, "crafts")
    assert any("few bones and no wood to spare" in n for n in notes), notes


if __name__ == "__main__":
    finish()
