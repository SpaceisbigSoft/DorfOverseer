"""(0.105.45) Kill zones at the gates and cavern openings: lua/ai-killzone.lua
on a stub map (the 1-wide approach found, never the only way in shut
without a lever, no channel over water, a cavern or a level below, the
staged drawbridge, TRAPAVOID read), the bridge's wiring, the settings and
the brain (brain/planner_killzone.py).

    python tests/test_killzones.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
import planner_killzone as PKZ  # noqa: E402
from digest import normalize, SECTION_DEFAULTS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"

# A fake game: a tile map (W.tiles["x,y,z"] = tile), the gates module's
# pieces the zone uses, quickfort's dig marks, the site data.
FAKE = r"""
local src = ...
local W = {tiles = {}, site = {}, placed = {}, named = {}, dug = {}, now = {}, buildings = {},
           lever_spot = {x = 40, y = 40, z = 10}, levers_waiting = {}, entrances = {}}
local env = setmetatable({}, {__index = _G})
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {global = {cur_year = 300, cur_year_tick = 0, world = {units = {active = {}}, items = {other = {}},
                                                                 buildings = {other = {STOCKPILE = {}}}}},
          creature_raw = {find = function(r) return W.raws and W.raws[r] end}}
env.dfhack = {persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                            saveSiteData = function(k, v) W.site[k] = v end},
              units = {}, maps = {}}
