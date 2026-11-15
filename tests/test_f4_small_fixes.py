"""(F4) Three small fixes on the 0.105.55 floors (verify-v55.md V4, S2, S4).

  V4  a workshops level placed on a floor keeps no free_left (the floor layout drops the spare
      rooms and nothing can join a floor level); a classic one still does.
  S2  a floor level's box (round all its rooms, and its hall box) can hold a neighbour's rooms
      and the main hall: the readers that count or place inside a level (ai-welfare open_tombs,
      corner_spots; the bridge's act_allow_burial and the report's in_ai_tombs) use the level's
      own room tiles (B.own_areas).
  S4  a floor that just answered "refused: ..." for a request is not searched again for a few
      days (an in-memory note in ai-builder-floors.lua); the answer, and the classic fallback,
      stay the same.

They run on the fake fort of tests/test_b16_floors_end_to_end.py (its setup and helpers, as
tests/test_v55_floors_verify.py does), with the real lua/ai-welfare.lua loaded beside it.

    python tests/test_f4_small_fixes.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import finish, make_test  # noqa: E402

_B16 = ROOT / "tests" / "test_b16_floors_end_to_end.py"
_SRC = _B16.read_text(encoding="utf-8")
_NS: dict = {"__name__": "b16_top_for_f4", "__file__": str(_B16)}
exec(compile(_SRC[:_SRC.index("# ----------------------------------------------------------------"
                              "----------- 1. the worked example")], str(_B16), "exec"), _NS)

F = type("B16", (), {})()
F.__dict__.update(_NS)
test = make_test(before=lambda: F._reset())
ROCK_Z, SX, SY = F.ROCK_Z, F.SX, F.SY
HINT = dict(elevs=[ROCK_Z], tag="homes", dirs=["east"])

# the real ai-welfare, its DF and ai-util faked; reqscript('ai-builder') is the fake fort's builder
# (tile_taken answered from W.taken: the fake fort has no dfhack.buildings)
WELFARE = r"""
local src, B, E = ...
local W = {taken = {}, tombs = {}, site = {}}
local env = setmetatable({}, {__index = _G})
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {global = {world = {buildings = {other = {ZONE_TOMB = W.tombs}}}}}
env.dfhack = {maps = {canWalkBetween = function() return true end}}
local U = {site_get = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
           site_put = function(k, v) W.site[k] = v end,
           citizens = function() return {} end, abs_tick = function() return 0 end}
local BP = setmetatable({tile_taken = function(x, y, z) return W.taken[x .. ',' .. y .. ',' .. z] == true end},
                        {__index = B})
env.reqscript = function(n)
  if n == 'ai-util' then return U end
  if n == 'ai-builder' then return BP end
  error('no module ' .. tostring(n))
