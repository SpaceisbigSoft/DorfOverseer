"""(0.105.119 item33) Labour asks the game refuses, and a fort idle for want of a pick.

  * A, C, E, F (25 Nov, 15:00-18:30): `labor` refused "nobody outside the
    squads left for this job" 48/9/26/22 times: the skilled_off asks
    (PLANT, HERBALIST, FISH with min_skill 3) for dwarves held off the labour
    on purpose (the recreation burrow's members: bridge side), fishers put
    back right after the fishing detail was trimmed to 0, and one labour
    asked twice in a cycle.
  * D (Hermit hold, years 253-254, 41-51% of its civilians idle): 2 dwarves
    on the Miners detail, 0 picks (its three iron picks were weapon-trap
    blades), 1217 tiles designated: the picks rule waited for nobody to be
    mining, and the stone rule's picks order wanted 20 picks of 16 bars.

    python tests/test_item33_labor_idle.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import planner  # noqa: E402
from planner import PLANNER_CONFIG, Memory, plan  # noqa: E402
from planner_core import Proposal  # noqa: E402
from planner_labor import _labor_rules, _labor_waiting_rule, dedupe_labor, labor_of  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LUA = (ROOT / "lua" / "ai-labor.lua").read_text(encoding="utf-8")


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def labor_props(props):
    return [p for p in props if p.rule == "labor" and p.action.get("type") == "assign_labor"
            and p.action.get("count")]


@test("(item33) labor: skilled_off asks no fishers while the fishing rule wants none (no water to fish)")
def _():
    lb = {"skilled_off": [{"labor": "FISH", "skilled": 4, "detail": "Fisherdwarves"},
                          {"labor": "BREWER", "skilled": 1, "detail": "Brewers"}]}
    props = []
    _labor_waiting_rule(lb, 40, PLANNER_CONFIG, props, unwanted={"FISH"})
    jobs = [p.action["job"] for p in props]
    assert jobs == ["BREWER"], jobs
    props = []
    _labor_waiting_rule(lb, 40, PLANNER_CONFIG, props)
    assert [p.action["job"] for p in props] == ["FISH", "BREWER"], props


@test("(item33) labor: in the planner, skilled fishers aren't put back on a fort with no water to fish")
def _():
    s = fort()
    s.setdefault("labor", {})
    s["labor"]["fish_water"] = 0
    s["labor"]["skilled_off"] = [{"labor": "FISH", "skilled": 4, "detail": "Fisherdwarves"}]
    props = labor_props(plan(s, Memory())[0])
    assert not [p for p in props if labor_of(p.action) == "FISH"], [p.action for p in props]
    s["labor"]["fish_water"] = 5
    props = labor_props(plan(s, Memory())[0])
    assert [p for p in props if labor_of(p.action) == "FISH"], [p.action for p in props]


@test("(item33) labor: one assign_labor a labour a cycle (the most urgent kept; 'farming' and PLANT are one)")
def _():
    props = [Proposal("labor", {"type": "assign_labor", "job": "PLANT", "count": 2, "min_skill": 3}, "skilled", 5),
             Proposal("labor", {"type": "assign_labor", "job": "farming", "count": 1}, "plots", 3),
             Proposal("labor", {"type": "assign_labor", "job": "mining", "count": 0}, "order", 1),
             Proposal("labor", {"type": "assign_labor", "job": "BREWER", "count": 3}, "waiting", 4),
             Proposal("labor", {"type": "assign_labor", "job": "BREWER", "count": 1, "min_skill": 3}, "sk", 5),
             Proposal("other", {"type": "assign_labor", "job": "PLANT", "count": 1}, "x", 9)]
    dedupe_labor(props)
    got = [(p.rule, p.action["job"], p.action["count"]) for p in props]
    assert got == [("labor", "farming", 1), ("labor", "mining", 0), ("labor", "BREWER", 3), ("other", "PLANT", 1)], got


@test("(item33) labor: idle D: picks forged when no pick is left though dwarves hold the mining labour")
def _():
    s = fort()
    lb = s.setdefault("labor", {})
    lb.update({"dig": 1217, "miners": 2, "picks": 0, "soldier_picks": 0, "built_picks": 3, "need": 0})
    s.setdefault("military", {}).setdefault("gear", {})["bars"] = {"IRON": 16}
    s["buildings"].setdefault("workshops", {})["MetalsmithsForge"] = 1
    s["orders"] = []
    props, notes = [], []
    _labor_rules(s, 57, PLANNER_CONFIG, props, notes, Memory())
    picks = [p for p in props if p.rule == "picks"]
    assert len(picks) == 1 and picks[0].action["material"] == "INORGANIC:IRON", [p.action for p in props]
    assert "built into traps" in picks[0].reason, picks[0].reason
    # a pick left: no order from this rule
    lb["picks"] = 1
    props = []
    _labor_rules(s, 57, PLANNER_CONFIG, props, [], Memory())
    assert not [p for p in props if p.rule == "picks"], [p.action for p in props]


@test("(item33) labor: idle D: in the whole plan, one picks order (labour rule and stone rule not both)")
def _():
    s = fort()
    lb = s.setdefault("labor", {})
    lb.update({"dig": 1217, "miners": 2, "picks": 0, "soldier_picks": 0, "need": 0})
    s.setdefault("military", {}).setdefault("gear", {})["bars"] = {"IRON": 16}
    s["buildings"].setdefault("workshops", {})["MetalsmithsForge"] = 1
    s["orders"] = []
    s["stone_use"] = {"usable": 3, "economic": {}, "forbidden": 0, "in_job": 0}
    picks = [p for p in plan(s, Memory())[0] if p.rule == "picks"]
    assert len(picks) == 1, [(p.action, p.reason) for p in picks]


@test("(item33) project/idle: the stone rule's picks order forges what the bars allow (16 iron, 20 wanted)")
def _():
    from planner_industry_stone import _picks_order
    s = fort()
    s["labor"] = {"dig": 1217, "picks": 0, "soldier_picks": 0}
    s.setdefault("military", {}).setdefault("gear", {})["bars"] = {"IRON": 16}
    s["buildings"].setdefault("workshops", {})["MetalsmithsForge"] = 1
    s["orders"] = []
    props = []
    _picks_order(s, PLANNER_CONFIG, props)
    assert len(props) == 1 and props[0].action["amount"] == 8 and props[0].action["material"] == "INORGANIC:IRON", \
        [p.action for p in props]
    s["military"]["gear"]["bars"] = {"IRON": 1}
    props = []
    _picks_order(s, PLANNER_CONFIG, props)
    assert not props


@test("(item33) labor bridge: skilled_off and the candidates leave out the recreation burrow's members and "
      "dwarves already on the detail; picks in buildings counted")
def _():
    assert "function rec_member_ids()" in LUA and "memo.rec[u.id]" in LUA
    assert "not rec[u.id] and not is_member(d, u.id)" in LUA
    assert "row.built_tools" in LUA and "out.built_picks" in LUA


# --- (item33, coordinator's addition) the best cooks at the kitchen -----------------------------

def cook_fort(free, kitchen_min=9, best=9, able=(9, 5), staffed=()):
    s = fort()
    s["orders"] = []
    pop = s["dwarves"]["total"]
    s["needs"] = {"needs": {"EatGoodMeal": {"distracted": 30}}}
    s["stocks"]["prepared_meals"] = pop * 30
    s["buildings"].setdefault("workshops", {})["Kitchen"] = 1
    s["supplies"].update(meal_servings=pop * 30, good_meals=0,
                         cooks={"best": best, "skilled": 2, "kitchen_min": kitchen_min, "able_skills": list(able),
                                "free": free, "staffed": list(staffed)})
    return s


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


@test("(item33) cook labor: C: the skill-17 cook hauls, a 9 cooks: the best two get the labour, off hauling")
def _():
    free = [{"id": 7, "skill": 17, "cook": False, "hauls": True, "away_days": 3},
            {"id": 9, "skill": 9, "cook": True, "hauls": True, "away_days": 0},
            {"id": 3, "skill": 4, "cook": True, "hauls": True}]
    s = cook_fort(free)
    props = plan(s, Memory())[0]
    c = by_rule(props, "cook_staff")
    assert c and c[0].action == {"type": "relieve_haulers", "count": 2, "cooks": [7, 9]}, [p.action for p in c]
    # not both kept yet: 0.105.8's bar stays by the second cook (no raise past 9)
    g = by_rule(props, "good_cooks")
    assert not g or g[0].action["min_level"] <= 9, [p.action for p in g]


@test("(item33) cook labor: A: a skill-11 cook with the labour off is put to cooking (none hauling either)")
def _():
    free = [{"id": 11, "skill": 11, "cook": False, "hauls": False}, {"id": 12, "skill": 6, "cook": True, "hauls": False}]
    s = cook_fort(free, kitchen_min=0, best=6, able=(6, 2))
    c = by_rule(plan(s, Memory())[0], "cook_staff")
    assert c and c[0].action["cooks"] == [11, 12], [p.action for p in c]


@test("(item33) cook project: both best cooks kept (labour on, off hauling, not away): the bar by the best cook")
def _():
    free = [{"id": 7, "skill": 17, "cook": True, "hauls": False, "away_days": 0},
            {"id": 9, "skill": 9, "cook": True, "hauls": False, "away_days": 1}]
    s = cook_fort(free, kitchen_min=9, best=17, able=(17, 9), staffed=(7, 9))
    props = plan(s, Memory())[0]
    assert not by_rule(props, "cook_staff"), [p.action for p in props if p.rule == "cook_staff"]
    g = by_rule(props, "good_cooks")
    assert g and g[0].action == {"type": "kitchen_skill", "min_level": 15}, [p.action for p in g]
    # kitchens at 15+ and both still kept: no drop back to the second's 9
    s["supplies"]["cooks"]["kitchen_min"] = 15
    assert not by_rule(plan(s, Memory())[0], "good_cooks")
    # (0.105.123 item22) the best cook 5 days at other work, the store full: the bar
    # stays by the best cook alone (solo_cook_bar)
    s["supplies"]["cooks"]["free"][0]["away_days"] = 5
    assert not by_rule(plan(s, Memory())[0], "good_cooks")
    # the best cook long at other work: 0.105.8's guard: down to what two cooks clear
    s["supplies"]["cooks"]["free"][0]["away_days"] = 8
    g = by_rule(plan(s, Memory())[0], "good_cooks")
    assert g and g[0].action == {"type": "kitchen_skill", "min_level": 9}, [p.action for p in g]


@test("(item33) cook labor: good meals no longer wanted: the kept cooks haul again")
def _():
    free = [{"id": 7, "skill": 17, "cook": True, "hauls": False}, {"id": 9, "skill": 9, "cook": True, "hauls": False}]
    s = cook_fort(free, staffed=(7, 9))
    s["needs"] = {"needs": {}}
    c = by_rule(plan(s, Memory())[0], "cook_staff")
    assert c and c[0].action == {"type": "relieve_haulers", "count": 2, "cooks": [], "back": True}, [p.action for p in c]
    # an old bridge (no `free`): nothing new
    del s["supplies"]["cooks"]["free"]
    assert not by_rule(plan(s, Memory())[0], "cook_staff")


@test("(item33) cook bridge: report names the free cooks; relieve_haulers takes cooks; hauling counts them key")
def _():
    rep = (ROOT / "lua" / "ai-bridge-report-supplies.lua").read_text(encoding="utf-8")
    hl = (ROOT / "lua" / "ai-hauling.lua").read_text(encoding="utf-8")
    civ = (ROOT / "lua" / "ai-bridge-actions-civic.lua").read_text(encoding="utf-8")
    assert "function free_cooks()" in rep and "out.cooks.free, out.cooks.staffed = free_cooks()" in rep
    assert "function relieve_cooks(ids, back, dry_run, txt)" in hl and "key_reason(u, st)" in hl
    assert "relieve_cooks(ids, a.back == true" in civ


finish()
