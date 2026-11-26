"""(layout B, group B16) The hallway-first floors end to end: the real modules
together for the first time.

On the fake fort of tests/test_builder.py (a real Lua engine), with the real
ai-floorplan, ai-floorplace and ai-floorunits (loaded as tests/test_layouts.py
loads a module), the real builder parts (ai-builder-floorstore, -floors,
-floorpiles: loaded by ai-builder's PARTS) and a small ai-overseer-settings
whose load_settings() answers the Rules switch floor_layout. Every level goes
through the real B.start_project. Nothing here is a stand-in of a floor
module; only ai-overseer-settings and ai-pile-links are (they are the game's).

    python tests/test_b16_floors_end_to_end.py           the tests
    python tests/test_b16_floors_end_to_end.py --show    and the floors they make, drawn

A failure's message carries the level drawn as text (brain/tools/draw_level.py's
render when it is there, a plain drawing otherwise).
"""

from __future__ import annotations

import copy
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "brain" / "tools"))
from harness import finish, have_lua, make_test, skip  # noqa: E402

try:                                   # an ASCII drawing, when the helper is there (never depended on)
    from draw_level import render as _render  # noqa: E402
except Exception:                      # noqa: BLE001
    _render = None

SHOW = "--show" in sys.argv
if SHOW:
    sys.argv.remove("--show")

LUA = B = W = TB = E = None
if have_lua():
    import test_builder as TB  # noqa: E402  (its fake fort; its tests run only when it is run itself)
    LUA, B, W = TB.LUA, TB.B, TB.W

# The real pure modules, the settings switch and a recording ai-pile-links, answered by reqscript.
SETUP = r"""
local B, LAYOUTS, srcs = ...
local real = REAL_REQ_B16 or reqscript
REAL_REQ_B16 = real
E = {mode = 'hallway', link = nil, links = {}, tick = 0, reads = 0, counting = false}
local function load_module(src, name)
  local env = setmetatable({}, {__index = _G})
  assert(load(src, name, 't', env))()
  return env
end
local mods = {}
for name, src in pairs(srcs) do mods[name] = load_module(src, name) end
mods['ai-floorunits'].LAYOUTS = LAYOUTS
E.mods = mods
mods['ai-overseer-settings'] = {load_settings = function()
  if E.mode == 'raise' then error('no settings') end
  return {floor_layout = E.mode, link_feeders = E.link}
end}
local PL = {LINKABLE = {Masons = true, Carpenters = true, Craftsdwarfs = true}}
function PL.remember_feeder(x, y, z, shop_id, shop, flag)
  table.insert(E.links, {what = 'remember', x = x, y = y, z = z, shop_id = shop_id, shop = shop, flag = flag})
  return true
end
function PL.link_feeder(t)
  table.insert(E.links, {what = 'link', pile_id = t.pile_id})
  return {ok = true}
end
mods['ai-pile-links'] = PL
reqscript = function(name)
  local m = mods[name]
  if m then return m end
  return real(name)
end
E.real_now = B.now_tick
B.now_tick = function() return E.tick end
-- the tile reads, counted while E.counting (floors_report must read none)
E.real_peek = B.tile_info
B.tile_info = function(x, y, z)
  if E.counting then E.reads = E.reads + 1 end
  return E.real_peek(x, y, z)
end
E.real_walk = B.walk_group
return E
"""

if TB is not None:
    _srcs = {n: (ROOT / "lua" / f"{n}.lua").read_text(encoding="utf-8")
             for n in ("ai-floorplan", "ai-floorplace", "ai-floorunits")}
    E = LUA.execute(SETUP, B, LUA.globals().LAYOUTS, LUA.table_from(_srcs))

SX, SY = 60, 60          # the fake fort's main stair
ROCK_Z = 63              # a level of the main stair in solid rock (the fort's open levels are 66..80)
KEY, PKEY = "ai-overseer/floors", "ai-overseer/projects"
LIVE = ROOT / "tests" / "fixtures" / "live"
SEEN_SHOWS: list[str] = []


def _reset(mode="hallway"):
    if TB is None:
        skip("needs the lupa package (pip install lupa)")
    W.size = LUA.table_from([120, 120, 100])
    TB._reset(False)
    E.mode, E.link, E.tick, E.reads, E.counting = mode, None, 0, 0, False
    E.links = LUA.table()
    B.walk_group = E.real_walk
    B.MAX_OPEN_PROJECTS = 100        # (the cap is not what these tests are about)
    B.FLOOR_SECONDS = 30             # (2-core machines: the deadline is test 12's only)
    B.FLOOR_OLD_OPEN = True


test = make_test(before=_reset)


# --------------------------------------------------------------------------- helpers

def tbl(v):
    if isinstance(v, dict):
        return LUA.table_from({k: tbl(x) for k, x in v.items()})
    if isinstance(v, (list, tuple)):
        return LUA.table_from([tbl(x) for x in v])
    return v


def plain(v):
    """A Lua value as Python: a table with keys 1..n is a list, any other a dict."""
    if LUA.eval("type")(v) != "table":
        return v
    keys = list(v.keys())
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [plain(v[i]) for i in range(1, len(keys) + 1)]
    return {k: plain(v[k]) for k in keys}


def lua_list(t):
    return [t[i] for i in range(1, len(t) + 1)] if t is not None else []


def start(dry=False, **kw):
    r = B.start_project(tbl(kw), LUA.table_from({"year": 148, "tick": 100}), dry)
    # a floor module that raised is never what a test wants (floor_search keeps it as "failed: ...")
    assert "failed:" not in str(r.not_on_floor or ""), f"a floor module raised: {r.not_on_floor}"
    return r


def projects():
    d = W.persist[PKEY]
    return lua_list(d.list) if d is not None else []


def project(pid):
    return next(p for p in projects() if p.id == pid)


def store():
    return plain(W.persist[KEY]) if W.persist[KEY] is not None else None


def designated(z=None):
    """The designated tiles (x, y, z) (absolute)."""
    out = set()
    for k, t in W.tiles.items():
        if t.designated:
            x, y, tz = (int(n) for n in k.split(","))
            if z is None or tz == z:
                out.add((x, y, tz))
    return out


def dig_all():
    for t in W.tiles.values():
        if t.designated:
            t.shape, t.designated = "FLOOR", False


_RECT = re.compile(r"^([A-Za-z~]+?)\d*\((\d+)x(\d+)\)$")


def cell_tiles(text, x, y):
    m = _RECT.match(str(text))
    if m:
        return [(x + dx, y + dy) for dx in range(int(m.group(2))) for dy in range(int(m.group(3)))]
    return [(x, y)]


def proj_tiles(p):
    """The project's dug tiles, absolute (x, y)."""
    a = p.anchor
    out = set()
    for c in lua_list(p.cells.dig):
        if re.match(r"^d\d*(\(|$)", str(c.text)):
            out.update(cell_tiles(c.text, a.x + c.x, a.y + c.y))
    return out


def proj_links(p):
    return {(t.x + p.anchor.x, t.y + p.anchor.y) for t in lua_list(p.links)} if p.links is not None else set()


def draw(z, sx=SX, sy=SY, title=None, box=None, extra_marks=None):
    """The level z of the fake world as text, stair-relative: dug or designated tiles, the stair,
    the AI's doors, furniture, piles and shops (from the projects' cells)."""
    cells, marks = set(), []
    for k, t in W.tiles.items():
        x, y, tz = (int(n) for n in k.split(","))
        if tz == z and (t.designated or (t.shape != "WALL" and not str(t.shape).startswith("STAIR"))):
            cells.add((x - sx, y - sy))
    for p in projects():
        if p.z != z or p.cells is None:
            continue
        a = p.anchor
        for ph in ("build", "place"):
            for c in lua_list(p.cells[ph]):
                m = _RECT.match(str(c.text))
                x, y = a.x + c.x - sx, a.y + c.y - sy
                if m:
                    marks.append({"x": x, "y": y, "label": f"{m.group(1)} ({ph})",
                                  "w": int(m.group(2)), "h": int(m.group(3))})
                else:
                    marks.append((x, y, f"{c.text} ({ph})"))
    for m in extra_marks or []:
        marks.append(m)
    if box:
        x1, y1, x2, y2 = box
        cells = {c for c in cells if x1 <= c[0] <= x2 and y1 <= c[1] <= y2}

        def inside(m):
            x, y = (m["x"], m["y"]) if isinstance(m, dict) else (m[0], m[1])
            return x1 <= x <= x2 and y1 <= y <= y2
        marks = [m for m in marks if inside(m)]
    if _render is not None:
        try:
            return _render({"cells": sorted(cells), "marks": marks, "stair": (0, 0), "title": title})
        except Exception:      # noqa: BLE001
            pass
    if not cells:
        return (title or "") + "\n(nothing dug)"
    xs, ys = [c[0] for c in cells] + [0], [c[1] for c in cells] + [0]
    lines = [title or ""]
    for y in range(min(ys) - 1, max(ys) + 2):
        lines.append("".join("X" if (x, y) == (0, 0) else ("." if (x, y) in cells else "#")
                             for x in range(min(xs) - 1, max(xs) + 2)))
    return "\n".join(lines)


def show(title, z, sx=SX, sy=SY, box=None):
    text = draw(z, sx, sy, title=title, box=box)
    SEEN_SHOWS.append(text)
    if SHOW:
        print(text)
        print()
    return text


