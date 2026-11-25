"""(0.105.114 item15) A killer who is not calm is locked at once: no larder wait.

Live E, 25 Nov 06:00-08:00: the killer rule ran killer_cell about every
minute on Dentconstruct (19508: a werebeast, certain, people 2) with "1
cell(s): the cell's pile waits for drink and meals"; the doors opened for the
haulers each time the pile ran low, he was out of his cell ("waiting") 30 of
77 cycles, and at 08:00 he killed two citizens in were form and was struck
down. Now a held killer who is a werebeast, transformed, in a tantrum (or
berserk), or who killed within the last day is locked at once: the cell's
doors are never opened for the haulers while so (drink and meals come once
calm), the let-outs only at the last-resort levels; the larder wait is for
calm cases only. The brain says it and passes `urgent` in the killer_cell
action; lua/ai-killers.lua (urgent_of) also sees a tantrum, a were form or a
were syndrome itself.

The Lua tests need lupa (they skip without it; run them on the PC).

    python tests/test_i114_killer_cell.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src, split_src  # noqa: E402

from planner import Memory, PLANNER_CONFIG as cfg  # noqa: E402
import planner_killers as PK  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

SRC = split_src("ai-killers.lua")
R97 = (ROOT / "tests" / "test_r97_cell_drink.py").read_text(encoding="utf-8")
ITEM3 = (ROOT / "tests" / "test_item3_killers.py").read_text(encoding="utf-8")
FAKE = re.search(r'FAKE = r"""(.*?)"""', ITEM3, re.S).group(1)
EXTRA = re.search(r'EXTRA = r"""(.*?)"""', R97, re.S).group(1)
DAY = 1200

YEAR, TICK = 270, 65088
DENT = 19508


# --- the brain ---------------------------------------------------------------------

def state(killers=None, cells=None, tantrums=None):
    s = {"date": {"year": YEAR, "tick": TICK}, "killers": {"list": killers or [], "cells": cells or [], "rooms": 5}}
    if tantrums is not None:
        s["tantrums"] = {"dwarves": tantrums, "loose": sum(1 for t in tantrums if t.get("now"))}
    return s


def krow(uid, name, kind="killer", conf="weak", people=1, ago=5000, **kw):
    return {"id": uid, "name": name, "kind": kind, "confidence": conf, "citizen": True, "kills": people,
            "people": people, "last_ago": ago, "stress": 3, "seen_ticks": 5000, "victims": ["Medtob"], **kw}


def empty_cell(uid, locked=True, **kw):
    return {"unit_id": uid, "locked": locked or None, "pile": 701, "drink": 0, "food": 0, "pile_empty": True,
            "fort_meals": 40, **kw}


def run(s, memory=None):
    props, notes = [], []
    PK._killer_rule(s, cfg, props, notes, memory)
    cells = [p for p in props if p.rule == "killer" and p.action.get("type") == "killer_cell"]
    return cells, notes


@test("brain: E's Dentconstruct (a werebeast, people 2, locked, the pile empty): no larder wait, said locked at once")
def _():
    m = Memory()
    row = krow(DENT, "Dentconstruct", kind="werebeast", conf="certain", people=2, ago=2000)
    s = state([row], cells=[empty_cell(DENT)])
    cells, notes = run(s, m)
    assert all("waits for" not in p.reason for p in cells), [p.reason for p in cells]
    assert any("Dentconstruct carries a werebeast curse: locked in the AI's cell at once" in n for n in notes), notes
    # not locked yet (out of the cell): the action runs, urgent passed, no word of the pile
    s = state([row], cells=[empty_cell(DENT, locked=False)])
    cells, notes = run(s, m)
    assert cells and cells[0].action.get("urgent") == [DENT], [p.action for p in cells]
    assert "waits for" not in cells[0].reason, cells[0].reason


@test("brain: a killing within the last day, a tantrum, or a transformed cell row: urgent; a calm one waits as before")
def _():
    # killed 600 ticks ago (half a day): urgent
    s = state([krow(40, "Fresh", ago=600)], cells=[empty_cell(40)])
    cells, notes = run(s, Memory())
    assert not cells and any("Fresh killed within the last day" in n for n in notes), (cells, notes)
    # in a tantrum now (the tantrum ledger)
    t = {"id": 41, "name": "Raging", "year": 1, "stress": "unhappy", "now": True, "ticks": [], "unmet": [], "posts": []}
    s = state([krow(41, "Raging")], cells=[empty_cell(41)], tantrums=[t])
    cells, notes = run(s, Memory())
    assert not cells and any("Raging is in a tantrum" in n for n in notes), (cells, notes)
    # the bridge's own reading of the cell (transformed)
    s = state([krow(42, "Changed")], cells=[empty_cell(42, urgent="transformed")])
    cells, notes = run(s, Memory())
    assert not cells and any("Changed is transformed" in n for n in notes), (cells, notes)
    # calm, the killing days ago: the larder wait as before
    s = state([krow(43, "Calm", ago=5 * DAY)], cells=[empty_cell(43)])
    cells, notes = run(s, Memory())
    assert cells and "the cell's pile waits for drink and meals" in cells[0].reason, cells
    assert "urgent" not in cells[0].action, cells[0].action


@test("brain: a vampire in a cell is never 'urgent' (it neither eats nor drinks)")
def _():
    s = state([krow(44, "Vamp", kind="vampire", conf="certain", ago=100)], cells=[empty_cell(44)])
    s["settings"] = {"rules": {"expel_vampires": False}}
    _, notes = run(s, Memory())
    assert not any("at once" in n for n in notes), notes


@test("bridge catalog: killer_cell passes urgent on to the cell")
def _():
    cat = (ROOT / "lua" / "ai-bridge-catalog.lua").read_text(encoding="utf-8")
    body = re.search(r"killer_cell = function\(a\).*?\n    end,", cat, re.S).group(0)
    assert "urgent = urgent" in body and "a.urgent" in body, body


@test("ai-killers: urgent_now keeps the haulers' doors shut and the let-outs at the last resort")
def _():
    chk = re.search(r"\nlocal function larder_check\(.*?\nend\n", SRC, re.S).group(0)
    assert "urgent_now(c, u, t)" in chk
    lo = re.search(r"\nlocal function let_out\(.*?\nend\n", SRC, re.S).group(0)
    assert "if urgent_now(c, u, t) then tl, hl = THIRST_LAST, HUNGER_LAST end" in lo


@test("ai-killers files stay under 60,000 bytes without CR")
def _():
    for f in ("ai-killers.lua", "ai-killers-cell.lua", "ai-bridge-catalog.lua"):
        n = len((ROOT / "lua" / f).read_bytes().replace(b"\r", b""))
        assert n < 60000, (f, n)


# --- the bridge (lupa) -------------------------------------------------------------

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


def cell(lua, env, ids, urgent=None):
    o = {"units": ids}
    if urgent is not None:
        o["urgent"] = urgent
    return py(env.cell(T(lua, o), False))


def locked_in(lua, env, w, **unit):
    u = w.unit(T(lua, {"id": 3, "name": "Dent", "citizen": True, "pos": {"x": 10, "y": 10, "z": 100}, **unit}))
    z = T(lua, {"id": 500, "x1": 20, "y1": 20, "x2": 22, "y2": 22, "z": 100, "assigned_unit_id": -1})
    w.bedrooms[1] = z
    d = w.door(T(lua, {"id": 600, "x": 23, "y": 21, "z": 100}))
    w.bed(20, 20, 100)
    cell(lua, env, [3])                              # placed
    u.pos.x, u.pos.y = 21, 21
    cell(lua, env, [3])                              # the pile made, locked
    return u, d


@test("lua: the brain's urgent one: the empty pile's doors stay shut; calm again, they open for the haulers")
def _():
    need_lua()
    lua, env, w = world()
    u, d = locked_in(lua, env, w)
    assert d.door_flags.forbidden is True
    r = cell(lua, env, [3], urgent=[3])
    assert d.door_flags.forbidden is True and r["urgent"][0]["why"] == "brain", r
    r = cell(lua, env, [3])                          # no longer urgent: the larder as before
    assert r["stocking"] == ["Dent"] and d.door_flags.forbidden is False, r


@test("lua: open for the haulers when he turns: shut and locked at once; the brain's word lasts a day")
def _():
    need_lua()
    lua, env, w = world()
    u, d = locked_in(lua, env, w)
    cell(lua, env, [3])                              # opened for the haulers
    assert d.door_flags.forbidden is False
    u.race, u.enemy.normal_race = 1301, 1            # in were form now
    r = cell(lua, env, [3])
    assert r["locked"] == ["Dent"] and d.door_flags.forbidden is True, r
    assert py(env.report())["cells"][0]["urgent"] == "transformed"
    u.race, u.enemy.normal_race = 1, -1
    advance(env, 3 * DAY)                            # past the gap
    cell(lua, env, [3], urgent=[3])
    assert d.door_flags.forbidden is True
    env.report()                                     # (the report's let-outs keep the brain's word)
    assert d.door_flags.forbidden is True


@test("lua: not calm, the pile empty: let out only at the last-resort thirst (45000), not at 20000")
def _():
    need_lua()
    lua, env, w = world()
    u, d = locked_in(lua, env, w)
    cell(lua, env, [3], urgent=[3])
    u.counters2.thirst_timer = 21000
    r = cell(lua, env, [3], urgent=[3])
    assert not r.get("out") and d.door_flags.forbidden is True, r
    u.counters2.thirst_timer = 46000
    r = cell(lua, env, [3], urgent=[3])
    assert r["out"] == ["Dent"], r


if __name__ == "__main__":
    finish()
