"""Tests for lua/ai-census.lua (0.104.113): what fills the map."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish, code_has  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))

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
    # (0.105.3) B: 151 scrubbable at 1-3 FPS: scrubbed while slow from 100
    # (two weeks apart); at full speed still 1,000 a month
    m.census["units"]["counts"]["dead_scrubbable"] = 300
    m.last_fired.pop("dead_units", None)
    assert [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "dead_units"]
    m.census["units"]["counts"]["dead_scrubbable"] = 60
    assert not [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "dead_units"]
    m.census["units"]["counts"]["dead_scrubbable"] = 300
    s.pop("fps_low")
    assert not [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "dead_units"]


WEBS = r"""
local env = ...
local function vec(l) local t = {_v = true}; for i, v in ipairs(l) do t[i - 1] = v end; return t end
local function web(x, y, z, flags)
    local f = {on_ground = true, spider_web = true}
    for k, v in pairs(flags or {}) do f[k] = v end
    return {pos = {x = x, y = y, z = z}, flags = f, t = 9, getType = function(self) return self.t end}
end
local webs = {
    web(50, 50, 10),                         -- inside the fort's box: kept for the weavers
    web(55, 52, 10, {forbid = true}),        -- forbidden: kept
    web(5, 5, 10),                           -- far, outside: goes
    web(100, 100, 3),                        -- a level with no building (caverns): goes
    web(101, 100, 3, {in_job = true}),       -- about to be collected: kept
    web(102, 100, 3),                        -- a creature stuck in it: kept
    web(103, 100, 3, {spider_web = false}),  -- collected thread: not a web any more
    web(104, 100, 3),                        -- goes
}
REMOVED = {}
env.df.global.world.items.other = {ANY_WEBS = vec(webs)}
env.df.global.world.buildings = {all = vec({{z = 10, x1 = 40, y1 = 40, x2 = 60, y2 = 60}})}
env.df.global.world.units.active = vec({{pos = {x = 102, y = 100, z = 3}, counters = {webbed = 30}, flags1 = {},
    flags2 = {}, race = 2, kind = 'wild'}})
env.dfhack.maps = {getTileFlags = function(x, y, z) return {hidden = z == 3} end}
env.dfhack.items = {remove = function(it) table.insert(REMOVED, it); it.flags.removed = true; return true end,
    getPosition = function(it) if it.pos then return it.pos.x, it.pos.y, it.pos.z end return nil end}
