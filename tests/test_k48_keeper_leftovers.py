"""(0.105.48, K17) The keeper's leftovers from audit A10: a pump that gives
up, title-screen stalls not counted as bad saves, a wrong fort unloaded, no
second copy of the game, restore folders moved aside, only a timeout taken
for a hung game, the "test" name pattern, and which game answers.

    python tests/test_k48_keeper_leftovers.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

TMP = Path(tempfile.mkdtemp())
LOGS = Path(os.environ["DFAI_LOG_DIR"])
LOGS.mkdir(parents=True, exist_ok=True)

import dfhack  # noqa: E402
import health_check as hc  # noqa: E402
import keeper  # noqa: E402
import pin  # noqa: E402
import revive  # noqa: E402
import scenario  # noqa: E402
import util  # noqa: E402
from dfhack import DFHackError, GameNotRunning, NoAnswer, NotStarted  # noqa: E402

pin.PIN_FILE, pin.LAST_FORT = LOGS / "keeper-pin.json", LOGS / "last-fort.json"
revive.LAST_FORT = LOGS / "last-fort.json"
keeper.LOG_DIR, keeper.LOG = LOGS, LOGS / "unattended.log"

OWN = "D:/DF-B"
CONFIG = TMP / "config.json"


def config(**kw):
    CONFIG.write_text(json.dumps(kw))
    dfhack.CONFIG_PATH = CONFIG


config(df_launch=OWN + "/Dwarf Fortress.exe", dfhack_port=5002)


def pin_site(site="1430", save_dir="region4"):
    pin.PIN_FILE.write_text(json.dumps({"world": "W", "site": site, "save_dir": save_dir,
                                        "df_path": str(TMP / "df"), "started": 1.0}))


class TitleDF:
    """A game at the title screen: ai-title load answers ok; `status` is the
    step log the next `ai-title status` returns; `site` the fort a load brings up."""

    def __init__(self, path=OWN):
        self.state, self.calls, self.site, self.path = "title", [], 1430, path
        self.status = {"steps": [{"step": "start"}]}

    def run(self, *args):
        self.calls.append(args)
        if self.state == "down":
            raise GameNotRunning("no")
        if args[0] == "lua":
            w = "WORLD-LOADED SITE=%d" % self.site if self.state == "world" else "NO-WORLD SITE="
            return w + " DFPATH=" + self.path
        if args[1] == "status":
            return json.dumps(dict(self.status, folder=self.status.get("folder", "autosave 2")))
        return '{"ok": true, "started": true, "folder": "%s"}' % args[-1].split("|")[0]


def reviver(df, logs, t):
    rv = revive.Reviver(logs.append, dfhack=df, launcher=lambda *_: None, clock=lambda: t[0])
    rv.candidates = lambda: (["autosave 2", "autosave 1"], None)
    rv.restore = None
    rv.save_stamp = lambda f: 1.0
    rv.df_running = lambda: None
    return rv


def loads(df):
    return [c[2] for c in df.calls if c[0] == "ai-title" and c[1] != "status"]


# ------------------------------------------------------------------ #15 pump

@test("pump: a reader that keeps raising is given up (said once), not spun for ever")
def _():
    class Bad:
        def readline(self):
            raise ValueError("I/O operation on closed file")
    proc = type("P", (), {"stdout": Bad()})()
    th = threading.Thread(target=keeper.pump, args=(proc,), kwargs={"sleep": lambda s: None}, daemon=True)
    th.start()
    th.join(timeout=5)
    assert not th.is_alive(), "pump never returned"
    assert "can't be read" in keeper.LOG.read_text(encoding="utf-8")


@test("pump: a read that fails now and then is tried again and the lines still come")
def _():
    lines = iter([ValueError("x"), "one\n", ValueError("y"), ValueError("z"), "two\n", ""])

    class Flaky:
        def readline(self):
            v = next(lines)
            if isinstance(v, Exception):
                raise v
            return v
    keeper.pump(type("P", (), {"stdout": Flaky()})(), sleep=lambda s: None)
    text = keeper.LOG.read_text(encoding="utf-8")
    assert "  one" in text and "  two" in text, text[-300:]


# ------------------------------------------------------------------ #8 title-screen stalls

@test("revive: a load stopped at the title screen (the list wouldn't scroll) is retried, never a bad save")
def _():
    t, logs = [1000.0], []
    df = TitleDF()
    rv = reviver(df, logs, t)
    for _ in range(3):
        rv.tick(); t[0] += 60
    assert rv.loading and rv.loading[0] == "autosave 2", rv.loading
    df.status = {"steps": [{"step": "start"}, {"step": "worlds listed", "ok": True},
                           {"step": "stopped: the list would not scroll to the save (scroll is 0, wanted 3)"}]}
    for _ in range(40):                          # three stalls an hour, for 40 minutes
        rv.tick(); t[0] += 60
    assert rv.load_fails == {}, rv.load_fails
    assert loads(df).count("autosave 2") >= 2, loads(df)     # the same newest save tried again
    assert any("stopped at the title screen" in x and "not counted" in x for x in logs), logs


@test("revive: steps still going at the timeout are a title stall; a load that began and came back counts")
def _():
    t, logs = [1000.0], []
    df = TitleDF()
    rv = reviver(df, logs, t)
    df.status = {"steps": [{"step": "start"}, {"step": "worlds listed", "ok": True}]}
    for _ in range(3 + revive.LOAD_TIMEOUT_S // 60):
        rv.tick(); t[0] += 60
    assert rv.load_fails == {} and rv.stalls.get("autosave 2"), (rv.load_fails, rv.stalls)
    df.status = {"steps": [{"step": "start"}, {"step": "save clicked", "ok": True, "loading": True}]}
    rv.loading = None
    for _ in range(3 + revive.LOAD_TIMEOUT_S // 60):
        rv.tick(); t[0] += 60
    assert rv.load_fails.get("autosave 2") == 1, rv.load_fails
    assert revive.Reviver._title_progress.__doc__


# ------------------------------------------------------------------ #9 a wrong fort

@test("revive: a load that brings up another fort: that save is dropped, the game closed and the next save tried")
def _():
    pin_site("1430")
    t, logs, closed = [1000.0], [], []
    df = TitleDF()
    rv = reviver(df, logs, t)
    ok = [False]
    rv.close_game = lambda now, why, safe_mid_save=False: closed.append(why) or ok[0]
    for _ in range(3):
        rv.tick(); t[0] += 60
    df.state, df.site = "world", 999
    rv.tick(); t[0] += 60
    assert rv.load_fails["autosave 2"] >= revive.LOAD_FAILS_MAX, rv.load_fails
    assert closed and "another fort" in closed[0], closed
    for _ in range(120):                          # can't close it: said again each hour, not each minute
        rv.tick(); t[0] += 60
    said = [x for x in logs if "couldn't be closed yet" in x]
    assert 2 <= len(said) <= 3, said
    ok[0] = True
    rv.tick(); t[0] += 60
    assert rv.wrong_load is None
    df.state, df.site = "title", 1430              # closed, started again: the next save
    for _ in range(4):
        rv.tick(); t[0] += 60
    assert loads(df)[-1] == "autosave 1", loads(df)
    pin.clear()


@test("revive: closing its game: by its pid only, never mid-save, at most once an hour")
def _():
    logs, ran = [], []
    rv = revive.Reviver(logs.append, dfhack=TitleDF())
    saved = revive.os.name, revive.subprocess.run, revive.save_written_within, revive.kill_command
    saving = [True]
    revive.save_written_within = lambda s, clock=None: saving[0]
    revive.kill_command = lambda: ["taskkill", "/F", "/PID", "4200"]
    revive.subprocess.run = lambda cmd, **kw: ran.append(cmd) or type("R", (), {"stdout": "SUCCESS", "stderr": ""})()
    try:
        revive.os.name = "nt"
        assert not rv._close_game(5000.0, "x") and not ran              # a save is being written
        saving[0] = False
        assert rv._close_game(5060.0, "x") and ran == [["taskkill", "/F", "/PID", "4200"]]
        assert not rv._close_game(5120.0, "x") and len(ran) == 1         # not again within the hour
    finally:
        revive.os.name, revive.subprocess.run, revive.save_written_within, revive.kill_command = saved


# ------------------------------------------------------------------ #11 a second copy

@test("revive: its own game still has a process: never a second copy, after it was seen up too")
def _():
    t, logs, launched = [1000.0], [], []
    df = TitleDF()
    df.state = "world"
    rv = reviver(df, logs, t)
    rv.launcher = launched.append
    rv.close_game = lambda now, why, safe_mid_save=False: logs.append("CLOSE " + why) or False
    rv.tick(); t[0] += 60
    df.state = "down"
    rv.df_running = lambda: True
    for _ in range(20):
        rv.tick(); t[0] += 60
    assert not launched, launched
    rv.df_running = lambda: False
    for _ in range(2):
        rv.tick(); t[0] += 60
    assert launched == [OWN + "/Dwarf Fortress.exe"], launched


@test("own_game_state: True/False by its own .exe only, None when it can't tell")
def _():
    class R:
        def __init__(self, out, rc=0):
            self.stdout, self.returncode = out, rc
    others = "4100|D:\\DF-A\\Dwarf Fortress.exe\n4300|D:\\DF-C\\Dwarf Fortress.exe\n"
    exe = "D:\\DF-B\\Dwarf Fortress.exe"
    assert revive.own_game_state(exe, run=lambda *a, **k: R(others)) is False
    assert revive.own_game_state(exe, run=lambda *a, **k: R(others + "4200|d:/df-b/dwarf fortress.exe\n")) is True
    assert revive.own_game_state(exe, run=lambda *a, **k: R("", 1)) is None
    assert revive.own_game_state(exe, run=lambda *a, **k: (_ for _ in ()).throw(OSError("no"))) is None
    assert revive.own_game_state(exe, run=lambda *a, **k: R("4100|\n")) is None      # a path unread


# ------------------------------------------------------------------ #12 restore folders

@test("restore: copied whole under a temporary name; only the newest two AI restores stay, older moved aside")
def _():
    import backup
    root = TMP / "dfR" / "save"
    root.mkdir(parents=True)
    for n in ("AI restore 2026-11-01 1200", "AI restore 2026-11-05 1200", "AI restore 2026-11-09 1200"):
        (root / n).mkdir()
        (root / n / "world.sav").write_text(n)
    src = TMP / "bk" / "2026-11-14 1915"
    src.mkdir(parents=True)
    (src / "world.sav").write_text("new")
    pin.PIN_FILE.write_text(json.dumps({"world": "W", "site": "1430", "save_dir": "region4",
                                        "df_path": str(TMP / "dfR"), "started": 1.0}))
    saved = backup.copies_of, revive.save_root
    backup.copies_of = lambda *a, **k: [src]
    revive.save_root = lambda *a, **k: root
    logs = []
    try:
        name = revive.restore_from_backup(logs.append)
    finally:
        backup.copies_of, revive.save_root = saved
    assert name == "AI restore 2026-11-14 1915" and (root / name / "world.sav").read_text() == "new"
    left = sorted(d.name for d in root.iterdir())
    assert left == ["AI restore 2026-11-09 1200", "AI restore 2026-11-14 1915"], left
    aside = sorted(d.name for d in (TMP / "dfR" / revive.OLD_FOLDER).iterdir())
    assert aside == ["AI restore 2026-11-01 1200", "AI restore 2026-11-05 1200"], aside
    assert not any(n.endswith(".partial") for n in aside + left)
    pin.clear()


@test("restore: a move that is refused never raises, and nothing is deleted")
def _():
    root = TMP / "dfM" / "save"
    for n in ("AI restore 1", "AI restore 2", "AI restore 3"):
        (root / n).mkdir(parents=True)
    (TMP / "dfM" / revive.OLD_FOLDER).write_text("a file where the folder would go")
    logs = []
    assert revive.prune_restores(root, log=logs.append) == []
    assert len(list(root.iterdir())) == 3 and any("couldn't move" in x for x in logs), logs


# ------------------------------------------------------------------ #16 dfhack-run errors

@test("revive: only a timeout looks hung; dfhack-run failing (missing, bad config, nonsense) never closes the game")
def _():
    class Err:
        def __init__(self, e):
            self.e = e

        def run(self, *a):
            if isinstance(self.e, Exception):
                raise self.e
            return self.e
    rv = revive.Reviver(lambda s: None, dfhack=Err(NoAnswer("timed out")))
    assert rv.probe() == "unknown"
    for e in (DFHackError("dfhack-run exited with code 1"), NotStarted("not found"), "garbage"):
        rv.df = Err(e)
        assert rv.probe() == "broken", e
    t, logs, closed = [1000.0], [], []
    df = TitleDF()
    df.state = "world"
    rv = reviver(df, logs, t)
    rv.close_game = lambda now, why, safe_mid_save=False: closed.append(why) or True
    rv.tick(); t[0] += 60
    rv.df = Err(DFHackError("dfhack-run not found at: X"))
    for _ in range(3 * 60):
        rv.tick(); t[0] += 60
    assert not closed, closed
    assert 2 <= len([x for x in logs if "dfhack-run doesn't work" in x]) <= 4, logs


# ------------------------------------------------------------------ #21 test-save names

@test("test saves: 'Contested' and 'Greatest' are real forts; the AI Run / AI Test prefixes are tests")
def _():
    for real in ("Contested", "Greatest hall", "region4", "autosave 1"):
        assert not hc.TEST_SAVE.search(real), real
        assert not scenario.looks_like_test(real), real
    for t in ("AI Run A", "AI Test Save", "AI_Run_B", "ai test 2"):
        assert hc.TEST_SAVE.search(t), t
    assert scenario.looks_like_test("region3-test") and scenario.looks_like_test("AI Run A")


# ------------------------------------------------------------------ #5 which game answers

@test("identity: a game on this port from another folder is 'foreign': nothing loaded into it, said hourly")
def _():
    t, logs = [1000.0], []
    df = TitleDF(path="D:\\DF-A")
    rv = reviver(df, logs, t)
    for _ in range(130):
        rv.tick(); t[0] += 60
    assert not loads(df), loads(df)
    assert 2 <= len([x for x in logs if "not this folder's own game" in x]) <= 3, logs
    df.path = "d:\\df-b\\"                          # its own folder, written another way: a load
    for _ in range(4):
        rv.tick(); t[0] += 60
    assert loads(df), logs[-3:]
    df.path = "."                                   # a relative answer can't tell: not refused
    assert rv.probe() == "title"


@test("identity: the pin refuses another game's last-fort.json; the overseer refuses a game from another folder")
def _():
    pin.clear()
    pin.LAST_FORT.write_text(json.dumps({"df_path": "D:\\DF-A", "save_dir": "region4", "fort": "region4#1430",
                                         "world": "W"}))
    said = []
    assert pin.take(time.time() - 10, at_title=True, log=said.append) is None
    assert said and "not this folder's own game" in said[0], said
    pin.LAST_FORT.write_text(json.dumps({"df_path": "D:\\DF-B", "save_dir": "region4", "fort": "region4#1430",
                                         "world": "W"}))
    assert pin.take(time.time() - 10, at_title=True)
    os.environ["DFAI_PIN"] = "1"
    try:
        assert pin.refusal("W", 1430, df_path="D:/DF-B") is None
        r = pin.refusal("W", 1430, df_path="D:/DF-A")
        assert r and "Not this folder's game" in r, r
        assert pin.refusal("W", 1430) is None              # (no path given: as before)
    finally:
        os.environ.pop("DFAI_PIN", None)
    assert pin.refusal("W", 1430, df_path="D:/DF-A") is None   # the player's own run: never refused
    pin.clear()


@test("identity: the hung-game kill never closes the port's listener when it isn't this folder's game")
def _():
    class R:
        def __init__(self, out):
            self.stdout, self.stderr, self.returncode = out, "", 0

    def run(cmd, **kw):
        if cmd[0] == "netstat":
            return R("  TCP    127.0.0.1:5000  0.0.0.0:0  LISTENING  4100\n")
        return R("4100|D:\\DF-A\\Dwarf Fortress.exe\n4200|D:\\DF-B\\Dwarf Fortress.exe\n")
    k = revive.kill_command(5000, run=run, exe="D:\\DF-B\\Dwarf Fortress.exe")
    assert "taskkill" not in k and "not this folder's" in k[-1], k
    k = revive.kill_command(5000, run=run, exe="D:\\DF-A\\Dwarf Fortress.exe")
    assert k == ["taskkill", "/F", "/PID", "4100"], k


@test("identity: a portable copy's saves never come from config's df_save_dir (another game's folder)")
def _():
    game = TMP / "DF-P"
    (game / "prefs").mkdir(parents=True)
    (game / "prefs" / "portable.txt").write_text("")
    (game / "save").mkdir()
    other = TMP / "AppData" / "save"
    other.mkdir(parents=True)
    config(df_launch=OWN + "/Dwarf Fortress.exe", dfhack_port=5002, df_save_dir=str(other))
    try:
        assert dfhack.save_roots(game) == [game / "save"], dfhack.save_roots(game)
    finally:
        config(df_launch=OWN + "/Dwarf Fortress.exe", dfhack_port=5002)


@test("identity: the keeper says when config.json has no port or no .exe of its own; same_path ignores case/slashes")
def _():
    assert keeper.port_note() is None
    config(df_launch="steam://rungameid/975370")
    try:
        line = keeper.port_note()
        assert line and "dfhack_port" in line and "df_launch" in line, line
    finally:
        config(df_launch=OWN + "/Dwarf Fortress.exe", dfhack_port=5002)
    assert util.own_df_folder() == OWN
    assert util.same_path("D:\\DF-B\\", "d:/df-b") and not util.same_path("D:/DF-A", "D:/DF-B")
    assert not util.same_path("", "")


if __name__ == "__main__":
    finish()
