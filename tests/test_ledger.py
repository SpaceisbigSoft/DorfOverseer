"""Tests for the AI's ledger (brain/ledger.py): what must not be forgotten,
kept in the save the moment it changes and read back over the memory.

    python tests/test_ledger.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import ledger  # noqa: E402
import memstore  # noqa: E402
import overseer  # noqa: E402
from planner import Memory  # noqa: E402
from tokens import TokenBank  # noqa: E402


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


@test("(0.105.0) a reload keeps the AI's order day counts and its gate, door and trap records")
def _():
    m = Memory()
    m.order_watch = {"12": {"left": 5, "since": 1000, "by_ai": True, "what": "cloth_bag", "job": "x"},
                     "13": {"left": 2, "since": 900, "by_ai": False, "what": "player's"}}
    m.atlas = {"registry": {"gate:5,5,0": {"kind": "gate", "variant": "plain", "tick": 500, "b": [5, 5, 5, 5, 0],
                                           "pieces": [f"p{i}" for i in range(30)]},
                            "traps:5,5,0": {"kind": "traps", "variant": "cage", "tick": 600, "count": 4},
                            "project:3": {"kind": "bedrooms", "tick": 1}}}
    snap = ledger.snapshot(m)
    assert set(snap["order_watch"]) == {"12"}, snap["order_watch"]                 # the AI's own only
    assert set(snap["gate_records"]) == {"gate:5,5,0", "traps:5,5,0"}, snap["gate_records"]
    # an older memory (the week-old one in the save) with the counts restarted
    m2 = Memory()
    m2.order_watch = {"12": {"left": 5, "since": 4000, "by_ai": True, "what": "cloth_bag"}}
    back = json.loads(json.dumps(snap))
    back["gate_records"]["gate:5,5,0"]["b"] = {"1": 5, "2": 5, "3": 5, "4": 5, "5": 0}   # as Lua may send it
    assert ledger.apply(m2, back)
    assert m2.order_watch["12"]["since"] == 1000, m2.order_watch
    reg = m2.atlas["registry"]
    assert reg["traps:5,5,0"]["count"] == 4 and reg["gate:5,5,0"]["b"] == [5, 5, 5, 5, 0], reg
    # bounded: 40 of each
    m3 = Memory()
    m3.order_watch = {str(i): {"left": 1, "since": i, "by_ai": True, "what": "x"} for i in range(100)}
    s3 = ledger.snapshot(m3)
    assert len(s3["order_watch"]) == ledger.ORDER_WATCH_MAX and "99" in s3["order_watch"]


if __name__ == "__main__":
    finish()
