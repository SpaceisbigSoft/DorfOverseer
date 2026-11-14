"""(0.105.45, Phase 11 "fighting back") Hunting, the Lua side: lua/ai-hunt.lua
in a fake fort (the targets picked and left out, the way there by DF's walk
groups, the AI's cavern seals and shut gates, workers near, the squads'
strength and bows, the hunts and their history kept in the save and capped,
the report closing a hunt whose target died or left), hunt_send and
hunt_recall (checks, dry runs, the kill order through ai-military's orders()),
and the wiring (the section, its digest default, the actions, DRY_OK, the
overseer's words).

    python tests/test_hunt.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from digest import normalize, SECTION_DEFAULTS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"

FAKE = r"""
local src = ...
local W = {units = {}, citizens = {}, site = {}, squads = {}, fort_squads = {}, hfs = {}, groups = {},
           outside_z = 150, sealed = {}, gates_closed = {}, calls = {}}
local env = setmetatable({}, {__index = _G})
local function key(x, y, z) return x .. ',' .. y .. ',' .. z end
function W.unit(t)
    t.f = t.f or {}
    t.pos = t.pos or {x = 50, y = 50, z = 100}
    t.flags1 = t.flags1 or {caged = false, chained = false}
    t.race, t.caste = t.race or 1, t.caste or 0
    t.body = t.body or {size_info = {size_cur = 60000}, blood_count = 100, blood_max = 100}
    t.enemy = t.enemy or {caste_flags = {FLIER = t.f.flier == true}}
    t.path = t.path or {goal = 0}
    t.profession = t.profession or 0
    t.inventory = t.inventory or {}
    if t.f.active == nil then t.f.active = true end
    table.insert(W.units, t)
    if t.f.citizen then table.insert(W.citizens, t) end
    if t.group then W.groups[key(t.pos.x, t.pos.y, t.pos.z)] = t.group end
    return t
end
function W.squad(t)
    t.positions = t.positions or {}
    t.orders = t.orders or {}
    for i, u in ipairs(t.members or {}) do
        local hf = 1000 + u.id
        W.hfs[hf] = {unit_id = u.id}
        table.insert(t.positions, {occupant = hf})
    end
    W.squads[t.id] = t
    table.insert(W.fort_squads, t.id)
    return t
end
local M = {}
function M.fort_squad(id)
    for _, s in ipairs(W.fort_squads) do if s == id then return W.squads[id] end end
end
function M.squad_power(sq) return {power = sq.power or 5, armed = sq.armed or 0, armored = sq.armored or 0} end
function M.kill_target_ok(u)
    return (u.f.danger or u.f.invader or u.f.interrupter or u.f.wild) and true or false