def neighbours8(x, y):
    return [(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]


def check_floor(z, sx=SX, sy=SY, what=""):
    """The floor invariants on level z: every room touches a hall; no two projects share a tile;
    nothing is dug within one tile of another project's room (but a room's opening on a hall);
    the stair tile is never designated; check_site's rules hold for every designated tile."""
    pic = lambda: draw(z, sx, sy, title=what)      # noqa: E731
    floor_ps = [p for p in projects() if p.z == z and p.floor is not None and p.phase != "cancelled"]
    tiles = {p.id: proj_tiles(p) for p in floor_ps}
    halls = {p.id: proj_links(p) for p in floor_ps}
    all_hall = set().union(*halls.values()) if halls else set()
    all_hall |= {(sx + dx, sy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    # the floor's own record: its runs' hall tiles (the walked ones too)
    st = store()
    for f in (st or {}).get("floors", []):
        if f.get("z") == z and f.get("stair", {}).get("x") == sx and f.get("stair", {}).get("y") == sy:
            for r in f.get("runs", []):
                px, py = -r["dy"], r["dx"]
                u0 = 3 if r.get("node") == 5 else 2
                for u in range(u0, u0 + r.get("len", 0)):
                    for v in (-1, 0, 1):
                        all_hall.add((sx + r["ox"] + u * r["dx"] + v * px, sy + r["oy"] + u * r["dy"] + v * py))
                if r.get("node") == 5 and r.get("parent"):
                    for du in range(-2, 3):
                        for dv in range(-2, 3):
                            all_hall.add((sx + r["ox"] + du, sy + r["oy"] + dv))
    rooms = {pid: tiles[pid] - halls[pid] for pid in tiles}
    for a in floor_ps:
        for b in floor_ps:
            if a.id >= b.id:
                continue
            both = tiles[a.id] & tiles[b.id]
            assert not both, f"{what}: projects {a.id} and {b.id} share {sorted(both)[:4]}\n{pic()}"
    for a in floor_ps:
        ra = rooms[a.id]
        opening = {t for t in ra if any((t[0] + d[0], t[1] + d[1]) in all_hall for d in ((1, 0), (-1, 0), (0, 1), (0, -1)))}
        for b in floor_ps:
            if a.id == b.id:
                continue
            for t in tiles[b.id]:
                near = [n for n in neighbours8(*t) if n in ra]
                if not near:
                    continue
                if t in halls[b.id] and all(n in opening for n in near):
                    continue        # a room's opening on a hall another project dug
                raise AssertionError(f"{what}: project {b.id} digs {t} beside project {a.id}'s room {near}\n{pic()}")
        # every room (a 4-connected group of room tiles) touches the hall
        left = set(ra)
        while left:
            seed = left.pop()
            group, todo = {seed}, [seed]
            while todo:
                x, y = todo.pop()
                for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if n in left:
                        left.discard(n)
                        group.add(n)
                        todo.append(n)
            assert any((x + d[0], y + d[1]) in all_hall for x, y in group
                       for d in ((1, 0), (-1, 0), (0, 1), (0, -1))), \
                f"{what}: a room of project {a.id} at {sorted(group)[:3]} has no opening on the hall\n{pic()}"
    t = W.peek(sx, sy, z)
    assert not (t.designated and str(t.dig_text or "").startswith("d")), f"{what}: the stair tile is dug\n{pic()}"
    w, h = int(W.size[1]), int(W.size[2])
    for (x, y, tz) in designated(z):
        t = W.peek(x, y, tz)
        bad = [k for k in ("aquifer", "liquid", "feature", "outside") if t[k]]
        up = W.peek(x, y, tz + 1)
        if up is not None and (up.aquifer or up.liquid):
            bad.append("water or aquifer above")
        if x <= 1 or y <= 1 or x >= w - 2 or y >= h - 2:
            bad.append("the map's edge")
        assert not bad, f"{what}: designated {x},{y},{tz}: {bad}\n{pic()}"


def floor_rec(z, sx=SX, sy=SY):
    for f in (store() or {}).get("floors", []):
        if f.get("z") == z and f.get("stair", {}).get("x") == sx and f.get("stair", {}).get("y") == sy:
            return f
    return None


# --------------------------------------------------------------------------- 1. the worked example

EXAMPLE_HINT = dict(elevs=[ROCK_Z], tag="homes", lead=2, gap=1, kind_gap=1, ahead=1, dirs=["east"],
                    sides="both", stagger=0, pile_w=5, piles_new=1)
# the contract's drawing, columns x = -3 .. 26, rows y = -7 .. 5
EXAMPLE = """\
################sssss#.....###
################sssss#.WWW.###
#######f.b#f.b##sssss#.WWW.###
#######h..#h..##sssss#.WWW.###
#######...#...##sssss#.....###
########D###D####+++###+++####
##..........................##
##.S........................##
##..........................##
########D###D#################
#######...#...################
#######h..#h..################
#######f.b#f.b################"""


def worked_example():
    r1 = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(EXAMPLE_HINT))
    assert r1.ok and r1.floor is not None, (plain(r1))
    first = designated(ROCK_Z)
    r2 = start(kind="workshops", shops=["Masons"], floor=dict(EXAMPLE_HINT))
    assert r2.ok and r2.floor is not None, plain(r2)
    return r1, r2, first


@test("1. the worked example, tile for tile: hub, hall 2..11 then 12..24, four bedrooms with doors, "
      "the stone pile and the mason's room with 3-wide openings")
def _():
    r1, r2, first = worked_example()
    f1, f2 = plain(r1.floor), plain(r2.floor)
    assert (f1["arm"], f1["side"], f1["u"], f1["hall_new"], f1["new_floor"], f1["units"]) == \
        ("east", "north", 4, 38, True, 4), f1
    assert (f2["arm"], f2["side"], f2["u"], f2["hall_new"], f2["new_floor"], f2["piles"], f2["units"]) == \
        ("east", "north", 13, 39, False, ["stone"], 2), f2
    rows = EXAMPLE.splitlines()
    pic = draw(ROCK_Z, title="the worked example")
    for j, row in enumerate(rows):
        y = j - 7
        for i, ch in enumerate(row):
            x = i - 3
            dug = W.peek(SX + x, SY + y, ROCK_Z).designated
            assert dug == (ch not in "#S"), f"tile {x},{y}: {ch!r} in the drawing, designated={dug}\n{pic}"
    # the second project digs nothing the first designated
    p1, p2 = project(r1.project_id), project(r2.project_id)
    t1, t2 = proj_tiles(p1), proj_tiles(p2)
    assert {(x, y) for x, y, _ in first} == t1 and not (t1 & t2)
    assert len(proj_links(p2)) == 39 and all(SX + 12 <= x <= SX + 24 for x, _ in proj_links(p2))
    # the doors, the furniture, the pile and the shop where the drawing has them
    marks = {}
    for p in (p1, p2):
        for ph in ("build", "place"):
            for c in lua_list(p.cells[ph]):
                for t in cell_tiles(c.text, c.x, c.y):
                    marks[t] = (ph, str(c.text))
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            x, y = i - 3, j - 7
            want = {"D": ("build", "d"), "b": ("build", "b"), "f": ("build", "f"), "h": ("build", "h"),
                    "s": ("place", "s(5x5)")}.get(ch)
            if want:
                assert marks.get((x, y)) == want, (x, y, ch, marks.get((x, y)))
    assert marks.get((21, -5)) == ("build", "wm"), "the Masons' workshop stands in the middle of its room"
    # both projects' cells pass layouts.to_data (no two cells on a tile)
    to_data = LUA.globals().LAYOUTS.to_data
    for p in (p1, p2):
        for ph in ("dig", "build", "place", "zone", "smooth", "engrave"):
            to_data(p.cells[ph], 0)
    # the record
    f = floor_rec(ROCK_Z)
    assert f["hub"] == "dug" and len(f["runs"]) == 1 and f["runs"][0]["len"] == 23, f["runs"]
    assert [(s["side"], s["u"], s["w"], s["d"], s["role"]) for s in f["slots"]] == [
        (-1, 4, 3, 3, "room"), (1, 4, 3, 3, "room"), (-1, 8, 3, 3, "room"), (1, 8, 3, 3, "room"),
        (-1, 13, 5, 5, "pile"), (-1, 19, 5, 5, "shop")], f["slots"]
    assert f["slots"][4]["flag"] == "stone"
    show("1. the worked example (z63 of the fake fort)", ROCK_Z, box=(-4, -9, 28, 7))


@test("1b. the worked example as the contract words it (no tag in the hint): the workshop's own district "
      "(industry) opens its own arm; it never shares the homes' hall while an arm can still open")
def _():
    hint = {k: v for k, v in EXAMPLE_HINT.items() if k != "tag"}
    r1 = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(hint))
    r2 = start(kind="workshops", shops=["Masons"], floor=dict(hint))
    f1, f2 = plain(r1.floor), plain(r2.floor)
    assert f1["arm"] == "east" and f2["arm"] != "east" and f2["u"] == 4, (f1, f2)
    check_floor(ROCK_Z, what="1b")


# --------------------------------------------------------------------------- 2. the lifecycle

GAME = r"""
local W, E = ...
-- buildings from what quickfort placed (W.placed): 1x1 furniture, 3x3 workshops by their centre, stockpiles
-- as their rectangle; every one built at once
df = df or {}
df.building_type = {Stockpile = 29, Civzone = 30, Workshop = 12, Furnace = 13, Bed = 1, Door = 2,
                    Cabinet = 3, Box = 4, Table = 5, Chair = 6, Statue = 7}
for k, v in pairs({}) do end
local names = {}
for k, v in pairs(df.building_type) do names[v] = k end
for v, k in pairs(names) do df.building_type[v] = k end
df.workshop_type, df.furnace_type = {}, {}
df.global = df.global or {}
df.global.world = {buildings = {all = {}, other = {STOCKPILE = {}}}}
df.global.cur_year, df.global.cur_year_tick = 148, 100
local id = 1000
local function mk(t, x1, y1, x2, y2, z, extra)
  id = id + 1
  local b = {id = id, t = t, x1 = x1, y1 = y1, x2 = x2, y2 = y2, z = z, flags = {exists = true},
             getType = function(self) return self.t end, getSubtype = function() return 0 end}
  for k, v in pairs(extra or {}) do b[k] = v end
  table.insert(df.global.world.buildings.all, b)
  if t == df.building_type.Stockpile then table.insert(df.global.world.buildings.other.STOCKPILE, b) end
  return b
end
E.build_all = function()
  df.global.world.buildings.all = {}
  df.global.world.buildings.other.STOCKPILE = {}
  for _, p in ipairs(W.placed) do
    local key, w, h = p.text:match('^(%a+)%((%d+)x(%d+)%)$')
    w, h = tonumber(w) or 1, tonumber(h) or 1
    key = key or p.text
    if p.mode == 'place' then
      mk(df.building_type.Stockpile, p.x, p.y, p.x + w - 1, p.y + h - 1, p.z)
    elseif p.mode == 'zone' then
      mk(df.building_type.Civzone, p.x, p.y, p.x + w - 1, p.y + h - 1, p.z)
    elseif p.mode == 'build' and (key:match('^w') or key:match('^e')) and #key == 2 then
      mk(df.building_type.Workshop, p.x - 1, p.y - 1, p.x + 1, p.y + 1, p.z, {key = key})
    elseif p.mode == 'build' then
      mk(df.building_type.Bed, p.x, p.y, p.x, p.y, p.z, {key = key})
    end
  end
end
E.building_at = function(x, y, z)
  for _, b in ipairs(df.global.world.buildings.all) do
    if b.z == z and x >= b.x1 and x <= b.x2 and y >= b.y1 and y <= b.y2 and b.t ~= df.building_type.Stockpile
        and b.t ~= df.building_type.Civzone then return b end
  end
end
E.game_off = function() df.global = nil; df.building_type = nil; df.workshop_type = nil; df.furnace_type = nil end
"""


@test("2. the lifecycle: dug, furnished and finished, each counting its own buildings; the stone pile "
      "booked as the mason's feeder and linked; the hall tiles are each project's links")
def _():
    r1, r2, _ = worked_example()
    LUA.execute(GAME, W, E)
    try:
        dig_all()
        B.floor_building_at = E.building_at
        B.floor_stockpiles = LUA.eval("function() return df.global.world.buildings.other.STOCKPILE end")
        E.link = True
        for r in (r1, r2):
            f = B.furnish_project(r.project_id, True)
            assert f.ok, plain(f)
        E.build_all()
        prog1 = plain(B.furnish_progress(project(r1.project_id)))
        prog2 = plain(B.furnish_progress(project(r2.project_id)))
        # bedrooms: 4 x (door, bed, cabinet, chest); workshops: the mason's shop (the pile is no building)
        assert (prog1["placed"], prog1["done"]) == (16, 16), prog1
        assert (prog2["placed"], prog2["done"]) == (1, 1), prog2
        for r in (r1, r2):
            fin = B.finish_project(r.project_id)
            assert fin.ok, plain(fin)
        links = plain(E.links) or []
        rem = [x for x in links if x["what"] == "remember"]
        assert len(rem) == 1 and rem[0]["shop"] == "Masons" and rem[0]["flag"] == "stone", links
        assert (rem[0]["x"], rem[0]["y"], rem[0]["z"]) == (SX + 13, SY - 7, ROCK_Z), rem
        shop = E.building_at(SX + 21, SY - 5, ROCK_Z)
        assert rem[0]["shop_id"] == shop.id
        assert [x for x in links if x["what"] == "link"], links
        # the links: the new hall tiles, nothing else
        p1, p2 = project(r1.project_id), project(r2.project_id)
        assert proj_links(p1) == {(SX + x, SY + y) for x in range(-1, 12) for y in (-1, 0, 1)} - {(SX, SY)}
        assert proj_links(p2) == {(SX + x, SY + y) for x in range(12, 25) for y in (-1, 0, 1)}
        assert plain(p2.floor)["piles"] == [{"x": 13, "y": -7, "flag": "stone", "shop": "Masons"}]
    finally:
        E.game_off()
        B.floor_building_at = None
        B.floor_stockpiles = None


@test("2b. a later level's rooms inside an earlier project's box: furnish_progress counts each project's own")
def _():
    # one room first (north, u = 4), then three: south u = 4, then north u = 8, south u = 8 -- the
    # second project's box (u 4..10, both sides) holds the first project's room
    hint = dict(elevs=[ROCK_Z], tag="homes", dirs=["east"])
    r1 = start(kind="bedrooms", rooms=1, room_size=3, floor=dict(hint))
    r2 = start(kind="bedrooms", rooms=3, room_size=3, floor=dict(hint))
    assert r1.ok and r2.ok and r1.floor is not None and r2.floor is not None
    LUA.execute(GAME, W, E)
    try:
        dig_all()
        for r in (r1, r2):
            assert B.furnish_project(r.project_id, True).ok
        E.build_all()
        prog1 = plain(B.furnish_progress(project(r1.project_id)))
        prog2 = plain(B.furnish_progress(project(r2.project_id)))
        assert prog1["placed"] == 4 and prog2["placed"] == 12, (prog1, prog2, draw(ROCK_Z))
    finally:
        E.game_off()


# --------------------------------------------------------------------------- 3. every kind, three styles

KIND_PARAMS = {
    "bedrooms": {"rooms": 4, "room_size": 3}, "suites": {"suites": 2}, "jail": {"cells": 3},
    "dining": {"tables": 8}, "storage": {"piles": ["food", "stone"], "room_size": 5},
    "workshops": {"shops": ["Masons", "Carpenters"]}, "temple": {"size": "shrine"},
    "memorial": {"name": "the Fallen"}, "garden": {"name": "the Green"}, "hospital": {"beds": 4}, "barracks": {"beds": 4},
    "archery": {"lanes": 1, "length": 10}, "tombs": {"coffins": 4}, "tavern": {"tables": 6},
    "library": {"bookcases": 4},
}
STYLES = {
    "plain": {},
    "rounded": {"hall": "rounded", "statues": 2, "smooth": 2},
    "grand": {"hall": "octagonal", "motif": "star", "scale": 150, "grand": True},
}
FLOOR_ZS = [63, 62, 61]      # the main stair's rock levels


def same_answer(d, r):
    """The dry run and the real run agree on where the level goes."""
    keys = ("ok", "z", "tiles", "not_on_floor")
    a, b = {k: d[k] for k in keys}, {k: r[k] for k in keys}
    fa, fb = plain(d.floor), plain(r.floor)
    return a == b and fa == fb, (a, b, fa, fb)


@test("3. every kind of FLOOR_KINDS, plain, rounded with statues and smoothing, and a new shape with a motif, "
      "scale 150 and grand: on a floor, openings on the hall, no overlap, nothing beside another's room, "
      "the stair never designated, dry run = real run, check_site's rules hold")
def _():
    kinds = sorted(plain(B.FLOOR_KINDS))
    assert sorted(KIND_PARAMS) == kinds, kinds
    placed = {}
    for sname, style in STYLES.items():
        _reset()
        for kind in kinds:
            kw = dict(KIND_PARAMS[kind], kind=kind, style=style, floor={"elevs": FLOOR_ZS})
            before = (designated(), json.dumps(store(), sort_keys=True), len(projects()))
            d = start(True, **copy.deepcopy(kw))
            assert (designated(), json.dumps(store(), sort_keys=True), len(projects())) == before, \
                f"{kind} {sname}: the dry run changed something"
            r = start(False, **copy.deepcopy(kw))
            ok, why = same_answer(d, r)
            assert ok, f"{kind} {sname}: the dry run and the real run differ: {why}"
            assert r.ok and r.floor is not None, f"{kind} {sname}: not on a floor: {plain(r)}"
            assert int(r.designated) == int(r.tiles)
            placed[(kind, sname)] = (int(r.z), plain(r.floor)["id"])
            check_floor(int(r.z), what=f"{kind} {sname}")
        for z in FLOOR_ZS:
            check_floor(z, what=f"all kinds {sname} z{z}")
            if sname == "grand":
                show(f"3. every kind of level, grand style, z{z}", z)
    assert len(placed) == 3 * len(kinds)


@test("3b. a grand hall closes a run's end (axial): recorded as a slot that closes the run, nothing placed over it")
def _():
    # (r3 g2) spill=False: one arm only, as arms_max says (a full floor would else open another arm)
    hint = dict(elevs=[ROCK_Z], tag="halls", run_max=20, axial=True, dirs=["east"], arms_max=1, grow=["arm"],
                spill=False)
    for _ in range(2):
        r = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(hint))
        assert r.ok and r.floor is not None, plain(r)
    r = start(kind="dining", tables=8, style={"grand": True}, floor=dict(hint))
    f = plain(r.floor)
    assert r.ok and f["side"] == "east" and f["hall_new"] == 0, f
    rec = floor_rec(ROCK_Z)
    ax = [s for s in rec["slots"] if s.get("axial")]
    assert len(ax) == 1 and ax[0]["side"] == 0 and rec["runs"][0].get("closed") == "terminus", rec
    assert ax[0]["u"] == 2 + rec["runs"][0]["len"], (ax, rec["runs"])
    # the next level of the tag finds no room on the closed run (one arm only): it is not put over the hall
    r = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(hint))
    assert r.floor is None and str(r.not_on_floor).startswith("floor 1: no room"), plain(r)
    check_floor(ROCK_Z, what="3b")


