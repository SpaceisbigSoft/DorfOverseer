"""(item1, 24 Nov) The in-game fight watcher. B lost seven citizens strangled
by citizens in three hours; break_fights (DFHack fix/loyaltycascade, once a
cycle, about a game day) took 11 out of a fight ~600 ticks before two died
in it. lua/ai-fights.lua looks every 10 ticks inside the game: a Conflict
among living citizens only is capped at Brawl and broken up
(makeown.remove_from_conflict); invaders and wildlife are left alone.

Tested here: the watcher over a fake game (lupa: run on the PC), the action
and the section wired into the bridge, the Rules switch, and the brain's
fight_watch rule, its words, its exemptions and its journal line.

    python tests/test_item1_fights.py
"""

from __future__ import annotations

import copy
import json
import atexit
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
from planner_core import LIMIT_EXEMPT, STEER_PROTECTED, LOOP_LIMITS, player_rules  # noqa: E402
import planner_tantrums as PT  # noqa: E402
import hold_classes  # noqa: E402
import overseer_words  # noqa: E402
from digest import SECTION_DEFAULTS  # noqa: E402

LUA_DIR = ROOT / "lua"
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort(fights=None, **settings) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    if fights is not None:
        s["fights"] = fights
    if settings:
        s.setdefault("settings", {}).update(settings)
    return s


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


# --- lua/ai-fights.lua in a fake game ------------------------------------------
# FAKE builds the game, loads the module and runs one CASE (Lua) with E (the
# module's env) and W (the world) in reach; a failed assert fails the test.

FAKE = r"""
local src, case = ...
local W = {units = {}, acts = {}, timers = {}, next_timer = 1, removed = {}, halted = false}
local env = setmetatable({}, {__index = _G})
local real = ipairs
local function vec(l)
    local t = {_v = true}
    for i, v in real(l or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
        __index = {erase = function(self, at) local n = #self; for i = at, n - 2 do self[i] = self[i + 1] end; self[n - 1] = nil end}})
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
    t.civ_id = t.civ_id or 7
    t.counters = t.counters or {soldier_mood = t.tantrum and 2 or -1, soldier_mood_countdown = t.countdown or -1,
                                suffocation = t.suffocation or 0}
    if t.attacks then   -- (item3) Attack actions on these target ids
        local acts = {}
        for _, tid in real(t.attacks) do
            table.insert(acts, {id = #acts + 1, type = 1, data = {attack = {target_unit_id = tid, attack_body_part_id = 3,
                                timer1 = 5, timer2 = 6, wrestle_info = {wrestle_type = 1, flags = 0}}}})
        end
        t.actions = vec(acts)
    end
    t.mood = t.mood or -1
    t.race = t.race or 1
    t.enemy = t.enemy or {normal_race = -1}
    if t.citizen == nil then t.citizen = true end
    W.units[t.id] = t
    return t
end
local CONFLICT_T, CONFLICT_E = 8, 10
-- sides: {{units = {ids}, level = n}, ...}: each side has the others as enemies at its level
function W.conflict(id, sides)
    local sv = {}
    for i, sd in real(sides) do
        local en = {}
        for k, _ in real(sides) do
            if k ~= i then table.insert(en, {id = k, conflict_level = sd.level}) end
        end
        table.insert(sv, {id = i, unit_ids = vec(sd.units), histfig_ids = vec({}), enemies = vec(en)})
    end
    local ev = {event_id = id * 10, sides = vec(sv), inactivity_timer = 3, attack_inactivity_timer = 4,
                stop_fort_fights_timer = 5, getType = function() return CONFLICT_E end}
    local a = {id = id, type = CONFLICT_T, events = vec({ev})}
    table.insert(W.acts, a)
    W.all = vec(W.acts)
    return a, ev
end
-- (item3) a non-conflict activity: one event of type `ety` whose participants.units are `units`
function W.activity(id, ety, units)
    local ev = {event_id = id * 10, participants = {units = vec(units or {})}, getType = function() return ety end}
    local a = {id = id, type = 50, events = vec({ev})}
    table.insert(W.acts, a)
    W.all = vec(W.acts)
    return a, ev
end
W.squads = {}
function W.clear() W.acts = {}; W.all = vec({}) end
function W.levels(ev)
    local out = {}
    for _, sd in env.ipairs(ev.sides) do for _, e in env.ipairs(sd.enemies) do table.insert(out, e.conflict_level) end end
    return out
end
W.all = vec({})
env.df = {
    global = {cur_year = 250, cur_year_tick = 1000, plotinfo = {civ_id = 7},
              world = setmetatable({}, {__index = function(_, k)
                  if k == 'activities' then
                      if W.broken then error('activities unreadable') end
                      return {all = W.all}
                  end
                  if k == 'units' then   -- (item3) the active units, by id
                      local ids, l = {}, {}
                      for id in pairs(W.units) do table.insert(ids, id) end
                      table.sort(ids)
                      for _, id in real(ids) do table.insert(l, W.units[id]) end
                      return {active = vec(l)}
                  end
              end})},
    activity_entry_type = {Conflict = CONFLICT_T},
    activity_event_type = {Conflict = CONFLICT_E, [20] = 'Sparring', [21] = 'CombatTraining', [99] = 'Conversation'},
    unit_action_type = {Attack = 1},
    squad = {find = function(id) return W.squads[id] end},   -- (item3) the squads, by id
    squad_order_type = {TRAIN = 3},
    job_type = {[5] = 'Strangle'},
    soldier_mood_type = {[-1] = 'None', [0] = 'MartialTrance', [1] = 'Enraged', [2] = 'Tantrum', [3] = 'Depressed'},
    mood_type = {[7] = 'Berserk'},
    unit = {find = function(id) return W.units[id] end},
}
env.SC_MAP_UNLOADED, env.SC_WORLD_UNLOADED = 'map_unloaded', 'world_unloaded'
env.dfhack = {
    units = {
        isCitizen = function(u) return u.citizen == true end,
        isDead = function(u) return u.dead == true end,
        isInvader = function(u) return u.invader == true end,
        isUndead = function(u) return u.undead == true end,
        isCrazed = function(u) return u.crazed == true end,
        isDanger = function(u) return u.invader == true or u.undead == true or u.crazed == true end,
        isAnimal = function(u) return u.animal == true end,
        isMerchant = function(u) return false end,
        isDiplomat = function(u) return false end,
        isVisitor = function(u) return u.visitor == true end,
        getReadableName = function(u) return u.name or ('Urist ' .. u.id) end,
    },
    df2utf = function(s) return s end,
    timeout = function(n, unit, fn)
        local id = W.next_timer
        W.next_timer = id + 1
        W.timers[id] = {n = n, unit = unit, fn = fn}
        return id
    end,
    timeout_active = function(id) return W.timers[id] ~= nil and W.timers[id].fn or nil end,
    getDFPath = function() if not W.dir then error('no DF path') end return W.dir end,
    filesystem = {mkdir_recursive = function(p) return true end},   -- (the test's folder made by Python: no shell, Windows too)
    onStateChange = {},
}
-- fire every pending timer once (as DF's ticks would)
function W.fire()
    local due = W.timers
    W.timers = {}
    local n = 0
    for _, t in pairs(due) do n = n + 1; t.fn() end
    return n
end
function W.pending() local n = 0; for _ in pairs(W.timers) do n = n + 1 end; return n end
local function erase_unit(u)
    for _, a in real(W.acts) do
        for _, ev in env.ipairs(a.events) do
            for _, sd in env.ipairs(ev.sides) do
                for i = #sd.unit_ids - 1, 0, -1 do if sd.unit_ids[i] == u.id then sd.unit_ids:erase(i) end end
            end
        end
    end
end
W.makeown = {remove_from_conflict = function(u)
    table.insert(W.removed, u.id)
    erase_unit(u)
    return true
end}
env.reqscript = function(name)
    if name == 'makeown' then
        if W.no_makeown then error('no makeown') end
        return W.makeown
    end
    if name == 'ai-status' then return {is_halted = function() return W.halted end} end
    error('no module ' .. tostring(name))
end
rawset(_G, 'ai_overseer_fight_watch', nil)
assert(load(src, 'ai-fights', 't', env))()
local E = env
local cenv = setmetatable({E = E, W = W}, {__index = function(_, k) local v = rawget(env, k); if v ~= nil then return v end; return _G[k] end})
local r = assert(load(case, 'case', 't', cenv))()
return r == nil and 'ok' or r
"""

