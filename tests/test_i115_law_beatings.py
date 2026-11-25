"""(0.105.115 item21) DF's beatings: the law's strangled convicts.

B and D, 25 Nov: four of the six citizens killed by citizens overnight were
convicts beaten to death (SUFFOCATE) by the captain of the guard or the
sheriff, job BeatCriminal (fights.jsonl lines 257, 283, 305 in B, 380 in D):
Armorsports by Stockadetuft 03:57, Stockadetuft by Inkycrewed 06:37 (36 s
after law_swap gave Inkycrewed the post), the doctor Monom by Inkycrewed
10:42 (each a ProductionOrderViolation sentenced, hammer strikes 5/1/4 and
no hammerer), and in D Gulfcopper by the sheriff 07:22, a minute after the
AI's chronic_convict convicted him. No Conflict activity, so the watcher
only logged a calm 'attack' once; the killers report counted each death as
lawful (`punished`) and no law_swap came.

Now: the watcher sets every punishment's beating and hammer strikes to 0
(prison kept) and stops a beating whose convict is in danger; a law officer
with a convict dead at their hands loses the post (never a cell); the AI's
chronic_convict waits unless the watcher spares beatings.

    python tests/test_i115_law_beatings.py
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402
from planner import PLANNER_CONFIG  # noqa: E402
from digest import normalize  # noqa: E402
import planner_killers as PK  # noqa: E402
import planner_tantrums as PT  # noqa: E402
from planner_core import Memory  # noqa: E402


def _const(fname: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / fname).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"no {name} in {fname}")


FAKE = _const("test_item1_fights.py", "FAKE")
P112 = _const("test_i112_fights.py", "PRELUDE")
PRELUDE = P112 + r"""
E.df.job_type[60] = 'BeatCriminal'
W.jobs_removed = {}
E.dfhack.job = {removeJob = function(j) table.insert(W.jobs_removed, j); return true end}
function W.punish(list) E.df.global.plotinfo.punishments = W.vec(list) end
function W.beater(id, tid, suff)
    local u = W.unit{id = id, name = 'Inkycrewed, captain of the guard', attacks = {tid}}
    u.job = {current_job = {id = 900 + id, job_type = 60}}
    return u
end
function W.last(kind)
    for i = #E.state().log, 1, -1 do if E.state().log[i].kind == kind then return E.state().log[i] end end
end
"""


def case(name: str, code: str):
    @test("lua: " + name)
    def _():
        need_lua()
        from lupa.lua53 import LuaRuntime
        lua = LuaRuntime(unpack_returned_tuples=True)
        r = lua.execute(FAKE, module_src("ai-fights.lua"), PRELUDE + code)
        assert r == "ok", r
    return _


case("a punishment's beating and hammer strikes set to 0, the prison time kept; logged and counted once", r"""
W.unit{id = 17251, name = 'Monom, Doctor'}; W.unit{id = 17221, name = 'Inkycrewed'}
W.punish({{criminal = 17251, officer = 17221, beating = 4, hammer_strikes = 4, prison_counter = 300},
          {criminal = 19120, officer = 17221, beating = 0, hammer_strikes = 0, prison_counter = 2573}})
