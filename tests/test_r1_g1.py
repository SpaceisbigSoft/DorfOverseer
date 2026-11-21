"""(R1 g1) The gate planner never cuts the fort in two.

Fort F (run 2, 15 Nov, 0.105.55): fortify #3 at 18:23:59 moved its gate line
two steps in from the founding stair (x108 y149), "the way in ... is a stair
updown", and walled x110 y148-150 z170, the full width of hallway floor 2's
main hall, with its 2 doors on z169 and none on z170. Four founders died of
thirst behind the wall (x125-128 y149-150 z170, `no_path`). plan_line's
cut-off check flooded from every citizen, so with citizens on both sides
the wall cut off "0 tiles". The scenario is built here from F's own
coordinates (journal.2.jsonl, rule fortify, result pieces).

    python tests/test_r1_g1.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lua_modules_util import module_src  # noqa: E402
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

HARNESS = r"""
local src, fp_src = ...
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-gates', 't', env))()
local W = {tiles = {}, default = {}, occ = {}, at = {}, size = {200, 200, 172}}
-- W.tiles["x,y,z"] = char; else W.default[z] (or rock):
-- '#' rock, '.' inside floor, 'o' outside floor, 's' stair up/down (inside),
-- 'u' stair up (inside, the bottom), 't' stair down on the surface (outside),
-- 'b' inside floor with a building on it
function env.tile(x, y, z)
  local W_, H_, Z_ = W.size[1], W.size[2], W.size[3]
  if x < 0 or y < 0 or z < 0 or x >= W_ or y >= H_ or z >= Z_ then return nil end
  local k = x .. ',' .. y .. ',' .. z
  local ch = W.tiles[k] or W.default[z] or '#'
  if ch == '#' then return {walk = false, shape = 'WALL'} end
  local shape = (ch == 's' and 'STAIR_UPDOWN') or (ch == 'u' and 'STAIR_UP') or (ch == 't' and 'STAIR_DOWN') or 'FLOOR'
  return {walk = true, shape = shape, outside = ch == 'o' or ch == 't', occupied = ch == 'b' or W.occ[k] == true,
          depth = 0, material = 'STONE'}
end
function env.map_size() return W.size[1], W.size[2], W.size[3] end
W.buildings = {}
function env.gate_buildings() return W.buildings end
function env.building_at(x, y, z) return W.at[x .. ',' .. y .. ',' .. z] end
-- the things a gate must leave on the fort's side (the game's lists, faked)
W.things = {citizens = {}, boxes = {}}
env.REAL_FAR = env.gate_far_things
function env.gate_far_things() return W.things end
-- ai-builder (the floor record, the projects) and the real ai-floorplan
local fp_env = setmetatable({}, {__index = _G})
assert(load(fp_src, 'ai-floorplan', 't', fp_env))()
W.floors, W.projects = {floors = {}}, {list = {}}
local B = {load_floors = function() return W.floors, true end, load_projects = function() return W.projects end}
local real_req = env.reqscript
env.reqscript = function(n, ...)
  if n == 'ai-builder' then return B end
  if n == 'ai-floorplan' then return fp_env end
  return real_req(n, ...)
