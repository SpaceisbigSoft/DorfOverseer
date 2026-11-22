"""(0.105.48, K7 part b) Audit A2's order and labour findings:

1. one cut-off dwarf holds every order: the bridge's workshop reach goes by
   the citizens' walk groups, and "out of reach" alone never holds an order;
3. the stuck-order memory key: an any-stone order ("INORGANIC"), a fixed
   material (GLASS_GREEN) and a meal's (GLASS_CLEAR) book and look up the
   same key as their action; the bridge reports no material for a meal;
4. the planner places the melt order for items marked to melt;
5/10. 53.17's stone labours (STONE_CARVER, STONECUTTER, ENGRAVER): the
   order check, the dead's-work shortcut, ai-labor's job_labor for jobs with
   no skill on their type, the bridge's order jobs without getSpecificLabor;
7. the stuck rule's copies are one recipe in one material.

    python tests/test_k48_a2_orders.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish, code_has  # noqa: E402
from lua_modules_util import module_src, bridge_part_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import PLANNER_CONFIG, Memory, Proposal, record, select, abs_tick, TICKS_PER_DAY  # noqa: E402
import order_check  # noqa: E402
from order_check import order_feasible, order_needs, miss_key  # noqa: E402
from planner_orders import _stuck_orders_rule  # noqa: E402
from planner_labor import _labor_waiting_rule, DEAD_LABORS  # noqa: E402
from planner_industry import _disposal_rules  # noqa: E402
from planner_core import player_rules  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
TPD = TICKS_PER_DAY
CFG = dict(PLANNER_CONFIG, max_actions_per_cycle=50, max_orders_per_game_day=50)


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["bridge_version"] = "0.105.48"
    s["military"]["gear"] = {"on_duty": 10, "soldiers": 10, "bars": {"IRON": 40, "STEEL": 40},
                             "all_bars": {"IRON": 40, "STEEL": 40}, "forges": 3, "spare": {}}
    s["supplies"] = dict(s["supplies"], fuel=30)
    s["stone_use"] = {"usable": 300}
    s["order_desk"] = {"workshops": [{"id": i, "type": t, "jobs": 1, "built": True}
                                     for i, t in enumerate(("Masons", "Carpenters", "MetalsmithsForge",
                                                            "Craftsdwarfs", "Kitchen"), 1)]}
    s["orders"] = []
    return s


def wo(rule, recipe, material=None, amount=2):
    a = {"type": "work_order", "recipe": recipe, "amount": amount}
    if material:
        a["material"] = material
    return Proposal(rule, a, "x", 4, True)


def placed(s, p, m=None):
    a, h = select([p], s, m or Memory(), CFG)
    return [q.action for q in a], h


def ai_order(oid, recipe, left, material=None, job="ConstructBlocks"):
    o = {"id": oid, "recipe": recipe, "job": job, "amount_left": left, "amount_total": left,
         "repeats": False, "by_ai": True, "validated": True, "active": True}
    if material:
        o["material"] = material
    return o


def cancel(s, m, oid, stuck=None):
    a = {"type": "cancel_work_order", "order_id": oid}
    if stuck:
        a["stuck"] = stuck
    record([(Proposal("stuck_order", a, "x", 6), {"ok": True})], s, m, CFG)


# --- 1. one cut-off dwarf -------------------------------------------------------------------

@test("A2-1: every mason's 'out of reach' (one cut-off dwarf's view) doesn't hold the order; a full or "
      "blocked one still does")
def _():
    s = fort()
    for w in s["order_desk"]["workshops"]:
        w["unreachable"] = True
    for recipe in ("stone_blocks", "wooden_barrel", "wooden_bucket"):
        assert order_feasible(recipe, s)["ok"], (recipe, order_feasible(recipe, s))
    a, h = placed(s, wo("industry", "stone_blocks"))
    assert a, h
    masons = s["order_desk"]["workshops"][0]
    masons["jobs"] = 10
    chk = order_feasible("stone_blocks", s)
    assert not chk["ok"] and chk["missing"] == "workshop" and "out of reach" not in chk["what"], chk
    masons["jobs"], masons["blocked"] = 1, True
    assert not order_feasible("stone_blocks", s)["ok"]
    # a reachable one with room is still preferred in the count
    s["order_desk"]["workshops"].append({"id": 9, "type": "Masons", "jobs": 0, "built": True})
    assert order_check._free_shops("Masons", s) == 1


@test("A2-1: the bridge's workshop reach goes by the citizens' walk groups (ai-bridge-report)")
def _():
    src = bridge_part_src("ai-bridge-report")
    assert code_has(src, "function citizen_walk_groups()")
    assert code_has(src, "local groups = citizen_walk_groups()")
    assert code_has(src, "if g and groups[g] then ok = true end")


if LuaRuntime is not None:
    @test("A2-1 (lua): citizen_walk_groups is the union of the citizens' groups, group 0 left out")
    def _():
        src = bridge_part_src("ai-bridge-report")
        start = src.index("function citizen_walk_groups()")
        body = src[start:src.index("\nend\n", start) + 5]
        lua = LuaRuntime(unpack_returned_tuples=True)
        env = lua.execute(r"""