local function k3(x, y, z) return x .. ',' .. y .. ',' .. z end
local function key(x, y, z) return (z * 4096 + y) * 4096 + x end
local function unkey(k) return k % 4096, (k // 4096) % 4096, k // (4096 * 4096) end
function W.T(x, y, z) return W.tiles[k3(x, y, z)] end
function W.moves(x, y, z, t, fn)
    for dx = -1, 1 do for dy = -1, 1 do if dx ~= 0 or dy ~= 0 then fn(x + dx, y + dy, z) end end end
end
function W.M(starts)
    return {T = W.T, moves = W.moves, key = key, unkey = unkey, starts = starts or W.starts or {},
            road = W.road or {}, floor = {FLOOR = true},
            dig_forbidden = function(x, y, z) return W.forbid and W.forbid[k3(x, y, z)] or nil end}
end
W.key = key
W.G = {
    GATES = {inside = {}, entrances = W.entrances, scanned = true},
    entrance = function(id) for _, e in ipairs(W.entrances) do if e.id == id then return e end end end,
    place = function(text, pos) table.insert(W.placed, {text = text, x = pos.x, y = pos.y, z = pos.z}); return true end,
    name_at = function(pos, name) table.insert(W.named, {name = name, x = pos.x, y = pos.y}) end,
    lever_spot = function() return W.lever_spot end,
    lever_waiting_for = function() return W.levers_waiting[1] end,
    unlinked_ai_levers = function() return W.levers_waiting end,
    fort_starts = function(s) return s end, citizen_starts = function() return W.starts or {} end,
    LEVER_NAME = 'AI gate lever',
    free_mechanism_count = function() return 5 end, free_levers = function() return {} end,
}
assert(load(src, 'ai-killzone', 't', env))()
env.gates = function() return W.G end
env.game_map = function(G, starts) return W.M(starts) end
env.builder = function() return {qf_try = function(mode, cells, z)
    table.insert(W.dug, {mode = mode, text = cells[1].text, x = cells[1].x, y = cells[1].y, z = z}); return true end} end
env.tile_now = function(x, y, z) return W.now[k3(x, y, z)] or W.T(x, y, z) end
env.building_info = function(x, y, z) return W.buildings[k3(x, y, z)] end
env.siege_mod = function() return {tile = W.T, survey = function() return {fortifications = 2, posts = 3} end} end
return env, W
"""

Z = 10


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-killzone.lua"))
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


def rock(**kw):
    t = {"walk": False, "shape": "WALL", "material": "STONE"}
    t.update(kw)
    return t


def floor(**kw):
    t = {"walk": True, "shape": "FLOOR", "material": "STONE"}
    t.update(kw)
    return t


def fort(lua, w, width=1, corridor=(5, 12), room=True, below=None, below2=None):
    """Solid rock everywhere (z-2..z), the outside west of x=5 at y 8-12, a
    corridor `width` tiles wide from x=corridor[0] to corridor[1] at y=10,
    a room x13-20 y5-15 east of it."""
    tiles = {}
    for z in (Z - 2, Z - 1, Z):
        for x in range(0, 26):
            for y in range(0, 20):
                tiles[f"{x},{y},{z}"] = rock()
    for x in range(0, 5):
        for y in range(8, 13):
            tiles[f"{x},{y},{Z}"] = floor(outside=True)
    half = width // 2
    for x in range(corridor[0], corridor[1] + 1):
        for y in range(10 - half, 10 - half + width):
            tiles[f"{x},{y},{Z}"] = floor()
    if room:
        for x in range(13, 21):
            for y in range(5, 16):
                tiles[f"{x},{y},{Z}"] = floor()
    for k, v in (below or {}).items():
        tiles[k] = v
    for k, v in (below2 or {}).items():
        tiles[k] = v
    for k, v in tiles.items():
        w.tiles[k] = T(lua, v)
    w.starts = T(lua, [{"x": 16, "y": 10, "z": Z}])
    return tiles


def entrance(lua, w, eid=1, kind="surface", x=5, y=10):
    e = T(lua, {"id": eid, "kind": kind, "x": x, "y": y, "z": Z, "inside_list": [w.key(x, y, Z)], "equipment": []})
    w.entrances[len(w.entrances) + 1] = e
    return e


# --- 1. the corridor planner ---------------------------------------------------------------

@test("corridor: the 1-wide approach is found: the bridge on its first straight tile, raising outward, traps behind")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w)
    e = entrance(lua, w)
    p = py(env.plan_corridor(e, w.M(), True))
    assert p["from"] == 2 and p["to"] == 7 and p["length"] == 6, p
    assert (p["bridge"]["x"], p["bridge"]["y"], p["bridge"]["dir"]) == (7, 10, "ga"), p["bridge"]
    assert [(t["x"], t["y"]) for t in p["tiles"]] == [(8, 10), (9, 10), (10, 10), (11, 10), (12, 10)], p["tiles"]
    # without the bridge: the traps from the stretch's start, at most 6
    p = py(env.plan_corridor(e, w.M(), False))
    assert [t["x"] for t in p["tiles"]] == [7, 8, 9, 10, 11, 12] and "bridge" not in p, p


@test("corridor: a 3-wide way in has no 1-wide stretch; a short one is too short; a dead end isn't a way in")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w, width=3)
    e = entrance(lua, w)
    p, why = env.plan_corridor(e, w.M(), True)
    assert p is None and "no 1-wide stretch" in why, why
    lua, env, w = world()
    fort(lua, w, corridor=(5, 8))
    for x in range(9, 13):                      # the room starts at x9 here
        for y in range(5, 16):
            w.tiles[f"{x},{y},{Z}"] = T(lua, floor())
    e = entrance(lua, w)
    p, why = env.plan_corridor(e, w.M(), False)
    assert p is None and "only 2 long" in why, why
    # a closet: the citizens are somewhere the corridor never leads
    lua, env, w = world()
    fort(lua, w, room=False)
    for y in range(9, 12):
        w.tiles[f"13,{y},{Z}"] = T(lua, floor())
    e = entrance(lua, w)
    w.starts = T(lua, [{"x": 30, "y": 30, "z": Z}])
    p, why = env.plan_corridor(e, w.M(), False)
    assert p is None and "dead end" in why, why


@test("corridor: no trap on the depot's wagon road, a building or water; stairs are walked over, not trapped")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w)
    w.tiles[f"8,10,{Z}"] = T(lua, floor(occupied=True))
    w.tiles[f"9,10,{Z}"] = T(lua, floor(liquid=True))
    w.tiles[f"10,10,{Z}"] = T(lua, floor(shape="STAIR_UPDOWN"))
    w.road = T(lua, {w.key(11, 10, Z): True})
    e = entrance(lua, w)
    p = py(env.plan_corridor(e, w.M(), False))
    assert [t["x"] for t in p["tiles"]] == [7, 12], p["tiles"]


# --- 2. the drop and the dwarf-safe rule ---------------------------------------------------

def drop(env, *a):
    r = env.drop_ok(*a)
    return r if isinstance(r, tuple) else (r, None)


@test("drop: natural rock below and under: yes; water, an aquifer, a cavern, a level below, the dig guard: no")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w)
    M = w.M()
    assert drop(env, 7, 10, Z, M) == (True, None)
    cases = [({f"7,10,{Z - 1}": rock(aquifer=True)}, "water below"),
             ({f"7,10,{Z - 1}": rock(feature=True)}, "cavern"),
             ({f"7,10,{Z - 1}": rock(material="CONSTRUCTION")}, "not natural rock"),
             ({f"7,10,{Z - 2}": floor()}, "two levels down"),
             ({f"7,10,{Z - 2}": rock(feature=True, walk=True, shape="FLOOR")}, "two levels down"),
             ({f"8,11,{Z - 1}": rock(liquid=True)}, "water or magma beside"),
             ({f"6,10,{Z - 1}": floor()}, "open tile beside the pit"),
             ({f"6,9,{Z - 1}": rock(feature=True)}, "cavern beside"),
             ({f"7,10,{Z}": floor(aquifer=True)}, "aquifer")]
    for change, words in cases:
        lua, env, w = world()
        fort(lua, w, below=change)
        ok, why = drop(env, 7, 10, Z, w.M())
        assert ok is False and words in why, (change, why)
    lua, env, w = world()
    fort(lua, w)
    w.forbid = T(lua, {f"7,10,{Z - 1}": "next to magma"})
    ok, why = drop(env, 7, 10, Z, w.M())
    assert ok is False and "dig guard" in why and "magma" in why, why


@test("bypass: the only surface way in gets no channel and a lever; another way in or a cavern opening may")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    only = T(lua, {"id": 1, "kind": "surface"})
    b = py(env.bypass(only, T(lua, [{"id": 1, "kind": "surface"}, {"id": 2, "kind": "cavern"}])))
    assert b["channel"] is False and b["lever_needed"] is True and "only way in" in b["why"], b
    b = py(env.bypass(only, T(lua, [{"id": 1, "kind": "surface"}, {"id": 3, "kind": "surface"}])))
    assert b["channel"] is True and b["lever_needed"] is True, b
    b = py(env.bypass(T(lua, {"id": 2, "kind": "cavern"}), T(lua, [])))
    assert b["channel"] is True and b["lever_needed"] is False, b
    assert py(env.trap_kinds("mixed", 5)) == ["cage", "cage", "cage", "weapon", "weapon"]
    assert py(env.trap_kinds("weapon", 2)) == ["weapon", "weapon"]


# --- 3. build_killzone -------------------------------------------------------------------------

def placed(w):
    return [(p["text"], p["x"], p["y"]) for p in py(w.placed) or []]


@test("build: the only way in: traps and a flat drawbridge with its lever, no channel; the dry run places nothing")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w)
    entrance(lua, w)
    r = py(env.build_killzone(1, 3, "cage", True, True))
    assert r["ok"] and r["dry_run"] and r["traps"] == 3 and r["drawbridge"]["channel"] is False, r
    assert placed(w) == [] and not py(w.dug) and not py(w.site), (placed(w), py(w.site))
    r = py(env.build_killzone(1, 3, "cage", True, False))
    assert r["ok"] and r["traps"] == 3 and "only way in" in r["channel_why"], r
    assert placed(w) == [("Tc", 8, 10), ("Tc", 9, 10), ("Tc", 10, 10), ("ga(1x1)", 7, 10), ("Tl", 40, 40)], placed(w)
    assert {n["name"] for n in py(w.named)} == {"AI killzone bridge", "AI gate lever"}
    assert not py(w.dug), py(w.dug)                     # no channel cuts the citizens' only way
    rec = py(w.site)["ai-overseer/killzones"]["5,10,10"]
    assert rec["stage"] == "done" and rec["bridge"]["channel"] is False and len(rec["traps"]) == 3, rec
    r = py(env.build_killzone(1, 3, "cage", True, False))
    assert r["rejected"] and "stands there already" in r["error"], r


@test("build: the only way in with no floor for a lever: no drawbridge at all, the traps still go in")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w)
    entrance(lua, w)
    w.lever_spot = None
    r = py(env.build_killzone(1, 2, "weapon", True, False))
    assert r["ok"] and "no free floor for its lever" in r["bridge_note"] and "drawbridge" not in r, r
    assert placed(w) == [("Tw", 7, 10), ("Tw", 8, 10)], placed(w)      # the bridge's tile trapped instead


@test("build: another way in and rock below: channel -> ramp removed -> bridge over the drop, a step a call")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w)
    entrance(lua, w)
    entrance(lua, w, eid=2, x=5, y=3)                   # a second surface way in (not on this map's walk)
    r = py(env.build_killzone(1, 2, "mixed", True, False))
    assert r["ok"] and r["drawbridge"]["channel"] is True and r["drawbridge"]["stage"] == "channel", r
    assert placed(w) == [("Tc", 8, 10), ("Tw", 9, 10)], placed(w)       # no bridge yet: the channel first
    assert [(d["text"], d["x"], d["z"]) for d in py(w.dug)] == [("h", 7, Z)]
    # not dug yet: waiting
    w.now[f"7,10,{Z}"] = T(lua, floor(designated=True))
    r = py(env.build_killzone(1, 2, "mixed", True, False))
    assert r["ok"] is False and r["waiting"] and "not dug yet" in r["error"], r
    # dug: the ramp below marked for removal
    w.now[f"7,10,{Z}"] = T(lua, {"walk": False, "shape": "RAMP_TOP"})
    w.now[f"7,10,{Z - 1}"] = T(lua, {"walk": True, "shape": "RAMP"})
    r = py(env.build_killzone(1, 2, "mixed", True, False))
    assert r["ok"] and r["stage"] == "ramp", r
    assert [(d["text"], d["z"]) for d in py(w.dug)][-1] == ("z", Z - 1)
    r = py(env.build_killzone(1, 2, "mixed", True, False))
    assert r["ok"] is False and "ramp in the channel is not removed" in r["error"], r
    # the pit's floor: the bridge over it and its lever
    w.now[f"7,10,{Z - 1}"] = T(lua, floor())
    r = py(env.build_killzone(1, 2, "mixed", True, True))
    assert r["ok"] and r["dry_run"] and len(placed(w)) == 2, (r, placed(w))
    r = py(env.build_killzone(1, 2, "mixed", True, False))
    assert r["ok"] and r["stage"] == "done", r
    assert placed(w)[-2:] == [("ga(1x1)", 7, 10), ("Tl", 40, 40)], placed(w)


@test("build: water under the bridge (an aquifer): no channel, the bridge flat with its lever")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w, below={f"7,10,{Z - 1}": rock(aquifer=True)})
    entrance(lua, w)
    entrance(lua, w, eid=2, x=5, y=3)
    r = py(env.build_killzone(1, 2, "cage", True, False))
    assert r["ok"] and "water below" in r["channel_why"] and r["drawbridge"]["channel"] is False, r
    assert not py(w.dug) and ("ga(1x1)", 7, 10) in placed(w), placed(w)


@test("build: a cavern opening may take a channel; an AI lever already waiting works the bridge (none placed)")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w)
    entrance(lua, w, kind="cavern")
    w.levers_waiting = T(lua, [{"id": 9, "x": 40, "y": 40, "z": Z}])
    r = py(env.build_killzone(1, 0, "cage", True, False))
    assert r["ok"] and r["traps"] == 0 and r["drawbridge"]["channel"] is True, r
    for step in ({f"7,10,{Z}": {"walk": False, "shape": "RAMP_TOP"}, f"7,10,{Z - 1}": {"walk": True, "shape": "RAMP"}},
                 {f"7,10,{Z - 1}": floor()}):
        for k, v in step.items():
            w.now[k] = T(lua, v)
        r = py(env.build_killzone(1, 0, "cage", True, False))
    assert r["stage"] == "done" and "works the bridge" in r["lever_note"] and ("Tl", 40, 40) not in placed(w), r


@test("build: refused: no such entrance, a gatehouse there, nothing asked, a bad kind")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w)
    e = entrance(lua, w)
    assert py(env.build_killzone(7, 2, "cage", False, False))["rejected"]
    assert "nothing to build" in py(env.build_killzone(1, 0, "cage", False, False))["error"]
    assert py(env.build_killzone(1, 2, "lava", False, False))["rejected"]
    e.gatehouse = "standing"
    assert "gatehouse" in py(env.build_killzone(1, 2, "cage", False, False))["error"]


# --- 4. the report, cages, TRAPAVOID ---------------------------------------------------------

@test("report: a possible zone (its stretch, the drawbridge's drop), and the AI's zone with built and full cages")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w)
    entrance(lua, w)
    entrance(lua, w, eid=2, x=5, y=3)                   # another way in (rock here: no stretch found)
    w.G.free_levers = lua.eval("function() return {{id = 1}} end")
    r = py(env.report())
    rows = {e["id"]: e for e in r["entrances"]}
    assert rows[1]["state"] == "possible" and rows[1]["corridor"] == 6 and rows[1]["fortifications"] == 2, rows[1]
    assert rows[1]["drawbridge"]["possible"] is True and rows[1]["drawbridge"]["channel"] is True, rows[1]
    assert rows[2]["state"] == "none" and "1-wide" in rows[2]["why"], rows[2]
    assert r["free_mechanisms"] == 5 and r["free_levers"] == 1, r
    env.build_killzone(1, 2, "cage", False, False)
    w.buildings[f"7,10,{Z}"] = T(lua, {"kind": "cage", "built": True, "full": True, "id": 50})
    w.buildings[f"8,10,{Z}"] = T(lua, {"kind": "cage", "built": False, "id": 51})
    rows = {e["id"]: e for e in py(env.report())["entrances"]}
    assert rows[1]["state"] == "building" and rows[1]["traps"]["planned"] == 2, rows[1]
    assert rows[1]["traps"]["built"] == 1 and rows[1]["traps"]["full"] == 1, rows[1]["traps"]
    w.buildings[f"8,10,{Z}"] = T(lua, {"kind": "cage", "built": True, "id": 51})
    assert {e["id"]: e for e in py(env.report())["entrances"]}[1]["state"] == "standing"
    r = py(env.reset_cage_traps(1, False))
    assert r["ok"] is False and r["waiting"] and r["full"] == 1 and "animal stockpile" in r["error"], r
    assert "itself" in r["note"]
    assert py(env.reset_cage_traps(2, False))["rejected"]


@test("TRAPAVOID: read from the unit's caste flags, else the caste raws; nil when neither reads")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    u = T(lua, {"enemy": {"caste_flags": {"TRAPAVOID": True}}, "race": 1, "caste": 0})
    assert env.trap_avoid(u) is True
    w.raws = T(lua, {5: {"caste": {0: {"flags": {"TRAPAVOID": False}}}}})
    lua.execute("local w = ...; w.raws[5].caste = setmetatable({}, {__index = function(_, i) "
                "if i == 0 then return {flags = {TRAPAVOID = false}} end end})", w)
    u2 = T(lua, {"race": 5, "caste": 0})
    assert env.trap_avoid(u2) is False
    assert env.trap_avoid(T(lua, {"race": 99, "caste": 0})) is None


# --- 5. the bridge's wiring and the settings --------------------------------------------------

@test("bridge: the killzones section (safe, cached a day), both actions (checked, on DRY_OK), the module listed")
def _():
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "killzones = function() return safe(function() return reqscript('ai-killzone').report(txt) end) end," in src
    actions = src[src.index("ACTIONS = {"):src.index("DRY_OK = {}")]
    assert "build_killzone = function(a)" in actions and "reset_cage_traps = function(a)" in actions
    dry = src[src.index("DRY_OK = {}"):src.index("}) do DRY_OK[name] = true end")]
    assert "'build_killzone', 'reset_cage_traps'" in dry
    mods = src[src.index("BRIDGE_MODULES = {"):src.index("}", src.index("BRIDGE_MODULES = {"))]
    assert "'ai-killzone'" in mods
    assert "SECTION_CACHE_DAYS.killzones = 1" in src and "CACHE_INVALIDATES.build_killzone" in src
    assert SECTION_DEFAULTS["killzones"] == {}
    import overseer
    assert "build_killzone" in overseer.SHORT_WORDS and "reset_cage_traps" in overseer.SHORT_WORDS
    orders = (LUA_DIR / "ai-bridge-orders.lua").read_text(encoding="utf-8")
    assert "ORDER_RECIPES.metal_trap_blades = {job = 'MakeTrapComponent'" in orders
    if LuaRuntime is None:
        return
    i = src.index("    build_killzone = function(a)")
    j = src.index("    reset_cage_traps = function(a)")
    fn = src[i:j].strip().rstrip(",").replace("build_killzone = function(a)", "return function(a)", 1)
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
        GOT = nil
        function reject(r) return {ok = false, rejected = true, error = r} end
        function int_in(v, lo, hi) v = math.tointeger(v); if v == nil or v < lo or v > hi then return nil end return v end
        function reqscript() return {build_killzone = function(id, n, kind, br, dry)
            GOT = {id = id, n = n, kind = kind, br = br, dry = dry}; return {ok = true} end} end
    """)
    f = lua.execute(fn)
    assert f(lua.table_from({}))["rejected"] is True
    assert f(lua.table_from({"entrance_id": 1, "traps": 9}))["rejected"] is True
    assert f(lua.table_from({"entrance_id": 1, "kind": "lava"}))["rejected"] is True
    assert f(lua.table_from({"entrance_id": 1, "drawbridge": "yes"}))["rejected"] is True
    assert f(lua.table_from({"entrance_id": 3, "traps": 0, "kind": "mixed", "drawbridge": True, "dry_run": True}))["ok"]
    g = lua.globals().GOT
    assert (g.id, g.n, g.kind, g.br, g.dry) == (3, 0, "mixed", True, True)
    f(lua.table_from({"entrance_id": 3}))
    g = lua.globals().GOT
    assert (g.n, g.kind, g.br, g.dry) == (4, "cage", False, False)