# --------------------------------------------------------------------------- 4. growth

TURN_REACH = 7       # ai-floorplace: columns a run may be lengthened by to make room for a turn's node


def runs_of(z=ROCK_Z):
    f = floor_rec(z)
    return f["runs"] if f else []


def compass(dx, dy):
    return {(1, 0): "east", (-1, 0): "west", (0, 1): "south", (0, -1): "north"}[(dx, dy)]


@test("4. twelve levels on one floor with run_max 20: the hall turns the way each `turns` says, or opens "
      "an arm first (grow); no run past run_max but for a turn's node; every level on the floor")
def _():
    want_first_turn = {"left": "north", "right": "south", "alternate": "north", "both": "north"}
    for turns in ("left", "right", "alternate", "both"):
        for grow in (["turn", "arm"], ["arm", "turn"]):
            _reset()
            hint = dict(elevs=[ROCK_Z], tag="homes", run_max=20, turns=turns, grow=grow, dirs=["east", "west"])
            for i in range(12):
                r = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(hint))
                assert r.ok and r.floor is not None and int(r.z) == ROCK_Z, \
                    f"{turns} {grow} level {i}: {plain(r)}\n{draw(ROCK_Z)}"
            runs = runs_of()
            hub = [r for r in runs if not r["parent"]]
            kids = [r for r in runs if r["parent"]]
            assert hub[0]["dx"] == 1 and kids, (turns, grow, runs)
            if grow[0] == "arm":
                # a second arm out of the hub before anything turns
                assert len(hub) == 2 and compass(hub[1]["dx"], hub[1]["dy"]) == "west", runs
                assert all(k["id"] > hub[1]["id"] for k in kids), runs
            else:
                assert kids[0]["id"] == 2 and kids[0]["parent"] == 1, runs
            byid = {r["id"]: r for r in runs}

            def side(k):
                p = byid[k["parent"]]
                return 1 if (k["dx"], k["dy"]) == (-p["dy"], p["dx"]) else -1
            first = kids[0]
            assert not byid[first["parent"]]["parent"], (turns, grow, runs)    # off a hub run
            # left = side -1 of its parent; alternate and both try the left first off a hub run
            assert side(first) == (1 if turns == "right" else -1), (turns, grow, first)
            if turns == "left":
                assert all(side(k) == -1 for k in kids), runs
            if turns == "right":
                assert all(side(k) == 1 for k in kids), runs
            if turns == "both" and grow[0] == "turn":       # (arm first: twelve levels never needed the fork)
                assert any(sorted(side(k) for k in kids if k["parent"] == r["id"]) == [-1, 1] for r in runs), runs
            for r in runs:
                lim = 20 + (TURN_REACH if any(k["parent"] == r["id"] for k in runs) else 0)
                assert r["len"] <= lim, (turns, grow, r)
            check_floor(ROCK_Z, what=f"4 {turns} {grow}")
            if turns == "alternate" and grow[0] == "turn":
                show("4. twelve bedroom levels, run_max 20, turns alternate, grow turn first", ROCK_Z)