CASES = {}


TMPDIR = tempfile.mkdtemp(prefix="item1-fights-")
os.makedirs(os.path.join(TMPDIR, "dfhack-config", "ai-overseer"), exist_ok=True)
atexit.register(shutil.rmtree, TMPDIR, True)


def case(name: str, code: str):
    code = code.replace("__TMPDIR__", TMPDIR.replace("\\", "/"))
    CASES[name] = code

    @test("lua: " + name)
    def _():
        need_lua()
        from lupa.lua53 import LuaRuntime
        lua = LuaRuntime(unpack_returned_tuples=True)
        r = lua.execute(FAKE, module_src("ai-fights.lua"), code)
        assert r == "ok" or (isinstance(r, str) and r.startswith("{")), r   # (the log case hands its line on)
    return _


case("two citizens at Lethal: capped to Brawl and separated at once, the log has both levels", r"""
local a = W.unit{id = 1, name = 'Urist Tantrum', tantrum = true}
local b = W.unit{id = 2, name = 'Bomrek "Quote"'}
local act, ev = W.conflict(100, {{units = {1}, level = 5}, {units = {2}, level = 5}})
local d = E.pass(5000)
local lv = W.levels(ev)
assert(lv[1] == 3 and lv[2] == 3, 'capped')
assert(#W.removed == 2, 'both separated')
local S = E.state()
assert(S.counts.capped == 2 and S.counts.separated == 2 and S.counts.seen == 1, 'counts')
local e = S.log[#S.log]
assert(e.kind == 'seen' and e.activity_id == 100 and e.max == 5 and e.capped == 2, 'entry')
assert(e.levels[1].level == 5 and e.levels_after[1].level == 3, 'before and after')
assert(e.units[1].tantrum == true and e.units[2].tantrum == nil, 'the tantrum marked')
assert(e.timers.inactivity == 3 and e.timers.attack_inactivity == 4 and e.timers.stop_fort_fights == 5, 'timers')
assert(#e.separated == 2 and e.tick == 5000, 'separated listed')
""")

