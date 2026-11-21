"""(X1) The thirst rule's way-opening made safe (lua/ai-thirst.lua open_way,
game_way_reader, plan_way, the report's cells; brain/planner_thirst.py;
lua/ai-gates-fortify.lua gate_keepout). The verifier's proofs are in
tests/test_v56_verify.py (V1, V2, V5, V8); these test the rest of each fix:

  V1  a dug tile is safe on all 8 neighbours and over and under it (water,
      magma, a cavern, the sky, an aquifer);
  V2  only plain AI walls (rooms, halls, a gate's inner line) come down, and
      none on the records of the cistern, the cavern seal, the wings; a wall
      beside water, a cavern or the sky stays;
  S1  the AI's locked doors held by the seal, a cell, a lure stay locked
      (open_way and probe);
  V5  every AI holding cell (killer, moon, the calm-down room) reads 'cell';
      open_way opens no way out of a cell, the jail or chains; probe lifts
      nobody out of one; the brain says so (the moon cell's dehydrated: Needs you);
  V8  the siege checks for every change (a dig too): the alarm up for an enemy
      in reach, a danger near any tile of the way; the flood check from the way's
      far end with the gates shut (the fort's own ungated way out allowed);
      the brain asks no way while the gates are shut;
  S8  the tiles a thirst way opened are kept out of the gate's walls.

    python tests/test_x1_thirst_way.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
import test_i2_thirst as I2  # noqa: E402  (its fake fort)
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import PLANNER_CONFIG  # noqa: E402
import planner_thirst as PT  # noqa: E402

T, py, dwarf, drink = I2.T, I2.py, I2.dwarf, I2.drink


def K(x, y, z):
    return (z * 4096 + y) * 4096 + x


def world():
    I2.need_lua()
    return I2.world()


# --- a 3-D fake level for game_way_reader --------------------------------------------------------

# tiles["x,y,z"] = {...}; missing: solid natural rock. ai-constructions' claim: W.claims["x,y,z"].
READER3 = r"""
local env, W, tiles = ...
local function info(x, y, z)
    if x < 0 or y < 0 or x > 60 or y > 60 then return nil end
    local t = tiles[x .. ',' .. y .. ',' .. z]
    local o = {shape = 'WALL', material = 'STONE', aquifer = false, liquid = false, feature = false,
               outside = false, warm = false, designated = false, dig = 'No', smoothed = false,
               subterranean = true}
    if t then for k, v in pairs(t) do o[k] = v end end
    return o
end
local B = {tile_info = info,
           natural_wall = function(t)
               if t.aquifer or t.liquid or t.feature or t.outside or t.warm then return false end
               return t.shape == 'WALL' and not t.designated and not t.built
           end}
W.claims = W.claims or {}
local C = {ai_regions = function() return {} end,
           ai_claim = function(R, x, y, z) return W.claims[x .. ',' .. y .. ',' .. z] end}
W.doors = W.doors or {}
env.df.building_type = {[5] = 'Door'}
env.dfhack.buildings = {findAtTile = function(p) return W.doors[p.x .. ',' .. p.y .. ',' .. p.z] end}
env.dfhack.constructions = {findAtTile = function(p)
    local t = tiles[p.x .. ',' .. p.y .. ',' .. p.z]
    return (t and t.built) and {} or nil
end}
W.mine = W.mine or {}
W.claimed = W.claimed or {}
local old = env.reqscript
env.reqscript = function(name)
    if name == 'ai-builder' then return B end
    if name == 'ai-constructions' then return C end
    if name == 'ai-gates' then
        return {GATES = {mine = W.mine, armed = W.armed, entrances = W.entrances}, stranded_citizens = function() return {list = {}} end}
    end
    if name == 'ai-threats' then
        local m = old(name)
        m.claimed_doors = function() return W.claimed end
        return m
    end
    return old(name)
