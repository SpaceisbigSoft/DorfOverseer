"""Tests for the scripted season choice (brain/season.py, 0.104.3).

    python tests/test_season.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import season  # noqa: E402
from planner import Memory  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort(pop=50, needs=None, stocks=None, traits=None, levels=None):
    s = copy.deepcopy(BASE)
    s["dwarves"]["total"] = pop
    s["date"] = {"year": 60, "tick": 1000, "season": "spring", "day": 1, "month": "Granite"}
    s["needs"] = {"needs": {k: {"distracted": v} for k, v in (needs or {}).items()}}
    s["stocks"] = {**(s.get("stocks") or {}), "drink": pop * 20, "prepared_meals": pop * 20, "wood": pop * 20,
                   "blocks": pop * 20, **(stocks or {})}
    s["settings"]["traits"] = traits or {}
    if levels is not None:
        s["settings"]["levels"] = levels
    s["locations"] = {"count": {}}
    s["dead"] = {}
    return s


@test("a thirsty fort brews; a fort longing for company raises its tavern")
def _():
    c = season.pick(fort(stocks={"drink": 10}, needs={"DrinkAlcohol": 20}), Memory())
    assert c["choice"] == "focus:drink" and "drink short" in c["why"] and c["by"] == "script", c
    assert c["line"].startswith("Spring of 60:"), c
    c = season.pick(fort(needs={"BeWithFriends": 30, "MakeMerry": 25}), Memory())
    assert c["choice"] == "raise:tavern" and "company" in c["why"], c


@test("a hall switched off on the Rules tab is never chosen; nothing pressing keeps the fort's ways")
def _():
    s = fort(needs={"BeWithFriends": 30})
    s["settings"]["levels"] = {"tavern": False}
    assert season.pick(s, Memory())["choice"] != "raise:tavern"
    c = season.pick(fort(), Memory())
    assert c["choice"] == "keep" and "old ways" in c["line"], c


@test("sliders and quirks lean the choice; a tavern already standing weighs less")
def _():
    s = fort(needs={"PrayOrMeditate": 10, "BeWithFriends": 10})
    assert season.pick(s, Memory())["choice"] in ("raise:temple", "raise:tavern")
    s["settings"]["traits"] = {"piety": 100}
    assert season.pick(s, Memory())["choice"] == "raise:temple"
    m = Memory()
    m.culture = {"quirks": {"mead_hall": {}}}
    s["settings"]["traits"] = {}
    assert season.pick(s, m)["choice"] == "raise:tavern"
    s["locations"] = {"count": {"INN_TAVERN": 2}}
    assert season.score_options(s, m)["raise:tavern"][0] < season.score_options(fort(needs={"BeWithFriends": 10}), m)["raise:tavern"][0]


@test("(0.104.162) the reason names the sliders that tipped it; Extreme pushes twice as hard; needs first")
def _():
    s = fort(needs={"BeWithFriends": 30})                   # a tavern by need alone
    assert season.pick(s, Memory())["choice"] == "raise:tavern"
    s["settings"]["traits"] = {"piety": 200}
    c = season.pick(s, Memory())
    assert c["choice"] == "raise:temple" and "sliders tipped it" in c["why"] and "Piety +200" in c["why"], c
    p1 = season.slider_pushes(fort(traits={"piety": 100}), Memory())["raise:temple"][0][2]
    p2 = season.slider_pushes(fort(traits={"piety": 200}), Memory())["raise:temple"][0][2]
    assert abs(p2 - 2 * p1) < 1e-9, (p1, p2)
    # the weight is a config key: 0 leaves needs and quirks alone
    from planner import PLANNER_CONFIG
    assert season.pick(s, Memory(), dict(PLANNER_CONFIG, season_slider_weight=0))["choice"] == "raise:tavern"
    # in crisis the sliders don't lean: the need wins again
    m = Memory()
    m.crisis = {"since": 1, "why": ["45% unhappy"]}
    c = season.pick(s, m)
    assert c["choice"] == "raise:tavern" and "needs alone choose" in c["why"], c
    # hunger before the sliders
    from planner import ALL_FOOD
    s = fort(traits={"piety": 200}, stocks={k: 0 for k in ALL_FOOD})
    c = season.pick(s, Memory())
    assert c["choice"] == "focus:food" and "hunger comes first" in c["why"], c


@test("the AI has two weeks of a season; then the script chooses")
def _():
    s = fort()
    s["date"]["tick"] = 5 * 1200
    assert not season.ai_gave_up(s, Memory())
    s["date"]["tick"] = 15 * 1200
    assert season.ai_gave_up(s, Memory())
    s["date"]["tick"] = season.SEASON_TICKS + 3 * 1200          # summer's first days
    assert not season.ai_gave_up(s, Memory())


@test("the choice applies like the AI's: kept a season, once a season")
def _():
    m = Memory()
    s = fort(stocks={"drink": 10}, needs={"DrinkAlcohol": 20})
    assert season.due(s, m)
    said = season.apply(season.pick(s, m), s, m, m.adjust)
    assert not season.due(s, m) and m.culture["season_choice"]["choice"] == "focus:drink" and m.adjust.get("drink_per_dwarf"), said


if __name__ == "__main__":
    finish()
