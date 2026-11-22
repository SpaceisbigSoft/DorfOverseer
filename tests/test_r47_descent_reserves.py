"""(0.105.47, R2 item 9) Two sliders with a signature: Verticality's stair
past the first cavern (lua/ai-descent.lua on a stub map: the walled shaft
through the cavern, never into water, magma or an aquifer, the dig guard,
the lowest cavern, the steps; brain/planner_descent.py and masterplan's
deep band) and Stockpile's reserves (brain/planner_reserves.py: the
targets by slider, the reserves kept, the storage district and its pile
size; the scorecard's two Stockpile lines).

    python tests/test_r47_descent_reserves.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import bridge_hub_src  # noqa: E402  (r8) the hub's text with its catalog and sections
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
import masterplan  # noqa: E402
import planner_descent as PD  # noqa: E402
import planner_reserves as PR  # noqa: E402
import scorecard  # noqa: E402
from planner import Memory, PLANNER_CONFIG, Proposal, plan  # noqa: E402
from digest import SECTION_DEFAULTS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
CFG = dict(PLANNER_CONFIG, deep_descent=True)   # (0.105.48) the crossing is off by default: on for its tests

# A stub map: rock everywhere; a stair at (50, 50) from z 100 down to 90; the
# layer Cavern1 from z 80 down to 74, open (air, a floor at its bottom) over
# x 40-60, y 40-60; the rock again under it.
FAKE = r"""
local src = ...
local W = {tiles = {}, site = {}, forbid = {}, qf = {}, units = {}, sealed = {}, floor = nil}
local env = setmetatable({}, {__index = _G})
local function k(x, y, z) return x .. ',' .. y .. ',' .. z end
W.layer = {name = 'Cavern1', z_top = 80, z_bottom = 74}
function W.base(x, y, z)
    if z <= W.layer.z_top and z >= W.layer.z_bottom and x >= 40 and x <= 60 and y >= 40 and y <= 60 then
        return {shape = z == W.layer.z_bottom and 'FLOOR' or 'EMPTY', material = 'STONE', feature = true,
                feature_global = true}
    end
    if z <= W.layer.z_top and z >= W.layer.z_bottom then
        return {shape = 'WALL', material = 'STONE', feature = true, feature_global = true}
    end
    if x == 50 and y == 50 and z >= 90 and z <= 100 then
        return {shape = z == 90 and 'STAIR_UP' or 'STAIR_UPDOWN', material = 'STONE'}
    end
    return {shape = 'WALL', material = 'STONE'}
end
function W.read(x, y, z)
    local t = W.tiles[k(x, y, z)]
    if t == false then return nil end
    if t then return t end
    return W.base(x, y, z)
end
function W.set(x, y, z, t) W.tiles[k(x, y, z)] = t end
function W.patch(x, y, z, f)
    local t = {}
    for kk, v in pairs(W.read(x, y, z)) do t[kk] = v end
    for kk, v in pairs(f) do t[kk] = v end
    W.tiles[k(x, y, z)] = t