end
"""


def reader3(tiles: dict, claims: dict | None = None):
    lua, env, w = world()
    w.claims = T(lua, claims or {})
    lt = lua.table_from({k: T(lua, v) for k, v in tiles.items()})
    lua.execute(READER3, env, w, lt)
    w.zgroup[100] = 0
    return lua, env, w


@test("V1 reader: rock with water over it, magma under it or an aquifer diagonal is never dug; plain rock is")
def _():
    lua, env, w = reader3({
        "10,10,101": {"shape": "FLOOR", "liquid": True, "depth": 4},        # water over x10 y10
        "20,10,99": {"shape": "FLOOR", "liquid": True, "magma": True},      # magma under x20 y10
        "31,11,100": {"aquifer": True},                                      # an aquifer diagonal to x30 y10
        "41,9,100": {"shape": "EMPTY", "outside": True},                    # the sky diagonal to x40 y10
    })
    R = env.game_way_reader(100)
    for x in (10, 20, 30, 40):
        t = py(R(x, 10))
        assert t["kind"] == "blocked", (x, t)
    assert py(R(50, 10)) == {"kind": "rock"}, py(R(50, 10))
    assert env.beside_unsafe is not None


@test("V2 reader: only plain room/hall/gate-line walls; the keep, wings, cistern, seal categories and a wall by water stay")
def _():
    tiles = {f"{x},10,100": {"built": True, "material": "CONSTRUCTION"} for x in (10, 20, 30, 40, 50, 55)}
    tiles["21,11,100"] = {"shape": "FLOOR", "feature": True}             # a cavern diagonal to the room wall x20
    claims = {"10,10,100": "room_walls", "20,10,100": "room_walls", "30,10,100": "keep",
              "40,10,100": "wings", "50,10,100": "halls", "55,10,100": "cistern"}
    lua, env, w = reader3(tiles, claims)
    R = env.game_way_reader(100)
    assert py(R(10, 10)) == {"kind": "wall", "cat": "room_walls"}, py(R(10, 10))
    assert py(R(50, 10)) == {"kind": "wall", "cat": "halls"}
    for x in (20, 30, 40, 55):
        assert py(R(x, 10))["kind"] == "blocked", (x, py(R(x, 10)))


@test("V2 reader: a 'halls' wall on the cistern's sealing record or a gate's wing record stays (by record, not category)")
def _():
    tiles = {f"{x},10,100": {"built": True, "material": "CONSTRUCTION"} for x in (10, 20, 30)}
    claims = {f"{x},10,100": "halls" for x in (10, 20, 30)}
    lua, env, w = reader3(tiles, claims)
    w.site["ai-overseer/cistern"] = T(lua, {"sealing": {"10,10,100": True}})
    w.site["ai-overseer/wings"] = T(lua, {"1": ["20,10,100"]})
    R = env.game_way_reader(100)
    assert py(R(10, 10))["kind"] == "blocked" and "cistern" in py(R(10, 10))["why"], py(R(10, 10))
    assert py(R(20, 10))["kind"] == "blocked" and "wing" in py(R(20, 10))["why"], py(R(20, 10))
    assert py(R(30, 10)) == {"kind": "wall", "cat": "halls"}


def door(lua, w, bid, x, y, z=100):
    b = T(lua, {"id": bid, "centerx": x, "centery": y, "z": z, "door_flags": {"forbidden": True}})
    lua.execute("local b = ...; b.getType = function() return 5 end", b)
    w.doors[f"{x},{y},{z}"] = b
    return b


@test("S1 reader and probe: the AI's locked door the seal/a cell holds stays locked; its other locked door is unlocked")
def _():
    lua, env, w = reader3({})
    w.mine = T(lua, {901: True, 902: True})
    w.claimed = T(lua, {901: True})
    b1, b2 = door(lua, w, 901, 10, 10), door(lua, w, 902, 12, 10)
    R = env.game_way_reader(100)
    assert py(R(10, 10))["kind"] == "blocked" and "holds" in py(R(10, 10))["why"], py(R(10, 10))
    assert py(R(12, 10))["kind"] == "door"
    # probe: both near a dwarf with drink in reach
    lua.execute("local env, a, b = ...; env.df.global.world.buildings.other.DOOR = {a, b}; "
                "env.df.global.world.buildings.other.HATCH = {}", env, b1, b2)
    lua.execute("""local env, W = ...
