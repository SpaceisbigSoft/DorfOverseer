"""Tests for brain/tools/draw_level.py: level layouts drawn as text.

render() takes plain Python data and needs no Lua; the tests that draw
lua/ai-layouts.lua's kinds run it in a real Lua engine (pip install lupa).

    python tests/test_draw_level.py            run the tests
    python tests/test_draw_level.py --show     also draw every kind
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import finish, have_lua, need_lua, test  # noqa: E402

sys.path.insert(0, str(ROOT / "brain" / "tools"))
import draw_level as D  # noqa: E402

# a 3x2 room, a doorway under its middle and a 1-wide way south of it
ROOM = [(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (1, 2), (1, 3)]


def picture(text: str) -> list[str]:
    """The grid's rows (the lines made only of grid characters before the summary)."""
    rows = []
    for line in text.splitlines():
        if line.startswith("==") or " x " in line:
            if rows:
                break
            continue
        rows.append(line)
    return rows


# ---------------------------------------------------------------------------
# render(): plain data, no Lua
# ---------------------------------------------------------------------------

@test("render: a hand-made set of cells is drawn with one tile of rock round it")
def _():
    text = D.render(ROOM)
    assert text.splitlines()[:6] == ["#####",
                                     "#...#",
                                     "#...#",
                                     "##.##",
                                     "##.##",
                                     "#####"], text
    assert "3 x 4, 8 dug tiles, narrowest way 1 wide" in text, text
    assert "legend: # rock, . dug floor" in text and "stair" not in text, text
    assert text.endswith("\n")


@test("render: marks as tuples get a letter each and a legend with counts")
def _():
    text = D.render(ROOM, marks=[(1, 2, "door"), (0, 0, "bed"), (2, 0, "bed"), (1, 0, "table", "T")])
    rows = text.splitlines()
    assert rows[1] == "#bTb#" and rows[3] == "##d##", text
    assert "d door" in text and "b bed (2)" in text and "T table" in text, text
    assert "8 dug tiles" in text, "marks never change the dug count"


@test("render: two labels wanting the same letter get different glyphs")
def _():
    text = D.render(ROOM, marks=[(0, 0, "bed"), (1, 0, "box"), (2, 0, "barrel"), (0, 1, "#bad"), (1, 1, "x", "#")])
    legend = [ln for ln in text.splitlines() if ln.startswith("legend:")][0]
    glyphs = [item.split()[0] for item in legend[len("legend:"):].split(",")]
    assert len(glyphs) == len(set(glyphs)), legend
    assert "b bed" in legend and "B box" in legend, legend
    # the rock and floor characters are never given to a mark
    assert legend.count("# ") == 1 and legend.count(". ") == 1, legend


@test("render: a dict of marks, an area mark, and a mark on rock")
def _():
    text = D.render({"cells": ROOM, "marks": [{"x": 0, "y": 0, "w": 3, "h": 2, "label": "food stockpile", "glyph": "F"}]},
                    marks={"lever": [(4, 3)]})
    rows = text.splitlines()
    assert rows[1] == "#FFF###" and rows[2] == "#FFF###", text
    assert rows[4] == "##.##l#", text            # the picture grows to hold a mark outside the dug tiles
    assert "F food stockpile" in text and "l lever" in text, text


@test("render: a layout dict draws the stair, the hub, a title, rooms and the corridor's width")
def _():
    cells = [(x, y) for x in range(-1, 6) for y in range(-1, 2) if (x, y) != (0, 0)]
    text = D.render({"cells": cells, "stair": (0, 0), "title": "== test", "rooms": 2, "corridor": 3,
                     "notes": ["a note"]})
    rows = text.splitlines()
    assert rows[0] == "== test"
    assert rows[2:5] == ["#:::....#", "#:X:....#", "#:::....#"], text
    assert "7 x 3, 20 dug tiles, 2 rooms, corridor 3 wide, narrowest way 3 wide" in text, text
    assert "X stair, : hub" in text and rows[-1] == "a note", text
    off = D.render({"cells": cells, "stair": (0, 0), "hub": False})
    assert ":" not in off.split("legend")[0] and "#.X.....#" in off, off