end
function M.ai_order(o) return o.title == 'AI overseer' or o.shelter == true end
function M.shelter_marks() return {} end
function M.is_shelter_order(o) return o.shelter == true end
function M.orders(id, kill, clear)
    table.insert(W.calls, {id = id, kill = kill, clear = clear})
    local sq = M.fort_squad(id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad'} end
    local function drop()
        local n = 0
        for i = #sq.orders, 1, -1 do
            if M.ai_order(sq.orders[i]) then table.remove(sq.orders, i); n = n + 1 end
        end
        return n
    end
    if clear then return {ok = true, cleared = drop()} end
    drop()
    table.insert(sq.orders, {kind = 'kill', units = kill, title = 'AI overseer'})
    return {ok = true, targets = #kill}
end
local T = {}
function T.thief_kind(prof, goal)
    if prof == 'THIEF' or goal == 'ThiefTarget' then return 'thief' end
    if prof == 'SNATCHER' then return 'snatcher' end
end
function T.interrupting(u) return u.f.interrupter == true end
function T.fire_breath_of(race) if race == 9 then return 'breath' end return false end
function T.load_state() return {sealed = W.sealed} end
env.reqscript = function(name)
    if name == 'ai-military' then return M end
    if name == 'ai-threats' then return T end
    if name == 'ai-gates' then return {GATES = {closed = W.gates_closed}} end
    if name == 'ai-builder' then return {hostile_wild = function(u) return u.f.wild == true end} end
    error('no module ' .. tostring(name))
end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {
    global = {cur_year = 300, cur_year_tick = 0, world = {units = {active = W.units}},
              plotinfo = {group_id = 7}},
    historical_entity = {find = function() return {squads = W.fort_squads} end},
    historical_figure = {find = function(id) return W.hfs[id] end},
    squad = {find = function(id) return W.squads[id] end},
    unit = {find = function(id) for _, u in ipairs(W.units) do if u.id == id then return u end end end},
    squad_order_kill_listst = {is_instance = function(_, o) return o.kind == 'kill' end},
    profession = {[0] = 'DRUNK', [1] = 'THIEF', [2] = 'SNATCHER'},
    unit_path_goal = {[0] = 'None', [1] = 'ThiefTarget'},
    item_type = {WEAPON = 1, AMMO = 2, QUIVER = 3},
}
local function p(name) return function(u) return u.f[name] == true end end
env.dfhack = {
    df2utf = function(s) return s end,
    units = {isDead = p('dead'), isActive = function(u) return u.f.active == true end, isHidden = p('hidden'),
             isCitizen = p('citizen'), isResident = p('resident'), isMerchant = p('merchant'),
             isDiplomat = p('diplomat'), isTame = p('tame'), isPet = p('pet'), isAnimal = p('animal'),
             isFortControlled = p('fort'), isVisitor = p('visitor'), isDanger = p('danger'),
             isInvader = p('invader'), isGreatDanger = p('great'),
             isForgottenBeast = p('fb'), isTitan = p('titan'), isUndead = p('undead'),
             isMegabeast = p('mega'), isSemiMegabeast = p('semi'), isNightCreature = p('night'), isDemon = p('demon'),
             getCitizens = function() return W.citizens end,
             getReadableName = function(u) return u.name or ('unit ' .. u.id) end},
    maps = {getWalkableGroup = function(pos) return W.groups[key(pos.x, pos.y, pos.z)] or 0 end,
            getTileFlags = function(x, y, z) return {outside = z >= W.outside_z} end,
            getTileBlock = function(x, y, z) return {global_feature = (z < 50) and 1 or -1} end},
    military = {getSquadName = function(id) return 'Squad ' .. id end},
    items = {getContainedItems = function(it) return it.contents or {} end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
assert(load(src, 'ai-hunt', 't', env))()
W.layers = {by_gid = {[1] = {name = 'Cavern1'}}, top_z = 60}
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-hunt.lua"))
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


def unit(lua, w, **kw):
    return w.unit(T(lua, kw))


def report(lua, env, w):
    return py(env.report(None, lua.table_from({"layers": w.layers})))


def advance(env, ticks):
    g = env.df["global"]
    g.cur_year_tick = g.cur_year_tick + ticks


def armed_soldier(lua, w, uid, pos=None, bow=False, hurt=False):
    inv = []
    if bow:
        inv = [{"item": {"t": 1, "subtype": {"ranged_ammo": "BOLT"}}},
               {"item": {"t": 3, "contents": [{"bolt": True}]}}]
    u = unit(lua, w, id=uid, name=f"Soldier {uid}", f={"citizen": True}, group=1,
             pos=pos or {"x": 10, "y": 10, "z": 100}, inventory=inv)
    # each item's getType, as DF's items have
    lua.execute("""local u = ...
        for _, inv in ipairs(u.inventory) do local t = inv.item.t; inv.item.getType = function() return t end end""", u)
    if hurt:
        u.body.blood_count = 50
    return u


def fort(lua, w):
    """Citizens in group 1 at z100; a forgotten beast in the cavern (group 2),
    a goblin at the gate (group 1), a thief, an ambusher, a wild hostile, a
    wounded interrupting visitor; and those never targeted."""
    for i in range(1, 6):
        unit(lua, w, id=i, f={"citizen": True}, group=1, pos={"x": 10 + i, "y": 10, "z": 100})
    unit(lua, w, id=100, name="Beast", race=9, f={"danger": True, "great": True, "fb": True},
         pos={"x": 40, "y": 40, "z": 30}, group=2)
    unit(lua, w, id=101, name="Goblin", f={"danger": True, "invader": True}, pos={"x": 20, "y": 12, "z": 101}, group=1)
    unit(lua, w, id=102, name="Thief", profession=1, f={}, pos={"x": 60, "y": 60, "z": 155}, group=3)
    unit(lua, w, id=103, name="Lurker", flags1={"caged": False, "chained": False, "hidden_ambusher": True},
         f={"invader": True}, pos={"x": 70, "y": 70, "z": 155}, group=3)
    unit(lua, w, id=104, name="Bear", f={"wild": True}, pos={"x": 80, "y": 80, "z": 155}, group=1)
    unit(lua, w, id=105, name="Beaten visitor", f={"visitor": True, "interrupter": True},
         body={"size_info": {"size_cur": 70000}, "blood_count": 40, "blood_max": 100},
         pos={"x": 12, "y": 11, "z": 100}, group=1)
    # never targets
    unit(lua, w, id=200, name="Merchant", f={"merchant": True, "danger": True})
    unit(lua, w, id=201, name="Diplomat", f={"diplomat": True})
    unit(lua, w, id=202, name="Dog", f={"tame": True, "animal": True, "fort": True, "danger": True})
    unit(lua, w, id=203, name="Resident", f={"resident": True, "danger": True})
    unit(lua, w, id=204, name="Visitor", f={"visitor": True})
    unit(lua, w, id=205, name="Unhurt blocker", f={"visitor": True, "interrupter": True})
    unit(lua, w, id=206, name="Caged beast", flags1={"caged": True}, f={"danger": True, "great": True})
    unit(lua, w, id=207, name="Hidden", f={"danger": True, "hidden": True})
    unit(lua, w, id=208, name="Dead", f={"danger": True, "dead": True})
    unit(lua, w, id=209, name="Gone", f={"danger": True, "active": False})


# --- 1. the pure parts ---------------------------------------------------------------

@test("target_ok: threats, thieves, ambushers, wild hostiles and a wounded interrupting visitor yes; the rest no")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    ok = lambda **f: env.target_ok(T(lua, f))[0]  # noqa: E731
    assert ok(danger=True) and ok(invader=True) and ok(thief=True) and ok(ambush=True) and ok(hostile_wild=True)
    assert ok(visitor=True, wounded=True, interrupter=True)
    assert not ok(visitor=True, interrupter=True) and not ok(visitor=True, wounded=True)
    for k in ("dead", "caged", "hidden", "citizen", "resident", "merchant", "diplomat", "tame", "fort_animal"):
        assert not ok(danger=True, **{k: True}), k
    assert not ok() and env.target_ok(T(lua, {"visitor": True}))[1] == "visitor"


@test("classify_route: same group ok (length rounded); a seal blocks a cavern target; a shut gate; no path")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    r = lambda **t: py(env.classify_route(T(lua, t)))  # noqa: E731
    assert r(group=1, main=1, region="surface", dist=12.4) == {"ok": True, "length": 12, "blocked_by": "none"}
    assert r(group=2, main=1, region="cavern", layer="Cavern1", sealed={"Cavern1": True}) == {"ok": False, "blocked_by": "seal"}
    assert r(group=1, main=1, region="cavern", layer="Cavern2", sealed={"all caverns": True})["blocked_by"] == "seal"
    assert r(group=2, main=1, region="cavern", layer="Cavern2", sealed={"Cavern1": True})["blocked_by"] == "no_path"
    assert r(group=3, main=1, region="surface", gate_shut=True) == {"ok": False, "blocked_by": "gate"}
    assert r(group=3, main=1, region="surface") == {"ok": False, "blocked_by": "no_path"}
    assert r(group=0, main=0, region="inside")["blocked_by"] == "no_path"


@test("pure helpers: the history capped (newest kept), the main group, region, workers near, targets ordered and capped")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    h = None
    for i in range(25):
        h = env.push_history(h, T(lua, {"n": i}), 20)
    assert [x["n"] for x in py(h)] == list(range(5, 25))
    assert env.main_group(T(lua, [0, 2, 1, 2, 1, 2, 0, 0])) == 2 and env.main_group(T(lua, [0, 0])) == 0
    assert env.region_of("Cavern2", True) == "cavern" and env.region_of("upper_levels", True) == "surface"
    assert env.region_of("upper_levels", False) == "inside" and env.region_of(None, False) == "inside"
    by_z = T(lua, {100: [{"x": 10, "y": 10}, {"x": 31, "y": 10}], 103: [{"x": 15, "y": 15}], 104: [{"x": 10, "y": 10}]})
    assert env.count_near(T(lua, {"x": 10, "y": 10, "z": 100}), by_z) == 2
    rows = [{"id": i, "great_danger": i == 7, "can_reach_dwarves": i == 3, "near_workers": i} for i in range(1, 70)]
    out = py(env.order_targets(T(lua, rows), 60))
    assert len(out) == 60 and out[0]["id"] == 7 and out[1]["id"] == 3 and out[2]["id"] == 69


# --- 2. the report -----------------------------------------------------------------------

@test("report: the contract's shape; every target and no forbidden one; route, region, layer, fire, flags")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w)
    w.sealed = T(lua, {})
    r = report(lua, env, w)
    assert set(r) >= {"targets", "squads", "hunts", "history"}
    by = {t["id"]: t for t in r["targets"]}
    assert set(by) == {100, 101, 102, 103, 104, 105}, sorted(by)
    keys = {"id", "name", "kinds", "great_danger", "size", "pos", "layer", "region", "flier", "fire_breather",
            "ambush", "thief", "wounded_visitor", "route", "near_workers", "seen_ticks"}
    for t in r["targets"]:
        assert keys <= set(t), (t["id"], keys - set(t))
        assert {"ok", "blocked_by"} <= set(t["route"])
    assert r["targets"][0]["id"] == 100          # the great one first
    b = by[100]
    assert b["kinds"] == ["ForgottenBeast"] and b["great_danger"] is True and b["fire_breather"] is True
    assert b["layer"] == "Cavern1" and b["region"] == "cavern" and b["route"]["blocked_by"] == "no_path"
    assert b["can_reach_dwarves"] is False and b["near_workers"] == 0
    g = by[101]
    assert g["route"]["ok"] is True and isinstance(g["route"]["length"], int) and g["region"] == "inside"
    assert g["can_reach_dwarves"] is True and g["near_workers"] >= 4 and g["fire_breather"] is False
    assert by[102]["thief"] is True and by[102]["region"] == "surface" and by[102]["layer"] == "upper_levels"
    assert by[103]["ambush"] is True and by[104]["route"]["ok"] is True
    assert by[105]["wounded_visitor"] is True and by[100]["wounded_visitor"] is False
    assert by[101]["seen_ticks"] == 0


@test("report: the seal and a shut gate block the way; seen_ticks grows; a target gone is forgotten")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w)
    w.sealed["all caverns"] = T(lua, {"ids": [1]})
    w.gates_closed[3] = True
    r = report(lua, env, w)
    by = {t["id"]: t for t in r["targets"]}
    assert by[100]["route"] == {"ok": False, "blocked_by": "seal"}
    assert by[102]["route"]["blocked_by"] == "gate"
    advance(env, 600)
    lua.execute("local u = ... ; u.f.dead = true", env.df.unit.find(101))
    r = report(lua, env, w)
    by = {t["id"]: t for t in r["targets"]}
    assert by[100]["seen_ticks"] == 600 and 101 not in by
    assert "101" not in py(w.site["ai-overseer/hunts"])["seen"]


@test("report: the squads: soldiers, power, armed, ranged (bow and bolts), at home, sheltering, hunting")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w)
    a = [armed_soldier(lua, w, 300 + i, bow=i < 2) for i in range(3)]
    b = [armed_soldier(lua, w, 310 + i, pos={"x": 5, "y": 5, "z": 160}) for i in range(2)]
    w.squad(T(lua, {"id": 1, "members": a, "armed": 3, "power": 9.5, "armored": 1}))
    w.squad(T(lua, {"id": 2, "members": b, "armed": 2, "orders": [{"shelter": True}]}))
    r = report(lua, env, w)
    sq = {q["id"]: q for q in r["squads"]}
    assert sq[1]["soldiers"] == 3 and sq[1]["power"] == 9.5 and sq[1]["armed"] == 3 and sq[1]["armored"] == 1
    assert sq[1]["ranged"] is True and sq[1]["at_home"] is True and sq[1]["sheltering"] is False
    assert sq[1].get("hunting") is None
    assert sq[2]["ranged"] is False and sq[2]["at_home"] is False and sq[2]["sheltering"] is True


# --- 3. the actions ------------------------------------------------------------------------

def two_squads(lua, w):
    a = [armed_soldier(lua, w, 300 + i) for i in range(3)]
    b = [armed_soldier(lua, w, 310 + i) for i in range(2)]
    w.squad(T(lua, {"id": 1, "members": a, "armed": 3}))
    w.squad(T(lua, {"id": 2, "members": b, "armed": 1}))
    w.squad(T(lua, {"id": 3, "members": [armed_soldier(lua, w, 320), armed_soldier(lua, w, 321)], "armed": 2,
                    "orders": [{"kind": "defend", "title": ""}]}))
    w.squad(T(lua, {"id": 4, "members": [armed_soldier(lua, w, 330), armed_soldier(lua, w, 331)], "armed": 2}))


@test("hunt_send: the rejects (no target, dead, caged, not a threat, no squad, the player's, under 2 armed); a dry run gives no order")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w)
    two_squads(lua, w)
    send = lambda sq, t, dry=False: py(env.send(T(lua, {"squad_ids": sq, "target_id": t}), dry))  # noqa: E731
    for tid in (999, 208, 206, 200, 201, 202, 203, 204):
        assert send([1], tid).get("rejected") is True, (tid, send([1], tid))
    assert "no squad" in send([9], 101)["error"]
    assert "your orders" in send([3], 101)["error"]
    assert "armed" in send([1, 2], 101)["error"]
    assert len(list(w.calls.keys())) == 0          # all-or-nothing: nothing sent
    r = send([1, 4], 101, True)
    assert r["ok"] and r["dry_run"] and [x["squad_id"] for x in r["would_send"]] == [1, 4]
    assert len(list(w.calls.keys())) == 0 and w.site["ai-overseer/hunts"] is None


