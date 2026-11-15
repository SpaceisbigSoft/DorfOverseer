"""(0.105.48, K2) Gates and the way out: the fort is never sealed in.

The audit (14 Nov, A5/A1/A9/A12) found, and these tests pin:
  * "found open: left open" orphaned the AI's own shut pieces (a bridge whose
    close pull a dwarf had not done yet read "opened by someone"; GATES.mine
    was wiped for the whole entrance, a hatch still locked became "not shut by
    the AI");
  * a close pull still queued when the lockdown ended raised the bridge later
    with no danger and nobody to lower it;
  * a door or hatch at rest (DF's `closed`) read as shut: "sealed in", a second
    stair dug; open_way could not undo the AI's own lock on a plain door;
  * nothing re-checked a saved lockdown after a load before a brain reported
    (on_map_loaded, the init file, `ai-bridge mapload`);
  * "brain away" after 2400 ticks with a live slow brain (the real-time ping);
  * the stranded check ignored the gatehouse bridge; a bridge was worked by any
    lever (the player's, one that works a floodgate too); the kill zone's ramp
    removal (its miner shut in the pit; a stage waiting for ever held every
    other zone); unstick_gate every day on a split nobody is shut out by.

    python tests/test_k48_gates.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA = ROOT / "lua"


def lst(t):
    return [t[i] for i in range(1, len(t) + 1)] if t is not None else []


# --- the watcher on a fake game (the real watcher, set_entrance, ai_piece) ---------------

FAKE = r"""
local M = ...
B = {}; JOBS = {}; PULLS = {}; REMOVED = 0; SITE = {}
df = {building = {find = function(id) return B[id] end}, job_type = {PullLever = 9},
      global = {world = {units = {active = {}}, reindex_pathfinding = false}, cur_year = 1, cur_year_tick = 5000}}
dfhack = dfhack or {}
dfhack.units = {getCitizens = function() return {} end, isDead = function() return false end}
dfhack.timeout = function() return nil end
dfhack.timeout_active = function() return false end
dfhack.gui = {showAnnouncement = function() end}
dfhack.persistent = {getSiteData = function(k, d) local v = SITE[k]; if v == nil then return d end return v end,
                     saveSiteData = function(k, v) SITE[k] = v end}
dfhack.job = {removeJob = function(j)
  for _, b in pairs(B) do
    for i, x in ipairs(b.jobs or {}) do if x == j then table.remove(b.jobs, i); REMOVED = REMOVED + 1; return true end end
  end
  return false
end}
CR_OK = 0
xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
-- the watcher's own pull (a dwarf's job): a PullLever job queued at the lever
dfhack.run_command_silent = function(...)
  local a = {...}
  if a[1] == 'lever' then
    local lid = tonumber(a[4])
    table.insert(JOBS, lid)
    B[lid] = B[lid] or {id = lid, jobs = {}}
    table.insert(B[lid].jobs, {job_type = 9})
  end
  return '', 0
end
-- the dwarf does the queued pull at lever lid: the bridge it works toggles
function DO_PULL(lid, bid)
  B[lid].jobs = {}
  B[bid].gate_flags.raised = not B[bid].gate_flags.raised
end
M.reqscript = function(name)
  if name == 'ai-mission-way' then return {mission_held = function() return false end} end
  error(name)
end
DANGERS = {}
M.visible_dangers = function() return DANGERS end
M.citizens_outside = function() return 0 end
M.distance_to = function(e, p) return M.DIST end
M.lure_holds = function() return {} end
M.seal_holds = function() return {ids = {}, levers = {}} end
M.note_split_after_open = function() end
M.pull_instant = function(lid) table.insert(PULLS, lid); return true end
M.bridge_occupied = function() return false end
B[7] = {id = 7, door_flags = {closed = true, forbidden = false}, jobs = {}}        -- a plain lid hatch, at rest
B[8] = {id = 8, gate_flags = {raised = false, raising = false, lowering = false}, jobs = {}}   -- the gatehouse bridge
B[91] = {id = 91, jobs = {}}                                                       -- its lever
M.GATES = {scanned = true, armed = true, closed = {}, opening = {}, peak = 0, clear_looks = {},
  brain_tick = 1 * 403200 + 5000,
  entrances = {{id = 1, kind = 'surface', x = 10, y = 8, z = 0, inside_list = {}, outs = {},
                equipment = {{id = 7, kind = 'hatch'}},
                outer = {{id = 8, kind = 'bridge', lever_id = 91}}}}}
