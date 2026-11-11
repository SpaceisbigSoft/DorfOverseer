"""(0.105.33, merge) The cross-group follow-ups done at the merge of round
33: each a small change in one group's file that another group's fix needs.

- the bridge passes society's `release` (recreation) and waterworks'
  `reopen` (water_work) through;
- planner_core's rope order doesn't take the hospital's cloth off twice;
- planner.py calls _gems_rule (scorecard's signature) and _water_zone_rule
  (wells: cfg) as their owners asked;
- cancel_project undoes a well with the wells group's undo_well_cells;
  a level's start passes `new_corridor` through;
- waterworks' cancel_pulls is the cistern's cancel_lever_pulls;
- digest: a default projects.done_total;
- planner_gates says entrances.stranded_error, lever_wait_days, lock_only;
- one_cycle writes nothing dated into memory when the report's date failed;
- _bottleneck_rule no longer raises on a None workshop count.

    python tests/test_r33_merge.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import make_test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import test_overseer as TO  # noqa: E402  (its fake bridge; its tests run only when it is run itself)
import test_r32_wayin as R32  # noqa: E402
import test_hygiene_bridge as HB  # noqa: E402
from digest import normalize  # noqa: E402
import planner  # noqa: E402
from planner import Memory, plan, PLANNER_CONFIG  # noqa: E402
import planner_core  # noqa: E402

test = make_test(before=lambda: (TO._before(), R32.W.reset()))
LUA_DIR = ROOT / "lua"
REAL = json.loads((ROOT / "tests" / "fixtures" / "real" / "region2-0.83-y62-spring.json").read_text(encoding="utf-8"))


def real():
    return copy.deepcopy(REAL)


# --- the bridge passes the groups' new flags through -----------------------------

@test("act_recreation passes `release` (society) as recreation_tick's 7th argument")
def _():
    HB.H.scripts = HB.LUA.table()
    M = HB.H.module()
    HB.LUA.execute("""local H = ...
      H.got = nil
      H.scripts['ai-society'] = {recreation_tick = function(n, days, dry, txt, f, fd, release)
        H.got = {n = n, release = release}; return {ok = true} end}""", HB.H)
    M.act_recreation(HB.t({"max": 4, "release": True}))
    assert HB.H.got.release is True and HB.H.got.n == 4, dict(HB.H.got)
    M.act_recreation(HB.t({"max": 4}))
    assert HB.H.got.release is False, dict(HB.H.got)


@test("act_water_work passes `reopen` (waterworks) into step's options")
def _():
    HB.H.scripts = HB.LUA.table()
    M = HB.H.module()
    HB.LUA.execute("""local H = ...
      H.got = nil
      H.scripts['ai-waterworks'] = {KINDS = {moat = true}, MAGMA_SHOPS = {},
        step = function(kind, opts) H.got = opts; return {ok = true} end}""", HB.H)
    M.act_water_work(HB.t({"kind": "moat", "reopen": True}))
    assert HB.H.got.reopen is True, dict(HB.H.got)
    M.act_water_work(HB.t({"kind": "moat"}))
    assert HB.H.got.reopen is False


# --- planner_core: the hospital's cloth taken off once -----------------------------

def _rope(supplies_hospital: bool):
    s = {"stocks": {"cloth": 9}, "orders": [],
         "supplies": {"cloth_kinds": {"plant": 3, "silk": 0, "yarn": 0}},
         "locations": {"list": [{"type": "HOSPITAL", "have": {"cloth": 3}}]},
         "military": {}}
    if supplies_hospital:
        s["supplies"]["hospital"] = {"cloth": 3, "thread": 0}
    props, notes = [], []
    planner_core._restraint_order(s, 3, dict(PLANNER_CONFIG), props, notes)
    return [p.action.get("recipe") for p in props]


@test("rope order: a bridge with supplies.hospital already left the hospital's cloth out (not taken off twice)")
def _():
    assert _rope(True) == ["cloth_rope"], _rope(True)
    assert _rope(False) == [], _rope(False)        # an older bridge: cloth_kinds holds it, taken off here


# --- planner.py: the owners' new signatures ---------------------------------------

@test("plan() calls _gems_rule with traits, memory, notes and _water_zone_rule with cfg")
def _():
    got = {}
    real_g, real_w = planner._gems_rule, planner._water_zone_rule

    def _gems_rule(s, cfg, proposals, traits=None, memory=None, notes=None):
        got["gems"] = (traits is not None, memory is not None, isinstance(notes, list))

    def _water_zone_rule(s, proposals, notes, cfg=None):
        got["water"] = cfg

    planner._gems_rule, planner._water_zone_rule = _gems_rule, _water_zone_rule
    try:
        cfg = dict(PLANNER_CONFIG, marker=1)
        plan(real(), Memory(), cfg)
    finally:
        planner._gems_rule, planner._water_zone_rule = real_g, real_w
    assert got.get("gems") == (True, True, True), got
    assert isinstance(got.get("water"), dict) and got["water"].get("marker") == 1, got


# --- ai-builder-projects: the wells group's undo, the builder's new corridor -------

@test("cancel_project: a well is undone by undo_well_cells (wells), shaft and all")
def _():
    B, W, LUA = R32.B, R32.W, R32.LUA
    W.persist["ai-overseer/projects"] = LUA.table_from({"next_id": 2, "list": LUA.table_from({1: LUA.table_from({
        "id": 1, "kind": "well", "phase": "dig", "z": 24, "anchor": LUA.table_from({"x": 50, "y": 50}),
        "cells": LUA.table_from({"dig": LUA.table()}), "shaft": LUA.table_from({1: 23, 2: 22}),
        "params": LUA.table_from({"pri": ""})})})})
    for z in (23, 22):
        W.set(50, 50, z, LUA.table_from({"designated": True, "dig_text": "h"}))
    real_u = B.undo_well_cells
    calls = LUA.table()
    B.undo_well_cells = LUA.eval("""function(real, calls)
        return function(p) table.insert(calls, p.id); return real(p) end end""")(real_u, calls)
    try:
        assert B.cancel_project(1).ok
    finally:
        B.undo_well_cells = real_u
    assert list(calls.values()) == [1], list(calls.values())
    assert not W.get(50, 50, 23).designated and not W.get(50, 50, 22).designated


@test("start_project: the site's new_corridor is in the result, the dry run and the project")
def _():
    src = (LUA_DIR / "ai-builder-projects.lua").read_text(encoding="utf-8")
    assert src.count("new_corridor = site.new_corridor") == 4, src.count("new_corridor = site.new_corridor")


# --- waterworks: the cistern's one cancel_lever_pulls -----------------------------

@test("waterworks cancel_pulls is the builder's cancel_lever_pulls (the loop only without it)")
def _():
    L = LuaRuntime(unpack_returned_tuples=True)
    env = L.execute(r"""
      local src = ...
      local env = setmetatable({}, {__index = _G})
      env.dfhack = {persistent = {saveSiteData = function() end, getSiteData = function(k, d) return d end}}
      env.GOT = {}
      env.reqscript = function(name)
        if name == 'ai-builder' then
          return {cancel_lever_pulls = function(id) table.insert(env.GOT, id); return 2 end}
        end
        error('no ' .. name)
      end
      assert(load(src, 'ai-waterworks', 't', env))()
      return env
    """, (LUA_DIR / "ai-waterworks.lua").read_text(encoding="utf-8"))
    assert env.cancel_pulls(77) == 2 and env.GOT[1] == 77


# --- digest: done_total's default ---------------------------------------------------

@test("digest: a failed projects section reads done_total 0")
def _():
    s = normalize({"projects": {"error": "boom"}})
    assert s["projects"]["done_total"] == 0 and "projects" in s["_errors"]
    assert planner_core.levels_done(s) == 0


# --- planner_gates: the gates group's report fields said ---------------------------

def _gates(**ent):
    s = real()
    s.setdefault("entrances", {}).update(ent)
    return plan(s, Memory())[1]


@test("gates: entrances.stranded_error is said (Needs you), as watch_error is")
def _():
    notes = _gates(stranded_error="lua: stranded_citizens failed")
    assert [n for n in notes if n.startswith("Needs you") and "shut outside failed" in n
            and "stranded_citizens failed" in n], [n for n in notes if "outside" in n]
    assert not [n for n in _gates() if "shut outside failed" in n]


@test("gates: a drawbridge's lever_wait_days and a lock_only gate are noted")
def _():
    s = real()
    es = s["entrances"].get("entrances") or []
    assert es, "the fixture has entrances"
    es[0]["sealed"] = False
    es[0]["lever_wait_days"] = 9
    es[0]["lock_only"] = True
    s["entrances"]["armed"] = True
    notes = plan(s, Memory())[1]
    assert [n for n in notes if "waited 9 day(s) for a lever" in n], [n for n in notes if "lever" in n]
    assert [n for n in notes if "shares a lever with another gate" in n], [n for n in notes if "lever" in n]


# --- overseer: nothing dated into memory on a failed date ---------------------------

@test("one_cycle: the report's date failed -> no deaths, events, timeline row or chronicle written; said")
def _():
    b = TO.FakeBridge()
    TO.overseer.one_cycle(b, autopilot=True)          # a good cycle first: memory exists
    before = TO.saved()["memory"]
    b2 = TO.FakeBridge(events=[{"kind": "death", "own_civ": True, "name": "Urist", "id": 5}])
    b2._state["date"] = {"error": "lua: date failed"}
    called = []
    real_nd, real_rw = TO.overseer.crisis.note_deaths, TO.overseer.remember_world
    TO.overseer.crisis.note_deaths = lambda *a: called.append("deaths")
    TO.overseer.remember_world = lambda *a, **k: called.append("world")
    try:
        TO.overseer.one_cycle(b2, autopilot=True)
    finally:
        TO.overseer.crisis.note_deaths, TO.overseer.remember_world = real_nd, real_rw
    assert called == [], called
    assert any("date couldn't be read" in x for x in TO.SAID), TO.SAID[-5:]
    after = TO.saved()["memory"]
    assert after.get("timeline") == before.get("timeline")
    assert after.get("chronicle") == before.get("chronicle")


# --- planner_industry: _bottleneck_rule on a None count ----------------------------

@test("_bottleneck_rule: a None workshop count is none, no TypeError")
def _():
    s = real()
    s["buildings"]["workshops"]["Still"] = None
    _, notes = plan(s, Memory())
    assert not [n for n in notes if n.startswith("rule _bottleneck_rule failed")], \
        [n for n in notes if "failed" in n]


if __name__ == "__main__":
    finish()
