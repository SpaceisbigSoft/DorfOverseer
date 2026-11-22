"""(Y1) The kitchen exclusions shared by every AI reason (W2), the bounded siege
workshop search (S3) and the cavern snap that keeps to the citizens' ground (S4).

  1. kitchen: one record (site data ai-overseer/kitchen-holds) per kitchen
     exclusion, naming every AI reason holding it (brewables, fat, seed:<plant>):
     added by the first reason, removed by the last, never the player's; it
     survives a reload (numbers read back as floats) and takes over the three
     old per-rule records.
  2. siege: shop_spot_anywhere looks at the AI's workshop levels first, then
     outward from the entrance and the fort's stair, a slice of tiles a call
     (taken up again next call, given up after SHOP_SCAN_MAX); never a hall's
     middle nor a room with a purpose (a zone, a stockpile, a farm plot, an AI
     level other than workshops).
  3. cavern_snap: only a cavern tile in the citizens' walk group, with no
     danger near; else refused.

    python tests/test_y1_kitchen_siege.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import bridge_part_src  # noqa: E402  (r6) the bridge parts split

LUA = ROOT / "lua"
HARNESS = re.search(r'HARNESS = r"""(.*?)"""',
                    (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8"), re.S).group(1)


# --- 1. the kitchen ------------------------------------------------------------------------

KITCHEN = r"""local env, H = ...
  local ex = {}       -- DF's kitchen exclusion list (Cook): one entry per key
  local log = {}
  local function k(t, s, mt, mi) return t .. ':' .. s .. ':' .. mt .. ':' .. mi end
  H.dfhack.kitchen = {
    addExclusion = function(j, t, s, mt, mi)
      if ex[k(t, s, mt, mi)] then return false end; ex[k(t, s, mt, mi)] = true
      table.insert(log, '+' .. k(t, s, mt, mi)); return true end,
    removeExclusion = function(j, t, s, mt, mi)
      if not ex[k(t, s, mt, mi)] then return false end; ex[k(t, s, mt, mi)] = nil
      table.insert(log, '-' .. k(t, s, mt, mi)); return true end}
  H.df.item_type = {PLANT = 53, SEEDS = 52, GLOB = 7}
  H.df.global.world.raws.plants = {all = {
      {id = 'MUSHROOM_HELMET_PLUMP', material = {{id = 'STRUCTURAL'}},
       material_defs = {type = {seed = 420}, idx = {seed = 21}}}}}
  H.dfhack.matinfo.find = function(p, m) return {type = 419, index = 21} end
  H.dfhack.run_command_silent = function(...) return '', 0 end
  env.plugin_enabled = function() return false end
  env.brewable_cook_keys = function() return {{t = 53, s = -1, mt = 419, mi = 21}} end
  return ex, log
