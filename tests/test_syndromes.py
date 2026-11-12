"""(0.105.41, item 11) Syndromes beyond infection, and miasma:
lua/ai-syndromes.lua in a fake fort (the syndromes read with their routes,
deadly effects and sources; the carriers of a contact syndrome; the fort's
floors walked in slices; the quarantine and the hospital burrow reading it;
the clean taking only the syndrome materials; miasma indoors and what rots
near it; clear_miasma's guards), the bridge's wiring, and the brain
(brain/planner_syndromes.py) with plan() unchanged without the sections.

    python tests/test_syndromes.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
import planner_syndromes as PS  # noqa: E402
from digest import normalize, SECTION_DEFAULTS, digest as build_digest  # noqa: E402
from planner_core import Proposal, player_rules  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
DAY = 1200

# The fake fort. W.syn(id, t): a syndrome; W.mat(type, index, t): a material
# (t.syn = list of syndrome ids, t.mode/id: its source); W.unit{...}: a
# citizen; W.block(bx, by, z): a map block; W.spatter(block, mt, mi, tiles);
# W.flow(x, y, z): a miasma tile; W.item{...}: an item on a block.
FAKE = r"""
local src = ...
local W = {syns = {}, mats = {}, citizens = {}, blocks = {}, flows = {}, items = {}, outside = {},
           piles = {}, site = {}, buildings = {}, units = {}, boxes = {}}
local env = setmetatable({}, {__index = _G})
local key = function(x, y, z) return x .. ',' .. y .. ',' .. z end
local ident = setmetatable({}, {__index = function(_, k) return k end})
function W.syn(id, t)
    t.id = id
    t.flags = t.flags or {}
    local ce = {}
    for _, e in ipairs(t.effects or {}) do table.insert(ce, {getType = function() return e end}) end
    t.ce = ce
    W.syns[id] = t
    return t
end
function W.mat(mt, mi, t)
    local list = {}
    for _, id in ipairs(t.syn or {}) do table.insert(list, W.syns[id]) end
    local info = {material = {syndrome = {syndrome = list}}, name = t.name or 'stuff'}
    if t.mode == 'creature' then info.creature = {creature_id = t.id}
    elseif t.mode == 'inorganic' then info.inorganic = {id = t.id}
    elseif t.mode == 'plant' then info.plant = {id = t.id} end
    info.toString = function(self) return self.name end
    W.mats[mt .. ':' .. mi] = info
end
function W.unit(t)
    t.body = t.body or {spatters = {}}
    t.syndromes = t.syndromes or {active = {}}
    t.inventory = t.inventory or {}
    t.military = t.military or {squad_id = -1}
    table.insert(W.citizens, t)
    W.units[t.id] = t
    return t
end
function W.block(bx, by, z)
    local b = {block_events = {}, items = {}, map_pos = {x = bx * 16, y = by * 16, z = z}}
    W.blocks[key(bx, by, z)] = b
    return b