case("an invader among them: nothing touched, nothing counted, its citizen never separated", r"""
W.unit{id = 1}
W.unit{id = 3, invader = true, citizen = false}
local act, ev = W.conflict(101, {{units = {1}, level = 5}, {units = {3}, level = 5}})
E.pass(5000); E.pass(5100)
local lv = W.levels(ev)
assert(lv[1] == 5 and lv[2] == 5, 'levels kept')
assert(#W.removed == 0 and E.state().counts.seen == 0 and #E.state().log == 0, 'untouched')
-- the same citizen also in a brawl with a citizen: that one is broken up, he is kept in
W.unit{id = 2}
W.conflict(102, {{units = {1}, level = 5}, {units = {2}, level = 5}})
E.pass(5200)
assert(#W.removed == 1 and W.removed[1] == 2, 'only the other separated')
assert(E.state().log[#E.state().log].kept[1] == 1, 'kept named')
""")

case("wildlife, undead, a crazed or transformed citizen: left alone", r"""
W.unit{id = 1}
W.unit{id = 4, animal = true, citizen = false}
W.unit{id = 5, undead = true}
W.unit{id = 6, crazed = true}
W.unit{id = 7, race = 9, enemy = {normal_race = 1}}
local evs = {}
for i, o in ipairs({4, 5, 6, 7}) do
    local _, ev = W.conflict(200 + i, {{units = {1}, level = 5}, {units = {o}, level = 5}})
    evs[i] = ev
end
E.pass(5000)
for _, ev in ipairs(evs) do local lv = W.levels(ev); assert(lv[1] == 5 and lv[2] == 5) end
assert(#W.removed == 0 and E.state().counts.seen == 0)
""")

case("a brawl: separated only once it has lasted past separate_ticks; horseplay never", r"""
W.unit{id = 1}; W.unit{id = 2}; W.unit{id = 8}; W.unit{id = 9}
local _, ev = W.conflict(110, {{units = {1}, level = 3}, {units = {2}, level = 3}})
local _, sp = W.conflict(111, {{units = {8}, level = 1}, {units = {9}, level = 1}})
E.pass(5000); E.pass(5040)
assert(#W.removed == 0, 'too young')
E.pass(5051)
assert(#W.removed == 2, 'old enough')
assert(E.state().counts.capped == 0, 'nothing above brawl')
E.pass(6000)
for _, id in ipairs(W.removed) do assert(id == 1 or id == 2, 'sparring left alone') end
assert(E.state().counts.seen == 2, 'both seen')
""")

case("a death in the fight: the living separated at once", r"""
W.unit{id = 1}; W.unit{id = 2, dead = true}
W.conflict(120, {{units = {1}, level = 3}, {units = {2}, level = 3}})
E.pass(5000)
assert(#W.removed == 1 and W.removed[1] == 1, 'the living one out')
assert(E.state().counts.died == 1 and E.state().log[1].died == true)
""")

case("re-engaged within the window: separated again at once and counted", r"""
W.unit{id = 1}; W.unit{id = 2}
W.conflict(130, {{units = {1}, level = 5}, {units = {2}, level = 5}})
E.pass(5000)
assert(#W.removed == 2)
W.clear()
W.conflict(131, {{units = {1}, level = 3}, {units = {2}, level = 3}})
E.pass(5010)
assert(#W.removed == 4, 'again, not waiting for separate_ticks')
assert(E.state().counts.reengaged == 1 and E.state().counts.separated == 4)
-- past the window it is a new brawl again
W.clear()
W.conflict(132, {{units = {1}, level = 3}, {units = {2}, level = 3}})
E.pass(5010 + E.REENGAGE_TICKS + 1)
assert(#W.removed == 4, 'a new brawl waits')
""")

case("the action: arms once (idempotent), updates settings, disarms; a stale beat ends", r"""
assert(E.act({}).rejected and E.act({on = 'yes'}).rejected and E.act({on = true, ticks = 0}).rejected)
local d = E.act({on = true, dry_run = true})
assert(d.dry_run and d.would == 'arm' and W.pending() == 0 and not E.state().on, 'dry run changes nothing')
local r = E.act({on = true})
assert(r.ok and r.armed and r.started and W.pending() == 1 and W.timers[1].n == 10 and W.timers[1].unit == 'ticks')
local r2 = E.act({on = true, ticks = 20, separate_ticks = 80})
assert(r2.armed and r2.already and W.pending() == 1 and E.state().ticks == 20 and E.state().separate_ticks == 80)
W.fire()
assert(W.pending() == 1 and W.timers[2].n == 20, 'the beat re-arms itself at the new pace')
local off = E.act({on = false})
assert(off.ok and not off.armed)
W.fire()
assert(W.pending() == 0, 'disarmed: the pending beat ends the loop')
-- off then on before the old beat fires: still one loop
E.act({on = true}); E.act({on = false}); E.act({on = true})
assert(W.pending() == 2)
W.fire()
assert(W.pending() == 1, 'the stale beat ended, one loop left')
W.fire(); W.fire()
assert(W.pending() == 1)
""")

case("the beat: a throw inside the pass never stops the loop; halted, it passes nothing", r"""
W.unit{id = 1}; W.unit{id = 2}
E.act({on = true})
W.broken = true
W.fire()
assert(W.pending() == 1, 'still armed')
W.broken = false
W.conflict(140, {{units = {1}, level = 5}, {units = {2}, level = 5}})
W.halted = true
W.fire()
assert(#W.removed == 0 and W.pending() == 1, 'halted: nothing done, still armed')
W.halted = false
W.fire()
assert(#W.removed == 2)
-- the map unloads: the state is cleared (DFHack drops the timers)
E.dfhack.onStateChange['ai-fights']('map_unloaded')
assert(not E.state().on and E.state().counts.separated == 0 and not E.alive())
""")

