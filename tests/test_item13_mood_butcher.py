"""(0.105.113 item13) The moods' leather, fuel and the bedridden's water: the
follow-ups of 0.105.112's mood work (fort D lost ~22 moods).

D, 24 Nov 03:27-03:47: four animals were butchered for Cog's leather mood and
each hide, tanned, went within a minute into a leather_gear order (armour, a
cap: in neither MOOD_BLOCKS nor MOOD_CONSUMERS). E: a peafowl marked for
slaughter in a pasture with no path to a butcher's shop got no job, and every
mood's slaughter_one was refused "1 animal(s) already wait for the butcher"
(79 times). D: two slaughter_one in one cycle (a mood's bone and its leather),
the second refused. D, 22-24 Nov: 19 logs, all where no dwarf walks, under the
fuel rule's 20; eight bar moods mad. B: care_feed refused every cycle,
"everybody already does this (Orderlies set to everybody)". B: the hospital's
thread part-used (97%), which the loom can't weave.

    python tests/test_item13_mood_butcher.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import bridge_part_src  # noqa: E402

import planner_moods as PM  # noqa: E402
import planner_thirst as PT  # noqa: E402
import planner_society as PS  # noqa: E402
import planner_industry_stone as PIS  # noqa: E402
from planner import Memory, PLANNER_CONFIG as CFG, abs_tick  # noqa: E402
from planner_core import Proposal  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LUA = ROOT / "lua"


def av(**kw):
    a = {"free": 0, "reach": 0, "forbidden": 0, "forbidden_reach": 0, "dump": 0, "job": 0, "other": 0,
         "held": 0, "trader": 0, "hospital": 0}
    a.update(kw)
    return a


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["orders"] = []
    s["buildings"]["workshops"].update(Butchers=1, Tanners=1)
    s["others_on_map"] = dict(s.get("others_on_map") or {}, tame_animals=8)
    s["herd"] = {"marked": 0, "marked_waiting": 0}
    s["provisions"] = {"butchery": {"butchers": 5, "tanners": 5, "hides": 0, "corpses": 0}}
    s.setdefault("supplies", {})
    return s


WHO = {"name": "Cog", "unit_id": 19100}


@test("D Cog: leather_gear's recipes (armour, cap, leggings, gloves, high boots) wait while a mood needs leather")
def _():
    for r in ("leather_armor", "leather_cap", "leather_leggings", "leather_gloves", "leather_high_boots",
              "leather_quiver", "leather_waterskin"):
        assert r in PM.MOOD_BLOCKS["leather"] and r in PM.MOOD_CONSUMERS["leather"], r
    from planner_leather import LEATHER_RECIPES
    assert set(LEATHER_RECIPES.values()) <= set(PM.MOOD_BLOCKS["leather"])
    s = fort()
    s["moods"] = {"list": [{"unit_id": 19100, "name": "Cog", "craft": True, "missing": [
        {"index": 0, "item": "SKIN_TANNED", "quantity": 1, "flags": [], "avail": av()}]}]}
    recipes, _ = PM.mood_blocked(s)
    assert "leather_armor" in recipes and "leather_cap" in recipes, recipes


@test("E: an animal already waits for the butcher (marked_waiting): no slaughter_one for the mood")
def _():
    s = fort()
    s["herd"] = {"marked": 1, "marked_waiting": 1}
    acts: list = []
    assert PM._mood_slaughter(s, Memory(), CFG, acts, "its hide", mood=WHO) is True
    assert not acts, acts
    # the marked one can't reach a butcher's (marked_waiting 0): another asked for
    s["herd"] = {"marked": 1, "marked_waiting": 0}
    acts = []
    assert PM._mood_slaughter(s, Memory(), CFG, acts, "its hide", mood=WHO) is True
    assert [a["type"] for a, _ in acts] == ["slaughter_one"], acts
    # an older bridge (no marked_waiting): every marked one counts
    s["herd"] = {"marked": 2}
    acts = []
    assert PM._mood_slaughter(s, Memory(), CFG, acts, "its hide", mood=WHO) is True and not acts


@test("an animal waits and nobody butchers: the next step, a butcher, not another animal")
def _():
    s = fort()
    s["herd"] = {"marked": 1, "marked_waiting": 1}
    s["provisions"]["butchery"]["butchers"] = 0
    acts: list = []
    PM._mood_slaughter(s, Memory(), CFG, acts, "its bones", mood=WHO)
    assert [a for a, _ in acts] == [{"type": "assign_labor", "job": "BUTCHER", "count": 1}], acts


@test("D 20:01: a mood's bone and its leather ask one animal a cycle, not two")
def _():
    s = fort()
    missing = [{"index": 0, "item": "CORPSEPIECE", "quantity": 1, "flags": ["bone"], "avail": av()},
               {"index": 1, "item": "SKIN_TANNED", "quantity": 1, "flags": [], "avail": av()}]
    props: list = []
    PM._mood_materials(s, "Cog", "Secretive", missing, 2, props, [], CFG, Memory(), 19100, 0, 100)
    n = sum(1 for p in props if p.action.get("type") == "slaughter_one")
    assert n == 1, [p.action for p in props]


@test("the mood's tan step reads the provisions' real hides (D: tan_hide orders on no hide, cancelled 9 times)")
def _():
    s = fort()
    s["supplies"]["hides"] = 6                    # skin-covered limbs and skulls: no tanner takes them
    s["provisions"]["butchery"]["hides"] = 0
    assert PM.raw_hides(s) == 0
    x = {"index": 0, "item": "SKIN_TANNED", "quantity": 1, "flags": [], "avail": av()}
    acts, _ = PM._mood_make(s, x, "leather", Memory(), CFG, mood=WHO)
    assert not any(a.get("recipe") == "tan_hide" for a, _ in acts), acts
    s["provisions"]["butchery"]["hides"] = 1
    acts, why = PM._mood_make(s, x, "leather", Memory(), CFG, mood=WHO)
    assert [a.get("recipe") for a, _ in acts] == ["tan_hide"] and why is None, (acts, why)
    del s["provisions"]
    assert PM.raw_hides(s) == 6                   # an older bridge: the supplies' count


def bar_fort(wood: int, reach: int | None) -> dict:
    s = fort()
    s["buildings"]["furnaces"] = {"Smelter": 1, "WoodFurnace": 1}
    s["supplies"]["fuel"] = 0
    if reach is not None:
        s["supplies"]["wood_reach"] = reach
    s["industry"] = {"ore_stock_by": {"LIMONITE": {"n": 5, "metals": ["IRON"]}},
                     "ores": {"IRON": {"tiles": 30, "ore": "LIMONITE"}}, "ore_stock": 45}
    s["stocks"]["wood"] = wood
    s["stone_use"] = {"economic": {}}
    return s


BAR = {"index": 0, "item": "BAR", "quantity": 1, "flags": ["metal"], "avail": av()}


@test("D: a bar mood's 19 logs all out of every dwarf's walk: no charcoal order, a reachable tree felled, said")
def _():
    s = bar_fort(19, 0)
    s["forestry"] = {"inside": {"reachable": 3, "reach_marked": 0}}
    acts, why = PM._mood_make(s, BAR, "bar", Memory(), CFG, mood=WHO)
    assert [a.get("type") for a, _ in acts] == ["cavern_logging"], (acts, why)
    assert "19 log(s) lie where no dwarf walks" in acts[0][1], acts
    s["forestry"] = {"inside": {"reachable": 0}}
    acts, why = PM._mood_make(s, BAR, "bar", Memory(), CFG, mood=WHO)
    assert not acts and "where no dwarf walks" in why and "no fuel" in why, (acts, why)
    # reachable logs: charcoal
    s = bar_fort(19, 4)
    acts, why = PM._mood_make(s, BAR, "bar", Memory(), CFG, mood=WHO)
    assert [a.get("recipe") for a, _ in acts] == ["make_charcoal"], (acts, why)


@test("the fuel rule: under 20 logs is enough while a bar mood waits (one log a charcoal), only reachable ones")
def _():
    def fuel(s):
        props: list = []
        PIS._industry_rules(s, Memory(), CFG, 30, props, [])
        return [p for p in props if p.rule == "fuel"]
    s = bar_fort(19, 19)
    assert not fuel(s)                                         # no mood: 20 asked, as before
    s["moods"] = {"list": [{"unit_id": 5, "craft": True, "missing": [BAR]}]}
    f = fuel(s)
    assert f and f[0].action == {"type": "work_order", "recipe": "make_charcoal", "amount": 10}, f
    s["supplies"]["wood_reach"] = 3
    f = fuel(s)
    assert f and f[0].action["amount"] == 3, f
    s["supplies"]["wood_reach"] = 0
    assert not fuel(s)                                         # D: none a dwarf can reach


@test("B: care_feed not proposed while the Orderlies work detail is everybody's (the bridge's refusal booked)")
def _():
    s = copy.deepcopy(BASE)
    s["society"] = dict(s.get("society") or {}, parched=2, vacant=[])
    m = Memory()

    def care(mem):
        props: list = []
        PS._society_notes(s, {}, 30, CFG, [], props, mem)
        return [p for p in props if p.rule == "care_feed"]
    assert care(m)
    p = Proposal("care_feed", {"type": "assign_labor", "job": "FEED_WATER_CIVILIANS", "count": 2}, "x", 2)
    PT.note_thirst(p, {"ok": False, "rejected": True,
                       "error": "everybody already does this (the Orderlies work detail is set to everybody)"},
                   m, abs_tick(s))
    assert PT.labor_all_done(m, "FEED_WATER_CIVILIANS", abs_tick(s))
    notes: list = []
    props: list = []
    PS._society_notes(s, {}, 30, CFG, notes, props, m)
    assert not [p for p in props if p.rule == "care_feed"], props
    assert any("everybody already brings water" in n for n in notes), notes
    # long after: asked again
    assert not PT.labor_all_done(m, "FEED_WATER_CIVILIANS", abs_tick(s) + PT.LABOR_ALL_TICKS + 1)
    assert care(None)


@test("B: the hospital's part-used thread is not set out for a loom to weave (thread_short)")
def _():
    s = fort()
    s["buildings"]["workshops"]["Loom"] = 1
    s["supplies"].update({"thread_kinds": {"plant": 0, "silk": 0, "yarn": 0},
                          "thread_short": {"plant": 0, "silk": 0, "yarn": 0},
                          "hospital": {"thread": 3, "cloth": 0,
                                       "thread_kinds": {"plant": 3, "silk": 0, "yarn": 0},
                                       "thread_short": {"plant": 3, "silk": 0, "yarn": 0},
                                       "cloth_kinds": {"plant": 0, "silk": 0, "yarn": 0}}})
    s["mood_help"] = {"cancels": []}
    x = {"index": 0, "item": "CLOTH", "quantity": 1, "flags": ["plant"], "avail": av()}
    assert PM._hospital_share(s, x, "cloth", CFG) is None
    s["supplies"]["hospital"]["thread_short"]["plant"] = 1
    assert PM._hospital_share(s, x, "cloth", CFG) == {"thread": 1}
    del s["supplies"]["hospital"]["thread_short"]          # an older bridge: as before
    assert PM._hospital_share(s, x, "cloth", CFG) == {"thread": 1}


@test("Lua: the bridge's pieces in place (reach to a butcher's, the kept list, wood_reach, thread_short)")
def _():
    herd = (LUA / "ai-herd.lua").read_text(encoding="utf-8")
    assert "function butcher_shops()" in herd and "function reaches_butcher(u, shops)" in herd
    assert "out.marked_waiting = out.marked_waiting + 1" in herd
    act = bridge_part_src("ai-bridge-actions")
    i = act.index("function act_slaughter_one")
    body = act[i:act.index("\nend\n", i)]
    assert "if reach(u) then marked = marked + 1 else stuck = stuck + 1 end" in body
    assert "if not reach(u) then return false end" in body
    assert "H.kept_save(kind, ids)" in body
    sup = (LUA / "ai-bridge-report-supplies.lua").read_text(encoding="utf-8")
    assert "out.wood_reach = n" in sup and "out.hospital.thread_short[k]" in sup


# --- Lua end to end (lupa: the PC runner) --------------------------------------------------------

ACT_ENV = r"""local src, units = ...
local env = setmetatable({}, {__index = _G})
env.BRIDGE_VERSION = 'test'; env.OUT_DIR = '/tmp'
env.require = function() return {} end
local list = {}
for i, u in ipairs(units) do
    u.flags1 = {caged = false}
    u.flags2 = {slaughter = u.marked == true}
    u.name = {nickname = '', has_name = false}
    u.race = 1; u.birth_year = u.born or 0; u.birth_time = 0
    list[i] = u
