"""(r1g8) Drink and food in a crisis, and ghosts (the 15-16 Nov run on 0.105.55).

  * the stuck-order rules never cancel (nor book, so never ban) a drink or
    meal order while drink/meals are under target or the alarm is up, and
    the alarm's days don't count as "stuck" (E y257-y259: brew orders
    cancelled 9 times, bans of 28/56/112 days, drink 1,458 -> 183);
  * the calibration never lowers the drink/meal (or farm) target over a
    window with the alarm up, dwarves thirsty or starving, or a thirst or
    hunger death (E y258: drink_per_dwarf 12 -> 6 while dwarves died);
  * brewing waiting on containers: the barrels or rock pots come first and
    from the workshop the fort has (F y250: barrels held for want of a
    Carpenters' while "no empty barrels or pots to brew into");
  * memorial slabs: a slab a Slab building already holds is not put up
    again, the walking ghost's own slab first, a spot the slab can be
    carried to, the AI's dead slab sites taken down, and a ghost with no
    slab at all gets one engraved by name (F: Udil's ghost never laid,
    place_slabs "done" 164 times);
  * the stuck sweep: a gate whose own pieces have no suspended job isn't
    nudged, and the AI's own level works aren't called "the player's";
  * a ghost laid to rest is journaled and logged as that, not as a second
    death (R-AD: 11 in B).

    python tests/test_r1_g8.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, skip  # noqa: E402
from lua_modules_util import module_src, prelude, bridge_part_src  # noqa: E402
from planner import PLANNER_CONFIG, Memory, note_cycle  # noqa: E402
from planner_core import TICKS_PER_DAY, TICKS_PER_YEAR, _stuck_again_rule, stuck_days, supply_order_kept  # noqa: E402
from planner_orders import _stuck_orders_rule  # noqa: E402
import planner_industry as PI  # noqa: E402
import planner_society as PS  # noqa: E402
import planner_stuck as PST  # noqa: E402
import calibrate  # noqa: E402
from digest import normalize  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = PLANNER_CONFIG
DAY = TICKS_PER_DAY
LUA = ROOT / "lua"


def need_lua():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    return True


# ---- (1) the stuck-order rules and the drink -----------------------------------------------

def e_state(drink=413, pop=90, alarm=True, meals=900, year=258, tick=249848):
    """E, 13 Sandstone y258 (order 1427: brew_drink, 61 left, "hasn't moved in 28 days")."""
    return {"date": {"year": year, "tick": tick}, "dwarves": {"total": pop}, "civ_alert": alarm,
            "stocks": {"drink": drink, "prepared_meals": meals},
            "orders": [{"id": 1427, "by_ai": True, "recipe": "brew_drink", "amount_left": 61, "active": True,
                        "validated": True},
                       {"id": 1430, "by_ai": True, "recipe": "prepare_lavish_meal", "amount_left": 20,
                        "active": True, "validated": True}],
            "_errors": {}}


def watch(mem, s, oid, what, days, paused_days=0):
    now = s["date"]["year"] * TICKS_PER_YEAR + s["date"]["tick"]
    mem.order_watch[str(oid)] = {"left": 61, "since": now - days * DAY, "by_ai": True, "what": what,
                                 "job": "BrewDrink" if what.startswith("brew") else "PrepareMeal",
                                 **({"paused": paused_days * DAY} if paused_days else {})}
    return now


def cancels(props):
    return [p for p in props if p.action.get("type") == "cancel_work_order"]


@test("stuck orders (E y258): a brew order 28+ days still is never cancelled under the alarm or with drink under target")
def _():
    for alarm, drink in ((True, 413), (True, 5000), (False, 413)):
        s = e_state(drink=drink, alarm=alarm)
        mem = Memory()
        watch(mem, s, 1427, "brew_drink", 29)
        props = []
        _stuck_orders_rule(s, mem, CFG, props)
        assert not cancels(props), (alarm, drink, [p.reason for p in props])
    # drink well over target, no alarm: the rule still cancels a stuck one
    s = e_state(drink=5000, alarm=False)
    mem = Memory()
    watch(mem, s, 1427, "brew_drink", 29)
    props = []
    _stuck_orders_rule(s, mem, CFG, props)
    assert [p.action["order_id"] for p in cancels(props)] == [1427], [p.reason for p in props]


@test("stuck orders (E 05:40/05:56): 'got stuck again' is not cancelled again (no 56/112-day ban) while drink is short")
def _():
    s = e_state(drink=600, pop=90, alarm=False)           # under 90 x drink_per_dwarf
    mem = Memory()
    now = watch(mem, s, 1427, "brew_drink", 29)
    mem.stuck_cancelled["brew_drink"] = {"tick": now - 30 * DAY, "n": 1}
    props = []
    _stuck_again_rule(s, mem, CFG, props)
    assert not cancels(props), [p.reason for p in props]
    # meals likewise (E 08:15: "prepare_lavish_meal ... got stuck again"), under the alarm
    s = e_state(drink=5000, alarm=True, meals=5000)
    mem = Memory()
    now = watch(mem, s, 1430, "prepare_lavish_meal", 29)
    mem.stuck_cancelled["prepare_lavish_meal"] = {"tick": now - 30 * DAY, "n": 1}
    props = []
    _stuck_again_rule(s, mem, CFG, props)
    assert not cancels(props), [p.reason for p in props]
    # and the same with plenty and no alarm: cancelled again (the rule is kept)
    s = e_state(drink=5000, alarm=False, meals=5000)
    props = []
    _stuck_again_rule(s, mem, CFG, props)
    assert [p.action.get("stuck") for p in cancels(props)] == ["prepare_lavish_meal"], [p.reason for p in props]


@test("stuck orders: the alarm's days don't count (orders_seen books them as `paused`; any order)")
def _():
    s = e_state(drink=5000, alarm=False)
    s["orders"] = [{"id": 77, "by_ai": True, "recipe": "stone_mugs", "amount_left": 10, "active": True,
                    "validated": True}]
    mem = Memory()
    watch(mem, s, 77, "stone_mugs", 40, paused_days=20)
    assert stuck_days(mem.order_watch["77"], s["date"]["year"] * TICKS_PER_YEAR + s["date"]["tick"]) == 20
    props = []
    _stuck_orders_rule(s, mem, CFG, props)
    assert not cancels(props), [p.reason for p in props]
    # note_cycle counts the alarm's time into `paused` between two reports
    base = {"date": {"year": 258, "tick": 1000}, "dwarves": {"total": 90}, "civ_alert": True,
            "stocks": {"drink": 5000}, "orders": [{"id": 5, "by_ai": True, "recipe": "stone_mugs",
                                                   "amount_left": 10}]}
    mem = Memory()
    note_cycle(copy.deepcopy(base), mem)
    later = copy.deepcopy(base)
    later["date"]["tick"] = 1000 + 30 * DAY
    note_cycle(later, mem)
    w = mem.order_watch["5"]
    assert w.get("paused") == 30 * DAY and w["since"] == 258 * TICKS_PER_YEAR + 1000, w
    calm = copy.deepcopy(later)
    calm["civ_alert"] = False
    calm["date"]["tick"] = 1000 + 40 * DAY
    note_cycle(calm, mem)
    assert mem.order_watch["5"]["paused"] == 30 * DAY, mem.order_watch["5"]


@test("supply_order_kept: drink/meal recipes only, under target or alarm; the stock unknown keeps them")
def _():
    assert supply_order_kept(e_state(drink=5000, alarm=False), "stone_mugs", CFG) is None
    assert supply_order_kept(e_state(drink=5000, alarm=False), "brew_drink", CFG) is None
    assert "under the target" in supply_order_kept(e_state(drink=100, alarm=False), "make_mead", CFG)
    assert supply_order_kept(e_state(drink=5000, alarm=True), "prepare_easy_meal", CFG) == "the alarm is up"
    s = e_state(alarm=False)
    del s["stocks"]["drink"]
    assert supply_order_kept(s, "brew_drink", CFG)


@test("stuck sweep (56 days): a brew order isn't given up under the alarm or with drink short; a craft order still is")
def _():
    YEAR = TICKS_PER_YEAR
    now = 300 * YEAR + 100 * DAY
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    base["date"] = {"year": 300, "tick": 100 * DAY, "day": 1, "month": "Granite", "season": "spring"}
    row = {"kind": "order", "id": 5, "state": "open", "progress": 3, "since": now - 60 * DAY,
           "moved": now - 60 * DAY, "left": 3, "total": 5, "what": "BrewDrink"}
    base["stuck"] = {"list": [row], "total": 1, "tick": now}
    pop = int(base["dwarves"]["total"])

    def sweep(recipe, drink, alarm):
        s = copy.deepcopy(base)
        s["orders"] = [{"id": 5, "recipe": recipe, "by_ai": True, "amount_left": 3, "validated": True}]
        s["stocks"]["drink"] = drink
        s["civ_alert"] = alarm
        props, notes = [], []
        PST._stuck_rule(normalize(s), Memory(), dict(CFG), props, notes)
        return [p.action for p in props if p.rule == PST.STUCK_RULE]
    plenty = pop * CFG["drink_per_dwarf"] * 3
    assert sweep("brew_drink", 0, False) == []
    assert sweep("brew_drink", plenty, True) == []
    assert sweep("brew_drink", plenty, False) == [{"type": "cancel_work_order", "order_id": 5, "stuck": "brew_drink"}]
    assert sweep("rock_crafts", 0, True) == [{"type": "cancel_work_order", "order_id": 5, "stuck": "rock_crafts"}]


# ---- (2) the calibration ----------------------------------------------------------------

def days(ratio=0.45, **kw):
    return [dict({"thin": False, "ratio": ratio, "alarm": False, "short": False, "deaths": 4}, **kw)
            for _ in range(10)]


@test("calibration (E 07:14-08:55): the drink target isn't lowered over a window with the alarm, deaths or thirst")
def _():
    up, why = calibrate._decide("drink_per_dwarf", days())
    assert up is False, (up, why)                        # a calm window: lowered as before
    d = days()
    d[3]["alarm"] = True
    assert calibrate._decide("drink_per_dwarf", d) == (None, "")
    d = days()
    for x in d[5:]:
        x["deaths"] = 5                                  # a thirst death in the window
    assert calibrate._decide("drink_per_dwarf", d) == (None, "")
    d = days()
    d[0]["short"] = True
    assert calibrate._decide("meals_per_dwarf", d) == (None, "")
    # the farms aren't made smaller in a pinch either
    f = [{"full": True, "thin": False, "plants_pd": 9, "idle": 40, "alarm": True, "short": False, "deaths": 0}] * 10
    assert calibrate._decide("farm_tiles_per_dwarf", f) == (None, "")


@test("calibration: the day's evidence reads the alarm, the thirsty and the death count from the report")
def _():
    s = {"date": {"year": 258, "tick": 5000}, "dwarves": {"total": 90}, "civ_alert": True,
         "stocks": {"drink": 400, "prepared_meals": 900}, "_errors": {},
         "thirst": {"deaths": 7, "thirsty": 2}, "dead": {"deaths": {"by_cause": {"HUNGER": 7}}},
         "settings": {"traits": {}}}
    ev = calibrate._observe("drink_per_dwarf", s, Memory(), CFG)
    assert ev["alarm"] is True and ev["short"] is True and ev["deaths"] == 14, ev
    # the whole update: 14+ days of E's window, drink at 37% of the target and the alarm up: no lowering
    mem = Memory()
    cfg = dict(CFG, drink_per_dwarf=12)
    t0 = 258 * TICKS_PER_YEAR
    for i in range(16):
        st_ = copy.deepcopy(s)
        st_["date"] = {"year": 258, "tick": 5000 + i * DAY, "day": 1, "month": "Slate"}
        ch = calibrate.update(st_, mem, cfg)
        assert not [c for c in ch if c["key"] == "drink_per_dwarf" and not c["up"]], ch
    del t0


@test("calibration heed: a drink raise judged 'no effect' isn't taken back while the alarm is up")
def _():
    mem = Memory()
    c = calibrate._state(mem)
    c["values"]["drink_per_dwarf"] = 8
    e = {"by": "self-tuning", "verdict": "none", "tune_key": "drink_per_dwarf", "tune_old": 6, "tune_new": 8}
    s = {"date": {"year": 259, "tick": 1, "day": 1, "month": "Granite"}, "civ_alert": True, "_errors": {}}
    assert calibrate.heed(e, mem, s) is None and c["values"]["drink_per_dwarf"] == 8
    s["civ_alert"] = False
    assert calibrate.heed(e, mem, s)["new"] == 6


# ---- (3) the barrels and pots first --------------------------------------------------------

def f_state(wood=200, boulders=80, shops=None, barrels=0, pots=0, drink=18, pop=11):
    """F, 19:11-19:16 15 Nov: drink 18 for 11, no empty barrels or pots, no Carpenters' yet."""
    return normalize({"date": {"year": 250, "tick": 300000}, "dwarves": {"total": pop},
            "stocks": {"wood": wood, "boulders": boulders, "drink": drink, "bins": 50},
            "supplies": {"empty_barrels": barrels, "empty_pots": pots, "empty_bags": 50, "brewable_plants": 30},
            "buildings": {"workshops": shops if shops is not None else {"Masons": 1, "Still": 1},
                          "furnaces": {}, "other": {}},
            "orders": [], "labor": {}})


