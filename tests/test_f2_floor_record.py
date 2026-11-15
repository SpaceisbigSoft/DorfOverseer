"""(F2) The floor record stays within FLOORS_MAX and heals itself (verify-v55 V2 and S3).

  V2  floors that are only marks (no run, no slot) are pruned once their marks
      expire; a mark never pushes the record past FLOORS_MAX; a new floor's
      level is never designated when the record cannot hold it (the start goes
      the classic way, and says why); a floor that is only a mark makes way for
      a real one.
  S3  a version-1 record with junk inside (a run's len or id saved as a string,
      a slot with no place, a run with no direction, floors saved as an object)
      is mended by migrate, and the placer uses the floor again.

The pure parts run on lua/ai-floorplan.lua alone; the end-to-end parts on the
fake fort of tests/test_b16_floors_end_to_end.py (its setup and helpers, as
test_v55_floors_verify.py loads them).

    python tests/test_f2_floor_record.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import finish, make_test  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime, lua_type
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

_B16 = ROOT / "tests" / "test_b16_floors_end_to_end.py"
_SRC = _B16.read_text(encoding="utf-8")
_NS: dict = {"__name__": "b16_top_for_f2", "__file__": str(_B16)}
exec(compile(_SRC[:_SRC.index("# ----------------------------------------------------------------"
                              "----------- 1. the worked example")], str(_B16), "exec"), _NS)
F = type("B16", (), {})()
F.__dict__.update(_NS)
ROCK_Z, SX, SY = F.ROCK_Z, F.SX, F.SY
DAY = 1200

test = make_test(before=lambda: F._reset())

# ---------------------------------------------------------------- the pure module

PL = LuaRuntime(unpack_returned_tuples=True)
M = PL.eval("function(src) local env = setmetatable({}, {__index=_G}); "
            "assert(load(src, 'ai-floorplan', 't', env))(); return env end")(
    (ROOT / "lua" / "ai-floorplan.lua").read_text(encoding="utf-8"))


def to_lua(v):
    if isinstance(v, dict):
        t = PL.table()
        for k, x in v.items():
            t[k] = to_lua(x)
        return t
    if isinstance(v, (list, tuple)):
        t = PL.table()
        for i, x in enumerate(v, 1):
            t[i] = to_lua(x)
        return t
    return v


def to_py(v, path="store"):
    """As JSON would hold it; fails on a mixed or holey table."""
    if lua_type(v) == "table":
        keys = list(v.keys())
        if not keys:
            return []
        if all(isinstance(k, int) for k in keys):
            assert sorted(keys) == list(range(1, len(keys) + 1)), f"{path}: a sparse list {sorted(keys)}"
            return [to_py(v[i], f"{path}[{i}]") for i in range(1, len(keys) + 1)]
        assert all(isinstance(k, str) for k in keys), f"{path}: mixed keys {keys}"
        return {k: to_py(v[k], f"{path}.{k}") for k in keys}
    return v


def call(fn, *args):
    res = fn(*args)
    return res if isinstance(res, tuple) else (res,)


def run(rid=1, length=10, **kw):
    r = {"id": rid, "parent": 0, "ox": 0, "oy": 0, "dx": 1, "dy": 0, "len": length, "walked": 0,
         "tag": "homes", "node": 3, "neck": False, "pid": 7}
    r.update(kw)
    return r


def slot(rid=1, u=4, side=1, **kw):
    s = {"run": rid, "side": side, "u": u, "w": 3, "d": 3, "pid": 7, "kind": "bedrooms", "tag": "homes",
         "role": "room"}
    s.update(kw)
    return s


def floor(fid, z, runs=(), slots=(), full=None, hub="found"):
    return {"id": fid, "z": z, "stair": {"x": 0, "y": 0}, "made": 0, "hub": hub,
            "runs": list(runs), "slots": list(slots), "full": full if full is not None else {}}


def placement():
    hall = [(x, y) for x in (-1, 0, 1) for y in (-1, 0, 1) if (x, y) != (0, 0)]
    hall += [(x, y) for x in range(2, 12) for y in (-1, 0, 1)]
    return to_lua({"req": {"kind": "bedrooms", "tag": "homes"},
                   "puts": [{"run": 1, "side": 1, "u": 4, "w": 3, "d": 3, "role": "room"}],
                   "runs": [{"id": 1, "new": True, "parent": 0, "ox": 0, "oy": 0, "dx": 1, "dy": 0,
                             "len_before": 0, "len": 10, "walked": 0, "tag": "homes", "node": 3}],
                   "hall": [{"x": x, "y": y} for x, y in hall], "hall_rects": [], "statues": []})


def ids(store):
    return [f["id"] for f in to_py(store)["floors"]]


# ---------------------------------------------------------------- V2, pure

@test("prune: a floor that is only expired marks goes; fresh marks, runs, slots, a dug hub stay; next never goes back")
def _():
    now = 100 * DAY
    store = to_lua({"v": 1, "next": 9, "fallbacks": 0, "floors": [
        floor(1, 10, full={"*": 0}),                                   # expired: goes
        floor(2, 11, full={"*": now - DAY}),                           # fresh: stays
        floor(3, 12, full={"homes": 0, "*": now - 2 * DAY}),           # one fresh mark: stays
        floor(4, 13, runs=[run(length=0, closed="released")], full={"*": 0}),   # a run: stays
        floor(5, 14, slots=[slot(dead=True)], full={"*": 0}),          # a slot (even orphaned): stays
        floor(6, 15, hub="dug", full={"*": 0}),                        # a dug hub: stays
        floor(7, 16),                                                  # no mark at all: goes
    ]})
    n = M.prune(store, now, 28)
    assert n == 2 and ids(store) == [2, 3, 4, 5, 6], ids(store)
    assert store.next == 9, "an id is never given twice"
    assert M.prune(store, now, 28) == 0
    # with no clock nothing expires
    assert M.prune(store, None, 28) == 0


@test("mark_full never pushes the record past FLOORS_MAX: expired marks make way, fresh ones refuse the mark")
def _():
    store = M.new_store()
    for z in range(60):
        assert M.mark_full(store, M.new_floor(store, z, 0, 0, 0), "*", 0) is not None
    assert len(store.floors) == 60
    # still fresh at day 10: the 61st mark is dropped, the record stays at 60
    out, why = call(M.mark_full, store, M.new_floor(store, 99, 0, 0, 10 * DAY), "*", 10 * DAY)
    assert out is None and why == "floor record full" and len(store.floors) == 60
    # at day 40 all 60 have expired: they go, the new mark is kept
    out = M.mark_full(store, M.new_floor(store, 99, 0, 0, 40 * DAY), "*", 40 * DAY)
    assert out is not None and len(store.floors) == 1 and store.floors[1].z == 99
    assert len(store.floors) <= M.FLOORS_MAX


@test("commit: a floor that is only a (fresh) mark makes way for a real floor; 60 floors with halls refuse it")
def _():
    store = M.new_store()
    for z in range(60):
        M.mark_full(store, M.new_floor(store, z, 0, 0, z), "*", z)    # floor of z 0 has the oldest mark
    assert M.room_for(store) is True
    f = M.commit(store, M.new_floor(store, 99, 0, 0, 100), placement(), 41, 100)
    assert f is not None and len(store.floors) == 60
    zs = [g["z"] for g in to_py(store)["floors"]]
    assert 99 in zs and 0 not in zs, "the floor whose newest mark is the oldest made way"
    assert f.id == 61 and store.next == 62

    full = M.new_store()
    for z in range(60):
        assert M.commit(full, M.new_floor(full, z, 0, 0, 1), placement(), 100 + z, 1) is not None
    assert M.room_for(full) is False
    before = json.dumps(to_py(full), sort_keys=True)
    out, why = call(M.commit, full, M.new_floor(full, 99, 0, 0, 1), placement(), 41, 1)
    assert out is None and why == "floor record full"
    assert json.dumps(to_py(full), sort_keys=True) == before


# ---------------------------------------------------------------- S3, pure

def junk_store():
    return to_lua({"v": 1, "next": "3", "fallbacks": "4", "floors": {
        "a": {"id": "1", "z": "63", "stair": {"x": "60", "y": 60}, "made": 0, "hub": "found",
              "runs": [{"id": "1", "parent": "0", "ox": 0, "oy": 0, "dx": 1, "dy": "0", "len": "12",
                        "walked": "0", "tag": "homes", "node": 3, "pid": 7, "grew": {"7": "0"}},
                       {"id": 2, "parent": 1, "ox": 5, "oy": 0, "dx": 3, "dy": 0, "len": 6},      # no direction
                       {"id": "x", "dx": 0, "dy": 1, "len": 4},                                  # no id
                       {"id": 1, "dx": 0, "dy": 1, "len": 4},                                    # a second run 1
                       "junk"],
              "slots": [{"run": "1", "side": "1", "u": "4", "w": 3, "d": "3", "pid": 7, "tag": 5,
                         "kind": "bedrooms", "dead": "yes"},
                        {"run": 1, "side": -1, "u": "four", "w": 3, "d": 3},                     # no place
                        {"run": 2, "side": 1, "u": 4, "w": 3, "d": 3},                           # its run went
                        {"run": 1, "side": 0, "u": 9, "w": 3, "d": 3},                           # side 0, not axial
                        {"run": 1, "side": 1, "u": 8, "w": 3, "d": 3, "rect": {"x1": "a"}, "dead": False}],
              "full": {"homes": "120", "bad": "soon", "*": 5}, "free": {"tick": "5", "east": "9"}},
        "b": {"id": 1, "z": 70, "stair": {"x": 60, "y": 60}, "runs": [], "slots": [], "full": []},  # a second id 1
        "c": "junk"}})


@test("S3. migrate mends a v1 record with junk inside: numeric strings become numbers, rows it cannot mend go")
def _():
    store = junk_store()
    out, changed, why = call(M.migrate, store)
    assert changed is True and why == "repaired"
    py = to_py(out)            # fails on a mixed or holey table: the record saves as JSON again
    assert py["next"] == 3 and py["fallbacks"] == 4 and len(py["floors"]) == 2
    a = next(f for f in py["floors"] if f["z"] == 63)
    b = next(f for f in py["floors"] if f["z"] == 70)
    assert a["id"] == 1 and b["id"] == 2 and py["next"] == 3, "the second floor 1 got its own id"
    assert a["stair"] == {"x": 60, "y": 60}
    assert len(a["runs"]) == 1
    r = a["runs"][0]
    assert (r["id"], r["parent"], r["dy"], r["len"], r["walked"], r["grew"]) == (1, 0, 0, 12, 0, {"7": 0}), r
    assert [(s["u"], s["side"], s["d"]) for s in a["slots"]] == [(4, 1, 3), (8, 1, 3)], a["slots"]
    s1, s2 = a["slots"]
    assert "tag" not in s1 and s1["dead"] is True and s2["dead"] is False and "rect" not in s2
    assert a["full"] == {"homes": 120, "*": 5}
    assert a["free"] == {"tick": 5, "east": 9}
    assert call(M.migrate, out)[1] is False, "a mended record is a good record"
    # and the module's own readers take it without throwing
    M.claims(out.floors[1])
    M.summary(out, None, 200)
    M.release(out, 7)


@test("S3. migrate leaves a good v1 record the same table, unchanged (dead = false, grew, closed kept)")
def _():
    store = to_lua({"v": 1, "next": 2, "fallbacks": 0, "floors": [
        floor(1, 63, runs=[run(grew={"7": 0}, closed="terminus", low=4)],
              slots=[slot(dead=False), slot(u=8, axial=True, side=0, rect={"x1": 1, "y1": 2, "x2": 3, "y2": 4})],
              full={"homes": 3})]})
    before = json.dumps(to_py(store), sort_keys=True)
    out, changed, why = call(M.migrate, store)
    assert changed is False and why is None
    assert json.dumps(to_py(out), sort_keys=True) == before


# ---------------------------------------------------------------- end to end (the fake fort)

def bedrooms(z=ROCK_Z):
    return F.start(kind="bedrooms", rooms=4, room_size=3,
                   floor={"elevs": [z], "tag": "homes", "dirs": ["east"], "arms_max": 1, "grow": ["arm"]})


def hall_floors(n, z0=200):
    """n floors with a hall and a room each, on levels away from the test's."""
    return [{"id": i, "z": z0 + i, "stair": {"x": SX, "y": SY}, "made": 0, "hub": "dug",
             "runs": [run()], "slots": [slot()], "full": {}} for i in range(1, n + 1)]


