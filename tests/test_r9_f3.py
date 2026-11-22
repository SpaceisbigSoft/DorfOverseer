"""(r9, builder f3) Audit A7's people findings still open at 0.105.64:

  * 2   the evil weather's keep-in: its own guard at every report (a member
        thirsty or hungry let out and not taken back for a while; no keep-in
        call for a day: everyone out), its members in the society section, the
        planner letting strays out with no spell in memory;
  * 10  the hospital guard taken off when enemies can reach the dwarves;
  * 13  the AI's alarm up with no shelter fill on record: drawn again;
  * 14  refresh_shelter puts the old tiles back when the redraw finds none or
        fails; the alarm is never sounded into an AI shelter that covers nothing;
  * 16  crisis mode: the one-tantrum hold only in a small fort, the tantrums'
        clear level grows with the fort;
  * 17  the last resort convicts only disorderly-behaviour cases, never with
        no usable well for the jail's water.

    python tests/test_r9_f3.py
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402
from lua_modules_util import bridge_part_src, module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan, note_cycle, abs_tick  # noqa: E402
import planner_tantrums as PT  # noqa: E402
from planner_core import Proposal  # noqa: E402
import planner_weather as PW  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

DAY = 1200
CFG = dict(PLANNER_CONFIG)
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


def lua_test(name):
    def wrap(fn):
        def run():
            if LuaRuntime is None:
                skip("needs the lupa package (pip install lupa)")
            fn()
        return test(name)(run)
    return wrap


def _fake_src(file: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return node.value.value
    raise KeyError(name)


# --- 10. the hospital guard and the enemies --------------------------------------------

def guard_fort(enemies: bool):
    s = fort()
    s["tantrums"] = {"loose": 1, "berserk": 0, "possessed": 0, "dwarves": [], "chronic": 0,
                     "hospitals": [{"zone_id": 50, "x": 10, "y": 10, "z": 100}],
                     "squads": [{"id": 20, "members": 4, "calm": True, "ai_orders": 1, "player_orders": 0}],
                     "guards": [{"squad_id": 20, "zone_id": 50, "since": abs_tick(s)}]}
    s["others_on_map"]["threats"] = [{"id": 5, "invader": True, "can_reach_dwarves": True}] if enemies else []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1 if enemies else 0
    return s


@test("A7 10: a hospital guard on post is taken off at once when enemies can reach the dwarves")
def _():
    p = by_rule(plan(guard_fort(True), Memory())[0], "hospital_guard")
    assert p and p[0].action == {"type": "hospital_guard", "squad_id": 20, "release": True}, p
    assert "enemies" in p[0].reason and p[0].priority <= 0, p[0]
    # no enemies, a tantrum loose, on post today: kept
    assert not by_rule(plan(guard_fort(False), Memory())[0], "hospital_guard")


# --- 17. the last resort's conviction ---------------------------------------------------

def chronic_ready(wells: int = 1):
    s = fort()
    t = abs_tick(s)
    ticks = [t - 120 * DAY, t - 90 * DAY, t - 60 * DAY, t - 20 * DAY, t - 2 * DAY]
    r = {"id": 9, "name": "Goden", "year": 5, "n28": 0, "posts": [], "unmet": [], "bedroom": True,
         "ticks": ticks, "last": ticks[-1], "stress": "miserable"}
    s["tantrums"] = {"loose": 0, "berserk": 0, "possessed": 0, "dwarves": [r], "chronic": 1, "hospitals": [],
                     "squads": [], "guards": []}
    s["dwarves"]["needs_medical_care"] = 0
    s["justice"] = {"restraints": 3, "restraints_used": 0, "punish": {"n": 0, "beatings": 0, "prison": 0}}
    s["offices"] = {"offices": {"SHERIFF": {"held": ["Sheriff"]}}}
    s["settings"]["traits"] = dict(s["settings"].get("traits") or {}, justice=0)
    s["buildings"]["other"]["Well"] = wells
    return s


@test("A7 17: the last resort convicts disorderly-behaviour cases only; never with no usable well for the jail")
def _():
    p = by_rule(plan(chronic_ready(), Memory())[0], "chronic_convict")
    assert p and p[0].action == {"type": "convict", "max": 1, "unit_id": 9, "disorderly": True}, p
    s = chronic_ready(wells=0)
    props, notes = plan(s, Memory())
    assert not by_rule(props, "chronic_convict")
    assert any("no usable well" in n for n in notes if n.startswith("chronic")), notes
    assert "no usable well for the jail's water" in PT._convict_blockers(s, CFG, s["tantrums"]["dwarves"][0])


CONVICT_FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local units = {[1] = {id = 1}, [2] = {id = 2}}
local function crime(id, mode, who)
    return {id = id, mode = mode, criminal = who, accused = -1, site = 7, criminal_hf = 0,
            accused_hf = {assign = function() end},
            flags = {sentenced = false, needs_trial = true, discovered = true}, punishment = {hammerstrikes = 0}}
end
local list = {[0] = crime(10, 3, 1), [1] = crime(11, 5, 1), [2] = crime(12, 5, 2)}
setmetatable(list, {__len = function() return 3 end})
env.df = {global = {plotinfo = {site_id = 7, punishments = {}}, world = {crimes = {all = list}}},
          crime_type = {[3] = 'ProductionOrderViolation', [5] = 'DisorderlyBehavior'},
          unit = {find = function(id) return units[id] end}}
env.dfhack = {units = {isDead = function() return false end, isCitizen = function() return true end,
                       isAdult = function() return true end, getReadableName = function(u) return 'dwarf ' .. u.id end}}
env.txt = function(s) return s end
env.reject = function(e) return {ok = false, rejected = true, error = e} end
env.whole_number = function(v) return math.tointeger(v) end
env.CONVICT_PER_CALL_MAX = 5
local function grab(name, text)
    local s, e = text:find('\nfunction ' .. name .. '%(')
    local stop = text:find('\nend\n', e, true)
    return text:sub(s + 1, stop + 4)
end
return env, list, grab
"""


