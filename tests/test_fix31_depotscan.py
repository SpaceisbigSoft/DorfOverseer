"""(0.105.31) The gates' entrance scan leaves the AI's deep depot hall (and
its wagon road) out of its starting points, as 0.105.30 left out the keep
and the surface hall: a dwarf in the hall made the road look like a way in.
Needs lupa.

    python tests/test_fix31_depotscan.py
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


def _const(path: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / path).read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name)


GATES_HARNESS = _const("test_construct_gates.py", "GATES_HARNESS")


def K(x, y, z=0):
    return (z * 4096 + y) * 4096 + x


def gates():
    lua = LuaRuntime(unpack_returned_tuples=True)
    M, W = lua.execute(GATES_HARNESS, module_src("ai-gates.lua"))
    return lua, M, W


def set_map(lua, W, rows, width=40):
    lvl = lua.table()
    for y, r in enumerate(rows):
        lvl[y] = r
    m = lua.table()
    m[0] = lvl
    W.map = m
    W.size = lua.table_from({1: width, 2: len(rows)})
    W.keepouts = lua.table()


def with_builder(lua, M, deep):
    """reqscript('ai-builder') gives a builder whose deep depot record is `deep`."""
    lua.execute("""local M, deep = ...
      M.reqscript = function(name)
          return {deep_depot_data = function() return deep end,
                  keep_data = function() return nil end, halls_data = function() return nil end}
      end""", M, deep)


def deep_record(lua, stage="done"):
    hall = lua.table_from({"x1": 20, "y1": 1, "x2": 28, "y2": 9, "z": 0})
    tiles = lua.table_from([lua.table_from({"x": 19, "y": y, "z": 0, "r": "d"}) for y in (4, 5, 6)])
    return lua.table_from({"stage": stage, "hall": hall, "tiles": tiles})


@test("depotscan 1: the deep depot's hall and road are in the AI's boxes, on their own level only")
def _():
    lua, M, W = gates()
    with_builder(lua, M, deep_record(lua))
    got = M.ai_surface_box_keys()
    assert got[K(20, 1)] and got[K(28, 9)] and got[K(24, 5)]
    assert got[K(19, 5)]                                      # the road's dug tile
    assert got[K(24, 5, 1)] is None                           # not the level above
    assert got[K(29, 5)] is None and got[K(5, 5)] is None
    # no road found: nothing of it
    with_builder(lua, M, deep_record(lua, "no_road"))
    assert next(iter(M.ai_surface_box_keys().keys()), None) is None
    # no deep depot at all
    with_builder(lua, M, None)
    assert next(iter(M.ai_surface_box_keys().keys()), None) is None


@test("depotscan 2: a dwarf in the deep depot hall seeds no fort of its own while others are elsewhere")
def _():
    lua, M, W = gates()
    # the fort x1-8; the depot hall x20-28 (81 tiles, under LEDGE_MAX: a
    # small "fort" of its own), joined to the fort by nothing walkable here
    rows = ["#" * 40]
    for y in range(1, 10):
        rows.append("#" + "." * 8 + "#" * 11 + "." * 9 + "#" * 11)
    rows.append("#" * 40)
    set_map(lua, W, rows)
    starts = lua.table_from([lua.table_from({"x": 3, "y": 3, "z": 0}), lua.table_from({"x": 24, "y": 5, "z": 0})])
    with_builder(lua, M, None)
    assert len(M.fort_starts(starts)) == 2                   # without the record: two "forts"
    with_builder(lua, M, deep_record(lua))
    got = M.fort_starts(starts)
    assert len(got) == 1 and got[1].x == 3, [(p.x, p.y) for p in got.values()]
    # the hall's dwarf alone: never no fort at all
    got = M.fort_starts(lua.table_from([lua.table_from({"x": 24, "y": 5, "z": 0})]))
    assert len(got) == 1


@test("depotscan 3: find_entrances' starts come through fort_starts (the exclusion applies to the scan)")
def _():
    src = module_src("ai-gates.lua")
    i = src.index("local entrances, inside, n = find_entrances(fstarts")
    assert "fort_starts(" in src[max(0, i - 1500):i]


if __name__ == "__main__":
    sys.exit(finish())
