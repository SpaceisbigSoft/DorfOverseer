"""(0.105.48, K6) The cycle's guards (audits A9 3/4/5/7/9/10, A12 3/4).

  * record(): one hook raising no longer loses the alarm's and the gate's
    ownership, the cooldown, the action log; the failure is counted;
  * select(): one proposal's check raising holds that proposal (an EMERGENCY
    one goes as it is); its preamble guarded;
  * the overseer's steps (cycle_step): a failing step gives its default and a
    "rule cycle_<step> failed" note the health check tracks; whole failed
    cycles counted apart from idle polls;
  * the gate rules run without the military section, under their own guard;
  * an unread `stocks` is not an empty fort; no outdoor work in danger;
  * the refusal back-off per target; late EMERGENCY rules limit-exempt; the
    strategist can't hold the guards.

    python tests/test_k48_cycle_guards.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

import planner  # noqa: E402
import planner_core  # noqa: E402
import planner_guards  # noqa: E402
import health_check  # noqa: E402
from planner import Memory, Proposal, plan, record, select  # noqa: E402
from planner_core import PLANNER_CONFIG, refusal_key  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
NOW_STATE = {"date": {"year": 148, "tick": 332256}}


def fresh(mod=None) -> dict:
    s = json.loads(json.dumps(BASE))
    if mod:
        mod(s)
    return s


def boom(*a, **k):
    raise ValueError("injected")


class Patch:
    """Swap a module attribute for the test's length."""
    def __init__(self, mod, name, value):
        self.mod, self.name, self.value = mod, name, value

    def __enter__(self):
        self.old = getattr(self.mod, self.name)
        setattr(self.mod, self.name, self.value)

    def __exit__(self, *a):
        setattr(self.mod, self.name, self.old)


# --- record() ---------------------------------------------------------------

@test("record: a hook raising still books the alarm's ownership, the cooldown and the log")
def _():
    m = Memory()
    p = Proposal("threat_alert", {"type": "civ_alert", "on": True}, "a threat can reach the dwarves", 0)
    with Patch(planner, "note_holdfast", boom):
        record([(p, {"ok": True})], NOW_STATE, m)
    assert m.ai_alert_raised is True
    assert "threat_alert" in m.last_fired
    assert m.recent_actions and m.recent_actions[-1]["rule"] == "threat_alert"
    assert "record_note_holdfast" in m.guard_fails, m.guard_fails


@test("record: the AI gate's pull is owned even when an earlier step raised")
def _():
    m = Memory()
    p = Proposal("gate", {"type": "pull_gate", "lever_id": 7}, "a threat", 0)
    with Patch(planner, "note_gate_stuck", boom), Patch(planner, "note_way_out", boom):
        record([(p, {"ok": True})], NOW_STATE, m)
    assert m.gate_closed_by_ai is True
    assert isinstance(m.gate_pull_asked, int)
    assert {"record_note_gate_stuck", "record_note_way_out"} <= set(m.guard_fails)


@test("record: a later good record clears the count; a second failing cycle counts 2")
def _():
    m = Memory()
    p = Proposal("threat_alert", {"type": "civ_alert", "on": True}, "x", 0)
    with Patch(planner, "note_holdfast", boom):
        record([(p, {"ok": True})], NOW_STATE, m)
        record([(p, {"ok": True})], {"date": {"year": 148, "tick": 333456}}, m)
    assert m.guard_fails["record_note_holdfast"]["n"] == 2
    record([(p, {"ok": True})], {"date": {"year": 148, "tick": 334656}}, m)
    assert "record_note_holdfast" not in m.guard_fails


@test("record: a reply that isn't a dict is read as unknown, not a crash")
def _():
    m = Memory()
    p = Proposal("labor", {"type": "assign_labor", "job": "mining", "count": 1}, "x", 3)
    record([(p, None)], NOW_STATE, m)
    assert "labor" in m.last_fired


# --- select() ---------------------------------------------------------------

@test("select: one proposal's check raising holds it; the alarm still goes")
def _():
    m = Memory()
    s = fresh()
    props = [Proposal("threat_alert", {"type": "civ_alert", "on": True}, "threat", 0),
             Proposal("idle", {"type": "work_order", "recipe": "stone_blocks", "amount": 2}, "idle", 5, True)]
    with Patch(planner, "order_gate", boom):
        allowed, held = select(props, s, m)
    assert [p.rule for p in allowed] == ["threat_alert"], allowed
    assert any(h.startswith("idle: the limits' check failed") for h in held), held
    assert "select" in m.guard_fails


