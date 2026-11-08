"""The real DFHack and Bridge classes (brain/dfhack.py, brain/bridge.py)
against a fake dfhack-run: subprocess.run replaced, everything above it real.

    python tests/test_dfhack_bridge.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import dfhack  # noqa: E402
from bridge import Bridge, BridgeError  # noqa: E402
from dfhack import DFHack, DFHackError, GameNotRunning  # noqa: E402

TMP = Path(tempfile.mkdtemp())
EXE = TMP / "dfhack-run.exe"
EXE.write_text("")


class FakeRun:
    """subprocess.run as dfhack-run: each call takes the next answer, a
    (returncode, stdout, stderr) or an exception; the calls are kept."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        a = self.answers.pop(0)
        if isinstance(a, BaseException):
            raise a
        code, out, err = a
        return subprocess.CompletedProcess(cmd, code, out, err)


def with_run(fake, fn):
    real = dfhack.subprocess.run
    dfhack.subprocess.run = fake
    try:
        return fn()
    finally:
        dfhack.subprocess.run = real


@test("DFHack.run: the program and arguments as given, the output (stdout then stderr), the limit and the port")
def _():
    fake = FakeRun((0, "hello\n", "warn\n"))
    df = DFHack(EXE, timeout_s=7, port=5011)
    out = with_run(fake, lambda: df.run("ai-bridge", "status"))
    assert out == "hello\nwarn\n", out
    cmd, kw = fake.calls[0]
    assert cmd == [str(EXE), "ai-bridge", "status"] and kw["timeout"] == 7, (cmd, kw)
    assert kw["env"]["DFHACK_PORT"] == "5011" and kw["encoding"] == "utf-8" and kw["errors"] == "replace"
    fake2 = FakeRun((0, "", ""))
    with_run(fake2, lambda: DFHack(EXE).run("x", timeout=45))
    assert fake2.calls[0][1]["timeout"] == 45 and fake2.calls[0][1]["env"] is None    # no port: inherited


@test("DFHack.run: no game (exit 2 'Could not connect', or 0xC0000005 with no output) is GameNotRunning")
def _():
    df = DFHack(EXE)
    for answer in ((2, "", "Could not connect to localhost:5000\n"), (3221225477, "", ""), (-1073741819, "  \n", "")):
        try:
            with_run(FakeRun(answer), lambda: df.run("ai-bridge", "status"))
            raise AssertionError(f"no error for {answer}")
        except GameNotRunning as e:
            assert "isn't running" in str(e), e
    # an access violation WITH output is the game failing, not absent; another exit code says its output
    for answer, word in (((3221225477, "lua error\n", ""), "3221225477"), ((1, "boom\n", ""), "boom")):
        try:
            with_run(FakeRun(answer), lambda: df.run("x"))
            raise AssertionError(f"no error for {answer}")
        except GameNotRunning:
            raise AssertionError(f"{answer} taken for a closed game")
        except DFHackError as e:
            assert word in str(e), e


@test("DFHack.run: a timeout and a program that won't start are DFHackErrors, never a crash")
def _():
    df = DFHack(EXE, timeout_s=3)
    for exc, word in ((subprocess.TimeoutExpired("x", 3), "within 3"), (OSError("command line too long"), "too long")):
        try:
            with_run(FakeRun(exc), lambda: df.run("x"))
            raise AssertionError(f"no error for {exc!r}")
        except DFHackError as e:
            assert word in str(e) and not isinstance(e, GameNotRunning), e


@test("DFHack.run_json: the last JSON line wins over the lines DFHack prints before it; none is an error")
def _():
    df = DFHack(EXE)
    out = with_run(FakeRun((0, 'Loading...\n{"ok": false}\nnoise\n  {"ok": true, "n": 2}\ntrailing\n', "")),
                   lambda: df.run_json("ai-bridge", "status"))
    assert out == {"ok": True, "n": 2}, out
    try:
        with_run(FakeRun((0, "nothing here\n", "")), lambda: df.run_json("ai-bridge", "status"))
        raise AssertionError("no error")
    except DFHackError as e:
        assert "No JSON" in str(e) and "nothing here" in str(e), e


@test("DFHack.from_config: no config, a .bat wrapper, a missing program refused; the timeout and port read")
def _():
    cfg = TMP / "config.json"
    cfg.unlink(missing_ok=True)
    for setup, word in ((None, "Missing config.json"),
                        ({"dfhack_run": str(TMP / "dfhack-run.bat")}, "dfhack-run.exe itself"),
                        ({"dfhack_run": str(TMP / "gone" / "dfhack-run.exe")}, "not found")):
        if setup is not None:
            cfg.write_text(json.dumps(setup), encoding="utf-8")
        try:
            DFHack.from_config(cfg)
            raise AssertionError(f"accepted {setup}")
        except DFHackError as e:
            assert word in str(e), e
    cfg.write_text(json.dumps({"dfhack_run": str(EXE), "timeout_s": 12, "dfhack_port": 5022}), encoding="utf-8")
    df = DFHack.from_config(cfg)
    assert df.dfhack_run == EXE and df.timeout_s == 12.0 and df.port == 5022, df


