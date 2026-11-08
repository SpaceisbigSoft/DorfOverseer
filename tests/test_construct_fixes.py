"""(0.105.30 construction fixes) Regression tests for what an independent
verifier found in the construction round: the shelter's surface exclusion
(drink, a fort DF reads all not subterranean, the AI's hall and keep), the
deep depot's wagon check taking down what guards the fort, the sealed
style walling citizens out, and the smaller seams (next_blocks, the blocks
rule's quiet check, wing pieces at the cleanup, doors on the wagon road,
the wagon drawbridge, the sealed walls' record, the survey's `missing`, the
keep's box at the gate scan). Needs lupa.

    python tests/test_construct_fixes.py
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)


def _const(path: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / path).read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name)


# --- 1. the shelter (ai-society fill_shelter) ------------------------------------------

FAKE = _const("test_construct_gates.py", "SHELTER_FAKE")
FAKE = FAKE.replace("local src, ncit, rule, entrance = ...", "local src, ncit, rule, entrance, drinks, builder = ...")
FAKE = FAKE.replace(
    "buildings = {other = {STOCKPILE",
    "items = {other = {DRINK = vec(drinks and (function() local t = {} for i, p in ipairs(drinks) do "
    "t[i] = {flags = {}, pos = p} end return t end)() or {})}},\n buildings = {other = {STOCKPILE")
FAKE = FAKE.replace(
    "maps = {getTileType",
    "items = {getContainer = function() return nil end, "
    "getPosition = function(it) return it.pos.x, it.pos.y, it.pos.z end},\n maps = {getTileType")
FAKE = FAKE.replace("    if name == 'ai-gates' then return {GATES = gates} end",
                    "    if name == 'ai-gates' then return {GATES = gates} end\n"
                    "    if name == 'ai-builder' and builder then return builder end")
assert "builder then return builder" in FAKE and "DRINK" in FAKE
ALL = 13 * 512


def shelter(rule_src, ncit=2, drinks=None, builder=None):
    lua = LuaRuntime(unpack_returned_tuples=True)
    rule = lua.eval(rule_src)
    dr = lua.table_from([lua.table_from({"x": x, "y": y, "z": z}) for x, y, z in drinks]) if drinks else None
    b = lua.eval(builder) if builder else None
    env, got = lua.execute(FAKE, module_src("ai-society.lua"), ncit, rule, False, dr, b)
    return env.refresh_shelter(), got


@test("shelter 1a: drink on a dark top level DF doesn't flag subterranean comes back (no no_water)")
def _():
    r, got = shelter("function(x, y, z) if z == 172 then return false, false end return true, false end",
                     ncit=10, drinks=[(100, 150, 172)])
    assert got["100,150,172"] and r.drink_tiles == 1 and not r.no_water and r.drink_back == 1, dict(r)
    assert r.tiles == ALL - 512 + 1 and r.surface_out == 511, dict(r)   # the rest of z172 stays out
    # a sunlit drink pile only when there is nothing else; a dark one first
    r, got = shelter("""function(x, y, z)
        if z == 172 and x >= 112 then return false, true end
        if z == 172 then return false, false end
        return true, false end""", ncit=10, drinks=[(120, 150, 172), (100, 150, 172)])
    assert got["100,150,172"] and not got["120,150,172"] and r.drink_tiles == 2 - 1, dict(r)


@test("shelter 1b: a fort DF reads all not subterranean: the whole fort (0.105.29), drink in it, one piece")
def _():
    r, got = shelter("function() return false, false end", ncit=10, drinks=[(100, 150, 162)])
    assert r.tiles == ALL and r.drink_tiles == 1 and not r.no_water and r.surface_mode == "unflagged", dict(r)
    levels = {}
    for k, v in got.items():
        if v:
            z = int(k.split(",")[2])
            levels[z] = levels.get(z, 0) + 1
    assert levels == {z: 512 for z in range(160, 173)}, levels


@test("shelter 1b: big fort mostly unflagged with a sunlit keep: the dark ones are the fort, the sunlit never")
def _():
    rule = """function(x, y, z)
        if z == 170 and x >= 113 and x <= 120 and y >= 146 and y <= 151 then return false, true end
        if z <= 161 then return true, false end
        return false, false end"""
    for ncit in (2000, 3300):                    # need 4000, and 6600 (more than all the dark ones)
        r, got = shelter(rule, ncit=ncit)
        assert r.tiles == ALL - 48 and r.surface_out == 48, (ncit, dict(r))
        assert not any(got[f"{x},{y},170"] for x in range(113, 121) for y in range(146, 152))


BUILDER = """{
  keep_data = function() return {x = 104, y = 150, z = 166, r = 4, stage = 'done'} end,
  halls_data = function() return {list = {{x1 = 110, y1 = 146, x2 = 118, y2 = 152, z = 170, stage = 'done'}}} end,
  deep_depot_data = function() return nil end}"""


@test("shelter 1c: the AI's hall and keep are never shelter, even short of tiles, whatever the flags say")
def _():
    for rule in ("function() return true, false end", "function() return false, false end"):
        for ncit in (2, 3300):
            r, got = shelter(rule, ncit=ncit, builder=BUILDER)
            keep = [f"{x},{y},{z}" for z in (166, 167) for x in range(100, 109) for y in range(146, 155)]
            hall = [f"{x},{y},{z}" for z in (170, 171) for x in range(110, 119) for y in range(146, 153)]
            assert not any(got[k] for k in keep + hall), (rule, ncit)
            assert r.ai_hall_tiles == len(keep) + len(hall) and r.tiles == ALL - r.ai_hall_tiles, dict(r)
    # a drink pile in the hall stays out with it
    r, got = shelter("function() return true, false end", ncit=2, drinks=[(112, 148, 170)], builder=BUILDER)
    assert not got["112,148,170"] and r.no_water, dict(r)


# --- 2 and 8. the deep depot's wagon check (ai-builder-surface) --------------------------------

DEPOT_SRC = (ROOT / "tests" / "test_deep_depot_wagons.py").read_text(encoding="utf-8")
_ns = {"__file__": str(ROOT / "tests" / "test_deep_depot_wagons.py"), "__name__": "construct_fixes_depot"}
# (its helpers and harnesses, its own tests left out: `test` a no-op here)
_src = DEPOT_SRC.replace("from harness import test, finish  # noqa: E402",
                         "test = lambda name: (lambda fn: fn)\nfinish = lambda *a: None")
assert _src != DEPOT_SRC
exec(compile(_src, "test_deep_depot_wagons", "exec"), _ns)
DL, DB, DW, DG = _ns["LUA"], _ns["B"], _ns["W"], _ns["G"]
d_reset, d_dig, d_tiles, d_status, d_setb = (_ns[k] for k in ("reset", "dig_and_build", "plan_tiles", "status", "setb"))


def removed():
    return list(DG.REMOVED.values())


def opened_hall():
    d_reset()
    d_dig(acc=0)
    hall = [(x, y, z) for x, y, z, r in d_tiles() if r == "d"][-1]
    DL.eval("""function(W, x, y, z)
      for dx = -1, 1 do for dy = -1, 1 do
        local t = W.get(x + dx, y + dy, z); if t.shape == 'WALL' then W.set(x + dx, y + dy, z, {shape = 'FLOOR'}) end
      end end end""")(DW, *hall)


@test("depot 2: the hall open into the fort: no door, floodgate, grate or bars on the road is taken down")
def _():
    for kind, occ in (("Door", "Dynamic"), ("Floodgate", "Impassable"), ("GrateWall", "Impassable"),
                      ("BarsVertical", "Impassable"), ("Hatch", "Dynamic")):
        opened_hall()
        floor = [(x, y, z) for x, y, z, r in d_tiles() if r == "d"][0]
        d_setb(*floor, {"occ": occ, "kind": kind, "id": 90})
        s = d_status()
        r = DB.place_deep_depot(False)
        assert s.opens_fort is not None and s.wagon_block.fix is None and removed() == [], (kind, dict(r))
        assert r.needs_you, (kind, dict(r))


@test("depot 2: a stair down from the hall's floor into the fort is an opening: the door on the road stays")
def _():
    d_reset()
    d_dig(acc=0)
    ds = [(x, y, z) for x, y, z, r in d_tiles() if r == "d"]
    x, y, z = ds[-1]
    DW.set(x, y, z, DL.table_from({"shape": "STAIR_DOWN"}))
    DW.set(x, y, z - 1, DL.table_from({"shape": "STAIR_UP"}))
    DW.set(x + 1, y, z - 1, DL.table_from({"shape": "FLOOR"}))
    d_setb(*ds[0], {"occ": "Dynamic", "kind": "Door", "id": 91})
    s = d_status()
    r = DB.place_deep_depot(False)
    assert s.opens_fort is not None and s.opens_fort.elevation == z - 1, dict(s)
    assert s.wagon_block.fix is None and removed() == [] and r.needs_you, dict(r)


@test("depot 2: sealed from the fort on every level: a door on the AI's own road is still taken down")
def _():
    d_reset()
    d_dig(acc=0)
    floor = [(x, y, z) for x, y, z, r in d_tiles() if r == "d"][0]
    d_setb(*floor, {"occ": "Dynamic", "kind": "Door", "id": 92})
    s = d_status()
    assert s.opens_fort is None and s.wagon_block.fix == "remove", dict(s)
    DB.place_deep_depot(False)
    assert removed() == [92]


@test("depot 8: a raised drawbridge on the road (the wagon gate at an alarm) is never marked for removal")
def _():
    d_reset()
    d_dig(acc=0)
    floor = [(x, y, z) for x, y, z, r in d_tiles() if r == "d"][0]
    d_setb(*floor, {"occ": "Impassable", "kind": "Bridge", "id": 93})
    s = d_status()
    r = DB.place_deep_depot(False)
    assert s.opens_fort is None and s.wagon_block.fix is None and removed() == [] and r.needs_you, dict(r)


# --- the gates (ai-gates) -------------------------------------------------------------------

GATES_HARNESS = _const("test_construct_gates.py", "GATES_HARNESS")


def gates():
    lua = LuaRuntime(unpack_returned_tuples=True)
    M, W = lua.execute(GATES_HARNESS, module_src("ai-gates.lua"))
    return lua, M, W


def set_map(lua, W, rows, width=40):
    lvl = lua.table()
    for y, r in enumerate(rows):
        lvl[y] = r
    m = lua.table()
    m[0] = lvl
    W.map = m
    W.size = lua.table_from({1: width, 2: len(rows)})
    W.keepouts = lua.table()


def K(x, y, z=0):
    return (z * 4096 + y) * 4096 + x


# the fort x1-9, the opening's inside at x9 (y1-3), the cavern x10-27, a
# miner's outpost x28-31 dug from the cavern (not cavern-flagged)
BEYOND = ["########################################",
          "#.........cccccccccccccccccc....########",
          "#.........cccccccccccccccccc....########",
          "#.........cccccccccccccccccc....########",
          "########################################"]


def beyond(cits):
    lua, M, W = gates()
    set_map(lua, W, BEYOND)
    lua.execute("""local env, cits = ...
      env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
      env.dfhack = {units = {getCitizens = function()
                        local out = {}
                        for i, p in ipairs(cits) do out[i] = {pos = p} end
                        return out end},
                    maps = {getWalkableGroup = function() return 1 end,
                            getTileFlags = function(x, y, z) local t = env.tile(x, y, z)
                                return {feature_global = t ~= nil and t.feature == true, feature_local = false} end}}
    """, M, lua.table_from([lua.table_from({"x": x, "y": y, "z": 0}) for x, y in cits]))
    e = lua.table_from({"kind": "cavern", "inside_list": lua.table_from([K(9, y) for y in (1, 2, 3)]),
                        "outs": lua.table_from({K(10, y): True for y in (1, 2, 3)})})
    return M.citizens_beyond(e)


@test("sealed 3: a miner in an outpost reached only through the cavern counts as beyond it")
def _():
    assert beyond([(3, 2)]) == 0
    assert beyond([(3, 2), (30, 2)]) == 1                # the outpost: not cavern-flagged, walled out all the same
    assert beyond([(3, 2), (15, 2)]) == 1                # in the cavern, as before
    assert beyond([(3, 2), (9, 2)]) == 1                 # on the opening, as before


@test("keep 11: a citizen in the AI's keep (court and roof over LEDGE_MAX) seeds no fort of its own")
def _():
    lua, M, W = gates()
    # the fort x1-8 (128 tiles); a 12x16 roofed court (x20-31, y1-16: 192
    # tiles, over LEDGE_MAX) out on the surface, its door at x19 y6
    rows = ["oooooooooooooooooooooooooooooooooooooooo"]
    for y in range(1, 17):
        rows.append("o" + "." * 8 + "#" * 10 + ("o" if y == 6 else "#") + "." * 12 + "#" * 7 + "o")
    rows.append("o" * 40)
    set_map(lua, W, rows)
    starts = lua.table_from([lua.table_from({"x": 3, "y": 3, "z": 0}), lua.table_from({"x": 25, "y": 6, "z": 0})])
    got = M.fort_starts(starts)
    assert len(got) == 2                                  # without the AI's record: two "forts"
    box = lua.table_from({K(x, y): True for x in range(19, 33) for y in range(0, 18)})
    M.ai_surface_box_keys = lambda: box
    got = M.fort_starts(starts)
    assert len(got) == 1 and got[1].x == 3, [(p.x, p.y) for p in got.values()]
    # only the keep's dwarf about: as before (never no fort at all)
    got = M.fort_starts(lua.table_from([lua.table_from({"x": 25, "y": 6, "z": 0})]))
    assert len(got) == 1


CLEAR = r"""
local src, under = ...
local env = setmetatable({}, {__index = _G})
local site = {}
env.dfhack = {persistent = {getSiteData = function(k, d) local v = site[k]; if v == nil then return d end return v end,
                            saveSiteData = function(k, v) site[k] = v end}}
