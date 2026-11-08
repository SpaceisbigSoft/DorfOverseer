"""Tests for lua/ai-missions.lua (the fort's world-map missions, read only)
on a fake world (pip install lupa).

    python tests/test_missions.py

The fake's objects raise on a missing field, as DFHack's do, so a field the
module guesses wrong shows up in the report's `unknown` list.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402

try:
    from lupa import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

SRC = (ROOT / "lua" / "ai-missions.lua").read_text(encoding="utf-8")
FAKE = r"""
local src, setup = ...
local env = setmetatable({}, {__index = _G})
-- a DF object: reading a field it doesn't have is an error
local function S(t)
  return setmetatable(t, {__index = function(_, k) error('no field ' .. tostring(k), 2) end})
end
local function enum(names)
  local e = {_first_item = 0, _last_item = #names - 1}
  for i, n in ipairs(names) do e[i - 1] = n; e[n] = i - 1 end
  return e
end
local G = enum({'SITE_INVASION', 'RECOVER_ARTIFACT', 'RESCUE_HF', 'MAKE_REQUEST', 'DIPLOMACY', 'MOVE_TO_SITE'})
local ENTS, SQUADS, HFS, UNITS, SITES, NEMS = {}, {}, {}, {}, {}, {}
env.SCREEN = nil
env.df = {
  army_controller_goal_type = G,
  invasion_intent_type = enum({'RAID', 'PILLAGE', 'DEMAND_TRIBUTE', 'EXPLORE'}),
  world_site_type = enum({'PlayerFortress', 'DarkFortress', 'Cave', 'MountainHalls', 'ForestRetreat', 'Town'}),
  diplomacy_state_type = enum({'Peace', 'War'}),
  world_view_mode_type = enum({'NORMAL', 'CIVILIZATIONS', 'MISSIONS_LIST', 'MISSIONS_DETAILS', 'NEW_MISSION'}),
  world_new_mission_type = enum({'OKAY', 'INACCESSIBLE', 'OWN_CIV', 'NOT_IN_CONTACT', 'HOSTILE_ENTITY'}),
  viewscreen_worldst = {is_instance = function(_, s) return rawget(s, '_world') == true end},
  historical_entity = {find = function(id) return ENTS[id] end},
  squad = {find = function(id) return SQUADS[id] end},
  historical_figure = {find = function(id) return HFS[id] end},
  unit = {find = function(id) return UNITS[id] end},
  world_site = {find = function(id) return SITES[id] end},
  nemesis_record = {find = function(id) return NEMS[id] end},
  global = S{
    plotinfo = S{civ_id = 100, group_id = 200, site_id = 10},
    gview = S{view = S{child = false}},
    world = S{
      army_controllers = S{all = {}},
      armies = S{all = {}},
      status = S{mission_reports = {}, spoils_reports = {},
                 flags = S{mission = false, spoils = false, tribute = false}},
      world_data = S{sites = {}},
    },
  },
}
env.dfhack = {
  gui = {getViewscreenByType = function(t, n) return env.SCREEN end},
  translation = {translateName = function(n, english) return n.text end},
}
local W = env.df.global.world
-- builders the tests use
local B = {S = S, G = G, W = W, ENTS = ENTS, SQUADS = SQUADS, UNITS = UNITS, SITES = SITES, env = env}
function B.entity(id, fields)
  local e = {id = id, squads = {}, relations = S{diplomacy = S{state = {}}}}
  for k, v in pairs(fields or {}) do e[k] = v end
  ENTS[id] = S(e)
  return ENTS[id]
end
function B.dwarf(hfid, unit_id, fields)
  fields = fields or {}
  HFS[hfid] = S{id = hfid, unit_id = unit_id, died_year = fields.died or -1,
                info = S{whereabouts = S{army_id = fields.army or -1}}}
  if unit_id >= 0 and not fields.no_unit then
    UNITS[unit_id] = S{id = unit_id, flags1 = S{inactive = fields.inactive == true},
                       flags2 = S{killed = fields.killed == true}}
  end
end
function B.squad(id, name, hfs, ctl, fields)
  local pos = {}
  for _, h in ipairs(hfs) do table.insert(pos, S{occupant = h}) end
  local s = {id = id, alias = name, name = {text = 'The ' .. name}, positions = pos,
             assigned_army_controller_id = ctl or -1}
  for k, v in pairs(fields or {}) do s[k] = v end
  if fields and fields.no_ctl then s.assigned_army_controller_id = nil; s.no_ctl = nil end
  SQUADS[id] = S(s)
  table.insert(ENTS[200].squads, id)
end
function B.controller(t)
  table.insert(W.army_controllers.all, S(t))
end
function B.site(id, name, civ, x, y, typ)
  SITES[id] = S{id = id, name = {text = name}, civ_id = civ, cur_owner_id = civ, type = typ or 3,
                pos = S{x = x, y = y}}
  table.insert(W.world_data.sites, SITES[id])
end
function B.relation(other, rel)
  table.insert(ENTS[100].relations.diplomacy.state, S{group_id = other, relation = rel})
end
function B.army(ctl, nemeses)
  local m = {}
  for _, n in ipairs(nemeses) do
    NEMS[n.id] = S{id = n.id, unit_id = n.unit, figure_id = -1}
    table.insert(m, S{nemesis_id = n.id})
  end
  table.insert(W.armies.all, S{controller_id = ctl, members = m})
end
B.entity(100)
B.entity(200)
B.site(10, 'Home', 100, 50, 50, 0)
assert(load(setup, 'setup', 't', setmetatable({B = B}, {__index = _G})))()
assert(load(src, 'ai-missions', 't', env))()
return env
"""

LUA = LuaRuntime(unpack_returned_tuples=True)


def world(setup: str):
    return LUA.execute(FAKE, SRC, setup)


def lst(t):
    """A Lua list as a Python list (None for nil)."""
    if t is None:
        return None
    return [t[i] for i in range(1, len(t) + 1)]


RAID = r"""
local S = B.S
B.site(20, 'Goblin Pits', 300, 54, 51, 1)
B.dwarf(1001, 1, {army = 7, no_unit = true})   -- on the march
B.dwarf(1002, 2, {inactive = true})            -- off the map
B.dwarf(1003, 3)                               -- home again
B.dwarf(1004, 4)
B.squad(1, 'Axes', {1001, 1002}, 5)
B.squad(2, 'Shields', {1003, 1004, -1}, 5)
B.controller{id = 5, entity_id = 200, site_id = 20, goal = B.G.SITE_INVASION,
             assigned_squads = {1, 2},
             data = S{goal_site_invasion = S{invasion_intent = 0, invasion_stage = 2,
                                             flag = S{RETURNING_HOME = true}}}}
"""


@test("a raid with two squads: goal, intent, stage, target site, returning, who is away")
def _():
    env = world(RAID)
    r = env.report()
    assert len(r.controllers) == 1, len(r.controllers)
    c = r.controllers[1]
    assert (c.id, c.goal, c.intent, c.stage, c.site_id, c.site) == (5, "SITE_INVASION", "RAID", 2, 20, "Goblin Pits"), \
        (c.id, c.goal, c.intent, c.stage, c.site_id, c.site)
    assert c.returning is True and lst(c.squads) == [1, 2] and c.away == 2, (c.returning, lst(c.squads), c.away)
    sq = {s.id: s for s in lst(r.squads)}
    assert sq[1].name == "Axes" and sq[1].members == 2 and sq[1].away == 2 and sq[1].controller == 5
    assert sq[2].members == 2 and sq[2].away == 0 and sq[2].controller == 5
    assert len(r.unknown) == 0, lst(r.unknown)
    assert r.screen is None


@test("a rescue: goal RESCUE_HF, returning from its own flag, no intent; squads found from the squad side")
def _():
    env = world(r"""
local S = B.S
B.dwarf(1001, 1, {army = 9})
B.squad(1, 'Rescuers', {1001}, 8)
B.controller{id = 8, entity_id = 100, site_id = -1, goal = B.G.RESCUE_HF, assigned_squads = {},
             data = S{goal_rescue_hf = S{flag = S{RETURNING = true}}}}
""")
    c = env.report().controllers[1]
    assert (c.goal, c.intent, c.site_id, c.returning) == ("RESCUE_HF", None, None, True), \
        (c.goal, c.intent, c.site_id, c.returning)
    assert lst(c.squads) == [1] and c.away == 1, (lst(c.squads), c.away)


@test("missing fields degrade to nil/'unknown' and are named once, without an error")
def _():
    env = world(r"""
local S, W = B.S, B.W
B.dwarf(1001, 1)
B.squad(1, 'A', {1001}, nil, {no_ctl = true})
B.squad(2, 'B', {1001}, nil, {no_ctl = true})
B.controller{id = 5, entity_id = 200}                     -- no goal, no data, no squads
rawset(W.status, 'spoils_reports', nil)                  -- gone from this version
B.ENTS[100] = S{id = 100}                                -- no relations
""")
    r = env.report()
    c = r.controllers[1]
    assert c.goal == "unknown" and c.returning is None and len(c.squads) == 0, (c.goal, c.returning)
    unk = lst(r.unknown)
    for f in ("army_controller.goal", "army_controller.assigned_squads", "squad.assigned_army_controller_id",
              "world.status.spoils_reports", "entity.relations.diplomacy.state"):
        assert f in unk, (f, unk)
    assert unk.count("squad.assigned_army_controller_id") == 1, unk
    assert r.spoils.n == 0 and r.squads[1].controller is None
    # nothing readable at all: still a report
    env2 = world("rawset(B.env.df.global, 'world', B.S{}); rawset(B.env.df.global, 'plotinfo', B.S{})")
    r2 = env2.report()
    assert len(r2.controllers) == 0 and len(r2.squads) == 0 and "plotinfo.civ_id" in lst(r2.unknown)
    assert len(env2.away_units()) == 0


@test("the World screen: allowed missions read when it is open, screen nil when it isn't")
def _():
    env = world(RAID)
    assert env.report().screen is None
    env = world(RAID + r"""
local nm = B.S{[0] = 0, [1] = 1, [2] = 3, [3] = 2, [4] = 0, [5] = 4}
B.env.SCREEN = setmetatable({_world = true, view_mode = 4, focus_site = 20, new_mission = nm},
                            getmetatable(B.S{}))
""")
    s = env.report().screen
    assert s.view_mode == "NEW_MISSION" and s.focus_site == 20, (s.view_mode, s.focus_site)
    a = dict(s.allowed.items())
    assert a == {"SITE_INVASION": "OKAY", "RECOVER_ARTIFACT": "INACCESSIBLE", "RESCUE_HF": "NOT_IN_CONTACT",
                 "MAKE_REQUEST": "OWN_CIV", "DIPLOMACY": "OKAY", "MOVE_TO_SITE": "HOSTILE_ENTITY"}, a
    # found by walking the screen stack when getViewscreenByType finds nothing
    env = world(r"""
local scr = B.S{_world = true, view_mode = 2, focus_site = -1, new_mission = B.S{[0] = 0}, child = false}
rawset(B.env.df.global.gview.view, 'child', B.S{_world = false, child = scr})
""")
    s = env.report().screen
    assert s.view_mode == "MISSIONS_LIST" and s.focus_site is None and dict(s.allowed.items()) == {"SITE_INVASION": "OKAY"}


@test("probe_screen (0.104.97): the World screen's fields one level deep, its mode and allowed goals; none when shut")
def _():
    env = world(RAID)
    r = env.probe_screen()
    assert r.screen is False and r.fields is None, dict(r)
    env = world(RAID + r"""
local nm = B.S{[0] = 0, [1] = 1}
B.env.SCREEN = setmetatable({_world = true, view_mode = 4, focus_site = 20, new_mission = nm, name = 'w'},
                            getmetatable(B.S{}))
""")
    r = env.probe_screen()
    assert r.screen is True and r.view_mode == "NEW_MISSION", dict(r)
    f = dict(r.fields.items())
    assert f.get("focus_site") == 20 and f.get("view_mode") == 4 and f.get("name") == "w", f
    assert dict(r.allowed.items())["SITE_INVASION"] == "OKAY"


@test("mission and spoils reports counted: unviewed, the last one, tribute, the new-report lights")
def _():
    env = world(r"""
local S, W = B.S, B.W
for i, v in ipairs({true, false, false}) do
  table.insert(W.status.mission_reports, S{title = 'Raid ' .. i, year = 100 + i, flags = S{viewed = v}})
end
table.insert(W.status.spoils_reports, S{flags = S{spoils = true, tribute = false}, item_counts = {1}})
table.insert(W.status.spoils_reports, S{flags = S{spoils = false, tribute = true}, item_counts = {3, 4}})
rawset(W.status.flags, 'mission', true)
""")
    r = env.report()
    assert (r.reports.n, r.reports.unviewed) == (3, 2), (r.reports.n, r.reports.unviewed)
    assert (r.reports.last.title, r.reports.last.year) == ("Raid 3", 103)
    assert lst(r.reports.new) == ["mission"]
    assert r.spoils.n == 2 and r.spoils.last.kind == "tribute" and r.spoils.last["items"] == 7  # (.items is lupa's method)
    assert len(r.unknown) == 0, lst(r.unknown)


@test("only the fort civ's controllers: the civ's and the fort's counted, another civ's not")
def _():
    env = world(r"""
B.controller{id = 1, entity_id = 100, goal = B.G.DIPLOMACY, site_id = -1, assigned_squads = {}, data = B.S{}}
B.controller{id = 2, entity_id = 200, goal = B.G.MAKE_REQUEST, site_id = -1, assigned_squads = {},
             data = B.S{goal_make_request = B.S{flag = B.S{RETURNING_HOME = false}}}}
B.controller{id = 3, entity_id = 999, goal = B.G.SITE_INVASION, site_id = 10, assigned_squads = {}, data = B.S{}}
""")
    r = env.report()
    ids = sorted(c.id for c in lst(r.controllers))
    assert ids == [1, 2], ids
    req = [c for c in lst(r.controllers) if c.id == 2][0]
    assert req.goal == "MAKE_REQUEST" and req.returning is False


@test("sites: nearest foreign occupied sites by world-tile distance, war/peace counted, own and empty skipped")
def _():
    env = world(r"""
B.site(11, 'Our Hamlet', 100, 51, 50)        -- the fort's own civ
B.site(12, 'Ruin', -1, 50, 51)               -- nobody's
B.site(13, 'Elf Wood', 400, 53, 50, 4)
B.site(14, 'Gob Tower', 300, 49, 47, 1)
for i = 1, 10 do B.site(100 + i, 'Far ' .. i, 500, 50 + 10 + i, 50) end
B.relation(300, 1)                            -- War
B.relation(400, 0)                            -- Peace
""")
    s = env.report().sites
    near = lst(s.nearest)
    assert len(near) == 8, len(near)
    assert [(n.id, n.dist) for n in near[:3]] == [(13, 3), (14, 3), (101, 11)], [(n.id, n.dist) for n in near[:3]]
    gob = near[1]
    assert (gob.name, gob.type, gob.owner_civ, gob.relation) == ("Gob Tower", "DarkFortress", 300, "War")
    assert near[0].relation == "Peace" and near[2].relation == "unknown"
    assert (s.n_hostile, s.n_neutral, s.n_unknown) == (1, 1, 10), (s.n_hostile, s.n_neutral, s.n_unknown)


@test("ruins (0.104.99): sites flagged RUINED (or owned by nobody, nobody living there), nearest first, with the way to them")
def _():
    env = world(r"""
B.site(12, 'Old Hall', 300, 50, 53)
B.env.df.global.world.world_data.sites[#B.env.df.global.world.world_data.sites].flag = B.S{RUINED = true, HIDDEN = false}
B.site(15, 'Empty Lair', -1, 46, 50)
local all = B.env.df.global.world.world_data.sites
all[#all].resident_count = 0
B.site(16, 'Secret', -1, 50, 49)
all[#all].flag = B.S{RUINED = true, HIDDEN = true}
B.site(17, 'Town', 400, 51, 50)
""")
    s = env.report().sites
    r = lst(s.ruins)
    assert [(x.id, x.dist, x.way) for x in r] == [(12, 3, "south"), (15, 4, "west")], [(x.id, x.dist, x.way) for x in r]
    assert s.n_ruins == 2 and r[0].name == "Old Hall"


@test("away_units: squad members away (army, off the map, no unit) and the armies' members; not the dead")
def _():
    env = world(r"""
B.dwarf(1001, 1, {army = 7})                  -- on an army's roll
B.dwarf(1002, 2, {inactive = true})           -- off the map
B.dwarf(1003, 3)                              -- at home
B.dwarf(1004, 4, {no_unit = true})            -- no unit on the map
B.dwarf(1005, 5, {died = 120, army = 7})      -- dead: not away
B.dwarf(1006, 6, {killed = true, inactive = true})
B.squad(1, 'A', {1001, 1002, 1003, 1004, 1005, 1006}, 5)
B.controller{id = 5, entity_id = 200, goal = B.G.SITE_INVASION, site_id = -1, assigned_squads = {1}, data = B.S{}}
B.controller{id = 6, entity_id = 999, goal = B.G.SITE_INVASION, site_id = -1, assigned_squads = {}, data = B.S{}}
B.army(5, {{id = 50, unit = 9}})              -- a member not in a squad
B.army(6, {{id = 60, unit = 77}})             -- another civ's army
""")
    got = sorted(k for k, v in env.away_units().items() if v)
    assert got == [1, 2, 4, 9], got
    r = env.report()
    assert r.controllers[1].army_members == 1 and r.squads[1].away == 3 and r.squads[1].members == 6


if __name__ == "__main__":
    finish()