case("no makeown: capped anyway, the error said, nothing thrown", r"""
W.no_makeown = true
W.unit{id = 1}; W.unit{id = 2}
local _, ev = W.conflict(150, {{units = {1}, level = 6}, {units = {2}, level = 4}})
E.pass(5000)
local lv = W.levels(ev)
assert(lv[1] == 3 and lv[2] == 3 and #W.removed == 0)
assert(E.state().error:find('makeown'))
""")

case("the section: armed, counts, the last ten log entries, the citizens' conflicts now", r"""
W.unit{id = 1}; W.unit{id = 2}; W.unit{id = 3, invader = true, citizen = false}
E.act({on = true})
for i = 1, 14 do
    W.clear()
    W.conflict(300 + i, {{units = {1}, level = 1}, {units = {2}, level = 1}})
    E.pass(5000 + i)
end
W.conflict(400, {{units = {1}, level = 3}, {units = {3}, level = 3}})
local r = E.report()
assert(r.armed == true and r.ticks == 10 and r.counts.seen == 14, 'state')
assert(#r.log == 10 and r.log[10].activity_id == 314, 'the last ten')
assert(#r.now == 1 and r.now[1].activity_id == 314 and r.now[1].max == 1 and r.now[1].units[2].name == 'Urist 2', 'now')
""")

case("the log file: one JSON line an entry, trimmed to the last LOG_FILE_KEEP", r"""
local dir = [[__TMPDIR__]]
W.dir = dir
E.LOG_FILE_KEEP, E.LOG_FILE_SLACK = 5, 3
W.unit{id = 1, name = 'Urist "Q" \\ McX'}; W.unit{id = 2}
for i = 1, 12 do
    W.clear()
    W.conflict(500 + i, {{units = {1}, level = 1}, {units = {2}, level = 1}})
    E.pass(5000 + i)
end
local f = assert(io.open(dir .. '/dfhack-config/ai-overseer/fights.jsonl'))
local lines = {}
for l in f:lines() do table.insert(lines, l) end
f:close()
assert(#lines >= 5 and #lines <= 8, #lines)
assert(lines[#lines]:find('"activity_id":512', 1, true), lines[#lines])
assert(lines[#lines]:find('Urist \\"Q\\" \\\\ McX', 1, true), lines[#lines])
return lines[#lines]
""")


# --- (item3) a tantrum that attacks a citizen ended ---------------------------

case("a tantrum citizen attacking a citizen: countdown to 1, counted, logged once a 100 ticks", r"""
local a = W.unit{id = 1, name = 'Ducim', tantrum = true, countdown = 1599, attacks = {2}}
local b = W.unit{id = 2, name = 'Doctor', suffocation = 40}
E.pass(5000)
assert(a.counters.soldier_mood_countdown == 1, 'ended')
assert(a.counters.soldier_mood == 2, 'the mood itself never written')
local S = E.state()
assert(S.counts.tantrums_ended == 1 and S.counts.tantrum_attacks == 1, 'counted')
local e = S.log[#S.log]
assert(e.kind == 'tantrum_ended' and e.id == 1 and e.name == 'Ducim' and e.target == 2 and e.target_name == 'Doctor', 'entry')
assert(e.how == 'attack' and e.countdown == 1599 and e.ended == true and e.suffocation == 40 and e.tick == 5000, 'details')
assert(e.mood == 'Tantrum' and e.attack.body_part == 3 and e.attack.wrestle.wrestle_type == 1, 'the attack')
-- DF starts it again: ended every time, logged once a TANTRUM_LOG_TICKS
a.counters.soldier_mood_countdown = 800
E.pass(5050)
assert(a.counters.soldier_mood_countdown == 1 and S.counts.tantrums_ended == 2, 'ended again')
assert(#S.log == 1, 'not logged again so soon')
a.counters.soldier_mood_countdown = 700
E.pass(5101)
assert(S.counts.tantrums_ended == 3 and #S.log == 2, 'logged again past the window')
-- the section shows it
local r = E.report()
assert(r.end_tantrums == true and r.counts.tantrums_ended == 3, 'the section')
""")

case("a tantrum citizen attacking an invader: untouched; Enraged by opponent or conflict: ended", r"""
local a = W.unit{id = 1, tantrum = true, countdown = 900, attacks = {3}}
W.unit{id = 3, invader = true, citizen = false}
E.pass(5000)
assert(a.counters.soldier_mood_countdown == 900 and E.state().counts.tantrums_ended == 0 and #E.state().log == 0, 'untouched')
-- an Enraged citizen whose opponent is a citizen
local c = W.unit{id = 4, countdown = 500, counters = {soldier_mood = 1, soldier_mood_countdown = 500}}
c.opponent = {timer = 10, unit_id = 5, unit_pos = {}}
W.unit{id = 5}
-- a tantrum citizen in a Conflict with a citizen (no Attack action read)
local d = W.unit{id = 6, tantrum = true, countdown = 300}
W.unit{id = 7}
W.conflict(600, {{units = {6}, level = 3}, {units = {7}, level = 3}})
E.pass(5010)
assert(c.counters.soldier_mood_countdown == 1 and d.counters.soldier_mood_countdown == 1, 'both ended')
assert(a.counters.soldier_mood_countdown == 900, 'still untouched')
local how = {}
for _, e in ipairs(E.state().log) do if e.kind == 'tantrum_ended' then how[e.id] = e.how end end
assert(how[4] == 'opponent' and how[6] == 'conflict' and how[1] == nil, 'how found')
-- a countdown already at 1: not written, not counted
local n = E.state().counts.tantrums_ended
E.pass(5020)
assert(E.state().counts.tantrums_ended == n, 'already ending')
""")

