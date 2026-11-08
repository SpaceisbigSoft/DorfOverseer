"""Tests for lua/ai-nobles.lua (appointing the fort's offices), in a real
Lua engine with a small fake of the game's records (pip install lupa).

    python tests/test_nobles.py
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

SRC = module_src("ai-nobles.lua")

FAKE = r"""
local src, spec = ...
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
local LINK = {}
local SK = {ORGANIZATION = 1, RECORD_KEEPING = 2, APPRAISAL = 3, NEGOTIATION = 4, PERSUASION = 5,
            JUDGING_INTENT = 6, DIAGNOSE = 7}
local positions = vec()
local assignments = vec()
for i, code in ipairs(spec.offices) do
    positions:insert('#', {id = 100 + i, code = code, appointed_by = vec({1})})
    assignments:insert('#', {id = 200 + i, position_id = 100 + i, histfig = spec.held and spec.held[code] or -1})
end
local ent = {id = 77, positions = {own = positions, assignments = assignments}}
local figs, units = {}, {}
for _, u in ipairs(spec.units) do
    figs[u.hf] = {id = u.hf, entity_links = vec(), name = 'fig' .. u.hf}
    local skills = {}
    for _, s in ipairs(u.skills or {}) do table.insert(skills, {id = SK[s[1]], rating = s[2]}) end
    table.insert(units, {id = u.id, hist_figure_id = u.hf, child = u.child, military = {squad_id = u.squad or -1},
                         status = {current_soul = {skills = skills}}})
end
local function noble_positions(u)
    local out = {}
    local hf = figs[u.hist_figure_id]
    if spec.blind then return out end
    for i = 0, #hf.entity_links - 1 do
        local l = hf.entity_links[i]
        if l._cls == LINK then
            for j = 0, #assignments - 1 do
                local a = assignments[j]
                if a.id == l.assignment_id then
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
local env = setmetatable({}, {__index = _G})
env.df = {
    global = {plotinfo = {group_id = 77}, cur_year = 50, cur_year_tick = 10, hist_event_next_id = 1,
              world = {history = {events = vec()}}},
    historical_entity = {find = function(id) return id == 77 and ent or nil end},
    historical_figure = {find = function(id) return figs[id] end},
    unit = {find = function(id) for _, u in ipairs(units) do if u.id == id then return u end end end},
    job_skill = SK,
    histfig_entity_link_positionst = setmetatable(LINK, {__index = {is_instance = function(_, l) return l._cls == LINK end}}),
    history_event_add_hf_entity_linkst = {},
    histfig_entity_link_type = {POSITION = 1},
}
env.dfhack = {
    units = {getCitizens = function() return units end,
             isChild = function(u) return u.child == true end, isBaby = function() return false end,
             getNoblePositions = function(u) local l = noble_positions(u); return #l > 0 and l or nil end,
             getReadableName = function(u) return 'dwarf ' .. u.id end},
    TranslateName = function(n) return n end,
}
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
assert(load(src, 'ai-nobles', 't', env))()
return env, ent, figs
"""


def game(units, offices=("MANAGER", "BOOKKEEPER", "BROKER", "SHERIFF"), **kw):
    lua = LuaRuntime(unpack_returned_tuples=True)

    def lt(v):
        if isinstance(v, dict):
            return lua.table_from({k: lt(x) for k, x in v.items()})
        if isinstance(v, (list, tuple)):
            return lua.table_from([lt(x) for x in v])
        return v
    env, ent, figs = lua.execute(FAKE, SRC, lt({"units": units, "offices": list(offices), **kw}))
    return env, ent, figs


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


FOLK = [{"id": 1, "hf": 11, "skills": [("ORGANIZATION", 1)]},
        {"id": 2, "hf": 12, "skills": [("ORGANIZATION", 4), ("RECORD_KEEPING", 1)]},
        {"id": 3, "hf": 13, "skills": [("ORGANIZATION", 9)], "child": True},
        {"id": 4, "hf": 14, "skills": [("RECORD_KEEPING", 5)], "squad": 3}]


@test("the most skilled grown dwarf is picked; a child never; one office each first")
def _():
    env, ent, figs = game(FOLK)
    r = env.appoint("MANAGER", True)
    assert r.ok and r.name == "dwarf 2" and r.dry_run, dict(r)
    assert ent.positions.assignments[0].histfig == -1                    # a dry run writes nothing


@test("appointing writes the holder and the figure's link, and DFHack sees it; not twice")
def _():
    env, ent, figs = game(FOLK)
    r = env.appoint("MANAGER", False)
    assert r.ok and r.name == "dwarf 2", dict(r)
    a = ent.positions.assignments[0]
    assert a.histfig == 12 and figs[12].entity_links[0].assignment_id == a.id
    again = env.appoint("MANAGER", False)
    assert not again.ok and "already held" in again.error
    b = env.appoint("BOOKKEEPER", False)                                  # dwarf 2 has an office now
    assert b.ok and b.name != "dwarf 2", dict(b)


@test("if DFHack doesn't see the appointment, both writes are undone")
def _():
    env, ent, figs = game(FOLK, blind=True)
    r = env.appoint("MANAGER", False)
    assert not r.ok and "undone" in r.error, dict(r)
    assert ent.positions.assignments[0].histfig == -1 and figs[12].entity_links[0] is None


@test("only the AI's offices (sheriff since 0.44); none the fort doesn't have")
def _():
    env, _, _ = game(FOLK)
    assert env.appoint("MILITIA_COMMANDER", False).rejected
    assert env.appoint("SHERIFF", True).ok                                  # justice: the AI's since 0.44
    assert "no CHIEF_MEDICAL_DWARF office" in env.appoint("CHIEF_MEDICAL_DWARF", False).error




@test("a dwarf holding an office gets a second only when nobody else will do (the 0.44 sheriff was the doctor)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute("local src = ...; local e = setmetatable({}, {__index = _G}); "
                      "assert(load(src, 'n', 't', e))(); return e", SRC)
    t = lambda rows: lua.table_from([lua.table_from({**r, "skills": lua.table_from(r["skills"])}) for r in rows])
    best = env.pick_holder(t([{"id": 1, "skills": [15, 15], "offices": 1}, {"id": 2, "skills": [0, 1], "offices": 0}]))
    assert best.id == 2, best.id
    best = env.pick_holder(t([{"id": 1, "skills": [15, 15], "offices": 1},
                              {"id": 2, "skills": [3], "offices": 0, "child": True}]))
    assert best.id == 1, best.id


ROOMS_FAKE = r"""
local src = ...
local CIV = 9
local ZT = {[0] = 'Bedroom', [1] = 'Office', [2] = 'Tomb', Bedroom = 0, Office = 1, Tomb = 2}
local function z(id, t, owner) return {id = id, type = t, assigned_unit_id = owner or -1,
                                       getType = function() return CIV end} end
