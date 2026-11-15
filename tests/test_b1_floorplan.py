"""Tests for lua/ai-floorplan.lua (layout B: the floor record), run in a real
Lua engine (pip install lupa).

    python tests/test_b1_floorplan.py

The placements are hand-written in the shape ai-floorplace.place answers. The
two of the design's worked example come first: a hub run east from the stair,
four bedrooms (hall 0 -> 10 columns), then a Masons' shop with its stone pile
(hall 10 -> 23 columns).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402

try:
    import lupa  # noqa: F401
    from lupa.lua53 import LuaRuntime, lua_type
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

try:
    sys.path.insert(0, str(ROOT / "brain" / "tools"))
    from draw_level import render as _render
except Exception:                                   # the helper is optional
    _render = None

SRC = (ROOT / "lua" / "ai-floorplan.lua").read_text(encoding="utf-8")
LUA = LuaRuntime(unpack_returned_tuples=True)
LOAD = LUA.eval("function(src) local env = setmetatable({}, {__index=_G}); "
                "assert(load(src, 'ai-floorplan', 't', env))(); return env end")
M = LOAD(SRC)
DEEP_EQ = LUA.eval("""function(a, b)
  local function eq(x, y)
    if type(x) ~= type(y) then return false end
    if type(x) ~= 'table' then return x == y end
    for k, v in pairs(x) do if not eq(v, y[k]) then return false end end
    for k in pairs(y) do if x[k] == nil then return false end end
    return true
  end
  return eq(a, b)
end""")
SAME = LUA.eval("function(a, b) return rawequal(a, b) end")      # the very same table
DAY = 1200


# ---------------------------------------------------------------- Python <-> Lua

def to_lua(v):
    if isinstance(v, dict):
        t = LUA.table()
        for k, x in v.items():
            t[k] = to_lua(x)
        return t
    if isinstance(v, (list, tuple)):
        t = LUA.table()
        for i, x in enumerate(v, 1):
            t[i] = to_lua(x)
        return t
    return v


def to_py(v, path="store"):
    """A Lua value as JSON would hold it. Fails on anything JSON cannot: a
    function, a table that mixes keys, a list with a hole."""
    if lua_type(v) == "table":
        keys = list(v.keys())
        if not keys:
            return []
        if all(isinstance(k, int) for k in keys):
            assert sorted(keys) == list(range(1, len(keys) + 1)), f"{path}: a sparse list {sorted(keys)}"
            return [to_py(v[i], f"{path}[{i}]") for i in range(1, len(keys) + 1)]
        assert all(isinstance(k, str) for k in keys), f"{path}: mixed keys {keys}"
        return {k: to_py(v[k], f"{path}.{k}") for k in keys}
    assert lua_type(v) is None, f"{path}: a {lua_type(v)}"
    assert v is None or isinstance(v, (bool, int, float, str)), f"{path}: {type(v)}"
    if isinstance(v, float) and v == int(v):
        return int(v)
    return v


def call(fn, *args):
    """A Lua call's results as a tuple."""
    res = fn(*args)
    return res if isinstance(res, tuple) else (res,)


def tiles_of(floor):
    out = set()
    for x, col in M.claims(floor).items():
        for y in col.keys():
            out.add((int(x), int(y)))
    return out


def draw(tiles) -> str:
    if _render is None:
        return f"{len(tiles)} tiles"
    try:
        return "\n" + _render({"cells": sorted(tiles), "stair": (0, 0)})
    except Exception:
        return f"{len(tiles)} tiles"


# ---------------------------------------------------------------- placements

def put(run, side, u, w, d, role="room", flag=None, axial=False, unit=1, rect=None):
    p = {"unit": unit, "run": run, "side": side, "u": u, "w": w, "d": d, "axial": axial, "role": role,
         "T": {"a": 1, "b": 0, "c": 0, "d": 1, "tx": 0, "ty": 0}}
    if flag:
        p["flag"] = flag
    if rect:
        p["rect"] = rect
    return p


def run_row(rid, len_before, length, new=False, parent=0, ox=0, oy=0, dx=1, dy=0, tag="homes", node=3,
            neck=False, walked=0):
    return {"id": rid, "new": new, "parent": parent, "ox": ox, "oy": oy, "dx": dx, "dy": dy,
            "len_before": len_before, "len": length, "walked": walked, "tag": tag, "node": node, "neck": neck}


def placement(req, puts, runs, hall=(), floor_id=1, new_floor=False):
    return to_lua({"floor_id": floor_id, "new_floor": new_floor, "req": req, "puts": puts, "runs": runs,
                   "hall": [{"x": x, "y": y} for x, y in hall], "hall_rects": [], "statues": [],
                   "tiles": 0, "hall_new": len(hall)})


HUB = [(x, y) for x in (-1, 0, 1) for y in (-1, 0, 1) if (x, y) != (0, 0)]


def bedrooms_placement():
    """Request 1: four bedrooms w3 d3, facing each other at u = 4 and u = 8; the hall dug to column 11."""
    hall = HUB + [(x, y) for x in range(2, 12) for y in (-1, 0, 1)]
    return placement({"kind": "bedrooms", "tag": "homes"},
                     [put(1, -1, 4, 3, 3, unit=1), put(1, 1, 4, 3, 3, unit=2),
                      put(1, -1, 8, 3, 3, unit=3), put(1, 1, 8, 3, 3, unit=4)],
                     [run_row(1, 0, 10, new=True)], hall, new_floor=True)


def masons_placement():
    """Request 2: the stone pile at u = 13 and the shop at u = 19, north; the hall lengthened to column 24."""
    hall = [(x, y) for x in range(12, 25) for y in (-1, 0, 1)]
    return placement({"kind": "workshops", "tag": "industry", "group": "crafts"},
                     [put(1, -1, 13, 5, 5, role="pile", flag="stone", unit=1),
                      put(1, -1, 19, 5, 5, role="shop", unit=2)],
                     [run_row(1, 10, 23)], hall)


def worked(pid1=41, pid2=42):
    """A store holding the worked example's floor."""
    store = M.new_store()
    floor = M.new_floor(store, 152, 96, 101, 1000)
    floor = M.commit(store, floor, bedrooms_placement(), pid1, 1000)
    assert floor is not None
    if pid2 is not None:
        assert M.commit(store, floor, masons_placement(), pid2, 2000) is not None
    return store, floor


