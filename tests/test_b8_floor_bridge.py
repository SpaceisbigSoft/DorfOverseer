"""(layout B, group B8) The bridge's side of the hallway-first floors: the
`floor` key of start_project (parse_floor in lua/ai-bridge-actions.lua: the
brain's hint, `false` for "place this one the classic way") and the report's
`floors` section (the builder's floors_report(), wrapped in safe()). On the
stub DFHack of tests/test_hygiene_bridge.py in a real Lua 5.3 engine (pip
install lupa); the builder is a stand-in (its floor parts are another
group's).

    python tests/test_b8_floor_bridge.py
"""

from __future__ import annotations

import copy
import re
import sys

from harness import ROOT, finish, test

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package with Lua 5.3 (pip install lupa)")
    sys.exit(0)

LUA_DIR = ROOT / "lua"
HUB = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
# the stub DFHack of tests/test_hygiene_bridge.py, read from it (not copied)
_hyg = (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8")
HARNESS = re.search(r'HARNESS = r"""(.*?)"""', _hyg, re.S).group(1)

LUA = LuaRuntime(unpack_returned_tuples=True)
H = LUA.execute(HARNESS, HUB, str(LUA_DIR))
LUA_TYPE = LUA.eval("type")
# parse_floor's two answers kept apart (a nil hint and a false hint are different things)
CALL2 = LUA.eval("""function(f, v)
    local hint, err = f(v)
    return {hint_type = type(hint), hint = hint, err = err}
end""")
RAISES = LUA.eval("function() error('floors record unreadable') end")


def t(d):
    if isinstance(d, dict):
        return LUA.table_from({k: t(v) for k, v in d.items()})
    if isinstance(d, (list, tuple)):
        return LUA.table_from([t(v) for v in d])
    return d


def plain(v):
    """A Lua value as Python: a table with keys 1..n is a list, any other a dict."""
    if LUA_TYPE(v) != "table":
        return v
    keys = list(v.keys())
    if keys and sorted(keys, key=str) == sorted(range(1, len(keys) + 1), key=str):
        return [plain(v[i]) for i in range(1, len(keys) + 1)]
    return {k: plain(v[k]) for k in keys}


# --- the contract's ranges, listed once (the spec's "The bridge" and ai-floorplan's G) ---

INTS = {            # key: (lo, hi)
    "gap": (1, 4), "kind_gap": (0, 6), "lead": (0, 8), "ahead": (0, 3), "run_max": (12, 80),
    "run_min": (4, 30), "arms_max": (1, 4), "stagger": (0, 6), "tries": (4, 60),
    "full_retry_days": (1, 336), "pile_w": (3, 11), "piles_new": (0, 3),
}
ODD_INTS = {        # key: (the values taken, the values refused)
    "bay": ((0, 3, 4, 5, 6), (-1, 1, 2, 7)),
    "node": ((3, 5), (2, 4, 6)),
}
WORDS = {
    "zone": ("near", "mid", "far", "any"),
    "sides": ("both", "one", "alternate"),
    "turns": ("left", "right", "alternate", "both"),
}
LISTS = {           # key: (the words, the most of them)
    "dirs": (("north", "south", "east", "west"), 4),
    "grow": (("arm", "turn"), 2),
}
BOOLS = ("balance", "axial", "neck")
NAMES = ("tag", "group")            # 1-24 of [a-z_]
ELEV = (-400, 400)                  # elevs: a list of 1-6 of these
ELEVS_MOST = 6
SPINE = (0, 999)                    # spine: {x, y}
KNOWN = set(INTS) | set(ODD_INTS) | set(WORDS) | set(LISTS) | set(BOOLS) | set(NAMES) | {"elevs", "spine"}

# the full valid hint, as the contract quotes it
FULL = {"elevs": [12, 11, 13], "tag": "industry", "group": "crafts", "zone": "mid",
        "spine": {"x": 96, "y": 101}, "dirs": ["east", "south"],
        "gap": 1, "kind_gap": 1, "lead": 2, "ahead": 1, "run_max": 30, "run_min": 10, "arms_max": 2,
        "sides": "both", "stagger": 0, "bay": 4, "node": 3, "grow": ["arm", "turn"], "turns": "alternate",
        "balance": False, "axial": False, "neck": False,
        "pile_w": 5, "piles_new": 1, "full_retry_days": 28}

# the stand-in ai-layouts and ai-builder: start_project records its params
STANDINS = """
local H = ...
H.started = {}
H.scripts['ai-layouts'] = {KINDS = {'bedrooms', 'dining', 'workshops'}, STOCKPILES = {stone = true},
                           WORKSHOPS = {Masons = true}, LAYOUT_CUSTOMS = {}}
H.scripts['ai-builder'] = {
  start_project = function(p, date, dry)
    table.insert(H.started, {p = p, dry = dry})
    return {ok = true, project_id = 57, kind = p.kind, dry_run = dry or nil}
  end,
  floors_report = function() return {v = 1, mode = 'hallway', count = 0, rooms = 0, hall_tiles = 0,
                                     fallbacks = 0, list = {}} end,
}
"""


def fresh():
    H.scripts = LUA.table()
    H.halted = False
    M = H.module()
    LUA.execute(STANDINS, H)
    return M


M0 = fresh()


def parse(v):
    """(kind, hint, err): kind is 'nil', 'false' or 'table'."""
    r = CALL2(M0.parse_floor, t(v))
    return r.hint_type, plain(r.hint), r.err


def ok(v):
    kind, hint, err = parse(v)
    assert kind == "table" and err is None, (v, kind, err)
    return hint


def refused(v, key):
    kind, hint, err = parse(v)
    assert kind == "nil" and isinstance(err, str), (v, kind, hint, err)
    assert err.startswith(f"floor.{key} must be "), (v, err)
    return err


def started():
    return [plain(x) for x in plain(H.started)] if len(H.started) else []


BEDROOMS = {"type": "start_project", "kind": "bedrooms", "rooms": 4}


# --- 1. parse_floor -----------------------------------------------------------

@test("parse_floor: nil stays nil, false stays false, neither with an error")
def _():
    assert parse(None) == ("nil", None, None)
    assert parse(False) == ("boolean", False, None)


@test("parse_floor: the contract's full hint comes back equal, as a new table")
def _():
    src = t(FULL)
    r = CALL2(M0.parse_floor, src)
    assert r.err is None and plain(r.hint) == FULL, (r.err, plain(r.hint))
    assert not LUA.eval("rawequal")(r.hint, src), "the brain's own table was handed on"
    assert set(FULL) == KNOWN - {"tries"}, "the test's key list and the contract's hint drifted apart"


@test("parse_floor: an empty hint is an empty hint; unknown keys are dropped, the known ones beside them kept")
def _():
    assert ok({}) == {}
    got = ok({"gap": 2, "colour": "red", "elev_lo": 3, "plan": {"x": 1}, "Gap": 9, "floor": False, "run": [1, 2]})
    assert got == {"gap": 2}, got


@test("parse_floor: what is neither an object nor false is refused (true, a number, a word)")
def _():
    for bad in (True, 3, "hallway", 0):
        kind, hint, err = parse(bad)
        assert kind == "nil" and err == "floor must be an object or false", (bad, kind, err)


@test("parse_floor: each key's wrong type is refused with the key named")
def _():
    wrong = {k: ("2", True, [2], {"n": 2}) for k in list(INTS) + list(ODD_INTS)}
    wrong.update({k: (1, True, ["near"], {"a": "near"}) for k in WORDS})
    wrong.update({k: ("east", 1, True) for k in LISTS})
    wrong.update({k: (1, 0, "true", "no", [True]) for k in BOOLS})
    wrong.update({k: (1, True, ["homes"], {"a": "homes"}) for k in NAMES})
    wrong["elevs"] = (12, "12", True, ["12"], [True], [[12]])
    wrong["spine"] = (5, "96,101", True, [96, 101], {"x": 96}, {"y": 101}, {"x": "96", "y": 101}, {"x": 96, "y": True})
    assert set(wrong) == KNOWN
    for key, values in wrong.items():
        for v in values:
            refused({key: v}, key)
            refused({**FULL, key: v}, key)      # one bad key refuses the whole hint


@test("parse_floor: each numeric range's two edges are taken, one past each refused, a fraction refused")
def _():
    for key, (lo, hi) in INTS.items():
        assert ok({key: lo}) == {key: lo} and ok({key: hi}) == {key: hi}, key
        for v in (lo - 1, hi + 1, lo + 0.5, float("inf"), float("nan")):
            err = refused({key: v}, key)
            assert f"{lo}-{hi}" in err, err
    # a whole number sent as a float (JSON's 2.0) is the number
    got = M0.parse_floor(t({"gap": 2.0}))
    assert got.gap == 2 and LUA.eval("math.type")(got.gap) == "integer"


@test("parse_floor: bay is 0 or 3-6 (1 and 2 refused); node is 3 or 5 (4 refused)")
def _():
    for key, (good, bad) in ODD_INTS.items():
        for v in good:
            assert ok({key: v}) == {key: v}, (key, v)
        for v in bad + (3.5,):
            refused({key: v}, key)
    for v in (1, 2):
        assert refused({"bay": v}, "bay") == "floor.bay must be 0 or 3-6"
    assert refused({"node": 4}, "node") == "floor.node must be 3 or 5"


@test("parse_floor: elevs is a list of 1-6 whole numbers -400..400 (empty, 7, a fraction, a hole refused)")
def _():
    lo, hi = ELEV
    assert ok({"elevs": [lo]}) == {"elevs": [lo]} and ok({"elevs": [hi]}) == {"elevs": [hi]}
    six = [12, 11, 13, 10, 14, 9]
    assert len(six) == ELEVS_MOST and ok({"elevs": six}) == {"elevs": six}
    assert ok({"elevs": [5, 5]}) == {"elevs": [5, 5]}          # the order and a repeat are the brain's
    for bad in ([], six + [8], [12, 11.5], [lo - 1], [hi + 1], [12, "11"], {"a": 12}):
        refused({"elevs": bad}, "elevs")
    # a list with a hole or a named key beside its numbers
    for src in ("{elevs = {12, nil, 13}}", "{elevs = {12, 11, n = 2}}", "{elevs = {[0] = 12, 11}}"):
        r = CALL2(M0.parse_floor, LUA.eval(src))
        assert r.hint is None and r.err.startswith("floor.elevs must be "), (src, r.err)


@test("parse_floor: tag and group are 1-24 of a-z and _")
def _():
    for key in NAMES:
        for good in ("a", "homes", "deep_mine", "_", "x" * 24):
            assert ok({key: good}) == {key: good}, (key, good)
        for bad in ("", "x" * 25, "Homes", "homes 2", "crafts-hall", "smiths1", "a\nb", "café"):
            refused({key: bad}, key)


@test("parse_floor: zone, sides and turns take their own words only")
def _():
    for key, words in WORDS.items():
        for w in words:
            assert ok({key: w}) == {key: w}
        for bad in ("", "none", words[0].upper(), words[0] + " "):
            err = refused({key: bad}, key)
            assert all(w in err for w in words), err
    assert "one" not in WORDS["turns"] and "left" not in WORDS["sides"]
    refused({"turns": "one"}, "turns")
    refused({"sides": "left"}, "sides")


@test("parse_floor: spine is x and y, 0-999; anything else in it is dropped")
def _():
    lo, hi = SPINE
    assert ok({"spine": {"x": lo, "y": hi}}) == {"spine": {"x": lo, "y": hi}}
    assert ok({"spine": {"x": 96, "y": 101, "z": 152}}) == {"spine": {"x": 96, "y": 101}}
    for bad in ({"x": lo - 1, "y": 5}, {"x": 5, "y": hi + 1}, {"x": 5.5, "y": 5}, {}):
        refused({"spine": bad}, "spine")


@test("parse_floor: dirs is 1-4 distinct compass words, grow 1-2 distinct of arm and turn; the order is kept")
def _():
    for key, (words, most) in LISTS.items():
        assert len(words) == most
        for w in words:
            assert ok({key: [w]}) == {key: [w]}
        full = list(reversed(words))
        assert ok({key: full}) == {key: full}, key
        for bad in ([], [words[0], words[0]], full + [words[0]], [words[0], "up"], ["nowhere"], [1],
                    [words[0].upper()], {"a": words[0]}):
            refused({key: bad}, key)
    assert ok({"dirs": ["west", "north", "east"]}) == {"dirs": ["west", "north", "east"]}
    refused({"grow": ["arm", "arm"]}, "grow")
    refused({"grow": ["arm", "stair"]}, "grow")
    refused({"dirs": ["east", "south", "east"]}, "dirs")
    refused({"grow": ["north"]}, "grow")
    refused({"dirs": ["arm"]}, "dirs")


@test("parse_floor: balance, axial and neck are true or false, each kept as sent")
def _():
    for key in BOOLS:
        assert ok({key: True}) == {key: True} and ok({key: False}) == {key: False}


# --- 4. the ranges cannot drift ------------------------------------------------

def edge_hints():
    """Hints made by hand from the lists above: every key at its range's low
    edge, at its high edge, and each word and each odd value once."""
    lo = {k: r[0] for k, r in INTS.items()}
    hi = {k: r[1] for k, r in INTS.items()}
    lo.update(bay=ODD_INTS["bay"][0][0], node=ODD_INTS["node"][0][0], elevs=[ELEV[0]],
              spine={"x": SPINE[0], "y": SPINE[0]}, tag="a", group="_",
              dirs=[LISTS["dirs"][0][0]], grow=[LISTS["grow"][0][0]], balance=False, axial=False, neck=False)
    hi.update(bay=ODD_INTS["bay"][0][-1], node=ODD_INTS["node"][0][-1], elevs=[ELEV[1]] * ELEVS_MOST,
              spine={"x": SPINE[1], "y": SPINE[1]}, tag="z" * 24, group="a_z" * 8,
              dirs=list(LISTS["dirs"][0]), grow=list(LISTS["grow"][0]), balance=True, axial=True, neck=True)
    out = []
    n = max(len(w) for w in WORDS.values())
    for i in range(n):
        for base in (lo, hi):
            h = copy.deepcopy(base)
            for k, words in WORDS.items():
                h[k] = words[i % len(words)]
            out.append(h)
    for k, (good, _bad) in ODD_INTS.items():
        for v in good:
            out.append({**copy.deepcopy(lo), "zone": "any", "sides": "one", "turns": "both", k: v})
    return out


@test("ranges: a hint made by hand at each range's edge survives parse_floor unchanged, every value")
def _():
    hints = edge_hints()
    assert len(hints) >= 8
    for h in hints:
        assert set(h) == KNOWN, set(h) ^ KNOWN
        got = ok(h)
        assert got == h, {k: (h[k], got.get(k)) for k in h if got.get(k) != h[k]}


@test("ranges: the bridge's tables are the test's (the contract's), key for key")
def _():
    src = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    body = src[src.index("local FLOOR_INTS"):src.index("function parse_floor")]
    ints = {k: (int(a), int(b)) for k, a, b in re.findall(r"(\w+) = \{(-?\d+), (-?\d+)\}", body)}
    assert ints == INTS, set(ints.items()) ^ set(INTS.items())
    for key, words in WORDS.items():
        m = re.search(key + r" = \{((?:'\w+',? ?)+)\}", body)
        assert m and tuple(re.findall(r"'(\w+)'", m.group(1))) == words, key
    for key, (words, most) in LISTS.items():
        m = re.search(key + r" = \{\{((?:'\w+',? ?)+)\}, (\d)\}", body)
        assert m and set(re.findall(r"'(\w+)'", m.group(1))) == set(words) and int(m.group(2)) == most, key


@test("ranges: parse_floor uses the file's own int_in and stands right after parse_plan")
def _():
    src = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    a, b, c = src.index("function parse_plan("), src.index("function parse_floor("), src.index("function act_start_project(")
    assert a < b < c
    between = src[a:b]
    assert between.count("\nfunction ") == 0, "another global function stands between parse_plan and parse_floor"
    assert "int_in(" in src[b:c] and "math.tointeger" not in src[b:c]
    assert "\nfunction int_in(" in HUB and "function int_in" not in src


# --- 2. act_start_project -----------------------------------------------------

@test("start_project: the cleaned floor hint reaches the builder's start_project as p.floor")
def _():
    M = fresh()
    r = M.act_start_project(t({**BEDROOMS, "floor": {**FULL, "colour": "red"}}))
    assert r.ok and r.project_id == 57, plain(r)
    calls = started()
    assert len(calls) == 1 and calls[0]["p"]["floor"] == FULL, calls
    assert calls[0]["p"]["kind"] == "bedrooms" and calls[0]["p"]["rooms"] == 4, calls


@test("start_project: floor = false reaches the builder as false; no floor key reaches it as none")
def _():
    M = fresh()
    assert M.act_start_project(t({**BEDROOMS, "floor": False})).ok
    assert M.act_start_project(t(BEDROOMS)).ok
    assert M.act_start_project(t({**BEDROOMS, "floor": {}})).ok
    a, b, c = (x.p for x in (H.started[1], H.started[2], H.started[3]))
    assert a.floor is False, "false did not stay false"
    assert LUA.eval("function(p) return rawget(p, 'floor') == nil end")(b), "a floor key appeared from nowhere"
    assert LUA_TYPE(c.floor) == "table" and plain(c.floor) == {}, "an empty hint is still a hint"
    # without the key the builder's params are today's, nothing more
    assert plain(b) == {"kind": "bedrooms", "rooms": 4, "room_size": 3}, plain(b)


@test("start_project: a bad floor is refused (rejected, the key named) before the builder is called")
def _():
    M = fresh()
    for bad, key in (({"gap": 9}, "gap"), ({"bay": 2}, "bay"), ({"elevs": []}, "elevs"), ({"zone": "deep"}, "zone"),
                     ({**FULL, "node": 4}, "node"), ({**FULL, "dirs": ["east", "east"]}, "dirs")):
        r = M.act_start_project(t({**BEDROOMS, "floor": bad}))
        assert r.ok is False and r.rejected is True and r.error.startswith(f"floor.{key} must be "), plain(r)
    for bad in (True, 7, "hallway"):
        r = M.act_start_project(t({**BEDROOMS, "floor": bad}))
        assert r.ok is False and r.rejected is True and r.error == "floor must be an object or false", plain(r)
    assert started() == [], "the builder was called with a refused floor"


@test("start_project: the kind, the style and the plan are checked first, as before; plan and floor go side by side")
def _():
    M = fresh()
    bad_floor = {"gap": 9}
    r = M.act_start_project(t({"type": "start_project", "kind": "bedrooms", "rooms": 99, "floor": bad_floor}))
    assert r.rejected and r.error == "bedrooms needs rooms 1-32 and room_size 2-4", plain(r)
    r = M.act_start_project(t({"type": "start_project", "kind": "castle", "floor": bad_floor}))
    assert r.rejected and r.error.startswith("unknown level kind: castle"), plain(r)
    r = M.act_start_project(t({**BEDROOMS, "style": {"hall": "nosuch"}, "floor": bad_floor}))
    assert r.rejected and r.error.startswith("style."), plain(r)
    r = M.act_start_project(t({**BEDROOMS, "plan": {"elev_lo": 5, "elev_hi": 1}, "floor": bad_floor}))
    assert r.rejected and r.error.startswith("plan needs elev_lo"), plain(r)
    r = M.act_start_project(t({**BEDROOMS, "floor": FULL, "max_elev": 999}))
    assert r.rejected and r.error == "max_elev must be -400 to 400", plain(r)
    assert started() == []
    plan = {"elev_lo": 10, "elev_hi": 14, "dirs": ["north"], "spine": {"x": 1, "y": 2}}
    r = M.act_start_project(t({"type": "start_project", "kind": "workshops", "shops": ["Masons"],
                               "plan": plan, "floor": FULL, "urgent": True, "max_elev": 20}))
    assert r.ok, plain(r)
    p = started()[0]["p"]
    assert p["floor"] == FULL and p["urgent"] is True and p["max_elev"] == 20, p
    assert p["plan"] == {**plan, "elev_target": 12}, p["plan"]        # the classic hint: what it was
    assert p["shops"] == ["Masons"], p


@test("start_project: through the act command, a dry run included (no new action, the same DRY_OK line)")
def _():
    M = fresh()
    assert M.ACTIONS.start_project is not None and M.DRY_OK.start_project is not None
    r = H.act(M, t({**BEDROOMS, "floor": {"elevs": [12], "tag": "homes"}, "dry_run": True}))
    assert r.ok and r.dry_run is True, plain(r)
    r = H.act(M, t({**BEDROOMS, "floor": False}))
    assert r.ok and r.dry_run is None, plain(r)
    r = H.act(M, t({**BEDROOMS, "floor": {"tag": "Homes"}}))
    assert r.ok is False and r.rejected and r.error.startswith("floor.tag must be "), plain(r)
    calls = started()
    assert [c["dry"] for c in calls] == [True, False], calls
    assert calls[0]["p"]["floor"] == {"elevs": [12], "tag": "homes"} and calls[1]["p"]["floor"] is False, calls
    for name in ("floor", "start_floor", "place_floor", "floors"):
        assert M.ACTIONS[name] is None and M.DRY_OK[name] is None, name


# --- 3. the floors section ----------------------------------------------------

EMPTY = {"v": 1, "mode": "hallway", "count": 0, "rooms": 0, "hall_tiles": 0, "fallbacks": 0, "list": []}
REPORT = {"v": 1, "mode": "hallway", "count": 1, "rooms": 7, "hall_tiles": 69, "fallbacks": 1,
          "last": {"tick": 104630400, "ok": False, "kind": "dining", "elevation": 12, "why": "floor 3: no room"},
          "list": [{"id": 3, "elevation": 12, "z": 152, "stair": {"x": 96, "y": 101}, "hub": "dug", "no_hall": False,
                    "width": 3, "rooms": 7, "hall": 69, "tags": ["homes", "industry"],
                    "kinds": {"bedrooms": 4, "workshops": 2, "pile": 1}, "full": ["homes"],
                    "free": {"north": 0, "east": 36, "south": 59, "west": 13, "tick": 104630400},
                    "others": [70, 72, 81], "old_boxes": 2,
                    "arms": [{"dir": "east", "len": 23, "runs": 1, "tag": "homes", "slots": 7}]}]}


def section(v):
    """The floors section as Python; an empty Lua list reads as {} (as [] here)."""
    out = plain(v)
    if isinstance(out, dict) and out.get("list") == {}:
        out["list"] = []
    return out


@test("floors: the section exists, is not in the pulse and is not cached")
def _():
    M = fresh()
    assert M.SECTIONS.floors is not None
    assert "floors" not in plain(M.PULSE_SECTIONS)
    assert M.SECTION_CACHE_DAYS.floors is None
    assert M.SECTION_MAX_DAYS is None or M.SECTION_MAX_DAYS.floors is None
    assert "floors" in plain(M.sorted_keys(M.SECTIONS)), "the daily report's list misses it"


@test("floors: the section answers the builder's floors_report(), as it is")
def _():
    M = fresh()
    assert section(M.SECTIONS.floors()) == EMPTY
    H.scripts["ai-builder"].floors_report = LUA.eval("function(r) return function(...) "
                                                     "ARGS = select('#', ...); return r end end")(t(REPORT))
    got = M.SECTIONS.floors(t({"tier": "daily"}))
    assert plain(got) == REPORT, plain(got)
    assert LUA.eval("ARGS") == 0, "floors_report takes no argument"


@test("floors: an {error = ...} table when floors_report raises, is missing, or the builder does not load")
def _():
    M = fresh()
    H.scripts["ai-builder"].floors_report = RAISES
    got = plain(M.SECTIONS.floors())
    assert set(got) == {"error"} and "floors record unreadable" in got["error"], got
    H.scripts["ai-builder"].floors_report = None       # a builder without the floor parts (this copy's)
    got = plain(M.SECTIONS.floors())
    assert set(got) == {"error"} and "floors_report" in got["error"], got
    H.scripts["ai-builder"] = None
    got = plain(M.SECTIONS.floors())
    assert set(got) == {"error"} and "no ai-builder here" in got["error"], got


def report_with(M, names, tier=None):
    """A report of the named real sections beside two stand-ins."""
    LUA.eval("""function(M, names)
        local real = M.SECTIONS
        M.get_dwarves = function() return {total = 7}, nil end
        M.SECTIONS = {date = function() return {year = 150} end, projects = function() return {} end}
        for _, n in ipairs(names) do M.SECTIONS[n] = real[n] end
        M.PULSE_SECTIONS = {'date', 'projects'}
        M.SECTION_CACHE = {}
    end""")(M, t(names))
    return M.build_state(False, tier) if tier else M.build_state(False)


@test("report: the full report builds with the floors section, without it, and when it fails")
def _():
    M = fresh()
    s = report_with(M, ["floors"])
    assert section(s.floors) == EMPTY and s.date.year == 150 and s.tier == "daily", plain(s.floors)
    assert s.perf.sections.floors is not None and not (s.perf.cached and s.perf.cached.floors)
    assert M.SECTION_CACHE.floors is None, "the floors section was kept in the cache"
    H.scripts["ai-builder"].floors_report = RAISES
    s = M.build_state(False)
    assert "floors record unreadable" in s.floors.error and s.date.year == 150, plain(s.floors)
    H.scripts["ai-builder"].floors_report = None
    s = M.build_state(False)
    assert "floors_report" in s.floors.error and s.date.year == 150 and s.projects is not None
    M = fresh()
    s = report_with(M, [])
    assert s.floors is None and s.date.year == 150 and s.tier == "daily"


@test("report: the pulse carries no floors section")
def _():
    M = fresh()
    s = report_with(M, ["floors"], "pulse")
    assert s.tier == "pulse" and s.floors is None and s.date.year == 150


@test("report: the section is read afresh each report (a floor made between two reports shows in the second)")
def _():
    M = fresh()
    assert report_with(M, ["floors"]).floors.count == 0
    H.scripts["ai-builder"].floors_report = LUA.eval("function(r) return function() return r end end")(t(REPORT))
    s = M.build_state(False)
    assert s.floors.count == 1 and s.floors.list[1].arms[1].dir == "east", plain(s.floors)


@test("bridge: nothing else moved (the hub's one new line is the section; no new module, no version bump here)")
def _():
    M = fresh()
    assert "ai-builder-floors" not in plain(M.BRIDGE_MODULES) or (LUA_DIR / "ai-builder-floors.lua").exists()
    assert HUB.count("floors_report") == 1 and HUB.count("floors = function()") == 1
    i, j = HUB.index("\nSECTIONS = {"), HUB.index("\nPULSE_SECTIONS = {")
    assert i < HUB.index("floors = function()") < j
    tail = HUB[HUB.index("    way_out = function()"):j]
    lines = tail[:tail.index("\n}\n")].splitlines()
    assert lines[-1] == ("    floors = function() return safe(function() "
                         "return reqscript('ai-builder').floors_report() end) end,"), lines[-1]
    assert all(ln.lstrip().startswith("--") for ln in lines[1:-1]), lines

if __name__ == "__main__":
    finish()