end
assert(load(src, 'ai-welfare', 't', env))()
W.env = env
E.mods['ai-welfare'] = env
return W
"""


def welfare():
    return F.LUA.execute(WELFARE, (ROOT / "lua" / "ai-welfare.lua").read_text(encoding="utf-8"), F.B, F.E)


def no_welfare():
    F.E.mods["ai-welfare"] = None


def tomb(w, x, y, owner=-1):
    """A 1x1 tomb zone with automatic burial of citizens off (a player's), owned by nobody."""
    z = F.tbl({"x1": x, "x2": x, "y1": y, "y2": y, "z": ROCK_Z, "assigned_unit_id": owner,
               "zone_settings": {"tomb": {"flags": {"no_citizens": True}}}})
    w.tombs[len(w.tombs) + 1] = z
    return z


def neighbours():
    """A one-room bedrooms level, then a storage level whose box holds that room (as test 2b of
    tests/test_b16_floors_end_to_end.py): (bedrooms project, storage project, the bedroom's room tiles)."""
    r1 = F.start(kind="bedrooms", rooms=1, room_size=3, floor=dict(HINT))
    r2 = F.start(kind="storage", piles=["food", "stone", "wood", "bars", "cloth", "furniture"], room_size=5,
                 floor=dict(HINT))
    assert r1.ok and r2.ok and r1.floor is not None and r2.floor is not None, (F.plain(r1), F.plain(r2))
    p1, p2 = F.project(r1.project_id), F.project(r2.project_id)
    room1 = F.proj_tiles(p1) - F.proj_links(p1)
    a = p2.area
    inside = [t for t in room1 if a.x1 <= t[0] <= a.x2 and a.y1 <= t[1] <= a.y2]
    assert inside, f"the scene changed: the storage level's box holds none of the bedroom\n{F.draw(ROCK_Z)}"
    return p1, p2, room1, inside


def hall_tiles():
    """Every hall tile on the floor (the projects' links and the hub round the stair)."""
    out = {(SX + dx, SY + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    for p in F.projects():
        out |= F.proj_links(p)
    return out


# --------------------------------------------------------------------------- V4

@test("V4. a workshops level on a floor is saved with no free_left (no spare room is dug there); "
      "a classic one keeps its spare as free_left")
def _():
    r = F.start(kind="workshops", shops=["Masons"], spare=2, floor=dict(elevs=[ROCK_Z], tag="industry"))
    assert r.ok and r.floor is not None, F.plain(r)
    p = F.project(r.project_id)
    assert p.free_left is None and p.params.spare == 2, (p.free_left, F.plain(p.params))
    r2 = F.start(kind="workshops", shops=["Masons"], spare=2, floor=False)
    assert r2.ok and r2.floor is None, F.plain(r2)
    assert F.project(r2.project_id).free_left == 2


@test("V4. a finished floor workshops level is not kept by save_projects as a 'free level' "
      "(it is closed and dropped like any other once past KEEP_CLOSED_PROJECTS)")
def _():
    r = F.start(kind="workshops", shops=["Masons"], spare=2, floor=dict(elevs=[ROCK_Z], tag="industry"))
    assert r.ok and r.floor is not None, F.plain(r)
    F.LUA.execute("""
      local B, id = ...
      local data = B.load_projects()
      for _, p in ipairs(data.list) do if p.id == id then p.phase = 'done' end end
      local keep = B.KEEP_CLOSED_PROJECTS
      B.KEEP_CLOSED_PROJECTS = 0
      B.save_projects(data)
      B.KEEP_CLOSED_PROJECTS = keep
    """, F.B, r.project_id)
    assert not [p for p in F.projects() if p.id == r.project_id], "the floor workshops level was kept"


# --------------------------------------------------------------------------- S2

@test("S2 proof. open_tombs from a floor tomb level's finish: a player's tomb zone in a neighbour's "
      "room inside the level's box stays closed; the level's own tombs open")
def _():
    p1, p2, room1, inside = neighbours()
    # the storage level's record made a tomb level's (a tomb level is one unit, so its own box holds no
    # neighbour; a wider level's does, and the reader is the same): its finish opens the tombs in it
    F.LUA.execute("""
      local B, id = ...
      local data = B.load_projects()
      for _, p in ipairs(data.list) do if p.id == id then p.kind = 'tombs'; p.phase = 'furnish' end end
      B.save_projects(data)
    """, F.B, p2.id)
    w = welfare()
    try:
        x, y = sorted(inside)[0]
        theirs = tomb(w, x, y)
        own_room = sorted(F.proj_tiles(p2) - F.proj_links(p2))[0]
        mine = tomb(w, *own_room)
        F.B.furnish_progress = F.LUA.eval("function() return {placed = 0, done = 0, waiting = {}} end")
        fin = F.B.finish_project(p2.id)
        assert fin.ok, F.plain(fin)
        assert theirs.zone_settings.tomb.flags.no_citizens is True, \
            f"the neighbour's tomb at {(x, y)} was opened (burial {fin.burial})\n{F.draw(ROCK_Z)}"
        assert mine.zone_settings.tomb.flags.no_citizens is False and fin.burial == 1, fin.burial
    finally:
        no_welfare()


@test("S2 proof. corner_spots on a finished floor level: never in a neighbour's room (here a bedroom), "
      "never on the main hall")
def _():
    p1, p2, room1, inside = neighbours()
    F.LUA.execute("""
      local B, id = ...
      local data = B.load_projects()
      for _, p in ipairs(data.list) do p.phase = 'done' end
      B.save_projects(data)
    """, F.B, p2.id)
    F.dig_all()
    w = welfare()
    try:
        spots = F.plain(w.env.corner_spots(40)) or []
        assert spots, f"no spot at all\n{F.draw(ROCK_Z)}"
        got = {(s["x"], s["y"]) for s in spots}
        bad_room = got & room1
        bad_hall = got & hall_tiles()
        assert not bad_room, f"coffin spots in the bedroom: {sorted(bad_room)}\n{F.draw(ROCK_Z)}"
        assert not bad_hall, f"coffin spots on the main hall: {sorted(bad_hall)}\n{F.draw(ROCK_Z)}"
        own = F.proj_tiles(p2) - F.proj_links(p2)
        assert got <= own, sorted(got - own)
    finally:
        no_welfare()


@test("S2. B.own_areas: a classic level's boxes are project_areas'; a floor level's is its room box, "
      "own() true only on its own room tiles (not the hall, not a neighbour's room)")
def _():
    p1, p2, room1, inside = neighbours()
    oa = F.B.own_areas(p2)
    assert len(oa) == 1 and oa[1].own is not None
    own = F.proj_tiles(p2) - F.proj_links(p2)
    test_ = oa[1].own

    def is_own(x, y):
        return test_(F.tbl({"x1": x, "y1": y, "x2": x, "y2": y}))
    assert all(is_own(x, y) for x, y in own)
    assert not any(is_own(x, y) for x, y in room1)
    assert not any(is_own(x, y) for x, y in hall_tiles())
    # the saved record is untouched (no function in it)
    assert F.project(p2.id).area.own is None
    classic = F.tbl({"area": {"x1": 1, "y1": 1, "x2": 5, "y2": 5, "z": 9},
                     "areas": [{"x1": 0, "y1": 0, "x2": 2, "y2": 2, "z": 9}]})
    oc = F.B.own_areas(classic)
    assert len(oc) == 2 and oc[1].own is None and F.plain(oc[1]) == F.plain(classic.area), F.plain(oc)


@test("S2. the bridge's act_allow_burial and the report's in_ai_tombs read the tomb levels through own_areas")
def _():
    acts = (ROOT / "lua" / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    i = acts.index("function act_allow_burial")
    body = acts[i:acts.index("\nend\n", i)]
    assert "own_areas" in body and "ar.own" in body, body[:600]
    rep = (ROOT / "lua" / "ai-bridge-report.lua").read_text(encoding="utf-8")
    i = rep.index("function in_ai_tombs")
    body = rep[i:rep.index("\nend\n", i)]
    assert "own_areas" in body and "a.own" in body, body[:600]
    proj = (ROOT / "lua" / "ai-builder-projects.lua").read_text(encoding="utf-8")
    assert proj.count("reqscript('ai-welfare').open_tombs(own_areas(p))") == 2


# --------------------------------------------------------------------------- S4

REFUSE = r"""
local B, E, why = ...
local P = E.mods['ai-floorplace']
E.real_place = E.real_place or P.place
E.places = 0
P.place = function(floor, req, G, env)
  E.places = E.places + 1
  local p, w = E.real_place(floor, req, G, env)
  if type(p) == 'table' and why then return {puts = {}, runs = p.runs, hall = p.hall} end
  return p, w
end
"""


def refusing(on=True):
    F.LUA.execute(REFUSE, F.B, F.E, "yes" if on else None)


def unrefuse():
    if F.E.real_place is not None:
        F.E.mods["ai-floorplace"].place = F.E.real_place


@test("S4. a floor that refused a request is not searched again for that request a day later: same "
      "answer (classic), same reason; searched again after REFUSED_DAYS, or for another request size")
def _():
    try:
        refusing()
        hint = dict(elevs=[ROCK_Z], tag="homes", dirs=["east"])
        F.E.tick = 100
        r1 = F.start(kind="bedrooms", rooms=2, room_size=3, floor=dict(hint))
        assert r1.ok and r1.floor is None and "refused: the placement holds no room" in str(r1.not_on_floor), \
            F.plain(r1)
        n1 = F.E.places
        assert n1 >= 1
        F.E.tick = 100 + 1200                     # a day later
        r2 = F.start(kind="bedrooms", rooms=2, room_size=3, floor=dict(hint), dry=True)
        assert r2.ok and r2.floor is None and F.E.places == n1, (F.E.places, n1, F.plain(r2))
        assert "refused: the placement holds no room" in str(r2.not_on_floor), r2.not_on_floor
        # another size of request: searched
        F.start(kind="bedrooms", rooms=3, room_size=3, floor=dict(hint), dry=True)
        assert F.E.places > n1
        n2 = F.E.places
        # later than REFUSED_DAYS: searched again
        F.E.tick = 100 + int(F.B.FLOOR_REFUSED_DAYS * 1200) + 1
        F.start(kind="bedrooms", rooms=2, room_size=3, floor=dict(hint), dry=True)
        assert F.E.places > n2
    finally:
        unrefuse()


@test("S4. the note never holds across a clock gone back (another save) or a fresh projects record, "
      "and a dry run and the real run at one tick agree")
def _():
    try:
        refusing()
        hint = dict(elevs=[ROCK_Z], tag="homes", dirs=["east"])
        F.E.tick = 5000
        F.start(kind="bedrooms", rooms=2, room_size=3, floor=dict(hint), dry=True)
        n = F.E.places
        F.E.tick = 4000                            # the clock went back
        F.start(kind="bedrooms", rooms=2, room_size=3, floor=dict(hint), dry=True)
        assert F.E.places > n
        # the same tick: searched (a dry run, then its real run, give one answer)
        n = F.E.places
        d = F.start(kind="bedrooms", rooms=2, room_size=3, floor=dict(hint), dry=True)
        assert F.E.places > n
        n = F.E.places
        r = F.start(kind="bedrooms", rooms=2, room_size=3, floor=dict(hint))
        assert F.E.places > n and d.not_on_floor == r.not_on_floor and d.z == r.z, (F.plain(d), F.plain(r))
        # the floor works again: the note is no reason to keep away from it once its days are over,
        # and a different projects record (another fort: next_id lower than seen) forgets every note
        unrefuse()
        F.E.tick = 4000 + 600
        r2 = F.start(kind="bedrooms", rooms=2, room_size=3, floor=dict(hint))
        assert r2.ok and r2.floor is None, "the note was dropped too early (the test expects it held)"
        F._reset()
        F.E.tick = 4000 + 600
        r3 = F.start(kind="bedrooms", rooms=2, room_size=3, floor=dict(hint))
        assert r3.ok and r3.floor is not None, F.plain(r3)
    finally:
        unrefuse()


@test("S4. the floor search code: the note is kept in ai-builder-floors.lua only (no record field)")
def _():
    src = (ROOT / "lua" / "ai-builder-floors.lua").read_text(encoding="utf-8")
    assert "FLOOR_REFUSED_DAYS" in src and "FLOOR_REFUSED" in src
    for f in ("ai-floorplan.lua", "ai-builder-floorstore.lua"):
        assert "REFUSED" not in (ROOT / "lua" / f).read_text(encoding="utf-8"), f
    assert re.search(r"\nFLOOR_REFUSED_DAYS = \d", src)


if __name__ == "__main__":
    finish()
