"""(0.105.46, I3) The order loop: inputs, fuel, a free workshop and a worker
checked before any order (brain/order_check.py, planner.select); no
re-order after a stuck cancel until what it lacked changes; approve_orders
only for unapproved orders, the AI's new ones approved as placed once it had
to approve; every crossbow counted. Each churn case of the 12-13 Nov run
check is a fixture here.

    python tests/test_order_loop.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish, code_has  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from planner import PLANNER_CONFIG, Memory, Proposal, record, select, abs_tick, TICKS_PER_DAY  # noqa: E402
import order_check  # noqa: E402
from order_check import order_feasible, order_needs  # noqa: E402
from planner_orders import _approve_rule  # noqa: E402
from planner_military import _ranged_squad_rule  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
TPD = TICKS_PER_DAY
CFG = dict(PLANNER_CONFIG, max_actions_per_cycle=50, max_orders_per_game_day=50)
IRON = "INORGANIC:IRON"


def fort(**over) -> dict:
    """The test fort with a forge, a mason's, bars by metal, fuel, thread and
    cloth by kind, and the order desk's workshops (all free)."""
    s = copy.deepcopy(BASE)
    s["bridge_version"] = "0.105.46"
    s["military"]["gear"] = {"on_duty": 10, "soldiers": 10, "bars": {"IRON": 40}, "all_bars": {"IRON": 40},
                             "forges": 3, "spare": {}}
    s["supplies"] = dict(s["supplies"], fuel=30, thread_plants=12,
                         thread_kinds={"plant": 10, "yarn": 5, "silk": 0},
                         cloth_kinds={"plant": 20, "yarn": 4, "silk": 0})
    s["stone_use"] = {"usable": 300}
    s["order_desk"] = {"workshops": [{"id": i, "type": t, "jobs": 1, "built": True}
                                     for i, t in enumerate(("Masons", "Carpenters", "MetalsmithsForge", "Loom",
                                                            "Clothiers", "Farmers", "Bowyers", "Mechanics",
                                                            "Craftsdwarfs"), 1)]}
    s["buildings"]["workshops"]["Bowyers"] = 1
    s["orders"] = []
    for k, v in over.items():
        s[k] = v
    return s


def wo(rule, recipe, material=None, amount=2, priority=4):
    a = {"type": "work_order", "recipe": recipe, "amount": amount}
    if material:
        a["material"] = material
    return Proposal(rule, a, "x", priority, True)


def placed(s, p, m=None):
    a, h = select([p], s, m or Memory(), CFG)
    return [q.action for q in a], h


def ai_order(oid, recipe, left, material=None, **kw):
    o = {"id": oid, "recipe": recipe, "job": "MakeHelm", "amount_left": left, "amount_total": left,
         "repeats": False, "by_ai": True, "validated": True, "active": True}
    if material:
        o["material"] = material
    o.update(kw)
    return o


# --- 1. the pre-check: one fixture a churn case -----------------------------------------------------

@test("metal_helm: no iron bars -> no helm order; with bars it goes")
def _():
    s = fort()
    s["military"]["gear"]["all_bars"] = {"IRON": 0, "COPPER": 9}
    a, h = placed(s, wo("arms", "metal_helm", IRON))
    assert not a and any("no metal_helm order" in x and "iron bars" in x for x in h), h
    a, h = placed(fort(), wo("arms", "metal_helm", IRON))
    assert a and a[0]["recipe"] == "metal_helm", h
    # a fort with no bars at all: the gear report leaves all_bars out, bars {}
    s = fort()
    s["military"]["gear"].pop("all_bars")
    s["military"]["gear"]["bars"] = {}
    a, h = placed(s, wo("arms", "metal_helm", IRON))
    assert not a, h


