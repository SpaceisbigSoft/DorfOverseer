"""(x3, V7) The fallen mark holds only the fort and date it names.

DF loads every save paused, and while a fallen mark stands the overseer's
loop neither unpauses nor runs a cycle (where fallen.note would end the
fall). So the loop checks the mark against the game loaded now
(fallen.idle(status, probe)): another fort, an earlier save, or citizens back
end it at once, and the loop unpauses and plans as usual; only the unchanged
fallen fort stays idle. The keeper holds only for a mark of its pinned fort.

Built from the run's data: fort F (Hammerstirred, world Usnuspbuzong, site
1430, fell 18 Slate y256 at tick 55000, `autosave 1`).

    python tests/test_x3_fallen.py
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp())
os.environ["DFAI_LOG_DIR"] = str(TMP / "logs")
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))

import fallen  # noqa: E402
import memstore  # noqa: E402
import overseer  # noqa: E402
import pin  # noqa: E402
import revive  # noqa: E402
from bridge import BridgeError  # noqa: E402
from dfhack import GameNotRunning  # noqa: E402

LOGS = TMP / "logs"
LOGS.mkdir(parents=True, exist_ok=True)
memstore.FORTS_DIR = TMP / "forts"
fallen.LOG_DIR = LOGS
pin.PIN_FILE = LOGS / "keeper-pin.json"

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
F_FORT = {"name": "Hammerstirred", "save_dir": "autosave 1", "site_id": 1430, "world": "Usnuspbuzong"}
F_DATE = {"day": 18, "month": "Slate", "season": "spring", "tick": 55000, "year": 256}
F_KEY = "Usnuspbuzong#1430"
# another fort of the six (a living one, its citizens at work)
B_FORT = {"name": "Oiledhelms", "save_dir": "region2", "site_id": 87, "world": "Rithol Kosoth"}


def report(fort=F_FORT, date=F_DATE, citizens=0, queued=0):
    s = copy.deepcopy(BASE)
    s["fort"] = dict(fort)
    s["date"] = dict(date)
    s["dwarves"]["total"] = citizens
    s["migration"] = {"civ": True, "force": "force", "hermit_tool": False, "queued": queued}
    s["tier"] = "pulse"
    return s


def reset():
    overseer.MEMORY_CACHE.clear()
    memstore.ALIASES.clear()
    fallen.STATE.clear()
    fallen.STATE.update(mark=None, dismissed=None)
    fallen.mark_path().unlink(missing_ok=True)
    pin.PIN_FILE.unlink(missing_ok=True)


def mark_f(**extra):
    """F's mark as fallen.note writes it (18 Slate y256)."""
    m = {"fort": F_KEY, "world": "Usnuspbuzong", "site": 1430, "save_dir": "autosave 1", "run": "r-f",
         "name": "Hammerstirred", "date": dict(F_DATE), "tick": 256 * 403200 + 55000,
         "since": "2026-11-16T01:47:00", "why": "no citizens left and no migrant wave on its way",
         "folder": None}
    m.update(extra)
    fallen.mark_path().write_text(json.dumps(m), encoding="utf-8")
    return m


class LoopGame:
    """The game for the overseer's main loop: loaded paused (as DF loads every
    save), unpaused by the 'unpause' action; the report it would send."""
    version = {"recipes": [], "tools": []}

    def __init__(self, rep, fail_state=False):
        self.rep, self.paused, self.acted, self.reads = rep, True, [], 0
        self.fail_state = fail_state

    def handshake(self):
        return {"bridge_version": "x", "dfhack_version": "53.17-r1"}

    def status(self):
        return {"ok": True, "in_fort": True, "paused": self.paused, "date": dict(self.rep["date"]),
                "halted": False, "decisions": {}, "fps": 100, "events_waiting": 0}

    def state(self, include_units=True, tier=None):
        self.reads += 1
        if self.fail_state:
            raise BridgeError("the report failed")
        return copy.deepcopy(self.rep)

    def act(self, a):
        self.acted.append(a)
        if a.get("type") == "unpause":
            self.paused = False
        return {"ok": True}


