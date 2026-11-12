"""(0.105.41, item 7) Environment hazards: lua/ai-hazards.lua in a fake fort
(spilt magma found, recorded, spreading, guarded and reclaimed; the AI's
magma works, the map's own magma and a magma workshop's pit left out; the
cave-in check before a channel; cave-ins with the hurt and the cut off;
frozen wells, water zones and moat; what burns by a magma workshop), the
bridge's wiring, and the brain (brain/planner_hazards.py: the guard, the
floodgate shut, the alarm, the reclaim and its Rules switch, the way dug to
the cut off, a well and a water zone for the frost, the heat notes; plan()
without the section unchanged).

    python tests/test_hazards.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
import planner_hazards as PH  # noqa: E402
from planner_military import hazard_alert  # noqa: E402
from digest import normalize, SECTION_DEFAULTS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
DAY = 1200

# The fake fort. W.tiles["x,y,z"] = {shape, material, liquid, magma, depth,
# outside, hidden, dig} (default: a floor with a wall under it, i.e. any
# tile at z < 100 is a wall); W.magma["x,y,z"] = {depth, feature} (what the
# blocks hold); W.cits; W.traffic; W.jobs; W.dug (cells dug).
FAKE = r"""
local src = ...
local W = {tiles = {}, magma = {}, cits = {}, traffic = {}, jobs = {}, dug = {}, removed = 0, site = {},
           works = {}, shops = {}, anns = {}, wells = {}, zones = {}, moat = {}, stuff = {}, heat = {},
           moving = true, t = 1000000}
local env = setmetatable({}, {__index = _G})
local key = function(x, y, z) return x .. ',' .. y .. ',' .. z end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {global = {cur_year = 2, cur_year_tick = 0}}
env.dfhack = {persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                            saveSiteData = function(k, v) W.site[k] = v end}}
env.reqscript = function(name)
    if name == 'ai-reports' then return W.reports end
    error('no module ' .. tostring(name))
end
assert(load(src, 'ai-hazards', 't', env))()
env.now = function() return W.t end
env.citizens = function() return W.cits end
env.tile = function(x, y, z)
    local t = W.tiles[key(x, y, z)]
    if t then return t end
    if z < 100 then return {shape = 'WALL', material = 'STONE'} end
    return {shape = 'FLOOR', material = 'STONE'}
end
env.map_blocks = function() return 20, 20, 200 end
env.block_magma = function(bx, by, z)
    local out = {}
    for k, m in pairs(W.magma) do
        local x, y, zz = k:match('^(%d+),(%d+),(%d+)$')
        x, y, zz = tonumber(x), tonumber(y), tonumber(zz)
        if zz == z and x // 16 == bx and y // 16 == by then
            table.insert(out, {x = x, y = y, z = z, depth = m.depth or 7, feature = m.feature or false})
        end
    end
    return out, W.moving
end
env.magma_works = function() return W.works end
env.magma_shops = function() return W.shops end
env.moat_tiles = function() return W.moat end
env.gate_magma_safe = function(id) return W.gate_safe end
env.items_near = function(x, y, z, r) return W.stuff[key(x, y, z)] or {burns = 0, melts = 0, on_fire = 0} end
env.unit_heat = function(u) return W.heat[u.id] or {on_fire = false} end
env.unit_hurt = function(u) return u.hurt == true end
env.walk_group = function(x, y, z) return (W.groups or {})[key(x, y, z)] or 1 end
env.temp_at = function(x, y, z) return W.temp end
env.wells = function() return W.wells end
env.water_zones = function() return W.zones end
env.announcements = function(since)
    local out = {}
    for _, a in ipairs(W.anns) do if a.tick >= since then table.insert(out, a) end end
    return out
end
env.classify = function(t, text) if tostring(text):find('cave') then return 'cave_in' end end
env.each_job = function(fn) for _, j in ipairs(W.jobs) do if fn(j.pos, j.jt, j) == false then return end end end
env.remove_job = function(j) j.removed = true; W.removed = W.removed + 1; return true end
env.job_ok = function(jt) return jt == 'Dig' or jt == 'StoreItemInStockpile' end
env.traffic = function(x, y, z) return W.traffic[key(x, y, z)] or 'Normal' end
env.set_traffic = function(x, y, z, n) W.traffic[key(x, y, z)] = n; return true end
env.dig_tiles = function(cells, z)
    for _, c in ipairs(cells) do table.insert(W.dug, key(c.x, c.y, z)) end
    return #cells