@test("metal gear in one metal: bars the AI's open orders claim don't count (greaves, gauntlets, shields, boots, mail)")
def _():
    s = fort()
    s["military"]["gear"]["all_bars"] = {"IRON": 4}
    s["orders"] = [ai_order(900, "metal_greaves", 2, IRON)]          # 2 greaves x 2 bars = all 4
    for r in ("metal_gauntlets", "metal_shield", "metal_high_boots", "metal_mail_shirt", "metal_helm"):
        a, h = placed(s, wo("arms", r, IRON))
        assert not a, (r, a)
        assert any("claimed by the AI's open orders" in x for x in h), h
    # a copper order isn't held by the iron the greaves claim
    s["military"]["gear"]["all_bars"]["COPPER"] = 5
    a, h = placed(s, wo("arms", "metal_helm", "INORGANIC:COPPER"))
    assert a, h


@test("one cycle: two orders on the same bars, the second is held (this cycle's orders claim too)")
def _():
    s = fort()
    s["military"]["gear"]["all_bars"] = {"IRON": 3}
    a, h = select([wo("arms", "metal_greaves", IRON, amount=1), wo("kit", "metal_mail_shirt", IRON, amount=1)],
                  s, Memory(), CFG)
    assert [x.action["recipe"] for x in a] == ["metal_greaves"], ([x.action for x in a], h)


@test("stone_blocks / stone_door: no stone the masons may use -> none; a mason's bench full -> none")
def _():
    s = fort(stone_use={"usable": 0})
    a, h = placed(s, wo("idle", "stone_blocks", amount=5))
    assert not a and any("stone the masons may use" in x for x in h), h
    s = fort()
    for w in s["order_desk"]["workshops"]:
        if w["type"] == "Masons":
            w["jobs"] = 10
    a, h = placed(s, wo("furniture", "stone_door"))
    assert not a and any("no free Masons workshop" in x for x in h), h


@test("weave_plant_cloth: no plant thread -> none; process_plants: no plants that give thread -> none")
def _():
    s = fort()
    s["supplies"]["thread_kinds"]["plant"] = 0
    a, h = placed(s, wo("cloth", "weave_plant_cloth"))
    assert not a and any("plant thread" in x for x in h), h
    s = fort()
    s["supplies"]["thread_plants"] = 0
    a, h = placed(s, wo("cloth", "process_plants"))
    assert not a and any("plants that give thread" in x for x in h), h


@test("yarn_bag: no yarn cloth -> none; metal_bolts: no bars -> none")
def _():
    s = fort()
    s["supplies"]["cloth_kinds"]["yarn"] = 0
    a, h = placed(s, wo("bags", "yarn_bag"))
    assert not a and any("yarn cloth" in x for x in h), h
    s = fort()
    s["military"]["gear"]["all_bars"] = {}
    a, h = placed(s, wo("arms", "metal_bolts", IRON))
    assert not a, h


@test("wooden_bed / wooden_crossbow / wooden_splint: no logs -> none")
def _():
    s = fort()
    s["stocks"]["wood"] = 0
    for rule, r in (("beds", "wooden_bed"), ("arms", "wooden_crossbow"), ("hospital", "wooden_splint")):
        a, h = placed(s, wo(rule, r))
        assert not a and any("logs" in x for x in h), (r, h)


@test("metal_battle_axe: no fuel and no magma forge -> none (a magma forge needs none)")
def _():
    s = fort()
    s["supplies"]["fuel"] = 0
    s["buildings"]["workshops"].pop("MagmaForge", None)
    a, h = placed(s, wo("arms", "metal_battle_axe", IRON))
    assert not a and any("charcoal or coke" in x for x in h), h
    s["buildings"]["workshops"]["MagmaForge"] = 1
    a, h = placed(s, wo("arms", "metal_battle_axe", IRON))
    assert a, h


@test("mechanisms: nobody has the MECHANIC labour (the report says 0 holders) -> none")
def _():
    s = fort()
    s["labor"] = {"waiting": [{"labor": "MECHANIC", "jobs": 3, "holders": 0, "idle": 0}]}
    a, h = placed(s, wo("mechanisms", "mechanisms"))
    assert not a and any("MECHANIC labour" in x for x in h), h
    s["labor"] = {"waiting": [{"labor": "MECHANIC", "jobs": 3, "holders": 2, "idle": 0}]}
    a, h = placed(s, wo("mechanisms", "mechanisms"))
    assert a, h


