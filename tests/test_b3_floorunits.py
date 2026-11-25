"""Tests for lua/ai-floorunits.lua (layout B, group B3): a level cut into room
units, cells turned, the layout of a floor project composed. Run in a real
Lua engine (pip install lupa); nothing touches the game.

    python tests/test_b3_floorunits.py          run the tests
    python tests/test_b3_floorunits.py --show   also draw the worked example
    python tests/test_b3_floorunits.py --neighbours   also run the layouts' own three test files
"""

from __future__ import annotations

import itertools
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402  (r9) ai-layouts / ai-blueprints split: the parts' texts too

try:
    import lupa  # noqa: F401
    from lupa.lua53 import LuaRuntime, LuaError
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

try:                                    # the drawing helper, when it is there (failure output only)
    sys.path.insert(0, str(ROOT / "brain" / "tools"))
    from draw_level import render as _render
except Exception:  # noqa: BLE001
    _render = None

SRC = (ROOT / "lua" / "ai-floorunits.lua").read_text(encoding="utf-8")
LAYOUTS_SRC = module_src("ai-layouts.lua")

LOADER = """function(src, name, extra)
  local env = setmetatable({}, {__index = _G})
  for k, v in pairs(extra or {}) do env[k] = v end
  assert(load(src, name, 't', env))()
  return env
end"""


def load():
    lua = LuaRuntime(unpack_returned_tuples=True)
    loader = lua.eval(LOADER)
    m = loader(LAYOUTS_SRC, "ai-layouts", None)
    # reqscript: only ai-layouts is known, and every call is counted
    lua.globals().REQ_CALLS = 0
    lua.globals().LAYOUTS_FOR_TEST = m
    req = lua.eval("""function(name)
        REQ_CALLS = REQ_CALLS + 1
        assert(name == 'ai-layouts', 'reqscript of ' .. tostring(name))
        return LAYOUTS_FOR_TEST
    end""")
    before = set(lua.globals().keys())
    f = loader(SRC, "ai-floorunits", lua.table_from({"reqscript": req}))
    return lua, m, f, before


LUA, M, F, GLOBALS_BEFORE = load()
SAME = LUA.eval("rawequal")
CALLS_AT_LOAD = LUA.globals().REQ_CALLS

# A Lua value as JSON: a tiles set ({[x] = {[y] = true}}) is given as a list
# of pairs by the helpers below; lists stay lists, records stay records.
JSON = LUA.eval("""function(v)
  local function enc(v)
    local t = type(v)
    if t == 'table' then
      local n = 0
      for _ in pairs(v) do n = n + 1 end
      if n == #v then
        local out = {}
        for _, x in ipairs(v) do out[#out + 1] = enc(x) end
        return '[' .. table.concat(out, ',') .. ']'
      end
      local out = {}
      for k, x in pairs(v) do out[#out + 1] = ('%q'):format(tostring(k)) .. ':' .. enc(x) end
      return '{' .. table.concat(out, ',') .. '}'
    elseif t == 'string' then
      return '"' .. v:gsub('[\\\\"]', function(c) return '\\\\' .. c end) .. '"'
    elseif t == 'number' or t == 'boolean' then return tostring(v)
    end
    return 'null'
  end
  return enc(v)
end""")

PAIRS = LUA.eval("""function(set)
  local out = {}
  for x, col in pairs(set or {}) do for y in pairs(col) do out[#out + 1] = {x, y} end end
  return out
end""")

LAYOUT_PY = LUA.eval("""function(L, pairs_of)
  local out = {tiles = pairs_of(L.tiles), halls = L.halls or {}, kind = L.kind}
  for _, ph in ipairs({'dig', 'build', 'place', 'zone', 'rooms_at', 'smooth', 'engrave'}) do
    out[ph] = {}
    for _, c in ipairs(L[ph] or {}) do table.insert(out[ph], {c.x, c.y, c.text}) end
  end
  if L.corridor then out.corridor = {top = L.corridor.top, width = L.corridor.width} end
  out.furniture = L.furniture; out.summary = L.summary; out.bounds = L.bounds
  return out
end""")

UNITS_PY = LUA.eval("""function(units, pairs_of)
  local out = {}
  for _, u in ipairs(units) do
    local o = {w = u.w, d = u.d, mode = u.mode, open = u.open, tag = u.tag or false,
               tiles = pairs_of(u.tiles), halls = u.halls}
    for _, ph in ipairs({'dig', 'build', 'place', 'zone', 'rooms_at'}) do
      o[ph] = {}
      for _, c in ipairs(u[ph]) do table.insert(o[ph], {c.x, c.y, c.text}) end
    end
    out[#out + 1] = o
  end
  return out
end""")


def lua_value(v):
    if isinstance(v, dict):
        return LUA.table_from({k: lua_value(x) for k, x in v.items()})
    if isinstance(v, (list, tuple)):
        return LUA.table_from([lua_value(x) for x in v])
    return v


def py(v):
    return json.loads(JSON(v))


def layout_py(L):
    d = py(LAYOUT_PY(L, PAIRS))
    d["tiles"] = {tuple(t) for t in d["tiles"]}
    for ph in ("dig", "build", "place", "zone", "rooms_at", "smooth", "engrave"):
        d[ph] = [tuple(c) for c in d[ph]]
    return d


def units_py(units):
    out = py(UNITS_PY(units, PAIRS))
    for u in out:
        u["tiles"] = {tuple(t) for t in u["tiles"]}
        for ph in ("dig", "build", "place", "zone", "rooms_at"):
            u[ph] = [tuple(c) for c in u[ph]]
    return out


def make(kind, params):
    p = dict(params)
    p["kind"] = kind
    up = F.unit_params(lua_value(p))
    res = M.make(kind, up)
    L, err = res if isinstance(res, tuple) else (res, None)
    assert L is not None, f"{kind} {params}: {err}"
    return L


def cut(kind, params, with_params=False):
    L = make(kind, params)
    res = F.cut(L, lua_value(params)) if with_params else F.cut(L)
    assert isinstance(res, tuple) and res[0] is not None, f"{kind} {params}: {res}"
    return L, res[0], res[1]


RECT = re.compile(r"^(.*)\((\d+)x(\d+)\)$", re.S)


def cell_tiles(text, x, y, prefix=None):
    """The tiles a 'key(WxH)' cell covers (any other cell: its one tile)."""
    m = RECT.match(text)
    if not m:
        return {(x, y)}
    return {(x + i, y + j) for i in range(int(m.group(2))) for j in range(int(m.group(3)))}


def dig_cover(cells):
    """Every tile the dig cells cover, and how many times in all."""
    tiles, n = set(), 0
    for x, y, text in cells:
        assert re.match(r"^d\d?(\(\d+x\d+\))?$", text), text
        t = cell_tiles(text, x, y)
        tiles |= t
        n += len(t)
    return tiles, n


# ---- placements, hand-written (ai-floorplace is another group's) -----------

DIRS = {"east": (1, 0), "west": (-1, 0), "south": (0, 1), "north": (0, -1)}
WORD = {v: k for k, v in DIRS.items()}