end
function W.spatter(b, mt, mi, tiles)
    local amount = {}
    for x = 0, 15 do amount[x] = setmetatable({}, {__index = function() return 0 end}) end
    for i = 1, tiles do amount[(i - 1) % 16][(i - 1) // 16] = 10 end
    local ev = {mat_type = mt, mat_index = mi, amount = amount, getType = function() return 'spatter' end}
    table.insert(b.block_events, ev)
    return ev
end
function W.flow(x, y, z, d)
    table.insert(W.flows, {type = 'Miasma', density = d or 50, pos = {x = x, y = y, z = z}})
end
function W.item(t)
    t.flags = t.flags or {}
    t.flags.on_ground = t.flags.on_ground ~= false
    t.getType = function(self) return self.kind end
    W.items[t.id] = t
    local b = W.blocks[key(t.pos.x // 16, t.pos.y // 16, t.pos.z)] or W.block(t.pos.x // 16, t.pos.y // 16, t.pos.z)
    table.insert(b.items, t.id)
    return t
end
function W.dump(x1, y1, x2, y2, z, outside)
    local b = {id = 900 + #W.buildings, type = 'Dump', x1 = x1, y1 = y1, x2 = x2, y2 = y2, z = z,
               getType = function() return 'Civzone' end}
    table.insert(W.buildings, b)
    if outside then
        for x = x1, x2 do for y = y1, y2 do W.outside[key(x, y, z)] = true end end
    end
end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {
    global = {cur_year = 200, cur_year_tick = 0, flows = W.flows,
              world = {buildings = {all = W.buildings}, raws = {inorganics = {all = {}}, plants = {all = {}},
                                                                creatures = {all = {}}}},
              plotinfo = {civ_id = 10, race_id = 1}},
    syndrome = {find = function(id) return W.syns[id] end},
    creature_interaction_effect_type = ident,
    block_square_event_type = {material_spatter = 'spatter'},
    flow_type = {Miasma = 'Miasma'},
    item_type = ident,
    building_type = {Civzone = 'Civzone', Stockpile = 'Stockpile'},
    civzone_type = ident,
    item = {find = function(id) return W.items[id] end},
    unit = {find = function(id) return W.units[id] end},
}
env.dfhack = {
    df2utf = function(s) return s end,
    matinfo = {decode = function(mt, mi) return W.mats[mt .. ':' .. mi] end},
    units = {getReadableName = function(u) return u.name or ('dwarf ' .. u.id) end,
             getCitizens = function() return W.citizens end},
    maps = {getBlock = function(x, y, z) return W.blocks[key(x, y, z)] end,
            getTileBlock = function(x, y, z) return W.blocks[key(x // 16, y // 16, z)] end,
            getTileFlags = function(x, y, z) return {outside = W.outside[key(x, y, z)] or false} end},
    items = {getPosition = function(it) return it.pos.x, it.pos.y, it.pos.z end,
             getDescription = function(it) return it.what or it.kind end,
             getOwner = function() return nil end},
    buildings = {findAtTile = function(p) return W.piles[key(p.x, p.y, p.z)] end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
env.reqscript = function(name)
    if name == 'ai-cleanup' then return {fort_boxes = function() return W.boxes end} end
    error('no module ' .. tostring(name))
end
assert(load(src, 'ai-syndromes', 't', env))()
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-syndromes.lua"))
    return lua, env, w


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


def py(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    keys = list(v.keys())
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in sorted(keys)]
    return {k: py(v[k]) for k in keys}


def fb_fort(lua, w):
    """A forgotten beast's contact syndrome (necrosis), a cave spider's venom
    (injected, paralysis), a beer with an ingested one of no known source."""
    w.syn(5, T(lua, {"syn_name": "beast blight", "flags": {"SYN_CONTACT": True}, "effects": ["NECROSIS", "PAIN"]}))
    w.syn(6, T(lua, {"syn_name": "spider venom", "flags": {"SYN_INJECTED": True}, "effects": ["PARALYSIS"]}))
    w.syn(7, T(lua, {"syn_name": "dizzy", "flags": {"SYN_INGESTED": True}, "effects": ["DIZZINESS"]}))
    w.mat(200, 1, T(lua, {"syn": [5], "mode": "creature", "id": "FORGOTTEN_BEAST_3", "name": "forgotten beast blood"}))
    w.mat(201, 2, T(lua, {"syn": [6], "mode": "creature", "id": "SPIDER_CAVE_GIANT", "name": "giant cave spider venom"}))
    w.mat(3, 0, T(lua, {"name": "dwarf blood"}))
    w.boxes = T(lua, {100: {"x1": 0, "y1": 0, "x2": 31, "y2": 15}})


def spat(lua, mt, mi):
    return T(lua, {"base": {"mat_type": mt, "mat_index": mi}})


# --- 1. syndromes ---------------------------------------------------------------------------

@test("syndromes: each one named, its days, routes, deadly effects and source (learned from the material seen)")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fb_fort(lua, w)
    w.unit(T(lua, {"id": 1, "name": "Urist", "body": {"spatters": [spat(lua, 200, 1)]},
                   "syndromes": {"active": [{"type": 5, "ticks": 3 * DAY}]}}))
    w.unit(T(lua, {"id": 2, "name": "Bim", "syndromes": {"active": [{"type": 7, "ticks": 100}]}}))
    w.unit(T(lua, {"id": 3, "name": "Clean"}))
    r = py(env.report())
    assert r["afflicted"] == 2 and r["deadly"] == 1 and r["carriers"] == 1 and r["carrier_ids"] == [1], r
    u = [x for x in r["list"] if x["id"] == 1][0]
    s = u["syndromes"][0]
    assert s["name"] == "beast blight" and s["days"] == 3 and s["routes"] == ["contact"] and s["deadly"] is True, s
    assert s["effects"] == ["NECROSIS", "PAIN"] and s["source"] == "forgotten_beast", s
    assert u["carrier"] is True and u["carries"] == ["forgotten beast blood"], u
    b = [x for x in r["list"] if x["id"] == 2][0]["syndromes"][0]
    assert b["routes"] == ["ingested"] and b.get("source") is None and b.get("deadly") is None, b
    assert r["unknown_sources"] == 1 and r["sources"] == {"forgotten_beast": 1, "unknown": 1}, r


@test("syndromes: a source not met on the fort is found in the raws (walked once, in slices)")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fb_fort(lua, w)
    mat = T(lua, {"syndrome": {"syndrome": [w.syns[6]]}, "state_name": {"Liquid": "venom", "Solid": "venom"}})
    env.df["global"]["world"]["raws"]["creatures"]["all"] = T(lua, [{"creature_id": "SPIDER_CAVE_GIANT",
                                                                    "material": [mat]}])
    w.unit(T(lua, {"id": 1, "syndromes": {"active": [{"type": 6, "ticks": 10}]}}))
    r = py(env.report())
    assert r["raws_walked"] is True, r
    r = py(env.report())
    s = r["list"][0]["syndromes"][0]
    assert s["source"] == "cave_spider" and s["source_what"] == "venom" and s["deadly"] is True, s


@test("source_kind: forgotten beast, cave spider, evil weather, plant, mineral")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    sk = env.source_kind
    assert sk("creature", "FORGOTTEN_BEAST_12") == "forgotten_beast"
    assert sk("creature", "SPIDER_CAVE_GIANT") == "cave_spider"
    assert sk("creature", "NIGHT_CREATURE_4") == "night_creature"
    assert sk("creature", "DWARF") == "creature"
    assert sk("inorganic", "EVIL_RAIN_2") == "evil_weather" and sk("inorganic", "GALENA") == "mineral"
    assert sk("plant", "MUSHROOM_HELMET_PLUMP") == "plant" and sk(None, None) == "unknown"


# --- 2. the floors, the clean ---------------------------------------------------------------

@test("floors: only blocks in the fort's areas walked; syndrome spatter counted, plain blood not; a pass a day")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fb_fort(lua, w)
    b = w.block(0, 0, 100)
    w.spatter(b, 200, 1, 5)
    w.spatter(b, 3, 0, 9)                                   # blood: no syndrome
    far = w.block(5, 5, 100)                                # outside the fort's box
    w.spatter(far, 200, 1, 7)
    r = py(env.report())
    f = r["floors"]
    assert f["tiles"] == 5 and f["contact_tiles"] == 5 and f["blocks"] == 1, f
    assert f["materials"] == {"forgotten beast blood": 5}, f
    w.spatter(b, 200, 1, 3)
    assert py(env.report())["floors"]["tiles"] == 5          # the same day: the last pass
    env.df["global"]["cur_year_tick"] = DAY + 1
    assert py(env.report())["floors"]["tiles"] == 8


@test("clean: the syndrome spatter off the citizens, their things and the fort's floors; blood left; dry run counts only")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fb_fort(lua, w)
    item = T(lua, {"contaminants": [spat(lua, 200, 1), spat(lua, 3, 0)]})
    u = w.unit(T(lua, {"id": 1, "body": {"spatters": [spat(lua, 200, 1), spat(lua, 3, 0), spat(lua, 200, 1)]},
                       "inventory": [{"item": item}]}))
    b = w.block(1, 0, 100)
    w.spatter(b, 3, 0, 4)
    w.spatter(b, 200, 1, 6)
    d = py(env.clean(None, True))
    assert d["dry_run"] is True and d["unit_spatter"] == 3 and d["units"] == 1 and d["items"] == 1, d
    assert d["tile_events"] == 1 and d["tiles"] == 6, d
    assert len(u.body.spatters) == 3 and len(b.block_events) == 2      # nothing changed
    r = py(env.clean(None, False))
    assert r["ok"] is True and r["unit_spatter"] == 3 and r["tile_events"] == 1, r
    assert len(u.body.spatters) == 1 and u.body.spatters[1].base.mat_type == 3
    assert len(item.contaminants) == 1 and item.contaminants[1].base.mat_type == 3
    assert len(b.block_events) == 1 and b.block_events[1].mat_type == 3
    again = py(env.clean(None, False))
    assert again["ok"] is False and again["rejected"] is True, again
    only = py(env.clean(T(lua, {"tiles": False}), True))
    assert only.get("walked") is None, only


# --- 3. the quarantine --------------------------------------------------------------------

@test("quarantine: carriers kept, held days after last seen carrying, then let out; release empties; dry run saves nothing")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    fb_fort(lua, w)
    u = w.unit(T(lua, {"id": 1, "name": "Urist", "body": {"spatters": [spat(lua, 200, 1)]}}))
    w.unit(T(lua, {"id": 2}))
    d = py(env.quarantine(T(lua, {"days": 3}), True))
    assert [a["id"] for a in d["added"]] == [1] and not env.quarantined(1), d
    r = py(env.quarantine(T(lua, {"days": 3}), False))
    assert r["added"][0]["name"] == "Urist" and r["added"][0]["carries"] == ["forgotten beast blood"], r
    assert env.quarantined(1) and not env.quarantined(2)
    assert py(env.report())["quarantined"] == 1
    u.body.spatters = T(lua, [])                             # washed
    env.df["global"]["cur_year_tick"] = 2 * DAY
    assert py(env.quarantine(T(lua, {"days": 3}), False))["unchanged"] is True and env.quarantined(1)
    env.df["global"]["cur_year_tick"] = 3 * DAY + 1
    r = py(env.quarantine(T(lua, {"days": 3}), False))
    assert r["released"] == [1] and not env.quarantined(1), r
    env.quarantine(None, False)
    w.unit(T(lua, {"id": 3, "body": {"spatters": [spat(lua, 200, 1)]}}))
    env.quarantine(None, False)
    assert env.quarantined(3)
    r = py(env.quarantine(T(lua, {"release": True}), False))
    assert r["released"] == [3] and not env.quarantined(3), r


@test("quarantine: the hospital burrow counts a quarantined citizen as a patient (ai-society-burrows is_patient)")
def _():
    src = (LUA_DIR / "ai-society-burrows.lua").read_text(encoding="utf-8")
    i = src.index("function is_patient(u)")
    j = src.index("\nend\n", src.index("function in_quarantine(u)")) + 5
    if LuaRuntime is None:
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("HOSP_RQ = {'rq_diagnosis'}; Q = {}\n"
                "function reqscript(n) if n == 'ai-syndromes' then return {quarantined = function(id) "
                "return Q[id] == true end} end error('no') end\n" + src[i:j])
    g = lua.globals()
    healthy = lua.table_from({"id": 4, "health": lua.table_from({"flags": lua.table_from({})})})
    assert g.is_patient(healthy) is False
    g.Q[4] = True
    assert g.is_patient(healthy) is True
    lua.execute("function reqscript() error('no module') end")
    assert g.is_patient(healthy) is False                    # no module: as before


# --- 4. miasma -------------------------------------------------------------------------------

def miasma_fort(lua, w):
    w.boxes = T(lua, {100: {"x1": 0, "y1": 0, "x2": 31, "y2": 31}})
    for x in range(4, 8):
        w.flow(x, 4, 100)
    w.flow(40, 40, 100)                                     # indoors, far from the living
    w.flow(5, 20, 99)
    w.outside["5,20,99"] = True                             # under the sky: not counted indoors
    w.item(T(lua, {"id": 11, "kind": "CORPSE", "race": 7, "pos": {"x": 5, "y": 5, "z": 100}, "what": "goblin corpse"}))
    w.item(T(lua, {"id": 12, "kind": "CORPSE", "race": 1, "unit_id": 50, "pos": {"x": 6, "y": 5, "z": 100}}))
    w.units[50] = T(lua, {"id": 50, "civ_id": 10})
    w.item(T(lua, {"id": 13, "kind": "MEAT", "flags": {"rotten": True}, "pos": {"x": 7, "y": 5, "z": 100}}))
    w.item(T(lua, {"id": 14, "kind": "MEAT", "pos": {"x": 7, "y": 6, "z": 100}}))       # not rotten
    w.item(T(lua, {"id": 15, "kind": "REMAINS", "race": 7, "pos": {"x": 8, "y": 5, "z": 100}}))
    w.item(T(lua, {"id": 16, "kind": "CORPSE", "race": 7, "flags": {"forbid": True}, "pos": {"x": 3, "y": 3, "z": 100}}))
    w.item(T(lua, {"id": 17, "kind": "CORPSEPIECE", "race": 7, "pos": {"x": 9, "y": 9, "z": 100}}))
    w.piles["9,9,100"] = T(lua, {"getType": lambda self: "Stockpile"})


@test("miasma: the tiles indoors and near the living; what rots near the worst; the fort's own dead apart; dumps outside")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    miasma_fort(lua, w)
    r = py(env.miasma_report())
    assert r["tiles"] == 6 and r["indoor"] == 5 and r["living"] == 4, r
    assert r["spots"][0]["tiles"] == 4 and r["spots"][0]["living"] is True, r
    assert r["sources"] == {"own_dead": 1, "corpse": 3, "remains": 1, "food": 1}, r
    assert r["kept"] == {"own_dead": 1, "in_pile": 1}, r
    assert r["markable"] == 4 and r["dumps"] == 0 and r["dump_outside"] == 0, r
    ids = {x["id"]: x for x in r["items"]}
    assert 14 not in ids and ids[11]["what"] == "goblin corpse" and ids[12]["kept"] == "own_dead", ids


@test("clear_miasma: refused without a dump under the sky; marks the rest, unforbids another's body; never the own dead")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    miasma_fort(lua, w)
    r = py(env.clear_miasma(None, False))
    assert r["rejected"] is True and "under the sky" in r["error"], r
    w.dump(50, 50, 52, 52, 101, False)
    assert py(env.clear_miasma(None, False))["rejected"] is True      # an indoor dump only
    w.dump(60, 60, 62, 62, 110, True)
    d = py(env.clear_miasma(None, True))
    assert d["marked"] == 4 and d["unforbidden"] == 1 and not w["items"][11].flags.dump, d
    r = py(env.clear_miasma(T(lua, {"max": 2}), False))
    assert r["marked"] == 2 and r["capped"] is True, r
    r = py(env.clear_miasma(None, False))
    assert r["marked"] == 2 and r["kept"]["marked"] == 2, r
    assert w["items"][16].flags.dump is True and w["items"][16].flags.forbid is False
    assert not w["items"][12].flags.dump and not w["items"][17].flags.dump
    assert py(env.clear_miasma(None, False))["rejected"] is True


# --- 5. the bridge's wiring --------------------------------------------------------------------

@test("bridge: the syndromes and miasma sections (safe), the three actions (dry runs, values checked), the module listed")
def _():
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "syndromes = function() return safe(function() return reqscript('ai-syndromes').report() end) end," in src
    assert "miasma = function() return safe(function() return reqscript('ai-syndromes').miasma_report() end) end," in src
    actions = src[src.index("ACTIONS = {"):src.index("DRY_OK = {}")]
    for a in ("clean_contaminants", "quarantine_syndromes", "clear_miasma"):
        assert f"    {a} = function(a)" in actions, a
    dry = src[src.index("DRY_OK = {}"):src.index("}) do DRY_OK[name] = true end")]
    assert "'clean_contaminants', 'quarantine_syndromes', 'clear_miasma'" in dry
    mods = src[src.index("BRIDGE_MODULES = {"):src.index("}", src.index("BRIDGE_MODULES = {"))]
    assert "'ai-syndromes'" in mods
    assert SECTION_DEFAULTS["syndromes"] == {} and SECTION_DEFAULTS["miasma"] == {}
    import overseer
    for a in ("clean_contaminants", "quarantine_syndromes", "clear_miasma"):
        assert a in overseer.SHORT_WORDS and a in overseer.CAMERA_QUIET, a
    if LuaRuntime is None:
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
        GOT = nil
        function reject(r) return {ok = false, rejected = true, error = r} end
        function int_in(v, lo, hi)
            local n = type(v) == 'number' and math.tointeger(v) or nil
            if n and n >= lo and n <= hi then return n end
            return nil
        end
        function reqscript() return setmetatable({}, {__index = function(_, k)
            return function(o, dry) GOT = {k = k, o = o, dry = dry}; return {ok = true} end end}) end
    """)
    fns = {}
    for a in ("clean_contaminants", "quarantine_syndromes", "clear_miasma"):
        i = actions.index(f"    {a} = function(a)")
        j = actions.index("    end,\n", i) + len("    end,\n")
        fns[a] = lua.execute(actions[i:j].strip().rstrip(",").replace(f"{a} = function(a)", "return function(a)", 1))
    tf = lua.table_from
    assert fns["clean_contaminants"](tf({"units": "x"}))["rejected"] is True
    assert fns["clean_contaminants"](tf({"budget_ms": 5}))["rejected"] is True
    assert fns["clean_contaminants"](tf({"tiles": False, "dry_run": True}))["ok"] is True
    g = lua.globals().GOT
    assert g.k == "clean" and g.o.tiles is False and g.dry is True
    assert fns["quarantine_syndromes"](tf({"days": 99}))["rejected"] is True
    assert fns["quarantine_syndromes"](tf({"release": 1}))["rejected"] is True
    fns["quarantine_syndromes"](tf({"days": 7, "max": 20}))
    g = lua.globals().GOT
    assert g.k == "quarantine" and g.o.days == 7 and g.o.max == 20 and g.o.release is False
    assert fns["clear_miasma"](tf({"max": 0}))["rejected"] is True
    fns["clear_miasma"](tf({"max": 50}))
    assert lua.globals().GOT.k == "clear_miasma"


@test("settings: the syndrome_care switch (on by default), saved, sent to the AI and on the Rules tab")
def _():
    src = (LUA_DIR / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    assert "syndrome_care = true," in src and "'syndrome_care'," in src and "syndrome_care = s.syndrome_care," in src
    gui = (LUA_DIR / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
    assert "view_id = 'syndrome_care'" in gui and "subviews.syndrome_care:setOption" in gui
    assert player_rules({"settings": {}})["syndrome_care"] is True
    assert player_rules({"settings": {"syndrome_care": False}})["syndrome_care"] is False


# --- 6. the brain -------------------------------------------------------------------------------

def state(**extra):
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    base.update(extra)
    return normalize(base)


SYN = {"afflicted": 2, "deadly": 1, "carriers": 1, "carrier_ids": [1], "quarantined": 0,
       "by_name": {"beast blight": 1, "dizzy": 1},
       "list": [{"id": 1, "name": "Urist", "carrier": True, "carries": ["forgotten beast blood"],
                 "syndromes": [{"id": 5, "name": "beast blight", "days": 3, "routes": ["contact"], "deadly": True,
                                "effects": ["NECROSIS"], "source": "forgotten_beast",
                                "source_what": "forgotten beast blood"}]},
                {"id": 2, "name": "Bim", "syndromes": [{"id": 7, "name": "dizzy", "days": 0, "routes": ["ingested"]}]}],
       "floors": {"tiles": 6, "contact_tiles": 6, "materials": {"forgotten beast blood": 6}}}


def run_syn(s, memory=None, cfg=PLANNER_CONFIG):
    props, notes = [], []
    PS._syndrome_rule(s, cfg, props, notes, memory or Memory())
    return props, notes


@test("brain: who has what, from where and what it does; the carriers kept apart; the clean's trial first, then real")
def _():
    m = Memory()
    props, notes = run_syn(state(syndromes=SYN), m)
    assert notes[0].startswith("2 citizens have an active syndrome (beast blight 1, dizzy 1); 1 with deadly"), notes
    assert notes[1].startswith("Urist: beast blight for 3 days, from a forgotten beast"), notes
    assert "deadly (necrosis)" in notes[1] and "carries forgotten beast blood" in notes[1], notes
    assert "something eaten or drunk (the food, the drink or the water)" in notes[2], notes
    assert "spreads sickness by touch: 1 citizen(s)" in notes[3], notes
    rules = [(p.rule, p.action) for p in props]
    assert rules == [("syndrome_quarantine", {"type": "quarantine_syndromes", "days": 7, "max": 20}),
                     ("syndrome_clean", {"type": "clean_contaminants", "dry_run": True})], rules
    PS.note_syndromes(props[1], {"ok": True, "unit_spatter": 1}, m, 500)
    assert m.syndromes_seen["dry"] == 500
    props, _ = run_syn(state(syndromes=SYN), m)
    assert props[1].action == {"type": "clean_contaminants"} and "trial" not in props[1].reason
    PS.note_syndromes(Proposal("syndrome_clean", {"type": "clean_contaminants"}, "", 3),
                      {"ok": True, "unit_spatter": 2, "tile_events": 3}, m, 900)
    assert m.syndromes_seen["cleaned"] == 5 and m.syndromes_seen["last"] == 900


@test("brain: switched off, nothing done and the kept let out; the hospital burrow off: nobody kept apart (said)")
def _():
    off = dict(SYN, quarantined=2)
    s = state(syndromes=off)
    s["settings"]["syndrome_care"] = False
    props, notes = run_syn(s)
    assert [p.action for p in props] == [{"type": "quarantine_syndromes", "release": True}], props
    assert any("syndrome care is off" in n for n in notes), notes
    s = state(syndromes=SYN)
    s["settings"]["hospital_burrow"] = False
    props, notes = run_syn(s)
    assert [p.rule for p in props] == ["syndrome_clean"] and any("hospital burrow is off" in n for n in notes)


@test("brain: none afflicted, nothing spread: silent; one kept apart and clean now: the quarantine asked to let out")
def _():
    quiet = {"afflicted": 0, "deadly": 0, "carriers": 0, "quarantined": 0, "list": [], "floors": {"tiles": 0}}
    assert run_syn(state(syndromes=quiet)) == ([], [])
    props, notes = run_syn(state(syndromes=dict(quiet, quarantined=1)))
    assert [p.rule for p in props] == ["syndrome_quarantine"] and "let out" in props[0].reason and notes == []
    assert run_syn(state(syndromes={"error": "boom"})) == ([], [])


MIA = {"tiles": 9, "indoor": 6, "living": 4, "spots": [{"x": 5, "y": 4, "z": 100, "tiles": 4, "living": True}],
       "sources": {"own_dead": 1, "corpse": 2, "food": 1}, "markable": 3, "dumps": 1, "dump_outside": 1,
       "kept": {"own_dead": 1, "in_pile": 1}}


def run_mia(s):
    props, notes = [], []
    PS._miasma_rule(s, PLANNER_CONFIG, props, notes, Memory())
    return props, notes


@test("brain: miasma said with what rots; marked for the dump outside; the own dead left to burial; the pile said")
def _():
    props, notes = run_mia(state(miasma=MIA))
    assert notes[0] == ("miasma on 6 tile(s) indoors, 4 where the dwarves live; worst at x5 y4 z100: rotting there "
                        "1 of the fort's own dead, 2 bodies or parts, 1 rotten food"), notes
    assert "burial rules" in notes[1] and "lie in a stockpile" in notes[2], notes
    assert [(p.rule, p.action) for p in props] == [("miasma_clear", {"type": "clear_miasma", "max": 50})], props


@test("brain: no dump outside: one made; every refuse pile indoors: one put outside; under the threshold: silent")
def _():
    s = state(miasma=dict(MIA, dump_outside=0))
    s["buildings"]["refuse_list"] = [{"id": 1, "outside": False, "x": 1, "y": 1, "z": 100}]
    props, _ = run_mia(s)
    assert [(p.rule, p.action) for p in props] == [("miasma_dump", {"type": "place_surface", "kind": "dump"}),
                                                   ("miasma_refuse", {"type": "place_surface", "kind": "refuse"})]
    s["buildings"]["refuse_list"].append({"id": 2, "outside": True})
    s["buildings"]["clearing"] = {"dump": {"x": 1}}
    assert run_mia(s)[0] == []
    assert run_mia(state(miasma=dict(MIA, indoor=2))) == ([], [])
    assert run_mia(state(miasma={})) == ([], [])


@test("plan(): without the sections the same as before; with them the rules propose; the digest line")
def _():
    base = state()
    props0, notes0 = plan(base, Memory())
    props1, notes1 = plan(state(syndromes={}, miasma={}), Memory())
    assert [p.action for p in props0] == [p.action for p in props1] and notes0 == notes1
    props, notes = plan(state(syndromes=SYN, miasma=MIA), Memory())
    types = {p.action.get("type") for p in props}
    assert {"quarantine_syndromes", "clean_contaminants", "clear_miasma"} <= types, types
    assert PS.syndrome_line(state(syndromes=SYN, miasma=MIA)) == (
        "Sickness: syndromes 2 (deadly 1), carriers 1, kept apart 0; miasma indoors 6 tiles")
    assert "Sickness:" in build_digest(state(syndromes=SYN, miasma=MIA))
    assert PS.syndrome_line(base) == ""


finish()