end
env.log_line = function() end
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-hazards.lua"))
    env.FULL_SCAN_AT = None
    env.LIGHT = None
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


def cit(lua, w, id_, x, y, z, **kw):
    c = T(lua, dict({"id": id_, "name": f"Urist {id_}", "x": x, "y": y, "z": z}, **kw))
    c.u = c
    w.cits[len(w.cits) + 1] = c
    return c


def spill(lua, w, tiles, z=100, **kw):
    for x, y in tiles:
        w.magma[f"{x},{y},{z}"] = T(lua, dict({"depth": 5}, **kw))


def report(env):
    env.LIGHT = None
    return py(env.report())


# --- 1. spilt magma found ----------------------------------------------------------

@test("magma: spilt magma near a dwarf is found, recorded, put in a spot with the nearest dwarf; not 'spreading' at the first read")
def _():
    lua, env, w = world()
    if LuaRuntime is None:
        return
    cit(lua, w, 1, 50, 50, 100)
    spill(lua, w, [(53, 50), (54, 50)])
    r = report(env)
    m = r["magma"]
    assert m["loose"] == 2 and len(m["cells"]) == 1, m
    assert m["cells"][0]["near"] == 3 and m["cells"][0]["n"] == 2, m
    assert "grew_ago" not in m, m
    st = py(w.site["ai-overseer/hazards"])
    assert set(st["magma"]["tiles"]) == {"53,50,100", "54,50,100"}, st
    assert all(v["near"] for v in st["magma"]["tiles"].values()), st


@test("magma: a new tile at a later read marks it spreading (grew_ago); a dwarf on a magma tile is burning")
def _():
    lua, env, w = world()
    cit(lua, w, 1, 50, 50, 100)
    spill(lua, w, [(53, 50)])
    report(env)
    w.t = w.t + 40
    spill(lua, w, [(52, 50), (50, 50)])
    m = report(env)["magma"]
    assert m["grew_ago"] == 0 and m["loose"] == 3, m
    assert m["burning"] == [{"id": 1, "name": "Urist 1"}], m


@test("magma: the map's own magma (a feature), the AI's magma works' tiles and a magma workshop's pit are not spilt")
def _():
    lua, env, w = world()
    cit(lua, w, 1, 50, 50, 100)
    spill(lua, w, [(55, 50)], feature=True)
    spill(lua, w, [(45, 45)])
    w.works = T(lua, [{"id": "magma:MagmaForge", "shop": "MagmaForge", "stage": "done",
                       "tiles": [{"x": 44, "y": 45, "z": 100}], "gate": {"x": 44, "y": 45, "z": 100}}])
    spill(lua, w, [(60, 60)], z=99)
    w.shops = T(lua, [{"id": 9, "kind": "MagmaSmelter", "x1": 59, "y1": 59, "x2": 61, "y2": 61, "z": 100, "x": 60, "y": 60}])
    m = report(env)["magma"]
    assert m["loose"] == 0 and not m["cells"], m


@test("magma: a spot near the AI's magma works names it (for the floodgate); a still block is read only once a day")
def _():
    lua, env, w = world()
    cit(lua, w, 1, 50, 50, 100)
    w.works = T(lua, [{"id": "magma:MagmaForge", "shop": "MagmaForge", "stage": "done",
                       "tiles": [{"x": 40, "y": 50, "z": 100}], "gate": {"x": 40, "y": 50, "z": 100}}])
    spill(lua, w, [(48, 50)])
    m = report(env)["magma"]
    c = m["cells"][0]
    assert c["work"] == "magma:MagmaForge" and c["work_shop"] == "MagmaForge" and c["work_d"] == 8, c
    # a block with no moving liquid, read again within the day: only the recorded tiles' blocks are read
    w.moving = False
    spill(lua, w, [(20, 50)])
    w.t += 100
    m = report(env)["magma"]
    assert m["loose"] == 1 and m["blocks_still"] > 0, m


