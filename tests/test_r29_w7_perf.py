"""(R29 W7, Phase 13e) The AI's own cost cut where the live forts paid most,
and the numbers the soak comparison needs.

- brain/perf.py: each perf.jsonl row now says the population, the full and
  pulse reports of the day (counts and median ms), the real seconds the day
  took and the AI's share of them, and the day's costliest sections summed;
  `python brain/perf.py compare <fort folder>` sets each later game year
  beside year one (or, --first, the first year seen) at the same population.
- lua/ai-builder-projects.lua: the projects record (240-420 KB of JSON live)
  decoded only when its stored text changed; a copy of the last decode else.
- lua/ai-labor.lua: the shrub and water scans kept per centre (the centre's
  level changes between reports: the one copy missed nearly every time).
- lua/ai-hazards.lua / ai-bridge-report-dead.lua: block_magma reads a column
  once; the AI's levels and tombs read the projects record without a copy.

    python tests/test_r29_w7_perf.py
"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import perf  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None


def _perf(total, sections, cached=None, fps=50):
    return {"total_ms": total, "sections": sections, "cached": cached or {}, "fps": fps}


# --- the meter's new fields ----------------------------------------------------------------

@test("perf row: population, full and pulse reports (count, median), real seconds, AI share, the day's sections")
def _():
    clock = {"t": 1000.0}
    m = perf.Meter(write=False, clock=lambda: clock["t"])
    full = {"tier": "daily", "dwarves": {"total": 98}}
    pulse = {"tier": "pulse", "dwarves": {"total": 98}}
    assert m.note("A#1", 0, 0.0, 0, _perf(1000, {"labor": 100, "dead": 90}), state=full) is None   # the baseline
    m.note("A#1", 300, 1500.0, 2, _perf(300, {"labor": 20, "killzones": 1}, cached={"killzones": True}), state=pulse)
    m.note("A#1", 600, 3000.0, 4, _perf(2000, {"labor": 150, "missions": 300}), state=full)
    clock["t"] += 20.0                                                         # 20 real seconds
    row = m.note("A#1", 1200, 4000.0, 6, _perf(1800, {"labor": 140}), state=full)
    assert row["pop"] == 98 and row["full"] == 2 and row["pulse"] == 1, row
    assert row["full_ms"] == 2000 and row["pulse_ms"] == 300, row
    assert row["wall_s"] == 20.0 and row["ai_share"] == 0.2, row              # 4000 ms of 20 s
    # summed over the row's reports, built ones only (the cached killzones copy left out)
    assert row["sections"][:2] == [["labor", 310.0], ["missions", 300.0]], row
    assert all(k != "killzones" for k, _ in row["sections"]), row
    # the old fields as before
    assert row["ms_per_day"] == 4000.0 and row["calls"] == 6 and row["slow"][0] == ["labor", 140]
    # the next row starts afresh
    clock["t"] += 10.0
    row = m.note("A#1", 2400, 4500.0, 7, None, state={"dwarves": {}})
    assert row["full"] == 0 and row["pulse"] == 0 and row["full_ms"] is None and row["pop"] is None, row
    assert row["ai_share"] == 0.05 and row["sections"] == [], row
    # an older caller (no state) still gets a row
    m2 = perf.Meter(write=False)
    m2.note("B#1", 0, 0.0, 0, _perf(10, {}))
    r2 = m2.note("B#1", 1200, 50.0, 1, _perf(10, {}))
    assert r2["pop"] is None and r2["full"] == 1, r2


@test("note_perf hands the report to the meter: the row carries the population and the tier")
def _():
    import overseer
    import bridge
    overseer.PERF_METER = perf.Meter(write=False)
    s = {"date": {"year": 250, "tick": 100}, "dwarves": {"total": 42}, "tier": "daily",
         "perf": _perf(500, {"labor": 50})}
    overseer.note_perf(s, "C#1")
    bridge.CALL_MS["ms"] += 300.0
    overseer.note_perf(dict(s, date={"year": 250, "tick": 1400}), "C#1")
    row = overseer.PERF_METER.latest("C#1")
    # (the first report is the baseline's: its time is in the count the row starts from)
    assert row and row["pop"] == 42 and row["full"] == 1 and row["ai_share"] is None, row


# --- the soak comparison ---------------------------------------------------------------------

def _rows(year, pop, fps, ms, n=5, t0=1_000_000):
    base = t0 + (year - 1) * perf.TICKS_PER_YEAR
    return [{"tick": base + i * 1200, "pop": pop, "fps": fps, "ms_per_day": ms, "ai_share": 0.1}
            for i in range(n)]


@test("soak comparison: later years beside year one at the same population; pass within 20%, fail past it")
def _():
    rows = _rows(1, 52, 100, 1000) + _rows(2, 55, 85, 1100) + _rows(3, 58, 70, 1500)
    res = perf.soak_compare(rows)
    assert res["verdict"] == "fail", res
    y2, y3 = res["years"][2][0], res["years"][3][0]
    assert y2["pop"] == "50-59" and y2["ok"] and y2["fps_ratio"] == 0.85, y2
    assert not y3["ok"] and y3["fps_ratio"] == 0.7 and y3["now"]["ms_per_day"] == 1500, y3
    assert perf.soak_compare(rows[:10])["verdict"] == "pass"
    # a bin with too few rows, or a population year one never had: not compared
    assert perf.soak_compare(_rows(1, 20, 100, 1) + _rows(2, 90, 50, 1))["verdict"] == "no overlap"
    assert perf.soak_compare([])["verdict"] == "no overlap"
    # --first: against the first year each population was seen in
    grow = _rows(1, 20, 100, 1) + _rows(2, 90, 100, 1) + _rows(3, 95, 60, 1)
    assert perf.soak_compare(grow)["verdict"] == "no overlap"
    res = perf.soak_compare(grow, ref="first")
    assert res["verdict"] == "fail" and res["years"][3][0]["ref_year"] == 2, res
    text = perf.compare_text(res)
    assert "year 3 pop   90-99" in text and "SLOWER" in text and "in year 2" in text, text


@test("soak comparison: rows written before R29 take their population from timeline.csv; the command line")
def _():
    d = Path(tempfile.mkdtemp())
    (d / "timeline.csv").write_text("day,pop,drink_pd\n800,30,1\n900,60,1\n", encoding="utf-8")
    pops = perf.timeline_pops(d / "timeline.csv")
    assert pops == {800: 30, 900: 60}
    rows = [{"tick": 850 * 1200}, {"tick": 950 * 1200, "pop": 61}, {"tick": 100 * 1200}]
    perf.fill_pop(rows, pops)
    assert rows[0]["pop"] == 30 and rows[1]["pop"] == 61 and "pop" not in rows[2], rows
    assert perf.timeline_pops(d / "none.csv") == {}
    lines = [json.dumps(r) for r in _rows(1, 40, 100, 900, t0=800 * 1200) + _rows(2, 41, 95, 950, t0=800 * 1200)]
    (d / perf.PERF_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert perf.main(["compare", str(d)]) == 0
    assert "pass" in buf.getvalue() and "pop   40-49" in buf.getvalue(), buf.getvalue()
    with contextlib.redirect_stdout(io.StringIO()):
        assert perf.main([]) == 2


# --- the Lua cuts ---------------------------------------------------------------------------

def _const(path: Path, name: str) -> str:
    """A string constant of another test file, read, not imported (it runs its tests)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


