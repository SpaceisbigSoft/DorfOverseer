"""(0.105.75) A new stairwell when the staircase's levels are all refused for water.

Live 22 Nov, D (the Hermit hold, 17 dwarves, unhappy 32%, idle 46%): one
staircase (x108 y149, elevations 40-42) and a stagnant pool under its first
floor at x109 y149, elevation 39. Every new level (arms_forge, bags, build,
fishery, industry, homes_dig...) was refused for seasons: "no safe level found
near 1 staircase(s), none above elevation 40 (under the surface only) (z38:
water or magma directly above x109 y150 z38; z37: stairs down to z37: water or
magma at x109 y149 z39; ...)". The stairwell rule never ran: the style wanted
one stairwell (it had one) and it needed 30 citizens.

    python tests/test_r75_stairs_blocked.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

import planner_building_rooms as R  # noqa: E402
import planner_stairs_blocked as SB  # noqa: E402
import masterplan  # noqa: E402
from planner_core import PLANNER_CONFIG, TICKS_PER_DAY, abs_tick  # noqa: E402

WHY = ("no safe level found near # staircase(s), none above elevation # (under the surface only) "
       "(z#: water ")
DISTRICTS = [
    {"id": "defence", "kind": "defence", "lo": 41, "hi": 42, "dirs": ["east", "south", "west", "north"]},
    {"id": "halls", "kind": "halls", "lo": 40, "hi": 41, "dirs": ["south", "west", "north", "east"]},
    {"id": "homes", "kind": "homes", "lo": 39, "hi": 40, "dirs": ["west", "north", "east", "south"]},
    {"id": "storage", "kind": "storage", "lo": 38, "hi": 39, "dirs": ["north", "east", "south", "west"]},
    {"id": "industry", "kind": "industry", "lo": 37, "hi": 38, "dirs": ["east", "south", "west", "north"]},
    {"id": "farms", "kind": "farms", "lo": 40, "hi": 40, "dirs": ["south", "west", "north", "east"]},
]


def state(pop=17, year=254, tick=143715):
    return {"date": {"year": year, "tick": tick}, "dwarves": {"total": pop},
            "food_store": {}, "others_on_map": {}, "farms": {}}


def memory(streaks):
    return SimpleNamespace(
        atlas={"plan": {"spine": {"x": 108, "y": 149, "bottom": 40, "top": 42},
                        "districts": [dict(d) for d in DISTRICTS]},
               "survey": {"site": {"stairwells": 1}}},
        culture={}, refusal_streaks=streaks)


def streak(rule, at, why=WHY):
    return {f"{rule}:x": {"at": at, "n": 1, "rule": rule, "why": why, "type": "start_project"}}


def run(s, m, traits=None):
    props = []
    old = R.young_fort
    R.young_fort = lambda s_, c_: False
    try:
        R._stairwell_rule(s, m, PLANNER_CONFIG, traits or {}, props)
    finally:
        R.young_fort = old
    return props


@test("D's case: two kinds of work refused for water lately: a new stairwell for the deepest district "
      "(industry, elevations 37-38), east of the main stair, whatever the style (wants 1, has 1) and the 17 dwarves")
def _():
    s = state()
    now = abs_tick(s)
    m = memory({**streak("industry", now - 2 * TICKS_PER_DAY), **streak("bags", now - 5 * TICKS_PER_DAY),
                **streak("fishery", now - 1 * TICKS_PER_DAY)})
    props = run(s, m)
    assert len(props) == 1, props
    a = props[0].action
    assert a == {"type": "dig_stairwell", "dir": "east", "elev_lo": 37, "elev_hi": 38, "district": "industry",
                 "spine": {"x": 108, "y": 149}}, a
    assert "water or magma" in props[0].reason and props[0].rule == "stairwell"


@test("not blocked: one rule only, or refusals over 30 days old, or another reason: the style's rule as before "
      "(17 dwarves under the 30: nothing)")
def _():
    s = state()
    now = abs_tick(s)
    assert run(s, memory(streak("industry", now - TICKS_PER_DAY))) == []
    assert run(s, memory({**streak("industry", now - 40 * TICKS_PER_DAY),
                          **streak("bags", now - 41 * TICKS_PER_DAY)})) == []
    other = "no safe level found near # staircase(s) (z#: not solid rock"
    assert run(s, memory({**streak("industry", now, other), **streak("bags", now, other)})) == []


@test("blocked but every district already has its stairwell (or only farms and homes left): nothing")
def _():
    s = state()
    now = abs_tick(s)
    m = memory({**streak("industry", now), **streak("bags", now)})
    for d in m.atlas["plan"]["districts"]:
        d["stair"] = {"x": 1, "y": 1}
    assert run(s, m) == []


@test("stairwell_district: deepest picks the lowest district (plan order on a tie); the default as before")
def _():
    m = memory({})
    assert masterplan.stairwell_district(m, deepest=True)["id"] == "industry"
    assert masterplan.stairwell_district(m)["id"] == "defence"


if __name__ == "__main__":
    finish()