@test("hunt_send: kill orders through ai-military orders(), the hunt kept; the report shows it and the squad hunting")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w)
    two_squads(lua, w)
    r = py(env.send(T(lua, {"squad_ids": [1, 4], "target_id": 101}), False))
    assert r["ok"] and r["sent"] == [1, 4]
    calls = py(w.calls)
    assert [c["kill"] for c in calls] == [[101], [101]]
    act = py(w.site["ai-overseer/hunts"])["active"]
    assert act["1"]["soldiers_at_start"] == 3 and act["1"]["since_tick"] == 300 * 403200
    lua.execute("local u = ... ; u.body.blood_count = 10", env.df.unit.find(301))
    rep = report(lua, env, w)
    h = {x["squad_id"]: x for x in rep["hunts"]}
    assert set(h) == {1, 4} and h[1]["target_alive"] is True and h[1]["soldiers_now"] == 3 and h[1]["wounded"] == 1
    assert h[1]["target_pos"] == {"x": 20, "y": 12, "z": 101}
    assert {"squad_id", "target_id", "since_tick", "soldiers_at_start", "soldiers_now", "wounded",
            "target_alive", "target_pos"} <= set(h[1])
    sq = {q["id"]: q for q in rep["squads"]}
    assert sq[1]["hunting"] == 101 and sq[1]["at_home"] is False