def containers(props):
    return [p for p in props if p.rule == "containers"]


@test("containers (F y250): brewing waits on them: rock pots at the masons' when there's no Carpenters', first (priority 1)")
def _():
    s = f_state()
    props, notes = [], []
    PI._supply_rules(s, 11, CFG, props, notes, memory=Memory())
    c = containers(props)
    assert c and c[0].action["recipe"] == "stone_large_pot" and c[0].priority == 1, [(p.action, p.priority) for p in c]
    # with a Carpenters' and wood to spare: barrels, still first
    s = f_state(shops={"Masons": 1, "Carpenters": 1, "Still": 1})
    props = []
    PI._supply_rules(s, 11, CFG, props, [], memory=Memory())
    c = containers(props)
    assert c and c[0].action["recipe"] == "wooden_barrel" and c[0].priority == 1, [(p.action, p.priority) for p in c]
    # little wood or stone: what there is, not nothing
    s = f_state(wood=4, boulders=6, shops={"Masons": 1, "Carpenters": 1, "Still": 1})
    props, notes = [], []
    PI._supply_rules(s, 11, CFG, props, notes, memory=Memory())
    c = containers(props)
    assert c and c[0].action["amount"] >= CFG["r1g8_dry_containers_min"], ([p.action for p in c], notes)
    # drink at its target: as before (priority 2, the usual choice)
    s = f_state(drink=5000, shops={"Masons": 1, "Carpenters": 1, "Still": 1})
    props = []
    PI._supply_rules(s, 11, CFG, props, [], memory=Memory())
    c = containers(props)
    assert c and c[0].priority == 2, [(p.action, p.priority) for p in c]


