"""(13c, group bridge) The bridge in parts (lua/ai-bridge.lua and the
ai-bridge-*.lua beside it), the halt switch's dry-run list (DRY_OK), and the
report's one-walk reads (boulders, logistics not kept when it failed, the
pastures in one pass), on a stub DFHack in a real Lua engine (pip install lupa).

    python tests/test_hygiene_bridge.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = []

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

LUA_DIR = ROOT / "lua"
PARTS = ["ai-bridge-report", "ai-bridge-orders", "ai-bridge-actions", "ai-bridge-probes",
         "ai-bridge-design"]   # (D0)

HARNESS = r"""
local src, lua_dir = ...
local H = {persist = {}, printed = nil, action = nil, halted = false, scripts = {}}
local json = {decode = function() return H.action end, encode = function(t) H.printed = t; return 'json' end,
              encode_file = function() end, decode_file = function() error('no file') end}
local utils = {invert = function(t) local o = {}; for i, v in ipairs(t) do o[v] = i end; return o end}
local dfhack = {
  getDFPath = function() return '/df' end,
  isMapLoaded = function() return true end, isWorldLoaded = function() return true end,
  world = {isFortressMode = function() return true end},
  persistent = {getSiteData = function(k, d) local v = H.persist[k]; if v == nil then return d end; return v end,
                saveSiteData = function(k, v) H.persist[k] = v end},
  filesystem = {mkdir_recursive = function() end},
  maps = {getTileSize = function() return 120, 120, 100 end},
  matinfo = {decode = function() return nil end},
  units = {getCitizens = function() return {} end},
}
local df = {global = {cur_year = 150, cur_year_tick = 1000, pause_state = true,
  world = {cur_savegame = {save_dir = 'region1'}, map = {region_z = 140},
           raws = {inorganics = {all = {}}, descriptors = {colors = {}}}},
  plotinfo = {site_id = 7, tasks = {wealth = {total = 1234}}, economic_stone = {},
              alerts = {civ_alert_idx = 0, list = {}}}}}
H.df, H.dfhack = df, dfhack
function H.module()
  local env = setmetatable({}, {__index = _G})
  env.dfhack, env.df = dfhack, df
  env.require = function(name) if name == 'json' then return json end if name == 'utils' then return utils end
    error('unexpected require ' .. name) end
  env.reqscript = function(name)
    if H.scripts[name] then return H.scripts[name] end
    if name == 'ai-status' then return {is_halted = function() return H.halted end} end
    error('no ' .. name .. ' here')
  end
  env.dfhack_flags = {module = true}
  env.print = function() end
  env.CR_OK = 0
  assert(load(src, '@' .. lua_dir .. '/ai-bridge.lua', 't', env))()
  H.env = env
  return env
end
function H.act(env, action)
  H.action = action
  env.dfhack_flags = {module = false}
  assert(load(src, '@' .. lua_dir .. '/ai-bridge.lua', 't', env))('act', '{}')
  return H.printed
