"""Tests for lua/ai-joins.lua (0.104.108): joining areas on one level.

Maps are drawn in text:  '#' rock, '.' passage floor, 'r' room floor (a zone
or building on it), '~' water, 'X' rock that can't be dug (a cavern wall).
"""
from __future__ import annotations

import sys
from pathlib import Path

from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parent.parent
LUA = LuaRuntime(unpack_returned_tuples=True)
M = LUA.execute("local src = ...; local env = setmetatable({}, {__index = _G}); "
                "assert(load(src, 'ai-joins', 't', env))(); return env",
                (ROOT / "lua" / "ai-joins.lua").read_text(encoding="utf-8"))
RESULTS = []


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


def reader(rows):
    def T(x, y):
        if y < 0 or y >= len(rows) or x < 0 or x >= len(rows[y]):
            return None
        c = rows[y][x]
        return LUA.table_from({"open": c in ".r", "passage": c == ".", "rock": c == "#",
                               "danger": c == "~"})
    return T


def seeds(*pts):
    return LUA.table_from({i + 1: LUA.table_from({"x": x, "y": y}) for i, (x, y) in enumerate(pts)})


def dug(r):
    return {(r.tiles[i].x, r.tiles[i].y) for i in range(1, len(r.tiles) + 1)}


# Two halls on one level, 6 tiles of rock apart; each ends in a corridor stub.
TWO = [
    "##############################",   # 0
    "#.......########.......#######",   # 1
    "#.......########.......#######",   # 2
    "#.......########.......#######",   # 3
    "##############################",   # 4
]


@test("two areas on one level: joined, 2 wide but 1 wide at each end, only through rock")
def _():
    r, why, stats = M.plan_join(reader(TWO), seeds((1, 1), (20, 2)))
    assert r, why
    assert stats.areas == 2
    t = dug(r)
    assert all(TWO[y][x] == "#" for x, y in t), t
    assert (r["from"].x, r["to"].x) == (7, 16), (r["from"].x, r["to"].x)
    assert r.length == 8 and len(t) == 8 + 6, (r.length, len(t))   # 2 wide inside, doorways 1 wide


@test("one area: nothing to join")
def _():
    rows = ["#####", "#...#", "#####"]
    r, why, stats = M.plan_join(reader(rows), seeds((1, 1)))
    assert r is None and why == "one area"


@test("too far apart (over 20 tiles of rock): left alone")
def _():
    rows = ["#" * 40, "#..#" + "#" * 30 + "#..#", "#" * 40]
    r, why, _ = M.plan_join(reader(rows), seeds((1, 1), (36, 1)))
    assert r is None and "none within" in why, why


@test("never from or into a room, and never opening onto a room on the way")
def _():
    rows = [
        "##############",
        "#..###rr###..#",   # a room between them, right on the shortest line
        "#..########..#",
        "#..########..#",
        "#..########..#",
        "##############",
        "##############",
    ]
    r, why, _ = M.plan_join(reader(rows), seeds((1, 1), (12, 1), (6, 1)))
    assert r, why
    for x, y in dug(r):
        near = {rows[y + dy][x + dx] for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
        assert "r" not in near, (x, y)
    assert rows[r["from"].y][r["from"].x] == "." and rows[r["to"].y][r["to"].x] == "."


@test("water beside the only way: refused")
def _():
    rows = [
        "################",
        "#..#####~####..#",
        "################",
    ]
    r, why, _ = M.plan_join(reader(rows), seeds((1, 1), (14, 1)))
    assert r is None, "dug beside water"


@test("a dead-end corridor is preferred as an end over an equally near hall")
def _():
    rows = [
        "##############",
        "#....#########",   # 1  hall
        "#....#########",   # 2
        "#....#########",   # 3
        "#.############",   # 4  its corridor, ending in rock at (1,6)
        "#.############",   # 5
        "#.######...###",   # 6  the other area
        "########...###",   # 7
        "########...###",   # 8
        "##############",
    ]
    r, why, stats = M.plan_join(reader(rows), seeds((1, 1), (9, 7)))
    assert r, why
    assert stats.dead_ends == 1 and r.dead_end and (r["from"].x, r["from"].y) == (1, 6), \
        (r["from"].x, r["from"].y, stats.dead_ends)


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
