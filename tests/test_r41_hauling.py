"""(0.105.40 M5) Hauling balanced: lua/ai-hauling.lua in a fake fort (the
haul jobs by labour and their waiting age, the haulers, the idle who don't
haul, the key workers who do; haulers added to the AI's own detail, never
the game's or yours; key workers relieved through the AI's detail or a
specialist mark it remembers, and given back; your undoing respected), the
bridge's wiring, and the brain (brain/planner_hauling.py: a stalled backlog
brings more haulers, key workers relieved while there are enough others,
nothing while balanced, a Haulers detail set to nobody left alone, and plan()
without a hauling section the same as main's on every fixture).

    python tests/test_r41_hauling.py
"""

from __future__ import annotations

import atexit
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
import planner_hauling as PH  # noqa: E402
import digest  # noqa: E402
import overseer  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
DAY = 1200

FAKE = r"""
local src = ...
local W = {site = {}, units = {}, citizens = {}, jobs = {}}
local env = setmetatable({}, {__index = _G})

local function both(t)
    local out = {}
    for k, v in pairs(t) do out[k] = v; out[v] = k end
    return out
end
local VEC = {}
-- DFHack's ipairs walks a game vector from 0
env.ipairs = function(t)
    if VEC[getmetatable(t) or 0] then
        return function(v, i) i = i + 1; local x = v[i]; if x ~= nil then return i, x end end, t, -1
    end
    return ipairs(t)
end
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    local mt = {
        __len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
        __index = {insert = function(self, at, v)
            local n = #self
            if at == '#' then at = n end
            for i = n, at + 1, -1 do self[i] = self[i - 1] end
            self[at] = v
        end,
        erase = function(self, at)
            local n = #self
            for i = at, n - 2 do self[i] = self[i + 1] end
            self[n - 1] = nil
        end}}
    VEC[mt] = true
    return setmetatable(t, mt)
end
W.vec = vec

local LAB = {HAUL_STONE = 1, HAUL_WOOD = 2, HAUL_BODY = 3, HAUL_FOOD = 4, HAUL_REFUSE = 5, HAUL_ITEM = 6,
             HAUL_FURNITURE = 7, HAUL_ANIMALS = 8, HAUL_TRADE = 9, HAUL_WATER = 10, MINE = 0, DIAGNOSE = 20,
             MASON = 21, PLANT = 22}
local UL = both(LAB)
local SK = both({MINING = 0, MASONRY = 5, DIAGNOSE = 6})
SK.attrs = {[0] = {labor = 0}, [5] = {labor = 21}, [6] = {labor = 20}}
local MODE = both({Default = 0, EverybodyDoesThis = 1, NobodyDoesThis = 2, OnlySelectedDoesThis = 3})
local ICON = both({NONE = -1, MINERS = 0, HAULERS = 8, CUSTOM_1 = 10})
W.LAB, W.MODE, W.ICON = LAB, MODE, ICON

-- details: {name, mode, icon, labors = {tokens}, members = {ids}, game = bool}
W.details = vec()
function W.detail(d)
    local allowed = {}
    for _, l in ipairs(d.labors or {}) do allowed[LAB[l]] = true end
    local wd = {name = d.name, flags = {mode = MODE[d.mode or 'OnlySelectedDoesThis'], no_modify = d.game == true},
                icon = ICON[d.icon or 'NONE'], allowed_labors = allowed, assigned_units = vec(d.members or {})}
    W.details:insert('#', wd)
    return wd
end
W.HAULS = {'HAUL_STONE', 'HAUL_WOOD', 'HAUL_BODY', 'HAUL_FOOD', 'HAUL_REFUSE', 'HAUL_ITEM', 'HAUL_FURNITURE',
           'HAUL_ANIMALS', 'HAUL_TRADE', 'HAUL_WATER'}

-- the game works a dwarf's labours out from the details (the fake's recompute)
function W.recompute(u)
    for _, l in pairs(LAB) do u.status.labors[l] = u.direct[l] or false end
    for i = 0, #W.details - 1 do
        local d = W.details[i]
        local m = MODE[d.flags.mode]
        local member = false
        for j = 0, #d.assigned_units - 1 do if d.assigned_units[j] == u.id then member = true end end
        if (m == 'EverybodyDoesThis' and not u.flags4.only_do_assigned_jobs)
                or ((m == 'OnlySelectedDoesThis' or m == 'Default') and member) then
            for l, yes in pairs(d.allowed_labors) do if yes then u.status.labors[l] = true end end
        end
    end
end

-- units: {id, skills = {{token, rating}}, busy, squad, child, mood, posts = {..}, offices = {..}, specialist, hurt}
function W.unit(t)
    local skills = {}
    for _, s in ipairs(t.skills or {}) do table.insert(skills, {id = SK[s[1]], rating = s[2]}) end
    local occ = {}
    for _, p in ipairs(t.posts or {}) do table.insert(occ, {type = p}) end
    local nobles = {}
    for _, o in ipairs(t.offices or {}) do table.insert(nobles, {position = {code = o}}) end
    local direct = {}
    for _, l in ipairs(t.direct or {}) do direct[LAB[l]] = true end
    local u = {id = t.id, child = t.child, military = {squad_id = t.squad or -1}, direct = direct,
               status = {labors = {}, current_soul = {skills = vec(skills)}},
               job = {current_job = t.busy and {} or nil}, mood = t.mood or -1,
               flags4 = {only_do_assigned_jobs = t.specialist == true}, occupations = vec(occ), nobles = nobles,
               health = t.hurt and {flags = {needs_healthcare = true}} or nil}
    table.insert(W.units, u)
    table.insert(W.citizens, u)
    W.recompute(u)
    return u
end
function W.recompute_all() for _, u in ipairs(W.units) do W.recompute(u) end end

-- jobs: {type, worker, suspend, item = {id, kind, unit_inside}, subtype}
function W.job(t)
    local items = vec()
    if t.item then
        local it = {id = t.item.id, kind = t.item.kind, refs = t.item.unit_inside and {CONTAINS_UNIT = {}} or {}}
        it.getType = function(self) return self.kind end
        items:insert('#', {item = it})
    end
    local j = {id = #W.jobs + 1, job_type = env.df.job_type[t.type or 'StoreItemInStockpile'],
               flags = {suspend = t.suspend == true}, worker = t.worker, items = items,
               item_subtype = t.subtype and LAB[t.subtype] or -1}
    table.insert(W.jobs, j)
    local head = {}
    local last = head
    for _, x in ipairs(W.jobs) do last.next = {item = x}; last = last.next end
    env.df.global.world.jobs.list.next = head.next
    return j
end
function W.clear_jobs() W.jobs = {}; env.df.global.world.jobs.list.next = nil end

local JT = both({StoreItemInStockpile = 1, BringItemToDepot = 2, ConstructBuilding = 3, DumpItem = 4})
JT.attrs = {[1] = {type = 3, labor = -1}, [2] = {type = 3, labor = LAB.HAUL_TRADE},
            [3] = {type = 2, labor = -1}, [4] = {type = 3, labor = LAB.HAUL_REFUSE}}

env.df = {
    global = {cur_year = 100, cur_year_tick = 0, world = {jobs = {list = {next = nil}}},
              plotinfo = {labor_info = {work_details = W.details}}},
    unit_labor = UL, job_skill = SK, work_detail_mode = MODE, work_detail_icon_type = ICON,
    job_type = JT, job_type_class = {Misc = 0, Building = 2, Hauling = 3},
    mood_type = both({Fey = 0, Secretive = 1, Possessed = 2, Macabre = 3, Fell = 4, Melancholy = 5}),
    occupation_type = both({DOCTOR = 0, TAVERN_KEEPER = 1, SCRIBE = 2, PERFORMER = 3}),
    item_type = setmetatable({}, {__index = function(_, k) return k end}),
    general_ref_type = {CONTAINS_UNIT = 'CONTAINS_UNIT'},
    unit = {find = function(id) for _, u in ipairs(W.units) do if u.id == id then return u end end end},
    work_detail = {new = function() return {name = '', flags = {mode = 0, no_modify = false}, icon = -1,
                                             allowed_labors = {}, assigned_units = vec()} end},
}
env.df.global.plotinfo.labor_info.work_details = W.details
env.dfhack = {
    units = {getCitizens = function() return W.citizens end, isChild = function(u) return u.child == true end,
             isBaby = function() return false end, isDead = function() return false end,
             getReadableName = function(u) return 'Urist ' .. u.id end,
             getNoblePositions = function(u) return u.nobles end},
    job = {getWorker = function(j) return j.worker end},
    items = {getGeneralRef = function(it, t) return it.refs[t] end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
assert(load(src, 'ai-hauling', 't', env))()
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-hauling.lua"))
    members.lua = lua
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


HAULS = ["HAUL_STONE", "HAUL_WOOD", "HAUL_BODY", "HAUL_FOOD", "HAUL_REFUSE", "HAUL_ITEM", "HAUL_FURNITURE",
         "HAUL_ANIMALS", "HAUL_TRADE", "HAUL_WATER"]


def fort(lua, w, mode="OnlySelectedDoesThis", members=(1, 2)):
    """The game's Haulers detail (mode, members), the Miners, a player's own
    'Stone crew' detail carrying stone hauling; ten dwarves:
    1, 2: haulers (busy); 3, 4, 5: idle, no hauling (5 a skilled mason);
    6: a doctor (post) on the Haulers detail; 7: the manager; 8: a soldier;
    9: a child; 10: idle, a specialist you made."""
    game = w.detail(T(lua, {"name": "Haulers", "mode": mode, "icon": "HAULERS", "labors": HAULS,
                            "members": list(members) + [6, 7], "game": True}))
    w.detail(T(lua, {"name": "Miners", "icon": "MINERS", "labors": ["MINE"], "members": [3], "game": True}))
    yours = w.detail(T(lua, {"name": "Stone crew", "icon": "CUSTOM_1", "labors": ["HAUL_STONE"], "members": [2]}))
    w.unit(T(lua, {"id": 1, "busy": True}))
    w.unit(T(lua, {"id": 2, "busy": True}))
    w.unit(T(lua, {"id": 3, "skills": [["MINING", 2]]}))
    w.unit(T(lua, {"id": 4}))
    w.unit(T(lua, {"id": 5, "skills": [["MASONRY", 8]]}))
    w.unit(T(lua, {"id": 6, "posts": [0], "busy": True}))
    w.unit(T(lua, {"id": 7, "offices": ["MANAGER"], "busy": True}))
    w.unit(T(lua, {"id": 8, "squad": 3}))
    w.unit(T(lua, {"id": 9, "child": True}))
    w.unit(T(lua, {"id": 10, "specialist": True}))
    return game, yours


def n(lua, v) -> int:
    """#v in Lua (the fake's vectors count from 0, with __len)."""
    return lua.eval("function(v) return #v end")(v)


