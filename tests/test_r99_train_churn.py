"""(0.105.99, merge) The rotation's rest month kept: a squad the rotation sent
off duty is not put back on training by the "sits off duty" rule on a cycle
the rotation doesn't run (E, 24 Nov: squads 191/210/217/219 sent off duty and
put back on staggered training every few minutes).

    python tests/test_r99_train_churn.py
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))

from harness import test, finish  # noqa: E402
from planner import Memory, plan, record, Proposal  # noqa: E402
from planner_core import abs_tick, TICKS_PER_DAY  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort():
    s = copy.deepcopy(BASE)
    s["dwarves"]["total"] = 80
    s["military"]["routines"] = ["Off duty", "Staggered training", "Constant training", "Ready"]
    s["military"]["squads"] = [{"id": 10 + i, "name": f"Squad {10 + i}", "members": 8, "size": 10,
                                "orders": 0, "ai_orders": 0, "routine": "Off duty"} for i in range(4)]
    return s


def sits_off(props):
    return [p for p in props if p.rule == "train" and "sits off duty" in p.reason]


@test("record: the rotation's rest is dated; another rest (a small fort's) is not")
def _():
    s, m = fort(), Memory()
    m.squads_trained = [10, 11]
    rot = Proposal("train", {"type": "squad_routine", "squad_id": 10, "routine": "Off duty"},
                   "a squad has trained its month: back to work while another squad trains (1 of 2 at a time)", 4)
    small = Proposal("train", {"type": "squad_routine", "squad_id": 11, "routine": "Off duty"},
                     "the fort is small: the squad back to work", 4)
    record([(rot, {"ok": True}), (small, {"ok": True})], s, m)
    assert m.rested_at.get("10") == abs_tick(s) and "11" not in m.rested_at, m.rested_at
    on = Proposal("train", {"type": "squad_routine", "squad_id": 10, "routine": "Constant training"}, "turn", 4)
    record([(on, {"ok": True})], s, m)
    assert "10" not in m.rested_at


@test("the sits-off rule leaves a squad in its rotation rest month alone; after the month it trains again")
def _():
    s, m = fort(), Memory()
    m.squads_trained = [10, 11, 12, 13]
    m.squads_rested = [10, 11, 12, 13]
    now = abs_tick(s)
    m.rested_at = {str(i): now - 2 * TICKS_PER_DAY for i in (10, 11, 12, 13)}
    props = plan(s, m)[0]
    assert not any(p.action.get("squad_id") in (10, 11, 12, 13) for p in sits_off(props)), \
        [(p.action, p.reason) for p in sits_off(props)]
    m2 = Memory()
    m2.squads_trained = [10, 11, 12, 13]
    m2.squads_rested = [10, 11, 12, 13]
    m2.rested_at = {str(i): now - 40 * TICKS_PER_DAY for i in (10, 11, 12, 13)}
    props2 = plan(s, m2)[0]
    trained = [p for p in props2 if p.rule == "train" and p.action.get("routine") != "Off duty"]
    assert trained, [(p.rule, p.reason) for p in props2 if p.rule == "train"]


if __name__ == "__main__":
    finish()