# --- 2. guard and reclaim --------------------------------------------------------

@test("magma_guard: tiles round the spilt magma near the dwarves restricted (only Normal ones), jobs beside it off; lift undoes it")
def _():
    lua, env, w = world()
    cit(lua, w, 1, 50, 50, 100)
    spill(lua, w, [(53, 50)])
    report(env)
    w.traffic["53,51,100"] = "High"
    w.jobs = T(lua, [{"pos": {"x": 54, "y": 50, "z": 100}, "jt": "Dig"},
                     {"pos": {"x": 54, "y": 50, "z": 100}, "jt": "Eat"},
                     {"pos": {"x": 70, "y": 50, "z": 100}, "jt": "Dig"}])
    dry = py(env.magma_guard(1, 10, False, True))
    assert dry["restricted"] == 8 and dry["jobs_removed"] == 1 and dry["dry_run"], dry
    assert not any(v == "Restricted" for v in py(w.traffic).values()), "dry run changed nothing"
    r = py(env.magma_guard(1, 10, False, False))
    assert r["ok"] and r["restricted"] == 8 and r["jobs_removed"] == 1 and w.removed == 1, r
    assert py(w.traffic)["53,51,100"] == "High", "the player's traffic kept"
    again = py(env.magma_guard(1, 10, False, False))
    assert again["restricted"] == 0, again
    lift = py(env.magma_guard(1, 10, True, False))
    assert lift["lifted"] == 8 and not any(v == "Restricted" for v in py(w.traffic).values()), lift


@test("magma_guard: refused with nothing to do when no spilt magma is near the dwarves")
def _():
    lua, env, w = world()
    cit(lua, w, 1, 10, 10, 100)
    spill(lua, w, [(40, 40)])
    report(env)
    r = py(env.magma_guard(3, 10, False, False))
    assert r["rejected"] and r["nothing_to_do"], r


@test("magma: cooled tiles reported settled with how long dry and the walls left; magma_reclaim digs a wall, never one beside liquid")
def _():
    lua, env, w = world()
    cit(lua, w, 1, 50, 50, 100)
    spill(lua, w, [(53, 50), (54, 50), (55, 50)])
    report(env)
    env.magma_guard(1, 10, False, False)
    # it cooled: two tiles are obsidian walls now, one still floor; water beside the third wall
    w.magma = T(lua, {})
    w.tiles["53,50,100"] = T(lua, {"shape": "WALL", "material": "STONE"})
    w.tiles["55,50,100"] = T(lua, {"shape": "WALL", "material": "STONE"})
    w.tiles["56,50,100"] = T(lua, {"shape": "FLOOR", "liquid": True, "depth": 3})
    w.t += 4 * DAY
    m = report(env)["magma"]
    assert m["loose"] == 0 and len(m["settled"]) == 1, m
    s0 = m["settled"][0]
    assert s0["n"] == 3 and s0["walls"] == 2 and s0["dry"] == 4 * DAY and s0["near"], s0
    too_soon = py(env.magma_reclaim(5 * DAY, True, False))
    assert too_soon["cooled"] == 0 and too_soon["lifted"] > 0, too_soon   # the paths opened (no live magma)
    r = py(env.magma_reclaim(3 * DAY, True, False))
    assert r["cooled"] == 3 and r["walls"] == 1 and r["beside_liquid"] == 1, r
    assert py(w.dug) == ["53,50,100"], py(w.dug)
    st = py(w.site["ai-overseer/hazards"])
    assert not st["magma"]["tiles"] and not st["magma"]["restricted"], st


@test("magma_reclaim: dig false only opens the paths; nothing cooled and nothing restricted: refused")
def _():
    lua, env, w = world()
    r = py(env.magma_reclaim(DAY, True, False))
    assert r["rejected"] and r["nothing_to_do"], r
    cit(lua, w, 1, 50, 50, 100)
    spill(lua, w, [(53, 50)])
    report(env)
    w.magma = T(lua, {})
    w.tiles["53,50,100"] = T(lua, {"shape": "WALL", "material": "STONE"})
    w.t += 4 * DAY
    report(env)
    r = py(env.magma_reclaim(3 * DAY, False, False))
    assert r["cooled"] == 1 and r["walls"] == 0 and not py(w.dug), r


