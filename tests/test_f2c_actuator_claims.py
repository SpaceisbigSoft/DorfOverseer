"""F2c: actuator claims (brain/actuator_claims.py, planner_select.select()).

- two rules fighting over a lever across cycles: one owner, no alternation;
  the owner's own pull back lets it go;
- a rule of a higher tier takes the claim over; one of the same tier and a
  higher priority number does not;
- the claim expires after claim_expiry_cycles cycles, or claim_expiry_seconds
  of real time;
- within one cycle the higher tier wins even when it sorts later;
- the alarm: the owner's off step releases it;
- squads are not held across cycles by default (the per-cycle rule only);
- old saves (no claims field) load; claims survive to_dict/from_dict.

    python tests/test_f2c_actuator_claims.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from planner import Memory, PLANNER_CONFIG, select  # noqa: E402
from planner_core import Proposal  # noqa: E402
import actuator_claims  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def pull(rule, pri=2, lever=7):
    return Proposal(rule, {"type": "pull_gate", "lever_id": lever}, f"{rule} pulls", pri)


def rules(props):
    return [p.rule for p in props]


@test("two rules fighting over a lever across cycles: one owner, the other waits every cycle (no alternation)")
def _():
    s, m = fort(), Memory()
    went = []
    for c in range(6):
        # the two take turns being first in the list, as rules' order changes
        props = [pull("gate"), pull("gates")] if c % 2 == 0 else [pull("gates"), pull("gate")]
        if c > 0:
            props = [p for p in props if p.rule == "gates"]     # the owner has pulled; the other keeps trying
        allowed, held = select(props, s, m)
        went += rules(allowed)
        if c > 0:
            assert any(h.startswith("gates: lever 7 is gate's") for h in held), held
    assert went == ["gate"], went
    assert m.claims["own"]["lever:7"]["rule"] == "gate", m.claims
    # the owner pulls it back: let go; the other gets it the next cycle
    allowed, _ = select([pull("gate")], s, m)
    assert rules(allowed) == ["gate"] and "lever:7" not in m.claims["own"], m.claims
    allowed, _ = select([pull("gates")], s, m)
    assert rules(allowed) == ["gates"] and m.claims["own"]["lever:7"]["rule"] == "gates", m.claims


@test("the same cycle: two rules on one lever, one goes (the first of equal rank)")
def _():
    allowed, held = select([pull("gate"), pull("gates")], fort(), Memory())
    assert rules(allowed) == ["gate"], rules(allowed)
    assert any(h.startswith("gates: lever 7 is used by gate this cycle") for h in held), held


@test("a higher tier takes the claim over; the same tier at a lower priority does not")
def _():
    s, m = fort(), Memory()
    select([pull("gate", 0)], s, m)                       # defence, priority 0
    allowed, held = select([pull("gates", 1)], s, m)      # defence, priority 1: waits
    assert not allowed and any("is gate's" in h for h in held), held
    allowed, _ = select([pull("stranded", 5)], s, m)      # survival: takes it
    assert rules(allowed) == ["stranded"] and m.claims["own"]["lever:7"]["rule"] == "stranded", m.claims
    allowed, held = select([pull("gate", 0)], s, m)       # the old owner waits now
    assert not allowed and any("is stranded's" in h for h in held), held
    # the same tier and a strictly higher priority (a lower number) takes it too
    m2 = Memory()
    select([pull("gates", 3)], s, m2)
    allowed, _ = select([pull("gate", 1)], s, m2)
    assert rules(allowed) == ["gate"] and m2.claims["own"]["lever:7"]["rule"] == "gate", m2.claims


@test("within one cycle the higher tier wins even when it sorts later by priority")
def _():
    allowed, held = select([pull("gate", 0), pull("stranded", 4)], fort(), Memory())
    assert rules(allowed) == ["stranded"], rules(allowed)
    assert any(h.startswith("gate: lever 7 goes to stranded this cycle") for h in held), held


@test("expiry: the claim frees after claim_expiry_cycles cycles, or claim_expiry_seconds of real time")
def _():
    s = fort()
    cfg = dict(PLANNER_CONFIG, claim_expiry_cycles=3, claim_expiry_seconds=10_000)
    m = Memory()
    select([pull("gate")], s, m, cfg)                     # cycle 1: gate owns it
    outs = [rules(select([pull("gates")], s, m, cfg)[0]) for _ in range(3)]   # cycles 2, 3, 4
    assert outs == [[], [], ["gates"]], outs
    # real time: the clock jumps past claim_expiry_seconds
    clock = [1000.0]
    old = actuator_claims._clock
    actuator_claims._clock = lambda: clock[0]
    try:
        cfg = dict(PLANNER_CONFIG, claim_expiry_cycles=100, claim_expiry_seconds=60)
        m = Memory()
        select([pull("gate")], s, m, cfg)
        clock[0] += 30
        assert not select([pull("gates")], s, m, cfg)[0]
        clock[0] += 31
        assert rules(select([pull("gates")], s, m, cfg)[0]) == ["gates"]
    finally:
        actuator_claims._clock = old


@test("the alarm: another rule's off waits while the owner holds it; the owner's off releases it")
def _():
    s, m = fort(), Memory()
    on = Proposal("threat_alert", {"type": "civ_alert", "on": True}, "up", 0)
    off_other = Proposal("strangers", {"type": "civ_alert", "on": False}, "down", 3)
    assert rules(select([on], s, m)[0]) == ["threat_alert"]
    assert m.claims["own"]["alarm:alarm"]["rule"] == "threat_alert"
    allowed, held = select([off_other], s, m)
    assert not allowed and any("the alarm is threat_alert's" in h for h in held), held
    allowed, _ = select([Proposal("threat_alert", {"type": "civ_alert", "on": False}, "down", 0)], s, m)
    assert rules(allowed) == ["threat_alert"] and "alarm:alarm" not in m.claims["own"], m.claims


@test("gates: the close claims, another rule's open waits unless it outranks (and then releases)")
def _():
    s, m = fort(), Memory()
    select([Proposal("gates", {"type": "close_threatened_gates"}, "shut", 0)], s, m)
    assert m.claims["own"]["gate:gates"]["rule"] == "gates"
    assert not select([Proposal("killzone", {"type": "open_gates"}, "open", 0)], s, m)[0]
    allowed, _ = select([Proposal("stranded", {"type": "open_gates"}, "let in", 0)], s, m)
    assert rules(allowed) == ["stranded"] and "gate:gates" not in m.claims["own"], m.claims


@test("squads: not held across cycles by default (the per-cycle rule only); held when listed")
def _():
    s, m = fort(), Memory()
    k = lambda rule, pri: Proposal(rule, {"type": "squad_orders", "squad_id": 11, "kill": [900]}, "x", pri)  # noqa: E731
    select([k("squad_attack", 0)], s, m)
    assert not any(key.startswith("squad:") for key in m.claims["own"])
    assert rules(select([k("killer", 3)], s, m)[0]) == ["killer"]
    cfg = dict(PLANNER_CONFIG, claim_persist_kinds=["squad", "lever"])
    m = Memory()
    select([k("squad_attack", 0)], s, m, cfg)
    allowed, held = select([k("killer", 3)], s, m, cfg)
    assert not allowed and any("squad 11 is squad_attack's" in h for h in held), held
    # the owner's recall (clear) lets it go
    select([Proposal("squad_attack", {"type": "squad_orders", "squad_id": 11, "clear": True}, "back", 0)], s, m, cfg)
    assert "squad:11" not in m.claims["own"], m.claims


@test("the table: every kind of key read off its action; nothing for other actions")
def _():
    ak = actuator_claims.actuator_keys
    assert ak({"type": "pull_gate", "lever_id": 3}) == [("lever", 3)]
    assert ak({"type": "hunt_send", "squad_ids": [1, 2]}) == [("squad", 1), ("squad", 2)]
    assert ak({"type": "lure_open", "opening": "x1y2"}) == [("gate", "lure:x1y2")]
    assert ak({"type": "cavern_way", "step": "build"}) == []
    assert ak({"type": "cavern_way", "step": "open"}) == [("gate", "cavern_way")]
    assert ak({"type": "hospital_burrow", "max": 5}) == [("burrow", "hospital")]
    assert ak({"type": "work_order", "recipe": "beds"}) == [] and ak(None) == []
    assert actuator_claims.ordered_squads({"type": "guard_gate", "squads": [4, None, True]}) == [4]


@test("old saves: no claims field loads as empty; claims survive to_dict/from_dict")
def _():
    m = Memory.from_dict({"quiet_cycles": 3})
    assert m.claims == {}
    select([pull("gate")], fort(), m)
    m2 = Memory.from_dict(json.loads(json.dumps(m.to_dict())))
    assert m2.claims["own"]["lever:7"]["rule"] == "gate"
    assert not select([pull("gates")], fort(), m2)[0]
    # a broken field is no claim, never a crash
    m3 = Memory()
    m3.claims = {"n": "x", "own": {"lever:7": "junk"}}
    assert rules(select([pull("gates")], fort(), m3)[0]) == ["gates"]



@test("danger within 12 tiles: a gate close or alarm raise skips an earlier cycle's claim (merge 0.105.135)")
def _():
    s, m = fort(), Memory()
    first = Proposal("siege_watch", {"type": "close_threatened_gates"}, "shut", 0)
    closer = Proposal("gates", {"type": "close_threatened_gates"}, "shut", 3)
    assert rules(select([first], s, m)[0]) == ["siege_watch"]
    assert not select([closer], s, m)[0]                     # far danger: the claim holds
    near = copy.deepcopy(s)
    near.setdefault("others_on_map", {})["threats"] = [
        {"can_reach_dwarves": True, "distance_to_nearest_dwarf": 8}]
    assert rules(select([closer], near, m)[0]) == ["gates"]  # near: the close goes
    off = Proposal("strangers", {"type": "civ_alert", "on": False}, "down", 3)
    m2 = Memory()
    select([Proposal("threat_alert", {"type": "civ_alert", "on": True}, "up", 0)], near, m2)
    assert not select([off], near, m2)[0]                    # an off is no safety step


finish()
