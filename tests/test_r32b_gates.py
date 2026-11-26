"""(R32 b) B's Giantess (26 Nov 08:33-08:39): 13 dead in 4 minutes.

  * "watch the 1 gate(s)" while the fort had 2 entrances: the gates line now
    counts every entrance and names the ones that can't shut, with why (and
    a threat with no entrance able to shut is said too);
  * the gatehouse's hatch had no lever ("levers": []) and nothing placed one
    in a fort of low Engineering: every fort gets a lever for a lever-less
    hatch, and for a drawbridge no lever inside works (mechanisms ordered
    when short); place_gate_lever takes an entrance whose only gate is such
    a drawbridge;
  * "the fort has been shut for days with no new enemy: open the gates"
    while she was killing: the lockdown cap never lifts for a building
    destroyer, flier, great beast or an enemy among the dwarves, a lifted one
    is taken back when one is, and the open says what is left.

    python tests/test_r32b_gates.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402

from planner import PLANNER_CONFIG, Memory, note_cycle, plan, TICKS_PER_DAY  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def entrances(*es, armed=False, age_days=1):
    s = fort()
    now = s["date"]["year"] * 403200 + s["date"]["tick"]
    s["entrances"] = {"scanned": True, "scanned_tick": now - age_days * 1200, "armed": armed,
                      "entrances": [dict({"id": i + 1, "kind": "surface", "x": 10, "y": 10 + i, "z": 173,
                                          "width": 1, "sealed": False, "equipment": [], "door_spots": 0}, **e)
                                    for i, e in enumerate(es)]}
    return s


def by_rule(props, rule):
    return [x for x in props if x.rule == rule]


def threat(i=7527, name="Trustdaub, Human Maceman", dist=18, **kw):
    return dict({"id": i, "name": name, "invader": True, "can_reach_dwarves": True, "great_danger": False,
                 "flier": False, "distance_to_nearest_dwarf": dist, "levels_from_nearest_dwarf": 4,
                 "layer": "fort_levels", "pos": {"x": 40, "y": 40, "z": 170}}, **kw)


def shut_fort(*threats, fps=3):
    """A fort the watcher holds shut, the given enemies inside it."""
    s = entrances({"sealed": True, "equipment": [{"id": 1, "kind": "hatch"}], "closed": True}, armed=True)
    s["entrances"]["citizens_outside"] = 0
    s["entrances"]["intruders_inside"] = [t["id"] for t in threats]
    s["others_on_map"]["threats"] = list(threats)
    s["others_on_map"]["threats_that_can_reach_dwarves"] = len(threats)
    s["civ_alert"] = True
    if fps:
        s["fps_low"] = fps
    return s


CFG = dict(PLANNER_CONFIG, lone_intruder_max=0)      # the cap alone (as test_planner's cap test)


def two_days_on(s, m, cfg=CFG):
    note_cycle(s, m, cfg)
    later = copy.deepcopy(s)
    later["date"]["tick"] += PLANNER_CONFIG["lockdown_max_days"] * TICKS_PER_DAY
    return later, note_cycle(later, m, cfg)


@test("R32 b: the cap never lifts the lockdown for a building destroyer, flier or big beast inside")
def _():
    for change in ({"destroyer": True}, {"flier": True}, {"kinds": ["SemiMegabeast"]}):
        s = shut_fort(threat(i=77, name="Giantess", **change))
        m = Memory(ai_alert_raised=True)
        later, notes = two_days_on(s, m)
        assert not m.atlas["lockdown"].get("released"), (change, m.atlas["lockdown"])
        p, _ = plan(later, m, CFG)
        assert not [x for x in by_rule(p, "gates") if x.action == {"type": "open_gates"}], change
        assert not any(x.action == {"type": "civ_alert", "on": False} for x in p), change


@test("R32 b: the cap never lifts it for an ordinary enemy among the dwarves (killing)")
def _():
    s = shut_fort(threat(dist=2))
    s["others_on_map"]["threats"][0]["levels_from_nearest_dwarf"] = 0
    m = Memory(ai_alert_raised=True)
    later, _ = two_days_on(s, m)
    assert not m.atlas["lockdown"].get("released"), m.atlas["lockdown"]
    # far off, as before: lifted, and the open says what is left (never "no new enemy" alone)
    s = shut_fort(threat())
    m = Memory(ai_alert_raised=True)
    later, notes = two_days_on(s, m)
    assert m.atlas["lockdown"].get("released") and "FPS" in m.atlas["lockdown"].get("released_why", ""), \
        m.atlas["lockdown"]
    g = by_rule(plan(later, m, CFG)[0], "gates")
    assert g and g[0].action == {"type": "open_gates"}, [x.action for x in g]
    assert "no new enemy" not in g[0].reason and "1 ordinary enemy" in g[0].reason and "inside" in g[0].reason, \
        g[0].reason


@test("R32 b: a lifted lockdown is taken back when the enemy comes among the dwarves or is a destroyer")
def _():
    s = shut_fort(threat())
    m = Memory(ai_alert_raised=True)
    later, _ = two_days_on(s, m)
    assert m.atlas["lockdown"].get("released")
    near = copy.deepcopy(later)
    near["others_on_map"]["threats"][0].update(distance_to_nearest_dwarf=1, levels_from_nearest_dwarf=0)
    notes = note_cycle(near, m, CFG)
    assert "released" not in m.atlas["lockdown"], m.atlas["lockdown"]
    assert any("taken back" in n and "among the dwarves" in n for n in notes), notes
    p, _ = plan(near, m, CFG)
    assert not [x for x in by_rule(p, "gates") if x.action == {"type": "open_gates"}], [x.reason for x in p]
    # it walks off again: not lifted again at once (the cap's days count afresh)
    off = copy.deepcopy(later)
    off["date"]["tick"] += 50
    note_cycle(off, m, CFG)
    assert "released" not in m.atlas["lockdown"], m.atlas["lockdown"]


@test("R32 b: with a stale lift on record, the gates rule doesn't open for a destroyer (no note_cycle)")
def _():
    s = shut_fort(threat(i=77, name="Giantess", destroyer=True, dist=3))
    m = Memory(ai_alert_raised=True)
    m.atlas = {"lockdown": {"released": 1, "new": 0, "seen": [77]}}
    p, _ = plan(s, m, CFG)
    bad = [x for x in by_rule(p, "gates") if x.action == {"type": "open_gates"}]
    assert not bad, [x.reason for x in bad]


@test("R32 b: arming counts every entrance and names the one that can't shut, with why")
def _():
    s = entrances({"x": 108, "y": 149, "z": 170, "sealed": True, "lid": True, "gatehouse": "standing",
                   "equipment": [{"id": 45, "kind": "hatch", "lever_away": False, "levers": []}],
                   "outer": [{"id": 222, "kind": "bridge", "lever_id": 300}]},
                  {"x": 126, "y": 128, "z": 165, "width": 3})
    s["others_on_map"]["threats"] = [threat(i=77, name="Giantess", dist=60, layer="upper_levels")]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    g = by_rule(plan(s, Memory())[0], "gates")
    assert g and g[0].action == {"type": "arm_gates"}, [x.action for x in g]
    r = g[0].reason
    assert "1 gate(s) of the 2 entrance(s)" in r and "1 can't shut" in r and "x126 y128" in r, r
    assert "x108 y149" not in r.split("can't shut")[1], r
    # a building destroyer on the map: the gatehouse's drawbridge holds; a hatch alone doesn't
    s["others_on_map"]["threats"][0]["destroyer"] = True
    g = by_rule(plan(copy.deepcopy(s), Memory())[0], "gates")
    assert "1 can't shut" in g[0].reason, g[0].reason
    s["entrances"]["entrances"][0]["outer"] = []
    g = by_rule(plan(s, Memory())[0], "gates")
    r = g[0].reason
    assert "2 can't shut" in r and "building destroyer" in r, r


@test("R32 b: a threat and no entrance able to shut: said, each with why")
def _():
    s = entrances({"x": 126, "y": 128, "z": 165, "width": 3, "bridges_unworked": [222]})
    s["others_on_map"]["threats"] = [threat()]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    _, notes = plan(s, Memory())[:2]
    n = [x for x in notes if "none of the 1 entrance(s) can shut" in x]
    assert n and "x126 y128" in n[0] and "drawbridge" in n[0], notes


@test("R32 b: a drawbridge no lever inside works gets a lever of its own in any fort, then linked")
def _():
    s = entrances({"x": 126, "y": 128, "z": 165, "width": 3, "bridges_unworked": [222]})
    s["settings"]["traits"] = {"engineering": 0, "fortification": 0}
    s["entrances"]["free_mechanisms"] = 5
    g = by_rule(plan(copy.deepcopy(s), Memory())[0], "gate_lever")
    assert g and g[0].action == {"type": "place_gate_lever", "entrance_id": 1}, [x.action for x in g]
    assert "drawbridge" in g[0].reason, g[0].reason
    s["entrances"]["free_mechanisms"] = 1                            # short: mechanisms made first
    p = plan(copy.deepcopy(s), Memory())[0]
    assert not by_rule(p, "gate_lever"), [x.action for x in by_rule(p, "gate_lever")]
    mech = [x for x in by_rule(p, "mechanisms") if "gate lever" in x.reason]
    assert mech and mech[0].action["amount"] == 2 and mech[0].is_order, [x.action for x in by_rule(p, "mechanisms")]
    s["entrances"]["free_mechanisms"] = 5
    s["entrances"]["free_levers"] = [{"id": 90, "x": 126, "y": 100, "z": 160}]
    g = by_rule(plan(copy.deepcopy(s), Memory())[0], "gate_lever")
    assert g and g[0].action == {"type": "link_lever", "lever_id": 90, "target_id": 222}, [x.action for x in g]


@test("R32 b: B's gatehouse hatch with no lever gets one in a fort of low Engineering (no threat)")
def _():
    s = entrances({"x": 108, "y": 149, "z": 170, "sealed": True, "lid": True, "gatehouse": "standing",
                   "equipment": [{"id": 45, "kind": "hatch", "lever_away": False, "levers": []}],
                   "outer": [{"id": 222, "kind": "bridge", "lever_id": 300}]})
    s["settings"]["traits"] = {"engineering": 0, "fortification": 0}
    g = by_rule(plan(copy.deepcopy(s), Memory())[0], "gate_lever")
    assert g and g[0].action == {"type": "place_gate_lever", "entrance_id": 1}, [x.action for x in g]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1        # a threat: the hatch's link waits
    s["others_on_map"]["threats"] = [threat()]
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "gate_lever")


@test("R32 b: place_gate_lever (Lua) takes an entrance whose only gate is an unworked drawbridge")
def _():
    src = (ROOT / "lua" / "ai-gates-works.lua").read_text(encoding="utf-8")
    i = src.index("function place_gate_lever")
    body = src[i:src.index("\nend", i)]
    assert "#(e.bridges_unworked or {}) == 0" in body, body[:600]


if __name__ == "__main__":
    finish()