# ---- (4) memorial slabs: lua/ai-builder-rooms.lua and lua/ai-welfare.lua -------------------

ROOMS_FAKE = r"""
local src = ...
local W = {slabs = {}, sbld = {}, units = {}, tombs = {{id = 1}}, built = {}, gone = {}, unreach = {}, spots = {}}
local env = setmetatable({}, {__index = _G})
env.require = function(n) error('no ' .. tostring(n)) end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.info, env.has = function() return nil end, function() return false end
env.ez = function(z) return z - 130 end
env.elevation_offset = function() return 0 end
env.item_held = function(it) return it.flags.forbid == true end
env.df = {
    global = {plotinfo = {race_id = 1, civ_id = 10},
              world = {units = {active = W.units}, items = {other = {SLAB = W.slabs}},
                       buildings = {other = {SLAB = W.sbld, ZONE_TOMB = W.tombs, ZONE_MEETING_HALL = {},
                                             ZONE_DINING_HALL = {}}}}},
    slab_engraving_type = {Memorial = 'Memorial'},
    building_type = {Slab = 'Slab'},
}
local function key(p) return p.x .. ',' .. p.y .. ',' .. p.z end
env.dfhack = {
    units = {isGhost = function(u) return u.ghost == true end},
    items = {getHolderBuilding = function(it) return it.holder end,
             getPosition = function(it) return it.pos.x, it.pos.y, it.pos.z end},
    maps = {canWalkBetween = function(a, b) return not W.unreach[key(b)] end},
    buildings = {
        constructBuilding = function(t)
            local it = t.items[1]
            it.flags.in_job = true
            table.insert(W.built, {x = t.pos.x, y = t.pos.y, z = t.pos.z, slab = it.id})
            return {id = 900 + #W.built}
        end,
        deconstruct = function(b) table.insert(W.gone, b.id) return true end,
    },
}
assert(load(src, 'ai-builder-rooms', 't', env))()
env.zone_area = function(id) return {x1 = 0, y1 = 0, x2 = 9, y2 = 9, z = 170, has = function() return true end} end
env.zone_spots = function(area)            -- (as the game's: a tile with a building on it is no spot)
    local out = {}
    for _, sp in ipairs(W.spots) do
        local taken = false
        for _, b in ipairs(W.built) do taken = taken or (b.x == sp.x and b.y == sp.y) end
        if not taken then table.insert(out, sp) end
    end
    return out
end
function W.slab(id, topic, x, y, z, flags)
    local it = {id = id, topic = topic, engraving_type = 'Memorial', flags = flags or {}, pos = {x = x, y = y, z = z}}
    table.insert(W.slabs, it)
    return it
end
function W.site(id, item_ids, stage, asks)
    local ci = {}
    for _, iid in ipairs(item_ids or {}) do table.insert(ci, {item = {id = iid}}) end
    local b = {id = id, contained_items = ci,
               jobs = {{items = {}, job_items = {elements = asks and {{}} or {}}}}}
    function b:getBuildStage() return stage or 0 end
    table.insert(W.sbld, b)
    return b
end
return env, W
"""


