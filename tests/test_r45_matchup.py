"""(0.105.45, Phase 11 (a)) A threat judged against the squads: the bridge's
threat facts (lua/ai-threat-facts.lua: attacks, venom, breath kinds, webs,
no pain, armour, speed, wounds), the squads' melee and ranged power
(lua/ai-military.lua squad_power), and the brain's threat_power with the
facts and `matchup` (brain/planner_matchup.py) in fight_or_hide. Rows from
an older bridge (no `facts`, no power split): the old judgement exactly.

    python tests/test_r45_matchup.py
"""

from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
import planner_military as PM  # noqa: E402
from planner_military import threat_power, fight_or_hide, matchup  # noqa: E402
from planner_matchup import squad_weights, facts_mult  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG


def lua_list(t):
    return [t[i] for i in range(1, len(t) + 1)] if t is not None else []


# --- the bridge: the threat facts --------------------------------------------------

FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local function enum(names, first)
    local e = {}
    for i, n in ipairs(names) do e[n] = i - 1 + (first or 0); e[i - 1 + (first or 0)] = n end
    return e
end
local function ce(name) return {getType = function(self) return env.df.creature_interaction_effect_type[name] end} end
local deadly_mat = {syndrome = {syndrome = {{ce = {ce('NECROSIS')}}}}, flags = {}, strength = {yield = {[1] = 20000}}}
local mats = {
    ['5:1'] = {material = deadly_mat},                                                       -- a beast's dust
    ['6:2'] = {material = {syndrome = {syndrome = {{ce = {ce('PARALYSIS')}}}}}},              -- venom
    ['0:9'] = {inorganic = {id = 'IRON'}, material = {flags = {IS_METAL = true}, strength = {yield = {[1] = 310000}}}},
    ['19:1'] = {material = {flags = {}, strength = {yield = {[1] = 20000}}}},                -- skin
    ['20:1'] = {material = {flags = {}, strength = {yield = {[1] = 130000}}}},               -- bone
}
local interactions = {
    [40] = {targets = {{breath_attack_type = 7, mat_type = 5, mat_index = 1}}, effects = {}},   -- UNDIRECTED_DUST of a deadly mat
    [41] = {targets = {}, effects = {{getType = function() return 0 end}}},                    -- ANIMATE
}
local function cdi(breath, type_id) return {type = 1, interaction = {material_breath = breath, type_id = type_id or -1}} end
local function att(name, edge, special, mt, mi)
    return {name = name, flags = {edge = edge, latch = false}, skill = -1, specialattack_type = special or {},
            specialattack_mat_type = mt and {mt} or {}, specialattack_mat_index = mi and {mi} or {}}
end
env.RACES = {
    [1] = {tissue = {{id = 'SCALE', mat_type = 19, mat_index = 1}, {id = 'BONE', mat_type = 20, mat_index = 1}},
           caste = {[0] = {body_info = {interactions = {cdi(9)}, attacks = {att('BITE', true), att('SCRATCH', true)}},
                           flags = {FLIER = true, FIREIMMUNE = true}}}},                          -- a dragon
    [2] = {tissue = {{id = 'SKIN', mat_type = 0, mat_index = 9}},
           caste = {[0] = {body_info = {interactions = {cdi(-1, 40)},
                                        attacks = {att('STING', false, {0}, 6, 2), att('PUNCH', false)}},
                           flags = {NOPAIN = true, NOSTUN = true, TRAPAVOID = true}}}},           -- an iron beast with deadly dust
    [3] = {tissue = {{id = 'SKIN', mat_type = 19, mat_index = 1}, {id = 'BONE', mat_type = 20, mat_index = 1}},
           caste = {[0] = {body_info = {interactions = {cdi(-1, 41)}, attacks = {att('PUNCH', false)}},
                           flags = {}}}},                                                         -- a necromancer's sort
    [4] = {tissue = {}, caste = {[0] = {body_info = {interactions = {cdi(8)}, attacks = {}}, flags = {WEBBER = true}}}},
}
env.df = {
    breath_attack_type = enum({'NONE', 'TRAILING_DUST_FLOW', 'TRAILING_VAPOR_FLOW', 'TRAILING_GAS_FLOW', 'SOLID_GLOB',
                               'LIQUID_GLOB', 'UNDIRECTED_GAS', 'UNDIRECTED_VAPOR', 'UNDIRECTED_DUST', 'WEB_SPRAY',
                               'DRAGONFIRE', 'FIREJET', 'FIREBALL'}, -1),
    specialattack_type = enum({'INJECT_EXTRACT', 'SUCK_BLOOD', 'INTERACTION'}),
    interaction_effect_type = enum({'ANIMATE', 'ADD_SYNDROME'}),
    creature_interaction_effect_type = enum({'PAIN', 'NECROSIS', 'PARALYSIS', 'REGROW_PARTS'}),
    job_skill = enum({'BITE'}),
    strain_type = {SHEAR = 1},
    interaction = {find = function(id) return interactions[id] end},
    creature_raw = {find = function(id) env.FINDS = (env.FINDS or 0) + 1; return env.RACES[id] end},
    syndrome = {find = function(id) if id == 7 then return {ce = {ce('REGROW_PARTS')}} end end},
    global = {world = {cur_savegame = {save_dir = 'region1'}}},
}
env.dfhack = {matinfo = {decode = function(t, i) return mats[tostring(t) .. ':' .. tostring(i)] end,
                         find = function() return nil end},
              units = {computeMovementSpeed = function(u) return u.move end}}
