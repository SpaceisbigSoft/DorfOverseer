"""(0.105.45) A great beast sealed in a cavern, lured in and cut off:
lua/ai-lure.lua in a fake fort (the pocket planned behind one of the AI's
cavern doors; build_lure's pieces, levers and links; lure_open's safety
refusals; lure_shut and what it notes), the seal's and the watcher's
respect for a lure's door (ai-threats, ai-gates-watch, planner_threats), the
wiring, and brain/planner_lure.py's phase machine and back-off.

    python tests/test_lure.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import code_has, finish, test  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG  # noqa: E402
import planner_lure as PL  # noqa: E402
import planner_threats as PT  # noqa: E402
from digest import SECTION_DEFAULTS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
DAY = 1200

# A fake fort: tiles by "x,y,z" (floor, cavern floor, wall by default),
# buildings by tile, citizens, one beast, the threats' and the gates' records.
FAKE = r"""
local src = ...
local W = {tiles = {}, blds = {}, by_id = {}, citizens = {}, units = {}, site = {}, placed = {}, pulls = {},
           links = {}, openings = {}, seal_ids = {}, mech = 20, next_id = 100, lever_spot = {x = 1, y = 1, z = 0}}
local env = setmetatable({}, {__index = _G})
local function k(x, y, z) return x .. ',' .. y .. ',' .. z end
function W.floor(x, y, z, t)
    t = t or {}
    W.tiles[k(x, y, z)] = {walk = true, shape = t.shape or 'FLOOR', cavern = t.cavern or false,
                           outside = false, hidden = false, liquid = false, occupied = t.occupied or false}
end
function W.building(kind, x, y, z, t)
    t = t or {}
    W.next_id = W.next_id + 1
    local b = {id = t.id or W.next_id, kind = kind, x1 = x, x2 = x, y1 = y, y2 = y, z = z, name = '',
               stage = t.stage or 1, door_flags = {forbidden = t.locked or false, closed = false},
               gate_flags = {raised = t.raised or false, raising = false, lowering = false},
               contained_items = t.items or {}}
    b.getType = function() return kind end
    b.getBuildStage = function(self) return self.stage end
    b.getMaxBuildStage = function() return 1 end
    W.blds[k(x, y, z)] = b
    W.by_id[b.id] = b
    if W.tiles[k(x, y, z)] then W.tiles[k(x, y, z)].occupied = true end
    return b
end
function W.citizen(id, x, y, z)
    local u = {id = id, pos = {x = x, y = y, z = z}, flags1 = {}}
    table.insert(W.citizens, u)
    return u
end
function W.beast(id, x, y, z, t)
    t = t or {}
    local u = {id = id, pos = {x = x, y = y, z = z}, flags1 = {caged = t.caged or false},
               enemy = {caste_flags = {TRAPAVOID = t.immune or false}}, race = 1, caste = 0, fb = true}
    W.units[id] = u
    return u