"""
PLANT, SEED = "53:-1:419:21", "52:-1:420:21"


def kitchen():
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    H = lua.execute(HARNESS, (LUA / "ai-bridge.lua").read_text(encoding="utf-8"), str(LUA))
    env = H.module()
    ex, log = lua.execute(KITCHEN, env, H)
    return lua, H, env, ex, log


def held(ex):
    return sorted(k for k, v in ex.items() if v)


@test("1. seed reserve first, then the brewables ban and its lift: the plump helmet stays kept from the cooks; "
      "the seed lift then removes plant and seed (the last reason)")
def _():
    need_lua()
    lua, H, env, ex, log = kitchen()
    assert env.act_seed_reserve(lua.table_from({"ban": lua.table_from(["MUSHROOM_HELMET_PLUMP"])})).ok
    b = env.act_kitchen_brewables(lua.table_from({"ban": True}))
    assert b.ok and b.banned == 0 and b.held == 1, dict(b)       # already excluded: held, not added
    l = env.act_kitchen_brewables(lua.table_from({"ban": False}))
    assert l.ok and l.lifted == 0 and held(ex) == sorted([PLANT, SEED]), (dict(l), held(ex))
    s = env.act_seed_reserve(lua.table_from({"lift": lua.table_from(["MUSHROOM_HELMET_PLUMP"])}))
    assert s.ok and held(ex) == [], held(ex)
    assert list(H.persist["ai-overseer/kitchen-holds"].holds.keys()) == []


@test("1. the W2 order, then the seed lift while the brewables ban is back: the plant stays (brewables "
      "holds it), the seed goes")
def _():
    need_lua()
    lua, H, env, ex, log = kitchen()
    env.act_kitchen_brewables(lua.table_from({"ban": True}))
    env.act_seed_reserve(lua.table_from({"ban": lua.table_from(["MUSHROOM_HELMET_PLUMP"])}))
    env.act_kitchen_brewables(lua.table_from({"ban": False}))
    assert held(ex) == sorted([PLANT, SEED]), held(ex)
    env.act_kitchen_brewables(lua.table_from({"ban": True}))
    env.act_seed_reserve(lua.table_from({"lift": lua.table_from(["MUSHROOM_HELMET_PLUMP"])}))
    assert held(ex) == [PLANT], held(ex)
    env.act_kitchen_brewables(lua.table_from({"ban": False}))
    assert held(ex) == [], held(ex)
    reasons = H.persist["ai-overseer/kitchen-holds"].holds
    assert list(reasons.keys()) == []


@test("1. a player's own exclusion is never removed, whichever AI reasons held it and let go")
def _():
    need_lua()
    lua, H, env, ex, log = kitchen()
    ex[PLANT] = True                                  # the player's, before the AI asked
    env.act_kitchen_brewables(lua.table_from({"ban": True}))
    env.act_seed_reserve(lua.table_from({"ban": lua.table_from(["MUSHROOM_HELMET_PLUMP"])}))
    env.act_seed_reserve(lua.table_from({"lift": lua.table_from(["MUSHROOM_HELMET_PLUMP"])}))
    env.act_kitchen_brewables(lua.table_from({"ban": False}))
    assert held(ex) == [PLANT], held(ex)              # the seed (the AI's) went, the player's plant stays
    assert "-" + PLANT not in list(log.values())


@test("1. the record survives a reload: a new bridge reads it back (numbers as floats, as JSON gives them) "
      "and still lifts only when the last reason lets go")
def _():
    need_lua()
    lua, H, env, ex, log = kitchen()
    env.act_kitchen_brewables(lua.table_from({"ban": True}))
    env.act_seed_reserve(lua.table_from({"ban": lua.table_from(["MUSHROOM_HELMET_PLUMP"])}))
    # the save written and read again: every whole number back as a float
    lua.execute("""local H = ...
      local function floats(v)
        if type(v) == 'number' then return v + 0.0 end
        if type(v) ~= 'table' then return v end
        local o = {}
        for k, x in pairs(v) do o[k] = floats(x) end
        return o
      end
      for k, v in pairs(H.persist) do H.persist[k] = floats(v) end""", H)
    env2 = H.module()
    lua.execute("local env = ...; env.plugin_enabled = function() return false end; "
                "env.brewable_cook_keys = function() return {{t = 53, s = -1, mt = 419, mi = 21}} end", env2)
    env2.act_kitchen_brewables(lua.table_from({"ban": False}))
    assert held(ex) == sorted([PLANT, SEED]), held(ex)
    assert list(env2.seed_bans_held().values()) == ["MUSHROOM_HELMET_PLUMP"]
    env2.act_seed_reserve(lua.table_from({"lift": lua.table_from(["MUSHROOM_HELMET_PLUMP"])}))
    assert held(ex) == [], held(ex)


@test("1. the old per-rule records are taken over: the seed ban the old code recorded without its plant "
      "(already excluded by the brewables ban) holds the plant now; the old records are cleared")
def _():
    need_lua()
    lua, H, env, ex, log = kitchen()
    ex[PLANT], ex[SEED], ex["7:-1:5:0"] = True, True, True
    lua.execute("""local H = ...
      H.persist['ai-overseer/kitchen'] = {bans = {{t = 53, s = -1, mt = 419, mi = 21}}}
      H.persist['ai-overseer/kitchen-fat'] = {bans = {{t = 7, s = -1, mt = 5, mi = 0}}}
      H.persist['ai-overseer/kitchen-seeds'] = {bans = {MUSHROOM_HELMET_PLUMP = {{t = 52, s = -1, mt = 420, mi = 21}}}}
    """, H)
    d = env.act_kitchen_brewables(lua.table_from({"ban": False, "dry_run": True}))
    assert d.ok and d.held == 1 and H.persist["ai-overseer/kitchen-holds"] is None   # a dry run writes nothing
    l = env.act_kitchen_brewables(lua.table_from({"ban": False}))
    assert l.ok and l.lifted == 0 and held(ex) == sorted([PLANT, SEED, "7:-1:5:0"]), (dict(l), held(ex))
    assert len(H.persist["ai-overseer/kitchen"].bans) == 0 and len(H.persist["ai-overseer/kitchen-fat"].bans) == 0
    assert list(env.seed_bans_held().values()) == ["MUSHROOM_HELMET_PLUMP"]
    env.act_kitchen_fat(lua.table_from({"ban": False}))
    assert held(ex) == sorted([PLANT, SEED]), held(ex)
    env.act_seed_reserve(lua.table_from({"lift": lua.table_from(["MUSHROOM_HELMET_PLUMP"])}))
    assert held(ex) == [], held(ex)


@test("1. one helper touches DF's kitchen list; the bans and the seed reserve go through the shared record")
def _():
    src = bridge_part_src("ai-bridge-actions")
    assert src.count("dfhack.kitchen.addExclusion") == 1 and src.count("dfhack.kitchen.removeExclusion") == 1
    body = src[src.index("function act_seed_reserve(a)"):src.index("-- (0.99.7) Soldiers")]
    assert "kitchen_exclude" not in body and "kitchen_hold(" in body and "kitchen_release(" in body
    others = [p for p in LUA.glob("*.lua") if not p.name.startswith("ai-bridge-actions")   # (r6) the actions part and its split-off files
              and ("addExclusion" in p.read_text(encoding="utf-8") or "removeExclusion" in p.read_text(encoding="utf-8"))]
    assert not others, others


# --- 2. the siege workshop -----------------------------------------------------------------

SIEGE_GAME = r"""
local src = ...
local e = setmetatable({}, {__index = _G})
e.reqscript = function() return {} end
e.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
e.df = {global = {world = {buildings = {all = {}, other = {WORKSHOP_ANY = {}}}}}}
e.dfhack = {}
assert(load(src, 'ai-siege', 't', e))()
return e
"""


def siege():
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua, lua.execute(SIEGE_GAME, (LUA / "ai-siege.lua").read_text(encoding="utf-8"))


def gkey(x, y, z):
    return (z * 4096 + y) * 4096 + x


def fort(lua, rows, z=150):
    """'#' wall, '.' free floor (inside), 'o' a building, 'E' the gate's opening."""
    tiles, inside, e = {}, {}, None
    for y, row in enumerate(rows):
        for x, c in enumerate(row):
            if c == "#":
                tiles[(x, y)] = lua.table_from({"shape": "WALL", "walk": False})
            else:
                tiles[(x, y)] = lua.table_from({"shape": "FLOOR", "walk": True, "occupied": c == "o"})
                inside[gkey(x, y, z)] = True
                if c == "E":
                    e = {"x": x, "y": y, "z": z, "id": 1, "inside_list": lua.table_from([gkey(x, y, z)])}
    T = lambda x, y, zz: tiles.get((x, y)) if zz == z else None  # noqa: E731
    return lua.table_from(e), lua.table_from(inside), T