"""


def gates_world(dist=5):
    L = LuaRuntime(unpack_returned_tuples=True)
    M = L.execute(r"""
      local src = ...
      local env = setmetatable({}, {__index = _G})
      assert(load(src, 'ai-gates', 't', env))()
      return env""", module_src("ai-gates.lua"))
    L.execute(FAKE, M)
    M.DIST = dist
    return L, M


def danger(L, on=True):
    L.execute("DANGERS = {{pos = {x = 0, y = 0, z = 0}}}" if on else "DANGERS = {}")


@test("watcher (A5 exp4): a hatch locked and the gatehouse bridge's close pull queued, then the danger 100 tiles "
      "off: not 'found open' while the pull waits (still booked, still the AI's); the pull lost: the whole "
      "entrance opened (the hatch unlocked too), nothing of the AI's left shut and forgotten")
def _():
    if LuaRuntime is None:
        return
    L, M = gates_world(dist=5)
    danger(L)
    M.check()
    assert M.GATES.closed[1] is True and L.eval("B[7].door_flags.forbidden") is True
    assert lst(L.eval("JOBS")) == [91] and M.GATES.mine[7] and M.GATES.mine[8]
    M.DIST = 100
    M.check()                                   # the pull still queued: the watcher's own, on its way
    assert M.GATES.closed[1] is True and M.GATES.mine[7] is True, "orphaned while its own pull waits"
    assert L.eval("B[7].door_flags.forbidden") is True
    # the job is lost (nobody does it) and ten looks pass: found open, let open
    L.execute("B[91].jobs = {}")
    L.execute("df.global.cur_year_tick = df.global.cur_year_tick + 11 * 100")
    M.check()
    assert not M.GATES.closed[1]
    assert L.eval("B[7].door_flags.forbidden") is False, "the AI's lock left on the hatch"
    assert not M.GATES.mine[7] and not M.GATES.mine[8]


@test("watcher (A5 exp3): a drawbridge's close pull still queued when the lockdown lifts is taken away, so the "
      "bridge is never raised later with no danger and no owner")
def _():
    if LuaRuntime is None:
        return
    L, M = gates_world(dist=5)
    L.execute("""M = ...; M.GATES.entrances[1].equipment = {{id = 8, kind = 'bridge', lever_id = 91}}
                 M.GATES.entrances[1].outer = {}""", M)
    M.GATES.peak = 1
    danger(L)
    M.check()
    assert M.GATES.closed[1] is True and len(lst(L.eval("B[91].jobs"))) == 1
    danger(L, False)
    for _ in range(int(M.REOPEN_CHECKS) + 1):
        M.check()
    assert not M.GATES.closed[1]
    assert len(lst(L.eval("B[91].jobs"))) == 0 and L.eval("REMOVED") == 1, "the stale close pull is still queued"
    assert L.eval("B[8].gate_flags.raised") is False


@test("watcher: opening, a bridge already rising (the dwarf's late pull begun) keeps the entrance booked and "
      "opening, so it is lowered once up (never left raised unowned)")
def _():
    if LuaRuntime is None:
        return
    L, M = gates_world(dist=100)
    L.execute("""M = ...; M.GATES.entrances[1].equipment = {{id = 8, kind = 'bridge', lever_id = 91}}
                 M.GATES.entrances[1].outer = {}; M.GATES.closed[1] = true; M.GATES.mine = {[8] = true}
                 B[8].gate_flags.raising = true""", M)
    M.GATES_ORIG.open_all()
    assert M.GATES.closed[1] is True


@test("open_entrance: an entrance unbooked with a piece the AI shut still shut opens that piece (no longer 'its "
      "gate was not shut by the AI'); the player's piece is left")
def _():
    if LuaRuntime is None:
        return
    L, M = gates_world(dist=100)
    L.execute("""M = ...; B[7].door_flags.forbidden = true; M.GATES.mine = {[7] = true}
                 B[8].gate_flags.raised = true""", M)
    r = M.open_entrance(1)
    assert r.ok, r.error
    assert L.eval("B[7].door_flags.forbidden") is False and lst(L.eval("JOBS")) == []   # the bridge: the player's
    L, M = gates_world(dist=100)
    L.execute("B[7].door_flags.forbidden = true")
    M.GATES.mine = L.eval("{}")
    r = M.open_entrance(1)
    assert r.ok is False and r.not_ai


@test("brain away: ticks alone no longer decide when the overseer polls (brain_ping); never pinged, or the ping "
      "older than UNATTENDED_REAL_S: away after UNATTENDED_TICKS (five days, not two)")
def _():
    if LuaRuntime is None:
        return
    L, M = gates_world()
    assert int(M.UNATTENDED_TICKS) >= 6000
    now = 1 * 403200 + 5000
    M.GATES.brain_tick = now - 2401
    assert M.brain_away(now) is False, "a slow brain (one report every 2400 ticks) read as away"
    M.GATES.brain_tick = now - int(M.UNATTENDED_TICKS) - 1
    assert M.brain_away(now) is True                              # never pinged: the ticks decide
    M.BRAIN_PING.t = 1000
    assert M.brain_away(now, 1000 + 30) is False                  # the overseer polls: present
    assert M.brain_away(now, 1000 + int(M.UNATTENDED_REAL_S) + 1) is True
    assert M.brain_ping() is not None
    br = (LUA / "ai-bridge.lua").read_text(encoding="utf-8")
    status = br[br.index("local function cmd_status()"):br.index("local function cmd_status()") + 900]
    assert "brain_ping()" in status


@test("pick_levers: a bridge is worked only by the AI's own lever (named 'AI gate...' or unnamed, working only "
      "this entrance): never the player's named lever, nor one that works a floodgate too")
def _():
    if LuaRuntime is None:
        return
    L, M = gates_world()
    ents = L.eval("""{{id = 1, x = 0, y = 0, z = 0, equipment = {
        {id = 8, kind = 'bridge', levers = {{id = 91, x = 50, y = 50, z = 0, name = 'Moat', targets = {8}}}},
        {id = 9, kind = 'bridge', levers = {{id = 92, x = 50, y = 50, z = 0, name = '', targets = {9, 300}}}},
        {id = 10, kind = 'bridge', lever_id = 93, levers = {{id = 93, x = 50, y = 50, z = 0, name = 'AI gate lever',
                                                             targets = {10}}}}}}}""")
    inside = L.eval("setmetatable({}, {__index = function() return true end})")
    M.pick_levers(ents, inside)
    eq = ents[1].equipment
    assert eq[1].lever_id is None and eq[2].lever_id is None and eq[3].lever_id == 93
    assert M.bridge_lever_ok(L.eval("{name = '', targets = {8}}"), L.eval("{[8] = true}")) is True


@test("stranded: a gatehouse's raised bridge (e.outer) in front of an open hatch shuts the way in (gate_shut, "
      "not no_path)")
def _():
    if LuaRuntime is None:
        return
    L, M = gates_world()
    L.execute("B[8].gate_flags.raised = true; dfhack.maps = {getWalkableGroup = function() return 5 end}")
    L.execute("M = ...; M.GATES.entrances[1].outs = {[1] = true}", M)
    w = M.entrance_ways(M.GATES.entrances[1])
    assert w.shut is True
    ways = L.eval("function(w) return {w} end")(w)
    cause, _w = M.stranded_cause(5, 1, ways, L.eval("{}"))[:2]
    assert cause == "gate_shut", cause
    L.execute("B[8].gate_flags.raised = false")
    assert M.entrance_ways(M.GATES.entrances[1]).shut is False


# --- after a load -----------------------------------------------------------------------

@test("on_map_loaded: a saved lockdown with no danger in sight is mapped, re-armed and opened at once; with an "
      "invader in sight it is held by the armed watcher; nothing saved: nothing done; once a load")
def _():
    if LuaRuntime is None:
        return
    for invader, opened in ((False, True), (True, False)):
        L, M = gates_world(dist=100)
        L.execute("""M = ...
          B[7].door_flags.forbidden = true
          SITE['ai-overseer/gates'] = {armed = true, gates = {{id = 7, kind = 'hatch'}}}
          SAVED_ENTS = M.GATES.entrances
          M.GATES = {scanned = false}
          M.scan = function() M.GATES.scanned = true; M.GATES.entrances = SAVED_ENTS; M.GATES.closed = {}
                              M.GATES.inside = {}; return M.summary() end
          M.stranded_citizens = function() return nil end
          M.attach_links = function() return 0 end
          M.gate_splits = function() end
          M.link_jobs_pending = function() return false end
          M.GATES_ORIG.summary = function() return {} end
        """, M)
        if invader:
            L.execute("DANGERS = {{pos = {x = 0, y = 0, z = 0}, invader = true}}")
        r = M.on_map_loaded()
        assert r.ok and r.mapped, (r.scan_error, r.nothing)
        assert (L.eval("B[7].door_flags.forbidden") is False) == opened, invader
        assert M.GATES.armed is True
        assert (M.GATES.closed[1] is True) == (not opened)
        assert M.on_map_loaded().already is True
    L, M = gates_world()
    M.GATES_SAVE.onload_done = None
    assert M.on_map_loaded().nothing is True


@test("on_map_loaded, no map (the scan failed): the saved gates opened by their ids unless a danger is near "
      "them; pure helpers")
def _():
    if LuaRuntime is None:
        return
    for near, opened in ((False, True), (True, False)):
        L, M = gates_world()
        L.execute("""M = ...
          B[7].x1, B[7].y1, B[7].z = 10, 8, 0
          SITE['ai-overseer/gates'] = {armed = true, gates = {{id = 7, kind = 'hatch'}}}
          M.GATES = {scanned = false}
          M.scan = function() error('no map') end
          OPEN_ALL = 0
          M.open_all = function() OPEN_ALL = OPEN_ALL + 1; return {ok = true, opened = 1} end
        """, M)
        if near:
            L.execute("DANGERS = {{pos = {x = 12, y = 8, z = 0}}}")
        r = M.on_map_loaded()
        assert (L.eval("OPEN_ALL") == 1) == opened and (r.kept is True) == near, (near, r.kept)
    assert M.nearest_to_spots(L.eval("{{pos = {x = 5, y = 5, z = 9}}}"), L.eval("{{x = 5, y = 5, z = 0}}")) == float("inf")
    assert M.live_danger(L.eval("{{great = true}}"), 1000) is True


@test("on load: the state hook runs on SC_MAP_LOADED; the init file runs `ai-bridge mapload` (a bridge command) "
      "and is written once into dfhack-config/init when missing")
def _():
    if LuaRuntime is None:
        return
    st = (LUA / "ai-gates-stuck.lua").read_text(encoding="utf-8")
    assert "sc == SC_MAP_LOADED" in st and "on_map_loaded" in st
    br = (LUA / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "mapload = cmd_mapload," in br and "on_map_loaded()" in br
    L, M = gates_world()
    assert "ai-bridge mapload" in M.ONLOAD_INIT_TEXT and M.ONLOAD_INIT_NAME.startswith("onMapLoad")
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "dfhack-config" / "init").mkdir(parents=True)
        L.execute("local d = ...; dfhack.getDFPath = function() return d end; "
                  "dfhack.filesystem = {mkdir_recursive = function() end}", d)
        assert M.install_onload_init() is True
        f = Path(d) / "dfhack-config" / "init" / str(M.ONLOAD_INIT_NAME)
        assert "ai-bridge mapload" in f.read_text()
        f.write_text("# the player's edit\n")
        assert M.install_onload_init() is True and f.read_text() == "# the player's edit\n"


@test("scan: a lockdown from the save waiting to be matched keeps the scan from opening its lever hatches first")
def _():
    src = (LUA / "ai-gates-scan.lua").read_text(encoding="utf-8")
    i = src.index("function scan(now_tick)")
    body = src[i:src.index("\nend", i)]
    assert "GATES_SAVE.saved ~= nil" in body and "not pending then pcall(open_lever_hatches)" in body


# --- the way out --------------------------------------------------------------------------

WAY = r"""
local src = ...
INSIDE = 1
PULLS, JOBS = {}, {}
B = {
  [7] = {id = 7, name = '', door_flags = {closed = true, forbidden = false}, jobs = {}, x1 = 5, y1 = 1, z = 2},
  [9] = {id = 9, name = '', door_flags = {closed = true, forbidden = false}, jobs = {}, x1 = 2, y1 = 1, z = 2},
}
G = {IMMINENT = 12, WIDE = 60}
G.GATES = {scanned = true, closed = {}, mine = {}, entrances = {
  {id = 1, kind = 'surface', x = 5, y = 1, z = 2, equipment = {{id = 7, kind = 'hatch'}}},
  {id = 2, kind = 'surface', x = 2, y = 1, z = 2, equipment = {{id = 9, kind = 'door'}}}}}