W.unlocked = {}
env.WAY_DO = {unlock = function(b) table.insert(W.unlocked, b.id) return true end}""", env, w)
    w.zgroup[100] = 1
    drink(lua, w, 11, 11, 100, stack_size=5)
    dwarf(lua, w, 1, 52000, pos={"x": 11, "y": 12, "z": 100})
    r = py(env.probe(1, False))
    assert list(w.unlocked.values()) == [902], (py(w.unlocked), r["findings"])
    assert any("x10 y10" in f and "stays locked" in f for f in r["findings"]), r["findings"]


# --- V5: the AI's holding cells ----------------------------------------------------------------------

def burrow(lua, w, bid, name):
    w.burrows[len(w.burrows) + 1] = T(lua, {"id": bid, "name": name, "tiles": {}})


@test("V5 report: a dwarf in a killer cell's burrow or the calm-down room is 'cell' (its kind), not 'burrow'/'no_path'")
def _():
    lua, env, w = world()
    w.zgroup[100] = 0
    w.gmap["20,10,100"] = 1
    drink(lua, w, 20, 10, 100, stack_size=30)
    burrow(lua, w, 31, "AI killer cell 3")
    burrow(lua, w, 32, "AI calm 2")
    for uid, bid, y in ((3, 31, 10), (4, 32, 12)):
        w.gmap[f"10,{y},100"] = 2
        dwarf(lua, w, uid, 52000, pos={"x": 10, "y": y, "z": 100}, burrows=[bid])
    _, by = I2.rows(env)
    assert by[3]["reason"] == "cell" and by[3]["cell"] == "killer", by[3]
    assert by[4]["reason"] == "cell" and by[4]["cell"] == "calm", by[4]


@test("V5 report: the moon cell read from ai-threats' load_state (the game's name), released cells not counted")
def _():
    lua, env, w = world()
    lua.execute(r"""
local env = ...
local old = env.reqscript
env.reqscript = function(name)
    local m = old(name)
    if name == 'ai-threats' then
        m.load_state = function() return {cells = {['5'] = {zone = 77, doors = {901}, tick = 0}}} end
    end
    return m
end
""", env)
    w.zgroup[100] = 0
    w.gmap["20,10,100"] = 1
    drink(lua, w, 20, 10, 100, stack_size=30)
    for uid, y in ((5, 10), (6, 12)):
        w.gmap[f"10,{y},100"] = 2
        dwarf(lua, w, uid, 30000, pos={"x": 10, "y": y, "z": 100})
    _, by = I2.rows(env)
    assert by[5]["reason"] == "cell" and by[5]["cell"] == "moon", by[5]
    assert by[6]["reason"] == "no_path", by[6]


@test("V5 open_way: no way out of the jail, chains or a cell's burrow, whatever the reason read")
def _():
    lua, env, w = world()
    lua.execute(r"""
local env, W = ...
env.WAY_READER = function(z)
    return function(x, y)
        if x < 0 or x > 40 or y < 0 or y > 20 then return nil end
        if y == 10 and x <= 9 then return {kind = 'walk', group = 2} end
        if y == 10 and x >= 11 then return {kind = 'walk', group = 1} end
        return {kind = 'rock'}
    end
end
W.dug = {}
env.WAY_DO = {dig = function(x, y) table.insert(W.dug, x) return true end, remove = function() return true end,
              unlock = function() return true end}
""", env, w)
    w.zgroup[100] = 0
    w.gmap["20,10,100"] = 1
    drink(lua, w, 20, 10, 100, stack_size=30)
    burrow(lua, w, 40, "AI moon cell 7")
    cases = {7: {"burrows": [40]}, 8: {"flags1": {"chained": True}}, 9: {}}
    w.punish[1] = T(lua, {"criminal": 9, "prison_counter": 500})
    for uid, kw in cases.items():
        w.gmap[f"5,10,100"] = 2
        dwarf(lua, w, uid, 52000, pos={"x": 5, "y": 10, "z": 100}, **kw)
        r = py(env.open_way(uid, False))
        assert r["rejected"] and r.get("held"), (uid, r)
    assert not list(w.dug.values())


@test("V5 probe: a dwarf in the AI's moon cell burrow is not taken out of it (an AI burrow with no drink otherwise is)")
def _():
    lua, env, w = world()
    lua.execute(r"""
