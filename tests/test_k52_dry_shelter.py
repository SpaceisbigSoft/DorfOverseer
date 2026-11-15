"""(0.105.52) B's 20 thirst deaths (R3, 15 Nov): a Hill Titan's siege, the
civilians held in a picked shelter level with no drink and no well; the redraw
kept redrawing the same dry level, and the shelter plan, restarted at every
move, was 'still being walked' for two hours.

    python tests/test_k52_dry_shelter.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except Exception:  # noqa: BLE001
    LuaRuntime = None

import test_society as TS  # noqa: E402


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, got, df = lua.execute(TS.SHELTER_FAKE, TS.module_src("ai-society.lua"))
    lua.execute(r"""local env = ...
        CALLS = {}
        local rq = env.reqscript
        env.reqscript = function(n)
          if n == 'ai-shelter-plan' then return {pick_levels = function() return {[15] = true} end} end
          if rq then return rq(n) end
          error('reqscript ' .. n)
        end
        env.fill_shelter = function(b, only)
          table.insert(CALLS, only and 'picked' or 'whole')
          if only then return 10, {drink_units = 0, well_tiles = 0, drink_tiles = 0} end
          return 500, {drink_units = WHOLE_DRINK, well_tiles = 0, drink_tiles = WHOLE_DRINK}
        end""", env)
    return lua, env


@test("refresh_shelter: a picked level with no drink and no well is redrawn over the whole fort")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    lua, env = world()
    lua.execute("WHOLE_DRINK = 40")
    r = env.refresh_shelter()
    calls = list(lua.eval("CALLS").values())
    assert calls == ["picked", "whole"], calls
    assert r.widened_for_drink and r.tiles == 500 and not r.dry, dict(r)


@test("refresh_shelter: no drink in the whole fort either: reported dry (the alarm comes down for the thirsty)")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    lua, env = world()
    lua.execute("WHOLE_DRINK = 0")
    r = env.refresh_shelter()
    calls = list(lua.eval("CALLS").values())
    assert calls == ["picked", "whole", "picked"] and r.dry and not r.widened_for_drink and r.tiles == 10, (calls, dict(r))


@test("shelter plan: the walk's key is the ways in and a range that only widens (not the pick, not the citizens' moves)")
def _():
    src = (ROOT / "lua" / "ai-shelter-plan.lua").read_text(encoding="utf-8")
    i = src.index("run_slices('shelter_walk'")
    assert "key = table.concat(sig, ',') .. '|' .. lo .. '-' .. hi" in src[i:i + 300]
    assert "RANGE = {lo, hi}" in src and "RANGE = nil" in src


sys.path.insert(0, str(ROOT / "brain"))
import planner_thirst as PT  # noqa: E402
from planner import Memory, PLANNER_CONFIG, Proposal, select  # noqa: E402
from planner import record
from planner_core import abs_tick, TICKS_PER_DAY  # noqa: E402


def _st(timer):
    return {"date": {"year": 300, "tick": 1200}, "civ_alert": True, "civ_alert_shelter": "ai",
            "thirst": {"list": [dict(id=7, name="Dwarf 7", reason="alert", timer=timer, x=1, y=2, z=3)], "deaths": []}}


@test("thirst: the shelter dry even over the whole fort and a dwarf dehydrated: the AI's alarm comes down")
def _():
    mem = Memory()
    mem.shelter_supply = {"tick": 1, "tiles": 500, "dry": True}
    props, notes = [], []
    PT._thirst_rule(_st(60000), PLANNER_CONFIG, props, notes, mem)
    acts = [p.action for p in props if p.rule == "thirst"]
    assert {"type": "civ_alert", "on": False, "why": "thirst"} in acts, acts
    mem = Memory()
    mem.shelter_supply = {"tick": 1, "tiles": 500, "dry": True}
    props, notes = [], []                       # merely thirsty: the redraw, as before
    PT._thirst_rule(_st(30000), PLANNER_CONFIG, props, notes, mem)
    assert [p.action["type"] for p in props if p.rule == "thirst"] == ["refresh_shelter"], [p.action for p in props]
    mem = Memory()
    mem.shelter_supply = {"tick": 1, "tiles": 500}          # not dry: the redraw
    props, notes = [], []
    PT._thirst_rule(_st(60000), PLANNER_CONFIG, props, notes, mem)
    assert [p.action["type"] for p in props if p.rule == "thirst"] == ["refresh_shelter"]


@test("thirst: once let down for the thirsty, the alarm isn't raised again for half a day")
def _():
    st = _st(60000)
    mem = Memory()
    off = Proposal("thirst", {"type": "civ_alert", "on": False, "why": "thirst"}, "x", 0)
    record([(off, {"ok": True})], st, mem)
    assert mem.thirst_alarm_off_until == abs_tick(st) + TICKS_PER_DAY // 2
    on = Proposal("threat_alert", {"type": "civ_alert", "on": True}, "a titan", 0)
    allowed, held = select([on], st, mem)
    assert not allowed and any("let down for the thirsty" in h for h in held), held
    st2 = dict(st, date={"year": 300, "tick": 1200 + TICKS_PER_DAY})
    allowed, held = select([on], st2, mem)
    assert allowed, held


@test("cover_cut_off: a citizen who can't walk to the shelter gets a patch of it where they stand; one who can, none")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, got, df = lua.execute(TS.SHELTER_FAKE, TS.module_src("ai-society.lua"))
    lua.execute(r"""local env = ...
        SET = {}
        env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
        -- the shelter: one block at z 152, its tile (0,0) only; walk group 1 there
        local blk = {map_pos = {x = 0, y = 0, z = 152}}
        env.dfhack.burrows.listBlocks = function(b) return {blk} end
        env.dfhack.burrows.isAssignedBlockTile = function(b, k, x, y) return x == 0 and y == 0 end
        env.dfhack.burrows.setAssignedTile = function(b, p, on) SET[p.x .. ',' .. p.y .. ',' .. p.z] = on end
        env.dfhack.maps = {isValidTilePos = function(p) return p.x >= 0 and p.y >= 0 end,
          getWalkableGroup = function(p) if p.z == 152 then return 1 end if p.z == 167 then return 2 end return 0 end}
        env.dfhack.units.getCitizens = function() return {{pos = {x = 3, y = 3, z = 152}}, {pos = {x = 50, y = 50, z = 167}},
                                                          {pos = {x = 52, y = 50, z = 167}}} end
    """, env)
    tiles, people = env.cover_cut_off({})
    assert people == 1 and tiles == 17 * 17, (tiles, people)        # one patch for the cut-off group (two dwarves)
    st = lua.eval("SET")
    assert st["50,50,167"] and st["42,42,167"] and not st["3,3,152"]


@test("planner: with the AI's alarm up, the shelter drawn again each quarter day (cut-off citizens covered)")
def _():
    import planner_society as PS
    mem = Memory()
    mem.shelter_supply = {"tick": abs_tick(_st(0)) - TICKS_PER_DAY // 4, "tiles": 500}
    props, notes = [], []
    PS._shelter_supply_rule(_st(0), mem, props, notes)
    assert [p.action for p in props] == [{"type": "refresh_shelter"}], [p.action for p in props]
    mem.shelter_supply = {"tick": abs_tick(_st(0)) - 10, "tiles": 500}
    props, notes = [], []
    PS._shelter_supply_rule(_st(0), mem, props, notes)
    assert not props


finish()
