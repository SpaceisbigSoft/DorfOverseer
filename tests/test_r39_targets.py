"""Tests for lua/ai-missions.lua targets() (0.105.39): where a mission could
go and why (rescue, recover_artifact, explore, raid, pillage, tribute,
conquer), on a fake world (pip install lupa).

    python tests/test_r39_targets.py

The fake's objects raise on a missing field, as DFHack's do, so a field the
module guesses wrong shows in the report's `unknown` list.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

SRC = (ROOT / "lua" / "ai-missions.lua").read_text(encoding="utf-8")
FAKE = r"""
local src, setup = ...
local env = setmetatable({}, {__index = _G})
local function S(t)
  return setmetatable(t, {__index = function(_, k) error('no field ' .. tostring(k), 2) end})
end
local function enum(names)
  local e = {_first_item = 0, _last_item = #names - 1}
  for i, n in ipairs(names) do e[i - 1] = n; e[n] = i - 1 end
  return e
end
local G = enum({'SITE_INVASION', 'RECOVER_ARTIFACT', 'RESCUE_HF', 'MAKE_REQUEST', 'DIPLOMACY'})
local EL = enum({'MEMBER', 'FORMER_MEMBER', 'SLAVE', 'PRISONER'})
local SL = enum({'OCCUPATION', 'HANGOUT', 'PRISON_ABSTRACT_BUILDING', 'PRISON_SITE_BUILDING_PROFILE'})
local EV = enum({'WAR_FIELD_BATTLE', 'HIST_FIGURE_ABDUCTED', 'ITEM_STOLEN'})
local ENTS, HFS, UNITS, SITES = {}, {}, {}, {}
env.SCREEN = nil
env.df = {
  army_controller_goal_type = G,
  histfig_entity_link_type = EL,
  histfig_site_link_type = SL,
  history_event_type = EV,
  invasion_intent_type = enum({'RAID'}),
  world_site_type = enum({'PlayerFortress', 'DarkFortress', 'Cave', 'MountainHalls', 'ForestRetreat', 'Town'}),
  diplomacy_state_type = enum({'Peace', 'War', 'Skirmishing'}),
  world_view_mode_type = enum({'NORMAL', 'NEW_MISSION'}),
  world_new_mission_type = enum({'OKAY', 'INACCESSIBLE', 'NOT_IN_CONTACT'}),
  viewscreen_worldst = {is_instance = function(_, s) return rawget(s, '_world') == true end},
  historical_entity = {find = function(id) return ENTS[id] end},
  squad = {find = function(id) return nil end},
  historical_figure = {find = function(id) return HFS[id] end},
  unit = {find = function(id) return UNITS[id] end},
  world_site = {find = function(id) return SITES[id] end},
  nemesis_record = {find = function(id) return nil end},
  global = S{
    plotinfo = S{civ_id = 100, group_id = 200, site_id = 10},
    gview = S{view = S{child = false}},
    world = S{
      army_controllers = S{all = {}},
      armies = S{all = {}},
      status = S{mission_reports = {}, spoils_reports = {},
                 flags = S{mission = false, spoils = false, tribute = false}},
      world_data = S{sites = {}},
      history = S{events = {}},
      artifacts = S{all = {}},
    },
  },
}
env.dfhack = {
  gui = {getViewscreenByType = function(t, n) return env.SCREEN end},
  translation = {translateName = function(n, english) return n.text end},
}
local W = env.df.global.world
local B = {S = S, G = G, W = W, ENTS = ENTS, HFS = HFS, UNITS = UNITS, SITES = SITES, env = env}
local function typed(t, v) t.getType = function() return v end; return S(t) end
function B.entity(id, name, fields)
  local e = {id = id, name = {text = name or ('Ent ' .. id)}, squads = {}, histfig_ids = {},
             relations = S{diplomacy = S{state = {}}}}
  for k, v in pairs(fields or {}) do e[k] = v end
  ENTS[id] = S(e)
  return ENTS[id]
end
-- a historical figure: f.member (in the group's list), f.at (whereabouts
-- site), f.prisoner_of / f.slave_of (entity), f.prison (site), f.unit,
-- f.inactive, f.died
function B.hf(id, name, f)
  f = f or {}
  local el, sl = {}, {}
  table.insert(el, typed({entity_id = 200}, EL.MEMBER))
  if f.prisoner_of then table.insert(el, typed({entity_id = f.prisoner_of}, EL.PRISONER)) end
  if f.slave_of then table.insert(el, typed({entity_id = f.slave_of}, EL.SLAVE)) end
  if f.prison then table.insert(sl, typed({site = f.prison, sub_id = 0, entity = -1}, SL.PRISON_ABSTRACT_BUILDING)) end
  HFS[id] = S{id = id, name = {text = name}, died_year = f.died or -1, unit_id = f.unit or -1,
              entity_links = el, site_links = sl,
              info = S{whereabouts = S{site_id = f.at or -1, army_id = -1}}}
  if f.unit then UNITS[f.unit] = S{id = f.unit, flags1 = S{inactive = f.inactive == true}} end
  if f.member ~= false then table.insert(ENTS[200].histfig_ids, id) end
  return HFS[id]
end
function B.site(id, name, civ, x, y, f)
  f = f or {}
  local s = {id = id, name = {text = name}, civ_id = civ, cur_owner_id = f.cur or civ, type = f.type or 3,
             pos = S{x = x, y = y}, flag = S{RUINED = f.ruined == true, HIDDEN = f.hidden == true}}
  if f.pop then s.resident_count = f.pop end
  SITES[id] = S(s)
  table.insert(W.world_data.sites, SITES[id])
  return SITES[id]
end
function B.relation(other, rel)
  table.insert(ENTS[100].relations.diplomacy.state, S{group_id = other, relation = rel})
end
function B.abducted(target, site)
  table.insert(W.history.events, typed({id = #W.history.events, target = target, snatcher = -1, site = site,
                                         region = -1, layer = -1}, EV.HIST_FIGURE_ABDUCTED))
end
function B.event_other()
  table.insert(W.history.events, typed({id = #W.history.events}, EV.WAR_FIELD_BATTLE))
end
function B.artifact(id, name, f)
  table.insert(W.artifacts.all, S{id = id, name = {text = name}, entity_claims = f.claims or {},
                                  site = f.site or -1, storage_site = f.storage or -1,
                                  holder_hf = f.holder or -1})
end
B.entity(100, 'The Bronze Realm')
B.entity(200, 'The Fort Council')
B.site(10, 'Home', 100, 50, 50, {type = 0})
assert(load(setup, 'setup', 't', setmetatable({B = B}, {__index = _G})))()
assert(load(src, 'ai-missions', 't', env))()
return env
"""

LUA = LuaRuntime(unpack_returned_tuples=True)


def world(setup: str):
    return LUA.execute(FAKE, SRC, setup)


def lst(t):
    if t is None:
        return None
    return [t[i] for i in range(1, len(t) + 1)]


def brief(r):
    return [(t.goal, t.site_id) for t in lst(r.targets)]


EVERY = r"""
B.entity(300, 'The Goblin Horde')
B.entity(400, 'The Elf Grove')
B.relation(300, 1)                                      -- War
B.relation(400, 0)                                      -- Peace
B.site(20, 'Goblin Pits', 300, 54, 51, {pop = 3, type = 1})
B.site(21, 'Dark Tower', 300, 70, 50, {pop = 500, type = 1})
B.site(22, 'Elf Wood', 400, 52, 50, {pop = 10})
B.site(23, 'Old Hall', -1, 50, 56, {ruined = true})
B.site(24, 'Secret Ruin', -1, 51, 51, {ruined = true, hidden = true})
-- the fort's people: one in a goblin prison, one a slave there, one at home
B.hf(1001, 'Urist the Captive', {prisoner_of = 300, at = 20})
B.hf(1002, 'Bomrek the Slave', {slave_of = 300, at = 21})
B.hf(1003, 'Kadol at Home', {unit = 3, at = 10})
for i = 1, 5 do B.hf(1100 + i, 'Citizen ' .. i, {unit = 100 + i, at = 10}) end
-- an artifact the fort claims, kept in the goblin tower; one nobody claims
B.artifact(7, 'The Shining Axe', {claims = {200}, storage = 21})
B.artifact(8, 'A Goblin Thing', {claims = {300}, storage = 21})
"""


@test("targets: every goal found, best first (goal order, then nearest), names and civs, hostile/at_war")
def _():
    env = world(EVERY)
    r = env.report()
    got = brief(r)
    assert got == [("rescue", 20), ("rescue", 21), ("recover_artifact", 21), ("explore", 23),
                   ("raid", 20), ("raid", 21), ("pillage", 20), ("tribute", 20), ("conquer", 20)], got
    t = lst(r.targets)
    res = t[0]
    assert (res.hf_id, res.hf, res.site, res.dist, res.civ_id, res.civ, res.why) == \
        (1001, "Urist the Captive", "Goblin Pits", 4, 300, "The Goblin Horde", "a prisoner"), dict(res)
    assert res.hostile is True and res.at_war is True and res.ready is None
    assert t[1].hf_id == 1002 and t[1].why == "enslaved"
    art = t[2]
    assert (art.artifact_id, art.artifact, art.why) == (7, "The Shining Axe", "claimed by the fort"), dict(art)
    ex = t[3]
    assert ex.site == "Old Hall" and ex.dist == 6 and ex.why == "a ruin" and ex.hostile is False and ex.civ_id is None
    assert "Elf Wood" not in [x.site for x in t]           # at peace: no raid
    assert r.targets_partial is None
    assert len(r.unknown) == 0, lst(r.unknown)


@test("rescue: an abduction event (newest events) of a fort citizen or at the fort, not one back home or dead")
def _():
    env = world(r"""
B.entity(300, 'Gobs')
B.site(20, 'Goblin Pits', 300, 53, 50)
B.site(25, 'Far Camp', 300, 60, 60)
B.hf(2001, 'Taken Away', {member = false, at = 25})     -- not in the group any more, taken from the fort
B.hf(2002, 'Came Back', {unit = 9, at = 10})           -- abducted once, home now
B.hf(2003, 'Dead One', {at = 20, died = 120})
B.hf(2004, 'Elsewhere', {member = false, at = 20})     -- not ours, taken from another site
B.abducted(2001, 10)
B.abducted(2002, 10)
B.abducted(2003, 10)
B.abducted(2004, 77)
for i = 1, 3 do B.event_other() end
""")
    t = lst(env.report().targets)
    assert [(x.goal, x.hf_id, x.site_id, x.why) for x in t] == [("rescue", 2001, 25, "abducted")], \
        [(x.goal, x.hf_id, x.site_id, x.why) for x in t]


@test("rescue: a PRISON site link gives the place held; a prisoner of our own civ is not a rescue")
def _():
    env = world(r"""
B.entity(300, 'Gobs')
B.site(20, 'Goblin Pits', 300, 53, 50)
B.site(26, 'Prison Keep', 300, 58, 50)
B.hf(3001, 'In Prison', {prison = 26, at = 20})
B.hf(3002, 'Our Own Jail', {prisoner_of = 100, at = 20})
""")
    t = lst(env.report().targets)
    assert [(x.hf_id, x.site_id, x.why) for x in t] == [(3001, 26, "held in a prison")], \
        [(x.hf_id, x.site_id, x.why) for x in t]


@test("recover_artifact: the group's claim before the civ's, then nearest; site, holder's whereabouts; not at the fort")
def _():
    env = world(r"""
B.entity(300, 'Gobs')
B.site(20, 'Near', 300, 52, 50)
B.site(21, 'Far', 300, 60, 50)
B.site(22, 'Holder Place', 300, 51, 50)
B.hf(4001, 'Thief', {member = false, at = 22})
B.artifact(1, 'Civ Claim Near', {claims = {100}, site = 20})
B.artifact(2, 'Group Claim Far', {claims = {300, 200}, storage = 21})
B.artifact(3, 'Held By Thief', {claims = {200}, holder = 4001})
B.artifact(4, 'At Home', {claims = {200}, storage = 10})
""")
    t = lst(env.report().targets)
    assert [(x.artifact_id, x.site_id, x.why) for x in t] == [
        (3, 22, "claimed by the fort"), (2, 21, "claimed by the fort"), (1, 20, "claimed by the fort's civ")], \
        [(x.artifact_id, x.site_id, x.why) for x in t]


@test("explore: RUINED only (0.105.39 review: not an empty unowned site); not hidden; tribute/conquer need a known size and nearness")
def _():
    env = world(r"""
B.entity(300, 'Gobs')
B.relation(300, 2)                                      -- Skirmishing: hostile, not at war
B.site(30, 'Empty Lair', -1, 47, 50, {pop = 0})
B.site(31, 'Lived In', -1, 49, 50, {pop = 4})          -- people there: not a ruin
B.site(32, 'Gob Camp', 300, 55, 50)                     -- size unknown: raid/pillage only
B.site(33, 'Gob Hamlet', 300, 56, 50, {pop = 2})        -- smaller, near: tribute, not conquer (not at war)
for i = 1, 4 do B.hf(1100 + i, 'Citizen ' .. i, {unit = 100 + i, at = 10}) end   -- the fort: 4
""")
    r = env.report()
    got = [(x.goal, x.site_id) for x in lst(r.targets)]
    assert got == [("raid", 32), ("raid", 33), ("pillage", 32), ("tribute", 33)], got
    t = lst(r.targets)
    assert t[0].hostile is True and t[0].at_war is False and t[0].why == "hostile: Skirmishing"


@test("caps: at most 12, per-goal caps, the nearest kept; names truncated to 40")
def _():
    long = "A" * 60
    env = world(r"""
B.entity(300, '%s')
B.relation(300, 1)
for i = 1, 10 do B.site(40 + i, '%s' .. i, 300, 50 + i, 50, {pop = 1}) end
for i = 1, 10 do B.site(60 + i, 'Ruin ' .. i, -1, 50, 50 + i, {ruined = true}) end
for i = 1, 6 do B.hf(5000 + i, '%s', {prisoner_of = 300, at = 40 + i}) end
for i = 1, 6 do B.artifact(i, '%s', {claims = {200}, storage = 40 + i}) end
""" % (long, long, long, long))
    r = env.report()
    t = lst(r.targets)
    assert len(t) == 12, len(t)
    goals = [x.goal for x in t]
    assert goals == ["rescue"] * 4 + ["recover_artifact"] * 3 + ["explore"] * 2 + ["raid"] * 2 + ["pillage"], goals
    assert [x.hf_id for x in t[:4]] == [5001, 5002, 5003, 5004]
    assert [x.site_id for x in t[7:9]] == [61, 62]
    for x in t:
        for k in ("site", "civ", "hf", "artifact"):
            v = x[k]
            assert v is None or len(v) <= 40, (k, v)
    assert t[0].hf == "A" * 40 and t[0].civ == "A" * 40 and t[4].artifact == "A" * 40


@test("ready: the open World screen's verdict for the goal, only at its focus site")
def _():
    env = world(EVERY + r"""
local nm = B.S{[0] = 0, [1] = 1, [2] = 2, [3] = 0, [4] = 0}   -- SITE_INVASION OKAY, RECOVER INACCESSIBLE, RESCUE NOT_IN_CONTACT
B.env.SCREEN = setmetatable({_world = true, view_mode = 1, focus_site = B.SITES[20], new_mission = nm,
                             focus_site_prisoner = {}}, getmetatable(B.S{}))
""")
    t = lst(env.report().targets)
    at20 = {x.goal: x.ready for x in t if x.site_id == 20}
    assert at20 == {"rescue": "NOT_IN_CONTACT", "raid": "OKAY", "pillage": "OKAY", "tribute": "OKAY",
                    "conquer": "OKAY"}, at20
    assert all(x.ready is None for x in t if x.site_id != 20)


@test("the screen's focus_site_prisoner: a fort citizen held there is a rescue even without a link")
def _():
    env = world(r"""
B.entity(300, 'Gobs')
B.site(20, 'Goblin Pits', 300, 53, 50)
local hf = B.hf(6001, 'Quiet Captive', {})
B.env.SCREEN = setmetatable({_world = true, view_mode = 1, focus_site = B.SITES[20],
                             new_mission = B.S{[0] = 0, [1] = 0, [2] = 0}, focus_site_prisoner = {hf}},
                            getmetatable(B.S{}))
""")
    t = lst(env.report().targets)
    assert [(x.goal, x.hf_id, x.site_id, x.ready) for x in t] == [("rescue", 6001, 20, "OKAY")], \
        [(x.goal, x.hf_id, x.site_id, x.ready) for x in t]


@test("missing fields: noted in unknown, not an error; the rest of the targets still found")
def _():
    env = world(EVERY + r"""
rawset(B.W, 'artifacts', nil)                 -- gone from this version
rawset(B.W, 'history', nil)
local e = B.ENTS[200]
rawset(e, 'histfig_ids', nil)
""")
    r = env.report()
    unk = lst(r.unknown)
    for f in ("world.artifacts.all", "world.history.events", "entity.histfig_ids"):
        assert f in unk, (f, unk)
    got = brief(r)
    assert ("explore", 23) in got and ("raid", 20) in got, got
    assert not any(g == "recover_artifact" or g == "tribute" for g, _ in got), got   # no claims, no fort size
    # targets() itself throwing: noted, an empty list
    env2 = world("")
    env2.GOAL_ORDER = None
    r2 = env2.report()
    assert len(r2.targets) == 0 and "targets" in lst(r2.unknown), lst(r2.unknown)


@test("time budget: the walk stops after 0.05 s of os.clock and says partial")
def _():
    env = world(EVERY + r"""
local t = 0
B.env.os = {clock = function() t = t + 0.004; return t end}
for i = 1, 200 do B.event_other() end
""")
    r = env.report()
    assert r.targets_partial is True
    got = brief(r)
    assert got[:2] == [("rescue", 20), ("rescue", 21)], got
    assert not any(g == "explore" for g, _ in got), got     # never reached
    # direct call, with its own reader
    out, partial = env.targets(None, 100, 200, 10)
    assert partial is True


# --- (0.105.39 review) -----------------------------------------------------------------

@test("(0.105.39 review) explore: a ruined cave or lair is no ruin to explore; recover_artifact: not from a site "
      "of the fort's own civ or group")
def _():
    env = world(r"""
B.entity(300, 'Gobs')
B.site(30, 'Ruined Cave', -1, 47, 50, {ruined = true, type = 2})          -- Cave
B.site(31, 'Old Hall', -1, 48, 50, {ruined = true, type = 3})
B.site(32, 'Kin Town', 100, 49, 50)                                        -- the fort's civ's
B.site(33, 'Gob Keep', 300, 52, 50)
B.artifact(1, 'Lent To Kin', {claims = {200}, site = 32})
B.artifact(2, 'Stolen', {claims = {200}, site = 33})
""")
    got = brief(env.report())
    assert got == [("recover_artifact", 33), ("explore", 31)], got
    env.df.world_site_type = env.df.world_site_type      # LairShrine named too
    assert env.EXPLORE_NOT.LairShrine and env.EXPLORE_NOT.Cave


@test("(0.105.39 review) the time budget by dfhack.getTickCount (ms) when there is one")
def _():
    env = world(EVERY + r"""
local ms = 0
B.env.dfhack.getTickCount = function() ms = ms + 4; return ms end
B.env.os = {clock = function() return 0 end}                 -- CPU time never moves: not used
for i = 1, 200 do B.event_other() end
""")
    r = env.report()
    assert r.targets_partial is True, "the ms clock wasn't used"
    env = world(EVERY + r"""
B.env.dfhack.getTickCount = function() return 1000 end
""")
    assert env.report().targets_partial is None


@test("(0.105.39 review) the controllers' cap keeps the fort's own: those holding its squads or of its group first")
def _():
    env = world(r"""
local W = B.W
for i = 1, 14 do table.insert(W.army_controllers.all, B.S{id = i, entity_id = 100, goal = 0, site_id = -1,
                                                         assigned_squads = {}}) end
table.insert(W.army_controllers.all, B.S{id = 50, entity_id = 200, goal = 2, site_id = -1, assigned_squads = {}})
table.insert(W.army_controllers.all, B.S{id = 51, entity_id = 100, goal = 1, site_id = -1, assigned_squads = {7}})
B.ENTS[200].squads = {7}
B.env.df.squad = {find = function(id) if id == 7 then return B.S{id = 7, alias = 'Axes', name = {text = 'x'},
                                        assigned_army_controller_id = 51, positions = {}} end end}
""")
    ids = [c.id for c in lst(env.report().controllers)]
    assert len(ids) == env.MAX_CONTROLLERS and ids[:2] == [50, 51] and ids[2:] == list(range(1, 9)), ids


@test("(0.105.39 review) status_of: where the last runs' citizen and artifact are now (home / dead / held / "
      "unknown; fort / away / unknown), string keys")
def _():
    env = world(r"""
B.entity(300, 'Gobs')
B.site(20, 'Pits', 300, 53, 50)
B.hf(1, 'Home Again', {unit = 5, at = 10})
B.hf(2, 'Still Held', {prisoner_of = 300, at = 20})
B.hf(3, 'Dead', {died = 120})
B.hf(4, 'Somewhere', {at = 20})
B.artifact(7, 'Back', {claims = {200}, site = 10})
B.artifact(8, 'Away', {claims = {200}, site = 20})
B.artifact(9, 'Lost', {claims = {200}})
B.env.reqscript = function(n)
  if n == 'ai-mission-send' then
    return {last_by_goal = function() return {rescue = {hf_id = 2}, recover_artifact = {artifact_id = 8},
                                              make_contact = {}} end}
  end
  error('no ' .. n)
end
""")
    so = env.status_of(None, 100, 200, 10, LUA.table_from({"hf": LUA.table_from([1, 2, 3, 4, 99]),
                                                          "artifact": LUA.table_from([7, 8, 9])}))
    assert dict(so.hf) == {"1": "home", "2": "held", "3": "dead", "4": "unknown", "99": "unknown"}, dict(so.hf)
    assert dict(so.artifact) == {"7": "fort", "8": "away", "9": "unknown"}, dict(so.artifact)
    r = env.report()
    assert dict(r.status_of.hf) == {"2": "held"} and dict(r.status_of.artifact) == {"8": "away"}, \
        (dict(r.status_of.hf), dict(r.status_of.artifact))


@test("(0.105.39 review) site_hostile: the owner's relation to the fort's civ; the fort's own never hostile")
def _():
    env = world(r"""
B.entity(300, 'Gobs'); B.entity(400, 'Elves')
B.relation(300, 1); B.relation(400, 0)
B.site(20, 'Pits', 300, 53, 50)
B.site(22, 'Wood', 400, 52, 50)
B.site(23, 'Kin', 100, 52, 52)
""")
    h = env.site_hostile(20)
    assert h.hostile is True and h.at_war is True and h.relation == "War" and h.owner == 300
    h = env.site_hostile(22)
    assert h.hostile is False and h.relation == "Peace"
    h = env.site_hostile(23)
    assert h.hostile is False and h.ours is True
    h, why = env.site_hostile(99)
    assert h is None and "no site 99" in why


@test("(0.105.39 review 2) explore needs a readable site type (not a cave or a lair shrine); no MonsterLair name")
def _():
    env = world(r"""
B.site(30, 'No Type', -1, 47, 50, {ruined = true})
rawset(B.SITES[30], 'type', nil)                     -- unreadable: the fake raises
B.site(31, 'Odd Type', -1, 48, 50, {ruined = true, type = 77})
B.site(32, 'Old Hall', -1, 49, 50, {ruined = true, type = 3})
""")
    assert brief(env.report()) == [("explore", 32)], brief(env.report())
    assert env.EXPLORE_NOT.MonsterLair is None


if __name__ == "__main__":
    finish()
