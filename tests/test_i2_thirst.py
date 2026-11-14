"""(0.105.46, I2) The thirst watch: lua/ai-thirst.lua in a fake fort (each
thirsty citizen's reason: insane, a strange mood, chained, jailed, the AI's
cell, stranded, on a Drink job, interrupted, the alarm's burrow, their own
burrow, forbidden drink, no path, no drink, injured; the last cancelled
Drink job matched by name; the snapshot in the save and a death of thirst
told with its place and last reason; unforbid_drink), the bridge's wiring,
and the brain (brain/planner_thirst.py: one remedy a reason, the existing
actions first, no double action, the pacing, the notes and the journal).

    python tests/test_i2_thirst.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, Proposal  # noqa: E402
import planner_thirst as PT  # noqa: E402
from planner_core import EMERGENCY, LIMIT_EXEMPT, STEER_PROTECTED  # noqa: E402
from digest import SECTION_DEFAULTS, normalize  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"

FAKE = r"""
local src = ...
local W = {cits = {}, units = {}, drinks = {}, wells = {}, zones = {}, gmap = {}, zgroup = {}, site = {},
           incidents = {}, punish = {}, cancels = {}, stranded = {}, cells = {}, burrows = {}, armed = false,
           alert_idx = 0, alerts = {}}
local env = setmetatable({}, {__index = _G})
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
local function k(x, y, z) return x .. ',' .. y .. ',' .. z end
function W.group(x, y, z) return W.gmap[k(x, y, z)] or W.zgroup[z] or 0 end
function W.unit(t)
    t.pos = t.pos or {x = 10, y = 10, z = 100}
    t.counters2 = t.counters2 or {thirst_timer = 0, hunger_timer = 0}
    t.counters = t.counters or {death_id = -1}
    t.mood = t.mood or -1
    t.flags1 = t.flags1 or {}
    t.job = t.job or {}
    t.military = t.military or {squad_id = -1}
    t.burrows = t.burrows or {}
    t.name = t.name or {full = t.nm or ('Dwarf ' .. t.id)}
    table.insert(W.units, t)
    if not t.is_dead and t.citizen ~= false then table.insert(W.cits, t) end
    return t
end
function W.drink(t)
    t.flags = t.flags or {}
    t.stack_size = t.stack_size or 1
    table.insert(W.drinks, t)
    return t
