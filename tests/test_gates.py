"""Tests for lua/ai-gates.lua (finding the fort's entrances and what closes
them) on a small fake map, in a real Lua engine (pip install lupa).

    python tests/test_gates.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = []

try:
    from lupa import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

HARNESS = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-gates', 't', env))()
local W = {}
-- W.map[z][y] = string of chars: '#' rock, '.' inside floor, 'o' outside floor,
-- 'c' cavern floor, '?' hidden
function env.tile(x, y, z)
  local lvl = W.map[z]; if not lvl then return nil end
  local row = lvl[y]; if not row then return nil end
  local ch = row:sub(x + 1, x + 1)
  if ch == '' then return nil end
  if ch == '#' then return {walk = false, shape = 'WALL'} end
  if ch == 'e' then return {walk = false, shape = 'EMPTY'} end      -- open space (a drop), inside
  if ch == 'R' then return {walk = true, shape = 'RAMP', feature = true} end   -- a ramp in the cavern
  -- 's' stairs, 'S' stairs in the cavern, 'w' water on the floor, 'b' a building
  -- on the floor (all inside)
  -- 'w' deep water (7/7) in a natural pool, 'v' shallow water (2/7)
  -- 't' the top of a stair shaft on the surface (outside); 'n' surface under a
  -- tree's crown (DF says not outside)
  if ch == 'B' then return {walk = true, shape = 'BRANCH', outside = true, material = 'TREE'} end   -- a treetop
  return {walk = true, shape = (ch == 's' or ch == 'S' or ch == 't') and 'STAIR_UPDOWN' or 'FLOOR',
          outside = ch == 'o' or ch == 'y' or ch == 't', canopy = ch == 'n', feature = ch == 'c' or ch == 'S',
          special = ch == 'p', hidden = ch == '?', liquid = ch == 'w' or ch == 'v', occupied = ch == 'b',
          depth = (ch == 'w' and 7) or (ch == 'v' and 2) or 0,
          material = (ch == 'w' or ch == 'v') and 'POOL' or 'STONE'}
end
function env.map_size() return 30, 19, 1 end
W.buildings = {}
function env.gate_buildings() return W.buildings end
W.at = {}
function env.building_at(x, y, z) return W.at[x .. ',' .. y .. ',' .. z] end
return env, W
"""

LUA = LuaRuntime(unpack_returned_tuples=True)
M, W = LUA.execute(HARNESS, (ROOT / "lua" / "ai-gates.lua").read_text(encoding="utf-8"))

# One level. Outside on the left (x 0-3), the fort on the right.
#   entrance A: 1-wide tunnel at y=2 with a door at x=8
#   entrance B: 2-wide tunnel at y=5-6, no door
#   entrance C: 6-wide opening at y=9-14, no door
#   cavern on the far right, reached through y=17
FORT = [
    "##############################",   # 0
    "##############################",   # 1
    "oooo..........................",   # 2  A
    "oooo#####.....................",   # 3
    "oooo#####.....................",   # 4
    "oooo..........................",   # 5  B
    "oooo..........................",   # 6  B
    "oooo#####.....................",   # 7
    "oooo#####.....................",   # 8
    "oooo..........................",   # 9  C
    "oooo..........................",   # 10
    "oooo..........................",   # 11
    "oooo..........................",   # 12
    "oooo..........................",   # 13
    "oooo..........................",   # 14
    "oooo#####.....................",   # 15
    "#############.################",   # 16
    "#############.........cccccccc",   # 17
    "##############################",   # 18
]


def setup(rows=FORT, buildings=()):
    level = LUA.table()
    for y, r in enumerate(rows):
        level[y] = r
    m = LUA.table()
    m[0] = level
    W.map = m
    bt = LUA.table()
    for i, b in enumerate(buildings, 1):
        bt[i] = LUA.table_from(b)
    W.buildings = bt


def find():
    starts = LUA.table_from({1: LUA.table_from({"x": 20, "y": 8, "z": 0})})
    entrances, _, n = M.find_entrances(starts, W.buildings)
    return [entrances[i] for i in range(1, len(entrances) + 1)], n


def by_kind_and_y(es):
    return {(e.kind, e.y): e for e in es}


