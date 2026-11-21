"""(X2) round-1 fixes in g6's mood code: V6 (no DF building object kept in
ai-moods' hospital cache) and V4 (the mood's slaughter keeps a kind's breeding
pair, young animals counted as future mates).

    python tests/test_x2_moods.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
import test_i2_thirst as I2  # noqa: E402

LUA_DIR = ROOT / "lua"


def _lua():
    I2.need_lua()
    from lupa.lua53 import LuaRuntime
    return LuaRuntime(unpack_returned_tuples=True)


# --- V6: the hospital zones ------------------------------------------------------------------------

def hospital_world():
    from lua_modules_util import module_src
    L = _lua()
    fake = re.search(r'FAKE = r"""(.*?)"""', (ROOT / "tests" / "test_moods.py").read_text(encoding="utf-8"),
                     re.S).group(1)
    W = L.execute(fake, module_src("ai-moods.lua"))
    W.reset()
    W.env.HOSPITAL_CACHE = None
    # R-AD: A's hospital zone 582, x104-112 y166-174 z163
    L.execute("""local W = ...
      local env = W.env
      W.finds, W.freed_reads, W.contains = 0, 0, 0
      W.zone = {id = 582, x1 = 104, x2 = 112, y1 = 166, y2 = 174, z = 163, contained_buildings = {}}
      W.alive = {[582] = W.zone}
      env.df.abstract_building_type = {HOSPITAL = 'HOSPITAL'}
      env.df.building_type = {BOX = 'Box'}
      env.df.building = {find = function(id) W.finds = W.finds + 1; return W.alive[id] end}
      env.dfhack.world = {getCurrentSite = function()
          return {buildings = {[0] = {getType = function() return 'HOSPITAL' end,
                                      getContents = function() return {building_ids = {[0] = 582}} end}}}
      end}
      env.dfhack.items.getPosition = function(it) return it.x, it.y, it.z end
      env.dfhack.buildings = {containsTile = function(b, x, y)
          W.contains = W.contains + 1
          if b.freed then W.freed_reads = W.freed_reads + 1 end
          return x >= b.x1 and x <= b.x2 and y >= b.y1 and y <= b.y2 end}
      function W.plain(v, seen)
          seen = seen or {}
          local t = type(v)
          if t == 'number' or t == 'string' or t == 'boolean' or t == 'nil' then return true end
          if t ~= 'table' or v == W.zone or seen[v] then return false end
          seen[v] = true
          for k, x in pairs(v) do
              if not W.plain(k, seen) or not W.plain(x, seen) then return false end
          end
          return true
      end
    """, W)
    return L, W


@test("V6 hospital_boxes: the day's cache holds plain data only (ids and the zone's box), never the zone object")
def _():
    L, W = hospital_world()
    env = W.env
    it = L.table_from({"x": 109, "y": 174, "z": 163})          # A's pig tail cloth
    assert env.hospital_ground(it) is True
    assert env.HOSPITAL_CACHE is not None
    assert W.plain(env.HOSPITAL_CACHE) is True, "a DF object (or a table that is one) is kept in HOSPITAL_CACHE"


@test("V6 hospital_ground: the zone removed within the day: found again by id (nil), no read of the freed building")
def _():
    L, W = hospital_world()
    env = W.env
    it = L.table_from({"x": 109, "y": 170, "z": 163})
    assert env.hospital_ground(it) is True
    L.execute("local W = ...; W.zone.freed = true; W.alive[582] = nil", W)
    before = W.contains
    assert env.hospital_ground(it) is False
    assert W.freed_reads == 0 and W.contains == before, "containsTile called on a removed zone"
    # (the box is still cached: the item is no longer the hospital's, so it is the mood's again)
    assert env.item_standing is not None


@test("V6 hospital_ground: off the zone's box or level: no find at all; inside: a fresh find and containsTile")
def _():
    L, W = hospital_world()
    env = W.env
    assert env.hospital_ground(L.table_from({"x": 109, "y": 170, "z": 163})) is True
    f0 = W.finds
    assert env.hospital_ground(L.table_from({"x": 140, "y": 170, "z": 163})) is False   # off the box
    assert env.hospital_ground(L.table_from({"x": 109, "y": 170, "z": 150})) is False   # another level
    assert W.finds == f0
    assert env.hospital_ground(L.table_from({"x": 104, "y": 166, "z": 163})) is True    # the corner
    assert W.finds == f0 + 1


@test("V6 hospital_boxes: a cache left by the old code (zone objects under `zones`) is not used")
def _():
    L, W = hospital_world()
    env = W.env
    env.hospital_boxes()                                    # (a cache's tick: the fake's own clock)
    L.execute("""local W = ...
      W.zone.freed = true
      W.env.HOSPITAL_CACHE = {at = W.env.HOSPITAL_CACHE.at, set = {}, zones = {W.zone}}""", W)
    assert env.hospital_ground(L.table_from({"x": 109, "y": 170, "z": 163})) is False
    assert W.freed_reads == 0


# --- V4: the mood's slaughter ----------------------------------------------------------------------

def pick_env():
    L = _lua()
    src = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    m = re.search(r"^function slaughter_pick_mood\(.*?^end\n", src, re.S | re.M)
    assert m
    L.execute(m.group(0))
    return L


def tbl(L, rows):
    return L.table_from([L.table_from(r) for r in rows])


def pick(L, animals, mates=None):
    r = L.globals().slaughter_pick_mood(tbl(L, animals), tbl(L, mates) if mates is not None else None)
    p, race, n = r if isinstance(r, tuple) else (r, None, None)
    return (dict(p) if p is not None else None), race, n


def cow(i, male, adult, born=None, **kw):
    d = {"id": i, "race": "COW", "male": male, "adult": adult, "born": born if born is not None else 100 + i}
    d.update(kw)
    return d


@test("V4 slaughter_pick_mood: 1 adult bull + 4 heifer calves: a calf goes, never the bull")
def _():
    L = pick_env()
    herd = [cow(1, True, True, 10)] + [cow(2 + i, False, False, 500 + i) for i in range(4)]
    p, race, n = pick(L, herd)
    assert p and race == "COW" and p["id"] in (2, 3, 4, 5), p
    assert p["id"] == 2                                     # the oldest calf


@test("V4 slaughter_pick_mood: the only male, a bull calf, is kept while the kind has cows")
def _():
    L = pick_env()
    herd = [cow(1, False, True, 10), cow(2, False, True, 11), cow(3, False, True, 12), cow(4, True, False, 600)]
    p, _, _ = pick(L, herd)
    assert p and p["id"] != 4, p
    assert p["id"] == 1                                     # adults first, the oldest


@test("V4 slaughter_pick_mood: the only female, a heifer calf, is kept while the kind has bulls")
def _():
    L = pick_env()
    herd = [cow(1, True, True, 10), cow(2, True, True, 11), cow(3, False, False, 600)]
    p, _, _ = pick(L, herd)
    assert p and p["id"] in (1, 2), p


@test("V4 slaughter_pick_mood: a kind of one pair only (any age) is never taken; none at all: nil")
def _():
    L = pick_env()
    assert pick(L, [cow(1, True, True), cow(2, False, False)])[0] is None
    assert pick(L, [cow(1, True, False), cow(2, False, True)])[0] is None
    # another kind with spare animals: that one
    goats = [{"id": 10 + i, "race": "GOAT", "male": False, "adult": True, "born": 50 + i} for i in range(3)]
    p, race, _ = pick(L, [cow(1, True, True), cow(2, False, False)] + goats)
    assert race == "GOAT" and p["id"] == 10, (race, p)


@test("V4 slaughter_pick_mood: one sex only (no pair to keep): any may go, adults and the oldest first")
def _():
    L = pick_env()
    p, _, _ = pick(L, [cow(1, True, True, 30), cow(2, True, True, 20), cow(3, True, False, 5)])
    assert p["id"] == 2, p


@test("V4 slaughter_pick_mood: an adult pair breeding now is kept before a young one goes")
def _():
    L = pick_env()
    # 1 adult bull, 1 adult cow, a bull calf and 2 heifers: neither adult is the last of its sex
    # (the calves count), but taking one stops the breeding until the calves grow up
    herd = [cow(1, True, True, 10), cow(2, False, True, 11), cow(3, True, False, 500),
            cow(4, False, False, 501), cow(5, False, False, 502)]
    p, _, _ = pick(L, herd)
    assert p["id"] in (3, 4, 5), p
    assert p["id"] == 3, p                                  # the oldest calf (another bull calf? none: still fine)
    # two adult pairs: an adult goes (more bone), a pair is left
    herd2 = [cow(1, True, True, 10), cow(2, False, True, 11), cow(6, True, True, 12), cow(7, False, True, 13),
             cow(3, True, False, 500)]
    p2, _, _ = pick(L, herd2)
    assert p2["id"] == 1, p2


@test("V4 slaughter_pick_mood: a pet or war bull still breeds: it counts as a mate (the herd bull may go)")
def _():
    L = pick_env()
    herd = [cow(1, True, True, 10)] + [cow(2 + i, False, False, 500 + i) for i in range(3)]
    assert pick(L, herd)[0]["id"] != 1
    p, _, _ = pick(L, herd, mates=[{"race": "COW", "male": True, "adult": True}])
    assert p["id"] == 1, p
    # a mate of another kind counts for nothing here
    p, _, _ = pick(L, herd, mates=[{"race": "GOAT", "male": True, "adult": True}])
    assert p["id"] != 1, p


@test("V4 slaughter_pick_mood: the AI's kept breeders only when nothing else will do, the pair rule still holds")
def _():
    L = pick_env()
    herd = [cow(1, True, True, 10, kept=True), cow(2, False, True, 11, kept=True), cow(3, False, False, 600)]
    p, _, _ = pick(L, herd)
    assert p["id"] == 3, p
    herd = [cow(1, True, True, 10, kept=True), cow(2, False, True, 11, kept=True), cow(3, False, True, 12, kept=True)]
    p, _, _ = pick(L, herd)
    assert p["id"] == 2, p                                  # a cow (two of them), never the only bull


@test("V4 slaughter_pick_mood: an animal of neither sex (female false) is no one's mate")
def _():
    L = pick_env()
    # the bull and one neuter: no female, so the bull is no last-of-a-pair
    p, _, _ = pick(L, [cow(1, True, True, 10), cow(2, False, True, 11, female=False)])
    assert p["id"] == 1, p


# --- V4 end to end: act_slaughter_one ----------------------------------------------------------------

ACT_ENV = r"""local src, units = ...
local env = setmetatable({}, {__index = _G})
env.BRIDGE_VERSION = 'test'; env.OUT_DIR = '/tmp'
env.require = function() return {} end
local list = {}
for i, u in ipairs(units) do
    u.flags1 = {caged = u.caged == true}
    u.flags2 = {slaughter = false}
    u.name = {nickname = u.nick or '', has_name = u.named == true}
    u.race = 1; u.birth_year = u.born or 0; u.birth_time = 0
    list[i] = u
