"""(item6, R32 e) R31's blocks seen in the overnight journals (0.105.125):

  * D's cavern way refused 69 times "2 free mechanisms are needed for the
    link": the way's link now in planner_mechanisms' demand (ordered at the
    Mechanic's workshop with the rest), the link step not asked for until
    they are in store (a note says what waits);
  * C's way waited for a door before its breach: a door ordered when none is
    free and none is on order, the step not asked for meanwhile;
  * `prospect` refused asked again every cycle (the next metal each time):
    its own cooldown starts at a refusal; (lua, tests/test_industry.py) the
    run goes on past a 1-tile pocket, the drift's search per vein tile;
  * B's built cistern asked "shut the floodgate" every cycle while a dwarf
    was on the way to the lever: not while a pull is pending, and a pull that
    changed nothing asked again only a day on.
  (E's crossing over a shrub: tests/test_r47_descent_reserves.py, lupa.)

    python tests/test_item6_r31_blocks.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG  # noqa: E402
from planner_core import Proposal, TICKS_PER_DAY  # noqa: E402
import planner_cavern_way as CW  # noqa: E402
import planner_mechanisms as PM  # noqa: E402
import planner_wells as PW  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = dict(PLANNER_CONFIG)
LUA = ROOT / "lua"


def way_state(state: str, **kw) -> dict:
    s = {"date": {"year": 260, "tick": 50_000, "season": "spring"}, "dwarves": {"total": 40},
         "settings": {}, "buildings": {"workshops": {"Masons": 1, "Mechanics": 1}}, "others_on_map": {},
         "deep": {}, "threats": {}, "orders": [], "stocks": {},
         "cavern_way": dict({"state": state, "layer": "Cavern1", "gate": "closed"}, **kw)}
    return s


def run_way(s, props=None):
    props, notes = list(props or []), []
    CW._cavern_way_rule(s, CFG, props, notes, Memory())
    return props, notes


# --- the cavern way's link: mechanisms ---------------------------------------------------

@test("cavern way: the link short of mechanisms is not asked for; a note says what waits")
def _():
    props, notes = run_way(way_state("link", mechanisms=0))
    assert not props, props
    assert any("2 free mechanisms wanted, 0 free" in n for n in notes), notes
    props, _ = run_way(way_state("link", mechanisms=2))
    assert [p.action.get("step") for p in props] == ["build"], props
    # an older bridge (no count): asked as before
    props, _ = run_way(way_state("link"))
    assert [p.action.get("step") for p in props] == ["build"], props


def fort(free=0, **kw) -> dict:
    s = copy.deepcopy(BASE)
    s["stocks"]["mechanisms"] = free
    s["stocks"]["mechanisms_free"] = free
    s["orders"] = []
    s["threats"] = {"were": {"list": [], "were_cells": {}}}
    s.update(kw)
    return s


@test("mechanisms: the cavern way's link in the demand, ordered with the reserve")
def _():
    s = fort(0, cavern_way={"state": "link", "mechanisms": 0})
    assert ("the cavern way", 2, "its gate's lever link") in PM.mechanism_demand(s), PM.mechanism_demand(s)
    props, notes = [], []
    PM._mechanism_stock_rule(s, CFG, props, notes)
    mine = [p for p in props if p.rule == "mechanism_stock"]
    assert len(mine) == 1 and mine[0].action == {"type": "work_order", "recipe": "mechanisms", "amount": 2 + 4}, mine
    assert "the cavern way: 2" in mine[0].reason, mine[0].reason
    # before the lever is placed: its own one too; linking or ready: none
    assert PM._cavern_way_need(fort(0, cavern_way={"state": "dig"}))[0] == 3
    assert PM._cavern_way_need(fort(0, cavern_way={"state": "lever_building"}))[0] == 2
    for st in ("linking", "breach", "ready", "none"):
        assert PM._cavern_way_need(fort(0, cavern_way={"state": st}))[0] == 0, st
    # the stock's free ones the way can't use don't count as its supply
    s = fort(5, cavern_way={"state": "link", "mechanisms": 1})
    assert PM._cavern_way_need(s)[0] == 2 + 4, PM._cavern_way_need(s)


# --- the cavern way's breach: a door ----------------------------------------------------

@test("cavern way: the breach with no door free: a stone door ordered, the step not asked; on order: a note")
def _():
    props, notes = run_way(way_state("breach", doors_free=0))
    assert len(props) == 1 and props[0].action == {"type": "work_order", "recipe": "stone_door", "amount": 1}, props
    assert props[0].is_order and "door" in props[0].reason
    s = way_state("breach", doors_free=0)
    s["orders"] = [{"recipe": "stone_door", "amount_left": 1, "amount_total": 1}]
    props, notes = run_way(s)
    assert not props and any("1 door(s) on order" in n for n in notes), (props, notes)
    # a door free: the breach asked for
    props, _ = run_way(way_state("breach", doors_free=1))
    assert [p.action.get("step") for p in props] == ["build"], props
    # no mason's: the carpenter's wooden door
    s = way_state("breach", doors_free=0)
    s["buildings"] = {"workshops": {"Carpenters": 1}}
    props, _ = run_way(s)
    assert props and props[0].action["recipe"] == "wooden_door", props


@test("cavern way (lua): the report says the mechanisms and doors a waiting step wants")
def _():
    src = (LUA / "ai-cavern-way.lua").read_text(encoding="utf-8")
    assert "if st.state == 'link' then out.mechanisms = mechanisms() end" in src
    assert "out.doors_free = free_doors()" in src


# --- prospect: paced after a refusal ----------------------------------------------------

@test("prospect: a refusal starts its own cooldown (not asked again every cycle with the next metal)")
def _():
    src = (ROOT / "brain" / "planner_record.py").read_text(encoding="utf-8")
    assert 'elif p.rule in ("burial_others", "prospect"):' in src
    act = (LUA / "ai-bridge-actions-works.lua").read_text(encoding="utf-8")
    assert "mine(a.metal, n, a.dry_run == true, a.prospect == true)" in act


# --- the cistern's top-up pull ----------------------------------------------------------

def cis(**kw) -> dict:
    return dict({"stage": "done", "gate": "open", "depth": 7}, **kw)


@test("cistern: full and open with a pull pending: no step, a note")
def _():
    s = {"date": {"year": 260, "tick": 50_000}}
    notes = []
    m = Memory()
    assert PW._cistern_pull_wait(s, cis(pull_pending=True), m, notes) is True
    assert "a dwarf is on the way" in notes[0], notes
    assert PW._cistern_pull_wait(s, cis(), m, notes) is False          # the first ask goes
    assert PW._cistern_pull_wait(s, cis(), m, notes) is True           # and not again within the day
    assert "asked again in a day" in notes[-1], notes
    # the other way (open when low) is not held back by the shut asked for
    assert PW._cistern_pull_wait(s, cis(gate="shut", depth=2), m, notes) is False
    s2 = {"date": {"year": 260, "tick": 50_000 + TICKS_PER_DAY + 1}}
    assert PW._cistern_pull_wait(s2, cis(), m, notes) is False         # a day on: asked again


@test("cistern (lua): the status says a pull is pending for a built, open floodgate")
def _():
    src = (LUA / "ai-builder-cistern-status.lua").read_text(encoding="utf-8")
    assert "out.pull_pending = lever_pull_pending(d.lever_id) or nil" in src


if __name__ == "__main__":
    finish()
