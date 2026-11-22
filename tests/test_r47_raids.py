"""(0.105.47, J17) The raid policy by the fort's character (brain/planner_raids.py,
lua/ai-raids.lua, the missions rule and the bridge's double check), the
player 14 Nov 17:47: the aggressive fort (high Militarism, the War-hold) may
raid any civ but its friends; every other fort reacts (an attacker, a hostile
site setting up close by); the Monastery only with a sure win; the Raids
switch; and the raid party's pets (live 17:38: a sheep in an AI pasture held
the squad at the map edge).

    python tests/test_r47_raids.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402
from lua_modules_util import bridge_hub_src  # noqa: E402  (r8) the hub's text with its catalog and sections

from planner import PLANNER_CONFIG, TICKS_PER_DAY, TICKS_PER_YEAR  # noqa: E402
import planner_missions as PM  # noqa: E402
import planner_raids as PR  # noqa: E402
import digest  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG
YEAR = 148
NOW = YEAR * TICKS_PER_YEAR + 332256


def site(sid, civ_id, dist, pop=10, typ="Camp", civ=None, **kw) -> dict:
    r = {"site_id": sid, "site": f"Site{sid}", "dist": dist, "civ_id": civ_id, "owner_id": civ_id,
         "civ": civ or f"Civ{civ_id}", "type": typ, "pop": pop, "relation": "Peace"}
    r.update(kw)
    return r


def fort(rows=(), targets=(), world=None, militarism=0, power=60.0, send=None, pets=None, **settings) -> dict:
    s = copy.deepcopy(BASE)
    s["settings"]["traits"] = {"militarism": militarism}
    for k in ("caution", "greed", "outsiders"):
        if k in settings:
            s["settings"]["traits"][k] = settings.pop(k)
    # (0.105.48, K9) raid_policy is 'off' by default now: these tests turn it on ('ai')
    s["settings"].update({"missions": "all", "send_missions": True, "raid_policy": "ai"})
    s["settings"].update(settings)
    if settings.pop("third_squad", False):           # 30 soldiers: the timid fort's reserve lets one squad go
        q = copy.deepcopy(s["military"]["squads"][-1])
        q["id"], q["name"] = 13, "The Third"
        s["military"]["squads"].append(q)
        s["military"]["soldiers"] = 30
    for q in s["military"]["squads"]:
        q["power"] = {"power": power, "armed": q["members"], "armored": 0}
    s["missions"] = {"controllers": [], "reports": {"n": 0, "unviewed": 0}, "spoils": {"n": 0}, "sites": {},
                     "unknown": [], "squads": [{"id": q["id"], "name": q["name"], "members": q["members"], "away": 0}
                                               for q in s["military"]["squads"]],
                     "targets": list(targets), "raid_sites": {"rows": [dict(r) for r in rows]},
                     "send": send if send is not None else button()}
    if pets is not None:
        s["missions"]["pets"] = pets
    s["world"] = world if world is not None else {}
    return digest.normalize(s)


def button(last_by_goal=None) -> dict:
    d = {"on": True, "buttons": ["World", "Diplomacy"],
         "goals": {g: {"button": True, "recorded": "confirm"} for g in PM.MISSION_GOALS}}
    if last_by_goal:
        d["last_by_goal"] = last_by_goal
    return d


class Mem:
    def __init__(self):
        self.missions_seen = {}
        self.world_seen = {}


def rule(s, memory=None):
    props, notes = [], []
    PM._mission_rule(s, CFG, props, notes, memory)
    return props, notes


def sent(props):
    return [p for p in props if p.action.get("type") == "send_mission"]


# --- aggressive ------------------------------------------------------------------------------

@test("aggressive (Militarism 150): a civ at peace that isn't a friend is raided; the friends (a caravan here, a "
      "trader, a peace pending, an ally) never; the action carries policy 'aggressive' and why")
def _():
    world = {"civs": [{"id": 20, "relation": "Peace"}, {"id": 21, "relation": "Peace"}, {"id": 22, "relation": "Peace"},
                      {"id": 23, "relation": "Peace", "peace_offered": True}, {"id": 24, "relation": "Peace", "allies": True}],
             "caravans": [{"civ_id": 21, "civ": "Civ21"}]}
    rows = [site(1, 21, 2, pop=3), site(2, 22, 3, pop=3), site(3, 23, 4, pop=3), site(4, 24, 5, pop=3),
            site(5, 20, 12, pop=10, civ="the Witch of Hardiness")]
    m = Mem()
    m.missions_seen = {"raids": {"traders": {"22": {"n": 2, "last": 1}}}}
    p, notes = rule(fort(rows, world=world, militarism=150), m)
    a = sent(p)
    assert len(a) == 1 and a[0].action["site_id"] == 5 and a[0].action["goal"] == "raid", (p, notes)
    assert a[0].action["policy"] == "aggressive"
    assert "aggressive" in a[0].reason and "the weakest reachable site of the Witch of Hardiness" in a[0].reason, a[0].reason
    fr = PR.raid_friends(fort(rows, world=world, militarism=150), m)
    assert set(fr) == {21, 22, 23, 24} and fr[23] == "a peace pending" and fr[24] == "an ally", fr


@test("aggressive: at least two friends kept (the civs at peace with the most contact); Outsiders high keeps one "
      "more, ((r10 p3) very low no fewer)")
def _():
    world = {"civs": [{"id": 20, "relation": "Peace"}, {"id": 21, "relation": "Peace"}, {"id": 25, "relation": "Peace"},
                      {"id": 26, "relation": "TotalWar"}]}
    m = Mem()
    m.missions_seen = {"raids": {"traders": {}}}
    fr = PR.raid_friends(fort(world=world, militarism=150), m)
    assert set(fr) == {20, 21} and all("kept as a friend" in v for v in fr.values()), fr       # never the enemy (26)
    assert len(PR.raid_friends(fort(world=world, militarism=150, outsiders=60), m)) == 3
    # (r10 p3 fix L4) a very closed fort keeps two as well, never one
    assert len(PR.raid_friends(fort(world=world, militarism=150, outsiders=-150), m)) == 2
    rows = [site(1, 20, 2), site(2, 21, 2), site(3, 25, 9), site(4, 26, 10)]
    p, _ = rule(fort(rows, world=world, militarism=150), m)
    assert sent(p)[0].action["site_id"] == 3, p       # 25: not a friend; the nearest clear win after the friends


@test("aggressive: the weakest site the squads clearly beat first, then the nearest; too strong passed over; "
      "Greed high: the richest clear win")
def _():
    rows = [site(1, 30, 2, pop=30), site(2, 31, 10, pop=5), site(3, 32, 1, pop=150, typ="Town")]
    world = {"civs": [{"id": 40, "relation": "Peace", "allies": True}, {"id": 41, "relation": "Peace", "allies": True}]}
    p, _ = rule(fort(rows, world=world, militarism=150))
    assert sent(p)[0].action["site_id"] == 2, p
    p, _ = rule(fort(rows, world=world, militarism=150, greed=80))
    assert sent(p)[0].action["site_id"] == 1 and "the richest" in sent(p)[0].reason, p
    cands, passed, stance = PR.raid_candidates(fort(rows, world=world, militarism=150), CFG)
    assert stance == "aggressive" and [c["site_id"] for c in cands] == [2, 1]
    assert any("Site3" in w and "too strong" in w for w in passed), passed


# --- reactive -----------------------------------------------------------------------------------

@test("reactive (the sliders at 0): a civ at peace that never attacked is never raided, near or not")
def _():
    rows = [site(1, 20, 2), site(2, 21, 30)]
    p, notes = rule(fort(rows, world={"civs": [{"id": 20, "relation": "Peace"}]}))
    assert not sent(p), p
    assert any(n.startswith("raids: ") and "no raid" in n for n in notes), notes


@test("reactive: retaliation against a civ that attacked the fort within 3 years, at its nearest site the squads "
      "clearly beat; an old attack, a peace pending: left alone")
def _():
    rows = [site(1, 30, 25, pop=10), site(2, 30, 20, pop=10), site(3, 30, 5, pop=200, typ="DarkFortress")]
    # (0.105.48, K9) retaliation only while still at war: TotalWar (at peace: tests/test_k48_raids.py)
    world = {"civs": [{"id": 30, "relation": "TotalWar"}],
             "sieges": [{"id": 30, "n": 2, "last_year": 147, "last_siege": True, "name": "The Goblins"}]}
    p, _ = rule(fort(rows, world=world))
    a = sent(p)
    assert a and a[0].action["site_id"] == 2 and a[0].action["policy"] == "retaliation", p
    assert "retaliation for the siege of y147" in a[0].reason, a[0].reason
    w2 = copy.deepcopy(world)
    w2["sieges"][0].update(last_year=140)
    assert not sent(rule(fort(rows, world=w2))[0])
    w3 = copy.deepcopy(world)
    w3["civs"][0]["peace_offered"] = True
    p, notes = rule(fort(rows, world=w3))
    assert not sent(p) and any("a peace pending" in n for n in notes), notes
    # thieves or an ambush (an invasion with no army) count too; the grudge list too
    w4 = copy.deepcopy(world)
    w4["sieges"][0]["last_siege"] = False
    assert "the thieves or ambush of y147" in sent(rule(fort(rows, world=w4))[0])[0].reason
    m = Mem()
    m.world_seen = {"grudges": {"30": {"name": "The Goblins", "sieges": 1, "last_year": 146}}}
    assert sent(rule(fort(rows, world={"civs": [{"id": 30, "relation": "TotalWar"}]}), m)[0])


@test("reactive: a hostile camp (or bandits) close by is removed before it grows; one farther only when new since "
      "the AI began watching")
def _():
    rows = [site(1, 50, 6, relation="TotalWar", hostile=True, at_war=True)]
    a = sent(rule(fort(rows))[0])
    assert a and a[0].action["policy"] == "threat" and "a camp 6 tile(s) away" in a[0].reason, a
    far = [site(1, 50, 12, relation="TotalWar", hostile=True, at_war=True)]
    assert not sent(rule(fort(far))[0])
    m = Mem()
    m.missions_seen = {"raids": {"since": 100, "sites": {"1": 5000}}}
    a = sent(rule(fort(far), m)[0])
    assert a and "a new camp setting up 12 tiles away" in a[0].reason, a
    bandits = [site(7, None, 5, bandit=True, civ=None, relation="unknown")]
    bandits[0]["civ"] = None
    a = sent(rule(fort(bandits))[0])
    assert a and a[0].action["site_id"] == 7 and "bandits" in a[0].reason, a
    # too strong: passed over and said
    big = [site(1, 50, 6, pop=200, typ="DarkFortress", relation="TotalWar", hostile=True)]
    p, notes = rule(fort(big))
    assert not sent(p) and any("too strong" in n for n in notes), notes


@test("timid (Militarism -60, the Monastery): retaliation only with a sure win (3x); a threat only within 4 tiles")
def _():
    world = {"civs": [{"id": 30, "relation": "Skirmishing"}], "sieges": [{"id": 30, "n": 1, "last_year": 147}]}
    # one squad of 10 at power 60 (the reserve keeps the other); pop 50 Camp: (4 + 25) x 0.8 = 23.2 -> 2.6x
    mid = [site(1, 30, 10, pop=50)]
    assert sent(rule(fort(mid, world=world))[0])                       # reactive: 2.6x >= 2
    assert not sent(rule(fort(mid, world=world, militarism=-60, third_squad=True))[0])   # timid wants 3x
    assert sent(rule(fort([site(1, 30, 10, pop=10)], world=world, militarism=-60, third_squad=True))[0])
    near6 = [site(2, 50, 6, relation="TotalWar", hostile=True)]
    assert not sent(rule(fort(near6, militarism=-60, third_squad=True))[0])
    assert sent(rule(fort([site(2, 50, 3, relation="TotalWar", hostile=True)], militarism=-60, third_squad=True))[0])


@test("the Raids switch: off sends no attack at all; reactive and aggressive override the sliders; ai follows them")
def _():
    rows = [site(1, 20, 5), site(2, 50, 4, relation="TotalWar", hostile=True)]
    world = {"civs": [{"id": 40, "relation": "Peace", "allies": True}, {"id": 41, "relation": "Peace", "allies": True}]}
    p, notes = rule(fort(rows, world=world, militarism=150, raid_policy="off"))
    assert not sent(p) and any("is off" in n for n in notes), notes
    assert PR.raid_stance(fort(militarism=150, raid_policy="reactive"))[0] == "reactive"
    assert PR.raid_stance(fort(militarism=0, raid_policy="aggressive"))[0] == "aggressive"
    assert PR.raid_stance(fort(militarism=150))[0] == "aggressive"
    assert PR.raid_stance(fort(militarism=-60))[0] == "timid"
    assert PR.raid_stance(fort(militarism=-30))[0] == "reactive"          # the Garden fort
    a = sent(rule(fort(rows, world=world, militarism=150, raid_policy="reactive"))[0])
    assert a and a[0].action["site_id"] == 2 and a[0].action["policy"] == "threat"
    a = sent(rule(fort(rows, world=world, militarism=0, raid_policy="aggressive"))[0])
    assert a and a[0].action["site_id"] == 2 and a[0].action["policy"] == "aggressive"   # both clear wins of the same strength: the nearest
    # below 'all' no raid whatever the policy
    assert not sent(rule(fort(rows, world=world, militarism=150, missions="explore"))[0])


@test("pace: a season between two attacks (the sender's last raid, or the book); a rescue still goes")
def _():
    rows = [site(2, 50, 4, relation="TotalWar", hostile=True)]
    last = {"raid": {"goal": "raid", "result": "sent", "site_id": 9, "tick": NOW - 30 * TICKS_PER_DAY}}
    p, notes = rule(fort(rows, send=button(last)))
    assert not sent(p) and any("one a season" in n for n in notes), notes
    last["raid"]["tick"] = NOW - 90 * TICKS_PER_DAY
    assert sent(rule(fort(rows, send=button(last)))[0])
    m = Mem()
    m.missions_seen = {"raids": {"last": NOW - 10 * TICKS_PER_DAY}}
    assert not sent(rule(fort(rows), m)[0])
    resc = {"goal": "rescue", "site_id": 77, "site": "Site77", "dist": 9, "hf_id": 5, "hf": "Urist"}
    a = sent(rule(fort(rows, targets=[resc]), m)[0])
    assert a and a[0].action["goal"] == "rescue" and "policy" not in a[0].action


@test("note_raids: when the AI began watching, each site's first sight, the caravans counted once a visit, the last "
      "attack")
def _():
    m = Mem()
    s = fort([site(1, 20, 5)], world={"caravans": [{"civ_id": 21}]})
    PR.note_raids(s, m)
    r = m.missions_seen["raids"]
    assert r["since"] == NOW and r["sites"] == {"1": NOW} and r["traders"] == {"21": {"n": 1, "last": NOW}}
    PR.note_raids(s, m)
    assert r["traders"]["21"]["n"] == 1                       # the same caravan still here
    s2 = fort([], world={"caravans": []})
    PR.note_raids(s2, m)
    PR.note_raids(s, m)
    assert r["traders"]["21"]["n"] == 2
    s3 = fort([], send=button({"raid": {"result": "sent", "tick": NOW - 5}}))
    PR.note_raids(s3, m)
    assert r["last"] == NOW - 5


# --- pets ---------------------------------------------------------------------------------------

def pet(squad, unit, pid, held="pasture", ai=True):
    return {"squad_id": squad, "unit_id": unit, "pet_id": pid, "pet": "sheep", "held": held, "zone_id": 900, "ai": ai}


@test("pets: a soldier's pet in the AI's pasture is let out first (mission_pets release), the send waits a cycle")
def _():
    rows = [site(2, 50, 4, relation="TotalWar", hostile=True)]
    p, _ = rule(fort(rows, pets={"held": [pet(11, 301, 501), pet(11, 302, 502, held="zone")], "book": []}))
    assert not sent(p), p
    rel = [x for x in p if x.action.get("type") == "mission_pets"]
    assert rel and rel[0].action == {"type": "mission_pets", "op": "release", "pet_ids": [501, 502]}, rel
    assert "sheep kept in a pasture of the AI's" in rel[0].reason, rel[0].reason
    # once let out, the send goes
    assert sent(rule(fort(rows, pets={"held": [], "book": [{"pet_id": 501, "state": "away", "tick": NOW}]}))[0])


@test("pets: a squad whose soldier's pet is caged (or in the player's zone) stays home, another goes; with none "
      "left the soldier is swapped out (squad_swap, avoiding the pet owners)")
def _():
    rows = [site(2, 50, 4, relation="TotalWar", hostile=True)]
    a = sent(rule(fort(rows, pets={"held": [pet(11, 301, 501, held="cage", ai=None)], "book": []}))[0])
    assert a and a[0].action["squad_ids"] == [12], a
    both = {"held": [pet(11, 301, 501, held="cage", ai=None), pet(12, 401, 601, ai=False)], "book": []}
    p, _ = rule(fort(rows, pets=both))
    assert not sent(p)
    sw = [x for x in p if x.action.get("type") == "squad_swap"]
    assert sw and sw[0].action["unit_id"] == 301 and sw[0].action["avoid"] == [301, 401], sw
    assert "in a cage" in sw[0].reason
    p, notes = rule(fort(rows, pets=both, fill_squads=False))
    assert not [x for x in p if x.action.get("type") == "squad_swap"] and any("stays home" in n for n in notes)


@test("pets: put back once home (restore) only when no mission is out, nothing was just sent, and booked 2 days ago")
def _():
    book = [{"pet_id": 501, "zone_id": 900, "owner_id": 301, "tick": NOW - 3 * TICKS_PER_DAY, "state": "ready"}]
    s = fort(pets={"held": [], "book": book})
    p, _ = rule(s)
    assert [x.action for x in p if x.action.get("type") == "mission_pets"] == [{"type": "mission_pets", "op": "restore"}]
    s = fort(pets={"held": [], "book": [dict(book[0], tick=NOW - TICKS_PER_DAY)]})
    assert not [x for x in rule(s)[0] if x.action.get("type") == "mission_pets"]
    s = fort(pets={"held": [], "book": [dict(book[0], state="away")]})
    assert not [x for x in rule(s)[0] if x.action.get("type") == "mission_pets"]
    s = fort(pets={"held": [], "book": book})
    s["missions"]["squads"][0]["away"] = 10
    s["missions"]["squads"][0]["controller"] = 77     # (0.105.48, K9) a squad out has a controller
    assert not [x for x in rule(s)[0] if x.action.get("type") == "mission_pets"]
    s = fort(pets={"held": [], "book": book}, send=button({"raid": {"result": "sent", "tick": NOW - 100}}))
    assert not [x for x in rule(s)[0] if x.action.get("type") == "mission_pets"]


@test("the departure watch names a soldier's pet it waits for")
def _():
    c = {"departed": False, "waiting": [{"unit_id": 301, "on_map": True, "path_goal": "None",
                                         "pet": {"pet": "sheep", "held": "pasture", "ai": True}}]}
    assert "waiting for its sheep kept in a pasture of the AI's" in PM._who_words(c)


# --- the Lua side ---------------------------------------------------------------------------------

try:
    from lupa.lua53 import LuaRuntime
    HAVE_LUPA = True
except ImportError:
    HAVE_LUPA = False

from lua_modules_util import module_src  # noqa: E402

FAKE = r"""
local src = ...
local G = {persist = {}}
local function vec(list)
  local v = setmetatable({_n = 0}, {__len = function(self) return rawget(self, '_n') end})
  function v:erase(i) for j = i, self._n - 2 do self[j] = self[j + 1] end; self[self._n - 1] = nil; self._n = self._n - 1 end
  function v:insert(at, x) self[self._n] = x; self._n = self._n + 1 end
  for _, x in ipairs(list or {}) do v[v._n] = x; v._n = v._n + 1 end
  return v