case("a calm citizen attacking a citizen: logged 'attack' once a pair, nothing changed; sparring left out", r"""
local a = W.unit{id = 1, name = 'Calm', countdown = 50, attacks = {2}}
a.job = {current_job = {job_type = 5}}
W.unit{id = 2, suffocation = 7}
E.pass(5000); E.pass(5100)
local S = E.state()
assert(#S.log == 1 and S.counts.attacks == 1 and S.counts.tantrums_ended == 0, 'once')
local e = S.log[1]
assert(e.kind == 'attack' and e.id == 1 and e.target == 2 and e.job == 'Strangle' and e.suffocation == 7, 'entry')
assert(a.counters.soldier_mood_countdown == 50, 'nothing changed')
E.pass(5000 + E.ATTACK_LOG_TICKS)
assert(S.counts.attacks == 2, 'again past the window')
-- sparring: in a Training conflict
E.reset()
W.unit{id = 8, attacks = {9}}; W.unit{id = 9}
W.conflict(610, {{units = {8}, level = 2}, {units = {9}, level = 2}})
E.pass(6000)
for _, x in ipairs(E.state().log) do assert(not (x.kind == 'attack' and x.id == 8), 'sparring not logged') end
assert(E.state().log[1].id == 1, 'the other pair still logged')
""")

# --- (item3) sparring that opens no conflict: B's 199 mutual wrestlers -----------

case("a mutual pair, neither in a tantrum: counted as spars once a pair a window, never logged", r"""
W.unit{id = 1, name = 'Wrestler A', attacks = {2}}
W.unit{id = 2, name = 'Wrestler B', attacks = {1}}
E.pass(5000)
local S = E.state()
assert(S.counts.spars == 1 and S.counts.attacks == 0 and #S.log == 0, 'one spar, no attack, no log')
local r = S.spars_recent[1]
assert(r.why == 'mutual' and r.tick == 5000 and ((r.id == 1 and r.target == 2) or (r.id == 2 and r.target == 1)), 'recent')
E.pass(5010); E.pass(5300)
assert(S.counts.spars == 1, 'once a pair a ATTACK_LOG_TICKS')
E.pass(5000 + E.ATTACK_LOG_TICKS)
assert(S.counts.spars == 2 and #S.log == 0, 'again past the window')
local rep = E.report()
assert(rep.counts.spars == 2 and #rep.spars_recent == 2 and #rep.log == 0, 'the section')
-- B joins a pass later: A's first attack logged, then the pair is sparring
W.units[1], W.units[2] = nil, nil
W.unit{id = 3, attacks = {4}}; W.unit{id = 4}
E.pass(8000)
assert(S.counts.attacks == 1, 'one-way: an attack')
W.unit{id = 4, attacks = {3}}
E.pass(8050)
assert(S.counts.attacks == 1 and S.counts.spars == 3, 'both ways now: one spar')
-- answered past MUTUAL_TICKS: not mutual
W.unit{id = 5, attacks = {6}}; W.unit{id = 6}
E.pass(9000)
W.unit{id = 5}; W.unit{id = 6, attacks = {5}}
E.pass(9000 + E.MUTUAL_TICKS + 10)
local n = 0
for _, e in ipairs(S.log) do if e.kind == 'attack' and (e.id == 5 or e.id == 6) then n = n + 1 end end
assert(n == 2, 'both logged as attacks')
-- spars_recent keeps the last SPAR_RECENT_KEEP
for i = 1, 8 do W.unit{id = 100 + 2 * i, attacks = {101 + 2 * i}}; W.unit{id = 101 + 2 * i, attacks = {100 + 2 * i}} end
E.pass(9500)
assert(#S.spars_recent == E.SPAR_RECENT_KEEP, 'kept to the last few')
""")

case("mutual but not sparring: a target suffocating or bleeding, a tantrum (still ended), a brawl", r"""
W.unit{id = 1, attacks = {2}}; W.unit{id = 2, attacks = {1}, suffocation = 30}
W.unit{id = 3, tantrum = true, countdown = 900, attacks = {4}}; W.unit{id = 4, attacks = {3}}
W.unit{id = 5, attacks = {6}}; W.unit{id = 6, attacks = {5}}
W.conflict(620, {{units = {5}, level = 3}, {units = {6}, level = 3}})
W.unit{id = 7, attacks = {8}}; W.unit{id = 8, attacks = {7}, body = {blood_count = 50, blood_max = 100}}
W.unit{id = 9, attacks = {10}}; W.unit{id = 10, attacks = {9}, body = {blood_count = 90, blood_max = 100}}
E.pass(5000)
local S = E.state()
local w = W.units[3]
assert(w.counters.soldier_mood_countdown == 1 and S.counts.tantrums_ended == 1, 'the tantrum ended, mutual or not')
local att = {}
for _, e in ipairs(S.log) do if e.kind == 'attack' then att[e.id] = e.target end end
assert(att[1] == 2 and att[2] == 1, 'suffocating: both attacks logged')
assert(att[4] == 3 and att[3] == nil, 'the calm one hitting a tantrum: an attack')
assert(att[5] == 6 and att[6] == 5, 'in a brawl: attacks')
assert(att[7] == 8 and att[8] == 7, 'bleeding: attacks')
assert(att[9] == nil and att[10] == nil, 'a scratch: sparring')
assert(S.counts.attacks == 7 and S.counts.spars == 1, 'counts')
""")