@lua_test("A7 17 bridge: convict with disorderly takes that culprit's disorderly-behaviour case, not an older one of another kind")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, lst, grab = lua.execute(CONVICT_FAKE, "")
    acts, rep = bridge_part_src("ai-bridge-actions"), bridge_part_src("ai-bridge-report-fort")
    for name, text in (("convict_busy", rep), ("convictable", rep), ("act_convict", acts)):
        lua.execute("local env, code = ...; assert(load(code, 'x', 't', env))()", env, grab(name, text))
    t = lua.table_from
    r = env.act_convict(t({"max": 1, "unit_id": 1, "dry_run": True}))
    assert r.ok and r.convicted[1].id == 10, "without disorderly: the oldest case of any kind (as before)"
    r = env.act_convict(t({"max": 1, "unit_id": 1, "disorderly": True, "dry_run": True}))
    assert r.ok and r.convicted[1].id == 11 and r.convicted[1].kind == "DisorderlyBehavior", dict(r)
    lua.execute("local l = ...; l[1].flags.needs_trial = false", lst)
    r = env.act_convict(t({"max": 1, "unit_id": 1, "disorderly": True, "dry_run": True}))
    assert not r.ok and "disorderly behaviour only" in r.error, dict(r)


# --- 16. crisis mode in a big fort -----------------------------------------------------

def big_fort(pop: int):
    s = fort()
    s["dwarves"]["total"] = pop
    s["dwarves"]["stress"] = {"content": pop}
    s.pop("tantrums", None)
    return s


@test("A7 16: held, a fort of 100 lets go with one tantrum in 14 days; a fort of 40 still holds for it")
def _():
    for pop, holds in ((100, False), (40, True)):
        s = big_fort(pop)
        m = Memory()
        m.crisis = {"since": abs_tick(s) - 20 * DAY, "why": ["x"]}
        m.tantrums = [[abs_tick(s) - 5 * DAY, "Kol"]]
        note_cycle(copy.deepcopy(s), m)
        assert bool(m.crisis) == holds, (pop, m.crisis)


@test("A7 16: held, the tantrums' clear level grows with the fort (5% of it, never past the level that starts it)")
def _():
    import crisis
    t0 = None
    for pop, n, holds in ((100, 4, False), (100, 5, True), (40, 4, True), (400, 9, False), (400, 10, True)):
        s = big_fort(pop)
        t0 = abs_tick(s)
        m = Memory()
        m.tantrums = [[t0 - (i + 1) * DAY, f"D{i}"] for i in range(n)]
        why = crisis.crisis_reasons(s, m, CFG, True)
        assert any("tantrums in 4 weeks" in w for w in why) == holds, (pop, n, why)


# --- 13. the alarm up with no fill on record ---------------------------------------------

@test("A7 13: the AI's alarm up and no shelter fill on record (memory lost): the shelter drawn again")
def _():
    from planner_society import _shelter_supply_rule
    s = fort()
    s["civ_alert"], s["civ_alert_shelter"] = True, "ai"
    props, notes = [], []
    _shelter_supply_rule(s, Memory(), props, notes)
    assert [p.action for p in props] == [{"type": "refresh_shelter"}], props
    # the player's own alarm burrow: nothing
    s["civ_alert_shelter"] = "player"
    props = []
    _shelter_supply_rule(s, Memory(), props, notes)
    assert props == []


# --- 2. the weather keep-in's guard ------------------------------------------------------

@test("A7 2 brain: civilians still kept in for the weather with no spell in memory: let out")
def _():
    s = fort()
    s["weather"] = {"rain": None}
    s.setdefault("society", {})["weather_keep_in"] = {"members": 6}
    props, notes = [], []
    PW._weather_rules(s, Memory(), CFG, props, notes)
    lets = [p for p in props if p.action == PW.LET_OUT]
    assert lets and "6 civilian(s)" in lets[0].reason, [(p.action, p.reason) for p in props]
    s["society"]["weather_keep_in"] = {"members": 0}
    props = []
    PW._weather_rules(s, Memory(), CFG, props, notes)
    assert not [p for p in props if p.action == PW.LET_OUT]


