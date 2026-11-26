"""(option B, group B14) The scorecard's floor lines: what the hallway-first
floors show of Spacing, Room size and Depth, read from the `floors` report
section of a season state and from the `floor` / `not_on_floor` keys of the
journal's start_project answers. Neither is made in this copy: the states
and journal entries here are written by hand, to the contract.

    python tests/test_b14_floor_scorecard.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402

import scorecard  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
DATE = {"year": 252, "tick": 0, "season": "spring"}
NEW = scorecard.FLOOR_KEYS

# the contract's own example of the section, word for word
SECTION = {"v": 1, "mode": "hallway", "count": 2, "rooms": 19, "hall_tiles": 150, "fallbacks": 1,
           "last": {"tick": 104630400, "ok": False, "kind": "dining", "elevation": 12, "why": "floor 3: no room"},
           "list": [{"id": 3, "elevation": 12, "z": 152, "stair": {"x": 96, "y": 101}, "hub": "dug", "no_hall": False,
                     "width": 3, "rooms": 7, "hall": 69, "tags": ["homes", "industry"],
                     "kinds": {"bedrooms": 4, "workshops": 2, "pile": 1}, "full": ["homes"],
                     "free": {"north": 0, "east": 36, "south": 59, "west": 13, "tick": 104630400},
                     "others": [70, 72, 81], "old_boxes": 2,
                     "arms": [{"dir": "east", "len": 23, "runs": 1, "tag": "homes", "slots": 7, "closed": None}]}]}
EMPTY = {"v": 1, "mode": "hallway", "count": 0, "rooms": 0, "hall_tiles": 0, "fallbacks": 0, "list": []}


def state(floors=None):
    s = copy.deepcopy(BASE)
    s["date"] = dict(DATE)
    if floors is not None:
        s["floors"] = copy.deepcopy(floors)
    return s


def answer_floor(**kw):
    """A start_project answer's `floor`, as the contract's example."""
    f = {"id": 3, "elevation": 12, "stair": {"x": 96, "y": 101}, "arm": "east", "side": "north", "u": 13,
         "hall_new": 39, "new_floor": False, "piles": ["stone"], "units": 2, "gap": 1, "lead": 2, "run_max": 30}
    f.update(kw)
    return f


def level(tick, kind="bedrooms", tiles=60, year=251, **result):
    """One journalled start_project (a decision that worked)."""
    r = {"ok": True, "project_id": tick, "kind": kind, "z": 150, "tiles": tiles, "corridor": 0, "new_corridor": 0}
    r.update(result)
    return {"kind": "decision", "date": {"year": year, "tick": tick}, "action": {"type": "start_project", "kind": kind},
            "result": r}


def counts(entries):
    return scorecard.journal_counts(entries, DATE)


def measures(entries, floors=None):
    """scorecard.measures, read as the lines read it: a key that is not there is None."""
    return dict(dict.fromkeys(NEW), **scorecard.measures(state(floors), counts(entries)))


def raw(entries, floors=None):
    return scorecard.measures(state(floors), counts(entries))


def fort_dir(root: Path, label: str, preset: str, s: dict, journal=()) -> Path:
    d = root / label
    fd = d / "logs" / "forts" / "region1-1"
    (fd / "states").mkdir(parents=True)
    s = copy.deepcopy(s)
    s["settings"] = dict(s.get("settings") or {}, preset=preset)
    (fd / "states" / "252-spring.json").write_text(json.dumps(s), encoding="utf-8")
    (fd / "journal.jsonl").write_text("".join(json.dumps(e) + "\n" for e in journal), encoding="utf-8")
    return d


def report(forts):
    with tempfile.TemporaryDirectory() as tmp:
        fs = [scorecard.Fort(lb, fort_dir(Path(tmp), lb, p, s, jn)) for lb, p, s, jn in forts]
        return scorecard.score(fs, None, True)


def new_lines():
    return list(scorecard.FLOOR_LINES)


def row(rows, key):
    return next(r for r in rows if r["key"].lstrip("-") == key)


# ------------------------------------------------------------------ 1. no floors: no data, and nothing old moves

@test("no `floors` section and no floor answer: every new measure is None, never 0")
def _():
    j = [level(1), level(2, "workshops", new_corridor=14)]
    fm = scorecard.floor_measures(state(), counts(j))
    assert set(fm) == set(NEW) and all(v is None for v in fm.values()), fm
    # measures() carries no floor key then (the dict it gave before, key for key); read with .get: None
    m = raw(j)
    assert not set(NEW) & set(m), set(NEW) & set(m)
    assert all(m.get(k) is None for k in NEW)
    # an empty journal, a section that failed, one from a newer version, junk
    for floors in ({"error": "boom"}, dict(SECTION, newer=True), [], "x", 7, {}):
        s = state()
        s["floors"] = floors
        fm = scorecard.floor_measures(s, counts([]))
        assert set(fm) == set(NEW) and all(v is None for v in fm.values()), (floors, fm)
        assert not set(NEW) & set(scorecard.measures(s, counts([])))


@test("no floors: every old measure is what it was, with or without the new keys in the state and the journal")
def _():
    plain = [level(1, tiles=80, new_corridor=6, summary={"rooms": 4}), level(2, "workshops", tiles=95, new_corridor=14)]
    floored = copy.deepcopy(plain)
    floored[0]["result"]["floor"] = answer_floor(units=4)
    floored[1]["result"]["not_on_floor"] = "floor 3: no room"
    a, b = raw(plain), raw(floored, SECTION)
    assert not set(NEW) & set(a) and set(NEW) & set(b)
    old = set(a) - set(NEW)
    assert old == set(b) - set(NEW)
    # (item23) Room size's tiles a bedroom takes a floor's new hall out; (R30c item24) and
    # counts the room's own 3x3 only: min(80, 36) / 4, and on the floor min(80 - 39, 36) / 4
    assert a["bedroom_room_tiles"] == 9.0 and b["bedroom_room_tiles"] == 9.0, (a, b)
    old.discard("bedroom_room_tiles")
    # and Spacing's tiles a bedroom beyond its 3x3: (80 - 36) / 4; on the floor (80 - 39 - 36) / 4
    assert a["bedroom_spare_tiles"] == 11.0 and b["bedroom_spare_tiles"] == 1.2, (a, b)
    old.discard("bedroom_spare_tiles")
    assert {k: a[k] for k in old} == {k: b[k] for k in old}, {k: (a[k], b[k]) for k in old if a[k] != b[k]}
    # the old corridor line still reads the old key (old and new runs stay comparable)
    assert a["corridor_mean"] == 10.0 and a["levels"] == 2 and a["bedroom_tiles"] == 20.0, a
    assert ("Spacing", "new corridor tiles a level (fewest wins)", "-corridor_mean",
            {scorecard.W, scorecard.D}, set()) in scorecard.LINES
    # the journal's level rows keep every key they had and gain the two
    rows = counts(floored)["levels"]
    assert rows[0]["floor"]["units"] == 4 and rows[0]["not_on_floor"] is False, rows[0]
    assert rows[1]["floor"] is None and rows[1]["not_on_floor"] is True, rows[1]
    for k in ("kind", "z", "tiles", "corridor", "rooms", "customs", "style", "when", "x", "y", "ground"):
        assert k in rows[0], k
    assert counts(plain)["levels"][0]["floor"] is None and counts(plain)["levels"][0]["not_on_floor"] is False


@test("no fort with floors: the report is the old one, line for line (no floor line, no floor note)")
def _():
    j = [level(1), level(2, "workshops", new_corridor=14)]
    md, rows = report([("A", "War-hold", state(), j), ("D", "Deep mine", state(), j),
                       ("G", "Garden fort", state(), j)])
    assert [(r["slider"], r["line"], r["key"]) for r in rows] == [ln[:3] for ln in scorecard.LINES]
    assert "on a floor" not in md and "main hall" not in md and "Room size" not in md, md
    assert not {ln[2].lstrip("-") for ln in scorecard.LINES} & set(NEW)


@test("a fort without floors beside one that has them: its new lines read \"-\" and \"no data\", never 0")
def _():
    j = [level(1), level(2, "workshops", new_corridor=14)]
    jd = [level(1, floor=answer_floor(units=4))]
    md, rows = report([("A", "War-hold", state(), j), ("D", "Deep mine", state(SECTION), jd),
                       ("G", "Garden fort", state(), j)])
    lines = new_lines()
    assert len(lines) == 5, lines
    assert len(rows) == len(scorecard.LINES) + 5
    for _sl, what, key, _hi, _lo in lines:
        r = next(x for x in rows if x["line"] == what)
        assert r["result"] == "no data", r
        if key.lstrip("-") not in NEW:      # (item23) Room size's tiles a bedroom: no level here has rooms
            assert all(v is None for v in r["values"].values()), r
            continue
        assert r["values"]["A"] is None and r["values"]["G"] is None and r["values"]["D"] is not None, r
        assert re.search(r"\| " + re.escape(what) + r" \| - \| [0-9.]+ \| - \|", md), what
    # each new line stands after the last old line of its slider; Room size after Spacing's
    order = [(r["slider"], r["key"].lstrip("-")) for r in rows]
    assert order[order.index(("Verticality", "depth")) + 1:][:2] == [("Verticality", "floors"),
                                                                     ("Verticality", "floor_arm_max")], order
    assert order[order.index(("Spacing", "bedroom_spare_tiles")) + 1:][:3] == [
        ("Spacing", "floor_gap_mean"), ("Spacing", "floor_lead_mean"), ("Room size", "bedroom_room_tiles")], order
    # the old lines keep their order around them
    assert [x for x in order if x[1] not in NEW and x[0] != "Room size"] == [(ln[0], ln[2].lstrip("-")) for ln in scorecard.LINES]


# ------------------------------------------------------------------ 2. the numbers, by hand

@test("the contract's `floors` section and two floor answers: each measure by hand")
def _():
    j = [level(1, "bedrooms", tiles=80, floor=answer_floor(gap=1, lead=2, hall_new=30, units=4)),
         level(2, "workshops", tiles=95, floor=answer_floor(gap=3, lead=4, hall_new=39, units=2))]
    m = measures(j, SECTION)
    assert m["floor_share"] == 100.0, m["floor_share"]              # 2 of 2
    assert m["floor_fallbacks"] == 0
    assert m["floor_gap_mean"] == 2.0, m["floor_gap_mean"]          # (1 + 3) / 2
    assert m["floor_lead_mean"] == 3.0, m["floor_lead_mean"]        # (2 + 4) / 2
    assert m["floor_room_tiles"] == 17.7, m["floor_room_tiles"]     # ((80 - 30) + (95 - 39)) / (4 + 2) = 106 / 6
    assert m["floors"] == 2, m["floors"]                            # the section's count
    assert m["floor_hall_per_room"] == 7.9, m["floor_hall_per_room"]            # 150 / 19
    assert m["floor_rooms_per_floor"] == 9.5, m["floor_rooms_per_floor"]        # 19 / 2
    assert m["floor_arm_max"] == 23, m["floor_arm_max"]
    # the longest of several arms, on several floors
    sec = copy.deepcopy(SECTION)
    sec["list"][0]["arms"].append({"dir": "south", "len": 31, "runs": 2, "tag": "industry", "slots": 4})
    sec["list"].append({"id": 4, "elevation": 11, "no_hall": False, "rooms": 12, "hall": 81,
                        "arms": [{"dir": "west", "len": 27, "runs": 1, "slots": 12}]})
    assert measures(j, sec)["floor_arm_max"] == 31
    # a level whose answer has no tile count or no units is left out of the room mean, not counted as 0
    j.append(level(3, "dining", tiles=0, floor=answer_floor(gap=2, lead=0, hall_new=9, units=1)))
    j.append(level(4, "storage", tiles=70, floor=answer_floor(gap=2, lead=0, hall_new=9, units=0)))
    m = measures(j, SECTION)
    assert m["floor_room_tiles"] == 17.7 and m["floor_gap_mean"] == 2.0 and m["floor_lead_mean"] == 1.5, m


@test("a hallway fort with no floor yet: 0 floors is a count; the shares of nothing are no data")
def _():
    m = measures([], EMPTY)
    assert m["floors"] == 0, m["floors"]
    for k in NEW:
        if k != "floors":
            assert m[k] is None, (k, m[k])


# ------------------------------------------------------------------ 3. the share

@test("floor_share: from the first floor answer on; a fallback counts against, a join and the old levels not at all")
def _():
    j = [level(1, "bedrooms"),                                           # before floors: not counted
         level(2, "dining"),
         level(3, "bedrooms", floor=answer_floor(units=4)),              # the first floor answer
         level(4, "workshops", not_on_floor="floor 3: no room; floor 4: refused: aquifer at x101 y96 z11"),
         level(5, "workshops", joined=57, floor=answer_floor()),         # a join: no new level
         level(6, "workshops", joined=57, not_on_floor="floor 3: no room"),
         level(7, "farms"),                                              # classic on purpose: no key, not on a floor
         level(8, "storage", floor=answer_floor(units=1))]
    jc = counts(j)
    assert len(jc["levels"]) == 6, len(jc["levels"])
    m = scorecard.measures(state(SECTION), jc)
    assert m["floor_share"] == 50.0, m["floor_share"]        # 2 on a floor of the 4 since (3, 4, 7, 8)
    assert m["floor_fallbacks"] == 1, m["floor_fallbacks"]
    assert m["levels"] == 6                                  # the old count: every level, joins aside
    # a fallback is a floor answer too: hallway mode was on
    m = measures([level(1), level(2, not_on_floor="no floor in the band"), level(3, floor=answer_floor())])
    assert m["floor_share"] == 50.0 and m["floor_fallbacks"] == 1, m
    # only fallbacks: 0% is measured (the mode was on, nothing went onto a floor); the means are no data
    m = measures([level(1), level(2, not_on_floor="no floor in the band")])
    assert m["floor_share"] == 0.0 and m["floor_fallbacks"] == 1, m
    assert m["floor_gap_mean"] is None and m["floor_lead_mean"] is None and m["floor_room_tiles"] is None, m
    # a level started after the season scored is not read; a failed start is no level
    late = level(5, floor=answer_floor(), year=253)
    failed = level(6, floor=answer_floor())
    failed["result"]["ok"] = False
    m = measures([level(1), late, failed])
    assert m["floor_share"] is None and m["floor_gap_mean"] is None, m


@test("the journal keeps the newest reason a level was not put on a floor")
def _():
    j = [level(1, not_on_floor="floor 3: no room"), level(2, floor=answer_floor()),
         level(3, not_on_floor="floor 4: refused: aquifer at x101 y96 z11")]
    assert counts(j)["floor_why"] == "floor 4: refused: aquifer at x101 y96 z11"
    assert counts([level(1)])["floor_why"] is None


# ------------------------------------------------------------------ 4. classic, and levels no hall can start on

@test("mode classic with no floor: no data, not 0")
def _():
    classic = dict(EMPTY, mode="classic")
    m = measures([level(1), level(2)], classic)
    assert all(m[k] is None for k in NEW), {k: m[k] for k in NEW if m[k] is not None}
    _md, rows = report([("A", "War-hold", state(classic), [level(1)]), ("D", "Deep mine", state(classic), [level(1)])])
    assert not any(r["key"].lstrip("-") in NEW for r in rows)      # no fort has a floor: the old report
    # beside a fort that has floors: "-" and no data
    _md, rows = report([("A", "War-hold", state(classic), [level(1)]), ("D", "Deep mine", state(SECTION), [level(1)])])
    for k in ("floors", "floor_arm_max"):
        r = row(rows, k)
        assert r["result"] == "no data" and r["values"]["A"] is None and r["values"]["D"] is not None, r
    # a fort switched back to classic keeps the floors it has
    assert measures([], dict(SECTION, mode="classic"))["floors"] == 2


@test("no_hall rows count in neither `floors` nor the means")
def _():
    dead = {"id": 5, "elevation": 14, "z": 154, "no_hall": True, "width": 3, "rooms": 0, "hall": 0, "arms": []}
    # the count covers the row: 3 rows, one of them no floor
    sec = copy.deepcopy(SECTION)
    sec["list"].append({"id": 4, "elevation": 11, "no_hall": False, "rooms": 12, "hall": 81,
                        "arms": [{"dir": "west", "len": 27, "runs": 1, "slots": 12}]})
    sec["list"].append(dict(dead))
    sec["count"] = 3
    m = measures([], sec)
    assert m["floors"] == 2, m["floors"]
    assert m["floor_rooms_per_floor"] == 9.5 and m["floor_hall_per_room"] == 7.9 and m["floor_arm_max"] == 27, m
    # the count leaves the row out: the same answer
    sec["count"] = 2
    assert measures([], sec)["floors"] == 2
    # a no_hall row that carries numbers all the same (an arm, rooms, hall): none of them is read
    sec["count"] = 3
    sec["list"][2].update(rooms=4, hall=30, arms=[{"dir": "north", "len": 99, "runs": 1, "slots": 4}])
    m = measures([], sec)
    assert m["floors"] == 2 and m["floor_arm_max"] == 27, m
    assert m["floor_rooms_per_floor"] == 7.5, m["floor_rooms_per_floor"]        # (19 - 4) / 2
    assert m["floor_hall_per_room"] == 8.0, m["floor_hall_per_room"]            # (150 - 30) / 15
    # only levels no hall can start on: 0 floors, and no mean of nothing
    only = dict(EMPTY, count=1, list=[dict(dead)])
    m = measures([], only)
    assert m["floors"] == 0, m["floors"]
    assert m["floor_arm_max"] is None and m["floor_rooms_per_floor"] is None and m["floor_hall_per_room"] is None, m


# ------------------------------------------------------------------ 5. who should win

# line key -> (the slider's id in BUILTIN_PRESETS, +1 when the measure rises with the slider, -1 when it falls)
EFFECT = {"floor_gap_mean": ("spacing", 1), "floor_lead_mean": ("spacing", 1),
          "floors": ("verticality", 1), "floor_arm_max": ("verticality", -1),
          "bedroom_room_tiles": ("size", 1)}     # (item23) Room size: tiles a bedroom
SLIDER_OF = {"Spacing": "spacing", "Verticality": "verticality", "Room size": "size"}


def presets() -> dict:
    from lupa.lua53 import LuaRuntime
    src = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    block = re.search(r"^BUILTIN_PRESETS = \{.*?^\}", src, re.S | re.M).group(0)
    lua = LuaRuntime()
    lua.execute(block)
    t = lua.globals().BUILTIN_PRESETS
    return {name: dict(t[name].items()) for name in t.keys()}


@test("each new line's winners are presets in BUILTIN_PRESETS, and most or least wins as the slider's sign says")
def _():
    need_lua()
    ps = presets()
    assert set(scorecard.SHORT) == set(ps), set(scorecard.SHORT) ^ set(ps)
    lines = new_lines()
    assert {ln[2].lstrip("-") for ln in lines} == set(EFFECT), [ln[2] for ln in lines]
    for slider, what, key, high, low in lines:
        k = key.lstrip("-")
        sid, effect = EFFECT[k]
        assert SLIDER_OF[slider] == sid, (slider, sid)
        turn = -1 if key.startswith("-") else 1          # "-key": least wins
        assert high | low <= set(ps), (what, high | low)
        for p in high:      # a named winner has the slider on the side that makes the judged value most
            assert ps[p].get(sid, 0) * effect * turn > 0, (what, p, ps[p].get(sid, 0))
        for p in low:
            assert ps[p].get(sid, 0) * effect * turn < 0, (what, p, ps[p].get(sid, 0))
        # no preset with the slider on the other side is left unnamed on a line that names a low side
        if low:
            assert low == {p for p in ps if ps[p].get(sid, 0) * effect * turn < 0}, what
        # a line with nobody to win is one whose slider no built-in preset moves
        if not high and not low:
            assert not any(ps[p].get(sid, 0) for p in ps), (what, sid)
    by = {ln[2].lstrip("-"): ln for ln in lines}
    # Spacing: the two presets below 0; the lead only where the tight step (-50) is passed
    assert by["floor_gap_mean"][3] == {p for p in ps if ps[p].get("spacing", 0) < 0} == {"War-hold", "Deep mine"}
    assert by["floor_lead_mean"][3] == {p for p in ps if ps[p].get("spacing", 0) <= -50} == {"War-hold"}
    # Depth: the Deep mine alone
    want = {p for p in ps if ps[p].get("verticality", 0) > 0}
    assert by["floors"][3] == by["floor_arm_max"][3] == want == {"Deep mine"}
    both = scorecard.floor_lines(scorecard.LINES)
    assert len({ln[2] for ln in both}) == len(both) == len(scorecard.LINES) + len(lines), "a measure key twice"


# ------------------------------------------------------------------ the report

def fort_state(count, arm, rooms, hall, fallbacks=0, why=None):
    sec = {"v": 1, "mode": "hallway", "count": count, "rooms": rooms, "hall_tiles": hall, "fallbacks": fallbacks,
           "list": [{"id": i + 1, "elevation": 10 - i, "no_hall": False, "width": 3, "rooms": rooms // count,
                     "hall": hall // count, "arms": [{"dir": "east", "len": arm, "runs": 1, "slots": rooms // count}]}
                    for i in range(count)]}
    if why:
        sec["last"] = {"tick": 1, "ok": False, "kind": "dining", "elevation": 12, "why": why}
    return state(sec)


@test("report: the Deep mine wins the floor lines, the War-hold the lead; the gap is flat; Room size is shown, not judged without its presets")
def _():
    def j(gap, lead, units_tiles):
        e = level(1, "bedrooms", tiles=units_tiles * 4 + 30, summary={"rooms": 4},
                  floor=answer_floor(gap=gap, lead=lead, hall_new=30, units=4))
        # (R30c item24) Room size reads the room's own room_size x room_size: the side asked for
        e["action"]["room_size"] = round(units_tiles ** 0.5)
        return [e]
    md, rows = report([("A", "War-hold", fort_state(2, 30, 16, 180), j(1, 0, 9)),
                       ("D", "Deep mine", fort_state(5, 14, 20, 210), j(1, 2, 9)),
                       ("G", "Garden fort", fort_state(1, 44, 18, 132), j(1, 2, 16))])
    r = row(rows, "floors")
    assert r["values"] == {"A": 2, "D": 5, "G": 1} and r["result"] == "pass", r
    r = row(rows, "floor_arm_max")
    assert r["values"] == {"A": 30, "D": 14, "G": 44} and r["result"] == "pass", r
    r = row(rows, "floor_lead_mean")
    assert r["values"] == {"A": 0.0, "D": 2.0, "G": 2.0} and r["result"] == "pass", r
    r = row(rows, "floor_gap_mean")
    assert r["values"] == {"A": 1.0, "D": 1.0, "G": 1.0} and r["result"] == "flat", r
    r = next(x for x in rows if x["slider"] == "Room size")
    assert r["key"] == "bedroom_room_tiles" and r["values"] == {"A": 9.0, "D": 9.0, "G": 16.0}, r
    assert r["result"] == "no data", r          # none of the three moves Room size
    assert "| Verticality | floors with a main hall | 2 | 5 | 1 | Deep | pass |" in md, md
    assert "| Spacing | hall before the first room on a floor (least wins) | 0 | 2 | 2 | War | pass |" in md
    assert "| Room size | tiles a bedroom | 9 | 9 | 16 | Mer / low: Mon | no data |" in md, md
    assert "not on a floor" not in md
    # the Deep mine with the longest arm and the fewest floors: both lines fail
    _md, rows = report([("A", "War-hold", fort_state(2, 30, 16, 180), j(1, 0, 9)),
                        ("D", "Deep mine", fort_state(1, 60, 20, 210), j(1, 2, 9))])
    assert row(rows, "floors")["result"] == "fail" and row(rows, "floor_arm_max")["result"] == "fail"


@test("report: the levels not on a floor, fort by fort, with the last reason")
def _():
    why = "floor 3: no room; floor 4: refused: aquifer at x101 y96 z11"
    ja = [level(1, floor=answer_floor()), level(2, "dining", not_on_floor="floor 3: no room"),
          level(3, "workshops", not_on_floor=why), level(4, floor=answer_floor())]
    jd = [level(1, floor=answer_floor())]
    md, _rows = report([("A", "War-hold", fort_state(2, 30, 16, 180, 2), ja),
                        ("D", "Deep mine", fort_state(5, 14, 20, 210), jd),
                        # the journal has none (rotated away): the builder's own count and its last refused try
                        ("G", "Garden fort", fort_state(1, 44, 18, 132, 3, "floor 1: no room"), jd)])
    assert "Levels not on a floor (hallway mode on, placed the classic way):" in md, md
    assert f"- Fort A: 2 level(s) placed the classic way (50% went onto a floor); last: {why}." in md, md
    assert "- Fort G: 0 level(s) placed the classic way (100% went onto a floor); the builder counts 3; " \
           "last: floor 1: no room." in md, md
    assert "- Fort D" not in md
    # a reason is cut at the contract's 300 characters
    long = [level(1, not_on_floor="x" * 500)]
    md, _rows = report([("A", "War-hold", state(), long), ("D", "Deep mine", state(), jd)])
    assert "last: " + "x" * 300 + "." in md


if __name__ == "__main__":
    finish()


@test("(item23) Room size: tiles a bedroom; the Merchant city's (+50) most wins, the Monastery's (-50) least")
def _():
    def j(tiles):
        return [level(1, "bedrooms", tiles=tiles * 4 + 20, summary={"rooms": 4},
                      floor=answer_floor(hall_new=20, units=4))]
    _md, rows = report([("B", "Monastery", fort_state(2, 30, 16, 180), j(4)),
                        ("C", "Merchant city", fort_state(2, 30, 16, 180), j(16)),
                        ("G", "Garden fort", fort_state(2, 30, 16, 180), j(9))])
    r = next(x for x in rows if x["slider"] == "Room size")
    assert r["values"] == {"B": 4.0, "C": 16.0, "G": 9.0} and r["result"] == "pass", r
    _md, rows = report([("B", "Monastery", fort_state(2, 30, 16, 180), j(16)),
                        ("C", "Merchant city", fort_state(2, 30, 16, 180), j(4)),
                        ("G", "Garden fort", fort_state(2, 30, 16, 180), j(9))])
    assert next(x for x in rows if x["slider"] == "Room size")["result"] == "fail"