def turn_placement(pid_tag="homes", node=3, rid=2, parent=1, at=20):
    """A run turning south off run 1's column `at`, with one room on it."""
    u0 = 3 if node == 5 else 2
    return placement({"kind": "bedrooms", "tag": pid_tag},
                     [put(rid, -1, u0 + 2, 3, 3)],
                     [run_row(rid, 0, 6, new=True, parent=parent, ox=at, oy=0, dx=0, dy=1, tag=pid_tag, node=node)],
                     [(at + v, y) for y in range(u0, u0 + 6) for v in (-1, 0, 1)])


def arm_placement(rid=3, tag="industry", neck=False, length=8):
    """A second hub arm, going west, with one room on it."""
    return placement({"kind": "storage", "tag": tag},
                     [put(rid, 1, 5, 3, 2)],
                     [run_row(rid, 0, length, new=True, dx=-1, dy=0, tag=tag, neck=neck)],
                     [(-x, y) for x in range(2, 2 + length) for y in (-1, 0, 1)])


# ---------------------------------------------------------------- 1. migrate

@test("migrate: nil and {} give a new v1 store")
def _():
    for junk in (None, LUA.table()):
        store, changed, why = call(M.migrate, junk)
        assert changed is True and why == "new", (changed, why)
        assert to_py(store) == {"v": 1, "next": 1, "fallbacks": 0, "floors": []}


@test("migrate: junk never throws and becomes a new store")
def _():
    for junk in ("floors", 7, True, to_lua({"v": "1"}), to_lua({"v": 0}), to_lua({"v": 1.5}),
                 to_lua({"floors": [1, 2]}), to_lua([1, 2, 3]), to_lua({"v": -3, "floors": "x"})):
        store, changed, why = call(M.migrate, junk)
        assert changed is True and why in ("junk", "new"), (junk, changed, why)
        assert store.v == 1 and len(store.floors) == 0 and store.next == 1 and store.fallbacks == 0


@test("migrate: a v1 store comes back the same table, unchanged")
def _():
    store, _floor = worked()
    before = json.dumps(to_py(store), sort_keys=True)
    out, changed, why = call(M.migrate, store)
    assert changed is False and why is None
    assert SAME(out, store) and json.dumps(to_py(out), sort_keys=True) == before
    out, changed, why = call(M.migrate, M.new_store())
    assert changed is False


@test("migrate: a newer store is not touched (changed false, why 'newer')")
def _():
    newer = to_lua({"v": 99, "floors": "whatever the future holds", "x": {"y": 1}})
    before = json.dumps(to_py(newer), sort_keys=True)
    out, changed, why = call(M.migrate, newer)
    assert changed is False and why == "newer"
    assert json.dumps(to_py(out), sort_keys=True) == before


@test("migrate: a v1 store that lost a part is mended (junk rows dropped, next past the ids)")
def _():
    broken = to_lua({"v": 1, "floors": [{"id": 4, "z": 10, "stair": {"x": 1, "y": 2}}, "junk", {"z": 3}]})
    out, changed, why = call(M.migrate, broken)
    assert changed is True and why == "repaired"
    py = to_py(out)
    assert py["next"] == 5 and py["fallbacks"] == 0 and len(py["floors"]) == 1
    assert py["floors"][0]["runs"] == [] and py["floors"][0]["slots"] == []
    assert call(M.migrate, out)[1] is False, "a mended store is a good store"
    out, changed, why = call(M.migrate, to_lua({"v": 1}))
    assert changed is True and to_py(out) == {"v": 1, "next": 1, "fallbacks": 0, "floors": []}


# ---------------------------------------------------------------- 2. new_floor, ids

@test("new_floor does not insert and does not move next; commit does both")
def _():
    store = M.new_store()
    floor = M.new_floor(store, 152, 96, 101, 1000)
    assert floor.id == 1 and floor.z == 152 and floor.stair.x == 96 and floor.stair.y == 101
    assert floor.made == 1000 and floor.hub == "found"
    assert len(floor.runs) == 0 and len(floor.slots) == 0
    assert len(store.floors) == 0 and store.next == 1
    assert M.find_floor(store, 152, 96, 101) is None
    again = M.new_floor(store, 152, 96, 101, 1000)
    assert again.id == 1, "still the same next id"
    out = M.commit(store, floor, bedrooms_placement(), 41, 1000)
    assert SAME(out, floor) and len(store.floors) == 1 and store.next == 2
    assert SAME(M.find_floor(store, 152, 96, 101), floor)
    assert M.find_floor(store, 152, 96, 102) is None and M.find_floor(store, 151, 96, 101) is None
    assert SAME(M.find_floor(store, 152), floor), "with no stair given: the level's floor"


@test("two floors get different ids, also when both were made before either was committed")
def _():
    store = M.new_store()
    a = M.new_floor(store, 152, 96, 101, 1)
    b = M.new_floor(store, 151, 96, 101, 1)
    assert a.id == b.id == 1
    M.commit(store, a, bedrooms_placement(), 41, 1)
    M.commit(store, b, bedrooms_placement(), 42, 1)
    assert (a.id, b.id) == (1, 2) and store.next == 3 and len(store.floors) == 2
    c = M.new_floor(store, 150, 96, 101, 1)
    assert c.id == 3
    M.mark_full(store, c, "*", 5)
    assert store.next == 4 and [f.id for f in store.floors.values()] == [1, 2, 3]


@test("commit on a second table for a floor already in the store writes into the store's record")
def _():
    store, floor = worked(pid2=None)
    twin = M.new_floor(store, 152, 96, 101, 3000)
    out = M.commit(store, twin, masons_placement(), 42, 3000)
    assert SAME(out, floor) and len(store.floors) == 1 and len(floor.slots) == 6 and store.next == 2


# ---------------------------------------------------------------- 3. commit

@test("commit: the worked example's first placement (run, slots, len, hub)")
def _():
    store, floor = worked(pid2=None)
    py = to_py(floor)
    assert py["hub"] == "dug", "the hall held the hub's tiles"
    assert len(py["runs"]) == 1
    run = py["runs"][0]
    for k, v in {"id": 1, "parent": 0, "ox": 0, "oy": 0, "dx": 1, "dy": 0, "len": 10, "walked": 0,
                 "tag": "homes", "node": 3, "neck": False}.items():
        assert run[k] == v, (k, run)
    assert "closed" not in run
    assert run["grew"] == {"41": 0}
    assert [(s["run"], s["side"], s["u"], s["w"], s["d"]) for s in py["slots"]] == \
        [(1, -1, 4, 3, 3), (1, 1, 4, 3, 3), (1, -1, 8, 3, 3), (1, 1, 8, 3, 3)]
    for s in py["slots"]:
        assert s["pid"] == 41 and s["kind"] == "bedrooms" and s["tag"] == "homes" and s["role"] == "room"
        assert "group" not in s and "flag" not in s and "dead" not in s


