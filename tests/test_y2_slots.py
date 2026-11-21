"""(y2, fix57-2) Building slots and levels: the v57 verifier's W1, W3, W4, W5
(/home/claude/verify-v57.md; proofs in tests/test_v57_verify.py), and the
bridge's dry run of park_project.

W1  planner_slots._dig_check_rule gave up a landmark's lower level at 21 days
    (0 dug, its tiles "can't reach" until the level above is dug), undoing h8's
    336-day exemption. Levels dug in stages of their own are left to their own
    rules: wells, ways in, landmarks, a floor level digging its new hall first,
    a cavern shaft. An ordinary level is still judged.
W3  planner_slots._park_rule dropped at once any waiting piece not on a fixed
    list (archery targets, altars, nest boxes, levers, floodgates...). Now only
    UNOBTAINABLE_KINDS (empty) go at once, the rest after h3_park_drop_days,
    KEEP_KINDS (wells, lids, doors, gates, traps, levers, bridges...) never; the
    bridge keeps the same list, and takes off only the level's own pieces.
W4  slot_cap gave no slot back for the lone crossbows Bowyer's level once open.
W5  the stuck sweep closed a level the slot rules parked.

    python tests/test_y2_slots.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402

import digest  # noqa: E402
import planner_slots as SL  # noqa: E402
import planner_stuck as ST  # noqa: E402
from planner import Memory, PLANNER_CONFIG as CFG, abs_tick, TICKS_PER_DAY  # noqa: E402

LUA_DIR = ROOT / "lua"
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
BUILDER_HARNESS = re.search(r'HARNESS = r"""(.*?)"""', (ROOT / "tests" / "test_builder.py").read_text(encoding="utf-8"),
                            re.S).group(1)
UNREACHED = "x60 y80 z120: Dig, no worker (priority 4), beside ground the dwarves can't reach"


def builder():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(LUA_DIR)
    B, W = lua.execute(BUILDER_HARNESS, (LUA_DIR / "ai-layouts.lua").read_text(encoding="utf-8"),
                       (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8"))
    return lua, B, W


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"] = {"year": 259, "tick": 259313, "season": "autumn", "month": "Sandstone", "day": 21}
    s["orders"] = []
    return s


def dig_level(id_, kind, **kw):
    p = {"id": id_, "kind": kind, "phase": "dig", "started": {"year": 259, "tick": 100},
         "dig": {"digging": 1, "dug": 0, "marked": 0, "stuck": 0, "total": 180, "waiting": [UNREACHED]}}
    p.update(kw)
    return p


def dig_check(levels):
    s = fort()
    s["projects"] = {"open": levels}
    m = Memory()
    t0 = abs_tick(s) - (CFG["h3_dig_check_days"] + 2) * TICKS_PER_DAY
    m.dig_seen = {str(p["id"]): {"dug": 0, "tick": t0} for p in levels}
    props, notes = [], []
    SL._dig_check_rule(digest.normalize(s), m, CFG, props, notes)
    return sorted(p.action["project_id"] for p in props if p.action.get("type") == "cancel_project")


def furnish_level(id_, kind, waiting, days, **kw):
    sig = ",".join(sorted(f"{k}:{n}" for k, n in waiting.items()))
    p = {"id": id_, "kind": kind, "phase": "furnish", "started": {"year": 252, "tick": 51324},
         "furnish": {"placed": 3, "done": 1, "waiting": dict(waiting), "days": days, "sig": sig}}
    p.update(kw)
    return p


def park(level, days_waited=400):
    s = fort()
    s["projects"] = {"open": [level]}
    m = Memory()
    m.furnish_seen = {str(level["id"]): {"sig": level["furnish"]["sig"],
                                         "tick": abs_tick(s) - days_waited * TICKS_PER_DAY}}
    props, notes = [], []
    SL._park_rule(digest.normalize(s), m, CFG, props, notes)
    return [p.action for p in props], notes


# ---- W1 ----------------------------------------------------------------------------------------------

@test("W1 dig check: staged digs (landmark, well, way in, floor hall first, cavern shaft) left to their own "
      "rules; an ordinary level (and a floor level with no new hall) still given up unreached")
def _():
    levels = [dig_level(1, "landmark", params={"landmark_id": 3}),
              dig_level(2, "well"), dig_level(3, "way_in"),
              dig_level(4, "bedrooms", floor={"id": 2, "hall": 14}),
              dig_level(5, "storage", floor={"id": 2}),                    # a hall of unknown size: kept
              dig_level(6, "tombs"),
              dig_level(7, "bedrooms", floor={"id": 2, "hall": 0}),        # no new hall: judged as any level
              dig_level(8, "storage")]
    levels[5]["dig"]["shaft_open"] = False                              # (its own shaft rules)
    assert dig_check(levels) == [7, 8], dig_check(levels)
    assert {"well", "way_in", "landmark"} <= SL.STAGED_DIG_KINDS


@test("W1 lua: the projects report gives a floor level's floor and its new hall tiles (the dig check reads them)")
def _():
    lua, B, W = builder()
    data = B.load_projects()
    data.list[1] = lua.eval("{id = 40, kind = 'bedrooms', phase = 'dig', z = 70, stair = {x = 5, y = 5}, "
                            "area = {x1 = 0, y1 = 0, x2 = 9, y2 = 9, z = 70}, cells = {}, "
                            "floor = {id = 3, slots = 4, hall = 12}}")
    data.list[2] = lua.eval("{id = 41, kind = 'storage', phase = 'dig', z = 71, stair = {x = 5, y = 5}, "
                            "area = {x1 = 0, y1 = 0, x2 = 9, y2 = 9, z = 71}, cells = {}}")
    data.next_id = 42
    B.save_projects(data)
    B.dig_progress = lua.eval("function() return {total = 10, dug = 0, stuck = 0, marked = 0, digging = 0} end")
    rep = B.projects_report()
    rows = {int(r.id): r for r in rep.open.values()}
    assert rows[40].floor.id == 3 and rows[40].floor.hall == 12, dict(rows[40])
    assert rows[41].floor is None


# ---- W3 ----------------------------------------------------------------------------------------------

@test("W3 park rule: archery targets, altars, nest boxes, hives wait h3_park_drop_days, then are taken off")
def _():
    for kind, piece in (("archery", "ArcheryTarget"), ("temple", "OfferingPlace"), ("farms", "NestBox"),
                        ("farms", "Hive"), ("tavern", "Instrument")):
        lvl = furnish_level(31, kind, {piece: 2}, 400, parked=True, parked_days=1)
        acts, notes = park(lvl)
        assert not acts and any("waits apart" in n for n in notes), (piece, acts, notes)
        lvl["parked_days"] = CFG["h3_park_drop_days"]
        acts, _ = park(lvl)
        assert acts == [{"type": "finish_project", "project_id": 31, "give_up": True, "drop": [piece]}], (piece, acts)


@test("W3 park rule: a well, a lid, a lever (Trap), floodgate, door, bridge, grate, bars, support never taken "
      "off, alone or beside a bed")
def _():
    for piece in ("Well", "Hatch", "Trap", "Lever", "Floodgate", "Door", "Bridge", "GrateWall", "GrateFloor",
                  "BarsVertical", "BarsFloor", "Support", "Weapon"):
        assert piece in SL.KEEP_KINDS, piece
        for waiting in ({piece: 1}, {piece: 1, "Bed": 1}):
            lvl = furnish_level(32, "bedrooms", waiting, 900, parked=True, parked_days=CFG["h3_park_drop_days"] + 50)
            acts, notes = park(lvl, 900)
            assert not acts, (waiting, acts)
            assert any("never taken off" in n for n in notes), notes


@test("W3 park rule: a kind put on UNOBTAINABLE_KINDS goes at once (never a KEEP_KINDS one)")
def _():
    old = SL.UNOBTAINABLE_KINDS
    try:
        SL.UNOBTAINABLE_KINDS = frozenset({"DisplayFurniture", "Door"})
        acts, _ = park(furnish_level(33, "museum", {"DisplayFurniture": 1}, 40, parked=True, parked_days=1), 40)
        assert acts == [{"type": "finish_project", "project_id": 33, "give_up": True, "drop": ["DisplayFurniture"]}]
        acts, _ = park(furnish_level(33, "museum", {"Door": 1}, 40, parked=True, parked_days=1), 40)
        assert not acts
    finally:
        SL.UNOBTAINABLE_KINDS = old
    assert not SL.UNOBTAINABLE_KINDS            # (kept empty: nothing known unobtainable)


@test("W3 lua: finish_project never takes off a KEEP_KINDS piece, whatever the brain names (refused while it waits)")
def _():
    lua, B, W = builder()
    B.df = lua.eval("{building_type = {Bed = 2, Trap = 24, Floodgate = 10, Door = 9, Workshop = 14, Furnace = 6, "
                    "Well = 19, Hatch = 36}}")
    data = B.load_projects()
    data.list[1] = lua.eval("{id = 66, kind = 'bedrooms', phase = 'furnish', z = 70, "
                            "area = {x1 = 0, y1 = 0, x2 = 9, y2 = 9, z = 70}, cells = {}}")
    data.next_id = 67
    B.save_projects(data)
    B.furnish_progress = lua.eval("function() return {placed = 4, done = 2, waiting = {Bed = 1, Trap = 1}} end")
    calls = lua.eval("{}")
    B.drop_waiting_shops = lua.eval("function(calls) return function(p, kinds) "
                                    "table.insert(calls, kinds); return 1 end end")(calls)
    got = B.finish_project(66, False, False, True, lua.table_from(["Bed", "Trap"]))
    assert not got.ok and "other than those named" in str(got.error), dict(got)
    assert not calls[1]                                      # nothing taken off
    # with leave_planned too (the stuck sweep's): the bed goes, the lever stays planned
    got = B.finish_project(66, False, False, True, lua.table_from(["Bed", "Trap"]), True)
    assert got.ok, dict(got)
    assert calls[1].Bed and not calls[1].Trap
    for k in ("Well", "Hatch", "Trap", "Lever", "Floodgate", "Door", "Bridge", "GrateWall", "GrateFloor",
              "BarsVertical", "BarsFloor", "Support"):
        assert B.KEEP_KINDS[k], k
    assert set(SL.KEEP_KINDS) == {k for k in B.KEEP_KINDS.keys()}, "the brain and the bridge keep one list"


@test("W3 lua: drop_waiting_shops takes off only the level's own planned pieces (its build cells), "
      "never another module's lever or floodgate in its area, nor any KEEP_KINDS piece")
def _():
    lua, B, W = builder()
    gone = lua.eval("{}")
    lua.execute("""local B, gone = ...
      B.df = {building_type = {Bed = 2, Trap = 24, Floodgate = 10, ArcheryTarget = 27,
                               [2] = 'Bed', [24] = 'Trap', [10] = 'Floodgate', [27] = 'ArcheryTarget'},
              global = {world = {buildings = {all = {}}}}}
      local function b(id, t, x1, y1, x2, y2)
        return {id = id, z = 70, x1 = x1, y1 = y1, x2 = x2, y2 = y2, flags = {exists = false},
                getType = function() return t end}
      end
      B.df.global.world.buildings.all = {
        b(1, 2, 12, 12, 12, 12),      -- its own bed (build cell 2,2 from the anchor 10,10)
        b(2, 2, 15, 15, 15, 15),      -- a bed some other module planned in its area
        b(3, 24, 13, 12, 13, 12),     -- its own cell, but a lever: kept
        b(4, 10, 16, 12, 16, 12),     -- another module's floodgate
        b(5, 27, 13, 14, 15, 16)}     -- its own archery target (cell 4,5 under its 3x3)
      B.is_planned = function() return true end
      B.dfhack.buildings = B.dfhack.buildings or {}
      B.dfhack.buildings.deconstruct = function(x) table.insert(gone, x.id) end
    """, B, gone)
    p = lua.eval("{id = 9, kind = 'archery', phase = 'furnish', z = 70, anchor = {x = 10, y = 10}, "
                 "area = {x1 = 10, y1 = 10, x2 = 19, y2 = 19, z = 70}, "
                 "cells = {build = {{x = 2, y = 2, text = 'b'}, {x = 3, y = 2, text = 'Tl'}, "
                 "{x = 4, y = 5, text = 'archery'}}}}")
    kinds = lua.eval("{Bed = true, Trap = true, Floodgate = true, ArcheryTarget = true}")
    n = B.drop_waiting_shops(p, kinds)
    assert sorted(int(x) for x in gone.values()) == [1, 5] and n == 2, list(gone.values())
    # an older record with no build cells: its area, as before (but never a KEEP_KINDS piece)
    for k in list(gone.keys()):
        gone[k] = None
    p.cells = lua.eval("{}")
    B.drop_waiting_shops(p, kinds)
    assert sorted(int(x) for x in gone.values()) == [1, 2, 5], list(gone.values())


# ---- W4 ----------------------------------------------------------------------------------------------

@test("W4 slot_cap: one slot back for the open crossbows Bowyer's level (one only; a parked one counted once)")
def _():
    lua, B, W = builder()
    base = int(B.MAX_OPEN_PROJECTS)
    mk = lua.eval("function(spec) local t = {} for i, s in ipairs(spec) do "
                  "t[i] = {id = i, kind = s, phase = 'dig'} "
                  "if s == 'workshops' then t[i].params = {shops = {'Bowyers'}, crossbows = true} end end return t end")
    assert B.slot_cap(mk(lua.table_from(["bedrooms"]))) == base
    assert B.slot_cap(mk(lua.table_from(["bedrooms", "workshops"]))) == base + 1
    two = mk(lua.table_from(["workshops", "workshops"]))
    assert B.slot_cap(two) == base + 1                    # at most one (start_project lets one through)
    one = mk(lua.table_from(["workshops"]))
    one[1].params = None
    one[1].crossbows = True                               # the record's own mark (start_project saves it)
    assert B.slot_cap(one) == base + 1
    plain = mk(lua.table_from(["workshops"]))
    plain[1].params.crossbows = None
    assert B.slot_cap(plain) == base                      # an ordinary workshops level holds its slot


# ---- W5 ----------------------------------------------------------------------------------------------

def sweep(parked):
    s = fort()
    now = abs_tick(s)
    lvl = furnish_level(66, "bedrooms", {"Bed": 1, "Box": 1}, 120, parked=parked, parked_days=90)
    s["projects"] = {"open": [lvl]}
    t0 = now - 120 * TICKS_PER_DAY
    s["stuck"] = {"list": [{"kind": "project", "id": 66, "what": "bedrooms", "state": "furnish",
                            "progress": "1/3", "since": t0, "moved": t0}]}
    m = Memory()
    m.stuck_seen = {"items": {}, "families": {}}
    props, notes = [], []
    ST._stuck_rule(digest.normalize(s), m, CFG, props, notes)
    return [p.action for p in props if p.action.get("project_id") == 66]


@test("W5 stuck sweep: a parked level is the slot rules'; one no longer parked (a piece came) is swept as before")
def _():
    assert sweep(True) == []
    shut = sweep(False)
    assert shut and shut[0]["type"] == "finish_project" and shut[0].get("leave_planned"), shut


# ---- park_project's dry run ----------------------------------------------------------------------

@test("park_project: in DRY_OK, and its dry run saves nothing")
def _():
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    dry = src[src.index("DRY_OK = {}"):src.index("}) do DRY_OK[name] = true end")]
    assert "'park_project'" in dry
    lua, B, W = builder()
    data = B.load_projects()
    data.list[1] = lua.eval("{id = 66, kind = 'bedrooms', phase = 'furnish', z = 70, "
                            "area = {x1 = 0, y1 = 0, x2 = 9, y2 = 9, z = 70}, cells = {}}")
    data.next_id = 67
    B.save_projects(data)
    B.furnish_progress = lua.eval("function() return {placed = 3, done = 1, waiting = {Bed = 1, Box = 1}} end")
    saved = lua.eval("{n = 0}")
    real_save = B.save_projects
    B.save_projects = lua.eval("function(saved, f) return function(d) saved.n = saved.n + 1; return f(d) end end")(
        saved, real_save)
    r = B.park_project(66, "Bed:1,Box:1", True)
    assert r.ok and r.dry_run and r.parked, dict(r)
    assert saved.n == 0
    rec = [p for p in B.load_projects().list.values() if p.id == 66][0]
    assert rec.parked is None
    r = B.park_project(66, "Bed:1,Box:1", False)
    assert r.ok and saved.n == 1


if __name__ == "__main__":
    finish()
