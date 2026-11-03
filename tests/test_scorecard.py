"""Tests for brain/scorecard.py (14.1's slider scorecard).

    python tests/test_scorecard.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

import scorecard  # noqa: E402

RESULTS = []


def test(name):
    def wrap(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


def state(preset, year, season, squads, adults=20, farm=50):
    return {"settings": {"preset": preset}, "date": {"year": year, "season": season, "tick": 10},
            "dwarves": {"adults": adults, "total": adults, "in_squads": squads, "idle_adults": 2,
                        "stress": {"unhappy": 1}},
            "buildings": {"other": {"Statue": 3}, "zones": {"Barracks": 1}, "workshops": {}},
            "farms": {"tiles": farm, "plots": 4}, "crossings": {"z": 100}}


def make_fort(root: Path, name: str, preset: str, squads: int, farm: int, extra_season=False) -> Path:
    d = root / name / "logs" / "forts" / "region4-1430"
    (d / "states").mkdir(parents=True)
    (d / "states" / "250-summer.json").write_text(json.dumps(state(preset, 250, "summer", squads, farm=farm)))
    if extra_season:
        (d / "states" / "251-spring.json").write_text(
            json.dumps(state(preset, 251, "spring", squads + 5, farm=farm)))
    lines = [
        {"kind": "decision", "date": {"year": 250, "tick": 5}, "action": {"type": "start_project", "kind": "barracks"},
         "result": {"ok": True, "kind": "barracks", "z": 98, "tiles": 80}},
        {"kind": "decision", "date": {"year": 250, "tick": 6}, "action": {"type": "bring_goods"},
         "result": {"ok": True, "value": 100}},
        {"kind": "decision", "date": {"year": 251, "tick": 6}, "action": {"type": "bring_goods"},
         "result": {"ok": True, "value": 999}},   # after the date: not counted
        {"kind": "decision", "date": {"year": 250, "tick": 7}, "action": {"type": "mine_ore"},
         "result": {"ok": False}},                 # refused: not counted
    ]
    (d / "journal.jsonl").write_text("\n".join(json.dumps(x) for x in lines))
    return root / name


@test("judge: pass, half, fail, flat, no data")
def _():
    j = scorecard.judge
    assert j({"a": 3, "b": 1, "c": 2}, {"a"}, {"b"}) == "pass"
    assert j({"a": 3, "b": 2, "c": 1}, {"a"}, {"b"}) == "half"
    assert j({"a": 1, "b": 3, "c": 2}, {"a"}, {"b"}) == "fail"
    assert j({"a": 2, "b": 2}, {"a"}, set()) == "flat"
    assert j({"a": None, "b": 2}, {"a"}, set()) == "no data"
    assert j({"x": 1, "y": 2}, {"a"}, set()) == "no data"


@test("forts compared at their common season, journal cut at the date")
def _():
    root = Path(tempfile.mkdtemp())
    a = scorecard.Fort("A", make_fort(root, "DF-AI", "War-hold", 10, 40, extra_season=True))
    b = scorecard.Fort("B", make_fort(root, "DF-AI-B", "Monastery", 1, 60))
    md, rows = scorecard.score([a, b], None, False)
    assert "all at 250-summer" in md, md[:200]
    sol = next(r for r in rows if r["line"].startswith("soldiers"))
    assert sol["values"] == {"A": 50.0, "B": 5.0} and sol["result"] == "pass", sol
    val = next(r for r in rows if r["line"] == "value taken to caravans")
    assert val["values"] == {"A": 100, "B": 100}, val
    veins = next(r for r in rows if r["line"] == "veins mined")
    assert veins["values"] == {"A": 0, "B": 0}, veins
    md2, rows2 = scorecard.score([a, b], None, True)
    assert "newest season" in md2
    sol2 = next(r for r in rows2 if r["line"].startswith("soldiers"))
    assert sol2["values"]["A"] == 75.0, sol2


@test("default forts: DF-AI and DF-AI-x beside the folder")
def _():
    root = Path(tempfile.mkdtemp())
    make_fort(root, "DF-AI", "War-hold", 10, 40)
    make_fort(root, "DF-AI-C", "Merchant city", 2, 40)
    forts = scorecard.default_forts(root / "DF-AI")
    assert [f.label for f in forts] == ["A", "C"], [f.label for f in forts]
    assert forts[1].preset == "Merchant city"


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
