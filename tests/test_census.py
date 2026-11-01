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


@test("census (0.104.158): the herd by kind (marked, pets, named, trained, kids) and the dead fix/dead-units would scrub")
def _():
    snippet = """
      local env = ...
      local function a(race, t) local x = {race = race, kind = 'tame', flags1 = {}, flags2 = {}, hist_figure_id = -1,
          name = {has_name = t.named or false, nickname = ''}}; for k, v in pairs(t) do x[k] = v end; return x end
      local function d(race, own, hf) return {race = race, kind = 'dead', own = own, flags1 = {}, flags2 = {},
          hist_figure_id = hf or -1} end
      local l = {a(6, {marked = true}), a(6, {}), a(6, {kid = true}), a(3, {pet = true}), a(3, {named = true}),
                 a(7, {war = true}), d(6, false), d(6, false), d(1, true, 5)}
      local t = {_v = true}; for i, v in ipairs(l) do t[i - 1] = v end
      env.df.global.world.units.active = t
      env.RACES[6], env.RACES[7] = 'BIRD_DUCK', 'DOG'
      local U = env.dfhack.units
      U.isMarkedForSlaughter = function(x) return x.marked == true end
      U.isPet = function(x) return x.pet == true end
      U.isWar = function(x) return x.war == true end
      U.isHunter = function() return false end
      U.isAdult = function(x) return not x.kid end
      U.isOwnRace = function(x) return x.own == true end
      U.isOwnCiv = function(x) return x.own == true end
    """
    LUA = LuaRuntime(unpack_returned_tuples=True)
    env2 = LUA.execute(FAKE.replace("local RACES =", "RACES ="), (ROOT / "lua" / "ai-census.lua").read_text(encoding="utf-8"))
    env2.RACES = LUA.globals().RACES
    env2["load"](snippet, "t", "t", env2)(env2)
    r = env2.units()
    c = r.counts
    assert (c.tame, c.marked, c.dead, c.dead_scrubbable) == (6, 1, 3, 2), dict(c)
    herd = {h.name: h for h in r.herd.values()}
    duck = herd["BIRD_DUCK"]
    assert (duck.n, duck.marked, duck.kids, duck.protected) == (3, 1, 1, 0), dict(duck)
    cat = herd["CAT"]
    assert (cat.n, cat.pet, cat.named, cat.protected) == (2, 1, 1, 2), dict(cat)
    assert herd["DOG"].trained == 1


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


@test("prune (0.104.115): thousands of bones on the ground and worn clothes rot too; without the census only the old way")
def _():
    from test_planner import fort  # noqa: E402
    from planner import Memory, plan  # noqa: E402
    s = fort()
    s["fps_low"] = 15
    s.setdefault("logistics", {})["counts"] = {"items": 50000, "units": 7800, "jobs": 600}
    s.setdefault("buildings", {}).setdefault("zones", {})["Dump"] = 1
    prune = lambda m: [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "prune"]
    got = prune(Memory())
    assert got and got[0].action == {"type": "prune_remains"}, got
    m = Memory()
    m.census = {"tick": s["date"]["year"] * 403200 + s["date"]["tick"],
                "items": {"on_ground": [{"name": "THREAD", "n": 10361}, {"name": "CORPSEPIECE", "n": 7227}],
                          "worn": [{"name": "SHOES", "n": 177}, {"name": "ARMOR", "n": 160}]}}
    got = prune(m)
    assert got and got[0].action == {"type": "prune_remains", "extra": ["usable-parts", "clothes"]}, got
    assert "7227 bones" in got[0].reason, got[0].reason
    # (0.104.116) webs by the thousand: cleared, not again for a season
    m.census["items"]["counts"] = {"webs": 10361}
    w = [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "webs"]
    assert w and w[0].action == {"type": "clear_webs"}, w
    from planner import record  # noqa: E402
    record([(w[0], {"ok": True, "removed": 10361})], s, m)
    assert not [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "webs"]


@test("herd (0.104.158): nestboxes off past the fort's herd, back on only under half; dead units scrubbed a month apart")
def _():
    from test_planner import fort  # noqa: E402
    from planner import Memory, plan, record  # noqa: E402
    s = fort()
    s["tools"]["nestboxes"] = True
    s["others_on_map"]["tame_animals"] = 1121
    cit = s["dwarves"]["total"]
    herd = lambda st, m=None: [p for p in plan(copy.deepcopy(st), m or Memory())[0] if p.rule == "herd"]
    got = herd(s)
    assert got and got[0].action == {"type": "tool", "name": "nestboxes", "enabled": False}, got
    assert "1121 tame animals" in got[0].reason, got[0].reason
    s["others_on_map"]["tame_animals"] = 40
    assert not herd(s)
    # off, and the herd still big: nestboxes not wanted back on
    s["tools"]["nestboxes"] = False
    s["others_on_map"]["tame_animals"] = int(max(60, cit * 2) * 0.8)
    tools_on = [p for p in plan(copy.deepcopy(s), Memory())[0] if p.rule == "tools" and p.action.get("name") == "nestboxes"]
    assert not tools_on, [p.action for p in tools_on]
    s["others_on_map"]["tame_animals"] = 10
    tools_on = [p for p in plan(copy.deepcopy(s), Memory())[0] if p.rule == "tools" and p.action.get("name") == "nestboxes"]
    assert tools_on, "nestboxes back on with a small herd"
    # dead units: from the census, once a month
    s["fps_low"] = 17
    s.setdefault("logistics", {})["counts"] = {"items": 36000, "units": 8627, "jobs": 124}
    m = Memory()
    m.census = {"tick": s["date"]["year"] * 403200 + s["date"]["tick"],
                "units": {"counts": {"total": 8627, "dead": 7322, "dead_scrubbable": 6600}}, "items": {}}
    d = [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "dead_units"]
    assert d and d[0].action == {"type": "scrub_dead_units"} and "7322 of the 8627" in d[0].reason, d
    record([(d[0], {"ok": True, "removed": 6500})], s, m)
    assert not [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "dead_units"]
    m.census["units"]["counts"]["dead_scrubbable"] = 300
    m.last_fired.pop("dead_units", None)
    assert not [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "dead_units"]


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
