"""(0.105.47, R2) The dwarves who badly want to fight or train: the squad
ping-pong ended (stress care keeps one whose need to train is theirs; the
rest, once released, are never drafted until the memory forgets them) and
the training squad (high Welfare, any Militarism: volunteers only, capped,
never counted as soldiers, no kill orders in peace). The brain
(brain/planner_training.py, planner_society._stress_care), the bridge
(lua/ai-training-squad.lua, ai-military make_squad/trim/report,
ai-bridge-report get_needs) and the wiring.

    python tests/test_r47_training.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import bridge_hub_src  # noqa: E402  (r8) the hub's text with its catalog and sections
from lua_modules_util import module_src, bridge_part_src, split_src  # noqa: E402
from py_parts import py_family_src  # noqa: E402  (r7) planner_core's parts

sys.path.insert(0, str(ROOT / "brain"))
from planner import (PLANNER_CONFIG, Memory, Proposal, TICKS_PER_DAY, abs_tick, note_cycle, plan,  # noqa: E402
                     record)
import planner_training as PTR  # noqa: E402
from planner_core import recently_home  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort(militarism=-60, welfare=80, adults=40, squads=None, needs=None) -> dict:
    """The Monastery: Militarism -60, Welfare 80, a guard squad of 3."""
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["settings"]["traits"] = {"militarism": militarism, "welfare": welfare}
    s["dwarves"].update(adults=adults, total=adults + 5, idle_adults=2)
    if squads is None:
        squads = [{"id": 11, "name": "The Guard", "members": 3, "size": 10, "leader": True,
                   "routine": "Staggered training", "orders": 0, "ai_orders": 0, "power": {"armed": 3}}]
    s["military"]["squads"] = squads
    s["military"]["soldiers"] = sum(q.get("members") or 0 for q in squads)
    s["needs"] = needs if needs is not None else {"needs": {}, "stressed": [], "keen_civilians": 6,
                                                   "keen_draftable": 6}
    return s


def tsquad(members=3, sid=40, **kw) -> dict:
    q = {"id": sid, "name": "The Sparrers", "members": members, "size": 10, "leader": members > 0,
         "routine": "Staggered training", "orders": 0, "ai_orders": 0, "training": True, "power": {"armed": 0}}
    q.update(kw)
    return q


def guard(**kw) -> dict:
    q = {"id": 11, "name": "The Guard", "members": 3, "size": 10, "leader": True,
         "routine": "Staggered training", "orders": 0, "ai_orders": 0, "power": {"armed": 3}}
    q.update(kw)
    return q


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


def acts(props, t):
    return [p.action for p in props if p.action.get("type") == t]


def stressed(**kw) -> dict:
    x = {"id": 7, "name": "Logem", "stress": "miserable", "unmet": ["CraftObject"], "bedroom": True, "squad": True}
    x.update(kw)
    return x


# --- 1. the ping-pong -------------------------------------------------------------------------

@test("ping-pong: a miserable soldier whose need to train is met in the squad stays (fight_need); without it, released")
def _():
    s = fort(welfare=0, militarism=0)
    s["needs"] = {"needs": {}, "stressed": [stressed(fight_need=True)]}
    assert not acts(plan(s, Memory())[0], "squad_release")
    s["needs"]["stressed"][0]["fight_need"] = None
    p = by_rule(plan(s, Memory())[0], "stress_care")
    assert p and p[0].action == {"type": "squad_release", "unit_id": 7}, p
    # as before: a need unmet now (wants_fight, or listed) keeps them too
    s["needs"]["stressed"][0].update(wants_fight=True)
    assert not acts(plan(s, Memory())[0], "squad_release")


@test("ping-pong: E's Logem over 10 cycles in the squad (need met, so no longer 'wants to fight'): never released")
def _():
    m = Memory()
    s = fort(welfare=0, militarism=0)
    released = 0
    for i in range(10):
        s["date"]["tick"] = 1000 + i * 1200 * 3
        s["needs"] = {"needs": {}, "stressed": [stressed(fight_need=True, unmet=["CraftObject", "BeWithFriends"])]}
        p, _ = plan(s, m)
        released += len(acts(p, "squad_release"))
    assert released == 0


@test("never draft: a stress release is remembered; every fill and swap passes the dwarf over beyond 168 days")
def _():
    m = Memory()
    s = fort(welfare=0, militarism=0)
    s["needs"] = {"needs": {}, "stressed": [stressed()]}
    p = [x for x in plan(s, m)[0] if x.action.get("type") == "squad_release"]
    assert p and p[0].rule == "stress_care"
    record([(p[0], {"ok": True, "name": "Logem"})], s, m)
    assert "7" in m.never_draft and m.released.get("7") is not None
    # 200 days on: the 168-day `released` memory is gone, the never-draft one isn't
    s2 = copy.deepcopy(s)
    s2["date"]["year"] = s["date"]["year"] + 1
    s2["needs"] = {"needs": {}, "stressed": []}
    assert abs_tick(s2) - abs_tick(s) > 168 * TICKS_PER_DAY
    note_cycle(s2, m)
    assert 7 in recently_home(s2, m)
    # the regular fill and the training fill carry it
    s2["military"]["squads"] = [guard(members=1)]
    s2["military"]["soldiers"] = 1
    s2["settings"]["traits"] = {"militarism": 50, "welfare": 0}
    fills = acts(plan(s2, m)[0], "squad_fill")
    assert fills and 7 in fills[0].get("avoid", []), fills
    # a mother sent home with her baby isn't "never draft"
    m2 = Memory()
    record([(Proposal("mothers", {"type": "squad_release", "unit_id": 9, "mother": True}, "", 3), {"ok": True})], s, m2)
    assert not m2.never_draft


@test("never draft: forgotten after never_draft_days, or once the dwarf is content or better")
def _():
    m = Memory()
    s = fort()
    now = abs_tick(s)
    m.never_draft = {"7": {"at": now}, "8": {"at": now}, "9": {"at": now - 700 * TICKS_PER_DAY}}
    s["needs"]["content_ids"] = [8]
    assert PTR.never_draft_ids(s, m) == [7]
    note_cycle(s, m)
    assert set(m.never_draft) == {"7"}
    # an unread needs section: only the age forgets
    m.never_draft["8"] = {"at": now}
    s["needs"] = {"error": "boom"}
    note_cycle(s, m)
    assert set(m.never_draft) == {"7", "8"}


@test("stress care: breaking down out of a squad, top unmet need to train -> into the training squad (not if never-draft)")
def _():
    x = stressed(squad=None, unmet=["MartialTraining", "CraftObject"], wants_fight=True, fight_need=True)
    s = fort(squads=[guard(), tsquad(members=3)], needs={"needs": {}, "stressed": [x], "keen_civilians": 1})
    p = by_rule(plan(s, Memory())[0], "stress_care")
    assert p and p[0].action == {"type": "training_squad", "mode": "fill", "squad_id": 40, "unit_id": 7,
                                 "count": 1}, p
    assert "longs most to train" in p[0].reason
    # top unmet is something else: not put in
    s["needs"]["stressed"][0]["unmet"] = ["CraftObject", "MartialTraining"]
    assert not acts(by_rule(plan(s, Memory())[0], "stress_care"), "training_squad")
    # never-draft wins
    s["needs"]["stressed"][0]["unmet"] = ["Fight"]
    m = Memory()
    m.never_draft = {"7": {"at": abs_tick(s)}}
    assert not acts(by_rule(plan(s, m)[0], "stress_care"), "training_squad")
    # no training squad, or it's full: not put in
    s2 = fort(squads=[guard()], needs={"needs": {}, "stressed": [x]})
    assert not acts(by_rule(plan(s2, Memory())[0], "stress_care"), "training_squad")
    s3 = fort(squads=[guard(), tsquad(members=8)], needs={"needs": {}, "stressed": [x]})   # cap 40 // 5 = 8
    assert not acts(by_rule(plan(s3, Memory())[0], "stress_care"), "training_squad")


# --- 2. the training squad -------------------------------------------------------------------

@test("training squad: Militarism -60, Welfare 80, 6 keen -> made (volunteers, up to a fifth of the adults)")
def _():
    s = fort()
    p, _ = plan(s, Memory())
    t = by_rule(p, "training_squad")
    assert t and t[0].action == {"type": "training_squad", "mode": "make"}, t
    assert "up to 8" in t[0].reason and "never counted as soldiers" in t[0].reason


@test("training squad: none at low Welfare, none with the switch off, none with too few keen or adults")
def _():
    assert not by_rule(plan(fort(welfare=20), Memory())[0], "training_squad")
    s = fort()
    s["settings"]["training_squad"] = False
    assert not by_rule(plan(s, Memory())[0], "training_squad")
    s = fort()
    s["needs"].update(keen_civilians=1, keen_draftable=1)
    assert not by_rule(plan(s, Memory())[0], "training_squad")
    assert not by_rule(plan(fort(adults=9), Memory())[0], "training_squad")      # cap 1 < 2
    # under a threat that can reach the dwarves: nothing made
    s = fort()
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    assert not acts(plan(s, Memory())[0], "training_squad")


@test("training squad: its cap (min 10, adults // 5): filled to it, never past it")
def _():
    s = fort(adults=30, squads=[guard(), tsquad(members=3)])          # cap 6
    f = acts(plan(s, Memory())[0], "training_squad")
    assert f and f[0]["mode"] == "fill" and f[0]["count"] == 3 and f[0]["squad_id"] == 40, f
    s = fort(adults=30, squads=[guard(), tsquad(members=6)])
    assert not [a for a in acts(plan(s, Memory())[0], "training_squad") if a["mode"] == "fill"]
    s = fort(adults=200, squads=[guard(), tsquad(members=1)])         # cap 10; 3 a cycle
    f = [a for a in acts(plan(s, Memory())[0], "training_squad") if a["mode"] == "fill"]
    assert f and f[0]["count"] == 3
    assert PTR.training_cap(fort(adults=200), PLANNER_CONFIG) == 10
    assert PTR.training_cap(fort(adults=40), PLANNER_CONFIG) == 8
    p, notes = plan(fort(adults=30, squads=[guard(), tsquad(members=7)]), Memory())
    assert any("over its cap of 6" in n for n in notes), notes
    assert any(n.startswith("training squad The Sparrers: 7 of up to 6") for n in notes)


@test("training squad: put on staggered training when off duty; let go when Welfare falls")
def _():
    s = fort(squads=[guard(), tsquad(members=3, routine="Off duty")])
    r = [a for a in acts(plan(s, Memory())[0], "squad_routine") if a["squad_id"] == 40]
    assert r == [{"type": "squad_routine", "squad_id": 40, "routine": "Staggered training"}], r
    s = fort(welfare=10, squads=[guard(), tsquad(members=3)])
    f = acts(plan(s, Memory())[0], "training_squad")
    assert f == [{"type": "training_squad", "mode": "forget", "squad_id": 40}], f


@test("training squad: never counted as soldiers (Militarism's share, the trim, the fill), the guard minimum unchanged")
def _():
    s = fort(squads=[guard(), tsquad(members=8)])
    s["military"]["gear"] = {"soldiers": 11, "on_duty": 11, "squads": 2, "squads_with_uniform": 1}
    s["others_on_map"]["threats"] = []        # (0.105.54) no cavern beasts: no defence floor above the guard
    p, _ = plan(s, Memory())
    assert not acts(p, "squad_trim"), acts(p, "squad_trim")
    # the 3 guards are the fort's soldiers: the guard minimum (3) is met, nothing to fill
    assert not acts(p, "squad_fill")
    PTR.prepare_training(s)
    assert s["military"]["soldiers"] == 3 and s["military"]["soldiers_all"] == 11
    assert [q["id"] for q in s["military"]["squads"]] == [11]
    assert s["military"]["gear"]["soldiers"] == 3 and s["military"]["gear"]["squads"] == 1
    # the guard short: the fill goes to the guard squad, never the training squad
    s = fort(squads=[guard(members=1), tsquad(members=3)])
    f = acts(plan(s, Memory())[0], "squad_fill")
    assert f and all(a["squad_id"] == 11 for a in f), f


@test("training squad: no kill orders in peace; at enemies in reach the regular squads go, not it")
def _():
    s = fort(squads=[guard(), tsquad(members=5, power={"armed": 5})])
    p, _ = plan(s, Memory())
    assert not [a for a in acts(p, "squad_orders") if a.get("kill")]
    # enemies in reach, the guard can fight: the guard alone
    s = fort(squads=[guard(), tsquad(members=5, power={"armed": 5})])
    s["others_on_map"]["threats"] = [{"id": 900, "name": "goblin", "can_reach_dwarves": True, "invader": True,
                                      "distance_to_nearest_dwarf": 10}]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    kills = [a for a in acts(plan(s, Memory())[0], "squad_orders") if a.get("kill")]
    assert kills and all(a["squad_id"] == 11 for a in kills), kills
    # a kill order already on it in peace: called back
    s = fort(squads=[guard(), tsquad(members=5, ai_orders=1, kill_ids=[5])])
    rec = [a for a in acts(plan(s, Memory())[0], "squad_orders") if a.get("squad_id") == 40]
    assert rec == [{"type": "squad_orders", "squad_id": 40, "clear": True}], rec


@test("training squad: needed (enemies in reach, no regular squad can fight) -> counted back in for the attack")
def _():
    s = fort(squads=[guard(members=1, power={"armed": 0}), tsquad(members=5, power={"armed": 5})])
    s["others_on_map"]["threats"] = [{"id": 900, "name": "goblin", "can_reach_dwarves": True, "invader": True,
                                      "distance_to_nearest_dwarf": 10}]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    p, notes = plan(s, Memory())
    assert any("training squad counts as an ordinary squad" in n for n in notes), notes
    kills = [a for a in acts(p, "squad_orders") if a.get("kill")]
    assert kills and kills[0]["squad_id"] == 40, kills
    # unarmed it still isn't sent (the usual armed test)
    s["military"]["squads"][1]["power"] = {"armed": 0}
    assert not [a for a in acts(plan(s, Memory())[0], "squad_orders") if a.get("kill")]


@test("guard_training_orders: drops a kill order, a hunt or a mission naming it in peace; keeps the rest")
def _():
    s = fort(squads=[guard(), tsquad()])
    PTR.prepare_training(s)
    props = [Proposal("killer", {"type": "squad_orders", "squad_id": 40, "kill": [3]}, "a vampire", 0),
             Proposal("hunt", {"type": "hunt_send", "squad_ids": [11, 40], "target_id": 5}, "hunt", 3),
             Proposal("mission", {"type": "send_mission", "goal": "raid", "squad_ids": [40]}, "raid", 4),
             Proposal("squad_recall", {"type": "squad_orders", "squad_id": 40, "clear": True}, "back", 1),
             Proposal("squad_attack", {"type": "squad_orders", "squad_id": 11, "kill": [3]}, "guard", 0)]
    notes: list = []
    kept = PTR.guard_training_orders(s, props, notes)
    assert [p.rule for p in kept] == ["squad_recall", "squad_attack"], kept
    assert len(notes) == 3
    src = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")
    assert src.index("_guard(prepare_training") < src.index("_guard(_killer_rule")
    assert src.index("guard_training_orders, s, proposals") < src.index("crisis.apply")


# --- 3. the bridge -------------------------------------------------------------------------

FAKE = r"""
local src = ...
local W = {site = {}, squads = {}, units = {}, calls = {}}
local env = setmetatable({}, {__index = _G})
env.df = {squad = {find = function(id) return W.squads[id] end},
          unit = {find = function(id) return W.units[id] end}}