local body = ...
local env = setmetatable({}, {__index = _G})
local G = {['1,1,1'] = 4, ['2,2,2'] = 0, ['3,3,3'] = 9}
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.report_citizens = function() return {{p = {1, 1, 1}}, {p = {2, 2, 2}}, {p = {3, 3, 3}}, {}} end
env.dfhack = {units = {getPosition = function(u) if u.p then return u.p[1], u.p[2], u.p[3] end end},
              maps = {getWalkableGroup = function(p) return G[p.x .. ',' .. p.y .. ',' .. p.z] end}}
assert(load(body, 'cwg', 't', env))()
return env
""", body)
        g = env.citizen_walk_groups()
        assert sorted(g.keys()) == [4, 9], list(g.keys())


# --- 3. the stuck memory's key -------------------------------------------------------------------

@test("A2-3: miss_key keeps only a named INORGANIC: material (any stone, a fixed glass, a meal's count: none)")
def _():
    assert miss_key("stone_blocks", "INORGANIC") == miss_key("stone_blocks") == "stone_blocks|"
    assert miss_key("glass_crafts", "GLASS_GREEN") == "glass_crafts|"
    assert miss_key("prepare_lavish_meal", "GLASS_CLEAR") == "prepare_lavish_meal|"
    assert miss_key("metal_helm", "inorganic:iron") == "metal_helm|INORGANIC:IRON"
    assert miss_key("stone_blocks", "INORGANIC:GRANITE") == "stone_blocks|INORGANIC:GRANITE"


@test("A2-3: an any-stone order cancelled as stuck (the bridge says INORGANIC) holds the next stone_blocks "
      "order; glass likewise")
def _():
    s = fort()
    s["orders"] = [ai_order(900, "stone_blocks", 5, "INORGANIC")]
    m = Memory()
    cancel(s, m, 900)
    s["orders"] = []
    a, h = placed(s, wo("industry", "stone_blocks"), m)
    assert not a and any("cancelled as stuck" in x for x in h), h
    s["orders"] = [ai_order(901, "glass_crafts", 5, "GLASS_GREEN", job="MakeCrafts")]
    cancel(s, m, 901)
    s["orders"] = []
    a, h = placed(s, wo("industry", "glass_crafts"), m)
    assert not a and any("cancelled as stuck" in x for x in h), h


@test("A2-3: the bridge reports no material for a PrepareMeal order")
def _():
    src = (LUA_DIR / "ai-bridge-orders.lua").read_text(encoding="utf-8")
    assert code_has(src, "if o.mat_type ~= -1 and df.job_type[o.job_type] ~= 'PrepareMeal' then")


# --- 7. copies --------------------------------------------------------------------------------

@test("A2-7: an iron helm order and a steel one are not copies; two iron ones are")
def _():
    s = fort()
    now = abs_tick(s)
    s["orders"] = [ai_order(5, "metal_helm", 3, "INORGANIC:IRON", job="MakeHelm"),
                   ai_order(6, "metal_helm", 3, "INORGANIC:STEEL", job="MakeHelm")]
    m = Memory()
    since = now - (CFG["order_stuck_days"] + 1) * TPD
    m.order_watch = {"5": {"what": "metal_helm", "left": 3, "since": since, "by_ai": True},
                     "6": {"what": "metal_helm", "left": 3, "since": since + 1, "by_ai": True}}
    p = []
    _stuck_orders_rule(s, m, dict(CFG), p)
    assert not p, [x.reason for x in p]
    s["orders"][1]["material"] = "INORGANIC:IRON"
    p = []
    _stuck_orders_rule(s, m, dict(CFG), p)
    assert [x.action for x in p] == [{"type": "cancel_work_order", "order_id": 5}], [x.action for x in p]
    assert "metal_helm orders" in p[0].reason, p[0].reason


# --- 4. the melt order ------------------------------------------------------------------------

def disposal_state():
    s = fort()
    s.setdefault("settings", {})["disposal"] = "melt"
    s.setdefault("dead", {}).update(unburied=0, standing={"gather_refuse": 1})
    s["disposal"] = {"dump_zones": [], "dumped_items": 0, "marked_dump": 0, "marked_melt": 7, "smelters": 1,
                     "magma_smelters": 0, "sealed_caverns": False, "siege": False}
    s["others_on_map"] = {"threats": []}
    return s


def disposal(s):
    props, notes = [], []
    _disposal_rules(s, dict(PLANNER_CONFIG), props, notes, Memory(), player_rules(s))
    return {p.rule: p for p in props}


@test("A2-4: items marked to melt and no melt order: the planner orders them melted (as a work order, "
      "through the order check); none with an order, no smelter, nothing marked or at 'store'")
def _():
    s = disposal_state()
    got = disposal(s)
    assert got["disposal_melt_order"].action == {"type": "work_order", "recipe": "melt_metal", "amount": 7}, got
    s2 = copy.deepcopy(s)
    s2["disposal"]["melt_order"] = 44
    assert "disposal_melt_order" not in disposal(s2)
    s2 = copy.deepcopy(s)
    s2["orders"] = [ai_order(3, "melt_metal", 2, job="MeltMetalObject")]
    assert "disposal_melt_order" not in disposal(s2)
    s2 = copy.deepcopy(s)
    s2["disposal"]["smelters"] = 0
    assert "disposal_melt_order" not in disposal(s2)
    s2 = copy.deepcopy(s)
    s2["disposal"]["marked_melt"] = 0
    assert "disposal_melt_order" not in disposal(s2)
    s2 = copy.deepcopy(s)
    s2["settings"]["disposal"] = "store"
    assert "disposal_melt_order" not in disposal(s2)
    s["disposal"]["marked_melt"] = 90
    assert disposal(s)["disposal_melt_order"].action["amount"] == 20


@test("A2-4: the bridge's mark_melt uses DFHack's melt list and places no order itself")
def _():
    dis = (LUA_DIR / "ai-disposal.lua").read_text(encoding="utf-8")
    assert code_has(dis, "pcall(dfhack.items.markForMelting, it)")
    assert code_has(dis, "pcall(dfhack.items.cancelMelting, it)")
    acts = bridge_part_src("ai-bridge-actions")
    body = acts[acts.index("function act_mark_melt(a)"):acts.index("function act_mark_dump(a)")]
    assert "act_work_order" not in body, body


# --- 5/10. 53.17's stone labours --------------------------------------------------------------

@test("A2-5/10: the mason's labours are 53.17's (STONE_CARVER, blocks STONECUTTER); the dead's work by them")
def _():
    assert order_needs("stone_slab")["labour"] == "STONE_CARVER"
    assert order_needs("stone_coffin")["labour"] == "STONE_CARVER"
    assert order_needs("stone_blocks")["labour"] == "STONECUTTER"
    assert set(DEAD_LABORS) == {"STONE_CARVER", "ENGRAVER"}
    s = fort()
    s["labor"] = {"waiting": [{"labor": "STONE_CARVER", "jobs": 3, "holders": 0}]}
    chk = order_feasible("stone_slab", s)
    assert not chk["ok"] and chk["missing"] == "labour" and "STONE_CARVER" in chk["what"], chk
    s["labor"] = {"waiting": [{"labor": "MASON", "jobs": 3, "holders": 0}]}       # wall builders: not the slab's
    assert order_feasible("stone_slab", s)["ok"]
    props = []
    _labor_waiting_rule({"waiting": [{"labor": "ENGRAVER", "jobs": 1, "holders": 2, "idle": 0}]}, 90,
                        dict(PLANNER_CONFIG), props, False, True)
    assert props and props[0].action["job"] == "ENGRAVER", props


if LuaRuntime is not None:
    @test("A2-5 (lua): job_labor names a labour for skill-less jobs: EngraveSlab the engraver's, "
          "ConstructSlab/Coffin at the mason's the stone carver's, at the carpenter's the carpenter's")
    def _():
        lua = LuaRuntime(unpack_returned_tuples=True)
        env = lua.execute(r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local function both(t) local o = {} for k, v in pairs(t) do o[k] = v; o[v] = k end return o end
local JT = both({ConstructSlab = 1, EngraveSlab = 2, ConstructCoffin = 3, ConstructBlocks = 4, CustomReaction = 5})
JT.attrs = setmetatable({[4] = {labor = -1, skill = 7}}, {__index = function() return {labor = -1, skill = -1} end})
env.df = {job_type = JT,
          job_skill = {attrs = {[7] = {labor = 30}}},
          unit_labor = both({ENGRAVER = 10, STONE_CARVER = 11, CARPENTER = 12, STONECUTTER = 30}),
          workshop_type = both({Masons = 1, Carpenters = 2}),
          global = {world = {raws = {reactions = {reactions = {}}}}}}
env.dfhack = {job = {getHolder = function(j) return j.shop end}}
assert(load(src, 'ai-labor', 't', env))()
return env
""", module_src("ai-labor.lua"))

        def job(jt, shop=None):
            d = {"job_type": jt}
            if shop is not None:
                d["shop"] = lua.table_from({"type": shop})
            return lua.table_from(d)
        assert env.job_labor(job(2)) == 10
        assert env.job_labor(job(1, 1)) == 11 and env.job_labor(job(3, 1)) == 11
        assert env.job_labor(job(3, 2)) == 12
        assert env.job_labor(job(4, 1)) == 30                 # the job type's skill still first
        assert env.job_labor(job(1)) is None                  # no workshop: unknown


@test("A2-5: the bridge's order jobs fall back on ai-labor's job_labor (53.17 has no job.getSpecificLabor)")
def _():
    src = (LUA_DIR / "ai-bridge-orders.lua").read_text(encoding="utf-8")
    assert code_has(src, "okl, lab = pcall(function() return reqscript('ai-labor').job_labor(j) end)")


finish()
