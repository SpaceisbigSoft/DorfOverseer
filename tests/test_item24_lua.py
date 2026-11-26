"""(R30c item24) The Lua side of squad_fill's pool: draft_pool_ids is the fill's own
loosest test (candidates, draft_bar, post_bar), so a fill whose `avoid` holds every
id it lists finds nobody to try. In a real Lua engine (pip install lupa).

    python tests/test_item24_lua.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from lua_modules_util import module_src  # noqa: E402
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)


# (the fill's world of tests/test_military.py: 1 miserable and keen, 2 very unhappy and keen,
# 3 content and keen, 4 content, 5 a noble, 6 a patient)
LUA = LuaRuntime(unpack_returned_tuples=True)


def _fill_env():
    return LUA.execute(r"""
    local src = ...
    local env = setmetatable({}, {__index = _G})
    assert(load(src, 'ai-military', 't', env))()
    local added = {}
    local function vec(t) t = t or {}; return setmetatable(t, {__len = function(v) local n = 0
        while rawget(v, n) ~= nil do n = n + 1 end return n end}) end
    local function zl(...) local t = {}; for i, v in ipairs({...}) do t[i - 1] = v end return vec(t) end
    local function dwarf(id, stress, focus, o)
        o = o or {}
        return {id = id, stress = stress, military = {squad_id = -1}, relationship_ids = {Mother = -1}, noble = o.noble,
                status = {current_soul = {skills = zl(), personality = {needs = zl({id = 5, focus_level = focus})}}},
                health = o.sick and {flags = {needs_healthcare = true}} or nil}
    end
    -- 1 miserable and keen, 2 very unhappy and keen, 3 content and keen, 4 content, not keen,
    -- 5 keen but a noble, 6 keen but a patient
    local citizens = {dwarf(1, 0, -20000), dwarf(2, 1, -20000), dwarf(3, 3, -20000), dwarf(4, 5, 0),
                      dwarf(5, 4, -20000, {noble = true}), dwarf(6, 4, -20000, {sick = true})}
    local sq = {id = 10, orders = zl(), positions = zl({occupant = 99}, {occupant = -1}, {occupant = -1}, {occupant = -1})}
    env.ipairs = function(t)
        if getmetatable(t) then return function(v, i) i = i + 1; if rawget(v, i) ~= nil then return i, v[i] end end, t, -1 end
        return ipairs(t)
    end
    env.df = {squad = {find = function(id) return id == 10 and sq or nil end}, job_skill = {}, need_type = {[5] = 'MartialTraining'},
        global = {plotinfo = {group_id = 1}}, historical_entity = {find = function() return {squads = zl(10)} end}}
    env.dfhack = {units = {getCitizens = function() return citizens end, isAdult = function() return true end,
            isBaby = function() return false end,
            getNoblePositions = function(u) if u.noble then return {{}} end return {} end,
            getStressCategory = function(u) return u.stress end, getReadableName = function(u) return 'd' .. u.id end},
        military = {addToSquad = function(id) table.insert(added, id); return true end}}
    env.CITIZENS = citizens
    return env, added
    """, module_src("ai-military.lua"))


def _ids(t):
    return sorted(t[i] for i in range(1, len(t) + 1))


@test("item24 draft_pool_ids: the fill's loosest pool (no miserable, very unhappy, noble or patient)")
def _():
    env, _ = _fill_env()
    assert _ids(env.draft_pool_ids()) == [3, 4], _ids(env.draft_pool_ids())


@test("item24 draft_pool_ids: a fill avoiding every id it lists tries nobody; avoiding one, drafts the other")
def _():
    env, added = _fill_env()
    avoid = LUA.table_from({3: True, 4: True})
    r = env.fill(10, 2, env.tostring, avoid)
    assert not r.ok and "0 tried" in r.error, dict(r)
    env, added = _fill_env()
    r = env.fill(10, 2, env.tostring, LUA.table_from({3: True}))
    assert r.ok and _ids(added) == [4], (dict(r), _ids(added))


@test("item24 report: military.draft_pool and draft_ids from draft_pool_ids")
def _():
    env, _ = _fill_env()
    ids = env.draft_pool_ids()
    assert len(ids) == 2 and env.DRAFT_IDS_MAX == 200


if __name__ == "__main__":
    finish()
