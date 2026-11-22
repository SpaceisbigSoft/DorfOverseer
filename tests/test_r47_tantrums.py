"""(0.105.47, R2 item 3, 12i) Tantrums one dwarf at a time (I7c): the ledger
and the section (lua/ai-tantrums.lua) in a fake fort; can_staff refusing the
very unhappy and recent tantrum-throwers (lua/ai-society.lua); a hospital
kept off the stairs (lua/ai-builder-sites.lua); the death event's conflict
marked; the bridge's wiring; and the brain (brain/planner_tantrums.py, the
crisis triggers, the hospital burrow's priority, the guards left alone by the
recall).

    python tests/test_r47_tantrums.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src, bridge_part_src, split_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
import planner  # noqa: E402
from planner import Memory, PLANNER_CONFIG, plan, select, note_cycle, abs_tick, TICKS_PER_DAY  # noqa: E402
import planner_tantrums as PT  # noqa: E402
import crisis  # noqa: E402
from digest import SECTION_DEFAULTS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime  # noqa: E402
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

LUA_DIR = ROOT / "lua"
DAY = 1200
YEAR = 403200
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = dict(PLANNER_CONFIG)


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


# --- lua/ai-tantrums.lua in a fake fort ------------------------------------------

FAKE = r"""
local src = ...
local W = {units = {}, site = {}, squads = {}, fort_squads = {}, hfs = {}, zones = {}, vacated = {}, stations = {},
           nowalk = {}}
