"""(layout option B, group B7) The wiring in start_project: the floor first,
today's placement as the fallback.

A new level is offered to its floor's main hall (floor_site) before
choose_site places it as before; a cancelled floor project is taken out of
its floor (floor_release) and a finished one has its piles booked
(floor_book_piles). The floor parts themselves (ai-builder-floorstore,
-floors, -floorpiles: groups B4 to B6) are not in this copy: every call in
lua/ai-builder-projects.lua is guarded, and these tests set stand-ins on
the builder's environment, on test_builder's fake fort in a real Lua engine.

    python tests/test_b7_floor_wiring.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import code_has, finish, have_lua, make_test, skip  # noqa: E402

try:                                   # an ASCII drawing for a failure's output, when it is there
    from tools.draw_level import render as _render  # noqa: E402
except Exception:                      # noqa: BLE001
    _render = None

LUA = B = W = TB = F = None
if have_lua():
    import test_builder as TB  # noqa: E402  (its fake fort; its tests run only when it is run itself)
    LUA, B, W = TB.LUA, TB.B, TB.W

FLOOR_NAMES = ("FLOOR_KINDS", "floor_mode", "floor_site", "floor_commit", "floor_fallback",
               "floor_release", "floor_book_piles")
SRC = (ROOT / "lua" / "ai-builder-projects.lua").read_text(encoding="utf-8")

# The stand-ins. F is their switchboard and their log:
#   F.mode      what floor_mode answers
#   F.answer    'site' | 'refuse' | 'error': what floor_site does
#   F.z         the level the stand-in's site is on
#   F.calls     {name = times called}; F.site_args, F.commit, F.fallback, F.released, F.booked: what they were given
# The site is a real small one, stair-relative on the fake fort's main stair (60,60): a 3x3 piece of
# main hall (cells 'd1', as compose gives a hall its priority) south of the fort's own hall (y 55-65),
# and a 3x3 room below it (one 'd(3x3)' cell), with a workshop, a pile and a zone in the room.
STANDINS = r"""
local B, W = ...
local F = {}
function F.reset()
  F.mode, F.answer, F.z = 'hallway', 'site', 72
  F.calls = {mode = 0, site = 0, commit = 0, fallback = 0, release = 0, book = 0}
  F.site_args, F.commit, F.fallback, F.released, F.booked, F.seen = nil, nil, nil, nil, nil, nil
end
F.reset()
function F.layout()
  local L = {dig = {}, tiles = {}, build = {}, place = {}, zone = {}, smooth = {}, engrave = {},
             furniture = {Workshop = 1}, summary = {rooms = 1, hall_tiles = 9}, halls = {}, style = {}}
  local function tile(x, y) L.tiles[x] = L.tiles[x] or {}; L.tiles[x][y] = true end
  for y = 6, 8 do for x = -1, 1 do
    table.insert(L.dig, {x = x, y = y, text = 'd1'}); tile(x, y)
  end end
  table.insert(L.dig, {x = -1, y = 9, text = 'd(3x3)'})
  for y = 9, 11 do for x = -1, 1 do tile(x, y) end end
  L.bounds = {x1 = -1, y1 = 6, x2 = 1, y2 = 11}
  L.build = {{x = 0, y = 10, text = 'wM'}}
  L.place = {{x = -1, y = 6, text = 's(3x1)'}}
  L.zone = {{x = -1, y = 9, text = 'm(3x3)'}}
  L.smooth = {{x = -1, y = 6, text = 's'}, {x = 1, y = 6, text = 's'}, {x = 0, y = 10, text = 's'},
              {x = -2, y = 7, text = 's'}}
  L.halls = {{x1 = -1, y1 = 6, x2 = 1, y2 = 8}}
  return L
end
function F.site(stair)
  local z = F.z
  local links = {}
  for y = 6, 8 do for x = -1, 1 do table.insert(links, {x = x, y = y}) end end
  return {z = z, extend = false, anchor = {x = 60, y = 60}, extra = {},
          area = {x1 = 58, y1 = 68, x2 = 62, y2 = 72, z = z},
          areas = {{x1 = 59, y1 = 66, x2 = 61, y2 = 68, z = z}},
          stair = stair, corridor = 0, new_corridor = 0, links = links,
          floor = {id = 3, slots = 1, hall = 9, piles = {{x = 60, y = 66, flag = 'stone', shop = 'Masons'}}},
          floor_result = {id = 3, elevation = z, stair = {x = 60, y = 60}, arm = 'south', side = 'south', u = 1,
                          hall_new = 9, new_floor = true, piles = {'stone'}, units = 1,
                          gap = 1, lead = 2, run_max = 30},
          _commit = {store = {}, floor = {id = 3}, placement = {}, free = {}, marks = {}}}
end
local function designated()
  local n = 0
  for _, t in pairs(W.tiles) do if t.designated then n = n + 1 end end
  return n