@test("4b. a full floor answers 'floor N: no room', the level goes by choose_site; the next level skips the "
      "floor (full for its tag) until full_retry_days have passed")
def _():
    hint = dict(elevs=[ROCK_Z], tag="homes", run_max=20, arms_max=1, grow=["arm"], dirs=["east"],
                full_retry_days=3, spill=False)    # (r3 g2) spill=False: the floor is full at its one arm
    for _ in range(2):
        r = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(hint))
        assert r.ok and r.floor is not None, plain(r)
    r = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(hint))
    assert r.ok and r.floor is None and str(r.not_on_floor).startswith("floor 1: no room"), plain(r)
    assert project(r.project_id).floor is None          # placed by choose_site, as today
    st = store()
    assert st["fallbacks"] == 1 and st["last"]["ok"] is False and st["floors"][0]["full"].get("homes") == 0, st
    E.tick = 2 * 1200
    # (r3 g2) the mark keeps the size refused: a level as big is kept off (a smaller one is tried:
    # tests/test_r3_g2.py)
    r = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(hint))
    assert r.floor is None and str(r.not_on_floor) == "floor 1: full for homes", plain(r)
    # another district's level is not kept off the floor by the homes' mark
    r = start(kind="jail", cells=2, floor=dict(hint, tag="defence", arms_max=2))
    assert r.ok and r.floor is not None, plain(r)
    E.tick = 3 * 1200 + 1
    # tried again (the homes' own run is full: it shares the defence hall, step 4 of `place`)
    r = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(hint))
    assert r.floor is not None and plain(r.floor)["arm"] == "west", plain(r)
    rep = plain(B.floors_report())
    assert rep["fallbacks"] == 2 and not rep["list"][0]["full"], rep
    check_floor(ROCK_Z, what="4b")


# --------------------------------------------------------------------------- 5. obstacles

def set_tiles(tiles, **fields):
    for (x, y, z) in tiles:
        W.set(x, y, z, LUA.table_from(fields))


def nothing_beside(obstacle, what, rooms_only=False, on_only=False):
    """No designated tile on or beside (8 ways) an obstacle tile; rooms_only: no room tile (a hall may
    cross the fort's own open floor)."""
    halls = set()
    for p in projects():
        halls |= {(x, y, p.z) for x, y in proj_links(p)}
    for (x, y, z) in designated():
        if rooms_only and (x, y, z) in halls:
            continue
        reach = (0,) if on_only else (-1, 0, 1)
        near = [(x + dx, y + dy, z) for dx in reach for dy in reach if (x + dx, y + dy, z) in obstacle]
        assert not near, f"{what}: {x},{y},{z} designated beside {near[:3]}\n{draw(z)}"


def no_half_levels(answers, what):
    for r in answers:
        if r.ok:
            assert int(r.designated) == int(r.tiles), f"{what}: {plain(r)}"
    # every saved project's dig cells are designated, whole (nothing half of a level)
    for p in projects():
        if p.phase == "dig":
            for (x, y) in proj_tiles(p):
                t = W.peek(x, y, p.z)
                assert t.designated or t.shape != "WALL", f"{what}: project {p.id} half designated at {x},{y}"


def obstacle_run(setup, what, rooms_only=False, levels=4, on_only=False):
    _reset()
    obstacle = setup()
    hint = dict(elevs=[ROCK_Z], tag="homes", dirs=["east"])
    answers = []
    for _ in range(levels):
        answers.append(start(kind="bedrooms", rooms=4, room_size=3, floor=dict(hint)))
    nothing_beside(obstacle, what, rooms_only, on_only)
    no_half_levels(answers, what)
    check_floor(ROCK_Z, what=what)
    return answers


@test("5. obstacles: water three tiles ahead of the hall, an aquifer over part of the floor, open sky, the "
      "map's edge 10 tiles from the stair, another project's box, a vein the player dug: nothing designated "
      "on or beside any; the floor goes round or the level falls back; never a half-designated level")
def _():
    def water():
        first = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(elevs=[ROCK_Z], tag="homes", dirs=["east"]))
        assert first.floor is not None
        tiles = {(SX + 14, SY + y, ROCK_Z) for y in range(-6, 7)}     # the hall ends at x = 11
        set_tiles(tiles, shape="FLOOR", liquid=True)
        return tiles
    ans = obstacle_run(water, "water")
    assert any(a.floor is not None and plain(a.floor)["arm"] != "east" for a in ans[:3]) or \
        any(a.floor is None for a in ans), "the floor went round the water or fell back"

    def aquifer():
        above = {(SX + x, SY + y, ROCK_Z + 1) for x in range(12, 40) for y in range(-12, 13)}
        set_tiles(above, aquifer=True)
        return {(x, y, ROCK_Z) for x, y, _ in above}
    # (check_site's rule: nothing under it; a hall beside the column under an aquifer is allowed, as today)
    obstacle_run(aquifer, "aquifer above", on_only=True)

    def sky():
        tiles = {(SX + x, SY + y, ROCK_Z) for x in range(-40, -8) for y in range(-20, 21)}
        set_tiles(tiles, outside=True)
        return tiles
    obstacle_run(sky, "open sky", levels=6)

    def edge():
        W.size = LUA.table_from([SX + 11, 120, 100])          # the map's last column 10 east of the stair
        return {(SX + 10, SY + y, ROCK_Z) for y in range(-60, 60)} | {(SX + 9, SY + y, ROCK_Z) for y in range(-60, 60)}
    ans = obstacle_run(edge, "the map's edge")
    assert all(a.floor is None or plain(a.floor)["arm"] != "east" for a in ans), [plain(a.floor) for a in ans]

    def other_box():
        d = B.load_projects()
        box = {"x1": SX + 13, "y1": SY - 8, "x2": SX + 26, "y2": SY + 8, "z": ROCK_Z}
        d.list = LUA.table_from(list(lua_list(d.list)) + [tbl({
            "id": 999, "kind": "storage", "phase": "done", "z": ROCK_Z, "area": box,
            "stair": {"x": SX, "y": SY}, "anchor": {"x": SX + 20, "y": SY}, "cells": {"dig": []}})])
        d.next_id = 1000
        B.save_projects(d)
        tiles = {(x, y, ROCK_Z) for x in range(box["x1"] + 1, box["x2"]) for y in range(box["y1"] + 1, box["y2"])}
        # (item38) a finished level keeps a floor out by its tiles: its stockpile's
        set_tiles(tiles, shape="FLOOR", taken=True)
        return tiles
    obstacle_run(other_box, "another project's box")

    def vein():
        tiles = {(SX + 16, SY + y, ROCK_Z) for y in range(-15, 16)}
        set_tiles(tiles, shape="FLOOR")
        return tiles
    ans = obstacle_run(vein, "a vein the player dug", rooms_only=True)


