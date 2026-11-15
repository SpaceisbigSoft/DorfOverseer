"""(0.105.51) The report's speed during dangers (R3 live run, 15 Nov).

perf.jsonl of the six R3 forts (region4-1430): AI ms per game day median
1.0-3.0 s; the full report's time rose 1.0 -> 2.1 s in B, E and F. The
sections over 150 ms median (when among a report's three slowest):
shelter_plan 1.0-2.3 s (only during a danger), killzones 170-370 ms
(nearly every report), then artifacts, benches, missions, forestry,
constructions, threats, stuck (150-210 ms in the slowest forts). By time
over all reports: killzones 151 ms a report, labor 68, forestry 60,
env_hazards 51, benches 44.

  * lua/ai-shelter-plan.lua: a full report's slice budget 700 ms (was
    3000), 1000 ms while there is no plan yet; the plan kept, nothing
    walked, while nothing changed (the same ways in and pick, the same
    dangers, none inside the fort) up to SHELTER_PLAN_KEEP_TICKS;
  * lua/ai-killzone.lua: an entrance's corridor plan (the walk in from the
    opening) kept KZ_PLAN_TICKS while the gate scan, the entrance and the
    held ways in are the same; dropped by build_killzone;
  * lua/ai-forestry.lua: the report's tree census walked in slices;
  * lua/ai-bridge.lua: benches cached (2 days, at most 4), read again
    after bench_caps.

    python tests/test_k51_report_speed.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402

import test_k48_shelter as TSH  # noqa: E402   (the shelter rig; its tests run only when it is run itself)
import test_killzones as TKZ  # noqa: E402
import test_item10 as T10  # noqa: E402

LUA_DIR = ROOT / "lua"
R3 = Path("/home/claude/r3")


# --- the evidence: the real perf rows ---------------------------------------------------------

def _perf_rows():
    rows = []
    for f in sorted(R3.glob("*/logs/forts/region4-1430/perf.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


# two real rows (DF-AI, 15 Nov): the shelter plan and the kill zones the slowest
REAL_ROWS = [
    {"time": "2026-11-15T10:52:16", "tick": 104063347, "days": 1.04, "ai_ms": 11224.4, "ms_per_day": 10827.4,
     "calls": 10, "report_ms": 6526.0, "slow": [["shelter_plan", 3190.0], ["miasma", 590.0], ["military", 271.0]],
     "fps": 25},
    {"time": "2026-11-14T22:01:09", "tick": 100827357, "days": 1.02, "ai_ms": 864.8, "ms_per_day": 847.1,
     "calls": 8, "report_ms": 361.0, "slow": [["killzones", 137.0], ["industry", 54.0], ["labor", 52.0]], "fps": 100},
]


@test("evidence: the slowest sections of the R3 perf rows are the ones this round budgets or caches")
def _():
    rows = _perf_rows() or REAL_ROWS
    by = {}
    for r in rows:
        for name, ms in r.get("slow", []):
            by.setdefault(name, []).append(ms)
    med = lambda v: sorted(v)[len(v) // 2]           # noqa: E731
    assert med(by["shelter_plan"]) >= 1000, med(by["shelter_plan"])
    assert med(by["killzones"]) >= 130, med(by["killzones"])
    # the shelter plan's slowest rows came near its old full-report budget (3000 ms)
    assert max(by["shelter_plan"]) > 2500


# --- 1. the shelter plan ----------------------------------------------------------------------

def _shelter():
    lua, env, w = TSH.fake()
    TSH.civ(lua, w, 3, 3, 99)
    TSH.civ(lua, w, 4, 4, 99)
    b = TSH.beast(lua, w, 0, 1, 100)
    return lua, env, w, b


def _tick(lua, env, n):
    lua.execute("local env, n = ...; env.df.global.cur_year_tick = env.df.global.cur_year_tick + n", env, n)


def _walks(w):
    st = w.slices.status("shelter_walk")
    return st.passes if st is not None else 0


@test("shelter budgets: a full report 700 ms (was 3000), 1000 with no plan yet; a pulse 150, 1000 with none")
def _():
    need_lua()
    lua, env, w, _b = _shelter()
    assert env.SHELTER_SLICE_MS_FULL <= 800 and env.SHELTER_SLICE_MS_FULL >= 500, env.SHELTER_SLICE_MS_FULL
    assert env.shelter_budget("daily", True) == env.SHELTER_SLICE_MS_FULL
    assert env.shelter_budget("daily", False) == 1000
    assert env.shelter_budget("pulse", True) == 150 and env.shelter_budget("pulse", False) == 1000
    assert env.SHELTER_PLAN_KEEP_TICKS > env.SHELTER_PLAN_TICKS


@test("shelter: nothing changed (same dangers and ways in, none inside): the plan kept, nothing walked")
def _():
    need_lua()
    lua, env, w, _b = _shelter()
    r = TSH.py(env.report(None, "daily"))
    assert r["danger"] and r["candidates"] and not r.get("walking"), r
    t0, n0 = r["walked_tick"], _walks(w)
    assert n0 == 1
    _tick(lua, env, 700)                 # past SHELTER_PLAN_TICKS (600): the old code walked again here
    r = TSH.py(env.report(None, "daily"))
    assert r["walked_tick"] == t0 and r.get("kept") is True and _walks(w) == n0, (r, _walks(w))
    assert r["candidates"] and not r.get("stale")
    # the pulse likewise
    r = TSH.py(env.report(None, "pulse"))
    assert r["walked_tick"] == t0 and _walks(w) == n0
    # past the keep: walked again
    _tick(lua, env, int(env.SHELTER_PLAN_KEEP_TICKS))
    r = TSH.py(env.report(None, "daily"))
    assert r["walked_tick"] > t0 and _walks(w) == n0 + 1 and not r.get("kept"), r


@test("shelter: another danger, or one inside the fort: walked again at once")
def _():
    need_lua()
    lua, env, w, b = _shelter()
    t0 = TSH.py(env.report(None, "daily"))["walked_tick"]
    _tick(lua, env, 700)
    TSH.add_unit(lua, w, id=901, name="Other", danger=True, great=True, pos={"x": 0, "y": 2, "z": 100},
                 flags1={"caged": False, "chained": False})
    r = TSH.py(env.report(None, "daily"))
    assert r["walked_tick"] > t0 and not r.get("kept"), r
    t1 = r["walked_tick"]
    # the beast walks in: it stands on an inside tile of the hall (z 99)
    _tick(lua, env, 700)
    b.pos.x, b.pos.y, b.pos.z = 5, 5, 99
    r = TSH.py(env.report(None, "daily"))
    assert r["walked_tick"] > t1 and not r.get("kept"), r
    assert any(d.get("inside") for d in r["dangers"]), r["dangers"]


@test("shelter plan_fresh (pure): the old half-day rule, then the keep only with the same dangers and calm")
def _():
    need_lua()
    lua, env, w, _b = _shelter()
    m = lua.table_from({"sig": "1|whole|98-100", "dsig": "900", "tick": 1000})
    f = lambda now, dsig="900", inside=False, sig="1|whole|98-100": tuple(env.plan_fresh(m, sig, dsig, now, inside))  # noqa
    assert f(1500) == (True, False)
    assert f(1700) == (True, True)
    assert f(1700, dsig="900,901") == (False, False)
    assert f(1700, inside=True) == (False, False)
    assert f(1700, sig="2|whole|98-100") == (False, False)
    assert f(1000 + int(env.SHELTER_PLAN_KEEP_TICKS)) == (False, False)
    assert f(900) == (False, False)              # a tick before the plan's (another save)
    assert tuple(env.plan_fresh(None, "x", "y", 5, False)) == (False, False)


# --- 2. the kill zones ------------------------------------------------------------------------

def _kz():
    lua, env, w = TKZ.world()
    TKZ.fort(lua, w)
    TKZ.entrance(lua, w)
    TKZ.entrance(lua, w, eid=2, x=5, y=3)           # rock: no stretch ('none'), the R3 forts' case
    w.G.GATES.scanned_tick = 5000
    calls = lua.eval("{n = 0}")
    lua.execute("""local env, W, calls = ...
        env.game_map = function(G, starts) calls.n = calls.n + 1; return W.M(starts) end""", env, w, calls)
    return lua, env, w, calls


@test("killzones: the corridor plans kept between reports (no walk, no map), the rows the same")
def _():
    need_lua()
    lua, env, w, calls = _kz()
    r1 = TKZ.py(env.report())
    assert calls.n == 1 and r1["plans"] == {"kept": 0, "walked": 2}, (calls.n, r1.get("plans"))
    lua.execute("local env = ...; env.df.global.cur_year_tick = env.df.global.cur_year_tick + 1300", env)
    r2 = TKZ.py(env.report())
    assert calls.n == 1 and r2["plans"] == {"kept": 2, "walked": 0}, (calls.n, r2.get("plans"))
    rows1 = {e["id"]: e for e in r1["entrances"]}
    rows2 = {e["id"]: e for e in r2["entrances"]}
    for i in (1, 2):
        for f in ("state", "corridor", "trap_tiles", "depth", "drawbridge", "why", "fortifications"):
            assert rows1[i].get(f) == rows2[i].get(f), (i, f, rows1[i].get(f), rows2[i].get(f))
    assert rows2[1]["state"] == "possible" and rows2[2]["state"] == "none"


@test("killzones: walked again after KZ_PLAN_TICKS, a new gate scan, another held entrance, build_killzone")
def _():
    need_lua()
    lua, env, w, calls = _kz()
    env.report()
    assert calls.n == 1
    lua.execute("local env = ...; env.df.global.cur_year_tick = env.df.global.cur_year_tick + env.KZ_PLAN_TICKS", env)
    assert TKZ.py(env.report())["plans"]["walked"] == 2 and calls.n == 2
    w.G.GATES.scanned_tick = 9000
    assert TKZ.py(env.report())["plans"]["walked"] == 2 and calls.n == 3
    TKZ.entrance(lua, w, eid=3, x=5, y=16)
    assert TKZ.py(env.report())["plans"]["walked"] == 3 and calls.n == 4
    env.build_killzone(1, 2, "cage", False, True)      # a dry run keeps them
    assert TKZ.py(env.report())["plans"]["walked"] == 0
    env.build_killzone(1, 2, "cage", False, False)
    r = TKZ.py(env.report())
    assert r["plans"]["walked"] == 2, r["plans"]       # 2 and 3 (1 has its record now)
    row1 = {e["id"]: e for e in r["entrances"]}[1]
    assert row1["state"] != "possible" and row1["traps"]["planned"] == 2, row1      # read from its record


# --- 3. forestry: the census in slices ----------------------------------------------------------

SLICED = r"""
local env, W, slices_src = ...
local senv = setmetatable({}, {__index = _G})
assert(load(slices_src, 'ai-slices', 't', senv))()
local old = env.reqscript
env.reqscript = function(n) if n == 'ai-slices' then return senv end return old(n) end
-- DF's vector: 0-based, # its length
env.df.global.world.plants.all = setmetatable({}, {
    __index = function(_, i) return W.plants[i + 1] end,
    __len = function() return #W.plants end})
env.CENSUS = nil
return senv
"""


@test("forestry: the report's census walked in slices (the first whole); the last whole one sent meanwhile")
def _():
    need_lua()
    lua, env, w = T10.world("ai-forestry.lua")
    T10.forest(lua, w)
    want = T10.py(env.report())
    senv = lua.execute(SLICED, env, w, (LUA_DIR / "ai-slices.lua").read_text(encoding="utf-8"))
    r = T10.py(env.report())                                   # the first: whole at once
    for k in ("surface", "cavern", "inside", "layers"):
        assert r[k] == want[k], (k, r[k], want[k])
    assert senv.status("forest_census").passes == 1
    # a day on, a tree more: a slice a report (one plant each), the old census sent until whole
    env.CENSUS_CHUNK, env.CENSUS_SLICE_MS = 1, 0
    lua.execute("local env = ...; env.df.global.cur_year_tick = env.df.global.cur_year_tick + 1300", env)
    w.tree(12, 12, 10, T10._tbl(lua, {"cave": True}))
    r = T10.py(env.report())
    assert r["cavern"]["trees"] == want["cavern"]["trees"] and r["census_age"] >= 1300, r
    n = 1
    while r["cavern"]["trees"] == want["cavern"]["trees"] and n < 20:
        r = T10.py(env.report())
        n += 1
    assert r["cavern"]["trees"] == want["cavern"]["trees"] + 1 and n >= 5, (n, r)
    assert r["census_age"] < 1300
    assert senv.status("forest_census").passes == 2


@test("forestry: without the slices module the census is walked whole, as before")
def _():
    need_lua()
    lua, env, w = T10.world("ai-forestry.lua")
    T10.forest(lua, w)
    r = T10.py(env.report())
    assert r["cavern"]["trees"] == 4 and r["census_age"] == 0, r


# --- 4. the bridge's cache tables --------------------------------------------------------------

@test("bridge: benches cached (2 days, at most 4) and read again after bench_caps; killzones as before")
def _():
    need_lua()
    import test_bridge_memory as TBM
    M = TBM.H.module()
    assert M.SECTION_CACHE_DAYS["benches"] == 2 and M.SECTION_MAX_DAYS["benches"] == 4
    assert list(M.CACHE_INVALIDATES["bench_caps"].values()) == ["benches"]
    assert M.SECTION_CACHE_DAYS["killzones"] == 1 and M.SECTION_MAX_DAYS["killzones"] == 2
    assert M.SECTION_CACHE_DAYS["forestry"] is None        # sliced in its module, its dangers read each report
    assert M.SECTION_CACHE_DAYS["shelter_plan"] is None    # sliced in its module, in the pulse
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "'shelter_grid', 'shelter_walk', 'forest_census'" in src     # perf.slices shows the census's passes


finish()
