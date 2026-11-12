"""(0.105.40b) Fire breathers: the bridge marks a threat that breathes, spits
or hurls fire (its caste's raws, one answer per race and caste), and the
brain never sends a melee squad at one: crossbows only, from inside the
AI's shut gates; the dwarves hide meanwhile (the alarm, the gates, the
squads in the shelter); a note says why. Fixtures without the flag: the
same plan as before.

    python tests/test_r41_firebreath.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, code_has  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

from planner import Memory, plan, PLANNER_CONFIG  # noqa: E402
import planner_firebreath as PF  # noqa: E402
from planner_army import hiding  # noqa: E402
from planner_gates import few_ordinary, lone_intruders, hunted_outside  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def acts(props, rule=None, typ=None):
    return [p for p in props if (rule is None or p.rule == rule) and (typ is None or p.action.get("type") == typ)]


def kills(props):
    return [p for p in props if p.action.get("type") == "squad_orders" and isinstance(p.action.get("kill"), list)]


def fort(*, breather=True, great=True, ranged=False, gates_shut=False, inside=False, goblin=False,
         policy=None, squad_on=None) -> dict:
    """A dragon (or a fire imp, great=False) that can reach the dwarves, two
    armed melee squads (one crossbow squad with ranged=True)."""
    s = copy.deepcopy(BASE)
    t = {"id": 5000, "name": "Ostuk the dragon" if great else "fire imp", "can_reach_dwarves": True,
         "great_danger": great, "flier": great, "destroyer": great, "invader": False, "layer": "surface",
         "distance_to_nearest_dwarf": 15, "levels_from_nearest_dwarf": 0, "size": 25_000_000 if great else 30_000,
         "kinds": ["Megabeast"] if great else None}
    if breather:
        t["fire_breather"], t["fire_how"] = True, "breath" if great else "fireball"
    th = [t]
    if goblin:
        th.append({"id": 6000, "name": "goblin", "can_reach_dwarves": True, "invader": True, "layer": "surface",
                   "distance_to_nearest_dwarf": 10})
    s["others_on_map"]["threats"] = th
    s["others_on_map"]["threats_that_can_reach_dwarves"] = len(th)
    for q in s["military"]["squads"]:
        q["power"] = {"power": 5000, "armed": 10}
    if ranged:
        s["military"]["squads"][1]["ai_uniform"] = "AI crossbows"
    if squad_on is not None:
        q = s["military"]["squads"][0]
        q["ai_orders"], q["kill_ids"] = 1, list(squad_on)
    ent = s["entrances"]
    if gates_shut:
        ent["armed"] = True
        ent["entrances"] = [{"id": 1, "kind": "surface", "x": 31, "y": 140, "z": 173, "width": 1, "sealed": True,
                             "closed": True, "equipment": [{"id": 500, "kind": "door"}], "door_spots": 0}]
    ent["intruders_inside"] = [5000] if inside else []
    if policy:
        s["settings"]["attack_policy"] = policy
    return s


def at_dragon(props):
    return [p for p in kills(props) if 5000 in p.action["kill"]]


# --- the bridge: the raws read ----------------------------------------------------------

FAKE = r"""
local src, races = ...
local env = setmetatable({}, {__index = _G})
local interactions = {}
local units = {[5000] = {race = 1, caste = 0}, [6000] = {race = 5, caste = 0}, [7000] = {race = 2, caste = 0}}
env.df = {
    breath_attack_type = {NONE = -1, TRAILING_DUST_FLOW = 0, WEB_SPRAY = 8, DRAGONFIRE = 9, FIREJET = 10, FIREBALL = 11},
    interaction = {find = function(id) return interactions[id] end},
    creature_raw = {find = function(id) return races[id] end},
    unit = {find = function(id) return units[id] end},
    global = {world = {units = {active = {}}}},
}
env.dfhack = {units = {}, maps = {}, persistent = {}}
assert(load(src, 'ai-threats', 't', env))()
env.FINDS = 0
local real = env.df.creature_raw.find
env.df.creature_raw.find = function(id) env.FINDS = env.FINDS + 1; return real(id) end
env.interactions = interactions
return env
"""

RACES = r"""
local function cdi(breath, type_id) return {type = 1, interaction = {material_breath = breath, type_id = type_id or -1}} end
local function caste(list, flags) return {body_info = {interactions = list}, flags = flags or {}} end
return {
    [1] = {caste = {[0] = caste({cdi(9)}), [1] = caste({cdi(9)})}},                -- dragon: DRAGONFIRE
    [2] = {caste = {[0] = caste({cdi(-1, 77), cdi(11)})}},                        -- fire imp: FIREBALL
    [3] = {caste = {[0] = caste({cdi(8)})}},                                      -- a web spinner: WEB_SPRAY
    [4] = {caste = {[0] = caste({cdi(-1, 40)})}},                                 -- a beast: its interaction's target jets fire
    [5] = {caste = {[0] = caste({})}},                                            -- a goblin
    [6] = {caste = {[0] = caste({}, {IMMOLATE = true})}},                         -- burns to the touch
}
"""


def lua_env():
    lua = LuaRuntime(unpack_returned_tuples=True)
    races = lua.execute(RACES)
    env = lua.execute(FAKE, module_src("ai-threats.lua"), races)
    env.interactions[40] = lua.execute("return {targets = {{breath_attack_type = 10}}}")
    env.interactions[77] = lua.execute("return {targets = {{}}}")
    return lua, env


@test("bridge: fire_breath_of reads the caste's abilities (DRAGONFIRE, FIREBALL, an interaction's FIREJET, "
      "IMMOLATE), not webs or nothing; one read per race and caste; a missing race is false")
def _():
    if LuaRuntime is None:
        return
    _, env = lua_env()
    f = env.fire_breath_of
    assert f(1, 0) == "breath" and f(2, 0) == "fireball" and f(4, 0) == "jet" and f(6, 0) == "burns"
    assert f(3, 0) is False and f(5, 0) is False and f(99, 0) is False
    n = env.FINDS
    assert f(1, 0) == "breath" and f(1, 1) == "breath" and env.FINDS == n + 1, (env.FINDS, n)   # 1:1 new, 1:0 kept


@test("bridge: mark_fire_breathers marks the others_on_map threats (fire_breather, fire_how), nothing on "
      "the others; the section wired through safe(); ai-bridge-report untouched")
def _():
    bridge = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert code_has(bridge, "pcall(function() reqscript('ai-threats').mark_fire_breathers(o) end)")
    assert code_has(bridge, "others_on_map = function() return safe(function() local o = get_others_on_map()")
    assert "fire_breath" not in (LUA_DIR / "ai-bridge-report.lua").read_text(encoding="utf-8")
    if LuaRuntime is None:
        return
    lua, env = lua_env()
    o = lua.execute("return {threats = {{id = 5000}, {id = 6000}, {id = 7000}, {id = 8000}, {name = 'x'}}}")
    assert env.mark_fire_breathers(o) == 2
    t = o.threats
    assert t[1].fire_breather is True and t[1].fire_how == "breath"
    assert t[2].fire_breather is None and t[2].fire_how is None
    assert t[3].fire_breather is True and t[3].fire_how == "fireball"
    assert t[4].fire_breather is None and t[5].fire_breather is None
    assert env.mark_fire_breathers(lua.execute("return {}")) == 0 and env.mark_fire_breathers(None) == 0


# --- the brain -------------------------------------------------------------------------

@test("a dragon in reach, melee squads only: no kill order names it, no fight weighed; the alarm and a note why")
def _():
    s = fort()
    props, notes = plan(s, Memory())
    assert not at_dragon(props), [(p.rule, p.action) for p in kills(props)]
    assert acts(props, "threat_alert", "civ_alert") and acts(props, typ="civ_alert")[0].action["on"] is True
    assert any("no melee squad is sent at it" in n and "Ostuk" in n for n in notes), notes
    assert not any("the squads go" in n for n in notes), notes


@test("a fire imp (no great danger) in reach: no melee squad either; not a lone intruder or one of a few "
      "ordinary enemies, so the alarm and gates aren't lifted early")
def _():
    s = fort(great=False, inside=True)
    m = Memory()
    props, notes = plan(s, m)
    assert not at_dragon(props), [(p.rule, p.action) for p in kills(props)]
    assert lone_intruders(s, PLANNER_CONFIG, None, m) == [] and few_ordinary(s, PLANNER_CONFIG) == []
    assert hunted_outside(s, PLANNER_CONFIG) == []
    # the same imp without the flag: the lone-intruder squad goes, as before
    s2 = fort(great=False, inside=True, breather=False)
    assert lone_intruders(s2, PLANNER_CONFIG, None, m) == [5000]
    props2, _ = plan(s2, Memory())
    assert at_dragon(props2), [(p.rule, p.action) for p in props2]


@test("a dragon and a goblin: the squads go at the goblin only")
def _():
    s = fort(goblin=True)
    props, notes = plan(s, Memory())
    ks = kills(props)
    assert ks and all(5000 not in p.action["kill"] and 6000 in p.action["kill"] for p in ks), \
        [(p.rule, p.action) for p in ks]


@test("a crossbow squad, the AI's gates shut, the dragon outside: it shoots from inside; the melee squad doesn't go")
def _():
    s = fort(ranged=True, gates_shut=True)
    props, notes = plan(s, Memory())
    d = at_dragon(props)
    assert len(d) == 1 and d[0].action["squad_id"] == 12, [(p.rule, p.action) for p in kills(props)]
    assert any("shoots at it from inside the shut gates" in n for n in notes), notes
    sh = acts(props, typ="shelter_squads")
    assert all(12 not in p.action["squads"] for p in sh), [p.action for p in sh]


@test("crossbows not sent while the gates are open, nor at one inside the fort, nor at Rules: never")
def _():
    for kw, word in ((dict(ranged=True), "the gates are open"),
                     (dict(ranged=True, gates_shut=True, inside=True), "inside the fort"),
                     (dict(ranged=True, gates_shut=True, policy="never"), "Rules tab: never")):
        props, notes = plan(fort(**kw), Memory())
        assert not at_dragon(props), (kw, [(p.rule, p.action) for p in kills(props)])
        assert any(word in n for n in notes), (kw, notes)


@test("a melee squad already on the dragon is called back; a crossbow one on it from inside stays")
def _():
    props, notes = plan(fort(squad_on=[5000]), Memory())
    rec = [p for p in acts(props, "squad_recall") if p.action.get("squad_id") == 11]
    assert rec and rec[0].action == {"type": "squad_orders", "squad_id": 11, "clear": True}, \
        [(p.rule, p.action) for p in props if p.action.get("type") == "squad_orders"]
    s = fort(ranged=True, gates_shut=True)
    q = s["military"]["squads"][1]
    q["ai_orders"], q["kill_ids"] = 1, [5000]
    props, _ = plan(s, Memory())
    assert not [p for p in props if p.action.get("type") == "squad_orders" and p.action.get("squad_id") == 12], \
        [(p.rule, p.action) for p in props]


@test("the dwarves hide: hiding() true for a fire breather alone (squads to the shelter), false without the flag")
def _():
    s = fort(great=False)
    h, targets = hiding(s, Memory(), PLANNER_CONFIG)
    assert h and targets == [], (h, targets)
    s2 = fort(great=False, breather=False)
    h2, t2 = hiding(s2, Memory(), PLANNER_CONFIG)
    assert not h2 and t2 == [5000], (h2, t2)


@test("Rules: attack everything is obeyed (the squads go), with the note")
def _():
    props, notes = plan(fort(policy="all"), Memory())
    assert at_dragon(props), [(p.rule, p.action) for p in kills(props)]
    assert any("attack everything" in n and "fire" in n for n in notes), notes


@test("the filter: a lone-intruder style order at a fire breather from another rule is stripped or dropped; "
      "a gate guard of melee squads isn't posted against one")
def _():
    from planner_core import Proposal
    s = fort(goblin=True)
    props = [Proposal("squad_attack", {"type": "squad_orders", "squad_id": 11, "kill": [5000]}, "x", 0),
             Proposal("squad_attack", {"type": "squad_orders", "squad_id": 12, "kill": [5000, 6000]}, "y", 0)]
    notes = []
    PF._fire_breather_rule(s, Memory(), PLANNER_CONFIG, props, notes)
    assert [p.action for p in props] == [{"type": "squad_orders", "squad_id": 12, "kill": [6000]}], \
        [p.action for p in props]
    s = fort()
    s["others_on_map"]["threats"][0].update(invader=True, can_reach_dwarves=False)
    props = [Proposal("gate_guard", {"type": "guard_gate", "x": 1, "y": 2, "z": 3, "squads": [11, 12]}, "g", 0)]
    PF._fire_breather_rule(s, Memory(), PLANNER_CONFIG, props, [])
    assert props == [], [p.action for p in props]


@test("identity: the fixture and forts without the flag plan the same with the rule as without it")
def _():
    import planner
    for s in (copy.deepcopy(BASE), fort(breather=False), fort(breather=False, goblin=True),
              fort(breather=False, ranged=True, gates_shut=True)):
        a = plan(copy.deepcopy(s), Memory())
        orig = planner._fire_breather_rule
        planner._fire_breather_rule = lambda *a_, **k_: None
        try:
            b = plan(copy.deepcopy(s), Memory())
        finally:
            planner._fire_breather_rule = orig
        assert [(p.rule, p.action, p.reason) for p in a[0]] == [(p.rule, p.action, p.reason) for p in b[0]]
        assert a[1] == b[1]


if __name__ == "__main__":
    finish()
