"""(0.105.97) A celled or known killer is kept: never pulled out of their
cell by other rules, never drafted, swapped in or appointed.

Live 23 Nov, B ("Monastery", no jail: the killer cells are burrows on the
killers' bedrooms): the recreation rule added the celled Degel (unit 17329)
and Fath Shemnish (17255) to the recreation burrow (taverns, temples) at
20:30 and 20:47 (a dwarf in several burrows may go to any of them);
`appoint` made Fath (2 kills, celled) MILITIA_CAPTAIN of squad 214 at 21:03;
`soldier_swap` had drafted him into squad 182 at 18:37. Degel killed again at
21:18 inside hospital zone 333.

The brain (brain/planner_killers.py held_killer_ids) skips them before it
proposes; the bridge (lua/ai-killers.lua held_ids / is_held) refuses them in
every burrow, squad and office rule as the last guard, and the cell takes a
killer out of every other burrow, the squad and any military office
(keep_apart).

    python tests/test_r97_killers_kept.py
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
import harness  # noqa: E402
from harness import test, finish, need_lua  # noqa: E402

from planner import Memory, PLANNER_CONFIG as cfg  # noqa: E402
from planner_core import _soldier_swap, recently_home  # noqa: E402
from planner_society import _recreation_rule  # noqa: E402
from planner_office_swap import _office_swap_rule  # noqa: E402
from planner_training import stress_train  # noqa: E402
import planner_killers as PK  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LUA = ROOT / "lua"

DEGEL, FATH = 17329, 17255
KILLERS = {"list": [{"id": FATH, "name": "Fath Shemnish", "kind": "killer", "confidence": "strong", "citizen": True,
                     "kills": 2, "cell": {"kind": "bedroom"}},
                    {"id": DEGEL, "name": "Degel", "kind": "killer", "confidence": "strong", "citizen": True,
                     "kills": 3, "cell": {"locked": True, "kind": "bedroom"}},
                    {"id": 40, "name": "Brawler", "kind": "killer", "confidence": "weak", "citizen": True, "brawls": 1},
                    {"id": 41, "name": "Sheriff", "kind": "killer", "confidence": "strong", "citizen": True,
                     "kills": 2, "law": True},
                    {"id": 42, "name": "Child", "kind": "killer", "confidence": "strong", "citizen": True,
                     "kills": 2, "child": True},
                    {"id": 43, "name": "Vamp", "kind": "vampire", "confidence": "certain", "citizen": True}],
           "cells": [{"unit_id": FATH, "out": True, "kind": "bedroom"},
                     {"unit_id": DEGEL, "locked": True, "kind": "bedroom"},
                     {"unit_id": 44, "locked": True, "kind": "jail"}],
           "rooms": 3}


def fort(killers=KILLERS):
    s = copy.deepcopy(BASE)
    if killers is not None:
        s["killers"] = copy.deepcopy(killers)
    return s


# --- the brain ---------------------------------------------------------------------------

@test("held_killer_ids: every cell, every strong or certain suspect; never the weak, a child or the law")
def _():
    assert PK.held_killer_ids(fort()) == {FATH, DEGEL, 43, 44}
    assert PK.held_killer_ids(fort(None)) == set()
    assert PK.held_killer_ids(fort({"list": [], "cells": [{"unit_id": True}, {"unit_id": "7"}]})) == set()


@test("recreation (B: Degel and Fath moved in): the held never counted; the rule asks only for the others")
def _():
    s = fort()
    p = []
    _recreation_rule(s, cfg, [{"id": DEGEL, "stress": "miserable"}, {"id": FATH, "stress": "very_unhappy"}], p, Memory())
    assert p == [], [(x.action, x.reason) for x in p]
    _recreation_rule(s, cfg, [{"id": DEGEL, "stress": "miserable"}, {"id": 9, "stress": "very_unhappy"}], p, Memory())
    assert len(p) == 1 and p[0].reason.startswith("1 civilian(s) very unhappy"), [(x.action, x.reason) for x in p]


def swap_fort():
    s = fort()
    s.setdefault("needs", {})
    s["needs"]["keen_civilians"] = 20
    s["needs"]["starved_soldiers"] = [{"id": FATH, "name": "Fath Shemnish", "unmet": ["DrinkAlcohol", "PrayOrMeditate"]},
                                      {"id": 5, "name": "Urist", "unmet": ["DrinkAlcohol"]}]
    return s


@test("soldier_swap (B: Fath drafted by a swap's fill): never names a held killer; the fill passes them over")
def _():
    s = swap_fort()
    p = []
    _soldier_swap(s, cfg, p, None)
    assert len(p) == 1 and p[0].action["unit_id"] == 5 and "Fath" not in p[0].reason, [(x.action, x.reason) for x in p]
    assert set(p[0].action["avoid"]) == {FATH, DEGEL, 43, 44}, p[0].action
    s["needs"]["starved_soldiers"] = s["needs"]["starved_soldiers"][:1]
    p = []
    _soldier_swap(s, cfg, p, None)
    assert p == [], [(x.action, x.reason) for x in p]


@test("squad_fill and every fill's avoid (recently_home): the held killers first, with or without memory")
def _():
    s = fort()
    assert recently_home(s, None) == sorted({FATH, DEGEL, 43, 44})
    m = Memory()
    m.swapped = {"5": 0}
    from planner_core import abs_tick
    m.swapped = {"5": abs_tick(s)}
    got = recently_home(s, m)
    assert got[:4] == sorted({FATH, DEGEL, 43, 44}) and 5 in got, got
    assert recently_home(fort(None), None) == []


@test("stress care: a held killer longing to train is never put in the training squad")
def _():
    s = fort()
    s.setdefault("dwarves", {})["adults"] = 60
    s["settings"].setdefault("traits", {})["welfare"] = 100
    s["military"]["training_squads"] = [{"id": 300, "name": "The Trainees", "members": 1, "size": 10}]
    s.setdefault("others_on_map", {})["threats_that_can_reach_dwarves"] = 0
    x = {"id": 9, "name": "Urist", "stress": "miserable", "unmet": ["MartialTraining"]}
    assert stress_train(s, cfg, x, None) is not None                  # the rule itself would draft
    x = dict(x, id=FATH, name="Fath Shemnish")
    assert stress_train(s, cfg, x, None) is None


@test("appoint (B: Fath made militia captain): no office swap or messenger takeover for a held killer")
def _():
    s = fort()
    s["offices"] = {"offices": {},
                    "swap": {"BOOKKEEPER": {"holder": "Kib", "holder_unit": 4, "holder_score": 0,
                                            "cand": "Fath Shemnish", "cand_unit": FATH, "cand_score": 15}},
                    "messenger": {"interim": True, "free_unit": FATH, "free_name": "Fath Shemnish", "held_by": "Kib"}}
    p, n = [], []
    _office_swap_rule(s, cfg, p, n, Memory())
    assert p == [] and not any("Fath" in x for x in n), ([(x.action, x.reason) for x in p], n)
    s2 = copy.deepcopy(s)
    s2["killers"] = {"list": [], "cells": []}
    p, n = [], []
    _office_swap_rule(s2, cfg, p, n, Memory())
    assert [x.action.get("office") for x in p] == ["BOOKKEEPER"], [(x.action, x.reason) for x in p]


@test("killer rule: one locked in a cell but still in a squad: the cell action is asked (it takes them out)")
def _():
    row = {"id": DEGEL, "name": "Degel", "kind": "killer", "confidence": "strong", "citizen": True, "kills": 3,
           "seen_ticks": 5000, "cell": {"locked": True}}
    s = fort({"list": [row], "cells": [{"unit_id": DEGEL, "locked": True}], "rooms": 1})
    p, n = [], []
    PK._killer_rule(s, cfg, p, n)
    assert p == [], [(x.action, x.reason) for x in p]                    # as it should be: nothing asked
    s["killers"]["list"][0]["squad_id"] = 214
    PK._killer_rule(s, cfg, p, n)
    assert [x.action for x in p] == [{"type": "killer_cell", "units": [DEGEL]}], [(x.action, x.reason) for x in p]
    assert "still in a squad" in p[0].reason


# --- the bridge: each rule's guard in place --------------------------------------------------

def src(name):
    return (LUA / name).read_text(encoding="utf-8")


def body(text, head):
    i = text.index(head)
    j = text.find("\nfunction ", i + 1)
    k = text.find("\nlocal function ", i + 1)
    ends = [e for e in (j, k) if e > 0]
    return text[i:min(ends) if ends else len(text)]


@test("bridge: draftable, seat_leader, the office candidates and write_appointment refuse a held killer first")
def _():
    draft = src("ai-military-draft.lua")
    d = body(draft, "function draftable(")
    assert "reqscript('ai-killers').is_held(u)" in d and d.index("is_held(u)") < d.index("local ok, yes = pcall"), d
    sl = body(draft, "function seat_leader(")
    assert sl.index("is_held(u)") < sl.index("sq.positions[0].occupant = hf.id")
    nob = src("ai-nobles.lua")
    c = body(nob, "local function candidates(")
    assert "held_ids()" in c and "not held[u.id]" in c, c
    w = body(nob, "function write_appointment(")
    assert w.index("is_held(u)") < w.index("assignment.histfig = hf.id")


@test("bridge: the recreation (and for friends), calm-down, hospital, weather and near-gates burrows skip the held")
def _():
    hub = src("ai-society-burrows.lua")
    assert "function killer_held(u)" in hub and "reqscript('ai-killers').is_held(u)" in hub
    assert "killer_held(u)" in body(hub, "local function rec_base(")          # both the low mood and for friends
    assert "killer_held(u)" in body(hub, "local function rec_keep(")          # a member let out
    calm = src("ai-society-burrows-calm.lua")
    assert "killer_held(u)" in body(calm, "function calm_burrow_tick(")
    assert "killer_held(u)" in body(calm, "local function calm_maintain(")
    hosp = src("ai-society-burrows-hospital.lua")
    assert "killer_held(u)" in body(hosp, "local function hb_eligible(")
    assert "killer_held(u)" in body(hosp, "local function hb_maintain(")
    assert "killer_held(u)" in body(src("ai-society-burrows-weather.lua"), "function weather_keep_in(")
    assert "is_held(u)" in body(src("ai-near-gates.lua"), "function set(")


@test("bridge: the cell keeps the killer apart (every cycle it runs); the touched files compile; under 60 KB")
def _():
    k = src("ai-killers.lua")
    cell = body(k, "function cell(")
    assert "keep_apart" in cell and "#out.apart" in cell
    for name in ("ai-killers.lua", "ai-military-draft.lua", "ai-nobles.lua", "ai-society-burrows.lua",
                 "ai-society-burrows-calm.lua", "ai-society-burrows-hospital.lua",
                 "ai-society-burrows-weather.lua", "ai-near-gates.lua"):
        assert len(src(name).encode("utf-8")) < 60 * 1024, name
    need_lua()
    from lupa.lua53 import LuaRuntime
    f = LuaRuntime().eval("function(s) local f, e = load(s, 'b', 't', {}) return e end")
    for name in ("ai-killers.lua", "ai-military-draft.lua", "ai-nobles.lua", "ai-society-burrows.lua",
                 "ai-society-burrows-calm.lua", "ai-society-burrows-hospital.lua",
                 "ai-society-burrows-weather.lua", "ai-near-gates.lua"):
        assert f(src(name)) is None, (name, f(src(name)))


# --- the bridge in a fake fort (lupa) --------------------------------------------------------

def _fake(file: str, name: str) -> str:
    """A fake's Lua source from another test file, read without running it."""
    tree = ast.parse((ROOT / "tests" / file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return node.value.value
    raise KeyError(name)


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


def killers_world():
    from lupa.lua53 import LuaRuntime
    from lua_modules_util import module_src
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(_fake("test_item3_killers.py", "FAKE"), module_src("ai-killers.lua"))
    return lua, env, w


@test("lua held_ids / is_held: the cells and the strong or certain seen; never the weak or the exempt")
def _():
    need_lua()
    lua, env, w = killers_world()
    w.site["ai-overseer/killers"] = T(lua, {"cells": {"44": {"zone": 500}},
                                           "seen": {"5": {"confidence": "strong"}, "6": {"confidence": "weak"},
                                                    "7": {"confidence": "certain"},
                                                    "8": {"confidence": "strong", "exempt": True}}})
    ids = py(env.held_ids())
    assert sorted(ids) == [5, 7, 44], ids
    assert env.is_held(5) is True and env.is_held(6) is False and env.is_held(None) is False
    assert env.is_held(T(lua, {"id": 44})) is True and env.is_held(T(lua, {"id": 8})) is False


@test("lua report: the sheriff and a child are marked exempt in the save (never held), the murderer is not")
def _():
    need_lua()
    lua, env, w = killers_world()
    w.unit(T(lua, {"id": 3, "name": "Murd", "citizen": True}))
    w.unit(T(lua, {"id": 5, "name": "Sheriff", "citizen": True, "positions": [{"position": {"code": "SHERIFF"}}]}))
    for i, (k, v) in enumerate([(3, 20), (3, 21), (5, 22), (5, 23)]):
        w.unit(T(lua, {"id": v, "name": f"Victim {v}", "is_dead": True}))
        w.incidents[i + 1] = T(lua, {"criminal": k, "victim": v, "death_cause": 7, "conflict_level": 6,
                                     "event_year": 300, "event_time": 0})
    env.report()
    seen = py(w.site["ai-overseer/killers"])["seen"]
    assert seen["5"].get("exempt") is True and not seen["3"].get("exempt"), seen
    assert sorted(py(env.held_ids())) == [3]


@test("lua cell: the killer taken out of the recreation burrow, the squad and the captain's post; a moon cell kept")
def _():
    need_lua()
    lua, env, w = killers_world()
    u = w.unit(T(lua, {"id": 3, "name": "Murd", "citizen": True, "pos": {"x": 10, "y": 10, "z": 100},
                       "military": {"squad_id": 214}, "hist_figure_id": 77, "burrows": [90, 91]}))
    w.dungeons[1] = T(lua, {"id": 500, "x1": 20, "y1": 20, "x2": 22, "y2": 22, "z": 100, "assigned_unit_id": -1})
    rec = T(lua, {"id": 90, "name": "AI recreation", "units": {3: True}, "tiles": {}})
    moon = T(lua, {"id": 91, "name": "AI moon cell 3", "units": {3: True}, "tiles": {}})
    lua.execute("""local env, W, rec, moon = ...
        W.burrows[#W.burrows + 1] = rec
        W.burrows[#W.burrows + 1] = moon
        env.df.global.plotinfo.burrows.next_id = 100
        local ent = {positions = {own = {{id = 5, code = 'MILITIA_CAPTAIN'}, {id = 6, code = 'BROKER'}},
                                  assignments = {{id = 1, position_id = 5, histfig = 77}, {id = 2, position_id = 6, histfig = 77}}}}
        env.ENT = ent
        env.df.historical_figure = {find = function(id) if id == 77 then return {id = 77} end end}
        env.dfhack.military = {removeFromSquad = function(id)
            local u = env.df.unit.find(id); u.military.squad_id = -1; return true end}
        local old = env.reqscript
        env.reqscript = function(n, ...)
            if n == 'ai-nobles' then
                return {MILITARY_OFFICES = {MILITIA_CAPTAIN = true, MILITIA_COMMANDER = true},
                        undo_appointment = function(a) a.histfig = -1 end, sync_held = function() end}
            end
            return old(n, ...)
        end
        env.reqscript('ai-util').fort_entity = function() return ent end""", env, w, rec, moon)
    r = py(env.cell(T(lua, {"units": [3]}), True))                       # a dry run says, changes nothing
    assert r["placed"] == ["Murd"] and r["apart"] and u.military.squad_id == 214 and rec.units[3] is True, r
    r = py(env.cell(T(lua, {"units": [3]}), False))
    assert r["placed"] == ["Murd"], r
    assert r["apart"] == ["Murd: out of burrow AI recreation, out of squad 214, off the militia captain"], r
    assert rec.units[3] is None and moon.units[3] is True and u.military.squad_id == -1
    ent = env.ENT
    assert ent.positions.assignments[1].histfig == -1 and ent.positions.assignments[2].histfig == 77
    u.burrows = T(lua, [])
    r = py(env.cell(T(lua, {"units": [3]}), False))
    assert r["waiting"] == ["Murd"] and not r["apart"], r                # nothing more to take them out of


@test("lua recreation (B: Degel and Fath moved in): a held killer is never moved in and a member is let out")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    from lua_modules_util import module_src
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, units, assigned, ntiles, g = lua.execute(_fake("test_society.py", "FAKE"), module_src("ai-society.lua"))
    lua.execute("""local env = ...
        HELD = {}
        local old = env.reqscript
        env.reqscript = function(n, ...)
            if n == 'ai-killers' then return {is_held = function(u) return HELD[u.id] == true end} end
            return old(n, ...)
        end
        HELD[1] = true""", env)
    r = env.recreation_tick(8, 28, False)
    assert not assigned[1] and assigned[2] and assigned[7], dict(assigned)
    lua.execute("HELD[2] = true")
    s = env.recreation_status()
    assert not assigned[2] and s.members == 1, dict(s)


finish()
