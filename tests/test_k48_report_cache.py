"""(0.105.48, K7 part c) Audits A1 3 and A3 5, 6, 14, 15, 19:

- the projects report changes nothing: a cavern well's lost shaft tile is
  counted (dig.redig_due), and only the redig_projects action (an action, so
  refused while halted) designates it again; the planner asks for it
- the stall rule never asks to furnish a well over a held or closed shaft
- the report's rows carry urgent and dig_done
- quickfort_apply digs nothing when the dig guard cannot run
- dig_stairwell undoes its levels when the game refuses one of them
- the section cache: a section past its SECTION_MAX_DAYS is rebuilt whatever
  the rotation; each cached copy's age is in perf.cache_age (and cache_due);
  brain/perf.py reads them (section_age, stale_sections, the PERF line)

    python tests/test_k48_report_cache.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime  # noqa: F401
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import perf  # noqa: E402
import planner_building as pb  # noqa: E402
import test_builder as TB  # noqa: E402   (the builder rig; its tests run only when it is run itself)
import test_bridge_memory as TBM  # noqa: E402   (the bridge rig)

LUA, B, W = TB.LUA, TB.B, TB.W
test = make_test(before=lambda: TB._reset(False))
BRIDGE = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")


def _lost_shaft_tile():
    TB.cavern_column()
    r = B.place_well(LUA.table_from({"cavern": True, "urgent": True}), LUA.table_from({"year": 148, "tick": 100}), False)
    assert r.ok, r.error
    LUA.eval("""function(W)
        local t = W.get(70, 58, 70); t.designated = false; t.shape = 'EMPTY'
        local s = W.get(70, 58, 69); s.designated = false; s.shape = 'RAMP'
    end""")(W)


def _project():
    d = W.persist["ai-overseer/projects"]
    return d.list[1]


# --- A3 5: the report is read only --------------------------------------------------

@test("A3 5: the projects report never designates a lost shaft tile, however often it is read")
def _():
    _lost_shaft_tile()
    for _ in range(4):
        d = B.projects_report().open[1].dig
        assert d.redig_due == 1 and d.stuck == 0 and d.redesignated is None, (d.redig_due, d.stuck)
    assert not W.get(70, 58, 69).designated
    assert _project().redug is None, "the report kept no count"


@test("A3 5: redig_projects designates it (a dry run only counts), each tile at most REDIG_MAX times")
def _():
    _lost_shaft_tile()
    dry = B.redig_projects(True)
    assert dry.ok and dry.dry_run and dry.tiles == 1 and not W.get(70, 58, 69).designated, dict(dry)
    assert _project().redug is None
    r = B.redig_projects(False)
    assert r.ok and r.tiles == 1 and r.projects[1] == _project().id, dict(r)
    assert W.get(70, 58, 69).designated and W.get(70, 58, 69).dig_text == "h1"
    assert _project().redug["70,58,69"] == 1 and _project().redug_changed is None
    assert B.projects_report().open[1].dig.redig_due is None
    again = B.redig_projects(False)
    assert not again.ok and again.rejected, dict(again)
    for _ in range(B.REDIG_MAX):               # the game keeps taking it off
        W.get(70, 58, 69).designated = False
        B.redig_projects(False)
    W.get(70, 58, 69).designated = False
    d = B.projects_report().open[1].dig
    assert d.redig_due is None and d.stuck == 1, "past REDIG_MAX it stays stuck"


@test("A3 5: redig_projects is a bridge action (dry runs allowed), labelled, and asked by a planner rule")
def _():
    # (r5 p5) the loaded hub run on a stand-in ai-builder (tests/bridge_behaviour.py), not its text
    import bridge_behaviour as BB
    BB.wired(actions=["redig_projects"], dry=["redig_projects"])
    got, _, _ = BB.forwarded("redig_projects", {"dry_run": True}, "ai-builder", "redig_projects")
    assert got == [("redig_projects", [True])], got
    got, _, _ = BB.forwarded("redig_projects", {}, "ai-builder", "redig_projects")
    assert got == [("redig_projects", [False])], got
    import overseer
    assert "redig_projects" in overseer.SHORT_WORDS
    props = []
    pb._redig_rule([{"id": 4, "kind": "well", "phase": "dig", "dig": {"redig_due": 2}},
                    {"id": 5, "kind": "bedrooms", "phase": "dig", "dig": {"stuck": 3}}], props)
    assert len(props) == 1 and props[0].action == {"type": "redig_projects"} and "2 shaft" in props[0].reason, props
    props = []
    pb._redig_rule([{"id": 5, "kind": "bedrooms", "phase": "dig", "dig": {"stuck": 3}}], props)
    assert props == []


@test("A3 5: the hub refuses redig_projects while halted, but runs its dry run")
def _():
    H = TBM.H
    H.scripts = TBM.LUA.eval("""{
        ['ai-status'] = {is_halted = function() return true end, STATUS = {}},
        ['ai-builder'] = {redig_projects = function(dry) return {ok = true, dry_run = dry, tiles = 1} end},
    }""")
    try:
        H.action = TBM.LUA.table_from({"type": "redig_projects"})
        r = H.run("act", "{}")
        assert not r.ok, dict(r)
        H.action = TBM.LUA.table_from({"type": "redig_projects", "dry_run": True})
        r = H.run("act", "{}")
        assert r.ok and r.dry_run, dict(r)
    finally:
        H.scripts = None


# --- A3 6 and 14 ----------------------------------------------------------------------

def _stall_plan(dig: dict):
    class Mem:
        dig_seen = {"100": {"dug": dig["dug"], "tick": 1}}
    cfg = dict(pb.PLANNER_CONFIG)
    s = {"date": {"year": 1, "tick": 60 * 1200 + 10}}
    p = {"id": 100, "kind": "well", "phase": "dig", "dig": dig}
    props, notes = [], []
    pb._dig_stall_rule(s, Mem(), cfg, [p], props, notes)
    return [x.action for x in props]


@test("A3 6: no stalled furnish for a well whose last shaft levels are held or whose shaft is closed")
def _():
    base = {"dug": 19, "total": 21, "stuck": 0, "marked": 0, "digging": 0}
    furnish = {"type": "furnish_project", "project_id": 100, "stalled": True}
    assert furnish in _stall_plan(dict(base)), "the plain stall still furnishes"
    assert furnish not in _stall_plan(dict(base, held=2, shaft_open=False))
    assert furnish not in _stall_plan(dict(base, shaft_open=False))


@test("A3 14: the report's rows carry urgent and dig_done")
def _():
    TB.cavern_column()
    r = B.place_well(LUA.table_from({"cavern": True, "urgent": True}), LUA.table_from({"year": 148, "tick": 100}), False)
    assert r.ok, r.error
    o = B.projects_report().open[1]
    assert o.urgent is True and o.dig_done == "open", (o.urgent, o.dig_done)
    TB._reset(True)       # (a hospital is placed beside a stair)
    r = TB.start(kind="hospital", beds=8, urgent=True)
    assert r.ok, r.error
    assert B.projects_report().open[1].urgent is True


# --- A3 15 and 19 ----------------------------------------------------------------------

@test("A3 15: quickfort_apply digs nothing when neither dig guard can run")
def _():
    real = B.util_module
    B.util_module = LUA.eval("""function() return {
        dig_guard_data = function() error('guard boom') end,
        dig_guard_drop_deep = function() error('drop boom') end} end""")
    try:
        W.set(40, 40, 50, LUA.table_from({"shape": "WALL", "material": "STONE"}))
        cells = LUA.table_from([LUA.table_from({"x": 0, "y": 0, "text": "d"})])
        s = B.quickfort_apply("dig", cells, 50, 40, 40)
        assert B.stat(s, "dig_designated") == 0 and "guard boom" in s.dig_guard_error, dict(s)
        assert not W.get(40, 40, 50).designated
    finally:
        B.util_module = real
    s = B.quickfort_apply("dig", cells, 50, 40, 40)
    assert B.stat(s, "dig_designated") == 1 and W.get(40, 40, 50).designated


@test("A3 19: dig_stairwell undoes its levels when the game refuses one in the real run")
def _():
    import test_r33_builder as R33   # its own rig (a map with a main stair)
    R33._reset()
    q = R33.LUA.globals().reqscript("quickfort")
    real = q.apply_blueprint
    q.apply_blueprint = R33.LUA.eval("""function(real) return function(p)
        if not p.dry_run and p.command ~= 'undo' and p.data[62] then
            return {dig_designated = {value = 0}}
        end
        return real(p)
    end end""")(real)
    try:
        r = R33.B.dig_stairwell(R33.params(dir="east", elev_lo=62, elev_hi=66, min_dist=10, max_dist=40), False)
    finally:
        q.apply_blueprint = real
    assert not r.ok and "undone" in r.error, dict(r)
    left = [t for t in R33.W.tiles.values() if t.designated and t.dig_text in ("i", "j", "u")]
    assert not left, [(t.x, t.y, t.z) for t in left]


# --- A1 3: the section cache -----------------------------------------------------------

def _cache_rig(max_days):
    M = TBM.H.module()
    M.get_dwarves = TBM.LUA.eval("function(inc) return {total = 7}, nil end")
    calls = TBM.LUA.eval("{}")
    TBM.LUA.eval("""function(M, calls, max)
        M.SECTIONS = {}
        for _, n in ipairs({'a', 'b', 'c', 'd', 'live'}) do
            M.SECTIONS[n] = function() calls[n] = (calls[n] or 0) + 1; return {n = n} end
        end
        M.SECTION_CACHE_DAYS = {a = 1, b = 1, c = 1, d = 1}
        M.SECTION_MAX_DAYS = max
        M.SECTION_CACHE = {}
        M.SECTION_REBUILDS = 1
    end""")(M, calls, TBM.LUA.table_from(max_days))
    return M, calls


@test("A1 3: a section past its max age is rebuilt whatever the rotation count; the rest rotate")
def _():
    M, calls = _cache_rig({"a": 2, "b": 2})
    M.build_state(False)
    tick0 = TBM.H.df["global"]["cur_year_tick"]
    try:
        TBM.H.df["global"]["cur_year_tick"] = tick0 + 3 * 1200     # all four expired, a and b past their max
        s = M.build_state(False)
        got = {k: calls[k] for k in ("a", "b", "c", "d")}
        assert got["a"] == 2 and got["b"] == 2, got                 # both, beyond SECTION_REBUILDS = 1
        assert got["c"] + got["d"] == 3, got                        # one of the others by the rotation
        stale = "c" if got["c"] == 1 else "d"
        assert s.perf.cached[stale] and s.perf.cache_age[stale] == 3.0 and s.perf.cache_due[stale], dict(s.perf.cache_age)
        assert s.perf.cache_age["a"] is None and s.perf.cached["a"] is None
    finally:
        TBM.H.df["global"]["cur_year_tick"] = tick0


@test("A1 3: without max ages (the old rule) only SECTION_REBUILDS are rebuilt (the control)")
def _():
    M, calls = _cache_rig({})
    M.build_state(False)
    tick0 = TBM.H.df["global"]["cur_year_tick"]
    try:
        TBM.H.df["global"]["cur_year_tick"] = tick0 + 3 * 1200
        M.build_state(False)
        assert sum(calls[k] for k in ("a", "b", "c", "d")) == 5
    finally:
        TBM.H.df["global"]["cur_year_tick"] = tick0


@test("A1 3: a fresh cached copy shows its age, not due")
def _():
    M, calls = _cache_rig({})
    M.build_state(False)
    tick0 = TBM.H.df["global"]["cur_year_tick"]
    try:
        TBM.H.df["global"]["cur_year_tick"] = tick0 + 600
        s = M.build_state(False)
        assert s.perf.cache_age["a"] == 0.5 and s.perf.cache_due["a"] is None
    finally:
        TBM.H.df["global"]["cur_year_tick"] = tick0


@test("A1 3: every cached section has a max age, at least its cache days, and none over 12")
def _():
    M = TBM.H.module()
    days = {k: v for k, v in M.SECTION_CACHE_DAYS.items()}
    maxd = {k: v for k, v in M.SECTION_MAX_DAYS.items()}
    assert set(days) == set(maxd), set(days) ^ set(maxd)
    for k, v in days.items():
        assert v <= maxd[k] <= 12, (k, v, maxd[k])
    for k in ("needs", "homes", "siege", "killzones", "food_store", "disposal"):
        assert maxd[k] <= 2, k


@test("A1 3: the brain reads the ages: section_age, stale_sections, the PERF line")
def _():
    s = {"needs": {}, "homes": {}, "stocks": {},
         "perf": {"sections": {"stocks": 12.0, "needs": 0.1, "homes": 0.1}, "total_ms": 40,
                  "cached": {"needs": True, "homes": True}, "cache_age": {"needs": 1.6, "homes": 0.4},
                  "cache_due": {"needs": True}, "fps": 30}}
    assert perf.section_age(s, "needs") == 1.6 and perf.section_age(s, "homes") == 0.4
    assert perf.section_age(s, "stocks") == 0.0 and perf.section_age(s, "missing") is None
    assert perf.section_age({"needs": {}}, "needs") is None
    assert perf.stale_sections(s) == [("needs", 1.6)]
    assert "| stale needs 1.6d" in perf.perf_line(s), perf.perf_line(s)
    s["perf"]["cache_age"] = []          # an empty Lua table comes as a list
    assert perf.section_age(s, "needs") is None and perf.stale_sections(s) == []


if __name__ == "__main__":
    finish()