local env = setmetatable({}, {__index = _G})
local real = ipairs
local function vec(l)
    local t = {_v = true}
    for i, v in real(l or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
        __index = {insert = function(self, at, v) self[#self] = v end,
                   erase = function(self, at) local n = #self; for i = at, n - 2 do self[i] = self[i + 1] end; self[n - 1] = nil end}})
end
W.vec = vec
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, '_v') then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return real(t)
end
function W.unit(t)
    t.mood = t.mood or -1
    t.cat = t.cat or 4
    t.counters = t.counters or {soldier_mood = -1}
    t.military = t.military or {squad_id = -1}
    t.occupations = vec(t.posts or {})
    t.status = t.status or {labors = {}, current_soul = {personality = {needs = vec(t.needs or {})}}}
    t.owned_buildings = vec(t.owned or {})
    t.body = t.body or {blood_count = 100, blood_max = 100}
    table.insert(W.units, t)
    return t
end
function W.squad(id, members, extra)
    local pos = {}
    for _, uid in real(members) do
        W.hfs[1000 + uid] = {unit_id = uid}
        table.insert(pos, {occupant = 1000 + uid})
    end
    local sq = {id = id, positions = vec(pos), orders = vec({})}
    for k, v in pairs(extra or {}) do sq[k] = v end
    W.squads[id] = sq
    table.insert(W.fort_squads, id)
    return sq
end
env.df = {
    global = {cur_year = 300, cur_year_tick = 1000, plotinfo = {group_id = 1}},
    soldier_mood_type = {[-1] = 'None', [0] = 'MartialTrance', [1] = 'Enraged', [2] = 'Tantrum', [3] = 'Depressed'},
    mood_type = {[3] = 'Possessed', [7] = 'Berserk'},
    occupation_type = {[2] = 'TAVERN_KEEPER', [7] = 'DIAGNOSTICIAN', [8] = 'DOCTOR'},
    unit_labor = {DIAGNOSE = 1, SURGERY = 2, BONE_SETTING = 3, SUTURING = 4, DRESSING_WOUNDS = 5},
    need_type = {[1] = 'EatGoodMeal', [2] = 'CraftObject', [3] = 'BeWithFriends', [4] = 'MartialTraining'},
    building_civzonest = {is_instance = function(_, b) return b.civzone == true end},
    civzone_type = {[1] = 'Bedroom'},
    squad = {find = function(id) return W.squads[id] end},
    historical_figure = {find = function(id) return W.hfs[id] end},
    historical_entity = {find = function() return {squads = vec(W.fort_squads)} end},
    unit = {find = function(id) for _, u in real(W.units) do if u.id == id then return u end end end},
}
env.dfhack = {
    units = {getCitizens = function() return W.units end,
             getStressCategory = function(u) return u.cat end,
             getReadableName = function(u) return u.name or ('dwarf ' .. u.id) end},
    maps = {getWalkableGroup = function(p) return W.nowalk[p.x .. ',' .. p.y] and 0 or 1 end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
local M = {STATION_KEY = 'ai-overseer/station'}
function M.ai_order(o) return o.ai == true end
function M.members_state(sq) return {parched = sq.parched} end
function M.station_of(o) return o.st end
function M.fort_squad(id) return W.squads[id] end
function M.station_marks() return W.site['ai-overseer/station'] or {} end
function M.station(sid, x, y, z, dry)
    table.insert(W.stations, {sid = sid, x = x, y = y, z = z, dry = dry})
    if not dry then
        local sq = W.squads[sid]
        sq.orders:insert('#', {ai = true, st = {x = x, y = y, z = z}})
        local m = M.station_marks(); m[tostring(sid)] = {x = x, y = y, z = z}; W.site['ai-overseer/station'] = m
    end
    return {ok = true, dry_run = dry or nil, x = x, y = y, z = z}
end
function M.drop_orders(sq, pick)
    local n = 0
    for i = #sq.orders - 1, 0, -1 do if pick(sq.orders[i]) then sq.orders:erase(i); n = n + 1 end end
    return n
end
env.reqscript = function(name)
    if name == 'ai-military' then return M end
    if name == 'ai-society-burrows' then return {hospital_zones = function() return W.zones, {} end} end
    if name == 'ai-society' then
        return {vacate_post = function(loc, uid, dry)
            table.insert(W.vacated, {loc = loc, uid = uid, dry = dry})
            return {ok = true, post = 'doctor'}
        end}
    end
    error('no module ' .. tostring(name))
end
assert(load(src, 'ai-tantrums', 't', env))()
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-tantrums.lua"))
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


def advance(env, ticks):
    g = env.df["global"]
    g.cur_year_tick = g.cur_year_tick + ticks


def tantrum(u, on=True):
    u.counters.soldier_mood = 2 if on else -1


@test("ledger: a tantrum is written once however many reports it lasts; a new one after calm; a year kept; future ticks dropped")
def _():
    lua, env, w = world()
    u = w.unit(T(lua, {"id": 1, "name": "Goden"}))
    w.unit(T(lua, {"id": 2, "name": "Calm"}))
    tantrum(u)
    r = py(env.report())
    assert r["loose"] == 1 and len(r["dwarves"]) == 1, r
    row = r["dwarves"][0]
    assert row["id"] == 1 and row["now"] is True and row["n28"] == 1 and row["year"] == 1, row
    for _ in range(5):
        advance(env, 100)
        env.report()
    assert py(env.report())["dwarves"][0]["year"] == 1          # one tantrum over many reports
    tantrum(u, False)
    advance(env, 600)
    r = py(env.report())
    assert r["loose"] == 0 and "now" not in r["dwarves"][0], r
    advance(env, 2 * DAY)
    tantrum(u)
    r = py(env.report())
    assert r["dwarves"][0]["year"] == 2 and r["dwarves"][0]["n28"] == 2
    # a flicker (calm a moment, then again within EPISODE_GAP) is the same tantrum
    tantrum(u, False); advance(env, 50); env.report()
    tantrum(u); advance(env, 50)
    assert py(env.report())["dwarves"][0]["year"] == 2
    # past 28 days: n28 drops, the year keeps them; past a year: gone
    tantrum(u, False)
    advance(env, 30 * DAY)
    row = py(env.report())["dwarves"][0]
    assert row["n28"] == 0 and row["year"] == 2, row
    advance(env, YEAR)
    assert not py(env.report())["dwarves"] and not py(w.site["ai-overseer/tantrums"]["units"])
    # an older save loaded: a tick after now is dropped
    w.site["ai-overseer/tantrums"] = T(lua, {"units": {"1": {"t": [10 ** 9]}}})
    assert not py(env.report())["dwarves"]


@test("row: posts, hospital labours on, the worst unmet needs, own bedroom, squad; sorted in a tantrum first, then the most")
def _():
    lua, env, w = world()
    a = w.unit(T(lua, {"id": 1, "name": "A", "cat": 0,
                       "posts": [{"location_id": 3, "type": 8}, {"location_id": 9, "type": 2}],
                       "needs": [{"id": 1, "focus_level": -20000}, {"id": 2, "focus_level": -5000},
                                 {"id": 3, "focus_level": 300}]}))
    a.status.labors[1] = True
    a.status.labors[4] = True
    b = w.unit(T(lua, {"id": 2, "name": "B", "owned": [{"civzone": True, "type": 1}]}))
    now = 300 * YEAR + 1000
    w.site["ai-overseer/tantrums"] = T(lua, {"units": {"1": {"t": [now - 40 * DAY, now - 20 * DAY, now - 2 * DAY]},
                                                       "2": {"t": [now - 3 * DAY]}}})
    tantrum(b)
    r = py(env.report())
    assert [x["id"] for x in r["dwarves"]] == [2, 1], r["dwarves"]           # in a tantrum first
    ra = r["dwarves"][1]
    assert ra["year"] == 3 and ra["n28"] == 2 and ra["stress"] == "miserable", ra
    assert ra["posts"] == [{"location_id": 3, "post": "DOCTOR"}, {"location_id": 9, "post": "TAVERN_KEEPER"}], ra
    assert ra["medical"] == ["DIAGNOSE", "SUTURING"] and ra["unmet"] == ["EatGoodMeal", "CraftObject"], ra
    assert ra["bedroom"] is False and r["dwarves"][0]["bedroom"] is True
    assert r["chronic"] == 1 and r["chronic_at"] == 3


@test("staff_refusal: very unhappy or worse, in a tantrum, one in 28 days, or 3+ this year; a calm dwarf may")
def _():
    lua, env, w = world()
    u = w.unit(T(lua, {"id": 1, "cat": 1}))
    assert env.staff_refusal(u) == "very unhappy"
    u.cat = 0
    assert env.staff_refusal(u) == "miserable"
    u.cat = 3
    assert env.staff_refusal(u) is None
    tantrum(u)
    assert env.staff_refusal(u) == "in a tantrum"
    env.report()
    tantrum(u, False)
    assert "28 days" in env.staff_refusal(u)
    advance(env, 29 * DAY)
    assert env.staff_refusal(u) is None
    now = 300 * YEAR + 1000 + 29 * DAY
    w.site["ai-overseer/tantrums"] = T(lua, {"units": {"1": {"t": [now - 200 * DAY, now - 100 * DAY, now - 40 * DAY]}}})
    assert "3+" in env.staff_refusal(u)


@test("kill_kind: berserk, possessed, in a tantrum or one begun in the last 2 days; else nothing")
def _():
    lua, env, w = world()
    k = w.unit(T(lua, {"id": 5}))
    assert env.kill_kind(k) is None
    k.mood = 7
    assert env.kill_kind(k) == "berserk"
    k.mood = 3
    assert env.kill_kind(k) == "possessed"
    k.mood = -1
    tantrum(k)
    assert env.kill_kind(k) == "tantrum"
    env.report()
    tantrum(k, False)
    advance(env, DAY)
    assert env.kill_kind(k) == "tantrum"
    advance(env, 2 * DAY)
    assert env.kill_kind(k) is None


@test("squads and hospitals read only while a tantrum is loose (or a guard stands): calm, wounded, thirsty, orders; a tile to stand on")
def _():
    lua, env, w = world()
    for i, cat in ((1, 4), (2, 3), (3, 1), (4, 4)):
        w.unit(T(lua, {"id": i, "cat": cat}))
    w.squad(10, T(lua, [1, 2]))
    w.squad(11, T(lua, [3, 4]))
    w.squad(12, T(lua, [4]), T(lua, {"parched": 1}))
    lua.execute("local sq = ...; sq.orders:insert('#', {ai = false})", w.squads[12])
    w.zones[1] = T(lua, {"id": 50, "x1": 10, "x2": 14, "y1": 10, "y2": 12, "z": 100})
    w.nowalk["12,11"] = True
    q = py(env.report())
    assert q.get("quiet") is True and not q["squads"] and not q["hospitals"], q     # nothing loose: not read
    tantrum(w.unit(T(lua, {"id": 5})))
    r = py(env.report())
    sq = {q["id"]: q for q in r["squads"]}
    assert sq[10].get("calm") is True and sq[10]["members"] == 2 and sq[10]["worst"] == "fine", sq[10]
    assert "calm" not in sq[11] and sq[11]["worst"] == "very_unhappy"
    assert sq[12]["parched"] == 1 and sq[12]["player_orders"] == 1 and sq[12]["ai_orders"] == 0
    assert r["hospitals"] == [{"zone_id": 50, "x": 10, "y": 10, "z": 100}], r["hospitals"]   # the middle can't be stood on


@test("guard: a squad stationed in the hospital zone, marked; the mark dropped once the order is gone; unguard clears both")
def _():
    lua, env, w = world()
    w.unit(T(lua, {"id": 1}))
    w.squad(10, T(lua, [1]))
    w.zones[1] = T(lua, {"id": 50, "x1": 10, "x2": 14, "y1": 10, "y2": 12, "z": 100})
    d = py(env.guard(10, 50, True))
    assert d["ok"] and d["zone_id"] == 50 and "ai-overseer/hospital-guard" not in w.site, d
    assert not py(env.guard(10, 99, False))["ok"]
    r = py(env.guard(10, 50, False))
    assert r["ok"] and (r["x"], r["y"], r["z"]) == (12, 11, 100), r
    rep = py(env.report())
    assert rep["guards"] == [{"squad_id": 10, "zone_id": 50, "x": 12, "y": 11, "z": 100, "since": 300 * YEAR + 1000}], rep
    assert rep["squads"][0]["guarding"] == 50
    u = py(env.unguard(10, False))
    assert u["ok"] and u["removed"] == 1 and len(w.squads[10].orders) == 0, u
    assert not py(w.site["ai-overseer/hospital-guard"]) and not py(w.site["ai-overseer/station"])
    assert not py(env.unguard(10, False))["ok"]
    env.guard(10, 50, False)
    lua.execute("local sq = ...; sq.orders:erase(0)", w.squads[10])   # the military rules gave it another order
    assert not py(env.report())["guards"] and not py(w.site["ai-overseer/hospital-guard"])


@test("step_down: every post vacated and the hospital labours off; a dry run changes nothing; nothing held: refused")
def _():
    lua, env, w = world()
    u = w.unit(T(lua, {"id": 1, "posts": [{"location_id": 3, "type": 8}]}))
    u.status.labors[2] = True
    d = py(env.step_down(1, True, True))
    assert d["ok"] and d["dry_run"] and d["labors"] == ["SURGERY"] and u.status.labors[2] is True, d
    r = py(env.step_down(1, True, False))
    assert r["ok"] and r["posts"] == ["doctor"] and r["labors"] == ["SURGERY"] and u.status.labors[2] is False, r
    assert py(w.vacated)[-1] == {"loc": 3, "uid": 1, "dry": False}
    w.unit(T(lua, {"id": 2}))
    assert not py(env.step_down(2, True, False))["ok"]
    assert not py(env.step_down(77, True, False))["ok"]


@test("(r9, audit A7 #22) step_down: the hospital labours off through the work details (ai-labor take_labors)")
def _():
    lua, env, w = world()
    u = w.unit(T(lua, {"id": 1}))
    u.status.labors[2] = True
    u.status.labors[4] = True
    lua.execute("""local env, W = ...
        local real = env.reqscript
        W.taken = {}
        env.reqscript = function(name)
            if name == 'ai-labor' then
                return {take_labors = function(u, tokens)
                    for _, t in ipairs(tokens) do table.insert(W.taken, t); u.status.labors[env.df.unit_labor[t]] = false end
                    return tokens
                end}
            end
            return real(name)
        end""", env, w)
    r = py(env.step_down(1, True, False))
    assert r["ok"] and r["labors"] == ["SURGERY", "SUTURING"] and py(w.taken) == ["SURGERY", "SUTURING"], (r, py(w.taken))
    assert u.status.labors[2] is False and u.status.labors[4] is False


# --- can_staff (lua/ai-society.lua) --------------------------------------------------

STAFF_FAKE = r"""
local src, T = ...
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
local post = {id = 70, type = 8, histfig_id = -1, unit_id = -1}
local hosp = {id = 3, occupations = vec({post})}
local function unit(id, skill, cat)
    return {id = id, hist_figure_id = 100 + id, skill = skill, cat = cat, military = {squad_id = -1}, mood = -1,
            occupations = vec(), status = {labors = {}}}
end
local units = {unit(1, 15, 0), unit(2, 0, 4), unit(3, 8, 4)}
env.UNITS, env.POST = units, post
env.df = {occupation_type = {[8] = 'DOCTOR'}, job_skill = {DRESS_WOUNDS = 1, DIAGNOSE = 2, SURGERY = 3, SET_BONE = 4, SUTURE = 5},
          unit_labor = {}}
env.dfhack = {world = {getCurrentSite = function() return {buildings = vec({hosp})} end},
              units = {getCitizens = function() return units end, isAdult = function() return true end,
                       getNominalSkill = function(u) return u.skill end,
                       getStressCategory = function(u) return u.cat end,
                       getNoblePositions = function() return nil end,
                       getReadableName = function(u) return 'dwarf ' .. u.id end},
              persistent = {getSiteData = function(_, d) return d end}}
env.reqscript = function(name) if name == 'ai-tantrums' and T then return T end return {} end
env.require = function() return {} end
assert(load(src, 'ai-society', 't', env))()
return env
"""


@test("can_staff: the miserable skilled dwarf and a recent tantrum-thrower are passed over for a calm one")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    tl = lua.eval("{load = function() return {units = {}} end, "
                  "staff_refusal = function(u, d) if u.id == 3 and d then return 'a tantrum in the last 28 days' end end}")
    env = lua.execute(STAFF_FAKE, module_src("ai-society.lua"), tl)
    d = env.staff_location(3, "DOCTOR", True)
    assert d.ok and d.unit_id == 2 and d.skill == 0, dict(d)     # 1 miserable (skill 15), 3 a tantrum lately (8)
    # without the tantrum ledger the stress still bars: the skilled tantrum-thrower 3 then
    env2 = lua.execute(STAFF_FAKE, module_src("ai-society.lua"), None)
    d = env2.staff_location(3, "DOCTOR", True)
    assert d.ok and d.unit_id == 3, dict(d)
    lua.execute("local env = ...; for _, u in ipairs(env.UNITS) do u.cat = 1 end", env)
    r = env.staff_location(3, "DOCTOR", False)
    assert not r.ok and "very unhappy" in r.error and env.POST.unit_id == -1, dict(r)


# --- the hospital off the stairs (lua/ai-builder-sites.lua) ----------------------------

SITES = (LUA_DIR / "ai-builder-sites.lua").read_text(encoding="utf-8")


@test("stair gap: a hospital level keeps HOSPITAL_STAIR_GAP from its stair and the main stair; other levels unchecked")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    fns = "\n".join(re.search(rf"\nfunction {n}\(.*?\nend\n", SITES, re.S).group(0) for n in ("stair_gap", "stair_gap_ok"))
    gap = re.search(r"\nHOSPITAL_STAIR_GAP = (\d+)", SITES).group(1)
    lua.execute(f"HOSPITAL_STAIR_GAP = {gap}\n" + fns)
    g = lua.globals()
    L = lua.eval("{tiles = {[0] = {[0] = true, [1] = true}, [3] = {[0] = true}}}")
    assert g.stair_gap(L, 100, 100, 100, 95) == 5                  # (100,100) to y95
    assert g.stair_gap(L, 100, 100, 110, 100) == 7
    st = lua.eval("{{x = 104, y = 100}}")
    assert g.stair_gap_ok(L, 100, 100, st) is True                  # no gap asked: any level
    L.stair_gap = int(gap)
    ok, why = g.stair_gap_ok(L, 100, 100, st)
    assert ok is False and "keeps 6 tiles from the stairs" in why, why
    assert g.stair_gap_ok(L, 90, 100, st) is True                   # 11 away
    ok, _ = g.stair_gap_ok(L, 90, 100, lua.eval("{{x = 104, y = 100}, {x = 94, y = 101}}"))
    assert ok is False                                              # the main stair too


@test("stair gap wired: a hospital is never centred on a stair; beside one, checked; start_project marks hospitals")
def _():
    assert "if ok and L.stair_gap then ok, why = false, 'a hospital is not centred on the stairs' end" in SITES
    assert "ok, why = stair_gap_ok(L, ax, ay, {stair, L.main_stair})" in SITES
    proj = __import__("lua_modules_util").builder_part_src("ai-builder-projects")   # (r8) the part and the files split off it
    assert re.search(r"if kind == 'hospital' then\s+L\.stair_gap = HOSPITAL_STAIR_GAP\s+L\.main_stair = stairs\[1\]", proj)


def builder():
    """lua/ai-builder.lua on tests/test_builder.py's fake fort map (its HARNESS, read from that file)."""
    import ast
    tree = ast.parse((ROOT / "tests" / "test_builder.py").read_text(encoding="utf-8"))
    harness = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                   and any(getattr(t, "id", None) == "HARNESS" for t in n.targets))
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(ROOT / "lua")
    B, W = lua.execute(harness, (LUA_DIR / "ai-layouts.lua").read_text(encoding="utf-8"),
                       (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8"))
    return lua, B, W


@test("stair gap in the builder: a hospital goes beside the stair, its nearest tile 6+ from it; a bedroom level still centred")
def _():
    lua, B, W = builder()
    W.reset()
    B.TRY_BESIDE = True
    when = lua.table_from({"year": 148, "tick": 100})
    r = B.start_project(lua.table_from({"kind": "hospital", "beds": 8, "urgent": True}), when)
    assert r.ok, r.error
    p = W.persist["ai-overseer/projects"].list[1]
    a, st = p.anchor, p.stair
    res = lua.globals().LAYOUTS.make("hospital", lua.table_from({"beds": 8, "urgent": True}))
    L = res[0] if isinstance(res, tuple) else res
    assert B.stair_gap(L, a.x, a.y, st.x, st.y) >= B.HOSPITAL_STAIR_GAP == 6, B.stair_gap(L, a.x, a.y, st.x, st.y)
    assert (a.x, a.y) != (st.x, st.y), "a hospital centred on the stair"
    W.reset()
    B.TRY_BESIDE = False
    r = B.start_project(lua.table_from({"kind": "hospital", "beds": 8, "urgent": True}), when)
    assert not r.ok and "a hospital is not centred on the stairs" in r.error, r.error
    r = B.start_project(lua.table_from({"kind": "bedrooms", "rooms": 8, "room_size": 3}), when)
    assert r.ok, r.error


# --- the bridge's wiring --------------------------------------------------------------

BRIDGE = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")


@test("bridge: the tantrums section (safe, in the pulse), the two actions (dry runs ok), the module listed; digest default")
def _():
    need_lua()
    # (r5 p5) the loaded hub's tables and a stand-in ai-tantrums (tests/bridge_behaviour.py), not its text
    import bridge_behaviour as BB
    acts = ["hospital_guard", "tantrum_step_down"]
    BB.wired(section="tantrums", module="ai-tantrums", txt=True, pulse=True, actions=acts, dry=acts,
             modules=["ai-tantrums"])
    assert SECTION_DEFAULTS.get("tantrums") == {}
    import overseer
    assert "hospital_guard" in overseer.SHORT_WORDS and "tantrum_step_down" in overseer.SHORT_WORDS


@test("bridge: convict takes unit_id (that culprit's cases only); the death event marks a tantrum's or berserker's kill")
def _():
    acts = bridge_part_src("ai-bridge-actions")
    assert "(only == nil or c.criminal == only)" in acts and "no solved case of that culprit" in acts
    rep = bridge_part_src("ai-bridge-report")
    assert "reqscript('ai-tantrums').kill_kind(k, abs_tick())" in rep
    assert "ev.conflict = kind:sub(1, 1):upper() .. kind:sub(2)" in rep and "ev.killer_x" in rep
    soc = split_src("ai-society.lua")   # (r8 s3) the hub and its parts
    assert "if okc and type(cat) == 'number' and cat <= 1 then return false end" in soc


# --- the brain -----------------------------------------------------------------------

NOW_DAY = None


def with_section(s, **sec):
    base = {"loose": 0, "berserk": 0, "possessed": 0, "dwarves": [], "chronic": 0, "hospitals": [], "squads": [],
            "guards": []}
    base.update(sec)
    s["tantrums"] = base
    return s


def row(s, uid, name, year, n28=0, now=False, posts=(), medical=None, unmet=(), bedroom=True, hurt=None, ticks=None):
    t = abs_tick(s)
    ticks = ticks if ticks is not None else [t - (i + 1) * 10 * DAY for i in range(year)][::-1]
    r = {"id": uid, "name": name, "year": year, "n28": n28, "posts": list(posts), "unmet": list(unmet),
         "bedroom": bedroom, "ticks": ticks, "last": ticks[-1] if ticks else None, "stress": "miserable"}
    if now:
        r["now"] = True
    if medical:
        r["medical"] = medical
    if hurt:
        r["hurt"] = True
    return r


@test("loyalty fix before the first death: on a tantrum, berserk or possession report, or a tantrum loose; never with enemies about")
def _():
    s = fort()
    m = Memory()
    assert not by_rule(plan(copy.deepcopy(s), m)[0], "break_fights")
    n = PT.note_tantrum_book(s, m, [{"kind": "report", "topic": "insanity", "type": "BERSERK_CITIZEN",
                                     "text": "Urist has gone berserk!"},
                                    {"kind": "report", "topic": "tantrum", "text": "Urist cancels Clean: Throwing tantrum."}])
    assert n == 1 and m.tantrum_book["breaks"] == [abs_tick(s)]
    b = by_rule(plan(copy.deepcopy(s), m)[0], "break_fights")
    assert len(b) == 1 and b[0].priority == 0 and "before someone dies" in b[0].reason, b
    later = copy.deepcopy(s)
    later["date"]["tick"] += PLANNER_CONFIG["break_fights_report_ticks"]
    assert not by_rule(plan(later, m)[0], "break_fights")
    # a possession report; a tantrum announced (memory.tantrums); a tantrum loose by the section
    m2 = Memory()
    PT.note_tantrum_book(s, m2, [{"kind": "report", "topic": "mood", "type": "POSSESSED_MOOD", "text": "x"}])
    assert by_rule(plan(copy.deepcopy(s), m2)[0], "break_fights")
    m3 = Memory()
    m3.tantrums = [[abs_tick(s) - 10, "Urist"]]
    assert by_rule(plan(copy.deepcopy(s), m3)[0], "break_fights")
    loose = with_section(fort(), loose=1)
    assert by_rule(plan(loose, Memory())[0], "break_fights")
    war = with_section(fort(), loose=1)
    war["others_on_map"]["threats"] = [{"id": 5, "invader": True, "can_reach_dwarves": False}]
    assert not by_rule(plan(war, Memory())[0], "break_fights")
    # with a death too: one proposal, not two
    import crisis as C
    m4 = Memory()
    C.note_deaths(s, m4, [{"kind": "death", "own_civ": True, "killer_kind": "citizen", "conflict": "Tantrum"}])
    assert len(m4.fight_deaths) == 1
    assert len(by_rule(plan(with_section(fort(), loose=1), m4)[0], "break_fights")) == 1
    assert planner.LOOP_LIMITS["break_fights"] == 400


@test("posts: taken from a holder with a tantrum in 28 days or in one now (one a cycle); a chronic case left to its own rule")
def _():
    s = with_section(fort())
    s["tantrums"]["dwarves"] = [row(s, 7, "Mebzuth", 1, n28=1, posts=[{"location_id": 9, "post": "TAVERN_KEEPER"},
                                                                      {"location_id": 3, "post": "DOCTOR"}])]
    p = by_rule(plan(s, Memory())[0], "staff_tantrum")
    assert len(p) == 1 and p[0].action == {"type": "vacate_post", "location_id": 9, "unit_id": 7}, p
    assert "tavern keeper" in p[0].reason and p[0].priority == 1
    old = copy.deepcopy(s); old["tantrums"]["dwarves"][0]["n28"] = 0
    assert not by_rule(plan(old, Memory())[0], "staff_tantrum")
    old["tantrums"]["dwarves"][0]["now"] = True
    assert by_rule(plan(old, Memory())[0], "staff_tantrum")
    chronic = copy.deepcopy(s); chronic["tantrums"]["dwarves"][0]["year"] = 3
    assert not by_rule(plan(chronic, Memory())[0], "staff_tantrum")
    assert by_rule(plan(chronic, Memory())[0], "chronic_posts")


def guard_fort(loose=1, guards=(), **sq):
    s = with_section(fort(), loose=loose)
    s["tantrums"]["hospitals"] = [{"zone_id": 50, "x": 10, "y": 10, "z": 100}, {"zone_id": 51, "x": 30, "y": 30, "z": 101}]
    s["tantrums"]["squads"] = [dict({"id": 20, "members": 4, "calm": True, "ai_orders": 0, "player_orders": 0}, **sq),
                               {"id": 21, "members": 8, "ai_orders": 0, "player_orders": 0},           # not calm
                               {"id": 22, "members": 2, "calm": True, "ai_orders": 1, "player_orders": 0}]  # busy
    s["tantrums"]["guards"] = list(guards)
    s["others_on_map"]["threats"] = []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    return s


@test("hospital guard: a tantrum loose -> the calm free squad to a hospital not yet guarded; none free: said; enemies: none")
def _():
    s = guard_fort()
    p = by_rule(plan(s, Memory())[0], "hospital_guard")
    assert len(p) == 1 and p[0].action == {"type": "hospital_guard", "squad_id": 20, "zone_id": 50}, p
    one = guard_fort(guards=[{"squad_id": 20, "zone_id": 50, "since": abs_tick(s)}])
    one["tantrums"]["squads"].append({"id": 23, "members": 3, "calm": True, "ai_orders": 0, "player_orders": 0})
    p = by_rule(plan(one, Memory())[0], "hospital_guard")
    assert p and p[0].action == {"type": "hospital_guard", "squad_id": 23, "zone_id": 51}, p
    none_ = guard_fort(wounded=1)
    props, notes = plan(none_, Memory())
    assert not by_rule(props, "hospital_guard") and any("no calm squad free" in n for n in notes), notes
    war = guard_fort()
    war["others_on_map"]["threats"] = [{"id": 5, "invader": True, "can_reach_dwarves": True}]
    assert not by_rule(plan(war, Memory())[0], "hospital_guard")
    assert not by_rule(plan(guard_fort(loose=0), Memory())[0], "hospital_guard")


@test("hospital guard: kept a day after the last tantrum loose; then off; off too after a week or with thirsty soldiers")
def _():
    s = guard_fort(loose=0, guards=[{"squad_id": 20, "zone_id": 50, "since": None}])
    m = Memory()
    m.tantrum_book = {"loose_last": abs_tick(s) - 600}
    assert not by_rule(plan(copy.deepcopy(s), m)[0], "hospital_guard")
    m.tantrum_book = {"loose_last": abs_tick(s) - 1300}
    p = by_rule(plan(copy.deepcopy(s), m)[0], "hospital_guard")
    assert p and p[0].action == {"type": "hospital_guard", "squad_id": 20, "release": True}, p
    assert "no tantrum loose" in p[0].reason
    long = guard_fort(guards=[{"squad_id": 20, "zone_id": 50, "since": abs_tick(s) - 8 * DAY}])
    p = by_rule(plan(long, Memory())[0], "hospital_guard")
    assert p and p[0].action.get("release") and "7 days" in p[0].reason, p
    dry = guard_fort(guards=[{"squad_id": 20, "zone_id": 50, "since": abs_tick(s)}], parched=2)
    p = by_rule(plan(dry, Memory())[0], "hospital_guard")
    assert p and p[0].action.get("release") and "thirsty" in p[0].reason, p
    # bookkeeping: the last tick a tantrum was seen loose
    m2 = Memory()
    PT.note_tantrum_book(guard_fort(loose=2), m2, [])
    assert m2.tantrum_book["loose_last"] == abs_tick(s)


@test("hospital guard: the military's 'no more threats' recall leaves a guard squad alone")
def _():
    s = guard_fort(loose=1, guards=[{"squad_id": 20, "zone_id": 50, "since": None}])
    s["military"]["squads"] = [{"id": 20, "name": "Guards", "members": 4, "ai_orders": 1, "sheltering": True,
                                "stationed": {"x": 10, "y": 10, "z": 100}},
                               {"id": 21, "name": "Other", "members": 4, "ai_orders": 1}]
    rec = by_rule(plan(s, Memory())[0], "squad_recall")
    ids = {p.action.get("squad_id") for p in rec}
    assert 20 not in ids and 21 in ids, ids


@test("hospital burrow: raised for the fights only with a guard posted; a crisis alone still raises it")
def _():
    s = fort()
    s["health"] = {"hospital": [{"id": 5, "zones": [{"id": 70, "beds": 4}], "staff": []}],
                   "patients": [{"id": 1, "needs": ["suture"]}]}
    s.setdefault("society", {})["hospital_burrow"] = {"members": 0, "outside": 5, "hospital_zones": 1}
    m = Memory()
    m.fight_deaths = [abs_tick(s) - 10]
    r = by_rule(plan(with_section(copy.deepcopy(s)), m)[0], "hospital_burrow")
    assert r and r[0].priority == 4 and "no guard there yet" in r[0].reason, r
    g = with_section(copy.deepcopy(s), guards=[{"squad_id": 20, "zone_id": 70}])
    r = by_rule(plan(g, m)[0], "hospital_burrow")
    assert r and r[0].priority == 2 and "a squad on guard there" in r[0].reason, r
    mc = Memory(); mc.crisis = {"since": 0, "why": ["45% unhappy"]}
    r = by_rule(plan(with_section(copy.deepcopy(s)), mc)[0], "hospital_burrow")
    assert r and r[0].priority <= 0, r                                  # 2, then the crisis's -2
    loose = with_section(copy.deepcopy(s), loose=1)
    r = by_rule(plan(loose, mc)[0], "hospital_burrow")
    assert r and r[0].priority == 2 and "not hurried" in r[0].reason, r   # 4, then -2


def chronic_fort(**kw):
    s = with_section(fort())
    r = row(s, 9, "Goden", kw.pop("year", 3), posts=kw.pop("posts", [{"location_id": 3, "post": "DOCTOR"}]),
            medical=kw.pop("medical", ["SURGERY"]), unmet=kw.pop("unmet", ["MartialTraining", "EatGoodMeal",
                                                                             "CraftObject", "BeWithFriends"]),
            bedroom=kw.pop("bedroom", False), ticks=kw.pop("ticks", None), hurt=kw.pop("hurt", None))
    s["tantrums"]["dwarves"] = [r, row(s, 10, "Logem", 3)]
    s["tantrums"]["dwarves"][1]["last"] = r["last"] - 5
    s.setdefault("noble_rooms", {})["free"] = {"bedroom": 2}
    s.setdefault("needs", {})["trinkets"] = 4
    s.setdefault("locations", {})["list"] = [{"id": 4, "type": "INN_TAVERN", "zones": [77]}]
    return s


@test("chronic case (3+ a year, the worst first): off every post and the hospital work; their own needs met in turn")
def _():
    s = chronic_fort()
    props, notes = plan(s, Memory())
    p = by_rule(props, "chronic_posts")
    assert len(p) == 1 and p[0].action == {"type": "tantrum_step_down", "unit_id": 9, "medical": True}, p
    acts = PT.chronic_need_actions(s, CFG, s["tantrums"]["dwarves"][0])
    kinds = [a[1]["type"] for a in acts]
    assert "pair_chairs" in kinds and "give_room" in kinds, kinds
    assert all(a[0] != "MartialTraining" for a in acts)                       # the training squads' (J4)
    c = by_rule(props, "chronic_care")
    assert len(c) == 1 and c[0].action in [a[1] for a in acts] and "Goden" in c[0].reason, c
    seen = set()
    for d in range(len(acts)):
        s2 = copy.deepcopy(s); s2["date"]["tick"] += d * DAY
        seen.add(json.dumps(by_rule(plan(s2, Memory())[0], "chronic_care")[0].action, sort_keys=True))
    assert len(seen) == len(acts), seen                                        # each in turn, a day each
    n = [x for x in notes if x.startswith("chronic tantrum cases (2)")]
    assert n and "training (the training squads meet it)" in n[0] and "next: Logem" in n[0], notes
    assert not by_rule(props, "chronic_convict")
    # nothing held any more: no step down; under 3: not chronic
    s3 = chronic_fort(posts=[], medical=None)
    assert not by_rule(plan(s3, Memory())[0], "chronic_posts")
    s4 = chronic_fort(year=2)
    s4["tantrums"]["dwarves"] = s4["tantrums"]["dwarves"][:1]
    assert not by_rule(plan(s4, Memory())[0], "chronic_care")


@test("chronic case, the last resort: 5+ a year, 28+ days after the third: their own case convicted, only behind every check")
def _():
    s0 = fort()
    t = abs_tick(s0)
    ticks = [t - 120 * DAY, t - 90 * DAY, t - 60 * DAY, t - 20 * DAY, t - 2 * DAY]

    def ready(**kw):
        s = chronic_fort(year=5, ticks=ticks, **kw)
        s["dwarves"]["needs_medical_care"] = 0
        s["justice"] = {"restraints": 3, "restraints_used": 0, "punish": {"n": 0, "beatings": 0, "prison": 0}}
        s["offices"] = {"offices": {"SHERIFF": {"held": ["Sheriff"]}}}
        s["settings"]["traits"] = dict(s["settings"].get("traits") or {}, justice=0)
        return s

    p = by_rule(plan(ready(), Memory())[0], "chronic_convict")
    assert len(p) == 1 and p[0].action == {"type": "convict", "max": 1, "unit_id": 9, "disorderly": True}, p
    for change, word in ((lambda s: s["dwarves"].update(needs_medical_care=1), "someone is wounded"),
                         (lambda s: s["justice"]["punish"].update(beatings=1), "a beating waits"),
                         (lambda s: s["justice"].update(restraints_used=2), "no free jail chain"),
                         (lambda s: s["offices"].update(offices={}), "no sheriff"),
                         (lambda s: s["settings"]["traits"].update(justice=-60), "lenient"),
                         (lambda s: s["tantrums"]["dwarves"][0].update(hurt=True), "they are hurt")):
        s = ready(); change(s)
        props, notes = plan(s, Memory())
        assert not by_rule(props, "chronic_convict"), word
        assert any(word in n for n in notes if n.startswith("chronic")), (word, notes)
    early = ready(); early["tantrums"]["dwarves"][0]["ticks"] = [t - 20 * DAY, t - 15 * DAY, t - 10 * DAY, t - 5 * DAY, t]
    assert not by_rule(plan(early, Memory())[0], "chronic_convict")              # care tried under 28 days
    cfg = dict(CFG, chronic_convict_on=False)
    assert PT._convict_blockers(ready(), cfg, ready()["tantrums"]["dwarves"][0]) == ["switched off"]


@test("crisis: any citizen killed by a citizen; 2+ dwarves with 2+ tantrums in 28 days; held while a tantrum was seen in 14 days")
def _():
    s = fort()
    s["dwarves"]["total"] = 40          # (r9) the one-tantrum hold is a small fort's (crisis_tantrum_quiet_max_pop)
    s["dwarves"]["stress"] = {"content": s["dwarves"]["total"]}
    m = Memory()
    note_cycle(copy.deepcopy(s), m)
    assert not m.crisis
    crisis.note_deaths(s, m, [{"kind": "death", "own_civ": True, "killer_kind": "citizen", "conflict": "Tantrum"}])
    notes = note_cycle(copy.deepcopy(s), m)
    assert m.crisis.get("why") and "killed by citizens" in m.crisis["why"][0], m.crisis
    # small fort: two dwarves with two tantrums each (the announcements' names), far under 10
    m2 = Memory()
    t = abs_tick(s)
    m2.tantrums = [[t - 5 * DAY, "Goden"], [t - 3 * DAY, "Goden"], [t - 4 * DAY, "Logem"], [t - DAY, "Logem"],
                   [t - DAY, "Kol"]]
    note_cycle(copy.deepcopy(s), m2)
    assert m2.crisis.get("why") and "2 dwarves threw 2+ tantrums" in m2.crisis["why"][-1], m2.crisis
    m3 = Memory(); m3.tantrums = [[t - 5 * DAY, "Goden"], [t - 3 * DAY, "Goden"], [t - DAY, "Kol"]]
    note_cycle(copy.deepcopy(s), m3)
    assert not m3.crisis                                                     # one repeat thrower only
    # the ledger's counts (by id) count too
    sl = with_section(copy.deepcopy(s), dwarves=[{"id": 1, "name": "A", "n28": 2}, {"id": 2, "name": "B", "n28": 3}])
    m4 = Memory(); note_cycle(sl, m4)
    assert m4.crisis.get("why"), m4.crisis
    # held: 15 days later with no kill in 14 days and nobody repeating, a tantrum 5 days ago keeps it
    later = copy.deepcopy(s); later["date"]["tick"] += 15 * DAY
    m2.tantrums = [[abs_tick(later) - 5 * DAY, "Kol"]]
    note_cycle(copy.deepcopy(later), m2)
    assert m2.crisis.get("why") == ["a tantrum in the last 14 days"], m2.crisis
    m2.tantrums = []
    notes = note_cycle(copy.deepcopy(later), m2)
    assert not m2.crisis and any("crisis is over" in n for n in notes), m2.crisis


@test("crisis rules: calm burrow dropped (it never held a tantrum), the tantrum rules in; config and memory")
def _():
    assert "calm_burrow" not in crisis.RECOVERY_RULES
    assert {"staff_tantrum", "chronic_posts", "chronic_care", "hospital_guard"} <= crisis.RECOVERY_RULES
    assert "chronic_convict" not in crisis.RECOVERY_RULES                 # never pushed by a crisis
    for k in ("break_fights_report_ticks", "hospital_guard_hold_ticks", "chronic_tantrums", "crisis_kill_days",
              "crisis_repeat_dwarves", "crisis_repeat_tantrums", "crisis_tantrum_quiet_days", "chronic_convict_on"):
        assert k in PLANNER_CONFIG, k
    m = Memory(); m.tantrum_book = {"breaks": [1], "loose_last": 2}
    assert Memory.from_dict(m.to_dict()).tantrum_book == {"breaks": [1], "loose_last": 2}
    # an older bridge (no section): nothing but the report-driven fix
    s = fort()
    s.pop("tantrums", None)
    props, _ = plan(s, Memory())
    assert not [p for p in props if p.rule in ("staff_tantrum", "hospital_guard", "chronic_posts", "chronic_care")]


@test("death events: a 'Tantrum' or 'Berserk' kill is a fight death (the loyalty fix and the crisis see it)")
def _():
    s = fort()
    m = Memory()
    crisis.note_deaths(s, m, [{"kind": "death", "own_civ": True, "killer_kind": "citizen", "conflict": "Berserk"},
                              {"kind": "death", "own_civ": True, "killer_kind": "citizen", "conflict": "Training"}])
    assert len(m.fight_deaths) == 1


if __name__ == "__main__":
    finish()
