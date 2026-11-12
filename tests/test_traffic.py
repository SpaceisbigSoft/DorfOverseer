"""(0.105.41, phase 13e) Traffic zones on the AI's own levels: lua/ai-traffic.lua
in a fake fort (each kind's tiles and classes, an older project's corridor,
the way in and the deep depot, only Normal tiles painted, slices and the
cursor, dry runs, the switch, the recheck and hands-off, ai_value), the fire
guard's and start_project's hooks, the bridge's wiring, the Rules switch
and its GUI row, and the brain (brain/planner_traffic.py).

    python tests/test_traffic.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish, code_has  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan, player_rules  # noqa: E402
import planner_traffic as PT  # noqa: E402
import digest  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
NORMAL, LOW, HIGH, RESTRICTED = 0, 1, 2, 3     # df-structures' tile_traffic order

FAKE = r"""
local src = ...
local W = {tiles = {}, site = {}, projects = {list = {}}, deep = nil, settings = {traffic = true}}
local env = setmetatable({}, {__index = _G})
local function key(x, y, z) return x .. ',' .. y .. ',' .. z end
function W.tile(x, y, z)
    local k = key(x, y, z)
    if not W.tiles[k] then W.tiles[k] = {traffic = 0} end
    return W.tiles[k]
end
W.CLOCK = 0
env.os = setmetatable({clock = function() return W.CLOCK end}, {__index = os})
env.df = {global = {cur_year = 200, cur_year_tick = 1000},
          tile_traffic = {Normal = 0, Low = 1, High = 2, Restricted = 3}}