case("in a training activity (participants, social_activities, activities): sparring; a conversation is not", r"""
W.unit{id = 1, attacks = {2}}; W.unit{id = 2}
W.activity(700, 20, {1})                                          -- a Sparring event listing unit 1
W.unit{id = 3, attacks = {4}, social_activities = W.vec({701})}; W.unit{id = 4}
W.activity(701, 21, {})                                           -- CombatTraining, no participants read
W.unit{id = 5, attacks = {6}, activities = W.vec({702})}; W.unit{id = 6}
W.activity(702, 20, {})
W.unit{id = 7, attacks = {8}, activities = W.vec({703})}; W.unit{id = 8}
W.activity(703, 99, {7})                                          -- a Conversation: no
W.unit{id = 9, attacks = {10}}; W.unit{id = 10, suffocation = 12}
W.activity(704, 20, {9})                                          -- sparring, but the target strangled: no
E.pass(5000)
local S = E.state()
local why = {}
for _, r in ipairs(S.spars_recent) do why[r.id] = r.why .. ':' .. tostring(r.what) end
assert(why[1] == 'activity:Sparring' and why[3] == 'activity:CombatTraining' and why[5] == 'activity:Sparring', 'found')
assert(S.counts.spars == 3 and S.counts.attacks == 2, 'counts')
local att = {}
for _, e in ipairs(S.log) do if e.kind == 'attack' then att[e.id] = true end end
assert(att[7] and att[9] and not att[1], 'the others logged')
-- a training activity opens no Conflict: the conflict pass has nothing to do
assert(S.counts.seen == 0 and #W.removed == 0)
""")

case("a squad told to train: sparring; left out of the order, an order of its own, off duty: not", r"""
local TRAIN = {getType = function() return 3 end}
local function sq(t) t.orders = t.orders or W.vec({}); return t end
E.df.global.plotinfo.alerts = {routines = {[0] = {name = 'Staggered training'}, [1] = {name = 'Off duty'}}}
W.squads[10] = sq{cur_routine_idx = 0, schedule = {[0] = {[0] = {orders = W.vec({{order = TRAIN, positions = W.vec({true})}})}}}}
W.unit{id = 1, attacks = {2}, military = {squad_id = 10, squad_position = 0}}; W.unit{id = 2}
W.squads[11] = sq{cur_routine_idx = 0, schedule = {[0] = {[0] = {orders = W.vec({{order = TRAIN, positions = W.vec({false})}})}}}}
W.unit{id = 3, attacks = {4}, military = {squad_id = 11, squad_position = 0}}; W.unit{id = 4}
W.squads[12] = sq{cur_routine_idx = 0, orders = W.vec({{}}),
                  schedule = {[0] = {[0] = {orders = W.vec({{order = TRAIN, positions = W.vec({true})}})}}}}
W.unit{id = 5, attacks = {6}, military = {squad_id = 12, squad_position = 0}}; W.unit{id = 6}
W.squads[13] = sq{cur_routine_idx = 0}                            -- no schedule read: the routine's name
W.unit{id = 7, attacks = {8}, military = {squad_id = 13, squad_position = 0}}; W.unit{id = 8}
W.squads[14] = sq{cur_routine_idx = 1}
W.unit{id = 9, attacks = {10}, military = {squad_id = 14, squad_position = 0}}; W.unit{id = 10}
W.unit{id = 11, attacks = {12}, military = {squad_id = -1, squad_position = -1}}; W.unit{id = 12}
E.pass(5000)
local S = E.state()
local why = {}
for _, r in ipairs(S.spars_recent) do why[r.id] = r.why .. ':' .. tostring(r.what) end
assert(why[1] == 'squad:order' and why[7] == 'squad:routine', 'training squads')
local att = {}
for _, e in ipairs(S.log) do if e.kind == 'attack' then att[e.id] = true end end
assert(att[3] and att[5] and att[9] and att[11] and not att[1] and not att[7], 'the others logged')
assert(S.counts.spars == 2 and S.counts.attacks == 4, 'counts')
""")

case("an older state (no spar tables, no spars count): read without a throw", r"""
local S = E.state()
S.attack_seen, S.spar_logged, S.spars_recent, S.counts.spars = nil, nil, nil, nil
W.unit{id = 1, attacks = {2}}; W.unit{id = 2, attacks = {1}}
E.pass(5000)
assert(S.counts.spars == 1 and S.counts.errors == 0, 'counted')
assert(#E.report().spars_recent == 1)
""")