@test("Rules: killzones on by default (settings, the Army tab's switch in a free row), off only when said")
def _():
    from planner_core import player_rules
    st = (LUA_DIR / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    assert "killzones = true," in st and "'killzones'," in st and "killzones = s.killzones," in st
    assert player_rules({"settings": {}})["killzones"] is True
    assert player_rules({"settings": {"killzones": False}})["killzones"] is False
    gui = (LUA_DIR / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
    assert "view_id = 'killzones',\n        frame = {t = t + 18, l = 76, w = 40}," in gui
    assert "self.subviews.killzones:setOption(s.killzones ~= false, false)" in gui
    assert len("Kill zones at the gates:") <= 28 and 76 + 40 <= 118
    if LuaRuntime is None:
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    chk = lua.eval("function(src, n) local f, e = load(src, n, 't', {}); return f ~= nil, e end")
    for name in ("ai-killzone.lua", "ai-bridge.lua", "ai-overseer-settings.lua", "gui/ai-overseer.lua",
                 "ai-bridge-orders.lua"):
        ok = chk((LUA_DIR / name).read_text(encoding="utf-8"), name)
        assert ok[0], (name, ok)


# --- 6. the brain ------------------------------------------------------------------------------

def row(**kw):
    r = {"id": 1, "kind": "surface", "x": 50, "y": 50, "z": 120, "sealed": True, "state": "possible",
         "corridor": 5, "trap_tiles": 5, "drawbridge": {"possible": True, "channel": False, "why": "the only way in"}}
    r.update(kw)
    return r


def section(*rows, **kw):
    k = {"entrances": list(rows), "threats": [], "free_mechanisms": 20, "trap_weapons": 0, "mechanics": 2,
         "scanned": True}
    k.update(kw)
    return k


def state(kz=None, traits=None, threats=None, settings=None, **extra):
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    if kz is not None:
        base["killzones"] = kz
    base.setdefault("settings", {})["traits"] = traits or {}
    base["settings"].update(settings or {})
    if threats is not None:
        base.setdefault("others_on_map", {})["threats"] = threats
        base["others_on_map"]["threats_that_can_reach_dwarves"] = sum(1 for t in threats if t.get("can_reach_dwarves"))
    base.update(extra)
    return normalize(base)


def memory(used=None):
    m = Memory()
    m.atlas = {"entrances": used or {}}
    return m


def run(s, m=None):
    props, notes = [], []
    PKZ._killzone_rule(s, m or memory(), dict(PLANNER_CONFIG), props, notes)
    return props, notes


def builds(props):
    return [p.action for p in props if p.action.get("type") == "build_killzone"]


@test("brain: an entrance enemies used gets a cage zone with its drawbridge; one nobody used waits (lean 0)")
def _():
    s = state(section(row(), row(id=2, x=80, y=20)))
    p, n = run(s)
    assert builds(p) == [], p
    m = memory({"50,50,120": {"threats": 3, "deaths": 1}})
    p, n = run(s, m)
    assert builds(p) == [{"type": "build_killzone", "entrance_id": 1, "traps": 4, "kind": "cage",
                          "drawbridge": True}], p
    assert "enemies came this way 3 time(s), 1 died by it" in p[0].reason, p[0].reason
    # a record 2 tiles off (walls moved the entrance's first tile) still counts
    p, _ = run(s, memory({"52,49,120": {"threats": 2}}))
    assert [a["entrance_id"] for a in builds(p)] == [1]


@test("brain: the most dangerous first: the gate a siege comes toward over a used one; a cavern with a great beast")
def _():
    inv = [{"id": 70, "invader": True, "can_reach_dwarves": False, "layer": "surface", "pos": {"x": 82, "y": 22, "z": 140}}]
    s = state(section(row(), row(id=2, x=80, y=20)), threats=inv)
    p, _ = run(s, memory({"50,50,120": {"threats": 3}}))
    assert [a["entrance_id"] for a in builds(p)] == [2] and "siege is coming" in p[0].reason, p
    beast = [{"id": 71, "great_danger": True, "layer": "Cavern1", "can_reach_dwarves": False}]
    s = state(section(row(), row(id=3, kind="cavern", x=10, y=10, z=125)), threats=beast)
    p, _ = run(s)
    assert [a["entrance_id"] for a in builds(p)] == [3] and "great beast is in cavern1" in p[0].reason, p
    # below the slider (Fortification and Caution low) a beast's cavern is sealed, not trapped
    s = state(section(row(id=3, kind="cavern", x=10, y=10, z=125)), threats=beast,
              traits={"fortification": -80, "caution": -80})
    assert builds(run(s)[0]) == []


@test("brain: a closed fort (the Hermit hold) and Fortification 80+ want every entrance; 6 traps, mixed at 80+")
def _():
    s = state(section(row(trap_tiles=6), row(id=3, kind="cavern", x=10, y=10, z=125)),
              traits={"outsiders": -150, "caution": 60})
    p, _ = run(s)
    a = builds(p)
    assert [x["entrance_id"] for x in a] == [3] and "closed fort" in p[0].reason, p      # cavern openings first
    s = state(section(row(trap_tiles=6)), traits={"fortification": 90}, trap_weapons=0)
    s["killzones"]["trap_weapons"] = 5
    p, _ = run(s)
    assert builds(p)[0]["kind"] == "mixed" and builds(p)[0]["traps"] == 6, builds(p)
    s["killzones"]["trap_weapons"] = 0               # no blades and no metal or forge: all cages
    p, _ = run(s)
    assert builds(p)[0]["kind"] == "cage", builds(p)


@test("brain: a crisis, enemies in reach, too few citizens, the switch off: nothing built")
def _():
    m = memory({"50,50,120": {"threats": 3}})
    s = state(section(row()))
    m.crisis = {"why": "deaths"}
    assert builds(run(s, m)[0]) == []
    m = memory({"50,50,120": {"threats": 3}})
    s2 = state(section(row()), threats=[{"id": 5, "can_reach_dwarves": True}])
    assert builds(run(s2, m)[0]) == []
    s3 = state(section(row()), dwarves={"total": 5})
    assert builds(run(s3, m)[0]) == []
    s4 = state(section(row()), settings={"killzones": False})
    assert run(s4, m) == ([], [])
    assert run(state(), m) == ([], [])


@test("brain: no mechanic: the labour first; mechanisms short: ordered with the zone")
def _():
    m = memory({"50,50,120": {"threats": 3}})
    p, _ = run(state(section(row(), mechanics=0)), m)
    assert [x.action for x in p] == [{"type": "assign_labor", "job": "MECHANIC", "count": 1}], p
    p, _ = run(state(section(row(), free_mechanisms=2)), m)
    orders = [x.action for x in p if x.action.get("type") == "work_order"]
    assert orders == [{"type": "work_order", "recipe": "mechanisms", "amount": 5}] and builds(p), p


@test("brain: every enemy coming that way avoids traps (TRAPAVOID): the drawbridge alone, said so")
def _():
    m = memory({"50,50,120": {"threats": 3}})
    th = [{"id": 71, "name": "Ogra the titan", "trapavoid": True, "entrance_id": 1}]
    p, _ = run(state(section(row(), threats=th)), m)
    a = builds(p)[0]
    assert a["traps"] == 0 and a["drawbridge"] is True and "TRAPAVOID" in p[-1].reason, p[-1].reason
    th.append({"id": 72, "name": "a goblin", "trapavoid": False, "entrance_id": 1})
    p, _ = run(state(section(row(), threats=th)), m)
    assert builds(p)[0]["traps"] == 4 and "the traps are for the rest" in p[-1].reason
    # nothing to build at all: said
    p, n = run(state(section(row(drawbridge={"possible": False, "why": "no straight tile"}),
                             threats=th[:1])), m)
    assert builds(p) == [] and any("no spot for a drawbridge" in x for x in n), n


@test("brain: one zone at a time: one being built goes a step on when ready, else waits; a bridge unlinked is linked")
def _():
    m = memory({"50,50,120": {"threats": 3}, "80,20,120": {"threats": 5}})
    b = row(id=2, x=80, y=20, state="building", drawbridge={"stage": "channel", "step_ready": True, "x": 81, "y": 20})
    p, _ = run(state(section(row(), b)), m)
    assert builds(p) == [{"type": "build_killzone", "entrance_id": 2, "drawbridge": True}], p
    b["drawbridge"]["step_ready"] = None
    assert builds(run(state(section(row(), b)), m)[0]) == []
    done = row(id=2, x=80, y=20, state="standing", drawbridge={"built": True, "id": 300, "linked": False, "x": 81, "y": 20})
    s = state(section(done), entrances={"entrances": [], "free_levers": [{"id": 9, "x": 1, "y": 1, "z": 1}]})
    p, _ = run(s, m)
    assert [x.action for x in p] == [{"type": "link_lever", "lever_id": 9, "target_id": 300}], p


@test("brain: full cages are said (DF empties them itself); plan() carries the rule; the fixtures hold no section")
def _():
    m = memory({"50,50,120": {"threats": 3}})
    full = row(id=2, x=80, y=20, state="standing", traps={"planned": 3, "built": 3, "full": 2})
    _, n = run(state(section(full)), m)
    assert any("2 cage trap(s) in the kill zones hold a catch" in x for x in n), n
    props, _ = plan(state(section(row())), m)
    assert [x.action["entrance_id"] for x in props if x.action.get("type") == "build_killzone"] == [1]
    for path in [ROOT / "tests" / "fixtures" / "test_fort.json"] + sorted((ROOT / "tests" / "fixtures" / "real").glob("*.json")):
        assert "killzones" not in json.loads(path.read_text(encoding="utf-8")), path.name


if LuaRuntime is None:
    finish("these tests need the lupa package (pip install lupa)")
finish()
