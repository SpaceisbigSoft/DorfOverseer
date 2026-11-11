"""(0.105.36, group core) The focused audit's core findings fixed: a workshops
level loses only its held shops (and a mood's is never held), the AI gate's
lever read from the gate itself, the shelter paced one way everywhere and
never a Needs you, the cavern alarm cap and the strategist's alarm-off kept
behind the other dangers, an unread alarm never read as the player's
lowering, a refused kill order not stamped, labour given under a timeout
counted, the stranded rule never raised. Fake reports, and ai-military's
gate_levers in a real Lua 5.3 engine.

    python tests/test_r36_core.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish  # noqa: E402
from lupa.lua53 import LuaRuntime  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

import planner  # noqa: E402
import planner_core  # noqa: E402
import planner_military as pm  # noqa: E402
import planner_threats as pt  # noqa: E402
import strategist  # noqa: E402
from planner import Memory, Proposal, note_cycle, note_gate_lever, plan, record, select, PLANNER_CONFIG as CFG  # noqa: E402
import test_planner as TPL  # noqa: E402

test = make_test()
DAY = planner_core.TICKS_PER_DAY
YOU = "[you] "


def yous(notes):
    return [n for n in notes if isinstance(n, str) and n.startswith(YOU)]


def no_still(s):
    ws = dict(s["buildings"].get("workshops") or {})
    ws.pop("Still", None)
    s["buildings"]["workshops"] = ws
    return s


# --- workshops levels: the held shops left out, a mood's never held ----------------------

@test("two levels carrying the added Still: a later level goes without the Still (was: every level held 56 days)")
def _():
    s = no_still(TPL.fort())
    m = Memory()
    for i, (rule, shop) in enumerate((("kiln", "Kilns"), ("bags", "Clothiers"))):
        s["date"]["tick"] = 100000 + i * 3 * DAY
        p = Proposal(rule, {"type": "start_project", "kind": "workshops", "shops": [shop]}, "x", 4)
        # (the added Still is plan()'s _survival_shops; marked here as it marks it)
        p.action = dict(p.action, shops=["Still", shop], added_shops=["Still"])
        a, h = select([p], s, m)
        assert a, h
        record([(a[0], {"ok": True, "project_id": 50 + i})], s, m)
    assert m.shops_started["Still"] == 2
    s["date"]["tick"] = 100000 + 7 * DAY
    p = Proposal("industry", {"type": "start_project", "kind": "workshops", "shops": ["Still", "Masons"],
                              "added_shops": ["Still"]}, "x", 4)
    a, h = select([p], s, m)
    assert a and a[0].action["shops"] == ["Masons"] and a[0].action["added_shops"] == [], (a, h)
    assert any("Still left out of this level" in x and "the rest of it goes ahead" in x for x in h), h
    record([(a[0], {"ok": True, "project_id": 60})], s, m)
    assert m.shops_started["Still"] == 2 and m.shops_started["Masons"] == 1     # the left-out shop not counted


@test("a level left with only shops it didn't ask for is held whole; one whose own shop is held, too")
def _():
    s = no_still(TPL.fort())
    m = Memory(shops_started={"Masons": 2}, shops_seen={"Masons": 99})
    p = Proposal("industry", {"type": "start_project", "kind": "workshops", "shops": ["Still", "Masons"],
                              "added_shops": ["Still"]}, "x", 4)
    a, h = select([p], s, m)
    assert not a and any("started twice already" in x and "left out" not in x for x in h), h


@test("a strange mood's level is never held by the started-twice guard, retries spent or not")
def _():
    s = no_still(TPL.fort())
    m = Memory(shops_started={"Craftsdwarfs": 2, "Still": 2}, shops_seen={"Craftsdwarfs": 99, "Still": 99},
               shops_retried={"Craftsdwarfs": 3})
    p = Proposal("mood", {"type": "start_project", "kind": "workshops", "shops": ["Still", "Craftsdwarfs"],
                          "urgent": True}, "Urist is in a fey mood", 0)
    a, h = select([p], s, m)
    assert [x.rule for x in a] == ["mood"] and a[0].action["shops"] == ["Still", "Craftsdwarfs"], h


@test("a shop seen built clears its hold's clock too (a later 'started twice' waits the full 56 days)")
def _():
    s = TPL.fort()
    n = planner_core.shop_count(s["buildings"], "Masons")
    m = Memory(shops_started={"Masons": 2}, shops_seen={"Masons": n - 1}, shops_held_since={"Masons": 5},
               shops_retried={"Masons": 1})
    p = Proposal("industry", {"type": "start_project", "kind": "workshops", "shops": ["Masons"]}, "x", 4)
    select([p], s, m)
    assert "Masons" not in m.shops_held_since and "Masons" not in m.shops_retried


# --- the AI gate's lever: read from the gate ---------------------------------------------

def lever_fort(shut, state=1, threat=True):
    s = TPL.under_attack() if threat else TPL.fort()
    s["military"] = dict(s.get("military") or {}, gates=[{"id": 7, "state": state, "linked": 1, "pending": False,
                                                          "shut": shut}])
    return s


@test("gate lever: a gate the player left shut is not learnt as open, and never pulled (opened) on an attack")
def _():
    s = lever_fort(True)
    m = Memory()
    note_gate_lever(planner.normalize(s), m)
    assert m.gate_open_state == {"7": 0} and not m.gate_closed_by_ai, (m.gate_open_state, m.gate_closed_by_ai)
    p, _ = plan(copy.deepcopy(s), m)
    assert not [x for x in p if x.action.get("type") == "pull_gate"], [x.action for x in p]


@test("gate lever: an open gate is pulled on an attack, and read shut after the pull is the AI's (pulled back later)")
def _():
    s = lever_fort(False, state=0)
    m = Memory()
    note_gate_lever(planner.normalize(s), m)
    assert m.gate_open_state == {"7": 0} and not m.gate_closed_by_ai
    p, _ = plan(copy.deepcopy(s), m)
    pull = [x for x in p if x.action.get("type") == "pull_gate"]
    assert pull, [x.action for x in p]
    record([(pull[0], {"ok": True})], s, m)
    assert m.gate_pull_asked == planner_core.abs_tick(s)
    t = lever_fort(True, state=1)
    t["date"] = dict(s["date"], tick=s["date"]["tick"] + DAY // 2)
    note_gate_lever(planner.normalize(t), m)
    assert m.gate_closed_by_ai and m.gate_open_state == {"7": 0}
    t = lever_fort(True, state=1)                 # still shut days later: still the AI's
    t["date"] = dict(s["date"], tick=s["date"]["tick"] + 9 * DAY)
    note_gate_lever(planner.normalize(t), m)
    assert m.gate_closed_by_ai
    t["military"]["gates"][0].update(state=0, shut=False)        # the player opened it: no longer the AI's
    note_gate_lever(planner.normalize(t), m)
    assert not m.gate_closed_by_ai


LEVER_RIG = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local function ref(t, id) return {building_id = id, getType = function() return t end} end
local B = {}
env.B = B
env.df = {general_ref_type = {BUILDING_HOLDER = 1, BUILDING_TRIGGERTARGET = 2},
          trap_type = {Lever = 5},
          building_bridgest = {is_instance = function(_, b) return b.kind == 'bridge' end},
          building = {find = function(id) return B[id] end},
          global = {world = {buildings = {other = {TRAP = {}}}}}}
env.mk_lever = function(id, targets)
    local mechs = {}
    for _, tid in ipairs(targets) do table.insert(mechs, {general_refs = {ref(1, tid)}}) end
    local lv = {id = id, trap_type = 5, name = 'AI gate', state = 1, linked_mechanisms = mechs, jobs = {},
                centerx = 1, centery = 1, z = 1}
    env.df.global.world.buildings.other.TRAP = {lv}
    return lv
end
assert(load(src, 'ai-military', 't', env))()
return env
"""