@test("the report closes hunts: target dead (won, soldiers lost counted), left the map (gone), order dropped")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w)
    two_squads(lua, w)
    env.send(T(lua, {"squad_ids": [1], "target_id": 101}), False)
    env.send(T(lua, {"squad_ids": [4], "target_id": 104}), False)
    lua.execute("local a, b = ... ; a.f.dead = true; b.f.dead = true", env.df.unit.find(101), env.df.unit.find(300))
    rep = report(lua, env, w)
    hist = rep["history"]
    assert len(hist) == 1 and hist[0]["outcome"] == "won" and hist[0]["soldiers_lost"] == 1 and hist[0]["target_dead"]
    assert [x["squad_id"] for x in rep["hunts"]] == [4]
    lua.execute("local u = ... ; u.f.active = false", env.df.unit.find(104))
    rep = report(lua, env, w)
    assert rep["history"][-1]["outcome"] == "gone" and not rep["hunts"]
    # an order cleared by another rule: the hunt is dropped
    assert py(env.send(T(lua, {"squad_ids": [4], "target_id": 103}), False))["ok"]
    lua.execute("local sq = ... ; for i = #sq.orders, 1, -1 do table.remove(sq.orders, i) end", w.squads[4])
    rep = report(lua, env, w)
    assert rep["history"][-1]["outcome"] == "dropped"


