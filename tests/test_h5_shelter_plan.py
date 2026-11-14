"""(0.105.45, Phase 11 brief (c)) Never let a beast reach the civilians' shelter.

F's hill titan (27 Galena y257) killed 42 in the shelter where the civilians
and two squads waited together. Here:

  * lua/ai-shelter-plan.lua's pure part (the walk over stairs and ramps,
    the path, the chokes, plan()) and its report and pick in a fake fort;
  * ai-society's shelter drawn over the AI's pick only;
  * the brain (brain/planner_shelter.py): the shelter away from the threat,
    with drink and never one it reaches first; moved at once from a great
    danger inside that comes close; the whole fort again once it's gone;
    the squads at a choke between, else the barracks, never in the shelter
    (planner_army's _shelter_squads_rule);
  * the wiring (actions, dry runs, sections, the pulse, the digest, labels).

    python tests/test_h5_shelter_plan.py
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan as full_plan  # noqa: E402
from planner_core import Proposal  # noqa: E402
import planner_shelter as PS  # noqa: E402
import planner_army as PA  # noqa: E402
from digest import normalize, SECTION_DEFAULTS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
CFG = dict(PLANNER_CONFIG)


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
    if not keys:
        return {}
    if all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in sorted(keys)]
    return {k: py(v[k]) for k in keys}


# --- 1. the pure walk (lupa) ----------------------------------------------------------

PURE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
env.reqscript = function(n) error('no ' .. tostring(n)) end
assert(load(src, 'ai-shelter-plan', 't', env))()
-- a grid builder for the tests: rows of text per level
function env.grid_of(levels)
    local g = {}
    for z, rows in pairs(levels) do
        for y, row in ipairs(rows) do
            for x = 1, #row do
                local c = row:sub(x, x)
                local f
                if c == '.' then f = env.WALK + env.INSIDE
                elseif c == 'o' then f = env.WALK                      -- outside
                elseif c == '>' then f = env.WALK + env.DOWN + env.INSIDE
                elseif c == '<' then f = env.WALK + env.UP + env.INSIDE
                elseif c == 'X' then f = env.WALK + env.UP + env.DOWN + env.INSIDE
                elseif c == '^' then f = env.WALK + env.RAMP + env.INSIDE end
                if f then g[env.K(x, y, z)] = f end
            end
        end
    end
    return g
end
return env
"""


def pure():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(PURE, module_src("ai-shelter-plan.lua"))
    return lua, env


def grid(lua, env, levels):
    return env.grid_of(T(lua, {z: rows for z, rows in levels.items()}))


@test("pure: keys round-trip; the walk crosses a stair only up-to-down, and a ramp both ways")
def _():
    if LuaRuntime is None:
        return
    lua, env = pure()
    k = env.K(700, 513, 170)
    assert tuple(env.unkey(k)) == (700, 513, 170)
    g = grid(lua, env, {10: ["..<"], 11: ["..>"]})
    dist = env.bfs(g, T(lua, [env.K(1, 1, 10)]))[0]
    assert dist[env.K(3, 1, 11)] == 3 and dist[env.K(1, 1, 11)] == 5, py(dist)
    # an up stair under another up stair: no way
    g = grid(lua, env, {10: ["..<"], 11: ["..<"]})
    dist = env.bfs(g, T(lua, [env.K(1, 1, 10)]))[0]
    assert dist[env.K(3, 1, 11)] is None
    # a ramp: up to the tiles round the one above it, and back down
    g = grid(lua, env, {10: [".^"], 11: ["..."]})
    dist = env.bfs(g, T(lua, [env.K(1, 1, 10)]))[0]
    assert dist[env.K(3, 1, 11)] == 2, py(dist)
    dist = env.bfs(g, T(lua, [env.K(3, 1, 11)]))[0]
    assert dist[env.K(1, 1, 10)] == 2, py(dist)


@test("pure: the walk stops at its cap and says so")
def _():
    if LuaRuntime is None:
        return
    lua, env = pure()
    g = grid(lua, env, {10: ["." * 50]})
    dist, n, capped = env.bfs(g, T(lua, [env.K(1, 1, 10)]), 10)
    assert n == 10 and capped, (n, capped)


