"""(0.105.51) Fort C's DF crashes: five overnight (R3 live run, 15 Nov), the
same DF 53.17 render-path stack, each crash log naming a named female tame
animal: three 'Mouser' stray cats (the AI's keep_mousers nickname), a cat,
and a soldier's pet doe rabbit the AI had put in a pasture.

DFHack's setNickname gives an unnamed animal a fresh name record (has_name,
language 0, no first name, no words) to hold the nickname: the likely
crash. So:
  1. keep_mousers / keep_breeders rename nobody: the kept are a list of
     unit ids in site data (lua/ai-herd.lua KEPT_KEY); upkeep() (each herd
     report, not while halted) takes autobutcher's mark off them, and the
     bridge's slaughter_one skips them;
  2. once a fort, the AI's old nicknames ('Mouser', 'Breeder', exactly) are
     cleared, their animals put on the list;
  3. pasture() and the nest boxes' penning skip pets (DF moves a pet with
     its owner).

    python tests/test_k48_named_animals.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"


def _fake(file: str, name: str) -> str:
    """A fake's Lua source from another test file, read without running it."""
    tree = ast.parse((ROOT / "tests" / file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return node.value.value
    raise KeyError(name)


def herd(halted=False):
    """lua/ai-herd.lua in test_husbandry's fake fort; ai-status answers `halted`."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(_fake("test_husbandry.py", "FAKE"), module_src("ai-herd.lua"))
    lua.execute("""local env, halted = ...
        local old = env.reqscript
        env.reqscript = function(name)
            if name == 'ai-status' then return {is_halted = function() return halted end} end
            return old(name)
        end""", env, halted)
    return lua, env, w


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


def ids(lua_set):
    return sorted(int(k) for k in lua_set.keys())


CAT, COW = 1, 2


def animals(lua, w):
    w.race(CAT, "CAT", T(lua, {"HUNTS_VERMIN": True}))
    w.race(COW, "COW", T(lua, {"GRAZER": True}))
    U = lambda **kw: w.unit(T(lua, kw))  # noqa: E731
    U(id=1, race=CAT, tame=True, sex="f", name={"nickname": "Mouser", "has_name": True})     # the AI's
    U(id=2, race=COW, tame=True, sex="f", name={"nickname": "Breeder", "has_name": True})    # the AI's
    U(id=3, race=CAT, tame=True, sex="f", name={"nickname": "Whiskers", "has_name": True})   # the player's
    U(id=4, race=CAT, tame=True, sex="m", name={"nickname": "Mousers", "has_name": True})    # not exactly
    U(id=5, race=CAT, tame=True, sex="m", dead=True, name={"nickname": "Mouser", "has_name": True})  # dead
    U(id=6, race=COW, tame=True, sex="m")


# --- 1 and 2. the kept list, the old nicknames cleared once --------------------------------------

@test("clear_ai_nicknames: exactly 'Mouser'/'Breeder' cleared (the dead too), the living fort's put on the list; once a fort")
def _():
    need_lua()
    lua, env, w = herd()
    animals(lua, w)
    r = env.clear_ai_nicknames()
    assert r.ok and r.cleared == 3, dict(r)
    nick = {int(u.id): u.name.nickname for u in w.units.values()}
    assert nick == {1: "", 2: "", 3: "Whiskers", 4: "Mousers", 5: "", 6: ""}, nick
    assert ids(env.kept_ids("mousers")) == [1] and ids(env.kept_ids("breeders")) == [2]
    assert ids(env.kept_all()) == [1, 2]
    # done once: a nickname the player gives later is theirs
    w.units[6].name.nickname = "Breeder"
    assert env.clear_ai_nicknames().unchanged
    assert w.units[6].name.nickname == "Breeder"


@test("clear_ai_nicknames: a nickname the game would not clear is tried again next time")
def _():
    need_lua()
    lua, env, w = herd()
    animals(lua, w)
    lua.execute("local env = ...; env.dfhack.units.setNickname = function() end", env)
    r = env.clear_ai_nicknames()
    assert not r.ok and r.failed == 3, dict(r)
    lua.execute("local env = ...; env.dfhack.units.setNickname = function(u, n) u.name.nickname = n end", env)
    assert env.clear_ai_nicknames().cleared == 3
    assert env.clear_ai_nicknames().unchanged


@test("upkeep: the kept animal marked by autobutcher unmarked, the gone dropped; while halted only the nicknames")
def _():
    need_lua()
    for halted in (False, True):
        lua, env, w = herd(halted)
        animals(lua, w)
        U = lambda **kw: w.unit(T(lua, kw))  # noqa: E731
        U(id=7, race=CAT, tame=True, sex="f", flags2={"slaughter": True})     # kept, then marked by autobutcher
        U(id=8, race=CAT, tame=True, sex="f", visitor=True)                   # kept, then sold to a caravan
        env.kept_save("mousers", T(lua, {7: True, 8: True, 99: True}))       # 99: gone from the map
        lua.execute("local env = ...; env.df.unit = {find = function() return nil end}", env)
        out = env.upkeep()
        assert out.nicknames.cleared == 3
        if halted:
            assert out.guard is None and w.units[7].flags2.slaughter is True
            assert ids(env.kept_ids("mousers")) == [1, 7, 8, 99]
        else:
            assert (out.guard.kept, out.guard.unmarked, out.guard.dropped) == (3, 1, 2)   # 1, 7 and the breeder 2, dict(out.guard)
            assert w.units[7].flags2.slaughter is False
            assert ids(env.kept_ids("mousers")) == [1, 7]
        assert all(u.name.nickname in ("", "Whiskers", "Mousers") for u in w.units.values())


@test("guard_kept: a dry run changes nothing")
def _():
    need_lua()
    lua, env, w = herd()
    w.race(CAT, "CAT", T(lua, {}))
    w.unit(T(lua, {"id": 7, "race": CAT, "tame": True, "sex": "f", "flags2": {"slaughter": True}}))
    env.kept_save("mousers", T(lua, {7: True, 99: True}))
    lua.execute("local env = ...; env.df.unit = {find = function() return nil end}", env)
    g = env.guard_kept(True)
    assert (g.kept, g.unmarked, g.dropped) == (1, 1, 1), dict(g)
    assert w.units[1].flags2.slaughter is True and ids(env.kept_ids("mousers")) == [7, 99]


@test("no animal renamed: the AI's Lua sets no nickname but '' (the old ones cleared)")
def _():
    pat = re.compile(r"setNickname\s*,\s*[^,]+,\s*([^)]+)\)|setNickname\(\s*[^,]+,\s*([^)]+)\)")
    for path in sorted(LUA_DIR.glob("*.lua")):
        for m in pat.finditer(path.read_text(encoding="utf-8")):
            arg = (m.group(1) or m.group(2)).strip()
            assert arg == "''", f"{path.name}: setNickname with {arg}"


@test("slaughter_one skips the animals on the AI's kept list (no nickname needed)")
def _():
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute("""local src = ...
        local env = setmetatable({}, {__index = _G})
        env.BRIDGE_VERSION = 'test'; env.OUT_DIR = '/tmp'
        env.require = function() return {} end
        local function cow(id, born) return {id = id, race = 1, birth_year = born, birth_time = 0,
            flags1 = {caged = false}, flags2 = {slaughter = false}, name = {nickname = ''}} end
        env.UNITS = {cow(1, 200), cow(2, 210), cow(3, 220), cow(4, 230), cow(5, 240)}
        env.df = {global = {world = {units = {active = env.UNITS}}},
                  creature_raw = {find = function() return {creature_id = 'COW'} end}}
        local no = function() return false end
        env.dfhack = {units = {isAnimal = function() return true end, isFortControlled = function() return true end,
            isDead = no, isPet = no, isWar = no, isHunter = no, isAdult = function() return true end, isMale = no}}
        env.reqscript = function(name)
            if name == 'ai-herd' then return {kept_all = function() return {[1] = true, [2] = true} end} end
            error('no ' .. name)
        end
        assert(load(src, 'ai-bridge-actions', 't', env))()
        return env""", (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8"))
    r = env.act_slaughter_one(lua.table_from({"oldest": True}))
    assert r.ok and r.unit_id == 3, dict(r)            # the oldest not kept (1 and 2 are the AI's)


# --- 3. pets never pastured ----------------------------------------------------------------------

@test("pasture: a pet (isPet, or a PetOwner) is never among the grazers waiting for a pasture")
def _():
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute("""local src = ...
      local list = {{id = 1}, {id = 2, pet = true}, {id = 3, relationship_ids = {PetOwner = 77}},
                    {id = 4, relationship_ids = {PetOwner = -1}}}
      for _, u in ipairs(list) do u.flags1 = {caged = false} end
      local env = setmetatable({}, {__index = _G})
      env.df = {global = {world = {units = {active = list}}}, general_ref_type = {BUILDING_CIVZONE_ASSIGNED = 1},
                unit = {find = function() return nil end}}
      env.dfhack = {units = {isAlive = function() return true end, isTame = function() return true end,
                             isOwnCiv = function() return true end, isGrazer = function() return true end,
                             isPet = function(u) return u.pet == true end,
                             getGeneralRef = function() return nil end}}
      env.reqscript = function() return {} end
      env.require = function() return {} end
      assert(load(src, 'ai-society', 't', env))()
      return env""", module_src("ai-society.lua"))
    got = env.unpastured_grazers()
    assert sorted(got[i].id for i in range(1, len(got) + 1)) == [1, 4]


@test("nest boxes: a loose pet hen is not penned with the others (DF moves it with its owner)")
def _():
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, pen1, pen2, placed, active = lua.execute(_fake("test_society.py", "NEST_FAKE"), module_src("ai-society.lua"))
    n = lua.eval("function(v) return #v end")
    loose = [u for u in active.values() if u.ref is None and u.female and not u.flags1.caged
             and u.race == 1]
    assert loose, "the fake has loose hens"
    loose[0].relationship_ids = lua.table_from({"PetOwner": 12})
    r = env.nest_boxes(3, False)
    assert r.ok and r.penned == len(loose) - 1, dict(r)
    assert n(pen2.assigned_units) + n(pen1.assigned_units) == len(loose) - 1


if __name__ == "__main__":
    finish()
