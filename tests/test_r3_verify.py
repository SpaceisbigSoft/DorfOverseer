"""(r3 verify) Proof tests for bugs found where the three round-3 groups meet.

Each test states the behaviour the brief asks for and fails on r3-merge
(a6926b2) while the bug is there. Fixtures as tests/test_r3_g1.py,
test_r3_g2.py and test_r3_g3.py (the fake fort of tests/test_builder.py with
the real ai-floorplan, ai-floorplace and ai-floorunits).

    python tests/test_r3_verify.py
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import finish, have_lua, make_test, skip, test as plain_test  # noqa: E402

from planner import Memory, PLANNER_CONFIG  # noqa: E402
import masterplan_floors as MF  # noqa: E402
import planner_core  # noqa: E402
import planner_floors as PF  # noqa: E402

CFG = dict(PLANNER_CONFIG)
SPINE = {"x": 108, "y": 149}
DAY = 1200


def plan_mem() -> Memory:
    """test_r3_g1's plan: the homes on 38-40, the industry on 34-36, range 28-42."""
    m = Memory()
    m.culture = {"seed": "Test#1", "eras": [{"year": 250, "title": "Plain era"}]}
    m.atlas = {"survey": {"elevation_offset": -129, "tick": 1, "layers": [],
                          "site": {"stairs": [{"x": 108, "y": 149, "elev_top": 42, "elev_bottom": 31}]}},
               "entrances": {},
               "plan": {"districts": [{"id": "homes", "kind": "homes", "name": "homes", "lo": 38, "hi": 40,
                                       "target": 39, "dirs": ["east"]},
                                      {"id": "industry", "kind": "industry", "name": "industry", "lo": 34,
                                       "hi": 36, "target": 35, "dirs": ["north"]}],
                        "range": [28, 42], "spine": dict(SPINE), "vertical": "deep"}}
    assert MF.ensure(m, {}), "the floors table"
    return m


def bed():
    return {"type": "start_project", "kind": "bedrooms", "rooms": 4, "room_size": 3}


def day(d):
    return {"date": {"year": 250, "tick": d * DAY, "day": 1, "month": "Granite"}}


# ------------------------------------------------------------------ V1 (g1 x g3, brain)

@plain_test("V1 every planned elevation lately refused for roots (floor_soil): the hint offers the band's other "
            "and deeper elevations (as g1 does for full/refused ones), not the same three soil levels again")
def _():
    m = plan_mem()
    t0 = planner_core.abs_tick(day(9))
    m.atlas["floor_soil"] = {str(e): {"tick": t0, "n": 1} for e in (38, 39, 40)}
    h = MF.hint(m, bed(), day(10), {}, CFG)
    assert isinstance(h, dict), h
    # what g1 offers when the same three are full: deeper ones
    rep = {"v": 1, "list": [{"id": i, "elevation": e, "stair": dict(SPINE), "full": ["homes"], "no_hall": False}
                            for i, e in enumerate((38, 39, 40), 1)]}
    deeper = MF.elevs_for(m, "bedrooms", bed(), {}, rep, CFG)
    assert deeper and not set(deeper) & {38, 39, 40}, deeper
    assert not set(h["elevs"]) <= {38, 39, 40}, (
        f"only the soil-refused elevations offered again: {h['elevs']} (g1 would offer {deeper})")


@plain_test("V1b two of three planned elevations soil-refused: g1's 'fewer than r3g1_floor_open_min open' "
            "rule should still add the band's/deeper ones (the soil filter runs after that decision)")
def _():
    m = plan_mem()
    t0 = planner_core.abs_tick(day(9))
    m.atlas["floor_soil"] = {str(e): {"tick": t0, "n": 1} for e in (39, 40)}
    h = MF.hint(m, bed(), day(10), {}, CFG)
    assert isinstance(h, dict), h
    assert len(h["elevs"]) >= CFG.get("r3g1_floor_open_min", 2), f"one elevation left to offer: {h['elevs']}"


# ------------------------------------------------------------------ V4 (g3: LAST_SENT)

@plain_test("V4 a hint set by floor_action whose send never reached journal (an error out of bridge.act other "
            "than BridgeError/DFHackError) must not be journaled on a later, unsent line of the same kind")
def _():
    PF.LAST_SENT.clear()
    m = plan_mem()
    sent = PF.floor_action(bed(), {}, m, CFG)
    assert "floor" in sent, sent                        # the hint was put on the action
    # ... bridge.act raised; the journal line for it was never written. Next cycle (or the next fort),
    # in dry-run, a bedrooms level is proposed but nothing is sent:
    # (fix) the overseer forgets any hint before each proposal (planner_floors.forget_sent)
    PF.forget_sent()
    got = PF.journal_hint(bed(), CFG)
    PF.LAST_SENT.clear()
    assert got == {}, f"a hint never sent with this line was journaled: {got}"
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    i = src.index("for p in allowed:")
    assert "floor_forget_sent()" in src[i:i + 300], "the overseer must forget the last hint before each proposal"


# ------------------------------------------------------------------ the fake fort (Lua)

LUA = B = W = TB = E = None
if have_lua():
    import test_builder as TB  # noqa: E402
    LUA, B, W = TB.LUA, TB.B, TB.W
    _b16 = (ROOT / "tests" / "test_b16_floors_end_to_end.py").read_text(encoding="utf-8")
    SETUP = re.search(r'SETUP = r"""(.*?)"""', _b16, re.S).group(1)
    _srcs = {n: (ROOT / "lua" / f"{n}.lua").read_text(encoding="utf-8")
             for n in ("ai-floorplan", "ai-floorplace", "ai-floorunits")}
    E = LUA.execute(SETUP, B, LUA.globals().LAYOUTS, LUA.table_from(_srcs))

