"""(F2a) One Switch for every on/off decision (brain/planner_switch.py).

Holds counted in game ticks held for nothing once a game day passed in about
one planner cycle; the gate lever was a toggle with no dwell. The Switch:
two thresholds, a minimum hold in real seconds (the cycle's wall clock) AND
planner cycles, set-state (act only when the game differs), an emergency
that flips at once. Moved onto it: the AI gate lever, the cistern's
floodgate, the werebeast cells (moon_cell) and the alarm (govern_alarm).

Each rule: an input flapping across its threshold every cycle flips at most
once a hold; the emergency still acts at once.

    python3 tests/test_f2a_switch.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, Proposal  # noqa: E402
from planner_core import TICKS_PER_DAY  # noqa: E402
import planner_switch as SW  # noqa: E402
import planner_military as PM  # noqa: E402
import planner_military_gatelever as GL  # noqa: E402
import planner_wells as PW  # noqa: E402
import planner_threats as PT  # noqa: E402
import planner_alarm as PA  # noqa: E402

CFG = dict(PLANNER_CONFIG)
HOLD_S, HOLD_N = CFG["switch_hold_seconds"], CFG["switch_hold_cycles"]
CYCLE_S = 20                      # a planner cycle ~20 s real, a game day a cycle (the fast forts)
T0 = 50_000


def date(i: int) -> dict:
    return {"year": 260, "tick": T0 + i * TICKS_PER_DAY}


def spaced(flips: list) -> bool:
    """Two flips at least a hold apart (real seconds and cycles)."""
    return all(b - a >= max(HOLD_N, -(-HOLD_S // CYCLE_S)) for a, b in zip(flips, flips[1:]))


def went(s, m, props):
    """The cycle's record(): every proposal went (the Switch's flips booked)."""
    for p in props:
        SW.note_switch(p, {"ok": True}, s, m)


# --- the Switch itself ---------------------------------------------------------------
def look(m, sw, i, w, value, observed, **kw):
    """One cycle: note_cycle, the rule's decide, record() when it acted."""
    s = {"date": date(i), "wall_time": w}
    SW.note_switches(s, m)
    got = sw.decide(value, s, observed=observed, **kw)
    if sw.act(observed):
        sw.expect("r", {"type": "x"})
        went(s, m, [Proposal("r", {"type": "x"}, "", 0)])
    return got


@test("Switch: hysteresis between the thresholds, the hold in real seconds AND cycles, set-state")
def _():
    m = Memory()
    sw = SW.Switch(m, "x", 3, on_at=6, off_at=2, hold_s=100, hold_cycles=3)
    assert look(m, sw, 0, 0, 7, False) is True and m.switches["x:3"]["on"] is True      # flipped, booked
    assert look(m, sw, 1, 10, 4, True) is True and not sw.act(True)                     # the band
    assert look(m, sw, 2, 20, 1, True) is True and sw.held and sw.wait_s == 80 and sw.wait_cycles == 1
    assert look(m, sw, 3, 210, 1, True) is False and sw.act(True)                       # 3 cycles, 210 s
    assert m.switches["x:3"]["on"] is False
    # a slow clock: the cycles alone don't flip it back
    for i in range(4, 14):
        assert look(m, sw, i, 210 + i, 7, False) is False and sw.held
    assert look(m, sw, 14, 400, 7, False) is True


@test("Switch: plan only reads; a flip not sent isn't booked; asking again isn't held; an emergency at once")
def _():
    m = Memory()
    sw = SW.Switch(m, "z", hold_s=100, hold_cycles=3)
    SW.note_switches({}, m)
    before = dict(m.switches)
    assert sw.decide(True, {"wall_time": 0}, observed=False) is True and sw.act(False)
    assert m.switches == before                                      # nothing written by decide
    look(m, sw, 1, 1, True, False)                                   # sent: booked on
    assert look(m, sw, 2, 2, True, False) is True                    # the pull on its way: asked again
    assert look(m, sw, 3, 3, False, True) is True and sw.held        # the flip back: held
    assert look(m, sw, 4, 4, False, True, emergency=False) is False  # the emergency: at once
    assert m.switches["z"]["by"] == "emergency"


@test("Switch: no memory (or an old save without the field): no hold, the input as before")
def _():
    sw = SW.Switch(None, "n")
    assert sw.decide(True, {}, observed=False) is True and sw.act(False)
    assert sw.decide(False, {}, observed=True) is False
    assert sw.decide(None, {}, observed=False) is False
    m = Memory.from_dict({"repeat_book": {}})                       # an older save: no "switches"
    assert m.switches == {}
    assert "switches" in Memory().to_dict()


