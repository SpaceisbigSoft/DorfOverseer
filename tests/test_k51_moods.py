"""(0.105.51) Failed strange moods -> insane -> thirst (R3, 15 Nov: 14 deaths,
A 6, E 4, F 3, C 1). What the logs showed and the fixes tested here:

1. The AI's recreation burrow (taverns, halls, food piles) took five dwarves
   in strange moods; DF lets a moody dwarf claim a workshop and fetch only
   inside its burrows: all five failed. The recreation and hospital burrows
   take no dwarf in a mood, and a member who enters one is let out.
2. MOOD_WORKSHOPS: a tanner's mood claims a Leather works, a weaver's a
   Clothier's (A's Ber: four Tanner's built, no Leather works, insane).
3. A bone request counted shorn wool (E's Tobul): body-part requests matched
   by the corpse piece's own flags.
4. The mood reserves: silk and yarn apart, yarn shorn and spun, leather from
   a spare animal when no hide, raw green glass and bars by the mood's
   routes, the mood workshops kept standing; silk/yarn the fort can't make
   on the caravans' list.
5. The webs a weaver reaches: by walk group from every Loom tile.
6. No office for a dwarf in a mood (A's Urdim made militia captain).

    python tests/test_k51_moods.py
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
from lua_modules_util import module_src, bridge_part_src  # noqa: E402

import planner_core  # noqa: E402
import planner_moods  # noqa: E402
import planner_mood_help as MH  # noqa: E402
from planner import Memory, PLANNER_CONFIG as CFG  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LUA = ROOT / "lua"


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["orders"] = []
    s["others_on_map"]["tame_animals"] = 33
    s.setdefault("supplies", {})
    s["date"] = dict(s["date"], year=max(5, int(s["date"].get("year") or 0)))
    s["projects"] = {"open": []}
    return s


def reserve_fort() -> dict:
    """Every reserve met but the one a test empties (the rule takes one step a cycle)."""
    s = fort()
    s["supplies"].update({"cloth_kinds": {"plant": 9, "silk": 9, "yarn": 9},
                          "thread_kinds": {"plant": 0, "silk": 0, "yarn": 0},
                          "green_glass": 9, "hides": 0, "sand_bags": 0, "empty_bags": 0, "fuel": 9})
    s["mood_help"] = {"webs": {"reach": 0}, "cancels": []}
    return s


def run_reserve(s, memory=None, **over):
    props, notes = [], []
    cfg = dict(CFG, young_fort_days=0, **over)
    planner_moods._mood_reserve_rule(s, memory or Memory(), cfg, props, notes)
    return props, notes


def recipes(props):
    return [p.action.get("recipe") or p.action.get("type") for p in props]


# ---- 2. the mood's workshop ----------------------------------------------------------

@test("2: a tanner's mood needs a Leather works, a weaver's a Clothier's (DF's table), the stone skills mapped")
def _():
    W = planner_moods.MOOD_WORKSHOPS
    assert W["TANNER"] == "Leatherworks" and W["WEAVING"] == "Clothiers", W
    assert W["MINING"] == "Masons" and W["CUT_STONE"] == "Masons" and W["ENGRAVE_STONE"] == "Craftsdwarfs", W
    for shop in W.values():
        assert shop in planner_core.BUILDABLE_SHOPS, shop


@test("2: A's Ber (fey, TANNER, no Leather works) gets a Leather works built, not another Tanner's")
def _():
    s = fort()
    s["buildings"]["workshops"].pop("Leatherworks", None)
    s["moods"] = {"list": [{"name": "Ber", "mood": "Fey", "craft": True, "skill": "TANNER", "unit_id": 17714,
                            "items_have": 0, "items_needed": 4}]}
    props, notes = [], []
    m = Memory()
    m.moods_seen["17714"] = planner_core.abs_tick(s) - 2 * 1200
    planner_moods._mood_rules(s, m, CFG, props, notes)
    shops = [p.action.get("shops") for p in props if p.action.get("type") == "start_project"]
    assert shops == [["Leatherworks"]], (shops, notes)


# ---- 4. the reserves -----------------------------------------------------------------

@test("4: silk kept on its own: 3 yarn and no silk (E) -> webs collected for silk")
def _():
    s = reserve_fort()
    s["supplies"]["cloth_kinds"] = {"plant": 9, "silk": 0, "yarn": 3}
    s["mood_help"]["webs"]["reach"] = 40
    props, notes = run_reserve(s)
    assert "collect_webs" in recipes(props), (recipes(props), notes)
    assert "reserve_silk_cloth" in CFG and "reserve_yarn_cloth" in CFG and "reserve_animal_cloth" not in CFG


@test("4: yarn short, no yarn thread, an animal with wool grown -> shear and spin (none while the shearing fails)")
def _():
    s = reserve_fort()
    s["supplies"].update({"cloth_kinds": {"plant": 9, "silk": 9, "yarn": 0}, "shearable_ready": 2})
    props, notes = run_reserve(s)
    assert recipes(props) == ["shear_creature", "spin_thread"], (recipes(props), notes)
    s["mood_help"]["cancels"] = [{"job": "Shear animal", "why": "No creature", "n": 5}]
    props, notes = run_reserve(s)
    assert "shear_creature" not in recipes(props), recipes(props)


@test("4: leather short and no hide -> the oldest spare tame animal to the butcher; none with few animals")
def _():
    s = reserve_fort()
    s["stocks"]["leather"] = 0
    props, notes = run_reserve(s)
    sl = [p for p in props if p.action.get("type") == "slaughter_one"]
    assert sl and sl[0].rule == "mood_reserve" and sl[0].action.get("oldest") is True, (recipes(props), notes)
    s["others_on_map"]["tame_animals"] = 4
    props, notes = run_reserve(s)
    assert not [p for p in props if p.action.get("type") == "slaughter_one"], recipes(props)
    s["others_on_map"]["tame_animals"] = 33
    m = Memory()                                                 # one went lately: no other for a fortnight
    p = sl[0]
    MH.note_mood_help(p, {"ok": True}, s, m, planner_core.abs_tick(s) - 3 * 1200)
    props, notes = run_reserve(s, m)
    assert not [p for p in props if p.action.get("type") == "slaughter_one"], recipes(props)
    m.mood_help["reserve_slaughter"] = planner_core.abs_tick(s) - 20 * 1200
    props, notes = run_reserve(s, m)
    assert [p for p in props if p.action.get("type") == "slaughter_one"], recipes(props)
    s["herd"] = {"kinds": [{"name": "YAK", "n": 6, "marked": 1}]}   # one marked for the butcher now
    props, notes = run_reserve(s)
    assert not [p for p in props if p.action.get("type") == "slaughter_one"], recipes(props)
    s.pop("herd")
    s["supplies"]["hides"] = 2                                  # a hide at hand: tanned instead
    props, notes = run_reserve(s)
    assert recipes(props) == ["tan_hide"], recipes(props)


@test("4: raw green glass short -> made at the glass furnace from sand; an older bridge (no count): nothing")
def _():
    s = reserve_fort()
    s["supplies"].update({"green_glass": 0, "sand_bags": 4})
    props, notes = run_reserve(s)
    assert recipes(props) == ["raw_green_glass"], (recipes(props), notes)
    assert props[0].rule == "mood_reserve"
    del s["supplies"]["green_glass"]
    props, notes = run_reserve(s)
    assert "raw_green_glass" not in recipes(props), recipes(props)


@test("4: the mood workshops kept standing: a Tanner's and no Leather works (sand: no glass furnace) -> one level")
def _():
    s = reserve_fort()
    b = s["buildings"]
    b["workshops"].pop("Leatherworks", None)
    b["furnaces"].pop("MagmaGlassFurnace", None)
    props, notes = run_reserve(s)
    sp = [p.action for p in props if p.action.get("type") == "start_project"]
    assert sp and sp[0]["shops"] == ["Leatherworks"] and not sp[0].get("urgent"), (sp, notes)
    s["supplies"]["sand_layers"] = ["sand"]
    props, notes = run_reserve(s)
    sp = [p.action for p in props if p.action.get("type") == "start_project"]
    assert sp[0]["shops"] == ["Leatherworks", "GlassFurnace"], sp
    s["supplies"]["sand_layers"] = []
    b["workshops"].pop("Tanners")                              # no leather worked here: none
    props, notes = run_reserve(s)
    assert not [p for p in props if p.action.get("type") == "start_project"]
    b["workshops"]["Tanners"] = 1
    s["dwarves"]["total"] = 15                                  # no moods under 20
    props, notes = run_reserve(s)
    assert not [p for p in props if p.action.get("type") == "start_project"]
    s["dwarves"]["total"] = 60                                  # a workshops level under way: waits
    s["projects"] = {"open": [{"id": 3, "kind": "workshops", "phase": "dig", "summary": {"workshops": ["Kiln"]}}]}
    props, notes = run_reserve(s)
    assert not [p for p in props if p.action.get("type") == "start_project"]


@test("4: silk and yarn the fort can't make (no webs in reach, nothing to shear) go on the caravans' list")
def _():
    s = reserve_fort()
    s["supplies"]["cloth_kinds"] = {"plant": 9, "silk": 0, "yarn": 0}
    w = planner_moods.reserve_trade_wants(s, CFG)
    # (R1 g6) each fibre by its own key
    assert w == [{"key": "CLOTH:SILK", "count": 2}, {"key": "CLOTH:YARN", "count": 2}], w
    s["mood_help"]["webs"]["reach"] = 30
    s["supplies"]["shearable_ready"] = 3
    assert planner_moods.reserve_trade_wants(s, CFG) == []


@test("4: remove_webs waits on the silk reserve alone (yarn met is no silk)")
def _():
    s = reserve_fort()
    s["supplies"]["cloth_kinds"] = {"plant": 9, "silk": 0, "yarn": 9}
    assert "silk cloth" in MH.silk_wanted(s, CFG), MH.silk_wanted(s, CFG)
    s["supplies"]["cloth_kinds"]["silk"] = 9
    assert MH.silk_wanted(s, CFG) == ""


# ---- Lua -----------------------------------------------------------------------------

def lua_env(name, extra_env=""):
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    env = L.execute("""
local src, extra = ...
local env = setmetatable({df = {item_type = {}, global = {world = {items = {other = {}}, buildings = {all = {}}}},
                                items_other_id = {}, building_type = {Workshop = 1}, workshop_type = {Loom = 7}},
  dfhack = {onStateChange = {}, matinfo = {}, job = {}, maps = {}, items = {}, burrows = {}},
  SC_MAP_UNLOADED = 1, SC_WORLD_UNLOADED = 2, xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end,
  reqscript = function(n) return {} end}, {__index = _G})
