"""(R29 W5) The library and its books: every fort's "0 books" was the report's
`books` (#copied_artifacts, a list DF never fills in a fort), while A held 7
codices and B 11 plus 11 scribes' copies (probes 25 Nov 21:32); no codex in
the six forts was written there: the AI never made a scholar's post. Now the
locations report counts the written items on the library's bookcases and in
its chests (`books`, `blank`), the paper section counts the fort's written
works (`writing`: items, works, copies, own), the digest shows them (BOOKS
line, numbers' `books`), and the staffing rule makes and fills scholars'
posts (more as the fort grows), giving back an unhappy scholar's post.

    python tests/test_w5_library.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish  # noqa: E402

import digest  # noqa: E402
import planner_health as PH  # noqa: E402
from planner import Memory, plan, PLANNER_CONFIG as CFG  # noqa: E402

test = make_test()
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LUA = ROOT / "lua"


def lib(**kw):
    e = {"id": 6, "type": "LIBRARY", "books": 6, "have": {"paper": 4}, "want": {"paper": 10},
         "flags": ["NON_CITIZENS_ALLOWED"], "jobs": {"SCRIBE": {"posts": 1, "filled": 1}}}
    e.update(kw)
    return e


def state(citizens=60, **kw):
    return {"dwarves": {"total": citizens}, "locations": {"list": [lib(**kw)]}}


def staff(s):
    props = []
    PH._staff_rule(s, dict(CFG), props)
    return [p for p in props if p.rule == "staff"]


@test("scholars wanted: one per 30 citizens up to 3; none under 20 citizens or without blank paper")
def _():
    assert PH.scholars_wanted(state(60), lib(), CFG) == 2
    assert PH.scholars_wanted(state(25), lib(), CFG) == 1          # at least one from 20 citizens
    assert PH.scholars_wanted(state(200), lib(), CFG) == 3
    assert PH.scholars_wanted(state(19), lib(), CFG) == 0
    assert PH.scholars_wanted(state(60), lib(have={"paper": 0}), CFG) == 0
    assert PH.scholars_wanted(state(60), lib(have={"paper": 0}, blank=2), CFG) == 2   # the report's own count


@test("staffing: the library's scholar post made (A, D: a scribe and no scholar), then filled, then a second")
def _():
    p = staff(state(60))
    assert p and p[0].action == {"type": "add_posts", "location_id": 6, "posts": ["SCHOLAR"]}, p
    s = state(60, jobs={"SCRIBE": {"posts": 1, "filled": 1}, "SCHOLAR": {"posts": 1, "filled": 0}})
    p = staff(s)
    assert p and p[0].action == {"type": "staff_location", "location_id": 6, "post": "SCHOLAR"}, p
    s = state(60, jobs={"SCRIBE": {"posts": 1, "filled": 1}, "SCHOLAR": {"posts": 1, "filled": 1}})
    p = staff(s)
    assert p and p[0].action == {"type": "add_posts", "location_id": 6, "posts": ["SCHOLAR"]}, p
    assert "1 scholar(s) of 2" in p[0].reason
    s = state(60, jobs={"SCRIBE": {"posts": 1, "filled": 1}, "SCHOLAR": {"posts": 2, "filled": 2}})
    assert not staff(s)


@test("staffing: no scholar in a small fort or a library without paper; the scribe as before")
def _():
    assert not staff(state(15))
    assert not staff(state(60, have={"paper": 0}))
    s = state(15, jobs={})
    p = staff(s)
    assert p and p[0].action["posts"] == ["SCRIBE"], p
    s = state(15, books=0, have={"paper": 0}, jobs={})
    assert not staff(s)                         # (0.85) no scribe before paper or books


@test("staffing: an unhappy scholar's post given back first")
def _():
    s = state(60, jobs={"SCRIBE": {"posts": 1, "filled": 1}, "SCHOLAR": {"posts": 1, "filled": 1}},
              unhappy=[{"post": "SCHOLAR", "unit_id": 77}])
    p = staff(s)
    assert p and p[0].action == {"type": "vacate_post", "location_id": 6, "unit_id": 77}, p


@test("plan(): the real fort with a library asks for its scholar")
def _():
    s = copy.deepcopy(BASE)
    s["dwarves"]["total"] = max(40, int(s["dwarves"].get("total") or 0))
    s["dwarves"]["needs_medical_care"] = 0
    s["locations"] = {"count": {"LIBRARY": 1}, "total": 1, "list": [lib()]}
    props = [p for p in plan(s, Memory())[0] if p.rule == "staff"]
    assert props and props[0].action.get("posts") == ["SCHOLAR"], props


@test("digest: the BOOKS line and the books number")
def _():
    s = {"locations": {"list": [lib(jobs={"SCRIBE": {"posts": 1, "filled": 1}, "SCHOLAR": {"posts": 2, "filled": 1}})]},
         "paper": {"reactions": {}, "writing": {"items": 12, "works": 11, "copies": 1, "own": 0, "scholars": 1}}}
    line = digest.library_line(s)
    assert line.startswith("BOOKS library books:6 paper:4/10 scribes:1/1 scholars:1/2 closed_to_visitors"), line
    assert "fort written:12 works:11 copies:1 own:0" in line, line
    assert digest.numbers(digest.normalize(s))["books"] == 12
    assert digest.library_line({}) == ""
    assert "BOOKS" in digest.digest(s)


@test("bridge: scholars' posts made and filled (POST_KINDS, STAFF_SKILLS); books and blank counted; writing()")
def _():
    posts = (LUA / "ai-society-posts.lua").read_text(encoding="utf-8")
    assert "LIBRARY = {'SCRIBE', 'SCHOLAR'}" in posts
    assert "SCHOLAR = {'WRITING'" in posts
    assert "k ~= 'SCHOLAR' or (o.histfig_id == -1 and o.unit_id == -1)" in posts
    civic = (LUA / "ai-bridge-report-civic.lua").read_text(encoding="utf-8")
    assert "e.books, e.blank = library_books(c)" in civic and "e.copied_artifacts = #b.copied_artifacts" in civic
    assert "table.insert(e.unhappy, {post = 'SCHOLAR'" in civic
    paper = (LUA / "ai-paper.lua").read_text(encoding="utf-8")
    assert "pcall(function() out.writing = writing() end)" in paper and "function writing()" in paper
    for f in ("ai-bridge-report-civic.lua", "ai-paper.lua", "ai-society-posts.lua"):
        assert (LUA / f).stat().st_size < 60_000, f


if __name__ == "__main__":
    finish()