end
function W.forbid_fn(x, y, z) return W.forbid[k(x, y, z)] end
local B = {
    tile_info = function(x, y, z) return W.read(x, y, z) end,
    elevation_offset = function() return -100 end,
    stair_shape = function(x, y, z)
        local t = W.read(x, y, z)
        if t and (t.shape == 'STAIR_UP' or t.shape == 'STAIR_DOWN' or t.shape == 'STAIR_UPDOWN') then return t.shape end
    end,
    stair_run = function(x, y, z) return 100, 90 end,
    qf_try = function(mode, cells, z, ax, ay, dry, need, loose)
        local list = {}
        for _, c in ipairs(cells) do list[#list + 1] = c.text .. '@' .. (ax + c.x) .. ',' .. (ay + c.y) end
        W.qf[#W.qf + 1] = {mode = mode, z = z, dry = dry, cells = list, n = #cells}
        if W.qf_fail then return false, 'dry' end
        return true
    end,
    hostile_wild = function(u) return u.wild == true end,
}
env.df = {global = {world = {units = {active = W.units}}}}
env.dfhack = {units = {isDead = function(u) return u.dead == true end,
                       isCitizen = function(u) return u.citizen == true end,
                       isDanger = function(u) return u.danger == true end}}
env.reqscript = function(name)
    if name == 'ai-builder' then return B end
    if name == 'ai-threats' then return {load_state = function() return {sealed = W.sealed} end} end
    error('no module ' .. tostring(name))
end
assert(load(src, 'ai-descent', 't', env))()
local U = env.reqscript('ai-util')
U.site_get = function(key, d) return W.site[key] or d end
U.site_put = function(key, v) W.site[key] = v end
U.dig_forbidden = function(x, y, z) return W.forbid[k(x, y, z)] end
U.deep_map = function() return {ok = true, floor = W.floor} end
U.abs_tick = function() return 5000 end
function W.layers() return {list = {W.layer}} end
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-descent.lua"))
    return lua, env, w


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


def py(v):
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    try:
        keys = list(v.keys())
    except AttributeError:
        return v
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in sorted(keys)]
    return {k: py(v[k]) for k in keys}


def plan_of(lua, env, w, zb=90, **opts):
    o = {"bottom_shape": "STAIR_UP"}
    o.update(opts)
    r = env.plan_crossing(w.read, w.forbid_fn, 50, 50, zb, w.layer, T(lua, o))
    return (py(r[0]), r[1]) if isinstance(r, tuple) else (py(r), None)


def cells(p, z):
    lv = next(lv for lv in p["levels"] if lv["z"] == z)
    return {(c["x"], c["y"], c["text"]) for c in lv["cells"]}, lv["part"]


# ------------------------------------------------------------------ the crossing, on a stub map

if LuaRuntime is None:
    print("SKIPPED: the Lua tests need the lupa package (pip install lupa)")
else:
    @test("crossing: rock dug down to the cavern, a built stair and 8 walls on each cavern level, rock below, 'u' last")
    def _():
        lua, env, w = world()
        p, why = plan_of(lua, env, w)
        assert p and not why, why
        assert p["z_end"] == 72 and p["z_start"] == 90
        assert cells(p, 90) == ({(50, 50, "i")}, "above")              # the old bottom made up/down
        assert cells(p, 85) == ({(50, 50, "i")}, "above")
        for z in range(74, 81):
            c, part = cells(p, z)
            assert part == "cavern"
            assert (50, 50, "Cx") in c and len(c) == 9, (z, c)
            ring = {(50 + dx, 50 + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)}
            assert {(x, y) for x, y, t in c if t == "Cw"} == ring
        assert cells(p, 73) == ({(50, 50, "i")}, "below")
        assert cells(p, 72) == ({(50, 50, "u")}, "below")

    @test("crossing: cavern rock beside the stair is left as it is; a rock shaft tile in the cavern is dug")
    def _():
        lua, env, w = world()
        w.patch(51, 50, 78, T(lua, {"shape": "WALL"}))
        w.patch(50, 50, 77, T(lua, {"shape": "WALL"}))
        p, _ = plan_of(lua, env, w)
        c78, _ = cells(p, 78)
        assert (51, 50, "Cw") not in c78 and len(c78) == 8
        c77, _ = cells(p, 77)
        assert (50, 50, "i") in c77 and (50, 50, "Cx") not in c77

    @test("crossing: never into water, magma or an aquifer, anywhere in the column (above, in or under the cavern)")
    def _():
        for z, f, word in ((78, {"liquid": True, "depth": 4}, "water"),
                           (76, {"liquid": True, "magma": True, "depth": 7}, "magma"),
                           (86, {"aquifer": True}, "aquifer"),
                           (73, {"liquid": True, "depth": 2}, "water"),
                           (84, {"warm": True}, "warm stone")):
            lua, env, w = world()
            w.patch(49, 51, z, T(lua, f))
            p, why = plan_of(lua, env, w)
            assert p is None and word in why, (z, why)
        lua, env, w = world()
        w.patch(50, 50, 72, T(lua, {"liquid": True}))                   # the stair's own last tile
        p, why = plan_of(lua, env, w)
        assert p is None and "water" in why, why

    @test("crossing: refused with no solid rock under the cavern, a tree in the way, the dig guard, the lowest cavern")
    def _():
        lua, env, w = world()
        w.patch(51, 51, 73, T(lua, {"shape": "EMPTY"}))
        p, why = plan_of(lua, env, w)
        assert p is None and "no solid rock under the cavern" in why, why
        lua, env, w = world()
        w.patch(50, 49, 76, T(lua, {"shape": "TREE"}))
        p, why = plan_of(lua, env, w)
        assert p is None and "tree" in why, why
        lua, env, w = world()
        w.forbid["50,50,73"] = "raw adamantine"
        p, why = plan_of(lua, env, w)
        assert p is None and "dig guard" in why and "adamantine" in why, why
        lua, env, w = world()
        p, why = plan_of(lua, env, w, floor=80)
        assert p is None and "lowest cavern" in why, why
        lua, env, w = world()
        w.patch(51, 50, 86, T(lua, {"shape": "FLOOR"}))                 # open beside the way down
        p, why = plan_of(lua, env, w)
        assert p is None and "not solid rock" in why, why
        lua, env, w = world()
        w.patch(51, 50, 79, T(lua, {"building": True}))                  # someone's building, not ours
        p, why = plan_of(lua, env, w)
        assert p is None and "built" in why, why
        # (r9, A3 10) with ours (the report's re-reading): a construction being
        # built counts as the crossing's own, any other building refuses
        lua, env, w = world()
        w.patch(51, 50, 79, T(lua, {"building": True, "construction": True}))
        r = env.plan_crossing(w.read, w.forbid_fn, 50, 50, 90, w.layer, T(lua, {"bottom_shape": "STAIR_UP", "ours": True}))
        assert not isinstance(r, tuple) or r[0] is not None, r
        w.patch(51, 50, 79, T(lua, {"building": True, "construction": False}))   # a trap, a seal's door
        r = env.plan_crossing(w.read, w.forbid_fn, 50, 50, 90, w.layer, T(lua, {"bottom_shape": "STAIR_UP", "ours": True}))
        assert isinstance(r, tuple) and r[0] is None and "built" in r[1], r
        lua.execute('''local env = ...
          env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
          env.df.building_type = {Construction = 5, Trap = 6}
          env.dfhack.buildings = {findAtTile = function(p)
              if p.x == 1 then return {getType = function() return 5 end} end
              if p.x == 2 then return {getType = function() return 6 end} end
          end}''', env)
        assert env.construction_at(1, 0, 0) is True and env.construction_at(2, 0, 0) is False
        assert env.construction_at(3, 0, 0) is None

    @test("steps: the rock above but its last level, then each cavern level with the level over it, then the rock below")
    def _():
        lua, env, w = world()
        r = env.plan_crossing(w.read, w.forbid_fn, 50, 50, 90, w.layer, T(lua, {"bottom_shape": "STAIR_UP"}))
        pl = r[0] if isinstance(r, tuple) else r
        pr = py(env.progress(w.read, pl))
        zs = [[lv["z"] for lv in st["levels"]] for st in pr["steps"]]
        assert zs[0] == list(range(90, 81, -1)), zs[0]
        assert zs[1] == [81, 80], zs[1]
        assert zs[2:8] == [[z] for z in range(79, 73, -1)], zs
        assert zs[8] == [73, 72] and len(zs) == 9, zs
        assert pr["next"] == 1 and pr["steps"][0]["state"] == "open"
        for z in range(82, 91):                                          # step 1 marked
            w.patch(50, 50, z, T(lua, {"designated": True}))
        assert py(env.progress(w.read, pl))["steps"][0]["state"] == "marked"
        for z in range(82, 91):                                          # and dug
            w.patch(50, 50, z, T(lua, {"designated": False, "shape": "STAIR_UPDOWN"}))
        pr = py(env.progress(w.read, pl))
        assert pr["next"] == 2 and pr["steps"][1]["state"] == "open", pr["next"]

    @test("action: a dry run marks nothing and saves nothing; the real one marks the first step, then waits for it")
    def _():
        lua, env, w = world()
        a = T(lua, {"x": 50, "y": 50, "elev": 0, "layer": "Cavern1"})
        r = py(env.cross_cavern(a, True, w.layers()))
        assert r["ok"] and r["dry_run"] and r["step"] == 1 and r["placed"] == 9, r
        assert all(q["dry"] for q in py(w.qf)) and not py(w.site), py(w.site)
        r = py(env.cross_cavern(a, False, w.layers()))
        assert r["ok"] and r["placed"] == 9 and not r.get("cavern"), r
        rec = py(w.site)["ai-overseer/descent"]
        assert rec["x"] == 50 and rec["z_start"] == 90 and rec["layer"] == "Cavern1", rec
        assert py(env.report(w.layers()))["state"] == "ready"           # (the fake map digs nothing itself)
        for z in range(82, 91):
            w.patch(50, 50, z, T(lua, {"designated": True}))
        rep = py(env.report(w.layers()))
        assert rep["state"] == "working" and rep["elevation_bottom"] == -28 and rep["steps"] == 9, rep
        r = py(env.cross_cavern(a, False, w.layers()))
        assert not r["ok"] and r["waiting"] and r["nothing_to_do"], r

    @test("action: a cavern step builds the stair and the walls (quickfort build), waits for a beast or the seal")
    def _():
        lua, env, w = world()
        for z in range(82, 91):
            w.patch(50, 50, z, T(lua, {"shape": "STAIR_UPDOWN"}))
        w.units[1] = T(lua, {"pos": {"x": 55, "y": 52, "z": 77}, "danger": True})
        a = T(lua, {"x": 50, "y": 50, "elev": 0, "layer": "Cavern1"})
        r = py(env.cross_cavern(a, False, w.layers()))
        assert not r["ok"] and r["waiting"] and "hostile" in r["error"], r
        assert py(env.report(w.layers())).get("danger") == 1
        w.units[1] = T(lua, {"pos": {"x": 55, "y": 52, "z": 77}, "dead": True})
        w.sealed.Cavern1 = T(lua, {"ids": [1]})
        r = py(env.cross_cavern(a, False, w.layers()))
        assert not r["ok"] and "sealed" in r["error"], r
        w.sealed.Cavern1 = None
        r = py(env.cross_cavern(a, False, w.layers()))
        assert r["ok"] and r["cavern"] and r["step"] == 2, r
        qf = py(w.qf)
        dig = [q for q in qf if q["mode"] == "dig"]
        build = [q for q in qf if q["mode"] == "build"]
        assert dig and dig[0]["z"] == 81 and dig[0]["cells"] == ["i@50,50"], dig
        assert len(build) == 1 and build[0]["z"] == 80 and build[0]["n"] == 9, build
        assert "Cx@50,50" in build[0]["cells"] and "Cw@51,51" in build[0]["cells"]

    @test("report: none without a crossing, built once every step stands, blocked with why")
    def _():
        lua, env, w = world()
        assert py(env.report(w.layers())) == {"state": "none"}
        a = T(lua, {"x": 50, "y": 50, "elev": 0, "layer": "Cavern1"})
        env.cross_cavern(a, False, w.layers())
        for z in range(73, 91):
            w.patch(50, 50, z, T(lua, {"shape": "STAIR_UPDOWN", "material": "STONE" if z > 80 or z < 74
                                       else "CONSTRUCTION"}))
        w.patch(50, 50, 72, T(lua, {"shape": "STAIR_UP"}))
        for z in range(74, 81):
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if (dx, dy) != (0, 0):
                        w.patch(50 + dx, 50 + dy, z, T(lua, {"shape": "WALL", "material": "CONSTRUCTION"}))
        rep = py(env.report(w.layers()))
        assert rep["state"] == "built" and rep["elevation_bottom"] == -28, rep
        r = py(env.cross_cavern(a, False, w.layers()))
        assert not r["ok"] and r.get("built"), r
        w.patch(49, 49, 73, T(lua, {"aquifer": True}))
        rep = py(env.report(w.layers()))
        assert rep["state"] == "blocked" and "aquifer" in rep["why"], rep

    @test("wiring: the action (and its dry run), the section, the module, the brain's default and label")
    def _():
        hub = bridge_hub_src()
        assert "cross_cavern = function(a)" in hub and "'cross_cavern'," in hub
        assert "descent = function()" in hub and "'ai-descent'," in hub
        assert SECTION_DEFAULTS.get("descent") == {}
        from overseer import SHORT_WORDS as WORDS
        assert "cross_cavern" in WORDS


# ------------------------------------------------------------------ the brain: the descent

def mem_with_plan(levels=10, layers=None):
    m = Memory()
    m.atlas = {"survey": {"elevation_offset": -100,
                          "layers": layers if layers is not None else
                          [{"name": "Cavern1", "z_top": 80, "z_bottom": 74},
                           {"name": "Cavern2", "z_top": 50, "z_bottom": 40},
                           {"name": "MagmaSea", "z_top": 20, "z_bottom": 5}]},
               "plan": {"spine": {"x": 50, "y": 50, "top": 0, "bottom": -10},
                        "districts": [{"kind": "industry", "id": "industry", "name": "the Forges", "lo": -14,
                                       "hi": -12, "levels": [{"elevation": -13} for _ in range(levels)]},
                                      {"kind": "storage", "id": "storage", "name": "the Vaults", "lo": -10,
                                       "hi": -8, "levels": []},
                                      {"kind": "homes", "id": "homes", "name": "the Hearths", "lo": -6,
                                       "hi": -4, "levels": []}]}}
    return m


def state(vert=120, citizens=30, descent=None, threats=0):
    return {"settings": {"traits": {"verticality": vert}}, "dwarves": {"total": citizens},
            "date": {"year": 260, "tick": 50000}, "descent": descent if descent is not None else {"state": "none"},
            "others_on_map": {"threats_that_can_reach_dwarves": threats}, "_errors": {}}


def _young_off():
    """The stub states carry no fort age: the young-fort test reads them as old enough."""
    PD.young_fort = lambda s, c: False


@test("masterplan: the first cavern under the spine in elevations; the next layer's top; none past a non-cavern")
def _():
    c = masterplan.cavern_to_cross(mem_with_plan())
    assert c == {"name": "Cavern1", "top": -20, "bottom": -26, "next_top": -50}, c
    assert masterplan.cavern_to_cross(mem_with_plan(layers=[{"name": "MagmaSea", "z_top": 80, "z_bottom": 70}])) is None
    assert masterplan.cavern_to_cross(Memory()) is None
    assert masterplan.crosses_caverns({"verticality": 120}) and not masterplan.crosses_caverns({"verticality": 60})


@test("masterplan: the deep band under the crossing, kept over the next layer, filled from the stair down")
def _():
    m = mem_with_plan()
    b = masterplan.deep_band(m, "workshops", -28, -50)
    assert (b["elev_lo"], b["elev_hi"], b["elev_target"], b["deep"]) == (-33, -28, -28, True), b
    assert b["extend"] == masterplan.DEEP_EXTEND
    m.atlas["plan"]["districts"][0]["levels"].append({"elevation": -28})
    assert masterplan.deep_band(m, "workshops", -28, -50)["elev_target"] == -29
    b = masterplan.deep_band(m, "workshops", -28, -33)       # the next layer close under it
    assert b["elev_lo"] == -30, b
    assert masterplan.deep_band(m, "workshops", -28, -29) is None


@test("descent rule: a grown deep fort begins the stair past Cavern1; not at low Verticality, small, or under threat")
def _():
    _young_off()
    m, props, notes = mem_with_plan(), [], []
    PD._descent_rule(state(), m, CFG, props, notes)
    assert len(props) == 1 and props[0].rule == "deep_descent", props
    a = props[0].action
    assert a == {"type": "cross_cavern", "x": 50, "y": 50, "elev": -10, "layer": "Cavern1"}, a
    for st, mm in ((state(vert=60), m), (state(citizens=10), m), (state(threats=2), m), (state(), mem_with_plan(3))):
        props = []
        PD._descent_rule(st, mm, CFG, props, [])
        assert not props, st
    props = []
    s = state()
    s.pop("descent")
    PD._descent_rule(s, m, CFG, props, [])                       # an older bridge: nothing
    assert not props


@test("descent rule: the next step while ready; nothing while working or built; a note when blocked or a beast is near")
def _():
    _young_off()
    m = mem_with_plan()
    props = []
    PD._descent_rule(state(descent={"state": "ready", "steps": 9, "steps_done": 3, "layer": "Cavern1"}),
                     m, CFG, props, [])
    assert props and "4 of 9" not in props[0].reason and "3 of 9" in props[0].reason, props[0].reason
    for st in ("working", "built"):
        props = []
        PD._descent_rule(state(descent={"state": st}), m, CFG, props, [])
        assert not props
    props, notes = [], []
    PD._descent_rule(state(descent={"state": "blocked", "why": "water at x1 y2 z3", "layer": "Cavern1"}),
                     m, CFG, props, notes)
    assert not props and any("water" in n for n in notes), notes
    props, notes = [], []
    PD._descent_rule(state(descent={"state": "ready", "danger": 2, "layer": "Cavern1"}), m, CFG, props, notes)
    assert not props and any("hostile" in n for n in notes), notes


@test("deep levels: once the crossing stands, industry levels go under it; storage from 40 citizens; urgent ones stay")
def _():
    m = mem_with_plan()
    built = {"state": "built", "elevation_bottom": -28, "layer": "Cavern1"}

    def props():
        return [Proposal("build", {"type": "start_project", "kind": "workshops", "plan": {"elev_lo": -14, "elev_hi": -12,
                                                                                          "district": "the Forges"}}, "x", 5),
                Proposal("build", {"type": "start_project", "kind": "storage"}, "x", 5),
                Proposal("needs_shops", {"type": "start_project", "kind": "workshops", "urgent": True}, "x", 5),
                Proposal("build", {"type": "start_project", "kind": "bedrooms"}, "x", 5)]
    p = props()
    PD.deep_pass(p, state(descent=built, citizens=30), m, CFG, 30)
    assert p[0].action["plan"]["elev_hi"] == -28 and p[0].action["plan"]["district"] == "the Forges", p[0].action
    assert "plan" not in p[1].action and "plan" not in p[2].action and "plan" not in p[3].action
    p = props()
    PD.deep_pass(p, state(descent=built, citizens=45), m, CFG, 45)
    assert p[1].action["plan"]["elev_lo"] == -33 and "plan" not in p[3].action
    p = props()
    PD.deep_pass(p, state(descent={"state": "working"}), m, CFG, 45)
    assert p[0].action["plan"]["elev_hi"] == -12                 # not built yet: as it was
    p = props()
    PD.deep_pass(p, state(vert=0, descent=built), m, CFG, 45)
    assert p[0].action["plan"]["elev_hi"] == -12


# ------------------------------------------------------------------ Stockpile

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort(stockpile=0, **stocks):
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["settings"]["traits"] = {"stockpile": stockpile}
    s["stocks"].update(stocks)
    return s


@test("stockpile: the factor (x2.3 at the Hermit hold's +60, x1.74 at the Merchant city's +40, lean below 0)")
def _():
    f = PR.stock_factor
    assert f({}) == 1.0 and round(f({"stockpile": 60}), 2) == 2.30 and round(f({"stockpile": 40}), 2) == 1.74
    assert f({"stockpile": -50}) == 0.5 and f({"stockpile": -200}) == 0.25 and f({"stockpile": 300}) == 4.0


@test("stockpile: the drink and meal targets a dwarf move by the slider (the same stock: brewed at +60, not at 0)")
def _():
    n = BASE["dwarves"]["total"]
    drink = int(n * CFG["drink_per_dwarf"] * 1.5)                # over the neutral target, under +60's
    rules0 = [p.rule for p in plan(fort(0, drink=drink), Memory())[0]]
    rules60 = [p.rule for p in plan(fort(60, drink=drink), Memory())[0]]
    assert "drink" not in rules0 and "drink" in rules60, (rules0, rules60)
    low = int(n * CFG["drink_per_dwarf"] * 0.6)                  # under the neutral target, over the lean one
    assert "drink" in [p.rule for p in plan(fort(0, drink=low), Memory())[0]]
    assert "drink" not in [p.rule for p in plan(fort(-100, drink=low), Memory())[0]]


@test("stockpile: the reserves kept follow it (cloth, bars); the moods' reserves never under their own; 0 is the same dict")
def _():
    assert PR.reserve_cfg(CFG, {}) is CFG and PR.reserve_cfg(CFG, {"stockpile": 0}) is CFG
    hi, lo = PR.reserve_cfg(CFG, {"stockpile": 60}), PR.reserve_cfg(CFG, {"stockpile": -100})
    assert hi["cloth_per_dwarf"] > CFG["cloth_per_dwarf"] > lo["cloth_per_dwarf"]
    assert hi["cloth_min"] > CFG["cloth_min"] > lo["cloth_min"] >= 1
    assert hi["metal_furniture_bars"] > CFG["metal_furniture_bars"]
    assert hi["reserve_bars"] > CFG["reserve_bars"] and lo["reserve_bars"] == CFG["reserve_bars"]
    assert lo["reserve_plant_cloth"] == CFG["reserve_plant_cloth"]
    assert CFG["cloth_min"] == PLANNER_CONFIG["cloth_min"]       # the shared config untouched


@test("stockpile: the storage district: reserve levels kept by citizens at +30 and over, none lean; piles by slider")
def _():
    assert PR.reserve_storage_want({"stockpile": 0}, 60, CFG) == 0
    assert PR.reserve_storage_want({"stockpile": -100}, 60, CFG) == 0
    h, me = PR.reserve_storage_want({"stockpile": 60}, 57, CFG), PR.reserve_storage_want({"stockpile": 40}, 64, CFG)
    assert h == 5 and me == 4, (h, me)
    assert PR.reserve_storage_want({"stockpile": 200}, 500, CFG) == CFG["reserve_vault_max"]
    assert [PR.storage_room_size({"stockpile": v}) for v in (-100, -40, 0, 39, 40, 99, 100)] == [5, 5, 7, 7, 9, 9, 11]


@test("stockpile: the reserve rule digs a storage level for food, bars, cloth while short; waits on an open one")
def _():
    PR.young_fort = lambda s, c: False
    m = Memory()
    s = {"dwarves": {"total": 57}, "date": {"year": 260, "tick": 50000}, "projects": {"open": []}, "_errors": {}}
    props = []
    PR._reserve_storage_rule(s, m, CFG, {"stockpile": 60}, props, [])
    assert len(props) == 1 and props[0].rule == "reserve_storage", props
    a = props[0].action
    assert a["kind"] == "storage" and a["room_size"] == 9 and "bars_blocks" in a["piles"] and "cloth" in a["piles"]
    m.atlas = {"registry": {f"project:{i}": {"kind": "storage", "status": "built"} for i in range(5)}}
    props = []
    PR._reserve_storage_rule(s, m, CFG, {"stockpile": 60}, props, [])
    assert not props                                              # 5 kept: enough
    m.atlas = {}
    s["projects"]["open"] = [{"kind": "storage"}]
    PR._reserve_storage_rule(s, m, CFG, {"stockpile": 60}, props, [])
    assert not props
    s["projects"]["open"] = []
    PR._reserve_storage_rule(s, m, CFG, {"stockpile": 0}, props, [])
    assert not props


@test("stockpile: every storage level the rules propose gets the slider's pile size (a small-storage culture keeps 5)")
def _():
    p = [Proposal("build", {"type": "start_project", "kind": "storage", "room_size": 7}, "x", 5)]
    PR.reserves_pass(p, Memory(), {"stockpile": 100})
    assert p[0].action["room_size"] == 11
    p = [Proposal("build", {"type": "start_project", "kind": "storage", "room_size": 7}, "x", 5)]
    PR.reserves_pass(p, Memory(), {"stockpile": -60})
    assert p[0].action["room_size"] == 5
    p = [Proposal("build", {"type": "start_project", "kind": "storage", "room_size": 7}, "x", 5)]
    PR.reserves_pass(p, Memory(), {"stockpile": 0})
    assert p[0].action["room_size"] == 7


@test("scorecard: the Stockpile lines read the storage (stone aside) and the stores a dwarf at the peak")
def _():
    lines = {k: (what, hi) for sl, what, k, hi, lo in scorecard.LINES if sl == "Stockpile"}
    assert set(lines) == {"store_tiles_pd", "stores_peak_pd"}, lines
    assert "stockpiles" not in scorecard.PER_PEAK
    j = scorecard.journal_counts([], {"year": 1, "tick": 0})
    j["peak_pop"] = 100
    s = {"dwarves": {"total": 28, "adults": 28}, "buildings": {"stockpiles": 30},
         "stocks": {"drink": 2000}, "supplies": {"meal_servings": 2427},
         "logistics": {"storage": {"food": {"tiles": 300}, "stone": {"tiles": 900}, "bars_blocks": {"tiles": 100}}}}
    m = scorecard.measures(s, j)
    assert m["stores_peak_pd"] == 44.3 and m["stores_pd"] == 158.1, m["stores_peak_pd"]
    assert m["store_tiles_pd"] == 4.0, m["store_tiles_pd"]


@test("temperament: the panel's Now: line for Stockpile and Verticality")
def _():
    import temperament
    e = temperament.effects({"settings": {"traits": {"stockpile": 60, "verticality": 120}}, "dwarves": {"total": 57}})
    assert "x2.3" in e["stockpile"] and "9x9" in e["stockpile"] and "5 storage levels" in e["stockpile"], e["stockpile"]
    assert "past the first cavern" in e["verticality"], e["verticality"]


if __name__ == "__main__":
    finish()