end
env.REAL_KEEPOUT = env.gate_keepout
return env, W
"""

LUA = LuaRuntime(unpack_returned_tuples=True)
M, W = LUA.execute(HARNESS, module_src("ai-gates.lua"),
                   (ROOT / "lua" / "ai-floorplan.lua").read_text(encoding="utf-8"))


def K(x, y, z):
    return (z * 4096 + y) * 4096 + x


def unk(k):
    return k % 4096, (k // 4096) % 4096, k // (4096 * 4096)


def lt(d):
    return LUA.table_from(d)


def keys_of(t):
    return sorted(unk(t[i]) for i in range(1, len(t) + 1)) if t is not None else []


def pts(lst):
    return lt({i + 1: lt({"x": x, "y": y, "z": z}) for i, (x, y, z) in enumerate(lst)})


# ---------------------------------------------------------------- fort F
SX, SY = 108, 149                 # the founding stair
Z1, Z2, ZS = 169, 170, 171        # floor 1 (workshops), floor 2 (bedrooms), the surface
F1_CIT = [(115, 149, Z1), (120, 150, Z1), (130, 149, Z1)]
F2_CIT = [(125, 149, Z2), (126, 150, Z2), (127, 149, Z2), (128, 150, Z2)]   # where F's four died


def fort_f(hatch_planned=True, top_blocked=True):
    """F's first weeks: the stair from the surface (z171) down to floor 1;
    floor 2 (z170): hub and a 3-wide hall east (x110-136), bedrooms off it;
    floor 1 (z169): hub, a hall east (x110-146) and one south."""
    tiles = {}
    tiles[f"{SX},{SY},{ZS}"] = "t"
    tiles[f"{SX},{SY},{Z2}"] = "s"
    tiles[f"{SX},{SY},{Z1}"] = "u"
    for z in (Z1, Z2):
        for x in range(SX - 1, SX + 2):
            for y in range(SY - 1, SY + 2):
                if (x, y) != (SX, SY):
                    tiles[f"{x},{y},{z}"] = "."
    for x in range(110, 137):                     # floor 2's main hall
        for y in range(148, 151):
            tiles[f"{x},{y},{Z2}"] = "."
    for i in range(6):                            # 12 bedrooms, 3x2 each side
        x0 = 112 + i * 4
        for x in range(x0, x0 + 3):
            for y in (145, 146, 147, 151, 152, 153):
                tiles[f"{x},{y},{Z2}"] = "."
    for x in range(110, 147):                     # floor 1's east hall
        for y in range(148, 151):
            tiles[f"{x},{y},{Z1}"] = "."
    for x in range(107, 110):                     # and its south arm
        for y in range(151, 180):
            tiles[f"{x},{y},{Z1}"] = "."
    W.tiles = lt(tiles)
    W.default = lt({ZS: "o"})
    occ, at = {}, {}
    if top_blocked:
        occ[f"{SX},{SY},{ZS}"] = True             # the planned hatch (or something else) on the stair's top
    if hatch_planned:
        at[f"{SX},{SY},{ZS}"] = "Hatch"
    W.occ, W.at = lt(occ), lt(at)
    W.buildings = lt({1: lt({"id": 301, "kind": "pending", "what": "hatch", "x1": SX, "y1": SY, "x2": SX,
                             "y2": SY, "z": ZS})}) if hatch_planned else LUA.table()
    W.floors = lt({"floors": lt({})})
    W.projects = lt({"list": lt({})})
    W.things = lt({"citizens": pts(F1_CIT + F2_CIT), "boxes": lt({})})
    M.gate_keepout = lambda: LUA.table()          # (the floor record's own test puts the real one back)
    starts = pts(F1_CIT + F2_CIT)
    es, _, _ = M.find_entrances(starts, W.buildings)
    es = [es[i] for i in range(1, len(es) + 1)]
    e = [x for x in es if x.kind == "surface" and (x.x, x.y) == (SX, SY)][0]
    return e, starts


def f_step2():
    """F's line two steps in, as plan_gate makes it: the hub ring on z169 and x110 y148-150 on z170;
    outside it the stair and floor 2's hub (the lines before it)."""
    line = [(x, y, Z1) for x in range(107, 110) for y in range(148, 151) if (x, y) != (SX, SY)] + \
           [(110, y, Z2) for y in range(148, 151)]
    outs = {K(SX, SY, ZS): True, K(SX, SY, Z2): True, K(SX, SY, Z1): True}
    for x in range(107, 110):
        for y in range(148, 151):
            outs[K(x, y, Z2)] = True
    return lt({"id": 1, "kind": "surface", "inside_list": lt({i + 1: K(*p) for i, p in enumerate(sorted(line))}),
               "outs": lt(outs), "width": len(line)})


def res2(r):
    return (r[0], r[1]) if isinstance(r, tuple) else (r, None)


@test("F: a hatch planned on the stair's top is the gate: no wall line moved in (fortify #3's walls never planned)")
def _():
    e, starts = fort_f(hatch_planned=True)
    assert e.z == Z2 and e.width == 1, (e.x, e.y, e.z, e.width)
    plan, why = res2(M.plan_gate(e, "plain", starts))
    assert plan is None, keys_of(plan.walls)
    assert "hatch" in why and f"x{SX} y{SY} z{ZS}" in why and "stair updown" in why, why


