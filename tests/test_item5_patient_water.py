"""(item5) Thirsty patients: the fort's part when DF's water carrying fails
(brain/planner_thirst.py _patient_support, note_thirst).

Built from fort B, 24 Nov: three patients died of thirst (18524 at 12:15,
18458 at 20:05, 17126 at 20:11), each after three thirst_patient tries in
the 35-40k thirst band and nothing more till ~74k (the ladder before
0.105.109); care_feed asked 33 times for the Orderlies labour that work
detail already gave everybody; after 0.105.109 Mebzuth "Cagerack" (17182)
lay outside a bed, unable to stand, with no GiveWater job (DF waters only a
patient resting in bed).

    python tests/test_item5_patient_water.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG  # noqa: E402
import planner_thirst as PT  # noqa: E402

RETRY = PLANNER_CONFIG["thirst_retry_ticks"]


def state(rows_=None, tick=1200, **kw):
    s = {"date": {"year": 300, "tick": tick}, "thirst": {"list": rows_ or [], "deaths": []}, "orders": []}
    s.update(kw)
    return s


def row(uid, timer=40000, **kw):
    return {"id": uid, "name": f"Dwarf {uid}", "reason": "injured", "timer": timer, "x": 105, "y": 160, "z": 148, **kw}


def cycle(s, m, results=None):
    props: list = []
    notes: list = []
    PT._thirst_rule(s, PLANNER_CONFIG, props, notes, m)
    now = s["date"]["year"] * 403200 + s["date"]["tick"]
    for p in props:
        if p.rule == "thirst" and results and p.action.get("type") in results:
            PT.note_thirst(p, results[p.action["type"]], m, now)
    return [p for p in props if p.rule == "thirst"], notes


# B, 22:15 (0.105.109): 17182 out of bed, can't stand, not resting, no GiveWater
CAGERACK = {"action": "thirst_patient", "ok": True, "unit_id": 17182, "buckets": 47, "buckets_free": 31,
            "can_stand": False, "carriers": 22, "carriers_free": 5, "give_water_for_them": 0, "give_water_jobs": 0,
            "in_bed": False, "resting": False, "wells": 5, "wells_here": 5, "water_zones": 1, "water_zones_here": 0}


@test("B 17182: a patient on the floor who can't stand: the Recover wounded labour, and the words say why")
def _():
    m = Memory()
    s = state([row(17182, timer=35538)], supplies={"buckets": 47})
    cycle(s, m, {"thirst_patient": CAGERACK})
    s = state([row(17182, timer=36800)], tick=1200 + RETRY, supplies={"buckets": 47})
    p, n = cycle(s, m)
    acts = [x.action for x in p]
    assert {"type": "assign_labor", "job": "RECOVER_WOUNDED", "count": 2} in acts, acts
    assert not any(a.get("job") == "FEED_WATER_CIVILIANS" for a in acts), acts     # carriers free: not asked
    assert not any(a.get("recipe") == "wooden_bucket" for a in acts), acts
    assert any("outside a bed" in x for x in n), n


@test("the Recover wounded work detail set to everybody (threats.rescue.mode): not asked")
def _():
    m = Memory()
    rescue = {"threats": {"rescue": {"holders": 30, "down": 1, "mode": "EverybodyDoesThis"}}}
    cycle(state([row(17182, timer=35538)], **rescue), m, {"thirst_patient": CAGERACK})
    p, _ = cycle(state([row(17182, timer=36800)], tick=1200 + RETRY, **rescue), m)
    assert not any(x.action.get("job") == "RECOVER_WOUNDED" for x in p), [x.action for x in p]


@test("in bed, resting, every carrier busy and no GiveWater for them: more on the water labour")
def _():
    m = Memory()
    busy = dict(CAGERACK, in_bed=True, resting=True, carriers_free=0)
    cycle(state([row(1, timer=40000)]), m, {"thirst_patient": busy})
    p, _ = cycle(state([row(1, timer=41000)], tick=1200 + RETRY), m)
    acts = [x.action for x in p]
    assert {"type": "assign_labor", "job": "FEED_WATER_CIVILIANS", "count": 2} in acts, acts
    assert not any(a.get("job") == "RECOVER_WOUNDED" for a in acts), acts           # in bed


@test("B care_feed x33: 'everybody already does this' is remembered: the labour not asked again for 10 days")
def _():
    m = Memory()
    busy = dict(CAGERACK, in_bed=True, resting=True, carriers_free=0)
    refused = {"action": "assign_labor", "ok": False, "rejected": True,
               "error": "everybody already does this (the Orderlies work detail is set to everybody)"}
    cycle(state([row(1, timer=40000)]), m, {"thirst_patient": busy})
    p, _ = cycle(state([row(1, timer=41000)], tick=1200 + RETRY), m, {"assign_labor": refused})
    assert any(x.action.get("job") == "FEED_WATER_CIVILIANS" for x in p)
    assert "FEED_WATER_CIVILIANS" in m.thirst_book["labor_all"]
    asked = 0
    for i in range(2, 12):
        s = state([row(1, timer=41000 + 500 * i)], tick=1200 + RETRY * i)
        p, _ = cycle(s, m, {"thirst_patient": busy})
        asked += sum(1 for x in p if x.action.get("job") == "FEED_WATER_CIVILIANS")
    assert asked == 0, asked
    # long after: asked again
    s = state([row(1, timer=52000)], tick=1200 + RETRY + PT.LABOR_ALL_TICKS + RETRY)
    cycle(s, m, {"thirst_patient": busy})
    s["date"]["tick"] += RETRY
    p, _ = cycle(s, m)
    assert any(x.action.get("job") == "FEED_WATER_CIVILIANS" for x in p), [x.action for x in p]


@test("no free bucket at the last count (the fort has some): more buckets ordered; a queued order is enough")
def _():
    m = Memory()
    nob = dict(CAGERACK, in_bed=True, resting=True, buckets_free=0, carriers_free=3, missing=["buckets"])
    cycle(state([row(1, timer=40000)], supplies={"buckets": 12}), m, {"thirst_patient": nob})
    p, _ = cycle(state([row(1, timer=41000)], tick=1200 + RETRY, supplies={"buckets": 12}), m)
    assert any(x.action.get("recipe") == "wooden_bucket" for x in p), [x.action for x in p]
    m = Memory()
    s = state([row(1, timer=40000)], supplies={"buckets": 12})
    cycle(s, m, {"thirst_patient": nob})
    s = state([row(1, timer=41000)], tick=1200 + RETRY, supplies={"buckets": 12},
              orders=[{"recipe": "wooden_bucket", "amount_left": 3}])
    p, _ = cycle(s, m)
    assert not any(x.action.get("recipe") == "wooden_bucket" for x in p)


@test("all well (free carriers, buckets, a GiveWater job for them): nothing more asked of the fort")
def _():
    m = Memory()
    ok = dict(CAGERACK, in_bed=True, resting=True, give_water_for_them=1, give_water_jobs=1)
    cycle(state([row(1, timer=40000)], supplies={"buckets": 47}), m, {"thirst_patient": ok})
    p, _ = cycle(state([row(1, timer=41000)], tick=1200 + RETRY, supplies={"buckets": 47}), m)
    assert not any(x.action.get("type") in ("assign_labor", "work_order") for x in p), [x.action for x in p]


@test("another rule's refused labour is not booked as 'everybody' by the thirst hook")
def _():
    m = Memory()

    class P:
        rule = "staff"          # (0.105.113 item13) care_feed's own refusals are booked now
        action = {"type": "assign_labor", "job": "FEED_WATER_CIVILIANS", "count": 2}
    PT.note_thirst(P(), {"ok": False, "error": "everybody already does this"}, m, 100)
    assert not getattr(m, "thirst_book", {}).get("labor_all")


if __name__ == "__main__":
    finish()
