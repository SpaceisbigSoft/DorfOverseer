"""(0.105.30) Construction: the scorecard's six lines and the digest's BUILT line.

    python tests/test_construct_scorecard.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import digest  # noqa: E402
import scorecard  # noqa: E402

KEYS = ("built_up", "roofed_up", "gate_walls", "cavern_walls", "block_pct", "soil_floors")


def survey(total=0, walls=0, floors=0, blocks=0, up=0, roofed=0, gate=0, wings=0, cavern=0, planned=0, **ai):
    """A constructions section shaped as the spec's survey() (lua/ai-constructions.lua)."""
    return {"total": total,
            "by_shape": {"wall": walls, "floor": floors, "ramp": 0, "stair_up": 0, "stair_down": 0,
                         "stair_updown": 0, "fortification": 0, "other": 0},
            "by_item": {"blocks": blocks, "boulder": total - blocks, "log": 0, "bar": 0, "other": 0},
            "surface": {"total": up, "wall": min(up, walls)}, "underground": {"total": total - up},
            "roofed_surface_tiles": roofed,
            "planned": {"n": planned, "by_type": {"Wall": planned} if planned else {}},
            "ai": dict({"keep": 0, "halls": 0, "gate_pieces": gate, "wings": wings, "cavern_walls": cavern,
                        "cistern": 0, "room_walls": 0}, **ai),
            "ms": 3}


def state(preset, cons=None):
    s = {"settings": {"preset": preset}, "date": {"year": 260, "season": "spring", "tick": 10},
         "dwarves": {"adults": 30, "total": 30, "in_squads": 3, "idle_adults": 2, "stress": {}},
         "buildings": {"other": {}, "zones": {}, "workshops": {}}, "farms": {}, "crossings": {"z": 100}}
    if cons is not None:
        s["constructions"] = cons
    return s


def journal(floored=0):
    out = []
    if floored:
        out.append({"kind": "decision", "date": {"year": 259, "tick": 5},
                    "action": {"type": "floor_rooms", "project_id": 4},
                    "result": {"ok": True, "placed": floored}})
        out.append({"kind": "decision", "date": {"year": 259, "tick": 6},       # a dry run: not counted
                    "action": {"type": "floor_rooms", "project_id": 5},
                    "result": {"ok": True, "placed": 99, "dry_run": True}})
    return out


def m(preset, cons=None, floored=0):
    s = state(preset, cons)
    return scorecard.measures(s, scorecard.journal_counts(journal(floored), s["date"]))


@test("the six lines are in LINES with the spec's sliders, keys and presets")
def _():
    W, M, ME, H, D, G = scorecard.W, scorecard.M, scorecard.ME, scorecard.H, scorecard.D, scorecard.G
    want = [("Surface", "constructed tiles above ground", "built_up", {G, ME}, {D, H}),
            ("Surface", "roofed surface tiles", "roofed_up", {G, ME}, {D, H}),
            ("Fortification", "gate walls and wings", "gate_walls", {W}, set()),
            ("Fortification", "cavern openings walled", "cavern_walls", {H}, set()),
            ("Craftsmanship", "constructions of blocks, %", "block_pct", {ME, M}, set()),
            ("Grandeur", "soil floors finished", "soil_floors", {G, M}, {W})]
    for line in want:
        assert line in scorecard.LINES, line
    assert len({ln[2] for ln in scorecard.LINES}) == len(scorecard.LINES), "a measure key twice"


@test("measures read the constructions section")
def _():
    got = m("Garden fort", survey(total=120, walls=40, floors=70, blocks=90, up=100, roofed=35,
                                  gate=6, wings=8, cavern=3, soil_floors=18))
    assert {k: got[k] for k in KEYS} == {"built_up": 100, "roofed_up": 35, "gate_walls": 14, "cavern_walls": 3,
                                         "block_pct": 75.0, "soil_floors": 18}, got


@test("no section (an older bridge): every line is no data, never a false 0")
def _():
    got = m("War-hold")
    assert all(got[k] is None for k in KEYS), got
    got = m("War-hold", {"error": "survey failed"})
    assert all(got[k] is None for k in KEYS), got


@test("the census's copy is read when the report has none")
def _():
    s = state("Merchant city")
    s["census"] = {"constructions": survey(total=10, blocks=10, up=10)}
    got = scorecard.measures(s, scorecard.journal_counts([], s["date"]))
    assert got["built_up"] == 10 and got["block_pct"] == 100.0, got


