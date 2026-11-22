"""(0.105.47, J16) The way out: a fort never left sealed in.

Live 14 Nov (War-hold, DF 53.17): after the keepers stopped, the AI's own
surface gates (two hatches on "AI gate lever"s, the gatehouse bridge on its
lever) held the fort shut, the citizens' walk group reached no map-edge tile,
and the in-game gate watcher re-pulled the gates shut when the player pulled
them open. Tested here:
  * one helper for every door/hatch flag write (lua/ai-util.lua lock_door /
    shut_door / repath): no bare write anywhere else (a grep), and what it does;
  * lua/ai-way-out.lua on a stub map of walk groups: the edge groups, the
    citizens' group, the verdict, the cache, shut_by; open_way by the AI's own
    levers (never the player's gates, never a lever that works a well's
    hatch too); leave();
  * the in-game watcher (lua/ai-gates-watch.lua): a lockdown whose peak is
    unknown lifts on its own; the brain away; the player's pull respected;
  * the guard (brain/planner_way_out.py): a live cause waits and is capped,
    none opens at once, the try verified, then the dig, then Needs you;
  * the clean exit (overseer, keeper), the mission rule and gate_stuck using
    the same check, the wiring.

    python tests/test_r47_way_out.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from py_parts import py_family_src  # noqa: E402  (r7) overseer.py and its parts
from lua_modules_util import module_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

LUA = ROOT / "lua"


def lst(t):
    return [t[i] for i in range(1, len(t) + 1)] if t is not None else []


# --- the one helper ----------------------------------------------------------------

WRITE = re.compile(r"(door_flags(\.\w+|\[[^\]]+\])|gate_flags\.\w+)\s*=(?!=)")


@test("no bare door/hatch/bridge flag write outside ai-util: every lock, unlock, open or shut goes through "
      "lock_door / shut_door (DF's walk map redone)")
def _():
    bad = []
    for p in sorted(LUA.rglob("*.lua")):
        if p.name == "ai-util.lua":
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("--", 1)[0]
            if WRITE.search(code):
                bad.append(f"{p.name}:{i}: {line.strip()[:100]}")
    assert not bad, bad
    # and the eleven files that wrote them before call it
    for name in ("ai-lure", "ai-builder-wells", "ai-well-safety", "ai-gates-watch", "ai-threats", "ai-insane",
                 "ai-gates-stuck", "ai-gates-save", "ai-waterworks", "ai-killers"):
        src = (LUA / f"{name}.lua").read_text(encoding="utf-8")
        assert "lock_door(" in src or "lock_gate(" in src or "shut_door(" in src, name


UTIL_ENV = r"""
local src = ...
df = {global = {world = {reindex_pathfinding = false}, cur_year = 3, cur_year_tick = 100}}
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-util', 't', env))()
return env
"""


@test("ai-util lock_door / shut_door: the flag written, DF asked to redo its walk map once a tick; nothing "
      "changed: no repath; a building that can't be read: ok false")
def _():
    L = LuaRuntime(unpack_returned_tuples=True)
    U = L.execute(UTIL_ENV, (LUA / "ai-util.lua").read_text(encoding="utf-8"))
    b = L.eval("{door_flags = {forbidden = true, closed = true}}")
    changed, ok = U.lock_door(b, False, "t")
    assert changed is True and ok is True and b.door_flags.forbidden is False
    assert L.eval("df.global.world.reindex_pathfinding") is True and U.REPATH.n == 1
    L.execute("df.global.world.reindex_pathfinding = false")
    changed, ok = U.shut_door(b, False, "t")          # the same tick: asked once already
    assert changed is True and b.door_flags.closed is False and U.REPATH.n == 1 and U.REPATH.writes == 2
    L.execute("df.global.cur_year_tick = 101")
    changed, ok = U.lock_door(b, False)               # no change: no repath
    assert changed is False and ok is True and U.REPATH.n == 1
    changed, ok = U.lock_door(None, True)
    assert changed is False and ok is False
    assert U.door_changed(b) is True and U.REPATH.n == 2
    assert U.repath_summary().n == 2


# --- lua/ai-way-out.lua --------------------------------------------------------------

WAY_FAKE = r"""
local src = ...
INSIDE = 5
PULLS, JOBS, OPENED_E, OPEN_ALL = {}, {}, {}, 0
DANGERS = {}
B = {
  [7] = {id = 7, name = 'AI gate 1 (surface)', door_flags = {closed = true, forbidden = false}, jobs = {}, x1 = 5, y1 = 1, z = 2},
  [8] = {id = 8, name = 'AI gatehouse bridge', gate_flags = {raised = true}, jobs = {}, x1 = 5, y1 = 2, z = 2},
  [9] = {id = 9, name = '', door_flags = {closed = false, forbidden = true}, jobs = {}, x1 = 2, y1 = 1, z = 2},
  [90] = {name = 'AI gate lever'}, [91] = {name = 'AI gate lever'},
}
LINKS = {[7] = {90}, [8] = {91}}
G = {IMMINENT = 12, WIDE = 60}
G.GATES = {scanned = true, closed = {}, entrances = {
  {id = 1, kind = 'surface', x = 5, y = 1, z = 2,
   equipment = {{id = 7, kind = 'hatch', lever_driven = true, drive_lever = 90}, {id = 9, kind = 'door'}},
   outer = {{id = 8, kind = 'bridge', lever_id = 91}}},
  {id = 2, kind = 'cavern', x = 5, y = 5, z = 0, equipment = {}}}}