@test("unknown counts never hold: an older report without bars, desk or labour goes as before")
def _():
    s = copy.deepcopy(BASE)
    s["orders"] = []
    assert order_feasible("metal_helm", s, {"material": IRON})["ok"]
    assert order_feasible("weave_plant_cloth", s)["ok"]
    assert order_feasible("stone_blocks", s)["ok"]


@test("needs: the shop, labour, fuel and input of the churn recipes")
def _():
    n = order_needs("metal_helm", {"material": IRON})
    assert n == {"input": ("bars:IRON", 1), "fuel": True, "shop": "MetalsmithsForge", "labour": "FORGE_ARMOR"}, n
    assert order_needs("metal_greaves", {"material": IRON})["input"] == ("bars:IRON", 2)
    assert order_needs("stone_blocks")["shop"] == "Masons" and order_needs("stone_blocks")["labour"] == "MASON"
    assert order_needs("wooden_crossbow")["shop"] == "Bowyers"
    assert order_needs("mechanisms")["shop"] == "Mechanics"
    assert order_needs("make_charcoal")["fuel"] is False
    assert order_needs("brew_drink")["input"] is None


@test("the drink, food and mood rules' own orders aren't checked here")
def _():
    s = fort()
    s["stocks"]["wood"] = 0
    s["military"]["gear"]["all_bars"] = {}
    a, h = placed(s, wo("mood", "metal_helm", IRON, amount=1, priority=1))
    assert a, h


# --- 2. the memory of a stuck cancel ------------------------------------------------------------------

def cancel(s, m, oid, rule="stuck_order", stuck=None):
    a = {"type": "cancel_work_order", "order_id": oid}
    if stuck:
        a["stuck"] = stuck
    record([(Proposal(rule, a, "x", 6), {"ok": True})], s, m, CFG)


@test("a stuck cancel with no bars: no re-order until bars arrive")
def _():
    s = fort()
    s["military"]["gear"]["all_bars"] = {"IRON": 0}
    s["orders"] = [ai_order(900, "metal_helm", 3, IRON)]
    m = Memory()
    cancel(s, m, 900, stuck="metal_helm")
    rec = m.order_loop["misses"]["metal_helm|INORGANIC:IRON"]
    assert rec["missing"] == "inputs" and rec["snap"]["inputs"] == 0, rec
    s["orders"] = []
    a, h = placed(s, wo("arms", "metal_helm", IRON), m)
    assert not a, h
    # bars come: the old 28-day recipe hold (stuck_cancelled) gives way too
    assert "metal_helm" in m.stuck_cancelled
    s["military"]["gear"]["all_bars"] = {"IRON": 6}
    a, h = placed(s, wo("arms", "metal_helm", IRON), m)
    assert a, h


@test("a stuck copy cancel with nothing visibly missing: held until a real change or order_miss_days")
def _():
    s = fort()
    s["military"]["gear"]["all_bars"] = {"IRON": 8}
    s["orders"] = [ai_order(900, "metal_helm", 2, IRON), ai_order(901, "metal_helm", 2, IRON)]
    m = Memory()
    cancel(s, m, 900)                           # the copy cancel: rule stuck_order, no `stuck`
    rec = m.order_loop["misses"]["metal_helm|INORGANIC:IRON"]
    assert rec["missing"] is None and rec["snap"]["inputs"] == 8, rec
    s["orders"] = []
    a, h = placed(s, wo("arms", "metal_helm", IRON), m)
    assert not a and any("cancelled as stuck" in x for x in h), h
    s["military"]["gear"]["all_bars"] = {"IRON": 10}           # two bars more of 8: no change
    a, h = placed(s, wo("arms", "metal_helm", IRON), m)
    assert not a, h
    s["military"]["gear"]["all_bars"] = {"IRON": 12}           # half again: a change
    a, h = placed(s, wo("arms", "metal_helm", IRON), m)
    assert a, h
    s["military"]["gear"]["all_bars"] = {"IRON": 8}
    s["date"] = dict(s["date"], tick=s["date"]["tick"] + (CFG["order_miss_days"] + 1) * TPD)
    if s["date"]["tick"] >= 403200:
        s["date"] = dict(s["date"], year=s["date"]["year"] + 1, tick=s["date"]["tick"] - 403200)
    m.stuck_cancelled = {}
    a, h = placed(s, wo("arms", "metal_helm", IRON), m)
    assert a, h