# --------------------------------------------------------------------------- 6. the six running forts

from snapshots import snapshot  # noqa: E402

FORTS = "ABCDEF"
LIVE_KINDS = [("bedrooms", {"rooms": 4, "room_size": 3}), ("storage", {"piles": ["food", "stone"], "room_size": 5}),
              ("workshops", {"shops": ["Masons"]}), ("dining", {"tables": 8}), ("bedrooms", {"rooms": 4, "room_size": 3}),
              ("jail", {"cells": 3}), ("temple", {"size": "shrine"}), ("bedrooms", {"rooms": 6, "room_size": 3}),
              ("library", {"bookcases": 4}), ("storage", {"piles": ["wood"], "room_size": 5})]


def walk_all():
    B.walk_group = LUA.eval("""function(B) return function(x, y, z) local t = B.tile_info(x, y, z)
        if t and t.shape ~= 'WALL' then return 1 end return 0 end end""")(B)


def load_fort(name):
    """The fort's standing levels on the fake world: each box open floor, every second level only as an
    old_areas outline (as the saves keep the dropped ones), the rest as finished (or open) projects;
    the other boxes (zones, the player's rooms) open floor taken by a building or zone."""
    fx = json.loads((LIVE / f"{name}-levels.json").read_text(encoding="utf-8"))
    W.size = LUA.table_from(list(fx["map"]["size"]))
    st = fx["stair"]
    sx, sy = st["x"], st["y"]
    zs = sorted(int(z) for z in fx["hall_runs"])
    lo, hi = min(zs + [l["z"] for l in fx["levels"]]), st["z_top"]
    boxes = []
    for b in fx.get("other_boxes", []):
        x1, y1, x2, y2 = b["box"]
        boxes.append((x1, y1, x2, y2, b["z"]))
        for x in range(x1, x2 + 1):
            for y in range(y1, y2 + 1):
                W.set(x, y, b["z"], LUA.table_from({"shape": "FLOOR", "taken": True}))
    plist, old = [], []
    for i, lv in enumerate(sorted(fx["levels"], key=lambda l: l["id"])):
        bd, z = lv["bounds"], lv["z"]
        boxes.append((bd["x1"], bd["y1"], bd["x2"], bd["y2"], z))
        for x in range(bd["x1"], bd["x2"] + 1):
            for y in range(bd["y1"], bd["y2"] + 1):
                W.set(x, y, z, LUA.table_from({"shape": "FLOOR"}))
        if i % 2 == 1:
            old.append({"x1": bd["x1"], "y1": bd["y1"], "x2": bd["x2"], "y2": bd["y2"], "z": z})
        else:
            phase = {"cancelled": "cancelled", "dig": "dig", "furnish": "furnish"}.get(lv["state"], "done")
            plist.append({"id": lv["id"], "kind": lv["kind"], "phase": phase, "z": z,
                          "area": {"x1": bd["x1"] - 1, "y1": bd["y1"] - 1, "x2": bd["x2"] + 1, "y2": bd["y2"] + 1, "z": z},
                          "stair": {"x": sx, "y": sy}, "anchor": {"x": (bd["x1"] + bd["x2"]) // 2, "y": (bd["y1"] + bd["y2"]) // 2},
                          "cells": {"dig": []}, "params": {}})
    for z in range(lo, hi + 1):
        W.set(sx, sy, z, LUA.table_from({"shape": "STAIR_UP" if z == lo else ("STAIR_DOWN" if z == hi else "STAIR_UPDOWN"),
                                          "taken": False}))
    d = B.load_projects()
    d.list = tbl(plist)
    d.old_areas = tbl(old)
    d.next_id = 500
    B.save_projects(d)
    W.citizens = tbl([{"x": sx + 1, "y": sy, "z": hi}] * 5)
    walk_all()
    return fx, sx, sy, zs, boxes


# (each name written out: tests/test_k48_verification.py matches every committed snapshot to its name here)
LIVE_SNAPSHOTS = {
    "A": lambda v: snapshot("b16_live_A", v), "B": lambda v: snapshot("b16_live_B", v),
    "C": lambda v: snapshot("b16_live_C", v), "D": lambda v: snapshot("b16_live_D", v),
    "E": lambda v: snapshot("b16_live_E", v), "F": lambda v: snapshot("b16_live_F", v),
}


@test("6. the six running forts' standing levels: no hall where the hub has no free way (a no_hall row, the "
      "level goes on), halls only where the fixture shows room, never longer than the free run, nothing "
      "designated inside a standing box; what each fort does recorded (b16_live_<fort>.json)")
def _():
    for name in FORTS:
        _reset()
        B.FLOOR_OLD_OPEN = False     # (item38) the fixture's free runs are by the boxes (its levels' tiles plain floor)
        fx, sx, sy, zs, boxes = load_fort(name)
        answers = []
        for i, (kind, kw) in enumerate(LIVE_KINDS):
            rot = zs[i % len(zs):] + zs[:i % len(zs)]
            r = start(kind=kind, floor={"elevs": rot[:6]}, **copy.deepcopy(kw))
            answers.append(r)
            assert r.ok or r.error, plain(r)
        # nothing designated inside a standing box
        for (x, y, z) in designated():
            inside = [b for b in boxes if b[4] == z and b[0] <= x <= b[2] and b[1] <= y <= b[3]]
            assert not inside, f"fort {name}: {x},{y},{z} designated inside the box {inside[0]}\n{draw(z, sx, sy)}"
        rep = plain(B.floors_report())
        rows = {row["z"]: row for row in rep["list"]}
        record = {}
        for z in zs:
            dirs = fx["hall_runs"][str(z)]["dirs"]
            free = {d: dirs[d]["free"] for d in dirs}
            row = rows.get(z)
            if row is None:
                record[str(z)] = "not tried"
                continue
            arms = row.get("arms") or []
            if all(v == 0 for v in free.values()):
                assert row["no_hall"] and not arms, f"fort {name} z{z}: {row}"
            for a in arms:
                f = floor_rec(z, sx, sy)
                hub = next(r for r in f["runs"] if not r["parent"] and compass(r["dx"], r["dy"]) == a["dir"])
                assert hub["len"] <= free[a["dir"]] + 1, \
                    f"fort {name} z{z}: the {a['dir']} hall runs {hub['len']}, the fixture's free run is {free[a['dir']]}\n{draw(z, sx, sy)}"
            if arms:
                assert any(free[a["dir"]] >= 10 for a in arms), (name, z, free, arms)
            record[str(z)] = ("no hall" if row["no_hall"] else
                              {"arms": {a["dir"]: a["len"] for a in arms}, "rooms": row["rooms"],
                               "fixture_free": free})
            if arms:
                check_floor(z, sx, sy, what=f"fort {name} z{z}")
        placed = [{"kind": k, "z": int(r.z) if r.ok else None,
                   "floor": (plain(r.floor)["id"], plain(r.floor)["arm"]) if r.floor is not None else None,
                   "not_on_floor": r.not_on_floor} for (k, _), r in zip(LIVE_KINDS, answers)]
        LIVE_SNAPSHOTS[name]({"floors": record, "levels": placed})
        if name == "F":
            z = next((int(zz) for zz, v in record.items() if isinstance(v, dict)), None)
            if z:
                show(f"6. fort F (Garden fort) z{z}: the new hall among the standing levels", z, sx, sy)


# --------------------------------------------------------------------------- 6b. two stairwells

def second_stair():
    TB._stair(90, 60, 60, 80)
    W.citizens = tbl(plain(W.citizens) + [{"x": 88, "y": 60, "z": 70}])


def built_up(z, sx, sy, r=9):
    d = B.load_projects()
    old = plain(d.old_areas) if d.old_areas is not None else []
    old = old if isinstance(old, list) else []
    old.append({"x1": sx - r, "y1": sy - r, "x2": sx + r, "y2": sy + r, "z": z})
    d.old_areas = tbl(old)
    B.save_projects(d)
    # (0.105.119 item38) a dropped outline keeps a floor out only by its tiles: the level's own,
    # dug and taken (its rooms' zones and furniture), all round the stair
    set_tiles({(x, y, z) for x in range(sx - r, sx + r + 1) for y in range(sy - r, sy + r + 1) if (x, y) != (sx, sy)},
              shape="FLOOR", taken=True)


@test("6b. two stairwells: the first stair's level built up, the level's floor hangs on the second stair; the "
      "report names that stair; a hint whose spine is the second stair starts there at once")
def _():
    second_stair()
    stairs = [(s.x, s.y) for s in lua_list(B.find_stairs(3))]
    assert stairs[0] == (SX, SY) and (90, 60) in stairs, stairs
    built_up(ROCK_Z, SX, SY)
    r = start(kind="bedrooms", rooms=4, room_size=3, floor={"elevs": [ROCK_Z]})
    f = plain(r.floor)
    assert r.ok and f["stair"] == {"x": 90, "y": 60}, plain(r)
    rep = plain(B.floors_report())
    stair_rows = {(row["stair"]["x"], row["stair"]["y"]): row for row in rep["list"]}
    assert stair_rows[(90, 60)]["arms"] and stair_rows[(SX, SY)]["no_hall"], rep
    check_floor(ROCK_Z, 90, 60, what="6b")
    # the spine: the second stair first, though the first is free and the most used
    _reset()
    second_stair()
    r = start(kind="bedrooms", rooms=4, room_size=3, floor={"elevs": [ROCK_Z], "spine": {"x": 90, "y": 60}})
    assert r.ok and plain(r.floor)["stair"] == {"x": 90, "y": 60}, plain(r)
    assert [f["stair"] for f in store()["floors"]] == [{"x": 90, "y": 60}], store()     # nothing tried on the first


# --------------------------------------------------------------------------- 6c. old levels

@test("6c. old levels round the stair (classic, each centred on it): the workshop goes into the free room; no "
      "hall starts inside an old level's box (a no_hall row; the level goes elsewhere); not one old tile "
      "designated again; the old records byte for byte the same")
def _():
    _reset("classic")
    plan = {"elev_lo": ROCK_Z, "elev_hi": ROCK_Z, "elev_target": ROCK_Z}
    old = []
    for kind, kw in (("bedrooms", {"rooms": 4, "room_size": 3}), ("storage", {"piles": ["food", "stone"], "room_size": 5}),
                     ("workshops", {"shops": ["Masons", "Carpenters"]})):
        old.append(start(kind=kind, plan=plan, **kw))
        dig_all()                     # (each dug before the next)
    for r in old:
        assert r.ok and r.floor is None, plain(r)
    old_z = sorted({int(r.z) for r in old})
    assert project(old[2].project_id).free_left, "the workshops level keeps a free room"
    old_tiles = {(x, y, project(r.project_id).z) for r in old for x, y in proj_tiles(project(r.project_id))}
    E.mode = "hallway"
    hint = {"elevs": old_z}
    r = start(kind="workshops", shops=["Craftsdwarfs"], floor=hint)
    assert r.ok and r.floor is None and r.project_id == old[2].project_id, plain(r)     # the free room
    after_join = json.loads(json.dumps(plain(W.persist[PKEY].list), sort_keys=True))
    for kind, kw in (("bedrooms", {"rooms": 4, "room_size": 3}), ("jail", {"cells": 3})):
        n = start(kind=kind, floor=dict(hint), **kw)
        assert n.ok and n.floor is None and "no hall" in str(n.not_on_floor), plain(n)
    rep = plain(B.floors_report())
    assert sorted(row["z"] for row in rep["list"] if row["no_hall"]) == old_z, rep
    assert not (designated() & old_tiles)
    now = json.loads(json.dumps(plain(W.persist[PKEY].list), sort_keys=True))
    olds = {o.project_id for o in old}
    assert [x for x in now if x["id"] in olds] == [x for x in after_join if x["id"] in olds]


@test("6d. the fort's own 3-wide corridor out of the stair (the player's): adopted as the hall's first stretch "
      "(walked, never dug), the rooms along it, nothing dug on it")
def _():
    corridor = {(SX + x, SY + y, ROCK_Z) for x in range(-1, 13) for y in (-1, 0, 1) if (x, y) != (0, 0)}
    set_tiles(corridor, shape="FLOOR")
    r = start(kind="bedrooms", rooms=4, room_size=3, floor={"elevs": [ROCK_Z], "dirs": ["east"]})
    assert r.ok and r.floor is not None, plain(r)
    run = floor_rec(ROCK_Z)["runs"][0]
    assert compass(run["dx"], run["dy"]) == "east" and run["walked"] == run["len"] == 10, run
    assert floor_rec(ROCK_Z)["hub"] == "found"
    assert not (designated(ROCK_Z) & corridor)
    assert plain(r.floor)["hall_new"] == 0
    check_floor(ROCK_Z, what="6d")
    show("6d. the player's corridor adopted as the hall", ROCK_Z)


# --------------------------------------------------------------------------- 7. no record, a newer record

EMPTY_KEYS = {"v", "mode", "count", "rooms", "hall_tiles", "fallbacks", "list"}


@test("7. a save with no floor record builds a floor; a record from a newer version (v = 99) is left untouched, "
      "the level placed classically; floors_report answers the contract's shapes for both")
def _():
    rep = plain(B.floors_report())
    assert set(rep) == EMPTY_KEYS and rep["count"] == 0 and rep["mode"] == "hallway" and not rep["list"], rep
    assert W.persist[KEY] is None
    r = start(kind="bedrooms", rooms=4, room_size=3, floor={"elevs": [ROCK_Z]})
    assert r.ok and r.floor is not None and store()["v"] == 1, plain(r)
    _reset()
    newer = {"v": 99, "next": 7, "floors": [{"id": 3, "z": ROCK_Z, "shape": "a newer one"}], "extra": "kept"}
    W.persist[KEY] = tbl(newer)
    r = start(kind="bedrooms", rooms=4, room_size=3, floor={"elevs": [ROCK_Z]})
    assert r.ok and r.floor is None and "newer version" in str(r.not_on_floor), plain(r)
    assert store() == newer, store()
    rep = plain(B.floors_report())
    assert set(rep) == EMPTY_KEYS | {"newer"} and rep["newer"] is True and rep["count"] == 0, rep


# --------------------------------------------------------------------------- 8. classic is today's

def boot_without_floor_parts():
    """A second engine with the builder whose PARTS has no floor part (today's builder)."""
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(ROOT / "lua")
    layouts = (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8")
    src = (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8")
    src2 = re.sub(r"\n\s*'floorstore',[^\n]*\n\s*'floorpiles',[^\n]*\n\s*'floors'\}", "\n}", src)
    assert src2 != src and "'floorstore'" not in src2, "the PARTS list changed shape: update this test"
    B2, W2 = lua.execute(TB.HARNESS, layouts, src2)
    assert B2.floor_site is None and B2.floor_mode is None
    return lua, B2, W2


CLASSIC_SEQ = [("bedrooms", {"rooms": 4, "room_size": 3}), ("storage", {"piles": ["food", "stone"], "room_size": 5}),
               ("workshops", {"shops": ["Masons"]}), ("dining", {"tables": 8}), ("temple", {"size": "shrine"}),
               ("jail", {"cells": 3}), ("hospital", {"beds": 4}), ("library", {"bookcases": 4}),
               ("tavern", {"tables": 6}), ("barracks", {"beds": 4})]


def py(lua, v):
    from lupa.lua53 import lua_type
    if lua_type(v) != "table":
        return v
    keys = list(v.keys())
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(lua, v[i]) for i in range(1, len(keys) + 1)]
    return {str(k): py(lua, v[k]) for k in keys}


def run_seq(lua, Bx, Wx):
    out = []
    for kind, kw in CLASSIC_SEQ:
        t = lua.table_from({k: (lua.table_from(v) if isinstance(v, list) else v) for k, v in dict(kw, kind=kind).items()})
        r = Bx.start_project(t, lua.table_from({"year": 148, "tick": 100}), False)
        out.append(py(lua, r))
        Bx.MAX_OPEN_PROJECTS = 100
    tiles = sorted(k for k, t in Wx.tiles.items() if t.designated)
    return out, tiles, py(lua, Wx.persist[PKEY])


@test("8. classic is today's: with the switch at classic, ten start_projects give exactly the tiles and the saved "
      "projects the builder without its floor parts gives; no floors record is written")
def _():
    _reset("classic")
    lua2, B2, W2 = boot_without_floor_parts()
    B2.MAX_OPEN_PROJECTS = 100
    B2.TRY_BESIDE, B2.WELL_DIG_UP = B.TRY_BESIDE, B.WELL_DIG_UP      # (test_builder's _reset, as on B)
    a = run_seq(LUA, B, W)
    b = run_seq(lua2, B2, W2)
    assert a[0] == b[0], [(x, y) for x, y in zip(a[0], b[0]) if x != y][:1]
    assert a[1] == b[1]
    assert json.dumps(a[2], sort_keys=True) == json.dumps(b[2], sort_keys=True)
    assert W.persist[KEY] is None
    assert sum(1 for r in a[0] if r.get("ok")) >= 6, a[0]       # (the small fake fort fills up: both alike)


# --------------------------------------------------------------------------- 9. cancel

@test("9. a floor project cancelled while digging: its slots dead, the next level not on them, the hall's "
      "recorded length back, the report's rooms without it")
def _():
    hint = dict(elevs=[ROCK_Z], tag="homes", dirs=["east"])
    r1 = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(hint))
    r2 = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(hint))
    assert floor_rec(ROCK_Z)["runs"][0]["len"] == 18
    t2 = proj_tiles(project(r2.project_id))
    c = B.cancel_project(r2.project_id)
    assert c.ok
    rec = floor_rec(ROCK_Z)
    assert [s.get("dead") for s in rec["slots"]] == [None] * 4 + [True] * 4, rec["slots"]
    assert rec["runs"][0]["len"] == 10, rec["runs"]
    rep = plain(B.floors_report())
    assert rep["rooms"] == 4 and rep["list"][0]["rooms"] == 4, rep
    assert not any(W.peek(x, y, ROCK_Z).designated for x, y in t2)
    r3 = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(hint))
    assert r3.floor is not None
    t3 = proj_tiles(project(r3.project_id)) - proj_links(project(r3.project_id))
    dead = {(SX + x, SY + y) for s in rec["slots"] if s.get("dead") for x in range(s["u"], s["u"] + s["w"])
            for y in ([-2 - k for k in range(s["d"] + 1)] if s["side"] == -1 else [2 + k for k in range(s["d"] + 1)])}
    assert not (t3 & dead), f"the next level dug a dead slot\n{draw(ROCK_Z)}"
    check_floor(ROCK_Z, what="9")