@test("hunt_recall: by squads or by target, orders cleared, outcome and reason kept; dry run changes nothing; history capped at 20")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w)
    two_squads(lua, w)
    env.send(T(lua, {"squad_ids": [1, 4], "target_id": 100}), False)
    r = py(env.recall(T(lua, {"target_id": 100, "reason": "too strong"}), True))
    assert r["dry_run"] and [x["squad_id"] for x in r["would_recall"]] == [1, 4]
    assert set(py(w.site["ai-overseer/hunts"])["active"]) == {"1", "4"}
    r = py(env.recall(T(lua, {"target_id": 100, "reason": "too strong"}), False))
    assert r["ok"] and r["recalled"] == [1, 4]
    assert all(c.get("clear") for c in py(w.calls)[-2:]) and len(py(w.squads[1].orders) or []) == 0
    d = py(w.site["ai-overseer/hunts"])
    assert not d["active"] and d["history"][-1]["outcome"] == "recalled" and d["history"][-1]["reason"] == "too strong"
    assert d["history"][-1]["target_dead"] is False
    assert py(env.recall(T(lua, {"target_id": 100}), False))["rejected"] is True
    assert py(env.recall(T(lua, {}), False))["rejected"] is True
    assert py(env.recall(T(lua, {"squad_ids": [9]}), False))["rejected"] is True
    for _ in range(25):
        env.send(T(lua, {"squad_ids": [1], "target_id": 101}), False)
        env.recall(T(lua, {"squad_ids": [1]}), False)
    rep = report(lua, env, w)
    assert len(rep["history"]) == 20 and len(py(w.site["ai-overseer/hunts"])["history"]) == 20