assert(load(src, 'ai-gates', 't', env))()
local removed, at, built = {}, {}, {}
env.df = {trap_type = {Lever = 1}, tiletype = {attrs = setmetatable({}, {__index = function() return {shape = 'WALL'} end})},
          tiletype_shape = setmetatable({}, {__index = function() return 'WALL' end})}
env.df.building_type = setmetatable({}, {__index = function(_, k) return k end})
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.dfhack.maps = {getTileFlags = function(x, y, z)
                     return {subterranean = under, feature_global = under and x == 61, feature_local = false} end,
                   getTileType = function() return 1 end}
env.dfhack.constructions = {findAtTile = function(p) return built[p.x .. ',' .. p.y .. ',' .. p.z] end,
                            designateRemove = function(p) table.insert(removed, p.x .. ',' .. p.y .. ',' .. p.z)
                                                          return true, false end}
env.dfhack.buildings = {findAtTile = function(p) return nil end, deconstruct = function() end}
env.GATES = {scanned = true, entrances = {}}
return env, removed, built, site
"""


@test("cleanup 6: the wing walls recorded for a gone way in come down with its gate (and leave the record)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, rem, built, site = lua.execute(CLEAR, module_src("ai-gates.lua"), False)
    for k in ("50,50,10", "55,50,11", "56,50,11"):
        built[k] = True
    site[env.WINGS_KEY] = lua.table_from({"50,50,10": lua.table_from(["55,50,11", "56,50,11"])})
    r = env.clear_gate(50, 50, 10, lua.table_from(["50,50,10"]), False)
    got = sorted(rem.values())
    assert r.ok and got == ["50,50,10", "55,50,11", "56,50,11"] and r.wings == 2, (dict(r), got)
    assert env.wing_records()["50,50,10"] is None
    # a gate with no pieces of its own recorded, but wings: the wings
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, rem, built, site = lua.execute(CLEAR, module_src("ai-gates.lua"), False)
    built["55,50,11"] = True
    site[env.WINGS_KEY] = lua.table_from({"50,50,10": lua.table_from(["55,50,11"])})
    r = env.clear_gate(50, 50, 10, None, False)
    assert r.ok and list(rem.values()) == ["55,50,11"], dict(r)


@test("cleanup 9: under rock only walls the sealed style recorded come down")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, rem, built, site = lua.execute(CLEAR, module_src("ai-gates.lua"), True)
    built["60,50,10"] = True                      # a construction beside the cavern (x61): not the AI's
    r = env.clear_gate(60, 50, 10, lua.table_from(["60,50,10"]), False)
    assert not r.ok and "under rock" in r.error and len(rem) == 0, dict(r)
    env.note_sealed(lua.table_from(["60,50,10"]))
    r = env.clear_gate(60, 50, 10, lua.table_from(["60,50,10"]), False)
    assert r.ok and list(rem.values()) == ["60,50,10"], dict(r)


@test("gates 7: fortify on the depot's wagon road takes the wagon style whatever is asked: never a door")
def _():
    GL, M, GW = _ns["GL"], _ns["M"], _ns["GW"]
    _ns["gsetup"](road=[(4, 5), (4, 6), (4, 7)])
    three = [e for e in _ns["gfind"]() if e.width == 3][0]
    three.id = 1
    M.GATES = GL.table_from({"entrances": GL.table_from({1: three}), "scanned": True})
    M.doors_in = GL.eval("function(list) return {} end")
    M.stockpiles_in = GL.eval("function(list) return {} end")
    placed = []
    M.place_hook = lambda text, pos: placed.append(text) or True
    M.name_hook = lambda pos, name: True
    saved = M.wall_beside
    M.wall_beside = GL.eval("function() return true end")
    try:
        starts = GL.table_from({1: GL.table_from({"x": 20, "y": 5, "z": 0})})
        r = M.fortify(1, "plain", starts)
    finally:
        M.place_hook = None
        M.name_hook = None
        M.wall_beside = saved
    assert "d" not in placed, placed
    assert r.asked_style == "plain" and (r.style == "wagon" or not r.ok), dict(r)


# --- the brain -----------------------------------------------------------------------------

import planner_construct as pc  # noqa: E402
import scorecard  # noqa: E402
import digest  # noqa: E402
from planner import Memory  # noqa: E402
from planner_core import PLANNER_CONFIG as CFG  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
MERCHANT = {"trade": 120, "greed": 80, "outsiders": 100, "craftsmanship": 60, "stockpile": 40,
            "growth": 60, "surface": 40, "deference": 40}


@test("brain 4: the hall's next stage takes halls_status's next_blocks (next_tiles still read)")
def _():
    assert pc._next_tiles({"stage": "floor", "next_blocks": 36}, {}, CFG) == ("roof", 36)
    assert pc._next_tiles({"stage": "floor", "next_tiles": 12}, {}, CFG) == ("roof", 12)
    assert pc._next_tiles({"stage": "floor"}, {}, CFG)[1] == CFG["hall_stage_tiles"]["roof"]


def blocks_fort():
    s = copy.deepcopy(BASE)
    s["settings"]["traits"] = dict(MERCHANT)
    s["others_on_map"]["threats"] = []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s["stocks"]["blocks"] = 5
    s["buildings"]["halls"] = {"kind": "market_hall", "stage": "walls", "walls_planned": 0, "blocks_needed": 200}
    return s


@test("brain 5: the blocks rule is quiet with construct off on the Rules tab (rules_) and during a siege")
def _():
    ps = []
    pc._construction_blocks_rule(blocks_fort(), CFG, 194, MERCHANT, ps, [], Memory())
    assert ps and ps[0].rule == "construct_blocks"
    ps = []
    pc._construction_blocks_rule(blocks_fort(), CFG, 194, MERCHANT, ps, [], Memory(), {"construct": False})
    assert not ps
    s = blocks_fort()
    s["others_on_map"]["threats"] = [{"invader": True, "can_reach_dwarves": False, "race": "GOBLIN"}]
    ps = []
    pc._construction_blocks_rule(s, CFG, 194, MERCHANT, ps, [], Memory())
    assert not ps


@test("brain 10: a constructions survey that found no list (`missing`) shows no data, not zeros")
def _():
    s = {"constructions": {"missing": True, "total": 0, "by_shape": {"wall": 0}, "by_item": {"blocks": 0},
                           "surface": {"total": 0}, "roofed_surface_tiles": 0, "ai": {"gate_pieces": 0}}}
    m = scorecard.construction_measures(s, {})
    assert all(v is None for v in m.values()), m
    assert digest.built_line(s) == ""
    s["constructions"].pop("missing")
    assert scorecard.construction_measures(s, {})["built_up"] == 0


if __name__ == "__main__":
    finish()
