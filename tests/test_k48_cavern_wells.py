"""(K48-K4b, round 2) The cavern-well leftovers of audit A4, the brain's half
(the bridge's half is in test_r47_wellsafe.py, "K48-K4b bridge"):

  * 14: a given-up shaft alone is shut with close false (close true shut
    every working well too, each for a day);
  * 11: a danger at one well's shaft no longer holds another's gate back
    (the break, the hatch, the link); one at its own still does;
  * 12: no seal_well_stairs asked for an open lid over a shaft still dug;
  * 15: a water zone's points: cavern water after any other;
  * 20: a cavern well still being dug is not counted against the Well buildings;
  * 18: act_place_well passes the brain's cooldown_days and site_tries on.

    python tests/test_k48_cavern_wells.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import bridge_part_src  # noqa: E402  (r6) the bridge parts split
import planner_wells  # noqa: E402


def gate(**k):
    g = {"project_id": 9, "x": 120, "y": 121, "z": 156, "elevation": 26, "state": "none",
         "gate": "closed", "watching": True, "watch_rule": 2, "shut_hold": 0}
    g.update(k)
    return g


def state(*gates, wells=2, drink=900, patients=0, parched=0, zones=None, mech=5):
    return {"settings": {"traits": {}}, "dwarves": {"total": 40, "needs_medical_care": patients},
            "society": {"parched": parched}, "stocks": {"drink": drink, "mechanisms": mech},
            "buildings": {"other": {"Well": wells}, "zones": zones or {}},
            "projects": {"open": [], "max_open": 2, "well_lids": list(gates)},
            "entrances": {"parts": {"hatch_covers": 1}},
            "others_on_map": {}, "date": {"year": 5, "tick": 1000, "season": "spring"}}


def run(s, kind="well_shaft"):
    props, notes = [], []
    planner_wells._well_lid_rule(s, props, notes)
    return [p for p in props if p.action.get("type") == kind], notes


NEAR = {"id": 3, "name": "Abyssal Squid", "d": 12, "reach": 25, "mobile": True, "climber": True}


@test("14: a given-up shaft standing open is shut with close false; a danger's shut stays close true")
def _():
    p, _ = run(state(gate(gate="open"), gate(project_id=4, gate="open", cancelled=True)))
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False}], [x.action for x in p]
    assert "given-up" in p[0].reason
    p, _ = run(state(gate(gate="open", watch_near=NEAR), gate(project_id=4, gate="open", cancelled=True)))
    assert p and p[0].action["close"] is True and "Abyssal Squid" in p[0].reason


@test("11: a held well's break is asked for while a danger is at another well's shaft, not at its own")
def _():
    other = gate(project_id=4, gate="closed", watch_near=NEAR)
    held = gate(project_id=10, gate="no_hatch", held=True, hatch_covers=1, gate_mechanisms=6, watch_rule=None)
    p, notes = run(state(other, held, mech=6))
    assert p and p[0].action == {"type": "well_shaft", "close": False}, [x.action for x in p]
    assert "dig the shaft's last level" in p[0].reason, p[0].reason
    # its own danger (a linked gate being re-hatched, say): not asked
    own = gate(project_id=10, gate="no_hatch", gate_mechanisms=6, watch_near=NEAR)
    p, _ = run(state(other, own, mech=6))
    assert not p, [x.reason for x in p]


@test("12: an open stair lid over a shaft still being dug (gate impossible) is not asked to be locked")
def _():
    lid = gate(gate="none_possible", state="open", digging=True, watch_rule=None)
    p, _ = run(state(lid), "seal_well_stairs")
    assert not p
    lid["digging"] = None
    p, _ = run(state(lid), "seal_well_stairs")
    assert p
    # nothing on the step yet: the hatch is still planned (left unlocked by the bridge while dug)
    p, _ = run(state(gate(gate="none_possible", state="none", digging=True, watch_rule=None)), "seal_well_stairs")
    assert p


@test("15: the water zone's points put cavern water after any other, however near it is")
def _():
    s = state(wells=0, patients=4)
    s["buildings"]["zones"] = {}
    s["water"] = {"bodies": [
        {"kind": "cavern", "nearest": {"x": 133, "y": 130, "z": 136, "d": 20}},
        {"kind": "pond", "stagnant_share": 80, "nearest": {"x": 68, "y": 121, "z": 170, "d": 60}},
        {"kind": "river", "nearest": {"x": 50, "y": 50, "z": 170, "d": 90}},
    ]}
    props, notes = [], []
    planner_wells._water_zone_rule(s, props, notes)
    pts = [p for p in props if p.action.get("type") == "water_zone"][0].action["points"]
    assert [(x["x"], x["y"]) for x in pts] == [(50, 50), (68, 121), (133, 130)], pts


@test("20: one ordinary well and a cavern well still being dug: not short of water")
def _():
    digging = gate(gate="no_hatch", held=True, digging=True)
    s = state(digging, wells=1, patients=3)
    assert planner_wells.shaft_water_short(s, [digging]) == ""
    built = gate(gate="closed")
    s = state(built, wells=1, patients=3)
    assert planner_wells.shaft_water_short(s, [built]) == "3 injured need water"



@test("18: act_place_well passes cooldown_days and site_tries to place_well (they were dropped)")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    src = bridge_part_src("ai-bridge-actions")
    i = src.index("function act_place_well(a)")
    part = src[i:src.index("\nend\n", i) + 5]
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(r"""
local src = ...
local env = setmetatable({}, {__index = _G})
env.whole_number = function(v) return math.tointeger(tonumber(v)) end
env.far_reach_of = function() end
env.map_width = function() return 192 end
env.get_date = function() return {year = 1, tick = 0} end
env.reqscript = function() return {place_well = function(params) GOT = params; return {ok = true} end} end
assert(load(src, 'act', 't', env))()
return env""", part)
    env.act_place_well(lua.table_from({"cavern": True, "cooldown_days": 30, "site_tries": 3}))
    got = lua.eval("GOT")
    assert got.cooldown_days == 30 and got.site_tries == 3, (got.cooldown_days, got.site_tries)
    env.act_place_well(lua.table_from({"cavern": True}))
    got = lua.eval("GOT")
    assert got.cooldown_days is None and got.site_tries is None


finish()
