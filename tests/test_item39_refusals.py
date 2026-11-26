"""(0.105.119 item39) Refusals that repeated in the 25 Nov fresh run (15:00-18:30):
each rule now skips when its own state shows nothing to do, or waits for the
dig/build it is waiting on.

    python tests/test_item39_refusals.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

from planner import Memory, plan  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LUA = ROOT / "lua"


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def by_rule(props, rule):
    return [x for x in props if x.rule == rule]


def lua(name: str) -> str:
    return (LUA / name).read_text(encoding="utf-8").replace("\r\n", "\n")


# --- eggs ------------------------------------------------------------------------------

def _hens(s, **herd):
    s["dwarves"]["total"] = 88
    s["buildings"]["workshops"]["Masons"] = 1
    s.setdefault("supplies", {}).update(egg_layers=7, egg_layers_penned=5, nest_boxes=5, nest_box_items=3)
    s.setdefault("herd", {}).update(herd)
    return s


@test("item39 eggs: the hens in no pasture are pets and the pen's hens each have a box: no nest_boxes")
def _():
    s = _hens(fort(), egg_layers_loose=0, hens_without_box=0)
    assert not by_rule(plan(s, Memory())[0], "eggs")


@test("item39 eggs: a loose hen that is no pet, or a pen short of boxes with boxes free: nest_boxes")
def _():
    s = _hens(fort(), egg_layers_loose=1, hens_without_box=0)
    assert by_rule(plan(s, Memory())[0], "eggs")
    s = _hens(fort(), egg_layers_loose=0, hens_without_box=2)
    assert by_rule(plan(s, Memory())[0], "eggs")
    s["supplies"]["nest_box_items"] = 0
    assert not by_rule(plan(s, Memory())[0], "eggs")      # nothing free to place: the order rule's turn


@test("item39 eggs: without the herd's new counts the old rule stands")
def _():
    s = _hens(fort())
    assert by_rule(plan(s, Memory())[0], "eggs")


@test("item39 eggs: the herd report counts the loose non-pet hens and the hens short of a box")
def _():
    t = lua("ai-herd.lua")
    assert "out.egg_layers_loose, out.hens_without_box = hens_loose, 0" in t
    assert "flag(c, 'LAYS_EGGS') and adult and female and not pet then" in t


# --- staff -----------------------------------------------------------------------------

@test("item39 staff: a post's labours go through the game's work detail (a bare flag is undone)")
def _():
    t = lua("ai-society-posts.lua")
    body = t[t.index("function give_post_labors"):t.index("function staff_labors")]
    assert "reqscript('ai-labor').give_labor(u, l)" in body, body


# --- homes_liked -----------------------------------------------------------------------

HOMES = {"citizens": 142, "adults": 125, "children": 17, "adults_roomless": 0, "children_roomless": 0,
         "couples": 20, "couples_shared": 20, "couples_apart": 0, "couples_none": 0, "couples_unlinked": 0,
         "hoarders": 0, "rough": 0, "rough_housed": 0, "rough_children": 0, "rough_unreachable": 0,
         "lack_room": 0, "free_bedrooms": 190, "free_suites": 2, "free_bedless": 0, "rooms_wanted": 0, "samples": []}


def _homes(**kw):
    s = fort()
    s["homes"] = {**copy.deepcopy(HOMES), **kw}
    s["dwarves"]["stress"].update(miserable=3, very_unhappy=4, unhappy=10)
    return s


@test("item39 homes_liked: the census's dry run finds no free room much better: not asked")
def _():
    assert not by_rule(plan(_homes(upgrades_placed=0, upgrades_plain=0), Memory())[0], "homes_liked")


@test("item39 homes_liked: a better room for one of them, or an older bridge: asked")
def _():
    assert by_rule(plan(_homes(upgrades_placed=2, upgrades_plain=2), Memory())[0], "homes_liked")
    assert by_rule(plan(_homes(), Memory())[0], "homes_liked")


@test("item39 homes_liked: the census runs the move's own dry run, both ways of scoring")
def _():
    t = lua("ai-homes.lua")
    assert "house(0, 3, true, txt, units, true)" in t and "house(0, 3, true, txt, units, false)" in t


# --- pair_chairs -----------------------------------------------------------------------

def _tavern(**e):
    s = fort()
    s["dwarves"]["total"] = 95
    s["locations"] = {"list": [{"id": 5, "type": "INN_TAVERN", "zones": [1081, 1090], "chests": 2,
                                "have": {"goblets": 10, "instruments": 5}, "want": {"goblets": 10, "instruments": 5},
                                **e}]}
    s.setdefault("needs", {}).setdefault("needs", {})["BeWithFriends"] = {"badly": 42, "distracted": 57}
    return s


@test("item39 pair_chairs: only the tavern zones with a chair are asked; none with chairs: not asked")
def _():
    c = by_rule(plan(_tavern(zone_chairs={"1090": 3}), Memory())[0], "pair_chairs")
    assert c and c[0].action["zones"] == [1090], c
    assert not by_rule(plan(_tavern(zone_chairs={}), Memory())[0], "pair_chairs")
    assert not by_rule(plan(_tavern(zone_chairs=[]), Memory())[0], "pair_chairs")      # (an empty table as a list)


@test("item39 pair_chairs: an older bridge without zone_chairs: every zone as before")
def _():
    c = by_rule(plan(_tavern(), Memory())[0], "pair_chairs")
    assert c and c[0].action["zones"] == [1081, 1090], c


@test("item39 pair_chairs: the locations report counts each zone's chairs, under the 60,000-byte limit")
def _():
    t = lua("ai-bridge-report-civic.lua")   # (0.105.119) get_locations split off ai-bridge-report
    assert "e.zone_chairs = ch" in t and "elseif t == 'Chair' then ch[tostring(bid)]" in t
    assert len(t.encode("utf-8")) < 60000 and len(lua("ai-bridge-report.lua").encode("utf-8")) < 60000


# --- open_trade ------------------------------------------------------------------------

def _caravan(**trader):
    s = fort()
    s["trade"] = {"depot": True, "caravans": [{"civ": "the Mountainhomes", "state": "AtDepot"}], "goods": 0,
                  "at_depot": 0, "trader": {"requested": True, "at_depot": True, "can_open": True, **trader}}
    return s


@test("item39 open_trade: the merchants still unloading (the report's watch): not opened")
def _():
    assert not by_rule(plan(_caravan(unloading=True), Memory())[0], "open_trade")


@test("item39 open_trade: unloaded, or an older bridge: opened")
def _():
    assert by_rule(plan(_caravan(), Memory())[0], "open_trade")
    assert by_rule(plan(_caravan(unloading=False), Memory())[0], "open_trade")


@test("item39 open_trade: the trade report reads the unloading watch, under the 60,000-byte limit")
def _():
    t = lua("ai-trade.lua")
    assert "out.trader.unloading = unloading(dep) or nil" in t and len(t.encode("utf-8")) < 60000


# --- polish ----------------------------------------------------------------------------

def _idle(polish=None):
    s = fort()
    s["dwarves"].update(idle_adults=60, adults=150)
    if polish is not None:
        s["projects"]["polish"] = polish
    return s


@test("item39 polish: a level still being smoothed, or every finished level polished: not asked")
def _():
    assert not by_rule(plan(_idle("wait"), Memory())[0], "polish")
    assert not by_rule(plan(_idle("none"), Memory())[0], "polish")


@test("item39 polish: a level to smooth or engrave, or an older bridge: asked")
def _():
    for v in ("smooth", "engrave", None):
        assert by_rule(plan(_idle(v), Memory())[0], "polish"), v


@test("item39 polish: the projects report gives polish_pick's answer")
def _():
    t = lua("ai-builder-projects-progress.lua")
    assert "pcall(polish_pick, data.list, now_tick())" in t and "(what and 'wait' or 'none')" in t


# --- well_shaft ------------------------------------------------------------------------

def _shaft(**lid):
    s = fort()
    s["others_on_map"]["threats"] = []
    s["projects"]["well_lids"] = [{"project_id": 76, "x": 115, "y": 44, "z": 154, "elevation": 26,
                                   "state": "none", "gate": "none", **lid}]
    s["stocks"]["mechanisms"] = 5
    s.setdefault("entrances", {})["parts"] = {"hatch_covers": 0}
    return s


@test("item39 well_shaft: no free floor for the lever (the report says so): not asked, said")
def _():
    p, notes = plan(_shaft(gate_no_lever_spot=True), Memory())
    assert not [x for x in by_rule(p, "well_shaft") if x.action.get("type") == "well_shaft"], p
    assert any("no free floor near the well for its lever" in n for n in notes), notes


@test("item39 well_shaft: a lever spot (or an older bridge): the gate begun as before")
def _():
    a = [x.action for x in by_rule(plan(_shaft(), Memory())[0], "well_shaft")]
    assert a == [{"type": "well_shaft", "close": False}], a


@test("item39 well_shaft: the shaft report tests the lever's spot as the action does")
def _():
    assert "function shaft_lever_spot_for(p)" in lua("ai-builder-wells-shaft.lua")
    assert "pcall(shaft_lever_spot_for, p)" in lua("ai-builder-wells-watch.lua")


# --- herd_breeders ---------------------------------------------------------------------

import digest  # noqa: E402
import planner_husbandry as PH  # noqa: E402
import planner_provisions as PP  # noqa: E402
from planner import PLANNER_CONFIG as CFG  # noqa: E402

GARDEN = {"agriculture": 120, "husbandry": 80, "surface": 80, "welfare": 40, "grandeur": 40, "militarism": -30}


def _herd_rules(kinds):
    s = fort()
    s["herd"] = {"tame": 30, "kinds": kinds, "breeders": 0, "grazing_need": 0, "tameable": 0, "trainers": 1,
                 "war": 0, "pets": 2, "breeding_pairs": 1}
    s.setdefault("society", {}).update({"ai_pastures": 1, "ai_pasture_tiles": 60})
    s = digest.normalize(s)
    props, notes = [], []
    PH._husbandry_rules(s, Memory(), GARDEN, CFG, 60, props, notes)
    return [p for p in props if p.rule == "herd_breeders"]


@test("item39 herd_breeders: the adults are pets or named (none keep_breeders may keep): not asked")
def _():
    k = {"name": "COW", "n": 4, "f": 2, "m": 1, "free_f": 2, "free_m": 0, "grazer": True,
         "breeders_f": 0, "breeders_m": 0}
    assert not _herd_rules([k])


@test("item39 herd_breeders: a free pair, or an older bridge's f and m alone: asked")
def _():
    k = {"name": "COW", "n": 4, "f": 2, "m": 1, "free_f": 1, "free_m": 1, "grazer": True,
         "breeders_f": 0, "breeders_m": 0}
    assert _herd_rules([k])
    k = {"name": "COW", "n": 4, "f": 2, "m": 1, "grazer": True, "breeders_f": 0, "breeders_m": 0}
    assert _herd_rules([k])


@test("item39 herd_breeders: the herd report counts the adults keep_breeders may keep")
def _():
    t = lua("ai-herd.lua")
    assert "free_f = 0, free_m = 0" in t and "k.free_f = k.free_f + 1" in t


# --- cavern_farm -----------------------------------------------------------------------

def _cavern(**cavern):
    s = fort()
    s["provisions"] = {"hunting": {"game": 0, "danger": 0, "hunters": 0, "ai_hunters": 0},
                       "butchery": {"standing": {}, "corpses": 0, "hides": 0, "ai_set": {}},
                       "meals": {"by_kind": {}, "servings": 0}, "fruit": {"zones": 0, "ai_zones": 0, "trees": 0},
                       "cavern": {"plots": 0, "tiles": 0, **cavern}}
    s["dwarves"]["total"] = 30
    s = digest.normalize(s)
    s["others_on_map"]["threats"] = []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s["deep"] = {"caverns": [{"name": "Cavern1", "discovered": True, "open": True, "z_top": 80, "z_bottom": 70,
                              "junctions": [{"x": 20, "y": 20, "z": 81, "cave": {"x": 20, "y": 21, "z": 80}}]}],
                 "dangers": [], "cursed": []}
    s["farms"]["crops"] = {"MUSHROOM_HELMET_PLUMP": {"seeds": 40, "underground": True, "seasons": [0, 1, 2, 3]}}
    s["farms"]["plot_list"] = [{"tiles": 20, "underground": False}]
    m = Memory()
    m.farm_failure = "no soil or muddy floor"
    props, notes = [], []
    PP._provisions_rules(s, CFG, 30, props, notes, m)
    return [p for p in props if p.rule == "cavern_farm"]


@test("item39 cavern_farm: the spot the bridge refused still fails the report's test: not asked")
def _():
    assert not _cavern(refused_at={"x": 20, "y": 21, "z": 80, "why": "unreached"})


@test("item39 cavern_farm: another spot refused, or none: asked")
def _():
    assert _cavern(refused_at={"x": 50, "y": 21, "z": 80, "why": "unreached"})
    assert _cavern()


@test("item39 cavern_farm: the refusal is kept and re-tested by the provisions report")
def _():
    t = lua("ai-provisions.lua")
    assert "CAVERN_REFUSED = {x = ax, y = ay, z = az, why = why}" in t
    assert "out.refused_at = {x = r.x, y = r.y, z = r.z" in t
    assert t.index("function cavern_dangers(B)") > 0 and "local function cavern_dangers" not in t


# --- waterworks_irrigation -------------------------------------------------------------

import planner_water  # noqa: E402

YEAR = 403200


def _water(works_, refused):
    refused = {"moat": {"tick": YEAR, "why": "retired: leaked", "retired": 2}, **refused}   # (the moat first else)
    works_ = {"moat": {"kind": "moat", "stage": "retired", "why": "leaked"}, **works_}
    return {"settings": {"traits": {"fortification": 100, "engineering": 0}}, "dwarves": {"total": 60},
            "date": {"year": 10, "tick": 100000}, "others_on_map": {}, "hazards": {"wet": []},
            "water": {"bodies": [{"kind": "river", "tiles": 30, "nearest": {"x": 1, "y": 1, "z": 1}}]},
            "entrances": {"entrances": [{"kind": "surface", "id": 1}]},
            "buildings": {"workshops": {}, "furnaces": {}, "other": {}},
            "waterworks": {"works": works_, "refused": refused}}


def _water_run(s):
    props, notes = [], []
    m = Memory()
    m.farm_failure = "no soil within reach"
    planner_water._waterworks_rule(s, m, CFG, props, notes)
    return props, notes


@test("item39 waterworks_irrigation: tiles left to dig, or a piece still being built: the step not asked")
def _():
    for row in ({"stage": "digging", "dig_left": 12}, {"stage": "building", "build_left": 1}):
        props, _n = _water_run(_water({"irrigation": {"kind": "irrigation", **row}}, {}))
        assert not props, [(p.rule, p.action) for p in props]


@test("item39 waterworks_irrigation: dug, built, or an older bridge: the next step asked")
def _():
    for row in ({"stage": "digging", "dig_left": 0}, {"stage": "building", "build_left": 0},
                {"stage": "digging"}, {"stage": "building"}):
        props, _n = _water_run(_water({"irrigation": {"kind": "irrigation", **row}}, {}))
        assert [p.rule for p in props] == ["waterworks_irrigation"], (row, [(p.rule, p.action) for p in props])


@test("item39 waterworks_irrigation: the same refusal again waits twice as long each time (at most a year)")
def _():
    why = "no still, fresh water beside solid rock under a fort level within reach"
    now = 10 * YEAR + 100000
    ago = 40 * 1200                           # past the 28 days, short of 56
    s = _water({}, {"irrigation": {"tick": now - ago, "why": why}})
    assert [p.rule for p in _water_run(s)[0]] == ["waterworks_irrigation"]
    s = _water({}, {"irrigation": {"tick": now - ago, "why": why, "times": 2}})
    assert not _water_run(s)[0]
    s = _water({}, {"irrigation": {"tick": now - 340 * 1200, "why": why, "times": 9}})
    assert [p.rule for p in _water_run(s)[0]] == ["waterworks_irrigation"]          # a year at most
    s = _water({}, {"irrigation": {"tick": now - ago, "why": why, "times": 3, "later": True}})
    assert [p.rule for p in _water_run(s)[0]] == ["waterworks_irrigation"]          # a search cut short: soon


@test("item39 waterworks_irrigation: the bridge counts the same answer and reports what a step waits on")
def _():
    t = lua("ai-waterworks-steps.lua")
    assert "times = times}" in t and "row.dig_left = n" in t and "row.build_left = n" in t


# --- the building cap ("already # unfinished building projects") -------------------------

from planner_core import Proposal  # noqa: E402
from planner_slots import cap_full_pass  # noqa: E402


def _capped(n_open, cap, *props):
    s = {"projects": {"open": [{"id": i, "kind": "storage", "phase": "dig"} for i in range(n_open)],
                      "max_open": cap, "need_slots_free": 1}, "_errors": {}}
    ps, notes = list(props), []
    cap_full_pass(s, ps, notes)
    return [p.rule for p in ps], notes


def _start(rule, kind, **kw):
    return Proposal(rule, {"type": "start_project", "kind": kind, **kw}, "x", 5)


@test("item39 cap: the slots full: reserve_storage, bottleneck, homes_dig, cups_home, food_store, cloth not asked")
def _():
    rules_, notes = _capped(3, 3, _start("reserve_storage", "storage"), _start("bottleneck", "workshops"),
                            _start("homes_dig", "bedrooms"), _start("cups_home", "workshops"),
                            _start("food_store", "storage"), _start("cloth", "workshops"),
                            Proposal("eggs", {"type": "nest_boxes"}, "x", 5))
    assert rules_ == ["eggs"], rules_
    assert notes and "fill the 3 slots" in notes[0], notes


@test("item39 cap: a slot free, an urgent level (2 past), a farm level (1 past), a small need with room: asked")
def _():
    assert _capped(2, 3, _start("reserve_storage", "storage"))[0] == ["reserve_storage"]
    assert _capped(4, 3, _start("build", "hospital", urgent=True))[0] == ["build"]
    assert _capped(5, 3, _start("build", "hospital", urgent=True))[0] == []
    assert _capped(3, 3, _start("farms", "farms"))[0] == ["farms"]
    assert _capped(3, 3, _start("paper_shop", "workshops", need="paper"))[0] == ["paper_shop"]


@test("item39 cap: a level finished this cycle (a slot frees), or no cap in the report: nothing held")
def _():
    fin = Proposal("finish", {"type": "finish_project", "project_id": 1}, "x", 4)
    assert _capped(3, 3, fin, _start("homes_dig", "bedrooms"))[0] == ["finish", "homes_dig"]
    s = {"projects": {"open": [{"id": 1, "phase": "dig"}] * 5}, "_errors": {}}
    ps = [_start("homes_dig", "bedrooms")]
    cap_full_pass(s, ps, [])
    assert len(ps) == 1


@test("item39 cap: plan() runs the pass after the small needs are marked")
def _():
    t = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")
    assert t.index("_guard(needs_pass, s, cfg, proposals, memory)") < t.index("_guard(cap_full_pass, s, proposals, notes)")


# --- new_pasture -----------------------------------------------------------------------

from planner import record  # noqa: E402
from planner_core import abs_tick, TICKS_PER_DAY  # noqa: E402


def _graze(memory):
    s = fort()
    s["herd"] = {"tame": 30, "kinds": [], "breeders": 0, "grazing_need": 200, "tameable": 0, "trainers": 1,
                 "war": 0, "pets": 2, "breeding_pairs": 0}
    s.setdefault("society", {}).update({"ai_pastures": 1, "ai_pasture_tiles": 60})
    s["dwarves"]["total"] = 60
    s = digest.normalize(s)
    props, notes = [], []
    PH._husbandry_rules(s, memory, GARDEN, CFG, 60, props, notes)
    return s, [p for p in props if p.rule == "new_pasture"]


@test("item39 new_pasture: refused for want of grass: a season's wait, then twice as long in a row")
def _():
    m = Memory()
    s, got = _graze(m)
    assert got
    r = {"ok": False, "error": "no single patch near the fort with 80 tiles of grass the dwarves can reach"}
    record([(got[0], r)], s, m)
    assert m.pasture_refused.get("n") == 1, m.pasture_refused
    assert not _graze(m)[1]
    m.pasture_refused["tick"] = abs_tick(s) - 90 * TICKS_PER_DAY
    assert _graze(m)[1]                                     # a season on: asked again
    m.pasture_refused["n"] = 2
    assert not _graze(m)[1]                                 # the second in a row: 168 days


@test("item39 new_pasture: the AI's pastures changed, or a pasture made: asked again")
def _():
    m = Memory()
    s, got = _graze(m)
    record([(got[0], {"ok": False, "error": "no free patch of living grass (3x3 or more) near the fort"})], s, m)
    m.pasture_refused["sig"] = [2, 90]
    assert _graze(m)[1]
    record([(got[0], {"ok": True, "zones": [{}], "tiles": 81})], s, m)
    assert m.pasture_refused == {}
    record([(got[0], {"ok": False, "timed_out": True, "error": "search cut short: no single patch near the fort "
                                                               "with 80 tiles of grass the dwarves can reach"})], s, m)
    assert m.pasture_refused == {}                          # a search cut short is no answer


if __name__ == "__main__":
    finish()