case("end_tantrums = false: logged, not ended; the action stores it, the section shows it", r"""
assert(E.act({on = true, end_tantrums = 'no'}).rejected, 'a bool only')
local r = E.act({on = true, end_tantrums = false})
assert(r.ok and r.end_tantrums == false and E.state().end_tantrums == false)
local a = W.unit{id = 1, tantrum = true, countdown = 1599, attacks = {2}}
W.unit{id = 2}
E.pass(5000)
assert(a.counters.soldier_mood_countdown == 1599 and E.state().counts.tantrums_ended == 0, 'not ended')
local e = E.state().log[#E.state().log]
assert(e.kind == 'tantrum_ended' and e.ended == false and e.off == true, 'logged')
assert(E.report().end_tantrums == false, 'the section')
-- absent: on again
assert(E.act({on = true}).end_tantrums == true and E.report().end_tantrums == true)
E.pass(5200)
assert(a.counters.soldier_mood_countdown == 1, 'ended now')
-- a dry pass changes nothing
a.counters.soldier_mood_countdown = 400
E.pass(5400, {dry = true})
assert(a.counters.soldier_mood_countdown == 400)
""")


@test("lua: the log line is valid JSON (encode)")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    line = lua.execute(FAKE, module_src("ai-fights.lua"), CASES[
        "the log file: one JSON line an entry, trimmed to the last LOG_FILE_KEEP"])
    e = json.loads(line)
    assert e["activity_id"] == 512 and e["units"][0]["name"] == 'Urist "Q" \\ McX' and e["levels"][0]["level"] == 1, e


# --- the wiring (source only) ---------------------------------------------------

def src(name: str) -> str:
    return (LUA_DIR / name).read_text(encoding="utf-8")


@test("bridge: fight_watch in ACTIONS and DRY_OK, the fights section safe() and in the pulse, the module listed")
def _():
    cat = src("ai-bridge-catalog.lua")
    assert re.search(r"^\s+fight_watch = function\(a\) return reqscript\('ai-fights'\)\.act\(a, a\.dry_run == true\) end,", cat, re.M)
    dry = cat[cat.index("DRY_OK = {}"):]
    assert "'fight_watch'" in dry[:dry.index("}) do")]
    sec = src("ai-bridge-sections.lua")
    assert "fights = function() return safe(function() return reqscript('ai-fights').report() end) end," in sec
    pulse = sec[sec.index("PULSE_SECTIONS = {"):]
    assert "'fights'" in pulse[:pulse.index("\n}")]
    hub = src("ai-bridge.lua")
    mods = hub[hub.index("BRIDGE_MODULES = {"):]
    assert "'ai-fights'" in mods[:mods.index("\n}")]
    assert re.search(r"^--@\s*module\s*=\s*true", src("ai-fights.lua"), re.M)
    assert "fights" in SECTION_DEFAULTS and SECTION_DEFAULTS["fights"] == {}


@test("sizes: the Lua files touched stay under 60 KB")
def _():
    for n in ("ai-fights.lua", "ai-bridge-catalog.lua", "ai-bridge-sections.lua", "ai-bridge.lua",
              "ai-overseer-settings.lua", "gui/ai-overseer-rules.lua"):
        assert (LUA_DIR / n).stat().st_size < 60 * 1024, n


@test("the watcher calls no vmethod but getType, and pcall-guards the timer's pass")
def _():
    s = src("ai-fights.lua")
    assert "dismiss" not in s.replace("-- ", "") or ":dismiss(" not in s
    assert ":removeParticipant(" not in s and ":dismiss(" not in s
    assert "pcall(pass)" in s and "reqscript, 'makeown'" in s


@test("settings: the fight_watch switch is on by default, sent to the AI, on the Rules tab")
def _():
    st = src("ai-overseer-settings.lua")
    assert "        fight_watch = true," in st and "'fight_watch'," in st and "fight_watch = s.fight_watch," in st
    gui = src("gui/ai-overseer-rules.lua")
    assert "view_id = 'fight_watch'" in gui and "self.subviews.fight_watch:setOption(s.fight_watch ~= false, false)" in gui
    assert player_rules({"settings": {}})["fight_watch"] is True
    assert player_rules({})["fight_watch"] is True
    assert player_rules({"settings": {"fight_watch": False}})["fight_watch"] is False


# --- the brain ------------------------------------------------------------------

ARMED = {"armed": True, "on": True, "ticks": 10, "counts": {"seen": 0, "capped": 0, "separated": 0}}
OFF = {"armed": False, "on": False, "ticks": 10, "counts": {"seen": 0, "capped": 0, "separated": 0}}


@test("rule: armed again whenever the section says it is off; not while armed; nothing without the section")
def _():
    p = by_rule(plan(fort(OFF), Memory())[0], "fight_watch")
    assert len(p) == 1 and p[0].action == {"type": "fight_watch", "on": True, "end_tantrums": True} and p[0].priority == 0, p
    assert not by_rule(plan(fort(ARMED), Memory())[0], "fight_watch")
    assert not by_rule(plan(fort(), Memory())[0], "fight_watch")               # an older bridge
    assert not by_rule(plan(fort({}), Memory())[0], "fight_watch")             # the digest's default
    assert not by_rule(plan(fort({"error": "boom"}), Memory())[0], "fight_watch")


@test("rule: the Rules switch off disarms it once it is on, and never arms it")
def _():
    p = by_rule(plan(fort(ARMED, fight_watch=False), Memory())[0], "fight_watch")
    assert len(p) == 1 and p[0].action == {"type": "fight_watch", "on": False}, p
    assert not by_rule(plan(fort(OFF, fight_watch=False), Memory())[0], "fight_watch")


