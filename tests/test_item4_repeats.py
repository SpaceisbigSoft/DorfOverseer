"""(item4) Three rules asked again and again for nothing (fort B, 24 Nov 19:23-20:53).

  a) unload_depot refused 57 times in 1.5 hours (107 in 2): "4 item(s) are
     being hauled out of the depot" (the bridge's waiting answer, the same 4
     items on a job for hours), between "the game kept it in the depot". The
     answer to wait looked again in 2 days, flat, and reset the refusal count.
     Now: the report's at_depot_busy (and at_depot_stuck, on the job 3+ days):
     nothing asked while every one left is busy, the stuck ones said; the same
     answer to wait twice as long each time (WAIT_BACKOFF_TYPES).
  b) gather_trim done 29 times in 1.5 hours ("135 plant-gathering jobs wait
     ... cancel all but 20"): DF made the jobs again. Now: the fruit zones'
     jobs are left by trim_gathering (lua), and done 4 times with the count
     not dropping it is held (the no-effect hold, by the count, not the words).
  c) burial_others refused 16 times "no body DF leaves unburied may be marked
     for the dump now" (tests/test_r99_bodies_dump.py for the bridge side);
     here: its own cooldown begins at a refusal too.

    python tests/test_item4_repeats.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

from planner import Memory, PLANNER_CONFIG, record  # noqa: E402
from planner_core import (Proposal, TICKS_PER_DAY, _refused_wait, no_effect_wait, note_no_effect,  # noqa: E402
                          note_refusal)
from planner_core_refusals import WAIT_BACKOFF_MAX_DAYS  # noqa: E402
from planner_trade import _trade_rules  # noqa: E402

CFG = PLANNER_CONFIG
LUA = ROOT / "lua"


def trade_state(at_depot=4, **more):
    tr = {"depot": True, "caravans": [], "at_depot": at_depot, "goods": 0,
          "trader": {"at_depot": False, "can_open": True, "fresh": True}}
    tr.update(more)
    return {"trade": tr, "buildings": {}, "dwarves": {"adults": 10}}


def trade(s):
    props, notes = [], []
    _trade_rules(s, CFG, 10, props, notes, {"trade": 0}, None)
    return [p for p in props if p.rule == "unload_depot"], notes


UNLOAD = Proposal("unload_depot", {"type": "unload_depot", "max": 50}, "x", 4)
WAIT = {"ok": False, "rejected": True, "waiting": True, "error": "4 item(s) are being hauled out of the depot"}


# --- a) unload_depot ----------------------------------------------------------------------

@test("unload_depot: B's 4 left in the depot all on a job (at_depot_busy 4): not asked")
def _():
    u, notes = trade(trade_state(4, at_depot_busy=4))
    assert not u, u
    assert not any("stuck" in str(n) for n in notes), notes


@test("unload_depot: all busy and some stuck 3+ days: not asked, the stuck ones said as a look in the game")
def _():
    u, notes = trade(trade_state(4, at_depot_busy=4, at_depot_stuck=4))
    assert not u
    n = [x for x in notes if "stuck job" in str(x)]
    assert n and n[0].startswith("4 of the fort's 4 goods left in the trade depot"), notes


@test("unload_depot: some free beside the busy: asked, the free ones counted; an older bridge (no busy count): as before")
def _():
    u, _ = trade(trade_state(10, at_depot_busy=4))
    assert len(u) == 1 and "6 of the fort's goods" in u[0].reason, u
    u, _ = trade(trade_state(10))
    assert len(u) == 1 and "10 of the fort's goods" in u[0].reason, u


@test("unload_depot: the same answer to wait waits 2, 4, 8 ... days (at most 28); another answer starts again at 2")
def _():
    m, now = Memory(), 100000
    waits = []
    for _ in range(7):
        note_refusal(m, UNLOAD, WAIT, now, "0.105.108")
        waits.append(_refused_wait(m, UNLOAD, now, "0.105.108"))
    assert waits == [2, 4, 8, 16, 28, 28, 28], waits           # before: 2 each time
    assert WAIT_BACKOFF_MAX_DAYS == 28
    note_refusal(m, UNLOAD, dict(WAIT, error="3 item(s) are being hauled out of the depot"), now, "0.105.108")
    assert _refused_wait(m, UNLOAD, now, "0.105.108") == 2


@test("unload_depot: an answer to wait between two refusals keeps the refusal count (the back-off no longer begins again)")
def _():
    m, now = Memory(), 100000
    kept = {"ok": False, "error": "none moved out of the depot: the game kept it in the depot"}
    note_refusal(m, UNLOAD, kept, now)
    note_refusal(m, UNLOAD, kept, now)
    assert m.refusals[next(iter(m.refusals))]["n"] == 2
    note_refusal(m, UNLOAD, WAIT, now)
    rec = m.refusals[next(iter(m.refusals))]
    assert rec["n"] == 2 and rec["w"] == 1, rec                # before: n 0
    note_refusal(m, UNLOAD, kept, now)
    assert m.refusals[next(iter(m.refusals))]["n"] == 3


@test("other waiting answers (trees being felled): 2 days flat, as before")
def _():
    m, now = Memory(), 100000
    p = Proposal("keep", {"type": "build_keep"}, "x", 4)
    for _ in range(3):
        note_refusal(m, p, {"ok": False, "waiting": True, "error": "trees being felled"}, now)
    assert _refused_wait(m, p, now) == 2


@test("bridge: the trade report's at_depot_busy and at_depot_stuck, the record kept per item; unload says the stuck")
def _():
    src = (LUA / "ai-trade.lua").read_text(encoding="utf-8")
    assert "out.at_depot_busy = busy" in src and "out.at_depot_stuck = stuck" in src
    assert "DEPOT_BUSY_KEY = 'ai-overseer/depot-busy'" in src and "function busy_record(seen, ids, now, stuck_ticks)" in src
    i = src.index("function unload(limit, dry_run, txt)")
    body = src[i:src.index("\nend\n", i)]
    assert "waiting = true, busy = busy_n, stuck =" in body


# --- b) gather_trim -------------------------------------------------------------------------

def trim(n, food=50):
    return Proposal("gather_trim", {"type": "trim_gathering", "keep": 20},
                    f"{n} plant-gathering jobs wait and the fort has {food:g} food a dwarf: cancel all but 20 "
                    "(the farthest first)", 5)


@test("gather_trim: done 4 times while the count doesn't drop (the food a dwarf moving): held 56 days")
def _():
    m, now = Memory(), 200000
    for i, (n, food) in enumerate([(135, 50), (135, 49.5), (131, 49), (136, 48.7)]):
        assert no_effect_wait(m, trim(n, food), now + i, CFG) is None
        note_no_effect(m, trim(n, food), True, now + i)
    w = no_effect_wait(m, trim(135, 48.5), now + 4, CFG)
    assert w == CFG["no_effect_hold_days"], w                  # before: every cycle (29 in 1.5 hours)


@test("gather_trim: the count dropped by a fifth since the streak began: not held, a new streak")
def _():
    m, now = Memory(), 200000
    for i in range(3):
        note_no_effect(m, trim(135), True, now + i)
    note_no_effect(m, trim(100), True, now + 3)                # it worked: 135 -> 100
    assert no_effect_wait(m, trim(100), now + 4, CFG) is None
    rec = next(iter(m.no_effect.values()))
    assert rec["n"] == 1 and rec["count"] == 100, rec


@test("the other no-effect rules (arms) still compare the very words, as before")
def _():
    m, now = Memory(), 200000
    arms = Proposal("arms", {"type": "work_order", "recipe": "crossbow", "amount": 1},
                    "4 crossbow soldiers and 3 with a crossbow", 4)
    for i in range(4):
        note_no_effect(m, arms, True, now + i)
    assert no_effect_wait(m, arms, now + 4, CFG) == CFG["no_effect_hold_days"]
    other = Proposal("arms", dict(arms.action), "4 crossbow soldiers and 2 with a crossbow", 4)
    assert no_effect_wait(m, other, now + 4, CFG) is None
    assert "count" not in next(iter(m.no_effect.values()))


@test("bridge: trim_gathering leaves the fruit zones' jobs (DF makes them again) and says so when only they are over")
def _():
    src = (LUA / "ai-labor.lua").read_text(encoding="utf-8")
    i = src.index("function trim_gathering(keep, dry_run)")
    body = src[i:src.index("\nend\n", i)]
    assert "zone_job(j, zones)" in body and "math.max(0, keep - zoned)" in body
    assert "fruit zones\\' (the game makes them again)" in body
    assert "function in_gather_zone(zones, x, y, z)" in src


# --- c) burial_others ----------------------------------------------------------------------

@test("burial_others: a refusal starts its own cooldown (burial_others_cooldown_ticks), as a success does")
def _():
    s = {"date": {"year": 264, "tick": 300000}}
    p = Proposal("burial_others", {"type": "mark_dump", "bodies": True, "junk": False,
                                   "reasons": ["free", "other_dead"], "max": 50}, "x", 4)
    m = Memory()
    record([(p, {"ok": False, "rejected": True,
                 "error": "no body DF leaves unburied may be marked for the dump now"})], s, m)
    assert "burial_others" in m.last_fired, m.last_fired       # before: only after a success
    assert CFG["burial_others_cooldown_ticks"] >= 3 * TICKS_PER_DAY
    # another rule's refusal still starts no cooldown
    q = Proposal("unload_depot", {"type": "unload_depot", "max": 50}, "x", 4)
    record([(q, {"ok": False, "error": "x"})], s, m)
    assert "unload_depot" not in m.last_fired


if __name__ == "__main__":
    finish()