# --- the AI gate lever -----------------------------------------------------------------
def gate_cycle(m, i, reach, near=None):
    s = {"date": date(i), "wall_time": i * CYCLE_S, "others_on_map": {"threats": []}}
    if near is not None:
        s["others_on_map"]["threats"] = [{"id": 9, "can_reach_dwarves": True, "distance_to_nearest_dwarf": near}]
    mil = {"gates": [{"id": 77, "linked": True, "shut": m.gate_closed_by_ai}]}
    props = []
    SW.note_switches(s, m)
    GL.ai_gate_lever(s, m, CFG, {"gate_lever": True}, mil, reach, False, False, props)
    pulls = [p for p in props if p.action.get("type") == "pull_gate"]
    went(s, m, pulls)
    for _ in pulls:                       # the dwarf pulls it: the lever read back next cycle
        m.gate_closed_by_ai = not m.gate_closed_by_ai
    return pulls


def _patched(fn):
    def run():
        keep = PM.all_clear, PM.quick_clear, PM.watched_gate_levers
        PM.all_clear, PM.quick_clear, PM.watched_gate_levers = (lambda *a: (True, "")), (lambda *a: ""), \
            (lambda *a: set())
        try:
            fn()
        finally:
            PM.all_clear, PM.quick_clear, PM.watched_gate_levers = keep
    return run


