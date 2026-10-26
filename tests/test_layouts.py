"""Tests for lua/ai-layouts.lua, run in a real Lua engine (pip install lupa).

    python tests/test_layouts.py          run the tests
    python tests/test_layouts.py --show   also draw each layout
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = []

try:
    import lupa  # noqa: F401
    from lupa import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)


def load():
    lua = LuaRuntime(unpack_returned_tuples=True)
    src = (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8")
    env = lua.eval("function(src) local env = setmetatable({}, {__index=_G}); "
                   "assert(load(src, 'ai-layouts', 't', env))(); return env end")(src)
    return lua, env


LUA, M = load()
TO_PY = LUA.eval("""function(L)
  local out = {tiles={}, cells={}}
  for x, col in pairs(L.tiles) do for y in pairs(col) do table.insert(out.tiles, {x, y}) end end
  for _, phase in ipairs({'dig','build','place','zone','smooth','engrave'}) do
    for _, c in ipairs(L[phase]) do table.insert(out.cells, {phase, c.x, c.y, c.text}) end
  end
  return out
end""")


def layout(kind, **params):
    p = LUA.table_from(params)
    for k, v in params.items():
        if isinstance(v, list):
            p[k] = LUA.table_from(v)
        elif isinstance(v, dict):
            p[k] = LUA.table_from(v)
    res = M.make(kind, p)
    L, err = res if isinstance(res, tuple) else (res, None)
    assert L is not None, err
    raw = TO_PY(L)
    tiles = {(int(t[1]), int(t[2])) for t in raw.tiles.values()}
    cells = [(c[1], int(c[2]), int(c[3]), c[4]) for c in raw.cells.values()]
    return L, tiles, cells


def draw(tiles, cells) -> str:
    xs = [x for x, _ in tiles] + [0]
    ys = [y for _, y in tiles] + [0]
    marks = {(x, y): t[0] if t[0] != "d" or ph == "build" else "+" for ph, x, y, t in cells
             if ph in ("build", "place")}
    rows = []
    for y in range(min(ys) - 1, max(ys) + 2):
        row = ""
        for x in range(min(xs) - 1, max(xs) + 2):
            if (x, y) == (0, 0):
                row += "X"
            elif (x, y) in marks:
                row += marks[(x, y)]
            else:
                row += "." if (x, y) in tiles else "#"
        rows.append(row)
    return "\n".join(rows)


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


def common_checks(L, tiles, cells):
    assert (0, 0) not in tiles, "the stair tile must never be dug"
    for ph, x, y, text in cells:
        if ph == "build":
            assert (x, y) in tiles, f"{ph} {text} at {x},{y} is not on a dug tile"
        elif ph in ("place", "zone"):
            # a zone or stockpile rectangle may start on a rounded (rock) corner
            near = {(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)}
            assert near & tiles, f"{ph} {text} at {x},{y} is not on a dug area"
    # every dug tile is connected to the hub (no sealed rooms)
    seen, todo = set(), [(1, 0)]
    while todo:
        p = todo.pop()
        if p in seen or p not in tiles:
            continue
        seen.add(p)
        x, y = p
        todo += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    assert seen == tiles, f"{len(tiles - seen)} dug tiles can't be walked to from the stair"
    b = L.bounds
    assert b.x1 == min(x for x, _ in tiles) and b.y2 == max(y for _, y in tiles)
    for ph in ("dig", "build", "place", "zone", "smooth", "engrave"):
        M.to_data(L[ph], 0)    # raises if two cells share a tile
    for ph, x, y, text in cells:
        if ph in ("smooth", "engrave"):
            assert (x, y) != (0, 0), "never decorate the stair tile"


@test("bedrooms: 16 rooms of 3x3, each with door, bed, cabinet, chest and zone")
def _():
    L, tiles, cells = layout("bedrooms", rooms=16, room_size=3)
    common_checks(L, tiles, cells)
    assert L.summary.rooms == 16 and L.summary.beds == 16
    f = L.furniture
    assert (f.Bed, f.Door, f.Cabinet, f.Box) == (16, 16, 16, 16), dict(f)
    assert sum(1 for c in cells if c[0] == "zone" and c[3] == "b(3x3)") == 16


@test("bedrooms: room size follows the setting (2x2 rooms get only a bed)")
def _():
    L, tiles, cells = layout("bedrooms", rooms=8, room_size=2)
    common_checks(L, tiles, cells)
    assert L.furniture.Bed == 8 and L.furniture.Cabinet is None
    L, tiles, cells = layout("bedrooms", rooms=8, room_size=4)
    common_checks(L, tiles, cells)


@test("bedrooms: rooms never touch each other or the corridor except through the door")
def _():
    L, tiles, cells = layout("bedrooms", rooms=12, room_size=3)
    doors = {(x, y) for ph, x, y, t in cells if ph == "build" and t == "d"}
    corridor = {(x, 0) for x, y in tiles if y == 0}
    rooms = tiles - corridor - doors - {(x, y) for x in (-1, 0, 1) for y in (-1, 0, 1)}
    for x, y in rooms:
        for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            assert n not in corridor, f"room tile {x},{y} opens straight onto the corridor"


@test("sizes are clamped: 999 rooms -> 32, size 9 -> 4")
def _():
    L, tiles, cells = layout("bedrooms", rooms=999, room_size=9)
    assert L.summary.rooms == 32 and L.summary.room_size == 4


@test("dining: tables and chairs paired, dining zone over the hall")
def _():
    L, tiles, cells = layout("dining", tables=20)
    common_checks(L, tiles, cells)
    assert L.furniture.Table == 20 and L.furniture.Chair == 20
    assert any(c[0] == "zone" and c[3].startswith("h(") for c in cells)


@test("storage: one stockpile per requested type; unknown types dropped")
def _():
    L, tiles, cells = layout("storage", piles=["food", "stone", "refuse", "nonsense"], room_size=7)
    common_checks(L, tiles, cells)
    places = [c[3] for c in cells if c[0] == "place"]
    assert places == ["f(7x7)", "s(7x7)"], places


@test("workshops: each workshop centred in its own 5x5 room")
def _():
    L, tiles, cells = layout("workshops", shops=["Still", "Kitchen", "Masons", "Carpenters", "Craftsdwarfs"])
    common_checks(L, tiles, cells)
    for ph, x, y, t in cells:
        if ph == "build":
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    assert (x + dx, y + dy) in tiles, f"workshop {t} at {x},{y} doesn't fit"


@test("unknown kinds and empty lists are refused, not guessed")
def _():
    assert M.make("throne_room", LUA.table())[0] is None
    p = LUA.table()
    p["piles"] = LUA.table()
    assert M.make("storage", p)[0] is None


# --- culture: styles, temples, memorials ---------------------------------------------

def style(**kw):
    return {"style": kw}


@test("pillared dining hall: pillars left as rock, every table and chair still reachable")
def _():
    L, tiles, cells = layout("dining", tables=24, **style(hall="pillared", statues=3))
    common_checks(L, tiles, cells)
    assert (4, -2) not in tiles and (4, 1) not in tiles and (2, -5) not in tiles, "pillars/corners dug"
    assert L.summary.statues == 3 and L.furniture.Statue == 3


@test("rounded rooms in storage and workshops; bedrooms stay square (beds sit in corners)")
def _():
    L, tiles, cells = layout("storage", piles=["food", "stone"], room_size=7, **style(hall="rounded"))
    common_checks(L, tiles, cells)
    room = [c for c in cells if c[0] == "place"][0]
    assert (room[1], room[2]) not in tiles, "storage room corner should be rock"
    L, tiles, cells = layout("bedrooms", rooms=4, room_size=3, **style(hall="rounded"))
    common_checks(L, tiles, cells)
    assert all((x, y) in tiles for ph, x, y, t in cells if ph == "build" and t == "b")


@test("decoration follows the style: none, floors, floors+walls, engraved halls")
def _():
    counts = []
    for lvl in range(4):
        L, tiles, cells = layout("dining", tables=8, **style(smooth=lvl))
        common_checks(L, tiles, cells)
        sm = [(x, y) for ph, x, y, t in cells if ph == "smooth"]
        en = [(x, y) for ph, x, y, t in cells if ph == "engrave"]
        counts.append((len(sm), len(en)))
        if lvl == 1:
            assert set(sm) == tiles, "level 1 smooths exactly the floors"
        if lvl >= 2:
            assert tiles < set(sm), "level 2 smooths floors and walls"
    assert counts[0] == (0, 0) and counts[3][1] > 0 and counts[2][1] == 0, counts


@test("temple: shrine and grand, with a temple zone and statues")
def _():
    for size, statues in (("shrine", 1), ("grand", 2)):
        L, tiles, cells = layout("temple", size=size)
        common_checks(L, tiles, cells)
        assert any(c[0] == "zone" and "location=temple" in c[3] for c in cells)
        assert L.furniture.Statue >= statues


@test("temple asked for by a petition (0.89): a guildhall zone for a profession; every wall engraved")
def _():
    L, tiles, cells = layout("temple", size="grand", profession="MINER")
    common_checks(L, tiles, cells)
    assert any(c[0] == "zone" and "location=guildhall profession=miner" in c[3] for c in cells), cells
    assert any(c[0] == "engrave" for c in cells) and L.summary.guildhall == "miner"
    L, tiles, cells = layout("temple", size="grand", deity_hf=55)
    assert any(c[0] == "zone" and "location=temple" in c[3] for c in cells)
    assert any(c[0] == "engrave" for c in cells) and L.summary.deity_hf == 55
    L, tiles, cells = layout("temple", size="shrine")
    assert L.summary.guildhall is None


@test("memorial: named hall, central statue, always smoothed and engraved")
def _():
    L, tiles, cells = layout("memorial", name="Shulmik the Jackalowls")
    common_checks(L, tiles, cells)
    assert any(c[0] == "zone" and 'Hall of Shulmik the Jackalowls' in c[3] for c in cells)
    assert any(c[0] == "engrave" for c in cells) and any(c[0] == "smooth" for c in cells)
    assert (6, 0) in tiles and L.furniture.Statue == 1


@test("memorial names that could break the blueprint are refused")
def _():
    for bad in ('x"}(99x99)', "Robert'); drop", "A" * 50, ""):
        res = M.make("memorial", LUA.table_from({"name": bad}))
        L = res[0] if isinstance(res, tuple) else res
        assert L is None, bad



@test("hospital and barracks: beds along both walls, supplies or weapon racks at the end, right zone")
def _():
    L, tiles, cells = layout("hospital", beds=10, **style(hall="rounded"))
    common_checks(L, tiles, cells)
    assert L.furniture.Bed == 10 and L.furniture.Table == 1 and L.furniture.Box == 2
    assert any(c[0] == "zone" and "location=hospital" in c[3] for c in cells)
    L, tiles, cells = layout("barracks", beds=8)
    common_checks(L, tiles, cells)
    assert L.furniture.Bed == 8 and L.furniture.Armorstand == 8 and L.furniture.Weaponrack == 2
    assert any(c[0] == "zone" and c[3].startswith("B(") for c in cells)


@test("archery: targets at the far end, one a lane; the range zone at the near end shoots toward them, turned with the level")
def _():
    L, tiles, cells = layout("archery", lanes=2, length=12)
    common_checks(L, tiles, cells)
    targets = [(x, y) for ph, x, y, t in cells if ph == "build" and t == "A"]
    assert targets == [(13, -1), (13, 1)], targets
    zone = [t for ph, x, y, t in cells if ph == "zone"]
    assert zone == ["a{shoot_from=west}(2x5)"], zone
    assert M.turn_shoot(1, "a{shoot_from=west}") == "a{shoot_from=east}"
    assert M.turn_shoot(2, "a{shoot_from=west}") == "a{shoot_from=north}"
    assert M.turn_shoot(3, "a{shoot_from=east}") == "a{shoot_from=south}"
    L, tiles, cells = layout("archery", lanes=1, length=10, style={"orient": 2})
    zone = [t for ph, x, y, t in cells if ph == "zone"]
    assert zone == ["a{shoot_from=north}(3x2)"], zone            # turned: the range runs south


@test("garden: statues in rows, a table and chairs at the heart, a named meeting area, always engraved")
def _():
    L, tiles, cells = layout("garden", name="Amalmebzuth")
    common_checks(L, tiles, cells)
    assert L.furniture.Statue == 10 and L.furniture.Table == 1 and L.furniture.Chair == 2, dict(L.furniture)
    assert any(c[0] == "zone" and 'name="The Amalmebzuth Garden"' in c[3] for c in cells)
    assert L.engrave_all


@test("tombs: one coffin per 1x1 tomb zone, on the hall's walls")
def _():
    L, tiles, cells = layout("tombs", coffins=9, **style(hall="rounded"))
    common_checks(L, tiles, cells)
    coffins = {(x, y) for ph, x, y, t in cells if ph == "build" and t == "n"}
    zones = {(x, y) for ph, x, y, t in cells if ph == "zone" and t == "T{citizens=true}"}  # (0.104.17) automatic burial asked for
    assert L.furniture.Coffin == 9 and len(coffins) == 9 and zones == coffins, (coffins, zones)


@test("tavern and library: tables with chairs, bookcases, the right location zone")
def _():
    L, tiles, cells = layout("tavern", tables=8)
    common_checks(L, tiles, cells)
    assert L.furniture.Table == 8 and L.furniture.Chair == 8 and L.furniture.Box == 2
    assert any(c[0] == "zone" and "location=tavern" in c[3] for c in cells)
    # (0.104.76) every chair beside another chair (not on a diagonal) and beside a table
    chairs = {(c[1], c[2]) for c in cells if c[0] == "build" and c[3] == "c"}
    tabls = {(c[1], c[2]) for c in cells if c[0] == "build" and c[3] == "t"}
    near = lambda p, ps: any((p[0] + dx, p[1] + dy) in ps for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
    assert all(near(c, chairs) and near(c, tabls) for c in chairs), (chairs, tabls)
    L, tiles, cells = layout("library", bookcases=6, **style(hall="pillared"))
    common_checks(L, tiles, cells)
    assert L.furniture.Bookcase == 6 and L.furniture.Table == 2 and L.furniture.Chair == 2
    assert any(c[0] == "zone" and "location=library" in c[3] for c in cells)


@test("farms: plots 3 deep either side of a walkway; every plot tile is marked as needing soil")
def _():
    L, tiles, cells = layout("farms", plots=5, plot_w=5)
    common_checks(L, tiles, cells)
    plots = [c for c in cells if c[0] == "build"]
    assert len(plots) == 5 and all(c[3] == "p(5x3)" for c in plots), plots
    soil = {(int(x), int(y)) for x, col in L.soil.items() for y in col}
    covered = {(x + dx, y + dy) for _, x, y, _ in plots for dx in range(5) for dy in range(3)}
    assert soil == covered and soil <= tiles, (len(soil), len(covered))
    assert all(y != 0 for _, y in soil), "the walkway (y=0) stays free"
    assert L.summary.farm_plots == 5 and L.summary.farm_tiles == 75
    assert not [c for c in cells if c[0] in ("smooth", "engrave")], "soil can't be smoothed"
    L, tiles, cells = layout("farms", plots=99, plot_w=1)
    assert L.summary.farm_plots == 12 and all(c[3] == "p(3x3)" for c in cells if c[0] == "build")
    assert "farms" not in list(M.KINDS.values()), "farm levels come only through farm_plots"


@test("spacing: spread-out forts leave two tiles of rock between rooms; tight and middle leave one")
def _():
    def gaps(spacing):
        L, tiles, cells = layout("bedrooms", rooms=8, room_size=3, style={"spacing": spacing})
        common_checks(L, tiles, cells)
        doors = sorted(x for ph, x, y, t in cells if ph == "build" and t == "d" and y == -1 and x > 0)
        return [b - a for a, b in zip(doors, doors[1:])]
    assert gaps(0) == [4] and gaps(-100) == [4], (gaps(0), gaps(-100))     # 3-wide rooms + 1 wall
    assert gaps(50) == [5] and gaps(100) == [5], gaps(50)                  # 3-wide rooms + 2 walls


# --- 4b: orientation and pillar rhythm ---------------------------------------------

ALL_KINDS = (
    ("bedrooms", {"rooms": 12, "room_size": 3}),
    ("suites", {"suites": 3}), ("jail", {"cells": 3}),
    ("dining", {"tables": 24, "style": {"hall": "pillared", "statues": 3, "smooth": 3}}),
    ("storage", {"piles": ["food", "stone", "wood"], "room_size": 7, "style": {"hall": "rounded"}}),
    ("workshops", {"shops": ["Still", "Kitchen", "Masons"]}),
    ("temple", {"size": "grand", "style": {"statues": 2, "smooth": 3}}),
    ("memorial", {"name": "Shulmik the Jackalowls", "style": {"statues": 4}}),
    ("hospital", {"beds": 10, "style": {"hall": "rounded"}}),
    ("barracks", {"beds": 8}),
    ("archery", {"lanes": 2, "length": 12}),
    ("garden", {"name": "Amalmebzuth"}),
    ("tombs", {"coffins": 9}),
    ("tavern", {"tables": 8}),
    ("library", {"bookcases": 8, "style": {"hall": "pillared"}}),
    ("farms", {"plots": 5, "plot_w": 5}),
)


def oriented(kind, params, orient=None, rhythm=None):
    p = {k: (dict(v) if isinstance(v, dict) else v) for k, v in params.items()}
    st = dict(p.get("style", {}))
    if orient is not None:
        st["orient"] = orient
    if rhythm is not None:
        st["rhythm"] = rhythm
    if st:
        p["style"] = st
    return layout(kind, **p)


def turn_pt(o, x, y):
    if o >= 2:
        x, y = y, x
    if o in (1, 3):
        x = -x
    return x, y


def covered(x, y, text):
    import re
    m = re.match(r"^.*\((\d+)x(\d+)\)$", text)
    w, h = (int(m[1]), int(m[2])) if m else (1, 1)
    return {(x + dx, y + dy) for dx in range(w) for dy in range(h)}


def dig_tiles(L):
    t = M.tiles_from_dig(L.dig)
    return {(int(x), int(y)) for x, col in t.items() for y in col}


@test("orientation: every kind, every turn: same cells, nothing on one tile twice, stair never dug")
def _():
    for kind, params in ALL_KINDS:
        L0, t0, c0 = oriented(kind, params)
        assert L0.orient == 0, kind
        for o in range(4):
            L, tiles, cells = oriented(kind, params, orient=o)
            where = f"{kind} orient {o}"
            assert L.orient == o, where
            common_checks(L, tiles, cells)
            for ph in ("dig", "build", "place", "zone", "smooth", "engrave"):
                assert len(L[ph]) == len(L0[ph]), (where, ph)
            assert (0, 0) not in tiles and (0, 0) not in dig_tiles(L), where
            assert dig_tiles(L) == tiles, where
            assert tiles == {turn_pt(o, x, y) for x, y in t0}, where
            # every cell covers exactly the turned tiles of its unturned self
            want = sorted((ph, sorted(turn_pt(o, *p) for p in covered(x, y, t))) for ph, x, y, t in c0)
            got = sorted((ph, sorted(covered(x, y, t))) for ph, x, y, t in cells)
            assert want == got, where
            assert dict(L.furniture) == dict(L0.furniture), where
            b = L.bounds
            assert (b.x1, b.y1, b.x2, b.y2) == (min(x for x, _ in tiles), min(y for _, y in tiles),
                                                 max(x for x, _ in tiles), max(y for _, y in tiles)), where
            for h0, h in zip(L0.halls.values(), L.halls.values()):
                assert covered(h.x, h.y, f"({h.w}x{h.h})") == \
                    {turn_pt(o, *p) for p in covered(h0.x, h0.y, f"({h0.w}x{h0.h})")}, where
            if L.soil is not None:
                soil = {(int(x), int(y)) for x, col in L.soil.items() for y in col}
                soil0 = {(int(x), int(y)) for x, col in L0.soil.items() for y in col}
                assert soil == {turn_pt(o, x, y) for x, y in soil0}, where


@test("orientation: a turned bedroom level runs north-south; a mirrored temple faces west")
def _():
    L, tiles, cells = oriented("bedrooms", {"rooms": 8, "room_size": 3}, orient=2)
    assert all((0, k) in tiles and (0, -k) in tiles for k in range(2, 8)), sorted(tiles)
    assert not any((k, 0) in tiles for k in range(2, 8))
    zones = [c[3] for c in cells if c[0] == "zone"]
    assert all(z == "b(3x3)" for z in zones)
    L, tiles, cells = oriented("dining", {"tables": 12}, orient=3)
    assert [c[3] for c in cells if c[0] == "zone"] == ["h(11x10)"], [c for c in cells if c[0] == "zone"]
    L, tiles, cells = oriented("temple", {"size": "shrine"})
    assert all(x >= -1 for x, _ in tiles) and max(x for x, _ in tiles) == 8
    L, tiles, cells = oriented("temple", {"size": "shrine"}, orient=1)
    assert all(x <= 1 for x, _ in tiles) and min(x for x, _ in tiles) == -8
    zone = [c for c in cells if c[0] == "zone"][0]
    assert (zone[1], zone[2]) == (-8, -3) and zone[3].endswith("(7x7)"), zone


@test("pillar rhythm: dining and grand temple pillars follow it; rhythm 4 is the old layout")
def _():
    def pillars(kind, params, rhythm=None):
        L, tiles, cells = oriented(kind, params, rhythm=rhythm)
        common_checks(L, tiles, cells)
        h = L.halls[1]
        inside = {(x, y) for x in range(h.x, h.x + h.w) for y in range(h.y, h.y + h.h)}
        corners = {(h.x, h.y), (h.x + h.w - 1, h.y), (h.x, h.y + h.h - 1), (h.x + h.w - 1, h.y + h.h - 1)}
        return sorted(inside - tiles - corners), (tiles, cells)
    dining = ("dining", {"tables": 30, "style": {"hall": "pillared"}})
    base, raw = pillars(*dining)
    assert base == sorted([(x, y) for x in range(4, 21, 4) for y in (-2, 1)]), base    # today's: every 4
    four, raw4 = pillars(*dining, rhythm=4)
    assert four == base and raw4 == raw
    three, _ = pillars(*dining, rhythm=3)
    six, _ = pillars(*dining, rhythm=6)
    assert len(three) > len(base) > len(six), (len(three), len(base), len(six))
    assert (7, -2) in three and (10, 1) in six and (8, -2) not in six
    temple = ("temple", {"size": "grand"})
    tb, traw = pillars(*temple)
    assert tb == sorted([(x, y) for x in (5, 9, 13) for y in (-3, 3)]), tb
    t4, traw4 = pillars(*temple, rhythm=4)
    assert t4 == tb and traw4 == traw
    t3, _ = pillars(*temple, rhythm=3)
    assert t3 == sorted([(x, y) for x in (5, 8, 11) for y in (-3, 3)]), t3
    L, *_ = oriented("dining", {"tables": 8}, rhythm=99)
    assert L.style.rhythm == 6                                    # clamped (the bridge refuses it)



@test("jail: 3x3 cells, each with a door, a restraint and its own dungeon zone")
def _():
    L, tiles, cells = layout("jail", cells=3)
    assert len([c for c in cells if c[0] == "build" and c[3] == "v"]) == 3, cells
    assert len([c for c in cells if c[0] == "build" and c[3] == "d"]) == 3
    assert [c[3] for c in cells if c[0] == "zone"] == ["j(3x3)"] * 3
    assert L.summary.cells == 3

@test("dormitory (0.103.11): one hall of beds, a chest beside each, a dormitory zone")
def _():
    L, tiles, cells = layout("bedrooms", rooms=12, room_size=2, dormitory=True)
    common_checks(L, tiles, cells)
    assert L.furniture.Bed == 12 and L.furniture.Box == 12 and not L.furniture.Door, dict(L.furniture)
    assert [c[3] for c in cells if c[0] == "zone"] == ["D(15x7)"], [c for c in cells if c[0] == "zone"]
    assert L.summary.beds == 12 and L.summary.dormitory
    L, tiles, cells = layout("bedrooms", rooms=6, room_size=2)            # not asked: rooms as before
    assert L.furniture.Door == 6 and all(c[3].startswith("b(") for c in cells if c[0] == "zone")


if __name__ == "__main__":
    if "--show" in sys.argv:
        for kind, params in (("bedrooms", {"rooms": 16, "room_size": 3}), ("dining", {"tables": 12}),
                             ("storage", {"piles": ["food", "stone", "wood", "furniture"], "room_size": 5}),
                             ("workshops", {"shops": ["Still", "Kitchen", "Masons"]}),
                             ("dining", {"tables": 24, "style": {"hall": "pillared", "statues": 3}}),
                             ("temple", {"size": "grand", "style": {"statues": 2}}),
                             ("memorial", {"name": "Shulmik the Jackalowls", "style": {"statues": 4}}),
                             ("hospital", {"beds": 8}), ("barracks", {"beds": 8}),
                             ("tombs", {"coffins": 10}), ("tavern", {"tables": 8}), ("library", {"bookcases": 8}),
                             ("farms", {"plots": 5})):
            _, t, c = layout(kind, **params)
            print(f"\n{kind} {params}  (X = stair, . = dug, letters = buildings/stockpiles)\n" + draw(t, c))
        print()
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
