"""(0.105.33, group projects) The project lifecycle and the way in
(lua/ai-builder-projects.lua) and the builder hub's shared helpers
(lua/ai-builder.lua), on test_r32_wayin's fake map in a real Lua engine.

- L4: a way in is never furnished with a step missing, a lost tile is put
  back at most REDIG_MAX times, cancel_project takes off what dig_progress
  kept designated, and the way-in search: no nil anchor, a great danger
  refuses too, the top 'j' into natural ground, a column the dry run
  refuses is left out and the search run again, the column's levels
  reserved.
- L8: site_get / site_put and item_held are ai-util's.
- Industry change 2: projects_report's done_total never saturates.

    python tests/test_r33_projects.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime  # noqa: F401
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import test_r32_wayin as R32  # noqa: E402  (the way-in fakes; its tests run only when it is run itself)

LUA, B, W, G = R32.LUA, R32.B, R32.W, R32.G      # (its way_in() uses these)
test = make_test(before=lambda: W.reset())
way_in, designated, projects, column_of = R32.way_in, R32.designated, R32.projects, R32.column_of
KEY = "ai-overseer/projects"


def open_of(rep):
    return [rep.open[i] for i in range(1, len(rep.open) + 1)]


# --- L4 Med 410-421/442-449/530-540: a way in with a lost step -------------------

@test("L4: a way-in tile the game keeps cancelling is put back REDIG_MAX times, then the way in is cancelled, never furnished")
def _():
    r = way_in()
    assert r.ok, dict(r)
    W.set(41, 25, 27, LUA.table_from({"designated": False, "dig_text": None}))    # the game took it off
    W.dig_all()                                                                    # the rest dug
    nexts = []
    for _ in range(B.REDIG_MAX + 1):
        o = open_of(B.projects_report())[0]
        nexts.append(o.next)
        W.set(41, 25, 27, LUA.table_from({"designated": False}))                  # and takes it off again
    assert nexts[:B.REDIG_MAX] == [False] * B.REDIG_MAX, nexts
    assert nexts[-1] == "cancel", nexts
    p = projects()[0]
    assert p.redug["41,25,27"] == B.REDIG_MAX and p.redug_changed is None, dict(p.redug)
    # furnish refuses a way in outright (the brain's stall rule can ask for it)
    f = B.furnish_project(1, True, True)
    assert not f.ok and f.rejected and "never furnished" in f.error, dict(f)
    assert projects()[0].phase == "dig"


@test("L4: a fully dug way in still finishes (the cap leaves the happy path alone)")
def _():
    assert way_in().ok
    W.dig_all()
    o = open_of(B.projects_report())[0]
    assert o.next == "finish" and o.dig.dug == o.dig.total == 7, (o.next, dict(o.dig))


# --- L4 Med 1239-1254: cancel takes the column and tunnel off ------------------------

@test("L4: cancel_project takes a way in's column (shaft_stairs) off")
def _():
    assert way_in().ok
    assert len(designated()) == 7
    c = B.cancel_project(1)
    assert c.ok and projects()[0].phase == "cancelled", dict(c)
    assert designated() == [], designated()


@test("L4: cancel_project takes a way in's tunnel (gallery) off too")
def _():
    W.box(14, 14, 46, 36, 30, LUA.table_from({"building": True}))     # the column can't stand beside the fort
    r = way_in(x=46, y=25)
    assert r.ok and r.tunnel == 6, dict(r)
    assert any(t[2] == 24 and t[3] == "d1" for t in designated())
    assert B.cancel_project(1).ok
    assert designated() == [], designated()


@test("L4: cancel_project takes a well's shaft ('h') off")
def _():
    W.persist[KEY] = LUA.table_from({"next_id": 2, "list": LUA.table_from({1: LUA.table_from({
        "id": 1, "kind": "well", "phase": "dig", "z": 24, "anchor": LUA.table_from({"x": 50, "y": 50}),
        "cells": LUA.table_from({"dig": LUA.table()}), "shaft": LUA.table_from({1: 23, 2: 22}),
        "params": LUA.table_from({"pri": ""})})})})
    for z in (23, 22):
        W.set(50, 50, z, LUA.table_from({"designated": True, "dig_text": "h"}))
    assert B.cancel_project(1).ok
    assert not W.get(50, 50, 23).designated and not W.get(50, 50, 22).designated


# --- L4 Lows: the way-in search --------------------------------------------------------

@test("L4 Low 1300-1303/1547-1548: 'citizens inside' (a group, no tile) stores no anchor; the search refuses cleanly")
def _():
    gm = B.way_in_gates()
    real = gm.fort_interior
    try:
        gm.fort_interior = LUA.eval("function() return {what = 'citizens inside', group = 1} end")
        fort = B.way_in_fort()
        assert len(fort.anchors) == 0, [dict(a) for a in fort.anchors.values()]
        W.GATES.inside = LUA.table()        # and no inside tile passes
        r = way_in(dry=True)
        assert "search failed" not in str(r.error), dict(r)
    finally:
        gm.fort_interior = real


@test("L4 Low 1669-1683: a great danger (no invader) in sight near an end refuses the way in")
def _():
    gm = B.way_in_gates()
    try:
        gm.visible_dangers = LUA.eval(
            "function() return {{pos = {x = 61, y = 25, z = 30}, invader = false, great = true}} end")
        r = way_in()
        assert not r.ok and r.rejected and "great danger" in r.error and designated() == [], dict(r)
        gm.visible_dangers = LUA.eval(
            "function() return {{pos = {x = 41, y = 63, z = 39}, invader = false, great = true}} end")
        assert way_in(dry=True).ok                 # far off: dug
    finally:
        gm.visible_dangers = None


@test("L4 Low 1357-1360: the top 'j' never goes into a built (not natural) floor")
def _():
    W.set(41, 25, 30, LUA.table_from({"material": "CONSTRUCTION"}))
    r = way_in(dry=True)
    assert r.ok and column_of(r) != (41, 25), dict(r)
    assert W.get(r.column.x, r.column.y, 30).material == "SOIL"


@test("L4 Low 1694-1699: a column quickfort's dry run refuses is left out and the next best tried")
def _():
    real = B.quickfort_apply
    W.set(41, 25, 27, LUA.table_from({"refuse": True}))
    B.quickfort_apply = LUA.eval("""function(real, W)
      return function(mode, cells, z, x, y, command, dry)
        local t = W.get(x, y, z)
        if t and t.refuse then return {dig_designated = {value = 0}} end
        return real(mode, cells, z, x, y, command, dry)
      end end""")(real, W)
    try:
        r = way_in()
    finally:
        B.quickfort_apply = real
    assert r.ok and column_of(r) != (41, 25), dict(r)
    assert not any(t[0] == 41 and t[1] == 25 for t in designated()), designated()


@test("L4 Low 1717-1720: the column's other levels are in level_areas (reserved)")
def _():
    assert way_in().ok
    boxes = [B.level_areas()[i] for i in range(1, len(B.level_areas()) + 1)]
    for z in range(25, 31):
        assert any(b.z == z and b.x1 <= 41 <= b.x2 and b.y1 <= 25 <= b.y2 for b in boxes), z
    # and they go to old_areas when the project is dropped
    p = projects()[0]
    assert len(p.areas) == 6, len(p.areas)


# --- Industry change 2: done_total --------------------------------------------------------

def _seed(n_done, old_areas=0, dropped=None):
    lst = LUA.table()
    for i in range(1, n_done + 1):
        lst[i] = LUA.table_from({"id": i, "kind": "bedrooms", "phase": "done",
                                 "area": LUA.table_from({"x1": 0, "y1": 0, "x2": 1, "y2": 1, "z": 10})})
    d = {"next_id": n_done + 1, "list": lst,
         "old_areas": LUA.table_from({i: LUA.table_from({"x1": 0, "y1": 0, "x2": 1, "y2": 1, "z": 5})
                                      for i in range(1, old_areas + 1)})}
    if dropped is not None:
        d["dropped_done"] = dropped
    W.persist[KEY] = LUA.table_from(d)


@test("industry 2: done_total goes past KEEP_CLOSED_PROJECTS while finished stops at it")
def _():
    _seed(25)
    B.save_projects(B.load_projects())
    rep = B.projects_report()
    assert rep.finished == B.KEEP_CLOSED_PROJECTS == 20 and rep.done_total == 25, (rep.finished, rep.done_total)
    # five more finish: still counted
    d = B.load_projects()
    for i in range(5):
        d.list[len(d.list) + 1] = LUA.table_from({"id": 100 + i, "kind": "dining", "phase": "done"})
    B.save_projects(d)
    rep = B.projects_report()
    assert rep.finished == 20 and rep.done_total == 30, (rep.finished, rep.done_total)


@test("industry 2: an older save (no counter) starts from its dropped outlines; cancelled drops are not counted")
def _():
    _seed(20, old_areas=7)
    assert B.projects_report().done_total == 27
    d = B.load_projects()
    d.list[len(d.list) + 1] = LUA.table_from({"id": 99, "kind": "dining", "phase": "cancelled"})
    B.save_projects(d)                       # the oldest done one dropped for the cancelled one
    rep = B.projects_report()
    assert rep.finished == 19 and rep.done_total == 27 + 0, (rep.finished, rep.done_total)
    assert W.persist[KEY].dropped_done == 8


# --- L8 Lows ai-builder.lua 288-305 ---------------------------------------------------------

@test("L8: item_held is ai-util's list: rotten, owned, an artifact... held; in a job is the caller's")
def _():
    held = LUA.eval("function(B, f) return B.item_held({flags = f}) and true or false end")
    for flag in ("rotten", "owned", "artifact", "encased", "on_fire", "spider_web", "murder", "dead_dwarf",
                 "forbid", "in_building", "construction", "removed", "garbage_collect", "trader", "dump", "hostile"):
        assert held(B, LUA.table_from({flag: True})), flag
    assert not held(B, LUA.table_from({"in_job": True}))
    assert not held(B, LUA.table())


@test("L8: site_get / site_put are ai-util's; a corrupt projects record reads as none")
def _():
    W.persist["k1"] = "junk"
    assert len(B.site_get("k1")) == 0
    ok = B.site_put("k2", LUA.table_from({"a": 1}))
    assert ok is True and B.site_get("k2").a == 1
    W.persist[KEY] = "junk"
    d = B.load_projects()
    assert d.next_id == 1 and len(d.list) == 0


finish()
