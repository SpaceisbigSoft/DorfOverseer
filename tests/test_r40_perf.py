"""(0.105.40, 13e, E1) What the AI costs the game: the bridge's perf report
section (each section timed, the cached ones, total, FPS), the digest's
PERF line, the AI's ms per game day (brain/perf.py, perf.jsonl), the
health check's speed lines, the scorecard's column, and the slow back-off
(perf_slow_cycle_factor, never while a threat is on).

    python tests/test_r40_perf.py
"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import digest  # noqa: E402
import health_check as hc  # noqa: E402
import overseer  # noqa: E402
import perf  # noqa: E402
import scorecard  # noqa: E402
from planner_config import PLANNER_CONFIG  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None


# --- the bridge's perf section (Lua) ---------------------------------------------------

def _harness_src() -> str:
    """The stub DFHack of tests/test_bridge_memory.py (its HARNESS), read, not imported."""
    tree = ast.parse((ROOT / "tests" / "test_bridge_memory.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "HARNESS" for t in node.targets):
            return node.value.value
    raise AssertionError("no HARNESS in test_bridge_memory.py")


if LuaRuntime is not None:
    LUA = LuaRuntime(unpack_returned_tuples=True)
    H = LUA.execute(_harness_src(), (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8"), str(ROOT / "lua"))

    def stub_module():
        M = H.module()
        M.get_dwarves = LUA.eval("function(inc) return {total = 7}, nil end")
        LUA.eval("""function(M)
            M.SECTIONS = {
                live = function() return {n = 1, list = {1, 2}} end,
                slow = function() local x = 0; for i = 1, 200000 do x = x + i end; return {sum = x} end,
                kept = function() return {k = 'v'} end,
            }
            M.SECTION_CACHE_DAYS = {kept = 3}
            M.SECTION_CACHE = {}
        end""")(M)
        return M

    def plain(v):
        """A Lua table as Python (dicts; a 1..n table as a list)."""
        if LUA.eval("type")(v) != "table":
            return v
        keys = list(v.keys())
        if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
            return [plain(v[k]) for k in sorted(keys)]
        return {k: plain(v[k]) for k in keys}

    @test("perf section: every section's ms, the cached ones, total_ms, walks, fps and the game tick")
    def _():
        M = stub_module()
        H.df["global"]["enabler"] = LUA.table_from({"calculated_fps": 42})
        try:
            s1 = M.build_state(False)
            p = plain(s1.perf)
            assert set(p) >= {"sections", "cached", "total_ms", "units_walks", "items_walks", "game_tick"}, p
            assert set(p["sections"]) == {"live", "slow", "kept"}, p
            assert all(isinstance(v, (int, float)) and v >= 0 for v in p["sections"].values()), p
            assert p["cached"] in ({}, []) and p["fps"] == 42, p          # first report: nothing from the cache
            assert p["units_walks"] == 0 and p["items_walks"] == 0
            assert p["game_tick"] == M.abs_tick() and p["total_ms"] >= p["sections"]["slow"], p
            s2 = M.build_state(False)
            p2 = plain(s2.perf)
            assert p2["cached"] == {"kept": True}, p2                     # the second: kept from the cache
            assert "kept" in p2["sections"]
            # the pulse has it too
            M.PULSE_SECTIONS = LUA.table_from(["live"])
            assert set(plain(M.build_state(False, "pulse").perf)["sections"]) == {"live"}
        finally:
            H.df["global"]["enabler"] = None

    @test("perf section: the timing hooks change no other section; the walks come from REPORT_CTX")
    def _():
        M = stub_module()
        s = M.build_state(False)
        keys = set(s.keys())
        assert keys == {"live", "slow", "kept", "tier", "_timing", "perf"}, keys
        assert plain(s.live) == {"n": 1, "list": [1, 2]} and plain(s.kept) == {"k": "v"}
        assert s.tier == "daily" and "dwarves" in plain(s._timing)
        assert plain(s.perf).get("fps") is None                           # no enabler: no fps, no failure
        # the sections' values are the very tables the sections returned (no copy, no change)
        M.SECTIONS.live = LUA.eval("(function() local t = {x = 1}; return function() return t end end)()")
        a, b = M.build_state(False).live, M.SECTIONS.live()
        assert LUA.eval("rawequal")(a, b)
        M.REPORT_CTX = LUA.table_from({"units_walks": 2, "items_walks": 1})
        try:
            p = plain(M.perf_section(LUA.table(), LUA.table(), 12.34, 99))
            assert p["units_walks"] == 2 and p["items_walks"] == 1 and p["total_ms"] == 12.3 and p["game_tick"] == 99, p
            M.REPORT_CTX = LUA.eval("setmetatable({}, {__index = function() error('boom') end})")
            assert "boom" in str(M.perf_section(LUA.table(), LUA.table(), 1, 1).error)   # never fails the report
        finally:
            M.REPORT_CTX = None

    @test("every lua/*.lua and lua/gui/*.lua still compiles (Lua 5.3)")
    def _():
        rt = LuaRuntime()
        check = rt.eval("function(src, name) local f, err = load(src, name, 't', {}); return err end")
        files = sorted((ROOT / "lua").glob("*.lua")) + sorted((ROOT / "lua" / "gui").glob("*.lua"))
        bad = {p.name: check(p.read_text(encoding="utf-8"), p.name) for p in files}
        bad = {k: v for k, v in bad.items() if v}
        assert files and not bad, bad


# --- the digest -----------------------------------------------------------------------

PERF = {"sections": {"military": 412.5, "industry": 300.0, "labor": 51.2, "date": 0.1, "logistics": 900.0},
        "cached": {"logistics": True}, "total_ms": 1210.4, "units_walks": 1, "items_walks": 2, "fps": 37,
        "game_tick": 123}


def base_state() -> dict:
    return {"date": {"year": 3, "tick": 100, "day": 1, "month": "Granite", "season": "spring"},
            "dwarves": {"total": 5}, "fort": {"name": "F", "site_id": 1}}


@test("digest: PERF line with the three slowest built sections (cached left out), total and fps")
def _():
    line = digest.perf_line({"perf": PERF})
    assert line == "PERF report 1210 ms | slowest military 412, industry 300, labor 51 | cached 1 | fps 37", line
    assert perf.slow_sections(PERF) == [("military", 412.5), ("industry", 300.0), ("labor", 51.2)]
    out = digest.digest(dict(base_state(), perf=json.loads(json.dumps(PERF))))
    assert "\nPERF report 1210 ms" in out, out
    # no perf section (an older bridge), a failed one, an empty one: no line, and no error for a missing one
    s = base_state()
    out = digest.digest(s)
    assert "PERF" not in out and "perf" not in s["_errors"], out
    assert digest.perf_line({"perf": {"error": "x"}}) == "" and digest.perf_line({"perf": []}) == ""
    s = dict(base_state(), perf={"error": "boom"})
    digest.normalize(s)
    assert s["_errors"].get("perf") == "boom" and s["perf"] == {}
    s = dict(base_state(), perf=[])                         # DFHack's JSON writes an empty table as []
    digest.normalize(s)
    assert s["perf"] == {} and "perf" not in s["_errors"]


# --- the AI's ms per game day -----------------------------------------------------------

@test("ms per game day: summed call ms over the game days passed; a row a game day, to perf.jsonl")
def _():
    assert perf.ms_per_day(600, 2400) == 300.0 and perf.ms_per_day(50, 600) == 100.0
    assert perf.ms_per_day(10, 0) is None and perf.ms_per_day(None, 1200) is None
    folder = Path(tempfile.mkdtemp()) / "F-1"
    m = perf.Meter()
    assert m.note("F#1", 1000, 100.0, 3, PERF, folder) is None             # the baseline
    assert m.note("F#1", 1600, 300.0, 9, PERF, folder) is None             # half a day: not yet
    row = m.note("F#1", 2200, 700.0, 13, PERF, folder)                     # a day: 600 ms
    assert row["ms_per_day"] == 600.0 and row["ai_ms"] == 600.0 and row["days"] == 1.0, row
    assert row["calls"] == 10 and row["fps"] == 37 and row["report_ms"] == 1210.4, row
    assert row["slow"][0] == ["military", 412.5]
    row = m.note("F#1", 2200 + 3600, 1000.0, 20, None, folder)             # three days: 300 ms
    assert row["ms_per_day"] == 100.0 and row["report_ms"] is None, row
    rows = perf.read_rows(folder / perf.PERF_FILE)
    assert [r["ms_per_day"] for r in rows] == [600.0, 100.0] and m.latest("F#1")["ms_per_day"] == 100.0
    assert m.note("F#1", 50, 2000.0, 30, None, folder) is None             # an older save: a new baseline
    assert m.note("F#1", 1250, 2100.0, 31, None, folder)["ms_per_day"] == 100.0
    assert m.note("F#1", "bad", 1, 1, None, folder) is None                # never raises
    # bounded: the file is capped (one old copy)
    perf.PERF_MAX_BYTES, keep = 200, perf.PERF_MAX_BYTES
    try:
        for i in range(10):
            m.note("F#1", 10_000 + i * 1200, 3000.0 + i, 40, None, folder)
        assert (folder / perf.PERF_FILE).stat().st_size < 1000 and (folder / "perf.old.jsonl").exists()
    finally:
        perf.PERF_MAX_BYTES = keep


@test("the bridge sums every call's ms; note_perf turns it into the soak row's ai_ms_day")
def _():
    import bridge
    before = dict(bridge.CALL_MS)
    bridge.note_call_ms(12.5)
    assert bridge.CALL_MS["ms"] == before["ms"] + 12.5 and bridge.CALL_MS["calls"] == before["calls"] + 1

    class FakeDF:
        def run_json(self, *a, **k):
            return {"ok": True}
    b = bridge.Bridge.__new__(bridge.Bridge)
    b.df, b.log = FakeDF(), bridge._setup_logger()
    n = bridge.CALL_MS["calls"]
    b._call("version")
    b.act({"type": "x"})
    assert bridge.CALL_MS["calls"] == n + 2
    overseer.PERF_METER = perf.Meter(write=False)
    overseer.PERF_LAST.clear()
    s = dict(base_state(), perf=PERF)
    overseer.note_perf(s, "F#1")
    bridge.CALL_MS["ms"] += 240.0
    s2 = dict(s, date=dict(s["date"], tick=100 + 2400))
    overseer.note_perf(s2, "F#1")
    assert overseer.PERF_LAST["ai_ms_day"] == 120.0, overseer.PERF_LAST
    assert overseer.PERF_LAST["perf_slow"] == {"military": 412.5, "industry": 300.0, "labor": 51.2}
    assert overseer.PERF_LAST["threat"] is False
    overseer.note_perf({"date": "broken"}, "F#1")                           # never raises


# --- the back-off ---------------------------------------------------------------------

@test("back-off: the full report perf_slow_cycle_factor times apart while slow; never while a threat is on")
def _():
    assert PLANNER_CONFIG["perf_slow_cycle_factor"] == 2
    assert perf.cycle_factor(False, False, 2) == 1
    assert perf.cycle_factor(True, False, 2) == 2 and perf.cycle_factor(True, False, 3) == 3
    assert perf.cycle_factor(True, True, 2) == 1                            # a threat keeps the cadence
    assert perf.cycle_factor(True, False, 0) == 1 and perf.cycle_factor(True, False, "x") == 1
    calm = base_state()
    assert not perf.threat_active(calm)
    for s in ({"others_on_map": {"threats_that_can_reach_dwarves": 2}},
              {"others_on_map": {"threats": [{"invader": True}]}},
              {"others_on_map": {"threats": [{"great_danger": True}]}},
              {"world": {"sieges": [{"active": True, "n": 1}]}},
              {"civ_alert": True}):
        assert perf.threat_active(dict(calm, **s)), s
    assert not perf.threat_active(dict(calm, world={"sieges": [{"active": False, "n": 3}]}))
    assert not perf.threat_active(dict(calm, others_on_map={"threats": [{"name": "x", "can_reach_dwarves": False}]}))
    overseer.PERF_LAST.clear()
    assert overseer.slow_factor(30, True) == 2 and overseer.slow_factor(None, True) == 1
    assert overseer.slow_factor(30, False) == 1                             # attended: as before, no stretch
    overseer.note_perf(dict(calm, others_on_map={"threats_that_can_reach_dwarves": 1}), "T#1")
    assert overseer.PERF_LAST["threat"] is True and overseer.slow_factor(30, True) == 1
    overseer.note_perf(calm, "T#1")
    assert overseer.slow_factor(30, True) == 2
    keep = PLANNER_CONFIG["perf_slow_cycle_factor"]
    PLANNER_CONFIG["perf_slow_cycle_factor"] = 4
    try:
        assert overseer.slow_factor(30, True) == 4
    finally:
        PLANNER_CONFIG["perf_slow_cycle_factor"] = keep
    # the main loop asks slow_factor for the full report's spacing
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    assert "every = PLAN_EVERY_TICKS * slow_factor(fps_low, args.unattended)" in src


# --- the health check and the scorecard ------------------------------------------------

@test("health check speed: AI ms per game day, the slowest sections by perf, the FPS trend")
def _():
    rows = [{"in_fort": True, "paused": False, "fort": "F#1", "fps": 100 - 5 * i, "pop": 50,
             "ai_ms_day": 400 + 10 * i, "perf_slow": {"military": 400 + i, "industry": 300}} for i in range(9)]
    flags, plain = hc.fps_flags(rows)
    assert "AI ms per game day: median 440, latest 480 (9 rows)" in plain, plain
    assert "slowest sections (perf), median ms: military 404, industry 300" in plain, plain
    assert "FPS trend: 95 -> 80 -> 65" in plain, plain
    assert not [f for f in flags if "AI" in f]
    # rows without the AI's numbers (an older overseer): the page reads as before
    old = [{k: v for k, v in r.items() if k not in ("ai_ms_day", "perf_slow")} for r in rows]
    plain = hc.fps_flags(old)[1]
    assert len(plain) == 1 and plain[0].startswith("FPS site 1"), plain


@test("scorecard: the health table's AI ms per game day row (only when a fort has perf.jsonl)")
def _():
    d = Path(tempfile.mkdtemp())
    (d / perf.PERF_FILE).write_text("\n".join(json.dumps(r) for r in (
        {"time": "2026-11-01T00:00:00", "ms_per_day": 900},       # before the run: left out
        {"time": "2026-11-10T00:00:00", "ms_per_day": 300},
        {"time": "2026-11-10T01:00:00", "ms_per_day": 500},
        {"time": "2026-11-10T02:00:00", "ms_per_day": 400})) + "\nnot json\n", encoding="utf-8")

    class F:
        fort_dir, run = d, "2026-11-05T00:00:00"
    assert scorecard.ai_ms_day(F) == 400
    F.run = None
    assert scorecard.ai_ms_day(F) == 500
    F.fort_dir = Path(tempfile.mkdtemp())
    assert scorecard.ai_ms_day(F) is None
    F.fort_dir = None
    assert scorecard.ai_ms_day(F) is None
    src = (ROOT / "brain" / "scorecard.py").read_text(encoding="utf-8")
    assert "AI ms per game day (median, perf.jsonl)" in src and "if any(v is not None for v in ai_ms.values())" in src


if __name__ == "__main__":
    finish()