@test("9b. the floor's first project cancelled: the floor starts again from the hub, in the same direction")
def _():
    hint = dict(elevs=[ROCK_Z], tag="homes", dirs=["east"], arms_max=1)
    r1 = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(hint))
    assert B.cancel_project(r1.project_id).ok
    assert not designated(ROCK_Z)
    r2 = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(hint))
    assert r2.floor is not None, plain(r2)
    f = plain(r2.floor)
    assert f["arm"] == "east" and f["hall_new"] > 0, f
    assert W.peek(SX + 1, SY, ROCK_Z).designated, "the hub dug again"
    check_floor(ROCK_Z, what="9b")


# --------------------------------------------------------------------------- 10. hospital

@test("10. a hospital's rooms never nearer than 6 tiles to the stair, whichever way its hall runs")
def _():
    for d in ("east", "south", "west", "north"):
        _reset()
        r = start(kind="hospital", beds=4, floor={"elevs": [ROCK_Z], "dirs": [d]})
        assert r.ok and r.floor is not None and plain(r.floor)["arm"] == d, plain(r)
        p = project(r.project_id)
        rooms = proj_tiles(p) - proj_links(p)
        near = min(max(abs(x - SX), abs(y - SY)) for x, y in rooms)
        assert near >= 6, f"{d}: a hospital tile {near} from the stair\n{draw(ROCK_Z)}"
        # and as the second level on a floor, behind a bedrooms level
        _reset()
        start(kind="bedrooms", rooms=4, room_size=3, floor={"elevs": [ROCK_Z], "dirs": [d], "tag": "homes"})
        r = start(kind="hospital", beds=4, floor={"elevs": [ROCK_Z], "dirs": [d], "tag": "homes"})
        p = project(r.project_id)
        rooms = proj_tiles(p) - proj_links(p)
        assert r.floor is not None and min(max(abs(x - SX), abs(y - SY)) for x, y in rooms) >= 6, plain(r)
        check_floor(ROCK_Z, what=f"10 {d}")


