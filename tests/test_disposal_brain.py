"""(0.105.27, group brain) Forbidden items disposed of: planner_industry's
_disposal_rules against fake reports (the census' items.forbidden, the
disposal section, dead.standing), each Rules level, a siege, the War-hold's
keep_enemy_gear, the Hermit hold's inside dump, the destroy threshold and the
note on the player's own forbidden items.

    python tests/test_disposal_brain.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))

from harness import test, finish  # noqa: E402

from test_planner import fort  # noqa: E402
from planner import Memory, plan, record, select, PLANNER_CONFIG, TICKS_PER_DAY, abs_tick  # noqa: E402
from planner_core import player_rules, STEER_PROTECTED  # noqa: E402
from planner_industry import _disposal_rules  # noqa: E402

DISPOSAL = ("disposal_unforbid", "disposal_melt", "disposal_dump", "disposal_place_dump",
            "disposal_empty", "disposal_orders")


def state(level="destroy", **settings):
    """A fort with a fresh census full of forbidden items, a dump zone with
    200 items in it, a smelter, and the refuse order off."""
    s = fort()
    s.setdefault("settings", {})["disposal"] = level
    s["settings"].update(settings)
    s.setdefault("dead", {}).update(unburied=0, standing={"gather_refuse": 0, "forbid_used_ammo": 1,
                                                          "forbid_own_dead_items": 1})
    s["disposal"] = {"dump_zones": [{"id": 7, "x": 10, "y": 10, "z": 100, "inside": False, "items": 200}],
                     "dumped_items": 200, "marked_dump": 0, "marked_melt": 0, "smelters": 1,
                     "magma_smelters": 0, "sealed_caverns": False, "siege": False}
    s["others_on_map"] = {"threats": []}
    m = Memory()
    m.census = {"tick": abs_tick(s) - TICKS_PER_DAY, "units": {}, "items": {"forbidden": {
        "total": 900, "by_type": {"AMMO": 300, "WEAPON": 40, "ARMOR": 60, "CORPSE": 50},
        "by_reason": {"own_dead": 20, "used_ammo": 300, "other_dead": 250, "dumped": 200, "ai": 10, "unknown": 120},
        "by_where": {"surface": 600, "inside": 300, "caverns": 0, "near_danger": 0, "unreachable": 0},
        "metal": 80, "worn": 90, "valuable": 2, "corpses": {"own": 0, "other": 50}}}}
    return s, m


def run(s, m):
    props, notes = [], []
    _disposal_rules(s, dict(PLANNER_CONFIG), props, notes, m, player_rules(s))
    return {p.rule: p for p in props}, notes


@test("player_rules: the disposal keys with their defaults (destroy, player items off, enemy gear melted)")
def _():
    s = fort()
    s["settings"] = {k: v for k, v in s.get("settings", {}).items()
                     if k not in ("disposal", "disposal_player_items", "keep_enemy_gear")}
    r = player_rules(s)
    assert r["disposal"] == "destroy" and r["disposal_player_items"] is False and r["keep_enemy_gear"] is False, r
    s["settings"].update(disposal="nonsense")
    assert player_rules(s)["disposal"] == "destroy"
    s["settings"].update(disposal="melt", disposal_player_items=True, keep_enemy_gear=True)
    r = player_rules(s)
    assert (r["disposal"], r["disposal_player_items"], r["keep_enemy_gear"]) == ("melt", True, True), r


@test("destroy (default): every action, sized by config, the refuse order on, the dead-items orders left alone")
def _():
    s, m = state()
    got, notes = run(s, m)
    assert set(DISPOSAL) - {"disposal_place_dump"} <= set(got), list(got)
    u = got["disposal_unforbid"].action
    assert u == {"type": "unforbid_items", "reasons": ["used_ammo", "own_dead", "other_dead"],
                 "max": PLANNER_CONFIG["disposal_unforbid_max"]}, u
    assert "570 items worth keeping" in got["disposal_unforbid"].reason, got["disposal_unforbid"].reason
    assert "300 used bolts and arrows" in got["disposal_unforbid"].reason
    mm = got["disposal_melt"].action
    assert mm == {"type": "mark_melt", "max": 40, "keep_masterwork": True, "keep_enemy_gear": False}, mm
    d = got["disposal_dump"].action
    assert d == {"type": "mark_dump", "reasons": ["free", "other_dead", "own_dead"], "max": 200}, d
    e = got["disposal_empty"]
    assert e.action == {"type": "empty_dump", "max": 200} and "200 items lie in the garbage dump" in e.reason, e
    o = got["disposal_orders"].action
    assert o == {"type": "set_standing_orders", "orders": {"gather_refuse": 1}}, o
    assert "census" not in got, "a census a day old: not counted again"
    # the full global names in dead.standing: the same names sent back
    s["dead"]["standing"] = {"standing_orders_gather_refuse": 0}
    assert run(s, m)[0]["disposal_orders"].action["orders"] == {"standing_orders_gather_refuse": 1}
    s["dead"]["standing"] = {"standing_orders_gather_refuse": 1}
    assert "disposal_orders" not in run(s, m)[0]
    # no unknown items unforbidden, no Needs you at 120
    assert "unknown" not in u["reasons"] and not any(n.startswith("[you] ") for n in notes), notes


@test("Rules levels: store only unforbids; melt adds melting; dump adds dumping; destroy adds empty_dump")
def _():
    want = {"store": {"disposal_unforbid"},
            "melt": {"disposal_unforbid", "disposal_melt"},
            "dump": {"disposal_unforbid", "disposal_melt", "disposal_dump"},
            "destroy": {"disposal_unforbid", "disposal_melt", "disposal_dump", "disposal_empty"}}
    for level, rules in want.items():
        s, m = state(level)
        got = set(run(s, m)[0]) - {"disposal_orders"}
        assert got == rules, (level, got)
    # no dump zone at store or melt: none placed either
    for level in ("store", "melt"):
        s, m = state(level)
        s["disposal"]["dump_zones"] = []
        assert "disposal_place_dump" not in run(s, m)[0], level


@test("siege: nothing proposed (the disposal report's flag, or invaders in the threats report), said in a note")
def _():
    s, m = state()
    s["disposal"]["siege"] = True
    got, notes = run(s, m)
    assert not set(DISPOSAL) & set(got), list(got)
    assert any("a siege is on" in n and "900 forbidden items" in n for n in notes), notes
    s, m = state()
    s["others_on_map"] = {"threats": [{"id": 1, "invader": True, "can_reach_dwarves": False}]}
    assert not set(DISPOSAL) & set(run(s, m)[0])


@test("War-hold: keep_enemy_gear goes to mark_melt and keeps the enemy's junk off the dump")
def _():
    s, m = state(keep_enemy_gear=True)
    got, _ = run(s, m)
    mm = got["disposal_melt"]
    assert mm.action["keep_enemy_gear"] is True and "the enemy's gear is kept" in mm.reason, mm
    assert "other_dead" not in got["disposal_dump"].action["reasons"], got["disposal_dump"].action
    assert "other_dead" in got["disposal_unforbid"].action["reasons"], "still stored, just not melted"


@test("Hermit hold: the dump goes inside (Outsiders -150, Surface -60); any fort at Outsiders or Surface <= -50")
def _():
    s, m = state()
    s["disposal"]["dump_zones"] = []
    s["disposal"]["dumped_items"] = 0
    s["settings"]["traits"] = dict(s["settings"].get("traits") or {}, outsiders=-150, surface=-60)
    got, _ = run(s, m)
    p = got["disposal_place_dump"]
    assert p.action == {"type": "place_dump", "inside": True} and "inside the fort" in p.reason, p
    assert "disposal_dump" not in got and "disposal_empty" not in got, list(got)
    s["settings"]["traits"].update(outsiders=0, surface=-50)
    assert run(s, m)[0]["disposal_place_dump"].action["inside"] is True
    s["settings"]["traits"].update(outsiders=0, surface=0)
    assert run(s, m)[0]["disposal_place_dump"].action["inside"] is False
    # little junk and nothing marked: no dump asked for
    m.census["items"]["forbidden"].update(worn=0, by_reason={"other_dead": 5})
    assert "disposal_place_dump" not in run(s, m)[0]


@test("the slow-game rule leaves the dump to the disposal rules when the bridge has them")
def _():
    s, m = state()
    s["fps_low"] = 14
    s["logistics"] = {"counts": {"items": 45000, "units": 300, "jobs": 200}}
    s["buildings"]["zones"].pop("Dump", None)
    s["disposal"]["dump_zones"] = []
    rules = {p.rule for p in plan(copy.deepcopy(s), m)[0]}
    assert "dump" not in rules and "disposal_place_dump" in rules, rules
    s.pop("disposal")
    assert "dump" in {p.rule for p in plan(copy.deepcopy(s), m)[0]}


@test("destroy threshold: empty_dump only past disposal_destroy_min items in the dump")
def _():
    s, m = state()
    s["disposal"]["dumped_items"] = PLANNER_CONFIG["disposal_destroy_min"] - 1
    assert "disposal_empty" not in run(s, m)[0]
    s["disposal"]["dumped_items"] = PLANNER_CONFIG["disposal_destroy_min"]
    e = run(s, m)[0]["disposal_empty"]
    assert e.action == {"type": "empty_dump", "max": 150}, e.action
    s["disposal"]["dumped_items"] = 5000
    assert run(s, m)[0]["disposal_empty"].action["max"] == PLANNER_CONFIG["disposal_empty_max"]


@test("unknown items: Needs you past 200, saying they may be the player's and naming the switch; on: the AI takes them")
def _():
    s, m = state()
    m.census["items"]["forbidden"]["by_reason"]["unknown"] = 450
    got, notes = run(s, m)
    you = [n for n in notes if n.startswith("[you] ")]
    assert you and "450 items" in you[0] and "may be yours" in you[0] and "disposal_player_items" in you[0], notes
    assert "unknown" not in got["disposal_unforbid"].action["reasons"]
    s["settings"]["disposal_player_items"] = True
    got, notes = run(s, m)
    assert not [n for n in notes if n.startswith("[you] ")], notes
    u = got["disposal_unforbid"].action
    assert "unknown" in u["reasons"] and u["player_items"] is True, u


@test("pace: a batch waits for a census taken after it, then a recount is asked; cooldowns from config")
def _():
    s, m = state()
    got, _ = run(s, m)
    u = got["disposal_unforbid"]
    record([(u, {"ok": True, "unforbidden": 300})], s, m)
    later = copy.deepcopy(s)
    later["date"]["tick"] += 2 * TICKS_PER_DAY
    got2, _ = run(later, m)
    assert "disposal_unforbid" not in got2 and "census" not in got2, list(got2)
    later["date"]["tick"] += 4 * TICKS_PER_DAY
    got3, _ = run(later, m)
    assert "disposal_unforbid" not in got3 and "census" in got3, list(got3)
    # the census comes back: the next batch, past its cooldown
    m.census["tick"] = abs_tick(later)
    assert "disposal_unforbid" in run(later, m)[0]
    # select(): the cooldown key by the rule's name
    m.census["tick"] = abs_tick(s)
    m.last_fired["disposal_unforbid"] = abs_tick(s) - 1
    _, held = select([got["disposal_unforbid"]], s, m)
    assert any("disposal_unforbid: waiting for its cooldown" in h for h in held), held
    assert not set(DISPOSAL) & STEER_PROTECTED


@test("no census (or a month old) and a disposal report: a census asked, nothing else counted on")
def _():
    s, m = state()
    m.census = {}
    got, _ = run(s, m)
    assert "census" in got and not {"disposal_unforbid", "disposal_melt", "disposal_dump"} & set(got), list(got)
    assert "disposal_empty" in got, "the dump's count comes from the disposal report, live"


@test("an older bridge (no disposal section, or it failed): nothing proposed")
def _():
    s, m = state()
    s.pop("disposal")
    assert run(s, m) == ({}, [])
    s["disposal"] = {"error": "boom"}
    assert run(s, m) == ({}, [])


@test("burial interplay: the dead's belongings wait while a body waits for its tomb")
def _():
    s, m = state()
    s["dead"]["unburied"] = 3
    got, _ = run(s, m)
    assert "own_dead" not in got["disposal_unforbid"].action["reasons"], got["disposal_unforbid"].action
    assert "own_dead" not in got["disposal_dump"].action["reasons"]


@test("clutter interplay: worn clothes rotting this cycle (prune with clothes) aren't marked for the dump")
def _():
    s, m = state()
    from planner_core import Proposal
    props = [Proposal("prune", {"type": "prune_remains", "extra": ["clothes"]}, "rot", 7)]
    notes = []
    _disposal_rules(s, dict(PLANNER_CONFIG), props, notes, m, player_rules(s))
    assert "disposal_dump" not in {p.rule for p in props}
    assert any("rot away this cycle" in n for n in notes), notes


@test("melt: no smelter or a backlog marked: a note, no marks")
def _():
    s, m = state()
    s["disposal"]["smelters"] = 0
    got, notes = run(s, m)
    assert "disposal_melt" not in got and any("no smelter" in n for n in notes), notes
    s["disposal"].update(magma_smelters=1, marked_melt=PLANNER_CONFIG["disposal_melt_backlog"])
    got, notes = run(s, m)
    assert "disposal_melt" not in got and any("wait for the smelters" in n for n in notes), notes


@test("refuse order: switched on once; off again after that: left as the player set it, said")
def _():
    s, m = state()
    o = run(s, m)[0]["disposal_orders"]
    record([(o, {"ok": True})], s, m)
    later = copy.deepcopy(s)
    later["date"]["tick"] += 30 * TICKS_PER_DAY
    m.census["tick"] = abs_tick(later)
    got, notes = run(later, m)
    assert "disposal_orders" not in got and any("left as you set it" in n for n in notes), notes


@test("whole plan: the disposal rules run at full speed, through plan()")
def _():
    s, m = state()
    props, _ = plan(copy.deepcopy(s), m)
    assert {"disposal_unforbid", "disposal_empty"} <= {p.rule for p in props}, [p.rule for p in props]


@test("overseer: the disposal actions have short labels")
def _():
    import overseer
    for t in ("unforbid_items", "mark_melt", "mark_dump", "place_dump", "empty_dump", "set_standing_orders"):
        assert overseer.short({"type": t}) == overseer.SHORT_WORDS[t], t


if __name__ == "__main__":
    finish()