G.visible_dangers = function() return DANGERS end
G.distance_to = function(e, p) return math.max(math.abs(p.x - e.x), math.abs(p.y - e.y)) end
G.lever_links = function() return LINKS, {} end
G.lever_targets = function(levers, lid)
  local out = {}
  for tid, l in pairs(levers) do for _, x in ipairs(l) do if x == lid then table.insert(out, tid) end end end
  return out
end
G.entrance_gate_ids = function(e)
  local out = {}
  for _, l in ipairs({e.equipment or {}, e.outer or {}}) do for _, g in ipairs(l) do out[g.id] = true end end
  return out
end
G.ai_lever_name = function(n) return tostring(n):find('^AI gate') ~= nil end
G.seal_holds = function() return {ids = {}, levers = {}} end
G.seal_has = function(h, g) return h.ids[g.id] == true end
G.pull = function(lid) table.insert(JOBS, lid); return true end
G.pull_instant = function(lid)
  table.insert(PULLS, lid)
  for tid, l in pairs(LINKS) do for _, x in ipairs(l) do if x == lid then
    local b = B[tid]
    if b.door_flags then b.door_flags.closed = not b.door_flags.closed end
    if b.gate_flags then b.gate_flags.raised = not b.gate_flags.raised end
  end end end
  return true
end
G.lever_pull_pending = function() return false end
G.bridge_occupied = function() return false end
G.lock_gate = function(b, v) local c = b.door_flags.forbidden ~= v; b.door_flags.forbidden = v; return c, true end
G.open_entrance = function(id) table.insert(OPENED_E, id); G.GATES.closed[id] = nil; return {ok = true, opened = 0} end
G.gates_persist = function() end
G.gates_restore = function() end
G.open_all = function() OPEN_ALL = OPEN_ALL + 1; G.GATES.armed = false; return {ok = true, opened = 0} end
reqscript_real = reqscript
reqscript = function(n) if n == 'ai-gates' then return G end error('reqscript ' .. tostring(n)) end
df = {global = {world = {map = {x_count = 10, y_count = 10, z_count = 5}, reindex_pathfinding = false},
                plotinfo = {site_id = 1}, cur_year = 1, cur_year_tick = 100},
      building = {find = function(id) return B[id] end}}
dfhack = {gui = {showAnnouncement = function() end}, maps = {}}
xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-way-out', 't', env))()
READS = 0
env.group_at = function(x, y, z)
  READS = READS + 1
  if x == 0 or y == 0 or x == 9 or y == 9 then return 1 end
  return INSIDE
