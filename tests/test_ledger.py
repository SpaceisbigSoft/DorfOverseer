"""Tests for the AI's ledger (brain/ledger.py): what must not be forgotten,
kept in the save the moment it changes and read back over the memory.

    python tests/test_ledger.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

import ledger  # noqa: E402
import memstore  # noqa: E402
import overseer  # noqa: E402
from planner import Memory  # noqa: E402
from tokens import TokenBank  # noqa: E402

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


@test("snapshot and apply: the fields round-trip, empty tables in either shape, bounded")
def _():
    m = Memory()
    m.ai_alert_raised, m.gate_closed_by_ai, m.kitchen_ban = True, True, True
    m.wishes_agreed = {f"w{i}": i for i in range(60)}
    m.culture = {"memorials_built": ["Hall of Ôlon"]}
    m.last_expel_tick = 12345
    snap = ledger.snapshot(m)
    assert len(snap["wishes_agreed"]) == ledger.DICT_MAX and "w59" in snap["wishes_agreed"] and "w0" not in snap["wishes_agreed"]
    m2 = Memory()
    assert ledger.apply(m2, snap)
    assert m2.ai_alert_raised and m2.gate_closed_by_ai and m2.kitchen_ban and m2.last_expel_tick == 12345
    assert m2.culture["memorials_built"] == ["Hall of Ôlon"]
    # from Lua: an empty dict comes back as [], an array as {"1": ..}
    back = dict(snap, squads_trained={"1": 4, "2": 9}, stuck_cancelled=[], tree_year=[])
    m3 = Memory()
    ledger.apply(m3, back)
    assert m3.squads_trained == [4, 9] and m3.stuck_cancelled == {} and m3.tree_year == {}
    assert ledger.same(snap, snap) and not ledger.same(snap, dict(snap, kitchen_ban=False))
    assert ledger.same(ledger.snapshot(Memory()), {})                      # empty = nothing held
    # no ledger (a save from before 0.104.0), or a section that failed: the memory as it was
    m4 = Memory()
    m4.ai_alert_raised = True
    assert not ledger.apply(m4, {}) and not ledger.apply(m4, {"error": "x"}) and m4.ai_alert_raised


class FakeBridge:
    def __init__(self, ok=True):
        self.acted, self.ok = [], ok

    def act(self, a):
        self.acted.append(a)
        return {"ok": self.ok, "error": None if self.ok else "nope"}


@test("write_ledger: only when it differs from the save's; never to a bridge without a ledger")
def _():
    m = Memory()
    b = FakeBridge()
    state = {"ledger": {}}
    overseer.write_ledger(b, state, m)
    assert not b.acted                                            # nothing to keep yet
    m.ai_alert_raised = True
    overseer.write_ledger(b, state, m)
    assert len(b.acted) == 1 and b.acted[0]["type"] == "ledger_set" and b.acted[0]["values"]["ai_alert_raised"]
    overseer.write_ledger(b, state, m)
    assert len(b.acted) == 1                                      # the state now holds it
    overseer.write_ledger(b, {}, m)                               # an older bridge: no section
    overseer.write_ledger(b, {"ledger": {"error": "x"}}, m)
    assert len(b.acted) == 1


@test("load: the save's ledger is laid over the memory read from the save (a reload), not over the cached one")
def _():
    real = memstore.load
    try:
        memstore.load = lambda key, bridge, prefer_logs: (Memory(), TokenBank())
        overseer.MEMORY_CACHE.clear()
        st = {"date": {"year": 56, "tick": 1000}, "ledger": {"gate_closed_by_ai": True, "memorials_built": ["X"]}}
        m, _ = overseer.load("F#1", None, state=st)
        assert m.gate_closed_by_ai and m.culture["memorials_built"] == ["X"]
        m.gate_closed_by_ai = False                               # changed this run, not yet in the save
        st2 = {"date": {"year": 56, "tick": 1500}, "ledger": {"gate_closed_by_ai": True}}
        m2, _ = overseer.load("F#1", None, state=st2)
        assert m2 is m and not m2.gate_closed_by_ai               # the cache: the run's own memory
        st3 = {"date": {"year": 56, "tick": 500}, "ledger": {"gate_closed_by_ai": True}}   # an older save
        m3, _ = overseer.load("F#1", None, state=st3)
        assert m3 is not m and m3.gate_closed_by_ai
    finally:
        memstore.load = real
        overseer.MEMORY_CACHE.clear()


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f"\n    {msg}"))
    fails = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - fails} passed, {fails} failed")
    sys.exit(1 if fails else 0)
