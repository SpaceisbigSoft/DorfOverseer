"""(0.105.97) The defence floor follows the fort's character and lets go
once a threat is long gone (brain/planner_defence_floor.py): with no threat
on the map the cap falls with Militarism below 0 (a third at 0, 12% at -50
and below); a threat here now keeps the third; the remembered peak and the
history are kept two years, then fade to nothing; the soldiers above the
want go home a few a day, the unhappiest and those badly missing friends,
a drink or prayer first, never a squad's captain (lua/ai-military-draft.lua
trim).

The live case: B ("Monastery", Militarism -60, 23 Nov): Stuxul's 184.3 a
year gone kept 46 for good; the weak soldiers made the floor ask the 33% cap
("13 soldiers, the fort wants 32 (defence floor)").

    python tests/test_r97_floor_character.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src, split_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
from planner_military import soldiers_wanted  # noqa: E402
import planner_defence_floor as DF  # noqa: E402
from digest import normalize  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = dict(PLANNER_CONFIG)
DAY = 1200
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort(mil=-60, adults=57, threats=None, squads=None) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["settings"]["traits"] = {"militarism": mil}
    s["dwarves"].update(total=adults, adults=adults, idle_adults=0)
    s["needs"] = {"needs": {}, "stressed": []}
    s["others_on_map"]["threats"] = threats or []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = sum(1 for t in threats or [] if t.get("can_reach_dwarves"))
    if squads is not None:
        s["military"]["squads"] = squads
        s["military"]["soldiers"] = sum(q.get("members") or 0 for q in squads)
    return normalize(s)


def squad(sid, members, power):
    return {"id": sid, "name": f"Squad {sid}", "members": members, "size": 10, "leader": True,
            "routine": "Staggered training", "orders": 0, "ai_orders": 0, "power": {"power": power, "armed": members}}


def beast(i=7000, size=60000 * 20, reach=True):
    # (item4) reaching the dwarves, no shelter: the third; one that can't reach is hidden from
    return {"id": i, "name": 'Stuxul "The Vile", Forgotten Beast', "great_danger": True,
            "kinds": ["ForgottenBeast"], "size": size, "layer": "cavern_1", "can_reach_dwarves": reach}


WEAK = [squad(1, 9, 18.0), squad(2, 9, 18.0)]      # B's soldiers: 2 a soldier, 18 in all


def b_memory(s, days_ago=403) -> Memory:
    m = Memory()
    m.defence_floor = {"peak": {"power": 184.3, "tick": DF.abs_tick(s) - days_ago * DAY, "why": "Stuxul on the map"}}
    return m


@test("B: Militarism -60, 57 adults, Stuxul's 184.3 403 days gone: a floor of at most 12% of the adults")
def _():
    s = fort(squads=WEAK)
    m = b_memory(s)
    f = DF.defence_floor(s, m, CFG, 57)
    assert f["threat"] == 46.1 or abs(f["threat"] - 184.3 * 0.25) < 0.1, f     # the quarter kept (under two years)
    # (item8) 403 quiet days: the cap has eased to the slider's own share (7% at -60): int(57 x .07) = 3
    assert f["wanted"] == 24 and f["cap"] == 3 and f["soldiers"] == 3, f
    assert abs(f["cap_share"] - 0.07) < 1e-9 and f["quiet_days"] == 403, f
    assert soldiers_wanted(s, 57, CFG, memory=m) == 4               # the slider's 4 (7% of 57)
    assert soldiers_wanted(s, 57, CFG, memory=Memory()) == 4
    # a fortnight after the beast was last on the map: the 12% cap (the easing above it)
    m.defence_floor["present_tick"] = DF.abs_tick(s) - 14 * DAY
    f = DF.defence_floor(s, m, CFG, 57)
    assert f["cap"] == int(57 * 0.12) == 6 and f["soldiers"] == 6, f
    assert soldiers_wanted(s, 57, CFG, memory=m) == 6


@test("the cap by Militarism: a third at 0 and above, a straight line to 12% at -50, 12% below")
def _():
    for mil, share in [(100, 0.33), (0, 0.33), (-25, 0.225), (-50, 0.12), (-60, 0.12), (-100, 0.12)]:
        got = DF.floor_cap_share(fort(mil=mil), CFG, 0.0)
        assert abs(got - share) < 1e-9, (mil, got)
    # a threat on the map now: the third, whatever the slider (survival first)
    assert DF.floor_cap_share(fort(mil=-100), CFG, 5.0) == CFG["floor_max_share"]


@test("a beast on the map now that can reach the dwarves, no shelter: the full 33% cap at Militarism -60")
def _():
    s = fort(threats=[beast()], squads=WEAK)
    s["civ_alert_ready"] = False                     # (item4) no shelter to hide in
    f = DF.defence_floor(s, b_memory(s), CFG, 57)
    assert f["present"] > 0 and f["cap"] == int(57 * 0.33) == 18 and f["soldiers"] == 18, f


@test("three years after the peak: the floor is gone (no permanent floor from one beast); the guard stays")
def _():
    s = fort(squads=WEAK)
    m = b_memory(s, days_ago=3 * 336)
    f = DF.defence_floor(s, m, CFG, 57)
    assert f["threat"] < 1 and f["soldiers"] == 0, f
    assert soldiers_wanted(s, 57, CFG, memory=m) == 4           # the slider's 7%
    # at -100 the guard's 3 (the slider's 5% of 40 = 2)
    s2 = fort(mil=-100, adults=40)
    assert soldiers_wanted(s2, 40, CFG, memory=b_memory(s2, days_ago=3 * 336)) == 3
    # the fade: whole for two years, then halving each season
    assert DF._fade(600, CFG) == 1.0 and DF._fade(672, CFG) == 1.0
    assert abs(DF._fade(672 + 84, CFG) - 0.5) < 1e-9
    assert DF._fade(672 + 4 * 84, CFG) == 0.0


@test("history fades too: sieges by the game year of the last one, great dangers by last_great_tick")
def _():
    s = fort(mil=0, adults=40)
    year = s["date"]["year"]
    m = Memory()
    m.culture = {"sieges": 2, "last_siege_year": year - 1}
    assert DF.history_threat(s, m, CFG)[0] == 50.0                # within two years: whole
    m.culture["last_siege_year"] = year - 3                       # 3 years: 336 days past the keep: 1/16 -> gone
    assert DF.history_threat(s, m, CFG)[0] == 0.0
    m.culture["last_siege_year"] = year - 2 - 0                   # exactly two years: whole
    assert DF.history_threat(s, m, CFG)[0] == 50.0
    # the world report's last_year counts (an older memory)
    s2 = copy.deepcopy(s)
    s2["world"] = {"sieges": [{"id": 5, "n": 1, "last_year": year - 5}]}
    assert DF.history_threat(s2, Memory(), CFG)[0] == 0.0
    # no year known: not faded (as before)
    s2["world"] = {"sieges": [{"id": 5, "n": 1}]}
    assert DF.history_threat(s2, Memory(), CFG)[0] == 40.0
    # a great danger seen long ago fades from memory.last_great_tick
    m = Memory()
    m.last_great_tick = DF.abs_tick(s) - 10
    assert DF.history_threat(s, m, CFG)[0] == 30.0
    m.last_great_tick = DF.abs_tick(s) - (672 + 84) * DAY
    p, why = DF.history_threat(s, m, CFG)
    assert p == 15.0 and "fading" in why, (p, why)


@test("plan(): B's 18 soldiers over the floor's 6: a trim, and the note says the cap and the fade")
def _():
    s = fort(squads=WEAK)
    m = b_memory(s)
    m.defence_floor["present_tick"] = DF.abs_tick(s) - 14 * DAY      # (item8) a fortnight quiet: the floor binds
    p, notes = plan(s, m)
    line = [n for n in notes if n.startswith("Defence floor")]
    assert line, notes
    assert "12% of the adults at Militarism -60" in line[0] and "24 to match" in line[0], line
    assert "fading from 184" in line[0] and "403 days ago" in line[0] and "let go after 672 days" in line[0], line
    trims = [x for x in p if x.rule == "squad_trim"]
    assert trims and trims[0].action["count"] == CFG["max_trim_per_cycle"], [x.reason for x in p]
    assert CFG["squad_trim_cooldown_ticks"] == DAY                # a few a day
    # past two years the note says it is being forgotten
    s2 = fort(squads=WEAK)
    f = DF.defence_floor(s2, b_memory(s2, days_ago=700), CFG, 57)
    assert "being forgotten" in f["why"], f
    # a beast here now: no trim (the floor is the third)
    s3 = fort(threats=[beast()], squads=WEAK)
    p3, _n = plan(s3, b_memory(s3))
    assert not [x for x in p3 if x.rule == "squad_trim"]


TRIM_FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
env.df = {global = {plotinfo = {group_id = 1}},
          need_type = {[1] = 'BeWithFriends', [2] = 'DrinkAlcohol', [3] = 'PrayOrMeditate', [4] = 'Craftsmanship'},
          unit_labor = {PLANT = 20, BREWER = 30}, job_skill = {[1] = 'AXE', [2] = 'MASON'}}
env.dfhack = {units = {isAdult = function(u) return true end}}
env.require = function() return {} end
assert(load(src, 'm', 't', env))()
return env
"""


