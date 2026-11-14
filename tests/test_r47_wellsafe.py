"""(0.105.47) Cavern wells made safe (R2, I7d "Cavern wells": 11 dwarves
dead in the run): one cavern well at a time, a cooldown after one is given
up and a cap per site; the shaft dug from the bottom up (no ramp to stand on
in its column), the column restricted, its dig held while a citizen stands
in it, the watcher's log; a door at the gallery's fort end recorded for the
seal; the stair lid and the shaft gate never locked or shut on a dwarf below
(the gate never opened under one on its hatch); the rescue of a dwarf
stranded in the cavern under a well.

    python tests/test_r47_wellsafe.py
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
import planner_wellsafe  # noqa: E402
import planner_gates  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def _const(path: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / path).read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name)


# ---- the brain ---------------------------------------------------------------------------

@plain_test("1 brain: no cavern well while one is being dug, nor within the cooldown of one given up")
def _():
    s = fort()
    assert planner_wellsafe.cavern_well_wait(s, CFG) == ""
    s["well_safety"] = {"book": {"active": [12], "gone": 0}}
    w = planner_wellsafe.cavern_well_wait(s, CFG)
    assert "already being dug" in w and "12" in w, w
    s["well_safety"] = {"book": {"active": [], "gone": 1, "last_gone": abs_tick(s) - 10 * TICKS_PER_DAY}}
    w = planner_wellsafe.cavern_well_wait(s, CFG)
    assert "given up 10 day(s) ago" in w and "74 more day(s)" in w, w
    # the brain's own number
    assert "34 more" in planner_wellsafe.cavern_well_wait(s, dict(CFG, cavern_well_cooldown_days=44))
    s["well_safety"]["book"]["last_gone"] = abs_tick(s) - 90 * TICKS_PER_DAY
    assert planner_wellsafe.cavern_well_wait(s, CFG) == ""
    # cavern_well_safe says it (both of _well_rule's cavern proposals ask it)
    s["well_safety"] = {"book": {"active": [3]}}
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s["deep"] = {"dangers": []}
    s["dwarves"]["total"] = 60
    got = planner_wells.cavern_well_safe(s, CFG, urgent=True)
    assert isinstance(got, str) and "one at a time" in got, got
    # the action carries the cooldown and the site cap only when set otherwise
    a = planner_wells.cavern_action(fort(), CFG, False)
    assert "cooldown_days" not in a and "site_tries" not in a, a
    a = planner_wells.cavern_action(fort(), dict(CFG, cavern_well_cooldown_days=30, cavern_well_site_tries=1), False)
    assert a["cooldown_days"] == 30 and a["site_tries"] == 1, a


@plain_test("1 brain: plan() proposes no cavern well while the book says one was given up lately (E: 13 in 6 hours)")
def _():
    s = fort()
    s["buildings"]["other"].pop("Well", None)
    s["projects"]["open"] = []
    s["dwarves"]["needs_medical_care"] = 2
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s["deep"] = {"dangers": []}
    m = Memory()
    m.well_floor_retried = True
    m.cavern_shaft_stairs = True
    m.well_failure = "no open drop from a free floor inside the fort to clean water (the water below is in a cavern)"
    props, _ = plan(s, m)
    cav = [p for p in props if p.rule == "well" and p.action.get("cavern")]
    assert cav, "without the book a cavern well is proposed (the old path)"
    s["well_safety"] = {"book": {"active": [], "gone": 1, "last_gone": abs_tick(s) - 2 * TICKS_PER_DAY}}
    props, notes = plan(s, m)
    assert not [p for p in props if p.rule == "well" and p.action.get("cavern")], [p.action for p in props if p.rule == "well"]
    assert any("given up 2 day(s) ago" in n for n in notes), [n for n in notes if "cavern" in n]


def ws_state(**row):
    s = fort()
    w = {"project_id": 7, "phase": "dig", "x": 70, "y": 58, "z": 70, "hz": 63}
    w.update(row)
    s["well_safety"] = {"watching": True, "wells": [w], "todo": [], "log": [], "book": {"active": [7]}}
    return s


@plain_test("2/3 brain: the well_safety step when the bridge lists something to do; the watcher's new log lines said once")
def _():
    s = ws_state()
    p, n = [], []
    planner_wellsafe._well_safety_rule(s, CFG, p, n, Memory())
    assert not p, [x.action for x in p]
    s["well_safety"]["todo"] = ["door", "watch"]
    p, n = [], []
    planner_wellsafe._well_safety_rule(s, CFG, p, n, Memory())
    assert [x.action for x in p] == [{"type": "well_safety"}], [x.action for x in p]
    assert "door at the fort end" in p[0].reason and "watcher" in p[0].reason
    m = Memory()
    s["well_safety"]["log"] = [{"tick": 500, "kind": "beside_shaft", "text": "Urist stands beside cavern well 7's open shaft"},
                               {"tick": 600, "kind": "level", "text": "dug up to z64"}]
    p, n = [], []
    planner_wellsafe._well_safety_rule(s, CFG, p, n, m)
    assert any("Urist stands beside" in x for x in n) and not any("z64" in x for x in n), n
    p, n = [], []
    planner_wellsafe._well_safety_rule(s, CFG, p, n, m)          # seen: not said again
    assert not any("Urist" in x for x in n), n


def stranded(**kw):
    r = {"id": 31, "name": "Nomal", "x": 72, "y": 59, "z": 60, "cause": "no_path", "in_cavern": True,
         "out_ticks": 2400, "out_days": 2}
    r.update(kw)
    return r


@plain_test("5 brain: a dwarf stranded in the cavern under a well gets well_rescue before any alarm; waits with a danger near")
def _():
    s = ws_state()
    s["entrances"]["stranded"] = [stranded()]
    p, n = [], []
    planner_wellsafe._well_safety_rule(s, CFG, p, n, Memory())
    r = [x for x in p if x.rule == "well_rescue"]
    assert r and r[0].action == {"type": "well_rescue", "x": 72, "y": 59, "z": 60, "project_id": 7}, [x.action for x in p]
    assert r[0].priority == -1 and "well_rescue" in planner_wellsafe.EMERGENCY
    # far from any well, not out long, or on the surface: not this rule's
    for row in (stranded(x=120), stranded(out_ticks=50), stranded(in_cavern=False), stranded(cause="gate_shut")):
        s["entrances"]["stranded"] = [row]
        p, n = [], []
        planner_wellsafe._well_safety_rule(s, CFG, p, n, Memory())
        assert not [x for x in p if x.rule == "well_rescue"], row
    # a danger near them: said, nothing opened
    s["entrances"]["stranded"] = [stranded(danger_near=9)]
    p, n = [], []
    planner_wellsafe._well_safety_rule(s, CFG, p, n, Memory())
    assert not p and any("danger is 9 tiles" in x for x in n), n


@plain_test("5 brain: planner_gates leaves the stranded under a well to the rescue (no 'the AI can't reach them')")
def _():
    s = ws_state()
    s["entrances"]["stranded"] = [stranded()]
    p, n = [], []
    planner_gates._stranded_rule(s, CFG, p, n, Memory(), any_reach=False)
    assert not any("can't get back up" in x for x in n), n
    s = fort()
    s["entrances"]["stranded"] = [stranded()]
    p, n = [], []
    planner_gates._stranded_rule(s, CFG, p, n, Memory(), any_reach=False)
    assert any("can't get back up" in x for x in n), n          # no well over them: as before
    # and end to end: the rescue proposed by plan()
    s = ws_state()
    s["entrances"]["stranded"] = [stranded()]
    props, notes = plan(s, Memory())
    assert [x for x in props if x.rule == "well_rescue"], [x.rule for x in props]


@plain_test("wiring: the actions, the section, the labels, the config")
def _():
    bridge = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    for name in ("well_safety = function(a)", "well_rescue = function(a)", "'well_safety', 'well_rescue',",
                 "well_safety = function() return safe(", "'well_safety',   -- (0.105.47)", "'ai-well-safety',"):
        assert name in bridge, name
    import digest
    import overseer
    assert "well_safety" in digest.SECTION_DEFAULTS if hasattr(digest, "SECTION_DEFAULTS") else '"well_safety": {}' in \
        (ROOT / "brain" / "digest.py").read_text(encoding="utf-8")
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    assert '"well_safety":' in src and '"well_rescue":' in src
    for k in ("cavern_well_cooldown_days", "cavern_well_site_tries", "well_rescue_after_ticks", "well_rescue_near",
              "well_safety_cooldown_ticks", "well_rescue_cooldown_ticks"):
        assert k in CFG, k
    threats = (ROOT / "lua" / "ai-threats.lua").read_text(encoding="utf-8")
    assert "reqscript('ai-well-safety').fort_doors()" in threats and "door_blocked(o)" in threats


# ---- the bridge --------------------------------------------------------------------------

WS_LOAD = r"""
local B, src = ...
local env = setmetatable({}, {__index = _G})
env.BUILDER = B
assert(load(src, 'ai-well-safety', 't', env))()
WS = env
local real = reqscript
reqscript = function(n) if n == 'ai-well-safety' then return WS end return real(n) end
return env
"""


def boot():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(ROOT / "lua")
    layouts = (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8")
    builder = (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8")
    B, W = lua.execute(_const("test_builder.py", "HARNESS"), layouts, builder)
    lua.execute("df = {global = {cur_year = 148, cur_year_tick = 100}}")
    WS = lua.execute(WS_LOAD, B, (ROOT / "lua" / "ai-well-safety.lua").read_text(encoding="utf-8"))
    return lua, B, W, WS


if LuaRuntime is not None:
    LUA, B, W, WS = boot()
    GAME_FAKE = _const("test_builder.py", "GAME_FAKE")
    GAME_CLEAN = _const("test_builder.py", "GAME_CLEAN")
    REAL_WALK = B.walk_group


def _reset():
    if LuaRuntime is None:
        return
    W.reset()
    B.CAVERN_NO_SPOT = None
    B.SHAFT_WATCH = LUA.table_from({"on": False})
    B.WELL_DIG_UP = True
    B.walk_group = REAL_WALK
    LUA.execute("df = df or {}; df.global = df.global or {}; df.global.cur_year = 148; df.global.cur_year_tick = 100")
    LUA.execute("""WS.STATE = {on = false, log = {}, seen = {}, under = {}, suspended = {}}
                   WS.CITIZENS_FN = function() return CITS or {} end
                   WS.DANGERS_FN = function() return DANGERS or {} end
                   WS.JOBS_FN = nil; WS.SUSPEND_FN = nil; WS.BUILDING_FN = nil; WS.UNLOCK_FN = nil
                   TRAFFIC = {}
                   WS.TRAFFIC_FN = function(x, y, z) table.insert(TRAFFIC, x .. ',' .. y .. ',' .. z); return true end
                   CITS, DANGERS = {}, {}""")


test = make_test(before=_reset)

NOW = None


def now():
    return LUA.table_from({"year": 148, "tick": 100})


def cavern_column(x=70, y=58, top=70):
    """test_builder's: a floor at `top`, solid rock to z63, the cavern's air at 62, its lake at 61."""
    for z in range(66, top):
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                W.set(x + dx, y + dy, z, LUA.table_from({"shape": "WALL", "material": "STONE"}))
    W.set(x, y, 62, LUA.table_from({"shape": "EMPTY", "feature": True}))
    W.set(x, y, 61, LUA.table_from({"shape": "EMPTY", "feature": True, "liquid": True, "depth": 5}))


def cits(*rows):
    LUA.execute("CITS = {}")
    for r in rows:
        LUA.eval("function(r) table.insert(CITS, r) end")(LUA.table_from(r))


def project(pid):
    data = B.load_projects()
    for i in range(1, len(data.list) + 1):
        if data.list[i].id == pid:
            return data, data.list[i]
    raise AssertionError(f"no project {pid}")


def add_project(p):
    data = B.load_projects()
    data.list[len(data.list) + 1] = LUA.table_from(p)
    data.next_id = max(int(data.next_id or 1), int(p["id"]) + 1)
    B.save_projects(data)


def well_rec(pid=9, phase="cancelled", **extra):
    """A cavern well's record (shaft 64..63 under the floor at 70, stairs at 71,58)."""
    p = {"id": pid, "kind": "well", "phase": phase, "z": 70, "anchor": LUA.table_from({"x": 70, "y": 58}),
         "stair": LUA.table_from({"x": 70, "y": 58}), "shaft": LUA.table_from([69, 68, 67, 66, 65, 64, 63]),
         "shaft_stairs": LUA.table_from([LUA.table_from({"x": 71, "y": 58, "z": z, "key": k})
                                         for z, k in [(70, "j")] + [(z, "i") for z in range(69, 63, -1)] + [(63, "u")]]),
         "area": LUA.table_from({"x1": 69, "y1": 57, "x2": 71, "y2": 59, "z": 70}),
         "summary": LUA.table_from({"well": 1, "cavern": True}),
         "cells": LUA.table_from({"dig": LUA.table_from([LUA.table_from({"x": 0, "y": 0, "text": "h"})])})}
    p.update(extra)
    return p


