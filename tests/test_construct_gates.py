"""0.105.30 construction, group G2 (gates and safety), in a real Lua engine
with stub DFHack (pip install lupa):
- the shelter leaves out the roofed surface (lua/ai-society.lua fill_shelter),
  and still finds room in a fort near the surface;
- the War-hold's wing walls (lua/ai-gates.lua plan_wings / build_wings);
- the `sealed` gate style for small cavern openings (plan_sealed);
- soil floors finished in halls (lua/ai-builder-rooms.lua floor_soil_rooms).

    python tests/test_construct_gates.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from lua_modules_util import module_src  # noqa: E402
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)


# --- 1. the shelter and the roofed surface -----------------------------------------
#
# A fort two blocks wide (x96-127, y144-159) on levels 160-180; citizens on
# z170, a stockpile on z162: the shelter's levels are 160-172 (13 x 512 tiles).
# `rule(x, y, z)` gives each tile's (subterranean, light); subterranean nil
# leaves the field out (an old fake, or a DFHack that can't read it).
SHELTER_FAKE = r"""
local src, ncit, rule, entrance = ...
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end})
end
local set = {}
local blocks = {}
for z = 160, 180 do
    for _, bx in ipairs({96, 112}) do
        local des, tt = {}, {}
        for x = 0, 15 do des[x], tt[x] = {}, {}
            for y = 0, 15 do
                local d = {hidden = false, outside = false, flow_size = 0}
                local sub, light = rule(bx + x, 144 + y, z)
                if sub ~= nil then d.subterranean = sub end
                if light ~= nil then d.light = light end
                des[x][y] = d
                tt[x][y] = 1
            end
        end
        table.insert(blocks, {map_pos = {x = bx, y = 144, z = z}, designation = des, tiletype = tt})
    end
end
local shelter = {id = 4, name = 'AI shelter'}
local gates = {scanned = true, closed = {}, entrances = {}}
if entrance then
    gates.entrances = {{id = 1, kind = 'surface', x = 108, y = 149, z = 170, sealed = false, equipment = {}}}
end
local cits = {}
for i = 1, ncit do cits[i] = {pos = {z = 170}} end
local env = setmetatable({}, {__index = _G})
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
env.df = {global = {world = {map = {map_blocks = blocks},
                             buildings = {other = {STOCKPILE = vec({{z = 162}}), WELL = vec({})}}},
                    plotinfo = {burrows = {list = vec({shelter}), next_id = 5},
                                alerts = {list = vec({{}, {burrows = vec({4})}}), next_id = 3}}},
          tiletype = {attrs = {[1] = {shape = 1}}},
          tiletype_shape = {[1] = 'FLOOR'},
          building = {find = function() return nil end}}
env.require = function(name) if name == 'utils' then return {insert_sorted = function() end} end return require(name) end
env.reqscript = function(name)
    if name == 'ai-gates' then return {GATES = gates} end
    error('no ' .. name)
end
env.dfhack = {units = {getCitizens = function() return cits end},
              maps = {getTileType = function() return nil end},
              persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end},
              burrows = {setAssignedBlockTile = function(b, block, x, y, on)
                             set[(block.map_pos.x + x) .. ',' .. (block.map_pos.y + y) .. ',' .. block.map_pos.z] = on end,
                         clearTiles = function(b) for k in pairs(set) do set[k] = nil end end}}
assert(load(src, 'ai-society', 't', env))()
return env, set
"""

ALL = 13 * 512


def shelter_world(rule_src, ncit=2, entrance=False):
    lua = LuaRuntime(unpack_returned_tuples=True)
    rule = lua.eval(rule_src)
    env, got = lua.execute(SHELTER_FAKE, module_src("ai-society.lua"), ncit, rule, entrance)
    return lua, env, got


# a keep's roofed court on the level above the fort's top floor... here, on
# z170 at x113-120 y146-151 (48 tiles): inside, sunlit, not subterranean
KEEP = """function(x, y, z)
    if z == 170 and x >= 113 and x <= 120 and y >= 146 and y <= 151 then return false, true end
    return true, false
