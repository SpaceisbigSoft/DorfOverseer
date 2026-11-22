"""(r5 verify) Proof tests for the bugs found in round 5's merge (r5-merge).

Each test fails on r5-merge and passes once its bug is fixed.

    python tests/test_r5_verify.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402

import crisis  # noqa: E402
import memstore  # noqa: E402
import rests  # noqa: E402
from planner import PLANNER_CONFIG, Memory, record, select, TICKS_PER_DAY  # noqa: E402
from planner_core import Proposal  # noqa: E402
from tokens import TokenBank  # noqa: E402
import json  # noqa: E402
from planner import abs_tick, TICKS_PER_YEAR  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


class P3:
    """test_r5_p3's fort and well (that file calls finish() when imported)."""
    NO_DROP = ("no open drop from a free floor inside the fort to clean water; and the water near the surface "
               "freezes in winter (a well over it would be taken down), so the AI looks only inside the fort")

    @staticmethod
    def fort(year=250, tick=300000):
        s = copy.deepcopy(BASE)
        s["date"] = dict(s["date"], year=year, tick=tick, season="autumn")
        s["bridge_version"] = "0.105.60"
        s["projects"] = dict(s.get("projects") or {}, done_total=57)
        s.setdefault("buildings", {}).setdefault("other", {})["Well"] = 0
        return s

    @staticmethod
    def well():
        return Proposal("well", {"type": "place_well", "shore_reach": 60, "inside_only": True}, "no well yet", 3)

CFG = dict(PLANNER_CONFIG)
Y, T = 257, 200000


# --- Z1 ---------------------------------------------------------------------------------------
@test("Z1 rests: a real death of a dwarf who shares a name with a ghost put to rest in the same batch is "
      "still a death (matched by name, not unit id)")
def _():
    rest = {"kind": "report", "topic": "ghost", "type": "CITIZEN_DEATH",
            "text": "Urist Lokumzon, Ghostly Miner has been put to rest.", "year": Y, "tick": T}
    # another unit (id 902, never told dead), killed now: same first and last name
    death = {"kind": "death", "unit_id": 902, "name": "Urist Lokumzon, Farmer", "own_civ": True,
             "animal": False, "cause": "STRUCK_DOWN", "year": Y, "tick": T}
    told: list = []
    out = rests.mark_rests([rest, death], told, Y * 403200 + T)
    d = next(e for e in out if e.get("kind") == "death")
    assert rests.citizen_death(d), ("a new unit's death read as a rest", d)
    m = Memory()
    s = {"date": {"year": Y, "tick": T}}
    assert crisis.note_deaths(s, m, out) == 1, "crisis mode missed a real death"


# --- Z2 ---------------------------------------------------------------------------------------
@test("Z2 memory: dead_told at its cap (TOLD_KEEP) and refusal_streaks at theirs (r5p3_refusal_keep) fit "
      "the working kind's budget")
def _():
    m = Memory()
    m.dead_told = [[100000 + i, Y * 403200 + i * 997] for i in range(rests.TOLD_KEEP)]
    assert not memstore.over_budget(m, TokenBank(), "AI Test Run#1234"), \
        ("dead_told alone", memstore.sizes(m, TokenBank(), "AI Test Run#1234"))
    m = Memory()
    for i in range(CFG["r5p3_refusal_keep"]):
        m.refusal_streaks[f"rule{i}:" + '{"kind": "workshops"}'] = {
            "n": 9, "why": "x" * 100, "sig": {"v": "0.105.60", "levels": 40, "wells": 3}, "at": 103000000 + i,
            "until": 104000000, "days": 28, "rule": f"rule{i}", "type": "start_project"}
    m.dead_told = [[100000 + i, Y * 403200 + i] for i in range(600)]      # a long fort's dead
    assert not memstore.over_budget(m, TokenBank(), "AI Test Run#1234"), \
        ("streaks + 600 dead", memstore.sizes(m, TokenBank(), "AI Test Run#1234"))


# --- Z3 ---------------------------------------------------------------------------------------
def _held(p, s, m):
    m.last_fired.clear()
    m.refusals.clear()                          # (the general back-off aside)
    allowed, held = select([p], s, m, CFG)
    return not allowed and any("in a row for the same reason" in h for h in held), held


@test("Z3 refusal streak: an urgent hospital level (rule build) in a crisis is never held by the streak")
def _():
    s, m = P3.fort(), Memory()
    m.crisis = {"since": 1, "why": ["9 citizens dead in 4 weeks"]}
    p = Proposal("build", {"type": "start_project", "kind": "hospital", "beds": 6, "urgent": True},
                 "40 wounded wait for a bed", 1)
    for _ in range(3):
        record([(p, {"ok": False, "error": "no site found for a hospital level"})], s, m, CFG)
    held, lines = _held(p, s, m)
    assert not held, lines


@test("Z3 refusal streak: an urgent Still for the thirsty (rule bottleneck) is never held by the streak")
def _():
    s, m = P3.fort(), Memory()
    p = Proposal("bottleneck", {"type": "start_project", "kind": "workshops", "shops": ["Still"], "urgent": True},
                 "drink is out: build another still (URGENT)", 3)
    for _ in range(3):
        record([(p, {"ok": False, "error": "no room for a workshops level"})], s, m, CFG)
    held, lines = _held(p, s, m)
    assert not held, lines


@test("Z3 refusal streak: the tombs for the ghosts (urgent, crisis recovery) are never held in a crisis")
def _():
    s, m = P3.fort(), Memory()
    m.crisis = {"since": 1, "why": ["6 ghosts"]}
    p = Proposal("tombs_ghosts", {"type": "start_project", "kind": "tombs", "coffins": 8, "urgent": True},
                 "6 ghosts haunt the fort", 1)
    for _ in range(3):
        record([(p, {"ok": False, "error": "no site found for a tombs level"})], s, m, CFG)
    held, lines = _held(p, s, m)
    assert not held, lines


# --- Z4 ---------------------------------------------------------------------------------------
@test("Z4 refusal streak: after an older save is loaded (the game's time goes back) the wait is still at most "
      "r5p3_refusal_wait_max_days")
def _():
    s, m = P3.fort(year=252), Memory()
    p = P3.well()
    for _ in range(3):
        record([(p, {"ok": False, "error": P3.NO_DROP})], s, m, CFG)
    rec = next(iter(m.refusal_streaks.values()))
    assert rec["days"] == 1, rec
    # the player loads a save from a year before (the logs' memory kept: a save without the memory kinds)
    back = P3.fort(year=251)
    import planner_refusal_streak as RS
    got = RS.wait(m, p, back, abs_tick(back), CFG)
    assert got is None or got[0] <= CFG["r5p3_refusal_wait_max_days"], ("held for days", got[0])


if __name__ == "__main__":
    finish()