@test("gate lever: a threat in reach every other cycle pulls it at most once a hold (was: every cycle)")
@_patched
def _():
    m = Memory()
    flips = [i for i in range(40) if gate_cycle(m, i, reach=i % 2 == 0)]
    assert flips[0] == 0 and len(flips) >= 3, flips
    assert spaced(flips), flips
    # the clear cases as before: shut on a threat, opened once quiet (a hold later)
    m = Memory()
    assert gate_cycle(m, 0, True) and m.gate_closed_by_ai
    i = max(HOLD_N, HOLD_S // CYCLE_S)
    for j in range(1, i):
        assert not gate_cycle(m, j, False)                 # the hold (the rule looks every cycle)
    assert gate_cycle(m, i, False) and not m.gate_closed_by_ai


@test("gate lever: an enemy within switch_emergency_tiles shuts it at once, inside the hold")
@_patched
def _():
    m = Memory()
    m.gate_closed_by_ai = True
    assert gate_cycle(m, 0, False)                          # opened (quiet)
    assert not m.gate_closed_by_ai
    assert not gate_cycle(m, 1, True, near=40)              # in reach, far off: the hold
    p = gate_cycle(m, 2, True, near=CFG["switch_emergency_tiles"])
    assert p and "pull the AI gate lever" in p[0].reason and m.gate_closed_by_ai


# --- the cistern's floodgate -----------------------------------------------------------
def cistern_cycle(m, i, gate, depth):
    s = {"date": date(i), "wall_time": i * CYCLE_S,
         "water": {"cistern_status": {"stage": "done", "gate": gate, "depth": depth, "v": 2, "sealed_now": True}}}
    props, notes = [], []
    SW.note_switches(s, m)
    PW._cistern_rule(s, m, CFG, props, notes, {})
    went(s, m, props)
    return [p for p in props if p.rule == "cistern"], notes


@test("cistern: a depth read flapping 7/1 every cycle flips the floodgate at most once a hold (was: every cycle)")
def _():
    m, gate, flips, said = Memory(), "open", [], []
    for i in range(40):
        ps, notes = cistern_cycle(m, i, gate, 7 if i % 2 == 0 else 1)
        if ps:
            flips.append(i)
            gate = "shut" if gate == "open" else "open"
        said += [n for n in notes if "once the hold is over" in n]
    assert flips[0] == 0 and len(flips) >= 3, flips
    assert spaced(flips), flips
    assert said, "the hold is said"


@test("cistern: the clear case unchanged: full shut, then low opened once the hold is past")
def _():
    m = Memory()
    ps, _ = cistern_cycle(m, 0, "open", 7)
    assert ps and "shut the floodgate" in ps[0].reason
    for i in range(1, 30):                                   # filling: the cycles counted (note_cycle)
        SW.note_switches({}, m)
    ps, _ = cistern_cycle(m, 30, "shut", 2)
    assert ps and "refill" in ps[0].reason


# --- the werebeast cells (moon_cell) ---------------------------------------------------
CH = [{"phase": 27, "tick": 110290156}]


def moon_cycle(m, i, phase, inside):
    from test_threats import fort
    rows = [{"id": 1, "name": "Litast", "by_syndrome": True, "cell": inside, "locked": inside}]
    s = fort({"were": {"list": rows, "changes": CH, "moon_phase": phase,
                       "cells": [{"unit_id": 1, "locked": True}] if inside else []}})
    s["date"] = dict(s["date"], tick=T0 + i * TICKS_PER_DAY)
    s["wall_time"] = i * CYCLE_S
    props, notes = [], []
    SW.note_switches(s, m)
    PT._were(s, CFG, s["threats"], {"moon_cells": True}, props, notes, m)
    went(s, m, props)
    mc = [p for p in props if p.rule == "moon_cell" and not p.action.get("reserve")]
    return mc, notes


@test("moon_cell: the moon phase flapping near/past every cycle: locked at once each time, let out once a hold")
def _():
    # the phases used: 26 is "near" (the lead), 5 "clearly past"
    assert moon_cycle(Memory(), 0, 26, False)[0][0].action.get("move_in")
    assert moon_cycle(Memory(), 0, 5, True)[0][0].action.get("release")
    m, inside, releases, locks = Memory(), True, [], []
    for i in range(40):
        near = i % 2 == 0
        ps, _ = moon_cycle(m, i, 26 if near else 5, inside)
        for p in ps:
            if p.action.get("release"):
                releases.append(i)
                inside = False
            else:
                locks.append(i)
                inside = True
    assert releases and spaced(releases), releases
    # every near cycle with them outside locked them in at once (the emergency)
    assert all(i % 2 == 0 for i in locks) and len(locks) == len(releases), (locks, releases)


@test("moon_cell: held release is said; no memory (old callers): let out as before")
def _():
    m = Memory()
    moon_cycle(m, 0, 26, False)                              # locked (the emergency)
    ps, notes = moon_cycle(m, 1, 5, True)
    assert not ps and any("hold since they were locked in" in n for n in notes), notes
    ps, _ = moon_cycle(None, 1, 5, True)
    assert ps and ps[0].action.get("release")


# --- the alarm -------------------------------------------------------------------------
ON = {"type": "civ_alert", "on": True}
OFF = {"type": "civ_alert", "on": False}
FIRE = "fire 9 tiles from the dwarves: sound the alarm"
REACH = "3 threat(s) can reach the dwarves"


def alarm_cycle(m, i, alert_on, action, why="x"):
    s = {"date": date(i), "wall_time": i * CYCLE_S, "civ_alert": alert_on}
    props = [Proposal("threat_alert", dict(action), why, 0)] if action else []
    notes = []
    SW.note_switches(s, m)
    PA.govern_alarm(s, m, CFG, props, notes)
    went(s, m, props)
    return [p for p in props if p.action in (ON, OFF)], notes


@test("alarm: a cause flapping every cycle (raise, lower) goes up or down at most once a hold")
def _():
    m, alert, flips = Memory(), False, []
    m.ai_alert_raised = True
    for i in range(40):
        act = OFF if alert else ON
        if i % 2:                                   # the cause gone every other cycle: no raise asked
            act = OFF if alert else None
        ps, _ = alarm_cycle(m, i, alert, act, FIRE if act == ON else "no fire near the dwarves now")
        if ps:
            flips.append(i)
            alert = ps[0].action["on"]
    assert flips[0] == 0 and len(flips) >= 3, flips
    assert spaced(flips), flips


@test("alarm: enemies in reach raise it at once inside the hold; the hold is said")
def _():
    m = Memory()
    m.ai_alert_raised = True
    assert alarm_cycle(m, 0, False, ON, FIRE)[0]
    ps, _ = alarm_cycle(m, 1, True, OFF, "no fire near the dwarves now")
    assert not ps                                            # lowered no sooner than a hold after the raise
    m = Memory()
    m.ai_alert_raised = True
    alarm_cycle(m, 0, True, OFF, "quiet")                    # lowered
    ps, notes = alarm_cycle(m, 1, False, ON, FIRE)
    assert not ps and any("a while yet" in n for n in notes), notes
    ps, _ = alarm_cycle(m, 2, False, ON, REACH)
    assert ps and ps[0].action == ON


if __name__ == "__main__":
    finish()
