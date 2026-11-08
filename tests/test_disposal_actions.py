"""(0.105.27, disposal round: actions) lua/ai-disposal.lua's actions and its
report section, in a fake fort: every safety mask (danger, siege, the sealed
caverns, the cistern's tiles, artifacts, a living dwarf's things, the unknown
reason), each action's dry run, the cap, and the bridge's wiring.

    python tests/test_disposal_actions.py
"""

from __future__ import annotations

import re
from pathlib import Path

from harness import test, finish, code_has  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

ROOT = Path(__file__).resolve().parent.parent
LUA_DIR = ROOT / "lua"

# A fort: the surface from z 150 up, a cavern at z 100, the fort's race 1.
# A dump zone (id 50) on the surface at x10-12 y10-12 z150. The cistern's
# room at x40-42 y40-42 z120, its tunnel (43..44, 41) and the plug (45, 41). Items
# are made by mk{kind=..., ...}.
FAKE = r"""
local src = ...
local W = {items = {}, by_kind = {}, units = {}, zones = {}, piles = {}, furnaces = {}, orders = {},
           site = {}, removed = {}, caves = {}, assigned = {}}
local env = setmetatable({}, {__index = _G})
local function qual(self) return self.quality or 0 end
local function kind_of(self) return self.kind end
function W.mk(t)
    t.id = t.id or (#W.items + 100)
    t.flags = t.flags or {}
    if t.flags.on_ground == nil and not t.flags.in_inventory then t.flags.on_ground = true end
    t.pos = t.pos or {x = 70, y = 70, z = 130}
    t.getQuality = qual
    t.getType = kind_of
    if t.kind == 'WEAPON' and t.subtype == nil then t.subtype = {skill_melee = 2, id = 'ITEM_WEAPON_SWORD_SHORT'} end
    table.insert(W.items, t)
    W.by_kind[t.kind] = W.by_kind[t.kind] or {}
    table.insert(W.by_kind[t.kind], t)
    return t
end
function W.unit(t)
    t.flags1 = t.flags1 or {}
    table.insert(W.units, t)
    return t
end
local other = setmetatable({}, {__index = function(_, k)
    if k == 'IN_PLAY' then return W.items end
    return W.by_kind[k] or {}
end})
env.df = {
    global = {world = {items = {other = other, all = W.items},
                       units = {active = W.units},
                       buildings = {other = {ANY_ZONE = W.zones, STOCKPILE = W.piles, FURNACE_ANY = W.furnaces},
                                    all = {}},
                       manager_orders = {all = W.orders}},
              plotinfo = {race_id = 1, group_id = 1, equipment = {items_assigned = {WEAPON = W.assigned}}},
              standing_orders_gather_refuse = 0, standing_orders_forbid_used_ammo = 1,
              standing_orders_dump_other = 0, standing_orders_petition_citizenship = 0},
    item = {find = function(id) for _, it in ipairs(W.items) do if it.id == id then return it end end end},
    civzone_type = {Dump = 7, Pen = 3},
    building_type = {Civzone = 1},
    furnace_type = {Smelter = 1, MagmaSmelter = 2},
    job_type = {MeltMetalObject = 5},
    job_skill = {MINING = 0, AXE = 1, SWORD = 2},
    item_type = setmetatable({}, {__index = function(_, k) return k end}),
}
env.dfhack = {
    units = {isDead = function(u) return u.dead == true end, isDanger = function(u) return u.danger == true end,
             isInvader = function(u) return u.invader == true end, isActive = function() return true end,
             getPosition = function(u) return u.pos.x, u.pos.y, u.pos.z end},
    items = {getPosition = function(it)
                 if it.off then return nil end
                 return it.pos.x, it.pos.y, it.pos.z end,
             getOwner = function(it) return it.owner end,
             getHolderUnit = function(it) return it.holder end,
             getContainedItems = function(it) return it.contents or {} end,
             remove = function(it) it.flags.removed = true; table.insert(W.removed, it.id); return true end},
    matinfo = {decode = function(it) return {material = {flags = {IS_METAL = it.metal == true}}} end},
    maps = {getTileFlags = function(x, y, z)
                return {outside = z >= 150, feature_global = W.caves[z] == true} end,
            getTileBlock = function(x, y, z)
                local bx, by = x - x % 16, y - y % 16
                local ids = {}
                for _, it in ipairs(W.items) do
                    if it.pos.z == z and it.pos.x - it.pos.x % 16 == bx and it.pos.y - it.pos.y % 16 == by then
                        table.insert(ids, it.id)
                    end
                end
                return {items = ids}
            end},
    buildings = {containsTile = function() return true end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
W.caves[100] = true
function W.dump(id, x1, y1, z)
    local zn = {id = id, type = 7, x1 = x1, y1 = y1, x2 = x1 + 2, y2 = y1 + 2, z = z,
                getType = function() return 1 end}
    table.insert(W.zones, zn)
    return zn
end
W.site['ai-overseer/cistern'] = {stage = 'filling',
    plan = {cistern = {x1 = 40, y1 = 40, x2 = 42, y2 = 42, z = 120}, tunnel_path = {{x = 43, y = 41}, {x = 44, y = 41}, {x = 45, y = 41}}}}   -- (45, 41): the plug
assert(load(src, 'ai-disposal', 't', env))()
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-disposal.lua"))
    return lua, env, w


def mk(lua, w, **kw):
    """An item: kind, flags {...}, pos (x, y, z), and anything else."""
    pos = kw.pop("pos", None)
    flags = kw.pop("flags", {})
    t = dict(kw)
    t["flags"] = lua.table_from(flags)
    if pos:
        t["pos"] = lua.table_from({"x": pos[0], "y": pos[1], "z": pos[2]})
    for k, v in list(t.items()):
        if isinstance(v, dict):
            t[k] = lua.table_from(v)
    return w.mk(lua.table_from(t))


def opts(lua, **kw):
    out = {}
    for k, v in kw.items():
        out[k] = lua.table_from(v) if isinstance(v, list) else v
    return lua.table_from(out)


def skipped(r):
    return dict(r.skipped) if r.skipped else {}


def need_lua():
    return LuaRuntime is not None


# --- unforbid_items: the reasons and every mask -------------------------------------

@test("unforbid_items: a dead dwarf's sword and used ammo let go; a dry run changes nothing and counts the same")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    a = mk(lua, w, kind="WEAPON", flags={"forbid": True, "dead_dwarf": True})
    b = mk(lua, w, kind="AMMO", flags={"forbid": True})
    r = env.unforbid_items(opts(lua), True)
    assert r.ok and r.n == 2 and r.dry_run, dict(r)
    assert a.flags.forbid and b.flags.forbid
    assert dict(r.by_reason) == {"own_dead": 1, "used_ammo": 1}, dict(r.by_reason)
    r = env.unforbid_items(opts(lua), False)
    assert r.ok and r.unforbidden == 2 and not a.flags.forbid and not b.flags.forbid, dict(r)


@test("unforbid_items: ammo in a stockpile isn't used ammo (unknown, kept); gear on another race's body is other_dead")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    w.piles[1] = lua.table_from({"x1": 60, "y1": 60, "x2": 80, "y2": 80, "z": 130})
    ammo = mk(lua, w, kind="AMMO", flags={"forbid": True})
    mk(lua, w, kind="CORPSE", race=2, flags={"forbid": True}, pos=(20, 20, 130))
    helm = mk(lua, w, kind="HELM", flags={"forbid": True}, pos=(20, 20, 130))
    r = env.unforbid_items(opts(lua), False)
    assert r.n == 1 and not helm.flags.forbid and ammo.flags.forbid, dict(r)
    assert dict(r.by_reason) == {"other_dead": 1} and skipped(r).get("unknown") == 1, (dict(r.by_reason), skipped(r))


@test("unforbid_items: unknown is kept unless listed AND player_items; listed alone is still masked")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    it = mk(lua, w, kind="COIN", flags={"forbid": True})
    r = env.unforbid_items(opts(lua, player_items=True), False)     # player_items, not listed
    assert not r.ok and it.flags.forbid and skipped(r) == {"reason": 1}, (dict(r), skipped(r))
    r = env.unforbid_items(opts(lua, reasons=["unknown"]), False)     # listed, no player_items
    assert not r.ok and it.flags.forbid and skipped(r) == {"unknown": 1}, skipped(r)
    r = env.unforbid_items(opts(lua, reasons=["unknown"], player_items=True), False)
    assert r.ok and r.n == 1 and not it.flags.forbid, dict(r)


@test("masks: danger within 20 tiles, a sealed cavern, the cistern's tiles, an artifact, a living owner")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    w.unit(lua.table_from({"danger": True, "pos": lua.table_from({"x": 0, "y": 0, "z": 130})}))
    near = mk(lua, w, kind="WEAPON", flags={"forbid": True, "dead_dwarf": True}, pos=(10, 9, 131))
    cave = mk(lua, w, kind="WEAPON", flags={"forbid": True, "dead_dwarf": True}, pos=(70, 70, 100))
    cis = mk(lua, w, kind="WEAPON", flags={"forbid": True, "dead_dwarf": True}, pos=(41, 41, 120))
    tun = mk(lua, w, kind="WEAPON", flags={"forbid": True, "dead_dwarf": True}, pos=(44, 41, 120))
    art = mk(lua, w, kind="WEAPON", flags={"forbid": True, "dead_dwarf": True, "artifact": True})
    alive = w.unit(lua.table_from({"pos": lua.table_from({"x": 200, "y": 200, "z": 10})}))
    own = mk(lua, w, kind="WEAPON", flags={"forbid": True, "owned": True}, owner=alive)
    lone = mk(lua, w, kind="WEAPON", flags={"forbid": True, "owned": True})   # owner can't be read
    dead = w.unit(lua.table_from({"dead": True, "pos": lua.table_from({"x": 200, "y": 200, "z": 10})}))
    heir = mk(lua, w, kind="WEAPON", flags={"forbid": True, "owned": True}, owner=dead)
    # the seal holds
    w.site["ai-overseer/threats"] = lua.table_from({"sealed": lua.table_from({"Cavern 1": lua.table_from({"ids": lua.table_from([5])})})})
    r = env.unforbid_items(opts(lua), False)
    s = skipped(r)
    assert s == {"danger": 1, "cavern": 1, "cistern": 2, "artifact": 1, "owned": 2}, s
    assert r.n == 1 and not heir.flags.forbid and dict(r.by_reason) == {"own_dead": 1}, dict(r)
    for it in (near, cave, cis, tun, art, own, lone):
        assert it.flags.forbid
    # the seal opened: the cavern's item may go
    w.site["ai-overseer/threats"] = lua.table_from({"sealed": lua.table_from({})})
    r = env.unforbid_items(opts(lua), False)
    assert r.n == 1 and not cave.flags.forbid, dict(r)


@test("masks: a siege refuses every action (dry run too); a lone thief doesn't make one, only its 20 tiles")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    it = mk(lua, w, kind="WEAPON", flags={"forbid": True, "dead_dwarf": True}, pos=(150, 150, 130))
    w.unit(lua.table_from({"invader": True, "pos": lua.table_from({"x": 0, "y": 0, "z": 130})}))
    r = env.unforbid_items(opts(lua), False)
    assert r.ok and r.n == 1, dict(r)
    it.flags.forbid = True
    for _ in range(2):
        w.unit(lua.table_from({"invader": True, "pos": lua.table_from({"x": 1, "y": 0, "z": 130})}))
    for fn in ("unforbid_items", "mark_melt", "mark_dump", "empty_dump"):
        for dry in (True, False):
            r = env[fn](opts(lua), dry)
            assert not r.ok and r.siege and r.invaders == 3, (fn, dict(r))
    assert it.flags.forbid
    # a caged invader is no part of a siege
    w.units[3].flags1.caged = True
    assert env.siege_state().on is False


@test("unforbid_items: max caps the work and says more; a held, in-job or loose-in-a-bin item is never touched")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    for _ in range(5):
        mk(lua, w, kind="AMMO", flags={"forbid": True})
    job = mk(lua, w, kind="AMMO", flags={"forbid": True, "in_job": True})
    held = mk(lua, w, kind="WEAPON", flags={"forbid": True, "dead_dwarf": True, "in_inventory": True},
              holder=lua.table_from({}))
    r = env.unforbid_items(opts(lua, max=3), False)
    assert r.n == 3 and r.more, dict(r)
    r = env.unforbid_items(opts(lua, max=50), False)
    assert r.n == 2 and job.flags.forbid and held.flags.forbid, dict(r)


# --- mark_melt -------------------------------------------------------------------------

@test("mark_melt: forbidden worn metal and a dead enemy's metal gear marked (forbid off); never masterwork, assigned or non-metal")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    worn = mk(lua, w, kind="WEAPON", metal=True, wear=1, flags={"forbid": True, "dead_dwarf": True})
    mk(lua, w, kind="CORPSE", race=2, flags={"forbid": True}, pos=(20, 20, 130))
    enemy = mk(lua, w, kind="ARMOR", metal=True, flags={"forbid": True}, pos=(20, 20, 130))
    master = mk(lua, w, kind="WEAPON", metal=True, wear=2, quality=5, flags={"forbid": True, "dead_dwarf": True})
    wood = mk(lua, w, kind="SHIELD", metal=False, wear=3, flags={"forbid": True, "dead_dwarf": True})
    fresh = mk(lua, w, kind="WEAPON", metal=True, flags={"forbid": True, "dead_dwarf": True})
    squad = mk(lua, w, kind="WEAPON", metal=True, wear=2, id=999, flags={"forbid": True, "dead_dwarf": True})
    w.assigned[1] = 999
    w.furnaces[1] = lua.table_from({"type": 1})
    r = env.mark_melt(opts(lua), True)
    assert r.ok and r.n == 2 and not worn.flags.melt and enemy.flags.forbid, dict(r)
    assert r.smelters == 1 and r.can_melt and r.needs_order, dict(r)
    r = env.mark_melt(opts(lua), False)
    assert r.marked == 2 and worn.flags.melt and enemy.flags.melt and not enemy.flags.forbid, dict(r)
    assert skipped(r) == {"masterwork": 1, "assigned": 1}, skipped(r)
    for it in (master, wood, fresh, squad):
        assert not it.flags.melt
    # marked already, an order waiting: none needed
    w.orders[1] = lua.table_from({"id": 8, "job_type": 5, "amount_left": 3})
    r = env.mark_melt(opts(lua), False)
    assert r.already == 2 and r.melt_order == 8 and not r.needs_order, dict(r)


@test("mark_melt: keep_enemy_gear keeps a dead enemy's unworn gear; keep_masterwork = false is refused")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    mk(lua, w, kind="CORPSE", race=2, flags={"forbid": True}, pos=(20, 20, 130))
    enemy = mk(lua, w, kind="ARMOR", metal=True, flags={"forbid": True}, pos=(20, 20, 130))
    r = env.mark_melt(opts(lua, keep_enemy_gear=True), False)
    assert not enemy.flags.melt and skipped(r) == {"enemy_gear": 1}, skipped(r)
    r = env.mark_melt(opts(lua, keep_masterwork=False), False)
    assert not r.ok and r.rejected, dict(r)


# --- mark_dump -------------------------------------------------------------------------

@test("mark_dump: worn non-metal clothes (free or forbidden), rotten food and enemy non-metal junk; not without a dump")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    rags = mk(lua, w, kind="PANTS", wear=2)                                   # free: junk whatever the reasons
    worn_f = mk(lua, w, kind="SHOES", wear=3, flags={"forbid": True, "dead_dwarf": True})
    rot = mk(lua, w, kind="MEAT", flags={"rotten": True})
    mk(lua, w, kind="CORPSE", race=2, flags={"forbid": True}, pos=(20, 20, 130))
    club = mk(lua, w, kind="WEAPON", flags={"forbid": True}, pos=(20, 20, 130))
    mail = mk(lua, w, kind="ARMOR", metal=True, wear=3)                        # metal: the smelter's
    new = mk(lua, w, kind="PANTS", wear=1)
    r = env.mark_dump(opts(lua), False)
    assert not r.ok and r.no_dump_zone and not rags.flags.dump, dict(r)
    r = env.mark_dump(opts(lua), True)
    assert r.ok and r.n == 4 and r.no_dump_zone and not rags.flags.dump, dict(r)
    w.dump(50, 10, 10, 150)
    r = env.mark_dump(opts(lua, reasons=["other_dead"]), False)
    assert r.n == 3 and rags.flags.dump and rot.flags.dump and club.flags.dump and not club.flags.forbid, dict(r)
    assert not worn_f.flags.dump and skipped(r) == {"reason": 1}, skipped(r)
    assert not mail.flags.dump and not new.flags.dump
    r = env.mark_dump(opts(lua), False)
    assert r.n == 1 and worn_f.flags.dump and not worn_f.flags.forbid, dict(r)


@test("mark_dump: unknown forbidden junk is masked; the cistern's and what lies in the dump already are left")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    w.dump(50, 10, 10, 150)
    unk = mk(lua, w, kind="PANTS", wear=2, flags={"forbid": True})
    cis = mk(lua, w, kind="PANTS", wear=2, pos=(40, 40, 120))
    there = mk(lua, w, kind="PANTS", wear=2, flags={"forbid": True}, pos=(11, 11, 150))
    r = env.mark_dump(opts(lua, max=10), False)
    assert not r.ok and skipped(r) == {"unknown": 1, "cistern": 1}, skipped(r)
    r = env.mark_dump(opts(lua, reasons=["unknown"], player_items=True), False)
    assert r.n == 1 and unk.flags.dump and not cis.flags.dump and not there.flags.dump, dict(r)


# --- empty_dump ------------------------------------------------------------------------

@test("empty_dump: loose items in the dump removed; never an artifact, a container with things, a held or in-job one")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    w.dump(50, 10, 10, 150)
    junk = [mk(lua, w, kind="PANTS", flags={"forbid": True}, pos=(10 + i, 11, 150)) for i in range(3)]
    art = mk(lua, w, kind="WEAPON", flags={"forbid": True, "artifact": True}, pos=(11, 10, 150))
    box = mk(lua, w, kind="BIN", flags={"forbid": True}, pos=(12, 12, 150), contents=lua.table_from([1]))
    job = mk(lua, w, kind="PANTS", flags={"forbid": True, "in_job": True}, pos=(12, 10, 150))
    away = mk(lua, w, kind="PANTS", flags={"forbid": True}, pos=(14, 11, 150))     # outside the zone
    r = env.empty_dump(opts(lua), True)
    assert r.ok and r.n == 3 and len(w.removed) == 0, dict(r)
    r = env.empty_dump(opts(lua, max=2), False)
    assert r.removed == 2 and r.more and len(w.removed) == 2, dict(r)
    r = env.empty_dump(opts(lua), False)
    assert r.removed == 1 and set(w.removed.values()) == {j.id for j in junk}, (dict(r), list(w.removed.values()))
    assert skipped(r) == {"artifact": 1, "container": 1, "busy": 1}, skipped(r)
    assert not art.flags.removed and not box.flags.removed and not job.flags.removed and not away.flags.removed


@test("empty_dump: near danger the dump stays; no dump zone is refused")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    r = env.empty_dump(opts(lua), False)
    assert not r.ok and r.no_dump_zone, dict(r)
    w.dump(50, 10, 10, 150)
    mk(lua, w, kind="PANTS", flags={"forbid": True}, pos=(11, 11, 150))
    w.unit(lua.table_from({"danger": True, "pos": lua.table_from({"x": 20, "y": 20, "z": 151})}))
    r = env.empty_dump(opts(lua), False)
    assert not r.ok and skipped(r) == {"danger": 1} and len(w.removed) == 0, (dict(r), skipped(r))


# --- set_standing_orders ---------------------------------------------------------------

@test("set_standing_orders: short or full names, dry run, only refuse/dump/forbid orders that exist and read 0/1")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    g = env.df["global"]
    o = lambda **kw: lua.table_from(kw)  # noqa: E731
    r = env.set_standing_orders(o(gather_refuse=1, standing_orders_forbid_used_ammo=0), True)
    assert r.ok and r.dry_run and dict(r.would_set) == {"gather_refuse": 1, "forbid_used_ammo": 0}, dict(r)
    assert g.standing_orders_gather_refuse == 0
    r = env.set_standing_orders(o(gather_refuse=True, forbid_used_ammo=0), False)
    assert r.ok and g.standing_orders_gather_refuse == 1 and g.standing_orders_forbid_used_ammo == 0, dict(r)
    for bad in (o(petition_citizenship=1), o(forbid_nosuch=1), o(gather_refuse=2), lua.table_from({})):
        r = env.set_standing_orders(bad, False)
        assert not r.ok and r.rejected, dict(r)
    g.standing_orders_dump_other = 3
    r = env.set_standing_orders(o(dump_other=1), False)
    assert not r.ok and g.standing_orders_dump_other == 3, dict(r)


# --- the report --------------------------------------------------------------------------

@test("report: the dump zones (inside or not) and what lies in them, the marks, smelters, the seal, the siege")
def _():
    if not need_lua():
        return
    lua, env, w = world()
    w.dump(50, 10, 10, 150)
    w.dump(51, 30, 30, 140)
    mk(lua, w, kind="PANTS", flags={"forbid": True}, pos=(11, 11, 150))
    mk(lua, w, kind="PANTS", flags={"forbid": True}, pos=(31, 31, 140))
    mk(lua, w, kind="PANTS", flags={"forbid": True}, pos=(32, 30, 140))
    mk(lua, w, kind="WEAPON", flags={"melt": True})
    mk(lua, w, kind="SHOES", flags={"dump": True})
    w.furnaces[1] = lua.table_from({"type": 2})
    w.site["ai-overseer/threats"] = lua.table_from({"sealed": lua.table_from({"C1": lua.table_from({})})})
    r = env.report()
    zones = {z.id: (z.inside, z["items"]) for z in r.dump_zones.values()}
    assert zones == {50: (False, 1), 51: (True, 2)}, zones
    assert r.dumped_items == 3 and r.marked_melt == 1 and r.marked_dump == 1, dict(r)
    assert r.smelters == 0 and r.magma_smelters == 1 and r.sealed_caverns == 1 and r.siege is False, dict(r)


# --- ai-util: the moved helpers ----------------------------------------------------------

@test("ai-util: danger_spots / near_danger live there; ai-military-gear forwards to them")
def _():
    util = (LUA_DIR / "ai-util.lua").read_text(encoding="utf-8")
    gear = (LUA_DIR / "ai-military-gear.lua").read_text(encoding="utf-8")
    assert re.search(r"^function danger_spots\(", util, re.M) and re.search(r"^function near_danger\(", util, re.M)
    assert code_has(gear, "local function danger_spots() return U.danger_spots() end")
    assert code_has(gear, "return U.near_danger(spots, x, y, z, UNFORBID_DANGER_TILES)")
    assert "isDanger" not in gear.split("local function danger_spots")[1].split("function unforbid_spares")[0]


# --- the bridge's wiring -------------------------------------------------------------------

NAMES = ["unforbid_items", "mark_melt", "mark_dump", "empty_dump", "set_standing_orders", "place_dump"]


@test("bridge: the six actions in ACTIONS, DRY_OK and CACHE_INVALIDATES; disposal a cached SECTION; the module listed")
def _():
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    acts = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    for n in NAMES:
        assert code_has(src, f"{n} = act_{n},"), n
        assert f"'{n}'" in src.split("DRY_OK = {}")[1].split("DISPLAY_ONLY")[0], n
        assert re.search(rf"^function act_{n}\(a\)", acts, re.M), n
    assert code_has(src, "disposal = function() return safe(function() return reqscript('ai-disposal').report() end) end,")
    assert code_has(src, "disposal = 1}")
    assert code_has(src, "CACHE_INVALIDATES.set_standing_orders = {'disposal', 'dead'}")
    assert "'ai-disposal'" in src.split("BRIDGE_MODULES = {")[1].split("}")[0]
    assert code_has((LUA_DIR / "ai-bridge-orders.lua").read_text(encoding="utf-8"),
                    "melt_metal = {job = 'MeltMetalObject'},")


# The bridge's disposal handlers (ai-bridge-actions, from its disposal
# header on), run over a fake bridge: the builder's place_dump_zone, the
# melt order.
ACTS_FAKE = r"""
local src, dumps, builder, made = ...
local env = setmetatable({}, {__index = _G})
env.reject = function(r) return {ok = false, rejected = true, error = r} end
env.whole_number = function(v) return math.tointeger(tonumber(v)) end
env.int_in = function(v, lo, hi) local n = env.whole_number(v); if n == nil or n < lo or n > hi then return nil end return n end
env.sorted_keys = function(t) local o = {} for k in pairs(t) do table.insert(o, k) end table.sort(o) return o end
env.string_list = function(v, allowed, max)
    if type(v) ~= 'table' then return nil end
    local out = {}
    for _, n in ipairs(v) do if not allowed[n] then return nil end table.insert(out, n) end
    if #out == 0 or #out > max then return nil end
    return out
