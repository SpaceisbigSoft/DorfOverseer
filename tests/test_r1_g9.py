"""(r1g9) The keeper and the run's bookkeeping (round 1, group 9).

  * a fallen fort (0 citizens, no migrants on the way) is seen once: said,
    marked (fallen.json) with its last report kept, nothing proposed, and the
    overseer's loop and the keeper leave the game alone (R-F 3, R-B 10);
  * the keeper doesn't start or reload the game while Windows ends the
    session (R-AD 12, section 6);
  * the run id and the fort's identity survive DF's rotating autosave
    folders, in Python (fort key, run id) and in Lua (the water survey first)
    (R-F 12, A1 1 and 42, A4 B2, A5 B1);
  * the run check counts game time once (A1 bug 7).

Built from the run's data: fort F (Hammerstirred, world Usnuspbuzong, site
1430, fell 18 Slate y256, `autosave 1`).

    python tests/test_r1_g9.py
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp())
os.environ["DFAI_LOG_DIR"] = str(TMP / "logs")
from harness import test, finish, need_lua  # noqa: E402
from py_parts import py_family_src  # noqa: E402  (r7) overseer.py and its parts
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))

import fallen  # noqa: E402
import health_check as hc  # noqa: E402
import ledger  # noqa: E402
import memstore  # noqa: E402
import overseer  # noqa: E402
import revive  # noqa: E402
import session_end  # noqa: E402
from dfhack import GameNotRunning  # noqa: E402

LOGS = TMP / "logs"
LOGS.mkdir(parents=True, exist_ok=True)
memstore.FORTS_DIR = TMP / "forts"
fallen.LOG_DIR = LOGS

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
# fort F's own identity and its last date (run2/F/state-last.json)
F_FORT = {"name": "Hammerstirred", "save_dir": "autosave 1", "site_id": 1430, "world": "Usnuspbuzong"}
F_DATE = {"day": 18, "month": "Slate", "season": "spring", "tick": 55000, "year": 256}
BOOKKEEPING = {"report_status", "ledger_set", "save_memory", "set_learned", "set_culture", "mark_run", "batch"}


def f_state(save_dir="autosave 1", tick=55000, citizens=None, ledger_v=None, queued=0):
    s = copy.deepcopy(BASE)
    s["fort"] = dict(F_FORT, save_dir=save_dir)
    s["date"] = dict(F_DATE, tick=tick)
    if citizens is not None:
        s["dwarves"]["total"] = citizens
    s["migration"] = {"civ": True, "force": "force", "hermit_tool": False, "queued": queued}
    s["ledger"] = dict(ledger_v if ledger_v is not None else {"fort_run": ""})
    return s


class FakeBridge:
    """The game for one_cycle: a report, the ledger it holds (ledger_set
    writes it), every action recorded."""
    version = {"recipes": [], "tools": []}

    def __init__(self, state):
        self.st, self.acted = state, []
        self.led = dict(state.get("ledger") or {})

    def status(self):
        return {"ok": True, "in_fort": True, "halted": False, "decisions": {}}

    def state(self, include_units=True, tier=None):
        s = copy.deepcopy(self.st)
        s["ledger"] = dict(self.led)
        return s

    def events(self):
        return []

    def act(self, a):
        self.acted.append(a)
        if a.get("type") == "ledger_set":
            self.led = dict(a["values"])
        return {"ok": True}

    def load_memory(self):
        return {}


def run_cycles(bridge, states, autopilot=True):
    said = []
    saved = overseer.say
    overseer.say = said.append
    try:
        for s in states:
            bridge.st = s
            overseer.one_cycle(bridge, autopilot=autopilot)
    finally:
        overseer.say = saved
    return said


def reset():
    overseer.MEMORY_CACHE.clear()
    overseer.PRINTED.clear()
    memstore.ALIASES.clear()
    fallen.STATE.update(mark=None, dismissed=None)
    for p in [fallen.mark_path()]:
        p.unlink(missing_ok=True)


# ------------------------------------------------------------------ the run id

@test("run id: made once and written into the save's ledger (the save's empty one no longer wipes it)")
def _():
    from planner_core import Memory
    m = Memory()
    m.fort_run = "202611151916-a7a4"          # F's first id, 19:16:15
    ledger.apply(m, {"fort_run": "", "ai_alert_raised": True})
    assert m.fort_run == "202611151916-a7a4" and m.ai_alert_raised is True, m.fort_run
    ledger.apply(m, {"fort_run": "202611151800-beef"})
    assert m.fort_run == "202611151800-beef"   # a save's own id still wins


@test("run id: across F's autosaves (1 -> 2 -> 3) one id, said once, kept in the save; the memory read once")
def _():
    reset()
    b = FakeBridge(f_state())
    said = run_cycles(b, [f_state("autosave 1", 55000, citizens=12), f_state("autosave 2", 55000 + 3 * 1200, citizens=12),
                          f_state("autosave 3", 55000 + 6 * 1200, citizens=12)])
    made = [x for x in said if x.startswith("Run: this fort's save holds no run id")]
    assert len(made) == 1, made
    run = b.led.get("fort_run")
    assert isinstance(run, str) and run in made[0], (run, made)
    keys = {overseer.fort_key(f_state(d)) for d in ("autosave 1", "autosave 2", "autosave 3", "region4")}
    assert keys == {"Usnuspbuzong#1430"}, keys
    assert not [x for x in said if x.startswith("Ledger: the alert")][1:], "the save's memory was read again"


@test("fort key: the logs folder is still the save folder's (an autosave goes to the fort's own folder)")
def _():
    reset()
    memstore.note_world("region4#1430", "Usnuspbuzong")            # the embark was loaded first (old-style key)
    (memstore.FORTS_DIR / "region4-1430").mkdir(parents=True, exist_ok=True)
    for d in ("region4", "autosave 1", "autosave 2"):
        key = overseer.fort_key({"fort": dict(F_FORT, save_dir=d)})
        assert memstore.note_world(key, "Usnuspbuzong", save_dir=d) == "region4-1430", d
        assert memstore.fort_dir(key).name == "region4-1430"
    # a test copy keeps its own folder, as before
    key = overseer.fort_key({"fort": dict(F_FORT, save_dir="AI Run X")})
    assert memstore.note_world(key, "Usnuspbuzong", save_dir="AI Run X") == "AI_Run_X-1430"
    # without a world name: the save folder, as before
    assert overseer.fort_key({"fort": {"save_dir": "region4", "site_id": 1430}}) == "region4#1430"
    memstore.ALIASES.clear()


# ------------------------------------------------------------------ the run check's game time

def dec(fort, year, tick, time_s):
    return {"kind": "decision", "mode": "autopilot", "rule": "water", "fort": fort,
            "action": {"type": "survey_water"}, "result": {"ok": True},
            "date": {"year": year, "tick": tick}, "time": f"2026-11-15T{time_s}"}


@test("run check: one game year over rotating autosave folders is one year (it read about three)")
def _():
    es, n = [], 0
    season = 403200 // 4
    for i in range(5 * 4):                                   # five years, a season per autosave folder
        folder = f"autosave {i % 3 + 1}#1430"
        for d in range(0, season, 2400):
            n += 1
            es.append(dec(folder, 250 + i // 4, (i % 4) * season + d, f"{18 + n // 3600:02d}:{n // 60 % 60:02d}:{n % 60:02d}"))
    lines = hc.journal_flags(es)[1]
    years = float(next(x for x in lines if x.startswith("game time")).split(": ")[1].split()[0])
    assert 4.8 <= years <= 5.1, lines


@test("run check: F's real stretch played twice (a reload of autosave 2) counts once")
def _():
    es = [dec("region4#1430", 250, t, f"18:{t // 2400:02d}:00") for t in range(0, 48000, 2400)]
    es += [dec("autosave 2#1430", 250, t, f"19:{t // 2400:02d}:00") for t in range(24000, 72000, 2400)]   # replayed
    pts = [(e["time"], e["date"]["year"] * 403200 + e["date"]["tick"]) for e in es]
    assert hc._covered(pts) == 69600, hc._covered(pts)          # 0 .. 69600, the replayed part once


# ------------------------------------------------------------------ the fallen fort

@test("fallen: F's last report (0 citizens, no wave queued) is said once, marked, its report kept, nothing done")
def _():
    reset()
    b = FakeBridge(f_state(citizens=0))
    said = run_cycles(b, [f_state(citizens=0), f_state(citizens=0, tick=55000 + 1200),
                          f_state(citizens=0, tick=55000 + 2400)])
    fell = [x for x in said if x.startswith("THE FORT HAS FALLEN")]
    assert len(fell) == 1, said[-8:]
    mark = fallen.current()
    assert mark and mark["fort"] == "Usnuspbuzong#1430" and mark["tick"] == 256 * 403200 + 55000, mark
    folder = Path(mark["folder"])
    assert (folder / "fallen.json").exists()
    ev = json.loads(Path(mark["evidence"]).read_text(encoding="utf-8"))
    assert ev["dwarves"]["total"] == 0 and ev["fort"]["world"] == "Usnuspbuzong", ev["fort"]
    other = sorted({a.get("type") for a in b.acted} - BOOKKEEPING)
    assert not other, other
    j = [json.loads(x) for x in (folder / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert not [e for e in j if e.get("kind") == "decision"], [e.get("rule") for e in j if e.get("kind") == "decision"]
    assert [e["event"] for e in j if e.get("kind") == "fallen"] == ["fallen"]


@test("fallen: citizens again (migrants, another save) end it: said, the mark taken off, the AI acts again")
def _():
    b = FakeBridge(f_state(citizens=0))
    said = run_cycles(b, [f_state(citizens=7, tick=55000 + 3600)])
    assert any("the fort's fall is over (7 citizen(s)" in x for x in said), said[-6:]
    assert fallen.current() is None and not fallen.mark_path().exists()
    reset()


@test("fallen: not while a migrant wave is queued, nor when the citizen count couldn't be read")
def _():
    reset()
    assert fallen.falls(f_state(citizens=0, queued=1)) is None
    s = f_state()
    s["dwarves"] = {"error": "get_dwarves failed"}
    assert fallen.falls(s) is None
    assert fallen.falls(f_state(citizens=0)) == "no citizens left and no migrant wave on its way"
    b = FakeBridge(s)
    run_cycles(b, [s])
    assert fallen.current() is None


@test("fallen: the player deleting logs/fallen.json lets the AI act on the fort again (not marked again)")
def _():
    reset()
    b = FakeBridge(f_state(citizens=0))
    run_cycles(b, [f_state(citizens=0)])
    assert fallen.current()
    fallen.mark_path().unlink()
    said = run_cycles(b, [f_state(citizens=0, tick=56200), f_state(citizens=0, tick=57400)])
    assert any("logs/fallen.json was removed" in x for x in said), said[-5:]
    assert fallen.current() is None and not [x for x in said if x.startswith("THE FORT HAS FALLEN")]
    reset()


@test("fallen: the overseer's loop neither unpauses nor unsticks a fallen fort")
def _():
    src = py_family_src("overseer")
    loop = src[src.index("def main() -> int:"):]
    assert "fallen_idle = bool(args.autopilot and fallen.idle(st, fallen_probe(bridge), say, journal))" in loop   # (x3, V7) the loaded fort checked
    stall = loop.index("elif stalled and fallen_idle:")
    assert stall < loop.index('r = bridge.act({"type": "unpause", "unstick": True})'), "the unstick comes first"
    unp = loop[:loop.index('r = bridge.act({"type": "unpause"})')]
    assert "and not fallen_idle):" in unp[-400:], unp[-400:]


class FakeDF:
    def __init__(self, state="down"):
        self.state, self.calls = state, []

    def run(self, *args):
        self.calls.append(args)
        if self.state == "down":
            raise GameNotRunning("no")
        if args[0] == "lua":
            return "WORLD-LOADED SITE=1430" if self.state == "world" else "NO-WORLD SITE="
        return '{"ok": true, "started": true}'


def reviver(state="down"):
    t = [1000.0]
    logs, launched = [], []
    df = FakeDF(state)
    rv = revive.Reviver(logs.append, dfhack=df, launcher=launched.append, clock=lambda: t[0])
    rv.candidates = lambda: (["autosave 1"], None)
    rv.df_running = lambda: False
    rv.any_df = lambda: None
    rv.session_ending = lambda: None
    rv.own_folder = lambda: None
    return rv, t, df, logs, launched


@test("keeper: a fallen fort is never relaunched or reloaded; once the mark is off, it is")
def _():
    reset()
    revive.launch_command = lambda: "D:/DF-F/Dwarf Fortress.exe"
    fallen.mark_path().write_text(json.dumps({"fort": "Usnuspbuzong#1430", "why": "no citizens left"}))
    rv, t, df, logs, launched = reviver("down")
    rv.seen_up = True
    for _ in range(30):
        rv.tick(); t[0] += 60
    assert not launched and sum("has fallen" in x for x in logs) == 1, logs
    df.state = "title"
    for _ in range(10):
        rv.tick(); t[0] += 60
    assert not [c for c in df.calls if c[0] == "ai-title"], df.calls
    fallen.mark_path().unlink()
    for _ in range(4):
        rv.tick(); t[0] += 60
    assert ("ai-title", "load", "autosave 1") in df.calls, df.calls


@test("keeper: Windows ending the session (F 10:44:20, C 10:42:48): no relaunch, no reload")
def _():
    reset()
    revive.launch_command = lambda: "D:/DF-F/Dwarf Fortress.exe"
    rv, t, df, logs, launched = reviver("down")
    rv.seen_up = True
    rv.session_ending = lambda: "Windows is shutting down, restarting or logging off"
    for _ in range(10):
        rv.tick(); t[0] += 60
    assert not launched and any("shutting down" in x for x in logs), logs
    df.state = "title"
    for _ in range(5):
        rv.tick(); t[0] += 60
    assert not [c for c in df.calls if c[0] == "ai-title"], df.calls
    # Windows' own word, and the console's close signal
    assert session_end.windows_ending(metrics=lambda i: 1 if i == session_end.SM_SHUTTINGDOWN else 0)
    assert not session_end.windows_ending(metrics=lambda i: 0)
    got = []
    assert not session_end.handle(0, got.append)            # Ctrl-C: Python's KeyboardInterrupt as before
    assert session_end.ending(metrics=lambda i: 0) is None
    assert session_end.handle(6, got.append) and got == ["Windows shutting down"]
    assert "close signal" in (session_end.ending(metrics=lambda i: 0) or "")
    session_end.SIGNAL.update(at=None, kind=None)


@test("keeper: every Dwarf Fortress on the PC closed together: no relaunch within the hold, then as before")
def _():
    reset()
    revive.launch_command = lambda: "D:/DF-F/Dwarf Fortress.exe"
    rv, t, df, logs, launched = reviver("world")
    rv.tick(); t[0] += 60                                    # up: seen
    df.state = "down"
    rv.any_df = lambda: False                                # A..E's games are gone too
    hold = session_end.all_closed_hold_s()
    for _ in range(int(hold // 60) - 1):
        rv.tick(); t[0] += 60
    assert not launched, logs
    assert sum("no Dwarf Fortress is left running" in x for x in logs) == 1, logs
    for _ in range(3):
        rv.tick(); t[0] += 60
    assert launched == ["D:/DF-F/Dwarf Fortress.exe"], logs
    # one game of six crashed (the others still run): as before, no hold
    rv, t, df, logs, launched = reviver("world")
    rv.tick(); t[0] += 60
    df.state = "down"
    rv.any_df = lambda: True
    for _ in range(5):
        rv.tick(); t[0] += 60
    assert launched, logs


@test("keeper: the console's close handler logs the end and writes the status")
def _():
    import keeper
    keeper.LOG_DIR, keeper.LOG, keeper.STATUS = LOGS, LOGS / "unattended.log", LOGS / "unattended-status.txt"
    calls = []
    real = session_end.install
    session_end.install = lambda cb: calls.append(cb) or True
    try:
        assert keeper.close_handler("2026-11-15 18:02:07")
    finally:
        session_end.install = real
    calls[0]("Windows shutting down")
    assert "the console is closing" in keeper.LOG.read_text(encoding="utf-8")
    assert "Windows shutting down" in keeper.STATUS.read_text(encoding="utf-8")


# ------------------------------------------------------------------ Lua: the fort's id

WATER_FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local F = {site = 1430, save = 'autosave 1', world = 'Usnuspbuzong', put = {}, handlers = {}}
env.F = F
env.SC_MAP_UNLOADED = 5
-- a clock that moves a step at each look: one block a slice whatever the PC's clock resolution
local now = 0
env.os = setmetatable({clock = function() now = now + 1; return now end}, {__index = os})
env.reqscript = function() return {site_put = function(k, v) F.put[k] = v end, site_get = function() return nil end} end
env.dfhack = {onStateChange = F.handlers,
              units = {getCitizens = function() return {{}} end, getPosition = function() return 50, 50, 100 end},
              maps = {getTileSize = function() return 200, 200, 200 end, getBlock = function() return nil end}}
env.df = setmetatable({}, {__index = function(_, k)
  if k == 'global' then
    return {plotinfo = {site_id = F.site},
            world = {cur_savegame = {save_dir = F.save}, world_data = {name = {first_name = F.world}}}}
  end
end})
assert(load(src, 'ai-water', 't', env))()
return env
"""