def members(d):
    lua = members.lua
    return [d.assigned_units[i] for i in range(n(lua, d.assigned_units))]


def labors(env, u):
    return sorted(k for k in HAULS if u.status.labors[env.df.unit_labor[k]] is True)


# --- 1. pure parts --------------------------------------------------------------------------

@test("lua pure: an item's hauling labour (stone, wood, food, refuse, furniture, a caged animal, the rest items); "
      "a job's own labour and the stockpile job's subtype first")
def _():
    lua, env, w = world()
    for kind, want in (("BOULDER", "HAUL_STONE"), ("WOOD", "HAUL_WOOD"), ("MEAT", "HAUL_FOOD"),
                       ("REMAINS", "HAUL_REFUSE"), ("CORPSE", "HAUL_BODY"), ("BED", "HAUL_FURNITURE"),
                       ("BAR", "HAUL_ITEM"), ("CAGE", "HAUL_FURNITURE")):
        assert env.item_haul(kind) == want, kind
    assert env.item_haul("CAGE", True) == "HAUL_ANIMALS"
    assert env.haul_labor_of("HAUL_TRADE", "HAUL_FOOD", "BOULDER") == "HAUL_TRADE"
    assert env.haul_labor_of(None, "HAUL_FOOD", "BOULDER") == "HAUL_FOOD"
    assert env.haul_labor_of(None, None, "BOULDER") == "HAUL_STONE"
    assert env.haul_labor_of("MINE", None, None) == "HAUL_ITEM"


