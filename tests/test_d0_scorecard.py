"""(D0, G3) The scorecard's Design block (design-track 9): the measures from
the journal's start_project and build_blueprint decisions (level signatures,
the share in the language, hall shapes and arms, landmarks by library and AI,
refusals a landmark), distinct() and judge_distinct(); and the old lines'
output unchanged (on the existing fixture). That was proved against the
scorecard.py of 8a13655, a commit not in every clone; since 0.105.48 against
the committed snapshot tests/fixtures/snapshots/d0_scorecard_*.json.

    python tests/test_d0_scorecard.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from snapshots import snapshot  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import scorecard  # noqa: E402
import test_scorecard as TS  # noqa: E402  (the existing fixture: make_fort, state)


def dec(t, year, tick, action=None, result=None):
    a = {"type": t}
    a.update(action or {})
    return {"kind": "decision", "date": {"year": year, "tick": tick}, "action": a, "result": result or {"ok": True}}


def level(kind, year, tick, **style):
    return dec("start_project", year, tick, {"kind": kind, "style": style},
               {"ok": True, "kind": kind, "z": 90, "tiles": 60})


GRID_A = {"levels": [{"grid": ["##@##", "#...#", "#####"]}], "legend": {}}
GRID_B = {"levels": [{"grid": ["#@#", "#.#", "###"]}], "legend": {}}


def design_journal(variant: str) -> list[dict]:
    """A fort's journal at Guided/Architect: levels in its language, a
    landmark refused twice then built from the library, one by the AI."""
    if variant == "a":
        lv = [level("bedrooms", 250, 1, hall="cruciform", arms="cross", motif="star"),
              level("dining", 250, 2, hall="octagonal", arms="cross", motif="star", scale=130),
              level("temple", 250, 3, hall="cruciform", arms="cross", motif="star", grand=True)]
    elif variant == "b":
        lv = [level("bedrooms", 250, 1, hall="round", arms="ring", motif="wave"),
              level("dining", 250, 2, hall="nave", arms="ring", motif="spiral", scale=90),
              level("temple", 250, 3, hall="round", arms="ring", motif="wave", orient=3)]
    else:   # today's styles: no design keys
        lv = [level("bedrooms", 250, 1, hall="plain"), level("dining", 250, 2, hall="pillared"),
              level("temple", 250, 3, hall="pillared")]
    marks = [
        dec("build_blueprint", 250, 4, {"name": "The Spiral of Ral", "purpose": "descent", "by": "library",
                                        "bp": GRID_A, "site": "S1"},
            {"ok": False, "rejected": True, "error": "a cavern beside",
             "reasons": [{"code": "CAVERN", "level": 2, "words": "a cavern beside"}]}),
        dec("build_blueprint", 250, 5, {"name": "The Spiral of Ral", "purpose": "descent", "by": "library",
                                        "bp": GRID_A, "site": "S2"},
            {"ok": False, "rejected": True, "error": "the way in", "reasons": [{"code": "PATH"}]}),
        dec("build_blueprint", 250, 6, {"name": "The Spiral of Ral", "purpose": "descent", "by": "library",
                                        "bp": GRID_A, "site": "S3", "dry_run": True},
            {"ok": True, "dry_run": True}),                                  # a dry run: not counted
        dec("build_blueprint", 250, 7, {"name": "The Spiral of Ral", "purpose": "descent", "by": "library",
                                        "bp": GRID_A, "site": "S3"},
            {"ok": True, "landmark_id": 1, "project_ids": [11, 12], "levels": 2}),
        dec("build_blueprint", 250, 8, {"name": "Hall of Ral", "purpose": "god_hall", "by": "ai",
                                        "bp": GRID_B if variant != "a" else GRID_A, "site": "S1"},
            {"ok": True, "landmark_id": 2, "project_ids": [13], "levels": 1}),
    ] if variant in ("a", "b") else []
    return lv + marks


def make_design_fort(root: Path, name: str, preset: str, variant: str, design="guided") -> Path:
    path = TS.make_fort(root, name, preset, 4, 50)
    d = path / "logs" / "forts" / "region4-1430"
    st = json.loads((d / "states" / "250-summer.json").read_text())
    st["settings"]["design"] = design
    if variant in ("a", "b"):
        st["landmarks"] = {"list": [{"id": 1, "name": "The Spiral of Ral", "status": "built"},
                                    {"id": 2, "name": "Hall of Ral", "status": "building"}]}
    (d / "states" / "250-summer.json").write_text(json.dumps(st))
    old = (d / "journal.jsonl").read_text()
    (d / "journal.jsonl").write_text(old + "\n" + "\n".join(json.dumps(x) for x in design_journal(variant)))
    return path


def counts(variant):
    entries = design_journal(variant)
    return scorecard.journal_counts(entries, {"year": 250, "tick": 100})


@test("distinct: the same signature sets give 0, disjoint ones 1, a mean over every pair")
def _():
    a = {"bedrooms:plain:corridor:10:rows:0", "dining:pillared:corridor:10:rows:0"}
    b = {"bedrooms:round:ring:10:wave:0", "dining:nave:ring:9:spiral:0"}
    assert scorecard.distinct({"A": a, "B": set(a)}) == 0
    assert scorecard.judge_distinct({"A": a, "B": set(a)}) == "fail"
    assert scorecard.distinct({"A": a, "B": b}) == 1.0
    assert scorecard.judge_distinct({"A": a, "B": b}) == "pass"
    c = set(a) | {"temple:plain:corridor:10:rows:0"}        # shares 2 of 3 with A
    assert abs(scorecard.jaccard_distance(a, c) - 1 / 3) < 1e-9
    assert scorecard.distinct([a, b, c]) == round((1.0 + 1 / 3 + 1.0) / 3, 3)
    assert scorecard.judge_distinct([a, b, c]) == "fail"     # A and C too close
    assert scorecard.judge_distinct({"A": a, "B": b, "C": c}, bar=0.3) == "pass"
    # forts without a level are left out
    assert scorecard.distinct({"A": a, "B": set()}) is None
    assert scorecard.judge_distinct({"A": a}) == "no data"


@test("level_signature: kind, hall, arms, scale band, motif, turn; today's style gets the defaults")
def _():
    sig = scorecard.level_signature
    if scorecard._design is None:
        assert sig("dining", {"hall": "nave", "arms": "ring", "scale": 137, "motif": "star", "orient": 2}) \
            == "dining:nave:ring:13:star:2"
        assert sig("bedrooms", {}) == "bedrooms:plain:corridor:10:rows:0"
    assert sig("dining", {"hall": "nave"}) != sig("dining", {"hall": "round"})
    assert sig("dining", {"arms": "ring"}) != sig("dining", {"arms": "cross"})
    assert sig("dining", {"scale": 80}) != sig("dining", {"scale": 150})
    assert sig("dining", {"motif": "star"}) != sig("dining", {"motif": "wave"})
    assert sig("dining", {}) != sig("temple", {})


@test("design measures from a journal: the language share, shapes, arms, landmarks by whom, refusals")
def _():
    j = counts("a")
    s = {"settings": {"design": "architect"}, "landmarks": {"list": [{"status": "built"}, {"status": "building"}]}}
    m = scorecard.design_measures(s, j)
    assert m["setting"] == "architect"
    assert m["language_pct"] == 100.0
    assert m["hall_shapes"] == 2 and m["arm_patterns"] == 1
    assert m["landmarks_library"] == 1 and m["landmarks_ai"] == 1       # the dry run not counted
    assert m["landmarks_built"] == 1
    assert m["refusals_per_landmark"] == 1.0                            # 2 refusals over 2 landmarks
    assert len(m["signatures"]) == 3 and m["styled"]
    assert len(m["grids"]) == 2
    # today's styles: nothing in a language, no landmarks; no report section: no data
    m0 = scorecard.design_measures({"settings": {}}, counts("plain"))
    assert m0["language_pct"] == 0.0 and m0["landmarks_library"] == 0 and m0["landmarks_built"] is None
    assert m0["refusals_per_landmark"] is None and not m0["styled"]
    assert m0["hall_shapes"] == 2 and m0["arm_patterns"] == 1


@test("the language share counts the last year's levels only")
def _():
    entries = [level("bedrooms", 249, 1, hall="round"), level("dining", 250, 50, hall="plain"),
               level("temple", 250, 60, hall="round")]
    j = scorecard.journal_counts(entries, {"year": 250, "tick": 100})
    m = scorecard.design_measures({}, j)
    assert m["language_pct"] == 50.0, m            # 249's level is more than a year back


@test("forts: two with the same signatures give 0 (fail); different ones above 0.5 (pass), in the report")
def _():
    root = Path(tempfile.mkdtemp())
    a = scorecard.Fort("A", make_design_fort(root, "DF-AI", "War-hold", "a"))
    b = scorecard.Fort("B", make_design_fort(root, "DF-AI-B", "Monastery", "a"))
    md, rows, summ = scorecard.score_full([a, b], None, False)
    assert summ["design"]["distinct"] == 0 and summ["design"]["verdict"] == "fail", summ["design"]
    assert "## Design" in md and "**fail**" in md
    assert "share a drawing" in md and summ["design"]["grids_unique"] is False
    c = scorecard.Fort("C", make_design_fort(root, "DF-AI-C", "Garden fort", "b"))
    md, rows, summ = scorecard.score_full([a, c], None, False)
    assert summ["design"]["distinct"] > 0.5 and summ["design"]["verdict"] == "pass", summ["design"]
    assert "Layout distinctness: " in md and "**pass**" in md
    assert "| landmarks started from the library | 1 | 1 |" in md
    assert "| refusals a landmark | 1 | 1 |" in md
    assert "| Design setting | guided | guided |" in md


@test("old lines unchanged: the existing fixture's report is byte-identical to the snapshot (no Design block)")
def _():
    root = Path(tempfile.mkdtemp())
    pa = TS.make_fort(root, "DF-AI", "War-hold", 10, 40, extra_season=True)
    pb = TS.make_fort(root, "DF-AI-B", "Monastery", 1, 60)
    got = {}
    for now in (False, True):
        new = scorecard.score_full([scorecard.Fort("A", pa), scorecard.Fort("B", pb)], None, now)
        assert "design" not in new[2], now
        got[str(now)] = list(new)
    got["LINES"] = scorecard.LINES
    snapshot("d0_scorecard_plain", got)


@test("old lines unchanged with a design: the rows equal the snapshot's, the Design block only appended")
def _():
    root = Path(tempfile.mkdtemp())
    pa = make_design_fort(root, "DF-AI", "War-hold", "a")
    pb = make_design_fort(root, "DF-AI-B", "Garden fort", "b")
    new = scorecard.score_full([scorecard.Fort("A", pa), scorecard.Fort("B", pb)], None, False)
    head, sep, _ = new[0].partition("## Design")
    assert sep, "no Design block"
    s = json.loads((pa / "logs" / "forts" / "region4-1430" / "states" / "250-summer.json").read_text())
    jn = scorecard.journal_counts(design_journal("a"), s["date"])
    snapshot("d0_scorecard_design", {"rows": new[1], "head": head,
                                     "summary": {k: v for k, v in new[2].items() if k != "design"},
                                     "measures": scorecard.measures(s, jn)})


@test("a Scripts fort with today's styles gets no Design block; one at Guided does")
def _():
    root = Path(tempfile.mkdtemp())
    a = scorecard.Fort("A", make_design_fort(root, "DF-AI", "War-hold", "plain", design="scripts"))
    b = scorecard.Fort("B", make_design_fort(root, "DF-AI-B", "Monastery", "plain", design="scripts"))
    md, _, summ = scorecard.score_full([a, b], None, False)
    assert "## Design" not in md and "design" not in summ
    c = scorecard.Fort("C", make_design_fort(root, "DF-AI-C", "Monastery", "plain", design="guided"))
    md, _, summ = scorecard.score_full([a, c], None, False)
    assert "## Design" in md and summ["design"]["verdict"] == "fail"     # the same signatures: 0 apart


if __name__ == "__main__":
    finish()