@test("commit: the second placement lengthens the run and touches nothing of the first")
def _():
    store, floor = worked(pid2=None)
    first = to_py(floor)["slots"]
    M.commit(store, floor, masons_placement(), 42, 2000)
    py = to_py(floor)
    assert len(py["runs"]) == 1 and py["runs"][0]["len"] == 23 and py["runs"][0]["tag"] == "homes"
    assert py["runs"][0]["grew"] == {"41": 0, "42": 10}
    assert py["slots"][:4] == first
    pile, shop = py["slots"][4], py["slots"][5]
    assert (pile["u"], pile["w"], pile["d"], pile["role"], pile["flag"]) == (13, 5, 5, "pile", "stone")
    assert (shop["u"], shop["w"], shop["d"], shop["role"]) == (19, 5, 5, "shop") and "flag" not in shop
    for s in (pile, shop):
        assert s["pid"] == 42 and s["kind"] == "workshops" and s["tag"] == "industry" and s["group"] == "crafts"
    assert py["hub"] == "dug" and len(store.floors) == 1


@test("commit: a hall with no hub tile leaves the hub 'found' on a new floor, and 'dug' where it was")
def _():
    store = M.new_store()
    floor = M.new_floor(store, 152, 96, 101, 1)
    pl = placement({"kind": "bedrooms", "tag": "homes"}, [put(1, -1, 4, 3, 3)],
                   [run_row(1, 0, 6, new=True, walked=2)], [(x, y) for x in range(4, 8) for y in (-1, 0, 1)])
    M.commit(store, floor, pl, 41, 1)
    assert floor.hub == "found" and floor.runs[1].walked == 2
    store2, floor2 = worked()
    assert floor2.hub == "dug"


@test("commit: a third placement with a new turning run, then a new hub arm")
def _():
    store, floor = worked()
    M.commit(store, floor, turn_placement(), 43, 3000)
    M.commit(store, floor, arm_placement(), 44, 4000)
    py = to_py(floor)
    assert [r["id"] for r in py["runs"]] == [1, 2, 3]
    turn, arm = py["runs"][1], py["runs"][2]
    assert (turn["parent"], turn["ox"], turn["oy"], turn["dx"], turn["dy"], turn["len"]) == (1, 20, 0, 0, 1, 6)
    assert turn["grew"] == {"43": 0} and turn["pid"] == 43
    assert (arm["parent"], arm["dx"], arm["dy"], arm["len"], arm["tag"]) == (0, -1, 0, 8, "industry")
    assert py["runs"][0]["len"] == 23, "run 1 untouched"
    assert [s["run"] for s in py["slots"]] == [1, 1, 1, 1, 1, 1, 2, 3]


@test("commit: an axial put closes its run")
def _():
    store, floor = worked()
    pl = placement({"kind": "dining", "tag": "homes"},
                   [put(1, -1, 26, 9, 7, role="hall", axial=True, rect={"x1": 26, "y1": -4, "x2": 33, "y2": 4})],
                   [run_row(1, 23, 24)], [(25, -1), (25, 0), (25, 1)])
    M.commit(store, floor, pl, 45, 5000)
    assert floor.runs[1].closed == "terminus" and floor.runs[1].len == 24
    slot = to_py(floor.slots[7])
    assert slot["axial"] is True and slot["role"] == "hall" and slot["rect"] == {"x1": 26, "y1": -4, "x2": 33, "y2": 4}
    assert all(not to_py(floor.slots[i]).get("axial") for i in range(1, 7))


@test("commit: a bad placement is refused and nothing changes")
def _():
    store, floor = worked()
    before = json.dumps(to_py(store), sort_keys=True)
    bad = [
        placement({"kind": "bedrooms", "tag": "homes"}, [put(9, -1, 4, 3, 3)], [run_row(1, 23, 30)]),   # no run 9
        placement({"kind": "bedrooms", "tag": "homes"}, [put(2, 0, 4, 3, 3)],
                  [run_row(2, 0, 6, new=True, parent=1, dx=0, dy=1)]),                                 # no side
        placement({"kind": "bedrooms", "tag": "homes"}, [put(2, 1, 4, 3, 3)],
                  [run_row(2, 0, 6, new=True, parent=1, dx=1, dy=1)]),                                 # no direction
    ]
    for pl in bad:
        out, why = call(M.commit, store, floor, pl, 50, 9)
        assert out is None and why.startswith("bad placement"), why
        assert json.dumps(to_py(store), sort_keys=True) == before
    assert call(M.commit, store, floor, None, 50, 9)[0] is None
    assert call(M.commit, None, floor, masons_placement(), 50, 9)[0] is None


# ---------------------------------------------------------------- 4. release

@test("release: the slots are dead and kept; the run's len rolls back")
def _():
    store, floor = worked()
    n = M.release(store, 42)
    assert n == 2
    py = to_py(floor)
    assert len(py["slots"]) == 6
    assert [bool(s.get("dead")) for s in py["slots"]] == [False] * 4 + [True, True]
    assert py["slots"][4]["u"] == 13 and py["slots"][4]["pid"] == 42, "a dead slot keeps its place"
    assert py["runs"][0]["len"] == 10 and "closed" not in py["runs"][0]
    assert py["runs"][0]["grew"] == {"41": 0}
    assert M.release(store, 42) == 0, "a second release marks nothing more"
    assert to_py(floor)["runs"][0]["len"] == 10