@test("select: its preamble guarded (mood_blocked, reserve_room raising)")
def _():
    m = Memory()
    props = [Proposal("idle", {"type": "work_order", "recipe": "stone_blocks", "amount": 2}, "idle", 5, True)]
    with Patch(planner, "mood_blocked", boom), Patch(planner, "reserve_room", boom):
        allowed, held = select(props, fresh(), m)
    assert "select" in m.guard_fails
    select([], fresh(), m)
    assert "select" not in m.guard_fails


@test("select: an EMERGENCY rule added after import (way_out) takes no action slot")
def _():
    import planner_way_out  # noqa: F401  (adds way_out to EMERGENCY)
    assert "way_out" in planner_core.EMERGENCY
    props = [Proposal("way_out", {"type": "way_out_open", "id": 1}, "shut in", -1)]
    props += [Proposal(f"r{i}", {"type": "tool", "name": f"t{i}", "enabled": True}, "x", 5) for i in range(3)]
    allowed, held = select(props, fresh(), Memory())
    assert len(allowed) == 4, (allowed, held)
    assert planner_core.limit_exempt("well_rescue") or "well_rescue" not in planner_core.EMERGENCY


# --- the strategist ---------------------------------------------------------

@test("the strategist can't hold the guards (intruder_guard, destroyer_gate, hospital_guard, near_gates...)")
def _():
    import strategist
    for rule in ("intruder_guard", "destroyer_gate", "hospital_guard", "staff_tantrum", "chronic_posts",
                 "near_gates", "hunting_stop"):
        act, why = strategist._check_steer({"type": "hold", "rule": rule, "days": 10, "why": "x"}, {rule})
        assert act is None and "can't be held" in why, (rule, act, why)
        m = Memory()
        m.steer = {rule: {"mode": "hold", "until": 10 ** 12, "why": "x"}}
        assert planner_core.steer_of(m, rule, 1000) is None, rule
    # any EMERGENCY rule, however late added
    planner_core.EMERGENCY.add("k48_test_rule")
    try:
        assert planner_core.steer_protected("k48_test_rule") and planner_core.limit_exempt("k48_test_rule")
    finally:
        planner_core.EMERGENCY.discard("k48_test_rule")


@test("emergency(): one call puts a rule in EMERGENCY, LIMIT_EXEMPT and STEER_PROTECTED")
def _():
    planner_core.emergency("k48_x")
    try:
        assert all("k48_x" in st for st in (planner_core.EMERGENCY, planner_core.LIMIT_EXEMPT,
                                              planner_core.STEER_PROTECTED))
    finally:
        for st in (planner_core.EMERGENCY, planner_core.LIMIT_EXEMPT, planner_core.STEER_PROTECTED):
            st.discard("k48_x")


# --- refusals per target ------------------------------------------------------

@test("refusal back-off per target: site, stone, item, landmark, district, library, id, ids (any order)")
def _():
    def k(rule, **a):
        return refusal_key(Proposal(rule, a, "x", 5))
    assert k("contact", type="send_mission", goal="make_contact", site_id=1) != \
        k("contact", type="send_mission", goal="make_contact", site_id=2)
    assert k("m", type="send_mission", goal="raid", site_id=1) != k("m", type="send_mission", goal="rescue", site_id=1)
    assert k("ores", type="allow_stone", stone="A") != k("ores", type="allow_stone", stone="B")
    assert k("a", type="display_artifact", item_id=1) != k("a", type="display_artifact", item_id=2)
    assert k("l", type="landmark_step", landmark_id=1) != k("l", type="landmark_step", landmark_id=2)
    assert k("s", type="dig_stairwell", district="d1") != k("s", type="dig_stairwell", district="d2")
    assert k("i", type="import_orders", library="a") != k("i", type="import_orders", library="b")
    assert k("w", type="way_out_open", id=1) != k("w", type="way_out_open", id=2)
    assert k("o", type="mine_ore", metal="IRON") != k("o", type="mine_ore", metal="COPPER")
    assert k("c", type="pit_prisoners", ids=[3, 1]) == k("c", type="pit_prisoners", ids=[1, 3])
    assert k("c", type="pit_prisoners", ids=[1]) != k("c", type="pit_prisoners", ids=[2])
    assert k("killer", type="killer_cell", units=[1]) != k("killer", type="killer_cell", units=[2])
    # the old keys unchanged
    assert k("x", type="tool", name="a") == "x:" + json.dumps({"name": "a", "type": "tool"}, sort_keys=True)


