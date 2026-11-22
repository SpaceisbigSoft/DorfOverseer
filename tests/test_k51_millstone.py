"""(0.105.51) The Millstone deadlock and idle hands (R3 live run, all six forts).

Every fort held 2-5 of its 5 building slots with workshops levels waiting
>1000 days for a Millstone: the bridge lists the slurry shops as
["Millstone", "Quern"], the paper rule built the first, nothing ordered the
millstone, finish_project refused ("1 buildings still waiting") and the
paper rule started another level beside the stale one. Here: the quern
first; a level for one of the shops open holds the next; the planned
Quern's quern ordered at the mason's; a level waiting only for workshops
given up (finish_project give_up) by the building rule and the stuck sweep;
the idle-hands rule past the blocks' cap (rock crafts, then stock
furniture); a second Carpenters' urgent while drink lacks barrels.

    python tests/test_k51_millstone.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish  # noqa: E402
from lua_modules_util import bridge_part_src  # noqa: E402  (r6) the bridge parts split

import digest  # noqa: E402
import planner_paper as PP  # noqa: E402
import planner_stuck as PS  # noqa: E402
import planner_building as PB  # noqa: E402
import planner_industry as PI  # noqa: E402
from planner import Memory, plan, PLANNER_CONFIG as CFG  # noqa: E402

test = make_test()
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LUA = ROOT / "lua"

# F's open Millstone level, as its 256-spring state has it
F_MILL = {"id": 41, "kind": "workshops", "phase": "furnish", "elevation": 29, "z": 158, "next": False,
          "furnish": {"days": 998, "done": 1, "placed": 2, "waiting": {"Workshop": 1}},
          "furniture": {"Door": 1, "Millstone": 1}, "summary": {"workshops": ["Millstone"]},
          "started": {"day": 20, "month": "Obsidian", "season": "winter", "tick": 393065, "year": 252}}


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


def paper_fort(open_=None):
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["locations"]["list"] = [{"id": 7, "type": "LIBRARY", "have": {"paper": 0}, "want": {"paper": 10},
                               "jobs": {}, "zones": [70], "chests": 1, "flags": ["VISITORS_ALLOWED"]}]
    s["supplies"].update(sheets=0, blank_quires=0)
    s["buildings"]["workshops"] = {"Farmers": 1, "Craftsdwarfs": 1, "Carpenters": 1, "ScrewPress": 1,
                                   "Kitchen": 2, "Still": 2, "Masons": 1}
    s["paper"] = {"reactions": {
        "slurry": {"code": "MAKE_SLURRY_FROM_PLANT", "inputs": 226, "shops": ["Millstone", "Quern"]},
        "press": {"code": "PRESS_PLANT_PAPER", "inputs": 0, "shops": ["ScrewPress"]},
        "papyrus": {"code": "MAKE_SHEET_FROM_PLANT", "inputs": 0, "shops": ["Farmers"]}},
        "sheets": 0, "quires_blank": 0, "scrolls_blank": 0}
    s["orders"] = [o for o in s["orders"] if o.get("recipe") not in PP.PAPER_RECIPES + PP.KILN_PAPER]
    s["projects"]["open"] = list(open_ or [])
    return digest.normalize(s)


def run_paper(s):
    props, notes = [], []
    PP._paper_rule(s, CFG, props, notes)
    return props, notes


@test("paper: the bridge's [Millstone, Quern] builds a quern (a millstone needs power)")
def _():
    props, _ = run_paper(paper_fort())
    shops = [p.action.get("shops") for p in props if p.rule == "paper_shop"]
    assert shops == [["Quern"]], shops
    assert props[0].reason.endswith("build a quern"), props[0].reason


@test("paper: a mill level open, however stale, holds the next one (no second Millstone level)")
def _():
    props, notes = run_paper(paper_fort([copy.deepcopy(F_MILL)]))
    assert not by_rule(props, "paper_shop"), props
    assert any("project 41" in n and "is open" in n for n in notes), notes


def building_fort(open_):
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["projects"]["open"] = open_
    s["orders"] = [o for o in s["orders"] if o.get("recipe") not in ("stone_quern", "stone_millstone")]
    s["buildings"]["workshops"].setdefault("Masons", 1)
    return s


@test("building: a level waiting only for its workshops 168+ days is given up (F's 998-day Millstone)")
def _():
    props, _ = plan(building_fort([copy.deepcopy(F_MILL)]), Memory())
    g = [p for p in by_rule(props, "project") if p.action.get("give_up")]
    assert g and g[0].action == {"type": "finish_project", "project_id": 41, "give_up": True}, g
    assert "998 days" in g[0].reason and "1 Millstone" in g[0].reason, g[0].reason
    # no millstone ordered for a level about to be given up
    assert not [p for p in props if p.action.get("recipe") == "stone_millstone"], props


@test("building: a young level waiting for its Quern orders a quern at the mason's; not twice; not a bed level")
def _():
    young = dict(copy.deepcopy(F_MILL), id=80, furniture={"Quern": 1}, summary={"workshops": ["Quern"]})
    young["furnish"] = {"days": 10, "done": 1, "placed": 2, "waiting": {"Workshop": 1},
                        "waiting_shops": {"Quern": 1}}
    s = building_fort([young])
    props, _ = plan(s, Memory())
    q = [p for p in props if p.action.get("recipe") == "stone_quern"]
    assert q and q[0].action == {"type": "work_order", "recipe": "stone_quern", "amount": 1}, q
    assert not [p for p in by_rule(props, "project") if p.action.get("give_up")], props
    s["orders"] = s["orders"] + [{"id": 900, "recipe": "stone_quern", "amount_left": 1, "amount_total": 1,
                                  "by_ai": True}]
    assert not [p for p in plan(s, Memory())[0] if p.action.get("recipe") == "stone_quern"]


@test("waiting_shops: the bridge's kinds; an older bridge's 'Workshop' read from the level's planned shop")
def _():
    assert PB.waiting_shops({"furnish": {"waiting": {"Workshop": 2}, "waiting_shops": {"Quern": 2}}}) == {"Quern": 2}
    assert PB.waiting_shops(F_MILL) == {"Millstone": 1}
    assert PB.waiting_shops({"furnish": {"waiting": {"Workshop": 1}}, "furniture": {"Masons": 1}}) == {}


@test("stuck sweep: a furnishing level whose only waiting pieces are workshops is retired with give_up")
def _():
    r = {"kind": "project", "id": 41, "state": "furnish", "what": "workshops"}
    _, retire, _ = PS._remedies(r, copy.deepcopy(F_MILL), None, 300, CFG)
    assert retire == {"type": "finish_project", "project_id": 41, "stalled": True, "give_up": True}, retire
    beds = dict(copy.deepcopy(F_MILL), furnish={"days": 998, "done": 1, "placed": 3,
                                                "waiting": {"Workshop": 1, "Bed": 1}})
    _, retire, _ = PS._remedies(r, beds, None, 300, CFG)
    assert "give_up" not in retire, retire
    young = dict(copy.deepcopy(F_MILL), furnish=dict(F_MILL["furnish"], days=100))
    _, retire, _ = PS._remedies(r, young, None, 300, CFG)
    assert "give_up" not in retire, retire


@test("lua: quern and millstone recipes (DF's ConstructQuern / ConstructMillstone, rock); give_up wired")
def _():
    # (r5 p5) the loaded hub's recipes and its finish_project run on a stand-in ai-builder (tests/bridge_behaviour.py)
    import bridge_behaviour as BB
    env = BB.hub()
    for r, job in (("stone_quern", "ConstructQuern"), ("stone_millstone", "ConstructMillstone")):
        assert env.ORDER_RECIPES[r].job == job and env.ORDER_RECIPES[r].kind == "stone", r
    got, _, _ = BB.forwarded("finish_project", {"project_id": 9, "give_up": True}, "ai-builder", "finish_project")
    assert got[0][1][3] is True, got
    rep = bridge_part_src("ai-bridge-report")
    assert "each('DOOR'" in rep and "each('CABINET'" in rep and "each('CHAIR'" in rep


def idle_fort(goods, blocks=600, sup=None):
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["dwarves"].update(total=100, adults=98, idle_adults=53, idle_free=40)
    s["stocks"].update(blocks=blocks, boulders=1601)
    s["stone_use"] = {"usable": 450}
    s.setdefault("trade", {})["goods"] = goods
    s["supplies"].update(sup or {})
    s["orders"] = [o for o in s["orders"] if o.get("recipe") not in
                   ("stone_blocks", "stone_crafts", "metal_crafts", "wood_crafts", "bone_crafts",
                    "stone_door", "stone_cabinet", "stone_table", "stone_chair")]
    s["buildings"]["workshops"].update(Masons=1, Craftsdwarfs=1)
    return s


@test("idle hands: blocks at the cap -> rock crafts in a batch of 20 while goods are few (F: silent at 535)")
def _():
    props, _ = plan(idle_fort(goods=250), Memory())
    i = by_rule(props, "idle")
    assert i and i[0].action == {"type": "work_order", "recipe": "stone_crafts", "amount": CFG["idle_order_min"]}, i


@test("idle hands: blocks at the cap, goods plenty -> stone furniture for stock, the fewest kind, up to 20")
def _():
    sup = {"doors": 12, "cabinets": 3, "tables": 25, "chairs": 8}
    props, _ = plan(idle_fort(goods=500, sup=sup), Memory())
    i = by_rule(props, "idle")
    assert i and i[0].action == {"type": "work_order", "recipe": "stone_cabinet", "amount": 17}, i
    sup = {"doors": 20, "cabinets": 30, "tables": 25, "chairs": 20}
    props, notes = plan(idle_fort(goods=500, sup=sup), Memory())
    assert not by_rule(props, "idle") and any("idle hands stay idle" in n for n in notes), notes


@test("idle hands: blocks under the cap still go first")
def _():
    props, _ = plan(idle_fort(goods=250, blocks=10), Memory())
    i = by_rule(props, "idle")
    assert i and i[0].action["recipe"] == "stone_blocks", i


@test("bottleneck: a second Carpenters' is urgent while drink is short with no empty barrels (F)")
def _():
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["dwarves"].update(total=99, adults=98, idle_adults=55)
    s["stocks"]["drink"] = 648
    s["supplies"].update(empty_barrels=0, empty_pots=0)
    s["buildings"]["workshops"]["Carpenters"] = 1
    s["orders"] = [{"id": 1, "recipe": "wooden_barrel", "job": "MakeBarrel", "amount_left": 17, "amount_total": 17,
                    "by_ai": True}]
    s["projects"]["open"] = []
    s = digest.normalize(s)
    props = []
    PI._bottleneck_rule(s, CFG, 99, props, None)
    b = by_rule(props, "bottleneck")
    assert b and b[0].action.get("shops") == ["Carpenters"] and b[0].action.get("urgent") is True, b
    assert "no empty barrels" in b[0].reason and b[0].priority == 3, b[0].reason
    s["supplies"]["empty_barrels"] = 40                      # barrels to brew into: not urgent
    props = []
    PI._bottleneck_rule(s, CFG, 99, props, None)
    b = by_rule(props, "bottleneck")
    assert b and not b[0].action.get("urgent"), b


if __name__ == "__main__":
    finish()
