"""Tests for the idle-crafting switch in lua/ai-society.lua (pip install lupa).

    python tests/test_idle_crafting.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from lua_modules_util import module_src  # (13c lua-modules) the modules' sources, with lua/ai-util.lua
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

SRC = module_src("ai-society.lua")
FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local saved, calls = {}, {}
local function shop(id, t, permitted)
    return {id = id, type = t, profile = {permitted_workers = permitted or {}},
            getType = function() return 1 end, getBuildStage = function() return 3 end,
            getMaxBuildStage = function() return 3 end}
end
env.SAVED, env.CALLS = saved, calls
env.SC_MAP_LOADED = 7
env.df = {building_type = {Workshop = 1}, workshop_type = {Craftsdwarfs = 5},
          global = {world = {buildings = {other = {WORKSHOP_ANY = {shop(10, 2), shop(11, 5, {99}), shop(12, 5), shop(13, 5)}},
                                          all = {}}}}}
env.dfhack = {persistent = {getSiteData = function(k, d) return saved[k] or d end,
                            saveSiteData = function(k, v) saved[k] = v end},
              onStateChange = {['idle-crafting'] = function(sc) table.insert(calls, sc) end}}
env.reqscript = function(name) return {} end
env.require = function(name) return {} end
assert(load(src, 'ai-society', 't', env))()
return env
"""


@test("idle crafting: the first Craftsdwarf's workshop open to anyone is allowed, saved, and the tool started")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(FAKE, SRC)
    assert env.idle_crafting_status().workshops == 0
    d = env.idle_crafting(True)
    assert d.ok and d.dry_run and d.workshop == 12, dict(d)          # 11 has a master assigned
    r = env.idle_crafting(False)
    assert r.ok and env.SAVED["idle-crafting"].enabled and env.SAVED["idle-crafting"].allowed["12"] == -1
    assert env.CALLS[1] == 7
    st = env.idle_crafting_status()
    assert st.enabled and st.workshops == 2 and r.added == 2, (st.workshops, r.added)   # every free one
    assert not env.idle_crafting(False).ok                            # none left to add
    assert env.craft_shops() == 3


TRINKET_FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local function item(id, value, flags, owner, container)
    return {id = id, value = value, flags = flags or {on_ground = true}, owner = owner, container = container}
end
local bin = {flags = {on_ground = true}}
env.ITEMS = {RING = {item(1, 50), item(2, 500, {on_ground = true, forbid = true}), item(3, 300, {}, nil, bin)},
             FIGURINE = {item(4, 80, {on_ground = true}, 'someone'), item(5, 20, {trader = true, on_ground = true})}}
local function unit(id, focus, adult)
    return {id = id, mood = -1, adult = adult ~= false,
            status = {current_soul = {personality = {needs = {{id = 9, focus_level = focus}}}}}}
end
env.UNITS = {unit(1, -5000), unit(2, -20000), unit(3, 200), unit(4, -3000, false)}
env.OWNED = {}
env.df = {need_type = {[9] = 'AcquireObject'}, global = {world = {items = {other = env.ITEMS}}}}
env.dfhack = {persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end},
              units = {getCitizens = function() return env.UNITS end, isAdult = function(u) return u.adult end},
              items = {getOwner = function(i) return i.owner end, getContainer = function(i) return i.container end,
                       getValue = function(i) return i.value end,
                       setOwner = function(i, u) env.OWNED[i.id] = u.id; i.owner = u; return true end}}
