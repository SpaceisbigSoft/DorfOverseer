"""(F5a) The dead-man pause in the game (lua/ai-status.lua).

  1. no check-in for DEADMAN_S real seconds: the game paused once, one line
     said; a player who unpauses is not fought until a fresh check-in goes
     stale again;
  2. never before the first check-in, while halted, while the keeper holds it
     (its planned close), or when DEADMAN_S is 0; a check-in ends a hold;
  3. the watcher's loop: armed by a check-in, re-armed by its own beat, and a
     reloaded file takes the loop over (ai-fights' token + CODE);
  4. the status reply carries deadman (in pcall: old fakes have no deadman_state);
     the keeper holds it before its quicksave.

    python tests/test_f5_deadman.py
"""

from __future__ import annotations

import sys
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

LUA_DIR = ROOT / "lua"

# the world: a real clock the test sets (NOW), DF's pause, the timers kept to run by hand
WORLD = r"""
local src = ...
local save = {}
NOW = 1000000
SAID, ANN, TIMERS = {}, {}, {}
NEXT_ID = 0
_G.SC_MAP_UNLOADED = 99
_G.df = {global = {cur_year = 10, cur_year_tick = 1000, pause_state = false}}
_G.dfhack = {isMapLoaded = function() return true end, onStateChange = {},
  persistent = {getSiteData = function(k, d) return save[k] or d end,
                saveSiteData = function(k, v) save[k] = v end},
  gui = {showAnnouncement = function(m) table.insert(ANN, m) end},
  timeout = function(n, unit, fn)
    NEXT_ID = NEXT_ID + 1
    TIMERS[NEXT_ID] = {n = n, unit = unit, fn = fn}
    return NEXT_ID
  end,
  timeout_active = function(id) return TIMERS[id] ~= nil end}
_G.COLOR_LIGHTRED, _G.COLOR_LIGHTGREEN = 12, 10
_G.print = function(m) table.insert(SAID, m) end
os.time = function() return NOW end
_G.reqscript = function(n) error(n) end
function RUN_TIMERS()               -- every pending timer fires once (as DF would)
  local due = TIMERS
  TIMERS = {}
  local n = 0
  for _, t in pairs(due) do t.fn(); n = n + 1 end
  return n
end
function LOAD(s)
  local env = setmetatable({}, {__index = _G})
  assert(load(s, 'ai-status', 't', env))()
  return env
end
return LOAD(src)
"""


def world():
    L = LuaRuntime(unpack_returned_tuples=True)
    M = L.execute(WORLD, module_src("ai-status.lua"))
    return L, M


def ev(L, s):
    return L.eval(s)