@test("F: no hatch, citizens on both floors: the line two steps in (floor 2's hall walled) is refused as a cut")
def _():
    e, starts = fort_f(hatch_planned=False, top_blocked=True)
    plan, why = res2(M.plan_gate(e, "plain", starts))
    walls = keys_of(plan.walls) if plan is not None else []
    assert plan is None, ("planned", walls, keys_of(plan.doors), plan.moved_in)
    assert "cut" in why, why
    # and the step-2 line itself (F's 11 tiles) straight to plan_line: refused, why said
    ve = f_step2()
    plan, why = res2(M.plan_line(ve, "plain", starts, LUA.table(), LUA.table()))
    assert plan is None and "cut the fort in two" in why, (why, plan and keys_of(plan.walls))


@test("F: citizens only on floor 1 (the four on floor 2 not among the starts): still refused, floor 2 is cut off")
def _():
    e, _ = fort_f(hatch_planned=False, top_blocked=True)
    starts = pts(F1_CIT)
    W.things = lt({"citizens": pts(F1_CIT + F2_CIT), "boxes": lt({})})
    plan, why = res2(M.plan_gate(e, "plain", starts))
    assert plan is None and "cut" in why, (why, plan and keys_of(plan.walls))


@test("F: floor 1's and floor 2's halls in the floor record: no wall on a hallway floor's hall (claims: hub, runs)")
def _():
    e, starts = fort_f(hatch_planned=False, top_blocked=True)
    M.gate_keepout = M.REAL_KEEPOUT
    hub = lt({"id": 1, "ox": 0, "oy": 0, "dx": 1, "dy": 0, "len": 27, "node": 3})
    hub1 = lt({"id": 1, "ox": 0, "oy": 0, "dx": 1, "dy": 0, "len": 37, "node": 3})
    W.floors = lt({"floors": lt({
        1: lt({"id": 1, "z": Z1, "stair": lt({"x": SX, "y": SY}), "runs": lt({1: hub1}), "slots": lt({})}),
        2: lt({"id": 2, "z": Z2, "stair": lt({"x": SX, "y": SY}), "runs": lt({1: hub}),
               "slots": lt({1: lt({"run": 1, "u": 4, "w": 3, "d": 2, "side": 1})})})})})
    ko = M.gate_keepout()
    assert ko[K(110, 149, Z2)] and "floor 2" in ko[K(110, 149, Z2)], "floor 2's hall start"
    assert ko[K(136, 150, Z2)] and not ko[K(137, 149, Z2)], "the hall's end"
    assert ko[K(107, 148, Z1)] and "floor 1" in ko[K(107, 148, Z1)] and not ko[K(SX, SY, Z1)], "the hub, not the stair"
    # the step-2 line straight to plan_line (no cut check reached: the hall check says why)
    ve = f_step2()
    plan, why = res2(M.plan_line(ve, "narrow", starts, LUA.table(), LUA.table()))
    assert plan is None and "hall of hallway floor" in why, why
    plan, why = res2(M.plan_gate(e, "plain", starts))
    assert plan is None, keys_of(plan.walls)


# ---------------------------------------------------------------- a line over two levels
def two_levels():
    """Two tunnels in from the west, one on z0 and one on z1, into rooms that
    an inner stair at x15 joins: the fort is whole whichever level is walled."""
    tiles = {}
    for z in (0, 1):
        for x in range(0, 5):
            for y in range(4, 7):
                tiles[f"{x},{y},{z}"] = "o"
        for x in range(5, 20):
            for y in range(4, 7):
                tiles[f"{x},{y},{z}"] = "."
    tiles["15,5,0"] = "u"
    tiles["15,5,1"] = "s"
    W.tiles = lt(tiles)
    W.default = LUA.table()
    W.occ, W.at = LUA.table(), LUA.table()
    W.size = lt({1: 40, 2: 20, 3: 2})
    W.things = lt({"citizens": pts([(18, 5, 0)]), "boxes": lt({})})
    M.gate_keepout = lambda: LUA.table()
    M.cache, M.edge_cache = LUA.table(), LUA.table()
    line = [(5, y, z) for z in (0, 1) for y in range(4, 7)]
    outs = {K(4, y, z): True for z in (0, 1) for y in range(3, 8)}
    e = lt({"id": 1, "kind": "surface", "inside_list": lt({i + 1: K(*p) for i, p in enumerate(line)}),
            "outs": lt(outs), "width": 6})
    return e, pts([(18, 5, 0)])