env.dfhack = {
    units = {isCitizen = function(u) return u.citizen ~= false end,
             getReadableName = function(u) return u.name end},
    military = {addToSquad = function(uid, sid, place)
        table.insert(W.calls, {'add', uid, sid, place}); return true end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
local U = {site_get = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
           site_put = function(k, v) W.site[k] = v return true end}
local M = {}
function M.make_squad(dry, txt, opts)
    table.insert(W.calls, {'make', dry, opts and opts.training})
    if dry then return {ok = true, dry_run = true, leader = 'Logem'} end
    W.squads[40] = {id = 40, positions = {[0] = {occupant = 1}, {occupant = -1}, {occupant = -1}}}
    return {ok = true, squad_id = 40, leader = 'Logem'}
end
function M.fort_squad(id) return W.squads[id] end
function M.nursing_mothers() return {} end
function M.draftable(u) return u.draftable ~= false end
function M.fill(sid, n, txt, avoid, strict, keen_only)
    table.insert(W.calls, {'fill', sid, n, strict, keen_only})
    return {ok = true, added = {}}
end
env.reqscript = function(name)
    if name == 'ai-util' then return U end
    if name == 'ai-military' then return M end
    error('no module ' .. tostring(name))
end
-- ipairs over a squad's positions as DF's vector (from 0)
env.ipairs = function(t)
    local i = (t[0] ~= nil) and -1 or 0
    return function() i = i + 1; local v = t[i]; if v ~= nil then return i, v end end
end
assert(load(src, 'ai-training-squad', 't', env))()
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua, *lua.execute(FAKE, module_src("ai-training-squad.lua"))


def py(v):
    if hasattr(v, "items"):
        d = {k: py(x) for k, x in v.items()}
        if d and all(isinstance(k, int) for k in d):
            return [d[k] for k in sorted(d)]
        return d
    return v


@test("ai-training-squad: make marks the squad (a dry run marks nothing), fill takes volunteers only, forget unmarks")
def _():
    need_lua()
    lua, env, w = world()
    r = py(env.make(True, None))
    assert r["dry_run"] and not py(env.marks())
    r = py(env.make(False, None))
    assert r["ok"] and r["training"] and py(env.marks()) == {"40": True}, r
    assert py(w.calls)[1] == ["make", False, True]
    # not the training squad: refused
    assert py(env.fill(41, 2, False, None, lua.table(), None))["rejected"]
    r = py(env.fill(40, 5, False, None, lua.table(), None))
    assert r["ok"] and py(w.calls)[-1] == ["fill", 40, 2, False, True], py(w.calls)
    # one named dwarf into the first open place; a dry run adds nobody
    w.units[7] = lua.table_from({"id": 7, "name": "Logem"})
    n = len(py(w.calls))
    assert py(env.fill(40, 1, True, None, lua.table(), 7))["dry_run"] and len(py(w.calls)) == n
    r = py(env.fill(40, 1, False, None, lua.table(), 7))
    assert r["ok"] and py(w.calls)[-1] == ["add", 7, 40, 1], py(w.calls)
    w.units[8] = lua.table_from({"id": 8, "name": "Mebzuth", "draftable": False})
    assert py(env.fill(40, 1, False, None, lua.table(), 8))["rejected"]
    assert py(env.forget(40, True))["dry_run"] and py(env.marks()) == {"40": True}
    assert py(env.forget(40, False))["ok"] and not py(env.marks())


@test("bridge: action, dry run, module listed; make_squad's training branch; trim and report skip/mark it; the needs report")
def _():
    b = bridge_hub_src()
    assert "training_squad = function(a)" in b and "'training_squad'," in b
    assert "'ai-training-squad'" in b[b.index("BRIDGE_MODULES = {"):b.index("MARKED_MODULES")]
    m = split_src("ai-military.lua")   # (r8) the hub and its parts
    assert "function make_squad(dry_run, txt, opts)" in m
    assert "if training and rank == 1 then rank = nil end" in m
    assert "local from = not training and squad_with_uniform(fort, sq.id) or nil" in m
    assert "not tmarks[tostring(sid)]" in m and "training = tmarks[tostring(sid)] and true or nil" in m
    r = bridge_part_src("ai-bridge-report")
    assert "fight_need = fight_focus ~= nil or nil" in r and "content_ids" in r
    import gui_behaviour as GB              # (r5 p5) the settings and the window run, not their text
    GB.rule_switch("training_squad", "MilitaryPage", True)
    import overseer
    assert "training_squad" in overseer.SHORT_WORDS
    for k in ("training_squad_welfare", "training_squad_max", "training_squad_adults_per", "never_draft_days"):
        assert k in PLANNER_CONFIG
    assert re.search(r'"training_squad": st.get\("training_squad"\) is not False', py_family_src("planner_core"))


if __name__ == "__main__":
    finish()