@test("hunt_send at another target: the old hunt closed (recalled), the new one kept")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fort(lua, w)
    two_squads(lua, w)
    env.send(T(lua, {"squad_ids": [1], "target_id": 101}), False)
    env.send(T(lua, {"squad_ids": [1], "target_id": 104}), False)
    d = py(w.site["ai-overseer/hunts"])
    assert d["active"]["1"]["target_id"] == 104 and d["history"][-1]["target_id"] == 101


# --- 4. the wiring ----------------------------------------------------------------------------

@test("bridge: the hunt section (safe), hunt_send / hunt_recall in ACTIONS and DRY_OK, ai-hunt listed; digest default; words")
def _():
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    sections = src[src.index("SECTIONS = {"):src.index("PULSE_SECTIONS = {")]
    assert "hunt = function()" in sections and "reqscript('ai-hunt').report(txt" in sections
    i = sections.index("hunt = function()")
    assert "safe(function()" in sections[i:i + 200]
    actions = src[src.index("ACTIONS = {"):src.index("DRY_OK = {}")]
    assert "hunt_send = function(a)" in actions and "reqscript('ai-hunt').send" in actions
    assert "hunt_recall = function(a)" in actions and "reqscript('ai-hunt').recall" in actions
    dry = src[src.index("DRY_OK = {}"):src.index("}) do DRY_OK[name] = true end")]
    assert "'hunt_send'" in dry and "'hunt_recall'" in dry
    mods = src[src.index("BRIDGE_MODULES = {"):src.index("}", src.index("BRIDGE_MODULES = {"))]
    assert "'ai-hunt'" in mods
    assert SECTION_DEFAULTS["hunt"] == {"targets": [], "squads": [], "hunts": []}
    s = normalize({"hunt": {"error": "boom"}})
    assert s["hunt"] == {"targets": [], "squads": [], "hunts": []}
    import overseer
    assert overseer.SHORT_WORDS["hunt_send"].startswith("hunt:")
    assert overseer.SHORT_WORDS["hunt_recall"].startswith("hunt back:")
    mil = (LUA_DIR / "ai-military.lua").read_text(encoding="utf-8")
    assert "function ai_order(o, squad_id) return is_ai_order(o, squad_id) end" in mil


