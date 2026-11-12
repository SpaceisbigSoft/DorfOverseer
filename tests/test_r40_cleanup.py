"""(0.105.40, phase 13e) World cleanup: lua/ai-cleanup.lua in a fake fort
(every never-delete case for items and creatures, the year / season ages,
the batches, the dry runs, the dead units' records, the spatter outside the
fort's areas with mud and snow kept, the walks' time budget and the passes'
slices), the bridge's wiring, the Rules switch and its GUI row, and the
brain (brain/planner_cleanup.py: thresholds scaled by slowness and counts,
a trial first per kind, the switch's levels, the journal before a deletion,
the digest line, and plan() without a cleanup section the same as main's).

    python tests/test_r40_cleanup.py
"""

from __future__ import annotations

import atexit
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish, code_has  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, Proposal, plan, record, player_rules  # noqa: E402
import planner_cleanup as PC  # noqa: E402
import digest  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
YEAR, SEASON, DAY = 403200, 100800, 1200

# A fort: the citizens stand in walk group 1; group 2 is a cavern nobody
# reaches, group 0 a wall. W.group(x, y, z) is 1 by default; W.walls[key] = g
# sets one tile's group. Items: W.mk{kind=..., pos=..., flags=...}; units:
# W.unit{...}; map blocks: W.block{x, y, z, events = {...}}.
FAKE = r"""
local src = ...
local W = {items = {}, units = {}, all_units = {}, blocks = {}, buildings = {}, site = {}, tiles = {},
           at_tile = {}, incidents = {}, citizens = {}, removed = {}, jobs = {}, refs = {}, assigned = {},
           tflags = {}, gid = {}}
local env = setmetatable({}, {__index = _G})
local function kind_of(self) return self.kind end
function W.mk(t)
    t.id = t.id or (#W.items + 100)
    t.flags = t.flags or {}
    if t.flags.on_ground == nil and not t.flags.in_inventory then t.flags.on_ground = true end
    t.pos = t.pos or {x = 70, y = 70, z = 100}
    t.getType = kind_of
    t.improvements = t.improvements or {}
    table.insert(W.items, t)
    return t
end
function W.unit(t)
    t.id = t.id or (#W.units + 5000)
    t.flags1 = t.flags1 or {}
    t.flags2 = t.flags2 or {}
    t.flags3 = t.flags3 or {}
    t.pos = t.pos or {x = 80, y = 80, z = 100}
    t.hist_figure_id = t.hist_figure_id or -1
    t.hist_figure_id2 = t.hist_figure_id2 or -1
    t.civ_id = t.civ_id or -1
    t.race = t.race or 7
    t.counters = t.counters or {death_id = -1}
    t.military = t.military or {squad_id = -1}
    t.burrows = t.burrows or {}
    t.animal = t.animal or {vanish_countdown = 0}
    t.mood = t.mood or -1
    table.insert(W.units, t)
    table.insert(W.all_units, t)
    if t.citizen then table.insert(W.citizens, t) end
    return t
end
function W.block(t)
    t.map_pos = {x = t.x, y = t.y, z = t.z}
    t.flags = t.flags or {}
    t.block_events = t.block_events or {}
    table.insert(W.blocks, t)
    return t
end
function W.spatter(mt, ms)
    local ev = {mat_type = mt or 0, mat_state = ms or 1, deleted = false}
    ev.getType = function() return 1 end
    ev.delete = function(self) self.deleted = true end
    return ev
end
W.CLOCK = nil     -- when set: os.clock returns it (and moves by W.CLOCK_STEP each call)
W.CLOCK_STEP = 0
local key = function(x, y, z) return x .. ',' .. y .. ',' .. z end
function W.group(x, y, z) local g = W.tiles[key(x, y, z)]; if g == nil then return 1 end return g end
local real_clock = os.clock
env.os = setmetatable({clock = function()
    if W.CLOCK then W.CLOCK = W.CLOCK + W.CLOCK_STEP; return W.CLOCK end
    return real_clock() end}, {__index = os})
local function find_in(list, id) for _, x in ipairs(list) do if x.id == id then return x end end end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {
    global = {cur_year = 200, cur_year_tick = 0,
              world = {items = {other = {IN_PLAY = W.items}, all = W.items},
                       units = {active = W.units, all = W.all_units},
                       map = {map_blocks = W.blocks},
                       buildings = {all = W.buildings},
                       jobs = {list = {next = nil}},
                       cur_savegame = {save_dir = 'region1'}},
              plotinfo = {site_id = 3, race_id = 1, civ_id = 10, group_id = 11,
                          equipment = {items_assigned = {WEAPON = W.assigned}}}},
    item = {find = function(id) local it = find_in(W.items, id); if it and not it.flags.removed then return it end end},
    unit = {find = function(id) return find_in(W.all_units, id) end},
    incident = {find = function(id) return W.incidents[id] end},
    creature_raw = {find = function(r) return {creature_id = 'RACE' .. r} end},
    item_type = setmetatable({}, {__index = function(_, k) return k end}),
    general_ref_type = {IS_ARTIFACT = 'IS_ARTIFACT', CONTAINS_UNIT = 'CONTAINS_UNIT', CONTAINS_ITEM = 'CONTAINS_ITEM'},
    improvement_type = {WRITING = 'WRITING', PAGES = 'PAGES'},
    building_type = {Stockpile = 'Stockpile'},
    block_square_event_type = {material_spatter = 1},
}
local function flag(name) return function(u) return u[name] == true end end
env.dfhack = {
    units = {isDead = function(u) return u.dead == true end, isActive = function(u) return u.inactive ~= true end,
             isCitizen = flag('citizen'), isResident = flag('resident'), isOwnGroup = flag('own_group'),
             isOwnCiv = function(u) return u.civ_id == 10 end, isPet = flag('pet'), isTame = flag('tame'),
             isDomesticated = flag('domestic'), isVisitor = flag('visitor'), isMerchant = flag('merchant'),
             isDiplomat = flag('diplomat'), isForest = flag('forest'), isPrisoner = flag('prisoner'),
             isDanger = flag('danger'), isInvader = flag('invader'), isWildlife = flag('wildlife'),
             isOwnRace = function(u) return u.race == 1 end,
             getCitizens = function() return W.citizens end,
             getPosition = function(u) return u.pos.x, u.pos.y, u.pos.z end},
    items = {getPosition = function(it) return it.pos.x, it.pos.y, it.pos.z end,
             getOwner = function(it) return it.owner end,
             getHolderUnit = function(it) return it.holder end,
             getGeneralRef = function(it, t) return (it.refs or {})[t] end,
             getContainedItems = function(it) return it.contained or {} end,
             remove = function(it) it.flags.removed = true; table.insert(W.removed, it.id); return true end},
    matinfo = {decode = function(it) if it.mat then return {material = {flags = {[it.mat] = true}}} end end},
    maps = {getWalkableGroup = function(p) return W.group(p.x, p.y, p.z) end,
            getTileFlags = function(x, y, z) return W.tflags[key(x, y, z)] or {} end,
            getTileBlock = function(x, y, z) return {global_feature = W.gid[key(x, y, z)] or 0} end},
    buildings = {findAtTile = function(p) return W.at_tile[key(p.x, p.y, p.z)] end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
assert(load(src, 'ai-cleanup', 't', env))()
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-cleanup.lua"))
    return lua, env, w


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


def py(v):
    """A Lua table as Python (a list when its keys are 1..n)."""
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    try:
        keys = list(v.keys())
    except AttributeError:
        return v
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in sorted(keys)]
    return {k: py(v[k]) for k in keys}


def fort(lua, w):
    """A citizen in group 1 at (80, 80, 100); the fort's buildings round (60..70, 60..70, 100)."""
    w.unit(T(lua, {"citizen": True, "civ_id": 10, "race": 1, "hist_figure_id": 1, "pos": {"x": 60, "y": 60, "z": 100}}))
    w.buildings[1] = T(lua, {"z": 100, "x1": 60, "y1": 60, "x2": 70, "y2": 70})


def cavern(lua, w, x, y, z=50, g=2):
    w.tiles[f"{x},{y},{z}"] = g
    return {"x": x, "y": y, "z": z}


def advance(lua, env, ticks):
    g = lua.globals()
    df = env.df
    t = df["global"].cur_year * YEAR + df["global"].cur_year_tick + ticks
    df["global"].cur_year, df["global"].cur_year_tick = t // YEAR, t % YEAR


def full_pass(env):
    """Report calls until a pass finishes (the clock stubbed out: the budget never runs out)."""
    for _ in range(50):
        r = env.report()
        if not r.walking and not r.partial:
            return r
    raise AssertionError("no pass finished in 50 calls")