def fort_levels():
    corridor = ["o............>"]                               # y1: x1 outside, x2-13 corridor, x14 stair down
    hall = ["............." + "X"] + ["............." + "."] * 6  # z99: a hall, the stair at x14 y1
    deep = ["............." + "<"] + ["............." + "."] * 6  # z98: a deeper level, the stair's foot
    return {100: corridor, 99: hall, 98: deep}


@test("pure: plan() gives the threat's walk and the civilians' to each level, the late ones and a choke")
def _():
    if LuaRuntime is None:
        return
    lua, env = pure()
    g = grid(lua, env, fort_levels())
    seeds99 = [env.K(x, y, 99) for x in range(1, 15) for y in range(1, 8)]
    seeds98 = [env.K(x, y, 98) for x in range(1, 15) for y in range(1, 8)]
    cands = T(lua, [{"z": 99, "key": 99, "seeds": seeds99}, {"z": 98, "key": 98, "seeds": seeds98}])
    src = [env.K(1, 1, 100)]
    civs = [env.K(2, 6, 99), env.K(3, 6, 99), env.K(1, 1, 99)]
    out, kept = env.plan(g, cands, T(lua, src), T(lua, civs), T(lua, [env.K(5, 5, 99)]), T(lua, {"keep": 98}))
    c = py(out)
    by = {r["z"]: r for r in c}
    # the threat: 13 steps along the corridor, the stair down to z99; one more to z98
    assert by[99]["d_threat"] == 14 and by[98]["d_threat"] == 15, c
    assert by[99]["civ_med"] == 0 and by[98]["civ_p90"] is not None, c
    assert by[99]["civ_late"] == 0 and by[98]["civ_late"] == 0, c
    assert by[99]["d_inside"] == 0 and by[98]["d_inside"] == 10, c
    ch = by[99]["chokes"]
    assert ch and ch[0]["z"] == 100 and ch[0]["from_src"] == 2 and ch[0]["width"] <= 2, ch
    assert all(x["to_shelter"] >= 6 for x in ch), ch
    assert kept is not None and kept[env.K(5, 5, 99)] == 10


@test("pure: a level the threat can't walk to has no d_threat; a civilian beyond it is unreached")
def _():
    if LuaRuntime is None:
        return
    lua, env = pure()
    g = grid(lua, env, {100: ["o.....", "......"], 99: ["......"]})       # no stair between
    cands = T(lua, [{"z": 99, "key": 99, "seeds": [env.K(x, 1, 99) for x in range(1, 7)]}])
    out, _ = env.plan(g, cands, T(lua, [env.K(1, 1, 100)]), T(lua, [env.K(3, 2, 100), env.K(2, 1, 99)]), T(lua, []))
    c = py(out)[0]
    assert c.get("d_threat") is None and c["civ_reached"] == 1 and c["civ_unreached"] == 1, c


@test("pure: chokes: the first in from the threat, the narrowest, a stair; none near the shelter")
def _():
    if LuaRuntime is None:
        return
    lua, env = pure()
    g = grid(lua, env, {100: ["o.........>"], 99: [".........." + "X"] + [".........." + "."] * 4})
    seeds = [env.K(x, y, 99) for x in range(1, 12) for y in range(1, 6)]
    dist = env.bfs(g, T(lua, seeds))[0]
    ch = py(env.chokes(g, dist, env.K(1, 1, 100), T(lua, {"min_to": 3}))[0])
    assert ch and ch[0]["from_src"] == 2 and ch[0]["x"] == 3, ch
    assert all(c["to_shelter"] >= 3 for c in ch)
    ch = py(env.chokes(g, dist, env.K(1, 1, 100), T(lua, {"min_to": 50}))[0])
    assert ch == {} or ch == [], ch


# --- 2. the report, the pick (lupa, a fake fort) ---------------------------------------

