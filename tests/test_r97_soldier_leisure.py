"""(0.105.97) Soldiers get time to make friends, drink and pray.

Live 23 Nov, B "Monastery" (Militarism -60, ~40% unhappy): the soldiers were
30 of the 32 badly missing drink, and 37 of the 76 of 88 badly wanting
friends; 2 of 3 squads trained at all times and the recreation burrow took
civilians only. Now, while a fifth of the soldiers badly miss friends (in an
unhappy fort), drink or prayer and no threat can reach the dwarves: half the
squads train at most (one at least), a squad most of whose members are short
rests a turn more, and off-duty soldiers get a few days in the recreation
burrow (out when the squad goes back on duty).

    python tests/test_r97_soldier_leisure.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

from planner import Memory, PLANNER_CONFIG  # noqa: E402
from planner_core import abs_tick, TICKS_PER_DAY  # noqa: E402
import planner_leisure as PL  # noqa: E402
from planner_military_squads import _training_rotation  # noqa: E402
from planner_society import _recreation_rule  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = dict(PLANNER_CONFIG)
UNHAPPY = {"content": 30, "fine": 10, "unhappy": 20, "very_unhappy": 3, "miserable": 2}     # B: ~40%
HAPPY = {"content": 50, "fine": 5, "happy": 30, "unhappy": 2}


def needs(**badly_soldiers):
    return {"needs": {k: {"badly": v, "badly_soldiers": v, "distracted": v} for k, v in badly_soldiers.items()}}


def fort(n_squads=3, members=10, stress=None, short=None, routine="Constant training", **need):
    """B-like: `n_squads` squads of `members`; `short`: per squad (short, short_np)."""
    s = copy.deepcopy(BASE)
    s["dwarves"]["stress"] = dict(stress or UNHAPPY)
    s["dwarves"]["total"] = sum(s["dwarves"]["stress"].values())
    s["dwarves"]["in_squads"] = n_squads * members
    s["needs"] = needs(**need)
    s["military"]["routines"] = ["Off duty", "Staggered training", "Constant training", "Ready"]
    s["military"]["squads"] = [{"id": 10 + i, "name": f"Squad {10 + i}", "members": members, "size": 10,
                                "orders": 0, "ai_orders": 0, "routine": routine} for i in range(n_squads)]
    s.setdefault("society", {})["recreation"] = {"members": 0}
    if short is not None:
        s["society"]["recreation"]["squads"] = {str(10 + i): {"n": members, "short": a, "short_np": b}
                                                for i, (a, b) in enumerate(short)}
    return s


def rotate(s, m=None):
    m = m or Memory()
    if not m.squads_trained:
        m.squads_trained = [q["id"] for q in s["military"]["squads"]]
        m.squads_rested = [q["id"] for q in s["military"]["squads"]]
    p = []
    _training_rotation(s, m, s["military"]["squads"], "Constant training", "Off duty", CFG, p)
    return {x.action["squad_id"]: x.action["routine"] for x in p}, p, m


def training_after(s, moved):
    out = []
    for q in s["military"]["squads"]:
        r = moved.get(q["id"], q["routine"])
        if "off duty" not in r.lower():
            out.append(q["id"])
    return out


# --- the need counted -------------------------------------------------------

@test("BeWithFriends counts for soldiers in an unhappy fort (B: 37 of 40), never in a happy one (A: 54 of 59)")
def _():
    s = fort(4, 10, stress=UNHAPPY, BeWithFriends=37)
    assert PL.friends_counted(s, CFG)
    assert PL.soldiers_short_of_leisure(s, CFG) == "BeWithFriends"
    s = fort(6, 10, stress=HAPPY, BeWithFriends=54)
    s["dwarves"]["in_squads"] = 59
    assert not PL.friends_counted(s, CFG)
    assert PL.soldiers_short_of_leisure(s, CFG) == ""
    # drink tops friends when more soldiers miss it; a few missing friends alone don't
    s = fort(4, 10, DrinkAlcohol=30, BeWithFriends=20)
    assert PL.soldiers_short_of_leisure(s, CFG) == "DrinkAlcohol"
    s = fort(4, 10, BeWithFriends=10)                    # a quarter: under the friends' third
    assert PL.soldiers_short_of_leisure(s, CFG) == ""


@test("company_short: the squads' own counts (one soldier once), friends only in an unhappy fort; the needs' max without them")
def _():
    s = fort(3, 10, short=[(8, 2), (6, 1), (1, 0)])
    assert PL.company_short(s, CFG) == 15
    s = fort(3, 10, stress=HAPPY, short=[(8, 2), (6, 1), (1, 0)])
    assert PL.company_short(s, CFG) == 0                  # 3 of 30 without friends: under a fifth
    s = fort(3, 10, stress=HAPPY, short=[(8, 4), (6, 3), (1, 0)])
    assert PL.company_short(s, CFG) == 7
    s = fort(3, 10, DrinkAlcohol=12, PrayOrMeditate=4)    # an older bridge: the most of any one need
    assert PL.company_short(s, CFG) == 12
    s = fort(3, 10, DrinkAlcohol=4)
    assert PL.company_short(s, CFG) == 0
    s = fort(3, 10, DrinkAlcohol=12)
    s["dwarves"]["in_squads"] = 0
    assert PL.company_short(s, CFG) == 0
    assert PL.squad_mostly_short(fort(3, 10, short=[(6, 0), (5, 5), (0, 0)]), CFG, 10)
    assert not PL.squad_mostly_short(fort(3, 10, short=[(6, 0), (5, 5), (0, 0)]), CFG, 11)
    assert not PL.squad_mostly_short(fort(3, 10, stress=HAPPY, short=[(6, 0)]), CFG, 10)
    assert not PL.squad_mostly_short(fort(3, 10, DrinkAlcohol=20), CFG, 10)     # no squad counts


# --- the rotation -----------------------------------------------------------

@test("B's 3 squads: 2 train at a time; with a fifth of the soldiers short, 1 (half at most, one at least)")
def _():
    s = fort(3, 10)
    moved, _, _ = rotate(s)
    assert len(training_after(s, moved)) == 2, moved
    s = fort(3, 10, DrinkAlcohol=10)
    moved, p, _ = rotate(s)
    assert len(training_after(s, moved)) == 1, moved
    assert any("half the squads train at most" in x.reason for x in p), [x.reason for x in p]


@test("two squads short: one keeps training; four: two; no shortage leaves 4 at 2 and a fort's MartialTraining rush is capped")
def _():
    s = fort(2, 10, DrinkAlcohol=10)
    moved, _, _ = rotate(s)
    assert len(training_after(s, moved)) == 1, moved
    s = fort(4, 10, DrinkAlcohol=10)
    moved, _, _ = rotate(s)
    assert len(training_after(s, moved)) == 2, moved
    s = fort(4, 10)
    moved, _, _ = rotate(s)
    assert len(training_after(s, moved)) == 2, moved
    # many soldiers longing to train would put all 4 on: while short, still 2
    s = fort(4, 10, MartialTraining=40, DrinkAlcohol=10)
    moved, _, _ = rotate(s)
    assert len(training_after(s, moved)) == 2, moved


@test("a resting squad most of whose soldiers are short isn't sent back: another trains; a turn later it goes")
def _():
    s = fort(4, 10, routine="Off duty", short=[(8, 8), (8, 8), (8, 8), (0, 0)])
    m = Memory()
    moved, _, m = rotate(s, m)
    assert training_after(s, moved) == [13], moved          # the one squad not short; the others rest on
    assert set(m.leisure_hold) == {"10", "11", "12"}, m.leisure_hold
    first = dict(m.leisure_hold)
    moved, _, m = rotate(s, m)                               # the hold keeps its start
    assert m.leisure_hold == first and training_after(s, moved) == [13]
    # a turn on (28 days) the holds have run out: two train again (half of 4)
    for k in m.leisure_hold:
        m.leisure_hold[k] = abs_tick(s) - 29 * TICKS_PER_DAY
    moved, _, m = rotate(s, m)
    on2 = training_after(s, moved)
    assert len(on2) == 2, (moved, on2)
    # kept while the squad still rests (its routine changes by the next report)
    assert all(str(x) in m.leisure_hold for x in on2 if x != 13), m.leisure_hold


@test("every squad resting and short: one still trains; nobody short: no hold kept")
def _():
    s = fort(2, 10, routine="Off duty", short=[(9, 9), (9, 9)])
    moved, _, m = rotate(s)
    assert len(training_after(s, moved)) == 1, moved
    s = fort(3, 10, routine="Off duty")
    m = Memory()
    m.leisure_hold = {"10": abs_tick(s)}
    moved, _, m = rotate(s, m)
    assert not m.leisure_hold and len(training_after(s, moved)) == 2, (m.leisure_hold, moved)


@test("many idle hands don't put every squad on training while the soldiers miss drink (company_short)")
def _():
    import planner_military
    src = (ROOT / "brain" / "planner_military.py").read_text(encoding="utf-8")
    assert "not company_short(s, cfg)" in src
    assert planner_military  # imported cleanly


# --- the recreation burrow ----------------------------------------------------

def rec(s, memory=None):
    p = []
    _recreation_rule(s, CFG, [], p, memory or Memory())
    return [x for x in p if x.rule == "recreation"]


@test("recreation: off-duty soldiers short of drink get places (a quarter of the short, 4 at least), a few days each")
def _():
    s = fort(4, 10, short=[(8, 8), (8, 8), (8, 8), (8, 8)])
    s["military"]["squads"][0]["routine"] = "Off duty"
    p = rec(s)
    assert p and p[0].action["soldiers"] == 8 and p[0].action["soldier_days"] == 5, p
    assert "soldiers off duty a few days" in p[0].reason
    s = fort(4, 10, DrinkAlcohol=10)
    s["military"]["squads"][0]["routine"] = "Off duty"
    p = rec(s)
    assert p and p[0].action["soldiers"] == 4, p


@test("recreation: no squad off duty, or nobody short: no soldiers' places; a threat empties the burrow")
def _():
    s = fort(4, 10, DrinkAlcohol=10)                      # all on constant training
    assert all("soldiers" not in x.action for x in rec(s))
    s = fort(4, 10)
    s["military"]["squads"][0]["routine"] = "Off duty"
    assert all("soldiers" not in x.action for x in rec(s))
    s = fort(4, 10, DrinkAlcohol=10)
    s["military"]["squads"][0]["routine"] = "Off duty"
    s["society"]["recreation"]["members"] = 3
    s.setdefault("others_on_map", {})["threats_that_can_reach_dwarves"] = 2
    p = rec(s)
    assert p and p[0].action.get("release") is True and "soldiers" not in p[0].action, p


@test("recreation: while the fort's own fight, two soldiers at most")
def _():
    s = fort(4, 10, short=[(8, 8)] * 4)
    s["military"]["squads"][0]["routine"] = "Off duty"
    m = Memory()
    m.fight_deaths = [abs_tick(s) - TICKS_PER_DAY]
    p = rec(s, m)
    assert p and p[0].action["soldiers"] == 2, p


# --- the bridge -------------------------------------------------------------------

BURROWS = (ROOT / "lua" / "ai-society-burrows.lua").read_text(encoding="utf-8")
WORKS = (ROOT / "lua" / "ai-bridge-actions-works.lua").read_text(encoding="utf-8")
CIVIC = (ROOT / "lua" / "ai-bridge-actions-civic.lua").read_text(encoding="utf-8")
POSTS = (ROOT / "lua" / "ai-society-posts.lua").read_text(encoding="utf-8")


@test("the bridge: recreation takes soldiers 0-10 for 2-14 days; a squad back on duty lets its soldiers out at once")
def _():
    assert "int_in(a.soldiers or 0, 0, 10), int_in(a.soldier_days or 5, 2, 14)" in WORKS
    assert "release, unhappy, soldiers, soldier_days)" in BURROWS
    assert "recreation_release_squad(id, txt)" in CIVIC and "'off duty', 1, true" in CIVIC
    assert "'recreation_release_squad'" in POSTS
    # a soldier member is kept only while the squad is off duty, under no order
    assert "if not squad_free(u.military.squad_id) then return false, 'back on duty', u end" in BURROWS
    assert "if d.soldiers then d.soldiers[id] = nil end" in BURROWS
    for f in ("ai-society-burrows.lua", "ai-bridge-actions-works.lua", "ai-bridge-actions-civic.lua",
              "ai-society-posts.lua"):
        assert (ROOT / "lua" / f).stat().st_size < 60 * 1024, f


def _lua_tests():
    try:
        from lupa.lua53 import LuaRuntime
    except ImportError:
        print("SKIPPED: the bridge's soldier places need the lupa package (pip install lupa)")
        return
    import ast
    from lua_modules_util import module_src
    tree = ast.parse((ROOT / "tests" / "test_society.py").read_text(encoding="utf-8"))
    fake = next(n.value.value for n in tree.body if isinstance(n, ast.Assign)
                and any(getattr(t, "id", None) == "FAKE" for t in n.targets))

    def world():
        lua = LuaRuntime(unpack_returned_tuples=True)
        env, units, assigned, ntiles, g = lua.execute(fake, module_src("ai-society.lua"))
        # unit 3 is in squad 7, off duty, badly missing drink; unit 7 a civilian missing friends
        lua.execute("""local env, units = ...
          env.df.need_type = {[1] = 'DrinkAlcohol', [2] = 'BeWithFriends', [3] = 'PrayOrMeditate'}
          local function needs(list) return {current_soul = {personality = {needs = list}}} end
          units[3].status = needs({{id = 1, focus_level = -20000}, {id = 2, focus_level = 500}})
          units[7].status = needs({{id = 2, focus_level = -15000}})
          SQUADS = {[7] = {orders = {}, cur_routine_idx = 0}}
          env.df.squad = {find = function(id) return SQUADS[id] end}
          env.df.global.plotinfo.alerts = {routines = {[0] = {name = 'Off duty'}, [1] = {name = 'Constant training'}}}
          env.SQUADS = SQUADS""", env, units)
        return lua, env, units, assigned

    @test("bridge (lupa): an off-duty soldier short of drink moved in as a soldier; counted by squad in the status")
    def _():
        lua, env, units, assigned = world()
        r = env.recreation_tick(1, 28, False, None, 0, 7, False, False, 2, 5)
        assert r.ok and assigned[3], (dict(r), dict(assigned))
        added = [r.added[i] for i in range(1, len(r.added) + 1)]
        assert "dwarf 3 (soldier off duty)" in added, added
        st = env.recreation_status()
        assert st.for_soldiers == 1 and st.squads["7"].short == 1 and st.squads["7"].short_np == 1, dict(st)

    @test("bridge (lupa): the squad back on duty or under an order: its soldier let out (report and squad_routine)")
    def _():
        lua, env, units, assigned = world()
        env.recreation_tick(1, 28, False, None, 0, 7, False, False, 2, 5)
        assert assigned[3]
        lua.execute("local env = ...; env.SQUADS[7].cur_routine_idx = 1", env)
        st = env.recreation_status()
        assert not assigned[3] and st.released_now, dict(st)
        lua, env, units, assigned = world()
        env.recreation_tick(1, 28, False, None, 0, 7, False, False, 2, 5)
        out = env.recreation_release_squad(7)
        assert not assigned[3] and len(out) == 1
        lua, env, units, assigned = world()
        lua.execute("local env = ...; env.SQUADS[7].cur_routine_idx = 1", env)
        r = env.recreation_tick(1, 28, False, None, 0, 7, False, False, 2, 5)
        assert not assigned[3], dict(r)                  # on duty: never moved in


_lua_tests()

if __name__ == "__main__":
    finish()