end
env.citizen_spots = function() return {{id = 1, x = 4, y = 4, z = 2}, {id = 2, x = 5, y = 5, z = 2}, {id = 3, x = 6, y = 4, z = 2}} end
return env
"""


def way_world():
    L = LuaRuntime(unpack_returned_tuples=True)
    env = L.execute(WAY_FAKE, module_src("ai-way-out.lua"))
    return L, env


@test("ai-way-out: the edge groups of a stub map (border tiles only, the surface's levels); the citizens' main "
      "group; sealed when it touches no edge group, open when it does")
def _():
    L, env = way_world()
    groups, n = env.edge_groups_of(4, 3, 0, 0, L.eval("function(x, y, z) return x * 10 + y end"))
    # the border of a 4x3 map: (0..3, 0), (0..3, 2), (0, 1), (3, 1)
    assert sorted(groups.keys()) == [1, 2, 10, 12, 20, 22, 30, 31, 32], sorted(groups.keys())
    assert n == 9                                # the tile at (0,0) reads group 0: no group
    g, cnt, at = env.main_group(L.eval("{{x=1,y=1,z=0},{x=2,y=2,z=0},{x=3,y=3,z=0}}"),
                                L.eval("function(x, y, z) return x == 3 and 9 or 4 end"))
    assert g == 4 and cnt == 2 and at.x == 1
    r = env.report()
    assert r.known is True and r.open is False and r.inside_group == 5 and r.edge_groups == 1
    sb = lst(r.shut_by)
    kinds = {p.id: p for p in sb}
    assert set(kinds) == {7, 8, 9}, set(kinds)
    assert kinds[7].ai is True and kinds[7].lever == 90 and kinds[7].closed is True
    assert kinds[8].ai is True and kinds[8].raised is True
    assert kinds[9].ai is False and kinds[9].locked is True       # the player's unnamed door: reported
    assert lst(r.nearest_entrances) == [1]
    L.execute("INSIDE = 1")
    env.EDGE.report = None                        # (read again)
    r = env.report()
    assert r.open is True and r.sealed_by_locks is True       # every surface entrance shut by a piece still


@test("ai-way-out: the edge groups are cached (a fort reading open): read again only every EDGE_EVERY reports "
      "or after a repath")
def _():
    L, env = way_world()
    L.execute("INSIDE = 1")                       # (0.105.51) open: a closed verdict is always read fresh
    env.report()
    first = L.eval("READS")
    env.report()
    second = L.eval("READS") - first
    assert second < first / 4, (first, second)     # only the citizens' groups read again
    U = env.reqscript("ai-util")
    U.REPATH.n = (U.REPATH.n or 0) + 1              # the walk map redone: read again
    before = L.eval("READS")
    env.report()
    assert L.eval("READS") - before >= first - 10
    for _ in range(int(env.EDGE_EVERY)):
        env.report()
    assert env.EDGE.report >= int(env.EDGE_EVERY)


@test("ai-way-out open_way: the AI's levered hatch pulled at once, its bridge by a dwarf's pull (at once with "
      "instant), the player's door left; a dry run pulls nothing; an enemy within IMMINENT: waiting")
def _():
    L, env = way_world()
    r = env.open_way(1, L.eval("{dry_run = true}"))
    assert r.ok and r.dry_run and lst(L.eval("PULLS")) == [] and lst(L.eval("JOBS")) == []
    assert "lever 90" in r.did and "lever 91" in r.did
    r = env.open_way(1)
    assert r.ok and lst(L.eval("PULLS")) == [90] and lst(L.eval("JOBS")) == [91], (lst(L.eval("PULLS")), r.did)
    assert L.eval("B[7].door_flags.closed") is False
    assert L.eval("B[9].door_flags.forbidden") is True and [p.id for p in lst(r.players)] == [9]
    assert L.eval("df.global.world.reindex_pathfinding") is True
    L.execute("B[8].gate_flags.raised = true; PULLS = {}; JOBS = {}")
    r = env.open_way(1, L.eval("{instant = true}"))
    assert lst(L.eval("PULLS")) == [91] and L.eval("B[8].gate_flags.raised") is False
    L.execute("B[7].door_flags.closed = true; DANGERS = {{pos = {x = 6, y = 3, z = 2}}}")
    r = env.open_way(1)
    assert not r.ok and r.waiting
    assert env.open_way(2).rejected                 # a cavern's entrance: never a way off the map


@test("ai-way-out open_way: a lever that also works something else (a cavern well's hatch) is never pulled; "
      "the watcher's booked entrance goes through open_entrance first")
def _():
    L, env = way_world()
    L.execute("LINKS[55] = {90}; B[55] = {id = 55, door_flags = {closed = true}}")
    r = env.open_way(1)
    assert 90 not in lst(L.eval("PULLS"))
    assert 7 in [p.id for p in lst(r.players)]
    L, env = way_world()
    L.execute("G.GATES.closed[1] = true")
    r = env.open_way(1)
    assert lst(L.eval("OPENED_E")) == [1] and r.ok


@test("ai-way-out leave: an enemy in reach: left as it is; none: the watcher stood down and the AI's gates "
      "pulled open at once (the bridge too), the player's door left")
def _():
    L, env = way_world()
    L.execute("DANGERS = {{pos = {x = 20, y = 1, z = 2}, invader = true}}")
    r = env.leave(False)
    assert not r.ok and r.enemy and L.eval("OPEN_ALL") == 0 and lst(L.eval("PULLS")) == []
    L.execute("DANGERS = {}")
    r = env.leave(True)
    assert r.ok and r.dry_run and L.eval("OPEN_ALL") == 0 and lst(L.eval("PULLS")) == []
    r = env.leave(False)
    assert r.ok and L.eval("OPEN_ALL") == 1 and sorted(lst(L.eval("PULLS"))) == [90, 91] and r.opened == 2
    assert L.eval("B[9].door_flags.forbidden") is True
    assert env.EDGE.report is None                 # the edge groups read again at the next report


# --- the in-game watcher -------------------------------------------------------------

WATCH = r"""
local M = ...
B = {}; PULLS = {}; JOBS = {}
NOW = 1 * 403200 + 5000
df = {building = {find = function(id) return B[id] end}, job_type = {PullLever = 9},
      global = {world = {units = {active = {}}, reindex_pathfinding = false}, cur_year = 1, cur_year_tick = 5000}}