def rooms_world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    src = (LUA / "ai-builder-rooms.lua").read_text(encoding="utf-8")
    env, w = lua.execute(ROOMS_FAKE, src)
    return lua, env, w


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


def py(v):
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    try:
        keys = list(v.keys())
    except AttributeError:
        return v
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in sorted(keys)]
    return {k: py(v[k]) for k in keys}


UDIL_HF = 41276        # F's ghost (state-last dead.ghost_list)


@test("memorial_slabs (F): a slab a Slab building already holds isn't counted again; the walking ghost's own first")
def _():
    if not need_lua():
        return
    lua, env, w = rooms_world()
    w.units[1] = T(lua, {"ghost": True, "race": 1, "civ_id": 10, "hist_figure_id": UDIL_HF})
    w.slab(11, 700, 100, 150, 167)                       # another dead's memorial, loose
    w.slab(12, UDIL_HF, 101, 150, 167)                   # Udil's, loose
    w.slab(13, 701, 102, 150, 167)                       # held by a planned Slab building (not in_job)
    w.slab(14, 702, 103, 150, 167, T(lua, {"in_building": True}))
    w.site(500, T(lua, [13]))
    got = [it["id"] for it in py(env.memorial_slabs())]
    assert got == [12, 11], got
    waiting, none = env.ghost_slab_counts()
    assert (waiting, none) == (1, 0), (waiting, none)


