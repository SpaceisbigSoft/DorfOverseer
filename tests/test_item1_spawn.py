"""(item1) lua/ai-spawn.lua: the tests' units set down (the siege test's war
party, ai-siege-invite spawn_party; the danger test, ai-military-duty
spawn_test_threat). DFHack 53.17-r1's modtools/create-unit is stale for DF 53
("create-unit.lua:164: Cannot read field world.arena_spawn: not found", A,
25 Nov 23:21), so spawn_units tries it and then drives DF 53's own arena
spawner the way gui/sandbox does, putting everything back whatever happens.

The source checks run anywhere; the fake-game ones need lupa (the PC).

    python tests/test_item1_spawn.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import code_has, finish, need_lua, test  # noqa: E402

LUA_DIR = ROOT / "lua"
CHANGED = ["ai-spawn.lua", "ai-siege-invite.lua", "ai-military-duty.lua", "ai-bridge.lua"]


def _src(name: str) -> str:
    return (LUA_DIR / name).read_text(encoding="utf-8")


LONG = re.compile(r"--\[(=*)\[.*?\]\1\]|\[(=*)\[.*?\]\2\]", re.S)
SHORT = re.compile(r"""("(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|--[^\n]*)""")


def _code(name: str) -> str:
    """The source with comments and strings blanked (as tests/test_df_names.py reads it)."""
    src = _src(name)
    out, i = [], 0
    for m in re.finditer(LONG.pattern + "|" + SHORT.pattern, src, re.S):
        out.append(src[i:m.start()])
        out.append(re.sub(r"[^\n]", " ", m.group(0)))
        i = m.end()
    out.append(src[i:])
    return "".join(out)


# --- the sources (no lupa) --------------------------------------------------------------------

@test("every changed Lua file stays under 60 KB")
def _():
    for n in CHANGED:
        size = len(_src(n).encode("utf-8"))
        assert size < 60 * 1024, (n, size)


@test("Lua blocks balance in the changed files (function/if/do/repeat against end/until; brackets)")
def _():
    for n in CHANGED:
        code = _code(n)
        words = re.findall(r"(?<![\w.:])(function|if|do|repeat|end|until)(?![\w])", code)
        opens = sum(1 for w in words if w in ("function", "if", "do", "repeat"))
        closes = sum(1 for w in words if w in ("end", "until"))
        assert opens == closes, (n, opens, closes)
        for a, b in ("()", "{}", "[]"):
            assert code.count(a) == code.count(b), (n, a, code.count(a), code.count(b))


@test("ai-spawn is a module of the bridge and in the code map")
def _():
    s = _src("ai-spawn.lua")
    assert re.search(r"^--@ module = true", s, re.M)
    assert "'ai-spawn'," in _src("ai-bridge.lua").split("BRIDGE_MODULES = {", 1)[1].split("\n}", 1)[0]
    assert "`lua/ai-spawn.lua`" in (ROOT / "docs" / "code-map.md").read_text(encoding="utf-8")
    assert "PART_VERSIONS" not in s, "a plain module: no version mark of its own"


@test("spawn_party and spawn_test_threat go through ai-spawn, never create-unit themselves")
def _():
    inv, duty = _code("ai-siege-invite.lua"), _code("ai-military-duty.lua")
    for code in (inv, duty):
        assert "createUnit" not in code
    for n in ("ai-siege-invite.lua", "ai-military-duty.lua"):
        assert "'modtools/create-unit'" not in _src(n)
        assert "pcall(reqscript, 'ai-spawn')" in _src(n)
    s = _src("ai-siege-invite.lua")
    assert code_has(s, "local ids, why, info = SP.spawn_units{race = civ.race, count = SPAWN_COUNT,")
    assert code_has(s, "equipped = info.equipped == true, equip_error = info.equip_error, route = info.route, ids = ids}")
    assert code_has(s, "equipped = sp.equipped, route = sp.route}")
    assert code_has(s, "spawn_error = rec.spawn_error,")
    d = _src("ai-military-duty.lua")
    assert code_has(d, "flags = {'marauder', 'active_invader', 'invader_origin'}}")