end
return H
"""

LUA = LuaRuntime(unpack_returned_tuples=True)
H = LUA.execute(HARNESS, (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8"), str(LUA_DIR))


def t(d):
    if isinstance(d, dict):
        return LUA.table_from({k: t(v) for k, v in d.items()})
    if isinstance(d, list):
        return LUA.table_from([t(v) for v in d])
    return d


def test(name):
    def wrap(fn):
        H.scripts = LUA.table()
        H.halted = False
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


def bridge_text() -> str:
    return "".join((LUA_DIR / f"{n}.lua").read_text(encoding="utf-8") for n in ["ai-bridge"] + PARTS)


@test("parts: every part is in BRIDGE_PARTS, compiles alone, refuses to run outside the bridge")
def _():
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    listed = re.search(r"BRIDGE_PARTS = \{(.*?)\}", src).group(1)
    assert re.findall(r"'([\w-]+)'", listed) == PARTS, listed
    on_disk = sorted(p.stem for p in LUA_DIR.glob("ai-bridge-*.lua"))
    assert on_disk == sorted(PARTS), on_disk
    L = LuaRuntime(unpack_returned_tuples=True)
    for n in PARTS:
        part = (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8")
        ok, err = L.eval("function(s) local f, e = load(s, 'p', 't', {}); return f ~= nil, e end")(part)
        assert ok, (n, err)
        ran = L.eval("""function(s)
            local env = setmetatable({qerror = function(m) error('QERROR ' .. m) end}, {__index = _G})
            return pcall(load(s, 'p', 't', env)) end""")(part)
        assert ran[0] is False and "QERROR" in str(ran[1]) and n in str(ran[1]), (n, ran)


@test("parts: every ACTIONS handler and command is defined once the parts are loaded")
def _():
    M = H.module()
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    table = src[src.index("ACTIONS = {"):src.index("\n}\n", src.index("ACTIONS = {"))]
    for name, fn in re.findall(r"^\s+(\w+) = (act_\w+),", table, re.M):
        assert LUA.eval(f"function(M) return type(M.{fn}) == 'function' and M.ACTIONS.{name} == M.{fn} end")(M), name
    cmds = src[src.index("local COMMANDS = {"):]
    for fn in re.findall(r"= (cmd_\w+),", cmds[:cmds.index("\n}\n")]):
        if fn not in ("cmd_status", "cmd_state", "cmd_run", "cmd_act", "cmd_halt", "cmd_memory", "cmd_survey",
                      "cmd_watch", "cmd_events", "cmd_map", "cmd_modules"):
            assert LUA.eval(f"function(M) return type(M.{fn}) == 'function' end")(M), fn
    for g in ("get_supplies", "get_order_desk", "boulder_census", "act_work_order", "act_civ_alert",
              "citizen_anchor", "abs_tick", "translate_name"):
        assert LUA.eval(f"function(M) return type(M.{g}) == 'function' end")(M), g
    assert M.BRIDGE_VERSION and M.SECTIONS.protocol is None and M.ACTIONS.assign_miners is None


@test("DRY_OK: names real actions, each handler honours dry_run; a dry run passes the halt, a real one doesn't")
def _():
    M = H.module()
    text = bridge_text()
    names = list(LUA.eval("function(M) local o = {} for k in pairs(M.DRY_OK) do o[#o + 1] = k end return o end")(M).values())
    assert len(names) >= 60 and "farm_thresholds" in names and "unstick_uniforms" in names
    hub = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    for n in names:
        assert LUA.eval(f"function(M) return M.ACTIONS['{n}'] ~= nil end")(M), n
        if f"function act_{n}(a)" in text:
            i = text.index(f"function act_{n}(a)")
            body = text[i:text.index("\nend\n", i)]
        else:                                     # (0.105.26) a handler written in ACTIONS itself
            i = hub.index(f"    {n} = function(a)")
            body = hub[i:re.compile(r"\n    \w").search(hub, i + 1).start()]   # to the next entry
        assert "dry_run" in body, n
    for n in LUA.eval("function(M) local o = {} for k in pairs(M.DISPLAY_ONLY) do o[#o + 1] = k end return o end")(M).values():
        assert LUA.eval(f"function(M) return M.ACTIONS['{n}'] ~= nil end")(M), n
    H.halted = True
    H.scripts["ai-joins"] = LUA.eval("{join_levels = function(dry) return {ok = true, dry_run = dry} end}")
    r = H.act(M, t({"type": "join_levels", "dry_run": True}))
    assert r.ok and r.dry_run, dict(r)
    r = H.act(M, t({"type": "join_levels"}))
    assert not r.ok and r.halted, dict(r)
    r = H.act(M, t({"type": "unpause", "dry_run": True}))      # (0.105.26) no dry run: refused, halted or not
    assert not r.ok and r.rejected and "no dry run" in r.error, dict(r)


@test("report: the boulders are walked once a report for stocks, stone_types and stone_use; afresh outside one")
def _():
    M = H.module()
    walks = LUA.execute(r"""
      local H = ...
      local w = {n = 0}
      local function boulder(idx, in_job)
        return {flags = {in_job = in_job}, mat_type = 0, mat_index = idx,
                getStackSize = function() return 1 end, getMaterial = function() return 0 end,
                getMaterialIndex = function() return idx end}
      end
      local data = {boulder(5), boulder(5), boulder(6, true)}
      local proxy = setmetatable({}, {__index = function(_, k) if k == 1 then w.n = w.n + 1 end return data[k] end,
                                      __len = function() return #data end})
      H.df.items_other_id = setmetatable({}, {__index = function(_, k) return k end})
      H.df.global.world.items = {other = setmetatable({BOULDER = proxy}, {__index = function() return {} end})}
      return w""", H)
    LUA.eval("""function(M)
        M.get_dwarves = function() return {total = 1}, nil end
        M.SECTIONS = {stocks = function() return M.get_stocks() end,
                      stone_types = function() return M.get_stone_types() end,
                      stone_use = function() return M.get_stone_use() end}
        M.SECTION_CACHE_DAYS = {}
    end""")(M)
    s = M.build_state(False)
    assert walks.n == 1, walks.n
    assert s.stocks.boulders == 3 and s.stone_use.usable == 0, (s.stocks.boulders, dict(s.stone_use))
    M.get_stone_use()
    M.get_stone_use()
    assert walks.n == 3 and M.REPORT_MEMO is None, walks.n
    assert M.boulder_census().stone[5] == 2 and M.boulder_census().free == 2


@test("report: a logistics section whose storage survey failed is not kept for 3 days")
def _():
    M = H.module()
    H.scripts = t({"ai-builder": {}})
    LUA.execute("""local H, M = ...
      H.fail = true
      H.scripts['ai-builder'] = {feeder_survey = function() return {piles = 1} end,
                                 storage_survey = function() if H.fail then error('boom') end return {ok = 1} end}
      H.df.global.world.items = {all = {}}
      H.df.global.world.units = {active = {}}
      H.df.global.world.jobs = {list = {}}
      M.get_dwarves = function() return {total = 1}, nil end
      local real = M.SECTIONS.logistics
      M.SECTIONS = {logistics = real}
      M.SECTION_CACHE = {}
    """, H, M)
    s = M.build_state(False)
    assert s.logistics.storage.error and M.SECTION_CACHE.logistics is None
    H.fail = False
    s = M.build_state(False)
    assert s.logistics.storage.ok == 1 and M.SECTION_CACHE.logistics is not None


@test("report: society reads the pastures in one call (pasture_report), not three walks")
def _():
    M = H.module()
    LUA.execute("""local H = ...
      local function no() error('walked again') end
      H.scripts['ai-society'] = {
        pasture_report = function() return {grazers = 4, count = 2, needs = {need = 30, smallest = 5, spare = 9},
                                            ai = {count = 1, tiles = 40, spare = 3}} end,
        pasture_count = no, pasture_needs = no, ai_pastures = no, unpastured_grazers = no,
        get_popcap = function() return {cap = 50, strict = 0} end}
      H.df.historical_entity = {find = function() return nil end}
      H.dfhack.units.getCitizens = function() return {} end
    """, H)
    s = M.get_society()
    assert (s.grazers_unpastured, s.pastures, s.grazer_tiles, s.pasture_spare, s.ai_pastures, s.ai_pasture_tiles) \
        == (4, 2, 30, 9, 1, 40), dict(s)
    assert s.pop_cap == 50 and s.pastures_error is None


@test("ai-society: pasture_report gives what pasture_count, pasture_needs and ai_pastures gave, in one pass")
def _():
    L = LuaRuntime(unpack_returned_tuples=True)
    S = L.execute(r"""
      local src = ...
      local CIV, PEN = 1, 2
      local walks = {n = 0}
      local function zone(id, name, x2, units)
        return {id = id, name = name, type = PEN, x1 = 0, y1 = 0, x2 = x2, y2 = 0, z = 1, assigned_units = units,
                getType = function() return CIV end}
      end
      local units = {}
      local function unit(id, grazer, penned)
        local u = {id = id, race = id, caste = 0, grazer = grazer, penned = penned, flags1 = {caged = false}}
        units[id] = u
        return u
      end
      local active = {unit(1, 2000), unit(2, 1000), unit(3, 4000, true)}
      local buildings = {zone(10, 'AI pasture', 19, {3}), zone(11, 'Pen', 9, {}), {getType = function() return 9 end}}
      local env = setmetatable({}, {__index = _G})
      env.df = {global = {world = {buildings = setmetatable({}, {__index = function(_, k)
                   if k == 'all' then walks.n = walks.n + 1 return buildings end end}),
                                    units = {active = active}}},
                building_type = {Civzone = CIV}, civzone_type = {Pen = PEN},
                general_ref_type = {BUILDING_CIVZONE_ASSIGNED = 1},
                unit = {find = function(id) return units[id] end},
                creature_raw = {find = function(race) return {caste = {[0] = {misc = {grazer = units[race].grazer}}}} end}}
      env.dfhack = {units = {isAlive = function() return true end, isTame = function() return true end,
                             isOwnCiv = function() return true end, isGrazer = function() return true end,
                             getGeneralRef = function(u) return u.penned end}}
      env.reqscript = function() return {grass_at = function(x) return x % 2 == 0 end} end
      env.require = function() return {} end
      env.dfhack_flags = {module = true}
      assert(load(src, 'ai-society', 't', env))()
      env.WALKS = walks
      return env
    """, (LUA_DIR / "ai-society.lua").read_text(encoding="utf-8"))
    r = S.pasture_report()
    assert S.WALKS.n == 1, S.WALKS.n
    old_needs, old_ai = S.pasture_needs(), S.ai_pastures()
    assert (r.count, r.grazers) == (S.pasture_count(), len(S.unpastured_grazers()))
    assert (r.needs.need, r.needs.smallest, r.needs.spare) == (old_needs.need, old_needs.smallest, old_needs.spare)
    assert (r.ai.count, r.ai.tiles, r.ai.spare) == (old_ai.count, old_ai.tiles, old_ai.spare)
    assert (r.count, r.grazers, r.needs.need, r.ai.tiles) == (2, 2, 30, 10), (r.count, r.grazers, r.needs.need, r.ai.tiles)


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
