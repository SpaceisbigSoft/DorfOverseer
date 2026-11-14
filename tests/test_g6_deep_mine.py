"""Group 6: the Deep mine goes up, and shrinks (fort E, y253-267).

The scorecard's Verticality and Surface lines now take each level's own
surface (the bridge's ground_z, else the nearest surface way in), and the
Deep mine's levels from every rule go to their district of the deep plan.

    python tests/test_g6_deep_mine.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import scorecard  # noqa: E402
from planner import Memory, _deep_surface_filter, _deep_plan_hint  # noqa: E402
from planner_core import Proposal  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))

# fort E (267-winter): the main way in on a plateau (ground z161), the
# founding stair from the hilltop (hatch at z170), a third way in at z168
E_STATE = {"crossings": {"z": 161, "entrance": {"x": 117, "y": 110}},
           "entrances": {"entrances": [{"kind": "surface", "x": 117, "y": 110, "z": 160},
                                       {"kind": "surface", "x": 108, "y": 149, "z": 170},
                                       {"kind": "surface", "x": 90, "y": 158, "z": 168}]}}


def level(z, x=None, y=None, ground=None):
    return {"z": z, "x": x, "y": y, "ground": ground, "kind": "bedrooms", "tiles": 40}


def journal(levels):
    return {"levels": levels, "ok": {}, "petitions_yes": 0, "petitions_no": 0, "trade_value": 0}


@test("scorecard (group 6): a level's surface is the bridge's ground over it, else the nearest way in, else the main way in's ground")
def _():
    s = copy.deepcopy(E_STATE)
    assert scorecard.level_surface(level(160, 108, 139, ground=171), s) == 171      # the bridge's reading
    assert scorecard.level_surface(level(160, 108, 139), s) == 170                   # by the hilltop stair
    assert scorecard.level_surface(level(166, 92, 160), s) == 168                    # by the west way in
    assert scorecard.level_surface(level(161, 115, 115), s) == 161                   # the main way in: its ground
    assert scorecard.level_surface(level(160), s) == 161                             # no place: as before
    assert scorecard.level_surface(level(160), {}) is None


@test("scorecard (group 6): fort E's levels under the mountain are not 'at or above the surface'; its depth from the ground over it")
def _():
    s = copy.deepcopy(BASE)
    s.update(copy.deepcopy(E_STATE))
    # E's shape: the deepest (z153) and the highest (z169) by the hilltop stair,
    # two by the plateau way in at its ground
    levels = [level(153, 108, 149), level(169, 122, 149), level(166, 108, 139), level(161, 108, 121),
              level(162, 108, 122)]
    m = scorecard.measures(s, journal(levels))
    assert m["depth"] == 17 and m["levels_up"] == 2 and m["z_span"] == 17, (m["depth"], m["levels_up"])
    # the old reading (one surface, the main way in's ground z161): depth 8, 4 levels up
    s2 = copy.deepcopy(s)
    s2.pop("entrances")
    m2 = scorecard.measures(s2, journal(levels))
    assert m2["depth"] == 8 and m2["levels_up"] == 4, (m2["depth"], m2["levels_up"])
    # the bridge's ground wins over the ways in
    levels[1]["ground"] = 169
    assert scorecard.measures(s, journal(levels))["levels_up"] == 3
    # no levels: nothing to say
    m3 = scorecard.measures(s, journal([]))
    assert m3["depth"] is None and m3["levels_up"] is None


@test("scorecard (group 6): the journal keeps each level's place and the bridge's ground over it")
def _():
    e = {"kind": "decision", "date": {"year": 260, "tick": 5},
         "action": {"type": "start_project", "kind": "workshops"},
         "result": {"ok": True, "z": 153, "anchor": {"x": 108, "y": 139}, "ground_z": 170, "tiles": 40}}
    j = scorecard.journal_counts([e], {"year": 261, "tick": 0})
    lv = j["levels"][0]
    assert (lv["x"], lv["y"], lv["ground"], lv["z"]) == (108, 139, 170, 153), lv
    e["result"].pop("ground_z")
    assert scorecard.journal_counts([e], {"year": 261, "tick": 0})["levels"][0]["ground"] is None


def deep_memory():
    m = Memory()
    m.atlas = {"entrances": {"108,149,170": {"kind": "surface", "elevation": 41}},
               "plan": {"v": 1, "spine": {"x": 108, "y": 149, "top": 41, "bottom": 22}, "axis": "south",
                        "vertical": "deep", "ceiling": 40, "range": [20, 40], "grammar": {},
                        "districts": [
                            {"id": "halls", "kind": "halls", "name": "the Old Echoing Halls", "lo": 37, "hi": 40,
                             "target": 39, "dirs": ["south"], "levels": []},
                            {"id": "homes", "kind": "homes", "name": "the Old Sleeping Deeps", "lo": 32, "hi": 35,
                             "target": 34, "dirs": ["north"], "levels": []},
                            {"id": "industry", "kind": "industry", "name": "the Old Workings", "lo": 22, "hi": 25,
                             "target": 24, "dirs": ["east"], "levels": []}]}}
    return m


@test("Deep mine (group 6): every rule's level gets its district of the deep plan (E: 53 of 83 levels went by the dwarves instead)")
def _():
    m = deep_memory()
    deep = {"surface": -100, "verticality": 120}
    s = copy.deepcopy(BASE)
    props = [Proposal("bottleneck", {"type": "start_project", "kind": "workshops", "shops": ["Mason"]}, "b", 5),
             Proposal("paper_shop", {"type": "start_project", "kind": "workshops", "shops": ["Paper"]}, "p", 5),
             Proposal("mood", {"type": "start_project", "kind": "workshops", "shops": ["Craft"], "urgent": True},
                      "m", 1),
             Proposal("build", {"type": "start_project", "kind": "bedrooms",
                                "plan": {"elev_lo": 33, "elev_hi": 33, "elev_target": 33}}, "l", 6),
             Proposal("farms", {"type": "farm_plots", "tiles": 30, "dig": True}, "f", 2)]
    out = _deep_surface_filter(s, deep, m, props, [])
    acts = {p.rule: p.action for p in out}
    for r in ("bottleneck", "paper_shop"):
        pl = acts[r].get("plan")
        assert pl and (pl["elev_lo"], pl["elev_hi"]) == (22, 25) and pl["district"] and acts[r]["max_elev"] == 40, \
            (r, acts[r])
    assert "plan" not in acts["mood"] and acts["mood"]["max_elev"] == 40, acts["mood"]     # urgent: nearest
    assert acts["build"]["plan"] == {"elev_lo": 33, "elev_hi": 33, "elev_target": 33}, acts["build"]  # its own
    assert "plan" not in acts["farms"], acts["farms"]
    # a kind with no district in the plan: no hint
    assert _deep_plan_hint({"type": "start_project", "kind": "barracks"}, m, deep, s) is None
    # no plan drawn yet: no hint
    assert _deep_plan_hint({"type": "start_project", "kind": "workshops"}, Memory(), deep, s) is None
    # the hint keeps under the ceiling even for a district grown past it
    m.atlas["plan"]["districts"][0]["hi"] = 44
    h = _deep_plan_hint({"type": "start_project", "kind": "tombs"}, m, deep, s)
    assert h["elev_hi"] == 40 and h["elev_target"] <= 40, h


@test("Deep mine (group 6): other presets' levels are untouched (no hint added outside the Deep mine)")
def _():
    m = deep_memory()
    s = copy.deepcopy(BASE)
    for t in ({"surface": 0, "verticality": 120}, {"surface": -79}, {"surface": 80}):
        props = [Proposal("bottleneck", {"type": "start_project", "kind": "workshops", "shops": ["Mason"]}, "b", 5)]
        out = _deep_surface_filter(s, t, m, props, [])
        assert "plan" not in out[0].action and "max_elev" not in out[0].action, (t, out[0].action)


if __name__ == "__main__":
    finish()