def run_loop(game, polls=40, argv=("--autopilot", "--unattended")):
    """Run overseer.main() on `game` for at most `polls` polls (2 s of a fake
    clock each); stop at the first cycle. Returns (cycles, said)."""
    clock = [5000.0]
    cycles, said, n = [], [], [0]
    real = (overseer.Bridge, sys.argv, overseer.one_cycle, overseer._leave_open, overseer.say,
            time.sleep, time.monotonic)

    def sleep(s):
        n[0] += 1
        clock[0] += s
        if n[0] >= polls:
            raise KeyboardInterrupt

    def one_cycle(bridge, autopilot, backend=None, controls=None, tier="daily", **kw):
        cycles.append({"tier": tier, "paused": game.paused})
        raise KeyboardInterrupt

    overseer.Bridge = lambda: game
    sys.argv = ["overseer.py", *argv]
    overseer.one_cycle, overseer._leave_open, overseer.say = one_cycle, (lambda b: None), said.append
    time.sleep, time.monotonic = sleep, (lambda: clock[0])
    os.environ["DFAI_PIN"] = "1"           # the keeper's own overseer: no folder lock taken
    try:
        overseer.main()
    finally:
        (overseer.Bridge, sys.argv, overseer.one_cycle, overseer._leave_open, overseer.say,
         time.sleep, time.monotonic) = real
        os.environ.pop("DFAI_PIN", None)
    return cycles, said


# ------------------------------------------------------------------ the overseer's loop

@test("loop: F's mark and another, living fort loaded paused: the mark lapses, the game is unpaused and planned")
def _():
    reset()
    mark_f()
    pin.PIN_FILE.write_text(json.dumps({"world": B_FORT["world"], "site": "87", "save_dir": "region2"}))
    game = LoopGame(report(fort=B_FORT, date={"day": 3, "month": "Granite", "tick": 2400, "year": 301},
                           citizens=31))
    cycles, said = run_loop(game)
    assert fallen.current() is None and not fallen.mark_path().exists(), said
    assert any("fall is over (another fort is loaded" in x for x in said), said
    assert {"type": "unpause"} in game.acted, game.acted
    assert cycles and not cycles[0]["paused"], (cycles, said)
    assert not any("left paused until you act" in x for x in said), said


@test("loop: F's own earlier save (an autosave of 1 Granite) lapses the mark from the status alone")
def _():
    reset()
    mark_f()
    game = LoopGame(report(date={"day": 1, "month": "Granite", "tick": 1200, "year": 256}, citizens=14))
    cycles, said = run_loop(game)
    assert fallen.current() is None, said
    assert any("an earlier date is loaded" in x for x in said), said
    assert game.reads == 0, "the status's date was enough: no report read"
    assert {"type": "unpause"} in game.acted and cycles, (game.acted, said)


@test("loop: the fallen fort with its citizens back (migrants arrived, game paused): unpaused and planned")
def _():
    reset()
    mark_f()
    game = LoopGame(report(date=dict(F_DATE, tick=56200), citizens=7))
    cycles, said = run_loop(game)
    assert fallen.current() is None, said
    assert any("7 citizen(s) in the fort again" in x for x in said), said
    assert {"type": "unpause"} in game.acted and cycles, (game.acted, said)


@test("loop: the unchanged fallen fort stays idle (not unpaused, no cycle) and its report is read only now and then")
def _():
    reset()
    mark_f()
    game = LoopGame(report(citizens=0))
    cycles, said = run_loop(game, polls=60)        # 2 minutes of polls
    assert fallen.current() is not None
    assert not cycles and not [a for a in game.acted if a.get("type") == "unpause"], (game.acted, said)
    assert sum("left paused until you act" in x for x in said) == 1, said
    assert 2 <= game.reads <= 6, f"the pulse read {game.reads} times in 2 minutes (every 30 s wanted)"


@test("idle: the fallen fort running (the player unpaused it): its report read every 30 s, not every poll")
def _():
    reset()
    mark_f()
    clock, reads = [100.0], []
    real = time.monotonic
    time.monotonic = lambda: clock[0]
    try:
        for i in range(30):                    # 60 s of polls, the date moving each one
            st = {"in_fort": True, "paused": False, "date": dict(F_DATE, tick=55000 + 20 * i)}
            assert fallen.idle(st, lambda: reads.append(1) or (report(citizens=0), F_KEY), print)
            clock[0] += 2
    finally:
        time.monotonic = real
    assert 2 <= len(reads) <= 3, len(reads)


@test("loop: the report can't be read: the mark stands (nothing told), the game left as it is")
def _():
    reset()
    mark_f()
    game = LoopGame(report(fort=B_FORT, citizens=31), fail_state=True)
    cycles, said = run_loop(game, polls=20)
    assert fallen.current() is not None and not cycles
    assert not [a for a in game.acted if a.get("type") == "unpause"], game.acted


