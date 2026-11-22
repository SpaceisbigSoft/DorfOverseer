"""(0.105.48 round 2) The gate and halt leftovers. The standing rule: the fort
is never sealed in; a halted or stopped AI leaves the fort open and changes
nothing else.

  * way_out_open: a later try pulls a bridge at once (a dwarf's queued pull
    taken away first), and open_way's instant ignores a queued pull (A5 #11);
  * leave(): open_all's own queued pull no longer leaves the bridge to a
    dwarf; an entrance with nothing done and nothing waiting is not listed
    (waiting 0 is truthy in Lua) (A5 #12); its dry run restores nothing (A1 #7);
  * a rescan keeps the watcher's heartbeat, marks and counters (A5 #13);
  * the scan names only the AI's own unnamed gates "AI gate..." (A5 #15);
  * the mission holds are forgotten when the map unloads, and a hold from a
    later date or another entrance numbering is no hold (A5 #17);
  * the kill zone counts trap blades only, not the soldiers' weapons (A5 #18);
  * halted: `ai-bridge run` and the unpause action refuse; the `entrances`
    report restores, takes up links, pulls and starts nothing;
  * train_cook's cooldown is cook_train_cooldown_ticks (A9 #13);
  * one "brain away" rule (ai-util brain_away) for the gate watcher and
    ai-status's away watcher: a slow live brain is never away.

    python tests/test_k48_gate_halt.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402
from lua_modules_util import bridge_hub_src  # noqa: E402  (r8) the hub's text with its catalog and sections
from lua_modules_util import module_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA = ROOT / "lua"


def lst(t):
    return [t[i] for i in range(1, len(t) + 1)] if t is not None else []


def _fake(file: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return node.value.value
    raise KeyError(name)


def need_lua():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")


# --- the way out ------------------------------------------------------------------------

def way_world():
    L = LuaRuntime(unpack_returned_tuples=True)
    env = L.execute(_fake("test_r47_way_out.py", "WAY_FAKE"), module_src("ai-way-out.lua"))
    L.execute("RESTORES = 0; G.gates_restore = function() RESTORES = RESTORES + 1 end")
    return L, env


@test("open_way instant: a dwarf's pull queued at the bridge's lever is no wait: pulled at once; without "
      "instant it still waits")
def _():
    need_lua()
    L, env = way_world()
    L.execute("G.lever_pull_pending = function(lid) return lid == 91 end")
    r = env.open_way(1)
    assert r.waiting >= 1 and 91 not in lst(L.eval("PULLS"))
    L.execute("PULLS = {}; B[7].door_flags.closed = true")
    r = env.open_way(1, L.eval("{instant = true}"))
    assert 91 in lst(L.eval("PULLS")), (lst(L.eval("PULLS")), r.did)
    assert L.eval("B[8].gate_flags.raised") is False


@test("leave: open_all's queued pull at the bridge's lever: the bridge lowered at once all the same; a dry run "
      "calls no gates_restore; an entrance with nothing done and nothing waiting is not listed")
def _():
    need_lua()
    L, env = way_world()
    # open_all queues a dwarf's pull at the bridge's lever (as set_entrance does)
    L.execute("""G.open_all = function() OPEN_ALL = OPEN_ALL + 1; G.GATES.armed = false; PENDING = true
                   return {ok = true, opened = 0} end
                 G.lever_pull_pending = function(lid) return PENDING == true and lid == 91 end""")
    r = env.leave(True)
    assert r.ok and r.dry_run and L.eval("RESTORES") == 0, "a dry run restored the saved gates"
    r = env.leave(False)
    assert L.eval("RESTORES") == 1
    assert 91 in lst(L.eval("PULLS")) and L.eval("B[8].gate_flags.raised") is False, r.entrances
    # nothing left of the AI's shut and the player's door open: nothing to list
    L.execute("B[9].door_flags.forbidden = false; PULLS = {}")
    r = env.leave(False)
    assert len(lst(r.entrances)) == 0, [dict(e) for e in lst(r.entrances)]


@test("the way-out guard: the first try leaves the bridge to a dwarf, the later ones pull at once")
def _():
    import planner_way_out as pw

    def _s():
        return {"date": {"year": 120, "tick": 5000}, "missions": {},
                "others_on_map": {"threats_that_can_reach_dwarves": 0},
                "settings": {"traits": {}}, "entrances": {"entrances": []},
                "way_out": {"known": True, "open": False, "inside_group": 6712, "edge_groups": 1,
                            "shut_by": [{"entrance": 1, "id": 8, "kind": "bridge", "raised": True, "lever": 91,
                                         "ai": True}],
                            "nearest_entrances": [1], "cause": {"invaders": 0, "great": 0, "seen": 0}}}

    class _Mem:
        way_out, way_in, second_way = {}, {}, {}
    NOW = 120 * 403200 + 5000
    m = _Mem()
    props, notes = [], []
    pw._way_out_rule(_s(), pw.PLANNER_CONFIG, props, notes, m)
    assert props and "instant" not in props[0].action
    m.way_out = {"tries": 1, "last_try": NOW - 10 * 1200, "since": NOW - 20 * 1200}
    props, notes = [], []
    pw._way_out_rule(_s(), pw.PLANNER_CONFIG, props, notes, m)
    assert props and props[0].action.get("instant") is True, [p.action for p in props]
    # (r5 p5) the action run on a stand-in ai-way-out (tests/bridge_behaviour.py), not the hub's text
    import bridge_behaviour as BB
    got, _, _ = BB.forwarded("way_out_open", {"id": 4, "instant": True}, "ai-way-out", "open_way")
    assert got == [("open_way", [4, {"dry_run": False, "instant": True}])], got
    got, _, _ = BB.forwarded("way_out_open", {"id": 4, "dry_run": True}, "ai-way-out", "open_way")
    assert got == [("open_way", [4, {"dry_run": True, "instant": False}])], got


# --- the gates module on a fake game --------------------------------------------------------

def gates_world(halted=False):
    L = LuaRuntime(unpack_returned_tuples=True)
    M = L.execute(r"""
      local src = ...
      local env = setmetatable({}, {__index = _G})
      assert(load(src, 'ai-gates', 't', env))()
      return env""", module_src("ai-gates.lua"))
    L.execute(_fake("test_k48_gates.py", "FAKE"), M)
    L.execute("""M, halted = ...
      HALTED = halted
      M.reqscript = function(name)
        if name == 'ai-mission-way' then return {mission_held = function() return false end} end
        if name == 'ai-status' then return {is_halted = function() return HALTED end} end
        error(name)
      end
      CALLED = {}
      for _, n in ipairs({'gates_restore', 'attach_links', 'open_lever_hatches', 'link_watch_start'}) do
        M[n] = function() CALLED[n] = (CALLED[n] or 0) + 1; return 0 end
      end
      M.link_jobs_pending = function() return true end
      M.GATES.armed = false
      M.GATES_ORIG.summary = function() return {entrances = {}} end""", M, halted)
    return L, M


@test("halted: the entrances report restores nothing, takes up no link, pulls no lever, starts no watch; "
      "not halted it does all four")
def _():
    need_lua()
    L, M = gates_world(halted=True)
    out = M.summary()
    assert out is not None
    called = dict(L.eval("CALLED"))
    assert called == {}, called
    L, M = gates_world(halted=False)
    M.summary()
    called = dict(L.eval("CALLED"))
    assert set(called) == {"gates_restore", "attach_links", "open_lever_hatches", "link_watch_start"}, called


@test("a rescan keeps the watcher's heartbeat, marks and counters (not its rescan flag); the player's unnamed "
      "hatch and bridge (and its lever) stay unnamed, the AI's own unnamed door is named 'AI gate...'")
def _():
    need_lua()
    L, M = gates_world()
    L.execute("""
      B[20] = {id = 20, door_flags = {closed = true, forbidden = false}, jobs = {}, x1 = 11, y1 = 8, z = 0}
      B[91].name = ''
      local G = M.GATES
      G.brain_tick, G.let_open, G.lever_opened, G.repaths = 777, 3, 2, 5
      G.close_pulled = {[8] = 123}
      G.rescan = true
      G.mine = {[20] = true}
      NEW = {{id = 1, kind = 'surface', x = 10, y = 8, z = 0, inside_list = {}, outs = {},
              equipment = {{id = 7, kind = 'hatch'}, {id = 20, kind = 'door'}},
              outer = {{id = 8, kind = 'bridge', lever_id = 91}}}}
      M.find_entrances = function() return NEW, {}, 0 end
      M.gate_buildings = function() return {} end
      M.fort_starts = function(s) return s end
      M.pick_levers = function() end
      M.drive_levers = function() end
      M.cut_survey = function() end""")
    M.scan_map(1 * 403200 + 6000)
    G = M.GATES
    assert G.scanned and G.brain_tick == 777 and G.let_open == 3 and G.lever_opened == 2 and G.repaths == 5
    assert G.close_pulled[8] == 123 and G.rescan is None and G.mine[20] is True
    assert str(L.eval("B[20].name")).startswith("AI gate 1"), L.eval("B[20].name")
    assert L.eval("B[7].name") in (None, ""), L.eval("B[7].name")
    assert L.eval("B[8].name") in (None, ""), L.eval("B[8].name")
    assert L.eval("B[91].name") in (None, ""), L.eval("B[91].name")
    # one the scan named before is still renamed
    L.execute("B[7].name = 'AI gate 4 (surface)'")
    M.scan_map(1 * 403200 + 6100)
    assert L.eval("B[7].name") == "AI gate 1 (surface)"


@test("a built gate of the AI's plan keeps its mark when its record is forgotten (named 'AI gate (built)')")
def _():
    need_lua()
    L, M = gates_world()
    L.execute("""
      df.building_type = {[1] = 'Door', [2] = 'Chair'}
      B[30] = {id = 30, x1 = 3, y1 = 3, z = 0, getType = function() return 1 end,
               getBuildStage = function() return 3 end, getMaxBuildStage = function() return 3 end}
      B[31] = {id = 31, x1 = 4, y1 = 3, z = 0, getType = function() return 2 end,
               getBuildStage = function() return 3 end, getMaxBuildStage = function() return 3 end}""")
    kept = M.prune_gate_planned(L.eval("{'3,3,0@30', '4,3,0@31'}"))
    assert len(lst(kept)) == 0
    assert L.eval("B[30].name") == "AI gate (built)" and L.eval("B[31].name") is None


# --- the mission holds --------------------------------------------------------------------

MISSION = r"""
local src = ...
_G.SC_MAP_UNLOADED = 99
NOWT = 1 * 403200 + 5000
_G.df = {global = {cur_year = 1, cur_year_tick = 5000}}
_G.dfhack = {onStateChange = {}}
GATE_IDS = {[1] = {[7] = true}}
local G = {GATES = {entrances = {{id = 1}}}, entrance_gate_ids = function(e) return GATE_IDS[e.id] or {} end}
_G.reqscript = function(n) if n == 'ai-gates' then return G end error(n) end
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-mission-way', 't', env))()
return env
"""


@test("mission holds: forgotten when the map unloads; one from a later date (an older save loaded) is no hold; "
      "nor one whose entrance id now has none of its gates (a rescan renumbered them)")
def _():
    need_lua()
    L = LuaRuntime(unpack_returned_tuples=True)
    M = L.execute(MISSION, (LUA / "ai-mission-way.lua").read_text(encoding="utf-8"))
    M.hold(1, "raid")
    assert M.mission_held(1) is True
    L.eval("dfhack.onStateChange['ai-mission-way']")(99)
    assert M.mission_held(1) is False and len(lst(M.holds())) == 0
    # a hold made at a later date: an older save loaded
    M.hold(1, "raid")
    L.execute("df.global.cur_year = 0")
    assert M.mission_held(1) is False
    L.execute("df.global.cur_year = 1")
    M.hold(1, "raid")
    L.execute("GATE_IDS[1] = {[50] = true}")          # entrance 1 is another one now
    assert M.mission_held(1) is False


# --- the kill zone, the cook, the halt in the bridge ----------------------------------------

@test("kill zone: trap_weapons counts trap components only (the fort's spare weapons are the soldiers')")
def _():
    src = (LUA / "ai-killzone.lua").read_text(encoding="utf-8")
    i = src.index("out.trap_weapons =")
    line = src[i:src.index("\n", i)]
    assert "WEAPON'" not in line and "count_free('WEAPON')" not in src, line


@test("train_cook's cooldown is cook_train_cooldown_ticks (7 days), not the 2-day default")
def _():
    import planner  # noqa: F401  (loads planner_welfare)
    from planner_core import COOLDOWN_KEYS
    from planner_config import PLANNER_CONFIG
    key = COOLDOWN_KEYS.get("train_cook", "train_cook_cooldown_ticks")
    assert key in PLANNER_CONFIG and PLANNER_CONFIG[key] == 7 * 1200, key


@test("halted: `ai-bridge run` refuses before it unpauses; the unpause action refuses by itself too")
def _():
    src = bridge_hub_src()
    i = src.index("local function cmd_run(args)")
    body = src[i:src.index("\nend\n", i)]
    assert body.index("is_halted()") < body.index("pause_state = false"), "run unpauses while halted"
    j = src.index("    unpause = ")
    assert "is_halted()" in src[j:j + 400] and "act_unpause(a)" in src[j:j + 400]


# --- one "brain away" rule -------------------------------------------------------------------

@test("one brain-away rule (ai-util brain_away): ai-status's away watcher no longer stands down a slow live "
      "brain (2400 ticks, or more while it still polls); away only after BRAIN_AWAY_TICKS and no poll for "
      "BRAIN_AWAY_REAL_S; the gate watcher uses the same rule and values")
def _():
    need_lua()
    L = LuaRuntime(unpack_returned_tuples=True)
    M = L.execute(_fake("test_k48_alarm_halt.py", "STATUS"), module_src("ai-status.lua"))
    M.mark_seen()
    L.execute("df.global.cur_year_tick = 1000 + 2401")
    why, _ = M.away_state()
    assert why is None, "two days with no status call read as away"
    L.execute(f"df.global.cur_year_tick = 1000 + {int(M.AWAY_TICKS) + 1}")
    real = int(M.LAST_SEEN)
    why, _ = M.away_state(None, real + 60)
    assert why is None, "a slow brain still polling read as away"
    why, _ = M.away_state(None, real + int(M.AWAY_REAL_S) + 1)
    assert why == "away"
    U = M.reqscript("ai-util")
    assert int(M.AWAY_TICKS) == int(U.BRAIN_AWAY_TICKS) and int(M.AWAY_REAL_S) == int(U.BRAIN_AWAY_REAL_S)
    assert U.brain_away(10000, 1000, 500, 450) is False and U.brain_away(10000, 1000, 500, 100) is True
    assert U.brain_away(10000, 1000, None, None) is True and U.brain_away(2000, 1000, None, None) is False
    _, G = gates_world()
    assert int(G.UNATTENDED_TICKS) == int(U.BRAIN_AWAY_TICKS)
    assert int(G.UNATTENDED_REAL_S) == int(U.BRAIN_AWAY_REAL_S)
    for name in ("ai-gates-watch-look.lua", "ai-status.lua"):   # (r9) the watcher's look
        assert "U.brain_away(" in (LUA / name).read_text(encoding="utf-8"), name


finish()
