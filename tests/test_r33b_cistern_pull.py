"""(r33b) Fort B's built cistern (done, 7/7 deep, floodgate open) proposed
"the cistern is 7/7 deep: shut the floodgate" every cycle (~15-25 s real) on
0.105.128-129: the PullLever job was taken by the militia captain and dropped,
so the status's pull_pending came and went, and the 1-game-day wait after a
pull was ~1 cycle at that speed. Now the ask is paced (game days, real minutes,
brain cycles: brain/planner_cistern_pull.py) and after 3 asks with the
floodgate unchanged the lever is pulled at once (no dwarf).

    python3 tests/test_r33b_cistern_pull.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG  # noqa: E402
from planner_core import TICKS_PER_DAY, abs_tick  # noqa: E402
import planner_wells as PW  # noqa: E402
import planner_cistern_pull as CP  # noqa: E402
import overseer_words as OW  # noqa: E402

CFG = dict(PLANNER_CONFIG)
LUA = ROOT / "lua"
T0 = 50_000


def state(tick: int, fps=50, **st) -> dict:
    cs = dict({"stage": "done", "gate": "open", "depth": 7, "v": 2, "sealed_now": True}, **st)
    s = {"date": {"year": 260, "tick": tick}, "water": {"cistern_status": cs}}
    if fps is not None:
        s["perf"] = {"fps": fps}
    # (F2a) the cycle's wall clock: the fps's real time, else a game day a real minute
    s["wall_time"] = tick / (fps or 20)
    return s


def cycle(s, m):
    props, notes = [], []
    PW._cistern_rule(s, m, CFG, props, notes, {})
    return [p for p in props if p.rule == "cistern"], notes


def run(n, m, fps=50, pending=lambda i: i % 3 == 1, **st):
    """n cycles a game day apart (B: a game day ~25 s, a cycle ~15-25 s)."""
    asks, notes = [], []
    for i in range(n):
        ps, ns = cycle(state(T0 + i * TICKS_PER_DAY, fps=fps, pull_pending=pending(i) or None, **st), m)
        asks += [(i, p) for p in ps]
        notes += ns
    return asks, notes


@test("B: no pull_pending, pending, gone: one proposal for the whole wait")
def _():
    m = Memory()
    asks, _ = run(3, m)
    assert [i for i, _ in asks] == [0], asks
    assert asks[0][1].action.get("type") == "cistern_step" and not asks[0][1].action.get("shut")


@test("B: paced by game days, real minutes (fps) and cycles; stuck after 3 asks: said once, then shut at once")
def _():
    m = Memory()
    asks, notes = run(30, m)
    # fps 50: 3 real minutes = 9000 ticks = 7.5 game days > 3 days, > 4 cycles: an ask every 8 cycles
    assert [i for i, _ in asks] == [0, 8, 16, 24], [i for i, _ in asks]
    for _, p in asks[:3]:
        assert not p.action.get("shut") and not p.action.get("instant"), p.action
    last = asks[3][1].action
    assert last == {"type": "cistern_step", "shut": True}, last     # cistern_shut: queued pulls off, instant pull
    assert "at once" in asks[3][1].reason
    stuck = [n for n in notes if "pulls it at once" in n]
    assert len(stuck) == 1, stuck


@test("without an fps reading (F2a: the wall clock a minute a day): game days and cycles (3 days, 4 cycles)")
def _():
    m = Memory()
    asks, _ = run(13, m, fps=None, pending=lambda i: False)
    assert [i for i, _ in asks] == [0, 4, 8, 12], [i for i, _ in asks]


@test("a fast game (a day a cycle): the cycles hold it even when the days are past")
def _():
    m = Memory()
    asks = []
    for i in range(9):      # 3 game days a cycle, no fps: the days pass at once, the cycles don't
        ps, _ = cycle(state(T0 + i * 3 * TICKS_PER_DAY, fps=None), m)
        asks += [i for _ in ps]
    assert asks == [0, 4, 8], asks


@test("the same tick looked at twice is one cycle, and asks nothing new")
def _():
    m = Memory()
    s = state(T0)
    assert len(cycle(s, m)[0]) == 1
    for _ in range(10):
        assert cycle(s, m)[0] == []
    assert int(m.repeat_book[CP.CISTERN_PULL_BOOK].get("seen") or 0) == 0


@test("the floodgate moved: the record starts afresh (the next want asked at once)")
def _():
    m = Memory()
    run(10, m)                                         # two asks for the shut
    assert m.repeat_book[CP.CISTERN_PULL_BOOK]["n"] == 2
    ps, _ = cycle(state(T0 + 11 * TICKS_PER_DAY, gate="shut", depth=7), m)   # shut: nothing wanted
    assert ps == []
    ps, _ = cycle(state(T0 + 40 * TICKS_PER_DAY, gate="shut", depth=2), m)   # low: the open asked now
    assert len(ps) == 1 and "refill" in ps[0].reason and not ps[0].action.get("instant")
    now = abs_tick(state(T0 + 40 * TICKS_PER_DAY))
    assert m.repeat_book[CP.CISTERN_PULL_BOOK] == {"want": "opened", "n": 1, "at": now, "seen": 0, "last": now,
                                                   "at_s": (T0 + 40 * TICKS_PER_DAY) / 50}


@test("the refill stuck too: its 4th ask is the done step with instant")
def _():
    m = Memory()
    asks, _ = run(30, m, gate="shut", depth=1)
    assert [i for i, _ in asks] == [0, 8, 16, 24]
    a = asks[3][1].action
    assert a.get("type") == "cistern_step" and a.get("instant") is True and not a.get("shut"), a
    assert OW.short(a) == "open the cistern's floodgate at once", OW.short(a)
    assert OW.short({"type": "cistern_step", "shut": True}) == "shut the cistern's floodgate"


@test("a pending pull the record doesn't know (before a restart): waited on, not counted")
def _():
    m = Memory()
    for i in range(5):
        ps, ns = cycle(state(T0 + i * TICKS_PER_DAY, pull_pending=True), m)
        assert ps == [] and "on the way" in ns[-1]
    assert not m.repeat_book[CP.CISTERN_PULL_BOOK].get("n")


@test("no memory: the old way (the pending flag only)")
def _():
    notes = []
    assert CP.cistern_pull_plan(state(T0), state(T0)["water"]["cistern_status"], None, notes) == "ask"
    st = dict(state(T0)["water"]["cistern_status"], pull_pending=True)
    assert CP.cistern_pull_plan(state(T0), st, None, notes) == "wait"


@test("lua: the done step's instant top-up pull takes the queued pulls away first; the bridge passes it")
def _():
    step = (LUA / "ai-builder-cistern-step.lua").read_text(encoding="utf-8")
    assert "function cistern_step(dry_run, prefs, tunnel, instant)" in step
    assert "local cancelled = lever_pull_pending(lever_id) and cancel_lever_pulls(lever_id) or nil" in step
    assert "local ok, out = pull(lever_id, true)" in step
    assert step.count("top_up_pull(d.lever_id, instant)") == 2
    act = (LUA / "ai-bridge-actions-trade.lua").read_text(encoding="utf-8")
    assert "a.instant == true)" in act
    assert "if a.shut == true then return reqscript('ai-builder').cistern_shut(a.dry_run == true) end" in act
    status = (LUA / "ai-builder-cistern-status.lua").read_text(encoding="utf-8")
    assert "if d.stage == 'done' and d.lever_id and gate and gate.built then" in status
    # cistern_shut (the stuck shut) cancels before its instant pull
    i = status.index("function cistern_shut(")
    body = status[i:status.index("\nend", i)]
    assert body.index("cancel_lever_pulls") < body.index("pull(d.lever_id, true)")


if __name__ == "__main__":
    finish()
