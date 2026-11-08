"""(0.105.0) Tests for the gate watcher's state kept with the save
(lua/ai-gates.lua, gates_persist / gates_restore), with a fake game, in a real
Lua engine (pip install lupa).

    python tests/test_gates_save.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from lua_modules_util import module_src  # (13c lua-modules) the modules' sources, with lua/ai-util.lua
RESULTS = []

try:
    from lupa import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

HARNESS = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local W = {persist = {}, pulls = {}, bridges = {}, doors = {}}
env.CR_OK = 0
env.df = {building = {find = function(id) return W.bridges[id] or W.doors[id] end},
          job_type = {PullLever = 1},
          global = {world = {units = {active = {}}}, cur_year_tick = 0}}
env.dfhack = {persistent = {getSiteData = function(k, d) local v = W.persist[k]; if v == nil then return d end; return v end,
                            saveSiteData = function(k, v) W.persist[k] = v end},
              run_command_silent = function(cmd, a, b, id) table.insert(W.pulls, tonumber(id)); return '', 0 end,
              timeout = function() return 1 end, timeout_active = function() return false end,
              units = {getCitizens = function() return {} end, isAlive = function() return true end},
              gui = {showAnnouncement = function() end}}
assert(load(src, 'ai-gates', 't', env))()
-- the original summary walks the map: a stub
env.GATES_ORIG.summary = function() return {scanned = env.GATES.scanned == true, armed = env.GATES.armed == true} end
return env, W
"""


def fresh():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, W = lua.execute(HARNESS, module_src("ai-gates.lua"))
    return lua, env, W


def entrance(lua, eid=1, bridge=10, lever=55, door=11):
    return lua.table_from({"id": eid, "x": 5, "y": 5, "z": 0, "outs": lua.table(), "equipment": lua.table_from({
        1: lua.table_from({"id": bridge, "kind": "bridge", "lever_id": lever}),
        2: lua.table_from({"id": door, "kind": "door"})})})


def setup_fort(lua, env, W, armed=True, closed=True):
    W.bridges[10] = lua.table_from({"gate_flags": lua.table_from({"raised": closed}), "jobs": lua.table(),
                                    "x1": 5, "x2": 5, "y1": 5, "y2": 5, "z": 0})
    W.doors[11] = lua.table_from({"door_flags": lua.table_from({"forbidden": closed})})
    env.GATES = lua.table_from({"scanned": True, "armed": armed, "entrances": lua.table_from({1: entrance(lua)}),
                                "closed": lua.table_from({1: True} if closed else {})})


def unload(lua, env):
    lua.execute("local env = ...; env.GATES = {scanned = false}; env.GATES_SAVE = {}", env)


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


@test("the watcher's state goes into the save when it changes, by building id")
def _():
    lua, env, W = fresh()
    setup_fort(lua, env, W)
    env.summary()                                   # (the save read back first: nothing there)
    saved = W.persist["ai-overseer/gates"]
    assert saved is not None and saved.armed is True, saved
    ids = sorted(saved.gates[i].id for i in range(1, len(saved.gates) + 1))
    assert ids == [10, 11], ids
    W.persist["ai-overseer/gates"] = None
    env.check()
    assert W.persist["ai-overseer/gates"] is None, "written again though nothing changed"


@test("a fresh map never writes over the save before reading it back")
def _():
    lua, env, W = fresh()
    W.persist["ai-overseer/gates"] = lua.table_from({"armed": True, "gates": lua.table_from({
        1: lua.table_from({"id": 10, "kind": "bridge", "lever_id": 55})})})
    env.GATES = lua.table_from({"scanned": False})
    assert env.gates_persist() is False
    r = env.summary()
    assert r.saved_closed == 1 and r.armed is True, (r.saved_closed, r.armed)
    assert W.persist["ai-overseer/gates"].armed is True        # still the save's


@test("raised before a reload, no scan yet: open_gates lowers the bridge from the save (its lever pulled)")
def _():
    lua, env, W = fresh()
    setup_fort(lua, env, W)
    env.summary()
    unload(lua, env)
    W.pulls = lua.table()
    r = env.open_all()
    assert r.ok and list(W.pulls.values()) == [55], (dict(r), list(W.pulls.values()))
    assert W.doors[11].door_flags.forbidden is False
    assert W.persist["ai-overseer/gates"].armed is False


@test("after a reload and a new scan: the watcher re-armed and the closed entrance known again (open_all opens it)")
def _():
    lua, env, W = fresh()
    setup_fort(lua, env, W)
    env.summary()
    unload(lua, env)
    # the new scan numbers the entrance anew (id 4), same gates
    env.GATES = lua.table_from({"scanned": True, "entrances": lua.table_from({1: entrance(lua, eid=4)}),
                                "closed": lua.table()})
    r = env.summary()
    assert env.GATES.armed is True and env.GATES.closed[4] is True, (env.GATES.armed, env.GATES.closed[4])
    assert r.restored.armed is True and r.restored.gates == 2, r.restored
    W.pulls = lua.table()
    env.open_all()
    assert list(W.pulls.values()) == [55], list(W.pulls.values())
    assert W.persist["ai-overseer/gates"].armed is False


@test("nothing saved (a new fort): nothing restored, nothing opened")
def _():
    lua, env, W = fresh()
    env.GATES = lua.table_from({"scanned": False})
    r = env.summary()
    assert r.saved_closed is None and r.restored is None
    r = env.open_all()
    assert r.ok and r.opened == 0


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