FAKE = r"""
local src = ...
local W = {units = {}, cits = {}, site = {}, barracks = {}, refreshed = 0, alert_burrows = {4}}
local blocks = {}
local function block(z, rows, outside_x)
    local des, tt = {}, {}
    for x = 0, 15 do
        des[x], tt[x] = {}, {}
        for y = 0, 15 do
            local row = rows[y + 1] or ''
            local c = row:sub(x + 1, x + 1)
            des[x][y] = {hidden = false, outside = (c == 'o'), flow_size = 0}
            local shape = 1                       -- WALL
            if c == '.' or c == 'o' then shape = 2 elseif c == '>' then shape = 3
            elseif c == '<' then shape = 4 elseif c == 'X' then shape = 5 end
            tt[x][y] = shape
        end
    end
    table.insert(blocks, {map_pos = {x = 0, y = 0, z = z}, designation = des, tiletype = tt})
end
W.block = block
local env = setmetatable({}, {__index = _G})
env.df = {global = {cur_year = 300, cur_year_tick = 1000,
                    world = {map = {map_blocks = blocks}, units = {active = W.units},
                             buildings = {other = {ZONE_BARRACKS = W.barracks}}},
                    plotinfo = {alerts = {list = {[1] = {burrows = W.alert_burrows}}}}},
          tiletype = {attrs = {[1] = {shape = 1}, [2] = {shape = 2}, [3] = {shape = 3}, [4] = {shape = 4}, [5] = {shape = 5}}},
          tiletype_shape = {[1] = 'WALL', [2] = 'FLOOR', [3] = 'STAIR_DOWN', [4] = 'STAIR_UP', [5] = 'STAIR_UPDOWN'}}
-- the alert list is zero-based in DF: [1] is the civilian alert's
env.dfhack = {
    units = {isActive = function() return true end, isDead = function() return false end,
             isCitizen = function(u) return u.citizen == true end, isDanger = function(u) return u.danger == true end,
             isGreatDanger = function(u) return u.great == true end, isInvader = function(u) return u.invader == true end,
             getReadableName = function(u) return u.name or 'it' end,
             getCitizens = function() return W.cits end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
local gates = {scanned = true, entrances = {{id = 1, kind = 'surface', x = 1, y = 1, z = 100}}}
local S = {SHELTER_NAME = 'AI shelter',
           find_burrow = function() return {id = 4} end,
           shelter_level_range = function() return 97, 101 end,
           shelter_supplies = function() return {}, {['5,5,98'] = 20}, {}, {} end,
           refresh_shelter = function() W.refreshed = W.refreshed + 1; return {refreshed = true, tiles = W.tiles or 30} end}
env.reqscript = function(n)
    if n == 'ai-gates' then return {GATES = gates} end
    if n == 'ai-society' then return S end
    error('no ' .. tostring(n))
end
assert(load(src, 'ai-shelter-plan', 't', env))()
return env, W
"""


def fake():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-shelter-plan.lua"))
    # block rows are y=0.. (x=0 a wall column): the entrance at x1 y1 z100
    lua.execute("""local env, W = ...
        W.block(100, {'', ' o............>'})
        local hall, deep = {'', ' .............X'}, {'', ' .............<'}
        for i = 1, 6 do table.insert(hall, ' ..............'); table.insert(deep, ' ..............') end
        W.block(99, hall)
        W.block(98, deep)""", env, w)
    return lua, env, w


def add_unit(lua, w, **kw):
    u = T(lua, kw)
    w.units[len(w.units) + 1] = u
    if kw.get("citizen"):
        w.cits[len(w.cits) + 1] = u
    return u


def civ(lua, w, x, y, z, squad=-1):
    return add_unit(lua, w, citizen=True, pos={"x": x, "y": y, "z": z}, military={"squad_id": squad},
                    flags1={"caged": False, "chained": False})


def titan(lua, w, x, y, z):
    return add_unit(lua, w, id=900, name="Titan", danger=True, great=True, pos={"x": x, "y": y, "z": z},
                    flags1={"caged": False, "chained": False})


@test("report: nothing dangerous on the map: danger false, no walk")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = fake()
    civ(lua, w, 3, 3, 99)
    r = py(env.report())
    assert r["danger"] is False and "candidates" not in r, r


@test("report: a titan at the gate: its way in, both levels walked (the deeper one farther), the drink by level")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = fake()
    civ(lua, w, 3, 3, 99)
    civ(lua, w, 4, 4, 99)
    civ(lua, w, 4, 6, 99, squad=7)             # a soldier: not a civilian
    titan(lua, w, 0, 1, 100)
    r = py(env.report())
    assert r["danger"] is True and r["civilians"] == 2, r
    assert r["dangers"][0]["way_in"] == 1 and not r["dangers"][0].get("inside"), r["dangers"]
    by = {c["z"]: c for c in r["candidates"]}
    assert set(by) == {98, 99}, by.keys()
    assert by[98]["d_threat"] > by[99]["d_threat"] and by[98]["drink"] == 20 and by[99]["drink"] == 0, by
    assert by[99]["way_in"]["id"] == 1 and by[99]["chokes"], by[99]


