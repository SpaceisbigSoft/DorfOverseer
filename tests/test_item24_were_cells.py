"""(0.105.115 item24) Werebeast cells a changed werebeast can't break.

A werebeast in its beast form is a building destroyer (DF wiki, level 2):
it breaks the door of the jail or bedroom moon_cell locked it in. Walls
and a raised drawbridge hold. Now:
  - the were_cells level (lua/ai-layouts-kinds.lua were_cells): 2x2 cells
    off a corridor, each with a 1-tile drawbridge on its doorway, a lever on
    the corridor tile in front and a bed; its saved cells (cells.were) name
    each cell's box, bridge and lever;
  - the planner (planner_threats.were_cells_rule): a werebeast citizen known
    and no such cells (or fewer than the cursed): the level, urgent; built
    levers not linked: the were_cells action links them (ai-werecells link,
    ai-gates link_lever);
  - moon_cell takes a ready were cell first and, once the cursed is alone
    inside, pulls its lever (ai-gates pull_instant) to raise the bridge; the
    release lowers it; never while anyone is on the bridge tile.

    python tests/test_item24_were_cells.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402

import hold_classes as H  # noqa: E402
import overseer  # noqa: E402
import planner_threats as PT  # noqa: E402
from planner import Memory, plan, PLANNER_CONFIG  # noqa: E402

LUA_DIR = ROOT / "lua"
CH = [{"phase": 27, "tick": 110290156}]
ROWS = [{"id": 1, "name": "Dodok", "by_syndrome": True}, {"id": 2, "name": "Uzol", "by_syndrome": True}]
RULES = {"moon_cells": True}


def rule(w, projects=None, rules=RULES):
    s = {"projects": {"open": projects or []}}
    props, notes = [], []
    rows = [x for x in w.get("list", [])]
    PT.were_cells_rule(s, PLANNER_CONFIG, w, rows, rules, props, notes)
    return props, notes


@test("a werebeast citizen and no were cells: the level, urgent; one being built: noted, none twice")
def _():
    props, _ = rule({"list": ROWS})
    assert len(props) == 1 and props[0].rule == "were_cells", props
    a = props[0].action
    assert a == {"type": "start_project", "kind": "were_cells", "cells": 3, "urgent": True}, a
    assert "drawbridge" in props[0].reason and "Dodok" in props[0].reason
    props, notes = rule({"list": ROWS}, [{"kind": "were_cells", "phase": "dig"}])
    assert not props and any("being built" in n for n in notes), (props, notes)
    assert not rule({"list": []})[0]                                    # no werebeast: none
    assert not rule({"list": ROWS}, rules={"moon_cells": False})[0]     # moon cells off: none


@test("enough cells: none; fewer than the cursed: more (never past were_cells_max)")
def _():
    assert not rule({"list": ROWS, "were_cells": {"n": 3, "ready": 3, "free": 3}})[0]
    many = [{"id": i, "name": f"W{i}"} for i in range(1, 12)]
    props, _ = rule({"list": many, "were_cells": {"n": 3}})
    assert props and props[0].action["cells"] == 8 and "3 cells" in props[0].reason, props
    props, _ = rule({"list": many + [{"id": 40 + i} for i in range(20)], "were_cells": {"n": 14}})
    assert props and props[0].action["cells"] == 2, props
    assert not rule({"list": many + [{"id": 40 + i} for i in range(20)], "were_cells": {"n": 16}})[0]


@test("built levers not linked: the were_cells action (even with the moon cells' werebeasts gone)")
def _():
    props, _ = rule({"list": [], "were_cells": {"n": 3, "unlinked": 2}})
    assert [p.action for p in props] == [{"type": "were_cells"}] and "2 werebeast cell lever" in props[0].reason
    assert not rule({"list": [], "were_cells": {"n": 3, "unlinked": 0}})[0]


@test("plan(): moon_cell's words say the drawbridge when a were cell is free; the level comes through _were")
def _():
    from test_threats import fort
    s = fort({"were": {"list": [dict(ROWS[0], cell=True)], "changes": CH, "moon_phase": 25,
                       "cells": [{"unit_id": 1}], "were_cells": {"n": 2, "ready": 2, "free": 2}}})
    props = plan(s, Memory())[0]
    c = [p for p in props if p.rule == "moon_cell" and not p.action.get("release")]
    assert c and "behind a drawbridge" in c[0].reason, c
    s = fort({"were": {"list": ROWS, "changes": CH, "moon_phase": 10}})
    props, notes = [], []
    PT._were(s, PLANNER_CONFIG, s["threats"], {"moon_cells": True}, props, notes)
    assert any(p.rule == "were_cells" and p.action.get("kind") == "were_cells" for p in props), props


@test("wiring: classes, words, catalog, dry run, modules, kinds, the start_project check, sizes")
def _():
    assert H.RULE_CLASS["were_cells"] == H.DEFENCE and H.ACTION_CLASS["were_cells"] == H.DEFENCE
    assert overseer.short({"type": "were_cells"}) == "link the werebeast cells' levers to their drawbridges"
    assert overseer.short({"type": "start_project", "kind": "were_cells"}) == "dig a new werebeast cell level"
    cat = (LUA_DIR / "ai-bridge-catalog.lua").read_text(encoding="utf-8")
    assert "were_cells = function(a) return reqscript('ai-werecells').link(a.dry_run == true) end," in cat
    assert "    'were_cells',     -- (0.105.115 item24)" in cat
    assert "    'ai-werecells',   -- (0.105.115 item24)" in (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "'were_cells'}" in (LUA_DIR / "ai-layouts.lua").read_text(encoding="utf-8")
    act = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    assert "elseif a.kind == 'were_cells' then" in act and "were_cells needs cells 1-8" in act
    pj = (LUA_DIR / "ai-builder-projects.lua").read_text(encoding="utf-8")
    assert "were = kind == 'were_cells' and L.rooms_at or nil" in pj
    assert "cavern_well or (p.kind == 'were_cells' and p.phase ~= 'cancelled')" in pj   # never dropped
    sites = (LUA_DIR / "ai-builder-sites.lua").read_text(encoding="utf-8")
    assert "were_cells = true}" in sites and "'^were%d+%((%d+)x(%d+)%)$'" in sites
    th = (LUA_DIR / "ai-threats.lua").read_text(encoding="utf-8")
    assert "out.were_cells = reqscript('ai-werecells').report(d.cells)" in th
    ta = (LUA_DIR / "ai-threats-actions.lua").read_text(encoding="utf-8")
    assert "W().set_raised(wc, true, dry_run)" in ta and "W().set_raised(wc, false, dry_run)" in ta
    assert "for id in pairs(W().piece_ids()) do out[id] = true end" in ta
    for f in ("ai-werecells.lua", "ai-threats-actions.lua", "ai-threats.lua", "ai-bridge-catalog.lua",
              "ai-bridge.lua", "ai-bridge-actions.lua", "ai-builder-projects.lua", "ai-builder-sites.lua",
              "ai-layouts.lua", "ai-layouts-kinds.lua", "ai-welfare.lua"):
        assert len((LUA_DIR / f).read_bytes().replace(b"\r", b"")) < 60_000, f
    assert (ROOT / "brain" / "planner.py").stat().st_size < 92_000


# ---- Lua (lupa: these run on the PC) -----------------------------------------------------

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None


@test("lua: the were_cells level: a bridge on each doorway, its lever in front in the corridor, a bed, rooms_at")
def _():
    need_lua()
    from lua_modules_util import module_src
    lua = LuaRuntime(unpack_returned_tuples=True)
    M = lua.eval("function(src) local env = setmetatable({}, {__index=_G}); "
                 "assert(load(src, 'ai-layouts', 't', env))(); return env end")(module_src("ai-layouts.lua"))
    for orient in (0, 2):
        L = M.make("were_cells", lua.table_from({"cells": 4, "style": lua.table_from({"orient": orient})}))
        assert L is not None
        build = [(c.x, c.y, c.text) for c in L.build.values()]
        at = {str(c.text): (c.x, c.y) for c in L.rooms_at.values()}
        bridges = [b for b in build if b[2] in ("gw(1x1)", "gx(1x1)")]
        levers = [b for b in build if b[2] == "Tl"]
        beds = [b for b in build if b[2] == "b"]
        assert len(bridges) == len(levers) == len(beds) == 4 and L.summary.cells == 4, build
        tiles = {(x, y) for x, col in L.tiles.items() for y in col.keys()}
        for i in range(1, 5):
            room = [(c.x, c.y, c.text) for c in L.rooms_at.values() if str(c.text) == f"were{i}(2x2)"]
            assert room, at
            rx, ry, _ = room[0]
            bx, by = at[f"werebridge{i}"]
            lx, ly = at[f"werelever{i}"]
            assert (bx, by) in tiles and (lx, ly) in tiles and abs(bx - lx) + abs(by - ly) == 1
            assert (bx, by, "gw(1x1)") in bridges or (bx, by, "gx(1x1)") in bridges
            cell = {(rx + dx, ry + dy) for dx in (0, 1) for dy in (0, 1)}
            assert cell <= tiles
            # the bridge touches the cell; the cell's only dug neighbours are the bridge (rock all round)
            ring = {(x + dx, y + dy) for x, y in cell for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))} - cell
            assert [t for t in ring if t in tiles] == [(bx, by)], (i, [t for t in ring if t in tiles], (bx, by))


WERE_GAME = r"""
local src = ...
local G = {tiles = {}, units = {}, pulls = 0, links = {}, linked_calls = {}, named = {}}
local e = setmetatable({G = G}, {__index = _G})
e.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
e.df = {global = {world = {units = {active = G.units}}},
        building_type = {Bridge = 'Bridge', Trap = 'Trap'}, trap_type = {Lever = 'Lever'},
        job_type = {LinkBuildingToTrigger = 'Link'}}