@test("lua pure: haulers picked least-skilled first (ties to the lower id); key workers relieved in order "
      "(a mood, the chief medical dwarf, doctors, offices, posts, the legendary)")
def _():
    lua, env, w = world()
    got = py(env.pick_haulers(T(lua, [{"id": 9, "best": 5}, {"id": 4, "best": 0}, {"id": 2, "best": 0},
                                      {"id": 7, "best": 2}]), 3))
    assert [c["id"] for c in got] == [2, 4, 7], got
    got = py(env.order_specialists(T(lua, [{"id": 1, "why": "legendary"}, {"id": 2, "why": "manager"},
                                           {"id": 3, "why": "doctor"}, {"id": 4, "why": "mood"},
                                           {"id": 5, "why": "tavern keeper"}])))
    assert [c["id"] for c in got] == [4, 3, 2, 5, 1], got


# --- 2. the report ---------------------------------------------------------------------------

@test("lua report: haul jobs by labour (the job's own, the stockpile subtype, the item), waiting and taken, "
      "suspended and other jobs left out; the waiting age follows the item across a re-made job")
def _():
    lua, env, w = world()
    fort(lua, w)
    w.job(T(lua, {"item": {"id": 501, "kind": "BOULDER"}}))
    w.job(T(lua, {"item": {"id": 502, "kind": "BOULDER"}}))
    w.job(T(lua, {"item": {"id": 503, "kind": "MEAT"}, "worker": {}}))
    w.job(T(lua, {"item": {"id": 504, "kind": "BAR"}, "subtype": "HAUL_FOOD"}))
    w.job(T(lua, {"type": "BringItemToDepot", "item": {"id": 505, "kind": "BAR"}}))
    w.job(T(lua, {"item": {"id": 506, "kind": "WOOD"}, "suspend": True}))
    w.job(T(lua, {"type": "ConstructBuilding"}))
    r = py(env.report())
    b = r["backlog"]
    assert b["waiting"] == 4 and b["taken"] == 1 and b["oldest_days"] == 0, b
    assert b["by"]["HAUL_STONE"]["waiting"] == 2 and b["by"]["HAUL_FOOD"]["waiting"] == 1, b
    assert b["by"]["HAUL_FOOD"]["taken"] == 1 and b["by"]["HAUL_TRADE"]["waiting"] == 1, b
    assert "HAUL_WOOD" not in b["by"] or b["by"]["HAUL_WOOD"]["waiting"] == 0, b
    # three days on, the game deleted and re-made the stockpile job for item 501: still 3 days old
    env.df["global"].cur_year_tick = 3 * DAY
    w.clear_jobs()
    w.job(T(lua, {"item": {"id": 501, "kind": "BOULDER"}}))
    w.job(T(lua, {"item": {"id": 507, "kind": "BOULDER"}}))
    b = py(env.report())["backlog"]
    assert b["waiting"] == 2 and b["oldest_days"] == 3 and b["old"] == 1, b
    assert b["by"]["HAUL_STONE"]["oldest_days"] == 3, b