local d = E.pass(5000)
local p = E.df.global.plotinfo.punishments
assert(p[0].beating == 0 and p[0].hammer_strikes == 0 and p[0].prison_counter == 300, 'spared, prison kept')
assert(p[1].prison_counter == 2573, 'a prison-only sentence untouched')
assert(d.beatings_spared == 1 and E.state().counts.beatings_spared == 1, 'counted')
local e = W.last('beating_spared')
assert(e and e.criminal == 17251 and e.officer == 17221 and e.beating == 4 and e.spared == true, 'logged')
E.pass(5010)
assert(E.state().counts.beatings_spared == 1, 'nothing more to spare')
""")

case("dry run: read and logged once, nothing changed; spare_beatings = false: left alone", r"""
W.unit{id = 5}
W.punish({{criminal = 5, officer = 6, beating = 2, hammer_strikes = 0, prison_counter = 0}})
E.state().dry = true
E.pass(5000); E.pass(5010)
assert(E.df.global.plotinfo.punishments[0].beating == 2, 'dry: unchanged')
local n = 0
for _, e in ipairs(E.state().log) do if e.kind == 'beating_spared' then n = n + 1 end end
assert(n == 1, 'logged once, not each pass: ' .. n)
E.state().dry = nil
assert(E.act({on = true, spare_beatings = 'no'}).rejected, 'a bool only')
local r = E.act({on = true, spare_beatings = false})
assert(r.ok and r.spare_beatings == false and E.report().spare_beatings == false)
E.pass(6000)
assert(E.df.global.plotinfo.punishments[0].beating == 2, 'switched off: left alone')
assert(E.act({on = true}).spare_beatings == false, 'kept until told again')
assert(E.act({on = true, spare_beatings = true}).spare_beatings == true)
E.pass(6010)
assert(E.df.global.plotinfo.punishments[0].beating == 0, 'on again: spared')
""")

case("a beating under way: the convict suffocating -> the officer's job removed, beating_stopped, a choke", r"""
W.unit{id = 17251, name = 'Monom, Doctor', suffocation = 3}
W.beater(17221, 17251)
E.pass(5000)
assert(#W.jobs_removed == 1 and W.jobs_removed[1].id == 18121, 'the BeatCriminal job removed')
local e = W.last('beating_stopped')
assert(e and e.id == 17221 and e.target == 17251 and e.danger == 'suffocating' and e.stopped == true, 'logged')
assert(E.state().counts.beatings_stopped == 1 and E.state().counts.chokes == 1, 'counted')
assert(W.last('attack') == nil and E.state().counts.spars == 0, 'neither an attack nor sparring')
""")

case("a beating with the convict unharmed: logged as the law's attack (job BeatCriminal), never sparring", r"""
W.unit{id = 17251, name = 'Monom, Doctor', attacks = {17221}}
W.beater(17221, 17251)
E.pass(5000)
assert(#W.jobs_removed == 0, 'not stopped')
local e = W.last('attack')
assert(e and e.id == 17221 and e.job == 'BeatCriminal', 'logged with its job')
assert(W.last('beating_stopped') == nil)
""")

case("a strangling hold in a beating stops it too", r"""
W.unit{id = 17156, name = 'Gulfcopper'}
local u = W.beater(18903, 17156)
W.grapple(u, 17156, 1)
E.pass(5000)
local e = W.last('beating_stopped')
assert(e and e.danger == 'choke hold' and e.grapple == 'Choke' and #W.jobs_removed == 1, 'stopped')
""")


@test("ai-fights.lua under 60,000 bytes without CR")
def _():
    assert len((ROOT / "lua" / "ai-fights.lua").read_bytes().replace(b"\r", b"")) < 60000


# --- the brain -------------------------------------------------------------------

def kstate(killers, **extra):
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    base["killers"] = killers
    base.update(extra)
    return normalize(base)


def law_row(**kw):
    r = {"id": 17221, "name": "ònul Likotginet \"Inkycrewed\", captain of the guard", "kind": "killer",
         "confidence": "weak", "citizen": True, "kills": 0, "brawls": 0, "punished": 2, "seen_ticks": 2000,
         "law": True, "law_codes": ["CAPTAIN_OF_THE_GUARD"], "law_kills": 0, "law_killer": True}
    r.update(kw)
    return r


def run(s):
    props, notes = [], []
    PK._killer_rule(s, dict(PLANNER_CONFIG), props, notes, None)
    return props, notes


@test("B's Inkycrewed: two convicts strangled in beatings -> law_swap (the post to a calm dwarf), never a cell")
def _():
    p, n = run(kstate({"list": [law_row()], "cells": [], "rooms": 2}))
    assert [(x.rule, x.action) for x in p] == [("law_swap", {"type": "appoint", "office": "CAPTAIN_OF_THE_GUARD",
                                                            "replace": True, "killer_out": True,
                                                            "unit_id": 17221})], p
    assert "beat 2 convict(s) to death" in p[0].reason and "never a cell" in p[0].reason, p[0].reason
    assert "2 convict(s) died in DF's beatings at their hands" in p[0].reason, p[0].reason
    assert 17221 not in PK.held_killer_ids(kstate({"list": [law_row()], "cells": []}))


@test("D's sheriff: one convict dead (even from an older bridge without law_killer) -> law_swap")
def _():
    r = law_row(punished=1, law_killer=None, law_codes=["SHERIFF"], name="Crowdpalace, sheriff")
    p, _ = run(kstate({"list": [r], "cells": [], "rooms": 2}))
    assert [x.action.get("office") for x in p] == ["SHERIFF"], p
    p, n = run(kstate({"list": [law_row(punished=0, law_killer=None)], "cells": [], "rooms": 2}))
    assert p == [] and "watched" in n[0], n


def chronic(fights=None):
    s = {"justice": {"restraints": 4, "restraints_used": 0, "punish": {"n": 0}}, "settings": {}}
    if fights is not None:
        s["fights"] = fights
    return s


@test("chronic_convict waits while the fight watcher does not spare beatings (D 07:21)")
def _():
    cfg = dict(PLANNER_CONFIG)
    WORDS = "DF's beating could kill them"
    assert any(WORDS in w for w in PT._convict_blockers(chronic({"armed": True}), cfg, {"id": 1}))
    assert any(WORDS in w for w in PT._convict_blockers(chronic({"armed": False, "spare_beatings": True}), cfg,
                                                       {"id": 1}))
    assert not any(WORDS in w for w in PT._convict_blockers(chronic({"armed": True, "spare_beatings": True}), cfg,
                                                           {"id": 1}))
    assert not any(WORDS in w for w in PT._convict_blockers(chronic(), cfg, {"id": 1})), "no section: as before"


@test("the fight journal tells beatings spared and stopped")
def _():
    m = Memory()
    sec = {"armed": True, "counts": {"capped": 0, "separated": 0, "beatings_spared": 2, "beatings_stopped": 1},
           "log": []}
    out = PT.fight_journal({"fights": sec}, m)
    assert len(out) == 1 and out[0]["beatings_spared"] == 2 and out[0]["beatings_stopped"] == 1, out
    assert "2 DF beating(s) of a convict spared" in out[0]["text"] and "1 beating(s) stopped" in out[0]["text"]
    assert PT.fight_journal({"fights": sec}, m) == []


# --- the killers report (lupa) ----------------------------------------------------

ITEM3 = (ROOT / "tests" / "test_item3_killers.py").read_text(encoding="utf-8")
KFAKE = re.search(r'FAKE = r"""(.*?)"""', ITEM3, re.S).group(1)


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


@test("bridge: the law with only convicts beaten to death is a row (law_killer); out of office, no killer")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(KFAKE, module_src("ai-killers.lua"))
    w.unit(T(lua, {"id": 5, "name": "Inkycrewed", "citizen": True,
                   "positions": [{"position": {"code": "CAPTAIN_OF_THE_GUARD"}}]}))
    w.unit(T(lua, {"id": 6, "name": "Stockadetuft, planter", "citizen": True}))
    for v in (20, 21):
        w.unit(T(lua, {"id": v, "name": f"V{v}", "is_dead": True}))
        w.crimes[len(w.crimes) + 1] = T(lua, {"mode": 5, "criminal": v, "flags": {"sentenced": True}})
    for k, v in ((5, 20), (6, 21)):
        w.incidents[len(w.incidents) + 1] = T(lua, {"criminal": k, "victim": v, "death_cause": 7,
                                                    "conflict_level": 0, "event_year": 300, "event_time": 0})
    rows = {x["id"]: dict(x) for x in env.report()["list"].values()}
    r = rows[5]
    assert (r.get("law"), r.get("punished"), r.get("law_killer"), r.get("confidence")) == (True, 1, True, "weak"), r
    assert env.law_killer(5) is True and not env.held_ids()[5]
    assert 6 not in rows, "a convict's beating death is lawful out of office too: no killer row"


if __name__ == "__main__":
    finish()