end"""


@test("shelter: a roofed keep (inside, not subterranean) is never shelter; the rest of the fort is, as before")
def _():
    lua, env, got = shelter_world(KEEP)
    r = env.refresh_shelter()
    assert r.tiles == ALL - 48 and r.surface_out == 48 and not r.surface_back, dict(r)
    for x in range(113, 121):
        for y in range(146, 152):
            assert not got[f"{x},{y},170"], (x, y)
    assert got["112,146,170"] and got["113,146,169"] and got["121,151,170"]
    assert not r.fallback and not r.surface_note
    # setup_shelter says the same
    lua.execute("local df = ...; df.global.plotinfo.alerts.list[1].burrows = setmetatable({}, {__len = function() return 0 end})",
                env.df)
    r2 = env.setup_shelter()
    assert r2.ok and r2.tiles == ALL - 48 and r2.surface_out == 48, dict(r2)


@test("shelter: the shade of a tree and an unroofed rule-less fake: the flag missing counts as underground")
def _():
    lua, env, got = shelter_world("function() return nil, nil end")
    r = env.refresh_shelter()
    assert r.tiles == ALL and not r.surface_out, dict(r)
    # the tree's crown over z172's corner: not outside, not subterranean, light
    lua, env, got = shelter_world("""function(x, y, z)
        if z == 172 and x < 100 and y < 148 then return false, true end
        return true, false end""")
    r = env.refresh_shelter()
    assert r.tiles == ALL - 16 and r.surface_out == 16 and not got["96,144,172"], dict(r)


# A fort near the surface: DF reads its two top levels (171-172) and half of
# z170 as not subterranean (say, a hill the flag doesn't cover); only 10
# levels under rock remain. Dark ones (no sunlight) are the fort itself.
NEAR = """function(x, y, z)
    if z >= 171 then return false, x >= 112 end           -- the west half dark
    if z == 170 and y >= 152 then return false, false end
    if z <= 169 then return true, false end
    return true, false
end"""


@test("shelter near the surface: enough tiles under rock: the not-subterranean ones stay out")
def _():
    lua, env, got = shelter_world(NEAR, ncit=100)
    r = env.refresh_shelter()
    under = 10 * 512 + 512 - 8 * 32          # z160-169, and z170 but rows y152-159
    assert r.tiles == under and r.surface_out == 2 * 512 + 8 * 32 and not r.surface_back, dict(r)


@test("shelter near the surface: too few under rock: the not-subterranean tiles come back, dark first, said so")
def _():
    lua, env, got = shelter_world(NEAR, ncit=2900)          # needs 5800 tiles: 424 back, all dark
    r = env.refresh_shelter()
    under = 10 * 512 + 512 - 8 * 32
    assert r.tiles == 5800 and r.surface_back == 5800 - under, dict(r)
    lit = sum(1 for z in (171, 172) for x in range(112, 128) for y in range(144, 160) if got[f"{x},{y},{z}"])
    assert lit == 0, lit
    lua, env, got = shelter_world(NEAR, ncit=3200)          # needs 6400: every dark one, then sunlit
    r = env.refresh_shelter()
    assert r.tiles == 6400 and r.surface_back == 6400 - under, dict(r)
    assert r.surface_out == 2 * 512 + 8 * 32 - r.surface_back
    assert "taken back" in r.surface_note and "dark" in r.surface_note, r.surface_note
    # the dark ones (west half of z171-172, z170's south rows: 768 tiles) all
    # came back before any sunlit one
    dark = [f"{x},{y},{z}" for z in (171, 172) for x in range(96, 112) for y in range(144, 160)] \
        + [f"{x},{y},170" for x in range(96, 128) for y in range(152, 160)]
    assert all(got[k] for k in dark), sum(1 for k in dark if not got[k])
    lit = sum(1 for z in (171, 172) for x in range(112, 128) for y in range(144, 160) if got[f"{x},{y},{z}"])
    assert lit == r.surface_back - len(dark), (lit, r.surface_back)


@test("shelter near the surface: a fort DF reads all not subterranean still gets its shelter (never empty)")
def _():
    lua, env, got = shelter_world("function() return false, false end", ncit=10)
    r = env.refresh_shelter()
    assert r.tiles == 50 and r.surface_back == 50 and r.surface_out == ALL - 50, dict(r)
    lua.execute("local df = ...; df.global.plotinfo.alerts.list[1].burrows = setmetatable({}, {__len = function() return 0 end})",
                env.df)
    r2 = env.setup_shelter()
    assert r2.ok and r2.tiles == 50, dict(r2)


@test("shelter: an open entrance's margin first, then the roofed surface: the surface comes back last, farthest first")
def _():
    lua, env, got = shelter_world(KEEP, ncit=2400, entrance=True)       # needs 4800
    r = env.refresh_shelter()
    # the entrance (x108 y149 z170) holds x96-120 on z168-172 (2000 tiles less
    # the 48 keep tiles: those count as surface); all of it comes back first
    assert r.fallback and r.tiles == 4800, dict(r)
    assert not r.surface_back and r.surface_out == 48, dict(r)
    assert not got["113,146,170"]


# --- 2. wing walls and the sealed style (ai-gates) -----------------------------------

GATES_HARNESS = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-gates', 't', env))()
local W = {}
-- '#' rock, '.' inside floor, 'o' outside floor, 'c' cavern floor, 's' stairs
-- (inside), 't' the top of a stair shaft (outside), 'w' water outside,
-- 'W' a built wall (a construction), 'b' a building on outside ground
function env.tile(x, y, z)
  local lvl = W.map[z]; if not lvl then return nil end
  local row = lvl[y]; if not row then return nil end
  local ch = row:sub(x + 1, x + 1)
  if ch == '' then return nil end
  if ch == '#' then return {walk = false, shape = 'WALL', material = 'STONE'} end
  if ch == 'W' then return {walk = false, shape = 'WALL', material = 'CONSTRUCTION'} end
  return {walk = true, shape = (ch == 's' or ch == 't') and 'STAIR_UPDOWN' or 'FLOOR',
          outside = ch == 'o' or ch == 't' or ch == 'w' or ch == 'b', feature = ch == 'c',
          liquid = ch == 'w', depth = ch == 'w' and 4 or 0, occupied = ch == 'b',
          material = ch == 'w' and 'POOL' or 'STONE'}
end
W.size = {40, 19}
function env.map_size() return W.size[1], W.size[2], 2 end
W.buildings = {}
function env.gate_buildings() return W.buildings end
function env.building_at() return nil end
W.keepouts = {}
function env.wing_keepouts(z) return W.keepouts end
return env, W
"""

