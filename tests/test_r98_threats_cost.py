"""(0.105.98) The `threats` section's cost: its openings part.

Live 23 Nov 22:00-22:12 (perf.sections, ms a full report; the bridge pauses
the game while it runs): threats 151 ms in C, 176 in F, 82 in A. Its own part
times (threats._ms, the parts over 5 ms) named one part alone: `openings` 170
in C and 157 in F (10 and 9 openings on record), 31-59 in A, B, D, E (2-6).
The unit walks (prisoners, thieves, undead, were, surface, interrupters) were
each under 5 ms. The openings part asked ai-builder's well_lids (every
well's gate, its watcher's test over every unit, the free mechanisms) only
for the shaft hatches' tiles, and each cavern well door's lockable test read
the projects twice (a deep copy of the whole record, old_areas up to 600
boxes) and the citizens afresh. Now: the hatches' tiles alone
(well_shaft_hatches, the same wells and tiles), the projects read once a
report without a copy (projects_read_only), the citizens once; the rows the
brain reads are the same. `openings.cost` counts what was read.

    python tests/test_r98_threats_cost.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402
from lua_modules_util import module_src, split_src  # noqa: E402

import planner  # noqa: E402,F401
import planner_threats as pt  # noqa: E402
from planner_core import Memory  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA = ROOT / "lua"
SURVEY = (LUA / "ai-threats-survey.lua").read_text(encoding="utf-8")
WATCH = (LUA / "ai-builder-wells-watch.lua").read_text(encoding="utf-8")
SAFETY = (LUA / "ai-well-safety.lua").read_text(encoding="utf-8")
PROJECTS = (LUA / "ai-builder-projects.lua").read_text(encoding="utf-8")
GSCAN = (LUA / "ai-gates-scan.lua").read_text(encoding="utf-8")
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def body(src, name):
    m = re.search(r"\nfunction " + re.escape(name) + r"\(.*?\n(.*?)\nend\n", src, re.S)
    assert m, name
    return m.group(1)


# --- static: what the openings part reads -------------------------------------------------

@test("the openings part asks only the hatches' tiles (well_shaft_hatches), well_lids only as the fallback")
def _():
    g = body(SURVEY, "gather_openings")
    assert "well_shaft_hatches" in g and "well_lids(false)" in g
    assert g.index("well_shaft_hatches") < g.index("well_lids(false)")
    k = body(GSCAN, "well_shaft_keys")
    assert "well_shaft_hatches" in k


@test("well_shaft_hatches gives well_lids' own hatch tile for the same wells (shaft_kept, anchor, shaft bottom)")
def _():
    h = body(WATCH, "well_shaft_hatches")
    lids = body(WATCH, "well_lids")
    assert "pcall(shaft_kept, p)" in h and "shaft_kept(p)" in lids
    assert "shaft_hatch = {x = an0.x, y = an0.y, z = shaft_bottom(p)}" in h
    assert "r.shaft_hatch = {x = an0.x, y = an0.y, z = shaft_bottom(p)}" in lids
    for heavy in ("shaft_threats", "shaft_gate_state", "free_mechanism", "findAtTile"):
        assert heavy not in h, heavy


@test("the projects read once a report (no copy) and handed to every door's test; the citizens once")
def _():
    r = body(SURVEY, "openings_report")
    assert "projects_read_only" in r and "gather_openings(d, t, ctx.data)" in r
    assert "pcall(seal_lockable, o, row, ctx)" in r
    assert "OPENINGS_COST = {project_reads" in r
    s = body(SURVEY, "seal_lockable")
    assert "WSAFE.door_blocked(o, cits, data)" in s and "WSAFE.door_seal_skip, o, data" in s
    assert "pcall(WSAFE.citizens)" in s
    for f, sig in (("fort_doors", "data"), ("door_blocked", "o, cits, data"), ("door_seal_skip", "o, data")):
        assert re.search(r"\nfunction " + f + r"\(" + re.escape(sig) + r"\)", SAFETY), f
        assert "data = data or builder().load_projects()" in body(SAFETY, f), f
    p = body(PROJECTS, "projects_read_only")
    assert "deep_copy" not in p and "return ctx.projects" in p


@test("seal_cavern's own call of seal_lockable is unchanged (reads afresh, as before)")
def _():
    acts = split_src("ai-threats.lua")   # (0.105.119) seal_cavern in ai-threats-seal
    assert "pcall(seal_lockable, o)" in acts


@test("every Lua file changed stays under 60 KB")
def _():
    for f in ("ai-threats-survey.lua", "ai-builder-wells-watch.lua", "ai-well-safety.lua",
              "ai-builder-projects.lua", "ai-gates-scan.lua"):
        assert (LUA / f).stat().st_size < 60 * 1024, f


# --- brain: the rows read the same with the new `cost` key -------------------------------

@test("the planner reads openings with `cost` as before (seal rows, the beasts' rule)")
def _():
    rows = [{"x": 1, "y": 1, "z": 140, "kind": "gate", "source": "cavern entrance 1", "building": "Door",
             "id": 7, "built": True, "locked": False, "closed": False, "lockable": True}]
    def fort(extra):
        s = copy.deepcopy(BASE)
        s["map"]["elevation_offset"] = -129
        op = {"list": [dict(r) for r in rows], "n": 1}
        op.update(extra)
        s["threats"] = {"sealed": {}, "openings": op, "cavern_citizens": {"list": [], "n": 0}}
        s["deep"] = {"caverns": [{"discovered": True, "name": "Cavern1", "open": False, "seen": 1,
                                  "z_bottom": 123, "z_top": 146}],
                     "dangers": [{"id": 50, "name": "Shedim, Forgotten Beast", "kind": "forgotten beast",
                                  "layer": "Cavern1"}], "cursed": []}
        s["civ_alert"], s["civ_alert_ready"] = False, True
        return s

    def run(s):
        props, notes = [], []
        pt._cavern_beasts(s, dict(pt.PLANNER_CONFIG), Memory(), s["threats"], pt.threat_rules_of(s), props, notes)
        return sorted((p.rule, json.dumps(p.action, sort_keys=True)) for p in props), notes

    a = run(fort({}))
    b = run(fort({"cost": {"project_reads": 1, "doors_checked": 0}}))
    assert a == b, (a, b)
    assert any(r == "seal_cavern" for r, _ in a[0]), a


# --- Lua (lupa; skipped here): one read of the projects for every door -------------------

THREATS_GAME = r"""
local src = ...
local G = {saved = {}, citizens = {}, tiles = {}, mods = {}, reads = {copy = 0, ro = 0, cit = 0}, got = {}}
local e = setmetatable({G = G}, {__index = _G})
e.reqscript = function(n) return G.mods[n] end
e.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
e.df = {global = {cur_year = 1, cur_year_tick = 0, world = {features = {map_features = {}, feature_global_idx = {}}}},
        building = {find = function(id) for _, b in pairs(G.tiles) do if b.id == id then return b end end end},
        building_type = {Door = 'Door', Hatch = 'Hatch', Wall = 'Wall'},
        feature_init_subterranean_from_layerst = {is_instance = function() return false end}}