def lost_items(lua, w, n, start=1000, **kw):
    out = []
    for i in range(n):
        p = cavern(lua, w, 10 + i, 10)
        out.append(w.mk(T(lua, {"id": start + i, "kind": kw.get("kind", "BOULDER"), "pos": p, "flags": kw.get("flags", {})})))
    return out


class SP:    # the fake's spatter maker, from Python
    @staticmethod
    def spatter(lua, mt=0, ms=1):
        return lua.eval(f"""(function() local ev = {{mat_type = {mt}, mat_state = {ms}, deleted = false}}
            ev.getType = function() return 1 end
            ev.delete = function(self) self.deleted = true end
            return ev end)()""")


# --- 1. the items: counted, followed, never-delete cases ---------------------------------

@test("items: counted by state; one in a cavern no citizen reaches is followed from the first pass, a reachable one not")
def _():
    lua, env, w = world()
    fort(lua, w)
    w.mk(T(lua, {"kind": "BAR", "flags": {"forbid": True}}))
    w.mk(T(lua, {"kind": "CORPSE", "race": 9, "flags": {}}))                    # reachable refuse
    w.mk(T(lua, {"kind": "BIN", "flags": {"on_ground": False, "in_building": True}}))
    w.mk(T(lua, {"kind": "BAR", "flags": {"on_ground": False, "in_inventory": True}}))
    lost_items(lua, w, 2)
    r = full_pass(env)
    c = py(r["items"])
    assert c["total"] == 6 and c["in_buildings"] == 1 and c["in_containers"] == 1 and c["on_ground"] == 4, c
    assert c["unreachable"] == 2 and c["refuse_loose"] == 1 and c["forbidden"] == 1 and c["tracked"] == 2, c
    assert c["unreachable_old"] == 0 and c["unreachable_season"] == 0, c
    # a year on, both are old enough
    advance(lua, env, YEAR + DAY)
    c = py(full_pass(env)["items"])
    assert c["unreachable_old"] == 2 and c["oldest_days"] >= 336, c


@test("items: a tile in no walk group next to a reachable one counts as reachable; an item reached again is no longer followed")
def _():
    lua, env, w = world()
    fort(lua, w)
    w.tiles["90,90,100"] = 0            # a wall-side tile; its neighbours are group 1
    w.mk(T(lua, {"id": 1, "kind": "BOULDER", "pos": {"x": 90, "y": 90, "z": 100}}))
    lost_items(lua, w, 1, start=2)
    assert py(full_pass(env)["items"])["unreachable"] == 1
    w.tiles["10,10,50"] = 1             # the cavern opened
    advance(lua, env, DAY + 1)
    c = py(full_pass(env)["items"])
    assert c["unreachable"] == 0 and c["tracked"] == 0, c


NEVER = [
    ("artifact", {"flags": {"artifact": True}}),
    ("artifact", {"refs": {"IS_ARTIFACT": True}}),
    ("named", {"improvements": [{"getType": "WRITING"}]}),
    ("owned", {"flags": {"owned": True}}),
    ("owned", {"owner": {"id": 1}}),
    ("held", {"flags": {"on_ground": False, "in_inventory": True}}),
    ("built", {"flags": {"in_building": True}}),
    ("built", {"flags": {"construction": True}}),
    ("container", {"flags": {"container": True}}),
    ("job", {"flags": {"in_job": True}}),
    ("trader", {"flags": {"trader": True}}),
    ("evidence", {"flags": {"murder": True}}),
    ("web", {"flags": {"spider_web": True}}),
    ("own_dead", {"flags": {"dead_dwarf": True}}),
    ("own_dead", {"kind": "CORPSE", "race": 1}),
    ("player", {"flags": {"forbid": True}}),
    ("stockpile", {"at": "Stockpile"}),
    ("building", {"at": "Workshop"}),
    ("squad", {"assigned": True}),
]


@test("items: never deleted, each case alone (artifact, named, owned, held, built, a container, a job's, a trader's, "
      "evidence, a web, the fort's dead, the player's forbidden, a stockpile's, a building's tile, the squads' gear)")
def _():
    for why, extra in NEVER:
        lua, env, w = world()
        fort(lua, w)
        p = cavern(lua, w, 20, 20)
        it = {"id": 77, "kind": extra.get("kind", "BOULDER"), "pos": p, "flags": dict(extra.get("flags", {}))}
        if "race" in extra:
            it["race"] = extra["race"]
        if "owner" in extra:
            it["owner"] = extra["owner"]
        if "refs" in extra:
            it["refs"] = extra["refs"]
        item = w.mk(T(lua, it))
        if "improvements" in extra:
            item.improvements = lua.eval("{ {getType = function() return 'WRITING' end} }")
        if "at" in extra:
            w.at_tile["20,20,50"] = lua.eval(f"{{getType = function() return '{extra['at']}' end}}")
        if extra.get("assigned"):
            w.assigned[1] = 77
        first = py(full_pass(env)["items"])
        advance(lua, env, YEAR + DAY)
        c = py(full_pass(env)["items"])
        assert c["unreachable_old"] == 0, (why, c)
        if first["on_ground"] or c["on_ground"]:
            assert (c["kept"] or {}).get(why), (why, c)
        r = env.cleanup_items(T(lua, {"max": 10}), False)
        assert not r.ok and r.removed == 0 and len(list(w.removed.values())) == 0, (why, py(r))


@test("items: a strange mood's kind stays while the mood waits; a request of any kind keeps every kind")
def _():
    lua, env, w = world()
    fort(lua, w)
    p = cavern(lua, w, 20, 20)
    w.mk(T(lua, {"id": 77, "kind": "BOULDER", "pos": p}))
    w.mk(T(lua, {"id": 78, "kind": "BAR", "pos": cavern(lua, w, 21, 20)}))
    moody = w.citizens[1]
    moody.mood = 2
    moody.job = lua.eval("{current_job = {job_items = { {item_type = 'BAR'} }}}")
    full_pass(env)
    advance(lua, env, YEAR + DAY)
    c = py(full_pass(env)["items"])
    assert c["unreachable_old"] == 1 and c["kept"].get("mood") == 1, c
    moody.job = lua.eval("{current_job = {job_items = { {item_type = -1} }}}")
    r = env.cleanup_items(T(lua, {"level": "full"}), True)
    assert not r.ok and py(r)["kept"] == {"mood": 1} and len(list(w.removed.values())) == 0, py(r)   # (the bar untracked at once)


@test("items: a job's listed item stays (job.items), though its flag isn't set")
def _():
    lua, env, w = world()
    fort(lua, w)
    it = w.mk(T(lua, {"id": 77, "kind": "BOULDER", "pos": cavern(lua, w, 20, 20)}))
    env.df["global"].world.jobs.list = lua.eval("function(it) return {next = {item = {items = { {item = it} }}, next = nil}} end")(it)
    full_pass(env)
    advance(lua, env, YEAR + DAY)
    c = py(full_pass(env)["items"])
    assert c["unreachable_old"] == 0 and c["kept"].get("job") == 1, c


@test("cleanup_items: only after a year unreachable, oldest first, max a call; a dry run counts and removes nothing (boulders: level full)")
def _():
    lua, env, w = world()
    fort(lua, w)
    lost_items(lua, w, 3, start=1000)
    full_pass(env)
    advance(lua, env, SEASON)
    lost_items(lua, w, 2, start=2000)       # found a season later: younger
    full_pass(env)
    r = env.cleanup_items(T(lua, {"max": 2, "level": "full"}), False)
    assert not r.ok and r.rejected and r.removed == 0, py(r)       # none a year yet
    advance(lua, env, YEAR - SEASON + DAY)
    full_pass(env)
    d = env.cleanup_items(T(lua, {"max": 2, "level": "full"}), True)
    assert d.ok and d.dry_run and d.would_remove == 2 and d.candidates == 3 and len(list(w.removed.values())) == 0, py(d)
    r = env.cleanup_items(T(lua, {"max": 2, "level": "full"}), False)
    assert r.ok and r.removed == 2 and r.more and r.left == 1, py(r)
    assert sorted(w.removed.values()) == [1000, 1001], py(w.removed)
    r = env.cleanup_items(T(lua, {"max": 2, "level": "full"}), False)
    assert r.ok and r.removed == 1 and not r.more and list(w.removed.values())[-1] == 1002, py(r)
    # the report follows at once (the last pass's counts)
    assert py(env.report()["items"])["unreachable_old"] == 0
    # min_age: never under a season
    r = env.cleanup_items(T(lua, {"min_age": 10, "level": "full"}), True)
    assert r.ok and r.candidates == 2, py(r)         # the younger two: a season and more by now