# --- 3. the cave-in check before a channel ------------------------------------------

def island_world(lua, w):
    """Level 100: a 3x1 floor strip at x 50-52 y 50, everything round it open
    (EMPTY) but channels to be dug at x 49 and x 53; level 99 under the strip
    open too (a room dug out below), so only the floor's ends hold it."""
    for x in range(46, 57):
        for y in range(47, 54):
            w.tiles[f"{x},{y},100"] = T(lua, {"shape": "EMPTY"})
            w.tiles[f"{x},{y},99"] = T(lua, {"shape": "FLOOR"})
    for x in range(49, 54):
        w.tiles[f"{x},50,100"] = T(lua, {"shape": "FLOOR"})
    # x 48 and x 54 at y 50: floor that runs on to the rock (a wall beyond)
    for x in (47, 48, 54, 55):
        w.tiles[f"{x},50,100"] = T(lua, {"shape": "FLOOR"})
    w.tiles["46,50,100"] = T(lua, {"shape": "WALL"})
    w.tiles["56,50,100"] = T(lua, {"shape": "WALL"})


@test("channel check: channels at both ends of a floor strip over an open room leave it hanging: the first refused (the strip held by it), one end alone is let by")
def _():
    lua, env, w = world()
    island_world(lua, w)
    bad = py(env.channel_islands(T(lua, [{"x": 49, "y": 50}, {"x": 53, "y": 50}]), 100))
    assert set(bad) == {"49,50,100"} and "hang over nothing" in bad["49,50,100"], bad
    ok = py(env.channel_islands(T(lua, [{"x": 49, "y": 50}]), 100))
    assert not ok, ok
    # a channel already designated at the other end counts as dug
    w.tiles["53,50,100"] = T(lua, {"shape": "FLOOR", "dig": "Channel"})
    bad2 = py(env.channel_islands(T(lua, [{"x": 49, "y": 50}]), 100))
    assert set(bad2) == {"49,50,100"}, bad2


@test("channel check: on rock (a wall under every floor) nothing is refused")
def _():
    lua, env, w = world()
    bad = py(env.channel_islands(T(lua, [{"x": 10, "y": 10}, {"x": 12, "y": 10}]), 100))
    assert not bad, bad


@test("channel_check: quickfort data with the hanging channels taken out, other keys kept, recorded only for real")
def _():
    lua, env, w = world()
    island_world(lua, w)
    data = lua.table_from({100: lua.table_from({50: lua.table_from({49: "h", 53: "h", 60: "d"})})})
    out, n, why = env.channel_check(data, 0, 0, 0, False)
    o = py(out)
    assert n == 1 and "cave-in" in why and o[100][50] == {53: "h", 60: "d"}, (n, o)
    assert py(env.CHANNEL_GUARD)["refused"] == 0
    out, n, why = env.channel_check(data, 0, 0, 0, True)
    g = py(env.CHANNEL_GUARD)
    assert g["refused"] == 1 and g["last"]["z"] == 100, g
    same, n0, _ = env.channel_check(lua.table_from({100: lua.table_from({10: lua.table_from({10: "h"})})}), 0, 0, 0, True)
    assert n0 == 0, n0


# --- 4. cave-ins -----------------------------------------------------------------------

