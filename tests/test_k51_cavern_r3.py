"""(0.105.51) Bugs from the R3 live run (15 Nov), builder 27:

  1. the cavern alarm: fisherdwarves and others at the surface river
     (elevation 32, z 161; Cavern1 is z 123-146) were read as "in the
     caverns" (a feature tile), so each forgotten beast in Cavern1 raised the
     alarm, held 3 days, and raised it again for the next one (A 6, B 4, C 5,
     E 2); seal_cavern was refused "no door or hatch on the way down to lock"
     (A 12, B 9, C 7, E 7) while the planner counted "1 door(s) and hatch(es)
     on record, 1 open": that door was a cavern well's, which the seal leaves
     open (its shaft gate keeps the cavern out). Now: a cavern layer's tile
     only (the bridge; the planner drops a citizen on no cavern level), the
     well's door marked in the openings report and left out of the count, a
     refused seal not asked again while its back-off runs, and no new alarm
     for the caverns within `cavern_realarm_days` of the last let-down;
  4. seen.py: a field saved empty ([]) counts as there;
  5. a module DFHack read half written ("ai-builder: Cannot be used as a
     module", F's industry section): its flags dropped, the section tried again.
  (2 and 3, the trainee cook and the memorial orders: tests/test_r47_welfare.py.)

    python tests/test_k51_cavern_r3.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from lua_modules_util import module_src, UTIL_SRC  # noqa: E402
from harness import test, finish, skip  # noqa: E402

import planner  # noqa: E402,F401
import planner_threats as pt  # noqa: E402
from planner_core import Memory, Proposal, abs_tick, refusal_key  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = dict(pt.PLANNER_CONFIG)
DAY = 1200

# the live rows (A, 257 winter; B 251-254): Cavern1 z 123-146, the fort z 152-172
CAVERNS = [{"discovered": True, "name": "Cavern1", "open": False, "seen": 3379, "z_bottom": 123, "z_top": 146},
           {"discovered": False, "name": "Cavern2", "open": False, "seen": 0, "z_bottom": 114, "z_top": 118},
           {"discovered": False, "name": "Cavern3", "open": False, "seen": 0, "z_bottom": 19, "z_top": 23}]
WELL_HATCH = {"building": "Hatch", "built": True, "closed": False, "id": 516, "kind": "well", "locked": False,
              "source": "cavern well 13", "x": 131, "y": 129, "z": 143}
WELL_DOOR = {"building": "Door", "built": True, "closed": True, "id": 173, "kind": "gate", "locked": False,
             "source": "cavern well 13 door", "x": 116, "y": 140, "z": 165}
MASON = {"id": 17723, "name": 'Bomrek Ramsigun "Prisontour", Mason', "x": 254, "y": 201, "z": 161}
BEAST = {"id": 50, "name": "Eslul Odiumo", "kind": "forgotten beast", "layer": "Cavern1"}


def fort(down=(), openings=(WELL_HATCH, WELL_DOOR)):
    s = copy.deepcopy(BASE)
    s["map"]["elevation_offset"] = -129
    s["threats"] = {"sealed": {}, "openings": {"list": [dict(o) for o in openings], "n": len(openings)},
                    "cavern_citizens": {"list": [dict(x) for x in down], "n": len(down)}}
    s["deep"] = {"caverns": copy.deepcopy(CAVERNS), "dangers": [dict(BEAST)], "cursed": []}
    s["civ_alert"], s["civ_alert_ready"] = False, True
    return s


def run(s, m):
    props, notes = [], []
    pt._cavern_beasts(s, CFG, m, s["threats"], pt.threat_rules_of(s), props, notes)
    return props, notes


def alarm_on(props):
    return [p for p in props if p.action == {"type": "civ_alert", "on": True}]


def seals(props):
    return [p for p in props if p.rule == "seal_cavern"]


# --- the brain ---------------------------------------------------------------------

@test("1: a mason at the surface river (z 161, Cavern1 z 123-146) is no citizen in the caverns: no alarm, nothing held")
def _():
    s = fort(down=[MASON])
    m = Memory()
    props, notes = run(s, m)
    assert not alarm_on(props) and not any("in the caverns" in n for n in notes), (props, notes)
    assert pt.alarm_held(s, m, CFG) == ""
    assert pt.cavern_down(s["threats"], CAVERNS) == []
    # one down in Cavern1 is: the alarm calls them up, and holds
    s = fort(down=[dict(MASON, z=130)])
    props, notes = run(s, Memory())
    assert alarm_on(props), (props, notes)
    assert "in the caverns" in pt.alarm_held(s, Memory(), CFG)
    # levels unknown: everyone the bridge names counts, as before
    s = fort(down=[MASON])
    for c in s["deep"]["caverns"]:
        c.pop("z_top")
    assert alarm_on(run(s, Memory())[0])


@test("1: the cavern well's door the seal leaves open isn't counted: no seal asked of the bridge (B's rows, 251-254)")
def _():
    door = dict(WELL_DOOR, seal_skip="cavern well 13: its shaft gate keeps the cavern out (open); the door would "
                                     "cut the well off")
    s = fort(openings=[WELL_HATCH, door])
    props, notes = run(s, Memory())
    assert not seals(props), [(p.rule, p.action, p.reason) for p in seals(props)]
    # a dwarf beyond it: not counted either (the bridge waits for them)
    s = fort(openings=[WELL_HATCH, dict(WELL_DOOR, well_blocked="Urist")])
    assert not seals(run(s, Memory())[0])
    # an ordinary door on the way down: locked as before
    s = fort(openings=[WELL_HATCH, dict(WELL_DOOR, source="cavern entrance 4")])
    p = seals(run(s, Memory())[0])
    assert p and p[0].action["type"] == "seal_cavern" and "1 door(s) and hatch(es) on record, 1 open" in p[0].reason


@test("1: a seal refused 'no door or hatch on the way down to lock' isn't asked again while its back-off runs")
def _():
    s = fort(openings=[WELL_HATCH, dict(WELL_DOOR, source="cavern entrance 4")])
    m = Memory()
    p = seals(run(s, m)[0])
    assert p
    key = refusal_key(p[0])
    m.refusals[key] = {"n": 1, "until": abs_tick(s) + DAY, "at": abs_tick(s),
                       "why": "no door or hatch on the way down to lock"}
    assert not seals(run(s, m)[0])
    # another refusal ("locked already") doesn't hold it here; nor one whose back-off ran out
    m.refusals[key] = {"n": 1, "until": abs_tick(s) + DAY, "at": abs_tick(s), "why": "something else"}
    assert seals(run(s, m)[0])
    m.refusals[key] = {"n": 1, "until": abs_tick(s) - 1, "at": abs_tick(s) - DAY,
                       "why": "no door or hatch on the way down to lock"}
    assert seals(run(s, m)[0])
    # the caverns open to the fort and nothing lockable left: the way down closed (mapped first)
    s = fort(openings=[WELL_HATCH, dict(WELL_DOOR, source="cavern entrance 4")])
    s["deep"]["caverns"][0]["open"] = True
    m.refusals[key]["until"] = abs_tick(s) + DAY
    props, _ = run(s, m)
    assert not seals(props) and any(p.action.get("type") == "scan_entrances" for p in props), \
        [(p.rule, p.action) for p in props]


@test("1: after the alarm was let down for the caverns, the next dwarf down raises none for cavern_realarm_days")
def _():
    down = [dict(MASON, z=130)]
    s = fort(down=down)
    s["civ_alert"] = True
    m = Memory()
    m.ai_alert_raised = True
    now = abs_tick(s)
    # held 3 days: let down, and the let-down remembered
    m.cavern_alarm = {"since": now - 3 * DAY}
    props, notes = run(s, m)
    assert any(p.action == {"type": "civ_alert", "on": False} for p in props), props
    assert m.cavern_alarm.get("lifted") == now, m.cavern_alarm
    # they came up: the hold forgotten, the let-down kept
    s["threats"]["cavern_citizens"] = {"n": 0, "list": []}
    run(s, m)
    assert m.cavern_alarm == {"lifted": now}, m.cavern_alarm
    # the next fisher goes down two days later: no alarm, the ways down locked, said
    s = fort(down=down)
    s["date"]["tick"] += 2 * DAY
    props, notes = run(s, m)
    assert not alarm_on(props), props
    assert any("went down into the caverns again" in n for n in notes), notes
    assert pt.alarm_held(s, m, CFG) == ""
    # a week on: the alarm again
    s = fort(down=down)
    s["date"]["tick"] += CFG["cavern_realarm_days"] * DAY
    m.cavern_alarm = {"lifted": now}
    props, notes = run(s, m)
    assert alarm_on(props), (props, notes)
    assert CFG["cavern_realarm_days"] == 7


# --- 4. seen.py ----------------------------------------------------------------------

@test("4: seen.py: a field saved empty ([] from an empty Lua table) counts as there; one missing still doesn't")
def _():
    import seen
    reg = seen.registry(ROOT)
    st = {"perf": {"sections": {"x": 1}, "cache_age": []}}
    r = seen.match_line("state.json `perf.cache_age`: no section older than its maximum", reg, {}, st, {})
    assert r["status"] == "seen", r
    st = {"perf": {"sections": {"x": 1}}}
    r = seen.match_line("state.json `perf.cache_age`: no section older than its maximum", reg, {}, st, {})
    assert r["status"] == "not met" and "field not in the report" in r["evidence"][0], r


# --- the Lua side --------------------------------------------------------------------

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

THREATS_GAME = r"""
local src = ...
local G = {saved = {}, citizens = {}, tiles = {}, mods = {}, flags = {}, blocks = {}}
local e = setmetatable({G = G}, {__index = _G})
e.reqscript = function(n) return G.mods[n] end
e.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
local feats = {map_features = {}, feature_global_idx = {}}
G.feats = feats
e.df = {global = {cur_year = 1, cur_year_tick = 0, world = {features = feats}},
        building = {find = function(id) for _, b in pairs(G.tiles) do if b.id == id then return b end end end},
        building_type = {Door = 'Door', Hatch = 'Hatch'},
        feature_init_subterranean_from_layerst = {is_instance = function(_, f) return f.cavern == true end}}
