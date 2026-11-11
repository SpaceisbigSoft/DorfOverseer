"""(0.105.33, group secondway) A second way to the surface by design. E (8 Nov)
had one way in, the founding stair under a hatch; when DF's walk map held
that open hatch shut, everyone outside was cut off and 64 died of thirst.
The brain (planner_gates._second_way_rule) asks a fort of 30+ with one
surface entrance for dig_way_in {second = true}; the bridge
(lua/ai-builder-projects.lua way_in_second_spots / way_in_plan_and_dig)
picks open ground under the sky 15-40 tiles from the entrance and digs with
every rule the emergency way in keeps; the gate scan then finds it and
fortify closes it like any other.

    python tests/test_r33_secondway.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish  # noqa: E402

import planner  # noqa: E402
from planner import Memory, plan, record, note_cycle, PLANNER_CONFIG  # noqa: E402
import planner_core  # noqa: E402
import overseer  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime  # noqa: F401
    HAVE_LUPA = True
except ImportError:
    HAVE_LUPA = False

if HAVE_LUPA:
    import test_r32_wayin as R32          # the way-in fakes (its tests run only when it is run itself)
    LUA, B, W, G = R32.boot()
else:
    LUA = B = W = G = None


def _reset():
    if W is not None:
        W.reset()


test = make_test(before=_reset)

# --- the brain -------------------------------------------------------------------------

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort(citizens=30, entrances=1, traits=None, reach=0, armed=False, stranded=(), projects=()) -> dict:
    s = copy.deepcopy(BASE)
    s["dwarves"]["total"] = citizens
    ent = s["entrances"]
    es = [{"id": 1, "kind": "surface", "x": 31, "y": 140, "z": 173, "width": 1, "sealed": True,
           "equipment": [{"id": 500, "kind": "door"}], "door_spots": 0, "closed": False}]
    for i in range(1, entrances):
        es.append({"id": 1 + i, "kind": "surface", "x": 31 + 20 * i, "y": 140, "z": 173, "width": 1,
                   "sealed": True, "equipment": [{"id": 500 + i, "kind": "hatch"}], "door_spots": 0})
    ent["entrances"] = es
    ent["armed"] = armed
    ent["stranded"] = list(stranded)
    ent["scanned_tick"] = planner_core.abs_tick(s) - 10
    s["others_on_map"]["threats_that_can_reach_dwarves"] = reach
    if traits is not None:
        s["settings"]["traits"] = dict(s["settings"].get("traits") or {}, **traits)
    s.setdefault("projects", {})["open"] = list(projects)
    return s


def later(s: dict, ticks: int) -> dict:
    s = copy.deepcopy(s)
    s["date"]["tick"] += ticks
    s["entrances"]["scanned_tick"] = planner_core.abs_tick(s) - 1
    return s


def second(props):
    return [p for p in props if p.rule == "second_way"]


def cycle(s, m):
    note_cycle(s, m)
    return plan(s, m)


HERMIT = {"outsiders": -150, "caution": 50}
DAY = 1200


@test("brain: a fort of 30 with one surface entrance asks for a second way in; not at 29")
def _():
    props, _ = cycle(fort(30), Memory())
    w = second(props)
    assert len(w) == 1 and w[0].action == {"type": "dig_way_in", "second": True}, props
    assert "one way to the surface" in w[0].reason and "dig a second" in w[0].reason, w[0].reason
    assert not second(cycle(fort(29), Memory())[0])
    assert PLANNER_CONFIG["second_way_min_citizens"] == 30 and PLANNER_CONFIG["second_way_retry_days"] == 60
    assert overseer.short(w[0].action) == "dig a second way in from the surface"


@test("brain: not with two surface entrances, and never again once a second one has been seen")
def _():
    m = Memory()
    assert not second(cycle(fort(80, entrances=2), m)[0])
    assert m.second_way.get("done"), m.second_way
    assert not second(cycle(later(fort(80, entrances=1), 100 * DAY), m)[0])


@test("brain: held in a siege (an enemy can reach the dwarves, or the watcher armed) and while a way in is dug")
def _():
    assert not second(cycle(fort(50, reach=2), Memory())[0])
    assert not second(cycle(fort(50, armed=True), Memory())[0])
    assert not second(cycle(fort(50, projects=[{"id": 9, "kind": "way_in", "phase": "dig"}]), Memory())[0])
    assert second(cycle(fort(50), Memory())[0])


@test("brain: not for the Hermit hold (hidden_hold, winding_ways, Outsiders -50) unless citizens were ever stranded")
def _():
    assert not second(cycle(fort(50, traits=HERMIT), Memory())[0])
    assert not second(cycle(fort(50, traits={"outsiders": -50}), Memory())[0])
    assert second(cycle(fort(50, traits={"outsiders": -49}), Memory())[0])
    # once stranded (cut off, no way back in), remembered: then dug all the same
    m = Memory()
    row = {"id": 1, "name": "Urist", "x": 10, "y": 10, "z": 174, "cause": "no_path", "out_ticks": 300, "out_days": 0}
    cycle(fort(50, traits=HERMIT, stranded=[row]), m)
    assert m.second_way.get("stranded_ever"), m.second_way
    m2 = Memory.from_dict(json.loads(json.dumps(m.to_dict())))       # kept with the fort
    props, _ = cycle(later(fort(50, traits=HERMIT), DAY), m2)
    w = second(props)
    assert w and "stranded outside once" in w[0].reason, props


@test("brain: refused: again only after 60 days")
def _():
    m = Memory()
    s = fort(40)
    w = second(cycle(s, m)[0])[0]
    record([(w, {"ok": False, "rejected": True, "error": "no safe second way in found"})], s, m)
    assert m.second_way["ok"] is False and "no safe" in m.second_way["why"], m.second_way
    assert not second(cycle(later(s, 30 * DAY), m)[0])
    assert not second(cycle(later(s, 59 * DAY), m)[0])
    assert second(cycle(later(s, 61 * DAY), m)[0])


@test("brain: dug: the entrances mapped again once its project closes, then done with two")
def _():
    m = Memory()
    s = fort(40)
    w = second(cycle(s, m)[0])[0]
    record([(w, {"ok": True, "project_id": 12})], s, m)
    s2 = later(fort(40, projects=[{"id": 12, "kind": "way_in", "phase": "dig"}]), 2 * DAY)
    assert not second(cycle(s2, m)[0])
    m.rescan_entrances = False
    cycle(later(fort(40), 3 * DAY), m)
    assert m.rescan_entrances and m.second_way.get("rescanned"), m.second_way
    cycle(later(fort(40, entrances=2), 4 * DAY), m)
    assert m.second_way.get("done")


# --- the bridge ------------------------------------------------------------------------

def dig(dry=False):
    return B.dig_way_in(LUA.table_from({"second": True}), LUA.table_from({"year": 253, "tick": 100}), dry)


def designated():
    return sorted((t.x, t.y, t.z, t.dig_text) for t in W.idx.values() if t.designated)


def projects():
    d = W.persist["ai-overseer/projects"]
    if d is None:
        return []
    return [d.list[i] for i in range(1, len(d.list) + 1)]


def apart(x, y):
    return max(abs(x - 30), abs(y - 25))        # from the founding stair's entrance (30, 25)


def lupa_test(name):
    def wrap(fn):
        if HAVE_LUPA:
            return test(name)(fn)
        return fn
    return wrap


@lupa_test("bridge: the second way's top 15-40 tiles from the entrance, under the sky, at most 30 tiles dug")
def _():
    r = dig()
    assert r.ok and r.second and r.project_id == 1, dict(r)
    assert 15 <= r.apart <= 40 and 15 <= apart(r.to.x, r.to.y) <= 40, dict(r.to)
    assert 15 <= apart(r.column.x, r.column.y) <= 40, dict(r.column)
    assert r.tiles <= 30, r.tiles
    top = W.get(r.to.x, r.to.y, r.to.z)
    assert top.outside and r.to.z == 30, dict(r.to)
    assert (r.entrance.x, r.entrance.y) == (30, 25), dict(r.entrance)
    ds = designated()
    assert len(ds) == r.tiles and all(t[3].endswith("4") for t in ds), ds     # the ordinary priority
    # 6+ tiles from the gate's pieces, nothing on the existing stair
    assert all(apart(t[0], t[1]) >= 6 for t in ds), ds
    p = projects()[0]
    assert p.kind == "way_in" and p.second is True and p.emergency is None and p.stranded is None, dict(p)
    assert p.summary.second is True and p.summary.way_in is True
    W.dig_all()
    rep = B.projects_report()
    o = rep.open[1]
    assert o.kind == "way_in" and o.next == "finish", (o.kind, o.next)
    assert B.finish_project(1).phase == "done"


@lupa_test("bridge: dry run gives the plan and changes nothing")
def _():
    r = dig(dry=True)
    assert r.ok and r.dry_run and r.second and r.project_id is None, dict(r)
    assert designated() == [] and projects() == []
    assert all(c.dry_run for c in W.calls.values()), "a real quickfort run on a dry run"


@lupa_test("bridge: never beside water, a cavern, an aquifer, a building or another project")
def _():
    # water west of the fort under the ground, a cavern pocket south, buildings
    # and another AI project east: dug east, round them
    for z in range(25, 30):
        W.box(10, 0, 17, 63, z, LUA.table_from({"liquid": True, "shape": "FLOOR"}))
    W.box(0, 36, 63, 63, 27, LUA.table_from({"feature": True, "shape": "FLOOR"}))
    W.box(44, 0, 63, 24, 30, LUA.table_from({"building": True}))
    W.persist["ai-overseer/projects"] = LUA.table_from({"next_id": 5, "list": LUA.table_from({
        1: LUA.table_from({"id": 4, "kind": "bedrooms", "phase": "done",
                           "area": LUA.table_from({"x1": 41, "y1": 26, "x2": 50, "y2": 30, "z": 24})})})})
    r = dig()
    assert r.ok, dict(r)
    assert r.column.x > 40, dict(r.column)
    for t in W.idx.values():
        if t.designated:
            assert not t.building, (t.x, t.y, t.z)
            assert not (t.z == 24 and 41 <= t.x <= 50 and 26 <= t.y <= 30), (t.x, t.y, t.z)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        n = W.get(t.x + dx, t.y + dy, t.z + dz)
                        assert not (n and (n.liquid or n.feature)), (t.x, t.y, t.z)
    assert 15 <= r.apart <= 40 and r.tiles <= 30, dict(r)


@lupa_test("bridge: refusals: an aquifer everywhere, too far to dig, two entrances, no scan, the watcher armed")
def _():
    for z in range(25, 30):
        W.box(0, 0, 63, 63, z, LUA.table_from({"aquifer": True}))
    r = dig()
    assert not r.ok and r.error.startswith("no safe second way in found") and "aquifer" in r.error, dict(r)
    assert designated() == [] and projects() == []
    W.reset()
    W.SURF = 38                                       # the fort 32 levels under the ground
    W.idx = LUA.table()
    W.fort(6, 20, 20, 40, 30)
    W.scan_inside()
    W.GATES.entrances[1].z = 37                       # (its stair's top, under the ground)
    r = dig()
    assert not r.ok and "more than 30 tiles" in r.error, dict(r)
    W.reset()
    W.GATES.entrances[2] = LUA.table_from({"id": 2, "kind": "surface", "x": 50, "y": 25, "z": 29,
                                           "equipment": LUA.table()})
    r = dig()
    assert not r.ok and "already has 2 ways to the surface" in r.error, dict(r)
    W.reset()
    W.use_gates = False
    r = dig()
    assert not r.ok and "not mapped" in r.error, dict(r)
    W.reset()
    W.GATES.armed = True
    r = dig()
    assert not r.ok and "watcher is armed" in r.error and designated() == [], dict(r)


@lupa_test("bridge: dug, the gate scan finds a second surface entrance and fortify closes it like any other")
def _():
    r = dig()
    assert r.ok
    W.dig_all()
    starts = LUA.table_from({1: LUA.table_from({"x": 25, "y": 25, "z": 24})})
    es, inside = G.find_entrances(starts, LUA.table())[0:2]
    surf = [e for e in (es[i] for i in range(1, len(es) + 1)) if e.kind == "surface"]
    spots = sorted((e.x, e.y) for e in surf)
    assert len(spots) == 2 and (30, 25) in spots and (r.column.x, r.column.y) in spots, spots
    new = next(e for e in surf if (e.x, e.y) == (r.column.x, r.column.y))
    assert not new.sealed and not new.closing, dict(new)
    # fortify: the scan's map kept as the gate module's, every placement recorded
    G.GATES = LUA.table_from({"scanned": True, "entrances": es, "inside": inside})
    placed = []
    G.place_hook = lambda key, pos: (placed.append((key, pos.x, pos.y, pos.z)) or True)
    try:
        f = G.fortify(new.id, "plain", starts)
    finally:
        G.place_hook = None
    assert f.ok is not False, dict(f)
    assert placed, dict(f)
    assert all(apart(x, y) >= 14 for _k, x, y, _z in placed), placed      # at the new one, not the old


if __name__ == "__main__":
    if not HAVE_LUPA:
        print("(the bridge tests need the lupa package: pip install lupa; skipped)")
    finish()