@test("ai-spawn: create-unit first, then the arena; the stale names are not used")
def _():
    s, code = _src("ai-spawn.lua"), _code("ai-spawn.lua")
    assert "arena_spawn" not in code and "D_LOOK_ARENA_CREATURE" not in s.split("--@ module = true", 1)[1]
    assert "viewscreen_dwarfmodest:new" not in code
    spawn = s.split("local function spawn(o)", 1)[1]
    assert spawn.index("by_create_unit(o)") < spawn.index("pcall(by_arena, o)")
    assert code_has(s, "g.gamemode, g.gametype = df.game_mode.DWARF, df.game_type.DWARF_ARENA")
    assert code_has(s, "gui.simulateInput(scr, 'ARENA_CREATE_CREATURE')")
    assert code_has(s, "gui.simulateInput(scr, '_MOUSE_L')")
    assert code_has(s, "function spawn_units(o) local ok, ids, why, info = pcall(spawn, o)")


@test("ai-spawn: the arena's clicks run in a pcall and the restore always follows; it puts back all it changes")
def _():
    s = _src("ai-spawn.lua")
    assert code_has(s, "local ok, err = pcall(arena_clicks, o, scr, rid, castes, eq_rows, tiles, out) "
                       "local rerr = restore_state(S, scr)")
    save = s.split("local function save_state(eq)", 1)[1].split("\nend\n", 1)[0]
    rest = s.split("local function restore_state(S, scr)", 1)[1].split("\nend\n", 1)[0]
    for k in ("gametype = g.gametype", "gamemode = g.gamemode", "pause = g.pause_state", "g.window_x",
              "gps.mouse_x", "bottom = mi.bottom_mode_selected", "view_sheets.open", "vcopy(arena.race)",
              "vcopy(arena.caste)", "vcopy(arena.creature_cnt)", "last_race = arena.last_race",
              "au_race = au.race", "item_counts"):
        assert k in save, k
    for k in ("g.gametype = S.gametype", "g.gamemode = S.gamemode", "g.pause_state = S.pause", "g.window_x",
              "gps.mouse_x", "bottom_mode_selected = -1", "view_sheets.open = false", "vset(a.race, S.race)",
              "vset(a.caste, S.caste)", "vset(a.creature_cnt, S.cnt)", "au.open", "dfhack.screen.dismiss(top)",
              "vset(e.item_counts, S.eq.counts)"):
        assert k in rest, k
    # each restore step on its own pcall
    assert code_has(rest, "local ok, e = pcall(f)")
    # what the arena route sets on df.global: only names save_state reads
    clicks = s.split("local function arena_clicks(", 1)[1].split("\nlocal function by_arena", 1)[0]
    for k in ("g.gamemode", "g.gametype", "mi.bottom_mode_selected", "arena.race", "arena.caste",
              "arena.creature_cnt", "arena.last_race"):
        assert k in clicks, k


@test("ai-spawn: the click tiles come from DFHack's own mouse reading, inside the screen's middle-right")
def _():
    s = _src("ai-spawn.lua")
    assert "CLICK_X = {0.50, 0.80}" in s and "CLICK_Y = {0.30, 0.70}" in s
    cp = s.split("function click_points(pos)", 1)[1].split("\nend\n", 1)[0]
    assert "dfhack.gui.getMousePos" in cp and "standable(" in cp
    assert "pcall(dfhack.units.teleport, u, xyz2pos(t.x, t.y, t.z))" in s


# --- in a fake game (lupa) --------------------------------------------------------------------

