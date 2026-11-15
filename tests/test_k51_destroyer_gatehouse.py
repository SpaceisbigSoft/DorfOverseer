"""(0.105.51) Every fort gets a gate a building destroyer can't break.

R3, 15 Nov: in C a Mountain Titan and a fire Hill Titan walked in by the
founding stair (x108 y149), held only by a hatch: destroyer_gate's drawbridge
was refused ("the way in at x108 y149 is a stair updown, which walls and
doors can't stand on ...") and nothing else was tried. The gatehouse (a
drawbridge at the end of a walled corridor in front of the stair's hatch)
was the War-hold's only, and in all six forts the embark wagon stood where
its walls go ("no wall can go at x109 y148 (floor, a Wagon stands there)")
for eight years. Now:
- every fort asks for a plain gatehouse (no traps) by its second year or at
  the first great danger (planner_gates.destroyer_gate_due / _gatehouse_rule);
- the scan says gatehouse "wagon" when only the embark wagon is in the way,
  and build_gatehouse takes the wagon down first (lua/ai-gates-scan.lua,
  ai-gates-works.lua); the refusal is asked again once it is gone;
- destroyer_gate asks for the gatehouse at the founding stair's lid before
  the drawbridge that can't stand on a stair.

    python tests/test_k51_destroyer_gatehouse.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan, record  # noqa: E402
import planner_gates as PG  # noqa: E402
import planner_holdfast as HF  # noqa: E402
from planner_core import abs_tick, Proposal  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = dict(PLANNER_CONFIG)
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))

# C's founding stair as its scan reported it (states/256-autumn.json, entrance 1)
C_STAIR = {"bridges_unworked": [], "closed": False, "closing": False, "door_spots": 0,
           "equipment": [{"id": 10, "kind": "hatch", "lever_away": False, "levers": []}],
           "gatehouse": "none",
           "gatehouse_why": "no room for a gatehouse round the hatch: west: no wall can go at x109 y148 (floor, a "
                            "Wagon stands there); south: no wall can go at x108 y148 (floor, a Wagon stands there)",
           "id": 1, "kind": "surface", "lid": True, "sealed": True, "width": 1, "x": 108, "y": 149, "z": 170}
C_SECOND = {"bridges_unworked": [], "closed": False, "closing": False, "door_spots": 0,
            "equipment": [{"id": 357, "kind": "hatch", "lever_away": False, "levers": []}],
            "id": 2, "kind": "surface", "sealed": True, "width": 1, "x": 131, "y": 130, "z": 167}
MOUNTAIN_TITAN = {"id": 900, "name": "Chantbeaches the Seed of Gems, Mountain Titan", "great_danger": True,
                  "destroyer": True, "kinds": ["Titan"], "can_reach_dwarves": False, "layer": "upper_levels",
                  "invader": False, "size": 20_000_000, "pos": {"x": 60, "y": 60, "z": 171},
                  "distance_to_nearest_dwarf": 80, "levels_from_nearest_dwarf": 0}


def stair(**kw):
    e = copy.deepcopy(C_STAIR)
    e.update(kw)
    return e


def fort(ents, threats=(), **ent_kw) -> dict:
    s = copy.deepcopy(BASE)
    s["others_on_map"]["threats"] = [copy.deepcopy(t) for t in threats]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = sum(1 for t in threats if t.get("can_reach_dwarves"))
    s["entrances"]["entrances"] = ents
    s["entrances"]["citizens_outside"] = 0
    s["entrances"]["stranded"] = []
    s["entrances"]["free_mechanisms"] = 5
    s["entrances"].update(ent_kw)
    return s


def founded(years_ago: int) -> Memory:
    m = Memory()
    m.chronicle = {"entries": [{"y": BASE["date"]["year"] - years_ago, "d": "1 Granite", "k": "founded",
                                "t": "the AI overseer began keeping this fort's memory"}], "years": {}}
    return m


def gatehouse_props(props):
    return [p for p in props if isinstance(p.action, dict) and p.action.get("type") == "build_gatehouse"]


# --- the brain ------------------------------------------------------------------------------

@test("destroyer_gate_due: a first-year fort with no danger: no; its second year, a great danger on the map "
      "(the caverns too) or one seen before: yes")
def _():
    s = fort([stair(gatehouse="possible")])
    assert PG.destroyer_gate_due(s, founded(0), CFG) is None
    assert PG.destroyer_gate_due(s, Memory(), CFG) is None                 # no chronicle: by danger only
    assert "second year" in PG.destroyer_gate_due(s, founded(1), CFG)
    cav = dict(MOUNTAIN_TITAN, layer="cavern_1", destroyer=False)
    assert "is on the map" in PG.destroyer_gate_due(fort([], [cav]), founded(0), CFG)
    m = founded(0)
    m.last_great_tick = abs_tick(s) - 50 * 1200
    assert "before" in PG.destroyer_gate_due(s, m, CFG)


@test("every fort: a plain gatehouse (no traps) at the founding stair's lid by its second year; "
      "not in its first, not twice, not without the lid")
def _():
    s = fort([stair(gatehouse="possible")])
    props, _ = plan(s, founded(1))
    g = gatehouse_props(props)
    assert len(g) == 1 and g[0].rule == "destroyer_gate", [(p.rule, p.action) for p in g]
    assert g[0].action == {"type": "build_gatehouse", "entrance_id": 1, "kind": "cage", "count": 0}, g[0].action
    assert "second year" in g[0].reason and "drawbridge" in g[0].reason
    props, _ = plan(s, founded(0))
    assert not gatehouse_props(props)
    m = founded(2)
    m.gatehouses["108,149,170"] = {"tick": 1}
    props, _ = plan(s, m)
    assert not gatehouse_props(props)
    # the second way in has no lid (no gatehouse field): nothing
    props, _ = plan(fort([dict(C_SECOND)]), founded(2))
    assert not gatehouse_props(props)


@test("C's stair (the embark wagon in the way, scan 'wagon'): asked, the wagon taken down first; "
      "the wagon's refusal waits 3 days, or none once the wagon is gone; other refusals 2 weeks")
def _():
    s = fort([stair(gatehouse="wagon")])
    m = founded(3)
    props, _ = plan(s, m)
    g = gatehouse_props(props)
    assert g and "embark wagon" in g[0].reason, [p.reason for p in g]
    now = abs_tick(s)
    p = Proposal("gatehouse", g[0].action, g[0].reason, 6)
    record([(p, {"ok": False, "wagon": True, "wagons": 1,
                 "error": "the embark wagon stands where the gatehouse goes: it is being taken down"})], s, m)
    assert m.gate_failures["gatehouse:108,149,170"].startswith(PG.GATEHOUSE_WAGON)
    e = stair(gatehouse="wagon")
    assert not PG.gatehouse_wanted(s, m, CFG, e, now + 1200)
    assert PG.gatehouse_wanted(s, m, CFG, e, now + 3 * 1200)
    assert PG.gatehouse_wanted(s, m, CFG, stair(gatehouse="possible"), now + 10)     # the wagon is gone
    m.gate_failures["gatehouse:108,149,170"] = "the drawbridge could not be placed"
    assert not PG.gatehouse_wanted(s, m, CFG, stair(gatehouse="possible"), now + 3 * 1200)
    assert PG.gatehouse_wanted(s, m, CFG, stair(gatehouse="possible"), now + 14 * 1200)
    assert not PG.gatehouse_wanted(s, m, CFG, stair(gatehouse="none"), now + 99 * 1200)


@test("War-hold: its trap gatehouse as before (and now past the wagon too)")
def _():
    s = fort([stair(gatehouse="wagon")])
    m = Memory()
    props = []
    PG._gatehouse_rule(s, m, CFG, s["entrances"]["entrances"], abs_tick(s), {"fortification": 120}, props)
    g = gatehouse_props(props)
    assert g and g[0].action["count"] >= 2 and "fortified fort" in g[0].reason, [p.action for p in props]
    assert g[0].rule == "gatehouse"


@test("C 256 (Mountain Titan, the lid's drawbridge refused as a stair): destroyer_gate asks for the gatehouse, "
      "not a drawbridge on the stair; the second way in keeps the old path")
def _():
    s = fort([stair(gatehouse="wagon"), dict(C_SECOND)], [MOUNTAIN_TITAN])
    props, notes = [], []
    HF._destroyer_gate_rule(s, CFG, props, notes, Memory())
    assert len(props) == 1 and props[0].rule == "destroyer_gate", [p.action for p in props]
    assert props[0].action == {"type": "build_gatehouse", "entrance_id": 1, "kind": "cage", "count": 0}
    assert "embark wagon" in props[0].reason
    # the gatehouse refused (not the wagon): the second way in gets its drawbridge try as before
    m = Memory()
    m.gate_failures["gatehouse:108,149,170"] = "no room for a gatehouse round the hatch"
    m.gate_failure_ticks["gatehouse:108,149,170"] = abs_tick(s)
    props = []
    HF._destroyer_gate_rule(s, CFG, props, [], m)
    assert props and props[0].action["type"] == "fortify_entrance", [p.action for p in props]
    # a gatehouse standing (its lever not linked yet): said, nothing asked there
    props, notes = [], []
    HF._destroyer_gate_rule(fort([stair(gatehouse="standing")], [MOUNTAIN_TITAN]), CFG, props, notes, Memory())
    assert not props and any("gatehouse" in n and "stands" in n for n in notes), notes
    # the titan within 15 tiles: nothing built there
    near = dict(MOUNTAIN_TITAN, pos={"x": 110, "y": 152, "z": 170})
    props, notes = [], []
    HF._destroyer_gate_rule(fort([stair(gatehouse="possible")], [near]), CFG, props, notes, Memory())
    assert not props and any("too close" in n for n in notes), notes


@test("plan(): one build_gatehouse a cycle with a titan about; plan() writes no memory")
def _():
    s = fort([stair(gatehouse="possible")], [MOUNTAIN_TITAN])
    m = founded(0)
    before = json.dumps(m.gate_failures, sort_keys=True), json.dumps(m.gatehouses, sort_keys=True)
    props, _ = plan(s, m)
    assert len(gatehouse_props(props)) == 1, [(p.rule, p.action) for p in gatehouse_props(props)]
    assert (json.dumps(m.gate_failures, sort_keys=True), json.dumps(m.gatehouses, sort_keys=True)) == before


@test("wiring: overseer label for the plain gatehouse; config keys")
def _():
    import overseer
    assert "walled corridor" in overseer.short({"type": "build_gatehouse", "entrance_id": 1, "count": 0})
    assert "trap corridor" in overseer.short({"type": "build_gatehouse", "entrance_id": 1, "count": 3})
    for k in ("destroyer_gate_year", "gatehouse_wagon_retry_ticks"):
        assert k in PLANNER_CONFIG, k


# --- the bridge (lua) -------------------------------------------------------------------------

HARNESS = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-gates', 't', env))()
local W = {}
-- '#' rock, '.' inside floor, 'o' outside floor, 's' stairs (inside),
-- 't' the top of the stair shaft (outside), 'g' the embark wagon on outside ground
function env.tile(x, y, z)
  local lvl = W.map[z]; if not lvl then return nil end
  local row = lvl[y]; if not row then return nil end
  local ch = row:sub(x + 1, x + 1)
  if ch == '' then return nil end
  if ch == '#' then return {walk = false, shape = 'WALL'} end
  return {walk = true, shape = (ch == 's' or ch == 't') and 'STAIR_UPDOWN' or 'FLOOR',
          outside = ch == 'o' or ch == 't' or ch == 'g', occupied = ch == 'g', depth = 0, material = 'STONE'}
end
W.buildings = {}
function env.gate_buildings() return W.buildings end
function env.building_at(x, y, z)
  local lvl = W.map[z]; local row = lvl and lvl[y]
  if row and row:sub(x + 1, x + 1) == 'g' then return 'Wagon' end
  return nil
end
W.down = {}
function env.wagon_at(x, y, z)
  local lvl = W.map[z]; local row = lvl and lvl[y]
  if row and row:sub(x + 1, x + 1) == 'g' then return {id = 77} end
  return nil
end
function env.take_down_wagon(b) table.insert(W.down, b.id) return true end
return env, W
"""


