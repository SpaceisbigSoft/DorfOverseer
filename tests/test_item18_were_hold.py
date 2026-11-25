"""(0.105.115 item18) E's werepanther outbreak, 25 Nov 06:13-10:40: werebeast
cells that confine and hold.

What the journal showed:
  - Litast's cell was locked at 07:31:55 and read unlocked at 07:32:24
    ("relock"); between them only water survey, house_dwarves ("Litast ...
    moves to a better room for them (151 -> 408)") and join_levels ran, and
    the pulse watchers (gates, insane, shafts, fights) log no decision. The
    cell's doors touch corridors, entrances and other rooms that other rules
    lock and unlock. Now every unlock of a locked cell's door by any rule but
    the cell's own release is refused in ai-util's lock_door, and counted by
    who asked (were.door_guard), and house_dwarves never hands out a room a
    moon cell or a killer's cell holds;
  - Dodok and the child Uzol "waited" 14+ days for their cells, worked
    outside them and turned there: the cell's burrow is now their only one
    (out of every other burrow, given back at the release), and a cursed
    dwarf still outside a day after the cell was placed, or once the change
    is close (move_in, WERE_MOVE_PHASES), is moved in at once
    (dfhack.units.teleport, a direct move) and locked in the same call.

    python tests/test_item18_were_hold.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

import planner_threats as PT  # noqa: E402
from planner import Memory, plan, PLANNER_CONFIG  # noqa: E402

CH = [{"phase": 27, "tick": 110290156}]


def fort(were):
    from test_threats import fort as tfort
    return tfort({"were": were})


def moon(props):
    return [p for p in props if p.rule == "moon_cell" and not p.action.get("release")]


@test("moon_change_close: 3 phases before a change phase and its own window; unread: no; none seen: phase 27")
def _():
    got = [ph for ph in range(28) if PT.moon_change_close(CH, ph, PLANNER_CONFIG)]
    after = PLANNER_CONFIG.get("moon_after_days", 1)
    want = sorted({(27 + k) % 28 for k in range(-3, after + 1)})
    assert got == want, (got, want)
    assert not PT.moon_change_close(CH, None, PLANNER_CONFIG)
    assert PT.moon_change_close([], 25, PLANNER_CONFIG) and not PT.moon_change_close([], 15, PLANNER_CONFIG)


@test("the change close: moon_cell carries move_in; far off (in the lead): it doesn't")
def _():
    rows = [{"id": 1, "name": "Dodok", "by_syndrome": True, "cell": True}]
    c = moon(plan(fort({"list": rows, "changes": CH, "moon_phase": 25, "cells": [{"unit_id": 1}]}), Memory())[0])
    assert c and c[0].action.get("move_in") is True and "moved in now" in c[0].reason, c
    c = moon(plan(fort({"list": rows, "changes": CH, "moon_phase": 20, "cells": [{"unit_id": 1}]}), Memory())[0])
    assert c and "move_in" not in c[0].action and "after a day" in c[0].reason, c


@test("an unlock refused at a locked cell's door is said in the notes, by who asked")
def _():
    rows = [{"id": 1, "name": "Litast", "by_syndrome": True, "cell": True, "locked": True}]
    s = fort({"list": rows, "changes": CH, "moon_phase": 26, "cells": [{"unit_id": 1, "locked": True}],
              "door_guard": {"held": 1, "refused": {"gate": 2}}})
    notes = plan(s, Memory())[1]
    assert any("unlock refused for gate x2" in n for n in notes), notes


@test("lua: house_dwarves never hands out a moon cell's or a killer cell's room; act_moon_cell checks move_in")
def _():
    src = (ROOT / "lua" / "ai-homes.lua").read_text(encoding="utf-8")
    assert "reqscript('ai-threats').load_state().cells" in src and "reqscript('ai-killers').state().cells" in src
    w = (ROOT / "lua" / "ai-bridge-actions-works.lua").read_text(encoding="utf-8")
    assert "moon_cell: move_in is true or false" in w and "{move_in = a.move_in == true}" in w
    d = (ROOT / "lua" / "ai-util-doors.lua").read_text(encoding="utf-8")
    assert "why ~= 'cell' and b and cell_door_held(b)" in d


def lua_env():
    try:
        from lupa.lua53 import LuaRuntime  # noqa: F401
    except ImportError:
        return None, None
    import test_threats as TT
    LUA, E = TT.LUA, TT.LUA.execute(TT.GAME, TT.SRC)
    LUA.execute("""local E = ...; local G = E.G
        E.df.tiletype = {attrs = setmetatable({}, {__index = function() return {shape = 'F'} end})}
        E.df.tiletype_shape = {F = 'FLOOR'}
        E.dfhack.maps.getTileType = function() return 1 end
        E.dfhack.maps.getWalkableGroup = function() return 1 end
        E.df.building_type.Civzone = 'Civzone'
        E.dfhack.job = {removeWorker = function(j) G.dropped = (G.dropped or 0) + 1 end}
        E.dfhack.units.teleport = function(u, p) u.pos = {x = p.x, y = p.y, z = p.z}; G.moved = (G.moved or 0) + 1 return true end
        local shelter = {id = 5, name = 'AI shelter', units = {}}
        G.shelter = shelter
        local list = setmetatable({shelter}, {__index = {insert = function(self, _, b) rawset(self, #self + 1, b) end}})
        E.df.global.plotinfo.burrows = {list = list, next_id = 6}
        E.df.burrow = {new = function() return {units = {}} end}
        E.dfhack.burrows.isAssignedUnit = function(b, u) return b.units[u.id] == true end
        E.dfhack.burrows.setAssignedUnit = function(b, u, on) b.units = b.units or {}; b.units[u.id] = on or nil end
        local z = {id = 77, x1 = 0, y1 = 0, x2 = 2, y2 = 2, z = 10}
        table.insert(G.buildings, z)
        table.insert(E.df.global.world.buildings.other.ZONE_DUNGEON, z)
        local door = {id = 31, door_flags = {forbidden = false}, getType = function() return 'Door' end}
        table.insert(G.buildings, door)
        G.tiles['3,1,10'] = door; G.door = door""", E)
    return LUA, E


@test("lua: confined (out of the shelter burrow), moved in after a day and locked at once; burrows back at the release")
def _():
    LUA, E = lua_env()
    if LUA is None:
        return
    G = E.G
    LUA.execute("""local E = ...; local G = E.G
        G.units[4] = {id = 4, name = 'Uzol', race = 1, enemy = {normal_race = -1}, pos = {x = 40, y = 40, z = 10},
                      job = {current_job = {id = 1}}}
        G.shelter.units[4] = true""", E)
    r = E.moon_cell(LUA.table_from([4]), False, False)
    st = G.saved["ai-overseer/threats"]
    assert st.cells["4"] is not None and not G.shelter.units[4] and r.unburrowed == 1, dict(r)
    assert not st.cells["4"].locked and not G.moved
    # a day on, still outside: moved in, job dropped, locked in the same call
    LUA.execute("local E = ...; local c = E.G.saved['ai-overseer/threats'].cells['4']; c.tick = c.tick - 1300", E)
    r = E.moon_cell(LUA.table_from([4]), False, False)
    st = G.saved["ai-overseer/threats"]
    assert G.moved == 1 and G.dropped == 1 and r.moved and st.cells["4"].locked and G.door.door_flags.forbidden, dict(r)
    # another rule's unlock refused, counted; the cell's own release unlocks, the shelter given back
    U = E.reqscript("ai-util")
    changed, ok = U.lock_door(G.door, False, "gate")
    assert not changed and not ok and G.door.door_flags.forbidden
    g = U.cell_door_guard()
    assert g.held == 1 and g.refused.gate == 1 and g.last.why == "gate", dict(g)
    E.moon_cell(LUA.table_from([]), True, False)
    assert not G.door.door_flags.forbidden and G.shelter.units[4] is True
    assert U.cell_door_guard().held == 0
    changed, ok = U.lock_door(G.door, True, "gate")
    assert ok and U.lock_door(G.door, False, "gate")[1]        # no cell: unlocked as before


@test("lua: move_in moves at once; never with someone else inside, nor one in beast form or a fight")
def _():
    LUA, E = lua_env()
    if LUA is None:
        return
    G = E.G
    LUA.execute("""local E = ...; local G = E.G
        G.units[4] = {id = 4, name = 'Dodok', race = 1, enemy = {normal_race = -1}, pos = {x = 40, y = 40, z = 10},
                      opponent = {unit_id = 9}}
        G.citizens[1] = {id = 12, name = 'Other', pos = {x = 1, y = 1, z = 10}}""", E)
    r = E.moon_cell(LUA.table_from([4]), False, False, None, LUA.table_from({"move_in": True}))
    assert not G.moved and r.not_moved and "fight" in r.not_moved[1], dict(r)
    LUA.execute("local E = ...; E.G.units[4].opponent.unit_id = -1", E)
    r = E.moon_cell(LUA.table_from([4]), False, False, None, LUA.table_from({"move_in": True}))
    assert not G.moved and "someone else" in r.not_moved[1], dict(r)
    LUA.execute("local E = ...; E.G.citizens[1] = nil", E)
    r = E.moon_cell(LUA.table_from([4]), False, True, None, LUA.table_from({"move_in": True}))
    assert r.would_move and not G.moved, dict(r)                 # a dry run moves nobody
    r = E.moon_cell(LUA.table_from([4]), False, False, None, LUA.table_from({"move_in": True}))
    assert G.moved == 1 and r.locked and len(r.locked) == 1, dict(r)


finish()