@test("cave-ins: the announcement's spot with the hurt and the cut off near it; old ones and other news left out")
def _():
    lua, env, w = world()
    cit(lua, w, 1, 50, 50, 100, hurt=True)
    cit(lua, w, 2, 52, 50, 100)
    cit(lua, w, 3, 80, 80, 100)
    cit(lua, w, 4, 81, 80, 100)
    cit(lua, w, 5, 82, 80, 100)
    w.groups = T(lua, {"52,50,100": 7})
    w.anns = T(lua, [{"type": "CAVE_COLLAPSE", "text": "A section of the cavern has collapsed!", "x": 51, "y": 51,
                      "z": 100, "tick": w.t - 100},
                     {"type": "CAVE_COLLAPSE", "text": "the cave collapsed", "x": 52, "y": 51, "z": 100,
                      "tick": w.t - 90},
                     {"type": "MIGRANTS", "text": "Migrants have arrived", "tick": w.t - 10},
                     {"type": "CAVE_COLLAPSE", "text": "cave-in long ago", "x": 10, "y": 10, "z": 100,
                      "tick": w.t - 10 * DAY}])
    cv = report(env)["cave_ins"]
    assert len(cv["list"]) == 1, cv
    c = cv["list"][0]
    assert c["ago"] == 100 and c["n"] == 2, c
    assert [h["id"] for h in c["hurt"]] == [1], c
    assert [t["id"] for t in c["trapped"]] == [2] and c["trapped"][0]["x"] == 52, c


# --- 5. frost and heat -----------------------------------------------------------------

@test("frost: each well's water (water, ice, dry), the AI's water zones, the moat frozen, dwarves on ice, the surface freezing")
def _():
    lua, env, w = world()
    cit(lua, w, 1, 30, 30, 120)
    w.tiles["30,30,120"] = T(lua, {"shape": "FLOOR", "material": "FROZEN_LIQUID", "outside": True})
    w.temp = 9990
    w.wells = T(lua, [{"id": 1, "x": 10, "y": 10, "z": 120}, {"id": 2, "x": 20, "y": 20, "z": 120}])
    for z in range(115, 120):
        w.tiles[f"10,10,{z}"] = T(lua, {"shape": "EMPTY"})
        w.tiles[f"20,20,{z}"] = T(lua, {"shape": "EMPTY"})
    w.tiles["10,10,114"] = T(lua, {"shape": "FLOOR", "material": "FROZEN_LIQUID", "outside": True})
    w.tiles["20,20,114"] = T(lua, {"shape": "FLOOR", "liquid": True, "outside": False})
    w.zones = T(lua, [{"x": 40, "y": 40, "z": 120}])
    w.tiles["40,40,120"] = T(lua, {"shape": "FLOOR", "material": "FROZEN_LIQUID", "outside": True})
    w.moat = T(lua, [{"x": 60, "y": y, "z": 120} for y in range(10)])
    for y in range(10):
        w.tiles[f"60,{y},120"] = T(lua, {"shape": "FLOOR", "material": "FROZEN_LIQUID"})
    f = report(env)["frost"]
    assert [x["water"] for x in f["wells"]] == ["ice", "water"] and f["wells"][0]["outside"], f
    assert f["zones"][0]["water"] == "ice", f
    assert f["moat"]["frozen"] and f["moat"]["ice"] == f["moat"]["looked"], f
    assert f["on_ice"][0]["id"] == 1 and f["freezing"] and f["surface_temp"] == 9990, f


@test("heat: what burns or melts by a magma workshop, an AI floodgate that isn't magma-safe, a burning dwarf near it")
def _():
    lua, env, w = world()
    cit(lua, w, 1, 61, 60, 100)
    cit(lua, w, 2, 90, 90, 100)
    w.shops = T(lua, [{"id": 9, "kind": "MagmaForge", "x1": 59, "y1": 59, "x2": 61, "y2": 61, "z": 100, "x": 60, "y": 60}])
    w.stuff["60,60,100"] = T(lua, {"burns": 3, "melts": 1, "on_fire": 0})
    w.works = T(lua, [{"id": "magma:MagmaForge", "shop": "MagmaForge", "gate_id": 77, "tiles": []}])
    w.gate_safe = False
    w.heat = T(lua, {1: {"on_fire": True}, 2: {"on_fire": True}})
    h = report(env)["heat"]
    assert h["shops"][0]["burns"] == 3 and h["shops"][0]["melts"] == 1, h
    assert h["works"] == [{"id": "magma:MagmaForge", "shop": "MagmaForge", "gate_safe": False}], h
    assert [b["id"] for b in h["burning"]] == [1], h      # the far one isn't read