def slot_T(run, side, u, w, mirror=False):
    """Bay -> stair-relative for a slot: (bx, by) -> run (u + bx, side * (2 + by))."""
    ox, oy, dx, dy = run
    px, py_ = -dy, dx
    e = -1 if mirror else 1
    u0 = u + (w - 1 if mirror else 0)
    return dict(a=e * dx, b=side * px, c=e * dy, d=side * py_,
                tx=ox + u0 * dx + 2 * side * px, ty=oy + u0 * dy + 2 * side * py_)


def run_tile(run, u, v):
    ox, oy, dx, dy = run
    return ox + u * dx - v * dy, oy + u * dy + v * dx


def hall_tiles(run, u_from, u_to, hub=False):
    out = []
    if hub:
        out += [(x, y) for x in (-1, 0, 1) for y in (-1, 0, 1) if (x, y) != (0, 0)]
    for u in range(u_from, u_to + 1):
        out += [run_tile(run, u, v) for v in (-1, 0, 1)]
    return out


def placement(puts, hall, **more):
    p = dict(floor_id=more.pop("floor_id", 1), new_floor=True, req=dict(kind="x", tag="t"),
             puts=puts, hall=[dict(x=x, y=y) for x, y in hall], hall_rects=[], runs=[], statues=[],
             tiles=0, hall_new=len(hall))
    p.update(more)
    return lua_value(p)


def compose(units, info, plc, **opts):
    opts.setdefault("layouts", M)
    for k, v in list(opts.items()):
        if isinstance(v, (dict, list)):
            opts[k] = lua_value(v)
    return F.compose(units, info, plc, LUA.table_from(opts))


def check_composed(L2):
    """What every composed layout must satisfy. Returns its Python form."""
    d = layout_py(L2)
    cover, n = dig_cover(d["dig"])
    assert cover == d["tiles"], "L2.tiles is not exactly the dig cells' tiles"
    assert n == len(cover), "a tile is in two dig cells"
    assert (0, 0) not in cover, "the stair tile is in a dig cell"
    from_dig = {tuple(t) for t in py(PAIRS(M.tiles_from_dig(L2.dig)))}
    assert from_dig == d["tiles"], "ai-layouts.tiles_from_dig reads the dig cells differently"
    for ph in ("dig", "build", "place", "zone", "smooth", "engrave"):
        M.to_data(L2[ph], 0)                      # raises when two cells share a tile
    b = d["bounds"]
    assert b["x1"] == min(x for x, _ in cover) and b["y2"] == max(y for _, y in cover)
    assert L2.orient == 0
    return d


# ---- 1. transforms ---------------------------------------------------------

LINEAR = [(a, b, c, d) for a, b, c, d in itertools.product((-1, 0, 1), repeat=4)
          if abs(a) + abs(b) == 1 and abs(c) + abs(d) == 1 and abs(a) + abs(c) == 1]


def T(a, b, c, d, tx=0, ty=0):
    return F.xf(a, b, c, d, tx, ty)


def tup(t):
    return (t.a, t.b, t.c, t.d, t.tx, t.ty)


def apply(t, x, y):
    a, b, c, d, tx, ty = t
    return a * x + b * y + tx, c * x + d * y + ty


@test("transforms: the 8 turns and mirrors, xf_point, xf_rect on a 3x2 rectangle under each")
def _():
    assert len(LINEAR) == 8
    for a, b, c, d in LINEAR:
        t = T(a, b, c, d, 7, -3)
        assert tup(t) == (a, b, c, d, 7, -3)
        assert tuple(F.xf_point(t, 2, 5)) == (a * 2 + b * 5 + 7, c * 2 + d * 5 - 3)
        # the rectangle (4..6, 1..2): its image is the image of its tiles
        want = {apply((a, b, c, d, 7, -3), x, y) for x in (4, 5, 6) for y in (1, 2)}
        x2, y2, w2, h2 = F.xf_rect(t, 4, 1, 3, 2)
        got = {(x2 + i, y2 + j) for i in range(w2) for j in range(h2)}
        assert got == want, (a, b, c, d, got, want)
        assert (w2, h2) == ((2, 3) if a == 0 else (3, 2))
    assert tup(F.xf(1, 0, 0, 1)) == (1, 0, 0, 1, 0, 0), "tx, ty default to 0"


@test("transforms: xf_compose is T2 after T1, and associative")
def _():
    samples = [T(a, b, c, d, tx, ty) for (a, b, c, d), (tx, ty)
               in zip(LINEAR, [(0, 0), (3, -2), (-5, 1), (7, 7), (0, -9), (2, 0), (-1, -1), (4, 6)])]
    pts = [(0, 0), (1, 0), (0, 1), (-3, 5), (8, -2)]
    for t1, t2 in itertools.product(samples, repeat=2):
        c = F.xf_compose(t2, t1)
        for x, y in pts:
            assert tuple(F.xf_point(c, x, y)) == tuple(F.xf_point(t2, *F.xf_point(t1, x, y)))
        assert (c.a, c.b, c.c, c.d) in LINEAR
    for t1, t2, t3 in itertools.product(samples[::2], samples[1::2], samples[2:5]):
        assert tup(F.xf_compose(t3, F.xf_compose(t2, t1))) == tup(F.xf_compose(F.xf_compose(t3, t2), t1))


@test("transforms: xf_cell on a dig run, a zone with braces, a single tile; turn_word")
def _():
    def cell(t, x, y, text):
        c = F.xf_cell(t, lua_value(dict(x=x, y=y, text=text)))
        return c.x, c.y, c.text
    ident, quarter = T(1, 0, 0, 1, 10, 20), T(0, -1, 1, 0)       # quarter: east -> south (clockwise)
    mirror, transpose = T(-1, 0, 0, 1), T(0, 1, 1, 0)
    assert cell(ident, 2, 3, "d(3x1)") == (12, 23, "d(3x1)")
    assert cell(quarter, 2, 3, "d(3x1)") == (-3, 2, "d(1x3)")
    assert cell(mirror, 2, 3, "d(3x1)") == (-4, 3, "d(3x1)")
    assert cell(transpose, 2, 3, "d(3x1)") == (3, 2, "d(1x3)")
    assert cell(quarter, 2, -5, "m{location=temple}(15x11)") == (-5, 2, "m{location=temple}(11x15)")
    assert cell(quarter, 2, -2, "a{shoot_from=west}(2x5)") == (-2, 2, "a{shoot_from=north}(5x2)")
    assert cell(mirror, 2, -2, "a{shoot_from=west}(2x5)") == (-3, -2, "a{shoot_from=east}(2x5)")
    assert cell(quarter, 4, 1, "T{citizens=true}") == (-1, 4, "T{citizens=true}")
    assert cell(quarter, 4, 1, "wm") == (-1, 4, "wm")
    assert cell(mirror, 4, 1, "d") == (-4, 1, "d")
    # a name is never read as a compass word
    assert cell(quarter, 2, -4, 'm{name="Hall of the west wind"}(9x9)')[2] == 'm{name="Hall of the west wind"}(9x9)'
    # the input cell is not changed
    c = lua_value(dict(x=2, y=3, text="d(3x1)"))
    F.xf_cell(quarter, c)
    assert (c.x, c.y, c.text) == (2, 3, "d(3x1)")
    for a, b, c_, d in LINEAR:
        t = T(a, b, c_, d, 5, 5)
        for word, (vx, vy) in DIRS.items():
            assert F.turn_word(t, word) == WORD[(a * vx + b * vy, c_ * vx + d * vy)], (a, b, c_, d, word)
        assert F.turn_word(t, "up") == "up"
    assert F.turn_word(quarter, "east") == "south" and F.turn_word(transpose, "west") == "north"


