"""(0.105.33, gates) The gate watcher's fixes (lua/ai-gates.lua), review slice L1.

- a drawbridge the armed watcher reopens is not pulled back up once the
  dwarf has lowered it (nor a gatehouse's hatch shut while its outer bridge
  comes down); danger while it opens closes it again;
- a rescan carries the closed entrances (and the clear-look counts) by the
  gates' building ids, not the entrance's first tile;
- a restore puts the saved closed entrances in place before the watcher's
  first look (a saved-shut lever hatch stays shut), and brings back the
  danger peak (unknown in an old save: the lockdown is kept);
- an unlinked "AI gate" lever makes an entrance "closing" only when it can
  work it (inside, away from the gate), and for LEVER_WAIT_DAYS at most;
  place_gate_lever refuses only for such a lever;
- a door or hatch on a lever shared with another gate is reported lock_only;
- fortify and place_traps read the citizens through fort_starts; the scan's
  cut survey doesn't filter its starts again;
- dead code gone (dangers, GATE_CLEAR_RADIUS); open_saved_gates pulls by pull().

    python tests/test_r33_gates.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from lua_modules_util import module_src  # noqa: E402
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

SRC = module_src("ai-gates.lua")


def load():
    L = LuaRuntime(unpack_returned_tuples=True)
    M = L.execute(r"""
local src = ...
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-gates', 't', env))()
return env""", SRC)
    return L, M


# a watcher world: buildings B, commands RUN, the year tick TICK
WATCH = r"""
local M = ...
B = {}; RUN = {}; TICK = 0; INSTANT = {}
M.df = {building = {find = function(id) return B[id] end}, job_type = {PullLever = 9},
        global = {world = {units = {active = {}}}}}
setmetatable(M.df.global, {__index = function(_, k) if k == 'cur_year_tick' then return TICK end end})
M.dfhack = {units = {getCitizens = function() return {} end, isDead = function() return false end},
            timeout = function() return nil end, timeout_active = function() return false end,
            gui = {showAnnouncement = function() end},
            run_command_silent = function(...) table.insert(RUN, table.concat({...}, ' ')); return '', 0 end}
M.CR_OK = 0
DANGERS = {}
M.visible_dangers = function() return DANGERS end
M.seal_holds = function() return {ids = {}, levers = {}} end
M.note_split_after_open = function() end
M.citizens_outside = function() return 0 end
M.pull_instant = function(lid)
  table.insert(INSTANT, lid)
  for _, b in pairs(B) do if b.drive == lid then b.door_flags.closed = not b.door_flags.closed end end
  return true
end
"""


def bridge_world(L, M, gatehouse=False):
    L.execute(WATCH, M)
    if gatehouse:
        L.execute(r"""
local M = ...
B[7] = {door_flags = {closed = true, forbidden = false}, jobs = {}, drive = 90}
B[40] = {gate_flags = {raised = true}, jobs = {}, x1 = 10, y1 = 3, x2 = 10, y2 = 3, z = 0}
M.GATES = {scanned = true, armed = true, closed = {[1] = true}, peak = 0, clear_looks = {},
  entrances = {{id = 1, kind = 'surface', x = 10, y = 3, z = 0, inside_list = {}, outs = {[(0*4096+4)*4096+10] = true},
                equipment = {{id = 7, kind = 'hatch', lever_driven = true, drive_lever = 90, drive_ai = true, levers = {}}},
                outer = {{id = 40, kind = 'bridge', lever_id = 91}}}}}
""", M)
    else:
        L.execute(r"""
local M = ...
B[40] = {gate_flags = {raised = true}, jobs = {}, x1 = 10, y1 = 3, x2 = 10, y2 = 3, z = 0}
M.GATES = {scanned = true, armed = true, closed = {[1] = true}, peak = 0, clear_looks = {},
  entrances = {{id = 1, kind = 'surface', x = 10, y = 3, z = 0, inside_list = {}, outs = {[(0*4096+4)*4096+10] = true},
                equipment = {{id = 40, kind = 'bridge', lever_id = 91}}}}}