@test("place_slabs (F): the ghost's slab put up first at a spot it can be carried to; the AI's dead slab sites taken down")
def _():
    if not need_lua():
        return
    lua, env, w = rooms_world()
    w.units[1] = T(lua, {"ghost": True, "race": 1, "civ_id": 10, "hist_figure_id": UDIL_HF})
    w.slab(11, 700, 100, 150, 167)
    w.slab(12, UDIL_HF, 101, 150, 167)
    # F's spots: one behind the floor-2 wall (x113 y148, out of the slab's walk), one in reach
    w.spots[1] = T(lua, {"x": 113, "y": 148})
    w.spots[2] = T(lua, {"x": 105, "y": 152})
    w.spots[3] = T(lua, {"x": 104, "y": 153})
    w.unreach["113,148,170"] = True
    w.site(600, T(lua, []), 0, False)                            # a dead site: holds nothing, asks nothing
    w.site(601, T(lua, []), 0, True)                             # a plan that asks by filter (buildingplan): kept
    w.site(602, T(lua, []), 1, False)                            # built: kept
    r = py(env.place_slabs(1, False))
    assert r["ok"] and r["for_ghosts"] == 1 and r["placed"][0]["hf"] == UDIL_HF, r
    assert (r["placed"][0]["x"], r["placed"][0]["y"]) == (105, 152), r
    assert py(w.gone) == [600], py(w.gone)
    assert py(w.built) == [{"x": 105, "y": 152, "z": 170, "slab": 12}], py(w.built)
    # the next call: Udil's slab is on its job now, the other's goes up at the next free spot
    r = py(env.place_slabs(5, False))
    assert r["ok"] and r["for_ghosts"] == 0 and [p["hf"] for p in r["placed"]] == [700], r
    assert (r["placed"][0]["x"], r["placed"][0]["y"]) == (104, 153), r
    # nothing left: refused, not "done" again (F: 164 times)
    r = py(env.place_slabs(5, False))
    assert r["ok"] is False and r["rejected"], r