@test("lua report: haulers (soldiers and children not counted), idle ones, the idle who don't haul (no "
      "specialist you made, no key worker), the key workers who haul and through what; the details")
def _():
    lua, env, w = world()
    fort(lua, w)
    r = py(env.report())
    h = r["haulers"]
    assert h["civilians"] == 8 and h["any"] == 4 and h["idle_any"] == 0, h      # 1, 2, 6, 7 haul
    assert h["candidates"] == 3, h                    # 3, 4, 5 (a skilled mason, not legendary)
    assert h["player_specialists"] == 1, h
    sp = {x["id"]: x for x in h["specialists"]}
    assert set(sp) == {6, 7} and sp[6]["why"] == "doctor" and sp[7]["why"] == "manager", sp
    assert sp[6]["via"] == "yours" and sp[7]["via"] == "yours", sp     # the Haulers detail is only-selected: yours
    assert h["relievable"] == 0, h
    assert r["detail"] == {"name": "Haulers", "mode": "OnlySelectedDoesThis", "members": 4}, r["detail"]
    assert r["other_details"] == 1 and "ai_detail" not in r, r


# --- 3. the actions ------------------------------------------------------------------------

@test("lua add_haulers: idle civilians who don't haul put on the AI's own detail (made once, only selected, "
      "the ten labours), least skilled first; the game's Haulers and your own detail untouched; a dry run changes nothing")
