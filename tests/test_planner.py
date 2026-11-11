"""Tests for the local planner. Run from the project folder:

    python tests/test_planner.py

Built on a real fort report (tests/fixtures/test_fort.json, 194 dwarves) with
one thing changed per test to create each situation.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish, code_has  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import planner  # noqa: E402
from planner import (PLANNER_CONFIG, Memory, effective_config, factor, game_day, note_cycle,  # noqa: E402
                     plan, record, select, abs_tick, TICKS_PER_DAY)

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort(**changes) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"      # (the saved fort is in winter; stocking up for winter has its own test)
    for path, value in changes.items():
        node = s
        keys = path.split("__")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    return s


def rules(proposals) -> list[str]:
    return [p.rule for p in proposals]


@test("well-stocked real fort: no stock orders")
def _():
    p, notes = plan(fort(), Memory())
    assert "drink" not in rules(p) and "food" not in rules(p), rules(p)


@test("low drink: orders brewing, sized to the shortfall, capped")
def _():
    p, _ = plan(fort(stocks__drink=100), Memory())
    d = [x for x in p if x.rule == "drink"]
    assert d, rules(p)
    assert d[0].action == {"type": "work_order", "recipe": "brew_drink", "amount": 100}, d[0].action
    assert "URGENT" in d[0].reason


@test("low drink but brewing already queued: no duplicate order")
def _():
    s = fort(stocks__drink=1800)
    assert "drink" in rules(plan(s, Memory())[0])                         # (13c) nothing queued: brewed
    s["orders"].append({"id": 9, "recipe": "brew_drink", "amount_left": 200, "by_ai": False})
    p, _ = plan(s, Memory())
    assert "drink" not in rules(p), rules(p)


@test("low drink, no plants: a note, no impossible order")
def _():
    p, notes = plan(fort(stocks__drink=10, stocks__plants=0), Memory())
    assert "drink" not in rules(p)
    assert any("no plants" in n for n in notes), notes


@test("Stockpile buffer +200 raises the drink target 4x")
def _():
    s = fort(stocks__drink=3000)
    assert "drink" not in rules(plan(s, Memory())[0])
    s["settings"]["traits"] = {"stockpile": 200}
    assert "drink" in rules(plan(s, Memory())[0])


@test("brewing (0.100): no more brew jobs than empty barrels and pots")
def _():
    s = fort(stocks__drink=0, stocks__plants=500)
    s["supplies"].update(empty_barrels=3, empty_pots=4)
    d = [x for x in plan(copy.deepcopy(s), Memory())[0] if x.rule == "drink"]
    assert d and d[0].action["amount"] == 7, d
    s["supplies"].update(empty_barrels=0, empty_pots=0)
    props, notes = plan(copy.deepcopy(s), Memory())[:2]
    assert not [x for x in props if x.rule == "drink"] and any("no empty barrels or pots" in n for n in notes)
    del s["supplies"]["empty_barrels"]                 # an older report: not limited
    d = [x for x in plan(copy.deepcopy(s), Memory())[0] if x.rule == "drink"]
    assert d and d[0].action["amount"] >= PLANNER_CONFIG["min_order"], d


@test("Welfare picks the meal grade")
def _():
    for welfare, recipe in ((80, "prepare_lavish_meal"), (0, "prepare_fine_meal"), (-80, "prepare_easy_meal")):
        s = fort(stocks__prepared_meals=50)
        s["settings"]["traits"] = {"welfare": welfare}
        food = [x for x in plan(s, Memory())[0] if x.rule == "food"]
        assert food and food[0].action["recipe"] == recipe, (welfare, food)


@test("food order never exceeds what raw food can make")
def _():
    s = fort(stocks__prepared_meals=0, stocks__meat=10, stocks__fish=0, stocks__plants=5)
    food = [x for x in plan(s, Memory())[0] if x.rule == "food"]
    assert food and food[0].action["amount"] <= 15 // 3, food


@test("meals (0.100): a job makes ~10 servings and takes whole ingredient stacks (the bridge's count, else items / 5)")
def _():
    s = fort(stocks__prepared_meals=0, stocks__meat=200, stocks__fish=0, stocks__plants=100)
    s["dwarves"]["total"] = 20
    s["supplies"]["food_stacks"] = 12                  # 12 stacks: 4 fine meals (3 stacks each)
    food = [x for x in plan(copy.deepcopy(s), Memory())[0] if x.rule == "food"]
    assert food and food[0].action["recipe"] == "prepare_fine_meal" and food[0].action["amount"] == 4, food
    del s["supplies"]["food_stacks"]                   # older bridge: 300 items / 5 = 60 stacks, 20 jobs
    food = [x for x in plan(copy.deepcopy(s), Memory())[0] if x.rule == "food"]
    target = int(food[0].reason.split("target of ")[1])
    assert food[0].action["amount"] == min(20, max(PLANNER_CONFIG["min_order"], -(-target // 10))), food
    s["stocks"].update(meat=30, plants=15)             # 45 items / 5 = 9 stacks: 3 jobs
    food = [x for x in plan(copy.deepcopy(s), Memory())[0] if x.rule == "food"]
    assert food and food[0].action["amount"] == 3, food


@test("threat that can reach the dwarves: sounds the alert")
def _():
    s = fort()
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 2
    p, _ = plan(s, Memory())
    assert p[0].rule == "threat_alert" and p[0].action == {"type": "civ_alert", "on": True}, p[:1]


@test("threat but no alert burrow: the AI sets up its own shelter, urgently; refused twice -> tried again later (0.105.35)")
def _():
    s = fort(civ_alert_ready=False)
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    p, notes = plan(s, Memory())
    sh = [x for x in p if x.rule == "shelter"]
    assert "threat_alert" not in rules(p) and sh and sh[0].priority == 0, rules(p)
    assert any("setting up a shelter" in n for n in notes), notes
    s["settings"]["alert_shelter"] = False                        # the player's switch: no shelter, said
    p, notes = plan(s, Memory())
    assert "shelter" not in rules(p) and any("burrow" in n and "Rules tab" in n for n in notes), notes
    assert not any(n.startswith("[you] ") for n in notes), notes
    s["settings"]["alert_shelter"] = True
    now = s["date"]["year"] * 403200 + s["date"]["tick"]
    p, notes = plan(s, Memory(shelter_attempts=2, shelter_tick=now - 1200))   # refused twice a day ago: waits
    assert "shelter" not in rules(p) and any("tried again in 2 day(s)" in n for n in notes), notes
    assert not any(n.startswith("[you] ") for n in notes), notes
    p, notes = plan(s, Memory(shelter_attempts=2, shelter_tick=now - 3 * 1200))   # 3 days on, a threat: again
    assert [x for x in p if x.rule == "shelter"][0].priority == 0, rules(p)
    p, _ = plan(fort(civ_alert_ready=False), Memory(shelter_attempts=2, shelter_tick=now - 3 * 1200))
    assert "shelter" not in rules(p)                              # no threat: the 28-day wait
    assert [x for x in plan(fort(civ_alert_ready=False), Memory())[0] if x.rule == "shelter"][0].priority == 4


@test("real fort's underworld demons (no path) do NOT trigger the alert")
def _():
    assert "threat_alert" not in rules(plan(fort(), Memory())[0])


@test("Caution +100 reacts to nearby threats of unknown reach (review #14: on the SAME level as a dwarf too)")
def _():
    for levels in (3, 0):
        s = fort()
        s["others_on_map"]["threats"][0]["levels_from_nearest_dwarf"] = levels
        s["others_on_map"]["threats"][0].pop("can_reach_dwarves", None)
        assert "threat_alert" not in rules(plan(s, Memory())[0]), levels
        s["settings"]["traits"] = {"caution": 100}
        assert "threat_alert" in rules(plan(s, Memory())[0]), levels


@test("AI lowers its own alert only after 3 quiet cycles")
def _():
    s = fort(civ_alert=True)
    m = Memory(ai_alert_raised=True, quiet_cycles=0)
    assert "threat_alert" not in rules(plan(s, m)[0])
    m.quiet_cycles = 3
    p = plan(s, m)[0]
    assert p and p[0].action == {"type": "civ_alert", "on": False}, p


@test("alert (0.104.100): after a titan, the alarm holds 7 days and the gates stay shut; 3 days after any threat")
def _():
    from planner import note_cycle, abs_tick, TICKS_PER_DAY
    s = fort(civ_alert=True)
    s["others_on_map"]["threats"] = [{"id": 77, "name": "Ume, Swamp Titan", "great_danger": True,
                                      "can_reach_dwarves": True, "layer": "upper_levels"}]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    m = Memory(ai_alert_raised=True, quiet_cycles=0)
    note_cycle(s, m)
    t0 = abs_tick(s)
    assert m.last_threat_tick == t0 and m.last_great_tick == t0
    s["others_on_map"]["threats"] = []                                  # the titan dies
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    m.quiet_cycles = 3
    s["date"]["tick"] += 2 * TICKS_PER_DAY
    p, notes = plan(s, m)
    assert not any(x.action == {"type": "civ_alert", "on": False} for x in p), p
    assert any("the alarm stays up: a great danger was about 2 day(s) ago" in n for n in notes), notes
    s["date"]["tick"] += 6 * TICKS_PER_DAY
    p = plan(s, m)[0]
    assert any(x.action == {"type": "civ_alert", "on": False} for x in p), p
    # an ordinary threat: 3 days
    m2 = Memory(ai_alert_raised=True, quiet_cycles=3, last_threat_tick=abs_tick(s) - TICKS_PER_DAY)
    assert not any(x.action == {"type": "civ_alert", "on": False} for x in plan(s, m2)[0])
    m2.last_threat_tick = abs_tick(s) - 4 * TICKS_PER_DAY
    assert any(x.action == {"type": "civ_alert", "on": False} for x in plan(s, m2)[0])
    # (0.105.2) the game slow and nothing hostile left: the quiet days skipped (B's sealed hatch)
    m3 = Memory(ai_alert_raised=True, quiet_cycles=3, last_threat_tick=abs_tick(s) - TICKS_PER_DAY)
    slow = {**s, "fps_low": 3}
    assert any(x.action == {"type": "civ_alert", "on": False} for x in plan(slow, m3)[0])
    from planner_core import all_clear, PLANNER_CONFIG as C
    assert all_clear(slow, m3, C)[0] and not all_clear(s, m3, C)[0]
    held = {**slow, "others_on_map": {**s.get("others_on_map", {}),
                                       "threats": [{"id": 1, "name": "goblin", "invader": True, "can_reach_dwarves": False}]}}
    assert not all_clear(held, m3, C)[0]                # an invader still about: the gates wait


@test("never lowers an alert the PLAYER raised")
def _():
    s = fort(civ_alert=True)
    m = Memory(ai_alert_raised=False, quiet_cycles=10)
    assert "threat_alert" not in rules(plan(s, m)[0])


@test("turns on missing helpful tools (seedwatch, autochop when wood is low)")
def _():
    p, _ = plan(fort(stocks__wood=10), Memory())
    names = {x.action["name"] for x in p if x.rule == "tools"}
    assert {"seedwatch", "autochop"} <= names, names
    assert "suspendmanager" not in names  # already on


@test("a tool the player switched off stays off")
def _():
    m = Memory(tools_enabled_by_ai=["seedwatch"], tools_seen_on=["seedwatch"])
    notes = note_cycle(fort(), m)
    p, _ = plan(fort(), m)
    assert "seedwatch" not in {x.action.get("name") for x in p}
    assert "seedwatch" in m.tools_player_disabled and any("switched off" in n for n in notes)
    p2, _ = plan(fort(), m)
    assert "seedwatch" not in {x.action.get("name") for x in p2}


@test("a tool that won't switch on: retried, then given up with a note (player not blamed)")
def _():
    s = fort()
    m = Memory()
    for attempt in range(3):
        p, notes = plan(s, m)
        tool = [x for x in p if x.action.get("name") == "seedwatch"]
        if attempt < 2:
            assert tool, (attempt, rules(p))
            record([(tool[0], {"ok": True, "enabled": False})], s, m)
            s["date"]["tick"] += 2400
        else:
            assert not tool, rules(p)
            assert any("tried twice" in n for n in notes), notes
    assert "seedwatch" not in m.tools_player_disabled


@test("tool switched on, seen running, later off: only then blame the player")
def _():
    m = Memory()
    s = fort()
    p, _ = plan(s, m)
    record([(x, {"ok": True, "enabled": None}) for x in p if x.action.get("name") == "seedwatch"], s, m)
    assert "seedwatch" not in m.tools_confirmed_on
    note_cycle(fort(tools__seedwatch=True), m)
    assert "seedwatch" in m.tools_confirmed_on
    note_cycle(fort(), m)
    p2, notes = plan(fort(), m)
    assert "seedwatch" in m.tools_player_disabled and not [x for x in p2 if x.action.get("name") == "seedwatch"]


@test("tools with unknown state (None) are left alone")
def _():
    p, _ = plan(fort(), Memory())
    assert "nestboxes" not in {x.action.get("name") for x in p}
    p, _ = plan(fort(tools__nestboxes=False), Memory())                  # (13c) known to be off: switched on
    assert "nestboxes" in {x.action.get("name") for x in p}


@test("mandate with a recipe gets queued; one without gets a note")
def _():
    s = fort(mandates=[{"kind": "Make", "item": "STATUE", "remaining": 3, "total": 3, "days_left": 40},
                       {"kind": "Make", "item": "GOBLET", "remaining": 3, "total": 3, "days_left": 59}])
    p, notes = plan(s, Memory())
    m = [x for x in p if x.rule == "mandate"]
    assert m and m[0].action == {"type": "work_order", "recipe": "stone_statue", "amount": 3}, m
    assert any("GOBLET" in n for n in notes), notes


@test("Noble deference -100 ignores mandates")
def _():
    s = fort(mandates=[{"kind": "Make", "item": "STATUE", "remaining": 3, "total": 3, "days_left": 40}])
    assert "mandate" in rules(plan(s, Memory())[0])                       # (13c) at the default: it's made
    s["settings"]["traits"] = {"deference": -100}
    assert "mandate" not in rules(plan(s, Memory())[0])


@test("idle hands: lots of idle adults + boulders -> stone blocks")
def _():
    p, _ = plan(fort(stocks__blocks=100), Memory())
    idle = [x for x in p if x.rule == "idle"]
    assert idle and idle[0].action["recipe"] == "stone_blocks", rules(p)
    assert PLANNER_CONFIG["idle_order_min"] <= idle[0].action["amount"] <= PLANNER_CONFIG["idle_order_max"]


@test("a failed report section skips only the rules that need it")
def _():
    s = fort(stocks={"error": "boom"}, stocks__drink=0) if False else fort()
    s["stocks"] = {"error": "boom"}
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    p, notes = plan(s, Memory())
    assert "drink" not in rules(p) and "food" not in rules(p) and "threat_alert" in rules(p)
    assert any("stocks" in n for n in notes), notes


@test("limits: at most 3 routine actions per cycle; the alert goes first and doesn't count")
def _():
    s = fort(stocks__drink=10, stocks__prepared_meals=10, stocks__wood=0, stocks__blocks=0)
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    p, _ = plan(s, Memory())
    allowed, held = select(p, s, Memory())
    rules_ = [a.rule for a in allowed]
    from planner import LIMIT_EXEMPT
    assert rules_[0] == "threat_alert" and len([r for r in rules_ if r not in LIMIT_EXEMPT]) == 3, rules_
    assert any("limit" in h for h in held), held


@test("limits: a rule waits 2 in-game days after acting")
def _():
    s = fort(stocks__drink=10)
    m = Memory()
    p, _ = plan(s, m)
    allowed, _ = select(p, s, m)
    record([(x, {"ok": True}) for x in allowed], s, m)
    s2 = copy.deepcopy(s)
    s2["date"]["tick"] += 1200  # one day later
    allowed2, held2 = select(plan(s2, m)[0], s2, m)
    assert "drink" not in [a.rule for a in allowed2] and any("cooldown" in h for h in held2)
    s3 = copy.deepcopy(s)
    s3["date"]["tick"] += 2400  # two days later
    assert "drink" in [a.rule for a in select(plan(s3, m)[0], s3, m)[0]]


@test("limits: daily work-order cap")
def _():
    s = fort(stocks__drink=10)
    m = Memory()
    m.orders_by_day[str(game_day(s))] = PLANNER_CONFIG["max_orders_per_game_day"]
    allowed, held = select(plan(s, m)[0], s, m)
    assert not [a for a in allowed if a.is_order] and any("today" in h for h in held)


@test("failed actions don't start a cooldown")
def _():
    s = fort(stocks__drink=10)
    m = Memory()
    allowed, _ = select(plan(s, m)[0], s, m)
    record([(x, {"ok": False, "rejected": True}) for x in allowed], s, m)
    assert m.last_fired == {}


@test("trait factor maths")
def _():
    assert factor({}, "x") == 1 and factor({"x": 100}, "x") == 2 and factor({"x": -200}, "x") == 0.25


@test("memory survives a round trip through JSON")
def _():
    m = Memory(ai_alert_raised=True, tools_enabled_by_ai=["autochop"])
    m2 = Memory.from_dict(json.loads(json.dumps(m.to_dict())))
    assert m2.ai_alert_raised and m2.tools_enabled_by_ai == ["autochop"]


@test("note_cycle: player clearing the alert hands ownership back")
def _():
    m = Memory(ai_alert_raised=True)
    note_cycle(fort(civ_alert=False), m)
    assert m.ai_alert_raised is False


@test("orders only for approved recipes, sizes within limits")
def _():
    s = fort(stocks__drink=0, stocks__prepared_meals=0, stocks__blocks=0, stocks__wood=0,
             mandates=[{"kind": "Make", "item": "TABLE", "remaining": 99, "total": 99, "days_left": 9}])
    approved = {"brew_drink", "prepare_easy_meal", "prepare_fine_meal", "prepare_lavish_meal",
                "stone_blocks", "stone_table"}
    for p in plan(s, Memory())[0]:
        if p.action["type"] == "work_order":
            assert p.action["recipe"] in approved, p.action
            assert 1 <= p.action["amount"] <= PLANNER_CONFIG["max_order"], p.action


# --- fixes from the code review --------------------------------------------

def cycle(s, m, ok=True):
    """The real order the overseer uses: note_cycle, plan, select, act, record."""
    note_cycle(s, m)
    p, notes = plan(s, m)
    allowed, _ = select(p, s, m)
    record([(x, {"ok": ok}) for x in allowed], s, m)
    return allowed, notes


def threat(s, tid=1, reach=True):
    s["others_on_map"]["threats"].append({"id": tid, "name": "goblin", "can_reach_dwarves": reach,
                                          "levels_from_nearest_dwarf": 0})
    s["others_on_map"]["threats_that_can_reach_dwarves"] += 1 if reach else 0
    return s


@test("review #1: full cycle raises the alert, keeps ownership, lowers it after 3 quiet cycles")
def _():
    m = Memory()
    s = threat(fort())
    a, _ = cycle(s, m)
    assert a and a[0].action == {"type": "civ_alert", "on": True} and m.ai_alert_raised
    lowered_at = None
    for i in range(1, 6):
        q = fort(civ_alert=True)
        q["date"]["tick"] += 1200 * i
        a, _ = cycle(q, m)
        if any(x.action == {"type": "civ_alert", "on": False} for x in a):
            lowered_at = i
            break
        assert m.ai_alert_raised, f"lost ownership on quiet cycle {i}"
    assert lowered_at == 3, lowered_at
    assert m.ai_alert_raised is False


@test("review #2: player clears the AI's alert -> not re-raised for the same threat; a new one still counts")
def _():
    m = Memory(ai_alert_raised=True)
    s = threat(fort(civ_alert=False), tid=7)
    a, notes = cycle(s, m)
    assert not [x for x in a if x.rule == "threat_alert"], a
    assert any("cleared" in n for n in notes), notes
    s2 = threat(threat(fort(civ_alert=False), tid=7), tid=8)
    assert [x for x in plan(s2, m)[0] if x.rule == "threat_alert"]
    note_cycle(fort(), m)          # all threats gone: the suppression is forgotten
    assert m.alert_suppressed == []


@test("review #2: alert that was already on (player's) is not taken over")
def _():
    m = Memory()
    p = [x for x in plan(threat(fort()), m)[0] if x.rule == "threat_alert"][0]
    record([(p, {"ok": True, "on": True, "already_on": True})], fort(), m)
    assert m.ai_alert_raised is False


@test("review #3: an unknown result (timeout) still starts the cooldown and counts the order")
def _():
    s = fort(stocks__drink=10)
    m = Memory()
    allowed, _ = select(plan(s, m)[0], s, m)
    record([(x, {"ok": None, "error": "timeout"}) for x in allowed], s, m)
    assert "drink" in m.last_fired and m.orders_by_day


@test("review #4: missing or failed orders/tools sections: no crash, no orders, no tools")
def _():
    for broken in ({"error": "boom"}, None):
        s = fort(stocks__drink=10, stocks__wood=0)
        if broken is None:
            del s["orders"]; del s["tools"]
        else:
            s["orders"] = broken; s["tools"] = broken
        p, notes = plan(s, Memory())
        assert not [x for x in p if x.rule in ("drink", "food", "idle", "tools", "mandate")], rules(p)
        assert any("orders" in n for n in notes), notes


@test("review #5: failed stocks section does not switch autochop on")
def _():
    s = fort(stocks__wood=0)
    assert "autochop" in {x.action.get("name") for x in plan(s, Memory())[0]}     # (13c) no wood read: on
    s["stocks"] = {"error": "boom"}
    assert "autochop" not in {x.action.get("name") for x in plan(s, Memory())[0]}


@test("review #6: loading an older save doesn't freeze the rules")
def _():
    s = fort(stocks__drink=10)
    m = Memory(last_fired={"drink": 10**9}, orders_by_day={str(10**7): 8})
    note_cycle(s, m)
    assert "drink" in [a.rule for a in select(plan(s, m)[0], s, m)[0]]


@test("review #7: order sizes are in jobs (one brew job = 5 drinks)")
def _():
    s = fort(stocks__drink=1700)          # target 1940: short by 240 drinks = 48 jobs
    d = [x for x in plan(s, Memory())[0] if x.rule == "drink"][0]
    assert d.action["amount"] == 48, d.action
    s["orders"].append({"id": 9, "recipe": "brew_drink", "amount_left": 48})   # 240 drinks queued
    assert "drink" not in rules(plan(s, Memory())[0])


@test("review #8: mandate for a non-stone material is noted, not met with stone")
def _():
    s = fort(mandates=[{"kind": "Make", "item": "TABLE", "remaining": 3, "material": "gold",
                        "material_is_stone": False}])
    p, notes = plan(s, Memory())
    assert "mandate" not in rules(p) and any("gold" in n for n in notes), notes
    s["mandates"][0].update(material="granite", material_is_stone=True, material_token="INORGANIC:GRANITE")
    m = [x for x in plan(s, Memory())[0] if x.rule == "mandate"][0]
    assert m.action["material"] == "INORGANIC:GRANITE"


@test("review #9: a repeating order counts even between repeats")
def _():
    s = fort(stocks__drink=1800)
    s["orders"].append({"id": 9, "recipe": "brew_drink", "amount_left": 0, "amount_total": 30, "repeats": True})
    assert "drink" not in rules(plan(s, Memory())[0])


@test("review #10: a tool the player had on and switched off is never turned back on")
def _():
    m = Memory()
    assert "seedwatch" in {x.action.get("name") for x in plan(fort(), m)[0]}      # (13c) never on: turned on
    note_cycle(fort(tools__seedwatch=True), m)
    note_cycle(fort(), m)
    assert "seedwatch" not in {x.action.get("name") for x in plan(fort(), m)[0]}


@test("review #11: failed settings section skips mandates and tools")
def _():
    s = fort(mandates=[{"kind": "Make", "item": "STATUE", "remaining": 3}])
    r = rules(plan(s, Memory())[0])
    assert "mandate" in r and "tools" in r, r              # (13c) with the settings read: both come up
    s["settings"] = {"error": "boom"}
    r = rules(plan(s, Memory())[0])
    assert "mandate" not in r and "tools" not in r, r


@test("review #13: daily order counts survive pruning (numeric day keys)")
def _():
    s = fort(stocks__drink=10)
    m = Memory(orders_by_day={str(game_day(s) - k): 1 for k in range(1, 9)})
    record([(plan(s, m)[0][0], {"ok": True})], s, m)
    assert m.orders_by_day.get(str(game_day(s))) == 1 and len(m.orders_by_day) <= 5


@test("plan() never changes memory")
def _():
    m = Memory(tools_enabled_by_ai=["seedwatch"])
    before = json.dumps(m.to_dict(), sort_keys=True)
    plan(fort(tools__seedwatch=True), m)
    plan(threat(fort()), m)
    assert json.dumps(m.to_dict(), sort_keys=True) == before


@test("strategist adjustments change the planner's targets (within its config keys only)")
def _():
    cfg = effective_config({"drink_per_dwarf": 30, "nonsense": 5, "max_order": True})
    assert cfg["drink_per_dwarf"] == 30 and "nonsense" not in cfg and cfg["max_order"] == 100
    s = fort(stocks__drink=3000)
    assert "drink" not in rules(plan(s, Memory())[0]) and "drink" in rules(plan(s, Memory(), cfg)[0])


# --- building (Phase 3) -------------------------------------------------------

def young_fort(**changes):
    """A fort with no rooms yet: few beds, no dining hall, no workshops or stockpiles."""
    s = fort(**changes)
    s["buildings"]["other"]["Bed"] = 20
    s["buildings"]["zones"]["DiningHall"] = 0
    # (0.100.1) the still, kitchen and carpenter's come before anything else
    # (tested on their own): this fort has them, and nothing more
    s["buildings"]["workshops"] = {"Still": 1, "Kitchen": 1, "Carpenters": 1}
    s["buildings"]["stockpiles"] = 0
    return s


def builds(p):
    # (a set piece comes up whenever a fed, quiet fort needs nothing else: tested on its own)
    return [x for x in p if x.rule == "build" and x.action.get("kind") != "garden"]


@test("building: too few beds -> one bedroom level, sized to the need, room size from Fort size")
def _():
    p, _ = plan(young_fort(), Memory())
    b = builds(p)
    assert len(b) == 1 and b[0].action["kind"] == "bedrooms", [x.action for x in b]
    assert b[0].action["rooms"] == 32 and b[0].action["room_size"] == 3
    s = young_fort()
    s["settings"]["traits"] = {"size": 80}
    assert builds(plan(s, Memory())[0])[0].action["room_size"] == 4


@test("building: beds already planned in an open project count")
def _():
    s = young_fort()
    s["buildings"]["other"]["Bed"] = 180
    b = builds(plan(s, Memory())[0])
    assert b and b[0].action["kind"] == "bedrooms", [x.action for x in b]      # (13c) without the project: one
    s["projects"]["open"] = [{"id": 1, "kind": "bedrooms", "phase": "dig", "summary": {"beds": 32},
                              "dig": {"total": 100, "dug": 10, "stuck": 0}}]
    b = builds(plan(s, Memory())[0])
    assert not b or b[0].action["kind"] != "bedrooms", [x.action for x in b]


@test("building: then dining hall, then workshops, then storage")
def _():
    s = young_fort()
    s["buildings"]["other"]["Bed"] = 400
    assert builds(plan(s, Memory())[0])[0].action["kind"] == "dining"
    s["buildings"]["zones"]["DiningHall"] = 1
    a = builds(plan(s, Memory())[0])[0].action
    assert a["kind"] == "workshops" and a["shops"] == ["Masons", "Craftsdwarfs", "Butchers"], a
    s["buildings"]["workshops"].update({w: 1 for w in a["shops"]})
    assert builds(plan(s, Memory())[0])[0].action["kind"] == "storage"


@test("building: the established test fort builds nothing")
def _():
    assert not builds(plan(fort(), Memory())[0])


@test("set pieces: a fed, quiet fort with hands to spare digs a statue garden named for it; not again for 2 years")
def _():
    from planner import good_times, garden_name, TICKS_PER_YEAR
    s = fort()
    s["fort"] = {"name": "Amalmebzuth, Teacheroar", "site_id": 1}
    s["settings"]["traits"] = {"grandeur": 50}
    m = Memory()
    g = [x for x in plan(s, m)[0] if x.rule == "build" and x.action.get("kind") == "garden"]
    assert g and g[0].action["name"] == "Amalmebzuth Teacheroar", g
    record([(g[0], {"ok": True})], s, m)
    g50 = {"grandeur": 50}
    assert m.gardens_built == ["Amalmebzuth Teacheroar"] and not good_times(s, m, g50, PLANNER_CONFIG)
    later = copy.deepcopy(s)
    later["date"]["year"] += 2
    assert good_times(later, m, g50, PLANNER_CONFIG) and garden_name(later, m) == "Amalmebzuth Teacheroar Second"
    assert not good_times(later, m, {}, PLANNER_CONFIG)                    # a plain fort builds none
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    assert not good_times(s, Memory(), g50, PLANNER_CONFIG)


@test("growth (0.104.85): a mature fort wants more taverns, libraries, hospitals, barracks as it grows and its sliders care")
def _():
    from planner import growth_want, growth_candidates, good_times
    assert growth_want("tavern", {}, 150, 0) == 2 and growth_want("tavern", {"outsiders": 100, "welfare": 100}, 150, 0) == 4
    assert growth_want("library", {}, 100, 0) == 0 and growth_want("library", {"craftsmanship": 100}, 100, 0) == 1
    assert growth_want("barracks", {"militarism": 100}, 100, 30) == 3 and growth_want("hospital", {}, 400, 0) == 2
    s = fort()
    s["fort"] = {"name": "Amalmebzuth, Teacheroar", "site_id": 1}
    s["dwarves"]["total"] = 150
    traits = {"grandeur": 50, "outsiders": 100}
    m = Memory()
    assert good_times(s, m, traits, PLANNER_CONFIG)
    c = growth_candidates(s, traits, PLANNER_CONFIG, m, {}, set(), {"INN_TAVERN": 1, "LIBRARY": 1, "HOSPITAL": 1},
                          {"Barracks": 0}, 150)
    kinds = {a["kind"]: (a, why) for a, why in c}
    assert set(kinds) == {"tavern"}, kinds                         # one library is enough for 150 at Craft 0
    a, why = kinds["tavern"]
    assert a["growth"] and "the fort wants 3" in why and "Outsiders +100" in why, why
    assert not growth_candidates(s, traits, PLANNER_CONFIG, m, {}, {"tavern"}, {"INN_TAVERN": 1}, {}, 150)   # one open
    assert not growth_candidates(s, traits, PLANNER_CONFIG, m, {}, set(), {"INN_TAVERN": 0}, {}, 150)        # the first: the ladder's
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    assert not growth_candidates(s, traits, PLANNER_CONFIG, m, {}, set(), {"INN_TAVERN": 1}, {}, 150)        # not in bad times


@test("growth (0.104.161, 14.1): a plain martial fort grows barracks, ranges and a prison in settled times; a devout one temples")
def _():
    from planner import growth_candidates, good_times, settled_times, growth_wait
    s = fort()
    s["dwarves"]["total"] = 200
    s["military"]["soldiers"] = 60
    s["military"]["squads"] = [{"id": 1, "members": 10, "ai_uniform": "crossbow"}]
    s["offices"] = {"offices": {"SHERIFF": {"held": [{"unit_id": 1}]}}}
    war = {"militarism": 150, "justice": 80, "grandeur": -40, "welfare": -40, "outsiders": -80, "piety": -30}
    m = Memory()
    assert settled_times(s, m, war, PLANNER_CONFIG) and not good_times(s, m, war, PLANNER_CONFIG)   # a plain fort
    locs = {"INN_TAVERN": 1, "LIBRARY": 1, "HOSPITAL": 1, "TEMPLE": 2}
    zones = {"Barracks": 1, "ArcheryRange": 1, "Dungeon": 2}
    c = {a["kind"]: (a, why) for a, why in growth_candidates(s, war, PLANNER_CONFIG, m, {}, set(), locs, zones, 200)}
    assert set(c) == {"barracks", "archery", "jail"}, c                      # no tavern or temple: it doesn't care
    assert c["jail"][0]["cells"] == 8 and "a prison" in c["jail"][1] and "Justice +80" in c["jail"][1], c["jail"]
    assert c["archery"][0]["lanes"] == 3
    # no crossbows: no second range; nobody to jail: no prison
    s2 = copy.deepcopy(s)
    s2["military"]["squads"] = [{"id": 1, "members": 10, "ai_uniform": "melee"}]
    s2["offices"] = {}
    assert {a["kind"] for a, _ in growth_candidates(s2, war, PLANNER_CONFIG, m, {}, set(), locs, zones, 200)} == {"barracks"}
    # the Rules tab's level switches still hold
    assert "jail" not in {a["kind"] for a, _ in growth_candidates(s, war, PLANNER_CONFIG, m, {"jail": False}, set(),
                                                                  locs, zones, 200)}
    # a devout fort: a grand temple to all gods, no barracks
    mon = {"piety": 150, "welfare": 80, "outsiders": 60, "grandeur": 60, "militarism": -60, "justice": -60}
    c = {a["kind"]: a for a, _ in growth_candidates(s, mon, PLANNER_CONFIG, m, {}, set(), locs, zones, 200)}
    assert "temple" in c and c["temple"]["size"] == "grand" and not {"barracks", "archery", "jail"} & set(c), c
    # a neutral fort, not in good times: nothing (its sliders don't ask)
    assert not growth_candidates(s, {}, PLANNER_CONFIG, m, {}, set(), locs, zones, 200)
    # one of a kind a season, and a lifetime cap (a count that never rises can't loop)
    a = {"type": "start_project", "kind": "barracks", "beds": 20, "growth": True}
    planner.record([(planner.Proposal("build", a, "x", 6), {"ok": True})], s, m)
    assert m.culture["growth_levels"]["barracks"]["n"] == 1 and growth_wait(m, "barracks", abs_tick(s), PLANNER_CONFIG)
    assert "barracks" not in {x["kind"] for x, _ in growth_candidates(s, war, PLANNER_CONFIG, m, {}, set(), locs, zones, 200)}
    later = abs_tick(s) + (PLANNER_CONFIG["growth_gap_days"] + 1) * TICKS_PER_DAY
    assert not growth_wait(m, "barracks", later, PLANNER_CONFIG)
    m.culture["growth_levels"]["barracks"]["n"] = PLANNER_CONFIG["growth_levels_max"]
    assert "built already" in growth_wait(m, "barracks", later, PLANNER_CONFIG)
    planner.record([(planner.Proposal("build", a, "x", 6), {"ok": False})], s, Memory())   # refused: not counted


@test("0.105.9 residency: closed forts decline, welcoming forts agree one as a probe, then on; gone visitors cleared")
def _():
    from planner import _residency_rule, record

    def st(outsiders, pending, residents=None, accept_visitors=True):
        s = fort()
        s["settings"]["traits"] = {"outsiders": outsiders}
        s["settings"]["accept_visitors"] = accept_visitors
        s["petitions"] = {"pending": pending, "orders": {}}
        if residents is not None:
            s["petitions"]["residents"] = residents
        return s

    def pet(i, unit=None, on_map=True):
        return {"id": i, "type": "Residency", "name": f"Bard {i}",
                "applicant": {"unit": unit, "on_map": on_map, "hf": i}}

    here = [pet(i, 100 + i) for i in range(1, 31)]
    # closed (Hermit hold): 25 declined at once
    props, notes = [], []
    m = Memory()
    _residency_rule(st(-150, here), m, PLANNER_CONFIG, props, notes)
    assert len(props) == 1 and props[0].action["accept"] is False and len(props[0].action["ids"]) == 25, props
    # neutral: only the gone ones cleared
    props = []
    _residency_rule(st(0, here + [pet(99, None, on_map=False)]), Memory(), PLANNER_CONFIG, props, notes)
    assert len(props) == 1 and props[0].action["ids"] == [99] and props[0].action["accept"] is False, props
    props = []
    _residency_rule(st(0, here), Memory(), PLANNER_CONFIG, props, notes)
    assert not props
    # (0.105.11) by default a welcoming fort agrees to none (the flag leaves a guest): a note for you
    from planner import NEEDS_YOU
    props, notes0 = [], []
    _residency_rule(st(100, here, residents=[]), Memory(), PLANNER_CONFIG, props, notes0)
    assert not props and any(n.startswith(NEEDS_YOU) and "petitions screen" in n for n in notes0), notes0
    PLANNER_CONFIG["residency_accept_by_flag"] = True           # the probe path, should DF ever take it
    # welcoming: one agreed, then wait for it to show as a resident
    m = Memory()
    s = st(100, here, residents=[])
    props = []
    _residency_rule(s, m, PLANNER_CONFIG, props, notes)
    assert len(props) == 1 and props[0].action == {"type": "answer_petition", "id": 1, "accept": True,
                                                    "residency": True}, props
    record([(props[0], {"ok": True, "unit": 101})], s, m)
    assert m.residency["probe"]["unit"] == 101, m.residency
    props = []
    _residency_rule(st(100, here[1:], residents=[]), m, PLANNER_CONFIG, props, notes)
    assert not props and m.residency.get("works") is None
    # seen as a resident: a batch of 25 from now on (one action)
    props = []
    _residency_rule(st(100, here[1:], residents=[101]), m, PLANNER_CONFIG, props, notes)
    assert m.residency["works"] is True and len(props) == 1 and props[0].action["accept"] is True, props
    assert props[0].action["ids"] == list(range(2, 27)), props[0].action
    # a vampire is never agreed to
    m3 = Memory()
    m3.residency = {"works": True}
    vamp = dict(pet(50, 150), vampire=True)
    props = []
    _residency_rule(st(100, [vamp, pet(51, 151)], residents=[]), m3, PLANNER_CONFIG, props, [])
    assert props[0].action["ids"] == [51], props
    # never seen: a second probe, then no more agreed, and a note for you
    m2 = Memory()
    m2.residency = {"probe": {"id": 1, "unit": 101, "tick": 0}}
    s = st(100, here[1:], residents=[])
    s["date"]["tick"] += 10 * 1200
    props, notes = [], []
    _residency_rule(s, m2, PLANNER_CONFIG, props, notes)
    assert m2.residency.get("works") is None and m2.residency["tries"] == 1 and len(props) == 1, (m2.residency, props)
    m2.residency["probe"] = {"id": 2, "unit": 102, "tick": 0}
    props, notes = [], []
    _residency_rule(s, m2, PLANNER_CONFIG, props, notes)
    assert m2.residency["works"] is False and not props and any(n.startswith(NEEDS_YOU) for n in notes), notes
    # Outsiders -40: DF's orders still take guests, so nothing is declined (only the gone cleared)
    props = []
    _residency_rule(st(-40, here), Memory(), PLANNER_CONFIG, props, [])
    assert not props
    # the Rules switch "accept visitors" off: nothing agreed
    props = []
    _residency_rule(st(100, here, residents=[], accept_visitors=False), Memory(), PLANNER_CONFIG, props, [])
    assert not props
    PLANNER_CONFIG["residency_accept_by_flag"] = False


@test("petitions (0.104.161, 14.1): a fort that doesn't hold with a temple or guildhall declines it; a devout one agrees")
def _():
    from planner import petition_lean
    temple = {"type": "Location", "id": 7, "loc": "TEMPLE", "deity_hf": 77, "deity": "Teshkad", "tier": 1}
    guild = {"type": "Location", "id": 8, "loc": "GUILDHALL", "profession": "MINER", "tier": 1}
    war = {"militarism": 150, "piety": -30, "welfare": -40}
    mon = {"piety": 150, "welfare": 80, "craftsmanship": 40, "industriousness": -20, "trade": -30}
    assert petition_lean(temple, war)[0] == -40 and petition_lean(guild, war)[0] == -60
    assert petition_lean(temple, mon)[0] > 100 and petition_lean(guild, mon)[0] > 0
    assert petition_lean(temple, {})[0] == 0 and "Piety -30" in petition_lean(temple, war)[1]

    def answers(traits, wishes):
        s = fort()
        s["settings"]["traits"] = traits
        s["petitions"] = {"pending": [copy.deepcopy(w) for w in wishes]}
        return [p for p in plan(s, Memory())[0] if p.action.get("type") == "answer_petition"]
    a = answers(war, [temple])
    assert len(a) == 1 and a[0].action["accept"] is False and a[0].action["id"] == 7 and "decline" in a[0].reason, a
    assert answers(war, [guild])[0].action["accept"] is False
    assert answers(mon, [temple])[0].action["accept"] is True and answers(mon, [guild])[0].action["accept"] is True
    assert answers({}, [temple])[0].action["accept"] is True                     # neutral: as before
    m = Memory()
    planner.record([(a[0], {"ok": True, "declined": True})], fort(), m)
    assert not m.wishes_agreed                                                    # a decline is no promise


@test("the keep: Surface 50+ builds walls round the way in, then a roof, a step at a time; waits while work is left")
def _():
    from planner import _keep_rule
    cfg = dict(PLANNER_CONFIG)

    def run(s, traits):
        p, n = [], []
        _keep_rule(s, cfg, 30, traits, p, n)
        return p, n
    s = fort()
    s["stocks"]["boulders"] = 500
    assert not run(s, {"surface": 40})[0]                                  # not asked for
    p, _n = run(s, {"surface": 60})
    assert p and p[0].action == {"type": "place_keep"} and "keep" in p[0].reason, p
    s["buildings"]["keep"] = {"stage": "walls", "walls_planned": 12}
    p, n = run(s, {"surface": 60})
    assert not p and any("12 wall tile" in x for x in n), n
    s["buildings"]["keep"] = {"stage": "walls", "walls_planned": 0}
    p, _n = run(s, {"surface": 60})
    assert p and "roof" in p[0].reason, p
    s["buildings"]["keep"] = {"stage": "done"}
    assert not run(s, {"surface": 60})[0]
    s["buildings"].pop("keep")
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 2
    assert not run(s, {"surface": 60})[0]                                   # not with enemies about
    s = fort()
    s["settings"]["traits"] = {"surface": 60}
    s["stocks"]["boulders"] = 500
    assert any(x.rule == "keep" for x in plan(s, Memory())[0])
    _p, notes = plan(s, Memory())
    assert not any("isn't supported yet" in x for x in notes)


@test("Deep mine (0.105.23): Surface -100 drops the keep (Sky-reachers too) and the surface farm; levels get a ceiling")
def _():
    from planner import _deep_surface_filter, _keep_rule, Proposal
    cfg = dict(PLANNER_CONFIG)
    s = fort()
    s["stocks"]["boulders"] = 500
    m = Memory()
    m.culture = {"quirks": {"sky_reachers": {"earned": True}}}
    m.atlas = {"entrances": {"10,10,168": {"kind": "surface", "elevation": 68}}}
    deep = {"surface": -100}
    # the keep: never, whatever the quirks
    p, n = [], []
    _keep_rule(s, cfg, 30, deep, p, n, m)
    assert not p, p
    props = [Proposal("keep", {"type": "place_keep"}, "k", 7),
             Proposal("surface_farm", {"type": "farm_plots", "tiles": 20, "dig": False, "outside": True}, "f", 2),
             Proposal("farms", {"type": "farm_plots", "tiles": 30, "dig": True, "outside": True}, "f", 2),
             Proposal("build", {"type": "start_project", "kind": "bedrooms", "rooms": 4}, "b", 6),
             Proposal("depot", {"type": "place_surface", "kind": "depot"}, "no trade depot", 6),
             Proposal("refuse", {"type": "place_surface", "kind": "refuse"}, "r", 5),
             Proposal("pasture", {"type": "make_pasture", "tiles": 40}, "p", 5)]
    notes = []
    out = _deep_surface_filter(s, deep, m, props, notes)
    rules = [x.rule for x in out]
    assert rules == ["farms", "build", "depot", "refuse", "pasture"], rules
    farms = out[0].action
    assert "outside" not in farms and farms["max_elev"] == 67 and farms["dig"], farms
    assert out[1].action["max_elev"] == 67, out[1].action                # one under the surface (68)
    # (0.105.23) the depot goes underground, down a wagon road the bridge digs
    assert out[2].action == {"type": "deep_depot"} and "wagon road" in out[2].reason, (out[2].action, out[2].reason)
    assert any("nothing above ground" in x for x in notes), notes
    # a fresh embark before its first stair may still farm under the sky
    s2 = fort()
    s2["founding"] = {"stairs": False}
    props = [Proposal("farms", {"type": "farm_plots", "tiles": 30, "outside": True}, "f", 2)]
    assert _deep_surface_filter(s2, deep, m, props, [])[0].action.get("outside") is True
    # Surface 0 and the Garden fort: untouched
    props = [Proposal("keep", {"type": "place_keep"}, "k", 7),
             Proposal("build", {"type": "start_project", "kind": "bedrooms", "rooms": 4}, "b", 6)]
    for t in ({"surface": 0}, {"surface": 80}):
        out = _deep_surface_filter(s, t, m, list(props), [])
        assert [x.rule for x in out] == ["keep", "build"] and "max_elev" not in out[1].action, out
    # through plan(): no keep, a Deep mine's levels carry the ceiling
    s3 = fort()
    s3["settings"]["traits"] = {"surface": -100, "verticality": 120}
    s3["stocks"]["boulders"] = 500
    got, _n = plan(s3, m)
    assert not any(x.rule == "keep" for x in got)
    assert all(x.action.get("max_elev") == 67 for x in got if x.action.get("type") == "start_project"), \
        [x.action for x in got if x.action.get("type") == "start_project"]


@test("Deep mine (0.105.23): the trade depot goes underground down a wagon road; notes while dug; the surface depot when no road; Needs you when wagons can't reach it")
def _():
    from planner import _deep_surface_filter, _deep_depot_watch, _surface_basics, Proposal, NEEDS_YOU
    m = Memory()
    deep = {"surface": -100}
    def depot():
        return [Proposal("depot", {"type": "place_surface", "kind": "depot"}, "no trade depot", 6)]
    s = fort()
    # no road begun: the underground depot
    out = _deep_surface_filter(s, deep, m, depot(), [])
    assert out[0].action == {"type": "deep_depot"} and out[0].rule == "depot" and out[0].priority == 6, out
    # every other preset keeps the surface depot
    for t in ({"surface": 0}, {"surface": -79}, {"surface": 80}):
        out = _deep_surface_filter(s, t, m, depot(), [])
        assert out[0].action == {"type": "place_surface", "kind": "depot"}, (t, out)
    # being dug: a note, nothing asked
    s["buildings"]["deep_depot"] = {"stage": "digging", "tiles_left": 40, "stalled": 0}
    notes = []
    assert _deep_surface_filter(s, deep, m, depot(), notes) == []
    assert any("40 tile(s)" in n for n in notes), notes
    # designations lost: asked again (the bridge marks them again)
    s["buildings"]["deep_depot"] = {"stage": "digging", "tiles_left": 40, "stalled": 3}
    out = _deep_surface_filter(s, deep, m, depot(), [])
    assert out[0].action == {"type": "deep_depot"} and "mark them again" in out[0].reason, out
    # dug: place the depot
    s["buildings"]["deep_depot"] = {"stage": "digging", "tiles_left": 0, "stalled": 0}
    out = _deep_surface_filter(s, deep, m, depot(), [])
    assert out[0].action == {"type": "deep_depot"} and "place the depot" in out[0].reason, out
    # no road down: the depot at the way in, with a note
    s["buildings"]["deep_depot"] = {"stage": "no_road", "why": "an aquifer under the road's start"}
    notes = []
    out = _deep_surface_filter(s, deep, m, depot(), notes)
    assert out[0].action == {"type": "place_surface", "kind": "depot"} and "at the way in" in out[0].reason, out
    assert any("no wagon road down (an aquifer" in n for n in notes), notes
    # the depot rule itself: none while a depot stands (the underground one included)
    s2 = fort()
    s2["buildings"]["other"] = {"TradeDepot": 1}
    p = []
    _surface_basics(s2, dict(PLANNER_CONFIG), 30, p)
    assert not any(x.rule == "depot" for x in p), p
    # built: what the game says of the wagons
    s3 = fort()
    s3["buildings"]["deep_depot"] = {"stage": "placed", "depot": "built", "wagon_access": False,
                                     "x": 60, "y": 45, "elevation": 79}
    notes = []
    _deep_depot_watch(s3, notes)
    assert len(notes) == 1 and not notes[0].startswith(NEEDS_YOU) and "can't reach" in notes[0] \
        and "pack animals" in notes[0], notes                             # (0.105.35) a note of what goes on
    for ok in (True, None):
        s3["buildings"]["deep_depot"]["wagon_access"] = ok
        notes = []
        _deep_depot_watch(s3, notes)
        assert notes == [], notes
    s3["buildings"]["deep_depot"] = {"stage": "placed", "depot": "building", "wagon_access": False}
    notes = []
    _deep_depot_watch(s3, notes)
    assert notes == []
    # through plan(): a Deep mine with no depot asks for the underground one
    s4 = fort()
    s4["settings"]["traits"] = {"surface": -100}
    s4["buildings"]["other"].pop("TradeDepot", None)
    got, _n = plan(s4, m)
    dep = [x for x in got if x.rule == "depot"]
    assert [x.action for x in dep] == [{"type": "deep_depot"}], [x.action for x in dep]
    s4["settings"]["traits"] = {"surface": 0}
    got, _n = plan(s4, m)
    assert [x.action for x in got if x.rule == "depot"] == [{"type": "place_surface", "kind": "depot"}]


@test("Deep mine (0.105.23): a bridge over the water only to reach the map's edge, never the wider one")
def _():
    from planner import _crossing_rule
    cfg = dict(PLANNER_CONFIG)
    s = fort()
    s["stocks"]["wood"] = 100
    far = {"trees": 80, "shrubs": 40, "grass": 400, "edge": False}
    s["crossings"] = {"near": {"trees": 2, "shrubs": 1, "grass": 10, "edge": True},
                      "crossings": [{"x": 5, "y": 5, "z": 160, "dir": "e", "len": 3, "width": 1, "far_side": far}]}
    def run(t):
        p, n = [], []
        _crossing_rule(s, cfg, 30, t, p, n)
        return p
    assert run({"surface": 0}), "a fort reaches its trees"
    assert not run({"surface": -100}), "the Deep mine needs no trees over the water"
    far["edge"], s["crossings"]["near"]["edge"] = True, False
    assert run({"surface": -100}), "the caravans' way to the map's edge"


@test("overnight loops: no new order of a recipe whose AI order stands still; empty polish backs off; depot reset only if the AI opened it")
def _():
    from planner import Proposal, note_refusal, refusal_key, TICKS_PER_DAY
    s = fort()
    now = abs_tick(s)
    m = Memory()
    m.order_watch = {"5": {"what": "brew_drink", "left": 10, "since": now - 9 * TICKS_PER_DAY, "by_ai": True}}
    p = Proposal("drink", {"type": "work_order", "recipe": "brew_drink", "amount": 10}, "x", 3, True)
    allowed, held = select([p], s, m, dict(PLANNER_CONFIG))
    assert not allowed and "hasn't moved in 9 days" in held[0], held
    m.order_watch["5"]["since"] = now - 2 * TICKS_PER_DAY
    assert select([p], s, m, dict(PLANNER_CONFIG))[0]
    pol = Proposal("polish", {"type": "polish"}, "x", 7)
    note_refusal(m, pol, {"ok": True, "designated": 0, "note": "nothing there could be smoothed"}, now)
    assert m.refusals[refusal_key(pol)]["n"] == 1
    s2 = fort()
    s2["trade"] = {"depot": True, "caravans": [], "trader": {"anyone": True, "anyone_by_ai": False}}
    assert not any(x.rule == "call_trader" for x in plan(s2, Memory())[0])
    s2["trade"]["trader"]["anyone_by_ai"] = True
    assert any(x.rule == "call_trader" for x in plan(s2, Memory())[0])
    s3 = fort()
    s3["trade"] = {"depot": True, "caravans": [{"civ": "X", "state": "AtDepot"}],
                   "trader": {"at_depot": True, "can_open": True, "fresh": True},
                   "screen": {"open": True, "by_ai": True, "ready": False, "unloading": True}}
    c = [x for x in plan(s3, Memory())[0] if x.rule == "close_trade"]
    assert c and c[0].action == {"type": "close_trade", "unloading": True}, c


@test("overnight 2: the soap maker's counts under its raws name; a workshop level isn't started a third time; polish waits for a new level")
def _():
    from planner import _has_shop, Proposal
    assert _has_shop({"workshops": {"Custom:SOAP_MAKER": 3}}, "SoapMaker")
    s = fort()
    m = Memory()
    p = Proposal("soap", {"type": "start_project", "kind": "workshops", "shops": ["SoapMaker"]}, "x", 5)
    for _ in range(2):
        m.last_fired.clear()
        record([(p, {"ok": True})], s, m)
    m.last_fired.clear()
    allowed, held = select([p], s, m)
    assert not allowed and "started twice" in held[0], held
    pol = Proposal("polish", {"type": "polish"}, "x", 7)
    record([(pol, {"ok": False, "rejected": True, "error": "every finished level is polished"})], s, m)
    assert m.polished_upto == s["projects"]["finished"]
    s["dwarves"]["idle_adults"] = s["dwarves"]["adults"]
    assert not [x for x in plan(s, m)[0] if x.rule == "polish"]
    s["projects"]["finished"] = (s["projects"]["finished"] or 0) + 1
    m.refusals.clear()
    assert [x for x in plan(s, m)[0] if x.rule == "polish"]


@test("contentment: trinkets for dwarves who want to own things (crafts made when none), more craft shops, extra soap makers down")
def _():
    def by_rule(props, rule):
        return [p for p in props if p.rule == rule]
    s = fort()
    s["orders"] = []
    s["projects"]["open"] = []
    s["needs"] = {"needs": {"AcquireObject": {"distracted": 40}, "CraftObject": {"distracted": 35}},
                  "idle_crafting": {"enabled": True, "workshops": 1}, "craft_shops": 1, "trinkets": 12}
    props = plan(s, Memory())[0]
    t = by_rule(props, "needs_trinkets")
    assert t and t[0].action == {"type": "give_trinkets", "max": 25}, t
    sh = by_rule(props, "needs_shops")
    assert sh and sh[0].action["shops"] == ["Craftsdwarfs"] * 4, sh                   # 1 + 35 // 8 = 5 wanted (0.104.53)
    s["needs"]["trinkets"] = 0
    t = by_rule(plan(s, Memory())[0], "trinket_orders")
    assert t and t[0].action["recipe"] == "stone_crafts" and t[0].action["amount"] == 20, t
    s["settings"]["give_trinkets"] = False
    assert not by_rule(plan(s, Memory())[0], "trinket_orders")
    s["needs"]["craft_shops"] = 5
    props = plan(s, Memory())[0]
    assert not by_rule(props, "needs_shops")
    assert by_rule(props, "needs_craft")                                  # 5 shops, idle crafting at 1
    s["buildings"]["workshops"]["Custom:SOAP_MAKER"] = 116
    x = by_rule(plan(s, Memory())[0], "excess_shops")
    assert x and x[0].action == {"type": "remove_workshops", "kind": "SoapMaker", "keep": 1, "max": 20}, x


@test("soldiering for dwarves who long to fight: more soldiers wanted, capped; none at the lowest Militarism")
def _():
    from planner import soldiers_wanted
    s = fort()
    base = soldiers_wanted(s, 100, PLANNER_CONFIG)
    s["needs"] = {"needs": {"Fight": {"distracted": 75}, "MartialTraining": {"distracted": 73}}}
    more = soldiers_wanted(s, 100, PLANNER_CONFIG)
    assert base <= more <= base + 3, (base, more)          # (0.105.10) Militarism 0: near its 10%
    s["settings"]["traits"] = {"militarism": 20}
    calm100 = soldiers_wanted({**s, "needs": {}}, 100, PLANNER_CONFIG)
    more = soldiers_wanted(s, 100, PLANNER_CONFIG)
    assert more > calm100 and more <= max(calm100, 30), (calm100, more)
    s["settings"]["traits"] = {"militarism": -100}
    assert soldiers_wanted(s, 100, PLANNER_CONFIG) == soldiers_wanted({**s, "needs": {}}, 100, PLANNER_CONFIG)


@test("soldiering (0.104.61): a quarter of the fort badly wanting to train lifts the cap as idle hands do")
def _():
    from planner import soldiers_wanted
    s = fort()
    s["needs"] = {"needs": {"Fight": {"distracted": 38, "badly": 13}, "MartialTraining": {"distracted": 54, "badly": 10}}}
    s["dwarves"].update(adults=88, idle_adults=10)
    s["settings"]["traits"] = {"militarism": 60}                      # (0.105.10) a keen fort's extra
    calm = soldiers_wanted(s, 93, PLANNER_CONFIG)
    assert calm <= round(93 * PLANNER_CONFIG["fight_share_max"]), calm
    s["needs"]["needs"]["MartialTraining"]["badly"] = 30                # 32% badly
    keen = soldiers_wanted(s, 93, PLANNER_CONFIG)
    assert calm < keen <= round(93 * PLANNER_CONFIG["idle_fight_share_max"]), (calm, keen)


@test("soldiering (0.105.2): a peaceful fort drafts fewer for the needs; enough civilians always kept")
def _():
    from planner import soldiers_wanted
    s = fort()
    s["needs"] = {"needs": {"Fight": {"distracted": 40, "badly": 30}, "MartialTraining": {"distracted": 50, "badly": 30}}}
    s["dwarves"].update(adults=68, idle_adults=39)                      # Monastery, 2 Nov
    s["settings"]["traits"] = {"militarism": 0}
    at0 = soldiers_wanted(s, 70, PLANNER_CONFIG, True)
    s["settings"]["traits"] = {"militarism": -60}
    at60 = soldiers_wanted(s, 70, PLANNER_CONFIG, True)
    s["settings"]["traits"] = {"militarism": 100}
    at100 = soldiers_wanted(s, 70, PLANNER_CONFIG, True)
    # (0.105.10) an eighth of the extra at 0, all of it at +100, almost none at -60
    assert at60 < at0 < at100, (at60, at0, at100)
    assert at0 <= round(70 * 0.15), at0                               # near its 10% (7) at Militarism 0
    # War-hold: Militarism 150 with Extreme, 36 adults: 12 kept at work (it drafted 29)
    s = fort()
    s["settings"]["traits"] = {"militarism": 150}
    s["settings"]["extreme"] = ["militarism"]
    s["dwarves"].update(adults=36, idle_adults=1)
    from planner_military import soldier_share
    share = soldier_share(s, PLANNER_CONFIG)
    assert soldiers_wanted(s, 39, PLANNER_CONFIG) == 36 - 12
    s["settings"]["traits"] = {"militarism": 200}                       # 90%: a big fort keeps 30%
    s["dwarves"]["adults"] = 200
    assert soldiers_wanted(s, 200, PLANNER_CONFIG) == 200 - 60
    s["settings"]["traits"] = {"militarism": 150}
    s["dwarves"].pop("adults")                                          # no count: the slider alone
    assert soldiers_wanted(s, 40, PLANNER_CONFIG) == round(40 * share)


@test("idle hands (0.83/0.84): a running average; from 40% every squad trains and more soldiers join; off under 25%")
def _():
    from planner import soldiers_wanted, idle_hands, update_idle
    s = fort()
    s["needs"] = {"needs": {"Fight": {"distracted": 78}, "MartialTraining": {"distracted": 76}}}
    s["dwarves"].update(adults=90, idle_adults=39)                      # 43% idle
    m = Memory()
    update_idle(s, m, PLANNER_CONFIG)
    assert idle_hands(s, m, PLANNER_CONFIG) and m.idle_hands and m.idle_avg == round(39 / 90, 4)
    busy = soldiers_wanted(s, 100, PLANNER_CONFIG)
    idle = soldiers_wanted(s, 100, PLANNER_CONFIG, True)
    assert idle > busy and idle <= 45, (busy, idle)
    s["dwarves"]["idle_adults"] = 9                                     # one quiet reading: the average holds
    update_idle(s, m, PLANNER_CONFIG)
    assert idle_hands(s, m, PLANNER_CONFIG) and 0.38 < m.idle_avg <= 0.401, m.idle_avg
    for _ in range(20):                                                 # busy for a while: off
        update_idle(s, m, PLANNER_CONFIG)
    assert not idle_hands(s, m, PLANNER_CONFIG) and m.idle_avg < 0.25
    s["dwarves"]["idle_adults"] = 27                                    # 30%: below 40 from below, stays off
    for _ in range(40):
        update_idle(s, m, PLANNER_CONFIG)
    assert not idle_hands(s, m, PLANNER_CONFIG)
    # plan() itself never changes the memory (note_cycle does the bookkeeping)
    before = m.idle_avg
    plan(s, m)
    assert m.idle_avg == before


@test("cavern well: the AI decides: only with no ordinary spot, a real need, and nothing dangerous about")
def _():
    s = fort()
    s["buildings"]["other"].pop("Well", None)
    s["projects"]["open"] = []
    s["dwarves"]["needs_medical_care"] = 0
    s["stocks"]["drink"] = 194 * 20
    s["military"]["soldiers"] = 0
    m = Memory()
    m.well_failure = "no open drop from a free floor inside the fort to clean water (the water below is in a cavern)"
    w = [p for p in plan(s, m)[0] if p.rule == "well"]
    assert w and not w[0].action.get("cavern"), w                       # no need: the ordinary try again
    s["dwarves"]["needs_medical_care"] = 2
    w = [p for p in plan(s, m)[0] if p.rule == "well"]
    # (0.104.13) the injured waiting: urgent (an urgent slot, dug first)
    assert w and w[0].action == {"type": "place_well", "cavern": True, "urgent": True, "gallery": 80} and "injured" in w[0].reason, w
    assert w[0].priority == 1 and "stair" in w[0].reason, w
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    props, notes = plan(s, m)
    assert not any(p.action.get("cavern") for p in props if p.rule == "well")
    assert any("cavern well would help" in n for n in notes), notes
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    record([(w[0], {"ok": False, "error": "no floor inside the fort over cavern water with solid rock between; no gallery to the cavern water at x135 y131 elevation 7 (its nearest column is 81 tiles from the dwarves; a gallery reaches 40)"})], s, m)
    assert m.cavern_well_failure.startswith("no floor")
    m.last_fired.clear()
    assert not any(p.action.get("cavern") for p in plan(s, m)[0] if p.rule == "well")


def _body():
    def plan_(st):
        return plan(st, Memory())[0]
    s = fort()
    s["projects"]["open"] = []
    cplan = {"elevation": 40, "source": "cavern lake", "tunnel": 6}
    s["water"] = {"tick": abs_tick(s), "bodies": [{"kind": "surface", "tiles": 300, "stagnant_share": 100}],
                  "cistern": cplan}
    c = [p for p in plan_(s) if p.rule == "cistern"]
    assert c and c[0].action["type"] == "cistern_step" and "stagnant" in c[0].reason, c
    s["water"]["bodies"][0]["stagnant_share"] = 0
    assert not [p for p in plan_(s) if p.rule == "cistern"]                 # good water already
    s["settings"]["water_works"] = False
    s["water"]["bodies"][0]["stagnant_share"] = 100
    assert not [p for p in plan_(s) if p.rule == "cistern"]                 # switched off
    s["settings"]["water_works"] = True
    s["water"]["cistern_status"] = {"v": 2, "stage": "filling", "depth": 3, "gate": "open"}
    props, notes = plan(s, Memory())
    assert [p for p in props if p.rule == "cistern"] and any("filling, 3/7" in n for n in notes), notes
    s["water"]["cistern_status"] = {"v": 2, "stage": "done", "depth": 7, "gate": "shut"}
    assert not [p for p in plan_(s) if p.rule == "cistern"]
    s["water"]["cistern_status"] = {"v": 2, "stage": "done", "depth": 2, "gate": "shut"}
    assert [p for p in plan_(s) if p.rule == "cistern"]


@test("cistern: started when the fort's water is poor (stagnant, freezing, none), stepped while building, kept topped up")
def _():
    PLANNER_CONFIG["cistern_hold"] = False      # (0.104.144) the design under the hold
    try:
        _body()
    finally:
        PLANNER_CONFIG["cistern_hold"] = False


@test("temperament (0.94): every slider says what it does now, in the planner's own numbers")
def _():
    import temperament
    from weights import TRAIT_NAMES
    s = fort()
    s["settings"]["traits"] = {"militarism": 150, "growth": 200, "industriousness": -100, "welfare": 60}
    e = temperament.effects(s)
    assert set(e) == set(TRAIT_NAMES), set(TRAIT_NAMES) ^ set(e)
    assert all(isinstance(v, str) and 0 < len(v) <= 140 for v in e.values()), e
    assert e["militarism"].startswith("65% of citizens") and e["growth"] == "no population cap; DF's cap set to it", e
    assert e["industriousness"].startswith("stone left where it's dug") and "lavish" in e["welfare"], e


def _body():
    s = fort()
    s.setdefault("water", {})["cistern_status"] = {
        "v": 2, "stage": "building", "gate": "planned", "lever": "planned",
        "floodgates_free": 0, "floodgates_reserved": 0, "mechanisms_free": 0, "mechanisms_reserved": 0}
    parts = lambda: [p for p in plan(copy.deepcopy(s), Memory())[0] if p.rule == "cistern_parts"]
    got = {p.action["recipe"]: p.action["amount"] for p in parts()}
    assert got == {"stone_floodgate": 1, "mechanisms": 3}, got
    assert all(p.is_order for p in parts())
    s["water"]["cistern_status"]["floodgates_reserved"] = 1          # one on its way to the job
    s["water"]["cistern_status"]["mechanisms_free"] = 3
    assert not parts()
    s["water"]["cistern_status"].update(floodgates_reserved=0, mechanisms_free=0)
    s["orders"] = list(s.get("orders") or []) + [
        {"recipe": "stone_floodgate", "amount_left": 1, "amount_total": 1},
        {"recipe": "mechanisms", "amount_left": 3, "amount_total": 3}]
    assert not parts()                                               # queued already
    s["orders"] = []
    s["water"]["cistern_status"].update(stage="linking", gate="shut", lever="built", mechanisms_free=1)
    got = {p.action["recipe"]: p.action["amount"] for p in parts()}
    assert got == {"mechanisms": 1}, got                             # the link takes 2
    # (0.94.1) region2: building, lever built, the link short: what holds the others is said
    s["water"]["cistern_status"].update(stage="building", mechanisms_free=0,
                                        mechanisms_held={"held in a Workshop": 2})
    ps = parts()
    assert ps and ps[0].action["amount"] == 2 and "2 held in a Workshop" in ps[0].reason, [p.reason for p in ps]
    s["water"]["cistern_status"] = {"v": 2, "stage": "filling", "depth": 3, "gate": "open"}
    assert not parts()                                               # older bridges: no counts


@test("cistern parts (0.92.1): a floodgate and mechanisms ordered while the floodgate and lever wait for them")
def _():
    PLANNER_CONFIG["cistern_hold"] = False      # (0.104.144) the design under the hold
    try:
        _body()
    finally:
        PLANNER_CONFIG["cistern_hold"] = False


@test("crops for drink (0.99.6): brewable crops favoured while drink is short, put back once it recovers; shrubs gathered")
def _():
    from planner import Proposal
    s = fort()
    s["dwarves"]["total"] = 243
    s["stocks"].update(drink=42, plants=151, plant_growths=325)
    s.setdefault("supplies", {}).update(brewable_plants=18, brewable_growths=0)
    s["farms"] = {"plots": 10, "built": 10, "tiles": 116, "season": "spring", "crops": {
        "MUSHROOM_HELMET_PLUMP": {"name": "plump helmet", "seeds": 0, "stock": 2, "brews": "plant"},
        "GRASS_TAIL_PIG": {"name": "pig tail", "seeds": 30, "stock": 10, "brews": "plant"},
        "BUSH_QUARRY": {"name": "quarry bush", "seeds": 80, "stock": 90, "brews": None},
        "CHERRY": {"name": "cherry tree", "seeds": 2, "brews": "growth", "seasons": []}}}
    s["labor"] = {**(s.get("labor") or {}), "shrubs": 500, "gather_marked": 0}
    s["farms"].update(plots_underground=10, plots_surface=0)
    s["farms"]["crops"]["MUSHROOM_HELMET_PLUMP"].update(seeds=25, underground=True)
    s["farms"]["crops"]["TURNIP"] = {"name": "turnip plant", "seeds": 79, "brews": "plant", "underground": False}
    m = Memory()
    props, notes = plan(copy.deepcopy(s), m)[:2]
    sf = [p for p in props if p.rule == "surface_farm"]
    assert sf and sf[0].action == {"type": "farm_plots", "tiles": 60, "dig": False, "outside": True}, sf
    s["farms"]["crops"].pop("TURNIP")
    s["farms"]["crops"]["MUSHROOM_HELMET_PLUMP"]["seeds"] = 0
    props, notes = plan(copy.deepcopy(s), m)[:2]
    crops = [p for p in props if p.rule == "crops"]
    assert crops and crops[0].action == {"type": "farm_thresholds", "steer": "drink",
                                         "thresholds": {"GRASS_TAIL_PIG": 300, "BUSH_QUARRY": 10}}, crops
    assert [p for p in props if p.rule == "gather"], "thirsty: shrubs gathered"
    record([(crops[0], {"ok": True})], s, m)
    assert m.farm_steer == "drink"
    assert not [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "crops"]     # steered already
    s["stocks"]["drink"] = 1500                                                     # recovered
    back = [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "crops"]
    assert back and set(back[0].action["thresholds"].values()) == {50} and back[0].action["steer"] == "", back
    s["stocks"]["drink"] = 42
    for c in s["farms"]["crops"].values():
        if c["brews"]:
            c["seeds"] = 0
    props, notes = plan(copy.deepcopy(s), Memory())[:2]
    assert not [p for p in props if p.rule == "crops"] and any("no seeds of a crop a still can brew" in n for n in notes)


@test("kitchen (0.100): cooking brewables is banned while drink is short, lifted once drink recovers")
def _():
    s = fort()
    s["dwarves"]["total"] = 243
    s["stocks"].update(drink=42)
    s.setdefault("supplies", {}).update(brewable_plants=18, brewable_growths=0)
    m = Memory()
    k = [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "kitchen"]
    assert k and k[0].action == {"type": "kitchen_brewables", "ban": True}, k
    record([(k[0], {"ok": True})], s, m)
    assert m.kitchen_ban is True
    assert not [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "kitchen"]     # banned already
    s["stocks"]["drink"] = 500                                                       # not short, not recovered
    assert not [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "kitchen"]
    s["stocks"]["drink"] = 1500                                                      # recovered
    back = [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "kitchen"]
    assert back and back[0].action == {"type": "kitchen_brewables", "ban": False}, back
    record([(back[0], {"ok": True})], s, m)
    assert m.kitchen_ban is False
    assert Memory.from_dict(m.to_dict()).kitchen_ban is False


@test("0.105.16 kitchen: meals to spare and drink under its target keep the ban; lifted once drink meets it or meals thin")
def _():
    s = fort()
    s["dwarves"]["total"] = 46
    s["stocks"].update(drink=198, prepared_meals=2802)                # B at 23:33: 4.3 a dwarf, 62 meals a dwarf
    s.setdefault("supplies", {}).update(brewable_plants=60, brewable_growths=0)   # not "short": brewables in store
    m = Memory()
    m.kitchen_ban = True
    assert not [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "kitchen"], "not lifted"
    m.kitchen_ban = False
    k = [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "kitchen"]
    assert k and k[0].action["ban"] is True and "meals to spare" in k[0].reason, k
    m.kitchen_ban = True
    s["stocks"]["drink"] = 480                                         # 10.4 a dwarf: just over, inside the 20% margin
    assert not [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "kitchen"], "0.105.17: no flip at the target"
    s["stocks"]["drink"] = 600                                         # 13 a dwarf: over its target
    back = [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "kitchen"]
    assert back and back[0].action["ban"] is False, back
    s["stocks"].update(drink=198, prepared_meals=200)                  # meals thin: the old rule (recovered at 4)
    back = [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "kitchen"]
    assert back and back[0].action["ban"] is False, back


@test("one level of a kind a cycle (0.100): two workshops levels or two temples don't both start; a held one doesn't block")
def _():
    from planner import Proposal
    s = fort()
    ps = [Proposal("bottleneck", {"type": "start_project", "kind": "workshops", "shops": ["Still"]}, "x", 3),
          Proposal("needs_shops", {"type": "start_project", "kind": "workshops", "shops": ["Craftsdwarfs"]}, "x", 6),
          Proposal("petition_build", {"type": "start_project", "kind": "temple", "size": "shrine"}, "x", 4),
          Proposal("build", {"type": "start_project", "kind": "temple", "size": "temple"}, "x", 5),
          Proposal("drink", {"type": "work_order", "recipe": "brew_drink", "amount": 10}, "x", 1)]
    m = Memory()
    allowed, held = select(ps, s, m, dict(PLANNER_CONFIG, max_actions_per_cycle=10))
    assert [p.rule for p in allowed] == ["drink", "bottleneck", "petition_build"], [p.rule for p in allowed]
    assert any("needs_shops: one new workshops level" in h for h in held), held
    m.last_fired["bottleneck"] = abs_tick(s)                  # the most urgent waits for its cooldown...
    allowed, held = select(ps, s, m, dict(PLANNER_CONFIG, max_actions_per_cycle=10))
    assert "needs_shops" in [p.rule for p in allowed], (held, [p.rule for p in allowed])   # ...the next one goes


@test("rule guard (13c): one rule failing on an odd report value doesn't stop the cycle")
def _():
    import json as _json
    s = _json.loads((Path(__file__).parent / "fixtures" / "real" / "region2-0.83-y62-spring.json").read_text(encoding="utf-8"))
    s["buildings"]["workshops"]["Still"] = None                   # an odd value: _needs_rules used to raise
    s["stocks"]["drink"] = 0                                      # something else to do
    props, notes = plan(copy.deepcopy(s), Memory())[:2]
    # (0.105.33 merge) no rule fails on it any more (_bottleneck_rule did): the
    # guard is shown with a rule of the test's own that raises
    assert not [n for n in notes if n.startswith("rule _") and " failed (" in n], \
        [n for n in notes if "fail" in n]
    import planner as _planner
    real = _planner._bottleneck_rule

    def _bottleneck_rule(*a, **k):
        raise ValueError("the test's own odd value")
    _planner._bottleneck_rule = _bottleneck_rule
    try:
        props, notes = plan(copy.deepcopy(s), Memory())[:2]
    finally:
        _planner._bottleneck_rule = real
    assert any(n.startswith("rule _bottleneck_rule failed (ValueError") for n in notes), \
        [n for n in notes if "fail" in n]
    assert any(p.rule == "drink" for p in props), [p.rule for p in props]
    s2 = fort()
    del s2["dwarves"]                                             # a missing section: defaults, no crash
    plan(copy.deepcopy(s2), Memory())


@test("brew_recipe (13c): only what a still can brew (needs_drink ordered fruit that drink_fruit cancelled)")
def _():
    from planner import brew_recipe
    s = fort()
    s.setdefault("supplies", {}).update(brewable_plants=0, brewable_growths=0)
    s["stocks"].update(plants=0, plant_growths=325)
    assert brew_recipe(s) is None
    s["supplies"]["brewable_growths"] = 12
    assert brew_recipe(s) == "brew_drink_from_fruit"
    s["supplies"]["brewable_plants"] = 5
    assert brew_recipe(s) == "brew_drink_from_fruit"           # (0.105.23) more fruit than plants: the fruit
    s["supplies"]["brewable_plants"] = 12
    assert brew_recipe(s) == "brew_drink"
    del s["supplies"]["brewable_plants"]                     # an older bridge: the raw stocks
    s["stocks"]["plants"] = 3
    assert brew_recipe(s) == "brew_drink"


@test("drink (0.104.71; 0.105.26 no needs_drink): one brew in the cycle the drink rule brews")
def _():
    s = fort()
    s["stocks"].update(drink=10, plants=300)
    s["dwarves"]["total"] = 94
    s.setdefault("supplies", {}).update(brewable_plants=111, brewable_growths=0, empty_barrels=17, empty_pots=1)
    s.setdefault("needs", {}).setdefault("needs", {})["DrinkAlcohol"] = {"distracted": 14, "badly": 1}
    props = plan(s, Memory())[0]
    brews = [p for p in props if p.action.get("recipe") in ("brew_drink", "brew_drink_from_fruit")]
    assert len(brews) == 1 and brews[0].rule == "drink", [(p.rule, p.action) for p in brews]


@test("brewable (0.99.5): only fermentable plants and fruit are brewed; a fruit brew with none is cancelled")
def _():
    s = fort()
    s["stocks"].update(drink=116, plants=202, plant_growths=325)
    s["dwarves"]["total"] = 243
    s.setdefault("supplies", {}).update(brewable_plants=202, brewable_growths=0)
    s["orders"] = [{"id": 2095, "recipe": "brew_drink_from_fruit", "amount_left": 99, "amount_total": 100, "by_ai": True}]
    props = plan(copy.deepcopy(s), Memory())[0]
    got = {p.rule: p.action for p in props if p.rule in ("drink", "drink_fruit")}
    assert got.get("drink_fruit") == {"type": "cancel_work_order", "order_id": 2095}, got
    assert got.get("drink", {}).get("recipe") == "brew_drink", got     # plants still brew
    s["supplies"]["brewable_plants"] = 0
    s["orders"] = []
    props, notes = plan(copy.deepcopy(s), Memory())[:2]
    assert not [p for p in props if p.rule == "drink"] and any("a still can brew" in n for n in notes), notes
    s["supplies"]["brewable_growths"] = 40                              # real fruit: brewed
    got = [p.action["recipe"] for p in plan(copy.deepcopy(s), Memory())[0] if p.rule == "drink"]
    assert got == ["brew_drink_from_fruit"], got


@test("fishery (0.99.4): raw fish piling up and no fishery, whatever the fort's age: build one")
def _():
    s = fort()
    s["stocks"]["raw_fish"] = 7940
    s["buildings"]["workshops"].pop("Fishery", None)
    fish = lambda st: [p for p in plan(copy.deepcopy(st), Memory())[0] if p.rule == "fishery"]
    got = fish(s)
    assert got and got[0].action == {"type": "start_project", "kind": "workshops", "shops": ["Fishery"]}, got
    s["buildings"]["workshops"]["Fishery"] = 1
    assert not fish(s)
    s["buildings"]["workshops"].pop("Fishery")
    s["stocks"]["raw_fish"] = 10
    assert not fish(s)


@test("picks (0.99.4): stone short and few picks: forge more, copper before steel; none when there are enough")
def _():
    s = fort()
    s["dwarves"]["total"] = 228
    s["labor"] = {**(s.get("labor") or {}), "picks": 3, "soldier_picks": 0, "dig": 0}
    s["stone_use"] = {"economic": {}, "usable": 2}
    s.setdefault("military", {}).setdefault("gear", {})["bars"] = {"COPPER": 14, "IRON": 6, "STEEL": 58}
    s["buildings"].setdefault("workshops", {})["MetalsmithsForge"] = 2
    picks = lambda st: [p for p in plan(copy.deepcopy(st), Memory())[0] if p.rule == "picks"]
    got = picks(s)
    assert got and got[0].action == {"type": "work_order", "recipe": "metal_pick", "amount": 4,
                                     "material": "INORGANIC:COPPER"}, [p.action for p in got]
    s["labor"]["picks"] = 7
    assert not picks(s)
    s["labor"]["picks"] = 3
    s["orders"] = [{"recipe": "metal_pick", "amount_left": 4, "amount_total": 4, "by_ai": True}]
    assert not picks(s)
    # (0.104.117) stone plentiful but 88 tiles wait for 9 picks in a fort of 300: more picks, up to 20
    s["orders"] = []
    s["dwarves"]["total"] = 300
    s["stone_use"] = {"economic": {}, "usable": 400}
    s["stocks"]["boulders"] = 400
    s["labor"].update(picks=9, dig=88)
    got = picks(s)
    assert got and got[0].action["amount"] == 3, [p.action for p in got]      # 300/30 + 88/40 = 12
    s["labor"]["dig"] = 10
    assert not picks(s), "little waits: no picks"


@test("weapons and armour storage (0.99.12): the forge's products with no pile for them get one")
def _():
    from planner import full_stores, PLANNER_CONFIG as CONFIG
    s = fort()
    s.setdefault("logistics", {})["storage"] = {
        "weapons": {"tiles": 0, "used": 0, "loose": 13, "in_workshops": 10, "piles": 0},
        "armor": {"tiles": 0, "used": 0, "loose": 40, "in_workshops": 30, "piles": 0},
        "food": {"tiles": 900, "used": 500, "loose": 0}}
    kinds = full_stores(s, CONFIG)
    assert kinds[:2] == ["armor"] or set(kinds[:2]) == {"weapons", "armor"} or "armor" in kinds, kinds
    s["logistics"]["storage"]["armor"].update(tiles=100, used=10)     # a pile with room: nothing more
    assert "armor" not in full_stores(s, CONFIG)
    # (0.100) bolts lying about with no ammo pile: storage for them
    s["logistics"]["storage"]["ammo"] = {"tiles": 0, "used": 0, "loose": 60, "in_workshops": 20, "piles": 0}
    assert "ammo" in full_stores(s, CONFIG)


@test("crossbow squads keep crossbows (0.99.11): never turned to the AI's melee weapon; put back if they were")
def _():
    from planner import _uniform_weapon_rule
    rules_ = {"gear_weapon": "axe"}
    g = {"spare_weapons": {"ITEM_WEAPON_AXE_BATTLE": 30}}
    ranged = {"id": 56, "members": 10, "ai_uniform": "Crossbows, metal armor"}
    props = []
    _uniform_weapon_rule({}, g, [ranged], rules_, props)
    assert not props, [p.action for p in props]
    ranged["ai_uniform"] = "Crossbows, metal armor |weapon:ITEM_WEAPON_AXE_BATTLE"
    _uniform_weapon_rule({}, g, [ranged], rules_, props)
    assert props and props[0].action == {"type": "set_uniform_weapon", "squad_id": 56,
                                         "weapon": "ITEM_WEAPON_CROSSBOW"}, [p.action for p in props]
    melee = {"id": 55, "members": 10, "ai_uniform": "Melee, metal armor"}
    props = []
    _uniform_weapon_rule({}, g, [melee], rules_, props)
    assert props and props[0].action["weapon"] == "ITEM_WEAPON_AXE_BATTLE"


@test("workshops (0.99.4): a start that added a shop doesn't count toward 'twice'; more of a kind for a big fort")
def _():
    from planner import Proposal, shops_max, PLANNER_CONFIG as CONFIG
    s = fort()
    m = Memory()
    s["buildings"].setdefault("workshops", {})["Craftsdwarfs"] = 1
    p = Proposal("needs_shops", {"type": "start_project", "kind": "workshops", "shops": ["Craftsdwarfs"]}, "x", 6)
    for n in (2, 3):                                        # each start builds one: 1 -> 2 -> 3
        m.last_fired.clear()
        allowed, held = select([p], s, m)
        assert allowed, held
        record([(p, {"ok": True})], s, m)
        s["buildings"]["workshops"]["Craftsdwarfs"] = n
    m.last_fired.clear()
    allowed, held = select([p], s, m)
    assert allowed, held                                    # region2: held "started twice" with 3 built
    record([(p, {"ok": True})], s, m)
    m.last_fired.clear()
    assert select([p], s, m)[0]                             # once more without a new shop...
    record([(p, {"ok": True})], s, m)
    m.last_fired.clear()
    allowed, held = select([p], s, m)
    assert not allowed and "started twice" in held[0], held  # ...and then held
    old = Memory()                                          # counted before 0.99.4: one more try
    old.shops_started = {"Craftsdwarfs": 2}
    assert select([p], s, old)[0]
    assert shops_max(CONFIG, 60) == 3 and shops_max(CONFIG, 228) == 5


@test("one brew order per source (0.99.3): no new one while the AI's last still has jobs left; fruit alongside plants")
def _():
    s = fort()
    s["stocks"].update(drink=1134, plants=218)
    s["dwarves"]["total"] = 228
    drink = lambda st: [p for p in plan(copy.deepcopy(st), Memory())[0] if p.rule == "drink"]
    s["orders"] = []
    assert drink(s), "low drink and nothing queued: brew"
    s["stocks"]["plant_growths"] = 0
    s["orders"] = [{"recipe": "brew_drink", "amount_left": 99, "amount_total": 100, "by_ai": True}]
    _, notes = plan(copy.deepcopy(s), Memory())[:2]
    assert not drink(s) and any("work through the brew orders" in n for n in notes), notes
    s["stocks"]["plant_growths"] = 325                               # fruit too: a second still brews it
    got = [p.action["recipe"] for p in drink(s)]
    assert got == ["brew_drink_from_fruit"], got
    s["orders"].append({"recipe": "brew_drink_from_fruit", "amount_left": 50, "amount_total": 50, "by_ai": True})
    assert not drink(s)
    s["orders"] = [{"recipe": "brew_drink", "amount_left": 5, "amount_total": 5, "by_ai": False}]
    assert drink(s), "the player's own order doesn't hold the AI back"


def _body():
    s = fort()
    s.setdefault("water", {})["cistern_status"] = {"v": 2, "stage": "well", "depth": 6, "gate": "shut"}
    s["stocks"].update(blocks=1174, mechanisms=4, chains=0, cloth=33)
    s.setdefault("supplies", {}).update(buckets=110, ropes=0)
    s["buildings"].setdefault("workshops", {})["Clothiers"] = 1
    parts = lambda st: [p for p in plan(copy.deepcopy(st), Memory())[0] if p.rule == "cistern_parts"]
    got = [p.action["recipe"] for p in parts(s)]
    assert got == ["cloth_rope"], got
    assert all(p.is_order for p in parts(s)) and "cistern's well" in parts(s)[0].reason
    s["orders"] = list(s.get("orders") or []) + [{"recipe": "cloth_rope", "amount_left": 1, "amount_total": 1}]
    assert not parts(s)                                              # on order already
    s["orders"] = []
    s["supplies"]["ropes"] = 1
    assert not parts(s)                                              # a rope is there: buildingplan takes it
    s["supplies"]["ropes"] = 0
    s["stocks"].update(cloth=0, thread=0)
    _, notes = plan(copy.deepcopy(s), Memory())[:2]
    assert not parts(s) and any("cistern's well waits for a rope or chain" in n for n in notes), notes


@test("cistern well parts (0.99.2): the cistern's well gets the rope it waits for (region2: ropes 0, chains 0, cloth 33)")
def _():
    PLANNER_CONFIG["cistern_hold"] = False      # (0.104.144) the design under the hold
    try:
        _body()
    finally:
        PLANNER_CONFIG["cistern_hold"] = False


@test("loop watchdog: the same action done too often in a year is held 28 days; rules that repeat by design aren't")
def _():
    from planner import Proposal, TICKS_PER_DAY
    s = fort()
    now = abs_tick(s)
    m = Memory()
    p = Proposal("build", {"type": "start_project", "kind": "bedrooms", "rooms": 8}, "x", 5)
    for i in range(12):
        m.last_fired.clear()
        st = {**s, "date": {**s["date"], "tick": s["date"]["tick"] - (12 - i) * 20 * TICKS_PER_DAY}}
        if st["date"]["tick"] < 0:
            st["date"] = {**s["date"], "year": s["date"]["year"] - 1, "tick": st["date"]["tick"] + 403200}
        record([(p, {"ok": True})], st, m)
    m.last_fired.clear()
    allowed, held = select([p], s, m, dict(PLANNER_CONFIG))
    assert not allowed and "possible loop" in held[0], (held, allowed, m.action_log, now)
    q = Proposal("entrances", {"type": "scan_entrances"}, "x", 5)
    for _ in range(100):
        record([(q, {"ok": True})], s, m)
    m.last_fired.clear()
    assert select([q], s, m, dict(PLANNER_CONFIG))[0]


@test("hazards: fire or a cloud near the dwarves sounds the alarm (and keeps it up); a berserk dwarf gets the squad; a flood shuts the cistern")
def _():
    s = fort()
    s["civ_alert"], s["civ_alert_ready"] = False, True
    s["hazards"] = {"fire_near": 6, "fires": 3}
    a = [p for p in plan(s, Memory())[0] if p.rule == "threat_alert"]
    assert a and a[0].action == {"type": "civ_alert", "on": True} and "fire" in a[0].reason, a
    s["hazards"] = {"fire_near": 60}
    assert not [p for p in plan(s, Memory())[0] if p.rule == "threat_alert"]                # far away
    s["hazards"] = {"berserk": [{"id": 9, "name": "Kib"}]}
    s["military"]["squads"] = [{"id": 3, "members": 6, "name": "Axes"}]
    k = [p for p in plan(s, Memory())[0] if p.rule == "squad_attack"]
    assert k and k[0].action == {"type": "squad_orders", "squad_id": 3, "kill": [9]}, k
    s["hazards"] = {"wet": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]}
    s["water"] = {"cistern_status": {"v": 2, "stage": "done", "gate": "open", "depth": 6}}
    props, notes = plan(s, Memory())
    assert any(p.action == {"type": "cistern_step", "shut": True} for p in props)
    assert any("deep water" in n for n in notes)
    from planner import hazard_alert, PLANNER_CONFIG as C
    assert hazard_alert({"hazards": {"cloud_near": 3}}, C).startswith("a cloud")
    s["hazards"] = {"cage_traps": 4, "cage_traps_full": 2, "free_cages": 0, "animal_piles": 0, "caged": 2}
    s["orders"] = []
    c = [p.action for p in plan(s, Memory())[0] if p.rule == "cages"]
    assert {"type": "place_surface", "kind": "cages"} in c, c
    assert any(a.get("recipe") == "wooden_cage" for a in c), c


@test("agenda: the most urgent proposals' goals, each once, then what the player is asked")
def _():
    from planner import Proposal, agenda
    props = [Proposal("arms", {}, "x", 3), Proposal("build", {}, "x", 6), Proposal("arms", {}, "y", 4),
             Proposal("unknown_rule", {}, "x", 1), Proposal("trade_deal", {}, "x", 2)]
    a = agenda(props, ["note", "[you] no well could be placed: blah"])
    assert a == ["trade with the caravans", "arm and armour the soldiers", "build the fort's next level",
                 "ask you: no well could be placed"], a


@test("building: never more than the open-project limit; Mining -100 digs only what the fort needs (0.96)")
def _():
    from planner import MINING_NEED_ONLY
    s = young_fort()
    s["projects"]["open"] = [{"id": i, "kind": "storage", "phase": "dig", "dig": {"total": 9, "dug": 1}}
                             for i in (1, 2)]
    assert not builds(plan(s, Memory())[0])
    s = young_fort()
    s["settings"]["traits"] = {"mining": -100}
    props, notes = plan(s, Memory())
    assert builds(props) and not {p.action.get("kind") for p in builds(props)} & set(MINING_NEED_ONLY)
    assert any(n.startswith("Mining -100: only the levels the fort needs") for n in notes), notes
    big = fort()                                    # a grown fort that would dig a library: not at -100
    big["settings"]["traits"] = {"mining": -100}
    assert not {p.action.get("kind") for p in builds(plan(big, Memory())[0])} & set(MINING_NEED_ONLY)


@test("building: one new project per 5 in-game days")
def _():
    s = young_fort()
    m = Memory()
    allowed, _ = select(plan(s, m)[0], s, m)
    record([(x, {"ok": True}) for x in allowed if x.rule == "build"], s, m)
    s2 = copy.deepcopy(s)
    s2["date"]["tick"] += 4 * 1200
    assert not [a for a in select(plan(s2, m)[0], s2, m)[0] if a.rule == "build"]
    s2["date"]["tick"] += 1200
    assert [a for a in select(plan(s2, m)[0], s2, m)[0] if a.rule == "build"]


@test("projects: dug -> furnish (needs buildingplan), built -> finish, stuck -> note")
def _():
    s = fort()
    s["projects"]["open"] = [
        {"id": 1, "kind": "bedrooms", "phase": "dig", "dig": {"total": 50, "dug": 50, "stuck": 0}},
        {"id": 2, "kind": "dining", "phase": "furnish", "furnish": {"placed": 10, "done": 10, "waiting": {}}}]
    acts = [x.action for x in plan(s, Memory())[0] if x.rule == "project"]
    assert {"type": "furnish_project", "project_id": 1} in acts and {"type": "finish_project", "project_id": 2} in acts
    s["tools"]["buildingplan"] = False
    p, notes = plan(s, Memory())
    assert not [x for x in p if x.action.get("type") == "furnish_project"]
    assert any(x.action == {"type": "tool", "name": "buildingplan", "enabled": True} for x in p)
    s["projects"]["open"] = [{"id": 3, "kind": "storage", "phase": "dig", "dig": {"total": 50, "dug": 20, "stuck": 30}}]
    assert any("no longer designated" in n for n in plan(s, Memory())[1])


@test("doctor a patient (0.104.111): the post goes back; a healthy doctor keeps his")
def _():
    s = fort()
    s["health"] = {"hospital": [{"id": 4, "staff": [{"post": "DOCTOR", "unit_id": 10},
                                                    {"post": "SURGEON", "unit_id": 11}], "zones": []}],
                   "patients": [{"id": 11, "name": "Udil, Surgeon", "in_hospital": True, "needs": ["dressing"]},
                                {"id": 12, "name": "Kib", "needs": ["diagnosis"]}]}
    got = [p for p in plan(copy.deepcopy(s), Memory())[0] if p.rule == "doctor_patient"]
    assert [p.action for p in got] == [{"type": "vacate_post", "location_id": 4, "unit_id": 11}], got
    s["health"]["patients"][0] = {"id": 11, "name": "Udil", "needs": []}      # healed, up and about
    assert not [p for p in plan(copy.deepcopy(s), Memory())[0] if p.rule == "doctor_patient"]


@test("stalled dig (0.104.110): 4 weeks still -> jobs let go of their workers; 8 weeks and 90% dug -> furnish anyway")
def _():
    s = fort()
    s["projects"]["open"] = [
        {"id": 170, "kind": "tombs", "phase": "dig", "started": {"year": s["date"]["year"], "tick": 0},
         "dig": {"total": 240, "dug": 235, "digging": 5, "stuck": 0, "waiting": ["x1 y2: Dig by Urist"]}},
        {"id": 173, "kind": "bedrooms", "phase": "dig", "started": {"year": s["date"]["year"], "tick": 0},
         "dig": {"total": 89, "dug": 0, "digging": 1, "stuck": 0}}]
    m = Memory()
    from planner import record

    def acts(done=False):
        got = [x for x in plan(copy.deepcopy(s), m)[0] if x.action.get("type") in ("free_dig_jobs", "furnish_project")]
        if done:            # (0.105.33) marked "freed" in record(), once done
            record([(x, {"ok": True}) for x in got if x.action["type"] == "free_dig_jobs"], s, m)
        return [x.action for x in got]
    assert acts() == []                                          # first look: progress noted
    s["date"]["tick"] += 28 * 1200
    got = acts()
    assert {"type": "free_dig_jobs", "project_id": 170} in got and {"type": "free_dig_jobs", "project_id": 173} in got, got
    assert [a for a in acts(done=True) if a["type"] == "free_dig_jobs"], "(0.105.33) not done: asked again"
    assert not [a for a in acts() if a["type"] == "free_dig_jobs"], "let go once"
    s["date"]["tick"] += 28 * 1200
    got = acts()
    assert got == [{"type": "furnish_project", "project_id": 170, "stalled": True}], got   # 0 of 89: not furnished
    s["projects"]["open"][0]["dig"]["dug"] = 236                  # progress: the clock starts again
    assert acts() == []


@test("dig first (0.104.128): a hospital or tomb level, or one with nothing dug for 2 weeks, raised to priority 2 once")
def _():
    s = fort()
    s["projects"]["open"] = [
        {"id": 174, "kind": "hospital", "phase": "dig", "dig": {"total": 175, "dug": 0, "digging": 1, "stuck": 0}},
        {"id": 173, "kind": "bedrooms", "phase": "dig", "dig": {"total": 89, "dug": 0, "digging": 1, "stuck": 0}},
        {"id": 175, "kind": "storage", "phase": "dig", "dig": {"total": 50, "dug": 20, "digging": 3, "stuck": 0}}]
    m = Memory()
    from planner import record
    def raised(ok=True):
        got = [x for x in plan(copy.deepcopy(s), m)[0] if x.action.get("type") == "prioritize_dig"]
        if ok:
            record([(x, {"ok": True}) for x in got], s, m)
        return sorted(x.action["project_id"] for x in got)
    assert raised() == []                                        # first look: progress noted
    s["date"]["tick"] += 1200
    assert raised(ok=False) == [174], "the hospital at once"
    assert raised() == [174], "(0.104.129) held or refused: asked again"
    assert raised() == []                                        # once taken: never again
    s["date"]["tick"] += 14 * 1200
    assert raised() == [173, 174], "nothing dug for 2 weeks; (0.104.134) the hospital again, still 0 a week on"
    assert raised() == []                                        # storage moves on its own: never
    s["projects"]["open"][0]["dig"]["dug"] = 5                   # progress: not asked again
    s["date"]["tick"] += 8 * 1200
    assert raised() == [173], "only the one still at 0"


@test("idle blocks (0.104.110): capped at 500, and only from stone the masons may use")
def _():
    s = fort()
    s["dwarves"]["idle_adults"] = s["dwarves"]["adults"]
    s["stocks"]["boulders"], s["stocks"]["blocks"] = 400, 100
    s["stone_use"] = {"usable": 2, "economic": {}}
    idle = lambda: [x for x in plan(copy.deepcopy(s), Memory())[0] if x.action.get("recipe") == "stone_blocks" and x.rule == "idle"]
    assert not idle(), "2 usable boulders: no blocks"
    s["stone_use"]["usable"] = 300
    assert idle()
    s["stocks"]["blocks"] = 600
    assert not idle(), "past the cap"


@test("projects: waiting furniture gets ordered once (not while an order is queued)")
def _():
    s = fort()
    s["projects"]["open"] = [{"id": 2, "kind": "bedrooms", "phase": "furnish",
                              "furnish": {"placed": 30, "done": 10, "waiting": {"Bed": 12, "Door": 8}}}]
    f = {x.action["recipe"]: x.action["amount"] for x in plan(s, Memory())[0] if x.rule == "furniture"}
    assert f == {"wooden_bed": 12, "stone_door": 8}, f
    s["orders"].append({"id": 7, "recipe": "wooden_bed", "amount_left": 5})
    f = {x.action["recipe"] for x in plan(s, Memory())[0] if x.rule == "furniture"}
    assert f == {"stone_door"}, f


@test("projects section missing (older bridge): no building at all")
def _():
    s = young_fort()
    del s["projects"]
    assert not builds(plan(s, Memory())[0])


@test("review: a storage level (nothing to build, placed=0) still gets finished")
def _():
    s = fort()
    s["projects"]["open"] = [{"id": 5, "kind": "storage", "phase": "furnish",
                              "furnish": {"placed": 0, "done": 0, "waiting": {}}}]
    assert {"type": "finish_project", "project_id": 5} in [x.action for x in plan(s, Memory())[0]]


@test("review: a failed or refused new project retries after a day, not every cycle")
def _():
    s = young_fort()
    m = Memory()
    b = builds(plan(s, m)[0])
    record([(b[0], {"ok": False, "error": "no safe level"})], s, m)
    s2 = copy.deepcopy(s)
    s2["date"]["tick"] += 600
    assert not [a for a in select(plan(s2, m)[0], s2, m)[0] if a.rule == "build"]
    s2["date"]["tick"] += 600
    assert [a for a in select(plan(s2, m)[0], s2, m)[0] if a.rule == "build"]
    m2 = Memory()
    record([(b[0], {"ok": False, "rejected": True, "error": "unknown level kind"})], s, m2)
    assert "build" in m2.last_fired                    # e.g. an older bridge: don't ask every cycle


@test("one bedroom level at a time: while one is open, the next need goes first")
def _():
    s = young_fort()
    s["projects"]["open"] = [{"id": 1, "kind": "bedrooms", "phase": "furnish", "summary": {"beds": 32},
                              "furnish": {"placed": 64, "done": 10, "waiting": {}}}]
    b = builds(plan(s, Memory())[0])
    assert b and b[0].action["kind"] == "dining", b[0].action


@test("review: marker-mode designations: the AI makes them real (0.105.35: was a Needs you note)")
def _():
    s = fort()
    s["projects"]["open"] = [{"id": 3, "kind": "storage", "phase": "dig",
                              "dig": {"total": 50, "dug": 0, "stuck": 0, "marked": 50}}]
    p, notes = plan(s, Memory())
    um = [x for x in p if x.action.get("type") == "unmark_project_dig"]
    assert um and um[0].action["project_id"] == 3 and "marker" in um[0].reason, p
    assert not any(n.startswith("[you] ") and "marker" in n for n in notes), notes


# --- culture (Phase 4c) ----------------------------------------------------------------

def settled_fort(**traits):
    """Beds, dining hall, workshops and stockpiles all present: only culture is left."""
    s = fort()
    s["settings"]["traits"] = traits
    s["locations"] = {"count": {"HOSPITAL": 1, "INN_TAVERN": 1, "LIBRARY": 1}, "total": 3}
    return s


@test("culture: every new level carries the fort's style")
def _():
    s = young_fort()
    s["settings"]["traits"] = {"grandeur": 150, "fortification": 60}
    a = builds(plan(s, Memory())[0])[0].action
    style = dict(a["style"])
    assert style.pop("orient") in (0, 1, 2, 3) and 3 <= style.pop("rhythm") <= 6, a["style"]   # seeded details
    assert style == {"hall": "pillared", "smooth": 3, "statues": 4, "entry_door": True,
                     "spacing": 0}, a["style"]
    s["settings"]["traits"] = {"spacing": -80}
    assert builds(plan(s, Memory())[0])[0].action["style"]["spacing"] == -80
    m = Memory(culture={"sieges": 2})                  # a besieged fort huddles closer: -15 per siege
    assert builds(plan(s, m)[0])[0].action["style"]["spacing"] == -110


@test("culture: a slain beast gets a memorial hall; once started, not again")
def _():
    m = Memory(culture={"beasts_slain": ["Shulmik the Jackalowls"], "memorials_built": []})
    s = settled_fort()
    a = builds(plan(s, m)[0])
    assert a and a[0].action["kind"] == "memorial" and a[0].action["name"] == "Shulmik the Jackalowls"
    record([(a[0], {"ok": True})], s, m)
    assert m.culture["memorials_built"] == ["Shulmik the Jackalowls"]
    assert not builds(plan(s, m)[0])


@test("culture: a devout fort without a temple builds one (grand when very devout)")
def _():
    s = settled_fort(piety=60)
    a = builds(plan(s, Memory())[0])
    assert a and a[0].action == {"type": "start_project", "kind": "temple", "size": "shrine",
                                  "style": a[0].action["style"]}
    s = settled_fort(piety=150)
    assert builds(plan(s, Memory())[0])[0].action["size"] == "grand"
    s["locations"] = {"count": {"TEMPLE": 1, "HOSPITAL": 1, "INN_TAVERN": 1, "LIBRARY": 1}, "total": 4}
    # (0.104.161, 14.1) one temple isn't the end of it for a fort this devout:
    # a second, grand temple to all gods as it grows (it built nothing before)
    a = builds(plan(s, Memory())[0])
    assert a and a[0].action["kind"] == "temple" and a[0].action["size"] == "grand" and a[0].action.get("growth") \
        and "deity_hf" not in a[0].action and "temple to all gods" in a[0].reason, [x.action for x in a]
    s["locations"]["count"]["TEMPLE"] = 4                      # as many as it wants (GROWTH_MAX)
    assert not builds(plan(s, Memory())[0])
    assert not builds(plan(settled_fort(piety=0), Memory())[0])


@test("culture: waiting furniture is ordered in the signature stone (beds stay wooden)")
def _():
    s = fort()
    s["settings"]["traits"] = {"outsiders": -80}                # dark palette
    s["stone_types"] = [{"token": "INORGANIC:GRANITE", "name": "granite", "count": 500, "rgb": [0.6, 0.6, 0.6]},
                        {"token": "INORGANIC:OBSIDIAN", "name": "obsidian", "count": 90, "rgb": [0.1, 0.1, 0.1]}]
    s["projects"]["open"] = [{"id": 2, "kind": "dining", "phase": "furnish",
                              "furnish": {"placed": 30, "done": 0, "waiting": {"Table": 10, "Bed": 2}}}]
    f = {x.action["recipe"]: x.action for x in plan(s, Memory())[0] if x.rule == "furniture"}
    assert f["stone_table"]["material"] == "INORGANIC:OBSIDIAN"
    assert "material" not in f["wooden_bed"]


@test("materials: stone by purpose gives each kind its stone; wood where it will do, while wood lasts")
def _():
    s = fort()
    s["settings"]["traits"] = {"craftsmanship": 120, "industriousness": 80}       # by purpose
    s["stone_types"] = [{"token": "INORGANIC:GRANITE", "name": "granite", "count": 500, "rgb": [0.6, 0.6, 0.6]},
                        {"token": "INORGANIC:OBSIDIAN", "name": "obsidian", "count": 90, "rgb": [0.1, 0.1, 0.1]},
                        {"token": "INORGANIC:JASPER", "name": "jasper", "count": 60, "rgb": [0.8, 0.2, 0.1]}]
    s["projects"]["open"] = [{"id": 2, "kind": "dining", "phase": "furnish",
                              "furnish": {"placed": 30, "done": 0, "waiting": {"Table": 10, "Door": 4}}}]
    f = {x.action["recipe"]: x for x in plan(s, Memory())[0] if x.rule == "furniture"}
    assert f["stone_door"].action["material"] == "INORGANIC:OBSIDIAN", f["stone_door"].action
    assert f["stone_table"].action["material"] == "INORGANIC:JASPER" and "own stone" in f["stone_table"].reason
    s["settings"]["traits"] = {"surface": 120, "agriculture": 80, "craftsmanship": -60}   # wood
    s["stocks"]["wood"] = 5000
    f = {x.action["recipe"]: x for x in plan(s, Memory())[0] if x.rule == "furniture"}
    assert "wooden_table" in f and "wooden_door" in f and "in wood" in f["wooden_table"].reason, list(f)
    s["stocks"]["wood"] = 0                                                       # no wood: stone after all
    f = {x.action["recipe"] for x in plan(s, Memory())[0] if x.rule == "furniture"}
    assert f == {"stone_table", "stone_door"}, f


@test("furniture in metal: a crafty fort with spare silver forges its tables; gear metals never")
def _():
    s = fort()
    s["settings"]["traits"] = {"craftsmanship": 80}
    s["orders"] = []
    s["projects"]["open"] = [{"id": 2, "kind": "dining", "phase": "furnish",
                              "furnish": {"placed": 30, "done": 0, "waiting": {"Table": 6, "Bed": 2}}}]
    s["military"]["gear"] = dict(s["military"].get("gear") or {}, forges=1,
                                 all_bars={"SILVER": 40, "STEEL": 300, "GOLD": 12})
    s["supplies"]["fuel"] = 50
    f = {x.action["recipe"]: x for x in plan(s, Memory())[0] if x.rule == "furniture"}
    assert f["metal_table"].action["material"] == "INORGANIC:SILVER" and "at the forge" in f["metal_table"].reason, f
    assert "wooden_bed" in f                                     # beds have no metal kind
    s["military"]["gear"]["all_bars"] = {"STEEL": 300}           # only gear metal: stone or wood instead
    f = {x.action["recipe"] for x in plan(s, Memory())[0] if x.rule == "furniture"}
    assert "metal_table" not in f, f


@test("culture: engraving is proposed when the game says the smoothing is done")
def _():
    s = fort()
    s["projects"]["decorating"] = [{"id": 4, "kind": "dining", "phase": "decorate", "next": "engrave"}]
    assert {"type": "engrave_project", "project_id": 4} in [x.action for x in plan(s, Memory())[0]]
    s["projects"]["decorating"][0]["next"] = None
    assert not [x for x in plan(s, Memory())[0] if x.action.get("type") == "engrave_project"]


@test("culture: decorating projects don't use up a building slot")
def _():
    s = young_fort()
    s["projects"]["decorating"] = [{"id": i, "kind": "dining", "phase": "decorate", "next": None} for i in (1, 2, 3)]
    assert builds(plan(s, Memory())[0])


@test("review 4c: an empty location list from the game (sent as []) still allows a temple")
def _():
    s = settled_fort(piety=60)
    s["locations"] = []
    a = builds(plan(s, Memory())[0])
    assert a and a[0].action["kind"] == "hospital", [x.action for x in a]     # no locations at all
    s["locations"] = {"count": {"HOSPITAL": 1, "INN_TAVERN": 1, "LIBRARY": 1}, "total": 3}
    assert builds(plan(s, Memory())[0])[0].action["kind"] == "temple"


@test("review 4c: a memorial with an unknown result is still recorded (no second memorial)")
def _():
    m = Memory(culture={"beasts_slain": ["Shulmik the Jackalowls"], "memorials_built": []})
    s = settled_fort()
    a = builds(plan(s, m)[0])
    record([(a[0], {"ok": None, "error": "timeout"})], s, m)
    assert m.culture["memorials_built"] == ["Shulmik the Jackalowls"]


@test("review 4c: 'next' = false from the game means nothing to do")
def _():
    s = fort()
    s["projects"]["open"] = [{"id": 1, "kind": "bedrooms", "phase": "dig", "next": False,
                              "dig": {"total": 50, "dug": 50, "stuck": 0}}]
    assert not [x for x in plan(s, Memory())[0] if x.rule == "project"]


@test("game: a memorial the game left unfinishable is cancelled and owed again")
def _():
    m = Memory(culture={"beasts_slain": ["Ijat"], "memorials_built": ["Ijat"]})
    s = fort()
    s["projects"]["open"] = [{"id": 1, "kind": "memorial", "phase": "dig", "next": "cancel",
                              "summary": {"memorial": "Ijat"}, "dig": {"total": 99, "dug": 50, "stuck": 49}}]
    c = [x for x in plan(s, m)[0] if x.action.get("type") == "cancel_project"]
    assert c and c[0].action == {"type": "cancel_project", "project_id": 1, "memorial": "Ijat"}, c
    record([(c[0], {"ok": True})], s, m)
    assert m.culture["memorials_built"] == []


@test("shoes mandate: leather shoes if there's leather, else cloth; boots are left to you")
def _():
    s = fort(mandates=[{"kind": "Make", "item": "SHOES", "subtype": "ITEM_SHOES_SHOES", "remaining": 3}])
    m = [x.action for x in plan(s, Memory())[0] if x.rule == "mandate"]
    assert m == [{"type": "work_order", "recipe": "leather_shoes", "amount": 3}], m
    s["stocks"]["leather"] = 0
    assert [x.action["recipe"] for x in plan(s, Memory())[0] if x.rule == "mandate"] == ["cloth_shoes"]
    s["stocks"]["cloth"] = 0
    p, notes = plan(s, Memory())
    assert not [x for x in p if x.rule == "mandate"] and any("leather or cloth" in n for n in notes)
    s = fort(mandates=[{"kind": "Make", "item": "SHOES", "subtype": "ITEM_SHOES_BOOTS", "remaining": 2}])
    p, notes = plan(s, Memory())
    assert not [x for x in p if x.rule == "mandate"] and any("boots" in n for n in notes), notes


@test("hospital: a fort of 20+ without one builds one; barracks only for a militant fort")
def _():
    s = settled_fort()
    s["locations"] = {"count": {}, "total": 0}
    a = builds(plan(s, Memory())[0])
    assert a and a[0].action["kind"] == "hospital" and 4 <= a[0].action["beds"] <= 20, a[0].action
    s = settled_fort(militarism=80)
    s["buildings"]["zones"]["Barracks"] = 0
    a = builds(plan(s, Memory())[0])
    assert a and a[0].action["kind"] == "barracks", [x.action for x in a]
    s["buildings"]["zones"]["Barracks"] = 2
    assert not builds(plan(s, Memory())[0])


@test("hospital: an older bridge (no location list) builds no hospital")
def _():
    s = settled_fort()
    del s["locations"]
    assert not [x for x in builds(plan(s, Memory())[0]) if x.action["kind"] == "hospital"]


# --- supplies (game systems audit, step 2) -------------------------------------------

def by_rule(props, rule):
    return [x for x in props if x.rule == rule]


@test("supplies: the real fort has enough of everything (no orders, no notes about it)")
def _():
    p, notes = plan(fort(), Memory())
    assert not by_rule(p, "containers") and not by_rule(p, "hospital") and not by_rule(p, "bags"), rules(p)
    assert not [n for n in notes if "well" in n or "soap" in n or "barrels" in n], notes


@test("supplies: no free barrels or pots -> barrels when wood is spare, rock pots when it isn't")
def _():
    p, _ = plan(fort(supplies__empty_barrels=2, supplies__empty_pots=1), Memory())
    c = by_rule(p, "containers")
    assert c and c[0].action["recipe"] == "wooden_barrel" and 5 <= c[0].action["amount"] <= 30, c
    p, _ = plan(fort(supplies__empty_barrels=2, supplies__empty_pots=1, stocks__wood=50), Memory())
    assert by_rule(p, "containers")[0].action["recipe"] == "stone_large_pot"
    p, notes = plan(fort(supplies__empty_barrels=0, supplies__empty_pots=0, stocks__wood=0,
                         stocks__boulders=0), Memory())
    assert not by_rule(p, "containers") and any("too little wood or stone" in n for n in notes), notes


@test("supplies: containers already ordered are counted (no double order)")
def _():
    s = fort(supplies__empty_barrels=2, supplies__empty_pots=1)
    s["orders"].append({"id": 1, "recipe": "wooden_barrel", "amount_left": 30, "amount_total": 30})
    p, _ = plan(s, Memory())
    assert not by_rule(p, "containers"), rules(p)


@test("supplies: hospital short of splints -> orders them; no soap -> a note")
def _():
    p, notes = plan(fort(supplies__splints=0, supplies__soap=0), Memory())
    h = by_rule(p, "hospital")
    assert h and h[0].action["recipe"] == "wooden_splint" and h[0].action["amount"] == 5, h
    assert any("soap" in n for n in notes), notes


@test("soap (0.104.7): infected wounds, no soap, no fat -> one spare animal to the butcher; never for Beast-friends")
def _():
    s = fort()
    s["supplies"].update(soap=0, tallow=0, fat=0, ash=0, lye=0)
    s["health"] = {"infected": 3}
    s["others_on_map"]["tame_animals"] = 42
    s["buildings"]["workshops"]["Butchers"] = 1
    sl = by_rule(plan(s, Memory())[0], "slaughter")
    assert sl and sl[0].action == {"type": "slaughter_one"}, sl
    m = Memory()
    m.culture = {"quirks": {"beast_friends": {}}}
    assert not by_rule(plan(s, m)[0], "slaughter")
    s["health"] = {"infected": 0}
    assert not by_rule(plan(s, Memory())[0], "slaughter")
    s["health"] = {"infected": 3}
    s["supplies"]["fat"] = 2
    assert not by_rule(plan(s, Memory())[0], "slaughter")
    # (0.104.11) fat there, no soap workshops, wounds infected: the urgent slot
    s["buildings"]["workshops"].pop("Ashery", None)
    s["buildings"]["workshops"].pop("SoapMaker", None)
    s["projects"]["open"] = []
    so = [p for p in by_rule(plan(s, Memory())[0], "soap") if p.action["type"] == "start_project"]
    assert so and so[0].action.get("urgent") is True and so[0].priority == 3, so
    # (0.104.14) another workshops level being dug (a kiln at 0 tiles since winter) doesn't hold it back,
    # and the fat is rendered into tallow meanwhile
    s["projects"]["open"] = [{"id": 44, "kind": "workshops", "phase": "dig", "summary": {"workshops": ["Kiln"]}}]
    s["supplies"]["fat"] = 149
    s["buildings"]["workshops"]["Kitchen"] = 1
    soap = by_rule(plan(s, Memory())[0], "soap")
    assert any(p.action["type"] == "start_project" and p.action.get("urgent") for p in soap), soap
    assert any(p.action == {"type": "work_order", "recipe": "render_fat", "amount": 5} for p in soap), soap
    # a level bringing the soap shops already: not a second
    s["projects"]["open"][0]["summary"]["workshops"] = ["Ashery", "SoapMaker"]
    assert not any(p.action["type"] == "start_project" for p in by_rule(plan(s, Memory())[0], "soap"))
    # no wounds infected: it waits its turn as before
    s["health"] = {"infected": 0}
    s["projects"]["open"][0]["summary"]["workshops"] = ["Kiln"]
    assert not by_rule(plan(s, Memory())[0], "soap")


@test("burial (0.104.15): free tombs and the dead forbidden -> unforbidden (the standing order on too, 0.105.27); unreachable said")
def _():
    s = fort()
    s["dead"] = {"ghosts": 0, "free_tombs": 7, "unburied": 104,
                 "why": {"forbidden": 60, "dump": 0, "in_job": 0, "unreachable": 4, "outside": 4, "carried": 0},
                 "forbid_own_dead": False}
    props, notes = plan(s, Memory())
    b = by_rule(props, "burial")
    assert b and b[0].action == {"type": "unforbid_dead", "max": 20} and "60" in b[0].reason, b
    assert any("4 of the unburied dead lie where the dwarves can't walk (4 outside)" in n for n in notes), notes
    s["dead"]["forbid_own_dead"] = True          # (0.105.27) the order on: still unforbidden by the AI, said why
    props, notes = plan(s, Memory())
    b = by_rule(props, "burial")
    assert b and b[0].action == {"type": "unforbid_dead", "max": 20} and "forbid your dead" in b[0].reason, b
    assert not any(n.startswith("[you] ") and "forbid your dead" in n for n in notes), notes
    s["dead"]["forbid_own_dead"] = False
    s["dead"]["why"]["forbidden"] = 0
    assert not by_rule(plan(s, Memory())[0], "burial")
    s["dead"]["why"]["forbidden"] = 60
    s["dead"]["free_tombs"] = 0                                     # no tomb: the tomb rules, not this
    assert not by_rule(plan(s, Memory())[0], "burial")
    # (0.104.17) the free tombs turn citizens away: automatic burial switched on
    s["dead"].update(free_tombs=7, free_tombs_no_citizens=7)
    s["dead"]["why"]["forbidden"] = 0
    b = by_rule(plan(s, Memory())[0], "burial")
    assert b and b[0].action == {"type": "allow_burial"} and b[0].priority == 2, b
    s["dead"]["unburied"] = 0
    assert not by_rule(plan(s, Memory())[0], "burial")


@test("rooms (0.104.20): gaps in rooms' walls -> built back; none -> nothing")
def _():
    s = fort()
    s["room_gaps"] = {"rooms": 6, "gaps": 23}
    r = by_rule(plan(s, Memory())[0], "rooms")
    assert r and r[0].action == {"type": "repair_rooms"} and "23 gap" in r[0].reason, r
    s["room_gaps"] = {"rooms": 0, "gaps": 0}
    assert not by_rule(plan(s, Memory())[0], "rooms")
    s["room_gaps"] = {"rooms": 0, "gaps": 0, "stalled": 40}        # (0.104.25) walls held by smoothing marks
    r = by_rule(plan(s, Memory())[0], "rooms")
    assert r and r[0].action == {"type": "repair_rooms"} and "40 planned" in r[0].reason, r


@test("coffins (0.104.21): a tomb level waits and the coffin order made no job in 3 days -> coffins on the bench")
def _():
    s = fort()
    s["bridge_version"] = "0.104.22"
    s["projects"]["open"] = [{"id": 43, "kind": "tombs", "phase": "furnish",
                              "furnish": {"days": 177, "placed": 30, "done": 1, "waiting": {"Coffin": 29}}}]
    s["orders"] = [{"id": 1666, "job": "ConstructCoffin", "recipe": "stone_coffin", "by_ai": True, "active": True,
                    "amount_left": 29, "validated": True}]
    s["stone_use"] = {"usable": 168, "economic": {}}
    m = Memory()
    now = abs_tick(s)
    m.order_watch["1666"] = {"left": 29, "since": now - 5 * 1200, "by_ai": True, "what": "stone_coffin"}
    c = by_rule(plan(s, m)[0], "coffins")
    assert c and c[0].action == {"type": "bench_jobs", "kind": "coffin", "count": 5, "material": "stone"}, c
    s["stone_use"]["usable"] = 0                                      # no stone: wood at a carpenter's
    assert by_rule(plan(s, m)[0], "coffins")[0].action["material"] == "wood"
    s["orders"][0]["jobs"] = {"n": 1, "suspended": 0, "working": 0}  # the order has a job: nothing
    assert not by_rule(plan(s, m)[0], "coffins")
    s["orders"][0].pop("jobs")
    m.order_watch["1666"]["since"] = now - 1200                       # only a day: wait
    assert not by_rule(plan(s, m)[0], "coffins")


@test("stress care (0.104.34): a release refused because the dwarf longs to fight waits 56 days")
def _():
    from planner import note_refusal, _refused_wait, Proposal
    m = Memory()
    p = Proposal("stress_care", {"type": "squad_release", "unit_id": 9}, "x", 3)
    note_refusal(m, p, {"ok": False, "error": "longs to fight or train: the squad is what meets that"}, 0)
    assert _refused_wait(m, p, 50 * 1200) is not None and _refused_wait(m, p, 57 * 1200) is None
    q = Proposal("stress_care", {"type": "squad_release", "unit_id": 10}, "x", 3)
    note_refusal(m, q, {"ok": False, "error": "no such squad"}, 0)
    assert _refused_wait(m, q, 50 * 1200) is None


@test("orphan jobs (0.104.34): jobs whose work order is gone are taken off the benches")
def _():
    s = fort()
    s["order_desk"] = {"orphan_jobs": 14, "workshops": []}
    o = by_rule(plan(s, Memory())[0], "orphan_jobs")
    assert o and o[0].action == {"type": "clear_orphan_jobs"}, o
    s["order_desk"]["orphan_jobs"] = 0
    assert not by_rule(plan(s, Memory())[0], "orphan_jobs")


@test("masons jammed (0.104.32): autoslab's engrave jobs fill the bench -> blank slabs and coffins on it, room made")
def _():
    from planner import masons_jammed
    s = fort()
    s["bridge_version"] = "0.104.32"
    jl = ([{"type": "ConstructCoffin", "worker": 2077}, {"type": "ConstructCoffin"}, {"type": "ConstructCoffin"}]
          + [{"type": "EngraveSlab", "order": 1500 + i} for i in range(7)])
    s["order_desk"] = {"workshops": [{"type": "Masons", "id": 13, "job_list": jl, "max_orders": 15}]}
    assert masons_jammed(s) == 7
    s["dead"].update(ghosts=13, ghost_names=["a"], unburied=90)
    s["supplies"].update(slabs=0, memorial_slabs=0)
    s.setdefault("tools", {})["autoslab"] = True
    s["stone_use"] = {"usable": 168, "economic": {}}
    sl = by_rule(plan(s, Memory())[0], "slabs")
    assert sl and sl[0].action == {"type": "bench_jobs", "kind": "slab", "count": 5, "make_room": True}, sl
    # the coffins lift room too
    s["projects"]["open"] = [{"id": 50, "kind": "tombs", "phase": "furnish",
                              "furnish": {"days": 30, "placed": 30, "done": 1, "waiting": {"Coffin": 23}}}]
    s["orders"] = [{"id": 1717, "job": "ConstructCoffin", "recipe": "stone_coffin", "by_ai": True, "active": True,
                    "amount_left": 28, "validated": True}]
    m = Memory()
    m.order_watch["1717"] = {"left": 28, "since": abs_tick(s) - 5 * 1200, "by_ai": True, "what": "stone_coffin"}
    c = by_rule(plan(s, m)[0], "coffins")
    assert c and c[0].action.get("make_room") is True, c
    # (0.104.33) blank slabs already on the full bench: not again
    s2 = copy.deepcopy(s)
    s2["order_desk"]["workshops"][0]["job_list"] = [{"type": "ConstructSlab"}] + jl[1:]
    assert masons_jammed(s2) == 0
    # a second mason's bench with room: nothing jammed, the slab order as before
    s["order_desk"]["workshops"].append({"type": "Masons", "id": 14, "job_list": [], "max_orders": 5})
    assert masons_jammed(s) == 0
    sl = by_rule(plan(s, Memory())[0], "slabs")
    assert sl and sl[0].action["type"] == "work_order", sl


@test("order slots (0.104.23): a workshop's order slots all held by idle jobs while the AI's orders get none -> 5 more")
def _():
    s = fort()
    s["bridge_version"] = "0.104.24"
    s["orders"] = [{"id": 1676, "recipe": "stone_slab", "job": "ConstructSlab", "by_ai": True, "active": True, "amount_left": 15},
                   {"id": 1666, "recipe": "stone_coffin", "job": "ConstructCoffin", "by_ai": True, "active": True, "amount_left": 29}]
    held = [{"type": "EngraveSlab", "order": 1490 + i} for i in range(5)]
    s["order_desk"] = {"workshops": [{"id": 13, "type": "Masons", "max_orders": 5,
                                      "job_list": held + [{"type": "ConstructCoffin", "worker": 2355}]}]}
    o = by_rule(plan(s, Memory())[0], "order_slots")
    assert o and o[0].action == {"type": "order_slots", "workshop_id": 13, "max": 10} and "EngraveSlab" in o[0].reason, o
    s["order_desk"]["workshops"][0]["job_list"][0]["worker"] = 7      # someone is on one: they move
    assert not by_rule(plan(s, Memory())[0], "order_slots")
    s["order_desk"]["workshops"][0]["job_list"][0].pop("worker")
    s["orders"] = [{"id": 1, "recipe": "stone_ring", "by_ai": True, "active": True, "amount_left": 5}]   # a craftsdwarf's
    assert not by_rule(plan(s, Memory())[0], "order_slots")
    from planner import order_shop
    assert order_shop("stone_coffin") == "Masons" and order_shop("stone_bracelet") == "Craftsdwarfs"
    assert order_shop("brew_drink") == "Still"


@test("wool (0.104.28): thread short, no fibre crop, tame animals to shear -> shear and spin; yarn cloth woven; none -> Needs you as before")
def _():
    s = fort()
    s["supplies"].update(thread_plants=0, shearable=4)
    s["stocks"]["thread"] = 0
    s["buildings"]["workshops"]["Farmers"] = 1
    s["health"] = {"patients": [{"id": 1, "needs": ["suture"]}]}
    s["dwarves"]["needs_medical_care"] = 1
    s["orders"] = []
    h = [p.action for p in by_rule(plan(s, Memory())[0], "hospital")]
    assert {"type": "work_order", "recipe": "shear_creature", "amount": 4} in h, h
    assert {"type": "work_order", "recipe": "spin_thread", "amount": 5} in h, h
    s["supplies"]["shearable"] = 0                                    # nothing to shear: the old Needs you
    props, notes = plan(s, Memory())
    assert not any(p.action.get("recipe") == "shear_creature" for p in props)
    assert any("no animal to shear" in n and "the AI buys them" in n for n in notes), notes      # (0.105.35) a note
    assert not any(n.startswith("[you] ") and "no animal to shear" in n for n in notes), notes
    from planner import wool_route
    s["supplies"]["shearable"] = 2
    assert wool_route(s)
    s["buildings"]["workshops"].pop("Farmers")
    assert not wool_route(s)


@test("soap (0.104.30): wounds infected, no soap, fat or tallow there -> kept from the cooks; lifted once soap is kept")
def _():
    s = fort()
    s["supplies"].update(soap=0, tallow=13, fat=0, ash=0, lye=0)
    s["health"] = {"infected": 9}
    f = by_rule(plan(s, Memory())[0], "fat_ban")
    assert f and f[0].action == {"type": "kitchen_fat", "ban": True}, f
    s["health"] = {"infected": 0}
    assert not by_rule(plan(s, Memory())[0], "fat_ban")
    m = Memory()
    m.fat_ban = True
    s["supplies"]["soap"] = 50
    f = by_rule(plan(s, m)[0], "fat_ban")
    assert f and f[0].action == {"type": "kitchen_fat", "ban": False}, f
    from planner import record
    record([(f[0], {"ok": True, "lifted": 2})], s, m)
    assert m.fat_ban is False


@test("tantrums (0.104.31): counted once a dwarf a day; many with a sheriff and no jail -> an urgent jail")
def _():
    from planner import note_tantrums, tantrums_recent
    s = settled_fort()
    m = Memory()
    ev = [{"kind": "report", "topic": "tantrum", "text": "Mistêm Udibisak, Bone Carver is throwing a tantrum!"},
          {"kind": "report", "topic": "tantrum", "text": "Mistêm Udibisak, Bone Carver is throwing a tantrum!"},
          {"kind": "report", "topic": "tantrum", "text": "Mistêm Udibisak, Bone Carver cancels Clean: Throwing tantrum."},
          {"kind": "report", "topic": "tantrum", "text": "Onget Dallithastesh, Miner is throwing a tantrum!"}]
    assert note_tantrums(s, m, ev) == 2 and note_tantrums(s, m, ev) == 0
    for d in range(1, 5):                                            # four more days of them
        s2 = copy.deepcopy(s)
        s2["date"]["tick"] += d * 1200
        note_tantrums(s2, m, ev[:1])
    assert tantrums_recent(s2, m) == 6, tantrums_recent(s2, m)
    s2["offices"] = {"offices": {"SHERIFF": {"held": ["Dodók"]}}}
    s2["buildings"]["zones"].pop("Dungeon", None)
    s2["projects"] = {"max_open": 2, "open": [{"id": 1, "kind": "storage", "phase": "dig"},
                                              {"id": 2, "kind": "bedrooms", "phase": "dig"}]}
    j = by_rule(plan(s2, m)[0], "jail_urgent")
    assert j and j[0].action["kind"] == "jail" and j[0].action["urgent"] is True, j
    s2["offices"] = {"offices": {}}                                  # nobody to punish: no jail rush
    assert not by_rule(plan(s2, m)[0], "jail_urgent")


@test("long-run pass (0.104.37): stuck orders held longer each time; splints for the patients waiting; the hospital's soap counted")
def _():
    from planner import stuck_hold_days, record, Proposal
    m = Memory()
    s = fort()
    now = abs_tick(s)
    p = Proposal("arms", {"type": "cancel_work_order", "order_id": 1, "stuck": "metal_gauntlets"}, "x", 3)
    record([(p, {"ok": True})], s, m)
    assert stuck_hold_days(m.stuck_cancelled["metal_gauntlets"], PLANNER_CONFIG) == 28
    s2 = copy.deepcopy(s); s2["date"]["tick"] += 40 * 1200
    record([(p, {"ok": True})], s2, m)
    assert stuck_hold_days(m.stuck_cancelled["metal_gauntlets"], PLANNER_CONFIG) == 56
    for _ in range(3):
        record([(p, {"ok": True})], s2, m)
    assert stuck_hold_days(m.stuck_cancelled["metal_gauntlets"], PLANNER_CONFIG) == 112
    # splints: one more for each patient waiting for one
    s = fort()
    s["locations"].setdefault("count", {})["HOSPITAL"] = 1
    s["supplies"].update(splints=3, crutches=10, buckets=10)
    s["orders"] = []
    s["health"] = {"infected": 0, "patients": [{"id": i, "needs": ["immobilize"]} for i in range(4)]}
    h = [x for x in by_rule(plan(s, Memory())[0], "hospital") if x.action.get("recipe") == "wooden_splint"]
    assert h and h[0].action["amount"] >= 3, h
    # the hospital's soap bars count: no fat ban when it holds enough
    s = fort()
    s["locations"] = {"count": {"HOSPITAL": 1}, "list": [{"type": "HOSPITAL", "have": {"soap": 750}, "want": {"soap": 750}}]}
    s["supplies"].update(soap=0, tallow=20, fat=0, ash=0, lye=0)
    s["health"] = {"infected": 5, "patients": []}
    assert not by_rule(plan(s, Memory())[0], "fat_ban")


@test("overnight fixes (0.104.38): tombs only for bodies a tomb can take; one storage level a season and a half; long back-offs kept")
def _():
    from planner import tombs_short, note_refusal, _refused_wait, Proposal, record
    s = fort()
    s["dead"] = {"unburied": 35, "free_tombs": 71, "ghosts": 8,
                 "why": {"outside": 26, "unreachable": 29, "not_ours": 2, "free": 1}}
    assert tombs_short(s, 95, PLANNER_CONFIG) == 0
    s["dead"]["why"] = {"free": 35}
    s["dead"]["free_tombs"] = 0
    assert tombs_short(s, 95, PLANNER_CONFIG) > 0
    # storage: the gap after the last storage level
    m = Memory()
    record([(Proposal("build", {"type": "start_project", "kind": "storage", "piles": ["stone"]}, "x", 5), {"ok": True})], s, m)
    assert m.storage_started == abs_tick(s)
    # a long back-off isn't forgotten at 60 days
    p = Proposal("feeder", {"type": "feeder_pile", "building_id": 12}, "x", 6)
    for i in range(8):
        note_refusal(m, p, {"ok": False, "error": "no free floor"}, i)
    note_refusal(m, Proposal("x", {"type": "y"}, "x", 6), {"ok": False, "error": "e"}, 70 * 1200)
    assert _refused_wait(m, p, 70 * 1200) is not None


@test("ghosts (0.104.42): slabs made but forbidden or their building suspended -> free them, first")
def _():
    s = fort()
    s["tools"] = dict(s.get("tools") or {}, autoslab=True)
    s["dead"] = {"ghosts": 2, "ghost_names": ["A", "B"], "unburied": 0, "free_tombs": 5,
                 "ghost_list": [{"kind": "MurderousGhost", "slab": "loose", "slab_at": {"forbid": True}},
                                {"kind": "RestlessHaunt", "slab": "job", "slab_job": {"suspended": True}}]}
    s["supplies"].update(slabs=0, memorial_slabs=0)
    f = by_rule(plan(s, Memory())[0], "slabs_free")
    assert f and f[0].action == {"type": "free_slabs"} and f[0].priority == 1 and "1 of them murderous" in f[0].reason, f
    s["dead"]["ghost_list"] = [{"kind": "MurderousGhost", "slab": "built"}]
    assert not by_rule(plan(s, Memory())[0], "slabs_free")


@test("water traffic (0.104.45): water near the surface -> restricted traffic over it; urgent after drownings")
def _():
    s = fort()
    s["water"] = {"middle": {"x": 98, "y": 88, "z_high": 170, "z_low": 155, "z_mid": 164},
                  "bodies": [{"kind": "surface", "z1": 168, "z2": 168}, {"kind": "cavern", "z1": 114, "z2": 140}]}
    w = by_rule(plan(s, Memory())[0], "water_traffic")
    assert w and w[0].action == {"type": "restrict_water", "levels": [168], "x": 98, "y": 88, "radius": 60} and w[0].priority == 6, w
    s["dead"] = dict(s.get("dead") or {}, deaths={"by_cause": {"DROWN": 1, "SUFFOCATE": 5}})
    assert by_rule(plan(s, Memory())[0], "water_traffic")[0].priority == 2
    # (0.104.139) every level of a body; strangling isn't drowning
    s["water"]["bodies"] = [{"kind": "surface", "z1": 168, "z2": 170}]
    s["dead"] = dict(s.get("dead") or {}, deaths={"by_cause": {"SUFFOCATE": 50}})
    w = by_rule(plan(s, Memory())[0], "water_traffic")
    assert w and w[0].action["levels"] == [170, 169, 168] and w[0].priority == 6, w
    s["water"]["bodies"] = [{"kind": "cavern", "z1": 114, "z2": 140}]
    assert not by_rule(plan(s, Memory())[0], "water_traffic")


@test("jail size (0.104.52): restraints all in use or too few while crimes come thick -> a chain in a jail zone")
def _():
    from planner import note_tantrums
    s = settled_fort()
    s["offices"] = {"offices": {"SHERIFF": {"held": ["Solon"]}}}
    s["dwarves"]["total"] = 73
    s["justice"] = {"jails": [{"id": 900, "chains": 1, "cages": 0, "used": 1}, {"id": 901, "chains": 1, "cages": 0, "used": 1}],
                    "restraints": 2, "restraints_used": 2, "punish": {"n": 1, "beatings": 1}}
    j = by_rule(plan(s, Memory())[0], "jail_size")
    assert j and j[0].action == {"type": "place_in_zone", "zone_id": 900, "what": "chain"}, j
    s["justice"].update(restraints=8, restraints_used=3, punish={"n": 0, "beatings": 0})
    assert not by_rule(plan(s, Memory())[0], "jail_size")
    s["offices"] = {"offices": {}}
    s["justice"].update(restraints=2, restraints_used=2, punish={"n": 1, "beatings": 1})
    assert not by_rule(plan(s, Memory())[0], "jail_size")              # nobody to jail them


@test("jail size (0.104.138): only a jail with free floor; none -> another jail; no hurry while places are free")
def _():
    s = settled_fort()
    s["offices"] = {"offices": {"SHERIFF": {"held": ["Solon"]}}}
    s["dwarves"]["total"] = 221
    s["justice"] = {"jails": [{"id": 453, "chains": 5, "used": 5, "free": 0}, {"id": 454, "chains": 6, "used": 4, "free": 3}],
                    "restraints": 11, "restraints_used": 10, "punish": {"n": 1, "beatings": 1}}
    j = by_rule(plan(copy.deepcopy(s), Memory())[0], "jail_size")
    assert j and j[0].action["zone_id"] == 454, j                     # the fuller-floored 453 has no room
    s["justice"]["jails"][1]["free"] = 0
    p = plan(copy.deepcopy(s), Memory())[0]
    assert not by_rule(p, "jail_size") and by_rule(p, "jail_more"), [x.rule for x in p]
    s["justice"]["jails"][1]["free"] = 3
    s["justice"].update(restraints=10, restraints_used=2)             # Teacheroar: 10 chains, 2 in use
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "jail_size")


@test("cloth (0.104.54): the hospital's thread isn't free to weave; no free thread and animals to shear -> shear and spin")
def _():
    s = settled_fort()
    s["stocks"].update(cloth=0, thread=6)
    s["supplies"].update(thread_plants=0, shearable=17)
    s["buildings"]["workshops"].update(Farmers=1, Loom=1)
    s["locations"] = {"count": {"HOSPITAL": 1}, "list": [{"type": "HOSPITAL", "have": {"thread": 89085}, "want": {"thread": 75000}}]}
    s["orders"] = []
    c = by_rule(plan(s, Memory())[0], "cloth")
    assert c and c[0].action["recipe"] == "shear_creature", c
    s["stocks"]["thread"] = 20                                        # free thread: weave it
    c = by_rule(plan(s, Memory())[0], "cloth")
    assert c and c[0].action["recipe"] == "weave_yarn_cloth", c


@test("arms (0.104.57): spare weapons unused a month -> new ones made anyway (Enxah's report, winter y73)")
def _():
    from planner import abs_tick
    s = json.loads((Path(__file__).parent / "fixtures" / "real" / "enxah-0.104.52-y73-winter.json").read_text(encoding="utf-8", errors="replace"))
    m = Memory()
    assert not [x for x in by_rule(plan(s, m)[0], "arms") if "weapon" in str(x.action.get("recipe")) or "axe" in str(x.action.get("recipe"))]
    m.gear_spare_since = {"weapons": abs_tick(s) - 40 * 1200}
    a = by_rule(plan(s, m)[0], "arms")
    assert a and a[0].action["recipe"] == "metal_battle_axe", a


@test("mood (0.104.36): plant cloth wanted where the thread is all wool -> no loom order, said instead")
def _():
    s = fort()
    s["stocks"]["thread"] = 7
    s["supplies"].update(thread_plants=0, shearable=7)
    s["buildings"]["workshops"]["Farmers"] = 1
    s["moods"] = {"list": [{"name": "Mestthos", "mood": "Secretive", "job": "StrangeMoodWeaver", "unit_id": 2550, "craft": True, "skill": "WEAVING",
                            "workshop": "Clothiers", "items_have": 0, "items_needed": 3,
                            "missing": [{"flags": ["plant"], "item": "CLOTH", "quantity": 30000}]}]}
    s["orders"] = []
    mem = Memory()
    mem.moods_seen["2550"] = abs_tick(s) - 20 * 1200
    m = [p for p in by_rule(plan(s, mem)[0], "mood") if p.action.get("recipe") == "weave_plant_cloth"]
    assert not m, m
    s["supplies"]["thread_plants"] = 4                                 # fibre crops: the loom can
    m = [p for p in by_rule(plan(s, mem)[0], "mood") if p.action.get("recipe") == "weave_plant_cloth"]
    assert m, by_rule(plan(s, Memory())[0], "mood")


@test("tavern (0.104.35): a third badly wanting company, only the stop-gap tavern, slots full -> an urgent tavern")
def _():
    s = settled_fort()
    cit = int(s["dwarves"].get("total") or 50)
    s.setdefault("needs", {}).setdefault("needs", {})["BeWithFriends"] = {"badly": cit // 2, "distracted": cit, "have": cit}
    s["locations"] = {"count": {"INN_TAVERN": 1}, "list": [{"type": "INN_TAVERN", "over_dining": True, "zones": [1]}]}
    s["projects"] = {"max_open": 2, "open": [{"id": 1, "kind": "storage", "phase": "dig"},
                                             {"id": 2, "kind": "bedrooms", "phase": "dig"}]}
    t = by_rule(plan(s, Memory())[0], "tavern_urgent")
    assert t and t[0].action["kind"] == "tavern" and t[0].action["urgent"] is True, t
    s["locations"]["list"][0]["over_dining"] = False                   # a real tavern: no rush
    assert not by_rule(plan(s, Memory())[0], "tavern_urgent")
    s["locations"]["list"][0]["over_dining"] = True
    s["needs"]["needs"]["BeWithFriends"]["badly"] = 2                  # few want company: the ladder's pace
    assert not by_rule(plan(s, Memory())[0], "tavern_urgent")


@test("ghosts (0.104.14): no stone the masons may use -> no slab order (it would only stand still), a note instead")
def _():
    s = fort()
    s["dead"] = {"ghosts": 3, "ghost_names": ["A", "B", "C"], "free_tombs": 2, "unburied": 0}
    s["supplies"]["slabs"] = 0
    s["supplies"]["memorial_slabs"] = 0
    s["tools"] = dict(s.get("tools") or {}, autoslab=True)
    s["stone_use"] = {"usable": 0, "economic": {}}
    props, notes = plan(s, Memory())
    assert not [p for p in by_rule(props, "slabs") if p.action.get("recipe") == "stone_slab"]
    assert any("waiting for quarried stone" in n for n in notes), notes
    s["stone_use"]["usable"] = 30
    assert [p for p in by_rule(plan(s, Memory())[0], "slabs") if p.action.get("recipe") == "stone_slab"]


@test("free time (0.104.10): many badly want friends and hardly anyone is idle -> planting, then gathering, to a crew; back when it's met")
def _():
    s = fort()
    s["dwarves"]["total"] = 88
    s["needs"] = {"needs": {"BeWithFriends": {"badly": 44, "distracted": 65}}, "social": {"idle": 3, "citizens": 88}}
    s["labor"] = dict(s.get("labor") or {}, jobs={"farming": {"mode": "EverybodyDoesThis"},
                                                    "gathering": {"mode": "EverybodyDoesThis"}}, narrowed={})
    s["farms"] = dict(s.get("farms") or {}, built=8)
    f = by_rule(plan(s, Memory())[0], "free_time")
    assert f and f[0].action == {"type": "narrow_detail", "job": "farming", "keep": 8}, f
    s["labor"]["narrowed"] = {"farming": True}
    s["labor"]["jobs"]["farming"]["mode"] = "OnlySelectedDoesThis"
    f = by_rule(plan(s, Memory())[0], "free_time")
    assert f and f[0].action == {"type": "narrow_detail", "job": "gathering", "keep": 3}, f
    s["needs"]["social"]["idle"] = 30                                  # plenty idle: nothing to cut
    assert not by_rule(plan(s, Memory())[0], "free_time")
    s["needs"]["needs"]["BeWithFriends"]["badly"] = 2                  # met: back to everybody
    f = by_rule(plan(s, Memory())[0], "free_time")
    assert f and f[0].action == {"type": "narrow_detail", "job": "farming", "widen": True}, f


@test("supplies: no hospital and nobody hurt -> no hospital orders")
def _():
    s = fort(supplies__splints=0, supplies__crutches=0)
    s["locations"]["count"].pop("HOSPITAL")
    s["dwarves"]["needs_medical_care"] = 0
    p, _ = plan(s, Memory())
    assert not by_rule(p, "hospital"), rules(p)


@test("wells: none -> the AI places one itself (urgently when someone is hurt); no Needs you")
def _():
    s = fort(dwarves__needs_medical_care=0)
    s["buildings"]["other"].pop("Well")
    props, notes = plan(s, Memory())
    w = by_rule(props, "well")
    assert len(w) == 1 and w[0].action == {"type": "place_well", "shore_reach": 60} and w[0].priority == 4, w
    assert not any("well" in n for n in notes if n.startswith("[you] ")), notes
    s["dwarves"]["needs_medical_care"] = 2
    w = by_rule(plan(s, Memory())[0], "well")
    assert w[0].priority == 2 and w[0].reason.startswith("2 injured dwarves need water"), w
    assert w[0].action.get("urgent") is True, w                         # (0.104.13) an urgent slot
    assert not by_rule(plan(fort(), Memory())[0], "well"), "the real fort has 3 wells"


@test("wells: one being built -> no second; slots full or Mining -100 -> a note, not an action")
def _():
    s = fort()
    s["buildings"]["other"].pop("Well")
    s["projects"]["open"] = [{"id": 3, "kind": "well", "phase": "dig"}]
    assert not by_rule(plan(s, Memory())[0], "well")
    s["projects"]["open"] = [{"id": 1, "kind": "bedrooms", "phase": "dig"}, {"id": 2, "kind": "dining", "phase": "dig"}]
    props, notes = plan(s, Memory())
    assert not by_rule(props, "well") and "no well yet: waiting for a free building slot" in notes, notes
    s["projects"]["open"] = []
    s["settings"]["traits"] = {"mining": -100}                      # (0.96) a well is a need: still dug
    props, notes = plan(s, Memory())
    assert by_rule(props, "well"), notes


@test("wells: nowhere to put one -> Needs you with the reason; waits 3 days; success clears it")
def _():
    s = fort()
    s["buildings"]["other"].pop("Well")
    m = Memory()
    p = by_rule(plan(s, m)[0], "well")[0]
    record([(p, {"ok": False, "error": "no open drop from a free floor inside the fort to clean water "
                 "(the water below is in a cavern)"})], s, m)
    assert "cavern" in m.well_failure
    props, notes = plan(s, m)
    # nobody hurt: a note; (0.104.13) and the AI goes to the cavern itself, so nothing asks the player
    assert any(n.startswith("no ordinary well could be placed") and "cavern instead" in n for n in notes), notes
    assert not any(n.startswith("[you] ") and "well" in n for n in notes), notes
    allowed, _ = select(props, s, m)
    assert not by_rule(allowed, "well"), "asked again straight away"
    record([(p, {"ok": False, "rejected": True, "error": "already 2 unfinished building projects"})], s, m)
    assert "cavern" in m.well_failure, "a full slot isn't a reason to bother the player"
    record([(p, {"ok": True, "x": 1, "y": 2})], s, m)
    assert m.well_failure == ""


@test("wells: waiting for parts -> the missing ones ordered; after 3 days, a note names what it can't make (0.105.35: no Needs you)")
def _():
    s = fort()
    s["buildings"]["other"].pop("Well")
    s["projects"]["open"] = [{"id": 3, "kind": "well", "phase": "furnish",
                              "furnish": {"placed": 1, "done": 0, "waiting": {"Well": 1}, "days": 1}}]
    s["stocks"].update(mechanisms=0, chains=0, cloth=0, thread=0)
    s["buildings"]["workshops"]["Mechanics"] = 1
    props, notes = plan(s, Memory())
    f = by_rule(props, "well_parts")
    assert [x.action for x in f if x.action.get("recipe") == "mechanisms"] == \
        [{"type": "work_order", "recipe": "mechanisms", "amount": 1}], f
    assert not by_rule(props, "furniture") or all(x.action["recipe"] != "mechanisms" for x in by_rule(props, "furniture"))
    assert not any("rope" in n for n in notes), notes
    s["projects"]["open"][0]["furnish"]["days"] = 3
    notes = plan(s, Memory())[1]
    assert any(n.startswith("the new well has waited 3 days") and "rope or chain" in n and "caravan" in n
               for n in notes), notes
    assert not any(n.startswith("[you]") and "well" in n for n in notes), notes


@test("wells: the game refused the well over the dug hole -> Needs you, and no second hole")
def _():
    s = fort()
    s["buildings"]["other"].pop("Well")
    m = Memory()
    from planner import Proposal
    p = Proposal("project", {"type": "furnish_project", "project_id": 3}, "x", 3)
    # (0.105.24) the bridge's give-up (3 tries, what it saw)
    record([(p, {"ok": False, "error": "the game would not place the well over the hole at x1 y2 z3 (3 tries; "
                                       "tiles: z3 OpenSpace, z2 OpenSpace, z1 OpenSpace; beside: StoneFloor1)"})], s, m)
    m.last_fired["well"] = abs_tick(s)          # (0.105.33) the stop lasts well_retry_days from the last try
    props, notes = plan(s, m)
    assert not by_rule(props, "well"), "would dig another hole"
    assert any(n.startswith("no well could be placed: the game would not place") for n in notes), notes


@test("0.105.24 wells: a refusal the bridge tries again isn't 'no well'; the old refusal (C, F) cleared once")
def _():
    s = fort()
    s["buildings"]["other"].pop("Well")
    m = Memory()
    from planner import Proposal
    p = Proposal("project", {"type": "furnish_project", "project_id": 3}, "x", 3)
    record([(p, {"ok": False, "retry": True, "error": "the game would not put the well over the hole at x1 y2 z3 "
                                                      "yet: no floor beside it; a floor is dug beside it"})], s, m)
    assert m.well_failure == ""
    # the old refusal (before the bridge said what it saw): cleared once, a well tried again
    m.well_failure = "the game would not place the well over the hole at x131 y129 z24"
    props, notes = plan(s, m)
    assert by_rule(props, "well") and m.well_floor_retried and m.well_failure == "", notes
    m.well_failure = "the game would not place the well over the hole at x131 y129 z24"
    m.last_fired["well"] = abs_tick(s)          # (0.105.33) tried just now: the stop holds (well_retry_days)
    props, notes = plan(s, m)
    assert not by_rule(props, "well")                              # once only


@test("supplies: an old bridge without the supplies section -> supply rules skipped, said once")
def _():
    s = fort()
    del s["supplies"]
    p, notes = plan(s, Memory())
    assert not by_rule(p, "containers") and any("supplies" in n for n in notes), notes


# --- the dead, strange moods, leisure (audit step 3) ---------------------------------

def mood(**kw):
    m = {"unit_id": 7, "name": "Urist", "mood": "Fey", "craft": True, "skill": "CUTGEM"}
    m.update(kw)
    return m


@test("mood: needs a workshop the fort lacks -> builds it (one workshops level), urgently")
def _():
    s = fort()
    s["buildings"]["workshops"].pop("Jewelers")
    s["moods"] = {"list": [mood()]}
    p, _ = plan(s, Memory())
    m = by_rule(p, "mood")
    assert m and m[0].action == {"type": "start_project", "kind": "workshops", "shops": ["Jewelers"], "urgent": True}, m
    assert m[0].priority <= 1
    s["projects"]["open"].append({"id": 9, "kind": "workshops", "phase": "dig"})
    p, notes = plan(s, Memory())
    assert not by_rule(p, "mood") and any("already being built" in n for n in notes), notes


@test("mood: a glassmaker's mood gets a glass furnace (0.104.95: the AI builds one now); the magma forge counts as a forge")
def _():
    s = fort()
    s["moods"] = {"list": [mood(skill="GLASSMAKER")]}
    s["buildings"]["furnaces"].pop("MagmaGlassFurnace")
    p, notes = plan(s, Memory())
    m = by_rule(p, "mood")
    assert m and m[0].action["type"] == "start_project" and "GlassFurnace" in m[0].action["shops"], (m, notes)
    s["moods"] = {"list": [mood(skill="FORGE_WEAPON")]}
    s["buildings"]["workshops"].pop("MetalsmithsForge")                  # MagmaForge is still there
    p, notes = plan(s, Memory())
    assert not by_rule(p, "mood"), rules(p)


@test("mood: no claim after 2 days -> a note; gathering stalls -> a note; insanity -> a note")
def _():
    s = fort()
    s["moods"] = {"list": [mood()]}
    mem = Memory()
    note_cycle(s, mem)
    _, notes = plan(s, mem)
    assert not any("without claiming" in n for n in notes)
    s["date"]["tick"] += 3 * 1200
    note_cycle(s, mem)
    _, notes = plan(s, mem)
    assert any("3 days without claiming" in n for n in notes), notes
    s["moods"] = {"list": [mood(workshop="Jewelers", items_have=1, items_needed=3)]}
    _, notes = plan(s, mem)
    assert any("gathering materials (1/3)" in n for n in notes), notes
    s["moods"] = {"list": [mood(mood="Baby", craft=False, name="Rimtar")]}
    _, notes = plan(s, mem)
    assert not any("Rimtar" in n for n in notes), notes            # a carried baby is not a mood
    s["moods"] = {"list": [mood(mood="Berserk", craft=False)]}
    _, notes = plan(s, mem)
    assert any("gone berserk" in n for n in notes), notes
    note_cycle(s, mem)
    assert mem.moods_seen == {}                                  # mood over: forgotten


@test("tombs: too few free tombs (plus bodies waiting) -> a tomb level; enough -> none")
def _():
    s = settled_fort()
    s["dead"] = {"free_tombs": 0, "unburied": 3, "ghosts": 0}
    a = builds(plan(s, Memory())[0])
    assert a and a[0].action["kind"] == "tombs", [x.action for x in a]
    assert a[0].action["coffins"] == max(4, min(30, (max(2, 4) + 3) * 2)), a[0].action
    s["dead"] = {"free_tombs": 10, "unburied": 0}
    assert not builds(plan(s, Memory())[0])
    del s["dead"]                                                # older bridge: never guess
    assert not [x for x in builds(plan(s, Memory())[0]) if x.action["kind"] == "tombs"]


@test("ghosts, bodies with nowhere to go, coffins outside tomb zones -> notes")
def _():
    s = fort()
    s["dead"] = {"ghosts": 2, "ghost_names": ["Urist", "Bomrek"], "unburied": 1, "free_tombs": 0,
                 "loose_coffins": 4}
    s["tools"].pop("autoslab")                                   # a DFHack without autoslab
    _, notes = plan(s, Memory())
    text = " | ".join(notes)
    assert "2 ghost(s)" in text and "Urist" in text and "memorial slab" in text, text
    assert "no free tomb" in text and "aren't in a tomb zone" in text, text


@test("ghosts with autoslab around: switch it on, and make blank slabs if there are too few")
def _():
    s = fort()
    s["dead"] = {"ghosts": 2, "ghost_names": ["Urist"], "unburied": 0, "free_tombs": 10}
    s["supplies"]["slabs"] = 0
    p, notes = plan(s, Memory())
    t = [x for x in by_rule(p, "tools") if x.action["name"] == "autoslab"]
    sl = by_rule(p, "slabs")
    assert t and sl and sl[0].action == {"type": "work_order", "recipe": "stone_slab", "amount": 3}, (t, sl)
    assert not any("ghost" in n for n in notes), notes                       # handled, not your job
    s["settings"]["engrave_slabs"] = False
    p, notes = plan(s, Memory())
    # (0.105.35) the player's own switch: a note, not a Needs you
    assert not by_rule(p, "slabs") and any(n.startswith("2 ghost(s)") and "switch" in n for n in notes), notes


@test("tavern from 15 dwarves, library from 40; coffins and bookcases waiting get ordered")
def _():
    s = settled_fort()
    s["locations"] = {"count": {"HOSPITAL": 1, "LIBRARY": 1}, "total": 2}
    a = builds(plan(s, Memory())[0])
    assert a and a[0].action["kind"] == "tavern" and 4 <= a[0].action["tables"] <= 20, a[0].action
    s["locations"] = {"count": {"HOSPITAL": 1, "INN_TAVERN": 1}, "total": 2}
    assert builds(plan(s, Memory())[0])[0].action == {
        "type": "start_project", "kind": "library", "bookcases": 6,
        "style": builds(plan(s, Memory())[0])[0].action["style"]}
    s["dwarves"]["total"] = 30
    assert not builds(plan(s, Memory())[0])                      # too small for a library
    s = fort()
    s["projects"]["open"] = [{"id": 3, "kind": "tombs", "phase": "furnish",
                              "furnish": {"waiting": {"Coffin": 6}}}]
    p, _ = plan(s, Memory())
    f = by_rule(p, "furniture")
    assert f and f[0].action["recipe"] == "stone_coffin" and f[0].action["amount"] == 6, f


# --- the Rules tab -------------------------------------------------------------------

@test("rules: memorials at most one per season by default; 'every' and 'never' too")
def _():
    m = Memory(culture={"beasts_slain": ["Shulmik the Jackalowls", "Thomo the Waters of Mining"],
                        "memorials_built": ["Shulmik the Jackalowls"]})
    s = settled_fort()
    m.last_memorial_tick = (s["date"]["year"] * 403200 + s["date"]["tick"]) - 5 * 1200   # 5 days ago
    p, notes = plan(s, m)
    assert not [x for x in builds(p) if x.action["kind"] == "memorial"]
    assert any("at most one per season" in n for n in notes), notes
    s["settings"]["memorial_pace"] = "every"
    assert builds(plan(s, m)[0])[0].action["kind"] == "memorial"
    s["settings"]["memorial_pace"] = "never"
    p, notes = plan(s, m)
    assert not builds(p) and any("switched off" in n for n in notes), notes
    s["settings"]["memorial_pace"] = "season"
    m.last_memorial_tick -= 100 * 1200                              # long ago
    assert builds(plan(s, m)[0])[0].action["kind"] == "memorial"


@test("rules: starting a memorial remembers when (for the pace)")
def _():
    from planner import Proposal
    s = settled_fort()
    m = Memory()
    record([(Proposal("build", {"type": "start_project", "kind": "memorial", "name": "X"}, "", 6), {"ok": True})],
           s, m)
    assert m.last_memorial_tick == s["date"]["year"] * 403200 + s["date"]["tick"]


@test("rules: a level switched off is skipped, the next need comes up instead")
def _():
    s = settled_fort()
    s["locations"] = {"count": {"HOSPITAL": 1}, "total": 1}
    assert builds(plan(s, Memory())[0])[0].action["kind"] == "tavern"
    s["settings"]["levels"] = {"tavern": False}
    assert builds(plan(s, Memory())[0])[0].action["kind"] == "library"
    s["settings"]["levels"] = {"tavern": False, "library": False}
    assert not builds(plan(s, Memory())[0])


@test("rules: supplies and mood workshops can be switched off (notes stay)")
def _():
    s = fort(supplies__empty_barrels=0, supplies__empty_pots=0)
    s["settings"]["order_supplies"] = False
    p, _ = plan(s, Memory())
    assert not by_rule(p, "containers")
    s = fort()
    s["buildings"]["workshops"].pop("Jewelers")
    s["moods"] = {"list": [mood()]}
    s["settings"]["mood_workshops"] = False
    p, notes = plan(s, Memory())
    assert not by_rule(p, "mood") and any("switched off in the Rules tab" in n for n in notes), notes


# --- military (audit step 4) ----------------------------------------------------------

def under_attack(great=False, n=2):
    s = fort()
    s["others_on_map"]["threats"] = [
        {"id": 900 + i, "name": "Goblin" if not great else "Forgotten Beast", "great_danger": great,
         "can_reach_dwarves": True, "invader": True} for i in range(n)]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = n
    return s


@test("fight or hide (0.104.118): a titan is fought by strong squads, hidden from by weak ones; a costly fight teaches")
def _():
    def titan(power):
        s = under_attack(great=True, n=1)
        s["others_on_map"]["threats"][0].update(kinds=["Titan"], size=2_500_000, name="Ume, Swamp Titan")
        for q in s["military"]["squads"]:
            q["power"] = {"power": power, "armored": 10, "skill": 10}
        s["military"]["soldiers"] = 20
        return s
    # titan: (8 + 2*sqrt(41.7)) * 1.2 = 25.1; two squads
    p, notes = plan(titan(40), Memory())                      # 80 >= 2 x 25: go
    assert by_rule(p, "squad_attack"), notes
    assert any("the squads go" in n for n in notes), notes
    p, notes = plan(titan(10), Memory())                      # 20 < 50: hide
    assert not by_rule(p, "squad_attack")
    assert any("hide behind the gates" in n for n in notes), notes
    # learning: a fight that cost a third of the soldiers makes titans count 1.5x
    m = Memory()
    s = titan(35)                                             # 70 >= 50: go
    plan(copy.deepcopy(s), m)
    assert m.fight and m.fight["keys"] == ["Titan"] and m.fight["soldiers"] == 20, m.fight
    after = copy.deepcopy(s)
    after["others_on_map"]["threats"] = []
    after["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    after["military"]["soldiers"] = 13
    plan(after, m)
    assert m.fight_factor == {"Titan": 1.5} and not m.fight and m.fights[-1]["lost"] == 7, (m.fight_factor, m.fights)
    p, notes = plan(titan(35), m)                             # now 70 < 2 x 37.7: hide
    assert not by_rule(p, "squad_attack")


@test("fight or hide (0.104.139): breath or dust and flight weigh; forgotten beasts their own kind; no flip-flop; no refills mid-fight")
def _():
    from planner_military import threat_power, fight_key
    small = {"size": 100_000, "kinds": ["ForgottenBeast"]}
    plain = threat_power(small)
    assert abs(threat_power(dict(small, abilities=2)) - plain * 3) < 1e-6          # (0.105.22: x3)
    assert abs(threat_power(dict(small, abilities=2, flier=True)) - plain * 4.5) < 1e-6
    assert fight_key({"kinds": ["Undead", "ForgottenBeast"]}) == "ForgottenBeast"

    def beast(power):
        s = under_attack(great=True, n=1)
        s["others_on_map"]["threats"][0].update(kinds=["ForgottenBeast"], size=100_000, abilities=1)
        for q in s["military"]["squads"]:
            q["power"] = {"power": power, "armored": 5, "skill": 5}
        s["military"]["soldiers"] = 20
        return s
    # (8 + 2*sqrt(1.67)) * 1.3 * 3 = 41.3; 2 squads: 2 x 30 = 60 < 82.6: hide (0.105.22: abilities x3)
    p, notes = plan(beast(30), Memory())
    assert not by_rule(p, "squad_attack") and any("hide behind the gates" in n for n in notes), notes
    m = Memory()
    plan(beast(45), m)                                       # 90 >= 82.6: go, the fight begins
    assert m.fight and m.fight["keys"] == ["ForgottenBeast"], m.fight
    p, notes = plan(beast(33), m)                            # 66: under 2.0, over 1.5: the fight goes on
    assert by_rule(p, "squad_attack") or any("the squads go" in n for n in notes), notes
    s = beast(45)
    s["military"]["soldiers"] = 12                           # (0.105.22) 8 of 20 lost mid-fight: they come back
    p, notes = plan(s, m)
    # (0.105.26) learned strong enough to hide even from the squads at full strength
    ff = m.fight_factor.get("ForgottenBeast")
    assert not by_rule(p, "squad_attack") and ff >= 1.5 and 90 * 20 / 12 < 2.0 * 41.3 * ff, (notes, m.fight_factor)
    plan(s, m)
    assert m.fight_factor.get("ForgottenBeast") == ff           # learned once
    s = beast(45)
    s["military"]["soldiers"] = 5                            # short of the target, mid-fight: no refill
    p, notes = plan(s, m)
    assert not by_rule(p, "squad_fill") and any("filled once the fight is over" in n for n in notes), notes
    m.fight["tick"] -= 8 * TICKS_PER_DAY                    # (review) a week on (the beast lingers outside): refills again
    p, notes = plan(s, m)
    assert not any("filled once the fight is over" in n for n in notes), notes


@test("reach (0.104.139): a flier in the air near the dwarves, or a building destroyer by the door, can reach them")
def _():
    s = under_attack(n=1)
    th = s["others_on_map"]["threats"][0]
    th.update(can_reach_dwarves=None, flier=True, distance_to_nearest_dwarf=12)
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    assert by_rule(plan(copy.deepcopy(s), Memory())[0], "squad_attack")
    th.update(distance_to_nearest_dwarf=80)
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "squad_attack")
    th.update(flier=None, can_reach_dwarves=False, destroyer=True, distance_to_nearest_dwarf=10)
    assert by_rule(plan(copy.deepcopy(s), Memory())[0], "squad_attack")
    th.update(invader=False, layer="cavern_1")                        # (review) a cavern destroyer that can't get up: no
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "squad_attack")


@test("break fights (0.104.139): a citizen killed by a citizen -> fix/loyaltycascade; quiet again -> no more")
def _():
    import crisis
    s = fort()
    m = Memory()
    crisis.note_deaths(s, m, [{"kind": "death", "own_civ": True, "killer_kind": "citizen", "cause": "SUFFOCATE"},
                              {"kind": "death", "own_civ": True, "killer_kind": "ghost"}])
    assert len(m.fight_deaths) == 1, m.fight_deaths
    b = by_rule(plan(copy.deepcopy(s), m)[0], "break_fights")
    assert b and b[0].action == {"type": "break_fights"} and b[0].priority == 0, b
    later = copy.deepcopy(s)
    later["date"]["tick"] += 4 * TICKS_PER_DAY
    assert not by_rule(plan(later, m)[0], "break_fights")
    # (review) never with enemies about (it takes soldiers out of their fights too); a sparring death doesn't count
    war = copy.deepcopy(s)
    war["others_on_map"]["threats"] = [{"id": 5, "invader": True, "can_reach_dwarves": False}]
    assert not by_rule(plan(war, m)[0], "break_fights")
    m2 = Memory()
    crisis.note_deaths(s, m2, [{"kind": "death", "own_civ": True, "killer_kind": "citizen", "conflict": "Training"}])
    assert not m2.fight_deaths
    crisis.note_deaths(s, m2, [{"kind": "death", "own_civ": True, "killer_kind": "citizen", "conflict": "None",
                                "cause": "SUFFOCATE", "patient": True}])
    assert len(m2.fight_deaths) == 1                                  # (0.104.141) a patient strangled: no fight level


@test("held off (0.104.139): an evil land's undead on the surface don't hold the gates shut; invaders and great ones do")
def _():
    from planner_core import held_off_threats
    s = fort()
    s["others_on_map"]["threats"] = [{"id": 1, "kinds": ["Undead"], "layer": "upper_levels", "can_reach_dwarves": False}]
    assert held_off_threats(s) == []
    s["others_on_map"]["threats"].append({"id": 2, "invader": True, "can_reach_dwarves": False})
    s["others_on_map"]["threats"].append({"id": 3, "kinds": ["Undead"], "great_danger": True, "layer": "upper_levels"})
    assert [x["id"] for x in held_off_threats(s)] == [2, 3]


@test("chunk D (0.104.140): a second wave gets the squad's order; invaders by the depot in a caravan reach; a changed werebeast is fought; corpses after an attack")
def _():
    from planner import record
    s = under_attack(n=2)
    for q in s["military"]["squads"]:
        q.update(ai_orders=1, kill_ids=[900])                          # out after the first goblin only
    a = by_rule(plan(copy.deepcopy(s), Memory())[0], "squad_attack")
    assert a and set(a[0].action["kill"]) == {900, 901} and "more enemies" in a[0].reason, a
    for q in s["military"]["squads"]:
        q["kill_ids"] = [900, 901]
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "squad_attack"), "nobody new"
    # (review) old targets kept; an id sent once and refused (not in the order) isn't new again
    for q in s["military"]["squads"]:
        q["kill_ids"] = [777]                                          # a berserk dwarf it was sent at
    m = Memory()
    a = by_rule(plan(copy.deepcopy(s), m)[0], "squad_attack")
    assert a and a[0].action["kill"][0] == 777 and {900, 901} <= set(a[0].action["kill"]), a
    record([(x, {"ok": True}) for x in a], s, m)
    assert not by_rule(plan(copy.deepcopy(s), m)[0], "squad_attack"), "the game refused 900/901: not again"
    d = under_attack(n=1)
    d["others_on_map"]["threats"][0].update(can_reach_dwarves=None, depot_distance=8)   # (behind a wall: False, not counted)
    d["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    assert not by_rule(plan(copy.deepcopy(d), Memory())[0], "squad_attack"), "no caravan in"
    d["others_on_map"]["merchants"] = 6
    assert by_rule(plan(copy.deepcopy(d), Memory())[0], "squad_attack")
    w = fort()
    w["hazards"] = dict(w.get("hazards") or {}, berserk=[{"id": 44, "name": "Urist", "changed": True}])
    p, notes = plan(w, Memory())
    a = by_rule(p, "squad_attack")
    assert a and a[0].action["kill"] == [44] and "changed into a beast" in a[0].reason, a
    c = fort()
    m = Memory(last_threat_tick=abs_tick(c) - 10 * TICKS_PER_DAY, quiet_cycles=50)
    g = by_rule(plan(copy.deepcopy(c), m)[0], "siege_cleanup")
    assert g and g[0].action == {"type": "prune_remains"}, g
    record([(g[0], {"ok": True})], c, m)
    assert not by_rule(plan(copy.deepcopy(c), m)[0], "siege_cleanup"), "once an attack"


@test("gate guard (0.104.83): invaders on the map out of reach -> the able squads hold the main gate; then kill orders")
def _():
    s = under_attack()
    for th in s["others_on_map"]["threats"]:
        th["can_reach_dwarves"] = False
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s["entrances"] = {"scanned": True, "entrances": [{"id": 1, "kind": "surface", "x": 10, "y": 10, "z": 50},
                                                    {"id": 2, "kind": "surface", "x": 94, "y": 95, "z": 168}]}
    m = Memory()
    m.atlas = {"plan": {"spine": {"x": 94, "y": 96}}}
    p, _ = plan(s, m)
    g = by_rule(p, "gate_guard")
    assert g and g[0].action == {"type": "guard_gate", "x": 94, "y": 95, "z": 168, "squads": [11, 12]}, g   # the main gate
    assert not by_rule(p, "squad_attack") and g[0].priority == 0
    for q in s["military"]["squads"]:
        q.update(ai_orders=1, orders=1, guarding=True)
    p, _ = plan(s, m)
    assert not by_rule(p, "gate_guard") and not by_rule(p, "squad_recall")      # holding: not called back
    s["others_on_map"]["threats"] = []
    assert by_rule(plan(s, m)[0], "squad_recall")                               # gone: back to work
    s = under_attack()
    s["entrances"] = {"scanned": True, "entrances": [{"id": 1, "kind": "surface", "x": 10, "y": 10, "z": 50}]}
    p, _ = plan(s, m)
    assert by_rule(p, "squad_attack") and not by_rule(p, "gate_guard")          # in reach: the kill orders
    s = under_attack()
    for th in s["others_on_map"]["threats"]:
        th.update(can_reach_dwarves=False, invader=False)                       # a cavern beast: no guard
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s["entrances"] = {"scanned": True, "entrances": [{"id": 1, "kind": "surface", "x": 10, "y": 10, "z": 50}]}
    assert not by_rule(plan(s, m)[0], "gate_guard")


@test("gate dogs (0.104.83): war-trained animals with no post are penned inside the main gate")
def _():
    s = fort()
    s["entrances"] = {"scanned": True, "entrances": [{"id": 1, "kind": "surface", "x": 10, "y": 10, "z": 50}]}
    s["society"]["animals"] = {"war_candidates": 0, "war_trained": 6, "in_training": 0, "trainers": 3,
                               "gate": {"free": 6, "pen": None, "posted": 0}}
    d = by_rule(plan(s, Memory())[0], "gate_dogs")
    assert d and d[0].action == {"type": "gate_dogs", "x": 10, "y": 10, "z": 50, "max": 4}, d
    s["society"]["animals"]["gate"]["free"] = 0
    assert not by_rule(plan(s, Memory())[0], "gate_dogs")


@test("military: enemies can reach the dwarves -> every able squad is sent, at once")
def _():
    s = under_attack()
    p, _ = plan(s, Memory())
    a = by_rule(p, "squad_attack")
    assert [x.action["squad_id"] for x in a] == [11, 12] and a[0].action["kill"] == [900, 901], a
    assert a[0].priority == 0
    allowed, _ = select(p, s, Memory())
    assert len([x for x in allowed if x.rule == "squad_attack"]) == 2       # both, same cycle


@test("military: great beasts aren't attacked by default; 'all' does; 'never' sends nobody")
def _():
    s = under_attack(great=True)
    p, notes = plan(s, Memory())
    assert not by_rule(p, "squad_attack") and any("great danger" in n for n in notes), notes
    s["settings"]["attack_policy"] = "all"
    assert by_rule(plan(s, Memory())[0], "squad_attack")
    s = under_attack()
    s["settings"]["attack_policy"] = "never"
    assert not by_rule(plan(s, Memory())[0], "squad_attack")


@test("military: a squad already on the AI's orders isn't sent twice; tiny squads stay home")
def _():
    s = under_attack()
    s["military"]["squads"][0]["ai_orders"] = 1
    s["military"]["squads"][1]["members"] = 2
    p, notes = plan(s, Memory())
    assert not by_rule(p, "squad_attack") and not any("no squad has" in n for n in notes)
    s["military"]["squads"][0]["members"] = 1
    _, notes = plan(s, Memory())
    assert any("no squad has 3+ armed soldiers" in n for n in notes), notes


@test("military: threat gone -> squads on the AI's orders are called back (only those)")
def _():
    s = fort()
    s["military"]["squads"][1]["ai_orders"] = 1
    s["military"]["squads"][0]["orders"] = 2                       # the player's own orders
    r = by_rule(plan(s, Memory())[0], "squad_recall")
    assert [x.action for x in r] == [{"type": "squad_orders", "squad_id": 12, "clear": True}], r


@test("military: alert, gate and every squad go out together, whatever the action limit")
def _():
    s = under_attack()
    s["military"]["gates"] = [{"id": 77, "state": 0, "linked": 1, "pending": False}]
    s["civ_alert"] = False
    s["civ_alert_ready"] = True
    p, _ = plan(s, Memory())
    p += [x for x in plan(fort(stocks__drink=10), Memory())[0]]       # plus routine work
    allowed, held = select(p, s, Memory())
    rules_ = [x.rule for x in allowed]
    assert {"threat_alert", "gate"} <= set(rules_) and rules_.count("squad_attack") == 2, rules_


@test("military: the AI gate lever is pulled on a threat, and back after it's quiet")
def _():
    from planner import note_gate_lever as note_cycle    # (0.105.33) the lever read each cycle
    s = under_attack()
    s["military"]["gates"] = [{"id": 77, "state": 0, "linked": 1, "pending": False}]
    m = Memory()
    note_cycle(s, m)                                                       # the lever's open state learnt
    g = by_rule(plan(s, m)[0], "gate")
    assert g and g[0].action == {"type": "pull_gate", "lever_id": 77}, g
    record([(g[0], {"ok": True})], s, m)
    s["military"]["gates"] = [{"id": 77, "state": 1, "linked": 1, "pending": False}]   # (0.105.33) the dwarf pulled it
    note_cycle(s, m)
    assert m.gate_closed_by_ai and not by_rule(plan(s, m)[0], "gate")     # not pulled twice
    quiet = fort()
    quiet["military"]["gates"] = s["military"]["gates"]
    note_cycle(quiet, m)
    m.quiet_cycles = 1
    assert not by_rule(plan(quiet, m)[0], "gate")                          # not yet
    m.quiet_cycles = 3
    g = by_rule(plan(quiet, m)[0], "gate")
    assert g, "pulled back after 3 quiet cycles"
    record([(g[0], {"ok": True})], quiet, m)
    quiet["military"]["gates"] = [{"id": 77, "state": 0, "linked": 1, "pending": False}]
    note_cycle(quiet, m)
    assert not m.gate_closed_by_ai


@test("needs you: things only the player can set up are marked; an unlinked lever isn't one any more")
def _():
    s = fort()
    s["military"]["gates"] = [{"id": 77, "state": 0, "linked": 0, "pending": False}]
    _, notes = plan(s, Memory())
    assert not any("isn't linked" in n for n in notes), notes
    s = under_attack()
    s["civ_alert_ready"] = False
    s["settings"]["alert_shelter"] = False
    _, notes = plan(s, Memory())
    # (0.105.35) the player's switch: said with what the AI does meanwhile, not Needs you
    assert any(not n.startswith("[you] ") and "civilian-alert" in n and "meanwhile" in n for n in notes), notes
    assert not any(n.startswith("[you] ") and "civilian-alert" in n for n in notes), notes


def entrances(*es, armed=False, age_days=1):
    s = fort()
    now = s["date"]["year"] * 403200 + s["date"]["tick"]
    s["entrances"] = {"scanned": True, "scanned_tick": now - age_days * 1200, "armed": armed,
                      "entrances": [dict({"id": i + 1, "kind": "surface", "x": 10, "y": 10 + i, "z": 173,
                                          "width": 1, "sealed": False, "equipment": [], "door_spots": 0}, **e)
                                    for i, e in enumerate(es)]}
    return s


@test("gate parts (0.104.105): a hatch planned over the stair waits for a cover -> the mason makes one")
def _():
    s = entrances({"closing": True, "waiting": {"hatch": 1}, "closing_days": 30})
    s["entrances"]["parts"] = {"hatch_covers": 0, "hatch_covers_held": 0, "doors": 5, "doors_held": 0}
    parts = lambda st: by_rule(plan(copy.deepcopy(st), Memory())[0], "gate_parts")
    got = parts(s)
    assert [(p.action["recipe"], p.action["amount"]) for p in got] == [("stone_hatch_cover", 1)], got
    assert got[0].is_order and "x10 y10" in got[0].reason, got[0].reason
    s["orders"] = list(s.get("orders") or []) + [{"recipe": "stone_hatch_cover", "amount_left": 1, "amount_total": 1}]
    assert not parts(s)                                              # queued already
    s["orders"] = []
    s["entrances"]["parts"]["hatch_covers_held"] = 1                 # one on its way to the job
    assert not parts(s)
    s["entrances"]["parts"].update(hatch_covers=2, hatch_covers_held=0)   # covers free, waited a month
    _, notes = plan(copy.deepcopy(s), Memory())[:2]
    # (0.104.139) the free ones may be heirlooms the game won't use: one more is made after the wait
    got = parts(s)
    assert [(p.action["recipe"], p.action["amount"]) for p in got] == [("stone_hatch_cover", 1)], got
    assert any("hatch cover planned" in n and "suspended" in n for n in notes), notes
    m = Memory()                                                     # (review) once for each stuck entrance
    assert by_rule(plan(copy.deepcopy(s), m)[0], "gate_parts") and not by_rule(plan(copy.deepcopy(s), m)[0], "gate_parts")
    s["entrances"]["entrances"][0]["closing_days"] = 3
    assert not parts(s)                                              # not before the wait
    del s["entrances"]["parts"]                                      # an older bridge: nothing guessed
    assert not parts(s)


@test("gates: many entrances doors can't close -> ONE needs-you item, widest named first")
def _():
    s = entrances(*[{"width": w, "door_spots": 0, "kind": k}
                    for w, k in ((5, "cavern"), (24, "surface"), (1, "cavern"), (9, "cavern"), (12, "surface"))])
    s["settings"]["fortify_entrances"] = False
    _, notes = plan(s, Memory())
    you = [n for n in notes if "can't be closed" in n]
    assert len(you) == 1 and "off on the Rules tab" in you[0] and "5 entrance(s)" in you[0] and "2 to the surface, 3 to the caverns" in you[0], you
    assert you[0].index("(24 wide)") < you[0].index("(12 wide)") < you[0].index("(9 wide)"), you


@test("gates: never mapped, or a week old -> map the entrances (at once if a threat is near)")
def _():
    s = fort()
    s["entrances"] = {"scanned": False}
    e = by_rule(plan(s, Memory())[0], "entrances")
    assert e and e[0].action == {"type": "scan_entrances"} and e[0].priority == 5, e
    s = entrances({"sealed": True, "equipment": [{"id": 1, "kind": "door"}]}, age_days=8)
    assert by_rule(plan(s, Memory())[0], "entrances")
    assert not by_rule(plan(entrances(age_days=2), Memory())[0], "entrances")


@test("gates: a threat -> the watcher is armed (it closes when everyone's in or danger is close)")
def _():
    s = entrances({"sealed": True, "equipment": [{"id": 1, "kind": "door"}]})
    s["others_on_map"]["threats"] = [{"id": 900, "name": "Goblin", "can_reach_dwarves": True}]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    g = by_rule(plan(s, Memory())[0], "gates")
    assert g and g[0].action == {"type": "arm_gates"} and g[0].priority == 0, g
    s["entrances"]["armed"] = True
    assert not by_rule(plan(s, Memory())[0], "gates")                        # already watching


@test("gates (0.104.81): a gate watcher that errors is said, not swallowed; (0.105.35) a plain note of what the AI does")
def _():
    s = entrances({"sealed": True, "equipment": [{"id": 1, "kind": "door"}]}, armed=True)
    _, notes = plan(s, Memory())
    assert not any("gate watcher" in n for n in notes)
    s["entrances"]["watch_error"] = {"n": 4, "error": "attempt to index a nil value", "tick": 100}
    _, notes = plan(s, Memory())
    n = [x for x in notes if "gate watcher failed 4 time(s)" in x]
    assert n and not n[0].startswith(("Needs you", "[you]")) and "nil value" in n[0], notes


@test("gates: quiet for 3 cycles -> opened again")
def _():
    s = entrances({"sealed": True, "equipment": [{"id": 1, "kind": "door"}]}, armed=True)
    m = Memory(quiet_cycles=1)
    assert not by_rule(plan(s, m)[0], "gates")
    m.quiet_cycles = 3
    assert by_rule(plan(s, m)[0], "gates")[0].action == {"type": "open_gates"}


@test("gates: an open narrow entrance gets doors (once); a wide one is walled; too wide -> Needs you")
def _():
    s = entrances({"door_spots": 2, "width": 2}, {"door_spots": 0, "width": 6, "x": 40, "y": 50},
                  {"door_spots": 0, "width": 80, "x": 90, "y": 50})
    p, notes = plan(s, Memory())
    d = by_rule(p, "gate_doors")
    assert d and d[0].action == {"type": "build_gate_doors", "entrance_id": 1}, d
    f = by_rule(p, "fortify")
    assert f and f[0].action == {"type": "fortify_entrance", "entrance_id": 2, "style": "plain"}, f
    assert any(n.startswith("[you] ") and "1 entrance(s) can't be closed" in n and "(80 wide)" in n
               and "wider than 50" in n and "elevation" in n for n in notes), notes
    m = Memory()
    record([(d[0], {"ok": True, "doors": 2})], s, m)
    assert m.gate_doors_requested == ["10,10,173"] and not by_rule(plan(s, m)[0], "gate_doors")
    s["settings"]["build_gate_doors"] = False
    assert not by_rule(plan(s, Memory())[0], "gate_doors")


@test("gates: the gate style follows the fort's sliders and history")
def _():
    s = entrances({"door_spots": 0, "width": 6})
    style = lambda: by_rule(plan(s, m)[0], "fortify")[0].action["style"]
    m = Memory()
    assert style() == "plain"
    s["settings"]["traits"] = {"caution": 60}
    assert style() == "narrow"
    s["settings"]["traits"] = {"grandeur": 100}
    assert style() == "grand"
    s["settings"]["traits"] = {"fortification": 100, "engineering": 60}
    assert style() == "gatehouse"
    s["settings"]["traits"] = {}
    m.culture = {"sieges": 2}
    assert style() == "fortified"


@test("gates: a refused build is remembered with the game's reason, not asked again for 2 weeks, shown once")
def _():
    s = entrances({"door_spots": 2, "width": 2}, {"door_spots": 0, "width": 6, "x": 40, "y": 50})
    m = Memory()
    p, _ = plan(s, m)
    d, f = by_rule(p, "gate_doors")[0], by_rule(p, "fortify")[0]
    record([(d, {"ok": False, "error": "no door could be placed there (build_unsuitable)"}),
            (f, {"ok": False, "error": "walls there would cut off 120 tiles of the fort"})], s, m)
    assert set(m.gate_failures) == {"10,10,173", "40,50,173"}, m.gate_failures
    p, notes = plan(s, m)
    assert not by_rule(p, "gate_doors") and not by_rule(p, "fortify")
    you = [n for n in notes if "refused to build" in n]
    assert len(you) == 1 and "2 entrance(s)" in you[0] and "build_unsuitable" in you[0], notes


@test("gates: once walled, that entrance (even its new gap) waits for the dwarves")
def _():
    s = entrances({"door_spots": 0, "width": 6, "x": 40, "y": 50})
    m = Memory()
    f = by_rule(plan(s, m)[0], "fortify")[0]
    record([(f, {"ok": True, "walls": 4, "doors": 2})], s, m)
    assert m.gates_fortified == {"40,50,173": "plain"}
    assert not by_rule(plan(s, m)[0], "fortify")
    # walls up: the scan now sees a 2-wide gap a tile over
    s2 = entrances({"door_spots": 2, "width": 2, "x": 42, "y": 50})
    assert not by_rule(plan(s2, m)[0], "gate_doors")
    s["settings"]["fortify_entrances"] = False
    assert not by_rule(plan(s, Memory())[0], "fortify")


@test("gates 5a: doors that had to wait for their walls (or a support wall) go in once the walls stand")
def _():
    s = entrances({"door_spots": 0, "width": 6, "x": 40, "y": 50})
    m = Memory()
    f = by_rule(plan(s, m)[0], "fortify")[0]
    record([(f, {"ok": True, "walls": 4, "doors": 0, "doors_later": 2})], s, m)
    assert m.gates_fortified == {"40,50,173": "plain, doors later"}
    assert not by_rule(plan(s, m)[0], "fortify")
    s2 = entrances({"door_spots": 2, "width": 2, "x": 42, "y": 50})
    d = by_rule(plan(s2, m)[0], "gate_doors")
    assert d and d[0].action["type"] == "build_gate_doors", d


@test("gates water: deep water as the gate is remembered, never asked again; the atlas keeps what the AI found")
def _():
    s = entrances({"door_spots": 0, "width": 1, "x": 14, "y": 108})
    m = Memory()
    f = by_rule(plan(s, m)[0], "fortify")[0]
    r = {"ok": True, "water_gate": True, "walls": 0, "doors": 0,
         "water": "natural pool, 40 tiles over 1 level(s), up to 7/7 deep (40 tiles 4/7 or deeper)"}
    record([(f, r)], s, m)
    assert list(m.gates_fortified.values())[0].startswith("water@")
    assert not by_rule(plan(s, m)[0], "fortify")
    import atlas
    lines = atlas.note_actions([(f, r)], s, m)
    assert any("left to its water" in x and "natural pool" in x for x in lines), lines
    assert "natural pool" in m.atlas["entrances"]["14,108,173"]["water"]
    # a later scan: still open (nothing was built) but not "open again"
    later = entrances({"door_spots": 0, "width": 1, "x": 14, "y": 108}, age_days=0)
    later["entrances"]["scanned_tick"] += 5000
    assert not [x for x in atlas.note_entrances(later, m) if "open again" in x]
    # a real opening 3 tiles away isn't hidden by it
    near = entrances({"door_spots": 0, "width": 2, "x": 14, "y": 111})
    assert by_rule(plan(near, m)[0], "fortify")
    # a season on, the water is looked at again
    s["date"]["tick"] += 3 * 28 * 1200 + 1
    s["entrances"]["scanned_tick"] += 3 * 28 * 1200 + 1             # (a fresh scan)
    assert by_rule(plan(s, m)[0], "fortify")


@test("gates water: a water refusal from before the AI looked at water is tried again at once")
def _():
    s = entrances({"door_spots": 0, "width": 1, "x": 14, "y": 108})
    m = Memory()
    now = s["date"]["year"] * 403200 + s["date"]["tick"]
    m.gate_failures["14,108,173"] = ("something is already in the opening at x14 y108 (FLOOR, STONE, liquid 7/7) "
                                     "(water or magma stands there), and no clear line for a gate within 3 tiles")
    m.gate_failure_ticks["14,108,173"] = now - 100
    assert by_rule(plan(s, m)[0], "fortify")
    m.gate_failures["14,108,173"] += "; the AI looked: natural pool ... (the fort uses this water)"
    assert not by_rule(plan(s, m)[0], "fortify")


@test("0.105.12/0.105.23 machinery: on by default; a lever for the founding hatch, then linked; none elsewhere")
def _():
    hatch = [{"id": 7, "kind": "hatch", "lever_away": False, "levers": []}]
    s = entrances({"door_spots": 0, "width": 1, "x": 108, "y": 149, "sealed": True, "equipment": hatch})
    s["settings"]["traits"] = {"engineering": 60}
    eid = s["entrances"]["entrances"][0]["id"]
    assert PLANNER_CONFIG["hatch_levers"] is True                      # (0.105.23) switched on
    g = by_rule(plan(s, Memory())[0], "gate_lever")
    assert g and g[0].action == {"type": "place_gate_lever", "entrance_id": eid}, [p.action for p in g]
    s["entrances"]["free_levers"] = [{"id": 90, "x": 108, "y": 120, "z": 160}]
    g = by_rule(plan(s, Memory())[0], "gate_lever")
    assert g and g[0].action == {"type": "link_lever", "lever_id": 90, "target_id": 7}, [p.action for p in g]
    s["settings"]["traits"] = {"engineering": 0, "fortification": 0}
    assert not by_rule(plan(s, Memory())[0], "gate_lever")
    s["entrances"]["free_levers"] = []
    assert not by_rule(plan(s, Memory())[0], "gate_lever")
    PLANNER_CONFIG["hatch_levers"] = False
    try:
        s["settings"]["traits"] = {"engineering": 60}
        assert not by_rule(plan(s, Memory())[0], "gate_lever")         # switched off: nothing
    finally:
        PLANNER_CONFIG["hatch_levers"] = True


@test("0.105.23 hatch levers: 3 free mechanisms before a lever; a cut's many hatches get none; drawbridges first")
def _():
    hatch = [{"id": 7, "kind": "hatch", "lever_away": False, "levers": []}]
    s = entrances({"door_spots": 0, "width": 1, "x": 108, "y": 149, "sealed": True, "equipment": hatch})
    s["settings"]["traits"] = {"fortification": 120}
    s["entrances"]["free_mechanisms"] = 1
    p, _ = plan(copy.deepcopy(s), Memory())[:2]
    assert not by_rule(p, "gate_lever"), [x.action for x in by_rule(p, "gate_lever")]
    m = [x for x in by_rule(p, "mechanisms") if "gate lever" in x.reason]
    assert m and m[0].action["amount"] == 2 and m[0].is_order, [x.action for x in by_rule(p, "mechanisms")]
    s["entrances"]["free_mechanisms"] = 3
    assert by_rule(plan(copy.deepcopy(s), Memory())[0], "gate_lever")
    # a cut entrance (hatches on every stair down): no lever for its hatches
    cut = copy.deepcopy(s)
    cut["entrances"]["entrances"][0].update(cut=True, cut_hatches=5, equipment=[
        {"id": 20 + i, "kind": "hatch", "lever_away": False, "levers": []} for i in range(5)])
    assert not by_rule(plan(cut, Memory())[0], "gate_lever")
    # a hatch and an unworked drawbridge at another entrance: the bridge takes the free lever first
    two = entrances({"door_spots": 0, "width": 1, "x": 108, "y": 149, "sealed": True, "equipment": hatch},
                    {"door_spots": 0, "width": 2, "x": 140, "y": 149, "sealed": True,
                     "equipment": [{"id": 30, "kind": "door", "levers": []}], "bridges_unworked": [31]})
    two["settings"]["traits"] = {"fortification": 120}
    two["entrances"]["free_levers"] = [{"id": 90, "x": 108, "y": 120, "z": 160}]
    g = by_rule(plan(two, Memory())[0], "gate_lever")
    assert g and g[0].action == {"type": "link_lever", "lever_id": 90, "target_id": 31}, [x.action for x in g]
    # a gatehouse standing, its drawbridge not built yet: the hatch waits for it (the bridge's lever first)
    gh = copy.deepcopy(s)
    gh["entrances"]["entrances"][0]["gatehouse"] = "standing"
    gh["entrances"]["free_levers"] = [{"id": 90, "x": 108, "y": 120, "z": 160}]
    assert not by_rule(plan(copy.deepcopy(gh), Memory())[0], "gate_lever")
    gh["entrances"]["entrances"][0]["outer"] = [{"id": 40, "kind": "bridge", "lever_id": 91}]
    assert by_rule(plan(gh, Memory())[0], "gate_lever")


@test("0.105.23 rescan: a lever linked since the scan (the bridge's `rescan`) maps the entrances again")
def _():
    s = entrances({"door_spots": 0, "width": 1, "sealed": True,
                   "equipment": [{"id": 7, "kind": "hatch", "levers": [90], "lever_driven": True}]})
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "entrances")
    s["entrances"]["rescan"] = True
    assert by_rule(plan(copy.deepcopy(s), Memory())[0], "entrances")


def gatehouse_fort(fortification=120, **e):
    s = entrances(dict({"door_spots": 0, "width": 1, "x": 108, "y": 149, "z": 160, "sealed": True, "lid": True,
                        "gatehouse": "possible",
                        "equipment": [{"id": 7, "kind": "hatch", "levers": [90], "lever_driven": True}]}, **e))
    s["settings"]["traits"] = {"fortification": fortification}
    s["entrances"]["free_mechanisms"] = 20
    return s


@test("0.105.23 gatehouse: a fortified fort builds one at the founding stair, once; not a mild fort, not in danger")
def _():
    s = gatehouse_fort()
    g = by_rule(plan(copy.deepcopy(s), Memory())[0], "gatehouse")
    assert g and g[0].action["type"] == "build_gatehouse" and g[0].action["entrance_id"] == 1, [x.action for x in g]
    assert g[0].action["kind"] in ("cage", "stonefall", "weapon") and 2 <= g[0].action["count"] <= 4, g[0].action
    assert not by_rule(plan(gatehouse_fort(fortification=40), Memory())[0], "gatehouse")
    assert not by_rule(plan(gatehouse_fort(gatehouse="standing"), Memory())[0], "gatehouse")
    assert not by_rule(plan(gatehouse_fort(gatehouse="none", gatehouse_why="no room"), Memory())[0], "gatehouse")
    # built: remembered by its spot, never again there
    m = Memory()
    record([(g[0], {"ok": True, "bridge": {"x": 112, "y": 149, "z": 161}, "dir": "gd"})], s, m)
    assert "108,149,160" in m.gatehouses, m.gatehouses
    assert not by_rule(plan(copy.deepcopy(s), m)[0], "gatehouse")
    # refused: waits gate_retry_ticks
    m = Memory()
    record([(g[0], {"ok": False, "error": "the game would not place the drawbridge: x"})], s, m)
    assert "gatehouse:108,149,160" in m.gate_failures
    assert not by_rule(plan(copy.deepcopy(s), m)[0], "gatehouse")
    # a threat that can reach the dwarves: not now
    d = copy.deepcopy(s)
    d.setdefault("others_on_map", {})["threats_that_can_reach_dwarves"] = 2
    d["others_on_map"]["threats"] = [{"id": 5, "name": "goblin", "can_reach_dwarves": True}]
    assert not by_rule(plan(d, Memory())[0], "gatehouse")
    # short of mechanisms: ordered beside it
    s["entrances"]["free_mechanisms"] = 1
    p = plan(copy.deepcopy(s), Memory())[0]
    assert by_rule(p, "gatehouse") and any("gatehouse" in x.reason for x in by_rule(p, "mechanisms")), \
        [x.reason for x in by_rule(p, "mechanisms")]


def _access(p):
    """(0.105.26) a location_access action without the mayor's rest it carries"""
    return {k: v for k, v in p.action.items() if k != "visitor_shut"}


@test("0.105.12 locations: a closed fort shuts its tavern, temple, library, guildhalls to visitors; reopened later")
def _():
    from planner import _location_access_rule, record, note_locations
    s = fort()
    both = ["VISITORS_ALLOWED", "NON_CITIZENS_ALLOWED"]
    s["locations"] = {"count": {}, "list": [{"id": 1, "type": "INN_TAVERN", "flags": list(both)},
                                            {"id": 2, "type": "HOSPITAL", "flags": list(both)},
                                            {"id": 3, "type": "TEMPLE", "flags": ["NON_CITIZENS_ALLOWED"]},
                                            {"id": 4, "type": "GUILDHALL", "flags": list(both)}]}
    s["settings"]["traits"] = {"outsiders": -150}
    m = Memory()
    props = []
    _location_access_rule(s, m, PLANNER_CONFIG, props, [])
    assert len(props) == 1 and _access(props[0]) == {"type": "location_access", "ids": [1, 4], "visitors": False}, props
    record([(props[0], {"ok": True, "changed": [1, 4]})], s, m)
    assert m.locations_closed == [1, 4]
    # (review) you open one again: it's yours, forgotten and never shut again
    s["locations"]["list"][0]["flags"] = ["NON_CITIZENS_ALLOWED"]
    s["locations"]["list"][3]["flags"] = ["VISITORS_ALLOWED", "NON_CITIZENS_ALLOWED"]
    s["locations"]["built"] = abs_tick(s) + 1          # (0.105.26) a report built since the shut
    props = []
    _location_access_rule(s, m, PLANNER_CONFIG, props, [])
    note_locations(s, m, PLANNER_CONFIG)               # (0.105.26) the bookkeeping, outside plan()
    assert not props and m.locations_closed == [1], (props, m.locations_closed)
    s["locations"]["list"][3]["flags"] = ["NON_CITIZENS_ALLOWED"]
    # neutral: nothing; welcoming again: the AI's own reopened (not the player's temple)
    s["locations"]["list"][0]["flags"] = ["NON_CITIZENS_ALLOWED"]
    s["locations"]["list"][3]["flags"] = ["NON_CITIZENS_ALLOWED"]
    s["settings"]["traits"] = {"outsiders": 60}
    props = []
    _location_access_rule(s, m, PLANNER_CONFIG, props, [])
    assert len(props) == 1 and _access(props[0]) == {"type": "location_access", "ids": [1], "visitors": True}, props
    record([(props[0], {"ok": True, "changed": [1]})], s, m)
    assert m.locations_closed == []


@test("0.105.24 heists: an artifact thief or a visitor's killing shuts the locations to visitors a while, then reopens")
def _():
    from planner import _location_access_rule, record
    from planner_society import note_heists, heist_lockout
    s = fort()
    both = ["VISITORS_ALLOWED", "NON_CITIZENS_ALLOWED"]
    s["locations"] = {"count": {}, "list": [{"id": 1, "type": "INN_TAVERN", "flags": list(both)},
                                            {"id": 2, "type": "HOSPITAL", "flags": list(both)},
                                            {"id": 3, "type": "LIBRARY", "flags": list(both)}]}
    s["settings"]["traits"] = {"outsiders": 0}
    m = Memory()
    props = []
    _location_access_rule(s, m, PLANNER_CONFIG, props, [])
    assert not props                                                  # a neutral fort with no heist: open
    # what doesn't count: a snatcher's words, a berserk citizen killed by a bard, an old wound, a raider's killing
    n = note_heists(s, m, [
        {"kind": "report", "topic": "thief", "text": "The Goblin Snatcher Ngom was spotted sneaking around!  \"I'll live to fight another day!\""},
        {"kind": "death", "own_civ": True, "killer": "Thîkut, Bard", "killer_kind": "outsider", "killer_visitor": True,
         "mood": "Berserk"},
        {"kind": "death", "own_civ": True, "killer": "Amxu, Goblin Dancer", "killer_kind": "outsider",
         "killer_visitor": True, "killer_dead": True},
        {"kind": "death", "own_civ": True, "killer": "Gulo, Human Spearman", "killer_kind": "outsider"}])
    assert n == 0 and not m.heists and heist_lockout(s, m, PLANNER_CONFIG) is None, m.heists
    # (E, 3 Nov 00:49) the baroness consort who had met the mayor, after an artifact
    heist = {"kind": "report", "topic": "thief", "text": "The Human baroness consort Lalgi Aspaescu was spotted "
             "sneaking around!  \"You will not stand between me and Oiledgullies the Drips of Helping!\""}
    assert note_heists(s, m, [heist, dict(heist)]) == 1 and m.heists[0][1] == "Human baroness consort Lalgi Aspaescu", m.heists
    props = []
    _location_access_rule(s, m, PLANNER_CONFIG, props, [])
    assert len(props) == 1 and _access(props[0]) == {"type": "location_access", "ids": [1, 3], "visitors": False}, props
    assert "Lalgi" in props[0].reason and "168 more day" in props[0].reason, props[0].reason
    record([(props[0], {"ok": True, "changed": [1, 3]})], s, m)
    for e in s["locations"]["list"]:
        if e["id"] in (1, 3):
            e["flags"] = ["NON_CITIZENS_ALLOWED"]
    props = []
    _location_access_rule(s, m, PLANNER_CONFIG, props, [])
    assert not props                                                  # shut: nothing more
    # the lockout over: the ones the AI shut open again
    later = copy.deepcopy(s)
    later["date"]["tick"] += 169 * TICKS_PER_DAY
    props = []
    _location_access_rule(later, m, PLANNER_CONFIG, props, [])
    assert len(props) == 1 and _access(props[0]) == {"type": "location_access", "ids": [1, 3], "visitors": True}, props
    assert "no heist for 168 days" in props[0].reason, props[0].reason
    # a visitor who killed a citizen (not berserk, alive) counts too; off at 0 days
    m2 = Memory()
    assert note_heists(s, m2, [{"kind": "death", "own_civ": True, "killer": "Lòr Kadolmigrur, Scholar",
                                "killer_kind": "outsider", "killer_visitor": True}]) == 1
    assert heist_lockout(s, m2, PLANNER_CONFIG) and heist_lockout(s, m2, dict(PLANNER_CONFIG, heist_lockout_days=0)) is None
    # a closed fort's own reason stands; the hospital is never shut
    s2 = copy.deepcopy(s)
    for e in s2["locations"]["list"]:
        e["flags"] = list(both)
    s2["settings"]["traits"] = {"outsiders": -150}
    props = []
    _location_access_rule(s2, m2, PLANNER_CONFIG, props, [])
    assert props and "keeps to itself" in props[0].reason and 2 not in props[0].action["ids"], props


@test("0.105.24 heist_lockout switch: off, no lockout and one under way lifted; on, as before")
def _():
    from planner import _location_access_rule, record, player_rules
    from planner_society import note_heists, heist_lockout
    both = ["VISITORS_ALLOWED", "NON_CITIZENS_ALLOWED"]
    s = fort()
    s["locations"] = {"count": {}, "list": [{"id": 1, "type": "INN_TAVERN", "flags": list(both)},
                                            {"id": 3, "type": "LIBRARY", "flags": list(both)}]}
    s["settings"]["traits"] = {"outsiders": 0}
    assert player_rules(s)["heist_lockout"] is True and player_rules(s)["shut_to_visitors"] is True
    heist = {"kind": "report", "topic": "thief", "text": "The Human baroness consort Lalgi Aspaescu was spotted "
             "sneaking around!  \"You will not stand between me and Oiledgullies the Drips of Helping!\""}
    # off: a heist shuts nothing
    m = Memory()
    off = copy.deepcopy(s)
    off["settings"]["heist_lockout"] = False
    assert note_heists(off, m, [heist]) == 1 and heist_lockout(off, m, PLANNER_CONFIG) is None
    props = []
    _location_access_rule(off, m, PLANNER_CONFIG, props, [])
    assert not props, props
    # on: shut (as before)
    props = []
    _location_access_rule(s, m, PLANNER_CONFIG, props, [])
    assert len(props) == 1 and _access(props[0]) == {"type": "location_access", "ids": [1, 3], "visitors": False}, props
    record([(props[0], {"ok": True, "changed": [1, 3]})], s, m)
    # a library the player shut before: never the AI's
    s["locations"]["list"].append({"id": 4, "type": "LIBRARY", "flags": ["NON_CITIZENS_ALLOWED"]})
    for e in s["locations"]["list"]:
        e["flags"] = ["NON_CITIZENS_ALLOWED"]
    # switched off mid-lockout: the ones the AI shut open again at once, the player's stays shut
    off = copy.deepcopy(s)
    off["settings"]["heist_lockout"] = False
    props = []
    _location_access_rule(off, m, PLANNER_CONFIG, props, [])
    assert len(props) == 1 and _access(props[0]) == {"type": "location_access", "ids": [1, 3], "visitors": True}, props
    assert "off on the Rules tab" in props[0].reason, props[0].reason
    # a closed fort keeps them shut whatever the switch says
    off["settings"]["traits"] = {"outsiders": -150}
    props = []
    _location_access_rule(off, m, PLANNER_CONFIG, props, [])
    assert not props, props


def _swamped_fort(visitors=3, citizens=1, unheard=9, outsiders=60):
    s = fort()
    both = ["VISITORS_ALLOWED", "NON_CITIZENS_ALLOWED"]
    s["locations"] = {"count": {}, "list": [{"id": 1, "type": "INN_TAVERN", "flags": list(both)},
                                            {"id": 2, "type": "HOSPITAL", "flags": list(both)},
                                            {"id": 3, "type": "TEMPLE", "flags": list(both)},
                                            {"id": 5, "type": "TEMPLE", "flags": list(both)},
                                            {"id": 6, "type": "LIBRARY", "flags": ["NON_CITIZENS_ALLOWED"]}]}
    s["settings"]["traits"] = {"outsiders": outsiders}
    s["needs"] = dict(s.get("needs") or {}, stress_causes={"causes": [
        {"thought": "UnableComplain", "citizens": unheard, "about": {"vent_at_boss": unheard}}]})
    s["offices"] = {"offices": {"MAYOR": {"held": ["Oddom Nomaluker"]}}}
    s["meetings"] = {"activities": [{"actor": "Mosus, Poet", "noble": "Oddom Nomaluker, mayor", "visitor": True}],
                     "requests": visitors - 1 + citizens, "requests_visitors": visitors - 1}
    return s


@test("0.105.24 shut_to_visitors: a mayor swamped by visitors gets the locations shut to visitors a while, then open")
def _():
    from planner import _location_access_rule, record
    from planner_society import visitor_shut
    s = _swamped_fort()
    m = Memory()
    props, notes = [], []
    _location_access_rule(s, m, PLANNER_CONFIG, props, notes)
    # the library the player shut stays as it is (not the AI's); the hospital never
    assert len(props) == 1 and _access(props[0]) == {"type": "location_access", "ids": [1, 3, 5], "visitors": False}, props
    assert "mayor is swamped" in props[0].reason and "the tavern and 2 temples" in props[0].reason, props[0].reason
    w = props[0].action["visitor_shut"]                # (0.105.26) carried on the action, kept by record()
    assert w["until"] - w["tick"] == 56 * TICKS_PER_DAY and m.visitor_shut == {}, (w, m.visitor_shut)
    assert notes and "3 of the mayor's 4 meetings" in notes[0] and "56 more day" in notes[0], notes
    record([(props[0], {"ok": True, "changed": [1, 3, 5]})], s, m)
    for e in s["locations"]["list"]:
        if e["id"] in (1, 3, 5):
            e["flags"] = ["NON_CITIZENS_ALLOWED"]
    # held while it lasts, even with the mayor no longer swamped
    calm = copy.deepcopy(s)
    calm["meetings"] = {}
    calm["date"]["tick"] += 20 * TICKS_PER_DAY
    props, notes = [], []
    _location_access_rule(calm, m, PLANNER_CONFIG, props, notes)
    assert not props and notes and "36 more day" in notes[0], (props, notes)
    # over: the ones the AI shut open again (never the player's library), then looked at afresh
    later = copy.deepcopy(s)
    later["date"]["tick"] += 57 * TICKS_PER_DAY
    props = []
    _location_access_rule(later, m, PLANNER_CONFIG, props, [])
    assert len(props) == 1 and _access(props[0]) == {"type": "location_access", "ids": [1, 3, 5], "visitors": True}, props
    assert "56 days without visitors are over" in props[0].reason, props[0].reason
    record([(props[0], {"ok": True, "changed": [1, 3, 5]})], later, m)
    for e in later["locations"]["list"]:
        if e["id"] in (1, 3, 5):
            e["flags"] = ["VISITORS_ALLOWED", "NON_CITIZENS_ALLOWED"]
    props = []
    _location_access_rule(later, m, PLANNER_CONFIG, props, [])
    assert not props and "until" not in m.visitor_shut, (props, m.visitor_shut)    # opened: forgotten
    # (0.105.26) still swamped: shut afresh only for complaints made since the reopen
    props = []
    _location_access_rule(later, m, PLANNER_CONFIG, props, [])
    assert not props, props
    later["needs"]["stress_causes"]["causes"][0]["citizens"] = 9 + 5
    props = []
    _location_access_rule(later, m, PLANNER_CONFIG, props, [])
    assert props and props[0].action["visitors"] is False, props
    # not swamped: too few unheard, too few visitors, visitors not most of the meetings
    for kw in ({"unheard": 4}, {"visitors": 2, "citizens": 0}, {"visitors": 3, "citizens": 4}):
        props = []
        _location_access_rule(_swamped_fort(**kw), Memory(), PLANNER_CONFIG, props, [])
        assert not props, (kw, props)
    # the switch off, or a fort whose point is visitors (the Merchant city's Outsiders 100): nothing
    off = _swamped_fort()
    off["settings"]["shut_to_visitors"] = False
    for st in (off, _swamped_fort(outsiders=100)):
        props = []
        _location_access_rule(st, Memory(), PLANNER_CONFIG, props, [])
        assert not props and visitor_shut(st, Memory(), PLANNER_CONFIG) is None, props
    # switched off while it lasts: the AI's open again
    m2 = Memory()
    s2 = _swamped_fort()
    props = []
    _location_access_rule(s2, m2, PLANNER_CONFIG, props, [])
    record([(props[0], {"ok": True, "changed": [1, 3, 5]})], s2, m2)
    for e in s2["locations"]["list"]:
        e["flags"] = ["NON_CITIZENS_ALLOWED"]
    s2["settings"]["shut_to_visitors"] = False
    props = []
    _location_access_rule(s2, m2, PLANNER_CONFIG, props, [])
    assert len(props) == 1 and _access(props[0]) == {"type": "location_access", "ids": [1, 3, 5], "visitors": True}, props
    assert "mayor is off on the Rules tab" in props[0].reason, props[0].reason


@test("0.105.24 shut_to_visitors and the heist lockout: shut while either holds, the longer winning")
def _():
    from planner import _location_access_rule, record
    from planner_society import note_heists
    s = _swamped_fort()
    m = Memory()
    heist = {"kind": "report", "topic": "thief", "text": "The Goblin Thief Snodub was spotted "
             "sneaking around!  \"You will not stand between me and Bluegold!\""}
    assert note_heists(s, m, [heist]) == 1
    props, notes = [], []
    _location_access_rule(s, m, PLANNER_CONFIG, props, notes)
    assert len(props) == 1 and "Snodub" in props[0].reason and props[0].priority == 3, props   # the lockout: longer
    record([(props[0], {"ok": True, "changed": [1, 3, 5]})], s, m)
    for e in s["locations"]["list"]:
        e["flags"] = ["NON_CITIZENS_ALLOWED"]
    # the mayor's 56 days over, the lockout's 168 not: still shut
    later = copy.deepcopy(s)
    later["date"]["tick"] += 60 * TICKS_PER_DAY
    props = []
    _location_access_rule(later, m, PLANNER_CONFIG, props, [])
    assert not props, props
    # the heist switch off then: the mayor's rest is over too, so they open
    later["settings"]["heist_lockout"] = False
    props = []
    _location_access_rule(later, m, PLANNER_CONFIG, props, [])
    assert len(props) == 1 and props[0].action["visitors"] is True, props


@test("0.105.24 presets: the Merchant city turns shut_to_visitors off (visitors are its point)")
def _():
    src = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    assert code_has(src, "shut_to_visitors = false}") and code_has(src, "'shut_to_visitors'}")
    assert code_has(src, "heist_lockout = true,") and code_has(src, "shut_to_visitors = true,")
    gui = (ROOT / "lua" / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
    assert code_has(gui, "subviews.heist_lockout:setOption") and code_has(gui, "subviews.shut_to_visitors:setOption")


@test("0.105.9 traps: the founding stair's hatch is a gate: traps behind it")
def _():
    hatch = [{"id": 7, "kind": "hatch", "lever_away": False, "levers": []}]
    s = entrances({"door_spots": 0, "width": 1, "x": 108, "y": 149, "sealed": True, "equipment": hatch})
    s["settings"]["traits"] = {"fortification": 120, "engineering": 60, "caution": 60, "militarism": 150}
    t = by_rule(plan(s, Memory())[0], "traps")
    assert t and t[0].action["type"] == "place_traps" and t[0].action["entrance_id"] == s["entrances"]["entrances"][0]["id"], t
    m = Memory()
    m.culture = {"quirks": ["Trapsmiths"], "sieges": 4}            # (0.105.10) quirks add traps: never past 8 a call
    from quirks import has_rule
    t = by_rule(plan(s, m)[0], "traps")
    assert t and 1 <= t[0].action["count"] <= 8, t


@test("5b traps: a gate with no traps gets them in the fort's style; mechanisms ordered if too few; not twice")
def _():
    door = [{"id": 70, "kind": "door"}]
    s = entrances({"door_spots": 0, "width": 2, "x": 40, "y": 50, "sealed": True, "equipment": door})
    s["settings"]["traits"] = {"fortification": 100, "engineering": 100, "caution": 100}
    s["entrances"]["free_mechanisms"] = 2
    m = Memory()
    props = plan(s, m)[0]
    t = by_rule(props, "traps")
    assert t and t[0].action["type"] == "place_traps" and t[0].action["count"] == 7, t
    assert t[0].action["kind"] in ("cage", "stonefall", "weapon")
    o = by_rule(props, "mechanisms")
    assert o and o[0].action == {"type": "work_order", "recipe": "mechanisms", "amount": 5}, o
    # placed: the atlas has it, so not again (even filed 2 tiles off: walls move the entrance's tile)
    m.atlas = {"registry": {"traps:42,50,173": {"kind": "traps"}}}
    assert not by_rule(plan(s, m)[0], "traps")
    m.atlas = {"registry": {"gate:41,51,173": {"kind": "gate", "variant": "gatehouse"}}}
    assert not by_rule(plan(s, m)[0], "traps")                      # a gatehouse has its own
    # no answer from the game: not asked again at once
    m = Memory()
    p0 = by_rule(plan(s, m)[0], "traps")[0]
    record([(p0, {"ok": None, "error": "no reply"})], s, m)
    m.last_fired.pop("traps", None)
    assert not by_rule(plan(s, m)[0], "traps")
    # a fort that wants no traps, or a threat on the way: none
    s2 = entrances({"door_spots": 0, "width": 2, "x": 40, "y": 50, "sealed": True, "equipment": door})
    s2["settings"]["traits"] = {"fortification": -100, "engineering": -100}
    assert not by_rule(plan(s2, Memory())[0], "traps")
    s["others_on_map"]["threats"] = [{"id": 5, "name": "goblin", "can_reach_dwarves": True}]
    assert not by_rule(plan(s, Memory())[0], "traps")
    # refused: tried again in 2 weeks
    m = Memory()
    s = entrances({"door_spots": 0, "width": 2, "x": 40, "y": 50, "sealed": True, "equipment": door})
    s["settings"]["traits"] = {"fortification": 100, "engineering": 100}
    p = by_rule(plan(s, m)[0], "traps")[0]
    record([(p, {"ok": False, "error": "no free floor just inside that gate for traps"})], s, m)
    m.last_fired.pop("traps", None)
    assert not by_rule(plan(s, m)[0], "traps")


@test("5b drawbridge: the AI's own lever (bridge 0.35 lists it) is linked before the player's")
def _():
    s = entrances({"door_spots": 0, "width": 2, "x": 35, "y": 120, "bridges_unworked": [900]})
    s["entrances"]["free_levers"] = [{"id": 555, "x": 30, "y": 120, "z": 180}]
    s["military"]["gates"] = [{"id": 67938, "linked": 0, "pending": False, "x": 36, "y": 124, "z": 179}]
    p = by_rule(plan(s, Memory())[0], "gate_lever")
    assert p and p[0].action == {"type": "link_lever", "lever_id": 555, "target_id": 900}, p


@test("founding: a fort with no staircase digs its first; refused, further out; refused there too, Needs you says why")
def _():
    s = fort()
    s["founding"] = {"stairs": False, "near": "the wagon"}
    m = Memory()
    p = by_rule(plan(s, m)[0], "found")
    assert p and p[0].action == {"type": "found_fort"} and "beside the wagon" in p[0].reason, p
    record([(p[0], {"ok": False, "error": "no tile within 10 of the wagon with solid, dry ground under it "
                                         "(found: an aquifer below)"})], s, m)
    # (0.105.35) nothing waits for the player: looked for further out first
    p, notes = plan(s, m)
    p = by_rule(p, "found")
    assert p and p[0].action == {"type": "found_fort", "wide": True}, p
    assert not any(n.startswith("[you] ") and "can't start the fort" in n for n in notes), notes
    record([(p[0], {"ok": False, "error": "no tile within 20 of the wagon with solid, dry ground under it "
                                         "(found: an aquifer below)"})], s, m)
    _, notes = plan(s, m)
    assert any(n.startswith("[you] ") and "can't start the fort" in n and "aquifer" in n and "looks again" in n
               for n in notes), notes
    allowed, _ = select(plan(s, m)[0], s, m)
    assert not [x for x in allowed if x.rule == "found"]           # (its cooldown: 3 days for the miners)
    s["founding"] = {"stairs": True}
    assert not by_rule(plan(s, Memory())[0], "found")
    del s["founding"]                                               # an older bridge: nothing
    assert not by_rule(plan(s, Memory())[0], "found")


def lever_state(lever_linked=0, pending=False, away=False, levers=(51800,)):
    s = entrances({"door_spots": 0, "width": 3, "x": 35, "y": 120, "sealed": True,
                   "equipment": [{"id": 51799, "kind": "bridge", "lever_id": levers[0] if levers else None,
                                  "levers": list(levers), "lever_away": away}]})
    s["military"]["gates"] = [{"id": 67938, "state": 0, "linked": lever_linked, "pending": pending,
                               "x": 36, "y": 124, "z": 179}]
    return s


@test("gates 5a: a drawbridge worked only from the gate gets the unlinked AI gate lever linked to it")
def _():
    m = Memory()
    p = by_rule(plan(lever_state(), m)[0], "gate_lever")
    assert p and p[0].action == {"type": "link_lever", "lever_id": 67938, "target_id": 51799}, p
    assert "x35 y120" in p[0].reason
    for s in (lever_state(away=True), lever_state(lever_linked=1), lever_state(pending=True),
              lever_state(levers=(51800, 67938))):
        assert not by_rule(plan(s, Memory())[0], "gate_lever")
    # a bridge no lever inside works: linked too, and not walled over meanwhile
    s = entrances({"door_spots": 0, "width": 3, "x": 35, "y": 120, "bridges_unworked": [51799]})
    s["military"]["gates"] = [{"id": 67938, "linked": 0, "pending": False, "x": 36, "y": 124, "z": 179}]
    props = plan(s, Memory())[0]
    assert by_rule(props, "gate_lever") and not by_rule(props, "fortify"), [p.rule for p in props]
    # the AI gate lever itself right by that gate: no link (it would fix nothing); walled as before
    s["military"]["gates"][0]["z"] = 173
    s["military"]["gates"][0].update(x=36, y=121)
    props = plan(s, Memory())[0]
    assert not by_rule(props, "gate_lever") and by_rule(props, "fortify"), [p.rule for p in props]
    # an older bridge (no lever details): nothing proposed
    old = lever_state()
    del old["entrances"]["entrances"][0]["equipment"][0]["lever_away"]
    assert not by_rule(plan(old, Memory())[0], "gate_lever")
    # a Lua fault in the bridge (0.34.0 in the game): tried again the next day, not in 2 weeks
    s = lever_state()
    m2 = Memory()
    pf = by_rule(plan(s, m2)[0], "gate_lever")[0]
    record([(pf, {"ok": False, "error": "ai-gates.lua:1272: attempt to index a nil value\nstack traceback: ..."})], s, m2)
    m2.last_fired.pop("gate_lever", None)
    assert not by_rule(plan(s, m2)[0], "gate_lever")
    s["date"]["tick"] += 1201
    assert by_rule(plan(s, m2)[0], "gate_lever")
    # no free mechanisms: 2 are ordered, and the link is tried again 3 days later
    s = lever_state()
    record([(p[0], {"ok": False, "error": "a link needs 2 free mechanisms (0 free)"})], s, m)
    props = plan(s, m)[0]
    assert not by_rule(props, "gate_lever")
    o = by_rule(props, "mechanisms")
    assert o and o[0].action == {"type": "work_order", "recipe": "mechanisms", "amount": 2}, o
    s["date"]["tick"] += 3 * 1200 + 1
    m.last_fired.pop("gate_lever", None)
    assert by_rule(plan(s, m)[0], "gate_lever")
    # the AI gate lever, once linked to the watched bridge, isn't pulled on its own
    def pulls(levers):
        s = lever_state(lever_linked=1, levers=levers)
        s["others_on_map"]["threats"] = [{"id": 5, "name": "goblin", "can_reach_dwarves": True}]
        return [x for x in plan(s, Memory())[0] if x.action.get("type") == "pull_gate"]
    assert pulls((51800,)), "linked elsewhere: still pulled on its own"
    assert not pulls((51800, 67938))


@test("military: squads are filled toward the Militarism target; none -> a note")
def _():
    s = fort()
    s["settings"]["traits"] = {"militarism": 0}                       # 10% of 194 = 19
    s["military"]["squads"][1]["members"] = 4
    s["military"]["soldiers"] = 14
    f = by_rule(plan(s, Memory())[0], "squad_fill")
    assert f and f[0].action == {"type": "squad_fill", "squad_id": 12, "count": 5}, f
    s["settings"]["fill_squads"] = False
    assert not by_rule(plan(s, Memory())[0], "squad_fill")
    s = fort()
    s["military"] = {"squads": [], "soldiers": 0, "routines": [], "gates": []}
    assert by_rule(plan(s, Memory())[0], "squad_make")                 # the AI makes one now
    s["settings"]["appoint_nobles"] = False                           # (0.97) officials only: squads go on
    assert by_rule(plan(s, Memory())[0], "squad_make")
    s["settings"]["fill_squads"] = False
    props, notes = plan(s, Memory())
    assert not by_rule(props, "squad_make") and any("raising and filling squads is off" in n for n in notes), notes


@test("military: all off-duty squads go on training in one cycle; if you send one back off duty, it stays")
def _():
    s = fort()
    for q in s["military"]["squads"]:
        q["routine"] = "Off duty"
    m = Memory()
    p, _ = plan(s, m)
    allowed, _ = select(p, s, m)
    trained = [x for x in allowed if x.rule == "train"]
    assert len(trained) == 2, [x.rule for x in allowed]
    record([(x, {"ok": True}) for x in trained], s, m)
    assert sorted(m.squads_trained) == [11, 12] and m.last_train_tick is not None
    assert not by_rule(plan(s, m)[0], "train")            # still off duty = the player's choice now


@test("military: soldier share from the slider: 5%, 10%, 40%; Extreme doubles it: 90% at +200, none at -200")
def _():
    from planner import soldier_share
    def share(v, extreme=False):
        s = fort()
        s["settings"]["traits"] = {"militarism": v * 2 if extreme else v} if v else {}
        s["settings"]["extreme"] = ["militarism"] if extreme else []
        return round(soldier_share(s, PLANNER_CONFIG), 3)
    assert (share(-100), share(-50), share(0), share(50), share(100)) == (0.05, 0.075, 0.10, 0.25, 0.40)
    assert (share(10, True), share(50, True), share(75, True), share(100, True)) == (0.16, 0.40, 0.65, 0.90)
    assert (share(-50, True), share(-75, True), share(-100, True)) == (0.05, 0.025, 0.0)
    assert share(10, True) < share(100)                              # (0.94) Extreme is twice as strong, never a jump


@test("military: a squad off duty is put on training (not during a threat)")
def _():
    s = fort()
    s["military"]["squads"][0]["routine"] = "Off duty"
    t = by_rule(plan(s, Memory())[0], "train")
    assert t and t[0].action == {"type": "squad_routine", "squad_id": 11, "routine": "Staggered training"}, t
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    assert not by_rule(plan(s, Memory())[0], "train")


def geared(**kw):
    s = fort()
    g = {"soldiers": 20, "armed": 20, "armored": 20, "helmed": 20, "squads": 4, "squads_with_uniform": 4,
         "spare": {"weapons": 0, "body": 0, "helms": 0}, "bars": {"IRON": 200, "STEEL": 5}, "forges": 2}
    g.update(kw)
    s["military"]["gear"] = g
    return s


@test("gear: soldiers without weapons -> axes from the best metal with enough bars; spare gear counts")
def _():
    a = by_rule(plan(geared(armed=12), Memory())[0], "arms")
    assert a and a[0].action == {"type": "work_order", "recipe": "metal_battle_axe", "amount": 8,
                                 "material": "INORGANIC:IRON"}, a          # 5 steel bars aren't enough for 8
    assert not by_rule(plan(geared(armed=12, spare={"weapons": 8}), Memory())[0], "arms")
    s = geared(armed=12, bars={"STEEL": 100, "IRON": 100})
    assert by_rule(plan(s, Memory())[0], "arms")[0].action["material"] == "INORGANIC:STEEL"
    s["settings"]["gear_weapon"] = "spear"
    assert by_rule(plan(s, Memory())[0], "arms")[0].action["recipe"] == "metal_spear"


@test("gear bars (0.100): a pair of boots takes one bar, an axe one, a breastplate two")
def _():
    kit = dict(legged=20, gloved=20, shielded=20, booted=12, spare={"weapons": 0, "body": 0, "helms": 0})
    s = geared(**dict(kit, bars={"STEEL": 8, "IRON": 200}))
    s["military"]["squads"][0]["ai_uniform"] = "Melee, metal armor"
    a = by_rule(plan(s, Memory())[0], "arms")
    assert a and a[0].action == {"type": "work_order", "recipe": "metal_high_boots", "amount": 8,
                                 "material": "INORGANIC:STEEL"}, a        # 8 pairs, 8 steel bars
    a = by_rule(plan(geared(armed=12, bars={"STEEL": 8, "IRON": 200}), Memory())[0], "arms")
    assert a and a[0].action["material"] == "INORGANIC:STEEL", a          # 8 axes, 8 bars
    a = by_rule(plan(geared(armored=12, bars={"STEEL": 15, "IRON": 200}), Memory())[0], "arms")
    assert a and a[0].action["material"] == "INORGANIC:IRON", a           # 8 breastplates want 16


@test("gear: a squad in the metal uniform gets the rest of a kit (shields, greaves, boots, gauntlets in pairs)")
def _():
    kit = dict(legged=20, gloved=20, booted=20, shielded=20)
    s = geared(**dict(kit, shielded=14))
    assert not by_rule(plan(s, Memory())[0], "arms")              # leather uniform: none of it
    s["military"]["squads"][0]["ai_uniform"] = "Melee, metal armor"
    a = by_rule(plan(s, Memory())[0], "arms")
    assert a and a[0].action["recipe"] == "metal_shield" and a[0].action["amount"] == 6, a
    s = geared(**dict(kit, booted=10, spare={"weapons": 0, "body": 0, "helms": 0, "boots": 4}))
    s["military"]["squads"][0]["ai_uniform"] = "Melee, metal armor"
    a = by_rule(plan(s, Memory())[0], "arms")
    assert a and a[0].action["recipe"] == "metal_high_boots" and a[0].action["amount"] == 8, a   # 20-10-4//2
    s = geared()                                                   # an older bridge: no kit counts
    s["military"]["squads"][0]["ai_uniform"] = "Melee, metal armor"
    assert not by_rule(plan(s, Memory())[0], "arms")


@test("crossbows: with two squads one becomes a crossbow squad; then crossbows, then bolts; melee needs drop")
def _():
    s = geared(ranged_armed=0, spare_crossbows=0, bolts=0, armed=20)
    sq = s["military"]["squads"]
    s["military"]["uniform_templates"] = ["Melee, leather armor", "Melee, metal armor", "Crossbows, leather armor",
                                          "Crossbows, metal armor"]
    for q in sq:
        q["ai_uniform"] = "Melee, metal armor"
    u = [p for p in by_rule(plan(s, Memory())[0], "uniform") if p.action.get("ranged")]
    newest = max(q["id"] for q in sq)
    assert u and u[0].action == {"type": "set_uniform", "squad_id": newest, "kind": "metal", "ranged": True}, u
    for q in sq:
        if q["id"] == newest:
            q["ai_uniform"] = "Crossbows, metal armor"
    s["buildings"]["workshops"]["Bowyers"] = 1
    s["stocks"]["wood"] = 500
    s["orders"] = []
    p = by_rule(plan(s, Memory())[0], "arms")
    assert p and p[0].action == {"type": "work_order", "recipe": "wooden_crossbow", "amount": 5}, p
    assert not any(x.action["recipe"] == "metal_battle_axe" for x in p)   # 20 armed covers the melee squad
    s["military"]["gear"].update(ranged_armed=10)
    p = by_rule(plan(s, Memory())[0], "arms")
    assert p and p[0].action["recipe"] == "metal_bolts" and p[0].action["amount"] == 5, p     # iron 200: metal
    s["military"]["gear"]["bars"] = {"IRON": 5}
    p = by_rule(plan(s, Memory())[0], "arms")
    assert p and p[0].action["recipe"] == "wooden_bolts", p
    # no further uniform switch takes the crossbows away
    assert not [x for x in by_rule(plan(s, Memory())[0], "uniform") if x.action.get("squad_id") == newest
                and not x.action.get("ranged")]


@test("quivers (0.100): leather quivers until a crossbow squad has one each (spare + worn), with leather and a leatherworks")
def _():
    s = geared(ranged_armed=10, spare_crossbows=0, bolts=100000, armed=20)
    sq = s["military"]["squads"]
    s["military"]["uniform_templates"] = ["Melee, metal armor", "Crossbows, metal armor"]
    newest = max(q["id"] for q in sq)
    for q in sq:
        q["ai_uniform"] = "Crossbows, metal armor" if q["id"] == newest else "Melee, metal armor"
    members = next(q["members"] for q in sq if q["id"] == newest)
    s["buildings"]["workshops"].update(Bowyers=1, Leatherworks=1)
    s["stocks"].update(wood=500, leather=50)
    s["orders"] = []
    def quivers(state):
        return [p for p in by_rule(plan(copy.deepcopy(state), Memory())[0], "arms") if p.action["recipe"] == "leather_quiver"]
    assert not quivers(s)                                            # an older bridge: no quiver count
    s["supplies"].update(quivers=1, quivers_worn=1)
    q = quivers(s)
    assert q and q[0].action == {"type": "work_order", "recipe": "leather_quiver",
                                 "amount": min(members - 2, PLANNER_CONFIG["max_quiver_order"])}, q
    s["supplies"].update(quivers=members)                            # one each already
    assert not quivers(s)
    s["supplies"].update(quivers=0, quivers_worn=0)
    s["stocks"]["leather"] = 0                                       # no leather
    assert not quivers(s)
    s["stocks"]["leather"] = 50
    s["orders"] = [{"recipe": "leather_quiver", "amount_left": members, "amount_total": members}]
    assert not quivers(s)                                            # queued already


@test("crossbows (Oct 23 live): the AI's own squads are adopted; never the first squad; one crossbow squad")
def _():
    s = geared(ranged_armed=0, spare_crossbows=0, bolts=0, armed=20)
    s["military"]["uniform_templates"] = ["Melee, leather armor", "Melee, metal armor", "Crossbows, leather armor",
                                          "Crossbows, metal armor"]
    sq = s["military"]["squads"]
    first = min(q["id"] for q in sq)
    base = dict(sq[0])
    for q in sq:
        q["ai_uniform"] = "Crossbows, metal armor" if q["id"] == first else None
        q["uniform"] = True
    new_a, new_b = dict(base, id=55, ai_uniform=None, uniform=True), dict(base, id=56, ai_uniform=None, uniform=True)
    sq += [new_a, new_b]
    m = Memory()
    m.squads_made = [55, 56]
    a = by_rule(plan(s, m)[0], "uniform_adopt")
    assert a and a[0].action == {"type": "adopt_uniform", "squad_id": 55}, a
    # adopted: 55 melee (it copied the axe uniform), 56 crossbows (it copied the crossbow one)
    new_a["ai_uniform"], new_b["ai_uniform"] = "Melee, metal armor |weapon:ITEM_WEAPON_AXE_BATTLE", "Crossbows, metal armor"
    for q in sq:
        if q["id"] not in (55, 56, first):
            q["ai_uniform"] = "Melee, metal armor"
    assert not by_rule(plan(s, m)[0], "uniform_adopt")
    u = by_rule(plan(s, m)[0], "uniform")
    assert u and u[0].action == {"type": "set_uniform", "squad_id": first, "kind": "metal"}, u   # back to melee
    # only the first squad shoots: the newest the AI made becomes the crossbow squad first
    new_b["ai_uniform"] = "Melee, metal armor"
    u = [x for x in by_rule(plan(s, m)[0], "uniform") if x.action.get("ranged")]
    assert u and u[0].action["squad_id"] == 56, u
    # nobody shoots and the AI made none: never the first squad
    for q in sq:
        q["ai_uniform"] = "Melee, metal armor"
    u = [x for x in by_rule(plan(s, Memory())[0], "uniform") if x.action.get("ranged")]
    assert u and u[0].action["squad_id"] != first, u


@test("archery: a crossbow squad and no range -> dig one; a range -> the crossbow squad trains there")
def _():
    s = fort()
    q = s["military"]["squads"][-1]
    q["ai_uniform"] = "Crossbows, leather armor"
    q["members"] = 6
    s["projects"]["open"] = []
    s["buildings"]["zones"].pop("ArcheryRange", None)
    found = None
    for _ in range(40):            # other levels come first in a test fort; drop them as they're asked
        props = plan(s, Memory())[0]
        b = [p for p in props if p.action.get("type") == "start_project"]
        if not b:
            break
        if b[0].action["kind"] == "archery":
            found = b[0]
            break
        s["projects"]["open"].append({"kind": b[0].action["kind"], "id": len(s["projects"]["open"]) + 1})
    assert found and {k: found.action[k] for k in ("kind", "lanes", "length")} == \
        {"kind": "archery", "lanes": 2, "length": 12}, found
    s["military"]["ranges"] = [{"id": 950, "squads": []}]
    a = [p for p in by_rule(plan(s, Memory())[0], "barracks_assign") if p.action["zone_id"] == 950]
    assert a and a[0].action["squad_id"] == q["id"], a
    s["military"]["ranges"][0]["squads"] = [q["id"]]
    assert not [p for p in by_rule(plan(s, Memory())[0], "barracks_assign") if p.action["zone_id"] == 950]


@test("constant training (0.104.59): many badly wanting to train, idle hands: the AI's staggered squads train constantly")
def _():
    from planner import update_idle
    s = fort()
    s["military"]["routines"] = ["Off duty", "Staggered training", "Constant training", "Ready"]
    for q in s["military"]["squads"]:
        q["routine"], q["members"], q["ai_orders"] = "Staggered training", 10, False
    s["dwarves"].update(adults=90, idle_adults=40, total=96)        # many idle: no rotation
    m = Memory()
    update_idle(s, m, PLANNER_CONFIG)
    ids = [q["id"] for q in s["military"]["squads"]]
    m.squads_trained = list(ids[:-1])                               # the last squad is yours
    def moves(state):
        return {p.action["squad_id"]: p.action["routine"] for p in by_rule(plan(state, m)[0], "train")}
    assert not moves(s), moves(s)                                   # nobody keen: staggered is fine
    s.setdefault("needs", {}).setdefault("needs", {})["MartialTraining"] = {"badly": 31, "distracted": 54}
    got = moves(s)
    assert got == {sid: "Constant training" for sid in ids[:-1]}, got  # never your squad
    s["military"]["squads"][-1]["ai_uniform"] = "Melee, metal armor"  # ...unless it wears the AI's uniform
    assert moves(s) == {sid: "Constant training" for sid in ids}, moves(s)
    # (0.104.72) training met, no keen civilians, soldiers starved of the rest: back to staggered
    for q in s["military"]["squads"]:
        q["routine"] = "Constant training"
    s["needs"]["needs"]["MartialTraining"] = {"badly": 1, "distracted": 5}
    s["needs"]["keen_civilians"] = 1
    s["needs"]["starved_soldiers"] = [{"id": i, "unmet": ["CraftObject", "BeWithFriends"]} for i in range(4)]
    assert moves(s) == {sid: "Staggered training" for sid in ids}, moves(s)
    s["needs"]["keen_civilians"] = 9                                  # civilians keen: the swap first, no change
    assert not moves(s), moves(s)


@test("training rotation: the AI's squads take turns, half at a time, a month each; yours and a militant fort's aren't")
def _():
    s = fort()
    sq = s["military"]["squads"]
    s["military"]["routines"] = ["Off duty", "Staggered training", "Constant training", "Ready"]
    for q in sq:
        q["routine"], q["members"], q["ai_orders"] = "Staggered training", 5, False
    m = Memory()
    m.squads_trained = [q["id"] for q in sq]
    ids = sorted(q["id"] for q in sq)
    def moves(state):
        return {p.action["squad_id"]: p.action["routine"] for p in by_rule(plan(state, m)[0], "train")}
    s["settings"]["militarism"] = 0
    moved = moves(s)
    # (0.100) half go off duty; the squads on their turn move from staggered to constant training
    first = {sid: r for sid, r in moved.items() if r == "Off duty"}
    assert first and len(first) == len(ids) // 2, moved
    assert all(r == "Constant training" for sid, r in moved.items() if sid not in first), moved
    # (0.104.53) many badly wanting to train: every squad trains, none goes off duty
    keen = copy.deepcopy(s)
    keen.setdefault("needs", {}).setdefault("needs", {})["MartialTraining"] = {"badly": 40, "distracted": 60}
    assert not [r for r in moves(keen).values() if r == "Off duty"], moves(keen)
    later = copy.deepcopy(s)                                   # a month on: the others' turn
    for q in later["military"]["squads"]:
        q["routine"] = "Off duty" if q["id"] in first else "Constant training"
    m.squads_rested = list(first)
    later["date"]["tick"] += 28 * 1200
    second = moves(later)
    assert set(second) == set(ids) and all((r == "Constant training") == (sid in first) for sid, r in second.items()), second
    # (0.100) no constant training routine: the rotation uses staggered training as before
    old_r = copy.deepcopy(later)
    old_r["military"]["routines"] = ["Off duty", "Staggered training", "Ready"]
    for q in old_r["military"]["squads"]:
        q["routine"] = "Off duty" if q["id"] in first else "Staggered training"
    third = moves(old_r)
    assert set(third) == set(ids) and all((r == "Staggered training") == (sid in first) for sid, r in third.items()), third
    # a squad you put off duty yourself (trained before, not rested by the AI) stays out of it
    m2 = Memory(); m2.squads_trained = list(ids)
    t = copy.deepcopy(s)
    t["military"]["squads"][0]["routine"] = "Off duty"
    got = {p.action["squad_id"] for p in by_rule(plan(t, m2)[0], "train")}
    assert ids[0] not in got or len(ids) > 2, got


@test("training rotation (0.104.149): all squads training keep on in the dead band; they don't flip each cycle")
def _():
    s = fort()
    sq = s["military"]["squads"]
    s["military"]["routines"] = ["Off duty", "Staggered training", "Constant training", "Ready"]
    for q in sq:
        q["routine"], q["members"], q["ai_orders"] = "Constant training", 5, False
    s["settings"]["militarism"] = 0
    m = Memory()
    m.squads_trained = [q["id"] for q in sq]
    cit = s["dwarves"]["total"] = 160
    mt = s.setdefault("needs", {}).setdefault("needs", {})
    def moves(state):
        return {p.action["squad_id"]: p.action["routine"] for p in by_rule(plan(state, m)[0], "train")}
    # all train, the need under the 15% (24) but over 7% (11): nobody sent off duty
    mt["MartialTraining"] = {"badly": 18, "distracted": 60}
    assert not [r for r in moves(copy.deepcopy(s)).values() if r == "Off duty"], moves(s)
    # under 7%: half go back to work
    mt["MartialTraining"] = {"badly": 8, "distracted": 30}
    assert [r for r in moves(copy.deepcopy(s)).values() if r == "Off duty"], moves(s)
    # half resting and 18 keen: not enough to call them all back (under 15%)
    first = sorted(q["id"] for q in sq)[: len(sq) // 2]
    for q in sq:
        q["routine"] = "Off duty" if q["id"] in first else "Constant training"
    m.squads_rested = list(first)
    mt["MartialTraining"] = {"badly": 18, "distracted": 60}
    got = moves(copy.deepcopy(s))
    assert not all(got.get(sid) == "Constant training" for sid in first), got     # not every resting one called back
    mt["MartialTraining"] = {"badly": 30, "distracted": 80}
    assert all(r == "Constant training" for r in moves(copy.deepcopy(s)).values()), moves(s)


@test("the deep: an open cavern is said; a great danger in it, vampires and werebeasts: said with what the AI does (0.105.35)")
def _():
    s = fort()
    s["deep"] = {"caverns": [{"name": "Cavern1", "discovered": True, "open": True, "z_top": 40, "z_bottom": 30},
                             {"name": "Cavern2", "discovered": False, "open": False}],
                 "dangers": [], "cursed": []}
    notes = plan(s, Memory())[1]
    assert any("Cavern1 is open to the fort's ground" in n for n in notes), notes
    s["deep"]["dangers"] = [{"name": "Ubbul the Toad", "kind": "forgotten beast", "layer": "Cavern1"},
                            {"name": "a titan", "kind": "titan", "layer": "upper_levels", "can_reach_dwarves": True}]
    notes = plan(s, Memory())[1]
    assert any(n.startswith("Cavern1 is open to the fort and Ubbul the Toad") and "locks" in n for n in notes), notes
    assert not any(n.startswith("[you] ") for n in notes), notes
    assert any("a titan (titan) is in upper levels and can reach the dwarves" in n for n in notes), notes
    m = Memory()
    note_cycle(s, m)
    assert m.rescan_entrances and m.caverns_open == ["Cavern1"]           # newly open: entrances mapped now
    m.rescan_entrances = False
    note_cycle(s, m)
    assert not m.rescan_entrances                                         # (once)
    s["deep"]["cursed"] = [{"id": 77, "name": "Urist", "kind": "vampire"}, {"name": "Bomrek", "kind": "werebeast"}]
    props, notes = plan(s, Memory())
    assert any(p.action == {"type": "expel_dwarf", "unit_id": 77} for p in props)        # sent away (Rules tab)
    assert any(n.startswith("Urist is a vampire: the AI sends them away") for n in notes)
    assert any(n.startswith("Bomrek carries a werebeast curse") and "cell" in n for n in notes), notes
    s["settings"]["expel_vampires"] = False                                # the player's switch: kept, said
    notes = plan(s, Memory())[1]
    assert any(n.startswith("Urist is a vampire") and "Rules tab" in n for n in notes), notes
    assert not any(n.startswith("[you] ") for n in notes), notes


@test("feeders: a workshop without a pile beside it gets one, busiest kind first; none in a young fort")
def _():
    s = fort()
    s["logistics"] = {"feeders": [{"id": 5, "kind": "Kitchen", "what": "food", "has": False, "x": 1, "y": 1},
                                  {"id": 6, "kind": "Masons", "what": "stone", "has": False, "x": 2, "y": 2},
                                  {"id": 7, "kind": "Carpenters", "what": "wood", "has": True}]}
    f = by_rule(plan(s, Memory())[0], "feeder")
    assert f and f[0].action == {"type": "feeder_pile", "building_id": 6}, f
    s["logistics"]["feeders"][1]["has"] = True
    assert by_rule(plan(s, Memory())[0], "feeder")[0].action["building_id"] == 5
    s["logistics"]["feeders"][1]["has"] = False
    s["logistics"]["feeders"][1]["room"] = False                       # (0.104.138) no room by the Masons
    assert by_rule(plan(s, Memory())[0], "feeder")[0].action["building_id"] == 5


@test("storage: full piles with things lying loose -> a storage level for those kinds; stone by Industriousness")
def _():
    from planner import full_stores
    s = fort()
    s["logistics"] = {"storage": {"wood": {"tiles": 50, "used": 49, "loose": 40, "piles": 1},
                                  "food": {"tiles": 100, "used": 60, "loose": 300, "piles": 2},       # room left
                                  "furniture": {"tiles": 0, "used": 0, "loose": 25, "piles": 0},     # none at all
                                  "stone": {"tiles": 10, "used": 10, "loose": 900, "piles": 1},
                                  "bars_blocks": {"tiles": 20, "used": 20, "loose": 5, "piles": 1}}}  # few loose
    assert full_stores(s, PLANNER_CONFIG) == ["furniture", "wood", "stone"], full_stores(s, PLANNER_CONFIG)
    # (0.93) stone: past 200 loose at Industriousness 0, 100 at +100; never at -100; not past the tile cap
    s["logistics"]["storage"]["stone"]["loose"] = 150
    assert "stone" not in full_stores(s, PLANNER_CONFIG)
    s["settings"]["traits"] = {"industriousness": 100}
    assert "stone" in full_stores(s, PLANNER_CONFIG)
    s["settings"]["traits"] = {"industriousness": -100}
    s["logistics"]["storage"]["stone"]["loose"] = 900
    assert "stone" not in full_stores(s, PLANNER_CONFIG)
    s["settings"]["traits"] = {}
    s["logistics"]["storage"]["stone"].update(tiles=700, used=700)
    assert "stone" not in full_stores(s, PLANNER_CONFIG)
    s["logistics"]["storage"]["stone"].update(tiles=10, used=10)
    assert full_stores(s, PLANNER_CONFIG)[-1] == "stone"
    s["projects"]["open"] = []
    found = None
    for _ in range(40):
        b = [p for p in plan(s, Memory())[0] if p.action.get("type") == "start_project"]
        if not b:
            break
        if b[0].action["kind"] == "storage":
            found = b[0]
            break
        s["projects"]["open"].append({"kind": b[0].action["kind"], "id": len(s["projects"]["open"]) + 1})
    assert found and found.action["piles"] == ["furniture", "wood", "stone"], found


@test("water zone (0.104.2): no well and the injured or parched wait: a water source, fresh water near the fort first")
def _():
    s = fort()
    s["buildings"]["other"].pop("Well", None)
    s["buildings"]["zones"].pop("WaterSource", None)
    s["dwarves"]["needs_medical_care"] = 2
    s["water"] = {"bodies": [
        {"kind": "cavern", "nearest": {"d": 3, "x": 1, "y": 1, "z": 5}, "stagnant_share": 0},
        {"kind": "pool", "nearest": {"d": 16, "x": 2, "y": 2, "z": 5}, "stagnant_share": 100},
        {"kind": "surface", "nearest": {"d": 20, "x": 3, "y": 3, "z": 6}, "stagnant_share": 0}]}
    s["others_on_map"]["threats"] = []                 # (0.105.7 review) cavern water only with no cavern danger
    w = by_rule(plan(s, Memory())[0], "water_zone")
    # (0.105.7 review) the nearest first (fresh before stagnant), not surface first
    assert w and [p["x"] for p in w[0].action["points"]] == [1, 3, 2] and w[0].priority == 1, w
    s["buildings"]["zones"]["WaterSource"] = 1
    assert not by_rule(plan(s, Memory())[0], "water_zone")
    s["buildings"]["zones"].pop("WaterSource")
    s["buildings"]["other"]["Well"] = 1
    assert not by_rule(plan(s, Memory())[0], "water_zone")
    s["buildings"]["other"].pop("Well")
    s["dwarves"]["needs_medical_care"] = 0
    s.setdefault("society", {})["parched"] = 0
    assert not by_rule(plan(s, Memory())[0], "water_zone")


@test("slow game: many items -> a dump outside, then old remains rot (no tidy); big herds -> autobutcher")
def _():
    s = fort()
    s["fps_low"] = 14
    s["logistics"] = {"counts": {"items": 45000, "units": 300, "jobs": 200}}
    s["buildings"]["zones"].pop("Dump", None)
    props, notes = plan(s, Memory())
    assert by_rule(props, "dump") and by_rule(props, "dump")[0].action == {"type": "place_surface", "kind": "dump"}
    assert any("45000 items, 300 creatures" in n for n in notes), notes
    s["buildings"]["zones"]["Dump"] = 1
    props = plan(s, Memory())[0]
    assert not by_rule(props, "tidy") and not by_rule(props, "dump")     # (0.104.149) no cleanowned
    assert by_rule(props, "prune") and by_rule(props, "prune")[0].action == {"type": "prune_remains"}
    s["logistics"]["counts"]["items"] = 5000
    assert not by_rule(plan(s, Memory())[0], "tidy")
    assert not by_rule(plan(s, Memory())[0], "prune")
    s["tools"]["autobutcher"] = False
    s["others_on_map"]["tame_animals"] = 500
    t = [p for p in by_rule(plan(s, Memory())[0], "tools") if p.action["name"] == "autobutcher"]
    assert t, "autobutcher"


@test("needs: unmet needs named with what helps; miserable dwarves noted with what the AI does (0.105.35); prayer builds a shrine early")
def _():
    s = fort()
    s["needs"] = {"needs": {"PrayOrMeditate": {"have": 10, "distracted": 4}, "DrinkAlcohol": {"have": 18, "distracted": 3},
                            "Socialize": {"have": 18, "distracted": 0}},
                  "deities": {"Ilbat the Gold": 3, "Aban": 1},
                  "stressed": [{"name": "Urist", "stress": "miserable", "unmet": ["DrinkAlcohol", "Socialize"]}]}
    s["needs"]["petitions"] = {"temples": ["Ilbat the Gold"], "guildhalls": ["miner"]}
    s["settings"]["answer_locations"] = False                         # (0.89) else the AI builds them itself
    notes = plan(s, Memory())[1]
    assert any("PrayOrMeditate 4 (a temple)" in n and "DrinkAlcohol 3 (more drink" in n for n in notes), notes
    assert any(n.startswith("the fort agreed to petitions") and "a temple to Ilbat the Gold" in n
               and "a miner guildhall" in n and "switch" in n for n in notes), notes
    assert any("Ilbat the Gold 3" in n for n in notes)
    assert any(n.startswith("1 dwarf(s) are miserable") and "Urist (missing DrinkAlcohol, Socialize)" in n
               and "recreation" in n for n in notes), notes
    s["locations"]["count"].pop("TEMPLE", None)
    s["projects"]["open"] = []
    found = None
    for _ in range(40):
        b = [p for p in plan(s, Memory())[0] if p.action.get("type") == "start_project"]
        if not b:
            break
        if b[0].action["kind"] == "temple":
            found = b[0]
            break
        s["projects"]["open"].append({"kind": b[0].action["kind"], "id": len(s["projects"]["open"]) + 1})
    assert found and "distracted for want of somewhere to pray" in found.reason or (found and found.action["size"]), found


@test("needs met without a room: idle crafting, more drink, fine meals, once enough dwarves miss them")
def _():
    s = fort()
    s["orders"] = []
    s["needs"] = {"needs": {"CraftObject": {"distracted": 2}, "DrinkAlcohol": {"distracted": 4},
                            "EatGoodMeal": {"distracted": 3}},
                  "idle_crafting": {"enabled": False, "workshops": 0}}
    s["stocks"]["prepared_meals"] = 300
    props = plan(s, Memory())[0]
    assert by_rule(props, "needs_craft")[0].action == {"type": "idle_crafting"}
    plenty = s["stocks"].get("drink", 0) >= PLANNER_CONFIG["drink_per_dwarf"] * s["dwarves"]["total"]
    assert not by_rule(props, "needs_drink"), "(0.105.26) no needs_drink rule: the drink rule brews"
    assert by_rule(props, "needs_meal")[0].action == {"type": "work_order", "recipe": "prepare_fine_meal", "amount": 5}
    s["needs"]["idle_crafting"] = {"enabled": True, "workshops": 1}
    s["needs"]["needs"]["DrinkAlcohol"]["distracted"] = 1
    props = plan(s, Memory())[0]
    assert not by_rule(props, "needs_craft")
    s["stocks"]["prepared_meals"] = 194 * 20                  # plenty in store: cooking more won't help
    assert not by_rule(plan(s, Memory())[0], "needs_meal")


@test("good meals (0.83): lavish meals while few are worth over 20, however many plain ones; a hard ceiling")
def _():
    s = fort()
    s["orders"] = []
    s["needs"] = {"needs": {"EatGoodMeal": {"distracted": 57}}}
    pop = s["dwarves"]["total"]
    s["stocks"]["prepared_meals"] = pop * 40                     # 40 a dwarf, past the old stop at 15
    s["supplies"].update(meal_servings=pop * 40, good_meals=pop)  # one good one a dwarf
    m = by_rule(plan(s, Memory())[0], "needs_meal")
    assert m and m[0].action == {"type": "work_order", "recipe": "prepare_lavish_meal", "amount": 20}, m
    assert "worth over 20" in m[0].reason
    s["needs"] = {"needs": {"EatGoodMeal": {"distracted": 12}}}     # (0.103.8) one a dwarf wanting one
    assert by_rule(plan(s, Memory())[0], "needs_meal")[0].action["amount"] == 12
    s["needs"] = {"needs": {"EatGoodMeal": {"distracted": 57}}}
    s["supplies"]["good_meals"] = pop * 3                        # enough good ones
    assert not by_rule(plan(s, Memory())[0], "needs_meal")
    s["supplies"]["good_meals"] = 0
    s["stocks"]["prepared_meals"] = pop * 61                     # the ceiling
    assert not by_rule(plan(s, Memory())[0], "needs_meal")


@test("hospital thread (0.83): plants processed for thread when the hospital has under 10, cloth or not")
def _():
    s = fort()
    s["orders"] = []
    s["locations"] = {"count": {"HOSPITAL": 1}, "total": 1}
    s["buildings"]["workshops"]["Farmers"] = 1
    s["stocks"].update(thread=5, cloth=100, plants=40)
    h = [p for p in plan(s, Memory())[0] if p.action.get("recipe") == "process_plants"]
    assert h and h[0].rule == "hospital" and "the fort has 5" in h[0].reason, h
    s["stocks"]["thread"] = 12
    assert not [p for p in plan(s, Memory())[0] if p.rule == "hospital" and p.action.get("recipe") == "process_plants"]
    # (0.104.11) no plant here gives thread: no order (it only stood still); Needs you while patients wait
    s["stocks"]["thread"] = 0
    s["supplies"]["thread_plants"] = 0
    s["health"] = {"patients": [{"needs": ["suture"]}, {"needs": ["diagnosis"]}]}
    props, notes = plan(s, Memory())
    assert not [p for p in props if p.action.get("recipe") == "process_plants"], props
    assert any("1 patient(s) wait for sutures or dressings" in n for n in notes), notes
    s["supplies"]["thread_plants"] = 30
    assert [p for p in plan(s, Memory())[0] if p.action.get("recipe") == "process_plants"]


@test("staffing (0.84): the hospital's posts first (urgent with patients), then a library's scribes, capped")
def _():
    s = fort()
    s["dwarves"]["needs_medical_care"] = 4
    s["locations"] = {"count": {"HOSPITAL": 1, "LIBRARY": 1}, "total": 2, "list": [
        {"id": 8, "type": "LIBRARY", "books": 3, "jobs": {"SCRIBE": {"posts": 4, "filled": 0}}},
        {"id": 3, "type": "HOSPITAL", "jobs": {"DIAGNOSTICIAN": {"posts": 1, "filled": 1}, "DOCTOR": {"posts": 2, "filled": 0},
                                               "SURGEON": {"posts": 1, "filled": 1}, "BONE_DOCTOR": {"posts": 1, "filled": 1}}}]}
    p = by_rule(plan(s, Memory())[0], "staff")
    assert p and p[0].action == {"type": "staff_location", "location_id": 3, "post": "DOCTOR"} and p[0].priority == 2, p
    assert "4 need care" in p[0].reason
    s["locations"]["list"][1]["jobs"]["DOCTOR"]["filled"] = 2
    p = by_rule(plan(s, Memory())[0], "staff")
    assert p and p[0].action["post"] == "SCRIBE" and p[0].priority == 5, p
    s["locations"]["list"][0]["jobs"]["SCRIBE"]["filled"] = 2                 # two scribes are enough
    assert not by_rule(plan(s, Memory())[0], "staff")
    # (0.85) posts the game hasn't made: made first, as its screen does; a library's only with paper or books
    s["locations"]["list"][1]["jobs"] = {"DIAGNOSTICIAN": {"posts": 1, "filled": 1}}
    p = by_rule(plan(s, Memory())[0], "staff")
    assert p and p[0].action == {"type": "add_posts", "location_id": 3, "posts": ["DOCTOR", "SURGEON", "BONE_DOCTOR"]}, p
    s["locations"]["list"] = [{"id": 8, "type": "LIBRARY", "books": 0, "have": {"paper": 0}}]
    assert not by_rule(plan(s, Memory())[0], "staff")


@test("locations (0.84, live region2 y62): the hospital by its own stock, its posts made; mugs for the tavern")
def _():
    s = fort()
    s["orders"] = []
    s["dwarves"]["needs_medical_care"] = 1
    s["buildings"]["workshops"].update(Farmers=1, Craftsdwarfs=1)
    s["stocks"].update(thread=5, cloth=100, plants=40)
    s["locations"] = {"count": {"HOSPITAL": 1, "INN_TAVERN": 1, "LIBRARY": 1}, "total": 3, "list": [
        {"id": 0, "type": "INN_TAVERN", "have": {"goblets": 0, "instruments": 4}, "want": {"goblets": 10, "instruments": 5}},
        {"id": 1, "type": "HOSPITAL", "have": {"thread": 75000, "cloth": 50000, "splints": 3, "crutches": 3,
                                               "soap": 750, "powder": 0},
         "want": {"thread": 75000, "cloth": 50000, "splints": 5, "crutches": 5, "soap": 750, "powder": 750}},
        {"id": 2, "type": "LIBRARY", "books": 0, "have": {"paper": 0}, "want": {"paper": 10}}]}
    props, notes = plan(s, Memory())
    assert not [p for p in props if p.action.get("recipe") == "process_plants" and p.rule == "hospital"]  # its thread is there
    assert any("keeps less than it should: splints 3 of 5, crutches 3 of 5, powder 0 of 5" in n for n in notes), notes
    assert not any("needs thread and cloth" in n for n in notes)
    st = by_rule(props, "staff")                                              # (0.85) the AI makes the posts
    assert st and st[0].action == {"type": "add_posts", "location_id": 1,
                                   "posts": ["DIAGNOSTICIAN", "DOCTOR", "SURGEON", "BONE_DOCTOR"]}, st
    t = by_rule(props, "tavern")
    assert t and t[0].action == {"type": "work_order", "recipe": "stone_mugs", "amount": 10}, t
    assert any("library has 0 books" in n for n in notes)
    ins = by_rule(props, "instruments")                                       # (0.104.8) ordered, not just said
    assert ins and ins[0].action == {"type": "order_instrument", "amount": 1} and "the tavern 4 of 5" in ins[0].reason, ins
    s["locations"]["list"][1]["have"]["thread"] = 15000                       # 1 of 5: short now
    assert [p for p in plan(s, Memory())[0] if p.action.get("recipe") == "process_plants" and p.rule == "hospital"]
    # (0.104.4) no stone: wooden cups; no chest in the tavern: one put in its zone
    s["stone_use"] = {"usable": 0, "economic": {}}
    s["stocks"]["wood"] = 200
    s["locations"]["list"][0].update(chests=0, zones=[136])
    props = plan(s, Memory())[0]
    t = by_rule(props, "tavern")
    assert t and t[0].action["recipe"] == "wooden_cups", t
    c = by_rule(props, "tavern_chest")
    assert c and c[0].action == {"type": "place_in_zone", "zone_id": 136, "what": "chest"}, c
    s["locations"]["list"][0]["chests"] = 1
    assert not by_rule(plan(s, Memory())[0], "tavern_chest")
    # (0.104.67) a temple short of instruments with no chest: a chest first, no instruments ordered for it
    s["locations"]["list"][0]["have"]["instruments"] = 5
    s["locations"]["list"].append({"id": 3, "type": "TEMPLE", "chests": 0, "zones": [325],
                                   "have": {"instruments": 0}, "want": {"instruments": 5}})
    props = plan(s, Memory())[0]
    c = by_rule(props, "temple_chest")
    assert c and c[0].action == {"type": "place_in_zone", "zone_id": 325, "what": "chest"}, c
    assert not by_rule(props, "instruments"), by_rule(props, "instruments")
    s["locations"]["list"][-1]["chests"] = 1
    props = plan(s, Memory())[0]
    assert not by_rule(props, "temple_chest") and by_rule(props, "instruments")
    # (0.104.69) an instrument order still open: no more ordered; 4+ not begun: trimmed to one
    o = {"job": "CustomReaction", "reaction": "MAKE_ENT103 INW1", "amount_left": 5, "amount_total": 5, "by_ai": False}
    s["orders"] = [dict(o, id=1, amount_left=2)]
    props = plan(s, Memory())[0]
    assert not by_rule(props, "instruments") and not by_rule(props, "instrument_orders")
    s["orders"] += [dict(o, id=i) for i in range(2, 6)]
    t = by_rule(plan(s, Memory())[0], "instrument_orders")
    assert t and t[0].action == {"type": "trim_instrument_orders", "keep": 1}, t


@test("glass (0.104.95): sand in the geology and idle hands -> furnace, sand zone, charcoal, sand, then glass crafts")
def _():
    s = fort()
    s["orders"] = []
    s["projects"]["open"] = []
    for k in ("GlassFurnace", "MagmaGlassFurnace", "WoodFurnace"):
        s["buildings"]["furnaces"].pop(k, None)
    s["supplies"].update(sand_layers=["yellow sand"], sand_zones=0, sand_bags=0, empty_bags=4, fuel=0)
    s["stocks"]["wood"] = 300
    s["trade"] = {"goods": 0}
    s["dwarves"].update(idle_adults=30, adults=60)
    g = by_rule(plan(s, Memory())[0], "glass")
    assert g and g[0].action == {"type": "start_project", "kind": "workshops", "shops": ["GlassFurnace", "WoodFurnace"]}, g
    s["buildings"]["furnaces"].update(GlassFurnace=1, WoodFurnace=1)
    g = by_rule(plan(s, Memory())[0], "glass")
    assert g and g[0].action == {"type": "sand_zone"}, g
    s["supplies"]["sand_zones"] = 1
    g = by_rule(plan(s, Memory())[0], "glass")
    assert g and g[0].action["recipe"] == "make_charcoal", g
    s["supplies"]["fuel"] = 6
    g = by_rule(plan(s, Memory())[0], "glass")
    assert g and g[0].action == {"type": "work_order", "recipe": "collect_sand", "amount": 3}, g
    s["supplies"]["sand_bags"] = 4
    g = by_rule(plan(s, Memory())[0], "glass")
    assert g and g[0].action == {"type": "work_order", "recipe": "glass_crafts", "amount": 4}, g
    s["orders"] = [{"id": 9, "recipe": "glass_crafts", "amount_left": 4, "by_ai": True}]
    assert not by_rule(plan(s, Memory())[0], "glass")                 # one at a time
    s["orders"] = []
    s["supplies"].update(sand_layers=[], sand_zones=0)
    assert not by_rule(plan(s, Memory())[0], "glass")                 # no sand: nothing
    from planner import recipe_shop
    assert recipe_shop("glass_crafts") == "GlassFurnace" and recipe_shop("collect_sand") == "GlassFurnace"


@test("crafts (0.104.95): a precious metal to spare is made into crafts before rock; never the gear metals")
def _():
    s = fort()
    s["orders"] = []
    s["trade"] = {"goods": 0, "depot": True}
    s["dwarves"].update(idle_adults=30, adults=60)
    s["supplies"]["fuel"] = 20
    s.setdefault("military", {}).setdefault("gear", {})
    s["military"]["gear"].update(forges=1, all_bars={"SILVER": 40, "IRON": 80, "GOLD": 5})
    p, notes = plan(s, Memory())
    c = by_rule(p, "crafts")
    assert c and c[0].action == {"type": "work_order", "recipe": "metal_crafts", "amount": 3,
                                 "material": "INORGANIC:SILVER"}, (c, rules(p))
    s["military"]["gear"]["all_bars"] = {"IRON": 80}
    c = by_rule(plan(s, Memory())[0], "crafts")
    assert c and c[0].action["recipe"] == "stone_crafts", c             # no precious metal: rock as before
    from planner import precious_metal, PLANNER_CONFIG
    s["military"]["gear"]["all_bars"] = {"SILVER": 40, "IRON": 80, "GOLD": 5}
    assert precious_metal(s, PLANNER_CONFIG) == "SILVER"
    s["military"]["gear"]["all_bars"] = {"IRON": 80, "GOLD": 12}
    assert precious_metal(s, PLANNER_CONFIG) is None                    # 12 gold: not 3 over the 10 kept
    s["military"]["gear"]["all_bars"] = {"GOLD": 30, "SILVER": 20}
    assert precious_metal(s, PLANNER_CONFIG) == "GOLD"


@test("kiln (0.86): bags of the cloth there is; a kiln for plaster; the paper chain one step at a time")
def _():
    s = fort()
    s["buildings"]["furnaces"].pop("MagmaKiln", None)               # (0.104.81) a magma kiln counts as a kiln
    s["orders"] = []
    s["projects"]["open"] = []
    s["supplies"].update(empty_bags=0, cloth_kinds={"plant": 0, "silk": 90, "yarn": 6}, gypsum=16, plaster=0,
                         calcium_carbonate=0, quicklime=0, milk_of_lime=0, sheets=0, blank_quires=0, hides=0,
                         fuel=50, buckets=100)
    s["locations"] = {"count": {"HOSPITAL": 1, "LIBRARY": 1}, "total": 2, "list": [
        {"id": 1, "type": "HOSPITAL", "have": {"powder": 0}, "want": {"powder": 750}},
        {"id": 2, "type": "LIBRARY", "books": 0, "have": {"paper": 0}, "want": {"paper": 10}}]}
    props, notes = plan(s, Memory())
    b = by_rule(props, "bags")
    assert b and b[0].action["recipe"] == "silk_bag" and "silk cloth (90)" in b[0].reason, b
    k = by_rule(props, "kiln")
    assert k and k[0].action == {"type": "start_project", "kind": "workshops", "shops": ["Kiln"]}, k   # no limestone: no tanner's
    s["buildings"]["furnaces"]["Kiln"] = 1
    props, notes = plan(s, Memory())
    assert not by_rule(props, "kiln") and any("waits for an empty bag" in n for n in notes), notes
    s["supplies"]["empty_bags"] = 3
    k = by_rule(plan(s, Memory())[0], "kiln")
    assert k and k[0].action["recipe"] == "make_plaster_powder", k
    s["supplies"]["plaster"] = 1                                   # plaster there: the paper chain
    s["supplies"]["calcium_carbonate"] = 20
    s["buildings"]["workshops"].update(Tanners=1, Ashery=1, Craftsdwarfs=1)
    seq = []
    for sup in ({}, {"quicklime": 2}, {"milk_of_lime": 2}, {"hides": 3}, {"sheets": 2}):
        s["supplies"].update(sup)
        k = by_rule(plan(s, Memory())[0], "kiln")
        seq.append(k[0].action["recipe"] if k else None)
    assert seq == ["make_quicklime", "make_milk_of_lime", None, "make_parchment", "make_quire"], seq
    s["supplies"]["blank_quires"] = 10                             # the library's 10 are there
    assert not by_rule(plan(s, Memory())[0], "kiln")


@test("0.105.10 the character slot: basics met, one slot left, no level of the fort's own open: it goes to one")
def _():
    from planner import character_slot_reserved, is_character_level
    s = fort()
    s["projects"]["open"] = [{"id": 3, "kind": "storage", "phase": "dig", "dig": {"total": 50, "dug": 10}}]
    s["settings"]["traits"] = {"piety": 150}
    props, notes = plan(s, Memory())
    starts = [p for p in props if p.action.get("type") == "start_project" and not p.action.get("urgent")]
    assert starts and all(is_character_level(p.action) for p in starts), [(p.rule, p.action) for p in starts]
    # a level of the fort's own already open: the other slot is free for anything
    s2 = fort()
    s2["projects"]["open"] = [{"id": 4, "kind": "temple", "phase": "dig", "dig": {"total": 50, "dug": 10}}]
    assert character_slot_reserved(s2, {}, PLANNER_CONFIG, Memory(), s2["projects"]["open"]) is None
    # both slots free: no hold yet (the first goes to need)
    assert character_slot_reserved(s, {}, PLANNER_CONFIG, Memory(), []) is None
    # the basics not met (beds short): no hold
    s3 = fort()
    s3["buildings"]["other"]["Bed"] = 3
    assert character_slot_reserved(s3, {}, PLANNER_CONFIG, Memory(), s["projects"]["open"]) is None
    assert character_slot_reserved(s, {}, PLANNER_CONFIG, Memory(), s["projects"]["open"])
    # (review) a slow game or a crisis: no hold (the need goes ahead)
    slow = dict(s, fps_low=5)
    assert character_slot_reserved(slow, {}, PLANNER_CONFIG, Memory(), s["projects"]["open"]) is None
    mc = Memory()
    mc.crisis = {"why": ["tantrums"]}
    assert character_slot_reserved(s, {}, PLANNER_CONFIG, mc, s["projects"]["open"]) is None
    # (review) an open growth level the AI started (the report doesn't say so): remembered by id
    mg = Memory()
    mg.character_projects = [3]
    assert character_slot_reserved(s, {}, PLANNER_CONFIG, mg, s["projects"]["open"]) is None
    # (review) every ladder level refused by the game: the need level goes ahead, nothing held
    from planner import record, select
    m = Memory()
    p0 = [p for p in plan(s, m)[0] if p.rule == "build"][0]
    record([(p0, {"ok": False, "error": "no room"})], s, m)
    props, notes = plan(s, m)
    assert not any("the fort's own" in n for n in notes), notes           # nothing held for a refused level


@test("a stuck forge (0.86, live: 104 days): an anvil made for it; it no longer holds back other workshops")
def _():
    s = fort()
    s["buildings"]["furnaces"].pop("MagmaKiln", None)               # (0.104.81) a magma kiln counts as a kiln
    s["orders"] = []
    stuck = {"id": 214, "kind": "workshops", "phase": "furnish", "furniture": {"MetalsmithsForge": 1},
             "furnish": {"days": 104, "done": 0, "placed": 1, "waiting": {"Workshop": 1}}}
    s["projects"]["open"] = [stuck]
    s["buildings"]["workshops"]["MetalsmithsForge"] = 1
    s["military"].setdefault("gear", {})["bars"] = {"IRON": 40}
    s["supplies"].update(anvils=0, gypsum=16, plaster=0, empty_bags=2, fuel=40, calcium_carbonate=0)
    s["locations"] = {"count": {"HOSPITAL": 1}, "total": 1, "list": [
        {"id": 1, "type": "HOSPITAL", "have": {"powder": 0}, "want": {"powder": 750}}]}
    drink = s["stocks"].get("drink")
    # (0.105.10) basics met, the last slot is the fort's own: the kiln level waits for it
    props, notes = plan(s, Memory())
    assert not by_rule(props, "kiln") and any("the fort's own" in n and "kiln" in n for n in notes), notes
    s["stocks"]["drink"] = 1                                            # basics not met: no slot held
    props = plan(s, Memory())[0]
    a = by_rule(props, "anvil")
    assert a and a[0].action == {"type": "work_order", "recipe": "metal_anvil", "amount": 1,
                                 "material": "INORGANIC:IRON"} and "104 days" in a[0].reason, a
    k = by_rule(props, "kiln")
    assert k and k[0].action["shops"] == ["Kiln"], k                    # not held back by the stuck forge
    s["supplies"]["anvils"] = 1                                         # an anvil there: none made
    assert not by_rule(plan(s, Memory())[0], "anvil")
    stuck["furnish"]["days"] = 5                                        # a fresh project still holds the next one
    assert not [p for p in by_rule(plan(s, Memory())[0], "kiln") if p.action.get("type") == "start_project"]


@test("petitions (0.87): DF's standing orders accept useful visitors, citizenship under the target; only changes")
def _():
    s = fort()
    s["dwarves"]["total"] = 80
    s["settings"]["traits"] = {"militarism": 10}
    s["petitions"] = {"orders": {k: 0 for k in ("performer", "scholar", "monster_hunter", "mercenary",
                                                "sanctuary", "citizenship")},
                      "pending": [{"type": "Citizenship", "name": "a poet"}, {"type": "Residency", "reason": "entertain"},
                                  {"type": "Residency", "vampire": True, "name": "Urist"}]}
    props, notes = plan(s, Memory())
    p = by_rule(props, "petitions")
    assert p and p[0].action["orders"] == {"performer": 1, "scholar": 1, "monster_hunter": 1, "sanctuary": 1,
                                           "citizenship": 1}, p          # no mercenaries at Militarism 10
    assert any("Citizenship 1, Residency 2" in n and "a vampire among them: Urist" in n for n in notes), notes
    s["petitions"]["orders"].update(performer=1, scholar=1, monster_hunter=1, sanctuary=1, citizenship=1)
    assert not by_rule(plan(s, Memory())[0], "petitions")
    s["dwarves"]["total"] = 200                                           # past the target: citizenship asked
    p = by_rule(plan(s, Memory())[0], "petitions")
    assert p and p[0].action["orders"] == {"citizenship": 0}, p
    s["petitions"]["orders"]["scholar"] = 2                               # a value the AI doesn't know
    props, notes = plan(s, Memory())
    assert not by_rule(props, "petitions") and any("values the AI doesn't know" in n for n in notes)
    s["petitions"]["orders"]["scholar"] = 1
    s["settings"]["accept_visitors"] = False                              # the switch off: never touched
    assert not by_rule(plan(s, Memory())[0], "petitions")
    s["settings"]["accept_visitors"] = True                               # (live) this DFHack can't reach them
    s["petitions"]["orders"] = []
    props, notes = plan(s, Memory())
    assert not by_rule(props, "petitions") and any("can't reach DF's petition standing orders" in n for n in notes)


@test("citizenship (0.105.24): petitions the fort would take are a Needs you with counts; else a note; the gone apart")
def _():
    from planner import NEEDS_YOU
    s = fort()
    s["dwarves"]["total"] = 40
    here = {"on_map": True, "unit": 5}
    s["petitions"] = {"orders": [], "pending": [
        {"type": "Citizenship", "name": "Lòr, Scholar", "applicant": dict(here)},
        {"type": "Citizenship", "name": "Bim, Bard", "applicant": dict(here)},
        {"type": "Citizenship", "name": "Urist", "applicant": dict(here), "vampire": True},
        {"type": "Citizenship", "name": "Gone", "applicant": {"on_map": False}},
        {"type": "Residency", "name": "Ast", "applicant": dict(here)}]}
    notes = plan(s, Memory())[1]
    ask = [n for n in notes if n.startswith(NEEDS_YOU) and "citizenship petition" in n]
    assert len(ask) == 1 and "2 citizenship petition(s) wait and the fort would take them (40 citizens" in ask[0], notes
    assert "Lòr, Scholar" in ask[0] and "1 more from visitors who left or died" in ask[0] and "1 of them a vampire" in ask[0]
    # past the population target, or a closed fort: a note, no Needs you
    s["dwarves"]["total"] = 400
    notes = plan(s, Memory())[1]
    assert not [n for n in notes if n.startswith(NEEDS_YOU) and "citizenship" in n], notes
    assert any("citizenship petition(s) wait" in n and "isn't taking citizens" in n for n in notes), notes
    s["dwarves"]["total"] = 40
    s["settings"]["traits"] = {"outsiders": -150}
    assert not [n for n in plan(s, Memory())[1] if n.startswith(NEEDS_YOU) and "citizenship" in n]
    # only the gone: a note
    s["settings"]["traits"] = {}
    s["petitions"]["pending"] = [{"type": "Citizenship", "applicant": {"on_map": True, "dead": True}}]
    notes = plan(s, Memory())[1]
    assert not [n for n in notes if n.startswith(NEEDS_YOU) and "citizenship" in n]
    assert any("1 citizenship petition(s) from visitors who left or died" in n for n in notes), notes


@test("bags (0.87.1, live): filled as fast as they're made: no more orders after 3 in 28 days with none empty")
def _():
    from planner import Proposal, refusal_key, abs_tick
    s = fort()
    s["orders"] = []
    s["supplies"].update(empty_bags=0, cloth_kinds={"plant": 5, "silk": 10, "yarn": 47})
    m = Memory()
    assert by_rule(plan(s, m)[0], "bags")
    p = Proposal("bags", {"type": "work_order", "recipe": "yarn_bag", "amount": 5}, "", 4, True)
    now = abs_tick(s)
    m.action_log[refusal_key(p)] = [now - 3 * 1200, now - 2 * 1200, now - 1200]
    props, notes = plan(s, m)
    assert not by_rule(props, "bags") and any("fill as fast as they're made" in n for n in notes), notes
    s["supplies"]["empty_bags"] = 1                                     # one stays empty: back to normal
    assert by_rule(plan(s, m)[0], "bags")


@test("bags (0.88): each kind of seed lying loose takes a new bag, so those are made on top; the sink waits longer")
def _():
    from planner import Proposal, refusal_key, abs_tick
    s = fort()
    s["orders"] = []
    s["supplies"].update(empty_bags=0, cloth_kinds={"plant": 5, "silk": 10, "yarn": 47},
                         bag_use={"empty": 0, "empty_in_job": 0, "held": {"SEEDS": 30},
                                  "seed_kinds_loose": 9, "seed_kinds_loose_unbagged": 8, "seeds_loose": 120})
    m = Memory()
    b = by_rule(plan(s, m)[0], "bags")
    assert b and "8 kind(s) of seed lie loose" in b[0].reason and b[0].action["amount"] == 10, b
    p = Proposal("bags", {"type": "work_order", "recipe": "yarn_bag", "amount": 5}, "", 4, True)
    now = abs_tick(s)
    m.action_log[refusal_key(p)] = [now - 3 * 1200, now - 2 * 1200, now - 1200]
    assert by_rule(plan(s, m)[0], "bags")                               # 3 + ceil(8/5) = 5 orders allowed
    m.action_log[refusal_key(p)] += [now - 600, now - 300]
    props, notes = plan(s, m)
    assert not by_rule(props, "bags") and any("the bags hold 30 seeds" in n for n in notes), notes


@test("traction bench (0.88): a free one goes into the hospital zone; else made, its missing part first")
def _():
    s = fort()
    s["orders"] = []
    s["buildings"].setdefault("workshops", {})["Mechanics"] = 1
    s["health"] = {"hospital": [{"id": 1, "staff": [], "zones": [{"id": 355, "type": "MeetingHall", "beds": 4,
                                                                   "traction": 0, "traction_planned": 0}]}]}
    s["supplies"].update(traction_benches=1, tables=2, ropes=1)
    p = by_rule(plan(s, Memory())[0], "traction")
    assert p and p[0].action == {"type": "place_in_zone", "zone_id": 355, "what": "traction_bench"}, p
    s["supplies"]["traction_benches"] = 0
    s["stocks"]["mechanisms"] = 0
    p = by_rule(plan(s, Memory())[0], "traction_parts")
    assert p and p[0].action["recipe"] == "mechanisms", p
    s["stocks"]["mechanisms"] = 3
    p = by_rule(plan(s, Memory())[0], "traction_parts")
    assert p and p[0].action["recipe"] == "traction_bench", p
    s["health"]["hospital"][0]["zones"][0]["traction_planned"] = 1          # planned: nothing more
    props = plan(s, Memory())[0]
    assert not by_rule(props, "traction") and not by_rule(props, "traction_parts")


@test("alert icons (0.88): old ones cleared, dangers kept a week; one alone first; the Rules choice")
def _():
    from planner import Proposal, refusal_key, abs_tick
    s = fort()
    s["alerts"] = {"total": 3, "by_type": {"GENERAL": {"n": 1, "age": 5000}, "DEATH": {"n": 1, "age": 5000},
                                           "WEATHER": {"n": 1, "age": 100}}}
    m = Memory()
    p = by_rule(plan(s, m)[0], "alerts")
    assert p and p[0].action["type"] == "dismiss_alerts" and p[0].action["max"] == 1, p
    ages = p[0].action["ages"]
    assert ages["default"] == 1200 and ages["DEATH"] == 7 * 1200, ages
    assert "general" in p[0].reason and "death" not in p[0].reason, p[0].reason
    now = abs_tick(s)
    m.action_log[refusal_key(p[0])] = [now - 2400]
    assert by_rule(plan(s, m)[0], "alerts")[0].action["max"] == 50
    s["alerts"]["by_type"]["GENERAL"]["age"] = 100                        # nothing old enough
    assert not by_rule(plan(s, m)[0], "alerts")
    s["alerts"]["by_type"]["DEATH"]["age"] = 9000                          # a week old: cleared
    assert by_rule(plan(s, m)[0], "alerts")
    s["settings"]["clear_alerts"] = "none"
    assert not by_rule(plan(s, m)[0], "alerts")
    s["settings"]["clear_alerts"] = "all"
    p = by_rule(plan(s, m)[0], "alerts")
    assert p and "DEATH" not in p[0].action["ages"], p
    s["alerts"]["open"] = True                                               # the alert window is open
    assert not by_rule(plan(s, m)[0], "alerts")


@test("long waits for care (0.88.3, live): only patients with a treatment waiting, not infected wounds alone")
def _():
    from planner import abs_tick
    s = fort()
    s["health"] = {"patients": [{"id": 1, "name": "Rovod", "infected": True, "needs": []},
                                {"id": 2, "name": "Zuntir", "needs": ["setting"]}]}
    m = Memory()
    now = abs_tick(s)
    m.patient_since = {"1": now - 600 * 1200, "2": now - 600 * 1200}
    notes = plan(s, m)[1]
    line = [n for n in notes if "waited a long time for care" in n]
    assert line and "1 dwarves" in line[0] and "Zuntir" in line[0] and "Rovod" not in line[0], notes


@test("location petitions (0.89): agree to one temple or guildhall, build it dedicated, not twice; the switch")
def _():
    s = fort()
    s["petitions"] = {"pending": [{"id": 174, "type": "Location", "loc": "TEMPLE", "tier": 1, "deity_hf": 55,
                                   "deity": "Rimtar", "days": 3}]}
    p = by_rule(plan(s, Memory())[0], "petition_answer")
    assert p and p[0].action == {"type": "answer_petition", "id": 174, "accept": True,
                                 "wish": "TEMPLE|None|None|55"}, p
    assert "a temple to Rimtar" in p[0].reason, p[0].reason
    # (0.102.2) the same wish again within a year, the temple standing: left to lapse
    from planner import record, TICKS_PER_DAY
    m2 = Memory()
    record([(p[0], {"ok": True})], s, m2)
    assert m2.wishes_agreed == {"TEMPLE|None|None|55": abs_tick(s)}
    s2 = json.loads(json.dumps(s))
    s2["locations"] = {"list": [{"id": 4, "type": "TEMPLE", "deity_hf": 55, "tier": 1, "value": 2400}]}
    s2["petitions"]["pending"][0]["id"] = 190
    props, notes = plan(s2, m2)
    assert not by_rule(props, "petition_answer") and any("not promised twice" in n for n in notes), notes
    s2["date"]["year"] += 2
    assert by_rule(plan(s2, m2)[0], "petition_answer")                # a year on: agreed again
    # agreed: a grand temple dedicated to the deity, unless one is being built
    s["petitions"] = {"agreed": [{"id": 174, "loc": "TEMPLE", "tier": 1, "deity_hf": 55, "deity": "Rimtar", "days": 30}],
                      "pending": [{"id": 175, "type": "Location", "loc": "GUILDHALL", "tier": 1, "profession": "MINER"}]}
    props = plan(s, Memory())[0]
    b = by_rule(props, "petition_build")
    assert b and b[0].action == {"type": "start_project", "kind": "temple", "size": "grand", "deity_hf": 55}, b
    assert not by_rule(props, "petition_answer")                        # one agreed and unbuilt at a time
    s["projects"]["open"] = [{"kind": "temple", "id": 9}]
    assert not by_rule(plan(s, Memory())[0], "petition_build")
    s["projects"]["open"] = []
    # (0.104.138) slots full: waits with a note; its last 112 days: urgent, a slot of its own
    s["projects"]["open"] = [{"kind": "hospital", "id": 7}, {"kind": "dining", "id": 8}]
    props, notes = plan(s, Memory())
    assert not by_rule(props, "petition_build") and any("waits for a building slot" in n for n in notes), notes
    s["petitions"]["agreed"][0]["days"] = 250
    b = by_rule(plan(s, Memory())[0], "petition_build")
    assert b and b[0].action.get("urgent") is True, b
    s["petitions"]["agreed"][0]["days"] = 30
    s["projects"]["open"] = []
    # built and dedicated: the guildhall petition is agreed to next; a low value is noted
    s["locations"]["list"] = [{"id": 4, "type": "TEMPLE", "deity_hf": 55, "tier": 0, "value": 1400}]
    props, notes = plan(s, Memory())
    assert not by_rule(props, "petition_build")
    a = by_rule(props, "petition_answer")
    assert a and a[0].action["id"] == 175 and "guildhall for the miners" in a[0].reason, a
    assert any("worth 1400 of the 2000" in n for n in notes), notes
    s["petitions"] = {"agreed": [{"id": 175, "loc": "GUILDHALL", "tier": 1, "profession": "MINER", "days": 300}]}
    b = by_rule(plan(s, Memory())[0], "petition_build")
    assert b and b[0].action["profession"] == "MINER" and b[0].priority == 4, b   # little time left: sooner
    # (0.104.163) Teacheroar: a miners' guildhall of the right tier stands while DF still lists the
    # agreement (it settles it when the agreement's year is out): no new hall (0.104.160 built
    # four), a note with the days left; the best of several halls is the one compared
    s["locations"]["list"] = [{"id": 19, "type": "GUILDHALL", "profession": "MINER", "tier": 0, "value": 1297},
                              {"id": 10, "type": "GUILDHALL", "profession": "MINER", "tier": 1, "value": 4839}]
    s["petitions"] = {"agreed": [{"id": 250, "loc": "GUILDHALL", "tier": 1, "profession": "MINER", "days": 268},
                                 {"id": 252, "loc": "TEMPLE", "tier": 1, "religion": 281, "days": 117}]}
    s["locations"]["list"].append({"id": 8, "type": "TEMPLE", "religion": 281, "tier": 1, "value": 8709})
    props, notes = plan(s, Memory())
    assert not by_rule(props, "petition_build"), by_rule(props, "petition_build")
    assert any("stands at tier 1" in n and "in about 68 days" in n for n in notes), notes
    # a hall being dug for it: not turned miners -> temple -> miners (0.104.160's loop), cancelled
    # while little is dug and no petition waits that could take it
    s["projects"]["open"] = [{"id": 233, "kind": "temple", "phase": "dig", "dedication": {"profession": "MINER"},
                              "dig": {"dug": 5, "total": 171}}]
    props = plan(s, Memory())[0]
    r = by_rule(props, "petition_retarget")
    assert r and r[0].action == {"type": "cancel_project", "project_id": 233}, r
    s["projects"]["open"][0]["dig"]["dug"] = 100                       # well along: left to finish
    assert not by_rule(plan(s, Memory())[0], "petition_retarget")
    s["projects"]["open"][0]["dig"]["dug"] = 5
    s["petitions"]["pending"] = [{"id": 254, "type": "Location", "loc": "GUILDHALL", "tier": 1,
                                  "profession": "PLANTER"}]                # one waits: kept for it
    assert not any(p.action.get("type") == "cancel_project" for p in by_rule(plan(s, Memory())[0], "petition_retarget"))
    s["projects"]["open"] = []
    s["settings"]["answer_locations"] = False
    props = plan(s, Memory())[0]
    assert not by_rule(props, "petition_build") and not by_rule(props, "petition_answer")
    # a tier-2 wish in a fort that doesn't care for grandeur: declined
    s["settings"]["answer_locations"] = True
    s["petitions"] = {"pending": [{"id": 176, "type": "Location", "loc": "GUILDHALL", "tier": 2, "profession": "MINER"}]}
    s["settings"]["traits"] = {}
    props, notes = plan(s, Memory())
    # (0.105.35) nothing waits for the player: the AI declines it
    d = by_rule(props, "petition_answer")
    assert d and d[0].action["id"] == 176 and d[0].action["accept"] is False, d
    assert not any("left to you" in n for n in notes), notes


@test("a hall being dug whose petition was met meanwhile (0.92) goes to the next petition")
def _():
    s = fort()
    s["petitions"] = {"agreed": [{"id": 176, "loc": "GUILDHALL", "tier": 1, "profession": "METALSMITH", "days": 120},
                                 {"id": 177, "loc": "GUILDHALL", "tier": 1, "profession": "FARMER", "days": 70}]}
    s["locations"]["list"] = [{"id": 4, "type": "GUILDHALL", "profession": "METALSMITH", "tier": 1, "value": 3018,
                               "zones": [1138]}]
    s["projects"]["open"] = [{"id": 221, "kind": "temple", "phase": "dig", "dedication": {"profession": "METALSMITH"}}]
    p = by_rule(plan(s, Memory())[0], "petition_retarget")
    assert p and p[0].action == {"type": "retarget_hall", "project_id": 221, "profession": "FARMER"}, p
    s["projects"]["open"][0]["phase"] = "furnish"                          # its zone stands: left as it is
    assert not by_rule(plan(s, Memory())[0], "petition_retarget")
    s["projects"]["open"][0]["phase"] = "dig"
    s["locations"]["list"] = []                                              # its own wish not met: kept
    assert not by_rule(plan(s, Memory())[0], "petition_retarget")


@test("meetings (0.91): the meeting screen waiting is Needs you; a meeting under way is a note")
def _():
    s = fort()
    s["meetings"] = {"activities": [{"actor": "Lolor, outpost liaison", "noble": "Urist, mayor", "flags": []}],
                     "popups": 0, "screen": "dwarfmode/Default"}
    notes = plan(s, Memory())[1]
    assert any(n.startswith("meetings under way: Lolor, outpost liaison with Urist, mayor") for n in notes), notes
    s["meetings"]["popups"] = 1                                     # (0.94.1) queued: the game runs on, a note
    notes = plan(s, Memory())[1]
    assert not any(n.startswith("[you]") and "meeting" in n for n in notes), notes
    assert any(n.startswith("a meeting waits to be shown in DF (Lolor") for n in notes), notes
    s["meetings"]["screen"] = "dwarfmode/Diplomacy"                  # the screen itself: Needs you
    notes = plan(s, Memory())[1]
    assert any(n.startswith("[you] DF's meeting screen is open") for n in notes), notes


@test("a petition's hall to its tier (0.90): statues into its zone once built, made when none are free")
def _():
    s = fort()
    s["orders"] = []
    s["petitions"] = {"agreed": [{"id": 176, "loc": "GUILDHALL", "tier": 1, "profession": "METALSMITH", "days": 80}]}
    s["locations"]["list"] = [{"id": 5, "type": "GUILDHALL", "profession": "METALSMITH", "tier": 0, "value": 900,
                               "zones": [612]}]
    s["supplies"]["statues"] = 2
    s["projects"]["open"] = [{"kind": "temple", "id": 221}]
    assert not by_rule(plan(s, Memory())[0], "location_value")          # still being built and engraved
    s["projects"]["open"] = []
    p = by_rule(plan(s, Memory())[0], "location_value")
    assert p and p[0].action == {"type": "place_in_zone", "zone_id": 612, "what": "statue"}, p
    assert "worth 900 of the 2000" in p[0].reason
    s["supplies"]["statues"] = 0
    p = by_rule(plan(s, Memory())[0], "location_value")
    assert p and p[0].action["recipe"] == "stone_statue", p
    s["locations"]["list"][0].update(value=2100, tier=1)
    assert not by_rule(plan(s, Memory())[0], "location_value")


@test("the elves' tree quota (0.89): felling counted from the year's start; autochop off near the cap")
def _():
    from planner import note_cycle, Proposal, record
    s = fort()
    s["tools"]["autochop"] = True
    s["diplomacy"] = {"trees_removed": 500, "tree_cap": 100, "elves": True}
    m = Memory()
    note_cycle(s, m)
    assert m.tree_year == {"year": s["date"]["year"], "base": 500}
    s["diplomacy"]["trees_removed"] = 560
    props, notes = plan(s, m)
    assert not by_rule(props, "tree_quota")
    s["diplomacy"]["trees_removed"] = 585                                 # 85 of 100
    note_cycle(s, m)
    props, notes = plan(s, m)
    q = by_rule(props, "tree_quota")
    assert q and q[0].action == {"type": "tool", "name": "autochop", "enabled": False}, q
    assert any("85 trees felled this year, of the 100" in n for n in notes), notes
    m.tools_seen_on.append("autochop")
    record([(q[0], {"ok": True, "enabled": False})], s, m)
    s["tools"]["autochop"] = False
    note_cycle(s, m)
    assert "autochop" not in m.tools_player_disabled                    # the AI's own choice
    assert not by_rule(plan(s, m)[0], "tools") or all(p.action.get("name") != "autochop"
                                                      for p in by_rule(plan(s, m)[0], "tools"))
    s["date"]["year"] += 1                                                # a new year: the count starts again
    note_cycle(s, m)
    assert m.tree_year["base"] == 585
    s["diplomacy"]["elves"] = False                                       # no elves: no quota
    s["date"]["year"] -= 1
    note_cycle(s, m)
    assert not by_rule(plan(s, m)[0], "tree_quota")


@test("hospital staff labours (0.87.3, live): a post holder without the post's labours gets them, first")
def _():
    import json as _json
    s = fort()
    s["dwarves"]["needs_medical_care"] = 1
    staff = [{"post": "DOCTOR", "labors": ["SUTURING", "DRESSING_WOUNDS"]},
             {"post": "DIAGNOSTICIAN", "labors": ["DIAGNOSE", "SUTURING"]},
             {"post": "BONE_DOCTOR", "labors": ["SUTURING"]}]
    s["health"] = {"hospital": [{"id": 1, "staff": staff, "zones": [{"type": "MeetingHall", "beds": 4}]}]}
    s["locations"] = {"count": {"HOSPITAL": 1}, "total": 1, "list": [{"id": 1, "type": "HOSPITAL", "jobs": {}}]}
    p = by_rule(plan(s, Memory())[0], "staff")
    assert p and p[0].action == {"type": "staff_labors", "location_id": 1} and p[0].priority == 2, p
    assert "doctor, bone doctor" in p[0].reason, p[0].reason
    for st, labs in zip(staff, (["DIAGNOSE", "SURGERY", "BONE_SETTING", "SUTURING", "DRESSING_WOUNDS"],
                                ["DIAGNOSE"], ["BONE_SETTING"])):
        st["labors"] = labs
    p = by_rule(plan(s, Memory())[0], "staff")
    assert not p or p[0].action["type"] != "staff_labors", p


@test("gems: rough gems -> a jeweller's, then autogems cuts them; crafts target grows with Trade focus")
def _():
    s = fort()
    s["stocks"]["rough_gems"] = 34
    s["buildings"]["workshops"].pop("Jewelers", None)
    s["projects"]["open"] = []
    g = by_rule(plan(s, Memory())[0], "gems")
    assert g and g[0].action == {"type": "start_project", "kind": "workshops", "shops": ["Jewelers"]}, g
    s["buildings"]["workshops"]["Jewelers"] = 1
    s["tools"]["autogems"] = False
    t = [p for p in by_rule(plan(s, Memory())[0], "tools") if p.action["name"] == "autogems"]
    assert t and not by_rule(plan(s, Memory())[0], "gems"), t
    s["trade"] = {"depot": True, "caravans": [], "goods": 17, "cut_gem": {"token": "INORGANIC:AMETHYST", "n": 8, "total": 9}}
    s["orders"] = []
    e = by_rule(plan(s, Memory())[0], "encrust")
    assert e and e[0].action == {"type": "work_order", "recipe": "encrust_goods", "amount": 4,
                                 "material": "INORGANIC:AMETHYST"}, e


@test("barracks: a squad without one is given the barracks with the fewest squads; one a cycle")
def _():
    s = fort()
    s["military"]["barracks"] = [{"id": 900, "squads": [99]}, {"id": 901, "squads": []}]
    b = by_rule(plan(s, Memory())[0], "barracks_assign")
    sid = s["military"]["squads"][0]["id"]
    assert b and b[0].action == {"type": "squad_barracks", "squad_id": sid, "zone_id": 901}, b
    s["military"]["barracks"][1]["squads"] = [q["id"] for q in s["military"]["squads"]]
    assert not by_rule(plan(s, Memory())[0], "barracks_assign")


@test("gear: soldiers off duty put weapons away -- not a shortage")
def _():
    assert not by_rule(plan(geared(soldiers=33, on_duty=0, armed=10, armored=33, helmed=31), Memory())[0], "arms")
    a = by_rule(plan(geared(soldiers=33, on_duty=20, armed=10, armored=20, helmed=20,
                            spare={"weapons": 2}), Memory())[0], "arms")
    assert a and a[0].action["amount"] == 8, a                     # 20 on duty - 10 armed - 2 spare


@test("soldier swap (0.104.138): never one swapped this year or drafted lately; the fill passes over those sent home")
def _():
    from planner import record
    s = fort()
    s["needs"] = {"needs": {}, "keen_civilians": 33,
                  "starved_soldiers": [{"id": 8, "name": "Bim", "unmet": ["CraftObject", "BeWithFriends"]}]}
    now = abs_tick(s)
    m = Memory(swapped={"8": now - 100 * TICKS_PER_DAY})
    assert not by_rule(plan(copy.deepcopy(s), m)[0], "soldier_swap"), "swapped 100 days ago"
    m = Memory(drafted={"8": now - 20 * TICKS_PER_DAY})
    assert not by_rule(plan(copy.deepcopy(s), m)[0], "soldier_swap"), "drafted 20 days ago"
    m = Memory(swapped={"5": now - 10 * TICKS_PER_DAY})
    w = by_rule(plan(copy.deepcopy(s), m)[0], "soldier_swap")
    assert w and w[0].action.get("avoid") == [5], w
    record([(w[0], {"ok": True, "filled": {"added": [{"unit_id": 44}]}})], s, m)
    assert "44" in m.drafted and "8" in m.swapped, (m.drafted, m.swapped)


@test("soldier swap (0.104.64): a soldier trained enough and starved of the rest goes home while civilians badly want to train")
def _():
    s = fort()
    s["needs"] = {"needs": {}, "keen_civilians": 33,
                  "starved_soldiers": [{"id": 7, "name": "Urist", "unmet": ["CraftObject", "BeWithFriends"]},
                                       {"id": 8, "name": "Bim", "unmet": ["CraftObject", "BeWithFriends", "PrayOrMeditate"]}]}
    w = by_rule(plan(s, Memory())[0], "soldier_swap")
    assert w and w[0].action == {"type": "squad_swap", "unit_id": 8}, w         # the most starved first, one at a time
    few = copy.deepcopy(s); few["needs"]["keen_civilians"] = 2
    assert not by_rule(plan(few, Memory())[0], "soldier_swap")
    war = copy.deepcopy(s); war["others_on_map"] = {"threats_that_can_reach_dwarves": 3}
    assert not by_rule(plan(war, Memory())[0], "soldier_swap")
    # (0.104.78) one sent home (or found already out) isn't asked for again for a week
    from planner import record
    m = Memory()
    record([(w[0], {"ok": False, "rejected": True, "error": "not in a squad"})], s, m)
    w2 = by_rule(plan(s, m)[0], "soldier_swap")
    assert w2 and w2[0].action["unit_id"] == 7, w2
    # (0.104.114) at most a tenth of the soldiers (2 at least) swapped in 28 days
    s["needs"]["starved_soldiers"].append({"id": 9, "name": "Kib", "unmet": ["CraftObject", "BeWithFriends"]})
    s.setdefault("military", {}).setdefault("gear", {})["soldiers"] = 12
    record([(w2[0], {"ok": True})], s, m)                           # two swapped this month
    assert by_rule(plan(copy.deepcopy(s), m)[0], "soldier_swap"), "(0.104.142) 33 keen: 8 a month"
    s["needs"]["keen_civilians"] = 7
    assert not by_rule(plan(copy.deepcopy(s), m)[0], "soldier_swap"), "the month's swaps are used"
    s["date"]["tick"] += 29 * 1200
    assert by_rule(plan(copy.deepcopy(s), m)[0], "soldier_swap")
    big = copy.deepcopy(s)                                           # (0.104.66) no trim while the keen wait
    big["military"]["soldiers"] = 60
    assert not by_rule(plan(big, Memory())[0], "squad_trim")
    big["needs"]["keen_civilians"] = 0
    assert by_rule(plan(big, Memory())[0], "squad_trim")


@test("bins (0.104.75): full finished-goods piles want more bins than the per-dwarf count")
def _():
    s = fort()
    s["dwarves"]["total"] = 94
    s["stocks"].update(bins=48, wood=533)
    s.setdefault("logistics", {})["storage"] = {"finished_goods": {"tiles": 1522, "used": 1520, "loose": 166, "piles": 34}}
    b = by_rule(plan(s, Memory())[0], "bins")
    assert b and b[0].action["recipe"] == "wooden_bin" and "finished-goods piles are full" in b[0].reason, b
    s["logistics"]["storage"]["finished_goods"].update(used=900, loose=0)
    assert not by_rule(plan(s, Memory())[0], "bins")                  # 48 for 94 is the usual count


@test("pair chairs (0.104.77): while many badly want friends, the tavern's lone chairs get a neighbour")
def _():
    s = fort()
    s["dwarves"]["total"] = 95
    s["locations"] = {"list": [{"id": 5, "type": "INN_TAVERN", "zones": [1081], "chests": 2,
                                "have": {"goblets": 10, "instruments": 5}, "want": {"goblets": 10, "instruments": 5}}]}
    s.setdefault("needs", {}).setdefault("needs", {})["BeWithFriends"] = {"badly": 42, "distracted": 57}
    c = by_rule(plan(s, Memory())[0], "pair_chairs")
    assert c and c[0].action == {"type": "pair_chairs", "zones": [1081], "max": 10}, c   # (0.104.137) 42 badly // 4
    s["needs"]["needs"]["BeWithFriends"]["badly"] = 5
    assert not by_rule(plan(s, Memory())[0], "pair_chairs")


@test("recreation (0.104.78): while civilians are very unhappy or worse, or the burrow has members, the bridge is asked")
def _():
    s = fort()
    s["dwarves"]["total"] = 95
    s["needs"] = {"needs": {}, "stressed": [{"id": 1, "name": "A", "stress": "miserable", "unmet": []},
                                             {"id": 2, "name": "B", "stress": "very_unhappy", "unmet": [], "squad": True}]}
    r = by_rule(plan(s, Memory())[0], "recreation")
    assert r and r[0].action == {"type": "recreation", "max": 8, "days": 28} and r[0].reason.startswith("1 civilian"), r
    calm = copy.deepcopy(s); calm["needs"]["stressed"] = []
    assert not by_rule(plan(calm, Memory())[0], "recreation")
    calm.setdefault("society", {})["recreation"] = {"members": 3}       # members to let out
    assert by_rule(plan(calm, Memory())[0], "recreation")
    small = copy.deepcopy(s); small["dwarves"]["total"] = 12
    assert not by_rule(plan(small, Memory())[0], "recreation")


@test("dairy (0.104.79): milk the tame animals, make cheese of the milk, while cheese is short")
def _():
    s = fort()
    s["dwarves"]["total"] = 88
    s["buildings"]["workshops"]["Farmers"] = 1
    s.setdefault("supplies", {}).update(milkable=4, milk=0)
    s["stocks"]["cheese"] = 0
    d = by_rule(plan(s, Memory())[0], "dairy")
    assert d and d[0].action == {"type": "work_order", "recipe": "milk_creature", "amount": 4}, d
    s["supplies"]["milk"] = 7
    d = by_rule(plan(s, Memory())[0], "dairy")
    assert d and d[0].action == {"type": "work_order", "recipe": "make_cheese", "amount": 5}, d
    s["stocks"]["cheese"] = 100
    assert not by_rule(plan(s, Memory())[0], "dairy")


@test("eggs (0.104.80): stone nest boxes ordered for the hens; the hens penned with boxes in their pasture")
def _():
    s = fort()
    s["dwarves"]["total"] = 88
    s["buildings"]["workshops"]["Masons"] = 1
    s.setdefault("supplies", {}).update(egg_layers=6, egg_layers_penned=2, nest_boxes=0, nest_box_items=0)
    ps = plan(s, Memory())[0]
    o, e = by_rule(ps, "nest_box_order"), by_rule(ps, "eggs")
    assert o and o[0].action == {"type": "work_order", "recipe": "stone_nest_box", "amount": 5}, o
    assert e and e[0].action == {"type": "nest_boxes", "max": 3} and "4 hens in no pasture" in e[0].reason, e
    s["supplies"].update(egg_layers_penned=6, nest_box_items=6)
    ps = plan(s, Memory())[0]
    assert not by_rule(ps, "nest_box_order") and by_rule(ps, "eggs")       # enough boxes to build
    s["supplies"].update(nest_boxes=6, nest_box_items=0)
    ps = plan(s, Memory())[0]
    assert not by_rule(ps, "nest_box_order") and not by_rule(ps, "eggs")   # a box a hen
    s["supplies"].update(egg_layers=1, nest_boxes=0)
    assert not by_rule(plan(s, Memory())[0], "eggs")                       # one hen: not worth it


@test("recreation (0.104.80): places for those badly wanting friends while a fifth of the fort does")
def _():
    s = fort()
    s["dwarves"]["total"] = 88
    s.setdefault("needs", {}).setdefault("needs", {})["BeWithFriends"] = {"badly": 42, "badly_soldiers": 17}
    r = by_rule(plan(s, Memory())[0], "recreation")
    assert r and r[0].action.get("friends") == 5 and r[0].action.get("friend_days") == 7, r   # (0.104.137) 25 // 5
    assert "25 civilian(s) badly wanting friends" in r[0].reason, r[0].reason
    # (0.104.139) while the fort's own kill each other: no crowd, no places for friends
    f = copy.deepcopy(s)
    f["society"] = dict(f.get("society") or {}, recreation={"members": 3})
    m = Memory(fight_deaths=[abs_tick(f)])
    r = by_rule(plan(f, m)[0], "recreation")
    assert r and "friends" not in r[0].action and r[0].action["max"] == 8, r
    s["needs"]["needs"]["BeWithFriends"] = {"badly": 10, "badly_soldiers": 2}
    assert not by_rule(plan(s, Memory())[0], "recreation")       # under a fifth, nobody low, nobody in


@test("magma twins (0.104.81): a magma smelter, kiln or forge counts as its plain twin, once a report")
def _():
    from digest import normalize
    s = fort()
    s["buildings"]["furnaces"] = {"MagmaSmelter": 1, "WoodFurnace": 1}
    s["buildings"]["workshops"].pop("MetalsmithsForge", None)
    s["buildings"]["workshops"]["MagmaForge"] = 2
    normalize(s); normalize(s)
    assert s["buildings"]["furnaces"]["Smelter"] == 1 and s["buildings"]["workshops"]["MetalsmithsForge"] == 2


@test("action log (0.104.81): keys with nothing in the last year are dropped at the cycle's start")
def _():
    s = fort()
    m = Memory()
    now = planner.abs_tick(s)
    m.action_log = {"old:1": [now - planner.TICKS_PER_YEAR - 5], "new:2": [now - 10], "empty:3": []}
    note_cycle(s, m)
    assert list(m.action_log) == ["new:2"], m.action_log


@test("war animals (0.104.81): a trainer first, then a few to war training a call, up to the wanted number")
def _():
    s = fort()
    s["dwarves"]["total"] = 88
    s["society"]["animals"] = {"war_candidates": 12, "war_trained": 0, "in_training": 0, "trainers": 0}
    ps = plan(s, Memory())[0]
    a = by_rule(ps, "animal_trainer")
    assert a and a[0].action == {"type": "assign_labor", "job": "ANIMALTRAIN", "count": 1} and not by_rule(ps, "war_animals"), a
    s["society"]["animals"]["trainers"] = 1
    w = by_rule(plan(s, Memory())[0], "war_animals")
    assert w and w[0].action == {"type": "train_war", "max": 3}, w
    s["society"]["animals"].update(war_trained=4, in_training=3)
    w = by_rule(plan(s, Memory())[0], "war_animals")
    assert w and w[0].action["max"] == 1, w                                   # 7 of 8
    s["society"]["animals"]["in_training"] = 4
    assert not by_rule(plan(s, Memory())[0], "war_animals")
    s["society"]["animals"] = {"error": "no training list"}
    assert not by_rule(plan(s, Memory())[0], "war_animals")


@test("gem cutting (0.104.84): with no autogems in DFHack, the commonest rough gem is cut by work order")
def _():
    s = fort()
    s["stocks"]["rough_gems"] = 293
    s.setdefault("trade", {})["rough_gem"] = {"token": "INORGANIC:AMETHYST", "n": 40, "total": 293}
    s["tools"] = {"autofarm": True}                                    # autogems unknown to this DFHack
    g = by_rule(plan(s, Memory())[0], "gem_cutting")
    assert g and g[0].action == {"type": "work_order", "recipe": "cut_gems", "amount": 10,
                                 "material": "INORGANIC:AMETHYST"}, g
    s["tools"]["autogems"] = True                                      # the tool does it
    assert not by_rule(plan(s, Memory())[0], "gem_cutting")


@test("bags (0.104.87): with no clothier's workshop the AI builds one instead of ordering bags that never start")
def _():
    s = fort()
    s["buildings"]["workshops"].pop("Clothiers", None)
    s["projects"]["open"] = []
    s["supplies"].update(empty_bags=0, cloth_kinds={"plant": 5, "silk": 0, "yarn": 0})
    b = by_rule(plan(s, Memory())[0], "bags")
    assert b and b[0].action == {"type": "start_project", "kind": "workshops", "shops": ["Clothiers"]}, b
    s["buildings"]["workshops"]["Clothiers"] = 1
    b = by_rule(plan(s, Memory())[0], "bags")
    assert b and b[0].action["recipe"] == "cloth_bag", b
    from planner import recipe_shop
    assert recipe_shop("cloth_bag") == recipe_shop("silk_bag") == "Clothiers"


@test("library chest (0.104.79): a library short of paper with no chest gets one")
def _():
    s = fort()
    s["locations"] = {"list": [{"id": 8, "type": "LIBRARY", "chests": 0, "zones": [1644], "books": 0,
                                "have": {"paper": 0}, "want": {"paper": 10}}]}
    c = by_rule(plan(s, Memory())[0], "library_chest")
    assert c and c[0].action == {"type": "place_in_zone", "zone_id": 1644, "what": "chest"}, c
    s["locations"]["list"][0]["chests"] = 1
    assert not by_rule(plan(s, Memory())[0], "library_chest")


@test("crops (0.104.79): plots lying fallow get thresholds that grow with the fort, once")
def _():
    s = fort()
    s["dwarves"]["total"] = 88
    s["farms"] = {"built": 10, "plots": 12, "crops": {
        "MUSHROOM_HELMET_PLUMP": {"name": "plump helmet", "brews": "plant", "seeds": 131, "stock": 73, "planted": 0,
                                  "seasons": ["spring"], "underground": True},
        "CHICORY": {"name": "chicory", "seeds": 51, "stock": 59, "planted": 0, "seasons": ["spring"]}}}
    m = Memory()
    c = by_rule(plan(s, m)[0], "crops")
    assert c and c[0].action["steer"] == "pop", c
    assert c[0].action["thresholds"] == {"MUSHROOM_HELMET_PLUMP": 352, "CHICORY": 176}, c[0].action
    m.farm_steer = "pop"                                             # done: not asked again
    assert not by_rule(plan(s, m)[0], "crops")
    m.farm_steer = ""
    for v in s["farms"]["crops"].values():
        v["planted"] = 6                                             # planted: nothing to do
    assert not by_rule(plan(s, m)[0], "crops")


@test("stray gear (0.104.58): gear the game lost track of is put back on its list; none lost, nothing")
def _():
    s = geared(soldiers=26, on_duty=26, armed=7, armored=20, helmed=20, spare={"weapons": 1}, bars={"STEEL": 53})
    assert not by_rule(plan(s, Memory())[0], "stray_gear")
    s["military"]["gear"]["stray"] = {"n": 4, "orphan": {"WEAPON": 1, "HELM": 1}, "unlisted": {"WEAPON": 1, "HELM": 1}}
    g = by_rule(plan(s, Memory())[0], "stray_gear")
    assert g and g[0].action == {"type": "free_stray_gear", "limit": 100}, g
    assert "helm, weapon" in g[0].reason, g[0].reason
    assert "3 piece(s)" in g[0].reason, g[0].reason
    armour_only = copy.deepcopy(s)                          # armour on no list isn't moved: nothing to ask
    armour_only["military"]["gear"]["stray"] = {"n": 4, "unlisted": {"HELM": 4}}
    assert not by_rule(plan(armour_only, Memory())[0], "stray_gear")
    off = copy.deepcopy(s)
    off["military"]["gear"]["on_duty"] = 0                 # off duty: no one to hand it to
    assert not by_rule(plan(off, Memory())[0], "stray_gear")


@test("assign weapons (0.104.60): places left without a weapon a week while free ones lie about -> the AI hands them out")
def _():
    s = geared(soldiers=26, on_duty=26, armed=6, armored=21, helmed=20, spare={"weapons": 19}, bars={"STEEL": 53},
               weapon_gaps=19, spare_weapons={"ITEM_WEAPON_AXE_BATTLE": 19, "ITEM_WEAPON_PICK": 3})
    m = Memory()
    note_cycle(s, m)
    assert not by_rule(plan(s, m)[0], "assign_weapons"), "DF gets a week first"
    later = copy.deepcopy(s)
    later["date"]["tick"] += 7 * 1200
    note_cycle(later, m)
    a = by_rule(plan(later, m)[0], "assign_weapons")
    assert a and a[0].action == {"type": "assign_weapons", "limit": 10}, a
    picks = copy.deepcopy(later)                         # only miners' picks free: nothing to hand out
    picks["military"]["gear"]["spare_weapons"] = {"ITEM_WEAPON_PICK": 3}
    m2 = Memory()
    note_cycle(picks, m2)
    assert "weapon_gaps" not in m2.gear_spare_since
    done = copy.deepcopy(later)                          # every place has its weapon: the timer stops
    done["military"]["gear"]["weapon_gaps"] = 0
    done["military"]["gear"]["melee_given"] = 26         # given, not fetched yet: no more axes made
    done["military"]["gear"]["spare_weapons"] = {"ITEM_WEAPON_AXE_BATTLE": 0}
    done["military"]["gear"]["spare"] = {"weapons": 0, "body": 0, "helms": 0}
    arms = [p for p in by_rule(plan(done, Memory())[0], "arms") if p.action["recipe"] == "metal_battle_axe"]
    assert not arms, arms
    note_cycle(done, m)
    assert "weapon_gaps" not in m.gear_spare_since and not by_rule(plan(done, m)[0], "assign_weapons")


@test("guard (0.105.8): every fort of 15+ adults wants 3 soldiers at least, whatever the Militarism")
def _():
    from planner_military import soldiers_wanted
    for mil in (-100, -60, 0):
        s = fort()
        s["settings"]["traits"]["militarism"] = mil
        s["dwarves"].update(total=15, adults=15, idle_adults=0)
        assert soldiers_wanted(s, 15, PLANNER_CONFIG) >= 3, (mil, soldiers_wanted(s, 15, PLANNER_CONFIG))
    s = fort()
    s["settings"]["traits"]["militarism"] = -100
    s["dwarves"].update(total=14, adults=14, idle_adults=0)
    assert soldiers_wanted(s, 14, PLANNER_CONFIG) < 3          # a smaller fort: by its slider, as before
    s["dwarves"].update(total=40, adults=40)
    assert soldiers_wanted(s, 40, PLANNER_CONFIG) == 3         # Monastery at 40: 5% is 2, the guard 3


@test("assign kit (0.105.8): armour places the bridge could fill, left 3 days -> the AI hands the armour out")
def _():
    s = geared(soldiers=9, on_duty=9, armed=9, armored=7, helmed=6, spare={"gloves": 10, "boots": 10}, bars={"IRON": 57})
    s["military"]["gear"]["kit"] = {"fillable": 9, "gloves": {"why": {"fillable": 7}}, "boots": {"why": {"fillable": 4}},
                                    "body": {"why": {"fillable": 2}}}
    m = Memory()
    note_cycle(s, m)
    assert not by_rule(plan(s, m)[0], "assign_kit"), "DF gets 3 days first"
    later = copy.deepcopy(s)
    later["date"]["tick"] += 3 * 1200
    note_cycle(later, m)
    a = by_rule(plan(later, m)[0], "assign_kit")
    assert a and a[0].action == {"type": "assign_kit", "limit": 20} and "gloves 7" in a[0].reason, a
    done = copy.deepcopy(later)
    done["military"]["gear"]["kit"] = {"fillable": 0}
    note_cycle(done, m)
    assert "kit_gaps" not in m.gear_spare_since and not by_rule(plan(done, m)[0], "assign_kit")
    off = copy.deepcopy(later)                       # nobody on duty: no timer
    off["military"]["gear"]["on_duty"] = 0
    m2 = Memory(); note_cycle(off, m2)
    assert "kit_gaps" not in m2.gear_spare_since
    import overseer
    assert "armour" in overseer.short({"type": "assign_kit", "limit": 20})


@test("gear (game): 3+ spares lying unused -> no more made; after a week a note (0.105.35: not Needs you), a month: made")
def _():
    s = geared(soldiers=33, on_duty=33, armed=17, armored=33, helmed=33, spare={"weapons": 7},
               bars={"STEEL": 64})
    m = Memory()
    note_cycle(s, m)
    p, notes = plan(s, m)
    assert not by_rule(p, "arms"), "7 axes already lie unused: more is wasted steel"
    assert any("7 spare weapons not picked up yet" in n for n in notes), notes
    u = by_rule(p, "unstick_uniforms")                             # (0.99.7) untangle them first
    assert u and u[0].action == {"type": "unstick_uniforms"}, u
    later = copy.deepcopy(s)
    later["date"]["tick"] += 7 * 1200
    note_cycle(later, m)
    notes = plan(later, m)[1]
    assert any(n.startswith("7 weapons lie unused") and "uniforms" in n for n in notes), notes
    assert not any(n.startswith("[you]") and "lie unused" in n for n in notes), notes
    picked = copy.deepcopy(later)                                  # soldiers took them
    picked["military"]["gear"]["spare"] = {"weapons": 0}
    picked["military"]["gear"]["armed"] = 24
    note_cycle(picked, m)
    assert "weapons" not in m.gear_spare_since
    a = by_rule(plan(picked, m)[0], "arms")
    assert a and a[0].action["amount"] == 9, a                     # 33 - 24


@test("gear (0.104.138): no hand-out the bridge's dry run can't fill; armour made again after a month unused; untangling stops when it changes nothing")
def _():
    s = geared(soldiers=26, on_duty=26, armed=6, armored=21, helmed=20, spare={"weapons": 19}, bars={"STEEL": 53},
               weapon_gaps=19, weapon_gaps_fillable=0, spare_weapons={"ITEM_WEAPON_AXE_BATTLE": 19})
    m = Memory()
    note_cycle(s, m)
    later = copy.deepcopy(s)
    later["date"]["tick"] += 8 * 1200
    note_cycle(later, m)
    assert not by_rule(plan(later, m)[0], "assign_weapons"), "every free axe is an artifact: nothing fits"
    h = geared(soldiers=30, on_duty=30, armed=30, armored=30, helmed=10, spare={"helms": 4}, bars={"STEEL": 64})
    m = Memory()
    note_cycle(h, m)
    assert not any(p.action.get("recipe") == "metal_helm" for p in by_rule(plan(h, m)[0], "arms"))
    month = copy.deepcopy(h)
    month["date"]["tick"] += 29 * 1200
    note_cycle(month, m)
    p, notes = plan(month, m)
    assert any(x.action.get("recipe") == "metal_helm" for x in by_rule(p, "arms")), (by_rule(p, "arms"), notes)
    assert not any(n.startswith("[you] 4 helms") for n in notes), notes
    u = by_rule(p, "unstick_uniforms")
    assert u
    record([(u[0], {"ok": True})], month, m)
    record([(u[0], {"ok": True})], month, m)
    p, notes = plan(month, m)
    assert not by_rule(p, "unstick_uniforms") and any("changed nothing" in n for n in notes), notes


@test("gear: then body armour, then helms; one order at a time; queued orders count")
def _():
    a = by_rule(plan(geared(armored=15, helmed=10), Memory())[0], "arms")
    assert len(a) == 1 and a[0].action["recipe"] == "metal_mail_shirt" and a[0].action["amount"] == 5, a
    s = geared(armored=15, helmed=10)
    s["orders"].append({"id": 5, "recipe": "metal_mail_shirt", "amount_left": 5, "amount_total": 5})
    assert by_rule(plan(s, Memory())[0], "arms")[0].action["recipe"] == "metal_helm"


@test("gear: no uniform, no forge, no bars, or switched off -> no order (a note says why)")
def _():
    p, notes = plan(geared(armed=0, squads_with_uniform=0), Memory())
    assert not by_rule(p, "arms") and any("no squad has a uniform" in n for n in notes), notes
    p, notes = plan(geared(armed=0, forges=0), Memory())
    assert not by_rule(p, "arms") and any("no forge" in n for n in notes), notes
    # (0.105.35) no forge at all: the AI builds one (it asked the player before)
    s = geared(armed=0, forges=0)
    for k in ("workshops", "furnaces"):
        for w in ("MetalsmithsForge", "MagmaForge"):
            _d_ = s["buildings"].get(k)
            if isinstance(_d_, dict):
                _d_.pop(w, None)
    s["projects"]["open"] = []
    p, notes = plan(s, Memory())
    f = by_rule(p, "arms_forge")
    assert f and f[0].action == {"type": "start_project", "kind": "workshops", "shops": ["MetalsmithsForge"]}, f
    assert not any(n.startswith("[you]") and "forge" in n for n in notes), notes
    p, notes = plan(geared(armed=0, bars={"GOLD": 500, "COPPER": 3}), Memory())
    assert not by_rule(p, "arms") and any("weapon-grade metal" in n for n in notes), notes
    assert not any(n.startswith("[you]") and "weapon-grade" in n for n in notes), notes
    s = geared(armed=0, bars={})                                  # the AI is smelting: a note, not Needs you
    s["buildings"]["furnaces"]["Smelter"] = 1
    s["industry"] = {"ores": {"IRON": {"tiles": 50, "ore": "MAGNETITE"}}}
    m = Memory()
    m.libraries_imported = ["smelting"]
    notes = plan(s, m)[1]
    assert any("being mined and smelted" in n for n in notes) and not any("no ore of it" in n for n in notes), notes
    s = geared(armed=0, squads_with_uniform=0)                    # templates: the AI gives a uniform itself
    s["military"]["uniform_templates"] = ["Melee, leather armor"]
    assert not any("no squad has a uniform" in n for n in plan(s, Memory())[1])
    s = geared(armed=0)
    s["settings"]["make_gear"] = False
    assert not by_rule(plan(s, Memory())[0], "arms")


@test("gear: not judged for 3 days after squads are put on training (they're still picking it up)")
def _():
    s = geared(armed=0)
    m = Memory(last_train_tick=s["date"]["year"] * 403200 + s["date"]["tick"] - 1200)
    assert not by_rule(plan(s, m)[0], "arms")
    m.last_train_tick -= 3 * 1200
    assert by_rule(plan(s, m)[0], "arms")


@test("society: vacant offices, starving dwarves, grazers without pasture -> needs you (farms: the AI's job now)")
def _():
    s = fort()
    s["society"] = {"vacant": ["BROKER", "CHIEF_MEDICAL_DWARF"], "starving": 2, "parched": 0,
                    "hungry_names": ["Urist"], "grazers_unpastured": 6}
    s["buildings"]["other"].pop("FarmPlot")
    s["farms"] = {"plots": 0, "tiles": 0, "built": 0}
    props, notes = plan(s, Memory())
    you = [n for n in notes if n.startswith("[you] ")]
    text = " | ".join(you)
    assert "broker" not in text and "starving" not in text, text        # the AI appoints those
    # (0.105.35) starving: a note of what the AI does, not "check they can reach"
    assert any(n.startswith("2 dwarves are starving") and "check" not in n for n in notes), notes
    ap = sorted(p.action["office"] for p in by_rule(props, "appoint"))
    assert ap == ["BROKER", "CHIEF_MEDICAL_DWARF"], ap
    s2 = copy.deepcopy(s)
    s2["settings"]["appoint_nobles"] = False                                    # switched off: asks you
    _, notes2 = plan(s2, Memory())
    assert any("broker (trading), chief medical dwarf" in n for n in notes2), notes2
    # (0.105.35) no grass figures: the AI makes a pasture by a guess, no Needs you
    assert "grazing" not in text and "farm" not in text, text
    assert by_rule(props, "new_pasture"), rules(props)
    assert by_rule(props, "farms"), rules(props)
    s["society"]["vacant"] = ["SHERIFF"]                  # a captain of the guard holds the job
    _, notes = plan(s, Memory())
    assert not any("offices" in n for n in notes), notes
    s["society"]["vacant"] = ["CAPTAIN_OF_THE_GUARD"]      # the post a growing fort adds: filled
    props, _ = plan(s, Memory())
    assert [p.action["office"] for p in by_rule(props, "appoint")] == ["CAPTAIN_OF_THE_GUARD"], rules(props)
    s["society"]["vacant"] = ["CAPTAIN_OF_THE_GUARD", "SHERIFF"]
    props, notes = plan(s, Memory())
    assert not any("offices" in n for n in notes), notes                # the AI appoints the sheriff (0.44)
    assert [p.action["office"] for p in by_rule(props, "appoint")] == ["SHERIFF"]
    s["settings"]["appoint_nobles"] = False
    _, notes = plan(s, Memory())
    assert any("sheriff (justice)" in n and "captain" not in n for n in notes), notes


@test("smelting: metal low and a smelter -> DFHack's smelting orders, once; no smelter -> needs you")
def _():
    s = geared(bars={"IRON": 10, "COPPER": 5})
    m = Memory()
    p, _ = plan(s, m)
    sm = by_rule(p, "smelting")
    assert sm and sm[0].action == {"type": "import_orders", "library": "smelting"}, sm
    record([(sm[0], {"ok": True, "added": 40})], s, m)
    assert m.libraries_imported == ["smelting"] and not by_rule(plan(s, m)[0], "smelting")
    s["buildings"]["furnaces"].pop("MagmaSmelter")
    s["buildings"]["furnaces"].pop("Smelter", None)
    _, notes = plan(s, Memory())
    assert any("no ore uncovered" in n for n in notes), notes               # no smelter: wait for ore
    assert not by_rule(plan(geared(), Memory())[0], "smelting")            # plenty of bars


@test("pastures (older bridge, no grass figures): into an existing pasture; none -> the AI makes one by a guess (0.105.35)")
def _():
    s = fort()
    s["society"] = {"vacant": [], "grazers_unpastured": 3, "pastures": 2}
    p, notes = plan(s, Memory())
    pa = by_rule(p, "pasture")
    assert pa and pa[0].action == {"type": "pasture", "count": 3} and not any("grazing" in n for n in notes)
    s["society"]["pastures"] = 0
    p, notes = plan(s, Memory())
    np_ = by_rule(p, "new_pasture")
    assert not by_rule(p, "pasture") and np_ and np_[0].action == {"type": "make_pasture", "tiles": 75} \
        and "a guess" in np_[0].reason, (np_, notes)                      # 3 x 20 x 1.25
    assert not any(n.startswith("[you]") for n in notes if "grazing" in n), notes


@test("mandates: socks in cloth, low boots in leather, high boots in steel at a forge")
def _():
    def mand(sub, **kw):
        s = geared(bars={"STEEL": 50})
        s["mandates"] = [{"kind": "Make", "item": "SHOES", "subtype": sub, "remaining": 3, "days_left": 40,
                          **kw}]
        return [x.action for x in by_rule(plan(s, Memory())[0], "mandate")]
    assert mand("ITEM_SHOES_SOCKS")[0]["recipe"] == "cloth_socks"
    assert mand("ITEM_SHOES_BOOTS_LOW")[0]["recipe"] == "leather_low_boots"
    a = mand("ITEM_SHOES_BOOTS")[0]
    assert a["recipe"] == "metal_high_boots" and a["material"] == "INORGANIC:STEEL", a
    a = mand("ITEM_SHOES_BOOTS", material="iron", material_token="INORGANIC:IRON")[0]
    assert a["material"] == "INORGANIC:IRON", a


# --- Growth and Maintain / Expand --------------------------------------------------

def grown(v, extreme=False, **kw):
    s = fort(**kw)
    s["settings"]["traits"] = {"growth": v * 2 if extreme else v} if v else {}
    s["settings"]["extreme"] = ["growth"] if extreme else []
    return s


@test("growth: 25 / 100 / 250 at -100, 0, +100; Extreme doubles it: no cap at +200, shrinking past -100")
def _():
    from planner import growth_mode
    got = [growth_mode(grown(v, e), PLANNER_CONFIG)
           for v, e in ((-100, False), (-50, False), (0, False), (50, False), (100, False))]
    assert got == [("target", 25), ("target", 63), ("target", 100), ("target", 175), ("target", 250)], got
    assert growth_mode(grown(100, True), PLANNER_CONFIG) == ("uncapped", None)
    assert growth_mode(grown(75, True), PLANNER_CONFIG) == ("target", 500)
    assert growth_mode(grown(30, True), PLANNER_CONFIG) == ("target", 190)        # (0.94) no longer "no cap"
    assert growth_mode(grown(-100, True), PLANNER_CONFIG) == ("shrink", 28)
    assert growth_mode(grown(-75, True), PLANNER_CONFIG) == ("shrink", 56)
    assert growth_mode(grown(-50, True), PLANNER_CONFIG) == ("target", 25)


@test("population cap: Expand sets it to the Growth target; Maintain to the size it had")
def _():
    s = grown(100)
    s["society"] = {"pop_cap": 200, "strict_pop_cap": 220}
    c = by_rule(plan(s, Memory())[0], "pop_cap")
    assert c and c[0].action == {"type": "set_population_cap", "cap": 250, "strict": 270}, c
    s["society"]["pop_cap"], s["society"]["strict_pop_cap"] = 250, 270
    assert not by_rule(plan(s, Memory())[0], "pop_cap")                       # already right
    s["settings"]["fort_goal"] = "maintain"
    m = Memory()
    note_cycle(s, m)
    assert m.maintain_pop == 194
    c = by_rule(plan(s, m)[0], "pop_cap")
    assert c and c[0].action == {"type": "set_population_cap", "cap": 194, "strict": 194}, c
    s["settings"]["set_pop_cap"] = False
    assert not by_rule(plan(s, m)[0], "pop_cap")
    del s["society"]["pop_cap"]                                               # cap not readable: leave it
    s["settings"]["set_pop_cap"] = True
    assert not by_rule(plan(s, m)[0], "pop_cap")


@test("join levels (0.104.108): asked every 2 days; a fortnight once every level was seen with nothing to join")
def _():
    s = fort()
    m = Memory()
    j = lambda: by_rule(plan(copy.deepcopy(s), m)[0], "join_levels")
    got = j()
    assert got and got[0].action == {"type": "join_levels"}, got
    record([(got[0], {"ok": True, "joined": {"z": 150}})], s, m)
    assert not j()
    s["date"]["tick"] += 2 * 1200
    got = j()
    assert got
    record([(got[0], {"ok": True, "wrapped": True})], s, m)        # nothing to join anywhere
    s["date"]["tick"] += 3 * 1200
    assert not j() and m.join_wait_days == 14


@test("strain (0.104.106): newcomers held at the fort's size while drink, meals or mood fail; let go with margin")
def _():
    s = grown(100, True)                                        # "no cap"
    s["society"] = {"pop_cap": 1000, "strict_pop_cap": 1000}
    pop = s["dwarves"]["total"]
    s["stocks"]["drink"] = pop * 1                              # 1 drink a dwarf: strained
    m = Memory()
    c = by_rule(plan(copy.deepcopy(s), m)[0], "pop_cap")
    assert c and c[0].action["cap"] <= pop + 1 and "strained" in c[0].reason and "drink" in c[0].reason, c
    record([(c[0], {"ok": True})], s, m)
    assert m.strain_hold and m.strain_cap == c[0].action["cap"] and m.fps_cap is None, (m.strain_hold, m.strain_cap)
    s["society"] = {"pop_cap": c[0].action["cap"], "strict_pop_cap": c[0].action["strict"]}
    s["stocks"]["drink"] = pop * 3                              # better, not yet past the "ok" level (4)
    assert not by_rule(plan(copy.deepcopy(s), m)[0], "pop_cap"), "held until it's well past"
    s["stocks"]["drink"] = pop * 6
    s["stocks"]["prepared_meals"] = pop * 6
    c = by_rule(plan(copy.deepcopy(s), m)[0], "pop_cap")
    assert c and c[0].action["cap"] == 1000, c                  # let go
    record([(c[0], {"ok": True})], s, m)
    assert not m.strain_hold and m.strain_cap is None and m.fps_cap is None


@test("strain (0.105.8): B's 7 dwarves, one miserable (14%): not strained; three unhappy of 7 are")
def _():
    from planner_building import fort_strain
    s = fort()
    s["dwarves"]["total"] = 7
    pop = 7
    s["stocks"]["drink"] = pop * 20
    s["stocks"]["prepared_meals"] = pop * 60
    s["dwarves"]["stress"] = {"content": 4, "fine": 2, "miserable": 1, "unhappy": 0, "very_unhappy": 0,
                              "happy": 0, "ecstatic": 0}
    import outcomes
    un = outcomes.measure(s).get("unhappy_pct")
    assert un and un > 12, un
    assert not fort_strain(s, PLANNER_CONFIG, True) and not fort_strain(s, PLANNER_CONFIG), fort_strain(s, PLANNER_CONFIG, True)
    s["dwarves"]["stress"].update(content=2, unhappy=2)
    assert any("unhappy" in x for x in fort_strain(s, PLANNER_CONFIG)), fort_strain(s, PLANNER_CONFIG)


@test("strain while slow (0.104.120): a stale slow-game cap above the fort's size doesn't stop the strain hold")
def _():
    s = grown(100, True)
    pop = s["dwarves"]["total"]
    s["society"] = {"pop_cap": pop + 100, "strict_pop_cap": pop + 110}
    s["fps_low"] = 18
    s["stocks"]["drink"] = pop * 1                              # strained
    m = Memory(fps_cap=pop + 100)                               # held when the fort was bigger (Teacheroar: 405 at 296)
    c = by_rule(plan(copy.deepcopy(s), m)[0], "pop_cap")
    assert c and c[0].action["cap"] <= pop + 1, c
    assert "strained" in c[0].reason and "runs slowly" in c[0].reason, c[0].reason
    record([(c[0], {"ok": True})], s, m)
    assert m.strain_hold and m.strain_cap == c[0].action["cap"] and m.fps_cap == pop + 100, (m.strain_cap, m.fps_cap)
    s["society"] = {"pop_cap": c[0].action["cap"], "strict_pop_cap": c[0].action["strict"]}
    s["stocks"]["drink"] = pop * 6
    s["stocks"]["prepared_meals"] = pop * 6
    c = by_rule(plan(copy.deepcopy(s), m)[0], "pop_cap")
    assert c and c[0].action["cap"] == pop + 100 and "strained" not in c[0].reason, c   # back to the slow-game hold
    record([(c[0], {"ok": True})], s, m)
    assert not m.strain_hold and m.strain_cap is None and m.fps_cap == pop + 100


@test("strain after losses (0.104.138): the cap follows the fort down, never back up to its size when the strain began")
def _():
    s = grown(100, True)
    pop = s["dwarves"]["total"]
    s["society"] = {"pop_cap": pop + 76, "strict_pop_cap": pop + 86}
    s["stocks"]["drink"] = pop * 1                              # strained
    m = Memory(strain_hold=True, strain_cap=pop + 76)           # Teacheroar: 293 remembered, 217 now
    c = by_rule(plan(copy.deepcopy(s), m)[0], "pop_cap")
    assert c and c[0].action["cap"] <= pop and "strained" in c[0].reason, c
    record([(c[0], {"ok": True})], s, m)
    assert m.strain_cap == c[0].action["cap"], m.strain_cap


@test("no cap: the population cap goes to 1000; shrinking: 7, and a dwarf is sent away now and then")
def _():
    s = grown(100, True)
    s["society"] = {"pop_cap": 200, "strict_pop_cap": 220}
    assert by_rule(plan(s, Memory())[0], "pop_cap")[0].action["cap"] == 1000
    s = grown(-100, True)
    s["society"] = {"pop_cap": 200, "strict_pop_cap": 220}
    p, _ = plan(s, Memory())
    assert by_rule(p, "pop_cap")[0].action == {"type": "set_population_cap", "cap": 7, "strict": 7}
    e = by_rule(p, "expel")
    assert e and e[0].action == {"type": "expel_dwarf"}, e
    m = Memory()
    record([(e[0], {"ok": True, "name": "Urist"})], s, m)
    assert not by_rule(plan(s, m)[0], "expel")                          # waits 28 days
    m.last_expel_tick -= 28 * 1200
    assert by_rule(plan(s, m)[0], "expel")
    s["dwarves"]["total"] = 7
    assert not by_rule(plan(s, Memory())[0], "expel")                   # never below 7
    s = grown(-100, True)
    s["settings"]["fort_goal"] = "maintain"
    assert not by_rule(plan(s, Memory())[0], "expel")                   # Maintain wins


@test("bedrooms: Expand builds ahead toward the target; Maintain only for who's there")
def _():
    s = grown(100)
    s["dwarves"]["total"] = 100
    s["buildings"]["other"]["Bed"] = 105
    b = [x for x in builds(plan(s, Memory())[0]) if x.action["kind"] == "bedrooms"]
    assert b and b[0].action["rooms"] == 15, [x.action for x in b]          # up to 120 beds (100 + 20 ahead)
    s["settings"]["fort_goal"] = "maintain"
    assert not [x for x in builds(plan(s, Memory())[0]) if x.action["kind"] == "bedrooms"]


@test("Maintain: no new memorials, temples or libraries; essentials still built")
def _():
    s = settled_fort(piety=150)
    s["locations"] = {"count": {"HOSPITAL": 1, "INN_TAVERN": 1}, "total": 2}
    m = Memory(culture={"beasts_slain": ["Urist the Beast"], "memorials_built": []})
    assert builds(plan(s, m)[0])[0].action["kind"] == "temple"      # (0.98) a devout fort: its temple first
    s["settings"]["fort_goal"] = "maintain"
    assert not builds(plan(s, m)[0])
    s["locations"] = {"count": {}, "total": 0}
    assert builds(plan(s, m)[0])[0].action["kind"] == "hospital"


# --- farm plots (placement, step 1) ------------------------------------------------

def farmless(**traits):
    s = fort()
    s["farms"] = {"plots": 0, "tiles": 0, "built": 0}
    s["buildings"]["other"].pop("FarmPlot", None)
    s["settings"]["traits"] = traits
    return s


@test("farms: no plots -> the AI lays them out itself, sized for the fort; may dig a farm level")
def _():
    p = by_rule(plan(farmless(), Memory())[0], "farms")
    assert len(p) == 1, p
    a = p[0].action
    assert a["type"] == "farm_plots" and a["tiles"] == 194 and a["dig"] is True, a   # 194 dwarves, 1 tile each
    assert set(a["style"]) >= {"hall", "smooth", "statues", "entry_door"}
    assert "194 tiles" in p[0].reason


@test("farms: sized by Agriculture (Big farms: x2) and by the Growth target; Hunt and gather: none")
def _():
    big = by_rule(plan(farmless(agriculture=100), Memory())[0], "farms")[0].action
    assert big["tiles"] == 388, big
    assert not by_rule(plan(farmless(agriculture=-100), Memory())[0], "farms")
    s = farmless(growth=100)                           # heading for 250: plan 20 ahead, like beds
    s["dwarves"]["total"] = 30
    assert by_rule(plan(s, Memory())[0], "farms")[0].action["tiles"] == 50
    s["settings"]["fort_goal"] = "maintain"            # Maintain: for the dwarves it has
    assert by_rule(plan(s, Memory())[0], "farms")[0].action["tiles"] == 30
    s["dwarves"]["total"] = 2                          # too few to farm yet (0.100.1: 3, was 7)
    assert not by_rule(plan(s, Memory())[0], "farms")
    s["dwarves"]["total"] = 6                          # an embark that lost a dwarf still farms
    assert by_rule(plan(s, Memory())[0], "farms")
    s["dwarves"]["total"] = 7
    assert by_rule(plan(s, Memory())[0], "farms")[0].action["tiles"] == 9   # the smallest field


@test("farms: enough tiles (3/4 of the target), or a farm level being dug, -> nothing more")
def _():
    s = farmless()
    s["farms"]["tiles"] = 146                          # 75% of 194
    assert not by_rule(plan(s, Memory())[0], "farms")
    s["farms"]["tiles"] = 100
    s["projects"]["open"] = [{"id": 4, "kind": "farms", "phase": "dig",
                              "summary": {"farm_plots": 4, "farm_tiles": 60}}]
    assert not by_rule(plan(s, Memory())[0], "farms")
    s["projects"]["open"][0]["summary"]["farm_tiles"] = 15
    a = by_rule(plan(s, Memory())[0], "farms")[0].action
    assert a["tiles"] == 79 and a["dig"] is False, a  # one farm level at a time


@test("farms: a farm level gets one slot more than other levels; none past that (Mining -100 still digs it, 0.96)")
def _():
    s = farmless()
    s["projects"]["open"] = [{"id": 1, "kind": "bedrooms", "phase": "dig"},
                             {"id": 2, "kind": "dining", "phase": "dig"}]
    a = by_rule(plan(s, Memory())[0], "farms")[0].action
    assert a["dig"] is True, a
    s["projects"]["open"].append({"id": 3, "kind": "temple", "phase": "dig"})
    p = by_rule(plan(s, Memory())[0], "farms")[0]
    assert p.action["dig"] is False and "style" not in p.action, p.action
    assert p.action["outside"] is True and p.priority == 2, p          # no farm at all: the surface will do
    a = by_rule(plan(farmless(mining=-100), Memory())[0], "farms")[0].action
    assert a["dig"] is True, a


@test("farms: nowhere to put them -> a note says why and what the AI does (0.105.35: no Needs you); waits 3 days")
def _():
    s = farmless()
    s["stocks"]["drink"] = 10                         # 194 dwarves: going thirsty
    m = Memory()
    p = by_rule(plan(s, m)[0], "farms")[0]
    record([(p, {"ok": False, "error": "no free soil or muddy floor near the dwarves; no farm level "
                 "either: no safe level found"})], s, m)
    assert "no free soil" in m.farm_failure
    allowed, _ = select(plan(s, m)[0], s, m)
    assert not by_rule(allowed, "farms"), "asked again straight away"
    notes = plan(s, m)[1]
    assert any(n.startswith("farm plots: no free soil") and "running low" in n and "irrigation" in n
               for n in notes), notes
    assert not any(n.startswith("[you] farm") for n in notes), notes
    fed = farmless()                                   # the real fort is well fed: a quiet note only
    notes = plan(fed, m)[1]
    assert not any(n.startswith("[you] farm") for n in notes), notes
    assert any(n.startswith("farm plots: no free soil") and "can wait" in n for n in notes), notes
    record([(p, {"ok": True, "tiles": 20})], s, m)
    assert m.farm_failure == ""
    m2 = Memory()
    full = farmless()
    full["projects"]["open"] = [{"id": i, "kind": k, "phase": "dig"} for i, k in ((1, "bedrooms"), (2, "dining"),
                                                                                   (3, "temple"))]
    q = by_rule(plan(full, m2)[0], "farms")[0]
    record([(q, {"ok": False, "error": "no free soil"})], s, m2)
    assert m2.farm_failure == "", "without a level to dig it's not the player's problem yet"


@test("farms: autofarm is switched on once there are plots (it picks the crops)")
def _():
    s = fort()
    s["tools"]["autofarm"] = False
    t = [x for x in by_rule(plan(s, Memory())[0], "tools") if x.action["name"] == "autofarm"]
    assert t, rules(plan(s, Memory())[0])
    s["settings"]["traits"] = {"agriculture": -100}
    assert not [x for x in by_rule(plan(s, Memory())[0], "tools") if x.action["name"] == "autofarm"]
    s = farmless()
    s["tools"]["autofarm"] = False
    assert not [x for x in by_rule(plan(s, Memory())[0], "tools") if x.action["name"] == "autofarm"]


@test("farms: an older bridge without the farms report -> no farm rule, and it says so")
def _():
    s = farmless()
    del s["farms"]
    p, notes = plan(s, Memory())
    assert not by_rule(p, "farms") and any("farms" in n and "failed" in n for n in notes), notes


# --- pastures sized by the herd (placement, step 3) ---------------------------------

def herd(waiting=3, need=60, smallest=6, pastures=0, spare=0, **traits):
    s = fort()
    s["society"] = {"vacant": [], "grazers_unpastured": waiting, "pastures": pastures,
                    "grazer_tiles": need, "grazer_tiles_smallest": smallest, "pasture_spare": spare}
    s["settings"]["traits"] = traits
    return s


@test("pastures: none -> the AI makes one on grass, sized for the herd (+25%); no Needs you")
def _():
    p, notes = plan(herd(), Memory())
    np_ = by_rule(p, "new_pasture")
    assert np_ and np_[0].action == {"type": "make_pasture", "tiles": 75}, np_      # 60 x 1.25
    assert not by_rule(p, "pasture") and not any("grazing" in n for n in notes if n.startswith("[you]")), notes
    assert "there is no pasture" in np_[0].reason
    big = by_rule(plan(herd(husbandry=100), Memory())[0], "new_pasture")[0].action
    assert big["tiles"] == 150, big                       # Large herds: room to grow
    tiny = by_rule(plan(herd(need=4, smallest=4), Memory())[0], "new_pasture")[0].action
    assert tiny["tiles"] == 9, tiny                       # never under 3x3


@test("pastures: an existing pasture with room is used first; full ones -> a new pasture")
def _():
    p = plan(herd(pastures=2, spare=40), Memory())[0]
    assert by_rule(p, "pasture") and not by_rule(p, "new_pasture"), rules(p)
    p = plan(herd(pastures=2, spare=3), Memory())[0]     # less room than the smallest animal needs
    np_ = by_rule(p, "new_pasture")
    assert np_ and not by_rule(p, "pasture") and "no pasture has room" in np_[0].reason, rules(p)


@test("pastures: nowhere to make one -> a note with the reason, tried again (0.105.35); waits 3 days; switch off -> yours")
def _():
    s, m = herd(), Memory()
    p = by_rule(plan(s, m)[0], "new_pasture")[0]
    record([(p, {"ok": False, "error": "no living grass near the fort's surface entrances"})], s, m)
    props, notes = plan(s, m)
    assert any(n.startswith("3 grazing animals have no pasture") and "no living grass" in n and "tries again" in n
               for n in notes), notes
    assert not any(n.startswith("[you]") and "grazing" in n for n in notes), notes
    allowed, _ = select(props, s, m)
    assert not by_rule(allowed, "new_pasture"), "asked again straight away"
    record([(p, {"ok": True, "tiles": 75})], s, m)
    assert m.pasture_failure == ""
    s["settings"]["pasture_animals"] = False
    props, notes = plan(s, Memory())
    assert not by_rule(props, "new_pasture") and any("switch is off" in n for n in notes), notes


# --- found in the game (milestone 0) -----------------------------------------------

@test("gates (game): an entrance with planned walls or doors being built is left alone")
def _():
    s = entrances({"door_spots": 2, "width": 2, "closing": True},
                  {"door_spots": 0, "width": 6, "x": 40, "y": 50, "closing": True})
    p, notes = plan(s, Memory())
    assert not by_rule(p, "gate_doors") and not by_rule(p, "fortify"), rules(p)
    assert not any("refused" in n or "can't be closed" in n for n in notes), notes


@test("gates (game): a refusal is tried again after 2 weeks (things change); one from before dates, at once")
def _():
    s = entrances({"door_spots": 2, "width": 2})
    m = Memory()
    d = by_rule(plan(s, m)[0], "gate_doors")[0]
    record([(d, {"ok": False, "error": "no door could be placed there (build_unsuitable at x10 y10 (SAPLING))"})], s, m)
    assert not by_rule(plan(s, m)[0], "gate_doors")
    later = copy.deepcopy(s)
    later["date"]["tick"] += 14 * 1200
    later["entrances"]["scanned_tick"] += 14 * 1200
    assert by_rule(plan(later, m)[0], "gate_doors"), "tried again after 2 weeks"
    record([(d, {"ok": True, "doors": 2})], later, m)
    assert not m.gate_failures and not m.gate_failure_ticks, "worked: forgotten"
    old = Memory(gate_failures={"10,10,173": "build_unsuitable"})          # saved before refusals were dated
    assert by_rule(plan(s, old)[0], "gate_doors")


@test("gates (game): the refusals' note cuts long reasons at a word, and says the AI will try again")
def _():
    s = entrances({"door_spots": 2, "width": 2}, {"door_spots": 2, "width": 3, "x": 40, "y": 50})
    m = Memory()
    p = plan(s, m)[0]
    long = "no door could be placed there (" + "; ".join(
        f"build_unsuitable at x{i} y5 (FLOOR, STONE, Construction (planned))" for i in range(6)) + ")"
    now = s["date"]["year"] * 403200 + s["date"]["tick"]
    m.gate_failures = {"10,10,173": long, "40,50,173": long}
    m.gate_failure_ticks = {"10,10,173": now, "40,50,173": now}
    notes = plan(s, m)[1]
    you = [n for n in notes if "refused to build" in n][0]
    assert " ..." in you and "tries again every 2 weeks" in you, you
    assert "(FLOOR, STONE, a b;" not in you


@test("gates (game): a refusal over a stockpile (saved before the AI moved stockpiles) is retried at once")
def _():
    s = entrances({"door_spots": 0, "width": 2, "x": 101, "y": 91})
    now = s["date"]["year"] * 403200 + s["date"]["tick"]
    m = Memory(gate_failures={"101,91,173": "something is already in the opening at x101 y91 (FLOOR, "
                              "CONSTRUCTION, Stockpile) (move the stockpile and the AI will wall the opening)"},
               gate_failure_ticks={"101,91,173": now})
    assert by_rule(plan(s, m)[0], "fortify"), "the AI moves the stockpile itself now"


@test("farms: nowhere to farm isn't proposed (or asked about) again for 4 weeks, plots or a level")
def _():
    s = fort()
    s["date"]["tick"] = 0
    s["farms"] = {"plots": 2, "tiles": 8}
    now = s["date"]["year"] * 403200
    m = Memory(farm_failure="no soil on any level the staircases reach", farm_failure_tick=now)
    assert not [x for x in plan(s, m)[0] if x.rule == "farms"]
    s["date"]["tick"] = 29 * 1200
    f = [x for x in plan(s, m)[0] if x.rule == "farms"]
    assert f and f[0].action["dig"] is True
    # a plots-only refusal waits too (no Needs you: a level might still be dug later)
    m2 = Memory()
    p = [x for x in plan(s, m2)[0] if x.rule == "farms"][0]
    p.action["dig"] = False
    record([(p, {"ok": False, "error": "no free soil or muddy floor near the dwarves"})], s, m2)
    assert m2.farm_failure == "" and m2.farm_failure_tick is not None
    assert not [x for x in plan(s, m2)[0] if x.rule == "farms"]


def labor(**kw):
    jobs = {j: {"doing": 0, "candidates": 4, "mode": "OnlySelectedDoesThis"}
            for j in ("mining", "woodcutting", "gathering", "fishing", "farming")}
    lb = {"miners": 1, "picks": 3, "soldier_picks": 0, "dig": 120, "want": 3, "need": 2, "candidates": 4,
          "shrubs": 0, "gather_marked": 0, "fish_water": 0, "jobs": jobs}
    lb.update(kw)
    return lb


@test("miners: digging waits and picks lie unused: more dwarves mine; nobody able to dig is Needs you")
def _():
    s = fort()
    s["labor"] = labor()
    p = [x for x in by_rule(plan(s, Memory())[0], "labor") if x.action.get("job") == "mining"]
    assert p and p[0].action == {"type": "assign_labor", "job": "mining", "count": 2} \
        and "120 tile(s) to dig" in p[0].reason, p
    allowed, held = select(plan(s, Memory())[0], s, Memory())
    assert [x for x in allowed if x.rule == "labor"], held               # (outside the per-cycle limit)
    s["labor"] = labor(dig=0)
    assert not [x for x in by_rule(plan(s, Memory())[0], "labor") if x.action.get("job") == "mining"]
    s["labor"] = labor(miners=0, picks=0, soldier_picks=1, dig=40, want=0, need=0)
    props, notes = plan(s, Memory())
    assert any("nobody can dig" in n and "soldiers' hands" in n for n in notes), notes
    s["labor"]["jobs"]["mining"]["mode"] = "EverybodyDoesThis"
    s["labor"].update(need=2, picks=3)
    assert not [x for x in by_rule(plan(s, Memory())[0], "labor") if x.action.get("job") == "mining"]
    s["labor"] = "oops"                                                  # a broken section never breaks planning
    plan(s, Memory())


@test("labour: 0.38.0's out-of-order work detail is put in order first")
def _():
    s = fort()
    s["labor"] = labor(dig=0)
    s["labor"]["jobs"]["mining"]["unsorted"] = True
    p = by_rule(plan(s, Memory())[0], "labor")
    assert p and p[0].action == {"type": "assign_labor", "job": "mining", "count": 0} and p[0].priority == 1, p


@test("food before farms: shrubs gathered and gatherers, fishers where there's water, farmers once there are plots")
def _():
    s = fort()
    s["buildings"].setdefault("other", {})["FarmPlot"] = 0
    s["farms"] = {"plots": 0, "tiles": 0, "built": 0}
    s["dwarves"]["total"] = 7
    s["stocks"].update(prepared_meals=20, meat=10, fish=0, plants=10, plant_growths=10, cheese=0, eggs=0, raw_fish=0)
    s["labor"] = labor(dig=0, shrubs=400, fish_water=12)
    props = plan(s, Memory())[0]
    g = by_rule(props, "gather")
    assert g and g[0].action == {"type": "gather_plants", "count": 28}, g        # 4 a dwarf, not 100
    jobs = {x.action["job"]: x.action["count"] for x in by_rule(props, "labor")}
    assert jobs.get("gathering") == 2 and jobs.get("fishing") == 1 and "farming" not in jobs, jobs
    assert jobs.get("woodcutting") is None                               # no axe
    s["labor"]["jobs"]["woodcutting"]["tools"] = 1
    s["labor"]["jobs"]["gathering"]["mode"] = "EverybodyDoesThis"        # yours: left alone
    jobs = {x.action["job"]: x.action["count"] for x in by_rule(plan(s, Memory())[0], "labor")}
    assert jobs.get("woodcutting") == 1 and "gathering" not in jobs, jobs
    s["farms"] = {"plots": 2, "tiles": 20, "built": 2}
    s["stocks"].update(prepared_meals=150)
    props = plan(s, Memory())[0]
    assert not by_rule(props, "gather")                                  # a farm and food: no more gathering marks
    jobs = {x.action["job"]: x.action["count"] for x in by_rule(props, "labor")}
    assert jobs.get("farming") == 2, jobs


def young(n=7, **stocks):
    s = fort()
    s["dwarves"]["total"] = n
    s["buildings"].setdefault("other", {})["FarmPlot"] = 0
    s["buildings"]["other"]["Bed"] = 0
    s["farms"] = {"plots": 0, "tiles": 0, "built": 0}
    s["projects"]["open"] = []
    s["stocks"].update({"prepared_meals": 0, "meat": 0, "fish": 0, "plants": 0, "plant_growths": 0,
                        "cheese": 0, "eggs": 0, "raw_fish": 0, **stocks})
    return s


@test("food a dwarf counts meals (0.39.0 read a key the bridge never sends), fruit, cheese, eggs and fish")
def _():
    from planner import food_per_dwarf
    s = young(prepared_meals=35, plant_growths=21, cheese=7, eggs=7, raw_fish=7, meat=7, plants=7, fish=14)
    assert food_per_dwarf(s) == 15.0, food_per_dwarf(s)
    s["labor"] = labor(dig=0, shrubs=400)
    assert not by_rule(plan(s, Memory())[0], "gather")                   # fed: no gathering


@test("a young fort: food first: no bedrooms while food is short and there's no farm; small plain rooms after")
def _():
    s = young(prepared_meals=30)                                                  # ~4 a dwarf
    props, notes = plan(s, Memory())
    assert not [p for p in by_rule(props, "build") if p.action.get("kind") == "bedrooms"], by_rule(props, "build")
    assert any("food first" in n for n in notes), notes
    s = young(prepared_meals=200)
    b = [p for p in by_rule(plan(s, Memory())[0], "build") if p.action.get("kind") == "bedrooms"]
    assert b and b[0].action["room_size"] == 2 and b[0].action["rooms"] <= 12, b
    assert b[0].action["style"]["smooth"] == 0 and b[0].action["style"]["statues"] == 0, b[0].action["style"]


@test("a young fort by water: a fishery (and butcher's) comes before homes")
def _():
    s = young(prepared_meals=200)
    s["labor"] = labor(dig=0, fish_water=20)
    s["buildings"]["workshops"] = {w: 1 for w in ("Still", "Kitchen", "Carpenters", "Masons", "Craftsdwarfs")}
    b = by_rule(plan(s, Memory())[0], "build")
    assert b and b[0].action["shops"] == ["Fishery", "Butchers"], b
    s["buildings"]["workshops"]["Fishery"] = 1
    b = by_rule(plan(s, Memory())[0], "build")
    assert b and b[0].action["kind"] == "bedrooms", b


def well_fort(**stocks):
    s = fort()
    s["buildings"].setdefault("other", {})["Well"] = 0
    s["projects"]["open"] = [{"id": 9, "kind": "well", "phase": "furnish",
                              "furnish": {"placed": 1, "done": 0, "waiting": {"Well": 1}, "days": 4}}]
    s["stocks"].update({"blocks": 0, "mechanisms": 0, "chains": 0, "cloth": 0, "thread": 0, "wood": 10, **stocks})
    s["supplies"]["buckets"] = 0
    s["orders"] = []
    return s


@test("a well's parts: block, bucket, mechanism and rope ordered from the real stocks; workshops first")
def _():
    s = well_fort(cloth=3)
    s["buildings"]["workshops"] = {"Masons": 1, "Carpenters": 1, "Mechanics": 1, "Clothiers": 1}
    p = by_rule(plan(s, Memory())[0], "well_parts")
    assert sorted(x.action["recipe"] for x in p) == ["cloth_rope", "mechanisms", "stone_blocks", "wooden_bucket"], p
    s = well_fort(blocks=5, mechanisms=1, chains=1)
    s["supplies"]["buckets"] = 2
    assert not by_rule(plan(s, Memory())[0], "well_parts")               # it has everything
    s = well_fort(cloth=3)
    s["buildings"]["workshops"] = {"Masons": 1, "Carpenters": 1, "Still": 1, "Kitchen": 1}
    p = by_rule(plan(s, Memory())[0], "well_parts")
    shop = [x for x in p if x.action["type"] == "start_project"]
    assert shop and shop[0].action["shops"] == ["Mechanics", "Clothiers"], p
    s = well_fort()                                                       # no cloth, no thread: say so
    s["buildings"]["workshops"] = {"Masons": 1, "Carpenters": 1, "Mechanics": 1}
    _, notes = plan(s, Memory())
    assert any("rope or chain" in n for n in notes), notes


@test("0.105.18 well parts: no plant thread -> a chain at the forge (non-gear metal first), else cloth of the thread there is")
def _():
    s = well_fort(blocks=5, mechanisms=1, thread=13)
    s["supplies"].update(buckets=11, fuel=33, cloth_kinds={"plant": 0, "silk": 0, "yarn": 0},
                         thread_kinds={"plant": 0, "silk": 0, "yarn": 3})
    s["buildings"]["workshops"] = {"Masons": 1, "Carpenters": 1, "Mechanics": 1, "Clothiers": 1, "Loom": 1}
    s.setdefault("military", {}).setdefault("gear", {}).update(
        forges=2, all_bars={"COPPER": 47, "IRON": 6, "PIG_IRON": 1, "SILVER": 12, "STEEL": 21})
    p = by_rule(plan(copy.deepcopy(s), Memory())[0], "well_parts")       # A, 3 Nov 08:41
    assert [x.action for x in p] == [{"type": "work_order", "recipe": "metal_chain", "amount": 1,
                                      "material": "INORGANIC:SILVER"}], p
    s["military"]["gear"]["all_bars"] = {"COPPER": 47, "IRON": 6, "STEEL": 21}
    p = by_rule(plan(copy.deepcopy(s), Memory())[0], "well_parts")
    assert p[0].action["material"] == "INORGANIC:COPPER", p
    s["military"]["gear"]["forges"] = 0                                   # no forge: weave the yarn there is
    p = by_rule(plan(copy.deepcopy(s), Memory())[0], "well_parts")
    assert [x.action["recipe"] for x in p] == ["weave_yarn_cloth"], p
    s["supplies"]["cloth_kinds"] = {"plant": 0, "silk": 0, "yarn": 2}     # yarn cloth: a yarn rope
    p = by_rule(plan(copy.deepcopy(s), Memory())[0], "well_parts")
    assert [x.action["recipe"] for x in p] == ["yarn_rope"], p
    s["military"]["gear"]["forges"] = 1                                   # B: plant cloth, but a forge: the chain first
    s["supplies"]["cloth_kinds"] = {"plant": 1, "silk": 0, "yarn": 0}
    p = by_rule(plan(copy.deepcopy(s), Memory())[0], "well_parts")
    assert [x.action["recipe"] for x in p] == ["metal_chain"], p
    s["orders"] = [{"recipe": "cloth_rope", "amount_left": 1}]            # B's stuck rope doesn't hold the chain
    p = by_rule(plan(copy.deepcopy(s), Memory())[0], "well_parts")
    assert [x.action["recipe"] for x in p] == ["metal_chain"], p
    s["orders"] = [{"recipe": "metal_chain", "amount_left": 1}]           # a chain on order: nothing more
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "well_parts")


@test("stuck fallback (0.104.138, 12l): a stuck stone order is made in wood (or metal) instead, else held")
def _():
    from planner import Proposal
    s = fort()
    now = abs_tick(s)
    s["stocks"]["wood"] = 900
    m = Memory(stuck_cancelled={"stone_coffin": {"tick": now - 3 * TICKS_PER_DAY, "n": 1}})
    p = Proposal("furniture", {"type": "work_order", "recipe": "stone_coffin", "amount": 10,
                               "material": "INORGANIC:GRANITE"}, "coffins", 4)
    allowed, held = select([p], s, m)
    assert allowed and allowed[0].action == {"type": "work_order", "recipe": "wooden_coffin", "amount": 10}, (allowed, held)
    assert "wooden_coffin instead" in allowed[0].reason
    s["stocks"]["wood"] = 0                                         # no wood, no spare metal: held as before
    m.last_fired.clear()
    allowed, held = select([p], s, m)
    assert not allowed and any("got stuck" in h for h in held), held
    m.stuck_cancelled["wooden_coffin"] = {"tick": now, "n": 1}       # the fallback stuck too: not again
    s["stocks"]["wood"] = 900
    m.last_fired.clear()
    assert not select([p], s, m)[0]


@test("stuck fallback (0.104.140): a stuck plant-cloth weave turns to silk thread at hand, never to none")
def _():
    from planner import Proposal
    s = fort()
    now = abs_tick(s)
    s["buildings"]["workshops"]["Loom"] = 1
    s["supplies"] = dict(s.get("supplies") or {}, thread_kinds={"plant": 0, "silk": 12, "yarn": 0})
    m = Memory(stuck_cancelled={"weave_plant_cloth": {"tick": now - TICKS_PER_DAY, "n": 1}})
    p = Proposal("cloth", {"type": "work_order", "recipe": "weave_plant_cloth", "amount": 5}, "cloth", 4)
    allowed, held = select([p], s, m)
    assert allowed and allowed[0].action["recipe"] == "weave_silk_cloth", (allowed, held)
    s["supplies"]["thread_kinds"]["silk"] = 0
    m.last_fired.clear()
    assert not select([p], s, m)[0]


@test("one back-off: the same refused action waits 1, 2, 4 ... days (at most 12 weeks); a success clears it")
def _():
    from planner import Proposal, REFUSAL_MAX_DAYS, abs_tick
    s = fort()
    m = Memory()
    p = Proposal("new_pasture", {"type": "make_pasture", "tiles": 127}, "x", 4)
    waits = []
    for i in range(7):
        record([(p, {"ok": False, "error": "no grass"})], s, m)
        waits.append((m.refusals[next(iter(m.refusals))]["until"] - abs_tick(s)) // 1200)
    assert waits == [1, 2, 4, 8, 16, 32, 64] and REFUSAL_MAX_DAYS == 84, waits
    m.last_fired.clear()                                                  # (the rule's own wait aside)
    allowed, held = select([p], s, m)
    assert not allowed and any("refused it 7 time(s)" in h for h in held), held
    other = Proposal("new_pasture", {"type": "make_pasture", "tiles": 300}, "x", 4)   # another size: same action
    assert not select([other], s, m)[0]
    record([(p, {"ok": True})], s, m)
    m.last_fired.clear()                                                  # (its own cooldown aside)
    # (0.104.138) a success frees it at once but keeps half the count: the next refusal waits 8 days, not 1
    assert [v["n"] for v in m.refusals.values()] == [3] and select([p], s, m)[0], m.refusals
    before = copy.deepcopy(m.refusals)
    # the in-game halt, an unknown result, or an attack response: no back-off
    record([(p, {"ok": False, "halted": True})], s, m)
    record([(p, {"ok": None})], s, m)
    record([(Proposal("gate", {"type": "pull_gate", "lever_id": 1}, "x", 0), {"ok": False})], s, m)
    assert m.refusals == before, m.refusals
    record([(p, {"ok": False, "error": "no grass"})], s, m)
    assert (m.refusals[next(iter(m.refusals))]["until"] - abs_tick(s)) // 1200 == 8
    q = Proposal("pair_chairs", {"type": "pair_chairs", "zones": [168]}, "x", 3)
    record([(q, {"ok": False, "rejected": True, "nothing_to_do": True, "error": "every chair has one beside it"})], s, m)
    from planner import refusal_key
    assert (m.refusals[refusal_key(q)]["until"] - abs_tick(s)) // 1200 == 336


@test("a mood stuck gathering: blocks and cloth are ordered; what no recipe makes is named in Needs you")
def _():
    s = fort()
    s["moods"] = {"list": [{"unit_id": 5, "name": "Urist", "mood": "Fey", "craft": True, "skill": "MASONRY",
                            "workshop": "Masons", "items_have": 2, "items_needed": 5, "missing": [
                                {"item": "BLOCKS", "quantity": 2, "flags": []},
                                {"item": "BAR", "material": "IRON", "quantity": 1, "flags": ["metal"]},
                                {"item": "CORPSEPIECE", "quantity": 1, "flags": ["bone"]}]}]}
    s["orders"] = []
    m = Memory()
    m.moods_seen = {"5": abs_tick(s) - 4 * 1200}
    props, notes = plan(s, m)
    o = [p.action for p in by_rule(props, "mood")]
    assert {"type": "work_order", "recipe": "stone_blocks", "amount": 2} in o, o
    # (0.105.24) a bone: one spare tame animal to the butcher; iron with no iron ore: named
    assert {"type": "slaughter_one", "oldest": True, "mood_unit": 5} in o, o     # (0.105.30) the oldest, one a mood
    assert any("1 bar of iron" in n for n in notes), notes
    # (0.103.8) on day 4 the dwarf may still be fetching it: a note; Needs you from day 7
    assert not any(n.startswith(planner.NEEDS_YOU) and "still lacks" in n for n in notes), notes
    m.moods_seen = {"5": abs_tick(s) - 8 * 1200}
    notes = plan(s, m)[1]
    # (0.105.35) a note: the forbidden freed, the rest bought from the caravans
    props, notes = plan(s, m)
    assert not any(n.startswith(planner.NEEDS_YOU) and "Urist" in n for n in notes), notes
    assert any("still lacks" in n and "1 bar of iron" in n and "caravan" in n for n in notes), notes
    assert {"type": "mood_free_items", "unit_id": 5, "max": 10} in [p.action for p in by_rule(props, "mood")]


def _counted_mood(missing, **kw):
    m = {"unit_id": 5, "name": "Urist", "mood": "Fey", "craft": True, "skill": "STONECRAFT",
         "workshop": "Craftsdwarfs", "items_have": 0, "items_needed": len(missing), "missing": missing}
    m.update(kw)
    return m


def _av(**kw):
    a = {"free": 0, "reach": 0, "forbidden": 0, "forbidden_reach": 0, "dump": 0, "job": 0, "other": 0}
    a.update(kw)
    return a


@test("mood (0.105.24): with the bridge's count: on hand left alone; forbidden freed; cloth by kind, leather, bars, glass made")
def _():
    s = fort()
    s["supplies"].update(thread_kinds={"plant": 0, "silk": 0, "yarn": 4}, hides=2, fuel=5, sand_bags=3)
    s["industry"] = {"ore_stock_by": {"MALACHITE": {"n": 6, "metals": ["COPPER"]}, "HEMATITE": {"n": 9, "metals": ["IRON"]}}}
    s["moods"] = {"list": [_counted_mood([
        {"index": 0, "item": "CLOTH", "quantity": 1, "flags": ["yarn"], "avail": _av()},
        {"index": 1, "item": "WOOD", "quantity": 1, "flags": [], "avail": _av(free=40, reach=1, enough=True)},
        {"index": 2, "item": "SKIN_TANNED", "quantity": 1, "flags": [], "avail": _av()},
        {"index": 3, "item": "BAR", "material": "copper", "quantity": 2, "flags": ["metal"], "avail": _av()},
        {"index": 4, "item": "ROUGH", "material": "green glass", "quantity": 1, "flags": [], "avail": _av()},
        {"index": 5, "item": "NONE", "quantity": 1, "flags": ["bone"], "avail": _av(forbidden=3, forbidden_reach=2)}])]}
    s["orders"] = []
    m = Memory()
    m.moods_seen = {"5": abs_tick(s)}                    # day 0: a counting bridge acts at once
    props, notes = plan(s, m)
    o = [p.action for p in by_rule(props, "mood")]
    assert {"type": "work_order", "recipe": "weave_yarn_cloth", "amount": 1} in o, o
    assert {"type": "work_order", "recipe": "tan_hide", "amount": 1} in o, o
    assert {"type": "work_order", "recipe": "smelt_ore", "amount": 2, "material": "INORGANIC:MALACHITE"} in o, o
    assert {"type": "work_order", "recipe": "raw_green_glass", "amount": 1} in o, o
    assert {"type": "mood_free_items", "unit_id": 5, "max": 10} in o, o
    assert not any(a.get("recipe") in ("wooden_bed",) or a.get("type") == "slaughter_one" for a in o), o   # bone freed, log on hand
    first = [p for p in by_rule(props, "mood") if p.action.get("recipe") == "weave_yarn_cloth"][0]
    assert "the one it is fetching now" in first.reason and first.priority == 1, first
    assert not any(n.startswith(planner.NEEDS_YOU) and "Urist" in n for n in notes), notes
    # the rule may act several times a cycle, and again a quarter day on
    allowed, _held = select(props, s, m)
    assert len([p for p in allowed if p.rule == "mood"]) >= 4, [p.action for p in allowed]
    assert PLANNER_CONFIG["mood_cooldown_ticks"] == 300
    import overseer
    assert "strange mood" in overseer.short({"type": "mood_free_items", "unit_id": 5})


@test("mood (0.105.24): what the fort can't supply goes to Needs you at once, named, and to the caravans; held gems let go")
def _():
    s = fort()
    s["supplies"].update(thread_kinds={"plant": 0, "silk": 0, "yarn": 0}, shearable=0)
    s["trade"] = {"rough_gem": {"n": 0}}
    s["moods"] = {"list": [_counted_mood([
        {"index": 0, "item": "CLOTH", "quantity": 1, "flags": ["silk"], "avail": _av()},
        {"index": 1, "item": "ROUGH", "quantity": 1, "flags": [], "avail": _av(job=2)},
        {"index": 2, "item": "NONE", "quantity": 1, "flags": ["shell"], "avail": _av()},
        {"index": 3, "item": "WOOD", "quantity": 1, "flags": [], "avail": _av(free=2, reach=0)}])]}
    s["orders"] = [{"id": 77, "recipe": "cut_gems", "by_ai": True, "amount_left": 4, "amount_total": 6}]
    m = Memory()
    m.moods_seen = {"5": abs_tick(s) - 1200}
    props, notes = plan(s, m)
    o = [p.action for p in by_rule(props, "mood")]
    assert {"type": "cancel_work_order", "order_id": 77} in o, o
    # (0.105.35) a note: on the caravans' list, the AI buys it (no Needs you)
    assert not any(n.startswith(planner.NEEDS_YOU) and "can't supply" in n for n in notes), notes
    need = [n for n in notes if "can't supply" in n]
    assert need and "1 cloth (silk): no silk thread to weave" in need[0] and "1 shell" in need[0], need
    assert "rough gem" not in need[0], need                # another job holds it: let go, not asked for
    assert any(n.startswith(planner.NEEDS_YOU) and "where the dwarf can't walk" in n and "1 log" in n for n in notes), notes
    from planner_industry import trade_wants
    w = trade_wants(s, PLANNER_CONFIG, 50)
    assert w[0] == {"key": "CLOTH", "count": 1}, w[:3]
    assert sum(1 for x in w if x["key"] == "CLOTH") == 1, w     # the fort's own cloth want isn't added twice


@test("mood (0.105.24): the jewellers and bone carvers leave the last gems and bones to a mood that waits for them")
def _():
    s = fort()
    s["stocks"]["rough_gems"] = 12
    s["trade"] = {"rough_gem": {"n": 12, "token": "INORGANIC:AMETHYST"}}
    s["tools"]["autogems"] = None
    s["orders"] = []
    p, _ = plan(s, Memory())
    assert by_rule(p, "gem_cutting"), rules(p)
    s["moods"] = {"list": [_counted_mood([{"index": 0, "item": "ROUGH", "quantity": 1, "flags": [],
                                           "avail": _av(reach=0, free=0)}])]}
    p, _ = plan(s, Memory())
    assert not by_rule(p, "gem_cutting"), by_rule(p, "gem_cutting")
    s["moods"]["list"][0]["missing"][0]["avail"] = _av(reach=3, free=3, enough=True)      # within reach: cut away
    p, _ = plan(s, Memory())
    assert by_rule(p, "gem_cutting"), rules(p)


@test("mood (0.105.24): words: 'none (bone)' reads '1 bone'; any stone, gem or metal reads plainly; cloth in DF's units")
def _():
    from planner_society import mood_item_text
    assert mood_item_text({"item": "NONE", "flags": ["bone"], "quantity": 1}) == "1 bone"
    assert mood_item_text({"item": "ROUGH", "material": "rock", "quantity": 1}) == "1 rough gem"
    assert mood_item_text({"item": "BAR", "material": "rock", "flags": ["metal"], "quantity": 1}) == "1 bar (metal)"
    assert mood_item_text({"item": "CLOTH", "flags": ["silk"], "quantity": 9999}) == "1 cloth (silk)"
    assert mood_item_text({"item": "CLOTH", "flags": ["yarn"], "quantity": 30000}) == "3 cloths (yarn)"


@test("calm burrows (0.105.24): seen outside 90%+ of 40+ times: retired, the members let out, no new ones")
def _():
    s = fort()
    s.setdefault("society", {})["calm_burrow"] = {"members": 2, "free": 1, "seen_in": 1, "seen_out": 91}
    props, notes = [], []
    planner._calm_burrow_rule(s, PLANNER_CONFIG, props, notes)
    assert [p.action for p in props] == [{"type": "calm_burrow", "release": True}], [p.action for p in props]
    assert any("calm burrows retired" in n and "91 of 92" in n for n in notes), notes
    s["society"]["calm_burrow"] = {"members": 0, "free": 1, "seen_in": 0, "seen_out": 20}
    props, notes = [], []
    planner._calm_burrow_rule(s, PLANNER_CONFIG, props, notes)
    assert props and props[0].action.get("max"), [p.action for p in props]   # 20 seen: not judged retired yet
    s["society"]["calm_burrow"] = {"members": 0, "free": 1, "seen_in": 0, "seen_out": 45}
    props = []
    planner._calm_burrow_rule(s, PLANNER_CONFIG, props, [])
    assert props == [], [p.action for p in props]


@test("same booze (0.105.24): SameBooze in the census: fruit brewed, a second brewable crop planted; said in words")
def _():
    s = fort()
    s.setdefault("needs", {})["stress_causes"] = {"causes": [{"thought": "SameBooze", "citizens": 40}]}
    s["supplies"].update(drink_kinds=1, brewable_growths=30)
    s["farms"] = {"season": "spring", "plots_underground": 3, "plots_surface": 0,
                  "plot_list": [{"id": i, "options": 2, "underground": True} for i in (1, 2, 3)], "crops": {
        "MUSHROOM_HELMET_PLUMP": {"brews": "DWARVEN_WINE", "seeds": 20, "planted": 3, "seasons": ["spring", "summer"], "underground": True},
        "GRASS_WHEAT_CAVE": {"brews": "DWARVEN_BEER", "seeds": 9, "planted": 0, "seasons": ["spring"], "underground": True},
        "BUSH_QUARRY": {"seeds": 9, "planted": 0, "seasons": ["spring"], "underground": True}}}
    s["orders"] = []
    m = Memory()
    m.farm_steer = "crops"
    props, notes = plan(s, m)
    o = [p.action for p in by_rule(props, "booze_variety")]
    assert {"type": "work_order", "recipe": "brew_drink_from_fruit", "amount": 5} in o, o
    assert any(a.get("type") == "set_farm_crops" and a.get("variety") is True for a in o), o
    assert any("drinking the same booze (40 citizens" in n for n in notes), notes
    s["supplies"]["drink_kinds"] = 4                       # kinds enough: only said
    props, notes = plan(s, m)
    assert not by_rule(props, "booze_variety") and any("4 kinds of drink" in n for n in notes), notes
    s["supplies"]["drink_kinds"] = 1
    s["needs"]["stress_causes"]["causes"][0]["citizens"] = 2  # a few: nothing
    assert not by_rule(plan(s, m)[0], "booze_variety")
    import overseer
    assert "drinks of more kinds" in overseer.short({"type": "set_farm_crops", "variety": True})


@test("winter: food and drink are stocked up in autumn, more where the water freezes; fruit brews when plants don't")
def _():
    s = fort(stocks__drink=1700)
    base = by_rule(plan(s, Memory())[0], "drink")[0].action["amount"]
    s["date"]["season"] = "autumn"
    up = by_rule(plan(s, Memory())[0], "drink")[0]
    assert up.action["amount"] > base and "stocking up for winter" in up.reason, (base, up)
    m = Memory()
    m.climate_freezes = True
    more = by_rule(plan(s, m)[0], "drink")[0]
    assert more.action["amount"] >= up.action["amount"], (up.action, more.action)
    s["stocks"].update(plants=0, plant_growths=40)
    f = by_rule(plan(s, Memory())[0], "drink")[0]
    assert f.action["recipe"] == "brew_drink_from_fruit" and f.action["amount"] <= 40, f
    # ice seen: noted once, and a new well is looked for only inside
    s = fort()
    s["buildings"]["other"].pop("Well")
    s["labor"] = labor(dig=0, ice=12)
    m = Memory()
    from planner import note_cycle
    notes = note_cycle(s, m)
    assert m.climate_freezes and any("freezes" in n for n in notes), notes
    w = by_rule(plan(s, m)[0], "well")
    assert w and "inside_only" not in w[0].action, w        # spring: a shore well is fine until the freeze
    s["date"]["season"] = "winter"
    w = by_rule(plan(s, m)[0], "well")
    assert w and w[0].action.get("inside_only") is True, w   # winter: surface water would dismantle it


@test("basics outside: a refuse pile when there is none; a trade depot once the fort is fed and has 10 dwarves")
def _():
    s = fort()
    s["buildings"]["refuse_piles"] = 0
    s["buildings"]["other"].pop("TradeDepot", None)
    props = plan(s, Memory())[0]
    assert by_rule(props, "refuse")[0].action == {"type": "place_surface", "kind": "refuse"}
    assert by_rule(props, "depot")[0].action == {"type": "place_surface", "kind": "depot"}
    s["buildings"]["refuse_piles"] = 1
    s["buildings"]["other"]["TradeDepot"] = 1
    props = plan(s, Memory())[0]
    assert not by_rule(props, "refuse") and not by_rule(props, "depot")
    y = young(prepared_meals=20)                                         # young and short of food: no depot yet
    y["buildings"]["other"].pop("TradeDepot", None)
    y["dwarves"]["total"] = 12
    assert not by_rule(plan(y, Memory())[0], "depot")


@test("squads: wanted and none (or all full): the AI makes one and appoints its leader; switched off, it asks")
def _():
    s = fort()
    s["military"]["squads"] = []
    s["military"]["soldiers"] = 0
    s["settings"]["traits"] = {"militarism": 50}
    p = by_rule(plan(s, Memory())[0], "squad_make")
    assert p and p[0].action == {"type": "make_squad"}, rules(plan(s, Memory())[0])
    s["settings"]["fill_squads"] = False                              # (0.97: was appoint_nobles)
    props, notes = plan(s, Memory())
    assert not by_rule(props, "squad_make") and any("raising and filling squads is off" in n for n in notes)
    s = fort()
    s["military"]["gear"] = dict(s["military"].get("gear") or {}, squads=2, squads_with_uniform=1)
    assert any("have no uniform" in n for n in plan(s, Memory())[1])


@test("pacing: no new level while the digging waiting is more than the miners can get through")
def _():
    s = young(prepared_meals=200)
    s["labor"] = labor(dig=400, miners=3)
    props, notes = plan(s, Memory())
    assert not by_rule(props, "build") and any("wait to be dug" in n for n in notes), notes
    s["labor"] = labor(dig=100, miners=3)
    assert by_rule(plan(s, Memory())[0], "build")


@test("military: a small fort keeps its soldiers at work; the AI's own training waits until it grows")
def _():
    s = fort()
    s["dwarves"]["total"] = 7
    s["military"]["squads"][0]["routine"] = "Off duty"
    assert not by_rule(plan(s, Memory())[0], "train")                   # too small to train
    s["military"]["routines"] = ["Off duty", "Staggered training", "Constant training", "Ready"]
    s["military"]["squads"][0]["routine"] = "Staggered training"
    assert not by_rule(plan(s, Memory())[0], "train")                   # yours: left alone
    m = Memory()
    m.squads_trained = [11]                                              # the AI's: back to work
    t = by_rule(plan(s, m)[0], "train")
    assert t and t[0].action == {"type": "squad_routine", "squad_id": 11, "routine": "Off duty"}, t
    record([(t[0], {"ok": True})], s, m)
    assert m.squads_rested == [11]
    s["military"]["squads"][0]["routine"] = "Off duty"
    assert not by_rule(plan(s, m)[0], "train")
    s["dwarves"]["total"] = 20                                           # grown: it trains again
    t = by_rule(plan(s, m)[0], "train")
    assert t and t[0].action["routine"] == "Staggered training", t
    record([(t[0], {"ok": True})], s, m)
    assert m.squads_rested == [] and 11 in m.squads_trained
    assert not by_rule(plan(s, m)[0], "train")                           # you send it off duty now: your call


@test("metal: ore uncovered -> furnaces and a forge; bars low -> the vein mined; charcoal for the smelter")
def _():
    s = geared(bars={"IRON": 10, "COPPER": 5})
    s["buildings"]["furnaces"] = {}
    s["buildings"]["workshops"].pop("MetalsmithsForge", None)
    s["projects"]["open"] = []
    s["industry"] = {"ores": {"COPPER": {"tiles": 30, "ore": "MALACHITE"}, "IRON": {"tiles": 12, "ore": "HEMATITE"}}}
    s["labor"] = labor(dig=0, miners=3)
    props = plan(s, Memory())[0]
    ind = by_rule(props, "industry")
    assert ind and ind[0].action["shops"][:2] == ["WoodFurnace", "Smelter"], ind          # (the fort has a magma forge)
    ore = by_rule(props, "ore")
    assert ore and ore[0].action == {"type": "mine_ore", "metal": "IRON", "count": 40}, ore      # iron first
    s["labor"] = labor(dig=400, miners=3)
    assert not by_rule(plan(s, Memory())[0], "ore")                        # digging backlog: not now
    s["labor"] = labor(dig=0, miners=3)
    s["industry"]["ore_stock"] = 45
    assert not by_rule(plan(s, Memory())[0], "ore")                        # ore enough waiting to be smelted
    s["buildings"]["furnaces"] = {"Smelter": 1, "WoodFurnace": 1}
    s["supplies"]["fuel"] = 2
    s["stocks"]["wood"] = 50
    s["orders"] = []
    f = by_rule(plan(s, Memory())[0], "fuel")
    assert f and f[0].action["recipe"] == "make_charcoal", f
    s["industry"] = {"ores": {}}
    assert not by_rule(plan(s, Memory())[0], "industry")


@test("cleanup: a gate built at an entrance a scan no longer finds is taken down once; a real one is kept")
def _():
    s = fort()
    m = Memory()
    m.atlas = {"entrances": {"20,30,80": {"kind": "surface", "gone": "1 Granite y51"},
                             "40,40,80": {"kind": "surface"}},
               "registry": {"gate:20,30,80": {"kind": "gate", "status": "built", "pieces": ["20,30,80", "21,30,80"]},
                            "gate:40,40,80": {"kind": "gate", "status": "built"}}}
    p = by_rule(plan(s, m)[0], "cleanup")
    assert p and p[0].action == {"type": "clear_gate", "x": 20, "y": 30, "z": 80, "spot": "20,30,80",
                                 "pieces": ["20,30,80", "21,30,80"]}, p
    record([(p[0], {"ok": False, "error": "it is still an entrance of the fort: kept"})], s, m)
    assert m.atlas["registry"]["gate:20,30,80"]["status"] == "kept"
    assert not by_rule(plan(s, m)[0], "cleanup")


@test("trade: crafts to the depot while a caravan is coming; at the depot, Needs you to trade; crafts made when idle")
def _():
    s = fort()
    s["trade"] = {"depot": True, "caravans": [{"civ": "the Mountainhomes", "state": "Approaching"}], "goods": 12,
                  "at_depot": 0}
    props, notes = plan(s, Memory())
    t = by_rule(props, "trade")
    assert t and t[0].action == {"type": "bring_goods", "count": 12}, t
    assert not any("trade screen" in n for n in notes)
    s["trade"]["caravans"][0]["state"] = "AtDepot"
    s["trade"]["trader"] = {"requested": True, "at_depot": True}
    assert any("open the trade screen" in n for n in plan(s, Memory())[1])
    s["trade"] = {"depot": True, "caravans": [], "goods": 3}
    s["dwarves"].update(idle_adults=100, adults=167)
    s["orders"] = []
    c = by_rule(plan(s, Memory())[0], "crafts")
    assert c and c[0].action["recipe"] == "stone_crafts", c
    s["trade"]["depot"] = False
    props = plan(s, Memory())[0]
    assert not by_rule(props, "crafts") and not by_rule(props, "trade")


@test("trade deal: with the trade screen open and ready, a deal for what the fort is short of (pressed); not otherwise")
def _():
    from planner import trade_wants
    s = fort()
    s["trade"] = {"depot": True, "caravans": [{"civ": "the Mountainhomes", "state": "AtDepot"}], "goods": 0,
                  "at_depot": 30, "screen": {"open": True, "ready": True, "by_ai": True}}
    s.setdefault("military", {}).setdefault("gear", {})["bars"] = {"IRON": 39, "STEEL": 6}
    s["stocks"].update(cloth=5, thread=5, leather=0, wood=228, drink=10 ** 6, prepared_meals=10 ** 6)
    props, notes = plan(s, Memory())
    d = by_rule(props, "trade_deal")
    assert d and d[0].action["type"] == "trade_deal" and d[0].action["press"] is True, d
    keys = [w["key"] for w in d[0].action["wants"]]
    assert keys[:2] == ["BAR:STEEL", "CLOTH"] and "BAR:IRON" not in keys and "WOOD" not in keys \
        and "FOOD" not in keys and "DRINK" not in keys, keys
    assert d[0].action["wants"][0]["count"] == 30           # 60 wanted, 6 had: capped at 30 a visit
    assert not any("open the trade screen" in n for n in notes)
    s["trade"]["screen"]["ready"] = False
    props, notes = plan(s, Memory())
    assert not by_rule(props, "trade_deal")
    s["trade"].pop("screen")
    assert not any("open the trade screen" in n for n in plan(s, Memory())[1])   # nobody at the depot yet
    c = by_rule(plan(s, Memory())[0], "call_trader")
    assert c and c[0].action == {"type": "call_trader", "wait_ticks": 1200}, c
    s["trade"]["trader"] = {"requested": True, "at_depot": True}
    props, notes = plan(s, Memory())
    assert any("open the trade screen" in n for n in notes) and not by_rule(props, "call_trader")
    s["trade"]["trader"]["can_open"] = True               # shown the depot's button: the AI opens it itself
    props, notes = plan(s, Memory())
    o = by_rule(props, "open_trade")
    assert o and o[0].action == {"type": "open_trade"} and not any("open the trade screen" in n for n in notes), o
    s["trade"]["screen"] = {"open": True, "ready": True, "by_ai": True}
    s["stocks"].update(cloth=500, thread=500, leather=500, wood=500)
    s["military"]["gear"]["bars"] = {"IRON": 500, "STEEL": 500}
    s["supplies"]["fuel"] = 500
    props = plan(s, Memory())[0]
    assert by_rule(props, "close_trade") and not by_rule(props, "trade_deal") and not by_rule(props, "open_trade")
    s["trade"].pop("screen")
    s["stocks"].update(drink=0)
    assert trade_wants(s, PLANNER_CONFIG, 10)[0]["key"] == "DRINK"


@test("soap: with a hospital and fat, the chain one step at a time (workshops, tallow, ash, lye, soap); none without fat")
def _():
    from planner import trade_wants
    s = fort()
    s["locations"].setdefault("count", {})["HOSPITAL"] = 1
    s["orders"] = []
    s["supplies"].update(soap=0, ash=0, lye=0, tallow=0, fat=0, buckets=5)
    props, notes = plan(s, Memory())
    assert not by_rule(props, "soap") and any("no tallow to make it from" in n for n in notes), notes
    keys = [w["key"] for w in trade_wants(s, PLANNER_CONFIG, 20)]
    assert "SOAP" in keys and "TALLOW" in keys, keys                 # bought from the caravans meanwhile
    s["supplies"]["fat"] = 8
    s["buildings"]["workshops"].pop("Ashery", None)
    s["buildings"]["workshops"].pop("SoapMaker", None)
    s["projects"]["open"] = []
    p = by_rule(plan(s, Memory())[0], "soap")
    assert p and p[0].action["kind"] == "workshops" and set(p[0].action["shops"]) >= {"Ashery", "SoapMaker"}, p
    s["buildings"]["workshops"].update(Ashery=1, SoapMaker=1, Kitchen=1)
    s["buildings"].setdefault("furnaces", {})["WoodFurnace"] = 1
    def step():
        p = by_rule(plan(s, Memory())[0], "soap")
        return p[0].action.get("recipe") if p else None
    got = step()
    assert got == "render_fat", got
    s["supplies"]["tallow"] = 3
    got = step()
    assert got == "make_ash", got
    s["supplies"]["ash"] = 4
    got = step()
    assert got == "make_lye", got
    s["supplies"]["lye"] = 2
    got = step()
    assert got == "make_soap_from_tallow", got
    s["orders"] = [{"id": 1, "recipe": "make_soap_from_tallow", "amount_left": 1, "by_ai": True}]
    got = step()
    assert got == "render_fat", got                                     # each step waits on its own order only
    s["orders"].append({"id": 2, "recipe": "render_fat", "amount_left": 1, "by_ai": True})
    got = step()
    assert got is None, got
    # (0.104.32) Enxah: a render_fat order left with no fat held the lye back
    s["supplies"].update(fat=0, tallow=25, ash=5, lye=0, buckets=29)
    s["health"] = dict(s.get("health") or {}, infected=16)
    s["orders"] = [{"id": 1, "recipe": "render_fat", "amount_left": 4, "by_ai": True}]
    p = by_rule(plan(s, Memory())[0], "soap")
    assert p and p[0].action["recipe"] == "make_lye" and p[0].priority == 3, p
    s["orders"] = []
    s["supplies"]["soap"] = 5
    assert step() is not None, "(0.104.121) 16 infected wounds: 6 bars kept, not 5"
    s["supplies"]["soap"] = 6
    got = step()
    assert got is None, got and "SOAP" not in [w["key"] for w in trade_wants(s, PLANNER_CONFIG, 20)]
    s["health"]["infected"] = 0
    s["supplies"]["soap"] = 5
    assert step() is None, "nobody infected: 5 bars are enough"


@test("labour: work waiting with nobody free gets more dwarves; skilled migrants put on their trade; limits")
def _():
    s = fort()
    s.setdefault("labor", {})
    s["labor"]["waiting"] = [
        {"labor": "BREWER", "jobs": 12, "holders": 1, "idle": 0, "detail": "Brewers", "mode": "OnlySelectedDoesThis"},
        {"labor": "COOK", "jobs": 5, "holders": 2, "idle": 1},                       # someone is free: no
        {"labor": "MINE", "jobs": 40, "holders": 1, "idle": 0},                      # its own rule
        {"labor": "HAUL_STONE", "jobs": 90, "holders": 0, "idle": 0},                # everyone hauls
        {"labor": "SMELT", "jobs": 2, "holders": 1, "idle": 0},                      # too few to bother
        # (0.105.24) nobody has it at all: one waiting job is enough
        {"labor": "BOOKBINDING", "jobs": 1, "holders": 0, "idle": 0},
        {"labor": "MASON", "jobs": 8, "holders": 3, "idle": 0, "mode": "EverybodyDoesThis"}]
    s["labor"]["skilled_off"] = [{"labor": "FISH", "skilled": 2, "detail": "Fisherdwarves"},
                                 {"labor": "MINE", "skilled": 1, "detail": "Miners"}]
    props = [p for p in plan(s, Memory())[0] if p.rule == "labor" and p.action.get("job") in ("BREWER", "COOK",
             "MINE", "HAUL_STONE", "SMELT", "MASON", "FISH", "BOOKBINDING") and p.action.get("count") != 0]
    acts = [(p.action["job"], p.action["count"], p.action.get("min_skill")) for p in props
            if p.action["job"] != "MINE" or p.action.get("min_skill")]
    assert ("BREWER", 3, None) in acts and ("FISH", 2, 3) in acts, acts
    assert ("BOOKBINDING", 1, None) in acts, acts
    assert not any(j in ("COOK", "HAUL_STONE", "SMELT", "MASON") for j, _, _ in acts), acts
    assert not any(j == "MINE" and m for j, _, m in acts), acts


@test("hauling: wheelbarrows, one per 15 dwarves (at least 2), not in a young fort")
def _():
    s = fort()
    s["supplies"]["wheelbarrows"] = 3
    s["orders"] = []
    h = by_rule(plan(s, Memory())[0], "hauling")
    assert h and h[0].action == {"type": "work_order", "recipe": "wheelbarrow", "amount": 194 // 15 - 3}, h
    s["supplies"]["wheelbarrows"] = 20
    assert not by_rule(plan(s, Memory())[0], "hauling")


@test("noble rooms: a free room given to a noble who wants one; a suites level when none is free")
def _():
    from planner import suites_short
    s = fort()
    s["noble_rooms"] = {"nobles": [{"unit_id": 5, "name": "Urist", "office": "MANAGER", "needs": ["bedroom", "office"]},
                                   {"unit_id": 6, "name": "Kib", "office": "BROKER", "needs": ["office"]}],
                        "free": {"bedroom": 1, "office": 1, "dining": 0, "tomb": 0}}
    g = by_rule(plan(s, Memory())[0], "noble_rooms")
    assert [p.action["unit_id"] for p in g] == [5, 5] and {p.action["kind"] for p in g} == {"bedroom", "office"}, g
    assert suites_short(s) == 1                     # Kib still wants an office
    s["noble_rooms"]["free"] = {}
    assert suites_short(s) == 2 and not by_rule(plan(s, Memory())[0], "noble_rooms")
    p = [p for p in plan(s, Memory())[0] if p.action.get("kind") == "suites"]
    assert p and p[0].action["suites"] == 2, p
    s["noble_rooms"] = {}
    assert suites_short(s) == 0


@test("outside things: no new depot while one is being built or trees are being felled for it; placed when they're down")
def _():
    s = fort()
    s["buildings"]["other"].pop("TradeDepot", None)
    assert by_rule(plan(s, Memory())[0], "depot")
    s["buildings"]["being_built"] = {"TradeDepot": 1}
    assert not by_rule(plan(s, Memory())[0], "depot")
    s["buildings"]["being_built"] = {}
    s["buildings"]["clearing"] = {"depot": 3}
    assert not by_rule(plan(s, Memory())[0], "depot")
    s["buildings"]["clearing"] = {"depot": 0}
    d = by_rule(plan(s, Memory())[0], "depot")
    assert d and "trees in the way are down" in d[0].reason, d
    from planner import Proposal, note_refusal, refusal_key
    m = Memory()
    p = Proposal("depot", {"type": "place_surface", "kind": "depot"}, "x", 6)
    note_refusal(m, p, {"ok": False, "waiting": True, "error": "still felling"}, 1000)
    assert m.refusals[refusal_key(p)]["n"] == 0 and m.refusals[refusal_key(p)]["until"] == 1000 + 2 * 1200


@test("uniforms: a squad without one gets the fort's leather uniform; metal once there's armour for all; yours left alone")
def _():
    s = fort()
    s["military"]["uniform_templates"] = ["Melee, leather armor", "Melee, metal armor"]
    s["military"]["gear"] = {"squads": 2, "squads_with_uniform": 1, "spare": {"body": 0, "helms": 0}}
    s["military"]["squads"][0]["uniform"] = False
    props, notes = plan(s, Memory())
    u = by_rule(props, "uniform")
    assert u and u[0].action == {"type": "set_uniform", "squad_id": 11, "kind": "leather"}, u
    assert not any("have no uniform" in n for n in notes)
    s["military"]["squads"][0].update(uniform=True, ai_uniform="Melee, leather armor")
    assert not by_rule(plan(s, Memory())[0], "uniform")
    s["military"]["gear"]["spare"] = {"body": 10, "helms": 10}
    u = by_rule(plan(s, Memory())[0], "uniform")
    assert u and u[0].action["kind"] == "metal", u
    s["military"]["squads"][0].pop("ai_uniform")                  # set by the player: never changed
    assert not by_rule(plan(s, Memory())[0], "uniform")
    s["military"]["uniform_templates"] = []                       # no templates: Needs you, as before
    s["military"]["squads"][0]["uniform"] = False
    assert any("have no uniform" in n for n in plan(s, Memory())[1])


@test("justice: the AI appoints a sheriff when the sheriff's post is vacant")
def _():
    s = fort()
    s["society"]["vacant"] = ["SHERIFF", "CAPTAIN_OF_THE_GUARD"]
    props, notes = plan(s, Memory())
    a = by_rule(props, "appoint")
    assert a and a[0].action == {"type": "appoint", "office": "SHERIFF"}, a
    assert not any("sheriff" in n for n in notes), notes


@test("health: a patient's wait is tracked; a long one is said, with why; infection without soap too")
def _():
    s = fort()
    m = Memory()
    s["health"] = {"patients": [{"id": 7, "name": "Urist", "needs": ["surgery", "suture"]}]}
    plan(s, m)
    assert "7" not in m.patient_since                                       # (0.104.81) plan() reads memory only
    note_cycle(s, m); _, notes = plan(s, m)
    assert "7" in m.patient_since and not any("waited" in n for n in notes), notes
    s["date"]["tick"] = s["date"].get("tick", 0) + 30 * 1200
    s["society"]["vacant"] = ["CHIEF_MEDICAL_DWARF"]
    note_cycle(s, m); _, notes = plan(s, m)
    n = [x for x in notes if "waited a long time" in x]
    assert n and "Urist 30 days (needs surgery, suture)" in n[0] and "chief medical" in n[0], notes
    s["health"] = {"patients": [{"id": 8, "infected": True}]}
    s["supplies"]["soap"] = 0
    note_cycle(s, m); _, notes = plan(s, m)
    assert m.patient_since == {}, m.patient_since                         # 7 got well: forgotten; 8 asks for nothing
    s["health"] = {"patients": [{"id": 8, "infected": True, "needs": ["dressing"]}]}
    note_cycle(s, m); plan(s, m)
    assert list(m.patient_since) == ["8"], m.patient_since                 # (0.104.78) the wait starts when care is asked
    assert any("infected wounds" in x for x in notes), notes


@test("jail: dug once the fort has a sheriff and no dungeon zone; its restraints get ropes or chains")
def _():
    s = fort()
    s["buildings"]["zones"].pop("Dungeon")
    jail = lambda st: [p for p in plan(st, Memory())[0] if p.action.get("kind") == "jail"]
    assert not jail(s)                                                   # nobody in the sheriff's office
    s["offices"] = {"offices": {"SHERIFF": {"held": ["Urist"], "vacant": 0}}}
    j = jail(s)
    assert j and j[0].action["cells"] == 7, j                          # 194 dwarves: 7 cells
    s["settings"]["levels"] = {"jail": False}
    assert not jail(s)
    # restraints waiting: rope from cloth, else a chain from bars, else a note
    from planner import _restraint_order
    s = fort()
    s["stocks"]["cloth"] = 5
    s["orders"] = []
    props, notes = [], []
    _restraint_order(s, 3, PLANNER_CONFIG, props, notes)
    assert props[0].action == {"type": "work_order", "recipe": "cloth_rope", "amount": 3}, props
    s["stocks"]["cloth"] = 0
    s["military"]["gear"] = {"bars": {"IRON": 10}}
    props = []
    _restraint_order(s, 3, PLANNER_CONFIG, props, notes)
    assert props[0].action["recipe"] == "metal_chain" and props[0].action["material"] == "INORGANIC:IRON", props
    s["military"]["gear"] = {"bars": {}}
    props, notes = [], []
    _restraint_order(s, 3, PLANNER_CONFIG, props, notes)
    assert not props and "waiting for 3 rope" in notes[0], notes


@test("gathering: a fed fort with hundreds of waiting gathering jobs cancels all but 20; a hungry one keeps them")
def _():
    s = fort()
    s["jobs"]["by_type"]["GatherPlants"] = 849
    s["stocks"].update(prepared_meals=194 * 50)
    t = by_rule(plan(s, Memory())[0], "gather_trim")
    assert t and t[0].action == {"type": "trim_gathering", "keep": 20}, t
    s["stocks"].update(prepared_meals=0, fish=0, raw_fish=0, plants=0, plant_growths=0, meat=0)
    assert not by_rule(plan(s, Memory())[0], "gather_trim")


@test("well: none can be placed and nobody is hurt -> a note, not Needs you")
def _():
    s = fort()
    s["buildings"]["other"].pop("Well", None)
    m = Memory()
    m.well_failure = "no open drop from a free floor inside the fort to clean water"
    m.cavern_well_failure = "no floor inside the fort over cavern water with solid rock between; no gallery to the cavern water at x135 y131 elevation 7 (its nearest column is 81 tiles from the dwarves; a gallery reaches 40)"
    m.cavern_gallery_retried = True          # (0.105.4 review) the gallery was tried already
    notes = plan(s, m)[1]
    assert not any(n.startswith("[you] ") and "well" in n for n in notes), notes
    assert any("no one is hurt" in n for n in notes)
    s["dwarves"]["needs_medical_care"] = 2
    notes = plan(s, m)[1]
    assert not any(n.startswith("[you] ") and "well" in n for n in notes), notes      # (0.105.35)
    assert any("injured dwarves need water" in n and "water source zone" in n for n in notes), notes


@test("gates: a gate the AI built, and 4 weeks later the entrance still open -> built again (0.40's lost hatch)")
def _():
    s = entrances({"door_spots": 0, "width": 1, "x": 94, "y": 95})
    m = Memory()
    f = by_rule(plan(s, m)[0], "fortify")[0]
    record([(f, {"ok": True, "hatches": 1})], s, m)
    assert m.gates_fortified == {"94,95,173": "plain"} and "94,95,173" in m.gates_fortified_ticks
    later = copy.deepcopy(s)
    later["date"]["tick"] += 20 * 1200
    later["entrances"]["scanned_tick"] += 20 * 1200
    assert not by_rule(plan(later, m)[0], "fortify")                    # the dwarves may still be at it
    later["date"]["tick"] += 9 * 1200
    later["entrances"]["scanned_tick"] += 9 * 1200
    p, notes = plan(later, m)
    assert by_rule(p, "fortify") and any("building it again" in n for n in notes), notes
    assert not m.gates_fortified
    # a record from before 0.48 (no date): counted from the first look
    m2 = Memory()
    m2.gates_fortified = {"94,95,173": "plain"}
    assert not by_rule(plan(s, m2)[0], "fortify") and isinstance(m2.gates_fortified_ticks.get("94,95,173"), int)


@test("smelting: the AI's own orders from the ore in stock (DFHack's library waits for 100 charcoal)")
def _():
    s = geared(armed=3, bars={})
    s["buildings"]["furnaces"]["Smelter"] = 1
    magma_smelters = s["buildings"]["furnaces"].pop("MagmaSmelter", 0)   # (0.104.96) a fuel-burning smelter first
    s["supplies"]["fuel"] = 15
    s["industry"] = {"ores": {"IRON": {"tiles": 37, "ore": "MAGNETITE"}}, "ore_stock": 89,
                     "ore_stock_by": {"TETRAHEDRITE": {"n": 60, "metals": ["COPPER", "SILVER"]},
                                      "MAGNETITE": {"n": 29, "metals": ["IRON"]}}}
    sm = by_rule(plan(s, Memory())[0], "smelt")
    assert sm and sm[0].action == {"type": "work_order", "recipe": "smelt_ore", "amount": 10,
                                   "material": "INORGANIC:MAGNETITE"}, sm          # iron first, 10 at a time
    s["supplies"]["fuel"] = 3
    assert by_rule(plan(s, Memory())[0], "smelt")[0].action["amount"] == 3            # no more than the fuel
    s["supplies"]["fuel"] = 0
    assert not by_rule(plan(s, Memory())[0], "smelt")
    s["buildings"]["furnaces"]["MagmaSmelter"] = magma_smelters or 1      # (0.104.96) a magma smelter needs no fuel
    sm = by_rule(plan(s, Memory())[0], "smelt")
    assert sm and sm[0].action["amount"] == 10, sm
    s["supplies"]["fuel"] = 15
    s["orders"].append({"id": 8, "recipe": "smelt_ore", "job": "SmeltOre", "amount_left": 1, "amount_total": 1,
                        "repeats": True, "by_ai": False})                            # DFHack's library: waits for 100 coal
    assert by_rule(plan(s, Memory())[0], "smelt"), "a library order isn't smelting"
    s["orders"].append({"id": 9, "recipe": "smelt_ore", "amount_left": 4, "amount_total": 10, "by_ai": True})
    assert not by_rule(plan(s, Memory())[0], "smelt")                                  # one order at a time
    assert not by_rule(plan(s, Memory())[0], "smelting")                               # no library import any more


@test("watchdog: an order that doesn't move is named after 2 weeks (with a missing workshop); the AI's stuck again is cancelled again (0.105.35)")
def _():
    from planner import note_cycle
    s = fort()
    s["orders"] = [{"id": 7, "recipe": "smelt_ore", "job": "SmeltOre", "amount_left": 10, "amount_total": 10,
                    "by_ai": True},
                   {"id": 8, "job": "MakeCrafts", "amount_left": 3, "amount_total": 5, "by_ai": False},
                   {"id": 9, "job": "SmeltOre", "amount_left": 1, "amount_total": 1, "repeats": True}]
    s["buildings"]["furnaces"].pop("Smelter", None)
    s["buildings"]["furnaces"].pop("MagmaSmelter", None)
    m = Memory()
    note_cycle(s, m)
    assert set(m.order_watch) == {"7", "8"}, m.order_watch                    # repeating orders wait by design
    def at(days):
        t = copy.deepcopy(s)
        t["date"]["tick"] += days * 1200
        note_cycle(t, m)
        return plan(t, m)[1]
    notes = at(10)
    assert not any("haven't moved" in n for n in notes)
    notes = at(15)
    line = [n for n in notes if "haven't moved:" in n]
    assert line and "smelt_ore (10 left, the AI) for 15 days: the fort has no Smelter" in line[0], notes
    t = copy.deepcopy(s)
    t["date"]["tick"] += 29 * 1200
    note_cycle(t, m)
    props, notes = plan(t, m)
    assert not any(n.startswith("[you]") and "work order" in n for n in notes), notes   # cancelled instead
    c = by_rule(props, "stuck_order")
    assert c and c[0].action == {"type": "cancel_work_order", "order_id": 7, "stuck": "smelt_ore"}, c
    assert not any(p.action.get("order_id") == 8 for p in c)                  # never the player's
    record([(c[0], {"ok": True})], t, m)
    assert "smelt_ore" in m.stuck_cancelled
    # not placed again for 4 weeks
    from planner import Proposal
    allowed, held = select([Proposal("smelt", {"type": "work_order", "recipe": "smelt_ore", "amount": 5}, "x", 4, True)],
                           t, m)
    assert not allowed and any("got stuck and was cancelled" in h for h in held), held
    # stuck again within 90 days: said, and cancelled again, held longer (was Needs you, left standing)
    notes = at(29 + 40)
    t = copy.deepcopy(s); t["date"]["tick"] += (29 + 40) * 1200
    assert any(n.startswith("1 of the AI's work order(s) got stuck again") for n in notes), notes
    assert not any(n.startswith("[you]") and "work order" in n for n in notes), notes
    c2 = by_rule(plan(t, m)[0], "stuck_order")
    assert c2 and c2[0].action == {"type": "cancel_work_order", "order_id": 7, "stuck": "smelt_ore"}, c2
    assert "56 days" in c2[0].reason, c2[0].reason
    assert not any(p.action.get("order_id") == 8 for p in c2)                 # never the player's
    s["orders"][0]["amount_left"] = 6                                         # it moved: the clock starts again
    notes = at(70)
    assert not any("smelt_ore" in n for n in notes if "haven't moved" in n or "stuck" in n), notes


@test("stuck orders: copies of one AI order that don't move are cancelled after 2 weeks, keeping one")
def _():
    from planner import note_cycle
    s = fort()
    s["orders"] = [{"id": i, "recipe": "coke_bituminous", "job": "CustomReaction", "amount_left": 5,
                    "amount_total": 5, "by_ai": True} for i in range(20, 28)]
    m = Memory()
    note_cycle(s, m)
    t = copy.deepcopy(s)
    t["date"]["tick"] += 15 * 1200
    t["orders"][-1]["amount_left"] = 4                                        # the last one moved
    note_cycle(t, m)
    c = by_rule(plan(t, m)[0], "stuck_order")
    ids = [p.action["order_id"] for p in c]
    assert len(ids) == 5 and 27 not in ids and all("stuck" not in p.action for p in c), ids
    u = copy.deepcopy(t)
    u["orders"] = {"error": "orders section failed"}                         # (0.104.81) no fresh list
    assert not by_rule(plan(u, m)[0], "stuck_order"), "a stale watch cancels nothing"


@test("watchdog: the same population for a year is said (under the cap)")
def _():
    from planner import note_cycle
    s = fort()
    m = Memory()
    note_cycle(s, m)
    later = copy.deepcopy(s)
    later["date"]["year"] += 1
    later["date"]["tick"] += 1200
    note_cycle(later, m)
    later["society"]["pop_cap"] = 300
    assert any("for a year or more" in n for n in plan(later, m)[1])
    later["dwarves"]["total"] += 1
    note_cycle(later, m)
    assert not any("for a year or more" in n for n in plan(later, m)[1])


@test("steel: pig iron first, then steel, from spare iron, flux and fuel; some iron always kept back")
def _():
    s = geared(bars={"IRON": 20})
    s["buildings"]["furnaces"]["Smelter"] = 1
    s["supplies"]["fuel"] = 30
    s["industry"] = {"ores": {"IRON": {"tiles": 30, "ore": "MAGNETITE"}}, "flux_stock": 12}
    st = by_rule(plan(s, Memory())[0], "steel")
    assert st and st[0].action == {"type": "work_order", "recipe": "pig_iron", "amount": 5}, st
    s["military"]["gear"]["pig_iron"] = 3
    st = by_rule(plan(s, Memory())[0], "steel")
    assert st and st[0].action == {"type": "work_order", "recipe": "steel", "amount": 3}, st
    s["military"]["gear"]["bars"] = {"IRON": 6}                                # only what's kept back
    assert not by_rule(plan(s, Memory())[0], "steel")
    s["military"]["gear"]["bars"] = {"IRON": 20}
    s["industry"]["flux_stock"] = 0
    p, notes = plan(s, Memory())
    assert not by_rule(p, "steel") and any("no flux stone" in n for n in notes), notes
    s["industry"]["flux_stock"] = 12
    s["military"]["gear"]["bars"] = {"IRON": 20, "STEEL": 80}                  # enough steel
    assert not by_rule(plan(s, Memory())[0], "steel")


@test("hospital: a small fed fort with a chief medical dwarf builds one at 10 dwarves (else at 20)")
def _():
    s = fort()
    s["locations"] = {"count": {}, "total": 0}
    s["dwarves"]["total"] = 14
    hosp = lambda st: [p for p in plan(st, Memory())[0] if p.action.get("kind") == "hospital"]
    assert not hosp(s)
    s["offices"] = {"offices": {"CHIEF_MEDICAL_DWARF": {"held": ["Onol"], "vacant": 0}}}
    assert hosp(s), [p.action for p in plan(s, Memory())[0] if p.action.get("type") == "start_project"]


@test("uniform weapon: soldiers holding a pick aren't armed; axes made, then the uniform asks for axes only")
def _():
    s = geared(soldiers=3, on_duty=3, armed=1, armored=3, helmed=3, squads=1, squads_with_uniform=1,
               bars={"IRON": 100}, spare={"weapons": 2, "body": 0, "helms": 0},
               spare_weapons={"ITEM_WEAPON_PICK": 2})
    s.setdefault("labor", {})["soldier_picks"] = 1
    s["military"]["uniform_templates"] = ["Melee, leather armor"]
    s["military"]["squads"] = [{"id": 32, "name": "", "members": 3, "size": 10, "uniform": True,
                                "ai_uniform": "Melee, leather armor"}]
    s["orders"] = []
    a = by_rule(plan(s, Memory())[0], "arms")
    assert a and a[0].action["recipe"] == "metal_battle_axe" and a[0].action["amount"] == 3, a   # the pick isn't an axe
    assert not [p for p in by_rule(plan(s, Memory())[0], "uniform")
                if p.action["type"] == "set_uniform_weapon"]                                     # no axes yet
    s["military"]["gear"]["spare_weapons"] = {"ITEM_WEAPON_AXE_BATTLE": 3}
    u = [p for p in by_rule(plan(s, Memory())[0], "uniform") if p.action["type"] == "set_uniform_weapon"]
    assert u and u[0].action == {"type": "set_uniform_weapon", "squad_id": 32, "weapon": "ITEM_WEAPON_AXE_BATTLE"}, u
    s["military"]["squads"][0]["ai_uniform"] = "Melee, leather armor |weapon:ITEM_WEAPON_AXE_BATTLE"
    assert not [p for p in by_rule(plan(s, Memory())[0], "uniform") if p.action["type"] == "set_uniform_weapon"]
    s["military"]["squads"][0]["ai_uniform"] = None                                              # yours: left alone
    s["military"]["squads"][0]["ai_uniform"] = ""
    assert not [p for p in by_rule(plan(s, Memory())[0], "uniform") if p.action["type"] == "set_uniform_weapon"]


@test("stone: no stone the masons may use -> a plentiful economic stone allowed (never ore or flux), else wood")
def _():
    s = fort()
    s["stone_use"] = {"usable": 2, "economic": {"MAGNETITE": {"n": 62, "ore": True},
                                                 "LIMESTONE": {"n": 30, "flux": True}, "GYPSUM": {"n": 40}}}
    st = by_rule(plan(s, Memory())[0], "stone")
    assert st and st[0].action == {"type": "allow_stone", "stone": "GYPSUM"}, st
    # nothing to allow: the AI's stuck stone order is cancelled, and furniture goes to wood
    s["stone_use"]["economic"].pop("GYPSUM")
    from planner import note_cycle
    s["orders"] = [{"id": 41, "recipe": "stone_chest", "job": "ConstructChest", "amount_left": 3,
                    "amount_total": 3, "by_ai": True}]
    m = Memory()
    note_cycle(s, m)
    later = copy.deepcopy(s)
    later["date"]["tick"] += 15 * 1200
    p_later = plan(later, m)[0]
    st = by_rule(p_later, "stone")
    assert st and st[0].action == {"type": "cancel_work_order", "order_id": 41, "stuck": "stone_chest"}, st
    q = by_rule(p_later, "quarry")
    assert q and q[0].action == {"type": "quarry", "count": 20}, q             # and dig some ordinary stone
    s["stone_use"]["usable"] = 500
    assert not by_rule(plan(s, Memory())[0], "stone")                          # plenty: nothing to do
    from planner import stone_short
    assert not stone_short({"stone_use": {}}, 10)                              # older bridge: unknown, not short


def _conv_body():
    s = fort()
    s["justice"] = {"jails": [{"id": 453, "chains": 5, "used": 0}], "restraints": 10, "restraints_used": 0,
                    "punish": {"n": 0}, "crimes": {"n": 1623, "convictable": 398}}
    c = by_rule(plan(copy.deepcopy(s), Memory())[0], "convict")
    assert c and c[0].action == {"type": "convict", "max": 3} and "398 solved" in c[0].reason, c
    s["justice"]["punish"]["n"] = 8                                    # 2 places left, 1 kept spare (0.104.141)
    assert by_rule(plan(copy.deepcopy(s), Memory())[0], "convict")[0].action["max"] == 1
    s["justice"]["punish"]["n"] = 9
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "convict")
    s["justice"]["punish"]["n"] = 0
    s["settings"]["traits"] = dict(s["settings"].get("traits") or {}, justice=-60)   # a lenient fort
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "convict")
    s["settings"]["traits"]["justice"] = 0
    s["justice"]["crimes"]["convictable"] = 0
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "convict")


@test("convict (0.104.131): solved cases convicted a few a cycle; none when lenient, none while punishments queue")
def _():
    PLANNER_CONFIG["convict_on"] = True        # (0.104.147) off by default
    try:
        _conv_body()
    finally:
        PLANNER_CONFIG["convict_on"] = False


def _conv_body():
    s = fort()
    s["justice"] = {"jails": [{"id": 453, "chains": 5, "used": 1}], "restraints": 10, "restraints_used": 2,
                    "punish": {"n": 1, "beatings": 1}, "crimes": {"n": 1745, "convictable": 204,
                                                                   "flags": {"sentenced": 2}}}
    m = Memory()
    props = plan(copy.deepcopy(s), m)[0]
    assert not by_rule(props, "convict"), "a beating waits (Teacheroar's sheriff)"
    s["justice"]["punish"] = {"n": 0, "beatings": 0}
    s["justice"]["restraints_used"] = 10
    assert not by_rule(plan(copy.deepcopy(s), m)[0], "convict"), "no free jail place"
    s["justice"]["restraints_used"] = 2
    c = by_rule(plan(copy.deepcopy(s), m)[0], "convict")
    assert c and c[0].action["max"] == 3 and "7 free jail" in c[0].reason, c
    for _ in range(10):                                         # 30 convicted, still 2 sentenced
        record([(c[0], {"ok": True, "convicted": [1, 2, 3]})], s, m)
    assert m.convict_watch["given"] == 30 and m.convict_watch["sentenced0"] == 2, m.convict_watch
    assert not by_rule(plan(copy.deepcopy(s), m)[0], "convict") and m.convict_watch.get("until")
    s["date"]["tick"] += 85 * 1200                              # rested: tries again
    assert by_rule(plan(copy.deepcopy(s), m)[0], "convict")
    m2 = Memory(convict_watch={"given": 30, "sentenced0": 2})
    s["justice"]["crimes"]["flags"]["sentenced"] = 12           # they work: on
    assert by_rule(plan(copy.deepcopy(s), m2)[0], "convict") and m2.convict_watch.get("sentenced0") == 12
    # (review) the count over every crime wins over the newest-400 flags; a rest late in the year ends
    m3 = Memory(convict_watch={"given": 30, "sentenced0": 2})
    s["justice"]["crimes"]["flags"]["sentenced"] = 2
    s["justice"]["crimes"]["sentenced_all"] = 9
    assert by_rule(plan(copy.deepcopy(s), m3)[0], "convict"), "7 more sentenced among the old cases"
    late = copy.deepcopy(s)
    late["justice"]["crimes"]["sentenced_all"] = 2
    late["date"]["tick"] = 300 * 1200
    m4 = Memory(convict_watch={"given": 30, "sentenced0": 2})
    assert not by_rule(plan(copy.deepcopy(late), m4)[0], "convict") and m4.convict_watch.get("until")
    late["date"]["year"] += 1
    late["date"]["tick"] = 60 * 1200                              # 96 days on, past the new year
    assert by_rule(plan(copy.deepcopy(late), m4)[0], "convict")


@test("convict (0.104.138): never while a beating waits, only into free jail places; rests when no sentences follow")
def _():
    PLANNER_CONFIG["convict_on"] = True        # (0.104.147) off by default
    try:
        _conv_body()
    finally:
        PLANNER_CONFIG["convict_on"] = False


@test("0.105.22 the dead's work: slab orders kept while ghosts walk; one waiting mason job gets a mason; a level nothing dug in 56 days given up")
def _():
    from planner_industry import _labor_waiting_rule
    cfg = dict(PLANNER_CONFIG)
    props = []
    lb = {"waiting": [{"labor": "MASON", "jobs": 1, "holders": 2, "idle": 0}]}
    _labor_waiting_rule(lb, 90, cfg, props, False, False)
    assert not props, props
    _labor_waiting_rule(lb, 90, cfg, props, False, True)
    assert props and props[0].action == {"type": "assign_labor", "job": "MASON", "count": 1}, props
    s = fort()
    s["dead"] = {"ghosts": 3, "unburied": 0, "free_tombs": 2}
    s["stone_use"] = {"usable": 5, "economic": {}}
    m = Memory()
    m.order_watch = {"77": {"by_ai": True, "what": "stone_slab", "since": abs_tick(s) - 40 * TICKS_PER_DAY, "left": 3}}
    acts = [p.action for p in plan(copy.deepcopy(s), m)[0]]
    assert not [a for a in acts if a.get("type") == "cancel_work_order" and a.get("order_id") == 77], acts
    s["dead"] = {"ghosts": 0, "unburied": 0, "free_tombs": 2}
    acts = [p.action for p in plan(copy.deepcopy(s), m)[0]]
    assert [a for a in acts if a.get("type") == "cancel_work_order" and a.get("order_id") == 77], acts


@test("0.105.19 stone crisis: ghosts waiting free an ore of 10+ boulders (C: limonite 27, tetrahedrite 27)")
def _():
    s = fort()
    s["stone_use"] = {"usable": 5, "economic": {"LIMONITE": {"n": 27, "ore": True}, "TETRAHEDRITE": {"n": 27, "ore": True},
                                                 "NATIVE_PLATINUM": {"n": 7, "ore": True}, "CASSITERITE": {"n": 6, "ore": True},
                                                 "COAL_BITUMINOUS": {"n": 21, "fuel": "coke_bituminous"}}}
    s["dead"] = {"ghosts": 0, "unburied": 0, "free_tombs": 5}
    assert not [p for p in by_rule(plan(copy.deepcopy(s), Memory())[0], "stone") if p.action["type"] == "allow_stone"]
    s["dead"] = {"ghosts": 2, "unburied": 0, "free_tombs": 5}
    st = [p for p in by_rule(plan(copy.deepcopy(s), Memory())[0], "stone") if p.action["type"] == "allow_stone"]
    assert st and st[0].action["ore"] is True and st[0].action["stone"] in ("LIMONITE", "TETRAHEDRITE"), st
    s["stone_use"]["economic"] = {"LIMONITE": {"n": 8, "ore": True}}     # too few even for ghosts
    assert not [p for p in by_rule(plan(copy.deepcopy(s), Memory())[0], "stone") if p.action["type"] == "allow_stone"]


@test("stone crisis (0.104.124): no ordinary stone, ghosts or dead waiting: the commonest common ore to the masons; kept again after")
def _():
    from planner import record
    s = fort()
    s["stone_use"] = {"usable": 3, "economic": {"MAGNETITE": {"n": 79, "ore": True}, "NATIVE_PLATINUM": {"n": 90, "ore": True},
                                                 "LIMONITE": {"n": 70, "ore": True}, "LIMESTONE": {"n": 30, "flux": True},
                                                 "COAL_BITUMINOUS": {"n": 13, "fuel": "coke_bituminous"}}}
    s["dead"] = {"ghosts": 0, "unburied": 0, "free_tombs": 0}
    st = [p for p in by_rule(plan(copy.deepcopy(s), Memory())[0], "stone") if p.action["type"] == "allow_stone"]
    assert not st, st                                                    # no crisis: ore stays kept
    s["dead"] = {"ghosts": 13, "unburied": 38, "free_tombs": 0}           # Teacheroar, 31 Oct
    m = Memory()
    st = by_rule(plan(copy.deepcopy(s), m)[0], "stone")
    assert st and st[0].action == {"type": "allow_stone", "stone": "MAGNETITE", "ore": True}, st   # never platinum
    assert "13 ghosts" in st[0].reason and "38 dead" in st[0].reason, st[0].reason
    record([(st[0], {"ok": True})], s, m)
    assert m.ores_freed == ["MAGNETITE"]
    s["stone_use"] = {"usable": 82, "economic": {}}                        # the masons have it now
    assert not by_rule(plan(copy.deepcopy(s), m)[0], "stone")             # still a crisis: kept free
    s["dead"] = {"ghosts": 0, "unburied": 0, "free_tombs": 4}             # over
    st = by_rule(plan(copy.deepcopy(s), m)[0], "stone")
    assert st and st[0].action == {"type": "allow_stone", "stone": "MAGNETITE", "keep": True}, st
    record([(st[0], {"ok": True})], s, m)
    assert m.ores_freed == []


@test("stone famine (0.104.4): no usable stone -> a quarry despite other digging (every 10 days); more picks for a backlog")
def _():
    s = fort()
    s["stone_use"] = {"usable": 0, "economic": {"MAGNETITE": {"n": 4, "ore": True}}}
    s["labor"] = dict(s.get("labor") or {}, dig=126, picks=3, miners=3)
    s["dwarves"]["total"] = 93
    s["buildings"]["workshops"]["MetalsmithsForge"] = 1
    s.setdefault("military", {}).setdefault("gear", {})["bars"] = {"IRON": 21}
    s["orders"] = []
    m = Memory()
    props = plan(s, m)[0]
    assert by_rule(props, "quarry"), "no quarry with 126 tiles waiting and no stone"
    pk = by_rule(props, "picks")
    assert pk and pk[0].action["amount"] == 3 and pk[0].action["material"] == "INORGANIC:IRON", pk
    m.last_fired["quarry"] = abs_tick(s) - 3 * 1200
    assert not by_rule(plan(s, m)[0], "quarry")                     # one 3 days ago: not yet
    s["stone_use"]["usable"] = 4
    assert not by_rule(plan(s, Memory())[0], "quarry")              # some stone: the backlog digs first


@test("furniture: no stone the masons may use -> made in wood (statues wait, with a note)")
def _():
    s = fort()
    s["orders"] = []
    s["projects"] = {"open": [{"id": 3, "kind": "suites", "phase": "furnish",
                               "furnish": {"waiting": {"Box": 3, "Statue": 2}}}], "max_open": 2}
    s["stone_use"] = {"usable": 0, "economic": {}}
    props, notes = plan(s, Memory())
    f = by_rule(props, "furniture")
    assert f and f[0].action["recipe"] == "wooden_chest" and "no stone the masons may use" in f[0].reason, f
    assert any("statue" in n and "no stone the masons may use" in n for n in notes), notes


@test("coal: kept for coke (never let to the masons); coke made before charcoal while fuel is low")
def _():
    s = fort()
    s["stone_use"] = {"usable": 0, "economic": {"COAL_BITUMINOUS": {"n": 39}, "GYPSUM": {"n": 6}}, "fuel_free": {}}
    props = plan(s, Memory())[0]
    assert not any(p.action.get("stone") == "COAL_BITUMINOUS" for p in by_rule(props, "stone")), by_rule(props, "stone")
    s["stone_use"]["fuel_free"] = {"COAL_BITUMINOUS": 30}                    # 0.52 let the masons have it
    st = by_rule(plan(s, Memory())[0], "stone")
    assert st and st[0].action == {"type": "allow_stone", "stone": "COAL_BITUMINOUS", "keep": True}, st
    # coke
    s = geared(bars={"IRON": 100})
    s["buildings"]["furnaces"].update(Smelter=1, WoodFurnace=1)
    s["industry"] = {"ores": {"IRON": {"tiles": 30, "ore": "MAGNETITE"}}}
    s["supplies"]["fuel"] = 8
    s["stone_use"] = {"usable": 50, "economic": {"COAL_BITUMINOUS": {"n": 39}, "LIGNITE": {"n": 8}}}
    s["orders"] = []
    f = by_rule(plan(s, Memory())[0], "fuel")
    assert f and f[0].action == {"type": "work_order", "recipe": "coke_bituminous", "amount": 5}, f
    s["stone_use"]["economic"] = {}
    f = by_rule(plan(s, Memory())[0], "fuel")
    assert f and f[0].action["recipe"] == "make_charcoal", f                  # no coal: charcoal as before


@test("cloth: workshops when missing, then thread from plants, then weaving; not in a young fort")
def _():
    s = fort()
    s["stocks"].update(cloth=5, thread=0, plants=100)
    s["orders"] = []
    s["projects"] = {"open": [], "max_open": 2}
    s["buildings"]["workshops"].pop("Loom", None)
    c = by_rule(plan(s, Memory())[0], "cloth")
    assert c and c[0].action["type"] == "start_project" and "Loom" in c[0].action["shops"], c
    s["buildings"]["workshops"].update(Loom=1, Farmers=1)
    c = by_rule(plan(s, Memory())[0], "cloth")
    assert c and c[0].action == {"type": "work_order", "recipe": "process_plants", "amount": 5}, c
    s["stocks"]["thread"] = 8
    c = by_rule(plan(s, Memory())[0], "cloth")
    assert c and c[0].action == {"type": "work_order", "recipe": "weave_plant_cloth", "amount": 5}, c
    s["orders"] = [{"id": 6202, "recipe": "weave_plant_cloth", "amount_left": 5, "by_ai": True}]   # (0.104.123) no job made
    c = by_rule(plan(s, Memory())[0], "cloth")
    assert c and c[0].action["recipe"] == "process_plants" and "isn't fit for the loom" in c[0].reason, c
    s["orders"][0]["jobs"] = {"n": 1, "working": 1}                                                  # weaving: fine
    assert not by_rule(plan(s, Memory())[0], "cloth")
    s["orders"] = []
    s["stocks"]["thread"] = 0                                                                         # (0.104.132)
    s["health"] = dict(s.get("health") or {}, needs_counts={"dressing": 79})
    c = by_rule(plan(s, Memory())[0], "cloth")
    assert c and c[0].action == {"type": "work_order", "recipe": "process_plants", "amount": 20}, c      # 79 dressings
    s["health"]["needs_counts"] = {"dressing": 8}
    assert by_rule(plan(s, Memory())[0], "cloth")[0].action["amount"] == 7
    s["stocks"]["cloth"] = 500
    assert not by_rule(plan(s, Memory())[0], "cloth")


@test("bottleneck: a long queue of the AI's orders on one smelter, dwarves idle -> another smelter")
def _():
    s = fort()
    s["dwarves"].update(idle_adults=60, adults=150)
    s["projects"] = {"open": [], "max_open": 2}
    s["buildings"]["furnaces"] = {"Smelter": 1, "WoodFurnace": 1}
    s["orders"] = [{"id": i, "recipe": r, "job": "CustomReaction", "amount_left": 5, "amount_total": 5, "by_ai": True}
                   for i, r in enumerate(["coke_bituminous", "coke_bituminous", "pig_iron", "steel"])]
    b = by_rule(plan(s, Memory())[0], "bottleneck")
    assert b and b[0].action == {"type": "start_project", "kind": "workshops", "shops": ["Smelter"]}, b
    s["buildings"]["furnaces"]["Smelter"] = 2                                   # 10 a smelter: fine
    assert not by_rule(plan(s, Memory())[0], "bottleneck")
    s["buildings"]["furnaces"]["Smelter"] = 1
    s["dwarves"].update(idle_adults=5)                                          # nobody idle: no point
    assert not by_rule(plan(s, Memory())[0], "bottleneck")


@test("polish: idle hands -> a finished level smoothed or engraved; none while busy")
def _():
    s = fort()
    s["dwarves"].update(idle_adults=60, adults=150)
    assert by_rule(plan(s, Memory())[0], "polish")
    s["dwarves"].update(idle_adults=10)
    assert not by_rule(plan(s, Memory())[0], "polish")


@test("leather to metal once there are bars for it (a leather uniform takes no iron helms), with mail ordered")
def _():
    s = geared(soldiers=3, on_duty=3, armed=0, armored=3, helmed=0, squads=1, squads_with_uniform=1,
               bars={"IRON": 28, "STEEL": 6}, spare={"weapons": 3, "body": 0, "helms": 3})
    s["military"]["uniform_templates"] = ["Melee, leather armor", "Melee, metal armor"]
    s["military"]["squads"] = [{"id": 32, "name": "", "members": 3, "size": 10, "uniform": True,
                                "ai_uniform": "Melee, leather armor |weapon:ITEM_WEAPON_AXE_BATTLE"}]
    s["orders"] = []
    props = plan(s, Memory())[0]
    u = by_rule(props, "uniform")
    assert u and u[0].action == {"type": "set_uniform", "squad_id": 32, "kind": "metal"}, u
    k = by_rule(props, "kit")
    assert k and k[0].action["recipe"] == "metal_mail_shirt" and k[0].action["amount"] == 3, k
    s["military"]["gear"]["bars"] = {"IRON": 5}
    assert not by_rule(plan(s, Memory())[0], "uniform")                       # too few bars: leather stays


@test("coke: fuel enough -> the AI's waiting coke orders are cancelled, one a cycle")
def _():
    s = geared(bars={"IRON": 100})
    s["buildings"]["furnaces"].update(Smelter=1, WoodFurnace=1)
    s["industry"] = {"ores": {"IRON": {"tiles": 30, "ore": "MAGNETITE"}}}
    s["supplies"]["fuel"] = 41                         # (0.100.1) just over: kept (no churn at the line)
    s["orders"] = [{"id": 70, "recipe": "coke_bituminous", "job": "CustomReaction", "amount_left": 5,
                    "amount_total": 5, "by_ai": True}]
    assert not by_rule(plan(s, Memory())[0], "fuel_trim")
    s["supplies"]["fuel"] = 81                         # twice the line: cancelled
    t = by_rule(plan(s, Memory())[0], "fuel_trim")
    assert t and t[0].action == {"type": "cancel_work_order", "order_id": 70}, t
    s["supplies"]["fuel"] = 20
    assert not by_rule(plan(s, Memory())[0], "fuel_trim")


@test("a refusal booked under another bridge version is tried again at once; the same version waits")
def _():
    from planner import Proposal, note_refusal, refusal_key, _refused_wait, TICKS_PER_DAY
    m = Memory()
    p = Proposal("squad_make", {"type": "make_squad"}, "x", 3)
    note_refusal(m, p, {"ok": False, "error": "no military office is free"}, 1000, "0.80.0")
    assert m.refusals[refusal_key(p)]["v"] == "0.80.0"
    assert _refused_wait(m, p, 1001, "0.80.0") is not None
    assert _refused_wait(m, p, 1001, "0.81.0") is None
    assert _refused_wait(m, p, 1001) is not None        # no version known: as before
    m.refusals[refusal_key(p)].pop("v")                                    # booked before 0.81: once more
    assert _refused_wait(m, p, 1001, "0.81.0") is None


# --- (0.96) graded behaviour: Mining, Surface, Justice, Deference, Greed, Engineering, Outsiders ----

@test("graded numbers (0.96): each of the seven sliders changes its numbers across the range")
def _():
    from planner import (cistern_pop, gatherers, jail_plan, keeps_treasures, mining_plan, noble_room_kinds,
                         outsider_orders, spare_mechanisms, tavern_factor, trade_margin_for, woodcutters)
    c = PLANNER_CONFIG
    lo, mid, hi = mining_plan({"mining": -100}, c), mining_plan({}, c), mining_plan({"mining": 100}, c)
    assert lo["need_only"] and not lo["veins"] and mid["veins"] and not mid["need_only"]
    assert lo["quarry"] < mid["quarry"] < hi["quarry"] and mid["bars_below"] < hi["bars_below"]
    assert not mining_plan({"mining": -50}, c)["veins"] and not mining_plan({"mining": -50}, c)["need_only"]
    assert [woodcutters({"surface": v}, False) for v in (-100, 0, 100)] == [1, 2, 3]
    assert [gatherers({"surface": v}, False) for v in (-100, 0, 100)] == [2, 3, 4]
    assert jail_plan({"justice": -100}, c, 100) is None
    assert jail_plan({"justice": -50}, c, 100)["min_dwarves"] > jail_plan({}, c, 100)["min_dwarves"] \
        > jail_plan({"justice": 100}, c, 100)["min_dwarves"]
    assert jail_plan({"justice": 100}, c, 100)["cells"] > jail_plan({}, c, 100)["cells"]
    assert trade_margin_for({"greed": -100}, c) > trade_margin_for({}, c) == 1.2 > trade_margin_for({"greed": 100}, c)
    assert trade_margin_for({"greed": 200}, c) == 1.05 and keeps_treasures({"greed": 50})
    assert keeps_treasures({"greed": 40}) and not keeps_treasures({"greed": 20})    # (0.105.33) +30 now
    assert noble_room_kinds({"deference": -100}) == () and noble_room_kinds({"deference": -60}) == ("bedroom",)
    assert noble_room_kinds({"deference": -10}) == ("bedroom", "office") and len(noble_room_kinds({})) == 4
    assert cistern_pop({"engineering": -200}, c) is None
    assert cistern_pop({"engineering": -100}, c) > cistern_pop({}, c) == 30 > cistern_pop({"engineering": 100}, c)
    assert [spare_mechanisms({"engineering": v}) for v in (0, 40, 50, 100)] == [0, 0, 2, 4]
    assert outsider_orders({"outsiders": -60}) == {"guests": 0, "closed": True}
    assert outsider_orders({}) == {"guests": 1, "closed": False}
    assert tavern_factor({"outsiders": 100}) > tavern_factor({}) == 1 > tavern_factor({"outsiders": -100})


@test("Mining (0.96): low Mining mines no vein (a note says metal comes by trade); high mines bigger ones")
def _():
    s = geared(bars={"IRON": 10, "COPPER": 5})
    s["projects"]["open"] = []
    s["industry"] = {"ores": {"IRON": {"tiles": 12, "ore": "HEMATITE"}}}
    s["labor"] = labor(dig=0, miners=3)
    s["settings"]["traits"] = {"mining": -60}
    props, notes = plan(s, Memory())
    assert not by_rule(props, "ore") and any("no vein mined (metal by trade)" in n for n in notes), notes
    s["settings"]["traits"] = {"mining": 100}
    ore = by_rule(plan(s, Memory())[0], "ore")
    assert ore and ore[0].action["count"] == 80, ore
    s["military"]["gear"]["bars"] = {"IRON": 60, "COPPER": 10}       # 70 bars: enough at 0, not at +100
    assert by_rule(plan(s, Memory())[0], "ore")
    s["settings"]["traits"] = {}
    assert not by_rule(plan(s, Memory())[0], "ore")


@test("Surface (0.96): woodcutters and gatherers by Surface")
def _():
    s = fort()
    s["labor"] = labor(dig=0, shrubs=400, fish_water=0)
    s["labor"]["jobs"]["woodcutting"]["tools"] = 5
    s["labor"]["gather_marked"] = 3
    def jobs(v):
        s["settings"]["traits"] = {"surface": v}
        return {x.action["job"]: x.action["count"] for x in by_rule(plan(s, Memory())[0], "labor")}
    lo, hi = jobs(-100), jobs(100)
    assert lo.get("woodcutting") == 1 and hi.get("woodcutting") == 3, (lo, hi)
    assert lo.get("gathering", 0) < hi.get("gathering", 0), (lo, hi)


@test("Justice (0.96): no jail at -100; a harsh fort's jail sooner and bigger")
def _():
    s = fort()
    s["buildings"]["zones"].pop("Dungeon")
    s["offices"] = {"offices": {"SHERIFF": {"held": ["Urist"], "vacant": 0}}}
    jail = lambda st: [p for p in plan(st, Memory())[0] if p.action.get("kind") == "jail"]
    s["settings"]["traits"] = {"justice": -100}
    assert not jail(s)
    s["settings"]["traits"] = {"justice": 100}
    j = jail(s)
    assert j and j[0].action["cells"] == 8 and "Justice +100" in j[0].reason, j
    s["settings"]["traits"] = {"justice": -50}
    s["dwarves"]["total"] = 18                                          # 15 at 0, 21 at -50
    assert not jail(s)


@test("Deference (0.96): which rooms nobles are given; no suites when they get no office")
def _():
    s = fort()
    s["noble_rooms"] = {"nobles": [{"unit_id": 5, "name": "Urist", "office": "SHERIFF",
                                    "needs": ["bedroom", "office", "dining"]}],
                        "free": {"bedroom": 1, "office": 1, "dining": 1, "tomb": 0}}
    kinds = lambda: {p.action["kind"] for p in by_rule(plan(s, Memory())[0], "noble_rooms")}
    assert kinds() == {"bedroom", "office", "dining"}
    s["settings"]["traits"] = {"deference": -60}
    assert kinds() == {"bedroom"}
    s["settings"]["traits"] = {"deference": -100}
    assert kinds() == set()
    s["noble_rooms"]["free"] = {}
    assert not [p for p in plan(s, Memory())[0] if p.action.get("kind") == "suites"]
    # (0.100.2) the manager's office isn't a comfort: given, or dug, whatever Deference says
    s["noble_rooms"] = {"nobles": [{"unit_id": 6, "name": "Kib", "office": "MANAGER", "needs": ["office"]}],
                        "free": {"office": 1}}
    assert kinds() == {"office"}
    s["noble_rooms"]["free"] = {}
    su = [p for p in plan(s, Memory())[0] if p.action.get("kind") == "suites"]
    assert len(su) == 1 and su[0].action["suites"] == 1 and su[0].action.get("urgent") is True, [p.action for p in su]


@test("Greed (0.96): the trade margin, and a grasping fort keeps its treasures home")
def _():
    s = fort()
    s["trade"] = {"depot": True, "caravans": [{"civ": "the Mountainhomes", "state": "Approaching"}], "goods": 12,
                  "at_depot": 0}
    s["settings"]["traits"] = {"greed": 60}
    t = by_rule(plan(s, Memory())[0], "trade")
    assert t and t[0].action == {"type": "bring_goods", "count": 12, "keep_treasures": True}, t
    s["trade"] = {"depot": True, "caravans": [{"civ": "the Mountainhomes", "state": "AtDepot"}], "goods": 0,
                  "at_depot": 30, "screen": {"open": True, "ready": True, "by_ai": True}}
    s.setdefault("military", {}).setdefault("gear", {})["bars"] = {"IRON": 0}
    s["settings"]["traits"] = {"greed": -100}
    d = by_rule(plan(s, Memory())[0], "trade_deal")
    assert d and d[0].action["margin"] == 1.35, d


@test("Engineering (0.96): the cistern sooner or later; mechanisms kept spare from +50")
def _():
    from planner import _spare_mechanisms_rule
    s = fort()
    s["stocks"]["mechanisms"] = 1
    s["buildings"]["workshops"]["Mechanics"] = 1
    s["orders"] = []
    props = []
    _spare_mechanisms_rule(s, PLANNER_CONFIG, {"engineering": 100}, props)
    assert props and props[0].action == {"type": "work_order", "recipe": "mechanisms", "amount": 3}, props
    props = []
    _spare_mechanisms_rule(s, PLANNER_CONFIG, {"engineering": 40}, props)
    assert not props


@test("Outsiders (0.96): a closed fort's standing orders take no guests, hunters, mercenaries or citizens")
def _():
    from planner import petition_orders_wanted
    s = fort()
    s["settings"]["traits"] = {"militarism": 60, "growth": 100}
    open_ = petition_orders_wanted(s, PLANNER_CONFIG)
    assert open_["performer"] == 1 and open_["mercenary"] == 1, open_
    s["settings"]["traits"] = {"militarism": 60, "growth": 100, "outsiders": -60}
    shut = petition_orders_wanted(s, PLANNER_CONFIG)
    assert set(shut.values()) == {0}, shut
    s["settings"]["traits"] = {"outsiders": -40}
    assert petition_orders_wanted(s, PLANNER_CONFIG)["performer"] == 0


# --- (0.97) the Rules tab untangled -------------------------------------------

@test("Rules (0.97): 'Close gates and link levers' off leaves walls, doors and mapping going; no gate closed")
def _():
    s = entrances({"door_spots": 2, "width": 2}, {"door_spots": 0, "width": 6, "x": 40, "y": 50})
    s["settings"]["gate_lever"] = False
    p = plan(s, Memory())[0]
    assert by_rule(p, "gate_doors") and by_rule(p, "fortify"), rules(p)
    s = entrances({"sealed": True, "equipment": [{"id": 1, "kind": "door"}]})
    s["others_on_map"]["threats"] = [{"id": 900, "name": "Goblin", "can_reach_dwarves": True}]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    s["settings"]["gate_lever"] = False
    assert not by_rule(plan(s, Memory())[0], "gates")
    s = entrances(age_days=40)
    s["settings"]["gate_lever"] = False
    assert by_rule(plan(s, Memory())[0], "entrances")                  # still mapped


@test("Rules (0.97): the Temple level off, or Maintain, leaves temple petitions to you; guildhalls go on")
def _():
    s = fort()
    s["petitions"] = {"pending": [{"id": 174, "type": "Location", "loc": "TEMPLE", "tier": 1, "deity_hf": 55,
                                   "deity": "Rimtar", "days": 3},
                                  {"id": 175, "type": "Location", "loc": "GUILDHALL", "tier": 1, "profession": "MINER"}]}
    s["settings"]["levels"] = {"temple": False}
    props, notes = plan(s, Memory())
    p = by_rule(props, "petition_answer")
    assert p and p[0].action["id"] == 175, p
    assert any("temple petitions aren't answered or built while the Temple level is off" in n for n in notes), notes
    s["settings"]["levels"] = {}
    s["settings"]["fort_goal"] = "maintain"
    notes = plan(s, Memory())[1]
    assert any("temple petitions aren't answered or built while the fort's goal is Maintain" in n for n in notes), notes


@test("Rules (0.97): level_refused speaks for the switches, Maintain and Mining -100 (the strategist obeys it)")
def _():
    from planner import level_refused
    s = fort()
    assert level_refused(s, "library") is None and level_refused(s, "bedrooms") is None
    s["settings"]["levels"] = {"library": False}
    assert "off on the Rules tab" in level_refused(s, "library")
    s["settings"]["levels"] = {}
    s["settings"]["fort_goal"] = "maintain"
    assert "Maintain" in level_refused(s, "temple") and level_refused(s, "bedrooms") is None
    s["settings"]["fort_goal"] = "expand"
    s["settings"]["traits"] = {"mining": -100}
    assert "Mining is -100" in level_refused(s, "archery") and level_refused(s, "hospital") is None


@test("Rules (0.97): 'Smelt ore when metal runs low' off stops the AI's own smelting orders")
def _():
    s = geared(armed=3, bars={})
    s["buildings"]["furnaces"]["Smelter"] = 1
    s["supplies"]["fuel"] = 15
    s["industry"] = {"ores": {"IRON": {"tiles": 37, "ore": "MAGNETITE"}}, "ore_stock": 89,
                     "ore_stock_by": {"MAGNETITE": {"n": 29, "metals": ["IRON"]}}}
    assert by_rule(plan(s, Memory())[0], "smelt")
    s["settings"]["import_smelting"] = False
    assert not by_rule(plan(s, Memory())[0], "smelt")


@test("Rules (0.97): Growth's Now line says whether DF's own cap is set, and when Maintain holds it")
def _():
    import temperament
    s = fort()
    assert temperament.effects(s)["growth"].endswith("DF's cap set to it")
    s["settings"]["set_pop_cap"] = False
    assert temperament.effects(s)["growth"].endswith("DF's cap left to you")
    s["settings"]["fort_goal"] = "maintain"
    assert temperament.effects(s)["growth"].startswith("Maintain (Rules tab)")


# --- (0.98) the weighted ladder, set pieces, the plan keeps acting --------------------------

@test("ladder (0.98): neutral sliders keep the old order; temperament reorders the optional levels")
def _():
    from planner import ladder_score
    s = fort()
    c = PLANNER_CONFIG
    order = sorted(("tavern", "library", "barracks", "temple", "garden"),
                   key=lambda k: -ladder_score({"kind": k}, s, {}, c))
    assert order == ["tavern", "library", "barracks", "temple", "garden"], order
    mil = sorted(("tavern", "library", "barracks"), key=lambda k: -ladder_score({"kind": k}, s, {"militarism": 100}, c))
    assert mil[0] == "barracks", mil
    dev = sorted(("tavern", "library", "temple"), key=lambda k: -ladder_score({"kind": k}, s, {"piety": 100}, c))
    assert dev[0] == "temple", dev


@test("stairwells (0.104.82): one more for a district without one while the style asks more than the survey counts")
def _():
    import masterplan
    from planner import record
    s = fort()
    s["dwarves"]["total"] = 88
    s["settings"]["traits"] = {"spacing": 150, "industriousness": 100}
    m = Memory()
    m.atlas = {"survey": {"site": {"stairwells": 1}},
               "plan": {"spine": {"x": 60, "y": 60}, "districts": [
                   {"id": "homes", "kind": "homes", "name": "The Homes", "lo": 5, "hi": 7, "target": 6, "dirs": ["south"], "levels": [1]},
                   {"id": "halls", "kind": "halls", "name": "The Halls", "lo": 10, "hi": 12, "target": 11, "dirs": ["north"], "levels": []},
                   {"id": "industry", "kind": "industry", "name": "The Forges", "lo": 1, "hi": 3, "target": 2, "dirs": ["east", "west"], "levels": [4, 5]}]}}
    w = by_rule(plan(s, m)[0], "stairwell")
    assert w and w[0].action == {"type": "dig_stairwell", "dir": "east", "elev_lo": 1, "elev_hi": 3,
                                 "district": "industry", "spine": {"x": 60, "y": 60}}, w     # most levels first
    record([(w[0], {"ok": True, "x": 72, "y": 60, "elev_top": 5, "elev_bottom": 1})], s, m)
    assert masterplan.hint(m, "workshops")["spine"] == {"x": 72, "y": 60}                  # its levels grow from it
    assert masterplan.hint(m, "temple")["spine"] == {"x": 60, "y": 60}                     # the others: the main stair
    d = [x for x in m.atlas["plan"]["districts"] if x["id"] == "industry"][0]
    assert d["stair"] == {"x": 72, "y": 60}
    m.last_fired.pop("stairwell", None)
    w = by_rule(plan(s, m)[0], "stairwell")
    assert w and w[0].action["district"] == "halls", w                                      # the next one
    m.atlas["survey"]["site"]["stairwells"] = 4
    m.last_fired.pop("stairwell", None)
    assert not by_rule(plan(s, m)[0], "stairwell")                                          # enough
    s["settings"]["traits"] = {"fortification": 150, "verticality": 100}
    m.atlas["survey"]["site"]["stairwells"] = 1
    assert not by_rule(plan(s, m)[0], "stairwell")                                          # one great stair


@test("set pieces (0.98): the plan's great hall raised in good times, among the halls; then its place is filled")
def _():
    import masterplan
    m = Memory()
    m.atlas = {"plan": {"districts": [{"id": "halls", "kind": "halls", "name": "The Halls", "lo": 10, "hi": 12,
                                       "target": 11, "dirs": ["north"], "levels": []},
                                      {"id": "homes", "kind": "homes", "name": "The Homes", "lo": 5, "hi": 7,
                                       "target": 6, "dirs": ["south"], "levels": []}],
                        "slots": [{"kind": "great hall", "district": "halls"}], "spine": {"x": 1, "y": 1}}}
    assert masterplan.open_slot(m, "great hall")
    h = masterplan.hint(m, "dining", slot="great hall")
    assert h["district"] == "The Halls" and 10 <= h["elev_target"] <= 12, h
    assert masterplan.hint(m, "dining")["district"] == "The Homes"
    a = {"type": "start_project", "kind": "dining", "tables": 40, "set_piece": "great hall", "plan": h}
    masterplan.note_result(m, a, {"ok": True, "project_id": 77, "elevation": 11}, {})
    assert not masterplan.open_slot(m, "great hall") and m.atlas["plan"]["slots"][0]["built"] == 77


@test("the plan keeps acting (0.98): a new era's wing follows today's layout; Depth deepens it; grammar is today's")
def _():
    import masterplan
    m = Memory()
    m.atlas = {"plan": {"axis": "south", "pattern": "grid", "range": [0, 20], "era": 0,
                        "districts": [{"id": "homes", "kind": "homes", "name": "The Homes", "lo": 8, "hi": 10,
                                       "target": 9, "dirs": ["south"], "levels": [],
                                       "wings": [{"era": 0, "dir": "south"}]}],
                        "grammar": {"avenue": 1, "corridors": "straight", "doors": "open"}, "spine": {"x": 1, "y": 1}}}
    lines = masterplan.new_era(m, 1, {"layout": "branching"}, {"verticality": 60})
    d = m.atlas["plan"]["districts"][0]
    assert d["wings"][-1]["pattern"] == "branching" and d["lo"] == 7, (d, lines)
    assert "laid out branching" in lines[0] and "elevation 7" in lines[0], lines
    h = masterplan.hint(m, "bedrooms", traits={"grandeur": 80, "fortification": 60}, profile={})
    assert h["avenue"] == 3 and h["corridors"] == "dog-leg", h


@test("trade deal (0.100 review): a trade screen the player opened is left to them")
def _():
    s = fort()
    s["trade"] = {"caravans": [{"civ": "X", "state": "AtDepot"}], "depot": True, "goods": 50,
                  "at_depot": 30, "screen": {"open": True, "ready": True, "by_ai": False}}
    s["stocks"]["drink"] = 0
    props, notes = plan(s, Memory())[:2]
    assert not [p for p in props if p.rule == "trade_deal"], [p.rule for p in props]


@test("no date or dwarves in the report (0.100 review): nothing planned on made-up numbers")
def _():
    s = fort()
    del s["date"]
    props, notes = plan(s, Memory())[:2]
    assert props == [] and "no date" in notes[0], notes
    s = fort()
    s["dwarves"] = {"error": "boom"}
    props, notes = plan(s, Memory())[:2]
    assert props == [] and "dwarves" in notes[0], notes


@test("stuck orders (0.100.1 review): a cancelled stuck brew never holds the fort's own drink rule; another rule's brew is held")
def _():
    from planner import Proposal
    s = fort()
    m = Memory()
    m.stuck_cancelled = {"brew_drink": {"tick": abs_tick(s) - 1200}}
    ps = [Proposal("drink", {"type": "work_order", "recipe": "brew_drink", "amount": 5}, "x", 1, True),
          Proposal("booze_variety", {"type": "work_order", "recipe": "brew_drink", "amount": 5}, "x", 4, True)]
    allowed, held = select(ps, s, m, dict(PLANNER_CONFIG, max_actions_per_cycle=10))
    assert [p.rule for p in allowed] == ["drink"], (held, [p.rule for p in allowed])
    assert any(h.startswith("booze_variety: an order for brew_drink got stuck") for h in held), held


@test("siege behind a raised bridge (0.100.1 review): invaders who can't walk in keep the alarm and gates up")
def _():
    s = fort()
    s["others_on_map"]["threats"] = [{"id": 9, "name": "goblin", "invader": True, "can_reach_dwarves": False,
                                      "layer": "upper_levels"}]
    m = Memory()
    m.ai_alert_raised, m.quiet_cycles = True, 5
    note_cycle(s, m)
    assert m.quiet_cycles == 0, m.quiet_cycles
    s["others_on_map"]["threats"] = [{"id": 10, "name": "crundle", "can_reach_dwarves": False, "layer": "cavern 1"}]
    note_cycle(s, m)
    assert m.quiet_cycles == 1, m.quiet_cycles                     # a cavern creature doesn't hold the fort shut


@test("survival workshops (0.100.1, overnight run): still, kitchen, carpenter's first, a slot of their own; others bring them; no orders for missing shops")
def _():
    from planner import Proposal
    s = young_fort()
    s["buildings"]["workshops"] = {"Masons": 1, "Mechanics": 1, "MetalsmithsForge": 1}
    s["projects"]["open"] = [{"id": 1, "kind": "well", "phase": "furnish", "furnish": {"placed": 1, "done": 0, "waiting": {"Well": 1}}},
                             {"id": 4, "kind": "workshops", "phase": "dig", "summary": {"workshops": ["Fishery", "Butchers"]},
                              "dig": {"total": 74, "dug": 63, "stuck": 6, "digging": 0, "marked": 0},
                              "started": {"year": s["date"]["year"], "tick": max(0, s["date"]["tick"] - 30 * 1200)}}]
    props = plan(s, Memory())[0]
    b = [p for p in builds(props) if p.action.get("kind") == "workshops"]
    assert b and b[0].action["shops"][:3] == ["Still", "Kitchen", "Carpenters"], [p.action for p in builds(props)]
    assert any(p.action == {"type": "cancel_project", "project_id": 4} for p in props), [p.action for p in props]
    m = Memory()
    ps = [Proposal("drink", {"type": "work_order", "recipe": "brew_drink", "amount": 5}, "x", 1, True),
          Proposal("food", {"type": "work_order", "recipe": "prepare_fine_meal", "amount": 5}, "x", 1, True),
          Proposal("furniture", {"type": "work_order", "recipe": "wooden_bed", "amount": 5}, "x", 3, True),
          Proposal("blocks", {"type": "work_order", "recipe": "stone_blocks", "amount": 5}, "x", 3, True)]
    allowed, held = select(ps, s, m, dict(PLANNER_CONFIG, max_actions_per_cycle=10))
    assert [p.rule for p in allowed] == ["blocks"], held
    s2 = young_fort()
    s2["buildings"]["workshops"] = {"Carpenters": 1}
    got = [x for x in plan(s2, Memory())[0] if x.action.get("kind") == "workshops"]
    assert got and got[0].action["shops"][:2] == ["Still", "Kitchen"], [x.action for x in got]


@test("river crossings (0.101): the AI weighs each side; a narrow bridge early, a wider one when established, the old one down")
def _():
    def fort_with(near, far, mine=(), citizens=7, wealth=2000, wood=50):
        s = fort()
        s["dwarves"]["total"], s["dwarves"]["adults"] = citizens, citizens
        s["wealth"] = wealth
        s["stocks"]["wood"] = wood
        s["stocks"]["blocks"], s["stocks"]["boulders"] = 0, 0
        s["crossings"] = {"z": 90, "near": near, "mine": list(mine),
                          "crossings": [{"x": 50, "y": 50, "z": 90, "dir": "e", "len": 3, "width": 3, "dist": 10,
                                         "far_side": far}]}
        return s
    poor = {"trees": 2, "shrubs": 3, "grass": 400}
    rich = {"trees": 40, "shrubs": 120, "grass": 3000, "edge": True}
    cross = lambda s: [p.action for p in plan(s, Memory())[0] if p.rule == "crossing"]
    a = cross(fort_with(poor, rich))
    assert a and a[0]["type"] == "build_crossing" and a[0]["width"] == 1 and a[0]["kind"] == "cheap", a
    assert not cross(fort_with(rich, poor))                            # nothing worth the walk over there
    s = fort_with(poor, rich, wood=1)
    assert not cross(s) and any("waits for 3 logs" in n for n in plan(s, Memory())[1])
    mine = [{"index": 1, "kind": "cheap", "built": True}]
    assert not cross(fort_with(poor, rich, mine))                      # a young fort keeps the narrow one
    big = fort_with(poor, rich, mine, citizens=40, wealth=50000, wood=200)
    a = cross(big)
    assert a and a[0]["kind"] == "refined" and a[0]["width"] == 2, a
    big["settings"]["traits"] = {"grandeur": 60}
    assert cross(big)[0]["width"] == 3
    big["settings"]["traits"] = {"grandeur": -60}
    assert not cross(big)                                              # a plain fort keeps it plain
    done = fort_with(poor, rich, mine + [{"index": 2, "kind": "refined", "built": True}], citizens=40, wealth=50000)
    assert cross(done) == [{"type": "remove_crossing", "index": 1}], cross(done)


@test("orders that never start: approve after 3 days, a chair straight at a workshop after 5, no stuck-cancel churn")
def _():
    from planner import TICKS_PER_DAY, _approve_rule, _stuck_orders_rule
    s = fort()
    now = abs_tick(s)
    cfg = dict(PLANNER_CONFIG)
    s["orders"] = [{"id": 5, "recipe": "brew_drink", "amount_left": 10, "by_ai": True, "validated": False},
                   {"id": 6, "recipe": "stone_chair", "amount_left": 4, "by_ai": True, "validated": True}]
    m = Memory()
    m.order_watch = {"5": {"what": "brew_drink", "left": 10, "since": now - 2 * TICKS_PER_DAY, "by_ai": True},
                     "6": {"what": "stone_chair", "left": 4, "since": now - 2 * TICKS_PER_DAY, "by_ai": True}}
    p = []
    _approve_rule(s, m, cfg, p, [])
    assert not p, p
    for w in m.order_watch.values():
        w["since"] = now - 30 * TICKS_PER_DAY
    _approve_rule(s, m, cfg, p, [])
    assert {x.rule for x in p} == {"approve_orders", "bootstrap_chair"}, p
    p = []
    _stuck_orders_rule(s, m, cfg, p)
    assert not p, p                                                   # nothing started: not "stuck", no churn
    s["orders"][1]["active"] = True
    p = []
    _approve_rule(s, m, cfg, p, [])
    assert [x.rule for x in p] == ["approve_orders"], p               # one started: the manager works


@test("appointed nobles the game can't see are put on its duty lists")
def _():
    from planner import _sync_offices_rule
    s = fort()
    p = []
    _sync_offices_rule(s, p)
    assert not p
    s["offices"] = {"offices": {}, "unlisted": 6}
    _sync_offices_rule(s, p)
    assert [x.action for x in p] == [{"type": "sync_offices"}], p


@test("military: an army bigger than Militarism wants is trimmed, a few at a time, only while quiet")
def _():
    s = fort()
    s["settings"]["traits"] = {"militarism": -60}                     # ~7% of 194 = 14
    s["military"]["soldiers"] = 49
    t = by_rule(plan(s, Memory())[0], "squad_trim")
    assert t and t[0].action == {"type": "squad_trim", "count": 2}, t
    s["military"]["soldiers"] = 17                                    # within the margin
    assert not by_rule(plan(s, Memory())[0], "squad_trim")
    s["military"]["soldiers"] = 49
    s["settings"]["fill_squads"] = False                              # yours: left alone
    assert not by_rule(plan(s, Memory())[0], "squad_trim")
    s["settings"]["fill_squads"] = True
    s["others_on_map"]["threats"] = [{"id": 5, "name": "goblin", "can_reach_dwarves": True}]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    assert not by_rule(plan(s, Memory())[0], "squad_trim")           # not with enemies about


@test("a devout fort with its temple raises one to the god most long to pray to; one more per 50 Piety")
def _():
    from planner import more_temple
    cfg = dict(PLANNER_CONFIG)
    s = fort()
    s["needs"] = {"needs": {}, "deities": {"Teshkad": 6, "Tobul": 2}, "deity_ids": {"Teshkad": 77, "Tobul": 78}}
    s["locations"] = {"list": [{"type": "TEMPLE", "deity_hf": 12}]}
    assert more_temple(s, {"piety": 0}, cfg) is None                  # not devout
    assert more_temple(s, {"piety": 60}, cfg) == ("Teshkad", 77, 6)
    s["locations"]["list"].append({"type": "TEMPLE", "deity_hf": 77})
    assert more_temple(s, {"piety": 60}, cfg) is None                  # two temples is enough at 60
    s["locations"]["list"].pop()
    s["needs"]["deities"]["Teshkad"] = 3
    assert more_temple(s, {"piety": 150}, cfg) is None                 # too few long for him


@test("drink short (0.102.2): one waiting brew job gets a brewer; the stills' feeder piles first")
def _():
    from planner import _labor_waiting_rule, _feeder_rule
    cfg = dict(PLANNER_CONFIG)
    lb = {"waiting": [{"labor": "BREWER", "jobs": 1, "holders": 4, "idle": 0}]}
    p = []
    _labor_waiting_rule(lb, 100, cfg, p)
    assert not p
    _labor_waiting_rule(lb, 100, cfg, p, True)
    assert p and p[0].action == {"type": "assign_labor", "job": "BREWER", "count": 1}, p
    s = fort()
    s["logistics"] = {"feeders": [{"kind": "Masons", "id": 1, "what": "stone"}, {"kind": "Still", "id": 2, "what": "plants"}]}
    s["stocks"]["drink"] = 10 ** 6
    p = []
    _feeder_rule(s, cfg, p)
    assert p and p[0].action["building_id"] == 1, p
    s["stocks"]["drink"] = 0
    p = []
    _feeder_rule(s, cfg, p)
    assert p and p[0].action["building_id"] == 2, p


@test("farms (0.102.3): bare surface plots (nothing in season to sow there) don't count toward the farm target")
def _():
    from planner import _farm_rule
    cfg = dict(PLANNER_CONFIG)
    s = fort()
    s["dwarves"]["total"] = 17
    s["farms"] = {"tiles": 42, "plots": 6, "plots_underground": 2, "plots_surface": 4, "crops": {
        "PLUMP": {"brews": "plant", "seeds": 57, "seasons": ["spring"], "underground": True},
        "PLUM": {"brews": "growth", "seeds": 20, "seasons": [], "underground": False}}}
    s["projects"] = {"open": [], "max_open": 2}
    m = Memory()
    p = []
    _farm_rule(s, m, {}, 17, cfg, p, [])
    assert p and p[0].action["type"] == "farm_plots" and "nothing to sow" in p[0].reason, p
    s["farms"]["crops"]["WHEAT"] = {"seeds": 30, "seasons": ["summer"], "underground": False}
    p = []
    _farm_rule(s, m, {}, 17, cfg, p, [])
    assert not p, p


@test("stress care (0.102.4): a miserable soldier leaves the squad (not its leader, not under threat); else a free bedroom")
def _():
    s = fort()
    s["needs"] = {"needs": {}, "stressed": [
        {"id": 7, "name": "Urist", "stress": "miserable", "unmet": [], "bedroom": False, "squad": True}]}
    s["noble_rooms"] = {"free": {"bedroom": 2}}
    p = by_rule(plan(s, Memory())[0], "stress_care")
    assert p and p[0].action == {"type": "squad_release", "unit_id": 7}, p
    s["needs"]["stressed"][0]["leader"] = True
    p = by_rule(plan(s, Memory())[0], "stress_care")
    assert p and p[0].action == {"type": "give_room", "unit_id": 7, "kind": "bedroom"}, p
    s["needs"]["stressed"][0]["bedroom"] = True
    assert not by_rule(plan(s, Memory())[0], "stress_care")
    s["needs"]["stressed"][0].update(stress="very_unhappy", bedroom=False, leader=None)
    assert not by_rule(plan(s, Memory())[0], "stress_care")          # only at Welfare 50+
    s["settings"]["traits"] = {"welfare": 60}
    assert by_rule(plan(s, Memory())[0], "stress_care")


@test("quick locations (0.102.5): no temple or tavern while dwarves long for one: the dining hall becomes one")
def _():
    from planner import _quick_location_rule
    cfg = dict(PLANNER_CONFIG)
    s = fort()
    s["buildings"].setdefault("zones", {})["DiningHall"] = 1
    s["locations"] = {"count": {}, "list": []}
    s["needs"] = {"needs": {"PrayOrMeditate": {"distracted": 7}, "MakeMerry": {"distracted": 5}}}
    p = []
    _quick_location_rule(s, cfg, p, {"levels": {}})
    assert [x.action for x in p] == [{"type": "quick_location", "kind": "temple"}], p
    s["locations"]["count"] = {"TEMPLE": 1}
    p = []
    _quick_location_rule(s, cfg, p, {"levels": {}})
    assert [x.action for x in p] == [{"type": "quick_location", "kind": "tavern"}], p
    p = []
    _quick_location_rule(s, cfg, p, {"levels": {"tavern": False}})
    assert not p


@test("grandeur (0.102.6): a grand, fed fort puts statues in its plainest hall; made when none is free")
def _():
    from planner import _grandeur_rule
    cfg = dict(PLANNER_CONFIG)
    s = fort()
    s["settings"]["traits"] = {"grandeur": 60}
    s["stocks"]["drink"] = 10 ** 5
    s["locations"] = {"list": [{"type": "TEMPLE", "zones": [5], "value": 4000},
                               {"type": "INN_TAVERN", "zones": [6], "value": 900}]}
    s["supplies"]["statues"] = 2
    p = []
    _grandeur_rule(s, cfg, p, [])
    assert p, "a grand, fed fort with two free statues proposes nothing"
    assert p[0].action == {"type": "place_in_zone", "zone_id": 6, "what": "statue"}, p
    s["settings"]["traits"] = {"grandeur": 0}
    p = []
    _grandeur_rule(s, cfg, p, [])
    assert not p


@test("site and story quirks (0.103): Thirst-scarred keeps a third more drink; Frozen Hold stocks from midsummer")
def _():
    from planner import winter_factor
    s = fort()
    s["stocks"]["drink"] = 0
    m = Memory()
    a = by_rule(plan(s, m)[0], "drink")
    m.culture = {"quirks": {"thirst_scarred": {"year": 1}}}
    b = by_rule(plan(s, m)[0], "drink")
    assert a and b and "target of" in b[0].reason
    ta = int(a[0].reason.split("target of ")[1].split()[0].strip("(),"))
    tb = int(b[0].reason.split("target of ")[1].split()[0].strip("(),"))
    assert tb > ta * 1.25, (ta, tb)
    s["date"]["season"] = "summer"
    m2 = Memory()
    assert winter_factor(s, m2) == 1.0
    m2.culture = {"quirks": {"frozen_hold": {"year": 1}}}
    assert winter_factor(s, m2) > 1.0


@test("ghosts (0.103.1): a tomb level of its own slot while the dead walk; Haunted keeps twice the tombs")
def _():
    from planner import tombs_short
    s = fort()
    s["dead"] = {"free_tombs": 0, "unburied": 3, "ghosts": 3}
    # (13c) both building slots taken (with one free the plain tombs rule came first, and this was never seen)
    s["projects"]["open"] = [{"id": i, "kind": k, "phase": "dig", "dig": {"total": 100, "dug": 10, "stuck": 0}}
                             for i, k in ((1, "bedrooms"), (2, "dining"))]
    p = by_rule(plan(s, Memory())[0], "tombs_ghosts")
    assert p and p[0].action["kind"] == "tombs" and p[0].action["urgent"] is True, p
    m = Memory()
    a = tombs_short(s, 18, dict(PLANNER_CONFIG), m)
    m.culture = {"quirks": {"haunted": {"year": 1}}}
    assert tombs_short(s, 18, dict(PLANNER_CONFIG), m) == 2 * a


@test("thirst (0.103.1): a second still while drink is under the urgent line, young fort or not")
def _():
    from planner import _bottleneck_rule
    cfg = dict(PLANNER_CONFIG)
    s = fort()
    s["buildings"]["workshops"] = {"Still": 1, "Kitchen": 1}
    s["orders"] = [{"id": 1, "recipe": "brew_drink", "amount_left": 18, "by_ai": True},
                   {"id": 2, "recipe": "brew_drink_from_fruit", "amount_left": 10, "by_ai": True}]
    s["dwarves"]["idle_adults"] = 0
    s["stocks"]["drink"] = 10 ** 5
    p = []
    _bottleneck_rule(s, cfg, 18, p)
    assert not p, p                                  # no idle hands, not thirsty
    s["stocks"]["drink"] = 3
    _bottleneck_rule(s, cfg, 18, p)
    assert p and p[0].action["shops"] == ["Still"] and p[0].action.get("urgent"), p


@test("designed quirks (0.103.2): Mead Hall, Scholars' Hold and Ancestor Halls lift their hall in the ladder")
def _():
    from planner import ladder_score
    s = fort()
    m = Memory()
    base = {k: ladder_score({"kind": k}, s, {}, dict(PLANNER_CONFIG), m) for k in ("tavern", "library", "memorial")}
    m.culture = {"quirks": {"mead_hall": {}, "scholars_hold": {}, "ancestor_halls": {}}}
    for k in base:
        assert ladder_score({"kind": k}, s, {}, dict(PLANNER_CONFIG), m) == base[k] + 2, k


@test("brew churn (0.103.4): a brew source whose order was cancelled as stuck isn't ordered again at once")
def _():
    s = fort()
    s["stocks"]["drink"] = 500           # (0.105.26) short but not urgent: an urgent fort waits for nothing
    s["supplies"]["brewable_plants"], s["supplies"]["brewable_growths"] = 0, 30
    m = Memory()
    d = by_rule(plan(s, m)[0], "drink")
    assert d and d[0].action["recipe"] == "brew_drink_from_fruit", d
    m.stuck_cancelled = {"brew_drink_from_fruit": {"tick": abs_tick(s)}}
    assert not by_rule(plan(s, m)[0], "drink")


@test("Merchant Princes (0.103.5): each caravan traded with is counted; the quirk doubles the crafts kept for them")
def _():
    from planner import record, Proposal
    s = fort()
    m = Memory()
    m.culture = {}
    p = Proposal("trade", {"type": "trade_deal", "wants": []}, "x", 2)
    record([(p, {"ok": True, "traded": True})], s, m)
    record([(p, {"ok": True, "traded": False})], s, m)
    assert m.culture.get("trades") == 1, m.culture

@test("urgent hospital (0.103.8): dwarves waiting for care, both slots taken: a hospital with a slot of its own")
def _():
    s = settled_fort()
    s["locations"] = {"count": {}, "total": 0}
    s["projects"] = {"max_open": 2, "open": [
        {"id": 21, "kind": "tombs", "phase": "furnish", "summary": {"coffins": 6}},
        {"id": 23, "kind": "workshops", "phase": "dig", "summary": {"workshops": ["Farmers", "Loom"]}}]}
    s["health"] = {"hospital": [], "patients": [{"id": 1, "needs": ["diagnosis"]}, {"id": 2, "needs": []}]}
    assert not [x for x in builds(plan(s, Memory())[0]) if x.action["kind"] == "hospital"]   # one waits: no
    s["health"]["patients"][1]["needs"] = ["diagnosis"]
    h = [x for x in builds(plan(s, Memory())[0]) if x.action["kind"] == "hospital"]
    assert h and h[0].action["urgent"] is True and "2 dwarves wait for care" in h[0].reason, h
    s["locations"] = {"count": {"HOSPITAL": 1}, "total": 1}                             # one stands: no
    assert not [x for x in builds(plan(s, Memory())[0]) if x.action["kind"] == "hospital"]
    s["locations"] = {"count": {}, "total": 0}
    s["projects"]["open"].append({"id": 24, "kind": "bedrooms", "phase": "dig", "summary": {}})  # one extra slot taken
    assert [x for x in builds(plan(s, Memory())[0]) if x.action["kind"] == "hospital"]       # (0.104.12) two extra
    s["projects"]["open"].append({"id": 25, "kind": "well", "phase": "dig", "summary": {}})      # both extra slots taken
    assert not [x for x in builds(plan(s, Memory())[0]) if x.action["kind"] == "hospital"]


@test("hospital too small (0.104.121): the wounded rest on a 5-bed hospital's floor in a big fort: another, by beds, in bad times too")
def _():
    s = settled_fort()
    s["dwarves"]["total"] = 296
    s["locations"] = {"count": {"HOSPITAL": 1}, "total": 1}
    s["projects"] = {"max_open": 2, "open": [
        {"id": 21, "kind": "tombs", "phase": "furnish", "summary": {"coffins": 6}},
        {"id": 23, "kind": "workshops", "phase": "dig", "summary": {"workshops": ["Farmers"]}}]}
    s["health"] = {"hospital": [{"id": 4, "zones": [{"id": 287, "beds": 5}]}], "patients": [],
                   "resting": 107, "resting_in_hospital": 106}                     # Teacheroar, 31 Oct
    hosp = lambda: [x for x in builds(plan(copy.deepcopy(s), Memory())[0]) if x.action["kind"] == "hospital"]
    h = hosp()
    assert h and h[0].action["urgent"] is True and h[0].action["beds"] == 20, h       # wants 30, has 5
    assert "107 wounded dwarves resting" in h[0].reason and "wants 30" in h[0].reason, h[0].reason
    s["health"]["resting"] = 8                                                        # 3 without a bed: no
    assert not hosp()
    s["health"]["resting"] = 14                                                       # 9 without a bed: up to 17
    h = hosp()
    assert h and h[0].action["beds"] == 12 and "wants 17" in h[0].reason, h
    s["health"]["resting"] = 107
    s["health"]["hospital"][0]["zones"].append({"id": 300, "beds": 25})               # 30 beds: the most it wants
    assert not hosp()
    s["health"]["hospital"][0]["zones"].pop()
    s["projects"]["open"].append({"id": 24, "kind": "hospital", "phase": "dig", "summary": {}})   # one coming
    assert not hosp()
    s["projects"]["open"].pop()
    del s["health"]["resting"]                                                       # an older bridge: listed patients
    s["health"]["patients"] = [{"id": i, "needs": ["dressing"]} for i in range(12)]
    assert hosp()


@test("true counts (0.104.133): care waiting, the long waits and the miserable counted in full, not from the capped lists")
def _():
    from planner import care_waiting, patient_waits
    s = settled_fort()
    s["health"] = {"patients": [{"id": 1, "needs": ["dressing"]}], "waiting": 79, "waiting_ids": list(range(1, 80))}
    assert care_waiting(s) == 79
    m = Memory()
    since = patient_waits(s, m, abs_tick(s))
    assert len(since) == 79, len(since)                         # every waiting patient tracked, not only the listed
    s["needs"] = {"needs": {}, "stressed": [{"id": 5, "name": "Urist", "stress": "miserable", "unmet": ["Argue"]}]}
    s["dwarves"]["stress"] = {"miserable": 94, "very_unhappy": 48}
    notes = plan(copy.deepcopy(s), Memory())[1]
    assert any("94 dwarf(s) are miserable" in n for n in notes), [n for n in notes if "miserable" in n]


@test("dining by tables (0.104.135): a hall too few tables for the fort: another, its own slot; none while half are there")
def _():
    s = settled_fort()
    s["dwarves"]["total"] = 227
    s["buildings"]["zones"]["DiningHall"] = 1
    s["buildings"]["other"]["Table"] = 19                              # Teacheroar, 31 Oct
    s["projects"] = {"max_open": 2, "open": [
        {"id": 21, "kind": "tombs", "phase": "furnish", "summary": {"coffins": 6}},
        {"id": 174, "kind": "hospital", "phase": "dig", "summary": {}}]}
    dn = lambda: [x for x in builds(plan(copy.deepcopy(s), Memory())[0]) if x.action["kind"] == "dining"]
    d = dn()
    assert d and d[0].action["tables"] == 40 and d[0].action["urgent"] is True and "19 tables for 227" in d[0].reason, d
    s["buildings"]["other"]["Table"] = 40                              # over half of 76
    assert not dn()
    s["buildings"]["other"]["Table"] = 19
    s["projects"]["open"].append({"id": 180, "kind": "dining", "phase": "dig", "summary": {}})
    assert not dn()


@test("crisis mode (0.104.137): unhappiness, deaths or ghosts -> expansion waits, recovery first with extra slots; ends with margin")
def _():
    from planner import note_cycle, select, Proposal
    import crisis
    s = settled_fort()
    pop = s["dwarves"]["total"]
    s["dwarves"]["stress"] = {"miserable": int(pop * 0.5), "very_unhappy": int(pop * 0.2), "content": pop - int(pop * 0.7)}
    m = Memory()
    notes = note_cycle(copy.deepcopy(s), m)
    assert m.crisis.get("why") and any(n.startswith("CRISIS") for n in notes), (m.crisis, notes)
    lib = Proposal("build", {"type": "start_project", "kind": "library", "bookcases": 6}, "a library", 6)
    hosp = Proposal("build", {"type": "start_project", "kind": "hospital", "beds": 20, "urgent": True}, "x", 1)
    hall = Proposal("build", {"type": "start_project", "kind": "dining", "tables": 90, "set_piece": "great hall"}, "x", 6)
    bury = Proposal("burial", {"type": "allow_burial"}, "x", 5)
    pol = Proposal("polish", {"type": "polish"}, "x", 7)
    out_notes = []
    kept = crisis.apply([lib, hosp, hall, bury, pol], m.crisis["why"], out_notes)
    assert hosp in kept and bury in kept and lib not in kept and hall not in kept and pol not in kept, kept
    assert bury.priority == 3 and any("expansion step" in n for n in out_notes)
    # extra action slots for recovery
    props = [Proposal(r, {"type": "work_order", "recipe": r, "amount": 1}, "x", 4) for r in
             ("soap", "cloth", "needs_trinkets", "needs_meal", "slabs", "coffins", "convict")]
    allowed, held = select(props, s, m)
    assert len(allowed) == 7, (len(allowed), held)          # all 7: 3 + 5 extra
    m2 = Memory()
    assert len(select([Proposal(p.rule, p.action, "x", 4) for p in props], s, m2)[0]) == 3   # no crisis: 3
    # clears only under the clear levels and after 14 days
    s["dwarves"]["stress"] = {"miserable": int(pop * 0.3), "content": pop - int(pop * 0.3)}   # 30%: above 25
    note_cycle(copy.deepcopy(s), m)
    assert m.crisis.get("why"), "30% is still over the clear level"
    s["dwarves"]["stress"] = {"miserable": int(pop * 0.1), "content": pop - int(pop * 0.1)}
    note_cycle(copy.deepcopy(s), m)
    assert m.crisis.get("since"), "under 14 days: held"
    s["date"]["tick"] += 15 * 1200
    notes = note_cycle(copy.deepcopy(s), m)
    assert not m.crisis and any("crisis is over" in n for n in notes), (m.crisis, notes)
    # deaths and ghosts start one too
    s["dead"] = dict(s.get("dead") or {}, ghosts=6)
    note_cycle(copy.deepcopy(s), m)
    assert m.crisis.get("why") and "6 ghosts" in m.crisis["why"]
    m3 = Memory()
    crisis.note_deaths(s, m3, [{"kind": "death", "own_civ": True}] * 6 + [{"kind": "death", "own_civ": True, "again": True}])
    assert crisis.deaths_recent(s, m3) == 6


@test("taverns and temples by need (0.104.137): many badly missing friends, drink or prayer -> another, own slot; craft shops by need")
def _():
    from planner_building import social_shortfall
    s = settled_fort()
    s["dwarves"]["total"] = 221
    s["locations"] = {"count": {"INN_TAVERN": 2, "TEMPLE": 2}, "total": 4}
    s["needs"] = {"needs": {"BeWithFriends": {"badly": 85, "distracted": 150}, "DrinkAlcohol": {"badly": 56},
                            "PrayOrMeditate": {"badly": 63}}}
    got = dict(social_shortfall(s, PLANNER_CONFIG))
    assert set(got) == {"tavern", "temple"} and "BeWithFriends 150 distracted (85 badly)" in got["tavern"], got
    s["locations"]["count"]["INN_TAVERN"] = 3
    assert "4 wanted" in dict(social_shortfall(s, PLANNER_CONFIG))["tavern"]  # (0.104.146) 1 + 150 // 40 = 4
    s["locations"]["count"]["INN_TAVERN"] = 4
    assert "tavern" not in dict(social_shortfall(s, PLANNER_CONFIG))       # enough
    s["needs"]["needs"]["PrayOrMeditate"]["badly"] = 20                    # under 15% of the fort
    assert not social_shortfall(s, PLANNER_CONFIG)
    s["locations"]["count"] = {}                                           # none yet: the ladder's job
    s["needs"]["needs"]["PrayOrMeditate"]["badly"] = 63
    assert not social_shortfall(s, PLANNER_CONFIG)
    # craft shops: one per 8 wanting to craft, up to a shop per 15 dwarves (not a fixed 8)
    f = fort()
    f["dwarves"]["total"] = 221
    f["projects"] = {"open": [], "max_open": 2}
    f["buildings"]["workshops"]["Craftsdwarfs"] = 8
    f["needs"] = {"needs": {"CraftObject": {"distracted": 118}}, "craft_shops": 8, "idle_crafting": {"workshops": 8}}
    c = by_rule(plan(copy.deepcopy(f), Memory())[0], "needs_shops")
    assert c and len(c[0].action["shops"]) == 7, c                         # 1 + 118 // 8 = 15


@test("needs at the fort's size (0.104.137): trinkets made in half the wanting, given a quarter; metal finery without stone; no brewing on plenty")
def _():
    s = fort()
    s["orders"] = []
    s["dwarves"]["total"] = 221
    s["needs"] = {"needs": {"AcquireObject": {"distracted": 166}, "BeExtravagant": {"distracted": 76}}, "trinkets": 30}
    s["stone_use"] = {"usable": 2, "economic": {}}
    s["stocks"]["wood"] = 525
    s["buildings"]["workshops"]["MetalsmithsForge"] = 2
    s.setdefault("military", {}).setdefault("gear", {})["all_bars"] = {"COPPER": 33, "IRON": 39}
    p = plan(copy.deepcopy(s), Memory())[0]
    g = by_rule(p, "needs_trinkets")
    assert g and g[0].action == {"type": "give_trinkets", "max": 41}, g             # 166 // 4
    o = by_rule(p, "trinket_orders")
    assert o and o[0].action == {"type": "work_order", "recipe": "wood_crafts", "amount": 60}, o   # 30 free < 41: more made
    f = by_rule(p, "needs_finery")
    assert f and f[0].action["recipe"].startswith("metal_") and f[0].action["material"] == "INORGANIC:COPPER", f
    s["needs"]["trinkets"] = 50                                                    # enough free: none made
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "trinket_orders")


@test("urgent tombs (0.104.12): many dead unburied with both slots taken: a tomb level of its own slot, beside urgent workshops")
def _():
    s = settled_fort()
    s["projects"] = {"max_open": 2, "open": [
        {"id": 21, "kind": "well", "phase": "dig", "summary": {}},
        {"id": 23, "kind": "suites", "phase": "furnish", "summary": {}}]}
    s["dead"] = {"free_tombs": 7, "ghosts": 0, "unburied": 35}
    s["locations"]["count"]["TEMPLE"] = 1                          # (no urgent shrine ahead of it)
    t = by_rule(plan(s, Memory())[0], "tombs_ghosts")
    assert t and t[0].action["urgent"] is True and "35 dead unburied" in t[0].reason, t
    s["dead"]["unburied"] = 3
    assert not by_rule(plan(s, Memory())[0], "tombs_ghosts")


@test("slots held for good (0.104.12): a dig under half done in a year given up (a cavern well never again); statues-only finished without stone")
def _():
    s = settled_fort()
    now = s["date"]
    old = {"year": now["year"] - 2, "tick": now["tick"]}
    s["projects"] = {"max_open": 2, "open": [
        {"id": 25, "kind": "well", "phase": "dig", "started": old, "summary": {"cavern": True},
         "dig": {"dug": 2, "total": 24, "digging": 1}},
        {"id": 42, "kind": "suites", "phase": "furnish", "started": old,
         "furnish": {"days": 257, "waiting": {"Statue": 4}}}]}
    s["stone_use"] = {"usable": 0, "economic": {}}
    pj = by_rule(plan(s, Memory())[0], "project")
    acts = [p.action for p in pj]
    # (0.105.26) 2 of 24 dug: slow, not unreached (a cavern well given up as slow stays revivable)
    assert {"type": "cancel_project", "project_id": 25, "cavern_well": True} in acts, acts
    assert {"type": "finish_project", "project_id": 42, "decor_only": True} in acts, acts
    from planner import record, Proposal
    m = Memory()
    record([(Proposal("project", {"type": "cancel_project", "project_id": 25, "cavern_well": True}, "x", 4), {"ok": True})], s, m)
    assert "given up" in m.cavern_well_failure
    s["stone_use"]["usable"] = 50                                    # stone to carve: still finished after 112 days (0.104.33)
    assert {"type": "finish_project", "project_id": 42, "decor_only": True} in [p.action for p in by_rule(plan(s, Memory())[0], "project")]
    s["projects"]["open"][1]["furnish"]["days"] = 80                  # stone and under 112 days: the statues are waited for
    assert {"type": "finish_project", "project_id": 42, "decor_only": True} not in [p.action for p in by_rule(plan(s, Memory())[0], "project")]


@test("winter thirst (0.104.13): the old shaft's give-up cleared once; the well urgent while the hurt or parched wait")
def _():
    s = fort()
    s["buildings"]["other"].pop("Well", None)
    s["dwarves"]["needs_medical_care"] = 3
    s["projects"] = {"max_open": 2, "open": [{"id": 43, "kind": "tombs", "phase": "dig"},
                                             {"id": 44, "kind": "workshops", "phase": "dig"}]}
    m = Memory()
    m.well_failure = "no open drop from a free floor inside the fort to clean water (the water below is in a cavern)"
    m.cavern_well_failure = "the last cavern well's shaft was under half dug in a game year: given up"
    w = by_rule(plan(s, m)[0], "well")
    assert w and w[0].action == {"type": "place_well", "cavern": True, "urgent": True, "gallery": 80}, w     # both slots full: urgent
    assert m.cavern_well_failure == "" and m.cavern_shaft_stairs is True
    m.cavern_well_failure = "the last cavern well's shaft was under half dug in a game year: given up"
    assert not any(p.action.get("cavern") for p in by_rule(plan(s, m)[0], "well")), "cleared once only"
    # nobody hurt or parched and the slots full: it waits for a slot
    s["dwarves"]["needs_medical_care"] = 0
    s.setdefault("society", {})["parched"] = 0
    m2 = Memory()
    props, notes = plan(s, m2)
    assert not by_rule(props, "well") and any("waiting for a free building slot" in n for n in notes), notes
    # the parched alone make it urgent too
    s["society"]["parched"] = 12
    w = by_rule(plan(s, Memory())[0], "well")
    assert w and w[0].action.get("urgent") and "12 parched" in w[0].reason, w


@test("winter thirst (0.104.13): a water source zone the game says is dry or frozen is said")
def _():
    s = fort()
    s["buildings"]["other"].pop("Well", None)
    s["buildings"]["zones"]["WaterSource"] = 1
    s["recent_announcements"] = [{"text": "Led Obokrinal, Dwarven Child cancels Give water: No water source.",
                                  "type": "CANCEL_JOB"}]
    notes = plan(s, Memory())[1]
    assert any("water source zone gives no water" in n for n in notes), notes
    s["recent_announcements"] = []
    assert not any("water source zone gives no water" in n for n in plan(s, Memory())[1])


@test("suspended order jobs (0.104.13): the AI's resumed; a player's never; the stuck note says what its job does")
def _():
    s = fort()
    s["bridge_version"] = "0.104.13"
    s["orders"] = [{"id": 1573, "job": "MakeBucket", "recipe": "wooden_bucket", "by_ai": True, "active": True,
                    "amount_left": 1, "validated": True, "jobs": {"n": 1, "suspended": 1, "working": 0}},
                   {"id": 9, "job": "MakeChair", "by_ai": False, "active": True, "amount_left": 1, "validated": True,
                    "jobs": {"n": 1, "suspended": 1, "working": 0}}]
    u = by_rule(plan(s, Memory())[0], "unsuspend")
    assert len(u) == 1 and u[0].action == {"type": "unsuspend_orders"} and "wooden_bucket" in u[0].reason, u
    s["orders"][0]["jobs"]["suspended"] = 0
    assert not by_rule(plan(s, Memory())[0], "unsuspend"), "a player's suspended job is left alone"
    from planner import order_job_state, jobs_reported
    assert "suspended" in order_job_state({"by_ai": True, "jobs": {"n": 1, "suspended": 1}})
    assert "no job made" in order_job_state({"by_ai": True, "active": True})
    assert "a dwarf is on it" in order_job_state({"by_ai": True, "jobs": {"n": 1, "suspended": 0, "working": 1}})
    assert jobs_reported(s) and not jobs_reported({"bridge_version": "0.104.12"})
    # the watchdog names it
    m = Memory()
    now = abs_tick(s)
    m.order_watch["1573"] = {"left": 1, "since": now - 20 * 1200, "by_ai": True, "what": "wooden_bucket",
                             "job": "MakeBucket"}
    s["orders"][0]["jobs"]["suspended"] = 1
    notes = plan(s, m)[1]
    assert any("wooden_bucket" in n and "suspended" in n for n in notes), notes


@test("0.105.13 trade by the slider: more goods a caravan, treasures kept by a grasping fort; none from a closed one")
def _():
    s = fort()
    s["trade"] = {"depot": True, "caravans": [{"civ": "the Mountainhomes", "state": "Approaching"}], "goods": 327,
                  "at_depot": 0}
    s["settings"]["traits"] = {"trade": 120, "greed": 80}
    t = by_rule(plan(s, Memory())[0], "trade")
    # (0.105.33) a grasping trading fort keeps its treasures too (Greed was off in the Merchant city)
    assert t and t[0].action["count"] > 40 and t[0].action.get("keep_treasures") is True, t[0].action
    s["settings"]["traits"] = {"trade": 0, "greed": 80}
    t = by_rule(plan(s, Memory())[0], "trade")
    assert t[0].action == {"type": "bring_goods", "count": 40, "keep_treasures": True}, t[0].action
    s["settings"]["traits"] = {"trade": -100}
    p, notes = plan(s, Memory())
    assert not by_rule(p, "trade") and not by_rule(p, "call_trader"), [x.rule for x in p]
    assert any("doesn't trade" in n for n in notes), notes


@test("depot (0.103.9): goods left there after the caravans are taken out; trinkets kept home while wanted")
def _():
    s = fort()
    s["trade"] = {"depot": True, "caravans": [], "goods": 327, "at_depot": 163}
    u = by_rule(plan(s, Memory())[0], "unload_depot")
    assert u and u[0].action == {"type": "unload_depot", "max": 50} and "163" in u[0].reason, u
    s["trade"]["caravans"] = [{"civ": "the Mountainhomes", "state": "Approaching"}]
    p = plan(s, Memory())[0]
    assert not by_rule(p, "unload_depot")
    assert by_rule(p, "trade")[0].action == {"type": "bring_goods", "count": 40}
    full = copy.deepcopy(s)                                      # (0.104.78) goods piles full: 120 a call
    full.setdefault("logistics", {})["storage"] = {"finished_goods": {"tiles": 1522, "used": 1520, "loose": 166}}
    t = by_rule(plan(full, Memory())[0], "trade")
    assert t[0].action == {"type": "bring_goods", "count": 120} and "goods piles are full" in t[0].reason, t
    s["needs"] = {"needs": {"AcquireObject": {"distracted": 16}}, "trinkets": 0}
    assert by_rule(plan(s, Memory())[0], "trade")[0].action.get("keep_trinkets") is True
    s["needs"]["trinkets"] = 20                                  # a free one for each: they may go
    assert "keep_trinkets" not in by_rule(plan(s, Memory())[0], "trade")[0].action


@test("soldiers (0.103.9): a small fort longing to train gets more soldiers; the stress care keeps such a dwarf in")
def _():
    from planner import soldiers_wanted, _stress_care
    s = fort()
    s["needs"] = {"needs": {"MartialTraining": {"distracted": 23}}}
    s["settings"]["traits"] = {"militarism": 20}                 # (0.105.10) a keener fort: more of the extra
    base = soldiers_wanted({**s, "needs": {"needs": {}}}, 28, PLANNER_CONFIG)
    more = soldiers_wanted(s, 28, PLANNER_CONFIG)
    assert more > base and more <= round(28 * 0.3) + base, (base, more)
    s["settings"]["traits"] = {}
    assert soldiers_wanted(s, 12, PLANNER_CONFIG) == round(12 * 0.1)   # under 15 citizens: as before
    props = []
    worst = [{"id": 5, "name": "Erush", "stress": "miserable", "squad": True, "unmet": ["MartialTraining"]},
             {"id": 6, "name": "Adil", "stress": "miserable", "squad": True, "unmet": ["EatGoodMeal"]}]
    _stress_care(s, PLANNER_CONFIG, worst, props)
    assert props and props[0].action == {"type": "squad_release", "unit_id": 6}, [p.action for p in props]


@test("finery (0.103.10): dwarves wanting to be extravagant get jewellery to wear; trinkets made then are jewellery")
def _():
    s = fort()
    s["orders"] = []
    s["needs"] = {"needs": {"BeExtravagant": {"distracted": 13}}, "trinkets": 0}
    f = by_rule(plan(s, Memory())[0], "needs_finery")
    assert f and f[0].action["recipe"] in planner.JEWEL_RECIPES and f[0].action["amount"] == 13, f
    s["needs"]["trinkets"] = 20                                   # enough free ones already
    assert not by_rule(plan(s, Memory())[0], "needs_finery")
    s["needs"] = {"needs": {"BeExtravagant": {"distracted": 13}, "AcquireObject": {"distracted": 16}}, "trinkets": 0}
    p = plan(s, Memory())[0]
    t = by_rule(p, "trinket_orders")
    assert t and t[0].action["recipe"] in planner.JEWEL_RECIPES and not by_rule(p, "needs_finery"), (t, by_rule(p, "needs_finery"))
    s["needs"] = {"needs": {"AcquireObject": {"distracted": 16}}, "trinkets": 0}
    assert by_rule(plan(s, Memory())[0], "trinket_orders")[0].action["recipe"] == "stone_crafts"


@test("trinkets in wood (0.104.122): stone short, logs at hand: wooden crafts, not stone jewellery that never moves")
def _():
    s = fort()
    s["orders"] = []
    s["needs"] = {"needs": {"BeExtravagant": {"distracted": 196}, "AcquireObject": {"distracted": 228}}, "trinkets": 0}
    s["stone_use"] = {"usable": 2, "economic": {}}                  # Teacheroar, 31 Oct
    s["stocks"]["wood"] = 518
    p = plan(copy.deepcopy(s), Memory())[0]
    t = by_rule(p, "trinket_orders")
    assert t and t[0].action == {"type": "work_order", "recipe": "wood_crafts", "amount": 60}, t   # (0.104.137) 228 // 2, to 60
    assert "wooden crafts" in t[0].reason
    f = by_rule(p, "needs_finery")                                    # (0.104.137) worn finery in metal at the forge
    assert not f or f[0].action["recipe"].startswith("metal_"), f
    assert planner.recipe_shop("wood_crafts") == "Craftsdwarfs"
    s["orders"] = [{"id": 3, "recipe": "wood_crafts", "amount_left": 12, "by_ai": True}]    # being made
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "trinket_orders")
    s["orders"] = []
    s["stocks"]["wood"] = 10                                         # no logs either: the old way
    assert by_rule(plan(copy.deepcopy(s), Memory())[0], "trinket_orders")[0].action["recipe"] in planner.JEWEL_RECIPES


@test("Forge-born and Communal (0.103.11): furniture in spare metal; new sleeping quarters a dormitory")
def _():
    s = fort()
    s["buildings"]["other"]["Bed"] = 2
    m = Memory()
    m.culture = {"quirks": {"communal": {}}}
    b = [x for x in builds(plan(s, m)[0]) if x.action["kind"] == "bedrooms"]
    assert b and b[0].action.get("dormitory") is True and 4 <= b[0].action["rooms"] <= 20, [x.action for x in b]
    b = [x for x in builds(plan(s, Memory())[0]) if x.action["kind"] == "bedrooms"]
    assert b and "dormitory" not in b[0].action
    s = fort()
    s["orders"] = []
    s["projects"] = {"max_open": 2, "open": [{"id": 3, "kind": "bedrooms", "phase": "furnish",
                                               "furnish": {"waiting": {"Door": 4}}, "summary": {}}]}
    s["military"] = {"gear": {"forges": 1, "all_bars": {"SILVER": 60}}}
    s["supplies"]["fuel"] = 50
    def door(m):
        return [x.action for x in plan(s, m)[0] if x.action.get("recipe") in ("stone_door", "metal_door", "wooden_door")]
    assert door(Memory()) and door(Memory())[0]["recipe"] != "metal_door", door(Memory())
    m = Memory()
    m.culture = {"quirks": {"forge_born": {}}}
    assert door(m) and door(m)[0]["recipe"] == "metal_door" and door(m)[0]["material"] == "INORGANIC:SILVER", door(m)


@test("urgent temple (0.103.12): most of the fort longing to pray, only the stop-gap: a shrine with its own slot")
def _():
    s = settled_fort()
    s["dwarves"]["total"] = 40
    s["locations"] = {"count": {"TEMPLE": 1}, "total": 1}
    s["projects"] = {"max_open": 2, "open": [{"id": 1, "kind": "bedrooms", "phase": "furnish", "summary": {}},
                                             {"id": 2, "kind": "well", "phase": "dig", "summary": {}}]}
    s["needs"] = {"needs": {"PrayOrMeditate": {"distracted": 25}}}
    m = Memory()
    m.quick_locations = {"temple": {}}
    t = [x for x in builds(plan(s, m)[0]) if x.action["kind"] == "temple"]
    assert t and t[0].action == {"type": "start_project", "kind": "temple", "size": "shrine", "urgent": True}, t
    assert not [x for x in builds(plan(s, Memory())[0]) if x.action["kind"] == "temple"]   # a real temple stands
    s["needs"]["needs"]["PrayOrMeditate"]["distracted"] = 12                               # under half: the ladder's
    assert not [x for x in builds(plan(s, m)[0]) if x.action["kind"] == "temple"]


@test("stress care (0.103.12): a release the game refused isn't asked again: the free bedroom comes next")
def _():
    from planner import _stress_care, note_refusal, Proposal
    s = fort()
    s["noble_rooms"] = {"free": {"bedroom": 2}}
    worst = [{"id": 6, "name": "Ber", "stress": "miserable", "squad": True, "bedroom": False, "unmet": ["EatGoodMeal"]}]
    m = Memory()
    props = []
    _stress_care(s, PLANNER_CONFIG, worst, props, m)
    assert props[0].action["type"] == "squad_release", props
    note_refusal(m, props[0], {"ok": False, "rejected": True, "error": "longs to fight or train"}, abs_tick(s))
    props = []
    _stress_care(s, PLANNER_CONFIG, worst, props, m)
    assert props and props[0].action == {"type": "give_room", "unit_id": 6, "kind": "bedroom"}, [p.action for p in props]


@test("stop-gap temple (0.103.13): one the bridge marks as laid over the dining hall isn't real, memory or not")
def _():
    s = settled_fort()
    s["dwarves"]["total"] = 40
    s["locations"] = {"count": {"TEMPLE": 1}, "total": 1,
                      "list": [{"id": 0, "type": "TEMPLE", "zones": [135], "over_dining": True}]}
    s["projects"] = {"max_open": 2, "open": [{"id": 1, "kind": "bedrooms", "phase": "furnish", "summary": {}},
                                             {"id": 2, "kind": "well", "phase": "dig", "summary": {}}]}
    s["needs"] = {"needs": {"PrayOrMeditate": {"distracted": 25}}}
    t = [x for x in builds(plan(s, Memory())[0]) if x.action["kind"] == "temple"]
    assert t and t[0].action.get("urgent"), t
    s["locations"]["list"][0]["over_dining"] = False
    assert not [x for x in builds(plan(s, Memory())[0]) if x.action["kind"] == "temple"]


@test("good cooks (0.103.14): a full store and no good meals: only the best cooks cook; any cook once it runs down")
def _():
    s = fort()
    s["orders"] = []
    pop = s["dwarves"]["total"]
    s["needs"] = {"needs": {"EatGoodMeal": {"distracted": 30}}}
    s["stocks"]["prepared_meals"] = pop * 30
    s["supplies"].update(meal_servings=pop * 30, good_meals=0, cooks={"best": 6, "skilled": 2, "kitchen_min": 0})
    g = by_rule(plan(s, Memory())[0], "good_cooks")
    assert g and g[0].action == {"type": "kitchen_skill", "min_level": 4}, g
    s["supplies"]["cooks"]["kitchen_min"] = 4                         # already so: nothing
    assert not by_rule(plan(s, Memory())[0], "good_cooks")
    s["stocks"]["prepared_meals"] = pop * 2                           # the store ran down: any cook
    g = by_rule(plan(s, Memory())[0], "good_cooks")
    assert g and g[0].action == {"type": "kitchen_skill", "min_level": 0}, g
    s["stocks"]["prepared_meals"] = pop * 30
    s["supplies"]["cooks"] = {"best": 2, "skilled": 0, "kitchen_min": 0}   # nobody skilled: no limit
    assert not by_rule(plan(s, Memory())[0], "good_cooks")
    # (0.104.19) the best cook gone: the kitchens at 9+, the best now 7: down to 5 at once
    s["supplies"]["cooks"] = {"best": 7, "skilled": 2, "kitchen_min": 9}
    g = by_rule(plan(s, Memory())[0], "good_cooks")
    assert g and g[0].action == {"type": "kitchen_skill", "min_level": 5} and g[0].priority == 2, g
    s["supplies"]["cooks"] = {"best": 2, "skilled": 0, "kitchen_min": 9}    # nobody skilled left: any cook
    g = by_rule(plan(s, Memory())[0], "good_cooks")
    assert g and g[0].action == {"type": "kitchen_skill", "min_level": 0}, g


@test("good cooks (0.105.8): two free cooks must clear the kitchens' bar; one alone, or soldiers, open it again")
def _():
    s = fort()
    s["orders"] = []
    pop = s["dwarves"]["total"]
    s["needs"] = {"needs": {"EatGoodMeal": {"distracted": 30}}}
    s["stocks"]["prepared_meals"] = pop * 30
    s["supplies"].update(meal_servings=pop * 30, good_meals=0)
    # two free cooks at 8 and 5: the bar goes to 5 (the second's), not 6
    s["supplies"]["cooks"] = {"best": 8, "skilled": 2, "kitchen_min": 0, "able_skills": [8, 5, 1]}
    g = by_rule(plan(s, Memory())[0], "good_cooks")
    assert g and g[0].action == {"type": "kitchen_skill", "min_level": 5}, g
    # one free cook at 8 (the other skilled ones are soldiers): no bar raised
    s["supplies"]["cooks"] = {"best": 8, "skilled": 1, "kitchen_min": 0, "able_skills": [8, 1]}
    assert not by_rule(plan(s, Memory())[0], "good_cooks")
    # the six forts: kitchens at 6+, one free cook that good: any cook again, at once
    s["supplies"]["cooks"] = {"best": 8, "skilled": 1, "kitchen_min": 6, "able_skills": [8, 2, 0]}
    g = by_rule(plan(s, Memory())[0], "good_cooks")
    assert len(g) == 1 and g[0].action == {"type": "kitchen_skill", "min_level": 0} and g[0].priority == 2, g
    # kitchens at 3+, free cooks 4 and 3: kept
    s["supplies"]["cooks"] = {"best": 4, "skilled": 0, "kitchen_min": 3, "able_skills": [4, 3]}
    assert not by_rule(plan(s, Memory())[0], "good_cooks")
    # no free cook at all (an empty list from the bridge may come as a dict)
    s["supplies"]["cooks"] = {"best": 0, "skilled": 0, "kitchen_min": 3, "able_skills": {}}
    g = by_rule(plan(s, Memory())[0], "good_cooks")
    assert g and g[0].action == {"type": "kitchen_skill", "min_level": 0}, g


@test("Gem-mad and Nobles' Pride (0.103.15): treasures kept home; every noble's rooms whatever the Deference")
def _():
    from planner import keeps_treasures, noble_room_kinds
    m = Memory()
    assert not keeps_treasures({}, m) and noble_room_kinds({"deference": -60}, m) == ("bedroom",)
    m.culture = {"quirks": {"gem_mad": {}, "nobles_pride": {}}}
    assert keeps_treasures({}, m)
    assert noble_room_kinds({"deference": -60}, m) == ("bedroom", "office", "dining", "tomb")
    assert noble_room_kinds({"deference": -100}, m) == ()            # at its lowest: still nothing
    s = fort()
    s["trade"] = {"depot": True, "caravans": [{"civ": "the Mountainhomes", "state": "Approaching"}], "goods": 12,
                  "at_depot": 0}
    assert by_rule(plan(s, m)[0], "trade")[0].action.get("keep_treasures") is True


@test("memorial slabs (0.103.16): engraved slabs lying unbuilt while ghosts walk are put up; blank ones made otherwise")
def _():
    s = fort()
    s["orders"] = []
    s["dead"] = {"ghosts": 3, "ghost_names": ["Avuz"], "free_tombs": 5}
    s["tools"] = {"autoslab": True}
    s["supplies"].update(slabs=5, memorial_slabs=3)
    p = by_rule(plan(s, Memory())[0], "slabs")
    assert p and p[0].action == {"type": "place_slabs", "max": 3}, p
    s["supplies"].update(slabs=1, memorial_slabs=0)
    p = by_rule(plan(s, Memory())[0], "slabs")
    assert p and p[0].action["recipe"] == "stone_slab", p


@test("Superstitious (0.103.17): the urgent shrine at a quarter of the fort longing to pray, not half")
def _():
    s = settled_fort()
    s["dwarves"]["total"] = 40
    s["locations"] = {"count": {"TEMPLE": 1}, "total": 1, "list": [{"id": 0, "type": "TEMPLE", "over_dining": True}]}
    s["projects"] = {"max_open": 2, "open": [{"id": 1, "kind": "bedrooms", "phase": "furnish", "summary": {}},
                                             {"id": 2, "kind": "well", "phase": "dig", "summary": {}}]}
    s["needs"] = {"needs": {"PrayOrMeditate": {"distracted": 12}}}
    assert not [x for x in builds(plan(s, Memory())[0]) if x.action["kind"] == "temple"]
    m = Memory()
    m.culture = {"quirks": {"superstitious": {}}}
    assert [x for x in builds(plan(s, m)[0]) if x.action["kind"] == "temple"]


@test("the last seven quirks (0.103.18): their effects in the planner")
def _():
    from planner import record, Proposal
    # Hermit Kingdom: nothing to the depot, no broker; the depot still emptied
    s = fort()
    s["trade"] = {"depot": True, "caravans": [{"civ": "the Mountainhomes", "state": "Approaching"}], "goods": 12, "at_depot": 0}
    m = Memory()
    m.culture = {"quirks": {"hermit_kingdom": {}}}
    p, notes = plan(s, m)
    assert not by_rule(p, "trade") and not by_rule(p, "call_trader") and any("hermit" in n for n in notes)
    # the last trade's year is kept for it
    m = Memory()
    m.culture = {}
    record([(Proposal("trade", {"type": "trade_deal", "wants": []}, "x", 2), {"ok": True, "traded": True})], s, m)
    assert m.culture.get("last_trade_year") == s["date"]["year"], m.culture
    # Waste Not: small storage rooms
    s = fort()
    s["buildings"]["stockpiles"] = 0
    s["buildings"]["other"]["Bed"] = 1000
    s["buildings"]["zones"]["DiningHall"] = 1
    m = Memory()
    m.culture = {"quirks": {"waste_not": {}}}
    st = [x for x in builds(plan(s, m)[0]) if x.action["kind"] == "storage"]
    assert st and st[0].action["room_size"] == 5, [x.action for x in builds(plan(s, m)[0])]
    # Living Walls: polish at half the idle share
    s = fort()
    s["dwarves"].update(idle_adults=20, adults=100)
    assert not by_rule(plan(s, Memory())[0], "polish")
    m = Memory()
    m.culture = {"quirks": {"living_walls": {}}}
    assert by_rule(plan(s, m)[0], "polish")


@test("tombs (0.104.101): the bodies a hauler can take count, not the unburied minus outside and out of reach twice")
def _():
    from planner import tombs_short, PLANNER_CONFIG
    s = fort()
    s["dead"] = {"unburied": 27, "free_tombs": 0, "why": {"free": 9, "forbidden": 0, "in_job": 0, "carried": 0,
                                                            "outside": 14, "unreachable": 18, "not_ours": 0, "dump": 0}}
    want = max(PLANNER_CONFIG["min_free_tombs"], -(-90 * PLANNER_CONFIG["free_tombs_per_dwarf"] // 1)) + 9
    assert tombs_short(s, 90, PLANNER_CONFIG) >= 9, tombs_short(s, 90, PLANNER_CONFIG)
    s["dead"]["why"].pop("free")                                          # an older bridge: the old count
    assert tombs_short(s, 90, PLANNER_CONFIG) < tombs_short(dict(s, dead=dict(s["dead"], why={"free": 9})), 90, PLANNER_CONFIG)


@test("caverns (0.104.101): an open cavern's note says where the dwarves' ground meets it")
def _():
    s = fort()
    s["deep"] = {"caverns": [{"name": "Cavern1", "discovered": True, "open": True, "z_bottom": 135, "z_top": 143,
                              "open_at": {"x": 91, "y": 100, "z": 135}}], "dangers": [], "cursed": []}
    notes = plan(s, Memory())[1]
    assert any("Cavern1 is open" in n and "x91 y100 z135" in n for n in notes), [n for n in notes if "Cavern" in n]


@test("furniture (0.104.141): a slow stone order -> part in wood beside it; none when the masons keep up or no carpenters")
def _():
    s = fort()
    s["stocks"]["wood"] = 659
    s["buildings"]["workshops"]["Masons"] = 5
    s["buildings"]["workshops"]["Carpenters"] = 3
    s["projects"]["open"] = [{"id": 176, "kind": "dining", "phase": "furnish",
                              "furnish": {"days": 93, "waiting": {"Table": 30}}}]
    s["orders"] = [{"id": 6380, "recipe": "stone_table", "job": "ConstructTable", "by_ai": True, "active": True,
                    "amount_left": 49, "amount_total": 60}]
    f = by_rule(plan(s, Memory())[0], "furniture")
    assert f and f[0].action == {"type": "work_order", "recipe": "wooden_table", "amount": 24}, [x.action for x in f]
    s["orders"][0]["amount_left"] = 12                    # 12 on 5 workshops: they keep up
    assert not [x for x in by_rule(plan(s, Memory())[0], "furniture") if x.action.get("recipe") == "wooden_table"]
    s["orders"][0]["amount_left"] = 49
    s["orders"].append({"id": 7, "recipe": "wooden_table", "by_ai": True, "amount_left": 10})
    assert not [x for x in by_rule(plan(s, Memory())[0], "furniture") if x.action.get("recipe") == "wooden_table"]
    s["orders"].pop()
    s["buildings"]["workshops"].pop("Carpenters")
    assert not [x for x in by_rule(plan(s, Memory())[0], "furniture") if x.action.get("recipe") == "wooden_table"]


@test("project (0.104.141): furnished but for a building never finished, 30+ days -> finished (stalled); not sooner")
def _():
    s = fort()
    s["projects"]["open"] = [{"id": 175, "kind": "hospital", "phase": "furnish",
                              "started": {"year": s["date"]["year"] - 1, "tick": s["date"]["tick"]},
                              "furnish": {"days": 134, "done": 30, "placed": 31, "waiting": []}}]
    acts = [x.action for x in by_rule(plan(s, Memory())[0], "project")]
    assert {"type": "finish_project", "project_id": 175, "stalled": True} in acts, acts
    s["projects"]["open"][0]["furnish"]["days"] = 10
    acts = [x.action for x in by_rule(plan(s, Memory())[0], "project")]
    assert not any(a.get("stalled") for a in acts), acts
    s["projects"]["open"][0]["furnish"].update(days=134, waiting={"Bed": 1})
    acts = [x.action for x in by_rule(plan(s, Memory())[0], "project")]
    assert not any(a.get("stalled") for a in acts), acts


@test("bottleneck (0.104.141): much furniture waiting -> Masons' workshops past the cap, at half the backlog")
def _():
    s = fort()
    s["dwarves"]["idle_adults"] = int(0.4 * s["dwarves"]["adults"])
    s["buildings"]["workshops"]["Masons"] = planner.shops_max(PLANNER_CONFIG, s["dwarves"]["total"])
    m_ = s["buildings"]["workshops"]["Masons"]
    s["projects"]["open"] = [{"id": 176, "kind": "dining", "phase": "furnish",
                              "furnish": {"days": 93, "waiting": {"Table": 30, "Chair": 21}}}]
    s["orders"] = [{"id": 1, "recipe": "stone_table", "job": "ConstructTable", "by_ai": True, "active": True,
                    "amount_left": 8 * m_, "amount_total": 60}]
    b = by_rule(plan(s, Memory())[0], "bottleneck")
    assert b and b[0].action["shops"] == ["Masons"], [x.action for x in b]
    s["projects"]["open"][0]["furnish"]["waiting"] = {"Table": 5}
    assert not by_rule(plan(s, Memory())[0], "bottleneck")


def _conv_body():
    s = fort()
    s["dwarves"]["total"] = 60
    s["offices"] = {"offices": {"SHERIFF": {"held": [{"id": 1}]}}}
    s["justice"] = {"jails": [{"id": 453, "chains": 5, "used": 4, "free": 3}], "restraints": 10, "restraints_used": 8,
                    "punish": {"n": 0, "beatings": 0}, "crimes": {"n": 900, "convictable": 99}}
    props, notes = plan(copy.deepcopy(s), Memory())
    assert by_rule(props, "jail_size"), [p.rule for p in props]
    c = by_rule(props, "convict")
    assert c and c[0].action["max"] == 1, c                          # 2 free, 1 kept spare
    s["justice"]["restraints_used"] = 9
    props, notes = plan(copy.deepcopy(s), Memory())
    assert not by_rule(props, "convict") and any("no spare place" in n for n in notes), notes
    s["justice"]["crimes"]["convictable"] = 2                        # few waiting: no hurry
    s["justice"]["restraints_used"] = 8
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "jail_size")


@test("jail (0.104.141, 12k): convicts waiting grow the jail once 1 spare place is left; no conviction into the last one")
def _():
    PLANNER_CONFIG["convict_on"] = True        # (0.104.147) off by default
    try:
        _conv_body()
    finally:
        PLANNER_CONFIG["convict_on"] = False


@test("trinkets (0.104.141): a slow trinket order -> a second beside it in bone (else wood); never a third")
def _():
    s = fort()
    s["orders"] = [{"id": 6382, "recipe": "stone_ring", "job": "MakeRing", "by_ai": True, "active": True,
                    "amount_left": 40, "amount_total": 60}]
    s["needs"] = {"needs": {"AcquireObject": {"distracted": 165}}, "trinkets": 0, "bones": 300,
                  "idle_crafting": {"enabled": True, "workshops": 8}, "craft_shops": 8}
    s["buildings"]["workshops"]["Craftsdwarfs"] = 8
    t_ = by_rule(plan(copy.deepcopy(s), Memory())[0], "trinket_orders")
    assert t_ and t_[0].action == {"type": "work_order", "recipe": "bone_crafts", "amount": 30}, [x.action for x in t_]
    s["needs"]["bones"] = 5
    s["stocks"]["wood"] = 5000
    t_ = by_rule(plan(copy.deepcopy(s), Memory())[0], "trinket_orders")
    assert t_ and t_[0].action["recipe"] == "wood_crafts", [x.action for x in t_]
    s["orders"].append({"id": 9, "recipe": "wood_crafts", "by_ai": True, "amount_left": 10})
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "trinket_orders")


@test("stuck orders (0.104.141): a dwarf at work on an order keeps it from being cancelled as stuck")
def _():
    s = fort()
    o = {"id": 6382, "recipe": "stone_ring", "job": "MakeRing", "by_ai": True, "active": True,
         "amount_left": 5, "amount_total": 20, "jobs": {"n": 5, "working": 1}}
    s["orders"] = [o]
    m = Memory()
    now = abs_tick(s)
    m.order_watch["6382"] = {"left": 5, "since": now - 40 * TICKS_PER_DAY, "by_ai": True, "what": "stone_ring"}
    note_cycle(copy.deepcopy(s), m)
    assert m.order_watch["6382"].get("worked") == now and m.order_watch["6382"]["since"] == now - 40 * TICKS_PER_DAY
    assert not by_rule(plan(copy.deepcopy(s), m)[0], "stuck_order")
    m2 = Memory()
    m2.order_watch["6382"] = {"left": 5, "since": now - 40 * TICKS_PER_DAY, "by_ai": True, "what": "stone_ring"}
    o["jobs"] = {"n": 5, "working": 0}
    assert by_rule(plan(copy.deepcopy(s), m2)[0], "stuck_order")


def _body():
    s = fort()
    s["water"] = dict(s.get("water") or {}, cistern_status={
        "v": 2, "stage": "linking", "gate": "shut", "lever": "built", "depth": 0, "relinks": 3,
        "lever_at": {"x": 109, "y": 38, "z": 168}, "gate_at": {"x": 110, "y": 40, "z": 160}})
    props, notes = plan(copy.deepcopy(s), Memory())
    # (0.105.35) nothing waits for the player: the link asked afresh, then the cistern retired
    c = by_rule(props, "cistern")
    assert [p.action for p in c] == [{"type": "cistern_step", "relink": True}], [p.action for p in c]
    assert not any(n.startswith(planner.NEEDS_YOU) and "cistern" in n for n in notes), notes
    s["water"]["cistern_status"]["relink_rounds"] = 2
    c = by_rule(plan(copy.deepcopy(s), Memory())[0], "cistern")
    assert [p.action.get("retire") for p in c] == [True], [p.action for p in c]
    s["water"]["cistern_status"]["relink_rounds"] = 0
    s["water"]["cistern_status"]["relinks"] = 1
    assert by_rule(plan(copy.deepcopy(s), Memory())[0], "cistern")
    s["water"]["cistern_status"].update(relinks=3, linked=True)
    assert by_rule(plan(copy.deepcopy(s), Memory())[0], "cistern")


@test("cistern (0.104.141): the lever's link lost 3 times -> asked afresh, then retired (0.105.35), no refused step each cycle")
def _():
    PLANNER_CONFIG["cistern_hold"] = False      # (0.104.144) the design under the hold
    try:
        _body()
    finally:
        PLANNER_CONFIG["cistern_hold"] = False


@test("wells (0.104.141, 12k): one well for every 70 dwarves; one at a time; a failure waits a season, never 'no well'")
def _():
    s = fort()
    s["dwarves"]["total"] = 209
    s["buildings"]["other"]["Well"] = 1
    s["projects"]["open"] = []
    m = Memory()
    w = by_rule(plan(copy.deepcopy(s), m)[0], "well")
    assert w and w[0].action == {"type": "place_well", "extra": True} and w[0].priority == 5, [x.action for x in w]
    record([(w[0], {"ok": False, "error": "no clean water inside the fort"})], s, m)
    assert m.extra_well_failure and not m.well_failure
    props, notes = plan(copy.deepcopy(s), m)
    assert not by_rule(props, "well") and any("share 1 well" in n for n in notes), notes
    s["buildings"]["other"]["Well"] = 4
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "well")
    s["buildings"]["other"]["Well"] = 1
    s["projects"]["open"] = [{"id": 9, "kind": "well", "phase": "dig"}]
    assert not [x for x in by_rule(plan(copy.deepcopy(s), Memory())[0], "well") if x.action.get("type") == "place_well"]


@test("well lids (0.104.151-152): the stair lid only where the shaft gate can't be built; hatch covers ordered")
def _():
    s = fort()
    s["others_on_map"]["threats"] = []
    lid = {"project_id": 203, "x": 95, "y": 102, "z": 169, "elevation": 41, "state": "none", "gate": "none_possible"}
    s["projects"]["well_lids"] = [lid]
    s.setdefault("entrances", {})["parts"] = {"hatch_covers": 0}
    acts = [x.action for x in by_rule(plan(copy.deepcopy(s), Memory())[0], "well_lid")]
    assert {"type": "seal_well_stairs"} in acts, acts
    assert any(a.get("recipe") == "stone_hatch_cover" and a.get("amount") == 1 for a in acts), acts
    s["entrances"]["parts"] = {"hatch_covers": 2}
    assert [x.action for x in by_rule(plan(copy.deepcopy(s), Memory())[0], "well_lid")] == [{"type": "seal_well_stairs"}]
    for state in ("planned", "locked"):
        lid["state"] = state
        assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "well_lid"), state
    lid["state"], lid["gate"] = "open", "open"                       # the gate stands: the lid stays unlocked
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "well_lid")
    lid["state"] = "open"
    lid["gate"] = "none_possible"
    assert by_rule(plan(copy.deepcopy(s), Memory())[0], "well_lid")[0].action == {"type": "seal_well_stairs"}


@test("people (0.104.159): a soldier with a baby goes home (not a leader); the syndromes named; children per stress")
def _():
    s = fort()
    s.setdefault("military", {})["soldier_mothers"] = [{"id": 7, "name": "Urist, Axedwarf", "leader": True},
                                                       {"id": 8, "name": "Ast, Wrestler"}, {"id": 9, "name": "Kib"}]
    s.setdefault("health", {}).update(syndromes=36, infected=82, syndrome_names={"alcohol": 30, "spider venom": 6})
    s.setdefault("needs", {})["stress_causes"] = {"causes": [{"thought": "SleptRoughFloor", "citizens": 6, "children": 4}]}
    props, notes = plan(copy.deepcopy(s), Memory())[:2]
    m = [p.action for p in props if p.rule == "mothers"]
    assert m == [{"type": "squad_release", "unit_id": 8, "mother": True}], m
    assert any("Urist, Axedwarf leads a squad and has a baby" in n for n in notes), notes
    assert any("36 citizens have a syndrome: alcohol (30), spider venom (6); 82 walk about" in n for n in notes), notes
    assert any("sleeping on the floor (6 citizens, 4 of them children)" in n for n in notes), notes
    s.setdefault("hazards", {}).update(miasma=29, miasma_spots=[{"n": 7, "x": 95, "y": 94, "z": 162,
                                                                "rotting": {"MEAT": 72, "CORPSE": 1}}])
    notes = plan(copy.deepcopy(s), Memory())[1]
    assert any("miasma: 29 clouds, the worst at x95 y94 z162, rotting near it: 72 meat, 1 corpse" in n for n in notes), notes
    del s["military"]["soldier_mothers"]
    assert not [p for p in plan(copy.deepcopy(s), Memory())[0] if p.rule == "mothers"]


@test("comfort (0.104.157): shoes for the barefoot in pairs (leather, else cloth), cups when dwarves drink without; the worst stresses said")
def _():
    s = fort()
    s["buildings"].setdefault("workshops", {}).update({"Leatherworks": 1, "Clothiers": 1, "Craftsdwarfs": 2})
    s["stocks"].update(leather=1325, cloth=35, wood=600)
    s.setdefault("needs", {})["stress_causes"] = {"causes": [
        {"thought": "NoShoes", "citizens": 75, "stress": 113, "emotion": "EMBARRASSMENT"},
        {"thought": "DrinkWithoutCup", "citizens": 149, "stress": 50, "emotion": "ANNOYANCE"}]}
    s["needs"]["clothing"] = {"citizens": 150, "without": {"shoes": 63, "legs": 7, "body": 4},
                              "free_shoes": 4, "free_cups": 0}
    def run(state):
        props, notes = plan(copy.deepcopy(state), Memory())[:2]
        return [x for x in props if x.rule == "comfort"], notes
    p, notes = run(s)
    acts = [x.action for x in p]
    assert {"type": "work_order", "recipe": "leather_shoes", "amount": 30} in acts, acts      # 61 pairs, 30 a batch
    cups = [a for a in acts if a.get("recipe") in ("stone_mugs", "wooden_cups")]
    assert cups and cups[0]["amount"] == 20, acts                                            # 50 wanted, 20 a batch
    assert any("no shoes (75 citizens)" in n and "drinking without a cup (149" in n for n in notes), notes
    shoes = [x for x in p if x.action.get("recipe") == "leather_shoes"][0]
    assert "63 of 150 citizens are barefoot (75 upset" in shoes.reason, shoes.reason
    s["orders"] = s.get("orders", []) + [{"recipe": "leather_shoes", "amount_left": 30, "active": True, "by_ai": True}]
    p, _ = run(s)
    assert not [x for x in p if x.action.get("recipe") in ("leather_shoes", "cloth_shoes")], [x.action for x in p]
    s["orders"] = []
    s["stocks"]["leather"] = 2                                             # no leather: cloth shoes
    p, _ = run(s)
    assert any(x.action.get("recipe") == "cloth_shoes" for x in p), [x.action for x in p]
    s["stocks"]["leather"] = 1325
    s["needs"]["clothing"]["free_shoes"] = 130                             # enough in store: a note, no order
    p, notes = run(s)
    assert not [x for x in p if "shoes" in x.action.get("recipe", "")], [x.action for x in p]
    assert any("130 shoes lie free" in n for n in notes), notes
    s["needs"]["clothing"]["free_cups"] = 60                               # enough cups
    s["needs"]["stress_causes"]["causes"] = s["needs"]["stress_causes"]["causes"][:1]
    p, _ = run(s)
    assert not p, [x.action for x in p]
    # Teacheroar 13:33: the cups made sit in the craftsdwarf's (finished goods full): storage, not cups
    s["needs"]["stress_causes"]["causes"].append({"thought": "DrinkWithoutCup", "citizens": 149, "stress": 50})
    s["needs"]["clothing"].update(free_cups=0, free_cups_detail={"n": 0, "place": {"workshop": 34}})
    p, notes = run(s)
    assert not [x for x in p if x.action.get("recipe") in ("stone_mugs", "wooden_cups")], [x.action for x in p]
    assert any("34 cups lie off the stockpiles" in n for n in notes), notes
    # (0.104.165) the piles have room and the cups still lie in the halls: not waited for, new ones made
    s.setdefault("logistics", {})["storage"] = {"finished_goods": {"tiles": 107, "used": 28, "loose": 28, "piles": 3}}
    s["needs"]["clothing"].update(free_cups=34, free_cups_detail={"n": 34, "place": {"zone DiningHall": 10,
                                                                                     "zone MeetingHall": 24}})
    p, notes = run(s)
    cup = [x for x in p if x.action.get("recipe") in ("stone_mugs", "wooden_cups")]
    assert cup and cup[0].action["amount"] == 20, [x.action for x in p]
    assert any("though the finished goods piles have room" in n for n in notes), notes
    s["logistics"]["storage"]["finished_goods"]["used"] = 105                # full: storage first again
    p, notes = run(s)
    assert not [x for x in p if x.action.get("recipe") in ("stone_mugs", "wooden_cups")]
    del s["logistics"]["storage"]
    # boots aren't worn by civilians: 20 free boots don't shoe anyone
    s["needs"]["clothing"].update(free_shoes=20, free_shoes_detail={"n": 20, "kinds": {"ITEM_SHOES_BOOTS": 20}})
    p, _ = run(s)
    assert {"type": "work_order", "recipe": "leather_shoes", "amount": 30} in [x.action for x in p], [x.action for x in p]
    del s["needs"]["clothing"]                                             # an older bridge: nothing
    assert run(s)[0] == []
    # finished goods left in their workshops count toward more storage
    st = {"finished_goods": {"tiles": 58, "used": 58, "loose": 39, "in_workshops": 34, "piles": 2}}
    s.setdefault("logistics", {})["storage"] = st
    assert "finished_goods" in planner.full_stores(s, PLANNER_CONFIG), planner.full_stores(s, PLANNER_CONFIG)
    st["finished_goods"].update(in_workshops=0, loose=5)
    assert "finished_goods" not in planner.full_stores(s, PLANNER_CONFIG)
    # Teacheroar 13:44: used cups on the halls' floors count too
    s["needs"]["clothing"] = {"free_cups_detail": {"place": {"zone MeetingHall": 24, "zone DiningHall": 10, "stockpile": 3}}}
    assert "finished_goods" in planner.full_stores(s, PLANNER_CONFIG)


@test("well shaft (0.104.156): two gates share the mechanisms; a link uses reachable ones; lost links wait; orders for all")
def _():
    s = fort()
    s["others_on_map"]["threats"] = []
    a = {"project_id": 218, "x": 115, "y": 44, "z": 154, "elevation": 26, "state": "none", "gate": "unlinked",
         "gate_hatch_built": True, "gate_hatch_standing": True, "gate_mechanisms": 3, "gate_mechanisms_reachable": 2}
    b = {"project_id": 224, "x": 79, "y": 43, "z": 157, "elevation": 29, "state": "none", "gate": "no_hatch",
         "gate_mechanisms": 3}
    s["projects"]["well_lids"] = [a, b]
    s["stocks"]["mechanisms"], s["stocks"]["mechanisms_free"] = 3, 3
    s.setdefault("entrances", {})["parts"] = {"hatch_covers": 2}
    def run(state):
        props, notes = plan(copy.deepcopy(state), Memory())[:2]
        return by_rule(props, "well_shaft"), notes
    p, _ = run(s)
    acts = [x.action for x in p]
    assert {"type": "well_shaft", "close": False} in acts, acts
    step = [x for x in p if x.action.get("type") == "well_shaft"][0]
    # Teacheroar 1 Nov: the link first; 224's hatch waits (3 mechanisms, 2 of them for the link)
    assert "link them" in step.reason and "hatch at the shaft's bottom" not in step.reason, step.reason
    assert {"type": "work_order", "recipe": "mechanisms", "amount": 1} in acts, acts    # 2 + 2 needed, 3 free
    a["gate_mechanisms_reachable"] = 1                                   # out of reach of 218's lever
    p, notes = run(s)
    assert all(x.action.get("type") != "well_shaft" for x in p), [x.action for x in p]
    assert any("out of reach of its lever" in n for n in notes), notes
    a["gate_mechanisms_reachable"], a["gate_link_lost"] = 2, 3           # DF cancelled the link 3 times
    p, notes = run(s)
    assert any("cancelled its lever link 3 times" in n for n in notes), notes
    assert all(x.action.get("type") != "well_shaft" for x in p), [x.action for x in p]
    s["stocks"]["mechanisms_free"], s["stocks"]["mechanisms_unwalkable_at"] = 1, "x92 y106 z168"
    p, notes = run(s)
    assert any("where no dwarf can walk (x92 y106 z168)" in n for n in notes), notes
    assert {"type": "work_order", "recipe": "mechanisms", "amount": 3} in [x.action for x in p], [x.action for x in p]
    s["stocks"]["mechanisms_free"] = 3
    del s["stocks"]["mechanisms_unwalkable_at"]
    a["gate_mechanisms"] = b["gate_mechanisms"] = 4                      # one more made: 224's hatch can go in
    p, _ = run(s)
    step = [x for x in p if x.action.get("type") == "well_shaft"]
    assert step and "hatch at the shaft's bottom" in step[0].reason, [x.reason for x in p]


@test("well shaft (0.104.152): lever, hatch, link, open; shut while a danger is near (60 tiles), open past 80")
def _():
    s = fort()
    s["others_on_map"]["threats"] = []
    lid = {"project_id": 218, "x": 115, "y": 44, "z": 154, "elevation": 26, "state": "none", "gate": "none"}
    s["projects"]["well_lids"] = [lid]
    s["stocks"]["mechanisms"] = 5
    s.setdefault("entrances", {})["parts"] = {"hatch_covers": 0}
    def shaft(state):
        return [x.action for x in by_rule(plan(copy.deepcopy(state), Memory())[0], "well_shaft")]
    def lidr(state):
        return [x.action for x in by_rule(plan(copy.deepcopy(state), Memory())[0], "well_lid")]
    assert shaft(s) == [{"type": "well_shaft", "close": False}], shaft(s)
    assert lidr(s) == []                                                # no lid while a gate can be built
    s["stocks"]["mechanisms"] = 1
    assert {"type": "work_order", "recipe": "mechanisms", "amount": 2} in shaft(s), shaft(s)
    s["stocks"]["mechanisms"] = 5
    lid["gate"] = "building"
    assert shaft(s) == []
    lid["gate"], lid["gate_mechanisms"] = "no_hatch", 1
    assert shaft(s) == [{"type": "work_order", "recipe": "mechanisms", "amount": 2}] or shaft(s) == [], shaft(s)
    assert any(a.get("recipe") == "stone_hatch_cover" for a in lidr(s)), lidr(s)
    lid["gate_mechanisms"] = 2
    assert shaft(s) == [{"type": "well_shaft", "close": False}], shaft(s)
    lid["gate"], lid["gate_hatch_built"] = "building", False
    assert any(a.get("recipe") == "stone_hatch_cover" for a in lidr(s)), lidr(s)
    lid["gate"] = "unlinked"
    assert shaft(s) == [{"type": "well_shaft", "close": False}]
    lid["gate"] = "open"
    assert shaft(s) == []
    beast = {"name": "Ubbul the Toad", "flier": False, "great_danger": True, "layer": "Cavern1",
             "pos": {"x": 150, "y": 60, "z": 130}}
    s["others_on_map"]["threats"] = [beast]
    p = by_rule(plan(copy.deepcopy(s), Memory())[0], "well_shaft")
    assert p and p[0].action == {"type": "well_shaft", "close": True} and "Ubbul" in p[0].reason and p[0].priority == 2
    beast["caged"] = True
    assert shaft(s) == []
    beast["caged"] = False
    beast["pos"] = {"x": 185, "y": 60, "z": 130}                       # 70 tiles: not near enough to shut
    assert shaft(s) == []
    lid["gate"] = "closed"
    assert shaft(s) == []                                              # but shut, it stays shut until past 80
    beast["pos"] = {"x": 200, "y": 60, "z": 130}
    assert shaft(s) == [{"type": "well_shaft", "close": False}]
    lid["gate"] = "open"
    beast["pos"], beast["layer"] = {"x": 116, "y": 44, "z": 145}, "upper_levels"   # in the shaft itself
    assert shaft(s) == [{"type": "well_shaft", "close": True}], shaft(s)
    beast["pos"] = {"x": 140, "y": 44, "z": 160}                       # elsewhere in the fort: not the shaft's
    assert shaft(s) == []
    lid["gate"] = "pulling"
    beast["pos"], beast["layer"] = {"x": 150, "y": 60, "z": 130}, "Cavern1"
    assert shaft(s) == [{"type": "well_shaft", "close": True}]          # a pull to open under way: called off
    # (review 2) nothing built while a danger is near (no dwarf sent down beside the opening)
    lid["gate"] = "none"
    assert shaft(s) == [], shaft(s)
    s["others_on_map"]["threats"] = []
    lid["gate"], lid["gate_mechanisms"] = "unlinked", 1                 # a link waits for 2 mechanisms
    assert shaft(s) == [], shaft(s)
    lid["gate_mechanisms"] = 2
    assert shaft(s) == [{"type": "well_shaft", "close": False}]
    # a failed hatch still at the bottom: no lid locked over the stairs the dwarf takes it away by
    lid.update(gate="none_possible", state="open", gate_hatch_standing=True)
    assert lidr(s) == [], lidr(s)
    lid.pop("gate_hatch_standing")
    assert lidr(s) == [{"type": "seal_well_stairs"}], lidr(s)
    # (0.104.153) hostile wild animals: a flier within 60, anything within 20; the watcher started again
    lid.update(gate="open", state="none", watching=True)
    s["others_on_map"]["threats"] = []
    s["others_on_map"]["wild_hostile"] = [{"name": "a giant cave spider", "pos": {"x": 145, "y": 44, "z": 130}}]
    assert shaft(s) == [], shaft(s)                                     # 30 tiles, walking
    s["others_on_map"]["wild_hostile"][0]["flier"] = True
    assert shaft(s) == [{"type": "well_shaft", "close": True}], shaft(s)
    s["others_on_map"]["wild_hostile"] = [{"name": "a crawler", "pos": {"x": 130, "y": 44, "z": 130}}]
    assert shaft(s) == [{"type": "well_shaft", "close": True}], shaft(s)   # 15 tiles
    s["others_on_map"]["wild_hostile"] = []
    lid["watching"] = False
    p = by_rule(plan(copy.deepcopy(s), Memory())[0], "well_shaft")
    assert p and p[0].action == {"type": "well_shaft", "close": False} and "watcher" in p[0].reason, [x.reason for x in p]


@test("free stock (0.104.155): mechanisms claimed by jobs don't count; an older bridge's count still does")
def _():
    from planner_core import free_stock
    s = fort()
    s["stocks"]["mechanisms"] = 3
    assert free_stock(s, "mechanisms") == 3                          # no _free from an older bridge
    s["stocks"]["mechanisms_free"] = 0
    assert free_stock(s, "mechanisms") == 0
    # the shaft gate's mechanisms order follows the free count
    s["others_on_map"]["threats"] = []
    s["projects"]["well_lids"] = [{"project_id": 218, "x": 115, "y": 44, "z": 154, "elevation": 26, "state": "none",
                                   "gate": "none"}]
    acts = [x.action for x in by_rule(plan(copy.deepcopy(s), Memory())[0], "well_shaft")]
    assert {"type": "work_order", "recipe": "mechanisms", "amount": 3} in acts, acts


@test("planned (0.104.154): the waiting well, hatches and levers said with what they lack and why")
def _():
    s = fort()
    s["planned"] = {"n": 12, "list": [
        {"kind": "Well", "x": 115, "y": 44, "z": 154, "elevation": 26, "suspended": True, "why": "Waiting for items",
         "items": [{"want": "Bucket (any material)", "queue": 3}, {"want": "Block (granite)"}]},
        {"kind": "Bed", "x": 1, "y": 1, "z": 1, "elevation": 1}]}
    notes = plan(copy.deepcopy(s), Memory())[1]
    n = [x for x in notes if "planned building(s) wait" in x]
    assert n and "Well at x115 y44 elevation 26: wants Bucket (any material) (queue 3); Block (granite); Waiting for items" in n[0], n
    assert "Bed" not in n[0]
    # what they lack is ordered from buildingplan's list, whatever the stock count says
    s["stocks"]["mechanisms"] = 3
    s["planned"]["list"] += [{"kind": "Trap", "x": 2, "y": 2, "z": 2, "elevation": 2, "items": [{"want": "1 Mechanism", "queue": 6}]},
                             {"kind": "Well", "x": 3, "y": 3, "z": 3, "elevation": 3,
                              "items": [{"want": "0 Block"}, {"want": "0 Bucket"}, {"want": "1 Mechanism", "queue": 5}]}]
    s["planned"]["list"][0]["items"] = [{"want": "0 Bucket"}]
    props = plan(copy.deepcopy(s), Memory())[0]
    acts = [x.action for x in by_rule(props, "planned_parts")]
    assert acts == [{"type": "work_order", "recipe": "mechanisms", "amount": 2}], acts
    s["orders"] = [{"job": "ConstructMechanisms", "recipe": "mechanisms", "amount_left": 2, "amount_total": 2, "by_ai": True}]
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "planned_parts")   # on order already: not again


@test("wells (0.104.148): another well can't be placed because the water is a cavern -> the cavern well")
def _():
    s = fort()
    s["dwarves"]["total"] = 163
    s["dwarves"]["needs_medical_care"] = 3
    s["buildings"]["other"]["Well"] = 1
    s["projects"]["open"] = []
    m = Memory()
    m.extra_well_failure = ("no open drop from a free floor inside the fort to clean water "
                            "(the water below is in a cavern)")
    m.last_fired["extra_well"] = abs_tick(s)
    w = by_rule(plan(copy.deepcopy(s), m)[0], "well")
    assert w and w[0].action == {"type": "place_well", "cavern": True, "urgent": True, "gallery": 80}, [x.action for x in w]
    assert w[0].priority == 1 and "share 1 well" not in w[0].reason and "injured" in w[0].reason, w[0].reason
    # its failure is the cavern well's (recorded as before), and then only said
    record([(w[0], {"ok": False, "error": "no floor inside the fort over cavern water with solid rock between; no gallery to the cavern water at x135 y131 elevation 7 (its nearest column is 81 tiles from the dwarves; a gallery reaches 40)"})], s, m)
    assert m.cavern_well_failure.startswith("no floor")
    props, notes = plan(copy.deepcopy(s), m)
    assert not by_rule(props, "well") and any("no cavern well either" in n for n in notes), notes
    # a danger about: not now, said
    m2 = Memory()
    m2.extra_well_failure = m.extra_well_failure
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    props, notes = plan(copy.deepcopy(s), m2)
    assert not by_rule(props, "well") and any("cavern well would help" in n for n in notes), notes
    # another reason for the failure: the season's wait as before
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    m3 = Memory()
    m3.extra_well_failure = "no clean water inside the fort"
    m3.last_fired["extra_well"] = abs_tick(s)
    assert not by_rule(plan(copy.deepcopy(s), m3)[0], "well")


def _body():
    s = fort()
    s["dwarves"]["total"] = 60
    s["offices"] = {"offices": {"SHERIFF": {"held": [{"id": 1}]}}}
    s["justice"] = {"jails": [{"id": 453, "chains": 30, "used": 28, "free": 3}], "restraints": 30, "restraints_used": 28,
                    "punish": {"n": 0, "beatings": 0}, "crimes": {"n": 900, "convictable": 99}}
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "jail_size")
    s = fort()
    s["water"] = dict(s.get("water") or {}, cistern_status={"v": 2, "stage": "linking", "relinks": 3, "link_pending": True})
    props, notes = plan(copy.deepcopy(s), Memory())
    assert by_rule(props, "cistern") and not any(n.startswith(planner.NEEDS_YOU) and "cistern" in n for n in notes)
    from planner_core import watch_since, WORKED_MAX_DAYS
    w = {"since": 0, "worked": 500 * TICKS_PER_DAY}
    assert watch_since(w) == WORKED_MAX_DAYS * TICKS_PER_DAY and watch_since({"since": 5}) == 5


@test("review (0.104.141): the jail stops growing at twice what the fort wants; the cistern waits on a pending link; worked delays 56 days at most")
def _():
    PLANNER_CONFIG["cistern_hold"] = False      # (0.104.144) the design under the hold
    try:
        _body()
    finally:
        PLANNER_CONFIG["cistern_hold"] = False


@test("woodcutters (0.104.142): more while wood is short; Elf-friends one, two while short and well under the quota")
def _():
    from quirks import has_rule
    s = fort()
    s["labor"] = labor(dig=0, fish_water=0)
    s["labor"]["jobs"]["woodcutting"]["tools"] = 10
    s["dwarves"]["total"] = 206
    def cut(m=None):
        return {x.action["job"]: x.action["count"] for x in by_rule(plan(copy.deepcopy(s), m or Memory())[0], "labor")}.get("woodcutting")
    s["stocks"]["wood"] = 5000
    assert cut() == 2
    s["stocks"]["wood"] = 112                                           # 300 short at 2 a dwarf
    assert cut() == 5, cut()
    m = Memory(culture={"quirks": {"elf_friends": {"since": 50}}})
    assert has_rule(m.culture, "elf_friends")
    assert cut(m) == 2
    s["stocks"]["wood"] = 5000
    assert cut(m) == 1


def _hold_body():
    s = fort()
    s["water"] = dict(s.get("water") or {}, cistern_status={"v": 2, "stage": "linking", "gate": "shut", "relinks": 3})
    props, notes = plan(copy.deepcopy(s), Memory())
    assert not by_rule(props, "cistern") and any("cistern is on hold" in n for n in notes), notes
    assert not any(n.startswith(planner.NEEDS_YOU) and "cistern" in n for n in notes)
    s["water"]["cistern_status"].update(stage="filling", gate="open")
    c = by_rule(plan(copy.deepcopy(s), Memory())[0], "cistern")
    assert c and c[0].action["type"] == "cistern_step" and "shut it" in c[0].reason, c


@test("cistern hold (0.104.144): no step and a note while the design is on hold")
def _():
    PLANNER_CONFIG["cistern_hold"] = True
    try:
        _hold_body()
    finally:
        PLANNER_CONFIG["cistern_hold"] = False


@test("cistern v2 (0.104.145): open and no longer closed -> shut at once; a second leak -> retired (0.105.35); the first design retired")
def _():
    s = fort()
    s["water"] = dict(s.get("water") or {}, cistern_status={"v": 2, "stage": "filling", "gate": "open", "depth": 3,
                                                            "sealed_now": False, "unsealed": "the shaft is open at x1 y2 elevation 3"})
    c = by_rule(plan(copy.deepcopy(s), Memory())[0], "cistern")
    assert c and c[0].action == {"type": "cistern_step", "shut": True} and c[0].priority == 0, [x.action for x in c]
    s["water"]["cistern_status"] = {"v": 2, "stage": "filling", "gate": "shut", "leak": "x5 y6 elevation 41"}
    props, notes = plan(copy.deepcopy(s), Memory())
    # (0.105.35) the first leak: a note (the bridge lets water in again once); the second: retired
    assert any("x5 y6 elevation 41" in n and "second leak retires it" in n for n in notes), notes
    assert not any(n.startswith(planner.NEEDS_YOU) and "cistern" in n for n in notes), notes
    assert not by_rule(props, "cistern")
    s["water"]["cistern_status"]["leaks"] = 2
    c = by_rule(plan(copy.deepcopy(s), Memory())[0], "cistern")
    assert c and c[0].action.get("retire") is True and "x5 y6" in c[0].action["why"], [x.action for x in c]
    s["water"]["cistern_status"] = {"stage": "filling", "gate": "shut", "depth": 0}          # no v: the first design
    c = by_rule(plan(copy.deepcopy(s), Memory())[0], "cistern")
    assert c and "retire" in c[0].reason and c[0].action["type"] == "cistern_step", [x.reason for x in c]


@test("temples (0.104.146): many praying to gods no temple serves -> a temple to all gods; none when one serves all")
def _():
    s = fort()
    s["projects"]["open"] = []
    s["dwarves"]["total"] = 195
    s["needs"] = dict(s.get("needs") or {}, deities={"Teshkad": 36, "Pulpy Dung": 19, "Nish": 8},
                      deity_ids={"Teshkad": 217, "Pulpy Dung": 220, "Nish": 215})
    s["locations"] = {"count": {"TEMPLE": 2, "INN_TAVERN": 1, "HOSPITAL": 1, "LIBRARY": 1},
                      "list": [{"id": 0, "type": "TEMPLE", "deity_hf": 217}, {"id": 8, "type": "TEMPLE", "deity_hf": 215}]}
    b = [x for x in by_rule(plan(copy.deepcopy(s), Memory())[0], "build") if x.action.get("kind") == "temple"]
    assert b and "deity_hf" not in b[0].action and "Pulpy Dung 19" in b[0].reason and "Teshkad" not in b[0].reason, \
        [x.reason for x in b]
    s["locations"]["list"][1] = {"id": 8, "type": "TEMPLE", "any_deity": True}
    assert not [x for x in by_rule(plan(copy.deepcopy(s), Memory())[0], "build")
                if x.action.get("kind") == "temple" and "gods no temple" in x.reason]
    s["locations"]["list"] = [{"id": 0, "type": "TEMPLE"}]          # an older bridge: says nothing
    assert not [x for x in by_rule(plan(copy.deepcopy(s), Memory())[0], "build")
                if x.action.get("kind") == "temple" and "gods no temple" in x.reason]


@test("convict (0.104.147): off by default: no convictions, a note while many cases wait")
def _():
    s = fort()
    s["justice"] = {"jails": [{"id": 453, "chains": 5, "used": 0}], "restraints": 10, "restraints_used": 0,
                    "punish": {"n": 0}, "crimes": {"n": 1623, "convictable": 398}}
    props, notes = plan(copy.deepcopy(s), Memory())
    assert not by_rule(props, "convict") and any("convicts no one" in n for n in notes)

@test("0.104.164: released soldiers passed over by the fill; a stale open pull turned; traction parts not held in a crisis")
def _():
    from planner import record, Proposal
    from planner_core import recently_home
    import crisis
    s = fort()
    now = abs_tick(s)
    m = Memory(swapped={"5": now - 10 * TICKS_PER_DAY})
    rel = Proposal("stress_care", {"type": "squad_release", "unit_id": 11438}, "miserable", 3)
    record([(rel, {"ok": True})], s, m)
    assert m.released.get("11438") == now, m.released
    assert sorted(recently_home(s, m)) == [5, 11438], recently_home(s, m)
    record([(Proposal("stress_care", {"type": "squad_release", "unit_id": 77}, "x", 3), {"ok": False})], s, m)
    assert "77" not in m.released                                       # refused: nobody went home
    m2 = Memory.from_dict(json.loads(json.dumps(m.to_dict())))
    assert m2.released == m.released                                    # kept with the memory
    # the shaft gate: a pull nobody made ("pulling" with no danger) is turned, as "closed" is
    s["others_on_map"]["threats"] = []
    s["projects"]["well_lids"] = [{"project_id": 218, "x": 115, "y": 44, "z": 154, "elevation": 26,
                                   "state": "none", "gate": "pulling", "watching": True}]
    acts = [p.action for p in by_rule(plan(copy.deepcopy(s), Memory())[0], "well_shaft")]
    assert {"type": "well_shaft", "close": False} in acts, acts
    # a crisis holds expansion, not the hospital's traction bench
    assert "traction_parts" not in crisis.EXPANSION_RULES and "war_animals" in crisis.EXPANSION_RULES
    # (0.104.165) the watcher's own test finds a beast near: the gate isn't opened, it's shut
    s["projects"]["well_lids"] = [{"project_id": 218, "x": 115, "y": 44, "z": 154, "elevation": 26, "state": "none",
                                   "gate": "closed", "watching": True,
                                   "watch_near": {"id": 6300, "name": "a cave crocodile", "pos": {"x": 120, "y": 50, "z": 140}}}]
    acts = [p.action for p in by_rule(plan(copy.deepcopy(s), Memory())[0], "well_shaft")]
    assert {"type": "well_shaft", "close": False} not in acts, acts
    s["projects"]["well_lids"][0]["gate"] = "open"
    acts = [p.action for p in by_rule(plan(copy.deepcopy(s), Memory())[0], "well_shaft")]
    assert {"type": "well_shaft", "close": True} in acts, acts


@test("labor trim (0.104.166): 84 on the fishing detail, 2 wanted: the rest off it; not while near the want")
def _():
    s = fort()
    s.setdefault("labor", {})["fish_water"] = 166
    s["labor"].setdefault("jobs", {})["fishing"] = {"candidates": 16, "detail": "Fisherdwarves", "doing": 84,
                                                   "mode": "OnlySelectedDoesThis", "soldiers": 21}
    s["stocks"]["fish"] = s["stocks"]["raw_fish"] = 0
    t = by_rule(plan(copy.deepcopy(s), Memory())[0], "labor_trim")
    assert t and t[0].action == {"type": "trim_labor", "job": "fishing", "keep": 2}, t
    assert "84 dwarves are on the fishing detail, 2 wanted and no fish in store" in t[0].reason, t[0].reason
    s["labor"]["jobs"]["fishing"]["doing"] = 6
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "labor_trim")
    s["labor"]["jobs"]["fishing"].update(doing=84, mode="EverybodyDoesThis")     # the player's setting: left
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "labor_trim")


@test("hospital burrow (0.104.167): asked while a hospital exists and patients walk outside it, or the burrow has members; first in a crisis")
def _():
    s = fort()
    s["health"] = {"hospital": [{"id": 5, "zones": [{"id": 70, "beds": 4}], "staff": []}],
                   "patients": [{"id": 1, "needs": ["suture"]}, {"id": 2, "needs": ["diagnosis"], "in_hospital": True},
                                {"id": 3, "needs": [], "infected": True}]}
    s.setdefault("society", {})["hospital_burrow"] = {"members": 0, "outside": 5, "hospital_zones": 1}
    r = by_rule(plan(copy.deepcopy(s), Memory())[0], "hospital_burrow")
    assert r and r[0].action == {"type": "hospital_burrow", "max": 30, "per": 10, "days": 28}, r
    assert r[0].reason.startswith("5 patient(s) walking outside the hospital") and r[0].priority == 4, r[0]
    # an older bridge (no status): the listed patients outside, with a treatment asked
    old = copy.deepcopy(s); del old["society"]["hospital_burrow"]
    r = by_rule(plan(old, Memory())[0], "hospital_burrow")
    assert r and r[0].reason.startswith("1 patient(s)"), r
    # nobody outside and nobody in: not asked; members to let out: asked
    calm = copy.deepcopy(s); calm["society"]["hospital_burrow"].update(outside=0)
    assert not by_rule(plan(calm, Memory())[0], "hospital_burrow")
    calm["society"]["hospital_burrow"]["members"] = 3
    assert by_rule(plan(calm, Memory())[0], "hospital_burrow")
    # no hospital: never
    none_ = copy.deepcopy(s); none_["health"]["hospital"] = []; none_["society"]["hospital_burrow"]["hospital_zones"] = 0
    assert not by_rule(plan(none_, Memory())[0], "hospital_burrow")
    # the fort in crisis: a recovery rule, ranked first
    m = Memory(); m.crisis = {"since": 0, "why": ["7 deaths"]}
    r = by_rule(plan(copy.deepcopy(s), m)[0], "hospital_burrow")
    assert r and r[0].priority <= 0, r
    import crisis
    assert "hospital_burrow" in crisis.RECOVERY_RULES
    assert planner.PLANNER_CONFIG["hospital_burrow_cooldown_ticks"] == 1200


@test("hospital burrow (0.104.167, review): members never left behind: let out when the hospital is gone, the rule is off, the status fails; never held by the strategist; not gated on the health section")
def _():
    RELEASE = {"type": "hospital_burrow", "release": True}
    s = fort()
    s["health"] = {"hospital": [], "patients": []}
    s.setdefault("society", {})["hospital_burrow"] = {"members": 4, "outside": 0, "hospital_zones": 0}
    r = by_rule(plan(copy.deepcopy(s), Memory())[0], "hospital_burrow")
    assert r and r[0].action == RELEASE and "no hospital zone" in r[0].reason, r          # the hospital gone
    s["society"]["hospital_burrow"]["members"] = 0
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "hospital_burrow")           # nobody to let out
    # switched off in the settings, with members: let out; with none: nothing
    off = copy.deepcopy(s)
    off["health"]["hospital"] = [{"id": 5, "zones": [{"id": 70}]}]
    off["society"]["hospital_burrow"].update(members=3, outside=6, hospital_zones=1)
    off.setdefault("settings", {})["hospital_burrow"] = False
    r = by_rule(plan(copy.deepcopy(off), Memory())[0], "hospital_burrow")
    assert r and r[0].action == RELEASE and "switched off" in r[0].reason, r
    off["society"]["hospital_burrow"]["members"] = 0
    assert not by_rule(plan(copy.deepcopy(off), Memory())[0], "hospital_burrow")
    # the status unreadable (or the whole society section): let out
    bad = copy.deepcopy(s); bad["society"]["hospital_burrow"] = {"error": "boom"}
    r = by_rule(plan(bad, Memory())[0], "hospital_burrow")
    assert r and r[0].action == RELEASE and "can't be read" in r[0].reason, r
    bad = copy.deepcopy(s); bad["society"] = {"error": "boom"}
    r = by_rule(plan(bad, Memory())[0], "hospital_burrow")
    assert r and r[0].action == RELEASE, r
    # the health section failed: the rule still runs on the burrow's own status
    sick = copy.deepcopy(s); sick["health"] = {"error": "boom"}
    sick["society"]["hospital_burrow"].update(members=2, outside=3, hospital_zones=1)
    r = by_rule(plan(sick, Memory())[0], "hospital_burrow")
    assert r and r[0].action.get("max") == 30, r
    # the strategist's hold never keeps it back
    m = Memory(); now = abs_tick(sick)
    m.steer["hospital_burrow"] = {"mode": "hold", "until": now + 10 * TICKS_PER_DAY, "why": "x"}
    allowed, held = select(plan(copy.deepcopy(sick), m)[0], sick, m)
    assert any(p.rule == "hospital_burrow" for p in allowed), held


def _rotation_fort():
    s = fort()
    sq = s["military"]["squads"]
    s["military"]["routines"] = ["Off duty", "Staggered training", "Constant training", "Ready"]
    for q in sq:
        q["routine"], q["members"], q["ai_orders"] = "Constant training", 5, False
    s["settings"]["militarism"] = 0
    s["dwarves"]["total"] = 160
    m = Memory()
    m.squads_trained = [q["id"] for q in sq]
    return s, m


@test("training rotation (0.104.168): the mode held a while: all training 14 days before half rest, half resting 7 before all train")
def _():
    s, m = _rotation_fort()
    sq = s["military"]["squads"]
    mt = s.setdefault("needs", {}).setdefault("needs", {})
    def moves(state):
        return {p.action["squad_id"]: p.action["routine"] for p in by_rule(plan(state, m)[0], "train")}
    mt["MartialTraining"] = {"badly": 30, "distracted": 80}            # all train (first seen: no hold)
    assert not [r for r in moves(copy.deepcopy(s)).values() if r == "Off duty"]
    assert m.train_mode.get("all") is True
    # the need drops under 7% two days later (as Teacheroar's did): still all training
    s["date"]["tick"] += 2 * TICKS_PER_DAY
    mt["MartialTraining"] = {"badly": 4, "distracted": 20}
    m.train_mode = {"all": True, "tick": abs_tick(s) - 2 * TICKS_PER_DAY}   # all since two days
    assert not [r for r in moves(copy.deepcopy(s)).values() if r == "Off duty"], "held: all train 14 days"
    s["date"]["tick"] += 13 * TICKS_PER_DAY                             # 15 days in: half rest
    off = [sid for sid, r in moves(copy.deepcopy(s)).items() if r == "Off duty"]
    assert off and m.train_mode == {"all": False, "tick": abs_tick(s)}, (off, m.train_mode)
    # half resting; the need back over 15% three days later: held another four days
    for q in sq:
        q["routine"] = "Off duty" if q["id"] in off else "Constant training"
    m.squads_rested = list(off)
    s["date"]["tick"] += 3 * TICKS_PER_DAY
    mt["MartialTraining"] = {"badly": 40, "distracted": 90}
    assert not [sid for sid, r in moves(copy.deepcopy(s)).items() if sid in off and r == "Constant training"], \
        "held: half rest 7 days"
    s["date"]["tick"] += 4 * TICKS_PER_DAY
    got = moves(copy.deepcopy(s))
    assert all(got.get(sid) == "Constant training" for sid in off), got
    assert m.train_mode.get("all") is True


@test("keen lift (0.104.168): in a crisis the soldiers wanted rise for the draftable keen, held after drafting; never in a threat")
def _():
    from planner_military import keen_lift
    cfg = PLANNER_CONFIG
    s = fort()
    # (review) 18 keen, 15 the fill could draft (3 nobles, mothers or patients): sized on the 15
    s["needs"] = {"needs": {}, "keen_civilians": 18, "keen_draftable": 15}
    now = abs_tick(s)
    calm = Memory()
    assert keen_lift(s, calm, cfg, 33, 34, 133, False) == 33, "no crisis: no lift"
    old = copy.deepcopy(s); del old["needs"]["keen_draftable"]
    mo = Memory(); mo.crisis = {"since": 1, "why": ["45% unhappy"]}
    assert keen_lift(old, mo, cfg, 33, 34, 133, False) == 33, "an older bridge (no draftable count): no lift"
    m = Memory(); m.crisis = {"since": 1, "why": ["45% unhappy"]}
    w = keen_lift(s, m, cfg, 33, 34, 133, False)
    assert w == 33 + 16 and m.keen_lift == {"n": 16, "tick": now}, (w, m.keen_lift)   # 34 + 15 = 49
    # 10 drafted (the lift's places go to the keen alone): the need holds, no more places
    s["needs"]["keen_draftable"] = 5
    assert keen_lift(s, m, cfg, 33, 44, 133, False) == 49
    # (review, minor) the count bouncing (5 -> 2 -> 5) doesn't ratchet it: the most over the period
    s["needs"]["keen_draftable"] = 2
    assert keen_lift(s, m, cfg, 33, 44, 133, False) == 49
    s["needs"]["keen_draftable"] = 5
    assert keen_lift(s, m, cfg, 33, 44, 133, False) == 49 and m.keen_lift["n"] == 16, m.keen_lift
    s["needs"]["keen_draftable"] = 9                                     # 4 newly keen: 4 more places
    assert keen_lift(s, m, cfg, 33, 44, 133, False) == 53 and m.keen_lift["n"] == 20, m.keen_lift
    # the keen all drafted: the lift is held, no extra soldiers to trim; then gone after 56 days
    s["needs"]["keen_draftable"] = 0
    assert keen_lift(s, m, cfg, 33, 53, 133, False) == 53
    s["date"]["tick"] += 57 * TICKS_PER_DAY
    assert keen_lift(s, m, cfg, 33, 53, 133, False) == 33 and m.keen_lift == {}
    # never while threats can reach the fort, nor at Militarism -50; capped by the fort's share and the max
    s["needs"]["keen_draftable"] = 40
    m2 = Memory(); m2.crisis = {"since": 1, "why": ["x"]}
    assert keen_lift(s, m2, cfg, 33, 34, 133, True) == 33
    low = copy.deepcopy(s); low["settings"]["traits"] = {"militarism": -60}
    assert keen_lift(low, m2, cfg, 33, 34, 133, False) == 33
    assert keen_lift(s, m2, cfg, 33, 34, 133, False) == 33 + cfg["keen_lift_max"]
    assert keen_lift(s, m2, cfg, 33, 34, 60, False) == 33, "within 45% of a fort of 60 (27): no more than wanted"


@test("keen lift (0.104.168, review): the fill fills the wanted places first, the lift's with the keen only, strict in a crisis; none while berserk or in a tantrum")
def _():
    p = fort()
    p["settings"]["traits"] = {"militarism": 0}                       # 10% of 194 = 19 wanted
    p["military"]["squads"][1]["members"] = 4
    p["military"]["soldiers"] = 14
    p["needs"] = {"needs": {}, "keen_civilians": 9, "keen_draftable": 9}
    def crisis():
        mc = Memory(); mc.crisis = {"since": 1, "why": ["45% unhappy"]}
        return mc
    f = by_rule(plan(copy.deepcopy(p), crisis())[0], "squad_fill")
    assert f and "more for the civilians who badly want to train" in f[0].reason, f
    assert f[0].action["count"] <= 19 - 14 and f[0].action.get("strict") is True and not f[0].action.get("keen_only"), f
    f = by_rule(plan(copy.deepcopy(p), Memory())[0], "squad_fill")
    assert f and "badly want to train" not in f[0].reason and "strict" not in f[0].action, f
    full = copy.deepcopy(p); full["military"]["soldiers"] = 19        # the wanted places are filled: keen only
    f = by_rule(plan(full, crisis())[0], "squad_fill")
    assert f and f[0].action.get("keen_only") is True and f[0].action.get("strict") is True, f
    # nobody drafted while a dwarf is berserk or a tantrum is under way
    mad = copy.deepcopy(p); mad.setdefault("hazards", {})["berserk"] = [{"id": 77, "name": "Urist"}]
    props, notes = plan(mad, Memory())[:2]
    assert not by_rule(props, "squad_fill") and any("no drafting while a dwarf is berserk" in n for n in notes), notes
    mt = Memory(); mt.tantrums = [[abs_tick(p) - 100, "Urist"]]
    props, notes = plan(copy.deepcopy(p), mt)[:2]
    assert not by_rule(props, "squad_fill") and any("tantrums are under way" in n for n in notes), notes
    mt.tantrums = [[abs_tick(p) - 2 * TICKS_PER_DAY, "Urist"]]         # two days ago: over
    assert by_rule(plan(copy.deepcopy(p), mt)[0], "squad_fill")
    # the swap's draft is strict in a crisis too
    from planner_core import _soldier_swap
    s = fort()
    s["needs"] = {"needs": {}, "keen_civilians": 18,
                  "starved_soldiers": [{"id": 9, "name": "Kib", "unmet": ["CraftObject", "BeWithFriends"]}]}
    out = []
    _soldier_swap(s, PLANNER_CONFIG, out, crisis())
    assert out and out[0].action.get("strict") is True, out
    out = []
    _soldier_swap(s, PLANNER_CONFIG, out, Memory())
    assert out and "strict" not in out[0].action, out


@test("soldier swap (0.104.168): in a crisis, one swap a month per 2 keen civilians (4 out of crisis)")
def _():
    from planner_core import _soldier_swap
    cfg = PLANNER_CONFIG
    s = fort()
    s["needs"] = {"needs": {}, "keen_civilians": 18,
                  "starved_soldiers": [{"id": 9, "name": "Kib", "unmet": ["CraftObject", "BeWithFriends"]}]}
    s.setdefault("military", {}).setdefault("gear", {})["soldiers"] = 34
    now = abs_tick(s)
    m = Memory(swapped={str(100 + i): now - TICKS_PER_DAY for i in range(5)})   # 5 swaps this month
    out = []
    _soldier_swap(s, cfg, out, m)
    assert not out, "out of crisis: 18 // 4 = 4 a month, 5 used"
    m.crisis = {"since": 1, "why": ["45% unhappy"]}
    _soldier_swap(s, cfg, out, m)
    assert out and out[0].action["unit_id"] == 9, out                    # 18 // 2 = 9 a month


@test("complaints (0.104.168): citizens unable to complain are said with why, the mayor's meetings; the mayor gets an office whatever Deference says")
def _():
    s = fort()
    s.setdefault("needs", {})["stress_causes"] = {"causes": [
        {"thought": "UnableComplain", "citizens": 24, "stress": 13,
         "about": {"vent_at_boss": 15, "cry_on_boss": 4, "insufficient_work": 5}}]}
    s["offices"] = {"offices": {"MAYOR": {"held": ["Asob Sheshekolin"], "vacant": 0}}}
    s["meetings"] = {"activities": [{"actor": "Iton", "noble": 'Asob Sheshekolin "Tiptongs", mayor'}], "requests": 11}
    notes = plan(copy.deepcopy(s), Memory())[1]
    n = [x for x in notes if "couldn't lodge a complaint" in x]
    assert n and "24 citizens" in n[0] and "venting 15" in n[0] and "back to back (11 waiting)" in n[0] \
        and "eases as the fort's stress does" in n[0], n
    work = copy.deepcopy(s)
    work["needs"]["stress_causes"]["causes"][0]["about"] = {"insufficient_work": 12, "vent_at_boss": 2}
    n = [x for x in plan(work, Memory())[1] if "couldn't lodge" in x]
    assert n and "asking for work" in n[0], n
    nomayor = copy.deepcopy(s); nomayor["offices"]["offices"]["MAYOR"]["held"] = []
    n = [x for x in plan(nomayor, Memory())[1] if "couldn't lodge" in x]
    assert n and "no mayor" in n[0], n
    few = copy.deepcopy(s); few["needs"]["stress_causes"]["causes"][0]["citizens"] = 3
    assert not [x for x in plan(few, Memory())[1] if "couldn't lodge" in x]
    # the mayor's office: given even when Deference gives nobles no office
    s["settings"]["traits"] = {"deference": -100}
    s["noble_rooms"] = {"nobles": [{"unit_id": 6247, "name": "Asob", "office": "MAYOR", "needs": ["office"]},
                                   {"unit_id": 5, "name": "Urist", "office": "SHERIFF", "needs": ["office"]}],
                        "free": {"office": 1}}
    g = by_rule(plan(copy.deepcopy(s), Memory())[0], "noble_rooms")
    assert [p.action["unit_id"] for p in g] == [6247], [p.action for p in g]
    n = [x for x in plan(copy.deepcopy(s), Memory())[1] if "couldn't lodge" in x]
    assert n and "no office of their own" in n[0], n


@test("vermin (0.104.168): citizens upset by hated vermin: a few cats kept from the butcher; no cats or all caged: said")
def _():
    s = fort()
    s["dwarves"]["total"] = 133
    s.setdefault("needs", {})["stress_causes"] = {"causes": [
        {"thought": "AnnoyedVermin", "citizens": 15, "stress": 25, "about": {"RAT": 9, "FLY": 4}}]}
    s["needs"]["vermin_hunters"] = {"n": 12, "loose": 10, "caged": 2, "marked": 3, "kept": 1, "mousers": 0}
    v = by_rule(plan(copy.deepcopy(s), Memory())[0], "vermin")
    assert v and v[0].action == {"type": "keep_mousers", "count": 5}, v            # 133 // 25 = 5
    assert "15 citizens were upset" in v[0].reason and "rat 9" in v[0].reason, v[0].reason
    enough = copy.deepcopy(s); enough["needs"]["vermin_hunters"]["kept"] = 5
    assert not by_rule(plan(enough, Memory())[0], "vermin")
    few = copy.deepcopy(s); few["needs"]["vermin_hunters"].update(loose=2, kept=2)
    assert not by_rule(plan(few, Memory())[0], "vermin"), "every loose cat already kept"
    none_ = copy.deepcopy(s); none_["needs"]["vermin_hunters"] = {"n": 0, "loose": 0, "kept": 0}
    p, notes = plan(none_, Memory())[:2]
    assert not by_rule(p, "vermin") and any("no cat" in n for n in notes), notes
    caged = copy.deepcopy(s); caged["needs"]["vermin_hunters"] = {"n": 3, "loose": 0, "caged": 3, "kept": 0}
    assert any("all caged" in n for n in plan(caged, Memory())[1])
    calm = copy.deepcopy(s); calm["needs"]["stress_causes"]["causes"][0]["citizens"] = 2
    assert not by_rule(plan(calm, Memory())[0], "vermin")
    from overseer import short
    assert "cats" in short({"type": "keep_mousers", "count": 5})
    assert planner.PLANNER_CONFIG["vermin_cooldown_ticks"] == 7 * 1200


@test("cistern gaps (0.104.168): an open spot the AI walls itself is a note and the step goes on; one it can't close is retired (0.105.35)")
def _():
    s = fort()
    st = {"v": 2, "stage": "linking", "gate": "shut", "depth": 0, "lever": "built", "linked": True,
          "unsealed": "the cistern's shaft is open at x105 y128 elevation 38"}
    s["water"] = dict(s.get("water") or {}, cistern_status=dict(st))
    props, notes = plan(copy.deepcopy(s), Memory())
    assert not any(n.startswith(planner.NEEDS_YOU) and "cistern" in n for n in notes), notes
    assert any("the AI builds a wall or floor there itself" in n for n in notes), notes
    c = by_rule(props, "cistern")
    assert c and c[0].action["type"] == "cistern_step" and not c[0].action.get("shut"), [x.action for x in c]
    s["water"]["cistern_status"] = dict(st, unsealed_why="the cistern's shaft is open at x105 y128 elevation 38: "
                                                         "it is stair_updown (a way up or down the dwarves may walk)")
    props, notes = plan(copy.deepcopy(s), Memory())
    # (0.105.35) tried again, then the cistern retired (no water let in): no Needs you
    assert any("stair_updown" in n and "1 of 3" in n for n in notes), notes
    assert not any(n.startswith(planner.NEEDS_YOU) and "cistern" in n for n in notes), notes
    s["water"]["cistern_status"]["unsealed_refusals"] = 3
    c = by_rule(plan(copy.deepcopy(s), Memory())[0], "cistern")
    assert [x.action.get("retire") for x in c] == [True], [x.action for x in c]


@test("cups (0.104.168): loose cups no pile takes -> accept_cups; forbidden ones in a hall -> accept_cups; a tavern's only said")
def _():
    s = fort()
    cl = s.setdefault("needs", {}).setdefault("clothing", {"citizens": 140})
    cl["free_cups"] = 34
    cl["free_cups_detail"] = {"n": 34, "place": {"zone DiningHall": 10, "zone MeetingHall": 24},
                              "why": {"pile_refuses": 10, "location": 24}, "why_locations": {"INN_TAVERN": 24},
                              "flags": {"on_ground": 34}}
    props, notes = plan(copy.deepcopy(s), Memory())
    r = by_rule(props, "cups_home")
    assert r and r[0].action == {"type": "accept_cups"} and r[0].reason.startswith("10 loose cup(s)"), r
    assert any("why the loose cups stay off the piles" in n and "24 in a tavern" in n for n in notes), notes
    cl["free_cups_detail"]["why"] = {"location": 34}
    cl["free_cups_detail"]["why_locations"] = {"INN_TAVERN": 34}
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "cups_home")
    cl["free_cups_detail"]["why"] = {"should_haul": 3}
    cl["free_cups_detail"]["forbidden_in_halls"] = 4
    from planner_society import _cups_home_rule
    out = []
    _cups_home_rule(cl, 100, out, [])
    assert out and out[0].action == {"type": "accept_cups"} and "forbidden" in out[0].reason, out
    out = []
    _cups_home_rule(cl, 0, out, [])
    assert not out                                                    # nobody wants a cup: left alone
    assert "shoes and cups" in planner.agenda([planner.Proposal("cups_home", {"type": "accept_cups"}, "x", 4)], [])[0]


def _infected_fort(**inf):
    s = fort()
    s["infection"] = {"infected": 77, "untreated": 75, "bleeding": 6, "idle_untreated": 20, "free_beds": 24,
                      "beds": 30, "hospital_zones": 3, "diagnosers": 6, "cleaners": 80, "sleeping": 0, "failed": 0,
                      "helped": 0, "rest_days": 3, "max_load": 900, "worst": [{"id": 1, "name": "Urist", "load": 900}]}
    s["infection"].update(inf)
    return s


@test("0.104.168 infection: idle infected dwarves DF asks nothing for are put to bed in the hospital, the bleeding first; said what is wrong")
def _():
    props, notes = plan(_infected_fort(), Memory())
    r = by_rule(props, "infected_rest")
    assert r and r[0].action == {"type": "rest_infected", "max": 3, "cap": 3, "keep_free": 2} and r[0].priority == 2, r
    assert any(n.startswith("77 citizens have infected wounds, 75 with no treatment asked") and "6 bleed" in n
               and "Urist (900)" in n for n in notes), notes
    # bounded by the free beds and the idle; no bleeding: lower priority
    # (review) 2 beds always left for DF's own patients; at most 3 of the AI's sleepers at once
    r = by_rule(plan(_infected_fort(free_beds=4, bleeding=0), Memory())[0], "infected_rest")
    assert r and r[0].action["max"] == 2 and r[0].priority == 4, r
    assert not by_rule(plan(_infected_fort(free_beds=2), Memory())[0], "infected_rest")
    r = by_rule(plan(_infected_fort(sleeping=2), Memory())[0], "infected_rest")
    assert r and r[0].action["max"] == 1, r
    assert not by_rule(plan(_infected_fort(sleeping=3), Memory())[0], "infected_rest")
    r = by_rule(plan(_infected_fort(idle_untreated=1), Memory())[0], "infected_rest")
    assert r and r[0].action["max"] == 1, r
    # every bed taken, nobody idle, no hospital, nobody to diagnose: not asked
    props, notes = plan(_infected_fort(free_beds=0), Memory())
    assert not by_rule(props, "infected_rest") and any("every hospital bed is taken" in n for n in notes), notes
    assert not by_rule(plan(_infected_fort(idle_untreated=0), Memory())[0], "infected_rest")
    assert not by_rule(plan(_infected_fort(hospital_zones=0), Memory())[0], "infected_rest")
    props, notes = plan(_infected_fort(diagnosers=0), Memory())
    assert not by_rule(props, "infected_rest")
    # (0.105.35) nobody to diagnose, or to clean: the AI gives the labour (no Needs you)
    d = by_rule(props, "care_diagnose")
    assert d and d[0].action == {"type": "assign_labor", "job": "DIAGNOSE", "count": 1}, rules(props)
    assert "nobody outside the military can diagnose" in d[0].reason
    props, notes = plan(_infected_fort(cleaners=0), Memory())
    c = by_rule(props, "care_clean")
    assert c and c[0].action == {"type": "assign_labor", "job": "CLEAN", "count": 2}, rules(props)
    assert not any(n.startswith(planner.NEEDS_YOU) and "cleaning labour" in n for n in notes), notes
    # an older bridge (no section) or a failed one: nothing
    s = fort(); s.pop("infection", None)
    assert not by_rule(plan(s, Memory())[0], "infected_rest")
    s = _infected_fort(); s["infection"] = {"error": "boom"}
    assert not by_rule(plan(s, Memory())[0], "infected_rest")


@test("0.104.168 infection (review): none of those put to bed lately got a treatment asked (got up, or DF ended the rest): the AI stops")
def _():
    props, notes = plan(_infected_fort(failed=3, helped=0), Memory())
    assert not by_rule(props, "infected_rest") and any("never diagnosed" in n and "3 days" in n for n in notes), notes
    assert by_rule(plan(_infected_fort(failed=3, helped=1), Memory())[0], "infected_rest")
    assert by_rule(plan(_infected_fort(failed=2), Memory())[0], "infected_rest")


@test("0.104.168 infection: a recovery rule in a crisis; labels for the new actions; a day apart")
def _():
    import crisis
    import overseer
    assert {"infected_rest", "soap_rush", "doctor_post", "appoint"} <= crisis.RECOVERY_RULES
    m = Memory(); m.crisis = {"since": 0, "why": ["7 deaths"]}
    r = by_rule(plan(_infected_fort(), m)[0], "infected_rest")
    assert r and r[0].priority <= 0, r
    assert PLANNER_CONFIG["infected_rest_cooldown_ticks"] == TICKS_PER_DAY
    assert "infected wounds to bed" in overseer.short({"type": "rest_infected", "max": 3})
    assert overseer.short({"type": "add_doctor_post", "location_id": 4}) == "add a second doctor's post at a hospital"


@test("0.104.168 doctors: more treatments waiting than the diagnosers can give: a second doctor's post at a fully staffed hospital")
def _():
    s = fort()
    full = {k: {"posts": 1, "filled": 1} for k in ("DIAGNOSTICIAN", "DOCTOR", "SURGEON", "BONE_DOCTOR")}
    s["locations"]["list"] = [{"id": 4, "type": "HOSPITAL", "jobs": copy.deepcopy(full), "zones": [287]},
                              {"id": 13, "type": "HOSPITAL", "jobs": copy.deepcopy(full), "zones": [2798]}]
    s["health"] = {"waiting": 20, "patients": [], "hospital": []}
    s["infection"] = {"infected": 0, "diagnosers": 2}
    r = by_rule(plan(copy.deepcopy(s), Memory())[0], "doctor_post")
    assert r and r[0].action == {"type": "add_doctor_post", "location_id": 4}, r
    s["health"]["waiting"] = 6                                          # 3 a diagnoser: enough
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "doctor_post")
    s["health"]["waiting"] = 20
    s["locations"]["list"][0]["jobs"]["DOCTOR"] = {"posts": 2, "filled": 2}    # the first has two: the second
    r = by_rule(plan(copy.deepcopy(s), Memory())[0], "doctor_post")
    assert r and r[0].action["location_id"] == 13, r
    s["locations"]["list"][1]["jobs"]["SURGEON"] = {"posts": 1, "filled": 0}   # a post empty: staffed first
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "doctor_post")
    # an older bridge: the diagnosers counted from the hospitals' staff
    s["locations"]["list"][1]["jobs"]["SURGEON"] = {"posts": 1, "filled": 1}
    s.pop("infection")
    s["health"]["hospital"] = [{"id": 4, "staff": [{"post": "DOCTOR", "labors": ["DIAGNOSE"]}]}]
    assert by_rule(plan(copy.deepcopy(s), Memory())[0], "doctor_post")


@test("0.104.168 soap: with 20+ infected the chain runs two steps a cycle, in batches of 5")
def _():
    s = fort()
    s["locations"].setdefault("count", {})["HOSPITAL"] = 1
    s["orders"] = []
    s["buildings"]["workshops"].update(Ashery=1, SoapMaker=1, Kitchen=1)
    s["buildings"].setdefault("furnaces", {})["WoodFurnace"] = 1
    s["supplies"].update(soap=0, ash=2, lye=1, tallow=50, fat=100, buckets=5)
    s["stocks"]["wood"] = 100
    s["health"] = dict(s.get("health") or {}, infected=77)
    props = plan(copy.deepcopy(s), Memory())[0]
    a, b = by_rule(props, "soap"), by_rule(props, "soap_rush")
    assert a and a[0].action == {"type": "work_order", "recipe": "make_soap_from_tallow", "amount": 1}, a
    assert b and b[0].action["recipe"] != "make_soap_from_tallow" and b[0].action["recipe"] == "make_ash", b
    assert b[0].action["amount"] == 5, b                                 # ash for the next bars, 5 at a time
    s["orders"] = [{"id": 1, "recipe": "make_soap_from_tallow", "amount_left": 1, "by_ai": True}]
    props = plan(copy.deepcopy(s), Memory())[0]
    a, b = by_rule(props, "soap"), by_rule(props, "soap_rush")
    assert a and a[0].action["recipe"] == "make_ash" and not b, (a, b)   # only one step left unqueued
    # fewer infected: one step a cycle, as before
    s["orders"] = []
    s["health"]["infected"] = 10
    props = plan(copy.deepcopy(s), Memory())[0]
    assert by_rule(props, "soap") and not by_rule(props, "soap_rush")


def _offices_fort(**offices):
    s = fort()
    base = {"MAYOR": {"held": ["Asob"], "vacant": 0, "appointable": False, "not_why": "elected", "ai": False},
            "MILITIA_COMMANDER": {"held": ["Lorbam"], "vacant": 0, "appointable": True, "ai": True},
            "MILITIA_CAPTAIN": {"held": ["Udil"], "vacant": 1, "appointable": True, "ai": True},
            "HAMMERER": {"held": [], "vacant": 1, "appointable": False, "not_why": "its appointer is not in the fort",
                         "ai": False}}
    for k, v in offices.items():
        base[k] = dict(base.get(k, {}), **v)
    s["offices"] = {"entity": 296, "offices": base}
    return s


@test("0.104.168 offices: a dead militia commander's office is filled again; a captain's only where a squad lost him")
def _():
    props, notes = plan(_offices_fort(), Memory())
    assert not [p for p in by_rule(props, "appoint") if "MILITIA" in str(p.action.get("office"))], props
    assert not any("hammerer" in n or "mayor" in n for n in notes), notes      # left to DF
    r = by_rule(plan(_offices_fort(MILITIA_COMMANDER={"held": [], "vacant": 1}), Memory())[0], "appoint")
    assert r and r[0].action == {"type": "appoint", "office": "MILITIA_COMMANDER"}, r
    # a captain's slot without a squad is DF's spare for the next squad: not filled
    assert not [p for p in by_rule(plan(_offices_fort(), Memory())[0], "appoint")
                if p.action.get("office") == "MILITIA_CAPTAIN"]
    r = by_rule(plan(_offices_fort(MILITIA_CAPTAIN={"vacant": 2, "vacant_squad": 1}), Memory())[0], "appoint")
    assert r and r[0].action == {"type": "appoint", "office": "MILITIA_CAPTAIN"} and "1 squad(s)" in r[0].reason, r
    # both vacant: the commander first (he appoints the captains)
    r = by_rule(plan(_offices_fort(MILITIA_COMMANDER={"held": [], "vacant": 1},
                                   MILITIA_CAPTAIN={"vacant_squad": 1}), Memory())[0], "appoint")
    assert [p.action["office"] for p in r if "MILITIA" in p.action["office"]] == ["MILITIA_COMMANDER"], r
    # not the fort's to fill, or appointing switched off: not asked
    assert not by_rule(plan(_offices_fort(MILITIA_COMMANDER={"held": [], "vacant": 1, "appointable": False}),
                            Memory())[0], "appoint")
    s = _offices_fort(MILITIA_COMMANDER={"held": [], "vacant": 1})
    s.setdefault("settings", {})["appoint_nobles"] = False
    assert not by_rule(plan(s, Memory())[0], "appoint")


@test("0.104.168 offices (review): nobody fit to lead a squad: the post stays empty and that is said")
def _():
    from planner import refusal_key, Proposal
    m = Memory()
    s = _offices_fort(MILITIA_COMMANDER={"held": [], "vacant": 1})
    m.refusals = {refusal_key(Proposal("appoint", {"type": "appoint", "office": "MILITIA_COMMANDER"}, "", 3)): {
        "n": 1, "until": abs_tick(s) + 2 * TICKS_PER_DAY,
        "why": "nobody fits to lead a squad (a content, healthy civilian ...): the militia commander stays vacant"}}
    notes = plan(s, m)[1]
    assert any(n.startswith("nobody fits to lead a squad") for n in notes), notes


@test("0.104.168 offices: one the fort could fill and the AI doesn't is said; elected and monarch's ones are not")
def _():
    notes = plan(_offices_fort(CHAMPION={"held": [], "vacant": 1, "appointable": True, "ai": False}), Memory())[1]
    assert any("the fort may fill these offices and the AI doesn't: champion" in n for n in notes), notes
    notes = plan(_offices_fort(CHAMPION={"held": [], "vacant": 1, "appointable": False, "ai": False}), Memory())[1]
    assert not any("champion" in n for n in notes), notes
    # an older bridge (no appointable): nothing said, the commander still filled
    s = _offices_fort(MILITIA_COMMANDER={"held": [], "vacant": 1})
    for o in s["offices"]["offices"].values():
        o.pop("appointable", None)
    props, notes = plan(s, Memory())
    assert by_rule(props, "appoint") and not any("may fill these offices" in n for n in notes)


# --- (0.104.168) homes: a bedroom per household, rooms the stressed like ------------

HOMES = {"citizens": 142, "adults": 125, "children": 17, "adults_roomless": 0, "children_roomless": 0,
         "couples": 20, "couples_shared": 20, "couples_apart": 0, "couples_none": 0, "couples_unlinked": 0,
         "hoarders": 0, "rough": 0, "rough_housed": 0, "rough_children": 0, "rough_unreachable": 0,
         "lack_room": 0, "free_bedrooms": 190, "free_suites": 2, "free_bedless": 0, "rooms_wanted": 0, "samples": []}


def homes_fort(**kw):
    s = fort()
    s["homes"] = {**copy.deepcopy(HOMES), **kw}
    return s


@test("homes (0.104.168): everyone housed, few stressed: nothing; an older bridge without the section: nothing")
def _():
    s = homes_fort(); s["dwarves"]["stress"]["unhappy"] = 2
    p, notes = plan(s, Memory())
    assert not [x for x in p if x.rule.startswith("homes")], rules(p)
    s = fort(); s.pop("homes", None)
    p, _ = plan(s, Memory())
    assert not [x for x in p if x.rule.startswith("homes")], rules(p)
    s = fort(); s["homes"] = {"error": "boom"}
    p, _ = plan(s, Memory())
    assert not [x for x in p if x.rule.startswith("homes")], rules(p)


@test("homes (0.104.168): couples in two rooms or roomless households with free rooms: house_dwarves")
def _():
    p, _ = plan(homes_fort(couples_apart=3, couples_unlinked=1, rooms_wanted=4, children_roomless=2,
                           adults_roomless=3), Memory())
    h = by_rule(p, "homes")
    assert h and h[0].action == {"type": "house_dwarves", "house": 8}, [x.action for x in h]
    assert "two rooms" in h[0].reason and "2 children" in h[0].reason, h[0].reason
    assert not by_rule(p, "homes_dig")
    # only as many as there are free rooms for the roomless
    p, _ = plan(homes_fort(rooms_wanted=9, free_bedrooms=2), Memory())
    assert by_rule(p, "homes")[0].action["house"] == 2


@test("homes (0.104.168): more roomless households than free bedrooms: a bedrooms level (not beside another)")
def _():
    s = homes_fort(rooms_wanted=12, free_bedrooms=2)
    d = by_rule(plan(s, Memory())[0], "homes_dig")
    assert d and d[0].action["kind"] == "bedrooms" and d[0].action["rooms"] == 10 + PLANNER_CONFIG["min_spare_beds"], \
        [x.action for x in d]
    s["projects"]["open"] = [{"kind": "bedrooms", "phase": "dig", "id": 9}]
    assert not by_rule(plan(s, Memory())[0], "homes_dig")


@test("homes (0.104.168): five or more stressed and free rooms: the most stressed to rooms they like, a week apart")
def _():
    s = homes_fort()
    s["dwarves"]["stress"].update(miserable=3, very_unhappy=4, unhappy=10)
    p, _ = plan(s, Memory())
    h = by_rule(p, "homes_liked")
    assert h and h[0].action == {"type": "house_dwarves", "house": 0, "upgrade": PLANNER_CONFIG["homes_liked_max"]}, \
        [x.action for x in h]
    assert PLANNER_CONFIG["homes_liked_cooldown_ticks"] == 7 * TICKS_PER_DAY
    s2 = homes_fort(free_bedrooms=0)
    s2["dwarves"]["stress"].update(miserable=3, very_unhappy=4, unhappy=10)
    assert not by_rule(plan(s2, Memory())[0], "homes_liked")
    # a week apart once fired
    m = Memory(); now = abs_tick(s)
    m.last_fired["homes_liked"] = now - TICKS_PER_DAY
    allowed, held = select(plan(copy.deepcopy(s), m)[0], s, m)
    assert not any(x.rule == "homes_liked" for x in allowed) and any("homes_liked" in x for x in held), held


@test("homes (0.104.168): rough sleepers get a note saying whether they lack a room or sleep away from it")
def _():
    _, notes = plan(homes_fort(rough=5, rough_housed=4, rough_unreachable=1, rough_children=2), Memory())
    n = [x for x in notes if "slept rough" in x]
    assert n and "2 of them children" in n[0] and "1 with no bedroom" in n[0] and "1 can't walk" in n[0], n
    import overseer
    assert "household" in overseer.short({"type": "house_dwarves", "house": 3})
    assert "like better" in overseer.short({"type": "house_dwarves", "house": 0, "upgrade": 5})


@test("homes (0.104.168, review): only roomless households that can reach a free room; no level if projects failed")
def _():
    p, notes = plan(homes_fort(rooms_wanted=4, rooms_reachable=1), Memory())
    h = by_rule(p, "homes")
    assert h and h[0].action["house"] == 1, [x.action for x in h]
    assert any("can't walk to any" in x for x in notes), notes
    assert not by_rule(plan(homes_fort(rooms_wanted=4, rooms_reachable=0), Memory())[0], "homes")
    s = homes_fort(rooms_wanted=12, free_bedrooms=2)
    s["projects"] = {"error": "boom"}
    assert not by_rule(plan(s, Memory())[0], "homes_dig")
    # refused (nothing it could do): the planner's refusal memory holds it back next cycle
    s = homes_fort(couples_apart=1)
    m = Memory()
    hp = by_rule(plan(copy.deepcopy(s), m)[0], "homes")
    assert hp
    for _ in range(3):      # refused three times: 1, 2, then 4 days' back-off
        record([(hp[0], {"ok": False, "rejected": True, "error": "nothing"})], s, m)
    s2 = copy.deepcopy(s); s2["date"]["tick"] += 3 * TICKS_PER_DAY
    allowed, held = select(plan(copy.deepcopy(s2), m)[0], s2, m)
    assert not any(x.rule == "homes" for x in allowed) and any(x.startswith("homes: the game refused") for x in held), held


def _crisis_mem():
    m = Memory()
    m.crisis = {"since": 1, "why": ["41% unhappy"]}       # (0.104.169) crisis.py's memory
    return m


@test("drink in a crisis (0.104.169): the target rises 1.5x; food under the floor wins")
def _():
    s = fort(stocks__drink=2500)                       # 194 dwarves: target 1940, in a crisis 2910
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "drink")
    d = by_rule(plan(copy.deepcopy(s), _crisis_mem())[0], "drink")
    assert d and d[0].action["recipe"] == "brew_drink" and "crisis" in d[0].reason, [x.reason for x in d]
    assert d[0].action["amount"] == 82, d[0].action    # (2910 - 2500) / 5
    for k in ("prepared_meals", "meat", "fish", "raw_fish", "eggs", "cheese", "plant_growths"):
        s["stocks"][k] = 0
    s["stocks"]["plants"] = 1000                       # ~5 food a dwarf: the plants are food first
    assert not by_rule(plan(copy.deepcopy(s), _crisis_mem())[0], "drink")


@test("drink in a crisis (0.104.169, review): the next batch waits until the stills hold all the open order's work")
def _():
    # DF 53's amount_left counts down as jobs FINISH (Teacheroar live: brew_drink
    # 10/10 with 6 jobs made and worked on 6 stills): made jobs are still in it
    s = fort(stocks__drink=500)
    s["buildings"]["workshops"]["Still"] = 6
    s["supplies"].update(empty_barrels=92, empty_pots=8, brewable_growths=0)
    s["orders"].append({"id": 7200, "recipe": "brew_drink", "amount_left": 10, "amount_total": 10, "by_ai": True,
                        "active": True, "validated": True, "jobs": {"n": 6, "suspended": 0, "working": 6}})
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "drink")       # calm: the stills work through it first
    assert not by_rule(plan(copy.deepcopy(s), _crisis_mem())[0], "drink")  # 4 of its 10 not made yet: not yet
    s["orders"][-1].update(amount_left=6, jobs={"n": 6, "suspended": 0, "working": 6})   # its last 6 on the stills
    d = by_rule(plan(copy.deepcopy(s), _crisis_mem())[0], "drink")
    assert d and "next batch" in d[0].reason, [x.reason for x in d]
    assert d[0].action["amount"] == 94, d[0].action          # 100 barrels and pots less the 6 still to finish
    s["supplies"].update(empty_barrels=10, empty_pots=0)
    d = by_rule(plan(copy.deepcopy(s), _crisis_mem())[0], "drink")
    assert d and d[0].action["amount"] == 4, [x.action for x in d]    # the two never want more than there are
    s["supplies"].update(empty_barrels=6)
    props, notes = plan(copy.deepcopy(s), _crisis_mem())[:2]
    assert not by_rule(props, "drink") and any("no empty barrels or pots" in n for n in notes), notes
    s["supplies"].update(empty_barrels=92)
    s["orders"].append({"id": 7201, "recipe": "brew_drink", "amount_left": 50, "amount_total": 50, "by_ai": True,
                        "active": True, "jobs": {"n": 0}})
    assert not by_rule(plan(copy.deepcopy(s), _crisis_mem())[0], "drink")    # the next one's 50 not made: wait
    s["orders"][-1].update(amount_left=3, jobs={"n": 3})
    assert not by_rule(plan(copy.deepcopy(s), _crisis_mem())[0], "drink")    # two open: crisis_brew_orders_max
    s["orders"] = s["orders"][:-1]
    s["stocks"]["drink"] = 2600                    # 2600 + 30 queued >= 0.75 x 2910: not far, one batch at a time
    assert not by_rule(plan(copy.deepcopy(s), _crisis_mem())[0], "drink")


@test("drink in a crisis (0.104.169): the extra brewing leaves plants for the kitchen; containers bound it")
def _():
    s = fort(stocks__drink=2000)                   # over the usual target, 910 under the crisis's
    s["supplies"]["brewable_plants"] = 1000        # 194 x 5 = 970 kept: 30 to brew
    s["supplies"]["brewable_growths"] = 0
    d = by_rule(plan(copy.deepcopy(s), _crisis_mem())[0], "drink")
    assert d and d[0].action["amount"] == 30, [x.action for x in d]
    s["stocks"]["drink"] = 1500                    # under the usual target too: the usual brewing is never cut
    d = by_rule(plan(copy.deepcopy(s), _crisis_mem())[0], "drink")
    assert d and d[0].action["amount"] == 88, [x.action for x in d]     # the usual (1940 - 1500) / 5, not the 30
    s["supplies"].update(empty_barrels=7, empty_pots=0)
    d = by_rule(plan(copy.deepcopy(s), _crisis_mem())[0], "drink")
    assert d and d[0].action["amount"] == 7, [x.action for x in d]
    s["supplies"].update(empty_barrels=100, brewable_plants=900)
    s["stocks"]["drink"] = 2000                    # at the usual target, the plants at the keep: none, said so
    props, notes = plan(copy.deepcopy(s), _crisis_mem())[:2]
    assert not by_rule(props, "drink") and any("kept for the kitchen" in n for n in notes), notes


@test("containers in a crisis (0.104.169): barrels or pots for the brew jobs the crisis's target needs; recovery")
def _():
    import crisis
    s = fort(stocks__drink=2500)
    s["supplies"].update(empty_barrels=0, empty_pots=30)      # 30 free: enough for 194 dwarves (20) when calm
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "containers")
    c = by_rule(plan(copy.deepcopy(s), _crisis_mem())[0], "containers")
    assert c and "crisis" in c[0].reason and c[0].action["recipe"] in ("wooden_barrel", "stone_large_pot"), \
        [x.reason for x in c]
    assert crisis.is_recovery(c[0])


@test("stills in a crisis (0.104.169): past the cap x3 under the crisis's drink target, idle or not; brewers at one job")
def _():
    from planner import _bottleneck_rule, _labor_waiting_rule, drink_below_target
    cfg = dict(PLANNER_CONFIG)
    s = fort(stocks__drink=2500)
    cap = planner.shops_max(cfg, 194)
    s["buildings"]["workshops"] = {"Still": 2 * cap, "Kitchen": 1}
    s["orders"] = [{"id": 1, "recipe": "brew_drink", "amount_left": 6 * 2 * cap, "by_ai": True}]
    s["dwarves"]["idle_adults"] = 0
    p = []
    _bottleneck_rule(s, cfg, 194, p, Memory())
    assert not p, p                                   # calm: drink over the target, at the cap, nobody idle
    _bottleneck_rule(s, cfg, 194, p, _crisis_mem())
    assert p and p[0].action["shops"] == ["Still"] and p[0].action.get("urgent") and "crisis" in p[0].reason, p
    s["buildings"]["workshops"]["Still"] = cfg["crisis_stills_cap_factor"] * cap
    p = []
    _bottleneck_rule(s, cfg, 194, p, _crisis_mem())
    assert not p, p                                   # the crisis's cap
    assert drink_below_target(s, 194, cfg, _crisis_mem()) and not drink_below_target(s, 194, cfg, Memory())
    lb = {"waiting": [{"labor": "BREWER", "jobs": 1, "holders": 3, "idle": 0}]}
    p = []
    _labor_waiting_rule(lb, 194, cfg, p, drink_below_target(s, 194, cfg, _crisis_mem()))
    assert p and p[0].action["job"] == "BREWER", p


@test("calm burrow (0.104.169): asked first while a citizen in a tantrum walks free, or while the burrows hold members (to let them out); never on an older bridge")
def _():
    s = fort()
    s.setdefault("society", {})["calm_burrow"] = {"members": 0, "tantrums": 3, "free": 2, "held": {"soldier": 1}}
    r = by_rule(plan(copy.deepcopy(s), Memory())[0], "calm_burrow")
    assert r and r[0].action == {"type": "calm_burrow", "max": 6, "days": 3}, r
    assert r[0].reason.startswith("2 citizen(s) in a tantrum walk free") and r[0].priority == 0, r[0]
    # members only: asked (to let the calm out), not first
    m_ = copy.deepcopy(s); m_["society"]["calm_burrow"].update(free=0, members=2)
    r = by_rule(plan(m_, Memory())[0], "calm_burrow")
    assert r and r[0].priority == 2 and "2 kept apart" in r[0].reason, r
    # nothing in a tantrum, nobody kept: not asked; an older bridge (no status): never
    quiet = copy.deepcopy(s); quiet["society"]["calm_burrow"].update(free=0, tantrums=1)
    assert not by_rule(plan(quiet, Memory())[0], "calm_burrow")
    old = copy.deepcopy(s); del old["society"]["calm_burrow"]
    assert not by_rule(plan(old, Memory())[0], "calm_burrow")
    # never held by the strategist nor by the action limit; a recovery rule; its own short cooldown
    m = Memory(); now = abs_tick(s)
    m.steer["calm_burrow"] = {"mode": "hold", "until": now + 10 * TICKS_PER_DAY, "why": "x"}
    allowed, held = select(plan(copy.deepcopy(s), m)[0], s, m)
    assert any(p.rule == "calm_burrow" for p in allowed), held
    import crisis
    assert "calm_burrow" in crisis.RECOVERY_RULES and "calm_burrow" in planner.LIMIT_EXEMPT
    assert planner.PLANNER_CONFIG["calm_burrow_cooldown_ticks"] == 300
    assert planner.AGENDA_THEMES["calm_burrow"] == "keep a tantrum away from the others"


@test("calm burrow (0.104.169): members never left behind: let out when the rule is off or the status fails; the room-less call said; DF ignoring the burrow said once the counts show it")
def _():
    RELEASE = {"type": "calm_burrow", "release": True}
    s = fort()
    s.setdefault("society", {})["calm_burrow"] = {"members": 2, "tantrums": 2, "free": 1}
    off = copy.deepcopy(s); off.setdefault("settings", {})["calm_burrow"] = False
    r = by_rule(plan(copy.deepcopy(off), Memory())[0], "calm_burrow")
    assert r and r[0].action == RELEASE and "switched off" in r[0].reason, r
    off["society"]["calm_burrow"]["members"] = 0
    assert not by_rule(plan(copy.deepcopy(off), Memory())[0], "calm_burrow")         # off, nobody in: nothing
    bad = copy.deepcopy(s); bad["society"]["calm_burrow"] = {"error": "boom"}
    r = by_rule(plan(bad, Memory())[0], "calm_burrow")
    assert r and r[0].action == RELEASE and "can't be read" in r[0].reason, r
    bad = copy.deepcopy(s); bad["society"] = {"error": "boom"}
    r = by_rule(plan(bad, Memory())[0], "calm_burrow")
    assert r and r[0].action == RELEASE, r
    # the last call found no room: said, and asked again
    nr = copy.deepcopy(s); nr["society"]["calm_burrow"].update(members=0, why="no free bedroom at least 15 tiles from the hospitals")
    props, notes = plan(nr, Memory())[:2]
    assert by_rule(props, "calm_burrow") and any("walk free: no free bedroom" in n for n in notes), notes
    # seen outside their burrow most of the time: said
    out = copy.deepcopy(s); out["society"]["calm_burrow"].update(seen_in=4, seen_out=16)
    notes = plan(out, Memory())[1]
    assert any("seen outside their burrow 16 of 20" in n for n in notes), notes
    inside = copy.deepcopy(s); inside["society"]["calm_burrow"].update(seen_in=18, seen_out=2)
    assert not any("seen outside" in n for n in plan(inside, Memory())[1])
    import overseer
    assert "free bedroom" in overseer.short({"type": "calm_burrow", "max": 6, "days": 3})
    assert overseer.short(RELEASE) == "let every dwarf out of the calm-down burrows"


# --- (0.105.3) B "Monastery" (2 Nov): one thief inside kept the only hatch shut 2.5 hours ---

def b_thief(armed=6, inside=True, closed=True, alert=True, policy="never", fps=None, more=()):
    """B after the siege: Trustdaub (7527) inside, the hatch shut by the watcher."""
    s = entrances({"sealed": True, "equipment": [{"id": 1, "kind": "hatch"}], "closed": closed}, armed=True)
    s["entrances"]["citizens_outside"] = 6
    s["entrances"]["intruders_inside"] = [7527] if inside else []
    s["others_on_map"]["threats"] = [{"id": 7527, "name": "Trustdaub, Human Maceman", "invader": True,
                                      "can_reach_dwarves": True, "great_danger": False, "flier": False,
                                      "distance_to_nearest_dwarf": 18, "levels_from_nearest_dwarf": 4,
                                      "layer": "fort_levels", "pos": {"x": 40, "y": 40, "z": 170}}] + list(more)
    s["others_on_map"]["threats_that_can_reach_dwarves"] = sum(
        1 for t in s["others_on_map"]["threats"] if t.get("can_reach_dwarves"))
    s["civ_alert"] = alert
    s["settings"]["attack_policy"] = policy
    for i, q in enumerate(s["military"]["squads"]):
        q["members"] = 8
        q["power"] = {"power": 3, "armored": 0, "skill": 0, "armed": armed if i == 1 else 0}
    if fps:
        s["fps_low"] = fps
    return s


@test("0.105.3 B: a lone thief inside -> the gates open, no arming, one armed squad sent (policy never)")
def _():
    s = b_thief()
    m = Memory(ai_alert_raised=True)
    note_cycle(s, m)
    p, notes = plan(s, m)
    g = by_rule(p, "gates")
    assert g and g[0].action == {"type": "open_gates"} and "inside the fort" in g[0].reason, g
    a = by_rule(p, "squad_attack")
    assert len(a) == 1 and a[0].action == {"type": "squad_orders", "squad_id": s["military"]["squads"][1]["id"],
                                           "kill": [7527]}, a
    # not armed again while he's the only one (the watcher off, gates open)
    s2 = b_thief(closed=False)
    s2["entrances"]["armed"] = False
    p2, notes2 = plan(s2, m)
    assert not by_rule(p2, "gates"), by_rule(p2, "gates")
    assert any("gates stay open" in n for n in notes2), notes2
    # a squad already on him: no second one (B sent all four in turn)
    s3 = b_thief()
    s3["military"]["squads"][0].update(ai_orders=1, kill_ids=[7527])
    assert not by_rule(plan(s3, m)[0], "squad_attack")


@test("0.105.3 B: a lone thief inside and no armed squad -> said (0.105.35: not Needs you), the gates still open")
def _():
    s = b_thief(armed=0)
    m = Memory(ai_alert_raised=True)
    p, notes = plan(s, m)
    assert not by_rule(p, "squad_attack")
    assert by_rule(p, "gates")[0].action == {"type": "open_gates"}
    assert not [n for n in notes if n.startswith("[you] ") and "Trustdaub" in n], notes
    said = [n for n in notes if "Trustdaub" in n and "no squad has anyone armed" in n]
    assert len(said) == 1, notes


@test("0.105.3 B: the alarm for a lone thief inside is held half a day at most")
def _():
    s = b_thief()
    m = Memory(ai_alert_raised=True)
    note_cycle(s, m)
    off = {"type": "civ_alert", "on": False}
    assert not any(x.action == off for x in plan(s, m)[0])          # just found: the alarm stays for now
    later = copy.deepcopy(s)
    later["date"]["tick"] += PLANNER_CONFIG["lone_intruder_alert_ticks"]
    note_cycle(later, m)
    a = [x for x in plan(later, m)[0] if x.action == off]
    assert a and "inside the fort" in a[0].reason, a
    # the player's alarm (not the AI's) is never lowered
    m2 = Memory(ai_alert_raised=False)
    note_cycle(s, m2); note_cycle(later, m2)
    assert not any(x.action == off for x in plan(later, m2)[0])


@test("0.105.3: the thief read as inside before still counts when he walks near the gate on his way out")
def _():
    s = b_thief()
    m = Memory(ai_alert_raised=True)
    note_cycle(s, m)
    near_gate = b_thief(inside=False, closed=False)
    near_gate["entrances"]["armed"] = False
    note_cycle(near_gate, m)
    assert not by_rule(plan(near_gate, m)[0], "gates")
    # a NEW enemy: read afresh (he's at the gate, not inside): the gates are armed
    more = b_thief(inside=False, closed=False, more=[{"id": 8000, "name": "goblin", "invader": True,
                                                     "can_reach_dwarves": True}])
    more["entrances"]["armed"] = False
    note_cycle(more, m)
    g = by_rule(plan(more, m)[0], "gates")
    assert g and g[0].action == {"type": "arm_gates"}, g


@test("0.105.8 A: one thief outside, a squad on him, the hatch shut on 10 citizens -> open, not armed again")
def _():
    s = b_thief(inside=False, policy="always")
    s["entrances"]["citizens_outside"] = 10
    s["military"]["squads"][1].update(ai_orders=1, kill_ids=[7527])
    m = Memory(ai_alert_raised=True)
    note_cycle(s, m)
    g = by_rule(plan(s, m)[0], "gates")
    assert g and g[0].action == {"type": "open_gates"} and "10 citizen(s) shut out" in g[0].reason, g
    s2 = copy.deepcopy(s)
    s2["entrances"]["armed"] = False
    s2["entrances"]["entrances"][0]["closed"] = False
    p2, notes2 = plan(s2, m)
    assert not by_rule(p2, "gates") and any("squads in and the citizens out" in n for n in notes2), notes2
    # no squad on him (or only an unarmed one): the gates are watched as before
    s3 = b_thief(inside=False, closed=False, policy="never")
    s3["entrances"]["armed"] = False
    s3["military"]["squads"][0].update(ai_orders=1, kill_ids=[7527])     # (squad 0 unarmed)
    g3 = by_rule(plan(s3, Memory())[0], "gates")
    assert g3 and g3[0].action == {"type": "arm_gates"}, g3
    # a third enemy, or a great danger: a siege, as before
    big = b_thief(inside=False, policy="always", more=[
        {"id": 900 + i, "name": "goblin", "invader": True, "can_reach_dwarves": True} for i in range(2)])
    big["military"]["squads"][1].update(ai_orders=1, kill_ids=[7527, 900, 901])
    gb = by_rule(plan(big, Memory(ai_alert_raised=True))[0], "gates")
    assert not gb or gb[0].action != {"type": "open_gates"}, gb


@test("0.105.8 B: one thief outside, no squad on him: the AI's alarm comes down after half a day")
def _():
    s = b_thief(inside=False, armed=0)
    m = Memory(ai_alert_raised=True)
    note_cycle(s, m)
    off = {"type": "civ_alert", "on": False}
    assert not any(x.action == off for x in plan(s, m)[0])
    later = copy.deepcopy(s)
    later["date"]["tick"] += PLANNER_CONFIG["lone_intruder_alert_ticks"]
    note_cycle(later, m)
    a = [x for x in plan(later, m)[0] if x.action == off]
    assert a and "half a day" in a[0].reason, a
    assert not any(x.action == {"type": "civ_alert", "on": True} for x in plan(later, m)[0])   # not raised again
    # a siege (6 enemies): the alarm stays
    goblins = [{"id": 900 + i, "name": "goblin", "invader": True, "can_reach_dwarves": True} for i in range(6)]
    big = b_thief(inside=False, armed=0, more=goblins)
    m2 = Memory(ai_alert_raised=True)
    note_cycle(big, m2)
    big2 = copy.deepcopy(big); big2["date"]["tick"] += 3 * PLANNER_CONFIG["lone_intruder_alert_ticks"]
    note_cycle(big2, m2)
    assert not any(x.action == off for x in plan(big2, m2)[0])


@test("0.105.3: a real siege (many invaders, or one inside with more outside, or a beast) -> as before")
def _():
    goblins = [{"id": 900 + i, "name": "goblin", "invader": True, "can_reach_dwarves": True} for i in range(6)]
    s = b_thief(inside=False, closed=False, more=goblins, policy="ordinary")
    s["entrances"]["armed"] = False
    s["entrances"]["intruders_inside"] = [7527, 900, 901]        # some inside, too many for "lone"
    m = Memory()
    note_cycle(s, m)
    p, _ = plan(s, m)
    assert by_rule(p, "gates")[0].action == {"type": "arm_gates"}
    assert len(by_rule(p, "squad_attack")) == 1                  # the one armed squad, all targets
    assert len(by_rule(p, "squad_attack")[0].action["kill"]) == 7
    # one inside, the rest of the siege held off outside the gate: the gates hold
    out = b_thief(more=[{"id": 950, "name": "goblin", "invader": True, "can_reach_dwarves": False}])
    assert not by_rule(plan(out, Memory())[0], "gates")         # armed, closed: left shut
    from planner_military import lone_intruders
    assert not lone_intruders(out, PLANNER_CONFIG)
    # a great danger, a flier or an older bridge without the map: never "lone"
    for change in ({"great_danger": True}, {"flier": True}, {"destroyer": True}):
        x = b_thief()
        x["others_on_map"]["threats"][0].update(change)
        assert not lone_intruders(x, PLANNER_CONFIG), change
    old = b_thief()
    del old["entrances"]["intruders_inside"]
    assert not lone_intruders(old, PLANNER_CONFIG)
    assert not by_rule(plan(old, Memory())[0], "gates")         # the old behaviour: left shut


@test("0.105.3: the AI's lockdown is capped: 2 days with no new enemy, the game slow or dwarves out -> opened")
def _():
    # (0.105.4 review) the cap is for enemies already inside: the lone-intruder
    # path is switched off here (lone_intruder_max 0) so the cap alone is tested
    cfg = dict(PLANNER_CONFIG, lone_intruder_max=0)
    s = b_thief()
    s["entrances"]["citizens_outside"] = 0
    m = Memory(ai_alert_raised=True)
    note_cycle(s, m, cfg)
    assert not by_rule(plan(s, m, cfg)[0], "gates")
    later = copy.deepcopy(s)
    later["date"]["tick"] += PLANNER_CONFIG["lockdown_max_days"] * TICKS_PER_DAY
    note_cycle(later, m, cfg)
    assert not by_rule(plan(later, m, cfg)[0], "gates")       # fast, nobody shut out: held
    later["fps_low"] = 3
    notes = note_cycle(later, m, cfg)
    assert any("open and the alarm comes down" in n for n in notes), notes
    p, _ = plan(later, m, cfg)
    assert by_rule(p, "gates")[0].action == {"type": "open_gates"}
    assert any(x.action == {"type": "civ_alert", "on": False} for x in p)
    # dwarves shut out works too (the game fast)
    m2 = Memory(ai_alert_raised=True)
    s2 = b_thief()
    note_cycle(s2, m2, cfg)
    l2 = copy.deepcopy(s2)
    l2["date"]["tick"] += PLANNER_CONFIG["lockdown_max_days"] * TICKS_PER_DAY
    note_cycle(l2, m2, cfg)
    assert by_rule(plan(l2, m2, cfg)[0], "gates")[0].action == {"type": "open_gates"}
    # then a new enemy: closed again
    more = copy.deepcopy(later)
    more["entrances"]["armed"] = False
    more["others_on_map"]["threats"].append({"id": 8001, "name": "goblin", "invader": True, "can_reach_dwarves": True})
    notes = note_cycle(more, m, cfg)
    assert any("may close again" in n for n in notes), notes
    assert by_rule(plan(more, m, cfg)[0], "gates")[0].action == {"type": "arm_gates"}


@test("0.105.4 review: two enemies camped outside a slow fort never lift the lockdown; one walking in re-closes a lifted one")
def _():
    camp = [{"id": 950 + i, "name": "goblin", "invader": True, "can_reach_dwarves": False} for i in range(2)]
    s = b_thief(inside=False, fps=3)
    s["others_on_map"]["threats"] = list(camp)
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    m = Memory(ai_alert_raised=True)
    note_cycle(s, m)
    later = copy.deepcopy(s)
    later["date"]["tick"] += 5 * TICKS_PER_DAY
    notes = note_cycle(later, m)
    assert not any("alarm comes down" in n for n in notes), notes
    p, _ = plan(later, m)
    assert not by_rule(p, "gates") and not any(x.action == {"type": "civ_alert", "on": False} for x in p)
    # a lockdown lifted for a thief inside; then one of the camped two (already seen) walks in
    cfg = dict(PLANNER_CONFIG, lone_intruder_max=0)
    t = b_thief(fps=3)
    m = Memory(ai_alert_raised=True)
    seen = copy.deepcopy(t)
    seen["others_on_map"]["threats"].append(dict(camp[0]))       # seen outside once, then hid
    note_cycle(seen, m, cfg)
    t["date"]["tick"] += 3 * TICKS_PER_DAY
    note_cycle(t, m, cfg)
    assert m.atlas["lockdown"].get("released")                   # only the thief inside left
    t["others_on_map"]["threats"].append(dict(camp[0]))
    walked = copy.deepcopy(t)
    walked["others_on_map"]["threats"][-1]["can_reach_dwarves"] = True
    walked["entrances"]["armed"] = False
    notes = note_cycle(walked, m, cfg)
    assert "released" not in m.atlas["lockdown"] and any("may close again" in n for n in notes), notes
    assert by_rule(plan(walked, m, cfg)[0], "gates")[0].action == {"type": "arm_gates"}


@test("0.105.3: the lockdown cap never opens on a siege or a great danger")
def _():
    goblins = [{"id": 900 + i, "name": "goblin", "invader": True, "can_reach_dwarves": False} for i in range(5)]
    s = b_thief(inside=False, more=goblins, fps=3)
    m = Memory(ai_alert_raised=True)
    note_cycle(s, m)
    later = copy.deepcopy(s)
    later["date"]["tick"] += 5 * TICKS_PER_DAY
    note_cycle(later, m)
    assert not by_rule(plan(later, m)[0], "gates")
    beast = b_thief(inside=False, fps=3)
    beast["others_on_map"]["threats"][0]["great_danger"] = True
    m = Memory(ai_alert_raised=True)
    note_cycle(beast, m)
    later = copy.deepcopy(beast)
    later["date"]["tick"] += 5 * TICKS_PER_DAY
    note_cycle(later, m)
    p, _ = plan(later, m)
    assert not by_rule(p, "gates") and not any(x.action == {"type": "civ_alert", "on": False} for x in p)


@test("0.105.3 B: no new pasture assignments while the AI's gates are shut (26 PenLargeAnimal jobs)")
def _():
    s = b_thief(inside=False)
    s["society"] = {"vacant": [], "grazers_unpastured": 6, "pastures": 2, "grazer_tiles": 60,
                    "grazer_tiles_smallest": 10, "pasture_spare": 200}
    p, notes = plan(s, Memory())
    assert not [x for x in p if x.action.get("type") in ("pasture", "make_pasture", "nest_boxes")], p
    assert any("pasture assignment(s) wait" in n for n in notes), notes
    s["entrances"]["entrances"][0]["closed"] = False                 # gates open again
    assert by_rule(plan(s, Memory())[0], "pasture")
    s["entrances"]["armed"] = False
    assert by_rule(plan(s, Memory(gate_closed_by_ai=True))[0], "pasture") == []   # the AI's lever pulled


@test("0.105.3 A: shut for a sneaker who hid again, 9 citizens outside -> gates and alarm open in hours, not days")
def _():
    # A (2 Nov 09:39): the swordsman seen sneaking, then gone; the hatch shut, 9 outside, 39 visitors
    s = b_thief(inside=False, policy="ordinary")
    m = Memory(ai_alert_raised=True)
    note_cycle(s, m)                                             # seen: the lockdown begins
    gone = copy.deepcopy(s)
    gone["others_on_map"]["threats"] = []
    gone["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    gone["entrances"]["citizens_outside"] = 9
    gone["others_on_map"]["visitors"] = 39
    off = {"type": "civ_alert", "on": False}
    for i in range(1, 4):                                         # three quiet cycles, an hour apart
        gone["date"]["tick"] += 50
        note_cycle(gone, m)
    p, _ = plan(gone, m)
    assert not by_rule(p, "gates") and not any(x.action == off for x in p)   # 3 hours: not yet
    gone["date"]["tick"] += PLANNER_CONFIG["lockdown_clear_ticks"]
    note_cycle(gone, m)
    p, _ = plan(gone, m)
    g = by_rule(p, "gates")
    assert g and g[0].action == {"type": "open_gates"} and "9 citizen(s) shut out" in g[0].reason, g
    assert any(x.action == off for x in p)
    # nobody shut out (gates already open): a sneaker alone still ends after a day, not 3
    m2 = Memory(ai_alert_raised=True)
    s2 = b_thief(inside=False, closed=False, policy="ordinary")
    s2["entrances"]["armed"] = False
    note_cycle(s2, m2)
    q = copy.deepcopy(s2)
    q["others_on_map"]["threats"] = []
    q["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    for _ in range(3):
        q["date"]["tick"] += 50
        note_cycle(q, m2)
    assert not any(x.action == off for x in plan(q, m2)[0])
    q["date"]["tick"] += PLANNER_CONFIG["small_alert_ticks"]
    note_cycle(q, m2)
    a = [x for x in plan(q, m2)[0] if x.action == off]
    assert a and "only 1 enemy" in a[0].reason, a


@test("0.105.3 A: a siege still in sight (held off at the gate) keeps gates and alarm as before")
def _():
    goblins = [{"id": 900 + i, "name": "goblin", "invader": True, "can_reach_dwarves": False} for i in range(5)]
    s = b_thief(inside=False, policy="ordinary")
    s["others_on_map"]["threats"] = goblins
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s["entrances"]["citizens_outside"] = 9
    m = Memory(ai_alert_raised=True)
    for _ in range(5):
        s["date"]["tick"] += 300
        note_cycle(s, m)
    p, _ = plan(s, m)
    assert not by_rule(p, "gates") and not any(x.action == {"type": "civ_alert", "on": False} for x in p)


@test("wells (0.105.3, 0.105.4 review): the old cavern refusal tried once (a memory flag), toward the survey's lake")
def _():
    s = fort()
    s["buildings"]["other"].pop("Well", None)
    s["projects"]["open"] = []
    s["dwarves"]["needs_medical_care"] = 4
    s["water"] = {"tick": abs_tick(s), "bodies": [
        {"kind": "surface", "tiles": 25, "stagnant_share": 100, "nearest": {"x": 59, "y": 200, "z": 172, "d": 77}},
        {"kind": "cavern", "tiles": 12412, "stagnant_share": 0, "nearest": {"x": 135, "y": 131, "z": 136, "d": 80}}]}
    m = Memory()
    m.well_failure = ("no open drop from a free floor inside the fort to clean water; no pond, brook or river "
                      "within 40 tiles of the surface entrances to put a well beside")
    m.cavern_well_failure = ("no floor inside the fort over cavern water with solid rock between "
                             "(cavern floor, not water, below; no cavern water within reach)")
    w = by_rule(plan(copy.deepcopy(s), m)[0], "well")
    assert w and w[0].action == {"type": "place_well", "cavern": True, "urgent": True, "gallery": 80,
                                 "toward": [{"x": 135, "y": 131, "z": 136}]}, [x.action for x in w]
    assert "tunnel" in w[0].reason and not m.cavern_gallery_retried     # plan() only reads memory
    # (0.105.4 review) its refusal, cut to 300 characters with no word of the gallery: the flag, not
    # the text, says the retry is spent
    long_refusal = "no floor inside the fort over cavern water with solid rock between (" + "x" * 400 + ")"
    record([(w[0], {"ok": False, "error": long_refusal})], s, m)
    assert m.cavern_gallery_retried and "gallery" not in m.cavern_well_failure
    props, notes = plan(copy.deepcopy(s), m)
    assert not [x for x in by_rule(props, "well") if x.action.get("cavern")]
    assert any("no cavern well either" in n for n in notes), notes
    # galleries off: the old refusal stands
    cfg_off = dict(PLANNER_CONFIG, cavern_well_gallery=0)
    m2 = Memory()
    m2.well_failure = m.well_failure
    m2.cavern_well_failure = "no floor inside the fort over cavern water with solid rock between"
    props = plan(copy.deepcopy(s), m2, cfg_off)[0]
    assert not [x for x in by_rule(props, "well") if x.action.get("cavern")]


@test("wells (0.105.4 review): a cavern no dwarf has found: the Rules switch on allows it; off, the AI decides (0.105.35)")
def _():
    s = fort()
    s["buildings"]["other"].pop("Well", None)
    s["projects"]["open"] = []
    s["dwarves"]["needs_medical_care"] = 4
    s["water"] = {"tick": abs_tick(s), "bodies": [
        {"kind": "cavern", "tiles": 12412, "stagnant_share": 0, "nearest": {"x": 135, "y": 131, "z": 125, "d": 80}}]}
    for l in s["map"]["layers"]:
        if l["name"] == "Cavern1":
            l["discovered"] = False                    # Hammerstirred: Cavern1 undiscovered
    m = Memory()
    m.well_failure = "no open drop from a free floor inside the fort to clean water (the water below is in a cavern)"
    # (0.105.35) the switch off: no soldiers for what comes out -> not now, and nothing asked of the player
    s.setdefault("military", {})["soldiers"] = 0
    props, notes = plan(copy.deepcopy(s), m)
    assert not [x for x in by_rule(props, "well") if x.action.get("cavern")], [x.action for x in by_rule(props, "well")]
    assert any("would open Cavern1 for the first time" in n and "0 soldier(s)" in n for n in notes), notes
    assert not any("Rules tab" in n or n.startswith("[you]") and "cavern" in n for n in notes), notes
    # short of water (4 injured) and soldiers: the AI opens it itself
    s["military"]["soldiers"] = 5
    w = [x for x in by_rule(plan(copy.deepcopy(s), m)[0], "well") if x.action.get("cavern")]
    assert w and w[0].action.get("open_caverns") is True and "the AI's call" in w[0].reason, [x.action for x in w]
    s["military"]["soldiers"] = 0
    s["settings"] = dict(s.get("settings") or {}, open_caverns=True)
    w = [x for x in by_rule(plan(copy.deepcopy(s), m)[0], "well") if x.action.get("cavern")]
    assert w and w[0].action.get("open_caverns") is True, [x.action for x in w]
    # a cavern already found: no switch needed
    s["settings"]["open_caverns"] = False
    for l in s["map"]["layers"]:
        l["discovered"] = True
    w = [x for x in by_rule(plan(copy.deepcopy(s), m)[0], "well") if x.action.get("cavern")]
    assert w and "open_caverns" not in w[0].action, [x.action for x in w]


@test("water (0.105.3): the survey and the cistern carry the brain's tunnel reach; the shore well its reach")
def _():
    s = fort()
    s["buildings"]["other"].pop("Well", None)
    s["projects"]["open"] = []
    s["dwarves"]["needs_medical_care"] = 0
    s["water"] = {"none": True}
    props = plan(copy.deepcopy(s), Memory())[0]
    sv = by_rule(props, "water")
    assert sv and sv[0].action == {"type": "survey_water", "tunnel": 70}, [x.action for x in sv]
    w = by_rule(props, "well")
    assert w and w[0].action.get("shore_reach") == 60, [x.action for x in w]


def _vanished(n_seen, outside=0, visitors_outside=None, visitors=0):
    """An ambush of n_seen seen, then hidden; the AI's hatch shut; quiet past every short wait."""
    goblins = [{"id": 700 + i, "name": "goblin", "invader": True, "can_reach_dwarves": True} for i in range(n_seen)]
    s = b_thief(inside=False, policy="ordinary")
    s["others_on_map"]["threats"] = goblins
    s["others_on_map"]["threats_that_can_reach_dwarves"] = n_seen
    m = Memory(ai_alert_raised=True)
    note_cycle(s, m)
    gone = copy.deepcopy(s)
    gone["others_on_map"]["threats"] = []
    gone["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    gone["entrances"]["citizens_outside"] = outside
    gone["others_on_map"]["visitors"] = visitors
    if visitors_outside is not None:
        gone["entrances"]["visitors_outside"] = visitors_outside
    for _ in range(3):
        gone["date"]["tick"] += 50
        note_cycle(gone, m)
    gone["date"]["tick"] += PLANNER_CONFIG["small_alert_ticks"]
    note_cycle(gone, m)
    from planner_military import quick_clear
    return quick_clear(gone, m, PLANNER_CONFIG)


@test("0.105.4 review: a bigger ambush that hid again keeps the normal quiet wait (no quick reopen)")
def _():
    assert _vanished(1, outside=9)                               # A's sneaker: quick
    assert _vanished(2)                                          # two, nobody shut out: after a day
    assert not _vanished(5, outside=9)                           # five vanished: the 3 quiet days
    assert not _vanished(5)


@test("0.105.4 review: only visitors OUTSIDE count as shut out (a tavern's 20+ inside don't)")
def _():
    assert "visitors shut out" not in _vanished(1, visitors=39)              # all inside: the day's wait instead
    assert "39 visitors shut out" in _vanished(1, visitors=39, visitors_outside=39)
    assert "visitors shut out" not in _vanished(1, visitors=39, visitors_outside=3)


@test("0.105.4 review: a cycle with no gate map doesn't flip the lone-thief case (the stored ids count)")
def _():
    from planner_military import lone_intruders
    s = b_thief()
    m = Memory(ai_alert_raised=True)
    note_cycle(s, m)
    assert m.atlas["lockdown"].get("lone_ids") == [7527]
    nomap = copy.deepcopy(s)
    del nomap["entrances"]["intruders_inside"]
    assert lone_intruders(nomap, PLANNER_CONFIG, memory=m) == [7527]
    note_cycle(nomap, m)
    assert by_rule(plan(nomap, m)[0], "gates")[0].action == {"type": "open_gates"}
    assert not lone_intruders(nomap, PLANNER_CONFIG)             # never seen inside: as before


@test("0.105.4 review: a squad on other AI orders isn't 'after the thief'; all pasture actions held leaves none")
def _():
    s = b_thief()
    s["military"]["squads"][0].update(ai_orders=1, kill_ids=None)          # a guard order, say: no kill list
    a = by_rule(plan(s, Memory(ai_alert_raised=True))[0], "squad_attack")
    assert len(a) == 1 and a[0].action["kill"] == [7527], a
    from planner_military import _pasture_hold
    held = [planner.Proposal("pasture", {"type": "pasture", "count": 3}, "x", 3)]
    assert _pasture_hold(b_thief(inside=False), Memory(), held, []) == []
    # in plan(): when the hold leaves nothing, nothing comes back (it was `or proposals`)
    old = planner._pasture_hold
    try:
        planner._pasture_hold = lambda s_, m_, props, notes: []
        assert plan(b_thief(inside=False), Memory())[0] == []
    finally:
        planner._pasture_hold = old


def overseer_short(a):
    import overseer
    return overseer.short(a)

def _fort_b():
    """(0.105.5) Hammerstirred fort B (2 Nov): 5 surface plots, 4 fallow, drink 0-11 for 7 dwarves,
    seeds mostly underground crops plus a few surface brewables."""
    s = fort()
    s["dwarves"]["total"] = 7
    s["stocks"]["drink"] = 4
    s["buildings"]["other"].pop("Well", None)
    s["buildings"]["zones"].pop("WaterSource", None)
    s["dwarves"]["needs_medical_care"] = 0
    s.setdefault("society", {})["parched"] = 0
    plots = [{"id": i, "tiles": 9, "underground": False, "crops": ["", "", "", ""], "fallow": True,
              "ok_now": False, "options": 1, "options_any": 2} for i in range(1, 6)]
    plots[0].update(fallow=False, ok_now=True, crops=["", "BERRIES_PRICKLE", "", ""])
    s["farms"] = {"plots": 5, "built": 5, "tiles": 45, "season": "summer", "plots_surface": 5, "plots_underground": 0,
                  "plot_list": plots, "crops": {
                      "MUSHROOM_HELMET_PLUMP": {"name": "plump helmet", "seeds": 60, "brews": "plant",
                                                "underground": True, "seasons": ["spring", "summer", "autumn", "winter"]},
                      "BERRIES_PRICKLE": {"name": "prickle berry", "seeds": 8, "brews": "plant",
                                          "underground": False, "seasons": ["spring", "summer", "autumn", "winter"]}}}
    return s


@test("farm crops (0.105.5): fort B: plots fallow while seeds grow there and drink is short -> set_farm_crops, brewable first, urgent")
def _():
    s = _fort_b()
    m = Memory()
    fc = by_rule(plan(copy.deepcopy(s), m)[0], "farm_crops")
    assert fc and fc[0].action == {"type": "set_farm_crops", "drink": True} and fc[0].priority == 1, fc
    record([(fc[0], {"ok": True})], s, m)
    assert m.farm_steer == "crops" and "autofarm" not in m.tools_seen_on
    m.last_fired.clear()
    # set: the plots grow now, so nothing more; autofarm isn't switched back on, thresholds left alone
    for p in s["farms"]["plot_list"]:
        p.update(fallow=False, ok_now=True)
    props = plan(copy.deepcopy(s), m)[0]
    assert not by_rule(props, "farm_crops") and not by_rule(props, "crops"), rules(props)
    s["tools"]["autofarm"] = False
    assert not [p for p in by_rule(plan(copy.deepcopy(s), m)[0], "tools") if p.action.get("name") == "autofarm"]
    # drink fine: a lower priority, no brewable steer
    s = _fort_b()
    s["stocks"]["drink"] = 200
    fc = by_rule(plan(copy.deepcopy(s), Memory())[0], "farm_crops")
    assert fc and fc[0].action == {"type": "set_farm_crops", "drink": False} and fc[0].priority == 4, fc
    assert overseer_short({"type": "set_farm_crops", "drink": True}) == "set each farm plot's crops (brewable first)"


@test("farm crops (0.105.5): surface plots that can grow nothing in any season are said, and underground plots are laid out")
def _():
    s = _fort_b()
    s["farms"]["crops"]["BERRIES_PRICKLE"]["seeds"] = 0
    for p in s["farms"]["plot_list"]:
        p.update(dead=True, options=0, options_any=0, fallow=True, ok_now=False)
    props, notes = plan(copy.deepcopy(s), Memory())[:2]
    assert not by_rule(props, "farm_crops"), by_rule(props, "farm_crops")
    assert any("can grow nothing" in n and "underground plots" in n for n in notes), notes
    f = by_rule(props, "farms")
    assert f and f[0].action.get("underground") is True and "outside" not in f[0].action and f[0].priority == 2, f
    assert "underground" in f[0].reason, f[0].reason


@test("water zone (0.105.5): drink short with no well -> a water source, even with nobody parched or injured")
def _():
    s = _fort_b()
    s["water"] = {"bodies": [{"kind": "cavern", "nearest": {"d": 30, "x": 133, "y": 130, "z": 5}, "stagnant_share": 0},
                             {"kind": "surface", "nearest": {"d": 60, "x": 3, "y": 3, "z": 40}, "stagnant_share": 0}]}
    s["others_on_map"]["threats"] = []
    w = by_rule(plan(s, Memory())[0], "water_zone")
    assert w and [p["x"] for p in w[0].action["points"]] == [133, 3] and "drink is short" in w[0].reason, w
    s["stocks"]["drink"] = 200
    assert not by_rule(plan(s, Memory())[0], "water_zone")


@test("farms review (0.105.7) MUST 1: no autofarm thresholds or autofarm switched on in a plan with farm_crops; record keeps \"crops\"")
def _():
    s = _fort_b()
    s["supplies"] = {**(s.get("supplies") or {}), "brewable_plants": 0, "brewable_growths": 0}
    s["tools"]["autofarm"] = False
    m = Memory()
    props = plan(copy.deepcopy(s), m)[0]
    assert by_rule(props, "farm_crops"), rules(props)
    assert not [p for p in props if p.action.get("type") == "farm_thresholds"], rules(props)
    assert not [p for p in props if p.action.get("type") == "tool" and p.action.get("name") == "autofarm"], rules(props)
    from planner import Proposal
    th = Proposal("crops", {"type": "farm_thresholds", "thresholds": {"X": 300}, "steer": "drink"}, "", 2)
    fc = Proposal("farm_crops", {"type": "set_farm_crops", "drink": True}, "", 1)
    record([(fc, {"ok": True}), (th, {"ok": True})], s, m)
    assert m.farm_steer == "crops", m.farm_steer
    # owned: the thresholds rule stays quiet on later cycles too
    m.last_fired.clear()
    props = plan(copy.deepcopy(s), m)[0]
    assert not [p for p in props if p.action.get("type") == "farm_thresholds"], rules(props)


@test("farms review (0.105.7) SHOULD 2: autofarm back as the fallback (no plot list, only dead plots); the player's autofarm kept")
def _():
    s = _fort_b()
    s["tools"]["autofarm"] = False
    m = Memory(farm_steer="crops")
    old = copy.deepcopy(s)
    old["farms"].pop("plot_list")                       # an old bridge / a failed plot list
    t = [p for p in by_rule(plan(old, m)[0], "tools") if p.action.get("name") == "autofarm"]
    assert t and t[0].action["enabled"] is True, t
    dead = copy.deepcopy(s)
    for p in dead["farms"]["plot_list"]:
        p["dead"] = True
    assert [p for p in by_rule(plan(dead, m)[0], "tools") if p.action.get("name") == "autofarm"]
    record([(t[0], {"ok": True, "enabled": True})], old, m)
    assert m.farm_steer == ""                            # autofarm's again
    # the player switches autofarm on while the AI owns the crops: theirs, said once
    m = Memory(farm_steer="crops")
    s["tools"]["autofarm"] = True
    notes = note_cycle(copy.deepcopy(s), m)
    assert m.farm_crops_player and any("autofarm was switched back on" in n for n in notes), notes
    props = plan(copy.deepcopy(s), m)[0]
    assert not by_rule(props, "farm_crops") and not [p for p in props if p.action.get("type") == "farm_thresholds"]
    s["tools"]["autofarm"] = False                        # off again: the AI's crops resume
    note_cycle(copy.deepcopy(s), m)
    assert not m.farm_crops_player and m.farm_steer == "crops"


@test("farms review (0.105.7) SHOULD 6: unknown drink isn't short (no priority 1); the dead-plot note once a season")
def _():
    s = _fort_b()
    s["stocks"].pop("drink")
    fc = by_rule(plan(copy.deepcopy(s), Memory())[0], "farm_crops")
    assert fc and fc[0].action["drink"] is False and fc[0].priority == 4, fc
    s = _fort_b()
    for p in s["farms"]["plot_list"]:
        p.update(dead=True, options=0, options_any=0)
    m = Memory()
    n1 = plan(copy.deepcopy(s), m)[1]
    m.farm_dead_noted = ""
    assert any("can grow nothing" in n for n in n1)
    from planner_industry import _farm_crops_rule
    notes = []
    _farm_crops_rule(planner.normalize(copy.deepcopy(s)), m, PLANNER_CONFIG, [], notes)
    _farm_crops_rule(planner.normalize(copy.deepcopy(s)), m, PLANNER_CONFIG, [], notes)
    assert sum("can grow nothing" in n for n in notes) == 1, notes


@test("farms review (0.105.7) SHOULD 5: underground plots just laid out count until the report shows them")
def _():
    s = _fort_b()
    s["farms"]["crops"]["BERRIES_PRICKLE"]["seeds"] = 0
    for p in s["farms"]["plot_list"]:
        p.update(dead=True, options=0, options_any=0)
    m = Memory()
    f = by_rule(plan(copy.deepcopy(s), m)[0], "farms")
    assert f and f[0].action.get("underground"), f
    record([(f[0], {"ok": True, "tiles": 40})], s, m)
    m.last_fired.clear()
    assert not by_rule(plan(copy.deepcopy(s), m)[0], "farms"), "asked again before the plots show"


@test("water zone review (0.105.7) SHOULD 4: none while a threat can reach the dwarves; no cavern water near a cavern danger; capped")
def _():
    s = _fort_b()
    s["others_on_map"]["threats"] = []
    s["water"] = {"bodies": [{"kind": "cavern", "nearest": {"d": 30, "x": 133, "y": 130, "z": 5}, "stagnant_share": 0},
                             {"kind": "surface", "nearest": {"d": 400, "x": 3, "y": 3, "z": 40}, "stagnant_share": 0}]}
    w = by_rule(plan(copy.deepcopy(s), Memory())[0], "water_zone")
    assert w and [p["x"] for p in w[0].action["points"]] == [133], w       # the far pond is past the cap
    s["others_on_map"]["threats"] = [{"name": "a crundle", "layer": "cavern 1", "pos": {"x": 1, "y": 1, "z": 1}}]
    props, notes = plan(copy.deepcopy(s), Memory())[:2]
    assert not by_rule(props, "water_zone"), by_rule(props, "water_zone")
    s["others_on_map"]["threats"] = []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    props, notes = plan(copy.deepcopy(s), Memory())[:2]
    assert not by_rule(props, "water_zone") and any("threat can reach" in n for n in notes), notes


def _thirsty_b():
    """(0.105.23) B, the Monastery (2 Nov 23:20): drink 3 a dwarf, the farm target met with plump helmets."""
    from planner import farm_target
    s = _fort_b()
    s["dwarves"]["total"] = 46
    s["stocks"]["drink"] = 138
    s["farms"]["crops"]["BERRIES_PRICKLE"]["seeds"] = 0
    s["farms"]["crops"]["MUSHROOM_HELMET_PLUMP"]["seeds"] = 200
    want = farm_target(s, {}, 46, PLANNER_CONFIG)
    plots = [{"id": 1, "tiles": want, "underground": True, "crops": ["MUSHROOM_HELMET_PLUMP"] * 4, "fallow": False,
              "ok_now": True, "options": 1, "options_any": 1}]
    plots += [{"id": i, "tiles": 9, "underground": False, "crops": ["", "", "", ""], "fallow": True, "ok_now": False,
               "options": 0, "options_any": 0, "dead": True} for i in range(2, 6)]
    s["farms"].update(plot_list=plots, plots=5, plots_underground=1, plots_surface=4, tiles=want + 36)
    return s, want


@test("4b farms (0.105.23): drink under its target -> more farm tiles for the brewable crops, capped, underground for helmets")
def _():
    from planner import thirsty_farm_extra
    import math
    s, want = _thirsty_b()
    f = by_rule(plan(copy.deepcopy(s), Memory())[0], "farms")
    assert f and f[0].action.get("underground") is True and "outside" not in f[0].action, f
    extra = min(math.ceil(want * PLANNER_CONFIG["farm_thirsty_share"]), PLANNER_CONFIG["farm_thirsty_max_tiles"], 200)
    assert f[0].action["tiles"] == max(4, extra) and "drink is under its target" in f[0].reason, (f[0].action, f[0].reason)
    # capped by the brewable seeds there are to sow
    s2 = copy.deepcopy(s)
    s2["farms"]["crops"]["MUSHROOM_HELMET_PLUMP"]["seeds"] = 7
    assert thirsty_farm_extra(s2, Memory(), 46, PLANNER_CONFIG, want) == (7, True)
    # drink at its target: the farm target as it was (met)
    s3 = copy.deepcopy(s)
    s3["stocks"]["drink"] = 46 * PLANNER_CONFIG["drink_per_dwarf"]
    assert not by_rule(plan(s3, Memory())[0], "farms")
    # no brewable seeds: nothing more
    s4 = copy.deepcopy(s)
    s4["farms"]["crops"]["MUSHROOM_HELMET_PLUMP"]["seeds"] = 0
    assert not by_rule(plan(s4, Memory())[0], "farms")
    # nowhere to lay plots (a farm failure on record): no extra
    m = Memory()
    m.farm_failure = "no soil"
    assert thirsty_farm_extra(s, m, 46, PLANNER_CONFIG, want) == (0, False)
    # an unread stocks section isn't thirst
    s5 = copy.deepcopy(s)
    s5["_errors"] = {"stocks": "boom"}
    assert thirsty_farm_extra(s5, Memory(), 46, PLANNER_CONFIG, want) == (0, False)


@test("4b brewing (0.105.23): the larger brewable source is brewed first")
def _():
    s = fort()
    s["orders"] = []
    s["stocks"].update(drink=100, plants=55, plant_growths=300)
    s["supplies"].update(brewable_plants=4, brewable_growths=200, empty_barrels=40, empty_pots=0)
    d = by_rule(plan(copy.deepcopy(s), Memory())[0], "drink")
    assert d and d[0].action["recipe"] == "brew_drink_from_fruit", d
    s["supplies"].update(brewable_plants=150, brewable_growths=20)
    d = by_rule(plan(copy.deepcopy(s), Memory())[0], "drink")
    assert d and d[0].action["recipe"] == "brew_drink" and d[0].action["amount"] <= 150, d
    # (0.105.26) needs_drink removed: brew_recipe still picks what a still can brew
    from planner import brew_recipe
    n = fort()
    n["supplies"].update(brewable_plants=3, brewable_growths=0)
    assert brew_recipe(n) == "brew_drink"


@test("4b temples (0.105.23): the urgent temple by need carries a size the bridge takes (fort E: refused 83 times)")
def _():
    s = settled_fort(piety=0)
    s["dwarves"]["total"] = 221
    s["locations"] = {"count": {"INN_TAVERN": 4, "TEMPLE": 2, "HOSPITAL": 1, "LIBRARY": 1}, "total": 8}
    s["needs"] = {"needs": {"PrayOrMeditate": {"badly": 63, "distracted": 90}}}
    props = plan(copy.deepcopy(s), Memory())[0]
    t = [p for p in props if p.action.get("type") == "start_project" and p.action.get("kind") == "temple"]
    assert t and all(p.action.get("size") in ("shrine", "grand") for p in t), [p.action for p in t]
    assert any(p.action.get("urgent") and p.action["size"] == "shrine" for p in t), [p.action for p in t]
    s["settings"]["traits"] = {"piety": 150}
    t = [p for p in plan(copy.deepcopy(s), Memory())[0]
         if p.action.get("type") == "start_project" and p.action.get("kind") == "temple" and p.action.get("urgent")]
    assert t and t[0].action["size"] == "grand", [p.action for p in t]


@test("4b temples (0.105.23): Piety 120+ raises a temple to each god most citizens pray to, met or not")
def _():
    from planner import more_temple
    cfg = dict(PLANNER_CONFIG)
    s = fort()
    s["needs"] = {"needs": {}, "deities": {}, "worship": {"Teshkad": 14, "Tobul": 6, "Nish": 2},
                  "deity_ids": {"Teshkad": 77, "Tobul": 78, "Nish": 79}}
    s["locations"] = {"list": [{"type": "TEMPLE", "any_deity": True, "tier": 1}]}
    assert more_temple(s, {"piety": 60}, cfg) is None                 # only the distracted ask below 120
    assert more_temple(s, {"piety": 150}, cfg) == ("Teshkad", 77, 14)
    s["locations"]["list"].append({"type": "TEMPLE", "religion_deities": [77, 80]})   # a religion's temple has him
    assert more_temple(s, {"piety": 150}, cfg) == ("Tobul", 78, 6)
    s["locations"]["list"].append({"type": "TEMPLE", "deity_hf": 78})
    assert more_temple(s, {"piety": 150}, cfg) is None                 # Nish: too few pray to him
    # the ladder: a dedicated, grand temple to the god
    f = settled_fort(piety=150)
    f["needs"] = {"needs": {}, "deities": {}, "worship": {"Teshkad": 14}, "deity_ids": {"Teshkad": 77}}
    f["locations"] = {"count": {"TEMPLE": 1, "HOSPITAL": 1, "INN_TAVERN": 1, "LIBRARY": 1}, "total": 4,
                      "list": [{"type": "TEMPLE", "any_deity": True, "tier": 1}]}
    t = [p for p in plan(copy.deepcopy(f), Memory())[0] if p.action.get("kind") == "temple"]
    assert t and t[0].action.get("deity_hf") == 77 and t[0].action["size"] == "grand" and "pray to Teshkad" in t[0].reason, \
        [(p.action, p.reason) for p in t]


@test("4b temples (0.105.23): Piety 120+ has a grand temple; one is remembered once started")
def _():
    from planner import has_grand_temple
    s = settled_fort(piety=150)
    s["needs"] = {"needs": {}, "deities": {}, "worship": {}, "deity_ids": {}}
    s["locations"] = {"count": {"TEMPLE": 1, "HOSPITAL": 1, "INN_TAVERN": 1, "LIBRARY": 1}, "total": 4,
                      "list": [{"type": "TEMPLE", "any_deity": True, "tier": 1}]}
    m = Memory()
    t = [p for p in plan(copy.deepcopy(s), m)[0] if p.action.get("kind") == "temple"]
    assert t and t[0].action["size"] == "grand" and "deity_hf" not in t[0].action, [p.action for p in t]
    assert not has_grand_temple(s, m)
    record([(t[0], {"ok": True, "project_id": 41})], s, m)
    assert has_grand_temple(s, m)
    m.last_fired.clear()
    assert not [p for p in plan(copy.deepcopy(s), m)[0] if p.action.get("kind") == "temple"
                and not p.action.get("growth")]
    # a temple complex (tier 2) is one; an open grand level is one
    g = copy.deepcopy(s)
    g["locations"]["list"][0]["tier"] = 2
    assert has_grand_temple(g, Memory())
    g = copy.deepcopy(s)
    g["projects"]["open"] = [{"id": 9, "kind": "temple", "phase": "dig", "summary": {"temple": "grand"}}]
    assert has_grand_temple(g, Memory())
    # less devout: no grand temple asked for by this rule
    s["settings"]["traits"] = {"piety": 60}
    assert not [p for p in plan(copy.deepcopy(s), Memory())[0] if p.action.get("kind") == "temple"
                and p.action.get("size") == "grand"]


@test("4b the Monastery's bend (0.105.23): Piety 120+ takes the last slot for a shrine before drink is met; never in a crisis")
def _():
    from planner import piety_slot
    s = fort()
    s["projects"]["open"] = [{"id": 3, "kind": "storage", "phase": "dig", "dig": {"total": 50, "dug": 10}}]
    s["settings"]["traits"] = {"piety": 150}
    s["stocks"]["drink"] = round(3.5 * s["dwarves"]["total"])             # basics not met: 3.5 drink a dwarf
    s["locations"] = {"count": {"HOSPITAL": 1, "INN_TAVERN": 1, "LIBRARY": 1}, "total": 3}
    props, notes = plan(copy.deepcopy(s), Memory())
    starts = [p for p in props if p.action.get("type") == "start_project" and not p.action.get("urgent")]
    assert starts and all(p.action.get("kind") == "temple" and p.action.get("size") == "shrine" for p in starts), \
        [(p.rule, p.action) for p in starts]
    assert "a shrine for now" in starts[0].reason and "build a shrine" in starts[0].reason, starts[0].reason
    open_ = s["projects"]["open"]
    assert piety_slot(s, {"piety": 150}, PLANNER_CONFIG, Memory(), open_)
    assert piety_slot(s, {"piety": 100}, PLANNER_CONFIG, Memory(), open_) is None       # not devout enough
    mc = Memory()
    mc.crisis = {"why": ["thirst"]}
    assert piety_slot(s, {"piety": 150}, PLANNER_CONFIG, mc, open_) is None             # never in a crisis
    dry = copy.deepcopy(s)
    dry["stocks"]["drink"] = 2 * s["dwarves"]["total"]
    assert piety_slot(dry, {"piety": 150}, PLANNER_CONFIG, Memory(), open_) is None     # too thirsty
    beds = copy.deepcopy(s)
    beds["buildings"]["other"]["Bed"] = 3
    assert piety_slot(beds, {"piety": 150}, PLANNER_CONFIG, Memory(), open_) is None    # beds first
    assert piety_slot(s, {"piety": 150}, PLANNER_CONFIG, Memory(), []) is None          # both slots free: need first
    # B's case: full stores asked for storage; the shrine goes ahead of it
    s.setdefault("logistics", {})["storage"] = {"furniture": {"tiles": 20, "used": 20, "loose": 200}}
    s["projects"]["open"] = [{"id": 5, "kind": "workshops", "phase": "dig", "dig": {"total": 50, "dug": 10}}]
    props, notes = plan(copy.deepcopy(s), Memory())
    starts = [p for p in props if p.action.get("type") == "start_project" and not p.action.get("urgent")]
    assert [(p.action["kind"], p.action.get("size")) for p in starts] == [("temple", "shrine")], [p.action for p in starts]
    assert any("goes ahead of the storage level" in n for n in notes), notes
    # Piety 60 at the same drink: the slot isn't held, storage goes ahead
    s["settings"]["traits"] = {"piety": 60}
    props, notes = plan(copy.deepcopy(s), Memory())
    assert not any("the fort's own building slot" in p.reason for p in props), [p.reason for p in props]
    assert [p.action["kind"] for p in props if p.rule == "build"] == ["storage"], [p.action for p in props]


@test("4b temples (0.105.23): a temple without a size the bridge takes is sent as a shrine")
def _():
    import planner_building as pb
    real = pb.social_shortfall
    try:
        pb.social_shortfall = lambda s, cfg: [("temple", "test")]
        import planner_building
        orig_size = planner_building.temple_size
        planner_building.temple_size = lambda traits: "temple"           # a bad size from some rule
        s = settled_fort(piety=0)
        s["locations"] = {"count": {"INN_TAVERN": 1, "TEMPLE": 2, "HOSPITAL": 1, "LIBRARY": 1}, "total": 5}
        t = [p for p in plan(copy.deepcopy(s), Memory())[0] if p.action.get("kind") == "temple"]
        assert t and all(p.action["size"] in ("shrine", "grand") for p in t), [p.action for p in t]
    finally:
        pb.social_shortfall = real
        planner_building.temple_size = orig_size

if __name__ == "__main__":
    finish()