@test("release: never below what another project's live slot needs")
def _():
    store, floor = worked()
    assert M.release(store, 41) == 4
    py = to_py(floor)
    assert py["runs"][0]["len"] == 23, "the shop at u 19 w 5 needs column 24"
    assert "closed" not in py["runs"][0], "the run holds another project's live slots"
    # the same with a slot nearer the stair: column u + w - 1 + 1
    store = M.new_store()
    floor = M.commit(store, M.new_floor(store, 1, 0, 0, 1),
                     placement({"kind": "a", "tag": "t"}, [put(1, -1, 4, 3, 3)], [run_row(1, 0, 6, new=True)]), 1, 1)
    M.commit(store, floor, placement({"kind": "b", "tag": "t"}, [put(1, 1, 5, 4, 3), put(1, -1, 20, 3, 3)],
                                     [run_row(1, 6, 22)]), 2, 2)
    M.commit(store, floor, placement({"kind": "c", "tag": "t"}, [put(1, 1, 30, 3, 3)], [run_row(1, 22, 32)]), 3, 3)
    M.release(store, 3)
    assert floor.runs[1].len == 22
    M.release(store, 1)
    assert floor.runs[1].len == 22, "project 2's slot at u 20 w 3 needs column 23"
    M.release(store, 2)
    assert floor.runs[1].len == 0, "nothing live is left: back to what the first project found"
    assert floor.runs[1].closed == "released" or floor.runs[1].closed is None


@test("release: the first project released while the second lives, then the second: the hall goes all the way back")
def _():
    store, floor = worked()
    M.release(store, 41)
    assert floor.runs[1].len == 23
    M.release(store, 42)
    assert floor.runs[1].len == 0
    assert all(s.dead for s in floor.slots.values()) and len(floor.slots) == 6


@test("release: a run made by the project is closed; one that holds another's live slot is not")
def _():
    store, floor = worked()
    M.commit(store, floor, turn_placement(), 43, 3000)
    assert M.release(store, 43) == 1
    turn = to_py(floor)["runs"][1]
    assert turn["closed"] == "released" and turn["len"] == 0
    assert floor.runs[1].len == 23 and floor.runs[1].closed is None
    # a turning run another project has a room on
    store, floor = worked()
    M.commit(store, floor, turn_placement(), 43, 3000)
    M.commit(store, floor, placement({"kind": "bedrooms", "tag": "homes"}, [put(2, 1, 8, 3, 3)],
                                     [run_row(2, 6, 10, parent=1, ox=20, dx=0, dy=1)]), 44, 4000)
    M.release(store, 43)
    turn = to_py(floor)["runs"][1]
    assert "closed" not in turn and turn["len"] == 10


@test("release: a run is kept long enough for a run that turns off it")
def _():
    store, floor = worked()
    M.commit(store, floor, turn_placement(at=20), 43, 3000)
    M.release(store, 42)             # the Masons' project lengthened run 1 from 10 to 23
    assert floor.runs[1].len == 20, "the turn at column 20 needs columns to 21"
    M.release(store, 43)
    assert floor.runs[2].closed == "released"


@test("release: walked columns stay in len")
def _():
    store = M.new_store()
    floor = M.new_floor(store, 1, 0, 0, 1)
    M.commit(store, floor, placement({"kind": "a", "tag": "t"}, [put(1, -1, 6, 3, 3)],
                                     [run_row(1, 0, 9, new=True, walked=4)]), 1, 1)
    M.release(store, 1)
    assert floor.runs[1].len == 4 and floor.runs[1].closed == "released"


@test("release: an unknown id returns 0 and changes nothing")
def _():
    store, floor = worked()
    before = json.dumps(to_py(store), sort_keys=True)
    for pid in (999, "x", None):
        assert M.release(store, pid) == 0
    assert M.release(None, 41) == 0 and M.release(to_lua({"v": 1}), 41) == 0
    assert json.dumps(to_py(store), sort_keys=True) == before


@test("release: an axial project released leaves its run closed (the end stays taken)")
def _():
    store, floor = worked()
    pl = placement({"kind": "dining", "tag": "homes"},
                   [put(1, -1, 26, 9, 7, role="hall", axial=True)], [run_row(1, 23, 24)], [(25, 0)])
    M.commit(store, floor, pl, 45, 5000)
    assert M.release(store, 45) == 1
    assert floor.runs[1].closed == "terminus" and floor.runs[1].len == 23


# ---------------------------------------------------------------- 5. mark_full

@test("mark_full on a new floor: a '*' record with no runs")
def _():
    store = M.new_store()
    floor = M.new_floor(store, 140, 96, 101, 7)
    out = M.mark_full(store, floor, "*", 5000, to_lua({"north": 0, "east": 3, "south": 0, "west": 7}))
    assert SAME(out, floor) and len(store.floors) == 1 and store.next == 2
    py = to_py(floor)
    assert py["full"] == {"*": 5000} and py["runs"] == [] and py["slots"] == []
    assert py["free"] == {"north": 0, "east": 3, "south": 0, "west": 7, "tick": 5000}
    assert SAME(M.find_floor(store, 140, 96, 101), floor)
    M.mark_full(store, M.new_floor(store, 140, 96, 101, 9), "*", 6000)
    assert len(store.floors) == 1 and floor.full["*"] == 6000, "the same level is not inserted twice"
    assert to_py(floor)["free"]["tick"] == 5000, "no new measure given: the old one is kept"


@test("mark_full on a known floor; commit clears the tag's mark")
def _():
    store, floor = worked()
    M.mark_full(store, floor, "homes", 7000, to_lua({"north": 0, "east": 36, "south": 59, "west": 13}))
    M.mark_full(store, floor, "industry", 7100)
    py = to_py(floor)
    assert py["full"] == {"homes": 7000, "industry": 7100} and len(store.floors) == 1
    assert py["free"] == {"north": 0, "east": 36, "south": 59, "west": 13, "tick": 7000}
    M.commit(store, floor, placement({"kind": "bedrooms", "tag": "homes"}, [put(1, 1, 13, 3, 3)],
                                     [run_row(1, 23, 23)]), 46, 8000)
    assert to_py(floor)["full"] == {"industry": 7100}


@test("a '*' floor that gets a hall after all loses its '*' mark")
def _():
    store = M.new_store()
    floor = M.new_floor(store, 140, 96, 101, 7)
    M.mark_full(store, floor, "*", 5000)
    M.commit(store, floor, bedrooms_placement(), 41, 6000)
    assert to_py(floor)["full"] == [] and len(store.floors) == 1


# ---------------------------------------------------------------- 6. claims