end
function F.install()
  B.FLOOR_KINDS = {bedrooms = true, suites = true, jail = true, dining = true, storage = true, workshops = true,
                   temple = true, memorial = true, garden = true, hospital = true, barracks = true, archery = true,
                   tombs = true, tavern = true, library = true}
  B.floor_mode = function() F.calls.mode = F.calls.mode + 1; return F.mode end
  B.floor_site = function(params, stairs, reserved, data, ceil_z)
    F.calls.site = F.calls.site + 1
    F.site_args = {params = params, stairs = stairs, reserved = reserved, data = data, ceil_z = ceil_z}
    -- what the fort looked like when the floor was asked: nothing dug or saved for this level yet
    F.seen = {projects = #data.list, designated = designated(), join_steps = params.join_steps}
    if F.answer == 'error' then error('the floor parts broke') end
    if F.answer == 'refuse' then
      return nil, 'no room', {{z = F.z, sx = 60, sy = 60, tag = 'homes', free = {east = 0}}}
    end
    return F.site(stairs[1]), F.layout()
  end
  B.floor_commit = function(site, id)
    F.calls.commit = F.calls.commit + 1
    local saved = false
    local d = W.persist['ai-overseer/projects']
    for _, p in ipairs(d and d.list or {}) do if p.id == id then saved = true end end
    F.commit = {site = site, id = id, saved = saved}
    return true
  end
  B.floor_fallback = function(kind, why, elevation, marks)
    F.calls.fallback = F.calls.fallback + 1
    F.fallback = {kind = kind, why = why, elevation = elevation, marks = marks}
  end
  B.floor_release = function(p)
    F.calls.release = F.calls.release + 1
    F.released = {id = p.id, phase = p.phase, floor = p.floor}
    return 1
  end
  B.floor_book_piles = function(p)
    F.calls.book = F.calls.book + 1
    F.booked = {id = p.id, phase = p.phase, piles = p.floor.piles}
    return 1, 0
  end
end
return F
"""

if TB is not None:
    F = LUA.execute(STANDINS, B, W)


def _reset():
    if TB is None:
        return
    TB._reset(False)
    for name in FLOOR_NAMES:           # the copy as it is: no floor part
        B[name] = None
    F.reset()


test = make_test(before=_reset)
plain_test = make_test()


def need():
    if TB is None:
        skip("needs the lupa package (pip install lupa)")


def tbl(v):
    if isinstance(v, dict):
        return LUA.table_from({k: tbl(x) for k, x in v.items()})
    if isinstance(v, list):
        return LUA.table_from([tbl(x) for x in v])
    return v


def start(dry=False, **kw):
    return B.start_project(tbl(dict(kw)), LUA.table_from({"year": 255, "tick": 100}), dry)


def floors(mode="hallway", answer="site"):
    F.install()
    F.mode, F.answer = mode, answer


def lua_list(t):
    return [t[i] for i in range(1, len(t) + 1)] if t is not None else []


def projects():
    d = W.persist["ai-overseer/projects"]
    return lua_list(d.list) if d is not None else []


def project(pid):
    return next(p for p in projects() if p.id == pid)


def dig_all():
    for t in W.tiles.values():
        if t.designated:
            t.shape, t.designated = "FLOOR", False


def designated():
    """The absolute tiles designated for digging: {(x, y, z)}."""
    out = set()
    for k, t in W.tiles.items():
        if t.designated:
            out.add(tuple(int(n) for n in k.split(",")))
    return out


def dig_cells(p):
    return [(c.x, c.y, c.text) for c in lua_list(p.cells.dig)]


def drawn(cells):
    """A level's tiles as text, for a failure's message (when the drawing helper is there)."""
    if _render is None:
        return sorted(cells)
    try:
        return "\n" + _render([(x, y) for x, y, *_ in cells])
    except Exception:                  # noqa: BLE001
        return sorted(cells)


def classic(dry=False, **kw):
    """What today's placement answers and designates for these params, on a fresh fort."""
    _reset()
    r = start(dry, **kw)
    assert r.ok, dict(r)
    return r, designated()


def same_site(r, r0):
    return ((r.z, r.anchor.x, r.anchor.y, r.corridor, r.new_corridor, r.tiles, r.extends_stairs)
            == (r0.z, r0.anchor.x, r0.anchor.y, r0.corridor, r0.new_corridor, r0.tiles, r0.extends_stairs))


BED = dict(kind="bedrooms", rooms=4, room_size=3)
HALL_CELLS = [(x, y, "d1") for y in (6, 7, 8) for x in (-1, 0, 1)]
FLOOR_TILES = {(60 + x, 60 + y, 72) for x in (-1, 0, 1) for y in range(6, 12)}


# --- 1. no floor part at all: today's path -------------------------------------------

@test("1. no floor part in the builder: a level is placed as today, its project has no floor or areas, its answer no floor key")
def _():
    need()
    assert all(B[n] is None for n in FLOOR_NAMES), "this copy has no floor part"
    r = start(**BED)
    assert r.ok and r.project_id == 1 and r.floor is None and r.not_on_floor is None, dict(r)
    p = project(1)
    assert p.floor is None and p.areas is None and p.links is not None, dict(p)
    assert len(designated()) == r.tiles
    d = start(True, kind="dining", tables=8)
    assert d.ok and d.dry_run and d.floor is None and d.not_on_floor is None, dict(d)


@test("1. the floor parts there but one missing (floor_mode, floor_site or FLOOR_KINDS): still today's path, nothing called")
def _():
    need()
    r0, tiles0 = classic(**BED)
    for missing in ("floor_mode", "floor_site", "FLOOR_KINDS"):
        _reset()
        floors()
        B[missing] = None
        r = start(**BED)
        assert r.ok and same_site(r, r0) and designated() == tiles0, (missing, dict(r))
        assert r.floor is None and r.not_on_floor is None and project(1).floor is None
        assert F.calls.site == 0 and F.calls.commit == 0 and F.calls.fallback == 0, (missing, dict(F.calls))


# --- 2. the switch at classic --------------------------------------------------------

@test("2. floor_mode 'classic': floor_site is never called, the level is today's tile for tile")
def _():
    need()
    r0, tiles0 = classic(**BED)
    _reset()
    floors(mode="classic")
    r = start(**BED)
    assert r.ok and same_site(r, r0) and designated() == tiles0, dict(r)
    assert F.calls.mode == 1 and F.calls.site == 0 and F.calls.commit == 0 and F.calls.fallback == 0, dict(F.calls)
    assert r.floor is None and r.not_on_floor is None and project(1).floor is None


@test("2. floor_mode raising or answering anything but 'hallway' is never a floor")
def _():
    need()
    floors(mode="Hallway")
    assert start(**BED).ok and F.calls.site == 0
    assert project(1).floor is None


# --- 3. a floor takes the level ------------------------------------------------------

@test("3. 'hallway' and a site: the project is saved with the floor's cells, floor, areas and links; floor_commit once, after the save; the answer has floor")
def _():
    need()
    floors()
    r = start(**BED)
    assert r.ok and r.project_id == 1 and r.kind == "bedrooms", dict(r)
    assert r.z == 72 and r.elevation == 72 and r.tiles == 18 and r.designated == 18, dict(r)
    assert r.corridor == 0 and r.new_corridor == 0 and (r.anchor.x, r.anchor.y) == (60, 60)
    assert r.not_on_floor is None and r.warning is None
    assert r.floor.id == 3 and r.floor.arm == "south" and r.floor.hall_new == 9 and r.floor.new_floor is True, dict(r.floor)
    assert dict(r.summary) == {"rooms": 1, "hall_tiles": 9}, dict(r.summary)        # the floor's layout's, not the classic one's
    # the floor's tiles are designated, and nothing else
    assert designated() == FLOOR_TILES, drawn(designated())
    p = project(1)
    assert p.phase == "dig" and p.z == 72 and (p.anchor.x, p.anchor.y) == (60, 60) and (p.stair.x, p.stair.y) == (60, 60)
    assert dig_cells(p) == HALL_CELLS + [(-1, 9, "d(3x3)")], dig_cells(p)
    assert [(c.x, c.y, c.text) for c in lua_list(p.cells.build)] == [(0, 10, "wM")]
    assert [(c.x, c.y, c.text) for c in lua_list(p.cells.place)] == [(-1, 6, "s(3x1)")]
    assert [(c.x, c.y, c.text) for c in lua_list(p.cells.zone)] == [(-1, 9, "m(3x3)")]
    assert dict(p.furniture) == {"Workshop": 1} and dict(p.summary) == {"rooms": 1, "hall_tiles": 9}
    # floor, areas, links: the site's
    assert p.floor.id == 3 and p.floor.slots == 1 and p.floor.hall == 9 and p.floor.piles[1].flag == "stone", dict(p.floor)
    assert dict(p.area) == {"x1": 58, "y1": 68, "x2": 62, "y2": 72, "z": 72}
    assert len(lua_list(p.areas)) == 1 and dict(p.areas[1]) == {"x1": 59, "y1": 66, "x2": 61, "y2": 68, "z": 72}
    assert [(c.x, c.y) for c in lua_list(p.links)] == [(x, y) for y in (6, 7, 8) for x in (-1, 0, 1)]
    assert len(lua_list(B.project_areas(p))) == 2                                   # both boxes keep others out
    # the smoothing: its own tiles, and untouched rock beside them; never under the workshop
    assert sorted((c.x, c.y) for c in lua_list(p.cells.smooth)) == [(-2, 7), (-1, 6), (1, 6)]
    # floor_site was given start_project's own things
    a = F.site_args
    assert a.params.kind == "bedrooms" and a.params.rooms == 4 and a.ceil_z is None
    assert (a.stairs[1].x, a.stairs[1].y) == (60, 60) and len(lua_list(a.reserved)) == 0 and len(lua_list(a.data.list)) == 1
    assert F.seen.projects == 0 and F.seen.designated == 0, "asked before anything was designated or saved"
    # floor_commit: once, with the site and the new id, after the save
    assert F.calls.site == 1 and F.calls.commit == 1 and F.calls.fallback == 0, dict(F.calls)
    assert F.commit.id == 1 and F.commit.saved is True and F.commit.site.floor.id == 3 and F.commit.site._commit is not None


@test("3. the dry run answers the same floor, and neither designates, saves nor commits")
def _():
    need()
    floors()
    d = start(True, **BED)
    assert d.ok and d.dry_run and d.z == 72 and d.tiles == 18 and d.not_on_floor is None, dict(d)
    assert d.floor.id == 3 and d.floor.arm == "south" and d.floor.units == 1, dict(d.floor)
    assert dict(d.summary) == {"rooms": 1, "hall_tiles": 9} and d.furniture.Workshop == 1
    assert d.decoration.smooth == 3 and dict(d.area) == {"x1": 58, "y1": 68, "x2": 62, "y2": 72, "z": 72}
    assert designated() == set() and projects() == []
    assert F.calls.site == 1 and F.calls.commit == 0 and F.calls.fallback == 0, dict(F.calls)
    r = start(**BED)                                           # and the real one answers what the dry run did
    assert r.ok and (r.z, r.tiles, r.floor.id, r.floor.arm) == (d.z, d.tiles, d.floor.id, d.floor.arm)


@test("3. max_elev reaches floor_site as its ceiling (a z); floor = a hint reaches it in the params")
def _():
    need()
    floors()
    r = start(kind="dining", tables=8, max_elev=75, floor={"elevs": [72], "tag": "halls"})
    assert r.ok and r.floor.id == 3, dict(r)
    assert F.site_args.ceil_z == 75 and F.site_args.params.floor.tag == "halls"
    assert project(1).params.floor is None, "the hint is not kept with the project"


@test("3. the save failing: the floor's dig is undone and floor_commit is not called")
def _():
    need()
    floors()
    real = B.save_projects
    B.save_projects = LUA.eval("function() return false end")
    try:
        r = start(**BED)
    finally:
        B.save_projects = real
    assert not r.ok and "undone" in r.error, dict(r)
    assert designated() == set() and F.calls.commit == 0 and F.calls.fallback == 0, dict(F.calls)


@test("3. a floor site Quickfort disagrees with is refused as any site is (nothing saved or committed)")
def _():
    need()
    floors()
    W.set(60, 70, 72, tbl({"shape": "FLOOR"}))                 # one of the room's tiles is no rock after all
    r = start(**BED)
    assert not r.ok and "dry run disagreed: 17 of 18" in r.error, dict(r)
    assert designated() == set() and projects() == [] and F.calls.commit == 0


# --- 4. / 5. the floor says no: today's placement ------------------------------------

@test("4. 'hallway' and nil, 'no room', marks: choose_site places it as today; not_on_floor; floor_fallback once with kind, reason, elevation, marks")
def _():
    need()
    r0, tiles0 = classic(**BED)
    p0 = project(1)
    cells0, links0 = dig_cells(p0), [(c.x, c.y) for c in lua_list(p0.links)]
    _reset()
    floors(answer="refuse")
    r = start(**BED)
    assert r.ok and same_site(r, r0) and designated() == tiles0, (dict(r), drawn(designated()))
    assert r.not_on_floor == "no room" and r.floor is None, dict(r)
    p = project(1)
    assert p.floor is None and p.areas is None and dig_cells(p) == cells0
    assert [(c.x, c.y) for c in lua_list(p.links)] == links0
    assert F.calls.site == 1 and F.calls.commit == 0 and F.calls.fallback == 1, dict(F.calls)
    fb = F.fallback
    assert fb.kind == "bedrooms" and fb.why == "no room" and fb.elevation == r.elevation, dict(fb)
    assert len(lua_list(fb.marks)) == 1 and fb.marks[1].tag == "homes" and fb.marks[1].z == 72 and fb.marks[1].free.east == 0


@test("4. the dry run of a refused floor: today's site, not_on_floor, and floor_fallback is not called")
def _():
    need()
    r0, _tiles = classic(True, **BED)
    _reset()
    floors(answer="refuse")
    d = start(True, **BED)
    assert d.ok and d.dry_run and same_site(d, r0) and d.not_on_floor == "no room" and d.floor is None, dict(d)
    assert designated() == set() and projects() == []
    assert F.calls.site == 1 and F.calls.fallback == 0 and F.calls.commit == 0, dict(F.calls)


@test("4. no floor and no classic site either: the refusal carries not_on_floor; floor_fallback is not called")
def _():
    need()
    floors(answer="refuse")
    real = B.choose_site
    B.choose_site = LUA.eval("function() return nil, 'no safe site near any staircase' end")
    try:
        r = start(**BED)
    finally:
        B.choose_site = real
    assert not r.ok and r.error == "no safe site near any staircase" and r.not_on_floor == "no room", dict(r)
    assert F.calls.fallback == 0 and projects() == []


@test("5. floor_site raising an error: the same fallback, the error's text in not_on_floor (300 characters at most), no marks")
def _():
    need()
    r0, tiles0 = classic(**BED)
    _reset()
    floors(answer="error")
    r = start(**BED)
    assert r.ok and same_site(r, r0) and designated() == tiles0, dict(r)
    assert "the floor parts broke" in r.not_on_floor and r.floor is None and project(1).floor is None, r.not_on_floor
    assert F.calls.fallback == 1 and F.fallback.kind == "bedrooms" and F.fallback.marks is None
    assert "the floor parts broke" in F.fallback.why and F.fallback.elevation == r.elevation
    # a long reason is cut
    _reset()
    floors()
    B.floor_site = LUA.eval("function() return nil, ('floor 3: no room; '):rep(40) end")
    r = start(**BED)
    assert r.ok and len(r.not_on_floor) == 300 and len(F.fallback.why) == 300, len(r.not_on_floor)


@test("5. floor_commit, floor_fallback, floor_release or floor_book_piles raising: the action still answers ok")
def _():
    need()
    floors()
    boom = LUA.eval("function() error('store unreadable') end")
    B.floor_commit, B.floor_release = boom, boom
    r = start(**BED)
    assert r.ok and r.floor.id == 3 and project(1).floor.id == 3, dict(r)
    c = B.cancel_project(1)
    assert c.ok and project(1).phase == "cancelled", dict(c)
    _reset()
    floors(answer="refuse")
    B.floor_fallback = boom
    r = start(**BED)
    assert r.ok and r.not_on_floor == "no room", dict(r)


@test("5. the floor parts half there (floor_site without floor_commit, or without floor_fallback): the level is still made")
def _():
    need()
    floors()
    B.floor_commit = None
    r = start(**BED)
    assert r.ok and r.floor.id == 3 and project(1).floor.id == 3, dict(r)
    _reset()
    floors(answer="refuse")
    B.floor_fallback = None
    r = start(**BED)
    assert r.ok and r.not_on_floor == "no room" and project(1).floor is None, dict(r)


# --- 6. the levels that stay classic -------------------------------------------------

@test("6. floor = false, join = false, a farms level and a kind not in FLOOR_KINDS: floor_site is not called")
def _():
    need()
    for label, kw in (("floor = false", dict(BED, floor=False)),
                      ("join = false", dict(BED, join=False)),
                      ("join = false (workshops)", dict(kind="workshops", shops=["Masons"], join=False)),
                      ("not in FLOOR_KINDS", dict(BED))):
        r0, tiles0 = classic(**kw)
        _reset()
        floors()
        if label == "not in FLOOR_KINDS":
            B.FLOOR_KINDS = tbl({"dining": True})
        r = start(**kw)
        assert r.ok and same_site(r, r0) and designated() == tiles0, (label, dict(r))
        assert F.calls.site == 0 and F.calls.commit == 0 and F.calls.fallback == 0, (label, dict(F.calls))
        assert r.floor is None and r.not_on_floor is None and project(1).floor is None, label
    # farms: the real FLOOR_KINDS has no farms (they follow the soil); whatever a farm level answers, no floor is asked
    _reset()
    floors()
    assert B.FLOOR_KINDS.farms is None
    start(kind="farms", plots=2, plot_w=3)
    assert F.calls.site == 0 and F.calls.mode == 0, dict(F.calls)


# --- 7. workshops --------------------------------------------------------------------

STYLE = {"hall": "plain", "smooth": 0, "statues": 0}


def standing_level(shops, **kw):
    """A classic workshops level that stands (dug, done), made with the floors off."""
    r = start(kind="workshops", shops=shops, style=STYLE, **kw)
    assert r.ok and r.joined is None, dict(r)
    dig_all()
    project(r.project_id).phase = "done"
    return r


@test("7. workshops, floors on: a standing level with a free room takes the shop (as 0.105.54); floor_site is not called")
def _():
    need()
    standing_level(["Smelter"])                                # planned with 3 free rooms
    assert project(1).free_left == 3
    floors()
    r = start(kind="workshops", shops=["MetalsmithsForge"], style=STYLE)
    assert r.ok and r.joined == 1 and r.how == "free_room" and r.tiles == 0, dict(r)
    assert r.floor is None and r.not_on_floor is None
    assert F.calls.site == 0 and F.calls.commit == 0 and F.calls.fallback == 0, dict(F.calls)
    assert project(2).parent == 1 and project(2).floor is None


@test("7. workshops, floors on, no free room: floor_site is called before any extension, and its floor takes the shop")
def _():
    need()
    standing_level(["Millstone"], spare=0)
    floors()
    r = start(kind="workshops", shops=["Quern"], spare=0, style=STYLE)
    assert r.ok and r.joined is None and r.how is None and r.project_id == 2, dict(r)
    assert r.floor.id == 3 and r.not_on_floor is None and designated() == FLOOR_TILES, drawn(designated())
    # when the floor was asked nothing had been extended: one project, no tile designated, the join back at both steps
    assert F.calls.site == 1 and F.seen.projects == 1 and F.seen.designated == 0 and F.seen.join_steps is None, dict(F.seen)
    p = project(2)
    assert p.parent is None and p.floor.id == 3 and p.kind == "workshops" and list(p.params.shops.values()) == ["Quern"]
    assert project(1).ext_tiles is None and F.calls.commit == 1 and F.commit.id == 2


@test("7. workshops, floors on, floor_site refusing: the standing level is extended as today (how = 'extension'), with not_on_floor")
def _():
    need()
    standing_level(["Millstone"], spare=0)
    r0 = start(kind="workshops", shops=["Quern"], spare=0, style=STYLE)       # today's extension
    assert r0.ok and r0.joined == 1 and r0.how == "extension", dict(r0)
    tiles0 = designated()
    for answer in ("refuse", "error"):
        _reset()
        standing_level(["Millstone"], spare=0)
        floors(answer=answer)
        r = start(kind="workshops", shops=["Quern"], spare=0, style=STYLE)
        assert r.ok and r.joined == 1 and r.how == "extension" and r.project_id == 2, (answer, dict(r))
        assert r.tiles == r0.tiles and designated() == tiles0, (answer, drawn(designated()))
        assert r.floor is None and project(2).floor is None and project(2).parent == 1
        assert ("no room" if answer == "refuse" else "the floor parts broke") in r.not_on_floor, r.not_on_floor
        assert F.calls.site == 1 and F.calls.commit == 0, dict(F.calls)
    # and its dry run: the extension, with the reason, nothing changed
    _reset()
    standing_level(["Millstone"], spare=0)
    floors(answer="refuse")
    d = start(True, kind="workshops", shops=["Quern"], spare=0, style=STYLE)
    assert d.ok and d.dry_run and d.how == "extension" and d.not_on_floor == "no room", dict(d)
    assert designated() == set() and len(projects()) == 1


@test("7. workshops, floors on, floor refusing and no level to extend: a new classic level, not_on_floor, floor_fallback")
def _():
    need()
    r0, tiles0 = classic(kind="workshops", shops=["Masons"], style=STYLE)
    _reset()
    floors(answer="refuse")
    r = start(kind="workshops", shops=["Masons"], style=STYLE)
    assert r.ok and r.joined is None and same_site(r, r0) and designated() == tiles0, dict(r)
    assert r.not_on_floor == "no room" and F.calls.fallback == 1 and F.fallback.kind == "workshops"
    assert project(1).params.spare == 3 and project(1).params.join_steps is None


@test("7. a floor's workshops project (p.floor set) is never offered as a level to join: not its free rooms, not an extension")
def _():
    need()
    standing_level(["Smelter"])                                # a classic level with 3 free rooms: it takes the next shop
    r = start(kind="workshops", shops=["MetalsmithsForge"], style=STYLE)
    assert r.ok and r.joined == 1 and r.how == "free_room", dict(r)
    _reset()
    standing_level(["Smelter"])
    project(1).floor = tbl({"id": 3, "slots": 1, "hall": 9})   # ... were the same level a floor's: a new level
    r = start(kind="workshops", shops=["MetalsmithsForge"], style=STYLE)
    assert r.ok and r.joined is None and r.project_id == 2, dict(r)
    assert project(1).free_left == 3 and project(1).taken is None
    _reset()
    standing_level(["Millstone"], spare=0)                     # nor is a floor's level extended
    project(1).floor = tbl({"id": 3, "slots": 1, "hall": 9})
    r = start(kind="workshops", shops=["Quern"], spare=0, style=STYLE)
    assert r.ok and r.joined is None and project(1).ext_tiles is None, dict(r)
    # and a real floor project of workshops, standing: the next shop does not go into it
    _reset()
    floors()
    r1 = start(kind="workshops", shops=["Masons"], spare=0, style=STYLE)
    assert r1.ok and r1.floor.id == 3 and project(1).floor.id == 3, dict(r1)
    dig_all()
    project(1).phase = "done"
    F.mode = "classic"
    r2 = start(kind="workshops", shops=["Mechanics"], style=STYLE)
    assert r2.ok and r2.joined is None and project(2).parent is None, dict(r2)


@test("7. join_steps: join_workshop_level takes only the steps named ({'free'}: no extension), both without it")
def _():
    need()
    standing_level(["Millstone"], spare=0)
    d = W.persist["ai-overseer/projects"]
    now = LUA.table_from({"year": 255, "tick": 100})
    call = LUA.eval("""function(B, data, now, steps)
      local params = {kind = 'workshops', shops = {'Quern'}, spare = 0, style = {}, join_steps = steps}
      local r = B.join_workshop_level(params, data, now, true, {}, nil)
      return r and r.how or nil end""")
    assert call(B, d, now, tbl(["free"])) is None
    assert call(B, d, now, None) == "extension"
    assert call(B, d, now, tbl(["extend"])) == "extension"
    assert call(B, d, now, "free") == "extension", "a join_steps that is no table counts as none"


# --- 8. the lifecycle of a floor project ---------------------------------------------

@test("8. a floor project's lifecycle from its saved cells: dig progress, furnish_project, finish_project (floor_book_piles once)")
def _():
    need()
    B.furnish_progress = LUA.eval("function() return {placed = 1, done = 1, waiting = {}} end")
    floors()
    r = start(kind="dining", tables=8, style={"smooth": 3})
    assert r.ok and r.floor.id == 3, dict(r)
    o = B.projects_report().open[1]
    assert o.id == 1 and o.dig.total == 18 and o.dig.dug == 0 and o.next != "furnish", (dict(o.dig), o.next)
    assert not B.furnish_project(1, True).ok
    dig_all()
    o = B.projects_report().open[1]
    assert o.dig.dug == o.dig.total == 18 and o.next == "furnish", (dict(o.dig), o.next)
    f = B.furnish_project(1, True)
    assert f.ok and f.placed.build == 1 and f.placed.place == 1 and f.placed.zone == 1 and f.placed.smooth == 3, dict(f.placed)
    placed = sorted((c.mode, c.x, c.y, c.z, c.text) for c in lua_list(W.placed))
    assert placed == [("build", 60, 70, 72, "wM"), ("place", 59, 66, 72, "s(3x1)"), ("zone", 59, 69, 72, "m(3x3)")], placed
    assert F.calls.book == 0
    fin = B.finish_project(1)
    assert fin.ok and fin.phase == "done", dict(fin)
    assert F.calls.book == 1 and F.booked.id == 1 and F.booked.phase == "done" and F.booked.piles[1].shop == "Masons"
    assert not B.finish_project(1).ok and F.calls.book == 1, "a refused finish books nothing"
    assert F.calls.release == 0 and project(1).floor.id == 3


@test("8. finish_project on a classic project, and one that is refused: floor_book_piles is not called")
def _():
    need()
    B.furnish_progress = LUA.eval("function() return {placed = 2, done = 1, waiting = {Bed = 1}} end")
    floors()
    r = start(kind="dining", tables=8)
    dig_all()
    assert B.furnish_project(1, True).ok
    assert not B.finish_project(1).ok and F.calls.book == 0          # a building still waiting
    _reset()
    B.furnish_progress = LUA.eval("function() return {placed = 1, done = 1, waiting = {}} end")
    floors(answer="refuse")
    r = start(kind="storage", piles=["food"], style={"smooth": 0})
    assert r.ok and project(1).floor is None
    dig_all()
    assert B.furnish_project(1, True).ok and B.finish_project(1).ok
    assert F.calls.book == 0 and F.calls.release == 0, dict(F.calls)


@test("8. cancel_project on a floor project: its designations are taken back, floor_release once (after the save); a classic one: not called")
def _():
    need()
    floors()
    r = start(**BED)
    assert r.ok and designated() == FLOOR_TILES
    c = B.cancel_project(1)
    assert c.ok and designated() == set() and project(1).phase == "cancelled", dict(c)
    assert F.calls.release == 1 and F.released.id == 1 and F.released.phase == "cancelled" and F.released.floor.id == 3
    assert not B.cancel_project(1).ok and F.calls.release == 1, "a refused cancel releases nothing"
    assert not B.cancel_project(99).ok and F.calls.release == 1
    F.answer = "refuse"
    r = start(**BED)
    assert r.ok and project(2).floor is None
    assert B.cancel_project(2).ok and F.calls.release == 1 and designated() == set()


@test("8. an urgent floor level: prioritized leaves the hall's d1 cells alone and makes the rooms d2, as today's urgent levels")
def _():
    need()
    floors()
    r = start(urgent=True, **BED)
    assert r.ok and r.tiles == 18 and r.designated == 18 and designated() == FLOOR_TILES, dict(r)
    p = project(1)
    assert p.urgent is True
    cells = dig_cells(p)
    assert cells[:9] == HALL_CELLS, cells
    assert sorted(cells[9:]) == sorted((x, y, "d2") for x in (-1, 0, 1) for y in (9, 10, 11)), cells[9:]
    texts = {(k, t.dig_text) for k, t in W.tiles.items() if t.designated}
    assert {t for _k, t in texts} == {"d1", "d2"} and sum(1 for _k, t in texts if t == "d2") == 9
    dig_all()
    o = B.projects_report().open[1]
    assert o.dig.dug == o.dig.total == 18 and o.next == "furnish", (dict(o.dig), o.next)


# --- 9. the refusals that come first -------------------------------------------------

def fill_slots(n):
    """n open classic levels (the floors off), each on its own."""
    for i in range(n):
        r = start(kind="storage", piles=["food"], join=False, floor=False, urgent=True)
        assert r.ok, (i, dict(r))


@test("9. the open-project cap and the urgent extra slots refuse before floor_site is called; an urgent level within them is asked")
def _():
    need()
    cap = int(B.slot_cap(LUA.table()))
    extra = int(B.URGENT_EXTRA)
    fill_slots(cap)
    floors()
    r = start(**BED)
    assert not r.ok and r.rejected and "unfinished building projects" in r.error, dict(r)
    assert F.calls.site == 0 and F.calls.mode == 0 and r.not_on_floor is None, dict(F.calls)
    u = start(urgent=True, **BED)
    assert u.ok and u.floor.id == 3 and F.calls.site == 1, dict(u)
    # ... and beyond the urgent slots an urgent one is refused unasked too
    _reset()
    fill_slots(cap + extra)
    floors()
    r = start(urgent=True, **BED)
    assert not r.ok and r.rejected and "unfinished building projects" in r.error, dict(r)
    assert F.calls.site == 0 and F.calls.mode == 0, dict(F.calls)


@test("9. the unreached-stair ban refuses before floor_site is called; the stairs it is given are the ones left")
def _():
    need()
    # the game's year, and its walk groups: the dwarves cannot walk to the main stair (60,60), to all else they can
    LUA.execute("""df = df or {}; B7_DF_GLOBAL = df.global; df.global = df.global or {cur_year = 10, cur_year_tick = 0}
      B7_MAPS = dfhack.maps
      dfhack.maps = {getWalkableGroup = function(p) return (p.x == 60 and p.y == 60) and 0 or 1 end}""")
    try:
        r1 = start(**BED)                                      # a classic level, given up as out of reach
        assert r1.ok
        assert B.cancel_project(1, True).ok and project(1).unreached is True
        floors()
        r = start(**BED)
        assert not r.ok and "given up as out of reach" in r.error, dict(r)
        assert F.calls.site == 0 and r.not_on_floor is None, dict(F.calls)
        # a second stair nobody gave up on: the floor is asked, with that stair only and the banned area reserved
        TB._stair(68, 60, 66, 80)                              # (within 10 tiles of the dwarves)
        r = start(**BED)
        assert r.ok and F.calls.site == 1, dict(r)
        a = F.site_args
        assert [(s.x, s.y) for s in lua_list(a.stairs)] == [(68, 60)], [(s.x, s.y) for s in lua_list(a.stairs)]
        assert len(lua_list(a.reserved)) == 1 and a.reserved[1].z == r1.z
    finally:
        LUA.execute("df.global = B7_DF_GLOBAL; B7_DF_GLOBAL = nil; dfhack.maps = B7_MAPS; B7_MAPS = nil")


@test("9. an unknown kind or a bad parameter is refused before the floor is asked")
def _():
    need()
    floors()
    r = start(kind="ballroom")
    assert not r.ok and r.rejected and F.calls.site == 0 and F.calls.mode == 0, dict(r)


# --- 10. the guards in the source ----------------------------------------------------

@plain_test("10. the guards are in the source: every floor call behind type(...) == 'function', the outside ones behind pcall")
def _():
    start_src = SRC[SRC.index("function start_project("):SRC.index("function cells_of(")]
    for snippet in (
        "local floors_on = type(floor_site) == 'function' and type(floor_mode) == 'function'",
        "and FLOOR_KINDS and FLOOR_KINDS[kind] and params.floor ~= false and params.join ~= false",
        "and floor_mode() == 'hallway'",
        "if floors_on and kind == 'workshops' then params.join_steps = {'free'} end",
        "pcall(floor_site, params, stairs, reserved, data, ceil and (ceil - OFFSET) or nil)",
        "floor_why = tostring(okf and L2 or s2):sub(1, 300)",
        "if not site and floors_on and kind == 'workshops' then",
        "if not site then site, why2 = choose_site(L, stairs, reserved, plan, ceil and (ceil - OFFSET) or nil) end",
        "if not site then return {ok = false, error = why2, not_on_floor = floor_why} end",
        "if site.floor and type(floor_commit) == 'function' then pcall(floor_commit, site, p.id)",
        "elseif floors_on and floor_why and type(floor_fallback) == 'function' then "
        "pcall(floor_fallback, kind, floor_why, ez(site.z), floor_marks)",
        # (tests/test_traffic.py pins the record's own line, so the floor's links are set right under the record)
        "links = extra_list(site.extra),",
        "if site.links then p.links = site.links end",
        "areas = site.areas,",
        "floor = site.floor,",
    ):
        assert code_has(start_src, snippet), snippet
    assert start_src.count("floor = site.floor_result, not_on_floor = floor_why") == 2, "the dry run's answer and the real one"
    # no floor function is called bare anywhere in the file
    assert code_has(SRC, "if p.floor and type(floor_release) == 'function' then pcall(floor_release, p) end")
    assert code_has(SRC, "if p.floor and type(floor_book_piles) == 'function' then pcall(floor_book_piles, p) end")
    for name in ("floor_site", "floor_commit", "floor_fallback", "floor_release", "floor_book_piles"):
        bare = [ln.strip() for ln in SRC.splitlines()
                if name + "(" in ln.split("--")[0] and "type(" + name + ")" not in ln]
        assert bare == [], (name, bare)
    assert SRC.count("floor_mode()") == 1 and "reqscript('ai-floor" not in SRC and 'reqscript("ai-floor' not in SRC
    # the order: the cap, then floors_on, then the free-room join, then the stairs and the ban, then the floor
    order = [start_src.index(s) for s in ("unfinished building projects", "local floors_on", "params.join_steps = {'free'}",
                                          "find_stairs(STAIRS_TO_TRY)", "unreached_stairs_dropped", "pcall(floor_site",
                                          "choose_site(L,", "if site.links then p.links = site.links end",
                                          "save_projects(data)", "pcall(floor_commit")]
    assert order == sorted(order), order


@plain_test("10. join_workshop_level: a floor's project is filtered out, and the steps can be named")
def _():
    join_src = SRC[SRC.index("function join_workshop_level("):SRC.index("function start_project(")]
    assert code_has(join_src, "p.kind == 'workshops' and p.parent == nil and p.floor == nil")
    assert code_has(join_src, "for _, step in ipairs(type(params.join_steps) == 'table' and params.join_steps "
                              "or {'free', 'extend'}) do")
    cancel_src = SRC[SRC.index("function cancel_project("):]
    cancel_src = cancel_src[:cancel_src.index("return {ok = true, project_id = id}")]
    assert cancel_src.rindex("save_projects(data)") < cancel_src.index("pcall(floor_release, p)")
    fin = SRC[SRC.index("function finish_project("):SRC.index("function engrave_project(")]
    assert fin.rindex("save_projects(data)") < fin.index("pcall(floor_book_piles, p)") < fin.rindex("return {ok = true, project_id = id, phase = p.phase")


if __name__ == "__main__":
    finish()
