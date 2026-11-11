"""(0.105.36, group people) The focused audit's D5 and X1 (mood) fixes:

* the hospital burrow's report cache keeps only sources that found drink or
  a well, and takes the tick's fresh sources (no flapping in and out);
* a dry recreation burrow is waiting, not a refusal, and is looked at again
  each day; a pre-0.105.33 save (no `ticked`) is not let out as stale;
* ai-moods' hospital chest cache is cleared when the map unloads;
* the shelter's drink_short / no_water / no_food are recorded and acted on
  (made again each day while the alarm is on, else said);
* a mood's workshop waits only for a level building its own kind.

    python tests/test_r36_people.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

from planner import Memory, PLANNER_CONFIG, abs_tick, plan, TICKS_PER_DAY  # noqa: E402
from planner_core import Proposal, note_refusal, _record_any_outcome  # noqa: E402
import planner_society  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import test_society as TS  # noqa: E402
import test_r33_society as T33  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["orders"] = []
    return s


def _vals(t):
    return sorted(t.values()) if t else []


# --- the hospital burrow -----------------------------------------------------

@test("D5 hospital: a cached 'no drink' never lets out the patients the tick moved in on drink brought back")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(TS.HOSP_FAKE, module_src("ai-society.lua"))
    r = env.hospital_burrow_tick(30, 10, False)
    assert _vals(r.added) == ["dwarf 1", "dwarf 2"], dict(r)
    lua.execute("local W = ...; W.saved = W.drink.contents; W.drink.contents = {}", w)
    w.day(0.1)
    assert env.hospital_burrow_status().members == 0
    lua.execute("local W = ...; W.drink.contents = W.saved", w)
    w.day(0.2)
    r = env.hospital_burrow_tick(30, 10, False)
    assert r.members == 2, dict(r)
    w.day(0.3)
    s = env.hospital_burrow_status()
    assert s.members == 2 and not s.released_now and not s.why, dict(s)


@test("D5 hospital: the tick's fresh sources are the report's cache (one signature, no refill back and forth)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(TS.HOSP_FAKE, module_src("ai-society.lua"))
    env.hospital_burrow_status()                 # nobody in: nothing cached
    env.hospital_burrow_tick(30, 10, False)
    n = w.ntiles()
    # a nearer drink pile appears; the next report (within the cache) keeps the tick's pile and tiles
    lua.execute("local W = ...; table.insert(W.all, W.bld(83, 'Stockpile', 3, 0, 3, 0, 10, "
                "{settings = {flags = {food = true}}, contents = {W.item(1)}}))", w)
    w.day(0.1)
    s = env.hospital_burrow_status()
    assert s.members == 2 and w.ntiles() == n, (dict(s), n, w.ntiles())
    src = (ROOT / "lua" / "ai-society-burrows.lua").read_text(encoding="utf-8")
    body = src[src.index("local function hb_src_store"):src.index("local function hospital_sources_cached")]
    assert "if not (src.drink or src.well) then HB_SRC = nil" in body


# --- the recreation burrow ---------------------------------------------------

@test("D5 recreation: a dry burrow is waiting, never a refusal; drink brought in is seen the next day")
def _():
    lua, env, units, assigned, ntiles, g = T33.soc()
    lua.execute("local env = ...; env.SAVED = env.df.global.world.items.other.DRINK; "
                "env.df.global.world.items.other.DRINK = {}", env)
    r = env.recreation_tick(8, 28, False)
    assert r.ok and r.waiting and not r.rejected and not r.error and r.members == 0, dict(r)
    m = Memory()
    p = Proposal("recreation", {"type": "recreation", "max": 8, "days": 28}, "x", 4)
    note_refusal(m, p, dict(r), 0)
    assert not m.refusals, m.refusals
    g.cur_year_tick = 1000 + 1200 // 2
    lua.execute("local env = ...; env.df.global.world.items.other.DRINK = env.SAVED", env)
    r = env.recreation_tick(8, 28, False)
    assert r.members == 0, dict(r)                # not a day yet
    g.cur_year_tick = 1000 + 1200
    r = env.recreation_tick(8, 28, False)
    assert r.ok and not r.waiting and r.members == 3, dict(r)


@test("D5 recreation: a save from before 0.105.33 (no `ticked`) is not let out as 'no tick for 9 days'")
def _():
    lua, env, units, assigned, ntiles, g = T33.soc()
    env.recreation_tick(8, 28, False)
    lua.execute("""local env = ...
        local U = env.reqscript('ai-util')
        local d = U.site_get('ai-overseer/recreation', {})
        d.ticked = nil
        U.site_put('ai-overseer/recreation', d)""", env)
    g.cur_year_tick = 1000 + 12 * 1200          # filled 12 days ago, ticks running
    s = env.recreation_status()
    assert s.members == 3 and not s.released_now, dict(s)
    g.cur_year_tick = 1000 + 13 * 1200          # the clock started at the first report
    assert env.recreation_status().members == 3
    g.cur_year_tick = 1000 + 21 * 1200          # 9 days with no tick since
    s = env.recreation_status()
    assert s.members == 0 and "no tick" in s.why, dict(s)


# --- the mood's hospital chests ------------------------------------------------

@test("D5 moods: the hospital chest cache is cleared when the map or world unloads")
def _():
    src = (ROOT / "lua" / "ai-moods.lua").read_text(encoding="utf-8")
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute("""
        local env = setmetatable({}, {__index = _G})
        env.SC_MAP_UNLOADED, env.SC_WORLD_UNLOADED = 5, 6
        env.dfhack = {onStateChange = {}}
        env.reqscript = function() return setmetatable({}, {__index = function() return function() end end}) end
        local fn = assert(load(..., 'ai-moods', 't', env))
        pcall(fn)
        return env""", src)
    h = env.dfhack.onStateChange["ai-moods-hospital"]
    assert h is not None
    env.HOSPITAL_CACHE = lua.table_from({"at": 1})
    h(3)
    assert env.HOSPITAL_CACHE is not None
    h(5)
    assert env.HOSPITAL_CACHE is None


# --- the shelter's drink and food ---------------------------------------------

def _shelter_memory(s, short: dict, ago_days: float) -> Memory:
    m = Memory()
    now = abs_tick(s)
    _record_any_outcome({"type": "civ_alert", "on": True},
                        {"ok": True, "on": True, "shelter": {"refreshed": True, "tiles": 400, **short}},
                        s, m, now - int(ago_days * TICKS_PER_DAY))
    return m


@test("D5 shelter: drink_short / no_food from a fill are recorded (the alarm's, set-up's or refresh's)")
def _():
    s = fort()
    m = _shelter_memory(s, {"drink_short": "the shelter holds 1 drink for 20 citizens and no well",
                            "no_food": "the shelter holds no food", "drink_units": 1, "food_units": 0}, 0)
    assert m.shelter_supply["drink_short"].startswith("the shelter holds 1") and m.shelter_supply["no_food"]
    _record_any_outcome({"type": "refresh_shelter"}, {"ok": True, "tiles": 400, "drink_units": 90,
                                                      "food_units": 50}, s, m, abs_tick(s))
    assert not m.shelter_supply.get("drink_short") and not m.shelter_supply.get("no_food"), m.shelter_supply
    _record_any_outcome({"type": "setup_shelter"}, {"ok": False, "error": "x"}, s, m, abs_tick(s))
    assert m.shelter_supply.get("drink_units") == 90          # a refusal records nothing
    assert Memory.from_dict(m.to_dict()).shelter_supply == m.shelter_supply


@test("D5 shelter: short of drink or food with the alarm on: made again (refresh_shelter) once a day; off: said")
def _():
    short = {"drink_short": "the shelter holds 2 drink for 30 citizens and no well", "no_food": "the shelter holds no food"}
    s = fort()
    s["civ_alert"] = True
    props, notes = [], []
    planner_society._shelter_supply_rule(s, _shelter_memory(s, short, 1.5), props, notes)
    assert [p.action for p in props] == [{"type": "refresh_shelter"}] and props[0].rule == "shelter_supply", props
    assert "2 drink for 30" in props[0].reason and "no food" in props[0].reason
    props, notes = [], []
    planner_society._shelter_supply_rule(s, _shelter_memory(s, short, 0.2), props, notes)
    assert not props and any("each day" in n for n in notes), notes
    s["civ_alert"] = False
    props, notes = [], []
    planner_society._shelter_supply_rule(s, _shelter_memory(s, short, 3), props, notes)
    assert not props and any("next sounds the alarm" in n for n in notes), notes
    props, notes = [], []
    planner_society._shelter_supply_rule(s, _shelter_memory(s, {}, 3), props, notes)
    assert not props and not notes
    # the whole planner: the rule runs (from _needs_notes) and its proposal is made
    s = fort()
    s["civ_alert"] = True
    p, _ = plan(s, _shelter_memory(s, short, 2))
    assert any(x.rule == "shelter_supply" for x in p), [x.rule for x in p]


# --- a mood's workshop ------------------------------------------------------------

def _mood_fort(open_):
    s = fort()
    s["buildings"]["workshops"].pop("Carpenters", None)
    s["moods"] = {"list": [{"unit_id": 9, "name": "Kib", "mood": "Fey", "craft": True, "skill": "CARPENTRY",
                            "job": "StrangeMoodCarpenter", "workshop": None, "missing": []}]}
    s["projects"]["open"] = open_
    return s


@test("X1 mood: another rule's workshops level (Jewelers) does not hold the mood's Carpenters; priority 0")
def _():
    s = _mood_fort([{"id": 501, "kind": "workshops", "phase": "furnish", "furnish": {"days": 20},
                     "summary": {"workshops": ["Jewelers"]}}])
    props, notes = plan(s, Memory())
    m = [p for p in props if p.rule == "mood" and p.action.get("type") == "start_project"]
    assert m and m[0].action["shops"] == ["Carpenters"] and m[0].action["urgent"] and m[0].priority == 0, \
        ([(p.rule, p.action) for p in props], [n for n in notes if "mood" in n])


@test("X1 mood: a level already building its Carpenters: a note, no second level")
def _():
    s = _mood_fort([{"id": 501, "kind": "workshops", "phase": "dig", "summary": {"workshops": ["Carpenters"]}}])
    props, notes = plan(s, Memory())
    assert not [p for p in props if p.rule == "mood" and p.action.get("type") == "start_project"]
    assert any("Kib" in n and "with a Carpenters is already being built" in n for n in notes), notes
    # one stuck furnishing past STALE_PROJECT_DAYS doesn't count
    s = _mood_fort([{"id": 501, "kind": "workshops", "phase": "furnish", "furnish": {"days": 40},
                     "summary": {"workshops": ["Carpenters"]}}])
    props, notes = plan(s, Memory())
    assert [p for p in props if p.rule == "mood" and p.action.get("type") == "start_project"]


if __name__ == "__main__":
    finish()