@test("place_slabs: no spot the slab can be carried to is a refusal that says so (never a building no dwarf can reach)")
def _():
    if not need_lua():
        return
    lua, env, w = rooms_world()
    w.slab(12, UDIL_HF, 101, 150, 167)
    w.spots[1] = T(lua, {"x": 113, "y": 148})
    w.unreach["113,148,170"] = True
    r = py(env.place_slabs(1, False))
    assert r["ok"] is False and r["rejected"] and "carried" in r["error"], r
    assert not py(w.built), py(w.built)


def welfare_fake() -> str:
    text = (ROOT / "tests" / "test_r47_welfare.py").read_text(encoding="utf-8")
    m = re.search(r'FAKE = r"""(.*?)"""', text, re.S)
    return m.group(1)


@test("ai-welfare ghost_scan/engrave_memorials ghosts (F): the ghost with no memorial slab gets an approved order by name, once")
def _():
    if not need_lua():
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(welfare_fake(), module_src("ai-welfare.lua"))
    w.citizen(T(lua, {"id": 1, "nm": "Alive"}))
    w.citizen(T(lua, {"id": 16787, "nm": "Udil", "dead": True, "ghost": True, "hist_figure_id": UDIL_HF}))
    w.citizen(T(lua, {"id": 20, "nm": "Laid", "dead": True, "ghost": True, "hist_figure_id": 300}))
    w.slabs[1] = T(lua, {"engraving_type": "Memorial", "topic": 300})
    # autoslab's own order for Udil (not the AI's): no reason to wait on it
    w.orders.insert(w.orders, "#", T(lua, {"id": 50, "job_type": "EngraveSlab",
                                           "specdata": {"hist_figure_id": UDIL_HF}}))
    assert [g["hf"] for g in py(env.ghost_scan())] == [UDIL_HF]
    r = py(env.engrave_memorials(5, False, True))
    assert r["ok"] and r["ordered"] == ["Udil"] and r["ghosts"], r
    o = w.orders[len(w.orders)]
    assert o.job_type == "EngraveSlab" and o.specdata.hist_figure_id == UDIL_HF and o.status.validated, o
    # its order open: not ordered again
    for i in range(len(w.orders)):
        w.orders[i + 1].id = w.orders[i + 1].id or 50
    assert not py(env.ghost_scan()), py(env.ghost_scan())
    r = py(env.engrave_memorials(5, False, True))
    assert r["ok"] is False and r["nothing_to_do"], r
    # the dead-ahead path is unchanged: never a ghost
    assert not [x for x in py(env.dead_scan())["wanted"] if x["hf"] == UDIL_HF]


