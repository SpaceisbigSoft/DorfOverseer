"""(r5 p1) The tests that failed only on the player's Windows PC, each cause
simulated here (this runs on Linux):

- os.clock on Windows is wall time in ~1 ms steps (CPU time in microseconds
  on Linux): within a short pass it often hasn't moved, so a deadline of
  "now + 0" was never passed (`>`) and a zero budget ran on. The builder's
  site search (test_builder "band pass") and the water survey's slices
  (test_r38_water "288x288x194") now stop when the deadline is reached
  (`>=`). Simulated by a clock that stands still.
- str(Path) has backslashes on Windows; the hub asks DFHack for
  lua_dir .. '/ai-bridge-orders.lua' (test_fix26_bridge "compiled once"):
  the stub's file times now read a path with either slash, as Windows does.
- %APPDATA% holds DF's user save folder (dfhack.save_roots): the restore of
  test_r33_keeper "autosave 2" went there (the player's own saves).
  tests/harness.py now runs every test without it.
- a Dwarf Fortress always runs on the player's PC: test_revive "game closed"
  asked the real process list and never launched. Its probes now answer as
  off Windows unless the test gives its own `run`.
- test_k48_shelter "slices" counted pulses that depended on the PC's speed:
  its walk now runs on a clock that moves 1 ms a read.

    python tests/test_r5_p1.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua, have_lua  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

TESTS = ROOT / "tests"
FROZEN = "local real = os.clock; os.clock = function() return 1.0 end; return real"


def run_file(name: str, env: dict | None = None, driver: str | None = None) -> subprocess.CompletedProcess:
    """A test file run on its own (as run_all does), with `env` over this
    process's, or through `driver` (Python run first, the file then run as
    __main__ in the same process)."""
    e = dict(os.environ, PYTHONIOENCODING="utf-8")
    e.pop("DFAI_TEST_SHARD", None)
    e.update(env or {})
    if driver is None:
        args = [sys.executable, str(TESTS / name)]
    else:
        code = (f"import sys, runpy; sys.path[:0] = [{str(TESTS)!r}, {str(ROOT / 'brain')!r}]; "
                f"import harness\n{driver}\nrunpy.run_path({str(TESTS / name)!r}, run_name='__main__')")
        args = [sys.executable, "-c", code]
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=e, cwd=str(ROOT), timeout=300)


# --- os.clock that hasn't moved (Windows' coarse clock) ------------------------

@test("builder: a zero time limit stops the site search though the clock hasn't moved (Windows' os.clock)")
def _():
    need_lua()
    import test_builder as TB
    TB._reset(True)
    real = TB.LUA.execute(FROZEN)
    TB.B.SEARCH_SECONDS = 0
    try:
        r = TB.planned(TB.plan(elev_lo=61, elev_hi=62))
    finally:
        TB.B.SEARCH_SECONDS = 4
        TB.LUA.globals().os.clock = real
    assert not r.ok and r.error and "time limit" in r.error, (r.ok, r.error)
    assert TB.designated_count() == 0
    # a real limit, the clock standing still: the search still finds its level
    TB._reset(True)
    real = TB.LUA.execute(FROZEN)
    try:
        r = TB.planned(TB.plan(elev_lo=61, elev_hi=62))
    finally:
        TB.LUA.globals().os.clock = real
    assert r.ok and r.in_district is True, r.error


@test("water: a zero slice is one block a call though the clock hasn't moved; it still finishes")
def _():
    need_lua()
    import test_r38_water as TW
    env = TW.world(W=64, H=64, Z=40, SURF=30)
    for y in range(64):
        env.SET(60, y, 29, TW.F(flow_size=7, outside=True), 2)
    real = TW.LUA.execute(FROZEN)
    try:
        r, times = TW.run_slices(env, 0)
    finally:
        TW.LUA.globals().os.clock = real
    assert len(times) > 4 * 4 * 20, len(times)          # (the map's 4x4 blocks, ~30 levels, a block a call)
    assert [b for b in TW.waters(r) if b.flow == "flowing"]


# --- path separators -----------------------------------------------------------

@test("hub stub: a part's file time keyed by its Windows spelling (backslashes) is the one the hub asks for")
def _():
    need_lua()
    import test_fix26_bridge as TF
    M = TF.fresh()
    TF.H.count_compiles(M)
    TF.H.rerun(M)
    assert dict(TF.H.compiled) == {}, dict(TF.H.compiled)
    win = str(PureWindowsPath(TF.LUA_DIR / "ai-bridge-orders.lua"))      # what str(Path) gives on Windows
    assert "\\" in win
    TF.H.mtimes[win] = 2
    TF.H.rerun(M)
    assert dict(TF.H.compiled) == {"ai-bridge-orders": 1}, dict(TF.H.compiled)
    TF.H.rerun(M)
    assert dict(TF.H.compiled) == {"ai-bridge-orders": 1}, dict(TF.H.compiled)


# --- the player's %APPDATA% ----------------------------------------------------

@test("APPDATA: with a user save folder there (as on Windows), test_r33_keeper passes and writes nothing into it")
def _():
    with tempfile.TemporaryDirectory() as tmp:
        user = Path(tmp) / "Bay 12 Games" / "Dwarf Fortress" / "save"
        user.mkdir(parents=True)
        p = run_file("test_r33_keeper.py", env={"APPDATA": tmp})
        assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]
        left = sorted(str(x.relative_to(tmp)) for x in Path(tmp).rglob("*"))
        assert left == [str(Path("Bay 12 Games")), str(Path("Bay 12 Games/Dwarf Fortress")),
                        str(Path("Bay 12 Games/Dwarf Fortress/save"))], left


@test("APPDATA: a test runs without it (the harness drops it)")
def _():
    p = run_file("harness.py", env={"APPDATA": "C:/Users/x/AppData/Roaming"},
                 driver="import os; print('APPDATA' in os.environ); sys.exit(0)")
    assert p.returncode == 0 and p.stdout.strip() == "False", (p.stdout, p.stderr[-2000:])


# --- a Dwarf Fortress running on the PC ----------------------------------------

@test("revive: with a Dwarf Fortress running on the PC (tasklist sees one), test_revive still passes")
def _():
    drv = ("import revive\n"
           "revive.df_running = lambda *a, **k: True      # the player's games\n"
           "revive.any_df_running = lambda *a, **k: True\n"
           "revive.own_game_state = lambda *a, **k: None  # its own .exe unknown (a steam:// link)")
    p = run_file("test_revive.py", driver=drv)
    assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]
    assert "11 passed, 0 failed" in p.stdout or " passed, 0 failed" in p.stdout, p.stdout[-500:]


# --- the shelter walk's pulses, whatever the PC's speed ------------------------

@test("shelter: test_k48_shelter passes on a PC so fast (or a clock so coarse) that os.clock never moves")
def _():
    need_lua()
    drv = ("import lupa.lua53 as L\n"
           "_Real = L.LuaRuntime\n"
           "def Frozen(*a, **k):\n"
           "    lua = _Real(*a, **k)\n"
           "    lua.execute('os.clock = function() return 1.0 end')\n"
           "    return lua\n"
           "L.LuaRuntime = Frozen")
    p = run_file("test_k48_shelter.py", driver=drv)
    assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]


if __name__ == "__main__":
    finish(None if have_lua() else "needs lupa")
