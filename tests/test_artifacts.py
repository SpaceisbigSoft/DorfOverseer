"""(item 12) The fort's artifacts shown and kept safe: lua/ai-artifacts.lua in
a fake fort (the report: the artifacts and where each is, the AI's and the
player's by the first id, the claims of other civs, the display furniture,
the AI's rooms with their doors and open ways out; place_display only in the
AI's rooms; display_artifact only the AI's loose artifact onto the AI's
furniture with room, as DF's put-on-display job), the bridge's wiring, the
guards that keep an artifact from being sold, melted, dumped or destroyed,
and the brain (brain/planner_artifacts.py).

    python tests/test_artifacts.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish, code_has  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan, player_rules  # noqa: E402
import planner_artifacts as PA  # noqa: E402
import digest  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"
CFG = PLANNER_CONFIG
BRIDGE = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
ACTS = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")

# A fort level at z 100. W.zone{...} a zone (a location's with loc = {type,
# visitors}, else a dining hall), W.art{...} an artifact item with its
# record, W.tool{kind} a free pedestal or case, W.display{...} display
# furniture. The builder stub: tile_info (WALL unless W.tiles says), door_at,
# zone_area, zone_spots; ai_boxes from W.boxes.
FAKE = r"""
local src = ...
local W = {site = {}, items = {}, tools = {}, records = {}, displays = {}, locs = {}, dining = {}, meeting = {},
           zones = {}, tiles = {}, doors = {}, boxes = {}, assigned = {}, all_items = {}, jobs = {}, next_id = 1000,
           built_fail = false}
local env = setmetatable({}, {__index = _G})
local function key(x, y, z) return x .. ',' .. y .. ',' .. z end
local function nid() W.next_id = W.next_id + 1; return W.next_id end
local function find_building(id)
    for _, z in pairs(W.zones) do if z.id == id then return z end end
    for _, b in ipairs(W.displays) do if b.id == id then return b end end
end
function W.zone(t)
    t.id = t.id or nid(); t.z = t.z or 100
    W.zones[t.id] = t
    if t.loc then
        local loc = {id = nid(), flags = {VISITORS_ALLOWED = t.loc.visitors == true}}
        loc.getType = function() return t.loc.type end
        loc.getContents = function() return {building_ids = {t.id}} end
        table.insert(W.locs, loc)
        t.location_id = loc.id
    else
        table.insert(W.dining, t)
    end
    return t
end
-- a closed room: walls all round (the default), doors where asked
function W.door(x, y, z) W.tiles[key(x, y, z or 100)] = {shape = 'FLOOR', building = true}; W.doors[key(x, y, z or 100)] = true end
function W.gap(x, y, z) W.tiles[key(x, y, z or 100)] = {shape = 'FLOOR'} end
function W.art(t)
    local it = {id = t.item_id or nid(), flags = t.flags or {artifact = true, on_ground = true}, kind = t.kind or 'WEAPON',
                pos = t.pos or {x = 1, y = 1, z = 100}, holder_b = t.holder_b, holder_u = t.holder_u}
    it.getType = function(self) return self.kind end
    if t.subtype then it.subtype = {id = t.subtype} end
    local rec = {id = t.id, item = it, name = t.name or ('Art' .. t.id), entity_claims = t.claims or {}}
    it.art = t.id
    table.insert(W.records, rec)
    table.insert(W.items, it)
    W.all_items[it.id] = it
    return it
end
function W.tool(kind)
    local it = {id = nid(), flags = {on_ground = true}, kind = 'TOOL',
                subtype = {id = kind == 'case' and 'ITEM_TOOL_DISPLAY_CASE' or 'ITEM_TOOL_PEDESTAL'}}
    it.getType = function(self) return self.kind end
    table.insert(W.tools, it)
    W.all_items[it.id] = it
    return it
end
function W.display(t)
    local tool = {id = nid(), flags = {}, kind = 'TOOL',
                  subtype = {id = t.kind == 'case' and 'ITEM_TOOL_DISPLAY_CASE' or 'ITEM_TOOL_PEDESTAL'}}
    local b = {id = t.id or nid(), x1 = t.x, y1 = t.y, centerx = t.x, centery = t.y, z = t.z or 100,
               contained_items = {{item = tool}}, displayed_items = t.shown or {}, jobs = {}}
    b.getBuildStage = function() return t.built == false and 0 or 1 end
    b.getMaxBuildStage = function() return 1 end
    b.getType = function() return 'DisplayFurniture' end
    table.insert(W.displays, b)
    return b