FAKE = r"""
local src, opts = ...
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    local n = #(list or {})
    local mt = {}
    local m = {}
    function m.resize(self, k) for i = k, rawget(self, '_n') - 1 do rawset(self, i, nil) end; rawset(self, '_n', k) end
    function m.insert(self, at, v) local k = rawget(self, '_n'); rawset(self, k, v); rawset(self, '_n', k + 1) end
    t._n = n
    mt.__len = function(self) return rawget(self, '_n') end
    mt.__index = m
    return setmetatable(t, mt)
end
local W = {clicks = {}, inputs = {}, teleported = {}, at_click = {}}
local env = setmetatable({}, {__index = _G})
local units, by_id = {}, {}
local creatures = {{creature_id = 'TOAD', caste = {{caste_id = 'MALE'}}},
                   {creature_id = 'GOBLIN', caste = {{caste_id = 'FEMALE'}, {caste_id = 'MALE'}}}}
local arena = {race = vec({7, 7}), caste = vec({0, 1}), creature_cnt = vec({3}), last_race = 5, last_caste = 1,
               interaction = 4,
               equipment = {item_types = vec(), item_subtypes = vec(), item_counts = vec(),
                            item_materials = {mat_type = vec(), mat_index = vec()}}}
local au = {open = false, context = 0, race = 9, caste = 9, interaction = 2, editing_filter = false,
            races_filtered = vec(), castes_filtered = vec(), races_all = vec(), castes_all = vec()}
local mi = {arena_unit = au, bottom_mode_selected = 3, view_sheets = {open = false}}
local gps = {dimx = 100, dimy = 50, mouse_x = 1, mouse_y = 2, precise_mouse_x = 11, precise_mouse_y = 22,
             tile_pixel_x = 8, tile_pixel_y = 12}
local g = {gametype = 0, gamemode = 0, pause_state = false, window_x = 0, window_y = 0, window_z = 5,
           unit_next_id = 500, gps = gps, game = {main_interface = mi},
           world = {arena = arena, units = {active = units}, raws = {creatures = {all = creatures},
                    itemdefs = {weapons = {{id = 'ITEM_WEAPON_SPEAR', subtype = 3}}, armor = {}, helms = {}}}}}
W.g, W.arena, W.au, W.mi, W.units = g, arena, au, mi, units
local scr = {dwarf = true}
env.df = {global = g,
          game_type = {DWARF_MAIN = 0, DWARF_ARENA = 4}, game_mode = {DWARF = 0},
          viewscreen_dwarfmodest = {is_instance = function(_, s) return s and s.dwarf == true end},
          unit = {find = function(id) return by_id[id] end},
          item_type = {WEAPON = 24}, profession = {STANDARD = 103},
          tiletype = {attrs = setmetatable({}, {__index = function(_, tt) return {shape = tt} end})},
          tiletype_shape = {attrs = {FLOOR = {walkable = true}, WALL = {walkable = false}}}}
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
-- a 200x200 map, all floor and outside but a wall column at x 101
local function mouse_tile()
    local x, y = g.window_x + gps.mouse_x, g.window_y + gps.mouse_y
    if x < 0 or y < 0 or x >= 200 or y >= 200 then return nil end
    return {x = x, y = y, z = g.window_z}
end
env.dfhack = {
    isMapLoaded = function() return true end,
    maps = {isValidTilePos = function(x, y, z) return x >= 0 and y >= 0 and x < 200 and y < 200 end,
            getTileType = function(x, y, z) if x == 101 then return 'WALL' end return 'FLOOR' end,
            getTileFlags = function(x, y, z) return {outside = true, flow_size = 0} end,
            getWalkableGroup = function(p) return 1 end},
    buildings = {findAtTile = function() return nil end},
    matinfo = {find = function(s) if s == 'INORGANIC:IRON' then return {type = 0, index = 8} end return nil end},
    gui = {getDFViewscreen = function() return W.top or scr end,
           revealInDwarfmodeMap = function(p, c) g.window_x, g.window_y, g.window_z = p.x - 50, p.y - 25, p.z end,
           getMousePos = mouse_tile},
    screen = {dismiss = function(s) s.dismissed = true; W.dismissed = (W.dismissed or 0) + 1 end,
              isDismissed = function(s) return s.dismissed == true end},
    units = {teleport = function(u, p) u.pos = p; table.insert(W.teleported, u.id) end},
}
env.require = function(n)
    if n ~= 'gui' then error('require ' .. n) end
    return {simulateInput = function(s, key)
        table.insert(W.inputs, key)
        if opts.input_error and key == opts.input_error then error('boom in ' .. key) end
        if key == 'ARENA_CREATE_CREATURE' then
            if opts.no_window then return end
            au.open = true
            if not opts.no_list then
                au.races_filtered:insert('#', 0)
                for i = 0, #arena.caste - 1 do au.castes_filtered:insert('#', i) end
            end
        elseif key == '_MOUSE_L' then
            assert(g.gametype == 4, 'clicked outside the arena')
            table.insert(W.at_click, {eq = #arena.equipment.item_types, race_list = #arena.race, open = au.open})
            if opts.push_screen then W.top = {} end
            if opts.dead_clicks then return end
            local t = mouse_tile()
            local id = g.unit_next_id
            g.unit_next_id = id + 1
            local race = arena.race[au.race]
            if opts.wrong_race then race = 1 end
            local u = {id = id, race = race, caste = au.caste, pos = t, flags1 = {}, civ_id = -1, name = {has_name = true},
                       animal = {vanish_countdown = 0}, inventory = (#arena.equipment.item_types > 0) and {1} or {}}
            by_id[id] = u
            table.insert(units, u)
            table.insert(W.clicks, {x = t.x, y = t.y, sx = gps.mouse_x, sy = gps.mouse_y})
        end
    end}
end
env.reqscript = function(n)
    if n == 'modtools/create-unit' then
        if opts.cu_mode == 'equip_refused' then
            return {createUnit = function(race, caste, pos, range, lt, age, dom, civ, grp, ern, nick, van, qty, equip)
                if equip then error('Invalid equipment material: IRON') end
                local us = {}
                for i = 1, qty do us[i] = {id = 900 + i, flags1 = {}, civ_id = -1} end
                W.made = us
                return us
            end}
        end
        return {createUnit = function() error('create-unit.lua:164: Cannot read field world.arena_spawn: not found') end}
    end
    error('reqscript ' .. tostring(n))
end
assert(load(src, 'ai-spawn', 't', env))()
return env, W
"""