# --------------------------------------------------------------------------- 11. stair extension

@test("11. a hint whose only level is below the stair's bottom, within reach: the stair is extended as today, "
      "the floor begins there")
def _():
    z = 58
    r = start(kind="bedrooms", rooms=4, room_size=3, floor={"elevs": [z]})
    assert r.ok and r.extends_stairs is True and int(r.z) == z and r.floor is not None, plain(r)
    assert plain(r.floor)["new_floor"] is True
    p = project(r.project_id)
    assert [int(c.z) for c in lua_list(p.stairs)] == [60, 59, 58], plain(p.stairs)     # (the old bottom made up/down)
    assert W.peek(SX, SY, 59).designated and W.peek(SX, SY, 58).designated
    check_floor(z, what="11")
    # out of reach (PLAN_EXTEND below the bottom): not tried
    r = start(kind="bedrooms", rooms=4, room_size=3, floor={"elevs": [50]})
    assert r.floor is None, plain(r)


# --------------------------------------------------------------------------- 12. speed

def big_record(z=ROCK_Z):
    """A floor with 150 slots on four arms (the record only: the map is untouched rock)."""
    runs, slots = [], []
    for i, (dx, dy, n) in enumerate(((1, 0, 48), (-1, 0, 48), (0, 1, 48), (0, -1, 6))):
        rid = i + 1
        runs.append({"id": rid, "parent": 0, "ox": 0, "oy": 0, "dx": dx, "dy": dy, "len": 50 if n == 48 else 14,
                     "walked": 0, "tag": "homes", "node": 3, "neck": False, "pid": 1})
        k = 0
        u = 4
        while k < n:
            for side in (-1, 1):
                slots.append({"run": rid, "side": side, "u": u, "w": 1, "d": 3, "pid": 1, "kind": "bedrooms",
                              "tag": "homes", "role": "room"})
                k += 1
            u += 2
    assert len(slots) == 150
    return {"v": 1, "next": 2, "fallbacks": 0,
            "floors": [{"id": 1, "z": z, "stair": {"x": SX, "y": SY}, "made": 0, "hub": "dug",
                        "runs": runs, "slots": slots, "full": {}}]}


@test("12. speed: a start_project on a floor with 150 slots recorded (120x120 level) answers in its time, its "
      "tile reads bounded; floors_report reads no tile")
def _():
    W.persist[KEY] = tbl(big_record())
    E.counting, E.reads = True, 0
    t0 = time.perf_counter()
    r = start(kind="bedrooms", rooms=4, room_size=3, floor={"elevs": [ROCK_Z], "arms_max": 4})
    dt = time.perf_counter() - t0
    reads = int(E.reads)
    assert r.ok and r.floor is not None and plain(r.floor)["arm"] == "north", plain(r)
    assert "out of time" not in str(r.not_on_floor or "")
    print(f"    (start_project on a 150-slot floor: {dt:.2f}s wall, {reads} tile reads; "
          "not asserted on the clock: the suite's rule)")
    assert reads < 60000, reads
    E.reads = 0
    t0 = time.perf_counter()
    rep = plain(B.floors_report())
    dt = time.perf_counter() - t0
    assert int(E.reads) == 0 and rep["rooms"] == 154, (int(E.reads), rep["rooms"])
    print(f"    (floors_report: {dt * 1000:.1f} ms)")


# --------------------------------------------------------------------------- 13. forts differ

# The six presets' grammars, written out by hand from the contract's table ("How the hint is filled") for the
# sliders of lua/ai-overseer-settings.lua BUILTIN_PRESETS (Spacing, Depth = verticality, Fortification,
# Grandeur, Reserves = stockpile, Room size = size: Monastery -50, Merchant city +50 (0.105.115), the rest 0).
# `stagger` is the fort seed's pick of (0, 2, 3):
# here the one floor_grammar picks for the preset's name as seed (test 15 checks the brain gives these).
PRESET_HINTS = {
    # Spacing -60 (tight: no lead, no kind gap, nothing ahead); Fortification 120: dog-leg run 30 x 0.6 = 18,
    # a doored neck
    "War-hold": dict(gap=1, kind_gap=0, lead=0, ahead=0, run_max=18, run_min=10, arms_max=2, sides="both",
                     stagger=0, bay=0, node=3, grow=["arm", "turn"], turns="alternate", balance=False,
                     axial=False, neck=True, pile_w=5, piles_new=1, full_retry_days=28),
    # Grandeur 60: a 5x5 square where a hall turns; Room size -50: the run 15% shorter (26)
    "Monastery": dict(gap=1, kind_gap=1, lead=2, ahead=1, run_max=26, run_min=10, arms_max=2, sides="both",
                      stagger=0, bay=0, node=5, grow=["arm", "turn"], turns="alternate", balance=False,
                      axial=False, neck=False, pile_w=5, piles_new=1, full_retry_days=28),
    # Reserves 40 < 50; Room size +50: the run 15% longer (35), 7-wide pile rooms
    "Merchant city": dict(gap=1, kind_gap=1, lead=2, ahead=1, run_max=35, run_min=10, arms_max=2, sides="both",
                          stagger=0, bay=0, node=3, grow=["arm", "turn"], turns="alternate", balance=False,
                          axial=False, neck=False, pile_w=7, piles_new=1, full_retry_days=28),
    # Fortification 100: dog-leg 18, the neck; Reserves 60: one more pile room
    "Hermit hold": dict(gap=1, kind_gap=1, lead=2, ahead=1, run_max=18, run_min=10, arms_max=2, sides="both",
                        stagger=2, bay=0, node=3, grow=["arm", "turn"], turns="alternate", balance=False,
                        axial=False, neck=True, pile_w=5, piles_new=2, full_retry_days=28),
    # Depth 120: the very deep run (14) and one arm
    "Deep mine": dict(gap=1, kind_gap=1, lead=2, ahead=1, run_max=14, run_min=10, arms_max=1, sides="both",
                      stagger=3, bay=0, node=3, grow=["arm", "turn"], turns="alternate", balance=False,
                      axial=False, neck=False, pile_w=5, piles_new=1, full_retry_days=28),
    # Grandeur 40 (< 60: no square); every slider between the bars, its own stagger
    "Garden fort": dict(gap=1, kind_gap=1, lead=2, ahead=1, run_max=30, run_min=10, arms_max=2, sides="both",
                        stagger=3, bay=0, node=3, grow=["arm", "turn"], turns="alternate", balance=False,
                        axial=False, neck=False, pile_w=5, piles_new=1, full_retry_days=28),
}
PRESET_SEQ = [("bedrooms", {"rooms": 4, "room_size": 3}), ("workshops", {"shops": ["Masons"]}),
              ("bedrooms", {"rooms": 4, "room_size": 3}), ("storage", {"piles": ["food", "stone"], "room_size": 5}),
              ("dining", {"tables": 8}), ("bedrooms", {"rooms": 4, "room_size": 3}), ("jail", {"cells": 3}),
              ("tavern", {"tables": 6}), ("library", {"bookcases": 4}), ("workshops", {"shops": ["Carpenters"]})]


PRESET_SNAPSHOTS = {
    "War-hold": lambda v: snapshot("b16_floor_war_hold", v),
    "Monastery": lambda v: snapshot("b16_floor_monastery", v),
    "Merchant city": lambda v: snapshot("b16_floor_merchant_city", v),
    "Hermit hold": lambda v: snapshot("b16_floor_hermit_hold", v),
    "Deep mine": lambda v: snapshot("b16_floor_deep_mine", v),
    "Garden fort": lambda v: snapshot("b16_floor_garden_fort", v),
}