end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {
    global = {world = {artifacts = {all = W.records},
                       items = {other = {ANY_ARTIFACT = W.items, TOOL = W.tools}},
                       buildings = {other = {DISPLAY_CASE = W.displays, ZONE_DINING_HALL = W.dining,
                                             ZONE_MEETING_HALL = W.meeting}}},
              plotinfo = {civ_id = 1, group_id = 2, equipment = {items_assigned = {W.assigned}}}},
    general_ref_type = {IS_ARTIFACT = 'IS_ARTIFACT', BUILDING_HOLDER = 'BUILDING_HOLDER'},
    artifact_record = {find = function(id) for _, r in ipairs(W.records) do if r.id == id then return r end end end},
    historical_entity = {find = function(id) return {name = 'Civ' .. id} end},
    abstract_building_type = setmetatable({}, {__index = function(_, k) return k end}),
    item_type = setmetatable({}, {__index = function(_, k) return k end}),
    building = {find = find_building},
    building_type = {DisplayFurniture = 'DisplayFurniture'},
    job_type = {PutItemOnDisplay = 'PutItemOnDisplay'},
    job_item_ref = {T_role = {Hauled = 'Hauled'}},
    item = {find = function(id) return W.all_items[id] end},
    job = {new = function() return {id = nid(), refs = {}, items = {}} end},
}
env.dfhack = {
    items = {getGeneralRef = function(it, t) return it.art and {artifact_id = it.art} or nil end,
             getHolderBuilding = function(it) return it.holder_b end,
             getHolderUnit = function(it) return it.holder_u end,
             getPosition = function(it) if not it.pos then return nil end return it.pos.x, it.pos.y, it.pos.z end},
    translation = {translateName = function(n) return n end},
    df2utf = function(s) return s end,
    world = {getCurrentSite = function() return {buildings = W.locs} end},
    buildings = {
        findCivzonesAt = function(p)
            local out = {}
            for _, z in pairs(W.zones) do
                if z.z == p.z and p.x >= z.x1 and p.x <= z.x2 and p.y >= z.y1 and p.y <= z.y2 then table.insert(out, z) end
            end
            return out
        end,
        constructBuilding = function(t)
            if W.built_fail then return nil, 'blocked' end
            local b = W.display{x = t.pos.x, y = t.pos.y, z = t.pos.z, kind = t.items[1].subtype.id == 'ITEM_TOOL_DISPLAY_CASE' and 'case' or 'pedestal', built = false}
            t.items[1].flags.in_building = true
            return b
        end},
    job = {addGeneralRef = function(j, t, id) table.insert(j.refs, {t, id}) end,
           attachJobItem = function(j, it, role) table.insert(j.items, {it, role}); it.flags.in_job = true; return true end,
           linkIntoWorld = function(j) table.insert(W.jobs, j) end,
           removeJob = function() end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
assert(load(src, 'ai-artifacts', 't', env))()
local B = {}
function B.tile_info(x, y, z)
    local t = W.tiles[key(x, y, z)]
    if t then return t end
    for _, zn in pairs(W.zones) do
        if zn.z == z and x >= zn.x1 and x <= zn.x2 and y >= zn.y1 and y <= zn.y2 then return {shape = 'FLOOR', outside = zn.outside} end
    end
    return {shape = 'WALL'}
end
function B.door_at(x, y, z) return W.doors[key(x, y, z)] == true end
function B.zone_area(id) local z = W.zones[id]; return z and {x1 = z.x1, y1 = z.y1, x2 = z.x2, y2 = z.y2, z = z.z} end
function B.zone_spots(area) return {{x = area.x1, y = area.y1, walls = 1}} end
env.builder = function() return B end
env.ai_boxes = function() return W.boxes end
-- jobs list with insert('#', x)
local jobs_mt = {__index = {insert = function(self, _, j) rawset(self, #self + 1, j) end}}
W.with_jobs = function(b) setmetatable(b.jobs, jobs_mt) end
return env, W
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-artifacts.lua"))
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


def temple(lua, w, x1=10, y1=10, visitors=False, door=True, gap=False, ai=True, kind="TEMPLE"):
    z = w.zone(T(lua, {"x1": x1, "y1": y1, "x2": x1 + 4, "y2": y1 + 4, "loc": {"type": kind, "visitors": visitors}}))
    if door:
        w.door(x1 + 2, y1 - 1)
    if gap:
        w.gap(x1 + 5, y1 + 2)
    if ai:
        n = len(py(w.boxes) or [])
        w.boxes[n + 1] = T(lua, {"x1": x1 - 1, "y1": y1 - 1, "x2": x1 + 5, "y2": y1 + 5, "z": 100})
    return z


def first(env, w, lua, n=5):
    """the AI first looks with n records in the world: ids 0..n-1 the player's"""
    for i in range(n):
        w.art(T(lua, {"id": i, "pos": {"x": -30000, "y": -30000, "z": -30000}}))   # off the map: not listed
    return env.first_id()


# --- 1. the report ---------------------------------------------------------------------

@test("report: the first id is set once (the next id at the AI's first look) and kept; the AI's artifacts are the ones "
      "at or past it, the player's older ones reported but not the AI's")
def _():
    lua, env, w = world()
    assert first(env, w, lua, 5) == 5
    old = w.art(T(lua, {"id": 3}))
    old.pos = T(lua, {"x": 2, "y": 2, "z": 100})
    new = w.art(T(lua, {"id": 9, "name": "Gleamshield"}))
    assert env.first_id() == 5                       # kept: not moved on by the new artifact
    r = py(env.report())
    rows = {a["id"]: a for a in r["artifacts"]}
    assert set(rows) == {3, 9}, rows                 # the off-map ones not listed
    assert rows[9]["mine"] is True and rows[9]["state"] == "loose" and rows[9]["name"] == "Gleamshield"
    assert rows[3]["mine"] is False
    assert r["artifacts"][0]["id"] == 9              # the AI's loose ones first
    assert r["counts"]["total"] == 2 and r["counts"]["mine"] == 1 and r["counts"]["mine_loose"] == 1
    assert r["first_id"] == 5 and r["api"]["display_job"] is True


@test("report: each artifact's state: carried, in a job, forbidden, owned, a squad's gear, a book, displayed")
def _():
    lua, env, w = world()
    first(env, w, lua, 0)
    z = temple(lua, w)
    d = w.display(T(lua, {"x": 11, "y": 11}))
    env.registry()                                   # nothing remembered: the player's display
    arts = {
        "carried": w.art(T(lua, {"id": 1, "holder_u": {"id": 5}, "flags": {"artifact": True, "in_inventory": True}})),
        "in_job": w.art(T(lua, {"id": 2, "flags": {"artifact": True, "in_job": True}})),
        "forbidden": w.art(T(lua, {"id": 3, "flags": {"artifact": True, "forbid": True}})),
        "owned": w.art(T(lua, {"id": 4, "flags": {"artifact": True, "owned": True}})),
        "written": w.art(T(lua, {"id": 5, "kind": "BOOK"})),
        "displayed": w.art(T(lua, {"id": 6, "holder_b": d})),
        "gear": w.art(T(lua, {"id": 7})),
        "written2": w.art(T(lua, {"id": 8, "kind": "TOOL", "subtype": "ITEM_TOOL_SCROLL"})),
    }
    w.assigned[1] = arts["gear"].id
    r = py(env.report())
    st = {a["id"]: a["state"] for a in r["artifacts"]}
    assert st == {1: "carried", 2: "in_job", 3: "forbidden", 4: "owned", 5: "written", 6: "displayed", 7: "gear",
                  8: "written"}, st
    disp = r["displays"][0]
    assert disp["kind"] == "pedestal" and disp["zone_id"] == z.id and disp["location"] == "TEMPLE"
    assert disp["ai"] is False and disp["ai_room"] is True and disp["built"] is True
    assert r["counts"]["displayed"] == 1 and r["counts"]["loose"] == 0


@test("report: artifacts other civs claim (the fort's own civ and group left out), by name")
def _():
    lua, env, w = world()
    first(env, w, lua, 0)
    w.art(T(lua, {"id": 1, "claims": [1, 2, 77]}))
    w.art(T(lua, {"id": 2, "claims": [2]}))
    r = py(env.report())
    rows = {a["id"]: a for a in r["artifacts"]}
    assert rows[1]["claimed_by"] == ["Civ77"] and "claimed_by" not in rows[2]
    assert r["counts"]["claimed"] == 1


@test("report: the AI's rooms only (zone centre in a level the AI dug): doors and open ways out, secure, visitors; "
      "the player's room and its furniture not the AI's; free pedestals and cases counted")
def _():
    lua, env, w = world()
    first(env, w, lua, 0)
    shut = temple(lua, w, 10, 10)
    open_ = temple(lua, w, 30, 10, visitors=True, gap=True, kind="INN_TAVERN")
    theirs = temple(lua, w, 50, 10, ai=False, kind="LIBRARY")
    w.tool("pedestal")
    w.tool("pedestal")
    w.tool("case")
    busy = w.tool("case")
    busy.flags.in_job = True
    r = py(env.report())
    rooms = {x["zone_id"]: x for x in r["rooms"]}
    assert set(rooms) == {shut.id, open_.id}, rooms
    assert rooms[shut.id]["doors"] == 1 and rooms[shut.id]["openings"] == 0 and rooms[shut.id]["secure"] is True
    assert rooms[open_.id]["openings"] == 1 and rooms[open_.id]["secure"] is False and rooms[open_.id]["visitors"] is True
    assert rooms[shut.id]["type"] == "TEMPLE" and rooms[shut.id]["visitors"] is False
    assert r["free"] == {"pedestal": 2, "case": 1}
    assert theirs.id not in rooms


# --- 2. the actions ----------------------------------------------------------------------

@test("place_display: a free pedestal built in the AI's room, remembered as the AI's; a dry run builds nothing; "
      "the player's room refused, untouched")
def _():
    lua, env, w = world()
    first(env, w, lua, 0)
    z = temple(lua, w)
    theirs = temple(lua, w, 50, 10, ai=False)
    w.tool("pedestal")
    r = py(env.place_display(T(lua, {"zone_id": z.id, "kind": "pedestal"}), True))
    assert r["ok"] and r["dry_run"] and len(py(w.displays) or []) == 0, r
    r = py(env.place_display(T(lua, {"zone_id": theirs.id, "kind": "pedestal"}), False))
    assert r["rejected"] and "player" in r["error"] and len(py(w.displays) or []) == 0, r
    r = py(env.place_display(T(lua, {"zone_id": z.id, "kind": "pedestal"}), False))
    assert r["ok"] and r["location"] == "TEMPLE" and (r["x"], r["y"]) == (10, 10), r
    assert py(env.registry())["displays"] == [r["building_id"]]
    rep = py(env.report())
    assert rep["displays"][0]["ai"] is True and rep["displays"][0]["built"] is False
    assert rep["free"]["pedestal"] == 0
    r = py(env.place_display(T(lua, {"zone_id": z.id, "kind": "pedestal"}), False))
    assert r["rejected"] and "no free pedestal" in r["error"]
    assert py(env.place_display(T(lua, {"zone_id": z.id, "kind": "throne"}), False))["rejected"]


@test("display_artifact: the AI's loose artifact onto the AI's built furniture with room: a put-on-display job "
      "(the artifact hauled, the furniture its holder)")
def _():
    lua, env, w = world()
    first(env, w, lua, 0)
    temple(lua, w)
    d = w.display(T(lua, {"x": 11, "y": 11}))
    w.with_jobs(d)
    reg = env.registry()
    reg.displays[1] = d.id
    w.site["ai-overseer/artifacts"] = reg
    it = w.art(T(lua, {"id": 3}))
    r = py(env.display_artifact(T(lua, {"item_id": it.id, "building_id": d.id}), True))
    assert r["ok"] and r["dry_run"] and not py(w.jobs), r
    r = py(env.display_artifact(T(lua, {"item_id": it.id, "building_id": d.id}), False))
    assert r["ok"] and r["name"] == "Art3", r
    job = w.jobs[1]
    assert job.job_type == "PutItemOnDisplay" and job.pos.x == 11
    assert job.refs[1][1] == "BUILDING_HOLDER" and job.refs[1][2] == d.id
    assert job["items"][1][1].id == it.id and job["items"][1][2] == "Hauled"
    assert d.jobs[1].id == job.id
    # a pedestal holds one: the job waiting fills it
    other = w.art(T(lua, {"id": 4}))
    r = py(env.display_artifact(T(lua, {"item_id": other.id, "building_id": d.id}), False))
    assert r["rejected"] and "holds 1" in r["error"], r


@test("display_artifact: refused for the player's artifact, the player's furniture, unbuilt furniture, a carried, "
      "forbidden or busy artifact, a plain item, a DF without the job")
def _():
    lua, env, w = world()
    first(env, w, lua, 2)
    temple(lua, w)
    mine_d = w.display(T(lua, {"x": 11, "y": 11}))
    theirs_d = w.display(T(lua, {"x": 12, "y": 11}))
    unbuilt = w.display(T(lua, {"x": 13, "y": 11, "built": False}))
    for b in (mine_d, theirs_d, unbuilt):
        w.with_jobs(b)
    reg = env.registry()
    reg.displays[1] = mine_d.id
    reg.displays[2] = unbuilt.id
    w.site["ai-overseer/artifacts"] = reg
    old = w.art(T(lua, {"id": 1}))
    old.pos = T(lua, {"x": 3, "y": 3, "z": 100})
    good = w.art(T(lua, {"id": 5}))
    carried = w.art(T(lua, {"id": 6, "holder_u": {"id": 1}, "flags": {"artifact": True, "in_inventory": True}}))
    forbidden = w.art(T(lua, {"id": 7, "flags": {"artifact": True, "forbid": True}}))
    plain = w.tool("pedestal")

    def go(item, b):
        return py(env.display_artifact(T(lua, {"item_id": item.id, "building_id": b.id}), False))
    assert "before the AI" in go(old, mine_d)["error"]
    assert "no display furniture the AI placed" in go(good, theirs_d)["error"]
    assert "not built" in go(good, unbuilt)["error"]
    assert "carried" in go(carried, mine_d)["error"]
    assert "forbidden" in go(forbidden, mine_d)["error"]
    assert "no artifact" in go(plain, mine_d)["error"]
    env.df.job_type.PutItemOnDisplay = None
    assert "no put-on-display job" in go(good, mine_d)["error"]
    assert not py(w.jobs)


@test("(fix5) display_artifact: no hauler sent for an artifact near a danger or out of the citizens' reach "
      "(or to a display out of reach); the game unable to say: as before")
def _():
    lua, env, w = world()
    first(env, w, lua, 0)
    temple(lua, w)
    d = w.display(T(lua, {"x": 11, "y": 11}))
    w.with_jobs(d)
    reg = env.registry()
    reg.displays[1] = d.id
    w.site["ai-overseer/artifacts"] = reg
    it = w.art(T(lua, {"id": 3}))                       # at (1, 1, 100)

    def go():
        return py(env.display_artifact(T(lua, {"item_id": it.id, "building_id": d.id}), True))
    assert go()["ok"]
    env.danger_spots = lua.eval("function() return {{x = 2, y = 2, z = 100}} end")
    r = go()
    assert r["rejected"] and "near a danger" in r["error"], r
    env.danger_spots = lua.eval("function() return {{x = 12, y = 12, z = 100}} end")
    r = go()
    assert r["rejected"] and "the display" in r["error"], r
    env.danger_spots = lua.eval("function() return {} end")
    env.citizen_groups = lua.eval("function() return {[1] = true} end")
    env.walk_group = lua.eval("function(x, y, z) if x < 5 then return 2 end return 1 end")
    r = go()
    assert r["rejected"] and "reach" in r["error"], r
    env.walk_group = lua.eval("function(x, y, z) if x >= 10 then return 0 end return 1 end")
    r = go()
    assert r["rejected"] and "reach (the display)" in r["error"], r
    env.walk_group = lua.eval("function(x, y, z) if x == 11 and y == 11 then return 0 end return 1 end")
    assert go()["ok"]                                   # the pedestal's own tile unwalkable, beside it in reach


@test("(fix5) the display list is buildings.other.DISPLAY_CASE (df-structures' name), every building the fallback; "
      "the display_artifacts switch on the Rules tab, set on refresh, clear of the other controls")
def _():
    src = (LUA_DIR / "ai-artifacts.lua").read_text(encoding="utf-8")
    assert "buildings.other.DISPLAY_CASE end" in src and "DISPLAY_FURNITURE end" not in src
    lua, env, w = world()
    w.display(T(lua, {"x": 11, "y": 11}))
    assert len(py(env.display_buildings())) == 1
    env.df["global"]["world"]["buildings"]["other"]["DISPLAY_CASE"] = None
    env.df["global"]["world"]["buildings"]["all"] = w.displays
    assert len(py(env.display_buildings())) == 1        # the fallback
    gui = (LUA_DIR / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
    assert "view_id = 'display_artifacts'" in gui and "subviews.display_artifacts:setOption" in gui
    import re
    jrow, hrow, t = 8, 2, 14
    page = gui[gui.index("function RulesPage:init()"):gui.index("MilitaryPage = defclass")]
    frames = []
    for m in re.finditer(r"view_id = '(\w+)',\s*frame = \{t = ([^,]+), l = (\d+), w = (\d+)\}", page):
        expr = m.group(2)
        if "i" in expr.replace("hrow", "").replace("jrow", ""):
            continue                                    # the levels' loop rows (left column, l < 56)
        frames.append((eval(expr, {"jrow": jrow, "hrow": hrow, "t": t}), int(m.group(3)), int(m.group(4)),
                       m.group(1)))
    for m in re.finditer(r"widgets\.Label\{frame = \{t = ([^,]+), l = (\d+)\}, text = \{\s*\{text = '([^']*)'", page):
        frames.append((eval(m.group(1), {"jrow": jrow, "hrow": hrow, "t": t}), int(m.group(2)), len(m.group(3)),
                       "label"))
    mine = [f for f in frames if f[3] == "display_artifacts"]
    assert len(mine) == 1, frames
    r, l, wd, _ = mine[0]
    for r2, l2, w2, v in frames:
        if v != "display_artifacts" and r2 == r:
            assert l2 + w2 <= l or l + wd <= l2, (mine[0], (r2, l2, w2, v))
    assert l >= 52                                      # clear of the levels' rows (l 2, w 50)


# --- 3. the bridge and the guards ----------------------------------------------------------

@test("bridge: place_display and display_artifact in ACTIONS and DRY_OK, the artifacts section (cached a day, "
      "cleared by the actions), ai-artifacts in BRIDGE_MODULES; the handlers check their arguments")
def _():
    dry = BRIDGE[BRIDGE.index("DRY_OK = {}"):BRIDGE.index("}) do DRY_OK[name] = true end")]
    for a in ("place_display", "display_artifact"):
        assert code_has(BRIDGE, f"{a} = act_{a},"), a
        assert f"'{a}'" in dry, a
        assert f"function act_{a}(a)" in ACTS
        assert f"CACHE_INVALIDATES.{a} = {{'artifacts'}}" in BRIDGE
    assert code_has(BRIDGE, "artifacts = function() return safe(function() return reqscript('ai-artifacts').report() end) end,")
    assert "SECTION_CACHE_DAYS.artifacts = 1" in BRIDGE
    mods = BRIDGE[BRIDGE.index("BRIDGE_MODULES = {"):BRIDGE.index("}", BRIDGE.index("BRIDGE_MODULES = {"))]
    assert "'ai-artifacts'" in mods
    lua = LuaRuntime(unpack_returned_tuples=True)
    f = lua.eval("""function(src)
        local seen = {}
        local env = setmetatable({BRIDGE_VERSION = 'x', OUT_DIR = '/tmp'}, {__index = _G})
        env.require = function(n) return {} end
        env.reject = function(m) return {ok = false, rejected = true, error = m} end
        env.whole_number = function(v) return math.tointeger(tonumber(v)) end
        env.int_in = function(v, lo, hi) local n = math.tointeger(tonumber(v)); if n == nil or n < lo or n > hi then return nil end return n end
        env.reqscript = function(n)
            assert(n == 'ai-artifacts')
            return {place_display = function(o, dry) seen[#seen + 1] = {'place', o, dry}; return {ok = true} end,
                    display_artifact = function(o, dry) seen[#seen + 1] = {'show', o, dry}; return {ok = true} end}
        end
        assert(load(src, 'actions', 't', env))()
        return env, seen
    end""")
    env, seen = f(ACTS)
    assert env.act_place_display(T(lua, {})).rejected
    assert env.act_place_display(T(lua, {"zone_id": 3, "kind": "throne"})).rejected
    assert env.act_display_artifact(T(lua, {"item_id": 3})).rejected
    assert env.act_place_display(T(lua, {"zone_id": 3, "dry_run": True})).ok
    last = seen[len(seen)]
    assert last[1] == "place" and last[2].kind == "pedestal" and last[3] is True
    assert env.act_display_artifact(T(lua, {"item_id": 3, "building_id": 4})).ok
    assert seen[len(seen)][2].building_id == 4 and seen[len(seen)][3] is False
    src = (LUA_DIR / "ai-artifacts.lua").read_text(encoding="utf-8")
    assert lua.eval("function(s) local f, e = load(s, 'c', 't', {}); return e end")(src) is None
    assert "--@ module = true" in src


@test("guards: an artifact is never sold (ai-trade), melted, dumped or removed from the dump (ai-disposal), deleted "
      "(ai-cleanup), nor free for a job (ai-util)")
def _():
    trade = (LUA_DIR / "ai-trade.lua").read_text(encoding="utf-8")
    assert "local function unsellable(item) return not U.item_free(item, HELD_OK) end" in trade
    assert "and not banned(item) and not is_artifact(item) then" in trade
    disp = (LUA_DIR / "ai-disposal.lua").read_text(encoding="utf-8")
    blocked = disp[disp.index("function blocked("):disp.index("local function position(")]
    assert "if f.artifact then return 'artifact' end" in blocked
    for fn in ("function melt_check(", "function mark_dump(", "function empty_dump("):
        body = disp[disp.index(fn):]
        body = body[:body.index("\nend\n")]
        assert "blocked(it, x, y, z" in body, fn
    clean = (LUA_DIR / "ai-cleanup.lua").read_text(encoding="utf-8")
    keep = clean[clean.index("function item_keep("):]
    assert "if f.artifact or fl(f, 'artifact_mood') or has_ref(it, 'IS_ARTIFACT') then return 'artifact' end" in keep[:600]
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute("""
        local src = ...
        local env = setmetatable({}, {__index = _G})
        env.dfhack = {items = {getHolderUnit = function() return nil end}}
        assert(load(src, 'ai-util', 't', env))()
        return env
    """, (LUA_DIR / "ai-util.lua").read_text(encoding="utf-8"))
    it = T(lua, {"flags": {"artifact": True, "on_ground": True}})
    assert env.item_unfree(it)[0] == "artifact"


# --- 4. the brain ------------------------------------------------------------------------------

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def room(zid, type_="TEMPLE", secure=True, visitors=False, displays=0, outside=False):
    return {"zone_id": zid, "type": type_, "secure": secure, "visitors": visitors, "displays": displays,
            "outside": outside, "doors": 1, "openings": 0 if secure else 2}


def art(id_, mine=True, state="loose", claimed=None, name=None):
    a = {"id": id_, "item_id": 100 + id_, "mine": mine, "state": state, "kind": "WEAPON"}
    if claimed:
        a["claimed_by"] = claimed
    if name:
        a["name"] = name
    return a


def disp(id_, zid, kind="pedestal", items=0, ai=True, built=True):
    return {"id": id_, "zone_id": zid, "kind": kind, "items": items, "ai": ai, "built": built}


def section(arts=(), rooms=(), displays=(), free=None, api=True):
    return {"artifacts": [dict(a) for a in arts], "rooms": [dict(r) for r in rooms],
            "displays": [dict(d) for d in displays], "free": free or {"pedestal": 0, "case": 0},
            "api": {"display_job": api}, "counts": {"total": len(arts)}}


def fort(sec=None, **settings) -> dict:
    s = copy.deepcopy(BASE)
    if sec is not None:
        s["artifacts"] = sec
    if settings:
        s.setdefault("settings", {}).update(settings)
    return digest.normalize(s)


def run(s):
    props, notes = [], []
    PA._artifact_rule(s, CFG, props, notes, player_rules(s))
    return props, notes


@test("brain: the AI's loose artifact goes onto the AI's display with room in the safest room (closed to visitors "
      "first), the claimed one first; never the player's artifact")
def _():
    sec = section([art(1), art(2, claimed=["the Goblins"]), art(3, mine=False)],
                  [room(10, visitors=True), room(11)],
                  [disp(50, 10), disp(51, 11), disp(52, 11, items=1)])
    props, _ = run(fort(sec))
    assert len(props) == 1 and props[0].rule == "artifact_display", props
    assert props[0].action == {"type": "display_artifact", "item_id": 102, "building_id": 51}, props[0].action
    assert "Goblins" in props[0].reason
    props, _ = run(fort(section([art(3, mine=False)], [room(11)], [disp(51, 11)])))
    assert not props


@test("brain: no display with room: a free case (else pedestal) built in the safest room; one being built is waited "
      "for; none free: stone pedestals ordered (not twice, not while stone is short)")
def _():
    s = fort(section([art(1), art(2)], [room(10, "DiningHall"), room(11), room(12, outside=True)],
                     [disp(50, 11, items=1)], free={"pedestal": 1, "case": 1}))
    props, _ = run(s)
    assert props[0].rule == "artifact_furniture" and props[0].action == {"type": "place_display", "zone_id": 11,
                                                                          "kind": "case"}, props[0].action
    s = fort(section([art(1)], [room(11)], [disp(50, 11, built=False)], free={"pedestal": 2, "case": 0}))
    assert run(s)[0] == []
    s = fort(section([art(1), art(2)], [room(11)]))
    props, _ = run(s)
    assert props[0].rule == "artifact_pedestals" and props[0].is_order
    assert props[0].action == {"type": "work_order", "recipe": "stone_pedestal", "amount": 2}
    s2 = copy.deepcopy(s)
    s2["orders"] = [{"recipe": "stone_pedestal", "amount_left": 2}]
    assert run(s2)[0] == []
    s3 = copy.deepcopy(s)
    s3["stone_use"] = {"usable": 2}
    assert run(s3)[0] == []


@test("brain: only rooms shut in by doors (artifact_display_need_doors), open-to-visitors ones only while "
      "artifact_display_open_rooms; none: a note and nothing done")
def _():
    s = fort(section([art(1)], [room(10, secure=False)], [disp(50, 10)]))
    props, notes = run(s)
    assert not props and any("shut in by doors" in n for n in notes), notes
    s = fort(section([art(1)], [room(10, visitors=True)], [disp(50, 10)]))
    assert run(s)[0][0].rule == "artifact_display"
    cfg = dict(CFG, artifact_display_open_rooms=False)
    props, notes = [], []
    PA._artifact_rule(s, cfg, props, notes, player_rules(s))
    assert not props


@test("brain: the Rules switch display_artifacts off: nothing proposed (claims still said); the player's furniture "
      "never used; no put-on-display job in this DF: said, nothing proposed")
def _():
    sec = section([art(1, claimed=["the Elves"], name="Gleam")], [room(11)], [disp(51, 11)])
    s = fort(sec, display_artifacts=False)
    assert player_rules(s)["display_artifacts"] is False
    props, notes = run(s)
    assert not props and any("Elves" in n and "Gleam" in n for n in notes), notes
    props, _ = run(fort(section([art(1)], [room(11)], [disp(51, 11, ai=False)], free={"pedestal": 0, "case": 0})))
    assert [p.rule for p in props] == ["artifact_pedestals"]
    props, notes = run(fort(section([art(1)], [room(11)], [disp(51, 11)], api=False)))
    assert not props and any("no put-on-display job" in n for n in notes)


@test("brain: a claimed artifact on display behind doors isn't said again; the player's claimed one is said as left")
def _():
    sec = section([art(1, state="displayed", claimed=["the Elves"])], [room(11)], [disp(51, 11, items=1)])
    sec["artifacts"][0]["building_id"] = 51
    assert run(fort(sec))[1] == []
    props, notes = run(fort(section([art(2, mine=False, claimed=["the Elves"])])))
    assert any("player's" in n for n in notes) and not props


@test("brain: plan() carries the rule; config keys, cooldowns, labels, agenda, the Rules switch in the settings; the "
      "digest line; nothing without the section")
def _():
    s = fort(section([art(1)], [room(11)], [disp(51, 11)]))
    props, _ = plan(s, Memory())
    assert any(p.rule == "artifact_display" for p in props), [p.rule for p in props]
    for r in ("artifact_display", "artifact_furniture", "artifact_pedestals"):
        assert f"{r}_cooldown_ticks" in CFG
    for k in ("artifact_pedestal_holds", "artifact_case_holds", "artifact_display_need_doors",
              "artifact_display_open_rooms", "artifact_pedestals_max", "artifact_pedestal_stone_min"):
        assert k in CFG, k
    import overseer
    import planner_core
    for a in ("place_display", "display_artifact"):
        assert a in overseer.SHORT_WORDS
    assert planner_core.AGENDA_THEMES["artifact_display"] == "show the fort's artifacts"
    settings = (LUA_DIR / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    assert "display_artifacts = true," in settings and "'display_artifacts'," in settings
    assert "display_artifacts = s.display_artifacts," in settings
    sec = section([art(1, claimed=["the Elves"])])
    sec["counts"] = {"total": 3, "mine": 1, "displayed": 1, "displayed_open": 0, "loose": 1, "claimed": 1}
    line = digest.artifacts_line(fort(sec))
    assert line.startswith("ARTIFACTS 3 on the map (1 the AI's)") and "claimed by others 1 (the Elves)" in line, line
    assert digest.artifacts_line(fort()) == ""
    assert "ARTIFACTS" in digest.digest(fort(sec))
    props, notes = plan(fort(), Memory())
    assert not any(p.rule.startswith("artifact_") for p in props)


if LuaRuntime is None:
    finish("these tests need the lupa package (pip install lupa)")
finish()