def game(*answers):
    """A Bridge over the real DFHack, its dfhack-run faked."""
    fake = FakeRun(*answers)
    return Bridge(DFHack(EXE, timeout_s=10)), fake


@test("Bridge: the handshake checks the protocol; an answer with ok=false is a BridgeError with its reason")
def _():
    b, fake = game((0, json.dumps({"ok": True, "protocol": 1, "bridge_version": "x"}) + "\n", ""),
                   (0, json.dumps({"ok": True, "protocol": 99}) + "\n", ""),
                   (0, json.dumps({"ok": False, "error": "no fort loaded"}) + "\n", ""))
    assert with_run(fake, b.handshake)["bridge_version"] == "x" and b.version["protocol"] == 1
    try:
        with_run(fake, b.handshake)
        raise AssertionError("protocol 99 accepted")
    except BridgeError as e:
        assert "protocol 99" in str(e), e
    try:
        with_run(fake, b.status)
        raise AssertionError("ok=false accepted")
    except BridgeError as e:
        assert str(e) == "no fort loaded", e
    assert [c[0][1:] for c in fake.calls] == [["ai-bridge", "version"]] * 2 + [["ai-bridge", "status"]]


@test("Bridge.state: the report read from the file the game names; the full one gets 30 s, the pulse the default")
def _():
    out = TMP / "out"
    out.mkdir(exist_ok=True)
    (out / "state.json").write_text(json.dumps({"date": {"year": 5}, "name": "Ôlon"}), encoding="utf-8")
    reply = json.dumps({"ok": True, "file": str(out / "state.json"), "build_ms": 250}) + "\n"
    b, fake = game((0, reply, ""), (0, reply, ""))
    s = with_run(fake, b.state)
    assert s["name"] == "Ôlon" and s["_meta"] == {"build_ms": 250, "file": str(out / "state.json")}, s
    assert b.out_dir == out
    with_run(fake, lambda: b.state(include_units=False, tier="pulse"))
    (cmd1, kw1), (cmd2, kw2) = fake.calls
    assert cmd1[1:] == ["ai-bridge", "state"] and kw1["timeout"] == 30.0, (cmd1, kw1["timeout"])
    assert cmd2[1:] == ["ai-bridge", "state", "--no-units", "--tier", "pulse"] and kw2["timeout"] == 10, kw2


@test("Bridge.act: the action as compact JSON; a refusal comes back to read, a failure raises; a closed game raises")
def _():
    b, fake = game((0, '{"ok": true, "order_id": 7}\n', ""),
                   (0, '{"ok": false, "rejected": true, "error": "amount out of range"}\n', ""),
                   (0, '{"ok": false, "error": "lua: boom"}\n', ""),
                   (2, "", "Could not connect\n"))
    r = with_run(fake, lambda: b.act({"type": "work_order", "recipe": "brew_drink", "amount": 5}))
    assert r == {"ok": True, "order_id": 7}
    assert fake.calls[0][0][1:] == ["ai-bridge", "act", '{"type":"work_order","recipe":"brew_drink","amount":5}']
    r = with_run(fake, lambda: b.act({"type": "work_order", "amount": 9999}))
    assert r["rejected"] and not r["ok"], r
    for exc in (BridgeError, GameNotRunning):
        try:
            with_run(fake, lambda: b.act({"type": "x"}))
            raise AssertionError(f"no {exc.__name__}")
        except exc:
            pass
    log = (Path(os.environ["DFAI_LOG_DIR"]) / "bridge.log").read_text(encoding="utf-8")
    assert "act {\"type\":\"work_order\"" in log and "amount out of range" in log, log[-500:]


@test("Bridge.save_memory: each kind's text in its own file beside the report, the list in memory-to-save.json")
def _():
    out = TMP / "out2"
    out.mkdir(exist_ok=True)
    b, fake = game((0, '{"ok": true}\n', ""))
    assert b.save_memory({"fort": "f"}) is False and not fake.calls          # no report read yet: nowhere to put it
    b.out_dir = out
    assert with_run(fake, lambda: b.save_memory({"fort": "f", "kinds": {"working": '{"a": 1}', "atlas": "[]"}}))
    sent = json.loads((out / "memory-to-save.json").read_text(encoding="utf-8"))
    assert sent == {"fort": "f", "kinds_files": {"working": "memory-to-save.working.txt",
                                                 "atlas": "memory-to-save.atlas.txt"}}, sent
    assert (out / "memory-to-save.working.txt").read_text(encoding="ascii") == '{"a": 1}'
    assert fake.calls[0][0][1:] == ["ai-bridge", "act", '{"type":"save_memory"}']


if __name__ == "__main__":
    finish()
