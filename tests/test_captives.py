"""(item6) Prisoners' outcomes and necromancer sieges: lua/ai-captives.lua in a
fake fort (each caged prisoner reported with what the brain decides by, the
AI's pit and its drop, the player's pits only counted; a drop found only
where the fall is clean, deep enough and lands outside the dwarves' walk
group; make_pit's dry run and real zone; pit_prisoners' checks and links;
the necromancer facts: the dead, the raisers, bodies outside, towers), the
bridge's wiring, and the brain (brain/planner_captives.py: each prisoner's
outcome by the Rules choice, the pit's trial first, nothing while enemies
are about; an overwhelming undead siege: the squads kept in or called back,
the alarm, the bodies rotted, the tower said).

    python tests/test_captives.py
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
from planner import Memory, PLANNER_CONFIG, plan, record  # noqa: E402
from planner_core import Proposal  # noqa: E402
import planner_captives as PC  # noqa: E402
from digest import normalize, SECTION_DEFAULTS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"

# The fake fort: tiles W.tiles["x,y,z"] = {shape, flow_size, liquid_type,
# hidden, outside, feature, group} (default: a floor in walk group 1);
# units W.unit{...}; the pit zones W.pits; world sites W.sites.
FAKE = r"""
local src = ...
local W = {units = {}, tiles = {}, pits = {}, zones = {}, site = {}, sites = {}, corpses = {}, pieces = {},
           interactions = {}, qf = {}, citizens = {}}
local env = setmetatable({}, {__index = _G})
local key = function(x, y, z) return x .. ',' .. y .. ',' .. z end
local ident = setmetatable({}, {__index = function(_, k) return k end})
function W.unit(t)
    t.flags1 = t.flags1 or {caged = t.caged or false}
    t.pos = t.pos or {x = 50, y = 50, z = 100}
    t.race = t.race or 1
    t.caste = 0
    t.general_refs = {insert = function(self, _, v) table.insert(self, v) end}
    t.curse = t.curse or {own_interaction = {}}
    table.insert(W.units, t)
    if t.citizen then table.insert(W.citizens, t) end
    return t
end
function W.tile(x, y, z, t) W.tiles[key(x, y, z)] = t end
-- a shaft at (x, y): open space from z down `levels` levels, landing on a
-- floor in walk group `group` (2: cut off from the dwarves)
function W.shaft(x, y, z, levels, group, landing)
    W.tile(x, y, z, {shape = 'EMPTY'})
    for i = 1, levels do W.tile(x, y, z - i, {shape = 'EMPTY'}) end
    W.tile(x, y, z - levels - 1, landing or {shape = 'FLOOR', group = group or 2})
end
function W.pit(t)
    t.x1, t.y1, t.x2, t.y2 = t.x, t.y, t.x, t.y
    t.assigned_units = t.assigned_units or {}
    table.insert(W.pits, t)
    W.zones[key(t.x, t.y, t.z)] = {t}
    return t
end
local tile = function(x, y, z) return W.tiles[key(x, y, z)] or {} end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.require = function(n)
    if n == 'utils' then return {insert_sorted = function(v, x) table.insert(v, x) end} end
    error('require ' .. n)
end
local RAWS = {[1] = {creature_id = 'GOBLIN', flags = {CAN_SPEAK = true}},
              [2] = {creature_id = 'GIANT_BADGER', flags = {}},
              [3] = {creature_id = 'TITAN', flags = {CAN_SPEAK = true}}}