""", M)
    # the lever: a pull leaves a job at it until the dwarf works it
    L.execute(r"""
local M = ...
B[91] = {jobs = {}}
local run = M.dfhack.run_command_silent
M.dfhack.run_command_silent = function(...)
  run(...)
  table.insert(B[91].jobs, {job_type = 9})
  return '', 0
end
""", M)


def look(L, M, n=1):
    for _ in range(n):
        L.execute("TICK = TICK + 100")
        M.GATES_ORIG.check()


def pulls(L):
    return list(L.eval("RUN").values())


def dwarf_pulls(L):
    """The dwarf works the lever: the job is gone, the bridge toggles."""
    L.execute("B[91].jobs = {}; B[40].gate_flags.raised = not B[40].gate_flags.raised")


@test("r33 gates 1: a reopened drawbridge is not pulled back up once the dwarf lowers it")
def _():
    L, M = load()
    bridge_world(L, M)
    look(L, M, 6)
    assert pulls(L) == ["lever pull --id 91"], pulls(L)
    assert M.GATES.opening[1] is True
    look(L, M, 2)                          # the dwarf hasn't come yet: no second pull
    assert pulls(L) == ["lever pull --id 91"], pulls(L)
    dwarf_pulls(L)
    assert not L.eval("B[40].gate_flags.raised")
    look(L, M, 10)
    assert pulls(L) == ["lever pull --id 91"], pulls(L)
    assert M.GATES.closed[1] is None and M.GATES.opening[1] is None


@test("r33 gates 2: a gatehouse's hatch isn't pulled shut while its outer bridge comes down")
def _():
    L, M = load()
    bridge_world(L, M, gatehouse=True)
    look(L, M, 6)
    assert list(L.eval("INSTANT").values()) == [90]           # the hatch opened at once
    assert L.eval("B[7].door_flags.closed") is False
    assert pulls(L) == ["lever pull --id 91"], pulls(L)       # the outer bridge: a dwarf's pull
    look(L, M, 3)
    assert list(L.eval("INSTANT").values()) == [90], "hatch pulled back shut while opening"
    dwarf_pulls(L)
    look(L, M, 8)
    assert pulls(L) == ["lever pull --id 91"], pulls(L)
    assert M.GATES.closed[1] is None and L.eval("B[7].door_flags.closed") is False


@test("r33 gates 3: danger while a gate opens closes it again (the lost-close re-pull works again)")
def _():
    L, M = load()
    bridge_world(L, M)
    look(L, M, 6)
    dwarf_pulls(L)                          # down
    L.execute("DANGERS = {{pos = {x = 11, y = 3, z = 0}, invader = true}}")
    look(L, M)
    assert M.GATES.closed[1] is True and not M.GATES.opening[1]
    assert pulls(L) == ["lever pull --id 91", "lever pull --id 91"], pulls(L)


@test("r33 gates 4: a bridge still moving isn't pulled again by an opening")
def _():
    L, M = load()
    bridge_world(L, M)
    L.execute("B[40].gate_flags.raised = true; B[40].gate_flags.lowering = true")
    M.GATES.closed[1] = True
    M.GATES.opening = L.table_from({1: True})
    look(L, M, 3)
    assert pulls(L) == [], pulls(L)
    assert M.GATES.closed[1] is True


MAP = r"""
local M = ...
MAP = {[0] = {
 [0]="##############################",
 [1]="##############################",
 [2]="oooo#####.....................",
 [3]="oooo..........................",
 [4]="oooo..........................",
 [5]="oooo..........................",
 [6]="oooo#####.....................",
 [7]="##############################"}}