@test("claims: the worked example (hub, hall columns 2..24, wall rows, rooms)")
def _():
    _store, floor = worked()
    t = tiles_of(floor)
    assert (0, 0) not in t, "never the stair"
    for xy in HUB:
        assert xy in t
    for x in range(2, 25):
        for y in (-1, 0, 1):
            assert (x, y) in t, (x, y)
    assert (25, 0) not in t and (-2, 0) not in t
    # bedrooms: wall rows y = -2 / 2 and rooms to y = -5 / 5, x 4..6 and 8..10
    for x in (4, 5, 6, 8, 9, 10):
        for y in (-5, -4, -3, -2, 2, 3, 4, 5):
            assert (x, y) in t, (x, y)
    for xy in ((7, -3), (3, -2), (11, 2), (4, -6), (7, 2)):
        assert xy not in t, xy
    # the pile x 13..17 and the shop x 19..23, y -2 .. -7, north only
    for x in list(range(13, 18)) + list(range(19, 24)):
        for y in range(-7, -1):
            assert (x, y) in t, (x, y)
        assert (x, 2) not in t
    assert (18, -4) not in t and (12, -3) not in t and (13, -8) not in t
    assert len(t) == 8 + 69 + 4 * 12 + 2 * 30, draw(t)


@test("claims: dead slots are still claimed")
def _():
    store, floor = worked()
    before = tiles_of(floor)
    M.release(store, 42)
    after = tiles_of(floor)
    assert (15, -5) in after and (21, -7) in after
    assert before - after == {(x, y) for x in range(12, 25) for y in (-1, 0, 1)}, "only the hall went back"


@test("claims: a turned run (its node on the parent's hall, its hall and its slot turned)")
def _():
    store, floor = worked()
    base = tiles_of(floor)
    M.commit(store, floor, turn_placement(at=20), 43, 3000)
    new = tiles_of(floor) - base
    # run 2: origin (20, 0), south: p = (-1, 0), so side -1 is east. Hall u 2..7 -> y 2..7, x 19..21
    hall = {(x, y) for x in (19, 20, 21) for y in range(2, 8)}
    # the slot: side -1, u 4..6 -> y 4..6; wall v = -2 -> x 22; rooms v -3..-5 -> x 23..25
    slot = {(x, y) for x in (22, 23, 24, 25) for y in (4, 5, 6)}
    assert new == hall | slot, draw(tiles_of(floor))


@test("claims: a 5x5 node and its hall from u0 = 3")
def _():
    store, floor = worked()
    base = tiles_of(floor)
    M.commit(store, floor, turn_placement(at=20, node=5), 43, 3000)
    assert floor.runs[2].node == 5
    new = tiles_of(floor) - base
    node = {(x, y) for x in range(18, 23) for y in range(-2, 3)} - base
    assert node == {(x, y) for x in range(18, 23) for y in (2,)} | {(x, -2) for x in (18,)}, sorted(node)
    hall = {(x, y) for x in (19, 20, 21) for y in range(3, 9)}
    slot = {(x, y) for x in (22, 23, 24, 25) for y in (5, 6, 7)}       # u 5..7
    assert new == node | hall | slot, draw(tiles_of(floor))


@test("claims: a neck's first column is one tile; a hub run never has a 5x5 node")
def _():
    store, floor = worked()
    base = tiles_of(floor)
    M.commit(store, floor, arm_placement(neck=True), 44, 4000)
    new = tiles_of(floor) - base
    hall = {(-2, 0)} | {(-x, y) for x in range(3, 10) for y in (-1, 0, 1)}
    # west: p = (0, -1), side +1 is north; u 5..7 -> x -5..-7; wall y -2, rooms y -3, -4
    slot = {(x, y) for x in (-5, -6, -7) for y in (-2, -3, -4)}
    assert new == hall | slot, draw(tiles_of(floor))
    store = M.new_store()
    floor = M.new_floor(store, 1, 0, 0, 1)
    M.commit(store, floor, placement({"kind": "a", "tag": "t"}, [], [run_row(1, 0, 4, new=True, node=5)]), 1, 1)
    assert floor.runs[1].node == 3 and (2, 0) in tiles_of(floor) and (-2, -2) not in tiles_of(floor)


@test("claims: an axial slot (its saved box; without one, w wide about the hall's axis)")
def _():
    store, floor = worked()
    base = tiles_of(floor)
    rect = {"x1": 26, "y1": -4, "x2": 33, "y2": 4}
    M.commit(store, floor, placement({"kind": "dining", "tag": "homes"},
                                     [put(1, -1, 26, 9, 7, role="hall", axial=True, rect=rect)],
                                     [run_row(1, 23, 24)], [(25, 0)]), 45, 5000)
    new = tiles_of(floor) - base
    box = {(x, y) for x in range(26, 34) for y in range(-4, 5)}
    assert new == box | {(25, -1), (25, 0), (25, 1)}
    floor.slots[7].rect = None
    assert tiles_of(floor) - base == box | {(25, -1), (25, 0), (25, 1)}, "the same box from u, w, d"


@test("claims: an empty or junk floor is the hub alone, or nothing")
def _():
    store = M.new_store()
    assert tiles_of(M.new_floor(store, 1, 0, 0, 1)) == set(HUB)
    assert len(list(M.claims(None).keys())) == 0


# ---------------------------------------------------------------- 7. summary

def rows(store, now=10 * DAY, retry=None, ez=None):
    ez = ez or LUA.eval("function(z) return z - 140 end")
    return [to_py(r, "row") for r in M.summary(store, ez, now, retry).values()]


@test("summary: the worked example's row, key by key")
def _():
    store, floor = worked()
    M.mark_full(store, floor, "homes", 9 * DAY, to_lua({"north": 0, "east": 36, "south": 59, "west": 13}))
    out = rows(store)
    assert len(out) == 1
    assert out[0] == {
        "id": 1, "elevation": 12, "z": 152, "stair": {"x": 96, "y": 101}, "hub": "dug", "no_hall": False,
        "width": 3, "rooms": 6, "hall": 69, "tags": ["homes", "industry"],
        "kinds": {"bedrooms": 4, "workshops": 1, "pile": 1}, "full": ["homes"],
        "free": {"north": 0, "east": 36, "south": 59, "west": 13, "tick": 9 * DAY},
        "arms": [{"dir": "east", "len": 23, "runs": 1, "tag": "homes", "slots": 6}],
    }, out[0]
    assert "others" not in out[0] and "old_boxes" not in out[0], "the caller adds those"


