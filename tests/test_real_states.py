"""The planner on real game states: every report kept from a real fort
(tests/fixtures/real/*.json, copied from logs/forts/<fort>/states/) is
planned, selected and recorded without errors, and nothing it proposes is
malformed. The other tests use fake forts, which hold only what we believed
the game looks like; these hold what it actually sent.

    python tests/test_real_states.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import run, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from digest import normalize  # noqa: E402
from planner import Memory, plan, record, select  # noqa: E402

STATES = sorted((ROOT / "tests" / "fixtures" / "real").glob("*.json"))


def crashed(notes: list) -> list:
    """The notes plan()._guard writes for a rule that raised (13c): the cycle
    goes on, so only these notes show that a rule crashed on the report."""
    return [n for n in notes if isinstance(n, str) and n.startswith("rule ") and " failed (" in n]


def check(path: Path) -> None:
    state = normalize(json.loads(path.read_text(encoding="utf-8")))
    m = Memory()
    for _ in range(3):                                   # three cycles, as if nothing changed
        props, notes = plan(copy.deepcopy(state), m)
        for p in props:
            assert isinstance(p.action, dict) and isinstance(p.action.get("type"), str), p
            assert isinstance(p.reason, str) and p.reason, p
            json.dumps(p.action)                         # it must go over the wire
        assert all(isinstance(n, str) for n in notes), notes
        assert not crashed(notes), crashed(notes)        # no rule raised on this report
        allowed, _ = select(props, state, m)
        record([(p, {"ok": False, "error": "refused (test)"}) for p in allowed], state, m)


for path in STATES:
    run(path.name, lambda path=path: check(path))


def _region2() -> dict:
    return normalize(json.loads((ROOT / "tests" / "fixtures" / "real" / "region2-0.42-y51-winter.json")
                                .read_text(encoding="utf-8")))


def _fed_small_fort() -> None:
    """region2, winter y51: 18 dwarves, farms, 135 food and 25 drinks a dwarf,
    no bins. 0.44 called it young (under 20 dwarves) for a year: no crafts,
    no wealth, no migrants. It is established, and orders bins."""
    from planner import PLANNER_CONFIG, young_fort
    s = _region2()
    assert s["dwarves"]["total"] == 18
    assert not young_fort(s, PLANNER_CONFIG)
    props, notes = plan(copy.deepcopy(s), Memory())
    assert not crashed(notes), crashed(notes)
    b = [p for p in props if p.rule == "bins"]
    assert b and b[0].action == {"type": "work_order", "recipe": "wooden_bin", "amount": 9}, b
    hungry = copy.deepcopy(s)
    hungry["stocks"].update(prepared_meals=0, fish=0, raw_fish=0, plants=20, plant_growths=0)
    assert young_fort(hungry, PLANNER_CONFIG)                    # not fed yet: young, food first


def _readiness() -> None:
    """region2, spring y52: the stair's hatch rebuilt, 3 soldiers (2 wanted)
    but no helms and one weapon, no hospital, the well dismantled by ice."""
    import report
    s = normalize(json.loads((ROOT / "tests" / "fixtures" / "real" / "region2-0.48-y52-spring.json")
                             .read_text(encoding="utf-8")))
    line = report.readiness_line(s)
    assert line.startswith("NOT YET: ") and "no hospital" in line and "no well" in line and "helms 0" in line, line
    assert "ways in that can be closed 1 of 1" in line.split("(ready:")[1], line


for name, fn in (("a fed fort of 18 is not young; it orders bins", _fed_small_fort),
                 ("ready for a siege? region2 in spring y52: not yet, and why", _readiness)):
    run(name, fn)


if __name__ == "__main__":
    finish(skipped=None if STATES else "no real states in tests/fixtures/real yet")