G.visible_dangers = function() return {} end
G.distance_to = function() return 100 end
G.lever_links = function() return {}, {} end
G.lever_targets = function() return {} end
G.entrance_gate_ids = function(e) local o = {} for _, g in ipairs(e.equipment) do o[g.id] = true end return o end
G.ai_lever_name = function(n) return tostring(n):find('^AI gate') ~= nil end
G.seal_holds = function() return {ids = {}, levers = {}} end
G.seal_has = function() return false end
G.pull = function(l) table.insert(JOBS, l) return true end
G.pull_instant = function(l) table.insert(PULLS, l) return true end
G.lever_pull_pending = function() return false end
G.bridge_occupied = function() return false end
G.lock_gate = function(b, v) local c = b.door_flags.forbidden ~= v; b.door_flags.forbidden = v; return c, true end
G.gates_persist = function() end
reqscript = function(n) if n == 'ai-gates' then return G end error('reqscript ' .. tostring(n)) end
df = {global = {world = {map = {x_count = 10, y_count = 10, z_count = 5}, reindex_pathfinding = false},
                plotinfo = {site_id = 1}, cur_year = 1, cur_year_tick = 100},
      building = {find = function(id) return B[id] end}}
dfhack = {gui = {showAnnouncement = function() end}, maps = {}}
xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-way-out', 't', env))()
env.group_at = function(x, y, z) if x == 0 or y == 0 or x == 9 or y == 9 then return 1 end return INSIDE end
env.citizen_spots = function() return {{id = 1, x = 4, y = 4, z = 2}} end
return env
"""


def way():
    L = LuaRuntime(unpack_returned_tuples=True)
    return L, L.execute(WAY, module_src("ai-way-out.lua"))


@test("way out (A5 exp1/exp2): plain doors and hatches at rest (DF's closed, unlocked) are not shut: the fort "
      "is not 'sealed by locks', nothing listed; every needed piece locked: sealed")
def _():
    if LuaRuntime is None:
        return
    L, env = way()
    r = env.report()
    assert r.open is True and not r.sealed_by_locks and r.shut_by is None, (r.sealed_by_locks, r.shut_by)
    L.execute("B[7].door_flags.forbidden = true")
    env.EDGE.report = None
    assert not env.report().sealed_by_locks            # one of two surface entrances locked: a way out
    L.execute("B[9].door_flags.forbidden = true")
    assert env.report().sealed_by_locks is True
    import planner_way_out as pw
    assert pw.sealed({"way_out": {"known": True, "open": True}}) is False


@test("way out: an entrance whose two needed pieces are not both shut is open; its gatehouse bridge raised "
      "shuts it alone")
def _():
    if LuaRuntime is None:
        return
    L, env = way()
    L.execute("""B[7].door_flags.forbidden = true
      B[10] = {id = 10, name = '', door_flags = {closed = true, forbidden = false}, jobs = {}, x1 = 6, y1 = 1, z = 2}
      B[8] = {id = 8, name = '', gate_flags = {raised = false}, jobs = {}, x1 = 5, y1 = 2, z = 2}
      B[9].door_flags.forbidden = true
      table.insert(G.GATES.entrances[1].equipment, {id = 10, kind = 'door'})
      G.GATES.entrances[1].outer = {{id = 8, kind = 'bridge'}}""")
    assert not env.report().sealed_by_locks
    L.execute("B[8].gate_flags.raised = true")
    assert env.report().sealed_by_locks is True


@test("open_way: the AI's own lock on a plain door at rest (closed and locked) is undone; the player's locked "
      "door is left")
def _():
    if LuaRuntime is None:
        return
    L, env = way()
    L.execute("B[7].door_flags.forbidden = true; G.GATES.mine[7] = true; B[9].door_flags.forbidden = true")
    r = env.open_way(1)
    assert r.ok and L.eval("B[7].door_flags.forbidden") is False and "unlocked" in r.did, r.did
    r = env.open_way(2)
    assert not r.ok and L.eval("B[9].door_flags.forbidden") is True and r.players


# --- the brain's rules --------------------------------------------------------------------

def _gate_state(now_tick):
    return {"date": {"year": 120, "tick": now_tick}, "others_on_map": {"threats_that_can_reach_dwarves": 0},
            "entrances": {"scanned": True, "entrances": [
                {"id": 1, "kind": "surface", "x": 1, "y": 2, "z": 3,
                 "split": [{"id": 9, "kind": "hatch", "x": 1, "y": 2, "z": 3}]}]},
            "way_out": {"known": True, "open": True}}


@test("unstick_gate on a split nobody is shut out by: backed off 1, 3, 7 days, then left with a note after "
      "gate_stuck_prevent_max tries (A12: daily for 60 days)")
def _():
    import planner_gates as pg
    from planner_core import PLANNER_CONFIG, Proposal, TICKS_PER_DAY

    class Mem:
        gate_unstick: dict = {}
        rescan_entrances = False
    m = Mem()
    m.gate_unstick = {}
    t = 1000
    fired = []
    for _day in range(40):
        s = _gate_state(t)
        props, notes = [], []
        pg._gate_stuck_rule(s, m, PLANNER_CONFIG, props, notes)
        if props:
            fired.append(_day)
            pg.note_gate_stuck(props[0], {"ok": True, "split_after": True}, s, m, 120 * 403200 + t)
        t += TICKS_PER_DAY
        if t >= 403200:
            break
    gaps = [b - a for a, b in zip(fired, fired[1:])]
    assert len(fired) == PLANNER_CONFIG["gate_stuck_prevent_max"], fired
    assert gaps == [1, 3, 7], gaps
    assert any("left as it is" in n for n in notes), notes
    assert isinstance(Proposal, type)


@test("kill zones: a zone still building after killzone_stage_days no longer holds the next one (said); a fresh "
      "one still does")
def _():
    import planner_killzone as pk
    from planner_core import PLANNER_CONFIG, TICKS_PER_DAY
    now = 120 * 403200 + 50000

    def state(since):
        return {"date": {"year": 120, "tick": 50000}, "dwarves": {"total": 30}, "settings": {"traits": {}},
                "others_on_map": {"threats_that_can_reach_dwarves": 0},
                "killzones": {"entrances": [
                    {"id": 1, "kind": "surface", "x": 1, "y": 1, "z": 1, "state": "building", "since": since,
                     "drawbridge": {"stage": "channel", "since": since}, "traps": {"planned": 2, "built": 0}},
                    {"id": 2, "kind": "surface", "x": 5, "y": 5, "z": 1, "state": "possible", "corridor": 4,
                     "trap_tiles": 4, "drawbridge": {"possible": False}}],
                    "mechanics": 1, "free_mechanisms": 20, "threats": []}}

    class Mem:
        crisis: dict = {}
    seen = {}
    orig = pk.zone_reasons
    pk.zone_reasons = lambda s, m, c, rows: [(10, r, ["used"]) for r in rows]
    try:
        for age_days, blocked in ((2, True), (PLANNER_CONFIG["killzone_stage_days"] + 1, False)):
            props, notes = [], []
            pk._killzone_rule(state(now - age_days * TICKS_PER_DAY), Mem(), PLANNER_CONFIG, props, notes)
            seen[age_days] = (props, notes)
            assert (props == []) == blocked, (age_days, [p.action for p in props], notes)
        props, notes = seen[PLANNER_CONFIG["killzone_stage_days"] + 1]
        assert props[0].action["entrance_id"] == 2 and any("no longer holds" in n for n in notes)
    finally:
        pk.zone_reasons = orig


finish()