end
function W.kill(u, cause)
    u.is_dead = true
    for i, c in ipairs(W.cits) do if c == u then table.remove(W.cits, i) break end end
    W.incidents[#W.incidents + 1] = {death_cause = cause or 9}
    u.counters.death_id = #W.incidents
end
local function bld(t)
    t.getBuildStage = function() return 1 end
    t.getMaxBuildStage = function() return 1 end
    return t
end
function W.well(t) table.insert(W.wells, bld(t)) return t end
local plot = {punishments = W.punish, burrows = {list = W.burrows},
              alerts = setmetatable({list = W.alerts}, {__index = function(_, kk) if kk == 'civ_alert_idx' then return W.alert_idx end end})}
env.df = {
    global = {cur_year = 300, cur_year_tick = 0, plotinfo = plot,
              world = {units = {active = W.units}, items = {other = {DRINK = W.drinks}},
                       buildings = {other = {WELL = W.wells, ZONE_WATER_SOURCE = W.zones}}}},
    mood_type = {[0] = 'Fey', [5] = 'Melancholy'},
    job_type = {[1] = 'Drink', [2] = 'Eat'},
    death_type = {[9] = 'THIRST', [7] = 'STRUCK_DOWN'},
    unit = {find = function(id) for _, u in ipairs(W.units) do if u.id == id then return u end end end},
    incident = {find = function(id) return W.incidents[id] end},
}
env.dfhack = {
    df2utf = function(s) return s end,
    maps = {getWalkableGroup = function(p) return W.group(p.x, p.y, p.z) end},
    units = {getCitizens = function() local o = {} for i, u in ipairs(W.cits) do o[i] = u end return o end,
             isDead = function(u) return u.is_dead == true end,
             isDanger = function(u) return u.danger == true end,
             isInvader = function(u) return false end,
             getPosition = function(u) return u.pos.x, u.pos.y, u.pos.z end,
             getReadableName = function(u) return (u.name.full or '?') .. ', Miner' end},
    translation = {translateName = function(n) return n.full end},
    items = {getContainer = function(it) return it.container end,
             getHolderUnit = function(it) return it.holder end,
             getPosition = function(it)
                 local p = it.container and it.container.pos or it.pos
                 return p.x, p.y, p.z
             end},
    burrows = {isAssignedTile = function(b, p) return b.tiles[k(p.x, p.y, p.z)] == true end},
    persistent = {getSiteData = function(kk, d) local v = W.site[kk]; if v == nil then return d end return v end,
                  saveSiteData = function(kk, v) W.site[kk] = v; W.saves = (W.saves or 0) + 1 end},
}
local threats = {}
function threats.cancel_rows() return W.cancels end
function threats.parse_cancel(text)
    local who, job, why = text:match('^(.-) cancels ([^:]+): (.-)%.?%s*$')
    return who, job, why
end
function threats.interrupter_of(why)
    local who = why and why:match('^Interrupted by (.+)$')
    if not who then return nil end
    return (who:lower():gsub('^an? ', ''))
end
env.reqscript = function(name)
    if name == 'ai-threats' then return threats end
    if name == 'ai-gates' then
        return {stranded_citizens = function() return {list = W.stranded} end,
                GATES = setmetatable({}, {__index = function(_, kk) if kk == 'armed' then return W.armed end end})}
    end
    if name == 'ai-killers' then return {state = function() return {cells = W.cells} end} end
    error('no module ' .. tostring(name))
end
assert(load(src, 'ai-thirst', 't', env))()
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-thirst.lua"))
    w.zgroup[100] = 1
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


def dwarf(lua, w, uid, timer, **kw):
    kw.setdefault("counters2", {"thirst_timer": timer, "hunger_timer": 0})
    return w.unit(T(lua, dict(id=uid, **kw)))


def drink(lua, w, x=12, y=10, z=100, **kw):
    return w.drink(T(lua, dict(pos={"x": x, "y": y, "z": z}, **kw)))


def rows(env):
    r = py(env.report())
    return r, {x["id"]: x for x in r.get("list") or []}


def need_lua():
    if LuaRuntime is None:
        print("  (lupa missing: Lua part skipped)")
        return False
    return True


# --- 1. the classifier --------------------------------------------------------------------

@test("classify: each reason in its order (insane before jailed before stranded before path)")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    c = lambda **f: env.classify(T(lua, f))
    here = dict(drink_group=5)
    assert c(insane=True, jailed=True, **here) == "insane"
    assert c(mood=True, **here) == "mood"
    assert c(chained=True, jailed=True, **here) == "chained"
    assert c(jailed=True, stranded=True, **here) == "jailed"
    assert c(cell=True, **here) == "cell"
    assert c(stranded=True, **here) == "stranded"
    assert c(drinking=True, timer=30000, **here) == "drinking"
    assert c(drinking=True, timer=60000, cancel={"why": "x", "by": "human spearman"}, **here) == "interrupted"
    assert c(alert=True, alert_drink=False, **here) == "alert"
    assert c(alert=True, alert_drink=True, **here) == "unknown"
    assert c(burrows=1, burrow_drink=False, timer=30000, **here) == "burrow"
    assert c(burrows=1, burrow_drink=False, timer=60000, **here) == "unknown"     # DF lets them out once dehydrated
    assert c(forbidden_group=4) == "forbidden"
    assert c(drink_elsewhere=40) == "no_path"
    assert c(wells_elsewhere=1) == "no_path"
    assert c() == "no_drink"
    assert c(wells_group=1, patient=True) == "injured"
    assert c(cancel={"why": "Too injured"}, **here) == "injured"
    assert c(cancel={"why": "Could not find path"}, **here) == "no_path"
    assert c(cancel={"why": "Dangerous terrain"}, **here) == "cancelled"
    assert c(water_group=1) == "unknown"


# --- 2. the report -------------------------------------------------------------------------

@test("report: nobody thirsty, nothing read, no list; the quenched dwarf is left out")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    dwarf(lua, w, 1, 1000)
    dwarf(lua, w, 2, 24999)
    r, by = rows(env)
    assert r["thirsty"] == 0 and not by and r["new_deaths"] == 0, r


@test("report: B's 845 drinks beyond a gate (no path), forbidden drink, a well in reach, no drink at all")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    w.zgroup[90] = 2                     # the stores' level: another walk group
    for _ in range(3):
        drink(lua, w, 5, 5, 90, stack_size=5)
    d1 = dwarf(lua, w, 1, 40000)                                   # z100: group 1, drink only on 90
    w.zgroup[80] = 3
    drink(lua, w, 7, 7, 80, flags={"forbid": True}, stack_size=2)
    dwarf(lua, w, 2, 52000, pos={"x": 7, "y": 9, "z": 80})       # forbidden drink beside them
    w.zgroup[70] = 4
    w.well(T(lua, {"centerx": 3, "centery": 3, "z": 70}))
    dwarf(lua, w, 3, 30000, pos={"x": 9, "y": 9, "z": 70})       # a well in reach, nothing seen
    r, by = rows(env)
    assert r["thirsty"] == 3 and r["dehydrated"] == 1 and r["drink_total"] == 15 and r["drink_forbidden"] == 2, r
    assert by[1]["reason"] == "no_path" and by[1]["drink_group"] == 0 and by[1]["drink_elsewhere"] == 15, by[1]
    assert by[2]["reason"] == "forbidden" and by[2]["forbidden_group"] == 2, by[2]
    assert by[2]["nearest_forbidden"]["d"] == 2 and by[2]["level"] == "dehydrated"
    assert by[3]["reason"] == "unknown" and by[3]["wells_group"] == 1, by[3]
    assert [x["id"] for x in r["list"]] == [2, 1, 3]                 # the thirstiest first
    assert d1 is not None


@test("report: a barrel forbidden makes its drink forbidden; a drink carried by someone is no store")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    barrel = T(lua, {"flags": {"forbid": True}, "pos": {"x": 11, "y": 10, "z": 100}})
    drink(lua, w, container=barrel, flags={"in_inventory": True}, stack_size=3)
    drink(lua, w, holder=T(lua, {"id": 50}), flags={"in_inventory": True})
    dwarf(lua, w, 1, 30000)
    r, by = rows(env)
    assert by[1]["reason"] == "forbidden" and by[1]["forbidden_group"] == 3 and r["drink_total"] == 0, (r, by)


@test("report: insane, strange mood, chained, jailed, the AI's cell, stranded (with the gate's facts)")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    drink(lua, w, stack_size=50)
    dwarf(lua, w, 1, 40000, mood=5)
    dwarf(lua, w, 2, 40000, mood=0)
    dwarf(lua, w, 3, 40000, flags1={"chained": True})
    dwarf(lua, w, 4, 40000)
    w.punish[1] = T(lua, {"criminal": 4, "prison_counter": 30})
    dwarf(lua, w, 5, 40000)
    w.cells["5"] = T(lua, {"locked": True})
    dwarf(lua, w, 6, 40000)
    w.stranded[1] = T(lua, {"id": 6, "cause": "gate_shut", "out_days": 2, "stuck_gate": 77,
                            "entrance": {"id": 3}, "by_ai": True})
    r, by = rows(env)
    assert (by[1]["reason"], by[1]["insane"]) == ("insane", "melancholy"), by[1]
    assert (by[2]["reason"], by[2]["mood"]) == ("mood", "Fey"), by[2]
    assert by[3]["reason"] == "chained" and by[4]["reason"] == "jailed" and by[4]["jailed"] == 30
    assert by[5]["reason"] == "cell"
    assert by[6]["reason"] == "stranded" and by[6]["stranded"] == {"cause": "gate_shut", "out_days": 2, "stuck_gate": 77,
                                                                    "entrance_id": 3, "by_ai": True}, by[6]


@test("report: the last cancelled Drink matched by name (nickname, profession dropped); Interrupted names who")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    drink(lua, w, stack_size=50)
    dwarf(lua, w, 1, 40000, name={"full": 'Urist "Bolt" Likot'})
    dwarf(lua, w, 2, 40000, name={"full": "Domas Rith"})
    dwarf(lua, w, 3, 40000, name={"full": "Zon Ast"})
    w.cancels[1] = T(lua, {"text": "Urist Likot, Miner cancels Drink: Interrupted by a human spearman.", "n": 3,
                           "tick": 5})
    w.cancels[2] = T(lua, {"text": "Urist Likot, Miner cancels Drink: Too injured.", "n": 1})   # older
    w.cancels[3] = T(lua, {"text": "Domas Rith, Farmer cancels Drink: Dangerous terrain.", "n": 1})
    w.cancels[4] = T(lua, {"text": "Zon Ast, Farmer cancels Eat: Interrupted by a goblin.", "n": 1})
    r, by = rows(env)
    assert by[1]["reason"] == "interrupted" and by[1]["cancel"]["by"] == "human spearman", by[1]
    assert by[1]["cancel"]["n"] == 4 and by[1]["cancel"]["why"] == "Interrupted by a human spearman", by[1]
    assert by[2]["reason"] == "cancelled" and by[2]["cancel"]["why"] == "Dangerous terrain", by[2]
    assert by[3]["reason"] == "unknown" and by[3].get("cancel") is None, by[3]


@test("report: on a Drink job (thirsty) is fine; a patient with water only by the well is injured")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    drink(lua, w, stack_size=5)
    dwarf(lua, w, 1, 30000, job={"current_job": {"job_type": 1}})
    dwarf(lua, w, 2, 30000, health={"flags": {"needs_healthcare": True, "rq_immobilize": True}})
    r, by = rows(env)
    assert by[1]["reason"] == "drinking" and by[1]["job"] == "Drink"
    assert by[2]["reason"] == "injured" and by[2]["patient"] is True, by[2]


@test("report: a burrow without drink (the AI's or the player's), and the alarm's burrow without drink")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    drink(lua, w, 12, 10, 100, stack_size=5)
    w.burrows[1] = T(lua, {"id": 7, "name": "AI recreation", "tiles": {"1,1,100": True}})
    w.burrows[2] = T(lua, {"id": 8, "name": "Farmers", "tiles": {"12,10,100": True}})
    w.burrows[3] = T(lua, {"id": 9, "name": "AI shelter", "tiles": {"2,2,100": True}})
    dwarf(lua, w, 1, 30000, burrows=[7])
    dwarf(lua, w, 2, 30000, burrows=[8])
    r, by = rows(env)
    assert by[1]["reason"] == "burrow" and by[1]["burrow_ai"] is True, by[1]
    assert by[1]["burrows"] == [{"id": 7, "name": "AI recreation", "ai": True, "drink": False}], by[1]
    assert by[2]["reason"] == "unknown" and by[2]["burrows"][0]["drink"] is True, by[2]
    w.alert_idx = 1
    w.alerts[1] = T(lua, {"id": 1, "burrows": [9]})
    dwarf(lua, w, 3, 30000)
    dwarf(lua, w, 4, 30000, military={"squad_id": 5})                 # a soldier: not kept in by the alarm
    r, by = rows(env)
    assert r["alert"] is True and by[3]["reason"] == "alert" and by[3]["alert"] == {"drink": False}, by[3]
    assert by[4]["reason"] == "unknown" and by[4].get("alert") is None, by[4]


@test("report: the snapshot is kept in the save; a dwarf who drank leaves it; a death of thirst is told once")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    w.zgroup[90] = 2
    drink(lua, w, 5, 5, 90, stack_size=5)
    u1 = dwarf(lua, w, 1, 60000, name={"full": "Kib Dry"})
    u2 = dwarf(lua, w, 2, 30000)
    w.cancels[1] = T(lua, {"text": "Kib Dry, Miner cancels Drink: Could not find path.", "n": 1})
    rows(env)
    snap = py(w.site["ai-overseer/thirst"])["snap"]
    assert set(snap) == {"1", "2"} and snap["1"]["reason"] == "no_path" and snap["1"]["cancel"] == "Could not find path"
    u2.counters2.thirst_timer = 100                       # drank
    w.kill(u1, 9)
    u1.pos = T(lua, {"x": 20, "y": 21, "z": 100})
    r, by = rows(env)
    assert r["new_deaths"] == 1 and not by, r
    d = r["deaths"][0]
    assert (d["id"], d["name"], d["reason"], d["cancel"], d["timer"]) == (1, "Kib Dry, Miner", "no_path",
                                                                         "Could not find path", 60000), d
    assert (d["x"], d["y"], d["z"]) == (20, 21, 100), d
    assert py(w.site["ai-overseer/thirst"])["snap"] == {} or not py(w.site["ai-overseer/thirst"])["snap"]
    r, _ = rows(env)
    assert r["new_deaths"] == 0 and len(r["deaths"]) == 1, r          # told once, kept for the brain


@test("report: a death by another cause is not a thirst death")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    u = dwarf(lua, w, 1, 60000)
    rows(env)
    w.kill(u, 7)
    r, _ = rows(env)
    assert r["new_deaths"] == 0 and not r["deaths"], r


@test("report: the save written when who or why changed, not every report")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    drink(lua, w, stack_size=5)
    u = dwarf(lua, w, 1, 30000)
    rows(env)
    n = w.saves
    u.counters2.thirst_timer = 30100
    rows(env)
    assert w.saves == n
    u.pos = T(lua, {"x": 10, "y": 10, "z": 101})        # walked off where the drink is: no path
    w.zgroup[101] = 5
    rows(env)
    assert w.saves == n + 1 and py(w.site["ai-overseer/thirst"])["snap"]["1"]["reason"] == "no_path"


# --- 3. the action --------------------------------------------------------------------------

@test("unforbid_drink: the forbidden drink in their group, nearest first, max; a dry run changes nothing")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    far = drink(lua, w, 40, 10, 100, flags={"forbid": True})
    near = drink(lua, w, 11, 10, 100, flags={"forbid": True})
    barrel = T(lua, {"flags": {"forbid": True}, "pos": {"x": 13, "y": 10, "z": 100}})
    inb = drink(lua, w, container=barrel, flags={"in_inventory": True})
    w.zgroup[90] = 2
    other = drink(lua, w, 5, 5, 90, flags={"forbid": True})
    dwarf(lua, w, 1, 40000)
    r = py(env.unforbid_drink(1, True, 2))
    assert r["ok"] and r["dry_run"] and r["unforbidden"] == 2 and r["candidates"] == 3 and r["containers"] == 1, r
    assert near.flags.forbid and barrel.flags.forbid
    r = py(env.unforbid_drink(1, False, 2))
    assert r["unforbidden"] == 2 and not near.flags.forbid and not barrel.flags.forbid and far.flags.forbid, r
    assert other.flags.forbid and not inb.flags.forbid        # the barrel let go (another group's drink left)
    r = py(env.unforbid_drink(1, False, 10))
    assert r["unforbidden"] == 1 and not far.flags.forbid, r     # only the far one is left
    assert py(env.unforbid_drink(1, False, 10))["rejected"]


@test("unforbid_drink: refused with the gates shut against enemies, near a danger, for no such dwarf")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    it = drink(lua, w, 11, 10, 100, flags={"forbid": True})
    dwarf(lua, w, 1, 40000)
    w.armed = True
    r = py(env.unforbid_drink(1, False))
    assert r["rejected"] and "enemies" in r["error"] and it.flags.forbid, r
    w.armed = False
    w.unit(T(lua, {"id": 99, "danger": True, "citizen": False, "pos": {"x": 14, "y": 10, "z": 100}}))
    r = py(env.unforbid_drink(1, False))
    assert r["rejected"] and r["near_danger"] == 1 and it.flags.forbid, r
    assert py(env.unforbid_drink(555, False))["rejected"]


# --- 4. the bridge's wiring ------------------------------------------------------------------

@test("bridge: the thirst section (in the pulse), the module listed, thirst_unforbid with a dry run")
def _():
    b = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert re.search(r"thirst = function\(\) return safe\(function\(\) return reqscript\('ai-thirst'\)\.report\(\)", b)
    pulse = b[b.index("PULSE_SECTIONS = {"):]
    assert "'thirst'" in pulse[:pulse.index("}")]
    assert "'ai-thirst'" in b[b.index("BRIDGE_MODULES = {"):b.index("MARKED_MODULES")]
    assert "thirst_unforbid = function(a)" in b and "'thirst_unforbid'," in b
    t = (LUA_DIR / "ai-threats.lua").read_text(encoding="utf-8")
    assert "function cancel_rows(window)" in t
    assert SECTION_DEFAULTS["thirst"] == {}
    s = normalize({"thirst": {"error": "boom"}})
    assert s["thirst"] == {} and "thirst" in s["_errors"]
    import overseer
    assert "thirst_unforbid" in overseer.SHORT_WORDS
    assert "thirst_journal" in (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")


# --- 5. the brain -----------------------------------------------------------------------------

def state(rows_=None, deaths=None, **kw):
    s = {"date": {"year": 300, "tick": 1200}, "thirst": {"list": rows_ or [], "deaths": deaths or []}}
    s.update(kw)
    return s


def row(uid, reason, timer=40000, **kw):
    return dict(id=uid, name=f"Dwarf {uid}", reason=reason, timer=timer, x=1, y=2, z=3, **kw)


def run(s, memory=None, proposals=None, cfg=None):
    props = list(proposals or [])
    notes: list = []
    PT._thirst_rule(s, cfg or PLANNER_CONFIG, props, notes, memory if memory is not None else Memory())
    return props, notes


@test("brain: the rule is an emergency (no limit, cooldown, strategist hold)")
def _():
    assert PT.RULE in EMERGENCY and PT.RULE in LIMIT_EXEMPT and PT.RULE in STEER_PROTECTED
    assert set(PT.REASONS) >= {"insane", "mood", "chained", "jailed", "cell", "stranded", "drinking", "interrupted",
                               "alert", "burrow", "forbidden", "no_path", "no_drink", "injured", "cancelled",
                               "unknown"}


@test("brain: jailed -> release_prisoners for them; not when the prisoners' water rule lets them go")
def _():
    p, n = run(state([row(4, "jailed"), row(5, "chained")]))
    acts = [x.action for x in p if x.rule == "thirst"]
    assert {"type": "release_prisoners", "ids": [4]} in acts and {"type": "release_prisoners", "ids": [5]} in acts
    assert all(x.priority == 0 for x in p)
    other = Proposal("prisoners_water", {"type": "release_prisoners"}, "x", 1)
    p, n = run(state([row(4, "jailed")]), proposals=[other])
    assert [x.rule for x in p] == ["prisoners_water"] and "prisoners' water rule" in n[0], n
    other = Proposal("prisoners_water", {"type": "release_prisoners", "ids": [4]}, "x", 1)
    p, _ = run(state([row(4, "jailed"), row(5, "jailed")]), proposals=[other])
    assert [x.action.get("ids") for x in p if x.rule == "thirst"] == [[5]]


@test("brain: forbidden -> thirst_unforbid from the first thirsty report; paced per dwarf")
def _():
    m = Memory()
    s = state([row(2, "forbidden", timer=26000, forbidden_group=3)])
    p, n = run(s, m)
    assert [x.action for x in p] == [{"type": "thirst_unforbid", "unit_id": 2, "max": 10}], p
    assert "proposed:" in n[0] and "forbidden" in n[0]
    p, n = run(s, m)
    assert not p and "tried" in n[0], n
    s["date"]["tick"] += PLANNER_CONFIG["thirst_retry_ticks"]
    p, _ = run(s, m)
    assert len(p) == 1


@test("brain: stranded and no_path left to the gates rules when they act; else join_levels once a cycle")
def _():
    gate = Proposal("gate_stuck", {"type": "unstick_gate", "id": 7, "step": 1}, "x", 0)
    p, n = run(state([row(6, "stranded", stranded={"cause": "gate_shut"}), row(7, "no_path")]), proposals=[gate])
    assert [x.rule for x in p] == ["gate_stuck"], p
    assert "gates rules" in n[0] and "gates rules" in n[1], n
    p, n = run(state([row(6, "stranded", stranded={"cause": "no_path"})]))
    assert not p and "(no_path)" in n[0], n
    p, n = run(state([row(7, "no_path"), row(8, "no_path")]))
    assert [x.action for x in p] == [{"type": "join_levels"}], p
    assert "fort-wide remedy" in n[1], n


@test("brain: the alarm: the AI shelter redrawn (refresh_shelter) once; a player's alarm burrow only said")
def _():
    p, n = run(state([row(1, "alert"), row(2, "alert")], civ_alert_shelter="ai"))
    assert [x.action for x in p] == [{"type": "refresh_shelter"}], p
    already = Proposal("shelter_refresh", {"type": "refresh_shelter"}, "x", 0)
    p, n = run(state([row(1, "alert")], civ_alert_shelter="ai"), proposals=[already])
    assert len(p) == 1 and "redrawn this cycle" in n[0]
    p, n = run(state([row(1, "alert")], civ_alert_shelter="player"))
    assert not p and "player's" in n[0]


@test("brain: insane, mood, cell, burrow, interrupted, no_drink, injured: said, no action; quiet ones quiet")
def _():
    rs = [row(1, "insane", insane="melancholy"), row(2, "mood", mood="Fey"), row(3, "cell"),
          row(4, "burrow", burrow_ai=True), row(5, "interrupted", cancel={"by": "human spearman", "why": "Interrupted by a human spearman"}),
          row(6, "no_drink"), row(7, "injured"), row(8, "drinking", timer=30000), row(9, "unknown", timer=30000),
          row(10, "cancelled", timer=30000, cancel={"why": "Dangerous terrain"})]
    p, n = run(state(rs))
    assert not p, p
    assert len(n) == 7, n
    assert any("human spearman interrupts them" in x for x in n)
    squad = Proposal("squad_attack", {"type": "squad_orders", "squad_id": 1, "kill": [99]}, "x", 0)
    p, n = run(state([rs[4]]), proposals=[squad])
    assert "a squad goes after" in n[0]
    p, n = run(state([row(9, "unknown", timer=55000)]))
    assert len(n) == 1 and "dehydrated" in n[0]


@test("brain: one note a dwarf up to the cap, the rest in one line; actions capped a cycle")
def _():
    cfg = dict(PLANNER_CONFIG, thirst_notes_max=2, thirst_actions_max=1)
    p, n = run(state([row(i, "jailed", timer=40000 + i) for i in range(1, 6)]), cfg=cfg)
    assert len([x for x in p if x.rule == "thirst"]) == 1
    assert len(n) == 3 and n[2].startswith("3 more thirsty: jailed 3"), n
    assert "Dwarf 5" in n[0]                                       # the thirstiest first


@test("brain: below the act line a jailed dwarf is only noted; below the note line nothing")
def _():
    p, n = run(state([row(4, "jailed", timer=30000)]))
    assert not p and len(n) == 1
    p, n = run(state([row(4, "jailed", timer=20000)]))
    assert not p and not n


@test("brain: a death of thirst told once (place, last reason, last cancelled Drink) and journaled once")
def _():
    m = Memory()
    d = {"id": 1, "name": "Kib Dry", "x": 20, "y": 21, "z": 100, "reason": "no_path",
         "cancel": "Could not find path", "timer": 60000}
    s = state(deaths=[d])
    p, n = run(s, m)
    assert n == ["Kib Dry died of thirst at x20 y21 z100; last reason: no_path (no path from where they stand to "
                 "drink or a well); last cancelled Drink: \"Could not find path\"; thirst 60000 when last seen"], n
    p, n = run(s, m)
    assert not n
    j = PT.thirst_journal(s, m)
    assert len(j) == 1 and j[0]["id"] == 1 and j[0]["reason"] == "no_path" and "x20 y21" in j[0]["text"]
    assert PT.thirst_journal(s, m) == []
    assert isinstance(Memory.from_dict(m.to_dict()).thirst_book.get("told"), dict)


@test("brain: plan() runs the rule after the others (the gates' proposal seen) and a failed section is skipped")
def _():
    import planner
    src = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")
    assert src.index("_guard(_thirst_rule") < src.index("_guard(_stuck_rule")
    assert src.index("_guard(_thirst_rule") > src.index("_guard(_artifact_rule")
    assert 'if "thirst" not in errors' in src
    assert planner._thirst_rule is PT._thirst_rule


if __name__ == "__main__":
    finish()
