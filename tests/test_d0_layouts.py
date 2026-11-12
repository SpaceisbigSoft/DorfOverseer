"""(D0 G4) Layouts follow the design language: lua/ai-layouts.lua's new hall
shapes, motifs, scale, aspect, arms and grand, and the bridge's parse_style.

    python tests/test_d0_layouts.py            run the tests
    python tests/test_d0_layouts.py --show     also draw a few new layouts

The snapshot (tests/fixtures/d0_layouts_snapshot.json, made from main's
ai-layouts.lua by tests/d0_layout_snapshot.py before any change) proves that
every layout made with today's style fields is byte-identical.
"""

from __future__ import annotations

import ast
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import d0_layout_snapshot as snap  # noqa: E402

LUA, M, SER = snap.lua_runtime()

# every tile of every phase's cells, the dig cells' coverage and the build
# tiles, flattened for Python
FLAT = LUA.eval(r"""function(L, M)
  local out = {tiles = {}, dig = {}, build = {}, place = {}, zone = {}, halls = {}, furniture = {}, dup = false}
  for x, col in pairs(L.tiles) do for y in pairs(col) do table.insert(out.tiles, {x, y}) end end
  for _, c in ipairs(L.dig) do
    local w, h = 1, 1
    local ew, eh = tostring(c.text):match('^d%((%d+)x(%d+)%)$')
    if ew then w, h = tonumber(ew), tonumber(eh) end
    for dx = 0, w - 1 do for dy = 0, h - 1 do table.insert(out.dig, {c.x + dx, c.y + dy}) end end
  end
  for _, phase in ipairs({'build', 'place', 'zone'}) do
    for _, c in ipairs(L[phase]) do table.insert(out[phase], {c.x, c.y, c.text}) end
  end
  for _, h in ipairs(L.halls) do table.insert(out.halls, {h.x, h.y, h.w, h.h}) end
  for k, v in pairs(L.furniture) do out.furniture[k] = v end
  -- to_data on every phase: two cells on one tile raise
  for _, phase in ipairs({'dig', 'build', 'place', 'zone', 'smooth', 'engrave'}) do
    local ok, err = pcall(M.to_data, L[phase], 0)
    if not ok then out.dup = phase .. ': ' .. tostring(err) end
  end
  return out
end""")


def to_lua(v):
    return snap.to_lua(LUA, v)


def make(kind, params, style=None):
    p = dict(params)
    if style is not None:
        p["style"] = style
    res = M.make(kind, to_lua(p))
    L, err = res if isinstance(res, tuple) else (res, None)
    assert L is not None, (kind, params, style, err)
    return L


def flat(L):
    f = FLAT(L, M)
    def pts(t):
        return [tuple(int(v) if not isinstance(v, str) else v for v in e.values()) for e in t.values()]
    return {"tiles": set(pts(f.tiles)), "dig": pts(f.dig), "build": pts(f.build), "place": pts(f.place),
            "zone": pts(f.zone), "halls": pts(f.halls), "furniture": dict(f.furniture), "dup": f.dup}


WORKSHOP_KEYS = set(dict(M.WORKSHOPS).values())


def connected(tiles: set, start_from_stair: bool = True) -> set:
    """The tiles 8-connected to the stair (the stair tile itself is open: it is a staircase)."""
    open_ = set(tiles) | {(0, 0)}
    seen, stack = {(0, 0)}, [(0, 0)]
    while stack:
        x, y = stack.pop()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if n in open_ and n not in seen:
                    seen.add(n)
                    stack.append(n)
    return seen