@test("bridge: trim sends home the unhappiest and those badly missing friends, drink, prayer first; never a captain")
def _():
    src = split_src("ai-military.lua")
    assert "trim_misery(u)" in src and "a.misery > b.misery" in src
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(TRIM_FAKE, module_src("ai-military.lua"))
    lua.eval("""function(env)
        local function unit(id, needs, stress, skills)
            local ns = {}
            for i, n in ipairs(needs) do ns[i] = {id = n[1], focus_level = n[2]} end
            local sk = {}
            for i, k in ipairs(skills or {}) do sk[i] = {id = k[1], rating = k[2]} end
            return {id = id, hist_figure_id = 100 + id, stress = stress, military = {squad_id = 7},
                    status = {current_soul = {personality = {needs = ns}, skills = sk}}}
        end
        local units = {
            [1] = unit(1, {}, 4, {{2, 10}}),                          -- content, a mason: least suited
            [2] = unit(2, {{2, -20000}, {1, -20000}}, 4, {{1, 15}}),  -- badly missing drink and friends
            [3] = unit(3, {{3, -20000}}, 1, {{1, 15}}),               -- unhappy and missing prayer
            [4] = unit(4, {{2, -20000}, {1, -20000}, {3, -20000}}, 0, {}),   -- the captain: never
            [5] = unit(5, {{4, -20000}}, 4, {{1, 5}}),                -- a craft need only: not counted
        }
        env.dfhack.units.isCitizen = function(u) return true end
        env.dfhack.units.getStressCategory = function(u) return u.stress end
        env.dfhack.units.getReadableName = function(u) return 'dwarf ' .. u.id end
        env.dfhack.military = {removeFromSquad = function(id) return true end}
        env.df.unit = {find = function(id) return units[id] end}
        env.df.historical_figure = {find = function(hf) return {unit_id = hf - 100} end}
        local sq = {id = 7, orders = {}, positions = {[0] = {occupant = 104}, {occupant = 101}, {occupant = 102},
                                                      {occupant = 103}, {occupant = 105}}}
        env.df.squad = {find = function(id) return id == 7 and sq or nil end}
        env.df.historical_entity = {find = function() return {squads = {7}} end}
        env.reqscript = function() error('no such script') end
    end""")(env)
    r = env.trim(4, True, None)
    assert r.ok, r.error
    got = [r.removed[i].unit_id for i in range(1, len(r.removed) + 1)]
    assert got == [3, 2, 1, 5], got             # misery 3, 2, then the least suited; the captain (4) never
    assert 4 not in got
    assert env.trim_misery(lua.eval("function(env) return env.df.unit.find(4) end")(env)) == 5


finish()
