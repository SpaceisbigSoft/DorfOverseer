"""Tests for the scripted season choice (brain/season.py, 0.104.3).

    python tests/test_season.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

import season  # noqa: E402
from planner import Memory  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
RESULTS = []


def test(name):
    def wrap(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


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
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f"\n    {msg}"))
    fails = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - fails} passed, {fails} failed")
    sys.exit(1 if fails else 0)