end
env.UNITS = list
env.df = {global = {world = {units = {active = list}}},
          creature_raw = {find = function() return {creature_id = 'COW'} end}}
local no = function() return false end
env.dfhack = {units = {isAnimal = function() return true end, isFortControlled = function() return true end,
    isDead = no, isPet = function(u) return u.pet == true end, isWar = function(u) return u.war == true end,
    isHunter = no, isAdult = function(u) return u.adult == true end, isMale = function(u) return u.male == true end,
    isFemale = function(u) return u.male ~= true end}}
env.reqscript = function(name)
    if name == 'ai-herd' then return {kept_all = function() return {} end} end
    error('no ' .. name)
end
assert(load(src, 'ai-bridge-actions', 't', env))()
return env"""


def act(units, **a):
    L = _lua()
    env = L.execute(ACT_ENV, (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8"),
                    L.table_from([L.table_from(u) for u in units]))
    a.setdefault("mood", True)
    a.setdefault("mood_unit", 5)
    a.setdefault("dry_run", True)
    a = {k: v for k, v in a.items() if v is not None}
    return dict(env.act_slaughter_one(L.table_from(a)))


@test("V4 act_slaughter_one (mood): R-AD's herd, 1 adult bull and 4 heifer calves: a calf is marked, not the bull")
def _():
    units = [{"id": 1, "male": True, "adult": True, "born": 100}]
    units += [{"id": 2 + i, "male": False, "adult": False, "born": 110 + i} for i in range(4)]
    r = act(units)
    assert r["ok"] and r["unit_id"] in (2, 3, 4, 5) and r.get("young") is True, r


@test("V4 act_slaughter_one (mood): a pet bull counts as the herd's mate; a caged one does not")
def _():
    base = [{"id": 1, "male": True, "adult": True, "born": 100}]
    base += [{"id": 2 + i, "male": False, "adult": False, "born": 110 + i} for i in range(3)]
    r = act(base + [{"id": 9, "male": True, "adult": True, "pet": True, "born": 90}])
    assert r["ok"] and r["unit_id"] == 1, r
    r = act(base + [{"id": 9, "male": True, "adult": True, "caged": True, "born": 90}])
    assert r["ok"] and r["unit_id"] != 1, r
    r = act(base + [{"id": 9, "male": True, "adult": True, "named": True, "born": 90}])
    assert r["ok"] and r["unit_id"] == 1, r                 # a named bull is never taken, but breeds


@test("V4 act_slaughter_one (mood): a lone pair is refused with the reason; the ordinary slaughter is unchanged")
def _():
    r = act([{"id": 1, "male": True, "adult": True}, {"id": 2, "male": False, "adult": False}])
    assert r["ok"] is False and r.get("rejected") and "breeding pair" in r["error"], r
    # not for a mood: three adults or more of a kind, as before (slaughter_pick)
    units = [{"id": i, "male": i == 1, "adult": True, "born": 100 + i} for i in range(1, 5)]
    r = act(units, mood=False, mood_unit=None, oldest=True)
    assert r["ok"] and r.get("young") is None, r


if __name__ == "__main__":
    finish()
