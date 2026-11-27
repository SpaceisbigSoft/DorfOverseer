"""(0.105.100) The keeper's planned restart, "a fresh start" (brain/fresh_start.py):
the timer from the game's load, the stagger by port, calm and not calm, the
max wait, the PC-wide turn, the save-written wait, the close, the keeper
starting itself again, and its reopening not counted as a crash.

    python tests/test_r106_fresh_start.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import make_test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

TMP = Path(tempfile.mkdtemp())
LOGS = TMP / "logs"
os.environ["DFAI_LOG_DIR"] = str(LOGS)

import dfhack  # noqa: E402
dfhack.CONFIG_PATH = TMP / "config.json"
import pin  # noqa: E402
import revive  # noqa: E402
import fresh_start as fs  # noqa: E402
import keeper  # noqa: E402
import soak_report  # noqa: E402
from dfhack import GameNotRunning  # noqa: E402

pin.PIN_FILE = LOGS / "keeper-pin.json"
pin.LAST_FORT = LOGS / "last-fort.json"
revive.LAST_FORT = pin.LAST_FORT
fs.PC_DIR = TMP / "pc" / "fresh-starts"
# never the PC's own processes (tests/test_revive.py's way)
revive.own_game_state = lambda *a, **k: None
revive.any_df_running = lambda *a, **k: None
revive.df_running = lambda *a, **k: False

H = 3600.0


def _reset():
    LOGS.mkdir(parents=True, exist_ok=True)
    for p in [fs.calm_file(), fs.mark_file(), pin.PIN_FILE]:
        p.unlink(missing_ok=True)
    if fs.PC_DIR.exists():
        for f in fs.PC_DIR.glob("*"):
            f.unlink()
    fs._LIVE.clear()
    fs._WRITTEN.update(at=float("-inf"), text="")
    dfhack.CONFIG_PATH.write_text(json.dumps({"dfhack_port": 5000}), encoding="utf-8")


test = make_test(before=_reset)


class RV:
    """A reviver as far as the fresh start reads it."""
    def __init__(self, world_since=None):
        self.world_since = world_since
        self.loading = self.wrong_load = None
        self.title_since = self.down_since = None
        self.planned, self.planned_since = False, None
        self.df = DF()

    def tick(self):
        pass

    def _dfhack(self):
        return self.df

    def probe(self):
        return "down"


class DF:
    def __init__(self):
        self.calls = []

    def run(self, *args):
        self.calls.append(args)
        return "The game should autosave now."


def _calm(now, why=(), threat=False, **status):
    st = {"in_fort": True, "paused": False, "saving": False}
    st.update(status)
    fs.note_status(st, halted=bool(status.get("halted")), season_end=bool(status.get("season_end")), now=now)
    fs._LIVE.update(cycle_at=now, why=list(why), threat=threat)
    fs._write(now, force=True)


def _lines():
    out = []
    return out, (lambda line: out.append(line))


# --- settings and the stagger -------------------------------------------------

@test("settings: fresh_start_hours 3 and max wait 2 by default, 0 is off, nonsense is the default")
def _():
    assert fs.settings({}) == (3.0, 2.0)
    assert fs.settings({"fresh_start_hours": 0}) == (0.0, 2.0)
    assert fs.settings({"fresh_start_hours": "x", "fresh_start_max_wait_hours": -1}) == (3.0, 2.0)
    assert fs.settings({"fresh_start_hours": 1.5, "fresh_start_max_wait_hours": 0.5}) == (1.5, 0.5)
    ex = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    assert ex.get("fresh_start_hours") == 3 and ex.get("fresh_start_max_wait_hours") == 2
    f = fs.FreshStart(lambda s: None, RV(0), cfg={"fresh_start_hours": 0})
    assert not f.on() and f.check(10 * H) is None


@test("stagger: ports 5000-5005 are 0, 30, 60 ... 150 minutes apart at 3 h; an unknown port none")
def _():
    assert [fs.stagger_s(5000 + i, 3) / 60 for i in range(6)] == [0, 30, 60, 90, 120, 150]
    assert fs.stagger_s(None, 3) == 0 and fs.stagger_s(5006, 3) == 0
    assert fs.stagger_s(5003, 6) / 60 == 180


# --- the timer ------------------------------------------------------------------

@test("timer: counted from the game's load, plus this fort's turn on the first period only")
def _():
    out, log = _lines()
    rv = RV(world_since=1000.0)
    f = fs.FreshStart(log, rv, cfg={}, port=5002, me="B")
    _calm(1000 + 3 * H + 59 * 60)
    assert f.check(1000 + 3 * H + 59 * 60) is None, "due before its turn (60 min for port 5002)"
    _calm(1000 + 3 * H + 61 * 60)
    go = f.check(1000 + 3 * H + 61 * 60)
    assert go and go["how"] == "calm" and abs(go["hours"] - (3 + 61 / 60)) < 0.01, go
    # a reload (a revive) starts a new period, without the turn
    fs.publish("B", None, None, 1000 + 3 * H + 62 * 60)     # B's own fresh start over
    rv2 = RV(world_since=0.0)
    f2 = fs.FreshStart(log, rv2, cfg={}, port=5002, me="B2")
    f2.check(10.0)
    rv2.world_since = 5000.0
    _calm(5000 + 3 * H + 10)
    assert f2.check(5000 + 3 * H + 10), "the second load waits only the period"


@test("timer: a keeper started by a fresh start has no turn offset; no load seen: nothing due")
def _():
    rv = RV(world_since=None)
    f = fs.FreshStart(lambda s: None, rv, cfg={}, port=5005, after_fresh=True, me="F")
    assert f.check(100 * H) is None
    rv.world_since = 0.0
    _calm(3 * H + 5)
    assert f.check(3 * H + 5)
    assert "the forts take turns" not in (f.first_line() or "")
    g = fs.FreshStart(lambda s: None, RV(0.0), cfg={}, port=5005, me="F2")
    assert "150 min later" in g.first_line(), g.first_line()


@test("timer: the reviver loading, or a wrong fort up: not now")
def _():
    rv = RV(world_since=0.0)
    rv.loading = ("region1", 1.0)
    f = fs.FreshStart(lambda s: None, rv, cfg={}, port=5000, me="A")
    _calm(4 * H)
    assert f.check(4 * H) is None


# --- calm ---------------------------------------------------------------------------

@test("calm: a threat in reach, invaders, the alarm, the AI's gates, tantrums and berserks each keep it waiting")
def _():
    assert fs.calm_verdict({"others_on_map": {"threats": []}}) == ([], False)
    why, threat = fs.calm_verdict({"others_on_map": {"threats_that_can_reach_dwarves": 2}})
    assert threat and "2 threat(s) can reach the dwarves" in why
    why, threat = fs.calm_verdict({"others_on_map": {"threats": [{"id": 1, "invader": True,
                                                                  "can_reach_dwarves": False}]}})
    assert threat and any("invader" in w for w in why)
    why, threat = fs.calm_verdict({"others_on_map": {}, "civ_alert": True})
    assert not threat and why == ["the civilian alarm is up"]
    why, _t = fs.calm_verdict({"others_on_map": {}, "entrances": {"armed": True, "entrances": [{"closed": True}]}})
    assert why == ["the AI's gates are shut"], why
    why, _t = fs.calm_verdict({"others_on_map": {}, "tantrums": {"loose": 1}})
    assert why == ["1 tantrum(s) loose"]
    why, _t = fs.calm_verdict({"others_on_map": {}, "hazards": {"berserk": [{"id": 4}]}})
    assert why == ["a berserk dwarf loose"]
    # wildlife out of reach: calm
    assert fs.calm_verdict({"others_on_map": {"threats": [{"id": 9, "can_reach_dwarves": False}]}}) == ([], False)


@test("calm: the overseer's word (logs/calm.json): paused, halted, saving, a season's end hold; an old word is unknown")
def _():
    now = 50_000.0
    fs.note_status({"in_fort": True}, now=now)
    fs.note_cycle({"others_on_map": {}}, now=now)
    assert fs.read_calm(now + 10)[0] is True
    fs.note_cycle({"date": {}}, now=now + 20)        # a pulse with no threats in it: the last word stands
    assert fs.read_calm(now + 30)[0] is True
    for k in ("paused", "saving"):
        fs.note_status({"in_fort": True, k: True}, now=now + 40)
        calm, why, threat = fs.read_calm(now + 41)
        assert calm is False and threat, (k, why)
    fs.note_status({"in_fort": True}, halted=True, now=now + 50)
    assert "halted" in " ".join(fs.read_calm(now + 51)[1])
    fs.note_status({"in_fort": True}, season_end=True, now=now + 60)
    assert fs.read_calm(now + 61)[0] is False
    assert fs.read_calm(now + fs.CALM_STALE_S + 100)[0] is None
    fs.calm_file().unlink()
    assert fs.read_calm(now)[0] is None


@test("not calm: waited for, said once an hour; past the max wait it goes with no threat on the map, never with one")
def _():
    out, log = _lines()
    f = fs.FreshStart(log, RV(world_since=0.0), cfg={}, port=5000, me="A")
    t = 3 * H + 1
    _calm(t, why=["the civilian alarm is up"])
    assert f.check(t) is None
    assert f.check(t + 60) is None
    assert len([x for x in out if "waiting for a calm moment" in x]) == 1, out
    _calm(t + 2 * H - 60, why=["the civilian alarm is up"])
    assert f.check(t + 2 * H - 60) is None
    _calm(t + 2 * H + 10, why=["the civilian alarm is up"])
    go = f.check(t + 2 * H + 10)
    assert go and "no threat on the map" in go["how"], go
    g = fs.FreshStart(log, RV(world_since=0.0), cfg={}, port=5000, me="A2")
    _calm(t, why=["1 threat(s) can reach the dwarves"], threat=True)
    g.check(t)
    _calm(t + 5 * H, why=["1 threat(s) can reach the dwarves"], threat=True)
    assert g.check(t + 5 * H) is None, "a threat in reach: never, however long"
    _calm(t + 5 * H, why=[], paused=True)
    assert g.check(t + 5 * H) is None, "paused: never, even past the max wait"


# --- the PC-wide turn ---------------------------------------------------------------

@test("PC-wide: another fort's game loading holds it; a quiet keeper or one busy too long doesn't")
def _():
    now = 10 * H
    out, log = _lines()
    f = fs.FreshStart(log, RV(world_since=0.0), cfg={}, port=5000, me="DF-AI")
    _calm(now)
    fs.publish("DF-AI-C", "loading", now - 60, now - 30)
    assert f.check(now) is None
    assert any("DF-AI-C's game is loading" in x for x in out), out
    fs.publish("DF-AI-C", "loading", now - 60, now - fs.PC_ALIVE_S - 5)     # its keeper gone quiet
    fs.publish("DF-AI-D", "starting", now - fs.PC_BUSY_MAX_S - 5, now - 5)  # stuck: not waited for
    fs.publish("DF-AI-E", None, None, now - 5)
    go = f.check(now)
    assert go, out
    me = json.loads((fs.PC_DIR / "DF-AI.json").read_text(encoding="utf-8"))
    assert me["busy"] == "saving for a fresh start"
    # the others now see this one busy
    assert fs.others_busy("DF-AI-B", now + 1)[0][0] == "DF-AI"


@test("PC-wide: the keeper's own word follows its reviver (starting, title, loading) and its fresh start")
def _():
    rv = RV(world_since=None)
    f = fs.FreshStart(lambda s: None, rv, cfg={}, port=5001, me="DF-AI-B")
    rv.down_since = 100.0
    f.publish_state(now=200.0)
    assert fs.others_busy("x", 210.0) == [("DF-AI-B", "starting", 100.0)]
    rv.down_since, rv.loading = None, ("autosave 1", 300.0)
    f.publish_state(now=310.0)
    assert fs.others_busy("x", 320.0)[0][1] == "loading"
    rv.loading = None
    f.publish_state(now=400.0)
    assert fs.others_busy("x", 410.0) == []


# --- the save, the close ------------------------------------------------------------

class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


@test("save wait: only a save newer than the request, and unchanged for 30 s; none in 15 min: None")
def _():
    clock = Clock(1000.0)
    folder = TMP / "s1"
    folder.mkdir(exist_ok=True)
    state = {"stamp": 900.0}

    def newest():
        return "region1", state["stamp"], folder

    import backup
    real = backup.folder_mtime
    backup.folder_mtime = lambda p: state["stamp"]
    try:
        assert fs.wait_saved(1000.0, clock=clock, sleep=clock.sleep, newest=newest, wait_s=120) is None
        clock.t = 2000.0

        def sleep(s):
            clock.sleep(s)
            if clock.t < 2020:
                state["stamp"] = clock.t           # DF still writing it
        state["stamp"] = 1990.0
        got = fs.wait_saved(2000.0, clock=clock, sleep=sleep, newest=newest)
        # the last write at 2015: still for 30 s from then
        assert got == "region1" and 2045 <= clock.t <= 2055, (got, clock.t)
    finally:
        backup.folder_mtime = real


@test("save wait: the save the reviver loads first is the one just written (load_candidates, newest first)")
def _():
    df = TMP / "DF"
    for name, age in (("region1", 0), ("autosave 1", 600)):
        d = df / "save" / name
        d.mkdir(parents=True, exist_ok=True)
        w = d / "world.sav"
        w.write_bytes(b"x" * 2048)
        t = time.time() - age
        os.utime(w, (t, t))
    pin.LAST_FORT.write_text(json.dumps({"df_path": str(df), "save_dir": "region1", "fort": "k"}),
                             encoding="utf-8")
    name, stamp, folder = fs.newest_save()
    assert name == "region1" and folder.name == "region1", (name, folder)
    names, _w = revive.load_candidates()
    assert names == ["region1", "autosave 1"], names


@test("close: by the pid only (an echo from kill_command is no close); waited until the game is gone")
def _():
    out, log = _lines()
    assert fs.close_game(RV(), log, kill=lambda: ["cmd", "/c", "echo", "no game of this folder found"]) is False
    assert "couldn't be closed" in out[-1]
    ran, clock = [], Clock(0.0)
    looks = iter([False, False, True])
    ok = fs.close_game(RV(), log, clock=clock, sleep=clock.sleep, kill=lambda: ["taskkill", "/F", "/PID", "42"],
                       run=lambda cmd, **k: ran.append(cmd) or type("R", (), {"stdout": "SUCCESS", "stderr": ""})(),
                       gone=lambda: next(looks))
    assert ok and ran == [["taskkill", "/F", "/PID", "42"]] and "closed" in out[-1], out
    clock = Clock(0.0)
    assert fs.close_game(RV(), log, clock=clock, sleep=clock.sleep, kill=lambda: ["taskkill", "/F", "/PID", "42"],
                         run=lambda cmd, **k: type("R", (), {"stdout": "", "stderr": ""})(),
                         gone=lambda: False) is False


# --- the keeper ------------------------------------------------------------------------

class Proc:
    def __init__(self, code=None):
        self.code, self.killed = code, False
        self.stdout = iter([])

    def poll(self):
        return self.code if self.code is not None else (-9 if self.killed else None)

    def kill(self):
        self.killed = True


def _keeper_reset(rv):
    for k in ("fresh", "reviver", "pinned", "start_ts", "last_check", "last_summary", "check_copy",
              "fresh_error_said"):
        keeper.EXTRAS.pop(k, None)
    revive.Reviver = lambda log, *a, **k: rv


REAL_REVIVER = revive.Reviver


@test("keeper: due and calm: the overseer stopped, quicksave, the save waited for, closed, marked, started again")
def _():
    rv = RV(world_since=time.time() - 2 * H)
    _keeper_reset(rv)
    dfhack.CONFIG_PATH.write_text(json.dumps({"dfhack_port": 5000, "fresh_start_hours": 1}), encoding="utf-8")
    _calm(time.time())
    procs, spawned, closed = [], [], []
    keeper.FRESH_HOOKS.update(wait_saved=lambda asked: "region1",
                              close=lambda r, log: closed.append(r) or True,
                              respawn=lambda argv: spawned.append(argv) or True)
    keeper.LOG.unlink(missing_ok=True)
    try:
        code = keeper.main(["--revive", "--preset", "War-hold"],
                           popen=lambda *a, **k: procs.append(Proc()) or procs[-1], sleep=lambda s: None, max_runs=3)
    finally:
        revive.Reviver = REAL_REVIVER
        keeper.FRESH_HOOKS.update(wait_saved=None, close=None, respawn=None)
    text = keeper.LOG.read_text(encoding="utf-8")
    assert code == 0, text
    assert len(procs) == 1 and procs[0].killed, "the overseer stopped first"
    # (F5a) the game's dead-man pause held first, then the save
    assert rv.df.calls == [("lua", keeper.DEADMAN_HOLD_LUA.format(s=fs.SAVE_WAIT_S + 300)), ("quicksave",)], \
        rv.df.calls
    assert closed == [rv] and spawned == [["--revive", "--preset", "War-hold"]]
    assert "Fresh start: 2.0 h since the game loaded, calm: saving, closing and reopening." in text, text
    assert "Restarting the overseer" not in text, "a planned close is no overseer restart"
    mark = json.loads(fs.mark_file().read_text(encoding="utf-8"))
    assert mark["phase"] == "closed" and mark["folder"] == "region1" and mark["run_start"]
    assert "restarting itself for a fresh start" in (LOGS / "unattended-status.txt").read_text(encoding="utf-8")


@test("keeper: the save never written: put off an hour, the overseer started again at once (no back-off)")
def _():
    rv = RV(world_since=time.time() - 2 * H)
    _keeper_reset(rv)
    dfhack.CONFIG_PATH.write_text(json.dumps({"dfhack_port": 5000, "fresh_start_hours": 1}), encoding="utf-8")
    _calm(time.time())
    procs, waits = [], []
    keeper.FRESH_HOOKS.update(wait_saved=lambda asked: None, close=lambda r, log: 1 / 0,
                              respawn=lambda argv: 1 / 0)
    keeper.LOG.unlink(missing_ok=True)
    try:
        keeper.main(["--revive"], popen=lambda *a, **k: procs.append(Proc(code=0 if procs else None)) or procs[-1],
                    sleep=waits.append, max_runs=2)
    finally:
        revive.Reviver = REAL_REVIVER
        keeper.FRESH_HOOKS.update(wait_saved=None, close=None, respawn=None)
    text = keeper.LOG.read_text(encoding="utf-8")
    assert "Fresh start: not done (no save was written within 15 min)" in text, text
    assert len(procs) == 2 and procs[0].killed and waits == [30], (len(procs), waits)
    assert not fs.mark_file().exists()
    assert keeper.EXTRAS["fresh"].retry_at > time.time() + 3000


@test("keeper: started by a fresh start: the pin kept, the run's start carried, planned until the fort is up")
def _():
    rv = RV(world_since=None)
    _keeper_reset(rv)
    pin.PIN_FILE.write_text(json.dumps({"world": "W", "site": "7"}), encoding="utf-8")
    fs.write_mark({"phase": "closed", "closed_at": time.time() - 20, "folder": "region1",
                   "run_start": "2026-11-24T00:00:00", "last_check": 123.0})
    keeper.LOG.unlink(missing_ok=True)
    try:
        keeper.main(["--revive"], popen=lambda *a, **k: Proc(code=0), sleep=lambda s: None, max_runs=1)
    finally:
        revive.Reviver = REAL_REVIVER
    text = keeper.LOG.read_text(encoding="utf-8")
    assert "this keeper started again after the planned close" in text, text
    assert pin.current() == {"world": "W", "site": "7"}, "the pin is kept"
    assert keeper.EXTRAS["run_start"].isoformat().startswith("2026-11-24T00:00")
    assert keeper.EXTRAS["last_check"] == 123.0
    assert rv.planned and keeper.EXTRAS["fresh"].offset == 0
    rv.world_since = time.time()
    keeper.planned_done(rv)
    assert not rv.planned
    assert json.loads(fs.mark_file().read_text(encoding="utf-8"))["phase"] == "done"
    assert "Fresh start: done: the fort is loaded again" in keeper.LOG.read_text(encoding="utf-8")
    assert fs.read_mark() is None, "a done mark starts no planned reopening"


# --- the reviver ----------------------------------------------------------------------

class GameDF:
    def __init__(self):
        self.state = "down"

    def run(self, *args):
        if self.state == "down":
            raise GameNotRunning("no")
        if args[0] == "lua":
            return ("WORLD-LOADED SITE=12 DFPATH=" if self.state == "world" else "NO-WORLD SITE= DFPATH=")
        return '{"ok": true}'


@test("reviver: world_since from the fort's load (None while down or at the title); a planned reopening says so")
def _():
    out, log = _lines()
    clock = Clock(1000.0)
    df = GameDF()
    launched = []
    r = REAL_REVIVER(log, dfhack=df, launcher=launched.append, clock=clock)
    r.own_folder = lambda: None
    r.df_running = lambda: False
    r.session_ending = lambda: None
    r.planned, r.planned_since = True, 1000.0
    dfhack.CONFIG_PATH.write_text(json.dumps({"df_launch": "steam://rungameid/975370"}), encoding="utf-8")
    r.tick()
    clock.t = 1020.0
    r.tick()
    assert launched and out[-1].startswith("Revive (planned): Dwarf Fortress wasn't running"), out
    assert r.world_since is None
    df.state = "world"
    clock.t = 1100.0
    r.tick()
    assert r.world_since == 1100.0
    clock.t = 1200.0
    r.tick()
    assert r.world_since == 1100.0
    df.state = "title"
    clock.t = 1300.0
    r.tick()
    assert r.world_since is None
    r.planned = False
    df.state = "down"
    clock.t = 1400.0
    r.tick()
    clock.t = 1400.0 + revive.DOWN_S + revive.LAUNCH_EVERY_S
    r.tick()
    assert out[-1].startswith("Revive: Dwarf Fortress wasn't running"), out


@test("counts: a planned close is never a revive or a crash in the run check; the fresh starts are counted apart")
def _():
    import health_check
    lines = ["[t] Fresh start: 3.0 h since the game loaded, calm: saving, closing and reopening.",
             "[t] Revive (planned): Dwarf Fortress wasn't running for 15 s: started it again (x).",
             "[t] Revive (planned): the game sat at the title screen; loading the save 'region1'."]
    flags, plain = health_check.log_flags(lines)
    assert flags == [], flags
    assert "revive: DF started again" not in plain[0] and "revive: save loaded" not in plain[0], plain
    assert "fresh starts (planned: saved, closed and reopened) 1" in plain[0], plain
    assert "planned reopenings (not crashes) 1" in plain[0], plain
    flags, plain = health_check.log_flags(["[t] Revive: Dwarf Fortress wasn't running for 200 s: started it again"])
    assert "revive: DF started again 1" in plain[0]


@test("overseer wiring: the loop notes the status, the cycle the calm (unattended only)")
def _():
    loop = (ROOT / "brain" / "overseer_loop.py").read_text(encoding="utf-8")
    cyc = (ROOT / "brain" / "overseer_cycle.py").read_text(encoding="utf-8")
    assert "fresh_start.note_status(st, halted=controls[\"halted\"], season_end=season_end)" in loop
    assert "fresh_start.note_cycle(state, memory, fort=key)" in cyc


# --- (0.105.100, verifier) -------------------------------------------------------------

@test("verifier: a siege named without its invaders is a threat: the max wait never closes the game in one")
def _():
    why, threat = fs.calm_verdict({"others_on_map": {"threats": []}, "military": {"siege": True}})
    assert "a siege" in why and threat is True, (why, threat)
    why, threat = fs.calm_verdict({"others_on_map": {"threats": []}, "tantrums": {"loose": 1}})
    assert why and threat is False


@test("verifier: calm.json written once a minute while nothing changes, not at every poll")
def _():
    st = {"in_fort": True, "paused": False, "saving": False}
    fs.note_status(st, now=1000.0)
    first = json.loads(fs.calm_file().read_text(encoding="utf-8"))["written"]
    fs.note_status(st, now=1010.0)
    fs.note_status(st, now=1030.0)
    assert json.loads(fs.calm_file().read_text(encoding="utf-8"))["written"] == first == 1000.0
    fs.note_status(st, now=1061.0)
    assert json.loads(fs.calm_file().read_text(encoding="utf-8"))["status_at"] == 1061.0
    fs.note_status({**st, "paused": True}, now=1062.0)
    assert json.loads(fs.calm_file().read_text(encoding="utf-8"))["paused"] is True, "a change at once"


@test("verifier: two keepers deciding together: the older word goes, the newer steps back (not both)")
def _():
    now = 50 * H
    _calm(now)
    # B said "saving" a moment after A would: A (older) still goes
    a = fs.FreshStart(lambda s: None, RV(world_since=now - 10 * H), cfg={}, port=5000, me="A")
    real = fs.others_busy
    fs.others_busy = lambda me, t: [] if not getattr(fs, "_seen", False) else real(me, t)
    try:
        fs._seen = False
        orig_publish = fs.publish

        def publish(me, busy, since, t):
            orig_publish(me, busy, since, t)
            if me == "A" and busy:
                orig_publish("B", "saving for a fresh start", t + 0.5, t + 0.5)
                fs._seen = True
        fs.publish = publish
        assert a.check(now) is not None, "A's word is the older"
        # and the other way round: B's word older than A's: A steps back
        _reset(); _calm(now)
        fs._seen = False

        def publish2(me, busy, since, t):
            orig_publish(me, busy, since, t)
            if me == "A" and busy:
                orig_publish("B", "saving for a fresh start", t - 0.5, t)
                fs._seen = True
        fs.publish = publish2
        a2 = fs.FreshStart(lambda s: None, RV(world_since=now - 10 * H), cfg={}, port=5000, me="A")
        assert a2.check(now) is None
    finally:
        fs.publish = orig_publish
        fs.others_busy = real
        fs._seen = False


@test("verifier: a game retrying its load at the title keeps its first 'since': past 45 min no one waits for it")
def _():
    rv = RV(world_since=None)
    f = fs.FreshStart(lambda s: None, rv, cfg={}, port=5001, me="B")
    rv.title_since = 1000.0
    f.publish_state(1000.0)
    rv.title_since = 1500.0                       # the reviver's next load try resets its own clock
    f.publish_state(1000.0 + fs.PC_WRITE_EVERY_S + 1)
    d = json.loads((fs.PC_DIR / "B.json").read_text(encoding="utf-8"))
    assert d["since"] == 1000.0, d
    assert fs.others_busy("A", 1000.0 + fs.PC_BUSY_MAX_S + 100) == [] or \
        fs.others_busy("A", 1000.0 + fs.PC_WRITE_EVERY_S + 2)[0][2] == 1000.0
    rv.title_since = None
    f.publish_state(3000.0)
    rv.loading = ("region1", 3100.0)
    f.publish_state(3200.0)
    assert json.loads((fs.PC_DIR / "B.json").read_text(encoding="utf-8"))["since"] == 3100.0, "a new stretch"


@test("verifier: the save wait gives up at once when its beat says the game went down")
def _():
    clock = Clock(0.0)
    beats = []
    got = fs.wait_saved(0.0, clock=clock, sleep=clock.sleep, newest=lambda: (None, None, None),
                        beat=lambda: beats.append(1) is not None)   # False on the first beat
    assert got is None and len(beats) == 1 and clock.t < 10, (got, beats, clock.t)


def _due_keeper(rv):
    _keeper_reset(rv)
    dfhack.CONFIG_PATH.write_text(json.dumps({"dfhack_port": 5000, "fresh_start_hours": 1}), encoding="utf-8")
    _calm(time.time())
    keeper.LOG.unlink(missing_ok=True)


@test("verifier: S pressed while the game closed for a fresh start: no new keeper, stopped, the mark kept")
def _():
    rv = RV(world_since=time.time() - 2 * H)
    _due_keeper(rv)
    spawned = []

    def close(r, log):
        keeper.STOP_FILE.write_text("stop", encoding="ascii")
        return True
    keeper.FRESH_HOOKS.update(wait_saved=lambda asked: "region1", close=close,
                              respawn=lambda argv: spawned.append(argv) or True)
    try:
        code = keeper.main(["--revive"], popen=lambda *a, **k: Proc(), sleep=lambda s: None, max_runs=3)
    finally:
        revive.Reviver = REAL_REVIVER
        keeper.FRESH_HOOKS.update(wait_saved=None, close=None, respawn=None)
    text = keeper.LOG.read_text(encoding="utf-8")
    assert code == 0 and spawned == [] and not keeper.STOP_FILE.exists(), text
    assert "during a fresh start" in text and "R in the keepers' window" in text, text
    assert "Keeper stopped" in (LOGS / "unattended-status.txt").read_text(encoding="utf-8")
    assert fs.read_mark() is not None, "the next keeper (R) still knows the close was planned"


class Child:
    def __init__(self, code):
        self.code = code

    def poll(self):
        return self.code


@test("verifier: the new keeper failing at start (exit 2): this one takes the lock back and reopens the game")
def _():
    rv = RV(world_since=time.time() - 2 * H)
    _due_keeper(rv)
    procs = []
    keeper.FRESH_HOOKS.update(wait_saved=lambda asked: "region1", close=lambda r, log: True,
                              respawn=lambda argv: Child(2))
    try:
        code = keeper.main(["--revive"], popen=lambda *a, **k: procs.append(Proc(code=0 if procs else None))
                           or procs[-1], sleep=lambda s: None, max_runs=2)
    finally:
        revive.Reviver = REAL_REVIVER
        keeper.FRESH_HOOKS.update(wait_saved=None, close=None, respawn=None)
    text = keeper.LOG.read_text(encoding="utf-8")
    assert "the new keeper ended at start (exit code 2" in text, text
    assert len(procs) == 2, "the overseer started again by this keeper"
    assert rv.planned and rv.world_since is None and keeper.EXTRAS["fresh"].busy is None


@test("verifier: the new keeper stopping at once (exit 0, asked to stop): this one ends too")
def _():
    rv = RV(world_since=time.time() - 2 * H)
    _due_keeper(rv)
    procs = []
    keeper.FRESH_HOOKS.update(wait_saved=lambda asked: "region1", close=lambda r, log: True,
                              respawn=lambda argv: Child(0))
    try:
        code = keeper.main(["--revive"], popen=lambda *a, **k: procs.append(Proc()) or procs[-1],
                           sleep=lambda s: None, max_runs=3)
    finally:
        revive.Reviver = REAL_REVIVER
        keeper.FRESH_HOOKS.update(wait_saved=None, close=None, respawn=None)
    assert code == 0 and len(procs) == 1, keeper.LOG.read_text(encoding="utf-8")


@test("verifier: handover: 'taken' once the lock is held elsewhere, the exit code if the child ended first")
def _():
    from util import folder_lock
    clock = Clock(0.0)
    held = folder_lock(LOGS)
    try:
        assert keeper.handover(Child(None), clock=clock, sleep=clock.sleep) == "taken"
    finally:
        keeper.release_lock(held)
    assert keeper.handover(Child(1), clock=clock, sleep=clock.sleep) == 1
    clock = Clock(0.0)
    assert keeper.handover(Child(None), clock=clock, sleep=clock.sleep, wait_s=5) == "slow"
    mine = folder_lock(LOGS)
    assert mine is not None, "the probe never keeps the lock"
    keeper.release_lock(mine)


@test("verifier: the new keeper finds the lock still held: tried again, and runs once it is let go")
def _():
    from util import folder_lock
    rv = RV(world_since=None)
    _keeper_reset(rv)
    fs.write_mark({"phase": "closed", "closed_at": time.time() - 5, "folder": "region1"})
    held = [folder_lock(LOGS)]
    tries = []

    def sleep(s):
        tries.append(s)
        if len(tries) == 3 and held[0] is not None:
            keeper.release_lock(held[0])
            held[0] = None
    keeper.LOG.unlink(missing_ok=True)
    try:
        code = keeper.main(["--revive"], popen=lambda *a, **k: Proc(code=0), sleep=sleep, max_runs=1)
    finally:
        revive.Reviver = REAL_REVIVER
        keeper.release_lock(held[0])
    text = keeper.LOG.read_text(encoding="utf-8")
    assert code == 0 and "not starting a second one" not in text and "started again after the planned close" in text, text


@test("verifier: S written while the old keeper handed over: the new keeper honours it (not an old ask)")
def _():
    rv = RV(world_since=None)
    _keeper_reset(rv)
    fs.write_mark({"phase": "closed", "closed_at": time.time() - 5, "folder": "region1"})
    keeper.STOP_FILE.write_text("stop", encoding="ascii")
    procs = []
    keeper.LOG.unlink(missing_ok=True)
    try:
        code = keeper.main(["--revive"], popen=lambda *a, **k: procs.append(Proc()) or procs[-1],
                           sleep=lambda s: None, max_runs=1)
    finally:
        revive.Reviver = REAL_REVIVER
    assert code == 0 and procs == [] and not keeper.STOP_FILE.exists(), keeper.LOG.read_text(encoding="utf-8")
    # without a mark, an old stop file is still only an old ask
    fs.mark_file().unlink()
    keeper.STOP_FILE.write_text("stop", encoding="ascii")
    try:
        keeper.main(["--revive"], popen=lambda *a, **k: procs.append(Proc(code=0)) or procs[-1],
                    sleep=lambda s: None, max_runs=1)
    finally:
        revive.Reviver = REAL_REVIVER
    assert len(procs) == 1


if __name__ == "__main__":
    finish()
