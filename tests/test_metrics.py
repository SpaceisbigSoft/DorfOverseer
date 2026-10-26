"""Tests for brain/metrics.py and the game-free parts of brain/scenario.py.

    python tests/test_metrics.py
"""

from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

import metrics  # noqa: E402
import scenario  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
RESULTS = []
TMP = Path(tempfile.mkdtemp())


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


DEATH = {"kind": "death", "own_civ": True, "animal": False}
CAT_DEATH = {"kind": "death", "own_civ": True, "animal": True}
MIGRANT = {"kind": "arrival", "own_civ": True, "hostile": False}
GOBLIN = {"kind": "arrival", "own_civ": False, "hostile": True}


@test("a day's row from the test fort")
def _():
    r = metrics.day_row(3, BASE, [DEATH, CAT_DEATH, MIGRANT, MIGRANT, GOBLIN], ai_actions=2, fps=48)
    assert r["day"] == 3 and r["date"] == "25 Moonstone 148"
    assert r["population"] == 194 and r["adults"] == 167
    assert r["idle_pct"] == round(100 * 43 / 167, 1)
    assert r["unhappy"] == 5 and r["unhappy_pct"] == round(500 / 194, 1)
    assert r["happy_pct"] == round(100 * (59 + 95) / 194, 1)
    assert r["wealth"] == 16769099
    assert r["drink_per_dwarf"] == round(3929 / 194, 1)
    assert r["citizen_deaths"] == 1 and r["arrivals"] == 2
    assert r["ai_actions"] == 2 and r["fps"] == 48
    assert set(r) == set(metrics.FIELDS), set(r) ^ set(metrics.FIELDS)


@test("announcement events are counted per day and summed per run")
def _():
    rep = lambda topic: {"kind": "report", "topic": topic}  # noqa: E731
    r1 = metrics.day_row(1, BASE, [rep("mood"), rep("tantrum"), rep("tantrum")])
    r2 = metrics.day_row(2, BASE, [rep("artifact_made"), rep("ghost")])
    assert (r1["moods"], r1["tantrums"], r2["artifacts"], r2["ghosts"]) == (1, 2, 1, 1)
    s = metrics.summarize([r1, r2])
    assert s["moods"] == 1 and s["tantrums"] == 2 and s["artifacts"] == 1 and s["crimes"] == 0


@test("a report with missing sections still gives a row (no crash, zeros)")
def _():
    r = metrics.day_row(1, {"date": BASE["date"]}, [])
    assert r["population"] == 0 and r["idle_pct"] == 0.0 and r["wealth"] is None
    assert r["drink_per_dwarf"] == 0 and r["projects_open"] == 0


def rows_for(pops, wealths):
    out = []
    for i, (p, w) in enumerate(zip(pops, wealths), 1):
        s = copy.deepcopy(BASE)
        s["dwarves"]["total"] = p
        s["wealth"] = w
        out.append(metrics.day_row(i, s, [DEATH] if i == 2 else []))
    return out


@test("summary: start/end/min population, deaths, wealth change")
def _():
    s = metrics.summarize(rows_for([10, 9, 12], [1000, 900, 1500]), "a", "planner", False)
    assert s["days"] == 3 and s["population_start"] == 10 and s["population_end"] == 12
    assert s["population_min"] == 9 and s["citizen_deaths"] == 1
    assert s["wealth_change_pct"] == 50.0 and s["fell"] is False
    assert s["new_citizens"] == 3, s["new_citizens"]   # day 2: one died, none joined; day 3: +3
    assert metrics.summarize([], "x", "none")["days"] == 0


@test("comparison marks the better run on each line")
def _():
    a = metrics.summarize(rows_for([10, 10], [1000, 2000]), "planner-a", "planner")
    b = metrics.summarize(rows_for([10, 8], [1000, 1100]), "base-a", "baseline")
    table = metrics.compare_table([a, b])
    lines = {ln[:32].strip(): ln[32:] for ln in table.splitlines()[1:]}
    assert "*" in lines["Population: end"].split()[1] or lines["Population: end"].count("*") == 1
    pe = lines["Population: end"]
    assert pe.index("*") < len(pe) // 2, pe           # planner's column (first) is better
    assert "*" not in lines["Days played"]            # no "better" for days
    assert "planner-a (planner)" in table.splitlines()[0]


