"""(0.105.33) Round 33, keeper group: revive counts lasting title-screen
refusals, the backup restore finds the fort's copies in any folder, the main
loop holds its unattended actions off a fort the pin refuses, preset_due by
site, the in-game answers acknowledged, and the B1 Lows.

    python tests/test_r33_keeper.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import make_test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

TMP = Path(tempfile.mkdtemp())
os.environ["DFAI_LOG_DIR"] = str(TMP / "logs")

import backup  # noqa: E402
import pin  # noqa: E402
import revive  # noqa: E402
import overseer  # noqa: E402
import keeper  # noqa: E402
import run_summary  # noqa: E402
from dfhack import GameNotRunning  # noqa: E402

pin.PIN_FILE = TMP / "logs" / "keeper-pin.json"
pin.LAST_FORT = TMP / "logs" / "last-fort.json"
revive.LAST_FORT = pin.LAST_FORT
backup.BACKUP_DIR = TMP / "backups"
backup.STATE = TMP / "backups" / "last.json"


def _before():
    pin.clear()
    os.environ.pop("DFAI_PIN", None)
    overseer.PIN_SEEN.update(checked=False, refused=None)


test = make_test(before=_before)


def write_pin(world="W", site="7", save_dir="region1"):
    df = TMP / "df"
    (df / "save").mkdir(parents=True, exist_ok=True)
    pin.PIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    pin.PIN_FILE.write_text(json.dumps({"world": world, "site": site, "save_dir": save_dir,
                                        "df_path": str(df)}), encoding="utf-8")
    return df


class TitleDF:
    """A game at the title screen whose load answers `answer`."""
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def run(self, *args, timeout=None):
        self.calls.append(args)
        if args[0] == "lua":
            return "NO-WORLD SITE="
        return self.answer


def run_day(rv, minutes=24 * 60):
    t = [0.0]
    rv.clock = lambda: t[0]
    for i in range(minutes):
        t[0] = i * 60.0
        rv.tick()


# ---------------------------------------------------------------- revive High 1

@test("revive: load-match 'no save of the world' counts against every folder; the restore is reached")
def _():
    logs = []
    rv = revive.Reviver(logs.append, dfhack=TitleDF('{"ok":false,"error":"no save of the world W among autosave 1: Other"}'))
    rv.candidates = lambda: (["autosave 1", "autosave 2"], "W")
    restores = []
    rv.restore = lambda log: restores.append(1) or None
    run_day(rv)
    tries = [c for c in rv.df.calls if c[0] == "ai-title"]
    assert len(tries) == 2, tries                      # was 72 a day
    assert rv.load_fails == {"autosave 1": 2, "autosave 2": 2}, rv.load_fails
    assert restores, "the backup restore is never reached"
    assert any("no save of the pinned fort is left" in x for x in logs), logs


@test("revive: a plain load's 'no save called' counts against that folder; the next one is tried")
def _():
    rv = revive.Reviver(lambda s: None, dfhack=TitleDF('{"ok":false,"error":"no save called region1 on the title screen"}'))
    rv.candidates = lambda: (["region1", "autosave 1"], None)
    rv.restore = lambda log: None
    run_day(rv, minutes=200)
    loaded = [c[2] for c in rv.df.calls if c[0] == "ai-title"]
    assert loaded[:3] == ["region1", "region1", "autosave 1"], loaded


@test("revive: a list left open ('backed out') and 'not at the title screen' are never counted")
def _():
    for err in ("a list was open on the title screen (mode 2): backed out to the menu; the next try starts from there",
                "not at the title screen", "a world is already loaded"):
        rv = revive.Reviver(lambda s: None, dfhack=TitleDF(json.dumps({"ok": False, "error": err})))
        rv.candidates = lambda: (["autosave 1"], "W")
        rv.restore = lambda log: None
        run_day(rv, minutes=200)
        assert rv.load_fails == {}, (err, rv.load_fails)
    assert revive.refused_folders('{"ok":false,"error":"the save\'s world X is not listed"}',
                                  ["a", "b"], "a", False) == ["a"]


# ---------------------------------------------------------------- revive High 2

@test("backup: a copy made from 'autosave 2' after a revive is marked with its world and site; the restore finds it")
def _():
    df = write_pin()
    root = df / "save"
    src = root / "autosave 2"
    src.mkdir(parents=True, exist_ok=True)
    (src / "world.sav").write_text("x")
    old = time.time() - 4000
    os.utime(src / "world.sav", (old, old))
    os.utime(src, (old, old))
    backup.STATE.unlink(missing_ok=True)
    backup.SESSION.clear()
    fort = {"world": "W", "site_id": 7, "save_dir": "autosave 2"}
    backup.SESSION["W#7"] = old - 10          # the fort was seen loaded before the autosave
    line = backup.maybe(root, "autosave 2", fort=fort, force=True)
    assert line and "a copy of the save" in line, line
    copies = [c for c in (backup.BACKUP_DIR / "autosave 2").iterdir() if c.is_dir()]
    assert len(copies) == 1 and backup.copy_fort(copies[0])["site"] == "7", copies
    name = revive.restore_from_backup(lambda s: None)       # the pin's save_dir is region1
    assert name and name.startswith(revive.RESTORE_PREFIX) and (root / name / "world.sav").exists(), name


@test("backup: another world's copy (marked, or unmarked in a shared autosave folder) is never restored")
def _():
    df = write_pin(save_dir="autosave 1")
    import shutil
    shutil.rmtree(backup.BACKUP_DIR, ignore_errors=True)
    a = backup.BACKUP_DIR / "autosave 1" / "2026-11-10 0300"
    a.mkdir(parents=True)
    backup.fort_mark_path(a).write_text(json.dumps({"world": "Other", "site": "7"}))
    b = backup.BACKUP_DIR / "autosave 1" / "2026-11-09 0300"   # unmarked: whose?
    b.mkdir(parents=True)
    assert backup.copies_of("W", "7", "autosave 1") == []
    assert revive.restore_from_backup(lambda s: None) is None
    # an unmarked copy under the pin's own (unshared) folder still counts, as before
    c = backup.BACKUP_DIR / "region1" / "2026-11-08 0300"
    c.mkdir(parents=True)
    assert backup.copies_of("W", "7", "region1") == [c]
    assert df


@test("backup: KEEP per fort in a shared folder: another world's copies never push this fort's out")
def _():
    import shutil
    shutil.rmtree(backup.BACKUP_DIR, ignore_errors=True)
    d = backup.BACKUP_DIR / "autosave 1"
    for i, world in enumerate(["W", "W", "Other", "Other", "Other"]):
        c = d / f"2026-11-0{i + 1} 0300"
        c.mkdir(parents=True)
        backup.fort_mark_path(c).write_text(json.dumps({"world": world, "site": "7"}))
    root = TMP / "df2" / "save"
    src = root / "autosave 1"
    src.mkdir(parents=True, exist_ok=True)
    (src / "f").write_text("x")
    old = time.time() - 4000
    os.utime(src / "f", (old, old))
    os.utime(src, (old, old))
    backup.SESSION.clear()
    backup.SESSION["Other#7"] = old - 10
    line = backup.maybe(root, "autosave 1", fort={"world": "Other", "site_id": 7}, force=True)
    assert line and "a copy" in line, line
    left = sorted(c.name for c in d.iterdir() if c.is_dir())
    assert len(backup.copies_of("W", "7", "autosave 1")) == 2, left   # W's two kept
    # (0.105.46, I6) Other's kept by age (backup.choose_keep), the new copy among them
    others = backup.copies_of("Other", "7", "autosave 1")
    assert others and backup.copy_time(others[0]) and len(others) >= 2, left
    assert sorted(others) == sorted(backup.choose_keep(others, time.time())), left


# ---------------------------------------------------------------- revive Med (second DF)

@test("revive: never seen up and a Dwarf Fortress process already runs: no second copy until START_BUSY_S")
def _():
    class Down:
        def run(self, *a, timeout=None):
            raise GameNotRunning("no")
    launched, logs = [], []
    rv = revive.Reviver(logs.append, dfhack=Down(), launcher=launched.append)
    rv.df_running = lambda: True
    real = revive.launch_command
    revive.launch_command = lambda: "df.exe"
    try:
        t = [0.0]
        rv.clock = lambda: t[0]
        for i in range(0, 200, 15):
            t[0] = float(i)
            rv.tick()
            if t[0] < revive.START_BUSY_S:
                assert not launched, (i, launched)
        assert launched == ["df.exe"], launched
        assert any("DFHack doesn't answer yet" in x for x in logs), logs
        # no process: started after START_DOWN_S as before
        launched.clear()
        rv2 = revive.Reviver(lambda s: None, dfhack=Down(), launcher=launched.append)
        rv2.df_running = lambda: False
        t2 = [0.0]
        rv2.clock = lambda: t2[0]
        for i in range(0, 40, 15):
            t2[0] = float(i)
            rv2.tick()
        assert launched == ["df.exe"], launched
    finally:
        revive.launch_command = real
    out = type("R", (), {"stdout": '"Dwarf Fortress.exe","1234","Console","1","500,000 K"\n'})()
    assert revive.df_running(run=lambda *a, **k: out) is True
    none = type("R", (), {"stdout": "INFO: No tasks are running which match the specified criteria.\n"})()
    assert revive.df_running(run=lambda *a, **k: none) is False


# ---------------------------------------------------------------- overseer Med (pin in the main loop)

class PausedGame:
    def __init__(self, world="Other", site=9):
        self.acts, self.version, self.world, self.site = [], None, world, site

    def handshake(self):
        return {"bridge_version": "0.36.0", "dfhack_version": "53.16-r3"}

    def status(self):
        return {"in_fort": True, "paused": True, "halted": False, "fps": 0, "meeting": True,
                "date": {"year": 150, "tick": 100, "day": 1, "month": "Granite", "season": "spring"}}

    def state(self, include_units=False, tier="daily"):
        return {"tier": tier, "fort": {"world": self.world, "site_id": self.site}}

    def act(self, a):
        self.acts.append(a)
        return {"ok": True}


def run_loop(game, args, ticks=40, step=2.0):
    clock = [0.0]
    calls = [0]
    real = (overseer.Bridge, overseer.time.monotonic, overseer.time.sleep, sys.argv)
    overseer.Bridge = lambda: game
    overseer.time.monotonic = lambda: clock[0]

    def fake_sleep(s):
        calls[0] += 1
        clock[0] += step
        if calls[0] >= ticks:
            raise KeyboardInterrupt
    overseer.time.sleep = fake_sleep
    sys.argv = ["overseer.py"] + args
    try:
        overseer.main()
    finally:
        overseer.Bridge, overseer.time.monotonic, overseer.time.sleep, sys.argv = real


@test("overseer under the keeper: another world's fort gets no unattended action (announcements, unpause, meeting)")
def _():
    write_pin()
    os.environ["DFAI_PIN"] = "1"
    g = PausedGame(world="Other", site=9)
    run_loop(g, ["--autopilot", "--unattended"], ticks=400)
    assert g.acts == [], g.acts
    assert overseer.PIN_SEEN["refused"], overseer.PIN_SEEN
    # the pinned fort: checked from the small report while paused, then unpaused
    overseer.PIN_SEEN.update(checked=False, refused=None)
    g = PausedGame(world="W", site=7)
    run_loop(g, ["--autopilot", "--unattended"])
    kinds = [a.get("type") for a in g.acts]
    assert "quiet_announcements" in kinds and "unpause" in kinds, kinds
    # without the keeper (no DFAI_PIN), nothing is held
    os.environ.pop("DFAI_PIN", None)
    assert overseer.pin_hold() is False


# ---------------------------------------------------------------- overseer Med (preset_due)

@test("preset_due: the same fort read from an autosave folder keeps the player's later choice")
def _():
    overseer.PRESET_FILE.parent.mkdir(parents=True, exist_ok=True)
    overseer.PRESET_FILE.write_text(json.dumps({"region1#7": {"name": "War-hold", "run": "x"}}))
    assert overseer.preset_due("region1#7", "War-hold", "Peaceful") is None
    assert overseer.preset_due("autosave 2#7", "War-hold", "Peaceful") is None
    assert overseer.preset_due("autosave 2#8", "War-hold", "Peaceful") == "first time for this fort"
    assert overseer.preset_due("autosave 2#7", "War-hold", None) == "the save shows no preset"
    assert overseer.preset_due("autosave 2#7", "Deep mine", "Peaceful") == "first time for this fort"


# ---------------------------------------------------------------- overseer Med (ack)

@test("ack: only answers read this cycle; a 'no' to a proposal not made goes into declined; a 'yes' waits")
def _():
    class M:
        declined: dict = {}
    m = M()
    m.declined = {}
    ack = overseer.acknowledged({"a1": "yes", "b2": "no", "c3": "yes"}, {"a1"}, m, 5000)
    assert sorted(ack) == ["a1", "b2"], ack
    assert m.declined == {"b2": 5000}, m.declined


# ---------------------------------------------------------------- Lows

@test("keeper (Low): a failed pin is tried again, said once")
def _():
    real = pin.take
    n = [0]

    def boom(*a, **k):
        n[0] += 1
        raise RuntimeError("disk")
    pin.take = boom
    keeper.EXTRAS["start_ts"], keeper.EXTRAS["pinned"] = time.time(), None
    keeper.EXTRAS.pop("pin_error_said", None)
    try:
        keeper.pin_fort()
        keeper.pin_fort()
    finally:
        pin.take = real
    assert n[0] == 2 and keeper.EXTRAS["pinned"] is None
    assert keeper.LOG.read_text(encoding="utf-8").count("couldn't pin the fort") == 1


@test("keeper (Low): the back-off sleeps in 5-s steps with the chores between")
def _():
    slept, chores = [], []
    real = keeper.chores
    keeper.chores = lambda: chores.append(1)
    try:
        keeper.sleep_doing_chores(12, sleep=slept.append)
    finally:
        keeper.chores = real
    assert slept == [5, 5, 2] and len(chores) == 3, (slept, chores)


@test("run_summary (Low): an action the game didn't answer (ok None) is counted apart, not as done")
def _():
    d = Path(tempfile.mkdtemp())
    fort = d / "f"
    fort.mkdir()
    now = datetime.now()
    rows = [{"time": now.isoformat(), "kind": "decision", "mode": "autopilot", "rule": "r",
             "action": {"type": "x"}, "result": {"ok": None, "error": "no reply"}},
            {"time": now.isoformat(), "kind": "decision", "mode": "autopilot", "rule": "r",
             "action": {"type": "x"}, "result": {"ok": True}}]
    (fort / "journal.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    line = run_summary.summarize(now - timedelta(hours=1), d)[0]
    assert "1 done, 0 refused, 1 unanswered" in line, line


@test("probe_gear (Low): a soldier off duty doesn't make the squad 'short'")
def _():
    calls = []

    class B:
        def _call(self, *a):
            calls.append(a)
            return {}
    st = {"military": {"gear": {"soldiers": 5, "on_duty": 3, "armed": 3, "helmed": 3}},
          "date": {"year": 150, "tick": 100}}
    overseer.LAST_GEAR_PROBE.clear()
    overseer.probe_gear(B(), st, "k#1")
    assert not calls, calls
    st["military"]["gear"]["armed"] = 2
    overseer.probe_gear(B(), st, "k#1")
    assert calls, calls


@test("soak_report (Low): the logs folder follows DFAI_LOG_DIR, and every rotation is read")
def _():
    import soak_report
    assert soak_report.LOGS == Path(os.environ["DFAI_LOG_DIR"]), soak_report.LOGS
    d = Path(tempfile.mkdtemp())
    log = d / "unattended.log"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for name in ("unattended.old3.log", "unattended.old2.log", "unattended.old.log", "unattended.log"):
        (d / name).write_text(f"[{stamp}] {name}\n", encoding="utf-8")
    lines = soak_report.log_lines(datetime.now() - timedelta(hours=1), log)
    assert [x.split()[-1] for x in lines] == ["unattended.old3.log", "unattended.old2.log",
                                              "unattended.old.log", "unattended.log"], lines


finish()
