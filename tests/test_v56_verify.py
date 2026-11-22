"""(v56 verify) Independent proofs against the round-1 merge (0.105.56 RC).

Each test here demonstrates a defect found in review and FAILS on the code
as merged (3757cd6). They are proofs, not fixes: a test passes once its bug
is fixed. See /home/claude/verify-v56.md for the findings (V1...).

    python tests/test_v56_verify.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import bridge_part_src  # noqa: E402  (r6) the bridge parts split
import test_i2_thirst as I2  # noqa: E402  (its fake fort)

sys.path.insert(0, str(ROOT / "brain"))

T, py, dwarf, drink = I2.T, I2.py, I2.dwarf, I2.drink


def thirst_world():
    I2.need_lua()
    return I2.world()


# --- g2: thirst_way --------------------------------------------------------------------------------

# A fake level for game_way_reader: tiles[(x, y)] = {shape, liquid, feature, outside, ...};
# missing tiles are solid natural rock. The dwarf's group 2 at x10 y10, the fort's drink group 1 at x14 y10.
READER_STUBS = r"""
local env, W, tiles = ...
local function tk(x, y) return x .. ',' .. y end
local function info(x, y, z)
    if x < 0 or y < 0 or x > 60 or y > 60 then return nil end
    local t = tiles[tk(x, y)]
    local o = {shape = 'WALL', material = 'STONE', aquifer = false, liquid = false, feature = false,
               outside = false, warm = false, designated = false, dig = 'No', smoothed = false,
               building = false, subterranean = true}
    if t then for k, v in pairs(t) do o[k] = v end end
    return o
end
local B = {tile_info = info,
           natural_wall = function(t)
               if t.aquifer or t.liquid or t.feature or t.outside or t.warm then return false end
               return t.shape == 'WALL' and not t.designated and not t.built
           end}
W.claims = {}
local C = {ai_regions = function() return {} end,
           ai_claim = function(R, x, y, z, shape) return W.claims[tk(x, y)] end}
env.dfhack.buildings = {findAtTile = function() return nil end}
env.dfhack.constructions = {findAtTile = function(p)
    local t = tiles[tk(p.x, p.y)]
    return (t and t.built) and {} or nil
end}
local old = env.reqscript
env.reqscript = function(name)
    if name == 'ai-builder' then return B end
    if name == 'ai-constructions' then return C end
    return old(name)
end
"""


def reader_world(tiles: dict):
    lua, env, w = thirst_world()
    lt = lua.table_from({f"{x},{y}": T(lua, v) for (x, y), v in tiles.items()})
    lua.execute(READER_STUBS, env, w, lt)
    w.zgroup[100] = 0              # nothing walkable but what a test marks
    return lua, env, w


@test("V1 game_way_reader: rock whose DIAGONAL neighbour is cavern/water is not offered for the thirst dig")
def _():
    # x12 y10 is rock; its orthogonal neighbours are rock or the way, but x13 y11 (diagonal) is
    # an open cavern tile with water: DF's water and the cavern's creatures both cross diagonals
    tiles = {(13, 11): {"shape": "FLOOR", "feature": True, "liquid": True, "depth": 7}}
    lua, env, w = reader_world(tiles)
    reader = env.game_way_reader(100)
    t = py(reader(12, 10))
    assert t["kind"] == "blocked", f"rock diagonally beside a flooded cavern tile offered to dig: {t}"


@test("V2 open_way: an AI wall of the cavern seal / the cistern is never taken down for a thirsty dwarf")
def _():
    lua, env, w = thirst_world()
    lua.execute(r"""
local env, W = ...
env.WAY_READER = function(z)
    return function(x, y)
        if x < 0 or x > 40 or y < 0 or y > 40 then return nil end
        if x <= 9 then return {kind = 'walk', group = 1} end           -- the cavern, with its pool
        if x == 10 then return {kind = 'wall', cat = W.cat} end        -- the AI's wall between
        if x <= 20 then return {kind = 'walk', group = 2} end          -- the fort side, no drink
        return {kind = 'blocked', why = 'not natural rock to dig'}
    end
end
W.done = {remove = {}}
env.WAY_DO = {remove = function(x, y, z) table.insert(W.done.remove, x .. ',' .. y) return true end,
              dig = function() return true end, unlock = function() return true end}