@test("summary: two arms and a turn (len, slots and runs summed over an arm's turnings)")
def _():
    store, floor = worked()
    M.commit(store, floor, turn_placement(at=20), 43, 3000)                       # run 2 off run 1
    M.commit(store, floor, arm_placement(rid=3), 44, 4000)                         # run 3, a west arm
    M.commit(store, floor, placement({"kind": "bedrooms", "tag": "homes"}, [put(4, 1, 4, 3, 3), put(4, -1, 4, 3, 3)],
                                     [run_row(4, 0, 7, new=True, parent=2, ox=20, oy=6, dx=1, dy=0)]), 47, 5000)
    row = rows(store)[0]
    assert row["arms"] == [
        {"dir": "east", "len": 23 + 6 + 7, "runs": 3, "tag": "homes", "slots": 6 + 1 + 2},
        {"dir": "west", "len": 8, "runs": 1, "tag": "industry", "slots": 1},
    ], row["arms"]
    assert row["hall"] == 3 * (23 + 6 + 7 + 8) and row["rooms"] == 10
    assert row["kinds"] == {"bedrooms": 7, "workshops": 1, "pile": 1, "storage": 1}
    assert row["tags"] == ["homes", "industry"]


@test("summary: compass words and a closed arm")
def _():
    store = M.new_store()
    floor = M.new_floor(store, 150, 5, 6, 1)
    dirs = [("north", 0, -1), ("south", 0, 1), ("east", 1, 0), ("west", -1, 0)]
    M.commit(store, floor, placement({"kind": "a", "tag": "t"}, [put(1, -1, 4, 3, 3, axial=True)],
                                     [run_row(i + 1, 0, 5, new=True, dx=dx, dy=dy, tag="t")
                                      for i, (_n, dx, dy) in enumerate(dirs)]), 1, 1)
    row = rows(store)[0]
    assert [a["dir"] for a in row["arms"]] == [n for n, _dx, _dy in dirs]
    assert row["arms"][0]["closed"] == "terminus" and "closed" not in row["arms"][1]
    assert row["elevation"] == 10 and row["hub"] == "found"


@test("summary: a '*' floor is a row with no arms and no_hall, until the mark is old")
def _():
    store = M.new_store()
    M.mark_full(store, M.new_floor(store, 140, 96, 101, 7), "*", 5 * DAY, to_lua({"east": 3, "west": 7}))
    row = rows(store, now=10 * DAY)[0]
    assert row["no_hall"] is True and row["arms"] == [] and row["rooms"] == 0 and row["hall"] == 0
    assert row["full"] == [] and row["tags"] == [] and row["kinds"] == [] and row["hub"] == "found"
    assert row["free"] == {"north": 0, "east": 3, "south": 0, "west": 7, "tick": 5 * DAY}
    assert rows(store, now=(5 + 28) * DAY - 1)[0]["no_hall"] is True
    assert rows(store, now=(5 + 28) * DAY)[0]["no_hall"] is False
    assert rows(store, now=8 * DAY, retry=3)[0]["no_hall"] is False
    assert rows(store, now=8 * DAY, retry=4)[0]["no_hall"] is True


@test("summary: full drops a mark older than retry_days")
def _():
    store, floor = worked()
    M.mark_full(store, floor, "homes", 10 * DAY)
    M.mark_full(store, floor, "industry", 30 * DAY)
    assert rows(store, now=31 * DAY)[0]["full"] == ["homes", "industry"]
    assert rows(store, now=38 * DAY - 1)[0]["full"] == ["homes", "industry"]
    assert rows(store, now=38 * DAY)[0]["full"] == ["industry"]
    assert rows(store, now=31 * DAY, retry=7)[0]["full"] == ["industry"]
    assert rows(store, now=100 * DAY)[0]["full"] == []
    assert rows(store, now=31 * DAY)[0]["no_hall"] is False


@test("summary: dead slots are not rooms (nor kinds, nor tags); the arm still counts them taken")
def _():
    store, floor = worked()
    M.release(store, 42)
    row = rows(store)[0]
    assert row["rooms"] == 4 and row["kinds"] == {"bedrooms": 4} and row["tags"] == ["homes"]
    assert row["hall"] == 30 and row["arms"] == [{"dir": "east", "len": 10, "runs": 1, "tag": "homes", "slots": 6}]


@test("summary: two floors in the store's order; an ez that throws, junk stores")
def _():
    store, _floor = worked()
    M.mark_full(store, M.new_floor(store, 140, 96, 101, 7), "*", 5 * DAY)
    out = rows(store)
    assert [(r["id"], r["z"], r["elevation"]) for r in out] == [(1, 152, 12), (2, 140, 0)]
    bad = rows(store, ez=LUA.eval("function(z) error('no map') end"))
    assert [r.get("elevation") for r in bad] == [None, None] and bad[0]["rooms"] == 6
    for junk in (None, "x", to_lua({"v": 1})):
        assert len(list(M.summary(junk, None, 0).values())) == 0
    assert len(list(M.summary(M.new_store(), None, 0).values())) == 0


# ---------------------------------------------------------------- 8. grammar

DEFAULTS = {"gap": 1, "kind_gap": 1, "lead": 2, "ahead": 1, "run_max": 30, "run_min": 10, "arms_max": 2,
            "dirs": ["east", "south", "west", "north"], "sides": "both", "stagger": 0, "bay": 0, "node": 3,
            "grow": ["arm", "turn"], "turns": "alternate", "balance": False, "axial": False, "neck": False,
            "tries": 24, "full_retry_days": 28, "pile_w": 5, "piles_new": 1}
RANGES = {"gap": (1, 4), "kind_gap": (0, 6), "lead": (0, 8), "ahead": (0, 3), "run_max": (12, 80),
          "arms_max": (1, 4), "stagger": (0, 6), "tries": (4, 60), "full_retry_days": (1, 336),
          "pile_w": (3, 11), "piles_new": (0, 3)}


def G(hint=None):
    return to_py(M.grammar(to_lua(hint) if isinstance(hint, (dict, list)) else hint), "G")


@test("grammar: the defaults from nil, {} and junk")
def _():
    for hint in (None, {}, "junk", 7, True, False, [1, 2]):
        assert G(hint) == DEFAULTS, hint


