"""(0.105.30, deep depot) The underground trade depot's wagons: the road's
search wants a 3-wide wagon way from the map's edge; the built road is
walked as a wagon would (DFHack's own depot check: 3x3 round every step,
ramps, no doors) and the first thing in the way is named, and cleared when
the AI can; the gates never put a door on the road; the brain acts on it.

Fort E (Deep mine, y251): `wagon_access: false` on a 1-level road, and a
caravan with pack animals only. Needs lupa.

    python tests/test_deep_depot_wagons.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)


def _harness(path: str) -> str:
    tree = ast.parse((ROOT / "tests" / path).read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "HARNESS")


# --- the builder, on test_builder's fake fort ------------------------------------

LUA = LuaRuntime(unpack_returned_tuples=True)
LUA.globals().LUA_DIR = str(ROOT / "lua")
B, W = LUA.execute(_harness("test_builder.py"),
                   (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8"),
                   (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8"))
B.DEEP_DEPOT_SECONDS = 20          # (a slow test machine: the search is never cut short here)
B.DEEP_WAGON_SECONDS = 10

# the module's own hooks, recorded
LUA.execute("""
  WAGON_BLD = {}                    -- "x,y,z" -> what a wagon sees built there
  FELLED, REMOVED = {}, {}
""")
LUA.eval("""function(B)
  B.wagon_building = function(x, y, z) return WAGON_BLD[x .. ',' .. y .. ',' .. z] end
  B.fell_tree = function(x, y, z) table.insert(FELLED, {x, y, z}); B.tile_info(x, y, z).designated = true; return true end
  B.remove_building = function(id) table.insert(REMOVED, id); return true end
  B.pasture_anchors = function() return {{x = 60, y = 60, z = 80}} end
  B.elevation_offset = function() return 0 end
end""")(B)
G = LUA.globals()


def reset(edge=True):
    """A fresh fort; open ground at z80 round it, out to the map's edges
    (edge=True) or only x/y 20-100 (no way out for wagons)."""
    W.reset()
    LUA.execute("df = df or {}; df.global = {cur_year = 250, cur_year_tick = 0, "
                "world = {buildings = {other = {TRADE_DEPOT = {}}}}}; WAGON_BLD = {}; FELLED = {}; REMOVED = {}")
    B.DEEP_CHECK = LUA.table()
    B.DEEP_REMOVING = LUA.table()
    lo, hi = (0, 119) if edge else (20, 100)
    LUA.eval("""function(W, lo, hi)
      for x = lo, hi do for y = lo, hi do
        local t = W.get(x, y, 80)
        if t.shape == 'WALL' then W.set(x, y, 80, {shape='FLOOR', material='SOIL', outside=true}) end
        W.set(x, y, 81, {shape='EMPTY', outside=true})
      end end
    end""")(W, lo, hi)


def plan_tiles():
    d = B.deep_depot_data()
    return [(t.x, t.y, t.z, t.r) for t in d.tiles.values()]


def dig_and_build(acc=0):
    """The road dug as the game digs it, the depot built in its hall; the
    game's flag `acc` (0 no, 1 yes, None unread)."""
    r = B.place_deep_depot(False)
    assert r.ok and r.stage == "digging", dict(r)
    shape = {"h": "RAMP_TOP", "ramp": "RAMP", "d": "FLOOR"}
    for x, y, z, rr in plan_tiles():
        W.set(x, y, z, LUA.table_from({"shape": shape[rr], "designated": False, "outside": rr == "h"}))
    p = B.place_deep_depot(False)
    assert p.ok and p.stage == "placed", dict(p)
    d = B.deep_depot_data()
    LUA.eval("""function(x, y, z, acc)
      df.global.world.buildings.other.TRADE_DEPOT = {{x1 = x - 2, x2 = x + 2, y1 = y - 2, y2 = y + 2, z = z,
        accessible = acc, getBuildStage = function(self) return 3 end, getMaxBuildStage = function(self) return 3 end}}
    end""")(d.depot.x, d.depot.y, d.depot.z, acc)
    return d


def status():
    B.DEEP_CHECK = LUA.table()
    return B.deep_depot_status()