def _():
    lua, env, w = world()
    game, yours = fort(lua, w)
    before = (members(game), members(yours), int(game.flags.mode), int(yours.flags.mode))
    r = py(env.add_haulers(1, True))
    assert r["ok"] and r["dry_run"] and r["made"] and r["added"] == ["Urist 4"], r
    assert n(lua, w.details) == 3 and w.site["ai-overseer/hauling"] is None
    r = py(env.add_haulers(5, False))
    assert r["ok"] and r["added"] == ["Urist 4", "Urist 3", "Urist 5"], r
    assert n(lua, w.details) == 4
    mine = w.details[3]
    assert mine.name == "AI haulers" and int(mine.flags.mode) == 3, mine.name
    assert members(mine) == [3, 4, 5], members(mine)
    assert all(mine.allowed_labors[env.df.unit_labor[k]] for k in HAULS)
    assert (members(game), members(yours), int(game.flags.mode), int(yours.flags.mode)) == before
    # the game agrees: the dwarves' labours worked out from the details are what the AI set
    u4 = env.df.unit.find(4)
    assert labors(env, u4) == sorted(HAULS)
    w.recompute_all()
    assert labors(env, u4) == sorted(HAULS)
    assert env.df.unit.find(10).status.labors[1] is False      # your specialist: never made a hauler
    assert env.df.unit.find(8).status.labors[1] is False       # the soldier
    # no one left: refused, no second detail
    r = py(env.add_haulers(5, False))
    assert not r["ok"] and r["rejected"], r
    assert n(lua, w.details) == 4


@test("lua add_haulers: a Haulers detail at nobody (your choice) refused; the AI's detail removed or set to "
      "everybody by you: yours, never made again")
def _():
    lua, env, w = world()
    fort(lua, w, mode="NobodyDoesThis")
    r = py(env.add_haulers(2, False))
    assert not r["ok"] and r["rejected"] and "nobody" in r["error"], r
    assert n(lua, w.details) == 3
    lua, env, w = world()
    fort(lua, w)
    assert py(env.add_haulers(1, False))["ok"]
    lua.eval("function(v) v:erase(3) end")(w.details)    # you delete the AI's detail
    r = py(env.add_haulers(1, False))
    assert not r["ok"] and r["rejected"], r
    assert n(lua, w.details) == 3 and w.site["ai-overseer/hauling"].gone
    lua, env, w = world()
    fort(lua, w)
    assert py(env.add_haulers(1, False))["ok"]
    w.details[3].flags.mode = 1                          # you set it to everybody
    r = py(env.add_haulers(1, False))
    assert not r["ok"] and r["rejected"] and "yours" in r["error"], r
    assert int(w.details[3].flags.mode) == 1


@test("lua relieve_haulers: at 'everybody', key workers made specialists (remembered) and off hauling, labours "
      "given straight to a post kept; one you set back is yours; back gives hauling back")
def _():
    lua, env, w = world()
    game, yours = fort(lua, w, mode="EverybodyDoesThis")
    doc = env.df.unit.find(6)
    doc.direct[20] = True                                 # DIAGNOSE given straight (staff_labors)
    w.recompute_all()
    assert labors(env, doc) == sorted(HAULS)
    h = py(env.report())["haulers"]
    sp = {x["id"]: x["via"] for x in h["specialists"]}
    assert sp == {6: "everybody", 7: "everybody"} and h["relievable"] == 2, h
    gm = members(game)
    r = py(env.relieve_haulers(1, False, True))
    assert r["ok"] and r["dry_run"] and r["relieved"] == ["Urist 6 (doctor)"], r
    assert doc.flags4.only_do_assigned_jobs is False
    r = py(env.relieve_haulers(5, False, False))
    assert r["ok"] and len(r["relieved"]) == 2, r
    assert doc.flags4.only_do_assigned_jobs is True and labors(env, doc) == []
    assert doc.status.labors[20] is True                  # the post's labour stays
    assert members(game) == gm and int(game.flags.mode) == 1
    w.recompute_all()
    assert labors(env, doc) == []                          # the game agrees
    h = py(env.report())["haulers"]
    assert h["relieved"] == 2 and h["relievable"] == 0 and h["player_specialists"] == 1, h
    # you set the manager back to hauling yourself: yours, never relieved again
    mgr = env.df.unit.find(7)
    mgr.flags4.only_do_assigned_jobs = False
    w.recompute_all()
    r = py(env.relieve_haulers(5, False, False))
    assert not r["ok"], r
    assert mgr.flags4.only_do_assigned_jobs is False
    assert w.site["ai-overseer/hauling"].yours["7"]
    # back: the doctor hauls again
    r = py(env.relieve_haulers(2, True, False))
    assert r["ok"] and r["back"] == ["Urist 6"], r
    assert doc.flags4.only_do_assigned_jobs is False and labors(env, doc) == sorted(HAULS)


