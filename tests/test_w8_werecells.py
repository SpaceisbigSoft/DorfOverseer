"""(R29 W8) A were cell shut on every side but its bridge. F, 25 Nov 17:21-17:27:
Besmar was locked behind a raised bridge and found turned nine levels down.
A read-only probe that evening (21:42) found F's two cells (and A's five, E's
six) shut all round, diagonals and above included, the raised ones cut off in
DF's walk map (F were:58:2 group 3005, the corridor 1, Besmar inside), and the
weremole (NIGHT_CREATURE_49) with no way to dig. lua/ai-werecells.lua now
checks it all the same: sealed(c) (every tile round the box a wall, its own
tiles floor, a roof above them and above the bridge), a cell not sealed is
never ready (moon_cell takes another room), and the report counts `open`
cells and `joined` ones (raised, yet DF still walks from inside to the lever).

    python tests/test_w8_werecells.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402

import ast  # noqa: E402


def _string_assign(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name)


WERE_GAME = _string_assign(ROOT / "tests" / "test_item24_were_cells.py", "WERE_GAME")

# the cell of T24's fake game: box x10-11 y11-12 z10, bridge 11,13, lever 11,14
SHAPES = r"""
local E = ...
E.SH = {}
for y = 9, 16 do for x = 8, 14 do
  E.SH[x .. ',' .. y .. ',10'] = 'WALL'
  E.SH[x .. ',' .. y .. ',11'] = 'FLOOR'
end end
for y = 11, 12 do for x = 10, 11 do E.SH[x .. ',' .. y .. ',10'] = 'FLOOR' end end
E.SH['11,13,10'] = 'FLOOR'      -- the bridge
E.SH['11,14,10'] = 'FLOOR'      -- the lever's corridor
E.shape_at = function(x, y, z) return E.SH[x .. ',' .. y .. ',' .. z] end
E.WG = {}
E.walk_group = function(x, y, z) return E.WG[x .. ',' .. y .. ',' .. z] end
"""


def env():
    need_lua()
    from lupa.lua53 import LuaRuntime
    from lua_modules_util import module_src
    lua = LuaRuntime(unpack_returned_tuples=True)
    E = lua.execute(WERE_GAME, module_src("ai-werecells.lua"))
    lua.execute(SHAPES, E)
    lua.execute("local E = ...; E.G.links[900] = {901}", E)
    return lua, E, E.cells()[1]


def setshape(lua, E, key, shape):
    lua.execute("local E, k, s = ...; E.SH[k] = s", E, key, shape)


@test("a cell walled all round, floored, roofed: sealed and ready")
def _():
    lua, E, c = env()
    ok = E.sealed(c)
    assert ok is True or ok == (True,) or (isinstance(ok, tuple) and ok[0] is True), ok
    r, st = E.ready(c)
    assert r is True and st.open is None, dict(st)


@test("a gap anywhere: not sealed, not ready, said where (a side, a diagonal, open above, a stair, above the bridge)")
def _():
    for key, shape, words in (("12,11,10", "FLOOR", "side"), ("9,10,10", "FLOOR", "side"),     # beside, a diagonal
                              ("12,13,10", "EMPTY", "side"),                                  # the bridge's corner
                              ("10,11,11", "EMPTY", "open above"), ("11,12,11", "STAIR_DOWN", "open above"),
                              ("10,12,10", "STAIR_DOWN", "own tile"), ("11,11,10", "RAMP", "own tile"),
                              ("11,13,11", "EMPTY", "above the bridge")):
        lua, E, c = env()
        setshape(lua, E, key, shape)
        ok, why = E.sealed(c)
        assert ok is False and words in why, (key, shape, ok, why)
        r, st = E.ready(c)
        assert r is False and words in st.open, (key, dict(st))
        rep = E.report(None)
        assert rep.open == 1 and rep.ready == 0 and rep.free == 0 and words in rep.rows[1].open, dict(rep)


@test("a roof that is a ramp or a floor holds; the tiles unread: as before (ready)")
def _():
    lua, E, c = env()
    setshape(lua, E, "10,11,11", "RAMP")
    setshape(lua, E, "11,11,11", "WALL")
    assert E.ready(c)[0] is True
    lua.execute("local E = ...; E.shape_at = function() return nil end", E)
    assert E.sealed(c) is None and E.ready(c)[0] is True


@test("raised and still: joined when DF's walk map still links the inside to the lever; not when cut off")
def _():
    lua, E, c = env()
    ok, _ = E.set_raised(c, True, False)
    assert ok and E.cell_state(c).raised
    assert E.cell_state(c).joined is None                         # walk groups unread
    lua.execute("local E = ...; E.WG['10,11,10'] = 7; E.WG['11,14,10'] = 7", E)
    st = E.cell_state(c)
    assert st.joined is True, dict(st)
    rep = E.report(None)
    assert rep.joined == 1 and rep.rows[1].joined is True, dict(rep)
    lua.execute("local E = ...; E.WG['10,11,10'] = 3005; E.WG['11,14,10'] = 1", E)
    assert E.cell_state(c).joined is None and E.report(None).joined is None
    # lowered: never joined (that is how a lowered cell is)
    ok, _ = E.set_raised(c, False, False)
    lua.execute("local E = ...; E.WG['10,11,10'] = 1", E)
    assert ok and E.cell_state(c).joined is None


if __name__ == "__main__":
    finish()