end
env.act_work_order = function(a) table.insert(made, a); return {ok = true, order_id = 77} end
local D = {dump_zones = function() return dumps end,
           mark_melt = function(o, dry) return {ok = false, rejected = true, n = 3, already = 1, needs_order = true, dry_run = dry} end,
           unforbid_items = function(o, dry) return {ok = true, opts = o, dry = dry} end}
env.reqscript = function(n)
    if n == 'ai-disposal' then return D end
    if n == 'ai-builder' then if builder == false then error('no builder') end return builder end
    error('no ' .. n)
end
src = src:gsub('local function string_list', 'local function _unused_string_list')
assert(load(src, 'acts', 't', env))()
return env
"""


def acts(dumps=None, builder=None, lua=None):
    lua = lua or LuaRuntime(unpack_returned_tuples=True)
    src = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    part = src[src.index("-- (0.105.27) Disposal"):]
    part = "local string_list = string_list\n" + part
    made = lua.table_from([])
    env = lua.execute(ACTS_FAKE, part, lua.table_from(dumps or []), builder if builder is not None else False, made)
    return lua, env, made


@test("bridge: place_dump calls the builder's place_dump_zone(inside, dry_run) under pcall; refused with a dump already")
def _():
    if not need_lua():
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    b = lua.eval("{calls = {}}")
    lua.execute("local b = ...; b.place_dump_zone = function(inside, dry) "
                "table.insert(b.calls, {inside, dry}); return {ok = true, x = 5, y = 6} end", b)
    calls = b.calls
    _, env, _ = acts(builder=b, lua=lua)
    r = env.act_place_dump(lua.table_from({"inside": True, "dry_run": True}))
    assert r.ok and r.inside is True and len(calls) == 1 and calls[1][1] is True and calls[1][2] is True, dict(r)
    _, env, _ = acts(dumps=[lua.table_from({"inside": True, "id": 4, "x": 1, "y": 2})], builder=b, lua=lua)
    r = env.act_place_dump(lua.table_from({"inside": True}))
    assert not r.ok and r.nothing_to_do and list(r.stale.values()) == ["disposal"], dict(r)
    _, env, _ = acts(lua=lua)                               # no builder function: said, not raised
    r = env.act_place_dump(lua.table_from({}))
    assert not r.ok and "place_dump_zone" in r.error, dict(r)
    boom = lua.eval("{place_dump_zone = function() error('kaput') end}")
    _, env, _ = acts(builder=boom, lua=lua)
    r = env.act_place_dump(lua.table_from({}))
    assert not r.ok and "kaput" in r.error, dict(r)
    _, env, _ = acts(builder=b, lua=lua)
    assert env.act_place_dump(lua.table_from({"inside": "yes"})).rejected


@test("bridge: mark_melt adds a melt work order when one is needed (not in a dry run); bad args refused")
def _():
    if not need_lua():
        return
    lua, env, made = acts()
    r = env.act_mark_melt(lua.table_from({"dry_run": True}))
    assert len(made) == 0 and not r.melt_order, dict(r)
    r = env.act_mark_melt(lua.table_from({}))
    assert r.ok and r.melt_order == 77 and r.order_added == 4 and made[1].recipe == "melt_metal", dict(r)
    assert env.act_unforbid_items(lua.table_from({"reasons": lua.table_from(["ai"])})).rejected
    assert env.act_unforbid_items(lua.table_from({"max": 9999})).rejected
    r = env.act_unforbid_items(lua.table_from({"reasons": lua.table_from(["unknown"]), "player_items": True, "max": 5}))
    assert r.ok and r.opts.player_items is True and r.opts.max == 5


if __name__ == "__main__":
    finish(None if LuaRuntime else "lupa is not installed")