@test("bridge: the handlers check their arguments (ids whole numbers, 1-10 squads, squads or a target)")
def _():
    if LuaRuntime is None:
        return
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
        GOT = nil
        function reject(r) return {ok = false, rejected = true, error = r} end
        function whole_number(v) return math.tointeger(tonumber(v)) end
        function reqscript() return {send = function(o, dry) GOT = {o = o, dry = dry}; return {ok = true} end,
                                     recall = function(o, dry) GOT = {o = o, dry = dry}; return {ok = true} end} end
    """)

    def handler(name):
        i = src.index(f"    {name} = function(a)")
        j = src.index("\n    end,\n", i) + len("\n    end,\n")
        return lua.execute(src[i:j].strip().rstrip(",").replace(f"{name} = function(a)", "return function(a)", 1))

    hs, hr = handler("hunt_send"), handler("hunt_recall")
    assert hs(T(lua, {"squad_ids": [1]}))["rejected"] is True
    assert hs(T(lua, {"target_id": 5}))["rejected"] is True
    assert hs(T(lua, {"target_id": 5, "squad_ids": [1.5]}))["rejected"] is True
    assert hs(T(lua, {"target_id": 5, "squad_ids": list(range(11))}))["rejected"] is True
    assert hs(T(lua, {"target_id": 5.0, "squad_ids": [1, 2], "dry_run": True}))["ok"] is True
    got = lua.globals().GOT
    assert py(got.o) == {"squad_ids": [1, 2], "target_id": 5} and got.dry is True
    assert hr(T(lua, {}))["rejected"] is True
    assert hr(T(lua, {"target_id": "x"}))["rejected"] is True
    assert hr(T(lua, {"target_id": 7, "reason": "lost two"}))["ok"] is True
    got = lua.globals().GOT
    assert py(got.o) == {"target_id": 7, "reason": "lost two"} and got.dry is False


if __name__ == "__main__":
    finish()
