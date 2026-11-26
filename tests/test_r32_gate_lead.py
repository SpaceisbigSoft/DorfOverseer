"""(R32 d) Fort A's siege test (26 Nov 01:22): 25 armed goblins set down at
the map edge. The squads held gate 3 ("too strong to go out at"), nearest to
the one goblin nearest any gate, while 31 came at gate 1; gate 1 never shut
and gate 3 was seen shut with the nearest 0 tiles off. These pin:

  * the gate the squads hold is the one most enemies are heading to (each
    enemy's walk since the last cycle projected ahead), read again each cycle;
  * the watcher shuts an entrance while an approaching danger is still
    LEAD_LOOKS of its steps plus IMMINENT off (a goblin walks 10+ tiles a
    look), per entrance: every one a danger comes at;
  * the siege record: `closing` (a gate being built) is not "shut", and the
    distance is the watcher's own at its close.

    python tests/test_r32_gate_lead.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import finish, skip, test  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

from planner import Memory, PLANNER_CONFIG  # noqa: E402
import planner_siege_watch as W  # noqa: E402
import scenario_siege as SC  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = PLANNER_CONFIG
G1 = {"id": 1, "kind": "surface", "x": 20, "y": 50, "z": 100}
G3 = {"id": 3, "kind": "surface", "x": 80, "y": 50, "z": 100}


def gob(i, x, y, z=100):
    return {"id": 500 + i, "name": f"goblin {i}", "invader": True, "can_reach_dwarves": False,
            "layer": "upper_levels", "pos": {"x": x, "y": y, "z": z}, "distance_to_nearest_dwarf": 40}


def state(threats, day=1.0, squads=None):
    s = SC.at(SC.base_state(power=5.0), day, threats)
    s["entrances"]["entrances"] = [dict(G1, closed=False), dict(G3, closed=False)]
    if squads is not None:
        s["military"]["squads"] = squads
    return s


# --- (1) the gate they come at --------------------------------------------------------------

@test("gate pick: one goblin nearest gate 3, 24 nearer gate 1 -> gate 1 (by count, not the one nearest enemy)")
def _():
    rows = [gob(0, 82, 20)] + [gob(i, 15 + i % 3, 10 + i % 5) for i in range(1, 25)]
    g, counts = W.gate_they_come_at(state(rows), rows)
    assert g["id"] == 1 and counts == {3: 1, 1: 24}, (g, counts)


@test("gate pick: by heading -- the army midway between the gates walking toward gate 3 picks gate 3, and re-picks "
      "gate 1 when they turn")
def _():
    m = Memory()
    rows0 = [gob(i, 48, 45 + i) for i in range(10)]          # 28 from G1, 32 from G3: nearest is gate 1
    s0 = state(rows0, day=1.0)
    W.note_siege_watch(s0, m, CFG)
    assert W.gate_they_come_at(s0, rows0, m)[0]["id"] == 1   # no heading yet: where they stand
    rows1 = [gob(i, 52, 45 + i) for i in range(10)]          # 4 tiles east a cycle: heading for gate 3
    s1 = state(rows1, day=1.5)
    W.note_siege_watch(s1, m, CFG)
    g, counts = W.gate_they_come_at(s1, rows1, m)
    assert g["id"] == 3 and counts == {3: 10}, (g, counts)
    # the plan reading before this cycle's bookkeeping sees the same heading
    rows2 = [gob(i, 46, 45 + i) for i in range(10)]          # turned: 6 west a cycle
    s2 = state(rows2, day=2.0)
    g, _c = W.gate_they_come_at(s2, rows2, m)
    assert g["id"] == 1, g
    W.note_siege_watch(s2, m, CFG)
    assert W.gate_they_come_at(s2, rows2, m)[0]["id"] == 1


@test("gate pick: a tie keeps the gate an AI squad already holds; no entrance or no position: None")
def _():
    rows = [gob(0, 25, 50), gob(1, 75, 50)]
    sq = [{"id": 11, "ai_orders": 1, "stationed": {"x": 79, "y": 51, "z": 100}}]
    assert W.gate_they_come_at(state(rows, squads=sq), rows)[0]["id"] == 3
    assert W.gate_they_come_at(state(rows, squads=[]), rows)[0]["id"] == 1     # nearest, then the id
    s = state(rows)
    s["entrances"]["entrances"] = [dict(G1, kind="cavern")]
    assert W.gate_they_come_at(s, rows) == (None, {})
    nopos = [{"id": 9, "invader": True}]
    assert W.gate_they_come_at(state([]), nopos) == (None, {})


@test("siege hold (too strong to go out at): the squads hold the gate most come at, and follow them")
def _():
    import planner_holdfast as HF
    rows = [gob(0, 82, 20)] + [gob(i, 15 + i % 3, 10 + i % 5) for i in range(1, 25)]
    s = state(rows)
    pool = [dict(q) for q in s["military"]["squads"]]
    add, notes = [], []
    HF._siege_hold(s, CFG, rows, pool, "goblins", add, set(), notes)
    assert add and (add[0].action["x"], add[0].action["y"]) == (G1["x"], G1["y"]), add
    # they move on to gate 3; the squads stationed at gate 1 are sent to gate 3
    rows3 = [gob(i, 84, 40 + i % 5) for i in range(25)]
    pool3 = [dict(q, stationed={"x": 21, "y": 50, "z": 100}) for q in pool]
    add = []
    HF._siege_hold(state(rows3), CFG, rows3, pool3, "goblins", add, set(), notes)
    assert add and add[0].action["x"] == G3["x"] and add[0].action["squads"] == [q["id"] for q in pool3], add


@test("gate guard (out of reach): the gate they come at, not the main gate; no positions: the main gate as before")
def _():
    from planner_gates_lockdown import _gate_guard_rule
    rows = [gob(i, 84, 40 + i % 5) for i in range(6)]
    s = state(rows)
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    for q in s["military"]["squads"]:
        q.update(ai_orders=0, orders=0)
    m = Memory()
    m.atlas = {"plan": {"spine": {"x": 21, "y": 50}}}            # the main gate is gate 1
    props = []
    _gate_guard_rule(s, m, CFG, props)
    assert props and props[0].action["x"] == G3["x"], props
    for t in s["others_on_map"]["threats"]:
        t.pop("pos")
    props = []
    _gate_guard_rule(s, m, CFG, props)
    assert props and props[0].action["x"] == G1["x"], props


# --- the siege record -----------------------------------------------------------------------

@test("siege record: `closing` (a gate being built) is not shut; the watcher's closed_near is the distance kept")
def _():
    m = Memory()
    rows = [gob(0, 30, 50)]
    s = state(rows)
    s["entrances"]["entrances"] = [dict(G1, closed=False, closing=True), dict(G3, closed=True, closed_near=17)]
    W.note_siege_watch(s, m, CFG)
    g = m.holdfast["siege_watch"]["gates"]
    assert not g["1"].get("closed"), g["1"]
    assert g["3"]["closed"] and g["3"]["closed_near"] == 17 and g["3"]["closed_near_by"] == "watcher", g["3"]
    s2 = state(rows, day=1.5)
    s2["entrances"]["entrances"] = [dict(G1, closed=True)]       # an older bridge: the brain's own reading
    W.note_siege_watch(s2, m, CFG)
    g1 = m.holdfast["siege_watch"]["gates"]["1"]
    assert g1["closed"] and g1["closed_near"] == 10 and g1["closed_near_by"] == "brain", g1


@test("Lua sources: the watcher reads the lead distance; visible_dangers carries the unit id; summary closed_near")
def _():
    look = (ROOT / "lua" / "ai-gates-watch-look.lua").read_text(encoding="utf-8")
    chk = look[look.index("function check()"):look.index("local function watched_check()")]
    assert chk.count("lead_distance(e, vis, steps, prev_pos)") == 2 and "close_for(lead)" in chk
    assert "elseif close_for(nearest)" not in chk and "local close_now = close_for(nearest)" not in chk
    watch = (ROOT / "lua" / "ai-gates-watch.lua").read_text(encoding="utf-8")
    assert "{id = u.id, pos = u.pos," in watch
    wings = (ROOT / "lua" / "ai-gates-wings.lua").read_text(encoding="utf-8")
    assert "closed_near = GATES.closed and GATES.closed[e.id] and GATES.close_near" in wings


# --- (2) the watcher shuts in time (Lua, lupa) ----------------------------------------------

FAKE = r"""
local M = ...
B = {}; JOBS = {}
df = {building = {find = function(id) return B[id] end}, job_type = {PullLever = 9},
      global = {world = {units = {active = {}}, reindex_pathfinding = false}, cur_year = 1, cur_year_tick = 5000}}