def mouth(d, u, v):
    """A surface tile off the road's start: u along the road (-1 the approach),
    v across it."""
    dx, dy = d.dir[1], d.dir[2]
    px, py = -dy, dx
    return d.start.x + u * dx + v * px, d.start.y + u * dy + v * py, d.start.z


def setb(x, y, z, fields):
    G.WAGON_BLD[f"{x},{y},{z}"] = LUA.table_from(fields)


@test("the search: no road whose start the wagons can't reach from the map's edge; a 3-wide way in is enough, 2 is not")
def _():
    reset(edge=False)                      # open ground ringed by rock: no way in from any edge
    r = B.place_deep_depot(True)
    assert not r.ok and r.no_road and "3-wide way for wagons" in r.error, dict(r)
    # a 3-wide road of open ground from the west edge into the pocket
    reset(edge=False)
    LUA.eval("""function(W) for x = 0, 20 do for y = 30, 32 do
      W.set(x, y, 80, {shape='FLOOR', material='SOIL', outside=true}); W.set(x, y, 81, {shape='EMPTY', outside=true})
    end end end""")(W)
    r = B.place_deep_depot(True)
    assert r.ok and r.stage == "digging", dict(r)
    # only 2 wide: no wagon gets through
    reset(edge=False)
    LUA.eval("""function(W) for x = 0, 20 do for y = 30, 31 do
      W.set(x, y, 80, {shape='FLOOR', material='SOIL', outside=true}); W.set(x, y, 81, {shape='EMPTY', outside=true})
    end end end""")(W)
    r = B.place_deep_depot(True)
    assert not r.ok and r.no_road and "3-wide way for wagons" in r.error, dict(r)


@test("the search saves the road's heading; the mouth's tiles (where the wagons turn in) are known")
def _():
    reset()
    dig_and_build()
    d = B.deep_depot_data()
    assert d.dir is not None and abs(d.dir[1]) + abs(d.dir[2]) == 1, dict(d)
    m = [(t.x, t.y, t.z) for t in B.deep_depot_mouth().values()]
    assert len(m) == 20 and (d.start.x, d.start.y, d.start.z) in m, m
    # an old save without the heading: worked out from the start and the channel
    d.dir = None
    assert len(B.deep_depot_mouth()) == 20


@test("DFHack's wagon rule on the AI's road: a wagon fits on the middle ramp with the rock behind it and goes up from there; the dug road reaches the map's edge from the depot")
def _():
    reset()
    d = dig_and_build()
    ramps = [(x, y, z) for x, y, z, r in plan_tiles() if r == "ramp"]
    mid = ramps[1]
    ok, ups = B.wagon_fits_at(*mid)
    assert ok, [dict(b) for b in ups.values()]
    assert {(u.x, u.y, u.z) for u in ups.values()} == {mouth(d, 0, v) for v in (-1, 0, 1)}, \
        [(u.x, u.y, u.z) for u in ups.values()]
    # from the depot's middle, the whole way out (the direction DFHack walks it)
    res = B.wagon_reaches_edge(B.wagon_lookup(), LUA.table_from([LUA.table_from(
        {"x": d.depot.x, "y": d.depot.y, "z": d.depot.z})]), 1, None, None)
    assert res.reached, dict(res)
    # a ramp row 2 wide: the wagon can't leave the ramp for the road's floor
    W.set(*ramps[2], LUA.table_from({"shape": "WALL"}))
    res = B.wagon_reaches_edge(B.wagon_lookup(), LUA.table_from([LUA.table_from(
        {"x": d.depot.x, "y": d.depot.y, "z": d.depot.z})]), 1, None, None)
    assert not res.reached and not res.cut, dict(res)


