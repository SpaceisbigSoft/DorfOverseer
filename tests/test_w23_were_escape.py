"""(R30b, 0.105.123) The weres that left their raised-bridge cells, and the
squads sent at a were sealed in one.

E, 25 Nov 22:04 and 22:18: werepanthers moved into their were cells
(dfhack.units.teleport), the bridge raised in the same call, and found
outside ~30 s later, levels away; a read-only probe (22:31) found the cells
walled, roofed, the raised ones cut off in DF's walk map, nobody sharing a
cell and nothing broken, and the one cycle where every were had no path at
the move (dest -30000, no steps) held. units.teleport moves the unit and
leaves its path: DF walks it on along the old steps from wherever it
stands. move_in now drops the path (drop_path); a raise DF's walk map still
joins to the corridor is not counted as locked (not_sealed).

A, 25 Nov 19:21-22:24: 105 squad_attack orders at Zuglar in beast form, six
squads every moon, while he stood locked behind a raised bridge. The threats
report's were row says `sealed` (cell_sealed: locked, raised and still, the
shell sealed, the walk map parted, the dwarf inside); no squad and no alarm
for such a one, an order already naming them comes off; loose or escaped
ones are targets as before.

    python tests/test_w23_were_escape.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, plan  # noqa: E402
import planner_military_weres as W  # noqa: E402
from planner_military import hazard_alert  # noqa: E402
from planner import PLANNER_CONFIG  # noqa: E402

CFG = dict(PLANNER_CONFIG)
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
ZUGLAR = 17594


def sq(i, members=10, power=60, **kw):
    q = {"id": i, "name": f"Squad {i}", "members": members, "size": 10, "orders": 0, "ai_orders": 0,
         "power": {"power": power, "melee_power": power, "armed": members}, "routine": "Constant training"}
    q.update(kw)
    return q


def fort(sealed=True, squads=None, locked=True) -> dict:
    s = copy.deepcopy(BASE)
    s["others_on_map"]["threats"] = []
    s["military"]["squads"] = squads if squads is not None else [sq(206), sq(210), sq(215)]
    s["hazards"] = {"berserk": [{"id": ZUGLAR, "name": 'Zuglar Uzolasdug "Oildrums", Werepanther Glassmaker',
                                 "changed": True}]}
    row = {"id": ZUGLAR, "name": "Zuglar", "cell": True, "cell_kind": "were", "by_syndrome": True}
    if locked:
        row["locked"] = True
    if sealed:
        row["sealed"] = True
    s.setdefault("threats", {})["were"] = {"list": [row], "cells": []}
    return s


def attacks(props, uid):
    return [p for p in props if p.rule == "squad_attack" and uid in (p.action.get("kill") or [])]


@test("A's Zuglar in beast form, sealed in his were cell: no squad sent, no alarm for him")
def _():
    s = fort()
    assert W.sealed_were_ids(s) == {ZUGLAR} and W.loose_berserk(s) == []
    assert ZUGLAR not in W.were_ids(s)
    props, _ = plan(s, Memory())
    assert not attacks(props, ZUGLAR), [(p.rule, p.action) for p in attacks(props, ZUGLAR)]
    why = hazard_alert(s, CFG, raising=True)
    assert "Zuglar" not in (why or ""), why


@test("loose (not sealed: escaped, bridge down, walk map joined) or not locked: every free squad goes as before")
def _():
    for s in (fort(sealed=False), fort(sealed=True, locked=False)):
        props, _ = plan(s, Memory())
        got = sorted(p.action["squad_id"] for p in attacks(props, ZUGLAR))
        assert got == [206, 210, 215], got
        assert "Zuglar" in (hazard_alert(s, CFG, raising=True) or "")


@test("an order already naming a sealed were comes off: cleared, or given again for the others")
def _():
    squads = [sq(206, ai_orders=1, kill_ids=[ZUGLAR]), sq(210, ai_orders=1, kill_ids=[ZUGLAR, 900])]
    props, _ = plan(fort(squads=squads), Memory())
    off = [p for p in props if p.action.get("squad_id") == 206 and p.action.get("clear")]
    assert off and off[0].rule == "squad_recall", [(p.rule, p.action) for p in props]
    again = [p for p in props if p.action.get("squad_id") == 210 and p.action.get("type") == "squad_orders"]
    assert again and again[0].action.get("kill") == [900], again


@test("a visiting were's threat row with the id of a sealed one is no threat row either")
def _():
    s = fort()
    s["others_on_map"]["threats"] = [{"id": ZUGLAR, "name": "Zuglar, Werepanther", "transformed": True,
                                      "can_reach_dwarves": True}]
    assert W.were_threat_rows(s) == []


@test("wiring: were_report says `sealed` from cell_sealed; move_in drops the path; a joined raise is not locked")
def _():
    t = (ROOT / "lua" / "ai-threats.lua").read_text(encoding="utf-8")
    assert "pcall(cell_sealed, c, u)" in t and "row.sealed" in t
    a = (ROOT / "lua" / "ai-threats-actions.lua").read_text(encoding="utf-8")
    assert "function drop_path(u)" in a and "    drop_path(u)\n    return true" in a
    assert "function cell_sealed(c, u)" in a and "out.not_sealed" in a
    for f in ("ai-threats.lua", "ai-threats-actions.lua"):
        assert len((ROOT / "lua" / f).read_bytes()) < 60 * 1024, f


# ---- Lua (lupa: the PC runner) ----

def lua_env():
    need_lua()
    import test_item18_were_hold as T18
    import test_threats as TT
    assert getattr(TT, "LUA", None) is not None, "test_threats' Lua did not load"
    game = TT.GAME.replace("assert(load(src, 'ai-threats'",
                           "e.reqscript = function(n) if n == 'ai-werecells' then return G.W end "
                           "error('reqscript ' .. tostring(n)) end\nassert(load(src, 'ai-threats'", 1)
    orig = TT.GAME
    TT.GAME = game
    try:
        LUA, E = T18.lua_env()
    finally:
        TT.GAME = orig
    LUA.execute("""local E = ...; local G = E.G
        local W = {st = {built = true, linked = true, raised = false, moving = false}, sets = {},
                   shut = true, join = false}
        W.cell = {key = 'were:7:1', x1 = 20, y1 = 20, x2 = 21, y2 = 21, z = 10,
                  bridge = {x = 20, y = 22, z = 10}, lever = {x = 20, y = 23, z = 10}}
        W.cells = function() return {W.cell} end
        W.find = function(k) if k == W.cell.key then return W.cell end end
        W.zone_of = function(c) return {id = c.key, x1 = c.x1, y1 = c.y1, x2 = c.x2, y2 = c.y2, z = c.z, were = true} end
        W.lever_links = function() return {} end
        W.ready = function() return W.st.built and W.st.linked and not W.st.raised end
        W.cell_state = function() return W.st end
        W.sealed = function() return W.shut end
        W.joined = function() return W.join end
        W.set_raised = function(c, up, dry)
            if not dry then W.st.raised = up; table.insert(W.sets, up) end
            return true
        end
        W.piece_ids = function() return {[900] = true, [901] = true} end
        G.W = W
        local function vec(t)
            return setmetatable(t, {__index = {resize = function(self, n)
                for i = #self, n + 1, -1 do self[i] = nil end end}})
        end
        G.units[4] = {id = 4, name = 'Onol', race = 1, enemy = {normal_race = -1}, pos = {x = 100, y = 154, z = 167},
                      path = {path = {x = vec({100, 101}), y = vec({155, 155}), z = vec({167, 167})},
                              dest = {x = 113, y = 148, z = 158}}}""", E)
    return LUA, E


@test("lua: moved in, the old path dropped (DF walked them out along it), the bridge raised, locked; sealed then")
def _():
    LUA, E = lua_env()
    G = E.G
    E.moon_cell(LUA.table_from([4]), False, False)                 # placed
    r = E.moon_cell(LUA.table_from([4]), False, False, None, LUA.table_from({"move_in": True}))
    u = G.units[4]
    assert G.moved == 1 and r.locked and len(r.locked) == 1, dict(r)
    assert len(u.path.path.x) == 0 and len(u.path.path.z) == 0 and u.path.dest.x == -30000, dict(u.path.dest)
    c = G.saved["ai-overseer/threats"].cells["4"]
    assert c.locked and E.cell_sealed(c, u)
    # each check of cell_sealed: the walk map joined, the shell open, moving, outside, not locked
    LUA.execute("local E = ...; E.G.W.join = true", E)
    assert not E.cell_sealed(c, u)
    LUA.execute("local E = ...; E.G.W.join = nil", E)
    assert not E.cell_sealed(c, u)                                   # unread: not sealed
    LUA.execute("local E = ...; E.G.W.join = false; E.G.W.shut = false", E)
    assert not E.cell_sealed(c, u)
    LUA.execute("local E = ...; E.G.W.shut = true; E.G.W.st.moving = true", E)
    assert not E.cell_sealed(c, u)
    LUA.execute("local E = ...; E.G.W.st.moving = false; E.G.units[4].pos = {x = 50, y = 50, z = 10}", E)
    assert not E.cell_sealed(c, u)
    LUA.execute("local E = ...; E.G.units[4].pos = {x = 20, y = 20, z = 10}", E)
    assert E.cell_sealed(c, u)
    LUA.execute("local E = ...; E.G.saved['ai-overseer/threats'].cells['4'].locked = nil", E)
    assert not E.cell_sealed(G.saved["ai-overseer/threats"].cells["4"], u)


@test("lua: raised, yet DF's walk map joins the cell to the corridor: not locked, said (not_sealed)")
def _():
    LUA, E = lua_env()
    G = E.G
    LUA.execute("local E = ...; E.G.W.join = true", E)
    E.moon_cell(LUA.table_from([4]), False, False)
    r = E.moon_cell(LUA.table_from([4]), False, False, None, LUA.table_from({"move_in": True}))
    c = G.saved["ai-overseer/threats"].cells["4"]
    assert not c.locked and r.not_sealed and not r.locked[1] and r.waiting[1], dict(r)
    LUA.execute("local E = ...; E.G.W.join = false", E)
    r = E.moon_cell(LUA.table_from([4]), False, False)
    assert G.saved["ai-overseer/threats"].cells["4"].locked and r.locked[1], dict(r)


@test("lua: locked and found outside: escaped, moved in again and relocked in the same call, path dropped")
def _():
    LUA, E = lua_env()
    G = E.G
    E.moon_cell(LUA.table_from([4]), False, False)
    E.moon_cell(LUA.table_from([4]), False, False, None, LUA.table_from({"move_in": True}))
    LUA.execute("""local E = ...; local u = E.G.units[4]
        u.pos = {x = 109, y = 152, z = 169}
        u.path.path.x[1] = 110; u.path.dest.x = 5""", E)
    r = E.moon_cell(LUA.table_from([4]), False, False)
    u = G.units[4]
    assert r.escaped and r.moved and r.locked[1] and G.moved == 2, dict(r)
    assert len(u.path.path.x) == 0 and u.path.dest.x == -30000


finish()
