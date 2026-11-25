"""(item7) The memorial slab orders that never end, and the walking ghost first
(B, 24 Nov: Inod "Oarzeal"'s ghost walked while the AI's 14 EngraveSlab orders,
frequency NONE, stood at "1 left" and engraved other dead's slabs again and
again: one dwarf's 71 times, 136 Slab buildings; `slabs` put up "1 engraved
memorial slab, none of them a walking ghost's" 34 times in 2 hours).

  * slab_order makes its order OneTime;
  * memorial_slabs puts up one slab a dead, and none for a dead a Slab
    building names already;
  * prune_memorial_orders (lua/ai-memorials.lua) takes the spent orders off
    with their unworked jobs, keeps a worked one, makes the rest once-only,
    and moves the walking ghosts' orders first;
  * the slabs_orders rule, the blanks wanted only for ghosts with no slab,
    slabs_ahead held while a ghost has none; the wiring.

    python tests/test_item7_memorials.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, skip  # noqa: E402
from planner import Memory  # noqa: E402
import planner_society as PS  # noqa: E402
import planner_memorials as PM  # noqa: E402
import planner_welfare as PW  # noqa: E402
from planner_config import PLANNER_CONFIG  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA = ROOT / "lua"
OARZEAL = 41275


def need_lua():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
        return False
    return True


def b_state(**sup):
    """B, 24 Nov 22:22: one ghost (Oarzeal, body lying), no blank slab, autoslab on."""
    base = {"slabs": 0, "memorial_slabs": 0, "ghost_slabs": 0, "ghosts_no_slab": 0}
    base.update(sup)
    return {"date": {"year": 272, "tick": 1000}, "dwarves": {"total": 38}, "orders": [], "_errors": {},
            "dead": {"ghosts": 1, "ghost_names": ['Inod Mebzuthkizest "Oarzeal", Ghostly Planter'],
                     "unburied": 0, "free_tombs": 8, "memorial_orders": 14,
                     "ghost_list": [{"hf": OARZEAL, "kind": "AngryGhost", "body": "lying"}]},
            "supplies": base, "tools": {"autoslab": True},
            "buildings": {"workshops": {"Masons": 2}}, "stocks": {"boulders": 100}, "stone_use": {"usable": 100},
            "labor": {}, "projects": {"open": []}}


# ---- the brain -------------------------------------------------------------------------------

@test("slabs_orders (B): 13 spent memorial orders and the ghost's endless one: prune_memorial_orders, first")
def _():
    s = b_state(memorial_orders_stale=13, memorial_orders_endless=1, ghosts_unslabbed=1)
    props, notes = [], []
    PM.memorial_order_rules(s, props, notes)
    assert len(props) == 1 and props[0].rule == "slabs_orders", props
    p = props[0]
    assert p.action == {"type": "prune_memorial_orders"} and p.priority == 1, p
    assert "13 memorial slab order(s)" in p.reason and "1 walking ghost(s) wait" in p.reason, p.reason


@test("slabs_orders: nothing reported, or nothing stale or endless: no proposal (an old bridge sends neither)")
def _():
    for sup in ({}, {"memorial_orders_stale": 0, "memorial_orders_endless": 0}, {"memorial_orders_stale": True}):
        props = []
        PM.memorial_order_rules(b_state(**sup), props, [])
        assert not props, (sup, props)
    # no ghost walking: still taken off, at a lower priority
    s = b_state(memorial_orders_stale=2)
    s["dead"]["ghosts"] = 0
    props = []
    PM.memorial_order_rules(s, props, [])
    assert props and props[0].priority == 3, props


@test("the welfare rules call slabs_orders; slabs_ahead waits while a walking ghost has no slab of her own")
def _():
    s = b_state(memorial_orders_stale=3, ghosts_unslabbed=1)
    s["dead"].update({"memorials_wanted": 4, "unreachable_dead": 6})
    props, notes = [], []
    PW._welfare_rules(s, PLANNER_CONFIG, props, notes, Memory(), {"engrave_slabs": True})
    rules = [p.rule for p in props]
    assert "slabs_orders" in rules and "slabs_ahead" not in rules, rules
    assert any("until the walking ghost(s) have their own" in n for n in notes), notes
    s["supplies"]["ghosts_unslabbed"] = 0
    props = []
    PW._welfare_rules(s, PLANNER_CONFIG, props, [], Memory(), {"engrave_slabs": True})
    assert "slabs_ahead" in [p.rule for p in props], [p.rule for p in props]


@test("slabs (B): blanks are wanted for the ghosts with no slab yet, not once hers is engraved")
def _():
    # her slab engraved (loose or put up): no "need memorial slabs, 0 blank" again and again
    s = b_state(ghosts_unslabbed=0)
    props = []
    PS._dead_notes(s, [], props, {"engrave_slabs": True}, Memory())
    assert not [p for p in props if p.action.get("recipe") == "stone_slab"], [(p.rule, p.action) for p in props]
    # none yet: two blanks ordered (ghosts 1 - 0 + 1)
    s = b_state(ghosts_unslabbed=1)
    props = []
    PS._dead_notes(s, [], props, {"engrave_slabs": True}, Memory())
    wo = [p for p in props if p.action.get("recipe") == "stone_slab"]
    assert wo and wo[0].action["amount"] == 2, [(p.rule, p.action) for p in props]
    # an old bridge (no ghosts_unslabbed): as before, by the ghosts
    s = b_state()
    props = []
    PS._dead_notes(s, [], props, {"engrave_slabs": True}, Memory())
    assert [p for p in props if p.action.get("recipe") == "stone_slab"]
    # and ghost_work_blocked says no slab is short once hers exists
    s = b_state(ghosts_unslabbed=0)
    s["buildings"] = {"workshops": {}}
    assert not PS.ghost_work_blocked(s, None), PS.ghost_work_blocked(s, None)



@test("slabs (item4, B): every unbuilt slab a spare (its dead has one up): no place_slabs, a note; the rest still put up")
def _():
    # B, 24 Nov: hf 42066's slab stands, two more of hers lie engraved; the bridge counts none of them
    s = b_state(memorial_slabs=0, memorial_spare=2, dup_memorials=1, ghosts_unslabbed=0)
    props, notes = [], []
    PS._dead_notes(s, notes, props, {"engrave_slabs": True}, Memory())
    PW._welfare_rules(s, PLANNER_CONFIG, props, notes, Memory(), {"engrave_slabs": True})
    assert not [p for p in props if p.action.get("type") == "place_slabs"], [(p.rule, p.action) for p in props]
    assert any("2 engraved memorial slab(s) are spares" in n for n in notes), notes
    assert any("1 dead have more than one memorial slab up" in n for n in notes), notes
    # one not a spare beside them: put up, that one only
    s = b_state(memorial_slabs=1, memorial_spare=2, ghost_slabs=1, ghosts_unslabbed=0)
    props = []
    PS._dead_notes(s, [], props, {"engrave_slabs": True}, Memory())
    pl = [p for p in props if p.action.get("type") == "place_slabs"]
    assert pl and pl[0].action == {"type": "place_slabs", "max": 1}, [(p.rule, p.action) for p in props]
    # no ghost: slabs_ahead_place the same way
    s["dead"]["ghosts"] = 0
    s["supplies"]["memorial_slabs"] = 0
    props, notes = [], []
    PW._welfare_rules(s, PLANNER_CONFIG, props, notes, Memory(), {"engrave_slabs": True})
    assert not [p for p in props if p.action.get("type") == "place_slabs"], [(p.rule, p.action) for p in props]
    # an old bridge (no spare fields): no note
    notes = []
    PM.spare_slab_notes(b_state(), notes)
    assert not notes, notes


# ---- the Lua's text (no lupa here) -----------------------------------------------------------

@test("slab_order makes its EngraveSlab order OneTime, inside the guarded block (a failed write leaks nothing)")
def _():
    src = (LUA / "ai-welfare.lua").read_text(encoding="utf-8")
    i = src.index("local function slab_order(hf)")
    body = src[i:src.index("\nend\n", i)]
    j = body.index("local ok, err = pcall(function()")
    k = body.index("if not ok then")
    assert "o.frequency = df.workquota_frequency_type.OneTime" in body[j:k], body


@test("the wiring: action, dry run, cache, words, rule classes, report fields, the module listed")
def _():
    cat = (LUA / "ai-bridge-catalog.lua").read_text(encoding="utf-8")
    assert "prune_memorial_orders = function(a) return reqscript('ai-memorials').prune_orders(a.dry_run == true) end" in cat
    assert "'prune_memorial_orders'," in cat[cat.index("DRY_OK = {}"):]
    assert "CACHE_INVALIDATES.prune_memorial_orders = {'dead'}" in (LUA / "ai-bridge-sections.lua").read_text(encoding="utf-8")
    assert "'ai-memorials'," in (LUA / "ai-bridge.lua").read_text(encoding="utf-8")
    sup = (LUA / "ai-bridge-report-supplies.lua").read_text(encoding="utf-8")
    assert "reqscript('ai-memorials').order_scan()" in sup and "out.ghosts_unslabbed = none" in sup
    # (item4) the spares and the dead with 2+ memorials up, from memorial_slabs' other returns
    assert "out.memorial_slabs, out.memorial_spare, out.dup_memorials = #m, sp, dup" in sup
    import overseer_words as OW
    import hold_classes as HC
    import crisis
    assert "prune_memorial_orders" in OW.SHORT_WORDS
    src = (ROOT / "brain" / "hold_classes.py").read_text(encoding="utf-8")
    assert '"slabs_orders"' in src and '"prune_memorial_orders"' in src, HC
    assert "slabs_orders" in crisis.RECOVERY_RULES
    mem = (LUA / "ai-memorials.lua").read_text(encoding="utf-8")
    assert "--@ module = true" in mem and len(mem.encode()) + mem.count("\n") < 59000
    rooms = (LUA / "ai-builder-rooms.lua").read_text(encoding="utf-8")
    assert len(rooms.encode()) + rooms.count("\n") < 59900


# ---- the Lua run (lupa, on the PC) -----------------------------------------------------------

MEM_FAKE = r"""
local src = ...
local W = {orders = {}, slabs = {}, jobs = {}, removed = {}, ghosts = {}, screen = false}
local env = setmetatable({}, {__index = _G})
local function vec(init)
    local items = init or {}
    return setmetatable({}, {
        __index = function(_, k)
            if type(k) == 'number' then return items[k + 1] end
            if k == '_items' then return items end
            if k == 'erase' then return function(_, i) table.remove(items, i + 1) end end
            if k == 'insert' then
                return function(_, i, x) if i == '#' then table.insert(items, x) else table.insert(items, i + 1, x) end end
            end
        end,
        __len = function() return #items end})
end
W.all = vec({})
env.ipairs = function(t)
    local items = type(t) == 'table' and t._items
    if items then
        local i = -1
        return function() i = i + 1; local v = items[i + 1]; if v ~= nil then return i, v end end
    end
    return ipairs(t)
end
env.df = {
    global = {world = {manager_orders = {all = W.all}, items = {other = {SLAB = W.slabs}},
                       jobs = {list = {next = nil}}},
              game = {main_interface = {info = {open = false}, job_details = {open = false}}}},
    job_type = {EngraveSlab = 'EngraveSlab', ConstructSlab = 'ConstructSlab'},
    slab_engraving_type = {Memorial = 'Memorial'},
    workquota_frequency_type = {OneTime = 0, NONE = -1},
    info_interface_mode_type = {WORK_ORDERS = 'WO'},
}
env.reqscript = function(n)
    if n == 'ai-builder' then return {ghost_hfs = function() return W.ghosts end} end
    error('no ' .. n)
end
env.dfhack = {job = {getWorker = function(j) return j.worker end,
                     removeJob = function(j) table.insert(W.removed, j.id) return true end}}
function W.order(id, hf, freq)
    local o = {id = id, job_type = 'EngraveSlab', specdata = {hist_figure_id = hf}, frequency = freq or -1,
               item_conditions = {}, order_conditions = vec({}), items = nil}
    function o:delete() o.deleted = true end
    W.all:insert('#', o)
    return o
end
function W.slab(topic) table.insert(W.slabs, {engraving_type = 'Memorial', topic = topic}) end
function W.job(id, order_id, worker)
    local j = {id = id, order_id = order_id, worker = worker}
    local link = {item = j, next = env.df.global.world.jobs.list.next}
    env.df.global.world.jobs.list.next = link
end
function W.ids() local out = {} for _, o in ipairs(W.all._items) do table.insert(out, o.id) end return out end
function W.freq(id) for _, o in ipairs(W.all._items) do if o.id == id then return o.frequency end end end
function W.open_screen() env.df.global.game.main_interface.job_details.open = true end
assert(load(src, 'ai-memorials', 't', env))()
return env, W
"""


def mem_world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    src = (LUA / "ai-memorials.lua").read_text(encoding="utf-8")
    env, w = lua.execute(MEM_FAKE, src)
    return lua, env, w


def lst(t):
    return [t[k] for k in sorted(t.keys())] if t is not None else []


@test("prune_orders (B): the spent orders off with their unworked jobs, a worked one kept, the ghost's first and once")
def _():
    if not need_lua():
        return
    lua, env, w = mem_world()
    w.ghosts[OARZEAL] = True
    w.order(806, 42066)
    w.order(1106, 42066)
    w.order(1974, 41939)
    w.order(2378, OARZEAL)          # hers: no slab yet
    w.order(3000, 50000, 0)         # another dead's, still wanted, already OneTime
    for _ in range(3):
        w.slab(42066)
    w.slab(41939)
    w.job(2966696, 1974)            # waiting for a blank: removed with its order
    w.job(2966700, 1106, lua.eval("{id = 7}"))   # a mason works it: the order kept
    scan = env.order_scan()
    assert (scan.stale, scan.endless, scan.ghost_waiting) == (3, 1, 1), (scan.stale, scan.endless)
    dry = env.prune_orders(True)
    assert dry.dry_run and lst(w.ids()) == [806, 1106, 1974, 2378, 3000]
    r = env.prune_orders(False)
    assert r.ok and r.removed == 2 and r.kept_worked == 1 and r.made_once == 1 and r.ghosts_first == 1, r
    assert lst(w.ids()) == [2378, 1106, 3000], lst(w.ids())
    assert lst(w.removed) == [2966696], lst(w.removed)
    assert w.freq(2378) == 0, w.freq(2378)


@test("prune_orders: nothing to do is a refusal that says so; the work orders screen open is a refusal")
def _():
    if not need_lua():
        return
    lua, env, w = mem_world()
    w.order(3000, 50000, 0)
    r = env.prune_orders(False)
    assert r.rejected and r.nothing_to_do, r
    w.order(806, 42066)
    w.slab(42066)
    w.open_screen()
    r = env.prune_orders(False)
    assert r.rejected and "screen is open" in r.error, r
    assert lst(w.ids()) == [3000, 806]


ROOMS_FAKE_MIN = r"""
local src = ...
local W = {slabs = {}, sbld = {}, units = {}}
local env = setmetatable({}, {__index = _G})
env.require = function(n) error('no ' .. tostring(n)) end
env.item_held = function(it) return false end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.info, env.has = function() return nil end, function() return false end
env.ez = function(z) return z - 130 end
env.elevation_offset = function() return 0 end
env.df = {global = {plotinfo = {race_id = 1, civ_id = 10},
                    world = {units = {active = W.units, all = W.units}, items = {other = {SLAB = W.slabs}},
                             buildings = {other = {SLAB = W.sbld}}}},
          slab_engraving_type = {Memorial = 'Memorial'}, building_type = {Slab = 'Slab', Workshop = 'Workshop'}}
env.dfhack = {units = {isGhost = function(u) return u.ghost == true end},
              items = {getHolderBuilding = function(it) return nil end}}
assert(load(src, 'ai-builder-rooms', 't', env))()
function W.slab(id, topic, flags)
    local it = {id = id, topic = topic, engraving_type = 'Memorial', flags = flags or {}}
    table.insert(W.slabs, it)
    return it
end
function W.site(id, it)
    local b = {id = id, contained_items = {{item = it}}, jobs = {}}
    function b:getBuildStage() return 1 end
    table.insert(W.sbld, b)
end
return env, W
"""


@test("memorial_slabs (B): one loose slab a dead, none for a dead a Slab building names; the ghost's first")
def _():
    if not need_lua():
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    src = (LUA / "ai-builder-rooms.lua").read_text(encoding="utf-8")
    env, w = lua.execute(ROOMS_FAKE_MIN, src)
    w.units[1] = lua.table_from({"ghost": True, "race": 1, "civ_id": 10, "hist_figure_id": OARZEAL})
    built = w.slab(1, 42066, lua.table_from({"in_building": True}))
    w.site(500, built)
    w.slab(2, 42066)                 # the 71st copy: its dead's slab stands already
    w.slab(3, 41939)
    w.slab(4, 41939)                 # two loose of one dead: one put up
    w.slab(5, OARZEAL)
    got = [it.id for it in lst(env.memorial_slabs()[0])]
    assert got == [5, 3], got
    waiting, none = env.ghost_slab_counts()
    assert (waiting, none) == (1, 0), (waiting, none)


@test("memorial_slabs (item4, B): a dead with a memorial up: the rest spares, counted by hf; 2+ up counted")
def _():
    if not need_lua():
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    src = (LUA / "ai-builder-rooms.lua").read_text(encoding="utf-8")
    env, w = lua.execute(ROOMS_FAKE_MIN, src)
    w.site(500, w.slab(1, 42066, lua.table_from({"in_building": True})))
    w.site(501, w.slab(2, 42066, lua.table_from({"in_building": True})))   # two up already
    w.slab(3, 42066)
    w.slab(4, 42066)                                                       # two more lie: spares
    w.site(502, lua.table_from({"id": 9, "topic": 41939, "engraving_type": "Slab"}))   # a blank: names no dead
    w.slab(5, 41939)
    one, spare, dup, by = env.memorial_slabs()
    assert [it.id for it in lst(one)] == [5], lst(one)
    assert (spare, dup, by[42066]) == (2, 1, 2), (spare, dup)
    # every one left a spare: place_slabs refuses, saying so, and builds nothing
    w.slabs[len(w.slabs)].flags.in_building = True
    r = env.place_slabs(5, False)
    assert r.ok is False and r.rejected and "spare" in r.error and r.spare == 2, r
    assert r.spare_hfs[1].hf == 42066 and r.spare_hfs[1].n == 2, r.spare_hfs


if __name__ == "__main__":
    finish()