# ---- unit_params -----------------------------------------------------------

@test("unit_params: a deep copy, orient 0 and corridor arms; a workshops level without spare rooms")
def _():
    p = lua_value(dict(kind="workshops", shops=["Masons", "Still"], spare=2, spare_for=["Kitchen"],
                       style=dict(orient=3, arms="ring", hall="rounded", customs=["ore_piles"])))
    q = F.unit_params(p)
    assert not SAME(q, p) and not SAME(q.style, p.style) and not SAME(q.shops, p.shops)
    assert not SAME(q.style.customs, p.style.customs)
    assert (q.style.orient, q.style.arms, q.style.hall) == (0, "corridor", "rounded")
    assert list(q.shops.values()) == ["Masons", "Still"] and list(q.style.customs.values()) == ["ore_piles"]
    assert q.spare == 0 and q.spare_for is None
    # the caller's are as they were
    assert (p.style.orient, p.style.arms, p.spare) == (3, "ring", 2) and list(p.spare_for.values()) == ["Kitchen"]
    q.shops[1] = "Loom"
    assert p.shops[1] == "Masons"
    # no kind given: a level that names shops is a workshops level
    assert F.unit_params(lua_value(dict(shops=["Still"], spare=3))).spare == 0
    # other kinds keep their own numbers; no style gets one
    q = F.unit_params(lua_value(dict(kind="bedrooms", rooms=8, spare=1)))
    assert q.spare == 1 and q.rooms == 8 and (q.style.orient, q.style.arms) == (0, "corridor")
    q = F.unit_params(None)
    assert (q.style.orient, q.style.arms) == (0, "corridor")


# ---- 2. cut, every kind and style ------------------------------------------

KIND_PARAMS = {
    "bedrooms": [dict(rooms=8, room_size=3), dict(rooms=1, room_size=2), dict(rooms=13, room_size=4),
                 dict(rooms=8, dormitory=True)],
    "suites": [dict(suites=2), dict(suites=5)],
    "jail": [dict(cells=4), dict(cells=7)],
    "dining": [dict(tables=12), dict(tables=4), dict(tables=60)],
    "storage": [dict(piles=["food", "stone", "wood", "furniture"], room_size=5), dict(piles=["stone"], room_size=7),
                dict(piles=["food", "stone", "wood", "gems", "cloth"], room_size=4 + 7)],
    "workshops": [dict(shops=["Still", "Kitchen", "Masons", "Carpenters"]), dict(shops=["Masons"]),
                  dict(shops=["Still", "Kitchen", "Masons", "Carpenters", "Loom", "Smelter"], spare=3,
                       spare_for=["Kiln"])],
    "temple": [dict(size="shrine"), dict(size="grand"), dict(size="grand", profession="MASON")],
    "memorial": [dict(name="the Fallen")],
    "hospital": [dict(beds=8), dict(beds=20)],
    "barracks": [dict(beds=8), dict(beds=5)],
    "tombs": [dict(coffins=8), dict(coffins=30)],
    "tavern": [dict(tables=8), dict(tables=20)],
    "library": [dict(bookcases=8)],
    "archery": [dict(lanes=2, length=12), dict(lanes=1, length=8), dict(lanes=3, length=16)],
    "garden": [dict(name="Quiet")],
}
STYLES = [
    dict(),
    dict(hall="rounded"),
    dict(hall="pillared", statues=4, rhythm=3),
    dict(hall="octagonal", motif="ring", scale=150, grand=True),
    dict(hall="nave", customs=["cloister", "armoury", "ore_piles"]),
    dict(hall="round", motif="star", scale=80, aspect="long", spacing=100, statues=2),
    dict(hall="cruciform", motif="cross", aspect="wide", smooth=3),
    dict(arms="cross", hall="rounded"),
    dict(arms="ring", grand=True, orient=3),
]


def all_levels():
    for kind in KIND_PARAMS:
        for params in KIND_PARAMS[kind]:
            for style in STYLES:
                p = dict(params)
                if style:
                    p["style"] = dict(style)
                yield kind, p


def in_hub(x, y):
    return abs(x) <= 1 and abs(y) <= 1


def expected_units(d):
    """An independent reading of the cut rules: for each unit, in order, a
    function level tile -> bay tile, its tiles and its (w, d)."""
    tiles = d["tiles"]
    out = []
    if "corridor" in d:
        top = d["corridor"]["top"]
        bottom = top + d["corridor"]["width"] - 1
        for side in "NS":
            room = (lambda y: y <= top - 2) if side == "N" else (lambda y: y >= bottom + 2)
            mine = (lambda y: y <= top - 1) if side == "N" else (lambda y: y >= bottom + 1)
            cols = sorted({x for x, y in tiles if room(y) and not in_hub(x, y)})
            groups = []
            for x in cols:
                if groups and groups[-1][-1] == x - 1:
                    groups[-1].append(x)
                else:
                    groups.append([x])
            for g in groups:
                xa, xb = g[0], g[-1]
                f = (lambda x, y, xa=xa: (x - xa, (top - 1) - y)) if side == "N" else \
                    (lambda x, y, xa=xa: (x - xa, y - (bottom + 1)))
                has = lambda x, y, xa=xa, xb=xb, mine=mine: xa <= x <= xb and mine(y) and not in_hub(x, y)  # noqa: E731
                ts = {f(x, y) for x, y in tiles if has(x, y)}
                out.append(dict(f=f, has=has, tiles=ts, w=xb - xa + 1, d=max(y for _, y in ts), flip=side == "N",
                                key=(xa if xa > 0 else -xb, 0 if xa > 0 else 1, 0 if side == "N" else 1)))
        out.sort(key=lambda u: u["key"])
        dropped = {(x, y) for x, y in tiles if in_hub(x, y) or top <= y <= bottom}
    else:
        ys = [y for x, y in tiles if x >= 2]
        ymin, ymax = min(ys), max(ys)
        xmax = max(x for x, _ in tiles)
        f = lambda x, y: (y - ymin, x - 1)                                                      # noqa: E731
        out.append(dict(f=f, has=lambda x, y: x >= 2, tiles={f(x, y) for x, y in tiles if x >= 2},
                        w=ymax - ymin + 1, d=xmax - 1, transpose=True, c=-ymin))
        dropped = {(x, y) for x, y in tiles if in_hub(x, y)}
    return out, dropped


def bay_cell(e, x, y, text):
    """A level cell in a unit's bay frame (rectangles by their corners)."""
    m = RECT.match(text)
    w, h = (int(m.group(2)), int(m.group(3))) if m else (1, 1)
    corners = [e["f"](x, y), e["f"](x + w - 1, y + h - 1)]
    bx, by = min(c[0] for c in corners), min(c[1] for c in corners)
    if not m:
        return bx, by, text
    if e.get("transpose"):
        w, h = h, w
    return bx, by, f"{m.group(1)}({w}x{h})"