def lua_world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    M, W = lua.execute(HARNESS, module_src("ai-gates.lua"))
    return lua, M, W


def shaft(lua, M, W, wagon=True, width=40):
    """The founding stair's top 't' at x10 y8 on the surface (z1), the fort below (z0); the embark
    wagon (3x3) just north of it at x9-11 y5-7, as C's at x107-109 y146-148 by its stair at y149."""
    surface = []
    for y in range(19):
        row = ["o"] * width
        if wagon and 5 <= y <= 7:
            row[9:12] = ["g", "g", "g"]
        if y == 8:
            row[10] = "t"
        surface.append("".join(row))
    below = (["#" * width] * 8 + ["#" * 10 + "s" + "." * (width - 11)] + ["#" * 10 + "." * (width - 10)] * 4
             + ["#" * width] * 6)
    m = lua.table()
    for z, rows in ((0, below), (1, surface)):
        level = lua.table()
        for y, r in enumerate(rows):
            level[y] = r
        m[z] = level
    W.map = m
    lua.execute("local M, w = ...; M.map_size = function() return w, 19, 2 end", M, width)
    s0 = lua.table_from({i + 1: lua.table_from({"x": 30 + i, "y": 10, "z": 0}) for i in range(3)})
    W.buildings = lua.table_from({1: lua.table_from({"id": 7, "kind": "hatch", "x1": 10, "y1": 8, "x2": 10,
                                                     "y2": 8, "z": 1, "name": ""})})
    es, _, _ = M.find_entrances(s0, W.buildings)
    e = es[1]
    e.id = 1
    M.GATES = lua.table_from({"entrances": lua.table_from({1: e})})
    return s0, e


