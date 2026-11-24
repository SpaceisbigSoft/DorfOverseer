"""(0.105.97, verifier) The independent check's fixes.

1. A killer's cell, locked with an empty pile inside the gap between two
   restockings (RESTOCK_GAP), said so in its report row (`restock_wait`); the
   brain doesn't ask the cell action every cycle for it ("killer" is an
   emergency rule: no back-off, and the bridge answered "stocking" each time).
2. The doors opened for the haulers shut again at once when the killer starts
   to rage (the burrow holds no one in a tantrum); the merge fix only kept
   them from opening.
3. A squad given a kill order lets its soldiers on leave out of the
   recreation burrow at once, as a squad back on duty does.

The Lua tests need lupa (they skip without it); the rest run anywhere.

    python tests/test_r97_verifier.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import PLANNER_CONFIG  # noqa: E402
import planner_killers as PK  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

SRC = (ROOT / "lua" / "ai-killers.lua").read_text(encoding="utf-8")
CIVIC = (ROOT / "lua" / "ai-bridge-actions-civic.lua").read_text(encoding="utf-8")
ITEM3 = (ROOT / "tests" / "test_item3_killers.py").read_text(encoding="utf-8")
DRINK = (ROOT / "tests" / "test_r97_cell_drink.py").read_text(encoding="utf-8")
FAKE = re.search(r'FAKE = r"""(.*?)"""', ITEM3, re.S).group(1)
EXTRA = re.search(r'EXTRA = r"""(.*?)"""', DRINK, re.S).group(1)
DAY = 1200


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-killers.lua"))
    lua.execute(EXTRA, env, w)
    return lua, env, w


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


def py(v):
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    try:
        keys = list(v.keys())
    except AttributeError:
        return v
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in sorted(keys)]
    return {k: py(v[k]) for k in keys}


def advance(env, ticks):
    g = env.df["global"]
    g.cur_year_tick = g.cur_year_tick + ticks


def cell(lua, env, ids):
    return py(env.cell(T(lua, {"units": ids}), False))


def locked_in(lua, env, w):
    u = w.unit(T(lua, {"id": 3, "name": "Degel", "citizen": True, "pos": {"x": 10, "y": 10, "z": 100}}))
    z = T(lua, {"id": 500, "x1": 20, "y1": 20, "x2": 22, "y2": 22, "z": 100, "assigned_unit_id": -1})
    w.bedrooms[1] = z
    d = w.door(T(lua, {"id": 600, "x": 23, "y": 21, "z": 100}))
    w.bed(20, 20, 100)
    cell(lua, env, [3])
    u.pos.x, u.pos.y = 21, 21
    cell(lua, env, [3])
    return u, z, d


# --- the source ------------------------------------------------------------------

@test("source: the report row says restock_wait; restocking reads the rage; a kill order releases the squad's leave")
def _():
    assert "row.restock_wait = true" in SRC and "t - c.restock_end < RESTOCK_GAP" in SRC
    assert "local function restocking(c, t, dry, memo, u)" in SRC and "restocking(c, t, dry, memo, u)" in SRC
    assert SRC.index("local function raging(u)") < SRC.index("local function larder_check(")
    body = CIVIC.split("function act_squad_orders(a)")[1].split("\nend\n")[0]
    assert "squad_rec_release(id, r)" in body and "r.ok" in body
    assert CIVIC.index("local function squad_rec_release(id, r)") < CIVIC.index("function act_squad_routine(a)")


# --- the brain ---------------------------------------------------------------------

def run(killers):
    props, notes = [], []
    PK._killer_rule({"killers": killers}, dict(PLANNER_CONFIG), props, notes, None)
    return props, notes


def row(**kw):
    r = {"id": 3, "name": "Degel", "kind": "killer", "confidence": "strong", "citizen": True, "kills": 2,
         "victims": ["A", "B"], "seen_ticks": 2000}
    r.update(kw)
    return r


@test("brain: a locked empty cell inside the restock gap is said, not proposed for every cycle")
def _():
    c = {"locked": True, "pile": 701, "drink": 0, "food": 0, "pile_empty": True, "restock_wait": True}
    p, n = run({"list": [row(cell=c)], "cells": [dict(c, unit_id=3)], "rooms": 0})
    assert p == [], p
    assert "the cell's pile is empty" in n[0] and "again after a short wait" in n[0], n
    c.pop("restock_wait")
    p, n = run({"list": [row(cell=c)], "cells": [dict(c, unit_id=3)], "rooms": 0})
    assert len(p) == 1 and "waits for drink" in p[0].reason, p


# --- the bridge (lupa) ---------------------------------------------------------------

@test("cell: the report row says restock_wait inside the gap after the doors locked again, not after it")
def _():
    need_lua()
    lua, env, w = world()
    u, z, d = locked_in(lua, env, w)
    cell(lua, env, [3])                                   # opened for the haulers
    advance(env, 2 * DAY)
    r = cell(lua, env, [3])                               # time up: locked again
    assert r["locked"] == ["Degel"], r
    c = py(env.report())["cells"][0]
    assert c.get("restock_wait") is True, c
    advance(env, 3 * DAY)
    c = py(env.report())["cells"][0]
    assert "restock_wait" not in c, c


@test("cell: doors open for the haulers shut at once when the killer starts to rage")
def _():
    need_lua()
    lua, env, w = world()
    u, z, d = locked_in(lua, env, w)
    r = cell(lua, env, [3])
    assert r["stocking"] == ["Degel"] and d.door_flags.forbidden is False, r
    env.df.soldier_mood_type = T(lua, {1: "Tantrum"})
    u.counters = T(lua, {"soldier_mood": 1})
    r = cell(lua, env, [3])
    assert r["locked"] == ["Degel"] and d.door_flags.forbidden is True, r
    r = cell(lua, env, [3])                               # still raging, empty: never opened
    assert d.door_flags.forbidden is True, r


finish()