@test("cut: every kind and style: each tile and cell in exactly one unit, inside its bay, opening on row 0")
def _():
    n_levels = 0
    for kind, params in all_levels():
        L, units, info = cut(kind, params)
        n_levels += 1
        d, us = layout_py(L), units_py(units)
        where = f"{kind} {params}"
        exp, dropped = expected_units(d)
        assert len(us) == len(exp), where
        assert info.mode == ("room" if "corridor" in d else "hall") and info.kind == L.kind, where
        assert SAME(info.summary, L.summary) and SAME(info.style, L.style) and info.engrave_all == L.engrave_all, where
        assert SAME(info.furniture, L.furniture), where
        # every non-hub, non-corridor tile is in exactly one unit
        assert sum(len(e["tiles"]) for e in exp) + len(dropped) == len(d["tiles"]), where
        counted = {ph: 0 for ph in ("build", "place", "zone", "rooms_at")}
        for u, e in zip(us, exp):
            assert u["mode"] == info.mode, where
            room = {t for t in u["tiles"] if t[1] >= 1}
            wall_row = {t for t in u["tiles"] if t[1] == 0}
            x0, x1 = u["open"]
            assert wall_row == {(x, 0) for x in range(x0, x1 + 1)}, (where, wall_row, u["open"])
            if info.mode == "room":
                assert u["tiles"] == e["tiles"], where
            else:
                assert room == e["tiles"], where
                c = e["c"]
                wide = kind in ("dining", "tavern", "temple", "garden", "library")
                assert (x0, x1) == ((c - 1, c + 1) if wide else (c, c)), (where, u["open"], c)
                assert e["f"](2, 0) == (c, 1), where
            assert (u["w"], u["d"]) == (e["w"], e["d"]), (where, u["w"], u["d"], e["w"], e["d"])
            # inside the bay; under the opening, floor
            assert all(0 <= x <= u["w"] - 1 and 0 <= y <= u["d"] for x, y in u["tiles"]), where
            assert all((x, 1) in u["tiles"] for x in range(x0, x1 + 1)), where
            # the dig cells: row runs, exactly the tiles, no tile twice
            cover, n = dig_cover(u["dig"])
            assert cover == u["tiles"] and n == len(cover), where
            assert all(re.match(r"^d(\(\d+x1\))?$", t) for _, _, t in u["dig"]), where
            # the cells: the level's own, in the bay frame
            for ph in counted:
                want = sorted(bay_cell(e, x, y, t) for x, y, t in d[ph] if e["has"](x, y))
                if kind == "archery" and ph == "zone":
                    want = [(x, y, t.replace("shoot_from=west", "shoot_from=north")) for x, y, t in want]
                assert sorted(u[ph]) == want, (where, ph, sorted(u[ph]), want)
                counted[ph] += len(u[ph])
                for x, y, t in u[ph]:
                    ct = cell_tiles(t, x, y)
                    assert all(0 <= cx <= u["w"] - 1 and 0 <= cy <= u["d"] for cx, cy in ct), (where, ph, x, y, t)
            for x, y, t in u["build"]:
                assert (x, y) in u["tiles"], (where, "a build cell on rock", x, y, t)
            assert u["tag"] == (u["rooms_at"][0][2] if u["rooms_at"] else False), where
        for ph, n in counted.items():
            assert n == len(d[ph]), (where, ph, "a cell is in no unit or in two")
        # the halls kept, turned: each rectangle covers the same tiles
        if info.mode == "hall":
            e = exp[0]
            want = [sorted(e["f"](x, y) for x in range(h["x"], h["x"] + h["w"]) for y in range(h["y"], h["y"] + h["h"]))
                    for h in d["halls"] if h["x"] >= 2]
            got = [sorted((x, y) for x in range(h["x"], h["x"] + h["w"]) for y in range(h["y"], h["y"] + h["h"]))
                   for h in us[0]["halls"]]
            assert got == want and len(got) >= 1, where
        else:
            assert all(u["halls"] == [] for u in us), where
    assert n_levels == sum(len(v) for v in KIND_PARAMS.values()) * len(STYLES)
    # (0.105.115) were_cells is never on a floor (masterplan_floors.CLASSIC_KINDS): cut refuses it
    assert set(KIND_PARAMS) | {"were_cells"} == set(M.KINDS.values()), "a kind of ai-layouts.KINDS is not tested"
    for p in (dict(cells=2), dict(cells=5)):
        res = F.cut(make("were_cells", p))
        us, why = res if isinstance(res, tuple) else (res, None)
        assert us is None and "not cuttable" in str(why), (p, res)