@test("heat_risk: wood burns, a low-melting metal melts, a fixed-temperature or high-melting one is safe")
def _():
    lua, env, w = world()
    assert env.heat_risk(T(lua, {"ignite_point": 10508, "melting_point": 60001})) == "burns"
    assert env.heat_risk(T(lua, {"ignite_point": 60001, "melting_point": 11500})) == "melts"
    assert env.heat_risk(T(lua, {"ignite_point": 60001, "melting_point": 12500, "boiling_point": 15000,
                                 "heatdam_point": 60001})) is None
    assert env.heat_risk(T(lua, {"mat_fixed_temp": 10000, "ignite_point": 10500})) is None


@test("report: the cave-ins, frost and heat are read again only after LIGHT_TICKS (the magma every time)")
def _():
    lua, env, w = world()
    cit(lua, w, 1, 50, 50, 100)
    r1 = py(env.report())
    w.anns = T(lua, [{"type": "X", "text": "cave-in", "x": 50, "y": 50, "z": 100, "tick": w.t}])
    w.t += 10
    r2 = py(env.report())
    assert not r2["cave_ins"]["list"] and r2["read_ago"] == 10, r2
    w.t += 400
    r3 = py(env.report())
    assert len(r3["cave_ins"]["list"]) == 1 and r3["read_ago"] == 0, r3


# --- 6. the bridge's wiring ---------------------------------------------------------