assert(load(src, 'ai-threat-facts', 't', env))()
return env
"""


def facts_env():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(FAKE, module_src("ai-threat-facts.lua"))
    return lua, env


@test("bridge: the pure helpers: breath kinds, an attack's kind, the attacks summed up, the armour hint, the flags")
def _():
    if LuaRuntime is None:
        return
    lua, env = facts_env()
    assert lua_list(env.breath_kinds("DRAGONFIRE")) == ["dragonfire"]
    assert lua_list(env.breath_kinds("FIREBALL")) == ["fire"]
    assert lua_list(env.breath_kinds("UNDIRECTED_DUST", True)) == ["dust", "deadly"]
    assert lua_list(env.breath_kinds("TRAILING_GAS_FLOW")) == ["poison_gas"]
    assert lua_list(env.breath_kinds("WEB_SPRAY")) == ["web"]
    assert lua_list(env.breath_kinds("NONE")) == [] and lua_list(env.breath_kinds("SOMETHING_NEW")) == ["other"]
    t = lua.table_from
    assert env.attack_kind(t({"name": "BITE"})) == "bite"
    assert env.attack_kind(t({"name": "SCRATCH", "edge": True})) == "edged"
    assert env.attack_kind(t({"name": "GRAB", "latch": True})) == "grab"
    assert env.attack_kind(t({"name": "PUNCH"})) == "blunt"
    s = env.attack_summary(lua.eval("{{name = 'PUNCH'}, {name = 'STING', special = {'INJECT_EXTRACT'}}, "
                                    "{name = 'SLASH', edge = true}}"))
    assert s["count"] == 3 and s["best"] == "edged" and s["syndrome"] and not s["deadly"]
    lvl, kind = env.armor_of(lua.eval("{{id = 'SKIN', shear = 20000}, {id = 'SCALE', shear = 20000}, "
                                      "{id = 'BONE', shear = 130000}}"))
    assert (lvl, kind) == (1, "scales"), (lvl, kind)                       # bone doesn't armour it
    assert env.armor_of(lua.eval("{{id = 'SKIN', inorganic = true, metal = true}}")) == (3, "metal")
    assert env.armor_of(lua.eval("{{id = 'SKIN', inorganic = true}}")) == (2, "stone")
    assert env.armor_of(lua.eval("{{id = 'SKIN', shear = 250000}}"))[0] == 3
    assert env.armor_of(lua.eval("{}"))[0] == 0
    f = env.flag_facts(lua.eval("{NOPAIN = true, FIREIMMUNE_SUPER = true, THICKWEB = true, TRAPAVOID = true}"))
    assert f["no_pain"] and f["immune_fire"] and f["webs"] and f["trap_avoid"] and f["no_stun"] is None


@test("bridge: add_facts reads a dragon (dragonfire, bite, scales, flier), an iron beast (deadly dust, deadly "
      "sting, no pain, metal), a raiser of the dead, a web sprayer; its wounds, blood and speed; once per caste")
def _():
    if LuaRuntime is None:
        return
    lua, env = facts_env()

    def unit(race, **kw):
        u = {"race": race, "caste": 0, "move": 900, "body": {"wounds": lua.table(), "blood_max": 100, "blood_count": 100}}
        u.update(kw)
        return lua.table_from(u, recursive=True)
    t = env.add_facts(lua.table(), unit(1, move=450))
    assert t["facts"] == 1 and lua_list(t["breath"]) == ["dragonfire"], lua_list(t["breath"])
    assert t["attacks"]["count"] == 2 and t["attacks"]["best"] == "edged" and not t["syndrome_attack"]
    assert t["armor"] == 1 and t["armor_kind"] == "scales" and t["immune_fire"] and t["speed"] == 2
    assert t["flier"] is None                                         # the report's own flier field is kept
    b = env.add_facts(lua.table(), unit(2, body={"wounds": lua.table_from([1, 2, 3]), "blood_max": 100,
                                                 "blood_count": 60}))
    assert lua_list(b["breath"]) == ["dust", "deadly"], lua_list(b["breath"])
    assert b["syndrome_attack"] and b["attacks"]["deadly"] and b["no_pain"] and b["no_stun"] and b["trap_avoid"]
    assert b["armor"] == 3 and b["armor_kind"] == "metal" and b["wounds"] == 3 and abs(b["blood_lost"] - 0.4) < 1e-9
    r = env.add_facts(lua.table(), unit(3, syndromes={"active": [{"type": 7}]}))
    assert r["undead_raiser"] and r["regenerates"] and r["breath"] is None and r["armor"] is None
    w = env.add_facts(lua.table(), unit(4))
    assert lua_list(w["breath"]) == ["web"] and w["webs"]
    n = env.FINDS
    env.add_facts(lua.table(), unit(1))
    assert env.FINDS == n, "the raws read once per race and caste"
    # a missing race: only the body half, still marked
    x = env.add_facts(lua.table(), unit(99))
    assert x["facts"] == 1 and x["breath"] is None


@test("bridge: the report calls the facts module under pcall (a small diff), the module compiles")
def _():
    src = (ROOT / "lua" / "ai-bridge-report.lua").read_text(encoding="utf-8")
    assert "pcall(reqscript, 'ai-threat-facts')" in src
    assert "pcall(TF.add_facts, out.threats[#out.threats], u)" in src
    if LuaRuntime is None:
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("local s = ...; assert(load(s, 'x', 't', {}))", (ROOT / "lua" / "ai-threat-facts.lua").read_text())


# --- the bridge: the squads' power --------------------------------------------------

MIL_FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
env.df = {global = {plotinfo = {group_id = 1}}, need_type = {[3] = 'BeWithFriends'}}
env.dfhack = {}
env.require = function() return {} end
assert(load(src, 'm', 't', env))()
return env
"""