@test("gate_levers (Lua 5.3): reports the gate's own shut state: a bridge raised, a door closed; nil when mixed")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(LEVER_RIG, module_src("ai-military.lua"))
    lua.execute("""local env = ...
        env.B[10] = {kind = 'bridge', gate_flags = {raised = true}}
        env.B[11] = {kind = 'door', door_flags = {closed = false}}
        env.B[12] = setmetatable({kind = 'floodgate', gate_flags = {closed = true}},
                                 {__index = function(_, k) if k == 'door_flags' then error('no field') end end})""", env)
    env.mk_lever(7, lua.table(10))
    assert env.gate_levers()[1].shut is True
    env.mk_lever(7, lua.table(11))
    assert env.gate_levers()[1].shut is False
    env.mk_lever(7, lua.table(12))
    assert env.gate_levers()[1].shut is True
    env.mk_lever(7, lua.table(10, 11))
    assert env.gate_levers()[1].shut is None
    env.mk_lever(7, lua.table(99))                     # a target that can't be found
    r = env.gate_levers()[1]
    assert r.shut is None and r.id == 7 and r.linked == 1


# --- the shelter: one pace, no Needs you ---------------------------------------------------

@test("shelter: a refusal books no back-off (its own 3-day pace holds, as the note says)")
def _():
    s = TPL.under_attack()
    s["civ_alert_ready"] = False
    m = Memory()
    base = s["date"]["tick"]
    tried = []
    for day in range(16):
        s["date"]["tick"] = base + day * DAY
        p, notes = plan(copy.deepcopy(s), m)
        a, h = select([x for x in p if x.rule == "shelter"], s, m)
        if a:
            tried.append(day)
            record([(a[0], {"ok": False, "error": "the game refused the burrow"})], s, m)
        else:
            assert not any("refused it" in x for x in h), h
    assert tried == [0, 1, 4, 7, 10, 13], tried            # two tries, then every 3 days (no 1-2-4... days)
    assert not m.refusals.get(planner_core.refusal_key(Proposal("shelter", {"type": "setup_shelter"}, "", 0)))


