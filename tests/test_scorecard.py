"""Tests for brain/scorecard.py (14.1's slider scorecard).

    python tests/test_scorecard.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import scorecard  # noqa: E402


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


def _level(customs, ok=True, tick=5, z=90, with_key=True):
    a = {"type": "start_project", "kind": "dining"}
    if with_key:
        a["customs"] = customs
    return {"kind": "decision", "date": {"year": 250, "tick": tick}, "action": a,
            "result": {"ok": ok, "kind": "dining", "z": z, "tiles": 60}}


@test("customs: journal levels keep action customs, six lines count each preset's own")
def _():
    date = {"year": 250, "tick": 10}
    entries = [
        _level(["cloister"]), _level(["cells"]), _level(["wide_ways", "market_gate"]),
        _level(["hidden_hold"]), _level(["gate_barracks", "armoury"]), _level(["ore_piles"]),
        _level(["deep_hall"]), _level(["field_kitchens"]),
        _level(["cloister"], ok=False),            # refused: not a level
        _level(["cloister"], tick=20),             # after the date: not counted
        _level("cloister"),                        # not a list: ignored
        _level([], with_key=False),                # an older journal line: no key
    ]
    j = scorecard.journal_counts(entries, date)
    assert len(j["levels"]) == 10, j["levels"]
    assert j["levels"][0]["customs"] == ["cloister"] and j["levels"][-1]["customs"] == [], j["levels"]
    m = scorecard.measures({}, j)
    got = {k: m[k] for k in m if k.startswith("custom_")}
    assert got == {"custom_W": 1, "custom_M": 2, "custom_ME": 1, "custom_H": 1, "custom_D": 2,
                   "custom_G": 1}, got
    keys = [ln[2] for ln in scorecard.LINES if ln[2].startswith("custom_")]
    assert keys == ["custom_M", "custom_ME", "custom_H", "custom_W", "custom_D", "custom_G"], keys
    for _s, _w, k, high, low in scorecard.LINES:
        if k.startswith("custom_"):
            owner = next(o for o, kk in scorecard.CUSTOM_KEYS.items() if "custom_" + kk == k)
            assert high == {owner} and low == set(), (k, high)
            assert len(scorecard.CUSTOM_IDS[owner]) == 2, scorecard.CUSTOM_IDS


@test("customs: no customs anywhere (default sliders) gives zeros, a flat line")
def _():
    j = scorecard.journal_counts([_level([], with_key=False)], {"year": 251, "tick": 0})
    m = scorecard.measures({}, j)
    assert all(m["custom_" + k] == 0 for k in scorecard.CUSTOM_KEYS.values()), m
    assert scorecard.judge({"War-hold": 0, "Monastery": 0}, {"Monastery"}, set()) == "flat"


@test("customs: the owner fort wins its line in a full score, old-run journal lines left out")
def _():
    root = Path(tempfile.mkdtemp())
    a = scorecard.Fort("A", make_fort(root, "DF-AI", "War-hold", 10, 40))
    b = scorecard.Fort("B", make_fort(root, "DF-AI-B", "Monastery", 1, 60))
    jf = b.fort_dir / "journal.jsonl"
    jf.write_text(jf.read_text() + "\n" + json.dumps(_level(["cloister"])) + "\n" +
                  json.dumps(_level(["cells"], tick=6)))
    jw = a.fort_dir / "journal.jsonl"
    jw.write_text(jw.read_text() + "\n" + json.dumps(_level(["armoury"])))
    _md, rows = scorecard.score([a, b], None, False)
    mon = next(r for r in rows if r["line"] == "cloister temples and cells")
    assert mon["values"] == {"A": 0, "B": 2} and mon["result"] == "pass", mon
    war = next(r for r in rows if r["line"] == "barracks by the gate, armouries")
    assert war["values"] == {"A": 1, "B": 0} and war["result"] == "pass", war
    # a journal line written before this run began is the old run's: not counted
    old = dict(_level(["cloister"], tick=7), time="2026-10-01T00:00:00")
    new = dict(_level(["cells"], tick=8), time="2026-11-02T00:00:00")
    jf.write_text(jf.read_text() + "\n" + json.dumps(old) + "\n" + json.dumps(new))
    b2 = scorecard.Fort("B", b.folder)
    b2.run = "2026-11-01T00:00:00"
    j = scorecard.journal_counts(b2.journal(), {"year": 250, "tick": 10})
    # (lines with no "time" are kept, as the scorecard always has)
    assert [lv["customs"] for lv in j["levels"] if lv["customs"]] == [["cloister"], ["cells"], ["cells"]], \
        j["levels"]


if __name__ == "__main__":
    finish()
