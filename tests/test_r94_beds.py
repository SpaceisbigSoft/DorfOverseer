"""(0.105.94) B's infected are no patients: their infected wounds are already
diagnosed.

Live 23 Nov, B (probe-beds-who, 20:28): the 10 hospital beds were free (no
unit on them, no job at them, no users; the 0 free at 20:24 was passing). All
7 infected citizens had each infected wound flagged `diagnosed` (most
`sutured`, some years old), no rq_ flag, needs_healthcare false: DF counts
them treated, so no doctor sees them and the bed rule (DF's patients only)
can't send them. The survey counts them (`not_patients`, `chronic`) and the
note says so. A re-diagnosis (clear the wounds' diagnosed flags, set
rq_diagnosis and needs_healthcare) is a design only (`rediagnose`, dry run by
default, no bridge action): a live trial first.

    python tests/test_r94_beds.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402

from planner_care import _infection_rule  # noqa: E402
from planner import PLANNER_CONFIG  # noqa: E402

HEALTH = (ROOT / "lua" / "ai-health.lua").read_text(encoding="utf-8")
CATALOG = (ROOT / "lua" / "ai-bridge-catalog.lua").read_text(encoding="utf-8")
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort(inf):
    s = copy.deepcopy(BASE)
    s["infection"] = inf
    return s


B_INF = {"infected": 7, "untreated": 7, "idle_untreated": 0, "not_patients": 7, "chronic": 7, "beds": 10,
         "free_beds": 10, "hospital_zones": 2, "cleaners": 35, "diagnosers": 6, "max_load": 115,
         "worst": [{"id": 16783, "name": "Zasit", "load": 115, "diagnosed": True}]}


@test("B's survey (7 infected, all already diagnosed, none DF's patient): the note says DF counts them treated and "
      "the AI can't put them to bed; no rest_infected proposed")
def _():
    props, notes = [], []
    _infection_rule(fort(B_INF), PLANNER_CONFIG, props, notes)
    n = [x for x in notes if x.startswith("7 citizens have infected wounds")]
    assert n and "7 of them DF doesn't count as patients" in n[0] and "DF counts them treated" in n[0], notes
    assert not [p for p in props if p.rule == "infected_rest"], props


@test("an older report (no not_patients key): the note as before")
def _():
    inf = {k: v for k, v in B_INF.items() if k not in ("not_patients", "chronic")}
    notes = []
    _infection_rule(fort(inf), PLANNER_CONFIG, [], notes)
    assert notes and "count as patients" not in notes[0], notes


@test("ai-health: the survey counts not_patients and chronic (each infected wound diagnosed); the candidate reads "
      "diagnosed_only")
def _():
    assert "local function diagnosed_only(u)" in HEALTH
    assert "c.diagnosed = diagnosed_only(u)" in HEALTH
    body = HEALTH[HEALTH.index("function survey("):]
    assert "out.not_patients = out.not_patients + 1" in body and "out.chronic = out.chronic + 1" in body


@test("rediagnose is a design only: dry run unless dry_run is false, and no bridge action calls it")
def _():
    body = HEALTH[HEALTH.index("function rediagnose("):]
    assert "dry_run = dry_run ~= false" in body
    assert re.search(r"if not dry_run then\s+w\.flags\.diagnosed = false", body)
    assert "rediagnose" not in CATALOG
    assert not list((ROOT / "brain").glob("*.py")) or not any(
        "rediagnose" in p.read_text(encoding="utf-8") for p in (ROOT / "brain").glob("*.py"))


@test("ai-health.lua compiles under Lua 5.3")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    f = LuaRuntime().eval("function(s) local f, e = load(s, 'b', 't', {}) return e end")
    assert f(HEALTH) is None, f(HEALTH)


finish()