local env, W = ...
env.dfhack.burrows.setAssignedUnit = function(b, u, on) W.assigned = (W.assigned or 0) + 1 end
""", env, w)
    w.zgroup[100] = 1
    drink(lua, w, 12, 10, 100, stack_size=5)
    burrow(lua, w, 41, "AI moon cell 3")
    dwarf(lua, w, 1, 52000, pos={"x": 10, "y": 10, "z": 100}, burrows=[41])
    r = py(env.probe(1, False))
    assert not w.assigned and r["acted"] == 0, r
    assert any("left alone" in f for f in r["findings"]), r["findings"]


def remedy(row, s=None):
    ex = PT._existing([])
    ex["shared"] = set()
    return PT._remedy(row, s or {}, dict(PLANNER_CONFIG), ex, {"results": {}, "acted": {}}, {"n": {}}, 1000)


@test("V5 brain: 'cell' asks nothing; the moon cell's dehydrated werebeast is the player's (Needs you), no way dug")
def _():
    act, words, needs = remedy({"id": 5, "reason": "cell", "cell": "moon", "timer": 30000, "name": "Urist"})
    assert act is None and needs is None and "moon cell" in words, words
    act, words, needs = remedy({"id": 5, "reason": "cell", "cell": "moon", "timer": 52000, "name": "Urist"})
    assert act is None and needs and "moon cell" in needs, needs
    act, words, needs = remedy({"id": 6, "reason": "cell", "cell": "calm", "timer": 30000})
    assert act is None and "calm-down" in words


# --- V8: the siege, the danger on any tile, the flood check -----------------------------------------

# A map for the reader: '#' rock, '.' the dwarf's side (group 2), ',' the drink's side (group 1),
# 'o' under the sky (group 1, outside), 'O' the fort's own ungated way out (outside, way_out),
# 'G' a gate piece (walkable, group 1, gate); off the rows: off the map.
MAP_READER = r"""
local env, W, rows = ...
env.WAY_READER = function(z)
    return function(x, y)
        local row = rows[y + 1]
        if not row or x < 0 or x >= #row then return nil end
        local ch = row:sub(x + 1, x + 1)
        if ch == '#' then return {kind = 'rock'} end
        if ch == '.' then return {kind = 'walk', group = 2} end
        if ch == ',' then return {kind = 'walk', group = 1} end
        if ch == 'o' then return {kind = 'walk', group = 1, outside = true} end
        if ch == 'O' then return {kind = 'walk', group = 1, outside = true, way_out = true} end
        if ch == 'G' then return {kind = 'walk', group = 1, gate = true} end
        return {kind = 'blocked', why = 'x'}
    end
end
W.dug = {}
env.WAY_DO = {dig = function(x, y) table.insert(W.dug, x .. ',' .. y) return true end,
              remove = function() return true end, unlock = function() return true end}