@test("a line over two levels gets a door on each level (no level walled shut with its doors on the other)")
def _():
    e, starts = two_levels()
    try:
        for style in ("plain", "narrow"):
            plan, why = res2(M.plan_line(e, style, starts, LUA.table(), LUA.table()))
            assert plan is not None, (style, why)
            wall_z = {z for _, _, z in keys_of(plan.walls)}
            door_z = {z for _, _, z in keys_of(plan.doors)}
            assert wall_z == {0, 1} and door_z == {0, 1}, (style, keys_of(plan.walls), keys_of(plan.doors))
        # the doors already there are on z0 only: z1 gets a door of its own too
        present = lt({K(5, 5, 0): True})
        plan, why = res2(M.plan_line(e, "narrow", starts, present, LUA.table()))
        assert plan is not None and plan.kept_doors == 1, why
        assert keys_of(plan.doors) == [(5, 5, 1)], keys_of(plan.doors)
    finally:
        W.size = lt({1: 200, 2: 200, 3: 172})


@test("an AI project's corridor (p.links) takes no gate wall")
def _():
    e, starts = two_levels()
    try:
        M.gate_keepout = M.REAL_KEEPOUT
        W.floors = lt({"floors": lt({})})
        W.projects = lt({"list": lt({1: lt({"id": 5, "kind": "bedrooms", "phase": "done", "z": 0,
                                               "anchor": lt({"x": 10, "y": 5}),
                                               "links": lt({1: lt({"x": -5, "y": -1})})})})})
        plan, why = res2(M.plan_line(e, "narrow", starts, LUA.table(), LUA.table()))
        assert plan is None and "corridor of AI project 5" in why and "x5 y4 z0" in why, why
        W.projects.list[1].phase = "cancelled"
        plan, why = res2(M.plan_line(e, "narrow", starts, LUA.table(), LUA.table()))
        assert plan is not None, why
    finally:
        W.size = lt({1: 200, 2: 200, 3: 172})
        W.projects = lt({"list": lt({})})


# ---------------------------------------------------------------- a room left outside a moved-in gate
SMALL = [
    "################",   # 0
    "##.#############",   # 1  a one-tile room off the tunnel's mouth
    "o...............",   # 2
    "obb.............",   # 3  the opening (x1) and the first line in (x2) blocked
    "o...............",   # 4
    "################",   # 5
]


def small(bed_at):
    tiles = {}
    for y, row in enumerate(SMALL):
        for x, ch in enumerate(row):
            if ch != "#":
                tiles[f"{x},{y},0"] = ch
    W.tiles = lt(tiles)
    W.default = LUA.table()
    W.occ, W.at = LUA.table(), LUA.table()
    W.size = lt({1: 16, 2: 6, 3: 1})
    boxes = {1: lt({"what": "a bed", "x1": bed_at[0], "y1": bed_at[1], "x2": bed_at[0], "y2": bed_at[1],
                    "z": 0, "ring": True})}
    W.things = lt({"citizens": pts([(12, 3, 0)]), "boxes": lt(boxes)})
    M.gate_keepout = lambda: LUA.table()
    starts = pts([(12, 3, 0)])
    es, _, _ = M.find_entrances(starts, LUA.table())
    es = [es[i] for i in range(1, len(es) + 1)]
    return es[0], starts


@test("a bed in a room the moved-in gate leaves outside: refused (the old check counted only tiles)")
def _():
    try:
        e, starts = small((2, 1))
        plan, why = res2(M.plan_gate(e, "plain", starts))
        assert plan is None and "a bed would be left outside the gate" in why and "x2 y1" in why, \
            (why, plan and keys_of(plan.walls))
        e, starts = small((10, 3))                # the same bed further in: the gate goes up
        plan, why = res2(M.plan_gate(e, "plain", starts))
        assert plan is not None and plan.moved_in == 2, why
        assert {x for x, _, _ in keys_of(plan.walls) + keys_of(plan.doors)} == {3}, keys_of(plan.walls)
    finally:
        W.size = lt({1: 200, 2: 200, 3: 172})