dfhack = dfhack or {}
dfhack.units = {getCitizens = function() return {} end, isDead = function() return false end}
dfhack.timeout = function() return nil end
dfhack.gui = {showAnnouncement = function() end}
dfhack.persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end}
dfhack.job = {removeJob = function() return true end}
CR_OK = 0
dfhack.run_command_silent = function(...) return '', 0 end
M.reqscript = function(name)
  if name == 'ai-mission-way' then return {mission_held = function() return false end} end
  error(name)
end
DANGERS = {}
OUTSIDE = 3
M.visible_dangers = function() return DANGERS end
M.citizens_outside = function() return OUTSIDE end
M.distance_to = function(e, p) return math.max(math.abs(p.x - e.x), math.abs(p.y - e.y)) end
M.lure_holds = function() return {} end
M.seal_holds = function() return {ids = {}, levers = {}} end
M.brain_away = function() return false end
M.ai_halted = function() return false end
M.open_lever_hatches = function() return 0 end
B[7] = {id = 7, door_flags = {closed = false, forbidden = false}, jobs = {}}
B[17] = {id = 17, door_flags = {closed = false, forbidden = false}, jobs = {}}
M.GATES = {scanned = true, armed = true, closed = {}, opening = {}, peak = 0, clear_looks = {},
  entrances = {{id = 1, kind = 'surface', x = 20, y = 50, z = 0, outs = {}, equipment = {{id = 7, kind = 'door'}}},
               {id = 3, kind = 'surface', x = 80, y = 50, z = 0, outs = {}, equipment = {{id = 17, kind = 'door'}}}}}
