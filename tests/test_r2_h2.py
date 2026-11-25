"""(r2 h2) Winter water for a fort like B: the winter cistern.

B (R-B finding 1): the only water was a stagnant brook and pond on the
surface (38 tiles, elevation 41-43) that froze every winter; no drop to water
inside the fort ("no open drop ..." 78 times); Cavern1 unfound, the Rules
switch "Cavern well into an unfound cavern" at "ai" and no armed soldier
(Militarism -60); the survey's cistern "none" (no tunnel through solid rock).
Round 1's winter rule (r1 g3) found nothing to propose, and every bedridden
dwarf of every winter died of thirst (5 dead: a patient gets only water,
carried in a bucket). The fix: a small chamber in solid rock one level under
a floor inside the fort, a well over it and a pond zone on the well, filled
by bucket while the surface water is liquid.

    python tests/test_r2_h2.py
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import make_test, test as plain_test, finish, need_lua, skip  # noqa: E402
from planner import PLANNER_CONFIG, Memory, Proposal, TICKS_PER_DAY, abs_tick  # noqa: E402
from planner import record  # noqa: E402
import planner_wells  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except Exception:  # noqa: BLE001
    LuaRuntime = None

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
B_REFUSAL = ("no open drop from a free floor inside the fort to clean water; and the water near the surface "
             "freezes in winter (a well over it would be taken down), so the AI looks only inside the fort")


def b_fort(season: str = "autumn", tick: int = 210000, year: int = 250) -> dict:
    """Fort B as R-B and run2/B/state-last.json have it: 16 citizens, no well
    that works (the shore well over the brook at x67-73 y122-125 given up
    before the ice), the surface near freezing in autumn, the cavern water at
    x125 y126 z136 in Cavern1 (z123-146) that no dwarf has found, the Rules
    switch at "ai", no squad, Militarism -60, the survey's cistern "none"."""
    s = copy.deepcopy(BASE)
    s["date"] = {"day": 4, "month": "Timber", "season": season, "tick": tick, "year": year}
    s["dwarves"]["total"] = 16
    s["dwarves"]["needs_medical_care"] = 0
    s["society"]["parched"] = 0
    s["buildings"]["other"].pop("Well", None)
    s["buildings"].setdefault("zones", {}).pop("WaterSource", None)
    s["projects"]["open"] = []
    s["projects"]["well_lids"] = []
    s["projects"]["max_open"] = 2
    s["env_hazards"] = {"frost": {"surface_temp": 10030, "freezing": False, "wells": [], "zones": [], "on_ice": []}}
    s["water"] = {"ok": True, "done": True, "tick": 106231076,
                  "bodies": [{"kind": "surface", "tiles": 38, "stagnant_share": 100, "salt_share": 0,
                              "nearest": {"d": 53, "depth": 7, "x": 73, "y": 124, "z": 170}},
                             {"kind": "cavern", "tiles": 12390, "stagnant_share": 0, "salt_share": 0,
                              "nearest": {"d": 68, "depth": 7, "x": 125, "y": 126, "z": 136}}],
                  "cistern": {"none": True, "why": "no tunnel through solid rock from a cistern site to still water "
                                                   "(the nearest still water on a cistern's levels is 16 tiles from a "
                                                   "fort floor; a tunnel reaches 70)"}}
    s["map"]["layers"] = [{"name": "Cavern1", "z_top": 146, "z_bottom": 123, "discovered": False},
                          {"name": "Cavern2", "z_top": 118, "z_bottom": 114, "discovered": False}]
    s["map"].setdefault("dwarves", {})["z_bottom"] = 160
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s["others_on_map"]["threats"] = []
    s.setdefault("deep", {})["dangers"] = []
    s.setdefault("well_safety", {})["book"] = {"active": [], "closed_sites": 0, "cooldown_days_left": 0}
    s["settings"]["open_caverns"] = "ai"
    s["settings"].setdefault("traits", {})["militarism"] = -60
    s["military"]["squads"] = []
    s.setdefault("supplies", {})["buckets"] = 3
    return s


def memory() -> Memory:
    m = Memory()
    m.well_floor_retried = True
    m.cavern_shaft_stairs = True
    m.well_failure = B_REFUSAL
    return m


def winter(s, m=None, cfg=None, rules=None):
    p, n = [], []
    planner_wells._winter_water_rule(s, m if m is not None else memory(), cfg or PLANNER_CONFIG, p, n, rules or {})
    return p, n