local zones = {z(1, 0), z(2, 1), z(3, 1, 7)}
local manager = {id = 5, owned_buildings = {}}
local commoner = {id = 6, owned_buildings = {}}
local pos = {code = 'MANAGER', required_office = 1, required_bedroom = 1, required_dining = 0, required_tomb = 0}
local env = setmetatable({}, {__index = _G})
env.df = {global = {world = {buildings = {all = zones}}}, building_type = {Civzone = CIV}, civzone_type = ZT,
          unit = {find = function(id) return id == 5 and manager or (id == 6 and commoner or nil) end}}
env.dfhack = {
    units = {getCitizens = function() return {manager, commoner} end,
             getNoblePositions = function(u) if u == manager then return {{position = pos}} end end,
             getReadableName = function(u) return 'dwarf ' .. u.id end},
    buildings = {setOwner = function(zone, u)
        zone.assigned_unit_id = u.id; table.insert(u.owned_buildings, zone); return true end},
}
assert(load(src, 'ai-nobles', 't', env))()
return env, manager
"""


def rooms_game():
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua.execute(ROOMS_FAKE, SRC)


@test("noble rooms: a noble's missing rooms and the free ones are surveyed")
def _():
    env, _ = rooms_game()
    r = env.rooms_survey()
    nobles = list(r.nobles.values())
    assert len(nobles) == 1 and nobles[0].unit_id == 5 and nobles[0].office == "MANAGER", nobles
    assert list(nobles[0].needs.values()) == ["bedroom", "office"], list(nobles[0].needs.values())
    assert r.free.office == 1 and r.free.bedroom == 1 and r.free.tomb == 0, dict(r.free)


@test("noble rooms: a free room is given (not one someone owns); a second ask is refused")
def _():
    env, manager = rooms_game()
    d = env.give_room(5, "office", True)
    assert d.ok and d.dry_run and d.zone == 2 and len(manager.owned_buildings) == 0, dict(d)
    r = env.give_room(5, "office", False)
    assert r.ok and r.zone == 2 and len(manager.owned_buildings) == 1, dict(r)
    r = env.give_room(5, "office", False)
    assert not r.ok and "already" in r.error, dict(r)
    r = env.give_room(5, "tomb", False)
    assert not r.ok and "no free tomb" in r.error, dict(r)
    s = env.rooms_survey()
    assert list(list(s.nobles.values())[0].needs.values()) == ["bedroom"], "office no longer needed"

if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