end
G.vec = vec
local REF = 7
local units, buildings = {}, {}
G.units, G.buildings = units, buildings
local function ent(id, typ, name) return {id = id, type = typ, name = name,
  relations = {diplomacy = {state = vec({{group_id = 20, relation = 1}, {group_id = 50, relation = 2}})}}} end
local ents = {[1] = ent(1, 0, 'Us'), [20] = ent(20, 0, 'Peaceful'), [21] = ent(21, 0, 'Other'), [50] = ent(50, 0, 'Goblins'),
              [60] = ent(60, 5, 'Bandits')}
local function S(id, x, y, civ_id, cur, kw)
  local s = {id = id, pos = {x = x, y = y}, civ_id = civ_id, cur_owner_id = cur or -1, type = 9, resident_count = 12,
             flag = {HIDDEN = false, RUINED = false}, name = 'Site' .. id, land = 1}
  for k, v in pairs(kw or {}) do s[k] = v end
  return s
end
local sites = vec({S(100, 50, 50, 1), S(1, 52, 50, 20), S(2, 55, 50, 20), S(3, 56, 50, 20), S(4, 57, 50, 20),
  S(5, 51, 51, 50), S(6, 53, 53, -1, 60), S(7, 51, 50, 21, -1, {land = 2}), S(8, 51, 52, 21, -1, {flag = {HIDDEN = true}}),
  S(9, 52, 52, 21, -1, {flag = {RUINED = true}}), S(10, 99, 99, 21), S(11, 54, 50, 1)})