function M.tile(x, y, z)
  local lvl = MAP[z]; if not lvl then return nil end
  local row = lvl[y]; if not row then return nil end
  local ch = row:sub(x + 1, x + 1)
  if ch == '' then return nil end
  if ch == '#' then return {walk = false, shape = 'WALL'} end
  return {walk = true, shape = 'FLOOR', outside = ch == 'o', material='STONE', depth=0}
end
M.map_size = function() return 30, 8, 1 end
M.deep_road_keys = function() return {} end
M.was_cut = function() return false end
M.cut_survey = function() end
M.gate_buildings = function() return {
  {id = 1, kind = 'door', x1 = 4, y1 = 3, x2 = 4, y2 = 3, z = 0, levers = {}},
  {id = 2, kind = 'door', x1 = 4, y1 = 4, x2 = 4, y2 = 4, z = 0, levers = {}},
  {id = 3, kind = 'door', x1 = 4, y1 = 5, x2 = 4, y2 = 5, z = 0, levers = {}}} end
M.df = {building = {find = function() return nil end}}
M.dfhack = {units = {getCitizens = function() return {} end}}
M.summary = function() return {} end
M.open_lever_hatches = function() return 0 end
"""


def rescan(L, M, sx, sy):
    L.execute(f"local M = ...; M.fort_starts = function() return {{{{x={sx}, y={sy}, z=0}}}} end", M)
    M.scan(0)
    e = M.GATES.entrances[1]
    return e.x, e.y


@test("r33 gates 5: a rescan keeps a closed entrance closed when its first tile moves")
def _():
    L, M = load()
    L.execute(MAP, M)
    assert rescan(L, M, 20, 3) == (4, 3)
    M.GATES.closed[1] = True
    M.GATES.clear_looks[1] = 4
    assert rescan(L, M, 5, 5) == (4, 4)        # the spot moved
    assert M.GATES.closed[1] is True
    assert M.GATES.clear_looks[1] == 4


@test("r33 gates 6: carry_ids by gate ids (outer too), by the spot only when no gate is left")
def _():
    L, M = load()
    old = L.eval("""{
      {id = 1, x = 1, y = 1, z = 0, equipment = {{id = 10}}},
      {id = 2, x = 5, y = 5, z = 0, equipment = {{id = 20}}, outer = {{id = 21}}},
      {id = 3, x = 9, y = 9, z = 0, equipment = {{id = 30}}}}""")
    new = L.eval("""{
      {id = 1, x = 5, y = 6, z = 0, equipment = {}, outer = {{id = 21}}},
      {id = 2, x = 1, y = 2, z = 0, equipment = {{id = 10}}},
      {id = 3, x = 9, y = 9, z = 0, equipment = {{id = 31}}}}""")
    m = M.carry_ids(old, new)
    assert (m[1], m[2], m[3]) == (2, 1, 3), (m[1], m[2], m[3])


RESTORE = r"""
local M = ...
B = {}; PULLS = {}
M.df = {building = {find = function(id) return B[id] end}, job_type = {PullLever = 9},
        global = {world = {units = {active = {}}}, cur_year_tick = 0}}
M.dfhack = {units = {getCitizens = function() return {} end, isDead = function() return false end},
            timeout = function() return nil end, timeout_active = function() return false end,
            gui = {showAnnouncement = function() end}}
M.visible_dangers = function() return {} end
M.seal_holds = function() return {ids = {}, levers = {}} end
M.note_split_after_open = function() end
M.pull_instant = function(lid) table.insert(PULLS, lid); B[7].door_flags.closed = not B[7].door_flags.closed; return true end
B[7] = {door_flags = {closed = true, forbidden = false}, jobs = {}}
M.GATES = {scanned = true, closed = {},
  entrances = {{id = 1, kind = 'surface', x = 10, y = 8, z = 0, inside_list = {}, outs = {[(1*4096+8)*4096+10] = true},
                equipment = {{id = 7, kind = 'hatch', lever_driven = true, drive_lever = 90, drive_ai = true, levers = {}}}}}}
