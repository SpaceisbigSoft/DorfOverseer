"""(0.105.30, construction G1) The surface hall (lua/ai-builder-halls.lua) and
the keep's roof stair and ways in (lua/ai-builder-surface.lua), on
test_builder's fake fort (its harness is read from that file by ast, not
copied). Needs lupa.

    python tests/test_halls.py
"""

from __future__ import annotations

import ast
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

_tree = ast.parse((ROOT / "tests" / "test_builder.py").read_text(encoding="utf-8"))
HARNESS = next(n.value.value for n in _tree.body
               if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "HARNESS")


def boot():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(ROOT / "lua")
    layouts = (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8")
    builder = (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8")
    B, W = lua.execute(HARNESS, layouts, builder)
    return lua, B, W


LUA, B, W = boot()
LUA.execute("""
  df = df or {}
  df.global = df.global or {}
  df.global.world = df.global.world or {}
  df.global.world.buildings = {other = {TRADE_DEPOT = {}}}
""")
REAL = {k: B[k] for k in ("surface_farm_spots", "walk_group", "pasture_anchors", "fell_tree",
                          "hall_planned_at", "hall_free_items")}
T = LUA.table_from


def _reset():
    W.reset()
    for k, v in REAL.items():
        B[k] = v
    B.ROOF_STAIR = True
    B.surface_farm_spots = LUA.eval("function() return {} end")
    B.hall_planned_at = LUA.eval("function(x, y, z) local t = W_PEEK(x, y, z); return t ~= nil and t.planned == true end")
    B.hall_free_items = LUA.eval("function(name) return FREE[name] or 0 end")
    LUA.execute("FREE = {}")
    LUA.execute("df.global.world.buildings = {other = {TRADE_DEPOT = {}}}")


LUA.globals().W_PEEK = W.peek
test = make_test(before=_reset)


def field(x1, y1, x2, y2, z=80, material="SOIL"):
    """Open flat ground under the sky (the keep test's soil field)."""
    for x in range(x1, x2 + 1):
        for y in range(y1, y2 + 1):
            if (x, y) != (60, 60):
                W.set(x, y, z, T({"shape": "FLOOR", "material": material, "outside": True}))
            W.set(x, y, z + 1, T({"shape": "EMPTY", "outside": True}))


def placed(mode=None, text=None):
    return [c for c in W.placed.values() if (mode is None or c.mode == mode) and (text is None or c.text == text)]


def rect_dist(h, x, y):
    return max(max(h.x1 - x, x - h.x2, 0), max(h.y1 - y, y - h.y2, 0))


def opts(**kw):
    return T(kw)


def build_all(z, texts, shape=None, material="CONSTRUCTION"):
    """The planned cells of these kinds at z: first as buildings, then built."""
    cells = [c for c in placed("build") if c.z == z and c.text in texts]
    for c in cells:
        f = {"building": False}
        if shape:
            f.update({"shape": shape(c.text), "material": material})
        W.set(c.x, c.y, z, T(f))
    return cells


def plan_all(z, texts):
    cells = [c for c in placed("build") if c.z == z and c.text in texts]
    for c in cells:
        W.set(c.x, c.y, z, T({"building": True}))
    return cells


SHAPE = {"Cw": "WALL", "Cf": "FLOOR", "Cu": "STAIR_UP", "Cd": "STAIR_DOWN"}


@test("hall: the full stage walk on a soil field: walls, door and windows; floor and stair; roof at z+1; furniture; zone")
def _():
    field(40, 40, 80, 80)
    LUA.execute("FREE = {WINDOW = 10, STATUE = 1}")
    o = opts(windows=True, floor=True, statue=True)
    d = B.place_hall("field_hall", True, o)
    assert d.ok and d.dry_run and d.stage == "walls", dict(d)
    assert len(placed()) == 0 and not W.persist["ai-overseer/halls"], "the dry run placed nothing"
    r = B.place_hall("field_hall", False, o)
    assert r.ok and r.stage == "walls", dict(r)
    h = B.halls_status()
    assert (h.x2 - h.x1 + 1) * (h.y2 - h.y1 + 1) == 63 and h.stage == "walls", dict(h)
    assert rect_dist(h, 60, 60) > 3, "the way in kept clear"
    walls, doors, wins = placed("build", "Cw"), placed("build", "d"), placed("build", "y")
    assert len(walls) + len(doors) + len(wins) == 28 and len(doors) == 1 and 1 <= len(wins) <= 4, \
        (len(walls), len(doors), len(wins))
    door = doors[0]
    for w in wins:
        assert abs(w.x - door.x) + abs(w.y - door.y) > 1, "no window beside the door"
        assert w.x not in (h.x1, h.x2) or w.y not in (h.y1, h.y2), "no window on a corner"
    # the door: mid-side, on the side facing the way in (60, 60)
    mx, my = (h.x1 + h.x2) // 2, (h.y1 + h.y2) // 2
    mids = [(mx, h.y1 - 1), (mx, h.y2 + 1), (h.x1 - 1, my), (h.x2 + 1, my)]
    dd = {m: max(abs(m[0] - 60), abs(m[1] - 60)) for m in mids}
    out = (door.x + (door.x == h.x2) - (door.x == h.x1), door.y + (door.y == h.y2) - (door.y == h.y1))
    assert (door.x, door.y) in ((mx, h.y1), (mx, h.y2), (h.x1, my), (h.x2, my)) and dd[out] == min(dd.values()), \
        ((door.x, door.y), dd)
    plan_all(80, ("Cw",))
    w = B.place_hall("field_hall", False, o)
    assert not w.ok and w.waiting and w.stage == "walls", dict(w)
    assert B.halls_status().walls_planned == len(walls)
    build_all(80, ("Cw",), SHAPE.get)
    W.placed = T([])
    f = B.place_hall("field_hall", False, o)
    assert f.ok and f.stage == "floor" and f.stair, dict(f)
    floors, stairs = placed("build", "Cf"), placed("build", "Cu")
    assert len(floors) == 34 and len(stairs) == 1, (len(floors), len(stairs))
    st = stairs[0]
    assert h.x1 < st.x < h.x2 and h.y1 < st.y < h.y2 and st.x in (h.x1 + 1, h.x2 - 1) and st.y in (h.y1 + 1, h.y2 - 1)
    plan_all(80, ("Cf", "Cu"))
    assert B.place_hall("field_hall", False, o).waiting
    build_all(80, ("Cf", "Cu"), SHAPE.get)
    W.placed = T([])
    r = B.place_hall("field_hall", False, o)
    assert r.ok and r.stage == "roof" and r.stair, dict(r)
    roof = placed("build")
    assert all(c.z == 81 for c in roof), "the roof at z+1 only"
    assert len([c for c in roof if c.text == "Cd"]) == 1 and len(roof) == 35 + len(wins), (len(roof), len(wins))
    for w in wins:
        assert any(c.x == w.x and c.y == w.y for c in roof), "a roof tile over each window"
    plan_all(81, ("Cf", "Cd"))
    assert B.halls_status().roof_planned == len(roof)
    assert B.place_hall("field_hall", False, o).waiting
    build_all(81, ("Cf", "Cd"), SHAPE.get)
    W.placed = T([])
    fu = B.place_hall("field_hall", False, o)
    assert fu.ok and fu.stage == "furnish" and fu.tables == 3 and fu.statue, dict(fu)
    furn = placed("build")
    assert sorted(c.text for c in furn) == ["c", "c", "c", "s", "t", "t", "t"], [c.text for c in furn]
    assert not any(c.x == st.x and c.y == st.y for c in furn), "nothing on the stair"
    for c in furn:
        W.set(c.x, c.y, 80, T({"building": True, "planned": True}))
    assert B.place_hall("field_hall", False, o).waiting
    for c in furn:
        W.set(c.x, c.y, 80, T({"planned": False}))
    W.placed = T([])
    z = B.place_hall("field_hall", False, o)
    assert z.ok and z.stage == "zone" and z.done, dict(z)
    zones = placed("zone")
    assert len(zones) == 1 and zones[0].text in ("h(7x5)", "h(5x7)") and (zones[0].x, zones[0].y) == (h.x1 + 1, h.y1 + 1)
    assert B.halls_status().stage == "done"
    e = B.place_hall("field_hall", False, o)
    assert not e.ok and e.done, dict(e)
    e = B.place_hall("market_hall", False, o)
    assert not e.ok and e.rejected, "one hall a fort"
    rec = W.persist["ai-overseer/halls"].list[1]
    assert len(rec.tiles) == 28 + 35 + 35 + len(wins) + 7, len(rec.tiles)     # every tile on record


@test("hall: no windows, floor or statue unless asked (and windows only as many as lie free); no stair with ROOF_STAIR off")
def _():
    field(40, 40, 80, 80)
    B.ROOF_STAIR = False
    r = B.place_hall("field_hall", False)
    assert r.ok and r.stage == "walls" and r.windows == 0, dict(r)
    assert len(placed("build", "Cw")) == 27 and not placed("build", "y")
    build_all(80, ("Cw",), SHAPE.get)
    f = B.place_hall("field_hall", False)
    assert f.ok and f.stage == "floor" and not f.stair and f.floor == 0, dict(f)
    r = B.place_hall("field_hall", False)
    assert r.ok and r.stage == "roof" and len(placed("build", "Cd")) == 0 and len(placed("build", "Cf")) == 35, dict(r)
    _reset()
    field(40, 40, 80, 80)
    LUA.execute("FREE = {WINDOW = 1}")
    r = B.place_hall("field_hall", False, opts(windows=True))
    assert r.ok and r.windows == 1 and len(placed("build", "y")) == 1, dict(r)


def _tight():
    """A field exactly the footprint, east of the way in; fort floors round it."""
    field(66, 57, 74, 63)
    return (66, 57, 74, 63)


@test("hall: trees in the footprint felled first, then the walls")
def _():
    _tight()
    site = B.find_hall_site("field_hall")
    W.set(site.x1 + 2, site.y1 + 2, 80, T({"shape": "WALL", "material": "TREE", "outside": True}))
    W.set(site.x1 + 2, site.y1 + 2, 81, T({"shape": "WALL", "material": "TREE", "outside": True}))
    felled = []
    B.fell_tree = lambda x, y, z: felled.append((x, y)) or True
    c = B.place_hall("field_hall", False)
    assert c.ok and c.clearing and c.trees == 1 and felled == [(site.x1 + 2, site.y1 + 2)], dict(c)
    w = B.place_hall("field_hall", False)
    assert not w.ok and w.waiting and "felling" in w.error, dict(w)
    W.set(site.x1 + 2, site.y1 + 2, 80, T({"shape": "FLOOR", "material": "SOIL"}))
    r = B.place_hall("field_hall", False)
    assert r.ok and r.stage == "walls", dict(r)


@test("hall: refused with water within 2, a zone, a slope, a channel nearby (the deep depot's too)")
def _():
    _tight()
    s = B.find_hall_site("field_hall")
    assert s and (s.x1, s.y1, s.x2, s.y2) == (66, 57, 74, 63), s
    W.set(76, 60, 80, T({"liquid": True}))                       # 2 east of the wall
    s, why = B.find_hall_site("field_hall")
    assert s is None and "water" in why, why
    W.set(76, 60, 80, T({"liquid": False}))
    W.set(70, 60, 80, T({"taken": True}))                        # a zone inside
    s, why = B.find_hall_site("field_hall")
    assert s is None, why
    W.set(70, 60, 80, T({"taken": False, "shape": "RAMP"}))       # a slope inside
    s, why = B.find_hall_site("field_hall")
    assert s is None, why
    W.set(70, 60, 80, T({"shape": "FLOOR"}))
    W.set(70, 65, 80, T({"shape": "EMPTY"}))                     # a channel 2 south
    s, why = B.find_hall_site("field_hall")
    assert s is None and "channel" in why, why
    W.set(70, 65, 80, T({"shape": "FLOOR"}))
    assert B.find_hall_site("field_hall")
    W.persist["ai-overseer/deep_depot"] = T({"stage": "digging", "tiles": T([T({"x": 76, "y": 58, "z": 80, "r": "h"})])})
    s, why = B.find_hall_site("field_hall")
    assert s is None and "channel" in why, why


@test("hall: never too near the way in, never with the depot inside or on the wagons' strip to the map's edge")
def _():
    field(40, 40, 80, 80)
    for _ in range(2):
        s = B.find_hall_site("field_hall")
        assert rect_dist(s, 60, 60) > 3, (s.x1, s.y1)
    # a depot on the field, the map's west edge nearest it: its strip runs west
    LUA.execute("df.global.world.buildings = {other = {TRADE_DEPOT = {{x1 = 46, x2 = 50, y1 = 66, y2 = 70, z = 80}}}}")
    for x in range(10, 50):
        for y in range(64, 73):
            W.set(x, y, 80, T({"shape": "FLOOR", "material": "SOIL", "outside": True}))
            W.set(x, y, 81, T({"shape": "EMPTY", "outside": True}))
    s = B.find_hall_site("market_hall")
    assert s, "a market hall site"
    assert not (s.x1 <= 50 and s.x2 >= 46 and s.y1 <= 70 and s.y2 >= 66), "the depot inside"
    assert not (s.x2 <= 45 and s.y1 <= 71 and s.y2 >= 65), "on the wagons' strip"
    d = max(max(46 - s.x2, s.x1 - 50, 0), max(66 - s.y2, s.y1 - 70, 0))
    assert 6 <= d <= 15, d
    # a hall placed by the depot
    r = B.place_hall("market_hall", False)
    assert r.ok and r.kind == "market_hall", dict(r)


@test("hall: a market hall needs a depot under the sky; an unknown kind is refused")
def _():
    field(40, 40, 80, 80)
    s, why = B.find_hall_site("market_hall")
    assert s is None and "depot" in why, why
    r = B.place_hall("tower", False)
    assert not r.ok and r.rejected


@test("hall: the field hall goes by the surface fields; never over the keep")
def _():
    field(40, 40, 80, 80)
    B.surface_farm_spots = LUA.eval("function() return {{x = 75, y = 45, z = 80}} end")
    s = B.find_hall_site("field_hall")
    assert max(abs((s.x1 + s.x2) / 2 - 75), abs((s.y1 + s.y2) / 2 - 45)) <= 6, (s.x1, s.y1)
    W.persist["ai-overseer/keep"] = T({"x": 74, "y": 46, "z": 80, "r": 4, "stage": "walls"})
    s = B.find_hall_site("field_hall")
    gap = max(max(70 - s.x2, s.x1 - 78, 0), max(42 - s.y2, s.y1 - 50, 0))
    assert gap > 3, gap


@test("hall: dry runs place and save nothing at any stage")
def _():
    field(40, 40, 80, 80)
    assert B.place_hall("field_hall", True).ok
    assert not W.persist["ai-overseer/halls"] and len(placed()) == 0 and B.halls_status() is None
    assert B.place_hall("field_hall", False).ok
    build_all(80, ("Cw",), SHAPE.get)
    n = len(placed())
    f = B.place_hall("field_hall", True, opts(floor=True))
    assert f.ok and f.dry_run and f.stage == "floor" and len(placed()) == n, dict(f)
    assert B.halls_status().stage == "walls"


@test("hall: the status: blocks still needed, the stage, the inside under the gates' ledge")
def _():
    field(40, 40, 80, 80)
    # nothing is built unless the brain asks (no call at the defaults): no record, no tile
    assert B.halls_status() is None and B.HALL_BLOCKS_EST >= 98 and len(placed()) == 0
    assert not W.persist["ai-overseer/halls"] and not W.persist["ai-overseer/keep"]
    assert (B.HALL_W - 2) * (B.HALL_H - 2) <= B.HALL_MAX_INTERIOR <= 120
    B.place_hall("field_hall", False)
    st = B.halls_status()
    # (no floor asked for: walls, the roof and the stair)
    assert st.stage == "walls" and st.blocks_needed == 27 + 35 + 2 and st.next_blocks == 1, dict(st)
    _reset()
    field(40, 40, 80, 80)
    B.place_hall("field_hall", False, opts(floor=True))
    st = B.halls_status()
    assert st.blocks_needed == 27 + 35 + 35 + 2 and st.next_blocks == 36, dict(st)
    assert st.halls == 1 and st.kind == "field_hall"


@test("hall fuzz: on random fields no site on water, a zone, a slope, a channel within 2, the depot or by the way in")
def _():
    rng = random.Random(30)
    for _ in range(12):
        _reset()
        field(40, 40, 80, 80)
        bad = []
        for _ in range(25):
            x, y = rng.randint(40, 80), rng.randint(40, 80)
            kind = rng.choice(["liquid", "taken", "RAMP", "EMPTY"])
            f = {"liquid": True} if kind == "liquid" else {"taken": True} if kind == "taken" else {"shape": kind}
            W.set(x, y, 80, T(f))
            bad.append((x, y, kind))
        s = B.find_hall_site("field_hall")
        if not s:
            continue
        assert rect_dist(s, 60, 60) > 3
        for x, y, kind in bad:
            d = rect_dist(s, x, y)
            if kind == "taken":
                assert d > 0, (x, y, kind)
            else:
                assert d > 2, (x, y, kind, s.x1, s.y1)


# --- the keep -----------------------------------------------------------------

@test("keep (0.105.30): the roof stair: Cu in an inside corner away from the door, then the roof with a Cd over it")
def _():
    field(40, 40, 80, 80)
    B.fell_tree = lambda x, y, z: True
    r = B.place_keep(False)
    assert r.ok and r.stage == "walls" and r.r == 4, dict(r)
    door = r.door
    walls = placed("build", "Cw")
    build_all(80, ("Cw",), SHAPE.get)
    W.placed = T([])
    s = B.place_keep(False)
    assert s.ok and s.stage == "stair", dict(s)
    cu = placed("build", "Cu")
    assert len(cu) == 1 and max(abs(cu[0].x - 60), abs(cu[0].y - 60)) == 3, [dict(c) for c in cu]
    assert abs(cu[0].x - door.x) + abs(cu[0].y - door.y) >= 10, "the corner away from the door"
    plan_all(80, ("Cu",))
    st = B.keep_status()
    assert st.stage == "stair" and st.roof_planned == 1 and st.stair_planned == 1, dict(st)
    w = B.place_keep(False)
    assert not w.ok and w.waiting and w.stage == "stair", dict(w)
    build_all(80, ("Cu",), SHAPE.get)
    W.placed = T([])
    rf = B.place_keep(False)
    assert rf.ok and rf.stage == "roof" and rf.stair, dict(rf)
    roof = placed("build")
    assert len(roof) == 49 and all(c.z == 81 for c in roof), len(roof)
    assert [(c.x, c.y) for c in roof if c.text == "Cd"] == [(cu[0].x, cu[0].y)]
    plan_all(81, ("Cf", "Cd"))
    assert B.keep_status().roof_planned == 49
    build_all(81, ("Cf", "Cd"), SHAPE.get)
    assert B.place_keep(False).stage == "done"
    assert len(walls) == 31


@test("keep (0.105.30): F and C's way in: the stair's inside tile under the hatch; the ring looked for on the open ground above")
def _():
    # the gates give the way in as the stair one level under the ground (z80);
    # the open ground is at z81, round the stair's top
    W.set(60, 60, 80, T({"shape": "STAIR_UPDOWN"}))
    W.set(60, 60, 81, T({"shape": "STAIR_DOWN", "outside": True}))
    field(40, 40, 80, 80, z=81)
    W.set(60, 60, 81, T({"shape": "STAIR_DOWN", "outside": True}))
    B.pasture_anchors = LUA.eval("function() return {{x = 60, y = 60, z = 80}} end")
    B.walk_group = LUA.eval("function(x, y, z) local t = W_PEEK(x, y, z); "
                            "if t and t.shape ~= 'WALL' and z >= 60 and z <= 81 then return 1 end return 0 end")
    site, why = B.find_keep_ring(B.pasture_anchors())
    assert site is None and "no ring of open ground" in why and "rooms" in why and "x" in why, why   # named
    a = B.surface_anchors()
    assert (a[1].z, a[1].below) == (81, 80), dict(a[1])
    r = B.place_keep(True)
    assert r.ok and not r.court and r.elevation == 81 and (r.x, r.y) == (60, 60), dict(r)
    # the refuse pile keeps min_d from the way in on the ground above it too
    p = B.place_surface("refuse", True)
    assert p.ok, dict(p)
    d = max(max(p.x - 60, 60 - (p.x + 4), 0), max(p.y - 60, 60 - (p.y + 4), 0))
    assert d >= 6, (p.x, p.y, d)


@test("keep (0.105.30): a way in on the open ground itself is not moved; a stair not reaching the sky is not followed")
def _():
    a = B.surface_anchors()
    assert a[1].z == 80 and a[1].below is None, dict(a[1])      # the harness stair: top at z80, rock above
    W.set(60, 60, 81, T({"shape": "STAIR_DOWN"}))                # up into the rock (not outside)
    a = B.surface_anchors()
    assert a[1].z == 80, dict(a[1])


if __name__ == "__main__":
    finish()