@test("render: nothing to draw is said, not an error")
def _():
    assert "nothing to draw" in D.render([])
    assert "nothing to draw" in D.render({"cells": []})


@test("narrowest: doorways, corridors and rooms")
def _():
    assert D.narrowest([]) == 0
    assert D.narrowest(ROOM) == 1
    assert D.narrowest([(x, y) for x in range(9) for y in range(2)]) == 2
    assert D.narrowest([(x, y) for x in range(4) for y in range(3)]) == 3


@test("parse_params: numbers, booleans, lists, JSON and the style's fields")
def _():
    p = D.parse_params(["rooms=6", "dormitory=true", "name=the Fallen", "shops=Still,Kitchen",
                        "piles=[\"food\"]", "style.hall=rounded", "style.customs=cloister+armoury",
                        "style=arms=ring,orient=2"])
    assert p == {"rooms": 6, "dormitory": True, "name": "the Fallen", "shops": ["Still", "Kitchen"],
                 "piles": ["food"],
                 "style": {"hall": "rounded", "customs": ["cloister", "armoury"], "arms": "ring", "orient": 2}}, p
    assert D.parse_params(["style={\"hall\": \"round\"}"]) == {"style": {"hall": "round"}}
    for bad in (["rooms"], ["style=ring"]):
        try:
            D.parse_params(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad} should be refused")


@test("params_for: rooms=N for workshops and storage means the first N shops or piles")
def _():
    assert len(D.params_for("workshops", {"rooms": 6})["shops"]) == 6
    assert D.params_for("workshops", {"rooms": 99})["shops"] == D.ROOM_LISTS["workshops"][1]
    assert D.params_for("workshops", {"rooms": 6, "shops": ["Loom"]})["shops"] == ["Loom"]
    assert len(D.params_for("storage", {"rooms": 2})["piles"]) == 2
    assert D.params_for("bedrooms", {"rooms": 6}) == {"rooms": 6, "room_size": 3}


# ---------------------------------------------------------------------------
# lua/ai-layouts.lua's kinds (lupa)
# ---------------------------------------------------------------------------

def lua_tiles(kind, params):
    """The dug tiles of make(kind, params), counted in Lua (not through draw_level's own flattening)."""
    lua, M = D.load_layouts()
    L = M.make(kind, D._to_lua(lua, params))
    L = L[0] if isinstance(L, tuple) else L
    assert L is not None, f"{kind}: make() refused {params}"
    n = lua.eval("function(L) local n = 0; for _, col in pairs(L.tiles) do for _ in pairs(col) do n = n + 1 end end; "
                 "return n end")(L)
    return L, int(n)


def check(kind, params):
    data = D.layout_data(kind, params)
    text = D.render(data)
    L, n = lua_tiles(kind, data["params"])
    assert len(data["cells"]) == n and f", {n} dug tiles" in text, f"{kind}: {len(data['cells'])} drawn, {n} in the layout"
    rows = picture(text)
    b = L.bounds
    w, h = b.x2 - b.x1 + 1, b.y2 - b.y1 + 1
    assert f"{w} x {h}, " in text, f"{kind}: bounds {w} x {h} not in the summary"
    assert len({len(r) for r in rows}) == 1, f"{kind}: ragged picture"
    assert sum(r.count("X") for r in rows) == 1, f"{kind}: one stair"
    assert sum(r.count(":") for r in rows) == 8, f"{kind}: the hub's 8 tiles"
    # every tile that is not rock is a dug tile or the stair: marks never spill onto rock
    open_tiles = sum(len(r) - r.count("#") for r in rows)
    assert open_tiles == n + 1, f"{kind}: {open_tiles} tiles drawn open, {n} dug + the stair"
    legend = text[text.index("legend:"):]
    assert "X stair" in legend and ": hub" in legend, legend
    return data, text


@test("every kind in ai-layouts.lua has default parameters and draws; the dug count matches the layout")
def _():
    need_lua()
    _, M = D.load_layouts()
    lua_kinds = [M.KINDS[i] for i in range(1, len(M.KINDS) + 1)]
    assert lua_kinds and set(lua_kinds) <= set(D.kinds())
    missing = [k for k in lua_kinds if k not in D.DEFAULTS]
    assert not missing, f"no default parameters for {missing}"
    for kind in D.kinds():
        _, text = check(kind, None)
        if "--show" in sys.argv:
            print(text)


