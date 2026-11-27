"""(F3a) The report's deadline and the bridge's side of the kept report
(lua/ai-bridge.lua build_state_body, run_action, cmd_state), in a real Lua
engine (pip install lupa; skipped without it):

- past REPORT_DEADLINE_MS a section that would be rebuilt and has a cached
  copy sends the copy (perf.deferred, perf.deadline_hit_ms); one with no copy
  is still built; one deferred REPORT_DEFER_MAX reports in a row is built
  whatever the deadline, and the deferred ones go first next report
- `state --tier pulse --sections a,b`: those sections built too, named in
  sections_extra (unknown names left out)
- an action's answer names the sections it changed (`invalidates`) only for
  an action CACHE_INVALIDATES knows (and refusals, dry runs: none)

    python tests/test_f4_report_deadline.py
"""

from __future__ import annotations

import subprocess
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import make_test, finish, code_has  # noqa: E402

BRIDGE = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
test = make_test()


@test("F3a: ai-bridge.lua and ai-bridge-sections.lua compile (texluac -p, where there is one)")
def _():
    luac = shutil.which("texluac") or shutil.which("luac5.3") or shutil.which("luac")
    if not luac:
        return
    for f in ("ai-bridge.lua", "ai-bridge-sections.lua"):
        r = subprocess.run([luac, "-p", str(ROOT / "lua" / f)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


@test("F3a: cmd_state reads --sections and hands them to build_state")
def _():
    assert code_has(BRIDGE, "if flags['--sections'] then")
    assert code_has(BRIDGE, "local state = build_state(include_units, tier, extra)")


try:
    from lupa.lua53 import LuaRuntime  # noqa: F401
except ImportError:
    LuaRuntime = None

if LuaRuntime is not None:
    import test_bridge_memory as TBM  # noqa: E402   (the bridge rig)

    def _rig(deadline=0, defer_max=3):
        """Sections a b c d cached a day, live uncached, p1 the pulse's; all built
        once, then three days on: a, b, c, d all due (SECTION_REBUILDS = 4, so
        without the deadline every one would be rebuilt)."""
        M = TBM.H.module()
        M.get_dwarves = TBM.LUA.eval("function(inc) return {total = 7}, nil end")
        calls = TBM.LUA.eval("{}")
        TBM.LUA.eval("""function(M, calls)
            M.SECTIONS = {}
            for _, n in ipairs({'a', 'b', 'c', 'd', 'live', 'p1'}) do
                M.SECTIONS[n] = function() calls[n] = (calls[n] or 0) + 1; return {n = n, k = calls[n]} end
            end
            M.SECTION_CACHE_DAYS = {a = 1, b = 1, c = 1, d = 1}
            M.SECTION_MAX_DAYS = {}
            M.SECTION_CACHE = {}
            M.SECTION_REBUILDS = 4
            M.PULSE_SECTIONS = {'p1'}
            M.SECTION_DEFERRED = {}
        end""")(M, calls)
        M.REPORT_DEADLINE_MS = None
        M.build_state(False)              # every copy made
        M.REPORT_DEADLINE_MS = deadline
        M.REPORT_DEFER_MAX = defer_max
        return M, calls

    def _days_on(n):
        TBM.H.df["global"]["cur_year_tick"] = TBM.H.df["global"]["cur_year_tick"] + n * 1200

    def _list(t):
        return [t[i] for i in range(1, len(t) + 1)] if t is not None else []

    @test("F3a: past the deadline the due cached sections send their copy; the uncached one is still built")
    def _():
        tick0 = TBM.H.df["global"]["cur_year_tick"]
        try:
            M, calls = _rig(deadline=0)
            _days_on(3)
            s = M.build_state(False)
            assert all(calls[k] == 1 for k in "abcd"), {k: calls[k] for k in "abcd"}
            assert calls["live"] == 2, "no cache: built"
            assert sorted(_list(s.perf.deferred)) == ["a", "b", "c", "d"], _list(s.perf.deferred)
            assert s.perf.deadline_ms == 0 and s.perf.deadline_hit_ms is not None
            assert s.a.k == 1 and s.perf.cached["a"] and s.perf.cache_due["a"] and s.perf.cache_age["a"] == 3.0
            assert M.SECTION_DEFERRED["a"] == 1
        finally:
            TBM.H.df["global"]["cur_year_tick"] = tick0

    @test("F3a: without a deadline (nil or < 0) every due section is rebuilt (the control)")
    def _():
        tick0 = TBM.H.df["global"]["cur_year_tick"]
        try:
            for dl in (None, -1):
                M, calls = _rig(deadline=dl)
                _days_on(3)
                s = M.build_state(False)
                assert all(calls[k] == 2 for k in "abcd"), {k: calls[k] for k in "abcd"}
                assert s.perf.deferred is None
                TBM.H.df["global"]["cur_year_tick"] = tick0
        finally:
            TBM.H.df["global"]["cur_year_tick"] = tick0

    @test("F3a: a generous deadline defers nothing")
    def _():
        tick0 = TBM.H.df["global"]["cur_year_tick"]
        try:
            M, calls = _rig(deadline=60000)
            _days_on(3)
            s = M.build_state(False)
            assert all(calls[k] == 2 for k in "abcd") and s.perf.deferred is None
            assert s.perf.deadline_ms == 60000
        finally:
            TBM.H.df["global"]["cur_year_tick"] = tick0

    @test("F3a: deferred REPORT_DEFER_MAX times in a row, a section is built whatever the deadline")
    def _():
        tick0 = TBM.H.df["global"]["cur_year_tick"]
        try:
            M, calls = _rig(deadline=0, defer_max=3)
            _days_on(3)
            for _ in range(3):
                s = M.build_state(False)
                assert len(_list(s.perf.deferred)) == 4
            s = M.build_state(False)          # the fourth: all four built
            assert all(calls[k] == 2 for k in "abcd"), {k: calls[k] for k in "abcd"}
            assert s.perf.deferred is None and M.SECTION_DEFERRED["a"] is None
            assert s.a.k == 2 and not s.perf.cached["a"]
        finally:
            TBM.H.df["global"]["cur_year_tick"] = tick0

    @test("F3a: the deferred sections go first in the next report")
    def _():
        tick0 = TBM.H.df["global"]["cur_year_tick"]
        try:
            M, calls = _rig(deadline=0)
            _days_on(3)
            M.SECTION_DEFERRED["d"] = 2
            M.SECTION_DEFERRED["c"] = 1
            order = TBM.LUA.eval("{}")
            TBM.LUA.eval("""function(M, order)
                for n, f in pairs(M.SECTIONS) do
                    M.SECTIONS[n] = function(ctx) table.insert(order, n); return f(ctx) end
                end
            end""")(M, order)
            M.REPORT_DEADLINE_MS = 60000       # nothing deferred: the order alone
            M.build_state(False)
            got = _list(order)
            assert got[:2] == ["d", "c"], got
            assert M.SECTION_DEFERRED["d"] is None and M.SECTION_DEFERRED["c"] is None
        finally:
            TBM.H.df["global"]["cur_year_tick"] = tick0

    @test("F3a: a pulse with extra sections builds them too, named in sections_extra")
    def _():
        M, calls = _rig(deadline=None)
        s = M.build_state(False, "pulse", TBM.LUA.table_from(["live", "nosuch", "p1", "a"]))
        assert _list(s.sections_extra) == ["live", "a"], _list(s.sections_extra)
        assert s.live is not None and s.a is not None and s.p1 is not None and s.b is None
        assert calls["live"] == 2, "uncached: built"
        s = M.build_state(False, "pulse")
        assert s.sections_extra is None and s.live is None

    @test("F3a: an action's answer names the sections it changed, only when CACHE_INVALIDATES knows it")
    def _():
        M = TBM.H.module()
        TBM.LUA.eval("""function(M)
            M.ACTIONS.known_x = function(a) return {ok = true} end
            M.ACTIONS.unknown_x = function(a) return {ok = true} end
            M.ACTIONS.refused_x = function(a) return {ok = false, rejected = true, error = 'no', stale = {'logistics'}} end
            M.CACHE_INVALIDATES.known_x = {'needs', 'dead'}
            M.CACHE_INVALIDATES.refused_x = {'needs'}
            M.SECTION_CACHE = {needs = {tick = 0}, dead = {tick = 0}, logistics = {tick = 0}}
        end""")(M)
        r = M.run_action(TBM.LUA.table_from({"type": "known_x"}))
        assert _list(r.invalidates) == ["needs", "dead"], _list(r.invalidates)
        assert M.SECTION_CACHE["needs"] is None
        r = M.run_action(TBM.LUA.table_from({"type": "unknown_x"}))
        assert r.invalidates is None, "unknown: the brain reads the full report"
        r = M.run_action(TBM.LUA.table_from({"type": "refused_x"}))
        assert _list(r.invalidates) == ["logistics"], "a refusal: only what it called stale"
        r = M.run_action(TBM.LUA.table_from({"type": "known_x", "dry_run": False}))
        assert _list(r.invalidates) == ["needs", "dead"]


if __name__ == "__main__":
    finish("lupa is not installed: only the compile and code checks ran" if LuaRuntime is None else None)