def cistern_props(p):
    return [x for x in p if x.rule == "winter_water" and x.action.get("type") == "place_well"
            and x.action.get("filled")]


# ---- the brain ---------------------------------------------------------------------------

@plain_test("B as it was (Cavern1 unfound, switch at 'ai', no soldier, no cistern site): a winter cistern, not nothing")
def _():
    s = b_fort()
    p, n = winter(s)
    c = cistern_props(p)
    assert c, ([(x.rule, x.action) for x in p], n)
    assert c[0].action == {"type": "place_well", "filled": True}, c[0].action      # early autumn: not urgent
    assert "3x3 chamber in solid rock" in c[0].reason and "flowing river or brook" not in c[0].reason, c[0].reason
    assert "open water on the surface" in c[0].reason and "no cistern site" in c[0].reason, c[0].reason
    # it opens nothing: no cavern action of any kind
    assert not [x for x in p if x.action.get("cavern") or x.action.get("open_caverns")], [x.action for x in p]


@plain_test("winter or patients waiting: the winter cistern is urgent (dug first, over the slot cap)")
def _():
    s = b_fort(season="winter", tick=340000)
    s["dwarves"]["needs_medical_care"] = 2
    s["projects"]["open"] = [{"id": i, "kind": "rooms", "phase": "dig"} for i in range(2)]
    p, n = winter(s)
    c = cistern_props(p)
    assert c and c[0].action.get("urgent") is True and c[0].priority == 2, [(x.action, x.priority) for x in p]


@plain_test("the switch at 'ai' with armed soldiers: the cistern first, the unfound cavern only after a cistern refusal")
def _():
    s = b_fort()
    s["military"]["squads"] = [{"id": 1, "members": 4, "power": {"armed": 4}}]
    p, n = winter(s)
    assert cistern_props(p) and not [x for x in p if x.action.get("cavern")], [x.action for x in p]
    m = memory()
    m.filled_well_failure = "no floor inside the fort over 3x3 tiles of solid rock for a winter cistern"
    m.filled_well_failure_at = abs_tick(s) - TICKS_PER_DAY
    p, n = winter(s, m)
    assert p and p[0].action.get("cavern") and p[0].action.get("open_caverns") is True, [x.action for x in p]
    # the refusal a season old: the cistern is asked again
    m.filled_well_failure_at = abs_tick(s) - 40 * TICKS_PER_DAY
    p, n = winter(s, m)
    assert cistern_props(p), [x.action for x in p]
    # a found cavern (the shaft opens nothing new): the cavern well, as round 1 had it
    s["map"]["layers"][0]["discovered"] = True
    p, n = winter(s)
    assert p and p[0].action.get("cavern") and not cistern_props(p), [x.action for x in p]


@plain_test("no winter cistern while enemies reach the dwarves, with water works off, or switched off: said why")
def _():
    s = b_fort()
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 2
    p, n = winter(s)
    assert not cistern_props(p) and any("no winter cistern now: enemies" in x for x in n), (p, n)
    s = b_fort()
    p, n = winter(s, rules={"water_works": False})
    assert not cistern_props(p) and any("water works are off" in x for x in n), (p, n)
    cfg = dict(PLANNER_CONFIG, h2_winter_cistern=False)
    p, n = winter(b_fort(), cfg=cfg)
    assert not cistern_props(p) and any("is off" in x for x in n), (p, n)


@plain_test("record: a winter cistern refused is booked as its own failure (not 'no well can be placed')")
def _():
    s = b_fort()
    m = Memory()
    record([(Proposal("winter_water", {"type": "place_well", "filled": True}, "x", 3),
             {"ok": False, "filled": True, "error": "no floor inside the fort over 3x3 tiles of solid rock"})], s, m)
    assert m.filled_well_failure.startswith("no floor inside") and m.filled_well_failure_at is not None
    assert m.well_failure == "" and m.cavern_well_failure == "", (m.well_failure, m.cavern_well_failure)
    record([(Proposal("winter_water", {"type": "place_well", "filled": True}, "x", 3),
             {"ok": True, "project_id": 9})], s, m)
    assert m.filled_well_failure == "" and m.filled_well_failure_at is None