if LuaRuntime:
    @test("dead-man: no check-in for DEADMAN_S real seconds: paused once, one line said; unpaused by the player: "
          "left alone until a fresh check-in goes stale")
    def _():
        L, M = world()
        assert int(M.DEADMAN_S) == 600
        M.mark_seen()
        L.execute("NOW = NOW + 599")
        assert M.deadman_check() is None and ev(L, "df.global.pause_state") is False
        L.execute("NOW = NOW + 61")                           # 11 min
        assert M.deadman_check() == "paused"
        assert ev(L, "df.global.pause_state") is True
        said = [ev(L, "SAID[1]"), ev(L, "ANN[1]")]
        assert said == ["AI Overseer: no check-in for 11 min, game paused"] * 2, said
        assert ev(L, "#SAID") == 1
        # the player unpauses: not paused again for the same stale check-in
        L.execute("df.global.pause_state = false; NOW = NOW + 3600")
        assert M.deadman_check() is None and ev(L, "df.global.pause_state") is False
        st = M.deadman_state()
        assert st.paused_at == 1000000 + 660 and st.paused_ago_s == 3600
        # a fresh check-in (its gap kept for the reply), then stale again: paused again
        M.mark_seen()
        assert M.deadman_state().last_checkin_age_s == 660 + 3600
        L.execute("NOW = NOW + 601")
        assert M.deadman_check() == "paused" and ev(L, "#SAID") == 2

    @test("dead-man: already paused when stale: nothing said, the period counted as done")
    def _():
        L, M = world()
        M.mark_seen()
        L.execute("df.global.pause_state = true; NOW = NOW + 700")
        assert M.deadman_check() is None and ev(L, "#SAID") == 0
        L.execute("df.global.pause_state = false")
        assert M.deadman_check() is None, "the player's unpause is not fought"
        assert M.deadman_state().found_paused_at == 1000700

    @test("dead-man: never before the first check-in, never halted, never held (a check-in ends the hold), "
          "never with DEADMAN_S 0; the status may set DEADMAN_S")
    def _():
        L, M = world()
        L.execute("NOW = NOW + 100000")
        assert M.deadman_check() is None and ev(L, "df.global.pause_state") is False    # never checked in
        M.mark_seen()
        L.execute("NOW = NOW + 700")
        L.execute("dfhack.persistent.saveSiteData('ai-overseer/halt', {halted = true})")
        assert M.deadman_check() is None and ev(L, "df.global.pause_state") is False
        L.execute("dfhack.persistent.saveSiteData('ai-overseer/halt', {halted = false})")
        # the keeper's planned close
        L2, M2 = world()
        M2.mark_seen()
        assert M2.deadman_hold(1200) is True
        L2.execute("NOW = NOW + 1100")
        assert M2.deadman_check() is None and M2.deadman_state().held_s == 100
        L2.execute("NOW = NOW + 101")
        assert M2.deadman_check() == "paused"                       # the hold over, the game still up
        M2.deadman_hold(10 ** 9)
        assert M2.deadman_state().held_s == int(M2.DEADMAN_HOLD_MAX_S)
        M2.mark_seen()
        assert M2.deadman_state().held_s is None, "the overseer back: the hold ends"
        # off
        L3, M3 = world()
        M3.set_status(L3.eval("{deadman_s = 0}"))
        assert int(M3.DEADMAN_S) == 0
        M3.mark_seen()
        L3.execute("NOW = NOW + 100000")
        assert M3.deadman_check() is None and M3.deadman_state().armed is False
        M3.set_status(L3.eval("{deadman_s = 5}"))                 # out of range: kept
        assert int(M3.DEADMAN_S) == 0
        M3.set_status(L3.eval("{deadman_s = 900}"))
        assert int(M3.DEADMAN_S) == 900

    @test("dead-man watcher: armed by a check-in (one timer, in ticks), re-armed by its beat, which pauses; "
          "a reloaded file takes the loop over and the old beat ends")
    def _():
        L, M = world()
        M.DEADMAN_LOOK_TICKS = 37                               # apart from the away watcher's timer
        assert M.deadman_state().armed is False
        M.mark_seen()
        dm = [t for t in ev(L, "TIMERS").values() if t.n == 37]
        assert len(dm) == 1 and dm[0].unit == "ticks"
        assert M.deadman_state().armed is True
        n_before = len(list(ev(L, "TIMERS").values()))
        M.mark_seen()                                           # live: not armed twice
        assert len(list(ev(L, "TIMERS").values())) == n_before
        L.execute("NOW = NOW + 601")
        L.execute("RUN_TIMERS()")
        assert ev(L, "df.global.pause_state") is True and ev(L, "#SAID") == 1
        assert M.deadman_state().armed is True, "the beat armed itself again"
        # a reload: the new load's start takes over; the old beat, when it fires, ends there
        old_token = M.deadman().token
        M2 = L.execute("return LOAD(...)", module_src("ai-status.lua"))
        M2.LAST_SEEN = M.LAST_SEEN
        M2.DEADMAN_LOOK_TICKS = 37
        assert M2.deadman_start() is True
        assert M2.deadman().token != old_token
        L.execute("RUN_TIMERS()")
        live = [t for t in ev(L, "TIMERS").values() if t.n == 37]
        assert len(live) == 1, "one loop after a reload, not two"

    @test("dead-man: the map unloaded: the check-in, the hold and the done period forgotten")
    def _():
        L, M = world()
        M.mark_seen()
        M.deadman_hold(600)
        L.execute("dfhack.onStateChange['ai-status'](SC_MAP_UNLOADED)")
        assert M.LAST_SEEN is None and M.deadman_state().held_s is None
        L.execute("NOW = NOW + 100000")
        assert M.deadman_check() is None

    @test("dead-man fails open in old fakes: no dfhack.timeout, no pause_state")
    def _():
        L = LuaRuntime(unpack_returned_tuples=True)
        M = L.execute(r"""
          local src = ...
          _G.SC_MAP_UNLOADED = 99
          _G.df = {global = {cur_year = 10, cur_year_tick = 1000}}
          _G.dfhack = {isMapLoaded = function() return true end, onStateChange = {},
            persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end},
            gui = {showAnnouncement = function() end}}
          _G.reqscript = function(n) error(n) end
          local env = setmetatable({}, {__index = _G})
          assert(load(src, 'ai-status', 't', env))()
          return env""", module_src("ai-status.lua"))
        M.mark_seen()
        assert M.deadman_start() is False
        assert M.deadman_state().armed is False


@test("status reply: deadman read in pcall (old ai-status fakes have no deadman_state)")
def _():
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    i = src.index("local function cmd_status()")
    body = src[i:src.index("\nend\n", i)]
    assert "deadman = (function()" in body and "pcall(function() return st.deadman_state() end)" in body


@test("keeper: the dead-man pause held before the fresh start's quicksave, for the save wait and the close")
def _():
    import fresh_start
    import keeper
    src = (ROOT / "brain" / "keeper.py").read_text(encoding="utf-8")
    i = src.index("def do_fresh_start(")
    body = src[i:src.index("\ndef ", i + 1)]
    assert body.index("DEADMAN_HOLD_LUA") < body.index('run("quicksave")')
    lua = keeper.DEADMAN_HOLD_LUA.format(s=fresh_start.SAVE_WAIT_S + 300)
    assert lua.startswith("pcall(") and "deadman_hold(1200)" in lua


if __name__ == "__main__":
    finish()