dfhack = dfhack or {}
dfhack.units = {getCitizens = function() return {} end, isDead = function() return false end}
dfhack.timeout = function() return nil end
dfhack.timeout_active = function() return false end
dfhack.gui = {showAnnouncement = function() end}
CR_OK = 0
dfhack.run_command_silent = function(...)        -- the watcher's local pull (a dwarf's job)
  local a = {...}
  if a[1] == 'lever' then table.insert(JOBS, tonumber(a[4])) end
  return '', 0
end
M.reqscript = function(name)
  if name == 'ai-mission-way' then return {mission_held = function() return false end} end
  error(name)
end
DANGERS = {}
M.visible_dangers = function() return DANGERS end
M.citizens_outside = function() return 0 end
M.distance_to = function(e, p) return M.DIST end
M.ai_piece = function() return true end
M.lure_holds = function() return {} end
M.seal_holds = function() return {ids = {}, levers = {}} end
M.note_split_after_open = function() end
M.pull_instant = function(lid) table.insert(PULLS, lid); B[7].door_flags.closed = not B[7].door_flags.closed; return true end
M.pull = function(lid) table.insert(JOBS, lid); return true end
M.bridge_occupied = function() return false end
B[7] = {id = 7, door_flags = {closed = true, forbidden = false}, jobs = {}}
B[8] = {id = 8, gate_flags = {raised = false, raising = false, lowering = false}, jobs = {}}
M.GATES = {scanned = true, armed = true, closed = {[1] = true}, opening = {}, peak = nil, clear_looks = {},
  brain_tick = NOW,
  entrances = {{id = 1, kind = 'surface', x = 10, y = 8, z = 0, inside_list = {}, outs = {},
                equipment = {{id = 7, kind = 'hatch', lever_driven = true, drive_lever = 90, drive_ai = true, levers = {}}}}}}
