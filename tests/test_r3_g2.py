"""(r3 g2, 21 Nov) Hallway floors that fill properly.

The 15-16 Nov run (R-AD, R-CE, R-B section 2): each floor got one arm of
13-26 tiles and then said "no room" while its survey showed free runs; big
kinds said "no room" where they were only too big for a run; classic levels
took the hub of the elevations the master plan kept for floors, so the next
floor there was refused "the stair's hub". Here:

  (a) a floor full by its grammar (arms_max reached) opens another arm out of
      the hub (ai-floorplace spill), the hint's spill = false keeps the old way;
  (b) "too big for a run" is its own answer (floor_big {need, run_max}), no
      other floor is tried, the brain asks for a run that holds it next time
      or goes classic at once; a "no room" mark keeps the size it refused, so
      a smaller level is still tried there;
  (c) a classic level keeps clear of a floor's hub and planned halls, and of
      the hub of the elevations its own hint offers.

    python tests/test_r3_g2.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import finish, have_lua, make_test, skip, test as plain_test  # noqa: E402

import masterplan  # noqa: E402
import masterplan_floors as MF  # noqa: E402
from planner import Memory  # noqa: E402
from planner_config import PLANNER_CONFIG  # noqa: E402

# ------------------------------------------------------------------ the fake fort (as test_b16)

LUA = B = W = TB = E = PL = None
if have_lua():
    import test_builder as TB  # noqa: E402  (its fake fort; its tests run only when it is run itself)
    from lupa.lua53 import LuaRuntime  # noqa: E402
    LUA, B, W = TB.LUA, TB.B, TB.W
    _b16 = (ROOT / "tests" / "test_b16_floors_end_to_end.py").read_text(encoding="utf-8")
    SETUP = re.search(r'SETUP = r"""(.*?)"""', _b16, re.S).group(1)
    _srcs = {n: (ROOT / "lua" / f"{n}.lua").read_text(encoding="utf-8")
             for n in ("ai-floorplan", "ai-floorplace", "ai-floorunits")}
    E = LUA.execute(SETUP, B, LUA.globals().LAYOUTS, LUA.table_from(_srcs))
    # the pure placement module alone, in an engine of its own
    _pl = LuaRuntime(unpack_returned_tuples=True)
    PL = _pl.eval("function(src) local env = setmetatable({}, {__index=_G}); "
                  "assert(load(src, 'ai-floorplace', 't', env))(); return env end")(_srcs["ai-floorplace"])

SX, SY, ROCK_Z = 60, 60, 63
KEY = "ai-overseer/floors"


def _reset(mode="hallway"):
    if TB is None:
        skip("needs the lupa package (pip install lupa)")
    W.size = LUA.table_from([120, 120, 100])
    TB._reset(False)
    E.mode, E.link, E.tick = mode, None, 0
    E.links = LUA.table()
    B.walk_group = E.real_walk
    B.MAX_OPEN_PROJECTS = 100
    B.FLOOR_SECONDS = 30
    for k in ("FLOOR_SPILL", "FLOOR_BIG_STOP", "FLOOR_FULL_BY_SIZE", "FLOOR_KEEP_CLEAR"):
        B[k] = True


lua_test = make_test(before=_reset)


def tbl(v):
    if isinstance(v, dict):
        return LUA.table_from({k: tbl(x) for k, x in v.items()})
    if isinstance(v, (list, tuple)):
        return LUA.table_from([tbl(x) for x in v])
    return v


def plain(v, lua=None):
    lua = lua or LUA
    if lua.eval("type")(v) != "table":
        return v
    keys = list(v.keys())
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [plain(v[i], lua) for i in range(1, len(keys) + 1)]
    return {k: plain(v[k], lua) for k in keys}


def start(**kw):
    r = B.start_project(tbl(kw), LUA.table_from({"year": 148, "tick": 100}), False)
    assert "failed:" not in str(r.not_on_floor or ""), f"a floor module raised: {r.not_on_floor}"
    return r


def store():
    return plain(W.persist[KEY]) if W.persist[KEY] is not None else None


def floor_rec(z, sx=SX, sy=SY):
    for f in (store() or {}).get("floors", []):
        if f.get("z") == z and f.get("stair", {}).get("x") == sx and f.get("stair", {}).get("y") == sy:
            return f
    return None


def arms(z):
    f = floor_rec(z)
    names = {(1, 0): "east", (-1, 0): "west", (0, 1): "south", (0, -1): "north"}
    return sorted(names[(r["dx"], r["dy"])] for r in (f or {}).get("runs", []) if not r.get("parent"))


ONE_ARM = dict(elevs=[ROCK_Z], tag="homes", run_max=20, arms_max=1, grow=["arm"], dirs=["east"])

# ------------------------------------------------------------------ (a) a full floor opens another arm


@lua_test("(a) arms_max 1, the first arm full: the next level opens a second arm out of the hub (the far side), "
          "not 'no room'; with the hint's spill = false it is 'no room' as before")
def _():
    for _ in range(2):
        r = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(ONE_ARM))
        assert r.ok and r.floor is not None, plain(r)
    assert arms(ROCK_Z) == ["east"], floor_rec(ROCK_Z)
    r = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(ONE_ARM))
    assert r.ok and r.floor is not None, plain(r)
    f = plain(r.floor)
    assert f["id"] == 1 and f["arm"] != "east", f
    assert len(arms(ROCK_Z)) == 2, floor_rec(ROCK_Z)
    # the switch: spill = false keeps the floor to its one arm
    _reset()
    for _ in range(2):
        start(kind="bedrooms", rooms=4, room_size=3, floor=dict(ONE_ARM, spill=False))
    r = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(ONE_ARM, spill=False))
    assert r.floor is None and str(r.not_on_floor).startswith("floor 1: no room"), plain(r)
    assert arms(ROCK_Z) == ["east"]


@plain_test("(a) ai-floorplace: a spill arm needs only the item's own columns free (an 8-column way out takes a "
            "3x3 room where run_min 10 would refuse it); off without G.spill")
def _():
    if PL is None:
        skip("needs the lupa package (pip install lupa)")
    rt = _pl
    env = rt.eval("""function()
      -- rock round the stair; east free for ever; west only 8 columns free; north and south shut at once
      local e = {seed = 0}
      function e.open(x, y)
        if x >= -1 and x <= 1 and (y == -2 or y == 2) then return 'bad' end
        if x == -10 then return 'bad' end
        return 'rock'
      end
      function e.blocked() return false end
      function e.probe() return true end
      function e.late() return false end
      return e
    end""")()
    G = {"gap": 1, "kind_gap": 1, "lead": 2, "ahead": 1, "run_max": 12, "run_min": 10, "arms_max": 1,
         "dirs": ["east"], "sides": "both", "stagger": 0, "bay": 0, "node": 3, "grow": ["arm"],
         "turns": "alternate", "balance": False, "axial": False, "neck": False, "tries": 24}

    def lt(v):
        if isinstance(v, dict):
            return rt.table_from({k: lt(x) for k, x in v.items()})
        if isinstance(v, list):
            return rt.table_from([lt(x) for x in v])
        return v
    unit = {"w": 3, "d": 3, "role": "room", "open": {"x0": 1, "x1": 1}}
    floor = {"id": 1, "runs": [], "slots": []}
    # fill the east arm (run_max 12: one room a side and a bit)
    commit = rt.eval("""function(floor, P)
      floor.hub = 'dug'
      for _, r in ipairs(P.runs) do
        if r.new then table.insert(floor.runs, {id = r.id, parent = r.parent, ox = r.ox, oy = r.oy, dx = r.dx,
                                                dy = r.dy, len = r.len, tag = r.tag, node = r.node})
        else for _, fr in ipairs(floor.runs) do if fr.id == r.id then fr.len = r.len end end end
      end
      for _, p in ipairs(P.puts) do
        table.insert(floor.slots, {run = p.run, side = p.side, u = p.u, w = p.w, d = p.d, kind = 'bedrooms', tag = 'homes'})
      end
    end""")
    fl = lt(floor)
    req = lt({"kind": "bedrooms", "tag": "homes", "units": [unit]})
    n = 0
    while True:
        P, why = PL.place(fl, req, lt(G), env), None
        if isinstance(P, tuple):
            P, why = P
        if P is None:
            break
        commit(fl, P)
        n += 1
        assert n < 20
    assert why == "no room", why
    survey = plain(PL.survey(fl, lt(G), env), rt)
    assert survey["west"] == 8 and survey["south"] == 0 and survey["north"] == 0, survey
    # without spill (the pure module's default) it stays 'no room'
    res = PL.place(fl, req, lt(G), env)
    assert (res[1] if isinstance(res, tuple) else None) == "no room", res
    res = PL.place(fl, req, lt(dict(G, spill=True)), env)
    P = res[0] if isinstance(res, tuple) else res
    assert P is not None, res
    runs = plain(P.runs, rt)
    new = [r for r in runs if r["new"]]
    assert new and (new[0]["dx"], new[0]["dy"]) == (-1, 0) and new[0]["len"] <= 8, runs


# ------------------------------------------------------------------ (b) too big for a run

GRAND = dict(kind="dining", tables=8, style={"grand": True})


@plain_test("(b) need_run: the shortest run_max that takes the request (G's own when it fits), nil past 80")
def _():
    if PL is None:
        skip("needs the lupa package (pip install lupa)")
    rt = _pl

    def lt(v):
        if isinstance(v, dict):
            return rt.table_from({k: lt(x) for k, x in v.items()})
        if isinstance(v, list):
            return rt.table_from([lt(x) for x in v])
        return v
    G = {"gap": 1, "kind_gap": 1, "lead": 2, "ahead": 1, "run_max": 12, "run_min": 10, "arms_max": 2,
         "dirs": [], "sides": "both", "stagger": 0, "bay": 0, "node": 3, "grow": ["arm", "turn"],
         "turns": "alternate", "balance": False, "axial": False, "neck": False, "tries": 24}
    small = lt({"kind": "bedrooms", "tag": "homes", "units": [{"w": 3, "d": 3}]})
    assert PL.need_run(small, lt(G)) == 12
    wide = lt({"kind": "dining", "tag": "homes", "units": [{"w": 15, "d": 5}]})
    assert PL.fits_empty(wide, lt(G)) is False
    assert PL.need_run(wide, lt(G)) == 2 + 15 + 1          # lead + the unit + ahead
    assert PL.fits_empty(wide, lt(dict(G, run_max=18))) is True
    huge = lt({"kind": "dining", "tag": "homes", "units": [{"w": 90, "d": 5}]})
    assert PL.need_run(huge, lt(G)) is None


@lua_test("(b) a level too big for any run: 'too big for a run (needs a run of N, this one is M)', floor_big in "
          "the answer, no second floor tried, no floor marked full; the classic level keeps off the hub")
def _():
    r = start(floor={"elevs": [ROCK_Z, ROCK_Z - 1], "run_max": 12}, **GRAND)
    assert r.ok and r.floor is None, plain(r)
    why = str(r.not_on_floor)
    assert re.fullmatch(r"z63: too big for a run \(needs a run of \d+, this one is 12\)", why), why
    big = plain(r.floor_big)
    assert big["run_max"] == 12 and big["need"] > 12 and big["kind"] == "dining", big
    assert "z62" not in why                         # the classic way at once
    assert not (store() or {}).get("floors"), store()
    # the brain's next hint asks for that run: the level goes onto a floor
    r = start(floor={"elevs": [ROCK_Z, ROCK_Z - 1], "run_max": big["need"]}, **GRAND)
    assert r.ok and r.floor is not None, plain(r)


@lua_test("(b) a 'no room' mark keeps the size refused: a level as big is kept off the floor, a smaller one is "
          "still tried there (FLOOR_FULL_BY_SIZE off: kept off too)")
def _():
    hint = dict(ONE_ARM, spill=False, full_retry_days=3)
    for _ in range(2):
        start(kind="bedrooms", rooms=4, room_size=3, floor=dict(hint))
    r = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(hint))
    assert str(r.not_on_floor) == "floor 1: no room", plain(r)
    fs = floor_rec(ROCK_Z).get("full_size", {}).get("homes")
    assert fs and fs["n"] == 4 and fs["w"] >= 3, floor_rec(ROCK_Z)
    E.tick = 1200
    r = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(hint))
    assert str(r.not_on_floor) == "floor 1: full for homes", plain(r)
    r = start(kind="bedrooms", rooms=2, room_size=3, floor=dict(hint))
    assert str(r.not_on_floor) == "floor 1: no room", plain(r)          # tried, not skipped
    B.FLOOR_FULL_BY_SIZE = False
    r = start(kind="bedrooms", rooms=1, room_size=3, floor=dict(hint))
    assert str(r.not_on_floor) == "floor 1: full for homes", plain(r)


# ------------------------------------------------------------------ (c) classic levels keep clear


PLAN63 = {"elev_lo": ROCK_Z, "elev_hi": ROCK_Z, "elev_target": ROCK_Z}


@lua_test("(c) a level the floor refused, its plan band on a floor elevation: the classic level does not take "
          "that elevation's hub, so the next level begins the floor there (B's z38/z42: 'the stair's hub')")
def _():
    r = start(plan=PLAN63, floor={"elevs": [ROCK_Z], "run_max": 12}, **GRAND)
    assert r.ok and r.floor is None and int(r.z) != ROCK_Z, plain(r)
    r = start(kind="bedrooms", rooms=4, room_size=3, floor={"elevs": [ROCK_Z]})
    assert r.ok and r.floor is not None and int(r.z) == ROCK_Z, plain(r)
    # the switch off: as before, the classic level is centred on the stair there and the floor is refused
    _reset()
    B.FLOOR_KEEP_CLEAR = False
    r = start(plan=PLAN63, floor={"elevs": [ROCK_Z], "run_max": 12}, **GRAND)
    assert r.ok and int(r.z) == ROCK_Z, plain(r)
    r = start(kind="bedrooms", rooms=4, room_size=3, floor={"elevs": [ROCK_Z]})
    assert r.floor is None and "the stair's hub" in str(r.not_on_floor), plain(r)


@lua_test("(c) floor_keep_boxes: a live floor's hub, its run out to run_max with its room rows, and each free way "
          "out of the hub; check_site names the floor when a level would stand there")
def _():
    r = start(kind="bedrooms", rooms=4, room_size=3, floor=dict(elevs=[ROCK_Z], dirs=["east"]))
    assert r.ok and r.floor is not None and plain(r.floor)["arm"] == "east", plain(r)
    boxes = plain(B.floor_keep_boxes(tbl({"kind": "bedrooms", "rooms": 4, "floor": {"elevs": [ROCK_Z]}}),
                                     B.find_stairs(3)))
    mine = [b for b in boxes if b["z"] == ROCK_Z]
    assert all("floor 1" in b["why"] for b in mine), mine
    hub = {"x1": SX - 1, "y1": SY - 1, "x2": SX + 1, "y2": SY + 1}
    assert any(all(b[k] == v for k, v in hub.items()) for b in mine), mine
    # the east run kept out to run_max (30) past its node, with 4 rows each side beyond the hall
    east = [b for b in mine if b["x1"] == SX + 2]
    assert any(b["x2"] >= SX + 2 + 30 and b["y1"] <= SY - 5 and b["y2"] >= SY + 5 for b in east), mine
    # the three free ways: FLOOR_KEEP_ARM columns, hall-wide
    for d, (x, y) in {"west": (SX - 2 - 11, SY), "south": (SX, SY + 2 + 11), "north": (SX, SY - 2 - 11)}.items():
        assert any(b["x1"] <= x <= b["x2"] and b["y1"] <= y <= b["y2"] for b in mine), (d, mine)
    # check_site's answer for a level on the kept ground
    L = LUA.eval("function() return {tiles = {[0] = {[0] = true}}, bounds = {x1 = 0, y1 = 0, x2 = 0, y2 = 0}} end")()
    ok, why = B.check_site(L, LUA.table(), SX - 6, SY, ROCK_Z, tbl(mine), None)[:2]
    assert not ok and "kept for the main hall of floor 1" in str(why), (ok, why)
    B.FLOOR_KEEP_CLEAR = False
    assert len(plain(B.floor_keep_boxes(tbl({"kind": "bedrooms"}), B.find_stairs(3)))) == 0


# ------------------------------------------------------------------ the brain


SITE = {"stairs": [{"x": 100, "y": 100, "z_top": 160, "z_bottom": 130, "elev_top": 60, "elev_bottom": 30,
                    "count": 8}],
        "citizen_elevation": 50, "soil": [58, 59], "elevation_offset": -100}
STATE = {"date": {"year": 150, "tick": 0, "day": 1, "month": "Granite"}, "dwarves": {"total": 40}}
TRAITS = {"verticality": 0, "spacing": 0, "grandeur": 0, "fortification": 0, "craftsmanship": 0}


def drawn() -> Memory:
    m = Memory()
    m.culture = {"seed": "Test#1", "eras": [{"year": 150, "title": "Plain era"}]}
    m.atlas = {"survey": {"elevation_offset": -100, "tick": 1,
                          "layers": [{"name": "Cavern1", "z_top": 120, "z_bottom": 115, "discovered": True}]},
               "entrances": {}}
    prof = {"layout": "grid", "palette": "dark", "temple": "shrine", "entry_doors": True}
    assert masterplan.draw(STATE, m, SITE, dict(TRAITS), prof) is not None
    MF.ensure(m, dict(TRAITS), prof)
    return m


ACT = {"type": "start_project", "kind": "dining", "tables": 8, "style": {"grand": True}}
CFG = dict(PLANNER_CONFIG)


@plain_test("(b) the brain: an answer with floor_big {need 40} -> the next hint for that kind and size asks for "
            "run_max 40; need none -> False (classic at once); another size untouched; a floor placement clears it")
def _():
    m = drawn()
    h0 = MF.hint(m, dict(ACT), {}, dict(TRAITS), CFG)
    assert isinstance(h0, dict) and h0.get("run_max", 0) < 40, h0
    line = masterplan.note_result(m, dict(ACT), {"ok": True, "floor_big": {"need": 40, "run_max": 30}}, STATE)
    assert line and "40" in line, line
    h = MF.hint(m, dict(ACT), {}, dict(TRAITS), CFG)
    assert isinstance(h, dict) and h["run_max"] == 40, h
    other = dict(ACT, tables=4)
    assert MF.hint(m, other, {}, dict(TRAITS), CFG).get("run_max") == h0.get("run_max")
    # the switch off: as before
    assert MF.hint(m, dict(ACT), {}, dict(TRAITS), dict(CFG, r3g2_floor_big=False)).get("run_max") == h0.get("run_max")
    # no run can take it: classic at once
    MF.note_result(m, dict(ACT), {"ok": True, "floor_big": {"need": None, "run_max": 30}})
    assert MF.hint(m, dict(ACT), {}, dict(TRAITS), CFG) is False
    # it went onto a floor after all: forgotten
    MF.note_result(m, dict(ACT), {"ok": True, "project_id": 9, "floor": {"id": 2, "elevation": 40}})
    assert MF.hint(m, dict(ACT), {}, dict(TRAITS), CFG).get("run_max") == h0.get("run_max")
    json.dumps(m.atlas)                       # the memory stays JSON


@plain_test("(a) the brain: r3g2_floor_spill off puts spill = false on the hint (on: no key, the builder spills)")
def _():
    m = drawn()
    act = {"type": "start_project", "kind": "bedrooms", "rooms": 4, "room_size": 3}
    assert "spill" not in MF.hint(m, act, {}, dict(TRAITS), CFG)
    assert MF.hint(m, act, {}, dict(TRAITS), dict(CFG, r3g2_floor_spill=False))["spill"] is False


@plain_test("(a) the bridge's parse_floor takes spill as one of its booleans (true or false, anything else refused)")
def _():
    src = (ROOT / "lua" / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    assert re.search(r"FLOOR_BOOLS = \{[^}]*'spill'", src), "spill is not one of parse_floor's booleans"


if __name__ == "__main__":
    finish()
