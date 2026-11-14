"""(item7) Actions repeated without effect:

  (a) the quarry: B (13 Nov) marked seven quarries of 4-7 tiles in three
      minutes, "only 8 boulders" every time. Now one at a time: the last one
      dug (the bridge's word on its tiles) and its stone counted before the
      next; a pause when quarries bring no stone the masons may use; none
      while ordinary stone lies forbidden; sized to what is short.
  (b) the cavern seal: "no door or hatch on the way down to lock" over and
      over. With nothing to lock the AI closes the way itself (doors, or the
      opening walled), maps the entrances first, or says the fort's own
      ground has no way down.
  (c) "no free floor in zone N" (statues) and "every finished level is
      polished": backed off properly.

    python tests/test_item7.py
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

import planner  # noqa: E402
import planner_industry as PI  # noqa: E402
import planner_threats as PT  # noqa: E402
import planner_locations as PLOC  # noqa: E402
import planner_nobles as PN  # noqa: E402
from planner import Memory, PLANNER_CONFIG, Proposal, plan, record, select, note_cycle  # noqa: E402
from planner_core import abs_tick, TICKS_PER_DAY, zone_full_days  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = dict(PLANNER_CONFIG)
DAY = TICKS_PER_DAY


def fort(**kw) -> dict:
    s = copy.deepcopy(BASE)
    s.update(kw)
    return s


def stone_fort(usable=8, in_job=0, forbidden=0, quarry=None, dig=0):
    s = fort()
    s["stone_use"] = {"usable": usable, "economic": {}, "fuel_free": {}, "in_job": in_job, "forbidden": forbidden}
    if quarry is not None:
        s["stone_use"]["quarry"] = quarry
    s["labor"] = {"dig": dig}
    return s


def stone_props(s, m):
    props, notes = [], []
    PI._stone_rule(s, m, CFG, props, notes)
    return [p for p in props if p.rule == "quarry"], notes


def dug(m, s, tiles=5, at=(10, 20, 30)):
    p = Proposal("quarry", {"type": "quarry", "count": 12}, "x", 4)
    record([(p, {"ok": True, "tiles": tiles, "x": at[0], "y": at[1], "z": at[2], "stone": "GRANITE"})], s, m)


def later(s, days):
    s = copy.deepcopy(s)
    s["date"]["tick"] += int(days * DAY)
    return s


# --- (a) the quarry -------------------------------------------------------------------

@test("quarry: sized to lift the masons' stone to twice stone_low, at least quarry_min_tiles, at most the slider's")
def _():
    assert PI.quarry_size(stone_fort(usable=8), CFG) == 12
    assert PI.quarry_size(stone_fort(usable=0), CFG) == 20
    assert PI.quarry_size(stone_fort(usable=9), CFG) == 11
    big = dict(CFG, stone_low=40)
    assert PI.quarry_size(stone_fort(usable=0), big) == 20          # Mining 0: the slider's 20 at most
    assert PI.quarry_size(stone_fort(usable=19), CFG) == CFG["quarry_min_tiles"]


@test("quarry: one at a time: none while the last one's tiles are still to dig (the bridge says), said")
def _():
    s = stone_fort()
    m = Memory()
    q, _ = stone_props(s, m)
    assert q and q[0].action == {"type": "quarry", "count": 12}, q
    dug(m, s)
    assert m.quarry_seen["before"] == 8 and m.quarry_seen["tiles"] == 5 and not m.quarry_seen["settled"]
    s2 = later(stone_fort(quarry={"pending": 3, "dug": 2, "dropped": 0, "tiles": 5, "x": 10, "y": 20, "z": 30}), 3)
    s2["date"] = later(s, 3)["date"]
    note_cycle(s2, m)
    assert not m.quarry_seen["settled"]
    q, notes = stone_props(s2, m)
    assert not q, q
    assert any("3 of the last quarry's 5 tiles still to dig" in n for n in notes), notes
    # still waiting after the cooldown (2 days) is long over: the tiles decide, not the clock
    s3 = copy.deepcopy(s2)
    s3["date"] = later(s, 20)["date"]
    note_cycle(s3, m)
    assert not stone_props(s3, m)[0]
    # undug for quarry_stall_days: counted as it is (a strike), and another may come
    s4 = copy.deepcopy(s2)
    s4["date"] = later(s, 29)["date"]
    note_cycle(s4, m)
    assert m.quarry_seen["settled"] and m.quarry_seen["strikes"] == 1 and "undug 28 days" in m.quarry_seen["why"]
    assert stone_props(s4, m)[0]


@test("quarry: dug and the stone rose: counted, and the next quarry may come")
def _():
    s = stone_fort()
    m = Memory()
    dug(m, s)
    s2 = stone_fort(usable=9, in_job=3, quarry={"pending": 0, "dug": 5, "dropped": 0, "tiles": 5,
                                                "x": 10, "y": 20, "z": 30})
    s2["date"] = later(s, 3)["date"]
    note_cycle(s2, m)
    assert m.quarry_seen["settled"] and m.quarry_seen["gain"] == 4 and m.quarry_seen["strikes"] == 0
    q, _ = stone_props(s2, m)
    assert q and q[0].action["count"] == 11, q


@test("quarry: two quarries in a row that brought no stone the masons may use: a pause, doubled the next time")
def _():
    s = stone_fort()
    m = Memory()
    notes_all = []
    t = 0
    for i in range(2):
        st = copy.deepcopy(s)
        st["date"] = later(s, t)["date"]
        dug(m, st, at=(10 + i * 10, 20, 30))
        t += 3
        st2 = stone_fort(usable=8, quarry={"pending": 0, "dug": 5, "dropped": 0, "tiles": 5,
                                           "x": 10 + i * 10, "y": 20, "z": 30})
        st2["date"] = later(s, t)["date"]
        notes_all += note_cycle(st2, m)
    assert m.quarry_seen["pauses"] == 1 and isinstance(m.quarry_seen["until"], int), m.quarry_seen
    assert any("no quarry for 7 days" in n for n in notes_all), notes_all
    q, notes = stone_props(st2, m)
    assert not q and any("next try in 7 day(s)" in n for n in notes), notes
    st3 = copy.deepcopy(st2)
    st3["date"] = later(s, t + 8)["date"]
    assert stone_props(st3, m)[0], "the pause is over"
    # two more with nothing: 14 days
    for i in range(2):
        st = copy.deepcopy(s)
        st["date"] = later(s, t)["date"]
        dug(m, st, at=(50 + i * 10, 20, 30))
        t += 3
        st2 = stone_fort(usable=8, quarry={"pending": 0, "dug": 0 if i else 5, "dropped": 5 if i else 0,
                                           "tiles": 5, "x": 50 + i * 10, "y": 20, "z": 30})
        st2["date"] = later(s, t)["date"]
        notes_all += note_cycle(st2, m)
    assert m.quarry_seen["pauses"] == 2 and any("no quarry for 14 days" in n for n in notes_all), notes_all
    assert "never dug" in m.quarry_seen["why"], m.quarry_seen


@test("quarry: ordinary stone lying forbidden: no quarry (it adds nothing the masons may take), said")
def _():
    m = Memory()
    q, notes = stone_props(stone_fort(usable=3, forbidden=40), m)
    assert not q and any("40 boulders of ordinary stone lie forbidden" in n for n in notes), notes
    # forbidden stone rising after a quarry: the strike says so
    s = stone_fort(usable=3, forbidden=2)
    dug(m, s)
    s2 = stone_fort(usable=3, forbidden=7, quarry={"pending": 0, "dug": 5, "dropped": 0, "tiles": 5,
                                                   "x": 10, "y": 20, "z": 30})
    s2["date"] = later(s, 2)["date"]
    note_cycle(s2, m)
    assert m.quarry_seen["strikes"] == 1 and "forbidden" in m.quarry_seen["why"], m.quarry_seen


@test("quarry: an older bridge (no word on its tiles): the quarry gets quarry_settle_days, then is counted")
def _():
    s = stone_fort()
    m = Memory()
    dug(m, s)
    s2 = stone_fort()
    s2["date"] = later(s, 1)["date"]
    note_cycle(s2, m)
    q, notes = stone_props(s2, m)
    assert not q and any("given 3 days" in n for n in notes), notes
    s3 = stone_fort(usable=15)
    s3["date"] = later(s, 3)["date"]
    note_cycle(s3, m)
    assert m.quarry_seen["settled"] and m.quarry_seen["gain"] == 7 and not stone_props(s3, m)[0]
    s4 = stone_fort(usable=9)
    s4["date"] = later(s, 3)["date"]
    assert stone_props(s4, m)[0]


@test("quarry: a refused or dry-run quarry is not taken for one dug; a stale memory is forgotten")
def _():
    s = stone_fort()
    m = Memory()
    p = Proposal("quarry", {"type": "quarry", "count": 12}, "x", 4)
    record([(p, {"ok": False, "error": "no wall"})], s, m)
    assert not m.quarry_seen
    m.quarry_seen = {"tick": abs_tick(s) - 500 * DAY, "tiles": 5, "settled": False}
    assert PI.quarry_wait(s, m, CFG) == ""


# --- (b) the cavern seal ------------------------------------------------------------------

def cave(entrances=None, column=None, fresh=True, ops=None):
    s = fort()
    s["map"]["elevation_offset"] = -100
    s["threats"] = {"sealed": {}, "openings": {"list": ops or []}}
    s["deep"] = {"caverns": [{"name": "Cavern1", "discovered": True, "open": True, "z_top": 146, "z_bottom": 123,
                              "open_at": {"x": 128, "y": 143, "z": 142}, "junctions": [],
                              "column": column if column is not None else
                              [{"z": 142, "shape": "FLOOR"}, {"z": 143, "shape": "WALL"}]}],
                 "dangers": [{"id": 50, "name": "Ozkak", "kind": "forgotten beast", "layer": "Cavern1"}],
                 "cursed": []}
    s["entrances"] = {"scanned": True, "inside_tiles": 9534, "armed": True,
                      "scanned_tick": abs_tick(s) - (100 if fresh else 5 * DAY),
                      "entrances": [{"id": 1, "kind": "surface", "x": 108, "y": 149, "z": 170, "sealed": True,
                                     "door_spots": 0, "width": 1}] + (entrances or [])}
    return s


def beasts(s, m=None):
    props, notes = [], []
    PT._cavern_beasts(s, CFG, m or Memory(), s["threats"], PT.threat_rules_of(s), props, notes)
    return props, notes


@test("cavern: nothing to lock and a fresh map with no cavern opening (B, 13 Nov): no seal, no Needs you, said why")
def _():
    props, notes = beasts(cave())
    assert not [p for p in props if p.rule == "seal_cavern"], props
    line = [n for n in notes if "no way down to Cavern1" in n]
    assert line and not line[0].startswith("[you]") and "nothing to lock" in line[0], notes
    # the deep note no longer says "the AI walls the openings it finds" there
    s = cave()
    s["deep"]["dangers"] = []
    _, notes = plan(s, Memory())
    assert any("finds no way down from inside the fort" in n for n in notes), [n for n in notes if "Cavern1" in n]
    assert not any("walls or doors the openings it finds" in n for n in notes)


@test("cavern: nothing to lock and an older map: mapped again first (no seal)")
def _():
    props, _ = beasts(cave(fresh=False))
    assert [p.action for p in props if p.rule == "cavern_scan"] == [{"type": "scan_entrances"}], props
    assert not [p for p in props if p.rule == "seal_cavern"], props


@test("cavern: an opening the map found, nothing on it: doors where a door can go, else walled up (sealed gate)")
def _():
    e = {"id": 3, "kind": "cavern", "x": 128, "y": 140, "z": 146, "sealed": False, "door_spots": 2, "width": 2}
    m = Memory()
    m.gate_doors_requested = ["128,140,146"]       # (so _cavern_doors' own request doesn't come first)
    props, _ = beasts(cave(entrances=[e]), m)
    d = [p for p in props if p.rule == "cavern_openings"]
    assert d and d[0].action == {"type": "build_gate_doors", "entrance_id": 3} and d[0].priority == 1, props
    assert not [p for p in props if p.rule == "seal_cavern"], props
    e2 = dict(e, door_spots=0, width=4)
    props, _ = beasts(cave(entrances=[e2]))
    d = [p for p in props if p.rule == "cavern_openings"]
    assert d and d[0].action == {"type": "fortify_entrance", "entrance_id": 3, "style": "sealed"}, props
    assert "not while a citizen is beyond it" in d[0].reason
    # one being shut: said, nothing more asked
    props, notes = beasts(cave(entrances=[dict(e2, closing=True)]))
    assert not [p for p in props if p.rule in ("cavern_openings", "seal_cavern")], props
    assert any("shut or being shut" in n for n in notes), notes


@test("cavern: something to lock (a door on record, a hatch in the column, junctions): the seal as before")
def _():
    props, _ = beasts(cave(ops=[{"x": 1, "y": 2, "z": 3, "kind": "gate", "building": "Door", "built": True}]))
    assert [p for p in props if p.rule == "seal_cavern"], props
    props, _ = beasts(cave(column=[{"z": 142, "shape": "STAIR_UP", "building": "Hatch"}]))
    assert [p for p in props if p.rule == "seal_cavern"], props
    s = cave()
    s["deep"]["caverns"][0]["junctions"] = [{"x": 1, "y": 2, "z": 147, "cave": {"x": 1, "y": 2, "z": 146}}]
    props, _ = beasts(s)
    assert [p for p in props if p.rule == "seal_cavern"], props
    # a well's hatch is never the seal's: still nothing to lock
    props, _ = beasts(cave(ops=[{"x": 1, "y": 2, "z": 3, "kind": "well", "building": "Hatch", "locked": True}]))
    assert not [p for p in props if p.rule == "seal_cavern"], props


# --- (c) statues with no free floor, the polish ----------------------------------------------

def refused_place(m, s, zone, rule="grandeur"):
    p = Proposal(rule, {"type": "place_in_zone", "zone_id": zone, "what": "statue"}, "x", 6)
    record([(p, {"ok": False, "rejected": True, "error": f"no free floor in zone {zone}"})], s, m)
    return p


@test("zone full: no free floor books the zone 28 days, doubled in a row; held in select; a placement clears it")
def _():
    s = fort()
    m = Memory()
    p = refused_place(m, s, 139)
    now = abs_tick(s)
    assert zone_full_days(m, 139, now) == 28 and m.place_full["139"]["n"] == 1
    allowed, held = select([p], s, m)
    assert not allowed and any("zone 139 has no free floor" in h for h in held), held
    s2 = later(s, 29)
    assert zone_full_days(m, 139, abs_tick(s2)) is None
    refused_place(m, s2, 139)
    assert zone_full_days(m, 139, abs_tick(s2)) == 56
    p_ok = Proposal("grandeur", {"type": "place_in_zone", "zone_id": 139, "what": "statue"}, "x", 6)
    record([(p_ok, {"ok": True})], s2, m)
    assert zone_full_days(m, 139, abs_tick(s2)) is None
    # another refusal ("no such zone") isn't a full room
    record([(p_ok, {"ok": False, "error": "no such zone"})], s2, m)
    assert zone_full_days(m, 139, abs_tick(s2)) is None


@test("grandeur: a hall with no free floor waits; the next-least valuable hall gets the statue; all full: said")
def _():
    s = fort()
    s["settings"]["traits"] = {"grandeur": 60}
    s["stocks"] = dict(s.get("stocks") or {}, drink=10000)
    s["supplies"] = dict(s.get("supplies") or {}, statues=2)
    s["locations"] = {"list": [{"type": "INN_TAVERN", "zones": [139], "value": 700},
                               {"type": "TEMPLE", "zones": [200], "value": 900}]}
    real = PLOC.young_fort, PLOC.food_per_dwarf
    PLOC.young_fort, PLOC.food_per_dwarf = (lambda *a: False), (lambda *a: 1000)
    try:
        m = Memory()
        props, notes = [], []
        PLOC._grandeur_rule(s, CFG, props, notes, m)
        assert props and props[0].action["zone_id"] == 139, props
        refused_place(m, s, 139)
        props, notes = [], []
        PLOC._grandeur_rule(s, CFG, props, notes, m)
        assert props and props[0].action["zone_id"] == 200, props
        refused_place(m, s, 200)
        props, notes = [], []
        PLOC._grandeur_rule(s, CFG, props, notes, m)
        assert not props and any("no free floor for another statue" in n for n in notes), notes
    finally:
        PLOC.young_fort, PLOC.food_per_dwarf = real


@test("noble room booked full: no statue put in nor ordered for it; polished or 'wants finer furniture' instead")
def _():
    s = fort()
    s["supplies"] = dict(s.get("supplies") or {}, statues=3)
    s["noble_demands"] = {"nobles": [{"unit_id": 1, "name": "Udib", "title": None, "positions": ["MAYOR"],
                                      "rooms": [{"kind": "bedroom", "need": 500, "value": 429, "zone_id": 286,
                                                 "statues": 0}]}]}
    m = Memory()
    plan_ = PN.noble_room_plan(s, CFG, m)
    assert plan_[0]["action"] == {"type": "place_in_zone", "zone_id": 286, "what": "statue"}, plan_
    refused_place(m, s, 286, "noble_value")
    plan_ = PN.noble_room_plan(s, CFG, m)
    assert plan_[0]["action"] is None and plan_[0]["plan"].startswith("wants finer"), plan_
    s["noble_demands"]["nobles"][0]["rooms"][0].update(ai_built=True, smooth_left=12)
    plan_ = PN.noble_room_plan(s, CFG, m)
    assert plan_[0]["action"] == {"type": "polish_room", "zone_id": 286}, plan_


@test("polish: 'every finished level is polished' twice in a row: a pause even when a level finishes meanwhile")
def _():
    s = fort()
    s["projects"] = dict(s.get("projects") or {}, done_total=40, finished=20)
    m = Memory()
    pol = Proposal("polish", {"type": "polish"}, "x", 7)
    no = {"ok": False, "rejected": True, "error": "every finished level is polished"}
    record([(pol, no)], s, m)
    assert m.polish_seen["n"] == 1 and not planner.polish_paused(m, abs_tick(s), CFG)
    s2 = later(s, 1)
    s2["projects"]["done_total"] = 41
    record([(pol, no)], s2, m)
    assert m.polish_seen["n"] == 2 and planner.polish_paused(m, abs_tick(s2), CFG)
    s3 = later(s2, 10)
    s3["projects"]["done_total"] = 42
    s3["dwarves"]["idle_adults"] = s3["dwarves"].get("adults") or 50
    assert not [p for p in plan(s3, m)[0] if p.rule == "polish"]
    assert not planner.polish_paused(m, abs_tick(later(s2, 15)), CFG)
    record([(pol, no)], later(s2, 15), m)
    assert planner.polish_paused(m, abs_tick(later(s2, 15 + 27)), CFG)          # 28 days the third time
    record([(pol, {"ok": True, "designated": 30})], later(s2, 50), m)
    assert not m.polish_seen


if __name__ == "__main__":
    finish()