end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.COLOR_YELLOW, env.COLOR_GREEN = 14, 10
env.df = {
    global = {cur_year = 300, cur_year_tick = 0, world = {units = {active = {}}}},
    building_type = setmetatable({}, {__index = function(_, v) return v end}),
    item_type = {CAGE = 'CAGE'},
    general_ref_type = {CONTAINS_UNIT = 'CONTAINS_UNIT'},
    unit = {find = function(id) return W.units[id] end},
    building = {find = function(id) return W.by_id[id] end},
    creature_raw = {find = function() return nil end},
}
env.df.global.world.units.active = setmetatable({}, {__index = function(_, i)
    local list = {}
    for _, u in pairs(W.units) do table.insert(list, u) end
    table.sort(list, function(a, b) return a.id < b.id end)
    return list[i]
end})
env.dfhack = {
    df2utf = function(s) return s end,
    units = {isDead = function(u) return u.dead == true end,
             getCitizens = function() local out = {}; for i, u in ipairs(W.citizens) do out[i] = u end; return out end,
             getReadableName = function(u) return u.name or ('unit ' .. u.id) end,
             isForgottenBeast = function(u) return u.fb == true end,
             isTitan = function() return false end, isMegabeast = function() return false end,
             isDemon = function() return false end},
    buildings = {findAtTile = function(p) return W.blds[k(p.x, p.y, p.z)] end},
    maps = {getTileFlags = function(x, y, z)
        local t = W.tiles[k(x, y, z)]
        return {feature_global = t and t.cavern or false, feature_local = false}
    end},
    items = {getGeneralRef = function(it, _) return it.unit end},
    gui = {showAnnouncement = function() end},
    persistent = {getSiteData = function(key, d) local v = W.site[key]; if v == nil then return d end return v end,
                  saveSiteData = function(key, v) W.site[key] = v end},
}
local THREATS = {
    load_state = function() return {openings = W.openings} end,
    seal_holds = function() local ids = {}; for _, id in ipairs(W.seal_ids) do ids[id] = true end; return {ids = ids} end,
}
local GATES = {
    free_mechanism_count = function() return W.mech end,
    lever_links = function() return W.links end,
    lever_spot = function()
        W.lever_spot = {x = W.lever_spot.x + 1, y = 1, z = 0}
        return W.lever_spot
    end,
    ai_planned_building = function() return false end,
    deep_road_keys = function() return {} end,
    fort_starts = function(s) return s end,
    link_lever = function(lid, bid)
        W.links[bid] = W.links[bid] or {}
        table.insert(W.links[bid], lid)
        return {ok = true}
    end,
    pull_instant = function(lid)
        table.insert(W.pulls, lid)
        for bid, ls in pairs(W.links) do
            for _, l in ipairs(ls) do
                if l == lid then local b = W.by_id[bid]; b.gate_flags.raised = not b.gate_flags.raised end
            end
        end
        return true
    end,
    bridge_occupied = function() return false end,
}
env.reqscript = function(name)
    if name == 'ai-threats' then return THREATS end
    if name == 'ai-gates' then return GATES end
    if name == 'ai-builder' then return {registry_report = function() return W.registry or {} end} end
    error('no module ' .. tostring(name))
end
assert(load(src, 'ai-lure', 't', env))()
env.tile_hook = function(x, y, z) return W.tiles[k(x, y, z)] end
local kinds = {Tc = 'Trap', d = 'Door', Tl = 'Trap'}
env.place_hook = function(text, p)
    table.insert(W.placed, text .. '@' .. k(p.x, p.y, p.z))
    local kind = kinds[text] or (text:match('^g') and 'Bridge') or 'Other'
    W.building(kind, p.x, p.y, p.z, {stage = 0})
    return true