env.reqscript = function(name) return {} end
env.require = function(name) return {} end
assert(load(src, 'ai-society', 't', env))()
return env
"""


@test("trinkets: free ones only (not forbidden, owned, the traders'), the most valuable to the most distracted")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(TRINKET_FAKE, SRC)
    assert len(env.free_trinkets()) == 2                              # 1 loose, 3 in a bin
    d = env.give_trinkets(10, True)
    assert d.ok and d.would_give == 2 and d.wanting == 2, dict(d)      # unit 3 is content, unit 4 a child
    r = env.give_trinkets(10, False)
    assert r.ok and r.given == 2 and r.trinkets_left == 0, dict(r)
    assert env.OWNED[3] == 2 and env.OWNED[1] == 1, dict(env.OWNED)    # worth 300 to the worst off
    assert env.UNITS[2].status.current_soul.personality.needs[1].focus_level == 400
    assert not env.give_trinkets(10, False).ok                         # nobody wants one now


@test("trinkets: a dwarf gets the one they like (its material) before a dearer one")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(TRINKET_FAKE, SRC)
    env.df.unitpref_type = lua.eval("{[0] = 'LikeMaterial', [4] = 'LikeItem'}")   # (13c) the real global enum
    for it in env.ITEMS.RING.values():
        lua.execute("local it = ...; it.getMaterial = function() return 0 end; "
                    "it.getMaterialIndex = function(self) return self.id end", it)
    worst = env.UNITS[2]                                              # the most distracted
    worst.status.current_soul.preferences = lua.eval("{{type = 0, mattype = 0, matindex = 1}}")
    r = env.give_trinkets(10, False)
    assert r.given == 2 and r.liked == 1, dict(r)
    assert env.OWNED[1] == 2 and env.OWNED[3] == 1, dict(env.OWNED)   # the cheap ring it likes


STAFF_FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local real = ipairs
local function vec(l)
    local t = {_v = true}
    for i, v in real(l or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
        __index = {insert = function(self, at, v) self[#self] = v end,
                   erase = function(self, at) local n = #self; for i = at, n - 2 do self[i] = self[i + 1] end; self[n - 1] = nil end}})
end
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, '_v') then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return real(t)
end
local post = {id = 70, type = 7, histfig_id = -1, unit_id = -1}
local hosp = {id = 3, occupations = vec({{id = 69, type = 8, histfig_id = 5, unit_id = 1}, post})}
local function unit(id, hf, skill, extra)
    local u = {id = id, hist_figure_id = hf, skill = skill, military = {squad_id = -1}, mood = -1, occupations = vec(),
               adult = true}
    for k, v in pairs(extra or {}) do u[k] = v end
    return u
end
local units = {unit(1, 5, 9, {occupations = vec({{id = 69}})}), unit(2, 6, 3), unit(3, 7, 7, {military = {squad_id = 32}}),
               unit(4, 8, 5), unit(5, 9, 12, {adult = false}), unit(6, 10, 11, {noble = true})}
env.UNITS, env.POST = units, post
env.df = {occupation_type = {[7] = 'DIAGNOSTICIAN', [8] = 'DOCTOR'}, job_skill = {DIAGNOSE = 1}}
env.dfhack = {world = {getCurrentSite = function() return {buildings = vec({hosp})} end},
              units = {getCitizens = function() return units end, isAdult = function(u) return u.adult end,
                       getNominalSkill = function(u, sk) return u.skill end,
                       getNoblePositions = function(u) return u.noble and {{}} or nil end,
                       getReadableName = function(u) return 'dwarf ' .. u.id end},
              persistent = {getSiteData = function(_, d) return d end}}
env.reqscript = function() return {} end
env.require = function() return {} end
assert(load(src, 'ai-society', 't', env))()
return env
"""


