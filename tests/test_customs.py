"""Tests for 0.105.29, group A: the fort customs (brain/customs.py) and where
they put levels (masterplan.hint, note_result, ceiling, and the Hermit
hold's ceiling in planner_industry._deep_surface_filter). No game needed.

    python tests/test_customs.py
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import make_test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from lupa.lua53 import LuaRuntime  # noqa: E402

import customs  # noqa: E402
import masterplan  # noqa: E402
from planner import Memory, Proposal  # noqa: E402
from planner_industry import _deep_surface_filter  # noqa: E402

test = make_test()

SITE = {"stairs": [{"x": 100, "y": 100, "z_top": 160, "z_bottom": 130, "elev_top": 60, "elev_bottom": 30,
                    "count": 8}],
        "citizen_elevation": 50, "soil": [58, 59], "elevation_offset": -100}
STATE = {"date": {"year": 150, "tick": 0, "day": 1, "month": "Granite", "season": "spring"},
         "dwarves": {"total": 40}}
PROFILE = {"layout": "grid", "palette": "dark", "temple": "shrine", "entry_doors": True}
KINDS = ["bedrooms", "dining", "tavern", "hospital", "temple", "library", "storage", "workshops",
         "barracks", "archery", "garden"]


def presets() -> dict:
    """BUILTIN_PRESETS from lua/ai-overseer-settings.lua, as the brain sees
    them (an Extreme slider's effective value is the preset's own number)."""
    src = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    block = re.search(r"^BUILTIN_PRESETS = \{.*?^\}", src, re.S | re.M).group(0)
    lua = LuaRuntime()
    lua.execute(block)
    t = lua.globals().BUILTIN_PRESETS
    return {name: dict(t[name].items()) for name in t.keys()}


PRESETS = presets()


def mem(entrance: str | None = None, elevation: int | None = None) -> Memory:
    m = Memory()
    m.culture = {"seed": "Test#1", "eras": [{"year": 150, "title": "Plain era"}]}
    m.atlas = {"survey": {"elevation_offset": -100, "tick": 1,
                          "layers": [{"name": "Cavern1", "z_top": 120, "z_bottom": 115, "discovered": True}]},
               "entrances": {}}
    if entrance:
        m.atlas["entrances"][entrance] = {"kind": "surface", **({"elevation": elevation} if elevation else {})}
    return m


def planned(traits: dict, entrance=None, elevation=None) -> Memory:
    m = mem(entrance, elevation)
    assert masterplan.ensure(copy.deepcopy(STATE), m, SITE, traits, PROFILE)
    return m


def district(m, kind) -> dict:
    return next(x for x in m.atlas["plan"]["districts"] if x["kind"] == kind)


ZERO: dict = {}


@test("customs: each built-in preset has exactly its own two; all-zero sliders none")
def _():
    want = {"Monastery": ["cloister", "cells"], "Merchant city": ["wide_ways", "market_gate"],
            "Hermit hold": ["winding_ways", "hidden_hold"], "War-hold": ["gate_barracks", "armoury"],
            "Deep mine": ["deep_hall", "ore_piles"], "Garden fort": ["field_hall", "field_kitchens"]}
    assert set(PRESETS) == set(want), sorted(PRESETS)
    for name, t in PRESETS.items():
        assert customs.active(t) == want[name], (name, customs.active(t))
        assert all(customs.CUSTOMS[c][1] == name for c in want[name])
    assert customs.active(ZERO) == [] and customs.active(None) == []
    assert customs.layout_customs(PRESETS["War-hold"], "barracks") == ["armoury"]
    assert customs.layout_customs(PRESETS["War-hold"], "temple") == []
    assert customs.has(PRESETS["Hermit hold"], "hidden_hold") and not customs.has(ZERO, "hidden_hold")


@test("hint: default sliders change nothing (no customs key, avenue 2, the district's own band)")
def _():
    for t in (ZERO, {"verticality": 0, "fortification": 50}):
        m = planned(t, "100,60,160", 60)
        for k in KINDS:
            a = masterplan.hint(m, k, traits=t, profile=PROFILE)
            b = masterplan.hint(m, k, traits=t, profile=PROFILE,
                                action={"type": "start_project", "kind": k, "shops": ["Still", "Kitchen"]},
                                citizens=30)
            assert a == b, (k, a, b)
            if a is None:
                continue
            assert "customs" not in a and a["avenue"] == 2, a
            d = masterplan._district(m, k)
            assert (a["elev_lo"], a["elev_hi"]) == (d["lo"], d["hi"]) and a["district"] == d["name"][:40], (k, a)
        assert masterplan.ceiling(m, t) is None


@test("Merchant city: 3-wide ways; the tavern in the gate band, toward the way in")
def _():
    t = PRESETS["Merchant city"]
    m = planned(t, "100,60,160", 60)                   # the way in is north of the stair
    h = masterplan.hint(m, "bedrooms", traits=t, profile=PROFILE)
    assert h["avenue"] == 3 and h["customs"] == ["wide_ways"], h
    tv = masterplan.hint(m, "tavern", traits=t, profile=PROFILE)
    assert (tv["elev_lo"], tv["elev_hi"], tv["elev_target"]) == (55, 57, 57), tv     # (customs fixes) s-5 .. s-3
    assert tv["dirs"][0] == "north" and tv["customs"] == ["market_gate", "wide_ways"], tv
    # the way in is the founding stair itself: the district's own directions
    m2 = planned(t, "101,100,160", 60)
    tv2 = masterplan.hint(m2, "tavern", traits=t, profile=PROFILE)
    assert tv2["dirs"] == district(m2, "homes")["dirs"] and tv2["elev_lo"] == 55, tv2


@test("Hermit hold: 1-wide dog-leg ways while 80 citizens or fewer; nothing at or above the surface")
def _():
    t = PRESETS["Hermit hold"]
    m = planned(t)
    small = masterplan.hint(m, "bedrooms", traits=t, profile=PROFILE, citizens=50)
    assert small["avenue"] == 1 and small["corridors"] == "dog-leg" and "winding_ways" in small["customs"], small
    big = masterplan.hint(m, "bedrooms", traits=t, profile=PROFILE, citizens=200)
    assert big["avenue"] == 2 and "customs" not in big, big
    assert masterplan.hint(m, "bedrooms", traits=t, profile=PROFILE)["avenue"] == 2, "no count: no custom"
    assert masterplan.ceiling(m, t) == 59, masterplan.ceiling(m, t)
    assert masterplan.ceiling(m, PRESETS["Garden fort"]) is None
    for k in KINDS:
        h = masterplan.hint(m, k, traits=t, profile=PROFILE)
        assert h is None or h["elev_hi"] <= 59, (k, h)


@test("War-hold: barracks and ranges in the 3 levels from 2 under the way in, the top one first")
def _():
    t = PRESETS["War-hold"]
    m = planned(t, "140,100,160", 60)                   # east of the stair
    for k in ("barracks", "archery"):
        h = masterplan.hint(m, k, traits=t, profile=PROFILE)
        assert (h["elev_lo"], h["elev_hi"], h["elev_target"]) == (56, 58, 58), h      # (customs fixes) s-4 .. s-2
        assert h["dirs"][0] == "east" and h["customs"] == ["gate_barracks"], h
    h = masterplan.hint(m, "bedrooms", traits=t, profile=PROFILE)
    assert "customs" not in h, h
    # a level used: the next goes to the next least-used level of the band
    h_ = masterplan.hint(m, "barracks", traits=t, profile=PROFILE)
    masterplan.note_result(m, {"type": "start_project", "kind": "barracks", "plan": h_},
                           {"ok": True, "project_id": 1, "elevation": 58, "in_district": True}, STATE)
    assert h_["district"] == district(m, "defence")["name"][:40]
    assert masterplan.hint(m, "barracks", traits=t, profile=PROFILE)["elev_target"] == 57


@test("Monastery: bedrooms go to the halls; note_result credits the halls, not the homes")
def _():
    t = PRESETS["Monastery"]
    m = planned(t)
    halls, homes = district(m, "halls"), district(m, "homes")
    h = masterplan.hint(m, "bedrooms", traits=t, profile=PROFILE)
    assert h["district"] == halls["name"][:40] and (h["elev_lo"], h["elev_hi"]) == (halls["lo"], halls["hi"]), h
    assert h["customs"] == ["cells"], h
    for i, inside in enumerate((True, False, False, False)):
        masterplan.note_result(m, {"type": "start_project", "kind": "bedrooms", "plan": h},
                               {"ok": True, "project_id": i, "elevation": h["elev_target"], "in_district": inside},
                               STATE)
    assert homes["missed"] == 0 and not homes["levels"], homes
    assert len(halls["levels"]) == 4, halls
    # a set piece in the halls (the temple) still goes to its slot's district
    assert masterplan.hint(m, "temple", slot="temple", traits=t, profile=PROFILE)["district"] == halls["name"][:40]
    # dining is not a cell: homes as before
    assert masterplan.hint(m, "dining", traits=t, profile=PROFILE)["district"] == homes["name"][:40]


@test("Deep mine: the dining hall in the industry district's band")
def _():
    t = PRESETS["Deep mine"]
    m = planned(t)
    ind = district(m, "industry")
    h = masterplan.hint(m, "dining", traits=t, profile=PROFILE)
    assert (h["elev_lo"], h["elev_hi"]) == (ind["lo"], ind["hi"]) and h["dirs"] == ind["dirs"], (h, ind)
    assert h["customs"] == ["deep_hall"] and h["district"] == ind["name"][:40], h
    # deep_hall comes before field_hall when a fort meets both
    both = dict(t, agriculture=100)
    assert masterplan.hint(m, "dining", traits=both, profile=PROFILE)["customs"] == ["deep_hall"]


@test("Garden fort: dining and food workshops at the farms' elevation; a mason's level not")
def _():
    t = PRESETS["Garden fort"]
    m = mem()                       # (customs fixes) soil 5 under the surface: the hall goes 3 under at most
    assert masterplan.ensure(copy.deepcopy(STATE), m, dict(SITE, soil=[55, 56]), t, PROFILE)
    farms = district(m, "farms")
    assert farms["lo"] == farms["hi"] == 55, farms
    h = masterplan.hint(m, "dining", traits=t, profile=PROFILE)
    assert (h["elev_lo"], h["elev_hi"], h["elev_target"]) == (55, 55, 55) and h["customs"] == ["field_hall"], h
    food = {"type": "start_project", "kind": "workshops", "shops": ["Still", "Kitchen"]}
    w = masterplan.hint(m, "workshops", traits=t, profile=PROFILE, action=food)
    assert w["elev_target"] == 55 and w["customs"] == ["field_kitchens"], w
    stone = {"type": "start_project", "kind": "workshops", "shops": ["Masons"]}
    w2 = masterplan.hint(m, "workshops", traits=t, profile=PROFILE, action=stone)
    ind = district(m, "industry")
    assert (w2["elev_lo"], w2["elev_hi"]) == (ind["lo"], ind["hi"]) and "customs" not in w2, w2
    assert "customs" not in masterplan.hint(m, "workshops", traits=t, profile=PROFILE), "no action: no custom"
    # the farms district credited for the hall
    masterplan.note_result(m, {"type": "start_project", "kind": "dining", "plan": h},
                           {"ok": True, "project_id": 1, "elevation": 55, "in_district": True}, STATE)
    assert len(farms["levels"]) == 1 and district(m, "homes")["missed"] == 0
    # no farms district (no soil found): unchanged
    m2 = mem()
    assert masterplan.ensure(copy.deepcopy(STATE), m2, dict(SITE, soil=[]), t, PROFILE)
    h2 = masterplan.hint(m2, "dining", traits=t, profile=PROFILE)
    assert "customs" not in h2 and h2["district"] == district(m2, "homes")["name"][:40], h2


@test("_deep_surface_filter: the Hermit hold's levels get a ceiling and the custom; farms left alone")
def _():
    t = PRESETS["Hermit hold"]
    m = planned(t)
    props = [Proposal("build", {"type": "start_project", "kind": "bedrooms"}, "beds", 6),
             Proposal("build", {"type": "start_project", "kind": "storage", "max_elev": 40}, "store", 6),
             Proposal("farm", {"type": "farm_plots", "dig": True, "outside": True}, "farm", 5),
             Proposal("surface_farm", {"type": "place_surface", "kind": "depot"}, "depot", 5)]
    before = [copy.deepcopy(p.action) for p in props]
    out = _deep_surface_filter({}, t, m, props, [])
    assert len(out) == 4
    assert out[0].action["max_elev"] == 59 and out[0].action["customs"] == ["hidden_hold"], out[0].action
    assert out[1].action == before[1], out[1].action     # (customs fixes) already under the ceiling: no stamp
    assert out[2].action == before[2] and out[3].action == before[3]
    # other forts: nothing changes
    props2 = [Proposal("build", {"type": "start_project", "kind": "bedrooms"}, "beds", 6)]
    for name in ("Garden fort", "War-hold", "Merchant city", "Monastery"):
        out2 = _deep_surface_filter({}, PRESETS[name], m, props2, [])
        assert out2[0].action == {"type": "start_project", "kind": "bedrooms"}, (name, out2[0].action)
    assert _deep_surface_filter({}, ZERO, m, props2, [])[0].action == {"type": "start_project", "kind": "bedrooms"}


if __name__ == "__main__":
    finish()
