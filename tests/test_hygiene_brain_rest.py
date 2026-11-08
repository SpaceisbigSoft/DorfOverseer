"""(0.105.25, 13c brain-rest) The shared helpers (brain/util.py,
dfhack.read_config), the one-autopilot lock, the cached player memory, the
panel report sent only when it changed, and the action words.

    python tests/test_hygiene_brain_rest.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

TMP = Path(tempfile.mkdtemp())
os.environ.setdefault("DFAI_LOG_DIR", str(TMP / "logs"))

import dfhack  # noqa: E402
import keeper  # noqa: E402
import learning  # noqa: E402
import ledger  # noqa: E402
import overseer  # noqa: E402
import util  # noqa: E402
from planner import Memory  # noqa: E402

learning.PLAYER_FILE = TMP / "player-memory.json"
RESULTS = []


def test(name):
    def wrap(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            import traceback
            RESULTS.append((name, False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"))
        return fn
    return wrap


@test("load_json: the file, else the default (missing, broken, or another type than the default)")
def _():
    p = TMP / "x.json"
    assert util.load_json(p, {}) == {} and util.load_json(p) is None
    p.write_text("{broken", encoding="utf-8")
    assert util.load_json(p, {"a": 1}) == {"a": 1}
    p.write_text("[1, 2]", encoding="utf-8")
    assert util.load_json(p, {}) == {} and util.load_json(p, []) == [1, 2] and util.load_json(p) == [1, 2]
    p.write_text('{"k": 3}', encoding="utf-8")
    assert util.load_json(p, {}) == {"k": 3}


@test("the clock: date_tick is lenient, state_tick strict, both year * 403200 + tick")
def _():
    assert util.YEAR_TICKS == 403200
    assert util.date_tick({"year": 2, "tick": 5}) == 806405
    assert util.date_tick(None) == 0 and util.date_tick({"year": None}) == 0
    assert util.state_tick({"date": {"year": 1, "tick": 7}}) == 403207
    try:
        util.state_tick({})
        raise AssertionError("a report without its date should raise")
    except KeyError:
        pass
    import planner
    assert util.YEAR_TICKS == planner.TICKS_PER_YEAR
    assert util.state_tick({"date": {"year": 3, "tick": 9}}) == planner.abs_tick({"date": {"year": 3, "tick": 9}})


@test("read_config: config.json as a dict, {} when missing or broken; follows dfhack.CONFIG_PATH")
def _():
    old = dfhack.CONFIG_PATH
    try:
        dfhack.CONFIG_PATH = TMP / "no-config.json"
        assert dfhack.read_config() == {}
        cfg = TMP / "config.json"
        cfg.write_text(json.dumps({"df_launch": "steam://rungameid/1", "dfhack_port": 5001}), encoding="utf-8")
        dfhack.CONFIG_PATH = cfg
        assert dfhack.read_config()["df_launch"] == "steam://rungameid/1"
        import revive
        assert revive.launch_command() == "steam://rungameid/1"
        assert dfhack.configured_port(cfg) == 5001
        cfg.write_text("[]", encoding="utf-8")
        assert dfhack.read_config() == {} and revive.launch_command() is None
    finally:
        dfhack.CONFIG_PATH = old


def run_overseer(argv, bridge_factory):
    real = (overseer.Bridge, sys.argv)
    overseer.Bridge = bridge_factory
    sys.argv = ["overseer.py"] + argv
    try:
        return overseer.main()
    finally:
        overseer.Bridge, sys.argv = real


class StopAtHandshake:
    """A game that stops the overseer (Ctrl-C) as soon as it connects,
    noting whether a keeper could have started meanwhile."""
    keeper_could_start = None

    def handshake(self):
        lock = keeper.single_instance()
        StopAtHandshake.keeper_could_start = lock is not None
        if lock is not None:
            lock.close()
        raise KeyboardInterrupt


@test("one autopilot per folder: a manual --autopilot refuses beside a keeper, and a keeper beside it")
def _():
    lock = keeper.single_instance()
    assert lock is not None
    try:
        assert run_overseer(["--autopilot"], lambda: (_ for _ in ()).throw(AssertionError("connected"))) == 1
    finally:
        lock.close()
    # running, it holds the keeper's lock: a keeper started now refuses
    assert run_overseer(["--autopilot"], StopAtHandshake) == 0
    assert StopAtHandshake.keeper_could_start is False
    # and lets go when it stops
    lock = keeper.single_instance()
    assert lock is not None
    lock.close()


@test("one autopilot per folder: a dry run, and the keeper's own overseer (DFAI_PIN), don't take the lock")
def _():
    lock = keeper.single_instance()
    assert lock is not None
    try:
        StopAtHandshake.keeper_could_start = None
        assert run_overseer([], StopAtHandshake) == 0               # dry run: watches beside the keeper
        assert StopAtHandshake.keeper_could_start is False          # (the keeper's lock still held: by the test)
        os.environ["DFAI_PIN"] = "1"
        try:
            assert run_overseer(["--autopilot", "--unattended"], StopAtHandshake) == 0
        finally:
            del os.environ["DFAI_PIN"]
    finally:
        lock.close()


@test("player memory: read once until the file changes; copy=True is the caller's own")
def _():
    learning.PLAYER_FILE.unlink(missing_ok=True)
    assert learning.load_player() == {"version": 1, "lessons": {}}
    learning.save_player({"version": 1, "lessons": {"a": {"forts": {}}}})
    a = learning.load_player()
    assert a["lessons"] == {"a": {"forts": {}}}
    assert learning.load_player() is a                               # not read again
    c = learning.load_player(copy=True)
    c["lessons"]["b"] = 1
    assert "b" not in learning.load_player()["lessons"]
    learning.save_player({"version": 1, "lessons": {"z": {"forts": {}}}, "wiped": "x"})
    assert set(learning.load_player()["lessons"]) == {"z"}             # written: read afresh
    # another program writing the file is seen too (size or time changed)
    learning.PLAYER_FILE.write_text(json.dumps({"version": 1, "lessons": {"q": {}, "r": {}}}), encoding="utf-8")
    assert set(learning.load_player()["lessons"]) == {"q", "r"}
    learning.PLAYER_FILE.write_text("{broken", encoding="utf-8")
    assert learning.load_player() == {"version": 1, "lessons": {}}
    learning.PLAYER_FILE.unlink()


class Panel:
    def __init__(self):
        self.sent = []

    def act(self, a):
        self.sent.append(a)
        return {"ok": True}


@test("the panel's report: not sent again unchanged; sent when it changes, to a new bridge, or after a while")
def _():
    clock = [1000.0]
    real = overseer.time.monotonic
    overseer.time.monotonic = lambda: clock[0]
    overseer.STATUS_SENT.clear()
    try:
        b = Panel()
        overseer.report_status(b, {"date": "1 Granite y1"})
        overseer.report_status(b, {"date": "1 Granite y1"})
        assert len(b.sent) == 1
        overseer.report_status(b, {"date": "2 Granite y1"})
        assert len(b.sent) == 2
        b2 = Panel()
        overseer.report_status(b2, {"date": "2 Granite y1"})          # reconnected: sent again
        assert len(b2.sent) == 1
        clock[0] += overseer.STATUS_REFRESH_S
        overseer.report_status(b2, {"date": "2 Granite y1"})          # a reloaded game forgot it
        assert len(b2.sent) == 2
    finally:
        overseer.time.monotonic = real
        overseer.STATUS_SENT.clear()


@test("action words: every word and co-pilot question is a real bridge action; the planner's have words")
def _():
    lua = "".join(f.read_text(encoding="utf-8") for f in sorted((ROOT / "lua").glob("ai-bridge*.lua")))  # the bridge is split (13c)
    acts = set(re.findall(r"(\w+)\s*=\s*act_\w+", lua)) | set(re.findall(r"^\s+(\w+) = function\(a\)", lua, re.M))
    assert set(overseer.SHORT_WORDS) <= acts, set(overseer.SHORT_WORDS) - acts
    assert overseer.BIG_MOVES <= acts, overseer.BIG_MOVES - acts
    for t in ("break_fights", "build_crossing", "remove_crossing", "free_dig_jobs", "trim_instrument_orders"):
        assert overseer.short({"type": t}) != t, t
    assert overseer.short({"type": "set_population_cap", "cap": 80}) == "set the population cap to 80"
    assert overseer.short({"type": "census"}) == "count what fills the map"
    assert overseer.short({"type": "something_new"}) == "something_new"


@test("squad memory survives a reload: squads_trained and squads_rested are in the ledger")
def _():
    assert "squads_trained" in ledger.FIELDS and "squads_rested" in ledger.FIELDS
    lua = "".join(f.read_text(encoding="utf-8") for f in sorted((ROOT / "lua").glob("ai-bridge*.lua")))  # the bridge is split (13c)
    assert "squads_trained = true" in lua and "squads_rested = true" in lua
    m = Memory()
    m.squads_trained, m.squads_rested = [4, 9], [9]
    snap = json.loads(json.dumps(ledger.snapshot(m)))                  # as the save keeps it
    m2 = Memory()
    assert ledger.apply(m2, snap)
    assert m2.squads_trained == [4, 9] and m2.squads_rested == [9]


@test("brain/tools: the one-off scripts find the brain's modules from their new folder")
def _():
    tools = ROOT / "brain" / "tools"
    names = sorted(p.name for p in tools.glob("*.py"))
    assert {"try_actions.py", "try_building.py", "token_test.py"} <= set(names), names
    for p in tools.glob("*.py"):
        src = p.read_text(encoding="utf-8")
        compile(src, str(p), "exec")
        assert "resolve().parent.parent" in src, p.name
    # what the player runs by name stays where it was
    for name in ("probe_missions.py", "probe_trade.py", "probe_meeting.py", "scorecard.py", "keeper.py",
                 "overseer.py", "selftest.py", "health_check.py", "scenario.py", "replay.py", "defence_test.py",
                 "check_ai.py", "check_connection.py", "show_fort.py"):
        assert (ROOT / "brain" / name).exists(), name


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