@test("bridge: the actions in ACTIONS and DRY_OK, the section (in the pulse), the module listed; digest default; the builder's hook")
def _():
    hub = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert re.search(r"^\s*magma_guard = function\(a\)", hub, re.M) and re.search(r"^\s*magma_reclaim = function\(a\)", hub, re.M)
    assert "'magma_guard', 'magma_reclaim'," in hub
    assert re.search(r"env_hazards = function\(\) return safe\(function\(\) return reqscript\('ai-hazards'\)\.report\(\)", hub)
    pulse = re.search(r"PULSE_SECTIONS = \{(.*?)\n\}", hub, re.S).group(1)
    assert "'env_hazards'" in pulse
    assert "'ai-hazards'," in re.search(r"BRIDGE_MODULES = \{(.*?)\n\}", hub, re.S).group(1)
    assert SECTION_DEFAULTS.get("env_hazards") == {}
    b = (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8")
    assert "reqscript('ai-hazards').channel_check(data, ax, ay, 0, not dry_run)" in b
    st = (LUA_DIR / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    assert "magma_reclaim = true," in st and "'magma_reclaim'," in st and "magma_reclaim = s.magma_reclaim" in st
    import overseer
    assert overseer.short({"type": "magma_guard"}) == "keep the dwarves away from the spilt magma"
    assert "back to normal" in overseer.short({"type": "magma_guard", "lift": True})
    assert overseer.short({"type": "magma_reclaim"}) == overseer.SHORT_WORDS["magma_reclaim"]


# --- 7. the brain ---------------------------------------------------------------------

def base_state():
    s = normalize({"date": {"year": 2, "tick": 0, "season": "winter"},
                   "dwarves": {"total": 10, "adults": 10, "idle_adults": 0},
                   "stocks": {"drink": 100, "food": 100}, "settings": {}})
    return s


def with_env(s, **parts):
    s = copy.deepcopy(s)
    s["env_hazards"] = parts
    return s


def rules(s, memory=None):
    props, notes = [], []
    PH._hazards_rule(s, memory or Memory(), PLANNER_CONFIG, props, notes)
    return props, notes


@test("brain: spilt magma near the dwarves: the guard, the AI's magma works beside it shut, said; far from them: said only")
def _():
    s = base_state()
    s["waterworks"] = {"works": {"magma:MagmaForge": {"kind": "magma", "gate": "open", "shop": "MagmaForge"}}}
    s = with_env(s, magma={"loose": 4, "grew_ago": 20, "restricted": 0,
                           "cells": [{"x": 53, "y": 50, "z": 100, "n": 4, "near": 3, "work": "magma:MagmaForge",
                                      "work_shop": "MagmaForge", "work_d": 8}]})
    props, notes = rules(s)
    kinds = {p.rule: p.action for p in props}
    assert kinds["magma_guard"] == {"type": "magma_guard", "radius": 3, "max_jobs": 40}, kinds
    assert kinds["magma_shut"] == {"type": "water_work", "kind": "magma", "shop": "MagmaForge", "shut": True,
                                   "why": "spilt magma near it"}, kinds
    assert any("spilt magma: 4 tile(s)" in n and "spreading" in n for n in notes), notes
    far = with_env(base_state(), magma={"loose": 2, "cells": [{"x": 5, "y": 5, "z": 100, "n": 2, "near": 30}]})
    props, notes = rules(far)
    assert not props and any("spilt magma" in n for n in notes), (props, notes)


@test("brain: the alarm while spilt magma spreads near the dwarves (hazard_alert), not once it stands still")
def _():
    s = with_env(base_state(), magma={"loose": 2, "grew_ago": 50, "cells": [{"x": 1, "y": 2, "z": 3, "n": 2, "near": 4}]})
    assert "spilt magma spreading 4 tiles" in hazard_alert(s, PLANNER_CONFIG)
    still = with_env(base_state(), magma={"loose": 2, "grew_ago": 500, "cells": [{"x": 1, "y": 2, "z": 3, "n": 2, "near": 4}]})
    assert hazard_alert(still, PLANNER_CONFIG) == ""
    far = with_env(base_state(), magma={"loose": 2, "grew_ago": 0, "cells": [{"x": 1, "y": 2, "z": 3, "n": 2, "near": 20}]})
    assert hazard_alert(far, PLANNER_CONFIG) == ""
    s2 = copy.deepcopy(s)
    s2["civ_alert_ready"] = True
    s2["hazards"] = {}
    props, _ = plan(s2, Memory())
    assert any(p.action == {"type": "civ_alert", "on": True} and "spilt magma" in p.reason for p in props), \
        [(p.rule, p.reason) for p in props]


@test("brain: cooled spilt magma reclaimed after magma_cool_days (dig by the Rules switch); before that, said")
def _():
    cool = 3 * DAY
    s = with_env(base_state(), magma={"loose": 0, "restricted": 9, "cells": [],
                                      "settled": [{"x": 5, "y": 6, "z": 100, "n": 3, "dry": 4 * DAY, "walls": 2}]})
    props, _ = rules(s)
    p = next(p for p in props if p.rule == "magma_reclaim")
    assert p.action == {"type": "magma_reclaim", "cool_ticks": cool, "dig": True} and "2 wall(s)" in p.reason, p
    s["settings"]["magma_reclaim"] = False
    props, _ = rules(s)
    p = next(p for p in props if p.rule == "magma_reclaim")
    assert p.action["dig"] is False and "leave what it left alone" in p.reason, p
    young = with_env(base_state(), magma={"loose": 0, "restricted": 9, "cells": [],
                                          "settled": [{"x": 5, "y": 6, "z": 100, "n": 3, "dry": DAY, "walls": 2}]})
    props, notes = rules(young)
    assert not props and any("reclaimed after 3 day(s)" in n for n in notes), (props, notes)


@test("brain: a cave-in: the hurt and the cut off said; cut off past the wait: a way dug to them, not while one is dug or enemies reach")
def _():
    row = {"x": 50, "y": 50, "z": 100, "ago": 100, "n": 1,
           "hurt": [{"id": 1, "name": "Urist"}], "trapped": [{"id": 2, "name": "Bomrek", "x": 52, "y": 50, "z": 100}]}
    s = with_env(base_state(), cave_ins={"list": [row]})
    s["threats"] = {"rescue": {"holders": 0}}
    props, notes = rules(s)
    assert not props and any("1 hurt near it" in n and "2 are put on it" in n and "cut off" in n for n in notes), notes
    assert any("after 6 hour(s)" in n for n in notes), notes
    row2 = dict(row, ago=7 * 50)
    s = with_env(base_state(), cave_ins={"list": [row2]})
    props, notes = rules(s)
    p = next(p for p in props if p.rule == "cave_in_dig_out")
    assert p.action == {"type": "dig_way_in", "x": 52, "y": 50, "z": 100}, p
    s["projects"] = {"open": [{"id": 4, "kind": "way_in", "phase": "dig"}]}
    props, notes = rules(s)
    assert not props and any("being dug" in n for n in notes), notes
    s["projects"] = {}
    s["others_on_map"] = {"threats_that_can_reach_dwarves": 2}
    props, notes = rules(s)
    assert not props, props


@test("brain: frost: every well frozen: a well inside the fort (urgent with the parched); a frozen water zone: underground water")
def _():
    s = with_env(base_state(), frost={"wells": [{"id": 1, "water": "ice"}], "zones": []})
    props, _ = rules(s)
    p = next(p for p in props if p.rule == "frost_well")
    assert p.action == {"type": "place_well", "inside_only": True}, p
    s["society"] = {"parched": 2}
    props, _ = rules(s)
    assert next(p for p in props if p.rule == "frost_well").action.get("urgent") is True
    s["projects"] = {"open": [{"id": 1, "kind": "well"}]}
    props, notes = rules(s)
    assert not any(p.rule == "frost_well" for p in props) and any("being dug" in n for n in notes)
    z = with_env(base_state(), frost={"wells": [], "zones": [{"x": 1, "y": 1, "z": 1, "water": "ice"}]})
    z["society"] = {"parched": 3}
    z["water"] = {"bodies": [{"kind": "river", "nearest": {"x": 1, "y": 1, "z": 1, "d": 5}},
                             {"kind": "pool", "underground": True, "nearest": {"x": 9, "y": 9, "z": 90, "d": 30}},
                             {"kind": "ice", "nearest": {"x": 2, "y": 2, "z": 2, "d": 3}}]}
    props, _ = rules(z)
    p = next(p for p in props if p.rule == "frost_water_zone")
    assert p.action == {"type": "water_zone", "points": [{"x": 9, "y": 9, "z": 90}]}, p
    z.pop("society")
    props, _ = rules(z)
    assert not any(p.rule == "frost_water_zone" for p in props)


@test("brain: frost and heat notes: a frozen moat, dwarves on ice in spring, what burns by a magma forge, an unsafe floodgate")
def _():
    s = with_env(base_state(), frost={"moat": {"frozen": True}, "on_ice": [{"id": 1, "name": "Urist"}], "freezing": False},
                 heat={"shops": [{"kind": "MagmaForge", "x": 1, "y": 2, "z": 3, "burns": 2, "melts": 0}],
                       "works": [{"id": "magma:MagmaForge", "shop": "MagmaForge", "gate_safe": False}],
                       "burning": [{"id": 5, "name": "Kib"}], "hot": []})
    props, notes = rules(s)
    text = " | ".join(notes)
    assert "moat is frozen" in text and "stand on ice as it thaws" in text, text
    assert "2 thing(s) that burn" in text and "isn't magma-safe" in text and "on fire by the magma: Kib" in text, text
    assert not props


@test("brain: a failed part is said, the others run; a failed section proposes nothing")
def _():
    s = with_env(base_state(), magma={"error": "boom"}, frost={"wells": [{"water": "ice"}]})
    props, notes = rules(s)
    assert any(p.rule == "frost_well" for p in props)
    s2 = base_state()
    s2["env_hazards"] = {"error": "x"}
    assert rules(s2) == ([], [])


FIXTURES = sorted((ROOT / "tests" / "fixtures").glob("*.json"))


@test("plan(): with no env_hazards section, the same proposals and notes as with an empty one (fixtures)")
def _():
    n = 0
    for f in FIXTURES[:12]:
        try:
            st = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(st, dict) or "date" not in st or "dwarves" not in st:
            continue
        a = copy.deepcopy(st)
        a.pop("env_hazards", None)
        b = copy.deepcopy(st)
        b["env_hazards"] = {}
        pa, na = plan(a, Memory())
        pb, nb = plan(b, Memory())
        assert [(p.rule, p.action) for p in pa] == [(p.rule, p.action) for p in pb], f.name
        assert na == nb, f.name
        n += 1
    assert n > 0


if __name__ == "__main__":
    finish()