def ctx(lua, taken=(), rooms=()):
    box = lambda b: lua.table_from(dict(zip(("x1", "y1", "x2", "y2", "z"), b)))  # noqa: E731
    return lua.table_from({"taken": lua.table_from([box(b) for b in taken]),
                           "rooms": lua.table_from([box(b) for b in rooms]), "starts": lua.table_from([])})


def spot(v):
    return None if v is None else (v["x"], v["y"], v["z"])


# a hall 11x9 off the gate's corridor
HALL = ["###############",
        "#######E#######",
        "#######.#######",
        "##...........##",
        "##...........##",
        "##...........##",
        "##...........##",
        "##...........##",
        "##...........##",
        "##...........##",
        "##...........##",
        "##...........##",
        "###############"]


@test("2. a dining hall (a zone over it) is never a siege workshop's spot; an empty hall gets one against "
      "its wall, never its middle (the whole ring open)")
def _():
    need_lua()
    lua, S = siege()
    e, inside, T = fort(lua, HALL)
    assert S.shop_spot_anywhere(e, inside, T, ctx(lua, taken=[(2, 3, 12, 11, 150)])) is None
    e, inside, T = fort(lua, HALL)          # (a new inside map: a search afresh)
    sp = spot(S.shop_spot_anywhere(e, inside, T, ctx(lua)))
    assert sp is not None, sp
    x, y, _ = sp
    ring_open = all(HALL[y + dy][x + dx] != "#" for dx in range(-3, 4) for dy in (-3, 3)) and \
        all(HALL[y + dy][x + dx] != "#" for dy in range(-3, 4) for dx in (-3, 3))
    assert not ring_open, sp
    # the hall's middle alone (walls 3 away on no side): refused
    e, inside, T = fort(lua, HALL)
    assert S.shop_spot_anywhere(e, inside, T, ctx(lua, taken=[(2, 3, 12, 4, 150), (2, 10, 12, 11, 150),
                                                              (2, 3, 3, 11, 150), (11, 3, 12, 11, 150)])) is None


