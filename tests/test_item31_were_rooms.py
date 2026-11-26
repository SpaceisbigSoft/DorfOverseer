"""(0.105.119 item31) Werebeast cells that never refuse, made before the moon.

What the journal showed (25 Nov, 15:00-18:30):
  - A, 16:27:43: a wild Werepanther Bowman ("has come!", hostile, from the
    map edge) killed 6 and bit more; the bitten were listed by DF's
    WERECURSE syndrome within 14 s (were_cells named them at 16:27:57). The
    next full moon came at 16:33 and moon_cell refused 39 times "no jail
    zone or free bedroom for a cell" though A had 2 jails with doors: since
    0.105.115 in_zone read `z.were` on a DF zone (userdata), which throws
    "Cannot read field building_civzonest.were", so cell_room found no jail
    or bedroom at all and only the were cells (levers unlinked) were left.
    7+ turned, 25 died.
  - E 16:53 (a Werepanther Child), F 15:09/15:59 (a Wereskink, the same one
    twice: it walked off in human form and came back at the next moon),
    17:07 (a Werellama Child), 17:20 (a Weremole Child): all wild werebeasts
    come to the fort, none a migrant or a guest; each bitten citizen was
    listed at once.
  - (item34) F: Besmar was locked in at 17:21:40 and turned at 17:27:32 nine
    levels down: a locked cell's dwarf found outside is now read unlocked
    (were.list outside) and moved in again at once; and the cursed are moved
    in at the first call of the lead, not in the last minutes.

Now: in_zone takes a plain table only as a box; cell_room falls back to any
small room with a door (an office, a tomb, another's bedroom with nobody in
it), a side cell dug for it (ai-werecells side_*), and a were cell not yet
linked (were_open: the burrow holds them, locked once linked); with nothing
at all it digs a side cell (never a refusal). The brain reserves a cell for
each cursed citizen as soon as the curse is known (moon_cell reserve).

    python tests/test_item31_were_rooms.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

from planner import Memory, plan  # noqa: E402

CH = [{"phase": 27, "tick": 110290156}]


def fort(were):
    from test_threats import fort as tfort
    return tfort({"were": were})


def moon(props):
    return [p for p in props if p.rule == "moon_cell"]


@test("were: a cursed citizen with no cell, far from the moon: a cell reserved now (all the cursed named), priority 2")
def _():
    rows = [{"id": 1, "name": "Zuglar", "by_syndrome": True}, {"id": 2, "name": "Mörul", "by_syndrome": True}]
    c = moon(plan(fort({"list": rows, "changes": CH, "moon_phase": 10, "cells": []}), Memory())[0])
    assert len(c) == 1 and c[0].action == {"type": "moon_cell", "ids": [1, 2], "reserve": True}, c
    assert "before the full moon" in c[0].reason and c[0].priority == 2


@test("were: every cursed one has a cell (reserved): no reserve again, and a reserved cell is never 'let out'")
def _():
    rows = [{"id": 1, "name": "Zuglar", "by_syndrome": True, "cell": True, "reserved": True}]
    props, notes = plan(fort({"list": rows, "changes": CH, "moon_phase": 10,
                              "cells": [{"unit_id": 1, "reserved": True, "kind": "jail"}]}), Memory())
    assert not moon(props), moon(props)
    assert not any("in their cells: kept in" in n for n in notes), notes


@test("moon: near the change, a reserved cell is taken (moon_cell with move_in), reserve not sent")
def _():
    rows = [{"id": 1, "name": "Zuglar", "by_syndrome": True, "cell": True, "reserved": True}]
    c = moon(plan(fort({"list": rows, "changes": CH, "moon_phase": 25,
                        "cells": [{"unit_id": 1, "reserved": True}]}), Memory())[0])
    assert len(c) == 1 and c[0].action == {"type": "moon_cell", "ids": [1], "move_in": True}, c


@test("were: cursed a moon or more and no cell that locks: a plain note (not a Needs you); an unlinked were cell counts as none")
def _():
    rows = [{"id": 1, "name": "Besmar", "by_syndrome": True, "days_cursed": 30}]
    notes = plan(fort({"list": rows, "changes": CH, "moon_phase": 10, "cells": []}), Memory())[1]
    hit = [n for n in notes if "werebeast-cursed 30+ days" in n]
    assert hit and not hit[0].startswith("Needs you"), notes
    rows[0].update(cell=True, cell_kind="were_open")
    notes = plan(fort({"list": rows, "changes": CH, "moon_phase": 10, "cells": [{"unit_id": 1}]}), Memory())[1]
    assert any("werebeast-cursed 30+ days" in n for n in notes), notes
    rows[0].update(cell_kind="jail", days_cursed=3)
    notes = plan(fort({"list": rows, "changes": CH, "moon_phase": 10, "cells": [{"unit_id": 1}]}), Memory())[1]
    assert not any("werebeast-cursed" in n for n in notes), notes


@test("moon (item34): locked in yet found outside: moon_cell again (move_in) and a note")
def _():
    rows = [{"id": 1, "name": "Besmar", "by_syndrome": True, "cell": True, "outside": True}]
    props, notes = plan(fort({"list": rows, "changes": CH, "moon_phase": 26,
                              "cells": [{"unit_id": 1, "locked": True}]}), Memory())
    c = moon(props)
    assert c and c[0].action.get("move_in") is True, c
    assert any("found outside it" in n for n in notes), notes


@test("were: a wild werebeast (hostile, not a guest) in human form: the squad's reason says so")
def _():
    s = fort({"list": [], "changes": CH, "moon_phase": 10,
              "outsiders": [{"id": 1776, "name": "Sapa", "hostile": True}]})
    s["military"] = {"squads": [{"id": 186, "name": "The Axes", "members": 5, "ai_orders": False}]}
    props = plan(s, Memory())[0]
    sq = [p for p in props if p.rule == "squad_attack" and 1776 in (p.action.get("kill") or [])]
    if sq:          # (a squad may be judged unable here; the wording is what is pinned)
        assert "wild werebeast" in sq[0].reason, sq
    src = (ROOT / "brain" / "planner_threats.py").read_text(encoding="utf-8")
    assert "a wild werebeast (hostile, it came to kill)" in src


@test("lua source: in_zone takes only a plain table as a box (z.were threw on a DF zone); reserve checked; file sizes")
def _():
    act = (ROOT / "lua" / "ai-threats-actions.lua").read_text(encoding="utf-8")
    body = act[act.index("local function in_zone("):act.index("function touches_zone")]
    assert "if type(z) == 'table' then return true end" in body and "if z.were then" not in act
    w = (ROOT / "lua" / "ai-bridge-actions-works.lua").read_text(encoding="utf-8")
    assert "moon_cell: reserve is true or false" in w
    for f in ("ai-threats-actions.lua", "ai-threats.lua", "ai-werecells.lua", "ai-bridge-actions-works.lua"):
        assert len((ROOT / "lua" / f).read_bytes().replace(b"\r", b"")) < 60_000, f


# ---- Lua (lupa: these run on the PC) -----------------------------------------------------

def need_env():
    try:
        from lupa.lua53 import LuaRuntime  # noqa: F401
    except ImportError:
        return None, None
    import test_item18_were_hold as T18
    import test_threats as TT
    game = TT.GAME.replace("assert(load(src, 'ai-threats'",
                           "e.reqscript = function(n) if n == 'ai-werecells' then return G.W end "
                           "error('reqscript ' .. tostring(n)) end\nassert(load(src, 'ai-threats'", 1)
    orig = TT.GAME
    TT.GAME = game
    try:
        LUA, E = T18.lua_env()
    finally:
        TT.GAME = orig
    LUA.execute(r"""local E = ...; local G = E.G
        local W = {digs = 0}
        W.cells = function() return W.list or {} end
        W.find = function(k) for _, c in ipairs(W.list or {}) do if c.key == k then return c end end end
        W.zone_of = function(c) return {id = c.key, x1 = c.x1, y1 = c.y1, x2 = c.x2, y2 = c.y2, z = c.z, were = true} end
        W.lever_links = function() return {} end
        W.ready = function() return false end
        W.cell_state = function() return {built = false, linked = false} end
        W.piece_ids = function() return {} end
        W.side_key = function(r) return ('dig:%d,%d,%d'):format(r.x, r.y, r.z) end
        W.side_site = function(pos, taken) if W.no_rock then return nil end
            local r = {x = 50, y = 50, z = 10, door = {x = 50, y = 51, z = 10}}
            if taken[W.side_key(r)] then return nil end return r end
        W.side_dig = function(site, dry) if not dry then W.digs = W.digs + 1 end return 2 end
        W.side_step = function(rec) return W.step or 'digging' end
        W.side_zone = function(key, rec) return {id = key, x1 = rec.x, y1 = rec.y, x2 = rec.x, y2 = rec.y, z = rec.z, side = true} end
        G.W = W
        -- a DF zone is userdata: an unknown field throws (as `z.were` did in the game)
        local function strict(t)
            return setmetatable({}, {__index = function(_, k)
                local v = t[k]
                if v == nil then error('Cannot read field building_civzonest.' .. tostring(k) .. ': not found') end
                return v end, __newindex = t})
        end
        G.strict = strict
        local other = E.df.global.world.buildings.other
        local jail = other.ZONE_DUNGEON[1]
        local sj = strict({id = jail.id, x1 = jail.x1, y1 = jail.y1, x2 = jail.x2, y2 = jail.y2, z = jail.z, type = 'Dungeon'})
        other.ZONE_DUNGEON[1] = sj
        for i, b in ipairs(G.buildings) do if b == jail then G.buildings[i] = sj end end
        other.ANY_ZONE = {sj}
        E.df.civzone_type = setmetatable({}, {__index = function(_, k) return k end})
        G.units[4] = {id = 4, name = 'Zuglar', race = 1, enemy = {normal_race = -1}, pos = {x = 40, y = 40, z = 10}}""", E)
    return LUA, E


def burrow_units(E, uid):
    from test_threats import LUA
    return bool(LUA.eval("""function(E, uid)
        for _, b in ipairs(E.df.global.plotinfo.burrows.list) do
            if b.units and b.units[uid] and tostring(b.name):sub(1, 12) == 'AI moon cell' then return true end
        end
        return false end""")(E, uid))


@test("lua: a jail that is a strict DF zone (an unknown field throws) is found: placed, not 'no jail zone'")
def _():
    LUA, E = need_env()
    if LUA is None:
        return
    r = E.moon_cell(LUA.table_from([4]), False, False)
    c = E.G.saved["ai-overseer/threats"].cells["4"]
    assert c is not None and c.zone == 77 and c.kind == "jail" and not r.error, dict(r)


@test("lua: reserve holds the room (no burrow, nobody moved); the moon's call takes it; release frees it")
def _():
    LUA, E = need_env()
    if LUA is None:
        return
    G = E.G
    r = E.moon_cell(LUA.table_from([4]), False, False, None, LUA.table_from({"reserve": True}))
    c = G.saved["ai-overseer/threats"].cells["4"]
    assert c.reserved and c.zone == 77 and r.reserved and not burrow_units(E, 4) and not G.moved, dict(r)
    r = E.moon_cell(LUA.table_from([4]), False, False, None, LUA.table_from({"reserve": True}))
    assert r.rejected and r.nothing_to_do, dict(r)                      # a reserve twice changes nothing
    r = E.moon_cell(LUA.table_from([4]), False, False, None, LUA.table_from({"move_in": True}))
    c = G.saved["ai-overseer/threats"].cells["4"]
    assert not c.reserved and burrow_units(E, 4) and G.moved == 1 and c.locked, dict(r)
    E.moon_cell(LUA.table_from([]), True, False)
    assert G.saved["ai-overseer/threats"].cells["4"] is None


@test("lua: no jail or bedroom: an office with a door; two cursed never share a room; nobody locked in with another")
def _():
    LUA, E = need_env()
    if LUA is None:
        return
    G = E.G
    LUA.execute("""local E = ...; local G = E.G
        local other = E.df.global.world.buildings.other
        local off = G.strict({id = 88, x1 = 10, y1 = 0, x2 = 12, y2 = 2, z = 10, type = 'Office'})
        table.insert(G.buildings, off)
        table.insert(other.ANY_ZONE, off)
        local door = {id = 32, door_flags = {forbidden = false}, getType = function() return 'Door' end}
        table.insert(G.buildings, door)
        G.tiles['13,1,10'] = door
        G.units[5] = {id = 5, name = 'Tosid', race = 1, enemy = {normal_race = -1}, pos = {x = 41, y = 40, z = 10}}""", E)
    r = E.moon_cell(LUA.table_from([4, 5]), False, False)
    cells = G.saved["ai-overseer/threats"].cells
    zones = {cells["4"].zone, cells["5"].zone}
    assert zones == {77, 88}, (dict(r), zones)
    assert {cells["4"].kind, cells["5"].kind} == {"jail", "room"}


@test("lua: no room at all: a side cell dug (never a refusal); dug and its door built: the cell; no rock: said")
def _():
    LUA, E = need_env()
    if LUA is None:
        return
    G = E.G
    LUA.execute("local E = ...; E.df.global.world.buildings.other.ZONE_DUNGEON = {}; "
                "E.df.global.world.buildings.other.ANY_ZONE = {}", E)
    r = E.moon_cell(LUA.table_from([4]), False, False)
    st = G.saved["ai-overseer/threats"]
    assert r.ok and r.digging and "side cell" in r.digging[1] and G.W.digs == 1, dict(r)
    assert st.digs["dig:50,50,10"] is not None and st.cells["4"] is None
    r = E.moon_cell(LUA.table_from([4]), False, False)
    assert G.W.digs == 1, dict(r)                                    # not dug twice
    LUA.execute("""local E = ...; local G = E.G; G.W.step = 'ready'
        local door = {id = 33, door_flags = {forbidden = false}, getType = function() return 'Door' end}
        table.insert(G.buildings, door); G.tiles['50,51,10'] = door""", E)
    r = E.moon_cell(LUA.table_from([4]), False, False)
    c = G.saved["ai-overseer/threats"].cells["4"]
    assert c and c.zone == "dig:50,50,10" and c.kind == "side", dict(r)
    LUA.execute("local E = ...; E.G.units[6] = {id = 6, name = 'Olin', race = 1, enemy = {normal_race = -1}, "
                "pos = {x = 40, y = 41, z = 10}}; E.G.W.no_rock = true", E)
    r = E.moon_cell(LUA.table_from([4, 6]), False, False)
    assert r.error and "no rock" in r.error, dict(r)


@test("lua: a were cell not linked yet is taken last (were_open): the burrow, never 'locked'; linked: a were cell")
def _():
    LUA, E = need_env()
    if LUA is None:
        return
    G = E.G
    LUA.execute("""local E = ...; local G = E.G
        E.df.global.world.buildings.other.ZONE_DUNGEON = {}; E.df.global.world.buildings.other.ANY_ZONE = {}
        G.W.list = {{key = 'were:9:1', x1 = 20, y1 = 20, x2 = 21, y2 = 21, z = 10}}""", E)
    r = E.moon_cell(LUA.table_from([4]), False, False, None, LUA.table_from({"move_in": True}))
    c = G.saved["ai-overseer/threats"].cells["4"]
    assert c.kind == "were_open" and G.moved == 1, dict(r)
    r = E.moon_cell(LUA.table_from([4]), False, False)
    c = G.saved["ai-overseer/threats"].cells["4"]
    assert not c.locked and r.open_cell, dict(r)
    LUA.execute("local E = ...; E.G.W.cell_state = function() return {built = true, linked = true} end", E)
    E.moon_cell(LUA.table_from([4]), False, True)
    E.moon_cell(LUA.table_from([4]), False, False)
    assert G.saved["ai-overseer/threats"].cells["4"].kind == "were"


@test("lua (item34): locked in yet outside: said (escaped), moved in again and locked in the same call")
def _():
    LUA, E = need_env()
    if LUA is None:
        return
    G = E.G
    E.moon_cell(LUA.table_from([4]), False, False, None, LUA.table_from({"move_in": True}))
    c = G.saved["ai-overseer/threats"].cells["4"]
    assert c.locked and G.moved == 1
    assert E.cell_has(c, G.units[4]) is True
    LUA.execute("local E = ...; E.G.units[4].pos = {x = 40, y = 40, z = 1}", E)
    assert E.cell_has(c, G.units[4]) is False
    r = E.moon_cell(LUA.table_from([4]), False, False)
    assert r.escaped and "40,40,1" in r.escaped[1] and G.moved == 2 and r.locked, dict(r)


@test("lua: side_site: a corridor floor, the doorway and room in rock, the room's 8 neighbours rock but the doorway")
def _():
    try:
        from lupa.lua53 import LuaRuntime  # noqa: F401
    except ImportError:
        return
    import test_item24_were_cells as T24
    lua, E = T24.were_env()
    lua.execute("""local E = ...
        E.G.floor = {['10,10'] = true}
        E.shape_at = function(x, y, z) if E.G.floor[x .. ',' .. y] then return 'FLOOR', false end return 'WALL', true end
        E.walk_at = function(x, y) return E.G.floor[x .. ',' .. y] == true end""", E)
    r = E.side_site(lua.table_from({"x": 10, "y": 10, "z": 5}))
    assert (r.x, r.y, r.door.x, r.door.y) == (12, 10, 11, 10), (r.x, r.y)
    lua.execute("local E = ...; E.G.floor['13,11'] = true", E)          # a hole beside the room (diagonal)
    r = E.side_site(lua.table_from({"x": 10, "y": 10, "z": 5}))
    assert (r.x, r.y) != (12, 10) and abs(r.x - 10) + abs(r.y - 10) == 2, (r.x, r.y)
    taken = lua.table_from({E.side_key(r): True})
    r2 = E.side_site(lua.table_from({"x": 10, "y": 10, "z": 5}), taken)
    assert r2 and E.side_key(r2) != E.side_key(r)
    lua.execute("local E = ...; E.shape_at = function() return 'FLOOR', false end", E)   # no rock anywhere
    assert E.side_site(lua.table_from({"x": 10, "y": 10, "z": 5})) is None


finish()