@test("built, the game says no: the AI's check names the first thing in the way and clears trees, boulders, undug tiles and doors on its road")
def _():
    reset()
    d = dig_and_build(acc=0)
    s = status()
    assert s.depot == "built" and s.wagon_access is False and s.wagon_check == "clear", dict(s)
    assert s.wagon_block is None and s.dfhack_wagon_access is None
    r = B.place_deep_depot(False)
    assert not r.ok and r.done and "nothing" in r.error, dict(r)
    # a tree grew in front of the mouth
    tx, ty, tz = mouth(d, -1, 1)
    W.set(tx, ty, tz, LUA.table_from({"shape": "WALL", "material": "TREE"}))
    s = status()
    b = s.wagon_block
    assert s.wagon_check == "blocked" and b.what == "a tree" and (b.x, b.y, b.elevation) == (tx, ty, tz), dict(b)
    assert b.fix == "fell" and "in front of the depot road's mouth" in b.text, b.text
    r = B.place_deep_depot(False)
    assert r.ok and r.fixed == "fell" and r.marked == 1, dict(r)
    assert [tuple(f.values()) for f in G.FELLED.values()] == [(tx, ty, tz)]
    s = status()
    assert s.wagon_block.pending, dict(s.wagon_block)
    w = B.place_deep_depot(False)
    assert not w.ok and w.waiting and "being cleared" in w.error, dict(w)
    W.set(tx, ty, tz, LUA.table_from({"shape": "FLOOR", "material": "SOIL", "designated": False}))
    # a boulder on the road's floor
    floor = [(x, y, z) for x, y, z, r in plan_tiles() if r == "d"][0]
    W.set(*floor, LUA.table_from({"shape": "BOULDER"}))
    s = status()
    assert s.wagon_block.what == "a boulder" and s.wagon_block.fix == "smooth", dict(s.wagon_block)
    r = B.place_deep_depot(False)
    assert r.ok and r.fixed == "smooth" and W.get(*floor).smoothing, dict(r)
    W.set(*floor, LUA.table_from({"shape": "FLOOR", "smoothing": False}))
    # a ramp left as rock: dug again
    ramp = [(x, y, z) for x, y, z, r in plan_tiles() if r == "ramp"][0]
    W.set(*ramp, LUA.table_from({"shape": "WALL"}))
    s = status()
    assert "so the ramp row is 2 wide" in s.wagon_block.text and s.wagon_block.fix == "redig", dict(s.wagon_block)
    r = B.place_deep_depot(False)
    assert r.ok and r.fixed == "redig" and W.get(*ramp).dig_text == "r", (dict(r), W.get(*ramp).dig_text)
    W.set(*ramp, LUA.table_from({"shape": "RAMP", "designated": False}))
    # a door on the road (the gates' kind): taken down
    setb(*floor, {"occ": "Dynamic", "kind": "Door", "id": 77})
    s = status()
    assert s.wagon_block.what == "a door" and s.wagon_block.fix == "remove", dict(s.wagon_block)
    assert f"x{floor[0]} y{floor[1]} elevation {floor[2]} on the depot road" in s.wagon_block.text, s.wagon_block.text
    r = B.place_deep_depot(False)
    assert r.ok and r.fixed == "remove" and list(G.REMOVED.values()) == [77], dict(r)
    assert status().wagon_block.pending                  # (once: its deconstruction is ordered)
    G.WAGON_BLD = LUA.table()
    # a hatch over the ramp's top: wagons can't go down under it
    top = [(x, y, z) for x, y, z, r in plan_tiles() if r == "h"][1]
    setb(*top, {"occ": "Dynamic", "kind": "Hatch", "closed": True, "id": 78})
    s = status()
    assert s.wagon_block.what == "a hatch over the ramp" and s.wagon_block.fix == "remove", dict(s.wagon_block)
    G.WAGON_BLD = LUA.table()
    # the depot itself is floor to a wagon
    setb(d.depot.x, d.depot.y, d.depot.z, {"occ": "Floored", "kind": "TradeDepot", "id": 9})
    assert status().wagon_check == "clear"