@test("staffing: a vacant post goes to the free dwarf best at it (no child, soldier, noble or post holder)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(STAFF_FAKE, SRC)
    d = env.staff_location(3, "DIAGNOSTICIAN", True)
    assert d.ok and d.dry_run and d.unit_id == 4 and d.post == "diagnostician", dict(d)
    r = env.staff_location(3, "DIAGNOSTICIAN", False)
    assert r.ok and env.POST.unit_id == 4 and env.POST.histfig_id == 8, dict(r)
    assert env.UNITS[4].occupations[0].id == 70
    again = env.staff_location(3, "DIAGNOSTICIAN", False)
    assert not again.ok and "no vacant" in again.error, dict(again)
    assert not env.staff_location(3, "PERFORMER", False).ok
    assert not env.staff_location(99, "DOCTOR", False).ok


@test("0.104.111: a wounded dwarf is passed over for a post; a patient doctor's post is given back")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(STAFF_FAKE, SRC)
    # (0.104.150) an old scar is no bar: only bleeding or a treatment waiting
    lua.execute("local env = ...; env.UNITS[4].body = {wounds = {_v = true, [0] = {}}, blood_count = 100, blood_max = 100}; "
                "env.UNITS[4].body.wounds = setmetatable(env.UNITS[4].body.wounds, {__len = function() return 1 end}); "
                "env.df.unit = {find = function(id) for _, u in pairs(env.UNITS) do if u.id == id then return u end end end}",
                env)
    d = env.staff_location(3, "DIAGNOSTICIAN", True)
    assert d.ok and d.unit_id == 4, dict(d)                          # unit 4 only scarred
    lua.execute("local env = ...; env.UNITS[4].health = {flags = {needs_healthcare = true, rq_suture = true}}", env)
    d = env.staff_location(3, "DIAGNOSTICIAN", True)
    assert d.ok and d.unit_id == 2, dict(d)                          # unit 4 waits for stitches
    lua.execute("local env = ...; env.UNITS[4].health = {flags = {needs_healthcare = true}}; env.UNITS[4].body.blood_count = 60", env)
    d = env.staff_location(3, "DIAGNOSTICIAN", True)
    assert d.ok and d.unit_id == 2, dict(d)                          # bleeding
    lua.execute("local env = ...; env.UNITS[4].body.blood_count = 100", env)
    d = env.staff_location(3, "DIAGNOSTICIAN", True)
    assert d.ok and d.unit_id == 4, dict(d)                          # only infected: he works, so he may staff
    v = env.vacate_post(3, 1, False)
    assert v.ok and v.post == "doctor", dict(v)
    assert len(env.UNITS[1].occupations) == 0
    again = env.vacate_post(3, 1, False)
    assert not again.ok and "no post" in again.error


@test("occupation probe: the world's posts with their fields and the holder's links that point at them")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(STAFF_FAKE, SRC)
    lua.execute("""local env = ...
        local real = ipairs
        local function vec(l) local t = {_v = true}; for i, v in real(l) do t[i - 1] = v end
            return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end}) end
        local occ = {id = 40, type = 8, histfig_id = 5, unit_id = 1, location_id = 1, site_id = 7, group_id = 77}
        env.df.global = {occupation_next_id = 41, world = {occupations = {all = vec({occ})}}}
        env.df.abstract_building_type = {[1] = 'HOSPITAL'}
        env.df.historical_figure = {find = function() return {entity_links = vec({{_type = 'histfig_entity_link_occupationst',
            entity_id = 77, link_strength = 100, occupation_id = 40}}), site_links = vec({}),
            getOccupation = function() return 40 end} end}
        env.df.unit = {find = function() return {id = 1, occupations = vec({{id = 40}})} end}
        env.dfhack.world.getCurrentSite = function() return {id = 7, buildings = vec({{id = 1, occupations = vec({occ}),
            getType = function() return 1 end}})} end""", env)
    r = env.probe_occupations()
    assert r.total == 1 and r.next_id == 41, dict(r)
    e = r.here[1]
    assert e.type == "DOCTOR" and e.group_id == 77 and e.unit_lists_it and e.hf_occupation == 40, dict(e)
    assert e.links[1].fields.entity_id == 77 and "occupationst" in e.links[1].kind
    assert r.locations[1].type == "HOSPITAL" and r.locations[1].posts == 1


@test("add posts: a vacant record of each missing kind, as the game makes them; none that exists, none of other kinds")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(STAFF_FAKE, SRC)
    lua.execute("""local env = ...
        local real = ipairs
        local function vec(l) local t = {_v = true}; for i, v in real(l) do t[i - 1] = v end
            return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
                __index = {insert = function(self, at, v) self[#self] = v end}}) end
        local occs = vec({})
        local tav = {id = 0, occupations = vec({}), getType = function() return 5 end}
        env.TAV, env.ALL = tav, occs
        env.df.global = {occupation_next_id = 42, world = {occupations = {all = occs}}}
        env.df.abstract_building_type = {[5] = 'INN_TAVERN', INN_TAVERN = 5}
        env.df.occupation_type = {TAVERN_KEEPER = 0, PERFORMER = 1, [0] = 'TAVERN_KEEPER', [1] = 'PERFORMER'}
        env.df.occupation = {new = function() return {} end}
        env.dfhack.world.getCurrentSite = function() return {id = 239, buildings = vec({tav})} end""", env)
    d = env.add_posts(0, None, True)
    assert d.ok and d.dry_run and d.posts[1] == "TAVERN_KEEPER", dict(d)
    r = env.add_posts(0, None, False)
    assert r.ok and r.posts[1] == "TAVERN_KEEPER", dict(r)
    o = env.TAV.occupations[0]
    assert o.id == 42 and o.type == 0 and o.histfig_id == -1 and o.unit_id == -1 and o.location_id == 0
    assert o.site_id == 239 and o.group_id == -1 and env.ALL[0].id == 42 and env.df["global"].occupation_next_id == 43
    again = env.add_posts(0, None, False)
    assert not again.ok and "no post to add" in again.error
    assert not env.add_posts(0, lua.table_from(["PERFORMER"]), False).ok       # not a kind the AI staffs


@test("post labours (0.87.3): holders get their post's labours; none twice; new staff get them when seated")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(STAFF_FAKE, SRC)
    lua.execute("""local env = ...
        env.df.unit_labor = {DIAGNOSE = 1, SURGERY = 2, BONE_SETTING = 3, SUTURING = 4, DRESSING_WOUNDS = 5}
        for _, u in ipairs(env.UNITS) do u.status = {labors = {}} end
        env.UNITS[1].status.labors[1] = false
        env.df.unit = {find = function(id) for _, u in ipairs(env.UNITS) do if u.id == id then return u end end end}""", env)
    r = env.staff_location(3, "DIAGNOSTICIAN", False)
    assert r.ok and r.labors[1] == "DIAGNOSE" and env.UNITS[4].status.labors[1] is True, dict(r)
    g = env.staff_labors(3, False)                                   # the doctor (unit 1) held the post already
    assert g.ok and g.given[1].post == "doctor" and len(list(g.given[1].labors.values())) == 5, dict(g)
    assert not env.staff_labors(3, False).ok                          # nothing left to give


if __name__ == "__main__":
    finish()
