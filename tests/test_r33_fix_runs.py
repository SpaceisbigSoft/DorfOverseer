"""(0.105.33 fixes, area "runs") the verifier's findings:

- one_cycle on a report whose date failed: no note_cycle, plan, act or record
  at tick 0; the cooldowns, declines and loop log stay as they were;
- check_pin backs off PIN_RETRY_S after a check that couldn't tell;
- the hostile-trade filter fails closed (no trade when it raises);
- a stored raise/hold the strategist now refuses goes at the next note_cycle,
  and an older build hold over 14 days is cut to 14;
- the strategist shortens a build hold over 14 days instead of dropping it.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))

from harness import make_test, finish  # noqa: E402
import test_overseer as TO  # noqa: E402  (its fake bridge; its tests run only when it is run itself)
import planner  # noqa: E402
import strategist  # noqa: E402
from planner import Memory, Proposal, plan, note_cycle, TICKS_PER_DAY  # noqa: E402

test = make_test(before=TO._before)
REAL = json.loads((ROOT / "tests" / "fixtures" / "real" / "region2-0.83-y62-spring.json").read_text(encoding="utf-8"))
KEY = "AI Test Run#1234"


@test("one_cycle, date failed: nothing planned or acted; cooldowns, declines and loop log kept")
def _():
    ov = TO.overseer
    b = TO.FakeBridge()
    for _ in range(6):
        ov.one_cycle(b, autopilot=True)
        b.advance(1)
    mem, bank = ov.load(KEY, b, state=b.state())
    mem.declined["abc123"] = max(mem.last_fired.values())
    ov.save(KEY, mem, bank, None, b.state())
    ov.MEMORY_CACHE.clear()
    mem, _ = ov.load(KEY, b, state=b.state())
    before = (dict(mem.last_fired), dict(mem.declined), copy.deepcopy(mem.action_log),
              copy.deepcopy(mem.timeline))
    assert before[0] and before[2], before
    good_date = copy.deepcopy(b._state["date"])
    b._state["date"] = {"error": "lua: date failed"}
    acted = len(b.acted)
    called = []
    real_plan, real_nc = ov.plan, ov.note_cycle
    ov.plan = lambda *a, **k: (called.append("plan"), real_plan(*a, **k))[1]
    ov.note_cycle = lambda *a, **k: (called.append("note_cycle"), real_nc(*a, **k))[1]
    try:
        ov.MEMORY_CACHE.clear()
        ov.one_cycle(b, autopilot=True)
    finally:
        ov.plan, ov.note_cycle = real_plan, real_nc
    assert called == [], called
    assert b.acted[acted:] == [], b.acted[acted:]
    assert any("date couldn't be read" in x for x in TO.SAID), TO.SAID[-5:]
    assert b.reports and "date couldn't be read" in b.reports[-1]["acting"], b.reports[-1:]
    ov.MEMORY_CACHE.clear()
    mem2, _ = ov.load(KEY, b, state=b.state())
    after = (dict(mem2.last_fired), dict(mem2.declined), copy.deepcopy(mem2.action_log),
             copy.deepcopy(mem2.timeline))
    assert after == before
    b._state["date"] = good_date
    b.advance(1)
    ov.MEMORY_CACHE.clear()
    ov.one_cycle(b, autopilot=True)                 # the next good cycle carries on
    mem3, _ = ov.load(KEY, b, state=b.state())
    assert all(t > 0 for t in mem3.last_fired.values()), mem3.last_fired
    assert "abc123" in mem3.declined


class _PulseBridge:
    def __init__(self, fort):
        self.fort, self.calls = fort, 0

    def state(self, include_units=True, tier="daily"):
        self.calls += 1
        return {"fort": dict(self.fort)}


@test("check_pin: a check that can't tell waits PIN_RETRY_S before the next pulse report")
def _():
    ov = TO.overseer
    ov.PIN_SEEN.clear()
    ov.PIN_SEEN.update(checked=False, refused=None)
    b = _PulseBridge({"site_id": 7})              # no world: can't tell
    ov.check_pin(b)
    ov.check_pin(b)
    ov.check_pin(b)
    assert b.calls == 1 and not ov.PIN_SEEN["checked"], (b.calls, ov.PIN_SEEN)
    ov.PIN_SEEN["failed_at"] -= ov.PIN_RETRY_S + 1   # a minute later
    b.fort["world"] = "W"
    ov.check_pin(b)
    assert b.calls == 2 and ov.PIN_SEEN["checked"] and "failed_at" not in ov.PIN_SEEN, ov.PIN_SEEN
    ov.PIN_SEEN.clear()
    ov.PIN_SEEN.update(checked=False, refused=None)


@test("plan: the hostile-trade filter raising drops every trade proposal (fails closed)")
def _():
    real_ex, real_hf = planner._export_rule, planner._hostile_trade_filter

    def ex(s, cfg, proposals, notes, memory):
        proposals.append(Proposal("trade", {"type": "call_trader"}, "test", 50))
        proposals.append(Proposal("trade", {"type": "bring_goods"}, "test", 50))

    def boom(*a, **k):
        raise RuntimeError("boom")
    try:
        planner._export_rule = ex
        props, _ = plan(copy.deepcopy(REAL), Memory())
        assert [p for p in props if p.action["type"] == "call_trader"], "the fake rule ran"
        planner._hostile_trade_filter = boom
        props, notes = plan(copy.deepcopy(REAL), Memory())
    finally:
        planner._export_rule, planner._hostile_trade_filter = real_ex, real_hf
    assert [n for n in notes if n.startswith("rule boom failed")], notes
    assert not [p for p in props if p.action["type"] in ("call_trader", "bring_goods")], props


@test("note_cycle: an old raise of slaughter, hold of containers go; an 84-day build hold cut to 14")
def _():
    s = copy.deepcopy(REAL)
    now = planner.abs_tick(s)
    m = Memory()
    far = now + 84 * TICKS_PER_DAY
    m.steer = {"slaughter": {"mode": "raise", "until": far, "why": ""},
               "containers": {"mode": "hold", "until": far, "why": ""},
               "build": {"mode": "hold", "until": far, "why": ""},
               "crafts": {"mode": "hold", "until": far, "why": ""}}
    note_cycle(s, m)
    assert "slaughter" not in m.steer and "containers" not in m.steer, m.steer
    assert m.steer["build"]["until"] == now + 14 * TICKS_PER_DAY, m.steer["build"]
    assert m.steer["crafts"]["until"] == far


@test("strategist: a 28-day build hold is shortened to 14, not rejected")
def _():
    ok, why = strategist._check_steer({"type": "hold", "rule": "build", "days": 28, "why": "x"})
    assert ok == {"type": "hold", "rule": "build", "days": 14, "why": "x"}, (ok, why)
    ok, why = strategist._check_steer({"type": "hold", "rule": "build", "days": 99})
    assert ok is None and "1-84" in why, (ok, why)


if __name__ == "__main__":
    finish()