def ghost_fort(**sup):
    return {"date": {"year": 251, "tick": 1000}, "dwarves": {"total": 30}, "orders": [], "_errors": {},
            "dead": {"ghosts": 1, "ghost_names": ['Udil Kobelcog "Summitboot", Ghostly Mason'], "unburied": 0,
                     "free_tombs": 3, "ghost_list": [{"hf": UDIL_HF, "kind": "RestlessHaunt", "body": "lying"}]},
            "supplies": dict({"slabs": 0, "memorial_slabs": 1}, **sup), "tools": {"autoslab": True},
            "buildings": {"workshops": {"Masons": 1}}, "stocks": {"boulders": 100}, "stone_use": {"usable": 100},
            "labor": {}, "projects": {"open": []}}


@test("the ghost rule (F): a ghost with no slab of its own gets it engraved by name; other dead's slabs said as such")
def _():
    s = ghost_fort(ghosts_no_slab=1, ghost_slabs=0)
    props, notes = [], []
    PS._dead_notes(s, notes, props, {"engrave_slabs": True}, Memory())
    g = [p for p in props if p.rule == "slabs_ghost"]
    assert g and g[0].action == {"type": "engrave_memorials", "max": 1, "ghosts": True} and g[0].priority == 2, \
        [(p.rule, p.action) for p in props]
    pl = [p for p in props if p.action.get("type") == "place_slabs"]
    assert pl and "none of them a walking ghost's" in pl[0].reason and pl[0].priority == 4, [p.reason for p in pl]
    # the ghost's own slab waits: put up at the usual priority
    s = ghost_fort(ghosts_no_slab=0, ghost_slabs=1)
    props = []
    PS._dead_notes(s, [], props, {"engrave_slabs": True}, Memory())
    assert not [p for p in props if p.rule == "slabs_ghost"]
    pl = [p for p in props if p.action.get("type") == "place_slabs"]
    assert pl and pl[0].priority == 3 and "1 of them the ghosts' own" in pl[0].reason, [p.reason for p in pl]
    # the Rules switch off: none
    props = []
    PS._dead_notes(ghost_fort(ghosts_no_slab=1), [], props, {"engrave_slabs": False}, Memory())
    assert not [p for p in props if p.rule == "slabs_ghost"]


@test("the bridge wiring: the report sends ghost_slabs and ghosts_no_slab, the action passes `ghosts`")
def _():
    rep = bridge_part_src("ai-bridge-report")
    assert "reqscript('ai-builder').ghost_slab_counts()" in rep and "reqscript('ai-welfare').ghost_scan()" in rep
    # (r5 p5) the action run on a stand-in ai-welfare (tests/bridge_behaviour.py), not the hub's text
    import bridge_behaviour as BB
    got, _, _ = BB.forwarded("engrave_memorials", {"max": 3, "ghosts": True, "dry_run": True}, "ai-welfare",
                             "engrave_memorials")
    assert got == [("engrave_memorials", [3, True, True])], got
    got, _, _ = BB.forwarded("engrave_memorials", {}, "ai-welfare", "engrave_memorials")
    assert got == [("engrave_memorials", [5, False, False])], got


# ---- (5) the stuck sweep and the AI's own gate pieces ---------------------------------------

@test("stuck sweep (F 18:33-18:35): a gate whose own pieces have no suspended job is not nudged with free_gate_jobs")
def _():
    r = {"kind": "gate", "id": 1, "what": "surface", "x": 108, "y": 149, "pieces": 1, "worker": False,
         "suspended": False}
    nudge, retire, what = PST._remedies(r, None, None, 46, CFG)
    assert nudge is None and retire is None and "none suspended" in what, (nudge, what)
    r["suspended"] = True
    nudge, _, _ = PST._remedies(r, None, None, 46, CFG)
    assert nudge == {"type": "free_gate_jobs", "entrance_id": 1}
    # an older bridge that doesn't say: nudged as before
    del r["suspended"]
    assert PST._remedies(r, None, None, 46, CFG)[0] == {"type": "free_gate_jobs", "entrance_id": 1}
    src = (LUA / "ai-stuck.lua").read_text(encoding="utf-8")
    assert "suspended = suspended,   -- (r1g8)" in src