@test("what the AI can't clear: a Needs you naming the tile (a ramp turned floor, a wall on the surface, a door when the hall opens into the fort)")
def _():
    reset()
    d = dig_and_build(acc=0)
    ramp = [(x, y, z) for x, y, z, r in plan_tiles() if r == "ramp"][2]
    W.set(*ramp, LUA.table_from({"shape": "FLOOR"}))
    s = status()
    assert s.wagon_block.fix is None and "is floor, so the ramp row is 2 wide" in s.wagon_block.text, dict(s.wagon_block)
    r = B.place_deep_depot(False)
    assert not r.ok and r.needs_you and f"x{ramp[0]} y{ramp[1]}" in r.error, dict(r)
    W.set(*ramp, LUA.table_from({"shape": "RAMP"}))
    # rock all round the surface past 5 tiles of the mouth: no way to the edge, nothing to fell
    sx, sy, sz = d.start.x, d.start.y, d.start.z
    LUA.eval("""function(W, sx, sy, sz)
      for x = 0, 119 do for y = 0, 119 do
        if math.max(math.abs(x - sx), math.abs(y - sy)) == 6 then W.set(x, y, sz, {shape='WALL', material='STONE', outside=false}) end
      end end
    end""")(W, sx, sy, sz)
    s = status()
    assert s.wagon_check == "blocked" and s.wagon_block.what == "rock" and s.wagon_block.fix is None, dict(s.wagon_block)
    assert "map's edge" in s.wagon_block.text, s.wagon_block.text
    # the same ring of trees: felled, a few a call, nearest the edge first
    LUA.eval("""function(W, sx, sy, sz)
      for x = 0, 119 do for y = 0, 119 do
        if math.max(math.abs(x - sx), math.abs(y - sy)) == 6 then W.set(x, y, sz, {shape='WALL', material='TREE'}) end
      end end
    end""")(W, sx, sy, sz)
    s = status()
    assert s.wagon_block.what == "a tree" and s.wagon_block.fix == "fell", dict(s.wagon_block)
    r = B.place_deep_depot(False)
    assert r.ok and r.fixed == "fell" and 1 <= r.marked <= B.DEEP_FIX_MAX, dict(r)
    # the hall opens into the fort: a door on the road may be the fort's gate (not the AI's to take)
    reset()
    d = dig_and_build(acc=0)
    hall = [(x, y, z) for x, y, z, r in plan_tiles() if r == "d"][-1]
    LUA.eval("""function(W, x, y, z)
      for dx = -1, 1 do for dy = -1, 1 do
        local t = W.get(x + dx, y + dy, z); if t.shape == 'WALL' then W.set(x + dx, y + dy, z, {shape = 'FLOOR'}) end
      end end
    end""")(W, *hall)
    floor = [(x, y, z) for x, y, z, r in plan_tiles() if r == "d"][0]
    setb(*floor, {"occ": "Dynamic", "kind": "Door", "id": 80})
    s = status()
    assert s.opens_fort is not None and s.wagon_block.what == "a door" and s.wagon_block.fix is None, \
        (dict(s.opens_fort or {}), dict(s.wagon_block))
    r = B.place_deep_depot(False)
    assert not r.ok and r.needs_you and list(G.REMOVED.values()) == [], dict(r)


@test("when the game (or DFHack's own check) says the wagons get there: no check, nothing done; with nothing changed the depot reads as before")
def _():
    reset()
    dig_and_build(acc=1)
    s = status()
    assert s.wagon_access is True and s.wagon_check is None and s.dfhack_wagon_access is None, dict(s)
    r = B.place_deep_depot(False)
    assert not r.ok and r.done and r.wagon_access is True and r.wagon_check is None, dict(r)
    # DFHack's pathable plugin says yes: believed (no fix on the AI's guess)
    reset()
    d = dig_and_build(acc=0)
    W.set(*mouth(d, -1, 0), LUA.table_from({"shape": "WALL", "material": "TREE"}))
    B.dfhack_wagon_access = lambda: True
    try:
        s = status()
        assert s.dfhack_wagon_access is True and s.wagon_check is None, dict(s)
        r = B.place_deep_depot(False)
        assert not r.ok and r.done and len(G.FELLED) == 0, dict(r)
    finally:
        LUA.eval("function(B) B.dfhack_wagon_access = function() return nil end end")(B)


@test("the keep's court never goes up in front of the depot road's mouth")
def _():
    reset()
    d = dig_and_build(acc=1)
    anchors = LUA.table_from([LUA.table_from({"x": 60, "y": 60, "z": 80})])
    mouth_tiles = [(t.x, t.y) for t in B.deep_depot_mouth().values()]

    def over(c):
        return any(abs(x - c.x) <= c.r + 1 and abs(y - c.y) <= c.r + 1 for x, y in mouth_tiles)

    court = B.find_keep_court(anchors)
    assert court and not over(court), dict(court or {})
    # (without the rule, the nearest court would stand in front of the mouth on this map)
    real = B.deep_depot_mouth
    B.deep_depot_mouth = lambda: None
    try:
        assert over(B.find_keep_court(anchors))
    finally:
        B.deep_depot_mouth = real


