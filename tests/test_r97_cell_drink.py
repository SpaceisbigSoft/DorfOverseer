"""(0.105.97) A killer's cell keeps them fed and watered inside it, so they are
not let out every day.

Live 23 Nov, B (the Monastery, no jail zone): the cells were the killers' own
free bedrooms, with no drink or food, so each killer was let out whenever
thirst passed 20000, walked through the fort and was taken back once fed; the
killers were "waiting" (out) almost every cycle of the hour, and Degël killed
again inside hospital zone 333 while out. Now lua/ai-killers.lua makes a pile
inside the cell (drink and prepared meals only, linked to nothing), opens the
locked doors for the haulers while it runs low, lets a killer out only at
THIRST_LAST / HUNGER_LAST while it holds drink / meals, and says the pile and
the let-outs in the report's cell rows; brain/planner_killers.py says when the
cell's pile waits for drink and keeps the cell action running.

The Lua tests need lupa (they skip without it); the rest run anywhere.

    python tests/test_r97_cell_drink.py
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
ITEM3 = (ROOT / "tests" / "test_item3_killers.py").read_text(encoding="utf-8")
DAY = 1200

# the item3 fake fort (units, doors, zones, burrows, the save), with the map,
# stockpiles, items and the builder's quickfort added for the cell's pile
FAKE = re.search(r'FAKE = r"""(.*?)"""', ITEM3, re.S).group(1)

EXTRA = r"""
local env, W = ...
W.piles, W.beds, W.contents, W.commands, W.qf = {}, {}, {}, {}, {}
W.import_ok = true
local df, dfhack = env.df, env.dfhack
env.CR_OK = 0
df.building_type.Stockpile = 'Stockpile'
df.building_type.Bed = 'Bed'
df.tiletype = {attrs = {[1] = {shape = 'FLOOR'}, [2] = {shape = 'WALL'}}}
df.tiletype_shape = {FLOOR = 'FLOOR'}
df.item_type = {[1] = 'DRINK', [2] = 'FOOD', [3] = 'BARREL', [4] = 'MEAT'}
local function in_box(b, x, y, z)
    return b.z == z and x >= b.x1 and x <= b.x2 and y >= b.y1 and y <= b.y2
end
dfhack.maps = {getTileType = function(x, y, z) if W.walls and W.walls[x .. ',' .. y] then return 2 end return 1 end,
               getTileFlags = function(x, y, z)
                   for _, p in ipairs(W.piles) do if in_box(p, x, y, z) then return {pile = true}, {} end end
                   return {pile = false}, {}
               end}
local old_find = dfhack.buildings.findAtTile
dfhack.buildings.findAtTile = function(p)
    local d = old_find(p)
    if d then return d end
    for _, b in ipairs(W.beds) do if b.x == p.x and b.y == p.y and b.z == p.z then return b end end
    for _, b in ipairs(W.piles) do if in_box(b, p.x, p.y, p.z) then return b end end
end
dfhack.buildings.getStockpileContents = function(sp) return W.contents[sp.id] or {} end
dfhack.buildings.deconstruct = function(sp)
    for i, b in ipairs(W.piles) do if b == sp then table.remove(W.piles, i) end end
    sp.gone = true
