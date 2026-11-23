"""(0.105.77) A keeper with no console stopped by logs/keeper-stop.

The player (22 Nov 23:19): one easy-to-read window for the six keepers, not six
consoles. start-keepers.ps1 runs them hidden, where Ctrl-C can't reach them;
it writes each fort's logs/keeper-stop instead, and the keeper stops as Ctrl-C
stops it (the overseer ended, the fort left open, the summary and the status).

    python tests/test_r77_keeper_stop.py
"""

from __future__ import annotations

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
LEFT = []


def _no_bridge():
    LEFT.append(1)
    raise RuntimeError("no game in tests")


keeper.LEAVE_BRIDGE = _no_bridge


class Hanging:
    """An overseer that runs on; the keepers' window asks the keeper to stop meanwhile."""
    def __init__(self):
        self.stdout = iter([])
        self.killed = False
        self.polls = 0

    def poll(self):
        self.polls += 1
        if self.polls == 1:
            keeper.STOP_FILE.write_text("stop", encoding="utf-8")
        return None if not self.killed else 0

    def kill(self):
        self.killed = True


@test("logs/keeper-stop during a run: the overseer killed, the fort left open, the file removed, the keeper "
      "returns 0 and says why in the log and the status")
def _():
    procs = []

    def popen(cmd, **kw):
        procs.append(Hanging())
        return procs[-1]
    keeper.EXTRAS.pop("run_start", None)
    code = keeper.main([], popen=popen, sleep=lambda s: None, max_runs=5)
    assert code == 0 and len(procs) == 1 and procs[0].killed
    assert not keeper.STOP_FILE.exists() and LEFT
    log = keeper.LOG.read_text(encoding="utf-8")
    assert "asked to stop (logs/keeper-stop" in log and "Keeper stopped (asked by the keepers' window)" in log, log
    assert "asked by the keepers' window" in keeper.STATUS.read_text(encoding="utf-8")


@test("an old keeper-stop left from before is removed at the start: it never stops a new run")
def _():
    keeper.STOP_FILE.write_text("old", encoding="utf-8")
    started = []

    class Quick:
        stdout = iter([])

        def poll(self):
            return 1

        def kill(self):
            pass

    def popen(cmd, **kw):
        started.append(cmd)
        return Quick()
    code = keeper.main([], popen=popen, sleep=lambda s: None, max_runs=2)
    assert code == 0 and len(started) == 2 and not keeper.STOP_FILE.exists()


@test("stop_asked: no file, nothing; StopAsked is a KeyboardInterrupt (the Ctrl-C path)")
def _():
    keeper.STOP_FILE.unlink(missing_ok=True)
    keeper.stop_asked()
    assert issubclass(keeper.StopAsked, KeyboardInterrupt)


if __name__ == "__main__":
    finish()
