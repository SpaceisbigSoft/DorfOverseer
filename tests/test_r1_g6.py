"""(R1 g6) Strange moods must not fail for want of materials. The 15-16 Nov
run on 0.105.55 (run2/R-AD.md findings 1-2, R-CE.md 4, audit A3 B5): 26 dead
after failed moods (A 6, D 11, C and E 9).

1. Bone: `slaughter_one` refused 93 times in D (200+ in C and E) with "three
   of a kind, adult". For a mood any spare tame animal goes (never a pet, a
   war or hunting animal, a named or caged one, or a kind's last breeding
   pair), from one tame animal up; another after some days if it still waits.
2. Reserves: bones under 2 sends an animal (the ordinary rule); a cut gem is
   kept whenever a rough gem lies about; a jeweller's is a mood shop kept.
3. A workshop a waiting mood needs (jeweller's for a cut gem, butcher's for
   bone...) is proposed for it and takes no project slot in the builder.
4. Items on a hospital zone's floor are the hospital's, not mood stock (A's
   cloth at x109 y174 z163, zone 582 x104-112 y166-174).
5. A dwarf in a strange mood (or insane) is never drafted.
6. Silk and other fibres are bought as that fibre (CLOTH:SILK); a no-trade
   fort trades for a mood's goods only; the note says plainly when there's
   no way to get it.

    python tests/test_r1_g6.py
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
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src, bridge_part_src, split_src  # noqa: E402

import planner  # noqa: E402
import planner_moods  # noqa: E402
import planner_trade  # noqa: E402
from planner import Memory, PLANNER_CONFIG as CFG, abs_tick, plan, TICKS_PER_DAY  # noqa: E402
from planner_core import mood_kind  # noqa: E402

LUA_DIR = ROOT / "lua"
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
FAKE = re.search(r'FAKE = r"""(.*?)"""', (ROOT / "tests" / "test_moods.py").read_text(encoding="utf-8"),
                 re.S).group(1)


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["orders"] = []
    s["buildings"]["workshops"].update({"Butchers": 1, "Farmers": 1, "Loom": 1, "Tanners": 1})
    s["others_on_map"]["tame_animals"] = 20          # D at the end of the run
    s.setdefault("supplies", {})
    return s


def av(**kw):
    a = {"free": 0, "reach": 0, "forbidden": 0, "forbidden_reach": 0, "dump": 0, "job": 0, "other": 0}
    a.update(kw)
    return a


def mood(missing, **kw):
    m = {"unit_id": 5, "name": "Edëm", "mood": "Fey", "craft": True, "skill": "BONECARVE",
         "workshop": "Craftsdwarfs", "items_have": 0, "items_needed": len(missing), "missing": missing}
    m.update(kw)
    return m


def mood_props(props):
    return [p for p in props if p.rule == "mood"]


BONE = {"index": 0, "item": "NONE", "quantity": 1, "flags": ["body_part", "bone"], "avail": av()}
CUT_GEM = {"index": 0, "item": "SMALLGEM", "quantity": 1, "flags": [], "avail": av()}
SILK = {"index": 0, "item": "CLOTH", "quantity": 3, "flags": ["silk"], "avail": av()}


# ---- 1. the slaughter for a mood (lua) -------------------------------------------------------

def slaughter_env(units, kept=None):
    """ai-bridge-actions with a fake herd: units {id, race, male, adult, born, pet, named, nick, caged, war}"""
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute("""local src, rows, kept = ...
        local env = setmetatable({}, {__index = _G})
        env.BRIDGE_VERSION = 'test'; env.OUT_DIR = '/tmp'
        env.require = function() return {} end
        local UNITS = {}
        for _, r in ipairs(rows) do
            table.insert(UNITS, {id = r.id, race = r.race, birth_year = r.born or 250, birth_time = 0,
                r = r, flags1 = {caged = r.caged == true}, flags2 = {slaughter = r.marked == true},
                name = {nickname = r.nick or '', has_name = r.named == true}})
        end
        env.UNITS = UNITS
        env.df = {global = {world = {units = {active = UNITS}}},
                  creature_raw = {find = function(race) return {creature_id = race} end}}
        local no = function() return false end
        env.dfhack = {units = {isAnimal = function() return true end, isFortControlled = function() return true end,
            isDead = no, isPet = function(u) return u.r.pet == true end, isWar = function(u) return u.r.war == true end,
            isHunter = no, isAdult = function(u) return u.r.adult ~= false end,
            isMale = function(u) return u.r.male == true end}}
        env.reqscript = function(name)
            if name == 'ai-herd' then return {kept_all = function() return kept end} end
            error('no ' .. name)
        end
        assert(load(src, 'ai-bridge-actions', 't', env))()
        return env""", bridge_part_src("ai-bridge-actions"),
        lua.table_from([lua.table_from(u) for u in units]), lua.table_from(kept or {}))
    return lua, env


# D's herd at the end of the run (state-last herd.kinds): cats (pets), an alpaca
# pair and its kid, two female donkeys, a yak pair, single goose, goat, pig...
D_HERD = ([{"id": i, "race": "CAT", "male": i == 1, "pet": True} for i in range(1, 6)]
          + [{"id": 10, "race": "ALPACA", "male": True, "born": 240}, {"id": 11, "race": "ALPACA", "born": 241},
             {"id": 12, "race": "ALPACA", "male": True, "adult": False, "born": 259},
             {"id": 20, "race": "DONKEY", "born": 245}, {"id": 21, "race": "DONKEY", "born": 243},
             {"id": 30, "race": "YAK", "male": True}, {"id": 31, "race": "YAK"},
             {"id": 40, "race": "BIRD_GOOSE", "male": True, "named": True}])


@test("1 lua: D's herd (no kind with three adults): the old rule refuses; for a mood the oldest donkey goes")
def _():
    need_lua()
    lua, env = slaughter_env(D_HERD)
    r = env.act_slaughter_one(lua.table_from({"oldest": True}))           # a reserve's / the soap's: as before
    assert not r.ok and "three or more" in r.error, dict(r)
    r = env.act_slaughter_one(lua.table_from({"oldest": True, "mood": True, "mood_unit": 5, "dry_run": True}))
    assert r.ok and r.unit_id == 21 and r.race == "DONKEY", dict(r)      # an adult, not one of a pair, the oldest
    assert r.mood_unit == 5


@test("1 lua: for a mood never a pet, a named one or a kind's last breeding pair; young before nothing; kept last")
def _():
    need_lua()
    herd = [{"id": 10, "race": "ALPACA", "male": True}, {"id": 11, "race": "ALPACA"},
            {"id": 12, "race": "ALPACA", "male": True, "adult": False},
            {"id": 40, "race": "BIRD_GOOSE", "male": True, "named": True},
            {"id": 41, "race": "BIRD_GOOSE", "male": True, "nick": "Honker"},
            {"id": 50, "race": "DOG", "male": True, "war": True}, {"id": 51, "race": "CAT", "pet": True}]
    lua, env = slaughter_env(herd)
    r = env.act_slaughter_one(lua.table_from({"mood": True, "dry_run": True}))
    assert r.ok and r.unit_id == 12 and r.young, dict(r)                 # the kid: the pair stays
    herd = [h for h in herd if h["id"] != 12]
    lua, env = slaughter_env(herd)
    r = env.act_slaughter_one(lua.table_from({"mood": True, "dry_run": True}))
    assert not r.ok and "breeding pair" in r.error, dict(r)
    # a third alpaca: one of the two males may go (the pair stays); the AI's kept ones only last
    herd2 = herd + [{"id": 13, "race": "ALPACA", "male": True}]
    lua, env = slaughter_env(herd2, {10: True})
    r = env.act_slaughter_one(lua.table_from({"mood": True, "dry_run": True}))
    assert r.ok and r.unit_id == 13 and not r.kept, dict(r)
    lua, env = slaughter_env(herd2, {10: True, 13: True})
    r = env.act_slaughter_one(lua.table_from({"mood": True, "dry_run": True}))
    assert r.ok and r.unit_id in (10, 13) and r.kept, dict(r)
    r = env.act_slaughter_one(lua.table_from({"mood": True}))            # not a dry run: marked
    assert r.ok and any(u.flags2.slaughter for u in env.UNITS.values())


@test("1 brain: a mood's bone with 2 tame animals asks the bridge (was: none under 3); `mood` in the action")
def _():
    s = fort()
    s["others_on_map"]["tame_animals"] = 2
    acts, why = planner_moods._mood_make(s, dict(BONE), "bone", Memory(), CFG, mood={"name": "Edëm", "unit_id": 5})
    assert why is None and acts and acts[0][0] == {"type": "slaughter_one", "oldest": True, "mood": True,
                                                   "mood_unit": 5}, (acts, why)
    assert "last breeding pair" in acts[0][1]


@test("1 brain: one animal a mood, and another after 8 days if the bone still hasn't come (D's Uvash)")
def _():
    s = fort()
    s["moods"] = {"list": [mood([dict(BONE)])]}
    m = Memory()
    now = abs_tick(s)
    m.moods_seen = {"5": now - 10 * TICKS_PER_DAY}
    m.mood_slaughter = {"5": now - 2 * TICKS_PER_DAY}
    props, _ = plan(s, m)
    assert not [p for p in mood_props(props) if p.action.get("type") == "slaughter_one"]
    m.mood_slaughter = {"5": now - 9 * TICKS_PER_DAY}
    props, _ = plan(s, m)
    sl = [p for p in mood_props(props) if p.action.get("type") == "slaughter_one"]
    assert len(sl) == 1 and sl[0].action.get("mood") is True, [p.action for p in mood_props(props)]


# ---- 3. the workshops a mood needs -----------------------------------------------------------

@test("3 brain: a cut gem wanted, 74 rough gems and no jeweller's (A, y252): a jeweller's for the mood, past the cap")
def _():
    s = fort()
    s["buildings"]["workshops"].pop("Jewelers", None)
    s["stocks"]["rough_gems"] = 74
    s["trade"] = {"rough_gem": {"n": 74, "token": "INORGANIC:AGATE"}}
    s["moods"] = {"list": [mood([dict(CUT_GEM)], skill="CLOTHESMAKING", workshop="Clothiers", name="Dastot")]}
    m = Memory()
    m.moods_seen = {"5": abs_tick(s) - 3 * TICKS_PER_DAY}
    props, notes = plan(s, m)
    shop = [p.action for p in mood_props(props) if p.action.get("type") == "start_project"]
    assert shop == [{"type": "start_project", "kind": "workshops", "shops": ["Jewelers"], "urgent": True,
                     "mood": True, "mood_unit": 5}], [p.action for p in mood_props(props)]
    assert not any("can't supply" in n and "Dastot" in n for n in notes), notes
    # a jeweller's already being built: nothing more, no "can't supply"
    s["projects"] = {"open": [{"id": 3, "kind": "workshops", "phase": "dig", "summary": {"workshops": ["Jewelers"]}}],
                     "max_open": 2}
    props, notes = plan(s, m)
    assert not [p for p in mood_props(props) if p.action.get("type") == "start_project"]
    assert not any("can't supply" in n and "Dastot" in n for n in notes), notes


@test("3 brain: a mood workshop the fort lacks (the claim rule) carries `mood` too; the reserve's never builds one")
def _():
    s = fort()
    s["buildings"]["workshops"].pop("Jewelers", None)
    s["moods"] = {"list": [{"unit_id": 6, "name": "Såkzul", "mood": "Secretive", "craft": True, "skill": "CUTGEM"}]}
    m = Memory()
    m.moods_seen = {"6": abs_tick(s)}
    props, _ = plan(s, m)
    shop = [p.action for p in mood_props(props) if p.action.get("type") == "start_project"]
    assert shop and shop[0]["shops"] == ["Jewelers"] and shop[0]["mood"] is True, shop
    acts, _ = planner_moods._mood_make(fort(), dict(CUT_GEM), "cut_gem", None, CFG)   # no mood: no shop
    assert not [a for a, _ in acts if a.get("type") == "start_project"]


BUILDER_HARNESS = re.search(r'HARNESS = r"""(.*?)"""', (ROOT / "tests" / "test_builder.py").read_text(encoding="utf-8"),
                            re.S).group(1)


@test("3 lua: start_project: a mood's workshops level takes no slot (A: 'already N unfinished building projects' x19)")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(LUA_DIR)
    B, W = lua.execute(BUILDER_HARNESS, (LUA_DIR / "ai-layouts.lua").read_text(encoding="utf-8"),
                       (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8"))
    full = lua.eval("function(n) local t = {} for i = 1, n do t[i] = {id = i, kind = 'bedrooms', phase = 'dig'} end "
                    "return t end")(int(B.MAX_OPEN_PROJECTS) + int(B.URGENT_EXTRA) + 3)
    B.open_projects = lambda data: full

    def p(**kw):
        t = lua.table()
        for k, v in kw.items():
            t[k] = lua.table_from(v) if isinstance(v, list) else v
        return t
    r = B.start_project(p(kind="workshops", shops=["Jewelers"], urgent=True), lua.table(), True)
    assert not r.ok and "unfinished building projects" in str(r.error), dict(r)
    r = B.start_project(p(kind="workshops", shops=["Jewelers"], urgent=True, mood=True), lua.table(), True)
    assert "unfinished building projects" not in str(r.error), dict(r)
    r = B.start_project(p(kind="bedrooms", rooms=4, room_size=3, mood=True), lua.table(), True)
    assert not r.ok and "unfinished building projects" in str(r.error), dict(r)   # only a workshops level
    # never past MOOD_SHOP_OPEN_MAX urgent workshops levels (one stuck furnishing isn't "coming" to the brain)
    urgent = lua.eval("function(n) local t = {} for i = 1, n do t[i] = {id = i, kind = 'workshops', phase = 'furnish', "
                      "urgent = true} end return t end")(max(int(B.MOOD_SHOP_OPEN_MAX),
                                                           int(B.MAX_OPEN_PROJECTS) + int(B.URGENT_EXTRA) + 1))
    B.open_projects = lambda data: urgent
    r = B.start_project(p(kind="workshops", shops=["Jewelers"], urgent=True, mood=True), lua.table(), True)
    assert not r.ok and "unfinished building projects" in str(r.error), dict(r)
    # (r5 p5) the bridge's start_project run on a stand-in ai-builder (tests/bridge_behaviour.py), not its text
    import bridge_behaviour as BB
    lay = BB.real_module("ai-layouts")

    def marked(**a):
        got, _, _ = BB.forwarded("start_project", a, "ai-builder", "start_project", extra={"ai-layouts": lay})
        return got[0][1][0].get("mood")
    assert marked(kind="workshops", shops=["Jewelers"], mood=True) is True
    assert marked(kind="workshops", shops=["Jewelers"], mood="yes") is None
    assert marked(kind="bedrooms", rooms=4, room_size=3, mood=True) is None


# ---- 2. the reserves ---------------------------------------------------------------------------

def reserve(s, memory=None):
    props, notes = [], []
    planner_moods._mood_reserve_rule(s, memory or Memory(), CFG, props, notes)
    return props, notes


def reserve_fort() -> dict:
    s = fort()
    s["dwarves"]["total"] = 60
    s["others_on_map"]["tame_animals"] = 30
    s["supplies"].update({"cloth_kinds": {"plant": 9, "silk": 9, "yarn": 9}, "hides": 0, "green_glass": 9})
    s["stocks"].update({"leather": 9, "rough_gems": 3, "cut_gems": 0, "metal_bars": 9, "blocks": 9})
    s["needs"] = dict(s.get("needs") or {}, bones=9)
    s["trade"] = {"rough_gem": {"n": 3, "token": "INORGANIC:AGATE"}}
    s["buildings"]["workshops"]["Jewelers"] = 1
    return s


@test("2: no cut gem and 3 rough gems (under their own reserve of 4): one is cut all the same")
def _():
    s = reserve_fort()
    a = [p.action for p in reserve(s)[0] if p.action.get("recipe") == "cut_gems"]
    assert a == [{"type": "work_order", "recipe": "cut_gems", "amount": 1, "material": "INORGANIC:AGATE"}], a
    s["stocks"]["cut_gems"] = 1
    assert not [p for p in reserve(s)[0] if p.action.get("recipe") == "cut_gems"]


@test("2: bones under 2: one spare animal to the butcher by the ordinary rule (not the mood's); the gems still go")
def _():
    s = reserve_fort()
    s["needs"]["bones"] = 1
    props, _ = reserve(s)
    sl = [p.action for p in props if p.action.get("type") == "slaughter_one"]
    assert sl == [{"type": "slaughter_one", "oldest": True}], sl          # no `mood`: the strict rule
    assert [p for p in props if p.action.get("recipe") == "cut_gems"], [p.action for p in props]
    s["needs"]["bones"] = 2
    assert not [p for p in reserve(s)[0] if p.action.get("type") == "slaughter_one"]


@test("2: a jeweller's is a mood shop kept standing while rough gems lie about")
def _():
    s = reserve_fort()
    s["buildings"]["workshops"].pop("Jewelers")
    assert "Jewelers" in planner_moods.mood_shops_missing(s)
    s["stocks"]["rough_gems"] = 0
    assert "Jewelers" not in planner_moods.mood_shops_missing(s)


# ---- 4. the hospital's floor (lua) --------------------------------------------------------------

def moods_world():
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    W = L.execute(FAKE, module_src("ai-moods.lua"))
    W.reset()
    W.env.HOSPITAL_CACHE = None
    # A's hospital: zone 582, x104-112 y166-174 z163; the fake's items lie at (x, 1, 1)
    L.execute("""local W = ...
      local env = W.env
      local zone = {id = 582, x1 = 104, x2 = 112, y1 = 166, y2 = 174, z = 163, contained_buildings = {}}
      env.df.abstract_building_type = {HOSPITAL = 'HOSPITAL'}
      env.df.building_type = {BOX = 'Box'}
      env.df.building = {find = function(id) return id == 582 and zone or nil end}
      env.dfhack.world = {getCurrentSite = function()
          return {buildings = {[0] = {getType = function() return 'HOSPITAL' end,
                                      getContents = function() return {building_ids = {[0] = 582}} end}}}
      end}
      env.dfhack.items.getContainer = function(it) return nil end
      env.dfhack.items.getPosition = function(it) return it.x, it.y or 1, it.z or 1 end
      env.dfhack.buildings = {containsTile = function(b, x, y)
          return x >= b.x1 and x <= b.x2 and y >= b.y1 and y <= b.y2 end}
      env.dfhack.maps.canWalkBetween = function(a, b) return true end""", W)
    return L, W


@test("4 lua: A's pig tail cloth on the hospital's floor (x109 y174 z163) is 'other', not free for the mood")
def _():
    need_lua()
    L, W = moods_world()
    env = W.env
    j = W.job(L.table_from([L.table_from({"t": 1, "kind": "plant", "q": 10000})]), L.table_from([]))
    u = W.unit(17731, j)
    cloth = W.item(1, "plant", 109, L.table_from({}), 1)
    cloth.y, cloth.z = 174, 163
    e = env.requests_missing(j)[1]
    assert env.item_standing(cloth) == "hospital"      # (0.105.99) the hospital's own, counted apart
    a = env.request_avail(j.job_items[0], e, u)
    assert a.free == 0 and a.reach == 0 and a.hospital == 1 and not a.enough, dict(a)
    # the same cloth a floor down, or beside the zone: free as before
    cloth.z = 162
    assert env.item_standing(cloth) == "free"
    cloth.z, cloth.x = 163, 113
    assert env.item_standing(cloth) == "free"


@test("4 brain: so the mood's cloth is made at once (day 1), not after a 7-day stall")
def _():
    s = fort()
    s["supplies"].update(thread_kinds={"plant": 3, "silk": 0, "yarn": 0})
    x = {"index": 0, "item": "CLOTH", "quantity": 1, "flags": ["plant"], "avail": av(other=1)}
    props, notes = [], []
    planner_moods._mood_materials(s, "Udib", "Possessed", [x], 1, props, notes, CFG, memory=Memory(), unit_id=5,
                                  stalled=0)
    assert [p.action.get("recipe") for p in props] == ["weave_plant_cloth"], [p.action for p in props]


@test("4 lua: the bridge's cloth counts leave the hospital floor's cloth out of the reserves too")
def _():
    src = bridge_part_src("ai-bridge-report")
    body = src[src.index("function hospital_store_test()"):src.index("function get_supplies()")]
    assert "findCivzonesAt(xyz2pos(x, y, z))" in body and "in_inventory" in body


# ---- 5. never drafted mid-mood (lua) ------------------------------------------------------------

@test("5 lua: draftable: a dwarf in a strange mood or gone insane is never drafted (Melbil, Zas, Fikod)")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    src = split_src("ai-military.lua")   # (r8) the hub and its parts
    bd = re.search(r"\nlocal function breaking_down\(.*?\nend\n", src, re.S).group(0)
    dr = re.search(r"\nfunction draftable\(.*?\nend\n", src, re.S).group(0)
    L = LuaRuntime(unpack_returned_tuples=True)
    L.execute("""dfhack = {units = {isAdult = function() return true end, getStressCategory = function() return 4 end,
                                   getNoblePositions = function() return {} end}}
                 function wants_fight() return false end""")
    L.execute(bd + dr)
    g = L.globals()
    mk = L.eval("function(mood) return {id = 1, mood = mood, military = {squad_id = -1}, health = nil} end")
    assert g.draftable(mk(-1), L.table(), False) is True
    for m in (1, 2, 3, 6, 8):                     # Fey, Secretive, Possessed, Melancholy, Berserk
        assert g.draftable(mk(m), L.table(), False) is False, m


# ---- 6. silk bought as silk; no way said plainly -----------------------------------------------

@test("6 lua: pick_buys: a CLOTH:SILK want takes the silk, never the cheaper plant cloth; CLOTH takes any")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    src = (LUA_DIR / "ai-trade.lua").read_text(encoding="utf-8")
    body = (re.search(r"\nfunction want_matches\(.*?\nend\n", src, re.S).group(0)
            + re.search(r"\nfunction pick_buys\(.*?\nend\n", src, re.S).group(0))
    L = LuaRuntime(unpack_returned_tuples=True)
    L.execute(body)
    g = L.globals()
    c = lambda **kw: L.table_from(kw)  # noqa: E731
    cands = L.table_from([c(idx=1, cat="CLOTH", n=3, value=30, sub="plant"), c(idx=2, cat="CLOTH", n=3, value=90, sub="silk"),
                          c(idx=3, cat="THREAD", n=1, value=5, sub="silk")])
    picks, spent = g.pick_buys(cands, L.table_from([c(key="CLOTH:SILK", count=3)]), 1000)
    assert [p.idx for p in picks.values()] == [2] and spent == 90, [dict(p) for p in picks.values()]
    picks, _ = g.pick_buys(cands, L.table_from([c(key="CLOTH", count=3)]), 1000)
    assert [p.idx for p in picks.values()] == [1]
    picks, _ = g.pick_buys(cands, L.table_from([c(key="THREAD:SILK", count=1)]), 1000)
    assert [p.idx for p in picks.values()] == [3]
    assert "sub = fibre_of(item)" in src


@test("6 brain: a silk mood's want is CLOTH:SILK (was CLOTH: the merchants' cheapest cloth)")
def _():
    s = fort()
    s["moods"] = {"list": [mood([dict(SILK)], skill="WEAVING", workshop="Clothiers")]}
    assert planner_moods.mood_trade_wants(s) == [{"key": "CLOTH:SILK", "count": 3}]


@test("6 brain: a hermit fort with a caravan at the depot trades for the mood's silk only, said plainly")
def _():
    s = fort()
    s["moods"] = {"list": [mood([dict(SILK)], skill="WEAVING", workshop="Clothiers")]}
    s["trade"] = {"depot": True, "goods": 50, "caravans": [{"civ": "Kogan", "state": "AtDepot"}],
                  "trader": {"at_depot": True, "can_open": True}, "screen": {"open": True, "ready": True, "by_ai": True}}
    m = Memory()
    m.culture = {"quirks": {"hermit_kingdom": {"year": 250, "why": "test"}}}
    if not planner_moods.has_rule(m.culture, "no_trade"):
        import quirks
        q = next(k for k, v in quirks.data()["quirks"].items() if "no_trade" in (v.get("rules") or []))
        m.culture = {"quirks": {q: {"year": 250, "why": "test"}}}
    props, notes = [], []
    planner_trade._trade_rules(s, CFG, 50, props, notes, {}, m)
    deal = [p.action for p in props if p.action.get("type") == "trade_deal"]
    assert deal and deal[0]["wants"] == [{"key": "CLOTH:SILK", "count": 3}], [p.action for p in props]
    bring = [p.action for p in props if p.action.get("type") == "bring_goods"]
    assert bring and bring[0]["count"] == 10, bring
    assert any("only for what a strange mood waits for" in n for n in notes), notes
    # no mood waiting: the hermit leaves the caravan alone, as before
    s["moods"] = {"list": []}
    props, notes = [], []
    planner_trade._trade_rules(s, CFG, 50, props, notes, {}, m)
    assert not [p for p in props if p.action.get("type") in ("trade_deal", "bring_goods")], [p.action for p in props]


@test("6 brain: silk the fort can't make, no caravan on the map: the note says there is no way to get it now")
def _():
    s = fort()
    s["supplies"].update(thread_kinds={"plant": 0, "silk": 0, "yarn": 0})
    s["trade"] = {"depot": True, "caravans": []}
    props, notes = [], []
    planner_moods._mood_materials(s, "Vucar", "Fey", [dict(SILK)], 3, props, notes, CFG, memory=Memory(), unit_id=5,
                                  stalled=0)
    line = " ".join(notes)
    assert "can't supply" in line and "no caravan is on the map, so there is no way to get it now" in line.lower(), notes
    s["trade"]["caravans"] = [{"civ": "Kogan", "state": "Approaching"}]
    props, notes = [], []
    planner_moods._mood_materials(s, "Vucar", "Fey", [dict(SILK)], 3, props, notes, CFG, memory=Memory(), unit_id=5,
                                  stalled=0)
    assert "A caravan is on the map" in " ".join(notes), notes
    s.pop("trade")
    props, notes = [], []
    planner_moods._mood_materials(s, "Vucar", "Fey", [dict(SILK)], 3, props, notes, CFG, memory=Memory(), unit_id=5,
                                  stalled=0)
    assert "no trade depot" in " ".join(notes), notes


@test("checks: the request kinds seen in the run (bone, leather, bar, cut gem, rough gem, log, cloth by fibre, "
      "stone, block, green glass) each have a route or a plain reason")
def _():
    s = fort()
    s["moods"] = {"list": []}
    for x in ({"item": "NONE", "flags": ["body_part", "bone"]}, {"item": "SKIN_TANNED"}, {"item": "BAR", "flags": ["metal"]},
              {"item": "SMALLGEM"}, {"item": "ROUGH"}, {"item": "WOOD"}, {"item": "CLOTH", "flags": ["silk"]},
              {"item": "CLOTH", "flags": ["yarn"]}, {"item": "CLOTH", "flags": ["plant"]}, {"item": "BOULDER"},
              {"item": "BLOCKS"}, {"item": "ROUGH", "material": "green glass"}):
        x = dict(x, quantity=1, avail=av())
        acts, why = planner_moods._mood_make(s, x, mood_kind(x), Memory(), CFG, mood={"name": "a", "unit_id": 1})
        assert acts or why, x
        assert why != "no recipe makes it", x


if __name__ == "__main__":
    finish()