@test("2. a stockpile or an AI bedroom level over the floor: refused; the near-gate 7x7 test refuses a zone too")
def _():
    need_lua()
    lua, S = siege()
    e, inside, T = fort(lua, HALL)
    assert S.shop_spot_anywhere(e, inside, T, ctx(lua, taken=[(2, 3, 12, 11, 150)])) is None
    assert spot(S.shop_spot(e, inside, T, ctx(lua))) is not None
    assert S.shop_spot(e, inside, T, ctx(lua, taken=[(2, 3, 12, 11, 150)])) is None
    # shop_context: zones, stockpiles and farm plots, and the AI's levels by kind
    lua.execute("""local S = ...
      S.df.building_type = {Civzone = 1, Stockpile = 2, FarmPlot = 3, Workshop = 4}
      local function b(t, x1, y1, x2, y2, z) return {x1 = x1, y1 = y1, x2 = x2, y2 = y2, z = z,
          getType = function() return t end} end
      S.df.global.world.buildings.all = {b(1, 0, 0, 4, 4, 150), b(2, 10, 10, 12, 12, 150), b(3, 20, 20, 21, 21, 150),
                                         b(4, 30, 30, 32, 32, 150)}
      local list = {{kind = 'bedrooms', area = {x1 = 40, y1 = 40, x2 = 50, y2 = 50, z = 150}},
                    {kind = 'workshops', area = {x1 = 60, y1 = 60, x2 = 70, y2 = 70, z = 150}}}
      local B = {load_projects = function() return {list = list} end,
                 project_areas = function(p) return {p.area} end}
      local G = {fort_anchor_starts = function() return {{x = 5, y = 6, z = 150}} end}
      S.builder = function() return B end
      S.gates = function() return G end
    """, S)
    c = S.shop_context()
    taken = sorted((t.x1, t.y1) for t in c.taken.values())
    assert taken == [(0, 0), (10, 10), (20, 20), (40, 40)], taken
    assert [(r.x1, r.y1) for r in c.rooms.values()] == [(60, 60)]
    assert [(p.x, p.y) for p in c.starts.values()] == [(5, 6)]


# the gate's corridor into a hall (x 1-21, y 3-9); an AI workshop level's empty 5x5 room east of it,
# its door at x 22 y 7
def rooms_fort():
    rows = ["#" * 30, "#E" + "#" * 28, "#." + "#" * 28]
    for y in range(3, 10):
        room = "....." if 5 <= y <= 9 else "#####"
        rows.append("#" + "." * 21 + ("." if y == 7 else "#") + room + "##")
    rows += ["#" * 30, "#" * 30]
    return rows