e.dfhack = {units = {isDead = function() return false end},
            buildings = {findAtTile = function(p) return G.tiles[p.x .. ',' .. p.y .. ',' .. p.z] end}}
local function bld(id, t) return {id = id, jobs = {}, trap_type = t == 'Trap' and 'Lever' or nil,
    gate_flags = {raised = false, raising = false, lowering = false},
    getType = function() return t end, getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end} end
G.bridge, G.lever = bld(900, 'Bridge'), bld(901, 'Trap')
G.tiles['11,13,10'] = G.bridge; G.tiles['11,14,10'] = G.lever
G.gates = {lever_links = function() return G.links end,
           pull_instant = function(id) G.pulls = G.pulls + 1; if not G.stuck then G.bridge.gate_flags.raised = not G.bridge.gate_flags.raised end return true end,
           link_lever = function(l, t, dry) table.insert(G.linked_calls, {l, t, dry}); return {ok = true} end,
           name_at = function(pos, name) G.named[pos.x .. ',' .. pos.y] = name end}
e.reqscript = function(n) if n == 'ai-gates' then return G.gates end error('reqscript ' .. tostring(n)) end
assert(load(src, 'ai-werecells', 't', e))()
e.projects = function() return {list = {{id = 7, kind = 'were_cells', phase = 'done', z = 10, anchor = {x = 10, y = 10},
    cells = {were = {{x = 0, y = 1, text = 'were1(2x2)'}, {x = 1, y = 3, text = 'werebridge1'},
                     {x = 1, y = 4, text = 'werelever1'}, {x = 9, y = 9, text = 'were2(2x2)'}}}},
    {id = 8, kind = 'were_cells', phase = 'cancelled', z = 10, anchor = {x = 0, y = 0},
     cells = {were = {{x = 0, y = 1, text = 'were1(2x2)'}, {x = 1, y = 3, text = 'werebridge1'}, {x = 1, y = 4, text = 'werelever1'}}}}}} end