@test("V2. a new floor the record cannot hold (60 floors with halls) is never dug: the level goes the classic way "
      "and says why")
def _():
    F.W.persist[F.KEY] = F.tbl({"v": 1, "next": 61, "fallbacks": 0, "floors": hall_floors(60)})
    r = bedrooms()
    assert r.ok and r.floor is None, F.plain(r)
    assert "the floor record is full" in str(r.not_on_floor or ""), F.plain(r)
    st = F.store()
    assert len(st["floors"]) == 60 and F.floor_rec(ROCK_Z) is None
    p = F.project(r.project_id)
    assert p.floor is None, "the classic level is not a floor level"


@test("V2. the 60th-floor limit with one floor that is only a fresh mark: the new floor takes its place, "
      "the level is dug and recorded")
def _():
    floors = hall_floors(59)
    floors.append({"id": 60, "z": 300, "stair": {"x": SX, "y": SY}, "made": 0, "hub": "found",
                   "runs": [], "slots": [], "full": {"*": 0}})
    F.W.persist[F.KEY] = F.tbl({"v": 1, "next": 61, "fallbacks": 0, "floors": floors})
    r = bedrooms()
    assert r.ok and r.floor is not None, F.plain(r)
    rec = F.floor_rec(ROCK_Z)
    assert rec is not None and any(s.get("pid") == r.project_id for s in rec["slots"]), F.store()
    st = F.store()
    assert len(st["floors"]) == 60 and all(f["z"] != 300 for f in st["floors"])
    assert rec["id"] == F.plain(r.floor)["id"] == 61


