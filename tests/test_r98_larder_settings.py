"""(0.105.98) The killer cell's larder takes only drink and prepared meals,
and the cell keeps its pile by its name.

Live 23 Nov 22:11, B (DFHack 53.17-r1, a read-only probe): pile 1537 ("AI
cell larder 17161") had flags.food on and every food list fully on (meat
14800/14800, seeds, plants, globs...), prepared meals on; both cell rows said
pile_all_food. 0.105.97 ran DFHack's presets (`stockpiles import
library/booze`, `library/preparedmeals -m enable`) and wrote by hand only
when they didn't read right, once, at creation. Now lua/ai-killers.lua writes
the settings by hand (every food list off, drink_plant and drink_animal on,
prepared meals on, every other category off, bins 0) and reads them back, on
creation and each cycle (the report and the cell action) while they differ:
c.pile_fixed counts the corrections, pile_all_food only when the write
itself didn't take. The other cell's pile, 1538, was not found by id just
after the report gave it: the id kept is always the stockpile's own, and a
pile not found by it is looked for by its name ("AI cell larder <uid>").

The Lua tests need lupa (they skip without it); the rest run anywhere.

    python tests/test_r98_larder_settings.py
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

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

SRC = (ROOT / "lua" / "ai-killers.lua").read_text(encoding="utf-8")
ITEM3 = (ROOT / "tests" / "test_item3_killers.py").read_text(encoding="utf-8")
R97 = (ROOT / "tests" / "test_r97_cell_drink.py").read_text(encoding="utf-8")
DAY = 1200

# the item3 fake fort, with r97's map, stockpiles, items and quickfort
FAKE = re.search(r'FAKE = r"""(.*?)"""', ITEM3, re.S).group(1)
EXTRA = re.search(r'EXTRA = r"""(.*?)"""', R97, re.S).group(1)

FOOD_LISTS = ["meat", "fish", "unprepared_fish", "egg", "plants", "cheese_plant", "cheese_animal", "seeds",
              "leaves", "powder_plant", "powder_creature", "glob", "glob_paste", "glob_pressed", "liquid_plant",
              "liquid_animal", "liquid_misc"]
DRINK_LISTS = ["drink_plant", "drink_animal"]


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


def cell(lua, env, ids, dry=False):
    return py(env.cell(T(lua, {"units": ids}), dry))


def vec(lua, v):
    n = lua.eval("function(v) return #v end")(v)
    return [v[i] for i in range(n)]


def exact(lua, sp):
    """The pile reads drink and prepared meals only: (ok, what differs)."""
    f, fl = sp.settings.food, sp.settings.flags
    bad = []
    for k in FOOD_LISTS:
        if any(x is True for x in vec(lua, f[k])):
            bad.append(k)
    for k in DRINK_LISTS:
        xs = vec(lua, f[k])
        if not xs or not all(x is True for x in xs):
            bad.append(k)
    if f.prepared_meals is not True:
        bad.append("prepared_meals")
    for k in ("food", "animals", "furniture", "stone"):
        if fl[k] is not (k == "food"):
            bad.append("flags." + k)
    if sp.storage.max_bins != 0:
        bad.append("max_bins")
    return not bad, bad


def bedroom_fort(lua, w):
    """B's case: no jail zone, the cell a free 3x3 bedroom (x20-22, y20-22),
    its bed at x20 y20 and its door east of it (x23 y21)."""
    u = w.unit(T(lua, {"id": 3, "name": "Degel", "citizen": True, "pos": {"x": 10, "y": 10, "z": 100}}))
    z = T(lua, {"id": 500, "x1": 20, "y1": 20, "x2": 22, "y2": 22, "z": 100, "assigned_unit_id": -1})
    w.bedrooms[1] = z
    d = w.door(T(lua, {"id": 600, "x": 23, "y": 21, "z": 100}))
    w.bed(20, 20, 100)
    return u, z, d


def made(lua, env, w):
    u, z, d = bedroom_fort(lua, w)
    cell(lua, env, [3])                              # placed
    u.pos.x, u.pos.y = 21, 21
    cell(lua, env, [3])                              # the pile made, locked
    assert len(w.piles) == 1
    return u, w.piles[1]


def state_cell(w):
    return w.site["ai-overseer/killers"].cells["3"]


def all_on(lua, w, sp, n=3):
    """The pile as B's were: every food list on (0.105.97's pile)."""
    sp.settings = w.new_settings(n)


# --- 1. the source (no Lua needed) ------------------------------------------------

@test("ai-killers: no DFHack presets; the settings written by hand and read back, on creation and each cycle")
def _():
    assert "'stockpiles', 'import'" not in SRC and "run_command" not in SRC
    mk = re.search(r"\nfunction larder_make\(.*?\nend\n", SRC, re.S).group(0)
    assert "larder_settings(b)" in mk and "c.pile_name" in mk
    chk = re.search(r"\nlocal function larder_check\(.*?\nend\n", SRC, re.S).group(0)
    assert "larder_keep_right" in chk
    rep = re.search(r"\nfunction report\(\).*?\nend\n", SRC, re.S).group(0)
    assert "larder_keep_right(c, larder_pile(c), false)" in rep
    st = re.search(r"\nfunction larder_settings\(.*?\nend\n", SRC, re.S).group(0)
    assert "LARDER_DRINK[k] == true" in st and "(k == 'food')" in st and "max_bins = 0" in st
    assert "max_barrels" not in st                                  # kept as made
    row = re.search(r"\nfunction larder_row\(.*?\nend\n", SRC, re.S).group(0)
    assert "'pile_fixed', 'pile_refound', 'pile_lost'" in row


@test("ai-killers: the pile found again by its name when its id finds no stockpile of ours")
def _():
    p = re.search(r"\nfunction larder_pile\(.*?\nend\n", SRC, re.S).group(0)
    assert "larder_by_name(c.pile_name)" in p and "c.pile = b.id" in p and "pile_lost" in p
    assert "LARDER_PREFIX .. uid" in re.search(r"\nlocal function free\(.*?\nend\n", SRC, re.S).group(0)


@test("ai-killers.lua stays under 60 KB")
def _():
    assert len(SRC.encode("utf-8")) < 60 * 1024, len(SRC.encode("utf-8"))


@test("ai-killers.lua compiles under Lua 5.3")
def _():
    need_lua()
    f = LuaRuntime().eval("function(s) local f, e = load(s, 'b', 't', {}) return e end")
    assert f(SRC) is None, f(SRC)


# --- 2. the settings (Lua) ----------------------------------------------------------

@test("creation: a new pile (every food on, as DF makes it) written to drink and meals only, exactly")
def _():
    need_lua()
    lua, env, w = world()
    u, sp = made(lua, env, w)
    ok, bad = exact(lua, sp)
    assert ok, bad
    assert sp.storage.max_barrels == 2 and not py(w.commands)   # (an empty Lua table reads as {})
    c = py(env.report())["cells"][0]
    assert "pile_all_food" not in c and "pile_fixed" not in c, c


@test("B's piles: one made by 0.105.97 with every food on is put right by the report, counted once")
def _():
    need_lua()
    lua, env, w = world()
    u, sp = made(lua, env, w)
    all_on(lua, w, sp)
    sp.settings.flags.stone = True                   # another category on too
    sp.storage.max_bins = 4
    state_cell(w).pile_all_food = True               # as 0.105.97 left it
    c = py(env.report())["cells"][0]
    ok, bad = exact(lua, sp)
    assert ok, bad
    assert c["pile_fixed"] == 1 and "pile_all_food" not in c and c["pile"] == sp.id, c
    assert sp.storage.max_barrels == 2                               # kept
    c = py(env.report())["cells"][0]
    assert c["pile_fixed"] == 1, c                                   # right now: not written again


@test("each cycle: the cell action puts the settings right too (DF turning a list on after creation)")
def _():
    need_lua()
    lua, env, w = world()
    u, sp = made(lua, env, w)
    sp.settings.food.meat[0] = True
    cell(lua, env, [3])
    assert exact(lua, sp)[0] and state_cell(w).pile_fixed == 1
    # a switch in the middle of a list: the quick read misses it, the whole read (once a day) doesn't
    sp.settings.food.seeds[1] = True
    py(env.report())
    assert sp.settings.food.seeds[1] is True
    advance(env, DAY)
    c = py(env.report())["cells"][0]
    assert sp.settings.food.seeds[1] is False and c["pile_fixed"] == 2, c


@test("a write that doesn't take: pile_all_food said, tried again at once when DF fills the lists")
def _():
    need_lua()
    lua, env, w = world()
    u, z, d = bedroom_fort(lua, w)
    cell(lua, env, [3])
    u.pos.x, u.pos.y = 21, 21
    # (the likeliest reading of B's piles) the new pile's lists not filled yet: nothing to write
    real = w.new_settings
    w.new_settings = lua.eval("function(f) return function() return f(0) end end")(real)
    cell(lua, env, [3])
    sp = w.piles[1]
    c = py(env.report())["cells"][0]
    assert c["pile_all_food"] is True and "pile_fixed" not in c, c
    w.new_settings = real
    all_on(lua, w, sp)                               # DF fills them, every food on
    c = py(env.report())["cells"][0]
    assert exact(lua, sp)[0] and c["pile_fixed"] == 1 and "pile_all_food" not in c, c
    # lists that refuse writes: said, and not written again each cycle
    all_on(lua, w, sp)
    w.locked = True
    c = py(env.report())["cells"][0]
    assert c["pile_all_food"] is True and c["pile_fixed"] == 1, c
    tried = state_cell(w).pile_tried
    advance(env, 100)
    py(env.report())
    assert state_cell(w).pile_tried == tried
    w.locked = False
    advance(env, DAY)
    c = py(env.report())["cells"][0]
    assert exact(lua, sp)[0] and c["pile_fixed"] == 2 and "pile_all_food" not in c, c


@test("a dry run reads, never writes")
def _():
    need_lua()
    lua, env, w = world()
    u, sp = made(lua, env, w)
    all_on(lua, w, sp)
    cell(lua, env, [3], dry=True)
    assert sp.settings.food.meat[0] is True and state_cell(w).pile_fixed is None


# --- 3. the pile's id (Lua) ---------------------------------------------------------

@test("id: a pile whose id changed (moved, its name kept) is found by its name; no second pile laid")
def _():
    need_lua()
    lua, env, w = world()
    u, sp = made(lua, env, w)
    old = sp.id
    sp.id = 1538
    c = py(env.report())["cells"][0]
    assert c["pile"] == 1538 and c["pile_refound"] == 1 and state_cell(w).pile == 1538, (c, old)
    cell(lua, env, [3])
    assert len(w.piles) == 1 and len(py(w.qf)) == 1


@test("id: a cell whose id was lost finds its own pile by name instead of laying another")
def _():
    need_lua()
    lua, env, w = world()
    u, sp = made(lua, env, w)
    state_cell(w).pile = None
    cell(lua, env, [3])
    assert len(w.piles) == 1 and len(py(w.qf)) == 1 and state_cell(w).pile == sp.id


@test("id: a pile gone is said (pile_lost) and made again; a pile of another name at the id is not ours")
def _():
    need_lua()
    lua, env, w = world()
    u, sp = made(lua, env, w)
    w.piles[1] = None                                # gone (a 1-tile pile built over, say)
    c = py(env.report())["cells"][0]
    assert c["pile"] is False and c["pile_lost"] == 1, c
    cell(lua, env, [3])
    assert len(w.piles) == 1 and len(py(w.qf)) == 2
    sp2 = w.piles[1]
    assert exact(lua, sp2)[0] and sp2.name == "AI cell larder 3"
    sp2.name = "Player's drinks"                     # renamed: no longer the cell's
    c = py(env.report())["cells"][0]
    assert c["pile"] is False and c["pile_lost"] == 2, c


@test("release: the cell's pile goes, and any other pile of its name")
def _():
    need_lua()
    lua, env, w = world()
    u, sp = made(lua, env, w)
    twin = lua.eval("function(W, sp) local b = {id = 900, x1 = 0, y1 = 0, x2 = 0, y2 = 0, z = 100,"
                    " name = sp.name, settings = W.new_settings(), storage = {max_barrels = 0, max_bins = 0},"
                    " getType = function() return 'Stockpile' end}; table.insert(W.piles, b); return b end")(w, sp)
    r = cell(lua, env, [])
    assert r["released"] == ["Degel"] and len(w.piles) == 0 and sp.gone is True and twin.gone is True, r


# --- 4. the brain -------------------------------------------------------------------

@test("brain: the corrections and a lost pile are said with the cell; the write that didn't take as before")
def _():
    w = PK._larder_words({"pile": 701, "drink": 5, "food": 1, "pile_fixed": 2, "pile_lost": 1})
    assert "settings put back to drink and meals only 2 time(s)" in w and "went missing 1 time(s)" in w, w
    assert "did not take" not in w
    w = PK._larder_words({"pile": 701, "drink": 5, "food": 1, "pile_all_food": True})
    assert "its settings did not take" in w and "put back" not in w, w
    w = PK._larder_words({"pile": 701, "drink": 5, "food": 1})
    assert w == "; the cell's pile holds 5 drink and 1 meal(s)", w


if __name__ == "__main__":
    finish()
