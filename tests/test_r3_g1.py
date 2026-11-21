"""(r3 g1) Hallway floors that keep opening (15-16 Nov run: the floors went
dormant after the first game year or two, A 18% and D 21% of new levels on a
floor; R-AD.md, R-CE.md, R-B.md section 2).

(a) masterplan_floors.elevs_for offers the band's other and deeper
    elevations once the planned ones are full or refused (a full tag, a level
    no hall can start on, a refusal in the last fallback), not only the role
    elevations the master plan fixed in y250.
(b) a floor may start from another of the fort's stairs: each stair after
    the first has tries of its own (the first stair's refusals no longer use
    up the search), the hint names the plan's other stairwells (`stairs`,
    `stair_tries`, kept by the bridge's parse_floor), and two columns of one
    stairwell count once.
(c) a floor with no hall left (its levels all cancelled) whose hub the fort
    then used: "refused: the stair's hub" marks the level '*' (no_hall, the
    report row `dead`), so it is skipped and no longer offered (D's floor 3,
    refused 39 times).

On the fake fort of tests/test_builder.py with the real ai-floorplan,
ai-floorplace and ai-floorunits (as tests/test_b16_floors_end_to_end.py
loads them), and the brain's masterplan_floors on a hand-made plan.

    python tests/test_r3_g1.py
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import finish, have_lua, make_test, skip  # noqa: E402

from planner import Memory, PLANNER_CONFIG  # noqa: E402
import masterplan_floors as MF  # noqa: E402

CFG = dict(PLANNER_CONFIG)

# ---------------------------------------------------------------------------- the brain

SPINE = {"x": 108, "y": 149}


def plan_mem(stairwell=None) -> Memory:
    """A plan as the master plan draws it (A's: the homes on 38-40, the workshops on 34-36),
    with its floors table made."""
    m = Memory()
    m.culture = {"seed": "Test#1", "eras": [{"year": 250, "title": "Plain era"}]}
    homes = {"id": "homes", "kind": "homes", "name": "homes", "lo": 38, "hi": 40, "target": 39,
             "dirs": ["east"]}
    if stairwell:
        homes["stair"] = dict(stairwell)
    m.atlas = {"survey": {"elevation_offset": -129, "tick": 1, "layers": [],
                          "site": {"stairs": [{"x": 108, "y": 149, "elev_top": 42, "elev_bottom": 31},
                                              {"x": 140, "y": 120, "elev_top": 40, "elev_bottom": 20}]}},
               "entrances": {},
               "plan": {"districts": [homes,
                                      {"id": "industry", "kind": "industry", "name": "industry", "lo": 34,
                                       "hi": 36, "target": 35, "dirs": ["north"]}],
                        "range": [28, 42], "spine": dict(SPINE), "vertical": "deep"}}
    assert MF.ensure(m, {}), "the floors table"
    return m


def bed():
    return {"type": "start_project", "kind": "bedrooms", "rooms": 4, "room_size": 3}


def row(fid, elev, full=(), no_hall=False, stair=SPINE):
    return {"id": fid, "elevation": elev, "stair": dict(stair), "full": list(full), "no_hall": no_hall}


test = make_test()


@test("(a) every planned floor full for the tag: the deeper levels are offered first, another district's "
      "band after the free ones; the full ones last")
def _():
    m = plan_mem()
    sl = m.atlas["plan"]["floors"]["roles"]["sleeping"]["elevs"]
    assert sl == [40, 38, 39], sl
    assert MF.elevs_for(m, "bedrooms", bed(), {}, None, CFG) == sl          # nothing full: as before
    rep = {"v": 1, "list": [row(i + 1, e, ["homes"]) for i, e in enumerate(sl)]}
    got = MF.elevs_for(m, "bedrooms", bed(), {}, rep, CFG)
    assert got == [37, 33, 32, 31], got                 # (main: [40, 38, 39], every one of them full)
    assert MF.elevs_for(m, "bedrooms", bed(), {}, rep, dict(CFG, floor_elevs_max=6)) == [37, 33, 32, 31, 30, 29]
    # never under the plan's range (28) nor more than r3g1_floor_deeper_max under the band
    got = MF.elevs_for(m, "bedrooms", bed(), {}, rep, dict(CFG, floor_elevs_max=6, r3g1_floor_deeper_max=2))
    assert got == [37, 36, 40, 38, 39], got             # 36 is the workshops' band: after 37, then the full ones
    # one planned floor still open: it first, then the deeper ones
    rep["list"][0]["full"] = []
    assert MF.elevs_for(m, "bedrooms", bed(), {}, rep, CFG) == [40, 37, 33, 32]
    # another tag's full floors, a floor on another stair: not counted
    rep2 = {"v": 1, "list": [row(1, 40, ["industry"]), row(2, 38, ["homes"], stair={"x": 1, "y": 1}),
                             row(3, 39, ["homes"])]}
    assert MF.elevs_for(m, "bedrooms", bed(), {}, rep2, CFG) == [40, 38, 39]
    # the switch off: the old list (full ones last, nothing deeper)
    assert MF.elevs_for(m, "bedrooms", bed(), {}, rep, dict(CFG, r3g1_floor_more_elevs=False)) == [40, 38, 39]


@test("(a) a level no hall can start on (no_hall: the hub refused too) and the last fallback's refusals count "
      "as full; the switch off: they don't")
def _():
    m = plan_mem()
    rep = {"v": 1, "list": [row(1, 40, no_hall=True), row(3, 38)],
           "last": {"ok": False, "kind": "storage",
                    "why": "floor 3: refused: not natural rock (ROOT) at x107 y177 z167; z39: refused: open to the sky"}}
    got = MF.elevs_for(m, "bedrooms", bed(), {}, rep, CFG)
    assert got == [37, 33, 32, 31], got
    assert MF.elevs_for(m, "bedrooms", bed(), {}, rep, dict(CFG, r3g1_floor_skip_no_hall=False)) == [40, 38, 39]
    # the last placement went onto a floor: its words are no refusal (two planned ones open: no deeper ones)
    rep["last"]["ok"] = True
    assert MF.elevs_for(m, "bedrooms", bed(), {}, rep, CFG) == [38, 39, 40]
    # junk never raises
    for junk in ({"list": [{"elevation": "x", "no_hall": True}], "last": {"ok": False, "why": 7}},
                 {"last": "x"}, {"error": "boom", "last": {"ok": False, "why": "z40: refused: x"}}):
        assert MF.elevs_for(m, "bedrooms", bed(), {}, junk, CFG) == [40, 38, 39], junk


@test("(b) the hint names the other stairs (the district's stairwell is the spine, the plan's spine and the "
      "survey's other stair after it) and stair_tries; within the bridge's ranges; the switches")
def _():
    m = plan_mem(stairwell={"x": 130, "y": 149})
    h = MF.hint(m, bed(), {}, {}, CFG)
    assert h["spine"] == {"x": 130, "y": 149}, h
    assert h["stairs"] == [{"x": 108, "y": 149}, {"x": 140, "y": 120}], h
    assert h["stair_tries"] == 1, h
    h = MF.hint(m, bed(), {}, {}, dict(CFG, r3g1_floor_stairs=False))
    assert "stairs" not in h and h["stair_tries"] == 1, h
    h = MF.hint(m, bed(), {}, {}, dict(CFG, r3g1_floor_stair_tries=0))
    assert "stairs" not in h and h["stair_tries"] == 0, h
    h = MF.hint(m, bed(), {}, {}, dict(CFG, r3g1_floor_stair_tries=9))
    assert h["stair_tries"] == 3, h


# ---------------------------------------------------------------------------- the bridge's parse_floor

BR = None
if have_lua():
    from lupa.lua53 import LuaRuntime
    _hyg = (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8")
    _HARNESS = re.search(r'HARNESS = r"""(.*?)"""', _hyg, re.S).group(1)
    BR = LuaRuntime(unpack_returned_tuples=True)
    _H = BR.execute(_HARNESS, (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8"), str(ROOT / "lua"))
    _H.scripts = BR.table()
    _M = _H.module()
    _CALL2 = BR.eval("function(f, v) local h, e = f(v) return {h = h, e = e} end")


def bt(v):
    if isinstance(v, dict):
        return BR.table_from({k: bt(x) for k, x in v.items()})
    if isinstance(v, (list, tuple)):
        return BR.table_from([bt(x) for x in v])
    return v


def bplain(v):
    if BR.eval("type")(v) != "table":
        return v
    keys = list(v.keys())
    if keys and sorted(keys, key=str) == sorted(range(1, len(keys) + 1), key=str):
        return [bplain(v[i]) for i in range(1, len(keys) + 1)]
    return {k: bplain(v[k]) for k in keys}


@test("(b) parse_floor keeps stair_tries (0-3) and stairs (1-6, x and y 0-999); a bad one is refused by name")
def _():
    if BR is None:
        skip("needs the lupa package (pip install lupa)")
    r = _CALL2(_M.parse_floor, bt({"elevs": [40], "stair_tries": 2, "stairs": [{"x": 108, "y": 149}, {"x": 0, "y": 999}]}))
    assert r.e is None and bplain(r.h) == {"elevs": [40], "stair_tries": 2,
                                           "stairs": [{"x": 108, "y": 149}, {"x": 0, "y": 999}]}, (r.e, bplain(r.h))
    for bad in ({"stair_tries": 4}, {"stair_tries": "1"}, {"stair_tries": 1.5}, {"stairs": []},
                {"stairs": [{"x": 1}]}, {"stairs": [{"x": 1000, "y": 1}]}, {"stairs": "x"},
                {"stairs": [{"x": i, "y": i} for i in range(7)]}):
        r = _CALL2(_M.parse_floor, bt(bad))
        assert r.h is None and ("floor." + next(iter(bad))) in str(r.e), (bad, r.e)


# ---------------------------------------------------------------------------- the builder (fake fort)

LUA = B = W = TB = E = None
if have_lua():
    import test_builder as TB  # noqa: E402  (its fake fort; its tests run only when it is run itself)
    LUA, B, W = TB.LUA, TB.B, TB.W

SETUP = r"""
local B, LAYOUTS, srcs = ...
local real = REAL_REQ_R3G1 or reqscript
REAL_REQ_R3G1 = real
E = {mode = 'hallway', tick = 0}
local function load_module(src, name)
  local env = setmetatable({}, {__index = _G})
  assert(load(src, name, 't', env))()
  return env
end
local mods = {}
for name, src in pairs(srcs) do mods[name] = load_module(src, name) end
mods['ai-floorunits'].LAYOUTS = LAYOUTS
mods['ai-overseer-settings'] = {load_settings = function() return {floor_layout = E.mode} end}
mods['ai-pile-links'] = {LINKABLE = {}, remember_feeder = function() return true end,
                         link_feeder = function() return {ok = true} end}
reqscript = function(name)
  local m = mods[name]
  if m then return m end
  return real(name)
end
E.real_now = B.now_tick
B.now_tick = function() return E.tick end
E.real_walk = B.walk_group
return E
"""

if TB is not None:
    _srcs = {n: (ROOT / "lua" / f"{n}.lua").read_text(encoding="utf-8")
             for n in ("ai-floorplan", "ai-floorplace", "ai-floorunits")}
    E = LUA.execute(SETUP, B, LUA.globals().LAYOUTS, LUA.table_from(_srcs))

SX, SY = 60, 60          # the fake fort's main stair (z 60-80)
ZS = (61, 62, 63)        # levels of the main stair in solid rock
KEY = "ai-overseer/floors"
DEFAULTS = {}


def _reset():
    if TB is None:
        skip("needs the lupa package (pip install lupa)")
    W.size = LUA.table_from([120, 120, 100])
    TB._reset(False)
    E.mode, E.tick = "hallway", 0
    B.walk_group = E.real_walk
    B.MAX_OPEN_PROJECTS = 100
    B.FLOOR_SECONDS = 30
    for k in ("FLOOR_STAIR_TRIES", "FLOOR_HUB_MARK", "FLOOR_STAIRS_APART", "FLOOR_STAIRS", "FLOOR_STAIRS_MORE"):
        DEFAULTS.setdefault(k, B[k])
        B[k] = DEFAULTS[k]


ltest = make_test(before=_reset)


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
    r = B.start_project(tbl(kw), LUA.table_from({"year": 250, "tick": 100}), False)
    assert "failed:" not in str(r.not_on_floor or ""), f"a floor module raised: {r.not_on_floor}"
    return r


def store():
    return plain(W.persist[KEY]) if W.persist[KEY] is not None else None


def hub_used(z, sx=SX, sy=SY):
    """The stair's hub on level z used by the fort (a dug tile with a building on it)."""
    W.set(sx + 1, sy, z, LUA.table_from({"shape": "FLOOR", "taken": True}))


def second_stair(x=90, y=60):
    TB._stair(x, y, 60, 80)
    W.citizens = tbl(plain(W.citizens) + [{"x": x - 2, "y": y, "z": 70}])


def rows():
    return {(r["z"], r["stair"]["x"], r["stair"]["y"]): r for r in plain(B.floors_report())["list"]}


BED = dict(kind="bedrooms", rooms=4, room_size=3)


@ltest("(b) the main stair's hub used at every level offered: the level's floor starts on the second stair "
       "(main: three hub refusals use up the search, the level goes classic); the main stair's levels are "
       "marked no_hall")
def _():
    second_stair()
    for z in ZS:
        hub_used(z)
    r = start(floor={"elevs": list(ZS), "tag": "homes"}, **copy.deepcopy(BED))
    assert r.ok and r.floor is not None, plain(r)
    f = plain(r.floor)
    assert f["stair"] == {"x": 90, "y": 60} and f["elevation"] == ZS[0], f
    rw = rows()
    for z in ZS:
        assert rw[(z, SX, SY)]["no_hall"], (z, rw.get((z, SX, SY)))
    # the next level: the main stair's marked levels cost nothing, it goes on the second stair's floor
    r2 = start(floor={"elevs": list(ZS), "tag": "homes"}, **copy.deepcopy(BED))
    assert r2.ok and r2.floor is not None and plain(r2.floor)["stair"] == {"x": 90, "y": 60}, plain(r2)
    assert plain(r2.floor)["id"] == f["id"], plain(r2.floor)


@ltest("(b) the stair budget alone (the hub mark off): the first stair's three refusals leave the second stair "
       "its own try; stair_tries 0 in the hint: the old search (classic)")
def _():
    B.FLOOR_HUB_MARK = False
    second_stair()
    for z in ZS:
        hub_used(z)
    r = start(floor={"elevs": list(ZS), "tag": "homes", "stair_tries": 0}, **copy.deepcopy(BED))
    assert r.ok and r.floor is None and str(r.not_on_floor).count("the stair's hub") == 3, plain(r)
    _reset()
    B.FLOOR_HUB_MARK = False
    second_stair()
    for z in ZS:
        hub_used(z)
    r = start(floor={"elevs": list(ZS), "tag": "homes"}, **copy.deepcopy(BED))
    assert r.ok and r.floor is not None and plain(r.floor)["stair"] == {"x": 90, "y": 60}, plain(r)


@ltest("(b) a stair the hint names (a district's stairwell the dwarves do not crowd) is tried right after the "
       "spine; a column beside the main stair (the same stairwell) is not tried")
def _():
    B.FLOOR_HUB_MARK = False
    B.FLOOR_STAIRS = 2
    TB._stair(62, 60, 60, 80)          # a second column of the main stairwell
    second_stair(100, 60)
    W.citizens = tbl([{"x": 61, "y": 61, "z": 70}] * 5)   # nobody near the far stair: find_stairs ranks it last
    for z in ZS:
        hub_used(z)
    r = start(floor={"elevs": list(ZS), "tag": "homes", "stairs": [{"x": 100, "y": 60}]}, **copy.deepcopy(BED))
    assert r.ok and r.floor is not None and plain(r.floor)["stair"] == {"x": 100, "y": 60}, plain(r)
    assert not any(k[1] == 62 for k in rows()), "the column beside the main stair was tried"


@ltest("(c) a floor whose only level was cancelled and whose hub the fort then used: refused once, marked "
       "'*' (the row no_hall and dead), skipped after that (main: refused again every time, never no_hall)")
def _():
    hint = {"elevs": [ZS[0]], "tag": "homes", "dirs": ["east"]}
    r1 = start(floor=dict(hint), **copy.deepcopy(BED))
    assert r1.ok and r1.floor is not None, plain(r1)
    fid = plain(r1.floor)["id"]
    assert B.cancel_project(r1.project_id).ok
    hub_used(ZS[0])
    rec = next(f for f in store()["floors"] if f["id"] == fid)
    assert all(s.get("dead") for s in rec["slots"]) and all(rr["closed"] == "released" for rr in rec["runs"]), rec
    r2 = start(floor=dict(hint), **copy.deepcopy(BED))
    assert r2.ok and r2.floor is None and f"floor {fid}: refused: the stair's hub" in str(r2.not_on_floor), plain(r2)
    row_ = rows()[(ZS[0], SX, SY)]
    assert row_["id"] == fid and row_["no_hall"] is True and row_.get("dead") is True, row_
    E.tick = 5 * 1200            # (past the in-memory refusal note's 3 days)
    r3 = start(floor=dict(hint), **copy.deepcopy(BED))
    assert f"floor {fid}: no hall can start here" in str(r3.not_on_floor), plain(r3)
    # the brain offers that level last while the mark is fresh (with the other two full: deeper ones first)
    m = plan_mem()
    rep = {"v": 1, "list": [dict(row_, elevation=40, stair=SPINE)]}
    assert MF.elevs_for(m, "bedrooms", bed(), {}, rep, CFG) == [38, 39, 40]
    rep["list"] += [row(8, 38, ["homes"]), row(9, 39, ["homes"])]
    assert MF.elevs_for(m, "bedrooms", bed(), {}, rep, CFG) == [37, 33, 32, 31]
    # the mark grows old (full_retry_days): the level is looked at again
    E.tick = 40 * 1200
    r4 = start(floor=dict(hint), **copy.deepcopy(BED))
    assert f"floor {fid}: refused: the stair's hub" in str(r4.not_on_floor), plain(r4)


@ltest("(c) a cancelled floor whose hub is still clear starts again from it as before (the record kept)")
def _():
    hint = {"elevs": [ZS[0]], "tag": "homes", "dirs": ["east"]}
    r1 = start(floor=dict(hint), **copy.deepcopy(BED))
    fid = plain(r1.floor)["id"]
    assert B.cancel_project(r1.project_id).ok
    assert rows()[(ZS[0], SX, SY)].get("dead") is True
    r2 = start(floor=dict(hint), **copy.deepcopy(BED))
    assert r2.ok and r2.floor is not None and plain(r2.floor)["id"] == fid, plain(r2)
    assert "dead" not in rows()[(ZS[0], SX, SY)]


if __name__ == "__main__":
    finish()