if LuaRuntime is not None:
    @test("1 bridge: place_well refuses a second cavern well while one is dug, and within the cooldown of one given up")
    def _():
        cavern_column()
        add_project(well_rec(4, phase="dig"))
        r = B.place_well(LUA.table_from({"cavern": True}), now(), False)
        assert not r.ok and r.rejected and r.one_at_a_time and "one at a time" in r.error, r.error
        W.reset()
        cavern_column()
        tick = 148 * 403200 + 100
        add_project(well_rec(4, phase="cancelled", cancelled_tick=tick - 5 * 1200))
        r = B.place_well(LUA.table_from({"cavern": True}), now(), False)
        assert not r.ok and r.rejected and r.cooldown and r.days_left == 79, (r.error, r.days_left)
        # the brain's shorter cooldown, passed in the action
        r = B.place_well(LUA.table_from({"cavern": True, "cooldown_days": 3}), now(), False)
        assert r.ok and r.dug_up, r.error

    @test("1 bridge: a site given up twice is kept free (its boxes reserved on the fort's levels round it); one give-up is not")
    def _():
        tick = 148 * 403200 + 100
        add_project(well_rec(4, cancelled_tick=tick - 400 * 1200))
        data = B.load_projects()
        g = WS.place_gate(data, LUA.table_from({}), now())
        assert g.reject is None and g.closed == 0, g.closed
        add_project(well_rec(5, anchor=LUA.table_from({"x": 71, "y": 59}), cancelled_tick=tick - 300 * 1200))
        data = B.load_projects()
        g = WS.place_gate(data, LUA.table_from({}), now())
        assert g.closed == 1 and B.inside_any(g.reserved, 70, 58, 70) and B.inside_any(g.reserved, 73, 61, 75)
        assert not B.inside_any(g.reserved, 75, 58, 70)
        cavern_column()
        r = B.place_well(LUA.table_from({"cavern": True, "gallery": 0}), now(), False)
        assert not r.ok and "no floor inside the fort over cavern water" in r.error, (r.ok, r.error)
        # site_tries 3: open again
        g = WS.place_gate(data, LUA.table_from({"site_tries": 3}), now())
        assert g.closed == 0
        # the report's book: a given-up well with no tick is stamped once (the cooldown counts from then)
        W.reset()
        add_project(well_rec(6))
        rep = WS.report()
        assert rep.book.gone == 1 and rep.book.last_gone == tick and rep.book.cooldown_days_left == 84, rep.book.last_gone
        _, p = project(6)
        assert p.cancelled_tick == tick

    @test("2 bridge: a new cavern shaft is dug from the bottom up: nothing in its column designated, the top last")
    def _():
        cavern_column()
        r = B.place_well(LUA.table_from({"cavern": True}), now(), False)
        assert r.ok and r.dug_up and r.held == 2, r.error
        assert all(not W.get(70, 58, z).designated for z in range(63, 71)), [W.get(70, 58, z).dig_text for z in range(63, 71)]
        assert W.get(71, 58, 70).dig_text == "j" and W.get(71, 58, 64).dig_text == "i" and not W.get(71, 58, 63).designated
        _, p = project(r.project_id)
        assert list(p.up.zs.values()) == [64, 65, 66, 67, 68, 69, 70], list(p.up.zs.values())
        d = B.projects_report().open[1].dig
        assert d.total == 16 and d.held == 9 and d.shaft_open is False and d.stuck == 0, (d.total, d.held, d.stuck)
        # the top waits: not "gone" (no renew, no give-up)
        chk = B.well_dig_check(p)
        assert chk.cause == "held" and "bottom up" in chk.text, chk.cause
        ren = B.renew_well_dig(r.project_id, 2, False)
        assert not ren.ok and ren.rejected and "bottom up" in ren.error
        assert not W.get(70, 58, 70).designated

    @test("2 bridge: each level designated only over an open one, after the break, with nobody in the column; then the well")
    def _():
        LUA.execute("dfhack.timeout = function() return 1 end")
        try:
            cavern_column()
            r = B.place_well(LUA.table_from({"cavern": True}), now(), False)
            pid = r.project_id
            data, p = project(pid)
            assert B.well_up_advance(p, False, None) == "held"  # (one value)
            # the break (well_shaft_step lets it go): the bottom channelled, dug
            p.held = None
            B.save_projects(data)
            W.set(70, 58, 63, LUA.table_from({"shape": "EMPTY", "designated": False}))
            out = WS.step(True)
            assert out.ok and out.advanced == 1 and not W.get(70, 58, 64).designated, "dry run"
            out = WS.step(False)
            assert out.ok and out.advanced == 1 and W.get(70, 58, 64).dig_text == "h", (out.ok, out.error)
            assert out.traffic == 8, out.traffic
            data, p = project(pid)
            assert list(p.up.zs.values())[0] == 65 and p.ws_traffic
            # 64 still rock: 65 waits
            assert B.well_up_advance(p, True, None)[0] == "below"
            W.set(70, 58, 64, LUA.table_from({"shape": "EMPTY", "designated": False}))
            # a citizen in the column (fell in, or on a ramp of an older shaft): it waits
            cits({"id": 1, "name": "Sazir", "x": 70, "y": 58, "z": 63})
            out = WS.step(False)
            assert not out.ok and out.nothing_to_do and not W.get(70, 58, 65).designated
            assert any(e.kind == "in_shaft" or e.kind == "beside_shaft" for e in WS.STATE.log.values())
            cits()
            out = WS.step(False)
            assert out.advanced == 1 and W.get(70, 58, 65).designated
            for z in range(65, 70):
                W.set(70, 58, z, LUA.table_from({"shape": "EMPTY", "designated": False}))
                WS.step(False)
            assert W.get(70, 58, 70).designated, "the top channel comes last"
            data, p = project(pid)
            assert len(list(p.up.zs.values())) == 0
            W.set(70, 58, 70, LUA.table_from({"shape": "EMPTY", "designated": False}))
            for z in range(63, 71):
                t = W.get(71, 58, z)
                t.designated = False
                t.shape = "STAIR_DOWN" if z == 70 else ("STAIR_UP" if z == 63 else "STAIR_UPDOWN")
            assert B.projects_report().open[1].next == "furnish"
        finally:
            LUA.execute("dfhack.timeout = nil")

    @test("2 bridge: a dig job in the column held while a citizen stands in it at or under its level; let go when clear")
    def _():
        add_project(well_rec(7, phase="dig"))
        LUA.execute("""JOBS = {{id = 41, x = 70, y = 58, z = 66, suspended = false}}
                       WS.JOBS_FN = function() return JOBS end
                       WS.SUSPEND_FN = function(row, on) row.suspended = on; return true end""")
        cits({"id": 2, "name": "Uzol", "x": 70, "y": 58, "z": 65})
        r = WS.watch_once()
        assert r.suspended == 1 and LUA.eval("JOBS[1].suspended") is True
        cits({"id": 2, "name": "Uzol", "x": 70, "y": 58, "z": 67})          # above it: no fall
        r = WS.watch_once()
        assert r.released == 1 and LUA.eval("JOBS[1].suspended") is False
        # a job the player suspended is never let go by the guard
        LUA.execute("JOBS[1].suspended = true")
        cits()
        r = WS.watch_once()
        assert r.released == 0 and LUA.eval("JOBS[1].suspended") is True

    @test("2 bridge: the watcher logs a citizen beside an open shaft (once a day) and one who turns up in the cavern under it")
    def _():
        add_project(well_rec(7, phase="done"))
        for z in range(63, 70):
            W.set(70, 58, z, LUA.table_from({"shape": "EMPTY"}))
        W.set(73, 60, 61, LUA.table_from({"shape": "FLOOR", "feature": True}))
        cits({"id": 3, "name": "Melbil", "x": 71, "y": 58, "z": 64}, {"id": 4, "name": "Bembul", "x": 73, "y": 60, "z": 61})
        r = WS.watch_once()
        kinds = sorted(e.kind for e in WS.STATE.log.values())
        assert r.logged == 2 and kinds == ["beside_shaft", "under_well"], kinds
        r = WS.watch_once()
        assert r.logged == 0                                            # the same: not again
        rep = WS.report()
        row = rep.wells[1]
        assert row.under[1].name == "Bembul" and row.below_lid in ("Melbil", "Bembul"), row.below_lid
        assert rep.log[1].text and rep.logged == 2

    @test("3 bridge: a door at the gallery's fort end (a hatch over the stair top in a hall), recorded for the seal")
    def _():
        LUA.execute(GAME_FAKE)
        try:
            LUA.execute("df.building_type.Door = 6; df.building_type[6] = 'Door'")
            gal = LUA.table_from([LUA.table_from({"x": 72, "y": 61}), LUA.table_from({"x": 72, "y": 60}),
                                  LUA.table_from({"x": 72, "y": 59})])
            W.set(72, 61, 70, LUA.table_from({"shape": "WALL"}))
            add_project(well_rec(8, phase="dig", gallery=gal))
            assert WS.door_spot(project(8)[1]).kind == "door"
            out = WS.step(True)
            assert out.doors == 0, "the gallery's first tile not dug yet"
            W.set(72, 61, 70, LUA.table_from({"shape": "FLOOR"}))
            out = WS.step(True)
            assert out.ok and out.doors == 1 and not [x for x in W.placed.values() if x.mode == "build"], "dry run"
            out = WS.step(False)
            built = [x for x in W.placed.values() if x.mode == "build"]
            assert out.doors == 1 and len(built) == 1 and (built[0].x, built[0].y, built[0].text) == (72, 61, "d")
            _, p = project(8)
            assert p.fort_door.kind == "door" and WS.door_state(p)[0] == "gone"   # (the fake places nothing)
            LUA.execute("MKS(72, 61, 70, 6, true)")
            assert WS.door_state(project(8)[1])[0] == "built"
            doors = WS.fort_doors()
            assert len(doors) == 1 and (doors[1].x, doors[1].y, doors[1].z) == (72, 61, 70)
            # nobody beyond: the seal may lock it; someone in the gallery or the stairs: not
            assert WS.door_blocked(LUA.table_from({"x": 72, "y": 61, "z": 70})) is None
            cits({"id": 5, "name": "Kib", "x": 72, "y": 59, "z": 70})
            assert WS.door_blocked(LUA.table_from({"x": 72, "y": 61, "z": 70})) == "Kib"
            cits({"id": 5, "name": "Kib", "x": 71, "y": 58, "z": 66})
            assert WS.door_blocked(LUA.table_from({"x": 72, "y": 61, "z": 70})) == "Kib"
            # a well in a hall: a hatch over its stair top once that is dug
            W.reset()
            add_project(well_rec(9, phase="dig"))
            W.set(71, 58, 70, LUA.table_from({"shape": "STAIR_DOWN"}))
            WS.step(False)
            built = [x for x in W.placed.values() if x.mode == "build"]
            assert built and (built[-1].x, built[-1].y, built[-1].text) == (71, 58, "H")
        finally:
            LUA.execute(GAME_CLEAN)

    @test("4 bridge: the stair lid is never locked, nor the gate shut for no danger, with a dwarf below; never opened under one")
    def _():
        LUA.execute(GAME_FAKE)
        try:
            add_project(well_rec(9, phase="done", shaft_gate=LUA.table_from({"impossible": True})))
            for z in range(63, 71):
                W.set(70, 58, z, LUA.table_from({"shape": "EMPTY"}))
            W.set(71, 58, 70, LUA.table_from({"shape": "STAIR_DOWN"}))
            LUA.execute("LID = MKS(71, 58, 70, 7, true)")
            cits({"id": 6, "name": "Nomal", "x": 71, "y": 58, "z": 64})
            r = B.seal_well_stairs(False)
            assert not r.ok and r.below == "Nomal" and "below the stair lid" in r.error, r.error
            assert LUA.eval("LID.door_flags.forbidden") is False
            # in the cavern under the well: still not
            W.set(74, 60, 61, LUA.table_from({"shape": "FLOOR", "feature": True}))
            cits({"id": 6, "name": "Nomal", "x": 74, "y": 60, "z": 61})
            assert not B.seal_well_stairs(False).ok
            cits()
            r = B.seal_well_stairs(False)
            assert r.ok and r.locked == 1 and LUA.eval("LID.door_flags.forbidden") is True
            # the gate: opening refused with a citizen on the shut hatch; shutting for a danger always allowed
            assert WS.gate_block(9, False, False, LUA.table_from([LUA.table_from(
                {"id": 1, "name": "Udib", "x": 70, "y": 58, "z": 63})])) == "Udib"
            assert WS.gate_block(9, True, True, LUA.table_from([LUA.table_from(
                {"id": 1, "name": "Udib", "x": 70, "y": 58, "z": 63})])) is None
            assert WS.gate_block(9, True, False, LUA.table_from([LUA.table_from(
                {"id": 1, "name": "Udib", "x": 74, "y": 60, "z": 61})])) == "Udib"
            assert WS.gate_block(9, False, False, LUA.table_from([])) is None
        finally:
            LUA.execute(GAME_CLEAN)

    @test("4 bridge: well_shaft_step keeps the gate as it is with a dwarf on the hatch, and the break waits for the column")
    def _():
        LUA.execute(GAME_FAKE)
        try:
            # a linked, shut gate on a built well; the brain asks it open
            add_project(well_rec(9, phase="done", shaft_gate=LUA.table_from(
                {"lever": LUA.table_from({"x": 72, "y": 60, "z": 70})})))
            for z in range(63, 71):
                W.set(70, 58, z, LUA.table_from({"shape": "EMPTY"}))
            LUA.execute("""LEV = MKS(72, 60, 70, 8, true, 3); HAT = MKS(70, 58, 63, 7, true)
                           LINKS[HAT.id] = {LEV.id}""")
            cits({"id": 1, "name": "Mebzuth", "x": 70, "y": 58, "z": 63})
            r = B.well_shaft_step(False, False)
            assert r.wells[1].stage == "waiting_below" and r.wells[1].below == "Mebzuth", r.wells[1].stage
            assert LUA.eval("#PULLS") == 0 and LUA.eval("HAT.door_flags.closed") is True
            r = B.well_shaft_step(False, False)                 # (the watcher runs now: a plain refusal, said)
            assert not r.ok and "Mebzuth" in r.error, r.error
            cits()
            r = B.well_shaft_step(False, False)
            assert r.ok and r.wells[1].stage == "opened" and LUA.eval("HAT.door_flags.closed") is False, r.error
            # the break into the cavern: waits while a citizen is in the column
            W.reset()
            LUA.execute("for k in pairs(SB) do SB[k] = nil end; for k in pairs(LINKS) do LINKS[k] = nil end")
            add_project(well_rec(10, phase="dig", held=LUA.table_from({"z": 63, "stair": LUA.table_from({"x": 71, "y": 58})}),
                                 shaft_gate=LUA.table_from({"lever": LUA.table_from({"x": 72, "y": 60, "z": 70})})))
            LUA.execute("MKS(72, 60, 70, 8, true, 3); MECH(4); df.global.world.items.other.HATCH_COVER = {{}}")
            B.count_items = LUA.eval("function(k) if k == 'HATCH_COVER' then return 1 end return #MECHS end")
            cits({"id": 1, "name": "Sodel", "x": 70, "y": 58, "z": 66})
            r = B.well_shaft_step(False, False)
            assert r.wells[1].stage == "waiting_below" and not W.get(70, 58, 63).designated, r.wells[1].stage
            cits()
            r = B.well_shaft_step(False, False)
            assert r.wells[1].stage == "break_started" and W.get(70, 58, 63).designated, (r.wells[1].stage, r.error)
        finally:
            LUA.execute(GAME_CLEAN)

    @test("5 bridge: the rescue digs a stair out from the well's stairs to the cavern floor they stand on; not with a beast near")
    def _():
        add_project(well_rec(7, phase="done"))
        # the cavern under the well: air at 62, a floor at 60 beside the stair column's foot
        for x in range(68, 76):
            for y in range(56, 62):
                if not (x == 71 and y == 58):
                    W.set(x, y, 62, LUA.table_from({"shape": "EMPTY", "feature": True}))
        W.set(72, 58, 60, LUA.table_from({"shape": "FLOOR", "feature": True}))
        B.walk_group = LUA.eval("""function(x, y, z)
            if z == 60 and x == 72 and y == 58 then return 5 end
            if z >= 63 and z <= 80 then return 1 end
            return 0 end""")
        r = WS.rescue(72, 58, 60, None, True)
        assert r.ok and r.dry_run and r.stair == 4 and r.foot.x == 71, (r.ok, r.error)
        assert not W.get(71, 58, 62).designated, "dry run"
        LUA.execute("DANGERS = {{id = 90, name = 'Ozkak', x = 74, y = 60, z = 60}}")
        r = WS.rescue(72, 58, 60, None, False)
        assert not r.ok and r.waiting and "Ozkak" in r.error, r.error
        LUA.execute("DANGERS = {}")
        r = WS.rescue(72, 58, 60, None, False)
        assert r.ok and r.project_id == 7, r.error
        assert W.get(71, 58, 63).dig_text == "i1" and W.get(71, 58, 62).dig_text == "i1" and W.get(71, 58, 60).dig_text == "u1"
        _, p = project(7)
        assert p.rescue.tries == 1
        again = WS.rescue(72, 58, 60, None, False)
        assert not again.ok and again.digging, again.error
        # nowhere near a well: not this action's
        assert not WS.rescue(110, 110, 60, None, True).ok

    @test("5 bridge: a way back held only by the well's locked door is unlocked for them")
    def _():
        LUA.execute("UNLOCKED = {}; WS.UNLOCK_FN = function(b) table.insert(UNLOCKED, b.id); return true end")
        LUA.execute("""WS.BUILDING_FN = function(x, y, z)
            if x == 72 and y == 61 and z == 70 then return {id = 77, type = 'Door', built = true, locked = true} end end""")
        add_project(well_rec(7, phase="done", fort_door=LUA.table_from({"x": 72, "y": 61, "z": 70, "kind": "door"})))
        B.walk_group = LUA.eval("function(x, y, z) if z == 60 or z == 63 then return 5 end return 1 end")
        W.set(72, 58, 60, LUA.table_from({"shape": "FLOOR", "feature": True}))
        r = WS.rescue(72, 58, 60, 7, False)
        assert r.ok and r.unlocked == 1 and LUA.eval("UNLOCKED[1]") == 77, r.error

finish(None if LuaRuntime is not None else "these tests need the lupa package (pip install lupa)")
