"""(0.105.113 item11) The Welfare slider wins a scorecard line.

The scorecard of 25 Nov (88 lines): Welfare won none. Its four lines measured
what the slider barely moves: unhappy % (B, Welfare +80, 42.9: its killings),
good meals (A, War-hold, 2.3 a dwarf: a cook of skill 25), drink kinds (C,
Merchant city, 11: the caravans). What Welfare sizes itself is the hospital
(citizens / 20 x 2^(Welfare/100) + 2 beds), but only the first one: after it,
beds came only for wounded lying on the floor (F, Garden fort +40, 97 dwarves:
4 beds, as A at -40 with 93).

Fixed: above Welfare 0 the hospitals grow to the slider's beds in settled
times, in an ordinary slot (planner_building_rooms.hospital_shortfall
`generous`, planner_building); the scorecard's Welfare line "hospital beds per
100 dwarves (peak)" (scorecard.WELFARE_LINES, put in once a state has
health.hospital).

    python tests/test_i113_welfare.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

import scorecard  # noqa: E402
from planner import PLANNER_CONFIG as CFG  # noqa: E402
from planner_building_rooms import hospital_shortfall  # noqa: E402


def fort(cit, beds, resting=0):
    return {"dwarves": {"total": cit}, "locations": {"count": {"HOSPITAL": 1}},
            "health": {"hospital": [{"id": 3, "zones": [{"beds": beds}]}], "resting": resting}}


@test("F (Welfare +40, 97 dwarves, 4 beds, nobody resting): another hospital, as generosity")
def _():
    hp = hospital_shortfall(fort(97, 4), {"welfare": 40}, CFG)
    assert hp and hp["generous"] and hp["want"] == 9 and hp["beds"] == 5, hp


@test("A (Welfare -40, 93 dwarves, 4 beds) and a neutral fort: none until the wounded need it")
def _():
    assert hospital_shortfall(fort(93, 4), {"welfare": -40}, CFG) is None
    assert hospital_shortfall(fort(197, 5), {}, CFG) is None
    hp = hospital_shortfall(fort(93, 4, resting=12), {"welfare": -40}, CFG)
    assert hp and not hp["generous"] and hp["unbedded"] == 8, hp


@test("generous only past a few beds short; the wounded's case is never 'generous'")
def _():
    assert hospital_shortfall(fort(40, 5), {"welfare": 80}, CFG) is None     # want 6: 1 short
    hp = hospital_shortfall(fort(97, 4, resting=10), {"welfare": 40}, CFG)
    assert hp and not hp["generous"], hp


@test("the planner: generous beds in an ordinary slot (not urgent), the wounded's urgent")
def _():
    import planner_building as pb
    src = Path(pb.__file__).read_text(encoding="utf-8")
    i = src.index('if hp and hp.get("generous")')
    block = src[i:src.index("elif hp and", i)]
    assert '"urgent"' not in block and "settled_times" in block and 'max_open") or 2)' in block


@test("scorecard: the Welfare line from health.hospital, per 100 dwarves at the peak; out without it")
def _():
    s = {"dwarves": {"total": 29}, "health": {"hospital": [{"zones": [{"beds": 10}, {"beds": 2}]},
                                                           {"zones": [{"beds": 10}]}]}}
    j = {"levels": [], "ok": {}, "petitions_yes": 0, "petitions_no": 0, "trade_value": 0, "peak_pop": 100}
    m = scorecard.measures(s, j)
    assert m["hospital_beds_pk"] == 22.0, m.get("hospital_beds_pk")
    s.pop("health")
    assert "hospital_beds_pk" not in scorecard.measures(s, j)
    lines = scorecard.welfare_lines(scorecard.LINES, [{"hospital_beds_pk": 4.3}, {}])
    i = [x[2] for x in lines].index("hospital_beds_pk")
    assert lines[i - 1][0] == "Welfare" and lines[i + 1][0] != "Welfare", lines[i - 1:i + 2]
    assert scorecard.welfare_lines(scorecard.LINES, [{}, {}]) == scorecard.LINES


@test("scorecard: the 25 Nov forts' beds judge pass (B's 22 for its peak the most); before item11 F trailed")
def _():
    hi, lo = scorecard.WELFARE_LINES[0][3], scorecard.WELFARE_LINES[0][4]
    P = scorecard
    now = {P.W: 4.3, P.M: 22.0, P.ME: 2.5, P.H: 0.0, P.D: 5.5, P.G: 4.1}
    assert scorecard.judge(now, hi, lo) == "pass"
    grown = dict(now, **{P.G: 9.3})
    assert scorecard.judge(grown, hi, lo) == "pass"


if __name__ == "__main__":
    finish()