@test("lua: the embark wagon alone in the way: the scan says 'wagon' (it said 'none' in all six R3 forts)")
def _():
    if LuaRuntime is None:
        skip("needs lupa")
        return
    lua, M, W = lua_world()
    s0, e = shaft(lua, M, W, wagon=True)
    assert e.sealed and e.lid and e.gatehouse == "wagon", (e.gatehouse, e.gatehouse_why)
    assert "embark wagon" in e.gatehouse_why
    s0, e = shaft(lua, M, W, wagon=False)
    assert e.gatehouse == "possible", (e.gatehouse, e.gatehouse_why)


@test("lua: build_gatehouse with the wagon in the way takes it down and places nothing else; "
      "a dry run takes nothing down; with the wagon gone a plain gatehouse (0 traps) goes up")
def _():
    if LuaRuntime is None:
        skip("needs lupa")
        return
    lua, M, W = lua_world()
    s0, e = shaft(lua, M, W, wagon=True)
    placed = []
    M.place_hook = lambda text, pos: placed.append((text, pos.x, pos.y, pos.z)) or True
    M.name_hook = lambda pos, name: None
    r = M.build_gatehouse(1, "cage", 0, True, s0)
    assert r.ok is False and r.wagon and not placed and len(list(W.down.values())) == 0, dict(r)
    r = M.build_gatehouse(1, "cage", 0, False, s0)
    assert r.ok is False and r.wagon and r.wagons == 1 and "taken down" in r.error, dict(r)
    assert list(W.down.values()) == [77] and not placed, (list(W.down.values()), placed)
    s0, e = shaft(lua, M, W, wagon=False)
    r = M.build_gatehouse(1, "cage", 0, False, s0)
    assert r.ok and r.traps == 0 and r.walls > 0 and not r.wagon, dict(r)
    assert placed[0][0].endswith("(1x1)") and placed[0][3] == 1, placed[0]
    assert not any(t[0] == "Tc" for t in placed), placed


if __name__ == "__main__":
    finish()
