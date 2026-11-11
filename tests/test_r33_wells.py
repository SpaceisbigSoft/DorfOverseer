"""(0.105.33, group wells) Wells, cisterns, farms and rooms (audit slices L5
and B4): the cavern-shaft watcher after a reload, given-up cavern wells'
open shafts kept shut, a refused well tried again (off its spot), a shut
shaft is no well, the drink swap of the AI's own plots, farm tiles counted
once, the cistern's shut calling off a queued pull, its lever spot found at
plan time, its plug never dug with the gate open, room walls that would cut
a way left out, and the farms' small fixes.

    python tests/test_r33_wells.py
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
from harness import make_test, test as plain_test, finish  # noqa: E402
from planner import PLANNER_CONFIG, TICKS_PER_DAY, Memory, abs_tick, plan  # noqa: E402
import planner_wells  # noqa: E402
import planner_farms  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def _const(path: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / path).read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name)


# ---- the brain ---------------------------------------------------------------------------

REFUSED = ("the game would not place the well over the hole at x10 y10 z100 (3 tries; tiles: "
           "z100 OpenSpace; beside: StoneFloor1)")


def no_well_fort() -> dict:
    s = fort()
    s["buildings"]["other"].pop("Well", None)
    s["projects"]["open"] = []
    s["dwarves"]["needs_medical_care"] = 3
    s["society"]["parched"] = 4
    return s


@plain_test("B4 wells 1: a refused well holds new holes for well_retry_days, then a well is tried again")
def _():
    s = no_well_fort()
    m = Memory()
    m.well_floor_retried = True
    m.well_failure = REFUSED
    m.last_fired["well"] = abs_tick(s) - 3 * TICKS_PER_DAY            # tried 3 days ago
    props, notes = plan(s, m)
    assert not [p for p in props if p.rule == "well"], [p.action for p in props if p.rule == "well"]
    assert any(n.startswith("injured dwarves need water and no well could be placed") or
               "no well could be placed" in n for n in notes), notes
    m.last_fired["well"] = abs_tick(s) - (PLANNER_CONFIG["well_retry_days"] + 1) * TICKS_PER_DAY
    props, notes = plan(s, m)
    wells = [p for p in props if p.rule == "well"]
    assert wells and wells[0].action["type"] == "place_well", [p.action for p in wells]
    assert any("tried again after" in n for n in notes), notes


@plain_test("B4 wells 2: a cavern well whose shaft gate is shut is no well: water zone, and the count")
def _():
    s = fort()
    s["buildings"]["other"]["Well"] = 1
    s["buildings"]["zones"].pop("WaterSource", None)
    s["projects"]["open"] = []
    s["projects"]["well_lids"] = [{"project_id": 4, "x": 5, "y": 5, "z": 50, "gate": "closed", "state": "none"}]
    s["dwarves"]["needs_medical_care"] = 6
    s["society"]["parched"] = 3
    s["water"] = {"bodies": [{"kind": "surface", "tiles": 40, "nearest": {"x": 9, "y": 9, "z": 120, "d": 20}}]}
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    assert planner_wells.usable_wells(s) == 0 and planner_wells.shut_wells(s) == 1
    p, n = [], []
    planner_wells._water_zone_rule(s, p, n)
    assert [x.action["type"] for x in p] == ["water_zone"] and "shaft is open" in p[0].reason, p
    # open again: a well
    s["projects"]["well_lids"][0]["gate"] = "open"
    p, n = [], []
    planner_wells._water_zone_rule(s, p, n)
    assert not p, p
    # a well still being dug, and a given-up shaft, are not built wells: not taken off
    s["projects"]["well_lids"] = [{"project_id": 4, "gate": "closed"}, {"project_id": 9, "gate": "closed", "cancelled": True}]
    s["projects"]["open"] = [{"id": 4, "kind": "well", "phase": "dig"}]
    assert planner_wells.shut_wells(s) == 0 and planner_wells.usable_wells(s) == 1
    # (Low) the plan's cfg is read: a far limit of 5 tiles leaves the water at 20 out
    s["projects"]["well_lids"] = [{"project_id": 4, "gate": "closed"}]
    s["projects"]["open"] = []
    cfg = dict(PLANNER_CONFIG, water_zone_max_d=5)
    p, n = [], []
    planner_wells._water_zone_rule(s, p, n, cfg)
    assert not p and any("no open water near the fort" in x for x in n), (p, n)


@plain_test("B4 wells 3: _well_rule counts only open wells toward dwarves_per_well")
def _():
    s = fort()
    s["buildings"]["other"]["Well"] = 1
    s["projects"]["open"] = []
    s["dwarves"]["total"] = 10
    s["projects"]["well_lids"] = [{"project_id": 4, "gate": "closed"}]
    m = Memory()
    m.well_floor_retried = True
    m.cavern_shaft_stairs = True
    p, n = [], []
    planner_wells._well_rule(s, m, {}, PLANNER_CONFIG, p, n)
    assert [x.action["type"] for x in p] == ["place_well"] and not p[0].action.get("extra"), [x.action for x in p]
    s["projects"]["well_lids"][0]["gate"] = "open"
    p, n = [], []
    planner_wells._well_rule(s, m, {}, PLANNER_CONFIG, p, n)
    assert not p, [x.action for x in p]


@plain_test("L5 wells 4: a given-up well's open shaft is shut, never opened again")
def _():
    s = fort()
    s["projects"]["open"] = []
    s["projects"]["well_lids"] = [{"project_id": 9, "x": 5, "y": 5, "z": 50, "elevation": 1, "gate": "open",
                                   "state": "none", "cancelled": True, "watching": True}]
    p, n = [], []
    planner_wells._well_lid_rule(s, p, n)
    shaft = [x for x in p if x.action.get("type") == "well_shaft"]
    assert shaft and "given-up" in shaft[0].reason, [(x.action, x.reason) for x in p]
    s["projects"]["well_lids"][0]["gate"] = "closed"
    p, n = [], []
    planner_wells._well_lid_rule(s, p, n)
    assert not [x for x in p if x.action.get("type") == "well_shaft"], [(x.action, x.reason) for x in p]


def crop_fort(ai_now=True) -> dict:
    s = fort()
    s["stocks"]["drink"] = 0
    s["supplies"]["brewable_plants"] = 0
    s["supplies"]["brewable_growths"] = 0
    s["farms"] = {"plots": 2, "built": 2, "tiles": 18, "plots_underground": 2, "plots_surface": 0, "season": "spring",
                  "crops": {"MUSHROOM_HELMET_PLUMP": {"name": "plump helmet", "seeds": 40, "brews": "dwarven wine",
                                                      "underground": True, "planted": 0,
                                                      "seasons": ["spring", "summer", "autumn", "winter"]},
                            "GRASS_TAIL_PIG": {"name": "pig tail", "seeds": 40, "brews": None, "thread": True,
                                               "underground": True, "planted": 18,
                                               "seasons": ["spring", "summer", "autumn", "winter"]}},
                  "plot_list": [{"id": i, "tiles": 9, "underground": True, "options": 2, "fallow": False,
                                 "ok_now": True, "ai_now": ai_now, "crops": ["GRASS_TAIL_PIG"] * 4}
                                for i in (1, 2)]}
    return s


@plain_test("B4 farms 1: drink short and the AI's plots all sow a crop no still brews: the drink swap asked")
def _():
    m = Memory()
    m.farm_steer = "crops"
    p, n = [], []
    planner_farms._farm_crops_rule(crop_fort(), m, PLANNER_CONFIG, p, n)
    assert [x.action for x in p] == [{"type": "set_farm_crops", "drink": True}], [x.action for x in p]
    # the player's crops (not the AI's): the bridge keeps them, so not asked
    p, n = [], []
    planner_farms._farm_crops_rule(crop_fort(ai_now=False), m, PLANNER_CONFIG, p, n)
    assert not p, [x.action for x in p]
    # drink not short: nothing
    s = crop_fort()
    s["stocks"]["drink"] = 10000
    p, n = [], []
    planner_farms._farm_crops_rule(s, m, PLANNER_CONFIG, p, n)
    assert not p, [x.action for x in p]
    # an older report (no crops per plot): read from what is sown
    s = crop_fort()
    for q in s["farms"]["plot_list"]:
        q.pop("crops")
        q.pop("ai_now")
    assert planner_farms.drink_swap_wanted(s, planner_farms.farm_plots_live(s))
    s["farms"]["crops"]["MUSHROOM_HELMET_PLUMP"]["seeds"] = 0
    assert not planner_farms.drink_swap_wanted(s, planner_farms.farm_plots_live(s))


@plain_test("B4 farms 2: underground plots just laid out are counted once, and no negative surface count")
def _():
    s = fort()
    s["stocks"]["drink"] = 0
    s["farms"] = {"plots": 3, "built": 3, "tiles": 20, "plots_underground": 2, "plots_surface": 1, "season": "spring",
                  "crops": {"MUSHROOM_HELMET_PLUMP": {"seeds": 200, "brews": "w", "underground": True,
                                                      "seasons": ["spring"]}},
                  "plot_list": [{"id": 1, "tiles": 10, "underground": True, "options": 1},
                                {"id": 2, "tiles": 20, "underground": True, "options": 1}]}
    m = Memory()
    m.farm_under_asked = {"tick": abs_tick(s) - TICKS_PER_DAY, "tiles": 20}      # plot 2: already listed
    p, n = [], []
    planner_farms._farm_rule(s, m, {}, 30, PLANNER_CONFIG, p, n)
    farms = [x for x in p if x.rule == "farms"]
    assert farms, [x.rule for x in p]
    r = farms[0].reason
    assert r.startswith("30 farm tiles"), r                  # 10 + 20, not 10 + 20 + 20
    assert "+-" not in r, r


# ---- the bridge --------------------------------------------------------------------------

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
    GAME_FAKE = _const("test_builder.py", "GAME_FAKE")
    GAME_CLEAN = _const("test_builder.py", "GAME_CLEAN")


def _reset():
    if LuaRuntime is None:
        return
    W.reset()
    B.SHAFT_WATCH = LUA.table_from({"on": False})
    LUA.execute("df.global = df.global or {cur_year = 148, cur_year_tick = 100}")


test = make_test(before=_reset)


def cancelled_well(**extra):
    """A cavern well given up over its shaft (z 64, 63 under the floor at 70),
    the stair column beside it at (71, 58)."""
    W.set(70, 58, 70, LUA.table_from({"shape": "EMPTY"}))
    for z in (64, 63):
        W.set(70, 58, z, LUA.table_from({"shape": "EMPTY"}))
    p = {"id": 9, "kind": "well", "phase": "cancelled", "z": 70, "anchor": LUA.table_from({"x": 70, "y": 58}),
         "stair": LUA.table_from({"x": 70, "y": 58}), "shaft": LUA.table_from([64, 63]),
         "shaft_stairs": LUA.table_from([LUA.table_from({"x": 71, "y": 58, "z": 70, "key": "j"}),
                                         LUA.table_from({"x": 71, "y": 58, "z": 64, "key": "i"}),
                                         LUA.table_from({"x": 71, "y": 58, "z": 63, "key": "u"})]),
         "area": LUA.table_from({"x1": 69, "y1": 57, "x2": 71, "y2": 59, "z": 70}),
         "cells": LUA.table_from({"dig": LUA.table_from([LUA.table_from({"x": 0, "y": 0, "text": "h"})])})}
    p.update(extra)
    data = B.load_projects()
    data.list[len(data.list) + 1] = LUA.table_from(p)
    B.save_projects(data)
    return data


if LuaRuntime is not None:
    @test("L5 wells 5: the shaft watcher with a dead timer (the world unloaded) starts again; unload resets it")
    def _():
        LUA.execute("""
          ACTIVE = {}
          dfhack.timeout = function(n, unit, f) local id = #ACTIVE + 1; ACTIVE[id] = true; return id end
          dfhack.timeout_active = function(id) return ACTIVE[id] == true end
          dfhack.onStateChange = {}
          SC_MAP_UNLOADED = 6
        """)
        try:
            # the part loaded again with onStateChange in reach (DFHack's)
            LUA.eval("function(B) assert(loadfile(LUA_DIR .. '/ai-builder-wells.lua', 't', B))() end")(B)
            assert B.shaft_watch_start() is True
            assert B.shaft_watch_start() is False                            # alive: not twice
            LUA.execute("for k in pairs(ACTIVE) do ACTIVE[k] = nil end")     # the world unloaded: timers gone
            assert B.shaft_watch_start() is True                             # started again, not "already on"
            LUA.eval("function() dfhack.onStateChange['ai-builder-wells-watch'](SC_MAP_UNLOADED) end")()
            assert B.SHAFT_WATCH.on is False and B.SHAFT_WATCH.timer is None
        finally:
            LUA.execute("dfhack.timeout = nil; dfhack.timeout_active = nil; dfhack.onStateChange = nil")

    @test("L5 wells 6: a given-up cavern well with its shaft open keeps its gate (always shut) and lid; held or closed ones don't")
    def _():
        LUA.execute(GAME_FAKE)
        try:
            data = cancelled_well()
            assert B.shaft_left_open(data.list[1])
            lids = B.well_lids(False)
            assert len(lids) == 1 and lids[1].cancelled is True and lids[1].project_id == 9, len(lids)
            # the shaft's last level never dug (held): not open to the cavern
            W.reset()
            cancelled_well(held=LUA.table_from({"z": 63}))
            assert len(B.well_lids(False)) == 0
            W.reset()
            cancelled_well()
            W.set(70, 58, 63, LUA.table_from({"shape": "WALL"}))
            assert len(B.well_lids(False)) == 0
            # the gate: linked and open, asked to open: shut instead (no well draws through it)
            W.reset()
            data = cancelled_well(shaft_gate=LUA.table_from({"lever": LUA.table_from({"x": 72, "y": 60, "z": 70})}))
            mk = LUA.eval("MKS")
            lv = mk(72, 60, 70, 8, True, 3)
            h = mk(70, 58, 63, 7, True)
            h.door_flags.closed = False
            LUA.eval("function(h, lv) LINKS[h.id] = {lv.id} end")(h, lv)
            assert B.well_lids(False)[1].gate == "open"
            s = B.well_shaft_step(False, False)
            assert s.ok and s.wells[1].stage == "closed" and s.wells[1].cancelled and h.door_flags.closed is True, \
                dict(s.wells[1])
            s = B.well_shaft_step(False, False)
            assert s.wells[1].stage == "closed" and h.door_flags.closed is True
        finally:
            LUA.execute(GAME_CLEAN)

    @test("L5/B4 wells 7: a refused well's spot is kept off; undo_well_cells takes back the shaft, stairs and gallery")
    def _():
        data = cancelled_well(refused=True, cancelled_year=148)
        spots = B.well_spots_unreached(data)
        assert len(spots) == 1 and spots[1].x1 == 69, len(spots)
        p = data.list[1]
        p.gallery = LUA.table_from([LUA.table_from({"x": 72, "y": 58})])
        for z in (64, 63):
            W.set(70, 58, z, LUA.table_from({"shape": "WALL"}))
        before = len(W.calls)
        B.undo_well_cells(p)
        undo = [W.calls[i] for i in range(before + 1, len(W.calls) + 1)]
        assert len(undo) == 6 and all(c.command == "undo" for c in undo), [dict(c) for c in undo]

    @test("L5 cistern 1: the instant shut calls off a pull queued for a dwarf (shut or open gate)")
    def _():
        LUA.execute(GAME_FAKE)
        try:
            LUA.execute("""
              df.building_type[9] = 'Floodgate'; df.building_type.Floodgate = 9
              function MKGATE(x, y, z, closed)
                local b = MKS(x, y, z, 9, true)
                b.gate_flags = {closed = closed}
                return b
              end
            """)
            gate = LUA.eval("MKGATE")(80, 50, 60, True)
            lever = LUA.eval("MKS")(82, 50, 70, 8, True, 3)
            lever.jobs[1] = LUA.table_from({"job_type": 1})                  # a refill pull queued
            LUA.eval("""function(B, lever) B.cistern_data = function()
                return {lever_id = lever.id, plan = {floodgate = {x = 80, y = 50}, intake_z = 60, cistern = {z = 60}}}
              end end""")(B, lever)
            r = B.cistern_shut(False)
            assert r.ok and r.shut and r.cancelled_pulls == 1 and len(LUA.eval("REMOVED")) == 1, dict(r)
            lever.jobs[1] = None
            r = B.cistern_shut(False)
            assert not r.ok and r.rejected and "already shut" in r.error
            # open, a pull queued: called off, then shut at once
            gate.gate_flags.closed = False
            lever.jobs[1] = LUA.table_from({"job_type": 1})
            r = B.cistern_shut(False)
            assert r.ok and r.instant and len(LUA.eval("REMOVED")) == 2, dict(r)
        finally:
            LUA.execute(GAME_CLEAN)

    @test("L5 cistern 2: the lever spot: 2 tiles from the well, else 3; none: nil")
    def _():
        for x in range(64, 77):
            for y in range(52, 65):
                W.set(x, y, 70, LUA.table_from({"shape": "WALL"}))
        assert B.cistern_lever_spot(70, 58, 70) is None
        W.set(73, 58, 70, LUA.table_from({"shape": "FLOOR"}))
        s = B.cistern_lever_spot(70, 58, 70)
        assert (s.x, s.y, s.z) == (73, 58, 70)
        W.set(72, 56, 70, LUA.table_from({"shape": "FLOOR"}))
        s = B.cistern_lever_spot(70, 58, 70)
        assert (s.x, s.y) == (72, 56)                                        # 2 tiles off first

    @test("L5 rooms 1: a gap a corridor runs through is not walled; one beside open floor is")
    def _():
        # a 3x3 bedroom at x 70-72, y 57-59, z 70, door at (71, 56); everything round walled,
        # except a corridor that runs west to east through the gap at (73, 58) to a dead end at x 76
        LUA.execute("""local B, W = ...
          for x = 66, 78 do for y = 54, 62 do W.set(x, y, 70, {shape = 'WALL'}) end end
          for x = 70, 72 do for y = 57, 59 do W.set(x, y, 70, {shape = 'FLOOR'}) end end
          for x = 67, 75 do W.set(x, 55, 70, {shape = 'FLOOR'}) end         -- the corridor to the door
          W.set(71, 56, 70, {shape = 'FLOOR', building = true})             -- the door
          for x = 73, 76 do W.set(x, 58, 70, {shape = 'FLOOR'}) end         -- the gap and a dead end beyond
          B.room_zones = function() return {{id = 1, x1 = 70, y1 = 57, x2 = 72, y2 = 59, z = 70}} end
          B.building_kind_at = function(x, y, z)
            if x == 71 and y == 56 then return 'Door' end
            if x == 72 and y == 59 then return 'Bed' end
          end
          B.units_on_tiles = function() return 0 end
        """, B, W)
        gaps, rooms, total = B.room_gaps(40)
        assert total == 0, [(g.x, g.y) for g in gaps.values()]            # walling it shuts the dead end off
        # the dead end joined to the corridor: the wall cuts nothing
        LUA.execute("""local B, W = ...
          for y = 55, 58 do W.set(76, y, 70, {shape = 'FLOOR'}) end""", B, W)
        gaps, rooms, total = B.room_gaps(40)
        assert total == 1 and (gaps[1].x, gaps[1].y) == (73, 58), total
        # a creature on the gap: not now
        LUA.execute("""local B = ...
          B.units_on_tiles = function(t, z) return (t[1].x == 73 and t[1].y == 58) and 1 or 0 end""", B)
        assert B.room_gaps(40)[2] == 0

    @test("L5 farms 1: set_farm_crops drops the entries of plots gone; a throw in pass 2 leaves no outside pass on")
    def _():
        LUA.execute("""local B, W = ...
          B.site_put = function(k, v) W.persist[k] = v end
          W.persist[B.FARM_CROPS_KEY] = {set = {['5'] = {1}, ['999'] = {2}}, drink_held = {['999'] = {1}}}
          B.farm_plot_buildings = function()
            return {{id = 5, x1 = 70, y1 = 58, x2 = 70, y2 = 58, centerx = 70, centery = 58, z = 70,
                     plant_id = {[0] = -1, -1, -1, -1}}}
          end
          B.seed_stock = function() return {[1] = 10} end
          df.plant_raw = {find = function(idx) if idx == 1 then return {id = 'MUSHROOM_HELMET_PLUMP'} end end}
          B.crop_in_season = function() return true end
          B.crop_grows_on = function() return true end
          B.plant_brews = function() return nil end
          B.plant_thread = function() return nil end
          B.plot_place = function() return {under = true} end
        """, B, W)
        r = B.set_farm_crops(LUA.table(), False)
        assert r.ok and r.changed == 4, (r.ok, r.error)
        data = LUA.eval("function(B, W) return W.persist[B.FARM_CROPS_KEY] end")(B, W)
        assert data.set["999"] is None and data.drink_held["999"] is None and data.set["5"] is not None
        LUA.execute("""local B = ...
          CALLED = false
          B.elevation_offset = function() return 0 end
          B.find_farm_spots = function() CALLED = true; B.PASS_OUTSIDE = true; error('boom') end""", B)
        ok = LUA.eval("function(B) return pcall(B.farm_plots, {tiles = 4}, nil, false) end")(B)
        assert LUA.eval("CALLED")
        assert not B.PASS_OUTSIDE


finish(None if LuaRuntime is not None else "these tests need the lupa package (pip install lupa)")