@test("cut: workshops' units are in shops order with their tags; 8 bedrooms give 8 units of room_size")
def _():
    shops = ["Still", "Kitchen", "Masons", "Carpenters", "Loom", "Smelter"]
    for style in (dict(), dict(hall="rounded", customs=["ore_piles"]), dict(arms="ring", grand=True)):
        L, units, info = cut("workshops", dict(shops=shops, spare=4, spare_for=["Kiln"], style=style))
        us = units_py(units)
        ore = "ore_piles" in style.get("customs", [])
        assert [u["tag"] for u in us] == ["shop:" + s for s in shops] + (["pile"] if ore else []), style
        for u, s in zip(us, shops):
            assert (u["w"], u["d"], u["open"]) == (5, 5, [1, 3])
            assert u["build"] == [(2, 3, M.WORKSHOPS[s])], u["build"]        # centred in its 5x5 room
            assert u["rooms_at"] == [(2, 3, "shop:" + s)]
        if ore:
            assert us[-1]["place"] == [(0, 1, "s(5x5)")] and us[-1]["build"] == []
        assert L.summary.free_rooms is None, "unit_params leaves no spare room"
    for size in (2, 3, 4):
        L, units, info = cut("bedrooms", dict(rooms=8, room_size=size))
        us = units_py(units)
        assert len(us) == 8 and all((u["w"], u["d"]) == (size, size) for u in us), size
        for u in us:
            door = u["open"][0]                 # an east room's door is left of the middle, a west room's right
            assert door in ((size - 1) // 2, size - 1 - (size - 1) // 2)
            assert u["open"] == [door, door] and (door, 0, "d") in u["build"]
            assert u["zone"] == [(0, 1, f"b({size}x{size})")]
            assert u["tag"] is False
        if size == 3:       # the bed in the far corner, the cabinet in the other, the chest before it
            assert all(sorted(u["build"]) == [(0, 2, "h"), (0, 3, "f"), (1, 0, "d"), (2, 3, "b")] for u in us)
    # storage: one unit a pile, in piles order, opening 3 wide; rounded rooms keep their corners
    L, units, info = cut("storage", dict(piles=["food", "stone", "wood"], room_size=7, style=dict(hall="rounded")))
    us = units_py(units)
    assert [u["place"] for u in us] == [[(0, 1, f"{k}(7x7)")] for k in "fsw"]
    assert all(u["open"] == [2, 4] and len(u["tiles"]) == 49 - 4 + 3 for u in us)
    assert all((0, 1) not in u["tiles"] and (6, 7) not in u["tiles"] for u in us)
    # suites: bedroom, office, bedroom, office
    L, units, info = cut("suites", dict(suites=2))
    assert [u["zone"][0][2] for u in units_py(units)] == ["b(4x4)", "o(4x4)", "b(4x4)", "o(4x4)"]


@test("cut: the fort's entry_door keeps a hall's opening 1 wide and puts a door on it")
def _():
    for kind, params in (("dining", dict(tables=12)), ("hospital", dict(beds=8)), ("temple", dict(size="grand"))):
        p = dict(params, style=dict(entry_door=True))
        # ai-layouts' style does not carry entry_door: given cut's own way (the params)
        L, units, info = cut(kind, p, with_params=True)
        u = units_py(units)[0]
        c = u["open"][0]
        assert u["open"] == [c, c] and (c, 0, "d") in u["build"], (kind, u["open"])
        assert sum(1 for x, y, t in u["build"] if (x, y) == (c, 0)) == 1
        assert info.style.entry_door is True and SAME(info.style, L.style)
        assert (info.furniture.Door or 0) == (L.furniture.Door or 0) + 1, "the door is counted, on a copy"
        # ... or set on the level's style by the caller
        L = make(kind, params)
        L.style.entry_door = True
        u2 = units_py(F.cut(L)[0])[0]
        assert u2["open"] == u["open"] and sorted(u2["build"]) == sorted(u["build"])
        # without it: no door, and the wide kinds open 3 wide
        L, units, info = cut(kind, params)
        u = units_py(units)[0]
        assert (c, 0, "d") not in u["build"] and info.style.entry_door is None
        assert u["open"] == ([c - 1, c + 1] if kind != "hospital" else [c, c])
    # a room level's rooms keep their own doors: nothing added
    L, units, info = cut("bedrooms", dict(rooms=4, room_size=3, style=dict(entry_door=True)), with_params=True)
    assert all(sum(1 for b in u["build"] if b[2] == "d") == 1 for u in units_py(units))
    assert info.furniture.Door == 4


# ---- 3. what cannot be cut -------------------------------------------------

@test("cut: a layout that is not cuttable answers nil, why")
def _():
    def refused(L, *words):
        res = F.cut(L)
        assert isinstance(res, tuple) and res[0] is None and isinstance(res[1], str), res
        assert any(w in res[1] for w in words), res[1]
    hand = LUA.eval("""function()
        local L = {kind = 'dining', tiles = {}, dig = {}, build = {}, place = {}, zone = {}, rooms_at = {}, halls = {},
                   style = {smooth = 0}, furniture = {}, summary = {}, orient = 0}
        for x = -3, 6 do for y = -1, 1 do
            if x ~= 0 or y ~= 0 then L.tiles[x] = L.tiles[x] or {}; L.tiles[x][y] = true end
        end end
        return L
    end""")
    refused(hand(), "not cuttable")
    L = hand()
    L.tiles[-3], L.tiles[-2], L.tiles[2][0] = None, None, None             # no way in at (2, 0)
    refused(L, "not cuttable")
    # levels made without unit_params: turned, cross arms, a ring, crypts
    for kind, params in (("dining", dict(tables=8, style=dict(orient=2))),
                         ("bedrooms", dict(rooms=8, room_size=3, style=dict(arms="cross"))),
                         ("storage", dict(piles=["food"] * 5, room_size=5, style=dict(arms="ring"))),
                         ("tombs", dict(coffins=9, style=dict(arms="cross")))):
        res = M.make(kind, lua_value(params))
        refused(res[0] if isinstance(res, tuple) else res, "not cuttable")
    refused(M.make("farms", lua_value(dict(plots=4))), "not cuttable")
    refused(LUA.table_from({}), "not cuttable")
    # a room level with something standing in its corridor
    L = make("bedrooms", dict(rooms=4, room_size=3))
    LUA.eval("function(L) table.insert(L.build, {x = 5, y = 0, text = 's'}) end")(L)
    refused(L, "in no room")
    # a hall level with a cell at the hub
    L = make("dining", dict(tables=8))
    LUA.eval("function(L) table.insert(L.build, {x = 1, y = 0, text = 'd'}) end")(L)
    refused(L, "at the hub")


# ---- 4. the worked example -------------------------------------------------

PICTURE = """\
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
#######f.b#f.b################""".splitlines()
PX, PY = -3, -7                    # the picture's top-left tile
EAST = (0, 0, 1, 0)


def draw_floor(layouts, wall_rows=(-2, 2)):
    tiles, glyph = set(), {}
    for d in layouts:
        tiles |= d["tiles"]
        for x, y in d["tiles"]:
            if y in wall_rows:
                glyph.setdefault((x, y), "+")
        for x, y, t in d["place"]:
            for p in cell_tiles(t, x, y):
                glyph[p] = t[0]
        for x, y, t in d["build"]:
            if t == "d":
                glyph[(x, y)] = "D"
            elif t.startswith("w") and len(t) == 2:
                for i in (-1, 0, 1):
                    for j in (-1, 0, 1):
                        glyph[(x + i, y + j)] = "W"
            else:
                glyph[(x, y)] = t[0]
    rows = []
    for j in range(len(PICTURE)):
        row = ""
        for i in range(len(PICTURE[0])):
            p = (PX + i, PY + j)
            row += "S" if p == (0, 0) else glyph.get(p, ".") if p in tiles else "#"
        rows.append(row)
    outside = [p for p in tiles if not (PX <= p[0] < PX + len(PICTURE[0]) and PY <= p[1] < PY + len(PICTURE))]
    return rows, outside


def worked_example(hall_pri=None):
    # 1. bedrooms {rooms = 4, room_size = 3}: north and south at u = 4 and u = 8; the hall to column 11
    L, beds, info1 = cut("bedrooms", dict(rooms=4, room_size=3))
    puts = [dict(unit=i + 1, run=1, side=side, u=u, w=3, d=3, axial=False, role="room", T=slot_T(EAST, side, u, 3))
            for i, (u, side) in enumerate([(4, -1), (4, 1), (8, -1), (8, 1)])]
    p1 = placement(puts, hall_tiles(EAST, 2, 11, hub=True), floor_id=3)
    L1 = compose(beds, info1, p1)
    # 2. workshops {shops = {'Masons'}} with its stone pile: the pile at u = 13, the shop at u = 19, north
    _, pile, _ = cut("storage", dict(piles=["stone"], room_size=5))
    _, shop, info2 = cut("workshops", dict(shops=["Masons"]))
    puts = [dict(unit=1, run=1, side=-1, u=13, w=5, d=5, axial=False, role="pile", flag="stone",
                 T=slot_T(EAST, -1, 13, 5)),
            dict(unit=2, run=1, side=-1, u=19, w=5, d=5, axial=False, role="shop", T=slot_T(EAST, -1, 19, 5))]
    p2 = placement(puts, hall_tiles(EAST, 12, 24), floor_id=3, new_floor=False)
    opts = dict(extra_units=pile)
    if hall_pri:
        opts["hall_pri"] = hall_pri
    L2 = compose(shop, info2, p2, **opts)
    return L1, L2


@test("compose: the worked example, tile for tile (bedrooms both sides, then a mason's shop with its pile)")
def _():
    L1, L2 = worked_example()
    d1, d2 = check_composed(L1), check_composed(L2)
    rows, outside = draw_floor([d1, d2])
    if "--show" in sys.argv:
        print("\n".join(rows))
    assert not outside, f"tiles outside the picture: {sorted(outside)}"
    if rows != PICTURE:
        extra = ""
        if _render:
            try:
                extra = "\n" + _render(sorted(d1["tiles"] | d2["tiles"]))
            except Exception:  # noqa: BLE001
                pass
        raise AssertionError("the floor is not the picture:\n" + "\n".join(
            f"{r}   {'' if r == w else '<- wanted ' + w}" for r, w in zip(rows, PICTURE)) + extra)
    # nothing of the first project is touched by the second
    assert not (d1["tiles"] & d2["tiles"])
    # the first project: the hub's 8 tiles and 10 hall columns first, at priority 3; then 4 rooms and doors
    hall1 = d1["dig"][:38]
    assert all(t == "d3" for _, _, t in hall1) and len({(x, y) for x, y, _ in hall1}) == 38
    assert all(t != "d3" for _, _, t in d1["dig"][38:])
    assert len(d1["tiles"]) == 38 + 4 * (9 + 1)
    assert sorted(c for c in d1["build"] if c[2] == "d") == [(5, -2, "d"), (5, 2, "d"), (9, -2, "d"), (9, 2, "d")]
    assert sorted(d1["zone"]) == [(4, -5, "b(3x3)"), (4, 3, "b(3x3)"), (8, -5, "b(3x3)"), (8, 3, "b(3x3)")]
    # the second: only the 39 new hall tiles and the two rooms
    hall2 = d2["dig"][:39]
    assert all(t == "d3" for _, _, t in hall2) and {(x, y) for x, y, _ in hall2} == set(hall_tiles(EAST, 12, 24))
    assert len(d2["tiles"]) == 39 + 2 * (25 + 3)
    assert d2["place"] == [(13, -7, "s(5x5)")], d2["place"]             # the pile by its top-left
    assert d2["build"] == [(21, -5, "wm")], d2["build"]                 # the shop centred in its room
    assert d2["rooms_at"] == [(21, -5, "shop:Masons")]
    assert all(re.match(r"^d(\(\d+x1\))?$", t) for _, _, t in d2["dig"][39:])
    # furniture and summary are the level's, copied; the floor is named
    assert dict(L1.furniture) == dict(Bed=4, Door=4, Cabinet=4, Box=4)
    assert (L1.summary.rooms, L1.summary.floor, L2.summary.floor) == (4, 3, 3)
    assert list(L2.summary.workshops.values()) == ["Masons"] and dict(L2.furniture) == dict(Masons=1)
    assert L1.kind == "bedrooms" and L2.kind == "workshops"
    # an urgent level's hall is dug first
    _, L2u = worked_example(hall_pri=1)
    du = check_composed(L2u)
    assert all(t == "d1" for _, _, t in du["dig"][:39]) and du["tiles"] == d2["tiles"]


@test("compose: the units as a put names them (extra units first; a unit handed over itself), mirrored slots")
def _():
    _, pile, _ = cut("storage", dict(piles=["stone"], room_size=5))
    _, shop, info = cut("workshops", dict(shops=["Masons"]))
    Tp, Ts = slot_T(EAST, -1, 13, 5), slot_T(EAST, -1, 19, 5)
    hall = hall_tiles(EAST, 12, 24)
    a = check_composed(compose(shop, info, placement([dict(unit=1, T=Tp), dict(unit=2, T=Ts)], hall),
                               extra_units=pile))
    all_units = LUA.eval("function(a, b) return {a[1], b[1]} end")(pile, shop)
    b = check_composed(compose(all_units, info, placement([dict(unit=1, T=Tp), dict(unit=2, T=Ts)], hall)))
    plc = placement([dict(unit=1, T=Tp), dict(unit=1, T=Ts)], hall)
    plc.puts[1].unit, plc.puts[2].unit = pile[1], shop[1]
    c = check_composed(compose(LUA.table_from([]), info, plc))
    for other in (b, c):
        assert all(a[k] == other[k] for k in ("dig", "build", "place", "rooms_at", "tiles")), "not the same level"
    # a mirrored bedroom: the bed changes corner, the room stays in its slot
    _, beds, info = cut("bedrooms", dict(rooms=1, room_size=3))
    plain = check_composed(compose(beds, info, placement([dict(unit=1, T=slot_T(EAST, 1, 4, 3))], [])))
    mirrored = check_composed(compose(beds, info, placement([dict(unit=1, T=slot_T(EAST, 1, 4, 3, True))], [])))
    assert plain["tiles"] == mirrored["tiles"] and plain["zone"] == mirrored["zone"] == [(4, 3, "b(3x3)")]
    assert (6, 5, "b") in plain["build"] and (4, 5, "b") in mirrored["build"]
    assert (5, 2, "d") in plain["build"] and (5, 2, "d") in mirrored["build"]
    # a put that names no unit is a bug in the caller: said, not skipped
    try:
        compose(beds, info, placement([dict(unit=7, T=slot_T(EAST, 1, 4, 3))], []))
        raise AssertionError("a put without its unit was let through")
    except LuaError as e:
        assert "no unit 7" in str(e)


@test("compose: one dig cell a tile (a hall tile listed twice, a unit over the hall), never the stair")
def _():
    _, beds, info = cut("bedrooms", dict(rooms=2, room_size=3))
    hall = hall_tiles(EAST, 2, 8, hub=True)
    # the same room put twice on one slot: its furniture would stand twice on a tile: refused, said
    plc = placement([dict(unit=1, T=slot_T(EAST, -1, 4, 3)), dict(unit=1, T=slot_T(EAST, -1, 4, 3))], hall)
    try:
        compose(beds, info, plc)
        raise AssertionError("two build cells on one tile were let through")
    except LuaError as e:
        assert "two build cells" in str(e), e
    # dig only (a unit without cells): the overlap is given to the first cell, nothing twice
    bare = LUA.eval("""function(u) return {{w = u.w, d = u.d, mode = u.mode, open = u.open, dig = u.dig,
        build = {}, place = {}, zone = {}, rooms_at = {}, halls = {}, tiles = u.tiles}} end""")(beds[1])
    plc = placement([dict(unit=1, T=slot_T(EAST, -1, 4, 3)), dict(unit=1, T=dict(a=1, b=0, c=0, d=1, tx=4, ty=-3)),
                     dict(unit=1, T=dict(a=1, b=0, c=0, d=1, tx=-1, ty=-1))], hall + [(0, 0), (5, 0)])
    d = check_composed(compose(bare, info, plc))
    assert (0, 0) not in d["tiles"] and len(d["dig"][0][2]) == 2
    assert sum(1 for x, y, t in d["dig"] if t == "d3") == len(set(hall))


# ---- 5. halls on every direction and side ----------------------------------

HALL_LEVELS = [("dining", dict(tables=12)), ("temple", dict(size="grand", style=dict(grand=True))),
               ("hospital", dict(beds=8)), ("dining", dict(tables=20, style=dict(hall="octagonal", statues=2))),
               ("tavern", dict(tables=8, style=dict(hall="rounded")))]


def connected(tiles, start):
    seen, todo = set(), [start]
    while todo:
        p = todo.pop()
        if p in seen or p not in tiles:
            continue
        seen.add(p)
        x, y = p
        todo += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    return seen


@test("compose: a dining hall, a grand temple and a hospital on each hall direction and both sides")
def _():
    n = 0
    for kind, params in HALL_LEVELS:
        L, units, info = cut(kind, params)
        lv, u = layout_py(L), units_py(units)[0]
        ymin = min(y for x, y in lv["tiles"] if x >= 2)
        w, depth = u["w"], u["d"]
        for (name, (dx, dy)), side, mirror in itertools.product(DIRS.items(), (-1, 1), (False, True)):
            run = (0, 0, dx, dy)
            col = 5
            Tm = slot_T(run, side, col, w, mirror)
            hall = hall_tiles(run, 2, col + w, hub=True)
            L2 = compose(units, info, placement([dict(unit=1, T=Tm, side=side, u=col, w=w, d=depth)], hall))
            d = check_composed(L2)
            where = f"{kind} {params} {name} side {side} mirror {mirror}"
            n += 1

            def at(bx, by):
                return (Tm["a"] * bx + Tm["b"] * by + Tm["tx"], Tm["c"] * bx + Tm["d"] * by + Tm["ty"])
            # the bay frame lands where the contract says: (u + bx, side * (2 + by)) in run coordinates
            for bx, by in ((0, 0), (w - 1, 0), (2, 3)):
                assert at(bx, by) == run_tile(run, col + (w - 1 - bx if mirror else bx), side * (2 + by)), where
            # the opening is dug on the wall row and touches the hall
            x0, x1 = u["open"]
            hall_set = set(hall)
            for bx in range(x0, x1 + 1):
                o = at(bx, 0)
                assert o in d["tiles"], where
                inward = (o[0] + side * dy, o[1] - side * dx)          # one step back towards the hall
                assert inward in hall_set, (where, o, inward)
            wall = {at(bx, 0) for bx in range(w)}
            assert d["tiles"] & wall == {at(bx, 0) for bx in range(x0, x1 + 1)}, where
            # the level's own entry row (y = 0, its first hall tile (2, 0)) lines up with the opening's middle
            c = -ymin
            assert (x0 + x1) // 2 == c and at(c, 1) in d["tiles"], where
            assert at(c, 1) == at(*(0 - ymin, 2 - 1)), where
            # the zone rectangle covers the hall's floor
            zone = [z for z in d["zone"] if RECT.match(z[2])]
            assert len(zone) == 1, (where, d["zone"])
            zt = cell_tiles(zone[0][2], zone[0][0], zone[0][1])
            floor = d["tiles"] - hall_set - wall
            assert floor and floor <= zt, (where, sorted(floor - zt)[:5])
            assert zt == {at(bx, by) for bx in range(w) for by in range(1, depth + 1)}, where
            # everything stands on dug floor, and it is one piece from the stair's hub
            for x, y, t in d["build"]:
                assert (x, y) in d["tiles"] and (x, y) not in hall_set, (where, x, y, t)
            assert connected(d["tiles"], (1, 0) if (1, 0) in d["tiles"] else hall[0]) == d["tiles"], where
            assert len(d["build"]) == len(lv["build"]) and dict(L2.furniture) == dict(L.furniture), where
            # the hall rectangle, turned: the same tiles as the zone's for these kinds
            assert len(d["halls"]) == 1, where
            h = d["halls"][0]
            assert {(h["x"] + i, h["y"] + j) for i in range(h["w"]) for j in range(h["h"])} == zt, where
    assert n == len(HALL_LEVELS) * 16


# ---- 6. archery ------------------------------------------------------------

@test("archery: shoot_from after both transforms: from the hall's side, on 4 directions x 2 sides (and mirrored)")
def _():
    L, units, info = cut("archery", dict(lanes=2, length=12))
    u = units_py(units)[0]
    assert u["zone"] == [(0, 1, "a{shoot_from=north}(5x2)")], u["zone"]      # bay: from the wall row's side
    assert (u["w"], u["d"], u["open"]) == (5, 12, [2, 2])
    seen = set()
    for (name, (dx, dy)), side, mirror in itertools.product(DIRS.items(), (-1, 1), (False, True)):
        run = (3, -2, dx, dy)
        Tm = slot_T(run, side, 6, 5, mirror)
        d = check_composed(compose(units, info, placement([dict(unit=1, T=Tm)], hall_tiles(run, 2, 12))))
        x, y, text = d["zone"][0]
        word = re.search(r"shoot_from=(\w+)", text).group(1)
        # the room grows away from the hall along side * p, p = (-dy, dx): the shooters stand on the
        # hall's side of it and shoot away from the hall
        grow = (-dy * side, dx * side)
        assert word == WORD[(-grow[0], -grow[1])], (name, side, mirror, word)
        seen.add((name, side, word))
        zt = cell_tiles(text, x, y)
        rows = {run_tile(run, 6 + i, side * v) for i in range(5) for v in (3, 4)}      # the two rows by the wall row
        assert zt == rows, (name, side, mirror)
        targets = {(bx, by) for bx, by, t in d["build"] if t == "A"}
        assert targets == {run_tile(run, 6 + i, side * 14) for i in ((1, 3))}, (name, side, mirror, targets)
        assert len(d["tiles"]) == 33 + 5 * 12 + 1
    assert {(n, s): w for n, s, w in seen} == {
        ("east", -1): "south", ("east", 1): "north", ("west", -1): "north", ("west", 1): "south",
        ("south", -1): "west", ("south", 1): "east", ("north", -1): "east", ("north", 1): "west"}


# ---- 7. decoration ---------------------------------------------------------

@test("compose: smooth and engrave from the public decorate; the main hall engraved only when grand")
def _():
    for grand in (False, True):
        style = dict(smooth=3, grand=grand, hall="pillared")
        L, units, info = cut("dining", dict(tables=12, style=style))
        w = units[1].w
        hall = hall_tiles(EAST, 2, 4 + w, hub=True)
        rect = dict(x=2, y=-1, w=3 + w, h=3)
        plc = placement([dict(unit=1, T=slot_T(EAST, 1, 4, w))], hall, hall_rects=[rect])
        L2 = compose(units, info, plc)
        d = check_composed(L2)
        smooth = {(x, y) for x, y, _ in d["smooth"]}
        engrave = {(x, y) for x, y, _ in d["engrave"]}
        assert smooth and engrave and (0, 0) not in smooth and (0, 0) not in engrave
        assert d["tiles"] <= smooth, "smooth 3: every floor"
        assert all(t == "s" for _, _, t in d["smooth"]) and all(t == "e" for _, _, t in d["engrave"])
        # the level's own hall: floor and walls engraved (its rectangle, turned, and one tile round it)
        h = d["halls"][0]
        own = {(h["x"] + i, h["y"] + j) for i in range(-1, h["w"] + 1) for j in range(-1, h["h"] + 1)}
        assert (h["x"], h["y"], h["w"], h["h"]) == (4, 3, w, units[1].d)
        main = {(x, y) for x in range(2, 5 + w) for y in (-1, 0, 1)}
        main_round = {(x, y) for x in range(1, 6 + w) for y in range(-2, 3)}
        # (a pillared hall's corners are rock: the border's own four corners touch no floor)
        far = {(h["x"] - 1 + i * (h["w"] + 1), h["y"] - 1 + j * (h["h"] + 1)) for i in (0, 1) for j in (0, 1)}
        assert own - far <= engrave, sorted(own - far - engrave)[:6]
        if grand:
            assert len(d["halls"]) == 2 and d["halls"][1] == rect
            assert main <= engrave, "a grand level engraves its stretch of the main hall"
            assert engrave <= own | main_round and len(engrave & main_round) > len(main)
            assert L2.engrave_all is True
        else:
            assert len(d["halls"]) == 1
            assert engrave <= own and not (main & engrave)
        assert SAME(L2.style, info.style) and L2.style.smooth == 3
    # a plain level: nothing smoothed, nothing engraved; bounds are the tiles' box
    L, units, info = cut("bedrooms", dict(rooms=2, room_size=3))
    L2 = compose(units, info, placement([dict(unit=1, T=slot_T(EAST, -1, 4, 3)),
                                         dict(unit=2, T=slot_T(EAST, 1, 4, 3))], hall_tiles(EAST, 2, 7, hub=True)))
    d = check_composed(L2)
    assert d["smooth"] == [] and d["engrave"] == []
    assert d["bounds"] == dict(x1=-1, y1=-5, x2=7, y2=5)
    # a memorial is engraved whatever the style (engrave_all), its own hall only
    L, units, info = cut("memorial", dict(name="the Fallen"))
    w = units[1].w
    L2 = compose(units, info, placement([dict(unit=1, T=slot_T(EAST, -1, 4, w))], hall_tiles(EAST, 2, 4 + w, hub=True),
                                        hall_rects=[dict(x=2, y=-1, w=3 + w, h=3)]))
    d = check_composed(L2)
    engrave = {(x, y) for x, y, _ in d["engrave"]}
    assert L2.engrave_all is True and engrave and not any(-1 <= y <= 1 for _, y in engrave)


@test("compose: statues on a new node's corners (opts.statues at most); the neck's door tile is dug")
def _():
    L, units, info = cut("bedrooms", dict(rooms=2, room_size=3))
    hall = hall_tiles(EAST, 2, 8, hub=True)
    corners = [dict(x=12, y=-2), dict(x=12, y=2), dict(x=16, y=-2), dict(x=16, y=2)]
    puts = [dict(unit=1, T=slot_T(EAST, -1, 4, 3)), dict(unit=2, T=slot_T(EAST, 1, 4, 3))]
    node = [(x, y) for x in range(12, 17) for y in range(-2, 3)]
    for want, got in ((0, 0), (2, 2), (4, 4), (9, 4)):
        L2 = compose(units, info, placement(puts, hall + node, statues=corners), statues=want)
        d = check_composed(L2)
        st = [(x, y) for x, y, t in d["build"] if t == "s"]
        assert st == [(c["x"], c["y"]) for c in corners[:got]], (want, st)
        assert (L2.furniture.Statue or 0) == got and L2.furniture.Bed == 2
        assert (L.furniture.Statue or 0) == 0, "the level's own furniture is not changed"
    # no statues listed: none, whatever the style asks
    d = check_composed(compose(units, info, placement(puts, hall), statues=3))
    assert not [c for c in d["build"] if c[2] == "s"]
    # a neck: the hall's first column only at v = 0; the door tile is dug, the door is the caller's
    neck_hall = [t for t in hall_tiles(EAST, 3, 8, hub=True)]
    for listed in (True, False):
        plc = placement(puts, neck_hall + ([(2, 0)] if listed else []), neck=dict(x=2, y=0))
        d = check_composed(compose(units, info, plc, door_neck=True))
        assert (2, 0) in d["tiles"] and (2, -1) not in d["tiles"] and (2, 1) not in d["tiles"]
        assert (2, 0, "d3") in d["dig"][:len(neck_hall) + 1]
        assert (2, 0, "d") not in d["build"]
    d = check_composed(compose(units, info, placement(puts, neck_hall, neck=dict(x=2, y=0))))
    assert (2, 0) not in d["tiles"], "without opts.door_neck the placement's hall is the whole of it"


# ---- 8, 9. the neighbours, the module --------------------------------------

@test("ai-layouts: decorate and set_bounds are public, and nothing else changed for its own tests")
def _():
    assert callable(M.decorate) and callable(M.set_bounds)
    assert "\nfunction decorate(L)\n" in LAYOUTS_SRC and "\nfunction set_bounds(L)\n" in LAYOUTS_SRC
    assert "local function decorate" not in LAYOUTS_SRC and "local function set_bounds" not in LAYOUTS_SRC
    # decorate and set_bounds called from outside give what finish() gave the level
    L = make("dining", dict(tables=12, style=dict(smooth=3, hall="pillared", statues=2)))
    before = layout_py(L)
    M.decorate(L)
    M.set_bounds(L)
    after = layout_py(L)
    assert sorted(before["smooth"]) == sorted(after["smooth"]) and sorted(before["engrave"]) == sorted(after["engrave"])
    assert before["bounds"] == after["bounds"]
    # the layouts' own tests (run_all runs them too; here only when asked: they take minutes)
    if "--neighbours" in sys.argv:
        for name in ("test_layouts.py", "test_d0_layouts.py", "test_k54_layout_a.py"):
            r = subprocess.run([sys.executable, str(ROOT / "tests" / name)], capture_output=True, text=True,
                               timeout=900)
            tail = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:]
            assert r.returncode == 0 and " 0 failed" in tail, f"{name}: {tail}"


