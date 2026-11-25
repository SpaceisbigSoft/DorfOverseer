"""(item 5) The killer cell's pile gets meals, and a killer is let out hungry
only when no meal can reach it.

Live B, 24 Nov 16:46: the killers report's cell for Ducim (three killings
that day) read {"drink":3,"food":0,"out":true,"pile_all_food":true,...}: the
pile held drink and no meal while the fort cooks ~110 meals a day, and he was
out (let out at hunger 40000, HUNGER_OUT, as the pile held no meal) and
killed. The causes, in lua/ai-killers.lua:
  * larder_low was `return drink <= 0`: the doors opened for the haulers only
    while the pile held no drink and shut once a drink came in, so meals
    never got in (the brain's _pile_waits watched drink only too);
  * larder_settings wrote booleans into DF's food lists, which read as 0/1
    numbers (a boolean written to a number errors in DFHack, in a pcall):
    no write took and the row said pile_all_food;
  * a 1x2 pile was made with 2 barrels allowed: 2 drink barrels leave the
    meals no tile.
Now the doors open while the pile holds no drink OR no meal while the fort
has free meals (never while the killer rages), the switches are written in
the type they read, barrels are tiles - 1, and a killer whose pile has no
meal is let out at HUNGER_OUT only when no meal can reach it (the fort has
none free, or none came MEAL_WAIT after the doors opened for the haulers);
else at HUNGER_LAST, the last resort.

The Lua cases need lupa (they skip without it) or texlua (each case returns
"ok"; see lua_cases()); the rest run anywhere.

    python tests/test_item5_cell_meals.py
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
import planner_killers as PK  # noqa: E402
from planner import PLANNER_CONFIG  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

SRC = (ROOT / "lua" / "ai-killers.lua").read_text(encoding="utf-8")
ITEM3 = (ROOT / "tests" / "test_item3_killers.py").read_text(encoding="utf-8")
R97 = (ROOT / "tests" / "test_r97_cell_drink.py").read_text(encoding="utf-8")
FAKE = re.search(r'FAKE = r"""(.*?)"""', ITEM3, re.S).group(1)
EXTRA = re.search(r'EXTRA = r"""(.*?)"""', R97, re.S).group(1)

# helpers for the cases: B's bedroom cell (3x3 at x20-22 y20-22, bed x20 y20,
# door x23 y21), the killer locked in with the pile made
HELP = r"""
local env, W = ...
local df = env.df
df.global.world.items = {other = {FOOD = {}}}
df.soldier_mood_type = {[1] = 'Tantrum'}
function W.fort()
    local u = W.unit({id = 3, name = 'Degel', citizen = true, pos = {x = 10, y = 10, z = 100}})
    W.bedrooms[1] = {id = 500, x1 = 20, y1 = 20, x2 = 22, y2 = 22, z = 100, assigned_unit_id = -1}
    local d = W.door({id = 600, x = 23, y = 21, z = 100})
    W.bed(20, 20, 100)
    env.cell({units = {3}}, false)
    u.pos.x, u.pos.y = 21, 21
    env.cell({units = {3}}, false)
    assert(#W.piles == 1 and d.door_flags.forbidden == true, 'not locked in')
    return u, d
end
function W.stock(drink, food)
    local items = {}
    if drink > 0 then table.insert(items, W.item(3, 1, {W.item(1, drink)})) end
    if food > 0 then table.insert(items, W.item(2, food)) end
    W.contents[W.piles[1].id] = items
end
function W.meals(n)                       -- the fort's free meals, elsewhere
    local l = df.global.world.items.other.FOOD
    for i = #l, 1, -1 do l[i] = nil end
    for i = 1, n do l[i] = W.item(2, 1) end
end
function W.adv(t) df.global.cur_year_tick = df.global.cur_year_tick + t end
function W.st() return W.site['ai-overseer/killers'].cells['3'] end
function W.row() return env.report().cells[1] end
function W.has(l, name) for _, v in ipairs(l or {}) do if v == name then return true end end return false end
"""

CASES = {
    # 1. the doors open for meals (the fort has some), the killer kept in the burrow; locked once a meal is in
    "meals_open": r"""
local env, W = ...
local u, d = W.fort()
local b = W.burrows[1]
W.stock(5, 0)
W.meals(0)
local r = env.cell({units = {3}}, false)
assert(r.rejected == true and d.door_flags.forbidden == true, 'no meals in the fort: nothing to open for')
W.meals(4)
r = env.cell({units = {3}}, false)
assert(W.has(r.stocking, 'Degel') and d.door_flags.forbidden == false and b.units[3] == true, 'opened for meals')
local row = W.row()
assert(row.stocking == true and row.fort_meals == 4 and row.meals_out == nil, 'row while open')
W.adv(600)
r = env.cell({units = {3}}, false)
assert(W.has(r.stocking, 'Degel') and d.door_flags.forbidden == false, 'still open: no meal yet')
W.stock(5, 2)
r = env.cell({units = {3}}, false)
assert(W.has(r.locked, 'Degel') and d.door_flags.forbidden == true, 'locked once a meal is in')
row = W.row()
assert(row.fort_meals == nil and W.st().meal_none == nil and W.st().meal_open == nil, 'clock cleared')
return 'ok'
""",
    # 2. never opened for meals while the killer rages
    "meals_raging": r"""
local env, W = ...
local u, d = W.fort()
W.stock(5, 0)
W.meals(4)
u.counters = {soldier_mood = 1}
local r = env.cell({units = {3}}, false)
assert(W.has(r.stocking, 'Degel') and d.door_flags.forbidden == true, 'kept locked in a tantrum')
return 'ok'
""",
    # 3. hungry with no meal in the pile: the last resort while one may still come;
    #    HUNGER_OUT once none came MEAL_WAIT after the doors opened, or none in the fort
    "meals_let_out": r"""
local env, W = ...
local u, d = W.fort()
W.stock(5, 0)
W.meals(4)
env.cell({units = {3}}, false)                  -- opened for the haulers
assert(d.door_flags.forbidden == false and W.st().meal_open ~= nil, 'opened, the clock started')
u.counters2.hunger_timer = 45000
W.adv(1000)
local r = env.cell({units = {3}}, false)
assert(not W.has(r.out, 'Degel'), 'not let out: a meal may still come')
W.adv(1400)                                     -- the doors' time up (RESTOCK_TICKS)
r = env.cell({units = {3}}, false)
assert(W.has(r.locked, 'Degel') and d.door_flags.forbidden == true, 'locked again')
r = env.cell({units = {3}}, false)
assert(W.has(r.out, 'Degel'), 'let out: no meal came in MEAL_WAIT')
local row = W.row()
assert(row.meals_out == true and row.out == true and row.let_outs == 1, 'let out: no meal came')
return 'ok'
""",
    "meals_none_in_fort": r"""
local env, W = ...
local u, d = W.fort()
W.stock(5, 0)
W.meals(0)
u.counters2.hunger_timer = 41000
local r = env.cell({units = {3}}, false)
assert(W.has(r.out, 'Degel'), 'no meals in the fort: the old level')
return 'ok'
""",
    "meals_in_pile": r"""
local env, W = ...
local u, d = W.fort()
W.stock(5, 3)
W.meals(4)
u.counters2.hunger_timer = 69000
local r = env.cell({units = {3}}, false)
assert(r.rejected == true and d.door_flags.forbidden == true, 'meals in the pile: kept in')
u.counters2.hunger_timer = 71000
r = env.cell({units = {3}}, false)
assert(W.has(r.out, 'Degel'), 'the last resort (70000)')
return 'ok'
""",
    # 4. DF's switches read as 0/1 and refuse booleans: written as numbers, read right
    "switches_numbers": r"""
local env, W = ...
local vec = W.vec
W.vec = function(n, val)
    local v = vec(n, val and 1 or 0)
    local mt = getmetatable(v)
    local put = mt.__newindex
    mt.__newindex = function(t, i, x)
        if type(x) ~= 'number' then error('number expected') end
        put(t, i, x)
    end
    return v
end
local new = W.new_settings
W.new_settings = function(n) local s = new(n); s.food.prepared_meals = 1; return s end
local u, d = W.fort()
local sp = W.piles[1]
local f = sp.settings.food
assert(f.drink_plant[0] == 1 and f.drink_animal[2] == 1 and f.meat[0] == 0 and f.seeds[2] == 0, 'lists')
assert(f.prepared_meals == 1, 'prepared meals')
assert(env.larder_reads_right(sp) == true, 'reads right')
local row = W.row()
assert(row.pile_all_food == nil and row.pile_fixed == nil, 'no pile_all_food')
f.meat[1] = 1
W.adv(1300)
row = W.row()
assert(f.meat[1] == 0 and row.pile_fixed == 1, 'put right again, as numbers')
return 'ok'
""",
    # 5. barrels: tiles - 1, an old pile's put right each cycle
    "barrels": r"""
local env, W = ...
local u, d = W.fort()
local sp = W.piles[1]
assert(sp.x2 - sp.x1 + sp.y2 - sp.y1 == 1 and sp.storage.max_barrels == 1, 'a 1x2 pile: 1 barrel')
sp.storage.max_barrels = 2                      -- as B's were made
env.report()
assert(sp.storage.max_barrels == 1, 'put right by the report')
sp.storage.max_barrels = 2
env.cell({units = {3}}, false)
assert(sp.storage.max_barrels == 1, 'and by the cell action')
sp.x2 = sp.x1; sp.y2 = sp.y1
assert(env.larder_barrels(sp) == 1, 'a 1-tile pile keeps 1')
return 'ok'
""",
}


def lua_cases() -> dict:
    """The cases as {name: (FAKE, module source, EXTRA, HELP, case)}, for a
    runner without lupa (texlua): load(FAKE)(src) gives env, W; then EXTRA,
    HELP and the case each run with env, W; the case returns "ok"."""
    src = module_src("ai-killers.lua")
    return {k: (FAKE, src, EXTRA, HELP, v) for k, v in CASES.items()}


def run_case(name):
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-killers.lua"))
    lua.execute(EXTRA, env, w)
    lua.execute(HELP, env, w)
    r = lua.execute(CASES[name], env, w)
    assert r == "ok", r


# --- 1. the source (no Lua needed) ------------------------------------------------

@test("ai-killers: the pile runs low with no drink, or no meal while the fort has free ones")
def _():
    low = re.search(r"\nlocal function larder_low\(.*?\nend\n", SRC, re.S).group(0)
    assert "drink <= 0 or (food <= 0 and fort_meals(memo) > 0)" in low, low
    rs = re.search(r"\nlocal function restocking\(.*?\nend\n", SRC, re.S).group(0)
    assert "not raging(u) and not urgent_now(c, u, t) and larder_low(c, memo)" in rs   # shut when the killer rages
    chk = re.search(r"\nlocal function larder_check\(.*?\nend\n", SRC, re.S).group(0)
    assert "if raging(u) or urgent_now(c, u, t) then return 'wait' end" in chk


@test("ai-killers: the switches written in the type they read (DF's 0/1)")
def _():
    st = re.search(r"\nfunction larder_settings\(.*?\nend\n", SRC, re.S).group(0)
    assert "pcall(larder_put, v, i, want)" in st and "pcall(larder_put, f, 'prepared_meals', true)" in st
    put = re.search(r"\nlocal function larder_put\(.*?\nend\n", SRC, re.S).group(0)
    assert "want and 1 or 0" in put
    assert "not larder_on(f.prepared_meals)" in SRC


@test("ai-killers: hungry let out at HUNGER_OUT only when no meal can reach the pile")
def _():
    ol = re.search(r"\nfunction out_levels\(.*?\nend\n", SRC, re.S).group(0)
    assert "food > 0 or not meals_unreachable(c, t, memo)" in ol and "HUNGER_LAST" in ol
    assert "out_levels(c, memo, t)" in re.search(r"local function let_out\(.*?\nend\n", SRC, re.S).group(0)
    assert re.search(r"^MEAL_WAIT = 2 \* DAY", SRC, re.M)


@test("ai-killers.lua stays under 60 KB; no local copies of ai-util helpers added")
def _():
    assert len(SRC.encode("utf-8")) < 60 * 1024, len(SRC.encode("utf-8"))
    assert "local function item_free" not in SRC and "U.item_free(it)" in SRC


# --- 2. the cell (Lua) --------------------------------------------------------------

for _name in CASES:
    test(f"lua case: {_name}")(lambda n=_name: run_case(n))


# --- 3. the brain -------------------------------------------------------------------

def run(killers):
    s = {"killers": killers}
    props, notes = [], []
    PK._killer_rule(s, dict(PLANNER_CONFIG), props, notes, None)
    return props, notes


def row(**kw):
    r = {"id": 3, "name": "Ducim", "kind": "killer", "confidence": "strong", "citizen": True, "kills": 3,
         "victims": ["A", "B", "C"], "seen_ticks": 2000}
    r.update(kw)
    return r


@test("brain: a locked cell whose pile holds drink but no meal (the fort has meals) keeps the cell action running")
def _():
    c = {"locked": True, "pile": 1912, "drink": 3, "food": 0, "fort_meals": 20, "let_outs": 1}
    assert PK._pile_waits(c) is True
    p, n = run({"list": [row(id=17777, cell=c)], "cells": [dict(c, unit_id=17777)], "rooms": 0})
    assert [x.action for x in p] == [{"type": "killer_cell", "units": [17777]}], p
    assert "the cell's pile waits for meals" in p[0].reason, p[0].reason
    assert "it waits for meals (20+ free in the fort)" in n[0], n


@test("brain: no meals in the fort (or an older bridge without fort_meals): meals not waited for")
def _():
    for c in ({"locked": True, "pile": 1912, "drink": 3, "food": 0, "fort_meals": 0},
              {"locked": True, "pile": 1912, "drink": 3, "food": 0}):
        assert PK._pile_waits(c) is False, c
    c = {"locked": True, "pile": 1912, "drink": 0, "food": 0, "fort_meals": 5}
    assert PK._pile_waits(c) is True
    p, n = run({"list": [row(cell=c)], "cells": [dict(c, unit_id=3)], "rooms": 0})
    assert "the cell's pile waits for drink and meals" in p[0].reason, p[0].reason
    # inside the gap between two restockings: not asked
    assert PK._pile_waits(dict(c, restock_wait=True)) is False


@test("brain: a pile no meal reached is said (let out when hungry)")
def _():
    w = PK._larder_words({"pile": 1912, "drink": 3, "food": 0, "fort_meals": 20, "meals_out": True})
    assert "no meal has reached it: let out when hungry" in w, w
    w = PK._larder_words({"pile": 701, "drink": 5, "food": 1})
    assert w == "; the cell's pile holds 5 drink and 1 meal(s)", w


if __name__ == "__main__":
    finish()