M.GATES_SAVE = {}
"""


def restore(L, M, saved):
    L.execute(RESTORE, M)
    L.execute("local M, s = ...; M.dfhack.persistent = {getSiteData = function() return s end, "
              "saveSiteData = function() end}", M, L.eval(saved))
    M.gates_restore()


@test("r33 gates 7: a restore keeps a saved-shut lever hatch shut through the first look")
def _():
    L, M = load()
    restore(L, M, "{armed = true, gates = {{id = 7, kind = 'hatch', drive_lever = 90}}, peak = 1}")
    assert len(L.eval("PULLS")) == 0
    assert L.eval("B[7].door_flags.closed") is True
    assert M.GATES.closed[1] is True and M.GATES.armed is True
    assert M.GATES.peak == 1


@test("r33 gates 8: an old save (no peak) keeps a restored lockdown shut; the snapshot saves the peak")
def _():
    L, M = load()
    restore(L, M, "{armed = true, gates = {{id = 7, kind = 'hatch', drive_lever = 90}}}")
    assert M.GATES.peak is None
    assert M.may_reopen(100, 0, 0, M.GATES.peak) is False
    M.GATES.peak = 2
    snap = M.gates_snapshot()
    assert snap.peak == 2
    M.GATES_SAVE.restored, M.GATES_SAVE.saved = True, None
    M.GATES_SAVE.persisted = snap
    assert not M.gates_persist()           # nothing changed: nothing written
    M.GATES.peak = 3                       # a bigger danger seen: written
    assert M.gates_persist()
    assert M.GATES_SAVE.persisted.peak == 3


def wait_world(L, M, lever):
    L.execute(MAP, M)
    L.execute(r"""
local M, lever = ...
M.df = {global = {world = {buildings = {other = {TRAP = {}}}}}}
M.AI_LEVERS_WAITING = lever and {lever} or {}
M.MAX_DOORS = 0
""", M, L.table_from(lever) if lever else None)
    return L.eval("{{id = 40, kind = 'bridge', x1 = 4, y1 = 3, x2 = 4, y2 = 5, z = 0, levers = {}}}")


def starts(L):
    return L.eval("{{x = 20, y = 3, z = 0}}")


@test("r33 gates 9: an unlinked lever makes an entrance 'closing' only if it can work it")
def _():
    L, M = load()
    bs = wait_world(L, M, {"id": 5, "x": 5, "y": 3, "z": 0})          # next to the gate
    es = M.find_entrances(starts(L), bs, 1000, None)[0]
    assert not es[1].closing
    bs = wait_world(L, M, {"id": 5, "x": 25, "y": 3, "z": 0})         # away, inside
    es = M.find_entrances(starts(L), bs, 1000, None)[0]
    assert es[1].closing is True and es[1].lever_wait_since == 1000
    bs = wait_world(L, M, {"id": 5, "x": 60, "y": 3, "z": 0})         # away, not inside
    es = M.find_entrances(starts(L), bs, 1000, None)[0]
    assert not es[1].closing


@test("r33 gates 10: the drawbridge's wait for a lever ends after LEVER_WAIT_DAYS")
def _():
    L, M = load()
    bs = wait_world(L, M, {"id": 5, "x": 25, "y": 3, "z": 0})
    since = L.table_from({40: 1000})
    es = M.find_entrances(starts(L), bs, 1000 + 6 * 1200, since)[0]
    assert es[1].closing is True
    es = M.find_entrances(starts(L), bs, 1000 + 7 * 1200, since)[0]
    assert not es[1].closing and es[1].lever_wait_over == 7


@test("r33 gates 11: place_gate_lever isn't refused by an unlinked lever that can't serve it")
def _():
    src = SRC
    i = src.index("function place_gate_lever")
    body = src[i:i + 3000]
    assert "lever_waiting_for(e, GATES.inside, unlinked_ai_levers())" in body
    L, M = load()
    e = L.eval("{x = 4, y = 3, z = 0}")
    near = L.eval("{{id = 5, x = 5, y = 3, z = 0}}")
    far = L.eval("{{id = 5, x = 40, y = 3, z = 0}}")
    assert M.lever_waiting_for(e, None, near) is None
    assert M.lever_waiting_for(e, None, far) is not None


@test("r33 gates 12: a door on a lever shared with another gate is reported lock_only")
def _():
    L, M = load()
    L.execute(r"""