@test("shelter: an unread alarm burrow is said as unread (no refusal claimed, no Needs you)")
def _():
    s = TPL.fort()
    s["civ_alert"], s["civ_alert_ready"] = False, {"error": "boom"}
    line = planner._no_shelter_note(planner.normalize(s), Memory(), "a werebeast")
    assert "couldn't be read this cycle" in line and "refused" not in line, line
    s["hazards"] = {"fire_near": 3}
    props, notes = [], []
    pm._hazard_rules(planner.normalize(s), Memory(), CFG, props, notes, pm.player_rules(s))
    assert not yous(notes) and any("couldn't be read" in n for n in notes), notes


@test("no_shelter: paced as plan()'s retry (tried again after the wait) and never a Needs you")
def _():
    s = TPL.fort()
    s["civ_alert"], s["civ_alert_ready"] = False, False
    now = planner_core.abs_tick(s)
    for tick, want in ((now - 400 * DAY, True), (now - DAY, False)):
        props, notes = [], []
        pm.no_shelter(s, Memory(shelter_attempts=2, shelter_tick=tick), "a werebeast", props, notes)
        assert bool([p for p in props if p.rule == "shelter"]) == want and not yous(notes), (props, notes)
    assert any("tried again in 2 day(s)" in n for n in notes), notes


@test("shelter: a set-up that worked isn't counted as a refusal")
def _():
    s = TPL.fort()
    m = Memory(shelter_attempts=1)
    record([(Proposal("shelter", {"type": "setup_shelter"}, "x", 0), {"ok": True})], s, m)
    assert m.shelter_attempts == 0


# --- the alarm ---------------------------------------------------------------------------

def cavern_state():
    s = {"date": {"year": 3, "tick": 0}, "settings": {}, "civ_alert": True, "civ_alert_ready": True,
         "deep": {"dangers": [{"kind": "forgotten beast", "name": "Ber", "layer": "Cavern 1"}], "caverns": []},
         "hazards": {"berserk": [{"id": 7, "name": "Urist"}]},
         "others_on_map": {"threats_that_can_reach_dwarves": 0}, "_errors": {}}
    t = {"sealed": {}, "openings": {"list": [{"kind": "door", "building": "Door", "built": True}]},
         "cavern_citizens": {"n": 1, "list": [{"name": "Kib", "x": 1, "y": 1, "z": 1}]}}
    return s, t


@test("cavern alarm cap: not let down while a berserk dwarf holds the alarm (the ways are still locked)")
def _():
    s, t = cavern_state()
    m = Memory(ai_alert_raised=True, cavern_alarm={"since": 0})
    s["date"]["tick"] = 5 * DAY
    p, n = [], []
    pt._cavern_beasts(s, CFG, m, t, pt.threat_rules_of(s), p, n)
    assert not [x for x in p if x.action.get("type") == "civ_alert"], [x.action for x in p]
    assert [x for x in p if x.action.get("type") == "seal_cavern"]
    assert any("the alarm stays up for Urist" in x for x in n), n
    s["hazards"] = {}
    p, n = [], []
    pt._cavern_beasts(s, CFG, m, t, pt.threat_rules_of(s), p, n)
    assert [x for x in p if x.action == {"type": "civ_alert", "on": False}], [x.action for x in p]


