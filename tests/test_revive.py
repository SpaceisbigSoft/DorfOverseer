"""Tests for brain/revive.py (bringing the game back) and brain/run_summary.py.

    python tests/test_revive.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

import revive  # noqa: E402
import run_summary  # noqa: E402
from dfhack import GameNotRunning  # noqa: E402

RESULTS = []


def test(name):
    def wrap(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


class FakeDF:
    def __init__(self):
        self.state, self.calls = "down", []

    def run(self, *args):
        self.calls.append(args)
        if self.state == "down":
            raise GameNotRunning("no")
        if args[0] == "lua":
            return "WORLD-LOADED" if self.state == "world" else "NO-WORLD"
        return '{"ok": true, "started": true}'


@test("backup (0.99.13): the save folder is looked up only when a copy is due")
def _():
    import time as _time
    import backup
    calls = []
    old_state = backup.STATE
    with tempfile.TemporaryDirectory() as tmp:
        backup.STATE = Path(tmp) / "last-backup.json"
        try:
            backup.STATE.write_text(json.dumps({"at": _time.time()}), encoding="utf-8")      # copied just now
            assert backup.maybe(lambda: calls.append(1) or None, "region2") is None
            assert not calls, "looked up the save folder though no copy was due"
            backup.STATE.write_text(json.dumps({"at": 0}), encoding="utf-8")                 # a day ago and more
            assert backup.maybe(lambda: calls.append(1) or None, "region2") is None
            assert calls == [1], calls
        finally:
            backup.STATE = old_state


@test("save folders (0.99.13): DF's user folder first; the folder that holds the save wins")
def _():
    import os
    import dfhack
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        game = tmp / "Dwarf Fortress"
        (game / "save" / "autosave 1").mkdir(parents=True)           # old portable saves
        user = tmp / "AppData" / "Bay 12 Games" / "Dwarf Fortress" / "save"
        (user / "region2").mkdir(parents=True)
        old, old_cfg = os.environ.get("APPDATA"), dfhack.CONFIG_PATH
        os.environ["APPDATA"] = str(tmp / "AppData")
        dfhack.CONFIG_PATH = tmp / "no-config.json"
        try:
            assert dfhack.save_roots(game) == [user, game / "save"], dfhack.save_roots(game)
            assert dfhack.save_root(game, "region2") == user
            assert dfhack.save_root(game, "autosave 1") == game / "save"   # only the portable one has it
            assert dfhack.save_root(game) == user
        finally:
            dfhack.CONFIG_PATH = old_cfg
            if old is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = old


@test("revive: down 3 minutes -> started with df_launch (once in 15 min); at the title 2 minutes -> ai-title load")
def _():
    t = [1000.0]
    logs, launched = [], []
    df = FakeDF()
    rv = revive.Reviver(logs.append, dfhack=df, launcher=launched.append, clock=lambda: t[0])
    revive.launch_command = lambda: "C:/DF/Dwarf Fortress.exe"
    rv.candidates = lambda: (["region2"], None)
    for _ in range(4):                       # probes a minute apart: down since 1000
        rv.tick(); t[0] += 60
    assert launched == ["C:/DF/Dwarf Fortress.exe"], (launched, logs)
    for _ in range(5):
        rv.tick(); t[0] += 60
    assert len(launched) == 1                 # not again within 15 minutes
    df.state = "title"
    for _ in range(4):
        rv.tick(); t[0] += 60
    assert ("ai-title", "load", "region2") in df.calls, df.calls
    df.state = "world"
    rv.tick()
    assert rv.down_since is None and rv.title_since is None


@test("revive: the game closed when the keeper starts -> started within about 30 s")
def _():
    t = [0.0]
    logs, launched = [], []
    rv = revive.Reviver(logs.append, dfhack=FakeDF(), launcher=launched.append, clock=lambda: t[0])
    revive.launch_command = lambda: "steam://rungameid/2346660"
    for _ in range(3):
        rv.tick(); t[0] += 15
    assert launched == ["steam://rungameid/2346660"], (launched, logs)


@test("dfhack-run crashing with no output (0xC0000005) means the game isn't running")
def _():
    import subprocess
    import dfhack as D
    real = subprocess.run
    subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 3221225477, "", "")
    try:
        try:
            D.DFHack(dfhack_run=Path("x"), timeout_s=1).run("lua", "print(1)")
            assert False, "no error"
        except GameNotRunning:
            pass
    finally:
        subprocess.run = real


@test("revive: with the fort's world known, the newest save of that world (autosaves are shared by every world)")
def _():
    t = [0.0]
    df = FakeDF()
    df.state = "title"
    rv = revive.Reviver(lambda *_: None, dfhack=df, launcher=lambda *_: None, clock=lambda: t[0])
    rv.seen_up = True
    rv.candidates = lambda: (["autosave 2", "region2", "autosave 1"], "Enxah")
    for _ in range(4):
        rv.tick(); t[0] += 60
    assert ("ai-title", "load-match", "Enxah", "autosave 2|region2|autosave 1") in df.calls, df.calls


@test("revive: no df_launch in config -> says so once, never launches")
def _():
    t = [0.0]
    logs, launched = [], []
    rv = revive.Reviver(logs.append, dfhack=FakeDF(), launcher=launched.append, clock=lambda: t[0])
    revive.launch_command = lambda: None
    for _ in range(30):
        rv.tick(); t[0] += 60
    assert not launched and sum("no \"df_launch\"" in line for line in logs) == 1, logs


@test("run summary: actions by rule, refusals with the reason, and possible loops")
def _():
    with tempfile.TemporaryDirectory() as d:
        fort = Path(d) / "fortA"
        fort.mkdir()
        now = datetime.now()
        rows = []
        for i in range(12):
            rows.append({"time": now.isoformat(), "kind": "decision", "mode": "autopilot", "rule": "trade",
                         "action": {"type": "bring_goods"}, "result": {"ok": True}})
        rows.append({"time": now.isoformat(), "kind": "decision", "mode": "autopilot", "rule": "well",
                     "action": {"type": "place_well"}, "result": {"ok": False, "error": "no water"}})
        rows.append({"time": (now - timedelta(days=3)).isoformat(), "kind": "decision", "mode": "autopilot",
                     "rule": "old", "action": {"type": "x"}, "result": {"ok": True}})
        (fort / "journal.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        lines = run_summary.summarize(now - timedelta(hours=1), Path(d))
        text = "\n".join(lines)
        assert lines[0].startswith("13 action(s)") and "12 done, 1 refused" in lines[0], lines
        assert "trade: bring_goods x12" in text and "well: place_well x1 (no water)" in text, text
        assert "POSSIBLE LOOPS" in text and "old" not in text, text
        # (0.105.24) the water survey's slices are no loop; a refusal is counted as one
        rows += [{"time": now.isoformat(), "kind": "decision", "mode": "autopilot", "rule": "water",
                  "action": {"type": "survey_water"}, "result": {"ok": True}}] * 20
        rows += [{"time": now.isoformat(), "kind": "decision", "mode": "autopilot", "rule": "quarry",
                  "action": {"type": "quarry", "count": 60}, "result": {"ok": False, "error": "quarry needs count 1-30"}}] * 11
        (fort / "journal.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        text = "\n".join(run_summary.summarize(now - timedelta(hours=1), Path(d)))
        loops = next(x for x in text.splitlines() if x.startswith("POSSIBLE LOOPS"))
        assert "survey_water" not in loops and "quarry: quarry x11 (11 refused)" in loops, loops



@test("revive (0.100.1 review; 0.104.138: 30 minutes, never mid-save): a hung game is closed, once an hour")
def _():
    t = [1000.0]
    logs, kills = [], []
    df = FakeDF()
    df.state = "world"
    rv = revive.Reviver(logs.append, dfhack=df, launcher=lambda *_: None, clock=lambda: t[0])
    rv.tick(); t[0] += 60                     # seen up
    rv.probe = lambda: "unknown"
    saved_os, saved_run, saved_sw = revive.os.name, revive.subprocess.run, revive.save_written_within
    class R: stdout, stderr = "SUCCESS", ""
    revive.subprocess.run = lambda args, **kw: (kills.append(args), R())[1] if args[0] == "taskkill" else R()
    saving = [True]
    revive.save_written_within = lambda s, clock=None: saving[0]
    try:
        revive.os.name = "nt"
        for _ in range(29):
            rv.tick(); t[0] += 60
        assert kills == [], kills             # 29 minutes: still waiting
        for _ in range(3):
            rv.tick(); t[0] += 60
        assert kills == [] and any("still writing its save" in x for x in logs), logs   # the save goes on
        saving[0] = False
        rv.tick(); t[0] += 60
        assert len(kills) == 1 and kills[0][:3] == ["taskkill", "/F", "/IM"], kills
        for _ in range(30):
            rv.tick(); t[0] += 60
        assert len(kills) == 1, kills            # not again within the hour
    finally:
        revive.os.name, revive.subprocess.run, revive.save_written_within = saved_os, saved_run, saved_sw


@test("two games (0.105.1): the hung game is found by its port; the other game is never closed")
def _():
    class R:
        def __init__(self, out): self.stdout = out
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "netstat":
            return R("  TCP    127.0.0.1:5000  0.0.0.0:0  LISTENING  111\n  TCP    127.0.0.1:5001  0.0.0.0:0  LISTENING  222\n"
                     "  TCP    127.0.0.1:5001  127.0.0.1:6000  ESTABLISHED  333\n")
        return R('"Dwarf Fortress.exe","111"\n"Dwarf Fortress.exe","222"\n')
    assert revive.kill_command(5001, run=run) == ["taskkill", "/F", "/PID", "222"]
    assert revive.kill_command(5000, run=run) == ["taskkill", "/F", "/PID", "111"]
    k = revive.kill_command(5002, run=run)                   # nothing on that port, two games: neither closed
    assert "taskkill" not in k and "left alone" in k[-1], k

    def one(cmd, **kw):
        return R("") if cmd[0] == "netstat" else R('"Dwarf Fortress.exe","111"\n')
    assert revive.kill_command(5000, run=one) == ["taskkill", "/F", "/IM", "Dwarf Fortress.exe"]


@test("two games (0.105.1): config's dfhack_port reaches dfhack-run's environment")
def _():
    import dfhack
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.json"
        p.write_text(json.dumps({"dfhack_run": "x.exe", "dfhack_port": 5001}), encoding="utf-8")
        assert dfhack.configured_port(p) == 5001
        assert dfhack.port_env(5001)["DFHACK_PORT"] == "5001"
        assert dfhack.port_env(None) is None
        p.write_text(json.dumps({"dfhack_run": "x.exe", "dfhack_port": "bad"}), encoding="utf-8")
        import os
        old = os.environ.pop("DFHACK_PORT", None)
        try:
            assert dfhack.configured_port(p) is None
        finally:
            if old is not None:
                os.environ["DFHACK_PORT"] = old


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
