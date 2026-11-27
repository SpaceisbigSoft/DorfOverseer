"""(F5a) The stop file says who asked and why; the keeper logs it.

26 Nov 15:39: all six keepers stopped at once and nobody could tell who asked.
The keepers' window's S now asks Y first and writes logs/keeper-stop as JSON
{"by", "why", "at"}; the keeper logs those when it stops. An empty file or the
old plain "stop" still stops it, with nothing more said (fail soft). Also
text checks of the launcher scripts (no PowerShell here to run them).

    python tests/test_f5_keeper_stop_note.py
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

import keeper  # noqa: E402

TMP = Path(tempfile.mkdtemp())
keeper.LOG_DIR = TMP
keeper.LOG = TMP / "unattended.log"
keeper.STATUS = TMP / "status.txt"
keeper.HEARTBEAT = TMP / "heartbeat"
keeper.STOP_FILE = TMP / "keeper-stop"
LAUNCH = ROOT / "tools" / "launch"
NOTE = {"by": "keepers window key S", "why": "Windows update tonight", "at": "2026-11-27T10:00:00+01:00"}


def _ask(text: str) -> str:
    """stop_asked on a stop file holding text: the log line it wrote."""
    keeper.LOG.write_text("", encoding="utf-8")
    keeper.STOP_FILE.write_text(text, encoding="utf-8")
    try:
        keeper.stop_asked()
    except keeper.StopAsked:
        pass
    else:
        raise AssertionError("no StopAsked")
    assert not keeper.STOP_FILE.exists()
    return keeper.LOG.read_text(encoding="utf-8")


@test("a JSON stop file: the keeper logs by, why and when, and stops")
def _():
    log = _ask(json.dumps(NOTE))
    assert "asked to stop (logs/keeper-stop" in log, log
    assert "by keepers window key S" in log and "why: Windows update tonight" in log, log
    assert "at 2026-11-27T10:00:00+01:00" in log, log


@test("an empty file, the old plain 'stop', broken JSON or a JSON list: still stops, nothing more said")
def _():
    for text in ("", "stop", "{not json", "[1, 2]", "{}"):
        log = _ask(text)
        assert "asked to stop (logs/keeper-stop, from the keepers' window)." in log, (text, log)


@test("a BOM (Windows PowerShell's UTF-8) and a missing field: read; long or multi-line text kept on one line")
def _():
    keeper.STOP_FILE.write_bytes(b"\xef\xbb\xbf" + json.dumps({"by": "a\nb", "why": "x" * 500}).encode())
    note = keeper.stop_note()
    assert note.startswith(" (by a b, why: ") and "\n" not in note and "at " not in note, note
    assert len(note) < 260, len(note)


@test("stop_note: no file at all gives '' (never raises)")
def _():
    keeper.STOP_FILE.unlink(missing_ok=True)
    assert keeper.stop_note() == ""


@test("stop_waiting (the fresh start's own check) keeps the note for its log line")
def _():
    keeper.STOP_FILE.write_text(json.dumps(NOTE), encoding="utf-8")
    assert keeper.stop_waiting() is True and not keeper.STOP_FILE.exists()
    assert "by keepers window key S" in keeper.LAST_STOP_NOTE


def _read(name: str) -> str:
    return (LAUNCH / name).read_text(encoding="utf-8")


@test("launcher scripts: one fort list (keepers-common.ps1) dot-sourced by the window and the watchdog")
def _():
    common = _read("keepers-common.ps1")
    assert common.count("Preset = ") == 6 and "keeper-owner-stop.json" in common
    for name in ("start-keepers.ps1", "keeper-watchdog.ps1"):
        text = _read(name)
        assert "keepers-common.ps1')" in text and "$Forts = @(" not in text, name
        assert "Start-Process -FilePath 'cmd.exe'" not in text, name    # the start command: the common file only


@test("the window's S asks Y and writes who/why stop files and the owner-stop marker; R clears it")
def _():
    text = _read("start-keepers.ps1")
    stop = text[text.index("function Stop-All"):text.index("function Kill-Stuck")]
    assert "Stop all six keepers? (Y/N)" in stop and "'keepers window key S'" in stop
    assert stop.index("Set-OwnerStop") < stop.index("Write-StopFile")    # the marker first
    start = text[text.index("function Start-Missing"):text.index("function Stop-All")]
    assert "Clear-OwnerStop" in start
    assert "'R' {" in text and "Start-Missing" in text[text.index("'R' {"):]


@test("the watchdog: skips an owner-stopped fort, starts others the common way, the status past 55 min, a log")
def _():
    text = _read("keeper-watchdog.ps1")
    assert "Get-OwnerStop" in text and "Start-KeeperProcess $f" in text and "Test-Running $f" in text
    assert "$StatusMaxMin = 55" in text and "Start-StatusOnce" in text and "watchdog.log" in text
    inst = _read("install-watchdog-task.ps1")
    for need in ("Register-ScheduledTask", "Unregister-ScheduledTask", "-LogonType Interactive",
                 "-RepetitionInterval (New-TimeSpan -Minutes 5)", "-WindowStyle Hidden -NoProfile",
                 "-ExecutionPolicy Bypass", "[switch]$Remove", "keeper-watchdog.ps1"):
        assert need in inst, need


@test("the PowerShell files' brackets balance outside strings and comments (a rough parse: no pwsh here)")
def _():
    for p in LAUNCH.glob("*.ps1"):
        depth = {"{": 0, "(": 0, "[": 0}
        close = {"}": "{", ")": "(", "]": "["}
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            line = re.sub(r"'[^']*'", "''", line)            # single-quoted: literal
            line = re.sub(r'`.', "", line)                     # backtick escapes
            line = line.split("#", 1)[0] if '"' not in line.split("#", 1)[0] or line.lstrip().startswith("#") \
                else line
            for ch in line:
                if ch in depth:
                    depth[ch] += 1
                elif ch in close:
                    depth[close[ch]] -= 1
                    assert depth[close[ch]] >= 0, (p.name, n, line)
        assert all(v == 0 for v in depth.values()), (p.name, depth)


if __name__ == "__main__":
    finish()
