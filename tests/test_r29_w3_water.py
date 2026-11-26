"""(R29 W3) Water works that finish (Phase 13), from the 25 Nov run (all six
forts on region4):

- the floodgate nobody made (A, C, F's irrigation "being built: the
  floodgate" for 150-313 days, 0 floodgates and no order): the mason's order
  for each missing part (floodgate, hatch cover, mechanism), and the magma
  works' magma-safe parts;
- a dry run that refused the first site ("a building (civzone) in the way",
  A): the planners walk the dry run themselves and try the next site;
- D's moat "the gate has no open ground outside it" (the gate scanned at its
  stair's foot, the open ground one level up): the gate's sides up its stair;
- the magma pipe "other water beside the way" (A, B, D, E): the survey's
  estimate from the fort's middle no longer rules a magma body out;
- the cistern search "cut short" (A, B, F): the survey's own plan taken when
  the map still fits it, else a fort level a call, the best kept between calls;
- each work's emergency gate proven (seen open, then shut by its lever) and
  reported; a done moat/magma/pump work is test-shut once and opened again.

    python tests/test_r29_w3_water.py

The planner tests run anywhere; the Lua ones need lupa (skipped without it).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, have_lua, skip  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import planner_water  # noqa: E402
from planner_core import PLANNER_CONFIG  # noqa: E402

LUA_DIR = ROOT / "lua"
YEAR = 403200


def lua(name: str) -> str:
    return (LUA_DIR / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def state(works=None, refused=None, orders=None, **over):
    s = {"date": {"year": 10, "tick": 0}, "dwarves": {"total": 60},
         "settings": {"traits": {"fortification": 0, "engineering": 0}},
         "water": {"bodies": []}, "entrances": {"entrances": []},
         "waterworks": {"works": works or {}, "refused": refused or {}},
         "buildings": {"workshops": {}, "furnaces": {}, "other": {}},
         "others_on_map": {}, "orders": orders or [], "projects": {"open": []}, "_errors": {}}
    s.update(over)
    return s


def run(s):
    props, notes = [], []
    planner_water._waterworks_rule(s, None, PLANNER_CONFIG, props, notes)
    return props, notes


def orders_of(props):
    return [p for p in props if p.action.get("type") == "work_order"]


# --- the parts nobody made ---------------------------------------------------------------

def _irr(**row):
    return {"irrigation": {"kind": "irrigation", "stage": "building", "gate": "planned", **row}}


@test("R29 W3: a work waiting on a floodgate with none free or carried, and no order: a mason makes one")
def _():
    props, notes = run(state(_irr(build_left=1, build_wait=["Floodgate"], floodgates_free=0,
                                  floodgates_reserved=0, mechanisms_free=4)))
    o = orders_of(props)
    assert [p.action for p in o] == [{"type": "work_order", "recipe": "stone_floodgate", "amount": 1}], props
    assert o[0].rule == "waterworks_irrigation" and o[0].is_order
    assert any("waits for floodgate (none free)" in n for n in notes), notes
    # no other step asked while the piece is unbuilt (item39)
    assert all(p.action.get("type") == "work_order" for p in props)


@test("R29 W3: no floodgate order when one is free, carried to its job, or already ordered; an older bridge says nothing")
def _():
    for row in ({"floodgates_free": 1, "floodgates_reserved": 0}, {"floodgates_free": 0, "floodgates_reserved": 1}):
        props, _ = run(state(_irr(build_left=1, build_wait=["Floodgate"], **row)))
        assert not orders_of(props), (row, props)
    props, _ = run(state(_irr(build_left=1, build_wait=["Floodgate"], floodgates_free=0),
                         orders=[{"recipe": "stone_floodgate", "amount_left": 1}]))
    assert not orders_of(props)
    props, _ = run(state(_irr(build_left=1, floodgates_free=0)))        # no build_wait: an older bridge
    assert not orders_of(props)
    s = state(_irr(build_left=1, build_wait=["Floodgate"], floodgates_free=0))
    del s["orders"]                                                    # no orders list: no crash, no order
    assert not orders_of(run(s)[0])


@test("R29 W3: a hatch cover and a mechanism ordered for the pieces that wait on them")
def _():
    works = {"magma:MagmaForge": {"kind": "magma", "shop": "MagmaForge", "stage": "building", "gate": "planned",
                                  "build_left": 2, "build_wait": ["Lever", "Hatch"], "floodgates_free": 0,
                                  "mechanisms_free": 0, "mechanisms_reserved": 0, "hatches_free": 0}}
    recipes = sorted(p.action["recipe"] for p in orders_of(run(state(works))[0]))
    assert recipes == ["mechanisms", "stone_hatch_cover"], recipes


@test("R29 W3: a dug magma work short of magma-safe parts orders the shortfall of each")
def _():
    works = {"magma:MagmaForge": {"kind": "magma", "shop": "MagmaForge", "stage": "digging", "dig_left": 0,
                                  "magma_parts": {"floodgates": 0, "hatches": 1, "mechanisms": 1}}}
    o = {p.action["recipe"]: p.action["amount"] for p in orders_of(run(state(works))[0])}
    assert o == {"stone_floodgate": 1, "mechanisms": 2}, o
    works["magma:MagmaForge"]["magma_parts"] = {"floodgates": 1, "hatches": 1, "mechanisms": 3}
    assert not orders_of(run(state(works))[0])


# --- the emergency gate ------------------------------------------------------------------

@test("R29 W3: a done work under its emergency gate test is asked again (gate shut); a proven gate is in its line")
def _():
    works = {"moat": {"kind": "moat", "stage": "done", "gate": "shut", "gate_test": "testing"}}
    props, _ = run(state(works))
    c = [p for p in props if p.rule == "waterworks_check"]
    assert c and "emergency gate test" in c[0].reason, props
    works = {"moat": {"kind": "moat", "stage": "done", "gate": "shut", "lever_name": "AI moat",
                      "gate_proven": {"tick": 5, "stage": "done", "at": {"x": 50, "y": 52, "e": -1}}}}
    props, notes = run(state(works))
    assert not [p for p in props if p.rule == "waterworks_check"], props      # proven and shut: nothing to do
    assert any("emergency gate proven" in n and "AI moat" in n and "x50 y52" in n for n in notes), notes
    works = {"moat": {"kind": "moat", "stage": "done", "gate": "open"}}
    c = [p for p in run(state(works))[0] if p.rule == "waterworks_check"]
    assert c and "leak check" in c[0].reason            # open: the step (the bridge begins the test if unproven)


@test("R29 W3: the cistern's proven emergency gate is in the water notes")
def _():
    import planner_wells_water as pww
    s = state()
    s["water"] = {"bodies": [], "cistern_status": {"stage": "done", "gate": "shut",
                                                   "gate_proven": {"stage": "hole", "depth": 6,
                                                                   "at": {"x": 10, "y": 11, "e": 29}}}}
    props, notes = [], []
    try:
        pww._water_rules(s, PLANNER_CONFIG, props, notes)
    except Exception:
        pass        # other rules on a thin state: only the note is looked at
    assert any("cistern's emergency gate proven" in n and "x10 y11" in n for n in notes), notes


# --- the Lua's text (the PC runner runs the Lua itself below, with lupa) -----------------

@test("R29 W3 text: the report says which pieces wait and the reserved parts; the step resets the planners' dry runs")
def _():
    t = lua("ai-waterworks-steps.lua")
    assert "row.build_wait = #left > 0 and left or nil" in t
    assert "row.floodgates_reserved, row.mechanisms_reserved" in t and "count_items('HATCH_COVER')" in t
    assert "row.magma_parts = magma_parts()" in t
    i = t.index("dry_reset()")
    assert i < t.index("PLANNERS[kind]()")
    assert "gate_proven = type(wk.gate_proven) == 'table'" in t and "emergency gate proven" in t
    p = lua("ai-waterworks-plans.lua")
    assert p.count("dry_try(p)") >= 4 and "function moat_sides(e)" in p
    assert "wet_only" in p and "blocked_why" in p
    assert len((LUA_DIR / "ai-waterworks-plans.lua").read_bytes()) < 60 * 1024
    assert len((LUA_DIR / "ai-waterworks-steps.lua").read_bytes()) < 60 * 1024
    assert len((LUA_DIR / "ai-waterworks.lua").read_bytes()) < 60 * 1024


@test("R29 W3 text: the cistern takes the survey's plan when it fits, else searches a level a call")
def _():
    c = lua("ai-builder-cistern.lua")
    assert "function cistern_plan_valid(p)" in c
    st = lua("ai-builder-cistern-step.lua")
    assert st.index("cistern_plan_valid") < st.index("plan_cistern, first, last")
    assert "CISTERN_SEARCH = S" in st and "searching = true" in st and "gate_proven" in st
    assert "gate_proven = type(d.gate_proven)" in lua("ai-builder-cistern-status.lua")
    for f in ("ai-builder-cistern.lua", "ai-builder-cistern-step.lua", "ai-builder-cistern-status.lua"):
        assert len((LUA_DIR / f).read_bytes()) < 60 * 1024, f


# --- the Lua on the fake map (lupa) ------------------------------------------------------

def _tw():
    if not have_lua():
        skip("needs lupa")
    import test_waterworks as TW  # noqa: E402  (its fake map)
    return TW


@test("R29 W3 lua: D's gate scanned at its stair's foot: the moat finds the open ground one level up")
def _():
    TW = _tw()
    env, W = TW.moat_world()
    # the gate's tile one level down (z 99, inside), a stair up to the ground's level
    for x in range(48, 53):
        for y in range(48, 53):
            W.set(x, y, 99, TW.T(shape="FLOOR", outside=False))
    W.set(50, 50, 99, TW.T(shape="STAIR_UP", outside=False))
    W.set(50, 50, 100, TW.T(shape="STAIR_DOWN", outside=False))
    W.entrances = TW.L(TW.T(x=50, y=50, z=99, id=1))
    sides = env.moat_sides(TW.T(x=50, y=50, z=99))
    assert len(sides) >= 1 and sides[1].z == 100, [dict(v) for v in sides.values()]
    # the same gate with no way up: still refused, now saying so
    env2, W2 = TW.moat_world()
    W2.set(50, 50, 99, TW.T(shape="FLOOR", outside=False))
    W2.entrances = TW.L(TW.T(x=50, y=50, z=99, id=1))
    r = TW.step(env2, "moat")
    assert r.rejected and "no open ground outside it" in r.error, dict(r)


@test("R29 W3 lua: a site whose dry run is refused (a zone in the way) lets the irrigation planner try the next")
def _():
    TW = _tw()
    env, W = TW.irrigation_world()
    r = TW.step(env, "irrigation", dry_run=True)
    assert r.ok, dict(r)
    first = r.plan.room
    # a bedroom zone on the first site's room: refused there, another site taken
    W.occ = TW.T(**{f"{first.x1 + 1},{first.y1 + 1},{first.z}": "a building (civzone)"})
    r2 = TW.step(env, "irrigation", dry_run=True)
    if r2.ok:
        room = r2.plan.room
        assert (room.x1, room.y1) != (first.x1, first.y1), (dict(room), dict(first))
    else:
        assert "civzone" in r2.error, dict(r2)         # no other site on this small map: said why


@test("R29 W3 lua: the moat's emergency gate proven at the leak test's shut, a done moat test-shut and opened again")
def _():
    TW = _tw()
    env, W = TW.moat_world()
    step = lambda **kw: TW.step(env, "moat", **kw)  # noqa: E731
    assert step().stage == "planned"
    step()
    wk = W.saved["ai-overseer/waterworks"].works.moat
    W.dig_all(wk.plan.dig)
    step()
    W.dig_all(wk.plan.dig2)
    step()
    W.build_all()
    assert step().stage == "linking"
    assert step().stage == "filling"
    gate = env.building(wk.plan.gate.x, wk.plan.gate.y, wk.plan.gate.z, "Floodgate")
    assert step().plug_dug and not gate.closed
    W.set(50, 54, 99, TW.T(liquid=True, depth=5, shape="RAMP"))
    step()                                                     # seen open: noted
    wk = W.saved["ai-overseer/waterworks"].works.moat
    assert wk.gate_seen_open and not wk.gate_proven
    assert step().stage == "done"
    r = step()                                                 # the test: shut by its lever
    assert r.waiting and "emergency gate test" in r.error and gate.closed, dict(r)
    wk = W.saved["ai-overseer/waterworks"].works.moat
    assert wk.gate_test
    n = len(W.pulls)
    r = step()                                                 # seen shut: proven, opened again
    wk = W.saved["ai-overseer/waterworks"].works.moat
    assert wk.gate_proven and wk.gate_proven.stage == "done", dict(r)
    assert r.gate_test == "passed" and len(W.pulls) == n + 1 and not W.pulls[n + 1].instant
    rep = env.report().works.moat
    assert rep.gate_proven and rep.lever_name == "AI moat" and rep.gate_test is None
    r = step()
    assert r.waiting and "is done" in r.error                 # proven: no second test


@test("R29 W3 lua: a gate that never shuts under the test: held, the test failed (the brain retires it)")
def _():
    TW = _tw()
    env, W = TW.moat_world()
    step = lambda **kw: TW.step(env, "moat", **kw)  # noqa: E731
    step(); step()
    wk = W.saved["ai-overseer/waterworks"].works.moat
    W.dig_all(wk.plan.dig); step(); W.dig_all(wk.plan.dig2); step(); W.build_all(); step(); step()
    step()
    W.set(50, 54, 99, TW.T(liquid=True, depth=5, shape="RAMP"))
    step(); step()
    env.pull = lambda *a: True                                 # the lever does nothing
    gate = env.building(wk.plan.gate.x, wk.plan.gate.y, wk.plan.gate.z, "Floodgate")
    r = step()
    assert "emergency gate test" in r.error and not gate.closed
    W.tick = W.tick + (env.FILL_STALL_DAYS + 1) * 1200
    r = step()
    assert r.stage == "held" and "emergency gate test failed" in r.error, dict(r)
    assert env.report().works.moat.gate_test == "failed"


if __name__ == "__main__":
    finish()
