"""(0.105.48, K8) The keeper and the saves: a real per-run identity, failed
loads by the save as written, the hung-game kill by pid only, backups that
never take the embark (or an old run) for the newest, housekeeping that
spares the kept copies, the memory after a key change, the keeper's end.

    python tests/test_k48_keeper_saves.py
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

TMP = Path(tempfile.mkdtemp())
os.environ["DFAI_LOG_DIR"] = str(TMP / "logs")

import backup  # noqa: E402
import fort_run  # noqa: E402
import health_check as hc  # noqa: E402
import keeper  # noqa: E402
import ledger  # noqa: E402
import memstore  # noqa: E402
import pin  # noqa: E402
import revive  # noqa: E402
from dfhack import DFHackError, GameNotRunning  # noqa: E402
from planner_core import Memory  # noqa: E402
from tokens import TokenBank  # noqa: E402

LOGS = TMP / "logs"
LOGS.mkdir(parents=True, exist_ok=True)
pin.PIN_FILE, pin.LAST_FORT = LOGS / "keeper-pin.json", LOGS / "last-fort.json"
revive.LAST_FORT = LOGS / "last-fort.json"
backup.BACKUP_DIR = TMP / "backups"
backup.STATE = backup.BACKUP_DIR / "last.json"
memstore.FORTS_DIR = TMP / "forts"
keeper.LOG_DIR, keeper.LOG, keeper.STATUS = LOGS, LOGS / "unattended.log", LOGS / "unattended-status.txt"
keeper.HEARTBEAT = LOGS / "heartbeat"


def make_save(root: Path, name: str, age: float, text: str | None = None) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "world.sav").write_text(text or name)
    t = time.time() - age
    os.utime(d / "world.sav", (t, t))
    os.utime(d, (t, t))
    return d


def last_fort(df_path, save_dir="region4", world="W", site=1430, run=None):
    d = {"df_path": str(df_path), "save_dir": save_dir, "fort": f"{save_dir}#{site}", "world": world}
    if run:
        d["run"] = run
    pin.LAST_FORT.write_text(json.dumps(d))


def fresh_backups():
    shutil.rmtree(backup.BACKUP_DIR, ignore_errors=True)
    backup.SESSION.clear()


# ------------------------------------------------------------------ run id

@test("run id: a save with none gets a new one; the save's wins; an unread ledger changes nothing")
def _():
    said = []
    m = Memory()
    m._texts = {"source": "save"}
    m2, _ = fort_run.settle(m, TokenBank(), {"ledger": {}}, said.append, make=lambda: "20261114-aaaa")
    assert m2 is m and m.fort_run == "20261114-aaaa" and any("run 20261114-aaaa" in x for x in said), said
    # the ledger then carries it into the save
    assert ledger.snapshot(m)["fort_run"] == "20261114-aaaa"
    assert not ledger.same(ledger.snapshot(m), {})
    m3 = Memory()
    m3._texts = {"source": "save"}
    fort_run.settle(m3, TokenBank(), {"ledger": {"fort_run": "20261101-bbbb"}}, said.append)
    assert m3.fort_run == "20261101-bbbb"
    m4 = Memory()
    m4._texts = {"source": "logs"}
    fort_run.settle(m4, TokenBank(), {"ledger": {"error": "x"}}, said.append)
    assert m4.fort_run == ""


@test("run id: the logs copy of another run (a fresh embark, the same key) is set aside, never acted on")
def _():
    said = []
    old = Memory()
    old.fort_run, old.saved_before = "20261101-old0", "the old run's plan"
    old.last_fired = {"dig": 258 * 403200 + 5000}             # the old run reached year 258
    old._texts = {"source": "logs"}
    embark = {"ledger": {}, "date": {"year": 250, "tick": 100}}  # a fresh embark: year 250, no run id
    m, bank = fort_run.settle(old, TokenBank(), embark, said.append, make=lambda: "20261114-new0")
    assert m is not old and m.saved_before == "" and m.fort_run == "20261114-new0", vars(m).get("saved_before")
    assert any("another run" in x for x in said), said
    # a save holding another run's id: set aside whatever the date
    old2 = Memory()
    old2.fort_run, old2.saved_before = "20261101-old0", "x"
    old2._texts = {"source": "logs"}
    m, _ = fort_run.settle(old2, TokenBank(), {"ledger": {"fort_run": "20261114-new0"}}, said.append)
    assert m is not old2 and m.fort_run == "20261114-new0"
    # the save holds none yet, but its game isn't behind the memory (the ledger not
    # written yet: the AI halted, a write that failed): this run's, kept
    same = Memory()
    same.fort_run, same.saved_before = "20261114-new0", "kept"
    same.last_fired = {"dig": 250 * 403200 + 50}
    same._texts = {"source": "logs"}
    m, _ = fort_run.settle(same, TokenBank(), embark, said.append, make=lambda: "20261114-zzzz")
    assert m is same and m.fort_run == "20261114-new0" and m.saved_before == "kept"
    # this run's own logs copy (the save unread) stays
    mine = Memory()
    mine.fort_run, mine.saved_before = "20261114-new0", "kept"
    mine._texts = {"source": "logs"}
    m, _ = fort_run.settle(mine, TokenBank(), {"ledger": {"fort_run": "20261114-new0"}}, said.append)
    assert m is mine and m.saved_before == "kept"
    # a logs copy from before run ids (none in it): kept, given the run
    pre = Memory()
    pre.saved_before = "kept too"
    pre._texts = {"source": "logs"}
    m, _ = fort_run.settle(pre, TokenBank(), {"ledger": {}}, said.append, make=lambda: "20261114-cccc")
    assert m is pre and m.saved_before == "kept too" and m.fort_run == "20261114-cccc"


@test("run id: the Lua ledger takes fort_run (ledger_set refuses fields it doesn't list)")
def _():
    src = (ROOT / "lua" / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    block = src[src.index("LEDGER_FIELDS = {"):src.index("}", src.index("LEDGER_FIELDS = {"))]
    assert re.search(r"\bfort_run\s*=\s*true", block), block[-200:]
    assert "fort_run" in ledger.FIELDS


@test("run id: the overseer puts it in last-fort.json and the pin takes it (pin.run_id follows last-fort)")
def _():
    pin.clear()
    revive.write_last_fort(str(TMP / "dfA"), "region4", "region4#1430", world="W", run="20261114-aaaa")
    assert json.loads(pin.LAST_FORT.read_text())["run"] == "20261114-aaaa"
    p = pin.take(time.time() - 60)
    assert p and p["run"] == "20261114-aaaa", p
    revive.write_last_fort(str(TMP / "dfA"), "autosave 2", "autosave 2#1430", world="W", run="20261114-bbbb")
    assert pin.run_id() == "20261114-bbbb"
    pin.clear()


# ------------------------------------------------------------------ load_fails

class TitleDF:
    def __init__(self):
        self.state, self.calls = "title", []

    def run(self, *args):
        self.calls.append(args)
        if self.state == "down":
            raise GameNotRunning("no")
        if args[0] == "lua":
            return "WORLD-LOADED SITE=1430" if self.state == "world" else "NO-WORLD SITE="
        return '{"ok": true, "started": true, "folder": "%s"}' % args[-1].split("|")[0]


@test("revive: 'autosave 2' failed twice, then DF wrote it again (a new season): it is tried again")
def _():
    t = [0.0]
    df = TitleDF()
    logs = []
    rv = revive.Reviver(logs.append, dfhack=df, launcher=lambda *_: None, clock=lambda: t[0])
    rv.candidates = lambda: (["autosave 2", "autosave 1"], None)
    rv.restore = None
    stamps = {"autosave 2": 100.0, "autosave 1": 50.0}
    rv.save_stamp = lambda f: stamps.get(f)

    def crash():
        for _ in range(4):
            rv.tick(); t[0] += 60
        df.state = "down"
        rv.tick(); t[0] += 60
        df.state = "title"

    crash(); crash()
    assert rv.load_fails == {"autosave 2": 2}, rv.load_fails
    t[0] += 3600
    crash()
    loads = [c[2] for c in df.calls if c[0] == "ai-title"]
    assert loads[-1] == "autosave 1", loads             # the bad save is passed over
    stamps["autosave 2"] = 9000.0                       # three weeks on: autosave 2 is a new save
    t[0] += 3600
    for _ in range(4):
        rv.tick(); t[0] += 60
    loads = [c[2] for c in df.calls if c[0] == "ai-title"]
    assert loads[-1] == "autosave 2", loads
    assert any("written again" in x for x in logs), logs


@test("revive: save_stamp reads the pinned fort's folder's world.sav time")
def _():
    root = TMP / "dfS" / "save"
    d = make_save(root, "autosave 2", 500)
    last_fort(TMP / "dfS")
    saved = revive.save_root
    revive.save_root = lambda p, s=None: root
    try:
        assert abs(revive.save_stamp("autosave 2") - (d / "world.sav").stat().st_mtime) < 1e-6
        assert revive.save_stamp("autosave 9") is None
    finally:
        revive.save_root = saved


# ------------------------------------------------------------------ the hung-game kill

class R:
    def __init__(self, out=""):
        self.stdout, self.stderr, self.returncode = out, "", 0


@test("hung game: netstat failing never kills by name; the game is found by its own .exe's pid")
def _():
    own = r"D:\DF-B\Dwarf Fortress.exe"

    def run(cmd, **kw):
        if cmd[0] == "netstat":
            raise revive.subprocess.TimeoutExpired("netstat", 30)
        if cmd[0] == "powershell":
            return R("4100|C:\\Steam\\steamapps\\common\\Dwarf Fortress\\Dwarf Fortress.exe\n"
                     f"4200|{own}\n4300|D:\\DF-C\\Dwarf Fortress.exe\n")
        return R('"Dwarf Fortress.exe","4100"\n"Dwarf Fortress.exe","4200"\n')
    k = revive.kill_command(5002, run=run, exe=own)
    assert k == ["taskkill", "/F", "/PID", "4200"], k
    # no pid known at all: left alone, never /IM
    k = revive.kill_command(5002, run=lambda cmd, **kw: (_ for _ in ()).throw(OSError("no")), exe=own)
    assert "/IM" not in k and "taskkill" not in k and "left alone" in k[-1], k
    k = revive.kill_command(5002, run=lambda cmd, **kw: R(""), exe=None)
    assert "taskkill" not in k, k


@test("hung game: the Steam game (a steam:// df_launch) is found by the pinned DF folder's .exe")
def _():
    last_fort(TMP / "steamDF")
    saved = revive.launch_command
    revive.launch_command = lambda: "steam://rungameid/975370"
    try:
        assert revive.game_exe() == str(TMP / "steamDF" / "Dwarf Fortress.exe")
    finally:
        revive.launch_command = saved


@test("hung game: when its process can't be told, the reviver says so and closes nothing")
def _():
    t = [1000.0]
    logs, ran = [], []
    df = TitleDF()
    df.state = "world"
    rv = revive.Reviver(logs.append, dfhack=df, launcher=lambda *_: None, clock=lambda: t[0])
    rv.tick(); t[0] += 60
    rv.probe = lambda: "unknown"
    saved = revive.os.name, revive.subprocess.run, revive.save_written_within, revive.kill_command
    revive.subprocess.run = lambda args, **kw: ran.append(args) or R("")
    revive.save_written_within = lambda s, clock=None: False
    revive.kill_command = lambda: ["cmd", "/c", "echo", "no game of this folder found: left alone (never closed by name)"]
    try:
        revive.os.name = "nt"
        for _ in range(35):
            rv.tick(); t[0] += 60
    finally:
        revive.os.name, revive.subprocess.run, revive.save_written_within, revive.kill_command = saved
    assert ran == [] and any("left alone" in x for x in logs), (ran, logs[-3:])


# ------------------------------------------------------------------ backups

FORT = {"world": "W", "site_id": 1430, "save_dir": "region4", "fort_run": "20261114-aaaa"}


@test("backup: after an overseer restart the run's newest autosave is copied, never the old embark dated today")
def _():
    fresh_backups()
    root = TMP / "bkA" / "save"
    make_save(root, "region4", 20 * 86400, "embark")
    make_save(root, "autosave 1", 3 * 3600, "season 3")
    make_save(root, "autosave 2", 2 * 3600, "season 4")
    now = time.time()
    backup.run_since("20261114-aaaa", now - 5 * 86400)     # the run began 5 days ago (an earlier overseer)
    backup.SESSION.clear()                                  # this overseer process just started
    line = backup.maybe(root, "region4", now=now, fort=dict(FORT), force=True, date={"tick": 1000})
    assert line and "(autosave 2)" in line, line
    copy = backup.copies_of("W", "1430", "region4", run="20261114-aaaa")[0]
    assert (copy / "world.sav").read_text() == "season 4"
    mark = backup.copy_fort(copy)
    assert mark["run"] == "20261114-aaaa" and isinstance(mark["save_mtime"], float), mark


@test("backup: a run first seen now (an upgrade mid-run): an autosave written since the keeper pinned it is its own")
def _():
    fresh_backups()
    root = TMP / "bkP" / "save"
    make_save(root, "region4", 20 * 86400, "embark")
    make_save(root, "autosave 3", 3600, "last season")
    last_fort(TMP / "bkP")
    pin.clear()
    p = pin.take(time.time() - 86400)
    p["pinned_at"] = time.time() - 86400                  # the keeper pinned it a day ago
    pin.PIN_FILE.write_text(json.dumps(p))
    try:
        fort = dict(FORT, fort_run="20261114-upgr")
        line = backup.maybe(root, "region4", now=time.time(), fort=fort, force=True, date={"tick": 1000})
    finally:
        pin.clear()
    assert line and "(autosave 3)" in line, line


@test("backup: a copy whose save is no newer than the last copy's is refused (tried again in an hour)")
def _():
    fresh_backups()
    root = TMP / "bkB" / "save"
    make_save(root, "region4", 20 * 86400, "embark")
    make_save(root, "autosave 2", 2 * 3600, "season 4")
    now = time.time()
    fort = dict(FORT)
    assert backup.maybe(root, "region4", now=now - 60, fort=fort, force=True, date={"tick": 1000})
    shutil.rmtree(root / "autosave 2")                      # (only the embark is left to see)
    line = backup.maybe(root, "region4", now=now + 86400, fort=fort, date={"tick": 1000})
    assert line and "no newer" in line, line
    assert len(backup.copies_of("W", "1430", "region4", run="20261114-aaaa")) == 1
    assert backup._last().get("run") == "20261114-aaaa"     # the retry's mark keeps the last copy's


@test("backup: an old run's copies (same world and site) are never this run's; order is by the save's time")
def _():
    fresh_backups()

    def mk(folder, name, run, smt):
        c = backup.BACKUP_DIR / folder / name
        c.mkdir(parents=True)
        (c / "world.sav").write_text(name)
        m = {"world": "W", "site": "1430", "save_dir": folder}
        if run:
            m["run"] = run
        if smt is not None:
            m["save_mtime"] = smt
        backup.fort_mark_path(c).write_text(json.dumps(m))
        return c
    old = mk("autosave 1", "2026-11-13 0300", "20261101-old0", 5000.0)
    unmarked_run = mk("region4", "2026-11-12 0300", None, None)
    embark_today = mk("region4", "2026-11-14 1915", "20261114-aaaa", 100.0)     # the embark, copied today
    newest = mk("autosave 2", "2026-11-14 0300", "20261114-aaaa", 9000.0)
    got = backup.copies_of("W", "1430", "region4", run="20261114-aaaa")
    assert got == [newest, embark_today], got
    assert old not in got and unmarked_run not in got
    # no run known (a pin from before 0.105.48): as before, every copy of the world and site
    assert old in backup.copies_of("W", "1430", "region4")


@test("restore: with the pinned run, the old run's newer backup is never restored")
def _():
    fresh_backups()
    df = TMP / "dfR"
    (df / "save" / "region4").mkdir(parents=True, exist_ok=True)
    last_fort(df, run="20261114-aaaa")
    pin.clear()
    assert pin.take(time.time() - 60)
    for name, run in (("2026-11-13 0300", "20261101-old0"), ("2026-11-10 0300", "20261114-aaaa")):
        c = backup.BACKUP_DIR / "autosave 1" / name
        c.mkdir(parents=True)
        (c / "world.sav").write_text(run)
        backup.fort_mark_path(c).write_text(json.dumps({"world": "W", "site": "1430", "run": run}))
    saved = revive.save_root
    revive.save_root = lambda p, s=None: df / "save"
    try:
        name = revive.restore_from_backup()
    finally:
        revive.save_root = saved
        pin.clear()
    assert name == "AI restore 2026-11-10 0300", name
    assert (df / "save" / name / "world.sav").read_text() == "20261114-aaaa"


# ------------------------------------------------------------------ housekeeping

@test("housekeeping: the played fort's kept weeklies under other folder names stay; an old run's are thinned")
def _():
    bk = TMP / "hk-backups"
    shutil.rmtree(bk, ignore_errors=True)
    now = time.time()
    from datetime import datetime

    def mk(folder, days, run):
        name = datetime.fromtimestamp(now - days * 86400).strftime("%Y-%m-%d %H%M")
        c = bk / folder / name
        c.mkdir(parents=True)
        (c / "world.sav").write_text("x")
        backup.fort_mark_path(c).write_text(json.dumps({"world": "W", "site": "1430", "run": run}))
        t = now - 40 * 86400                                  # copytree: the source save's old time
        os.utime(c, (t, t))
        return c
    weeklies = [mk("region4", d, "R-new") for d in (30, 23, 16)]
    today = mk("region4", 0.01, "R-new")
    olds = [mk("autosave 1", d, "R-old") for d in (40, 33, 26)]
    flags, plain = hc.housekeeping([], "autosave 2", bk, now=now,
                                   current_fort={"world": "W", "site": "1430", "run": "R-new"})
    assert all(c.exists() for c in weeklies + [today]), plain
    assert not olds[0].exists() and not olds[1].exists() and olds[2].exists(), plain
    assert not backup.fort_mark_path(olds[0]).exists(), "the mark is removed with its copy"
    assert "2 old copies" in plain[-1], plain


# ------------------------------------------------------------------ memory after a key change

class TimeoutBridge:
    def load_memory(self):
        raise DFHackError("timed out")


@test("memory: after a revive ('autosave 2'), a failed read of the save falls back to the logs copy by site")
def _():
    m = Memory()
    m.saved_before, m.fort_run = "the plan", "20261114-aaaa"
    memstore.save("region4#1430", m, TokenBank())
    memstore.ALIASES["autosave 2#1430"] = memstore.fort_dir("region4#1430").name
    try:
        got, _ = memstore.load("autosave 2#1430", TimeoutBridge())
    finally:
        memstore.ALIASES.pop("autosave 2#1430", None)
    assert got._texts["save_unread"] and got._texts["source"] == "logs", got._texts["source"]
    assert got.saved_before == "the plan"


@test("overseer: the save unread and no logs copy: nothing acted on, no memory.json written over")
def _():
    import overseer
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    said, acted = [], []
    saved_say = overseer.say
    overseer.say = said.append

    class B:
        version = {"recipes": [], "tools": []}

        def status(self):
            return {"ok": True, "in_fort": True, "halted": False, "decisions": {}}

        def state(self, include_units=True):
            return copy.deepcopy(base)

        def events(self):
            return []

        def act(self, a):
            acted.append(a)
            return {"ok": True}

        def load_memory(self):
            raise DFHackError("timed out")
    try:
        overseer.MEMORY_CACHE.clear()
        key = overseer.fort_key(base)
        shutil.rmtree(memstore.fort_dir(key), ignore_errors=True)
        overseer.one_cycle(B(), autopilot=True)
    finally:
        overseer.say = saved_say
    assert any("not acting this cycle" in x for x in said), said[-5:]
    assert not [a for a in acted if a.get("type") not in ("report_status",)], acted
    assert not (memstore.fort_dir(key) / "memory.json").exists()


# ------------------------------------------------------------------ the keeper's end

class Proc:
    def __init__(self):
        self.stdout = iter([])

    def poll(self):
        return 1

    def kill(self):
        pass


@test("keeper: popen raising (python moved, out of handles) is logged and retried, not the keeper's end")
def _():
    keeper.LOG.unlink(missing_ok=True)
    calls = []

    def popen(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("[WinError 2] The system cannot find the file specified")
        return Proc()
    assert keeper.main([], popen=popen, sleep=lambda s: None, max_runs=2) == 0
    text = keeper.LOG.read_text(encoding="utf-8")
    assert len(calls) == 2 and "couldn't be run (OSError" in text and "Traceback" in text, text[-600:]


@test("keeper: an unexpected error ends it loudly (log, status, exit 2), and the run check flags it")
def _():
    keeper.LOG.unlink(missing_ok=True)
    saved = keeper.write_status, keeper.leave_fort_open
    n = [0]

    def ws(*a):
        n[0] += 1
        if n[0] == 2:
            raise RuntimeError("disk gone")         # inside the loop, outside run_once
        saved[0](*a)
    keeper.write_status, keeper.leave_fort_open = ws, lambda: None
    try:
        code = keeper.main([], popen=lambda *a, **k: Proc(), sleep=lambda s: None, max_runs=3)
    finally:
        keeper.write_status, keeper.leave_fort_open = saved
    assert code == 2, code
    text = keeper.LOG.read_text(encoding="utf-8")
    assert "Keeper stopped unexpectedly (RuntimeError: disk gone)" in text, text[-400:]
    status = keeper.STATUS.read_text(encoding="utf-8")
    assert "stopped unexpectedly" in status, status
    flags, _ = hc.keeper_end_flags(keeper.STATUS, keeper.HEARTBEAT)
    assert flags and "stopped on an error" in flags[0], flags
    lf, _ = hc.log_flags(text.splitlines())
    assert any("keeper trouble" in f for f in lf), lf


@test("run check: a keeper gone without a word (no heartbeat for hours) is flagged; a Ctrl-C stop isn't")
def _():
    st, hb = TMP / "st.txt", TMP / "hb"
    hb.write_text("")
    old = time.time() - 5 * 3600
    os.utime(hb, (old, old))
    st.write_text("keeper started x\nrestarts: 0\nlast: 2026-11-14 10:00:00 running\n")
    flags, _ = hc.keeper_end_flags(st, hb)
    assert flags and "never said it stopped" in flags[0], flags
    st.write_text("keeper started x\nrestarts: 0\nlast: 2026-11-14 10:00:00 Keeper stopped (Ctrl-C)\n")
    assert hc.keeper_end_flags(st, hb)[0] == []


@test("keeper: five short runs in a row are said loudly (the game runs with no AI)")
def _():
    keeper.LOG.unlink(missing_ok=True)
    keeper.main([], popen=lambda *a, **k: Proc(), sleep=lambda s: None, max_runs=5)
    text = keeper.LOG.read_text(encoding="utf-8")
    assert "stopped 5 times in a row" in text, text[-500:]


if __name__ == "__main__":
    finish()