@test("report: a titan inside: inside, and its walk to the AI's pick (the pick's own walk kept)")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = fake()
    civ(lua, w, 3, 3, 98)
    titan(lua, w, 5, 5, 99)
    w.site["ai-overseer/shelter-pick"] = T(lua, {"levels": [98], "tick": 300 * 403200 + 900})
    r = py(env.report())
    t = r["dangers"][0]
    assert t.get("inside") is True and t["to_shelter"] == 10, t
    assert r["current"]["levels"] == [98] and r.get("current_walk"), r.keys()


@test("pick: refused when the alert's burrow isn't the AI shelter; levels kept and the shelter redrawn; cleared")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = fake()
    w.alert_burrows[1] = 9
    r = py(env.pick(T(lua, [98]), None, False))
    assert r["ok"] is False and "not the AI shelter" in r["error"], r
    w.alert_burrows[1] = 4
    r = py(env.pick(T(lua, [98]), T(lua, {"why": "far"}), True))
    assert r["ok"] and r["dry_run"] and w.refreshed == 0, r
    r = py(env.pick(T(lua, [98, 99]), T(lua, {"why": "far"}), False))
    assert r["ok"] and w.refreshed == 1 and py(w.site["ai-overseer/shelter-pick"])["levels"] == [98, 99], r
    assert py(env.pick_levels()) == {98: True, 99: True}
    r = py(env.pick(T(lua, [120]), None, False))
    assert r["ok"] is False and "not one of the fort" in r["error"], r
    r = py(env.pick(None, T(lua, {"clear": True}), False))
    assert r["ok"] and r["clear"] and env.pick_levels() is None, r


@test("pick: a pick with no tiles is undone (the old pick back)")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = fake()
    w.tiles = 0
    r = py(env.pick(T(lua, [98]), None, False))
    assert r["ok"] is False and env.pick_levels() is None, r


@test("pick: an old pick (over 10 game days) is dropped: the whole fort again")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = fake()
    w.site["ai-overseer/shelter-pick"] = T(lua, {"levels": [98], "tick": 300 * 403200 + 1000 - 13 * 1200})
    assert env.pick_levels() is None