@test("the strategist's alarm-off is held while a berserk dwarf or a reachable threat keeps it up; else let through")
def _():
    strat = lambda: Proposal("strategist", {"type": "civ_alert", "on": False}, "strategist: back to work", 1)
    s = TPL.fort()
    s["civ_alert"] = True
    s["hazards"] = {"berserk": [{"id": 555, "name": "Urist"}]}
    m = Memory(ai_alert_raised=True)
    a, h = select([strat()], s, m)
    assert not a and any("the alarm stays up" in x and "Urist" in x for x in h), h
    a, h = select([strat()], TPL.under_attack(), m)
    assert not a and any("can reach the dwarves" in x for x in h), h
    s = TPL.fort()
    s["civ_alert"] = True
    a, h = select([strat()], s, m)
    assert [x.rule for x in a] == ["strategist"], h


@test("an unread alarm (failed or missing) is not the player's lowering: ownership kept, nothing raised on a guess")
def _():
    for bad in ({"error": "read failed"}, None):
        s = TPL.fort()
        if bad is None:
            s.pop("civ_alert", None)
        else:
            s["civ_alert"] = bad
        m = Memory(ai_alert_raised=True, alert_asked={"on": True, "tick": planner_core.abs_tick(s) - 5 * DAY})
        note_cycle(s, m)
        assert m.ai_alert_raised and m.alert_suppressed == [] and m.alert_asked, (bad, m.ai_alert_raised)
        assert "civ_alert" in s["_errors"]
    s = TPL.under_attack()
    s["civ_alert"] = {"error": "read failed"}
    p, notes = plan(s, Memory())
    assert not [x for x in p if x.action.get("type") == "civ_alert"] and any(
        "the alarm couldn't be read" in n for n in notes), notes


@test("an AI switch-off whose reply never came is matched on the first good tools read, even days later")
def _():
    s = TPL.fort()
    name = next(k for k, v in s["tools"].items() if isinstance(v, bool))
    m = Memory(tools_seen_on=[name], tool_off_asked={name: planner_core.abs_tick(s) - 3 * DAY})
    s["tools"][name] = False
    note_cycle(s, m)
    assert name not in m.tools_player_disabled and name not in m.tools_seen_on and not m.tool_off_asked


# --- kill orders, labour, the strategist's raise --------------------------------------------

@test("a refused kill order isn't stamped (a new send at the berserk dwarf isn't held a day)")
def _():
    s = TPL.fort()
    m = Memory()
    p = Proposal("berserk", {"type": "squad_orders", "squad_id": 3, "kill": [7]}, "x", 0)
    record([(p, {"ok": False, "error": "refused"})], s, m)
    assert "3" not in m.kill_sent and "3" not in m.kill_sent_at
    record([(p, {"ok": None})], s, m)
    assert m.kill_sent["3"] == [7] and m.kill_sent_at["3"] == planner_core.abs_tick(s)


@test("labour given under a timeout (ok None) counts toward the yearly cap")
def _():
    s = TPL.fort()
    m = Memory()
    rule = next(iter(planner_core.LABOR_CAPS))
    p = Proposal(rule, {"type": "assign_labor", "job": "X", "count": 2}, "x", 2)
    planner_core.note_labor_given(m, p, {"ok": None}, planner_core.abs_tick(s))
    planner_core.note_labor_given(m, p, {"ok": False}, planner_core.abs_tick(s))
    assert planner_core.labor_given(m, rule, planner_core.abs_tick(s)) == 2


@test("the strategist can't raise the stranded rule (it opens gates on its own per-entrance pace)")
def _():
    assert "stranded" in strategist.RAISE_FORBIDDEN
    s = TPL.fort()
    m = Memory()
    m.steer = {"stranded": {"mode": "raise", "until": planner_core.abs_tick(s) + 9 * DAY, "why": "x"},
               "kiln": {"mode": "raise", "until": planner_core.abs_tick(s) + 9 * DAY, "why": "x"}}
    note_cycle(s, m)
    assert "stranded" not in m.steer and "kiln" in m.steer, m.steer


finish(test)