@test("every kind draws turned and styled too (orient 0-3, a round hall, cross and ring arms)")
def _():
    need_lua()
    for kind in D.kinds():
        base = len(D.layout_data(kind)["cells"])
        for style in ({"orient": 1}, {"orient": 2}, {"orient": 3}):
            data, _ = check(kind, {"style": style})
            assert len(data["cells"]) == base, f"{kind}: turning changed the dug count"
        for style in ({"hall": "round", "motif": "ring", "statues": 4}, {"arms": "cross"},
                      {"arms": "ring", "hall": "rounded"}, {"customs": ["cloister", "armoury", "ore_piles"]}):
            check(kind, {"style": style})


@test("workshops: six rooms, each shop its own digit in a 3x3 of w; the corridor is 3 wide")
def _():
    need_lua()
    data, text = check("workshops", {"rooms": 6})
    assert data["rooms"] == 6 and data["corridor"] == 3
    assert ", 6 rooms, corridor 3 wide, narrowest way 3 wide" in text, text
    rows = picture(text)
    assert sum(r.count("w") for r in rows) == 6 * 8, text
    for i, shop in enumerate(data["params"]["shops"], 1):
        assert sum(r.count(str(i)) for r in rows) == 1 and f"{i} {shop}" in text, text
    assert "w workshop (6)" in text
    # spare rooms are dug and counted, and said
    spare, text2 = check("workshops", {"shops": ["Still"], "spare": 2})
    assert spare["rooms"] == 3 and "free rooms: 2" in text2, text2


@test("bedrooms: a door, a bed, a cabinet and a chest a room; the zones are listed, not drawn")
def _():
    need_lua()
    data, text = check("bedrooms", {"rooms": 8, "room_size": 3})
    rows = picture(text)
    for glyph in "Dbfh":
        assert sum(r.count(glyph) for r in rows) == 8, f"{glyph}: {text}"
    assert "D door (8), b bed (8), f cabinet (8), h chest (8)" in text, text
    assert ", 8 rooms, corridor 2 wide" in text and "zones (not drawn): 8 x bedroom" in text, text


@test("storage: each pile's room is filled with its own letter")
def _():
    need_lua()
    data, text = check("storage", {"piles": ["food", "stone"], "room_size": 5})
    rows = picture(text)
    assert sum(r.count("F") for r in rows) == 25 and sum(r.count("S") for r in rows) == 25, text
    assert "F food stockpile (25), S stone stockpile (25)" in text and data["rooms"] == 2, text


@test("make()'s refusals are a ValueError with its words")
def _():
    need_lua()
    for kind, params, words in (("nonsense", {}, "unknown level kind"),
                                ("workshops", {"shops": ["Nope"]}, "no valid workshop types")):
        try:
            D.layout_data(kind, params)
        except ValueError as e:
            assert words in str(e), e
            continue
        raise AssertionError(f"{kind} should be refused")


@test("the command line: a kind with --param, --all, --list, --out FILE, and a bad kind")
def _():
    need_lua()
    import contextlib
    import io

    def run(*argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = D.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    code, out, _ = run("workshops", "--param", "rooms=6", "--param", "style=hall=rounded")
    assert code == 0 and out == D.draw("workshops", {"rooms": 6, "style": {"hall": "rounded"}}), out
    assert out.startswith("== workshops (") and ", 6 rooms" in out
    code, out, _ = run("--all")
    assert code == 0
    for kind in D.kinds():
        assert f"== {kind} (" in out, kind
    code, out, _ = run("--list")
    assert code == 0 and out.count("\n") == len(D.kinds())
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "level.txt"
        code, out, _ = run("bedrooms", "--param", "rooms=4", "--out", str(f))
        assert code == 0 and "wrote" in out
        assert f.read_text(encoding="utf-8") == D.draw("bedrooms", {"rooms": 4})
    code, out, err = run("nonsense")
    assert code == 1 and out == "" and "unknown level kind" in err


if __name__ == "__main__":
    if not have_lua():
        print("(without lupa only render() is tested: pip install lupa)")
    finish()