@test("bridge: squad power by soldier: skill, coverage, the weapon's class, ranged with and without bolts, "
      "wounded and tired; melee and ranged apart")
def _():
    if LuaRuntime is None:
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(MIL_FAKE, module_src("ai-military.lua"))
    assert env.weapon_class("inorganic", "STEEL", True) == "steel"
    assert env.weapon_class("inorganic", "BISMUTH_BRONZE", True) == "bronze"
    assert env.weapon_class("inorganic", "SILVER", True) == "metal"
    assert env.weapon_class("inorganic", "GRANITE", False) == "stone"
    assert env.weapon_class("creature", "BONE") == "bone" and env.weapon_class("plant", "WOOD") == "wood"
    full = lua.eval("{body = true, helm = true, legs = true, feet = true, hands = true, shield = true}")
    assert env.coverage(full) == 1 and env.coverage(lua.eval("{body = true}")) == 0.4
    T = lambda d: lua.table_from(d, recursive=True)  # noqa: E731
    # a steel axedwarf at skill 9, fully armoured: (1 + 3) x 1.5 x 1.25 = 7.5
    m, r = env.soldier_power(T({"skill": 9, "has_weapon": True, "wclass": "steel",
                                "slots": {"body": True, "helm": True, "legs": True, "feet": True,
                                          "hands": True, "shield": True}}))
    assert abs(m - 7.5) < 1e-9 and r == 0, (m, r)
    # the same with a copper axe, wounded and tired
    m2, _ = env.soldier_power(T({"skill": 9, "has_weapon": True, "wclass": "copper", "wounded": True, "tired": True,
                                 "slots": {}}))
    assert abs(m2 - 4 * 0.85 * 0.5 * 0.85) < 1e-9, m2
    # unarmed: x0.4 as before
    m3, _ = env.soldier_power(T({"skill": 0, "slots": {}}))
    assert abs(m3 - 0.4) < 1e-9
    # a marksdwarf at crossbow 6 with bolts: ranged 3, a little melee; no bolts: x0.15
    m4, r4 = env.soldier_power(T({"skill": 0, "rskill": 6, "ranged": True, "ammo": 20, "has_weapon": True,
                                  "slots": {}}))
    assert abs(r4 - 3) < 1e-9 and abs(m4 - 0.3) < 1e-9, (m4, r4)
    _, r5 = env.soldier_power(T({"rskill": 6, "ranged": True, "ammo": 0, "has_weapon": True, "slots": {}}))
    assert abs(r5 - 0.45) < 1e-9