e.dfhack = {persistent = {getSiteData = function(k, d) return G.saved[k] or d end,
                          saveSiteData = function(k, v) G.saved[k] = v end},
            units = {getReadableName = function(u) return u.name end, getCitizens = function() return G.citizens end},
            buildings = {findAtTile = function(p) return G.tiles[p.x .. ',' .. p.y .. ',' .. p.z] end},
            maps = {getTileFlags = function() return {} end, getTileBlock = function() return nil end}}
function G.bld(id, ty) return {id = id, jobs = {}, door_flags = {forbidden = false, closed = false},
    getType = function() return ty end, getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end} end
local PROJ = {list = {{id = 13, kind = 'well'}}}
G.mods['ai-builder'] = {
    load_projects = function() G.reads.copy = G.reads.copy + 1; return PROJ end,
    projects_read_only = function() G.reads.ro = G.reads.ro + 1; return PROJ end,
    well_shaft_hatches = function(data)
        G.got.hatches = data == PROJ
        return {{project_id = 13, shaft_hatch = {x = 131, y = 129, z = 143}}}
    end,
    well_lids = function() error('well_lids read') end,
}
G.mods['ai-well-safety'] = {
    citizens = function() G.reads.cit = G.reads.cit + 1; return {{id = 1, x = 0, y = 0, z = 0}} end,
    fort_doors = function(data)
        G.got.doors = data == PROJ
        local out = {}
        for i = 1, 6 do out[i] = {x = 100 + i, y = 140, z = 165, kind = 'door', project_id = 13} end
        return out
    end,
    door_blocked = function(o, cits, data)
        if data ~= PROJ or type(cits) ~= 'table' then error('read afresh') end
        return o.x == 101 and 'Morul' or nil
    end,
    door_seal_skip = function(o, data)
        if data ~= PROJ then error('read afresh') end
        return o.x == 102 and 'kept' or nil
    end,
}
assert(load(src, 'ai-threats', 't', e))()
return e
"""


def py(v):
    if hasattr(v, "items"):
        d = dict(v.items())
        if d and all(isinstance(k, int) for k in d):
            return [py(d[k]) for k in sorted(d)]
        return {k: py(x) for k, x in d.items()}
    return v


@test("Lua: six cavern well doors and the shaft hatch: the projects read once (read only), the citizens once, "
      "the same verdicts (blocked, skip, lockable), no well_lids")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    lua = LuaRuntime(unpack_returned_tuples=True)
    E = lua.execute(THREATS_GAME, module_src("ai-threats.lua"))
    G = E.G
    G.tiles["131,129,143"] = G.bld(516, "Hatch")
    for i in range(1, 7):
        G.tiles[f"{100 + i},140,165"] = G.bld(600 + i, "Door")
    rep = py(E.openings_report(E.load_state(), 0, None))
    assert G.reads.ro == 1 and G.reads.copy == 0 and G.reads.cit == 1, (G.reads.ro, G.reads.copy, G.reads.cit)
    assert G.got.hatches and G.got.doors
    by_x = {r["x"]: r for r in rep["list"]}
    assert by_x[131]["lockable"] is False and by_x[131]["kind"] == "well"
    assert by_x[101]["lockable"] is False and by_x[101]["well_blocked"] == "Morul"
    assert by_x[102]["lockable"] is False and by_x[102]["seal_skip"] == "kept"
    assert all(by_x[x]["lockable"] is True for x in (103, 104, 105, 106))
    assert rep["n"] == 7 and "cost" not in rep        # (merge) the cost kept out of the report's shape
    c = E.OPENINGS_COST
    assert c is None or py(c) == {"project_reads": 1, "doors_checked": 6}, py(c)


if __name__ == "__main__":
    finish()