@test("2. the AI's workshop levels are looked at first: their empty room is taken before a nearer hall spot")
def _():
    need_lua()
    lua, S = siege()
    e, inside, T = fort(lua, rooms_fort())
    near = spot(S.shop_spot_anywhere(e, inside, T, ctx(lua)))
    assert near is not None and near[0] < 22, near                 # without the levels: the hall, nearest
    e, inside, T = fort(lua, rooms_fort())
    sp = spot(S.shop_spot_anywhere(e, inside, T, ctx(lua, rooms=[(23, 5, 27, 9, 150)])))
    assert sp == (25, 7, 150), sp


@test("2. the search is bounded: one call looks at SHOP_SLICE_TILES at most (and stops at SHOP_SLICE_MS), "
      "the next takes it up, a spot past the first slice is found; nothing in SHOP_SCAN_MAX: 'none', kept")
def _():
    need_lua()
    lua, S = siege()
    # a 200x200 hall full of buildings (nothing fits), the gate at its corner; a T in Lua (fast)
    e, inside, T, setfree = lua.execute("""local S = ...
      local function gkey(x, y, z) return (z * 4096 + y) * 4096 + x end
      local N, z, free, walls = 200, 150, {}, nil
      local inside = {}
      for y = 1, N do for x = 1, N do inside[gkey(x, y, z)] = true end end
      local wall = {shape = 'WALL', walk = false}
      local busy = {shape = 'FLOOR', walk = true, occupied = true}
      local open = {shape = 'FLOOR', walk = true}
      local T = function(x, y, zz)
        if zz ~= z or x < 0 or y < 0 or x > N + 1 or y > N + 1 then return nil end
        if x == 0 or y == 0 or x == N + 1 or y == N + 1 then return wall end
        if free[x .. ',' .. y] then return open end
        if walls[x .. ',' .. y] then return wall end
        return busy
      end
      local e = {x = 1, y = 1, z = z, id = 7, inside_list = {}}
      walls = {}
      local function setfree(cx, cy)
        -- a room: its 5x5 free, its ring wall but the top row (open floor, its door)
        for dy = -3, 3 do for dx = -3, 3 do
          local k = (cx + dx) .. ',' .. (cy + dy)
          if dy == -3 or (math.abs(dx) <= 2 and math.abs(dy) <= 2) then free[k] = true else walls[k] = true end
        end end
      end
      return e, inside, T, setfree
    """, S)
    S.SHOP_SLICE_TILES, S.SHOP_SLICE_MS, S.SHOP_SCAN_MAX = 2000, 10000, 9000
    c = ctx(lua)
    assert S.shop_spot_anywhere(e, inside, T, c) is None and S.SHOP_LAST == "searching"
    for _ in range(3):
        assert S.shop_spot_anywhere(e, inside, T, c) is None and S.SHOP_LAST == "searching"
    assert S.shop_spot_anywhere(e, inside, T, c) is None and S.SHOP_LAST == "none"     # 9000 looked at in all
    assert S.shop_spot_anywhere(e, inside, T, c) is None and S.SHOP_LAST == "none"     # kept: no new search
    # a fresh inside map: a new search; a spot ~70 tiles off (past the first slice) is found on a later call
    e2 = lua.table_from({"x": 1, "y": 1, "z": 150, "id": 8, "inside_list": lua.table_from([])})
    setfree(60, 40)
    S.SHOP_SCAN_MAX = 100000
    calls, sp = 0, None
    while sp is None and calls < 40:
        calls += 1
        sp = spot(S.shop_spot_anywhere(e2, inside, T, c))
    assert sp is not None and calls > 1 and sp[2] == 150, (sp, calls)
    # the time budget: 0 ms stops a call within a few hundred tiles
    e3 = lua.table_from({"x": 1, "y": 1, "z": 150, "id": 9, "inside_list": lua.table_from([])})
    S.SHOP_SLICE_TILES, S.SHOP_SLICE_MS = 100000, -1
    assert S.shop_spot_anywhere(e3, inside, T, c) is None and S.SHOP_LAST == "searching"