local env = setmetatable({}, {__index = _G})
env.df = {
  global = {cur_year = 148, cur_year_tick = 100, plotinfo = {civ_id = 1, group_id = 2, site_id = 100},
            world = {world_data = {sites = sites}, units = {active = vec()}}},
  historical_entity = {find = function(id) return ents[id] end},
  historical_entity_type = {[0] = 'Civilization', [5] = 'SiteGovernment'},
  diplomacy_state_type = {[1] = 'Peace', [2] = 'TotalWar'},
  world_site_type = {[9] = 'Camp'},
  civzone_type = {Pen = 3},
  general_ref_type = {BUILDING_CIVZONE_ASSIGNED = REF},
  unit = {find = function(id) return units[id] end},
  building = {find = function(id) return buildings[id] end},
  creature_raw = {find = function(r) return {creature_id = 'SHEEP', caste = {[0] = {caste_name = {[0] = 'sheep'}}}} end},
  general_ref_building_civzone_assignedst = {new = function() local r = {}; function r:getType() return REF end; return r end},
}
env.dfhack = {
  translation = {translateName = function(n) return n end},
  units = {isAlive = function(u) return not u.dead end,
           getGeneralRef = function(u, t)
             for i = 0, #u.general_refs - 1 do local r = u.general_refs[i]; if r:getType() == t then return r end end
           end},
  persistent = {getSiteData = function(k, d) local v = G.persist[k]; if v == nil then return d end; return v end,
                saveSiteData = function(k, v) G.persist[k] = v end},
}
env.require = function(n) error('no ' .. n) end
env.reqscript = function(n)
  if n == 'ai-missions' then return {site_landmass = function(s) return s.land end} end
  error('no script ' .. n)