@test("rule: selected even with every slot taken (limit exempt, never held, survival class)")
def _():
    assert "fight_watch" in LIMIT_EXEMPT and "fight_watch" in STEER_PROTECTED
    assert LOOP_LIMITS["fight_watch"] >= 400
    assert hold_classes.rule_class("fight_watch") == hold_classes.SURVIVAL
    props, _ = plan(fort(OFF), Memory())
    from planner import select
    chosen, held = select(props, fort(OFF), Memory(), dict(PLANNER_CONFIG, max_actions_per_cycle=0))
    assert any(p.rule == "fight_watch" for p in chosen), ([p.rule for p in chosen], held)


@test("words: the action has a short label, and its off says so")
def _():
    assert overseer_words.short({"type": "fight_watch", "on": True}) != "fight_watch"
    assert "stop" in overseer_words.short({"type": "fight_watch", "on": False})
    assert "fight_watch" in overseer_words.SHORT_WORDS


@test("journal: one line when the capped or separated counts grew; none when they didn't; a reload starts again")
def _():
    m = Memory()
    sec = {"armed": True, "counts": {"seen": 2, "capped": 2, "separated": 4, "reengaged": 1, "died": 0},
           "log": [{"tick": 1, "kind": "seen", "activity_id": 9, "max": 5}]}
    out = PT.fight_journal(fort(sec), m)
    assert len(out) == 1 and out[0]["capped"] == 2 and out[0]["separated"] == 4 and "re-engaged" in out[0]["text"], out
    assert out[0]["last"][0]["activity_id"] == 9
    assert PT.fight_journal(fort(sec), m) == []                               # nothing new
    more = copy.deepcopy(sec)
    more["counts"]["separated"] = 6
    out = PT.fight_journal(fort(more), m)
    assert len(out) == 1 and out[0]["separated"] == 2 and out[0]["capped"] == 0
    reload = {"armed": True, "counts": {"seen": 1, "capped": 1, "separated": 0}}
    out = PT.fight_journal(fort(reload), m)
    assert len(out) == 1 and out[0]["capped"] == 1, out
    assert PT.fight_journal(fort(), m) == [] and PT.fight_journal(fort(sec), None) == []


@test("journal: wired into the cycle's journals")
def _():
    cyc = (ROOT / "brain" / "overseer_cycle.py").read_text(encoding="utf-8")
    assert "for e in fight_journal(state, memory):" in cyc and '"kind": "fight_watch"' in cyc


# --- (item3) the end_tantrums switch ---------------------------------------------

@test("settings: end_tantrums on by default, sent to the AI, on the Rules tab beside the fight watcher")
def _():
    st = src("ai-overseer-settings.lua")
    assert "        end_tantrums = true," in st and "'end_tantrums'," in st and "end_tantrums = s.end_tantrums," in st
    gui = src("gui/ai-overseer-rules.lua")
    assert "view_id = 'end_tantrums'" in gui and "frame = {t = t + 13, l = 78, w = 40}" in gui
    assert "self.subviews.end_tantrums:setOption(s.end_tantrums ~= false, false)" in gui
    label = re.search(r"view_id = 'end_tantrums',.*?label = '([^']*)',\s*label_width = (\d+)", gui, re.S)
    assert label and len(label.group(1)) < int(label.group(2)) <= 40 - 4, label
    assert player_rules({"settings": {}})["end_tantrums"] is True
    assert player_rules({})["end_tantrums"] is True
    assert player_rules({"settings": {"end_tantrums": False}})["end_tantrums"] is False


@test("rule: end_tantrums from the Rules sent when arming, and again while armed when the section differs")
def _():
    p = by_rule(plan(fort(OFF, end_tantrums=False), Memory())[0], "fight_watch")
    assert len(p) == 1 and p[0].action == {"type": "fight_watch", "on": True, "end_tantrums": False}, p
    p = by_rule(plan(fort(dict(ARMED, end_tantrums=True), end_tantrums=False), Memory())[0], "fight_watch")
    assert len(p) == 1 and p[0].action == {"type": "fight_watch", "on": True, "end_tantrums": False}, p
    p = by_rule(plan(fort(dict(ARMED, end_tantrums=False)), Memory())[0], "fight_watch")
    assert len(p) == 1 and p[0].action == {"type": "fight_watch", "on": True, "end_tantrums": True}, p
    assert not by_rule(plan(fort(dict(ARMED, end_tantrums=True)), Memory())[0], "fight_watch")
    assert not by_rule(plan(fort(dict(ARMED, end_tantrums=False), end_tantrums=False), Memory())[0], "fight_watch")
    assert not by_rule(plan(fort(ARMED, end_tantrums=False), Memory())[0], "fight_watch")   # an older bridge: no key


@test("journal: a tantrum ended counts as news")
def _():
    m = Memory()
    sec = {"armed": True, "counts": {"seen": 0, "capped": 0, "separated": 0, "tantrums_ended": 2}}
    out = PT.fight_journal(fort(sec), m)
    assert len(out) == 1 and out[0]["tantrums_ended"] == 2 and "tantrum" in out[0]["text"], out
    assert PT.fight_journal(fort(sec), m) == []


if __name__ == "__main__":
    finish()
