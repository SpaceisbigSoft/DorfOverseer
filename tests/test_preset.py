"""(0.105.4) Tests for applying a preset from the bridge (keeper.py --preset):
lua/ai-overseer-settings.lua apply_preset and the bridge's apply_preset action,
with a stub DFHack, in a real Lua engine (pip install lupa).

    python tests/test_preset.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import make_test, finish  # noqa: E402

try:
    from lupa import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

HARNESS = r"""
local bridge_src, settings_src, lua_dir = ...
local H = {persist = {}, action = nil, printed = nil, halted = false, preset_files = {}}
local json = {
  decode = function(text) return H.action end,
  decode_file = function(path)
    local d = H.preset_files[path]
    if d == nil then error('no file ' .. path) end
    return d
  end,
  encode_file = function(data, path) H.preset_files[path] = data end,
  encode = function(t) H.printed = t; return 'json' end,
}
local utils = {invert = function(t) local o = {}; for i, v in ipairs(t) do o[v] = i end; return o end}
local dfhack = {
  getDFPath = function() return '/df' end,
  isMapLoaded = function() return true end, isWorldLoaded = function() return true end,
  world = {isFortressMode = function() return true end},
  persistent = {
    getSiteData = function(k, default) local v = H.persist[k]; if v == nil then return default end; return v end,
    saveSiteData = function(k, v) H.persist[k] = v end,
  },
  filesystem = {mkdir_recursive = function() end,
                isdir = function() return next(H.preset_files) ~= nil end,
                listdir = function()
                  local out = {}
                  for path in pairs(H.preset_files) do table.insert(out, (path:match('[^/]+$'))) end
                  return out
                end},
  maps = {getTileSize = function() return 120, 120, 100 end},
}
local df = {global = {cur_year = 150, cur_year_tick = 1000, pause_state = true,
  world = {cur_savegame = {save_dir = 'region1'}, map = {region_z = 140}},
  plotinfo = {site_id = 7, tasks = {wealth = {total = 1234}}, alerts = {civ_alert_idx = 0, list = {}}}}}
local function new_env()
  local env = setmetatable({}, {__index = _G})
  env.dfhack, env.df = dfhack, df
  env.require = function(name) if name == 'json' then return json end if name == 'utils' then return utils end
    error('unexpected require ' .. name) end
  env.dfhack_flags = {module = true}
  env.print = function() end
  return env
end
function H.settings()
  local env = new_env()
  assert(load(settings_src, 'ai-overseer-settings', 't', env))()
  return env
end
function H.run(...)
  local S = H.settings()
  local env = new_env()
  env.dfhack_flags = {module = false}
  env.reqscript = function(name)
    if name == 'ai-overseer-settings' then return S end
    if name == 'ai-status' then return {is_halted = function() return H.halted end} end
    error('no ' .. name .. ' here')
  end
  assert(load(bridge_src, '@' .. lua_dir .. '/ai-bridge.lua', 't', env))(...)
  return H.printed