# --- the brain: threat_power and the matchup ----------------------------------------

def a_titan(**kw):
    """A's titan (4-5 Nov): huge, breathing fire."""
    t = {"id": 900, "name": "Hill Titan", "great_danger": True, "can_reach_dwarves": True, "kinds": ["Titan"],
         "size": 2_500_000, "abilities": 1, "facts": 1, "breath": ["fire"],
         "attacks": {"count": 3, "best": "edged"}, "armor": 1, "armor_kind": "scales", "speed": 1.0}
    t.update(kw)
    return t


def a_beast(**kw):
    """An ordinary forgotten beast: no breath, the size of 7 dwarves."""
    t = {"id": 901, "name": "Forgotten beast", "great_danger": True, "can_reach_dwarves": True,
         "kinds": ["ForgottenBeast"], "size": 420_000, "facts": 1,
         "attacks": {"count": 2, "best": "blunt"}, "armor": 1, "armor_kind": "shell", "speed": 1.0}
    t.update(kw)
    return t


def squads(total, ranged_share=0.0, split=True, n=2):
    out = []
    for i in range(n):
        p = {"power": total / n, "armed": 10, "armored": 10, "skill": 8}
        if split:
            p["melee_power"] = total / n * (1 - ranged_share)
            p["ranged_power"] = total / n * ranged_share
        out.append({"id": 10 + i, "name": f"squad {i}", "members": 10, "power": p})
    return out


@test("brain: with no facts (an older bridge) threat_power and the ratio are the old ones exactly")
def _():
    old = {"size": 2_500_000, "kinds": ["Titan"], "abilities": 1, "flier": True}
    expect = (PM.GREAT_BASE + 2 * math.sqrt(2_500_000 / 60000)) * 1.2 * PM.GREAT_ABILITY * PM.GREAT_FLIER
    assert abs(threat_power(old) - expect) < 1e-9
    ratio, why = matchup(old, squads(488))
    assert abs(ratio - 488 / expect) < 1e-9 and why == [], (ratio, why)
    ratio2, _ = matchup(old, squads(488, split=False))
    assert abs(ratio2 - ratio) < 1e-9
    assert squad_weights(old) == (1.0, 1.0, [])


@test("brain: the facts weigh: fire and dragonfire high, deadly dust or gas highest, venom, no pain, armour, "
      "regeneration, speed, a flier; wounds lower it")
def _():
    plain = threat_power(a_beast(armor=None, speed=None))
    assert abs(threat_power(a_beast(armor=None, speed=None, breath=["fire"])) / plain - 4) < 1e-9
    assert abs(threat_power(a_beast(armor=None, speed=None, breath=["dragonfire"])) / plain - 6) < 1e-9
    assert threat_power(a_beast(breath=["dust", "deadly"])) >= threat_power(a_beast(breath=["dragonfire"]))
    assert threat_power(a_beast(breath=["poison_gas"])) > threat_power(a_beast(breath=["fire"]))
    assert threat_power(a_beast(breath=["web"])) > threat_power(a_beast())
    assert threat_power(a_beast(syndrome_attack=True)) == threat_power(a_beast()) * 2
    for k in ("no_pain", "no_exert", "no_stun", "regenerates", "undead_raiser", "flier"):
        assert threat_power(a_beast(**{k: True})) > threat_power(a_beast()), k
    assert threat_power(a_beast(armor=3)) > threat_power(a_beast(armor=1))
    assert threat_power(a_beast(speed=2.0)) > threat_power(a_beast()) > threat_power(a_beast(speed=0.5))
    assert threat_power(a_beast(blood_lost=0.5)) < threat_power(a_beast())
    _, why = facts_mult(a_beast(breath=["dust", "deadly"], no_pain=True, flier=True))
    text = "; ".join(why)
    assert "breathes dust that kills" in text and "feels no pain" in text and "flies" in text, text