# ---------------------------------------------------------------- the cut's hatches
def porch_two_parts():
    """A roofed porch (z1) behind a wide opening, two stairs down from it into
    two parts of the fort (z0) that meet nowhere else."""
    tiles = {}
    for x in range(0, 5):
        for y in range(1, 8):
            tiles[f"{x},{y},1"] = "o"
    for x in range(5, 16):
        for y in range(2, 7):
            tiles[f"{x},{y},1"] = "."
    for sx in (8, 12):
        tiles[f"{sx},4,1"] = "s"
        tiles[f"{sx},4,0"] = "u"
    for x in range(6, 10):                        # part A under the first stair
        for y in range(3, 6):
            if (x, y) != (8, 4):
                tiles[f"{x},{y},0"] = "."
    for x in range(11, 15):                       # part B under the second
        for y in range(3, 6):
            if (x, y) != (12, 4):
                tiles[f"{x},{y},0"] = "."
    for x in range(14, 20):
        for y in range(4, 6):
            tiles[f"{x},{y},0"] = "."
    W.tiles = lt(tiles)
    W.default = LUA.table()
    W.occ, W.at = LUA.table(), LUA.table()
    W.size = lt({1: 25, 2: 10, 3: 2})
    M.gate_keepout = lambda: LUA.table()
    M.cache, M.edge_cache = LUA.table(), LUA.table()
    line = [(5, y, 1) for y in range(2, 7)]
    outs = {K(4, y, 1): True for y in range(1, 8)}
    return lt({"id": 1, "kind": "surface", "x": 5, "y": 2, "z": 1, "width": 5,
               "inside_list": lt({i + 1: K(*p) for i, p in enumerate(line)}), "outs": lt(outs)})


@test("cut: hatches on two stairs down into parts of the fort that meet only on the porch are refused")
def _():
    try:
        e = porch_two_parts()
        cits = [(7, 4, 0), (18, 5, 0)]
        W.things = lt({"citizens": pts(cits), "boxes": lt({})})
        plan, why = res2(M.plan_cut(e, pts(cits), True))
        assert plan is None and "cut the fort in two" in why, (why, plan and keys_of(plan.hatches))
        # joined below as well (a tunnel from A to B): the two hatches are the cut
        for x in range(9, 12):
            W.tiles[f"{x},5,0"] = "."
        M.cache, M.edge_cache = LUA.table(), LUA.table()
        plan, why = res2(M.plan_cut(e, pts(cits), True))
        assert plan is not None and keys_of(plan.hatches) == [(8, 4, 1), (12, 4, 1)], why
        # a well on the porch: it would be outside the hatches
        W.things = lt({"citizens": pts(cits), "boxes": lt({1: lt({"what": "a well", "x1": 10, "y1": 3, "x2": 10,
                                                                  "y2": 3, "z": 1, "ring": True})})})
        plan, why = res2(M.plan_cut(e, pts(cits), True))
        assert plan is None and "a well would be left outside the gate" in why, why
    finally:
        W.size = lt({1: 200, 2: 200, 3: 172})


@test("the game's lists: citizens, beds, wells, food piles and AI levels, each behind its pcall")
def _():
    assert len(M.REAL_FAR().citizens) == 0 and len(M.REAL_FAR().boxes) == 0     # no game: empty, no error
    LUA.execute("""local M, W = ...
      M.dfhack = {units = {getCitizens = function() return {{pos = {x = 1, y = 2, z = 3}}, {pos = {x = 0, y = 0, z = -30000}}} end}}
      M.df = {global = {world = {buildings = {other = {
        BED = {{x1 = 4, y1 = 5, x2 = 4, y2 = 5, z = 6}},
        WELL = {{x1 = 7, y1 = 7, x2 = 7, y2 = 7, z = 6}},
        STOCKPILE = {{x1 = 1, y1 = 1, x2 = 3, y2 = 3, z = 6, settings = {flags = {food = true}}},
                     {x1 = 9, y1 = 9, x2 = 9, y2 = 9, z = 6, settings = {flags = {food = false}}}}}}}}}
      W.projects = {list = {{id = 7, kind = 'dining', phase = 'done', z = 6, area = {x1 = 10, y1 = 10, x2 = 14, y2 = 12, z = 6}},
                            {id = 8, kind = 'tombs', phase = 'cancelled', z = 6, area = {x1 = 1, y1 = 1, x2 = 2, y2 = 2, z = 6}}}}""", M, W)
    try:
        t = M.REAL_FAR()
        cits = [(c.x, c.y, c.z) for c in t.citizens.values()]
        whats = sorted(b.what for b in t.boxes.values())
        assert cits == [(1, 2, 3)], cits
        assert whats == ["AI level 7 (dining)", "a bed", "a food or drink stockpile", "a well"], whats
    finally:
        M.dfhack, M.df = None, None
        W.projects = lt({"list": lt({})})


finish()
