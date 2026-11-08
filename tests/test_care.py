"""(0.104.168) Tests for disease and care (lua/ai-health.lua) and the military
offices refilled (lua/ai-nobles.lua), in a real Lua engine with a small fake
of the game's records (pip install lupa).

    python tests/test_care.py
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

NOBLES = module_src("ai-nobles.lua")
HEALTH = module_src("ai-health.lua")


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


VEC = r"""
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {
        __len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
        __index = {
            insert = function(self, at, v)
                local n = #self
                if at == '#' then at = n end
                if type(v) == 'table' and v.new then
                    local cls = v.new; v.new = nil; setmetatable(v, {__index = {delete = function() end}}); v._cls = cls
                end
                for i = n, at + 1, -1 do self[i] = self[i - 1] end
                self[at] = v
            end,
            erase = function(self, at)
                local n = #self
                for i = at, n - 2 do self[i] = self[i + 1] end
                self[n - 1] = nil
            end}})
end
local function zipairs(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
"""

# --- the military offices (lua/ai-nobles.lua) ---------------------------------

NOBLES_FAKE = VEC + r"""
local src, spec = ...
local LINK = {}
local SK = {MILITARY_TACTICS = 1, LEADERSHIP = 2, MELEE_COMBAT = 3, DISCIPLINE = 4, ORGANIZATION = 5}
local positions, assignments = vec(), vec()
-- spec.positions: {code, id, by = {position ids}, civ = entity id of the appointer, flags}
for _, p in ipairs(spec.positions) do
    local civs = {}
    for _ in ipairs(p.by or {}) do table.insert(civs, p.civ or 77) end
    positions:insert('#', {id = p.id, code = p.code, appointed_by = vec(p.by or {}), appointed_by_civ = vec(civs),
                           flags = p.flags or {}})
end
for _, a in ipairs(spec.assignments) do
    assignments:insert('#', {id = a.id, position_id = a.pos, histfig = a.hf or -1, squad_id = a.squad or -1})
end
local ent = {id = 77, positions = {own = positions, assignments = assignments}, assignments_by_type = vec()}
local figs, units = {}, {}
for _, u in ipairs(spec.units) do
    figs[u.hf] = {id = u.hf, entity_links = vec(), name = 'fig' .. u.hf}
    local skills = {}
    for _, s in ipairs(u.skills or {}) do table.insert(skills, {id = SK[s[1]], rating = s[2]}) end
    local needs = {}
    if u.fight then table.insert(needs, {id = 1, focus_level = -5000}) end
    table.insert(units, {id = u.id, hist_figure_id = u.hf, child = u.child, baby = u.baby, stress = u.stress or 4,
                         military = {squad_id = u.squad or -1}, relationship_ids = {Mother = u.mother or -1},
                         occupations = u.staff and {{id = 1}} or {},
                         health = {flags = {needs_healthcare = u.patient == true}},
                         body = {wounds = u.wounds and {{id = 1}} or {}},   -- (0.105.24) the messenger is healthy
                         status = {current_soul = {skills = skills, personality = {needs = needs}}}})
end
for _, f in pairs({}) do end
-- the existing holders' links
for i = 0, #assignments - 1 do
    local a = assignments[i]
    if a.histfig ~= -1 and figs[a.histfig] then
        local l = {assignment_id = a.id}; l._cls = LINK
        figs[a.histfig].entity_links:insert('#', l)
    end
end
local function noble_positions(u)
    local out = {}
    local hf = figs[u.hist_figure_id]
    for i = 0, #hf.entity_links - 1 do
        local l = hf.entity_links[i]
        if l._cls == LINK then
            for j = 0, #assignments - 1 do
                local a = assignments[j]
                if a.id == l.assignment_id and a.histfig == hf.id then
                    for k = 0, #positions - 1 do
                        if positions[k].id == a.position_id then
                            table.insert(out, {position = positions[k], assignment = a})
                        end
                    end
                end
            end
        end
    end
    return out
end
local squads = {}
for _, sq in ipairs(spec.squads or {}) do squads[sq] = {id = sq} end
local seated = {}
local env = setmetatable({}, {__index = _G})
env.df = {
    global = {plotinfo = {group_id = 77}, cur_year = 50, cur_year_tick = 10, hist_event_next_id = 1,
              world = {history = {events = vec()}}},
    historical_entity = {find = function(id) return id == 77 and ent or nil end},
    historical_figure = {find = function(id) return figs[id] end},
    unit = {find = function(id) for _, u in ipairs(units) do if u.id == id then return u end end end},
    squad = {find = function(id) return squads[id] end},
    need_type = {[1] = 'Fight'},
    job_skill = SK,
    histfig_entity_link_positionst = setmetatable(LINK, {__index = {is_instance = function(_, l) return l._cls == LINK end}}),
    history_event_add_hf_entity_linkst = {},
    histfig_entity_link_type = {POSITION = 1},
}
env.dfhack = {
    units = {getCitizens = function() return units end,
             isChild = function(u) return u.child == true end, isBaby = function(u) return u.baby == true end,
             getNoblePositions = function(u) local l = noble_positions(u); return #l > 0 and l or nil end,
             getStressCategory = function(u) return u.stress end,
             getReadableName = function(u) return 'dwarf ' .. u.id end},
    TranslateName = function(n) return n end,
}
env.reqscript = function(name)
    assert(name == 'ai-military', name)
    return {seat_leader = function(u, sq) table.insert(seated, {unit = u.id, squad = sq.id}); u.military.squad_id = sq.id; return true end}
end
env.ipairs = zipairs
assert(load(src, 'ai-nobles', 't', env))()
return env, ent, seated
"""

# positions: the expedition leader (held) appoints the commander; the
# commander appoints the captains
POS = [{"code": "EXPEDITION_LEADER", "id": 1},
       {"code": "MILITIA_COMMANDER", "id": 2, "by": [1]},
       {"code": "MILITIA_CAPTAIN", "id": 3, "by": [2]},
       {"code": "MAYOR", "id": 4, "flags": {"ELECTED": True}},
       {"code": "HAMMERER", "id": 5, "by": [99], "civ": 5}]
FOLK = [{"id": 1, "hf": 11},                                                     # the expedition leader
        {"id": 2, "hf": 12, "skills": [("LEADERSHIP", 3), ("MELEE_COMBAT", 2)]},
        {"id": 3, "hf": 13, "skills": [("MILITARY_TACTICS", 9), ("LEADERSHIP", 9)], "squad": 50},  # a soldier
        {"id": 4, "hf": 14, "skills": [("MILITARY_TACTICS", 8), ("LEADERSHIP", 8)]},  # a mother
        {"id": 5, "hf": 15, "baby": True, "mother": 4},
        {"id": 6, "hf": 16, "skills": [("MILITARY_TACTICS", 7)], "stress": 0},        # miserable
        {"id": 7, "hf": 17, "skills": [("MELEE_COMBAT", 1)]}]


def nobles(assignments, units=FOLK, positions=POS, squads=(60, 61)):
    lua = LuaRuntime(unpack_returned_tuples=True)

    def lt(v):
        if isinstance(v, dict):
            return lua.table_from({k: lt(x) for k, x in v.items()})
        if isinstance(v, (list, tuple)):
            return lua.table_from([lt(x) for x in v])
        return v
    return lua.execute(NOBLES_FAKE, NOBLES, lt({"positions": positions, "assignments": assignments,
                                                  "units": units, "squads": list(squads)}))


BASE_A = [{"id": 201, "pos": 1, "hf": 11}, {"id": 202, "pos": 2, "squad": 60},
          {"id": 203, "pos": 3, "hf": 13, "squad": 50}, {"id": 204, "pos": 4, "hf": 11}]


@test("the commander's office refilled by the best fit: never a soldier or a mother of a baby, the miserable last; seated in his squad")
def _():
    env, ent, seated = nobles(BASE_A)
    r = env.appoint("MILITIA_COMMANDER", False)
    assert r.ok and r.name == "dwarf 2", dict(r)                        # 3 soldier, 4 mother, 6 miserable
    assert ent.positions.assignments[1].histfig == 12
    assert r.squad_id == 60 and r.seated and len(seated) == 1 and seated[1].unit == 2, dict(r)
    again = env.appoint("MILITIA_COMMANDER", False)
    assert not again.ok and "already held" in again.error, dict(again)
    # left: the miserable and the expedition leader (two offices): one already in office before the miserable
    env, ent, _ = nobles(BASE_A, units=[u for u in FOLK if u["id"] not in (2, 7)])
    r = env.appoint("MILITIA_COMMANDER", True)
    assert r.ok and r.name == "dwarf 1", dict(r)
    # (review) only the miserable, the soldier and the mother: nobody fits, the post stays empty
    env, ent, _ = nobles(BASE_A, units=[u for u in FOLK if u["id"] in (3, 4, 5, 6)])
    r = env.appoint("MILITIA_COMMANDER", False)
    assert not r.ok and r.rejected and r.nobody_fits and "nobody fits to lead" in r.error, dict(r)
    assert ent.positions.assignments[1].histfig == -1


@test("(review) a squad's leader: never a patient, a post holder (the hospital's staff) or the unhappy; one who wants to fight first")
def _():
    folk = [{"id": 1, "hf": 11},
            {"id": 2, "hf": 12, "skills": [("MILITARY_TACTICS", 9)], "patient": True},
            {"id": 3, "hf": 13, "skills": [("MILITARY_TACTICS", 9)], "staff": True},
            {"id": 4, "hf": 14, "skills": [("MILITARY_TACTICS", 9)], "stress": 2},      # unhappy
            {"id": 5, "hf": 15, "skills": [("MILITARY_TACTICS", 3)]},
            {"id": 6, "hf": 16, "skills": [("MILITARY_TACTICS", 1)], "fight": True}]
    env, _, _ = nobles(BASE_A, units=folk)
    r = env.appoint("MILITIA_COMMANDER", True)
    assert r.ok and r.name == "dwarf 6", dict(r)                        # wants to fight beats a little skill
    env, _, _ = nobles(BASE_A, units=[u for u in folk if u["id"] != 6])
    assert env.appoint("MILITIA_COMMANDER", True).name == "dwarf 5"
    env, _, _ = nobles(BASE_A, units=[u for u in folk if u["id"] in (1, 2, 3, 4)])
    r = env.appoint("MILITIA_COMMANDER", True)
    assert r.ok and r.name == "dwarf 1", dict(r)                        # the expedition leader, before nobody
    env, _, _ = nobles(BASE_A, units=[u for u in folk if u["id"] in (2, 3, 4)] + [{"id": 1, "hf": 11, "patient": True}])
    assert env.appoint("MILITIA_COMMANDER", True).nobody_fits


@test("a captain's slot is refilled only where it leads a squad (a vacant slot with none is DF's spare)")
def _():
    a = BASE_A[:2] + [{"id": 203, "pos": 3}, {"id": 204, "pos": 4, "hf": 11}]
    a[1] = {"id": 202, "pos": 2, "hf": 17, "squad": 60}                 # the commander holds his office
    env, ent, _ = nobles(a)
    r = env.appoint("MILITIA_CAPTAIN", False)
    assert not r.ok and r.rejected and "lost its captain" in r.error, dict(r)
    a.append({"id": 205, "pos": 3, "squad": 61})                        # the dead captain's, leading squad 61
    env, ent, seated = nobles(a)
    r = env.appoint("MILITIA_CAPTAIN", False)
    assert r.ok and r.squad_id == 61 and r.seated and ent.positions.assignments[4].histfig == 12, dict(r)


@test("not the fort's to fill: the captain with no commander, an elected or a monarch's office; the survey says which")
def _():
    a = [{"id": 201, "pos": 1, "hf": 11}, {"id": 202, "pos": 2, "squad": 60}, {"id": 205, "pos": 3, "squad": 61},
         {"id": 204, "pos": 4}, {"id": 206, "pos": 5}]
    env, ent, _ = nobles(a)
    r = env.appoint("MILITIA_CAPTAIN", False)
    assert not r.ok and r.rejected and "not the fort's to fill" in r.error, dict(r)   # no commander to appoint him
    assert ent.positions.assignments[2].histfig == -1
    s = env.survey()
    o = s.offices
    assert o.MILITIA_COMMANDER.appointable is True and o.MILITIA_COMMANDER.vacant_squad == 1, dict(o.MILITIA_COMMANDER)
    assert o.MILITIA_CAPTAIN.appointable is False and o.MAYOR.appointable is False and o.MAYOR.not_why == "elected"
    assert o.HAMMERER.appointable is False and "not in the fort" in o.HAMMERER.not_why, dict(o.HAMMERER)
    assert o.MILITIA_COMMANDER.ai is True and o.MAYOR.ai is False
    assert env.appoint("MAYOR", False).rejected                          # never the AI's
    # the expedition leader gone too: the commander isn't the fort's to fill either
    a[0] = {"id": 201, "pos": 1}
    env, _, _ = nobles(a)
    assert "not the fort's to fill" in env.appoint("MILITIA_COMMANDER", True).error


@test("pick_holder: a mother of a baby never for a military office, but for a civil one; the miserable only last")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute("local src = ...; local e = setmetatable({}, {__index = _G}); "
                      "assert(load(src, 'n', 't', e))(); return e", NOBLES)
    t = lambda rows: lua.table_from([lua.table_from({**r, "skills": lua.table_from(r["skills"])}) for r in rows])
    rows = [{"id": 1, "skills": [9], "mother": True}, {"id": 2, "skills": [1]}]
    assert env.pick_holder(t(rows), True).id == 2
    assert env.pick_holder(t(rows)).id == 1
    rows = [{"id": 1, "skills": [9], "miserable": True}, {"id": 2, "skills": [0]}]
    assert env.pick_holder(t(rows)).id == 2
    assert env.pick_holder(t(rows[:1])).id == 1


# --- the infected (lua/ai-health.lua) -----------------------------------------

HEALTH_FAKE = VEC + r"""
local src, spec = ...
local REST = 7
local units = {}
for _, u in ipairs(spec.units) do
    local wounds = {}
    for _ = 1, (u.infected and 1 or 0) do table.insert(wounds, {flags = {infection = true}}) end
    table.insert(units, {id = u.id, pos = {x = u.x or 0, y = u.y or 0, z = u.z or 0},
                         body = {wounds = wounds, infection_level = u.load or 0},
                         health = {flags = {rq_diagnosis = u.asked or false,
                                            needs_healthcare = u.care ~= false and (u.infected or false)}},
                         job = {current_job = u.busy and {job_type = 1, pos = {x = -1, y = -1, z = -1}} or nil},
                         military = {squad_id = u.squad or -1}, mood = u.mood or -1, adult = not u.child,
                         stress = u.stress or 4, insane = u.insane, noble = u.noble,
                         counters = {soldier_mood = u.tantrum and 1 or 0},
                         burrows = u.burrow and {5} or {},
                         flags1 = {caged = u.caged == true, chained = false},
                         status = {labors = {[1] = u.clean ~= false, [2] = u.diagnose == true}}})
end
local beds = {}
for i, b in ipairs(spec.beds or {}) do
    table.insert(beds, {id = 700 + i, centerx = b[1], centery = b[2], z = b[3], getType = function() return 1 end,
                        users = {unit = b[5] and {b[5]} or {}},
                        getBuildStage = function() return b[4] == false and 0 or 3 end,
                        getMaxBuildStage = function() return 3 end})
end
local zone = {id = 900, x1 = 0, y1 = 0, x2 = 10, y2 = 10, z = 0, contained_buildings = beds}
local posts = {}
for _, p in ipairs(spec.posts or {}) do table.insert(posts, p) end
local loc = {id = 4, getType = function() return 2 end,
             getContents = function() return {building_ids = spec.no_hospital and {} or {900}} end,
             occupations = vec(posts)}
-- the world's job list (a linked list), with the jobs given in spec.jobs
local head = {}
local last = head
for _, p in ipairs(spec.jobs or {}) do
    local link = {item = {pos = {x = p[1], y = p[2], z = p[3]}}}
    last.next = link; last = link
end
local made, removed, saved = {}, {}, {}
local site_data = {}
local env = setmetatable({}, {__index = _G})
env.df = {
    global = {cur_year = 50, cur_year_tick = spec.tick or 1000, occupation_next_id = 500,
              world = {occupations = {all = vec()}, units = {active = units}, jobs = {list = head}}},
    abstract_building_type = {[2] = 'HOSPITAL'},
    building_type = {[1] = 'Bed'},
    building = {find = function(id) return id == 900 and zone or nil end},
    unit = {find = function(id) for _, u in ipairs(units) do if u.id == id then return u end end end},
    unit_labor = {CLEAN = 1, DIAGNOSE = 2},
    job_type = {Rest = REST},
    soldier_mood_type = {[1] = 'Tantrum', [0] = 'None'},
    occupation_type = setmetatable({DOCTOR = 3, [3] = 'DOCTOR', DIAGNOSTICIAN = 4, [4] = 'DIAGNOSTICIAN'}, {}),
    occupation = {new = function() return {} end},
    job = {new = function() local j = {id = 800 + #made, pos = {}, flags = {}, general_refs = vec()}
                            table.insert(made, j); return j end},
    general_ref_unit_workerst = 'worker',
    new = function(t) return {kind = t} end,
}
env.dfhack = {
    world = {getCurrentSite = function() return {id = 1, buildings = {loc}} end},
    units = {getCitizens = function() return units end, isAdult = function(u) return u.adult end,
             isAlive = function(u) return not u.dead end, isSane = function(u) return not u.insane end,
             getStressCategory = function(u) return u.stress end,
             getNoblePositions = function(u) if u.noble then return {{position = {code = 'MANAGER'}}} end end,
             getReadableName = function(u) return 'dwarf ' .. u.id end},
    buildings = {findCivzonesAt = function(pos)
        if pos.x >= 0 and pos.x <= 10 and pos.y >= 0 and pos.y <= 10 and pos.z == 0 then return {zone} end
        return {} end},
    maps = {canWalkBetween = function(a, b) return not (spec.walls and a.z ~= b.z) end},
    job = {linkIntoWorld = function() end,
           removeJob = function(j)
               table.insert(removed, j)
               for _, u in ipairs(units) do if u.job.current_job == j then u.job.current_job = nil end end
               return true end},
    persistent = {getSiteData = function(k, default) return site_data[k] or default end,
                  saveSiteData = function(k, v) site_data[k] = v; table.insert(saved, k) end},
}
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.vlen = function(t) return #t end
env.ipairs = zipairs
env.pairs = function(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then return zipairs(t) end
    return pairs(t)
end
-- a fresh load of the module over the same game and save (a reload)
local function fresh()
    local e = setmetatable({}, {__index = env})
    assert(load(src, 'ai-health', 't', e))()
    return e
end
local mod = fresh()
mod.reload = fresh
mod.site_data = site_data
return mod, units, made, loc, removed
"""


def health(units, beds=((1, 1, 0), (2, 1, 0), (3, 1, 0)), **kw):
    lua = LuaRuntime(unpack_returned_tuples=True)

    def lt(v):
        if isinstance(v, dict):
            return lua.table_from({k: lt(x) for k, x in v.items()})
        if isinstance(v, (list, tuple)):
            return lua.table_from([lt(x) for x in v])
        return v
    return lua.execute(HEALTH_FAKE, HEALTH, lt({"units": units, "beds": list(beds), **kw}))


SICK = [{"id": 1, "infected": True, "load": 120, "x": 50, "diagnose": True},
        {"id": 2, "infected": True, "load": 400, "x": 50},                    # bleeding
        {"id": 3, "infected": True, "load": 900, "x": 50, "busy": True},      # at work: not taken off it
        {"id": 4, "infected": True, "load": 200, "x": 50, "asked": True},     # DF asks a treatment already
        {"id": 5, "infected": True, "load": 250, "x": 5},                     # in the hospital already
        {"id": 6, "infected": True, "load": 300, "x": 50, "squad": 9},        # a soldier
        {"id": 7, "infected": True, "load": 350, "x": 50, "child": True},
        {"id": 8, "x": 50, "clean": False},                                   # healthy
        {"id": 9, "infected": True, "load": 100, "x": 50, "mood": 2}]
BEDS4 = ((1, 1, 0), (2, 1, 0), (3, 1, 0), (4, 1, 0), (6, 1, 0), (7, 1, 0))


@test("infection survey: counts the infected, untreated, bleeding, idle; the worst; the free beds; cleaners and diagnosers")
def _():
    env, units, made, _, _ = health(SICK, beds=((1, 1, 0), (2, 1, 0), (5, 0, 0), (9, 9, 0, False)))
    s = env.survey()
    assert (s.infected, s.untreated, s.bleeding, s.in_hospital) == (8, 7, 4, 1), \
        (s.infected, s.untreated, s.bleeding, s.in_hospital)
    assert s.idle_untreated == 2, s.idle_untreated                     # 1 and 2: idle, grown, no soldier, no mood
    assert s.worst[1].id == 3 and s.worst[1].load == 900 and len(list(s.worst.values())) == 5
    assert s.beds == 3 and s.free_beds == 2, (s.beds, s.free_beds)      # dwarf 5 lies in one; the unfinished isn't one
    assert s.cleaners == 6 and s.diagnosers == 1, (s.cleaners, s.diagnosers)   # soldiers and children not counted
    assert s.max_load == 900 and s.hospital_zones == 1
    assert (s.sleeping, s.failed, s.helped, s.rest_days) == (0, 0, 0, 3)


@test("(review) eligibility: needs_healthcare, and never the unhappy, raging, mad, in a burrow, hospital staff, caged, office holders")
def _():
    base = {"infected": True, "load": 500, "x": 50}
    bad = [dict(base, id=11, care=False), dict(base, id=12, stress=2), dict(base, id=13, tantrum=True),
           dict(base, id=14, insane=True), dict(base, id=15, burrow=True), dict(base, id=16),
           dict(base, id=17, caged=True), dict(base, id=18, noble=True)]
    env, _, _, _, _ = health(bad + [dict(base, id=19, load=10)], beds=BEDS4, posts=[{"type": 3, "unit_id": 16}])
    assert env.survey().idle_untreated == 1
    r = env.rest_infected(3, False, None, 3, 2)
    assert r.ok and [x.unit_id for x in r.sent.values()] == [19], [x.unit_id for x in r.sent.values()]
    lua = LuaRuntime(unpack_returned_tuples=True)
    pure = lua.execute("local src = ...; local e = setmetatable({}, {__index = _G}); "
                       "assert(load(src, 'h', 't', e))(); return e", HEALTH)
    ok = {"infected": True, "care": True, "idle": True}
    assert pure.eligible(lua.table_from(ok))
    for k in ("asked", "in_hospital", "soldier", "child", "mood", "sent", "cooldown", "unhappy", "tantrum", "insane",
              "burrow", "staff", "restrained", "noble"):
        assert not pure.eligible(lua.table_from(dict(ok, **{k: True}))), k
    for k in ("infected", "care", "idle"):
        assert not pure.eligible(lua.table_from(dict(ok, **{k: False}))), k
    assert pure.room(3, 3, 2, 0, 10) == 3 and pure.room(3, 3, 2, 2, 10) == 1 and pure.room(3, 3, 2, 0, 3) == 1
    assert pure.room(3, 3, 2, 0, 2) == 0 and pure.room(3, 3, 2, 3, 10) == 0


@test("rest_infected: the bleeding first, a free bed each (not one lain in), a special Rest job as dwarfvet makes; kept in the save")
def _():
    units_ = SICK + [{"id": 10, "x": 1, "y": 1}]                         # someone lies in bed (1,1)
    env, units, made, _, _ = health(units_, beds=BEDS4)
    d = env.rest_infected(3, True, None, 3, 2)
    assert d.ok and d.dry_run and [x.unit_id for x in d.sent.values()] == [2, 1] and len(made) == 0, dict(d)
    r = env.rest_infected(3, False, None, 3, 2)
    assert r.ok and [x.unit_id for x in r.sent.values()] == [2, 1], dict(r)
    assert len(made) == 2 and made[1].job_type == 7 and made[1].flags.special
    assert (made[1].pos.x, made[1].pos.y) != (made[2].pos.x, made[2].pos.y)
    assert (made[1].pos.x, made[1].pos.y) != (1, 1) and (made[2].pos.x, made[2].pos.y) != (1, 1)
    assert made[1].general_refs[0].unit_id == 2 and units[2].job.current_job.job_type == 7
    st = env.site_data["ai-overseer/infected-rest"]
    assert st.sent["2"].tick == 50 * 403200 + 1000 and st.sent["1"] is not None
    # a reload of the script forgets nobody (the save keeps them)
    again = env.reload()
    s = again.survey()
    assert s.sleeping == 2 and s.failed == 0, (s.sleeping, s.failed)
    r = again.rest_infected(3, False, None, 3, 2)
    assert not r.ok and r.rejected and "no idle infected" in r.error, dict(r)


@test("(review) a bed held by any job aimed at it or listed as used is not free")
def _():
    env, _, _, _, _ = health(SICK, beds=((1, 1, 0), (2, 1, 0, True, 99), (3, 1, 0)), jobs=[(1, 1, 0)])
    assert env.survey().free_beds == 1


@test("(review) at most `cap` undiagnosed sleepers at once, and `keep_free` beds left for DF's patients")
def _():
    many = [{"id": i, "infected": True, "load": 100 + i, "x": 50} for i in range(1, 9)]
    env, _, made, _, _ = health(many, beds=tuple((i, 1, 0) for i in range(1, 11)))
    r = env.rest_infected(10, False, None, 3, 2)
    assert r.ok and len(list(r.sent.values())) == 3, dict(r)
    r = env.rest_infected(10, False, None, 3, 2)
    assert not r.ok and "no room" in r.error, dict(r)                  # the cap reached
    env, _, made, _, _ = health(many, beds=((1, 1, 0), (2, 1, 0), (3, 1, 0)))
    r = env.rest_infected(10, False, None, 3, 2)
    assert r.ok and len(list(r.sent.values())) == 1, dict(r)           # 3 free, 2 kept
    r = env.rest_infected(10, False, None, 3, 2)
    assert not r.ok and "no room" in r.error, dict(r)


@test("(review 2) a Rest job that isn't the AI's own (DF's, for a new wound) is never removed")
def _():
    env, units, made, _, removed = health(SICK, beds=BEDS4)
    env.rest_infected(3, False, None, 3, 2)
    j = units[2].job.current_job
    j.id = 4242                                                         # DF's own rest replaced the AI's
    env.df["global"].cur_year_tick = 1000 + 3 * 1200
    s = env.survey()
    # dwarf 1's own (the AI's) rest is ended after 3 days; dwarf 2's, now DF's, is left alone
    assert len(removed) == 1 and removed[1].id != 4242 and units[2].job.current_job.id == 4242, len(removed)
    assert s.sleeping == 0, s.sleeping                                  # counted as ended, not the AI's


@test("(review) a sleeper with no treatment asked after 3 days is got up (the Rest job removed) and not sent again for 28 days")
def _():
    env, units, made, _, removed = health(SICK, beds=BEDS4)
    env.rest_infected(3, False, None, 3, 2)
    env.df["global"].cur_year_tick = 1000 + 2 * 1200
    s = env.survey()
    assert s.sleeping == 2 and len(removed) == 0
    units[1].health.flags.rq_diagnosis = True                           # dwarf 1 diagnosed: DF's patient now
    env.df["global"].cur_year_tick = 1000 + 3 * 1200
    s = env.survey()
    assert len(removed) == 1 and units[2].job.current_job is None, len(removed)      # dwarf 2 got up
    assert (s.sleeping, s.failed, s.helped, s.got_up_now) == (0, 1, 1, 1), (s.sleeping, s.failed, s.helped)
    units[1].health.flags.rq_diagnosis = False                          # treated, up again, still infected
    units[1].job.current_job = None
    r = env.rest_infected(3, False, None, 3, 2)
    assert r.ok and [x.unit_id for x in r.sent.values()] == [1], [x.unit_id for x in r.sent.values()]  # 2 waits
    env.df["global"].cur_year_tick = 1000 + 3 * 1200 + 28 * 1200
    s = env.survey()
    cd = env.site_data["ai-overseer/infected-rest"].cooldown
    assert cd["2"] is None and cd["1"] is not None, (dict(cd))        # 2 forgotten after 28 days; 1 just got up
    assert s.failed == 1 and s.helped == 0, (s.failed, s.helped)
    # DF ending the rest itself counts the same
    env, units, _, _, removed = health(SICK, beds=BEDS4)
    env.rest_infected(1, False, None, 3, 2)
    units[2].job.current_job = None
    s = env.survey()
    assert s.failed == 1 and s.sleeping == 0 and len(removed) == 0


@test("rest_infected: none without a hospital, a free bed or one they can walk to")
def _():
    env, _, _, _, _ = health(SICK, beds=())
    assert "no room" in env.rest_infected(3, False, None, 3, 2).error
    env, _, _, _, _ = health(SICK, no_hospital=True)
    assert "no hospital zone" in env.rest_infected(3, False, None, 3, 2).error
    env, _, made, _, _ = health(SICK, beds=((1, 1, 1), (2, 1, 1), (3, 1, 1)), walls=True)
    r = env.rest_infected(3, False, None, 3, 0)
    assert not r.ok and "walk to" in r.error and len(made) == 0, dict(r)


@test("add_doctor_post: a second doctor's post, never a third")
def _():
    env, _, _, loc, _ = health(SICK, posts=[{"type": 3}, {"type": 4}])
    d = env.add_doctor_post(4, True)
    assert d.ok and d.dry_run and d.posts == 2 and env.vlen(loc.occupations) == 2, dict(d)
    r = env.add_doctor_post(4, False)
    assert r.ok and r.posts == 2 and env.vlen(loc.occupations) == 3 and loc.occupations[2].type == 3
    assert loc.occupations[2].location_id == 4 and loc.occupations[2].unit_id == -1
    r = env.add_doctor_post(4, False)
    assert not r.ok and r.rejected and "two doctors" in r.error, dict(r)
    assert env.add_doctor_post(99, False).rejected


@test("pick_patients (pure): bleeding then heavier first")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute("local src = ...; local e = setmetatable({}, {__index = _G}); "
                      "assert(load(src, 'h', 't', e))(); return e", HEALTH)
    t = lambda rows: lua.table_from([lua.table_from(r) for r in rows])
    base = {"infected": True, "idle": True, "care": True}
    rows = [dict(base, id=1, load=100), dict(base, id=2, load=310), dict(base, id=3, load=290),
            dict(base, id=4, load=900, asked=True), dict(base, id=5, load=900, soldier=True),
            dict(base, id=6, load=500, in_hospital=True), {"id": 7, "load": 900, "infected": True},
            dict(base, id=8, load=999, sent=True), dict(base, id=9, load=320)]
    got = [c.id for c in env.pick_patients(t(rows), 10).values()]
    assert got == [9, 2, 3, 1], got
    assert [c.id for c in env.pick_patients(t(rows), 2).values()] == [9, 2]



if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