GL = LuaRuntime(unpack_returned_tuples=True)
M, GW = GL.execute(GATES_HARNESS, module_src("ai-gates.lua"))


def set_map(levels, width=40, height=19):
    m = GL.table()
    for z, rows in levels.items():
        lvl = GL.table()
        for y, r in enumerate(rows):
            lvl[y] = r
        m[z] = lvl
    GW.map = m
    GW.size = GL.table_from({1: width, 2: height})
    GW.keepouts = GL.table()


def shaft_world(surface_rows=None, width=40):
    """The founding stair's top 't' on the surface (z1) at x10 y8; the fort below (z0)."""
    surface = surface_rows or (["o" * width] * 8 + ["o" * 10 + "t" + "o" * (width - 11)] + ["o" * width] * 10)
    below = (["#" * width] * 8 + ["#" * 10 + "s" + "." * (width - 11)] + ["#" * 10 + "." * (width - 10)] * 4
             + ["#" * width] * 6)
    set_map({0: below, 1: surface}, width)
    return GL.table_from({i + 1: GL.table_from({"x": 30 + i, "y": 10, "z": 0}) for i in range(3)})


HATCH = {"id": 7, "kind": "hatch", "x1": 10, "y1": 8, "x2": 10, "y2": 8, "z": 1, "name": ""}
BRIDGE = {"id": 40, "kind": "bridge", "x1": 10, "y1": 3, "x2": 10, "y2": 3, "z": 1, "name": "AI gatehouse bridge"}


def gatehouse_entrance(s0, bridge=True):
    b = {1: GL.table_from(HATCH)}
    if bridge:
        b[2] = GL.table_from(BRIDGE)
    GW.buildings = GL.table_from(b)
    es, _, _ = M.find_entrances(s0, GW.buildings)
    e = es[1]
    e.id = 1
    M.GATES = GL.table_from({"scanned": True, "entrances": GL.table_from({1: e})})
    return e