@test("A7 2 bridge: the keep-in's status is in the society section, behind its own pcall")
def _():
    src = bridge_part_src("ai-bridge-report-fort")
    assert "pcall(soc.weather_keep_in_status, txt)" in src and "out.weather_keep_in = wk" in src


if LuaRuntime:
    SOC = _fake_src("test_society.py", "FAKE")

    def soc():
        lua = LuaRuntime(unpack_returned_tuples=True)
        env, units, assigned, ntiles, g = lua.execute(SOC, module_src("ai-society.lua"))
        lua.execute("""local env = ...
            local b = {id = 9, name = 'AI shelter'}
            env.df.global.plotinfo.burrows.list[#env.df.global.plotinfo.burrows.list] = b
            env.dfhack.burrows.listBlocks = function() return {1, 2} end
            env.shelter_for_keep_in = function(force) return {tiles = 30, redrawn = force} end""", env)
        return lua, env, units, assigned, g


@lua_test("A7 2 bridge: at a report, a thirsty member is let out and not kept in again for a day")
def _():
    lua, env, units, assigned, g = soc()
    r = env.weather_keep_in(True, False)
    assert r.ok and assigned[1], dict(r)
    n = r.members
    lua.execute("local u = ...; u.counters2 = {thirst_timer = 30000, hunger_timer = 0}", units[1])
    st = env.weather_keep_in_status()
    assert st.members == n - 1 and not assigned[1] and st.released_now, dict(st)
    r = env.weather_keep_in(True, False)               # the resend: not taken back yet
    assert not assigned[1] and r.members == n - 1, dict(r)
    lua.execute("local g = ...; g.cur_year_tick = g.cur_year_tick + 1300", g)
    lua.execute("local u = ...; u.counters2 = {thirst_timer = 0, hunger_timer = 0}", units[1])
    env.weather_keep_in(True, False)
    assert assigned[1]


@lua_test("A7 2 bridge: no keep-in call for a day: everyone let out at the report")
def _():
    lua, env, units, assigned, g = soc()
    assert env.weather_keep_in(True, False).ok
    assert env.weather_keep_in_status().members > 0
    lua.execute("local g = ...; g.cur_year_tick = g.cur_year_tick + 1200", g)
    st = env.weather_keep_in_status()
    assert st.members == 0 and st.released_stale and "no keep-in call" in st.why, dict(st)
    assert not any(assigned[i] for i in range(1, 8)), dict(assigned)
    assert env.weather_keep_in_status().members == 0


# --- 14. refresh_shelter and the alarm ----------------------------------------------------

if LuaRuntime:
    SHELTER_FAKE = _fake_src("test_construct_gates.py", "SHELTER_FAKE")

    def shelter():
        lua = LuaRuntime(unpack_returned_tuples=True)
        rule = lua.eval("function() return true, false end")
        env, got = lua.execute(SHELTER_FAKE, module_src("ai-society.lua"), 2, rule, False)
        lua.execute("""local env, set = ...
            env.dfhack.burrows.listBlocks = function(b)
                local out = {}
                for _, blk in ipairs(env.df.global.world.map.map_blocks) do
                    for k, on in pairs(set) do
                        if on and k:match(',' .. blk.map_pos.z .. '$') then table.insert(out, blk); break end
                    end
                end
                return out
            end
            env.dfhack.burrows.isAssignedBlockTile = function(b, blk, x, y)
                return set[(blk.map_pos.x + x) .. ',' .. (blk.map_pos.y + y) .. ',' .. blk.map_pos.z] == true
            end""", env, got)
        return lua, env, got

    def count(got):
        return sum(1 for k in got.keys() if got[k])


@lua_test("A7 14: a redraw that finds no tiles, or fails part-way, puts the old shelter back and says so")
def _():
    lua, env, got = shelter()
    r = env.refresh_shelter()
    whole = count(got)
    assert r.refreshed and r.tiles == whole and whole > 0, dict(r)
    lua.execute("local env = ...; env.fill_shelter = function() return 0, {} end", env)
    r = env.refresh_shelter()
    assert r.ok is False and r.refreshed is False and r.kept_old and r.tiles == whole, dict(r)
    assert "no inside tiles" in r.error and count(got) == whole
    lua.execute("""local env, set = ...
        env.fill_shelter = function(b)
            set['96,144,160'] = true
            error('boom')
        end""", env, got)
    r = env.refresh_shelter()
    assert r.ok is False and "failed: " in r.error and count(got) == whole, dict(r)
    assert not env.shelter_empty()
    lua.execute("local set = ...; for k in pairs(set) do set[k] = nil end", got)
    assert env.shelter_empty()


@test("A7 14: the alarm is not sounded into an AI shelter that covers nothing; a refresh that failed is ok = false")
def _():
    acts = bridge_part_src("ai-bridge-actions")
    i = acts.index("function act_civ_alert(a)")
    body = acts[i:acts.index("\nend\n", i)]
    assert body.index("shelter_empty()") < body.index("civ.sound_alarm()"), "checked before sounding"
    assert "the alarm not sounded" in body
    fort_ = bridge_part_src("ai-bridge-actions-fort")
    assert "if r.ok == nil then r.ok = true end" in fort_


finish()