SX, SY, ROCK_Z = 60, 60, 63
KEY = "ai-overseer/floors"
DEFAULTS = {}


def _reset():
    if TB is None:
        skip("needs the lupa package (pip install lupa)")
    W.size = LUA.table_from([120, 120, 100])
    TB._reset(False)
    E.mode, E.link, E.tick = "hallway", None, 0
    E.links = LUA.table()
    B.walk_group = E.real_walk
    B.MAX_OPEN_PROJECTS = 100
    B.FLOOR_SECONDS = 30
    for k in ("FLOOR_SPILL", "FLOOR_BIG_STOP", "FLOOR_FULL_BY_SIZE", "FLOOR_KEEP_CLEAR", "FLOOR_STAIR_TRIES",
              "FLOOR_HUB_MARK", "FLOOR_STAIRS_APART", "FLOOR_STAIRS", "FLOOR_STAIRS_MORE", "FLOOR_KEEP_ARM"):
        DEFAULTS.setdefault(k, B[k])
        B[k] = DEFAULTS[k]


lua_test = make_test(before=_reset)


def tbl(v):
    if isinstance(v, dict):
        return LUA.table_from({k: tbl(x) for k, x in v.items()})
    if isinstance(v, (list, tuple)):
        return LUA.table_from([tbl(x) for x in v])
    return v


def plain(v):
    if LUA.eval("type")(v) != "table":
        return v
    keys = list(v.keys())
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [plain(v[i]) for i in range(1, len(keys) + 1)]
    return {k: plain(v[k]) for k in keys}


def start(**kw):
    r = B.start_project(tbl(kw), LUA.table_from({"year": 148, "tick": 100}), False)
    assert "failed:" not in str(r.not_on_floor or ""), f"a floor module raised: {r.not_on_floor}"
    return r


def store():
    return plain(W.persist[KEY]) if W.persist[KEY] is not None else None


def hits(boxes, z, x, y):
    return [b for b in boxes if b["z"] == z and b["x1"] <= x <= b["x2"] and b["y1"] <= y <= b["y2"]]


BED = dict(kind="bedrooms", rooms=4, room_size=3)
GRAND = dict(kind="dining", tables=8, style={"grand": True})
PLAN63 = {"elev_lo": ROCK_Z, "elev_hi": ROCK_Z, "elev_target": ROCK_Z}


# ------------------------------------------------------------------ V2 (g2 keep-clear x hint False)

@lua_test("V2 a level sent with floor = false (g2's 'too big, classic at once', g3's holy level with only soil "
          "left, CLASSIC_CUSTOMS, landmarks) still keeps clear of a live floor's hub and planned hall")
def _():
    r = start(floor=dict(elevs=[ROCK_Z], dirs=["east"]), **copy.deepcopy(BED))
    assert r.ok and r.floor is not None and int(r.z) == ROCK_Z, plain(r)
    seen = []
    real = B.choose_site

    def spy(L, stairs, reserved, plan, ceil_z):
        seen.append([str(x.why) for x in reserved.values() if x.why is not None])
        return real(L, stairs, reserved, plan, ceil_z)
    B.choose_site = spy
    try:
        r2 = start(plan=PLAN63, floor={"elevs": [ROCK_Z], "run_max": 12}, **copy.deepcopy(GRAND))   # hint, refused
        r3 = start(plan=PLAN63, floor=False, **copy.deepcopy(GRAND))                       # classic on purpose
    finally:
        B.choose_site = real
    assert r2.ok and r3.ok, (plain(r2), plain(r3))
    assert len(seen) == 2, seen
    assert any("floor 1" in w for w in seen[0]), f"(the hinted level keeps clear: {seen[0]})"
    assert any("floor 1" in w for w in seen[1]), (
        f"the floor=false level was placed with none of floor 1's kept boxes reserved: {seen[1]}")


# ------------------------------------------------------------------ V3 (g2 keep-clear x g1 dead '*')

@lua_test("V3 a dead floor (its levels cancelled, runs released, the hub then used; g1 marks it '*' and the brain "
          "stops offering it) no longer reserves its released run out to run_max and four arms for classic levels")
def _():
    hint = {"elevs": [ROCK_Z], "tag": "homes", "dirs": ["east"]}
    r1 = start(floor=dict(hint), **copy.deepcopy(BED))
    assert r1.ok and r1.floor is not None, plain(r1)
    fid = plain(r1.floor)["id"]
    assert B.cancel_project(r1.project_id).ok
    W.set(SX + 1, SY, ROCK_Z, LUA.table_from({"shape": "FLOOR", "taken": True}))     # the hub used
    r2 = start(floor=dict(hint), **copy.deepcopy(BED))
    assert r2.floor is None and "refused: the stair's hub" in str(r2.not_on_floor), plain(r2)
    row = next(x for x in plain(B.floors_report())["list"] if x["id"] == fid)
    assert row.get("dead") and row.get("no_hall"), row
    keep = plain(B.floor_keep_boxes(tbl({"kind": "bedrooms", "rooms": 4, "floor": {"elevs": [ROCK_Z - 1]}}),
                                    B.find_stairs(3)))
    mine = [b for b in keep if b["z"] == ROCK_Z and f"floor {fid}" in b["why"]]
    assert not mine, f"the dead, '*'-marked floor {fid} still keeps {len(mine)} boxes: {mine}"


if __name__ == "__main__":
    finish()
