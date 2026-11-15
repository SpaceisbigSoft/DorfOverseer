"""(layout B, B13) The floors in words (brain/planner_floor_notes.py): the
planner's notes for a level that fell back to the classic placement and for
a floor full for a district, the digest's FLOORS line, the `floors` report
section's default in digest.py, and the wiring in planner.py. The section
itself is another group's (lua/ai-builder-floorstore.lua): the states here
are written by hand from its contract.

    python tests/test_b13_floor_notes.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, code_has  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
import planner  # noqa: E402
import digest as D  # noqa: E402
import planner_floor_notes as FN  # noqa: E402
from planner_core import abs_tick  # noqa: E402

DAY = 1200
CFG = dict(PLANNER_CONFIG)
DATE = {"year": 259, "tick": 201600, "day": 1, "month": "Felsite", "season": "summer"}
NOW = 259 * 403200 + 201600
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
EMPTY = {"v": 1, "mode": "hallway", "count": 0, "rooms": 0, "hall_tiles": 0, "fallbacks": 0, "list": []}


def row(i=3, elevation=12, **kw):
    r = {"id": i, "elevation": elevation, "z": 140 + elevation, "stair": {"x": 96, "y": 101}, "hub": "dug",
         "no_hall": False, "width": 3, "rooms": 7, "hall": 69, "tags": ["homes", "industry"],
         "kinds": {"bedrooms": 4, "workshops": 2, "pile": 1}, "full": [],
         "free": {"north": 0, "east": 36, "south": 59, "west": 13, "tick": NOW - DAY},
         "others": [70, 72, 81], "old_boxes": 2,
         "arms": [{"dir": "east", "len": 23, "runs": 1, "tag": "homes", "slots": 7, "closed": None}]}
    r.update(kw)
    return r


def no_hall(i, elevation):
    return row(i, elevation, no_hall=True, hub="found", rooms=0, hall=0, tags=[], kinds={}, arms=[])


def last(ago_days=0.0, ok=False, kind="dining", why="floor 3: no room", **kw):
    v = {"tick": int(NOW - ago_days * DAY), "ok": ok, "kind": kind, "elevation": 12, "why": why}
    v.update(kw)
    return v


def floors(rows=(), last_=None, **kw):
    rows = list(rows)
    f = {"v": 1, "mode": "hallway", "count": len(rows), "rooms": sum(r.get("rooms", 0) for r in rows if isinstance(r, dict)),
         "hall_tiles": sum(r.get("hall", 0) for r in rows if isinstance(r, dict)), "fallbacks": 0, "list": rows}
    if last_ is not None:
        f["last"] = last_
    f.update(kw)
    return f


def state(section="absent"):
    s = {"date": dict(DATE)}
    if section != "absent":
        s["floors"] = section
    return s


class Untouchable:
    """A memory that fails on any read or write: the pass never looks at it."""
    def __getattribute__(self, name):
        raise AssertionError(f"memory.{name} was read")

    def __setattr__(self, name, value):
        raise AssertionError(f"memory.{name} was written")


def notes_of(section="absent", cfg=None, memory=None):
    notes = ["said before"]
    out = FN._floor_notes(state(section), Untouchable() if memory is None else memory, CFG if cfg is None else cfg, notes)
    assert out is None and notes[0] == "said before"
    return notes[1:]


FALLBACK = "the dining level went to the classic placement, not a floor (floor 3: no room)"
FULL = "floor 3 (elevation 12) has no more room for the homes: the next homes level goes to another floor"


# ---- 1. the notes ---------------------------------------------------------

@test("the test's own clock is the planner's (abs_tick, 1200 ticks a day)")
def _():
    assert abs_tick(state()) == NOW and FN.TICKS_PER_DAY == DAY


@test("_floor_notes is silent without the section, with {}, with an error, with the empty answer")
def _():
    for sec in ("absent", {}, {"error": "lua: attempt to index a nil value"}, dict(EMPTY), dict(EMPTY, newer=True),
                None, [], "floors", 3, {"list": [], "last": None}, {"list": "x", "last": "y"}):
        assert notes_of(sec) == [], sec


@test("floors_view: the section when it is a dict without an error, else None")
def _():
    f = floors([row()])
    assert FN.floors_view({"floors": f}) is f and FN.floors_view({"floors": {}}) == {}
    for sec in ({"error": "x"}, None, [], "x", 1):
        assert FN.floors_view({"floors": sec}) is None
    assert FN.floors_view({}) is None and FN.floors_view(None) is None


@test("a fresh fallback is one note, in the brief's words")
def _():
    assert notes_of(floors([row()], last(0.5), fallbacks=1)) == [FALLBACK]
    # a save whose only floor news is the fallback (no floor took a level yet)
    assert notes_of(dict(EMPTY, fallbacks=1, last=last(0))) == [FALLBACK]


@test("a fallback is said for floor_note_days days, then no more; a level that went onto a floor is no note")
def _():
    f = lambda d, **kw: floors([row()], last(d, **kw), fallbacks=1)   # noqa: E731
    assert notes_of(f(3)) == [FALLBACK]                     # exactly the days: still said
    assert notes_of(f(3.01)) == []
    assert notes_of(f(40)) == []
    assert notes_of(f(5), cfg=dict(CFG, floor_note_days=7)) == [FALLBACK]
    assert notes_of(f(0.5), cfg=dict(CFG, floor_note_days=0)) == []
    assert notes_of(f(0), cfg=dict(CFG, floor_note_days=0)) == [FALLBACK]
    assert notes_of(f(1), cfg={}) == [FALLBACK]             # no key (B10's block not merged yet): 3 days
    assert notes_of(f(3.5), cfg={}) == []
    assert notes_of(f(0.5, ok=True)) == []


@test("an odd `last` is silence, never a failed rule: no tick, a tick from another calendar, no date, junk")
def _():
    for lv in ({"ok": False, "kind": "dining"}, last(0, tick="soon"), last(0, tick=True), last(0, tick=0),
               last(-400), last(0, ok=None), last(0, ok=0), "x", 7):
        assert notes_of(floors([row()], lv)) == [], lv
    notes = []
    FN._floor_notes({"floors": floors([row()], last(0))}, None, CFG, notes)        # no date in the state
    assert notes == []
    FN._floor_notes(state(floors([row()], last(0))), None, None, notes)            # no config at all: the default
    assert notes == [FALLBACK]
    for cfg in ({"floor_note_days": "x"}, {"floor_note_days": None}, {"floor_note_days": float("nan")}):
        assert notes_of(floors([row()], last(1)), cfg=cfg) in ([FALLBACK], []), cfg


@test("the fallback note's words: the kind as written, no kind, no reason, a long or odd reason kept to one safe line")
def _():
    one = lambda **kw: notes_of(floors([row()], last(0, **kw)))   # noqa: E731
    assert one(kind="deep_hall") == ["the deep hall level went to the classic placement, not a floor (floor 3: no room)"]
    assert one(kind="Dining {x}") == ["a level went to the classic placement, not a floor (floor 3: no room)"]
    assert one(kind=None, why=None) == ["a level went to the classic placement, not a floor"]
    assert one(why="  ") == ["the dining level went to the classic placement, not a floor"]
    n = one(why="floor 3: no room; " + "floor 4: refused: aquifer at x101 y96 z11; " * 8 + "{\"type\":\n\"x\"}")[0]
    assert len(n) < 200 and "\n" not in n and "{" not in n and n.startswith(FALLBACK[:-1]), n


@test("a floor full for a district is one note, the lowest floor id; a no_hall level is no note")
def _():
    assert notes_of(floors([row(full=["homes"])])) == [FULL]
    rows = [row(7, 9, full=["industry"]), row(3, 12, full=["homes"]), row(5, 11, full=["halls"])]
    assert notes_of(floors(rows)) == [FULL]
    assert notes_of(floors([no_hall(1, 14), no_hall(2, 13), row(4, 10)])) == []
    # a no_hall level's marks are not a full floor
    assert notes_of(floors([dict(no_hall(1, 14), full=["homes"]), row(4, 10, full=["storage"])])) == [
        "floor 4 (elevation 10) has no more room for the storage: the next storage level goes to another floor"]
    assert notes_of(floors([row(full=["homes", "industry", "homes"])])) == [
        "floor 3 (elevation 12) has no more room for the homes and the industry: "
        "the next homes or industry level goes to another floor"]
    assert notes_of(floors([row(full=[]), row(4, 11, full=None), row(5, 10, full=["{x}", 3])])) == []
    assert notes_of(floors([dict(row(full=["homes"]), elevation=None)])) == [
        "floor 3 has no more room for the homes: the next homes level goes to another floor"]
    assert notes_of(floors([row("3", full=["homes"]), "junk", None])) == []


@test("never more than two notes: a fallback and many full floors")
def _():
    rows = [row(i, 20 - i, full=["homes", "industry"]) for i in range(1, 9)] + [no_hall(20, 2), no_hall(21, 3)]
    got = notes_of(floors(rows, last(1), fallbacks=6))
    assert len(got) == 2 and got[0] == FALLBACK and got[1].startswith("floor 1 (elevation 19) has no more room"), got
    assert FN.NOTES_MAX == 2


@test("memory is not read or written, the state and the config are left as they were")
def _():
    s = state(floors([row(full=["homes"])], last(0), fallbacks=1))
    before, cfg, notes = copy.deepcopy(s), dict(CFG), []
    m = Memory()
    held = copy.deepcopy(vars(m))
    FN._floor_notes(s, m, cfg, notes)
    assert len(notes) == 2 and s == before and cfg == CFG and vars(m) == held
    notes2 = []
    FN._floor_notes(s, Untouchable(), cfg, notes2)          # any read of memory would raise
    assert notes2 == notes
    FN._floor_notes(s, m, cfg, notes2)                      # nothing remembered: the same again next cycle
    assert notes2 == notes * 2


# ---- 2. the digest line ---------------------------------------------------

@test("floors_line: nothing without floors")
def _():
    for sec in ("absent", {}, {"error": "x"}, dict(EMPTY), None, [], "x", {"list": [], "fallbacks": 0, "last": last(0)},
                {"list": "x", "fallbacks": "many"}):
        assert FN.floors_line(state(sec)) == "", sec
    assert FN.floors_line({}) == "" and FN.floors_line(None) == ""


@test("floors_line: some floors")
def _():
    rows = [row(1, 10, rooms=20, hall=150), row(2, 11, rooms=14, hall=100), row(3, 12, rooms=7, hall=60)]
    assert FN.floors_line(state(floors(rows))) == "FLOORS 3 floors, 41 rooms on 310 tiles of hall"
    assert FN.floors_line(state(floors([row(rooms=1, hall=1)]))) == "FLOORS 1 floor, 1 room on 1 tile of hall"
    # a last try that went onto a floor is not news
    assert FN.floors_line(state(floors(rows, last(0, ok=True)))) == "FLOORS 3 floors, 41 rooms on 310 tiles of hall"


@test("floors_line: no_hall rows, a fallback, all of it (the brief's line)")
def _():
    rows = [row(1, 10, rooms=20, hall=150), row(2, 11, rooms=14, hall=100), row(3, 12, rooms=7, hall=60)]
    nh = [no_hall(4, 13), no_hall(5, 14)]
    assert FN.floors_line(state(floors(rows + nh))) == (
        "FLOORS 3 floors, 41 rooms on 310 tiles of hall | 2 levels with no room for a hall")
    assert FN.floors_line(state(floors(rows + nh[:1]))).endswith("| 1 level with no room for a hall")
    assert FN.floors_line(state(floors(rows, fallbacks=2))) == (
        "FLOORS 3 floors, 41 rooms on 310 tiles of hall | classic placements 2")
    assert FN.floors_line(state(floors(rows + nh, last(30), fallbacks=2))) == (
        "FLOORS 3 floors, 41 rooms on 310 tiles of hall | 2 levels with no room for a hall | classic placements 2"
        " | last: dining not on a floor (floor 3: no room)")
    # only fallbacks so far: still a line
    assert FN.floors_line(state(dict(EMPTY, fallbacks=1, last=last(0, kind=None, why=None)))) == (
        "FLOORS 0 floors, 0 rooms on 0 tiles of hall | classic placements 1 | last: a level not on a floor")
    line = FN.floors_line(state(floors(rows, last(0, why="a|b {c}\n" + "x" * 400), fallbacks=1)))
    assert "\n" not in line and "{" not in line and line.count("|") == 2 and len(line) < 220, line


@test("the digest of the fixture fort is unchanged (no FLOORS line); with a floors section it has one, by traffic's")
def _():
    base = D.digest(D.normalize(copy.deepcopy(FIXTURE)))
    assert "FLOORS" not in base
    for sec in ({}, dict(EMPTY), {"error": "lua: boom"}):
        s = copy.deepcopy(FIXTURE)
        s["floors"] = sec
        got = D.digest(D.normalize(s))
        if "error" in sec:
            assert "FLOORS" not in got and "MISSING_SECTIONS" in got and "floors" in got.split("MISSING_SECTIONS")[1]
        else:
            assert got == base, sec
    s = copy.deepcopy(FIXTURE)
    s["floors"] = floors([row()], last(0), fallbacks=1)
    got = D.digest(D.normalize(s)).splitlines()
    mine = [x for x in got if x.startswith("FLOORS ")]
    assert mine == ["FLOORS 1 floor, 7 rooms on 69 tiles of hall | classic placements 1"
                    " | last: dining not on a floor (floor 3: no room)"], mine
    assert [x for x in got if not x.startswith("FLOORS ")] == base.splitlines()
    assert D.floors_line(s) == mine[0] and D.floors_line({"floors": 3}) == "" and D.floors_line(None) == ""
    src = (ROOT / "brain" / "digest.py").read_text(encoding="utf-8")
    assert code_has(src, "traffic_line(s), floors_line(s),")


# ---- 3. the section's default ---------------------------------------------

@test("digest.SECTION_DEFAULTS['floors'] is {}; normalize adds it; a missing floors section is not an error")
def _():
    assert D.SECTION_DEFAULTS["floors"] == {}
    assert "floors" not in D.REQUIRED and "floors" not in D.UNREAD_IS_ERROR and "floors" not in D.LISTED_ONLY
    s = D.normalize(copy.deepcopy(FIXTURE))
    assert s["floors"] == {} and "floors" not in s["_errors"]
    s = D.normalize({"date": dict(DATE), "floors": []})         # DFHack's empty table
    assert s["floors"] == {} and "floors" not in s["_errors"]
    f = floors([row()])
    s = D.normalize({"date": dict(DATE), "floors": f})
    assert s["floors"] is f and "floors" not in s["_errors"]


@test("a failed floors section is handled as the other optional sections are: listed, an empty default, silence")
def _():
    s = D.normalize({"date": dict(DATE), "floors": {"error": "lua: boom"}, "garden_court": {"error": "lua: bang"}})
    assert s["floors"] == {} and s["_errors"]["floors"] == "lua: boom"
    assert s["garden_court"] == {} and s["_errors"]["garden_court"] == "lua: bang"
    assert D.normalize(s)["_errors"]["floors"] == "lua: boom"   # kept on a second pass
    notes = []
    FN._floor_notes(s, None, CFG, notes)
    assert notes == [] and FN.floors_line(s) == ""
    s = D.normalize({"date": dict(DATE), "floors": "hallway"})
    assert s["floors"] == {} and "unexpected type" in s["_errors"]["floors"]


# ---- 4. plan() ------------------------------------------------------------

def run_plan(section="absent"):
    s = copy.deepcopy(FIXTURE)
    if section != "absent":
        s["floors"] = section
    m = Memory()
    props, notes = plan(s, m)
    return [(p.rule, json.dumps(p.action, sort_keys=True, default=str)) for p in props], notes, s


@test("plan() on the fixture fort: the same proposals and notes with no floors, whatever shape 'no floors' takes")
def _():
    props, notes, _s = run_plan()
    assert props and not any("floor" in n and "classic placement" in n for n in notes)
    assert not any("_floor_notes" in n for n in notes)
    for sec in ({}, dict(EMPTY), {"error": "lua: boom"}, floors([row(), no_hall(4, 13)]), floors([row()], last(0, ok=True))):
        p2, n2, _s = run_plan(sec)
        assert p2 == props and n2 == notes, sec


@test("plan() with a floors section that reports a fallback: the same proposals plus the note")
def _():
    props, notes, _s = run_plan()
    now = abs_tick(D.normalize(copy.deepcopy(FIXTURE)))
    sec = floors([row()], last(0, tick=now - DAY), fallbacks=1)
    p2, n2, _s = run_plan(sec)
    assert p2 == props
    assert [n for n in n2 if n not in notes] == [FALLBACK] and [n for n in n2 if n != FALLBACK] == notes, n2
    # a full floor too: two notes, in that order; an old fallback: only the full floor
    sec = floors([row(full=["homes"])], last(0, tick=now - DAY), fallbacks=1)
    p3, n3, _s = run_plan(sec)
    assert p3 == props and [n for n in n3 if n not in notes] == [FALLBACK, FULL]
    sec = floors([row(full=["homes"])], last(0, tick=now - 10 * DAY), fallbacks=1)
    p4, n4, _s = run_plan(sec)
    assert p4 == props and [n for n in n4 if n not in notes] == [FULL]


@test("planner.py: the import beside planner_garden's, the pass right after guided_pass; no rule or action name added")
def _():
    src = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8").splitlines()
    i = next(k for k, ln in enumerate(src) if ln.startswith("from planner_garden import"))
    assert src[i + 1].startswith("from planner_floor_notes import floors_view, floors_line, _floor_notes")
    j = next(k for k, ln in enumerate(src) if ln.strip().startswith("_guard(guided_pass,"))
    assert src[j + 1].strip().startswith("_guard(_floor_notes, s, memory, cfg, notes)")
    assert planner._floor_notes is FN._floor_notes and planner.floors_line is FN.floors_line
    mine = (ROOT / "brain" / "planner_floor_notes.py").read_text(encoding="utf-8")
    assert "Proposal" not in mine and "import memstore" not in mine and "setattr" not in mine


if __name__ == "__main__":
    finish()
