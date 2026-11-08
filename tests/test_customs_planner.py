"""Tests for the customs' planner wiring (0.105.29, group C): the level
action carries the fort's customs (style.customs for the builder's layout,
action["customs"] for the journal), and masterplan.hint is given the action
and the head count. The strategist's levels carry them too.

    python tests/test_customs_planner.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import customs  # noqa: E402
import masterplan  # noqa: E402
from planner import Memory, plan  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
WAR = {"militarism": 100}


def settled_fort(**traits) -> dict:
    """(as test_planner's) beds, dining, workshops, stockpiles, the social
    locations: only a barracks is missing for a martial fort."""
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["settings"]["traits"] = traits
    s["locations"] = {"count": {"HOSPITAL": 1, "INN_TAVERN": 1, "LIBRARY": 1}, "total": 3}
    s["buildings"]["zones"]["Barracks"] = 0
    return s


def levels(p) -> list:
    return [x.action for x in p if x.rule == "build" and x.action.get("type") == "start_project"
            and x.action.get("kind") != "garden"]


class Hint:
    """A stand-in for masterplan.hint (group A's real one adds the placement
    customs): records its keywords, returns a district, optionally customs."""

    def __init__(self, applied=None):
        self.calls, self.applied = [], applied

    def __call__(self, memory, kind, slot=None, traits=None, profile=None, action=None, citizens=None):
        self.calls.append({"kind": kind, "action": action, "citizens": citizens, "traits": traits})
        out = {"elev_lo": 100, "elev_hi": 110, "elev_target": 105, "district": "defence"}
        if self.applied:
            out["customs"] = list(self.applied)
        return out


def with_hint(h, fn):
    real = masterplan.hint
    masterplan.hint = h
    try:
        return fn()
    finally:
        masterplan.hint = real


@test("customs wiring: a War-hold barracks carries style.customs ['armoury'] and the journal's customs")
def _():
    s = settled_fort(**WAR)
    h = Hint()
    a = with_hint(h, lambda: levels(plan(s, Memory())[0]))
    b = [x for x in a if x["kind"] == "barracks"]
    assert b, a
    assert b[0]["style"]["customs"] == ["armoury"], b[0]["style"]
    assert b[0]["customs"] == ["armoury"], b[0]
    # hint got the action and the head count
    c = [x for x in h.calls if x["kind"] == "barracks"]
    assert c and c[0]["action"] is b[0] and c[0]["citizens"] == max(1, s["dwarves"]["total"]), c


@test("customs wiring: the hint's own customs join action['customs'] (sorted, no repeats), not style")
def _():
    s = settled_fort(**WAR)
    a = with_hint(Hint(applied=["gate_barracks", "armoury"]), lambda: levels(plan(s, Memory())[0]))
    b = [x for x in a if x["kind"] == "barracks"][0]
    assert b["customs"] == ["armoury", "gate_barracks"], b["customs"]
    assert b["style"]["customs"] == ["armoury"], b["style"]
    assert b["plan"]["district"] == "defence"


@test("customs wiring: a hint-only custom (no layout one) gives action['customs'] and no style.customs")
def _():
    s = settled_fort(militarism=80)          # a barracks, but no armoury (under 100)
    a = with_hint(Hint(applied=["wide_ways"]), lambda: levels(plan(s, Memory())[0]))
    b = [x for x in a if x["kind"] == "barracks"][0]
    assert b["customs"] == ["wide_ways"] and "customs" not in b["style"], b


@test("customs wiring: default sliders -> no customs keys anywhere (journal unchanged)")
def _():
    for traits in ({}, {"militarism": 80}):
        s = settled_fort(**traits)
        a = with_hint(Hint(), lambda: levels(plan(s, Memory())[0]))
        assert a, traits
        for x in a:
            assert "customs" not in x and "customs" not in (x.get("style") or {}), x
        # with the real hint too
        for x in levels(plan(s, Memory())[0]):
            assert "customs" not in x and "customs" not in (x.get("style") or {}), x


@test("customs wiring: the real masterplan.hint takes action= and citizens= (no TypeError dropping the level)")
def _():
    s = settled_fort(**WAR)
    b = [x for x in levels(plan(s, Memory())[0]) if x["kind"] == "barracks"]
    assert b and b[0]["style"]["customs"] == ["armoury"], b


@test("customs wiring: the strategist's levels carry the layout customs too; none at default sliders")
def _():
    from backends import Reply
    from review import maybe_review
    from tokens import TokenBank

    class Claude:
        def ask(self, instructions, message, important=False, effort=None):
            return Reply(text='{"note":"arm","actions":[{"type":"start_project","kind":"barracks","beds":10}]}',
                         input_tokens=3000, output_tokens=200, model="m")

    def run(traits):
        s = copy.deepcopy(BASE)
        s["settings"] = {"traits": traits, "ai_frequency": 100, "ai_effort": 100, "real_day_token_cap": 0}
        out = maybe_review(s, Memory(), TokenBank(), Claude(), {"recipes": [], "tools": [], "level_kinds": ["barracks"]}, [])
        return [p.action for p in out.proposals if p.action.get("type") == "start_project"]

    a = run(dict(WAR))
    assert a and a[0]["style"]["customs"] == ["armoury"] and a[0]["customs"] == ["armoury"], a
    a = run({})
    assert a and "customs" not in a[0] and "customs" not in a[0]["style"], a


@test("customs: the module copy is the spec's (War-hold ids, layout customs by kind)")
def _():
    assert customs.active(WAR) == ["gate_barracks", "armoury"]
    assert customs.layout_customs(WAR, "barracks") == ["armoury"] and customs.layout_customs(WAR, "temple") == []
    assert customs.active({}) == []


if __name__ == "__main__":
    finish()