@test("lua relieve_haulers: a key worker on the AI's own detail taken off it; one hauling through your own "
      "detail left alone")
def _():
    lua, env, w = world()
    game, yours = fort(lua, w, members=(1,))
    assert py(env.add_haulers(2, False))["ok"]           # 4 and 3 on the AI's detail
    mine = w.details[3]
    u3 = env.df.unit.find(3)
    lua.eval("function(v, x) v:insert('#', x) end")(u3.occupations, T(lua, {"type": 1}))   # 3: the tavern keeper
    u2 = env.df.unit.find(2)                             # 2: on your Stone crew
    h = py(env.report())["haulers"]
    sp = {x["id"]: x["via"] for x in h["specialists"]}
    assert sp[3] == "ai" and sp[6] == "yours", sp
    r = py(env.relieve_haulers(5, False, False))
    assert r["ok"] and r["relieved"] == ["Urist 3 (tavern keeper)"], r
    assert 3 not in members(mine) and labors(env, u3) == []
    assert members(yours) == [2] and "HAUL_STONE" in labors(env, u2)


# --- 4. the bridge's wiring --------------------------------------------------------------------

@test("bridge: the hauling section (safe), the two actions on ACTIONS and DRY_OK, the module listed, the "
      "handlers' counts checked; the brain's labels and the section's default")
def _():
    hub = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    acts = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    assert "hauling = function() return safe(function() return reqscript('ai-hauling').report(txt) end) end" in hub
    assert "add_haulers = act_add_haulers" in hub and "relieve_haulers = act_relieve_haulers" in hub
    assert "'add_haulers', 'relieve_haulers'," in hub and "'ai-hauling'," in hub
    assert "function act_add_haulers(a)" in acts and "int_in(a.count, 1, 10)" in acts
    assert "function act_relieve_haulers(a)" in acts and "int_in(a.count, 1, 5)" in acts
    assert "add_haulers" in overseer.SHORT_WORDS and "relieve_haulers" in overseer.SHORT_WORDS
    assert digest.SECTION_DEFAULTS["hauling"] == {}


# --- 5. the brain ---------------------------------------------------------------------------

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG


def section(waiting=0, oldest=0, any_=10, idle_any=0, civilians=40, candidates=0, relievable=0, relieved=0,
            stale=0, mode="EverybodyDoesThis", specialists=None, **extra) -> dict:
    h = {"backlog": {"waiting": waiting, "taken": 3, "old": waiting if oldest else 0, "oldest_days": oldest,
                     "by": {"HAUL_STONE": {"waiting": waiting, "taken": 3, "oldest_days": oldest}}},
         "haulers": {"civilians": civilians, "idle": idle_any, "any": any_, "idle_any": idle_any,
                     "candidates": candidates, "player_specialists": 0, "by": {}, "relievable": relievable,
                     "relieved": relieved, "relieved_stale": stale, "specialists": specialists or []},
         "detail": {"name": "Haulers", "mode": mode, "members": 0}, "other_details": 0}
    h.update(extra)
    return h


def mine(h) -> tuple[list, list]:
    s = copy.deepcopy(BASE)
    s["hauling"] = h
    props, notes = [], []
    PH._hauling_labor_rule(s, CFG, 40, props, notes)
    return props, notes


@test("brain: a stalled backlog (many waiting, a day old, no hauler idle) with too few haulers: idle "
      "non-haulers added, capped a call; the more jobs, the more haulers wanted")
