"""Tests for lua/ai-census.lua (0.104.113): what fills the map."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
RESULTS = []

FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local function vec(l) local t = {_v = true}; for i, v in ipairs(l) do t[i - 1] = v end; return t end
local real = ipairs
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, '_v') then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return real(t)
end
local function u(race, kind) return {race = race, kind = kind, flags1 = {caged = kind == 'caged'}, flags2 = {}} end
local units = vec({u(1, 'cit'), u(1, 'cit'), u(2, 'dead'), u(2, 'dead'), u(2, 'dead'), u(3, 'tame'), u(4, 'wild'),
                   u(4, 'wild'), u(5, 'caged')})
local function it(t, flags, wear) return {t = t, flags = flags or {on_ground = true}, wear = wear or 0,
    getType = function(self) return self.t end} end
local items = vec({it(1), it(1, {on_ground = true, forbid = true}), it(2, {in_building = true}), it(3, nil, 3),
                   it(3, {garbage_collect = true})})
local RACES = {[1] = 'DWARF', [2] = 'GOBLIN', [3] = 'CAT', [4] = 'GIANT_BAT', [5] = 'TROLL'}
env.df = {global = {world = {units = {active = units}, items = {all = items}, jobs = {list = {next = {next = nil}}}}},
          creature_raw = {find = function(r) return {creature_id = RACES[r]} end},
          item_type = {[1] = 'BOULDER', [2] = 'BED', [3] = 'PANTS'}}
env.dfhack = {units = {isDead = function(x) return x.kind == 'dead' end, isActive = function() return true end,
                       isCitizen = function(x) return x.kind == 'cit' end, isTame = function(x) return x.kind == 'tame' end,
                       isDomesticated = function() return false end, isDanger = function() return false end,
                       isVisitor = function() return false end, isMerchant = function() return false end,
                       isDiplomat = function() return false end, isAnimal = function(x) return x.kind == 'wild' end}}
assert(load(src, 'ai-census', 't', env))()
return env
"""


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


@test("census: creatures by kind and race, items by type and state")
def _():
    env = LuaRuntime(unpack_returned_tuples=True).execute(FAKE, (ROOT / "lua" / "ai-census.lua").read_text(encoding="utf-8"))
    r = env.census()
    c = r.units.counts
    assert (c.total, c.citizens, c.dead, c.tame, c.wild, c.caged) == (9, 2, 3, 1, 2, 1), dict(c)
    assert r.units.dead[1].name == "GOBLIN" and r.units.dead[1].n == 3
    i = r["items"].counts
    assert (i.total, i.forbidden, i.in_buildings, i.worn, i.on_ground) == (4, 1, 1, 1, 3), dict(i)
    assert r["items"].types[1].name == "BOULDER" and r["items"].types[1].n == 2
    assert r.jobs == 1


@test("census rule: once a week while the game runs slowly; the result kept")
def _():
    from test_planner import fort  # noqa: E402
    from planner import Memory, plan, record  # noqa: E402
    s = fort()
    s["fps_low"] = 15
    s.setdefault("logistics", {})["counts"] = {"items": 42000, "units": 6500, "jobs": 5000}
    m = Memory()
    got = [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "census"]
    assert got and got[0].action == {"type": "census"}, got
    record([(got[0], {"ok": True, "units": {"counts": {"total": 6500}}, "items": {}, "jobs": 5000})], s, m)
    assert m.census["units"]["counts"]["total"] == 6500
    assert not [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "census"]


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
