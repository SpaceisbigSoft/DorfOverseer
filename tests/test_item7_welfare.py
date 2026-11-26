"""(item7) Welfare: the hospitals' beds by the population; flour for good meals.

- hospital_beds (brain/planner_hospital_beds.py): the hospital zones filled
  to ceil(citizens / 20 x f) + ceil(2 x f) beds (f = 2^(Welfare/100)): a free
  bed into the zone with the most free floor (place_in_zone what=bed), else
  beds ordered at the carpenter's; a bed placed counts at once (beds_planned);
  a zone booked full is passed over.
- mill_flour (brain/planner_flour.py): while good meals are short, the cooks'
  plants worth 2-4 a unit are joined by flour milled at the quern (worth 20).
- the bridge: free beds, millable plants and flour in the supplies report, beds
  planned on a hospital zone's tiles, a bed in ZONE_FURNITURE (text checks).

    python tests/test_item7_welfare.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from planner import PLANNER_CONFIG, Memory, plan  # noqa: E402
import planner_flour  # noqa: E402
from planner_hospital_beds import hospital_bed_target, hospital_beds_have, hospital_beds_rule  # noqa: E402
from planner_core_base import COOLDOWN_KEYS  # noqa: E402
from hold_classes import _SURVIVAL_RULES  # noqa: E402
import crisis  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG
LUA = ROOT / "lua"


def zone(zid, beds, planned=None, size=9):
    z = {"id": zid, "beds": beds, "chests": 2, "tables": 1, "traction": 1, "traction_planned": 1,
         "type": "MeetingHall", "x1": 100, "x2": 100 + size - 1, "y1": 50, "y2": 50 + size - 1, "z": 160}
    if planned is not None:
        z["beds_planned"] = planned
    return z


def hosp_fort(cit=97, zones=None, free_beds=0, wood=300, carpenters=True):
    """E, 26 Nov 00:04: 97 dwarves, one hospital zone (441, 9x9) with 4 beds, no free bed."""
    s = {"dwarves": {"total": cit}, "locations": {"count": {"HOSPITAL": 1}},
         "health": {"hospital": [{"id": 3, "zones": zones if zones is not None else [zone(441, 4, 4)]}]},
         "supplies": {"beds": free_beds}, "stocks": {"wood": wood},
         "buildings": {"workshops": {"Carpenters": 2} if carpenters else {}}, "jobs": {}, "orders": []}
    return s


def run(s, traits=None, memory=None):
    props, notes = [], []
    hospital_beds_rule(s, traits or {}, CFG, props, notes, memory)
    return props, notes


@test("the target by population and Welfare: War -40 6, neutral 7, Garden +40 10, Monastery +80 13 at 100")
def _():
    assert hospital_bed_target(100, {"welfare": -40}, CFG) == 6
    assert hospital_bed_target(100, {}, CFG) == 7
    assert hospital_bed_target(97, {}, CFG) == 7           # E
    assert hospital_bed_target(100, {"welfare": 40}, CFG) == 10
    assert hospital_bed_target(100, {"welfare": 80}, CFG) == 13
    assert hospital_bed_target(55, {}, CFG) == 5            # D, the Hermit hold: its 5 are enough
    assert hospital_bed_target(5, {}, CFG) == 4             # never under 4
    assert hospital_bed_target(2000, {"welfare": 200}, CFG) == CFG["hospital_beds_max"]
    # per 100 dwarves the Monastery and the Garden fort come out on top (the scorecard's line)
    per = {k: hospital_bed_target(n, {"welfare": w}, CFG) / n
           for k, n, w in (("War", 100, -40), ("Mon", 100, 80), ("Mer", 110, 0), ("Her", 55, 0),
                           ("Deep", 97, 0), ("Gar", 100, 40))}
    assert sorted(per, key=per.get)[-2:] == ["Gar", "Mon"], per


@test("E: 4 beds for 97, no free bed: 3 beds ordered at the carpenter's")
def _():
    p, _n = run(hosp_fort())
    assert len(p) == 1 and p[0].rule == "hospital_beds", p
    assert p[0].action == {"type": "work_order", "recipe": "wooden_bed", "amount": 3}, p[0].action
    assert p[0].is_order


@test("a free bed: into the zone with the most free floor")
def _():
    s = hosp_fort(cit=150, zones=[zone(441, 4, 4, size=6), zone(822, 4, 4, size=9)], free_beds=2)
    p, _n = run(s)
    assert p and p[0].action == {"type": "place_in_zone", "zone_id": 822, "what": "bed"}, p


@test("a bed placed counts at once (beds_planned); enough beds: nothing")
def _():
    s = hosp_fort(zones=[zone(441, 4, 7)], free_beds=3)
    assert hospital_beds_have(s) == 7
    assert run(s)[0] == []
    assert run(hosp_fort(cit=40, zones=[zone(441, 4)], free_beds=3))[0] == []      # 40 dwarves: 4 wanted


@test("a zone booked full is passed over; none left: a note, no step")
def _():
    from planner_core_refusals import note_zone_full
    from planner_core import Proposal, abs_tick
    s = copy.deepcopy(BASE)
    s.update(hosp_fort(cit=150, zones=[zone(441, 4), zone(822, 4, size=6)], free_beds=2))
    m = Memory()
    now = abs_tick(s)
    note_zone_full(m, Proposal("hospital_beds", {"type": "place_in_zone", "zone_id": 441, "what": "bed"}, "", 4),
                   {"ok": False, "error": "no free floor in zone 441"}, now)
    p, _n = run(s, memory=m)
    assert p and p[0].action["zone_id"] == 822, p
    note_zone_full(m, Proposal("hospital_beds", {"type": "place_in_zone", "zone_id": 822, "what": "bed"}, "", 4),
                   {"ok": False, "error": "no free floor in zone 822"}, now)
    p, n = run(s, memory=m)
    assert p == [] and any("no free floor" in x for x in n), (p, n)


@test("no hospital, an older bridge (no supplies.beds), a bed order queued, no carpenter: nothing asked")
def _():
    s = hosp_fort()
    s["locations"]["count"] = {}
    assert run(s)[0] == []
    s = hosp_fort()
    s["supplies"].pop("beds")
    assert run(s)[0] == []
    s = hosp_fort()
    s["orders"] = [{"recipe": "wooden_bed", "amount_left": 3, "amount_total": 3}]
    assert run(s)[0] == []
    p, n = run(hosp_fort(carpenters=False))
    assert p == [] and any("Carpenter" in x for x in n), (p, n)


@test("the planner: a bed step for a fort short of hospital beds; the rule's words and classes")
def _():
    s = copy.deepcopy(BASE)
    s.setdefault("locations", {}).setdefault("count", {})["HOSPITAL"] = 1
    s.setdefault("health", {})["hospital"] = [{"id": 3, "zones": [zone(441, 4, 4)]}]
    s.setdefault("supplies", {})["beds"] = 1
    s["dwarves"]["total"] = 97
    props, _notes = plan(s, Memory())
    assert any(p.rule == "hospital_beds" and p.action.get("what") == "bed" for p in props), \
        [p.rule for p in props]
    assert "hospital_beds" in _SURVIVAL_RULES and "mill_flour" in _SURVIVAL_RULES
    assert {"hospital_beds", "mill_flour"} <= crisis.RECOVERY_RULES
    assert COOLDOWN_KEYS["mill_flour"] == "needs_meal_cooldown_ticks"


# --- flour ------------------------------------------------------------------------------------

def meal_fort(**sup):
    """E, 26 Nov 00:09: 97 dwarves, 60 good meals, a quern, 16 empty bags, 13 millet, 13 cave
    wheat, 2 sweet pods (28 edible) beside 5 dimple cups and 19 hide roots (24 dye)."""
    s = copy.deepcopy(BASE)
    s["dwarves"]["total"] = 97
    s["buildings"]["workshops"] = {"Kitchen": 2, "Quern": 1, "Still": 4}
    s["stocks"].update(prepared_meals=2945, drink=97 * 40)
    s.setdefault("needs", {}).setdefault("needs", {})["EatGoodMeal"] = {"distracted": 13, "badly": 2}
    su = s.setdefault("supplies", {})
    su.update(good_meals=60, flour=1, empty_bags=16, millable={"edible": 28, "other": 24})
    su.update(sup)
    return s


def flour(s, notes=None):
    props: list = []
    planner_flour.flour_rule(s, Memory(), CFG, props, notes)
    return props


@test("E: good meals short, a quern, 28 edible millables of 52: mill 10 plants to flour")
def _():
    p = flour(meal_fort())
    assert len(p) == 1 and p[0].rule == "mill_flour", p
    assert p[0].action == {"type": "work_order", "recipe": "mill_plants", "amount": 10}, p[0].action
    assert p[0].is_order


@test("flour: not while the dye plants outnumber the edible ones, nor without a quern or bags (a note why)")
def _():
    n: list = []
    assert flour(meal_fort(millable={"edible": 10, "other": 30}), n) == [] and any("dye" in x for x in n), n
    s = meal_fort()
    s["buildings"]["workshops"].pop("Quern")
    s["buildings"]["workshops"].pop("Millstone", None)
    n = []
    assert flour(s, n) == [] and any("quern" in x for x in n), n
    n = []
    assert flour(meal_fort(empty_bags=0), n) == [] and any("bag" in x for x in n), n
    n = []
    assert flour(meal_fort(millable={"edible": 2, "other": 0}), n) == [] and n


@test("flour: not while good meals are enough, flour is kept, drink is under target, or an older bridge")
def _():
    assert flour(meal_fort(good_meals=97 * 3)) == []
    assert flour(meal_fort(flour=60)) == []
    s = meal_fort()
    s["stocks"]["drink"] = 10
    n: list = []
    assert flour(s, n) == [] and any("drink" in x for x in n), n
    s = meal_fort()
    s["supplies"].pop("millable")
    assert flour(s) == []
    # a small store: no more than the flour kept (20 at least) minus what is there
    assert flour(meal_fort(flour=40))[0].action["amount"] == 8     # 48 kept for 97


@test("the bridge: free beds, flour and millable plants reported; beds planned on a hospital zone; a bed placeable")
def _():
    sup = (LUA / "ai-bridge-report-supplies.lua").read_text(encoding="utf-8")
    assert "out.beds = 0" in sup and "each('BED'" in sup
    assert "out.millable = {edible = 0, other = 0}" in sup and "material_defs.type.mill" in sup
    assert "out.flour = 0" in sup and "EDIBLE_COOKED" in sup
    fort_ = (LUA / "ai-bridge-report-fort.lua").read_text(encoding="utf-8")
    assert "ze.beds_planned = n" in fort_ and "buildings.other.BED" in fort_
    rooms = (LUA / "ai-builder-rooms.lua").read_text(encoding="utf-8")
    assert "bed = {key = 'b', what = 'a bed'}" in rooms
    orders = (LUA / "ai-bridge-orders.lua").read_text(encoding="utf-8")
    assert "mill_plants = {job = 'MillPlants'}" in orders and "wooden_bed = {job = 'ConstructBed'" in orders
    for f in LUA.glob("*.lua"):
        assert f.stat().st_size < 60 * 1024, f.name
    assert (ROOT / "brain" / "planner.py").stat().st_size < 92000


finish()