def _lua(**opts):
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, _src("ai-spawn.lua"), lua.table_from(opts))
    _lua.rt = lua
    return env, w


def _t(d):
    rt = _lua.rt
    if isinstance(d, dict):
        return rt.table_from({k: _t(v) for k, v in d.items()})
    if isinstance(d, list):
        return rt.table_from([_t(v) for v in d])
    return d


def _vals(v):
    """A fake DF vector's values (its _n: lupa's len() is the raw length)."""
    return [v[i] for i in range(v._n)]


def _vals_list(t):
    return [t[i] for i in range(1, len(t) + 1)]


def _restored(w):
    g, a, au = w.g, w.arena, w.au
    assert g.gametype == 0 and g.gamemode == 0 and g.pause_state is False
    assert (g.window_x, g.window_y, g.window_z) == (0, 0, 5)
    assert (g.gps.mouse_x, g.gps.mouse_y, g.gps.precise_mouse_x, g.gps.precise_mouse_y) == (1, 2, 11, 22)
    assert _vals(a.race) == [7, 7] and _vals(a.caste) == [0, 1] and _vals(a.creature_cnt) == [3]
    assert (a.last_race, a.last_caste, a.interaction) == (5, 1, 4)
    assert a.equipment.item_types._n == 0 and a.equipment.item_materials.mat_index._n == 0
    assert au.open is False and (au.race, au.caste, au.interaction) == (9, 9, 2)
    assert w.mi.bottom_mode_selected == -1 and w.mi.view_sheets.open is False