end
return H
"""

LUA = LuaRuntime(unpack_returned_tuples=True)
H = LUA.execute(HARNESS, (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8"),
                (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8"), str(ROOT / "lua"))
PRESETS = ["War-hold", "Monastery", "Merchant city", "Hermit hold", "Deep mine", "Garden fort"]


def t(d):
    if isinstance(d, dict):
        return LUA.table_from({k: t(v) for k, v in d.items()})
    if isinstance(d, list):
        return LUA.table_from([t(v) for v in d])
    return d


def reset():
    H.persist = LUA.table()
    H.preset_files = LUA.table()
    H.halted = False


def act(action):
    H.action = t(action)
    return H.run("act", "{}")


test = make_test(before=reset)


def saved():
    return H.persist["ai-overseer/settings"]


@test("apply_preset: War-hold's sliders (Extreme past 100) and its rules saved in the fort's site data, named")
def _():
    r = act({"type": "apply_preset", "name": "War-hold"})
    assert r.ok and r.preset == "War-hold" and r.previous is None and r.action == "apply_preset", dict(r)
    s = saved()
    assert s.traits.militarism.value == 75 and s.traits.militarism.extreme is True     # 150: 75 with Extreme
    assert s.traits.caution.value == 60 and s.traits.caution.extreme is False
    assert s.traits.piety.value == -30 and s.traits.growth.value == 0                  # not named: balanced
    assert s.attack_policy == "all" and s.fill_squads is True and s.fortify_entrances is True
    assert s.levels.garden is False
    assert r.traits.militarism == 150 and r.traits.fortification == 120 and r.traits.growth is None
    assert list(r.extreme.values()) == ["fortification", "militarism"], list(r.extreme.values())
    assert r.rules.attack_policy == "all" and r.rules.levels.garden is False
    assert H.persist["ai-overseer/preset"].name == "War-hold" and H.persist["ai-overseer/preset"].by == "keeper"
    assert r.settings.preset == "War-hold"


@test("apply_preset: the same as the window's Load preset (load_preset on the saved settings), whatever came before")
def _():
    S = H.settings()
    H.persist["ai-overseer/settings"] = t({"traits": {"greed": {"value": 90, "extreme": False}},
                                           "mode": "copilot", "real_day_token_cap": 250000})
    for name in PRESETS:
        want = S.load_preset(name, S.load_settings())
        assert act({"type": "apply_preset", "name": name}).ok, name
        got = saved()
        for tid in ("militarism", "greed", "piety", "trade", "mining", "agriculture", "outsiders"):
            assert got.traits[tid].value == want.traits[tid].value, (name, tid)
            assert got.traits[tid].extreme == want.traits[tid].extreme, (name, tid)
        for k in ("attack_policy", "accept_visitors", "answer_locations", "pasture_animals", "water_works"):
            assert got[k] == want[k], (name, k)
        for k in ("garden", "barracks", "archery", "jail"):
            assert got.levels[k] == want.levels[k], (name, k)
        assert got.mode == "copilot" and got.real_day_token_cap == 250000        # kept, as the window keeps them
    assert saved().traits.greed.value == 0            # Garden fort, last: no greed in it
    r = act({"type": "apply_preset", "name": "Deep mine"})
    assert r.previous == "Garden fort", dict(r)


@test("apply_preset: an unknown name is refused listing the valid ones; nothing saved")
def _():
    for bad in ("Fortress of Doom", "../x", ""):
        r = act({"type": "apply_preset", "name": bad})
        assert not r.ok and r.rejected, (bad, dict(r))
    r = act({"type": "apply_preset", "name": "Warhold"})
    for name in PRESETS:
        assert name in r.error, r.error
    assert act({"type": "apply_preset"}).rejected
    assert H.persist["ai-overseer/settings"] is None and H.persist["ai-overseer/preset"] is None


@test("apply_preset: a dry run saves nothing; a saved preset of the player's own is known too")
def _():
    r = act({"type": "apply_preset", "name": "Monastery", "dry_run": True})
    assert r.ok and r.dry_run and r.traits.piety == 150 and r.rules.attack_policy == "never", dict(r)
    assert H.persist["ai-overseer/settings"] is None and H.persist["ai-overseer/preset"] is None
    S = H.settings()
    s = S.load_settings()
    s.traits.trade.value = 40
    assert S.save_preset("My hold", s)
    r = act({"type": "apply_preset", "name": "My hold"})
    assert r.ok and saved().traits.trade.value == 40 and H.persist["ai-overseer/preset"].name == "My hold", dict(r)


@test("apply_preset: allowed while the AI is halted (the player's settings, not the fort); in the table")
def _():
    H.halted = True
    assert act({"type": "apply_preset", "name": "Hermit hold"}).ok
    assert saved().accept_visitors is False and saved().traits.outsiders.extreme is True
    assert act({"type": "start_project", "kind": "x"}).halted         # the halt still holds for the rest
    v = H.run("version")
    assert v is not None


@test("the settings section names the preset the fort was given; none before")
def _():
    S = H.settings()
    assert S.current_preset() is None
    assert S.apply_preset("Garden fort", None, "window")
    assert S.current_preset() == "Garden fort" and saved().pasture_animals is True
    assert saved().levels.archery is False


@test("the brain: a short label for the action")
def _():
    sys.path.insert(0, str(ROOT / "brain"))
    import overseer
    assert overseer.short({"type": "apply_preset", "name": "Deep mine"}) == "apply the Deep mine preset"


if __name__ == "__main__":
    finish()