@test("rows survive the CSV round trip with numbers as numbers")
def _():
    path = TMP / "m.csv"
    rows = rows_for([10, 9], [1000, None])
    for r in rows:
        metrics.write_row(path, r)
    back = metrics.read_rows(path)
    assert len(back) == 2 and back[0]["population"] == 10 and back[1]["wealth"] is None
    assert isinstance(back[0]["idle_pct"], float) and back[0]["date"] == "25 Moonstone 148"


class DayBridge:
    """Pretends to be the game: run_ticks + wait_for_run advance the clock, but
    the game 'pauses itself' (an announcement) after only part of the first run."""

    def __init__(self, interrupt_after=None):
        self.tick = 1000
        self.interrupt_after = interrupt_after
        self.runs = []

    def status(self):
        return {"in_fort": True, "date": {"year": 148, "tick": self.tick}}

    def run_ticks(self, n):
        self.runs.append(n)
        self._pending = n

    def wait_for_run(self, n, on_stall=None):
        step = self._pending
        if self.interrupt_after is not None:
            step, self.interrupt_after = self.interrupt_after, None
        self.tick += step
        return self.status()

    def events(self):
        return [MIGRANT]


@test("one day passes exactly, even when DF pauses itself partway")
def _():
    b = DayBridge()
    assert scenario.run_one_day(b) and b.tick == 1000 + 1200 and b.runs == [1200]
    b = DayBridge(interrupt_after=500)
    assert scenario.run_one_day(b) and b.tick == 2200 and b.runs == [1200, 700], b.runs


@test("a very slow day (time limit hit) carries on instead of ending the run")
def _():
    from bridge import BridgeError
    b = DayBridge()
    real = b.wait_for_run
    calls = []

    def slow(n, on_stall=None):
        calls.append(n)
        if len(calls) == 1:
            b.tick += 300
            raise BridgeError("run of 1200 ticks did not finish in time; game paused")
        return real(n)
    b.wait_for_run = slow
    scenario.say = lambda m: None
    assert scenario.run_one_day(b) and b.tick == 2200 and calls == [1200, 900], calls


@test("the event tap passes events on and keeps a copy for the day's record")
def _():
    tap = scenario.EventTap(DayBridge())
    assert tap.events() == [MIGRANT] and tap.events() == [MIGRANT]
    assert tap.take() == [MIGRANT, MIGRANT] and tap.take() == []
    assert tap.status()["in_fort"]                    # everything else goes straight through


@test("only real changes count as AI actions (not panel updates, failures or dry runs)")
def _():
    ds = [{"kind": "decision", "action": {"type": "work_order"}, "result": {"ok": True}},
          {"kind": "decision", "action": {"type": "report_status"}, "result": {"ok": True}},
          {"kind": "decision", "action": {"type": "tool"}, "result": {"ok": False}},
          {"kind": "decision", "action": {"type": "tool"}, "result": None},
          {"kind": "event", "event": {}}]
    assert scenario.count_actions(ds) == 1


@test("decisions are read a day at a time from the run's journal")
def _():
    j = TMP / "d.jsonl"
    j.write_text('{"kind":"decision","n":1}\n', encoding="utf-8")
    got, pos = scenario.new_decisions(j, 0)
    assert [d["n"] for d in got] == [1]
    with j.open("a", encoding="utf-8") as f:
        f.write('{"kind":"decision","n":2}\n')
    got, pos = scenario.new_decisions(j, pos)
    assert [d["n"] for d in got] == [2]
    assert scenario.new_decisions(TMP / "none.jsonl", 0) == ([], 0)


@test("only saves named like a test are played without --yes")
def _():
    assert scenario.looks_like_test("region3-test") and scenario.looks_like_test("AI Run A")
    assert not scenario.looks_like_test("region1")