@test("ai-water (A1 1, A4 B2): a half-done whole-map survey goes on across F's autosave 1 -> 2 -> 3")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    from lua_modules_util import module_src
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(WATER_FAKE, module_src("ai-water.lua"))
    F = env.F
    for _ in range(300):                                     # one block a call: a few levels of the near box
        r = env.scan_step(1, 0)
    assert r.ok and r.done is False, r
    env.JOB.marker = "begun under autosave 1"
    z, bi = env.JOB.z, env.JOB.bi
    for save in ("autosave 2", "autosave 3"):
        F.save = save
        r = env.scan_step(1, 0)
        assert r.ok and env.JOB.marker == "begun under autosave 1", (save, r.ok)
        assert env.JOB.z < z or (env.JOB.z == z and env.JOB.bi > bi), (save, z, bi, env.JOB.z, env.JOB.bi)
        z, bi = env.JOB.z, env.JOB.bi                        # carried on, not begun again
    assert env.JOB.fort == "Usnuspbuzong#1430", env.JOB.fort
    F.world = "Another World"                                 # another world's fort of that site id: begun afresh
    env.scan_step(2, 0)
    assert env.JOB.marker is None and env.JOB.fort == "Another World#1430"


@test("ai-util fort_id: world and site, the same over autosave folders; every module keys on it")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    util = (ROOT / "lua" / "ai-util.lua").read_text(encoding="utf-8")
    env = lua.execute(r"""
      local src = ...
      local env = setmetatable({}, {__index = _G})
      env.G = {plotinfo = {site_id = 1430},
               world = {cur_savegame = {save_dir = 'autosave 1'}, world_data = {name = {first_name = 'x'}}}}
      env.df = {global = env.G}
      env.dfhack = {translation = {translateName = function(n) return 'Usnuspbuzong' end}}
      assert(load(src, 'ai-util', 't', env))()
      return env
    """, util)
    a = env.fort_id()
    env.G.world.cur_savegame.save_dir = "autosave 2"
    assert a == env.fort_id() == "Usnuspbuzong#1430", (a, env.fort_id())
    # no module keys its state on the save folder any more (only as a fallback without ai-util)
    import re
    for name in ("ai-water", "ai-cleanup", "ai-captives", "ai-threats", "ai-threat-facts", "ai-paper",
                 "ai-bridge-orders", "ai-bridge-report", "ai-mission-send", "ai-bridge"):
        from lua_modules_util import bridge_part_src   # (r6) a split bridge part: its files together
        src = bridge_part_src(name)
        uses = [m.start() for m in re.finditer(r"cur_savegame\.save_dir", src)]
        for at in uses:
            before = src[max(0, at - 700):at]
            fine = ("fort_id()" in before or "world_name()" in before
                    or "save_dir = df.global.world.cur_savegame.save_dir" in src[at - 30:at + 30])
            assert fine, (name, src[at - 200:at + 40])


if __name__ == "__main__":
    finish()