def check_layout(kind, params, style, base_furniture):
    """The checks every new layout must pass; returns the flattened layout."""
    L = make(kind, params, style)
    f = flat(L)
    tiles = f["tiles"]
    where = f"{kind} {params} {style}"
    assert (0, 0) not in tiles, f"stair tile dug: {where}"
    assert not f["dup"], f"to_data: {f['dup']}: {where}"
    # the dig cells cover exactly the tiles, each once (Quickfort counts must match)
    assert len(f["dig"]) == len(set(f["dig"])) == len(tiles) and set(f["dig"]) == tiles, f"dig overlap: {where}"
    # every dug tile reaches the hub
    reach = connected(tiles)
    assert tiles <= reach, f"{len(tiles - reach)} dug tiles cut off: {where}"
    # every building stands on dug floor (a workshop on its 3x3); statues block, so the rest
    # must still be walkable round them
    statues = set()
    for x, y, text in f["build"]:
        if text in WORKSHOP_KEYS:
            need = {(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        else:
            need = {(x, y)}
        assert need <= tiles, f"{text} at {x},{y} not on dug floor: {where}"
        if text == "s":
            statues.add((x, y))
    walk = connected(tiles - statues)
    assert (tiles - statues) <= walk, f"statues cut off {len((tiles - statues) - walk)} tiles: {where}"
    for x, y, text in f["place"]:
        m = re.match(r"^\w+\((\d+)x(\d+)\)$", text)
        w, h = (int(m.group(1)), int(m.group(2))) if m else (1, 1)
        cover = {(x + dx, y + dy) for dx in range(w) for dy in range(h)}
        assert len(cover & tiles) >= len(cover) * 0.8, f"pile {text} off the floor: {where}"
    # furniture counts unchanged by the style
    assert f["furniture"] == base_furniture, f"furniture {f['furniture']} != {base_furniture}: {where}"
    # halls inside HALL_MAX (or the kind's own size, when that is larger)
    mx = M.HALL_MAX[kind]
    is_hall = mx is not None and (kind != "bedrooms" or params.get("dormitory")) \
        and not (kind == "tombs" and style.get("arms", "corridor") != "corridor")
    if is_hall:
        bw, bh = BASE_HALL[(kind, json.dumps(params, sort_keys=True))]
        hx, hy, hw, hh = f["halls"][0]
        if style.get("orient", 0) >= 2:                      # turned north-south
            hw, hh = hh, hw
        assert hw <= max(mx.w, bw) and hh <= max(mx.h, bh), f"hall {hw}x{hh}: {where}"
        assert hw >= bw and hh >= bh, f"hall {hw}x{hh} smaller than {bw}x{bh}: {where}"
    return f


# (kind, params) for the new-key grid: every kind, at its largest and a small size
GRID = [
    ("bedrooms", {"rooms": 5, "room_size": 2}), ("bedrooms", {"rooms": 32, "room_size": 4}),
    ("bedrooms", {"rooms": 20, "dormitory": True}),
    ("suites", {"suites": 3}), ("suites", {"suites": 8}),
    ("jail", {"cells": 1}), ("jail", {"cells": 8}),
    ("dining", {"tables": 4}), ("dining", {"tables": 90}),
    ("storage", {"piles": ["food", "stone"], "room_size": 11}),
    ("storage", {"piles": ["food", "stone", "wood", "furniture", "gems", "ammo", "cloth", "leather",
                           "weapons", "armor", "bars_blocks", "finished_goods"], "room_size": 5}),
    ("workshops", {"shops": ["Still"]}),
    ("workshops", {"shops": ["Still", "Kitchen", "Masons", "Carpenters", "Craftsdwarfs", "Loom", "Smelter",
                             "Tanners", "Bowyers", "Jewelers", "Mechanics", "Kiln"]}),
    ("temple", {"size": "shrine"}), ("temple", {"size": "grand", "deity_hf": 3}),
    ("memorial", {"name": "Shulmik the Jackalowls"}),
    ("garden", {"name": "Copper"}),
    ("hospital", {"beds": 20}), ("barracks", {"beds": 4}), ("barracks", {"beds": 20}),
    ("tombs", {"coffins": 4}), ("tombs", {"coffins": 30}),
    ("tavern", {"tables": 20}), ("library", {"bookcases": 20}),
    ("archery", {"lanes": 3, "length": 16}),
]
HALLS = sorted(dict(M.HALLS).keys())
ARMS = ["corridor", "cross", "ring"]
MOTIFS = ["rows", "ring", "cross", "spiral", "star", "wave"]
BASE_FURNITURE = {}
BASE_HALL = {}
for _k, _p in GRID:
    _f = flat(make(_k, _p, {"statues": 4}))
    BASE_FURNITURE[(_k, json.dumps(_p, sort_keys=True))] = _f["furniture"]
    BASE_HALL[(_k, json.dumps(_p, sort_keys=True))] = (_f["halls"][0][2], _f["halls"][0][3]) if _f["halls"] else (0, 0)


def grid_cases(extra=None):
    for kind, params in GRID:
        base = BASE_FURNITURE[(kind, json.dumps(params, sort_keys=True))]
        for hall in HALLS:
            for arms in ARMS:
                for motif in MOTIFS:
                    for scale in (80, 150):
                        style = {"hall": hall, "arms": arms, "motif": motif, "scale": scale, "statues": 4}
                        if extra:
                            style.update(extra)
                        yield kind, params, style, base


@test("the snapshot: every kind x today's style fields is byte-identical to main's")
def _():
    want = json.loads(snap.FIXTURE.read_text(encoding="utf-8"))["cases"]
    got = snap.snapshot()
    assert set(got) == set(want), set(got) ^ set(want)
    bad = []
    for group, hashes in want.items():
        for i, (a, b) in enumerate(zip(got[group], hashes)):
            if a != b:
                bad.append((group, i))
    assert not bad, f"{len(bad)} layouts changed, e.g. {bad[:5]}"
    assert sum(map(len, want.values())) > 5000


@test("style defaults (scale 100, corridor, rows, no aspect, not grand) give today's layout exactly")
def _():
    for kind, params in GRID:
        for st in ({}, {"hall": "pillared", "statues": 3}):
            plain = SER(make(kind, params, st))
            dflt = SER(make(kind, params, {**st, "scale": 100, "arms": "corridor", "motif": "rows",
                                           "grand": False}))
            bogus = SER(make(kind, params, {**st, "arms": "spokes", "motif": "axe", "aspect": "tall",
                                            "scale": "big"}))
            assert plain == dflt == bogus, (kind, params, st)


@test("every kind x every hall x arms x motif x scale 80/150: connected, no stair tile, no two cells, "
      "furniture unchanged, inside HALL_MAX")
def _():
    t0 = time.perf_counter()
    n = 0
    for kind, params, style, base in grid_cases():
        check_layout(kind, params, style, base)
        n += 1
    assert n == len(GRID) * len(HALLS) * len(ARMS) * len(MOTIFS) * 2
    print(f"    ({n} layouts in {time.perf_counter() - t0:.1f}s)")


@test("aspect, grand and every orient over the new shapes and arms pass the same checks")
def _():
    for extra in ({"aspect": "long"}, {"aspect": "wide"}, {"aspect": "square"}, {"grand": True},
                  {"orient": 1, "rhythm": 3}, {"orient": 2, "spacing": 60}, {"orient": 3, "rhythm": 6},
                  {"customs": ["cloister", "armoury", "ore_piles"]}):
        for kind, params, style, base in grid_cases(extra):
            # every hall and arms, at scale 150, with the rows or the star motif in turn
            turn = (HALLS.index(style["hall"]) + ARMS.index(style["arms"])) % 2
            if style["scale"] == 150 and style["motif"] == ("star" if turn else "rows"):
                check_layout(kind, params, style, base)


@test("hall_mask: plain cuts nothing; rounded/pillared the 4 corners; octagonal, round, cruciform, nave")
def _():
    def cut(shape, w, h):
        skip, pillars = M.hall_mask(shape, 0, 0, w, h, None, 4)
        out = {(int(x), int(y)) for x, col in skip.items() for y in col.keys()}
        return out, [(int(p.x), int(p.y)) for p in pillars.values()]
    assert cut("plain", 9, 9) == (set(), [])
    assert cut("rounded", 9, 9)[0] == cut("pillared", 9, 9)[0] == {(0, 0), (8, 0), (0, 8), (8, 8)}
    octo, _ = cut("octagonal", 12, 12)               # corners at w/4 = 3: 6 tiles a corner
    assert len(octo) == 24 and (2, 0) in octo and (3, 0) not in octo and (0, 2) in octo
    rnd, _ = cut("round", 11, 11)                    # a circle: symmetric, centre and axis ends kept
    assert (5, 5) not in rnd and (0, 5) not in rnd and (5, 0) not in rnd and (0, 0) in rnd
    assert rnd == {(10 - x, y) for x, y in rnd} == {(y, x) for x, y in rnd}
    stad, _ = cut("round", 21, 9)                    # long: round ends, straight sides
    assert (10, 0) not in stad and (0, 0) in stad and (0, 1) in stad and (1, 1) not in stad
    assert all((x, 4) not in stad for x in range(21))       # the middle row runs end to end
    cross, _ = cut("cruciform", 12, 12)              # arms half the width: 3x3 cut from each corner
    assert len(cross) == 4 * 9 and (5, 0) not in cross and (0, 5) not in cross and (2, 2) in cross
    nave, pillars = cut("nave", 21, 9)
    assert nave == set() and pillars and {y for _, y in pillars} == {2, 6}
    assert all(abs(a[0] - b[0]) >= 4 for a in pillars for b in pillars if a != b and a[1] == b[1])


@test("motif_mask: rows is today's pillars and far-wall statues; each form gives distinct spots inside the hall")
def _():
    def spots(form, x=2, y=-5, w=21, h=11):
        p, s = M.motif_mask(form, x, y, w, h, 4)
        return [(int(q.x), int(q.y)) for q in p.values()], [(int(q.x), int(q.y)) for q in s.values()]
    p, s = spots("rows", 2, -5, 15, 11)
    # a grand temple's: pillars at x = 5, 9, 13 on rows top+2 and top+h-3; statues down x = 2+w-2
    assert sorted(p) == sorted([(x, y) for x in (5, 9, 13) for y in (-3, 3)]), p
    assert s[:3] == [(15, 0), (15, -2), (15, 2)]
    seen = set()
    for form in MOTIFS:
        p, s = spots(form)
        assert p and s, form
        for x, y in p + s:
            assert 2 < x < 22 and -5 < y < 5, (form, x, y)
        assert len(set(p)) == len(p) and len(set(s)) == len(s)
        seen.add((tuple(sorted(p)), tuple(sorted(s))))
    assert len(seen) == len(MOTIFS)        # six different placements


@test("motifs move the statues: a dining hall's statues stand on the star's spots, not today's row")
def _():
    base = flat(make("dining", {"tables": 30}, {"statues": 4}))
    star = flat(make("dining", {"tables": 30}, {"statues": 4, "motif": "star"}))
    ring = flat(make("dining", {"tables": 30}, {"statues": 4, "motif": "ring", "hall": "pillared"}))
    st = lambda f: sorted((x, y) for x, y, t in f["build"] if t == "s")  # noqa: E731
    assert len(st(base)) == len(st(star)) == len(st(ring)) == 4
    assert st(base) != st(star) != st(ring)
    assert all(y == 5 for _, y in st(base))
    # a pillared ring hall has its pillars on the ring, not today's two rows
    pill_today = flat(make("dining", {"tables": 30}, {"hall": "pillared"}))
    assert pill_today["tiles"] != ring["tiles"]


@test("scaled: scale and aspect only add floor, capped by HALL_MAX; the depth stays centred; nave is long")
def _():
    def sc(kind, w, h, **st):
        r = M.scaled(kind, w, h, to_lua(st))
        return int(r[0]), int(r[1])
    assert sc("dining", 22, 11) == (22, 11)
    assert sc("dining", 22, 11, scale=80) == (22, 11)
    assert sc("dining", 22, 11, scale=150) == (33, 17)
    assert sc("dining", 62, 11, scale=150) == (64, 17)          # capped
    assert sc("tombs", 33, 7, scale=150) == (41, 11)
    w, h = sc("hospital", 23, 7, aspect="long")
    assert w > 23 and h == 7
    w, h = sc("hospital", 23, 7, aspect="wide")
    assert w == 23 and h > 7 and (h - 7) % 2 == 0
    assert sc("hospital", 23, 7, grand=True) == (28, 9)          # at least 120
    assert sc("temple", 7, 7, hall="round") == (9, 9)            # a new shape's margin
    assert sc("hospital", 23, 7, hall="nave")[0] > sc("hospital", 23, 7, hall="octagonal")[0]   # long
    assert sc("archery", 12, 5, scale=150) == (12, 5)            # no HALL_MAX: unchanged
    big = sc("dining", 200, 31, scale=150)
    assert big == (200, 31)                                      # never smaller than the kind's own


@test("cross and ring arms: the same slots, rooms on all four sides, furnished in the room, no room across an axis")
def _():
    for arms in ("cross", "ring"):
        f = flat(make("bedrooms", {"rooms": 16, "room_size": 3}, {"arms": arms}))
        beds = [(x, y) for x, y, t in f["build"] if t == "b"]
        assert len(beds) == 16
        quads = {(x > 0) - (x < 0) for x, _ in beds}, {(y > 0) - (y < 0) for _, y in beds}
        assert quads[0] >= {-1, 1} and quads[1] >= {-1, 1}, (arms, beds)
        zones = [(x, y, t) for x, y, t in f["zone"]]
        for (x, y, t) in zones:                       # each zone covers its own room and its bed
            w, h = map(int, re.match(r"b\((\d+)x(\d+)\)", t).groups())
            assert {(x + dx, y + dy) for dx in range(w) for dy in range(h)} <= f["tiles"]
        for bx, by in beds:
            assert sum(1 for x, y, t in zones if x <= bx < x + 3 and y <= by < y + 3) == 1
        doors = [(x, y) for x, y, t in f["build"] if t == "d"]
        assert len(doors) == 16
    # ring: nothing dug on an axis beyond the loop but the loop itself, so a corridor from the fort
    # comes in along an axis to the loop, not through a room
    f = flat(make("storage", {"piles": ["food", "stone", "wood", "gems", "ammo"], "room_size": 5}, {"arms": "ring"}))
    xs = sorted({y for x, y in f["tiles"] if x == 0 and y < 0})
    outer = min(xs)
    assert not any((x, outer - 1) in f["tiles"] for x in (-1, 0, 1))
    # workshops on a cross: each centred in its 5x5 room, wide openings kept
    f = flat(make("workshops", {"shops": ["Still", "Kitchen", "Masons", "Carpenters", "Loom"]}, {"arms": "cross"}))
    for x, y, t in f["build"]:
        assert {(x + dx, y + dy) for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2)} <= f["tiles"]


@test("tombs on cross or ring arms: crypts, three coffins a room, a tomb zone each")
def _():
    for arms in ("cross", "ring"):
        f = flat(make("tombs", {"coffins": 10}, {"arms": arms}))
        coffins = [(x, y) for x, y, t in f["build"] if t == "n"]
        tombs = [(x, y) for x, y, t in f["zone"] if t == "T{citizens=true}"]
        assert len(coffins) == 10 and sorted(coffins) == sorted(tombs)


@test("grand: halls engraved, at least scale 120; a room level's corridors engraved too")
def _():
    L = make("dining", {"tables": 12}, {"grand": True})
    assert L.engrave_all and len(list(L.engrave.values())) > 0
    plain = make("dining", {"tables": 12})
    assert L.halls[1].w > plain.halls[1].w and L.halls[1].h > plain.halls[1].h
    for arms in ARMS:
        R = make("bedrooms", {"rooms": 8, "room_size": 3}, {"grand": True, "arms": arms})
        assert R.engrave_all and len(list(R.halls.values())) >= 2 and len(list(R.engrave.values())) > 0, arms
        assert len(list(make("bedrooms", {"rooms": 8, "room_size": 3}, {"arms": arms}).engrave.values())) == 0


# --- on test_builder's fake fort --------------------------------------------------------------

_tree = ast.parse((ROOT / "tests" / "test_builder.py").read_text(encoding="utf-8"))
HARNESS = next(n.value.value for n in _tree.body
               if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "HARNESS")


def to_lua_in(lua, v):
    return snap.to_lua(lua, v)


def boot_fort():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(ROOT / "lua")
    layouts = (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8")
    builder = (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8")
    B, W = lua.execute(HARNESS, layouts, builder)
    return lua, B, W


@test("the new layouts pass check_site on test_builder's fake fort (natural rock, a stair at the centre)")
def _():
    lua, B, W = boot_fort()
    W.size[1], W.size[2] = 240, 240
    W.reset()
    LAY = lua.globals().LAYOUTS
    n = 0
    for kind, params in GRID:
        for hall in HALLS:
            for arms in ARMS:
                for motif, scale, orient in (("star", 150, 0), ("spiral", 80, 3), ("wave", 150, 1)):
                    p = to_lua_in(lua, {**params, "style": {"hall": hall, "arms": arms, "motif": motif,
                                                            "scale": scale, "orient": orient, "statues": 4}})
                    res = LAY.make(kind, p)
                    L = res[0] if isinstance(res, tuple) else res
                    ok = B.check_site(L, lua.table(), 120, 120, 40, lua.table(), lua.table_from({"x": 0, "y": 0}))
                    ok, why = (ok[0], ok[1]) if isinstance(ok, tuple) else (ok, None)
                    assert ok, (kind, params, hall, arms, motif, why)
                    n += 1
    assert n > 1000


@test("start_project on the fake fort: a ring of bedrooms, a cross of workshops and a round star dining hall "
      "dig exactly their tiles, and furnish")
def _():
    lua, B, W = boot_fort()
    W.reset()
    B.TRY_BESIDE = True
    for params in ({"kind": "bedrooms", "rooms": 12, "room_size": 3, "style": {"arms": "ring", "smooth": 1}},
                   {"kind": "workshops", "shops": ["Still", "Kitchen", "Masons"], "style": {"arms": "cross"}},
                   {"kind": "dining", "tables": 12, "style": {"hall": "round", "motif": "star", "statues": 3,
                                                              "scale": 130}},
                   {"kind": "temple", "size": "grand", "style": {"hall": "nave", "statues": 2, "grand": True}}):
        W.reset()
        r = B.start_project(to_lua_in(lua, params), lua.table_from({"year": 148, "tick": 100}))
        assert r.ok, (params, r.error)
        # (start_project's own dry run already refused any count but the layout's tiles)
        designated = sum(1 for t in W.tiles.values() if t.designated)
        assert designated >= r.tiles > 0, (params["kind"], designated, r.tiles)
        for t in W.tiles.values():
            if t.designated:
                t.shape, t.designated = "FLOOR", False
        B.furnish_progress = lua.eval("function() return {placed = 0, done = 0, waiting = {}} end")
        f = B.furnish_project(r.project_id, True)
        assert f.ok, (params["kind"], f.error)


# --- the bridge's parse_style (d0-spec 1.4) ---------------------------------------------------

def bridge_parse_style(with_layouts=True):
    src = (ROOT / "lua" / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    fn = re.search(r"\nlocal function parse_style\(st\)\n.*?\nend\n", src, re.S).group(0)
    lua = LuaRuntime(unpack_returned_tuples=True)
    lay = (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8")
    parse = lua.execute("""
        local lay_src, with_layouts = ...
        local LAY = setmetatable({}, {__index = _G})
        assert(load(lay_src, 'ai-layouts', 't', LAY))()
        function reqscript(name)
            if name == 'ai-layouts' and with_layouts then return LAY end
            error('no ' .. name)
        end
        function int_in(v, lo, hi)
            v = math.tointeger(tonumber(v)); if v == nil or v < lo or v > hi then return nil end; return v
        end
    """ + fn + "\nreturn parse_style", lay, with_layouts)
    def call(st):
        res = parse(to_lua_in(lua, st))
        return res if isinstance(res, tuple) else (res, None)
    return call


@test("parse_style: takes the new keys (hall from ai-layouts.HALLS, scale, aspect, arms, motif, grand)")
def _():
    for with_layouts in (True, False):
        parse = bridge_parse_style(with_layouts)
        for hall in HALLS:
            out, err = parse({"hall": hall})
            assert err is None and out.hall == hall, (hall, err)
        out, err = parse({"hall": "nave", "scale": 150, "aspect": "long", "arms": "ring", "motif": "spiral",
                          "grand": True, "smooth": 2, "statues": 3, "orient": 3, "rhythm": 5})
        assert err is None, err
        assert (out.scale, out.aspect, out.arms, out.motif, out.grand) == (150, "long", "ring", "spiral", True)
        # the old keys come out as before, and the new ones stay unset when not given
        out, err = parse({"hall": "pillared"})
        assert err is None and out.scale is None and out.aspect is None and out.arms is None
        assert out.motif is None and out.grand is None and out.hall == "pillared"


@test("parse_style: refuses bad values of the new keys, with words")
def _():
    parse = bridge_parse_style()
    for st, words in (({"hall": "gothic"}, "style.hall must be one of"),
                      ({"scale": 79}, "style.scale must be 80-150"), ({"scale": 151}, "80-150"),
                      ({"scale": "big"}, "80-150"), ({"scale": 99.5}, "80-150"),
                      ({"aspect": "tall"}, "style.aspect must be square, long or wide"),
                      ({"arms": "spokes"}, "style.arms must be corridor, cross or ring"),
                      ({"motif": "axe"}, "style.motif must be one of"),     # a symbol, not a form
                      ({"grand": "yes"}, "style.grand must be true or false")):
        out, err = parse(st)
        assert out is None and err and words in err, (st, err)
    out, err = parse({"hall": "gothic"})
    for h in HALLS:
        assert h in err


@test("the changed Lua compiles under 5.3")
def _():
    lua = LuaRuntime()
    check = lua.eval("function(src, name) local f, err = load(src, name, 't', {}); return f ~= nil, err end")
    for name in ("ai-layouts.lua", "ai-bridge-actions.lua"):
        ok, err = check((ROOT / "lua" / name).read_text(encoding="utf-8"), name)
        assert ok, err


def draw(f) -> str:
    tiles = f["tiles"]
    xs = [x for x, _ in tiles] + [0]
    ys = [y for _, y in tiles] + [0]
    marks = {(x, y): t[0] for x, y, t in f["build"]}
    rows = []
    for y in range(min(ys) - 1, max(ys) + 2):
        row = ""
        for x in range(min(xs) - 1, max(xs) + 2):
            row += "X" if (x, y) == (0, 0) else marks.get((x, y), "." if (x, y) in tiles else "#")
        rows.append(row)
    return "\n".join(rows)


if __name__ == "__main__":
    if "--show" in sys.argv:
        for kind, params, style in (
                ("dining", {"tables": 24}, {"hall": "round", "motif": "star", "statues": 4}),
                ("dining", {"tables": 24}, {"hall": "pillared", "motif": "wave", "statues": 4}),
                ("temple", {"size": "grand"}, {"hall": "octagonal", "motif": "ring", "statues": 4}),
                ("temple", {"size": "grand"}, {"hall": "cruciform", "statues": 4}),
                ("temple", {"size": "shrine"}, {"hall": "nave", "statues": 4}),
                ("memorial", {"name": "Urist"}, {"hall": "round", "motif": "spiral", "statues": 4}),
                ("garden", {"name": "Copper"}, {"hall": "octagonal", "motif": "spiral", "scale": 150}),
                ("hospital", {"beds": 12}, {"hall": "round"}),
                ("bedrooms", {"rooms": 16, "room_size": 3}, {"arms": "cross"}),
                ("bedrooms", {"rooms": 16, "room_size": 3}, {"arms": "ring"}),
                ("workshops", {"shops": ["Still", "Kitchen", "Masons", "Loom"]}, {"arms": "ring"}),
                ("tombs", {"coffins": 12}, {"arms": "cross"})):
            print(f"\n{kind} {params} {style}\n" + draw(flat(make(kind, params, style))))
        print()
    finish()