@test("V2. floors_report: the pruned marks are gone from the list, and count/rooms agree with the record")
def _():
    floors = hall_floors(3) + [
        {"id": 4, "z": 300, "stair": {"x": SX, "y": SY}, "made": 0, "hub": "found", "runs": [], "slots": [],
         "full": {"*": 0}},
        {"id": 5, "z": 301, "stair": {"x": SX, "y": SY}, "made": 0, "hub": "found", "runs": [], "slots": [],
         "full": {"industry": 100 * DAY}}]
    F.W.persist[F.KEY] = F.tbl({"v": 1, "next": 6, "fallbacks": 2, "floors": floors})
    F.E.tick = 101 * DAY
    rep = F.plain(F.B.floors_report())
    assert [row["id"] for row in rep["list"]] == [1, 2, 3, 5], rep["list"]
    assert rep["count"] == 3 and rep["rooms"] == 3 and rep["fallbacks"] == 2
    assert rep["list"][3]["full"] == ["industry"]


@test("S3. a record whose floor has its run's len and id saved as strings: the next level goes onto that floor")
def _():
    a = bedrooms()
    assert a.ok and a.floor is not None, F.plain(a)
    st = F.store()
    rec = next(f for f in st["floors"] if f["z"] == ROCK_Z)
    for r in rec["runs"]:
        r["len"], r["id"] = str(r["len"]), str(r["id"])
    for s in rec["slots"]:
        s["run"], s["u"] = str(s["run"]), str(s["u"])
    rec["full"] = {"homes": "soon", "industry": "-99999"}     # junk, and a long-expired mark
    F.W.persist[F.KEY] = F.tbl(st)
    b = bedrooms()
    assert b.ok and b.floor is not None, F.plain(b)
    assert F.plain(b.floor)["id"] == F.plain(a.floor)["id"], (F.plain(a.floor), F.plain(b.floor))
    rec = F.floor_rec(ROCK_Z)
    assert all(isinstance(r["len"], int) and isinstance(r["id"], int) for r in rec["runs"]), rec["runs"]
    assert any(s.get("pid") == b.project_id for s in rec["slots"])


if __name__ == "__main__":
    finish()