@test("cleanup_items: re-checks at the time: an item reached again (or now kept) is not deleted")
def _():
    lua, env, w = world()
    fort(lua, w)
    items = lost_items(lua, w, 2)
    full_pass(env)
    advance(lua, env, YEAR + DAY)
    full_pass(env)
    w.tiles["10,10,50"] = 1                   # reached
    items[1].flags.forbid = True              # the player's now
    r = env.cleanup_items(T(lua, {"level": "full"}), False)
    assert not r.ok and r.removed == 0 and py(r)["kept"] == {"reachable": 1, "player": 1}, py(r)


@test("cleanup_items: no citizen in a readable walk group: refused, nothing known to be unreachable; a blind pass "
      "forgets nothing it follows")
def _():
    lua, env, w = world()
    fort(lua, w)
    lost_items(lua, w, 2)
    full_pass(env)
    w.tiles["60,60,100"] = 0                  # the citizen in no group
    r = env.cleanup_items(T(lua, {}), True)
    assert not r.ok and r.rejected and "walk group" in r.error, py(r)
    advance(lua, env, YEAR + DAY)
    c = py(full_pass(env)["items"])
    assert c["tracked"] == 2 and c["unknown_reach"] == 2, c
    w.tiles["60,60,100"] = 1
    advance(lua, env, DAY + 1)
    assert py(full_pass(env)["items"])["unreachable_old"] == 2


@test("followed items survive a reload (site data), and another fort starts afresh")
def _():
    lua, env, w = world()
    fort(lua, w)
    lost_items(lua, w, 2)
    full_pass(env)
    env.reset()
    advance(lua, env, YEAR + DAY)
    assert py(full_pass(env)["items"])["unreachable_old"] == 2
    env.reset()
    env.df["global"].plotinfo.site_id = 99
    w.site = lua.table()
    advance(lua, env, DAY + 1)
    assert py(full_pass(env)["items"])["unreachable_old"] == 0


# --- 2. the creatures -----------------------------------------------------------------

UNIT_NEVER = [
    ("citizen", {"citizen": True, "danger": True}),
    ("citizen", {"resident": True, "danger": True}),
    ("fort", {"civ_id": 10, "wildlife": True}),
    ("tame", {"pet": True, "wildlife": True}),
    ("tame", {"tame": True, "wildlife": True}),
    ("tame", {"domestic": True, "wildlife": True}),
    ("visitor", {"visitor": True, "danger": True}),
    ("visitor", {"merchant": True}),
    ("visitor", {"diplomat": True}),
    ("prisoner", {"danger": True, "flags1": {"caged": True}}),
    ("prisoner", {"danger": True, "flags1": {"chained": True}}),
    ("prisoner", {"danger": True, "prisoner": True}),
    ("historical", {"danger": True, "hist_figure_id": 55}),
    ("historical", {"wildlife": True, "hist_figure_id2": 56}),
    ("riding", {"danger": True, "flags1": {"rider": True}}),
    ("dead", {"danger": True, "dead": True}),
    ("other", {}),
]


@test("creatures: never removed, each case alone (citizens, residents, the fort's, pets, tame, domestic, visitors, "
      "merchants, diplomats, prisoners, historical figures, riders, the dead, neither hostile nor wild)")
def _():
    for why, extra in UNIT_NEVER:
        lua, env, w = world()
        fort(lua, w)
        u = {"pos": cavern(lua, w, 30, 30), **{k: v for k, v in extra.items()}}
        w.unit(T(lua, u))
        full_pass(env)
        advance(lua, env, SEASON + DAY)
        c = py(full_pass(env)["units"])
        assert c["unreachable_old"] == 0, (why, c)
        r = env.cleanup_units(T(lua, {}), False)
        assert not r.ok and r.removed == 0, (why, py(r))
        assert all(x.animal.vanish_countdown == 0 for x in w.units.values()), why


@test("cleanup_units: a hostile or wild non-historical creature out of reach a season is vaporized (exterminate's "
      "way), the kinds asked only; a dry run lists them and changes nothing")
def _():
    lua, env, w = world()
    fort(lua, w)
    gob = w.unit(T(lua, {"id": 7001, "danger": True, "race": 4, "pos": cavern(lua, w, 30, 30)}))
    bat = w.unit(T(lua, {"id": 7002, "wildlife": True, "race": 5, "pos": cavern(lua, w, 31, 30)}))
    near = w.unit(T(lua, {"id": 7003, "danger": True, "pos": {"x": 85, "y": 85, "z": 100}}))   # reachable
    c = py(full_pass(env)["units"])
    assert c["unreachable"] == {"hostile": 1, "wild": 1} and c["unreachable_old"] == 0, c
    r = env.cleanup_units(T(lua, {}), True)
    assert not r.ok and r.rejected, py(r)                     # not a season yet
    advance(lua, env, SEASON + DAY)
    c = py(full_pass(env)["units"])
    assert c["unreachable_old"] == 2 and {x["kind"] for x in c["list"]} == {"hostile", "wild"}, c
    d = env.cleanup_units(T(lua, {}), True)
    assert d.ok and d.would_remove == 2 and gob.animal.vanish_countdown == 0, py(d)
    r = env.cleanup_units(T(lua, {"kinds": ["wild"]}), False)
    assert r.ok and r.removed == 1 and bat.animal.vanish_countdown == 1 and gob.animal.vanish_countdown == 0, py(r)
    r = env.cleanup_units(T(lua, {"max": 5}), False)
    assert r.ok and r.removed == 1 and gob.animal.vanish_countdown == 1 and near.animal.vanish_countdown == 0, py(r)


# --- 3. dead units and spatter ----------------------------------------------------------

@test("cleanup_dead_units: only the long dead nobody refers to leave the active list (never the fort's own or its "
      "race, a named merchant or diplomat, a ghost, a squad's or a burrow's, nor one whose death can't be read); "
      "units.all keeps every one")
def _():
    lua, env, w = world()
    fort(lua, w)
    now = 200 * YEAR
    w.incidents[1] = T(lua, {"event_year": 198, "event_time": 0})       # two years ago
    w.incidents[2] = T(lua, {"event_year": 200, "event_time": 0})       # just now
    mk = lambda **kw: w.unit(T(lua, {"dead": True, "counters": {"death_id": kw.pop("death", 1)}, **kw}))
    go = mk(id=8001, civ_id=33, race=4)                       # a goblin, long dead
    mk(id=8002, civ_id=33, race=4, death=2)                   # recent
    mk(id=8003, civ_id=10, race=1, hist_figure_id=3)          # the fort's own dwarf
    mk(id=8004, civ_id=10, race=6, hist_figure_id=4)          # the fort's named pet (a historical figure)
    mk(id=8005, civ_id=33, race=4, flags3={"ghostly": True})
    mk(id=8006, civ_id=33, race=4, military={"squad_id": 2})
    mk(id=8007, civ_id=33, race=4, burrows=[3])
    mk(id=8008, civ_id=33, race=4, death=-1)                  # when: unknown
    mk(id=8009, civ_id=44, race=1)                            # a foreign dwarf: the fort's race, kept (fix/dead-units)
    mk(id=8010, civ_id=33, race=4, hist_figure_id=9, merchant=True)   # a named merchant: kept
    n_all = len(list(w.all_units.values()))
    c = py(full_pass(env)["units"])
    assert c["dead_active"] == 10 and c["dead_removable"] == 1 and c["dead_all"] == 10 and c["all"] == n_all, c
    d = env.cleanup_dead_units(T(lua, {}), True)
    assert d.ok and d.would_remove == 1 and len(list(w.units.values())) == n_all, py(d)
    kept = py(d)["kept"]
    assert kept == {"recent": 1, "own": 3, "ghost": 1, "referenced": 2, "when": 1, "visitor": 1}, kept
    r = env.cleanup_dead_units(T(lua, {}), False)
    assert r.ok and r.removed == 1, py(r)
    ids = {u.id for u in w.units.values()}
    assert 8001 not in ids and 8009 in ids and 8010 in ids and len(ids) == n_all - 1, ids
    assert len(list(w.all_units.values())) == n_all       # the units themselves stay (nothing dangles)
    r = env.cleanup_dead_units(T(lua, {}), False)
    assert not r.ok and r.rejected, py(r)


@test("spatter: counted (outside the fort's areas apart, mud and snow not), cleaned outside first, 'all' inside too; "
      "a dry run removes nothing")