if extra ~= '' then assert(load(extra, 'extra', 't', env))() end
assert(load(src, 'mod', 't', env))()
return env
""", module_src(name), extra_env)
    return L, env


@test("3: a bone request takes a corpse piece that counts as bone, not shorn wool (E's Tobul); other requests as before")
def _():
    need_lua()
    L, env = lua_env("ai-moods.lua")
    t = L.table_from
    ji = t({"flags2": t({"body_part": True, "bone": True})})
    wool = t({"corpse_flags": t({"hair_wool": True})})
    skull = t({"corpse_flags": t({"bone": True, "skull": True})})
    carcass = t({"corpse_flags": t({"bone": True, "unbutchered": True})})
    assert env.body_suits(ji, wool) is False
    assert env.body_suits(ji, skull) is True
    assert env.body_suits(ji, carcass) is False
    plain = t({"flags2": t({"bone": True})})                     # no body-part request: DFHack decides
    assert env.body_suits(plain, wool) is None
    assert env.body_suits(ji, t({})) is None                      # no corpse flags: DFHack decides


@test("5: the webs a weaver reaches: by the walk group of any Loom tile (the centre unwalkable), all webs looked at")
def _():
    need_lua()
    extra = """
dfhack.maps.getWalkableGroup = function(p)
    if p.x == 11 and p.y == 11 then return 0 end              -- the loom's frame
    if p.z == 5 then return 3 end                              -- the fort's level
    return 9                                                   -- a sealed cavern