@plain_test("being dug: a note; the shore well (its fill source) still goes on beside it")
def _():
    s = b_fort(season="summer", tick=150000)
    s["projects"]["open"] = [{"id": 80, "kind": "well", "phase": "dig", "summary": {"filled": True}}]
    m = memory()
    m.climate_freezes = True
    m.well_failure = ""
    p, n = winter(s, m)
    assert not p and any("the winter cistern is being made (project 80)" in x for x in n), (p, n)
    p, n = [], []
    planner_wells._well_rule(s, m, {}, PLANNER_CONFIG, p, n)
    assert [x.action for x in p if x.rule == "well"] and not p[0].action.get("filled"), ([x.action for x in p], n)
    # any other well being made holds the well rule, as before
    s["projects"]["open"] = [{"id": 81, "kind": "well", "phase": "dig", "summary": {"shore": True}}]
    p, n = [], []
    planner_wells._well_rule(s, m, {}, PLANNER_CONFIG, p, n)
    assert not [x for x in p if x.rule == "well"], [x.action for x in p]


@plain_test("built and filling (a pond on the well, dry or under 3/7): a note, buckets ordered, nothing else; 3/7: winter water")
def _():
    s = b_fort(season="summer", tick=150000)
    m = memory()
    m.climate_freezes = True
    s["buildings"]["other"]["Well"] = 1
    s["supplies"]["buckets"] = 0
    s["stocks"]["wood"] = 30
    well = {"id": 90, "x": 108, "y": 152, "z": 166, "water": "dry", "pond": True}
    s["env_hazards"]["frost"]["wells"] = [well]
    p, n = winter(s, m)
    assert [x.action for x in p] == [{"type": "work_order", "recipe": "wooden_bucket", "amount": 2}], [x.action for x in p]
    assert any("being filled by bucket (0/7" in x for x in n), n
    # 2/7: still no water for the bucket (a well needs 3/7): not a usable well
    well.update(water="water", depth=2)
    s["supplies"]["buckets"] = 4
    assert planner_wells.usable_wells(s) == 0
    p, n = winter(s, m)
    assert not p and any("(2/7" in x for x in n), (p, n)
    # 4/7: the fort has water that works in winter; nothing more is asked
    well["depth"] = 4
    assert planner_wells.usable_wells(s) == 1
    assert planner_wells.winter_water_need(s, m, PLANNER_CONFIG) == ""
    assert winter(s, m) == ([], [])
    # an ordinary well's depth is not read this way (no pond zone): water is water
    well.update(pond=None, depth=None)
    assert planner_wells.usable_wells(s) == 1


@plain_test("B's first year: winter water before its first winter (autumn warning -> dug -> filled -> no need in winter)")
def _():
    m = memory()
    # 1. first autumn, the surface 30 degrees over freezing (g3's warning), the shore well over the brook
    s = b_fort(season="autumn", tick=210000, year=250)
    s["buildings"]["other"]["Well"] = 1
    s["env_hazards"]["frost"]["wells"] = [{"id": 49, "x": 72, "y": 124, "z": 170, "water": "water", "outside": True}]
    p, n = winter(s, m)
    assert cistern_props(p), (p, n)
    record([(cistern_props(p)[0], {"ok": True, "project_id": 80, "filled": True, "x": 108, "y": 152})], s, m)
    # 2. being dug and built: a note only
    s["projects"]["open"] = [{"id": 80, "kind": "well", "phase": "furnish", "summary": {"filled": True}}]
    p, n = winter(s, m)
    assert not p, [x.action for x in p]
    # 3. built, filled by bucket from the shore well while the brook is liquid
    s["projects"]["open"] = []
    s["buildings"]["other"]["Well"] = 2
    s["env_hazards"]["frost"]["wells"].append({"id": 91, "x": 108, "y": 152, "z": 166, "water": "water",
                                               "pond": True, "depth": 5})
    # 4. winter: the brook is ice, the cistern's water is not
    s["date"] = {"day": 1, "month": "Opal", "season": "winter", "tick": 340000, "year": 250}
    s["env_hazards"]["frost"].update(surface_temp=9990, freezing=True)
    s["env_hazards"]["frost"]["wells"][0]["water"] = "ice"
    assert planner_wells.winter_wells(s) == (1, 1)
    assert planner_wells.winter_water_need(s, m, PLANNER_CONFIG) == ""
    assert planner_wells.usable_wells(s) == 1