def floor_text(z):
    """The level as a plain picture (rows of '#', '.', 'X'), for a snapshot."""
    cells = set()
    for k, t in W.tiles.items():
        x, y, tz = (int(n) for n in k.split(","))
        if tz == z and t.designated:
            cells.add((x - SX, y - SY))
    if not cells:
        return []
    xs, ys = [c[0] for c in cells] + [0], [c[1] for c in cells] + [0]
    return ["".join("X" if (x, y) == (0, 0) else ("." if (x, y) in cells else "#")
                    for x in range(min(xs) - 1, max(xs) + 2)) for y in range(min(ys) - 1, max(ys) + 2)]


@test("13. forts differ: the six presets' grammars, the same ten levels: six different floors (b16_floor_<preset>), "
      "the tight fort's hall per room below the others', the deep fort's longest arm shorter than the wide fort's")
def _():
    out = {}
    for name, g in PRESET_HINTS.items():
        _reset()
        on = 0
        for kind, kw in PRESET_SEQ:
            r = start(kind=kind, floor=dict(g, elevs=[ROCK_Z, ROCK_Z - 1]), **copy.deepcopy(kw))
            assert r.ok, (name, kind, plain(r))
            on += r.floor is not None
        rep = plain(B.floors_report())
        rows = [row for row in rep["list"] if row["z"] == ROCK_Z]
        arm = max((a["len"] for row in rows for a in row["arms"]), default=0)
        out[name] = {"on_floor": on, "rooms": rep["rooms"], "hall_tiles": rep["hall_tiles"],
                     "hall_per_room": round(rep["hall_tiles"] / max(1, rep["rooms"]), 2), "arm_max": arm,
                     "picture": floor_text(ROCK_Z)}
        for z in (ROCK_Z, ROCK_Z - 1):
            check_floor(z, what=f"13 {name} z{z}")
        PRESET_SNAPSHOTS[name](out[name])
        show(f"13. {name}: ten levels on its floor (z63)", ROCK_Z)
    pics = [json.dumps(v["picture"]) for v in out.values()]
    assert len(set(pics)) == 6, {k: v["hall_per_room"] for k, v in out.items()}
    tight = out["War-hold"]["hall_per_room"]
    for other in ("Monastery", "Merchant city", "Garden fort"):
        assert tight < out[other]["hall_per_room"], (tight, other, out[other]["hall_per_room"])
    assert out["Deep mine"]["arm_max"] < out["Garden fort"]["arm_max"], \
        (out["Deep mine"]["arm_max"], out["Garden fort"]["arm_max"])


# --------------------------------------------------------------------------- 14. the bridge

_BRIDGE = []


def bridge():
    """ai-bridge.lua on test_hygiene_bridge.py's stub DFHack, in this engine, its ai-builder the real one."""
    if not _BRIDGE:
        hyg = (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8")
        harness = re.search(r'HARNESS = r"""(.*?)"""', hyg, re.S).group(1)
        H = LUA.execute(harness, (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8"), str(ROOT / "lua"))
        H.scripts = LUA.table()
        H.halted = False
        M = H.module()
        _BRIDGE.extend([H, M])
    H, M = _BRIDGE
    H.scripts["ai-builder"] = B
    H.scripts["ai-layouts"] = LUA.globals().LAYOUTS
    return H, M


FLOORS_ROW_KEYS = {"stair", "hub", "width", "arms", "free", "others", "old_boxes", "no_hall", "full"}


@test("14. the bridge: act_start_project's floor hint reaches floor_site; a bad hint is refused with the key "
      "named; SECTIONS.floors answers every key of the contract's row")
def _():
    H, M = bridge()
    a = {"type": "start_project", "kind": "bedrooms", "rooms": 4, "room_size": 3,
         "floor": dict(EXAMPLE_HINT, colour="red")}
    r = M.act_start_project(tbl(a))
    assert r.ok and r.floor is not None, plain(r)
    f = plain(r.floor)
    assert (f["arm"], f["u"], f["hall_new"], f["new_floor"]) == ("east", 4, 38, True), f
    assert set(f) >= {"id", "elevation", "stair", "arm", "side", "u", "hall_new", "new_floor", "units", "gap",
                      "lead", "run_max"}, f
    r = M.act_start_project(tbl(dict(a, floor=dict(EXAMPLE_HINT, run_max=99))))
    assert r.ok is False and "floor.run_max" in str(r.error), plain(r)
    r = M.act_start_project(tbl(dict(a, floor=False)))
    assert r.ok and r.floor is None and r.not_on_floor is None, plain(r)         # the classic way, on purpose
    sec = plain(M.SECTIONS.floors())
    assert sec["v"] == 1 and sec["mode"] == "hallway" and sec["count"] == 1, sec
    row = sec["list"][0]
    assert FLOORS_ROW_KEYS <= set(row), set(row)
    assert row["width"] == 3 and row["hub"] == "dug" and row["stair"] == {"x": SX, "y": SY}, row
    on_z = sorted((p.id for p in projects() if p.z == ROCK_Z and p.floor is None), reverse=True)
    assert row["arms"][0]["dir"] == "east" and row["arms"][0]["slots"] == 4 and (row["others"] or []) == on_z, row


# --------------------------------------------------------------------------- 15. the brain's hint

def preset_sliders():
    src = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    block = src[src.index("BUILTIN_PRESETS = {"):src.index("\n}\n", src.index("BUILTIN_PRESETS = {"))]
    out = {}
    for m in re.finditer(r"\['([^']+)'\]\s*=\s*\{([^}]*)\}", block):
        out[m.group(1)] = {k: int(v) for k, v in re.findall(r"(\w+)\s*=\s*(-?\d+)", m.group(2))}
    return out


@test("15. the brain's hint against the bridge: floor_grammar.grammar(...) for the six presets' sliders passes "
      "parse_floor unchanged, and is the grammar test 13 wrote out by hand")
def _():
    try:
        import floor_grammar
        import masterplan_floors  # noqa: F401
    except Exception as e:      # noqa: BLE001
        skip(f"brain/floor_grammar.py or masterplan_floors.py not importable: {e}")
    H, M = bridge()
    sliders = preset_sliders()
    assert sorted(sliders) == sorted(PRESET_HINTS), sorted(sliders)
    to_lua = LUA.eval("function(f, v) local h, e = f(v); return {h = h, e = e} end")
    for name, traits in sliders.items():
        g = floor_grammar.grammar(traits, None, None, seed=name)
        got = to_lua(M.parse_floor, tbl(g))
        assert got.e is None, (name, got.e)
        back = plain(got.h)
        assert back == g, (name, {k: (g.get(k), back.get(k)) for k in set(g) | set(back) if g.get(k) != back.get(k)})
        assert g == PRESET_HINTS[name], (name, {k: (g[k], PRESET_HINTS[name][k]) for k in g if g[k] != PRESET_HINTS[name][k]})
        # and through the urgent and grand variants too
        for kw in ({"urgent": True}, {"grand": True}, {"doors": "fortified"}, {"pattern": "rings"}):
            g2 = floor_grammar.grammar(traits, {"symmetry": "radial", "scale": 140}, None, seed=name, **kw)
            got = to_lua(M.parse_floor, tbl(g2))
            assert got.e is None and plain(got.h) == g2, (name, kw, got.e)



@test("7b. a level that begins a new floor after another level was marked (no hall): the answer's floor id, the "
      "project's p.floor.id and the record's id are one and the same (the placement recorded before the marks)")
def _():
    built_up(ROCK_Z, SX, SY)
    r = start(kind="bedrooms", rooms=4, room_size=3, floor={"elevs": [ROCK_Z, ROCK_Z - 1]})
    assert r.ok and r.floor is not None and int(r.z) == ROCK_Z - 1, plain(r)
    fid = plain(r.floor)["id"]
    assert plain(project(r.project_id).floor)["id"] == fid
    rec = floor_rec(ROCK_Z - 1)
    assert rec["id"] == fid and rec["slots"][0]["pid"] == r.project_id, rec
    marked = floor_rec(ROCK_Z)
    assert marked["id"] != fid and "*" in marked["full"] and not marked["runs"], marked
    assert store()["next"] == max(fid, marked["id"]) + 1


@test("15b. the ranges: every whole-number key of the brain's RANGES, at both ends, passes parse_floor and comes "
      "out of ai-floorplan.grammar unchanged; one past either end is refused by parse_floor with the key named")
def _():
    try:
        import floor_grammar
    except Exception as e:      # noqa: BLE001
        skip(f"brain/floor_grammar.py not importable: {e}")
    H, M = bridge()
    to_lua = LUA.eval("function(f, v) local h, e = f(v); return {h = h, e = e} end")
    G = E.mods["ai-floorplan"].grammar
    for key, (lo, hi) in floor_grammar.RANGES.items():
        for v in (lo, hi):
            got = to_lua(M.parse_floor, tbl({key: v}))
            assert got.e is None and plain(got.h) == {key: v}, (key, v, got.e)
            g = plain(G(got.h))
            if key == "run_min" and v > g["run_max"]:
                continue          # (grammar keeps run_min <= run_max: 30 > the default 30? never)
            assert g[key] == v, (key, v, g[key])
        for v in (lo - 1, hi + 1):
            got = to_lua(M.parse_floor, tbl({key: v}))
            assert got.h is None and str(got.e).startswith(f"floor.{key} "), (key, v, got.e)


if __name__ == "__main__":
    finish()