end
dfhack.items = {getContainedItems = function(it) return it.contained or {} end}
dfhack.run_command_silent = function(...)
    local args = {...}
    table.insert(W.commands, table.concat(args, ' '))
    if not W.import_ok then return 'no such preset', 1 end
    local id = tonumber(args[#args])
    for _, b in ipairs(W.piles) do
        if b.id == id then
            if args[3] == 'library/booze' then
                b.settings.food = {prepared_meals = false, drink_plant = {true}, drink_animal = {true},
                                   meat = {false}, plants = {false}, seeds = {false}}
            elseif args[3] == 'library/preparedmeals' then
                b.settings.food.prepared_meals = true
            end
        end
    end
    return '', 0
end
local old_bfind = df.building.find
df.building.find = function(id)
    for _, b in ipairs(W.piles) do if b.id == id then return b end end
    return old_bfind(id)
end
function W.bed(x, y, z)
    local b = {x = x, y = y, z = z, getType = function() return 'Bed' end}
    table.insert(W.beds, b)
    return b
end
function W.item(kind, n, contained)
    return {getType = function() return kind end, stack_size = n or 1, flags = {forbid = false}, contained = contained}
end
local builder = {qf_try = function(mode, cells, z, x, y, dry)
    local w, h = cells[1].text:match('f%((%d+)x(%d+)%)')
    w, h = tonumber(w), tonumber(h)
    table.insert(W.qf, {mode = mode, x = x, y = y, z = z, w = w, h = h, text = cells[1].text})
    if dry or W.qf_refuse then return not W.qf_refuse end
    local b = {id = 700 + #W.qf, x1 = x, y1 = y, x2 = x + w - 1, y2 = y + h - 1, z = z, name = '',
               settings = {flags = {food = true}, food = {}}, storage = {max_barrels = 0, max_bins = 5},
               getType = function() return 'Stockpile' end}
    table.insert(W.piles, b)
    return true
end}
local old_req = env.reqscript
env.reqscript = function(name)
    if name == 'ai-builder' then return builder end
    return old_req(name)
end
"""


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


def cell(lua, env, ids, dry=False, release_only=False):
    return py(env.cell(T(lua, {"units": ids, "release_only": release_only}), dry))


def bedroom_fort(lua, w):
    """B's case: no jail zone, the killer's cell a free 3x3 bedroom (x20-22,
    y20-22) with its bed at x20 y20 and its door east of it (x23 y21)."""
    u = w.unit(T(lua, {"id": 3, "name": "Degel", "citizen": True, "pos": {"x": 10, "y": 10, "z": 100}}))
    z = T(lua, {"id": 500, "x1": 20, "y1": 20, "x2": 22, "y2": 22, "z": 100, "assigned_unit_id": -1})
    w.bedrooms[1] = z
    d = w.door(T(lua, {"id": 600, "x": 23, "y": 21, "z": 100}))
    w.bed(20, 20, 100)
    return u, z, d


def locked_in(lua, env, w):
    """The killer placed, inside and locked, the pile made (empty)."""
    u, z, d = bedroom_fort(lua, w)
    cell(lua, env, [3])                              # placed
    u.pos.x, u.pos.y = 21, 21
    cell(lua, env, [3])                              # the pile made, locked
    return u, z, d


def stock(lua, w, drink=0, food=0):
    """A barrel of drink (its drink inside it) and meals left in the pile."""
    sp = w.piles[1]
    items = []
    if drink:
        items.append(w.item(3, 1, T(lua, [w.item(1, drink)])))
    if food:
        items.append(w.item(2, food))
    w.contents[sp.id] = T(lua, items)


# --- 1. the source (no Lua needed) ------------------------------------------------

@test("ai-killers: the last-resort levels (45000 / 70000) beside the old ones; let_out reads the cell's pile")
def _():
    m = re.search(r"THIRST_LAST, HUNGER_LAST = (\d+), (\d+)", SRC)
    assert m and (int(m.group(1)), int(m.group(2))) == (45000, 70000), m
    m = re.search(r"THIRST_OUT, HUNGER_OUT = (\d+), (\d+)", SRC)
    assert m and (int(m.group(1)), int(m.group(2))) == (20000, 40000), m
    body = re.search(r"local function let_out\(.*?\nend\n", SRC, re.S).group(0)
    assert "out_levels(c, memo)" in body and "c.let_outs" in body, body
    # (0.105.94) the way back is unchanged: under the old levels
    assert re.search(r"if c\.out and \(th >= THIRST_OUT or hu >= HUNGER_OUT\) then", SRC)


@test("ai-killers: the pile takes drink and prepared meals only (DFHack's presets, then by hand), never linked")
def _():
    assert "'stockpiles', 'import', 'library/booze', '-s', id" in SRC
    assert "'library/preparedmeals', '-m', 'enable', '-s', id" in SRC
    assert "f.prepared_meals = true" in SRC
    assert "links" not in re.search(r"function larder_make\(.*?\nend\n", SRC, re.S).group(0)
    assert "pcall(larder_remove, c)" in re.search(r"local function free\(.*?\nend\n", SRC, re.S).group(0)


@test("ai-killers.lua stays under 60 KB")
def _():
    assert len(SRC.encode("utf-8")) < 60 * 1024, len(SRC.encode("utf-8"))


@test("ai-killers.lua compiles under Lua 5.3")
def _():
    need_lua()
    f = LuaRuntime().eval("function(s) local f, e = load(s, 'b', 't', {}) return e end")
    assert f(SRC) is None, f(SRC)


# --- 2. the cell's pile (Lua) -------------------------------------------------------

@test("cell: a pile is made inside the cell room (never the bed's tile nor beside the door), drink and meals only")
def _():
    need_lua()
    lua, env, w = world()
    u, z, d = bedroom_fort(lua, w)
    r = cell(lua, env, [3])
    assert r["placed"] == ["Degel"] and len(w.piles) == 0, r      # the pile comes once the cell stands
    r = cell(lua, env, [3])
    assert len(w.piles) == 1, (r, py(w.qf))
    sp = w.piles[1]
    assert (sp.x1, sp.y1, sp.x2, sp.y2) == (21, 20, 21, 21), py(w.qf)  # 1x2, away from the bed and the door
    assert sp.name == "AI cell larder 3" and sp.storage.max_barrels == 2 and sp.storage.max_bins == 0
    cmds = py(w.commands)
    assert cmds == [f"stockpiles import library/booze -s {sp.id}",
                    f"stockpiles import library/preparedmeals -m enable -s {sp.id}"], cmds
    assert sp.settings.food.prepared_meals is True
    st = py(w.site["ai-overseer/killers"])["cells"]["3"]
    assert st["pile"] == sp.id and "pile_all_food" not in st, st
    r = cell(lua, env, [3])
    assert len(w.piles) == 1 and len(py(w.qf)) == 1, r              # kept, not made again
    rep = py(env.report())
    c = rep["cells"][0]
    assert c["pile"] == sp.id and c["drink"] == 0 and c["food"] == 0 and c["pile_empty"] is True, c
    assert c["let_outs"] == 0


@test("cell: a dry run makes no pile; a room with no free floor says so; the settings not taken are said")
def _():
    need_lua()
    lua, env, w = world()
    u, z, d = bedroom_fort(lua, w)
    cell(lua, env, [3])
    cell(lua, env, [3], dry=True)
    assert len(w.piles) == 0 and len(py(w.qf)) == 0
    w.walls = T(lua, {f"{x},{y}": True for x in (20, 21, 22) for y in (20, 21, 22)})
    cell(lua, env, [3])
    rep = py(env.report())
    assert rep["cells"][0]["pile"] is False and "no free floor" in rep["cells"][0]["pile_error"], rep["cells"]
    w.walls = None
    w.import_ok = False
    cell(lua, env, [3])
    assert len(w.piles) == 1
    c = py(env.report())["cells"][0]
    assert c["pile_all_food"] is True and "pile_error" not in c, c


@test("cell: a locked cell with an empty pile opens for the haulers (the killer kept in the burrow), locks once stocked")
def _():
    need_lua()
    lua, env, w = world()
    u, z, d = locked_in(lua, env, w)
    b = w.burrows[1]
    assert d.door_flags.forbidden is True and len(w.piles) == 1
    r = cell(lua, env, [3])                                         # the pile is empty: the doors open
    assert r["stocking"] == ["Degel"] and d.door_flags.forbidden is False and b.units[3] is True, r
    advance(env, DAY)
    r = cell(lua, env, [3])
    assert r["stocking"] == ["Degel"] and d.door_flags.forbidden is False, r   # still waiting for the haulers
    rep = py(env.report())
    assert rep["cells"][0]["stocking"] is True and "locked" not in rep["cells"][0], rep["cells"]
    stock(lua, w, drink=20, food=3)
    r = cell(lua, env, [3])
    assert r["locked"] == ["Degel"] and d.door_flags.forbidden is True, r
    c = py(env.report())["cells"][0]
    assert c["drink"] == 20 and c["food"] == 3 and "pile_empty" not in c and "stocking" not in c, c
    assert cell(lua, env, [3])["rejected"] is True                  # stocked and locked: as it should be


@test("cell: the doors lock again when the haulers don't come in time, and stay locked for the gap after")
def _():
    need_lua()
    lua, env, w = world()
    u, z, d = locked_in(lua, env, w)
    cell(lua, env, [3])                                             # opened
    assert d.door_flags.forbidden is False
    advance(env, 2 * DAY)
    r = cell(lua, env, [3])
    assert r["locked"] == ["Degel"] and d.door_flags.forbidden is True, r
    advance(env, DAY)
    r = cell(lua, env, [3])
    assert r["stocking"] == ["Degel"] and d.door_flags.forbidden is True and r["ok"] is True, r   # in the gap
    advance(env, 2 * DAY)
    r = cell(lua, env, [3])
    assert r["stocking"] == ["Degel"] and d.door_flags.forbidden is False, r   # the gap over: opened again


@test("let-out: with drink in the pile not before thirst 45000 (meals: hunger 70000); counted in the cell row")
def _():
    need_lua()
    lua, env, w = world()
    u, z, d = locked_in(lua, env, w)
    for v in (20, 21):                               # two killings: on the report's list
        w.unit(T(lua, {"id": v, "name": f"Victim {v}", "is_dead": True}))
        w.incidents[len(w.incidents) + 1] = T(lua, {"criminal": 3, "victim": v, "death_cause": 7,
                                                    "conflict_level": 6, "event_year": 300, "event_time": 0})
    stock(lua, w, drink=10, food=2)
    b = w.burrows[1]
    u.counters2.thirst_timer = 30000
    u.counters2.hunger_timer = 50000
    rep = py(env.report())
    assert d.door_flags.forbidden is True and b.units[3] is True and rep["cells"][0]["locked"] is True, rep
    assert cell(lua, env, [3])["rejected"] is True
    u.counters2.thirst_timer = 46000
    rep = py(env.report())
    assert d.door_flags.forbidden is False and b.units[3] is None, rep           # the last resort
    assert rep["cells"][0]["out"] is True and rep["cells"][0]["let_outs"] == 1, rep["cells"]
    u.counters2.thirst_timer, u.counters2.hunger_timer = 100, 100
    cell(lua, env, [3])                                                          # back
    cell(lua, env, [3])                                                          # locked
    assert d.door_flags.forbidden is True
    u.counters2.hunger_timer = 71000
    r = cell(lua, env, [3])
    assert r["out"] == ["Degel"], r
    rows = py(env.report())
    assert rows["cells"][0]["let_outs"] == 2 and rows["list"][0]["cell"]["let_outs"] == 2, rows


@test("let-out: with no drink in the pile the old level stays (thirst 20000)")
def _():
    need_lua()
    lua, env, w = world()
    u, z, d = locked_in(lua, env, w)
    stock(lua, w, drink=0, food=4)                   # meals but no drink
    u.counters2.thirst_timer = 21000
    r = cell(lua, env, [3])
    assert r["out"] == ["Degel"] and d.door_flags.forbidden is False, r


@test("release: the cell's pile goes with the cell (its items stay)")
def _():
    need_lua()
    lua, env, w = world()
    u, z, d = locked_in(lua, env, w)
    sp = w.piles[1]
    r = cell(lua, env, [])
    assert r["released"] == ["Degel"] and len(w.piles) == 0 and sp.gone is True, r


# --- 3. the brain -------------------------------------------------------------------

def run(killers):
    s = {"killers": killers}
    props, notes = [], []
    PK._killer_rule(s, dict(PLANNER_CONFIG), props, notes, None)
    return props, notes


def row(**kw):
    r = {"id": 3, "name": "Degel", "kind": "killer", "confidence": "strong", "citizen": True, "kills": 2,
         "victims": ["A", "B"], "seen_ticks": 2000}
    r.update(kw)
    return r


@test("brain: a locked cell whose pile holds no drink keeps the cell action running, the reason says so")
def _():
    c = {"locked": True, "pile": 701, "drink": 0, "food": 0, "pile_empty": True, "let_outs": 3}
    p, n = run({"list": [row(cell=c)], "cells": [dict(c, unit_id=3)], "rooms": 0})
    assert [x.action for x in p] == [{"type": "killer_cell", "units": [3]}], p
    assert "the cell's pile waits for drink" in p[0].reason, p[0].reason
    assert "locked in a cell by the AI" in n[0] and "the cell's pile is empty" in n[0] and "let out 3 time(s)" in n[0], n


@test("brain: a pile not made yet is proposed for; one that can't be made is said, not proposed for")
def _():
    c = {"locked": True, "pile": False, "let_outs": 0}
    p, n = run({"list": [row(cell=c)], "cells": [dict(c, unit_id=3)], "rooms": 1})
    assert len(p) == 1 and "waits for drink" in p[0].reason and "waits to be made" in n[0], (p, n)
    c = {"locked": True, "pile": False, "pile_error": "no free floor in the cell for a pile"}
    p, n = run({"list": [row(cell=c)], "cells": [dict(c, unit_id=3)], "rooms": 1})
    assert p == [] and "no free floor" in n[0], (p, n)


@test("brain: a stocked locked cell is said with what it holds, not proposed; the old rows (no pile) as before")
def _():
    c = {"locked": True, "pile": 701, "drink": 15, "food": 2, "let_outs": 0}
    p, n = run({"list": [row(cell=c)], "cells": [dict(c, unit_id=3)], "rooms": 0})
    assert p == [] and "holds 15 drink and 2 meal(s)" in n[0] and "let out" not in n[0].split("then back")[1], n
    p, n = run({"list": [row(cell={"locked": True})], "cells": [{"unit_id": 3, "locked": True}], "rooms": 0})
    assert p == [] and "locked in a cell by the AI" in n[0] and "pile" not in n[0], (p, n)


@test("brain: a cell open for the haulers is said and stays proposed (not locked), with the pile's words")
def _():
    c = {"stocking": True, "pile": 701, "drink": 0, "food": 0, "pile_empty": True}
    p, n = run({"list": [row(cell=c)], "cells": [dict(c, unit_id=3)], "rooms": 0})
    assert len(p) == 1 and "lock them in a cell" in p[0].reason and "waits for drink" in p[0].reason, p
    assert "open for the haulers" in n[0], n


finish()