class GameForRun:
    """A whole fake game for scenario run: the clock moves when asked, drink
    runs low so the planner has something to do, and a migrant shows up."""
    version = {"recipes": ["brew_drink", "stone_blocks", "prepare_fine_meal"],
               "tools": ["autochop", "seedwatch", "suspendmanager"]}

    def __init__(self):
        self._state = copy.deepcopy(BASE)
        self._state["stocks"]["drink"] = 10
        self._events = [MIGRANT]
        self.acted = []

        class _DF:
            def run(self, *args):
                return ""
        self.df = _DF()

    def handshake(self):
        return {"protocol": 1, "bridge_version": "test"}

    def status(self):
        return {"ok": True, "in_fort": True, "halted": False, "decisions": {}, "fps": 60,
                "date": dict(self._state["date"])}

    def state(self, include_units=True):
        return copy.deepcopy(self._state)

    def events(self):
        ev, self._events = self._events, []
        return ev

    def act(self, a):
        self.acted.append(a)
        return {"ok": True, "order_id": 1}

    def run_ticks(self, n):
        self._run = n

    def wait_for_run(self, n, on_stall=None):
        self._state["date"]["tick"] += self._run
        return self.status()


@test("a whole scenario run: plays day by day, records rows, decisions, summary")
def _():
    import overseer
    overseer.memstore.FORTS_DIR = TMP / "forts"
    overseer.memstore.LEGACY_FILE = TMP / "memory.json"
    overseer.learning.PLAYER_FILE = TMP / "player-memory.json"
    overseer.STOP_FILE = TMP / "STOP"
    overseer.say = lambda m: None
    scenario.say = lambda m: None
    scenario.RUNS_DIR = TMP / "runs"
    game = GameForRun()
    scenario.Bridge = lambda: game
    args = type("A", (), {"days": 3, "years": 0, "mode": "planner", "label": "t 1", "yes": False})()
    with redirect_stdout(io.StringIO()):
        assert scenario.cmd_run(args) == 0
    run = next((TMP / "runs").iterdir())
    assert run.name.endswith("-t-1"), run.name
    rows = metrics.read_rows(run / "metrics.csv")
    assert [r["day"] for r in rows] == [1, 2, 3] and rows[0]["fps"] == 60
    assert rows[0]["arrivals"] == 1 and rows[1]["arrivals"] == 0
    assert any(a.get("recipe") == "brew_drink" for a in game.acted), game.acted
    assert rows[0]["ai_actions"] >= 1, rows[0]
    days = [json.loads(x) for x in (run / "days.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(days) == 3 and days[0]["events"] == [MIGRANT] and days[0]["decisions"]
    summ = metrics.load_summary(run)
    assert summ["days"] == 3 and summ["mode"] == "planner" and summ["new_citizens"] == 0
    assert json.loads((run / "run.json").read_text())["save_dir"] == BASE["fort"]["save_dir"]


@test("compare recomputes summaries, so older runs get newer measures")
def _():
    run = TMP / "old-run"
    run.mkdir()
    rows = rows_for([10, 10, 15], [1000, 1000, 1000])
    for r in rows:
        metrics.write_row(run / "metrics.csv", r)
    old = metrics.summarize(rows, "old", "planner")
    del old["new_citizens"]
    (run / "summary.json").write_text(json.dumps(old), encoding="utf-8")
    s = scenario.fresh_summary(run)
    assert s["new_citizens"] == 6 and s["label"] == "old", s   # day 2: one died and one joined; day 3: +5


@test("a run refuses a save that isn't named like a test")
def _():
    game = GameForRun()
    game._state["fort"]["save_dir"] = "region1"
    scenario.Bridge = lambda: game
    args = type("A", (), {"days": 1, "years": 0, "mode": "none", "label": "", "yes": False})()
    assert scenario.cmd_run(args) == 1 and game.acted == []



@test("scenario (0.100): a stalled run takes the popup off; announcements quieted at the start")
def _():
    import scenario
    said, acts = [], []

    class B:
        def __init__(self, reply): self.reply = reply
        def act(self, a): acts.append(a); return self.reply
    old = scenario.say
    scenario.say = said.append
    try:
        scenario.clear_popups(B({"ok": True, "popups_cleared": 1}))
        assert acts[-1] == {"type": "unpause", "unstick": True} and "taken off" in said[-1], said
        scenario.clear_popups(B({"ok": True, "popups_cleared": 0}))
        assert "menu or screen" in said[-1], said
        scenario.clear_popups(B({"ok": False, "rejected": True, "error": "halted"}))
        assert "halted" in said[-1], said
        scenario.quiet_announcements(B({"ok": True, "pausing": 12, "boxes": 3}))
        assert acts[-1] == {"type": "quiet_announcements"} and "12 paused" in said[-1], said
    finally:
        scenario.say = old

if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