def _fake_src(file: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return node.value.value
    raise KeyError(name)


@test("ai-society: the shelter drawn over the AI's pick only (and the whole fort without one)")
def _():
    if LuaRuntime is None:
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, got, w = lua.execute(_fake_src("test_fix26_combat.py", "FAKE"), module_src("ai-society.lua"))
    r = env.refresh_shelter()
    zs = {int(k.split(",")[2]) for k in got.keys() if got[k]}
    assert len(zs) > 3 and not r.levels, zs
    lua.execute("""local env = ...
        local old = env.reqscript
        env.reqscript = function(n)
            if n == 'ai-shelter-plan' then return {pick_levels = function() return {[165] = true} end} end
            return old(n)
        end""", env)
    r = env.refresh_shelter()
    zs = {int(k.split(",")[2]) for k in got.keys() if got[k]}
    assert zs == {165} and r.tiles > 0 and list(r.levels.values()) == [165], (zs, dict(r))


# --- 3. the brain ---------------------------------------------------------------------

def cand(z, d, p90=5, drink=0, wells=0, tiles=200, reached=10, chokes=None, way=None):
    return {"z": z, "d_threat": d, "civ_p90": p90, "civ_med": p90 // 2, "civ_reached": reached, "civ_late": 0,
            "drink": drink, "wells": wells, "tiles": tiles, "food": 0,
            "chokes": chokes or [], "way_in": way or {"id": 1, "kind": "surface", "x": 10, "y": 20, "z": 170}}


def splan(cands, dangers=None, current=None, barracks=None, current_walk=None):
    p = {"danger": True, "candidates": cands, "dangers": dangers or [{"id": 900, "name": "Titan", "great": True,
                                                                         "x": 9, "y": 20, "z": 170, "way_in": 1}],
         "civilians": 20, "barracks": barracks or []}
    if current is not None:
        p["current"] = {"levels": current}
    if current_walk is not None:
        p["current_walk"] = current_walk
    return p


def state(sp, alert=False, shelter="ai", squads=None, total=20):
    return {"date": {"year": 300, "tick": 1000}, "shelter_plan": sp, "civ_alert": alert,
            "civ_alert_shelter": shelter, "dwarves": {"total": total},
            "military": {"squads": squads or []}}


def run(s, cfg=None):
    props, notes = [], []
    PS._shelter_pick_rule(s, cfg or CFG, props, notes, Memory())
    return props, notes


@test("choose: the level the threat reaches last, with drink; never one it reaches before the civilians")
def _():
    # z150 is farthest but the civilians need 60 to get there and the threat 62: unsafe
    p = splan([cand(165, 30, drink=100), cand(160, 45, wells=1), cand(150, 62, p90=60, wells=1)])
    c = PS.choose_shelter(p, CFG, citizens=20)
    assert c["main"] == 160 and c["safe"] and c["drink"], c
    assert "level" in c["why"] and "x10 y20 z170" in c["why"], c["why"]


@test("choose: an unreachable level beats any distance; a dry one loses to a wet one")
def _():
    p = splan([cand(165, 30, drink=100), cand(150, None, wells=1), cand(140, 90)])
    assert PS.choose_shelter(p, CFG, citizens=20)["main"] == 150
    p = splan([cand(165, 30, drink=100), cand(140, 90)])
    c = PS.choose_shelter(p, CFG, citizens=20)
    assert c["main"] == 165 and c["drink"], c


@test("choose: neighbours added (farthest first) for room and drink, up to 3 levels")
def _():
    p = splan([cand(160, 60, tiles=20, wells=1), cand(161, 55, tiles=20), cand(159, 65, tiles=20),
               cand(158, 70, tiles=20, p90=80)])
    c = PS.choose_shelter(p, CFG, citizens=20)        # 40 tiles wanted (50 at least)
    assert c["levels"] == [159, 160, 161], c
    assert 158 not in c["levels"], c                  # unsafe: the threat gets there first


@test("choose: nothing safe: the most room between the threat and the civilians, said")
def _():
    p = splan([cand(165, 10, p90=9, drink=50), cand(160, 20, p90=18, drink=50)])
    c = PS.choose_shelter(p, CFG, citizens=20)
    assert not c["safe"] and "surely reach first" in c["why"], c


@test("rule 1: a great danger on the map: the shelter drawn over the farthest level (its way in said)")
def _():
    s = state(splan([cand(165, 30, drink=100), cand(160, 45, wells=1)]))
    p, n = run(s)
    assert [x.rule for x in p] == ["shelter_pick"] and p[0].action["levels"] == [160], [x.action for x in p]
    assert p[0].action["way_in"]["id"] == 1 and p[0].priority == 0
    assert "great danger" in p[0].reason and "x10 y20 z170" in p[0].reason, p[0].reason


@test("rule 1: the same pick in use: nothing; a slightly farther one: kept (hysteresis); the player's burrow: a note")
def _():
    sp = splan([cand(165, 30, drink=100, tiles=20), cand(160, 45, wells=1)])
    lv = PS.choose_shelter(sp, CFG, citizens=20)["levels"]
    p, n = run(state(dict(sp, current={"levels": lv})))
    assert p == [], p
    sp2 = splan([cand(165, 40, drink=100), cand(160, 45, wells=1)], current=[165],
                current_walk={"d_threat": 40, "civ_p90": 5})
    p, n = run(state(sp2))
    assert p == [], [x.action for x in p]
    p, n = run(state(splan([cand(165, 30, drink=100)]), shelter="player"))
    assert p == [] and "yours" in n[0], n


@test("rule 1: no level with drink: the shelter stays as it is, said")
def _():
    p, n = run(state(splan([cand(165, 30), cand(160, 45)])))
    assert p == [] and "no drink" in n[0], n


@test("rule 1: the danger gone and the alarm down: the whole fort again; with the alarm up: kept")
def _():
    s = state({"danger": False, "current": {"levels": [160]}})
    p, n = run(s)
    assert [x.action for x in p] == [{"type": "shelter_pick", "clear": True}], [x.action for x in p]
    s["civ_alert"] = True
    assert run(s)[0] == []
    assert run(state({"danger": False}))[0] == []


@test("rule 3: a great danger inside, close to the shelter: the civilians moved at once to the next, a note")
def _():
    d = [{"id": 900, "name": "Titan", "great": True, "inside": True, "to_shelter": 12, "x": 5, "y": 5, "z": 160}]
    s = state(splan([cand(165, 30, drink=100), cand(160, 45, wells=1), cand(150, 70, wells=1)],
                    dangers=d, current=[160]))
    p, n = run(s)
    assert [x.rule for x in p] == ["shelter_flee"] and 160 not in p[0].action["levels"], [x.action for x in p]
    assert "Titan is inside the fort, 12 steps" in p[0].reason and any("the shelter moved" in x for x in n), (p, n)
    # far away inside: the ordinary rule
    d[0]["to_shelter"] = 80
    p, n = run(s)
    assert all(x.rule != "shelter_flee" for x in p), [x.rule for x in p]
    # the whole fort as the shelter and the titan inside: at once
    d[0]["to_shelter"] = None
    s = state(splan([cand(165, 30, drink=100), cand(150, 70, wells=1)], dangers=d))
    p, n = run(s)
    assert [x.rule for x in p] == ["shelter_flee"] and p[0].action["levels"][0] == 150, [x.action for x in p]
    # an invader (not a great danger) inside: no flee
    d[0]["great"] = None
    assert all(x.rule != "shelter_flee" for x in run(s)[0])


CH = [{"x": 12, "y": 20, "z": 170, "from_src": 2, "to_shelter": 25, "width": 2},
      {"x": 30, "y": 20, "z": 168, "from_src": 20, "to_shelter": 12, "width": 1}]


@test("choke: the first from the threat's side, off the shelter's levels, far enough, narrow enough")
def _():
    s = state(splan([cand(160, 45, wells=1, chokes=CH)], current=[160]))
    spot = PS.squad_station_spot(s, CFG)
    assert (spot["x"], spot["y"], spot["z"], spot["kind"]) == (12, 20, 170, "choke"), spot
    cfg = dict(CFG, shelter_choke_min_tiles=30)
    s2 = state(splan([cand(160, 45, wells=1, chokes=CH)], current=[160]))
    assert PS.squad_station_spot(s2, cfg) is None
    # a choke on the shelter's own level is not taken
    s3 = state(splan([cand(170, 45, wells=1, chokes=CH)], current=[170]))
    assert PS.squad_station_spot(s3, CFG)["z"] == 168
    # a pick proposed this cycle counts over the one in use
    props = [Proposal("shelter_pick", {"type": "shelter_pick", "levels": [168, 170]}, "x", 0)]
    s4 = state(splan([cand(170, 45, wells=1, chokes=CH)], current=[160]))
    assert PS.squad_station_spot(s4, CFG, props) is None


@test("choke: none: the barracks off the shelter's levels (the squads' own first); none at all: None")
def _():
    bars = [{"id": 1, "x": 50, "y": 50, "z": 160, "squads": [7], "walkable": True},
            {"id": 2, "x": 60, "y": 50, "z": 158, "squads": [], "walkable": True},
            {"id": 3, "x": 70, "y": 50, "z": 157, "squads": [7], "walkable": True}]
    s = state(splan([cand(160, 45, wells=1)], current=[160], barracks=bars), squads=[{"id": 7}])
    spot = PS.squad_station_spot(s, CFG)
    assert spot["kind"] == "barracks" and spot["z"] == 157, spot
    s = state(splan([cand(160, 45, wells=1)], current=[160], barracks=bars[:1]))
    assert PS.squad_station_spot(s, CFG) is None


SQ = {"id": 7, "name": "The Axes", "members": 5, "power": {"power": 50, "armed": 5}, "orders": 0, "ai_orders": 0}


def army(s, monkey_hide=True):
    props, notes = [], []
    old = PA.hiding
    if monkey_hide:
        PA.hiding = lambda s_, m_, c_: (True, [])
    try:
        PA._shelter_squads_rule(s, Memory(), CFG, props, notes)
    finally:
        PA.hiding = old
    return props, notes


@test("squads: while the dwarves hide they stand at the choke, not in the shelter")
def _():
    s = state(splan([cand(160, 45, wells=1, chokes=CH)], current=[160]), alert=True, squads=[dict(SQ)])
    s["civ_alert_ready"] = True
    p, n = army(s)
    assert [x.action for x in p] == [{"type": "shelter_squads", "squads": [7], "station": {"x": 12, "y": 20, "z": 170}}], \
        [x.action for x in p]
    assert "between it and the civilians' shelter" in p[0].reason
    # already there: nothing
    s["military"]["squads"] = [dict(SQ, sheltering=True, stationed={"x": 12, "y": 20, "z": 170}, ai_orders=1, orders=1)]
    assert army(s)[0] == []
    # in the old shelter (the burrow): moved to the choke
    s["military"]["squads"] = [dict(SQ, sheltering=True, ai_orders=1, orders=1)]
    p, n = army(s)
    assert p and p[0].action.get("station"), [x.action for x in p]


@test("squads: no choke nor barracks: a squad in the civilians' shelter is called out, a note; no plan: the old way")
def _():
    s = state(splan([cand(160, 45, wells=1)], current=[160]), alert=True,
              squads=[dict(SQ, sheltering=True, ai_orders=1, orders=1)])
    s["civ_alert_ready"] = True
    p, n = army(s)
    assert [x.rule for x in p] == ["squad_recall"] and "never in the civilians' shelter" in n[0], (p, n)
    s = state({}, alert=True, squads=[dict(SQ)])
    s["civ_alert_ready"] = True
    p, n = army(s)
    assert [x.action for x in p] == [{"type": "shelter_squads", "squads": [7]}], [x.action for x in p]


@test("brain: plan() carries the rule through the planner (the fixture fort with a titan at the gate)")
def _():
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    base["shelter_plan"] = splan([cand(165, 30, drink=100), cand(160, 45, wells=1)])
    base["civ_alert_shelter"] = "ai"
    s = normalize(base)
    props, notes = full_plan(s, Memory())
    assert any(x.rule == "shelter_pick" for x in props), [x.rule for x in props]
    # without the section nothing about it
    base.pop("shelter_plan")
    props, notes = full_plan(normalize(base), Memory())
    assert not any(x.rule in ("shelter_pick", "shelter_flee") for x in props)


# --- 4. the wiring --------------------------------------------------------------------

@test("wiring: actions, dry runs, the section (and the pulse), the module list, digest default, labels")
def _():
    hub = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert re.search(r"^\s+shelter_pick = function\(a\)", hub, re.M) and re.search(r"^\s+squad_station = function\(a\)", hub, re.M)
    dry = hub[hub.index("DRY_OK = {}"):]
    assert "'shelter_pick', 'squad_station'" in dry[:dry.index("do DRY_OK") if "do DRY_OK" in dry else 20000]
    assert "shelter_plan = function() return safe(function() return reqscript('ai-shelter-plan').report(txt)" in hub
    pulse = hub[hub.index("PULSE_SECTIONS = {"):]
    assert "'shelter_plan'" in pulse[:pulse.index("}")]
    assert "'ai-shelter-plan'" in hub[hub.index("BRIDGE_MODULES = {"):]
    assert SECTION_DEFAULTS.get("shelter_plan") == {}
    import overseer
    assert "away from the threat" in overseer.short({"type": "shelter_pick", "levels": [160]})
    assert "whole fort" in overseer.short({"type": "shelter_pick", "clear": True})
    assert "between the threat" in overseer.short({"type": "shelter_squads", "squads": [7],
                                                    "station": {"x": 1, "y": 2, "z": 3}})
    assert overseer.short({"type": "shelter_squads", "squads": [7]}) == "send 1 squad(s) to wait in the shelter"
    from planner_core import EMERGENCY, NO_COOLDOWN
    assert {"shelter_pick", "shelter_flee"} <= EMERGENCY and "shelter_flee" in NO_COOLDOWN
    for k in ("shelter_pick_margin", "shelter_flee_tiles", "shelter_choke_min_tiles", "shelter_pick_cooldown_ticks"):
        assert k in PLANNER_CONFIG, k
    acts = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    assert "M.station(id, sx, sy, sz, a.dry_run == true)" in acts
    mil = (LUA_DIR / "ai-military.lua").read_text(encoding="utf-8")
    assert "df.squad_order_movest:new()" in mil and "stationed = stationed" in mil


if __name__ == "__main__":
    finish()