env.df = {
    global = {cur_year = 200, cur_year_tick = 0,
              world = {units = {active = W.units},
                       buildings = {other = {ZONE_PIT_POND = W.pits}, all = {}},
                       items = {other = {CORPSE = W.corpses, CORPSEPIECE = W.pieces}},
                       world_data = {sites = W.sites},
                       cur_savegame = {save_dir = 'region1'}},
              plotinfo = {civ_id = 10, site_id = 7}},
    tiletype = {attrs = setmetatable({}, {__index = function(_, k) return {shape = k} end})},
    tiletype_shape = ident, profession = ident, world_site_type = ident, interaction_effect_type = ident,
    general_ref_type = {BUILDING_CIVZONE_ASSIGNED = 'zone'},
    general_ref_building_civzone_assignedst = {new = function() return {} end},
    unit = {find = function(id) for _, u in ipairs(W.units) do if u.id == id then return u end end end},
    creature_raw = {find = function(r) local c = RAWS[r]; return {creature_id = c.creature_id, caste = {[0] = {flags = c.flags}}} end},
    interaction = {find = function(id) return W.interactions[id] end},
}
local function f(name) return function(u) return u[name] == true end end
env.dfhack = {
    df2utf = function(s) return s end,
    translation = {translateName = function(n) return n end},
    units = {isDead = f('dead'), isCitizen = f('citizen'), isMerchant = f('merchant'), isVisitor = f('visitor'),
             isDiplomat = f('diplomat'), isTame = f('tame'), isOwnCiv = f('own'), isInvader = f('invader'),
             isDanger = f('danger'), isUndead = f('undead'), isGreatDanger = f('great'), isTitan = f('great'),
             isActive = function(u) return not u.inactive end,
             getReadableName = function(u) return u.name or ('unit ' .. u.id) end,
             getGeneralRef = function(u, t) for _, r in ipairs(u.general_refs) do return r end return nil end,
             getContainer = function(u) return u.cage end,
             getCitizens = function() return W.citizens end},
    items = {getPosition = function(it) return it.x, it.y, it.z end},
    maps = {getTileFlags = function(x, y, z)
                local t = tile(x, y, z)
                return {flow_size = t.flow_size or 0, liquid_type = t.liquid_type or false, hidden = t.hidden or false,
                        outside = t.outside or false, feature_global = t.feature or false, feature_local = false}
            end,
            getTileType = function(x, y, z) return tile(x, y, z).shape or 'FLOOR' end,
            getWalkableGroup = function(p)
                local t = tile(p.x, p.y, p.z)
                if t.group then return t.group end
                return (t.shape or 'FLOOR') == 'FLOOR' and 1 or 0
            end},
    buildings = {findAtTile = function() return nil end,
                 findCivzonesAt = function(p) return W.zones[key(p.x, p.y, p.z)] end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
env.reqscript = function(name)
    if name == 'quickfort' then
        return {apply_blueprint = function(o)
            table.insert(W.qf, o)
            if W.qf_refuse then return {zone_designated = {value = 0}} end
            if not o.dry_run then
                for z, rows in pairs(o.data) do for y, row in pairs(rows) do for x, text in pairs(row) do
                    W.pit({id = 900, x = x, y = y, z = z, name = text:match('name="([^"]+)"')})
                end end end
            end
            return {zone_designated = {value = 1}}
        end}
    end
    error('no module ' .. tostring(name))
end
assert(load(src, 'ai-captives', 't', env))()
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-captives.lua"))
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


def dwarves(lua, w, n=3, z=100):
    for i in range(n):
        w.unit(T(lua, {"id": 100 + i, "citizen": True, "pos": {"x": 50, "y": 50, "z": z}}))


def goblin(lua, w, uid=1, **kw):
    d = {"id": uid, "name": f"goblin {uid}", "caged": True, "invader": True, "danger": True, "race": 1,
         "cage": {"flags": {"in_building": True}, "x": 40, "y": 40, "z": 100}}
    d.update(kw)
    return w.unit(T(lua, d))


# --- 1. the report ---------------------------------------------------------------------

@test("report: each caged prisoner with its facts; the fort's own animals, citizens, merchants and the dead aren't prisoners")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    goblin(lua, w, 1)
    w.unit(T(lua, {"id": 2, "caged": True, "danger": True, "race": 2}))                       # a wild badger
    w.unit(T(lua, {"id": 3, "caged": True, "great": True, "danger": True, "race": 3}))        # a titan
    w.unit(T(lua, {"id": 4, "caged": True, "tame": True, "own": True, "race": 2}))            # the fort's own
    w.unit(T(lua, {"id": 5, "caged": True, "merchant": True, "race": 1}))
    w.unit(T(lua, {"id": 6, "caged": True, "dead": True, "invader": True, "race": 1}))
    w.unit(T(lua, {"id": 7, "caged": True, "citizen": True, "race": 1}))
    w.unit(T(lua, {"id": 8, "caged": True, "profession": "THIEF", "race": 1}))
    w.unit(T(lua, {"id": 9, "invader": True, "race": 1}))                                    # loose, not caged
    r = py(env.report())
    rows = {x["id"]: x for x in r["list"]}
    assert r["caged"] == 4 and sorted(rows) == [1, 2, 3, 8], r
    assert rows[1]["invader"] and rows[1]["trap"] and rows[1]["intelligent"] and rows[1]["race"] == "GOBLIN", rows[1]
    assert "invader" not in rows[2] and "intelligent" not in rows[2] and rows[2]["danger"], rows[2]
    assert rows[3]["great"] is True and rows[8]["thief"] == "thief", rows


@test("report: the AI's pit with its drop and assigned count; a player's pit only counted")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    dwarves(lua, w)
    w.shaft(60, 50, 100, 8)
    w.pit(T(lua, {"id": 50, "x": 60, "y": 50, "z": 100, "name": "AI pit", "assigned_units": [11]}))
    w.pit(T(lua, {"id": 51, "x": 70, "y": 70, "z": 100, "name": "my pond"}))
    r = py(env.report())
    assert r["player_pits"] == 1 and r["pits"] == [{"id": 50, "x": 60, "y": 50, "z": 100, "assigned": 1, "drop": 8}], r


# --- 2. the drop and the pit -------------------------------------------------------------

@test("find_drop: open space beside a walked floor with a deep clean fall; nearest inside first")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    dwarves(lua, w)
    w.shaft(60, 50, 100, 8)
    w.shaft(55, 50, 100, 9)
    spot = py(env.find_drop(7, 25))
    assert (spot["x"], spot["y"], spot["z"], spot["drop"]) == (55, 50, 100, 9), spot


@test("find_drop: refused: too shallow, water at the bottom, a cavern below, a landing in the dwarves' walk group, "
      "a cistern tile, no floor beside it (each alone)")
def _():
    if LuaRuntime is None:
        return

    def one(build):
        lua, env, w = world()
        dwarves(lua, w)
        build(lua, w)
        return env.find_drop(7, 25)

    def ok(lua, w):
        w.shaft(55, 50, 100, 8)
    assert one(ok) is not None                                                   # the control
    assert one(lambda lua, w: w.shaft(55, 50, 100, 4)) is None                   # shallow
    assert one(lambda lua, w: w.shaft(55, 50, 100, 8, 2, T(lua, {"shape": "FLOOR", "flow_size": 7, "group": 2}))) is None

    def cavern(lua, w):
        ok(lua, w)
        w.tile(55, 50, 96, T(lua, {"shape": "EMPTY", "feature": True}))
    assert one(cavern) is None
    assert one(lambda lua, w: w.shaft(55, 50, 100, 8, 1)) is None               # lands where the dwarves walk

    import re
    util = (LUA_DIR / "ai-util.lua").read_text(encoding="utf-8")
    ck = re.search(r"CISTERN_KEY = '([^']+)'", util).group(1)

    def cistern2(lua, w):
        ok(lua, w)
        w.site[ck] = T(lua, {"plan": {"cistern": {"x1": 55, "y1": 50, "x2": 55, "y2": 50, "z": 95}}})
    assert one(cistern2) is None

    def walled(lua, w):
        ok(lua, w)
        for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            w.tile(55 + d[0], 50 + d[1], 100, T(lua, {"shape": "WALL"}))
    assert one(walled) is None


@test("make_pit: the dry run changes nothing; for real a pit/pond zone named AI pit; an AI pit there is kept; no drop refused")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    dwarves(lua, w)
    r = py(env.make_pit(T(lua, {"min_drop": 7}), False))
    assert r["ok"] is False and r["rejected"] and r["no_drop"], r
    w.shaft(55, 50, 100, 8)
    r = py(env.make_pit(T(lua, {"min_drop": 7}), True))
    assert r["ok"] and r["dry_run"] and len(py(w.pits) or []) == 0, r
    assert all(o.dry_run for o in w.qf.values())
    r = py(env.make_pit(T(lua, {"min_drop": 7}), False))
    assert r["ok"] and r["zone_id"] == 900 and (r["x"], r["y"], r["z"]) == (55, 50, 100), r
    q = py(w.qf)[-1]
    assert q["mode"] == "zone" and q["data"][100][50][55] == 'p{name="AI pit"}', q
    r = py(env.make_pit(T(lua, {}), False))
    assert r["existing"] and r["zone_id"] == 900, r
    lua, env, w = world()
    dwarves(lua, w)
    w.shaft(55, 50, 100, 8)
    w.qf_refuse = True
    assert py(env.make_pit(T(lua, {}), False))["ok"] is False


@test("pit_prisoners: links made both ways (zone lists, unit points); the dry run changes nothing; checks each one")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    dwarves(lua, w)
    w.shaft(60, 50, 100, 8)
    pit = w.pit(T(lua, {"id": 50, "x": 60, "y": 50, "z": 100, "name": "AI pit"}))
    g = goblin(lua, w, 1)
    goblin(lua, w, 2)
    w.unit(T(lua, {"id": 3, "caged": True, "great": True, "race": 3}))
    w.unit(T(lua, {"id": 4, "invader": True, "race": 1}))          # not caged
    r = py(env.pit_prisoners(T(lua, {"ids": [1, 2, 3, 4, 99]}), True))
    assert r["ok"] and r["assigned"] == 2 and r["dry_run"] and len(py(pit.assigned_units) or []) == 0, r
    r = py(env.pit_prisoners(T(lua, {"ids": [1, 3, 4, 99], "max": 5}), False))
    assert r["ok"] and r["ids"] == [1] and r["pit_id"] == 50, r
    assert r["skipped"] == {"3": "a great danger: kept caged", "4": "not a caged prisoner", "99": "gone"}, r
    assert py(pit.assigned_units) == [1] and g.general_refs[1].building_id == 50
    r = py(env.pit_prisoners(T(lua, {"ids": [1]}), False))
    assert r["ok"] is False and r["skipped"] == {"1": "already assigned to a zone"}, r


@test("pit_prisoners: refused with no AI pit, or a pit whose drop is too short; never more than the batch cap")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    dwarves(lua, w)
    goblin(lua, w, 1)
    assert py(env.pit_prisoners(T(lua, {"ids": [1]}), False))["rejected"] is True
    w.shaft(60, 50, 100, 3)
    w.pit(T(lua, {"id": 50, "x": 60, "y": 50, "z": 100, "name": "AI pit"}))
    r = py(env.pit_prisoners(T(lua, {"ids": [1], "min_drop": 7}), False))
    assert r["rejected"] and r["drop"] == 3, r
    lua, env, w = world()
    dwarves(lua, w)
    w.shaft(60, 50, 100, 8)
    w.pit(T(lua, {"id": 50, "x": 60, "y": 50, "z": 100, "name": "AI pit"}))
    for i in range(1, 10):
        goblin(lua, w, i)
    r = py(env.pit_prisoners(T(lua, {"ids": list(range(1, 10)), "max": 50}), False))
    assert r["assigned"] == env.PIT_BATCH, r


# --- 3. necromancer facts ----------------------------------------------------------------

@test("necro: the dead counted (invaders apart), a raiser found by its animating interaction, bodies outside counted "
      "only while the dead are about, towers near listed nearest first")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    w.interactions[5] = T(lua, {"effects": [{"getType": lua.eval("function() return 'ANIMATE' end")}]})
    w.interactions[6] = T(lua, {"effects": [{"getType": lua.eval("function() return 'ADD_SYNDROME' end")}]})
    w.corpses[1] = T(lua, {"x": 1, "y": 1, "z": 100})
    w.tile(1, 1, 100, T(lua, {"outside": True}))
    w.pieces[1] = T(lua, {"x": 2, "y": 2, "z": 90})
    r = py(env.necro())
    assert r["undead"] == 0 and r["surface_corpses"] == 0 and (r["raisers"] or []) == [], r
    w.unit(T(lua, {"id": 1, "undead": True, "invader": True}))
    w.unit(T(lua, {"id": 2, "undead": True}))
    w.unit(T(lua, {"id": 3, "undead": True, "caged": True}))
    w.unit(T(lua, {"id": 4, "name": "Necro", "invader": True, "curse": {"own_interaction": [6, 5]}}))
    w.unit(T(lua, {"id": 5, "curse": {"own_interaction": [6]}}))
    w.sites[1] = T(lua, {"id": 7, "pos": {"x": 10, "y": 10}, "type": "PlayerFortress"})
    w.sites[2] = T(lua, {"id": 8, "pos": {"x": 20, "y": 5}, "type": "Tower", "name": "Tower far"})
    w.sites[3] = T(lua, {"id": 9, "pos": {"x": 7, "y": 12}, "type": "Tower", "name": "Tower near"})
    w.sites[4] = T(lua, {"id": 10, "pos": {"x": 90, "y": 90}, "type": "Tower"})
    r = py(env.necro())
    assert r["undead"] == 2 and r["undead_invaders"] == 1 and r["surface_corpses"] == 1, r
    assert r["raisers"] == [{"id": 4, "name": "Necro", "invader": True}], r
    assert [(t["id"], t["dist"], t["way"]) for t in r["towers"]] == [(9, 3, "southwest"), (8, 10, "northeast")], r


@test("(fix3) necro: a visiting or resident necromancer is no raiser of a siege; an uninvited hostile one is")
def _():
    if LuaRuntime is None:
        return
    lua, env, w = world()
    w.interactions[5] = T(lua, {"effects": [{"getType": lua.eval("function() return 'ANIMATE' end")}]})
    w.unit(T(lua, {"id": 6, "name": "Guest", "visitor": True, "curse": {"own_interaction": [5]}}))
    w.unit(T(lua, {"id": 7, "name": "Scholar", "curse": {"own_interaction": [5]}}))          # resident, no hostility
    r = py(env.necro())
    assert (r["raisers"] or []) == [] and r["surface_corpses"] == 0, r
    w.unit(T(lua, {"id": 8, "name": "Lurker", "flags2": {"visitor_uninvited": True},
                   "curse": {"own_interaction": [5]}}))
    w.unit(T(lua, {"id": 9, "name": "Raider", "danger": True, "curse": {"own_interaction": [5]}}))
    r = py(env.necro())
    assert [x["id"] for x in r["raisers"]] == [8, 9], r


# --- 4. the bridge ---------------------------------------------------------------------

@test("bridge: the captives and necro sections (safe), make_pit and pit_prisoners (dry runs ok, ids checked), the module listed")
def _():
    src = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "captives = function() return safe(function() return reqscript('ai-captives').report(txt) end) end," in src
    assert "necro = function() return safe(function() return reqscript('ai-captives').necro(txt) end) end," in src
    actions = src[src.index("ACTIONS = {"):src.index("DRY_OK = {}")]
    assert "make_pit = function(a)" in actions and "pit_prisoners = function(a)" in actions
    dry = src[src.index("DRY_OK = {}"):src.index("}) do DRY_OK[name] = true end")]
    assert "'make_pit', 'pit_prisoners'" in dry
    mods = src[src.index("BRIDGE_MODULES = {"):src.index("}", src.index("BRIDGE_MODULES = {"))]
    assert "'ai-captives'" in mods
    assert SECTION_DEFAULTS["captives"] == {} and SECTION_DEFAULTS["necro"] == {}
    import overseer
    assert "make_pit" in overseer.SHORT_WORDS and "pit_prisoners" in overseer.SHORT_WORDS
    if LuaRuntime is None:
        return
    i = actions.index("    pit_prisoners = function(a)")
    j = actions.index("    end,\n", i) + len("    end,\n")
    fn = actions[i:j].strip().rstrip(",").replace("pit_prisoners = function(a)", "return function(a)", 1)
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
        GOT = nil
        function reject(r) return {ok = false, rejected = true, error = r} end
        function reqscript() return {pit_prisoners = function(o, dry) GOT = {o = o, dry = dry}; return {ok = true} end} end
    """)
    f = lua.execute(fn)
    assert f(lua.table_from({}))["rejected"] is True
    assert f(lua.table_from({"ids": lua.table_from([1.5])}))["rejected"] is True
    assert f(lua.table_from({"ids": lua.table_from([])}))["rejected"] is True
    assert f(lua.table_from({"ids": lua.table_from([7, 8.0]), "dry_run": True}))["ok"] is True
    got = lua.globals().GOT
    assert list(got.o.ids.values()) == [7, 8] and got.dry is True


# --- 5. the brain ------------------------------------------------------------------------

def state(captives=None, necro=None, prisoners="keep", **extra):
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    if captives is not None:
        base["captives"] = captives
    if necro is not None:
        base["necro"] = necro
    base.setdefault("settings", {})
    base["settings"] = dict(base["settings"] or {}, prisoners=prisoners)
    base.update(extra)
    return normalize(base)


ROWS = [{"id": 1, "name": "Goblin A", "invader": True, "intelligent": True},
        {"id": 2, "name": "Badger", "danger": True},
        {"id": 3, "name": "Titan", "great": True, "invader": True},
        {"id": 4, "name": "Thief", "thief": "thief", "intelligent": True},
        {"id": 5, "name": "Goblin B", "invader": True, "zone": 50}]


def calm(s):
    s["others_on_map"] = {"threats": [], "threats_that_can_reach_dwarves": 0}
    s["civ_alert"] = False
    return s


def run(rule, s, memory=None):
    props, notes = [], []
    rule(s, PLANNER_CONFIG, props, notes, memory if memory is not None else Memory())
    return props, notes


@test("decide: great dangers and wild creatures always kept; keep and release keep; kill sends invaders and thieves")
def _():
    out = {c: [PC.decide(r, c)[0] for r in ROWS] for c in ("keep", "release", "kill")}
    assert out["keep"] == ["keep"] * 5, out
    assert out["release"] == ["keep"] * 5, out
    assert out["kill"] == ["pit", "keep", "keep", "pit", "assigned"], out
    assert "DFHack" in PC.decide(ROWS[0], "release")[1]


@test("brain: keep (the default): one note with each outcome, nothing proposed")
def _():
    s = calm(state({"caged": 5, "list": ROWS, "pits": []}))
    props, notes = run(PC._captives_rule, s)
    assert not props, props
    assert any("5 prisoner(s) in cages" in n and "kept caged (Rules tab: keep)" in n for n in notes), notes


@test("brain: kill with no pit: make_pit proposed with the drop wanted; with enemies about or the alarm up: it waits")
def _():
    s = calm(state({"caged": 5, "list": ROWS, "pits": []}, prisoners="kill"))
    props, notes = run(PC._captives_rule, s)
    assert [p.action for p in props] == [{"type": "make_pit", "min_drop": PLANNER_CONFIG["pit_min_drop"]}], props
    assert props[0].rule == "prisoner_pit"
    s["civ_alert"] = True
    props, notes = run(PC._captives_rule, s)
    assert not props and any("wait for the pit" in n for n in notes), notes
    s = state({"caged": 5, "list": ROWS, "pits": []}, prisoners="kill")
    s["civ_alert"] = False
    s["others_on_map"] = {"threats": [{"id": 77, "can_reach_dwarves": True, "name": "goblin"}],
                          "threats_that_can_reach_dwarves": 1}
    props, _ = run(PC._captives_rule, s)
    assert not props


@test("brain: kill with a deep pit: a trial first, then for real once the trial came back ok; a shallow pit only said")
def _():
    s = calm(state({"caged": 5, "list": ROWS, "pits": [{"id": 50, "drop": 9, "assigned": 1}]}, prisoners="kill"))
    m = Memory()
    props, _ = run(PC._captives_rule, s, m)
    assert len(props) == 1 and props[0].action["dry_run"] is True and props[0].action["ids"] == [1, 4], props
    record([(props[0], {"ok": True, "dry_run": True, "assigned": 2})], s, m)
    assert m.captives_seen.get("pit_trial") is not None
    props, _ = run(PC._captives_rule, s, m)
    assert len(props) == 1 and "dry_run" not in props[0].action and props[0].action["type"] == "pit_prisoners", props
    record([(props[0], {"ok": True, "assigned": 2})], s, m)
    assert m.captives_seen["pitted"] == 2
    s["captives"]["pits"][0]["drop"] = 3
    props, notes = run(PC._captives_rule, s, Memory())
    assert not props and any("drops 3 level(s)" in n for n in notes), notes


@test("brain: with the captives section the threats rule no longer says the old 'no safe way' line; a convict noted")
def _():
    s = calm(state({"caged": 1, "list": ROWS[:1], "pits": []}, prisoners="kill",
                   threats={"prisoners": {"caged": 1, "cage_rooms": 1}}, justice={"punish": {"prison": 2}}))
    _, notes = plan(s, Memory())
    assert not any("no safe way" in n for n in notes), [n for n in notes if "prisoner" in n]
    assert any("2 convict(s)" in n for n in notes)


def squads(n=2, armed=3):
    return [{"id": i, "name": f"Squad {i}", "members": armed, "power": {"armed": armed, "power": 50}}
            for i in range(1, n + 1)]


def horde(n, invader=True, reach=True):
    return [{"id": 1000 + i, "name": "zombie", "kinds": ["Undead"], "invader": invader,
             "can_reach_dwarves": reach, "distance_to_nearest_dwarf": 20} for i in range(n)]


@test("undead odds: overwhelming past the minimum and the per-soldier share; a raiser lowers the share")
def _():
    s = state(necro={"raisers": []})
    s["military"] = dict(s.get("military") or {}, squads=squads(1, 3))
    s["others_on_map"] = {"threats": horde(6)}
    o = PC.undead_odds(s, PLANNER_CONFIG)
    assert o["n"] == 6 and o["soldiers"] == 3 and o["overwhelming"] is False, o
    s["others_on_map"] = {"threats": horde(7)}
    assert PC.undead_odds(s, PLANNER_CONFIG)["overwhelming"] is True
    s["others_on_map"] = {"threats": horde(5)}
    assert PC.undead_odds(s, PLANNER_CONFIG)["overwhelming"] is False      # under the minimum
    s["necro"] = {"raisers": [{"id": 9, "name": "Necro"}]}
    s["others_on_map"] = {"threats": horde(6)}
    assert PC.undead_odds(s, PLANNER_CONFIG)["overwhelming"] is True


@test("brain: an overwhelming siege: the kill orders on the dead dropped (others kept), squads out called back, the alarm, "
      "the bodies outside rotted; attack-everything lets them go")
def _():
    s = state(necro={"raisers": [{"id": 9, "name": "Necro"}], "surface_corpses": 12, "towers": []})
    sq = squads(2, 3)
    sq[1]["ai_orders"] = True
    sq[1]["kill_ids"] = [1000, 1001]
    s["military"] = dict(s.get("military") or {}, squads=sq)
    s["others_on_map"] = {"threats": horde(10) + [{"id": 5, "name": "goblin", "can_reach_dwarves": True}]}
    s["civ_alert"] = False
    s["civ_alert_ready"] = True
    props = [Proposal("squad_attack", {"type": "squad_orders", "squad_id": 1, "kill": [1000, 1001, 5]}, "go", 0),
             Proposal("squad_attack", {"type": "squad_orders", "squad_id": 3, "kill": [1002]}, "go", 0),
             Proposal("threat_alert", {"type": "civ_alert", "on": False}, "down", 0)]
    notes = []
    m = Memory()
    PC._necro_rule(s, PLANNER_CONFIG, props, notes, m)
    acts = [p.action for p in props]
    assert {"type": "squad_orders", "squad_id": 1, "kill": [5]} in acts, acts
    assert not any(a.get("squad_id") == 3 for a in acts), acts
    assert {"type": "squad_orders", "squad_id": 2, "clear": True} in acts, acts
    assert {"type": "civ_alert", "on": True} in acts and {"type": "civ_alert", "on": False} not in acts, acts
    assert {"type": "prune_remains"} in acts and any(p.rule == "necro_corpses" for p in props), acts
    assert any("too many to fight" in n and "raiser" in n for n in notes), notes
    assert m.captives_seen["siege"]["peak"] == 10
    assert "map-wide" in next(p.reason for p in props if p.rule == "necro_corpses")
    # (fix3) kills waiting for the butchers: the map-wide rot is not proposed (said)
    s2 = dict(s, provisions={"butchery": {"corpses": 3}})
    props2, notes2 = [], []
    PC._necro_rule(s2, PLANNER_CONFIG, props2, notes2, Memory())
    assert not any(p.rule == "necro_corpses" for p in props2), [p.rule for p in props2]
    assert any("wait for the butchers" in n for n in notes2), notes2
    s["settings"] = dict(s["settings"], attack_policy="all")
    props = [Proposal("squad_attack", {"type": "squad_orders", "squad_id": 1, "kill": [1000]}, "go", 0)]
    notes = []
    PC._necro_rule(s, PLANNER_CONFIG, props, notes, Memory())
    assert props[0].action["kill"] == [1000] and any("attack everything" in n for n in notes), notes


@test("brain: a small undead siege: the squads go; the local dead of a reanimating land (no invaders, no raiser) are no siege")
def _():
    s = state(necro={"raisers": [], "surface_corpses": 0})
    s["military"] = dict(s.get("military") or {}, squads=squads(2, 5))
    s["others_on_map"] = {"threats": horde(4)}
    props = [Proposal("squad_attack", {"type": "squad_orders", "squad_id": 1, "kill": [1000]}, "go", 0)]
    notes = []
    PC._necro_rule(s, PLANNER_CONFIG, props, notes, Memory())
    assert props[0].action["kill"] == [1000] and any("can take them" in n for n in notes), notes
    s["others_on_map"] = {"threats": horde(20, invader=False)}
    notes, props = [], []
    PC._necro_rule(s, PLANNER_CONFIG, props, notes, Memory())
    assert not props and not notes, notes


@test("brain: a necromancer tower near: said once a year, and with every siege; a far one never")
def _():
    s = state(necro={"raisers": [], "towers": [{"id": 9, "dist": 3, "way": "south", "name": "Gloom"},
                                                {"id": 8, "dist": 80, "way": "north"}]})
    m = Memory()
    _, notes = run(PC._necro_rule, s, m)
    assert any("necromancer tower (Gloom) 3 world tile(s) south" in n for n in notes), notes
    _, notes = run(PC._necro_rule, s, m)
    assert not notes, notes
    s["necro"]["towers"] = [{"id": 8, "dist": 80}]
    _, notes = run(PC._necro_rule, s, Memory())
    assert not notes


@test("plan(): the new rules run inside plan() on a calm fixture without noise or proposals")
def _():
    s = state()
    props, notes = plan(s, Memory())
    assert not any(p.rule in ("prisoner_pit", "pit_prisoners", "necro_corpses") for p in props)
    assert not any("necromancer" in n or "prisoner(s) in cages:" in n for n in notes)


if __name__ == "__main__":
    finish()
