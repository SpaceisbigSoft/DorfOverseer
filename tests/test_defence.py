"""Tests for brain/defence.py (milestone 5b: sieges judged per gate, design
scores, trying new designs, traps per gate) and its use in the weights engine.

    python tests/test_defence.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

import defence  # noqa: E402
import learning  # noqa: E402
from planner import Memory  # noqa: E402
from weights import choose  # noqa: E402

TMP = Path(tempfile.mkdtemp())
learning.PLAYER_FILE = TMP / "player-memory.json"
RESULTS = []
YEAR = 403200
DAY = 1200


def test(name):
    def wrap(fn):
        learning.PLAYER_FILE.unlink(missing_ok=True)
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            import traceback
            RESULTS.append((name, False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"))
        return fn
    return wrap


def state_at(tick, year=150):
    return {"date": {"year": year, "tick": tick, "day": 1, "month": "Granite", "season": "spring"}}


def fort_after_siege(events, variant="plain", traps=None, built_tick=1000, seed="Run#7"):
    """A fort whose siege ran from day 10 to day 20 of year 150, now day 25."""
    m = Memory()
    m.culture = {"seed": seed}
    t0 = 150 * YEAR
    m.chronicle = {"phase": {"now": "recovery", "log": [
        {"phase": "growth", "tick": t0}, {"phase": "siege", "tick": t0 + 10 * DAY},
        {"phase": "recovery", "tick": t0 + 20 * DAY}]}}
    reg = {"gate:35,120,112": {"kind": "gate", "variant": variant, "tick": t0 + built_tick, "status": "built"}}
    if traps:
        reg["traps:35,120,112"] = {"kind": "traps", "variant": traps, "tick": t0 + built_tick}
    m.atlas = {"entrances": {"35,120,112": {"kind": "cavern", "elevation": -17}}, "registry": reg,
               "events": [dict(e, t=t0 + e["t"], near=e.get("near", "entrance:35,120,112")) for e in events]}
    return m, state_at(25 * DAY)


@test("verdicts: held with no deaths, costly when enemies died twice as often, else failed; untested if nobody came")
def _():
    assert defence.verdict(0, 0, 0) is None
    assert defence.verdict(5, 0, 0) == "held"
    assert defence.verdict(5, 1, 3) == "costly"
    assert defence.verdict(5, 2, 1) == "failed"


@test("a siege is judged once, after it ends, per gate that saw the enemy; traps behind it are judged too")
def _():
    evs = [{"k": "threat_at_gate", "t": 12 * DAY}, {"k": "threat_at_gate", "t": 13 * DAY},
           {"k": "kill", "t": 13 * DAY}]
    m, s = fort_after_siege(evs, variant="drawbridge", traps="cage")
    lines = defence.judge_sieges(s, m)
    assert len(lines) == 1 and "the drawbridge gate and cage traps held" in lines[0] and "x35 y120" in lines[0], lines
    sc = m.learning["defence"]["scores"]
    assert sc["defence:drawbridge"]["held"] == 1 and sc["traps:cage"]["held"] == 1, sc
    assert m.atlas["registry"]["gate:35,120,112"]["sieges"][0]["verdict"] == "held"
    assert defence.judge_sieges(s, m) == []                       # not twice
    # still under siege, or just over: not yet
    m, s = fort_after_siege(evs)
    m.chronicle["phase"]["now"] = "siege"
    assert defence.judge_sieges(s, m) == []
    m, _ = fort_after_siege(evs)
    assert defence.judge_sieges(state_at(20 * DAY + 100), m) == []
    # a gate built after the siege began isn't judged by it; nor one nobody came to
    m, s = fort_after_siege(evs, built_tick=15 * DAY)
    assert defence.judge_sieges(s, m) == []
    m, s = fort_after_siege([{"k": "threat_at_gate", "t": 30 * DAY}])
    assert defence.judge_sieges(s, m) == []


@test("deaths at a gate make it fail; the engine leans away from a failed design and toward a proven one")
def _():
    m, s = fort_after_siege([{"k": "threat_at_gate", "t": 12 * DAY}, {"k": "death", "t": 12 * DAY},
                             {"k": "death", "t": 13 * DAY}], variant="plain")
    assert "the plain gate failed" in defence.judge_sieges(s, m)[0]
    b = defence.engine_bonuses(m)
    assert b["defence"]["plain"][0] < 0 and "failed 1" in b["defence"]["plain"][1], b
    held = {"n": 4, "held": 4, "costly": 0, "failed": 0}
    assert defence.bonus(held) > 0.3 and defence.bonus({"n": 1, "held": 1}) < defence.bonus(held)
    assert -defence.BONUS_MAX <= defence.bonus({"n": 50, "failed": 50}) < 0
    # in the engine: a proven drawbridge beats plain for a fort that leaned plain
    traits = {"engineering": 60, "caution": 30, "fortification": -60}
    base = choose("defence", traits, {"seed": "x"})
    assert base["id"] == "plain", base
    hist = {"seed": "x", "design": {"defence": {"drawbridge": [0.45, "held 4 of 4 siege(s)"],
                                                "plain": [-0.45, "held 0 of 3 siege(s), failed 3"]}}}
    c = choose("defence", traits, hist)
    assert c["id"] == "drawbridge" and "held 4 of 4 siege(s)" in c["drivers"], c


@test("your other forts' verdicts count at half weight; this fort's own copy isn't counted twice")
def _():
    m, s = fort_after_siege([{"k": "threat_at_gate", "t": 12 * DAY}], variant="fortified", seed="A#1")
    defence.judge_sieges(s, m)
    p = learning.load_player()
    assert p["design"]["A#1"]["defence:fortified"]["held"] == 1, p
    other = Memory()
    other.culture = {"seed": "B#2"}
    b = defence.engine_bonuses(other)["defence"]["fortified"]
    own = defence.engine_bonuses(m)["defence"]["fortified"]
    assert 0 < b[0] < own[0], (b, own)
    # an autosave folder of the same fort (same site id) isn't "another fort"
    same = Memory()
    same.culture = {"seed": "autosave 1#1"}
    assert "defence" not in defence.engine_bonuses(same)


@test("Caution sets how often a promising design is tried: never at +100; never one that failed")
def _():
    assert defence.explore({"caution": 100}, 150)["rate"] == 0
    assert defence.explore({}, 150)["rate"] == 0.15 and defence.explore({"caution": -100}, 150)["rate"] == 0.3
    traits = {"caution": 30, "fortification": 20}            # narrow and fortified close
    plain = choose("defence", traits, {"seed": "s"})
    tried = [y for y in range(150, 200)
             if choose("defence", traits, {"seed": "s", "explore": {"rate": 0.3, "turn": y}})["trying"]]
    assert 5 <= len(tried) <= 30, len(tried)
    c = choose("defence", traits, {"seed": "s", "explore": {"rate": 0.3, "turn": tried[0]}})
    assert c["id"] != plain["id"] and "trying something new" in c["drivers"][0], c
    # same year, same answer (a reload never changes it)
    assert choose("defence", traits, {"seed": "s", "explore": {"rate": 0.3, "turn": tried[0]}})["id"] == c["id"]
    bad = {"seed": "s", "explore": {"rate": 1.0, "turn": tried[0]},
           "design": {"defence": {c["id"]: [-0.05, "held 0 of 2 siege(s), failed 2"]}}}
    assert not choose("defence", traits, bad)["trying"]


@test("traps per gate: 2 to 8, more with Fortification, Engineering and Caution")
def _():
    assert defence.trap_count({}) == 3
    assert defence.trap_count({"fortification": 100, "engineering": 100, "caution": 100}) == 7
    assert defence.trap_count({"fortification": 200, "engineering": 200, "caution": 200}) == 8
    assert defence.trap_count({"fortification": -200}) == 2


@test("the learned view's lines")
def _():
    m, s = fort_after_siege([{"k": "threat_at_gate", "t": 12 * DAY}], variant="grand", traps="weapon")
    defence.judge_sieges(s, m)
    lines = defence.lesson_lines(m)
    assert "the grand gate: held 1 of 1 siege(s)" in lines and "weapon traps: held 1 of 1 siege(s)" in lines, lines


@test("review: a gate's records and events filed a tile or two apart (walls move the entrance's tile) are one gate")
def _():
    m, s = fort_after_siege([{"k": "threat_at_gate", "t": 12 * DAY, "near": "entrance:36,121,112"},
                             {"k": "death", "t": 12 * DAY, "near": "entrance:36,121,112"},
                             {"k": "kill", "t": 12 * DAY, "near": "entrance:35,120,112"},
                             {"k": "kill", "t": 12 * DAY, "near": "entrance:35,120,112"}],
                            variant="fortified")
    m.atlas["registry"]["traps:37,120,112"] = {"kind": "traps", "variant": "stonefall", "tick": 150 * YEAR + 1000}
    m.atlas["registry"]["doors:36,121,112"] = {"kind": "doors", "variant": "doors", "tick": 150 * YEAR + 1000}
    lines = defence.judge_sieges(s, m)
    assert len(lines) == 1 and "the fortified gate and stonefall traps costly" in lines[0], lines
    sc = m.learning["defence"]["scores"]
    assert set(sc) == {"defence:fortified", "traps:stonefall"}, sc       # its doors are part of the gate


@test("review: a wipe forgets the verdicts but doesn't re-judge old sieges")
def _():
    m, s = fort_after_siege([{"k": "threat_at_gate", "t": 12 * DAY}])
    assert defence.judge_sieges(s, m)
    learning.wipe(m)
    assert m.learning["defence"]["scores"] == {} and defence.judge_sieges(s, m) == []


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