@test("the module: Lua 5.3, no game access, no reqscript while loading, no global leaked, listed in the bridge")
def _():
    assert LUA.eval("_VERSION") == "Lua 5.3"
    assert "--@ module = true" in SRC
    code = "\n".join(line.split("--")[0] for line in SRC.splitlines())
    assert not re.search(r"\bdfhack\b|\bdf\.", code), "game access in a pure module"
    assert CALLS_AT_LOAD == 0, "reqscript was called while the module loaded"
    assert len(re.findall(r"\breqscript\(", code)) == 1
    # compose finds ai-layouts itself (reqscript) when no one hands it over, or takes the module's LAYOUTS
    L, units, info = cut("bedrooms", dict(rooms=1, room_size=3))
    plc = placement([dict(unit=1, T=slot_T(EAST, -1, 4, 3))], hall_tiles(EAST, 2, 7, hub=True))
    before = LUA.globals().REQ_CALLS
    a = layout_py(F.compose(units, info, plc, None))
    assert LUA.globals().REQ_CALLS == before + 1
    F.LAYOUTS = M
    b = layout_py(F.compose(units, info, plc))
    F.LAYOUTS = None
    assert LUA.globals().REQ_CALLS == before + 1 and a == b
    # every test above has run by now: nothing was written to the real globals
    leaked = set(LUA.globals().keys()) - GLOBALS_BEFORE
    assert not leaked, f"globals leaked: {sorted(map(str, leaked))}"
    for name in ("xf", "xf_point", "xf_rect", "xf_cell", "xf_compose", "turn_word", "unit_params", "cut", "compose"):
        assert callable(F[name]), name
    bridge = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    after = bridge.split("    'ai-raids',   -- (0.105.47, J17)", 1)[1].split("\n", 2)[1]
    assert after == "    'ai-floorunits',   -- (layout B) a level cut into room units for a floor", after


if __name__ == "__main__":
    finish()
