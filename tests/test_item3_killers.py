"""(item3) A killer among the fort's own: lua/ai-killers.lua in a fake fort
(cursed citizens and residents by the game's flags, curse tags and
syndromes; the living who killed the fort's people, from DF's incidents and
crimes, with what is lawful left out; a confidence each, the first sighting
kept in the save; the cell: placed, locked once inside, let out to eat and
drink, taken back, released), the bridge's wiring, the old-death fix in
death_details (F, 13 Nov: ghosts laid to rest after a restart were told as
new "bleed" deaths), and the brain (brain/planner_killers.py).

    python tests/test_item3_killers.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
import planner_killers as PK  # noqa: E402
from digest import normalize, SECTION_DEFAULTS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
DAY = 1200
YEAR = 403200

FAKE = r"""
local src = ...
local W = {units = {}, dead = {}, site = {}, incidents = {}, crimes = {}, doors = {}, dungeons = {}, bedrooms = {},
           syndromes = {}, threat_cells = {}}
local env = setmetatable({}, {__index = _G})
local function zero_based(t)
    return setmetatable({}, {__len = function() return #t end, __index = function(_, i) return t[i + 1] end})
end
local blist = setmetatable({}, {__index = {insert = function(self, _, b) rawset(self, #self + 1, b) end}})
W.burrows = blist
function W.unit(t)
    t.civ_id = t.civ_id or 10
    t.race = t.race or 1
    t.mood = t.mood or -1
    t.pos = t.pos or {x = 50, y = 50, z = 100}
    t.enemy = t.enemy or {normal_race = -1, were_race = -1}
    t.counters2 = t.counters2 or {thirst_timer = 0, hunger_timer = 0}
    t.military = t.military or {squad_id = -1}
    t.curse = t.curse or {add_tags1 = {}, add_tags2 = {}}
    t.syndromes = t.syndromes or {active = {}}
    if t.is_dead then table.insert(W.dead, t) else table.insert(W.units, t) end
    return t
end
function W.door(t)
    t.door_flags = t.door_flags or {forbidden = false}
    t.getType = function() return 'Door' end
    table.insert(W.doors, t)
    return t
end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {
    global = {cur_year = 300, cur_year_tick = 0,
              world = {units = {active = W.units}, incidents = {all = zero_based(W.incidents)},
                       crimes = {all = zero_based(W.crimes)},
                       buildings = {other = {ZONE_DUNGEON = W.dungeons, ZONE_BEDROOM = W.bedrooms}, all = {}}},
              plotinfo = {civ_id = 10, burrows = {list = blist, next_id = 1}}},
    mood_type = {[7] = 'Berserk', [5] = 'Melancholy'},
    death_type = {[4] = 'BLEED', [7] = 'STRUCK_DOWN', [50] = 'DRAIN_BLOOD'},
    conflict_level = {[0] = 'None', [3] = 'Training', [4] = 'Brawl', [5] = 'Nonlethal', [6] = 'Lethal'},
    crime_type = {[4] = 'Murder', [5] = 'DisorderlyBehavior', [10] = 'BloodDrinking'},
    building_type = {Door = 'Door', Hatch = 'Hatch'},
    burrow = {new = function() return {tiles = {}, units = {}} end},
    unit = {find = function(id)
        for _, l in ipairs({W.units, W.dead}) do for _, u in ipairs(l) do if u.id == id then return u end end end
    end},
    building = {find = function(id)
        for _, l in ipairs({W.doors, W.dungeons, W.bedrooms}) do for _, b in ipairs(l) do if b.id == id then return b end end end
    end},
    syndrome = {find = function(id) return W.syndromes[id] end},
}
env.dfhack = {
    df2utf = function(s) return s end,
    units = {isDead = function(u) return u.is_dead == true end,
             isCitizen = function(u) return u.citizen == true end,
             isResident = function(u) return u.resident == true end,
             isOwnGroup = function(u) return u.own == true end,
             isBloodsucker = function(u) return u.vamp == true end,
             isNightCreature = function(u) return u.night == true end,
             isAdult = function(u) return not u.child end,
             getNoblePositions = function(u) return u.positions end,
             getReadableName = function(u) return u.name or ('dwarf ' .. u.id) end},
    buildings = {containsTile = function() return true end,
                 findAtTile = function(p)
                     for _, d in ipairs(W.doors) do if d.x == p.x and d.y == p.y and d.z == p.z then return d end end
                 end},
    burrows = {setAssignedTile = function(b, p, on) b.tiles[p.x .. ',' .. p.y .. ',' .. p.z] = on or nil end,
               setAssignedUnit = function(b, u, on) b.units[u.id] = on or nil end,
               clearTiles = function(b) b.tiles = {} end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
env.reqscript = function(name)
    if name == 'ai-threats' then return {load_state = function() return {cells = W.threat_cells} end} end
    error('no module ' .. tostring(name))
end
assert(load(src, 'ai-killers', 't', env))()
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-killers.lua"))
    return lua, env, w


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


def py(v):
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    try:
        keys = list(v.keys())
    except AttributeError:
        return v
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in sorted(keys)]
    return {k: py(v[k]) for k in keys}


def unit(lua, w, **kw):
    return w.unit(T(lua, kw))


def kill(lua, w, killer, victim, cause=7, conflict=6, years_ago=0):
    w.incidents[len(w.incidents) + 1] = T(lua, {"criminal": killer, "victim": victim, "death_cause": cause,
                                                "conflict_level": conflict, "event_year": 300 - years_ago,
                                                "event_time": 0})


def victim(lua, w, vid, **kw):
    return unit(lua, w, id=vid, name=f"Victim {vid}", is_dead=True, **kw)


def advance(env, ticks):
    g = env.df["global"]
    g.cur_year_tick = g.cur_year_tick + ticks


def big_fort(lua, w):
    """Every kind of suspect, and the lawful killings left out."""
    unit(lua, w, id=1, name="Vamp", citizen=True, vamp=True)
    unit(lua, w, id=2, name="Wolfy", citizen=True, enemy={"normal_race": -1, "were_race": 5})
    unit(lua, w, id=3, name="Murd", citizen=True)
    for v in (20, 21):
        victim(lua, w, v)
        kill(lua, w, 3, v)
    unit(lua, w, id=4, name="Brawler", citizen=True)
    victim(lua, w, 22)
    kill(lua, w, 4, 22, conflict=4)
    unit(lua, w, id=5, name="Sheriff", citizen=True, positions=[{"position": {"code": "SHERIFF"}}])
    victim(lua, w, 23, mood=7)                 # berserk: lawful
    kill(lua, w, 5, 23)
    for v in (24, 25):
        victim(lua, w, v)
        kill(lua, w, 5, v)
    unit(lua, w, id=6, name="Lodger", resident=True)
    victim(lua, w, 26)
    kill(lua, w, 6, 26, cause=50)              # drained of blood
    unit(lua, w, id=7, name="Oldtimer", citizen=True)
    victim(lua, w, 27)
    kill(lua, w, 7, 27, years_ago=2)           # outside the window
    unit(lua, w, id=8, name="Bitten", citizen=True, syndromes={"active": [{"type": 77}]})
    w.syndromes[77] = T(lua, {"ce": [{"tags1": {"BLOODSUCKER": True}}]})
    unit(lua, w, id=9, name="Sipper", citizen=True)
    w.crimes[1] = T(lua, {"mode": 10, "criminal": 9})
    w.crimes[2] = T(lua, {"mode": 5, "criminal": 7})         # a tantrum: nothing
    unit(lua, w, id=10, name="Sparrer", citizen=True)
    victim(lua, w, 28)
    kill(lua, w, 10, 28, conflict=3)           # training: lawful
    unit(lua, w, id=99, name="Titan", civ_id=-1)
    victim(lua, w, 29)
    kill(lua, w, 99, 29)                       # not one of the fort's own
    unit(lua, w, id=11, name="Visitor killer", citizen=True)
    victim(lua, w, 30, civ_id=-1)              # a visitor, not the fort's
    kill(lua, w, 11, 30)


# --- 1. the report ----------------------------------------------------------------

@test("report: each suspect with its kind and confidence; the lawful, old, outsider and foreign killings left out")
def _():
    lua, env, w = world()
    big_fort(lua, w)
    r = py(env.report())
    rows = {x["id"]: x for x in r["list"]}
    assert set(rows) == {1, 2, 3, 4, 5, 6, 8, 9}, sorted(rows)
    assert (rows[1]["kind"], rows[1]["confidence"]) == ("vampire", "certain")
    assert (rows[2]["kind"], rows[2]["confidence"]) == ("werebeast", "certain")
    assert (rows[3]["kind"], rows[3]["confidence"], rows[3]["kills"]) == ("killer", "strong", 2), rows[3]
    assert rows[3]["victims"] == ["Victim 21", "Victim 20"] and rows[3]["causes"] == {"STRUCK_DOWN": 2}, rows[3]
    assert (rows[4]["confidence"], rows[4]["kills"], rows[4]["brawls"]) == ("weak", 0, 1), rows[4]
    assert (rows[5]["confidence"], rows[5]["kills"], rows[5]["lawful"], rows[5]["law"]) == ("strong", 2, 1, True)
    assert (rows[6]["confidence"], rows[6]["drained"], rows[6]["resident"]) == ("strong", True, True), rows[6]
    assert rows[6].get("citizen") is None
    assert (rows[8]["kind"], rows[8]["tags"]) == ("vampire", ["BLOODSUCKER"]), rows[8]
    assert (rows[9]["confidence"], rows[9]["crimes"]) == ("strong", {"BloodDrinking": 1}), rows[9]
    # the surest first
    assert [x["confidence"] for x in r["list"]] == sorted((x["confidence"] for x in r["list"]),
                                                         key=["certain", "strong", "weak"].index)
    assert r["total"] == 8 and r["scanned"] >= 10 and not r["cells"] and r["rooms"] == 0, r


@test("report: the first sighting is kept in the save (seen_ticks grows); one no longer suspected is forgotten")
def _():
    lua, env, w = world()
    unit(lua, w, id=3, name="Murd", citizen=True)
    for v in (20, 21):
        victim(lua, w, v)
        kill(lua, w, 3, v)
    assert py(env.report())["list"][0]["seen_ticks"] == 0
    advance(env, 700)
    assert py(env.report())["list"][0]["seen_ticks"] == 700
    w.incidents[1] = None
    w.incidents[2] = None
    r = py(env.report())
    assert not r["list"] and not py(w.site["ai-overseer/killers"])["seen"], r


@test("report: a quiet fort (F after the titan: no curse, nobody living with a killing) lists nobody")
def _():
    lua, env, w = world()
    for i in range(1, 6):
        unit(lua, w, id=i, citizen=True)
    victim(lua, w, 20)
    kill(lua, w, 99, 20, cause=4)          # the titan's bleed: killer not one of the fort's
    victim(lua, w, 21, mood=7)
    kill(lua, w, 2, 21)                    # a berserk one killed by the guard
    r = py(env.report())
    assert not r["list"] and r["total"] == 0, r


# --- 2. the cell ------------------------------------------------------------------------

def cell_fort(lua, w, kind="dungeon"):
    u = unit(lua, w, id=3, name="Murd", citizen=True, pos={"x": 10, "y": 10, "z": 100})
    z = T(lua, {"id": 500, "x1": 20, "y1": 20, "x2": 22, "y2": 22, "z": 100, "assigned_unit_id": -1})
    (w.dungeons if kind == "dungeon" else w.bedrooms)[1] = z
    d = w.door(T(lua, {"id": 600, "x": 23, "y": 21, "z": 100}))
    return u, z, d


def cell(lua, env, ids, dry=False, release_only=False):
    return py(env.cell(T(lua, {"units": ids, "release_only": release_only}), dry))


@test("cell: placed (burrow on the jail zone), locked once inside, let out thirsty, back once fed, released when not listed")
def _():
    lua, env, w = world()
    u, z, d = cell_fort(lua, w)
    r = cell(lua, env, [3])
    assert r["placed"] == ["Murd"] and r["ok"] is True, r
    b = w.burrows[1]
    assert b.name == "AI killer cell 3" and b.units[3] is True and len(list(b.tiles.keys())) == 9
    assert d.door_flags.forbidden is False
    r = cell(lua, env, [3])
    assert r["waiting"] == ["Murd"] and d.door_flags.forbidden is False, r      # not inside yet
    u.pos.x, u.pos.y = 21, 21
    r = cell(lua, env, [3])
    assert r["locked"] == ["Murd"] and d.door_flags.forbidden is True, r
    assert cell(lua, env, [3])["rejected"] is True                               # as it should be
    u.counters2.thirst_timer = 25000
    rep = py(env.report())                                                       # the report lets them out itself
    assert d.door_flags.forbidden is False and b.units[3] is None, rep
    assert rep["cells"][0]["out"] is True
    r = cell(lua, env, [3])
    assert r["waiting"] == ["Murd"] and b.units[3] is None, r                    # still thirsty: stays out
    u.counters2.thirst_timer = 100
    r = cell(lua, env, [3])
    assert b.units[3] is True, r                                                 # fed: back to the cell
    r = cell(lua, env, [3])
    assert r["locked"] == ["Murd"] and d.door_flags.forbidden is True, r
    r = cell(lua, env, [])
    assert r["released"] == ["Murd"] and d.door_flags.forbidden is False and b.units[3] is None, r
    assert len(list(b.tiles.keys())) == 0 and py(w.site["ai-overseer/killers"])["cells"] in ({}, [])


@test("cell: a dry run changes nothing; release_only locks nobody; no room is said; a moon cell's room is never taken")
def _():
    lua, env, w = world()
    u, z, d = cell_fort(lua, w, kind="bedroom")
    r = cell(lua, env, [3], dry=True)
    assert r["placed"] == ["Murd"] and r["dry_run"] is True and len(w.burrows) == 0, r
    assert w.site["ai-overseer/killers"] is None
    r = cell(lua, env, [3], release_only=True)
    assert r["rejected"] is True and len(w.burrows) == 0, r
    w.threat_cells["5"] = T(lua, {"zone": 500})
    r = cell(lua, env, [3])
    assert r["ok"] is False and "no jail zone" in r["error"], r
    w.threat_cells["5"] = None
    u.pos.x, u.pos.y = 21, 21
    cell(lua, env, [3])
    cell(lua, env, [3])
    assert d.door_flags.forbidden is True
    u.counters2.hunger_timer = 45000
    r = cell(lua, env, [3], release_only=True)                                   # halted: the let-out still runs
    assert r["out"] == ["Murd"] and d.door_flags.forbidden is False, r


@test("cell: nobody else in the room when the doors lock; a dead prisoner's cell is cleared")
def _():
    lua, env, w = world()
    u, z, d = cell_fort(lua, w)
    cell(lua, env, [3])
    u.pos.x, u.pos.y = 21, 21
    unit(lua, w, id=4, citizen=True, pos={"x": 20, "y": 20, "z": 100})
    r = cell(lua, env, [3])
    assert r["waiting"] == ["Murd"] and d.door_flags.forbidden is False, r
    u.is_dead = True
    r = cell(lua, env, [3])
    assert r["released"] == ["Murd"], r


# --- 3. the bridge ----------------------------------------------------------------------

@test("bridge: the killers section (safe), killer_cell (ids checked, dry run, release_only while halted), the module listed")
def _():
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "killers = function() return safe(function() return reqscript('ai-killers').report() end) end," in src
    actions = src[src.index("ACTIONS = {"):src.index("DRY_OK = {}")]
    assert "killer_cell = function(a)" in actions and "reqscript('ai-killers').cell" in actions
    dry = src[src.index("DRY_OK = {}"):src.index("}) do DRY_OK[name] = true end")]
    assert "'killer_cell'" in dry
    assert "killer_cell = 'release_only'" in src
    mods = src[src.index("BRIDGE_MODULES = {"):src.index("}", src.index("BRIDGE_MODULES = {"))]
    assert "'ai-killers'" in mods
    assert SECTION_DEFAULTS["killers"] == {}
    import overseer
    import planner_core
    import strategist
    assert "killer_cell" in overseer.SHORT_WORDS
    assert "killer" in planner_core.STEER_PROTECTED and "killer" in strategist.RAISE_FORBIDDEN
    if LuaRuntime is None:
        return
    i = src.index("    killer_cell = function(a)")
    j = src.index("    end,\n", i) + len("    end,\n")
    fn = src[i:j].strip().rstrip(",").replace("killer_cell = function(a)", "return function(a)", 1)
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
        GOT = nil
        function reject(r) return {ok = false, rejected = true, error = r} end
        function reqscript() return {cell = function(o, dry) GOT = {o = o, dry = dry}; return {ok = true} end} end
    """)
    f = lua.execute(fn)
    assert f(lua.table_from({}))["rejected"] is True
    assert f(lua.table_from({"units": lua.table_from([1.5])}))["rejected"] is True
    assert f(lua.table_from({"units": lua.table_from([3, 4.0]), "dry_run": True}))["ok"] is True
    got = lua.globals().GOT
    assert list(got.o.units.values()) == [3, 4] and got.dry is True and got.o.release_only is False


@test("death_details: a death more than a day old when told is `again` (F: ghosts laid to rest after a restart)")
def _():
    if LuaRuntime is None:
        return
    src = (ROOT / "tests" / "test_bridge_memory.py").read_text(encoding="utf-8")
    harness = re.search(r'HARNESS = r"""(.*?)"""', src, re.S).group(1)
    L = LuaRuntime(unpack_returned_tuples=True)
    H = L.execute(harness, (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8"), str(LUA_DIR))
    env = H.module()
    r = L.execute(r"""
    local env, df, dfhack = ...
    df.global.cur_year, df.global.cur_year_tick = 266, 1000
    df.death_type = {[4] = 'BLEED'}
    local old = {id = 5, counters = {death_id = 70}}
    local new = {id = 6, counters = {death_id = 71}}
    df.unit = {find = function(id) return ({[5] = old, [6] = new})[id] end}
    df.incident = {find = function(id) return ({[70] = {death_cause = 4, criminal = -1, event_year = 257, event_time = 5000},
                                                [71] = {death_cause = 4, criminal = -1, event_year = 266, event_time = 900}})[id] end}
    dfhack.units = dfhack.units or {}
    dfhack.units.isGhost = function() return false end
    env.DEATHS_TOLD = {}
    local a, b = {}, {}
    env.death_details(a, 5)
    env.death_details(b, 6)
    return {a_again = a.again or false, a_old = a.old_death or false, a_cause = a.cause, b_again = b.again or false}
    """, env, H.df, H.dfhack)
    assert (r["a_again"], r["a_old"], r["a_cause"], r["b_again"]) == (True, True, "BLEED", False), dict(r)
    import overseer
    line = overseer.death_words({"name": 'Goden Akrulvutok "Tinfigure", Stonecrafter', "cause": "BLEED",
                                 "again": True, "x": 84, "y": 143, "z": 167})
    assert "laid to rest: died before" in line and "bleed" not in line, line


# --- 4. the brain -------------------------------------------------------------------------

def state(killers=None, squads=None, expel=True, **extra):
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    if killers is not None:
        base["killers"] = killers
    if squads is not None:
        base.setdefault("military", {})["squads"] = squads
    if not expel:
        base.setdefault("settings", {})["expel_vampires"] = False
    base.update(extra)
    return normalize(base)


SQUAD = {"id": 40, "name": "The Axes", "members": 5, "power": {"armed": 5}}


def run(s, memory=None):
    props, notes = [], []
    PK._killer_rule(s, dict(PLANNER_CONFIG), props, notes, memory)
    return props, notes


def row(**kw):
    r = {"id": 3, "name": "Murd", "kind": "killer", "confidence": "strong", "citizen": True, "kills": 2,
         "victims": ["A", "B"], "seen_ticks": 2000}
    r.update(kw)
    return r


@test("brain: weak is a note only; strong but first seen is a note; strong and held is a cell")
def _():
    p, n = run(state({"list": [row(confidence="weak", kills=0, brawls=1)], "cells": [], "rooms": 2}))
    assert p == [] and "watched" in n[0], n
    p, n = run(state({"list": [row(seen_ticks=100)], "cells": [], "rooms": 2}))
    assert p == [] and "first seen" in n[0] and "killed 2 of the fort's own (A, B)" in n[0], n
    p, n = run(state({"list": [row()], "cells": [], "rooms": 2}))
    assert [(x.rule, x.action) for x in p] == [("killer", {"type": "killer_cell", "units": [3]})], p
    assert "locks them in a cell" in n[0]


@test("brain: a locked cell is said, not proposed again; a stale cell is let out; no room is said")
def _():
    p, n = run(state({"list": [row(cell={"locked": True})], "cells": [{"unit_id": 3, "locked": True}], "rooms": 0}))
    assert p == [] and "locked in a cell by the AI" in n[0], (p, n)
    p, n = run(state({"list": [], "cells": [{"unit_id": 3, "locked": True}], "rooms": 1}))
    assert [x.action for x in p] == [{"type": "killer_cell", "units": []}] and "no longer needed" in p[0].reason
    p, n = run(state({"list": [row()], "cells": [], "rooms": 0}))
    assert p == [] and any("no jail zone or free bedroom" in x for x in n), n


@test("brain: the berserk, a werebeast, a child and the sheriff are notes only")
def _():
    for r, words in ((row(berserk=True), "military rules"),
                     (row(kind="werebeast", confidence="certain", kills=0), "moon cells"),
                     (row(child=True), "a child"),
                     (row(law=True), "sheriff")):
        p, n = run(state({"list": [r], "cells": [], "rooms": 2}, squads=[SQUAD]))
        assert p == [] and words in n[0], (r, n)


@test("brain: a vampire citizen is sent away first (Rules), a squad after a week; a resident vampire gets the squad")
def _():
    v = row(id=1, name="Vamp", kind="vampire", confidence="certain", kills=0, tags=["BLOODSUCKER"])
    p, n = run(state({"list": [v], "cells": [], "rooms": 2}, squads=[SQUAD]))
    assert p == [] and "sends them away" in n[0], n
    v["seen_ticks"] = 8 * DAY
    p, n = run(state({"list": [v], "cells": [], "rooms": 2}, squads=[SQUAD]))
    assert [x.action for x in p] == [{"type": "squad_orders", "squad_id": 40, "kill": [1]}] and p[0].guard, p
    r = dict(v, seen_ticks=1000, citizen=None, resident=True)
    p, n = run(state({"list": [r], "cells": [], "rooms": 2}, squads=[SQUAD]))
    assert [x.action for x in p] == [{"type": "squad_orders", "squad_id": 40, "kill": [1]}], p
    assert "a resident, who can't be sent away" in p[0].reason


@test("brain: a vampire's own squad is not sent; no squad able: a cell; the switch off: kept, in a cell; just sent: a note")
def _():
    v = row(id=1, name="Vamp", kind="vampire", confidence="certain", kills=0, citizen=None, resident=True,
            squad_id=40)
    p, n = run(state({"list": [v], "cells": [], "rooms": 2}, squads=[SQUAD]))
    assert [x.action for x in p] == [{"type": "killer_cell", "units": [1]}] and "no squad" in n[0], (p, n)
    v2 = row(id=1, name="Vamp", kind="vampire", confidence="certain", kills=0)
    p, n = run(state({"list": [v2], "cells": [], "rooms": 2}, squads=[SQUAD], expel=False))
    assert [x.action for x in p] == [{"type": "killer_cell", "units": [1]}] and "keeps them" in n[0], (p, n)
    s = state({"list": [dict(v, squad_id=None)], "cells": [], "rooms": 2}, squads=[SQUAD])
    m = Memory()
    from planner_core import abs_tick
    m.kill_sent, m.kill_sent_at = {"40": [1]}, {"40": abs_tick(s)}
    p, n = run(s, m)
    assert p == [] and "a squad was sent" in n[0], (p, n)


@test("brain: plan() carries the rule: a strong murderer gets a cell proposal through the planner")
def _():
    s = state({"list": [row()], "cells": [], "rooms": 2})
    props, notes = plan(s, Memory())
    assert [x.action for x in props if x.rule == "killer"] == [{"type": "killer_cell", "units": [3]}], \
        [x.rule for x in props]
    assert any("may be a murderer" in x for x in notes)


@test("brain: without the killers section nothing is said or proposed; the fixtures hold none")
def _():
    p, n = run(state())
    assert p == [] and n == []
    for path in [ROOT / "tests" / "fixtures" / "test_fort.json"] + sorted((ROOT / "tests" / "fixtures" / "real").glob("*.json")):
        assert "killers" not in json.loads(path.read_text(encoding="utf-8")), path.name


@test("evidence words: kills, brawls, drained blood, DF's crimes, the curse")
def _():
    w = PK.evidence_words({"kills": 1, "brawls": 2, "victims": ["A"], "drained": True,
                           "crimes": {"Murder": 1}, "tags": ["BLOODSUCKER"]})
    assert w == ("killed 1 of the fort's own (A); 2 died after a fight or a beating with them; a victim drained of "
                 "blood; DF holds 1 Murder against them; curse: BLOODSUCKER"), w
    assert PK.evidence_words({}) == "the game's own curse flag"


if LuaRuntime is None:
    finish("these tests need the lupa package (pip install lupa)")
finish()