def _():
    lua, env, w = world()
    fort(lua, w)
    inside = w.block(T(lua, {"x": 64, "y": 64, "z": 100}))
    far = w.block(T(lua, {"x": 0, "y": 0, "z": 100}))
    deep = w.block(T(lua, {"x": 64, "y": 64, "z": 40, "flags": {"update_liquid": True}}))
    for b, evs in ((inside, [SP.spatter(lua) for _ in range(2)]),
                   (far, [SP.spatter(lua), SP.spatter(lua, 12, 0), SP.spatter(lua, 6, 3)]),
                   (deep, [SP.spatter(lua)])):
        b.block_events = lua.table_from(evs)
    r = full_pass(env)
    s = py(r["spatter"])
    assert s["events"] == 4 and s["outside"] == 2 and s["blocks"] == 3, s
    assert py(r["fluids"])["blocks"] == 1
    d = env.cleanup_spatter(T(lua, {}), True)
    assert d.ok and d.would_remove == 2 and d.removed == 0 and len(list(far.block_events.values())) == 3, py(d)
    c = env.cleanup_spatter(T(lua, {}), False)
    assert c.ok and c.removed == 2 and c.kept_mud_snow == 2 and len(list(inside.block_events.values())) == 2, py(c)
    left = list(far.block_events.values())
    assert len(left) == 2 and {(e.mat_type, e.mat_state) for e in left} == {(12, 0), (6, 3)}
    assert py(env.report()["spatter"])["outside"] == 0
    c = env.cleanup_spatter(T(lua, {"scope": "all"}), False)
    assert c.ok and c.removed == 2 and len(list(inside.block_events.values())) == 0, py(c)


# --- 4. budgets ---------------------------------------------------------------------

@test("budget: a report's walk stops at BUDGET_MS and goes on where it stopped; a full pass is a day apart at most")
def _():
    lua, env, w = world()
    fort(lua, w)
    lost_items(lua, w, 3)
    for i in range(3000):
        w.mk(T(lua, {"kind": "BOULDER"}))
    w.CLOCK, w.CLOCK_STEP = 0.0, 0.015        # every clock read 15 ms on
    r = env.report()
    assert r.partial and r.walking and r.ms <= env.BUDGET_MS + 50, (r.partial, r.walking, r.ms)
    calls = 1
    while env.report().walking:
        calls += 1
        assert calls < 200
    assert calls >= 2
    w.CLOCK = None
    r = env.report()
    assert not r.partial and not r.walking and py(r["items"])["unreachable"] == 3 and r.passes == 1
    env.report()
    assert env.report().passes == 1                          # the same day: the last pass sent
    advance(lua, env, DAY)
    full_pass(env)
    assert env.report().passes == 2


@test("budget: cleanup_spatter walks the blocks within budget_ms and the next call goes on from there")
def _():
    lua, env, w = world()
    fort(lua, w)
    for i in range(10):
        b = w.block(T(lua, {"x": 200 + 16 * i, "y": 0, "z": 10}))
        b.block_events = lua.table_from([SP.spatter(lua)])
    w.CLOCK, w.CLOCK_STEP = 0.0, 0.001
    r = env.cleanup_spatter(T(lua, {"budget_ms": 10}), False)
    assert r.ok and r.more and 0 < r.removed < 10, py(r)
    total = r.removed
    for _ in range(10):
        r = env.cleanup_spatter(T(lua, {"budget_ms": 10}), False)
        total += r.removed
        if not r.more:
            break
    assert total == 10, total


@test("budget: cleanup_items' look over the followed items stops at ACTION_BUDGET_MS (cut_short)")
def _():
    lua, env, w = world()
    fort(lua, w)
    lost_items(lua, w, 30)
    full_pass(env)
    advance(lua, env, YEAR + DAY)
    full_pass(env)
    w.CLOCK, w.CLOCK_STEP = 0.0, 0.05
    r = env.cleanup_items(T(lua, {"max": 500, "level": "full"}), True)
    assert r.cut_short and r.candidates < 30, py(r)


# --- 5. the bridge, the settings, the window ----------------------------------------------