function LOOK(list)
  DANGERS = {}
  for _, d in ipairs(list) do table.insert(DANGERS, {id = d[1], pos = {x = d[2], y = d[3], z = 0}, invader = true}) end
  df.global.cur_year_tick = df.global.cur_year_tick + 100
  M.check()
end
"""


def world():
    L = LuaRuntime(unpack_returned_tuples=True)
    M = L.execute(r"""
      local src = ...
      local env = setmetatable({}, {__index = _G})
      assert(load(src, 'ai-gates', 't', env))()
      return env""", module_src("ai-gates.lua"))
    L.execute(FAKE, M)
    return L, M


@test("lead (pure): a step is the walk since the last look (scaled to CHECK_TICKS), STEP_DEFAULT when first seen "
      "or after a leap; an approaching danger counts LEAD_LOOKS steps nearer, one walking away its distance")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    L, M = world()
    vis = L.eval("{{id = 1, pos = {x = 40, y = 50, z = 0}}, {id = 2, pos = {x = 60, y = 50, z = 0}}, "
                 "{id = 3, pos = {x = 0, y = 0, z = 0}}}")
    prev = L.eval("{[1] = {x = 52, y = 50, z = 0}, [2] = {x = 55, y = 50, z = 0}, [3] = {x = 90, y = 90, z = 0}}")
    steps, keep = M.danger_steps(vis, prev, 100)
    assert (steps[1], steps[2], steps[3]) == (12, 5, int(M.STEP_DEFAULT)), (steps[1], steps[2], steps[3])
    assert keep[1].x == 40
    steps2, _k = M.danger_steps(vis, prev, 200)                   # two looks' gap: per look
    assert steps2[1] == 6
    steps3, _k = M.danger_steps(vis, prev, None)                  # no tick: first seen
    assert steps3[1] == int(M.STEP_DEFAULT)
    e1 = M.GATES.entrances[1]                                       # x20: 1 at 20 coming (12/look), 2 going away
    near, lead = M.lead_distance(e1, vis, steps, prev)
    assert near == 20 and lead == 0, (near, lead)
    only2 = L.eval("{{id = 2, pos = {x = 60, y = 50, z = 0}}}")
    near, lead = M.lead_distance(e1, only2, steps, prev)
    assert near == 40 and lead == 40, (near, lead)                # walking away from gate 1: no lead
    e3 = M.GATES.entrances[2]
    near, lead = M.lead_distance(e3, only2, steps, prev)
    assert near == 20 and lead == 10, (near, lead)                # coming at gate 3, 5 a look: 20 - 10


@test("watcher (A 26 Nov): citizens outside, goblins walking 12 tiles a look at gate 1 -- shut while the nearest "
      "is still over IMMINENT off (before: at <=12, a look before it was at the gate)")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    L, M = world()
    imm = int(M.IMMINENT)
    seen = None
    for x in range(-100, 20, 12):                 # walking east toward gate 1 (x 20), 12 a look
        L.eval("LOOK")(L.eval("function(x) return {{1, x, 50}} end")(x))
        if M.GATES.closed[1] and seen is None:
            seen = 20 - x
    assert seen is not None and seen > imm, seen
    assert M.GATES.close_near[1] == seen
    assert not M.GATES.closed[3]                  # gate 3, nothing coming at it: open


@test("watcher: every gate a danger comes at shuts (two groups, two gates); one standing still far off, or "
      "walking away, shuts none")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    L, M = world()
    look = L.eval("LOOK")
    mk = L.eval("function(a, b) return {{1, a, 50}, {2, b, 50}} end")
    look(mk(-30, 130))
    for k in range(1, 6):
        look(mk(-30 + 10 * k, 130 - 10 * k))
    assert M.GATES.closed[1] and M.GATES.closed[3]
    L, M = world()
    look = L.eval("LOOK")
    one = L.eval("function(x) return {{1, x, 50}} end")
    look(one(-20))                                 # first seen 40 off: STEP_DEFAULT lead -> 20, not shut
    for _ in range(3):
        look(one(-20))                             # standing: no lead
    assert not M.GATES.closed[1]
    for k in range(1, 4):
        look(one(-20 - 10 * k))                    # walking away
    assert not M.GATES.closed[1] and not M.GATES.closed[3]


if __name__ == "__main__":
    finish()