@test("one site's refusals don't hold another site")
def _():
    m = Memory()
    a = Proposal("contact", {"type": "send_mission", "goal": "make_contact", "site_id": 1}, "x", 5)
    b = Proposal("contact", {"type": "send_mission", "goal": "make_contact", "site_id": 2}, "x", 5)
    record([(a, {"ok": False, "error": "no"})], NOW_STATE, m)
    now = planner_core.abs_tick(NOW_STATE)
    assert planner_core._refused_wait(m, a, now + 1) is not None
    assert planner_core._refused_wait(m, b, now + 1) is None


# --- the overseer's steps -----------------------------------------------------

@test("cycle_step: a failing step gives its default, is counted and said as a 'rule ... failed' note")
def _():
    import overseer
    m = Memory()
    said = []
    with Patch(overseer, "say", said.append):
        out = overseer.cycle_step(m, NOW_STATE, "observe", boom, default=[])
    assert out == []
    assert "cycle_observe" in m.guard_fails
    lines = planner_guards.guard_lines(m)
    assert lines and all(health_check.FAIL_NOTE.match(x) for x in lines), lines
    assert any("Step observe failed" in x for x in said)
    assert overseer.cycle_step(m, NOW_STATE, "observe", lambda: 5) == 5
    assert "cycle_observe" not in m.guard_fails


@test("one_cycle: the steps before the plan, the strategist, select and the record all go through cycle_step")
def _():
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    body = src[src.index("def one_cycle("):src.index("def remember_world(")]
    for name in ("observe", "note_cycle", "note_tantrums", "note_heists", "note_intrusions", "note_events",
                 "remember_world", "calibrate", "outcomes", "culture", "plan", "strategist", "learning_apply",
                 "select", "record", "learning_actions", "outcomes_actions", "atlas", "masterplan"):
        assert f'cycle_step(memory, state, "{name}"' in body, name
    assert "guard_lines(memory)" in body
    for bare in ("learned_now = learning.observe(", "\n        note_tantrums(state, memory, events)",
                 "proposals, plan_notes = plan(state, memory, cfg)", "allowed, held = select(proposals",
                 "\n                record(results, state, memory, cfg)"):
        assert bare not in body, bare


@test("whole failed cycles: counted apart from idle polls, a standing 'rule cycle failed' line")
def _():
    import overseer
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    run = src[src.index("def _run("):]
    assert "failed_cycles += 1" in run and "in_cycle = True" in run
    seen = {}
    with Patch(health_check, "track_standing", lambda fort, todo, notes, tick: seen.update({fort: notes})):
        overseer.note_failed_cycles(3, ValueError("x"))
        assert seen["_overseer"] and health_check.FAIL_NOTE.match(seen["_overseer"][0])
        assert "3 cycle(s) in a row" in seen["_overseer"][0]
        overseer.note_failed_cycles(0, None)
        assert seen["_overseer"] == []


# --- plan(): the gates without the military section ---------------------------

@test("plan: the gate rules run when the military section failed (and when a squad rule raises)")
def _():
    props, _n = plan(fresh(), Memory())
    assert any(p.rule == "second_way" for p in props)          # from _gate_rules
    props, notes = plan(fresh(lambda s: s.update(military={"error": "x"})), Memory())
    assert any(p.rule == "second_way" for p in props), (sorted({p.rule for p in props}), notes)
    with Patch(planner, "_military_rules", boom):
        props, notes = plan(fresh(), Memory())
    assert any(p.rule == "second_way" for p in props)
    assert any(n.startswith("rule boom failed") for n in notes)


@test("plan: _military_rules no longer runs the gate rules a second time")
def _():
    calls = []
    real = planner._gate_rules
    with Patch(planner, "_gate_rules", lambda *a, **k: (calls.append(1), real(*a, **k))):
        import planner_military
        with Patch(planner_military, "_gate_rules", lambda *a, **k: (calls.append(2), real(*a, **k))):
            plan(fresh(), Memory())
    assert calls == [1], calls


# --- unknown is not zero; no outdoor work in danger -----------------------------

def _shrubs(s):
    s["labor"] = {"shrubs": 50, "gather_marked": 0}


def _no_food(s):
    _shrubs(s)
    for k, v in list(s["stocks"].items()):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            s["stocks"][k] = 0


def _siege(s):
    s["others_on_map"]["threats"].append({"id": 999001, "name": "goblin", "invader": True,
                                          "can_reach_dwarves": True, "distance_to_nearest_dwarf": 20,
                                          "pos": {"x": 1, "y": 1, "z": 1}})
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1