def test(name):
    def wrap(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


DOOR_A = {"id": 1, "kind": "door", "x1": 8, "y1": 2, "x2": 8, "y2": 2, "z": 0, "name": ""}


@test("finds every opening: three to the surface, one to the cavern")
def _():
    setup(buildings=[DOOR_A])
    es, n = find()
    kinds = sorted((e.kind, e.width) for e in es)
    assert kinds == [("cavern", 1), ("surface", 1), ("surface", 2), ("surface", 6)], kinds
    assert n > 200


@test("an entrance with a door that seals it: that door, nothing else")
def _():
    setup(buildings=[DOOR_A, {"id": 2, "kind": "door", "x1": 20, "y1": 12, "x2": 20, "y2": 12, "z": 0}])
    es, _ = find()
    a = [e for e in es if e.kind == "surface" and e.width == 1][0]
    eq = [a.equipment[i].id for i in range(1, len(a.equipment) + 1)]
    assert a.sealed and eq == [1], eq


@test("a narrow open entrance gets door spots that would seal it; a wide one doesn't")
def _():
    setup(buildings=[DOOR_A])
    es, _ = find()
    b = [e for e in es if e.kind == "surface" and e.width == 2][0]
    c = [e for e in es if e.kind == "surface" and e.width == 6][0]
    assert not b.sealed and len(b.door_spots) == 2, len(b.door_spots)
    assert not c.sealed and len(c.door_spots) == 0


@test("a door off to the side (not in the tunnel) doesn't count as closing it")
def _():
    side = {"id": 3, "kind": "door", "x1": 12, "y1": 4, "x2": 12, "y2": 4, "z": 0}
    setup(buildings=[side])
    es, _ = find()
    a = [e for e in es if e.kind == "surface" and e.width == 1][0]
    assert not a.sealed and len(a.equipment) == 0 and len(a.door_spots) == 1


@test("a drawbridge counts only with a lever linked to it")
def _():
    bridge = {"id": 4, "kind": "bridge", "x1": 5, "y1": 5, "x2": 6, "y2": 6, "z": 0}
    setup(buildings=[DOOR_A, bridge])
    b = [e for e in find()[0] if e.width == 2 and e.kind == "surface"][0]
    assert not b.sealed
    lever_in = LUA.table_from({1: LUA.table_from({"id": 99, "x": 20, "y": 8, "z": 0})})
    setup(buildings=[DOOR_A, dict(bridge, lever_id=99, levers=lever_in)])
    b = [e for e in find()[0] if e.width == 2 and e.kind == "surface"][0]
    assert b.sealed and b.equipment[1].id == 4
    # 5a: a lever only outside the fort doesn't make it a gate (nobody should go out to pull it)
    lever_out = LUA.table_from({1: LUA.table_from({"id": 98, "x": 1, "y": 5, "z": 0})})
    setup(buildings=[DOOR_A, dict(bridge, lever_id=98, levers=lever_out)])
    b = [e for e in find()[0] if e.width == 2 and e.kind == "surface"][0]
    assert not b.sealed and list(b.bridges_unworked.values()) == [4]


@test("the watcher waits: closes when danger is at the door, or coming with nobody outside")
def _():
    assert M.should_close(5, 3)                  # at the door: close, even with 3 still out
    assert not M.should_close(30, 3)             # coming, but dwarves still outside: wait
    assert M.should_close(30, 0)                 # coming, everyone in: close
    assert not M.should_close(200, 0)            # far away: leave it open


@test("an open-air courtyard inside the walls is part of the fort, not an entrance")
def _():
    rows = list(FORT)
    rows[11] = "oooo#####.......yyyy.........."    # a roofless yard in the middle of the fort
    rows[12] = "oooo#####.......yyyy.........."
    rows[9] = "oooo#####....................."
    rows[10] = "oooo#####....................."
    rows[13] = "oooo#####....................."
    rows[14] = "oooo#####....................."
    setup(rows, buildings=[DOOR_A])
    es, _ = find()
    kinds = sorted((e.kind, e.width) for e in es)
    assert kinds == [("cavern", 1), ("surface", 1), ("surface", 2)], kinds


@test("a treetop beside the fort (0.104.104) is neither part of it nor an entrance")
def _():
    rows = list(FORT)
    rows[11] = "oooo#####.......BBBB.........."    # branches of a tree in a roofless gap, ringed by sky
    rows[12] = "oooo#####.......BBBB.........."
    rows[9] = "oooo#####....................."
    rows[10] = "oooo#####....................."
    rows[13] = "oooo#####....................."
    rows[14] = "oooo#####....................."
    setup(rows, buildings=[DOOR_A])
    es, n_tree = find()
    kinds = sorted((e.kind, e.width) for e in es)
    assert kinds == [("cavern", 1), ("surface", 1), ("surface", 2)], kinds
    rows[11] = rows[11].replace("BBBB", "####")
    rows[12] = rows[12].replace("BBBB", "####")
    setup(rows, buildings=[DOOR_A])
    _, n_rock = find()
    assert n_tree == n_rock, (n_tree, n_rock)                     # the treetop adds nothing to the fort


@test("a local feature (a deep pit) is neither walked into nor an entrance")
def _():
    rows = list(FORT)
    rows[17] = "#############.........pppppppp"
    setup(rows, buildings=[DOOR_A])
    es, _ = find()
    assert not [e for e in es if e.kind == "cavern"], [(e.kind, e.width) for e in es]


def keys_xy(t):
    out = []
    for i in range(1, len(t) + 1):
        k = t[i]
        out.append((k % 4096, (k // 4096) % 4096))
    return sorted(out)


def wide_c():
    setup(buildings=[DOOR_A])
    es, _ = find()
    t = LUA.table()
    for i, e in enumerate(es, 1):
        t[i] = e
    M.GATES = LUA.table_from({"entrances": t})
    return [e for e in es if e.kind == "surface" and e.width == 6][0]


STARTS = None


def starts():
    return LUA.table_from({1: LUA.table_from({"x": 20, "y": 8, "z": 0})})


@test("plain: walls across the 6-wide opening, a 2-tile gap in the middle with doors")
def _():
    c = wide_c()
    plan = M.plan_gate(c, "plain", starts())
    assert keys_xy(plan.doors) == [(4, 11), (4, 12)], keys_xy(plan.doors)
    assert keys_xy(plan.walls) == [(4, 9), (4, 10), (4, 13), (4, 14)], keys_xy(plan.walls)
    assert len(plan.inner) == 0 and len(plan.traps) == 0 and len(plan.statues) == 0


@test("the styles: narrow 1 door; fortified a second door behind; gatehouse adds cage traps; grand 2 doors and statues")
def _():
    c = wide_c()
    n = M.plan_gate(c, "narrow", starts())
    assert len(n.doors) == 1 and len(n.walls) == 5
    f = M.plan_gate(c, "fortified", starts())
    assert len(f.doors) == 1 and keys_xy(f.inner) == [(5, keys_xy(f.doors)[0][1])], keys_xy(f.inner)
    g = M.plan_gate(c, "gatehouse", starts())
    assert len(g.inner) == 1 and 1 <= len(g.traps) <= 3, len(g.traps)
    assert all(x >= 5 for x, _ in keys_xy(g.traps)), keys_xy(g.traps)
    r = M.plan_gate(c, "grand", starts())
    assert len(r.doors) == 2 and len(r.statues) == 2, (len(r.doors), len(r.statues))   # 3 can't: middle has no wall
    assert all(x == 5 for x, _ in keys_xy(r.statues)), keys_xy(r.statues)


@test("fortify places the walls now; doors wait for them (DF builds a door only beside a built wall)")
def _():
    c = wide_c()
    placed = []

    def hook(text, pos):
        if text == "Cw" and pos.y == 9:
            return False, "build_unsuitable"
        placed.append((text, pos.x, pos.y))
        return True
    M.place_hook = hook
    try:
        r = M.fortify(c.id, "plain", starts())
    finally:
        M.place_hook = None
    assert r.ok and r.walls == 3 and r.doors == 0 and r.doors_later == 2 and r.style == "plain", dict(r)
    assert "Cw:build_unsuitable" in r.failed and "d:" not in r.failed, r.failed
    assert ("Cw", 4, 10) in placed and not [p for p in placed if p[0] == "d"], placed


@test("walls that would cut the fort in two are refused, with why")
def _():
    # a corridor along the surface is the only way between the two halves
    rows = ["oooooooooooo"] + ["............"] + [".#####......"] * 9 + ["############"]
    level = LUA.table()
    for y, r in enumerate(rows):
        level[y] = r
    m = LUA.table()
    m[0] = level
    W.map = m
    W.buildings = LUA.table()
    s = LUA.table_from({1: LUA.table_from({"x": 0, "y": 8, "z": 0})})
    es, _, _ = M.find_entrances(s, W.buildings)
    e = [es[i] for i in range(1, len(es) + 1) if es[i].width == 12][0]
    plan, why = M.plan_gate(e, "narrow", s)
    assert plan is None and "cut off" in why, why


@test("an unknown entrance or style is refused")
def _():
    wide_c()
    assert M.fortify(99, "plain", starts()).rejected
    assert M.fortify(1, "castle", starts()).rejected


# --- found in the game: the AI's own planned walls, and tiles that can't take a door -----

def with_tile(rows, x, y, ch):
    rows = list(rows)
    rows[y] = rows[y][:x] + ch + rows[y][x + 1:]
    return rows


@test("game: walls or doors planned across an opening (not built yet) mean it's being closed: no new plan")
def _():
    pending = {"id": 9, "kind": "pending", "x1": 4, "y1": 5, "x2": 4, "y2": 6, "z": 0, "name": ""}
    setup(buildings=[DOOR_A, pending])
    b = by_kind_and_y(find()[0])[("surface", 5)]
    assert b.closing and not b.sealed and len(b.door_spots) == 0, (b.closing, b.sealed, len(b.door_spots))
    half = dict(pending, y2=5)                       # only half of it planned: still open
    setup(buildings=[DOOR_A, half])
    b = by_kind_and_y(find()[0])[("surface", 5)]
    assert not b.closing, "half a wall doesn't close it"


@test("game: door spots never go on stairs, water, or a tile that already has something on it")
def _():
    setup(buildings=[DOOR_A])
    assert len(by_kind_and_y(find()[0])[("surface", 5)].door_spots) == 2
    for ch in ("s", "w", "b"):
        setup(rows=with_tile(FORT, 4, 6, ch), buildings=[DOOR_A])
        es = find()[0]
        b = [e for e in es if e.kind == "surface" and e.y in (5, 6)][0]
        assert len(b.door_spots) == 0, (ch, len(b.door_spots))


@test("game: something in the opening (a building, water, stairs): the gate goes on the first clear line further in")
def _():
    for ch in ("b", "w", "s"):
        setup(rows=with_tile(FORT, 4, 11, ch), buildings=[DOOR_A])
        es = find()[0]
        c = [e for e in es if e.kind == "surface" and e.width >= 5][0]
        res = M.plan_gate(c, "plain", starts())
        plan = res[0] if isinstance(res, tuple) else res
        assert plan is not None and plan.moved_in == 1, (ch, res)
        xs = {x for x, _ in keys_xy(plan.walls) + keys_xy(plan.doors)}
        assert xs == {5}, (ch, keys_xy(plan.walls), keys_xy(plan.doors))
        assert "already in the opening" in plan.moved_why or "stair" in plan.moved_why, plan.moved_why


def pool_rows(ch="w"):
    rows = list(FORT)
    for x in range(4, 8):                                   # water over the opening and 3 lines behind it
        for y in range(9, 15):
            rows = with_tile(rows, x, y, ch)
    return rows


def pool_entrance(ch="w"):
    setup(rows=pool_rows(ch), buildings=[DOOR_A])
    W.at = LUA.table()
    return [e for e in find()[0] if e.kind == "surface" and e.width >= 5][0]


@test("water: the AI looks at it, and walls the pool's dry shore, leaving the water outside")
def _():
    c = pool_entrance()
    starts_ = starts()
    c.starts = starts_
    r = M.investigate_water(c)
    c.starts = None
    assert r.kind == "natural water" and r.tiles == 24 and r.deep == 24 and r.max_depth == 7, (r.kind, r.tiles)
    text = M.describe_water(r)
    assert "natural water, 24 tiles over 1 level(s), up to 7/7 deep" in text, text
    res = M.plan_gate(c, "plain", starts_)
    plan = res[0] if isinstance(res, tuple) else res
    assert plan is not None and plan.shore and "natural water" in plan.water, res
    xs = {x for x, _ in keys_xy(plan.walls) + keys_xy(plan.doors)}
    assert xs == {8}, (keys_xy(plan.walls), keys_xy(plan.doors))


@test("water: a well drawing from it, or dwarf-made works in it: never walled off; the reason says what it found")
def _():
    c = pool_entrance("v")                                  # shallow: walkers could cross
    W.at = LUA.table_from({"5,10,1": "Well"})
    res = M.plan_gate(c, "plain", starts())
    plan, why = res if isinstance(res, tuple) else (res, None)
    assert plan is None and "the AI looked" in why and "1 well(s) drawing from it" in why and "uses this water" in why, why
    W.at = LUA.table_from({"6,12,4": "ScrewPump"})            # a pump 4 levels up, over the water
    res = M.plan_gate(c, "plain", starts())
    plan, why = res if isinstance(res, tuple) else (res, None)
    assert plan is None and "screwpump" in why and "uses this water" in why, why


@test("water: deep water the shore can't be walled round is the gate itself (nothing built, nothing asked)")
def _():
    c = pool_entrance("w")
    saved = M.MAX_SHORE
    M.MAX_SHORE = 2
    try:
        res = M.plan_gate(c, "plain", starts())
        plan = res[0] if isinstance(res, tuple) else res
        assert plan is not None and plan.water_gate and "up to 7/7" in plan.water, res
        t = LUA.table()
        t[1] = c
        c.id = 1
        M.GATES = LUA.table_from({"entrances": t})
        M.doors_in = LUA.eval("function(list) return {} end")
        M.stockpiles_in = LUA.eval("function(list) return {} end")
        M.place_hook = lambda text, pos: True
        r = M.fortify(1, "plain", starts())
        assert r.ok and r.water_gate and r.walls == 0 and "natural water" in r.water, dict(r)
        # shallow water walkers could wade through: refused, with what the AI found
        c = pool_entrance("v")
        res = M.plan_gate(c, "plain", starts())
        plan, why = res if isinstance(res, tuple) else (res, None)
        assert plan is None and "up to 2/7" in why and "too long" in why, why
    finally:
        M.MAX_SHORE = saved
        M.place_hook = None


@test("game: half-closed (a door built or planned, its neighbour refused): only the missing door is added")
def _():
    for door in ({"id": 7, "kind": "door", "x1": 4, "y1": 5, "x2": 4, "y2": 5, "z": 0, "name": ""},
                 {"id": 7, "kind": "pending", "what": "door", "x1": 4, "y1": 5, "x2": 4, "y2": 5, "z": 0, "name": ""}):
        setup(rows=with_tile(FORT, 4, 5, "b"), buildings=[DOOR_A, door])   # the door's tile is taken
        b = [e for e in find()[0] if e.kind == "surface" and e.y in (5, 6)][0]
        spots = [(sp.x, sp.y) for sp in b.door_spots.values()]
        assert not b.closing and spots == [(4, 6)], (door["kind"], b.closing, spots)
    wall = {"id": 8, "kind": "pending", "what": "wall", "x1": 4, "y1": 5, "x2": 4, "y2": 5, "z": 0, "name": ""}
    setup(rows=with_tile(FORT, 4, 5, "b"), buildings=[DOOR_A, wall])     # a wall planned on one tile:
    b = [e for e in find()[0] if e.kind == "surface" and e.y in (5, 6)][0]   # a door on the other closes it
    assert [(sp.x, sp.y) for sp in b.door_spots.values()] == [(4, 6)], len(b.door_spots)


@test("game: door spots need a built wall beside them; walls still planned there mean wait")
def _():
    # one 3-wide opening (x4, y9-11) between rock: the middle tile has no wall beside it
    rows = ["#" * 30] * 2 + ["oooo" + ("." if 9 <= y <= 11 else "#") + "." * 25 for y in range(2, 16)] + ["#" * 30] * 3
    setup(rows=rows)
    b = find()[0][0]
    assert b.width == 3 and len(b.door_spots) == 0 and not b.closing, (b.width, len(b.door_spots), b.closing)
    # walls planned on its two outer tiles: the middle one gets its door once they're built
    walls = [{"id": 20 + i, "kind": "pending", "what": "wall", "x1": 4, "y1": y, "x2": 4, "y2": y, "z": 0, "name": ""}
             for i, y in enumerate((9, 11))]
    setup(rows=with_tile(with_tile(rows, 4, 9, "b"), 4, 11, "b"), buildings=walls)
    b = find()[0][0]
    assert b.closing and len(b.door_spots) == 0, (b.closing, len(b.door_spots))
    # once built (rock now), the middle tile takes the door
    setup(rows=with_tile(with_tile(rows, 4, 9, "#"), 4, 11, "#"))
    b = find()[0][0]
    assert [(sp.x, sp.y) for sp in b.door_spots.values()] == [(4, 10)], [(sp.x, sp.y) for sp in b.door_spots.values()]


@test("game: a stockpile in the opening is moved by the AI first, then the gate is walled")
def _():
    rows = with_tile(FORT, 4, 11, "b")                     # the stockpile's tile in the 6-wide opening
    setup(rows=rows, buildings=[DOOR_A])
    c = [e for e in find()[0] if e.kind == "surface" and e.width >= 5][0]
    M.GATES = LUA.table_from({"entrances": LUA.table_from({1: c})})
    c.id = 1
    calls = []
    LUA.globals().FAKE_PILE = LUA.table_from({"id": 77, "name": "Wood", "x1": 4, "y1": 11, "x2": 8, "y2": 11, "z": 0})
    M.stockpiles_in = LUA.eval("function(list) return {FAKE_PILE} end")

    def mover(pile, avoid):
        calls.append(pile.id)
        setup(rows=FORT, buildings=[DOOR_A])               # the opening's tile is free now
        return True, "moved to 6x2 at x10 y3"
    M.move_hook = mover
    M.place_hook = lambda text, pos: True
    try:
        r = M.fortify(1, "plain", LUA.table_from({1: LUA.table_from({"x": 20, "y": 8, "z": 0})}))
    finally:
        M.move_hook = None
        M.place_hook = None
    assert calls == [77] and r.ok and r.walls == 4 and "moved to" in r.stockpiles_moved, dict(r)

    def stuck(pile, avoid):
        return False, "no free floor inside the fort near it"
    setup(rows=rows, buildings=[DOOR_A])
    M.move_hook = stuck
    try:
        r = M.fortify(1, "plain", LUA.table_from({1: LUA.table_from({"x": 20, "y": 8, "z": 0})}))
    finally:
        M.move_hook = None
    assert not r.ok and "could not be moved" in r.error and "no free floor" in r.error, dict(r)


@test("game: where a moved stockpile goes: what's left of it clear of the opening, else free floor nearby")
def _():
    LUA.execute("""local M = ...
      M.dfhack = {buildings = {containsTile = function(p, x, y)
        return x >= p.x1 and x <= p.x2 and y >= p.y1 and y <= p.y2 end}}""", M)
    setup(rows=FORT, buildings=[DOOR_A])
    c = [e for e in find()[0] if e.kind == "surface" and e.width >= 5][0]
    avoid = LUA.table()
    for k in c.inside_list.values():
        avoid[k] = True
    for k in c.outs.keys():
        avoid[k] = True
    big = LUA.table_from({"id": 1, "x1": 4, "y1": 9, "x2": 14, "y2": 14, "z": 0})     # most of it is clear
    r = M.new_pile_spot(big, avoid)
    assert r.kept and r.x >= 7 and r.w * r.h >= 20, (r.kept, r.x, r.w, r.h)
    small = LUA.table_from({"id": 2, "x1": 4, "y1": 11, "x2": 6, "y2": 12, "z": 0})   # all of it is in the way
    r = M.new_pile_spot(small, avoid)
    assert not r.kept and r.x >= 7 and r.w * r.h >= 4, (r.kept, r.x, r.y, r.w, r.h)
    LUA.execute("local M = ...; M.dfhack = nil", M)


@test("game: a door already in the opening is kept as the gate; walls go on the rest")
def _():
    rows = with_tile(FORT, 4, 11, "b")                     # a built door's tile in the 6-wide opening
    setup(rows=rows, buildings=[DOOR_A])
    c = [e for e in find()[0] if e.kind == "surface" and e.width >= 5][0]
    k = [kk for kk in c.inside_list.values() if kk % 4096 == 4 and (kk // 4096) % 4096 == 11][0]
    present = LUA.table()
    present[k] = True
    res = M.plan_gate(c, "plain", starts(), present)
    plan = res[0] if isinstance(res, tuple) else res
    assert plan is not None and len(plan.doors) == 0 and plan.kept_doors == 1, res
    assert keys_xy(plan.walls) == [(4, 9), (4, 10), (4, 12), (4, 13), (4, 14)], keys_xy(plan.walls)
    M.GATES = LUA.table_from({"entrances": LUA.table_from({1: c})})
    c.id = 1
    M.doors_in = LUA.eval("function(list) return {[%d] = true} end" % k)
    M.stockpiles_in = LUA.eval("function(list) return {} end")
    M.place_hook = lambda text, pos: True
    try:
        r = M.fortify(1, "plain", starts())
    finally:
        M.place_hook = None
    assert r.ok and r.walls == 5 and r.kept_doors == 1, dict(r)


@test("game: when the only door has no wall to hang on, the reason says so (not 'nothing could be placed')")
def _():
    setup(buildings=[DOOR_A])
    b = by_kind_and_y(find()[0])[("surface", 5)]
    M.GATES = LUA.table_from({"entrances": LUA.table_from({1: b})})
    b.id = 1
    M.doors_in = LUA.eval("function(list) return {} end")
    M.stockpiles_in = LUA.eval("function(list) return {} end")
    saved = M.wall_beside
    M.wall_beside = LUA.eval("function() return false end")
    M.place_hook = lambda text, pos: True
    try:
        r = M.fortify(1, "plain", starts())
    finally:
        M.place_hook = None
        M.wall_beside = saved
    assert not r.ok and "wall beside it" in r.error and "?" not in r.error, dict(r)


@test("5a: a 1-wide opening with no wall beside its door gets a support wall across the way in")
def _():
    rows = ["#" * 30] * 2 + ["ooo" + "#" + "." * 26] * 16 + ["#" * 30]
    rows = with_tile(rows, 3, 10, "o")                     # the one way in
    rows = with_tile(with_tile(rows, 4, 9, "e"), 4, 11, "e")   # open space either side of the door tile
    for y in range(2, 18):
        if y != 10:
            rows = with_tile(rows, 3, y, "#")
    setup(rows=rows)
    es = find()[0]
    e = [x for x in es if x.width == 1][0]
    assert len(e.door_spots) == 0 and not e.closing, (len(e.door_spots), e.closing)
    plan = M.plan_gate(e, "plain", starts())
    plan = plan[0] if isinstance(plan, tuple) else plan
    assert plan is not None and keys_xy(plan.doors) == [(4, 10)], plan
    assert keys_xy(plan.support) in ([(4, 9)], [(4, 11)]), keys_xy(plan.support)
    t = LUA.table()
    t[1] = e
    e.id = 1
    M.GATES = LUA.table_from({"entrances": t})
    M.doors_in = LUA.eval("function(list) return {} end")
    M.stockpiles_in = LUA.eval("function(list) return {} end")
    placed = []
    M.place_hook = lambda text, pos: placed.append((text, pos.x, pos.y)) or True
    try:
        r = M.fortify(1, "plain", starts())
    finally:
        M.place_hook = None
    assert r.ok and r.support_walls == 1 and r.doors_later == 1 and "door follows" in r.note, dict(r)
    assert placed[0][0] == "Cw" and placed[0][1] == 4, placed
    # once the support is built (rock now), the scan offers the door
    setup(rows=with_tile(rows, 4, plan.support[1] // 4096 % 4096, "#"))
    e = [x for x in find()[0] if x.width == 1][0]
    assert [(sp.x, sp.y) for sp in e.door_spots.values()] == [(4, 10)]


@test("5a: stairs whose outside is straight below get a hatch on the stair")
def _():
    up = ["#" * 30] * 3 + ["##########s" + "." * 19] + ["#" * 10 + "." * 20] * 4 + ["#" * 30] * 11
    down = ["#" * 30] * 3 + ["cccccccccc" + "S" + "#" * 19] + ["#" * 30] * 15
    m = LUA.table()
    for z, rows in ((0, down), (1, up)):
        level = LUA.table()
        for y, r in enumerate(rows):
            level[y] = r
        m[z] = level
    W.map = m
    W.buildings = LUA.table()
    s1 = LUA.table_from({1: LUA.table_from({"x": 20, "y": 5, "z": 1})})
    es, _, _ = M.find_entrances(s1, W.buildings)
    e = [es[i] for i in range(1, len(es) + 1) if es[i].z == 1][0]
    assert (e.x, e.y, e.width) == (10, 3, 1), (e.x, e.y, e.width)
    plan = M.plan_gate(e, "plain", s1)
    plan = plan[0] if isinstance(plan, tuple) else plan
    assert plan is not None and len(plan.hatches) == 1 and len(plan.walls) == 0, plan
    k = plan.hatches[1]
    assert (k % 4096, k // 4096 % 4096, k // (4096 * 4096)) == (10, 3, 1)


@test("a new fort's shaft: the outside straight above the stairs gets a hatch on the shaft's top")
def _():
    surface = ["o" * 30] * 3 + ["oooooooooo" + "t" + "o" * 19] + ["o" * 30] * 15
    below = ["#" * 30] * 3 + ["##########s" + "." * 19] + ["#" * 10 + "." * 20] * 4 + ["#" * 30] * 11
    m = LUA.table()
    for z, rows in ((0, below), (1, surface)):
        level = LUA.table()
        for y, r in enumerate(rows):
            level[y] = r
        m[z] = level
    W.map = m
    W.buildings = LUA.table()
    s0 = LUA.table_from({1: LUA.table_from({"x": 20, "y": 5, "z": 0})})
    es, _, _ = M.find_entrances(s0, W.buildings)
    es = [es[i] for i in range(1, len(es) + 1)]
    assert len(es) == 1 and (es[0].x, es[0].y, es[0].z) == (10, 3, 0), [(e.x, e.y, e.z) for e in es]
    plan = M.plan_gate(es[0], "plain", s0)
    plan = plan[0] if isinstance(plan, tuple) else plan
    assert plan is not None and len(plan.hatches) == 1 and len(plan.walls) == 0, plan
    k = plan.hatches[1]
    assert (k % 4096, k // 4096 % 4096, k // (4096 * 4096)) == (10, 3, 1)      # on the top, on the surface
    # once built, the hatch is that entrance's gate (0.40 said it "stands open again")
    W.buildings = LUA.table_from({1: LUA.table_from({"id": 5, "kind": "hatch", "x1": 10, "y1": 3, "x2": 10,
                                                     "y2": 3, "z": 1, "name": ""})})
    es, _, _ = M.find_entrances(s0, W.buildings)
    e = es[1]
    assert e.sealed and e.equipment[1].id == 5, (e.sealed, len(e.equipment))


@test("trees: the ground under a tree's crown is the surface, not an entrance to wall in")
def _():
    rows = ["o" * 30] * 5 + ["oooooooonnnooooooooooooooooooo"] * 3 + ["o" * 30] * 11
    level = LUA.table()
    for y, r in enumerate(rows):
        level[y] = r
    m = LUA.table()
    m[0] = level
    W.map = m
    W.buildings = LUA.table()
    s = LUA.table_from({1: LUA.table_from({"x": 9, "y": 6, "z": 0})})      # a dwarf under the tree
    es, _, _ = M.find_entrances(s, W.buildings)
    assert len(es) == 0, [(es[i].x, es[i].y) for i in range(1, len(es) + 1)]


@test("5a: a bridge's levers: the one away from the gate (inside, 20+ tiles or 4+ levels) is the one pulled")
def _():
    e = LUA.table_from({"x": 10, "y": 10, "z": 5, "equipment": LUA.table_from({1: LUA.table_from({
        "id": 1, "kind": "bridge", "levers": LUA.table_from({
            1: LUA.table_from({"id": 11, "x": 12, "y": 10, "z": 5}),     # right by the gate
            2: LUA.table_from({"id": 12, "x": 40, "y": 10, "z": 5}),     # outside the fort
            3: LUA.table_from({"id": 13, "x": 12, "y": 12, "z": 12})})})})})   # inside, 7 levels up
    inside = LUA.table()
    for x, y, z in ((12, 10, 5), (12, 12, 12)):
        inside[(z * 4096 + y) * 4096 + x] = True
    M.pick_levers(LUA.table_from({1: e}), inside)
    b = e.equipment[1]
    assert b.lever_id == 13 and b.lever_away, (b.lever_id, b.lever_away)
    del_far = LUA.table_from({1: LUA.table_from({"x": 10, "y": 10, "z": 5, "equipment": LUA.table_from({1: LUA.table_from({
        "id": 1, "kind": "bridge", "levers": LUA.table_from({1: LUA.table_from({"id": 11, "x": 12, "y": 10, "z": 5})})})})})})
    M.pick_levers(del_far, inside)
    b = del_far[1].equipment[1]
    assert b.lever_id == 11 and not b.lever_away, (b.lever_id, b.lever_away)


LINK_STUB = r"""
local M = ...
local function ref(t, id) return {building_id = id, getType = function() return t end} end
M.df = {general_ref_type = {BUILDING_TRIGGER = 1, BUILDING_TRIGGERTARGET = 2, BUILDING_HOLDER = 3},
        trap_type = {Lever = 1}, global = {world = {buildings = {other = {TRAP = {
          {id = 50, trap_type = 1, centerx = 3, centery = 4, z = 9, name = 'AI Gate', linked_mechanisms = {}},
          {id = 51, trap_type = 1, centerx = 30, centery = 40, z = 2, name = '',
           linked_mechanisms = {{general_refs = {ref(3, 500), ref(1, 51)}}}},
          {id = 52, trap_type = 1, centerx = 31, centery = 40, z = 2, name = '',
           linked_mechanisms = {{general_refs = {ref(2, 600)}}}}}}}}}}
"""


@test("5a: lever links are read from the mechanisms (holder = the target), as DF 53.16 keeps them")
def _():
    LUA.execute(LINK_STUB, M)
    try:
        levers, pos = M.lever_links()
        assert list(levers[500].values()) == [51] and list(levers[600].values()) == [52], dict(levers)
        assert levers[50] is None and pos[50].name == "AI Gate" and pos[51].z == 2
    finally:
        LUA.execute("local M = ...; M.df = nil", M)


JOB_STUB = r"""
local M = ...
local calls = {}
local function jobs() return setmetatable({}, {__index = {insert = function(self, _, v) table.insert(self, v) end}}) end
local function bld(id, t, extra)
  local b = {id = id, centerx = 3, centery = 4, z = 9, jobs = jobs(), linked_mechanisms = {}, name = '',
             getType = function() return t end, getBuildStage = function() return 1 end,
             getMaxBuildStage = function() return 1 end}
  for k, v in pairs(extra or {}) do b[k] = v end
  return b
end
local lever = bld(50, 7, {trap_type = 1, name = 'AI Gate'})
local bridge = bld(500, 5)
local door = bld(501, 6, {getBuildStage = function() return 0 end})
local well = bld(502, 9)
local mechs = {{id = 1, flags = {}}, {id = 2, flags = {in_job = true}}, {id = 3, flags = {}}, {id = 4, flags = {}}}
M.df = {building_type = {[5] = 'Bridge', [6] = 'Door', [7] = 'Trap', [9] = 'Well', Bridge = 5, Door = 6, Trap = 7},
        trap_type = {Lever = 1}, job_type = {LinkBuildingToTrigger = 66},
        job_role_type = {LinkToTarget = 4, LinkToTrigger = 5},
        general_ref_type = {BUILDING_TRIGGER = 1, BUILDING_TRIGGERTARGET = 2, BUILDING_HOLDER = 3},
        building = {find = function(id) return ({[50] = lever, [500] = bridge, [501] = door, [502] = well})[id] end},
        job = {new = function() return {id = 777} end},
        global = {world = {buildings = {other = {TRAP = {lever}}}, items = {other = {TRAPPARTS = mechs}}}}}
M.dfhack = {items = {getHolderUnit = function() return nil end, getHolderBuilding = function() return nil end},
            job = {addGeneralRef = function(j, t, id) table.insert(calls, 'ref ' .. t .. ' ' .. id) end,
                   attachJobItem = function(j, it, role) table.insert(calls, 'item ' .. it.id .. ' ' .. role); return true end,
                   linkIntoWorld = function(j) table.insert(calls, 'link') end,
                   removeJob = function(j) table.insert(calls, 'remove') end}}
M.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
M.JOB_CALLS, M.JOB_LEVER, M.JOB_MECHS = calls, lever, mechs
"""


@test("5a: link_lever makes DF's link job on the lever with two free mechanisms; dry run and refusals change nothing")
def _():
    LUA.execute(JOB_STUB, M)
    try:
        r = M.link_lever(50, 500, True)
        assert r.ok and r.dry_run and r.mechanisms == 2 and len(M.JOB_CALLS) == 0, dict(r)
        assert M.link_lever(500, 50, False).rejected                       # not a lever
        assert M.link_lever(50, 502, False).rejected                       # a well can't be linked
        assert "not built" in M.link_lever(50, 501, False).error
        r = M.link_lever(50, 500, False)
        assert r.ok and r.job_id == 777 and r.target == "Bridge", dict(r)
        calls = list(M.JOB_CALLS.values())
        assert calls == ["ref 3 50", "ref 2 500", "item 1 4", "item 3 5", "link"], calls
        job = M.JOB_LEVER.jobs[1]
        assert job.job_type == 66 and job.pos.x == 3 and job.pos.z == 9
        r = M.link_lever(50, 500, False)                                   # the job is waiting: not twice
        assert r.rejected and "already waiting" in r.error, dict(r)
        LUA.execute("local M = ...; M.JOB_MECHS[1].flags.in_job = true; M.JOB_MECHS[3].flags.forbid = true; "
                    "M.JOB_LEVER.jobs[1] = nil", M)
        r = M.link_lever(50, 500, False)
        assert not r.ok and not r.rejected and "2 free mechanisms (1 free; 1 forbidden)" in r.error, dict(r)
        # (0.95.1) region2: the mechanisms sat in the Mechanic's workshop where they
        # were made: usable from there; one kept in a cabinet isn't
        LUA.execute("local M = ...; M.JOB_MECHS[1].flags.in_job = false; M.JOB_MECHS[3].flags.forbid = false; "
                    "M.df.building_type[10] = 'Workshop'; M.df.building_type[11] = 'Cabinet'; "
                    "M.dfhack.items.getHolderBuilding = function(it) if it.id == 1 then "
                    "return {getType = function() return 10 end} elseif it.id == 3 then "
                    "return {getType = function() return 11 end} end end", M)
        c = M.mechanism_counts()
        assert c.usable == 2 and c.reserved == 1 and c.why["held in a Cabinet"] == 1, (c.usable, c.reserved, dict(c.why))
        LUA.execute("local M = ...; M.dfhack.items.getHolderBuilding = function() return nil end", M)
        # 0.34.0 in the game: the role enum wasn't where the code looked, and the link
        # stopped with a Lua error. A DF without either name is refused cleanly now.
        LUA.execute("local M = ...; M.df.job_role_type = nil; M.JOB_MECHS[1].flags.in_job = false; "
                    "M.JOB_MECHS[3].flags.forbid = false", M)
        r = M.link_lever(50, 500, True)
        assert r.rejected and "no lever-link job" in r.error, dict(r)
        LUA.execute("local M = ...; M.df.job_item_ref = {T_role = {LinkToTarget = 4, LinkToTrigger = 5}}", M)
        assert M.link_lever(50, 500, True).ok                              # the older name still works
    finally:
        LUA.execute("local M = ...; M.df = nil; M.dfhack = nil; M.xyz2pos = nil", M)


@test("0.104.156: a link takes the mechanisms a dwarf can reach from the lever, nearest first; out of reach ones said")
def _():
    LUA.execute(JOB_STUB, M)
    try:
        # the lever at x3 y4 z9 (walk group 1); mechanism 1 far off in group 2, 3 near, 4 nearer
        LUA.execute("""local M = ...
            local at = {[1] = {x = 3, y = 4, z = 30}, [3] = {x = 20, y = 4, z = 9}, [4] = {x = 5, y = 4, z = 9}}
            M.dfhack.items.getPosition = function(it) local p = at[it.id]; return p.x, p.y, p.z end
            M.dfhack.maps = {getWalkableGroup = function(p) if p.z == 30 then return 2 end; return 1 end}""", M)
        r = M.link_lever(50, 500, False)
        assert r.ok and list(r.mechanism_ids.values()) == [4, 3], dict(r)
        calls = list(M.JOB_CALLS.values())
        assert calls[2:4] == ["item 4 4", "item 3 5"], calls
        LUA.execute("local M = ...; M.JOB_LEVER.jobs[1] = nil; M.JOB_MECHS[4].flags.in_job = true", M)
        r = M.link_lever(50, 500, False)
        assert not r.ok and "1 out of reach of the lever" in r.error and r.mechanisms == 1, dict(r)
        # the lever's own tile unread (group 0): no filter, as before
        LUA.execute("local M = ...; M.dfhack.maps.getWalkableGroup = function(p) "
                    "if p.x == 3 and p.y == 4 and p.z == 9 then return 0 end; return 1 end", M)
        lst, far = LUA.eval("function(M) local l, f = M.free_mechanisms(2, {x = 3, y = 4, z = 9}); return #l, f end")(M)
        assert lst == 2 and far == 0, (lst, far)
        # Teacheroar: loose ones on a tile no dwarf can walk to are not usable at all (nor counted free);
        # one in a workshop whose own tile is impassable is reached from beside it
        LUA.execute("""local M = ...
            M.JOB_MECHS[4].flags.in_job = false
            M.dfhack.maps.getWalkableGroup = function(p) if p.x == 5 and p.y == 4 then return 0 end; return 1 end""", M)
        assert M.mechanism_unusable(M.JOB_MECHS[4]) == "where no dwarf can walk"
        c = M.mechanism_counts()
        assert c.usable == 2 and c.why["where no dwarf can walk"] == 1 and c.unwalkable_at == "x5 y4 z9", dict(c)
        LUA.execute("""local M = ...; M.df.building_type[10] = 'Workshop'
            M.dfhack.items.getHolderBuilding = function(it) if it.id == 4 then return {getType = function() return 10 end} end end""", M)
        assert M.mechanism_unusable(M.JOB_MECHS[4]) is None
        r = M.link_lever(50, 500, True)
        assert r.ok and r.mechanisms == 2, dict(r)
    finally:
        LUA.execute("local M = ...; M.df = nil; M.dfhack = nil; M.xyz2pos = nil", M)


@test("5a review: a fortified gate's inner door never gets its support wall on the way through")
def _():
    c = wide_c()
    plan = M.plan_gate(c, "fortified", starts())
    plan = plan[0] if isinstance(plan, tuple) else plan
    door = keys_xy(plan.doors)[0]
    for x, y in keys_xy(plan.support):
        assert y != door[1], (keys_xy(plan.support), door)       # never in line with the door
    saved = M.wall_beside
    M.wall_beside = LUA.eval("function() return false end")
    try:
        plan = M.plan_gate(c, "fortified", starts())
        plan = plan[0] if isinstance(plan, tuple) else plan
    finally:
        M.wall_beside = saved
    inner = keys_xy(plan.inner)[0]
    assert all(y != inner[1] for _, y in keys_xy(plan.support)), (keys_xy(plan.support), inner)


@test("5a review: no hatch when the outside below is beside the stair (a ramp would walk onto the lid)")
def _():
    up = ["#" * 30] * 3 + ["##########s" + "." * 19] + ["#" * 10 + "." * 20] * 4 + ["#" * 30] * 11
    down = ["#" * 30] * 2 + ["#########cR" + "#" * 19] + ["cccccccccc" + "S" + "#" * 19] + ["#" * 30] * 15
    m = LUA.table()
    for z, rows in ((0, down), (1, up)):
        level = LUA.table()
        for y, r in enumerate(rows):
            level[y] = r
        m[z] = level
    W.map = m
    W.buildings = LUA.table()
    s1 = LUA.table_from({1: LUA.table_from({"x": 20, "y": 5, "z": 1})})
    es, _, _ = M.find_entrances(s1, W.buildings)
    e = [es[i] for i in range(1, len(es) + 1) if es[i].z == 1][0]
    res = M.plan_gate(e, "plain", s1)
    plan = res[0] if isinstance(res, tuple) else res
    assert plan is None or len(plan.hatches) == 0, plan


@test("5b: drawbridge style: walls and a raising bridge over the gap (raised toward the outside), and a lever where the dwarves are")
def _():
    c = wide_c()
    plan = M.plan_gate(c, "drawbridge", starts())
    plan = plan[0] if isinstance(plan, tuple) else plan
    assert plan is not None and plan.bridge and len(plan.doors) == 0, plan
    br = plan.bridge
    assert (br.x, br.w, br.h, br.dir) == (4, 1, 2, "ga") and br.y in (11, 10), (br.x, br.y, br.w, br.h, br.dir)
    assert len(plan.walls) == 4 and len(plan.support) == 0
    c.id = 1
    M.GATES = LUA.table_from({"entrances": LUA.table_from({1: c})})
    M.doors_in = LUA.eval("function(list) return {} end")
    M.stockpiles_in = LUA.eval("function(list) return {} end")
    placed, named = [], []
    M.place_hook = lambda text, pos: placed.append((text, pos.x, pos.y)) or True
    M.name_hook = lambda pos, name: named.append((pos.x, pos.y, name))
    try:
        r = M.fortify(1, "drawbridge", starts())
    finally:
        M.place_hook = None
        M.name_hook = None
    assert r.ok and r.bridge and r.lever and r.walls == 4 and r.doors == 0, dict(r)
    texts = [p[0] for p in placed]
    assert "ga(1x2)" in texts and "Tl" in texts, texts
    lever = [p for p in placed if p[0] == "Tl"][0]
    assert lever[1] >= 24 and named == [(lever[1], lever[2], "AI gate lever")], (lever, named)   # 20+ tiles away
    # no spot for a lever away from the gate: doors in the gap instead, never a bridge nobody can work
    saved = M.LEVER_AWAY
    M.LEVER_AWAY = 100
    placed.clear()
    M.place_hook = lambda text, pos: placed.append((text, pos.x, pos.y)) or True
    try:
        r = M.fortify(1, "drawbridge", starts())
    finally:
        M.place_hook = None
        M.LEVER_AWAY = saved
    assert r.ok and not r.bridge and r.style == "plain" and "doors instead" in r.bridge_note, dict(r)
    assert not [p for p in placed if p[0] in ("Tl", "ga(1x2)")], placed


@test("5b: traps go just inside a gate, never outside it or on the tile right behind the door")
def _():
    setup(buildings=[DOOR_A])
    es = find()[0]
    a = [e for e in es if e.kind == "surface" and e.y == 2][0]
    assert a.sealed
    a.id = 1
    M.GATES = LUA.table_from({"entrances": LUA.table_from({1: a})})
    placed = []
    M.place_hook = lambda text, pos: placed.append((text, pos.x, pos.y)) or True
    try:
        r = M.place_traps(1, "cage", 4, starts())
    finally:
        M.place_hook = None
    assert r.ok and r.traps == 4 and r.kind == "cage", dict(r)
    # the door is at x8 y2: all inside it (x9+), none on a tile touching it
    assert all(t == "Tc" and x >= 9 and max(abs(x - 8), abs(y - 2)) >= 2 for t, x, y in placed), placed
    # an entrance with no gate yet: refused; an unknown kind: refused
    b = [e for e in es if e.kind == "surface" and e.y in (5, 6)][0]
    b.id = 2
    M.GATES = LUA.table_from({"entrances": LUA.table_from({1: a, 2: b})})
    assert M.place_traps(2, "cage", 3, starts()).rejected
    assert M.place_traps(1, "spikes", 3, starts()).rejected


@test("fortify places every piece of each style: inner doors, gatehouse traps, statues")
def _():
    for style, want in (("fortified", "inner_doors"), ("gatehouse", "traps"), ("grand", "statues")):
        c = wide_c()
        c.id = 1
        M.GATES = LUA.table_from({"entrances": LUA.table_from({1: c})})
        M.doors_in = LUA.eval("function(list) return {} end")
        M.stockpiles_in = LUA.eval("function(list) return {} end")
        M.place_hook = lambda text, pos: True
        saved = M.wall_beside
        M.wall_beside = LUA.eval("function() return true end")
        try:
            r = M.fortify(1, style, starts())
        finally:
            M.place_hook = None
            M.wall_beside = saved
        assert r.ok and r[want] > 0, (style, dict(r))



CLEAR = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-gates', 't', env))()
local function key(x, y, z) return (z * 4096 + y) * 4096 + x end
-- the main stair at 94,95 (z 168) with its hatch a level up (94,95,169);
-- an old tree gate's door at 94,99,169 (no pieces recorded)
local at = {['94,95,169'] = {id = 7, t = 'Hatch'}, ['94,99,169'] = {id = 8, t = 'Door'}}
local removed = {}
env.df = {building_type = {Hatch = 'Hatch', Door = 'Door', Trap = 'Trap', Construction = 'Construction',
                           Hatch_ = 1}, trap_type = {Lever = 1}}
setmetatable(env.df.building_type, {__index = function(_, k) return k end})
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.dfhack = {maps = {getTileFlags = function() return {subterranean = false} end},
              constructions = {findAtTile = function() return nil end},
              buildings = {findAtTile = function(p)
                  local b = at[p.x .. ',' .. p.y .. ',' .. p.z]
                  if b then return {id = b.id, getType = function() return b.t end,
                                    getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end} end
              end, deconstruct = function(b) table.insert(removed, b.id) end}}
env.GATES = {scanned = true, entrances = {{inside_list = {key(94, 95, 168)}, outs = {[key(94, 95, 169)] = true},
                                           equipment = {}}}}
return env, removed
"""


@test("cleanup: an old tree gate 4 tiles from the main stair never takes the stair's hatch (a level up)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, removed = lua.execute(CLEAR, (ROOT / "lua" / "ai-gates.lua").read_text(encoding="utf-8"))
    r = env.clear_gate(94, 99, 169, None, False)
    got = [removed[i] for i in range(1, len(removed) + 1)]
    # (0.100) no record of its pieces: nothing guessed at, nothing taken down
    assert not r.ok and "no record" in r.error and got == [], (dict(r), got)
    r = env.clear_gate(94, 97, 169, None, False)                   # right beside the stair: refused
    assert not r.ok and "still an entrance" in r.error, dict(r)


@test("0.104.105: a closing entrance says what it waits for (a planned hatch)")
def _():
    hatch = {"id": 9, "kind": "pending", "what": "hatch", "x1": 4, "y1": 5, "x2": 4, "y2": 6, "z": 0, "name": ""}
    setup(buildings=[DOOR_A, hatch])
    b = by_kind_and_y(find()[0])[("surface", 5)]
    assert b.closing and b.waiting and b.waiting["hatch"] == 1, (b.closing, b.waiting and dict(b.waiting))
    setup(buildings=[DOOR_A])
    assert not by_kind_and_y(find()[0])[("surface", 5)].waiting, "nothing planned: nothing waited for"


@test("0.104.105: days an entrance has read closing count from the first scan that saw it so")
def _():
    e = LUA.table_from({"closing": True, "x": 4, "y": 5, "z": 0})
    k = (0 * 4096 + 5) * 4096 + 4
    M.GATES = LUA.table_from({"scanned": True, "scanned_tick": 18000,
                              "closing_since": LUA.table_from({k: 6000})})
    assert M.closing_days(e) == 10, M.closing_days(e)
    e.closing = False
    assert M.closing_days(e) is None

@test("(0.104.139) the watcher: a gate gone asks for a scan (and the re-pull of a lowered bridge runs without error)")
def _():
    LUA.execute("""
      local M = ...
      PULLED = {}
      df = {building = {find = function(id)
              if id == 10 then return {gate_flags = {raised = false}, jobs = {}} end
              return nil end},
            global = {world = {units = {active = {}}}, cur_year_tick = 0}}
      dfhack = dfhack or {}
      dfhack.units = {getCitizens = function() return {} end}
      dfhack.timeout = function() return nil end
    """, M)
    e = LUA.table_from({"id": 1, "equipment": LUA.table_from({
        1: LUA.table_from({"id": 10, "kind": "bridge", "lever_id": 55}),
        2: LUA.table_from({"id": 11, "kind": "door"})})})
    M.GATES = LUA.table_from({"armed": True, "scanned": True, "closed": LUA.table_from({1: True}),
                              "entrances": LUA.table_from({1: e})})
    pulls = []
    M.pull = lambda lever: pulls.append(lever) or True
    M.check()
    assert M.GATES.scanned is False and M.GATES.gone == 1, (M.GATES.scanned, M.GATES.gone)
    LUA.execute("df = nil; dfhack = nil")


# --- (0.105.0, round 2) ledges and the vertical cut -----------------------------------

CUT = LUA.eval("function(M, e, s) local p, w = M.plan_cut(e, s); return {p, w} end")
_cut = CUT


def CUT(M_, e, s):
    r = _cut(M_, e, s)
    return r[1], r[2]


def two_levels(top, below):
    m = LUA.table()
    for z, rows in ((0, below), (1, top)):
        level = LUA.table()
        for y, r in enumerate(rows):
            level[y] = r
        m[z] = level
    W.map = m
    W.buildings = LUA.table()


# z1: the surface on the left, a 70-tall open court ('.' inside, roofed but wide
# open to the surface down column x4) leading down by two stairs at x10 and x20;
# z0: the fort below, reached only by those stairs.
COURT_TOP = ["oooo" + "." * 26 for _ in range(19)]
COURT_TOP[5] = COURT_TOP[5][:10] + "s" + COURT_TOP[5][11:]
COURT_TOP[12] = COURT_TOP[12][:20] + "s" + COURT_TOP[12][21:]
COURT_BELOW = ["#" * 30 for _ in range(19)]
COURT_BELOW[5] = "#" * 10 + "s" + "." * 19
COURT_BELOW[12] = "#" * 20 + "s" + "." * 9
for _y in range(6, 12):
    COURT_BELOW[_y] = "#" * 21 + "." * 9


def court_entrance():
    two_levels(COURT_TOP, COURT_BELOW)
    s0 = LUA.table_from({1: LUA.table_from({"x": 25, "y": 8, "z": 0})})
    es, _, _ = M.find_entrances(s0, W.buildings)
    es = [es[i] for i in range(1, len(es) + 1)]
    return es, s0


@test("0.105.0 cut: a wide surface opening is closed where it leads down: a hatch on each stair down")
def _():
    es, s0 = court_entrance()
    assert len(es) == 1 and es[0].kind == "surface" and es[0].width == 19, [(e.kind, e.width) for e in es]
    e = es[0]
    plan, why = CUT(M, e, s0)
    assert plan is not None, why
    assert sorted(((k % 4096, k // 4096 % 4096, k // (4096 * 4096)) for k in plan.hatches.values())) == \
        [(10, 5, 1), (20, 12, 1)], list(plan.hatches.values())
    t = LUA.table()
    t[1] = e
    e.id = 1
    M.GATES = LUA.table_from({"entrances": t})
    placed = []
    M.place_hook = lambda text, pos: placed.append((text, pos.x, pos.y, pos.z)) or True
    try:
        r = M.cut_entrance(1, s0)
    finally:
        M.place_hook = None
    assert r.ok and r.hatches == 2 and r.style == "cut", dict(r)
    assert sorted(placed) == [("H", 10, 5, 1), ("H", 20, 12, 1)], placed


@test("0.105.0 cut: the scan counts the hatches (planned: closing; built: the entrance's gates, watched like others)")
def _():
    es, s0 = court_entrance()
    LUA.execute("local M, e = ... ; M.CUT_SPOTS = {}; for _, k in ipairs(e.inside_list) do M.CUT_SPOTS[k] = true end",
                M, es[0])                                  # (0.105.0 review) a 19-wide opening: scanned for a cut the AI made
    def hatch(i, x, y, kind="hatch"):
        b = {"id": i, "kind": kind, "x1": x, "y1": y, "x2": x, "y2": y, "z": 1, "name": ""}
        if kind == "pending":
            b["what"] = "hatch"
        return LUA.table_from(b)
    W.buildings = LUA.table_from({1: hatch(31, 10, 5, "pending"), 2: hatch(32, 20, 12, "pending")})
    es, _, _ = M.find_entrances(s0, W.buildings)
    e = es[1]
    assert e.closing and e.cut and e.waiting.hatch == 2 and not e.sealed, (e.closing, e.cut, e.sealed)
    W.buildings = LUA.table_from({1: hatch(31, 10, 5), 2: hatch(32, 20, 12)})
    es, _, _ = M.find_entrances(s0, W.buildings)
    e = es[1]
    assert e.sealed and e.cut and sorted(e.equipment[i].id for i in (1, 2)) == [31, 32], (e.sealed, e.cut)
    W.buildings = LUA.table_from({1: hatch(31, 10, 5)})                    # one stair still open: not sealed
    es, _, _ = M.find_entrances(s0, W.buildings)
    assert not es[1].sealed and not es[1].closing


@test("0.105.0 review cut: a dry run places nothing; a narrow opening the AI never cut isn't walked for hatches")
def _():
    es, s0 = court_entrance()
    e = es[0]
    t = LUA.table()
    t[1] = e
    e.id = 1
    M.GATES = LUA.table_from({"entrances": t})
    placed = []
    M.CUT_SPOTS = LUA.table()
    M.place_hook = lambda text, pos: placed.append((text, pos.x, pos.y, pos.z)) or True
    try:
        r = M.cut_entrance(1, s0, True)
    finally:
        M.place_hook = None
    assert r.ok and r.dry_run and r.hatches == 2 and placed == [], (dict(r), placed)
    assert not M.was_cut(e)
    def hatch(i, x, y):
        return LUA.table_from({"id": i, "kind": "hatch", "x1": x, "y1": y, "x2": x, "y2": y, "z": 1, "name": ""})
    W.buildings = LUA.table_from({1: hatch(31, 10, 5), 2: hatch(32, 20, 12)})
    es, _, _ = M.find_entrances(s0, W.buildings)
    assert not es[1].sealed and not es[1].cut           # 19 wide, never cut by the AI: walled, not cut
    # an error in the cut check doesn't lose the scan
    LUA.execute("local M = ... ; M.CUT_SPOTS = {}; M.FORTIFY_MAX_WIDTH = 5; M._ce = M.cut_equipment; "
                "M.cut_equipment = function() error('boom') end", M)
    try:
        es, _, _ = M.find_entrances(s0, W.buildings)
        assert len(es) == 1
    finally:
        LUA.execute("local M = ... ; M.cut_equipment = M._ce; M.FORTIFY_MAX_WIDTH = 50", M)


@test("0.105.0 review watcher: a dwarf on a cut entrance's porch is outside; a beast near the hatches is near")
def _():
    es, s0 = court_entrance()
    LUA.execute("local M, e = ... ; M.CUT_SPOTS = {}; for _, k in ipairs(e.inside_list) do M.CUT_SPOTS[k] = true end",
                M, es[0])
    def hatch(i, x, y):
        return LUA.table_from({"id": i, "kind": "hatch", "x1": x, "y1": y, "x2": x, "y2": y, "z": 1, "name": ""})
    W.buildings = LUA.table_from({1: hatch(31, 10, 5), 2: hatch(32, 20, 12)})
    es, inside, _ = M.find_entrances(s0, W.buildings)
    e = es[1]
    assert e.sealed and e.cut and e.porch is not None
    k = LUA.eval("function(x, y, z) return (z * 4096 + y) * 4096 + x end")
    assert inside[k(15, 8, 1)] and e.porch[k(15, 8, 1)]          # the porch reads as inside on the map...
    M.GATES = LUA.table_from({"entrances": LUA.table_from({1: e}), "inside": inside})
    cit = []
    M.dfhack = LUA.table_from({"units": LUA.table_from({"getCitizens": lambda *_: LUA.table_from(
        {i + 1: LUA.table_from({"pos": LUA.table_from(p)}) for i, p in enumerate(cit)})})})
    try:
        cit[:] = [{"x": 25, "y": 8, "z": 0}]
        assert M.citizens_outside() == 0
        cit.append({"x": 15, "y": 8, "z": 1})                        # ...but a dwarf there is outside
        assert M.citizens_outside() == 1
    finally:
        M.dfhack = None
    # a beast deep in the court: 16 from the opening (x4), 1 from the hatch at x20 y12
    d = M.distance_to(e, LUA.table_from({"x": 21, "y": 12, "z": 1}))
    assert d == 1, d


@test("0.105.0 cut: refused when a ramp leads down, or when dwarves live in the open area")
def _():
    below = list(COURT_BELOW)
    below[13] = "#" * 19 + "." * 11                         # floor under the court at y13, from x19
    two_levels(COURT_TOP, below)
    # x19 y13 on z0 is a ramp up into the court beside the stair's foot: a way down no hatch closes
    old = M.tile
    M.tile = LUA.eval("""function(old) return function(x, y, z)
        if x == 19 and y == 13 and z == 0 then return {walk = true, shape = 'RAMP', material = 'STONE'} end
        return old(x, y, z) end end""")(old)
    try:
        s0 = LUA.table_from({1: LUA.table_from({"x": 25, "y": 8, "z": 0})})
        es, _, _ = M.find_entrances(s0, W.buildings)
        e = [es[i] for i in range(1, len(es) + 1) if es[i].kind == "surface"][0]
        plan, why = CUT(M, e, s0)
        assert plan is None and "ramp" in str(why), why
    finally:
        M.tile = old
    es, s0 = court_entrance()
    s1 = LUA.table_from({1: LUA.table_from({"x": 15, "y": 8, "z": 1}),        # a dwarf lives in the court
                         2: LUA.table_from({"x": 25, "y": 8, "z": 0})})
    plan, why = CUT(M, es[0], s1)
    assert plan is None and "dwarves live" in str(why), why


@test("0.105.0 ledges: a citizen on a ledge outside doesn't seed entrances of his own")
def _():
    rows = list(FORT)
    # a little roofed ledge (2 tiles) out on the surface at x1-2 y12, walled from the
    # fort on its east, open to the surface on its west; a citizen stands on it
    rows = with_tile(with_tile(with_tile(rows, 1, 11, "#"), 2, 11, "#"), 3, 11, "#")
    rows = with_tile(with_tile(with_tile(rows, 1, 13, "#"), 2, 13, "#"), 3, 13, "#")
    rows = with_tile(with_tile(with_tile(rows, 1, 12, "."), 2, 12, "."), 3, 12, "#")
    setup(rows=rows, buildings=[DOOR_A])
    ledge = LUA.table_from({"x": 1, "y": 12, "z": 0})
    fort_ = LUA.table_from({"x": 20, "y": 8, "z": 0})
    kept = M.fort_starts(LUA.table_from({1: ledge, 2: fort_}))
    assert len(kept) == 1 and kept[1].x == 20, [(kept[i].x, kept[i].y) for i in range(1, len(kept) + 1)]
    # alone (a new fort's first room), the pocket is the fort
    kept = M.fort_starts(LUA.table_from({1: ledge}))
    assert len(kept) == 1 and kept[1].x == 1
    # the scan with both: the same entrances as the fort alone
    es, _, _ = M.find_entrances(M.fort_starts(LUA.table_from({1: ledge, 2: fort_})), W.buildings)
    assert len(es) == 4, len(es)
    # with the ledge's citizen counted, the ledge was an inside of its own, with an entrance
    es, _, _ = M.find_entrances(LUA.table_from({1: ledge, 2: fort_}), W.buildings)
    assert len(es) == 5, len(es)
    # a treetop never counts
    setup(rows=with_tile(FORT, 1, 12, "B"), buildings=[DOOR_A])
    kept = M.fort_starts(LUA.table_from({1: LUA.table_from({"x": 1, "y": 12, "z": 0}), 2: fort_}))
    assert len(kept) == 1 and kept[1].x == 20


@test("0.105.3 B: an enemy deep inside the fort is an intruder; one at a gate, outside, or with no map isn't")
def _():
    setup(buildings=[DOOR_A])
    starts = LUA.table_from({1: LUA.table_from({"x": 20, "y": 8, "z": 0})})
    es, inside, n = M.find_entrances(starts, W.buildings)
    old = M.GATES
    try:
        M.GATES = LUA.table_from({"scanned": True, "entrances": es, "inside": inside})
        pos = lambda x, y: LUA.table_from({"x": x, "y": y, "z": 0})
        assert M.inside_fort(pos(25, 4)) is True             # deep in the fort (the thief)
        assert M.inside_fort(pos(10, 2)) is False            # just behind entrance A's door: at the gate
        assert M.inside_fort(pos(1, 2)) is False             # outside
        assert M.inside_fort(pos(22, 15)) is False           # 10 tiles or less from the cavern opening
        M.GATES = LUA.table_from({"scanned": False})
        assert M.inside_fort(pos(25, 4)) is None             # no map (a reload): can't say
        assert M.intruders_inside() is None
    finally:
        M.GATES = old


@test("0.105.3 A: a gate shut with dwarves outside opens again after half a day with nothing in sight; a siege in sight keeps it shut")
def _():
    LUA.execute("""
      local M = ...
      DOORS = {[11] = {door_flags = {forbidden = true}, jobs = {}}}
      df = {building = {find = function(id) return DOORS[id] end},
            global = {world = {units = {active = {}}}, cur_year_tick = 0}}
      dfhack = {units = {getCitizens = function() return {} end}, timeout = function() return nil end,
                gui = {showAnnouncement = function() end}}
      SEEN = {}
      M._vd = M.visible_dangers
      M.visible_dangers = function() return SEEN end
    """, M)
    k = (0 * 4096 + 5) * 4096 + 3
    def gate():
        e = LUA.table_from({"id": 1, "x": 4, "y": 5, "z": 0, "outs": LUA.table_from({k: True}),
                            "equipment": LUA.table_from({1: LUA.table_from({"id": 11, "kind": "door"})})})
        M.GATES = LUA.table_from({"armed": True, "scanned": True, "closed": LUA.table_from({1: True}),
                                  "entrances": LUA.table_from({1: e}), "peak": 1})
        LUA.execute("DOORS[11].door_flags.forbidden = true")
    try:
        # the sneaker hid again: nothing visible. Shut for 5 looks, open at the 6th
        gate()
        for i in range(int(M.REOPEN_CHECKS) - 1):
            M.check()
            assert M.GATES.closed[1], i
        M.check()
        assert not M.GATES.closed[1] and LUA.eval("DOORS[11].door_flags.forbidden") is False
        assert M.GATES.armed                                         # still watching: shut again if danger comes
        # a siege in sight (an invader far off): stays shut
        gate()
        LUA.execute("SEEN = {{pos = {x = 150, y = 150, z = 0}, invader = true}}")
        for _ in range(int(M.REOPEN_CHECKS) + 2):
            M.check()
        assert M.GATES.closed[1]
        # a beast (not an invader) near the gate: stays shut; far off: opens
        gate()
        LUA.execute("SEEN = {{pos = {x = 20, y = 5, z = 0}, invader = false}}")
        for _ in range(int(M.REOPEN_CHECKS) + 2):
            M.check()
        assert M.GATES.closed[1]
        LUA.execute("SEEN = {{pos = {x = 200, y = 5, z = 0}, invader = false}}")
        for _ in range(int(M.REOPEN_CHECKS)):
            M.check()
        assert not M.GATES.closed[1]
        # (0.105.4 review) a great danger in sight, however far: stays shut
        gate()
        LUA.execute("SEEN = {{pos = {x = 200, y = 5, z = 0}, invader = false, great = true}}")
        for _ in range(int(M.REOPEN_CHECKS) + 2):
            M.check()
        assert M.GATES.closed[1]
        # (0.105.4 review) a bigger ambush seen (peak 5) that hid again: stays shut
        # (the brain's quiet wait); no peak known (a reload): stays shut too
        for peak in (5, None):
            gate()
            M.GATES.peak = peak
            LUA.execute("SEEN = {}")
            for _ in range(int(M.REOPEN_CHECKS) + 2):
                M.check()
            assert M.GATES.closed[1], peak
        # (0.105.4 review) reopen and re-close at the same distance: no band that flips
        assert not M.may_reopen(M.WIDE, 0, 0, 1) and M.may_reopen(M.WIDE + 1, 0, 0, 1)
        assert not M.should_close(M.WIDE + 1, 0) and M.should_close(M.WIDE, 0)
    finally:
        LUA.execute("local M = ...; df = nil; dfhack = nil; M.visible_dangers = M._vd", M)
        M.GATES = LUA.table_from({"scanned": False})



@test("0.105.4 review: visitors outside counts only visitors off the map of the inside")
def _():
    LUA.execute("""
      local M = ...
      local function u(x, y, vis) return {pos = {x = x, y = y, z = 0}, vis = vis} end
      df = {global = {world = {units = {active = {u(25, 4, true), u(1, 2, true), u(2, 3, true), u(1, 5, false)}}}}}
      dfhack = {units = {isAlive = function() return true end, isVisitor = function(x) return x.vis end,
                         isCitizen = function() return false end}}
    """, M)
    setup(buildings=[DOOR_A])
    starts = LUA.table_from({1: LUA.table_from({"x": 20, "y": 8, "z": 0})})
    es, inside, n = M.find_entrances(starts, W.buildings)
    old = M.GATES
    try:
        M.GATES = LUA.table_from({"scanned": True, "entrances": es, "inside": inside})
        assert M.visitors_outside() == 2              # two outside; the one in the tavern doesn't count
        M.GATES = LUA.table_from({"scanned": False})
        assert M.visitors_outside() is None
    finally:
        M.GATES = old
        LUA.execute("df = nil; dfhack = nil")


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