# --- the gates ----------------------------------------------------------------

GL = LuaRuntime(unpack_returned_tuples=True)
M, GW = GL.execute(_harness("test_gates.py"), module_src("ai-gates.lua"))

# the fort on the right, outside on the left; a 3-wide tunnel at y=5-7 (the
# depot road, when marked) and a 1-wide one at y=2
ROWS = [
    "##############################",
    "##############################",
    "oooo..........................",
    "oooo#####.....................",
    "oooo#####.....................",
    "oooo..........................",
    "oooo..........................",
    "oooo..........................",
    "oooo#####.....................",
    "##############################",
]


def gsetup(road=()):
    level = GL.table()
    for y, r in enumerate(ROWS):
        level[y] = r
    m = GL.table()
    m[0] = level
    GW.map = m
    GW.buildings = GL.table()
    keys = GL.table()
    for x, y in road:
        keys[(0 * 4096 + y) * 4096 + x] = True
    M.deep_road_keys = lambda *a: keys


def gfind():
    starts = GL.table_from({1: GL.table_from({"x": 20, "y": 5, "z": 0})})
    es, _, _ = M.find_entrances(starts, GW.buildings)
    return [es[i] for i in range(1, len(es) + 1)]


@test("gates: no door spots on the depot's wagon road, and it's marked; elsewhere nothing changes")
def _():
    gsetup()
    es = gfind()
    three = [e for e in es if e.width == 3][0]
    assert three.deep_road is None and len(three.door_spots) == 0      # (3 wide, the middle has no wall: as before)
    one = [e for e in es if e.width == 1][0]
    assert len(one.door_spots) == 1 and one.deep_road is None
    gsetup(road=[(4, 5), (4, 6), (4, 7), (3, 5), (3, 6), (3, 7)])
    es = gfind()
    three = [e for e in es if e.width == 3][0]
    assert three.deep_road is True and len(three.door_spots) == 0
    one = [e for e in es if e.width == 1][0]
    assert one.deep_road is None and len(one.door_spots) == 1


@test("gates: the wagon style is a 3-wide drawbridge across the road, never doors")
def _():
    gsetup(road=[(4, 5), (4, 6), (4, 7)])
    es = gfind()
    three = [e for e in es if e.width == 3][0]
    starts = GL.table_from({1: GL.table_from({"x": 20, "y": 5, "z": 0})})
    plan = M.plan_gate(three, "wagon", starts, GL.table())
    assert plan and plan.bridge, plan
    assert plan.bridge.w * plan.bridge.h == 3 and len(plan.doors) == 0 and len(plan.walls) == 0, dict(plan.bridge)
    # the drawbridge style as before: 2 wide, a wall beside it
    plan2 = M.plan_gate(three, "drawbridge", starts, GL.table())
    assert plan2.bridge.w * plan2.bridge.h == 2 and len(plan2.walls) == 1


@test("gates: no gatehouse wall goes on the depot road or in front of its mouth")
def _():
    rows = ["o" * 30 for _ in range(19)]
    gsetup()
    level = GL.table()
    for y, r in enumerate(rows):
        level[y] = r
    m = GL.table()
    m[0] = level
    GW.map = m
    M.fort_starts(GL.table())                      # (fresh map caches)
    h = GL.table_from({"x": 15, "y": 9, "z": 0})
    e = GL.table_from({"inside_list": GL.table(), "equipment": GL.table()})
    plan = M.plan_gatehouse(e, h)
    assert not isinstance(plan, tuple) and plan.bridge, plan
    keys = GL.table()
    for x in range(5, 26):
        for y in range(0, 19):
            keys[(0 * 4096 + y) * 4096 + x] = True
    M.deep_road_keys = lambda *a: keys
    M.fort_starts(GL.table())
    plan, why = M.plan_gatehouse(e, h)
    assert plan is None and "wagon road" in why, (plan, why)