"""


def map_fort(rows, drink_at=(8, 3)):
    lua, env, w = world()
    lua.execute(MAP_READER, env, w, T(lua, rows))
    w.zgroup[100] = 0
    dx, dy = drink_at
    w.gmap[f"{dx},{dy},100"] = 1
    drink(lua, w, dx, dy, 100, stack_size=40)
    w.gmap["2,3,100"] = 2
    dwarf(lua, w, 1, 45000, pos={"x": 2, "y": 3, "z": 100})
    return lua, env, w


BYPASS = ["###############",
          "###############",
          "###############",
          "#....#,,,,,,,o#",          # the drink's side runs out under the sky (no gate between)
          "###############",
          "###############"]


@test("V8 flood: a dig whose far end reaches the sky past no gate is refused; with a gate shut between, it is dug")
def _():
    lua, env, w = map_fort(BYPASS)
    r = py(env.open_way(1, False))
    assert r["rejected"] and "outside" in r["error"] and not list(w.dug.values()), r
    gated = list(BYPASS)
    gated[3] = "#....#,,,,,,Go#"
    lua, env, w = map_fort(gated)
    r = py(env.open_way(1, False))
    assert r["ok"] and r["dug"] == 1 and list(w.dug.values()) == ["5,3"], r


@test("V8 flood: the fort's own ungated way out (the fort is open there anyway) does not refuse the dig")
def _():
    rows = list(BYPASS)
    rows[3] = "#....#,,,,,,,O#"
    lua, env, w = map_fort(rows)
    r = py(env.open_way(1, False))
    assert r["ok"] and r["dug"] == 1, r


@test("V8 flood: a danger the far end's side reaches refuses the dig, even far (>15) from the way")
def _():
    rows = ["#" * 40, "#" * 40, "#" * 40, "#....#" + "," * 33 + "#", "#" * 40]
    lua, env, w = map_fort(rows)
    w.unit(T(lua, {"id": 99, "danger": True, "citizen": False, "pos": {"x": 37, "y": 3, "z": 100}}))
    r = py(env.open_way(1, False))
    assert r["rejected"] and "danger" in r["error"] and not list(w.dug.values()), r


@test("V8 the danger near ANY tile of the way: one by the walked corridor (not the dig) refuses the dig")
def _():
    # the corridor x1-24 (group 2), the rock x25, the drink's side x26-29 (group 1)
    rows = ["#" * 32] * 3 + ["#" + "." * 24 + "#,,,,#"] + ["#" * 32] * 6
    lua, env, w = map_fort(rows, drink_at=(27, 3))
    w.gmap["2,3,100"] = 0
    w.gmap["24,3,100"] = 2
    lua.execute("local W = ...; for _, u in ipairs(W.units) do if u.id == 1 then u.pos.x = 24 end end", w)
    # the dwarf at x24, beside the rock: the way is the dig alone
    r = py(env.open_way(1, True))
    assert r["ok"] and r["rock"] == 1, r
    # now the dwarf far up the corridor: the way walks x2-24 past a danger at x3 y8 (5 tiles off x3 y3)
    lua.execute("local W = ...; for _, u in ipairs(W.units) do if u.id == 1 then u.pos.x = 2 end end", w)
    w.gmap["24,3,100"] = 0
    w.gmap["2,3,100"] = 2
    w.unit(T(lua, {"id": 98, "danger": True, "citizen": False, "pos": {"x": 3, "y": 8, "z": 100}}))
    r = py(env.open_way(1, False))
    assert r["rejected"] and "danger is near" in r["error"] and not list(w.dug.values()), r


@test("V8 siege: the alarm up for an enemy in the citizens' walk group refuses a dig too; the gates shut, likewise")
def _():
    rows = list(BYPASS)
    rows[3] = "#....#,,,,,,Go#"
    lua, env, w = map_fort(rows)
    w.alert_idx = 1
    w.gmap["40,40,100"] = 1
    dwarf(lua, w, 2, 0, pos={"x": 9, "y": 3, "z": 100})                 # a citizen on the drink's side
    w.gmap["9,3,100"] = 1
    w.unit(T(lua, {"id": 97, "danger": True, "citizen": False, "pos": {"x": 40, "y": 40, "z": 100}}))
    r = py(env.open_way(1, False))
    assert r["rejected"] and "alarm" in r["error"] and not list(w.dug.values()), r
    w.alert_idx = 0
    w.armed = True
    r = py(env.open_way(1, False))
    assert r["rejected"] and "gates are shut" in r["error"], r
    w.armed = False
    r = py(env.open_way(1, False))
    assert r["ok"] and r["dug"] == 1, r


@test("V8 game flood (ai-gates explore): gates shut; past a gated entrance or no entrance: exposed; ungated: not")
def _():
    lua, env, w = world()
    lua.execute(r"""
