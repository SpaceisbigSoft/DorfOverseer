"""(K48-K4) Usable water (audit A4): only water a dwarf can drink now counts.

  * a dry well (nothing under it) is no well, a frozen one no drinkable well;
    a gallery well behind a door the cavern seal locked is shut;
  * a Water Source zone DF calls empty ("No water source", or the frost
    reading) is no zone: the next one is placed;
  * the frost rule's "a well still draws" leaves out shut cavern wells;
  * winter takes the AI's surface zone down only when the water is ice or
    another source gives water;
  * a refused cavern well is tried again well_retry_days later;
  * the magma workshop's way through a cavern waits for the cavern well's
    danger tests.

    python tests/test_k48_water.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
from planner import PLANNER_CONFIG, TICKS_PER_DAY, Memory, abs_tick  # noqa: E402
import planner_wells as PW  # noqa: E402
import planner_hazards as PH  # noqa: E402
import planner_ice as PI  # noqa: E402
import planner_core  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG


def fort(wells=0, lids=None, frost=None, zones=0, **over) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "summer"
    s.setdefault("buildings", {}).setdefault("other", {})["Well"] = wells
    s["buildings"].setdefault("zones", {})["WaterSource"] = zones
    s.setdefault("projects", {})["open"] = []
    s["projects"]["well_lids"] = lids or []
    if frost is not None:
        s["env_hazards"] = {"frost": frost}
    s.update(over)
    return s


def lid(pid, x, y, gate="closed", **k):
    return dict({"project_id": pid, "x": x + 1, "y": y, "z": 70, "gate": gate, "watch_rule": 2,
                 "shaft_hatch": {"x": x, "y": y, "z": 60}}, **k)


@test("usable wells: a dry well is none, a frozen one no drinkable one, a shut cavern well not counted twice")
def _():
    s = fort(1, frost={"wells": [{"id": 1, "x": 5, "y": 5, "z": 100, "water": "dry"}], "zones": []})
    assert PW.usable_wells(s) == 0            # (was 1: a Well building)
    s["env_hazards"]["frost"]["wells"][0]["water"] = "water"
    assert PW.usable_wells(s) == 1
    s["env_hazards"]["frost"]["wells"][0]["water"] = "ice"
    assert PW.usable_wells(s) == 0 and PW.usable_wells(s, drinkable=False) == 1
    # three wells: a shut cavern well (water under its hatch), a dry one, a good one
    s = fort(3, lids=[lid(7, 40, 40)], frost={"wells": [{"x": 40, "y": 40, "water": "water"},
                                                       {"x": 5, "y": 5, "water": "dry"},
                                                       {"x": 9, "y": 9, "water": "water"}], "zones": []})
    assert PW.usable_wells(s) == 1
    # no frost reading (an older bridge): as before
    s = fort(1)
    assert PW.usable_wells(s) == 1


@test("usable wells: a gallery well whose door the seal locked is shut, whatever its gate")
def _():
    s = fort(1, lids=[lid(7, 40, 40, gate="open")])
    assert PW.usable_wells(s) == 1
    s["projects"]["well_lids"][0]["door_locked"] = True
    assert PW.shut_wells(s) == 1 and PW.usable_wells(s) == 0


@test("water zone: a zone DF calls empty is no zone, the next one is placed (War-hold: notes only)")
def _():
    body = {"kind": "pond", "nearest": {"x": 30, "y": 30, "z": 100, "d": 20}}
    s = fort(0, zones=1, frost={"wells": [], "zones": []},
             recent_announcements=[{"text": "Urist cancels Give Water: No water source."}],
             water={"bodies": [body]})
    s["dwarves"]["needs_medical_care"] = 6
    s.setdefault("society", {})["parched"] = 4
    s.setdefault("others_on_map", {})["threats_that_can_reach_dwarves"] = 0
    assert PW.water_zones_usable(s) == 0
    props, notes = [], []
    PW._water_zone_rule(s, props, notes, CFG)
    assert [p.action["type"] for p in props] == ["water_zone"], (notes, props)
    assert any("another water source is looked for" in n for n in notes)
    # the AI's zone reads as water: it gives water, nothing more
    s["env_hazards"]["frost"]["zones"] = [{"x": 30, "y": 30, "z": 100, "water": "water", "outside": True}]
    assert PW.water_zones_usable(s) == 1
    props, notes = [], []
    PW._water_zone_rule(s, props, notes, CFG)
    assert not props
    # the AI's only zone dry (the pond evaporated): none
    s["env_hazards"]["frost"]["zones"][0]["water"] = "dry"
    s["recent_announcements"] = []
    assert PW.water_zones_usable(s) == 0
    # an older bridge (no frost reading): the zone at its word
    del s["env_hazards"]
    s["recent_announcements"] = [{"text": "No water source"}]
    assert PW.water_zones_usable(s) == 1


@test("shaft short of water: a dry ordinary well or an empty zone doesn't count as water")
def _():
    s = fort(2, lids=[lid(7, 40, 40)], frost={"wells": [{"x": 40, "y": 40, "water": "water"},
                                                       {"x": 5, "y": 5, "water": "dry"}], "zones": []})
    s["dwarves"]["needs_medical_care"] = 3
    assert "3 injured" in PW.shaft_water_short(s, s["projects"]["well_lids"])
    s["env_hazards"]["frost"]["wells"][1]["water"] = "water"
    assert PW.shaft_water_short(s, s["projects"]["well_lids"]) == ""


@test("frost: shut cavern wells don't 'still draw water': the frozen zone is replaced by underground water")
def _():
    under = {"kind": "lake", "underground": True, "nearest": {"x": 50, "y": 50, "z": 80, "d": 30}}
    s = fort(2, lids=[lid(7, 40, 40), lid(8, 44, 44)], zones=1,
             frost={"wells": [{"x": 40, "y": 40, "water": "water"}, {"x": 44, "y": 44, "water": "water"}],
                    "zones": [{"x": 30, "y": 30, "z": 100, "water": "ice", "outside": True}]},
             water={"bodies": [under]})
    s["dwarves"]["needs_medical_care"] = 6
    props, notes = [], []
    PH._frost(s, CFG, s["env_hazards"], None, props, notes)
    assert [p.rule for p in props] == ["frost_water_zone"], (props, notes)
    # the zone rule leaves the frost rule's own case to it (no second water_zone)
    props2, notes2 = [], []
    s.setdefault("others_on_map", {})["threats_that_can_reach_dwarves"] = 0
    PW._water_zone_rule(s, props2, notes2, CFG)
    assert not props2, props2
    # one gate open: it draws, nothing proposed
    s["projects"]["well_lids"][1]["gate"] = "open"
    props, notes = [], []
    PH._frost(s, CFG, s["env_hazards"], None, props, notes)
    assert not props


@test("ice: the AI's only surface zone is kept while no well draws; taken down once one does or it is ice")
def _():
    s = fort(1, lids=[lid(7, 40, 40)],
             frost={"wells": [{"x": 40, "y": 40, "water": "water"}], "surface_temp": 10010, "freezing": False,
                    "zones": [{"x": 30, "y": 30, "z": 100, "water": "water", "outside": True}]})
    s["date"]["season"] = "winter"
    props, notes = [], []
    PI._ice_rule(s, Memory(), CFG, props, notes)
    assert "ice_zones" not in [p.rule for p in props], [p.rule for p in props]
    assert any("only water the dwarves can drink" in n for n in notes), notes
    s["projects"]["well_lids"][0]["gate"] = "open"
    props, notes = [], []
    PI._ice_rule(s, Memory(), CFG, props, notes)
    assert "ice_zones" in [p.rule for p in props]
    s["projects"]["well_lids"][0]["gate"] = "closed"
    s["env_hazards"]["frost"]["zones"][0]["water"] = "ice"
    props, notes = [], []
    PI._ice_rule(s, Memory(), CFG, props, notes)
    assert "ice_zones" in [p.rule for p in props]


@test("cavern well: a refusal is stamped and forgotten well_retry_days later (was: for the fort's life)")
def _():
    s = fort(0)
    m = Memory()
    m.cavern_well_failure = "the search was cut short"
    # an older memory without a stamp: stamped now, still standing
    assert PW.cavern_failure_now(s, m, CFG) == "the search was cut short"
    assert m.cavern_well_failure_at == abs_tick(s)
    m.cavern_well_failure_at = abs_tick(s) - (CFG["well_retry_days"] - 1) * TICKS_PER_DAY
    assert PW.cavern_failure_now(s, m, CFG)
    m.cavern_well_failure_at = abs_tick(s) - CFG["well_retry_days"] * TICKS_PER_DAY
    assert PW.cavern_failure_now(s, m, CFG) == "" and m.cavern_well_failure == ""
    # the record stamps it, and it is saved and read back
    m = Memory()
    planner_core._record_any_outcome({"type": "place_well", "cavern": True}, {"ok": False, "error": "no spot"},
                                     s, m, 12345)
    assert m.cavern_well_failure == "no spot" and m.cavern_well_failure_at == 12345
    m2 = Memory.from_dict(json.loads(json.dumps(m.to_dict())))
    assert m2.cavern_well_failure_at == 12345
    planner_core._record_any_outcome({"type": "place_well", "cavern": True}, {"ok": True}, s, m, 12400)
    assert m.cavern_well_failure == "" and m.cavern_well_failure_at is None


@test("cavern well: the refusal no longer stops a cavern well a season on (_well_rule)")
def _():
    s = fort(0)
    s["dwarves"]["needs_medical_care"] = 6
    m = Memory()
    m.cavern_shaft_stairs = m.well_floor_retried = True
    m.well_failure = "no clean water inside the fort"
    m.cavern_well_failure = "the search was cut short"
    m.cavern_well_failure_at = abs_tick(s)
    props, notes = [], []
    PW._well_rule(s, m, {}, CFG, props, notes)
    assert any("no cavern well either" in n for n in notes), notes
    m.cavern_well_failure_at = abs_tick(s) - 90 * TICKS_PER_DAY
    props, notes = [], []
    PW._well_rule(s, m, {}, CFG, props, notes)
    assert not any("no cavern well either" in n for n in notes), notes


@test("magma: a way to magma through a cavern waits while a danger is about (the cavern well's tests)")
def _():
    import test_waterworks as TW
    cav = {"kind": "magma", "magma": "pipe", "d": 100, "opens_cavern": "Cavern1", "reach_through": 90, "top": {"z": 70}}
    st = TW.state(settings={"traits": {}, "open_caverns": "always"},
                  buildings={"workshops": {"MetalsmithsForge": 1}, "furnaces": {}, "other": {}},
                  water={"bodies": [], "waters": [cav], "middle": {"z_low": 90}}, map={"layers": []})
    props, notes = TW.run(st)
    acts = [p.action for p in props if p.action.get("kind") == "magma"]
    assert acts and acts[0].get("open_caverns") is True, (acts, notes)
    st["deep"] = {"dangers": [{"name": "The Abyssal Squid"}]}
    props, notes = TW.run(st)
    assert not [p for p in props if p.action.get("kind") == "magma"]
    assert any("Abyssal Squid" in n and "opens a cavern" in n for n in notes), notes
    st["deep"] = {}
    st["projects"]["well_lids"] = [lid(7, 40, 40, watch_near={"name": "a cave crocodile", "d": 12, "mobile": False})]
    props, notes = TW.run(st)
    assert not [p for p in props if p.action.get("kind") == "magma"] and any("crocodile" in n for n in notes)
    assert PW.cavern_open_danger(TW.state()) == ""


if __name__ == "__main__":
    finish()