return e
"""


def were_env():
    from lua_modules_util import module_src
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua, lua.execute(WERE_GAME, module_src("ai-werecells.lua"))


@test("lua: ai-werecells finds the cells (a half cell and a cancelled level left out), links, raises and lowers")
def _():
    need_lua()
    lua, E = were_env()
    G = E.G
    cs = E.cells()
    assert len(cs) == 1 and cs[1].key == "were:7:1", [c.key for c in cs.values()]
    c = cs[1]
    assert (c.x1, c.y1, c.x2, c.y2, c.bridge.x, c.bridge.y, c.lever.y) == (10, 11, 11, 12, 11, 13, 14)
    st = E.cell_state(c)
    assert st.built and not st.linked and st.bridge_id == 900 and st.lever_id == 901
    assert not E.ready(c)[0]                                     # (ready, state)
    ok, why = E.set_raised(c, True, False)
    assert not ok and "not linked" in why and G.pulls == 0
    rep = E.report(None)
    assert rep.n == 1 and rep.built == 1 and rep.unlinked == 1 and rep.free == 0, dict(rep)
    r = E.link(False)
    assert r.ok and len(G.linked_calls) == 1 and G.linked_calls[1][1] == 901 and G.linked_calls[1][2] == 900
    assert G.named["11,14"] == "AI were cell lever" and G.named["11,13"] == "AI were cell"
    lua.execute("local E = ...; E.G.links[900] = {901}", E)
    assert E.ready(c)[0] and E.link(False).nothing_to_do
    rep = E.report(lua.table_from({"5": lua.table_from({"zone": "were:7:1"})}))
    assert rep.ready == 1 and rep.free == 0 and rep.rows[1].unit_id == 5, dict(rep)
    # anyone on the bridge tile: never raised (it would fling them)
    lua.execute("local E = ...; E.G.units[1] = {pos = {x = 11, y = 13, z = 10}}", E)
    ok, why = E.set_raised(c, True, False)
    assert not ok and "fling" in why and G.pulls == 0
    lua.execute("local E = ...; E.G.units[1] = nil", E)
    ok, _ = E.set_raised(c, True, True)
    assert ok and G.pulls == 0                                   # a dry run pulls nothing
    ok, _ = E.set_raised(c, True, False)
    assert ok and G.pulls == 1 and E.cell_state(c).raised and E.piece_ids()[900] and E.piece_ids()[901]
    ok, why = E.set_raised(c, True, False)
    assert ok and why == "already" and G.pulls == 1
    # (R32 a) a lever out of step: one pull per call, never two (a second could
    # send a bridge on its way straight back); the next call pulls again
    lua.execute("local E = ...; E.G.stuck = true", E)
    ok, why = E.set_raised(c, False, False)
    assert not ok and "out of step" in why and "next call" in why and G.pulls == 2, why
    ok, why = E.set_raised(c, False, False)
    assert not ok and G.pulls == 3
    lua.execute("local E = ...; E.G.stuck = false", E)
    ok, _ = E.set_raised(c, False, False)
    assert ok and not E.cell_state(c).raised and G.pulls == 4


# (R32 a) E, 26 Nov 04:08-09:14: three passers-by killed by the were cells' bridges
# seconds after moon_cell moved them (the tile empty when it looked: DF moves the
# bridge over the next ticks). The fake's cell: box x10-11 y11-12, bridge 11,13, lever 11,14.
OWN = r"""
local E = ...
E.dfhack.units.isCitizen = function(u) return u.citizen == true end
E.dfhack.units.isDanger = function(u) return u.danger == true end
E.df.global.plotinfo = {civ_id = 5}
E.G.links[900] = {901}
E.put = function(u) E.G.units[1] = u end
E.clear = function() E.G.units[1] = nil end
"""


def own_env():
    lua, E = were_env()
    lua.execute(OWN, E)
    return lua, E, E.cells()[1]


def put(lua, E, **u):
    path = u.pop("path", None)
    dest = u.pop("dest", None)
    x, y, z = u.pop("at")
    code = ("local E, x, y, z, cit, civ, dg = ...; E.put({id = 33, pos = {x = x, y = y, z = z}, citizen = cit, civ_id = civ, "
            "danger = dg, path = {path = {x = {}, y = {}, z = {}}, dest = {x = -30000, y = -30000, z = -30000}}})")
    lua.execute(code, E, x, y, z, u.get("citizen", False), u.get("civ", 9), u.get("danger", False))
    if path:
        for i, (px, py) in enumerate(path, 1):
            lua.execute("local E, i, x, y = ...; local p = E.G.units[1].path.path; p.x[i] = x; p.y[i] = y; p.z[i] = 10",
                        E, i, px, py)
    if dest:
        lua.execute("local E, x, y = ...; E.G.units[1].path.dest = {x = x, y = y, z = 10}", E, dest[0], dest[1])


@test("lua: (R32 a) a were cell's bridge never moves with one of the fort's own next to it or about to cross it")
def _():
    need_lua()
    lua, E, c = own_env()
    G = E.G
    waits = [  # (unit, words): each one makes the raise wait, no pull
        (dict(at=(11, 14, 10), citizen=True), "next to"),          # on the lever tile in front
        (dict(at=(12, 14, 10), citizen=True), "next to"),          # a diagonal
        (dict(at=(10, 13, 10), civ=5), "next to"),                 # a tame animal (the fort's civ)
        (dict(at=(12, 12, 10), civ=5), "next to"),                 # beside the cell, outside its box
        (dict(at=(11, 18, 10), citizen=True, path=[(11, 17), (11, 16), (11, 15), (11, 14), (11, 13)]), "on its way"),
        (dict(at=(20, 20, 10), citizen=True, dest=(11, 13)), "on its way"),
    ]
    for u, words in waits:
        put(lua, E, **u)
        for up in (True, False):
            lua.execute("local E, r = ...; E.G.bridge.gate_flags.raised = r", E, not up)
            ok, why = E.set_raised(c, up, False)
            assert not ok and words in why and "waits" in why and G.pulls == 0, (u, up, why)
            assert ("fling" if up else "crush") in why, why
            ok, why = E.set_raised(c, up, True)
            assert not ok and G.pulls == 0, (u, "dry run", why)     # a dry run says the same
    lua.execute("local E = ...; E.G.bridge.gate_flags.raised = false", E)
    fine = [  # none of these hold it
        dict(at=(11, 12, 10), citizen=True),                       # the cell's werebeast inside, by the bridge
        dict(at=(11, 14, 10), citizen=True, danger=True),          # a citizen in a rage (a danger)
        dict(at=(11, 14, 10), civ=9),                              # a stranger beside it
        dict(at=(11, 14, 9), citizen=True),                        # a level down
        dict(at=(11, 16, 10), citizen=True),                       # two tiles off
        dict(at=(11, 20, 10), citizen=True, path=[(11, 19), (11, 18), (11, 17), (11, 16), (11, 15), (11, 14), (11, 13)]),
    ]
    for u in fine:
        put(lua, E, **u)
        lua.execute("local E = ...; E.G.bridge.gate_flags.raised = false", E)
        n = G.pulls
        ok, why = E.set_raised(c, True, False)
        assert ok and G.pulls == n + 1, (u, why)
    # the units can't be read: it waits
    lua.execute("local E = ...; E.G.bridge.gate_flags.raised = false; E.put({id = 1, citizen = true})", E)
    n = G.pulls
    ok, why = E.set_raised(c, True, False)
    assert not ok and G.pulls == n, why
    lua.execute("local E = ...; E.clear()", E)
    # a bridge on its way: 'raising', never a second pull
    lua.execute("local E = ...; local f = E.G.bridge.gate_flags; f.raised = false; f.raising = true", E)
    n = G.pulls
    ok, why = E.set_raised(c, True, False)
    assert ok and why == "raising" and G.pulls == n, why
    ok, why = E.set_raised(c, False, False)
    assert not ok and "moving" in why and G.pulls == n, why
    lua.execute("local E = ...; local f = E.G.bridge.gate_flags; f.raised = true; f.raising = false", E)
    ok, why = E.set_raised(c, True, False)
    assert ok and why == "already" and G.pulls == n


@test("lua: moon_cell takes a ready were cell first, raises its bridge once alone inside, lowers it at the release")
def _():
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
    G = E.G
    LUA.execute("""local E = ...; local G = E.G
        local W = {st = {built = true, linked = true, raised = false, moving = false}, sets = {}}
        W.cell = {key = 'were:7:1', x1 = 20, y1 = 20, x2 = 21, y2 = 21, z = 10,
                  bridge = {x = 20, y = 22, z = 10}, lever = {x = 20, y = 23, z = 10}}
        W.cells = function() return {W.cell} end
        W.find = function(k) if k == W.cell.key then return W.cell end end
        W.zone_of = function(c) return {id = c.key, x1 = c.x1, y1 = c.y1, x2 = c.x2, y2 = c.y2, z = c.z, were = true} end
        W.lever_links = function() return {} end
        W.ready = function() return W.st.built and W.st.linked and not W.st.raised end
        W.cell_state = function() return W.st end
        W.set_raised = function(c, up, dry)
            if W.occupied then return false, 'someone is on the cell\\'s bridge tile' end
            if W.rising and not dry then return true, 'raising' end
            if not dry then W.st.raised = up; table.insert(W.sets, up) end
            return true
        end
        W.piece_ids = function() return {[900] = true, [901] = true} end
        G.W = W
        G.units[4] = {id = 4, name = 'Dodok', race = 1, enemy = {normal_race = -1}, pos = {x = 40, y = 40, z = 10}}""", E)
    r = E.moon_cell(LUA.table_from([4]), False, False)
    st = G.saved["ai-overseer/threats"]
    c = st.cells["4"]
    assert c.zone == "were:7:1" and c.kind == "were" and not c.locked, dict(r)    # the were cell, not jail 77
    # (R32 a) moved in, the bridge still rising (DF moves it over the next ticks): not a
    # wall yet, so neither locked nor "not sealed"; the next call finds it up and locks
    LUA.execute("local E = ...; E.G.W.rising = true", E)
    r = E.moon_cell(LUA.table_from([4]), False, False, None, LUA.table_from({"move_in": True}))
    c = G.saved["ai-overseer/threats"].cells["4"]
    assert G.moved == 1 and not c.locked and r.raising and not r.not_sealed and len(r.waiting) == 1, dict(r)
    LUA.execute("local E = ...; E.G.W.rising = false", E)
    # alone inside -> the bridge raised, locked
    r = E.moon_cell(LUA.table_from([4]), False, False, None, LUA.table_from({"move_in": True}))
    c = G.saved["ai-overseer/threats"].cells["4"]
    W = G.W
    assert G.moved == 1 and c.locked and W.st.raised and list(W.sets.values()) == [True], dict(r)
    assert E.cell_doors_held(c) and E.claimed_doors()[900]
    # lowered by someone else: read not held, raised again
    LUA.execute("local E = ...; E.G.W.st.raised = false", E)
    assert not E.cell_doors_held(c)
    r = E.moon_cell(LUA.table_from([4]), False, False)
    assert r.relock and G.W.st.raised, dict(r)
    # the release: someone on the bridge tile -> kept, said; then lowered and let out
    LUA.execute("local E = ...; E.G.W.occupied = true", E)
    r = E.moon_cell(LUA.table_from([]), True, False)
    assert G.saved["ai-overseer/threats"].cells["4"] is not None and r.errors and "stays up" in r.errors[1], dict(r)
    LUA.execute("local E = ...; E.G.W.occupied = false", E)
    r = E.moon_cell(LUA.table_from([]), True, False)
    assert G.saved["ai-overseer/threats"].cells["4"] is None and not G.W.st.raised and len(r.released) == 1, dict(r)


finish()