"""


@test("remove_webs (0.105.3): only loose webs outside the fort, nobody stuck, not forbidden; a batch at a time")
def _():
    LUA = LuaRuntime(unpack_returned_tuples=True)
    env = LUA.execute(FAKE, (ROOT / "lua" / "ai-census.lua").read_text(encoding="utf-8"))
    env["load"](WEBS, "w", "t", env)(env)
    w = env.webs_survey()
    assert (w.total, w.removable, w.hidden) == (8, 3, 2), (w.total, w.removable, w.hidden)
    k = w.kept
    assert (k.fort, k.forbidden, k.held, k.stuck) == (1, 1, 2, 1), dict(k)
    dry = env.remove_webs(2, True)
    assert dry.ok and dry.dry_run and len(LUA.globals().REMOVED or {}) == 0
    r = env.remove_webs(2, False)
    assert r.ok and r.removed == 2 and r.removable_left == 1 and r.more, dict(r)
    r = env.remove_webs(2, False)
    assert r.ok and r.removed == 1 and not r.more, dict(r)
    r = env.remove_webs(2, False)
    assert r.ok is False and r.rejected and "all kept" in r.error, dict(r)
    # the census counts them too, with why the rest stay
    i = env["items"]()
    assert i.counts.webs_removable == 0 and i.webs.kept.fort == 1 and i.webs.kept.gone == 3, dict(i.counts)


@test("census (0.105.3): artifacts kept at other sites counted apart, not as this map's (B: 5,992)")
def _():
    snippet = r"""
      local env = ...
      local function vec(l) local t = {_v = true}; for i, v in ipairs(l) do t[i - 1] = v end; return t end
      local function it(x, art) return {pos = {x = x, y = 1, z = 1}, flags = {on_ground = x >= 0, artifact = art},
          wear = 0, t = 4, getType = function(self) return self.t end} end
      env.df.global.world.items.all = vec({it(5, true), it(-30000, true), it(-30000, true), it(-30000, false), it(7)})
      env.df.item_type[4] = 'BOOK'
      env.dfhack.items = {getPosition = function(i) if i.pos.x < 0 then return nil end return i.pos.x, i.pos.y, i.pos.z end}
    """
    LUA = LuaRuntime(unpack_returned_tuples=True)
    env = LUA.execute(FAKE, (ROOT / "lua" / "ai-census.lua").read_text(encoding="utf-8"))
    env["load"](snippet, "a", "t", env)(env)
    c = env["items"]().counts
    assert (c.total, c.artifacts, c.artifacts_off_map, c.off_map, c.on_ground) == (5, 1, 2, 3, 2), dict(c)


@test("bridge (0.105.3): remove_webs is in the action table, max checked, the census module called")
def _():
    src = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    assert code_has(src, "    remove_webs = act_remove_webs,")
    body = src[src.index("function act_remove_webs"):]
    body = body[:body.index("\nend\n") + 5]
    LUA = LuaRuntime(unpack_returned_tuples=True)
    f = LUA.execute(r"""
      local body = ...
      local CALLS = {}
      local env = setmetatable({CALLS = CALLS}, {__index = _G})
      env.reject = function(r) return {ok = false, rejected = true, error = r} end
      env.int_in = function(v, lo, hi) v = tonumber(v); if v and v >= lo and v <= hi and v == math.floor(v) then return v end end
      env.reqscript = function(n) assert(n == 'ai-census'); return {remove_webs = function(max, dry)
          table.insert(CALLS, {max, dry}); return {ok = true, removed = 0} end} end
      assert(load(body, 'b', 't', env))()
      return env
    """, body)
    assert f.act_remove_webs(LUA.table_from({})).ok
    assert f.CALLS[1][1] == 2000 and f.CALLS[1][2] is False
    assert f.act_remove_webs(LUA.table_from({"max": 9000})).rejected
    f.act_remove_webs(LUA.table_from({"max": 500, "dry_run": True}))
    assert f.CALLS[2][1] == 500 and f.CALLS[2][2] is True


def _b_fort(slow=True):
    """B "Monastery" at the census of 2 Nov 07:38 (17,471 items, under the old 30,000 bar)."""
    from test_planner import fort  # noqa: E402
    from planner import Memory  # noqa: E402
    s = fort()
    if slow:
        s["fps_low"] = 2
    s.setdefault("logistics", {})["counts"] = {"items": 17471, "units": 429, "jobs": 300}
    s.setdefault("dead", {})["unburied"] = 0
    m = Memory()
    m.census = {"tick": s["date"]["year"] * 403200 + s["date"]["tick"],
                "units": {"counts": {"total": 429, "dead": 181, "dead_scrubbable": 151}},
                "items": {"counts": {"total": 17471, "webs": 5530, "webs_removable": 5400},
                          "webs": {"kept": {"fort": 130}},
                          "on_ground": [{"name": "THREAD", "n": 5530}, {"name": "CORPSEPIECE", "n": 76},
                                        {"name": "CORPSE", "n": 69}, {"name": "REMAINS", "n": 52}]}}
    return s, m


@test("clutter (0.105.3): B's census at 1-3 FPS: webs far off removed in batches, 151 dead scrubbed, corpses rot")
def _():
    from planner import plan, record  # noqa: E402
    s, m = _b_fort()
    got = {p.rule: p for p in plan(copy.deepcopy(s), m)[0]}
    w = got.get("remove_webs")
    assert w and w.action == {"type": "remove_webs", "max": 2000}, list(got)
    assert "5400 spider webs" in w.reason and "130 near the fort stay" in w.reason, w.reason
    assert "webs" not in got, "not DFHack's clear-webs (every web) as well"
    assert got.get("dead_units") and got["dead_units"].action == {"type": "scrub_dead_units"}, list(got)
    pr = got.get("prune")
    assert pr and "197 corpses and remains" in pr.reason, pr and pr.reason
    # a batch left more: the next in two days, not a week
    record([(w, {"ok": True, "removed": 2000, "removable_left": 3400, "webs": 3530, "more": True})], s, m)
    assert m.census["items"]["counts"]["webs_removable"] == 3400
    later = copy.deepcopy(s)
    later["date"]["tick"] += 1 * 1200
    assert not [p for p in plan(copy.deepcopy(later), m)[0] if p.rule == "remove_webs"]
    later["date"]["tick"] += 1 * 1200
    w2 = [p for p in plan(copy.deepcopy(later), m)[0] if p.rule == "remove_webs"]
    assert w2 and "3400 spider webs" in w2[0].reason, w2
    # the last batch: then a week apart, and none under 1,000 while slow
    record([(w2[0], {"ok": True, "removed": 2000, "removable_left": 900, "webs": 1530, "more": False})], later, m)
    later["date"]["tick"] += 3 * 1200
    assert not [p for p in plan(copy.deepcopy(later), m)[0] if p.rule == "remove_webs"]
    # refused (every web kept): none asked for again from the old count
    s2, m2 = _b_fort()
    w3 = [p for p in plan(copy.deepcopy(s2), m2)[0] if p.rule == "remove_webs"][0]
    record([(w3, {"ok": False, "rejected": True, "removable": 0, "error": "no loose web"})], s2, m2)
    assert m2.census["items"]["counts"]["webs_removable"] == 0


@test("clutter (0.105.3): at full speed only past the higher bars; a dwarf unburied keeps the corpses from rotting")
def _():
    from planner import plan  # noqa: E402
    s, m = _b_fort(slow=False)
    m.census["items"]["counts"]["webs_removable"] = 4000
    rules = lambda st: {p.rule for p in plan(copy.deepcopy(st), m)[0]}
    got = rules(s)
    assert not {"remove_webs", "dead_units", "prune", "webs"} & got, got
    m.census["items"]["counts"]["webs_removable"] = 6000
    m.census["units"]["counts"]["dead_scrubbable"] = 1200
    got = rules(s)
    assert {"remove_webs", "dead_units"} <= got and "prune" not in got, got
    # slow, but a citizen's body waits for a coffin: deteriorate would rot it too
    s2, m2 = _b_fort()
    s2["dead"]["unburied"] = 1
    assert "prune" not in {p.rule for p in plan(copy.deepcopy(s2), m2)[0]}
    # a census a month old says too little
    s3, m3 = _b_fort(slow=False)
    m3.census["items"]["counts"]["webs_removable"] = 6000
    m3.census["tick"] -= 30 * 1200
    assert "remove_webs" not in {p.rule for p in plan(copy.deepcopy(s3), m3)[0]}


@test("clutter (0.105.3): a census from an older bridge (no webs_removable) still clears webs the old way when heavy")
def _():
    from planner import plan  # noqa: E402
    s, m = _b_fort()
    m.census["items"]["counts"] = {"webs": 5530}
    assert "remove_webs" not in {p.rule for p in plan(copy.deepcopy(s), m)[0]}
    assert "webs" not in {p.rule for p in plan(copy.deepcopy(s), m)[0]}, "17,471 items: not heavy"
    s["logistics"]["counts"]["items"] = 40000
    w = [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "webs"]
    assert w and w[0].action == {"type": "clear_webs"}, w


@test("overseer (0.105.3): remove_webs has a short label")
def _():
    import overseer  # noqa: E402
    assert overseer.short({"type": "remove_webs", "max": 2000}) == "remove spider webs far from the fort"


if __name__ == "__main__":
    finish()