@test("nothing built: zeros (a flat line), block share 0")
def _():
    got = m("Monastery", survey())
    assert got["built_up"] == 0 and got["block_pct"] == 0.0 and got["gate_walls"] == 0, got


@test("ai registry entries as lists or dicts are counted")
def _():
    c = survey(total=5)
    c["ai"].update(gate_pieces=[{"x": 1}, {"x": 2}], wings={"walls": 9}, cavern_walls={"tiles": [1, 2, 3]})
    got = m("Hermit hold", c)
    assert got["gate_walls"] == 11 and got["cavern_walls"] == 3, got
    del c["ai"]
    got = m("Hermit hold", c)
    assert got["gate_walls"] is None and got["cavern_walls"] is None, got


@test("soil floors: from the journal's floor_rooms when the survey has no count (dry runs left out)")
def _():
    got = m("Garden fort", survey(total=20), floored=24)
    assert got["soil_floors"] == 24, got


@test("six forts: each preset wins its construction lines")
def _():
    forts = {
        "A": ("War-hold", survey(total=60, walls=60, blocks=30, up=20, gate=10, wings=10), 0),
        "B": ("Monastery", survey(total=50, floors=50, blocks=45, up=10, soil_floors=20), 20),
        "C": ("Merchant city", survey(total=150, walls=40, floors=110, blocks=148, up=120, roofed=35,
                                      soil_floors=5), 0),
        "D": ("Hermit hold", survey(total=10, walls=10, blocks=1, up=0, cavern=6, soil_floors=2), 0),
        "E": ("Deep mine", survey(total=8, walls=8, blocks=4, up=0, soil_floors=1), 0),
        "F": ("Garden fort", survey(total=160, walls=40, floors=120, blocks=120, up=150, roofed=40,
                                    soil_floors=30), 30),
    }
    with tempfile.TemporaryDirectory() as tmp:
        args = []
        for lb, (preset, cons, floored) in forts.items():
            d = Path(tmp) / lb / "logs" / "forts" / "region1-77"
            (d / "states").mkdir(parents=True)
            (d / "states" / "260-spring.json").write_text(json.dumps(state(preset, cons)))
            (d / "journal.jsonl").write_text("\n".join(json.dumps(x) for x in journal(floored)))
            args.append(scorecard.Fort(lb, Path(tmp) / lb))
        md, rows = scorecard.score(args, None, False)
    res = {r["line"]: r["result"] for r in rows}
    for what in ("constructed tiles above ground", "gate walls and wings", "cavern openings walled",
                 "constructions of blocks, %", "soil floors finished"):
        assert res[what] == "pass", (what, res[what])
    # roofed: D and E share 0 with A and B, so the low side is only half
    assert res["roofed surface tiles"] in ("pass", "half"), res["roofed surface tiles"]
    assert "constructed tiles above ground" in md


@test("digest BUILT line: walls, floors, block share, above ground, waiting, stages")
def _():
    s = state("Garden fort", survey(total=100, walls=30, floors=70, blocks=80, up=60, roofed=35, planned=12))
    s["buildings"]["keep"] = {"stage": "roof", "roof_planned": 9}
    s["buildings"]["halls"] = {"list": [{"kind": "field_hall", "stage": "walls", "walls_planned": 20}]}
    line = digest.built_line(digest.normalize(s))
    assert line.startswith("BUILT 30 walls, 70 floors (80% blocks), 60 above ground; 12 waiting"), line
    assert "roofed surface 35" in line and "keep roof (9 left)" in line and "field hall walls (20 left)" in line, line
    assert line in digest.digest(s)


@test("digest: no section or nothing built gives no line and no missing-section note")
def _():
    s = state("Monastery")
    out = digest.digest(s)
    assert "BUILT" not in out and "constructions" not in digest.normalize(state("Monastery"))["_errors"], out
    assert digest.built_line(digest.normalize(state("Monastery", survey()))) == ""
    s = state("Monastery", {"error": "boom"})
    assert "BUILT" not in digest.digest(s) and "constructions" in s["_errors"]
    # a finished keep and nothing else counts as nothing to say only when nothing is built
    s = state("Garden fort", survey())
    s["buildings"]["keep"] = {"stage": "done"}
    assert digest.built_line(digest.normalize(s)) == ""


@test("digest numbers and diff unchanged by the section")
def _():
    a = state("War-hold")
    b = state("War-hold", survey(total=10, walls=10))
    assert digest.numbers(digest.normalize(a)) == digest.numbers(digest.normalize(b))


finish()