@test("a stuck cancel in one metal doesn't hold the recipe in another")
def _():
    s = fort()
    s["military"]["gear"]["all_bars"] = {"IRON": 8, "COPPER": 8}
    s["orders"] = [ai_order(900, "metal_helm", 2, IRON), ai_order(901, "metal_helm", 2, "INORGANIC:COPPER")]
    m = Memory()
    cancel(s, m, 900)
    s["orders"] = [ai_order(901, "metal_helm", 2, "INORGANIC:COPPER")]
    a, h = placed(s, wo("arms", "metal_helm", "INORGANIC:COPPER"), m)
    assert a, h


@test("the report's own why (no citizen has the labour) is kept with the miss")
def _():
    s = fort()
    s["orders"] = [ai_order(900, "mechanisms", 3, jobs={"n": 1, "labor": "MECHANIC", "holders": 0,
                                                         "why": "no citizen has the labour MECHANIC"})]
    m = Memory()
    cancel(s, m, 900, stuck="mechanisms")
    rec = m.order_loop["misses"]["mechanisms|"]
    assert rec["missing"] == "labour" and "MECHANIC" in rec["what"], rec


# --- 3. approve_orders --------------------------------------------------------------------------------

def approve_props(s, m):
    props, notes = [], []
    _approve_rule(s, m, CFG, props, notes)
    return [p for p in props if p.rule == "approve_orders"], notes


@test("approve_orders: only when the report shows the AI's unapproved orders (and a fresh order list)")
def _():
    s = fort()
    now = abs_tick(s)
    m = Memory()
    s["orders"] = [ai_order(900, "metal_helm", 2, IRON)]
    m.order_watch = {"900": {"left": 2, "since": now - 10 * TPD, "by_ai": True, "what": "metal_helm"}}
    assert not approve_props(s, m)[0]
    s["orders"][0]["validated"] = False
    assert approve_props(s, m)[0]
    s["_errors"] = {"orders": "x"}
    assert not approve_props(s, m)[0]


@test("approve: once the AI approved, its new orders carry approve (placed approved); not before")
def _():
    s = fort()
    m = Memory()
    a, _ = placed(s, wo("arms", "metal_helm", IRON), m)
    assert "approve" not in a[0]
    s["orders"] = [ai_order(900, "metal_helm", 2, IRON, validated=False)]
    record([(Proposal("approve_orders", {"type": "approve_orders"}, "x", 2), {"ok": True, "approved": 1})],
           s, m, CFG)
    assert m.order_loop["approved"] == abs_tick(s) and m.order_loop["approved_ids"] == ["900"]
    s["orders"] = []
    a, _ = placed(s, wo("arms", "metal_helm", IRON), m)
    assert a[0].get("approve") is True, a


@test("approve: the very orders it approved show unapproved again soon after: no loop, a note")
def _():
    s = fort()
    now = abs_tick(s)
    m = Memory()
    s["orders"] = [ai_order(900, "metal_helm", 2, IRON, validated=False)]
    m.order_watch = {"900": {"left": 2, "since": now - 10 * TPD, "by_ai": True, "what": "metal_helm"}}
    m.order_loop = {"misses": {}, "approved": now - TPD, "approved_ids": ["900"]}
    props, notes = approve_props(s, m)
    assert not props and any("not approved again" in n for n in notes), notes
    m.order_loop["approved_ids"] = ["800"]
    assert approve_props(s, m)[0]


# --- 4. crossbows -------------------------------------------------------------------------------------

def crossbow_orders(g):
    s = fort()
    squads = [{"id": 12, "name": "The Bolts", "members": 10, "ai_uniform": "metal crossbow"}]
    props = []
    _ranged_squad_rule(s, g, squads, ["Crossbow"], CFG, props, [12])
    return [p.action for p in props if p.action.get("recipe") == "wooden_crossbow"]


