"""r33, group planner: the planner's frame (planner.py, planner_core,
planner_building, masterplan).

- the AI gate read from its lever's state, not toggled on every pull (B2 High)
- an alarm change or a tool switch-off whose reply never came (ok None):
  owned once the next report shows it (B2 High, B2 Med)
- the hostile-trade filter's [] kept (B2 Med)
- a stalled level's freed jobs and a well's renewed channel marked in
  record(), not plan() (B2 Med)
- plan()'s and note_cycle()'s unguarded blocks guarded (B2 Med)
- the waterworks' flood stop reached through plan() (T1 Med)
- Industriousness: the polish gate on the levels finished ever, its share
  and the blocks cap by the slider, the idle rules on the truly idle
- Spacing on every new level (customs_pass)
- Lows: the loop log's length, a non-tick last_fired, the agenda's farms,
  masterplan.ensure

    python tests/test_r33_planner.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import planner  # noqa: E402
from digest import _d, normalize  # noqa: E402
from planner import Memory, Proposal, note_cycle, note_gate_lever, plan, record, select  # noqa: E402
from planner_core import (PLANNER_CONFIG, TICKS_PER_DAY, LOOP_LIMITS, AGENDA_THEMES, _idle_share,  # noqa: E402
                          _loop_count, levels_done, factor)

FIX = ROOT / "tests" / "fixtures" / "test_fort.json"      # test_planner's fort (194 dwarves)


def real(traits: dict | None = None) -> dict:
    s = json.loads(FIX.read_text(encoding="utf-8"))
    s["date"]["season"] = "spring"
    if traits is not None:
        s.setdefault("settings", {})["traits"] = dict(s["settings"].get("traits") or {}, **traits)
    return s


def under_attack_state() -> dict:
    s = real()
    s["others_on_map"]["threats"] = [{"id": 900 + i, "name": "Goblin", "great_danger": False,
                                      "can_reach_dwarves": True, "invader": True} for i in range(2)]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 2
    return s


def failed(notes):
    return [n for n in notes if " failed (" in n]


# --- the AI gate: its lever's state -------------------------------------------------

def lever(state, pending=False, linked=1):
    return {"military": {"gates": [{"id": 77, "state": state, "linked": linked, "pending": pending}]},
            "entrances": {"entrances": []}}


@test("r33 gate: a pull queued but never done (job dropped) leaves the gate open; the next attack pulls again")
def _():
    m = Memory()
    note_gate_lever(lever(0), m)                     # first sight: open at state 0
    assert m.gate_open_state == {"77": 0} and not m.gate_closed_by_ai
    g = Proposal("gate", {"type": "pull_gate", "lever_id": 77}, "x", 0)
    st = dict(lever(0), date={"year": 250, "tick": 0})
    record([(g, {"ok": True})], st, m)
    assert not m.gate_closed_by_ai, "a queued pull is not a shut gate"
    note_gate_lever(lever(0, pending=True), m)       # on its way: the last reading kept
    assert not m.gate_closed_by_ai
    note_gate_lever(lever(0), m)                     # the job was cancelled: still open
    assert not m.gate_closed_by_ai


@test("r33 gate: a pull whose reply never came (ok None) but happened reads shut, and the all-clear opens it")
def _():
    m = Memory()
    note_gate_lever(lever(1), m)
    g = Proposal("gate", {"type": "pull_gate", "lever_id": 77}, "x", 0)
    record([(g, {"ok": None})], dict(lever(1), date={"year": 250, "tick": 0}), m)
    note_gate_lever(lever(0), m)                     # it was pulled after all
    assert m.gate_closed_by_ai and m.gate_open_state == {"77": 1}
    note_gate_lever(lever(1), m)                     # pulled back
    assert not m.gate_closed_by_ai


@test("r33 gate: an older save that says the AI shut it takes the lever's state as shut; an older bridge toggles")
def _():
    m = Memory(gate_closed_by_ai=True)
    note_gate_lever(lever(1), m)
    assert m.gate_closed_by_ai and m.gate_open_state == {"77": 0}
    # a lever with no state (an older bridge): record() toggles, as before
    m = Memory()
    g = Proposal("gate", {"type": "pull_gate", "lever_id": 77}, "x", 0)
    st = {"date": {"year": 250, "tick": 0}, "military": {"gates": [{"id": 77, "linked": 1, "pending": False}]}}
    record([(g, {"ok": True})], st, m)
    assert m.gate_closed_by_ai
    note_gate_lever(st, m)
    assert m.gate_closed_by_ai and m.gate_open_state == {}
    # the gate watcher's drawbridge lever is not this gate
    m = Memory()
    s = lever(1)
    s["entrances"] = {"entrances": [{"equipment": [{"levers": [77]}]}]}
    note_gate_lever(s, m)
    assert m.gate_open_state == {} and not m.gate_closed_by_ai


@test("r33 gate: through note_cycle and plan, a dropped pull is asked again on the next attack")
def _():
    s = under_attack_state()
    s["military"]["gates"] = [{"id": 77, "state": 0, "linked": 1, "pending": False}]
    m = Memory()
    note_cycle(copy.deepcopy(s), m)
    g = [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "gate"]
    assert g and g[0].action["type"] == "pull_gate", g
    record([(g[0], {"ok": True})], s, m)
    note_cycle(copy.deepcopy(s), m)                  # the lever still at 0: nobody pulled it
    assert not m.gate_closed_by_ai
    assert [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "gate"], "asked again"


# --- the alarm and the tools under a timeout -------------------------------------------

def report(civ_alert, tools=None):
    s = real()
    s["civ_alert"] = civ_alert
    s["others_on_map"]["threats"] = []
    if tools is not None:
        s["tools"] = tools
    return s


@test("r33 alarm: raised with no reply (ok None) and on in the next report: the AI's, so it can lower it")
def _():
    s = report(False)
    m = Memory()
    p = Proposal("threat_alert", {"type": "civ_alert", "on": True}, "x", 0)
    record([(p, {"ok": None, "error": "no reply from the game"})], s, m)
    assert not m.ai_alert_raised and m.alert_asked.get("on") is True
    note_cycle(report(True), m)
    assert m.ai_alert_raised and m.alert_asked == {}


@test("r33 alarm: lowered with no reply and off in the next report: not the player's lowering (no suppression)")
def _():
    m = Memory(ai_alert_raised=True)
    s = report(True)
    p = Proposal("threat_alert", {"type": "civ_alert", "on": False}, "x", 0)
    record([(p, {"ok": None})], s, m)
    assert m.ai_alert_raised                          # unknown yet
    s2 = report(False)
    s2["others_on_map"]["threats"] = [{"id": 5, "can_reach_dwarves": True, "race": "GOBLIN"}]
    note_cycle(s2, m)
    assert not m.ai_alert_raised and m.alert_suppressed == [], m.alert_suppressed
    assert not (m.intrusion or {}).get("cleared")
    # the player's own lowering is still read as theirs
    m = Memory(ai_alert_raised=True)
    note_cycle(copy.deepcopy(s2), m)
    reach = planner.reachable_threats(normalize(copy.deepcopy(s2)), {}, PLANNER_CONFIG)
    assert reach and not m.ai_alert_raised and m.alert_suppressed == list(reach), (reach, m.alert_suppressed)


@test("r33 alarm: an asked change the report never shows is forgotten after a day")
def _():
    m = Memory()
    s = report(False)
    record([(Proposal("threat_alert", {"type": "civ_alert", "on": True}, "x", 0), {"ok": None})], s, m)
    note_cycle(report(False), m)
    assert m.alert_asked and not m.ai_alert_raised    # not yet through: kept a day
    later = report(False)
    later["date"]["tick"] += 2 * TICKS_PER_DAY
    note_cycle(later, m)
    assert m.alert_asked == {}
    later2 = report(True)                             # the player's own alarm later: not taken over
    later2["date"]["tick"] += 3 * TICKS_PER_DAY
    note_cycle(later2, m)
    assert not m.ai_alert_raised


@test("r33 tools: the AI's switch-off with no reply, seen off next: not booked as the player's; it may come back")
def _():
    m = Memory(tools_seen_on=["autochop"], tools_confirmed_on=["autochop"], tools_enabled_by_ai=["autochop"])
    s = report(False, tools={"autochop": True})
    p = Proposal("tree_quota", {"type": "tool", "name": "autochop", "enabled": False}, "x", 3)
    record([(p, {"ok": None})], s, m)
    assert "autochop" in m.tool_off_asked
    notes = note_cycle(report(False, tools={"autochop": False}), m)
    assert "autochop" not in m.tools_player_disabled, notes
    assert "autochop" not in m.tools_seen_on and m.tool_off_asked == {}
    # without the ask (the player switched it off): booked as theirs, as before
    m = Memory(tools_seen_on=["autochop"])
    note_cycle(report(False, tools={"autochop": False}), m)
    assert "autochop" in m.tools_player_disabled


# --- the hostile-trade filter's answer -------------------------------------------------

@test("r33 hostile trade: [] from the filter (every proposal trade with an enemy) is kept, not undone by `or`")
def _():
    s = real()
    s["world"] = {"caravans": []}
    real_filter = planner._hostile_trade_filter
    try:
        planner._hostile_trade_filter = lambda s_, props, notes: []
        props, _ = plan(copy.deepcopy(s), Memory())
        assert props == [], props
        planner._hostile_trade_filter = lambda s_, props, notes: 1 / 0     # a failure: the proposals stand
        props2, notes2 = plan(copy.deepcopy(s), Memory())
        assert props2 and any("_lambda_" in n or "<lambda>" in n for n in notes2), notes2
    finally:
        planner._hostile_trade_filter = real_filter


# --- dig marks in record() ------------------------------------------------------------------

@test("r33 dig: free_dig_jobs held back (nothing recorded) is proposed again; once done, not again")
def _():
    cfg = PLANNER_CONFIG
    m = Memory()
    proj = {"id": 7, "kind": "bedrooms", "phase": "dig", "dig": {"dug": 10, "total": 89, "digging": 3}}
    rule = planner._dig_stall_rule
    rule({"date": {"year": 250, "tick": 0}}, m, cfg, [proj], [], [])
    s1 = {"date": {"year": 250, "tick": (cfg["dig_stall_days"] + 1) * TICKS_PER_DAY}}
    p1 = []
    rule(s1, m, cfg, [proj], p1, [])
    assert [p.rule for p in p1] == ["dig_jobs"] and "freed" not in m.dig_seen["7"], m.dig_seen
    s2 = {"date": {"year": 250, "tick": (cfg["dig_stall_days"] + 2) * TICKS_PER_DAY}}
    p2 = []
    rule(s2, m, cfg, [proj], p2, [])
    assert [p.rule for p in p2] == ["dig_jobs"], "held, so asked again"
    record([(p2[0], {"ok": True})], s2, m)
    assert m.dig_seen["7"].get("freed")
    p3 = []
    rule(s2, m, cfg, [proj], p3, [])
    assert p3 == []
    # refused: not marked
    m2 = Memory(dig_seen={"7": {"dug": 10, "tick": 0}})
    record([(p2[0], {"ok": False, "error": "x"})], s2, m2)
    assert "freed" not in m2.dig_seen["7"]


@test("r33 dig: a well's channel renewal is marked only once done")
def _():
    cfg = PLANNER_CONFIG
    m = Memory()
    proj = {"id": 9, "kind": "well", "phase": "dig", "dig_done": "open",
            "dig": {"dug": 0, "total": 1, "well_check": {"cause": "unworked"}}}
    rule = planner._dig_stall_rule
    rule({"date": {"year": 250, "tick": 0}}, m, cfg, [proj], [], [])
    s = {"date": {"year": 250, "tick": (cfg["well_renew_days"] + 1) * TICKS_PER_DAY}}
    got = []
    rule(s, m, cfg, [proj], got, None)
    w = [p for p in got if p.rule == "well_dig"]
    assert w and "renewed" not in m.dig_seen["9"]
    again = []
    rule(s, m, cfg, [proj], again, None)
    assert [p for p in again if p.rule == "well_dig"], "held: asked again"
    record([(w[0], {"ok": True})], s, m)
    assert m.dig_seen["9"].get("renewed")
    last = []
    rule(s, m, cfg, [proj], last, None)
    assert not [p for p in last if p.rule == "well_dig"]


# --- the guards --------------------------------------------------------------------------

@test("r33 guards: odd report values in plan()'s and note_cycle()'s old unguarded blocks become notes")
def _():
    base = real({"deference": 0})
    cases = {
        "mandates": lambda s: s.__setitem__("mandates", [None]),
        "threats": lambda s: s["others_on_map"].__setitem__("threats", [None]),
        "orders": lambda s: s.__setitem__("orders", [None] + list(s.get("orders") or [])),
        "drink": lambda s: s["stocks"].__setitem__("drink", "12"),
        "moods": lambda s: s["moods"].__setitem__("list", [None]),
        "tools": lambda s: s.__setitem__("tools", {"autochop": True, 5: None, "x": [1]}),
        "deep": lambda s: s.__setitem__("deep", {"caverns": [{"name": None, "open": True}, None]}),
    }
    for name, mut in cases.items():
        s = copy.deepcopy(base)
        mut(s)
        m = Memory()
        m.last_fired = {"build": None, "food": "x", "drink": 5}     # (Low) not ticks: dropped, not raised on
        notes = note_cycle(copy.deepcopy(s), m)
        assert "build" not in m.last_fired and "food" not in m.last_fired and "drink" in m.last_fired, name
        props, pnotes = plan(copy.deepcopy(s), m)
        allowed, _ = select(props, s, m)
        record([(p, {"ok": False, "error": "test"}) for p in allowed], s, m)
        assert all(isinstance(n, str) for n in notes + pnotes), name
    s = copy.deepcopy(base)
    s["others_on_map"]["threats"] = [None]
    notes = note_cycle(copy.deepcopy(s), Memory())
    assert any("bookkeeping" in n and "failed" in n for n in notes), notes
    _, pnotes = plan(copy.deepcopy(s), Memory())
    assert any("_threat_alert failed" in n for n in pnotes), pnotes


@test("r33 guards: on a sound report no guarded block fails (the fixtures)")
def _():
    for f in sorted((ROOT / "tests" / "fixtures" / "real").glob("*.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        m = Memory()
        notes = note_cycle(copy.deepcopy(s), m)
        _, pnotes = plan(copy.deepcopy(s), m)
        assert not failed(notes + pnotes) and not [n for n in notes if "bookkeeping" in n], (f.name, failed(pnotes))


# --- the waterworks through plan() (T1) ---------------------------------------------------

@test("r33 waterworks: through plan(), dwarves in deep water shut an open moat gate")
def _():
    s = real()
    s["waterworks"] = {"works": {"moat": {"kind": "moat", "stage": "done", "gate": "open"}}, "refused": {}}
    s["hazards"] = dict(s.get("hazards") or {}, wet=[{"id": 1}, {"id": 2}])
    props, notes = plan(copy.deepcopy(s), Memory())
    shut = [p for p in props if p.rule == "waterworks_shut"]
    assert shut and shut[0].action.get("shut") is True and shut[0].action.get("kind") == "moat", (props, failed(notes))
    s["hazards"]["wet"] = [{"id": 1}]
    props, _ = plan(copy.deepcopy(s), Memory())
    assert not [p for p in props if p.rule == "waterworks_shut"]


# --- Industriousness ---------------------------------------------------------------------

def idle_state(traits=None, idle_adults=10, adults=40, idle_free=None, in_squads=0, finished=20, done_total=None):
    s = real(traits)
    s["dwarves"].update(adults=adults, idle_adults=idle_adults, in_squads=in_squads)
    if idle_free is not None:
        s["dwarves"]["idle_free"] = idle_free
    s["projects"]["finished"] = finished
    if done_total is not None:
        s["projects"]["done_total"] = done_total
    return s


def polish(s, m=None):
    return [p for p in plan(copy.deepcopy(s), m or Memory())[0] if p.rule == "polish"]


@test("r33 polish: the gate reads done_total (it never saturates): new levels past the 20 kept are polished")
def _():
    m = Memory(polished_upto=20)
    assert not polish(idle_state(idle_adults=16, finished=20), m), "an older bridge: as before"
    assert polish(idle_state(idle_adults=16, finished=20, done_total=27), m), "27 finished ever: polish again"
    p = Proposal("polish", {"type": "polish"}, "x", 7)
    st = idle_state(finished=20, done_total=27)
    record([(p, {"ok": False, "error": "every finished level is polished"})], st, m)
    assert m.polished_upto == 27
    assert not polish(idle_state(idle_adults=16, finished=20, done_total=27), m)
    assert polish(idle_state(idle_adults=16, finished=20, done_total=28), m)
    assert levels_done({"projects": {"finished": 20}}) == 20 and levels_done({"projects": {"done_total": 3,
                                                                                            "finished": 2}}) == 3


@test("r33 polish: the idle share it needs is divided by the Industriousness factor")
def _():
    # 10 of 40 idle (25%): under the flat 30%, over 30% / factor(+60) (about 20%)
    assert not polish(idle_state({"industriousness": 0}, idle_adults=10))
    assert polish(idle_state({"industriousness": 60}, idle_adults=10))
    assert not polish(idle_state({"industriousness": -20}, idle_adults=13))     # 32.5% < 34.5%
    assert polish(idle_state({"industriousness": 0}, idle_adults=13))


@test("r33 idle: idle_free over the adults outside the squads when the bridge sends it, else as before")
def _():
    s = {"dwarves": {"adults": 76, "idle_adults": 5, "in_squads": 46}}
    assert abs(_idle_share(s) - 5 / 76) < 1e-9
    s["dwarves"]["idle_free"] = 4
    assert abs(_idle_share(s) - 4 / 30) < 1e-9
    s = {"dwarves": {"adults": 40, "idle_adults": 20, "in_squads": 0, "idle_free": 2}}
    assert abs(_idle_share(s) - 0.05) < 1e-9          # prayer and the tavern are not idleness
    # the polish rule follows it: 20 "idle", but only 2 truly idle
    assert not polish(idle_state(idle_adults=20, idle_free=2))
    assert polish(idle_state(idle_adults=20))


@test("r33 idle blocks: the blocks cap is scaled by Industriousness (a driven fort keeps cutting)")
def _():
    def blocks(traits, have):
        s = idle_state(traits, idle_adults=20, adults=40)
        s["dwarves"]["total"] = 200
        s["stocks"]["blocks"] = have
        s["stocks"]["boulders"] = 1000
        s["stone_use"] = {"usable": 1000}
        s["orders"] = [o for o in (s.get("orders") or []) if not (isinstance(o, dict)
                                                                   and o.get("recipe") == "stone_blocks")]
        return [p for p in plan(copy.deepcopy(s), Memory())[0] if p.rule == "idle"]
    cap = PLANNER_CONFIG["blocks_cap"]
    assert not blocks({"industriousness": 0}, cap + 10)
    assert blocks({"industriousness": 60}, cap + 10), "under 500 x 1.52"
    assert not blocks({"industriousness": 60}, int(cap * factor({"industriousness": 60}, "industriousness")) + 10)


# --- Spacing on every level ------------------------------------------------------------------

@test("r33 spacing: customs_pass gives every new level without one the fort's spacing; 0 changes nothing")
def _():
    from planner_building import customs_pass
    def props():
        return [Proposal("needs_shops", {"type": "start_project", "kind": "workshops"}, "x", 3),
                Proposal("mood", {"type": "start_project", "kind": "workshops", "style": {"smooth": 1}}, "x", 3),
                Proposal("build", {"type": "start_project", "kind": "bedrooms", "style": {"spacing": 10}}, "x", 3),
                Proposal("food", {"type": "work_order", "recipe": "x"}, "x", 3)]
    ps = props()
    shared = ps[1].action["style"]
    customs_pass(ps, Memory(), {"spacing": 60}, 50)
    assert ps[0].action["style"] == {"spacing": 60}, ps[0].action
    assert ps[1].action["style"] == {"smooth": 1, "spacing": 60} and shared == {"smooth": 1}, "a copy"
    assert ps[2].action["style"] == {"spacing": 10}, "its own kept"
    assert "style" not in ps[3].action
    ps = props()
    customs_pass(ps, Memory(), {"spacing": 0}, 50)
    assert "style" not in ps[0].action and ps[1].action["style"] == {"smooth": 1}
    ps = props()
    customs_pass(ps, Memory(), {"spacing": -60}, 50)
    assert ps[0].action["style"]["spacing"] == -60


@test("r33 spacing: through plan(), a non-build level carries the slider")
def _():
    s = real({"spacing": 60})
    live = planner._kitchen_rule

    def shops_rule(s_, memory, cfg, proposals):       # a level from a rule that never set a style
        proposals.append(Proposal("needs_shops", {"type": "start_project", "kind": "workshops",
                                                  "shops": ["Still"]}, "x", 3))
    try:
        planner._kitchen_rule = shops_rule
        props, _ = plan(copy.deepcopy(s), Memory())
    finally:
        planner._kitchen_rule = live
    lv = [p for p in props if p.action.get("type") == "start_project"]
    assert [p for p in lv if p.rule == "needs_shops"], [(p.rule, p.action) for p in lv]
    assert all(_d(p.action.get("style")).get("spacing") not in (None, 0) for p in lv), [(p.rule, p.action) for p in lv]


# --- Lows --------------------------------------------------------------------------------------

@test("r33 lows: the loop log keeps enough ticks for the 400 limits; the agenda names farms; ensure() keeps a plan")
def _():
    m = Memory()
    p = Proposal("alerts", {"type": "dismiss_alerts"}, "x", 5)
    st = {"date": {"year": 250, "tick": 0}}
    for i in range(450):
        st = {"date": {"year": 250, "tick": i * 10}}
        record([(p, {"ok": True})], st, m)
    assert len(m.action_log[planner.refusal_key(p)]) >= LOOP_LIMITS["dismiss_alerts"]
    assert _loop_count(m, p, 250 * planner.TICKS_PER_YEAR + 450 * 10) is not None, "the loop hold can fire"
    assert "farms" in AGENDA_THEMES and "farm" not in AGENDA_THEMES
    import masterplan
    m = Memory()
    m.atlas = {"plan": {"v": 1, "pattern": "old"}}
    real_draw, real_redraw = masterplan.draw, masterplan.needs_redraw
    try:
        masterplan.draw = lambda *a, **k: None
        masterplan.needs_redraw = lambda memory: True
        assert masterplan.ensure({}, m, {"x": 1}, {}, {}) == []
        assert m.atlas["plan"] == {"v": 1, "pattern": "old"}
    finally:
        masterplan.draw, masterplan.needs_redraw = real_draw, real_redraw


if __name__ == "__main__":
    finish()