# --- the brain ----------------------------------------------------------------

from planner import _deep_depot_watch, NEEDS_YOU  # noqa: E402


def fort(dd):
    return {"buildings": {"deep_depot": dict({"stage": "placed", "depot": "built", "x": 114, "y": 160,
                                              "elevation": 41, "levels": 1, "road": 12}, **dd)}}


@test("brain: a block the AI can clear is a deep_depot step; one it can't is a Needs you naming the tile")
def _():
    blk = {"x": 112, "y": 150, "elevation": 42, "what": "a tree", "fix": "fell",
           "text": "a tree at x112 y150 elevation 42, in front of the depot road's mouth"}
    notes, props = [], []
    _deep_depot_watch(fort({"wagon_access": False, "wagon_check": "blocked", "wagon_block": blk}), notes, props)
    assert notes == [] and len(props) == 1 and props[0].action == {"type": "deep_depot"}, (notes, props)
    assert "x112 y150" in props[0].reason and "fell" in props[0].reason, props[0].reason
    # being cleared: a note, nothing new
    notes, props = [], []
    _deep_depot_watch(fort({"wagon_access": False, "wagon_check": "blocked", "wagon_block": dict(blk, pending=True)}),
                      notes, props)
    assert props == [] and "being cleared" in notes[0], notes
    # not the AI's to clear
    wall = {"x": 100, "y": 150, "elevation": 42, "what": "rock", "fix": None,
            "text": "rock at x100 y150 elevation 42, on the wagons' way from the depot road's mouth (x112 y152) "
                    "to the map's edge (no 3-wide way past it)"}
    notes, props = [], []
    _deep_depot_watch(fort({"wagon_access": False, "wagon_check": "blocked", "wagon_block": wall}), notes, props)
    assert props == [] and len(notes) == 1 and notes[0].startswith(NEEDS_YOU) and "x100 y150 elevation 42" in notes[0], notes
    # the AI finds nothing: a Needs you that says so (and what else keeps wagons away)
    notes = []
    _deep_depot_watch(fort({"wagon_access": False, "wagon_check": "clear"}), notes, [])
    assert notes[0].startswith(NEEDS_YOU) and "finds nothing" in notes[0] and "landholder" in notes[0], notes
    # DFHack's own check says yes: open the depot's sheet
    notes = []
    _deep_depot_watch(fort({"wagon_access": False, "dfhack_wagon_access": True}), notes, [])
    assert "DFHack's own wagon check" in notes[0], notes
    # the game says yes, or the depot isn't built: nothing, as before
    for dd in ({"wagon_access": True}, {"depot": "building", "wagon_access": False}, {"wagon_access": None}):
        notes, props = [], []
        _deep_depot_watch(fort(dd), notes, props)
        assert notes == [] and props == [], (dd, notes, props)
    # an old call with no proposals list: a Needs you rather than nothing
    notes = []
    _deep_depot_watch(fort({"wagon_access": False, "wagon_check": "blocked", "wagon_block": blk}), notes)
    assert notes[0].startswith(NEEDS_YOU) and "x112 y150" in notes[0], notes


@test("brain: an entrance on the depot's wagon road is gated with the wagon style (a drawbridge), never doors; others as before")
def _():
    import copy
    import json
    from planner import plan, Memory
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    base["date"]["season"] = "spring"

    def fortified(**e):
        s = copy.deepcopy(base)
        now = s["date"]["year"] * 403200 + s["date"]["tick"]
        s["entrances"] = {"scanned": True, "scanned_tick": now - 1200, "armed": False,
                          "entrances": [dict({"id": 1, "kind": "surface", "x": 40, "y": 50, "z": 173, "width": 3,
                                              "sealed": False, "equipment": [], "door_spots": 0}, **e)]}
        got, _ = plan(s, Memory())
        return [p for p in got if p.rule == "fortify"]

    road = fortified(deep_road=True)
    assert len(road) == 1 and road[0].action["style"] == "wagon" and "drawbridge" in road[0].reason, \
        [(p.action, p.reason) for p in road]
    other = fortified()
    assert len(other) == 1 and other[0].action["style"] != "wagon", [p.action for p in other]


if __name__ == "__main__":
    finish()