@test("crossbows: a squad off duty (none on duty with one) whose crossbows lie in bins: none ordered")
def _():
    g = {"ranged_armed": 0, "spare_crossbows": 0, "bolts": 500, "crossbows_total": 10, "bars": {}}
    assert not crossbow_orders(g)
    g["crossbows_total"] = 7
    o = crossbow_orders(g)
    assert o and o[0]["amount"] == 3, o
    # an older bridge (no crossbows_total): as before
    g.pop("crossbows_total")
    assert crossbow_orders(g)


@test("crossbows: the gear report counts every crossbow (bins, put away), not only spare on the floor")
def _():
    src = (ROOT / "lua" / "ai-military-gear.lua").read_text(encoding="utf-8")
    assert "crossbows_total = 0" in src and "out.crossbows_total = (out.crossbows_total or 0) + 1" in src
    py = (ROOT / "brain" / "planner_army.py").read_text(encoding="utf-8")
    assert code_has(py, 'if int(g.get("crossbows_total") or 0) >= n:')


# --- 5. the bridge: the order's material, the labour's holders, approve on place ----------------------

try:
    from lupa.lua53 import LuaRuntime
    HAVE_LUPA = True
except ImportError:
    HAVE_LUPA = False

if HAVE_LUPA:
    LUA_DIR = ROOT / "lua"
    HARNESS = r"""
local src, lua_dir = ...
local H = {persist = {}}
local json = {decode = function() return {} end, encode = function() return 'json' end,
              encode_file = function() end, decode_file = function() error('no file') end}
local utils = {invert = function(t) local o = {}; for i, v in ipairs(t) do o[v] = i end; return o end}
-- a DF vector: 0-based, # its size, ipairs from 0
local function vec(t)
  local v = {n = #t}
  for i, x in ipairs(t) do v[i - 1] = x end
  return setmetatable(v, {__len = function(s) return s.n end})
end
H.vec = vec
local function vipairs(t)
  if getmetatable(t) and rawget(t, 'n') then
    return function(s, i) i = i + 1; if i < s.n then return i, s[i] end end, t, -1
  end
  return ipairs(t)
end
local units = {
  {id = 1, military = {squad_id = -1}, status = {labors = {[5] = true}}},
  {id = 2, military = {squad_id = 3}, status = {labors = {[5] = true}}},
  {id = 3, military = {squad_id = -1}, status = {labors = {}}},
}
local dfhack = {
  getDFPath = function() return '/df' end,
  isMapLoaded = function() return true end, isWorldLoaded = function() return true end,
  world = {isFortressMode = function() return true end},
  persistent = {getSiteData = function(k, d) local v = H.persist[k]; if v == nil then return d end; return v end,
                saveSiteData = function(k, v) H.persist[k] = v end},
  filesystem = {mkdir_recursive = function() end},
  maps = {getTileSize = function() return 120, 120, 100 end},
  matinfo = {decode = function(t, i) if t == 0 then return {getToken = function() return 'INORGANIC:IRON' end} end end},
  units = {getCitizens = function() return units end, isAdult = function() return true end},
  job = {getWorker = function() return nil end, getHolder = function() return nil end,
         getSpecificLabor = function(j) return j.labor end, getSkill = function() return -1 end},
}
local df = {global = {cur_year = 150, cur_year_tick = 1000, pause_state = true,
  world = {cur_savegame = {save_dir = 'region1'}, map = {region_z = 140},
           raws = {inorganics = {all = {}}, descriptors = {colors = {}}},
           manager_orders = {all = vec({}), manager_order_next_id = 10},
           jobs = {list = {next = nil}}},
  plotinfo = {site_id = 7, tasks = {wealth = {total = 1234}}, economic_stone = {},
              alerts = {civ_alert_idx = 0, list = {}}, manager_timer = 0}},
  unit_labor = {[5] = 'MECHANIC', [6] = 'MASON'},
  job_type = {}, workquota_frequency_type = {[0] = 'OneTime'}}
H.df, H.dfhack = df, dfhack
function H.module()
  local env = setmetatable({}, {__index = _G})
  env.dfhack, env.df, env.ipairs = dfhack, df, vipairs
  env.require = function(name) if name == 'json' then return json end if name == 'utils' then return utils end
    error('unexpected require ' .. name) end
  env.reqscript = function(name)
    if name == 'ai-status' then return {is_halted = function() return false end} end
    if name == 'workorder' then
      return {preprocess_orders = function(t) return t end, fillin_defaults = function() end,
              create_orders = function(orders)
                local mo = df.global.world.manager_orders
                local all = mo.all
                all[all.n] = {id = mo.manager_order_next_id, status = {validated = false}}
                all.n = all.n + 1
                mo.manager_order_next_id = mo.manager_order_next_id + 1
              end}
    end
    error('no ' .. name .. ' here')
  end
  env.dfhack_flags = {module = true}
  env.print = function() end
  env.CR_OK = 0
  assert(load(src, '@' .. lua_dir .. '/ai-bridge.lua', 't', env))()
  return env
end
return H
"""
    LUA = LuaRuntime(unpack_returned_tuples=True)
    H = LUA.execute(HARNESS, (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8"), str(LUA_DIR))
    ENV = H.module()

    def t(d):
        if isinstance(d, dict):
            return LUA.table_from({k: t(v) for k, v in d.items()})
        return d

    @test("bridge: a work order with approve=true is placed approved; without, left to the manager")
    def _():
        H.df["global"]["world"]["manager_orders"]["all"] = H.vec(LUA.table())
        r = ENV.act_work_order(t({"recipe": "wooden_bed", "amount": 2, "approve": True}))
        assert r["ok"] and r["approved"] is True, dict(r)
        all_ = H.df["global"]["world"]["manager_orders"]["all"]
        assert all_[0]["status"]["validated"] is True
        r = ENV.act_work_order(t({"recipe": "wooden_bed", "amount": 2}))
        assert r["ok"] and r["approved"] is None
        assert all_[1]["status"]["validated"] is False

    @test("bridge: approve_orders refuses when none of the AI's orders waits, approves only the AI's")
    def _():
        mo = H.df["global"]["world"]["manager_orders"]
        mo["all"] = H.vec(LUA.table_from([t({"id": 1, "status": t({"validated": True})}),
                                          t({"id": 2, "status": t({"validated": False})})]))
        H.persist["ai-overseer/orders"] = t({"ids": t({"1": True})})
        r = ENV.act_approve_orders(t({}))
        assert r["ok"] is False, dict(r)
        H.persist["ai-overseer/orders"] = t({"ids": t({"1": True, "2": True})})
        r = ENV.act_approve_orders(t({"dry_run": True}))
        assert r["ok"] and r["approved"] == 1 and mo["all"][1]["status"]["validated"] is False
        r = ENV.act_approve_orders(t({}))
        assert r["ok"] and r["approved"] == 1 and mo["all"][1]["status"]["validated"] is True

    @test("bridge: an AI order's waiting job says the labour and how many citizens outside squads hold it")
    def _():
        job = t({"order_id": 7, "flags": t({"suspend": False}), "labor": 5})
        job2 = t({"order_id": 8, "flags": t({"suspend": False}), "labor": 6})
        H.df["global"]["world"]["jobs"]["list"] = t({"next": t({"item": job, "next": t({"item": job2})})})
        by = ENV.order_jobs(t({"7": True, "8": True}))
        assert by[7]["labor"] == "MECHANIC" and by[7]["holders"] == 1 and by[7]["why"] is None, dict(by[7])
        assert by[8]["labor"] == "MASON" and by[8]["holders"] == 0
        assert "no citizen has the labour MASON" in by[8]["why"]

    @test("bridge: the orders report carries each order's material")
    def _():
        src = (LUA_DIR / "ai-bridge-orders.lua").read_text(encoding="utf-8")
        assert code_has(src, "if mi then e.material = mi:getToken() end")
else:
    print("(lupa missing: the bridge tests are skipped)")


@test("watch list: the 0.105.46 order-loop block is in docs/watch-in-game.md")
def _():
    txt = (ROOT / "docs" / "watch-in-game.md").read_text(encoding="utf-8")
    assert "I3" in txt and "order loop" in txt.lower()


if __name__ == "__main__":
    finish()