env.dfhack = {
    maps = {getTileFlags = function(x, y, z)
        if x < 0 or y < 0 then return nil end
        return W.tile(x, y, z) end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
env.reqscript = function(n)
    if n == 'ai-builder' then
        return {load_projects = function() return W.projects end,
                deep_depot_data = function() return W.deep end}
    end
    if n == 'ai-overseer-settings' then return {load_settings = function() return W.settings end} end
    error('reqscript ' .. tostring(n))
end
assert(load(src, 'ai-traffic', 't', env))()
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-traffic.lua"))
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


def bedrooms(pid=1, phase="done", kind="bedrooms", links=True, **kw):
    """A level at z 100: stair (50, 50), anchor (55, 50); the corridor (51..54, 50)
    relative -4..-1; rooms: a 3x2 block at (1..3, -1..0) and one tile (0, 2)."""
    p = {"id": pid, "kind": kind, "phase": phase, "z": 100, "stair": {"x": 50, "y": 50},
         "anchor": {"x": 55, "y": 50}, "stairs": [{"z": 99, "text": "i"}],
         "cells": {"dig": [{"x": 1, "y": -1, "text": "d(3x2)"}, {"x": 0, "y": 2, "text": "d"},
                           {"x": -4, "y": 0, "text": "d"}, {"x": -3, "y": 0, "text": "d"},
                           {"x": -2, "y": 0, "text": "d"}, {"x": -1, "y": 0, "text": "d"}]},
         "corridor": 4, "new_corridor": 4}
    if links:
        p["links"] = [{"x": -4, "y": 0}, {"x": -3, "y": 0}, {"x": -2, "y": 0}, {"x": -1, "y": 0}]
    p.update(kw)
    return p


def put(lua, w, *projects):
    w.projects = T(lua, {"list": list(projects)})


def tiles(lua, env, p):
    return [(t["x"], t["y"], t["z"], t["v"]) for t in py(env.tiles_of(T(lua, p)))]


def tr(w, x, y, z=100):
    return w.tile(x, y, z).traffic


# --- 1. what each level gets ---------------------------------------------------------------

@test("tiles: a bedrooms level: the stair (its level and the stair level it dug) and the corridor High, "
      "every other dug tile Low, each tile once")
def _():
    lua, env, w = world()
    t = tiles(lua, env, bedrooms())
    high = {(x, y, z) for x, y, z, v in t if v == "high"}
    low = {(x, y, z) for x, y, z, v in t if v == "low"}
    assert high == {(50, 50, 100), (50, 50, 99), (51, 50, 100), (52, 50, 100), (53, 50, 100), (54, 50, 100)}, high
    assert low == {(56, 49, 100), (57, 49, 100), (58, 49, 100), (56, 50, 100), (57, 50, 100), (58, 50, 100),
                   (55, 52, 100)}, low
    assert len(t) == len(set((x, y, z) for x, y, z, _ in t))
    assert [v for *_, v in t] == sorted([v for *_, v in t])      # High first ('high' < 'low')


@test("tiles: a storage level gets only its stair and corridor (High); the rest stays Normal")
def _():
    lua, env, w = world()
    t = tiles(lua, env, bedrooms(kind="storage"))
    assert all(v == "high" for *_, v in t) and len(t) == 6, t


@test("tiles: an older level without links: its straight corridor found from the stair toward the anchor")
def _():
    lua, env, w = world()
    t = tiles(lua, env, bedrooms(links=False))
    high = {(x, y) for x, y, z, v in t if v == "high" and z == 100}
    assert high == {(50, 50), (51, 50), (52, 50), (53, 50), (54, 50)}, high
    # no corridor length on record: only the stair
    p = bedrooms(links=False)
    p.pop("corridor"), p.pop("new_corridor")
    assert {(x, y) for x, y, z, v in tiles(lua, env, p) if v == "high" and z == 100} == {(50, 50)}


@test("tiles: a way in is High all through (shaft stairs, gallery, dug cells)")
def _():
    lua, env, w = world()
    p = {"id": 3, "kind": "way_in", "phase": "done", "z": 100, "anchor": {"x": 10, "y": 10},
         "stair": {"x": 10, "y": 10}, "cells": {"dig": []},
         "shaft_stairs": [{"x": 10, "y": 10, "z": 100}, {"x": 10, "y": 10, "z": 101}],
         "gallery": [{"x": 11, "y": 10}, {"x": 12, "y": 10}]}
    t = tiles(lua, env, p)
    assert {(x, y, z) for x, y, z, v in t if v == "high"} == {(10, 10, 100), (10, 10, 101), (11, 10, 100),
                                                              (12, 10, 100)}, t


@test("report: only finished levels are waiting (dig, furnish, wells and cancelled ones not); the deep depot once dug")
def _():
    lua, env, w = world()
    put(lua, w, bedrooms(1), bedrooms(2, phase="furnish"), bedrooms(3, kind="well"),
        bedrooms(4, phase="cancelled"), bedrooms(5, phase="decorate", kind="tombs"))
    r = py(env.report())
    assert [p["key"] for p in r["pending"]] == ["p1", "p5"] and r["pending_total"] == 2, r
    assert r["painted"] == 0 and r["enabled"] is True and "audit_next" not in r
    w.deep = T(lua, {"stage": "digging", "tiles": [{"x": 1, "y": 1, "z": 90}]})
    assert py(env.report())["pending_total"] == 2
    w.deep = T(lua, {"stage": "placed", "tiles": [{"x": 1, "y": 1, "z": 90}, {"x": 2, "y": 1, "z": 90}]})
    r = py(env.report())
    assert r["pending_total"] == 3 and r["pending"][-1]["key"] == "deep", r


# --- 2. painting ---------------------------------------------------------------------------

@test("paint: only tiles at Normal change; the player's Low, High or Restricted ones are left and counted; "
      "the level is recorded and not painted again")
def _():
    lua, env, w = world()
    put(lua, w, bedrooms(1))
    w.tile(52, 50, 100).traffic = LOW          # the player's
    w.tile(57, 50, 100).traffic = RESTRICTED   # the player's
    w.tile(58, 50, 100).traffic = LOW          # already what the AI wants
    r = py(env.paint(T(lua, {}), False))
    assert r["ok"] and r["finished"] and r["key"] == "p1", r
    assert r["painted"] == 10 and r["other"] == 2 and r["kept"] == 1 and r["high"] == 5 and r["low"] == 5, r
    assert tr(w, 50, 50) == HIGH and tr(w, 50, 50, 99) == HIGH and tr(w, 51, 50) == HIGH
    assert tr(w, 52, 50) == LOW and tr(w, 57, 50) == RESTRICTED and tr(w, 56, 49) == LOW
    rep = py(env.report())
    assert rep["painted"] == 1 and rep["pending_total"] == 0 and rep["tiles"] == 10, rep
    again = py(env.paint(T(lua, {}), False))
    assert again["ok"] is False and again["nothing_to_do"] is True, again
    assert py(env.paint(T(lua, {"key": "p1"}), False))["nothing_to_do"] is True


@test("paint: in slices (max tiles a call): a cursor in the save, resumed next call, then the next level")
def _():
    lua, env, w = world()
    put(lua, w, bedrooms(1), bedrooms(2, kind="storage", z=120))
    r = py(env.paint(T(lua, {"max": 5}), False))
    assert r["ok"] and not r["finished"] and r["at"] == 5 and r["tiles"] == 13, r
    assert py(env.report())["cursor"] == {"key": "p1", "at": 5}
    r = py(env.paint(T(lua, {"max": 5}), False))
    assert r["at"] == 10 and not r["finished"]
    r = py(env.paint(T(lua, {"max": 5}), False))
    assert r["finished"] and r["painted"] == 13, r
    assert "cursor" not in py(env.report())
    r = py(env.paint(T(lua, {"max": 50}), False))
    # (its stair level z 99 is p1's too: already High, kept)
    assert r["key"] == "p2" and r["finished"] and r["painted"] == 5 and r["kept"] == 1, r
    assert tr(w, 50, 50, 120) == HIGH


@test("paint: the time budget stops a slice early (and it resumes)")
def _():
    lua, env, w = world()
    put(lua, w, bedrooms(1))
    env.os = lua.eval("setmetatable({clock = (function() local c = 0; return function() c = c + 0.02; return c end end)()}, {__index = os})")
    r = py(env.paint(T(lua, {"max": 100, "budget_ms": 30}), False))
    assert r["ok"] and not r["finished"] and 1 <= r["at"] < 13, r


@test("paint: a dry run counts and changes nothing (no tile, no cursor, no record)")
def _():
    lua, env, w = world()
    put(lua, w, bedrooms(1))
    r = py(env.paint(T(lua, {"max": 5}), True))
    assert r["ok"] and r["dry_run"] and r["painted"] == 5, r
    assert tr(w, 50, 50) == NORMAL and py(env.report())["pending_total"] == 1 and "cursor" not in py(env.report())


@test("paint: off on the Rules tab: refused, nothing painted; the report says so")
def _():
    lua, env, w = world()
    put(lua, w, bedrooms(1))
    w.settings = T(lua, {"traffic": False})
    r = py(env.paint(T(lua, {}), False))
    assert r["ok"] is False and "Rules" in r["error"] and tr(w, 50, 50) == NORMAL
    assert py(env.report())["enabled"] is False


@test("paint: a level gone from the records drops its cursor; nothing to do (no refusal back-off), "
      "an asked-for unknown level still refused")
def _():
    lua, env, w = world()
    put(lua, w, bedrooms(1))
    env.paint(T(lua, {"max": 3}), False)
    put(lua, w)
    r = py(env.paint(T(lua, {}), False))
    assert r["ok"] is False and "cursor" not in py(env.report()), r
    assert r.get("nothing_to_do") is True, r
    r2 = py(env.paint(T(lua, {"key": "p9"}), False))
    assert r2["ok"] is False and not r2.get("nothing_to_do"), r2


# --- 3. the recheck ------------------------------------------------------------------------

def painted(lua, env, w):
    put(lua, w, bedrooms(1))
    assert py(env.paint(T(lua, {}), False))["finished"]


@test("audit: a few tiles back at Normal (a guard lifted) are painted again; the level's check date moves")
def _():
    lua, env, w = world()
    painted(lua, env, w)
    w.tile(56, 49, 100).traffic = NORMAL
    w.tile(51, 50, 100).traffic = NORMAL
    env.df["global"].cur_year_tick = 50000
    r = py(env.paint(T(lua, {"key": "p1", "audit": True}), False))
    assert r["ok"] and r["repainted"] == 2 and not r.get("hands_off"), r
    assert tr(w, 56, 49) == LOW and tr(w, 51, 50) == HIGH
    a = py(env.report())["audit_next"]
    assert a["key"] == "p1" and a["days"] == 0, a


@test("audit: the player changed many tiles (or wiped them to Normal): the level is his from then on, never painted again")
def _():
    lua, env, w = world()
    painted(lua, env, w)
    for x in (56, 57, 58):
        w.tile(x, 49, 100).traffic = HIGH
        w.tile(x, 50, 100).traffic = HIGH
    r = py(env.paint(T(lua, {"key": "p1", "audit": True}), False))
    assert r["hands_off"] is True and "repainted" not in r, r
    rep = py(env.report())
    assert rep["hands_off"] == 1 and rep["painted"] == 0 and "audit_next" not in rep
    assert py(env.paint(T(lua, {"key": "p1", "audit": True}), False))["nothing_to_do"] is True
    assert env.ai_value(56, 49, 100) is None
    # wiped back to Normal
    lua, env, w = world()
    painted(lua, env, w)
    for t in list(w.tiles.values()):
        t.traffic = NORMAL
    r = py(env.paint(T(lua, {"key": "p1", "audit": True}), False))
    assert r["hands_off"] is True and tr(w, 50, 50) == NORMAL, r


@test("audit: tiles a guard restricted (a fire) don't count against the level; a dry run changes nothing")
def _():
    lua, env, w = world()
    painted(lua, env, w)
    for x in (56, 57, 58):
        w.tile(x, 49, 100).traffic = RESTRICTED
        w.tile(x, 50, 100).traffic = RESTRICTED
    w.tile(55, 52, 100).traffic = NORMAL
    r = py(env.paint(T(lua, {"key": "p1", "audit": True}), True))
    assert not r.get("hands_off") and r["restricted"] == 6 and r["repainted"] == 1, r
    assert tr(w, 55, 52) == NORMAL       # a dry run
    assert py(env.paint(T(lua, {"key": "p1", "audit": True}), False))["repainted"] == 1
    assert tr(w, 55, 52) == LOW


@test("audit: needs a painted level; ai_value gives what the AI painted (for the fire guard), nil elsewhere")
def _():
    lua, env, w = world()
    put(lua, w, bedrooms(1))
    assert py(env.paint(T(lua, {"key": "p1", "audit": True}), False))["ok"] is False
    assert py(env.paint(T(lua, {"audit": True}), False))["ok"] is False
    env.paint(T(lua, {}), False)
    assert env.ai_value(50, 50, 100) == HIGH and env.ai_value(56, 49, 100) == LOW
    assert env.ai_value(5, 5, 100) is None


# --- 4. hooks and wiring ---------------------------------------------------------------------

THREATS = (LUA_DIR / "ai-threats.lua").read_text(encoding="utf-8")
PROJECTS = (LUA_DIR / "ai-builder-projects.lua").read_text(encoding="utf-8")
BRIDGE = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
SETTINGS = (LUA_DIR / "ai-overseer-settings.lua").read_text(encoding="utf-8")
GUI = (LUA_DIR / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
SRC = (LUA_DIR / "ai-traffic.lua").read_text(encoding="utf-8")


# (0.105.41 review) ai-threats' fire_guard run in a fake fort: a fire at
# (50, 50, 100), the tiles' traffic in TILES, ai-traffic's ai_value from AI
FIRE_FAKE = r"""
local src, TILES, AI = ...
local env = setmetatable({}, {__index = _G})
local site = {}
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {global = {cur_year = 200, cur_year_tick = 1000, world = {jobs = {list = {}}},
                    flows = {{density = 50, type = 1, pos = {x = 50, y = 50, z = 100}}}},
          flow_type = {[1] = 'Fire'},
          tile_traffic = {Normal = 0, Low = 1, High = 2, Restricted = 3}}
env.dfhack = {maps = {getTileFlags = function(x, y, z)
                  local k = x .. ',' .. y .. ',' .. z
                  if not TILES[k] then TILES[k] = {traffic = 0} end
                  return TILES[k] end},
              job = {removeJob = function() return true end},
              persistent = {getSiteData = function(k, d) local v = site[k]; if v == nil then return d end return v end,
                            saveSiteData = function(k, v) site[k] = v end}}
env.reqscript = function(n)
    if n == 'ai-traffic' then
        return {ai_value = function(x, y, z, memo)
            memo.calls = (memo.calls or 0) + 1
            return AI[x .. ',' .. y .. ',' .. z] end}
    end
    error('reqscript ' .. tostring(n))
end
assert(load(src, 'ai-threats', 't', env))()
return env
"""


@test("hooks: the fire guard (run in a fake fort) restricts the AI's painted tiles too and lifts them back to what "
      "the AI painted; the player's own High kept; start_project keeps the corridor (links)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    tiles = lua.table_from({"51,50,100": lua.table_from({"traffic": HIGH}),     # the AI's High
                            "49,50,100": lua.table_from({"traffic": LOW}),      # the AI's Low
                            "50,51,100": lua.table_from({"traffic": HIGH})})    # the player's High
    ai = lua.table_from({"51,50,100": HIGH, "49,50,100": LOW, "50,51,100": LOW})   # the AI painted Low there once
    env = lua.execute(FIRE_FAKE, module_src("ai-threats.lua"), tiles, ai)
    r = py(env.fire_guard(1, 10, False, False))
    assert r["ok"] and r["fires"] == 1 and r["restricted"] == 8, r
    assert tiles["51,50,100"].traffic == RESTRICTED and tiles["49,50,100"].traffic == RESTRICTED
    assert tiles["50,51,100"].traffic == HIGH, "the player's own value kept"
    assert tiles["50,50,100"].traffic == RESTRICTED and tiles["51,51,100"].traffic == RESTRICTED
    lift = py(env.fire_guard(1, 10, True, False))
    assert lift["lifted"] == 8, lift
    assert tiles["51,50,100"].traffic == HIGH and tiles["49,50,100"].traffic == LOW
    assert tiles["50,50,100"].traffic == NORMAL and tiles["50,51,100"].traffic == HIGH
    assert code_has(PROJECTS, "links = extra_list(site.extra),")
    lua = LuaRuntime(unpack_returned_tuples=True)
    m = re.search(r"local function extra_list\(extra\).*?\nend\n", PROJECTS, re.S)
    f = lua.execute(m.group(0) + "\nreturn extra_list")
    out = py(f(T(lua, {3: {1: True, -1: True}, -2: {0: True}})))
    assert out == [{"x": -2, "y": 0}, {"x": 3, "y": -1}, {"x": 3, "y": 1}], out


@test("Lua: ai-traffic compiles (Lua 5.3), is a module, and names the traffic values, never numbers")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    assert lua.eval("function(s) local f, e = load(s, 'c', 't', {}); return e end")(SRC) is None
    assert "--@module = true" in SRC
    assert not re.search(r"traffic\s*=\s*\d", SRC)


@test("bridge: paint_traffic in ACTIONS and DRY_OK, the traffic section, ai-traffic among the modules; "
      "digest default; short words; camera quiet; config keys")
def _():
    assert code_has(BRIDGE, "paint_traffic = function(a)")
    assert re.search(r"'paint_traffic',\s+-- \(0\.105\.41\)", BRIDGE)
    assert code_has(BRIDGE, "traffic = function() return safe(function() return reqscript('ai-traffic').report() end) end,")
    assert "'ai-traffic'" in BRIDGE[BRIDGE.index("BRIDGE_MODULES = {"):]
    assert digest.SECTION_DEFAULTS["traffic"] == {}
    import overseer
    assert "paint_traffic" in overseer.SHORT_WORDS and "paint_traffic" in overseer.CAMERA_QUIET
    for k in ("traffic_slice_tiles", "traffic_budget_ms", "traffic_paint_cooldown_ticks",
              "traffic_audit_cooldown_ticks", "traffic_recheck_days", "traffic_priority", "traffic_priority_slow"):
        assert k in PLANNER_CONFIG, k
    assert PLANNER_CONFIG["traffic_slice_tiles"] <= 5000 and PLANNER_CONFIG["traffic_budget_ms"] <= 200


@test("settings: traffic on by default, kept off when set off, sent to the brain; a row on the Rules page clear of the others")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    S = lua.eval("""function(src)
      local env = setmetatable({dfhack_flags = {module = true}, dfhack = {getDFPath = function() return '.' end,
                                          isMapLoaded = function() return false end}},
                               {__index = _G})
      env.require = function(n) if n == 'json' then return {} end return require(n) end
      assert(load(src, 'settings', 't', env))()
      return env end""")(SETTINGS)
    assert S.defaults().traffic is True and S.for_ai(S.defaults()).traffic is True
    off = S.sanitize(lua.table_from({"traffic": False}))
    assert off.traffic is False and S.for_ai(off).traffic is False
    assert S.sanitize(lua.table_from({})).traffic is True
    assert player_rules({"settings": {"traffic": False}})["traffic"] is False
    assert player_rules({"settings": {}})["traffic"] is True
    assert code_has(GUI, "view_id = 'traffic',") and code_has(GUI, "p:set_field('traffic', v)")
    assert "self.subviews.traffic:setOption(" in GUI
    src = GUI[GUI.index("function RulesPage:init()"):GUI.index("MilitaryPage = defclass")]
    jrow, hrow, t = 8, 2, 14
    rows = []
    for m in re.finditer(r"frame = \{t = ([^,}]+), l = (\d+)(?:, w = (\d+))?\}", src):
        expr = m.group(1).strip()
        for i in ((1, 2, 3) if " + i" in expr else (0,)):
            rows.append((eval(expr, {"jrow": jrow, "hrow": hrow, "t": t, "i": i}), int(m.group(2)),
                         int(m.group(3) or 60), m.start()))
    mine = src.index("view_id = 'traffic',")
    me = [r for r in rows if r[3] > mine][:2]          # the switch and its help line
    assert me[0][0] == 9 and me[1][0] == 10, me
    for r, l, wd, pos in rows:
        for mr, ml, mw, mpos in me:
            if pos != mpos and r == mr:
                assert l + wd <= ml or ml + mw <= l, (r, l, wd, mr, ml, mw)


# --- 5. the brain ----------------------------------------------------------------------------

def state(**traffic):
    t = {"enabled": True, "pending": [], "pending_total": 0, "painted": 0, "hands_off": 0, "tiles": 0}
    t.update(traffic)
    return {"traffic": t, "settings": {}}


def props(s):
    out = []
    PT._traffic_rule(s, PLANNER_CONFIG, out)
    return out


@test("rule: a level waiting -> paint_traffic, a slice (the config's tiles and ms), low priority; sooner while slow")
def _():
    s = state(pending=[{"key": "p4", "kind": "bedrooms"}, {"key": "p5", "kind": "farms"}], pending_total=3)
    p = props(s)
    assert len(p) == 1 and p[0].rule == "traffic_paint", p
    assert p[0].action == {"type": "paint_traffic", "max": PLANNER_CONFIG["traffic_slice_tiles"],
                           "budget_ms": PLANNER_CONFIG["traffic_budget_ms"]}, p[0].action
    assert "bedrooms" in p[0].reason and "2 more" in p[0].reason
    assert p[0].priority == PLANNER_CONFIG["traffic_priority"]
    s["fps_low"] = 12
    assert props(s)[0].priority == PLANNER_CONFIG["traffic_priority_slow"]
    # one in progress, nothing else waiting
    assert props(state(cursor={"key": "p4", "at": 300}))[0].rule == "traffic_paint"


@test("rule: nothing when off (Rules or the bridge's word), halted, a threat on the map, or no section")
def _():
    s = state(pending=[{"key": "p4", "kind": "bedrooms"}], pending_total=1)
    s["settings"] = {"traffic": False}
    assert not props(s)
    assert not props(state(enabled=False, pending=[{"key": "p4"}], pending_total=1))
    s = state(pending=[{"key": "p4"}], pending_total=1)
    s["halted"] = True
    assert not props(s)
    s = state(pending=[{"key": "p4"}], pending_total=1)
    s["others_on_map"] = {"threats_that_can_reach_dwarves": 2}
    assert not props(s)
    s["others_on_map"] = {"threats": [{"great_danger": True, "can_reach_dwarves": False}]}   # a beast in the deep
    assert props(s)
    s["world"] = {"sieges": [{"active": True}]}
    assert not props(s)
    assert not props({"settings": {}}) and not props({"traffic": {"error": "x"}})
    assert PT.traffic_line({}) == ""


@test("rule: a recheck only when nothing waits and the oldest painted level is old enough")
def _():
    days = PLANNER_CONFIG["traffic_recheck_days"]
    assert not props(state(painted=2, audit_next={"key": "p1", "kind": "farms", "days": days - 1}))
    p = props(state(painted=2, audit_next={"key": "p1", "kind": "farms", "days": days}))
    assert p and p[0].rule == "traffic_audit" and p[0].action["key"] == "p1" and p[0].action["audit"] is True, p
    p = props(state(painted=2, pending=[{"key": "p9"}], pending_total=1,
                    audit_next={"key": "p1", "days": days + 50}))
    assert [x.rule for x in p] == ["traffic_paint"]


@test("plan(): the traffic rule runs with a traffic section (and not without one); the digest line")
def _():
    import copy
    import json
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    s = copy.deepcopy(base)
    s["traffic"] = state(pending=[{"key": "p4", "kind": "bedrooms"}], pending_total=1)["traffic"]
    rules = [p.rule for p in plan(s, Memory())[0]]
    assert "traffic_paint" in rules, rules
    rules = [p.rule for p in plan(copy.deepcopy(base), Memory())[0]]
    assert "traffic_paint" not in rules and "traffic_audit" not in rules
    line = PT.traffic_line(state(painted=3, tiles=900, pending_total=1, hands_off=1, cursor={"key": "p4"}))
    assert line.startswith("TRAFFIC painted 3 levels (900 tiles) | waiting 1 (one in progress) | yours 1"), line
    assert "TRAFFIC painted" in digest.traffic_line(state(painted=1))


if __name__ == "__main__":
    finish()
