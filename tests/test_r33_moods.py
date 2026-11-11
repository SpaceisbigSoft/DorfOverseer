"""(0.105.33, moods) The round-33 fixes to the strange moods:

1. L6 Med ai-moods.lua free_items: never unforbids what ai-disposal's
   blocked() keeps (the cistern before the flood, a danger, a sealed cavern);
   nothing freed when those can't be read.
2. moods.md 2: suits() checks the request's material (green glass is not
   any rough gem).
3. moods.md 1: the hospital's chests are not the mood's stock ('other').
4. B4 Med planner_moods _mood_make: a THREAD request is made (plants
   processed, wool shorn and spun), not "no recipe makes it".
5. moods.md 3: a first request counted on hand that has stalled is made
   as if missing (a bone: an animal to the butcher); and cloth whose weaving
   is already on order while the mood stalls gets its thread made too.
6. B4 Lows: reserve_blocked and _drink_short_any gone; the reserve notes
   said again each season.

    python tests/test_r33_moods.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

import planner_moods  # noqa: E402
from planner import Memory, PLANNER_CONFIG as CFG, Proposal  # noqa: E402
from planner_core import mood_kind  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
FAKE = re.search(r'FAKE = r"""(.*?)"""', (ROOT / "tests" / "test_moods.py").read_text(encoding="utf-8"),
                 re.S).group(1)
STALL = CFG.get("mood_stall_days", 7)


def lua_world():
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    W = L.execute(FAKE, module_src("ai-moods.lua"))
    W.reset()
    W.env.HOSPITAL_CACHE = None
    return L, W


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["orders"] = []
    s["buildings"]["workshops"].update({"Butchers": 1, "Farmers": 1, "Loom": 1})
    s["others_on_map"]["tame_animals"] = 33
    return s


def av(**kw):
    a = {"free": 0, "reach": 0, "forbidden": 0, "forbidden_reach": 0, "dump": 0, "job": 0, "other": 0}
    a.update(kw)
    return a


def materials(s, missing, stalled):
    props, notes = [], []
    planner_moods._mood_materials(s, "Astesh", "Possessed", missing, stalled or 0, props, notes, CFG,
                                  memory=Memory(), unit_id=5, stalled=stalled)
    return props, notes


# ---- Lua ----------------------------------------------------------------------------------

@test("L6 free_items: an item ai-disposal keeps (cistern, danger, cavern) stays forbidden; the rest is freed")
def _():
    L, W = lua_world()
    env = W.env
    j = W.job(L.table_from([L.table_from({"t": 4, "kind": "iron", "q": 2})]), L.table_from([]))
    W.unit(7, j)
    a = W.item(4, "iron", 1, L.table_from({"forbid": True}), 1)
    b = W.item(4, "iron", 2, L.table_from({"forbid": True}), 1)
    a.cistern = True
    L.execute("local W = ...; W.blocked = function(it) return it.cistern and 'cistern' or nil end", W)
    r = env.free_items(7, False, 10)
    assert r.ok and r.freed == 1 and r.kept == 1, dict(r)
    assert a.flags.forbid is True and b.flags.forbid is False
    # all of them kept: rejected, saying why
    b.flags.forbid = True
    b.cistern = True
    r = env.free_items(7, False, 10)
    assert not r.ok and r.rejected and "2 cistern" in r.error, dict(r)
    assert a.flags.forbid is True and b.flags.forbid is True
    L.execute("local W = ...; W.blocked = nil", W)


@test("L6 free_items: when ai-disposal can't be read, nothing is freed")
def _():
    L, W = lua_world()
    env = W.env
    j = W.job(L.table_from([L.table_from({"t": 4, "kind": "iron", "q": 1})]), L.table_from([]))
    W.unit(7, j)
    it = W.item(4, "iron", 1, L.table_from({"forbid": True}), 1)
    L.execute("local W = ...; W.disposal.context = function() error('boom') end", W)
    r = env.free_items(7, False, 10)
    assert not r.ok and r.rejected and it.flags.forbid is True, dict(r)
    L.execute("local W = ...; W.disposal.context = function() return {} end", W)
    r = env.free_items(7, False, 10)
    assert r.ok and r.freed == 1 and it.flags.forbid is False, dict(r)


@test("moods.md 2: a request of green glass isn't met by plain rough gems (suits checks the material)")
def _():
    L, W = lua_world()
    env = W.env
    # mat_type 3 (green glass); the rough gems are inorganic (mat_type 0)
    L.execute("local W = ...; W.env.dfhack.job.isSuitableMaterial = function() return true end", W)
    j = W.job(L.table_from([L.table_from({"t": 2, "kind": 5, "q": 2, "mt": 3})]), L.table_from([]))
    u = W.unit(7, j)
    W.item(2, 5, 1, L.table_from({}), 2)
    e = env.requests_missing(j)[1]
    a = env.request_avail(j.job_items[0], e, u)
    assert a.free == 0 and a.reach == 0 and not a.enough, dict(a)
    glass = W.item(2, 5, 1, L.table_from({}), 2)
    L.execute("local g = ...; g.getMaterial = function() return 3 end", glass)
    a = env.request_avail(j.job_items[0], e, u)
    assert a.free == 2 and a.reach == 2 and a.enough, dict(a)
    # "any stone, gem or metal" (mat_type 0, no index): any inorganic still does
    j2 = W.job(L.table_from([L.table_from({"t": 2, "kind": 5, "q": 1, "mt": 0})]), L.table_from([]))
    a = env.request_avail(j2.job_items[0], env.requests_missing(j2)[1], W.unit(8, j2))
    assert a.reach >= 1, dict(a)


@test("moods.md 1: thread or cloth in the hospital's chest is 'other', not free for the mood")
def _():
    L, W = lua_world()
    env = W.env
    L.execute("""local W = ...
      local env = W.env
      local box = {id = 55, getType = function() return 'BOX' end}
      local zone = {id = 9, contained_buildings = {[0] = box}}
      local chest = {id = 900}
      W.chest = chest
      env.df.abstract_building_type = {HOSPITAL = 'HOSPITAL'}
      env.df.building_type = {BOX = 'Box'}
      env.df.building = {find = function(id) return id == 9 and zone or nil end}
      env.dfhack.world = {getCurrentSite = function()
          return {buildings = {[0] = {getType = function() return 'HOSPITAL' end,
                                      getContents = function() return {building_ids = {[0] = 9}} end}}}
      end}
      env.dfhack.items.getContainer = function(it) return it.box end
      env.dfhack.items.getHolderBuilding = function(c) return c == chest and box or nil end""", W)
    j = W.job(L.table_from([L.table_from({"t": 1, "kind": "yarn", "q": 10000})]), L.table_from([]))
    u = W.unit(7, j)
    hosp = W.item(1, "yarn", 1, L.table_from({"in_inventory": True}), 1)
    hosp.box = W.chest
    e = env.requests_missing(j)[1]
    assert env.item_standing(hosp) == "other"
    a = env.request_avail(j.job_items[0], e, u)
    assert a.free == 0 and a.reach == 0 and a.other == 1 and not a.enough, dict(a)
    W.item(1, "yarn", 1, L.table_from({}), 1)                 # one on a stockpile: free
    a = env.request_avail(j.job_items[0], e, u)
    assert a.free == 1 and a.reach == 1 and a.enough, dict(a)


@test("lua: every lua/*.lua and lua/gui/*.lua compiles under Lua 5.3")
def _():
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime()
    chk = L.eval("function(s, n) local f, e = load(s, n, 't', {}); return f ~= nil, e end")
    for p in sorted(list((ROOT / "lua").glob("*.lua")) + list((ROOT / "lua" / "gui").glob("*.lua"))):
        ok, err = chk(p.read_text(encoding="utf-8"), p.name)
        assert ok, (p.name, err)


# ---- brain --------------------------------------------------------------------------------

@test("B4 Med: a THREAD request is made: plants processed, wool shorn and spun; silk says why")
def _():
    s = fort()
    s["supplies"]["thread_plants"] = 12
    x = {"item": "THREAD", "quantity": 2, "flags": ["plant"], "avail": av()}
    assert mood_kind(x) == "other"
    acts, why = planner_moods._mood_make(s, x, mood_kind(x), Memory(), CFG)
    assert why is None and [a["recipe"] for a, _ in acts] == ["process_plants"], (acts, why)
    s["supplies"]["shearable"] = 4
    y = dict(x, flags=["yarn"])
    acts, why = planner_moods._mood_make(s, y, "other", Memory(), CFG)
    assert why is None and [a["recipe"] for a, _ in acts] == ["shear_creature", "spin_thread"], (acts, why)
    z = dict(x, flags=["silk"])
    acts, why = planner_moods._mood_make(s, z, "other", Memory(), CFG)
    assert acts == [] and "silk" in why and "no recipe" not in why, (acts, why)
    s["supplies"]["thread_plants"] = 0
    acts, why = planner_moods._mood_make(s, x, "other", Memory(), CFG)
    assert acts == [] and "fibre plant" in why, (acts, why)


@test("moods.md 3: a bone counted on hand that has stalled sends an animal to the butcher (B Astesh)")
def _():
    s = fort()
    bone = {"index": 0, "item": "NONE", "quantity": 1, "flags": ["bone"], "avail": av(free=1, reach=1, enough=True)}
    props, notes = materials(s, [bone], 2)
    assert not any(p.action.get("type") == "slaughter_one" for p in props), [p.action for p in props]
    props, notes = materials(s, [bone], STALL + 3)
    sl = [p for p in props if p.action.get("type") == "slaughter_one"]
    assert len(sl) == 1 and sl[0].action.get("mood_unit") == 5, [p.action for p in props]
    assert "nothing was fetched" in sl[0].reason, sl[0].reason
    assert not any("can't supply" in n for n in notes), notes
    # only the first request: an on-hand second one is left to the dwarf
    other = {"index": 1, "item": "BAR", "quantity": 1, "flags": [], "avail": av(free=1, reach=1, enough=True)}
    stone = {"index": 0, "item": "BOULDER", "quantity": 1, "flags": [], "avail": av(free=3, reach=3, enough=True)}
    props, _ = materials(s, [stone, dict(bone, index=1), other], STALL + 3)
    assert not any(p.action.get("type") == "slaughter_one" for p in props), [p.action for p in props]


@test("moods.md 1/3: yarn cloth whose weaving is on order while the mood stalls gets wool shorn too (C Stakud)")
def _():
    s = fort()
    s["supplies"]["thread_kinds"] = {"plant": 0, "silk": 0, "yarn": 5}
    s["supplies"]["shearable"] = 6
    s["orders"] = [{"id": 816, "recipe": "weave_yarn_cloth", "amount_left": 1, "by_ai": True}]
    cloth = {"index": 0, "item": "CLOTH", "quantity": 2, "flags": ["yarn"], "avail": av()}
    acts, why = planner_moods._mood_make(s, cloth, "cloth", Memory(), CFG, mood={"stalled": 1})
    assert acts == [] and why is None, (acts, why)                  # not stalled: wait for the weaving
    acts, why = planner_moods._mood_make(s, cloth, "cloth", Memory(), CFG, mood={"stalled": STALL})
    assert [a["recipe"] for a, _ in acts] == ["shear_creature", "spin_thread"] and why is None, (acts, why)
    s["supplies"]["shearable"] = 0
    acts, why = planner_moods._mood_make(s, cloth, "cloth", Memory(), CFG, mood={"stalled": STALL})
    assert acts == [] and "never woven" in why, (acts, why)


@test("B4 Low: the reserve notes are said again each season (one string no longer shared for life)")
def _():
    s = fort()
    su = s["supplies"]
    su.update({"cloth_kinds": {"plant": 0, "silk": 0, "yarn": 0}, "thread_kinds": {"plant": 0, "silk": 0, "yarn": 0},
               "thread_plants": 0})
    s["farms"] = {"crops": {}, "plot_list": []}
    m = Memory()
    cfg = dict(CFG, reserve_plant_cloth=3)

    def said():
        notes = []
        planner_moods._mood_reserve_rule(s, m, cfg, [], notes)
        return [n for n in notes if "no fibre crop, seed or plant" in n]

    if planner_moods.young_fort(s, cfg):
        s["date"]["year"] = int(s["date"]["year"]) + 5
    assert len(said()) == 1
    assert said() == []                                        # the same season: once
    s["date"]["tick"] = (int(s["date"]["tick"]) + planner_moods.TICKS_PER_YEAR // 4) % planner_moods.TICKS_PER_YEAR
    if s["date"]["tick"] < planner_moods.TICKS_PER_YEAR // 4:
        s["date"]["year"] = int(s["date"]["year"]) + 1
    assert len(said()) == 1                                    # the next season: again


@test("B4 Lows: reserve_blocked and _drink_short_any are gone; the drink check is planner_farms'")
def _():
    assert not hasattr(planner_moods, "reserve_blocked") and "reserve_blocked" not in planner_moods.__all__
    assert not hasattr(planner_moods, "_drink_short_any")
    s = fort()
    s["stocks"]["drink"] = 0
    ok, why = planner_moods._plants_spare(s, CFG, 1)
    assert not ok and why == "drink is short", (ok, why)


if __name__ == "__main__":
    finish()
