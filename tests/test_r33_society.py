"""(0.105.33, group society) The L6/B4 audit's society fixes:

* labour: narrow() on an "everybody" detail picks from those already holding
  the labour (it emptied the detail); trim() fills from those breaking down
  when too few are calm;
* the shelter: a well (on its channelled EMPTY tile) is in it, a mug is not
  drink for forty, food is taken back too;
* the recreation burrow: members checked at every report (thirst, hunger,
  tantrum, care, too long), everyone out when no tick came or there is no
  drink nor well; the brain's release; the burrow's water;
* the calm burrow's drink must lie on its own tiles; the hospital sources
  cached at the report; visiting animals never pastured; a location's
  bedroom never a home; the infected's rest never for the thirsty.

    python tests/test_r33_society.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
import harness  # noqa: E402
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)


def _fake(file: str, name: str) -> str:
    """A fake's Lua source from another test file, read without running it."""
    tree = ast.parse((ROOT / "tests" / file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return node.value.value
    raise KeyError(name)


import test_labor as TL  # noqa: E402   (its own tests ran on import: their results dropped)
harness.RESULTS.clear()

import test_planner as tp  # noqa: E402
import test_homes as TH  # noqa: E402
harness.RESULTS.clear()
from planner import Memory, PLANNER_CONFIG as cfg  # noqa: E402
from planner_society import _recreation_rule, _needs_notes  # noqa: E402

SOC = _fake("test_society.py", "FAKE")
CALM = _fake("test_society.py", "CALM_FAKE")
HOSP = _fake("test_society.py", "HOSP_FAKE")
SHELTER = _fake("test_fix26_combat.py", "FAKE")


def _names(t):
    return [t[i] for i in range(1, len(t) + 1)] if t else []


# --- labour -------------------------------------------------------------------

def _everybody_plants():
    g = TL.game(TL.SEVEN, [], TL.DETAILS)
    g["lua"].execute("""local env = ...
      local store = {}
      env.dfhack.persistent = {getSiteData = function(k, d) return store[k] or d end,
                               saveSiteData = function(k, v) store[k] = v end}
      for _, u in ipairs(env.dfhack.units.getCitizens(true)) do env.dfhack.units.setAutomaticProfessions(u) end""",
                     g["env"])
    return g


@test("L6 narrow: an everybody detail whose dwarves all hold the labour keeps the `keep` best, not nobody")
def _():
    g = _everybody_plants()
    env, by_id, lab = g["env"], g["by_id"], g["lab"]
    assert all(by_id[i].status.labors[lab.PLANT] for i in by_id)
    r = env.narrow("farming", 2, False)
    assert r.ok and r.keep == 2 and len(TL.members(g, 4)) == 2 and 4 in TL.members(g, 4), (dict(r), TL.members(g, 4))
    assert g["details"][4].flags.mode == 3
    assert any(by_id[i].status.labors[lab.PLANT] for i in by_id)          # somebody still plants


@test("L6 narrow: fewer civilians than `keep` is refused and the detail left as it is")
def _():
    g = _everybody_plants()
    r = g["env"].narrow("farming", 30, False)
    assert not r.ok and r.rejected and "left as it is" in r.error, dict(r)
    assert g["details"][4].flags.mode == 1 and TL.members(g, 4) == []


@test("L6 trim: with every member breaking down, `keep` of them stay rather than nobody")
def _():
    units = [{"id": i, "skills": [("FISH", s)]} for i, s in ((11, 9), (12, 7), (13, 5), (14, 3))]
    dets = [dict(d) for d in TL.DETAILS]
    dets[3] = {**dets[3], "members": [11, 12, 13, 14]}
    g = TL.game(units, [], dets)
    g["lua"].execute("local env = ...; env.dfhack.units.getStressCategory = function(u) return 0 end", g["env"])
    r = g["env"].trim("fishing", 2, False)
    assert r.ok and TL.members(g, 3) == [11, 12], (dict(r), TL.members(g, 3))


# --- the shelter ----------------------------------------------------------------

def shelter_world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, got, w = lua.execute(SHELTER, module_src("ai-society.lua"))
    # the well's own tile is its channelled hole: shape EMPTY (tiletype 2)
    lua.execute("""local env = ...
      env.df.tiletype.attrs[2] = {shape = 2}
      env.df.tiletype_shape[2] = 'EMPTY'
      function env.hole(x, y, z)
          for _, b in ipairs(env.df.global.world.map.map_blocks) do
              if b.map_pos.z == z and x >= b.map_pos.x and x < b.map_pos.x + 16 and y >= b.map_pos.y and y < b.map_pos.y + 16 then
                  b.tiletype[x - b.map_pos.x][y - b.map_pos.y] = 2
              end
          end
      end""", env)
    return lua, env, got, w


@test("L6 shelter: a well on its EMPTY hole inside the fort is in the shelter (its own tile too): no no_water")
def _():
    lua, env, got, w = shelter_world()
    lua.execute("""local env, w = ...
        env.hole(125, 150, 166)
        w.wells[1] = {centerx = 125, centery = 150, z = 166,
                      getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end}""", env, w)
    r = env.refresh_shelter()
    assert r.well_tiles == 1 and not r.no_water, dict(r)
    assert got["125,150,166"], "the well's own tile"


@test("L6 shelter: the only well in an open entrance's margin comes back with its 8 neighbours")
def _():
    lua, env, got, w = shelter_world()
    lua.execute("""local env, w = ...
        w.live[1].closed = false; w.hatch.door_flags.closed = false
        env.hole(110, 150, 169)
        w.wells[1] = {centerx = 110, centery = 150, z = 169,
                      getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end}""", env, w)
    r = env.refresh_shelter()
    assert r.open_entrances == 1 and r.well_tiles == 1 and r.drink_back == 1 and not r.no_water, dict(r)
    assert got["110,150,169"] and got["109,149,169"] and got["111,151,169"]


@test("L6 shelter: one mug for many and no well: more drink taken back from the margins; said short when none is left")
def _():
    lua, env, got, w = shelter_world()
    lua.execute("""local env, w = ...
        for i = 1, 20 do env.dfhack.units.getCitizens()[i] = {pos = {z = 170}} end
        w.live[1].closed = false; w.hatch.door_flags.closed = false
        w.drinks[1] = {flags = {}, pos = {x = 120, y = 150, z = 166}, stack_size = 1}       -- inside
        w.drinks[2] = {flags = {}, pos = {x = 112, y = 150, z = 170}, stack_size = 50}      -- in the margin
        """, env, w)
    r = env.refresh_shelter()
    assert r.drink_tiles == 2 and r.drink_units == 51 and r.drink_back == 1 and not r.drink_short, dict(r)
    assert got["112,150,170"]
    lua.execute("local w = ...; w.drinks[2] = nil", w)
    r = env.refresh_shelter()
    assert r.drink_units == 1 and "1 drink for 20 citizens" in r.drink_short, dict(r)


@test("L6 shelter: food in the margins comes back when the shelter holds none; no_food said otherwise")
def _():
    lua, env, got, w = shelter_world()
    lua.execute("""local env, w = ...
        w.live[1].closed = false; w.hatch.door_flags.closed = false
        env.df.global.world.items.other.ANY_GOOD_FOOD = {{flags = {}, pos = {x = 113, y = 151, z = 170}, stack_size = 9}}""",
                env, w)
    r = env.refresh_shelter()
    assert r.food_back == 1 and r.food_units == 9 and got["113,151,170"] and not r.no_food, dict(r)
    lua.execute("local env = ...; env.df.global.world.items.other.ANY_GOOD_FOOD = {}", env)
    assert env.refresh_shelter().no_food


# --- the recreation burrow --------------------------------------------------------

def soc():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, units, assigned, ntiles, g = lua.execute(SOC, module_src("ai-society.lua"))
    return lua, env, units, assigned, ntiles, g


@test("L6 recreation: every report lets out a member who is thirsty, hungry, in a tantrum or needs care")
def _():
    lua, env, units, assigned, ntiles, g = soc()
    r = env.recreation_tick(8, 28, False)
    assert assigned[1] and assigned[2] and assigned[7], dict(assigned)
    lua.execute("""local units, env = ...
        units[1].counters2 = {thirst_timer = 26000, hunger_timer = 0}
        units[2].counters = {soldier_mood = 2}; env.df.soldier_mood_type = {[2] = 'Tantrum'}
        units[7].health.flags.needs_healthcare = true""", units, env)
    s = env.recreation_status()
    assert s.members == 0 and len(_names(s.released_now)) == 3, dict(s)
    assert not assigned[1] and not assigned[2] and not assigned[7]


@test("L6 recreation: no tick for 9 days (the brain stopped asking): the report lets everyone out")
def _():
    lua, env, units, assigned, ntiles, g = soc()
    env.recreation_tick(8, 28, False)
    g.cur_year_tick = 1000 + 8 * 1200
    assert env.recreation_status().members == 3
    g.cur_year_tick = 1000 + 9 * 1200
    s = env.recreation_status()
    assert s.members == 0 and "no tick" in s.why and not assigned[1], dict(s)


@test("L6 recreation: the brain's release empties the burrow and moves nobody in")
def _():
    lua, env, units, assigned, ntiles, g = soc()
    env.recreation_tick(8, 28, False)
    r = env.recreation_tick(1, 28, False, None, 0, 7, True)
    assert r.ok and r.release and len(_names(r.released)) == 3 and not any(assigned[i] for i in (1, 2, 7)), dict(r)
    assert env.recreation_status().members == 0


@test("L6 recreation: no drink in the burrow: the nearest working well's 3x3 added; neither: nobody kept or moved in")
def _():
    lua, env, units, assigned, ntiles, g = soc()
    lua.execute("""local env = ...
        env.df.global.world.items.other.DRINK = {}
        env.df.global.world.buildings.other = {WELL = {{centerx = 90, centery = 90, z = 10}, {centerx = 40, centery = 40, z = 10}}}
        env.reqscript('ai-society-burrows').well_gives_water = function() return true end""", env)
    r = env.recreation_tick(8, 28, False)
    s = env.recreation_status()
    assert s.water == "well" and r.tiles == 6 and ntiles() == 6 + 9 and s.members == 3, (dict(r), dict(s), ntiles())
    lua.execute("local env = ...; assert(env.dfhack.burrows.isAssignedTile(nil, {x = 41, y = 41, z = 10}))", env)
    lua, env, units, assigned, ntiles, g = soc()
    lua.execute("local env = ...; env.df.global.world.items.other.DRINK = {}", env)
    r = env.recreation_tick(8, 28, False)
    # (0.105.36) waiting, not a refusal (no back-off on the shared key)
    assert r.ok and r.waiting and "no drink" in r.note and r.members == 0 and not assigned[1], dict(r)
    assert env.recreation_status().water is False


def _fort(members=6, total=60):
    s = tp.fort()
    s["society"]["recreation"] = {"members": members}
    s["dwarves"]["total"] = total
    return s


@test("B4 recreation (brain): members are let out when a threat is near, the fort shrank, or the needs section failed")
def _():
    for label, mut in (("threat", lambda s: s["others_on_map"].update(threats_that_can_reach_dwarves=1)),
                       ("shrunk", lambda s: s["dwarves"].update(total=25))):
        s = _fort()
        mut(s)
        p = []
        _recreation_rule(s, cfg, [], p, Memory())
        assert [x.action for x in p] == [{"type": "recreation", "release": True, "max": 1, "days": cfg["recreation_days"]}], (label, p)
    s = _fort()
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    s["society"]["recreation"] = {"members": 0}
    p = []
    _recreation_rule(s, cfg, [], p, Memory())
    assert p == []                                               # nobody in: nothing to let out
    s = _fort()
    s["needs"] = {"error": "x"}
    p = []
    _needs_notes(s, cfg, [], p, Memory())
    assert [x.action["type"] for x in p if x.rule == "recreation"] == ["recreation"], p


# --- the calm burrow, the hospital, animals, homes, health ------------------------

@test("L6 calm burrow: the busy pile's drink tiles in the burrow emptied (drink elsewhere in the pile): the member let out")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(CALM, module_src("ai-society.lua"))
    lua.execute("""local W = ...
      W.drink2.x2 = 78
      W.drink2.contents = {}
      for x = 75, 78 do
          local it = W.item(2, {W.item(1)}); it.pos = {x = x, y = 5, z = 10}
          table.insert(W.drink2.contents, it)
      end
      table.insert(W.all, W.bld(60, 'Civzone', 73, 3, 79, 7, 10, {type = 3}))
      W.drink.contents = {}
    """, w)
    env.calm_burrow_tick(6, 3, False)
    assert w.drink_of(9) == 83
    assert env.calm_burrow_status().members >= 1
    lua.execute("""local W = ...
      local keep = {}
      for _, it in ipairs(W.drink2.contents) do if it.pos.x < 77 then table.insert(keep, it) end end
      W.drink2.contents = keep""", w)                       # the 2 barrels by the room drunk; 2 far ones left
    s = env.calm_burrow_status()
    assert any("dwarf 9 (no drink)" == x for x in _names(s.released_now)), _names(s.released_now)


@test("L6 hospital burrow: the report's sources are cached (the piles' contents not read again), the chosen pile re-checked")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(HOSP, module_src("ai-society.lua"))
    lua.execute("""local env = ...
        local real = env.dfhack.buildings.getStockpileContents
        env.READS = 0
        env.dfhack.buildings.getStockpileContents = function(b) env.READS = env.READS + 1; return real(b) end""", env)
    env.hospital_burrow_tick(30, 10, False)
    tick = env.READS
    env.hospital_burrow_status()          # (0.105.36) the tick's fresh sources are the report's cache
    first = env.READS - tick
    env.hospital_burrow_status()
    second = env.READS - tick - first
    assert tick > first and first <= 2 and second <= 2, (tick, first, second)
    lua.execute("local W = ...; W.drink.contents = {}", w)            # the chosen pile drunk dry: looked again
    s = env.hospital_burrow_status()
    assert s.drink != "stockpile" or s.members == 0 or s.why, dict(s)


@test("L6 pasture: a caravan's or a visitor's animal, or one led by a merchant, is never pastured")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute("""local src = ...
      local units = {}
      local function u(id, o) local x = {id = id, flags1 = {caged = false, merchant = o.merchant}, following = o.following}
          units[id] = x; return x end
      local trader = u(9, {merchant = true})
      local list = {u(1, {}), u(2, {merchant = true}), u(3, {following = trader}), u(4, {})}
      list[4].visitor = true
      local env = setmetatable({}, {__index = _G})
      env.df = {global = {world = {units = {active = list}}}, general_ref_type = {BUILDING_CIVZONE_ASSIGNED = 1},
                unit = {find = function(id) return units[id] end}}
      env.dfhack = {units = {isAlive = function() return true end, isTame = function() return true end,
                             isOwnCiv = function() return true end, isGrazer = function() return true end,
                             isVisitor = function(x) return x.visitor == true end,
                             getGeneralRef = function() return nil end}}
      env.reqscript = function() return {} end
      env.require = function() return {} end
      assert(load(src, 'ai-society', 't', env))()
      return env""", (ROOT / "lua" / "ai-society.lua").read_text(encoding="utf-8"))
    got = env.unpastured_grazers()
    assert [got[i].id for i in range(1, len(got) + 1)] == [1], [got[i].id for i in range(1, len(got) + 1)]


@test("L6 homes: a location's bedroom (a tavern's guest room) is never counted free nor given to a citizen")
def _():
    units = [{"id": 7, "thoughts": ["SleptGrass", "LackBedroom"]}]
    zones = [{"id": 13, "items": TH.BED}]
    env, owner_of, _ = TH.game(units, zones)
    assert env.census().free_bedrooms == 1
    env.load("""local env = ...
        env.dfhack.world = {getCurrentSite = function()
            return {buildings = {[0] = {getContents = function() return {building_ids = {[0] = 13}} end}}} end}""")(env)
    assert env.census().free_bedrooms == 0
    env.house(5, 0, False)
    assert owner_of(13) == -1


@test("L6 health: the infected's 3-day rest is never for one already thirsty; the survey writes only on a change")
def _():
    src = (ROOT / "lua" / "ai-health.lua").read_text(encoding="utf-8")
    assert "REST_THIRST = 20000" in src and "u.counters2.thirst_timer >= REST_THIRST" in src
    assert "if state_sig(d) ~= before then save_state(d) end" in src


if __name__ == "__main__":
    finish()
