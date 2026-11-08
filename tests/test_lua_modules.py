"""(13c lua-modules) Tests for lua/ai-util.lua (the helpers the modules share)
and for the modules split in two (ai-military / ai-military-gear,
ai-society / ai-society-burrows): every name the other half holds is still
reachable through the old module. In a real Lua engine (pip install lupa).

    python tests/test_lua_modules.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from lua_modules_util import UTIL_SRC, module_src  # (13c lua-modules)
RESULTS = []

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)


def test(name):
    def wrap(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


UTIL_FAKE = r"""
local src = ...
local saved = {}
local env = setmetatable({}, {__index = _G})
env.df = {global = {cur_year = 3, cur_year_tick = 1000, plotinfo = {group_id = 7}},
          historical_entity = {find = function(id) return {id = id} end}}
env.dfhack = {persistent = {getSiteData = function(k, d) if saved[k] == nil then return d end return saved[k] end,
                            saveSiteData = function(k, v) if k == 'bad' then error('no save') end saved[k] = v end},
              items = {getHolderUnit = function(it) return it.holder end}}
assert(load(src, 'ai-util', 't', env))()
return env, saved
"""


def util():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, saved = lua.execute(UTIL_FAKE, UTIL_SRC)
    return lua, env, saved


@test("ai-util: abs_tick now and from an event's year and tick; the fort's entity")
def _():
    lua, U, _ = util()
    assert U.abs_tick() == 3 * 403200 + 1000
    assert U.abs_tick(2, 5) == 2 * 403200 + 5
    assert U.fort_entity().id == 7


@test("ai-util: site data read with a default (missing, unreadable or not a table) and saved, a failure said")
def _():
    lua, U, saved = util()
    assert dict(U.site_get("k", lua.table_from({"a": 1}))) == {"a": 1}
    saved["k"] = "text"
    assert dict(U.site_get("k", lua.table_from({}))) == {}           # not a table: the default
    assert U.site_get("k", None) == "text"                           # no table default: as saved
    ok = U.site_put("k2", lua.table_from({"b": 2}))
    assert ok is True and saved["k2"]["b"] == 2
    ok, err = U.site_put("bad", 1)
    assert ok is False and "no save" in err
    lua.execute("local U = ...; U.dfhack = nil", U)                   # no DFHack at all: the default, no error
    assert U.site_get("k", 5) == 5 and U.site_put("k", 1)[0] is False


@test("ai-util: one free-item list, in order: never-usable flags, then a job, forbidden, dump, then carried")
def _():
    lua, U, _ = util()
    item = lua.eval("function(flags, holder) return {flags = flags, holder = holder} end")
    t = lua.table_from
    assert U.item_free(item(t({}), None))
    assert U.item_free(item(t({"in_inventory": True}), None))        # in a bin: free
    assert U.item_unfree(item(t({"in_inventory": True}), t({}))) == ("held", "carried")
    for flag in ("removed", "garbage_collect", "construction", "in_building", "encased", "trader", "hostile",
                 "owned", "artifact", "murder", "dead_dwarf", "rotten", "on_fire", "spider_web",
                 "in_job", "forbid", "dump"):
        assert U.item_unfree(item(t({flag: True}), None))[0] == flag, flag
    # a never-usable flag wins over a soft one (the moods' 'other' before 'forbidden')
    assert U.item_unfree(item(t({"forbid": True, "owned": True}), None))[0] == "owned"
    assert U.item_unfree(item(t({"in_job": True, "forbid": True}), None))[0] == "in_job"
    # what the caller allows
    assert U.item_free(item(t({"in_job": True}), None), t({"in_job": True}))
    assert U.item_free(item(t({"in_inventory": True}), t({})), t({"held": True}))
    assert not U.item_free(item(t({"in_job": True, "dump": True}), None), t({"in_job": True}))


SPLIT_FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
env.df = {global = {plotinfo = {group_id = 1}}, need_type = {[3] = 'BeWithFriends'}}
env.dfhack = {}
env.require = function() return {} end
assert(load(src, 'm', 't', env))()
return env
"""


def gear_names(fname):
    src = (ROOT / "lua" / fname).read_text(encoding="utf-8")
    return re.findall(r"^function (\w+)\(", src, re.M)


@test("13c split: every function of ai-military-gear is reachable as ai-military's, and works through it")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(SPLIT_FAKE, module_src("ai-military.lua"))
    own = set(gear_names("ai-military.lua"))
    # the four the squad half calls through gear() itself (they were local before)
    helpers = {"metal_token", "equipment_lists", "id_set", "inv_mode_name"}
    missing = [n for n in gear_names("ai-military-gear.lua") if n not in helpers and n not in own
               and lua.eval("type")(env[n]) != "function"]
    assert not missing, missing
    assert env.weapon_is_ranged(lua.table_from({"ranged_ammo": "BOLT"})) is True
    assert env.weapon_is_ranged(lua.table_from({})) is False


@test("13c split: every function of ai-society-burrows is reachable as ai-society's, and works through it")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(SPLIT_FAKE, module_src("ai-society.lua"))
    own = set(gear_names("ai-society.lua"))
    missing = [n for n in gear_names("ai-society-burrows.lua") if n not in own
               and lua.eval("type")(env[n]) != "function"]
    assert not missing, missing
    u = lua.eval("{status = {current_soul = {personality = {needs = {{id = 3, focus_level = -20000}}}}}}")
    assert env.badly_wants_friends(u) == -20000


@test("13c split: the halves never use the other's names bare (in the game they'd be nil)")
def _():
    def defs(t):
        return set(re.findall(r"^(?:local function |function |local )?([A-Za-z_]\w*)\s*(?:=|\()", t, re.M))

    def used(t):
        c = re.sub(r"--[^\n]*", "", t)
        c = re.sub(r"'[^']*'|\"[^\"]*\"", "", c)
        return set(re.findall(r"(?<![\w.:])([A-Za-z_]\w*)(?!\s*=[^=])", c))   # (not a table key)

    for main, half in (("ai-military.lua", "ai-military-gear.lua"), ("ai-society.lua", "ai-society-burrows.lua")):
        m = (ROOT / "lua" / main).read_text(encoding="utf-8")
        h = (ROOT / "lua" / half).read_text(encoding="utf-8")
        bare = (used(h) & defs(m)) - defs(h) - {"held"}          # (held: a local of gear_report's)
        assert not bare, (half, sorted(bare))


@test("every Lua file compiles (load with an empty env)")
def _():
    lua = LuaRuntime()
    f = lua.eval("function(src) local fn, err = load(src, 'b', 't', {}); return err end")
    bad = []
    for p in sorted(list((ROOT / "lua").glob("*.lua")) + list((ROOT / "lua" / "gui").glob("*.lua"))):
        err = f(p.read_text(encoding="utf-8"))
        if err:
            bad.append(f"{p.name}: {err}")
    assert not bad, bad


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