BRIDGE = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
ACTS = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
SETTINGS = (LUA_DIR / "ai-overseer-settings.lua").read_text(encoding="utf-8")
GUI = (LUA_DIR / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
ACTIONS = ("cleanup_items", "cleanup_units", "cleanup_spatter", "cleanup_dead_units")


@test("bridge: the four actions in ACTIONS and DRY_OK, the cleanup section, ai-cleanup in BRIDGE_MODULES, not a cached section")
def _():
    dry = BRIDGE[BRIDGE.index("DRY_OK = {}"):BRIDGE.index("}) do DRY_OK[name] = true end")]
    for a in ACTIONS:
        assert code_has(BRIDGE, f"{a} = act_{a},"), a
        assert f"'{a}'" in dry, a
        assert f"function act_{a}(a)" in ACTS and "dry_run" in ACTS[ACTS.index(f"function act_{a}(a)"):][:1500], a
    assert code_has(BRIDGE, "cleanup = function() return safe(function() return reqscript('ai-cleanup').report() end) end,")
    mods = BRIDGE[BRIDGE.index("BRIDGE_MODULES = {"):BRIDGE.index("}", BRIDGE.index("BRIDGE_MODULES = {"))]
    assert "'ai-cleanup'" in mods
    cache = BRIDGE[BRIDGE.index("SECTION_CACHE_DAYS = {"):BRIDGE.index("SECTION_REBUILDS =")]
    assert "cleanup" not in cache


@test("bridge: the handlers check their numbers and pass dry_run on")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    f = lua.eval("""function(src)
        local seen = {}
        local env = setmetatable({BRIDGE_VERSION = 'x', OUT_DIR = '/tmp'}, {__index = _G})
        env.require = function(n) return {} end
        env.reject = function(m) return {ok = false, rejected = true, error = m} end
        env.int_in = function(v, lo, hi) local n = math.tointeger(tonumber(v)); if n == nil or n < lo or n > hi then return nil end return n end
        env.reqscript = function(n)
            if n == 'ai-overseer-settings' then return {load_settings = function() return {world_cleanup = 'full'} end} end
            assert(n == 'ai-cleanup')
            local m = {}
            for _, k in ipairs({'cleanup_items', 'cleanup_units', 'cleanup_spatter', 'cleanup_dead_units'}) do
                m[k] = function(o, dry) seen[#seen + 1] = {k, o, dry}; return {ok = true, dry_run = dry} end
            end
            return m
        end
        assert(load(src, 'actions', 't', env))()
        return env, seen
    end""")
    env, seen = f(ACTS)
    assert env.act_cleanup_items(T(lua, {"max": 9999})).rejected
    assert env.act_cleanup_items(T(lua, {"min_age": 5})).rejected
    assert env.act_cleanup_units(T(lua, {"kinds": ["citizen"]})).rejected
    assert env.act_cleanup_spatter(T(lua, {"scope": "inside"})).rejected
    assert env.act_cleanup_dead_units(T(lua, {"min_age": 1})).rejected
    r = env.act_cleanup_items(T(lua, {"max": 50, "dry_run": True}))
    assert r.ok and r.dry_run is True and seen[len(seen)][2].max == 50
    r = env.act_cleanup_units(T(lua, {"kinds": ["hostile"]}))
    assert r.ok and r.dry_run is False and seen[len(seen)][2].kinds[1] == "hostile"
    assert env.act_cleanup_spatter(T(lua, {"scope": "all", "budget_ms": 100})).ok
    assert env.act_cleanup_dead_units(T(lua, {})).ok


@test("settings: world_cleanup off | safe | full, default safe; sanitize, for_ai, RULE_CHOICES (set_rules)")
def _():
    assert "WORLD_CLEANUP_CHOICES = {'off', 'safe', 'full'}" in SETTINGS
    assert code_has(SETTINGS, "world_cleanup = WORLD_CLEANUP_CHOICES}")
    assert code_has(SETTINGS, "world_cleanup = 'safe',")
    assert code_has(SETTINGS, "out.world_cleanup = one_of(s.world_cleanup, WORLD_CLEANUP_CHOICES, d.world_cleanup)")
    assert code_has(SETTINGS, "world_cleanup = s.world_cleanup,")
    assert player_rules({"settings": {}})["world_cleanup"] == "safe"
    assert player_rules({"settings": {"world_cleanup": "full"}})["world_cleanup"] == "full"
    assert player_rules({"settings": {"world_cleanup": "nuke"}})["world_cleanup"] == "safe"
    from strategist import rules_line
    assert "world_cleanup" not in rules_line(player_rules({"settings": {}}))
    assert "world_cleanup=off" in rules_line(player_rules({"settings": {"world_cleanup": "off"}}))


def _rules_rows():
    """(row, l, w, view) of every Rules-page control with a frame, at the window's numbers
    (9 optional levels: t = 14; the hospital 2nd, the jail 8th)."""
    src = GUI[GUI.index("function RulesPage:init()"):GUI.index("MilitaryPage = defclass")]
    jrow, hrow, t = 8, 2, 14
    out = []
    for m in re.finditer(r"view_id = '(\w+)',\s*frame = \{t = ([^,]+), l = (\d+), w = (\d+)\}", src):
        view, expr, l, wd = m.group(1), m.group(2).strip(), int(m.group(3)), int(m.group(4))
        for i in ((1, 2, 3) if " + i" in expr else (None,)):
            env = {"jrow": jrow, "hrow": hrow, "t": t, "i": i if i is not None else 0}
            out.append((eval(expr, env), l, wd, view))
    return out


@test("window: the World cleanup row on the Rules tab, in a free row of the right-hand column, refreshed; its widest "
      "choice fits")
def _():
    assert code_has(GUI, "view_id = 'world_cleanup',") and code_has(GUI, "p:set_field('world_cleanup', v)")
    assert "self.subviews.world_cleanup:setOption(" in GUI
    rows = _rules_rows()
    mine = [r for r in rows if r[3] == "world_cleanup"]
    assert len(mine) == 1, rows
    r, l, wd, _ = mine[0]
    for r2, l2, w2, v in rows:
        if v != "world_cleanup" and r2 == r:
            assert l2 + w2 <= l or l + wd <= l2, (v, r2, l2, w2, mine)
    # the help labels in the right-hand column (calm burrow's at row 5 + jrow)
    assert r != 5 + 8 and r != 5 + 2
    assert l + wd <= 118
    m = re.search(r"view_id = 'world_cleanup',.*?label = '([^']*)',\s*label_width = (\d+)", GUI, re.S)
    names = re.search(r"WORLD_CLEANUP_NAMES = \{(.*?)\}", SETTINGS, re.S).group(1)
    widest = max(len(x) for x in re.findall(r"'([^']*)'", names))
    assert len(m.group(1)) <= int(m.group(2)) and int(m.group(2)) + widest <= wd, (m.groups(), widest, wd)


@test("Lua: ai-cleanup compiles (Lua 5.3) and is a module")
def _():
    src = (LUA_DIR / "ai-cleanup.lua").read_text(encoding="utf-8")
    lua = LuaRuntime(unpack_returned_tuples=True)
    assert lua.eval("function(s) local f, e = load(s, 'c', 't', {}); return e end")(src) is None
    assert "--@ module = true" in src


# --- 6. the brain ---------------------------------------------------------------------

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG


def section(**kw) -> dict:
    c = {"tick": 1, "passes": 3,
         "items": {"total": 30000, "on_ground": 9000, "unreachable": 0, "unreachable_old": 0, "refuse_loose": 0},
         "units": {"active": 900, "all": 3000, "dead_active": 0, "dead_removable": 0,
                   "unreachable": {"hostile": 0, "wild": 0}, "unreachable_old": 0, "list": []},
         "spatter": {"events": 0, "outside": 0, "blocks": 0}, "fluids": {"blocks": 0}}
    for k, v in kw.items():
        part, key = k.split("__")
        c[part][key] = v
    return c


def fort_state(c=None, slow=False, **rules) -> dict:
    s = copy.deepcopy(BASE)
    if c is not None:
        s["cleanup"] = c
    s["settings"].update(rules)
    if slow:
        s["fps_low"] = 9
    return s


def mine(s, memory=None):
    props, notes = [], []
    PC._world_cleanup_rule(s, CFG, props, notes, memory, player_rules(s))
    return props, notes


@test("brain: nothing without a cleanup section, a failed one, or before the first full pass")
def _():
    for c in (None, {}, {"error": "boom"}, {**section(items__unreachable_old=10 ** 6), "partial": True}):
        assert mine(fort_state(c)) == ([], []), c
    assert mine(fort_state(section())) == ([], [])


@test("brain: thresholds: each kind only past its count; lower while slow (cleanup_slow_factor); the items' grows "
      "with the items on the map")
def _():
    th = PC.cleanup_thresholds(fort_state(), CFG, section())
    assert th["items"] == max(CFG["cleanup_items_min"], int(CFG["cleanup_items_share"] * 30000))
    th_slow = PC.cleanup_thresholds(fort_state(slow=True), CFG, section())
    for k in th:
        assert th_slow[k] < th[k], k
    big = PC.cleanup_thresholds(fort_state(), CFG, section(items__total=1_000_000))
    assert big["items"] == int(CFG["cleanup_items_share"] * 1_000_000) > th["items"]
    m = Memory()
    m.cleanup_seen = {"dry": {f"{k}@{lv}": 1 for k in ("spatter", "dead", "items", "units") for lv in ("safe", "full")}}
    just_under = section(items__unreachable_old=th["items"] - 1, spatter__outside=th["spatter"] - 1,
                         units__dead_removable=th["dead"] - 1)
    assert mine(fort_state(just_under), m)[0] == []
    props, _ = mine(fort_state(just_under, slow=True), m)
    assert sorted(p.rule for p in props) == ["cleanup_dead", "cleanup_items", "cleanup_spatter"], props
    at = section(items__unreachable_old=th["items"], spatter__outside=th["spatter"], units__dead_removable=th["dead"])
    props, _ = mine(fort_state(at), m)
    assert sorted(p.action["type"] for p in props) == ["cleanup_dead_units", "cleanup_items", "cleanup_spatter"]
    it = [p for p in props if p.action["type"] == "cleanup_items"][0]
    assert it.action == {"type": "cleanup_items", "max": CFG["cleanup_items_batch"], "min_age": 403200,
                         "level": "safe"}, it.action
    sp = [p for p in props if p.action["type"] == "cleanup_spatter"][0]
    assert sp.action["scope"] == "outside"


@test("brain: spatter inside the fort only while slow and past the whole map's threshold, after the outside")
def _():
    m = Memory()
    m.cleanup_seen = {"dry": {"spatter@safe": 1}}
    c = section(spatter__events=10 ** 6, spatter__outside=0)
    assert mine(fort_state(c), m)[0] == []
    props, _ = mine(fort_state(c, slow=True), m)
    assert len(props) == 1 and props[0].action["scope"] == "all", props


@test("brain: a trial (dry run) first per kind; after its ok the real call; a refused trial is tried again")
def _():
    m = Memory()
    s = fort_state(section(items__unreachable_old=10 ** 5))
    props, _ = mine(s, m)
    assert [(p.rule, p.action.get("dry_run")) for p in props] == [("cleanup_items_dry", True)], props
    record([(props[0], {"ok": False, "rejected": True, "error": "x"})], s, m)
    assert [p.rule for p in mine(s, m)[0]] == ["cleanup_items_dry"]
    record([(props[0], {"ok": True, "dry_run": True, "would_remove": 500})], s, m)
    props2, _ = mine(s, m)
    assert [(p.rule, p.action.get("dry_run")) for p in props2] == [("cleanup_items", None)], props2
    record([(props2[0], {"ok": True, "removed": 500, "more": True})], s, m)
    assert m.cleanup_seen["removed"]["items"] == 500
    j = PC.cleanup_journal(m)
    assert [(e["ok"], e["text"]) for e in j] == [(False, "trial: 0 unreachable items would go"),
                                               (True, "trial: 500 unreachable items would go"),
                                               (True, "removed 500 unreachable items (more left)")], j
    assert PC.cleanup_journal(m) == []
    # each kind its own trial
    s2 = fort_state(section(items__unreachable_old=10 ** 5, spatter__outside=10 ** 6))
    assert sorted(p.rule for p in mine(s2, m)[0]) == ["cleanup_items", "cleanup_spatter_dry"]


@test("brain: the Rules switch: off proposes nothing; safe no creatures (a note says what full would do); full all four")
def _():
    m = Memory()
    m.cleanup_seen = {"dry": {f"{k}@{lv}": 1 for k in ("spatter", "dead", "items", "units") for lv in ("safe", "full")}}
    c = section(items__unreachable_old=10 ** 5, spatter__outside=10 ** 6, units__dead_removable=10 ** 4,
                units__unreachable_old=500)
    assert mine(fort_state(c, world_cleanup="off"), m) == ([], [])
    props, notes = mine(fort_state(c), m)
    assert sorted(p.action["type"] for p in props) == ["cleanup_dead_units", "cleanup_items", "cleanup_spatter"]
    assert any("'full' would remove them" in n for n in notes), notes
    props, notes = mine(fort_state(c, world_cleanup="full"), m)
    assert sorted(p.action["type"] for p in props) == ["cleanup_dead_units", "cleanup_items", "cleanup_spatter",
                                                      "cleanup_units"]
    u = [p for p in props if p.action["type"] == "cleanup_units"][0]
    assert u.action == {"type": "cleanup_units", "max": CFG["cleanup_units_batch"], "min_age": 100800}
    assert not notes


@test("brain: plan() carries the rule (registered), its cooldowns are in the config, the labels and the camera quiet")
def _():
    m = Memory()
    s = digest.normalize(fort_state(section(items__unreachable_old=10 ** 5)))
    props, _ = plan(copy.deepcopy(s), m)
    assert any(p.rule == "cleanup_items_dry" for p in props), [p.rule for p in props]
    for k in ("spatter", "dead", "items", "units"):
        assert f"cleanup_{k}_cooldown_ticks" in CFG and f"cleanup_{k}_dry_cooldown_ticks" in CFG
    assert all(k.startswith("cleanup_") for k in CFG if "cleanup" in k and k not in ("siege_cleanup_cooldown_ticks",))
    import overseer
    for a in ACTIONS:
        assert a in overseer.SHORT_WORDS and a in overseer.CAMERA_QUIET, a
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    i = src.index('if acting and p.action["type"] in CLEANUP_ACTIONS and not p.action.get("dry_run"):')
    assert src.index("r = bridge.act(p.action)", i) - i < 600       # the journal line comes first
    assert '"kind": "cleanup"' in src[i:i + 400]


@test("digest: the CLEANUP line with the counts and the switch; none without a section")
def _():
    line = digest.digest(fort_state(section(items__unreachable=20, items__unreachable_old=7, spatter__events=99,
                                            spatter__outside=40, units__dead_removable=3)))
    got = [x for x in line.splitlines() if x.startswith("CLEANUP")]
    assert len(got) == 1 and "(safe)" in got[0] and "unreachable 20 (a year: 7)" in got[0] and "spatter 99 (outside 40)" in got[0], got
    assert not [x for x in digest.digest(fort_state()).splitlines() if x.startswith("CLEANUP")]
    assert "cleanup" not in digest.normalize(fort_state())["_errors"]
    assert "cleanup" in digest.normalize(fort_state({"error": "x"}))["_errors"]


# --- 4b. (0.105.40 review) the verifier's findings ------------------------------------------

def year_on(lua, env):
    full_pass(env)
    advance(lua, env, YEAR + DAY)
    return full_pass(env)


@test("review 1: an item on a tile no one has seen is not followed (not counted toward the thresholds), nor deleted "
      "at any level; a creature there stays")
def _():
    lua, env, w = world()
    fort(lua, w)
    p = cavern(lua, w, 20, 20)
    w.tflags["20,20,50"] = T(lua, {"hidden": True})
    w.mk(T(lua, {"id": 77, "kind": "REMAINS", "race": 9, "pos": p}))
    w.mk(T(lua, {"id": 900, "kind": "REMAINS", "race": 9, "pos": cavern(lua, w, 10, 10)}))   # a seen one, for contrast
    w.unit(T(lua, {"id": 7001, "danger": True, "pos": p}))
    c = py(year_on(lua, env)["items"])
    assert c["hidden_tile"] == 1 and c["unreachable"] == 1 and c["unreachable_old"] == 1 and c["tracked"] == 1, c
    r = env.cleanup_items(T(lua, {"level": "full"}), True)
    assert r.ok and r.would_remove == 1, py(r)
    # reached by the follow list some other way (an old save's list): item_keep says hidden at the time
    env.state()["items"][77] = 0
    r = env.cleanup_items(T(lua, {"level": "full"}), True)
    assert r.would_remove == 1 and py(r)["kept"].get("hidden") == 1, py(r)
    assert env.unit_keep(w.units[2]) == "hidden"
    advance(lua, env, SEASON)
    u = py(full_pass(env)["units"])
    assert u["unreachable_old"] == 0, u
    assert not env.cleanup_units(T(lua, {}), False).ok


ITEM_FLAG_KEEPS = [
    ("hidden", {"flags": {"hidden": True}}),
    ("worldgen", {"flags": {"from_worldgen": True}}),
    ("artifact", {"flags2": {"might_contain_artifact": True}}),
    ("location", {"flags2": {"location_reserved": True}}),
    ("riding", {"flags2": {"has_rider": True}}),
    ("container", {"refs": {"CONTAINS_UNIT": True}}),
    ("container", {"refs": {"CONTAINS_ITEM": True}}),
    ("container", {"contained": [{"id": 5}]}),
    ("vehicle", {"vehicle": 3}),
]


@test("review 1-2: kept at every level: flags hidden, from_worldgen, might_contain_artifact, location_reserved, "
      "has_rider; a minecart; a cage or trap holding a creature; anything holding an item; no flags2 at all is no error")
def _():
    for why, extra in ITEM_FLAG_KEEPS:
        lua, env, w = world()
        fort(lua, w)
        it = {"id": 77, "kind": "REMAINS", "race": 9, "pos": cavern(lua, w, 20, 20),
              "flags": dict(extra.get("flags", {}))}
        for k in ("flags2", "refs", "contained"):
            if k in extra:
                it[k] = extra[k]
        item = w.mk(T(lua, it))
        if "vehicle" in extra:
            item.getVehicleID = lua.eval(f"function() return {extra['vehicle']} end")
        c = py(year_on(lua, env)["items"])
        assert c["unreachable_old"] == 0 and (c["kept"] or {}).get(why) == 1, (why, c)
        r = env.cleanup_items(T(lua, {"level": "full"}), False)
        assert not r.ok and r.removed == 0 and not list(w.removed.values()), (why, py(r))
    # no flags2, no getVehicleID, a vehicle id of -1: the item may go
    lua, env, w = world()
    fort(lua, w)
    item = w.mk(T(lua, {"id": 77, "kind": "REMAINS", "race": 9, "pos": cavern(lua, w, 20, 20)}))
    item.getVehicleID = lua.eval("function() return -1 end")
    year_on(lua, env)
    assert env.cleanup_items(T(lua, {}), False).removed == 1


@test("review 3: at 'safe' only the low-value kinds go (remains, body parts, unnamed corpses, vermin, rotten, rags); "
      "goods and a named corpse stay, still followed for 'full'; the report counts unreachable_old_safe")
def _():
    lua, env, w = world()
    fort(lua, w)
    cheap = [("REMAINS", {"race": 9}), ("CORPSEPIECE", {"race": 9}), ("CORPSE", {"race": 9}), ("VERMIN", {}),
             ("FISH_RAW", {"flags": {"rotten": True}}), ("CLOTH", {"wear": 3, "mat": "THREAD_PLANT"}),
             ("SHOES", {"wear": 3, "mat": "LEATHER", "quality": 4}), ("THREAD", {"wear": 4, "mat": "SILK"}),
             ("PANTS", {"wear": 3, "mat": "YARN"})]
    dear = [("BOULDER", {}), ("BAR", {}), ("WEAPON", {}), ("CLOTH", {"wear": 1, "mat": "SILK"}),
            ("ARMOR", {"wear": 2, "mat": "LEATHER"}), ("CORPSE", {"race": 9, "hist_figure_id": 12}), ("AMMO", {}),
            ("CORPSE", {"race": 9, "hist_figure_id": 13, "flags": {"rotten": True}}),     # named and rotten: kept
            ("ARMOR", {"wear": 3}),                                                         # worn, but metal
            ("CLOTH", {"wear": 3, "mat": "SILK", "quality": 5}),                            # a masterwork
            ("CLOTH", {"wear": 3, "mat": "SILK", "improvements": [{"x": 1}]})]              # decorated
    for i, (kind, extra) in enumerate(cheap + dear):
        w.mk(T(lua, {"id": 1000 + i, "kind": kind, "pos": cavern(lua, w, 10 + i, 10), **extra}))   # (race 9: no dwarf's)
    c = py(year_on(lua, env)["items"])
    assert c["unreachable_old"] == len(cheap) + len(dear) and c["unreachable_old_safe"] == len(cheap), c
    assert c["tracked"] == len(cheap) + len(dear) and c["tracked_value"] == len(dear), c
    d = env.cleanup_items(T(lua, {}), True)
    assert d.ok and d.level == "safe" and d.candidates == len(cheap) and not py(d)["kept"], py(d)   # goods not read
    r = env.cleanup_items(T(lua, {"max": 500}), False)
    assert r.removed == len(cheap) and sorted(w.removed.values()) == list(range(1000, 1000 + len(cheap))), py(r)
    assert env.state().n_items == 0 and env.state().n_value == len(dear)      # the goods still followed
    assert py(env.report()["items"])["unreachable_old_safe"] == 0
    r = env.cleanup_items(T(lua, {"level": "full", "max": 500}), False)
    assert r.removed == len(dear) and r.level == "full", py(r)


@test("review 3: anything in a cavern the AI's seal shut off stays at every level (all caverns, or the layer sealed; "
      "another layer's not); a creature there too")
def _():
    lua, env, w = world()
    fort(lua, w)
    a, b = cavern(lua, w, 20, 20), cavern(lua, w, 21, 20, z=30)
    for p, gid in ((a, 7), (b, 8)):
        k = f"{p['x']},{p['y']},{p['z']}"
        w.tflags[k] = T(lua, {"feature_global": True})
        w.gid[k] = gid
    w.mk(T(lua, {"id": 77, "kind": "REMAINS", "race": 9, "pos": a}))
    w.mk(T(lua, {"id": 78, "kind": "REMAINS", "race": 9, "pos": b}))
    gob = w.unit(T(lua, {"id": 7001, "danger": True, "pos": a}))
    w.site["ai-overseer/threats"] = T(lua, {"sealed": {"all caverns": {"ids": [1], "tick": 0}}})
    c = py(year_on(lua, env)["items"])
    assert c["unreachable_old"] == 0 and c["kept"].get("sealed") == 2, c
    assert not env.cleanup_items(T(lua, {"level": "full"}), False).ok and not list(w.removed.values())
    assert env.unit_keep(gob) == "sealed"
    # one layer sealed (an older seal's record): it and every layer below; a layer that can't be named: sealed
    w.site["ai-overseer/threats"] = T(lua, {"sealed": {"Cavern1": {"ids": [1], "tick": 0}}})
    env.cavern_layer_names = lua.eval("function() return {[7] = 'Cavern1', [8] = 'Cavern2'} end")
    assert env.in_sealed_cavern(env.sealed_layers(), 21, 20, 30) and env.in_sealed_cavern(env.sealed_layers(), 20, 20, 50)
    w.site["ai-overseer/threats"] = T(lua, {"sealed": {"Cavern2": {"ids": [1], "tick": 0}}})
    advance(lua, env, DAY + 1)
    c = py(year_on(lua, env)["items"])                  # 78 followed from now: a year on, old enough
    assert c["kept"].get("sealed") == 1 and c["unreachable_old"] == 1, c
    r = env.cleanup_items(T(lua, {"level": "full"}), False)
    assert r.removed == 1 and list(w.removed.values()) == [77], py(r)      # Cavern1, above the seal
    env.cavern_layer_names = lua.eval("function() return {} end")
    assert env.in_sealed_cavern(env.sealed_layers(), 21, 20, 30)
    # no seal: nothing kept for it
    w.site["ai-overseer/threats"] = T(lua, {"sealed": {}})
    assert not env.in_sealed_cavern(env.sealed_layers(), 20, 20, 50)


@test("review 5: a walk resumes after the id it stopped at, not an index (items removed in front between reports); "
      "resume_at's fast path and binary search")
def _():
    lua, env, w = world()
    fort(lua, w)
    for i in range(1, 1501):
        w.mk(T(lua, {"id": i, "kind": "BOULDER"}))
    lost_items(lua, w, 10, start=2000)
    w.CLOCK, w.CLOCK_STEP = 0.0, 0.015
    r = env.report()
    p = env.state()["pass"]
    assert r.walking and p.phase == "items" and 0 < p.i < 1500, (p.phase, p.i)
    lua.execute("local t = ...; for _ = 1, 600 do table.remove(t, 1) end", w["items"])
    for _ in range(100):
        if not env.report().walking:
            break
    w.CLOCK = None
    c = py(env.report()["items"])
    assert c["unreachable"] == 10 and c["tracked"] == 10, c
    L = lua.eval("{ {id = 1}, {id = 3}, {id = 5}, {id = 7} }")
    assert env.resume_at(L, 4, 2, 3) == 2                     # the one before i is still the last walked
    lua.execute("table.remove(..., 1)", L)                    # id 1 gone: 3 now at index 0
    assert env.resume_at(L, 3, 2, 3) == 1
    assert env.resume_at(L, 3, 2, 4) == 1 and env.resume_at(L, 3, 2, 9) == 3 and env.resume_at(L, 3, 0, None) == 0


@test("review 5: a pass that doesn't see a followed item keeps following it unless it is gone")
def _():
    lua, env, w = world()
    fort(lua, w)
    items = lost_items(lua, w, 3)
    full_pass(env)
    g = env.df["global"].world["items"]["other"]
    g.IN_PLAY = lua.table()                                    # the walk sees none of them
    items[0].flags.removed = True
    advance(lua, env, DAY + 1)
    c = py(full_pass(env)["items"])
    assert c["tracked"] == 2, c
    g.IN_PLAY = w["items"]
    advance(lua, env, YEAR)
    assert py(full_pass(env)["items"])["unreachable_old"] == 2


@test("review 6: a spatter event is freed only when it came off the block's list")
def _():
    lua, env, w = world()
    fort(lua, w)
    b = w.block(T(lua, {"x": 0, "y": 0, "z": 100}))
    ev = SP.spatter(lua)
    b.block_events = lua.eval("""function(ev) local raw = {ev}
        return setmetatable({}, {__index = raw, __len = function() return #raw end,
                                 __newindex = function() error('read-only') end}) end""")(ev)
    r = env.cleanup_spatter(T(lua, {}), False)
    assert ev.deleted is False and r.removed == 0 and r.failed == 1, py(r)
    ok = w.block(T(lua, {"x": 0, "y": 0, "z": 90}))
    ev2 = SP.spatter(lua)
    ok.block_events = lua.table_from([ev2])
    r = env.cleanup_spatter(T(lua, {}), False)
    assert ev2.deleted is True and r.removed == 1, py(r)


@test("review 9: the cleanup actions clear the cached sections whose counts they change")
def _():
    inv = BRIDGE[BRIDGE.index("CACHE_INVALIDATES = {"):BRIDGE.index("SECTION_CACHE = SECTION_CACHE or {}")]
    assert code_has(inv, "CACHE_INVALIDATES.cleanup_items = {'disposal', 'industry'}")
    assert code_has(inv, "CACHE_INVALIDATES.cleanup_units = {'disposal'}")
    assert code_has(inv, "CACHE_INVALIDATES.cleanup_dead_units = {'disposal', 'dead'}")
    cleanup_src = (LUA_DIR / "ai-cleanup.lua").read_text(encoding="utf-8")
    assert "one full pass at most a game day" not in cleanup_src and "a pass spans many reports" in cleanup_src
    assert "a pass spans many reports" in BRIDGE


@test("review 3: the bridge's cleanup_items: level safe or full (else refused), safe by default; full only while "
      "the Rules say full")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    f = lua.eval("""function(src, setting)
        local seen = {}
        local env = setmetatable({BRIDGE_VERSION = 'x', OUT_DIR = '/tmp'}, {__index = _G})
        env.require = function(n) return {} end
        env.reject = function(m) return {ok = false, rejected = true, error = m} end
        env.int_in = function(v, lo, hi) local n = math.tointeger(tonumber(v)); if n == nil or n < lo or n > hi then return nil end return n end
        env.reqscript = function(n)
            if n == 'ai-overseer-settings' then return {load_settings = function() return {world_cleanup = setting} end} end
            return {cleanup_items = function(o, dry) seen[#seen + 1] = o.level; return {ok = true} end}
        end
        assert(load(src, 'actions', 't', env))()
        return env, seen
    end""")
    env, seen = f(ACTS, "safe")
    assert env.act_cleanup_items(T(lua, {"level": "nuke"})).rejected
    env.act_cleanup_items(T(lua, {}))
    env.act_cleanup_items(T(lua, {"level": "full"}))
    assert [seen[i] for i in (1, 2)] == ["safe", "safe"]
    env, seen = f(ACTS, "full")
    env.act_cleanup_items(T(lua, {"level": "full"}))
    assert seen[1] == "full"


@test("review 3: the brain: at safe the items' count is unreachable_old_safe and the call says level safe; at full "
      "unreachable_old and level full")
def _():
    m = Memory()
    m.cleanup_seen = {"dry": {"items@safe": 1, "items@full": 1}}
    th = PC.cleanup_thresholds(fort_state(), CFG, section())["items"]
    c = section(items__unreachable_old=th * 3, items__unreachable_old_safe=th - 1)
    assert mine(fort_state(c), m)[0] == []
    props, _ = mine(fort_state(c, world_cleanup="full"), m)
    assert len(props) == 1 and props[0].action["level"] == "full", props
    c = section(items__unreachable_old=th * 3, items__unreachable_old_safe=th)
    props, _ = mine(fort_state(c), m)
    assert len(props) == 1 and props[0].action["level"] == "safe" and "low-value" in props[0].reason, props



@test("last review 4: the goods are followed in a map of their own (capped apart): they never fill the junk's room")
def _():
    lua, env, w = world()
    fort(lua, w)
    env.VALUE_TRACK_MAX = 2
    env.ITEM_TRACK_MAX = 3
    lost_items(lua, w, 5, start=1000)                                      # boulders: goods
    for i in range(3):
        w.mk(T(lua, {"id": 3000 + i, "kind": "REMAINS", "race": 9, "pos": cavern(lua, w, 40 + i, 10)}))
    c = py(year_on(lua, env)["items"])
    assert env.state().n_value == 2 and env.state().n_items == 3 and c["unreachable_old_safe"] == 3, c
    assert env.cleanup_items(T(lua, {}), False).removed == 3
    env.reset()                                                            # both maps kept in the save
    assert env.state().n_value == 2


@test("last review 4: a real cleanup call that removed nothing backs that kind off (at that level) a season; a "
      "trial doesn't, a spatter slice with more to walk doesn't")
def _():
    m = Memory()
    m.cleanup_seen = {"dry": {"items@safe": 1, "spatter@safe": 1}}
    s = fort_state(section(items__unreachable_old=10 ** 5, items__unreachable_old_safe=10 ** 5, spatter__outside=10 ** 6))
    props, _ = mine(s, m)
    it = [p for p in props if p.rule == "cleanup_items"][0]
    sp = [p for p in props if p.rule == "cleanup_spatter"][0]
    record([(it, {"ok": False, "rejected": True, "removed": 0}), (sp, {"ok": True, "removed": 0, "more": True})], s, m)
    assert sorted(p.rule for p in mine(s, m)[0]) == ["cleanup_spatter"], mine(s, m)[0]
    # full: its own key
    props, _ = mine(fort_state(section(items__unreachable_old=10 ** 5), world_cleanup="full"), m)
    assert "cleanup_items_dry" in [p.rule for p in props]
    s2 = copy.deepcopy(s)
    s2["date"]["tick"] = s2["date"].get("tick", 0) + PLANNER_CONFIG["cleanup_empty_backoff_ticks"] + 1
    assert "cleanup_items" in [p.rule for p in mine(s2, m)[0]]
    # a trial at safe says nothing for full
    m2 = Memory()
    sd = fort_state(section(items__unreachable_old=10 ** 5, items__unreachable_old_safe=10 ** 5))
    d = mine(sd, m2)[0][0]
    record([(d, {"ok": True, "dry_run": True, "would_remove": 5})], sd, m2)
    assert "items@safe" in m2.cleanup_seen["dry"] and "items@full" not in m2.cleanup_seen["dry"]


@test("last review 1-3: safe_kind: a named body stays even rotten; a body of the fort's civ stays; rotten food goes")
def _():
    lua, env, w = world()
    fort(lua, w)
    named = w.mk(T(lua, {"id": 1, "kind": "CORPSEPIECE", "race": 9, "hist_figure_id": 4, "flags": {"rotten": True}}))
    w.unit(T(lua, {"id": 6001, "dead": True, "civ_id": 10, "race": 9}))
    ours = w.mk(T(lua, {"id": 2, "kind": "CORPSE", "race": 9, "unit_id": 6001}))
    food = w.mk(T(lua, {"id": 3, "kind": "MEAT", "flags": {"rotten": True}}))
    assert env.safe_kind(named) is False and env.safe_kind(ours) is False and env.safe_kind(food) is True


@test("last review 7: the bridge refuses every cleanup action at off (or settings unread), cleanup_units unless full")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    f = lua.eval("""function(src, setting)
        local seen = {}
        local env = setmetatable({BRIDGE_VERSION = 'x', OUT_DIR = '/tmp'}, {__index = _G})
        env.require = function(n) return {} end
        env.reject = function(m) return {ok = false, rejected = true, error = m} end
        env.int_in = function(v, lo, hi) local n = math.tointeger(tonumber(v)); if n == nil or n < lo or n > hi then return nil end return n end
        env.reqscript = function(n)
            if n == 'ai-overseer-settings' then
                if setting == 'broken' then error('no settings') end
                return {load_settings = function() return {world_cleanup = setting} end}
            end
            local m = {}
            for _, k in ipairs({'cleanup_items', 'cleanup_units', 'cleanup_spatter', 'cleanup_dead_units'}) do
                m[k] = function(o, dry) seen[#seen + 1] = k; return {ok = true} end
            end
            return m
        end
        assert(load(src, 'actions', 't', env))()
        return env, seen
    end""")
    for setting in ("off", "broken"):
        env, seen = f(ACTS, setting)
        for a in ACTIONS:
            r = getattr(env, "act_" + a)(T(lua, {"dry_run": True}))
            assert r.rejected and "World cleanup" in r.error, (setting, a, py(r))
        assert len(seen) == 0
    env, seen = f(ACTS, "safe")
    assert env.act_cleanup_units(T(lua, {})).rejected
    for a in ("cleanup_items", "cleanup_spatter", "cleanup_dead_units"):
        assert getattr(env, "act_" + a)(T(lua, {})).ok, a
    env, seen = f(ACTS, "full")
    assert env.act_cleanup_units(T(lua, {})).ok


# --- scripts identity: without a cleanup section, plan() is main's --------------------------

PROBE = r'''
import copy, json, sys
from pathlib import Path
brain = Path(sys.argv[1]); sys.path.insert(0, str(brain))
fixtures = Path(sys.argv[2])
from digest import normalize
from planner import Memory, plan, record, select, note_cycle, TICKS_PER_DAY
out = {}
for path in [fixtures / "test_fort.json"] + sorted((fixtures / "real").glob("*.json")):
    base = json.loads(path.read_text(encoding="utf-8"))
    for slow in (False, True):
        s = copy.deepcopy(base)
        if slow:
            s["fps_low"] = 8
        s = normalize(s)
        m = Memory()
        cycles = []
        for _ in range(3):
            n = note_cycle(copy.deepcopy(s), m)
            props, notes = plan(copy.deepcopy(s), m)
            cycles.append({"props": [[p.rule, json.dumps(p.action, sort_keys=True, default=str), p.reason,
                                      p.priority] for p in props], "notes": notes, "cycle": n})
            allowed, _ = select(props, s, m)
            record([(p, {"ok": False, "error": "refused (test)"}) for p in allowed], s, m)
            s["date"]["tick"] = s["date"].get("tick", 0) + TICKS_PER_DAY
        out[f"{path.name}:{slow}"] = cycles
print(json.dumps(out, sort_keys=True))
'''

_MAIN = {}


def main_brain() -> Path | None:
    if "dir" not in _MAIN:
        tmp = tempfile.mkdtemp(prefix="r40-main-")
        arch = subprocess.run(["git", "-C", str(ROOT), "archive", "main", "brain"], capture_output=True)
        if arch.returncode != 0:
            _MAIN["dir"] = None
        else:
            subprocess.run(["tar", "-x", "-C", tmp], input=arch.stdout, check=True)
            _MAIN["dir"] = Path(tmp) / "brain"
            atexit.register(shutil.rmtree, tmp, True)
    return _MAIN["dir"]


def probe(brain: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "probe.py"
        p.write_text(PROBE, encoding="utf-8")
        r = subprocess.run([sys.executable, "-I", str(p), str(brain), str(ROOT / "tests" / "fixtures")],
                           capture_output=True, text=True, env=dict(os.environ, DFAI_LOG_DIR=tmp), cwd=tmp)
    assert r.returncode == 0, r.stderr[-1500:]
    return r.stdout.strip().splitlines()[-1]


@test("no cleanup section in the report (world_cleanup at its default, safe): plan() and note_cycle() are main's, "
      "byte for byte (every fixture, slow and not, 3 cycles)")
def _():
    main = main_brain()
    assert main is not None, "no main branch to compare with"
    a, b = probe(main), probe(ROOT / "brain")
    if a != b:
        ja, jb = json.loads(a), json.loads(b)
        bad = [k for k in ja if ja[k] != jb.get(k)]
        raise AssertionError(f"differs from main at {bad[:3]}")


if LuaRuntime is None:
    finish("these tests need the lupa package (pip install lupa)")
finish()