e.dfhack = {persistent = {getSiteData = function(k, d) return G.saved[k] or d end,
                          saveSiteData = function(k, v) G.saved[k] = v end},
            units = {getReadableName = function(u) return u.name end, getCitizens = function() return G.citizens end},
            buildings = {findAtTile = function(p) return G.tiles[p.x .. ',' .. p.y .. ',' .. p.z] end},
            maps = {getTileFlags = function(x, y, z) return G.flags[z] or {} end,
                    getTileBlock = function(x, y, z)
                        if type(x) == 'table' then x, y, z = x.x, x.y, x.z end
                        local g = G.blocks[z]
                        if g == nil then return nil end
                        return {global_feature = g}
                    end},
            gui = {showAnnouncement = function() end}}
function G.bld(id, ty) return {id = id, jobs = {}, door_flags = {forbidden = false, closed = true},
    getType = function() return ty end, getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end} end
assert(load(src, 'ai-threats', 't', e))()
return e
"""


def rig():
    lua = LuaRuntime(unpack_returned_tuples=True)
    E = lua.execute(THREATS_GAME, module_src("ai-threats.lua"))
    return lua, E


def py(v):
    if hasattr(v, "items"):
        d = dict(v.items())
        if d and all(isinstance(k, int) for k in d):
            return [py(d[k]) for k in sorted(d)]
        return {k: py(x) for k, x in d.items()}
    return v


@test("1 lua: cavern_citizens counts a cavern layer's tile only (the surface river's feature tiles not); unknown layers: the flags, as before")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    lua, E = rig()
    G = E.G
    t = lua.table_from
    # world features: index 0 a river-like local feature (not a cavern), 1 Cavern1 (global index 7)
    G.feats.map_features = t({1: t({"cavern": False}), 2: t({"cavern": True})})
    G.feats.feature_global_idx = t({1: 3, 2: 7})
    # lupa tables are 1-based; the module reads them with ipairs: indices as Lua gives them
    G.flags[161] = t({"feature_local": True})      # the surface river
    G.flags[130] = t({"feature_global": True})     # Cavern1
    G.blocks[161] = -1
    G.blocks[130] = 7
    G.citizens = t({1: t({"id": 1, "name": "Mason", "pos": t({"x": 254, "y": 201, "z": 161})}),
                    2: t({"id": 2, "name": "Fisher", "pos": t({"x": 10, "y": 10, "z": 130})})})
    r = py(E.cavern_citizens())
    assert r["n"] == 1 and r["list"][0]["name"] == "Fisher", r
    # the seal's own check: the mason doesn't hold it
    gids = E.cavern_gids()
    assert E.on_cavern_tile(254, 201, 161, gids) is False and E.on_cavern_tile(10, 10, 130, gids) is True
    # the layers can't be read: every feature tile counts, as before
    G.feats.map_features = t({})
    assert py(E.cavern_citizens())["n"] == 2


@test("1 lua: the openings report marks a cavern well's door the seal leaves open; the seal says so, not 'no door or hatch'")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    lua, E = rig()
    G = E.G
    t = lua.table_from
    G.tiles["116,140,165"] = G.bld(173, "Door")
    why = "cavern well 13: its shaft gate keeps the cavern out (open); the door would cut the well off"
    G.mods["ai-well-safety"] = t({"door_blocked": lambda o, *a: None, "door_seal_skip": lambda o: why,
                                  "fort_doors": lambda: t({})})
    d = E.load_state()
    E.note_opening(d, 116, 140, 165, "gate", "cavern well 13 door", 0)
    rep = py(E.openings_report(d, 0, None))
    row = rep["list"][0]
    assert row["building"] == "Door" and row["seal_skip"] == why and "well_blocked" not in row, row
    E.reqscript("ai-util").site_put(E.STATE_KEY, d)
    r = py(E.seal_cavern("all caverns", t({}), False, False, 19, 146, True))
    assert r["ok"] is False and r.get("nothing_to_do") is True and r["well_kept"] == 1, r
    assert "no door or hatch" not in r["error"] and "cavern well" in r["error"], r
    assert G.tiles["116,140,165"].door_flags.forbidden is False
    # a dwarf beyond it: waiting (tried again soon), not nothing to do
    G.mods["ai-well-safety"] = t({"door_blocked": lambda o, *a: "Urist", "door_seal_skip": lambda o: None,
                                  "fort_doors": lambda: t({})})
    r = py(E.seal_cavern("all caverns", t({}), False, False, 19, 146, True))
    assert r.get("waiting") is True and not r.get("nothing_to_do") and "Urist" in r["error"], r
    assert py(E.openings_report(E.load_state(), 0, None))["list"][0]["well_blocked"] == "Urist"
    # no well about it: locked as before
    G.mods["ai-well-safety"] = None
    r = py(E.seal_cavern("all caverns", t({}), False, False, 19, 146, True))
    assert r["ok"] is True and r["locked"] == 1 and G.tiles["116,140,165"].door_flags.forbidden is True, r


UTIL_GAME = r"""
local src = ...
local G = {scripts = {}}
local e = setmetatable({G = G}, {__index = _G})
e.dfhack = {findScript = function(n) return 'hack/scripts/' .. n .. '.lua' end, internal = {scripts = G.scripts}}
e.df = {global = {}}
e.reqscript = function() error('no') end
assert(load(src, 'ai-util', 't', e))()
return e
"""


@test("5 lua: 'ai-builder: Cannot be used as a module' drops the module's cached flags (read again next time); other errors untouched")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    lua = LuaRuntime(unpack_returned_tuples=True)
    src = UTIL_SRC   # (r9) ai-util with its parts
    E = lua.execute(UTIL_GAME, src)
    t = lua.table_from
    sc = t({"flags_mtime": 1731620000, "_flags": t({})})
    E.G.scripts["hack/scripts/ai-builder.lua"] = sc
    err = r"D:\SteamLibrary\steamapps\common\DFHack\hack\lua\dfhack.lua:1106: ai-builder: Cannot be used as a module"
    assert E.module_flags_reset(err) == "ai-builder"
    assert sc.flags_mtime is None
    assert E.module_flags_reset("ai-builder: attempt to index a nil value") is None
    assert E.module_flags_reset(r"x.lua:1: ai-gates: Cannot be used as a module") is None    # not loaded: nothing
    # the bridge tries the section once more after it
    b = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    i = b.index("local v, nocache = SECTIONS[name](ctx)")
    seg = b[i:i + 700]
    assert "module_flags_reset(v.error)" in seg and seg.count("SECTIONS[name](ctx)") == 2, seg


finish()