end
return env, W
"""


LUA = None


def world():
    global LUA
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-lure.lua"))
    LUA = lua
    return lua, env, w


def L(d):
    """A Python dict as a Lua table, in the last world made."""
    return T(LUA, d)


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


def corridor(w, length=8, room=True, z=0):
    """The cavern east of a door at x10 y5; a 1-wide way west of it (x9 down
    to x10-length), opening into a 3x3 room past its end."""
    for x in range(11, 15):
        for y in range(3, 8):
            w.floor(x, y, z, L({"cavern": True}))
    w.floor(10, 5, z)                               # the door's tile
    for i in range(1, length + 1):
        w.floor(10 - i, 5, z)
    if room:
        end = 10 - length
        for x in range(end - 3, end):
            for y in range(4, 7):
                w.floor(x, y, z)


def plan(lua, env, w, immune=False, **opts):
    o = T(lua, {"x": 10, "y": 5, "z": 0})
    res = env.plan_pocket(o, env.tile_hook, T(lua, dict(opts, immune=immune)))
    p, why = res if isinstance(res, tuple) else (res, None)
    return py(p), why


SKIP = LuaRuntime is None


# --- 1. the pocket planner (pure) ------------------------------------------------------

@test("plan_pocket: a long 1-wide way behind the door: 6 tiles of cage traps, the inner door on the 7th")
def _():
    if SKIP:
        return
    lua, env, w = world()
    corridor(w, 8)
    p, why = plan(lua, env, w)
    assert p, why
    assert p["length"] == 6 and [t["x"] for t in p["tiles"]] == [9, 8, 7, 6, 5, 4], p
    assert len(p["traps"]) == 6 and p["inner"] == {"x": 3, "y": 5, "z": 0, "kind": "door"}, p
    assert "mouth" not in p and p["immune"] is False


@test("plan_pocket: a way of 4 then a room: a pocket of 3, its inner door on the last 1-wide tile")
def _():
    if SKIP:
        return
    lua, env, w = world()
    corridor(w, 4)
    p, why = plan(lua, env, w)
    assert p, why
    assert p["length"] == 3 and p["inner"]["x"] == 6, p


@test("plan_pocket: too short, wider than one tile, no cavern beside it, a cavern leak: no pocket, and why")
def _():
    if SKIP:
        return
    lua, env, w = world()
    corridor(w, 3)                                  # 3 tiles 1-wide: 2 pocket + gate
    p, why = plan(lua, env, w)
    assert p is None and "only 2" in why, why
    lua, env, w = world()
    corridor(w, 8)
    w.floor(9, 4, 0)                                # a second floor behind the door
    p, why = plan(lua, env, w)
    assert p is None and "wider" in why, why
    lua, env, w = world()
    corridor(w, 8)
    for x in range(11, 15):
        for y in range(3, 8):
            w.floor(x, y, 0)                        # not a cavern: no cavern floor beside the door
    p, why = plan(lua, env, w)
    assert p is None and "no cavern" in why, why
    lua, env, w = world()
    corridor(w, 8)
    w.floor(8, 4, 0, L({"cavern": True}))              # cavern floor touching the pocket: a way round the door
    p, why = plan(lua, env, w)
    assert p is None, p


@test("plan_pocket: a trap-immune beast: drawbridges at the mouth and as the inner gate, no traps")
def _():
    if SKIP:
        return
    lua, env, w = world()
    corridor(w, 8)
    p, why = plan(lua, env, w, immune=True)
    assert p, why
    assert p["immune"] and p["traps"] == [] if isinstance(p["traps"], list) else p["immune"], p
    assert p["mouth"]["kind"] == "bridge" and p["mouth"]["x"] == 9 and p["mouth"]["dir"] == "gd", p
    assert p["inner"]["kind"] == "bridge" and p["inner"]["x"] == 3 and p["inner"]["dir"] == "gd", p
    assert env.mechanisms_needed(T(lua, {"traps": [], "mouth": p["mouth"], "inner": p["inner"]})) == 6


@test("plan_pocket: not on a level without the AI's projects; never over the depot road or anyone's building")
def _():
    if SKIP:
        return
    lua, env, w = world()
    corridor(w, 8)
    p, why = plan(lua, env, w, levels={5: True})
    assert p is None and "level" in why, why
    p, _ = plan(lua, env, w, levels={0: True})
    assert p and p["length"] == 6
    # a building on the 3rd tile: the chain stops before it (2 tiles: too short)
    lua, env, w = world()
    corridor(w, 8)
    w.building("Chair", 7, 5, 0)
    p, why = plan(lua, env, w)
    assert p is None, p
    # ...unless it is the lure's own piece
    p, why = plan(lua, env, w, own={"7,5,0": True})
    assert p and p["length"] == 6, why
    lua, env, w = world()
    corridor(w, 8)
    road = (0 * 4096 + 5) * 4096 + 7
    p, why = plan(lua, env, w, avoid={road: True})
    assert p is None, p


@test("phase_of: idle, building, ready, open, caught, shut_in, done")
def _():
    if SKIP:
        return
    lua, env, w = world()
    f = lambda **r: env.phase_of(T(lua, r))  # noqa: E731
    assert f() == "idle" and f(planned=True) == "building" and f(planned=True, built=True) == "ready"
    assert f(planned=True, built=True, open=True) == "open"
    assert f(planned=True, built=True, open=True, caught=True) == "caught"
    assert f(planned=True, built=True, in_pocket=True, shut=True) == "shut_in"
    assert f(planned=True, built=True, done=True, caught=True) == "done"


# --- 2. the actions in the fake fort ---------------------------------------------------

def held_door(lua, w, locked=True):
    door = w.building("Door", 10, 5, 0, L({"locked": locked, "id": 7}))
    w.openings["10,5,0"] = T(lua, {"x": 10, "y": 5, "z": 0, "kind": "gate", "source": "cavern entrance 1"})
    w.seal_ids[1] = 7
    return door


def built_pocket(lua, env, w, immune=False):
    corridor(w, 8)
    held_door(lua, w)
    w.beast(50, 13, 5, 0, L({"immune": immune}))
    r = py(env.build_lure("10,5,0", 50, False))
    assert r["ok"] and r["placed"] >= 1, r
    for b in list(w.blds.values()):
        b.stage = 1                                   # the dwarves build everything
    if immune:
        r = py(env.build_lure("10,5,0", None, False))   # the levers' links once all is built
        for b in list(w.blds.values()):
            b.stage = 1
        r = py(env.build_lure("10,5,0", None, False))
    return r


@test("build_lure: only behind a door the AI holds; a dry run plans and places nothing; too few mechanisms wait")
def _():
    if SKIP:
        return
    lua, env, w = world()
    corridor(w, 8)
    w.beast(50, 13, 5, 0)
    r = py(env.build_lure("10,5,0", 50, False))
    assert r["rejected"] and "holds" in r["error"], r
    held_door(lua, w)
    r = py(env.build_lure("10,5,0", 50, True))
    assert r["ok"] and r["dry_run"] and r["traps"] == 6 and r["inner"] == "door", r
    assert len(w.placed) == 0 and not py(env.load_state())["lures"]
    w.mech = 3
    r = py(env.build_lure("10,5,0", 50, False))
    assert not r["ok"] and r["waiting"] and "mechanism" in r["error"], r


@test("build_lure: cage traps and the inner door placed; the report's row: building, then ready once built")
def _():
    if SKIP:
        return
    lua, env, w = world()
    corridor(w, 8)
    held_door(lua, w)
    w.beast(50, 13, 5, 0)
    r = py(env.build_lure("10,5,0", 50, False))
    assert r["ok"] and r["placed"] == 7, r
    assert sorted(w.placed.values()) == sorted([f"Tc@{x},5,0" for x in range(4, 10)] + ["d@3,5,0"]), py(w.placed)
    rep = py(env.report())
    row = rep["lures"][0]
    assert row["phase"] == "building" and row["traps"] == 6 and row["traps_built"] == 0 and not row["immune"], row
    assert rep["beasts"][0]["id"] == 50 and rep["beasts"][0]["cavern"] and rep["beasts"][0]["immune"] is False
    for b in list(w.blds.values()):
        b.stage = 1
    row = py(env.report())["lures"][0]
    assert row["phase"] == "ready" and row["built"] and row["inner"]["shut"] is False, row
    r = py(env.build_lure("10,5,0", None, False))
    assert r["ok"] and r["built"] and r["nothing_new"], r


@test("build_lure for a trap-immune beast: two drawbridges, a lever each (named), linked once built")
def _():
    if SKIP:
        return
    lua, env, w = world()
    r = built_pocket(lua, env, w, immune=True)
    rec = py(env.load_state())["lures"]["10,5,0"]
    assert rec["immune"] and rec["mouth"]["kind"] == "bridge" and rec["inner"]["kind"] == "bridge", rec
    assert set(rec["levers"]) == {"inner", "mouth"}, rec
    assert w.by_id[rec["levers"]["inner"]].name == "AI lure lever"
    row = py(env.report())["lures"][0]
    assert row["inner"]["linked"] and row["mouth"]["linked"] and row["phase"] == "ready", row


@test("lure_open refuses: unfinished, a citizen in the caverns, one beside the pocket, the inner gate open")
def _():
    if SKIP:
        return
    lua, env, w = world()
    corridor(w, 8)
    held_door(lua, w)
    w.beast(50, 13, 5, 0)
    env.build_lure("10,5,0", 50, False)
    r = py(env.lure_open("10,5,0", False))
    assert r["rejected"] and "not finished" in r["error"], r
    for b in list(w.blds.values()):
        b.stage = 1
    r = py(env.lure_open("10,5,0", False))
    assert r["rejected"] and "inner gate" in r["error"], r
    assert py(env.lure_shut("10,5,0", False))["ok"]           # the inner door locked (and the seal kept locked)
    assert w.blds["3,5,0"].door_flags.forbidden is True
    u = w.citizen(1, 12, 4, 0)                                 # down in the cavern
    r = py(env.lure_open("10,5,0", False))
    assert r["rejected"] and r["waiting"] and "caverns" in r["error"], r
    u.pos.x, u.pos.y = 2, 4                                    # out, but beside the inner door
    r = py(env.lure_open("10,5,0", False))
    assert r["rejected"] and "beside the pocket" in r["error"], r
    u.pos.x, u.pos.y = 0, 0
    r = py(env.lure_open("10,5,0", True))
    assert r["ok"] and r["dry_run"] and w.blds["10,5,0"].door_flags.forbidden is True, r
    assert py(env.lure_open("10,5,0", False))["ok"]
    assert w.blds["10,5,0"].door_flags.forbidden is False
    assert py(env.held_open()) == {7: True}
    row = py(env.report())["lures"][0]
    assert row["phase"] == "open" and row["open"], row
    r = py(env.lure_open("10,5,0", False))
    assert r["rejected"] and r["nothing_to_do"], r


@test("lure_open: a door on a lever is refused (the lure works only a locked door)")
def _():
    if SKIP:
        return
    lua, env, w = world()
    built_pocket(lua, env, w)
    env.lure_shut("10,5,0", False)
    w.links[7] = T(lua, [999])
    r = py(env.lure_open("10,5,0", False))
    assert r["rejected"] and "lever" in r["error"], r


@test("lure_shut: a caged beast noted caught (done); the seal locked; the pocket's pieces released")
def _():
    if SKIP:
        return
    lua, env, w = world()
    built_pocket(lua, env, w)
    env.lure_shut("10,5,0", False)
    assert py(env.lure_open("10,5,0", False))["ok"]
    assert 7 in py(env.held_ids())
    b = w.units[50]
    b.pos.x = 8
    b.flags1.caged = True
    row = py(env.report())["lures"][0]
    assert row["phase"] == "caught", row
    r = py(env.lure_shut("10,5,0", False))
    assert r["ok"] and r["caught"] == 50 and r["was_open"], r
    assert w.blds["10,5,0"].door_flags.forbidden is True
    row = py(env.report())["lures"][0]
    assert row["phase"] == "done" and row["done"]["how"] == "caught", row
    assert py(env.held_ids()) in ({}, None) and py(env.held_open()) in ({}, None)
    r = py(env.lure_open("10,5,0", False))
    assert r["rejected"] and r["nothing_to_do"], r


@test("lure_shut, trap-immune: the mouth raised behind the beast in the pocket: shut in, held")
def _():
    if SKIP:
        return
    lua, env, w = world()
    built_pocket(lua, env, w, immune=True)
    assert py(env.lure_shut("10,5,0", False))["ok"]           # both bridges raised
    rec = py(env.load_state())["lures"]["10,5,0"]
    assert w.by_id[w.blds["9,5,0"].id].gate_flags.raised and w.blds["3,5,0"].gate_flags.raised
    assert py(env.lure_open("10,5,0", False))["ok"]
    assert not w.blds["9,5,0"].gate_flags.raised and w.blds["3,5,0"].gate_flags.raised   # mouth down, inner up
    w.units[50].pos.x = 6                                      # walked in past the mouth
    row = py(env.report())["lures"][0]
    assert row["beast_in_pocket"] and row["phase"] == "open", row
    r = py(env.lure_shut("10,5,0", False))
    assert r["shut_in"] == 50, r
    assert w.blds["9,5,0"].gate_flags.raised and w.blds["10,5,0"].door_flags.forbidden is True
    rep = py(env.report())
    assert rep["held_beasts"] == [50] and rep["lures"][0]["phase"] == "done", rep
    assert rec["levers"]["mouth"] in py(w.pulls)
    # another beast: the pocket holding one is never retargeted
    w.beast(51, 13, 6, 0)
    r = py(env.build_lure("10,5,0", 51, False))
    assert r["rejected"] and "holds a beast" in r["error"], r


# --- 3. the seal and the watcher leave a lure's door to it -----------------------------

THREATS_SRC = (LUA_DIR / "ai-threats.lua").read_text(encoding="utf-8")
WATCH_SRC = (LUA_DIR / "ai-gates-watch.lua").read_text(encoding="utf-8")


@test("ai-threats: the openings report marks a lure's open door; seal_cavern leaves it unlocked")
def _():
    assert code_has(THREATS_SRC, "reqscript('ai-lure').held_open()")
    assert code_has(THREATS_SRC, "if row.id and lure[row.id] then row.lure_open = true end")
    assert code_has(THREATS_SRC, "for id in pairs(lure) do found[id] = nil end")


@test("ai-gates-watch: an entrance with a lure's piece is skipped by the watcher")
def _():
    assert code_has(WATCH_SRC, "reqscript('ai-lure').held_ids()")
    assert code_has(WATCH_SRC, "if lure[id] then goto continue end")


def seal_state(lure_open: bool, held=None):
    return {"date": {"year": 300, "tick": 0}, "map": {"elevation_offset": 0}, "settings": {},
            "deep": {"caverns": [{"name": "Cavern1", "open": True, "z_top": 20, "z_bottom": 10}],
                     "dangers": [{"id": 50, "name": "Ozkak", "kind": "forgotten beast", "layer": "Cavern1"}]},
            "lures": {"held_beasts": held or []},
            "threats": {"sealed": {"all caverns": {"doors": 1, "days": 9}},
                        "openings": {"list": [{"x": 10, "y": 5, "z": 0, "kind": "gate", "building": "Door",
                                               "id": 7, "built": True, "locked": False, "sealed": False,
                                               "lure_open": lure_open or None}]},
                        "cavern_citizens": {"n": 0, "list": []}}}


@test("planner_threats: a lure's open door is no unlocked opening (no re-seal); others are re-sealed")
def _():
    rules = PT.threat_rules_of({"settings": {}})
    for lure_open, want in ((True, False), (False, True)):
        s = seal_state(lure_open)
        props, notes = [], []
        PT._cavern_beasts(s, dict(PLANNER_CONFIG), Memory(), s["threats"], rules, props, notes)
        got = any(p.action.get("type") == "seal_cavern" and not p.action.get("open") for p in props)
        assert got is want, (lure_open, [p.action for p in props])


@test("planner_threats: a beast shut in a lure pocket is no cavern danger (the caverns can open again)")
def _():
    assert PT.cavern_great(seal_state(False))
    assert PT.cavern_great(seal_state(False, held=[50])) == []


# --- 4. wiring --------------------------------------------------------------------------

BRIDGE = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")


@test("bridge: the three actions, DRY_OK, the lures section (pulse too), the module listed")
def _():
    for a in ("build_lure", "lure_open", "lure_shut"):
        assert code_has(BRIDGE, f"{a} = function(a)"), a
    dry = BRIDGE[BRIDGE.index("DRY_OK = {}"):BRIDGE.index("}) do DRY_OK[name] = true end")]
    assert "'build_lure', 'lure_open', 'lure_shut'" in dry
    assert code_has(BRIDGE, "lures = function() return safe(function() return reqscript('ai-lure').report() end) end,")
    pulse = BRIDGE[BRIDGE.index("PULSE_SECTIONS = {"):BRIDGE.index("TIERS = ")]
    assert "'lures'" in pulse
    assert "'ai-lure'," in BRIDGE[BRIDGE.index("BRIDGE_MODULES = {"):BRIDGE.index("MARKED_MODULES")]


@test("brain: digest default, labels, config, Rules switch (settings, window, player_rules)")
def _():
    import overseer
    import planner_core
    assert SECTION_DEFAULTS.get("lures") == {}
    for a in ("build_lure", "lure_open", "lure_shut"):
        assert a in overseer.ACTION_LABELS if hasattr(overseer, "ACTION_LABELS") else a in Path(
            ROOT / "brain" / "overseer.py").read_text(encoding="utf-8"), a
    for k in ("lure_after_days", "lure_open_days", "lure_retry_days", "lure_retry_max_days",
              "lure_build_cooldown_ticks", "lure_open_cooldown_ticks", "lure_shut_cooldown_ticks"):
        assert k in PLANNER_CONFIG, k
    assert planner_core.player_rules({"settings": {}})["lure_beasts"] is True
    assert planner_core.player_rules({"settings": {"lure_beasts": False}})["lure_beasts"] is False
    st = (LUA_DIR / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    assert code_has(st, "lure_beasts = true,") and "'lure_beasts'," in st and code_has(st, "lure_beasts = s.lure_beasts,")
    gui = (LUA_DIR / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
    assert code_has(gui, "view_id = 'lure_beasts'") and code_has(gui, "self.subviews.lure_beasts:setOption(")


@test("ai-lure.lua compiles under Lua 5.3")
def _():
    if SKIP:
        return
    ok = LuaRuntime(unpack_returned_tuples=True).eval(
        "function(src) local f, e = load(src, 'ai-lure', 't', {}); return f ~= nil, e end")(
        (LUA_DIR / "ai-lure.lua").read_text(encoding="utf-8"))
    assert ok[0], ok


# --- 5. the phase machine and the back-off (brain/planner_lure.py) ---------------------

def lstate(rows=None, tick=0, sealed_days=9, beasts=None, cands=None, cave=0, settings=None, mech=20):
    return {"date": {"year": 300, "tick": tick}, "settings": settings or {},
            "threats": {"sealed": {"all caverns": {"doors": 1, "days": sealed_days}}},
            "deep": {"dangers": [{"id": 50, "kind": "forgotten beast", "layer": "Cavern1"}]},
            "military": {"squads": []},
            "lures": {"lures": rows or [], "cavern_citizens": cave, "mechanisms": mech, "held_beasts": [],
                      "beasts": beasts if beasts is not None else
                      [{"id": 50, "name": "Ozkak", "kind": "forgotten beast", "cavern": True, "immune": False}],
                      "candidates": cands if cands is not None else
                      [{"key": "10,5,0", "x": 10, "y": 5, "z": 0, "fits": True, "length": 6}]}}


def row(phase, **kw):
    r = {"key": "10,5,0", "opening": {"x": 10, "y": 5, "z": 0}, "phase": phase, "beast_id": 50, "beast_name": "Ozkak",
         "immune": False, "inner": {"kind": "door", "built": True, "shut": True}, "citizens_near": 0,
         "pieces": 7, "pieces_built": 7}
    r.update(kw)
    return r


def run(s, memory=None):
    props, notes = [], []
    PL._lure_rule(s, dict(PLANNER_CONFIG), props, notes, memory)
    return props, notes


def types(props):
    return [(p.rule, p.action.get("type")) for p in props]


@test("backoff_days: 0, then lure_retry_days doubled each try, up to the cap")
def _():
    cfg = dict(PLANNER_CONFIG, lure_retry_days=4, lure_retry_max_days=20)
    assert [PL.backoff_days(n, cfg) for n in range(5)] == [0, 4, 8, 16, 20]


@test("new lure: a beast sealed long enough, a door with room: build_lure for it; too soon or off: none")
def _():
    props, notes = run(lstate(sealed_days=9))
    assert types(props) == [("lure_build", "build_lure")] and props[0].action == {
        "type": "build_lure", "opening": "10,5,0", "beast": 50}, [p.action for p in props]
    props, notes = run(lstate(sealed_days=2))
    assert not props and any("after 7" in n for n in notes), notes
    props, _ = run(lstate(settings={"lure_beasts": False}))
    assert not props
    props, notes = run(lstate(cands=[{"key": "10,5,0", "fits": False, "why": "wider than one tile"}]))
    assert not props and any("wider" in n for n in notes), notes
    props, notes = run(lstate(mech=2))
    assert not props and any("mechanism" in n for n in notes), notes
    props, _ = run(lstate(beasts=[{"id": 50, "kind": "forgotten beast", "caged": True}]))
    assert not props


@test("phases: building -> build_lure; ready with a gate open -> lure_shut first; ready and clear -> lure_open")
def _():
    m = Memory()
    props, _ = run(lstate([row("building", pieces_built=3)]), m)
    assert types(props) == [("lure_build", "build_lure")] and props[0].action == {"type": "build_lure",
                                                                                   "opening": "10,5,0"}
    props, _ = run(lstate([row("ready", inner={"kind": "door", "built": True, "shut": False})]), m)
    assert types(props) == [("lure_shut", "lure_shut")]
    props, _ = run(lstate([row("ready")]), m)
    assert types(props) == [("lure_open", "lure_open")]
    props, notes = run(lstate([row("ready")], cave=2), m)
    assert not props and any("in the caverns" in n for n in notes), notes
    props, notes = run(lstate([row("ready", citizens_near=1)]), m)
    assert not props


@test("open: caught -> shut (noted caught); in the pocket (immune) -> shut; a citizen down or near, Rules off -> shut")
def _():
    m = Memory()
    props, _ = run(lstate([row("caught", open=True, caught=True)]), m)
    assert types(props) == [("lure_shut", "lure_shut")] and m.lure["10,5,0"]["caught"] == 50
    props, _ = run(lstate([row("open", open=True, immune=True, beast_in_pocket=True)]), m)
    assert types(props) == [("lure_shut", "lure_shut")]
    for kw in ({"cave": 1}, {"settings": {"lure_beasts": False}}):
        props, _ = run(lstate([row("open", open=True, open_ticks=10)], **kw), Memory())
        assert types(props) == [("lure_shut", "lure_shut")], kw
    props, _ = run(lstate([row("open", open=True, open_ticks=10, citizens_near=1)]), Memory())
    assert types(props) == [("lure_shut", "lure_shut")]
    props, notes = run(lstate([row("open", open=True, open_ticks=10)]), Memory())
    assert not props and any("is open" in n for n in notes), notes


@test("open too long: shut, try counted, opened again only after the back-off, doubled the next time")
def _():
    m = Memory()
    cfg_days = PLANNER_CONFIG["lure_open_days"]
    t0 = 10 * DAY
    props, notes = run(lstate([row("open", open=True, open_ticks=cfg_days * DAY)], tick=t0), m)
    assert types(props) == [("lure_shut", "lure_shut")] and "try 1" in props[0].reason, props[0].reason
    mm = m.lure["10,5,0"]
    base = 300 * 403200
    assert mm["tries"] == 1 and mm["next_try"] == base + t0 + PLANNER_CONFIG["lure_retry_days"] * DAY, mm
    props, notes = run(lstate([row("ready")], tick=t0 + DAY), m)
    assert not props and any("waits" in n for n in notes), notes
    t1 = t0 + PLANNER_CONFIG["lure_retry_days"] * DAY
    props, _ = run(lstate([row("ready")], tick=t1), m)
    assert types(props) == [("lure_open", "lure_open")]
    props, _ = run(lstate([row("open", open=True, open_ticks=cfg_days * DAY)], tick=t1 + 5 * DAY), m)
    assert m.lure["10,5,0"]["tries"] == 2
    assert m.lure["10,5,0"]["next_try"] == base + t1 + 5 * DAY + 2 * PLANNER_CONFIG["lure_retry_days"] * DAY
    # a new beast for the pocket: its tries start again
    run(lstate([row("ready", beast_id=51)], tick=t1 + 6 * DAY), m)
    assert m.lure["10,5,0"]["tries"] == 0 and "next_try" not in m.lure["10,5,0"]


@test("done: a caught beast is noted (stays caged, never let out); a finished pocket is reused for the next beast")
def _():
    m = Memory()
    props, notes = run(lstate([row("done", done={"how": "caught"})], beasts=[]), m)
    assert not props and any("stays caged" in n for n in notes), notes
    props, _ = run(lstate([row("done", done={"how": "caught"}, beast_id=49)]), m)
    assert types(props) == [("lure_build", "build_lure")] and props[0].action["beast"] == 50


@test("shut in, no fortification near: noted, no archers; one with posts near and a crossbow squad: archer_post")
def _():
    s = lstate([row("done", done={"how": "shut_in"}, immune=True)], beasts=[])
    props, notes = run(s)
    assert not props and any("stays shut in" in n for n in notes), notes
    s["siege"] = {"entrances": [{"id": 3, "x": 12, "y": 5, "z": 0, "posts": 2}]}
    s["military"] = {"squads": [{"id": 9, "name": "Bolts", "ai_uniform": "crossbow", "members": 4,
                                 "power": {"power": 50, "armed": 4}}]}
    props, _ = run(s)
    assert types(props) == [("lure_archer", "archer_post")] and props[0].action == {
        "type": "archer_post", "entrance_id": 3, "squads": [9]}, [p.action for p in props]


@test("the lure's rule runs in plan() (an older bridge without the section: nothing)")
def _():
    src = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")
    assert "from planner_lure import _lure_rule" in src and "_guard(_lure_rule, s, cfg, proposals, notes, memory)" in src
    props, notes = [], []
    PL._lure_rule({"date": {"year": 300, "tick": 0}}, dict(PLANNER_CONFIG), props, notes, Memory())
    assert not props and not notes


if __name__ == "__main__":
    finish("lupa not installed" if SKIP else None)