"""


def watch_world(danger=True, dist=100):
    L = LuaRuntime(unpack_returned_tuples=True)
    M = L.execute(r"""
      local src = ...
      local env = setmetatable({}, {__index = _G})
      assert(load(src, 'ai-gates', 't', env))()
      return env""", module_src("ai-gates.lua"))
    L.execute(WATCH, M)
    if danger:
        L.execute("DANGERS = {{pos = {x = 0, y = 0, z = 0}}}")
    M.DIST = dist
    return L, M


@test("watcher: a lockdown whose peak is unknown (restored) lifts by itself after LIFT_CHECKS clear looks "
      "(no invader, nothing within WIDE); a known small peak after REOPEN_CHECKS, as before")
def _():
    L, M = watch_world()
    for _ in range(int(M.LIFT_CHECKS) - 1):
        M.check()
    assert M.GATES.closed[1] is True and lst(L.eval("PULLS")) == []
    M.check()
    assert not M.GATES.closed[1] and lst(L.eval("PULLS")) == [90] and M.GATES.lifted.lift == 1
    L, M = watch_world()
    M.GATES.peak = 1
    for _ in range(int(M.REOPEN_CHECKS)):
        M.check()
    assert not M.GATES.closed[1]
    L, M = watch_world()
    L.execute("DANGERS = {{pos = {x = 0, y = 0, z = 0}, invader = true}}")
    for _ in range(int(M.LIFT_CHECKS) + 2):
        M.check()
    assert M.GATES.closed[1] is True                # an invader in sight: kept shut (the brain decides)


@test("watcher, the brain away (no report for UNATTENDED_TICKS): shuts only for a danger within IMMINENT, and "
      "opens what it holds once nothing is within 2 x IMMINENT for UNATTENDED_CLEAR looks (an invader in sight "
      "far off too)")
def _():
    L, M = watch_world(dist=30)
    L.execute("DANGERS = {{pos = {x = 0, y = 0, z = 0}, invader = true}}")
    M.GATES.brain_tick = L.eval("NOW") - int(M.UNATTENDED_TICKS) - 1
    M.check()
    assert M.GATES.closed[1] is True and M.GATES.away is True
    M.check()
    assert not M.GATES.closed[1], "away: opened after two clear looks"
    L.execute("B[7].door_flags.closed = false")
    M.DIST = 30                                     # within WIDE, nobody outside: attended would shut
    M.check()
    assert not M.GATES.closed[1]
    M.DIST = 5
    M.check()
    assert M.GATES.closed[1] is True                # a real danger at the gate: shut
    M.GATES.brain_tick = L.eval("NOW")              # the brain back: the old rule
    assert M.brain_away() is False


@test("watcher: a gate it holds found open (the player's pull) with no danger within WIDE is left open and "
      "unbooked; with a danger within WIDE it is pulled shut again, as before; a held bridge let down likewise")
def _():
    L, M = watch_world(dist=100)
    L.execute("B[7].door_flags.closed = false")
    M.check()
    assert lst(L.eval("PULLS")) == [] and not M.GATES.closed[1] and M.GATES.let_open == 1
    L, M = watch_world(dist=40)
    L.execute("B[7].door_flags.closed = false")
    M.check()
    assert lst(L.eval("PULLS")) == [90] and M.GATES.closed[1] is True
    # the gatehouse bridge, down and still, booked shut
    for dist, pulled in ((100, False), (40, True)):
        L, M = watch_world(dist=dist)
        L.execute("""M = ...; M.GATES.entrances[1].equipment = {}
                     M.GATES.entrances[1].outer = {{id = 8, kind = 'bridge', lever_id = 91}}""", M)
        M.GATES.entrances[1].equipment = L.eval("{{id = 8, kind = 'bridge', lever_id = 91}}")
        M.check()
        assert (lst(L.eval("JOBS")) == [91]) == pulled, (dist, lst(L.eval("JOBS")))
        assert (M.GATES.closed[1] is True) == pulled


@test("watcher: a restored lockdown with no danger in sight is opened on load (lift_restored), kept with one near")
def _():
    for near, shut in ((False, False), (True, True)):
        L, M = watch_world(danger=near, dist=5)
        M.GATES.closed = L.eval("{}")
        M.GATES.armed = False
        M.GATES_ORIG.arm(L.eval("{closed = {[1] = true}}"))   # as gates_restore arms it
        assert (M.GATES.closed[1] is True) == shut, (near, M.GATES.closed[1])


# --- the guard -----------------------------------------------------------------------

def _s(**kw):
    s = {"date": {"year": 120, "tick": 5000}, "missions": {}, "others_on_map": {"threats_that_can_reach_dwarves": 0},
         "settings": {"traits": {}}, "entrances": {"entrances": []},
         "way_out": {"known": True, "open": False, "fresh": True, "inside_group": 6712, "edge_groups": 1,
                     "shut_by": [{"entrance": 1, "id": 9, "kind": "hatch", "x": 108, "y": 149, "closed": True,
                                  "lever": 145, "ai": True, "name": "AI gate 1 (surface)"},
                                 {"entrance": 3, "id": 99, "kind": "door", "x": 99, "y": 151, "locked": True,
                                  "ai": False}],
                     "nearest_entrances": [1, 3], "cause": {"invaders": 0, "great": 0, "seen": 0}}}
    s.update(kw)
    return s


class _Mem:
    def __init__(self):
        self.way_out = {}
        self.way_in = {}
        self.second_way = {}


NOW = 120 * 403200 + 5000


def _run(s, m):
    import planner_way_out as pw
    props, notes = [], []
    pw._way_out_rule(s, pw.PLANNER_CONFIG, props, notes, m)
    return props, notes


@test("guard: sealed with no live cause: the nearest AI gate opened at once (way_out_open); the player's door "
      "never; open: nothing")
def _():
    m = _Mem()
    props, notes = _run(_s(), m)
    assert [p.action for p in props] == [{"type": "way_out_open", "id": 1}], (props, notes)
    assert props[0].rule == "way_out" and "AI gate 1" in props[0].reason
    s = _s()
    s["way_out"]["open"] = True
    assert _run(s, m) == ([], [])


@test("guard: a live cause (invaders in sight, a threat that can reach the dwarves) keeps it shut; gone less "
      "than half a day: waits; gone longer: opened; a soft cause (the alert) capped at way_out_soft_days")
def _():
    import planner_way_out as pw
    m = _Mem()
    s = _s()
    s["way_out"]["cause"]["invaders"] = 3
    pw.note_way_out_cycle(s, m)
    props, notes = _run(s, m)
    assert props == [] and "kept shut for 3 invader(s) in sight" in notes[0], notes
    s2 = _s(others_on_map={"threats_that_can_reach_dwarves": 2})
    props, notes = _run(s2, m)
    assert props == [] and "kept shut" in notes[0]
    s3 = _s(date={"year": 120, "tick": 5300})          # the cause gone 300 ticks
    props, notes = _run(s3, m)
    assert props == [] and "danger is gone" in notes[0], notes
    s4 = _s(date={"year": 120, "tick": 5000 + 601})
    props, notes = _run(s4, m)
    assert [p.action["type"] for p in props] == ["way_out_open"]
    # the civilian alert: soft, at most way_out_soft_days
    m = _Mem()
    m.way_out = {"since": NOW - 3 * 1200}
    s5 = _s(civ_alert=True)
    props, notes = _run(s5, m)
    assert [p.action["type"] for p in props] == ["way_out_open"], notes
    m.way_out = {"since": NOW - 100}
    props, notes = _run(s5, m)
    assert props == [] and "the civilian alert" in notes[0]


@test("guard: an opening is verified at the next reports (waits way_out_retry_ticks), tried way_out_tries times, "
      "then a stair dug out (dig_way_in second), then Needs you; the way open again resets it")
def _():
    import planner_way_out as pw
    from planner_core import Proposal
    m = _Mem()
    p = Proposal("way_out", {"type": "way_out_open", "id": 1}, "", -1)
    pw.note_way_out(p, {"ok": True, "opened": 1}, _s(), m, NOW)
    assert m.way_out["tries"] == 1
    props, notes = _run(_s(date={"year": 120, "tick": 5050}), m)
    assert props == [] and "looks again" in notes[0]
    props, notes = _run(_s(date={"year": 120, "tick": 5200}), m)
    assert [p.action["type"] for p in props] == ["way_out_open"] and "try 2" in props[0].reason
    pw.note_way_out(props[0], {"ok": True}, _s(), m, NOW + 200)
    props, notes = _run(_s(date={"year": 120, "tick": 5400}), m)
    assert [p.action for p in props] == [{"type": "dig_way_in", "second": True}] and props[0].rule == "way_out_dig"
    pw.note_way_out(props[0], {"ok": True}, _s(), m, NOW + 400)
    m.way_out["digs"] = 2
    m.way_out["dig_tick"] = NOW - 10 * 1200
    m.way_out["since"] = NOW - 2 * 1200          # (0.105.51) sealed long enough to ask
    props, notes = _run(_s(date={"year": 120, "tick": 5400}), m)
    assert props == [] and any(n.startswith("NEEDS YOU") or "open a way by hand" in n for n in notes), notes
    s = _s()
    s["way_out"]["open"] = True
    out = pw.note_way_out_cycle(s, m)
    assert m.way_out == {} and out and "way off the map again" in out[0]


@test("guard: only the player's gates shut the way: left as they are; nothing shut at all: a stair dug out at "
      "once; an open gate DF holds shut on the way "
      "is the gate_stuck rule's; a waiting refusal isn't a try")
def _():
    import planner_way_out as pw
    from planner_core import Proposal
    m = _Mem()
    s = _s()
    s["way_out"]["shut_by"] = [x for x in s["way_out"]["shut_by"] if not x["ai"]]
    props, notes = _run(s, m)
    assert props == [] and "player's own door" in notes[0]     # the player's own seal: theirs, no hole dug
    s["way_out"]["shut_by"] = []                    # no gate shut at all (a collapse): dug out
    props, notes = _run(s, m)
    assert [p.action for p in props] == [{"type": "dig_way_in", "second": True}]
    s["entrances"] = {"entrances": [{"id": 1, "kind": "surface", "split": [{"id": 9, "kind": "hatch"}]}]}
    props, notes = _run(s, m)
    assert props == [] and "gate_stuck" in notes[0]
    p = Proposal("way_out", {"type": "way_out_open", "id": 1}, "", -1)
    pw.note_way_out(p, {"ok": False, "waiting": True}, _s(), m, NOW)
    assert not m.way_out.get("tries")
    pw.note_way_out(p, {"ok": False, "nothing": True}, _s(), m, NOW)
    assert m.way_out["tries"] >= pw.PLANNER_CONFIG["way_out_tries"]


@test("the same check: the mission rule leaves a sealed fort to the guard (no mission_way); gate_stuck steps on "
      "a sealed fort's split piece without the once-a-day wait")
def _():
    import planner_missions as pm
    import planner_gates as pg
    import planner_way_out as pw
    s = _s(missions={"way_out": {"known": True, "shut": [{"id": 1, "kind": "hatch", "x": 1, "y": 2}]}})
    props, notes = [], []
    assert pm.way_out_gate(s, pw.PLANNER_CONFIG, 9, "a raid", "raid 73", props, notes) is False
    assert props == [] and "way-out guard" in notes[0]
    s = _s(entrances={"entrances": [{"id": 1, "kind": "surface",
                                     "split": [{"id": 9, "kind": "hatch", "x": 1, "y": 2, "z": 3}]}]})

    class M2:
        gate_unstick = {"9": {"step": 1, "tick": NOW - 2000, "ok": True, "split_after": True, "prevent": NOW - 10}}
    props, notes = [], []
    pg._gate_stuck_rule(s, M2, pw.PLANNER_CONFIG, props, notes)
    assert [p.action for p in props] == [{"type": "unstick_gate", "id": 9, "step": 2}], (props, notes)
    s["way_out"]["open"] = True                     # not sealed: the old once-a-day prevent
    props, notes = [], []
    pg._gate_stuck_rule(s, M2, pw.PLANNER_CONFIG, props, notes)
    assert props == []


# --- the clean exit ------------------------------------------------------------------

class FakeBridge:
    def __init__(self, halted=False, in_fort=True, reply=None):
        self.acts, self.halted, self.in_fort = [], halted, in_fort
        self.reply = reply or {"ok": True, "opened": 3}

    def status(self):
        return {"in_fort": self.in_fort, "halted": self.halted}

    def state(self, include_units=True, tier=None):
        return {"fort": {}}

    def act(self, a):
        self.acts.append(a)
        return dict(self.reply)


@test("clean exit: leave_open sends way_out_leave and says what it did; the keeper's Ctrl-C does it (halted too; not "
      "out of a fort); an enemy in reach: said, the gates left; a dead bridge never raises")
def _():
    import planner_way_out as pw
    import keeper
    said = []
    b = FakeBridge()
    pw.leave_open(b, said.append)
    assert b.acts == [{"type": "way_out_leave"}] and "3 gate piece(s)" in said[0]
    b = FakeBridge(reply={"ok": False, "enemy": True, "error": "an enemy is in reach"})
    said = []
    pw.leave_open(b, said.append)
    assert "stay as they are" in said[0]
    # (0.105.48, K3) halted: the leave goes too (it passes the halt: it only lets go)
    for kw, n in (({}, 1), ({"halted": True}, 1), ({"in_fort": False}, 0)):
        fb = FakeBridge(**kw)
        keeper.LEAVE_BRIDGE = lambda fb=fb: fb
        try:
            keeper.leave_fort_open()
        finally:
            keeper.LEAVE_BRIDGE = None
        assert len(fb.acts) == n, (kw, fb.acts)

    class Dead:
        def status(self):
            raise OSError("no game")
    said = []
    assert pw.leave_open(Dead(), said.append) is None and "failed" in said[0]
    src = py_family_src("overseer")
    assert src.count("_leave_open(bridge)") >= 4         # Ctrl-C (twice), the STOP file, the run's end
    assert "leave_fort_open()" in (ROOT / "brain" / "keeper.py").read_text(encoding="utf-8")


@test("wiring: the way_out section (in the pulse too) and its digest default, the two actions with dry runs and "
      "labels, the module listed, the rules emergencies, the planner calls")
def _():
    # (r5 p5) the loaded hub's tables and a stand-in ai-way-out (tests/bridge_behaviour.py), not its text
    import bridge_behaviour as BB
    acts = ["way_out_open", "way_out_leave"]
    BB.wired(section="way_out", module="ai-way-out", pulse=True, actions=acts, dry=acts, modules=["ai-way-out"])
    import overseer
    import planner
    from planner_core import EMERGENCY, NO_COOLDOWN, STEER_PROTECTED
    import digest
    assert digest.SECTION_DEFAULTS["way_out"] == {}
    assert "way_out_open" in overseer.SHORT_WORDS and "way_out_leave" in overseer.SHORT_WORDS
    assert {"way_out", "way_out_dig"} <= EMERGENCY & NO_COOLDOWN & STEER_PROTECTED
    assert planner._way_out_rule and planner.note_way_out and planner.note_way_out_cycle
    from planner_core import Memory
    assert Memory.from_dict(Memory().to_dict()).way_out == {}


finish()