@test("2. place_shop: a search not done yet is reported as such (not 'no free 5x5'), and taken up next time")
def _():
    need_lua()
    lua, S = siege()
    e, inside, T = fort(lua, HALL)
    S.shop_count = lambda: 0
    mods = {"ai-gates": lua.table_from({"GATES": lua.table_from({"entrances": lua.table_from([e]), "inside": inside}),
                                        "fort_anchor_starts": lambda: lua.table_from([])}),
            "ai-builder": lua.table_from({"qf_try": lambda *a: True})}
    S.reqscript = lambda n: mods.get(n)
    S.tile = T
    S.SHOP_RADIUS = 0               # nothing by the gate: the fort-wide search
    S.SHOP_SLICE_TILES = 3
    r = S.place_shop(1, True)
    assert r.ok is False and r.searching is True and "still looking" in r.error, dict(r)
    S.SHOP_SLICE_TILES = 15000
    r = S.place_shop(1, True)
    assert r.ok is True and r["at"] is not None, dict(r)


# --- 3. cavern_snap ------------------------------------------------------------------------

def provisions():
    src = (ROOT / "tests" / "test_provisions.py").read_text(encoding="utf-8")
    TP = type(sys)("tp_helpers")
    TP.__dict__["__file__"] = str(ROOT / "tests" / "test_provisions.py")
    exec(compile(src[:src.index("\n@test(")], "test_provisions_head", "exec"), TP.__dict__)
    cut = src.index("def cave_floor(")
    exec(compile(src[cut:src.index("\n@test(", cut)], "test_provisions_cave", "exec"), TP.__dict__)
    return TP


@test("3. cavern_farm off the cavern: the nearest cavern tile in another walk group (beyond the AI's cavern "
      "wall) is passed over; none the citizens reach: refused, saying so")
def _():
    need_lua()
    TP = provisions()
    lua, env, w = TP.world()
    TP.cave_floor(w, 20, 20, 25, 25)
    for x in range(20, 26):
        for y in range(20, 26):
            w.group[f"{x},{y},80"] = 2           # the cavern: walk group 2
    r = TP.py(env.cavern_farm(TP.T(lua, {"at": {"x": 18, "y": 20, "z": 80}, "tiles": 12}), True))
    assert r["rejected"] and "not where the citizens can walk" in r["error"] and not TP.py(w.qf), r
    w.cit_groups = lua.table_from({2: True})     # the citizens walk there too
    r = TP.py(env.cavern_farm(TP.T(lua, {"at": {"x": 18, "y": 20, "z": 80}, "tiles": 12}), True))
    assert r["ok"], r
    # nearer tiles cut off, farther ones the citizens' own: the farther one is taken
    w.cit_groups = None
    for y in range(20, 26):
        w.group[f"21,{y},80"] = 1
    x, y, z = env.cavern_snap(env.builder(), 18, 20, 80, None, lua.table_from([]))
    assert (x, y, z) == (21, 20, 80), (x, y, z)


@test("3. cavern_snap: a cavern tile with a danger within CAVERN_DANGER is passed over; nothing else near: "
      "refused (danger)")
def _():
    need_lua()
    TP = provisions()
    lua, env, w = TP.world()
    TP.cave_floor(w, 20, 20, 25, 25)
    B = env.builder()
    danger = lua.table_from([lua.table_from({"x": 20, "y": 60, "z": 80})])
    x, why = env.cavern_snap(B, 18, 20, 80, None, danger)[:2]
    assert x == 20, x                                  # 40 away: no danger
    danger = lua.table_from([lua.table_from({"x": 22, "y": 30, "z": 80})])
    r = env.cavern_snap(B, 18, 20, 80, None, danger)
    assert r[0] is None and r[1] == "danger", r
    r = env.cavern_snap(B, 18, 20, 80, lua.table_from({}), lua.table_from([]))
    assert r[0] is None and r[1] == "unreached", r


if __name__ == "__main__":
    finish()
