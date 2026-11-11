"""(fix33, safety) The second way to the surface, after the v33 verify:
it never holds the emergency way in for citizens cut off (brain and bridge),
it keeps to the player's gate Rules, it stops after one dug the scan doesn't
see (a courtyard top is refused in the bridge), and the bridge's search has
one deadline for the whole action.

    python tests/test_r33_fix_safety.py
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

from planner import Memory, plan, record, note_cycle  # noqa: E402
import planner_core  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime  # noqa: F401
    HAVE_LUPA = True
except ImportError:
    HAVE_LUPA = False

if HAVE_LUPA:
    import test_r32_wayin as R32
    LUA, B, W, G = R32.boot()
else:
    LUA = B = W = G = None


def _reset():
    if W is not None:
        W.reset()


test = make_test(before=_reset)
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
DAY = 1200
ROW = {"id": 7, "name": "Urist", "x": 60, "y": 100, "z": 174, "cause": "no_path", "out_ticks": 4 * DAY, "out_days": 4}


def fort(citizens=40, stranded=(), projects=(), settings=None, registry=None) -> dict:
    s = copy.deepcopy(BASE)
    s["dwarves"]["total"] = citizens
    ent = s["entrances"]
    ent["entrances"] = [{"id": 1, "kind": "surface", "x": 31, "y": 140, "z": 173, "width": 1, "sealed": True,
                         "equipment": [{"id": 500, "kind": "door"}], "door_spots": 0, "closed": False}]
    ent["armed"] = False
    ent["stranded"] = list(stranded)
    ent["scanned_tick"] = planner_core.abs_tick(s) - 10
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s.setdefault("projects", {})["open"] = list(projects)
    for k, v in (settings or {}).items():
        s["settings"][k] = v
    if registry is not None:
        s["registry"] = registry
    return s


def later(s: dict, ticks: int) -> dict:
    s = copy.deepcopy(s)
    s["date"]["tick"] += ticks
    s["entrances"]["scanned_tick"] = planner_core.abs_tick(s) - 1
    return s


def cycle(s, m):
    note_cycle(s, m)
    return plan(s, m)


def rule(props, name):
    return [p for p in props if p.rule == name]


def started(m) -> dict:
    s = fort()
    w = rule(cycle(s, m)[0], "second_way")[0]
    record([(w, {"ok": True, "project_id": 12})], s, m)
    return s


# --- the brain ---------------------------------------------------------------------------

@test("brain: an open second way (summary.second, or memory's project) never holds the emergency way in")
def _():
    for proj in ({"id": 12, "kind": "way_in", "phase": "dig", "summary": {"way_in": True, "second": True}},
                 {"id": 12, "kind": "way_in", "phase": "dig"}):          # (memory.second_way's project id)
        m = Memory()
        started(m)
        for d in (3, 10, 20):
            props, notes = cycle(later(fort(stranded=[ROW], projects=[proj]), d * DAY), m)
            assert len(rule(props, "way_in")) == 1, (d, proj)
            said = [n for n in notes if "stranded outside" in str(n)]
            assert said and "#12" not in said[0], said
    # an emergency way in under way still holds another
    m = Memory()
    props, _ = cycle(later(fort(stranded=[ROW], projects=[{"id": 9, "kind": "way_in", "phase": "dig",
                                                            "summary": {"way_in": True, "emergency": True}}]),
                           3 * DAY), m)
    assert not rule(props, "way_in")


@test("brain: an open second way still holds another second way")
def _():
    m = Memory()
    started(m)
    proj = {"id": 12, "kind": "way_in", "phase": "dig", "summary": {"way_in": True, "second": True}}
    props, _ = cycle(later(fort(projects=[proj]), 61 * DAY), m)
    assert not rule(props, "second_way")


@test("brain: no second way while doors and walls on entrances are both off on the Rules tab")
def _():
    props, notes = cycle(fort(settings={"build_gate_doors": False, "fortify_entrances": False}), Memory())
    assert not rule(props, "second_way")
    assert any("Rules tab" in str(n) and "second way" in str(n) for n in notes), notes
    for k in ("build_gate_doors", "fortify_entrances"):
        props, _ = cycle(fort(settings={k: False}), Memory())
        assert rule(props, "second_way"), k


@test("brain: one dug, closed, mapped again and still one surface entrance: no more, said once")
def _():
    m = Memory()
    s = started(m)
    cycle(later(fort(registry=[{"id": 12, "kind": "way_in", "phase": "done"}]), 2 * DAY), m)
    assert m.second_way.get("rescanned") and m.second_way.get("closed_phase") == "done", m.second_way
    m.rescan_entrances = False
    props, notes = cycle(later(s, 61 * DAY), m)
    assert not rule(props, "second_way") and m.second_way.get("dug_unseen")
    assert sum("second way to the surface was dug" in str(n) for n in notes) == 1, notes
    for k in range(2, 6):
        props, notes = cycle(later(s, k * 61 * DAY), m)
        assert not rule(props, "second_way")
        assert not any("second way to the surface was dug" in str(n) for n in notes)


@test("brain: one cancelled (the registry): tried again after 60 days")
def _():
    m = Memory()
    s = started(m)
    cycle(later(fort(registry=[{"id": 12, "kind": "way_in", "phase": "cancelled"}]), 2 * DAY), m)
    assert m.second_way.get("closed_phase") == "cancelled"
    m.rescan_entrances = False                 # the scan ran: still one surface entrance
    w = rule(cycle(later(s, 61 * DAY), m)[0], "second_way")
    assert w and not m.second_way.get("dug_unseen")
    record([(w[0], {"ok": True, "project_id": 30})], later(s, 61 * DAY), m)
    assert "closed_phase" not in m.second_way, m.second_way


# --- the bridge --------------------------------------------------------------------------

def lupa_test(name):
    def wrap(fn):
        if HAVE_LUPA:
            return test(name)(fn)
        return fn
    return wrap


def second(dry=False):
    return B.dig_way_in(LUA.table_from({"second": True}), LUA.table_from({"year": 253, "tick": 100}), dry)


def way_in(x=46, y=25, z=30):
    return B.dig_way_in(LUA.table_from({"x": x, "y": y, "z": z}), LUA.table_from({"year": 253, "tick": 100}), False)


def surface_entrances():
    starts = LUA.table_from({1: LUA.table_from({"x": 25, "y": 25, "z": 24})})
    es = G.find_entrances(starts, LUA.table())[0]
    return sorted((e.x, e.y) for e in (es[i] for i in range(1, len(es) + 1)) if e.kind == "surface")


@lupa_test("bridge: the emergency way in is dug while the second way is; a second second way is refused")
def _():
    r = second()
    assert r.ok and r.project_id == 1, dict(r)
    r2 = way_in()
    assert r2.ok and r2.project_id == 2, dict(r2)
    r3 = second(True)
    assert not r3.ok and "already being dug (project" in r3.error, dict(r3)
    W.reset()
    assert way_in().ok
    r4 = second(True)
    assert not r4.ok and "already being dug (project 1)" in r4.error, dict(r4)


@lupa_test("bridge: a walled courtyard joined to the fort (the scan's inside): the second way's top not in it")
def _():
    # courtyard x39-52 y20-30 at z30, constructed walls round it, a stair up into it from the fort
    for x in range(38, 54):
        for y in range(19, 32):
            if x in (38, 53) or y in (19, 31):
                W.set(x, y, 30, LUA.table_from({"shape": "WALL", "material": "CONSTRUCTION", "outside": True}))
    for z in range(24, 30):
        W.set(41, 25, z, LUA.table_from({"shape": "STAIR_UPDOWN" if z > 24 else "STAIR_UP"}))
    W.set(41, 25, 30, LUA.table_from({"shape": "STAIR_DOWN"}))
    W.scan_inside()
    LUA.execute("local W, B = ...; local g0 = W.group; B.walk_group = function(x, y, z) "
                "local g = g0(x, y, z); if g == 2 then return 1 end return g end", W, B)
    try:
        starts = LUA.table_from({1: LUA.table_from({"x": 25, "y": 25, "z": 24})})
        inside = G.find_entrances(starts, LUA.table())[1]
        W.GATES.inside = inside
        assert inside[(30 * 4096 + 25) * 4096 + 45], "the courtyard is in the scan's inside"
        r = second()
        assert r.ok, dict(r)
        assert not inside[(r.to.z * 4096 + r.to.y) * 4096 + r.to.x], dict(r.to)
        W.dig_all()
        assert len(surface_entrances()) == 2, surface_entrances()
    finally:
        B.walk_group = W.group


@lupa_test("bridge: one deadline for the spot scan and every column search (the game's freeze)")
def _():
    LUA.execute("""
        local B = ...
        FAKE_T, REAL_CLOCK, REAL_SPOTS = 0, os.clock, B.way_in_second_spots
        os.clock = function() FAKE_T = FAKE_T + 0.05; return FAKE_T end
        B.way_in_second_spots = function(...)
            local a, b = REAL_SPOTS(...)
            FAKE_T = FAKE_T + 3.5            -- the spot scan took 5.5 s in all
            return a, b
        end
    """, B)
    try:
        start = LUA.eval("FAKE_T")
        second(True)
        spent = LUA.eval("FAKE_T") - start
        assert spent <= B.WAY_IN_SECONDS * B.WAY_IN_TRIES + 0.5, spent
    finally:
        LUA.execute("local B = ...; os.clock = REAL_CLOCK; B.way_in_second_spots = REAL_SPOTS", B)


if __name__ == "__main__":
    finish()