end
env.UNITS = list
env.df = {global = {world = {units = {active = list}}},
          creature_raw = {find = function() return {creature_id = 'PEAFOWL'} end}}
local no = function() return false end
env.dfhack = {units = {isAnimal = function() return true end, isFortControlled = function() return true end,
    isDead = no, isPet = no, isWar = no, isHunter = no, isAdult = function() return true end,
    isMale = function(u) return u.male == true end, isFemale = function(u) return u.male ~= true end}}
env.SAVED = {}
local kept = {breeders = {}, mousers = {}}
for _, u in ipairs(list) do if u.kept then kept.breeders[u.id] = true end end
env.reqscript = function(name)
    if name == 'ai-herd' then
        return {KEPT_KINDS = {'mousers', 'breeders'},
                kept_all = function() local o = {} for id in pairs(kept.breeders) do o[id] = true end return o end,
                kept_ids = function(k) local o = {} for id in pairs(kept[k]) do o[id] = true end return o end,
                kept_save = function(k, ids) kept[k] = ids; env.SAVED[k] = ids end,
                butcher_shops = function() return {{x = 1, y = 1, z = 1}} end,
                reaches_butcher = function(u) return u.cut_off ~= true end}
    end
    error('no ' .. name)
end
assert(load(src, 'ai-bridge-actions', 't', env))()
return env"""


def act(units, **a):
    import test_i2_thirst as I2
    I2.need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    env = L.execute(ACT_ENV, bridge_part_src("ai-bridge-actions"),
                    L.table_from([L.table_from(u) for u in units]))
    a.setdefault("mood", True)
    a.setdefault("mood_unit", 5)
    a = {k: v for k, v in a.items() if v is not None}
    return dict(env.act_slaughter_one(L.table_from(a))), env


@test("Lua E: a marked animal cut off from every butcher's blocks no other; a cut-off one is never picked")
def _():
    herd = [{"id": i, "male": i % 2 == 0, "born": 100 + i} for i in range(1, 7)]
    r, _ = act([dict(herd[0], marked=True, cut_off=True)] + herd[1:], dry_run=True)
    assert r["ok"] and r.get("stuck") == 1 and r["unit_id"] != 1, r
    r, _ = act([dict(herd[0], marked=True)] + herd[1:], dry_run=True)
    assert r["ok"] is False and r.get("waiting"), r
    r, _ = act([dict(h, cut_off=True) for h in herd[:5]] + herd[5:], dry_run=True)
    assert r.get("unit_id") in (None, 6), r


@test("Lua: a kept animal taken for a mood leaves the kept list (the herd's upkeep unmarked it each report)")
def _():
    herd = [{"id": 1, "male": True, "born": 100, "kept": True}, {"id": 2, "male": False, "born": 101, "kept": True},
            {"id": 3, "male": True, "born": 102, "kept": True}, {"id": 4, "male": False, "born": 103, "kept": True}]
    r, env = act(herd)
    assert r["ok"] and r.get("kept"), r
    saved = env.SAVED["breeders"]
    assert saved is not None and saved[r["unit_id"]] is None, r


finish()