def _():
    assert PH.haulers_wanted(40, 0, CFG) == 6 and PH.haulers_wanted(40, 160, CFG) == 20
    assert PH.haulers_wanted(40, 10000, CFG) == 24            # at most 60%
    props, _ = mine(section(waiting=160, oldest=2, any_=8, candidates=12, mode="OnlySelectedDoesThis"))
    assert [p.rule for p in props] == ["hauling_add"], props
    assert props[0].action == {"type": "add_haulers", "count": CFG["hauling_add_max"]}
    props, _ = mine(section(waiting=160, oldest=2, any_=18, candidates=12, mode="OnlySelectedDoesThis"))
    assert props[0].action["count"] == 2, props                # 20 wanted, 18 have
    props, _ = mine(section(waiting=160, oldest=2, any_=8, candidates=1))
    assert props[0].action["count"] == 1                      # only one to add
    # nobody to add, the AI relieved some: given back
    props, _ = mine(section(waiting=160, oldest=2, any_=8, candidates=0, relieved=3))
    assert [p.rule for p in props] == ["hauling_back"] and props[0].action == {
        "type": "relieve_haulers", "count": 2, "back": True}, props


@test("brain: key workers relieved while there are enough others and nothing stalls; none while short, "
      "stalled or within the margin; the no-longer-key given back")
def _():
    sp = [{"id": 6, "name": "Urist", "why": "doctor", "via": "everybody"},
          {"id": 7, "name": "Bomrek", "why": "manager", "via": "yours"}]
    props, _ = mine(section(waiting=10, oldest=0, any_=30, relievable=1, specialists=sp))
    assert [p.rule for p in props] == ["hauling_relieve"], props
    assert props[0].action == {"type": "relieve_haulers", "count": 1} and "Urist (doctor)" in props[0].reason
    assert "Bomrek" not in props[0].reason
    props, _ = mine(section(waiting=10, any_=7, relievable=1, specialists=sp))     # 6 wanted + 2 margin
    assert props == [], props
    props, _ = mine(section(waiting=160, oldest=3, any_=30, relievable=3, specialists=sp))   # stalled
    assert props == [], props
    props, _ = mine(section(waiting=10, any_=30, relievable=0, relieved=2, stale=1))
    assert [p.rule for p in props] == ["hauling_back"] and props[0].action["count"] == 1, props


@test("brain: balanced (enough haulers, or one idle, or a young backlog): no change; a Haulers detail at "
      "nobody: said, no hauler added; no or a failed section: nothing")
def _():
    for h in (section(waiting=160, oldest=2, any_=20, candidates=5),       # enough
              section(waiting=160, oldest=2, any_=8, idle_any=1, candidates=5),   # a hauler is free
              section(waiting=160, oldest=0, any_=8, candidates=5),        # not a day old
              section(waiting=10, oldest=5, any_=8, candidates=5)):        # few
        props, notes = mine(h)
        assert props == [] and notes == [], (h, props)
    props, notes = mine(section(waiting=160, oldest=2, any_=8, candidates=5, mode="NobodyDoesThis"))
    assert props == [] and notes and "nobody" in notes[0], notes
    props, _ = mine(section(waiting=160, oldest=2, any_=8, candidates=5, ai_detail_gone=True))
    assert props == [], props
    for h in ({}, {"error": "boom"}, {"backlog": {"error": "x"}, "haulers": {}}, None):
        s = copy.deepcopy(BASE)
        if h is not None:
            s["hauling"] = h
        props, notes = [], []
        PH._hauling_labor_rule(s, CFG, 40, props, notes)
        assert props == [] and notes == [], h
        assert PH.hauling_line(s) == ""


@test("brain: plan() carries the rule (registered); its cooldowns are in the config; the digest line")
def _():
    s = copy.deepcopy(BASE)
    s["hauling"] = section(waiting=300, oldest=3, any_=2, candidates=4, civilians=max(1, s["dwarves"]["total"]),
                           mode="OnlySelectedDoesThis")
    props, _ = plan(s, Memory())
    assert any(p.rule == "hauling_add" and p.action["type"] == "add_haulers" for p in props), \
        [p.rule for p in props]
    for r in ("hauling_add", "hauling_relieve", "hauling_back"):
        assert f"{r}_cooldown_ticks" in CFG, r
    line = PH.hauling_line(s)
    assert line.startswith("HAULING waiting 300") and "stone 300" in line, line
    assert digest.hauling_line(s) == line


# --- scripts identity: without a hauling section, plan() is main's ---------------------------

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
        tmp = tempfile.mkdtemp(prefix="r41-main-")
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


@test("no hauling section in the report: plan() and note_cycle() are main's, byte for byte (every fixture, "
      "slow and not, 3 cycles)")
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
