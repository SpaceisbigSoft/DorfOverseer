"""(0.105.99) E's citizens killed by citizens "without a tantrum", 23 Nov 23:47-23:56.

What the probes showed (E, region4-1430, year 263):
  * 23:47:22 Medtob Sefollòr (a stonecrafter then, miserable, stress 83,000)
    threw a tantrum (tick 141621) and struck the butcher Tobul at 142379.
    The peasant Endok joined the fight at 142434 (DF's JoinConflict thought);
    both had "major injuries" by 142900, were carried to the hospital
    (Rescued) and suffocated there (143695, 144129). DF credited the kills
    to two calm dwarves who had joined in: the miner Zon Avuzfikod (stress
    -8,469, a pick in hand) and the axedwarf Dodók Tithlethzas (-18,948,
    no weapon). DF's record of every one of these deaths names no weapon.
  * 23:55:43 Meng Inoddesor's second tantrum began at 183635 (no report of
    it was told); five blows at the stonecrafter Urist ran to 186154, Urist
    suffocated at 186584, 2,949 ticks after the start: past the 2 days
    kill_kind looked back from a tantrum's START, so told as no tantrum.
  * 24 Nov 00:07:57 the defence floor's fill drafted Medtob (miserable,
    slipping into depression that report) into squad 191; at 00:15:13 he
    threw a tantrum among his squad and struck down Goden; the calm burrow
    passes soldiers over.
Not a weapon kept after a release (no weapon in the records), not a loyalty
cascade (fix/loyaltycascade ran each time, nothing to fix), not a Nonlethal
fight (DF gave conflict None).

The fixes: kill_kind counts from a tantrum's end too; fight_of marks a calm
killer's kill in a fight the victim was drawn into as a brawl (and names the
tantrum it grew from); the fill never drafts the breaking-down, the
miserable or a recent tantrum-thrower into the fort's squads (draft_bar);
a soldier in a tantrum is let out of his squad (tantrum_soldier).

    python tests/test_r99_e_killings.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

from planner import Memory, plan, PLANNER_CONFIG  # noqa: E402
from planner_core import abs_tick  # noqa: E402
import planner_tantrums as PT  # noqa: E402
from overseer_words import death_words  # noqa: E402
import crisis  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LUA = ROOT / "lua"
DAY = 1200


def src(name: str) -> str:
    return (LUA / name).read_text(encoding="utf-8")


def fort(rows, threats=0):
    s = copy.deepcopy(BASE)
    s["tantrums"] = {"loose": sum(1 for r in rows if r.get("now")), "berserk": 0, "possessed": 0, "dwarves": rows,
                     "chronic": 0, "hospitals": [], "squads": [], "guards": []}
    s.setdefault("others_on_map", {})["threats_that_can_reach_dwarves"] = threats
    return s


MEDTOB = {"id": 18086, "name": "Medtob Sefollòr, Axe Lord", "now": True, "squad": True, "year": 2, "n28": 1,
          "stress": "miserable", "posts": [], "unmet": ["HelpSomebody"]}


# --- the brain: a soldier in a tantrum goes home ---------------------------------------

@test("tantrum_soldier: a soldier in a tantrum is let out of his squad (squad_release, tantrum)")
def _():
    props = []
    PT._tantrum_soldier_rule(fort([MEDTOB]), Memory(), PLANNER_CONFIG, props)
    assert len(props) == 1, props
    p = props[0]
    assert p.rule == "tantrum_soldier" and p.action == {"type": "squad_release", "unit_id": 18086, "tantrum": True}
    assert "calm burrow" in p.reason


@test("tantrum_soldier: never a civilian, a calm soldier, nor while enemies can reach the dwarves")
def _():
    for rows, threats in (([dict(MEDTOB, squad=None)], 0), ([dict(MEDTOB, now=None)], 0), ([MEDTOB], 1)):
        props = []
        PT._tantrum_soldier_rule(fort(rows, threats), Memory(), PLANNER_CONFIG, props)
        assert props == [], (rows, threats, props)
    props = []
    PT._tantrum_soldier_rule(fort([MEDTOB]), Memory(), dict(PLANNER_CONFIG, tantrum_soldier_release=False), props)
    assert props == []


@test("tantrum_soldier: a refused release (a squad leader stays) waits out its back-off")
def _():
    s = fort([MEDTOB])
    m = Memory()
    props = []
    PT._tantrum_soldier_rule(s, m, PLANNER_CONFIG, props)
    from planner_core_refusals import refusal_key
    m.refusals = {refusal_key(props[0]): {"n": 1, "until": abs_tick(s) + 5 * DAY, "at": abs_tick(s)}}
    again = []
    PT._tantrum_soldier_rule(s, m, PLANNER_CONFIG, again)
    assert again == []


@test("plan(): the release comes out of the whole planner, and the rule is classified for holds and crisis")
def _():
    props = plan(fort([MEDTOB]), Memory())[0]
    got = [p for p in props if p.rule == "tantrum_soldier"]
    assert got and got[0].action.get("tantrum") is True, [p.rule for p in props][:40]
    import hold_classes
    text = (ROOT / "brain" / "hold_classes.py").read_text(encoding="utf-8")
    assert '"tantrum_soldier"' in text
    assert "tantrum_soldier" in crisis.RECOVERY_RULES
    from planner_core_base import STEER_PROTECTED
    assert "tantrum_soldier" in STEER_PROTECTED
    assert hold_classes is not None


@test("words: the release says why; a brawl's death names the tantrum it grew from")
def _():
    from overseer_words import short
    assert "in a tantrum" in short({"type": "squad_release", "unit_id": 5, "tantrum": True})
    ev = {"kind": "death", "name": "Tobul Edëmmomuz, Butcher", "cause": "SUFFOCATE", "killer": "Zon Avuzfikod, Miner",
          "killer_kind": "citizen", "conflict": "Brawl", "conflict_df": "None", "kill_kind": "brawl",
          "brawl_tantrum": "Medtob Sefollòr, Stonecrafter", "patient": True, "x": 116, "y": 155, "z": 163}
    w = death_words(ev)
    assert "a brawl" in w and "brawl fight" not in w and "round Medtob Sefollòr, Stonecrafter's tantrum" in w, w


@test("crisis: a brawl's death by a citizen counts as a fight death (the fights broken up)")
def _():
    s = copy.deepcopy(BASE)
    m = Memory()
    ev = {"kind": "death", "own_civ": True, "animal": False, "name": "Endok", "cause": "SUFFOCATE",
          "killer_kind": "citizen", "conflict": "Brawl", "kill_kind": "brawl", "unit_id": 19510}
    crisis.note_deaths(s, m, [ev])
    assert len(m.fight_deaths) == 1


# --- the bridge's text (runs without lupa) --------------------------------------------------

@test("bridge: kill_kind counts from a tantrum's end; fight_of reads Conflict / JoinConflict; the death event uses it")
def _():
    t = src("ai-tantrums.lua")
    assert "r.ended = now" in t
    assert "r.seen = now" in t and "now - e < KILL_DAYS * DAY" in t
    assert "BRAWL_THOUGHTS = {Conflict = true, JoinConflict = true}" in t and "function fight_of(v, now)" in t
    w = src("ai-bridge-report-world.lua")
    assert "reqscript('ai-tantrums').fight_of(u, abs_tick())" in w
    assert "ev.conflict = 'Brawl'" in w and "ev.brawl_tantrum = txt(" in w
    assert len(w.encode("utf-8")) < 60 * 1024


@test("bridge: the fill keeps the breaking-down out (but the training squad); a tantrum's release skips the longing")
def _():
    d = src("ai-military-draft.lua")
    assert "DRAFT_BREAKDOWN = {Tantrum = true, Enraged = true, Depressed = true, Oblivious = true}" in d
    assert "if okc and cat == 0 then return 'miserable' end" in d
    assert "T.count(d, u.id, T.STAFF_DAYS, now) > 0" in d
    # (item4) the bar by reason; draft_bar but for the training squad, post_bar for every squad
    assert "local why = (not training and draft_bar(c.unit)) or post_bar(c.unit, care)" in d and "pcall(TSQ.marks)" in d
    assert "function release(unit_id, dry_run, txt, mother, tantrum)" in d
    assert "if wants_fight(u) and not mother and not tantrum then" in d and "'not in a tantrum now'" in d
    c = src("ai-bridge-actions-civic.lua")
    assert "a.mother == true, a.tantrum == true)" in c


# --- the bridge in a fake game (lupa) ----------------------------------------------------------

FAKE_T = r"""
local src = ...
local W = {units = {}, site = {}}
local env = setmetatable({}, {__index = _G})
local real = ipairs
local function vec(l)
    local t = {_v = true}
    for i, v in real(l or {}) do t[i - 1] = v end
    return t
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
    t.counters = t.counters or {soldier_mood = -1}
    t.military = t.military or {squad_id = -1}
    t.status = {current_soul = {personality = {emotions = vec(t.emo or {}), needs = vec({})}}, labors = {}}
    table.insert(W.units, t)
    return t
