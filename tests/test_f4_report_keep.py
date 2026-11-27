"""(F3a) The overseer's own reads stall the game: the last full report kept
after the AI acts, only the sections its actions changed read again; the
game's ticks a real second in perf.jsonl.

- brain/report_keep.py: an action's answer names the sections it changed
  (`invalidates`, the bridge's CACHE_INVALIDATES); those are marked stale in
  overseer.LAST_FULL and the next pulse asks for them (`--sections`); an
  answer that names none clears the kept report (the full one next cycle)
- brain/overseer.get_state: the pulse with the stale sections merged into the
  kept report; an older bridge (no `sections`, or a reply without them): the
  full report
- brain/perf.py: `tps` in each row (perf.game_tick over the real seconds)

The bridge's side (the deadline, --sections, `invalidates`) is in
tests/test_f4_report_deadline.py (lupa).

    python tests/test_f4_report_keep.py
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import memstore  # noqa: E402
import overseer  # noqa: E402
import perf  # noqa: E402
import report_keep  # noqa: E402
from bridge import Bridge  # noqa: E402

overseer.THROTTLE_MEMORY_SAVE = False
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
TMP = Path(tempfile.mkdtemp())
memstore.FORTS_DIR = TMP / "forts"
memstore.LEGACY_FILE = TMP / "overseer-memory.json"
overseer.say = lambda m: None
overseer.JOURNAL = TMP / "decisions.jsonl"


def _before():
    shutil.rmtree(memstore.FORTS_DIR, ignore_errors=True)
    overseer.LAST_FULL.clear()
    report_keep.KEEP_AFTER_ACTIONS = True


test = make_test(before=_before)


class Fake:
    """A bridge: the full report, the pulse, and the pulse with --sections."""
    version = {"recipes": ["brew_drink"], "tools": []}

    def __init__(self, reply=None, knows_sections=True, echo_sections=True):
        self.s = copy.deepcopy(BASE)
        self.s["stocks"]["drink"] = 10           # it will order drink
        self.s["tier"] = "daily"
        self.calls = []
        self.reply = reply if reply is not None else {"ok": True, "order_id": 7}
        self.knows = knows_sections
        self.echo = echo_sections

    def state(self, include_units=True, tier=None, **kw):
        if "sections" in kw and not self.knows:
            raise TypeError("state() got an unexpected keyword argument 'sections'")
        self.calls.append((tier, kw.get("sections")))
        out = copy.deepcopy(self.s)
        if tier == "pulse":
            keep = ["fort", "date", "stocks", "orders"]
            if self.echo:
                keep += list(kw.get("sections") or [])
            out = {k: out[k] for k in keep if k in out}
            out["tier"] = "pulse"
        return out

    def events(self):
        return []

    def act(self, a):
        return dict(self.reply)

    def status(self):
        return {"halted": False, "decisions": {}}


# --- report_keep: what the answers say ---------------------------------------------------

@test("F3a: the actions' answers give the changed sections; any answer that doesn't say gives None")
def _():
    assert report_keep.invalidated([(None, {"ok": True, "invalidates": ["needs"]}),
                                    (None, {"ok": True, "invalidates": ["needs", "dead"]})]) == ["needs", "dead"]
    assert report_keep.invalidated([(None, {"ok": False, "invalidates": {}})]) == []   # an empty Lua table
    assert report_keep.invalidated([(None, {"ok": True, "invalidates": ["needs"]}),
                                    (None, {"ok": True, "order_id": 7})]) is None      # an action the table doesn't know
    assert report_keep.invalidated([(None, {"ok": None, "error": "no reply"})]) is None
    assert report_keep.invalidated([(None, {"ok": True, "invalidates": [3]})]) is None
    assert report_keep.invalidated([]) == []


@test("F3a: after_actions marks the sections stale in the kept report, or clears it")
def _():
    lf = {"state": {"fort": "x"}}
    assert report_keep.after_actions(lf, [(None, {"ok": True, "invalidates": ["needs"]})]) == ["needs"]
    assert report_keep.after_actions(lf, [(None, {"ok": True, "invalidates": ["dead", "needs"]})]) == ["needs", "dead"]
    assert lf["state"] == {"fort": "x"} and report_keep.stale(lf) == ["needs", "dead"]
    assert report_keep.after_actions(lf, [(None, {"ok": True})]) is None and lf == {}
    lf = {}
    assert report_keep.after_actions(lf, [(None, {"ok": True, "invalidates": []})]) is None and lf == {}, "nothing kept"
    lf = {"state": {"fort": "x"}}
    report_keep.KEEP_AFTER_ACTIONS = False
    assert report_keep.after_actions(lf, [(None, {"ok": True, "invalidates": ["needs"]})]) is None and lf == {}


# --- the cycle and get_state -------------------------------------------------------------

@test("F3a: an action whose answer names its sections keeps the report; the next pulse asks only for those")
def _():
    b = Fake(reply={"ok": True, "order_id": 7, "invalidates": ["needs", "food_store"]})
    overseer.one_cycle(b, autopilot=True)                 # acts: orders drink
    assert overseer.LAST_FULL.get("state"), "the morning's report is kept"
    assert report_keep.stale(overseer.LAST_FULL) == ["needs", "food_store"]
    b.s["needs"] = {"marker": "fresh"}
    b.s["food_store"] = {"piles": 1}
    b.reply = {"ok": True, "invalidates": []}
    s = overseer.get_state(b, "pulse")
    assert b.calls[-1] == ("pulse", ["needs", "food_store"]), b.calls
    assert s["needs"] == {"marker": "fresh"} and s["tier"] == "pulse"
    assert overseer.LAST_FULL["state"]["needs"] == {"marker": "fresh"}, "merged into the kept report"
    assert report_keep.stale(overseer.LAST_FULL) == []
    assert "military" in s or "military" not in BASE           # the rest from the kept report
    overseer.get_state(b, "pulse")
    assert b.calls[-1] == ("pulse", None), "nothing stale: the plain pulse"


@test("F3a: an answer without invalidates (the old rule): the next pulse cycle reads the full report")
def _():
    b = Fake()
    overseer.one_cycle(b, autopilot=True)
    assert not overseer.LAST_FULL
    overseer.one_cycle(b, autopilot=True, tier="pulse")
    assert (None, None) in b.calls[1:], b.calls


@test("F3a: a bridge that doesn't know sections=, or leaves them out of the reply: the full report")
def _():
    for b in (Fake(knows_sections=False), Fake(echo_sections=False)):
        overseer.LAST_FULL.clear()
        overseer.get_state(b, "daily")
        overseer.LAST_FULL["stale"] = ["needs"]
        s = overseer.get_state(b, "pulse")
        assert b.calls[-1] == (None, None) and s["tier"] == "daily", b.calls
        assert "stale" not in overseer.LAST_FULL, "the full report read everything afresh"


@test("F3a: a daily report clears what was stale")
def _():
    b = Fake()
    overseer.get_state(b, "daily")
    overseer.LAST_FULL["stale"] = ["needs"]
    overseer.get_state(b, "daily")
    assert report_keep.stale(overseer.LAST_FULL) == []


@test("F3a: Bridge.state sends --sections only when asked")
def _():
    br = Bridge.__new__(Bridge)
    seen = []
    br._call = lambda *a, **kw: seen.append(a) or (_ for _ in ()).throw(RuntimeError("stop"))
    for kw in ({"tier": "pulse", "sections": ["needs", "dead"]}, {"tier": "pulse"}):
        try:
            br.state(include_units=False, **kw)
        except RuntimeError:
            pass
    assert seen[0] == ("state", "--no-units", "--tier", "pulse", "--sections", "needs,dead"), seen
    assert seen[1] == ("state", "--no-units", "--tier", "pulse"), seen


@test("F3a: the cycle's code marks the sections stale instead of clearing the kept report")
def _():
    src = (ROOT / "brain" / "overseer_cycle.py").read_text(encoding="utf-8")
    assert "report_keep.after_actions(_ov.LAST_FULL, results)" in src
    assert "_ov.LAST_FULL.clear()" not in src


# --- perf.jsonl: ticks a real second ----------------------------------------------------

@test("F3a: each perf row says the game's ticks a real second (perf.game_tick, stalls included)")
def _():
    clock = {"t": 1000.0}
    m = perf.Meter(write=False, clock=lambda: clock["t"])
    p = {"total_ms": 100, "sections": {}, "cached": {}, "fps": 50}
    assert m.note("A#1", 5000, 0.0, 0, dict(p, game_tick=5000)) is None
    clock["t"] += 15.0
    m.note("A#1", 5600, 500.0, 2, dict(p, game_tick=5600))
    clock["t"] += 25.0                                       # 40 real seconds in all
    row = m.note("A#1", 6200, 900.0, 4, dict(p, game_tick=6200))
    assert row["tps"] == 30.0, row                           # 1200 ticks / 40 s
    clock["t"] += 60.0
    row = m.note("A#1", 7400, 1000.0, 5, dict(p, game_tick=7400))
    assert row["tps"] == 20.0, row                           # measured from the last row
    clock["t"] += 10.0
    row = m.note("A#1", 8600, 1000.0, 5, {"total_ms": 1, "sections": {}})   # no game_tick: the date's tick
    assert row["tps"] == 120.0, row


@test("F3a: tps is None under a real second (a test's or a replay's instant row)")
def _():
    m = perf.Meter(write=False, clock=lambda: 5.0)
    m.note("A#1", 0, 0.0, 0, {"game_tick": 0})
    row = m.note("A#1", 1200, 0.0, 0, {"game_tick": 1200})
    assert row["tps"] is None
    assert perf.tps(1200, 0, 1200, 0, 0.5) is None and perf.tps(1200, 0, 1200, 0, 10) == 120.0
    assert perf.tps(None, None, 600, 0, 10) == 60.0 and perf.tps(None, None, 0, 600, 10) is None


if __name__ == "__main__":
    finish()