SPEC = {"race": "GOBLIN", "count": 4, "pos": {"x": 120, "y": 80, "z": 5}, "spread": 2, "civ_id": 314,
        "flags": ["active_invader", "invader_origin"], "equip": ["ITEM_WEAPON_SPEAR:INORGANIC:IRON"]}


@test("arena (Lua): create-unit stale: the arena makes the units, moved to their tiles round pos; all put back")
def _():
    need_lua()
    env, w = _lua()
    ids, why, info = env.spawn_units(_t(SPEC))
    assert ids is not None, why
    assert _vals_list(ids) == [500, 501, 502, 503], _vals_list(ids)
    assert info.route == "arena" and "arena_spawn" in info.cu_error, dict(info)
    assert info.equipped is True and info.equip_error is None, dict(info)
    assert list(w.inputs.values())[0] == "ARENA_CREATE_CREATURE" and len(w.clicks) == 4
    for c in w.clicks.values():               # every click in the screen's middle-right, on the map
        assert 50 <= c.sx <= 80 and 15 <= c.sy <= 35, dict(c)
    at = list(w.at_click.values())
    assert all(a.eq == 1 and a.race_list == 2 and a.open for a in at), [dict(a) for a in at]
    for u in w.units.values():
        assert u.race == 2 and abs(u.pos.x - 120) <= 2 and abs(u.pos.y - 80) <= 2 and u.pos.z == 5, dict(u.pos)
        assert u.civ_id == 314 and u.flags1.active_invader and u.flags1.invader_origin and u.flags1.marauder
        assert u.name.has_name is False
    _restored(w)


@test("arena (Lua): an error mid-click, a window that never opens, an empty list: nil and why, all put back")
def _():
    need_lua()
    for opts, words in (({"input_error": "_MOUSE_L"}, "boom"), ({"no_window": True}, "did not open"),
                        ({"no_list": True}, "lists no creature"), ({"dead_clicks": True}, "placed no unit")):
        env, w = _lua(**opts)
        ids, why, info = env.spawn_units(_t(SPEC))
        assert ids is None and words in why and "create-unit" in why, (opts, why)
        assert info.route == "none"
        _restored(w)


@test("arena (Lua): a click that made another race: sent away, not returned; a pushed screen dismissed")
def _():
    need_lua()
    env, w = _lua(wrong_race=True)
    ids, why, info = env.spawn_units(_t(SPEC))
    assert ids is None and "another race" in why, why
    assert all(u.animal.vanish_countdown > 0 for u in w.units.values())
    _restored(w)
    env, w = _lua(push_screen=True)
    ids, why, info = env.spawn_units(_t(SPEC))
    assert ids is not None and w.dismissed == 1, (why, w.dismissed)
    _restored(w)


@test("create-unit (Lua): when it works it is used (equipment refused: placed unarmed); garbage in: nil, no throw")
def _():
    need_lua()
    env, w = _lua(cu_mode="equip_refused")
    ids, why, info = env.spawn_units(_t(SPEC))
    assert ids is not None and len(ids) == 4 and info.route == "create-unit", why
    assert info.equipped is False and "IRON" in info.equip_error, dict(info)
    assert len(w.inputs) == 0, "the arena left alone"
    assert all(u.civ_id == 314 and u.flags1.active_invader and not u.flags1.marauder for u in w.made.values())
    for bad in (None, 5, _t({"race": "GOBLIN"}), _t({"pos": {"x": 1, "y": 1, "z": 1}})):
        r = env.spawn_units(bad)
        assert r[0] is None and isinstance(r[1], str), r
    env, w = _lua()
    ids, why, info = env.spawn_units(_t({**SPEC, "race": "NOSUCH"}))
    assert ids is None and "no creature NOSUCH" in why, why


@test("every changed Lua file compiles under Lua 5.3")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    chk = LuaRuntime().eval("function(src, n) local f, e = load(src, n, 't', {}); return f ~= nil, e end")
    for n in CHANGED:
        ok, err = chk(_src(n), n)
        assert ok, (n, err)


if __name__ == "__main__":
    finish()