@test("brain: matchup: against fire only ranged power counts; a flier counts ranged more; the reasons in words")
def _():
    ratio, why = matchup(a_titan(), squads(488))
    assert ratio == 0 and any("only ranged squads count" in w for w in why), (ratio, why)
    assert any("mostly melee" in w for w in why), why
    r_mix, _ = matchup(a_titan(), squads(488, ranged_share=0.5))
    assert 0 < r_mix
    fl = a_beast(flier=True)
    r_melee, _ = matchup(fl, squads(150))
    r_ranged, why = matchup(fl, squads(150, ranged_share=1.0))
    assert r_ranged > r_melee and any("flies" in w for w in why)


@test("calibration: A's titan (huge, fire breath) against squads of 488 says HIDE; an ordinary forgotten beast "
      "(no breath, 7 dwarves' size) against 150 says FIGHT")
def _():
    fight, words = fight_or_hide(BASE, Memory(), CFG, [a_titan()], squads(488))
    assert not fight and "fire" in words, words
    # even with a third of the squads shooting
    fight, words = fight_or_hide(BASE, Memory(), CFG, [a_titan()], squads(488, ranged_share=0.33))
    assert not fight, words
    # (a titan breathing deadly dust: hide too)
    fight, words = fight_or_hide(BASE, Memory(), CFG, [a_titan(breath=["dust", "deadly"])], squads(488))
    assert not fight, words
    fight, words = fight_or_hide(BASE, Memory(), CFG, [a_beast()], squads(150))
    assert fight, words
    fight, words = fight_or_hide(BASE, Memory(), CFG, [a_beast(syndrome_attack=True)], squads(150))
    assert fight, words


def fort_with(threat, sq):
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["others_on_map"]["threats"] = [threat]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    for q, p in zip(s["military"]["squads"], sq):
        q["power"] = p["power"]
    s["military"]["soldiers"] = 20
    s["civ_alert_ready"] = True
    return s


@test("plan: the titan's fire keeps the squads home (a note why); the forgotten beast is attacked")
def _():
    s = fort_with(a_titan(), squads(488, n=len(BASE["military"]["squads"])))
    p, notes = plan(s, Memory())
    assert not [x for x in p if x.rule == "squad_attack" and 900 in (x.action.get("kill") or [])], notes
    assert any("hide behind the gates" in n and "fire" in n for n in notes), notes
    s = fort_with(a_beast(), squads(150, n=len(BASE["military"]["squads"])))
    p, notes = plan(s, Memory())
    assert [x for x in p if x.rule == "squad_attack" and 901 in (x.action.get("kill") or [])], notes
    assert any("the squads go" in n for n in notes), notes


@test("fight_or_hide keeps its shape and its old ways: called off, a fight going badly, no squads")
def _():
    fight, words = fight_or_hide(BASE, Memory(), CFG, [a_beast()], [])
    assert (fight, words) == (False, "no squad to send")
    m = Memory()
    m.called_off = {"901": 1}
    s = fort_with(a_beast(), squads(150, n=len(BASE["military"]["squads"])))
    fight, words = fight_or_hide(s, m, CFG, [a_beast()], squads(150))
    assert not fight and "called off" in words
    # a fight that lost a third of the soldiers comes back and learns, with the facts too
    m = Memory()
    m.fight = {"tick": PM.abs_tick(s), "keys": ["ForgottenBeast"], "soldiers": 30}
    fight, words = fight_or_hide(s, m, CFG, [a_beast()], squads(150))
    assert not fight and "come back" in words and m.fight_factor.get("ForgottenBeast", 1) > 1, (words, m.fight_factor)


if __name__ == "__main__":
    finish()