local env, W = ...
local function nk(x, y, z) return (z * 4096 + y) * 4096 + x end
W.G = {MAX_TILES = 250000,
       GATES = {entrances = {
           {kind = 'surface', equipment = {{id = 1, x1 = 5, x2 = 5, y1 = 3, y2 = 3, z = 100}},
            outs = {[nk(14, 3, 100)] = true}, inside_list = {nk(13, 3, 100)}},
           {kind = 'surface', equipment = {}, outs = {[nk(14, 9, 100)] = true}, inside_list = {nk(13, 9, 100)}}}},
       explore = function(starts, shut)
           W.shut = shut
           local seen = {[nk(starts[1].x, starts[1].y, starts[1].z)] = true, [nk(13, 3, 100)] = true}
           return seen, 10, W.openings
       end}
local old = env.reqscript
env.reqscript = function(name) if name == 'ai-gates' then return W.G end return old(name) end
""", env, w)
    nk = K
    seed = T(lua, {"x": 8, "y": 3, "z": 100})
    none = T(lua, [])
    w.openings = T(lua, [{"inside": nk(13, 9, 100), "out": nk(14, 9, 100), "kind": "surface"}])
    assert env.game_exposure(seed, none, T(lua, {"ids": {}})) is None
    assert w.shut[nk(5, 3, 100)], "the gate's tile shut in the flood"
    w.openings = T(lua, [{"inside": nk(13, 3, 100), "out": nk(14, 3, 100), "kind": "surface"}])
    why = env.game_exposure(seed, none, T(lua, {"ids": {}}))
    assert why and "past the gates" in why, why
    w.openings = T(lua, [{"inside": nk(20, 20, 100), "out": nk(21, 20, 100), "kind": "cavern"}])
    why = env.game_exposure(seed, none, T(lua, {"ids": {}}))
    assert why and "cavern" in why, why
    w.openings = T(lua, [])
    why = env.game_exposure(seed, T(lua, [{"x": 13, "y": 3, "z": 100}]), T(lua, {"ids": {}}))
    assert why and "danger" in why, why


@test("V8 brain: no join_levels nor thirst_way while the gates are shut or the alarm is up for an enemy in reach")
def _():
    row = {"id": 1, "reason": "no_path", "timer": 45000, "name": "Urist", "x": 2, "y": 3, "z": 100}
    act, words, needs = remedy(row)
    assert act and act["type"] == "join_levels", act
    act, words, needs = remedy(row, {"entrances": {"armed": True}})
    assert act is None and "gates are shut" in words and needs is None, (act, words)
    act, words, needs = remedy(dict(row, timer=52000), {"civ_alert": True,
                                                         "others_on_map": {"threats_that_can_reach_dwarves": 2}})
    assert act is None and "alarm" in words and needs and "dehydrated" in needs, (act, needs)
    act, _, _ = remedy(row, {"civ_alert": True, "others_on_map": {"threats_that_can_reach_dwarves": 0}})
    assert act and act["type"] == "join_levels"


# --- S8: the gate's walls keep off a thirst way ------------------------------------------------------

@test("S8 gate_keepout: the tiles a thirst way opened (ai-overseer/thirst-ways) are kept out of the gate's walls")
def _():
    I2.need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, site = lua.execute(r"""
local src = ...
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-gates', 't', env))()
local site = {}
env.dfhack = {persistent = {getSiteData = function(k, d) local v = site[k]; if v == nil then return d end return v end}}
env.reqscript = (function(old) return function(n, ...)
    if n == 'ai-builder' or n == 'ai-floorplan' then error('no ' .. n) end
    return old(n, ...)
end end)(env.reqscript)
return env, site
""", module_src("ai-gates.lua"))
    site["ai-overseer/thirst-ways"] = T(lua, {"tiles": [{"x": 110, "y": 149, "z": 170, "kind": "wall", "tick": 5}]})
    ko = env.gate_keepout()
    assert ko[K(110, 149, 170)] and "thirsty" in ko[K(110, 149, 170)], py(ko)
    assert not ko[K(111, 149, 170)]


if __name__ == "__main__":
    finish()