@test("idle: a fault in the check lets the game run (never a living fort held paused by it)")
def _():
    reset()
    mark_f()
    said = []

    def bad():
        raise ValueError("odd report")
    st = {"in_fort": True, "paused": True, "date": dict(F_DATE)}
    assert fallen.idle(st, bad, said.append) is None
    assert any("couldn't be checked" in x for x in said), said
    assert fallen.idle() is not None, "the keeper's view: the mark itself is left"


@test("idle: without the status (the keeper) or with no fort loaded, the mark as it stands")
def _():
    reset()
    m = mark_f()
    assert fallen.idle()["fort"] == m["fort"]
    assert fallen.idle({"in_fort": False}, lambda: (_ for _ in ()).throw(AssertionError("read")))["fort"] == F_KEY


@test("after the loop ends a fall, one_cycle doesn't take it as dismissed: F falling again is marked again")
def _():
    reset()
    mark_f()
    said = []
    st = {"in_fort": True, "paused": True, "date": {"year": 256, "tick": 1200}}
    assert fallen.idle(st, None, said.append) is None
    assert fallen.STATE.get("mark") is None and fallen.STATE.get("dismissed") is None
    # (the earlier save played on, and fell too)
    later = report(date={"day": 9, "month": "Granite", "tick": 10000, "year": 256}, citizens=0)
    assert fallen.note(later, F_KEY, None, said.append) is True
    assert not any("was removed" in x for x in said), said
    assert fallen.current()["tick"] == 256 * 403200 + 10000


# ------------------------------------------------------------------ the keeper

class FakeDF:
    def __init__(self, state="down"):
        self.state, self.calls = state, []

    def run(self, *args):
        self.calls.append(args)
        if self.state == "down":
            raise GameNotRunning("no")
        if args[0] == "lua":
            return "NO-WORLD SITE="
        return '{"ok": true, "started": true}'


def reviver(state="down"):
    t = [1000.0]
    logs, launched = [], []
    df = FakeDF(state)
    rv = revive.Reviver(logs.append, dfhack=df, launcher=launched.append, clock=lambda: t[0])
    rv.candidates = lambda: (["region2"], None)
    rv.df_running = lambda: False
    rv.any_df = lambda: None
    rv.session_ending = lambda: None
    rv.own_folder = lambda: None
    return rv, t, df, logs, launched


@test("keeper: a mark of another fort than the pinned one doesn't stop the pinned fort being started")
def _():
    reset()
    revive.launch_command = lambda: "D:/DF-B/Dwarf Fortress.exe"
    mark_f()
    pin.PIN_FILE.write_text(json.dumps({"world": B_FORT["world"], "site": "87", "save_dir": "region2"}))
    rv, t, df, logs, launched = reviver("down")
    rv.seen_up = True
    for _ in range(30):
        rv.tick(); t[0] += 60
    assert launched, logs
    assert not any("has fallen" in x for x in logs), logs


@test("keeper: pinned to the fallen fort itself (or no pin), it is still held")
def _():
    for p in ({"world": "Usnuspbuzong", "site": "1430", "save_dir": "autosave 1"}, None):
        reset()
        revive.launch_command = lambda: "D:/DF-F/Dwarf Fortress.exe"
        mark_f()
        if p:
            pin.PIN_FILE.write_text(json.dumps(p))
        rv, t, df, logs, launched = reviver("down")
        rv.seen_up = True
        for _ in range(30):
            rv.tick(); t[0] += 60
        assert not launched and sum("has fallen" in x for x in logs) == 1, (p, logs)


@test("holds_for: by the mark's world and site, or its key when it has none")
def _():
    assert fallen.holds_for({"fort": F_KEY}, {"world": "Usnuspbuzong", "site": "1430"})
    assert not fallen.holds_for({"fort": F_KEY}, {"world": "Usnuspbuzong", "site": "88"})
    assert not fallen.holds_for({"fort": "Usnuspbuzong@run7#1430"}, {"world": "Other", "site": "1430"})
    assert fallen.holds_for({"fort": "Usnuspbuzong@run7#1430"}, {"world": "Usnuspbuzong", "site": 1430})
    assert fallen.holds_for({"fort": F_KEY}, None) and not fallen.holds_for(None, None)


if __name__ == "__main__":
    finish()
