"""(item16) The cavern wells' shaft guard remembers a great beast it kept a
shaft shut for. B (24 Nov 23:25-23:35): the flier Urnut in Cavern1 left
others_on_map.threats for minutes at a time (hidden over unrevealed cavern
tiles), and the five shafts were opened "no danger near the cavern well now"
4 times in 10 minutes. Remembered (memory.shaft_beasts, by unit id and the
tick last seen) until seen dead, caged, out of the caverns or unseen
SHAFT_BEAST_MEMORY_DAYS; a shaft the guard shut stays shut a day at least,
but for a dwarf dying of thirst; the pulse's own hidden great beasts
(others_on_map.hidden_great) count as unseen ones.

    python tests/test_i16_shaft_memory.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
import planner_wells  # noqa: E402
from planner import Memory  # noqa: E402
from planner_shaft_guard import (remember_shaft_beasts, SHAFT_BEAST_MEMORY_DAYS,  # noqa: E402
                                 SHAFT_GUARD_HOLD_TICKS)
from planner_core_base import TICKS_PER_DAY  # noqa: E402

LAYERS = [{"name": "Cavern1", "z_top": 150, "z_bottom": 141, "discovered": True},
          {"name": "Cavern2", "z_top": 120, "z_bottom": 106, "discovered": True}]


def gate(pid, x, z=145, **k):
    g = {"project_id": pid, "x": x, "y": 100, "z": 156, "elevation": 26, "state": "none",
         "gate": "closed", "watching": True, "watch_rule": 2, "shut_hold": 0,
         "shaft_hatch": {"x": x, "y": 100, "z": z}}
    g.update(k)
    return g


def state(*gates, threats=(), hidden=(), tick=200000, wells=3):
    return {"settings": {"traits": {}}, "dwarves": {"total": 40, "needs_medical_care": 0},
            "society": {"parched": 0}, "stocks": {"drink": 900, "mechanisms": 5},
            "buildings": {"other": {"Well": wells}, "zones": {}},
            "projects": {"open": [], "max_open": 2, "well_lids": list(gates)},
            "map": {"layers": LAYERS},
            "others_on_map": {"threats": list(threats), "hidden_great": list(hidden)},
            "date": {"year": 274, "tick": tick, "season": "winter"}}


def urnut(x=160, **k):
    t = {"id": 16692, "name": "Urnut, Forgotten Beast", "kinds": ["ForgottenBeast"], "great_danger": True,
         "flier": True, "destroyer": True, "layer": "Cavern1", "pos": {"x": x, "y": 100, "z": 144}}
    t.update(k)
    return t


def cycle(s, mem, events=None):
    """The overseer's order: the shaft_beasts step, then the plan's well rule."""
    remember_shaft_beasts(s, mem, events or [])
    s["_shaft_memory"] = mem.shaft_beasts
    props, notes = [], []
    planner_wells._well_lid_rule(s, props, notes)
    return [p for p in props if p.rule == "well_shaft"], notes


def gates3():
    return [gate(63, 100), gate(128, 200), gate(145, 300)]


@test("item16: B 23:25: Urnut out of sight on the next cycle keeps every shaft into Cavern1 shut, said")
def _():
    m = Memory()
    p, _ = cycle(state(*gates3(), threats=[urnut()]), m)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "keep_shut": [63, 128, 145]}], \
        [x.action for x in p]
    assert "16692" in m.shaft_beasts["beasts"] and m.shaft_beasts["beasts"]["16692"]["layer"] == "Cavern1"
    # the next cycles (a pulse, minutes later): no threat row at all, no watcher verdict
    for t in (200400, 201000, 202300):
        p, notes = cycle(state(*gates3(), tick=t), m)
        acts = [x.action for x in p]
        assert all(x.get("keep_shut") == [63, 128, 145] for x in acts), acts
        assert not any("no danger near" in x.reason for x in p), [x.reason for x in p]
        assert any("out of sight" in n and "Urnut" in n for n in notes), notes


@test("item16: forgotten after SHAFT_BEAST_MEMORY_DAYS unseen: the shafts open")
def _():
    m = Memory()
    cycle(state(*gates3(), threats=[urnut()]), m)
    t = 200000 + SHAFT_BEAST_MEMORY_DAYS * TICKS_PER_DAY + 10
    p, _ = cycle(state(*gates3(), tick=t), m)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False}], [x.action for x in p]
    assert "no danger near" in p[0].reason
    assert m.shaft_beasts["beasts"] == {} and m.shaft_beasts["held"] == {}, m.shaft_beasts


@test("item16: seen again it is seen again (memory refreshed); out of sight once more still remembered")
def _():
    m = Memory()
    cycle(state(*gates3(), threats=[urnut()]), m)
    t1 = 200000 + TICKS_PER_DAY
    cycle(state(*gates3(), threats=[urnut(x=900)], tick=t1), m)   # far off, still in the layer (a destroyer)
    assert m.shaft_beasts["beasts"]["16692"]["seen"] == 274 * 403200 + t1
    t2 = t1 + SHAFT_BEAST_MEMORY_DAYS * TICKS_PER_DAY - 50
    p, _ = cycle(state(*gates3(), tick=t2), m)
    assert all(x.action.get("keep_shut") == [63, 128, 145] for x in p), [x.action for x in p]


@test("item16: told dead (a death event): forgotten; the shafts still kept a day from when the guard shut them")
def _():
    m = Memory()
    cycle(state(*gates3(), threats=[urnut()]), m)
    death = {"kind": "death", "unit_id": 16692, "name": "Urnut", "great": True}
    p, _ = cycle(state(*gates3(), tick=200300), m, [death])
    assert "16692" not in m.shaft_beasts["beasts"]
    assert all(x.action.get("keep_shut") == [63, 128, 145] for x in p), [x.action for x in p]
    assert any("no flapping" in x.reason for x in p), [x.reason for x in p]
    p, _ = cycle(state(*gates3(), tick=200000 + SHAFT_GUARD_HOLD_TICKS + 1), m)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False}], [x.action for x in p]


@test("item16: seen caged or out of the caverns: forgotten")
def _():
    for row in (urnut(caged=True), urnut(layer="surface")):
        m = Memory()
        cycle(state(*gates3(), threats=[urnut()]), m)
        cycle(state(*gates3(), threats=[row], tick=200100), m)
        assert "16692" not in m.shaft_beasts["beasts"], (row, m.shaft_beasts)


@test("item16: a shaft can't flip more than once a day: a flier near then far is kept shut the day")
def _():
    m = Memory()
    near = dict(urnut(x=110), destroyer=None)                          # within 60 of shaft 63
    p, _ = cycle(state(gate(63, 100), threats=[near]), m)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "keep_shut": [63]}], [x.action for x in p]
    far = dict(urnut(x=400), destroyer=None)                          # seen, 300 off: the live rule lets it go
    p, _ = cycle(state(gate(63, 100), threats=[far], tick=200500), m)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "keep_shut": [63]}], [x.action for x in p]
    p, _ = cycle(state(gate(63, 100), threats=[far], tick=200000 + TICKS_PER_DAY + 5), m)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False}], [x.action for x in p]


@test("item16: the pulse's hidden great beast (others_on_map.hidden_great) keeps its layer's shafts shut")
def _():
    m = Memory()
    hid = {"id": 16692, "name": "Urnut", "layer": "Cavern1", "flier": True, "pos": {"x": 5, "y": 5, "z": 144}}
    p, _ = cycle(state(gate(63, 100), gate(9, 100, z=110), hidden=[hid]), m)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "keep_shut": [63]}], [x.action for x in p]
    assert "16692" in m.shaft_beasts["beasts"]
    # a hidden walker that can't reach the dwarves: as deep.unseen, no shaft kept
    m = Memory()
    p, _ = cycle(state(gate(63, 100), hidden=[dict(hid, flier=None)]), m)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False}], [x.action for x in p]


@test("item16: dying of thirst with only well water: the farthest guarded shaft still opened for a remembered beast")
def _():
    m = Memory()
    cycle(state(*gates3(), threats=[urnut()]), m)
    s = state(*gates3(), tick=200300)
    s["dwarves"]["needs_medical_care"] = 1
    s["thirst"] = {"list": [{"id": 501, "name": "Urist", "timer": 61000, "level": "dehydrated", "reason": "injured"}]}
    p, _ = cycle(s, m)
    assert len(p) == 1 and "Urist" in p[0].reason, [(x.action, x.reason) for x in p]
    assert len(p[0].action.get("keep_shut") or []) == 2, p[0].action


@test("item16: the memory round-trips; no memory (an older run, a test) acts as before")
def _():
    m = Memory()
    cycle(state(*gates3(), threats=[urnut()]), m)
    m2 = Memory.from_dict(m.to_dict())
    assert m2.shaft_beasts == m.shaft_beasts
    props, notes = [], []
    planner_wells._well_lid_rule(state(*gates3()), props, notes)
    assert [x.action for x in props if x.rule == "well_shaft"] == [{"type": "well_shaft", "close": False}]


@test("item16: wired: the cycle's step, the plan's memory, the bridge's hidden_great and its default")
def _():
    cyc = (ROOT / "brain" / "overseer_cycle.py").read_text(encoding="utf-8")
    assert '"shaft_beasts", lambda: remember_shaft_beasts(state, memory, events)' in cyc
    pl = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")
    assert 's["_shaft_memory"] = getattr(memory, "shaft_beasts", None) or {}' in pl
    lua = (ROOT / "lua" / "ai-bridge-report-world.lua").read_text(encoding="utf-8")
    assert "out.hidden_great = out.hidden_great or {}" in lua and ("dfhack.units.isHidden(u) and not" in lua or "and hidden and not dfhack.units.isCitizen(u, true)" in lua)  # (r34b) hidden read once
    from digest import SECTION_DEFAULTS as DEFAULTS
    assert DEFAULTS["others_on_map"]["hidden_great"] == []


if __name__ == "__main__":
    finish()