@plain_test("plan(): B's state gives the winter cistern")
def _():
    from planner import plan
    s = b_fort()
    props, notes = plan(s, memory())
    c = cistern_props(props)
    assert c, [(x.rule, x.action) for x in props]


@plain_test("config: the h2 block sits before the floors block")
def _():
    keys = list(PLANNER_CONFIG)
    assert keys.index("h2_winter_cistern_retry_days") < keys.index("floor_gap"), "the h2 block must come before the floors block"
    assert PLANNER_CONFIG["h2_winter_cistern_half"] == 1


# ---- the bridge ------------------------------------------------------------------------

def _const(path: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / path).read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name)


def boot():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(ROOT / "lua")
    layouts = (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8")
    builder = (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8")
    B, W = lua.execute(_const("test_builder.py", "HARNESS"), layouts, builder)
    lua.execute("df = {global = {cur_year = 148, cur_year_tick = 100}}")
    return lua, B, W


if LuaRuntime is not None:
    LUA, B, W = boot()


def _reset():
    need_lua()
    W.reset()
    B.well_miners = lambda: W.citizens
    B.CAVERN_NO_SPOT = None


test = make_test(before=_reset)

NOW = None


def rock_block():
    """The fort's levels z66-80 are dug out over x40-80 y55-65 (the harness):
    every floor has a dug level under it but z66. Under a corner of z71 the
    rock is left whole (z70 x42-50 y55-61, z69 x44-48 y56-60): the one place
    with solid rock under a floor on a level the dwarves are on."""
    for x in range(42, 51):
        for y in range(55, 62):
            W.set(x, y, 70, LUA.table_from({"shape": "WALL"}))
    for x in range(44, 49):
        for y in range(56, 61):
            W.set(x, y, 69, LUA.table_from({"shape": "WALL"}))


def place(dry=False, **params):
    return B.place_well(LUA.table_from({"filled": True, **params}), LUA.table_from({"year": 148, "tick": 100}), dry)


if LuaRuntime is not None:
    @test("bridge: the winter cistern goes over whole rock (z71 over the kept rock), its chamber dug a level down")
    def _():
        rock_block()
        r = place()
        assert r.ok and r.filled, (r.ok, r.error)
        assert 44 <= r.x <= 48 and 57 <= r.y <= 59 and r.chamber == 8, (r.x, r.y, r.chamber)
        top = W.get(r.x, r.y, 71)
        assert top.designated and top.dig_text.startswith("h"), dict(top)
        dug = [(x, y) for x in range(r.x - 1, r.x + 2) for y in range(r.y - 1, r.y + 2)
               if (x, y) != (r.x, r.y) and W.get(x, y, 70).designated and W.get(x, y, 70).dig_text == "d"]
        assert len(dug) == 7, dug      # (item28) one side of the ramp kept rock: the digger's way out
        # nothing outside the chamber designated on z70 (the ring stays rock)
        ring = [(x, y) for x in range(r.x - 2, r.x + 3) for y in range(r.y - 2, r.y + 3)
                if max(abs(x - r.x), abs(y - r.y)) == 2 and W.get(x, y, 70).designated]
        assert not ring, ring
        rep = B.projects_report().open[1]
        assert rep.dig.total == 8, rep.dig.total
        # the project: a well, its pond zone on the well's tile, filled by bucket
        data = B.load_projects()
        p = data.list[len(data.list)]
        assert p.kind == "well" and p.summary.filled and p.cells.zone[1].text == 'p{name="AI winter cistern"}'
        # undone on cancel: the chamber's designations taken back too
        assert B.cancel_project(r.project_id, False).ok
        assert W.calls[len(W.calls)].command == "undo"

    @test("bridge: no spot where the chamber wouldn't be closed all round, has water beside it, or lacks rock under it")
    def _():
        r = place(True)
        assert not r.ok and r.filled and "3x3 tiles of solid rock" in r.error, r.error
        rock_block()
        # an aquifer in the ring: never there
        for y in range(55, 62):
            W.set(42, y, 70, LUA.table_from({"aquifer": True}))
            W.set(43, y, 70, LUA.table_from({"aquifer": True}))
        for y in range(55, 62):
            W.set(44, y, 70, LUA.table_from({"aquifer": True}))
        r = place(True)
        assert r.ok and r.x >= 47, (r.ok, r.error, r.x if r.ok else None)
        # a tunnel dug through the rest of the ring: no spot left, the why said
        for y in range(55, 62):
            W.set(49, y, 70, LUA.table_from({"shape": "FLOOR"}))
        r = place(True)
        assert not r.ok and ("closed all round" in r.error or "water or an aquifer" in r.error), r.error
        # a 5x5 (the brain's h2_winter_cistern_half 2) fits the block only at its middle
        W.reset()
        rock_block()
        r = place(True, half=2)
        assert r.ok and (r.x, r.y) == (46, 58) and r.chamber == 24, (r.ok, r.error)
        W.set(44, 56, 69, LUA.table_from({"shape": "FLOOR"}))      # a hole under its corner
        r = place(True, half=2)
        assert not r.ok and "5x5" in r.error and "no solid rock under the chamber" in r.error, r.error

    @test("bridge: winter cistern (item28): one side of the well's ramp stays rock under a floor, the digger's way out")
    def _():
        rock_block()
        r = place()
        assert r.ok and r.exit, (r.ok, r.error)
        ex, ey = r.exit.x, r.exit.y
        assert abs(ex - r.x) + abs(ey - r.y) == 1, (ex, ey, r.x, r.y)
        e = W.get(ex, ey, 70)
        assert e.shape == "WALL" and not e.designated, dict(e)
        assert W.get(ex, ey, 71).shape == "FLOOR"
        p = B.load_projects().list[1]
        assert (p.chamber_exit.x, p.chamber_exit.y, p.chamber_exit.z) == (ex, ey, 70)
        assert (p.chamber_box.x1, p.chamber_box.x2, p.chamber_box.z) == (r.x - 1, r.x + 1, 70)
        assert not any(c.x == ex and c.y == ey for c in (p.chamber[i] for i in range(1, len(p.chamber) + 1)))

    @test("bridge: winter cistern (item28): never within 6 tiles of a staircase")
    def _():
        rock_block()
        for z in (70, 71, 72):
            W.set(47, 52, z, LUA.table_from({"shape": "STAIR_UPDOWN"}))
        r = place(True)
        assert not r.ok and "a staircase within 6 tiles of the chamber" in r.error, r.error
        W.reset()
        rock_block()
        for z in (70, 71, 72):
            W.set(47, 49, z, LUA.table_from({"shape": "STAIR_UPDOWN"}))   # 8 tiles off the nearest chamber
        r = place(True)
        assert r.ok and r.y >= 57, (r.ok, r.error)

    @test("bridge: winter cistern (item28): the well and its pond zone wait while a dwarf is in the chamber")
    def _():
        rock_block()
        r = place()
        assert r.ok
        p = B.load_projects().list[1]
        assert B.filled_well_occupant(p) is None
        W.citizens = LUA.table_from({1: LUA.table_from({"x": r.x + 1, "y": r.y + 1, "z": 70})})
        who = B.filled_well_occupant(p)
        assert who and (who.x, who.y, who.z) == (r.x + 1, r.y + 1, 70), who
        W.citizens = LUA.table_from({1: LUA.table_from({"x": r.x + 1, "y": r.y + 1, "z": 71})})   # on the floor above
        assert B.filled_well_occupant(p) is None
        src = (ROOT / "lua" / "ai-builder-projects-finish.lua").read_text(encoding="utf-8")
        i = src.index("function furnish_project(")
        assert src.index("filled_well_occupant", i) < src.index("for _, mode in ipairs({'build', 'place', 'zone'})", i)

    @test("bridge: the well's frost reading carries the depth of its water (hazards well_water)")
    def _():
        src = (ROOT / "lua" / "ai-hazards.lua").read_text(encoding="utf-8")
        i = src.index("function well_water(")
        j = src.index("\nend\n", i) + 5
        fn = LUA.execute("local FROZEN = 'FROZEN_LIQUID'\n" + src[i:j] + "\nreturn well_water")
        tiles = {165: {"shape": "RAMP", "liquid": True, "depth": 4, "outside": False}}
        tf = lambda x, y, z: LUA.table_from(tiles[z]) if z in tiles else None
        water, outside, depth = fn(LUA.table_from({"x": 1, "y": 1, "z": 166}), tf)
        assert (water, outside, depth) == ("water", False, 4), (water, outside, depth)
else:
    @plain_test("the 6 Lua test(s) of the bridge block: not run")
    def _():
        skip("needs the lupa package (pip install lupa)")


finish()