@test("grammar: each number's two edges are kept and what lies past them is clamped")
def _():
    for key, (lo, hi) in RANGES.items():
        assert G({key: lo})[key] == lo and G({key: hi})[key] == hi, key
        assert G({key: lo - 1})[key] == lo and G({key: hi + 1})[key] == hi, key
        assert G({key: -10 ** 9})[key] == lo and G({key: 10 ** 9})[key] == hi, key
    # run_min 4-30, and never past run_max
    assert G({"run_min": 4})["run_min"] == 4 and G({"run_min": 3})["run_min"] == 4
    assert G({"run_min": 30})["run_min"] == 30 and G({"run_min": 31})["run_min"] == 30
    assert G({"run_min": 30, "run_max": 12})["run_min"] == 12
    # bay: 0, or 3-6
    assert [G({"bay": b})["bay"] for b in (-1, 0, 1, 2, 3, 4, 6, 7)] == [0, 0, 3, 3, 3, 4, 6, 6]
    # node: 3 or 5
    assert [G({"node": n})["node"] for n in (0, 3, 4, 5, 9)] == [3, 3, 3, 5, 5]
    assert G({"gap": 2.4})["gap"] == 2 and G({"gap": 2.6})["gap"] == 3, "numbers are whole"


@test("grammar: wrong types fall back to the default")
def _():
    junk = {k: "many" for k in list(RANGES) + ["run_min", "bay", "node"]}
    junk.update({"sides": 3, "turns": ["left"], "balance": "yes", "axial": 1, "neck": "true",
                 "dirs": "east", "grow": 5})
    assert G(junk) == DEFAULTS
    assert G({"gap": True, "lead": {"a": 1}, "tries": float("nan"), "run_max": float("inf")}) == DEFAULTS
    assert G({"sides": "default", "turns": "sideways"}) == DEFAULTS


@test("grammar: words, lists and switches")
def _():
    for s in ("both", "one", "alternate"):
        assert G({"sides": s})["sides"] == s
    for t in ("left", "right", "alternate", "both"):
        assert G({"turns": t})["turns"] == t
    for key in ("balance", "axial", "neck"):
        assert G({key: True})[key] is True and G({key: False})[key] is False
    assert G({"dirs": ["west", "up", "west", 3, "north"]})["dirs"] == ["west", "north"]
    assert G({"dirs": ["up"]})["dirs"] == DEFAULTS["dirs"] and G({"dirs": []})["dirs"] == DEFAULTS["dirs"]
    assert G({"grow": ["turn"]})["grow"] == ["turn"]
    assert G({"grow": ["turn", "arm", "turn", "dig"]})["grow"] == ["turn", "arm"]
    assert G({"grow": ["dig"]})["grow"] == ["arm", "turn"]


@test("grammar: unknown keys are dropped; elevs, tag, group, zone, spine pass through untouched")
def _():
    hint = {"elevs": [12, 11, 13], "tag": "industry", "group": "crafts", "zone": "mid", "spine": {"x": 96, "y": 101},
            "pile_w": 7, "piles_new": 2, "bay": 4, "colour": "red", "run": 9, "v": 1}
    g = G(hint)
    assert g == DEFAULTS | {"elevs": [12, 11, 13], "tag": "industry", "group": "crafts", "zone": "mid",
                            "spine": {"x": 96, "y": 101}, "pile_w": 7, "piles_new": 2, "bay": 4}
    assert G({"tag": 5, "zone": "nowhere"})["tag"] == 5 and G({"zone": "nowhere"})["zone"] == "nowhere"
    lua_hint = to_lua({"dirs": ["west"], "elevs": [1]})
    out = M.grammar(lua_hint)
    assert SAME(out.elevs, lua_hint.elevs) and not SAME(out.dirs, lua_hint.dirs), "the lists G owns are its own"


@test("grammar: the contract's example hint comes through as sent")
def _():
    hint = {"elevs": [12, 11, 13], "tag": "industry", "group": "crafts", "zone": "mid",
            "spine": {"x": 96, "y": 101}, "dirs": ["east", "south"],
            "gap": 1, "kind_gap": 1, "lead": 2, "ahead": 1, "run_max": 30, "run_min": 10, "arms_max": 2,
            "sides": "both", "stagger": 0, "bay": 4, "node": 3, "grow": ["arm", "turn"], "turns": "alternate",
            "balance": False, "axial": False, "neck": False, "pile_w": 5, "piles_new": 1, "full_retry_days": 28}
    assert G(hint) == hint | {"tries": 24}


# ---------------------------------------------------------------- 9. the limits

@test("the limits are the contract's")
def _():
    assert (M.VERSION, M.FLOORS_MAX, M.SLOTS_MAX, M.RUNS_MAX) == (1, 60, 160, 24)


@test("FLOORS_MAX: the 61st floor is refused by commit and by mark_full, the store unchanged")
def _():
    # (F2) 60 floors that hold halls: a floor that is only a mark would make way (see test_f2_floor_record)
    store = M.new_store()
    for z in range(60):
        assert M.commit(store, M.new_floor(store, z, 0, 0, 1), bedrooms_placement(), 100 + z, 1) is not None
    assert len(store.floors) == 60 and store.next == 61
    before = json.dumps(to_py(store), sort_keys=True)
    extra = M.new_floor(store, 99, 0, 0, 1)
    out, why = call(M.commit, store, extra, bedrooms_placement(), 41, 1)
    assert out is None and why == "floor record full"
    out, why = call(M.mark_full, store, extra, "*", 1)
    assert out is None and why == "floor record full"
    assert json.dumps(to_py(store), sort_keys=True) == before and len(extra.slots) == 0
    # a floor already in the store still takes a placement
    assert M.commit(store, M.find_floor(store, 5, 0, 0), masons_placement(), 41, 2) is not None


@test("SLOTS_MAX: the placement that would pass 160 slots is refused, the store unchanged")
def _():
    store = M.new_store()
    floor = M.new_floor(store, 1, 0, 0, 1)
    M.commit(store, floor, placement({"kind": "a", "tag": "t"}, [put(1, -1, 4 + i, 1, 1) for i in range(158)],
                                     [run_row(1, 0, 200, new=True)]), 1, 1)
    before = json.dumps(to_py(store), sort_keys=True)
    out, why = call(M.commit, store, floor, placement({"kind": "a", "tag": "t"},
                                                      [put(1, 1, 4 + i, 1, 1) for i in range(3)],
                                                      [run_row(1, 200, 210)]), 2, 2)
    assert out is None and why == "floor record full"
    assert json.dumps(to_py(store), sort_keys=True) == before
    assert M.commit(store, floor, placement({"kind": "a", "tag": "t"}, [put(1, 1, 4, 1, 1), put(1, 1, 6, 1, 1)],
                                            [run_row(1, 200, 200)]), 2, 2) is not None
    assert len(floor.slots) == 160
    M.release(store, 1)
    out, why = call(M.commit, store, floor, placement({"kind": "a", "tag": "t"}, [put(1, 1, 9, 1, 1)], []), 3, 3)
    assert out is None and why == "floor record full", "dead slots still fill the record"