def unk(k):
    return (k % 4096, k // 4096 % 4096, k // (4096 * 4096))


def wings(e):
    r = M.plan_wings(e)
    return r if not isinstance(r, tuple) else r


def arms_of(plan):
    return [sorted(unk(a[i]) for i in range(1, len(a) + 1)) for a in (plan.arms[j] for j in range(1, len(plan.arms) + 1))]


@test("wings: a standing gatehouse gets two arms of 5 from its front corners, across the corridor's line")
def _():
    s0 = shaft_world()
    e = gatehouse_entrance(s0)
    assert e.gatehouse == "standing" and (e.gatehouse_bridge.x, e.gatehouse_bridge.y) == (10, 3), e.gatehouse
    plan = M.plan_wings(e)
    plan = plan[0] if isinstance(plan, tuple) else plan
    arms = arms_of(plan)
    # the corridor runs north (bridge at y3); the corners at x9 and x11 y3: the arms go west and east on y3
    assert arms == [[(x, 3, 1) for x in range(4, 9)], [(x, 3, 1) for x in range(12, 17)]], arms
    assert len(plan.walls) == 10


@test("wings: build places 10 walls and records them; a dry run places nothing; no gatehouse: refused")
def _():
    s0 = shaft_world()
    e = gatehouse_entrance(s0)
    placed = []
    M.place_hook = lambda text, pos: placed.append((text, pos.x, pos.y, pos.z)) or True
    try:
        r = M.build_wings(1, True)
        assert r.ok and r.dry_run and r.walls == 10 and r.blocks_needed == 10 and not placed, dict(r)
        r = M.build_wings(1, False)
        assert r.ok and r.walls == 10 and len(r.pieces) == 10, dict(r)
        assert all(t[0] == "Cw" and t[2] == 3 and t[3] == 1 for t in placed), placed
        assert "4,3,1" in [r.pieces[i] for i in range(1, 11)]
        assert M.build_wings(9, False).rejected
        e2 = gatehouse_entrance(s0, bridge=False)
        assert e2.gatehouse == "possible"
        r = M.build_wings(1, False)
        assert r.rejected and "gatehouse" in r.error, dict(r)
    finally:
        M.place_hook = None
        M.GATES = GL.table_from({"scanned": False})


@test("wings: an arm stops before a pasture (3 tiles off), and is dropped when under 3 long")
def _():
    s0 = shaft_world()
    e = gatehouse_entrance(s0)
    GW.keepouts = GL.table_from({1: GL.table_from({"x1": 19, "y1": 2, "x2": 21, "y2": 4, "kind": "pasture"})})
    plan = M.plan_wings(e)
    plan = plan[0] if isinstance(plan, tuple) else plan
    assert [len(a) for a in arms_of(plan)] == [5, 4], arms_of(plan)          # east stops at x15
    GW.keepouts = GL.table_from({1: GL.table_from({"x1": 17, "y1": 3, "x2": 18, "y2": 3, "kind": "pasture"})})
    plan = M.plan_wings(e)
    plan = plan[0] if isinstance(plan, tuple) else plan
    assert arms_of(plan) == [[(x, 3, 1) for x in range(4, 9)]] and "second arm stops after 2" in plan.dropped[1], \
        (arms_of(plan), plan.dropped[1])
    # a zone on the tile itself, a farm or a depot near: the same
    GW.keepouts = GL.table_from({1: GL.table_from({"x1": 6, "y1": 3, "x2": 6, "y2": 3, "kind": "zone"}),
                                 2: GL.table_from({"x1": 14, "y1": 6, "x2": 14, "y2": 6, "kind": "depot"})})
    r = M.plan_wings(e)
    assert r[0] is None and "no room" in r[1], r


@test("wings: water within 2 stops an arm; ground taken, or open space, too")
def _():
    rows = ["o" * 40] * 8 + ["o" * 10 + "t" + "o" * 29] + ["o" * 40] * 10
    rows[1] = "o" * 6 + "w" + "o" * 33                    # a pool 2 north of x6 y3
    rows[3] = "o" * 13 + "b" + "o" * 26                   # a building at x13 y3
    s0 = shaft_world(surface_rows=rows)
    e = gatehouse_entrance(s0)
    r = M.plan_wings(e)
    assert r[0] is None and "water near" in r[1] and "not open ground" in r[1], r


@test("wings: a cliff the arms would close into a courtyard: refused, nothing placed")
def _():
    rows = []
    for y in range(19):
        r = list("o" * 40)
        if 3 <= y <= 10:
            r[3] = "#"
            r[17] = "#"
        if y == 10:
            for x in range(3, 18):
                r[x] = "#"
        rows.append("".join(r))
    rows[8] = rows[8][:10] + "t" + rows[8][11:]
    s0 = shaft_world(surface_rows=rows)
    e = gatehouse_entrance(s0)
    assert e.gatehouse == "standing"
    r = M.plan_wings(e)
    assert r[0] is None and "courtyard" in r[1], r
    placed = []
    M.place_hook = lambda text, pos: placed.append(text) or True
    try:
        r = M.build_wings(1, False)
        assert r.rejected and not placed, dict(r)
    finally:
        M.place_hook = None
        M.GATES = GL.table_from({"scanned": False})
    # only one side closed: that arm dropped, the other kept
    rows2 = []
    for y in range(19):
        r = list("o" * 40)
        if 3 <= y <= 10:
            r[3] = "#"
        if y == 10:
            for x in range(3, 10):
                r[x] = "#"
        rows2.append("".join(r))
    rows2[8] = rows2[8][:10] + "t" + rows2[8][11:]
    s0 = shaft_world(surface_rows=rows2)
    e = gatehouse_entrance(s0)
    plan = M.plan_wings(e)
    plan = plan[0] if isinstance(plan, tuple) else plan
    assert arms_of(plan) == [[(x, 3, 1) for x in range(12, 17)]], arms_of(plan)
    assert any("courtyard" in plan.dropped[i] for i in range(1, len(plan.dropped) + 1))


@test("wings: built already (constructions at both corners): refused, said so")
def _():
    rows = ["o" * 40] * 8 + ["o" * 10 + "t" + "o" * 29] + ["o" * 40] * 10
    rows[3] = "o" * 4 + "WWWWW" + "o" * 3 + "WWWWW" + "o" * 23
    s0 = shaft_world(surface_rows=rows)
    e = gatehouse_entrance(s0)
    r = M.plan_wings(e)
    assert r[0] is None and "stand there already" in r[1], r


# The sealed style. One level: the fort (x1-14) and a cavern (x16-28)
# through a gap in the rock wall at x15, `gap` tiles wide from y5.
def cavern_world(gap):
    rows = []
    for y in range(19):
        if y in (0, 18):
            rows.append("#" * 30)
            continue
        wall = "." if 5 <= y < 5 + gap else "#"
        rows.append("#" + "." * 14 + wall + "c" * 13 + "#")
    set_map({0: rows}, 30, 19)
    starts = GL.table_from({1: GL.table_from({"x": 3, "y": 9, "z": 0})})
    es, _, _ = M.find_entrances(starts, GL.table())
    cav = [es[i] for i in range(1, len(es) + 1) if es[i].kind == "cavern"]
    assert len(cav) == 1, [es[i].kind for i in range(1, len(es) + 1)]
    cav[0].id = 1
    M.GATES = GL.table_from({"scanned": True, "entrances": GL.table_from({1: cav[0]})})
    return cav[0], starts


def no_uses():
    M.sealed_layer_use = lambda e: None
    M.citizens_beyond = lambda e: 0


@test("sealed: a cavern opening up to 3 wide is walled whole, no door; fortify places and records the walls")
def _():
    real = (M.sealed_layer_use, M.citizens_beyond)
    no_uses()
    try:
        e, starts = cavern_world(3)
        plan = M.plan_gate(e, "sealed", starts)
        plan = plan[0] if isinstance(plan, tuple) else plan
        assert plan and plan.sealed and len(plan.walls) == 3 and len(plan.doors) == 0, plan
        assert len(plan.inner) == 0 and len(plan.support) == 0
        placed = []
        M.place_hook = lambda text, pos: placed.append((text, pos.x, pos.y)) or True
        M.stockpiles_in = lambda lst: GL.table()
        M.doors_in = lambda lst: GL.table()
        try:
            r = M.fortify(1, "sealed", starts)
            assert r.ok and r.walls == 3 and r.doors == 0 and r.style == "sealed" and len(r.pieces) == 3, dict(r)
            assert sorted(placed) == [("Cw", 15, 5), ("Cw", 15, 6), ("Cw", 15, 7)], placed
        finally:
            M.place_hook = None
        assert M.GAP.sealed == 0
    finally:
        M.sealed_layer_use, M.citizens_beyond = real
        M.GATES = GL.table_from({"scanned": False})


@test("sealed: refused wider than 3, with a citizen beyond, with a cavern well on the layer, on the surface")
def _():
    real = (M.sealed_layer_use, M.citizens_beyond)
    no_uses()
    try:
        e, starts = cavern_world(4)
        r = M.plan_gate(e, "sealed", starts)
        assert r[0] is None and "4 wide" in r[1], r
        e, starts = cavern_world(2)
        M.citizens_beyond = lambda e: 1
        r = M.plan_gate(e, "sealed", starts)
        assert r[0] is None and "1 citizen beyond" in r[1], r
        M.citizens_beyond = lambda e: 0
        M.sealed_layer_use = lambda e: "cavern well 12 draws on that cavern"
        r = M.plan_gate(e, "sealed", starts)
        assert r[0] is None and "cavern well 12" in r[1], r
        M.sealed_layer_use = lambda e: None
        e.kind = "surface"
        r = M.plan_gate(e, "sealed", starts)
        assert r[0] is None and "cavern opening only" in r[1], r
    finally:
        M.sealed_layer_use, M.citizens_beyond = real
        M.GATES = GL.table_from({"scanned": False})


@test("sealed: with no DFHack to read the layer or the citizens, it is refused (never walled blind)")
def _():
    e, starts = cavern_world(1)
    r = M.plan_gate(e, "sealed", starts)
    assert r[0] is None and ("could not" in r[1]), r
    # the other styles are untouched by the new one
    r = M.plan_gate(e, "narrow", starts)
    r = r[0] if isinstance(r, tuple) else r
    assert r and len(r.doors) == 1, r
    M.GATES = GL.table_from({"scanned": False})


@test("sealed: the real layer check: a cavern well or a cistern on the same cavern layer, read from the blocks")
def _():
    e, starts = cavern_world(1)
    GL.execute("""local M = ...
        M.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
        M.dfhack = {maps = {getTileBlock = function(p) return {global_feature = (p.x >= 16) and 3 or -1} end}}
        M._wells, M._cist = {}, nil
        M.reqscript = function(name)
            if name == 'ai-builder' then
                return {well_lids = function() return M._wells end, cistern_data = function() return M._cist end}
            end
            error('no ' .. name)
        end""", M)
    try:
        assert M.sealed_layer_use(e) is None
        GL.execute("""local M = ...; M._wells = {{project_id = 12, shaft_hatch = {x = 20, y = 9, z = 0}}}""", M)
        assert "cavern well 12" in M.sealed_layer_use(e)
        GL.execute("""local M = ...; M._wells = {{project_id = 12, shaft_hatch = {x = 3, y = 9, z = 0}}}""", M)
        assert M.sealed_layer_use(e) is None                 # another layer (not the cavern's)
        GL.execute("""local M = ...; M._cist = {plan = {source = 'cavern lake', water = {x = 25, y = 9, z = 0}}}""", M)
        assert "cistern" in M.sealed_layer_use(e)
    finally:
        GL.execute("local M = ...; M.dfhack = nil; M.reqscript = nil; M.xyz2pos = nil", M)
        M.GATES = GL.table_from({"scanned": False})


# --- 3. soil floors (ai-builder-rooms) on test_builder's fake fort -------------------

_tree = ast.parse((ROOT / "tests" / "test_builder.py").read_text(encoding="utf-8"))
BUILDER_HARNESS = next(n.value.value for n in _tree.body
                       if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "HARNESS")
BL = LuaRuntime(unpack_returned_tuples=True)
BL.globals().LUA_DIR = str(ROOT / "lua")
B, BW = BL.execute(BUILDER_HARNESS, (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8"),
                   (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8"))


def projects(*ps):
    BW.reset()
    data = BL.table_from({"next_id": len(ps) + 1, "list": BL.table_from({i + 1: p for i, p in enumerate(ps)})})
    BW.persist[B.PROJECTS_KEY] = data


def proj(id_, kind, phase, z=71):
    # a 6x4 hall: tiles x42-47 y56-59 (anchor x40 y55, dig cell at +2,+1)
    return BL.table_from({"id": id_, "kind": kind, "phase": phase, "z": z,
                          "anchor": BL.table_from({"x": 40, "y": 55}),
                          "cells": BL.table_from({"dig": BL.table_from({1: BL.table_from({"x": 2, "y": 1, "text": "d(6x4)"})})})})


def soil(x1, y1, x2, y2, z, **extra):
    for x in range(x1, x2 + 1):
        for y in range(y1, y2 + 1):
            BW.set(x, y, z, BL.table_from({"shape": "FLOOR", "material": "SOIL", **extra}))


def floors_placed():
    return sorted((c.x, c.y, c.z) for c in BW.placed.values() if c.mode == "build" and c.text == "Cf")


@test("soil floors: a finished dining hall with a soil corner floors only those tiles, recorded; a dry run places none")
def _():
    projects(proj(1, "dining", "done"))
    soil(42, 56, 44, 57, 71)                              # 6 soil tiles in the hall's corner
    soil(50, 60, 52, 60, 71)                              # soil outside the hall: never
    BW.set(43, 57, 71, BL.table_from({"taken": True}))    # a table on one of them
    r = B.soil_floor_report()
    assert r.tiles == 5 and r.blocks_needed == 5 and r.projects[1].project_id == 1, dict(r)
    r = B.floor_soil_rooms(1, True)
    assert r.ok and r.dry_run and r.floors == 5 and not floors_placed(), dict(r)
    r = B.floor_soil_rooms(1, False)
    assert r.ok and r.floors == 5 and r.tiles == 5, dict(r)
    assert floors_placed() == sorted([(42, 56, 71), (43, 56, 71), (44, 56, 71), (42, 57, 71), (44, 57, 71)]), floors_placed()
    p = BW.persist[B.PROJECTS_KEY].list[1]
    assert len(p.soil_floors) == 5
    r = B.floor_soil_rooms(1, False)                      # once: nothing left bare
    assert r.rejected and "no soil floor" in r.error, dict(r)
    rep = B.soil_floor_report()
    assert rep.tiles == 0 and rep.floored == 5, dict(rep)


@test("soil floors: a farm level, an unfinished hall, a stone hall and no project are left alone")
def _():
    projects(proj(1, "farms", "done"), proj(2, "dining", "furnish"), proj(3, "temple", "decorate", z=72))
    soil(42, 56, 47, 59, 71)
    r = B.floor_soil_rooms(1, False)
    assert r.rejected and "halls only" in r.error, dict(r)
    r = B.floor_soil_rooms(2, False)
    assert r.rejected and "not finished" in r.error, dict(r)
    r = B.floor_soil_rooms(3, False)                      # z72 is stone: smoothing's, not this
    assert r.rejected and "no soil floor" in r.error, dict(r)
    assert B.floor_soil_rooms(9, False).rejected
    assert not floors_placed()
    assert B.soil_floor_report().tiles == 0


@test("soil floors: at most 60 a call, the rest the next call")
def _():
    big = BL.table_from({"id": 1, "kind": "tavern", "phase": "done", "z": 71,
                         "anchor": BL.table_from({"x": 40, "y": 55}),
                         "cells": BL.table_from({"dig": BL.table_from({1: BL.table_from({"x": 1, "y": 1, "text": "d(10x8)"})})})})
    projects(big)
    soil(41, 56, 50, 63, 71)                              # 80 tiles
    r = B.floor_soil_rooms(1, False)
    assert r.ok and r.floors == 60 and r.tiles == 80 and r.left == 20, dict(r)
    r = B.floor_soil_rooms(1, False)
    assert r.ok and r.floors == 20 and r.left == 0, dict(r)


@test("every new function compiles under Lua 5.3 and is reachable where the bridge looks")
def _():
    for name in ("plan_wings", "build_wings", "plan_sealed", "sealed_layer_use", "citizens_beyond", "wing_keepouts"):
        assert M[name] is not None, name
    for name in ("floor_soil_rooms", "soil_floor_report"):
        assert B[name] is not None, name


if __name__ == "__main__":
    finish()