@test("projects record: decoded once while its stored text stays the same; a changed text decoded again")
def _():
    if LuaRuntime is None:
        skip("needs lupa")
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(ROOT / "lua")
    harness = _const(ROOT / "tests" / "test_builder.py", "HARNESS")
    layouts = (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8")
    builder = (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8")
    B, W = lua.execute(harness, layouts, builder)
    r = lua.execute("""
    local B, W = ...
    local P = dfhack.persistent
    local reads, rev = 0, {}
    local get = P.getSiteData
    P.getSiteData = function(k, d) if k == 'ai-overseer/projects' then reads = reads + 1 end return get(k, d) end
    local save = P.saveSiteData
    P.saveSiteData = function(k, v) rev[k] = (rev[k] or 0) + 1; return save(k, v) end
    -- the stored text: a mark that changes with every write (DFHack: the JSON itself)
    P.getSiteDataString = function(k) return W.persist[k] and ('rev ' .. tostring(rev[k] or 0)) or nil end
    B.PROJECTS_RAW_CACHE = nil
    B.save_projects({next_id = 2, list = {{id = 1, kind = 'bedrooms', phase = 'dig'}}})
    local a = B.load_projects()
    local b = B.load_projects()
    local first = reads
    a.list[1].phase = 'changed by a caller'           -- a caller's copy is its own
    local c = B.load_projects()
    local same = c.list[1].phase == 'dig' and a ~= b and b ~= c
    B.save_projects({next_id = 3, list = {{id = 1, kind = 'bedrooms', phase = 'done'}}})
    local d = B.load_projects()
    local after_save = reads
    -- another writer (not save_projects): its text differs, so it is decoded again
    W.persist['ai-overseer/projects'] = {next_id = 9, list = {}}
    rev['ai-overseer/projects'] = 99
    local e = B.load_projects()
    -- no getSiteDataString (an older DFHack, the other tests' fakes): every read decodes
    P.getSiteDataString = nil
    local n0 = reads
    B.load_projects(); B.load_projects()
    return {first = first, same = same, d = d.list[1].phase, after_save = after_save,
            e = e.next_id, old = reads - n0, cache = B.PROJECTS_RAW_CACHE == nil}
    """, B, W)
    assert r["first"] == 1, dict(r)          # two loads, one decode
    assert r["same"], dict(r)
    assert r["d"] == "done" and r["after_save"] == 2, dict(r)
    assert r["e"] == 9, dict(r)
    assert r["old"] == 2 and r["cache"], dict(r)


@test("labor scans: one copy per centre, each for its week; the marked shrubs still clear them all")
def _():
    if LuaRuntime is None:
        skip("needs lupa")
        return
    from lua_modules_util import module_src
    fake = _const(ROOT / "tests" / "test_labor.py", "FAKE")
    old = "env.reqscript = function() return {found_center = function() return {x = 10, y = 10, z = 10, what = 'the wagon'} end} end"
    assert old in fake
    fake = fake.replace(old, "env.reqscript = function() return {found_center = function() return spec.centre end} end")
    lua = LuaRuntime(unpack_returned_tuples=True)
    spec = lua.table_from({"units": lua.table_from([]), "tools": lua.table_from([]),
                           "details": lua.table_from([]), "dig": 0})
    env = lua.execute(fake, module_src("ai-labor.lua"), spec)[0]
    r = lua.execute("""
    local env, spec = ...
    env.df.global.cur_year, env.df.global.cur_year_tick = 250, 0
    local function at(z, tick)
        spec.centre = {x = 10, y = 10, z = z, what = 'the dwarves'}
        env.df.global.cur_year_tick = tick
        return env.survey().ms.scanned == true
    end
    local out = {}
    out[1] = at(10, 0)          -- first sight: scanned
    out[2] = at(11, 100)        -- the centre's level moved: scanned
    out[3] = at(10, 200)        -- back: the first copy (the one copy kept missed here)
    out[4] = at(11, 300)        -- and the second
    out[5] = at(10, 7 * 1200 + 1)   -- a week on: scanned again
    env.SCAN_CACHE = nil        -- (the gather action's reset)
    out[6] = at(11, 7 * 1200 + 2)
    local n = 0
    for _ in pairs(env.SCAN_CACHE.by) do n = n + 1 end
    out[7] = n
    return out
    """, env, spec)
    got = [r[i] for i in range(1, 8)]
    assert got == [True, True, False, False, True, True, 1], got


@test("block_magma: the same tiles found with the column read once")
def _():
    src = (ROOT / "lua" / "ai-hazards.lua").read_text(encoding="utf-8")
    assert "local col = des[lx]" in src and "local d = col[ly]" in src
    if LuaRuntime is None:
        skip("needs lupa")
        return
    from lua_modules_util import module_src
    lua = LuaRuntime(unpack_returned_tuples=True)
    r = lua.execute("""
    local src = ...
    local des = {}
    for x = 0, 15 do des[x] = {}; for y = 0, 15 do des[x][y] = {flow_size = 0, liquid_type = false} end end
    des[3][4] = {flow_size = 7, liquid_type = true, feature_local = true}
    des[5][6] = {flow_size = 2, liquid_type = 1}
    des[7][7] = {flow_size = 7, liquid_type = false}      -- water
    local block = {flags = {update_liquid = false}, designation = des}
    local env = setmetatable({}, {__index = _G})
    env.dfhack = {maps = {getTileBlock = function() return block end}, persistent = {}}
    env.df = {global = {}}
    assert(load(src, 'ai-hazards', 't', env))()
    local list, moving = env.block_magma(2, 1, 9, true)
    local none, mv2 = env.block_magma(2, 1, 9, false)
    return #list, list[1].x + list[2].x, list[1].feature or list[2].feature, moving, #none, mv2
    """, module_src("ai-hazards.lua"))
    n, xs, feat, moving, none, mv2 = r
    assert n == 2 and xs == 32 + 3 + 32 + 5 and feat is True and moving is False, r
    assert none == 0 and mv2 is False, r


if __name__ == "__main__":
    finish()