end
env.df = {
    global = {cur_year = 263, cur_year_tick = 186584, plotinfo = {group_id = 1}},
    soldier_mood_type = {[-1] = 'None', [0] = 'MartialTrance', [1] = 'Enraged', [2] = 'Tantrum', [3] = 'Depressed',
                         [4] = 'Oblivious'},
    mood_type = {[3] = 'Possessed', [7] = 'Berserk'},
    unit_thought_type = {[1] = 'Conflict', [2] = 'JoinConflict', [3] = 'Attacked', [4] = 'Spar'},
    unit = {find = function(id) for _, u in real(W.units) do if u.id == id then return u end end end},
}
env.dfhack = {
    units = {getCitizens = function() return W.units end,
             getStressCategory = function(u) return u.cat or 4 end,
             getReadableName = function(u) return u.name or ('dwarf ' .. u.id) end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
env.reqscript = function(name) error('no module ' .. tostring(name)) end
assert(load(src, 'ai-tantrums', 't', env))()
return env, W
"""


def tworld():
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE_T, module_src("ai-tantrums.lua"))
    return lua, env, w


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


YEAR0 = 263 * 403200


@test("lua kill_kind: Meng's long tantrum (begun 2,949 ticks before the death, ended since) is a tantrum's kill")
def _():
    need_lua()
    lua, env, w = tworld()
    k = w.unit(T(lua, {"id": 18358}))
    now = YEAR0 + 186584
    w.site["ai-overseer/tantrums"] = T(lua, {"units": {"18358": {"t": [YEAR0 + 183635], "ended": YEAR0 + 186300}}})
    assert env.kill_kind(k, now) == "tantrum"
    w.site["ai-overseer/tantrums"] = T(lua, {"units": {"18358": {"t": [YEAR0 + 183635], "on": True,
                                                                 "seen": YEAR0 + 185000}}})
    assert env.kill_kind(k, now) == "tantrum"
    # on by a report long ago, never seen since: no tantrum's kill
    w.site["ai-overseer/tantrums"] = T(lua, {"units": {"18358": {"t": [YEAR0 + 183635], "on": True,
                                                                 "seen": YEAR0 + 183635}}})
    assert env.kill_kind(k, now) is None
    w.site["ai-overseer/tantrums"] = T(lua, {"units": {"18358": {"t": [YEAR0 + 183635], "ended": now - 3 * DAY}}})
    assert env.kill_kind(k, now) is None


@test("lua note(): when the tantrum was last seen on, and its end, are written down")
def _():
    need_lua()
    lua, env, w = tworld()
    u = w.unit(T(lua, {"id": 7}))
    u.counters.soldier_mood = 2
    env.note(YEAR0 + 1000)
    env.note(YEAR0 + 1050)
    assert w.site["ai-overseer/tantrums"].units["7"].seen == YEAR0 + 1000
    env.note(YEAR0 + 1200)
    assert w.site["ai-overseer/tantrums"].units["7"].seen == YEAR0 + 1200
    u.counters.soldier_mood = -1
    env.note(YEAR0 + 2500)
    r = w.site["ai-overseer/tantrums"].units["7"]
    assert r.ended == YEAR0 + 2500 and r.on is None


@test("lua fight_of: Endok joined the fight round Medtob's tantrum: a brawl, Medtob named; no fight thought: nil")
def _():
    need_lua()
    lua, env, w = tworld()
    now = YEAR0 + 144129
    endok = w.unit(T(lua, {"id": 19510, "emo": [{"thought": 2, "year": 263, "year_tick": 142434},
                                               {"thought": 3, "year": 263, "year_tick": 142815}]}))
    calm = w.unit(T(lua, {"id": 1, "emo": [{"thought": 4, "year": 263, "year_tick": 140801}]}))
    old = w.unit(T(lua, {"id": 2, "emo": [{"thought": 1, "year": 263, "year_tick": 100000}]}))
    w.site["ai-overseer/tantrums"] = T(lua, {"units": {"18086": {"t": [YEAR0 + 141621], "on": True,
                                                                 "seen": YEAR0 + 143000},
                                                       "18358": {"t": [YEAR0 + 118314], "ended": YEAR0 + 120500}}})
    kind, who = env.fight_of(endok, now)
    assert kind == "brawl" and who == 18086, (kind, who)
    assert env.fight_of(calm, now) is None
    assert env.fight_of(old, now) is None
    w.site["ai-overseer/tantrums"] = T(lua, {"units": {}})
    kind, who = env.fight_of(endok, now)
    assert kind == "brawl" and who is None


FAKE_D = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local LEDGER = {units = {}}
env.MILITARY_PART_LOCALS = {U = {abs_tick = function() return 1000000 end}}
env.df = {soldier_mood_type = {[-1] = 'None', [1] = 'Enraged', [2] = 'Tantrum', [3] = 'Depressed', [4] = 'Oblivious'}}
env.dfhack = {units = {getStressCategory = function(u) return u.cat end}}
local T = {STAFF_DAYS = 28, YEAR = 403200, DAY = 1200, CHRONIC = 3, LEDGER = LEDGER}
function T.load() return LEDGER end
function T.count(d, id, days, now)
    local r = d.units[tostring(id)]
    local n = 0
    for _, t in ipairs(r and r.t or {}) do if now - t >= 0 and now - t < days * 1200 then n = n + 1 end end
    return n
end
env.reqscript = function(name) if name == 'ai-tantrums' then return T end error('no module ' .. name) end
assert(load(src, 'ai-military-draft', 't', env))()
return env, LEDGER
"""


@test("lua draft_bar: a breakdown, the miserable, a tantrum in 28 days or 3 a year bar the draft; the rest pass")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, ledger = lua.execute(FAKE_D, src("ai-military-draft.lua"))

    def u(i, mood=-1, cat=3):
        return T(lua, {"id": i, "cat": cat, "counters": {"soldier_mood": mood}})
    assert env.draft_bar(u(1)) is None
    assert "breakdown" in env.draft_bar(u(2, mood=3))
    assert "breakdown" in env.draft_bar(u(3, mood=2))
    assert env.draft_bar(u(4, cat=0)) == "miserable"
    assert env.draft_bar(u(5, cat=1)) == "very unhappy"      # (item4) the very unhappy too, longing or not
    ledger.units["6"] = T(lua, {"t": [1000000 - 10 * DAY]})
    assert "28 days" in env.draft_bar(u(6))
    ledger.units["7"] = T(lua, {"t": [1000000 - 300 * DAY, 1000000 - 200 * DAY, 1000000 - 100 * DAY]})
    assert "3+" in env.draft_bar(u(7))


if __name__ == "__main__":
    finish()