@test("plan: with food at 0 the gather rule fires (the control)")
def _():
    props, _n = plan(fresh(_no_food), Memory())
    assert any(p.rule == "gather" for p in props)


@test("plan: an unread stocks section is not an empty fort: no gathering on it")
def _():
    props, notes = plan(fresh(lambda s: (_shrubs(s), s.update(stocks={"error": "x"}))), Memory())
    assert not any(p.rule == "gather" for p in props), [p.rule for p in props]
    assert any("stocks couldn't be read" in n for n in notes), notes


@test("plan: no gathering outside while a threat can reach the dwarves (food at 0)")
def _():
    props, notes = plan(fresh(lambda s: (_no_food(s), _siege(s))), Memory())
    assert not any(p.rule == "gather" for p in props), [p.rule for p in props]
    assert any("no work outside" in n for n in notes), notes


@test("outdoor_filter: what counts as outside; EMERGENCY and indoor work kept; nothing held in peace")
def _():
    P = Proposal
    out = [P("gather", {"type": "gather_plants", "count": 5}, "x", 2),
           P("labor", {"type": "assign_labor", "job": "fishing", "count": 2}, "x", 3),
           P("labor", {"type": "assign_labor", "job": "woodcutting", "count": 1}, "x", 3),
           P("hunting", {"type": "hunters", "count": 2}, "x", 4),
           P("tree_quota", {"type": "tool", "name": "autochop", "enabled": True}, "x", 4),
           P("refuse", {"type": "place_surface", "kind": "refuse"}, "x", 4),
           P("keep", {"type": "place_keep"}, "x", 4),
           P("surface_farm", {"type": "farm_plots", "tiles": 9, "outside": True}, "x", 4),
           P("new_pasture", {"type": "make_pasture", "tiles": 9}, "x", 4),
           P("traps", {"type": "place_traps", "entrance_id": 1}, "x", 5),
           P("grove", {"type": "keep_grove"}, "x", 5)]
    keep = [P("hunting_stop", {"type": "hunters", "stop": True}, "x", 0),
            P("grove_guard", {"type": "keep_grove", "guard": True}, "x", 5),
            P("labor", {"type": "assign_labor", "job": "mining", "count": 2}, "x", 3),
            P("farm", {"type": "farm_plots", "tiles": 9, "dig": True}, "x", 4),
            P("way_in", {"type": "place_surface", "kind": "x"}, "x", 0)]     # EMERGENCY: never held
    assert all(planner_guards.is_outdoor(p) for p in out)
    assert not any(planner_guards.is_outdoor(p) for p in keep[:4])
    s = planner.normalize(fresh(_siege))
    notes: list = []
    kept = planner_guards.outdoor_filter(s, Memory(), {}, PLANNER_CONFIG, out + keep, notes)
    assert kept == keep and notes
    s = planner.normalize(fresh())
    assert planner_guards.outdoor_filter(s, Memory(), {}, PLANNER_CONFIG, out + keep, []) == out + keep
    s = planner.normalize(fresh(lambda x: x.update(civ_alert=True)))
    assert planner_guards.outdoor_filter(s, Memory(), {}, PLANNER_CONFIG, out, []) == []
    s = planner.normalize(fresh(lambda x: x.update(others_on_map={"error": "x"})))
    assert planner_guards.outdoor_filter(s, Memory(), {}, PLANNER_CONFIG, out, []) == []


@test("unknown_filter: a release or a stop is never held; sections that were read hold nothing")
def _():
    P = Proposal
    props = [P("recreation", {"type": "recreation", "release": True, "max": 1}, "x", 3),
             P("recreation", {"type": "recreation", "max": 1}, "x", 3),
             P("good_cooks", {"type": "kitchen_skill", "min_level": 0}, "x", 3)]
    s = planner.normalize(fresh(lambda x: x.update(others_on_map={"error": "x"}, stocks={"error": "y"})))
    notes: list = []
    kept = planner_guards.unknown_filter(s, props, notes)
    assert kept == props[:1] and len(notes) == 2, (kept, notes)
    assert planner_guards.unknown_filter(planner.normalize(fresh()), props, []) == props


@test("plan: the preamble guarded (_traits raising: neutral sliders, the rules still run)")
def _():
    with Patch(planner, "_traits", boom):
        props, notes = plan(fresh(), Memory())
    assert any(n.startswith("rule boom failed") for n in notes), notes[:5]
    assert any(p.rule == "second_way" for p in props)


if __name__ == "__main__":
    finish()