@test("RUNS_MAX: the 25th run is refused, the store unchanged")
def _():
    store = M.new_store()
    floor = M.new_floor(store, 1, 0, 0, 1)
    M.commit(store, floor, placement({"kind": "a", "tag": "t"}, [],
                                     [run_row(i, 0, 5, new=True, parent=max(0, i - 1)) for i in range(1, 25)]), 1, 1)
    assert len(floor.runs) == 24
    before = json.dumps(to_py(store), sort_keys=True)
    out, why = call(M.commit, store, floor, placement({"kind": "a", "tag": "t"}, [put(25, 1, 4, 3, 3)],
                                                      [run_row(25, 0, 5, new=True, parent=24)]), 2, 2)
    assert out is None and why == "floor record full"
    assert json.dumps(to_py(store), sort_keys=True) == before
    # lengthening a run it has is still fine
    assert M.commit(store, floor, placement({"kind": "a", "tag": "t"}, [put(3, 1, 4, 3, 3)],
                                            [run_row(3, 5, 9)]), 2, 2) is not None
    assert len(M.summary(store, None, 0)[1].arms) == 1 and M.summary(store, None, 0)[1].arms[1].runs == 24


# ---------------------------------------------------------------- 10. JSON

def busy_store():
    store, floor = worked()
    M.commit(store, floor, turn_placement(at=20, node=5), 43, 3000)
    M.commit(store, floor, arm_placement(neck=True), 44, 4000)
    M.commit(store, floor, placement({"kind": "dining", "tag": "homes"},
                                     [put(1, -1, 26, 9, 7, role="hall", axial=True,
                                          rect={"x1": 26, "y1": -4, "x2": 33, "y2": 4})],
                                     [run_row(1, 23, 24)], [(25, 0)]), 45, 5000)
    M.mark_full(store, floor, "homes", 6000, to_lua({"north": 0, "east": 36, "south": 59, "west": 13}))
    M.mark_full(store, M.new_floor(store, 140, 96, 101, 7), "*", 7000)
    M.release(store, 42)
    M.release(store, 43)
    store.fallbacks = 2
    store.last = to_lua({"tick": 7000, "ok": False, "kind": "dining", "elevation": 12, "why": "floor 1: no room"})
    return store


@test("the store round-trips through JSON unchanged (string keys or dense lists only)")
def _():
    store = busy_store()
    py = to_py(store)                       # fails on a function, a sparse list, mixed keys
    text = json.dumps(py)
    back = to_lua(json.loads(text))
    assert DEEP_EQ(store, back), "the store read back from JSON differs"
    assert to_py(back) == py
    out, changed, why = call(M.migrate, back)
    assert changed is False and why is None, "what was saved is a good v1 store"
    # and it still works as a store
    floor = M.find_floor(back, 152, 96, 101)
    assert floor is not None and tiles_of(floor) == tiles_of(M.find_floor(store, 152, 96, 101))
    assert [to_py(r, "row") for r in M.summary(back, None, 8000).values()] == \
        [to_py(r, "row") for r in M.summary(store, None, 8000).values()]
    assert M.release(back, 44) == 1


@test("summary rows and G are JSON too")
def _():
    store = busy_store()
    for r in M.summary(store, LUA.eval("function(z) return z end"), 8000).values():
        json.dumps(to_py(r, "row"))
    json.dumps(to_py(M.grammar(to_lua({"elevs": [1, 2], "spine": {"x": 1, "y": 2}})), "G"))


# ---------------------------------------------------------------- 11. the module

@test("the module compiles under Lua 5.3, leaks no global and uses no game access")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    assert lua.eval("_VERSION") == "Lua 5.3"
    leaked = lua.eval("""function(src)
      local before = {}
      for k in pairs(_G) do before[k] = true end
      local env = setmetatable({}, {__index = _G, })
      assert(load(src, 'ai-floorplan', 't', env))()
      local out = {}
      for k in pairs(_G) do if not before[k] then table.insert(out, tostring(k)) end end
      return table.concat(out, ' ')
    end""")(SRC)
    assert leaked == "", leaked
    # and with no dfhack, df or reqscript to lean on: any read of an unknown global is an error
    names = lua.eval("""function(src)
      local env = setmetatable({}, {__index = function(_, k)
        local v = _G[k]
        if v == nil then error('reads the global ' .. tostring(k)) end
        return v
      end})
      assert(load(src, 'ai-floorplan', 't', env))()
      local s = env.new_store()
      local f = env.new_floor(s, 1, 2, 3, 4)
      env.mark_full(s, f, 'homes', 5, {east = 3})
      env.commit(s, f, {req = {kind = 'a', tag = 'homes'}, hall = {{x = 1, y = 0}},
                        puts = {{run = 1, side = 1, u = 4, w = 3, d = 3, role = 'room'}},
                        runs = {{id = 1, new = true, parent = 0, ox = 0, oy = 0, dx = 1, dy = 0, len_before = 0, len = 8}}}, 9, 6)
      env.claims(f); env.summary(s, nil, 7); env.grammar({gap = 2}); env.migrate(s); env.release(s, 9)
      env.find_floor(s, 1, 2, 3)
      local out = {}
      for k, v in pairs(env) do table.insert(out, k) end
      table.sort(out)
      return table.concat(out, ' ')
    end""")(SRC)
    assert names == ("FLOORS_MAX RUNS_MAX SLOTS_MAX VERSION claims commit find_floor grammar mark_full migrate "
                     "new_floor new_store prune release room_for summary"), names
    for word in ("dfhack", "reqscript", "df."):
        code = "\n".join(line.split("--")[0] for line in SRC.splitlines())
        assert word not in code, word
    assert "--@ module = true" in SRC


@test("the bridge lists the module, right after ai-recovery")
def _():
    lines = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8").splitlines()
    i = lines.index("    'ai-recovery',   -- (0.105.46, I4)")
    assert lines[i + 1] == "    'ai-floorplan',   -- (layout B) the hallway-first floor plans"


if __name__ == "__main__":
    finish()