""", env, w)
    bad = []
    for cat in ("cavern_walls", "cistern"):
        w.cat = cat
        w.done.remove = lua.table_from([])
        w.zgroup[100] = 0
        w.gmap["5,10,100"] = 1
        drink(lua, w, 5, 10, 100, stack_size=10)
        dwarf(lua, w, 1 if cat == "cavern_walls" else 2, 45000, pos={"x": 15, "y": 10, "z": 100})
        w.gmap["15,10,100"] = 2
        r = py(env.open_way(1 if cat == "cavern_walls" else 2, False))
        if r.get("removed"):
            bad.append((cat, r.get("removed")))
    assert not bad, f"open_way took down the AI's {bad} walls (cavern seal / cistern) for a thirsty dwarf"


# --- g5: arm_first --------------------------------------------------------------------------------

@test("V3 arm_first: a forge with no fuel cannot make weapons: drafting is not held under a siege")
def _():
    import copy, json
    import digest
    import planner_war_hold as wh
    from planner import PLANNER_CONFIG
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    s = copy.deepcopy(base)
    s["others_on_map"]["threats"] = [{"id": 9, "name": "a goblin lasher", "invader": True, "can_reach_dwarves": True,
                                      "pos": {"x": 100, "y": 100, "z": 150}}]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    s = digest.normalize(s)
    s["supplies"]["fuel"] = 0                       # no charcoal or coke: the forge (not a magma one) is idle
    s["military"]["gear"] = {"soldiers": 10, "on_duty": 10, "armed": 2, "bars": {"IRON": 80}, "forges": 1}
    why = wh.arm_first(s, dict(PLANNER_CONFIG), {"make_gear": True})
    assert why == "", ("drafting held for weapons a fuel-less forge can't make, with an enemy in reach "
                       f"(up to 56 days): {why!r}")


# --- g6: the mood's slaughter ---------------------------------------------------------------------

def _lua_fn(file: str, name: str) -> str:
    import re
    src = bridge_part_src(file)   # (r6) a split bridge part: its files together
    m = re.search(r"^function " + re.escape(name) + r"\(.*?^end\n", src, re.S | re.M)
    assert m, name
    return m.group(0)


@test("V4 slaughter_pick_mood: the only adult male of a kind with young females is not taken (the herd's breeding)")
def _():
    I2.need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_lua_fn("ai-bridge-actions.lua", "slaughter_pick_mood"))
    # the fort's herd: 1 adult bull and 4 heifer calves (they breed once grown, with him), and two
    # young goats; adults before young, so the bull goes first
    animals = [{"id": 1, "race": "COW", "male": True, "adult": True, "born": 10}]
    animals += [{"id": 2 + i, "race": "COW", "male": False, "adult": False, "born": 500 + i} for i in range(4)]
    animals += [{"id": 20 + i, "race": "GOAT", "male": i == 0, "adult": False, "born": 600 + i} for i in range(2)]
    pick, race, n = lua.globals().slaughter_pick_mood(T(lua, animals))
    assert not (race == "COW" and pick["id"] == 1), "the cows' only bull taken for a mood (no calf born again)"



@test("V5 thirst report: a dwarf locked in the AI's moon cell (ai-threats, a werebeast) is 'cell', not 'no_path' "
      "(no_path now digs a way out: thirst_way)")
def _():
    lua, env, w = thirst_world()
    lua.execute(r"""
local env = ...
local old = env.reqscript
env.reqscript = function(name)
    local m = old(name)
    if name == 'ai-threats' then
        m.state = function() return {cells = {['5'] = {zone = 77, kind = 'bedroom', doors = {901}, tick = 0}}} end
    end
    return m