end
local loom = {x1 = 10, x2 = 12, y1 = 10, y2 = 12, centerx = 11, centery = 11, z = 5, type = 7}
loom.getType = function() return 1 end
df.global.world.buildings.all = {loom}
local webs = {}
for i = 1, 900 do
    local w = {flags = {spider_web = true, on_ground = true}, pos = {x = 1, y = 1, z = (i <= 600) and 40 or 5}}
    table.insert(webs, w)
end
df.global.world.items.other.ANY_WEBS = webs
"""
    L, env = lua_env("ai-mood-help.lua", extra)
    r = env.webs_near()
    assert r.loose == 900 and r.looms == 1, (r.loose, r.looms)
    assert r.reach == 200, r.reach                               # (counted to WEB_REACH_ENOUGH)


@test("1: the recreation and hospital burrows take no dwarf in a mood; a recreation member in one is let out")
def _():
    need_lua()
    L, env = lua_env("ai-society-burrows.lua")
    t = L.table_from
    assert env.in_mood(t({"mood": -1})) is False
    assert env.in_mood(t({"mood": 0})) is True                     # fey
    assert env.in_mood(t({"mood": 6})) is True                     # melancholy
    src = (LUA / "ai-society-burrows.lua").read_text(encoding="utf-8")
    base = src[src.index("local function rec_base(u)"):src.index("-- (0.104.80) BeWithFriends badly unmet")]
    keep = src[src.index("local function rec_keep("):src.index("local function rec_let_out(")]
    hb = src[src.index("local function hb_eligible("):src.index("-- (0.105.33, L6) The report's sources")]
    assert "in_mood(u)" in base and "in_mood(u)" in keep and "in_mood(u)" in hb, "mood checks"


@test("6: no office for a dwarf in a mood (A's Urdim, possessed, made militia captain)")
def _():
    src = (LUA / "ai-nobles.lua").read_text(encoding="utf-8")
    body = src[src.index("local function candidates(code)"):]
    body = body[:body.index("\nend\n")]
    assert re.search(r"u\.mood", body) and "not moody" in body, "candidates skip moods"


@test("report: the bridge counts raw green glass for the reserve")
def _():
    src = bridge_part_src("ai-bridge-report")
    assert "out.green_glass" in src and "GLASS_GREEN" in src


finish()
