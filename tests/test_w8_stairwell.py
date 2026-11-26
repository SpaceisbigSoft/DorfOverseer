"""(R29 W8) A new stairwell through the fort's dug floors: D refused 29 times on
25 Nov ("stairs down to z38: not solid rock (already dug or open) at x104 y139
z39"). lua/ai-builder-sites.lua stairwell_cells: a level where the stair tile
is the fort's own dug floor takes a constructed stair (Cx; Cu at the bottom),
a rock tile may have the fort's walkable space beside it; open space, the sky,
caverns and water still refuse. A refused direction tries its two sides before
refusing. On test_builder's fake fort (its harness read by ast). Needs lupa.

    python tests/test_w8_stairwell.py
"""

from __future__ import annotations

import ast
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


def _string_assign(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name)


HARNESS = _string_assign(ROOT / "tests" / "test_builder.py", "HARNESS")
LUA = LuaRuntime(unpack_returned_tuples=True)
LUA.globals().LUA_DIR = str(ROOT / "lua")
B, W = LUA.execute(HARNESS, (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8"),
                   (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8"))
T = LUA.table_from


def _reset():
    W.reset()
    B.CACHE = None


test = make_test(before=_reset)


def params(**kw):
    t = LUA.table()
    for k, v in kw.items():
        t[k] = T(v) if isinstance(v, (list, dict)) else v
    return t


def east(dry):
    return B.dig_stairwell(params(dir="east", elev_lo=62, elev_hi=66, min_dist=10, max_dist=40), dry)


def placed():
    return [(p.x, p.y, p.z, p.text) for p in W.placed.values()]


def room(z, cx=70, cy=60):
    for x in range(cx - 1, cx + 2):
        for y in range(cy - 1, cy + 2):
            W.set(x, y, z, T({"shape": "FLOOR"}))


@test("a dug room crossed: a constructed up/down stair there, the rock levels dug as before")
def _():
    room(64)
    r = east(True)
    assert r.ok and (r.x, r.y) == (70, 60) and r.built == 1 and r.dry_run, dict(r)
    assert not placed() and not any(t.designated for t in W.tiles.values())
    r = east(False)
    assert r.ok and (r.x, r.y) == (70, 60) and r.levels == 5 and r.built == 1, dict(r)
    assert placed() == [(70, 60, 64, "Cx")], placed()
    assert [W.get(70, 60, z).dig_text for z in (66, 65, 63, 62)] == ["j", "i", "i", "u"]
    assert W.get(70, 60, 64).dig_text is None


@test("the bottom level a dug floor: a constructed up stair (Cu)")
def _():
    room(62)
    r = east(False)
    assert r.ok and (r.x, r.y) == (70, 60), dict(r)
    assert placed() == [(70, 60, 62, "Cu")], placed()
    assert [W.get(70, 60, z).dig_text for z in (66, 65, 64, 63)] == ["j", "i", "i", "i"]


@test("a rock tile beside the fort's dug floor (a corridor, a ramp) is dug; nothing built")
def _():
    W.set(71, 60, 64, T({"shape": "FLOOR"}))
    W.set(69, 61, 63, T({"shape": "RAMP"}))
    r = east(False)
    assert r.ok and (r.x, r.y) == (70, 60) and r.built is None, dict(r)
    assert not placed()
    assert [W.get(70, 60, z).dig_text for z in (66, 65, 64, 63, 62)] == ["j", "i", "i", "i", "u"]


@test("still refused: open space, the sky, a cavern or water on the way (beside or on the tile)")
def _():
    for bad in ({"shape": "EMPTY"}, {"shape": "FLOOR", "outside": True}, {"shape": "FLOOR", "feature": True},
                {"shape": "FLOOR", "liquid": True}):
        W.reset()
        B.CACHE = None
        W.set(71, 60, 64, T(bad))
        r = east(True)
        if r.ok:
            assert max(abs(r.x - 71), abs(r.y - 60)) > 1, (bad, dict(r))
        W.reset()
        B.CACHE = None
        W.set(70, 60, 64, T(bad))
        r = east(True)
        assert not (r.ok and (r.x, r.y) == (70, 60)), (bad, dict(r))


@test("a floor with a building or a zone is not built over")
def _():
    room(64)
    W.set(70, 60, 64, T({"shape": "FLOOR", "taken": True}))
    r = east(True)
    assert not (r.ok and (r.x, r.y) == (70, 60)), dict(r)
    W.reset()
    room(64)
    W.get(70, 60, 64).zones = T(["Bedroom"])
    B.CACHE = None
    r = east(True)
    assert not (r.ok and (r.x, r.y) == (70, 60)), dict(r)


@test("the game refusing the construction: refused with why; a real run undone (no stray dig)")
def _():
    room(64)
    LUA.execute("""local q = reqscript('quickfort'); W8_REAL = q.apply_blueprint
        q.apply_blueprint = function(p) local s = W8_REAL(p); if p.mode == 'build' then s.build_designated.value = 0 end; return s end""")
    try:
        r = east(False)
        if r.ok:
            assert (r.x, r.y) != (70, 60) and r.built is None, dict(r)
        else:
            assert "would not build a stair" in r.error or "no place" in r.error, dict(r)
        assert not W.get(70, 60, 66).designated
    finally:
        LUA.execute("local q = reqscript('quickfort'); q.apply_blueprint = W8_REAL")


@test("a direction with no place turns to its sides before refusing (never the opposite); said so")
def _():
    # north of the main stair: no fort floor (the floors are y55-65)
    r = B.dig_stairwell(params(dir="north", elev_lo=62, elev_hi=66, min_dist=10, max_dist=40), True)
    assert r.ok and r.turned_from == "north" and r.dir in ("east", "west"), dict(r)
    r = B.dig_stairwell(params(dir="north", elev_lo=62, elev_hi=66, min_dist=10, max_dist=40, turned_from="x"), True)
    assert not r.ok and "north" in r.error, dict(r)
    # east finds its own place: no turn
    r = east(True)
    assert r.ok and r.dir == "east" and r.turned_from is None, dict(r)
    assert B.CACHE is None


@test("check_extension's other callers keep the old rule (untouched rock only)")
def _():
    room(64)
    ok = B.check_extension(70, 60, 66, 62, True)
    assert ok is not True and not (isinstance(ok, tuple) and ok[0]), ok


@test("the part stays under 57 KB")
def _():
    assert (ROOT / "lua" / "ai-builder-sites.lua").stat().st_size < 57 * 1024


if __name__ == "__main__":
    finish()