end
""", env)
    w.zgroup[100] = 0
    w.gmap["20,10,100"] = 1                       # the fort's drink, beyond the cell's locked door
    drink(lua, w, 20, 10, 100, stack_size=30)
    w.gmap["10,10,100"] = 2                       # the cell (a bedroom), its door locked by moon_cell
    dwarf(lua, w, 5, 30000, pos={"x": 10, "y": 10, "z": 100})
    _, by = I2.rows(env)
    assert by[5]["reason"] != "no_path", (f"the moon cell's werebeast reads {by[5]['reason']!r}: the thirst rule "
                                           "then digs or opens a way out of the cell")



# --- g6: the hospital's floor ---------------------------------------------------------------------

@test("V6 ai-moods hospital_boxes: no DF building object kept between calls (a removed zone is freed memory)")
def _():
    I2.need_lua()
    import re
    from lupa.lua53 import LuaRuntime
    from lua_modules_util import module_src
    fake = re.search(r'FAKE = r"""(.*?)"""', (ROOT / "tests" / "test_moods.py").read_text(encoding="utf-8"),
                     re.S).group(1)
    L = LuaRuntime(unpack_returned_tuples=True)
    W = L.execute(fake, module_src("ai-moods.lua"))
    W.reset()
    W.env.HOSPITAL_CACHE = None
    L.execute("""local W = ...
      local env = W.env
      W.zone = {id = 582, x1 = 104, x2 = 112, y1 = 166, y2 = 174, z = 163, contained_buildings = {}}
      env.df.abstract_building_type = {HOSPITAL = 'HOSPITAL'}
      env.df.building_type = {BOX = 'Box'}
      env.df.building = {find = function(id) return id == 582 and W.zone or nil end}
      env.dfhack.world = {getCurrentSite = function()
          return {buildings = {[0] = {getType = function() return 'HOSPITAL' end,
                                      getContents = function() return {building_ids = {[0] = 582}} end}}}
      end}
      env.dfhack.items.getPosition = function(it) return it.x, it.y, it.z end
      env.dfhack.buildings = {containsTile = function(b, x, y)
          if b.freed then error('read of a freed building') end
          return x >= b.x1 and x <= b.x2 and y >= b.y1 and y <= b.y2 end}
    """, W)
    env = W.env
    it = L.table_from({"x": 109, "y": 170, "z": 163})
    assert env.hospital_ground(it) is True
    # the player (or the AI's rebuild) takes the hospital zone away within the cached day:
    # DF frees the building; the cache still holds it
    L.execute("local W = ...; W.zone.freed = true; W.env.df.building = {find = function() return nil end}", W)
    kept = [v for v in (env.HOSPITAL_CACHE.zones or {}).values()] if env.HOSPITAL_CACHE else []
    assert not kept, ("hospital_boxes keeps the zone's building object for HOSPITAL_TICKS; DF memory read "
                      "after the zone is removed")



# --- g9: the fallen fort --------------------------------------------------------------------------

@test("V7 fallen: a mark left by one fort does not keep a newly loaded (paused) fort paused for good")
def _():
    # The overseer's loop plans only while the game runs ("Game is paused; planning resumes when it
    # runs"), and the fall ends only in one_cycle (fallen.note). With a mark in force the loop never
    # unpauses (fallen_idle), and fallen.idle() looks at nothing of the game now loaded. DF loads a
    # save paused: the player (or the keeper) loading another fort, or an earlier save, gets a game
    # that stays paused with no AI until someone unpauses it by hand.
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    loop = src[src.index("def main() -> int:"):]
    paused_branch = loop[loop.index('elif st.get("paused") and not answered:'):]
    paused_branch = paused_branch[:paused_branch.index("else:")]
    assert "one_cycle(" not in paused_branch          # (the premise: no cycle while paused)
    line = next(x for x in loop.splitlines() if "fallen_idle =" in x)
    assert "st" in line.split("fallen.idle(", 1)[1].split(")", 1)[0], (
        "fallen_idle is taken from the mark alone, whatever fort or date the status shows: " + line.strip())



@test("V8 open_way: with the gates shut against a siege, no tunnel is dug round the shut gate to the enemy's side")
def _():
    lua, env, w = thirst_world()
    # z100: the fort's inside x0-19 (group 2, no drink left), its gate at x20 (a locked door: 'blocked'),
    # the roofed entrance tunnel beyond it x21-40 (group 1, joined to the surface: the brook's water
    # zone and the besiegers); natural rock all round (y9, y11)
    lua.execute(r"""
local env, W = ...
env.WAY_READER = function(z)
    return function(x, y)
        if x < 0 or x > 60 or y < 0 or y > 30 then return nil end
        if y == 10 and x <= 19 then return {kind = 'walk', group = 2} end
        if y == 10 and x == 20 then return {kind = 'blocked', why = 'a locked door not the AI\'s'} end
        if y == 10 and x >= 21 then return {kind = 'walk', group = 1} end
        return {kind = 'rock'}
    end
end
W.done = {dig = {}}
env.WAY_DO = {remove = function() return true end, unlock = function() return true end,
              dig = function(x, y, z) table.insert(W.done.dig, x .. ',' .. y) return true end}
""", env, w)
    w.zgroup[100] = 0
    w.gmap["30,10,100"] = 1
    drink(lua, w, 30, 10, 100, stack_size=50)                 # beyond the gate
    w.gmap["15,10,100"] = 2
    dwarf(lua, w, 1, 40000, pos={"x": 15, "y": 10, "z": 100})
    w.armed = True                                            # the gates shut against enemies
    w.unit(T(lua, {"id": 99, "danger": True, "citizen": False, "pos": {"x": 23, "y": 10, "z": 100}}))
    r = py(env.open_way(1, False))
    dug = list(w.done.dig.values())
    assert not dug, f"thirst_way dug {dug} round the shut gate during a siege, an invader 2 tiles off: {r}"


if __name__ == "__main__":
    finish()