local M = ...
M.df = {building = {find = function() return nil end}}
M.free_levers = function() return {} end
M.intruders_inside = function() return nil end
M.GATES = {scanned = false, closed = {}, entrances = {
  {id = 1, kind = 'surface', x = 1, y = 1, z = 0, sealed = true, door_spots = {},
   equipment = {{id = 7, kind = 'door', lever_driven = true, lever_id = 90, levers = {}}}},
  {id = 2, kind = 'surface', x = 9, y = 9, z = 0, sealed = true, door_spots = {},
   equipment = {{id = 8, kind = 'door', lever_driven = true, lever_id = 91, drive_lever = 91, levers = {}}}}}}
""", M)
    r = M.GATES_ORIG.summary()
    assert r.entrances[1].lock_only is True and r.entrances[1].equipment[1].lock_only is True
    assert r.entrances[2].lock_only is None


@test("r33 gates 13: fortify and place_traps read the citizens through fort_starts")
def _():
    src = SRC
    for fn in ("function fortify(", "function place_traps("):
        i = src.index(fn)
        body = src[i:src.index("\nend\n", i)]
        assert "fort_starts(citizen_starts())" in body, fn
        assert "starts or citizen_starts()" not in body, fn
    L, M = load()
    L.execute(r"""
local M = ...
GOT = nil
M.fort_starts = function(s) return {{x = 1, y = 2, z = 0, fort = true}} end
M.trap_tiles = function(e, n, starts) GOT = starts; return {} end
M.GATES = {scanned = true, entrances = {{id = 1, equipment = {{id = 3}}}}}
M.dfhack = {units = {getCitizens = function() return {} end}}
""", M)
    M.place_traps(1, "cage", 1)
    assert L.eval("GOT[1].fort") is True


@test("r33 gates 14: the scan's cut survey doesn't run fort_starts again")
def _():
    L, M = load()
    L.execute(r"""
local M = ...
N = 0
M.fort_starts = function(s) N = N + 1; return s end
M.porch_of = function() return {capped = true} end
""", M)
    e = L.eval("{x = 1, y = 1, z = 0, inside_list = {}}")
    M.plan_cut(e, L.table(), True)
    assert L.eval("N") == 0
    M.plan_cut(e, L.table())
    assert L.eval("N") == 1
    assert "pcall(plan_cut, e, starts, true)" in SRC


@test("r33 gates 15: dead code gone; open_saved_gates pulls through pull() (a pending pull is kept)")
def _():
    L, M = load()
    assert "local function dangers()" not in SRC
    assert "GATE_CLEAR_RADIUS" not in SRC
    L.execute(WATCH, M)
    L.execute(r"""
local M = ...
B[40] = {gate_flags = {raised = true}, jobs = {}, x1 = 1, y1 = 1, x2 = 1, y2 = 1, z = 0}
B[91] = {jobs = {{job_type = 9}}}
""", M)
    opened, waiting = M.open_saved_gates(L.eval("{gates = {{id = 40, kind = 'bridge', lever_id = 91}}}"))
    assert (opened, waiting) == (0, 1) and pulls(L) == []
    L.execute("B[91].jobs = {}")
    opened, waiting = M.open_saved_gates(L.eval("{gates = {{id = 40, kind = 'bridge', lever_id = 91}}}"))
    assert opened == 1 and pulls(L) == ["lever pull --id 91"]


if __name__ == "__main__":
    sys.exit(finish())