GATES_FAKE = r"""
local src = ...
local W = {site = {}, projects = {}}
local env = setmetatable({}, {__index = _G})
env.U = {site_put = function(k, v) W.site[k] = v end, site_get = function(k, d) return W.site[k] or d end}
env.GATES = {entrances = {}}
env.gate_planned_records = function() return W.recs or {}, {} end
env.prune_gate_planned = function(list) return list end
env.gate_planned_since = function() return 1 end
env.ai_planned_building = function(b) return b.mine == true end
env.reqscript = function(n)
    if n == 'ai-builder' then
        return {load_projects = function() return {list = W.projects} end,
                project_areas = function(p) return {p.area} end}
    end
    error('no ' .. n)
end
local bs = {}
env.df = {building = {find = function(id) return bs[id] end}}
assert(load(src, 'ai-gates-stuck', 't', env))()
function W.piece(id, x, y, z, mine, suspended)
    bs[id] = {id = id, x1 = x, y1 = y, x2 = x, y2 = y, z = z, mine = mine,
              jobs = {{flags = {suspend = suspended}}}}
end
return env, W
"""


@test("free_gate_jobs (F): a suspended job on the AI's own level works near the entrance isn't called the player's")
def _():
    if not need_lua():
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(GATES_FAKE, (LUA / "ai-gates-stuck.lua").read_text(encoding="utf-8"))
    w.piece(10, 108, 149, 170, True, False)               # the AI's hatch, waiting for its cover
    w.piece(11, 110, 149, 170, False, True)               # floor 2's wall (the AI's floor level)
    w.projects[1] = T(lua, {"kind": "floor", "area": {"x1": 109, "y1": 140, "x2": 130, "y2": 160, "z": 170}})
    env.GATES.entrances[1] = T(lua, {"id": 1, "pending_ids": [10, 11]})
    r = py(env.free_gate_jobs(1, False, False))
    assert r["ok"] is False and r.get("ai_works") == 1 and not r.get("players"), r
    assert "player" not in r["error"] and "the AI's own level works" in r["error"], r
    # a piece outside every AI level: the player's, as before
    w.piece(12, 90, 120, 170, False, True)
    env.GATES.entrances[1] = T(lua, {"id": 1, "pending_ids": [10, 12]})
    r = py(env.free_gate_jobs(1, False, False))
    assert r.get("players") and "what the player planned" in r["error"], r


# ---- (6) a ghost laid to rest is no second death ------------------------------------------

ZULBAN_AGAIN = {"again": True, "animal": False, "cause": "BLEED", "kind": "death", "old_death": True,
                "name": 'Zulban Dakostag "Floordaub", Axedwarf', "own_civ": True, "tick": 356390,
                "unit_id": 17163, "x": 97, "y": 159, "year": 259, "z": 166}


@test("laid to rest (A, Zulban 09:59:17): journaled as laid_to_rest, not a death; the log line says so")
def _():
    import overseer
    j = overseer.journal_event(ZULBAN_AGAIN)
    assert j["kind"] == "laid_to_rest" and j["was"] == "death" and ZULBAN_AGAIN["kind"] == "death", j
    first = dict(ZULBAN_AGAIN, again=None, old_death=None)
    assert overseer.journal_event(first) is first
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    i = src.index("events = bridge.events()")
    block = src[i:i + 1600]
    assert 'journal({"kind": "event", "fort": key, "event": journal_event(ev)})' in block
    assert '"Laid to rest: " + death_words(ev)' in block
    import replay
    assert replay.event_text(j).startswith("laid to rest:")


@test("laid to rest: the scorecard counts Zulban once from a journal with either form of the second event")
def _():
    import overseer
    import scorecard
    first = dict(ZULBAN_AGAIN, tick=79912)
    del first["again"], first["old_death"]
    for second in (ZULBAN_AGAIN, overseer.journal_event(ZULBAN_AGAIN)):
        jn = [{"kind": "event", "event": first}, {"kind": "event", "event": second}]
        d = dict(scorecard.journal_counts(jn, {"year": 260, "tick": 0})["deaths"])
        assert d == {"BLEED": 1}, (second["kind"], d)


if __name__ == "__main__":
    finish()
