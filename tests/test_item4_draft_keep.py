"""(item4) Who the fill keeps at their work, and a peaceful fort hides from a beast.

B, 24 Nov 16:45-16:48 (Militarism -60, Piety 150, Welfare 80; 41 adults, 19
in squads, 54% unhappy; 14 soldiers badly missing friends, a drink and
prayer): squad_fill "14 soldiers, the fort wants 16 (defence floor)" drafted
Fath (the tavern keeper), Kadol (a diagnoser) and Kosoth (a bone doctor),
the day two doctors were strangled with 2 patients waiting. The threat: a
forgotten beast in the caverns and an evil cloud on the surface, so the
floor's cap was the third of the adults.

1. The fill (lua/ai-military-draft.lua) never drafts a location post's
   holder (u.occupations), a dwarf with a hospital labour while the fort
   has 3 or fewer outside the squads or a patient waits, the very unhappy
   (draft_bar; the training squad still takes them) or a recent
   tantrum-thrower; the result counts who was kept out by reason
   (kept_out, kept_names, kept_note).
2. Below Militarism 0 a great danger that is no invasion, sheltered from or
   out of reach, keeps the floor's cap at the Militarism share
   (planner_defence_floor.hidden_from); an invasion, or a danger reaching
   the dwarves with no shelter, lifts it to the third. The guard (3 for 15+
   adults) stands.

    python tests/test_item4_draft_keep.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
from planner_military import soldiers_wanted  # noqa: E402
import planner_defence_floor as DF  # noqa: E402
from digest import normalize  # noqa: E402

CFG = dict(PLANNER_CONFIG)
DAY = 1200
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LUA = ROOT / "lua"


def fort(mil=-60, adults=41, threats=None, squads=None, alert=False, ready=False) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["settings"]["traits"] = {"militarism": mil}
    s["dwarves"].update(total=adults, adults=adults, idle_adults=0)
    s["needs"] = {"needs": {}, "stressed": []}
    s["others_on_map"]["threats"] = threats or []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = sum(1 for t in threats or [] if t.get("can_reach_dwarves"))
    s["civ_alert"] = alert
    s["civ_alert_ready"] = ready
    if squads is not None:
        s["military"]["squads"] = squads
        s["military"]["soldiers"] = sum(q.get("members") or 0 for q in squads)
    return normalize(s)


def squad(sid, members, power):
    return {"id": sid, "name": f"Squad {sid}", "members": members, "size": 10, "leader": True,
            "routine": "Staggered training", "orders": 0, "ai_orders": 0, "power": {"power": power, "armed": members}}


def beast(reach=True, i=7000):
    return {"id": i, "name": "Ngokang, Forgotten Beast", "great_danger": True, "kinds": ["ForgottenBeast"],
            "size": 60000 * 20, "layer": "cavern_1", "can_reach_dwarves": reach}


def goblins(n=6, reach=True):
    return [{"id": 9000 + i, "name": "goblin", "invader": True, "kinds": ["Goblin"], "size": 60000,
             "can_reach_dwarves": reach} for i in range(n)]


WEAK = [squad(1, 7, 14.0), squad(2, 7, 14.0)]      # 14 soldiers at 2 a soldier


@test("hidden_from: Militarism -60, a beast and no invasion, the alarm up: the civilians hide (the peaceful share)")
def _():
    s = fort(threats=[beast()], squads=WEAK, alert=True)
    why = DF.hidden_from(s, Memory(), CFG)
    assert "no invasion" in why and "the alarm keeps the civilians in the shelter" in why, why
    f = DF.defence_floor(s, Memory(), CFG, 41)
    assert f["present"] > 0 and abs(f["cap_share"] - 0.12) < 1e-9 and f["cap"] == int(41 * 0.12) == 4, f
    assert f["soldiers"] == 4 and f["hidden"] == why, f
    # the shelter ready (the alarm sounds for it), or the weather burrow keeping them in: the same
    s2 = fort(threats=[beast()], squads=WEAK, ready=True)
    assert "the shelter is ready" in DF.hidden_from(s2, Memory(), CFG)
    m = Memory()
    m.weather_alarm = {"kept_in": DF.abs_tick(s) - 10}
    s3 = fort(threats=[beast()], squads=WEAK)
    assert "the weather burrow" in DF.hidden_from(s3, m, CFG)
    # a beast that can't reach the dwarves: hidden from with no shelter at all
    s4 = fort(threats=[beast(reach=False)], squads=WEAK)
    assert "can't reach the dwarves" in DF.hidden_from(s4, Memory(), CFG)


@test("hidden_from: an invasion, a danger reaching the dwarves with no shelter, the player's cleared alarm, Militarism 0: the third")
def _():
    for s, m in [(fort(threats=[beast()] + goblins(), squads=WEAK, alert=True), Memory()),   # a siege as well
                 (fort(threats=goblins(), squads=WEAK, alert=True), Memory()),
                 (fort(threats=[beast()], squads=WEAK), Memory()),                            # no shelter
                 (fort(mil=0, threats=[beast()], squads=WEAK, alert=True), Memory())]:
        assert DF.hidden_from(s, m, CFG) == "", DF.hidden_from(s, m, CFG)
        f = DF.defence_floor(s, m, CFG, 41)
        assert f["cap"] == int(41 * 0.33) == 13 and f["hidden"] is None, f
    m = Memory()
    m.alert_suppressed = [7000]                 # the player cleared the alert for it: no alarm will sound
    s = fort(threats=[beast()], squads=WEAK, ready=True)
    assert DF.hidden_from(s, m, CFG) == ""
    # switched off in the config: the third as before
    assert DF.hidden_from(fort(threats=[beast()], alert=True), Memory(), dict(CFG, floor_hide_from_beasts=False)) == ""


@test("the guard stands while the civilians hide: 3 soldiers for 15+ adults at Militarism -100")
def _():
    s = fort(mil=-100, adults=20, threats=[beast()], squads=[], alert=True)
    assert DF.hidden_from(s, Memory(), CFG)
    assert soldiers_wanted(s, 20, CFG, memory=Memory()) >= CFG["guard_min_soldiers"] == 3


@test("plan() (B, 24 Nov): the floor note says why the cap stays at the Militarism share; the fill asks only that")
def _():
    s = fort(threats=[beast()], squads=WEAK, alert=True)
    p, notes = plan(s, Memory())
    line = [n for n in notes if n.startswith("Defence floor")]
    assert line and line[0].startswith("Defence floor 4 (cap 4 = 12% of the adults at Militarism -60: Ngokang, "
                                       "no invasion: the alarm keeps the civilians in the shelter"), line
    assert "hide rather than being drafted" in line[0], line
    assert not [x for x in p if x.rule == "squad_fill"], [x.reason for x in p]    # 14 soldiers: none drafted
    f = DF.defence_floor(s, Memory(), CFG, 41)
    note = DF.floor_note(f, 14, 3)
    assert "cap 4 = 12% of the adults at Militarism -60: Ngokang" in note and "hide rather than being drafted" in note, note


# --- the bridge --------------------------------------------------------------------------------

def src(name: str) -> str:
    return (LUA / name).read_text(encoding="utf-8")


@test("bridge: the fill keeps out a post's holder, a needed healer, the very unhappy; the result counts them by reason")
def _():
    d = src("ai-military-draft.lua")
    assert "HOSPITAL_LABORS = {'DIAGNOSE', 'SURGERY', 'BONE_SETTING', 'SUTURING', 'DRESSING_WOUNDS'}" in d
    assert "HOSPITAL_FEW = 3" in d and "function post_bar(u, care)" in d and "function care_need()" in d
    assert "if okc and cat == 1 then return 'very unhappy' end" in d
    assert "kept_out = barred > 0 and by_why or nil" in d and "kept_note = barred > 0" in d
    assert "not draft_bar(c.unit) and not post_bar(c.unit, care)" in d          # the leader's seat too
    # no local copies of ai-util's helpers (tests/test_r6_c1.py)
    for name in ("now_tick", "name_of"):
        assert f"local function {name}" not in d


# A fake game: the fill run in it; the case returns "ok" (lupa here, texlua by hand)
FILL_CASE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local LEDGER = {units = {}}
local T = {STAFF_DAYS = 28, YEAR = 403200, DAY = 1200, CHRONIC = 3}
function T.load() return LEDGER end
function T.count(d, id, days, now)
    local r = d.units[tostring(id)]
    local n = 0
    for _, t in ipairs(r and r.t or {}) do if now - t >= 0 and now - t < days * 1200 then n = n + 1 end end
    return n
end
env.reqscript = function(name) if name == 'ai-tantrums' then return T end error('no module ' .. name) end
assert(load(src, 'ai-military', 't', env))()
local added = {}
local function vec(t) t = t or {}; return setmetatable(t, {__len = function(v) local n = 0
    while rawget(v, n) ~= nil do n = n + 1 end return n end}) end
local function zl(...) local t = {}; for i, v in ipairs({...}) do t[i - 1] = v end return vec(t) end
local LAB = {DIAGNOSE = 1, SURGERY = 2, BONE_SETTING = 3, SUTURING = 4, DRESSING_WOUNDS = 5, PLANT = 20, BREWER = 30}
local function dwarf(id, o)
    o = o or {}
    local labors = {}
    for _, l in ipairs(o.labors or {}) do labors[LAB[l]] = true end
    local needs = o.keen and zl({id = 5, focus_level = -20000}) or zl()      -- badly wants to train
    return {id = id, stress = o.stress or 4, military = {squad_id = o.squad or -1}, relationship_ids = {Mother = -1},
            occupations = o.post and zl({type = o.post}) or zl(), counters = {soldier_mood = -1},
            status = {labors = labors, current_soul = {skills = zl(), personality = {needs = needs}}},
            health = o.waits and {flags = {needs_healthcare = true, rq_diagnosis = true}} or nil}
end
local citizens
local sq
local function squad(open)
    local ps = {{occupant = 99}}
    for i = 1, open do ps[#ps + 1] = {occupant = -1} end
    sq = {id = 10, orders = zl(), positions = zl(table.unpack(ps))}
end
env.ipairs = function(t)
    if getmetatable(t) then return function(v, i) i = i + 1; if rawget(v, i) ~= nil then return i, v[i] end end, t, -1 end
    return ipairs(t)
end
env.df = {squad = {find = function(id) return id == 10 and sq or nil end}, job_skill = {}, need_type = {[5] = 'MartialTraining'},
    unit_labor = LAB, occupation_type = {[0] = 'TAVERN_KEEPER', [1] = 'DOCTOR'},
    soldier_mood_type = {[-1] = 'None'},
    global = {plotinfo = {group_id = 1}, cur_year = 100, cur_year_tick = 0},
    historical_entity = {find = function() return {squads = zl(10)} end}}
env.dfhack = {units = {getCitizens = function() return citizens end, isAdult = function() return true end,
        isBaby = function() return false end, getNoblePositions = function() return {} end,
        getStressCategory = function(u) return u.stress end, getReadableName = function(u) return 'd' .. u.id end},
    military = {addToSquad = function(id) table.insert(added, id); return true end}}
local function got() local t = {}; for _, v in ipairs(added) do t[#t + 1] = v end; table.sort(t); return table.concat(t, ',') end

-- B: the tavern keeper, two healers (2 outside the squads, a patient waiting), one very unhappy
-- who badly wants to train (draftable lets the keen past; draft_bar keeps them out now),
-- one with a tantrum 10 days ago, two plain dwarves
local now = 100 * 403200
LEDGER.units['8'] = {t = {now - 10 * 1200}}
citizens = {dwarf(1, {post = 0}), dwarf(2, {labors = {'DIAGNOSE'}}), dwarf(3, {labors = {'BONE_SETTING'}}),
            dwarf(4), dwarf(5), dwarf(6, {stress = 1, keen = true}), dwarf(7, {waits = true}), dwarf(8)}
squad(8)
local r = env.fill(10, 6, tostring)
assert(r.ok and got() == '4,5', got())
assert(r.kept_out['a post'] == 1 and r.kept_out['the hospital'] == 2, 'by reason')
assert(r.kept_out['very unhappy'] == 1 and r.kept_out['a recent tantrum'] == 1, 'by reason')
assert(r.kept_note == '5 kept out: 1 a post, 1 a recent tantrum, 2 the hospital, 1 very unhappy', r.kept_note)
assert(#r.kept_names == 5 and r.kept_names[1] == 'd1: holds a post (tavern keeper)', r.kept_names[1])

-- five healers outside the squads, nobody waiting: two may go (3 stay), the rest are kept
added = {}
citizens = {dwarf(2, {labors = {'DIAGNOSE'}}), dwarf(3, {labors = {'SURGERY'}}), dwarf(9, {labors = {'SUTURING'}}),
            dwarf(10, {labors = {'DRESSING_WOUNDS'}}), dwarf(11, {labors = {'BONE_SETTING'}})}
squad(8)
r = env.fill(10, 5, tostring)
assert(r.ok and #added == 2, got())
assert(r.kept_out['the hospital'] == 3, tostring(r.kept_out and r.kept_out['the hospital']))

-- the same five with a patient waiting: none of them
added = {}
table.insert(citizens, dwarf(12, {waits = true}))
squad(8)
r = env.fill(10, 5, tostring)
assert(not r.ok and #added == 0 and r.kept_out['the hospital'] == 5, tostring(r.error))
assert(tostring(r.error):find('5 kept out: 5 the hospital', 1, true), tostring(r.error))
return 'ok'
"""


@test("lua fill: a post, the hospital (3 or fewer, or a patient waiting), the very unhappy, a tantrum kept out and counted")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    assert lua.execute(FILL_CASE, module_src("ai-military.lua")) == "ok"


if __name__ == "__main__":
    finish()