end
function G.unit(id, kw)
  local u = {id = id, flags1 = {}, race = 1, caste = 0, relationship_ids = {PetOwner = -1}, general_refs = vec()}
  for k, v in pairs(kw or {}) do u[k] = v end
  units[id] = u
  env.df.global.world.units.active:insert('#', u)
  return u
end
function G.zone(id, name, pen)
  local z = {id = id, name = name, type = pen and 3 or 1, assigned_units = vec()}
  buildings[id] = z
  return z
end
function G.put(u, z)
  z.assigned_units:insert('#', u.id)
  local r = env.df.general_ref_building_civzone_assignedst.new(); r.building_id = z.id
  u.general_refs:insert('#', r)
end
assert(load(src, 'ai-raids', 't', env))()
return env, G
"""


def lua_env():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, G = lua.execute(FAKE, module_src("ai-raids.lua"))
    return lua, env, G


def L(t):
    return [t[i] for i in range(1, len(t) + 1)]


if HAVE_LUPA:
    @test("ai-raids raid_sites: every owner's nearest sites (3 each), civs at peace and bandits too; never the fort's "
          "own civ, a hidden or ruined site, another landmass, or one past 40 tiles")
    def _():
        lua, env, G = lua_env()
        r = env.raid_sites()
        rows = L(r.rows)
        ids = [x.site_id for x in rows]
        assert ids == [5, 1, 6, 2, 3], ids            # civ 20 capped at its nearest 3 (4 dropped); 11 is ours
        by = {x.site_id: x for x in rows}
        assert by[5].hostile is True and by[5].at_war is True and by[5].relation == "TotalWar"
        assert by[1].relation == "Peace" and by[1].hostile is None and by[1].pop == 12 and by[1].type == "Camp"
        assert by[6].bandit is True and by[6].civ_id is None and by[6].owner_id == 60 and by[6].owner_kind == "SiteGovernment"
        assert r.other_landmass == 1

    @test("ai-raids pets: a soldier's pet held in the AI's pasture is reported and let out (both links undone, "
          "booked), the player's zone and a cage refused, a dry run changes nothing; put back once both are home")
    def _():
        lua, env, G = lua_env()
        n = lua.eval("function(v) return #v end")
        z = G.zone(900, "AI pasture", True)
        mine = G.zone(901, "My pen", True)
        G.unit(301)
        sheep = G.unit(501, lua.table_from({"relationship_ids": lua.table_from({"PetOwner": 301})}))
        G.put(sheep, z)
        bird = G.unit(502, lua.table_from({"relationship_ids": lua.table_from({"PetOwner": 301})}))
        G.put(bird, mine)
        cat = G.unit(503, lua.table_from({"relationship_ids": lua.table_from({"PetOwner": 301}),
                                          "flags1": lua.table_from({"caged": True})}))
        sq = lua.table_from([lua.table_from({"id": 11, "units": lua.table_from([301])})])
        rep = env.pets_report(sq)
        held = {p.pet_id: p for p in L(rep.held)}
        assert set(held) == {501, 502, 503}
        assert held[501].held == "pasture" and held[501].ai is True and held[501].squad_id == 11 and held[501].unit_id == 301
        assert held[502].ai is None and held[503].held == "cage"
        r = env.release_pets(lua.table_from([501, 502, 503]), True)
        assert r.ok and r.dry_run and n(z.assigned_units) == 1 and G.persist["ai-overseer/raid_pets"] is None
        r = env.release_pets(lua.table_from([501, 502, 503]))
        assert r.ok and len(L(r.released)) == 1 and len(L(r.refused)) == 2, r
        assert n(z.assigned_units) == 0 and n(sheep.general_refs) == 0 and n(mine.assigned_units) == 1
        book = env.pets_report(sq).book
        assert book[1].pet_id == 501 and book[1].state == "ready"
        assert not env.release_pets(lua.table_from([503])).ok
        # away on the mission: kept; home again: put back
        sheep.flags1.inactive = True
        r = env.restore_pets()
        assert not r.ok and r.kept == 1
        sheep.flags1.inactive = False
        r = env.restore_pets(True)
        assert r.ok and r.dry_run and n(z.assigned_units) == 0
        r = env.restore_pets()
        assert r.ok and r.restored == 1 and n(z.assigned_units) == 1 and n(sheep.general_refs) == 1
        assert len(L(env.pets_report(sq).book)) == 0

    @test("(r9, A8 #20) a booked pet home while its owner is dead is put back; owner off the map: waited for a "
          "season, then put back (before: kept 'away' for ever)")
    def _():
        lua, env, G = lua_env()
        lua.execute("local env = ...; env.df.global.cur_year, env.df.global.cur_year_tick = 120, 0", env)
        z = G.zone(900, "AI pasture", True)
        owner = G.unit(301)
        sheep = G.unit(501, lua.table_from({"relationship_ids": lua.table_from({"PetOwner": 301})}))
        G.put(sheep, z)
        assert env.release_pets(lua.table_from([501])).ok
        sq = lua.table_from([lua.table_from({"id": 11, "units": lua.table_from([301])})])
        owner.flags1.inactive = True                       # the soldier off on the mission
        assert env.pets_report(sq).book[1].state == "away"
        lua.execute("local env = ...; env.df.global.cur_year_tick = 100800", env)     # a season on
        assert env.pets_report(sq).book[1].state == "ready"
        # the owner dead: at once
        lua.execute("local env = ...; env.df.global.cur_year_tick = 0", env)
        assert env.pets_report(sq).book[1].state == "away"
        owner.dead = True
        assert env.pets_report(sq).book[1].state == "ready"
        assert env.restore_pets().restored == 1

    @test("the bridge: a raid on a civ that isn't hostile only with the policy's reason the Raids switch allows; off "
          "refuses every attack; the fort's own civ never")
    def _():
        import test_bridge_memory as tbm
        tbm.reset()
        M = tbm.H.module()
        tbm.LUA.execute("""local M, H = ...
          H.calls = {}
          H.rules = {missions = 'all', send_missions = true, send_messenger = true, raid_policy = 'ai'}
          H.goals = {all = {'rescue', 'recover_artifact', 'explore', 'raid', 'pillage', 'tribute', 'conquer'}}
          H.settings = {load_settings = function() return H.rules end, MISSION_GOALS = H.goals}
          H.scripts = {['ai-mission-send'] = {start = function(a) table.insert(H.calls, a); return {ok = true, sending = true} end},
                       ['ai-overseer-settings'] = H.settings,
                       ['ai-missions'] = {site_hostile = function(id)
                           return {hostile = id == 42, relation = id == 42 and 'TotalWar' or 'Peace', ours = id == 1 or nil} end}}
          H.df.global.plotinfo.invasions = {list = {}}
          H.df.global.plotinfo.alerts.civ_alert_idx = 0
        """, M, tbm.H)
        T = tbm.t
        sq = T([1])

        def go(site_id, policy=None, rp="ai"):
            tbm.LUA.execute("local H, v = ...; H.rules.raid_policy = v", tbm.H, rp)
            a = {"site_id": site_id, "goal": "raid", "squad_ids": sq}
            if policy:
                a["policy"] = policy
            return M.act_send_mission(T(a))
        assert go(42).ok and not go(50).ok
        assert go(50, "aggressive").ok and go(50, "retaliation").ok and go(50, "threat").ok
        assert not go(50, "aggressive", "reactive").ok and go(50, "retaliation", "reactive").ok
        assert go(50, "aggressive", "aggressive").ok
        r = go(42, None, "off")
        assert not r.ok and "Raids" in r.error, dict(r)
        r = go(1, "aggressive")
        assert not r.ok and "own" in r.error, dict(r)
        assert not go(50, "whatever").ok

    @test("the bridge: mission_pets in the action table (dry run allowed), its label; ai-raids a bridge module")
    def _():
        br = bridge_hub_src()
        assert "mission_pets = function(a)" in br and "'mission_pets'," in br and "'ai-raids'," in br
        from overseer import SHORT_WORDS
        assert "mission_pets" in SHORT_WORDS
        lua = LuaRuntime(unpack_returned_tuples=True)
        chk = lua.eval("function(src, n) local f, e = load(src, n, 't', {}); return f ~= nil, e end")
        for name in ("ai-raids.lua", "ai-missions.lua", "ai-bridge.lua", "ai-bridge-actions.lua", "ai-diplomacy.lua",
                     "ai-overseer-settings.lua", "gui/ai-overseer.lua"):
            ok = chk((ROOT / "lua" / name).read_text(encoding="utf-8"), name)
            assert ok[0], (name, ok)
else:
    @test("the 4 Lua test(s) of the block at line 424: not run")
    def _():
        skip("needs the lupa package (pip install lupa)")      # (0.105.48) counted, not passed


if __name__ == "__main__":
    finish()
